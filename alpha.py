"""
alpha.py — Lo que Alpha (la venta de pasajes) toma del tráfico (La Santaniana)

Alpha no inventa los servicios: salen del tráfico de cada día, nacional e
internacional. De ahí saca, para cada corredor (Concepción, Pedro Juan,
Buenos Aires...), las salidas de ida y de regreso con su hora, el tramo tal
como lo escriben, el coche asignado y la tripulación.

  - Si el tráfico de ese día ya está armado (publicado o no), se usa tal cual.
  - Si todavía no se armó (se venden pasajes para mañana o pasado), se toman
    los horarios del último tráfico del mismo día de la semana. El coche queda
    "a confirmar" y se muestra el que suele hacer esa salida, para saber qué
    plano de asientos vender.

La configuración de Alpha sí va a la base (tabla alpha_config, un JSON por
tema), porque es real y la usan todas las computadoras:

  - planos: el plano de asientos de cada modelo de coche (pisos, filas, clase)
  - coche_plano: qué plano usa cada coche (si no está, se deduce del modelo)
  - recorridos: las paradas de cada corredor, en orden de ida (puede haber
    más de un recorrido: "X 25", "X CHACO")
  - tarifas: el precio de cada tramo entre dos paradas, en diferencial y cama
  - descuentos: menor (hasta 8 años), jubilado...

Las ventas siguen siendo de prueba y quedan en el navegador (falta lo fiscal).
Todo es solo para administración.

Enganche en app.py:
    from alpha import bp_alpha, init_alpha
    init_alpha()
    app.register_blueprint(bp_alpha)
"""

import json
import re
from datetime import date, timedelta

from flask import Blueprint, jsonify, session, request

from db_compat import get_connection, USE_POSTGRES
from hora_local import ahora_iso
import trafico as tr

bp_alpha = Blueprint("alpha", __name__)

# Cómo se muestra cada lugar en la pantalla y en el boleto
NOMBRES = {
    "ASU": "Asunción", "COP": "Concepción", "LOT": "Loreto", "PJC": "Pedro Juan Caballero",
    "CDE": "Ciudad del Este", "ATQ": "Antequera", "SAN PEDRO": "San Pedro", "TACUATI": "Tacuatí",
    "SAN VICENTE": "San Vicente", "VILLARRICA": "Villarrica", "CARAPEGUA": "Carapeguá",
    "ROQUE GONZALEZ": "Roque González", "RETIRO": "Retiro", "LA PLATA": "La Plata",
    "LA NORIA": "La Noria", "SAN JUSTO": "San Justo", "LINIERS": "Liniers",
    "BUENOS AIRES": "Buenos Aires", "CLORINDA": "Clorinda",
}
SEMANAS_ATRAS = 5          # hasta cuántas semanas atrás se busca un tráfico de referencia
DIAS_HABITUAL = 21         # para el coche que suele hacer cada salida


def nombre_lugar(sigla):
    s = str(sigla or "").strip()
    if not s:
        return ""
    return NOMBRES.get(s.upper()) or s.title()


def _hora_ok(h):
    return bool(re.fullmatch(r"\d{2}:\d{2}", str(h or "")))


def _coche(txt):
    """El número interno si es un número; 'A CONF' y vacíos no son coche."""
    t = str(txt or "").strip()
    return t if re.fullmatch(r"\d{2,6}", t) else ""


def _salidas_de(conn, dia_id):
    return [dict(r) for r in conn.execute("""
        SELECT s.id, s.lado, s.hora, s.destino, s.coche, s.trip1, s.trip2, s.nota,
               b.nombre AS corredor, b.orden
        FROM trafico_salidas s JOIN trafico_bloques b ON b.id = s.bloque_id
        WHERE s.dia_id = ? ORDER BY b.orden, b.id, s.lado, s.hora, s.id""", (dia_id,)).fetchall()]


def _con_salidas(conn, dia_id):
    r = conn.execute("SELECT COUNT(*) AS n FROM trafico_salidas WHERE dia_id=?", (dia_id,)).fetchone()
    return int(r["n"] or 0) > 0


def _referencia(conn, fecha, tipo):
    """Un tráfico ya armado para tomar los horarios: el último del mismo día
    de la semana; si no hay, el último que haya antes de esa fecha. Una sola
    consulta (con la base lejos, cada ida y vuelta cuesta)."""
    f = date.fromisoformat(fecha)
    desde = (f - timedelta(days=7 * SEMANAS_ATRAS + 30)).isoformat()
    filas = [dict(r) for r in conn.execute("""
        SELECT d.*, (SELECT COUNT(*) FROM trafico_salidas s WHERE s.dia_id = d.id) AS n
        FROM trafico_dias d WHERE COALESCE(d.tipo,'nacional') = ? AND d.fecha < ? AND d.fecha >= ?
        ORDER BY d.fecha DESC""", (tipo, fecha, desde)).fetchall()]
    con = [x for x in filas if int(x.get("n") or 0) > 0]
    for x in con:
        k = (f - date.fromisoformat(x["fecha"])).days
        if k % 7 == 0 and k // 7 <= SEMANAS_ATRAS:
            return x
    return con[0] if con else None


def _habituales(conn, fecha, tipo):
    """(corredor, lado, hora) → el último coche que hizo esa salida."""
    desde = (date.fromisoformat(fecha) - timedelta(days=DIAS_HABITUAL)).isoformat()
    out = {}
    for r in conn.execute("""
        SELECT d.fecha, b.nombre AS corredor, s.lado, s.hora, s.coche
        FROM trafico_salidas s JOIN trafico_dias d ON d.id = s.dia_id
        JOIN trafico_bloques b ON b.id = s.bloque_id
        WHERE COALESCE(d.tipo,'nacional') = ? AND d.fecha >= ? AND d.fecha <= ?
        ORDER BY d.fecha""", (tipo, desde, fecha)).fetchall():
        c = _coche(r["coche"])
        if c:
            out[(tr._sin_tildes(tr.limpiar(r["corredor"])), r["lado"], r["hora"])] = c
    return out


def _tripulacion(s):
    """Los tripulantes escritos. 'CHOFER 21027' es cómo marcan que va el
    chofer fijo de ese coche: se muestra tal cual."""
    return [t.strip() for t in (s.get("trip1"), s.get("trip2")) if t and t.strip()]


def dia_para_alpha(fecha):
    conn = get_connection()
    try:
        flota = tr._flota(conn)

        def modelo(c):
            v = flota.get(c)
            return " ".join(x for x in ((v or {}).get("marca"), (v or {}).get("modelo")) if x).strip() if v else ""

        corredores = []
        for tipo in ("nacional", "internacional"):
            d = tr._dia_por_fecha(conn, fecha, tipo)
            fuente = {"tipo": tipo}
            if d and _con_salidas(conn, d["id"]):
                filas = _salidas_de(conn, d["id"])
                version = int(d.get("version") or 0)
                fuente.update(estado=("publicado" if version and not int(d.get("modificado") or 0)
                                      else "cambios" if version else "borrador"),
                              version=version, publicado_el=d.get("publicado_el") or "")
                es_ref = False
            else:
                ref = _referencia(conn, fecha, tipo)
                if not ref:
                    continue
                filas = _salidas_de(conn, ref["id"])
                fuente.update(estado="referencia", fecha_ref=ref["fecha"])
                es_ref = True
            hab = _habituales(conn, fecha, tipo)

            por = {}
            for s in filas:
                if not _hora_ok(s["hora"]) or s["lado"] not in tr.LADOS:
                    continue
                corr = (s["corredor"] or "").strip()
                clave_corr = tr._sin_tildes(tr.limpiar(corr))
                c = por.get(clave_corr)
                if c is None:
                    lugar = (tr._lugar_ar(corr) or "BUENOS AIRES") if tipo == "internacional" else tr.lugar_del_corredor(corr)
                    c = por[clave_corr] = {
                        "clave": f"{tipo}|{clave_corr}", "tipo": tipo, "corredor": corr,
                        "lugar": lugar, "titulo": nombre_lugar(lugar) if lugar and lugar != "ASU" else corr.title(),
                        "fuente": fuente, "ida": [], "regreso": [],
                    }
                o, dst = tr.tramo(s["destino"], s["lado"], corr, tipo)
                base, extras = tr.partes_destino(s["destino"])
                coche = "" if es_ref else _coche(s["coche"])
                habitual = "" if coche else hab.get((clave_corr, s["lado"], s["hora"]), "")
                c[s["lado"]].append({
                    "id": None if es_ref else s["id"],
                    "clave": f"{tipo}|{clave_corr}|{s['lado']}|{s['hora']}|{tr._sin_tildes(tr.limpiar(s['destino']))}",
                    "hora": s["hora"], "destino": s["destino"] or "", "tramo": base, "extras": extras,
                    "origen": o, "llega": dst, "origen_nombre": nombre_lugar(o), "llega_nombre": nombre_lugar(dst),
                    "coche": coche, "modelo": modelo(coche),
                    "a_confirmar": not coche and str(s.get("coche") or "").strip().upper().startswith("A CONF"),
                    "habitual": habitual, "habitual_modelo": modelo(habitual),
                    "tripulacion": [] if es_ref else _tripulacion(s),
                    "nota": "" if es_ref else (s.get("nota") or ""),
                })
            for c in por.values():
                for lado in tr.LADOS:
                    c[lado].sort(key=lambda x: x["hora"])
                corredores.append(c)
        aplicar_programacion(conn, fecha, corredores)
        # El plano de asientos de cada salida (sale del coche asignado o del que suele ir)
        try:
            cfg = {r["clave"]: json.loads(r["valor"]) for r in conn.execute(
                "SELECT clave, valor FROM alpha_config WHERE clave IN ('planos', 'coche_plano')").fetchall()}
        except Exception:
            cfg = {}
        planos = cfg.get("planos") or PLANOS_INICIALES
        cp = cfg.get("coche_plano") or {}
        # Transbordos: el coche que reemplazó al que se rompió. Si el tráfico ya
        # tiene la salida, el cambio está ahí; si no, se toma de Controles.
        try:
            reemp = {r["servicio"]: dict(r) for r in conn.execute(
                """SELECT servicio, COALESCE(coche, '') AS coche, COALESCE(reemplazo, '') AS reemplazo FROM alpha_servicios
                   WHERE fecha=? AND (COALESCE(coche, '') <> '' OR COALESCE(reemplazo, '') <> '')""", (fecha,)).fetchall()}
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            reemp = {}
        for c in corredores:
            for lado in tr.LADOS:
                for x in c[lado]:
                    r = reemp.get(x["clave"])
                    if not r:
                        continue
                    if r["coche"] and not x["coche"]:
                        x["coche"], x["modelo"], x["habitual"], x["habitual_modelo"] = r["coche"], modelo(r["coche"]), "", ""
                    try:
                        x["reemplazo"] = json.loads(r["reemplazo"]) if r["reemplazo"] else None
                    except ValueError:
                        x["reemplazo"] = None
        for c in corredores:
            for lado in tr.LADOS:
                for x in c[lado]:
                    coche = x["coche"] or x["habitual"]
                    x["plano"] = plano_de(coche, x["modelo"] if x["coche"] else x["habitual_modelo"], planos, cp)
                    # Un servicio agregado sin coche usa el plano que se le eligió
                    if not coche and (x.get("adicional") or {}).get("plano") in planos:
                        x["plano"] = x["adicional"]["plano"]
        return {"fecha": fecha, "corredores": corredores}

    finally:
        conn.close()


def plano_de(coche, modelo, planos, coche_plano):
    """El plano del coche: el que se le eligió; si no, se deduce del modelo
    (Volare o Senior → micro, Paradiso 1800 DD → AO01, los 8x2 → AO03, el
    resto → Paradiso un piso)."""
    fijo = coche and coche_plano.get(coche)
    if fijo and fijo in planos:
        return fijo
    m = str(modelo or "").lower()
    def ok(c):
        return c if c in planos else (next(iter(planos)) if planos else c)
    if re.search(r"volare|senior", m):
        return ok("VOLARE")
    if re.search(r"1800\s*dd|b6x2", m):
        return ok("AO01")
    if "8x2" in m:
        return ok("AO03")
    return ok("ACXC" if m else "AO01")


# Lo que una agencia no ve del tráfico: quién maneja, qué coche va, notas
# internas y en qué estado está el armado del día.
def para_agencia(d):
    for c in d.get("corredores", []):
        c["fuente"] = {"tipo": c["fuente"].get("tipo")}
        for lado in tr.LADOS:
            c[lado] = [x for x in c[lado] if not x.get("desactivado")]
            for x in c[lado]:
                if x.get("adicional"):
                    x["adicional"] = True
        for lado in tr.LADOS:
            for x in c[lado]:
                for k in ("tripulacion",):
                    x[k] = []
                for k in ("nota", "coche", "modelo", "habitual", "habitual_modelo"):
                    x[k] = ""
                x.pop("reemplazo", None)
                x["id"] = None
                x["a_confirmar"] = False
    d["corredores"] = [c for c in d.get("corredores", []) if c["ida"] or c["regreso"]]
    return d


def _rol_alpha():
    r = session.get("rol")
    return r if r in ("admin", "agencia") else None


@bp_alpha.route("/api/alpha/dia/<fecha>", methods=["GET"])
def api_alpha_dia(fecha):
    rol = _rol_alpha()
    if not rol:
        return jsonify({"ok": False, "error": "Alpha la ve solo administración y las agencias"}), 403
    try:
        date.fromisoformat(fecha)
    except ValueError:
        return jsonify({"ok": False, "error": "Fecha inválida"}), 400
    d = dia_para_alpha(fecha)
    return jsonify(para_agencia(d) if rol == "agencia" else d)


# ════════════════════════════════════════════════════════════════════════════
# PROGRAMACIÓN: activar y desactivar servicios por período
#   desactivar  un horario (o todos los de un corredor y sentido) que no sale
#               en un período y ciertos días: no se vende; la agencia no lo ve
#   activar     un servicio que no está en el tráfico (un refuerzo, un
#               feriado): se agrega a esos días. Si el tráfico lo arma, vale el
#               del tráfico (es el mismo servicio)
# ════════════════════════════════════════════════════════════════════════════

def _norm_dest(d):
    return tr._sin_tildes(tr.limpiar(d or ""))


def reglas_del_dia(conn, fecha):
    try:
        wd = str(date.fromisoformat(fecha).weekday())
        filas = [dict(r) for r in conn.execute(
            "SELECT * FROM alpha_programacion WHERE desde <= ? AND hasta >= ? ORDER BY id", (fecha, fecha)).fetchall()]
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return []
    return [r for r in filas if wd in (r.get("dias") or "0123456")]


def _coincide(r, corredor, lado, hora, dest_norm):
    return (r["corredor"] == corredor and (not r["lado"] or r["lado"] == lado) and (not r["hora"] or r["hora"] == hora)
            and (not r["destino"] or _norm_dest(r["destino"]) == dest_norm))


def servicio_desactivado(conn, fecha, clave):
    """El motivo si ese servicio está desactivado ese día (None si se vende)."""
    p = str(clave or "").split("|", 4)
    if len(p) < 5:
        return None
    for r in reglas_del_dia(conn, fecha):
        if r["tipo"] == "desactivar" and _coincide(r, f"{p[0]}|{p[1]}", p[2], p[3], p[4]):
            return r["motivo"] or "Servicio desactivado"
    return None


def aplicar_programacion(conn, fecha, corredores):
    reglas = reglas_del_dia(conn, fecha)
    if not reglas:
        return
    for r in [x for x in reglas if x["tipo"] == "activar" and _hora_ok(x["hora"]) and x["lado"] in tr.LADOS and x["destino"]]:
        tipo, clave_corr = (r["corredor"].split("|", 1) + [""])[:2]
        c = next((c for c in corredores if c["clave"] == r["corredor"]), None)
        nombre = (c or {}).get("corredor") or r["corredor_nombre"] or clave_corr
        if c is None:
            lugar = (tr._lugar_ar(nombre) or "BUENOS AIRES") if tipo == "internacional" else tr.lugar_del_corredor(nombre)
            c = {"clave": r["corredor"], "tipo": tipo, "corredor": nombre, "lugar": lugar,
                 "titulo": nombre_lugar(lugar) if lugar and lugar != "ASU" else nombre.title(),
                 "fuente": {"tipo": tipo, "estado": "programado"}, "ida": [], "regreso": []}
            corredores.append(c)
        clave = f"{r['corredor']}|{r['lado']}|{r['hora']}|{_norm_dest(r['destino'])}"
        if any(x["clave"] == clave for x in c[r["lado"]]):
            continue
        o, dst = tr.tramo(r["destino"], r["lado"], nombre, tipo)
        base, extras = tr.partes_destino(r["destino"])
        c[r["lado"]].append({
            "id": None, "clave": clave, "hora": r["hora"], "destino": r["destino"], "tramo": base, "extras": extras,
            "origen": o, "llega": dst, "origen_nombre": nombre_lugar(o), "llega_nombre": nombre_lugar(dst),
            "coche": "", "modelo": "", "a_confirmar": False, "habitual": "", "habitual_modelo": "",
            "tripulacion": [], "nota": "", "adicional": {"id": r["id"], "motivo": r["motivo"], "plano": r["plano"], "hasta": r["hasta"]}})
        c[r["lado"]].sort(key=lambda x: x["hora"])
    des = [x for x in reglas if x["tipo"] == "desactivar"]
    if des:
        for c in corredores:
            for lado in tr.LADOS:
                for x in c[lado]:
                    p = x["clave"].split("|", 4)
                    r = next((r for r in des if len(p) == 5 and _coincide(r, c["clave"], lado, x["hora"], p[4])), None)
                    if r:
                        x["desactivado"] = {"id": r["id"], "motivo": r["motivo"] or "", "hasta": r["hasta"]}


def programacion_listar():
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM alpha_programacion ORDER BY hasta DESC, id DESC").fetchall()]
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return []
    finally:
        conn.close()


def programacion_crear(d, quien=""):
    tipo = d.get("tipo")
    if tipo not in ("activar", "desactivar"):
        return None, "¿Activar o desactivar?"
    corredor = str(d.get("corredor") or "")[:120]
    if "|" not in corredor:
        return None, "Elegí el recorrido"
    lado = d.get("lado") or ""
    if lado not in ("", "ida", "regreso"):
        return None, "Sentido inválido"
    hora = tr.normalizar_hora(d.get("hora")) if d.get("hora") else ""
    if d.get("hora") and not hora:
        return None, "La hora no se entiende (poné HH:MM)"
    destino = " ".join(str(d.get("destino") or "").split()).upper()[:80]
    desde, hasta = str(d.get("desde") or ""), str(d.get("hasta") or d.get("desde") or "")
    try:
        f1, f2 = date.fromisoformat(desde), date.fromisoformat(hasta)
    except ValueError:
        return None, "Revisá las fechas"
    if f2 < f1:
        return None, "La fecha de fin es anterior a la de inicio"
    if (f2 - f1).days > 400:
        return None, "El período es de más de un año"
    dias = "".join(ch for ch in "0123456" if ch in str(d.get("dias") or "0123456"))
    if not dias:
        return None, "Elegí al menos un día de la semana"
    motivo = " ".join(str(d.get("motivo") or "").split())[:160]
    plano = str(d.get("plano") or "")[:12]
    if tipo == "activar":
        if lado not in tr.LADOS or not hora or not destino:
            return None, "Para agregar un servicio hacen falta el sentido, la hora y el destino (como en el tráfico, ej.: ASU/COP X 25)"
    elif not motivo:
        return None, "Contá por qué se desactiva (queda anotado)"
    conn = get_connection()
    try:
        cur = conn.execute("""INSERT INTO alpha_programacion (tipo, desde, hasta, dias, corredor, corredor_nombre, lado, hora,
                                  destino, plano, motivo, por, el) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                           (tipo, desde, hasta, dias, corredor, str(d.get("corredor_nombre") or "")[:80], lado, hora,
                            destino, plano, motivo, (quien or "")[:80], ahora_iso()))
        rid = cur.lastrowid
        conn.commit()
        # Lo que ya está vendido en las salidas que se desactivan
        afectados = []
        if tipo == "desactivar":
            r = {"corredor": corredor, "lado": lado, "hora": hora, "destino": destino}
            try:
                filas = conn.execute("""SELECT fecha, servicio, estado, vence, COUNT(*) AS n FROM alpha_ventas
                                        WHERE fecha >= ? AND fecha <= ? AND estado IN ('vendido', 'reserva')
                                        GROUP BY fecha, servicio, estado, vence""", (desde, hasta)).fetchall()
            except Exception:
                conn.rollback()
                filas = []
            ahora = ahora_iso()
            grupos = {}
            for f in filas:
                if f["estado"] == "reserva" and (f["vence"] or "") <= ahora:
                    continue
                if str(date.fromisoformat(f["fecha"]).weekday()) not in dias:
                    continue
                p = f["servicio"].split("|", 4)
                if len(p) == 5 and _coincide(r, f"{p[0]}|{p[1]}", p[2], p[3], p[4]):
                    k = (f["fecha"], f["servicio"])
                    grupos[k] = grupos.get(k, 0) + int(f["n"])
            afectados = [{"fecha": k[0], "servicio": k[1], "hora": k[1].split("|")[3], "pasajeros": n}
                         for k, n in sorted(grupos.items())]
        return {"id": rid, "afectados": afectados}, None
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def programacion_borrar(rid):
    conn = get_connection()
    try:
        r = conn.execute("SELECT * FROM alpha_programacion WHERE id=?", (int(rid),)).fetchone()
        if not r:
            return None
        conn.execute("DELETE FROM alpha_programacion WHERE id=?", (int(rid),))
        conn.commit()
        return dict(r)
    finally:
        conn.close()


@bp_alpha.route("/api/alpha/programacion", methods=["GET"])
def api_programacion():
    if session.get("rol") != "admin":
        return jsonify({"ok": False, "error": "La programación la ve administración"}), 403
    return jsonify({"reglas": programacion_listar(), "hoy": ahora_iso()[:10]})


@bp_alpha.route("/api/alpha/programacion", methods=["POST"])
def api_programacion_crear():
    if session.get("rol") != "admin":
        return jsonify({"ok": False, "error": "La programación la maneja administración"}), 403
    quien = session.get("nombre") or session.get("usuario") or ""
    d = request.get_json(silent=True) or {}
    r, err = programacion_crear(d, quien)
    if err:
        return jsonify({"ok": False, "msg": err, "error": err}), 400
    try:
        from database import registrar_auditoria
        registrar_auditoria(usuario=quien or "?", rol="admin", categoria="Alpha",
                            accion=f"Alpha: {'desactivó' if d.get('tipo') == 'desactivar' else 'agregó'} servicios por período",
                            detalle=f"{d.get('corredor')} {d.get('lado') or ''} {d.get('hora') or 'todos'} del {d.get('desde')} al {d.get('hasta')}: {d.get('motivo') or ''}"[:200])
    except Exception:
        pass
    return jsonify(dict(r, ok=True))


@bp_alpha.route("/api/alpha/programacion/<int:rid>", methods=["DELETE"])
def api_programacion_borrar(rid):
    if session.get("rol") != "admin":
        return jsonify({"ok": False, "error": "La programación la maneja administración"}), 403
    r = programacion_borrar(rid)
    if not r:
        return jsonify({"ok": False, "msg": "No existe", "error": "No existe"}), 404
    try:
        from database import registrar_auditoria
        registrar_auditoria(usuario=session.get("nombre") or "?", rol="admin", categoria="Alpha",
                            accion=f"Alpha: quitó una regla de programación ({'reactivó' if r['tipo'] == 'desactivar' else 'sacó el servicio agregado'})",
                            detalle=f"{r['corredor']} {r['lado']} {r['hora'] or 'todos'} del {r['desde']} al {r['hasta']}"[:200])
    except Exception:
        pass
    return jsonify({"ok": True})


# ════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN (planos, recorridos, tarifas, descuentos)
# ════════════════════════════════════════════════════════════════════════════

def _filas(desde, n, huecos=None):
    """Filas desde el frente: [ventanilla izq, pasillo izq, (pasillo), pasillo der, ventanilla der]."""
    huecos, out, k = huecos or {}, [], desde
    for i in range(n):
        if huecos.get(i) == "izq":
            out.append([k, k + 1, None, None, None]); k += 2
        else:
            out.append([k, k + 1, None, k + 3, k + 2]); k += 4
    return out


# Los planos de Delta. La empresa usa solo carrocerías Marcopolo: los doble
# piso son Paradiso 1800 DD, los de un piso Paradiso, y los micros Volare o
# Senior. Los códigos quedan como en Delta.
PLANOS_INICIALES = {
    "AO01": {"nombre": "Paradiso 1800 DD · cama abajo", "tipo": "Doble piso", "parados": 10, "pisos": [
        {"nombre": "Piso alto", "clase": "CO", "filas": _filas(1, 13, {2: "izq", 3: "izq"})},
        {"nombre": "Piso bajo", "clase": "CA", "filas": [[49, 50, None, None, 51], [52, 53, None, None, 54],
                                                         [55, 56, None, None, 57], [58, 59, None, None, 60]]},
    ]},
    "AO03": {"nombre": "Paradiso 1800 DD · todo diferencial", "tipo": "Doble piso", "parados": 10, "pisos": [
        {"nombre": "Piso alto", "clase": "CO", "filas": _filas(1, 14, {3: "izq", 4: "izq"})},
        {"nombre": "Piso bajo", "clase": "CO", "filas": _filas(53, 4)},
    ]},
    "ACXC": {"nombre": "Paradiso un piso", "tipo": "Un piso", "parados": 0, "pisos": [
        {"nombre": "Planta única", "clase": "CO", "filas": _filas(1, 12, {11: "izq"})},
    ]},
    # De arranque: 2 + 2 en 7 filas. Se ajusta en Alpha → Planos si no es así.
    "VOLARE": {"nombre": "Volare / Senior (micro)", "tipo": "Un piso", "parados": 0, "pisos": [
        {"nombre": "Planta única", "clase": "CO", "filas": _filas(1, 7)},
    ]},
}
NOMBRES_VIEJOS = {"AO01": "Doble piso con cama abajo", "AO03": "Doble piso, todo diferencial", "ACXC": "Un piso"}
# El recorrido de Concepción que ya se veía en la maqueta. Los demás se cargan
# en Tarifas → Recorridos.
RECORRIDOS_INICIALES = {
    "nacional|CONCEPCION": [
        {"nombre": "Por Ruta 3", "variante": "X 25", "paradas": [
            {"nombre": "Asunción"}, {"nombre": "Santaní"}, {"nombre": "Santa Rosa del Aguaray"},
            {"nombre": "Yby Yaú"}, {"nombre": "Horqueta"}, {"nombre": "Concepción"}]},
    ],
}
TARIFAS_INICIALES = {
    "nacional|CONCEPCION": {"Asunción|Concepción": {"CO": 150000, "CA": 180000}},
}
DESCUENTOS_INICIALES = [
    {"id": "general", "nombre": "General", "factor": 1},
    {"id": "menor", "nombre": "Menor (hasta 8 años)", "factor": 0.5},
    {"id": "jubilado", "nombre": "Jubilado", "factor": 0.75},
]
# Lo que dice el boleto (no fiscal): cuánto antes presentarse, el equipaje
# incluido, un teléfono y una leyenda al pie
BOLETO_INICIAL = {"presentarse_min": 15, "equipaje_kg": 20, "telefono": "", "leyenda": "", "menor_edad": 5}
INICIALES = {"planos": PLANOS_INICIALES, "coche_plano": {}, "recorridos": RECORRIDOS_INICIALES,
             "tarifas": TARIFAS_INICIALES, "descuentos": DESCUENTOS_INICIALES, "boleto": BOLETO_INICIAL}
MAX_JSON = 400_000


def init_alpha():
    conn = get_connection()
    try:
        conn.execute(f"""CREATE TABLE IF NOT EXISTS alpha_programacion (
            id {"SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"},
            tipo TEXT NOT NULL,
            desde TEXT NOT NULL,
            hasta TEXT NOT NULL,
            dias TEXT DEFAULT '0123456',
            corredor TEXT NOT NULL,
            corredor_nombre TEXT DEFAULT '',
            lado TEXT DEFAULT '',
            hora TEXT DEFAULT '',
            destino TEXT DEFAULT '',
            plano TEXT DEFAULT '',
            motivo TEXT DEFAULT '',
            por TEXT DEFAULT '',
            el TEXT DEFAULT '')""")
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS alpha_config (
            clave TEXT PRIMARY KEY,
            valor TEXT NOT NULL,
            actualizado_el TEXT DEFAULT '',
            actualizado_por TEXT DEFAULT '')""")
        conn.commit()
        hay = {r["clave"] for r in conn.execute("SELECT clave FROM alpha_config").fetchall()}
        for k, v in INICIALES.items():
            if k not in hay:
                conn.execute("INSERT INTO alpha_config (clave, valor, actualizado_el) VALUES (?,?,?) ON CONFLICT (clave) DO NOTHING",
                             (k, json.dumps(v, ensure_ascii=False), ahora_iso()))
        conn.commit()
        # Los planos con los nombres de Marcopolo y el del micro (solo si
        # nadie los cambió a mano)
        r = conn.execute("SELECT valor FROM alpha_config WHERE clave='planos'").fetchone()
        if r:
            pls = json.loads(r["valor"])
            cambio = False
            for cod, viejo in NOMBRES_VIEJOS.items():
                if cod in pls and pls[cod].get("nombre") == viejo:
                    pls[cod]["nombre"] = PLANOS_INICIALES[cod]["nombre"]; cambio = True
            if "VOLARE" not in pls and not any(re.search(r"volare|senior", str(p.get("nombre") or ""), re.I) for p in pls.values()):
                pls["VOLARE"] = PLANOS_INICIALES["VOLARE"]; cambio = True
            if cambio:
                conn.execute("UPDATE alpha_config SET valor=? WHERE clave='planos'", (json.dumps(pls, ensure_ascii=False),))
                conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


def leer_config():
    conn = get_connection()
    try:
        out = {k: json.loads(json.dumps(v)) for k, v in INICIALES.items()}
        meta = {}
        for r in conn.execute("SELECT clave, valor, actualizado_el, actualizado_por FROM alpha_config").fetchall():
            try:
                out[r["clave"]] = json.loads(r["valor"])
                meta[r["clave"]] = {"el": r["actualizado_el"] or "", "por": r["actualizado_por"] or ""}
            except ValueError:
                pass
        out["meta"] = meta
        # Los coches de la flota (para elegir el plano de cada uno)
        out["coches"] = [{"coche": n, "marca": v.get("marca") or "", "modelo": v.get("modelo") or "",
                          "patente": v.get("patente") or ""}
                         for n, v in sorted(tr._flota(conn).items(), key=lambda kv: (len(kv[0]), kv[0]))
                         if int(v.get("activo") or 0) == 1]
        # Los corredores que aparecen en el tráfico de los últimos dos meses
        desde = (date.fromisoformat(ahora_iso()[:10]) - timedelta(days=60)).isoformat()
        vistos = {}
        for r in conn.execute("""SELECT DISTINCT COALESCE(d.tipo,'nacional') AS tipo, b.nombre
                                 FROM trafico_bloques b JOIN trafico_dias d ON d.id = b.dia_id
                                 WHERE d.fecha >= ?""", (desde,)).fetchall():
            corr = (r["nombre"] or "").strip()
            clave = f"{r['tipo']}|{tr._sin_tildes(tr.limpiar(corr))}"
            if corr and clave not in vistos:
                lugar = (tr._lugar_ar(corr) or "BUENOS AIRES") if r["tipo"] == "internacional" else tr.lugar_del_corredor(corr)
                vistos[clave] = {"clave": clave, "tipo": r["tipo"], "corredor": corr,
                                 "titulo": nombre_lugar(lugar) if lugar and lugar != "ASU" else corr.title()}
        for clave in list(out.get("recorridos", {})) + list(out.get("tarifas", {})):
            if clave not in vistos and "|" in clave:
                tipo, corr = clave.split("|", 1)
                vistos[clave] = {"clave": clave, "tipo": tipo, "corredor": corr, "titulo": corr.title()}
        out["corredores"] = sorted(vistos.values(), key=lambda c: (c["tipo"] != "nacional", c["titulo"]))
        return out
    finally:
        conn.close()


def _valido(clave, valor):
    """Revisa lo mínimo para que Alpha no se rompa con un dato mal cargado."""
    if clave == "planos":
        if not isinstance(valor, dict) or not valor:
            return "Tiene que haber al menos un plano"
        for cod, p in valor.items():
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,12}", str(cod)):
                return f"El código «{cod}» no sirve: letras y números, hasta 12"
            if not isinstance(p, dict) or not isinstance(p.get("pisos"), list) or not p["pisos"]:
                return f"El plano {cod} no tiene pisos"
            vistos = set()
            for piso in p["pisos"]:
                if piso.get("clase") not in ("CO", "CA"):
                    return f"En el plano {cod} hay un piso sin clase"
                for fila in piso.get("filas") or []:
                    if not isinstance(fila, list) or len(fila) != 5:
                        return f"En el plano {cod} hay una fila mal armada"
                    for n in fila:
                        if n is None:
                            continue
                        if not isinstance(n, int) or not 1 <= n <= 199:
                            return f"En el plano {cod} hay un asiento con número inválido"
                        if n in vistos:
                            return f"En el plano {cod} el asiento {n} está dos veces"
                        vistos.add(n)
            if not vistos:
                return f"El plano {cod} no tiene asientos"
            try:
                if not 0 <= int(p.get("parados") or 0) <= 40:
                    return f"En el plano {cod}, los parados van de 0 a 40"
            except (TypeError, ValueError):
                return f"En el plano {cod}, los parados tienen que ser un número"
    elif clave == "coche_plano":
        if not isinstance(valor, dict):
            return "Formato inválido"
    elif clave == "recorridos":
        if not isinstance(valor, dict):
            return "Formato inválido"
        for corr, lista in valor.items():
            if not isinstance(lista, list):
                return "Formato inválido"
            for r in lista:
                ps = r.get("paradas") if isinstance(r, dict) else None
                if not isinstance(ps, list) or len(ps) < 2:
                    return f"Cada recorrido necesita al menos dos paradas ({corr})"
                nombres = [str(x.get("nombre") or "").strip() for x in ps]
                if any(not n for n in nombres):
                    return "Hay una parada sin nombre"
                if len({n.lower() for n in nombres}) != len(nombres):
                    return f"En el recorrido «{r.get('nombre') or corr}» hay una parada repetida"
    elif clave == "tarifas":
        if not isinstance(valor, dict):
            return "Formato inválido"
        for corr, pares in valor.items():
            if not isinstance(pares, dict):
                return "Formato inválido"
            for par, pr in pares.items():
                for cl in ("CO", "CA"):
                    x = (pr or {}).get(cl)
                    if x in (None, ""):
                        continue
                    if not isinstance(x, (int, float)) or x < 0 or x > 50_000_000:
                        return f"El precio de {par.replace('|', ' a ')} no es válido"
    elif clave == "descuentos":
        if not isinstance(valor, list) or not valor:
            return "Tiene que haber al menos una tarifa"
        for d in valor:
            try:
                f = float(d.get("factor"))
            except (TypeError, ValueError, AttributeError):
                return "Un descuento tiene un porcentaje inválido"
            if not 0 <= f <= 1 or not str(d.get("nombre") or "").strip():
                return "Revisá los descuentos: nombre y porcentaje entre 0 y 100"
    elif clave == "boleto":
        if not isinstance(valor, dict):
            return "Formato inválido"
        for k, (lo, hi) in {"presentarse_min": (0, 240), "equipaje_kg": (0, 100), "menor_edad": (0, 12)}.items():
            try:
                if not lo <= int(valor.get(k) or 0) <= hi:
                    return f"Revisá «{k.replace('_', ' ')}»: va de {lo} a {hi}"
            except (TypeError, ValueError):
                return f"«{k.replace('_', ' ')}» tiene que ser un número"
        if len(str(valor.get("telefono") or "")) > 60 or len(str(valor.get("leyenda") or "")) > 300:
            return "El teléfono o la leyenda son demasiado largos"
    else:
        return "Eso no se puede guardar"
    return None


def guardar_config(clave, valor, quien=""):
    err = _valido(clave, valor)
    if err:
        return False, err
    txt = json.dumps(valor, ensure_ascii=False)
    if len(txt) > MAX_JSON:
        return False, "Es demasiado grande para guardar"
    conn = get_connection()
    try:
        conn.execute("""INSERT INTO alpha_config (clave, valor, actualizado_el, actualizado_por) VALUES (?,?,?,?)
                        ON CONFLICT (clave) DO UPDATE SET valor=excluded.valor,
                        actualizado_el=excluded.actualizado_el, actualizado_por=excluded.actualizado_por""",
                     (clave, txt, ahora_iso(), (quien or "")[:80]))
        conn.commit()
    finally:
        conn.close()
    return True, "Guardado"


@bp_alpha.route("/api/alpha/config", methods=["GET"])
def api_alpha_config():
    rol = _rol_alpha()
    if not rol:
        return jsonify({"ok": False, "error": "Alpha la ve solo administración y las agencias"}), 403
    cfg = leer_config()
    if rol == "agencia":
        # Solo lo necesario para vender: los planos para dibujar el coche, las
        # paradas, los descuentos y el precio de cada tramo. Nada de la flota.
        cfg = {k: cfg.get(k) for k in ("planos", "recorridos", "tarifas", "descuentos", "corredores", "boleto")}
        cfg["coches"] = []
        cfg["coche_plano"] = {}
    return jsonify(cfg)


@bp_alpha.route("/api/alpha/config/<clave>", methods=["PUT"])
def api_alpha_guardar(clave):
    if session.get("rol") != "admin":
        return jsonify({"ok": False, "error": "Alpha la ve solo administración"}), 403
    d = request.get_json(silent=True) or {}
    quien = session.get("nombre") or session.get("usuario") or ""
    ok, msg = guardar_config(clave, d.get("valor"), quien)
    if not ok:
        return jsonify({"ok": False, "msg": msg, "error": msg}), 400
    try:
        from database import registrar_auditoria
        nombres = {"planos": "los planos de asientos", "coche_plano": "el plano de los coches",
                   "recorridos": "los recorridos", "tarifas": "las tarifas", "descuentos": "los descuentos",
                   "boleto": "lo que dice el boleto"}
        registrar_auditoria(usuario=quien or "?", rol=session.get("rol") or "",
                            accion=f"Alpha: cambió {nombres.get(clave, clave)}", categoria="Alpha", detalle="")
    except Exception:
        pass
    return jsonify({"ok": True, "msg": msg})
