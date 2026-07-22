"""
historial_carga.py — Carga retroactiva del historial en papel (La Santaniana)

El historial de los buses está en papel. Este módulo permite tipearlo al
sistema de forma rápida, bus por bus, con fecha retroactiva. La regla de
destino es la clave:

  - tipo 'correctivo'  → va a la tabla REAL `correctivos` (estado completado).
    Así el OEE y el dossier lo cuentan como falla, que es lo correcto.
  - cualquier otro tipo (preventivo, neumáticos, servicio, otro) → va a la
    tabla `historial_eventos`. Un cambio de aceite histórico NO es una falla
    y no debe ensuciar las métricas de confiabilidad.

El dossier lee ambas fuentes, así que todo lo cargado suma a los reportes.

Enganche en app.py (2 líneas, después de los otros blueprints):
    from historial_carga import bp_historial, init_historial_module
    init_historial_module(app)
    app.register_blueprint(bp_historial)
"""

from flask import Blueprint, request, jsonify, session
from db_compat import get_connection, USE_POSTGRES, OperationalError, columnas_de_tabla

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"

TIPOS_EVENTO = ["correctivo", "preventivo", "neumaticos", "servicio", "otro"]

bp_historial = Blueprint("historial_carga", __name__)


# ════════════════════════════════════════════════════════════════════════════
# TABLA
# ════════════════════════════════════════════════════════════════════════════

def inicializar_historial():
    """Crea la tabla de eventos históricos. Idempotente."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS historial_eventos (
            id {PK},
            vehiculo_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'otro',   -- preventivo | neumaticos | servicio | otro
            categoria TEXT DEFAULT '',           -- ej: 'Cambio de aceite', 'Rotación', libre
            descripcion TEXT NOT NULL,
            km REAL DEFAULT 0,
            costo REAL DEFAULT 0,
            taller TEXT DEFAULT '',
            observaciones TEXT DEFAULT '',
            cargado_por TEXT DEFAULT '',
            fecha_carga TEXT DEFAULT (date('now')),
            FOREIGN KEY (vehiculo_id) REFERENCES vehiculos(id)
        )
    """)
    conn.commit()
    conn.close()


def init_historial_module(app):
    inicializar_historial()


# ════════════════════════════════════════════════════════════════════════════
# LÓGICA
# ════════════════════════════════════════════════════════════════════════════

def agregar_evento(vehiculo_id, fecha, tipo, descripcion, categoria="",
                   km=0, costo=0, taller="", usuario=""):
    """Registra un evento histórico en su tabla de destino según el tipo.
    Devuelve (ok, {origen, id}) — 'origen' indica en qué tabla quedó,
    necesario para poder borrarlo si se cargó mal."""
    tipo = (tipo or "otro").lower().strip()
    if tipo not in TIPOS_EVENTO:
        tipo = "otro"
    descripcion = (descripcion or "").strip()
    if not descripcion:
        return False, "La descripción es obligatoria."

    conn = get_connection()
    try:
        if tipo == "correctivo":
            # A la tabla real de correctivos, como falla ya resuelta.
            # La categoría del papel (ej: "Motor") es el tipo_falla.
            cur = conn.execute("""
                INSERT INTO correctivos
                    (vehiculo_id, fecha, km, tipo_falla, descripcion,
                     reparacion, costo, taller, estado, observaciones)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (vehiculo_id, fecha, float(km or 0),
                  (categoria or "Otros").strip(), descripcion,
                  "", float(costo or 0), taller.strip(), "completado",
                  f"[Historial cargado por {usuario}]" if usuario else "[Historial]"))
            rid = cur.lastrowid
            conn.commit()
            return True, {"origen": "correctivos", "id": rid}
        else:
            cur = conn.execute("""
                INSERT INTO historial_eventos
                    (vehiculo_id, fecha, tipo, categoria, descripcion,
                     km, costo, taller, cargado_por)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (vehiculo_id, fecha, tipo, categoria.strip(), descripcion,
                  float(km or 0), float(costo or 0), taller.strip(), usuario))
            rid = cur.lastrowid
            conn.commit()
            return True, {"origen": "historial_eventos", "id": rid}
    finally:
        conn.close()


def obtener_historial_vehiculo(vehiculo_id, limite=100):
    """Todo lo cargado retroactivamente para un coche: eventos de la tabla
    propia + correctivos marcados como históricos. Más recientes primero."""
    conn = get_connection()
    eventos = conn.execute("""
        SELECT id, fecha, tipo, categoria, descripcion, km, costo, taller,
               cargado_por, 'historial_eventos' AS origen
        FROM historial_eventos WHERE vehiculo_id=?
    """, (vehiculo_id,)).fetchall()
    correctivos = conn.execute("""
        SELECT id, fecha, 'correctivo' AS tipo, tipo_falla AS categoria,
               descripcion, km, costo, taller, '' AS cargado_por,
               'correctivos' AS origen
        FROM correctivos
        WHERE vehiculo_id=? AND observaciones LIKE '[Historial%'
    """, (vehiculo_id,)).fetchall()
    conn.close()
    todos = [dict(r) for r in eventos] + [dict(r) for r in correctivos]
    todos.sort(key=lambda x: (x.get("fecha") or "", x.get("id") or 0), reverse=True)
    return todos[:limite]


def eliminar_evento(origen, evento_id):
    """Borra un evento cargado por error, de la tabla que corresponda."""
    if origen not in ("historial_eventos", "correctivos"):
        return False, "Origen inválido."
    conn = get_connection()
    if origen == "correctivos":
        # Solo permitir borrar correctivos que son de carga histórica
        row = conn.execute(
            "SELECT observaciones FROM correctivos WHERE id=?", (evento_id,)).fetchone()
        if not row or not str(row["observaciones"] or "").startswith("[Historial"):
            conn.close()
            return False, "Ese correctivo no es de carga histórica."
    conn.execute(f"DELETE FROM {origen} WHERE id=?", (evento_id,))
    conn.commit()
    conn.close()
    return True, "Evento eliminado."


def eventos_historial_periodo(vehiculo_id, desde, hasta):
    """Para el dossier: eventos históricos (no-correctivos) de un período."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT fecha, tipo, categoria, descripcion, km, costo, taller
        FROM historial_eventos
        WHERE vehiculo_id=? AND fecha BETWEEN ? AND ?
        ORDER BY fecha DESC
    """, (vehiculo_id, desde, hasta)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ════════════════════════════════════════════════════════════════════════════

def _puede_cargar():
    return session.get("rol") in ("admin", "taller", "compras")


@bp_historial.route("/api/historial_carga/<int:vid>", methods=["GET"])
def api_historial_vehiculo(vid):
    if not _puede_cargar():
        return jsonify({"error": "Sin permiso"}), 403
    return jsonify(obtener_historial_vehiculo(vid))


@bp_historial.route("/api/historial_carga", methods=["POST"])
def api_agregar_evento():
    if not _puede_cargar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    d = request.json or {}
    vid = d.get("vehiculo_id")
    fecha = (d.get("fecha") or "").strip()
    if not vid or not fecha:
        return jsonify({"ok": False, "msg": "Faltan coche o fecha"}), 400
    ok, res = agregar_evento(
        int(vid), fecha, d.get("tipo", "otro"), d.get("descripcion", ""),
        categoria=d.get("categoria", ""), km=d.get("km", 0),
        costo=d.get("costo", 0), taller=d.get("taller", ""),
        usuario=session.get("nombre") or session.get("usuario") or "")
    if not ok:
        return jsonify({"ok": False, "msg": res}), 400
    # Auditoría (import perezoso para evitar circular)
    try:
        from database import registrar_auditoria
        registrar_auditoria(
            usuario=session.get("nombre") or "?", rol=session.get("rol") or "",
            accion=f"Cargó evento histórico ({d.get('tipo','otro')}) del {fecha}",
            categoria="Historial", detalle=d.get("descripcion", "")[:120],
            referencia=f"vehiculo:{vid}")
    except Exception:
        pass
    return jsonify({"ok": True, **res})


@bp_historial.route("/api/historial_carga/<origen>/<int:eid>", methods=["DELETE"])
def api_eliminar_evento(origen, eid):
    if not _puede_cargar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    ok, msg = eliminar_evento(origen, eid)
    return jsonify({"ok": ok, "msg": msg}), (200 if ok else 400)
