"""
ficha_coche.py — La ficha única de cada coche (La Santaniana)

Taller quedó en tres secciones: Órdenes de trabajo, Pedidos de choferes y
Coches. La sección Coches junta en una sola ficha lo que antes estaba repartido
en Preventivo, Correctivos, Mantenimientos, Neumáticos, Historial, Costos y
KPIs.

Este archivo arma el RESUMEN de la ficha: lo que hay que saber del coche de un
vistazo (cómo está ahora, qué le toca, qué tiene abierto en el taller, lo
último que se le hizo, cómo están las cubiertas y los papeles). Las otras
pestañas de la ficha usan las rutas de siempre de cada módulo.

Cada bloque se calcula por separado: si uno falla, ese queda vacío y los demás
se muestran igual.

Enganche en app.py:
    from ficha_coche import bp_ficha_coche
    app.register_blueprint(bp_ficha_coche)
"""

from datetime import date, timedelta

from flask import Blueprint, jsonify, session

from db_compat import get_connection
from hora_local import hoy

bp_ficha_coche = Blueprint("ficha_coche", __name__)

ROLES = ("admin", "taller", "compras")


def _dias_hasta(fecha):
    try:
        return (date.fromisoformat(str(fecha)[:10]) - date.fromisoformat(hoy())).days
    except Exception:
        return None


def _bloque(out, clave, fn):
    try:
        out[clave] = fn()
    except Exception as e:
        print(f"[ficha_coche] {clave}: {e}")
        out[clave] = None


def _coche(conn, vid):
    v = conn.execute("""SELECT id, n_interno, patente, marca, modelo, año AS anio, chasis, asientos, ejes, tipo,
                               activo FROM vehiculos WHERE id=?""", (vid,)).fetchone()
    return dict(v) if v else None


def _fuera_servicio(conn, vid):
    r = conn.execute("""SELECT fecha_desde, motivo FROM fuera_servicio
                        WHERE vehiculo_id=? AND (fecha_hasta IS NULL OR fecha_hasta='')
                        ORDER BY fecha_desde DESC LIMIT 1""", (vid,)).fetchone()
    if not r:
        return None
    d = _dias_hasta(r["fecha_desde"])
    return {"desde": r["fecha_desde"], "motivo": r["motivo"] or "", "dias": -d if d is not None else None}


def _ots(conn, vid):
    """Las órdenes que el coche tiene abiertas, con cuánto falta de cada una."""
    filas = conn.execute("""
        SELECT o.id, o.estado, o.fecha_apertura, o.km, o.conductor,
               (SELECT COUNT(*) FROM ot_items i WHERE i.ot_id=o.id) AS trabajos,
               (SELECT COUNT(*) FROM ot_items i WHERE i.ot_id=o.id AND i.estado <> 'completado') AS pendientes
        FROM ordenes_trabajo o
        WHERE o.vehiculo_id=? AND o.estado IN ('abierta','en_proceso')
        ORDER BY o.id DESC LIMIT 6""", (vid,)).fetchall()
    out = []
    for f in filas:
        d = dict(f)
        dias = _dias_hasta(d["fecha_apertura"])
        d["dias"] = -dias if dias is not None else None
        d["falta"] = [r["descripcion"] for r in conn.execute(
            "SELECT descripcion FROM ot_items WHERE ot_id=? AND estado <> 'completado' ORDER BY id LIMIT 4",
            (d["id"],)).fetchall()]
        out.append(d)
    return out


def _ots_cuenta(conn, vid):
    desde = (date.fromisoformat(hoy()) - timedelta(days=90)).isoformat()
    r = conn.execute("""SELECT COUNT(*) AS total,
                               SUM(CASE WHEN fecha_apertura >= ? THEN 1 ELSE 0 END) AS ultimos_90
                        FROM ordenes_trabajo WHERE vehiculo_id=?""", (desde, vid)).fetchone()
    return {"total": int(r["total"] or 0), "ultimos_90": int(r["ultimos_90"] or 0)}


def _pedidos(vid):
    from ot_pedidos import del_coche
    return [{"id": p["id"], "descripcion": p["descripcion"], "estado": p["estado"], "prioridad": p["prioridad"],
             "chofer": p.get("chofer") or "", "fecha": p.get("fecha") or "", "fecha_turno": p.get("fecha_turno") or ""}
            for p in del_coche(vid)][:8]


def _preventivo(vid):
    from plan_preventivo import ficha_coche
    f = ficha_coche(vid)
    if not f:
        return None
    claves = ("estado", "plan_id", "plan_nombre", "km_actual", "km_dia", "km_dia_fuente", "km_verif", "proximo",
              "n_tareas", "al_dia", "vencidas", "proximas", "sin_dato", "cumplimiento", "fecha_sugerida")
    out = {k: f.get(k) for k in claves}
    turno = f.get("turno")
    if not turno:
        abiertos = [t for t in (f.get("turnos") or []) if t.get("estado") in ("agendado", "en_taller")]
        turno = abiertos[-1] if abiertos else None
    out["turno"] = ({"id": turno["id"], "fecha": turno["fecha"], "hora": turno.get("hora") or "",
                     "estado": turno["estado"], "ot_id": turno.get("ot_id")} if turno else None)
    return out


def _historia(vid):
    from historial_carga import historia_coche
    d = historia_coche(vid, 1, por_pagina=6)
    if not d:
        return None
    desde = (date.fromisoformat(hoy()) - timedelta(days=90)).isoformat()
    ultimos_90 = {"preventivo": 0, "correctivo": 0, "neumaticos": 0, "otros": 0}
    for m in d.get("vida") or []:
        if m["mes"] >= desde[:7]:
            for g in ultimos_90:
                ultimos_90[g] += int(m.get(g) or 0)
    return {"resumen": d["resumen"], "por_tipo": d["por_tipo"], "ultimos": d["items"][:6],
            "vida": (d.get("vida") or [])[-12:], "tres_meses": ultimos_90}


def _neumaticos(vid):
    from database import estado_neumaticos_vehiculo
    e = estado_neumaticos_vehiculo(vid)
    if not e:
        return None
    ruedas = e.get("neumaticos") or []
    montadas = [r for r in ruedas if not r.get("vacia")]
    mal = [r for r in montadas if r.get("estado_grad") in ("atencion", "vencido")]
    peor = max(montadas, key=lambda r: r.get("porcentaje_uso") or 0) if montadas else None
    return {"configuracion": e.get("configuracion"), "medida": e.get("medida") or "",
            "posiciones": len(ruedas), "montadas": len(montadas), "vacias": len(ruedas) - len(montadas),
            "para_cambiar": len(mal),
            "ruedas": [{"posicion": r.get("posicion"), "nombre": r.get("posicion_nombre"),
                        "vacia": bool(r.get("vacia")), "estado": r.get("estado_grad") or "",
                        "uso": r.get("porcentaje_uso") or 0} for r in ruedas],
            "peor": ({"nombre": peor.get("posicion_nombre"), "uso": peor.get("porcentaje_uso"),
                      "km_restantes": peor.get("km_restantes")} if peor else None)}


def _documentos(vid):
    from database import obtener_documentos
    out = []
    for d in obtener_documentos(vehiculo_id=vid):
        dias = _dias_hasta(d.get("fecha_vencimiento"))
        out.append({"id": d["id"], "tipo": d.get("tipo") or "", "nombre": d.get("nombre") or "",
                    "vence": d.get("fecha_vencimiento") or "", "dias": dias})
    out.sort(key=lambda x: (x["dias"] is None, x["dias"] if x["dias"] is not None else 0))
    return out[:8]


def resumen_coche(vid):
    conn = get_connection()
    try:
        coche = _coche(conn, vid)
        if not coche:
            return None
        out = {"coche": coche, "hoy": hoy()}
        _bloque(out, "fuera_servicio", lambda: _fuera_servicio(conn, vid))
        _bloque(out, "ots", lambda: _ots(conn, vid))
        _bloque(out, "ots_cuenta", lambda: _ots_cuenta(conn, vid))
    finally:
        conn.close()
    _bloque(out, "pedidos", lambda: _pedidos(vid))
    _bloque(out, "preventivo", lambda: _preventivo(vid))
    _bloque(out, "historia", lambda: _historia(vid))
    _bloque(out, "neumaticos", lambda: _neumaticos(vid))
    _bloque(out, "documentos", lambda: _documentos(vid))
    return out


@bp_ficha_coche.route("/api/coche/<int:vid>/resumen", methods=["GET"])
def api_resumen_coche(vid):
    if session.get("rol") not in ROLES:
        return jsonify({"error": "Sin permiso"}), 403
    d = resumen_coche(vid)
    if not d:
        return jsonify({"error": "Ese coche no existe"}), 404
    return jsonify(d)
