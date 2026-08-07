"""
borrados_corp.py — Borrar rendiciones y deshacer liquidaciones.

El orden importa y el código lo obliga:

    liquidación pagada  →  deshacer liquidación  →  editar o borrar rendición

Una rendición liquidada no se toca. Si hay que corregirla, primero se deshace
la liquidación de esa semana, y ahí queda libre para editar o borrar.

Todo borrado queda registrado en eventos_corp con quién, cuándo y qué decía la
rendición. Es plata: nada desaparece sin dejar rastro.

Efecto secundario útil: borrar una rendición libera el candado del índice único
(cliente + tramo + fecha), así que resuelve el caso de la rendición suspendida
que no dejaba volver a cargar ese tramo.

Para engancharlo:
  1. from borrados_corp import borrados_bp, init_borrados
  2. app.register_blueprint(borrados_bp)
  3. init_borrados()
"""

import json

from flask import Blueprint, jsonify, request, session

from db_compat import get_conn              # <-- ajustar al nombre real

borrados_bp = Blueprint("borrados_corp", __name__)


def _es_admin():
    return session.get("rol") == "admin"    # <-- ajustar a tu control de roles


def _usuario():
    return session.get("usuario", "?")


def init_borrados():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS eventos_corp (
                id       SERIAL PRIMARY KEY,
                accion   TEXT NOT NULL,
                detalle  TEXT,
                usuario  TEXT,
                fecha    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


def _registrar(cur, accion, detalle):
    cur.execute(
        "INSERT INTO eventos_corp (accion, detalle, usuario) VALUES (%s, %s, %s)",
        (accion, json.dumps(detalle, ensure_ascii=False, default=str), _usuario()),
    )


# ── Borrar una rendición ───────────────────────────────────────────────────

@borrados_bp.route("/api/corp/rendicion/<int:rid>", methods=["DELETE"])
def borrar_rendicion(rid):
    if not _es_admin():
        return jsonify({"error": "Solo el administrador puede borrar rendiciones"}), 403

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT fecha, chofer, cliente, tramo, estado, monto, liquidado
            FROM rendiciones_corp WHERE id = %s
        """, (rid,))
        fila = cur.fetchone()

        if not fila:
            return jsonify({"error": "Esa rendición no existe"}), 404

        if fila[6]:
            return jsonify({
                "error": "Esta rendición ya está liquidada. "
                         "Deshacé la liquidación de esa semana y volvé a intentar."
            }), 409

        _registrar(cur, "borrar_rendicion", {
            "id": rid, "fecha": fila[0], "chofer": fila[1],
            "cliente": fila[2], "tramo": fila[3],
            "estado": fila[4], "monto": fila[5],
        })
        cur.execute("DELETE FROM rendiciones_corp WHERE id = %s", (rid,))
        conn.commit()

    return jsonify({"borrada": rid})


# ── Liquidaciones ──────────────────────────────────────────────────────────

@borrados_bp.route("/api/corp/liquidaciones", methods=["GET"])
def listar_liquidaciones():
    """Liquidaciones ya hechas, agrupadas por chofer y fecha de pago."""
    if not _es_admin():
        return jsonify({"error": "Solo el administrador puede ver esto"}), 403

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT chofer,
                   DATE(fecha_liquidacion) AS pagada_el,
                   COUNT(*)                AS servicios,
                   SUM(monto)              AS total,
                   MIN(fecha)              AS desde,
                   MAX(fecha)              AS hasta,
                   MAX(liquidado_por)      AS liquidado_por
            FROM rendiciones_corp
            WHERE COALESCE(liquidado, FALSE) = TRUE
            GROUP BY chofer, DATE(fecha_liquidacion)
            ORDER BY pagada_el DESC, chofer
        """)
        filas = cur.fetchall()

    return jsonify({"liquidaciones": [{
        "chofer": f[0], "pagada_el": f[1], "servicios": f[2], "total": f[3],
        "desde": f[4], "hasta": f[5], "liquidado_por": f[6],
    } for f in filas]})


@borrados_bp.route("/api/corp/liquidacion", methods=["DELETE"])
def deshacer_liquidacion():
    """Devuelve las rendiciones de esa liquidación al estado sin liquidar.

    No borra ninguna rendición: solo saca la marca de pagada, así vuelven a
    aparecer en el acumulado del chofer y se pueden editar o borrar.
    """
    if not _es_admin():
        return jsonify({"error": "Solo el administrador puede deshacer liquidaciones"}), 403

    datos = request.get_json(silent=True) or {}
    chofer = datos.get("chofer")
    pagada_el = datos.get("pagada_el")

    if not chofer or not pagada_el:
        return jsonify({"error": "Falta el chofer o la fecha de la liquidación"}), 400

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*), COALESCE(SUM(monto), 0)
            FROM rendiciones_corp
            WHERE chofer = %s
              AND DATE(fecha_liquidacion) = %s
              AND COALESCE(liquidado, FALSE) = TRUE
        """, (chofer, pagada_el))
        cantidad, total = cur.fetchone()

        if not cantidad:
            return jsonify({"error": "No encontré esa liquidación"}), 404

        _registrar(cur, "deshacer_liquidacion", {
            "chofer": chofer, "pagada_el": pagada_el,
            "servicios": cantidad, "total": total,
        })

        cur.execute("""
            UPDATE rendiciones_corp
            SET liquidado = FALSE,
                fecha_liquidacion = NULL,
                liquidado_por = NULL
            WHERE chofer = %s AND DATE(fecha_liquidacion) = %s
        """, (chofer, pagada_el))
        conn.commit()

    return jsonify({
        "chofer": chofer,
        "servicios": cantidad,
        "total": total,
        "mensaje": f"{cantidad} servicios volvieron a quedar sin liquidar",
    })
