"""
integraciones.py — Avisarle a otro sistema cuando pasa algo (La Santaniana)

La otra mitad de las integraciones: en vez de que el otro sistema venga a
preguntar (la API, api_externa.py), el sistema le avisa solo. En la pantalla
Sistema → Integraciones se pega el link del otro sistema (o de Make, Zapier,
n8n, un Apps Script de Google…) y se marca cuándo avisar.

  · Eventos: OT abierta, OT cerrada, falla reportada por un chofer, carga de
    combustible, rendición de corporativos, tráfico publicado.
  · Cada aviso es un POST con JSON:
        {"evento": "ot.cerrada", "id": "…", "momento": "2026-11-06T18:40:00",
         "sistema": "La Santaniana", "datos": {…la OT, la carga, etc.…}}
  · Va firmado: encabezado X-Santaniana-Firma: sha256=<HMAC del cuerpo con el
    secreto del aviso>. El otro sistema puede comprobar que viene de acá.
  · Se manda por detrás (el que cierra la OT no espera) y se reintenta 3 veces
    (al toque, a los 10 s y al minuto). Cada envío queda anotado con lo que
    respondió el otro lado. Si falla 30 veces seguidas, el aviso se pausa solo.
  · No se puede apuntar a direcciones internas (localhost, 10.x, 192.168.x…).

Enganche en app.py:
    from integraciones import bp_integraciones, init_integraciones
    init_integraciones()
    app.register_blueprint(bp_integraciones)
Y donde pasa cada cosa (nunca tira error, nunca demora):
    from integraciones import avisar
    avisar("ot.cerrada", ot_id=123)
"""

import hashlib
import hmac
import ipaddress
import json
import os
import secrets
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlparse

from flask import Blueprint, request, jsonify, session
from db_compat import get_connection, USE_POSTGRES

from hora_local import ahora_iso

bp_integraciones = Blueprint("integraciones", __name__)

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"

EVENTOS = [
    ("ot.abierta",          "Se abre una OT",                  "La OT con el coche, el km y sus ítems"),
    ("ot.cerrada",          "Se cierra una OT",                "La OT completa, con lo que se hizo, quién y el costo"),
    ("falla.reportada",     "Un chofer reporta una falla",     "El coche, lo que escribió el chofer y el km"),
    ("combustible.cargado", "Se registra una carga de combustible", "Coche, litros, precio, odómetro y estación"),
    ("rendicion.cargada",   "Un chofer corporativo rinde un servicio", "Cliente, tramo, chofer, horario, km y monto"),
    ("trafico.publicado",   "Se publica el tráfico del día",   "Todas las salidas con coche y tripulantes, y qué cambió"),
    ("asignacion.publicada", "Se publica la asignación de corporativos", "Cada servicio con chofer y coche, y qué cambió"),
]
CODIGOS = {e[0] for e in EVENTOS}
REINTENTOS = (0, 10, 60)          # segundos de espera antes de cada intento
PAUSA_TRAS_FALLOS = 30
TIEMPO_MAX = 10                   # segundos que se espera la respuesta del otro lado


def init_integraciones():
    conn = get_connection()
    try:
        for sql in (
            f"""CREATE TABLE IF NOT EXISTS integ_avisos (
                id {PK},
                nombre TEXT NOT NULL,
                url TEXT NOT NULL,
                eventos TEXT DEFAULT '[]',
                secreto TEXT NOT NULL,
                activo INTEGER DEFAULT 1,
                creado_el TEXT DEFAULT '',
                creado_por TEXT DEFAULT '',
                ultimo_envio TEXT DEFAULT '',
                ultimo_estado INTEGER DEFAULT 0,
                ultimo_error TEXT DEFAULT '',
                enviados INTEGER DEFAULT 0,
                fallidos INTEGER DEFAULT 0,
                fallos_seguidos INTEGER DEFAULT 0)""",
            f"""CREATE TABLE IF NOT EXISTS integ_envios (
                id {PK},
                aviso_id INTEGER,
                evento TEXT DEFAULT '',
                momento TEXT DEFAULT '',
                ok INTEGER DEFAULT 0,
                estado INTEGER DEFAULT 0,
                intentos INTEGER DEFAULT 0,
                respuesta TEXT DEFAULT '',
                resumen TEXT DEFAULT '')""",
            "CREATE INDEX IF NOT EXISTS idx_integ_envios_aviso ON integ_envios (aviso_id, id)",
        ):
            conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════
#  Qué se manda en cada evento
# ════════════════════════════════════════════════════════════════════════

def _datos_del_evento(evento, ref):
    import api_externa as A
    if evento in ("ot.abierta", "ot.cerrada"):
        return A.una_ot(int(ref["ot_id"]))
    if evento == "combustible.cargado":
        return A.una_carga(int(ref["carga_id"]))
    if evento == "rendicion.cargada":
        if ref.get("rendicion_id"):
            return A.una_rendicion(int(ref["rendicion_id"]))
        conn = get_connection()
        try:
            f = conn.execute("""SELECT id FROM rendiciones_corp WHERE chofer_usuario=? AND fecha_servicio=?
                                AND tramo=? AND cliente=? ORDER BY id DESC LIMIT 1""",
                             (ref.get("chofer_usuario", ""), ref.get("fecha_servicio", ""),
                              ref.get("tramo", ""), ref.get("cliente", ""))).fetchone()
        finally:
            conn.close()
        return A.una_rendicion(f["id"]) if f else None
    if evento == "trafico.publicado":
        return A.trafico_publicado(ref["fecha"], ref.get("tipo") or "nacional")
    if evento == "asignacion.publicada":
        return A.asignacion_publicada(ref["fecha"])
    if evento == "falla.reportada":
        conn = get_connection()
        try:
            v = conn.execute("SELECT n_interno, patente FROM vehiculos WHERE id=?",
                             (int(ref["vehiculo_id"]),)).fetchone()
        finally:
            conn.close()
        return {"pedido": ref.get("pedido"), "coche": v["n_interno"] if v else "", "patente": v["patente"] if v else "",
                "vehiculo_id": ref.get("vehiculo_id"), "chofer": ref.get("chofer", ""), "km": ref.get("km"),
                "problemas": ref.get("problemas") or []}
    if evento == "prueba":
        return {"mensaje": "Aviso de prueba desde La Santaniana. Si ves esto, la integración funciona."}
    return dict(ref)


def _resumen(evento, datos):
    """Una línea para el registro de envíos."""
    d = datos or {}
    if evento.startswith("ot."):
        return f"OT {d.get('id')} · coche {d.get('coche')}"
    if evento == "combustible.cargado":
        return f"Coche {d.get('coche')} · {d.get('litros')} L"
    if evento == "rendicion.cargada":
        return f"{d.get('cliente')} · {d.get('tramo')} · {d.get('chofer_nombre')}"
    if evento == "trafico.publicado":
        return f"{d.get('fecha')} {d.get('tipo')} · versión {d.get('version')} · {len(d.get('salidas') or [])} salidas"
    if evento == "asignacion.publicada":
        return f"Corporativos {d.get('fecha')} · versión {d.get('version')} · {len(d.get('servicios') or [])} servicios"
    if evento == "falla.reportada":
        return f"Coche {d.get('coche')} · {d.get('chofer')}"
    return evento


# ════════════════════════════════════════════════════════════════════════
#  Envío
# ════════════════════════════════════════════════════════════════════════

def url_segura(url):
    """(ok, motivo). Solo http/https a direcciones públicas."""
    try:
        p = urlparse(url)
    except ValueError:
        return False, "El link no es válido."
    if p.scheme not in ("http", "https") or not p.hostname:
        return False, "El link tiene que empezar con https:// (o http://)."
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80))
    except socket.gaierror:
        return False, f"No se encuentra el servidor «{p.hostname}». Revisá el link."
    if os.environ.get("INTEG_PERMITIR_LOCAL") == "1":   # solo para probar en una compu, nunca en Render
        return True, ""
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False, "Ese link apunta a una dirección interna; tiene que ser un servidor de internet."
    return True, ""


def _firmar(secreto, cuerpo):
    return "sha256=" + hmac.new(secreto.encode("utf-8"), cuerpo, hashlib.sha256).hexdigest()


def _un_intento(aviso, evento, cuerpo):
    ok, motivo = url_segura(aviso["url"])
    if not ok:
        return False, 0, motivo
    req = urllib.request.Request(aviso["url"], data=cuerpo, method="POST", headers={
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": "LaSantaniana-Integraciones/1.0",
        "X-Santaniana-Evento": evento,
        "X-Santaniana-Firma": _firmar(aviso["secreto"], cuerpo),
    })
    try:
        with urllib.request.urlopen(req, timeout=TIEMPO_MAX) as r:
            return 200 <= r.status < 300, r.status, r.read(300).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        try:
            txt = e.read(300).decode("utf-8", "replace")
        except Exception:
            txt = ""
        return False, e.code, txt or str(e.reason)
    except Exception as e:
        return False, 0, _error_claro(e)


def _error_claro(e):
    """El error de red en palabras de la oficina."""
    txt = str(getattr(e, "reason", "") or e)
    bajo = txt.lower()
    if "timed out" in bajo or isinstance(e, TimeoutError) or isinstance(getattr(e, "reason", None), TimeoutError):
        return f"El otro sistema tardó más de {TIEMPO_MAX} segundos en contestar."
    if "refused" in bajo:
        return "El otro sistema no está atendiendo (rechazó la conexión)."
    if "certificate" in bajo or "ssl" in bajo:
        return "El certificado de seguridad del otro sistema no es válido."
    if "name or service" in bajo or "getaddrinfo" in bajo or "nodename" in bajo:
        return "No se encuentra el servidor del link. Revisá que esté bien escrito."
    return f"No se pudo conectar: {txt}"[:300]


def _anotar(aviso_id, evento, ok, estado, intentos, respuesta, resumen):
    try:
        conn = get_connection()
        try:
            momento = ahora_iso()
            conn.execute("""INSERT INTO integ_envios (aviso_id, evento, momento, ok, estado, intentos, respuesta, resumen)
                            VALUES (?,?,?,?,?,?,?,?)""",
                         (aviso_id, evento, momento, 1 if ok else 0, estado, intentos, (respuesta or "")[:300],
                          (resumen or "")[:200]))
            if evento != "prueba":
                if ok:
                    conn.execute("""UPDATE integ_avisos SET ultimo_envio=?, ultimo_estado=?, ultimo_error='',
                                    enviados=COALESCE(enviados,0)+1, fallos_seguidos=0 WHERE id=?""",
                                 (momento, estado, aviso_id))
                else:
                    conn.execute("""UPDATE integ_avisos SET ultimo_envio=?, ultimo_estado=?, ultimo_error=?,
                                    fallidos=COALESCE(fallidos,0)+1, fallos_seguidos=COALESCE(fallos_seguidos,0)+1
                                    WHERE id=?""", (momento, estado, (respuesta or "")[:300], aviso_id))
                    conn.execute(f"""UPDATE integ_avisos SET activo=0,
                                     ultimo_error='Pausado solo: falló {PAUSA_TRAS_FALLOS} veces seguidas. ' || COALESCE(ultimo_error,'')
                                     WHERE id=? AND fallos_seguidos >= ?""", (aviso_id, PAUSA_TRAS_FALLOS))
            # Se guardan los últimos 200 envíos de cada aviso
            conn.execute("""DELETE FROM integ_envios WHERE aviso_id=? AND id NOT IN
                            (SELECT id FROM integ_envios WHERE aviso_id=? ORDER BY id DESC LIMIT 200)""",
                         (aviso_id, aviso_id))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass
    _olvidar_cache()


def _entregar(aviso, evento, cuerpo, resumen, reintentar=True):
    pausas = REINTENTOS if reintentar else (0,)
    ok, estado, resp = False, 0, ""
    n = 0
    for espera in pausas:
        if espera:
            time.sleep(espera)
        n += 1
        ok, estado, resp = _un_intento(aviso, evento, cuerpo)
        # Un 4xx (salvo 408/429) es que el otro lado no lo quiere: no se insiste
        if ok or (400 <= estado < 500 and estado not in (408, 429)):
            break
    _anotar(aviso["id"], evento, ok, estado, n, resp, resumen)
    return ok, estado, resp


def _sobre(evento, datos):
    return json.dumps({"evento": evento, "id": uuid.uuid4().hex, "momento": ahora_iso(),
                       "sistema": "La Santaniana", "datos": datos}, ensure_ascii=False, default=str).encode("utf-8")


# Cache de los avisos activos: cada OT que se cierra no tiene que ir a la base
# a preguntar si hay alguien escuchando.
_cache = {"t": 0, "avisos": None}
_candado = threading.Lock()


def _olvidar_cache():
    with _candado:
        _cache["t"] = 0


def _activos():
    with _candado:
        if _cache["avisos"] is not None and time.monotonic() - _cache["t"] < 30:
            return _cache["avisos"]
    conn = get_connection()
    try:
        filas = [dict(f) for f in conn.execute("SELECT * FROM integ_avisos WHERE activo=1").fetchall()]
    finally:
        conn.close()
    with _candado:
        _cache.update(t=time.monotonic(), avisos=filas)
    return filas


def avisar(evento, **ref):
    """Avisa a los sistemas que escuchan ese evento. No demora (va por detrás)
    y nunca tira error: una integración caída no puede trabar el taller."""
    try:
        interesados = [a for a in _activos() if evento in (json.loads(a["eventos"] or "[]"))]
        if not interesados:
            return
        threading.Thread(target=_mandar, args=(evento, ref, interesados), daemon=True).start()
    except Exception:
        pass


def _mandar(evento, ref, interesados):
    if evento == "ot.abierta":
        time.sleep(3)      # los ítems de la OT se cargan justo después de crearla
    try:
        datos = _datos_del_evento(evento, ref)
    except Exception:
        datos = None
    if datos is None:
        return
    cuerpo = _sobre(evento, datos)
    resumen = _resumen(evento, datos)
    for a in interesados:
        try:
            _entregar(a, evento, cuerpo, resumen)
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════════
#  Pantalla (con sesión, solo admin)
# ════════════════════════════════════════════════════════════════════════

def _admin():
    return session.get("rol") == "admin"


def _quien():
    return session.get("nombre") or session.get("usuario") or "?"


def _auditar(accion, detalle=""):
    try:
        from database import registrar_auditoria
        registrar_auditoria(usuario=_quien(), rol=session.get("rol") or "", accion=accion,
                            categoria="Sistema", detalle=detalle)
    except Exception:
        pass


def _publico(f):
    try:
        ev = [e for e in json.loads(f["eventos"] or "[]") if e in CODIGOS]
    except ValueError:
        ev = []
    return {"id": f["id"], "nombre": f["nombre"], "url": f["url"], "eventos": ev, "activo": bool(f["activo"]),
            "secreto": f["secreto"], "creado_el": f["creado_el"], "creado_por": f["creado_por"],
            "ultimo_envio": f["ultimo_envio"] or "", "ultimo_estado": f["ultimo_estado"] or 0,
            "ultimo_error": f["ultimo_error"] or "", "enviados": f["enviados"] or 0, "fallidos": f["fallidos"] or 0}


@bp_integraciones.route("/api/integ/avisos")
def api_avisos():
    if not _admin():
        return jsonify({"error": "Solo administración"}), 403
    conn = get_connection()
    try:
        filas = conn.execute("SELECT * FROM integ_avisos ORDER BY activo DESC, id DESC").fetchall()
    finally:
        conn.close()
    return jsonify({"avisos": [_publico(f) for f in filas],
                    "eventos": [{"codigo": c, "nombre": n, "detalle": d} for c, n, d in EVENTOS]})


def _leer_form():
    d = request.get_json(silent=True) or {}
    nombre = str(d.get("nombre") or "").strip()[:80]
    url = str(d.get("url") or "").strip()[:500]
    eventos = [e for e in (d.get("eventos") or []) if e in CODIGOS]
    if not nombre:
        return None, "Poné un nombre (ej.: Contabilidad, Make – WhatsApp al jefe)."
    if not url:
        return None, "Pegá el link del otro sistema."
    ok, motivo = url_segura(url)
    if not ok:
        return None, motivo
    if not eventos:
        return None, "Marcá al menos un evento."
    return {"nombre": nombre, "url": url, "eventos": eventos}, None


@bp_integraciones.route("/api/integ/avisos", methods=["POST"])
def api_crear_aviso():
    if not _admin():
        return jsonify({"error": "Solo administración"}), 403
    f, err = _leer_form()
    if err:
        return jsonify({"ok": False, "error": err}), 400
    secreto = "whsec_" + secrets.token_urlsafe(24)
    conn = get_connection()
    try:
        cur = conn.execute("""INSERT INTO integ_avisos (nombre, url, eventos, secreto, activo, creado_el, creado_por)
                              VALUES (?,?,?,?,1,?,?)""",
                           (f["nombre"], f["url"], json.dumps(f["eventos"]), secreto, ahora_iso(), _quien()))
        conn.commit()
        aid = cur.lastrowid
    finally:
        conn.close()
    _olvidar_cache()
    _auditar(f"Creó la integración «{f['nombre']}»", f"{f['url']} · {', '.join(f['eventos'])}")
    return jsonify({"ok": True, "id": aid, "secreto": secreto})


@bp_integraciones.route("/api/integ/avisos/<int:aid>", methods=["POST"])
def api_editar_aviso(aid):
    if not _admin():
        return jsonify({"error": "Solo administración"}), 403
    d = request.get_json(silent=True) or {}
    conn = get_connection()
    try:
        f = conn.execute("SELECT * FROM integ_avisos WHERE id=?", (aid,)).fetchone()
        if not f:
            return jsonify({"ok": False, "error": "Esa integración no existe."}), 404
        if "activo" in d and len(d) == 1:
            conn.execute("UPDATE integ_avisos SET activo=?, fallos_seguidos=0 WHERE id=?",
                         (1 if d["activo"] else 0, aid))
            accion = "Reactivó" if d["activo"] else "Pausó"
        else:
            nuevo, err = _leer_form()
            if err:
                return jsonify({"ok": False, "error": err}), 400
            conn.execute("UPDATE integ_avisos SET nombre=?, url=?, eventos=? WHERE id=?",
                         (nuevo["nombre"], nuevo["url"], json.dumps(nuevo["eventos"]), aid))
            accion = "Editó"
        conn.commit()
    finally:
        conn.close()
    _olvidar_cache()
    _auditar(f"{accion} la integración «{f['nombre']}»")
    return jsonify({"ok": True})


@bp_integraciones.route("/api/integ/avisos/<int:aid>/borrar", methods=["POST"])
def api_borrar_aviso(aid):
    if not _admin():
        return jsonify({"error": "Solo administración"}), 403
    conn = get_connection()
    try:
        f = conn.execute("SELECT nombre FROM integ_avisos WHERE id=?", (aid,)).fetchone()
        if not f:
            return jsonify({"ok": False, "error": "Esa integración no existe."}), 404
        conn.execute("DELETE FROM integ_envios WHERE aviso_id=?", (aid,))
        conn.execute("DELETE FROM integ_avisos WHERE id=?", (aid,))
        conn.commit()
    finally:
        conn.close()
    _olvidar_cache()
    _auditar(f"Borró la integración «{f['nombre']}»")
    return jsonify({"ok": True})


@bp_integraciones.route("/api/integ/probar", methods=["POST"])
def api_probar():
    """Manda un aviso de prueba al toque y devuelve lo que contestó el otro
    lado. Sirve con un aviso ya guardado (id) o con un link recién pegado."""
    if not _admin():
        return jsonify({"error": "Solo administración"}), 403
    d = request.get_json(silent=True) or {}
    if d.get("id"):
        conn = get_connection()
        try:
            f = conn.execute("SELECT * FROM integ_avisos WHERE id=?", (int(d["id"]),)).fetchone()
        finally:
            conn.close()
        if not f:
            return jsonify({"ok": False, "error": "Esa integración no existe."}), 404
        aviso = dict(f)
    else:
        url = str(d.get("url") or "").strip()
        ok, motivo = url_segura(url)
        if not ok:
            return jsonify({"ok": False, "error": motivo}), 400
        aviso = {"id": None, "url": url, "secreto": "whsec_prueba"}
    evento = d.get("evento") if d.get("evento") in CODIGOS else "prueba"
    datos = _ejemplo(evento)
    cuerpo = _sobre(evento, datos)
    if aviso["id"]:
        ok, estado, resp = _entregar(aviso, "prueba", cuerpo, f"Prueba: {evento}", reintentar=False)
    else:
        ok, estado, resp = _un_intento(aviso, evento, cuerpo)
    return jsonify({"ok": ok, "estado": estado, "respuesta": (resp or "")[:300],
                    "mandado": json.loads(cuerpo.decode("utf-8"))})


def _ejemplo(evento):
    """Para probar: un caso real del sistema (la última OT, la última carga…)
    o, si no hay, el mensaje de prueba."""
    try:
        conn = get_connection()
        try:
            if evento in ("ot.abierta", "ot.cerrada"):
                f = conn.execute("SELECT id FROM ordenes_trabajo ORDER BY id DESC LIMIT 1").fetchone()
                ref = {"ot_id": f["id"]} if f else None
            elif evento == "combustible.cargado":
                f = conn.execute("SELECT id FROM combustible ORDER BY id DESC LIMIT 1").fetchone()
                ref = {"carga_id": f["id"]} if f else None
            elif evento == "rendicion.cargada":
                f = conn.execute("SELECT id FROM rendiciones_corp ORDER BY id DESC LIMIT 1").fetchone()
                ref = {"rendicion_id": f["id"]} if f else None
            elif evento == "trafico.publicado":
                f = conn.execute("""SELECT fecha, tipo FROM trafico_dias WHERE COALESCE(version,0)>0
                                    ORDER BY fecha DESC LIMIT 1""").fetchone()
                ref = {"fecha": f["fecha"], "tipo": f["tipo"]} if f else None
            elif evento == "asignacion.publicada":
                f = conn.execute("""SELECT fecha FROM corp_asig_dias WHERE COALESCE(version,0)>0
                                    ORDER BY fecha DESC LIMIT 1""").fetchone()
                ref = {"fecha": f["fecha"]} if f else None
            elif evento == "falla.reportada":
                f = conn.execute("SELECT id FROM vehiculos WHERE activo=1 ORDER BY id LIMIT 1").fetchone()
                ref = {"vehiculo_id": f["id"], "pedido": 0, "chofer": "Chofer de prueba", "km": 0,
                       "problemas": [{"descripcion": "Ejemplo: no anda el aire", "tipo": "correctivo"}]} if f else None
            else:
                ref = None
        finally:
            conn.close()
        if ref:
            datos = _datos_del_evento(evento, ref)
            if datos:
                return datos
    except Exception:
        pass
    return _datos_del_evento("prueba", {})


@bp_integraciones.route("/api/integ/avisos/<int:aid>/envios")
def api_envios(aid):
    if not _admin():
        return jsonify({"error": "Solo administración"}), 403
    conn = get_connection()
    try:
        filas = conn.execute("""SELECT momento, evento, ok, estado, intentos, respuesta, resumen FROM integ_envios
                                WHERE aviso_id=? ORDER BY id DESC LIMIT 50""", (aid,)).fetchall()
    finally:
        conn.close()
    return jsonify({"envios": [dict(f) | {"ok": bool(f["ok"])} for f in filas]})
