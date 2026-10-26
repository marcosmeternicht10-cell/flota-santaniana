"""
ot_salidas.py — Cuándo tiene que salir el coche que está en el taller

El taller necesita saber para qué hora tiene que estar listo un coche. Esto
junta las próximas salidas del coche desde lo que ya está cargado:

  · el tráfico (nacional e internacional): hora, corredor y tramo
  · la asignación de corporativos: el tramo, con su horario (cambiado o no)
  · la agenda de turismo: el servicio con su hora

Se muestra en la OT (/api/ots/<id>/salidas) y en la hoja del técnico.
No modifica nada: solo lee.
"""

import re
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, session

from db_compat import get_connection
from hora_local import ahora

bp_ot_salidas = Blueprint("ot_salidas", __name__)

DIAS_ADELANTE = 3
DIAS_TXT = ["LUN", "MAR", "MIÉ", "JUE", "VIE", "SÁB", "DOM"]


def _rollback(conn):
    try:
        conn.rollback()
    except Exception:
        pass


def _coche(c):
    """'21660', ' 021660 ', 'A CONF' → '21660' / '' (solo los números cuentan)."""
    s = re.sub(r"\s+", "", str(c or "").upper())
    d = re.sub(r"\D", "", s)
    return d.lstrip("0") if d and d == s else ""


def _hora(h):
    m = re.match(r"^\s*(\d{1,2})[:.](\d{2})", str(h or ""))
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return ""
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def _del_trafico(conn, coche, desde, hasta):
    import trafico as T
    out = []
    filas = conn.execute("""
        SELECT d.fecha, COALESCE(d.tipo,'nacional') AS tipo, s.hora, s.destino, s.lado, s.coche, b.nombre AS corredor
        FROM trafico_salidas s
        JOIN trafico_dias d ON d.id = s.dia_id
        LEFT JOIN trafico_bloques b ON b.id = s.bloque_id
        WHERE d.fecha >= ? AND d.fecha <= ?""", (desde, hasta)).fetchall()
    for f in filas:
        if _coche(f["coche"]) != coche:
            continue
        try:
            o, l = T.tramo(f["destino"] or "", f["lado"] or "ida", f["corredor"] or "", f["tipo"])
        except Exception:
            o, l = "", ""
        corredor = " ".join(p.capitalize() for p in str(f["corredor"] or "").split())
        detalle = f"{o} → {l}" if o and l else (f["destino"] or "")
        out.append({"fecha": f["fecha"], "hora": _hora(f["hora"]), "origen": "trafico",
                    "titulo": ("Internacional" if f["tipo"] == "internacional" else "Tráfico") + (f" · {corredor}" if corredor else ""),
                    "detalle": detalle})
    return out


def _de_corporativos(conn, coche, desde, hasta):
    import corp_asignacion as CA
    out = []
    dias = conn.execute("SELECT id, fecha FROM corp_asig_dias WHERE fecha >= ? AND fecha <= ?", (desde, hasta)).fetchall()
    for d in dias:
        horarios = CA._horarios(conn, d["id"])
        for f in conn.execute("SELECT * FROM corp_asig WHERE dia_id=?", (d["id"],)).fetchall():
            f = dict(f)
            if f["lado"] == "no_corre" or _coche(f.get("coche")) != coche:
                continue
            if f["lado"] == "variable":
                hora, nombre = _hora(f.get("hora")), (f.get("detalle") or "Servicio variable")
            else:
                i = CA.info_tramo(f["tramo"], horarios.get((f["cliente"], f["tramo"])))
                hora = i["hora_fin"] if f["lado"] == "saliente" and i.get("hora_fin") else i["hora"]
                nombre = i["corto"] + {"entrante": " (entrada)", "saliente": " (salida)"}.get(f["lado"], "")
            out.append({"fecha": d["fecha"], "hora": hora, "origen": "corporativos",
                        "titulo": f"Corporativos · {f['cliente']}", "detalle": nombre})
    return out


def _de_turismo(conn, coche, desde, hasta):
    out = []
    filas = conn.execute("""SELECT * FROM agenda_turismo WHERE fecha >= ? AND fecha <= ?
                            AND COALESCE(estado,'') NOT IN ('cancelado','completado')""", (desde, hasta)).fetchall()
    for f in filas:
        f = dict(f)
        coches = {_coche(f.get(k)) for k in ("coche_interno", "coche_interno_2", "coche_interno_3")}
        if coche not in coches:
            continue
        ruta = " → ".join(x for x in (f.get("salida"), f.get("destino")) if x)
        out.append({"fecha": f["fecha"][:10], "hora": _hora(f.get("hora")), "origen": "turismo",
                    "titulo": f"Turismo · {f.get('cliente') or ''}", "detalle": ruta})
    return out


def proximas_salidas(n_interno, dias=DIAS_ADELANTE, limite=6, conn=None):
    """Las salidas del coche desde ahora hasta dentro de `dias` días, la más
    próxima primero. Las de hoy sin hora también entran (no se sabe a qué hora)."""
    coche = _coche(n_interno)
    if not coche:
        return []
    ah = ahora().replace(tzinfo=None)
    desde = ah.date().isoformat()
    hasta = (ah.date() + timedelta(days=dias)).isoformat()
    propia = conn is None
    conn = conn or get_connection()
    todas = []
    try:
        for fn in (_del_trafico, _de_corporativos, _de_turismo):
            try:
                todas += fn(conn, coche, desde, hasta)
            except Exception:
                _rollback(conn)
    finally:
        if propia:
            conn.close()
    out = []
    for s in todas:
        try:
            cuando = datetime.fromisoformat(f"{s['fecha']}T{s['hora'] or '23:59'}")
        except Exception:
            continue
        if s["hora"] and cuando < ah:
            continue
        d = date.fromisoformat(s["fecha"])
        dif = (d - ah.date()).days
        s["dia"] = "HOY" if dif == 0 else "MAÑANA" if dif == 1 else f"{DIAS_TXT[d.weekday()]} {d.day:02d}/{d.month:02d}"
        s["faltan_min"] = int((cuando - ah).total_seconds() // 60) if s["hora"] else None
        s["_orden"] = cuando
        out.append(s)
    out.sort(key=lambda s: s["_orden"])
    for s in out:
        s.pop("_orden", None)
    return out[:limite]


def texto_corto(s):
    """'HOY 16:30 · Corporativos · BALL · TURNO 2' para la hoja del técnico."""
    partes = [f"{s['dia']} {s['hora'] or '(sin hora)'}", s["titulo"]]
    if s.get("detalle"):
        partes.append(s["detalle"])
    return " · ".join(p for p in partes if p)


@bp_ot_salidas.route("/api/ots/<int:ot_id>/salidas", methods=["GET"])
def api_salidas(ot_id):
    if session.get("rol") not in ("admin", "taller", "compras", "auditor"):
        return jsonify({"error": "Sin permiso"}), 403
    conn = get_connection()
    try:
        r = conn.execute("""SELECT v.n_interno FROM ordenes_trabajo o JOIN vehiculos v ON v.id = o.vehiculo_id
                            WHERE o.id=?""", (ot_id,)).fetchone()
        coche = (r["n_interno"] if r else "") or ""
        salidas = proximas_salidas(coche, conn=conn) if r else []
    finally:
        conn.close()
    return jsonify({"coche": coche, "salidas": salidas, "dias": DIAS_ADELANTE})
