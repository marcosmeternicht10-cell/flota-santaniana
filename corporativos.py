"""
corporativos.py — Módulo de Servicios Corporativos (La Santaniana)

Los choferes de corporativos cubren servicios para clientes (ADM, Bimbo,
Cervepar, etc.), cada uno con sus tramos/horarios. Este módulo:

  - Da de alta a los choferes como usuarios con rol 'chofer_corp' (interfaz de
    celular), usuario y contraseña = su nombre.
  - Registra las rendiciones que cada chofer carga desde el teléfono: cliente,
    tramo, fecha, bus (Nº interno), horarios, kilometraje, pasajeros, estado.
  - Alimenta la subsección "Resumen de rendiciones" (ver por chofer + PDF).

Enganche en app.py (después de los otros módulos):
    from corporativos import bp_corp, init_corporativos_module
    init_corporativos_module(app)
    app.register_blueprint(bp_corp)
"""

from flask import Blueprint, request, jsonify, session
from db_compat import get_connection, USE_POSTGRES, IntegrityError

try:
    from database import auditar
except Exception:
    def auditar(*a, **k):  # si no está disponible, no rompe la liquidación
        pass

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"

bp_corp = Blueprint("corporativos", __name__)


# ════════════════════════════════════════════════════════════════════════════
# TARIFAS Y REGLAS DE PAGO
# ════════════════════════════════════════════════════════════════════════════
# Un tramo tiene dos mitades: entrante y saliente. A veces las hace el mismo
# chofer (completado) y a veces se reparten entre dos choferes distintos.
#   completado (entrante + saliente) → 150.000
#   solo entrante  /  solo saliente  →  75.000
#   tramo VARIABLE                   →  75.000 siempre
#   suspendido                       →       0 (el servicio no se prestó)

MONTO_COMPLETADO = 150000
MONTO_MEDIO      = 75000     # entrante o saliente por separado
MONTO_VARIABLE   = 75000     # el tramo "VARIABLE" paga esto sin importar el estado
PLUS_SEMANAL     = 150000    # plus fijo por semana trabajada, para ciertos choferes

# Choferes que cobran el plus semanal (por nombre completo, como figura en la
# planilla). Se identifican por nombre y no por usuario porque hay nombres de
# pila repetidos en la nómina.
CHOFERES_CON_PLUS = [
    "CUENCA, LUCIO",
    "FRETES, CESAR",
    "FRANCO, JAVIER",
    "RESQUIN, RUBEN",
]

# Empresas que ya no operan con La Santaniana. No aparecen en el selector del
# chofer, pero sus rendiciones históricas se siguen viendo en el Resumen.
# "FAPASA Y LASCA" era una sola planilla: Fapasa dejó de operar y Lasca sigue,
# así que el cliente activo quedó como "LASCA" (con los tramos de esa planilla)
# y el nombre viejo se conserva acá solo para que el historial no se pierda.
CLIENTES_INACTIVOS = ["BIMBO", "PETROPAR", "FPV", "FAPASA", "FAPASA Y LASCA"]

TRAMO_VARIABLE = "VARIABLE"


def _tarifa_por_defecto(cliente, tramo):
    """Tarifa inicial de un tramo, la primera vez que arranca el sistema.
    Los administrativos van a 150.000 el completo; el resto (turnos y tramos
    numerados) a 75.000. Después cada uno se ajusta desde la pantalla."""
    t = (tramo or "").strip().upper()
    if t == TRAMO_VARIABLE:
        return MONTO_VARIABLE
    es_admin = (t.startswith("ADMIN") or t.startswith("ADM ")
                or t.startswith("HOTEL"))
    return MONTO_COMPLETADO if es_admin else MONTO_MEDIO


def tarifas_tramos():
    """Precio del servicio completo de cada tramo. Vive en la base para que se
    pueda corregir sin tocar el código: cada tramo con su monto, tal como lo
    paga la empresa. La mitad (entrante o saliente) es siempre la mitad exacta.
    """
    import json
    conn = get_connection()
    try:
        row = conn.execute("SELECT valor FROM config_corp WHERE clave=?",
                           ("tarifas_tramos",)).fetchone()
    except Exception:
        row = None
    conn.close()

    guardadas = {}
    if row and row["valor"]:
        try:
            guardadas = json.loads(row["valor"]) or {}
        except Exception:
            guardadas = {}

    # Se arma el catálogo completo: lo guardado manda, el resto toma el default
    tarifas = {}
    for cliente, tramos in CLIENTES_TRAMOS.items():
        for tramo in tramos:
            clave = f"{cliente}|{tramo}"
            valor = guardadas.get(clave)
            try:
                tarifas[clave] = float(valor) if valor is not None else \
                    _tarifa_por_defecto(cliente, tramo)
            except Exception:
                tarifas[clave] = _tarifa_por_defecto(cliente, tramo)
    return tarifas


def guardar_tarifas(nuevas, admin=""):
    """Guarda el precio de cada tramo. Solo se persisten los que difieren o
    fueron tocados; el resto sigue el valor por defecto."""
    import json, datetime as _dt
    limpio = {}
    for clave, valor in (nuevas or {}).items():
        try:
            v = float(str(valor).replace(".", "").replace(",", ".") or 0)
        except Exception:
            return False, f"El monto de «{clave.split('|')[-1]}» no es válido."
        if v < 0:
            return False, "Los montos no pueden ser negativos."
        limpio[clave] = round(v)

    conn = get_connection()
    try:
        conn.execute("DELETE FROM config_corp WHERE clave IN (?,?)",
                     ("tarifas_tramos", "tarifas_editadas"))
        conn.execute("INSERT INTO config_corp (clave, valor) VALUES (?,?)",
                     ("tarifas_tramos", json.dumps(limpio, ensure_ascii=False)))
        conn.execute("INSERT INTO config_corp (clave, valor) VALUES (?,?)",
                     ("tarifas_editadas", f"{admin} {_dt.date.today().isoformat()}"))
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        return False, "No se pudieron guardar las tarifas."
    conn.close()
    return True, f"Se guardaron las tarifas de {len(limpio)} tramo(s)."


def calcular_monto(tramo, estado, cliente=None):
    """Cuánto se le paga al chofer por esta rendición.

    El precio sale de la tarifa del tramo (configurable desde la pantalla).
    Completado paga la tarifa entera; entrante o saliente, la mitad exacta;
    suspendido no paga porque el servicio no se prestó.
    """
    if estado == "suspendido":
        return 0

    completo = None
    if cliente:
        completo = tarifas_tramos().get(f"{cliente}|{tramo}")
    if completo is None:
        # Sin cliente (o tramo fuera del catálogo): se busca por nombre de tramo
        for clave, valor in tarifas_tramos().items():
            if clave.split("|", 1)[-1] == tramo:
                completo = valor
                break
    if completo is None:
        completo = _tarifa_por_defecto(cliente, tramo)

    if estado == "completado":
        return round(completo)
    if estado in ("entrante", "saliente"):
        return round(completo / 2)
    return 0


# ════════════════════════════════════════════════════════════════════════════
# CLIENTES Y TRAMOS (extraídos de la planilla de rendición 2026)
# ════════════════════════════════════════════════════════════════════════════
# El chofer elige cliente y después el tramo (listas encadenadas).

CLIENTES_TRAMOS = {
    "ADM": [
        "ADM RUTA 1 - 7:00 A 17:00", "ADM ACCESO - 7:00 A 17:00",
        "ADM SINALCO - 7:00 A 17:00", "ADM VILLA OLIVA - 07:00 A 17:00",
        "TURNO A RUTA 1 NORMAL 6:00/6:30", "TURNO A RUTA 1 APOYO 6:00/6:30",
        "TURNO A SINALCO NORMAL 6:00/6:30", "TURNO A SINALCO APOYO 6:00/6:30",
        "TURNO B RUTA 1 NORMAL 14:00/14:30", "TURNO B RUTA 1 APOYO 14:00/14:30",
        "TURNO B SINALCO NORMAL 14:00/14:30", "TURNO B SINALCO APOYO 14:00/14:30",
        "TURNO C RUTA 1 NORMAL 22:00/22:30", "TURNO C RUTA 1 APOYO 22:00/22:30",
        "TURNO C SINALCO NORMAL 22:00/22:30", "TURNO C SINALCO APOYO 22:00/22:30",
        "VARIABLE",
    ],
    "BIMBO": [
        "TRAMO ADMINIST 1 - 7:00/15:00", "TRAMO ADMINIST 2 - 7:00/15:00",
        "TRAMO ADMINIST 3 - 7:00/15:00",
        "TRAMO 1 - 6:00/14:30", "TRAMO 2 - 6:00/14:30",
        "TRAMO 1 - 14:30/22:30", "TRAMO 2 - 14:30/22:30",
        "TRAMO 1 - 22:30/06:00", "TRAMO 2 - 22:30/06:00",
        "VARIABLE",
    ],
    "CERVEPAR": [
        "ADMIN. SAJONIA", "ADMIN. ESPAÑA", "ADMIN. LUQUE",
        "LIMPIO 6:00/6:20", "ITAUGUA 6:00/6:20", "SAJONIA 6:00/6:20", "ITA 6:00/6:20",
        "LIMPIO 14:00/14:20", "ITAUGUA 14:00/14:20", "SAJONIA 14:00/14:20", "ITA 14:00/14:20",
        "LIMPIO 22:00/22:20", "ITAUGUA 22:00/22:20", "SAJONIA 22:00/22:20", "ITA 22:00/22:20",
        "VARIABLE",
    ],
    "FPV": [
        "6:00/6:20 TRAMO LOMA PYTA", "6:00/6:20 TRAMO LAMBARE",
        "14:00/14:20 TRAMO LOMA PYTA", "14:00/14:20 TRAMO LAMBARE",
        "22:00/22:15 TRAMO LOMA PYTA", "22:00/22:15 TRAMO LAMBARE",
        "VARIABLE",
    ],
    "BALL": [
        "HOTEL 1 / 8:00/17:00", "HOTEL 2 / 8:00/17:00",
        "ADMIN. LUQUE/RUTA 1 / 7:00/17:00", "ADMIN. ACCESO SUR / 7:00/17:00",
        "TRAMO 1 / 6:00/18:00 - Mañana", "TRAMO 1 / 18:00/06:00 - Tarde",
        "TRAMO 2 / 6:00/18:00 - Mañana", "TRAMO 2 / 18:00/06:00 - Tarde",
        "TRAMO 3 / 6:00/18:00 - Mañana", "TRAMO 3 / 18:00/06:00 - Tarde",
        "TRAMO 4 / 6:00/18:00 - Mañana", "TRAMO 4 / 18:00/06:00 - Tarde",
        "TRAMO 5 / 6:00/18:00 - Mañana", "TRAMO 5 / 18:00/6:00 - Tarde",
        "TRAMO 6 / 6:00/18:00 - Mañana", "TRAMO 6 / 18:00/6:00 - Tarde",
        "TRAMO 7 / 6:00/18:00 - Mañana", "TRAMO 7 / 18:00/6:00 - Tarde",
        "VARIABLE",
    ],
    "PETROPAR": [
        "TRAMO LUQUE 1 - 7:00/15:00", "TRAMO LUQUE 2 - 7:00/15:00",
        "TRAMO SAJONIA 7:00/15:00",
        "TRAMO CARGADERO 1 - 6:00", "TRAMO CARGADERO 2 - 6:00",
        "TRAMO CARGADERO 1 - 12:00/12:30", "TRAMO CARGADERO 2 - 12:00/12:30",
        "TRAMO TURNANTE 1 - 06:00/06:30", "TRAMO TURNANTE 1 - 12:00/12:30",
        "TRAMO TURNANTE 2 - 18:00/18:30", "TRAMO TURNANTE 2 - 00:00/00:30",
        "VARIABLE",
    ],
    "LASCA": [
        "ADMIN. LIMPIO (7:30 A 17:00 HS.)", "ADMIN. RUTA 1 (7:30 A 17:00 HS.)",
        "ADMIN. RUTA 2 (7:30 A 17:00 HS.)", "ADMIN. TACUMBU (7:30 A 17:00 HS.)",
        "TURNANTE LIMPIO (4:30 HS.)", "TURNANTE RUTA 1 (4:30 HS.)", "TURNANTE RUTA 2 (4:30 HS.)",
        "TURNANTE LIMPIO (13:30 HS.)", "TURNANTE RUTA 1 (13:30 HS.)", "TURNANTE RUTA 2 (13:30 HS.)",
        "TURNANTE LIMPIO (23:50 HS.)", "TURNANTE RUTA 1 (23:50 HS.)", "TURNANTE RUTA 2 (23:50 HS.)",
        "TURNANTE YPANE (23:50 HS.)",
        "VARIABLE",
    ],
}

# Los 31 choferes de corporativos (del Excel de julio 2026).
# Formato: "APELLIDO, NOMBRE" tal como figura en la planilla de sueldos.
CHOFERES_CORP = [
    "ACOSTA, ARMANDO", "ACUÑA, ANGEL", "AGUIAR, MARCOS", "ALVARENGA, CESAR",
    "AQUINO, GERARDO", "CUENCA, LUCIO", "DELVALLE, ROBERT", "DUARTE, CARLOS",
    "ESPINOLA, DERLIS", "FERNANDEZ, SERGIO", "FLORENTIN, FELIPE", "FLORENTIN, PABLO",
    "FRANCO, JAVIER", "FRETES, CESAR", "GOMEZ, RICHARD", "GONZALEZ, RICHARD",
    "JARA, JUAN", "LEIVA, AMADO", "MARTINEZ, ISIDRO", "MARTINEZ, OSMAR",
    "MONTANIA, JUAN", "NUÑEZ, GABRIEL", "OLMEDO, DARIO", "PEREZ, WALTER",
    "REINOSO, IVAN", "RESQUIN, RUBEN", "RIQUELME, HEBERLINO", "SAUCEDO, ALCIDES",
    "SOSA, CARLOS", "SOTO, ANGEL", "TORRES, JULIO",
]


def _usuario_desde_nombre(nombre_completo):
    """De 'ACOSTA, ARMANDO' saca el usuario 'armando' (primer nombre, en
    minúscula, sin tildes) — fácil de tipear en el celular."""
    # Toma lo que está después de la coma (el nombre de pila)
    if "," in nombre_completo:
        pila = nombre_completo.split(",", 1)[1].strip()
    else:
        pila = nombre_completo.strip()
    primer = pila.split()[0] if pila.split() else pila
    # Sacar tildes y ñ para que sea fácil de escribir
    tabla = str.maketrans("ÁÉÍÓÚÜÑáéíóúüñ", "AEIOUUNaeiouun")
    return primer.translate(tabla).lower()


# ════════════════════════════════════════════════════════════════════════════
# TABLA
# ════════════════════════════════════════════════════════════════════════════

def inicializar_corporativos():
    """Crea la tabla de rendiciones. Idempotente."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS rendiciones_corp (
            id {PK},
            chofer_usuario TEXT NOT NULL,     -- usuario que cargó (login)
            chofer_nombre TEXT NOT NULL,      -- nombre completo para el reporte
            cliente TEXT NOT NULL,
            tramo TEXT NOT NULL,
            fecha_servicio TEXT NOT NULL,
            bus_interno TEXT NOT NULL,        -- Nº interno del bus
            hora_inicio TEXT DEFAULT '',
            hora_fin TEXT DEFAULT '',
            km_inicial REAL DEFAULT 0,
            km_final REAL DEFAULT 0,
            pasajeros INTEGER DEFAULT 0,
            estado TEXT DEFAULT 'completado',  -- completado | entrante | saliente | suspendido
            observacion TEXT DEFAULT '',       -- obligatoria si suspendido
            monto REAL DEFAULT 0,              -- lo que se le paga al chofer
            liquidado INTEGER DEFAULT 0,       -- 1 = ya se le pagó al chofer
            fecha_liquidacion TEXT,            -- cuándo se marcó como pagado
            liquidado_por TEXT DEFAULT '',     -- quién la liquidó (admin)
            fecha_carga TEXT DEFAULT (date('now'))
        )
    """)
    # Configuración editable del módulo (monto del plus, quiénes lo cobran)
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS config_corp (
            id {PK},
            clave TEXT UNIQUE NOT NULL,
            valor TEXT
        )
    """)
    conn.commit()

    # Migración: columnas de liquidación para bases que ya existían
    try:
        from db_compat import columnas_de_tabla
        cols = columnas_de_tabla(conn, "rendiciones_corp")
        for col, ddl in (("liquidado", "INTEGER DEFAULT 0"),
                         ("fecha_liquidacion", "TEXT"),
                         ("liquidado_por", "TEXT DEFAULT ''"),
                         # Monto corregido a mano: el recálculo automático no lo toca
                         ("monto_fijo", "INTEGER DEFAULT 0"),
                         ("editado_por", "TEXT DEFAULT ''"),
                         ("fecha_edicion", "TEXT")):
            if col not in cols:
                conn.execute(f"ALTER TABLE rendiciones_corp ADD COLUMN {col} {ddl}")
        conn.commit()
    except Exception:
        conn.rollback()

    # Migración para bases que ya tenían la tabla sin la columna monto
    try:
        from db_compat import columnas_de_tabla
        if "monto" not in columnas_de_tabla(conn, "rendiciones_corp"):
            conn.execute("ALTER TABLE rendiciones_corp ADD COLUMN monto REAL DEFAULT 0")
            conn.commit()
    except Exception:
        pass

    # Las rendiciones cargadas antes de que existiera el cálculo quedaron en
    # cero. Se les pone el monto que les corresponde según su tramo y estado,
    # así el Resumen no muestra guiones. Solo toca las que están en cero.
    try:
        sql_pendientes = """
            SELECT id, cliente, tramo, estado FROM rendiciones_corp
            WHERE (monto IS NULL OR monto = 0) AND estado <> 'suspendido'
              AND COALESCE(monto_fijo,0) = 0
        """
        pendientes = [dict(r) for r in conn.execute(sql_pendientes).fetchall()]
        for p in pendientes:
            conn.execute("UPDATE rendiciones_corp SET monto=? WHERE id=?",
                         (calcular_monto(p["tramo"], p["estado"], p["cliente"]), p["id"]))
        conn.commit()
    except Exception:
        conn.rollback()

    # Candado a nivel base de datos, a prueba de cargas simultáneas.
    # Un tramo tiene dos "lugares": el entrante y el saliente. Marcar
    # "completado" ocupa los dos a la vez. Con un índice por lugar, la base
    # rechaza sola cualquier combinación inválida aunque dos choferes guarden
    # en el mismo instante:
    #   entrante + saliente  → uno en cada índice, conviven (es lo que se busca)
    #   entrante + entrante  → chocan
    #   completado + lo que sea → chocan (ocupa ambos lugares)
    # Se excluyen VARIABLE (comodín) y los suspendidos (no generan pago).
    for nombre, estados in (("idx_rend_lugar_entrante", "('entrante','completado')"),
                            ("idx_rend_lugar_saliente", "('saliente','completado')")):
        try:
            conn.execute(f"""
                CREATE UNIQUE INDEX IF NOT EXISTS {nombre}
                ON rendiciones_corp (cliente, tramo, fecha_servicio)
                WHERE estado IN {estados} AND tramo <> 'VARIABLE'
            """)
            conn.commit()
        except Exception:
            conn.rollback()
    # Limpieza del candado viejo, que no cubría el caso de carga simultánea
    try:
        conn.execute("DROP INDEX IF EXISTS idx_rend_tramo_unico")
        conn.commit()
    except Exception:
        conn.rollback()
    conn.close()


def seed_choferes_corp():
    """Da de alta a los 31 choferes como usuarios rol 'chofer_corp'.
    Usuario = primer nombre; contraseña = igual al usuario.

    Resuelve las colisiones de nombre de dos maneras:
      - Entre choferes con el mismo nombre de pila (los dos "RICHARD").
      - Contra usuarios que YA existen en el sistema (por ejemplo, si el admin
        se llama 'marcos' y hay un chofer AGUIAR, MARCOS). Antes ese chofer
        quedaba sin cuenta en silencio.

    Es idempotente: si un chofer ya tiene su cuenta, no la vuelve a crear.
    """
    from database import crear_usuario

    # Usuarios que ya existen en la base (cualquier rol) y nombres de choferes
    # que ya tienen cuenta creada, para no duplicarlos.
    conn = get_connection()
    filas = [dict(r) for r in conn.execute(
        "SELECT usuario, nombre, rol FROM usuarios").fetchall()]
    conn.close()
    ocupados = {f["usuario"].lower() for f in filas}
    ya_tienen = {(f["nombre"] or "").strip().upper()
                 for f in filas if f["rol"] == "chofer_corp"}

    creados, saltados = 0, 0
    usados, sin_cuenta = {}, []

    for nombre in CHOFERES_CORP:
        if nombre.strip().upper() in ya_tienen:
            saltados += 1                      # ya tiene su cuenta
            continue

        base = _usuario_desde_nombre(nombre)
        apellido = nombre.split(",", 1)[0].strip()
        ini = apellido[0].lower() if apellido else "x"

        # Buscar un nombre de usuario libre: primero el nombre de pila, después
        # con la inicial del apellido, y si hace falta con un número.
        candidatos = [base, base + ini] + [f"{base}{ini}{n}" for n in range(2, 12)]
        usuario = next((c for c in candidatos
                        if c not in usados and c not in ocupados), None)
        if not usuario:
            sin_cuenta.append(nombre)
            continue

        ok, _ = crear_usuario(usuario, usuario, nombre=nombre, rol="chofer_corp")
        if ok:
            usados[usuario] = nombre
            ocupados.add(usuario)
            creados += 1
        else:
            sin_cuenta.append(nombre)

    return {"creados": creados, "saltados": saltados,
            "usuarios": usados, "sin_cuenta": sin_cuenta,
            "total_esperado": len(CHOFERES_CORP)}


def init_corporativos_module(app):
    inicializar_corporativos()


# ════════════════════════════════════════════════════════════════════════════
# LÓGICA
# ════════════════════════════════════════════════════════════════════════════

ESTADOS_CON_PAGO = ("completado", "entrante", "saliente")

LABEL_ESTADO = {
    "completado": "entrante y saliente",
    "entrante": "solo el entrante",
    "saliente": "solo el saliente",
    "suspendido": "suspendido",
}


def _canonizar(cliente, tramo):
    """Devuelve el cliente y el tramo tal como figuran en el catálogo oficial.

    Evita que dos escrituras distintas del mismo tramo ("ADM RUTA 1" vs
    "adm ruta 1  ") entren como servicios diferentes y se cuele un duplicado.
    Devuelve (cliente_oficial, tramo_oficial) o (None, None) si no existe.
    """
    def limpio(s):
        return " ".join(str(s or "").split()).upper()

    c_busca = limpio(cliente)
    cliente_of = next((k for k in CLIENTES_TRAMOS if limpio(k) == c_busca), None)
    if not cliente_of:
        return None, None
    t_busca = limpio(tramo)
    tramo_of = next((t for t in CLIENTES_TRAMOS[cliente_of] if limpio(t) == t_busca), None)
    return (cliente_of, tramo_of) if tramo_of else (cliente_of, None)


def tramo_ocupado(cliente, tramo, fecha, estado_nuevo, excluir_id=None):
    """Verifica si el tramo ya fue reportado por otro chofer.

    Un tramo tiene dos mitades (entrante y saliente) que pueden hacer dos
    choferes distintos. Pero la MISMA mitad no puede reportarse dos veces, ni
    puede marcarse "completado" si otro ya tomó una de las mitades.

    Devuelve None si está libre, o un mensaje explicando quién lo tomó.
    """
    if estado_nuevo not in ESTADOS_CON_PAGO:
        return None                                   # los suspendidos no bloquean
    if (tramo or "").strip().upper() == TRAMO_VARIABLE:
        return None                                   # VARIABLE es comodín

    conn = get_connection()
    q = """SELECT id, chofer_nombre, estado FROM rendiciones_corp
           WHERE cliente=? AND tramo=? AND fecha_servicio=?
             AND estado IN ('completado','entrante','saliente')"""
    params = [cliente.strip(), tramo.strip(), fecha.strip()]
    if excluir_id:
        q += " AND id<>?"
        params.append(excluir_id)
    previas = [dict(r) for r in conn.execute(q, params).fetchall()]
    conn.close()

    if not previas:
        return None

    completa = next((p for p in previas if p["estado"] == "completado"), None)
    if completa:
        return (f"Ese tramo ya lo reportó {completa['chofer_nombre']} completo "
                f"(entrante y saliente). No se puede cargar de nuevo.")

    tomados = {p["estado"]: p for p in previas}
    if estado_nuevo == "completado":
        cual = list(tomados.values())[0]
        falta = "saliente" if cual["estado"] == "entrante" else "entrante"
        return (f"{cual['chofer_nombre']} ya reportó el {cual['estado']} de ese tramo. "
                f"Si vos hiciste la otra mitad, marcá «solo el {falta}».")
    if estado_nuevo in tomados:
        quien = tomados[estado_nuevo]["chofer_nombre"]
        return f"{quien} ya reportó el {estado_nuevo} de ese tramo en esa fecha."
    return None


def segmentos_tomados(cliente, tramo, fecha):
    """Qué mitades del tramo ya están reportadas — para avisarle al chofer
    ANTES de que cargue todo el formulario."""
    if (tramo or "").strip().upper() == TRAMO_VARIABLE:
        return {"libre": True, "tomados": []}
    conn = get_connection()
    rows = conn.execute("""
        SELECT chofer_nombre, estado FROM rendiciones_corp
        WHERE cliente=? AND tramo=? AND fecha_servicio=?
          AND estado IN ('completado','entrante','saliente')
    """, (cliente.strip(), tramo.strip(), fecha.strip())).fetchall()
    conn.close()
    tomados = [dict(r) for r in rows]
    return {"libre": len(tomados) == 0, "tomados": tomados}


def registrar_rendicion(datos):
    """Guarda una rendición cargada por un chofer. Valida:
    cliente, tramo, fecha, bus; observación si está suspendido; y sobre todo
    que ese tramo no haya sido reportado ya por otro chofer."""
    req = ["cliente", "tramo", "fecha_servicio", "bus_interno"]
    for r in req:
        if not str(datos.get(r, "")).strip():
            return False, f"Falta {r.replace('_',' ')}."
    estado = datos.get("estado", "completado")
    if estado not in ("completado", "entrante", "saliente", "suspendido"):
        estado = "completado"
    if estado == "suspendido" and not str(datos.get("observacion", "")).strip():
        return False, "Si el servicio fue suspendido, explicá el motivo en la observación."

    # ── Solo se aceptan clientes y tramos del catálogo, con su escritura
    # oficial. Así nadie puede colar un duplicado cambiando mayúsculas o
    # espacios, ni cargar para una empresa que ya no opera.
    cliente_of, tramo_of = _canonizar(datos["cliente"], datos["tramo"])
    if not cliente_of:
        return False, "Ese cliente no está en la lista de empresas activas."
    if not tramo_of:
        return False, "Ese tramo no figura entre los del cliente elegido."
    if cliente_of in CLIENTES_INACTIVOS:
        return False, f"{cliente_of} ya no opera con La Santaniana."
    datos = dict(datos)
    datos["cliente"], datos["tramo"] = cliente_of, tramo_of

    # ── Candado: un tramo no puede reportarse dos veces ──
    ocupado = tramo_ocupado(datos["cliente"], datos["tramo"],
                            datos["fecha_servicio"], estado)
    if ocupado:
        return False, ocupado

    def num(v):
        try: return float(str(v).replace(".", "").replace(",", ".") or 0)
        except: return 0

    monto = calcular_monto(datos["tramo"], estado, datos["cliente"])

    conn = get_connection()
    try:
        conn.execute("""INSERT INTO rendiciones_corp
            (chofer_usuario, chofer_nombre, cliente, tramo, fecha_servicio,
             bus_interno, hora_inicio, hora_fin, km_inicial, km_final,
             pasajeros, estado, observacion, monto)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (datos.get("chofer_usuario", ""), datos.get("chofer_nombre", ""),
             datos["cliente"].strip(), datos["tramo"].strip(),
             datos["fecha_servicio"].strip(), str(datos["bus_interno"]).strip(),
             datos.get("hora_inicio", ""), datos.get("hora_fin", ""),
             num(datos.get("km_inicial")), num(datos.get("km_final")),
             int(num(datos.get("pasajeros"))), estado,
             datos.get("observacion", "").strip(), monto))
        conn.commit()
    except IntegrityError:
        # El candado de la base atajó una carga simultánea de dos choferes
        conn.rollback()
        conn.close()
        return False, "Otro chofer acaba de reportar ese mismo tramo. Verificá antes de volver a cargar."
    conn.close()
    # El chofer no ve montos: el cálculo se guarda para la liquidación, pero
    # la plata solo se muestra en el Resumen de admin.
    return True, "Rendición registrada." 


def rendiciones_de_chofer(chofer_usuario, limite=100):
    """Rendiciones PENDIENTES de un chofer (para que las vea en su celular).
    Una vez que el admin marca la semana como liquidada, dejan de aparecerle
    acá — su vista se limpia y arranca a acumular de nuevo. El historial no se
    pierde: sigue estando en el Resumen buscando por fecha."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM rendiciones_corp
        WHERE chofer_usuario=? AND COALESCE(liquidado,0)=0
        ORDER BY fecha_servicio DESC, id DESC LIMIT ?
    """, (chofer_usuario, limite)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def obtener_rendiciones(chofer_usuario=None, desde=None, hasta=None, cliente=None):
    """Para el Resumen: rendiciones filtrables por chofer, período y cliente."""
    q = "SELECT * FROM rendiciones_corp WHERE 1=1"
    params = []
    if chofer_usuario:
        q += " AND chofer_usuario=?"; params.append(chofer_usuario)
    if desde:
        q += " AND fecha_servicio>=?"; params.append(desde)
    if hasta:
        q += " AND fecha_servicio<=?"; params.append(hasta)
    if cliente:
        q += " AND cliente=?"; params.append(cliente)
    q += " ORDER BY fecha_servicio DESC, id DESC"
    conn = get_connection()
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def config_plus():
    """Cómo está configurado hoy el plus semanal: cuánto es y quién lo cobra.

    Vive en la base, no en el código, porque cambia: la empresa suma o saca
    choferes del plus y a veces mueve el monto. Los valores de arriba
    (PLUS_SEMANAL y CHOFERES_CON_PLUS) son solo el punto de partida la primera
    vez que arranca el sistema.
    """
    import json
    conn = get_connection()
    try:
        rows = {r["clave"]: r["valor"] for r in
                conn.execute("SELECT clave, valor FROM config_corp").fetchall()}
    except Exception:
        rows = {}
    conn.close()

    try:
        monto = float(rows.get("plus_monto") or PLUS_SEMANAL)
    except Exception:
        monto = PLUS_SEMANAL
    try:
        nombres = json.loads(rows.get("plus_choferes") or "null")
        if not isinstance(nombres, list):
            nombres = list(CHOFERES_CON_PLUS)
    except Exception:
        nombres = list(CHOFERES_CON_PLUS)

    return {"monto": round(monto), "choferes": nombres}


def guardar_config_plus(monto, nombres, admin=""):
    """Guarda el monto del plus y la lista de quiénes lo cobran."""
    import json, datetime as _dt
    try:
        monto = float(str(monto).replace(".", "").replace(",", ".") or 0)
    except Exception:
        return False, "El monto del plus no es un número válido."
    if monto < 0:
        return False, "El monto no puede ser negativo."
    nombres = [str(n).strip() for n in (nombres or []) if str(n).strip()]

    conn = get_connection()
    for clave, valor in (("plus_monto", str(int(monto))),
                         ("plus_choferes", json.dumps(nombres, ensure_ascii=False)),
                         ("plus_editado", f"{admin} {_dt.date.today().isoformat()}")):
        try:
            conn.execute("DELETE FROM config_corp WHERE clave=?", (clave,))
            conn.execute("INSERT INTO config_corp (clave, valor) VALUES (?,?)",
                         (clave, valor))
        except Exception:
            conn.rollback()
            conn.close()
            return False, "No se pudo guardar la configuración del plus."
    conn.commit()
    conn.close()
    txt = f"{monto:,.0f}".replace(",", ".")
    return True, f"Plus de Gs. {txt} para {len(nombres)} chofer(es)."


def _tiene_plus(nombre, lista=None):
    """Si a ese chofer le corresponde el plus semanal."""
    if lista is None:
        lista = config_plus()["choferes"]
    return (nombre or "").strip().upper() in [c.strip().upper() for c in lista]


def _semana_de(fecha_iso):
    """Devuelve (año, número de semana ISO) de una fecha 'YYYY-MM-DD'."""
    import datetime as _dt
    try:
        d = _dt.date.fromisoformat(str(fecha_iso)[:10])
        iso = d.isocalendar()
        return (iso[0], iso[1])
    except Exception:
        return None


def liquidacion_por_chofer(rendiciones):
    """Arma el resumen de pago por chofer a partir de una lista de rendiciones.

    Suma lo que generó cada tramo y le agrega el plus semanal a los choferes
    que lo tienen — una vez por cada semana en la que efectivamente trabajó.
    """
    por_chofer = {}
    for r in rendiciones:
        nom = r.get("chofer_nombre") or r.get("chofer_usuario") or "—"
        d = por_chofer.setdefault(nom, {
            "chofer_nombre": nom,
            "chofer_usuario": r.get("chofer_usuario", ""),
            "servicios": 0, "completados": 0, "medios": 0, "suspendidos": 0,
            "monto_tramos": 0, "semanas": set(),
        })
        d["servicios"] += 1
        est = r.get("estado")
        if est == "completado":
            d["completados"] += 1
        elif est in ("entrante", "saliente"):
            d["medios"] += 1
        elif est == "suspendido":
            d["suspendidos"] += 1
        d["monto_tramos"] += float(r.get("monto") or 0)
        sem = _semana_de(r.get("fecha_servicio"))
        if sem and est != "suspendido":
            d["semanas"].add(sem)

    cfg_plus = config_plus()
    salida = []
    for nom, d in por_chofer.items():
        tiene_plus = _tiene_plus(nom, cfg_plus["choferes"])
        semanas = len(d["semanas"])
        plus = cfg_plus["monto"] * semanas if tiene_plus else 0
        salida.append({
            "chofer_nombre": d["chofer_nombre"],
            "chofer_usuario": d["chofer_usuario"],
            "servicios": d["servicios"],
            "completados": d["completados"],
            "medios": d["medios"],
            "suspendidos": d["suspendidos"],
            "monto_tramos": round(d["monto_tramos"]),
            "tiene_plus": tiene_plus,
            "semanas_trabajadas": semanas,
            "plus": plus,
            "total": round(d["monto_tramos"]) + plus,
        })
    salida.sort(key=lambda x: -x["total"])
    return salida


def resumen_pendiente_chofer(chofer_usuario):
    """Lo que el chofer tiene acumulado SIN liquidar: cuánto suma y de qué
    semanas. Es lo que ve en «Mis rendiciones»."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT fecha_servicio, estado, monto FROM rendiciones_corp
        WHERE chofer_usuario=? AND COALESCE(liquidado,0)=0
    """, (chofer_usuario,)).fetchall()
    conn.close()
    total = sum(float(r["monto"] or 0) for r in rows)
    semanas = {_semana_de(r["fecha_servicio"]) for r in rows
               if r["estado"] != "suspendido" and _semana_de(r["fecha_servicio"])}
    return {"total_acumulado": round(total), "servicios": len(rows),
            "semanas": len(semanas)}


def semanas_liquidables(chofer_usuario):
    """Las semanas con rendiciones pendientes de un chofer, cada una con su
    rango de fechas y su total. Es lo que el admin elige para liquidar."""
    import datetime as _dt
    conn = get_connection()
    rows = conn.execute("""
        SELECT id, fecha_servicio, estado, monto, cliente, tramo
        FROM rendiciones_corp
        WHERE chofer_usuario=? AND COALESCE(liquidado,0)=0
        ORDER BY fecha_servicio
    """, (chofer_usuario,)).fetchall()
    conn.close()

    tiene_plus = False
    conn = get_connection()
    u = conn.execute("SELECT nombre FROM usuarios WHERE usuario=?",
                     (chofer_usuario,)).fetchone()
    conn.close()
    if u:
        tiene_plus = _tiene_plus(u["nombre"])

    grupos = {}
    for r in rows:
        sem = _semana_de(r["fecha_servicio"])
        if not sem:
            continue
        g = grupos.setdefault(sem, {"anio": sem[0], "semana_iso": sem[1],
                                    "servicios": 0, "monto_tramos": 0,
                                    "trabajo": False, "fechas": []})
        g["servicios"] += 1
        g["monto_tramos"] += float(r["monto"] or 0)
        g["fechas"].append(r["fecha_servicio"])
        if r["estado"] != "suspendido":
            g["trabajo"] = True

    salida = []
    for sem, g in sorted(grupos.items()):
        fechas = sorted(g["fechas"])
        # Lunes a domingo de esa semana ISO
        try:
            lunes = _dt.date.fromisocalendar(g["anio"], g["semana_iso"], 1)
            domingo = _dt.date.fromisocalendar(g["anio"], g["semana_iso"], 7)
            rango = f"{lunes.isoformat()} a {domingo.isoformat()}"
        except Exception:
            rango = f"{fechas[0]} a {fechas[-1]}"
        plus = config_plus()["monto"] if (tiene_plus and g["trabajo"]) else 0
        salida.append({
            "anio": g["anio"], "semana_iso": g["semana_iso"],
            "rango": rango, "desde": (lunes.isoformat() if 'lunes' in dir() else fechas[0]),
            "hasta": (domingo.isoformat() if 'domingo' in dir() else fechas[-1]),
            "servicios": g["servicios"],
            "monto_tramos": round(g["monto_tramos"]),
            "plus": plus,
            "total": round(g["monto_tramos"]) + plus,
        })
    return salida


def historial_liquidaciones(chofer_usuario=None, desde=None, hasta=None):
    """Todo lo que ya se pagó: cada liquidación con su fecha, el período que
    cubrió, cuánto fue y quién la autorizó.

    Cada vez que se liquida una semana queda marcado el momento exacto, así que
    las rendiciones pagadas en el mismo instante forman un pago. El filtro de
    fechas es por CUÁNDO SE PAGÓ, no por cuándo se prestó el servicio.
    """
    q = """SELECT chofer_usuario, chofer_nombre, fecha_servicio, estado, monto,
                  fecha_liquidacion, liquidado_por, cliente, tramo
           FROM rendiciones_corp
           WHERE COALESCE(liquidado,0)=1 AND fecha_liquidacion IS NOT NULL"""
    params = []
    if chofer_usuario:
        q += " AND chofer_usuario=?"; params.append(chofer_usuario)
    if desde:
        q += " AND fecha_liquidacion>=?"; params.append(desde)
    if hasta:
        q += " AND fecha_liquidacion<=?"; params.append(hasta + "T23:59:59")
    q += " ORDER BY fecha_liquidacion DESC"

    conn = get_connection()
    rows = [dict(r) for r in conn.execute(q, params).fetchall()]
    conn.close()

    cfg = config_plus()
    pagos = {}
    for r in rows:
        # Un pago = mismo chofer, mismo momento de liquidación
        clave = (r["chofer_usuario"], r["fecha_liquidacion"])
        p = pagos.setdefault(clave, {
            "chofer_usuario": r["chofer_usuario"],
            "chofer_nombre": r["chofer_nombre"],
            "fecha_pago": r["fecha_liquidacion"],
            "liquidado_por": r["liquidado_por"] or "—",
            "servicios": 0, "monto_tramos": 0,
            "semanas": set(), "fechas": [], "detalle": [],
        })
        p["servicios"] += 1
        p["monto_tramos"] += float(r["monto"] or 0)
        p["fechas"].append(r["fecha_servicio"])
        p["detalle"].append(r)
        sem = _semana_de(r["fecha_servicio"])
        if sem and r["estado"] != "suspendido":
            p["semanas"].add(sem)

    salida = []
    for p in pagos.values():
        tiene_plus = _tiene_plus(p["chofer_nombre"], cfg["choferes"])
        plus = cfg["monto"] * len(p["semanas"]) if tiene_plus else 0
        fechas = sorted(p["fechas"])
        salida.append({
            "chofer_usuario": p["chofer_usuario"],
            "chofer_nombre": p["chofer_nombre"],
            "fecha_pago": p["fecha_pago"],
            "liquidado_por": p["liquidado_por"],
            "servicios": p["servicios"],
            "periodo_desde": fechas[0] if fechas else "",
            "periodo_hasta": fechas[-1] if fechas else "",
            "semanas": len(p["semanas"]),
            "monto_tramos": round(p["monto_tramos"]),
            "plus": plus,
            "total": round(p["monto_tramos"]) + plus,
            "detalle": p["detalle"],
        })
    salida.sort(key=lambda x: x["fecha_pago"], reverse=True)
    return salida


def resumen_historial(pagos):
    """Totales del histórico: cuánto se pagó en total y cuánto a cada chofer."""
    por_chofer = {}
    for p in pagos:
        d = por_chofer.setdefault(p["chofer_nombre"], {
            "chofer_nombre": p["chofer_nombre"],
            "chofer_usuario": p["chofer_usuario"],
            "pagos": 0, "servicios": 0, "total": 0,
            "ultimo_pago": "",
        })
        d["pagos"] += 1
        d["servicios"] += p["servicios"]
        d["total"] += p["total"]
        if p["fecha_pago"] > d["ultimo_pago"]:
            d["ultimo_pago"] = p["fecha_pago"]
    lista = sorted(por_chofer.values(),
                   key=lambda x: (x["chofer_nombre"] or "").upper())
    return {"por_chofer": lista,
            "total_pagado": sum(p["total"] for p in pagos),
            "cantidad_pagos": len(pagos)}


def liquidar_semana(chofer_usuario, anio, semana_iso, admin=""):
    """Marca como liquidadas todas las rendiciones pendientes de ese chofer en
    esa semana ISO. Dejan de aparecerle en «Mis rendiciones»; el admin las
    sigue viendo buscando por fecha en el Resumen."""
    import datetime as _dt
    try:
        lunes = _dt.date.fromisocalendar(int(anio), int(semana_iso), 1)
        domingo = _dt.date.fromisocalendar(int(anio), int(semana_iso), 7)
    except Exception:
        return False, "Semana inválida.", 0
    ahora = _dt.datetime.now().isoformat(timespec="seconds")
    conn = get_connection()
    n = conn.execute("""
        SELECT COUNT(*) AS c FROM rendiciones_corp
        WHERE chofer_usuario=? AND COALESCE(liquidado,0)=0
          AND fecha_servicio>=? AND fecha_servicio<=?
    """, (chofer_usuario, lunes.isoformat(), domingo.isoformat())).fetchone()["c"]
    if n == 0:
        conn.close()
        return False, "No había rendiciones pendientes en esa semana.", 0
    conn.execute("""
        UPDATE rendiciones_corp
        SET liquidado=1, fecha_liquidacion=?, liquidado_por=?
        WHERE chofer_usuario=? AND COALESCE(liquidado,0)=0
          AND fecha_servicio>=? AND fecha_servicio<=?
    """, (ahora, admin, chofer_usuario, lunes.isoformat(), domingo.isoformat()))
    conn.commit()
    conn.close()
    return True, f"Se liquidaron {n} servicio(s) de la semana.", n


def revertir_liquidacion(chofer_usuario, anio, semana_iso):
    """Deshace una liquidación (por si se marcó por error): las rendiciones de
    esa semana vuelven a estar pendientes y reaparecen en el celular del chofer."""
    import datetime as _dt
    try:
        lunes = _dt.date.fromisocalendar(int(anio), int(semana_iso), 1)
        domingo = _dt.date.fromisocalendar(int(anio), int(semana_iso), 7)
    except Exception:
        return False, "Semana inválida.", 0
    conn = get_connection()
    n = conn.execute("""
        SELECT COUNT(*) AS c FROM rendiciones_corp
        WHERE chofer_usuario=? AND COALESCE(liquidado,0)=1
          AND fecha_servicio>=? AND fecha_servicio<=?
    """, (chofer_usuario, lunes.isoformat(), domingo.isoformat())).fetchone()["c"]
    if n == 0:
        conn.close()
        return False, "No había nada liquidado en esa semana.", 0
    conn.execute("""
        UPDATE rendiciones_corp
        SET liquidado=0, fecha_liquidacion=NULL, liquidado_por=''
        WHERE chofer_usuario=? AND COALESCE(liquidado,0)=1
          AND fecha_servicio>=? AND fecha_servicio<=?
    """, (chofer_usuario, lunes.isoformat(), domingo.isoformat()))
    conn.commit()
    conn.close()
    return True, f"Se revirtieron {n} servicio(s).", n


def actualizar_monto_rendicion(rid, monto, admin=""):
    """Corrige a mano el monto de una rendición y lo deja FIJO: el recálculo
    automático del arranque no lo vuelve a pisar."""
    import datetime as _dt
    try:
        monto = float(str(monto).replace(".", "").replace(",", ".") or 0)
    except Exception:
        return False, "El monto no es un número válido."
    if monto < 0:
        return False, "El monto no puede ser negativo."

    conn = get_connection()
    row = conn.execute("""SELECT chofer_nombre, liquidado FROM rendiciones_corp
                          WHERE id=?""", (int(rid),)).fetchone()
    if not row:
        conn.close()
        return False, "No encontré esa rendición."
    if row["liquidado"]:
        conn.close()
        return False, ("Esa rendición ya fue liquidada. Revertí la liquidación "
                       "de esa semana antes de cambiarle el monto.")
    conn.execute("""UPDATE rendiciones_corp
        SET monto=?, monto_fijo=1, editado_por=?, fecha_edicion=?
        WHERE id=?""",
        (monto, admin, _dt.datetime.now().isoformat(timespec="seconds"), int(rid)))
    conn.commit()
    conn.close()
    txt = f"{monto:,.0f}".replace(",", ".")
    return True, f"Monto fijado en Gs. {txt} para {row['chofer_nombre']}."


def liberar_monto_rendicion(rid):
    """Deshace la corrección manual: el monto vuelve a calcularse por las
    reglas de tarifa (tramo + estado)."""
    conn = get_connection()
    row = conn.execute("""SELECT cliente, tramo, estado, liquidado FROM rendiciones_corp
                          WHERE id=?""", (int(rid),)).fetchone()
    if not row:
        conn.close()
        return False, "No encontré esa rendición."
    if row["liquidado"]:
        conn.close()
        return False, "Esa rendición ya fue liquidada."
    monto = calcular_monto(row["tramo"], row["estado"], row["cliente"])
    conn.execute("""UPDATE rendiciones_corp
        SET monto=?, monto_fijo=0, editado_por='', fecha_edicion=NULL
        WHERE id=?""", (monto, int(rid)))
    conn.commit()
    conn.close()
    txt = f"{monto:,.0f}".replace(",", ".")
    return True, f"Monto recalculado por tarifa: Gs. {txt}."


def eliminar_rendicion(rid):
    """Borra una rendición. Al hacerlo, ese tramo/cliente/fecha queda libre
    para que alguien lo vuelva a cargar."""
    conn = get_connection()
    row = conn.execute("""SELECT chofer_nombre, cliente, tramo, fecha_servicio, liquidado
                          FROM rendiciones_corp WHERE id=?""", (int(rid),)).fetchone()
    if not row:
        conn.close()
        return False, "No encontré esa rendición."
    if row["liquidado"]:
        conn.close()
        return False, ("Esa rendición ya fue liquidada — no se puede borrar. "
                       "Revertí la liquidación de esa semana primero.")
    conn.execute("DELETE FROM rendiciones_corp WHERE id=?", (int(rid),))
    conn.commit()
    conn.close()
    return True, (f"Se eliminó el servicio de {row['chofer_nombre']} "
                  f"({row['cliente']} · {row['fecha_servicio']}). El tramo quedó libre.")


def rendiciones_descartables(desde=None, hasta=None):
    """Servicios que probablemente haya que limpiar: los suspendidos (no se
    prestaron) y los incompletos (quedaron cargados a medias, sin horario ni
    kilometraje ni pasajeros). Nunca incluye los ya liquidados."""
    q = """SELECT id, chofer_nombre, cliente, tramo, fecha_servicio, estado,
                  hora_inicio, hora_fin, km_final, pasajeros, monto, observacion
           FROM rendiciones_corp
           WHERE COALESCE(liquidado,0)=0"""
    params = []
    if desde:
        q += " AND fecha_servicio>=?"; params.append(desde)
    if hasta:
        q += " AND fecha_servicio<=?"; params.append(hasta)
    q += " ORDER BY fecha_servicio DESC, id DESC"
    conn = get_connection()
    rows = [dict(r) for r in conn.execute(q, params).fetchall()]
    conn.close()

    suspendidas, incompletas = [], []
    for r in rows:
        if r["estado"] == "suspendido":
            r["motivo"] = "Suspendido — el servicio no se prestó"
            suspendidas.append(r)
            continue
        vacio = (not (r.get("hora_inicio") or "").strip()
                 and not float(r.get("km_final") or 0)
                 and not int(r.get("pasajeros") or 0))
        if vacio:
            r["motivo"] = "Sin horario, ni kilometraje, ni pasajeros"
            incompletas.append(r)
    return {"suspendidas": suspendidas, "incompletas": incompletas,
            "total": len(suspendidas) + len(incompletas)}


def eliminar_rendiciones(ids):
    """Borra varias rendiciones de una. Saltea las ya liquidadas."""
    borradas, saltadas = 0, 0
    for rid in ids:
        ok, _ = eliminar_rendicion(rid)
        if ok:
            borradas += 1
        else:
            saltadas += 1
    msg = f"Se eliminaron {borradas} servicio(s)."
    if saltadas:
        msg += f" {saltadas} no se tocaron por estar ya liquidados."
    return borradas, saltadas, msg


def choferes_corp_registrados():
    """Lista de choferes corp (de la tabla de usuarios) para el filtro del
    Resumen — usuario + nombre."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT usuario, nombre FROM usuarios
        WHERE rol='chofer_corp' AND activo=1 ORDER BY nombre
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINTS — carga (chofer) y consulta (admin)
# ════════════════════════════════════════════════════════════════════════════

@bp_corp.route("/api/corp/config", methods=["GET"])
def api_corp_config():
    """Clientes y tramos para los selectores encadenados del reporte.
    Solo se ofrecen las empresas que siguen operando con La Santaniana."""
    activos = {k: v for k, v in CLIENTES_TRAMOS.items() if k not in CLIENTES_INACTIVOS}
    # Las tarifas se envían para que el chofer vea en vivo cuánto suma cada
    # servicio mientras lo carga.
    return jsonify({
        "clientes_tramos": activos,
        "tarifas": {"completado": MONTO_COMPLETADO, "medio": MONTO_MEDIO,
                    "variable": MONTO_VARIABLE},
    })


@bp_corp.route("/api/corp/disponibilidad", methods=["GET"])
def api_corp_disponibilidad():
    """Le avisa al chofer si el tramo que eligió ya fue reportado, y por quién,
    antes de que llene todo el formulario."""
    if session.get("rol") not in ("chofer_corp", "admin"):
        return jsonify({"error": "Sin permiso"}), 403
    cliente = request.args.get("cliente", "")
    tramo = request.args.get("tramo", "")
    fecha = request.args.get("fecha", "")
    if not (cliente and tramo and fecha):
        return jsonify({"libre": True, "tomados": []})
    return jsonify(segmentos_tomados(cliente, tramo, fecha))


@bp_corp.route("/api/corp/rendicion", methods=["POST"])
def api_corp_rendicion():
    """El chofer carga una rendición desde el celular."""
    if session.get("rol") not in ("chofer_corp", "admin"):
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    d = request.json or {}
    d["chofer_usuario"] = session.get("usuario", "")
    d["chofer_nombre"] = session.get("nombre", "") or session.get("usuario", "")
    ok, msg = registrar_rendicion(d)
    return jsonify({"ok": ok, "msg": msg}), (200 if ok else 400)


@bp_corp.route("/api/corp/mis_rendiciones", methods=["GET"])
def api_corp_mis_rendiciones():
    """Las rendiciones PENDIENTES del chofer logueado, con su monto y el total
    acumulado. Cuando el admin liquida una semana, esas dejan de aparecer acá."""
    if session.get("rol") not in ("chofer_corp", "admin"):
        return jsonify({"error": "Sin permiso"}), 403
    usuario = session.get("usuario", "")
    return jsonify({
        "rendiciones": rendiciones_de_chofer(usuario),
        "resumen": resumen_pendiente_chofer(usuario),
    })


@bp_corp.route("/api/corp/rendicion/<int:rid>/monto", methods=["POST"])
def api_corp_editar_monto(rid):
    """Corrige el monto de un servicio y lo deja fijo."""
    if session.get("rol") != "admin":
        return jsonify({"error": "Sin permiso"}), 403
    d = request.json or {}
    if d.get("recalcular"):
        ok, msg = liberar_monto_rendicion(rid)
    else:
        ok, msg = actualizar_monto_rendicion(
            rid, d.get("monto"),
            admin=session.get("nombre") or session.get("usuario", ""))
    if ok:
        auditar(f"Editó el monto de la rendición #{rid}", "Corporativos", msg)
    return jsonify({"ok": ok, "msg": msg}), (200 if ok else 400)


@bp_corp.route("/api/corp/rendicion/<int:rid>", methods=["DELETE"])
def api_corp_eliminar_rendicion(rid):
    """Elimina un servicio cargado."""
    if session.get("rol") != "admin":
        return jsonify({"error": "Sin permiso"}), 403
    ok, msg = eliminar_rendicion(rid)
    if ok:
        auditar(f"Eliminó la rendición #{rid}", "Corporativos", msg)
    return jsonify({"ok": ok, "msg": msg}), (200 if ok else 400)


@bp_corp.route("/api/corp/descartables", methods=["GET"])
def api_corp_descartables():
    """Servicios suspendidos o cargados a medias, candidatos a limpiar."""
    if session.get("rol") != "admin":
        return jsonify({"error": "Sin permiso"}), 403
    return jsonify(rendiciones_descartables(
        desde=request.args.get("desde") or None,
        hasta=request.args.get("hasta") or None))


@bp_corp.route("/api/corp/eliminar_lote", methods=["POST"])
def api_corp_eliminar_lote():
    """Elimina varios servicios de una."""
    if session.get("rol") != "admin":
        return jsonify({"error": "Sin permiso"}), 403
    ids = (request.json or {}).get("ids", [])
    if not ids:
        return jsonify({"ok": False, "msg": "No seleccionaste nada."}), 400
    borradas, saltadas, msg = eliminar_rendiciones(ids)
    auditar(f"Eliminó {borradas} rendiciones en lote", "Corporativos", msg)
    return jsonify({"ok": True, "borradas": borradas, "msg": msg})


@bp_corp.route("/api/corp/config_plus", methods=["GET"])
def api_corp_config_plus():
    """Cómo está el plus hoy: monto y qué choferes lo cobran, junto con la
    lista completa de choferes para poder marcarlos."""
    if session.get("rol") != "admin":
        return jsonify({"error": "Sin permiso"}), 403
    cfg = config_plus()
    conn = get_connection()
    todos = [dict(r) for r in conn.execute("""
        SELECT usuario, nombre FROM usuarios
        WHERE rol='chofer_corp' AND activo=1 ORDER BY nombre
    """).fetchall()]
    conn.close()
    con_plus = [c.strip().upper() for c in cfg["choferes"]]
    for t in todos:
        t["tiene_plus"] = (t["nombre"] or "").strip().upper() in con_plus
    return jsonify({"monto": cfg["monto"], "choferes": todos,
                    "nombres_con_plus": cfg["choferes"]})


@bp_corp.route("/api/corp/config_plus", methods=["POST"])
def api_corp_guardar_config_plus():
    """Guarda el monto del plus y a quiénes les corresponde."""
    if session.get("rol") != "admin":
        return jsonify({"error": "Sin permiso"}), 403
    d = request.json or {}
    ok, msg = guardar_config_plus(
        d.get("monto"), d.get("choferes", []),
        admin=session.get("nombre") or session.get("usuario", ""))
    if ok:
        auditar("Cambió la configuración del plus semanal", "Corporativos", msg)
    return jsonify({"ok": ok, "msg": msg}), (200 if ok else 400)


@bp_corp.route("/api/corp/tarifas", methods=["GET"])
def api_corp_tarifas():
    """Precio de cada tramo, agrupado por cliente, para editarlo en pantalla."""
    if session.get("rol") != "admin":
        return jsonify({"error": "Sin permiso"}), 403
    t = tarifas_tramos()
    salida = []
    for cliente, tramos in CLIENTES_TRAMOS.items():
        if cliente in CLIENTES_INACTIVOS:
            continue
        salida.append({
            "cliente": cliente,
            "tramos": [{"tramo": tr,
                        "clave": f"{cliente}|{tr}",
                        "completo": t.get(f"{cliente}|{tr}", 0),
                        "mitad": round(t.get(f"{cliente}|{tr}", 0) / 2)}
                       for tr in tramos],
        })
    return jsonify({"clientes": salida})


@bp_corp.route("/api/corp/tarifas", methods=["POST"])
def api_corp_guardar_tarifas():
    """Guarda el precio de los tramos que se hayan tocado."""
    if session.get("rol") != "admin":
        return jsonify({"error": "Sin permiso"}), 403
    d = request.json or {}
    ok, msg = guardar_tarifas(
        d.get("tarifas", {}),
        admin=session.get("nombre") or session.get("usuario", ""))
    if ok:
        auditar("Actualizó las tarifas de los tramos", "Corporativos", msg)
    return jsonify({"ok": ok, "msg": msg}), (200 if ok else 400)


@bp_corp.route("/api/corp/accesos", methods=["GET"])
def api_corp_accesos():
    """Lista de choferes con su usuario, para que el admin sepa qué darle a
    cada uno. La contraseña inicial es igual al usuario."""
    if session.get("rol") != "admin":
        return jsonify({"error": "Sin permiso"}), 403
    conn = get_connection()
    filas = [dict(r) for r in conn.execute("""
        SELECT usuario, nombre, activo FROM usuarios
        WHERE rol='chofer_corp' ORDER BY nombre
    """).fetchall()]
    conn.close()
    con_cuenta = {(f["nombre"] or "").strip().upper() for f in filas}
    faltantes = [n for n in CHOFERES_CORP if n.strip().upper() not in con_cuenta]
    return jsonify({"choferes": filas, "faltantes": faltantes,
                    "total_esperado": len(CHOFERES_CORP)})


@bp_corp.route("/api/corp/rendiciones", methods=["GET"])
def api_corp_rendiciones():
    """Resumen para admin/auditor: filtrable por chofer, período, cliente.
    Devuelve las rendiciones y la liquidación por chofer (tramos + plus)."""
    if session.get("rol") not in ("admin", "auditor"):
        return jsonify({"error": "Sin permiso"}), 403
    rends = obtener_rendiciones(
        chofer_usuario=request.args.get("chofer") or None,
        desde=request.args.get("desde") or None,
        hasta=request.args.get("hasta") or None,
        cliente=request.args.get("cliente") or None)
    return jsonify({
        "rendiciones": rends,
        "liquidacion": liquidacion_por_chofer(rends),
    })


@bp_corp.route("/api/corp/choferes", methods=["GET"])
def api_corp_choferes():
    """Lista de choferes corp para el filtro del Resumen."""
    if session.get("rol") not in ("admin", "auditor"):
        return jsonify({"error": "Sin permiso"}), 403
    return jsonify(choferes_corp_registrados())


@bp_corp.route("/api/corp/semanas_liquidables", methods=["GET"])
def api_corp_semanas_liquidables():
    """Las semanas pendientes de pago de un chofer, para que el admin elija
    cuál liquidar cuando le hace firmar."""
    if session.get("rol") != "admin":
        return jsonify({"error": "Sin permiso"}), 403
    chofer = request.args.get("chofer", "")
    if not chofer:
        return jsonify({"error": "Falta el chofer"}), 400
    return jsonify(semanas_liquidables(chofer))


@bp_corp.route("/api/corp/liquidar", methods=["POST"])
def api_corp_liquidar():
    """Marca una semana como liquidada (ya se le pagó al chofer). Sus
    rendiciones dejan de aparecerle en el celular."""
    if session.get("rol") != "admin":
        return jsonify({"error": "Sin permiso"}), 403
    d = request.json or {}
    chofer = d.get("chofer", "")
    anio = d.get("anio")
    semana = d.get("semana_iso")
    if not (chofer and anio and semana):
        return jsonify({"ok": False, "msg": "Faltan datos de la semana"}), 400
    ok, msg, n = liquidar_semana(chofer, anio, semana,
                                 admin=session.get("nombre") or session.get("usuario", ""))
    if ok:
        auditar(f"Liquidó la semana {semana}/{anio} de {chofer}",
                "Corporativos", msg)
    return jsonify({"ok": ok, "msg": msg, "liquidadas": n})


@bp_corp.route("/api/corp/revertir_liquidacion", methods=["POST"])
def api_corp_revertir():
    """Deshace una liquidación marcada por error."""
    if session.get("rol") != "admin":
        return jsonify({"error": "Sin permiso"}), 403
    d = request.json or {}
    chofer = d.get("chofer", "")
    anio = d.get("anio")
    semana = d.get("semana_iso")
    if not (chofer and anio and semana):
        return jsonify({"ok": False, "msg": "Faltan datos"}), 400
    ok, msg, n = revertir_liquidacion(chofer, anio, semana)
    if ok:
        auditar(f"Revirtió la liquidación {semana}/{anio} de {chofer}",
                "Corporativos", msg)
    return jsonify({"ok": ok, "msg": msg, "revertidas": n})


@bp_corp.route("/api/corp/historial_liquidaciones", methods=["GET"])
def api_corp_historial():
    """Todo lo que ya se le pagó a los choferes, con fecha y responsable."""
    if session.get("rol") not in ("admin", "auditor"):
        return jsonify({"error": "Sin permiso"}), 403
    pagos = historial_liquidaciones(
        chofer_usuario=request.args.get("chofer") or None,
        desde=request.args.get("desde") or None,
        hasta=request.args.get("hasta") or None)
    # El detalle de cada pago no viaja en el listado: se pide aparte
    liviano = [{k: v for k, v in p.items() if k != "detalle"} for p in pagos]
    return jsonify({"pagos": liviano, "resumen": resumen_historial(pagos)})


@bp_corp.route("/api/corp/historial_pdf", methods=["GET"])
def api_corp_historial_pdf():
    """PDF del histórico de pagos, como respaldo para Recursos Humanos."""
    if session.get("rol") not in ("admin", "auditor"):
        return jsonify({"error": "Sin permiso"}), 403
    from flask import send_file
    import io
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    pagos = historial_liquidaciones(
        chofer_usuario=request.args.get("chofer") or None,
        desde=desde, hasta=hasta)
    return send_file(io.BytesIO(generar_pdf_historial(pagos, desde, hasta)),
                     mimetype="application/pdf", as_attachment=False,
                     download_name="historial_pagos.pdf")


@bp_corp.route("/api/corp/rendiciones_pdf", methods=["GET"])
def api_corp_rendiciones_pdf():
    """PDF de la liquidación. Con ?resumen=1 sale la versión corta: una sola
    hoja con el total de cada chofer, en orden alfabético."""
    if session.get("rol") not in ("admin", "auditor"):
        return jsonify({"error": "Sin permiso"}), 403
    from flask import send_file
    import io
    chofer = request.args.get("chofer") or None
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    cliente = request.args.get("cliente") or None
    resumen = request.args.get("resumen") in ("1", "true", "si")
    rends = obtener_rendiciones(chofer, desde, hasta, cliente)
    nombre = rends[0]["chofer_nombre"] if rends else (chofer or "Todos")
    if resumen:
        pdf_bytes = generar_pdf_resumen_liquidacion(rends, desde, hasta)
        archivo = "liquidacion_resumen.pdf"
    else:
        pdf_bytes = generar_pdf_rendiciones(rends, nombre, desde, hasta)
        archivo = f"liquidacion_{(chofer or 'todos')}.pdf"
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                     as_attachment=False, download_name=archivo)


def generar_pdf_historial(pagos, desde, hasta):
    """PDF del histórico de pagos: qué se le liquidó a cada chofer y cuándo.
    Primero el total por chofer, después el detalle de cada pago realizado."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph, Spacer)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    import io

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=14*mm, rightMargin=14*mm,
                            topMargin=15*mm, bottomMargin=14*mm,
                            title="Historial de pagos")
    S = getSampleStyleSheet()
    AZUL = colors.HexColor("#1E5A96")
    GRIS = colors.HexColor("#666666")
    SUAVE = colors.HexColor("#F7F6F3")

    st_tit = ParagraphStyle("t", parent=S["Title"], fontSize=15, textColor=AZUL,
                            alignment=1, spaceAfter=1)
    st_per = ParagraphStyle("p", parent=S["Normal"], fontSize=9.5,
                            textColor=GRIS, alignment=1, spaceAfter=9)
    st_sec = ParagraphStyle("s", parent=S["Normal"], fontSize=10.5,
                            textColor=AZUL, fontName="Helvetica-Bold",
                            spaceBefore=10, spaceAfter=4)

    def gs(v):
        return f'{round(v or 0):,}'.replace(",", ".")

    elems = [Paragraph("Historial de pagos — Servicios Corporativos", st_tit)]
    rango = ""
    if desde or hasta:
        rango = f"Pagos realizados entre {desde or '...'} y {hasta or '...'}"
    elems.append(Paragraph(rango or "Todos los pagos registrados", st_per))

    if not pagos:
        elems.append(Paragraph("No hay pagos registrados en ese período.",
                               S["Normal"]))
        doc.build(elems)
        return buf.getvalue()

    res = resumen_historial(pagos)

    # ── Total pagado a cada chofer ──
    elems.append(Paragraph("Total pagado por chofer", st_sec))
    d1 = [["Chofer", "Pagos", "Servicios", "Último pago", "Total Gs."]]
    for c in res["por_chofer"]:
        d1.append([c["chofer_nombre"], str(c["pagos"]), str(c["servicios"]),
                   (c["ultimo_pago"] or "")[:10], gs(c["total"])])
    d1.append(["TOTAL PAGADO", "", "", "", gs(res["total_pagado"])])
    t1 = Table(d1, repeatRows=1, colWidths=[62*mm, 20*mm, 26*mm, 32*mm, 32*mm])
    t1.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
        ("FONTNAME", (-1, 1), (-1, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, SUAVE]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EAF1F8")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elems.append(t1)

    # ── Cada pago, uno por uno ──
    elems.append(Paragraph(f"Detalle de los pagos ({len(pagos)})", st_sec))
    d2 = [["Fecha del pago", "Chofer", "Período cubierto", "Serv.",
           "Tramos Gs.", "Plus Gs.", "Total Gs.", "Autorizó"]]
    for p in pagos:
        d2.append([
            (p["fecha_pago"] or "").replace("T", " ")[:16],
            p["chofer_nombre"],
            f'{p["periodo_desde"]} a {p["periodo_hasta"]}',
            str(p["servicios"]),
            gs(p["monto_tramos"]),
            gs(p["plus"]) if p["plus"] else "—",
            gs(p["total"]),
            p["liquidado_por"],
        ])
    t2 = Table(d2, repeatRows=1,
               colWidths=[27*mm, 40*mm, 38*mm, 12*mm, 22*mm, 19*mm, 22*mm, 22*mm])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 7.5),
        ("FONTSIZE", (0, 1), (-1, -1), 7),
        ("ALIGN", (3, 0), (6, -1), "RIGHT"),
        ("FONTNAME", (6, 1), (6, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SUAVE]),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    elems.append(t2)

    elems.append(Spacer(1, 8))
    elems.append(Paragraph(
        f"{res['cantidad_pagos']} pago(s) · Total pagado: <b>Gs. {gs(res['total_pagado'])}</b>",
        ParagraphStyle("f", parent=S["Normal"], fontSize=10, textColor=AZUL,
                       alignment=2)))

    doc.build(elems)
    return buf.getvalue()


def generar_pdf_resumen_liquidacion(rends, desde, hasta):
    """Versión corta de la liquidación: UNA hoja con el total de cada chofer,
    en orden alfabético. Es lo que Recursos Humanos necesita para saber cuánto
    pagarle a cada uno, sin el detalle de los servicios.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph, Spacer)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    import io

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=14*mm, rightMargin=14*mm,
                            topMargin=15*mm, bottomMargin=14*mm,
                            title="Resumen de liquidación")
    S = getSampleStyleSheet()
    AZUL = colors.HexColor("#1E5A96")
    GRIS = colors.HexColor("#666666")
    SUAVE = colors.HexColor("#F7F6F3")

    st_tit = ParagraphStyle("t", parent=S["Title"], fontSize=15, textColor=AZUL,
                            alignment=1, spaceAfter=1)
    st_per = ParagraphStyle("p", parent=S["Normal"], fontSize=9.5,
                            textColor=GRIS, alignment=1, spaceAfter=10)

    def gs(v):
        return f'{round(v or 0):,}'.replace(",", ".")

    elems = [Paragraph("Resumen de liquidación — Servicios Corporativos", st_tit)]
    if desde or hasta:
        elems.append(Paragraph(f"Período: {desde or '...'} al {hasta or '...'}", st_per))
    else:
        elems.append(Spacer(1, 8))

    liq = liquidacion_por_chofer(rends)
    if not liq:
        elems.append(Paragraph("No hay servicios en el período seleccionado.",
                               S["Normal"]))
        doc.build(elems)
        return buf.getvalue()

    # Orden alfabético por nombre de chofer
    liq.sort(key=lambda l: (l.get("chofer_nombre") or "").upper())

    data = [["#", "Chofer", "Serv.", "Tramos Gs.", "Plus Gs.", "TOTAL Gs.", "Firma"]]
    total_general = 0
    for i, l in enumerate(liq, start=1):
        total_general += l.get("total", 0)
        data.append([
            str(i),
            l.get("chofer_nombre", ""),
            str(l.get("servicios", 0)),
            gs(l.get("monto_tramos", 0)),
            gs(l.get("plus", 0)) if l.get("tiene_plus") else "—",
            gs(l.get("total", 0)),
            "",
        ])
    data.append(["", "TOTAL A LIQUIDAR", "", "", "", gs(total_general), ""])

    t = Table(data, repeatRows=1,
              colWidths=[9*mm, 58*mm, 13*mm, 26*mm, 24*mm, 28*mm, 24*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (2, 0), (5, -1), "RIGHT"),
        ("FONTNAME", (5, 1), (5, -1), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, SUAVE]),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EAF1F8")),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    elems.append(t)

    elems.append(Spacer(1, 10))
    elems.append(Paragraph(
        f"{len(liq)} chofer(es) · Total a liquidar: <b>Gs. {gs(total_general)}</b>",
        ParagraphStyle("f", parent=S["Normal"], fontSize=10, textColor=AZUL,
                       alignment=2)))

    doc.build(elems)
    return buf.getvalue()


def generar_pdf_rendiciones(rends, nombre_chofer, desde, hasta):
    """Planilla de liquidación para Recursos Humanos, SEPARADA POR CHOFER.

    Cada chofer ocupa su propia hoja: arriba lo que hay que pagarle bien
    grande, después el detalle de los servicios que lo justifican, y al pie un
    espacio para firmar. Al final, una hoja resumen con el total de todos.
    """
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph, Spacer, PageBreak)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    import io

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=13*mm, rightMargin=13*mm,
                            topMargin=13*mm, bottomMargin=13*mm,
                            title="Liquidación de Servicios Corporativos")
    S = getSampleStyleSheet()
    AZUL = colors.HexColor("#1E5A96")
    ROJO = colors.HexColor("#DC2641")
    GRIS = colors.HexColor("#666666")
    SUAVE = colors.HexColor("#F7F6F3")

    st_tit = ParagraphStyle("t", parent=S["Title"], fontSize=14, textColor=AZUL,
                            alignment=1, spaceAfter=1)
    st_per = ParagraphStyle("p", parent=S["Normal"], fontSize=9,
                            textColor=GRIS, alignment=1, spaceAfter=6)
    st_nom = ParagraphStyle("n", parent=S["Normal"], fontSize=16,
                            textColor=colors.HexColor("#1A1A18"),
                            fontName="Helvetica-Bold", spaceAfter=1)
    st_sub = ParagraphStyle("s", parent=S["Normal"], fontSize=9, textColor=GRIS,
                            spaceAfter=4)
    st_secc = ParagraphStyle("sc", parent=S["Normal"], fontSize=9.5,
                             textColor=AZUL, fontName="Helvetica-Bold",
                             spaceBefore=6, spaceAfter=3)
    st_susp = ParagraphStyle("o", parent=S["Normal"], fontSize=8,
                             textColor=ROJO, leftIndent=6, spaceAfter=1)

    def gs(v):
        return f'{round(v or 0):,}'.replace(",", ".")

    etiqueta = {"completado": "Completo", "entrante": "Entrante",
                "saliente": "Saliente", "suspendido": "Suspendido"}
    periodo = ""
    if desde or hasta:
        periodo = f"Período: {desde or '...'} al {hasta or '...'}"

    elems = []
    if not rends:
        elems.append(Paragraph("Liquidación de Servicios Corporativos", st_tit))
        if periodo:
            elems.append(Paragraph(periodo, st_per))
        elems.append(Spacer(1, 10))
        elems.append(Paragraph("No hay servicios en el período seleccionado.",
                               S["Normal"]))
        doc.build(elems)
        return buf.getvalue()

    por_chofer = {}
    for r in rends:
        nom = r.get("chofer_nombre") or r.get("chofer_usuario") or "—"
        por_chofer.setdefault(nom, []).append(r)
    liq_idx = {l["chofer_nombre"]: l for l in liquidacion_por_chofer(rends)}
    choferes = sorted(por_chofer.keys())
    total_general = 0

    for ci, nom in enumerate(choferes):
        filas = sorted(por_chofer[nom], key=lambda x: x.get("fecha_servicio", ""))
        l = liq_idx.get(nom, {})
        total_general += l.get("total", 0)

        elems.append(Paragraph("Liquidación de Servicios Corporativos", st_tit))
        if periodo:
            elems.append(Paragraph(periodo, st_per))

        # ── Cabecera: quién es y cuánto se le paga ──
        resumen = [[
            Paragraph(nom, st_nom),
            Paragraph("<b>TOTAL A PAGAR</b>", ParagraphStyle(
                "lb", parent=S["Normal"], fontSize=9, textColor=GRIS, alignment=2)),
            Paragraph(f"<b>Gs. {gs(l.get('total', 0))}</b>", ParagraphStyle(
                "tt", parent=S["Normal"], fontSize=19, textColor=AZUL, alignment=2)),
        ]]
        th = Table(resumen, colWidths=[150*mm, 55*mm, 66*mm])
        th.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BACKGROUND", (0, 0), (-1, -1), SUAVE),
            ("BOX", (0, 0), (-1, -1), 0.7, AZUL),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ]))
        elems.append(th)

        # ── Cómo se compone ese total ──
        elems.append(Paragraph("Cómo se compone", st_secc))
        comp = [["Servicios", "Completos", "Medios", "Tramos Gs.",
                 "Semanas c/plus", "Plus Gs.", "TOTAL Gs."],
                [str(l.get("servicios", 0)), str(l.get("completados", 0)),
                 str(l.get("medios", 0)), gs(l.get("monto_tramos", 0)),
                 str(l.get("semanas_trabajadas", 0)) if l.get("tiene_plus") else "—",
                 gs(l.get("plus", 0)) if l.get("tiene_plus") else "—",
                 gs(l.get("total", 0))]]
        tc = Table(comp, colWidths=[30*mm, 30*mm, 26*mm, 42*mm, 38*mm, 36*mm, 44*mm])
        tc.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), AZUL),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (-1, 1), (-1, 1), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
            ("BACKGROUND", (-1, 1), (-1, 1), colors.HexColor("#EAF1F8")),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        elems.append(tc)

        # ── Detalle de los servicios ──
        elems.append(Paragraph(f"Servicios del período ({len(filas)})", st_secc))
        head = ["Fecha", "Cliente", "Tramo", "Bus", "Inicio", "Fin",
                "Pas.", "Estado", "Monto Gs."]
        data = [head]
        for r in filas:
            data.append([
                r.get("fecha_servicio", ""), r.get("cliente", ""),
                (r.get("tramo", "") or "")[:34], str(r.get("bus_interno", "")),
                r.get("hora_inicio", ""), r.get("hora_fin", ""),
                str(r.get("pasajeros") or 0),
                etiqueta.get(r.get("estado", ""), r.get("estado", "")),
                gs(r.get("monto")),
            ])
        t = Table(data, repeatRows=1,
                  colWidths=[21*mm, 26*mm, 68*mm, 17*mm, 16*mm, 16*mm,
                             14*mm, 24*mm, 26*mm])
        estilo = [
            ("BACKGROUND", (0, 0), (-1, 0), AZUL),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("FONTSIZE", (0, 1), (-1, -1), 7.5),
            ("ALIGN", (3, 0), (-1, -1), "CENTER"),
            ("ALIGN", (8, 0), (8, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SUAVE]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        for i, r in enumerate(filas, start=1):
            if r.get("estado") == "suspendido":
                estilo.append(("TEXTCOLOR", (7, i), (7, i), ROJO))
                estilo.append(("FONTNAME", (7, i), (7, i), "Helvetica-Bold"))
        t.setStyle(TableStyle(estilo))
        elems.append(t)

        # ── Suspendidos, con el motivo ──
        susp = [r for r in filas if r.get("estado") == "suspendido" and r.get("observacion")]
        if susp:
            elems.append(Paragraph("Servicios suspendidos — motivos", st_secc))
            for r in susp:
                elems.append(Paragraph(
                    f"- {r.get('fecha_servicio','')} · {r.get('cliente','')} "
                    f"({r.get('tramo','')}): {r.get('observacion','')}", st_susp))

        # ── Firma ──
        elems.append(Spacer(1, 14))
        firma = [["", ""],
                 ["Firma del chofer", "Firma de Recursos Humanos"]]
        tf = Table(firma, colWidths=[130*mm, 130*mm], rowHeights=[16*mm, 6*mm])
        tf.setStyle(TableStyle([
            ("LINEABOVE", (0, 1), (0, 1), 0.6, colors.HexColor("#999999")),
            ("LINEABOVE", (1, 1), (1, 1), 0.6, colors.HexColor("#999999")),
            ("ALIGN", (0, 1), (-1, 1), "CENTER"),
            ("FONTSIZE", (0, 1), (-1, 1), 8),
            ("TEXTCOLOR", (0, 1), (-1, 1), GRIS),
            ("TOPPADDING", (0, 1), (-1, 1), 3),
        ]))
        elems.append(tf)

        if ci < len(choferes) - 1:
            elems.append(PageBreak())

    # ── Hoja final: total de todos, para el cierre de RRHH ──
    if len(choferes) > 1:
        elems.append(PageBreak())
        elems.append(Paragraph("Resumen general de la liquidación", st_tit))
        if periodo:
            elems.append(Paragraph(periodo, st_per))
        elems.append(Spacer(1, 6))
        gdata = [["Chofer", "Servicios", "Tramos Gs.", "Plus Gs.", "Total Gs.", "Firma"]]
        for nom in choferes:
            l = liq_idx.get(nom, {})
            gdata.append([nom, str(l.get("servicios", 0)), gs(l.get("monto_tramos", 0)),
                          gs(l.get("plus", 0)) if l.get("tiene_plus") else "—",
                          gs(l.get("total", 0)), ""])
        gdata.append(["TOTAL A LIQUIDAR", "", "", "", gs(total_general), ""])
        gt = Table(gdata, repeatRows=1,
                   colWidths=[72*mm, 26*mm, 34*mm, 30*mm, 36*mm, 60*mm])
        gt.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), AZUL),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 0), (4, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, SUAVE]),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EAF1F8")),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("TOPPADDING", (0, 0), (-1, -1), 7),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ]))
        elems.append(gt)

    doc.build(elems)
    return buf.getvalue()
