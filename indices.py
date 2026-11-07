"""
indices.py — Índices de la base (los «índices de un libro» para las tablas)

Sin índice, para encontrar los ítems de una OT la base tiene que leer TODOS
los ítems de todas las OT. Con pocos datos no se nota; con años de uso, las
pantallas se ponen lentas (en una prueba con 3 años de datos, la tabla de
control tardaba 16 segundos; con estos índices, menos de medio segundo).

Se crean solos al arrancar el sistema, solo si faltan. Cada uno por separado:
si una tabla o columna todavía no existe (porque ese módulo no se usó), se
saltea sin afectar a los demás.

Enganche en app.py (después de crear todas las tablas):
    from indices import crear_indices
    crear_indices()
"""

from db_compat import get_connection, USE_POSTGRES

# (nombre, tabla, columnas). Los de una sola tabla que más se consultan.
INDICES = [
    # Órdenes de trabajo: lo más consultado del sistema
    ("ix_ot_items_ot", "ot_items", "ot_id"),
    ("ix_ot_items_estado", "ot_items", "estado"),
    ("ix_ot_vehiculo", "ordenes_trabajo", "vehiculo_id"),
    ("ix_ot_estado", "ordenes_trabajo", "estado"),
    ("ix_ot_apertura", "ordenes_trabajo", "fecha_apertura"),
    ("ix_ot_fotos_ot", "ot_fotos", "ot_id"),
    ("ix_ot_pedidos_ot", "ot_pedidos", "ot_id"),
    ("ix_ot_pedido_rep_veh", "ot_pedido_reportes", "vehiculo_id"),
    ("ix_ot_fusiones_destino", "ot_fusiones", "destino"),
    # Combustible
    ("ix_comb_vehiculo_fecha", "combustible", "vehiculo_id, fecha"),
    ("ix_comb_fecha", "combustible", "fecha"),
    ("ix_comb_origen", "combustible", "origen"),
    # Historia del coche, costos, documentos, correctivos
    ("ix_hist_vehiculo", "historial_eventos", "vehiculo_id"),
    ("ix_costos_vehiculo", "costos", "vehiculo_id"),
    ("ix_costos_mes", "costos", "mes"),
    ("ix_docs_vehiculo", "documentos", "vehiculo_id"),
    ("ix_docs_venc", "documentos", "fecha_vencimiento"),
    ("ix_correctivos_vehiculo", "correctivos", "vehiculo_id"),
    ("ix_fuera_serv_vehiculo", "fuera_servicio", "vehiculo_id"),
    ("ix_servicios_vehiculo", "servicios", "vehiculo_id"),
    ("ix_neu_inst_vehiculo", "instalaciones_neumaticos", "vehiculo_id"),
    ("ix_neu_inst_neumatico", "instalaciones_neumaticos", "neumatico_id"),
    ("ix_mantreal_tarea", "mantenimientos_realizados", "vehiculo_id, tarea_plan_id"),
    # Repuestos
    ("ix_repmov_repuesto", "repuestos_movimientos", "repuesto_id"),
    ("ix_repmov_fecha", "repuestos_movimientos", "fecha"),
    # Auditoría / historial de acciones (crece todos los días)
    ("ix_auditoria_fecha", "auditoria", "fecha_hora"),
    ("ix_auditoria_usuario", "auditoria", "usuario"),
    # Corporativos
    ("ix_rendcorp_chofer", "rendiciones_corp", "chofer_usuario, fecha_servicio"),
    ("ix_rendcorp_cliente", "rendiciones_corp", "cliente, fecha_servicio"),
    # Tráfico
    ("ix_trafico_versiones_dia", "trafico_versiones", "dia_id, version"),
    # Contabilidad
    ("ix_contab_mov_fecha", "contabilidad_movimientos", "fecha"),
]


def crear_indices():
    """Crea los índices que falten. Nunca frena el arranque del sistema."""
    try:
        conn = get_connection()
    except Exception:
        return
    creados = 0
    # Los que ya están se saltean sin preguntar uno por uno (la base está
    # lejos: cada pregunta es un viaje)
    existentes = set()
    try:
        if USE_POSTGRES:
            existentes = {r["indexname"] for r in conn.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = current_schema()").fetchall()}
        else:
            existentes = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'").fetchall()}
    except Exception:
        existentes = set()
    try:
        for nombre, tabla, columnas in INDICES:
            if nombre in existentes:
                continue
            try:
                conn.execute(f"CREATE INDEX IF NOT EXISTS {nombre} ON {tabla} ({columnas})")
                conn.commit()
                creados += 1
            except Exception:
                # La tabla o la columna no existe en esta base: se sigue con el resto
                try:
                    conn.rollback()
                except Exception:
                    pass
    finally:
        try:
            conn.close()
        except Exception:
            pass
    return creados
