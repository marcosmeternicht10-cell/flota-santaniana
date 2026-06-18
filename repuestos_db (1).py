"""
repuestos_db.py — Inventario de repuestos del depósito (La Santaniana)

Módulo separado para no inflar database.py. Sigue exactamente los mismos
patrones: usa db_compat (SQLite local / PostgreSQL nube), migraciones por
columna, y MAX/cálculos en Python para compatibilidad entre motores.

Modelo:
- Cada repuesto es una fila en 'repuestos' con su código (del fabricante),
  ubicación estructurada (pasillo-estantería-nivel-posición), stock actual,
  stock mínimo y costo unitario.
- Las entradas/salidas se registran en 'repuestos_movimientos' (historial).
  El stock actual se recalcula desde los movimientos para que nunca se
  desincronice (la columna stock_actual es un caché que se actualiza solo).
"""

from db_compat import (get_connection, USE_POSTGRES,
                       IntegrityError, OperationalError, columnas_de_tabla)

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"

# Categorías que reflejan la zonificación del depósito (las 4 zonas del cartel)
CATEGORIAS = [
    "Filtros", "Correas y mangueras", "Lubricantes y aditivos",
    "Rulemanes / rodamientos", "Tensores / bombas", "Embragues / frenos",
    "Eléctricos", "Tornillería / ferretería", "Neumáticos", "Usados recuperables",
    "Varios",
]


# ════════════════════════════════════════════════════════════════════════════
# INICIALIZACIÓN / MIGRACIÓN
# ════════════════════════════════════════════════════════════════════════════

def inicializar_repuestos():
    """Crea las tablas del inventario si no existen, y migra columnas faltantes.

    Llamar esto UNA VEZ desde inicializar_db() de database.py (al final),
    o de forma independiente. Es idempotente: se puede correr siempre."""
    conn = get_connection()
    c = conn.cursor()

    # Catálogo de repuestos
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS repuestos (
            id {PK},
            codigo TEXT NOT NULL UNIQUE,        -- código del fabricante (lo carga el usuario)
            codigo_alt TEXT DEFAULT '',         -- código alternativo / segundo número de parte
            descripcion TEXT NOT NULL,
            categoria TEXT DEFAULT 'Varios',
            marca TEXT DEFAULT '',              -- ej: Mann, Bosch, Fras-le
            aplicacion TEXT DEFAULT '',         -- ej: 'Scania K380', 'Volvo B420'
            -- Ubicación estructurada: Pasillo-Estantería-Nivel-Posición (A-02-03-04)
            ubic_pasillo TEXT DEFAULT '',
            ubic_estanteria TEXT DEFAULT '',
            ubic_nivel TEXT DEFAULT '',
            ubic_posicion TEXT DEFAULT '',
            -- Stock
            stock_actual REAL DEFAULT 0,        -- caché, se recalcula desde movimientos
            stock_minimo REAL DEFAULT 0,
            unidad TEXT DEFAULT 'u',            -- u, litros, metros, kg
            costo_unitario REAL DEFAULT 0,
            proveedor TEXT DEFAULT '',
            observaciones TEXT DEFAULT '',
            activo INTEGER DEFAULT 1,
            fecha_alta TEXT DEFAULT (date('now'))
        )
    """)

    # Migración: si la tabla ya existía sin alguna columna, agregarla
    cols = columnas_de_tabla(conn, "repuestos")
    for col, ddl in [
        ("codigo_alt", "TEXT DEFAULT ''"),
        ("categoria", "TEXT DEFAULT 'Varios'"),
        ("marca", "TEXT DEFAULT ''"),
        ("aplicacion", "TEXT DEFAULT ''"),
        ("ubic_pasillo", "TEXT DEFAULT ''"),
        ("ubic_estanteria", "TEXT DEFAULT ''"),
        ("ubic_nivel", "TEXT DEFAULT ''"),
        ("ubic_posicion", "TEXT DEFAULT ''"),
        ("stock_actual", "REAL DEFAULT 0"),
        ("stock_minimo", "REAL DEFAULT 0"),
        ("unidad", "TEXT DEFAULT 'u'"),
        ("costo_unitario", "REAL DEFAULT 0"),
        ("proveedor", "TEXT DEFAULT ''"),
        ("observaciones", "TEXT DEFAULT ''"),
        ("activo", "INTEGER DEFAULT 1"),
    ]:
        if col not in cols:
            try:
                c.execute(f"ALTER TABLE repuestos ADD COLUMN {col} {ddl}")
            except OperationalError:
                pass

    # Movimientos de stock (historial de entradas y salidas)
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS repuestos_movimientos (
            id {PK},
            repuesto_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            tipo TEXT NOT NULL,             -- 'entrada' | 'salida' | 'ajuste'
            cantidad REAL NOT NULL,         -- siempre positiva; el tipo define el signo
            motivo TEXT DEFAULT '',         -- ej: 'compra', 'uso en OT #45', 'rotura', 'ajuste inventario'
            costo_unitario REAL DEFAULT 0,  -- costo en ese movimiento (para entradas)
            referencia TEXT DEFAULT '',     -- ej: 'OT:45', 'compra:12', factura
            usuario TEXT DEFAULT '',
            observaciones TEXT DEFAULT '',
            FOREIGN KEY (repuesto_id) REFERENCES repuestos(id) ON DELETE CASCADE
        )
    """)

    conn.commit()
    conn.close()


# ════════════════════════════════════════════════════════════════════════════
# HELPERS DE UBICACIÓN
# ════════════════════════════════════════════════════════════════════════════

def _formatear_ubicacion(r):
    """Construye el string 'A-02-03-04' a partir de los 4 campos.
    Omite los vacíos para no mostrar 'A---'."""
    partes = [r.get("ubic_pasillo"), r.get("ubic_estanteria"),
              r.get("ubic_nivel"), r.get("ubic_posicion")]
    partes = [str(p).strip() for p in partes if p and str(p).strip()]
    return "-".join(partes)


def _enriquecer(r):
    """Agrega campos calculados a un dict de repuesto."""
    d = dict(r)
    d["ubicacion"] = _formatear_ubicacion(d)
    stock = float(d.get("stock_actual") or 0)
    minimo = float(d.get("stock_minimo") or 0)
    costo = float(d.get("costo_unitario") or 0)
    d["valor_stock"] = round(stock * costo)
    # Estado de stock para semáforo en la UI
    if stock <= 0:
        d["estado_stock"] = "sin_stock"
    elif minimo > 0 and stock <= minimo:
        d["estado_stock"] = "bajo"
    else:
        d["estado_stock"] = "ok"
    return d


# ════════════════════════════════════════════════════════════════════════════
# CRUD DE REPUESTOS
# ════════════════════════════════════════════════════════════════════════════

def agregar_repuesto(codigo, descripcion, **kwargs):
    """Crea un repuesto nuevo. 'codigo' es del fabricante (único).
    Devuelve (ok, id_o_mensaje).

    kwargs admitidos: codigo_alt, categoria, marca, aplicacion,
    ubic_pasillo, ubic_estanteria, ubic_nivel, ubic_posicion,
    stock_minimo, unidad, costo_unitario, proveedor, observaciones,
    y stock_inicial (cantidad de arranque; genera un movimiento de entrada)."""
    stock_inicial = float(kwargs.pop("stock_inicial", 0) or 0)
    usuario = kwargs.pop("usuario", "")

    campos = {
        "codigo_alt": "", "categoria": "Varios", "marca": "", "aplicacion": "",
        "ubic_pasillo": "", "ubic_estanteria": "", "ubic_nivel": "", "ubic_posicion": "",
        "stock_minimo": 0, "unidad": "u", "costo_unitario": 0,
        "proveedor": "", "observaciones": "",
    }
    campos.update({k: v for k, v in kwargs.items() if k in campos})

    conn = get_connection()
    try:
        cur = conn.execute(f"""
            INSERT INTO repuestos
            (codigo, descripcion, codigo_alt, categoria, marca, aplicacion,
             ubic_pasillo, ubic_estanteria, ubic_nivel, ubic_posicion,
             stock_actual, stock_minimo, unidad, costo_unitario, proveedor, observaciones)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            codigo.upper().strip(), descripcion.strip(),
            str(campos["codigo_alt"]).upper().strip(), campos["categoria"],
            campos["marca"], campos["aplicacion"],
            str(campos["ubic_pasillo"]).upper().strip(),
            str(campos["ubic_estanteria"]).strip(),
            str(campos["ubic_nivel"]).strip(),
            str(campos["ubic_posicion"]).strip(),
            stock_inicial, float(campos["stock_minimo"] or 0),
            campos["unidad"], float(campos["costo_unitario"] or 0),
            campos["proveedor"], campos["observaciones"],
        ))
        rid = cur.lastrowid
        conn.commit()
    except IntegrityError:
        conn.close()
        return False, f"El código '{codigo.upper().strip()}' ya existe."
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # Si vino stock inicial, registrar el movimiento de entrada
    if stock_inicial > 0:
        registrar_movimiento(rid, "entrada", stock_inicial,
                             motivo="Stock inicial",
                             costo_unitario=float(campos["costo_unitario"] or 0),
                             usuario=usuario)
    return True, rid


def actualizar_repuesto(repuesto_id, **kwargs):
    """Actualiza campos del repuesto. NO toca stock_actual directamente
    (eso se hace solo vía movimientos)."""
    permitidos = {
        "codigo", "codigo_alt", "descripcion", "categoria", "marca", "aplicacion",
        "ubic_pasillo", "ubic_estanteria", "ubic_nivel", "ubic_posicion",
        "stock_minimo", "unidad", "costo_unitario", "proveedor", "observaciones",
    }
    campos = {k: v for k, v in kwargs.items() if k in permitidos}
    if not campos:
        return False, "Sin campos para actualizar."
    # Normalizar
    if "codigo" in campos and campos["codigo"]:
        campos["codigo"] = str(campos["codigo"]).upper().strip()
    if "codigo_alt" in campos:
        campos["codigo_alt"] = str(campos["codigo_alt"] or "").upper().strip()
    if "ubic_pasillo" in campos:
        campos["ubic_pasillo"] = str(campos["ubic_pasillo"] or "").upper().strip()

    sets = ", ".join(f"{k}=?" for k in campos.keys())
    valores = list(campos.values()) + [repuesto_id]
    conn = get_connection()
    try:
        conn.execute(f"UPDATE repuestos SET {sets} WHERE id=?", valores)
        conn.commit()
        return True, "Repuesto actualizado."
    except IntegrityError:
        return False, "Ese código ya pertenece a otro repuesto."
    finally:
        conn.close()


def obtener_repuestos(categoria=None, buscar=None, solo_bajos=False, incluir_inactivos=False):
    """Lista repuestos con filtros opcionales.
    - categoria: filtra por categoría exacta
    - buscar: texto libre, busca en código, descripción, marca, aplicación
    - solo_bajos: solo los que están en o bajo el mínimo (o sin stock)
    """
    conn = get_connection()
    q = "SELECT * FROM repuestos WHERE 1=1"
    params = []
    if not incluir_inactivos:
        q += " AND activo=1"
    if categoria:
        q += " AND categoria=?"
        params.append(categoria)
    if buscar:
        like = f"%{buscar.strip().lower()}%"
        q += (" AND (LOWER(codigo) LIKE ? OR LOWER(descripcion) LIKE ?"
              " OR LOWER(codigo_alt) LIKE ? OR LOWER(marca) LIKE ?"
              " OR LOWER(aplicacion) LIKE ?)")
        params += [like, like, like, like, like]
    q += " ORDER BY categoria, descripcion"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    resultado = [_enriquecer(r) for r in rows]
    if solo_bajos:
        resultado = [r for r in resultado if r["estado_stock"] in ("bajo", "sin_stock")]
    return resultado


def obtener_repuesto(repuesto_id):
    """Un repuesto con sus campos calculados y su historial de movimientos."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM repuestos WHERE id=?", (repuesto_id,)).fetchone()
    conn.close()
    if not row:
        return None
    d = _enriquecer(row)
    d["movimientos"] = obtener_movimientos(repuesto_id)
    return d


def eliminar_repuesto(repuesto_id):
    """Da de baja un repuesto (soft delete: activo=0). Conserva el historial."""
    conn = get_connection()
    conn.execute("UPDATE repuestos SET activo=0 WHERE id=?", (repuesto_id,))
    conn.commit()
    conn.close()
    return True, "Repuesto dado de baja."


# ════════════════════════════════════════════════════════════════════════════
# MOVIMIENTOS DE STOCK
# ════════════════════════════════════════════════════════════════════════════

def _recalcular_stock(conn, repuesto_id):
    """Recalcula stock_actual sumando entradas y restando salidas.
    Se hace en Python para no depender de funciones específicas del motor.
    'ajuste' fija el stock directamente al valor de la cantidad."""
    rows = conn.execute(
        "SELECT tipo, cantidad FROM repuestos_movimientos WHERE repuesto_id=? ORDER BY id",
        (repuesto_id,)
    ).fetchall()
    stock = 0.0
    for r in rows:
        tipo = r["tipo"]
        cant = float(r["cantidad"] or 0)
        if tipo == "entrada":
            stock += cant
        elif tipo == "salida":
            stock -= cant
        elif tipo == "ajuste":
            stock = cant  # el ajuste fija el stock al valor contado
    conn.execute("UPDATE repuestos SET stock_actual=? WHERE id=?", (stock, repuesto_id))
    return stock


def registrar_movimiento(repuesto_id, tipo, cantidad, motivo="",
                         costo_unitario=0, referencia="", usuario="",
                         observaciones="", fecha=None):
    """Registra una entrada, salida o ajuste y recalcula el stock.
    Devuelve (ok, dict_con_stock_nuevo o mensaje).

    - entrada: suma al stock (compra, devolución)
    - salida: resta del stock (uso, rotura, baja)
    - ajuste: fija el stock al valor 'cantidad' (inventario físico contado)
    """
    import datetime as _dt
    tipo = (tipo or "").lower().strip()
    if tipo not in ("entrada", "salida", "ajuste"):
        return False, "Tipo inválido (entrada / salida / ajuste)."
    try:
        cantidad = float(cantidad)
    except (ValueError, TypeError):
        return False, "Cantidad inválida."
    if cantidad < 0:
        return False, "La cantidad no puede ser negativa."

    if not fecha:
        fecha = _dt.date.today().isoformat()

    conn = get_connection()

    # Validar que no deje stock negativo en una salida
    if tipo == "salida":
        actual = conn.execute("SELECT stock_actual FROM repuestos WHERE id=?",
                              (repuesto_id,)).fetchone()
        if actual is None:
            conn.close()
            return False, "Repuesto no encontrado."
        if float(actual["stock_actual"] or 0) < cantidad:
            disp = float(actual["stock_actual"] or 0)
            conn.close()
            return False, f"Stock insuficiente: hay {disp:g}, querés sacar {cantidad:g}."

    conn.execute("""
        INSERT INTO repuestos_movimientos
        (repuesto_id, fecha, tipo, cantidad, motivo, costo_unitario,
         referencia, usuario, observaciones)
        VALUES (?,?,?,?,?,?,?,?,?)
    """, (repuesto_id, fecha, tipo, cantidad, motivo,
          float(costo_unitario or 0), referencia, usuario, observaciones))

    # Si es una entrada con costo, actualizar el costo unitario del repuesto
    if tipo == "entrada" and float(costo_unitario or 0) > 0:
        conn.execute("UPDATE repuestos SET costo_unitario=? WHERE id=?",
                    (float(costo_unitario), repuesto_id))

    stock_nuevo = _recalcular_stock(conn, repuesto_id)
    conn.commit()
    conn.close()
    return True, {"stock_actual": stock_nuevo}


def obtener_movimientos(repuesto_id, limite=None):
    """Historial de movimientos de un repuesto, los más recientes primero."""
    conn = get_connection()
    q = """
        SELECT * FROM repuestos_movimientos
        WHERE repuesto_id=? ORDER BY id DESC
    """
    if limite:
        q += f" LIMIT {int(limite)}"
    rows = conn.execute(q, (repuesto_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def eliminar_movimiento(movimiento_id):
    """Borra un movimiento (corrección de error de carga) y recalcula stock."""
    conn = get_connection()
    row = conn.execute("SELECT repuesto_id FROM repuestos_movimientos WHERE id=?",
                      (movimiento_id,)).fetchone()
    if not row:
        conn.close()
        return False, "Movimiento no encontrado."
    rid = row["repuesto_id"]
    conn.execute("DELETE FROM repuestos_movimientos WHERE id=?", (movimiento_id,))
    _recalcular_stock(conn, rid)
    conn.commit()
    conn.close()
    return True, "Movimiento eliminado."


# ════════════════════════════════════════════════════════════════════════════
# RESÚMENES / ALERTAS / DASHBOARD
# ════════════════════════════════════════════════════════════════════════════

def repuestos_bajo_minimo():
    """Lista de repuestos que llegaron al mínimo o se quedaron sin stock.
    Esto alimenta la pantalla de 'pendientes de pedido'."""
    return obtener_repuestos(solo_bajos=True)


def resumen_inventario():
    """KPIs del depósito para el dashboard:
    total de repuestos, valor total del stock, cuántos están bajos/sin stock,
    y desglose por categoría."""
    todos = obtener_repuestos()
    total_items = len(todos)
    valor_total = sum(r["valor_stock"] for r in todos)
    bajos = [r for r in todos if r["estado_stock"] == "bajo"]
    sin_stock = [r for r in todos if r["estado_stock"] == "sin_stock"]

    por_categoria = {}
    for r in todos:
        cat = r.get("categoria") or "Varios"
        if cat not in por_categoria:
            por_categoria[cat] = {"categoria": cat, "cantidad": 0, "valor": 0}
        por_categoria[cat]["cantidad"] += 1
        por_categoria[cat]["valor"] += r["valor_stock"]

    categorias = sorted(por_categoria.values(), key=lambda x: -x["valor"])

    return {
        "total_items": total_items,
        "valor_total": valor_total,
        "cant_bajos": len(bajos),
        "cant_sin_stock": len(sin_stock),
        "por_categoria": categorias,
        "alertas": bajos + sin_stock,  # los que necesitan atención
    }


def categorias_disponibles():
    """Lista de categorías para los selectores del frontend."""
    return CATEGORIAS


if __name__ == "__main__":
    inicializar_repuestos()
    print("Tablas de repuestos inicializadas.")
