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
from hora_local import ahora, ahora_iso, hoy

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
                     ("tarifas_editadas", f"{admin} {hoy()}"))
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
        "TURNO A RUTA 1 NORMAL 6:00/6:30",
        "TURNO A SINALCO NORMAL 6:00/6:30",
        "TURNO B RUTA 1 NORMAL 14:00/14:30",
        "TURNO B SINALCO NORMAL 14:00/14:30",
        "TURNO C RUTA 1 NORMAL 22:00/22:30",
        "TURNO C SINALCO NORMAL 22:00/22:30",
        "VARIABLE VILLA OLIVA",
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
        "HOTEL 1 / 8:00/17:00",
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
                         # Momento exacto en que se cargó, en hora local: sirve
                         # para saber si se reportó el día del servicio o mucho
                         # después
                         ("cargado_el", "TEXT"),
                         # Variables cargados antes de exigir justificación:
                         # no se marcan como pendientes, ya no se pueden completar
                         ("justif_exenta", "INTEGER DEFAULT 0"),
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

    # Los servicios variables cargados antes de que la justificación fuera
    # obligatoria no se pueden completar hacia atrás: se dan por normales para
    # que no queden marcados en rojo para siempre. Los nuevos sí deben justificar.
    try:
        conn.execute("""
            UPDATE rendiciones_corp SET justif_exenta=1
            WHERE COALESCE(justif_exenta,0)=0
              AND UPPER(TRIM(tramo)) LIKE 'VARIABLE%'
              AND (observacion IS NULL OR TRIM(observacion)='')
        """)
        conn.commit()
    except Exception:
        conn.rollback()

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


def corregir_horarios_utc():
    """Pasa a hora de Paraguay los horarios que quedaron guardados en UTC.

    Hasta ahora el sistema usaba la hora del servidor de Render, que corre en
    UTC: un pago hecho a las 9:39 quedaba registrado como 12:39. Esto corrige
    de una vez lo ya guardado. Se ejecuta una sola vez y deja constancia, para
    no restar horas dos veces si el servicio se reinicia.
    """
    from hora_local import a_local
    conn = get_connection()

    # ¿Ya se corrigió antes?
    try:
        hecho = conn.execute("SELECT valor FROM config_corp WHERE clave=?",
                             ("horarios_corregidos",)).fetchone()
        if hecho:
            conn.close()
            return {"ya_estaba": True, "corregidos": 0}
    except Exception:
        conn.close()
        return {"ya_estaba": False, "corregidos": 0, "error": "sin tabla de configuración"}

    corregidos = 0
    # Campos con fecha y hora que hay que pasar a hora local
    objetivos = [
        ("rendiciones_corp", "fecha_liquidacion"),
        ("rendiciones_corp", "fecha_edicion"),
    ]
    for tabla, campo in objetivos:
        try:
            filas = conn.execute(
                f"SELECT id, {campo} AS v FROM {tabla} WHERE {campo} IS NOT NULL"
            ).fetchall()
        except Exception:
            continue
        for f in filas:
            # Solo los que tienen hora (los que son solo fecha no se tocan)
            if "T" not in str(f["v"]):
                continue
            nuevo = a_local(f["v"])
            if nuevo != f["v"]:
                try:
                    conn.execute(f"UPDATE {tabla} SET {campo}=? WHERE id=?",
                                 (nuevo, f["id"]))
                    corregidos += 1
                except Exception:
                    pass

    try:
        conn.execute("INSERT INTO config_corp (clave, valor) VALUES (?,?)",
                     ("horarios_corregidos", f"{corregidos} registros"))
        conn.commit()
    except Exception:
        conn.rollback()
    conn.close()
    return {"ya_estaba": False, "corregidos": corregidos}


def init_corporativos_module(app):
    inicializar_corporativos()
    # Registro del plus pagado, para que el histórico no se recalcule
    try:
        inicializar_pagos_plus()
    except Exception:
        pass
    # Pasa a hora de Paraguay lo que quedó guardado en hora del servidor
    try:
        corregir_horarios_utc()
    except Exception:
        pass


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


# ════════════════════════════════════════════════════════════════════════════
# CUÁNTOS SERVICIOS PUEDE HACER UN CHOFER EN UN DÍA
# ════════════════════════════════════════════════════════════════════════════
# Nadie puede estar en dos lugares a la vez: si arrancó un tramo a las 7 de la
# mañana no puede estar haciendo otro a las 9. La regla de la empresa es como
# máximo dos servicios en el día, y nunca los dos en la misma franja.

# Ya no bloquea la carga: se usa para marcar en "Revisar cargas" los días con
# una cantidad de servicios que llama la atención.
MAX_SERVICIOS_DIA = 2
# Ningún tanque de la flota pasa de esto. Un número más alto es un error de
# tipeo (poner 2000 en vez de 200), y si entra arruina el consumo del coche.
MAX_LITROS_POR_CARGA = 600
# Un servicio se reporta el día que se hizo o, como mucho, al día siguiente.
# Más atrás que eso ya no es un olvido: es alguien completando la planilla de
# memoria, y esos números no sirven para liquidar ni para controlar nada.
# Tampoco bloquea: sirve para detectar las cargas hechas mucho después.
DIAS_ATRAS_PERMITIDOS = 1
# Un tramo que dura más de esto ocupa el día entero (los de 7 a 17, por ejemplo)
HORAS_JORNADA_COMPLETA = 5


def fecha_reportable(fecha_servicio):
    """Si esa fecha se puede reportar.

    Se admite cualquier fecha pasada: a veces se reporta con demora y trabarlo
    solo hace que el servicio no quede registrado. Lo único que se rechaza es
    una fecha futura, que es imposible por definición.

    Las cargas con mucha demora no se bloquean pero sí se registran: quedan
    marcadas en "Revisar cargas" para que el encargado las mire.
    """
    import datetime as _dt
    try:
        f = _dt.date.fromisoformat(fecha_servicio)
    except Exception:
        return False, "La fecha no es válida."
    if f > _dt.date.fromisoformat(hoy()):
        return False, ("Esa fecha es futura. Solo se puede reportar un servicio "
                       "que ya hiciste.")
    return True, ""


def _horas_del_tramo(tramo):
    """Las horas que figuran en el nombre del tramo: 'LIMPIO 6:00/6:20' son las
    6:00 y las 6:20; 'ADM RUTA 1 - 7:00 A 17:00' son las 7 y las 17."""
    import re
    horas = []
    for h, m in re.findall(r"(\d{1,2})[:.](\d{2})", tramo or ""):
        try:
            hh, mm = int(h), int(m)
            if 0 <= hh <= 23 and 0 <= mm <= 59:
                horas.append(hh + mm / 60)
        except Exception:
            pass
    return horas


def franja_del_servicio(tramo, hora_inicio=""):
    """En qué momento del día cae el servicio.

    Devuelve 'completa' si ocupa la jornada entera, 'manana' si arranca antes
    del mediodía, 'tarde' si arranca después, o None si el tramo no dice
    horarios y el chofer tampoco los cargó.
    """
    horas = _horas_del_tramo(tramo)

    if len(horas) >= 2:
        inicio, fin = horas[0], horas[1]
        dur = (fin - inicio) if fin > inicio else (24 - inicio + fin)
        if dur >= HORAS_JORNADA_COMPLETA:
            return "completa"
        return "manana" if inicio < 12 else "tarde"

    if len(horas) == 1:
        return "manana" if horas[0] < 12 else "tarde"

    # El tramo no dice hora: se usa la que cargó el chofer, si la puso
    hs = _horas_del_tramo(hora_inicio or "")
    if hs:
        return "manana" if hs[0] < 12 else "tarde"
    return None


NOMBRE_FRANJA = {"manana": "la mañana", "tarde": "la tarde",
                 "completa": "todo el día"}


def servicios_del_dia(chofer_usuario, fecha, excluir_id=None):
    """Lo que ese chofer ya reportó ese día, sin contar los suspendidos —
    un servicio que no se prestó no le ocupa el tiempo a nadie."""
    q = """SELECT id, cliente, tramo, hora_inicio, estado
           FROM rendiciones_corp
           WHERE chofer_usuario=? AND fecha_servicio=? AND estado <> 'suspendido'"""
    params = [chofer_usuario, fecha]
    if excluir_id:
        q += " AND id <> ?"
        params.append(excluir_id)
    conn = get_connection()
    rows = [dict(r) for r in conn.execute(q, params).fetchall()]
    conn.close()
    for r in rows:
        r["franja"] = franja_del_servicio(r["tramo"], r.get("hora_inicio", ""))
    return rows


def rango_horario(tramo, hora_inicio="", hora_fin=""):
    """El horario que ocupa el servicio, en horas decimales.

    Se saca del nombre del tramo, que es el dato confiable: 'ADM RUTA 1 - 7:00
    A 17:00' ocupa de 7 a 17. Si el tramo no dice horarios, se usa lo que cargó
    el chofer. Devuelve None cuando no hay forma de saberlo.
    """
    horas = _horas_del_tramo(tramo)
    if len(horas) >= 2:
        ini, fin = horas[0], horas[1]
    elif len(horas) == 1:
        # Un solo horario: es la salida. Se le da un margen de media hora.
        ini, fin = horas[0], horas[0] + 0.5
    else:
        hi = _horas_del_tramo(hora_inicio or "")
        hf = _horas_del_tramo(hora_fin or "")
        if not hi:
            return None
        ini = hi[0]
        fin = hf[0] if hf else hi[0] + 0.5
    if fin <= ini:
        fin += 24                     # cruzó la medianoche
    return (ini, fin)


def _se_pisan(a, b):
    """Si dos rangos horarios se superponen, contemplando los que cruzan la
    medianoche."""
    if not a or not b:
        return False
    for desp in (0, 24, -24):
        ini_b, fin_b = b[0] + desp, b[1] + desp
        if a[0] < fin_b and ini_b < a[1]:
            return True
    return False


def puede_cargar_servicio(chofer_usuario, fecha, tramo, hora_inicio="",
                          estado="completado", excluir_id=None):
    """Si este servicio se pisa con otro que el chofer ya cargó ese día.

    YA NO BLOQUEA la carga: la decisión fue que el sistema no trabe al chofer,
    porque un reporte que no entra es peor que uno con un horario raro. Se sigue
    usando para avisarle en pantalla y para marcar el cruce en "Revisar cargas",
    donde el encargado lo ve y decide.
    """
    if estado == "suspendido" or _es_variable(tramo):
        return True, ""

    ya = servicios_del_dia(chofer_usuario, fecha, excluir_id)
    if not ya:
        return True, ""

    nuevo = rango_horario(tramo, hora_inicio)
    if not nuevo:
        return True, ""

    def _hhmm(h):
        h = h % 24
        return f"{int(h):02d}:{int(round((h - int(h)) * 60)):02d}"

    for s in ya:
        if _es_variable(s["tramo"]):
            continue
        otro = rango_horario(s["tramo"], s.get("hora_inicio", ""))
        if _se_pisan(nuevo, otro):
            return False, (f"Ese horario se pisa con otro servicio que ya "
                           f"cargaste: {s['cliente']} · {s['tramo']} "
                           f"({_hhmm(otro[0])} a {_hhmm(otro[1])}).")
    return True, ""


def registrar_rendicion(datos, limitar_fecha=False):
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
    # Los servicios fuera de tramo fijo hay que poder justificarlos después,
    # así que el chofer tiene que decir qué servicio hizo.
    if _es_variable(datos.get("tramo")) and not str(datos.get("observacion", "")).strip():
        return False, ("Es un servicio variable: contá qué servicio hiciste "
                       "(a dónde fuiste, para qué).")

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
    # El chofer solo reporta lo de hoy o lo de ayer. El admin puede cargar
    # cualquier fecha, porque a veces hay que regularizar algo viejo a mano.
    if limitar_fecha:
        ok_fecha, msg_fecha = fecha_reportable(datos["fecha_servicio"])
        if not ok_fecha:
            return False, msg_fecha

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
             pasajeros, estado, observacion, monto, cargado_el)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (datos.get("chofer_usuario", ""), datos.get("chofer_nombre", ""),
             datos["cliente"].strip(), datos["tramo"].strip(),
             datos["fecha_servicio"].strip(), str(datos["bus_interno"]).strip(),
             datos.get("hora_inicio", ""), datos.get("hora_fin", ""),
             num(datos.get("km_inicial")), num(datos.get("km_final")),
             int(num(datos.get("pasajeros"))), estado,
             datos.get("observacion", "").strip(), monto, ahora_iso()))
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



def a_numero(v, decimales=True):
    """Convierte a número lo que escribió el usuario, sin romper los decimales.

    Acá el punto puede ser separador de miles (1.500.000 guaraníes) o decimal
    (201.35 litros). La regla: si hay coma, la coma es el decimal y los puntos
    son miles. Si solo hay puntos y el último grupo tiene una o dos cifras, ese
    punto es decimal — así "201.35" son doscientos un litros y medio, no veinte
    mil, que es lo que pasaba antes.
    """
    s = str(v or "").strip().replace(" ", "")
    if not s:
        return 0.0
    try:
        if "," in s:
            return float(s.replace(".", "").replace(",", "."))
        if "." in s:
            entero, _, ultimo = s.rpartition(".")
            if decimales and len(ultimo) in (1, 2) and "." not in entero:
                return float(s)                    # 201.35 → decimal
            return float(s.replace(".", ""))       # 1.500.000 → miles
        return float(s)
    except Exception:
        return 0.0


def config_plus():
    """Cómo está configurado hoy el plus semanal.

    Hay un monto general y, opcionalmente, un monto propio para cada chofer
    que lo cobra: no todos tienen por qué cobrar lo mismo. Si un chofer no
    tiene monto propio, cobra el general.

    Vive en la base, no en el código, porque cambia: la empresa suma o saca
    choferes y mueve montos. PLUS_SEMANAL y CHOFERES_CON_PLUS son solo el punto
    de partida la primera vez que arranca el sistema.
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
    try:
        montos = json.loads(rows.get("plus_montos") or "{}")
        if not isinstance(montos, dict):
            montos = {}
    except Exception:
        montos = {}

    # Normalizar a mayúsculas para comparar sin errores de tipeo
    montos = {k.strip().upper(): round(float(v)) for k, v in montos.items()
              if str(v).strip() not in ("", "None")}
    return {"monto": round(monto), "choferes": nombres, "montos": montos}


def monto_plus_de(nombre, cfg=None):
    """Cuánto cobra de plus ese chofer por semana: su monto propio si tiene
    uno, el general si no, o cero si no cobra plus."""
    if cfg is None:
        cfg = config_plus()
    clave = (nombre or "").strip().upper()
    if clave not in [c.strip().upper() for c in cfg["choferes"]]:
        return 0
    return cfg["montos"].get(clave, cfg["monto"])


def guardar_config_plus(monto, nombres, admin="", montos=None):
    """Guarda el monto general, quién cobra plus y los montos propios.

    Los cambios valen de acá en adelante: lo que ya se pagó queda registrado
    con el monto de ese momento y no se recalcula.
    """
    import json
    try:
        monto = float(str(monto).replace(".", "").replace(",", "."))
    except Exception:
        return False, "El monto no es un número."
    if monto < 0:
        return False, "El monto no puede ser negativo."

    nombres = sorted({(n or "").strip().upper() for n in (nombres or []) if (n or "").strip()})

    limpios = {}
    for k, v in (montos or {}).items():
        clave = (k or "").strip().upper()
        if not clave or clave not in nombres:
            continue                # solo se guarda monto de quien cobra plus
        txt = str(v if v is not None else "").strip()
        if not txt:
            continue                # vacío = usa el general
        try:
            val = float(txt.replace(".", "").replace(",", "."))
        except Exception:
            return False, f"El monto de {clave} no es un número."
        if val < 0:
            return False, f"El monto de {clave} no puede ser negativo."
        limpios[clave] = round(val)

    conn = get_connection()
    for clave, valor in (("plus_monto", str(round(monto))),
                         ("plus_choferes", json.dumps(nombres, ensure_ascii=False)),
                         ("plus_montos", json.dumps(limpios, ensure_ascii=False))):
        existe = conn.execute("SELECT 1 FROM config_corp WHERE clave=?", (clave,)).fetchone()
        if existe:
            conn.execute("UPDATE config_corp SET valor=? WHERE clave=?", (valor, clave))
        else:
            conn.execute("INSERT INTO config_corp (clave, valor) VALUES (?,?)", (clave, valor))
    conn.commit()
    conn.close()

    txt = f"{round(monto):,}".replace(",", ".")
    extra = f", {len(limpios)} con monto propio" if limpios else ""
    return True, f"Plus de Gs. {txt} para {len(nombres)} chofer(es){extra}."


def _tiene_plus(nombre, lista=None):
    """Si a ese chofer le corresponde el plus semanal."""
    if lista is None:
        lista = config_plus()["choferes"]
    return (nombre or "").strip().upper() in [c.strip().upper() for c in lista]


# ════════════════════════════════════════════════════════════════════════════
# REGISTRO DEL PLUS PAGADO
# ════════════════════════════════════════════════════════════════════════════
# El plus se guarda en el momento de liquidar, con el monto de ese día. Antes
# el histórico lo recalculaba con la configuración actual: si a un chofer se le
# sacaba el plus, sus pagos viejos aparecían sin plus, y si se subía el monto,
# los pagos viejos mostraban el monto nuevo. Plata ya pagada no puede cambiar.

def inicializar_pagos_plus():
    conn = get_connection()
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS pagos_plus (
            id              {PK},
            chofer_usuario  TEXT NOT NULL,
            chofer_nombre   TEXT NOT NULL,
            anio            INTEGER NOT NULL,
            semana_iso      INTEGER NOT NULL,
            monto           REAL NOT NULL,
            fecha_pago      TEXT,
            pagado_por      TEXT DEFAULT ''
        )
    """)
    conn.commit()
    conn.close()


def registrar_plus_pagado(conn, chofer_usuario, chofer_nombre, anio, semana, monto, admin, fecha):
    conn.execute("""DELETE FROM pagos_plus
                    WHERE chofer_usuario=? AND anio=? AND semana_iso=?""",
                 (chofer_usuario, int(anio), int(semana)))
    if monto:
        conn.execute("""INSERT INTO pagos_plus
            (chofer_usuario, chofer_nombre, anio, semana_iso, monto, fecha_pago, pagado_por)
            VALUES (?,?,?,?,?,?,?)""",
            (chofer_usuario, chofer_nombre, int(anio), int(semana), monto, fecha, admin))


def plus_pagado(chofer_usuario, anio, semana):
    """Lo que se pagó de plus esa semana, si quedó registrado. None si es una
    liquidación anterior a este registro."""
    conn = get_connection()
    try:
        row = conn.execute("""SELECT monto FROM pagos_plus
                              WHERE chofer_usuario=? AND anio=? AND semana_iso=?""",
                           (chofer_usuario, int(anio), int(semana))).fetchone()
    except Exception:
        row = None
    conn.close()
    return float(row["monto"]) if row else None


# ════════════════════════════════════════════════════════════════════════════
# CONTROL POR EMPRESA — cobertura, costo y justificación de variables
# ════════════════════════════════════════════════════════════════════════════
# Hasta acá el módulo miraba la plata desde el chofer (cuánto se le paga).
# Esto lo mira desde el cliente: se cubrió todo lo que contrató, cuánto cuesta
# atenderlo, y por qué hubo servicios fuera de tramo.

# Clientes que solo operan de lunes a viernes. El resto trabaja todos los días.
CLIENTES_SOLO_HABILES = ["ADM", "BALL", "LASCA"]


def _es_variable(tramo):
    """Los tramos comodín (VARIABLE y sus derivados) no forman parte de la
    grilla fija: son servicios sueltos, así que no se esperan ni se controlan."""
    return (tramo or "").strip().upper().startswith(TRAMO_VARIABLE)


def tramos_fijos(cliente):
    """Los tramos de la grilla de un cliente — los que deberían cubrirse."""
    return [t for t in CLIENTES_TRAMOS.get(cliente, []) if not _es_variable(t)]


def dias_operativos(cliente, desde, hasta):
    """Los días en que ese cliente espera servicio dentro del rango."""
    import datetime as _dt
    try:
        d0 = _dt.date.fromisoformat(desde)
        d1 = _dt.date.fromisoformat(hasta)
    except Exception:
        return []
    solo_habiles = cliente in CLIENTES_SOLO_HABILES
    dias, d = [], d0
    while d <= d1:
        # weekday(): 0=lunes ... 4=viernes, 5=sábado, 6=domingo
        if not solo_habiles or d.weekday() < 5:
            dias.append(d.isoformat())
        d += _dt.timedelta(days=1)
    return dias


def _periodo_de(fecha, agrupacion):
    """Etiqueta del período al que pertenece una fecha, según la agrupación."""
    import datetime as _dt
    if agrupacion == "dia":
        return fecha
    if agrupacion == "total":
        return "Total del período"
    try:
        d = _dt.date.fromisoformat(fecha)
    except Exception:
        return fecha
    if agrupacion == "semana":
        iso = d.isocalendar()
        lunes = _dt.date.fromisocalendar(iso[0], iso[1], 1)
        return f"Semana {iso[1]} ({lunes.isoformat()})"
    if agrupacion == "mes":
        return d.strftime("%Y-%m")
    return "Total del período"


def primer_servicio(cliente=None):
    """La fecha del servicio más antiguo cargado. Antes de esa fecha no había
    sistema, así que no tiene sentido contar tramos como faltantes: se estaría
    midiendo contra días en los que nadie podía reportar nada."""
    q = "SELECT MIN(fecha_servicio) AS f FROM rendiciones_corp WHERE fecha_servicio<>''"
    params = []
    if cliente:
        q += " AND cliente=?"
        params.append(cliente)
    conn = get_connection()
    try:
        row = conn.execute(q, params).fetchone()
        f = row["f"] if row else None
    except Exception:
        f = None
    conn.close()
    return f


def control_cobertura(cliente, desde, hasta, agrupacion="total", modo="reales"):
    """Qué tramos se esperaban y cuáles se reportaron realmente.

    El problema de comparar contra el catálogo entero es que ahí están TODOS
    los tramos posibles del cliente, y muchos no corren todos los días (los de
    apoyo, los administrativos en fin de semana). Eso hacía que el sistema
    esperara miles de tramos y la cobertura no sirviera para nada.

    Por eso el modo por defecto es "reales": el sistema deduce del historial
    qué tramos operan de verdad y con qué frecuencia. Un tramo que nunca se
    reportó no se cuenta; uno que solo aparece de lunes a viernes se espera
    solo esos días. El modo "catalogo" mantiene la comparación contra la lista
    completa, por si se quiere ver el máximo teórico.

    Un tramo está CUBIERTO si alguien lo marcó completado, o si entre dos
    choferes se cubrieron el entrante y el saliente. Con una sola mitad queda
    PARCIAL, y sin nada, FALTANTE.
    """
    import datetime as _dt
    fijos = tramos_fijos(cliente)

    # El rango arranca, como muy temprano, el día del primer servicio cargado.
    # Si se pide "últimos 3 meses" pero el sistema tiene un mes de datos, contar
    # los dos meses anteriores como no cubiertos sería medir contra la nada.
    primero = primer_servicio(cliente)
    desde_real, ajustado = desde, False
    if primero and desde and primero > desde:
        desde_real, ajustado = primero, True

    dias = dias_operativos(cliente, desde_real, hasta)
    vacio = {"cliente": cliente, "esperados": 0, "cubiertos": 0, "parciales": 0,
             "faltantes": 0, "suspendidos": 0, "cobertura": 0, "dias": 0,
             "tramos_por_dia": 0, "periodos": [], "detalle_faltantes": [],
             "tramos_activos": 0, "tramos_catalogo": len(fijos),
             "tramos_sin_actividad": [], "solo_habiles": [],
             "desde_real": desde_real, "hasta_real": hasta,
             "rango_ajustado": ajustado, "primer_servicio": primero}
    if not fijos or not dias:
        return vacio

    conn = get_connection()
    rows = [dict(r) for r in conn.execute("""
        SELECT fecha_servicio, tramo, estado, chofer_nombre
        FROM rendiciones_corp
        WHERE cliente=? AND fecha_servicio>=? AND fecha_servicio<=?
    """, (cliente, desde_real, hasta)).fetchall()]
    conn.close()

    reportado = {}
    for r in rows:
        if _es_variable(r["tramo"]):
            continue
        reportado.setdefault((r["fecha_servicio"], r["tramo"]), []).append(r)

    # ── Qué tramos operan de verdad, y qué días ──
    # Se mira en qué días de la semana apareció cada tramo: si nunca apareció
    # un fin de semana, se asume que solo corre de lunes a viernes.
    actividad = {}
    for (fecha, tramo), regs in reportado.items():
        a = actividad.setdefault(tramo, {"veces": 0, "findes": 0})
        a["veces"] += 1
        try:
            if _dt.date.fromisoformat(fecha).weekday() >= 5:
                a["findes"] += 1
        except Exception:
            pass

    if modo == "catalogo":
        controlados = {t: "todos" for t in fijos}
    else:
        controlados = {}
        for t in fijos:
            a = actividad.get(t)
            if not a:
                continue                      # nunca se reportó: no se controla
            controlados[t] = "habiles" if a["findes"] == 0 else "todos"

    sin_actividad = [t for t in fijos if t not in controlados]

    def corre(tramo, dia):
        if controlados.get(tramo) == "habiles":
            try:
                return _dt.date.fromisoformat(dia).weekday() < 5
            except Exception:
                return True
        return True

    periodos, detalle = {}, []
    tot = {"esperados": 0, "cubiertos": 0, "parciales": 0,
           "faltantes": 0, "suspendidos": 0}

    for dia in dias:
        per = _periodo_de(dia, agrupacion)
        p = periodos.setdefault(per, {
            "periodo": per, "dias": 0, "esperados": 0, "cubiertos": 0,
            "parciales": 0, "faltantes": 0, "suspendidos": 0})
        p["dias"] += 1
        for tramo in controlados:
            if not corre(tramo, dia):
                continue
            regs = reportado.get((dia, tramo), [])
            estados = {x["estado"] for x in regs}
            p["esperados"] += 1; tot["esperados"] += 1
            if "completado" in estados or ("entrante" in estados and "saliente" in estados):
                p["cubiertos"] += 1; tot["cubiertos"] += 1
            elif "entrante" in estados or "saliente" in estados:
                p["parciales"] += 1; tot["parciales"] += 1
                falta = "saliente" if "entrante" in estados else "entrante"
                detalle.append({"fecha": dia, "tramo": tramo, "situacion": "parcial",
                                "detalle": f"falta el {falta}",
                                "quien": ", ".join(x["chofer_nombre"] for x in regs)})
            elif "suspendido" in estados:
                p["suspendidos"] += 1; tot["suspendidos"] += 1
                detalle.append({"fecha": dia, "tramo": tramo, "situacion": "suspendido",
                                "detalle": "servicio suspendido",
                                "quien": ", ".join(x["chofer_nombre"] for x in regs)})
            else:
                p["faltantes"] += 1; tot["faltantes"] += 1
                detalle.append({"fecha": dia, "tramo": tramo, "situacion": "faltante",
                                "detalle": "nadie lo reportó", "quien": "—"})

    lista = sorted(periodos.values(), key=lambda x: x["periodo"])
    for p in lista:
        p["cobertura"] = round(p["cubiertos"] / p["esperados"] * 100, 1) if p["esperados"] else 0

    return {
        "cliente": cliente, "dias": len(dias),
        "desde_real": desde_real, "hasta_real": hasta,
        "rango_ajustado": ajustado, "primer_servicio": primero,
        "tramos_por_dia": len(controlados),
        "tramos_activos": len(controlados),
        "tramos_catalogo": len(fijos),
        "tramos_sin_actividad": sorted(sin_actividad),
        "solo_habiles": sorted([t for t, v in controlados.items() if v == "habiles"]),
        "esperados": tot["esperados"], "cubiertos": tot["cubiertos"],
        "parciales": tot["parciales"], "faltantes": tot["faltantes"],
        "suspendidos": tot["suspendidos"],
        "cobertura": round(tot["cubiertos"] / tot["esperados"] * 100, 1) if tot["esperados"] else 0,
        "periodos": lista,
        "detalle_faltantes": sorted(detalle, key=lambda x: (x["fecha"], x["tramo"])),
    }


def costo_por_empresa(desde=None, hasta=None, agrupacion="total"):
    """Cuánto cuesta atender a cada cliente. La agrupación puede ser por día,
    semana, mes, o el total del período."""
    import datetime as _dt
    q = """SELECT cliente, fecha_servicio, estado, monto, tramo
           FROM rendiciones_corp WHERE 1=1"""
    params = []
    if desde:
        q += " AND fecha_servicio>=?"; params.append(desde)
    if hasta:
        q += " AND fecha_servicio<=?"; params.append(hasta)
    conn = get_connection()
    rows = [dict(r) for r in conn.execute(q, params).fetchall()]
    conn.close()

    datos = {}
    for r in rows:
        cli = r["cliente"]
        per = _periodo_de(r["fecha_servicio"], agrupacion)
        d = datos.setdefault((cli, per), {
            "cliente": cli, "periodo": per, "servicios": 0,
            "costo": 0, "variables": 0, "suspendidos": 0,
        })
        d["servicios"] += 1
        d["costo"] += float(r["monto"] or 0)
        if _es_variable(r["tramo"]):
            d["variables"] += 1
        if r["estado"] == "suspendido":
            d["suspendidos"] += 1

    lista = sorted(datos.values(), key=lambda x: (x["cliente"], x["periodo"]))
    for d in lista:
        d["costo"] = round(d["costo"])
    # Totales por cliente, para el resumen de arriba
    por_cliente = {}
    for d in lista:
        c = por_cliente.setdefault(d["cliente"], {
            "cliente": d["cliente"], "servicios": 0, "costo": 0, "variables": 0})
        c["servicios"] += d["servicios"]
        c["costo"] += d["costo"]
        c["variables"] += d["variables"]
    return {"filas": lista,
            "por_cliente": sorted(por_cliente.values(), key=lambda x: x["cliente"]),
            "costo_total": sum(d["costo"] for d in lista)}


def variables_del_periodo(desde=None, hasta=None, cliente=None):
    """Los servicios fuera de tramo fijo, con la explicación del chofer.
    Sirve para justificar por qué se pagaron."""
    q = """SELECT id, chofer_nombre, cliente, tramo, fecha_servicio, bus_interno,
                  hora_inicio, hora_fin, pasajeros, monto, observacion, estado,
                  COALESCE(justif_exenta,0) AS justif_exenta
           FROM rendiciones_corp WHERE 1=1"""
    params = []
    if desde:
        q += " AND fecha_servicio>=?"; params.append(desde)
    if hasta:
        q += " AND fecha_servicio<=?"; params.append(hasta)
    if cliente:
        q += " AND cliente=?"; params.append(cliente)
    q += " ORDER BY fecha_servicio DESC, id DESC"
    conn = get_connection()
    rows = [dict(r) for r in conn.execute(q, params).fetchall()]
    conn.close()

    variables = [r for r in rows if _es_variable(r["tramo"])]
    # Los eximidos son los que se cargaron antes de que la justificación fuera
    # obligatoria: no cuentan como pendientes.
    sin_justificar = [r for r in variables
                      if not (r.get("observacion") or "").strip()
                      and not r.get("justif_exenta")]
    return {"variables": variables,
            "cantidad": len(variables),
            "sin_justificar": len(sin_justificar),
            "monto_total": round(sum(float(r["monto"] or 0) for r in variables))}


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
        plus = monto_plus_de(nom, cfg_plus) * semanas
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
    nombre_chofer = ""
    cfg_semana = config_plus()
    conn = get_connection()
    u = conn.execute("SELECT nombre FROM usuarios WHERE usuario=?",
                     (chofer_usuario,)).fetchone()
    conn.close()
    if u:
        nombre_chofer = u["nombre"]
        tiene_plus = _tiene_plus(nombre_chofer, cfg_semana["choferes"])

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
        plus = monto_plus_de(nombre_chofer, cfg_semana) if g["trabajo"] else 0
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


def historial_liquidaciones(chofer_usuario=None, desde=None, hasta=None,
                            modo="servicio"):
    """Todo lo que ya se pagó: cada liquidación con su fecha, el período que
    cubrió, cuánto fue y quién la autorizó.

    El filtro de fechas tiene dos modos, porque son dos preguntas distintas:
      - "servicio" (por defecto): de qué fechas son los servicios pagados.
        Es lo natural — se busca "la liquidación de la semana del 27 de julio"
        aunque se haya cargado semanas después.
      - "pago": cuándo se apretó el botón de liquidar. Sirve para cerrar caja
        ("todo lo que pagamos en agosto").
    """
    campo = "fecha_liquidacion" if modo == "pago" else "fecha_servicio"
    q = """SELECT chofer_usuario, chofer_nombre, fecha_servicio, estado, monto,
                  fecha_liquidacion, liquidado_por, cliente, tramo
           FROM rendiciones_corp
           WHERE COALESCE(liquidado,0)=1 AND fecha_liquidacion IS NOT NULL"""
    params = []
    if chofer_usuario:
        q += " AND chofer_usuario=?"; params.append(chofer_usuario)
    if desde:
        q += f" AND {campo}>=?"; params.append(desde)
    if hasta:
        # La fecha de liquidación lleva hora, la del servicio no
        q += f" AND {campo}<=?"
        params.append(hasta + "T23:59:59" if campo == "fecha_liquidacion" else hasta)
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
        # Lo pagado de verdad, semana por semana. Solo si la liquidación es
        # anterior al registro se estima con la configuración actual.
        plus = 0
        for (an, sem) in p["semanas"]:
            pagado = plus_pagado(p["chofer_usuario"], an, sem)
            plus += pagado if pagado is not None else monto_plus_de(p["chofer_nombre"], cfg)
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
    if modo == "pago":
        salida.sort(key=lambda x: x["fecha_pago"], reverse=True)
    else:
        salida.sort(key=lambda x: x["periodo_hasta"], reverse=True)
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
    ahora = ahora_iso()
    conn = get_connection()
    n = conn.execute("""
        SELECT COUNT(*) AS c FROM rendiciones_corp
        WHERE chofer_usuario=? AND COALESCE(liquidado,0)=0
          AND fecha_servicio>=? AND fecha_servicio<=?
    """, (chofer_usuario, lunes.isoformat(), domingo.isoformat())).fetchone()["c"]
    if n == 0:
        conn.close()
        return False, "No había rendiciones pendientes en esa semana.", 0
    # El plus se congela con el monto de hoy: si mañana cambia la
    # configuración, lo que ya se pagó no se mueve.
    fila = conn.execute("""SELECT chofer_nombre FROM rendiciones_corp
                           WHERE chofer_usuario=? AND fecha_servicio>=? AND fecha_servicio<=?
                             AND estado <> 'suspendido' LIMIT 1""",
                        (chofer_usuario, lunes.isoformat(), domingo.isoformat())).fetchone()
    nombre = fila["chofer_nombre"] if fila else ""
    monto_plus = monto_plus_de(nombre) if fila else 0

    conn.execute("""
        UPDATE rendiciones_corp
        SET liquidado=1, fecha_liquidacion=?, liquidado_por=?
        WHERE chofer_usuario=? AND COALESCE(liquidado,0)=0
          AND fecha_servicio>=? AND fecha_servicio<=?
    """, (ahora, admin, chofer_usuario, lunes.isoformat(), domingo.isoformat()))
    registrar_plus_pagado(conn, chofer_usuario, nombre, anio, semana_iso,
                          monto_plus, admin, ahora)
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
    # El plus de esa semana deja de estar pagado: si se vuelve a liquidar se
    # registra de nuevo con el monto que corresponda en ese momento.
    try:
        conn.execute("""DELETE FROM pagos_plus
                        WHERE chofer_usuario=? AND anio=? AND semana_iso=?""",
                     (chofer_usuario, int(anio), int(semana_iso)))
    except Exception:
        pass
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
        (monto, admin, ahora_iso(), int(rid)))
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


def rendiciones_sospechosas(desde=None, hasta=None):
    """Servicios que no cierran y conviene mirar antes de pagarlos.

    Revisa TODA la base, no el período que esté filtrado en pantalla: los
    servicios con fecha futura justamente quedan fuera de cualquier filtro
    normal, que es como se pasan por alto.

    Detecta seis cosas distintas, porque no significan lo mismo:
      - fecha futura: el servicio todavía no pasó
      - día imposible: más servicios en un día de los que alguien puede hacer
      - mismo momento del día dos veces: nadie está en dos lugares a la vez
      - bus compartido: el mismo coche en dos servicios que se pisan
      - día no laborable: un cliente que trabaja de lunes a viernes con un
        servicio cargado un fin de semana
      - cargado tarde o en bloque: la planilla completada de memoria
    """
    import datetime as _dt
    conn = get_connection()
    rows = [dict(r) for r in conn.execute("""
        SELECT id, chofer_usuario, chofer_nombre, cliente, tramo, bus_interno,
               fecha_servicio, hora_inicio, hora_fin, km_inicial, km_final,
               pasajeros, estado, monto, liquidado,
               COALESCE(cargado_el,'') AS cargado_el
        FROM rendiciones_corp
        WHERE COALESCE(liquidado,0)=0 AND estado <> 'suspendido'
        ORDER BY fecha_servicio DESC, id DESC
    """).fetchall()]
    conn.close()

    hoy_py = _dt.date.fromisoformat(hoy())
    futuras, tardias, dia_imposible, misma_franja, bus_compartido, no_laborable = [], [], [], [], [], []
    por_momento, por_chofer_dia, por_bus_dia = {}, {}, {}

    for r in rows:
        try:
            f = _dt.date.fromisoformat(r["fecha_servicio"])
        except Exception:
            continue

        # 1. Fecha futura
        if f > hoy_py:
            r["motivo"] = f"el servicio es de dentro de {(f - hoy_py).days} día(s)"
            futuras.append(r)

        # 2. Cliente que solo opera de lunes a viernes, cargado un fin de semana
        if r["cliente"] in CLIENTES_SOLO_HABILES and f.weekday() >= 5:
            dia = "sábado" if f.weekday() == 5 else "domingo"
            r["motivo_dia"] = f"{r['cliente']} no opera los {dia}s"
            no_laborable.append(r)

        r["franja"] = franja_del_servicio(r["tramo"], r.get("hora_inicio", ""))
        por_chofer_dia.setdefault((r["chofer_usuario"], r["fecha_servicio"]), []).append(r)
        bus = str(r.get("bus_interno") or "").strip()
        if bus:
            por_bus_dia.setdefault((bus, r["fecha_servicio"]), []).append(r)

        # 3. Demora entre el servicio y su carga
        cargado = (r.get("cargado_el") or "")[:10]
        if cargado:
            try:
                dias = (_dt.date.fromisoformat(cargado) - f).days
                if dias > DIAS_ATRAS_PERMITIDOS:
                    r["motivo"] = f"cargado {dias} días después del servicio"
                    r["dias_demora"] = dias
                    tardias.append(r)
            except Exception:
                pass
            momento = (r.get("cargado_el") or "")[:16]
            if momento:
                por_momento.setdefault((r["chofer_usuario"], momento), []).append(r)

    # 4. Más servicios en un día de los permitidos
    for (usuario, fecha), grupo in por_chofer_dia.items():
        if len(grupo) > MAX_SERVICIOS_DIA:
            dia_imposible.append({
                "chofer_usuario": usuario, "chofer_nombre": grupo[0]["chofer_nombre"],
                "fecha": fecha, "cantidad": len(grupo),
                "ids": [g["id"] for g in grupo],
                "monto": round(sum(float(g["monto"] or 0) for g in grupo)),
                "detalle": [f"{g['cliente']} · {g['tramo']}" for g in grupo],
            })
        # 5. Dos servicios en la misma franja, o uno de jornada completa con otro
        franjas = {}
        for g in grupo:
            if not g["franja"]:
                continue
            franjas.setdefault(g["franja"], []).append(g)
        choque = [g for fr, gs in franjas.items() if len(gs) > 1 for g in gs]
        completa = franjas.get("completa", [])
        if completa and len(grupo) > 1:
            choque = grupo
        if choque:
            misma_franja.append({
                "chofer_usuario": usuario, "chofer_nombre": grupo[0]["chofer_nombre"],
                "fecha": fecha, "cantidad": len(choque),
                "ids": [g["id"] for g in choque],
                "monto": round(sum(float(g["monto"] or 0) for g in choque)),
                "detalle": [f"{g['cliente']} · {g['tramo']}" for g in choque],
            })

    # 6. El mismo bus en dos servicios que se pisan
    for (bus, fecha), grupo in por_bus_dia.items():
        if len(grupo) < 2:
            continue
        choferes = {g["chofer_usuario"] for g in grupo}
        franjas = {}
        for g in grupo:
            if g["franja"]:
                franjas.setdefault(g["franja"], []).append(g)
        pisa = any(len(gs) > 1 for gs in franjas.values()) or "completa" in franjas
        if pisa and len(choferes) > 1:
            bus_compartido.append({
                "bus": bus, "fecha": fecha, "cantidad": len(grupo),
                "ids": [g["id"] for g in grupo],
                "choferes": sorted({g["chofer_nombre"] for g in grupo}),
                "detalle": [f"{g['chofer_nombre']}: {g['tramo']}" for g in grupo],
                "monto": round(sum(float(g["monto"] or 0) for g in grupo)),
            })

    # 7. El bus estaba parado: fuera de servicio o con una OT abierta ese día
    bus_parado = []
    conn = get_connection()
    try:
        paradas = [dict(r) for r in conn.execute("""
            SELECT v.n_interno, f.fecha_desde, f.fecha_hasta, f.motivo
            FROM fuera_servicio f JOIN vehiculos v ON v.id = f.vehiculo_id
            WHERE v.n_interno <> ''
        """).fetchall()]
    except Exception:
        paradas = []
    try:
        # Una OT abierta varios días seguidos: el bus estuvo en el taller
        ots = [dict(r) for r in conn.execute("""
            SELECT v.n_interno, o.fecha_apertura, o.fecha_cierre, o.estado
            FROM ordenes_trabajo o JOIN vehiculos v ON v.id = o.vehiculo_id
            WHERE v.n_interno <> ''
        """).fetchall()]
    except Exception:
        ots = []
    # Capacidad de cada bus, para detectar pasajeros imposibles
    try:
        asientos = {str(r["n_interno"]): int(r["asientos"] or 0)
                    for r in conn.execute(
                        "SELECT n_interno, asientos FROM vehiculos WHERE n_interno <> ''").fetchall()}
    except Exception:
        asientos = {}
    conn.close()

    def _entre(fecha, desde, hasta):
        if not desde or fecha < desde:
            return False
        return True if not hasta else fecha <= hasta

    for r in rows:
        bus = str(r.get("bus_interno") or "").strip()
        if not bus:
            continue
        for p in paradas:
            if str(p["n_interno"]) == bus and _entre(r["fecha_servicio"],
                                                     p["fecha_desde"], p["fecha_hasta"]):
                r["motivo_parado"] = (f"el coche estaba fuera de servicio"
                                      f"{' (' + p['motivo'] + ')' if p.get('motivo') else ''}")
                bus_parado.append(r)
                break
        else:
            for o in ots:
                # Solo cuenta si la OT abarcó más de un día: una OT abierta y
                # cerrada el mismo día no necesariamente dejó el bus parado.
                if (str(o["n_interno"]) == bus and o.get("fecha_cierre")
                        and o["fecha_cierre"] > o["fecha_apertura"]
                        and _entre(r["fecha_servicio"], o["fecha_apertura"], o["fecha_cierre"])):
                    r["motivo_parado"] = "el coche estaba en el taller con una orden abierta"
                    bus_parado.append(r)
                    break

    # 8. Kilometrajes y pasajeros que no cierran
    km_raros, pax_raros = [], []
    for r in rows:
        ki = float(r.get("km_inicial") or 0)
        kf = float(r.get("km_final") or 0)
        if ki and kf:
            if kf < ki:
                r["motivo_km"] = f"el kilometraje final ({kf:.0f}) es menor que el inicial ({ki:.0f})"
                km_raros.append(r)
            elif kf - ki > 1500:
                r["motivo_km"] = f"{kf - ki:.0f} km en un solo servicio"
                km_raros.append(r)
        pax = int(r.get("pasajeros") or 0)
        cap = asientos.get(str(r.get("bus_interno") or "").strip(), 0)
        if pax and cap and pax > cap * 1.6:
            r["motivo_pax"] = f"{pax} pasajeros en un coche de {cap} asientos"
            pax_raros.append(r)

    # 9. Horarios que no cierran
    horario_raro = []
    for r in rows:
        hi = _horas_del_tramo(r.get("hora_inicio") or "")
        hf = _horas_del_tramo(r.get("hora_fin") or "")
        if hi and hf:
            dur = hf[0] - hi[0]
            if dur < 0:
                dur += 24            # cruzó la medianoche, es válido
            if dur > 16:
                r["motivo_horario"] = (f"{dur:.0f} horas de servicio "
                                       f"({r['hora_inicio']} a {r['hora_fin']})")
                horario_raro.append(r)

    # 10. Varios días cargados en el mismo minuto
    en_bloque = []
    for (usuario, momento), grupo in por_momento.items():
        fechas = {g["fecha_servicio"] for g in grupo}
        if len(fechas) > 1:
            en_bloque.append({
                "chofer_usuario": usuario, "chofer_nombre": grupo[0]["chofer_nombre"],
                "momento": momento.replace("T", " "),
                "cantidad": len(grupo), "dias_distintos": len(fechas),
                "fechas": sorted(fechas), "ids": [g["id"] for g in grupo],
                "monto": round(sum(float(g["monto"] or 0) for g in grupo)),
            })

    for lista in (en_bloque, dia_imposible, misma_franja, bus_compartido):
        lista.sort(key=lambda x: -x.get("cantidad", 0))

    total = (len(futuras) + len(tardias) + len(dia_imposible) +
             len(misma_franja) + len(bus_compartido) + len(no_laborable) +
             len(en_bloque) + len(bus_parado) + len(km_raros) + len(pax_raros) +
             len(horario_raro))
    return {
        "bus_parado": bus_parado,
        "km_raros": km_raros,
        "pax_raros": pax_raros,
        "horario_raro": horario_raro,
        "futuras": futuras,
        "tardias": sorted(tardias, key=lambda x: -x.get("dias_demora", 0)),
        "dia_imposible": dia_imposible,
        "misma_franja": misma_franja,
        "bus_compartido": bus_compartido,
        "no_laborable": no_laborable,
        "en_bloque": en_bloque,
        "sin_registro_de_carga": sum(1 for r in rows if not (r.get("cargado_el") or "").strip()),
        "revisadas": len(rows),
        "total_revisar": total,
    }


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
    es_chofer = session.get("rol") == "chofer_corp"
    ok, msg = registrar_rendicion(d, limitar_fecha=es_chofer)
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


@bp_corp.route("/api/corp/sospechosas", methods=["GET"])
def api_corp_sospechosas():
    """Servicios cargados con fechas que no cierran, para revisarlos."""
    if session.get("rol") not in ("admin", "auditor"):
        return jsonify({"error": "Sin permiso"}), 403
    return jsonify(rendiciones_sospechosas(
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
    if session.get("rol") not in ("admin", "auditor"):
        return jsonify({"error": "Sin permiso"}), 403
    cfg = config_plus()
    conn = get_connection()
    todos = [dict(r) for r in conn.execute("""
        SELECT usuario, nombre FROM usuarios
        WHERE rol='chofer_corp' AND COALESCE(activo,1)=1 ORDER BY nombre
    """).fetchall()]
    # Cuánto plus cobró cada uno, para que se vea el impacto de sacarlo
    try:
        pagado = {r["chofer_usuario"]: {"total": float(r["t"] or 0), "semanas": r["n"]}
                  for r in conn.execute("""SELECT chofer_usuario, SUM(monto) t, COUNT(*) n
                                           FROM pagos_plus GROUP BY chofer_usuario""").fetchall()}
    except Exception:
        pagado = {}
    conn.close()
    con_plus = [c.strip().upper() for c in cfg["choferes"]]
    for t in todos:
        clave = (t["nombre"] or "").strip().upper()
        t["tiene_plus"] = clave in con_plus
        t["monto_propio"] = cfg["montos"].get(clave)
        t["monto_efectivo"] = monto_plus_de(t["nombre"], cfg)
        p = pagado.get(t["usuario"], {})
        t["plus_cobrado"] = round(p.get("total", 0))
        t["semanas_cobradas"] = p.get("semanas", 0)
    return jsonify({"monto": cfg["monto"], "choferes": todos,
                    "nombres_con_plus": cfg["choferes"],
                    "con_plus": sum(1 for t in todos if t["tiene_plus"]),
                    "costo_semanal": sum(t["monto_efectivo"] for t in todos)})


@bp_corp.route("/api/corp/config_plus", methods=["POST"])
def api_corp_guardar_config_plus():
    """Guarda el monto del plus y a quiénes les corresponde."""
    if session.get("rol") != "admin":
        return jsonify({"error": "Sin permiso"}), 403
    d = request.json or {}
    ok, msg = guardar_config_plus(
        d.get("monto"), d.get("choferes", []),
        admin=session.get("nombre") or session.get("usuario", ""),
        montos=d.get("montos") or {})
    if ok:
        auditar("Cambió la configuración del plus semanal", "Corporativos", msg)
    return jsonify({"ok": ok, "msg": msg}), (200 if ok else 400)


@bp_corp.route("/api/corp/tarifas", methods=["GET"])
def api_corp_tarifas():
    """Precio de cada tramo, agrupado por cliente, para editarlo en pantalla."""
    if session.get("rol") not in ("admin", "auditor"):
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


@bp_corp.route("/api/corp/control_empresa", methods=["GET"])
def api_corp_control_empresa():
    """Panel por cliente: cobertura de tramos, costo y variables del período."""
    if session.get("rol") not in ("admin", "auditor"):
        return jsonify({"error": "Sin permiso"}), 403
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    cliente = request.args.get("cliente") or None
    agrup = request.args.get("agrupacion") or "total"
    modo = request.args.get("modo") or "reales"

    activos = [c for c in CLIENTES_TRAMOS if c not in CLIENTES_INACTIVOS]
    objetivo = [cliente] if cliente else activos

    cobertura = []
    if desde and hasta:
        for c in objetivo:
            cobertura.append(control_cobertura(c, desde, hasta, agrup, modo))

    return jsonify({
        "cobertura": cobertura,
        "costos": costo_por_empresa(desde, hasta, agrup),
        "variables": variables_del_periodo(desde, hasta, cliente),
        "clientes": activos,
        "solo_habiles": CLIENTES_SOLO_HABILES,
        "primer_servicio": primer_servicio(cliente),
    })


@bp_corp.route("/api/corp/control_empresa_pdf", methods=["GET"])
def api_corp_control_empresa_pdf():
    """PDF del control por empresa."""
    if session.get("rol") not in ("admin", "auditor"):
        return jsonify({"error": "Sin permiso"}), 403
    from flask import send_file
    import io
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    cliente = request.args.get("cliente") or None
    agrup = request.args.get("agrupacion") or "total"
    activos = [c for c in CLIENTES_TRAMOS if c not in CLIENTES_INACTIVOS]
    objetivo = [cliente] if cliente else activos
    cobertura = [control_cobertura(c, desde, hasta, agrup, request.args.get("modo") or "reales") for c in objetivo] if (desde and hasta) else []
    pdf = generar_pdf_control_empresa(
        cobertura, costo_por_empresa(desde, hasta, agrup),
        variables_del_periodo(desde, hasta, cliente), desde, hasta)
    return send_file(io.BytesIO(pdf), mimetype="application/pdf",
                     as_attachment=False, download_name="control_empresas.pdf")


# ════════════════════════════════════════════════════════════════════════════
# COMBUSTIBLE DE CORPORATIVOS
# ════════════════════════════════════════════════════════════════════════════
# Los choferes cargan el combustible desde el mismo celular donde cargan sus
# rendiciones. Va a la tabla general de combustible pero marcado como
# 'corporativo', así se puede ver aparte sin perderlo del consumo total.

@bp_corp.route("/api/corp/combustible", methods=["POST"])
def api_corp_cargar_combustible():
    """El chofer registra una carga de combustible desde el celular."""
    if session.get("rol") not in ("chofer_corp", "admin"):
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    from database import registrar_carga_combustible
    d = request.json or {}

    # Los litros llevan decimales; los montos en guaraníes no.
    def num(v):
        return a_numero(v, decimales=True)

    if not d.get("vehiculo_id"):
        return jsonify({"ok": False, "msg": "Elegí el bus."}), 400
    litros = num(d.get("litros"))
    if litros <= 0:
        return jsonify({"ok": False, "msg": "Poné cuántos litros cargaste."}), 400
    if litros > MAX_LITROS_POR_CARGA:
        return jsonify({"ok": False,
                        "msg": f"{litros:,.0f} litros es demasiado para una carga "
                               f"(el máximo es {MAX_LITROS_POR_CARGA}). "
                               f"Revisá el número.".replace(",", ".")}), 400
    # El kilometraje es opcional: si el chofer no lo tiene a mano, la carga se
    # registra igual. Sin él no se puede medir el consumo de ese tramo, pero
    # es preferible tener la carga cargada que no tenerla.
    odo = num(d.get("odometro"))

    # Al chofer solo se le piden kilometraje y litros: el precio se toma del
    # último registrado, así el costo se sigue calculando sin cargarle un dato
    # más a alguien que está en el surtidor con el celular en la mano.
    precio = num(d.get("precio_litro")) or ultimo_precio_litro()

    nombre = session.get("nombre") or session.get("usuario", "")
    cid = registrar_carga_combustible({
        "vehiculo_id": int(d["vehiculo_id"]),
        "fecha": d.get("fecha") or hoy(),
        "odometro": odo, "litros": litros,
        "precio_litro": precio,
        "costo_total": num(d.get("costo_total")),
        "estacion": (d.get("estacion") or "").strip(),
        "chofer": nombre,
        "tanque_lleno": True,
        "observaciones": (d.get("observaciones") or "").strip(),
        "registrado_por": nombre,
        "origen": "corporativo",
        "cliente": (d.get("cliente") or "").strip(),
    })
    return jsonify({"ok": True, "id": cid, "msg": "Carga registrada."})


def ultimo_precio_litro():
    """El precio por litro de la última carga con precio cargado.

    Sirve para calcular el costo de las cargas que hacen los choferes, que solo
    anotan kilometraje y litros. Si el precio del combustible cambia, se
    corrige desde la pantalla de Combustible del taller y las cargas nuevas
    toman el valor actualizado.
    """
    conn = get_connection()
    try:
        row = conn.execute("""
            SELECT precio_litro FROM combustible
            WHERE precio_litro > 0
            ORDER BY fecha DESC, id DESC LIMIT 1
        """).fetchone()
        p = float(row["precio_litro"]) if row else 0
    except Exception:
        p = 0
    conn.close()
    return p


@bp_corp.route("/api/corp/mi_dia", methods=["GET"])
def api_corp_mi_dia():
    """Qué tiene cargado el chofer ese día, para avisarle antes de que intente
    guardar un servicio que le va a rebotar."""
    if session.get("rol") not in ("chofer_corp", "admin"):
        return jsonify({"error": "Sin permiso"}), 403
    fecha = request.args.get("fecha") or hoy()
    usuario = session.get("usuario", "")
    ya = servicios_del_dia(usuario, fecha)
    return jsonify({
        "fecha": fecha,
        "servicios": [{"cliente": s["cliente"], "tramo": s["tramo"],
                       "franja": s["franja"],
                       "franja_texto": NOMBRE_FRANJA.get(s["franja"], "")}
                      for s in ya],
        "cantidad": len(ya),
        "maximo": MAX_SERVICIOS_DIA,
        "completo": len(ya) >= MAX_SERVICIOS_DIA,
        "ocupa_todo_el_dia": any(s["franja"] == "completa" for s in ya),
        "franjas_ocupadas": [s["franja"] for s in ya if s["franja"]],
    })


@bp_corp.route("/api/corp/mis_cargas", methods=["GET"])
def api_corp_mis_cargas():
    """Las últimas cargas del chofer, para que las vea en su celular."""
    if session.get("rol") not in ("chofer_corp", "admin"):
        return jsonify({"error": "Sin permiso"}), 403
    from database import obtener_cargas_combustible
    nombre = session.get("nombre") or session.get("usuario", "")
    cargas = obtener_cargas_combustible(origen="corporativo", chofer=nombre, limite=40)
    cargas.sort(key=lambda x: (x.get("fecha") or ""), reverse=True)
    total_litros = sum(float(c.get("litros") or 0) for c in cargas)
    return jsonify({"cargas": cargas[:20],
                    "total_litros": round(total_litros, 2),
                    "cantidad": len(cargas)})


@bp_corp.route("/api/corp/combustible", methods=["GET"])
def api_corp_combustible_resumen():
    """Resumen de las cargas de corporativos para el admin: por período, por
    chofer, por bus y por cliente."""
    if session.get("rol") not in ("admin", "auditor"):
        return jsonify({"error": "Sin permiso"}), 403
    from database import obtener_cargas_combustible
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    chofer = request.args.get("chofer") or None
    agrup = request.args.get("agrupacion") or "total"

    cargas = obtener_cargas_combustible(desde=desde, hasta=hasta,
                                        origen="corporativo", chofer=chofer,
                                        limite=5000)
    cargas.sort(key=lambda x: (x.get("fecha") or ""), reverse=True)
    return jsonify({
        "cargas": cargas,
        "resumen": resumen_combustible_corp(cargas, agrup),
        "choferes": choferes_corp_registrados(),
    })


def resumen_combustible_corp(cargas, agrupacion="total"):
    """Totales de combustible: general, por período, por chofer y por bus."""
    def n(v):
        try: return float(v or 0)
        except Exception: return 0

    total_litros = sum(n(c.get("litros")) for c in cargas)
    total_costo = sum(n(c.get("costo_total")) for c in cargas)

    por_periodo, por_chofer, por_bus = {}, {}, {}
    for c in cargas:
        per = _periodo_de(c.get("fecha", ""), agrupacion)
        p = por_periodo.setdefault(per, {"periodo": per, "cargas": 0,
                                         "litros": 0, "costo": 0})
        p["cargas"] += 1; p["litros"] += n(c.get("litros")); p["costo"] += n(c.get("costo_total"))

        ch = c.get("chofer") or "—"
        d = por_chofer.setdefault(ch, {"chofer": ch, "cargas": 0, "litros": 0, "costo": 0})
        d["cargas"] += 1; d["litros"] += n(c.get("litros")); d["costo"] += n(c.get("costo_total"))

        bus = c.get("n_interno") or c.get("patente") or "—"
        b = por_bus.setdefault(bus, {"bus": bus, "patente": c.get("patente", ""),
                                     "cargas": 0, "litros": 0, "costo": 0,
                                     "rendimientos": []})
        b["cargas"] += 1; b["litros"] += n(c.get("litros")); b["costo"] += n(c.get("costo_total"))
        if c.get("rendimiento"):
            b["rendimientos"].append(n(c.get("rendimiento")))

    # El consumo por bus se calcula sobre el total de km y litros de ese bus,
    # no promediando los rendimientos de cada carga.
    from database import consumo_promedio
    from database import comparar_con_referencia
    for bus, b in por_bus.items():
        b.pop("rendimientos", None)
        del_bus = [c for c in cargas
                   if (c.get("n_interno") or c.get("patente") or "—") == bus]
        prom = consumo_promedio(del_bus)
        b["rendimiento"] = prom["km_l"]
        b["litros_100km"] = prom["litros_100km"]
        b["km_medidos"] = prom["km_totales"]
        # Contra qué se compara: el consumo esperado de ese motor
        vid = del_bus[0].get("vehiculo_id") if del_bus else None
        b["comparacion"] = comparar_con_referencia(vid, prom) if vid else None
        b["litros"] = round(b["litros"], 2); b["costo"] = round(b["costo"])
    for d in list(por_periodo.values()) + list(por_chofer.values()):
        d["litros"] = round(d["litros"], 2); d["costo"] = round(d["costo"])

    prom_general = consumo_promedio(cargas)
    return {
        "cargas": len(cargas),
        "litros": round(total_litros, 2),
        "consumo": prom_general,
        "costo": round(total_costo),
        "precio_promedio": round(total_costo / total_litros) if total_litros else 0,
        "por_periodo": sorted(por_periodo.values(), key=lambda x: x["periodo"], reverse=True),
        "por_chofer": sorted(por_chofer.values(), key=lambda x: -x["litros"]),
        "por_bus": sorted(por_bus.values(), key=lambda x: -x["litros"]),
    }


def perfil_de_uso(n_interno, desde=None, hasta=None):
    """Qué hizo ese bus en el período: qué tramos, para qué clientes, con qué
    choferes y cuántos kilómetros.

    Sirve para entender por qué dos coches iguales consumen distinto. El
    consumo no depende solo del motor: un bus que hace ciudad con paradas cada
    500 metros gasta mucho más que uno que hace ruta, aunque sean gemelos.
    """
    q = """SELECT tramo, cliente, chofer_nombre, fecha_servicio,
                  km_inicial, km_final, pasajeros, estado
           FROM rendiciones_corp
           WHERE bus_interno=? AND estado <> 'suspendido'"""
    params = [str(n_interno)]
    if desde:
        q += " AND fecha_servicio>=?"; params.append(desde)
    if hasta:
        q += " AND fecha_servicio<=?"; params.append(hasta)
    conn = get_connection()
    rows = [dict(r) for r in conn.execute(q, params).fetchall()]
    conn.close()

    tramos, clientes, choferes = {}, {}, {}
    km_reportados, con_km, pasajeros = 0, 0, 0
    for r in rows:
        tramos[r["tramo"]] = tramos.get(r["tramo"], 0) + 1
        clientes[r["cliente"]] = clientes.get(r["cliente"], 0) + 1
        ch = r.get("chofer_nombre") or "—"
        choferes[ch] = choferes.get(ch, 0) + 1
        ki, kf = float(r.get("km_inicial") or 0), float(r.get("km_final") or 0)
        if ki and kf and kf > ki:
            km_reportados += kf - ki
            con_km += 1
        pasajeros += int(r.get("pasajeros") or 0)

    ordenar = lambda d: sorted([{"nombre": k, "veces": v} for k, v in d.items()],
                               key=lambda x: -x["veces"])
    return {
        "servicios": len(rows),
        "tramos": ordenar(tramos),
        "clientes": ordenar(clientes),
        "choferes": ordenar(choferes),
        "km_reportados": round(km_reportados),
        "servicios_con_km": con_km,
        "pasajeros": pasajeros,
        "dias_distintos": len({r["fecha_servicio"] for r in rows}),
    }


@bp_corp.route("/api/combustible/control", methods=["GET"])
def api_control_combustible():
    """Control estadístico del consumo: desvíos, choferes, cargas raras."""
    if session.get("rol") not in ("admin", "auditor", "taller"):
        return jsonify({"error": "Sin permiso"}), 403
    from database import control_estadistico_combustible
    return jsonify(control_estadistico_combustible(
        desde=request.args.get("desde") or None,
        hasta=request.args.get("hasta") or None))


@bp_corp.route("/api/corp/comparar_buses", methods=["GET"])
def api_comparar_buses():
    """Pone dos buses lado a lado para entender por qué consumen distinto."""
    if session.get("rol") not in ("admin", "auditor", "taller"):
        return jsonify({"error": "Sin permiso"}), 403
    from database import (obtener_cargas_combustible, consumo_promedio,
                          comparar_con_referencia, referencia_de_vehiculo)

    internos = [request.args.get("a", ""), request.args.get("b", "")]
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None

    conn = get_connection()
    buses = []
    for n in internos:
        row = conn.execute("""SELECT id, n_interno, patente, marca, modelo, asientos, tipo
                              FROM vehiculos WHERE n_interno=?""", (str(n),)).fetchone()
        buses.append(dict(row) if row else None)
    conn.close()
    if not all(buses):
        return jsonify({"error": "No encontré alguno de los dos coches"}), 404

    salida = []
    for b in buses:
        cargas = obtener_cargas_combustible(vehiculo_id=b["id"], desde=desde,
                                            hasta=hasta, limite=2000)
        prom = consumo_promedio(cargas)
        validas = [c for c in cargas if c.get("consumo_valido")]
        salida.append({
            "bus": b,
            "consumo": prom,
            "referencia": referencia_de_vehiculo(b["id"]),
            "comparacion": comparar_con_referencia(b["id"], prom),
            "cargas": len(cargas),
            "tramos_medidos": len(validas),
            "detalle_tramos": [{
                "fecha": c["fecha"], "km": c.get("km_recorridos"),
                "litros": c.get("litros_del_tramo"),
                "litros_100km": c.get("litros_100km"),
            } for c in validas][:20],
            "dudosos": [{"fecha": c["fecha"], "valor": c.get("rendimiento_dudoso")}
                        for c in cargas if c.get("rendimiento_dudoso")],
            "uso": perfil_de_uso(b["n_interno"], desde, hasta),
        })

    # Qué tienen distinto: lo que explica la diferencia de consumo
    a, bb = salida[0], salida[1]
    dif = {}
    if a["consumo"]["litros_100km"] and bb["consumo"]["litros_100km"]:
        dif["consumo_pct"] = round(
            (a["consumo"]["litros_100km"] - bb["consumo"]["litros_100km"])
            / bb["consumo"]["litros_100km"] * 100, 1)
    ta = {t["nombre"] for t in a["uso"]["tramos"]}
    tb = {t["nombre"] for t in bb["uso"]["tramos"]}
    dif["tramos_solo_a"] = sorted(ta - tb)
    dif["tramos_solo_b"] = sorted(tb - ta)
    dif["tramos_compartidos"] = sorted(ta & tb)
    ca = {c["nombre"] for c in a["uso"]["choferes"]}
    cb = {c["nombre"] for c in bb["uso"]["choferes"]}
    dif["choferes_solo_a"] = sorted(ca - cb)
    dif["choferes_solo_b"] = sorted(cb - ca)
    dif["mismo_modelo"] = (a["bus"]["modelo"] or "").strip().upper() == \
                          (bb["bus"]["modelo"] or "").strip().upper()
    dif["mismo_plan"] = ((a["referencia"] or {}).get("modelo") ==
                         (bb["referencia"] or {}).get("modelo"))

    return jsonify({"buses": salida, "diferencias": dif,
                    "desde": desde, "hasta": hasta})


@bp_corp.route("/api/corp/combustible_pdf", methods=["GET"])
def api_corp_combustible_pdf():
    """PDF del resumen de combustible de corporativos."""
    if session.get("rol") not in ("admin", "auditor"):
        return jsonify({"error": "Sin permiso"}), 403
    from flask import send_file
    from database import obtener_cargas_combustible
    import io
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    chofer = request.args.get("chofer") or None
    agrup = request.args.get("agrupacion") or "total"
    cargas = obtener_cargas_combustible(desde=desde, hasta=hasta,
                                        origen="corporativo", chofer=chofer,
                                        limite=5000)
    cargas.sort(key=lambda x: (x.get("fecha") or ""), reverse=True)
    # El control va al final del PDF: es lo que sirve para sentarse a revisar
    control = None
    if request.args.get("control", "1") != "0":
        try:
            from database import control_estadistico_combustible
            control = control_estadistico_combustible(desde=desde, hasta=hasta)
        except Exception:
            control = None
    pdf = generar_pdf_combustible_corp(cargas, resumen_combustible_corp(cargas, agrup),
                                       desde, hasta, agrup, control)
    return send_file(io.BytesIO(pdf), mimetype="application/pdf",
                     as_attachment=False, download_name="combustible_corporativos.pdf")


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
    if session.get("rol") not in ("admin", "auditor"):
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
        hasta=request.args.get("hasta") or None,
        modo=request.args.get("modo") or "servicio")
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
    modo = request.args.get("modo") or "servicio"
    pagos = historial_liquidaciones(
        chofer_usuario=request.args.get("chofer") or None,
        desde=desde, hasta=hasta, modo=modo)
    return send_file(io.BytesIO(generar_pdf_historial(pagos, desde, hasta, modo)),
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


def generar_pdf_combustible_corp(cargas, resumen, desde, hasta, agrupacion="total",
                                 control=None):
    """PDF del combustible de corporativos: totales, desglose por período,
    por chofer y por bus, más el detalle de cada carga."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph, Spacer)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    import io

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14*mm, rightMargin=14*mm,
                            topMargin=15*mm, bottomMargin=14*mm,
                            title="Combustible — Corporativos")
    S = getSampleStyleSheet()
    AZUL = colors.HexColor("#1E5A96")
    GRIS = colors.HexColor("#666666")
    SUAVE = colors.HexColor("#F7F6F3")
    st_tit = ParagraphStyle("t", parent=S["Title"], fontSize=15, textColor=AZUL,
                            alignment=1, spaceAfter=1)
    st_per = ParagraphStyle("p", parent=S["Normal"], fontSize=9.5, textColor=GRIS,
                            alignment=1, spaceAfter=9)
    st_sec = ParagraphStyle("s", parent=S["Normal"], fontSize=10.5, textColor=AZUL,
                            fontName="Helvetica-Bold", spaceBefore=11, spaceAfter=4)

    def gs(v):
        return f'{round(v or 0):,}'.replace(",", ".")

    def lt(v):
        return f'{(v or 0):,.1f}'.replace(",", "@").replace(".", ",").replace("@", ".")

    def tabla(datos, anchos, ultima=False):
        t = Table(datos, repeatRows=1, colWidths=anchos)
        est = [("BACKGROUND", (0, 0), (-1, 0), AZUL),
               ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
               ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
               ("FONTSIZE", (0, 0), (-1, -1), 8.5),
               ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
               ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
               ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SUAVE]),
               ("TOPPADDING", (0, 0), (-1, -1), 5),
               ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]
        if ultima:
            est += [("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EAF1F8")),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]
        t.setStyle(TableStyle(est))
        return t

    elems = [Paragraph("Combustible — Servicios Corporativos", st_tit)]
    elems.append(Paragraph(
        f"Período: {desde or '...'} al {hasta or '...'}" if (desde or hasta)
        else "Todas las cargas registradas", st_per))

    if not cargas:
        elems.append(Paragraph("No hay cargas de combustible en el período.", S["Normal"]))
        doc.build(elems)
        return buf.getvalue()

    # ── Totales ──
    r = resumen
    # Sin precios cargados las columnas de plata solo muestran ceros: se
    # omiten enteras en vez de llenar el informe de guiones.
    hay_costo = bool(r["costo"])
    if hay_costo:
        tot = [["Cargas", "Litros", "Costo Gs.", "Precio promedio Gs./L"],
               [str(r["cargas"]), lt(r["litros"]), gs(r["costo"]), gs(r["precio_promedio"])]]
        anchos_tot = [40*mm, 44*mm, 48*mm, 50*mm]
    else:
        tot = [["Cargas", "Litros"], [str(r["cargas"]), lt(r["litros"])]]
        anchos_tot = [91*mm, 91*mm]
    t = Table(tot, colWidths=anchos_tot)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8.5), ("FONTSIZE", (0, 1), (-1, 1), 13),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
        ("BACKGROUND", (0, 1), (-1, 1), colors.HexColor("#EAF1F8")),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    elems.append(t)

    # ── Por período ──
    if agrupacion != "total" and len(r["por_periodo"]) > 1:  # noqa: E501
        etiqueta = {"dia": "día", "semana": "semana", "mes": "mes"}.get(agrupacion, "período")
        elems.append(Paragraph(f"Por {etiqueta}", st_sec))
        d = [["Período", "Cargas", "Litros"] + (["Costo Gs."] if hay_costo else [])]
        for p in r["por_periodo"]:
            d.append([p["periodo"], str(p["cargas"]), lt(p["litros"])]
                     + ([gs(p["costo"])] if hay_costo else []))
        d.append(["TOTAL", str(r["cargas"]), lt(r["litros"])]
                 + ([gs(r["costo"])] if hay_costo else []))
        elems.append(tabla(d, [72*mm, 30*mm, 38*mm, 42*mm] if hay_costo
                           else [92*mm, 40*mm, 50*mm], ultima=True))

    # ── Por chofer ──
    elems.append(Paragraph("Por chofer", st_sec))
    d = [["Chofer", "Cargas", "Litros"] + (["Costo Gs."] if hay_costo else [])]
    for x in r["por_chofer"]:
        d.append([x["chofer"], str(x["cargas"]), lt(x["litros"])]
                 + ([gs(x["costo"])] if hay_costo else []))
    elems.append(tabla(d, [72*mm, 30*mm, 38*mm, 42*mm] if hay_costo
                       else [92*mm, 40*mm, 50*mm]))

    # ── Por bus ── (las mismas columnas que la pantalla)
    elems.append(Paragraph("Por bus", st_sec))
    d = [["Bus", "Patente", "Cargas", "Litros", "Consumo\nL cada 100 km",
          "Vs. su motor"] + (["Costo Gs."] if hay_costo else [])]
    filas_bus = []
    for x in r["por_bus"]:
        comp = x.get("comparacion") or {}
        if comp.get("sin_datos"):
            vs = {"sin_plan": "falta el plan", "sin_consumo": "faltan cargas"}.get(
                comp.get("estado"), "sin referencia")
        elif comp:
            vs = f'{"+" if comp["desvio_pct"] > 0 else ""}{comp["desvio_pct"]}%'
        else:
            vs = "—"
        d.append([f'#{x["bus"]}', x.get("patente", ""), str(x["cargas"]), lt(x["litros"]),
                  (lt(x["litros_100km"]) if x.get("litros_100km") else "—"), vs]
                 + ([gs(x["costo"])] if hay_costo else []))
        filas_bus.append(comp)
    t_bus = tabla(d, [22*mm, 28*mm, 20*mm, 28*mm, 30*mm, 30*mm, 30*mm] if hay_costo
                  else [26*mm, 34*mm, 24*mm, 34*mm, 36*mm, 36*mm])
    # El desvío se pinta según cómo viene cada coche, igual que en pantalla
    est_bus = []
    for i, comp in enumerate(filas_bus, start=1):
        if not comp or comp.get("sin_datos"):
            est_bus.append(("TEXTCOLOR", (5, i), (5, i), colors.HexColor("#A5A49E")))
            continue
        col = {"bien": "#2F7C46", "atencion": "#B97D0A",
               "malo": "#DC2641", "revisar": "#1E5A96"}.get(comp.get("estado"), "#666666")
        est_bus.append(("TEXTCOLOR", (5, i), (5, i), colors.HexColor(col)))
        est_bus.append(("FONTNAME", (5, i), (5, i), "Helvetica-Bold"))
    t_bus.setStyle(TableStyle(est_bus))
    elems.append(t_bus)

    # ── Detalle ──
    elems.append(Paragraph(f"Detalle de las cargas ({len(cargas)})", st_sec))
    d = [["Fecha", "Bus", "Chofer", "Odómetro", "Litros", "L/100km"]
         + (["Gs./L", "Total Gs."] if hay_costo else [])]
    for c in cargas[:90]:
        d.append([c.get("fecha", ""),
                  f'#{c.get("n_interno") or ""}',
                  (c.get("chofer") or "")[:20],
                  (gs(c.get("odometro")) if float(c.get("odometro") or 0) else "sin km"),
                  lt(c.get("litros")),
                  (lt(c.get("litros_100km")) if c.get("litros_100km") else "—")]
                 + ([gs(c.get("precio_litro")), gs(c.get("costo_total"))] if hay_costo else []))
    t2 = tabla(d, [21*mm, 16*mm, 36*mm, 24*mm, 20*mm, 22*mm, 20*mm, 28*mm] if hay_costo
               else [26*mm, 20*mm, 48*mm, 30*mm, 26*mm, 30*mm])
    t2.setStyle(TableStyle([("ALIGN", (2, 1), (2, -1), "LEFT"),
                            ("FONTSIZE", (0, 1), (-1, -1), 7.2)]))
    elems.append(t2)
    if len(cargas) > 90:
        elems.append(Paragraph(f"...y {len(cargas)-90} cargas más.", st_per))

    # ── Control del consumo ──
    if control:
        elems += _bloque_control_pdf(control, st_sec, st_per, tabla, gs, lt, mm, colors, Paragraph, Spacer)

    doc.build(elems)
    return buf.getvalue()


def _bloque_control_pdf(control, st_sec, st_per, tabla, gs, lt, mm, colors, Paragraph, Spacer):
    """Las conclusiones del control, para imprimir y revisar con el taller."""
    from reportlab.platypus import PageBreak, TableStyle
    r = control.get("resumen", {})
    coches = control.get("coches", [])
    picos = [g for g in coches if g["patron"] == "puntual" and g["nivel"] != "bajo"]
    parejos = [g for g in coches if g["patron"] == "parejo"]
    if not (picos or parejos or control.get("choferes")):
        return []

    e = [PageBreak(), Paragraph("Control del consumo", st_sec)]
    e.append(Paragraph(
        f"Cada coche se compara contra su propia historia: {r.get('buses_con_estandar', 0)} de "
        f"{r.get('buses_total', 0)} ya tienen estándar propio. "
        f"{'Ninguna carga del período tiene precio por litro, por eso no se calculan guaraníes. ' if r.get('sin_precio') else ''}"
        f"{r.get('pct_sin_km', 0)}% de las cargas no tiene kilometraje.", st_per))

    if picos:
        e.append(Paragraph("Picos: tanques que se dispararon", st_sec))
        d = [["Coche", "Fecha", "Chofer", "Consumo", "Su normal", "Desvío", "Litros de más"]]  # sin plata
        for g in picos:
            for t in g["tanques"]:
                d.append([f'#{g["bus"]}', t["fecha"], (t["chofer"] or "—")[:22],
                          lt(t["litros_100km"]), lt(t["normal"]),
                          f'{"+" if t["desvio_pct"] > 0 else ""}{t["desvio_pct"]}%',
                          f'{lt(t["litros_de_mas"])} L'])
        t = tabla(d, [20*mm, 22*mm, 44*mm, 24*mm, 24*mm, 22*mm, 28*mm])
        t.setStyle(TableStyle([
            ("ALIGN", (2, 1), (2, -1), "LEFT"),
            ("TEXTCOLOR", (5, 1), (5, -1), colors.HexColor("#DC2641")),
            ("FONTNAME", (5, 1), (5, -1), "Helvetica-Bold")]))
        e.append(t)
        e.append(Paragraph(
            "Un pico es un tanque que se aparta de lo que ese coche suele consumir. "
            "Antes de sospechar, verificar que el kilometraje esté bien cargado.", st_per))

    if parejos:
        e.append(Paragraph("Coches que consumen siempre más que su motor", st_sec))
        d = [["Coche", "Patente", "Consume siempre", "Su motor dice", "Diferencia", "Tanques"]]
        for g in parejos:
            dif = round((g["consumo_real"] - g["normal"]) / g["normal"] * 100)
            d.append([f'#{g["bus"]}', g.get("patente", ""), lt(g["consumo_real"]),
                      lt(g["normal"]), f"+{dif}%", str(g["medidos"])])
        e.append(tabla(d, [22*mm, 30*mm, 34*mm, 30*mm, 26*mm, 22*mm]))
        e.append(Paragraph(
            "No es un robo: dar siempre el mismo número por encima del motor significa que la "
            "referencia no corresponde. Revisar el plan asignado y, si está bien, ajustar la referencia.", st_per))

    chs = [x for x in control.get("choferes", []) if x.get("desvio_pct") is not None]
    if chs:
        e.append(Paragraph("Choferes", st_sec))
        d = [["Chofer", "Desvío", "Comparables", "Sin kilometraje", "Picos"]]
        for x in chs:
            d.append([x["chofer"][:30], f'{"+" if x["desvio_pct"] > 0 else ""}{x["desvio_pct"]}%',
                      f'{x["medidos"]} de {x["cargas"]}', f'{x["pct_sin_km"]}%', str(x["alertas"])])
        e.append(tabla(d, [54*mm, 24*mm, 30*mm, 30*mm, 22*mm]))
        e.append(Paragraph(
            "Cuánto se aparta cada chofer del consumo normal de los coches que manejó. "
            "Un chofer que da más en todos los coches no es el coche.", st_per))
    return e


def generar_pdf_control_empresa(cobertura, costos, variables, desde, hasta):
    """PDF del control por empresa: cobertura de tramos, costo y variables."""
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph, Spacer)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    import io

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=14*mm, rightMargin=14*mm,
                            topMargin=15*mm, bottomMargin=14*mm,
                            title="Control por empresa")
    S = getSampleStyleSheet()
    AZUL = colors.HexColor("#1E5A96")
    ROJO = colors.HexColor("#DC2641")
    GRIS = colors.HexColor("#666666")
    SUAVE = colors.HexColor("#F7F6F3")
    st_tit = ParagraphStyle("t", parent=S["Title"], fontSize=15, textColor=AZUL,
                            alignment=1, spaceAfter=1)
    st_per = ParagraphStyle("p", parent=S["Normal"], fontSize=9.5, textColor=GRIS,
                            alignment=1, spaceAfter=9)
    st_sec = ParagraphStyle("s", parent=S["Normal"], fontSize=10.5, textColor=AZUL,
                            fontName="Helvetica-Bold", spaceBefore=10, spaceAfter=4)

    def gs(v):
        return f'{round(v or 0):,}'.replace(",", ".")

    def tabla(datos, anchos, resaltar_ultima=False):
        t = Table(datos, repeatRows=1, colWidths=anchos)
        est = [
            ("BACKGROUND", (0, 0), (-1, 0), AZUL),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8.5),
            ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, SUAVE]),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]
        if resaltar_ultima:
            est += [("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EAF1F8")),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]
        t.setStyle(TableStyle(est))
        return t

    elems = [Paragraph("Control por empresa — Servicios Corporativos", st_tit)]
    elems.append(Paragraph(
        f"Período: {desde or '...'} al {hasta or '...'}" if (desde or hasta)
        else "Todos los períodos", st_per))

    # ── Cobertura ──
    if cobertura:
        elems.append(Paragraph("Cobertura de tramos", st_sec))
        hay_periodos = any(len(x.get("periodos", [])) > 1 for x in cobertura)
        cab = ["Empresa"] + (["Período"] if hay_periodos else []) + \
              ["Días", "Esperados", "Cubiertos", "Parciales", "Faltantes", "Cobertura"]
        d = [cab]
        for x in cobertura:
            pers = x.get("periodos", []) if hay_periodos else []
            for p in pers:
                d.append(["", p["periodo"], str(p["dias"]), str(p["esperados"]),
                          str(p["cubiertos"]), str(p["parciales"]),
                          str(p["faltantes"]), f'{p["cobertura"]}%'])
            fila = [x["cliente"]] + (["todo el período"] if hay_periodos else []) + \
                   [str(x["dias"]), str(x["esperados"]), str(x["cubiertos"]),
                    str(x["parciales"]), str(x["faltantes"]), f'{x["cobertura"]}%']
            d.append(fila)
        anchos = ([32*mm, 40*mm] if hay_periodos else [40*mm]) + \
                 [14*mm, 20*mm, 20*mm, 18*mm, 18*mm, 20*mm]
        elems.append(tabla(d, anchos))

    # ── Costo por empresa ──
    elems.append(Paragraph("Costo por empresa", st_sec))
    d2 = [["Empresa", "Período", "Servicios", "Variables", "Costo Gs."]]
    for f in costos.get("filas", []):
        d2.append([f["cliente"], f["periodo"], str(f["servicios"]),
                   str(f["variables"]), gs(f["costo"])])
    d2.append(["TOTAL", "", "", "", gs(costos.get("costo_total", 0))])
    elems.append(tabla(d2, [34*mm, 48*mm, 24*mm, 24*mm, 34*mm], resaltar_ultima=True))

    # ── Variables justificados ──
    v = variables or {}
    if v.get("cantidad"):
        elems.append(Paragraph(
            f"Servicios variables ({v['cantidad']}) — Gs. {gs(v['monto_total'])}", st_sec))
        if v.get("sin_justificar"):
            elems.append(Paragraph(
                f"Atención: {v['sin_justificar']} sin justificar.",
                ParagraphStyle("w", parent=S["Normal"], fontSize=8.5,
                               textColor=ROJO, spaceAfter=3)))
        d3 = [["Fecha", "Empresa", "Chofer", "Justificación", "Gs."]]
        for x in v["variables"]:
            d3.append([x["fecha_servicio"], x["cliente"],
                       (x["chofer_nombre"] or "")[:22],
                       ((x.get("observacion") or "").strip()
                        or ("(anterior a la exigencia)" if x.get("justif_exenta")
                            else "SIN JUSTIFICAR"))[:46],
                       gs(x["monto"])])
        t3 = tabla(d3, [21*mm, 24*mm, 34*mm, 62*mm, 22*mm])
        t3.setStyle(TableStyle([("ALIGN", (1, 1), (3, -1), "LEFT"),
                                ("FONTSIZE", (0, 1), (-1, -1), 7.5)]))
        elems.append(t3)

    # ── Faltantes, si los hay ──
    faltas = [f for c in cobertura for f in c.get("detalle_faltantes", [])
              if f["situacion"] in ("faltante", "parcial")]
    if faltas:
        elems.append(Paragraph(f"Tramos sin cubrir ({len(faltas)})", st_sec))
        d4 = [["Fecha", "Tramo", "Situación", "Detalle"]]
        for f in faltas[:60]:
            d4.append([f["fecha"], f["tramo"][:40], f["situacion"], f["detalle"]])
        t4 = tabla(d4, [21*mm, 72*mm, 24*mm, 46*mm])
        t4.setStyle(TableStyle([("ALIGN", (1, 1), (-1, -1), "LEFT"),
                                ("FONTSIZE", (0, 1), (-1, -1), 7.5)]))
        elems.append(t4)
        if len(faltas) > 60:
            elems.append(Paragraph(f"...y {len(faltas)-60} más.", st_per))

    doc.build(elems)
    return buf.getvalue()


def generar_pdf_historial(pagos, desde, hasta, modo="servicio"):
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
        if modo == "pago":
            rango = f"Pagos realizados entre {desde or '...'} y {hasta or '...'}"
        else:
            rango = f"Servicios prestados entre {desde or '...'} y {hasta or '...'}"
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
