"""
consola.py — Los números de la vista «consola» del administrador

La vista consola (static/consola.js) muestra el sistema como el inicio de una
PlayStation: las divisiones arriba, y adentro de cada una sus subdivisiones
como tarjetas. Cada tarjeta lleva un dato en vivo (OTs abiertas, servicios
de hoy, lo que falta liquidar…). Todos salen de acá, en un solo pedido.

Cada número se calcula por separado: si una tabla no existe o una consulta
falla, ese dato queda vacío y los demás se muestran igual.

Enganche en app.py:
    from consola import bp_consola
    app.register_blueprint(bp_consola)
"""

import time
from datetime import date, timedelta

from flask import Blueprint, jsonify, session

from db_compat import get_connection
from hora_local import hoy, ahora

bp_consola = Blueprint("consola", __name__)

# Se guarda unos segundos: la consola pide los números al abrir y cada minuto,
# y varias pestañas abiertas no tienen que multiplicar las consultas.
_memo = {"t": 0.0, "datos": None}
_MEMO_SEG = 20


def _uno(conn, sql, params=(), campo="n", defecto=None):
    """Un número suelto. Si falla, se deshace la consulta y se sigue."""
    try:
        r = conn.execute(sql, params).fetchone()
        if r is None:
            return defecto
        v = r[campo]
        return v if v is not None else defecto
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        return defecto


def resumen():
    f = date.fromisoformat(hoy())
    hoy_txt = f.isoformat()
    en30 = (f + timedelta(days=30)).isoformat()
    hace7 = (f - timedelta(days=7)).isoformat()
    mes = hoy_txt[:7]
    d = {"fecha": hoy_txt, "hora": ahora().strftime("%H:%M")}

    # Lo del día (lo mismo que ve el gerente): tráfico, turismo, corporativos, flota
    try:
        import gerencia
        op = gerencia.operacion_del_dia(f)
        t, tu, co, fl = op["trafico"], op["turismo"], op["corporativos"], op["flota"]
        d["trafico"] = {"total": t["total"], "salieron": t["salieron"], "por_salir": t["por_salir"],
                        "sin_coche": t["sin_coche"], "internacional": t["internacional"], "existe": t["existe"]}
        d["turismo_hoy"] = {"total": tu["total"], "en_viaje": len(tu.get("en_viaje") or []),
                            "sin_asignar": tu["sin_asignar"]}
        d["corp_hoy"] = {"servicios": co["servicios"], "completos": co["completos"], "medios": co["medios"]}
        d["flota"] = {"activos": fl["activos"], "disponibles": fl["disponibles"],
                      "en_taller": fl["en_taller"], "fuera_servicio": fl["fuera_servicio"]}
    except Exception:
        pass

    conn = get_connection()
    try:
        # Taller
        d["ots"] = {
            "abiertas": _uno(conn, """SELECT COUNT(DISTINCT COALESCE(ot_grupo, id)) AS n FROM ordenes_trabajo
                                      WHERE estado <> 'cerrada'""", defecto=0),
            "en_compras": _uno(conn, """SELECT COUNT(*) AS n FROM ordenes_trabajo WHERE estado <> 'cerrada'
                                        AND COALESCE(estado_compras,'') IN ('en_espera','presupuestado','en_camino')""", defecto=0),
            "cerradas_mes": _uno(conn, """SELECT COUNT(*) AS n FROM ordenes_trabajo WHERE estado = 'cerrada'
                                          AND substr(COALESCE(fecha_cierre,''),1,7) = ?""", (mes,), defecto=0),
        }
        d["pedidos_7d"] = _uno(conn, "SELECT COUNT(*) AS n FROM ot_pedido_reportes WHERE substr(COALESCE(fecha,''),1,10) >= ?",
                               (hace7,), defecto=0)
        d["correctivos"] = _uno(conn, "SELECT COUNT(*) AS n FROM correctivos WHERE estado IN ('pendiente','en_reparacion')", defecto=0)

        # Documentos de los coches
        d["docs"] = {
            "vencidos": _uno(conn, """SELECT COUNT(*) AS n FROM documentos WHERE reemplazado_por IS NULL
                                      AND COALESCE(fecha_vencimiento,'') <> '' AND fecha_vencimiento < ?""", (hoy_txt,), defecto=0),
            "por_vencer": _uno(conn, """SELECT COUNT(*) AS n FROM documentos WHERE reemplazado_por IS NULL
                                        AND COALESCE(fecha_vencimiento,'') <> '' AND fecha_vencimiento >= ? AND fecha_vencimiento <= ?""",
                               (hoy_txt, en30), defecto=0),
        }

        # Combustible del mes
        d["combustible"] = {
            "litros_mes": round(float(_uno(conn, "SELECT SUM(litros) AS n FROM combustible WHERE substr(fecha,1,7) = ?", (mes,), defecto=0) or 0)),
            "cargas_hoy": _uno(conn, "SELECT COUNT(*) AS n FROM combustible WHERE substr(fecha,1,10) = ?", (hoy_txt,), defecto=0),
        }

        # Corporativos: lo que falta liquidar
        d["corp_pend"] = {
            "servicios": _uno(conn, """SELECT COUNT(*) AS n FROM rendiciones_corp
                                       WHERE COALESCE(liquidado,0)=0 AND estado <> 'suspendido'""", defecto=0),
            "monto": round(float(_uno(conn, """SELECT SUM(monto) AS n FROM rendiciones_corp
                                               WHERE COALESCE(liquidado,0)=0 AND estado <> 'suspendido'""", defecto=0) or 0)),
        }

        # Turismo: rendiciones que esperan revisión
        d["turismo_rend"] = _uno(conn, "SELECT COUNT(*) AS n FROM turismo_rendiciones WHERE estado = 'presentada'",
                                 defecto=0)

        # Pasajes (Alpha): lo vendido hoy
        d["alpha_hoy"] = {
            "boletos": _uno(conn, """SELECT COUNT(*) AS n FROM alpha_ventas WHERE estado = 'vendido'
                                     AND substr(COALESCE(creado_el,''),1,10) = ?""", (hoy_txt,), defecto=0),
            "total": round(float(_uno(conn, """SELECT SUM(total) AS n FROM alpha_ventas WHERE estado = 'vendido'
                                               AND substr(COALESCE(creado_el,''),1,10) = ?""", (hoy_txt,), defecto=0) or 0)),
        }

        # Integraciones: lo que llegó y hay que mirar
        d["integ_revisar"] = _uno(conn, "SELECT COUNT(*) AS n FROM integ_entrada WHERE estado IN ('revisar','error')", defecto=0)

        # Tesorería: cajas abiertas
        d["cajas"] = _uno(conn, "SELECT COUNT(*) AS n FROM cajas", defecto=None)
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return d


@bp_consola.route("/api/consola/resumen", methods=["GET"])
def api_consola_resumen():
    if session.get("rol") != "admin":
        return jsonify({"error": "Solo el administrador"}), 403
    ahora_s = time.time()
    if not _memo["datos"] or ahora_s - _memo["t"] > _MEMO_SEG:
        _memo["datos"] = resumen()
        _memo["t"] = ahora_s
    return jsonify(_memo["datos"])
