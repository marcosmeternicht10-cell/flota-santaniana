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

    # Proveedores con su contacto. Se guardan una sola vez por nombre: al
    # cargar otro repuesto del mismo proveedor el contacto se completa solo,
    # y si cambia el teléfono se corrige en un lugar y vale para todos.
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS repuestos_proveedores (
            id {PK},
            clave TEXT NOT NULL UNIQUE,     -- el nombre en minúsculas, para no duplicar
            nombre TEXT NOT NULL,
            contacto TEXT DEFAULT '',       -- la persona con la que se habla
            telefono TEXT DEFAULT '',
            actualizado TEXT DEFAULT ''
        )
    """)
    cols = columnas_de_tabla(conn, "repuestos_proveedores")
    # codigo, ruc, direccion y email vienen del listado de la empresa; el
    # nombre de fantasía (cómo lo conoce la gente) se carga a mano
    for col in ("codigo", "ruc", "direccion", "email", "fantasia"):
        if col not in cols:
            try:
                c.execute(f"ALTER TABLE repuestos_proveedores ADD COLUMN {col} TEXT DEFAULT ''")
            except OperationalError:
                pass

    conn.commit()
    conn.close()

    try:
        importar_lista_proveedores()
    except Exception as e:
        print("[proveedores] no se pudo importar el listado:", e)


# ════════════════════════════════════════════════════════════════════════════
# PROVEEDORES
# ════════════════════════════════════════════════════════════════════════════

def _sin_tildes(texto):
    """'El Rápido' → 'el rapido': para buscar sin depender de las tildes."""
    import unicodedata
    t = unicodedata.normalize("NFD", str(texto or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _col_sin_tildes(col):
    """La misma idea del lado de la base. En PostgreSQL se sacan las tildes
    con translate; la base local de pruebas (SQLite) no lo tiene."""
    if USE_POSTGRES:
        return f"translate(LOWER({col}), 'áéíóúüñàèìòùâêîôû', 'aeiouunaeiouaeiou')"
    return f"LOWER({col})"


def _clave_proveedor(nombre):
    return " ".join(str(nombre or "").split()).lower()


def _siguiente_codigo(conn):
    """El número que le toca a un proveedor nuevo: el siguiente al más alto,
    así sigue la misma numeración del listado de la empresa."""
    mayor = 0
    for r in conn.execute("SELECT codigo FROM repuestos_proveedores WHERE codigo<>''").fetchall():
        c = str(r["codigo"]).strip()
        if c.isdigit():
            mayor = max(mayor, int(c))
    return str(mayor + 1)


def guardar_contacto_proveedor(nombre, contacto=None, telefono=None):
    """Crea el proveedor o actualiza su contacto. Un dato que no viene (None)
    no se toca; uno que viene vacío tampoco borra lo que ya había, así un
    formulario incompleto no pierde el teléfono guardado.

    Devuelve el nombre tal como quedó guardado la primera vez, así "repuestos
    del este" y "Repuestos del Este" terminan siendo el mismo proveedor."""
    clave = _clave_proveedor(nombre)
    if not clave:
        return ""
    nombre = " ".join(str(nombre).split())
    contacto = " ".join(str(contacto or "").split())
    telefono = " ".join(str(telefono or "").split())
    from hora_local import hoy
    conn = get_connection()
    try:
        fila = conn.execute("SELECT id, nombre, contacto, telefono FROM repuestos_proveedores WHERE clave=?",
                            (clave,)).fetchone()
        if fila:
            nombre = fila["nombre"]
            conn.execute("""UPDATE repuestos_proveedores
                            SET contacto=?, telefono=?, actualizado=? WHERE id=?""",
                         (contacto or fila["contacto"] or "",
                          telefono or fila["telefono"] or "", hoy(), fila["id"]))
        else:
            conn.execute("""INSERT INTO repuestos_proveedores
                            (clave, nombre, contacto, telefono, actualizado, codigo) VALUES (?,?,?,?,?,?)""",
                         (clave, nombre, contacto, telefono, hoy(), _siguiente_codigo(conn)))
        conn.commit()
    except IntegrityError:
        pass
    finally:
        conn.close()
    return nombre


CAMPOS_PROV = ("nombre", "fantasia", "codigo", "ruc", "contacto", "telefono", "direccion", "email")


def importar_lista_proveedores(ruta=None):
    """Carga el listado de proveedores de la empresa (proveedores_lista.json,
    sacado del sistema contable) la primera vez que encuentra la tabla sin él.

    No pisa nada que ya se haya cargado a mano: si el proveedor ya existe, solo
    completa los datos que le faltan (RUC, teléfono, dirección...). Se inserta
    en tandas para no hacer miles de viajes a la base al arrancar.
    """
    import json, os
    ruta = ruta or os.path.join(os.path.dirname(os.path.abspath(__file__)), "proveedores_lista.json")
    if not os.path.exists(ruta):
        return 0
    conn = get_connection()
    try:
        # Ya importado: hay miles con número. Unos pocos con número son los
        # que se agregaron a mano, y no cuentan como listado cargado.
        ya = conn.execute("SELECT COUNT(*) AS n FROM repuestos_proveedores WHERE codigo<>''").fetchone()
        if ya and int(ya["n"] or 0) >= 1000:
            return 0
        lista = json.load(open(ruta, encoding="utf-8"))

        # Un mismo nombre puede venir dos veces: queda el que trae más datos
        por_clave = {}
        for p in lista:
            k = _clave_proveedor(p.get("nombre"))
            if not k:
                continue
            datos = sum(1 for c in ("ruc", "telefono", "direccion", "email") if p.get(c))
            if k not in por_clave or datos > por_clave[k][0]:
                por_clave[k] = (datos, p)

        existentes = {r["clave"]: dict(r) for r in conn.execute(
            "SELECT id, clave, codigo, ruc, telefono, direccion, email FROM repuestos_proveedores").fetchall()}
        from hora_local import hoy
        hoy_s = hoy()
        nuevos = []
        for k, (_, p) in por_clave.items():
            fila = (str(p.get("codigo", "")), p.get("ruc", ""), p.get("telefono", ""),
                    p.get("direccion", ""), p.get("email", ""))
            if k in existentes:
                e = existentes[k]
                # El nombre pasa a ser el oficial del listado (el de la factura)
                conn.execute("""UPDATE repuestos_proveedores SET nombre=?, codigo=?, ruc=?,
                                telefono=?, direccion=?, email=? WHERE id=?""",
                             (" ".join(p["nombre"].split()), fila[0], e["ruc"] or fila[1], e["telefono"] or fila[2],
                              e["direccion"] or fila[3], e["email"] or fila[4], e["id"]))
            else:
                nuevos.append((k, " ".join(p["nombre"].split())) + fila + (hoy_s,))
        tanda = 400
        for i in range(0, len(nuevos), tanda):
            grupo = nuevos[i:i + tanda]
            marcas = ",".join(["(?,?,?,?,?,?,?,?)"] * len(grupo))
            conn.execute(f"""INSERT INTO repuestos_proveedores
                (clave, nombre, codigo, ruc, telefono, direccion, email, actualizado)
                VALUES {marcas} ON CONFLICT (clave) DO NOTHING""",
                [v for f in grupo for v in f])
        conn.commit()
        print(f"[proveedores] listado importado: {len(nuevos)} nuevos")
        return len(nuevos)
    finally:
        conn.close()


def obtener_proveedores(q=None, limite=30, pagina=0, letra="", solo_uso=False):
    """Busca o lista proveedores.

    - q: nombre, RUC, número o contacto.
    - pagina (desde 1): lista completa paginada, por orden alfabético.
    - letra: los que empiezan con esa letra ("#" = los que empiezan con número).
    - solo_uso: solo los que ya figuran en algún repuesto.
    Sin q ni página devuelve los que ya se usan en repuestos (los más a mano).
    """
    conn = get_connection()
    usos = {r["k"]: r["n"] for r in conn.execute(
        """SELECT LOWER(TRIM(proveedor)) AS k, COUNT(*) AS n FROM repuestos
           WHERE activo=1 AND proveedor<>'' GROUP BY LOWER(TRIM(proveedor))""").fetchall()}
    cols = ", ".join(CAMPOS_PROV) + ", clave"
    q = _sin_tildes(" ".join(str(q or "").split()))
    donde, params = [], []
    if q:
        like = f"%{q}%"
        donde.append(f"({_col_sin_tildes('clave')} LIKE ? OR {_col_sin_tildes('fantasia')} LIKE ?"
                     f" OR LOWER(ruc) LIKE ? OR codigo=? OR {_col_sin_tildes('contacto')} LIKE ?)")
        params += [like, like, like, q, like]
    letra = str(letra or "").strip().lower()[:1]
    # Algunos nombres vienen entre comillas ("AMM" S.A.): cuentan por su letra
    sin_comillas = "LTRIM(clave, '\" ')"
    if letra == "#":
        donde.append(f"SUBSTR({sin_comillas},1,1) BETWEEN '0' AND '9'")
    elif letra:
        donde.append(f"{sin_comillas} LIKE ?")
        params.append(letra + "%")
    if solo_uso or (not q and not pagina and not letra):
        claves = list(usos)
        if not claves:
            conn.close()
            return {"proveedores": [], "total": _total_proveedores(), "coincidencias": 0}
        donde.append(f"clave IN ({','.join('?' * len(claves))})")
        params += claves
    where = ("WHERE " + " AND ".join(donde)) if donde else ""
    coinc = conn.execute(f"SELECT COUNT(*) AS n FROM repuestos_proveedores {where}", params).fetchone()["n"]
    orden = "nombre"
    extra = []
    if q:
        # Primero los que empiezan con lo buscado, por razón social o por fantasía
        orden = (f"CASE WHEN {_col_sin_tildes('clave')} LIKE ? OR {_col_sin_tildes('fantasia')} LIKE ?"
                 " THEN 0 ELSE 1 END, LOWER(nombre)")
        extra = [f"{q}%", f"{q}%"]
    else:
        orden = "LTRIM(clave, '\" ')"
    limite = int(limite)
    desde = (max(int(pagina or 1), 1) - 1) * limite
    filas = conn.execute(f"""SELECT {cols} FROM repuestos_proveedores {where}
        ORDER BY {orden} LIMIT ? OFFSET ?""", params + extra + [limite, desde]).fetchall()
    conn.close()
    res = []
    for f in filas:
        d = {k: (f[k] or "") for k in CAMPOS_PROV}
        d["repuestos"] = usos.get(f["clave"], 0)
        res.append(d)
    return {"proveedores": res, "total": _total_proveedores(), "coincidencias": int(coinc or 0)}


def _total_proveedores():
    conn = get_connection()
    try:
        return int(conn.execute("SELECT COUNT(*) AS n FROM repuestos_proveedores").fetchone()["n"] or 0)
    finally:
        conn.close()


def resumen_proveedores():
    """Los números de arriba del directorio."""
    conn = get_connection()
    f = conn.execute("""SELECT COUNT(*) AS total,
        SUM(CASE WHEN telefono<>'' THEN 1 ELSE 0 END) AS con_tel,
        SUM(CASE WHEN contacto<>'' THEN 1 ELSE 0 END) AS con_contacto
        FROM repuestos_proveedores""").fetchone()
    en_uso = conn.execute("""SELECT COUNT(DISTINCT LOWER(TRIM(proveedor))) AS n FROM repuestos
        WHERE activo=1 AND proveedor<>''""").fetchone()["n"]
    conn.close()
    return {"total": int(f["total"] or 0), "con_telefono": int(f["con_tel"] or 0),
            "con_contacto": int(f["con_contacto"] or 0), "en_uso": int(en_uso or 0)}


def crear_proveedor(datos):
    """Agrega un proveedor al directorio a mano."""
    nombre = " ".join(str(datos.get("nombre") or "").split())
    if len(nombre) < 2:
        return False, "Poné el nombre del proveedor."
    if proveedor_por_nombre(nombre):
        return False, "Ese proveedor ya está en el directorio."
    ruc = " ".join(str(datos.get("ruc") or "").split())
    if ruc:
        conn = get_connection()
        otro = conn.execute("SELECT nombre FROM repuestos_proveedores WHERE ruc=?", (ruc,)).fetchone()
        conn.close()
        if otro:
            return False, f"Ese RUC ya está cargado como «{otro['nombre']}»."
    guardar_contacto_proveedor(nombre, datos.get("contacto"), datos.get("telefono"))
    editar_proveedor(nombre, datos)
    p = proveedor_por_nombre(nombre) or {}
    return True, f"Proveedor agregado con el N° {p.get('codigo') or '—'}."


def proveedor_por_nombre(nombre):
    k = _clave_proveedor(nombre)
    if not k:
        return None
    conn = get_connection()
    f = conn.execute(f"SELECT {', '.join(CAMPOS_PROV)} FROM repuestos_proveedores WHERE clave=?",
                     (k,)).fetchone()
    conn.close()
    return {c: (f[c] or "") for c in CAMPOS_PROV} if f else None


def editar_proveedor(nombre_actual, datos):
    """Corrige los datos de un proveedor desde el directorio. El nombre no se
    cambia acá: los repuestos lo tienen escrito y quedarían desenganchados."""
    k = _clave_proveedor(nombre_actual)
    campos = {c: " ".join(str(datos.get(c) or "").split())
              for c in ("fantasia", "ruc", "contacto", "telefono", "direccion", "email") if c in datos}
    if not k or not campos:
        return False, "Nada para guardar."
    from hora_local import hoy
    conn = get_connection()
    sets = ", ".join(f"{c}=?" for c in campos) + ", actualizado=?"
    cur = conn.execute(f"UPDATE repuestos_proveedores SET {sets} WHERE clave=?",
                       list(campos.values()) + [hoy(), k])
    conn.commit()
    conn.close()
    return True, "Proveedor actualizado."


def _contactos_por_clave(conn, nombres=None):
    claves = sorted({_clave_proveedor(n) for n in (nombres or []) if _clave_proveedor(n)})
    if not claves:
        return {}
    try:
        filas = conn.execute(
            f"SELECT clave, contacto, telefono, ruc, fantasia FROM repuestos_proveedores WHERE clave IN ({','.join('?' * len(claves))})",
            claves).fetchall()
    except Exception:
        return {}
    return {f["clave"]: f for f in filas}


def _con_contacto(d, contactos):
    f = contactos.get(_clave_proveedor(d.get("proveedor")))
    d["proveedor_contacto"] = (f["contacto"] if f else "") or ""
    d["proveedor_telefono"] = (f["telefono"] if f else "") or ""
    d["proveedor_ruc"] = (f["ruc"] if f else "") or ""
    d["proveedor_fantasia"] = (f["fantasia"] if f else "") or ""
    return d


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
    prov_contacto = kwargs.pop("proveedor_contacto", None)
    prov_telefono = kwargs.pop("proveedor_telefono", None)

    campos = {
        "codigo_alt": "", "categoria": "Varios", "marca": "", "aplicacion": "",
        "ubic_pasillo": "", "ubic_estanteria": "", "ubic_nivel": "", "ubic_posicion": "",
        "stock_minimo": 0, "unidad": "u", "costo_unitario": 0,
        "proveedor": "", "observaciones": "",
    }
    campos.update({k: v for k, v in kwargs.items() if k in campos})
    campos["proveedor"] = guardar_contacto_proveedor(
        campos["proveedor"], prov_contacto, prov_telefono)

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
    if "proveedor" in kwargs:
        kwargs["proveedor"] = guardar_contacto_proveedor(kwargs.get("proveedor"),
                                   kwargs.get("proveedor_contacto"),
                                   kwargs.get("proveedor_telefono"))
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
              " OR LOWER(aplicacion) LIKE ? OR LOWER(proveedor) LIKE ?"
              # también por el nombre de fantasía del proveedor
              " OR LOWER(TRIM(proveedor)) IN (SELECT clave FROM repuestos_proveedores"
              f" WHERE {_col_sin_tildes('fantasia')} LIKE ?))")
        params += [like, like, like, like, like, like, f"%{_sin_tildes(buscar.strip())}%"]
    q += " ORDER BY categoria, descripcion"
    rows = conn.execute(q, params).fetchall()
    contactos = _contactos_por_clave(conn, [r["proveedor"] for r in rows])
    conn.close()
    resultado = [_con_contacto(_enriquecer(r), contactos) for r in rows]
    if solo_bajos:
        resultado = [r for r in resultado if r["estado_stock"] in ("bajo", "sin_stock")]
    return resultado


def obtener_repuesto(repuesto_id):
    """Un repuesto con sus campos calculados y su historial de movimientos."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM repuestos WHERE id=?", (repuesto_id,)).fetchone()
    contactos = _contactos_por_clave(conn, [row["proveedor"]]) if row else {}
    conn.close()
    if not row:
        return None
    d = _con_contacto(_enriquecer(row), contactos)
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
