"""
vigilancia.py — Que el sistema avise cuando algo anda mal (sin estar mirándolo)

Tres cosas:

1. Los errores quedan guardados y agrupados (tabla sistema_errores): los del
   servidor (cualquier pantalla que revienta) y los de las pantallas (un error
   de JavaScript en el navegador de alguien). El mismo error repetido suma
   «veces» en vez de llenar la lista.

2. Avisos al celular del desarrollador cuando aparece un error nuevo o la base
   deja de responder. Por Telegram o por ntfy, según qué variables de entorno
   estén cargadas en Render:
       AVISOS_TELEGRAM_TOKEN + AVISOS_TELEGRAM_CHAT   (un bot de Telegram)
       AVISOS_NTFY_TEMA                                (la app ntfy, sin cuenta)
   Sin ninguna, todo se guarda igual y se ve en Sistema → Salud del sistema.
   Para no inundar el celular: el mismo error avisa una vez cada 30 minutos y
   en total no más de 15 avisos por hora.

3. /salud: una dirección pública (sin login) que dice si el sistema y la base
   responden. Un vigilante externo gratuito (UptimeRobot, Better Stack) la
   visita cada 5 minutos y avisa si no contesta: así te enterás también de
   las caídas completas, cuando el sistema no puede avisar solo.

Lo que se manda por aviso es lo mínimo (qué falló, dónde, quién): nunca datos
cargados ni contraseñas.

Enganche en app.py:
    from vigilancia import bp_vigilancia, init_vigilancia, registrar_error
    app.register_blueprint(bp_vigilancia)
    init_vigilancia()
"""

import hashlib
import json
import os
import threading
import time
import urllib.request
from collections import deque

from flask import Blueprint, jsonify, request, session

from db_compat import get_connection

bp_vigilancia = Blueprint("vigilancia", __name__)

NOMBRE_SISTEMA = os.environ.get("AVISOS_NOMBRE", "La Santaniana")
AVISO_MISMO_ERROR_SEG = 30 * 60
AVISOS_POR_HORA = 15
VIGIA_CADA_SEG = 5 * 60

_lock = threading.Lock()
_enviados = deque()                 # horas de los avisos de la última hora
_ultimo_aviso_firma = {}            # firma → cuándo se avisó por última vez
_estado = {"arranque": time.time(), "base_ok": None, "base_falla_desde": None,
           "ultimo_chequeo": None, "ultimo_ms": None, "ultimo_aviso": None, "ultimo_aviso_error": None}


# ── La tabla ─────────────────────────────────────────────────────────────────

def init_vigilancia():
    try:
        conn = get_connection()
        clave = "id SERIAL PRIMARY KEY" if _es_pg(conn) else "id INTEGER PRIMARY KEY AUTOINCREMENT"
        conn.execute(f"""CREATE TABLE IF NOT EXISTS sistema_errores (
            {clave},
            firma TEXT UNIQUE, tipo TEXT, ruta TEXT, mensaje TEXT, detalle TEXT, usuario TEXT,
            navegador TEXT, veces INTEGER DEFAULT 1, primera TEXT, ultima TEXT, visto INTEGER DEFAULT 0)""")
        conn.commit()
        conn.close()
    except Exception:
        pass
    _arrancar_vigia()


def _es_pg(conn):
    try:
        from db_compat import USE_POSTGRES
        return USE_POSTGRES
    except Exception:
        return False


def _ahora_txt():
    try:
        from hora_local import ahora
        return ahora().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return time.strftime("%Y-%m-%d %H:%M:%S")


# ── Avisos al celular ────────────────────────────────────────────────────────

def canales():
    """Qué canales de aviso están configurados (sin mostrar las claves)."""
    out = []
    if os.environ.get("AVISOS_TELEGRAM_TOKEN") and os.environ.get("AVISOS_TELEGRAM_CHAT"):
        out.append("telegram")
    if os.environ.get("AVISOS_NTFY_TEMA"):
        out.append("ntfy")
    return out


def _post(url, datos, headers):
    req = urllib.request.Request(url, data=datos, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status


def _enviar(titulo, texto, urgente=False):
    """Manda el aviso por todos los canales configurados. Devuelve los que anduvieron."""
    ok, errores = [], []
    tok, chat = os.environ.get("AVISOS_TELEGRAM_TOKEN"), os.environ.get("AVISOS_TELEGRAM_CHAT")
    if tok and chat:
        try:
            base = os.environ.get("AVISOS_TELEGRAM_URL", "https://api.telegram.org").rstrip("/")
            cuerpo = json.dumps({"chat_id": chat, "text": f"{'🔴' if urgente else '🟡'} {titulo}\n{texto}",
                                 "disable_web_page_preview": True}).encode()
            _post(f"{base}/bot{tok}/sendMessage", cuerpo, {"Content-Type": "application/json"})
            ok.append("telegram")
        except Exception as e:
            errores.append(f"Telegram: {e}")
    tema = os.environ.get("AVISOS_NTFY_TEMA")
    if tema:
        try:
            from urllib.parse import urlencode, quote
            base = os.environ.get("AVISOS_NTFY_URL", "https://ntfy.sh").rstrip("/")
            q = urlencode({"title": titulo, "priority": "high" if urgente else "default",
                           "tags": "rotating_light" if urgente else "warning"})
            _post(f"{base}/{quote(tema)}?{q}", texto.encode("utf-8"), {"Content-Type": "text/plain; charset=utf-8"})
            ok.append("ntfy")
        except Exception as e:
            errores.append(f"ntfy: {e}")
    _estado["ultimo_aviso"] = _ahora_txt() if ok else _estado["ultimo_aviso"]
    _estado["ultimo_aviso_error"] = "; ".join(errores) or None
    return ok, errores


def avisar(titulo, texto, urgente=False, firma=None):
    """Aviso en segundo plano, con freno: el mismo asunto una vez cada 30 min
    y no más de 15 por hora en total."""
    if not canales():
        return False
    ahora = time.time()
    with _lock:
        while _enviados and ahora - _enviados[0] > 3600:
            _enviados.popleft()
        if len(_enviados) >= AVISOS_POR_HORA:
            return False
        if firma and ahora - _ultimo_aviso_firma.get(firma, 0) < AVISO_MISMO_ERROR_SEG:
            return False
        _enviados.append(ahora)
        if firma:
            _ultimo_aviso_firma[firma] = ahora
    threading.Thread(target=_enviar, args=(f"{NOMBRE_SISTEMA}: {titulo}", texto, urgente), daemon=True).start()
    return True


# ── Errores ──────────────────────────────────────────────────────────────────

def _firma(tipo, ruta, mensaje):
    primera = (mensaje or "").strip().splitlines()[0][:300] if mensaje else ""
    # Los números cambian de una vez a otra (ids, cantidades): no separan errores
    import re
    base = re.sub(r"\d+", "#", f"{tipo}|{ruta}|{primera}")
    return hashlib.sha1(base.encode("utf-8", "ignore")).hexdigest()[:20]


def registrar_error(tipo, ruta, mensaje, detalle="", usuario="", navegador=""):
    """Guarda el error (o le suma una vez) y avisa si es nuevo o volvió a pasar.
    Nunca falla: si no puede guardar, solo avisa."""
    ruta = (ruta or "")[:300]
    mensaje = (mensaje or "Error sin mensaje")[:1000]
    detalle = (detalle or "")[-6000:]
    firma = _firma(tipo, ruta, mensaje)
    ahora = _ahora_txt()
    nuevo = True
    veces = 1
    try:
        conn = get_connection()
        try:
            r = conn.execute("SELECT id, veces, visto FROM sistema_errores WHERE firma = ?", (firma,)).fetchone()
            if r:
                nuevo = False
                veces = (r["veces"] or 0) + 1
                conn.execute("""UPDATE sistema_errores SET veces = ?, ultima = ?, detalle = ?, usuario = ?,
                                navegador = ?, visto = 0 WHERE id = ?""",
                             (veces, ahora, detalle, usuario[:80], navegador[:200], r["id"]))
            else:
                conn.execute("""INSERT INTO sistema_errores (firma, tipo, ruta, mensaje, detalle, usuario, navegador,
                                veces, primera, ultima, visto) VALUES (?,?,?,?,?,?,?,1,?,?,0)""",
                             (firma, tipo, ruta, mensaje, detalle, usuario[:80], navegador[:200], ahora, ahora))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass
    que = {"servidor": "Error en el servidor", "pantalla": "Error en una pantalla"}.get(tipo, "Error")
    texto = (f"{'Nuevo' if nuevo else f'Se repitió ({veces} veces)'} · {ruta or '-'}\n"
             f"{mensaje.strip().splitlines()[0][:300] if mensaje.strip() else ''}\n"
             f"Usuario: {usuario or '-'}\nDetalle en Sistema → Salud del sistema")
    avisar(que, texto, urgente=(tipo == "servidor"), firma=firma)


# ── El vigía de la base ──────────────────────────────────────────────────────

def chequear_base():
    """¿La base contesta? Devuelve (ok, milisegundos, error)."""
    t = time.time()
    try:
        conn = get_connection()
        try:
            conn.execute("SELECT 1 AS n").fetchone()
        finally:
            conn.close()
        return True, round((time.time() - t) * 1000), None
    except Exception as e:
        return False, round((time.time() - t) * 1000), str(e)[:300]


def _vigia():
    fallas = 0
    while True:
        time.sleep(VIGIA_CADA_SEG)
        ok, ms, err = chequear_base()
        _estado["ultimo_chequeo"], _estado["ultimo_ms"] = _ahora_txt(), ms
        if ok:
            if _estado["base_ok"] is False and fallas >= 2:
                desde = _estado["base_falla_desde"] or "?"
                avisar("La base volvió a responder", f"Estuvo sin responder desde {desde}.", firma="base-volvio")
            fallas = 0
            _estado["base_ok"], _estado["base_falla_desde"] = True, None
        else:
            fallas += 1
            if _estado["base_falla_desde"] is None:
                _estado["base_falla_desde"] = _ahora_txt()
            _estado["base_ok"] = False
            if fallas == 2:            # dos chequeos seguidos: no es un parpadeo
                avisar("La base de datos no responde",
                       f"Hace unos 10 minutos que no contesta.\n{err or ''}", urgente=True, firma="base-caida")


def _arrancar_vigia():
    if os.environ.get("VIGIA", "1") == "0" or getattr(_arrancar_vigia, "_hecho", False):
        return
    _arrancar_vigia._hecho = True
    # Con varios procesos de gunicorn, vigila uno solo (el que toma el candado)
    try:
        import fcntl
        f = open("/tmp/santaniana-vigia.lock", "w")
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _arrancar_vigia._f = f
    except Exception:
        return
    threading.Thread(target=_vigia, daemon=True).start()


# ── Rutas ────────────────────────────────────────────────────────────────────

@bp_vigilancia.route("/salud", methods=["GET", "HEAD"])
def salud():
    """Para el vigilante externo: 200 si el sistema y la base responden, 503 si no."""
    ok, ms, _ = chequear_base()
    return jsonify({"ok": ok, "base": "ok" if ok else "sin respuesta", "ms": ms}), (200 if ok else 503)


_por_sesion = {}


@bp_vigilancia.route("/api/sistema/error_pantalla", methods=["POST"])
def api_error_pantalla():
    """Un error de JavaScript en el navegador de alguien (lo manda app.js)."""
    quien = session.get("usuario") or "-"
    ahora = time.time()
    lista = [t for t in _por_sesion.get(quien, []) if ahora - t < 60]
    if len(lista) >= 10:
        return jsonify({"ok": True})
    lista.append(ahora)
    _por_sesion[quien] = lista
    d = request.get_json(silent=True) or {}
    msg = str(d.get("mensaje") or "")[:600]
    if not msg or msg in ("Script error.", "ResizeObserver loop limit exceeded",
                          "ResizeObserver loop completed with undelivered notifications."):
        return jsonify({"ok": True})
    donde = f"pantalla: {str(d.get('seccion') or '-')[:60]}"
    detalle = f"{str(d.get('fuente') or '')[:300]}:{d.get('linea') or ''}:{d.get('columna') or ''}\n{str(d.get('pila') or '')[:4000]}"
    registrar_error("pantalla", donde, msg, detalle, quien, request.headers.get("User-Agent", "")[:200])
    return jsonify({"ok": True})


def _solo_admin():
    return session.get("rol") == "admin"


@bp_vigilancia.route("/api/sistema/salud", methods=["GET"])
def api_sistema_salud():
    if not _solo_admin():
        return jsonify({"error": "Solo administración"}), 403
    ok, ms, err = chequear_base()
    errores = []
    try:
        conn = get_connection()
        try:
            errores = [dict(r) for r in conn.execute(
                """SELECT id, tipo, ruta, mensaje, detalle, usuario, navegador, veces, primera, ultima, visto
                   FROM sistema_errores ORDER BY visto ASC, ultima DESC LIMIT 200""").fetchall()]
        finally:
            conn.close()
    except Exception:
        pass
    return jsonify({
        "base": {"ok": ok, "ms": ms, "error": err},
        "canales": canales(),
        "vigia": {"ultimo_chequeo": _estado["ultimo_chequeo"], "ultimo_ms": _estado["ultimo_ms"],
                  "base_ok": _estado["base_ok"], "falla_desde": _estado["base_falla_desde"]},
        "ultimo_aviso": _estado["ultimo_aviso"], "ultimo_aviso_error": _estado["ultimo_aviso_error"],
        "arranque_hace_min": round((time.time() - _estado["arranque"]) / 60),
        "url_salud": (("https://" + request.host) if request.headers.get("X-Forwarded-Proto", "") == "https" or request.host.endswith(".onrender.com")
                      else request.host_url.rstrip("/")) + "/salud",
        "errores": errores,
        "sin_ver": sum(1 for e in errores if not e.get("visto")),
    })


@bp_vigilancia.route("/api/sistema/errores/<int:eid>/visto", methods=["POST"])
def api_error_visto(eid):
    if not _solo_admin():
        return jsonify({"error": "Solo administración"}), 403
    conn = get_connection()
    try:
        conn.execute("UPDATE sistema_errores SET visto = 1 WHERE id = ?", (eid,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})


@bp_vigilancia.route("/api/sistema/errores/vistos", methods=["POST"])
def api_errores_todos_vistos():
    if not _solo_admin():
        return jsonify({"error": "Solo administración"}), 403
    conn = get_connection()
    try:
        conn.execute("UPDATE sistema_errores SET visto = 1 WHERE visto = 0")
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True})


@bp_vigilancia.route("/api/sistema/probar_aviso", methods=["POST"])
def api_probar_aviso():
    if not _solo_admin():
        return jsonify({"error": "Solo administración"}), 403
    if not canales():
        return jsonify({"ok": False, "msg": "No hay ningún canal configurado todavía (mirá los pasos de abajo)."})
    ok, errores = _enviar(f"{NOMBRE_SISTEMA}: aviso de prueba",
                          f"Si te llegó esto, los avisos funcionan. Enviado por {session.get('usuario', '-')}.")
    if ok:
        return jsonify({"ok": True, "msg": f"Aviso enviado por {', '.join(ok)}. Revisá el celular."})
    return jsonify({"ok": False, "msg": "No se pudo enviar: " + "; ".join(errores)})


def sin_ver():
    """Para la consola: cuántos errores hay sin mirar."""
    try:
        conn = get_connection()
        try:
            r = conn.execute("SELECT COUNT(*) AS n FROM sistema_errores WHERE visto = 0").fetchone()
            return r["n"] if r else 0
        finally:
            conn.close()
    except Exception:
        return None
