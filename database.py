"""
database.py — Gestión de la base de datos (SQLite local / PostgreSQL nube)
Sistema de Gestión de Flota - La Santaniana

Usa db_compat para funcionar con ambos motores automáticamente.
"""

import os
from db_compat import (get_connection, USE_POSTGRES, motor_actual,
                       IntegrityError, OperationalError, columnas_de_tabla)

# Tipo de columna autoincremental según motor
PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"


def inicializar_db():
    conn = get_connection()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS vehiculos (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            patente        TEXT NOT NULL UNIQUE,
            marca          TEXT DEFAULT '',
            modelo         TEXT DEFAULT '',
            año            INTEGER,
            chasis         TEXT DEFAULT '',
            n_interno      TEXT DEFAULT '',
            asientos       INTEGER DEFAULT 0,
            ejes           INTEGER DEFAULT 0,
            tipo           TEXT DEFAULT '',
            activo         INTEGER DEFAULT 1,
            fecha_registro TEXT DEFAULT (date('now'))
        )
    """)

    # Migración: si la tabla existía antes (sin estas columnas), agregarlas
    columnas_existentes = columnas_de_tabla(conn, "vehiculos")
    for col, ddl in [
        ("chasis",    "TEXT DEFAULT ''"),
        ("n_interno", "TEXT DEFAULT ''"),
        ("asientos",  "INTEGER DEFAULT 0"),
        ("ejes",      "INTEGER DEFAULT 0"),
        ("tipo",      "TEXT DEFAULT ''"),
    ]:
        if col not in columnas_existentes:
            try:
                c.execute(f"ALTER TABLE vehiculos ADD COLUMN {col} {ddl}")
            except OperationalError:
                pass

    # Un servicio = UN viaje/recorrido de un coche en una fecha concreta
    c.execute("""
        CREATE TABLE IF NOT EXISTS servicios (
            id                 INTEGER PRIMARY KEY AUTOINCREMENT,
            vehiculo_id        INTEGER NOT NULL,
            fecha              TEXT NOT NULL,          -- YYYY-MM-DD
            km                 REAL DEFAULT 0.0,
            horas              REAL DEFAULT 0.0,
            ingreso            REAL DEFAULT 0.0,       -- ₲ cobrado en ese servicio
            descripcion        TEXT DEFAULT '',
            FOREIGN KEY (vehiculo_id) REFERENCES vehiculos(id)
        )
    """)

    # Costos: también por coche y mes (año-mes como texto "2024-06")
    c.execute("""
        CREATE TABLE IF NOT EXISTS costos (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            vehiculo_id INTEGER NOT NULL,
            mes         TEXT NOT NULL,   -- "2024-06"
            tipo        TEXT NOT NULL,   -- 'variable' | 'fijo_directo' | 'fijo_indirecto'
            concepto    TEXT NOT NULL,
            monto       REAL NOT NULL DEFAULT 0.0,
            FOREIGN KEY (vehiculo_id) REFERENCES vehiculos(id)
        )
    """)

    # ─── MANTENIMIENTO ──────────────────────────────────────────────────────

    # Planes de mantenimiento (biblioteca reutilizable: K380, K420, etc.)
    c.execute("""
        CREATE TABLE IF NOT EXISTS planes_mantenimiento (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre      TEXT NOT NULL UNIQUE,    -- ej: 'Scania K380 / DC12 380'
            descripcion TEXT DEFAULT ''
        )
    """)

    # Tareas de cada plan
    c.execute("""
        CREATE TABLE IF NOT EXISTS tareas_plan (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id         INTEGER NOT NULL,
            tarea           TEXT NOT NULL,          -- ej: 'Aceite de motor'
            intervalo_km    INTEGER NOT NULL,       -- ej: 15000
            categoria       TEXT DEFAULT '',        -- ej: 'Lubricación'
            FOREIGN KEY (plan_id) REFERENCES planes_mantenimiento(id) ON DELETE CASCADE
        )
    """)

    # Asignación de plan a vehículo + odómetro inicial
    c.execute("""
        CREATE TABLE IF NOT EXISTS vehiculo_plan (
            vehiculo_id     INTEGER PRIMARY KEY,
            plan_id         INTEGER NOT NULL,
            km_inicial      REAL DEFAULT 0,         -- km del odómetro cuando se cargó
            FOREIGN KEY (vehiculo_id) REFERENCES vehiculos(id),
            FOREIGN KEY (plan_id) REFERENCES planes_mantenimiento(id)
        )
    """)

    # Mantenimientos realizados en el taller (registro histórico)
    c.execute("""
        CREATE TABLE IF NOT EXISTS mantenimientos_realizados (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            vehiculo_id     INTEGER NOT NULL,
            tarea_plan_id   INTEGER NOT NULL,
            fecha           TEXT NOT NULL,
            km              REAL NOT NULL,          -- km del coche en el momento del servicio
            costo           REAL DEFAULT 0,
            observaciones   TEXT DEFAULT '',
            FOREIGN KEY (vehiculo_id) REFERENCES vehiculos(id),
            FOREIGN KEY (tarea_plan_id) REFERENCES tareas_plan(id)
        )
    """)

    # Mantenimientos correctivos (averías / reparaciones no planificadas)
    c.execute("""
        CREATE TABLE IF NOT EXISTS correctivos (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            vehiculo_id     INTEGER NOT NULL,
            fecha           TEXT NOT NULL,
            km              REAL DEFAULT 0,
            tipo_falla      TEXT NOT NULL,
            descripcion     TEXT NOT NULL,
            reparacion      TEXT DEFAULT '',
            costo           REAL DEFAULT 0,
            taller          TEXT DEFAULT '',
            estado          TEXT DEFAULT 'pendiente',
            observaciones   TEXT DEFAULT '',
            FOREIGN KEY (vehiculo_id) REFERENCES vehiculos(id)
        )
    """)
    # Migración correctivos
    cols_corr = columnas_de_tabla(conn, "correctivos")
    if "observaciones" not in cols_corr:
        try:
            c.execute("ALTER TABLE correctivos ADD COLUMN observaciones TEXT DEFAULT ''")
        except OperationalError:
            pass

    # Documentos del vehículo con vencimiento (VTV, seguro, habilitación)
    c.execute("""
        CREATE TABLE IF NOT EXISTS documentos (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            vehiculo_id     INTEGER NOT NULL,
            tipo            TEXT NOT NULL,          -- 'VTV', 'Seguro', 'Habilitación', 'Cédula', 'Otro'
            nombre          TEXT DEFAULT '',
            fecha_emision   TEXT,
            fecha_vencimiento TEXT NOT NULL,
            proveedor       TEXT DEFAULT '',
            costo           REAL DEFAULT 0,
            observaciones   TEXT DEFAULT '',
            FOREIGN KEY (vehiculo_id) REFERENCES vehiculos(id)
        )
    """)

    # ─── NEUMÁTICOS ─────────────────────────────────────────────────────────

    # Configuración de neumáticos por modelo de chasis
    # (asociada al plan de mantenimiento - misma lógica que motor)
    c.execute("""
        CREATE TABLE IF NOT EXISTS config_neumaticos (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id         INTEGER NOT NULL,        -- vinculado al plan del motor
            configuracion   TEXT NOT NULL,           -- '4x2', '6x2', '8x2'
            cant_posiciones INTEGER NOT NULL,        -- total de ruedas
            medida          TEXT DEFAULT '',         -- '295/80 R22.5'
            presion_dir     REAL DEFAULT 0,          -- presión dirección (psi)
            presion_trac    REAL DEFAULT 0,          -- presión tracción (psi)
            vida_util_km    INTEGER DEFAULT 100000,  -- km estimados
            FOREIGN KEY (plan_id) REFERENCES planes_mantenimiento(id) ON DELETE CASCADE
        )
    """)

    # Catálogo de neumáticos (stock de la empresa)
    # Cada cubierta es una entidad ÚNICA con número de serie
    c.execute("""
        CREATE TABLE IF NOT EXISTS neumaticos (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo          TEXT NOT NULL UNIQUE,    -- código interno: NEU-001, NEU-002
            marca           TEXT DEFAULT '',         -- Michelin, Bridgestone, etc.
            modelo          TEXT DEFAULT '',         -- ej: X Multi D
            medida          TEXT DEFAULT '',         -- ej: 295/80 R22.5
            dot             TEXT DEFAULT '',         -- número DOT del neumático
            fecha_compra    TEXT,
            costo_compra    REAL DEFAULT 0,
            estado          TEXT DEFAULT 'disponible', -- 'disponible', 'instalado', 'reencauche', 'baja'
            km_acumulados   REAL DEFAULT 0,          -- km totales del neumático
            km_actuales_pos REAL DEFAULT 0,          -- km en la posición actual
            reencauches     INTEGER DEFAULT 0,       -- veces que fue reencauchado
            profundidad_mm  REAL DEFAULT 0,          -- profundidad banda rodadura (mm)
            observaciones   TEXT DEFAULT ''
        )
    """)

    # Instalación: qué neumático está en qué posición de qué vehículo
    c.execute("""
        CREATE TABLE IF NOT EXISTS instalaciones_neumaticos (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            neumatico_id    INTEGER NOT NULL,
            vehiculo_id     INTEGER NOT NULL,
            posicion        TEXT NOT NULL,           -- 'DI', 'DD', 'TI-Ext', 'TI-Int', 'TD-Ext', 'TD-Int', 'AI', 'AD'
            fecha_instalacion TEXT NOT NULL,
            km_instalacion  REAL DEFAULT 0,
            fecha_retiro    TEXT,                    -- NULL si está instalado actualmente
            km_retiro       REAL,
            motivo_retiro   TEXT DEFAULT '',         -- 'rotación', 'desgaste', 'pinchazo', 'reencauche', 'baja'
            FOREIGN KEY (neumatico_id) REFERENCES neumaticos(id),
            FOREIGN KEY (vehiculo_id) REFERENCES vehiculos(id)
        )
    """)

    # ─── ÓRDENES DE TRABAJO (OT) ──────────────────────────────────────────
    # Cuando un coche entra al taller, se abre una OT con varios items.
    # Se basa en los reportes que mandan los choferes por WhatsApp.

    c.execute("""
        CREATE TABLE IF NOT EXISTS ordenes_trabajo (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            vehiculo_id     INTEGER NOT NULL,
            fecha_apertura  TEXT NOT NULL,
            fecha_cierre    TEXT,
            km              REAL DEFAULT 0,
            conductor       TEXT DEFAULT '',
            procedencia     TEXT DEFAULT '',           -- ej: "Loreto", "Pedro Juan"
            estado          TEXT DEFAULT 'abierta',    -- 'abierta', 'en_proceso', 'cerrada'
            observaciones   TEXT DEFAULT '',
            FOREIGN KEY (vehiculo_id) REFERENCES vehiculos(id)
        )
    """)

    # Items de cada OT (las líneas individuales del reporte)
    c.execute("""
        CREATE TABLE IF NOT EXISTS ot_items (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            ot_id           INTEGER NOT NULL,
            descripcion     TEXT NOT NULL,
            tipo            TEXT DEFAULT 'control',    -- 'preventivo','correctivo','neumaticos','control','otro'
            estado          TEXT DEFAULT 'pendiente',  -- 'pendiente','en_proceso','completado'
            costo           REAL DEFAULT 0,
            fecha_completado TEXT,
            tecnico         TEXT DEFAULT '',           -- quién hizo el trabajo
            observaciones   TEXT DEFAULT '',
            FOREIGN KEY (ot_id) REFERENCES ordenes_trabajo(id) ON DELETE CASCADE
        )
    """)
    # Migración: agregar columna tecnico si no existe
    cols_items = columnas_de_tabla(conn, "ot_items")
    if "tecnico" not in cols_items:
        try:
            c.execute("ALTER TABLE ot_items ADD COLUMN tecnico TEXT DEFAULT ''")
        except OperationalError:
            pass

    # Cubiertas auxiliares (trucky) que lleva cada coche
    # Esta tabla registra qué cubiertas están a bordo COMO REPUESTO,
    # no instaladas. Cuando se rota una, se mueve al inventario o a una posición.
    c.execute("""
        CREATE TABLE IF NOT EXISTS truckies (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            vehiculo_id     INTEGER NOT NULL,
            neumatico_id    INTEGER NOT NULL,
            fecha_asignacion TEXT NOT NULL,
            km_asignacion   REAL DEFAULT 0,
            fecha_uso       TEXT,                       -- NULL si todavía está a bordo
            km_uso          REAL,
            motivo_uso      TEXT DEFAULT '',            -- ej: 'pinchazo en ruta'
            observaciones   TEXT DEFAULT '',
            FOREIGN KEY (vehiculo_id) REFERENCES vehiculos(id),
            FOREIGN KEY (neumatico_id) REFERENCES neumaticos(id)
        )
    """)

    # ─── USUARIOS (login multiusuario) ─────────────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario         TEXT NOT NULL UNIQUE,
            nombre          TEXT DEFAULT '',
            password_hash   TEXT NOT NULL,
            rol             TEXT DEFAULT 'operador',
            activo          INTEGER DEFAULT 1,
            fecha_creacion  TEXT DEFAULT (date('now')),
            ultimo_acceso   TEXT
        )
    """)

    conn.commit()
    conn.close()


# ── Vehículos ─────────────────────────────────────────────────────────────────

def agregar_vehiculo(patente, marca="", modelo="", año=None,
                      chasis="", n_interno="", asientos=0, ejes=0, tipo=""):
    conn = get_connection()
    try:
        conn.execute(
            """INSERT INTO vehiculos
               (patente, marca, modelo, año, chasis, n_interno, asientos, ejes, tipo)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (patente.upper().strip(), marca.strip(), modelo.strip(), año,
             chasis.strip().upper(), str(n_interno).strip(),
             int(asientos or 0), int(ejes or 0), tipo.strip())
        )
        conn.commit()
        return True, "Vehículo agregado."
    except IntegrityError:
        return False, f"La patente '{patente.upper()}' ya existe."
    finally:
        conn.close()


def actualizar_vehiculo(vid, **kwargs):
    """Actualiza campos específicos de un vehículo."""
    if not kwargs:
        return
    # Normalizar valores de texto
    for k in ['patente', 'chasis']:
        if k in kwargs and kwargs[k]:
            kwargs[k] = str(kwargs[k]).upper().strip()
    campos = ", ".join(f"{k}=?" for k in kwargs.keys())
    valores = list(kwargs.values()) + [vid]
    conn = get_connection()
    conn.execute(f"UPDATE vehiculos SET {campos} WHERE id=?", valores)
    conn.commit()
    conn.close()


def obtener_vehiculos(solo_activos=True):
    conn = get_connection()
    q = "SELECT * FROM vehiculos WHERE activo=1 ORDER BY patente" if solo_activos \
        else "SELECT * FROM vehiculos ORDER BY patente"
    rows = conn.execute(q).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def eliminar_vehiculo(vid):
    conn = get_connection()
    conn.execute("UPDATE vehiculos SET activo=0 WHERE id=?", (vid,))
    conn.commit()
    conn.close()


# ── Servicios ─────────────────────────────────────────────────────────────────

def agregar_servicio(vehiculo_id, fecha, km, horas, ingreso, descripcion=""):
    conn = get_connection()
    conn.execute(
        "INSERT INTO servicios (vehiculo_id, fecha, km, horas, ingreso, descripcion) VALUES (?,?,?,?,?,?)",
        (vehiculo_id, fecha, km, horas, ingreso, descripcion)
    )
    conn.commit()
    conn.close()


def eliminar_servicio(servicio_id):
    conn = get_connection()
    conn.execute("DELETE FROM servicios WHERE id=?", (servicio_id,))
    conn.commit()
    conn.close()


def obtener_servicios_vehiculo(vehiculo_id, mes=None):
    """
    mes = "2024-06" → filtra ese mes.
    mes = None → todos los servicios del vehículo.
    """
    conn = get_connection()
    if mes:
        rows = conn.execute("""
            SELECT s.*, v.patente FROM servicios s
            JOIN vehiculos v ON v.id = s.vehiculo_id
            WHERE s.vehiculo_id=? AND strftime('%Y-%m', s.fecha)=?
            ORDER BY s.fecha DESC
        """, (vehiculo_id, mes)).fetchall()
    else:
        rows = conn.execute("""
            SELECT s.*, v.patente FROM servicios s
            JOIN vehiculos v ON v.id = s.vehiculo_id
            WHERE s.vehiculo_id=?
            ORDER BY s.fecha DESC
        """, (vehiculo_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def obtener_servicios_mes(mes):
    """Todos los servicios de todos los coches en un mes."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT s.*, v.patente, v.marca, v.modelo
        FROM servicios s JOIN vehiculos v ON v.id = s.vehiculo_id
        WHERE strftime('%Y-%m', s.fecha) = ?
        ORDER BY v.patente, s.fecha
    """, (mes,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def meses_con_servicios(vehiculo_id=None):
    """Retorna lista de meses (YYYY-MM) que tienen servicios."""
    conn = get_connection()
    if vehiculo_id:
        rows = conn.execute("""
            SELECT DISTINCT strftime('%Y-%m', fecha) as mes FROM servicios
            WHERE vehiculo_id=? ORDER BY mes DESC
        """, (vehiculo_id,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT DISTINCT strftime('%Y-%m', fecha) as mes FROM servicios
            ORDER BY mes DESC
        """).fetchall()
    conn.close()
    return [r["mes"] for r in rows if r["mes"]]


# ── Costos ────────────────────────────────────────────────────────────────────

def agregar_costo(vehiculo_id, mes, tipo, concepto, monto):
    conn = get_connection()
    conn.execute(
        "INSERT INTO costos (vehiculo_id, mes, tipo, concepto, monto) VALUES (?,?,?,?,?)",
        (vehiculo_id, mes, tipo, concepto, monto)
    )
    conn.commit()
    conn.close()


def eliminar_costo(costo_id):
    conn = get_connection()
    conn.execute("DELETE FROM costos WHERE id=?", (costo_id,))
    conn.commit()
    conn.close()


def obtener_costos(vehiculo_id, mes=None):
    conn = get_connection()
    if mes:
        rows = conn.execute(
            "SELECT * FROM costos WHERE vehiculo_id=? AND mes=? ORDER BY tipo, concepto",
            (vehiculo_id, mes)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM costos WHERE vehiculo_id=? ORDER BY mes DESC, tipo, concepto",
            (vehiculo_id,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Resúmenes agregados ───────────────────────────────────────────────────────

def resumen_por_mes(vehiculo_id):
    """Agrupa servicios por mes: total km, horas, ingreso, cantidad."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT
            strftime('%Y-%m', fecha) as mes,
            COUNT(*) as cantidad,
            SUM(km) as km_total,
            SUM(horas) as horas_total,
            SUM(ingreso) as ingreso_total
        FROM servicios
        WHERE vehiculo_id=?
        GROUP BY mes
        ORDER BY mes DESC
    """, (vehiculo_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def resumen_produccion(vehiculo_id):
    """Acumula toda la producción del vehículo."""
    conn = get_connection()
    row = conn.execute("""
        SELECT
            COUNT(*) as cantidad,
            SUM(km) as km_total,
            SUM(horas) as horas_total,
            SUM(ingreso) as ingreso_total,
            MIN(fecha) as fecha_inicio,
            MAX(fecha) as fecha_fin
        FROM servicios WHERE vehiculo_id=?
    """, (vehiculo_id,)).fetchone()
    conn.close()
    return dict(row) if row else {}


if __name__ == "__main__":
    inicializar_db()
    print("DB inicializada.")


# ════════════════════════════════════════════════════════════════════════════
#  MANTENIMIENTO PREVENTIVO
# ════════════════════════════════════════════════════════════════════════════

# ── Planes de mantenimiento ──────────────────────────────────────────────

def crear_plan(nombre, descripcion=""):
    """Crea un nuevo plan de mantenimiento. Devuelve (ok, id_o_msg)."""
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO planes_mantenimiento (nombre, descripcion) VALUES (?,?)",
            (nombre.strip(), descripcion.strip())
        )
        conn.commit()
        return True, cur.lastrowid
    except IntegrityError:
        return False, f"Ya existe un plan llamado '{nombre}'."
    finally:
        conn.close()


def obtener_planes():
    """Lista todos los planes con la cantidad de tareas que tiene cada uno."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT p.*, (SELECT COUNT(*) FROM tareas_plan t WHERE t.plan_id = p.id) AS cant_tareas,
               (SELECT COUNT(*) FROM vehiculo_plan vp WHERE vp.plan_id = p.id) AS cant_vehiculos
        FROM planes_mantenimiento p
        ORDER BY p.nombre
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def obtener_plan(plan_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM planes_mantenimiento WHERE id=?", (plan_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def eliminar_plan(plan_id):
    conn = get_connection()
    # Verificar que no haya vehículos usando este plan
    n = conn.execute("SELECT COUNT(*) c FROM vehiculo_plan WHERE plan_id=?", (plan_id,)).fetchone()["c"]
    if n > 0:
        conn.close()
        return False, f"No se puede eliminar: {n} vehículo(s) usan este plan."
    conn.execute("DELETE FROM planes_mantenimiento WHERE id=?", (plan_id,))
    conn.commit()
    conn.close()
    return True, "Plan eliminado."


# ── Tareas del plan ──────────────────────────────────────────────────────

def agregar_tarea(plan_id, tarea, intervalo_km, categoria=""):
    conn = get_connection()
    conn.execute(
        "INSERT INTO tareas_plan (plan_id, tarea, intervalo_km, categoria) VALUES (?,?,?,?)",
        (plan_id, tarea.strip(), int(intervalo_km), categoria.strip())
    )
    conn.commit()
    conn.close()


def obtener_tareas_plan(plan_id):
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM tareas_plan WHERE plan_id=? ORDER BY intervalo_km, tarea",
        (plan_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def eliminar_tarea(tarea_id):
    conn = get_connection()
    conn.execute("DELETE FROM tareas_plan WHERE id=?", (tarea_id,))
    conn.commit()
    conn.close()


# ── Asignación de plan a vehículo ────────────────────────────────────────

def asignar_plan(vehiculo_id, plan_id, km_inicial=0):
    """Asigna o reemplaza el plan de un vehículo."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO vehiculo_plan (vehiculo_id, plan_id, km_inicial)
        VALUES (?,?,?)
        ON CONFLICT(vehiculo_id) DO UPDATE SET
            plan_id=excluded.plan_id, km_inicial=excluded.km_inicial
    """, (vehiculo_id, plan_id, km_inicial))
    conn.commit()
    conn.close()


def obtener_plan_vehiculo(vehiculo_id):
    """Plan asignado a un vehículo + sus datos. None si no tiene."""
    conn = get_connection()
    row = conn.execute("""
        SELECT vp.*, p.nombre as plan_nombre, p.descripcion as plan_descripcion
        FROM vehiculo_plan vp
        JOIN planes_mantenimiento p ON p.id = vp.plan_id
        WHERE vp.vehiculo_id=?
    """, (vehiculo_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def desasignar_plan(vehiculo_id):
    conn = get_connection()
    conn.execute("DELETE FROM vehiculo_plan WHERE vehiculo_id=?", (vehiculo_id,))
    conn.commit()
    conn.close()


# ── Kilometraje del vehículo ─────────────────────────────────────────────

def km_actual_vehiculo(vehiculo_id):
    """
    Calcula el km actual del coche:
      km_inicial (de vehiculo_plan, si lo hay) + suma de km de TODOS los servicios.
    """
    conn = get_connection()
    fila = conn.execute("""
        SELECT
            COALESCE((SELECT km_inicial FROM vehiculo_plan WHERE vehiculo_id=?), 0)
          + COALESCE((SELECT SUM(km) FROM servicios WHERE vehiculo_id=?), 0)
          AS km_total
    """, (vehiculo_id, vehiculo_id)).fetchone()
    conn.close()
    return float(fila["km_total"] or 0)


# ── Mantenimientos realizados ────────────────────────────────────────────

def registrar_mantenimiento(vehiculo_id, tarea_plan_id, fecha, km, costo=0, observaciones=""):
    conn = get_connection()
    conn.execute("""
        INSERT INTO mantenimientos_realizados
            (vehiculo_id, tarea_plan_id, fecha, km, costo, observaciones)
        VALUES (?,?,?,?,?,?)
    """, (vehiculo_id, tarea_plan_id, fecha, km, costo, observaciones))
    conn.commit()
    conn.close()


def obtener_historial_mantenimiento(vehiculo_id, limite=None):
    """Devuelve los mantenimientos hechos a un coche, los más recientes primero."""
    conn = get_connection()
    q = """
        SELECT m.*, t.tarea, t.intervalo_km, t.categoria
        FROM mantenimientos_realizados m
        JOIN tareas_plan t ON t.id = m.tarea_plan_id
        WHERE m.vehiculo_id=?
        ORDER BY m.km DESC, m.fecha DESC
    """
    if limite:
        q += f" LIMIT {int(limite)}"
    rows = conn.execute(q, (vehiculo_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def eliminar_mantenimiento(mantenimiento_id):
    conn = get_connection()
    conn.execute("DELETE FROM mantenimientos_realizados WHERE id=?", (mantenimiento_id,))
    conn.commit()
    conn.close()


def estado_mantenimiento(vehiculo_id):
    """
    Calcula el estado de cada tarea del plan para un vehículo:
      - último km en que se hizo (o None si nunca se hizo)
      - próximo km de vencimiento
      - km restantes (puede ser negativo si está vencido)
      - estado: 'ok' | 'pronto' | 'vencido' | 'nunca'

    Devuelve lista de dicts ordenada: vencidos primero, después por km restantes.
    """
    conn = get_connection()
    plan_row = conn.execute(
        "SELECT plan_id FROM vehiculo_plan WHERE vehiculo_id=?",
        (vehiculo_id,)
    ).fetchone()
    if not plan_row:
        conn.close()
        return None  # vehículo sin plan asignado

    plan_id = plan_row["plan_id"]
    km_actual = km_actual_vehiculo(vehiculo_id)
    UMBRAL_PRONTO = 1000  # km

    # Para cada tarea, encontrar el último mantenimiento hecho
    tareas = conn.execute("""
        SELECT t.id, t.tarea, t.intervalo_km, t.categoria,
               MAX(m.km) as ultimo_km,
               (SELECT m2.fecha FROM mantenimientos_realizados m2
                WHERE m2.tarea_plan_id = t.id AND m2.vehiculo_id = ?
                ORDER BY m2.km DESC, m2.fecha DESC LIMIT 1) as ultima_fecha
        FROM tareas_plan t
        LEFT JOIN mantenimientos_realizados m
            ON m.tarea_plan_id = t.id AND m.vehiculo_id = ?
        WHERE t.plan_id = ?
        GROUP BY t.id
        ORDER BY t.intervalo_km, t.tarea
    """, (vehiculo_id, vehiculo_id, plan_id)).fetchall()
    conn.close()

    resultado = []
    for t in tareas:
        intervalo = t["intervalo_km"]
        ultimo_km = t["ultimo_km"]
        if ultimo_km is None:
            # Nunca se hizo → vence al cumplir el intervalo desde 0 (km_inicial)
            proximo_km = intervalo
            restantes = proximo_km - km_actual
            # % de uso (cuánto se usó el intervalo desde el inicio)
            porcentaje = (km_actual / intervalo) * 100 if intervalo else 0
            # Si nunca se hizo, el estado depende del porcentaje
            if porcentaje >= 100:
                estado = "vencido"
            elif porcentaje >= 85:
                estado = "pronto"
            elif porcentaje < 50:
                estado = "ok"
            else:
                estado = "ok"  # entre 50% y 85% sigue OK, no es urgente
        else:
            proximo_km = ultimo_km + intervalo
            restantes = proximo_km - km_actual
            # % de uso del intervalo actual
            km_recorridos_desde_ultimo = km_actual - ultimo_km
            porcentaje = (km_recorridos_desde_ultimo / intervalo) * 100 if intervalo else 0
            if restantes < 0:
                estado = "vencido"
            elif restantes <= UMBRAL_PRONTO:
                estado = "pronto"
            else:
                estado = "ok"

        # Estado gradual (mismo esquema que neumáticos)
        if porcentaje >= 100:
            estado_grad = "vencido"
        elif porcentaje >= 85:
            estado_grad = "atencion"
        elif porcentaje >= 70:
            estado_grad = "regular"
        elif porcentaje >= 50:
            estado_grad = "bueno"
        else:
            estado_grad = "optimo"

        resultado.append({
            "tarea_id": t["id"],
            "tarea": t["tarea"],
            "categoria": t["categoria"],
            "intervalo_km": intervalo,
            "ultimo_km": ultimo_km,
            "ultima_fecha": t["ultima_fecha"],
            "proximo_km": proximo_km,
            "km_restantes": restantes,
            "estado": estado,
            "estado_grad": estado_grad,
            "porcentaje": round(porcentaje, 1),
            "porcentaje_visual": min(100, max(0, round(porcentaje, 1))),
            "km_actual": km_actual,
        })

    # Ordenar: vencidos primero, luego prontos, luego ok (por restantes asc)
    orden = {"vencido": 0, "pronto": 1, "ok": 2}
    resultado.sort(key=lambda x: (orden.get(x["estado"], 3), x["km_restantes"]))
    return resultado


# ════════════════════════════════════════════════════════════════════════════
#  MANTENIMIENTOS CORRECTIVOS (averías)
# ════════════════════════════════════════════════════════════════════════════

def agregar_correctivo(vehiculo_id, fecha, km, tipo_falla, descripcion,
                       reparacion="", costo=0, taller="", estado="pendiente"):
    conn = get_connection()
    conn.execute("""
        INSERT INTO correctivos
            (vehiculo_id, fecha, km, tipo_falla, descripcion, reparacion, costo, taller, estado)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (vehiculo_id, fecha, km, tipo_falla, descripcion, reparacion, costo, taller, estado))
    conn.commit()
    conn.close()


def obtener_correctivos(vehiculo_id=None, estado=None):
    conn = get_connection()
    q = """
        SELECT c.*, v.patente, v.marca, v.modelo
        FROM correctivos c JOIN vehiculos v ON v.id = c.vehiculo_id
        WHERE 1=1
    """
    params = []
    if vehiculo_id:
        q += " AND c.vehiculo_id = ?"
        params.append(vehiculo_id)
    if estado:
        q += " AND c.estado = ?"
        params.append(estado)
    q += " ORDER BY c.fecha DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def actualizar_correctivo(id, **kwargs):
    """Actualiza campos de un correctivo. Útil para cambiar estado, agregar reparación, etc."""
    if not kwargs:
        return
    campos = ", ".join(f"{k}=?" for k in kwargs.keys())
    valores = list(kwargs.values()) + [id]
    conn = get_connection()
    conn.execute(f"UPDATE correctivos SET {campos} WHERE id=?", valores)
    conn.commit()
    conn.close()


def eliminar_correctivo(id):
    conn = get_connection()
    conn.execute("DELETE FROM correctivos WHERE id=?", (id,))
    conn.commit()
    conn.close()


# ════════════════════════════════════════════════════════════════════════════
#  DOCUMENTOS Y VENCIMIENTOS
# ════════════════════════════════════════════════════════════════════════════

def agregar_documento(vehiculo_id, tipo, fecha_vencimiento, nombre="",
                       fecha_emision=None, proveedor="", costo=0, observaciones=""):
    conn = get_connection()
    conn.execute("""
        INSERT INTO documentos
            (vehiculo_id, tipo, nombre, fecha_emision, fecha_vencimiento,
             proveedor, costo, observaciones)
        VALUES (?,?,?,?,?,?,?,?)
    """, (vehiculo_id, tipo, nombre, fecha_emision, fecha_vencimiento,
          proveedor, costo, observaciones))
    conn.commit()
    conn.close()


def obtener_documentos(vehiculo_id=None):
    conn = get_connection()
    if vehiculo_id:
        rows = conn.execute("""
            SELECT d.*, v.patente FROM documentos d
            JOIN vehiculos v ON v.id = d.vehiculo_id
            WHERE d.vehiculo_id=? ORDER BY d.fecha_vencimiento ASC
        """, (vehiculo_id,)).fetchall()
    else:
        rows = conn.execute("""
            SELECT d.*, v.patente, v.marca, v.modelo FROM documentos d
            JOIN vehiculos v ON v.id = d.vehiculo_id
            ORDER BY d.fecha_vencimiento ASC
        """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def actualizar_documento(id, **kwargs):
    if not kwargs:
        return
    campos = ", ".join(f"{k}=?" for k in kwargs.keys())
    valores = list(kwargs.values()) + [id]
    conn = get_connection()
    conn.execute(f"UPDATE documentos SET {campos} WHERE id=?", valores)
    conn.commit()
    conn.close()


def eliminar_documento(id):
    conn = get_connection()
    conn.execute("DELETE FROM documentos WHERE id=?", (id,))
    conn.commit()
    conn.close()


def documentos_proximos_a_vencer(dias=30):
    """Devuelve los documentos que vencen en los próximos N días o ya están vencidos."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT d.*, v.patente, v.marca, v.modelo,
               CAST(julianday(d.fecha_vencimiento) - julianday('now') AS INTEGER) AS dias_restantes
        FROM documentos d
        JOIN vehiculos v ON v.id = d.vehiculo_id
        WHERE v.activo = 1
          AND julianday(d.fecha_vencimiento) - julianday('now') <= ?
        ORDER BY d.fecha_vencimiento ASC
    """, (dias,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ════════════════════════════════════════════════════════════════════════════
#  DASHBOARD GENERAL
# ════════════════════════════════════════════════════════════════════════════

def dashboard_resumen():
    """
    Resumen general de la flota — versión optimizada.
    En vez de hacer 3 consultas por vehículo (lento en la nube), hace pocas
    consultas grandes y arma los datos en memoria.
    """
    conn = get_connection()

    # 1. Todos los vehículos activos (1 consulta)
    vehiculos = [dict(r) for r in conn.execute(
        "SELECT * FROM vehiculos WHERE activo=1 ORDER BY n_interno, patente"
    ).fetchall()]

    # 2. Km actual de TODOS los vehículos de una vez (1 consulta)
    #    km = km_inicial del plan + suma de servicios
    km_por_veh = {}
    for r in conn.execute("""
        SELECT v.id,
            COALESCE((SELECT km_inicial FROM vehiculo_plan WHERE vehiculo_id=v.id), 0)
          + COALESCE((SELECT SUM(km) FROM servicios WHERE vehiculo_id=v.id), 0) AS km_total
        FROM vehiculos v WHERE v.activo=1
    """).fetchall():
        km_por_veh[r["id"]] = float(r["km_total"] or 0)

    # 3. Plan de cada vehículo (1 consulta con JOIN)
    plan_por_veh = {}
    for r in conn.execute("""
        SELECT vp.vehiculo_id, p.nombre AS plan_nombre
        FROM vehiculo_plan vp
        JOIN planes_mantenimiento p ON p.id = vp.plan_id
    """).fetchall():
        plan_por_veh[r["vehiculo_id"]] = r["plan_nombre"]

    # 4. Correctivos pendientes (1 consulta)
    correctivos_pendientes = conn.execute("""
        SELECT COUNT(*) c FROM correctivos
        WHERE estado IN ('pendiente', 'en_reparacion')
    """).fetchone()["c"]

    conn.close()

    # El estado de mantenimiento detallado (vencidos/próximos) es costoso de
    # calcular por vehículo. Para el dashboard mostramos el resumen básico y
    # el estado general según si tiene plan. El detalle de vencimientos se ve
    # al entrar a cada vehículo (módulo Preventivo).
    estado_vehiculos = []
    for v in vehiculos:
        plan_nombre = plan_por_veh.get(v["id"])
        estado_vehiculos.append({
            **v,
            "km_actual": km_por_veh.get(v["id"], 0),
            "plan_nombre": plan_nombre,
            "vencidos": 0,
            "pronto": 0,
            "alertas": [],
            "estado_general": "ok" if plan_nombre else "sin_plan",
        })

    # Documentos próximos a vencer (1 consulta)
    docs_proximos = documentos_proximos_a_vencer(30)

    return {
        "vehiculos_activos": len(vehiculos),
        "mant_vencidos": 0,
        "mant_proximos": 0,
        "docs_proximos": len(docs_proximos),
        "correctivos_pendientes": correctivos_pendientes,
        "vehiculos": estado_vehiculos,
        "documentos_proximos": docs_proximos,
    }


# ════════════════════════════════════════════════════════════════════════════
#  NEUMÁTICOS
# ════════════════════════════════════════════════════════════════════════════

# Configuración estándar de posiciones por configuración de ejes:
POSICIONES_POR_CONFIG = {
    "4x2": ["DI", "DD", "TI-Ext", "TD-Ext"],                              # 4 ruedas (bus chico)
    "6x2": ["DI", "DD", "TI-Ext", "TI-Int", "TD-Ext", "TD-Int"],           # 6 ruedas
    "6x2/3": ["DI", "DD", "TI-Ext", "TI-Int", "TD-Ext", "TD-Int", "AI", "AD"],  # 6x2 + 3er eje
    "8x2": ["DI", "DD", "TI-Ext", "TI-Int", "TD-Ext", "TD-Int", "AI-Ext", "AI-Int", "AD-Ext", "AD-Int"],
    # NUEVO: "4 patas" - 4 ejes / 10 cubiertas (típico bus doble piso Scania K380/K410)
    # Eje 1: dirección (2)  - Eje 2: tracción dual (4)
    # Eje 3: apoyo (2)      - Eje 4: trasero (2)
    "4patas": ["DI", "DD", "TI-Ext", "TI-Int", "TD-Ext", "TD-Int", "AI", "AD", "RI", "RD"],
}

NOMBRE_POSICIONES = {
    "DI": "Dirección Izq.",      "DD": "Dirección Der.",
    "TI-Ext": "Tracción I-Ext.", "TI-Int": "Tracción I-Int.",
    "TD-Ext": "Tracción D-Ext.", "TD-Int": "Tracción D-Int.",
    "AI": "Apoyo Izq.",          "AD": "Apoyo Der.",
    "AI-Ext": "Apoyo I-Ext.",    "AI-Int": "Apoyo I-Int.",
    "AD-Ext": "Apoyo D-Ext.",    "AD-Int": "Apoyo D-Int.",
    "RI": "Trasero Izq.",        "RD": "Trasero Der.",
}


# ── Configuración de neumáticos del modelo ─────────────────────────────────

def crear_config_neumaticos(plan_id, configuracion, medida="", presion_dir=110,
                              presion_trac=120, vida_util_km=100000):
    """Crea o reemplaza la config de neumáticos asociada a un plan/modelo."""
    cant = len(POSICIONES_POR_CONFIG.get(configuracion, []))
    conn = get_connection()
    # Si ya existe, actualizar
    existe = conn.execute(
        "SELECT id FROM config_neumaticos WHERE plan_id=?", (plan_id,)
    ).fetchone()
    if existe:
        conn.execute("""UPDATE config_neumaticos
            SET configuracion=?, cant_posiciones=?, medida=?, presion_dir=?,
                presion_trac=?, vida_util_km=? WHERE plan_id=?""",
            (configuracion, cant, medida, presion_dir, presion_trac, vida_util_km, plan_id))
    else:
        conn.execute("""INSERT INTO config_neumaticos
            (plan_id, configuracion, cant_posiciones, medida, presion_dir, presion_trac, vida_util_km)
            VALUES (?,?,?,?,?,?,?)""",
            (plan_id, configuracion, cant, medida, presion_dir, presion_trac, vida_util_km))
    conn.commit()
    conn.close()


def obtener_config_neumaticos_plan(plan_id):
    """Devuelve la config de neumáticos de un plan."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM config_neumaticos WHERE plan_id=?", (plan_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def obtener_config_neumaticos_vehiculo(vehiculo_id):
    """Devuelve la config de neumáticos del vehículo (vía su plan asignado)."""
    conn = get_connection()
    row = conn.execute("""
        SELECT cn.*, p.nombre as plan_nombre
        FROM config_neumaticos cn
        JOIN planes_mantenimiento p ON p.id = cn.plan_id
        JOIN vehiculo_plan vp ON vp.plan_id = cn.plan_id
        WHERE vp.vehiculo_id = ?
    """, (vehiculo_id,)).fetchone()
    conn.close()
    if row:
        d = dict(row)
        d["posiciones"] = POSICIONES_POR_CONFIG.get(d["configuracion"], [])
        return d
    return None


# ── Inventario de neumáticos ───────────────────────────────────────────────

def agregar_neumatico(codigo, marca="", modelo="", medida="", dot="",
                       fecha_compra=None, costo_compra=0, profundidad_mm=0,
                       observaciones=""):
    """Agrega un neumático nuevo al inventario."""
    conn = get_connection()
    try:
        cur = conn.execute("""INSERT INTO neumaticos
            (codigo, marca, modelo, medida, dot, fecha_compra, costo_compra,
             profundidad_mm, observaciones)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (codigo.upper().strip(), marca, modelo, medida, dot,
             fecha_compra, costo_compra, profundidad_mm, observaciones))
        conn.commit()
        return True, cur.lastrowid
    except IntegrityError:
        return False, f"El código '{codigo}' ya existe."
    finally:
        conn.close()


def obtener_neumaticos(estado=None):
    """Lista neumáticos, opcionalmente filtrados por estado."""
    conn = get_connection()
    q = """
        SELECT n.*,
            (SELECT v.patente FROM instalaciones_neumaticos i
             JOIN vehiculos v ON v.id = i.vehiculo_id
             WHERE i.neumatico_id = n.id AND i.fecha_retiro IS NULL) AS patente_actual,
            (SELECT i.posicion FROM instalaciones_neumaticos i
             WHERE i.neumatico_id = n.id AND i.fecha_retiro IS NULL) AS posicion_actual
        FROM neumaticos n
        WHERE 1=1
    """
    params = []
    if estado:
        q += " AND n.estado = ?"
        params.append(estado)
    q += " ORDER BY n.codigo"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def obtener_neumatico(neumatico_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM neumaticos WHERE id=?", (neumatico_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def eliminar_neumatico(neumatico_id):
    """Da de baja un neumático (solo si no está instalado)."""
    conn = get_connection()
    instalado = conn.execute("""
        SELECT COUNT(*) c FROM instalaciones_neumaticos
        WHERE neumatico_id=? AND fecha_retiro IS NULL
    """, (neumatico_id,)).fetchone()["c"]
    if instalado > 0:
        conn.close()
        return False, "No se puede eliminar: el neumático está instalado en un vehículo."
    conn.execute("DELETE FROM neumaticos WHERE id=?", (neumatico_id,))
    conn.commit()
    conn.close()
    return True, "Neumático eliminado."


def actualizar_neumatico(neumatico_id, **kwargs):
    if not kwargs:
        return
    campos = ", ".join(f"{k}=?" for k in kwargs.keys())
    valores = list(kwargs.values()) + [neumatico_id]
    conn = get_connection()
    conn.execute(f"UPDATE neumaticos SET {campos} WHERE id=?", valores)
    conn.commit()
    conn.close()


# ── Instalaciones ──────────────────────────────────────────────────────────

def instalar_neumatico(neumatico_id, vehiculo_id, posicion, fecha, km_instalacion):
    """Instala un neumático en una posición de un vehículo."""
    conn = get_connection()

    # Verificar que el neumático esté disponible
    n = conn.execute("SELECT * FROM neumaticos WHERE id=?", (neumatico_id,)).fetchone()
    if not n or n["estado"] != "disponible":
        conn.close()
        return False, "El neumático no está disponible."

    # Verificar que la posición esté libre
    en_uso = conn.execute("""
        SELECT i.* FROM instalaciones_neumaticos i
        WHERE i.vehiculo_id=? AND i.posicion=? AND i.fecha_retiro IS NULL
    """, (vehiculo_id, posicion)).fetchone()
    if en_uso:
        conn.close()
        return False, f"Ya hay un neumático instalado en la posición {posicion}. Retiralo primero."

    # Crear instalación + actualizar estado del neumático
    conn.execute("""INSERT INTO instalaciones_neumaticos
        (neumatico_id, vehiculo_id, posicion, fecha_instalacion, km_instalacion)
        VALUES (?,?,?,?,?)""",
        (neumatico_id, vehiculo_id, posicion, fecha, km_instalacion))
    conn.execute("""UPDATE neumaticos SET estado='instalado', km_actuales_pos=0
                    WHERE id=?""", (neumatico_id,))
    conn.commit()
    conn.close()
    return True, "Neumático instalado."


def retirar_neumatico(neumatico_id, fecha_retiro, km_retiro, motivo,
                       nuevo_estado="disponible"):
    """Retira un neumático de su posición actual."""
    conn = get_connection()

    # Encontrar la instalación activa
    inst = conn.execute("""
        SELECT * FROM instalaciones_neumaticos
        WHERE neumatico_id=? AND fecha_retiro IS NULL
    """, (neumatico_id,)).fetchone()
    if not inst:
        conn.close()
        return False, "El neumático no está instalado actualmente."

    # Calcular km recorridos en esa posición
    km_recorridos = max(0, km_retiro - inst["km_instalacion"])

    # Cerrar la instalación
    conn.execute("""UPDATE instalaciones_neumaticos
        SET fecha_retiro=?, km_retiro=?, motivo_retiro=?
        WHERE id=?""", (fecha_retiro, km_retiro, motivo, inst["id"]))

    # Actualizar neumático: sumar km al acumulado y resetear km actual
    conn.execute("""UPDATE neumaticos
        SET km_acumulados = km_acumulados + ?,
            km_actuales_pos = 0,
            estado = ?
        WHERE id=?""", (km_recorridos, nuevo_estado, neumatico_id))

    # Si es reencauche, incrementar contador
    if nuevo_estado == "reencauche":
        conn.execute("UPDATE neumaticos SET reencauches = reencauches + 1 WHERE id=?",
                     (neumatico_id,))

    conn.commit()
    conn.close()
    return True, f"Neumático retirado. {km_recorridos:.0f} km en esa posición."


def obtener_neumaticos_vehiculo(vehiculo_id):
    """Devuelve los neumáticos actualmente instalados en un vehículo, por posición."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT i.*, n.codigo, n.marca, n.modelo, n.medida, n.km_acumulados,
               n.reencauches, n.profundidad_mm, n.dot
        FROM instalaciones_neumaticos i
        JOIN neumaticos n ON n.id = i.neumatico_id
        WHERE i.vehiculo_id = ? AND i.fecha_retiro IS NULL
        ORDER BY i.posicion
    """, (vehiculo_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def historial_neumatico(neumatico_id):
    """Devuelve toda la historia de un neumático: instalaciones, retiros, km."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT i.*, v.patente, v.marca as veh_marca, v.modelo as veh_modelo
        FROM instalaciones_neumaticos i
        JOIN vehiculos v ON v.id = i.vehiculo_id
        WHERE i.neumatico_id = ?
        ORDER BY i.fecha_instalacion DESC
    """, (neumatico_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Estado del neumático (% de vida útil, semáforo gradual) ────────────────

def estado_neumaticos_vehiculo(vehiculo_id):
    """
    Para cada neumático instalado, calcula:
      - km recorridos en esta posición (desde instalación)
      - km totales (acumulado + actual posición)
      - % de uso (0 a 100+)
      - estado gradual:
          'optimo'    → 0-50%   (verde brillante)
          'bueno'     → 50-70%  (verde claro)
          'regular'   → 70-85%  (amarillo)
          'atencion'  → 85-100% (naranja)
          'vencido'   → >100%   (rojo)

    Usa la vida_util_km de la configuración del modelo.
    """
    config = obtener_config_neumaticos_vehiculo(vehiculo_id)
    if not config:
        return None

    vida_util = config["vida_util_km"] or 100000
    km_actual_veh = km_actual_vehiculo(vehiculo_id)
    instalados = obtener_neumaticos_vehiculo(vehiculo_id)

    resultado = []
    for n in instalados:
        # KM recorridos en la posición actual
        km_en_posicion = max(0, km_actual_veh - n["km_instalacion"])
        # KM totales del neumático (anteriores + actual)
        km_totales = n["km_acumulados"] + km_en_posicion
        # % de vida útil consumida
        porcentaje = (km_totales / vida_util) * 100 if vida_util else 0
        # Estado gradual
        if porcentaje >= 100:
            estado = "vencido"
        elif porcentaje >= 85:
            estado = "atencion"
        elif porcentaje >= 70:
            estado = "regular"
        elif porcentaje >= 50:
            estado = "bueno"
        else:
            estado = "optimo"

        resultado.append({
            **n,
            "posicion_nombre": NOMBRE_POSICIONES.get(n["posicion"], n["posicion"]),
            "km_en_posicion": round(km_en_posicion, 0),
            "km_totales": round(km_totales, 0),
            "porcentaje_uso": round(porcentaje, 1),
            "porcentaje_visual": min(100, round(porcentaje, 1)),  # tope visual 100%
            "estado_grad": estado,
            "vida_util_km": vida_util,
            "km_restantes": max(0, vida_util - km_totales),
        })

    # Llenar las posiciones vacías (sin neumático asignado)
    posiciones_ocupadas = {n["posicion"] for n in resultado}
    todas_posiciones = config["posiciones"]
    for pos in todas_posiciones:
        if pos not in posiciones_ocupadas:
            resultado.append({
                "posicion": pos,
                "posicion_nombre": NOMBRE_POSICIONES.get(pos, pos),
                "vacia": True,
            })

    # Ordenar por posición canónica
    orden_pos = {p: i for i, p in enumerate(todas_posiciones)}
    resultado.sort(key=lambda x: orden_pos.get(x["posicion"], 99))

    return {
        "configuracion": config["configuracion"],
        "medida": config["medida"],
        "vida_util_km": vida_util,
        "presion_dir": config["presion_dir"],
        "presion_trac": config["presion_trac"],
        "neumaticos": resultado,
        "km_actual_vehiculo": km_actual_veh,
    }


# ════════════════════════════════════════════════════════════════════════════
#  ÓRDENES DE TRABAJO (OT)
# ════════════════════════════════════════════════════════════════════════════

def crear_ot(vehiculo_id, fecha_apertura, km=0, conductor="", procedencia="",
             observaciones="", items=None):
    """
    Crea una OT con sus items.
    items: lista de dicts [{descripcion, tipo, costo}]
    """
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO ordenes_trabajo
            (vehiculo_id, fecha_apertura, km, conductor, procedencia, observaciones)
        VALUES (?,?,?,?,?,?)
    """, (vehiculo_id, fecha_apertura, km, conductor, procedencia, observaciones))
    ot_id = cur.lastrowid

    if items:
        for it in items:
            cur.execute("""INSERT INTO ot_items
                (ot_id, descripcion, tipo, estado, costo)
                VALUES (?,?,?,?,?)""",
                (ot_id, it["descripcion"], it.get("tipo", "control"),
                 it.get("estado", "pendiente"), it.get("costo", 0)))
    conn.commit()
    conn.close()
    return ot_id


def obtener_ot(ot_id):
    conn = get_connection()
    ot = conn.execute("""
        SELECT o.*, v.patente, v.marca, v.modelo, v.n_interno
        FROM ordenes_trabajo o
        JOIN vehiculos v ON v.id = o.vehiculo_id
        WHERE o.id=?
    """, (ot_id,)).fetchone()
    if not ot:
        conn.close()
        return None
    items = conn.execute("""
        SELECT * FROM ot_items WHERE ot_id=? ORDER BY id
    """, (ot_id,)).fetchall()
    conn.close()
    ot = dict(ot)
    ot["items"] = [dict(i) for i in items]
    return ot


def obtener_ots(estado=None, vehiculo_id=None, desde=None, hasta=None):
    """Lista OTs con filtros opcionales y conteo de items."""
    conn = get_connection()
    q = """
        SELECT o.*, v.patente, v.marca, v.modelo, v.n_interno,
            (SELECT COUNT(*) FROM ot_items WHERE ot_id=o.id) AS total_items,
            (SELECT COUNT(*) FROM ot_items WHERE ot_id=o.id AND estado='completado') AS items_completados,
            (SELECT SUM(costo) FROM ot_items WHERE ot_id=o.id) AS costo_total
        FROM ordenes_trabajo o
        JOIN vehiculos v ON v.id = o.vehiculo_id
        WHERE 1=1
    """
    params = []
    if estado:
        q += " AND o.estado=?"; params.append(estado)
    if vehiculo_id:
        q += " AND o.vehiculo_id=?"; params.append(vehiculo_id)
    if desde:
        q += " AND o.fecha_apertura >= ?"; params.append(desde)
    if hasta:
        q += " AND o.fecha_apertura <= ?"; params.append(hasta)
    q += " ORDER BY o.fecha_apertura DESC, o.id DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def agregar_item_ot(ot_id, descripcion, tipo="control", costo=0, observaciones=""):
    conn = get_connection()
    conn.execute("""INSERT INTO ot_items
        (ot_id, descripcion, tipo, costo, observaciones)
        VALUES (?,?,?,?,?)""",
        (ot_id, descripcion, tipo, costo, observaciones))
    conn.commit()
    conn.close()


def actualizar_item_ot(item_id, **kwargs):
    if not kwargs:
        return
    # Si se marca como completado, registrar fecha
    if kwargs.get("estado") == "completado" and "fecha_completado" not in kwargs:
        from datetime import date
        kwargs["fecha_completado"] = date.today().isoformat()
    campos = ", ".join(f"{k}=?" for k in kwargs.keys())
    valores = list(kwargs.values()) + [item_id]
    conn = get_connection()
    conn.execute(f"UPDATE ot_items SET {campos} WHERE id=?", valores)
    conn.commit()

    # Si el item quedó completado y es CORRECTIVO, espejar al módulo de correctivos
    if kwargs.get("estado") == "completado":
        item = conn.execute("""
            SELECT i.*, o.vehiculo_id, o.km, o.id AS ot_id
            FROM ot_items i JOIN ordenes_trabajo o ON o.id = i.ot_id
            WHERE i.id=?""", (item_id,)).fetchone()
        if item and item["tipo"] == "correctivo":
            # Verificar que no esté ya espejado (busca por descripción + ot_id en observaciones)
            marca_espejo = f"[OT#{item['ot_id']}-item{item_id}]"
            ya_existe = conn.execute("""
                SELECT id FROM correctivos WHERE observaciones LIKE ?
            """, (f"%{marca_espejo}%",)).fetchone()
            if not ya_existe:
                conn.execute("""
                    INSERT INTO correctivos
                        (vehiculo_id, fecha, km, tipo_falla, descripcion,
                         reparacion, costo, taller, estado, observaciones)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    item["vehiculo_id"],
                    kwargs.get("fecha_completado") or item["fecha_completado"],
                    item["km"] or 0,
                    "OT correctivo",  # tipo_falla genérico
                    item["descripcion"],
                    item["descripcion"],
                    item["costo"] or 0,
                    "Taller propio",
                    "completado",
                    f"Generado automáticamente desde OT {marca_espejo}",
                ))
                conn.commit()

    conn.close()


def eliminar_item_ot(item_id):
    conn = get_connection()
    conn.execute("DELETE FROM ot_items WHERE id=?", (item_id,))
    conn.commit()
    conn.close()


def actualizar_ot(ot_id, **kwargs):
    if not kwargs:
        return
    campos = ", ".join(f"{k}=?" for k in kwargs.keys())
    valores = list(kwargs.values()) + [ot_id]
    conn = get_connection()
    conn.execute(f"UPDATE ordenes_trabajo SET {campos} WHERE id=?", valores)
    conn.commit()
    conn.close()


def cerrar_ot(ot_id, fecha_cierre=None):
    """Marca una OT como cerrada y opcionalmente registra la fecha."""
    from datetime import date
    fecha = fecha_cierre or date.today().isoformat()
    conn = get_connection()
    conn.execute("""UPDATE ordenes_trabajo
        SET estado='cerrada', fecha_cierre=? WHERE id=?""", (fecha, ot_id))
    conn.commit()
    conn.close()


def eliminar_ot(ot_id):
    conn = get_connection()
    conn.execute("DELETE FROM ot_items WHERE ot_id=?", (ot_id,))
    conn.execute("DELETE FROM ordenes_trabajo WHERE id=?", (ot_id,))
    conn.commit()
    conn.close()


# ════════════════════════════════════════════════════════════════════════════
#  CUBIERTAS AUXILIARES (TRUCKY)
# ════════════════════════════════════════════════════════════════════════════

def asignar_trucky(vehiculo_id, neumatico_id, fecha_asignacion, km_asignacion=0,
                    observaciones=""):
    """Asigna una cubierta como trucky (auxiliar a bordo) de un vehículo."""
    conn = get_connection()
    # Verificar que el neumático esté disponible
    n = conn.execute("SELECT estado FROM neumaticos WHERE id=?",
                      (neumatico_id,)).fetchone()
    if not n or n["estado"] != "disponible":
        conn.close()
        return False, "El neumático no está disponible."

    conn.execute("""INSERT INTO truckies
        (vehiculo_id, neumatico_id, fecha_asignacion, km_asignacion, observaciones)
        VALUES (?,?,?,?,?)""",
        (vehiculo_id, neumatico_id, fecha_asignacion, km_asignacion, observaciones))
    # Marcar el neumático como "trucky" (a bordo pero no instalado)
    conn.execute("UPDATE neumaticos SET estado='trucky' WHERE id=?", (neumatico_id,))
    conn.commit()
    conn.close()
    return True, "Trucky asignado."


def obtener_truckies_vehiculo(vehiculo_id):
    """Devuelve las cubiertas auxiliares actualmente a bordo del vehículo."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT t.*, n.codigo, n.marca, n.modelo, n.medida, n.km_acumulados, n.reencauches
        FROM truckies t
        JOIN neumaticos n ON n.id = t.neumatico_id
        WHERE t.vehiculo_id = ? AND t.fecha_uso IS NULL
        ORDER BY t.fecha_asignacion DESC
    """, (vehiculo_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def usar_trucky(trucky_id, fecha_uso, km_uso, motivo=""):
    """Marca una trucky como usada (ya no está a bordo)."""
    conn = get_connection()
    t = conn.execute("SELECT neumatico_id FROM truckies WHERE id=?",
                      (trucky_id,)).fetchone()
    if not t:
        conn.close()
        return False, "Trucky no encontrada."
    conn.execute("""UPDATE truckies
        SET fecha_uso=?, km_uso=?, motivo_uso=? WHERE id=?""",
        (fecha_uso, km_uso, motivo, trucky_id))
    # Devolver el neumático a "disponible"
    conn.execute("UPDATE neumaticos SET estado='disponible' WHERE id=?",
                  (t["neumatico_id"],))
    conn.commit()
    conn.close()
    return True, "Trucky marcada como usada."


def retirar_trucky(trucky_id):
    """Saca una trucky del vehículo sin usar (vuelve al inventario disponible)."""
    return usar_trucky(trucky_id, "", 0, "retirada del coche")


# ════════════════════════════════════════════════════════════════════════════
#  REPORTE GERENCIAL
# ════════════════════════════════════════════════════════════════════════════

def reporte_gerencial(desde, hasta):
    """
    Genera un resumen gerencial de toda la flota entre dos fechas:
      - Cantidad de OTs, items por tipo, costos
      - Mantenimientos preventivos hechos
      - Correctivos
      - Cambios de neumáticos
      - Top vehículos por costo
      - Documentos por vencer
    """
    conn = get_connection()

    # OTs en el período
    ots = conn.execute("""
        SELECT o.*, v.patente, v.n_interno,
            (SELECT SUM(costo) FROM ot_items WHERE ot_id=o.id) AS costo_total,
            (SELECT COUNT(*) FROM ot_items WHERE ot_id=o.id) AS items_total,
            (SELECT COUNT(*) FROM ot_items WHERE ot_id=o.id AND estado='completado') AS items_completados
        FROM ordenes_trabajo o
        JOIN vehiculos v ON v.id = o.vehiculo_id
        WHERE o.fecha_apertura BETWEEN ? AND ?
    """, (desde, hasta)).fetchall()

    # Items por tipo
    items_por_tipo = conn.execute("""
        SELECT i.tipo, COUNT(*) AS cant, COALESCE(SUM(i.costo),0) AS costo
        FROM ot_items i
        JOIN ordenes_trabajo o ON o.id = i.ot_id
        WHERE o.fecha_apertura BETWEEN ? AND ?
        GROUP BY i.tipo
    """, (desde, hasta)).fetchall()

    # Mantenimientos preventivos realizados
    preventivos = conn.execute("""
        SELECT COUNT(*) AS cant, COALESCE(SUM(costo),0) AS costo
        FROM mantenimientos_realizados
        WHERE fecha BETWEEN ? AND ?
    """, (desde, hasta)).fetchone()

    # Correctivos en el período
    correctivos = conn.execute("""
        SELECT COUNT(*) AS cant, COALESCE(SUM(costo),0) AS costo
        FROM correctivos
        WHERE fecha BETWEEN ? AND ?
    """, (desde, hasta)).fetchone()

    # Cambios de neumáticos (retiros)
    neumaticos = conn.execute("""
        SELECT COUNT(*) AS cant
        FROM instalaciones_neumaticos
        WHERE fecha_retiro BETWEEN ? AND ?
    """, (desde, hasta)).fetchone()

    # Top vehículos por costo total (OT + preventivo + correctivo)
    top_vehiculos = conn.execute("""
        SELECT v.id, v.patente, v.n_interno, v.marca, v.modelo,
            (COALESCE((SELECT SUM(costo) FROM ot_items i JOIN ordenes_trabajo o ON o.id=i.ot_id
                       WHERE o.vehiculo_id=v.id AND o.fecha_apertura BETWEEN ? AND ?), 0) +
             COALESCE((SELECT SUM(costo) FROM mantenimientos_realizados
                       WHERE vehiculo_id=v.id AND fecha BETWEEN ? AND ?), 0) +
             COALESCE((SELECT SUM(costo) FROM correctivos
                       WHERE vehiculo_id=v.id AND fecha BETWEEN ? AND ?), 0)) AS costo_total
        FROM vehiculos v
        WHERE v.activo=1
        ORDER BY costo_total DESC
        LIMIT 10
    """, (desde, hasta, desde, hasta, desde, hasta)).fetchall()

    # Documentos próximos a vencer (30 días) o vencidos
    docs_proximos = conn.execute("""
        SELECT d.tipo, d.nombre, d.fecha_vencimiento, v.patente,
            CAST(julianday(d.fecha_vencimiento) - julianday('now') AS INTEGER) AS dias_restantes
        FROM documentos d
        JOIN vehiculos v ON v.id = d.vehiculo_id
        WHERE v.activo=1
          AND julianday(d.fecha_vencimiento) - julianday('now') <= 30
        ORDER BY d.fecha_vencimiento ASC
        LIMIT 20
    """).fetchall()

    conn.close()

    # Costos
    costo_ots = sum(o["costo_total"] or 0 for o in ots)
    costo_prev = preventivos["costo"] or 0
    costo_corr = correctivos["costo"] or 0

    # ─── Datos adicionales para las páginas técnicas del PDF ──────────────
    conn2 = get_connection()

    # 1. Detalle de cada OT con sus items
    ots_detalle = []
    for o in ots:
        items = conn2.execute("""
            SELECT * FROM ot_items WHERE ot_id=? ORDER BY id
        """, (o["id"],)).fetchall()
        d = dict(o)
        d["items"] = [dict(i) for i in items]
        ots_detalle.append(d)

    # 2. Técnicos involucrados (de los items de OT del período)
    tecnicos_raw = conn2.execute("""
        SELECT i.tecnico,
               COUNT(*) AS total,
               SUM(CASE WHEN i.tipo='preventivo' THEN 1 ELSE 0 END) AS preventivos,
               SUM(CASE WHEN i.tipo='correctivo' THEN 1 ELSE 0 END) AS correctivos,
               COALESCE(SUM(i.costo),0) AS costo
        FROM ot_items i
        JOIN ordenes_trabajo o ON o.id = i.ot_id
        WHERE o.fecha_apertura BETWEEN ? AND ?
          AND i.tecnico IS NOT NULL AND TRIM(i.tecnico) != ''
        GROUP BY i.tecnico
        ORDER BY total DESC
    """, (desde, hasta)).fetchall()
    tecnicos = [{"nombre": t["tecnico"], "total": t["total"],
                 "preventivos": t["preventivos"], "correctivos": t["correctivos"],
                 "costo": t["costo"]} for t in tecnicos_raw]

    # 3. Desglose de costos por vehículo y tipo (solo los que tienen gasto)
    desglose = conn2.execute("""
        SELECT v.patente, v.n_interno,
            COALESCE(SUM(CASE WHEN i.tipo='preventivo' THEN i.costo ELSE 0 END),0) AS preventivo,
            COALESCE(SUM(CASE WHEN i.tipo='correctivo' THEN i.costo ELSE 0 END),0) AS correctivo,
            COALESCE(SUM(CASE WHEN i.tipo='neumaticos' THEN i.costo ELSE 0 END),0) AS neumaticos,
            COALESCE(SUM(CASE WHEN i.tipo IN ('control','otro') THEN i.costo ELSE 0 END),0) AS otro,
            COALESCE(SUM(i.costo),0) AS total
        FROM ot_items i
        JOIN ordenes_trabajo o ON o.id = i.ot_id
        JOIN vehiculos v ON v.id = o.vehiculo_id
        WHERE o.fecha_apertura BETWEEN ? AND ?
        GROUP BY v.id
        HAVING total > 0
        ORDER BY total DESC
    """, (desde, hasta)).fetchall()
    desglose_por_vehiculo = [dict(d) for d in desglose]

    conn2.close()

    return {
        "desde": desde, "hasta": hasta,
        "ots": [dict(o) for o in ots],
        "items_por_tipo": [dict(i) for i in items_por_tipo],
        "preventivos_count": preventivos["cant"],
        "preventivos_costo": costo_prev,
        "correctivos_count": correctivos["cant"],
        "correctivos_costo": costo_corr,
        "cambios_neumaticos": neumaticos["cant"],
        "top_vehiculos": [dict(t) for t in top_vehiculos if (t["costo_total"] or 0) > 0],
        "docs_proximos": [dict(d) for d in docs_proximos],
        "costo_total": costo_ots + costo_prev + costo_corr,
        "costo_ots": costo_ots,
        # Datos para páginas técnicas:
        "ots_detalle": ots_detalle,
        "tecnicos": tecnicos,
        "desglose_por_vehiculo": desglose_por_vehiculo,
    }


# ════════════════════════════════════════════════════════════════════════════
#  USUARIOS Y AUTENTICACIÓN
# ════════════════════════════════════════════════════════════════════════════
import hashlib
import secrets

def _hash_password(password, salt=None):
    """Hashea una contraseña con PBKDF2 + salt (seguro)."""
    if salt is None:
        salt = secrets.token_hex(16)
    pwd_hash = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'),
                                    salt.encode('utf-8'), 100000)
    return f"{salt}${pwd_hash.hex()}"

def _verificar_password(password, password_hash):
    """Verifica una contraseña contra su hash almacenado."""
    try:
        salt, _ = password_hash.split('$', 1)
        return _hash_password(password, salt) == password_hash
    except (ValueError, AttributeError):
        return False


def crear_usuario(usuario, password, nombre="", rol="operador"):
    """Crea un nuevo usuario. rol: 'admin', 'operador', 'consulta'."""
    conn = get_connection()
    try:
        conn.execute("""INSERT INTO usuarios (usuario, nombre, password_hash, rol)
                        VALUES (?,?,?,?)""",
                     (usuario.lower().strip(), nombre.strip(),
                      _hash_password(password), rol))
        conn.commit()
        return True, "Usuario creado."
    except IntegrityError:
        return False, f"El usuario '{usuario}' ya existe."
    finally:
        conn.close()


def autenticar_usuario(usuario, password):
    """Verifica credenciales. Devuelve el usuario (dict) si son válidas, o None."""
    conn = get_connection()
    u = conn.execute("SELECT * FROM usuarios WHERE usuario=? AND activo=1",
                     (usuario.lower().strip(),)).fetchone()
    if u and _verificar_password(password, u["password_hash"]):
        # Registrar último acceso
        from datetime import datetime
        conn.execute("UPDATE usuarios SET ultimo_acceso=? WHERE id=?",
                     (datetime.now().isoformat(timespec='seconds'), u["id"]))
        conn.commit()
        conn.close()
        return {"id": u["id"], "usuario": u["usuario"],
                "nombre": u["nombre"], "rol": u["rol"]}
    conn.close()
    return None


def obtener_usuarios():
    conn = get_connection()
    rows = conn.execute("""SELECT id, usuario, nombre, rol, activo,
                           fecha_creacion, ultimo_acceso FROM usuarios
                           ORDER BY usuario""").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def actualizar_usuario(uid, **kwargs):
    """Actualiza datos de un usuario. Si viene 'password', la hashea."""
    if "password" in kwargs:
        pwd = kwargs.pop("password")
        if pwd:
            kwargs["password_hash"] = _hash_password(pwd)
    if not kwargs:
        return
    campos = ", ".join(f"{k}=?" for k in kwargs.keys())
    valores = list(kwargs.values()) + [uid]
    conn = get_connection()
    conn.execute(f"UPDATE usuarios SET {campos} WHERE id=?", valores)
    conn.commit()
    conn.close()


def eliminar_usuario(uid):
    conn = get_connection()
    conn.execute("DELETE FROM usuarios WHERE id=?", (uid,))
    conn.commit()
    conn.close()


def contar_usuarios():
    conn = get_connection()
    n = conn.execute("SELECT COUNT(*) c FROM usuarios").fetchone()["c"]
    conn.close()
    return n


def crear_admin_por_defecto():
    """Crea un admin inicial si no hay ningún usuario. Devuelve credenciales."""
    if contar_usuarios() == 0:
        crear_usuario("admin", "santaniana2026", "Administrador", "admin")
        return ("admin", "santaniana2026")
    return None
