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


def calcular_monto(tramo, estado):
    """Cuánto se le paga al chofer por esta rendición."""
    if estado == "suspendido":
        return 0
    if (tramo or "").strip().upper() == TRAMO_VARIABLE:
        return MONTO_VARIABLE
    if estado == "completado":
        return MONTO_COMPLETADO
    if estado in ("entrante", "saliente"):
        return MONTO_MEDIO
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
            fecha_carga TEXT DEFAULT (date('now'))
        )
    """)
    conn.commit()

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
        conn.execute(f"""
            UPDATE rendiciones_corp SET monto = CASE
                WHEN UPPER(TRIM(tramo)) = '{TRAMO_VARIABLE}' THEN {MONTO_VARIABLE}
                WHEN estado = 'completado' THEN {MONTO_COMPLETADO}
                WHEN estado IN ('entrante','saliente') THEN {MONTO_MEDIO}
                ELSE 0 END
            WHERE (monto IS NULL OR monto = 0) AND estado <> 'suspendido'
        """)
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
    Usuario = primer nombre; contraseña = igual al usuario. Idempotente:
    si el usuario ya existe, lo saltea."""
    from database import crear_usuario
    creados, saltados, colisiones = 0, 0, []
    usados = {}
    for nombre in CHOFERES_CORP:
        base = _usuario_desde_nombre(nombre)
        usuario = base
        # Resolver choferes con el mismo primer nombre (ej: dos "RICHARD")
        if base in usados:
            # Agregar inicial del apellido: 'richard' -> 'richardg'
            apellido = nombre.split(",", 1)[0].strip()
            usuario = base + apellido[0].lower()
            n = 2
            while usuario in usados:
                usuario = f"{base}{apellido[0].lower()}{n}"; n += 1
        usados[usuario] = nombre
        ok, _ = crear_usuario(usuario, usuario, nombre=nombre, rol="chofer_corp")
        if ok:
            creados += 1
        else:
            saltados += 1
    return {"creados": creados, "saltados": saltados, "usuarios": usados}


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

    monto = calcular_monto(datos["tramo"], estado)

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


def rendiciones_de_chofer(chofer_usuario, limite=50):
    """Últimas rendiciones de un chofer (para que las vea en su celular)."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM rendiciones_corp WHERE chofer_usuario=?
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

    salida = []
    for nom, d in por_chofer.items():
        tiene_plus = nom.strip().upper() in [c.upper() for c in CHOFERES_CON_PLUS]
        semanas = len(d["semanas"])
        plus = PLUS_SEMANAL * semanas if tiene_plus else 0
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
    # No se envían las tarifas: los montos son información de liquidación y
    # solo se muestran en el Resumen de admin.
    return jsonify({"clientes_tramos": activos})


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
    """Las rendiciones del chofer logueado (para ver en su celular)."""
    if session.get("rol") not in ("chofer_corp", "admin"):
        return jsonify({"error": "Sin permiso"}), 403
    # Se le quita el monto: el chofer ve sus servicios, no la liquidación.
    rends = rendiciones_de_chofer(session.get("usuario", ""))
    for r in rends:
        r.pop("monto", None)
    return jsonify(rends)


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


@bp_corp.route("/api/corp/rendiciones_pdf", methods=["GET"])
def api_corp_rendiciones_pdf():
    """PDF del resumen de rendiciones de un chofer en un período."""
    if session.get("rol") not in ("admin", "auditor"):
        return jsonify({"error": "Sin permiso"}), 403
    from flask import send_file
    import io
    chofer = request.args.get("chofer") or None
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    cliente = request.args.get("cliente") or None
    rends = obtener_rendiciones(chofer, desde, hasta, cliente)
    nombre = rends[0]["chofer_nombre"] if rends else (chofer or "Todos")
    pdf_bytes = generar_pdf_rendiciones(rends, nombre, desde, hasta)
    return send_file(io.BytesIO(pdf_bytes), mimetype="application/pdf",
                     as_attachment=False,
                     download_name=f"rendiciones_{(chofer or 'todos')}.pdf")


def generar_pdf_rendiciones(rends, nombre_chofer, desde, hasta):
    """Arma el PDF del resumen. Usa reportlab (ya disponible en el proyecto)."""
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.units import mm
    from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                    Paragraph, Spacer)
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    import io

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4),
                            leftMargin=12*mm, rightMargin=12*mm,
                            topMargin=14*mm, bottomMargin=12*mm)
    styles = getSampleStyleSheet()
    AZUL = colors.HexColor("#1E5A96")
    ROJO = colors.HexColor("#DC2641")

    titulo = ParagraphStyle("t", parent=styles["Title"], fontSize=16,
                            textColor=AZUL, spaceAfter=2)
    sub = ParagraphStyle("s", parent=styles["Normal"], fontSize=10,
                         textColor=colors.HexColor("#666666"))
    elems = [Paragraph("Rendición de Servicios Corporativos", titulo)]
    periodo = ""
    if desde or hasta:
        periodo = f"Período: {desde or '...'} a {hasta or '...'}   ·   "
    elems.append(Paragraph(f"{periodo}Chofer: <b>{nombre_chofer}</b>   ·   "
                           f"{len(rends)} servicio(s)", sub))
    elems.append(Spacer(1, 8))

    if not rends:
        elems.append(Paragraph("No hay rendiciones en el período seleccionado.",
                               styles["Normal"]))
    else:
        def gs(v):
            return f'{v or 0:,.0f}'.replace(",", ".")

        etiqueta = {"completado": "Completo", "entrante": "Entrante",
                    "saliente": "Saliente", "suspendido": "Suspendido"}
        head = ["Fecha", "Cliente", "Tramo", "Bus", "Inicio", "Fin",
                "Km ini", "Km fin", "Pas.", "Estado", "Monto Gs."]
        data = [head]
        for r in rends:
            data.append([
                r.get("fecha_servicio", ""), r.get("cliente", ""),
                (r.get("tramo", "")[:24]), str(r.get("bus_interno", "")),
                r.get("hora_inicio", ""), r.get("hora_fin", ""),
                gs(r.get("km_inicial")), gs(r.get("km_final")),
                str(r.get("pasajeros") or 0),
                etiqueta.get(r.get("estado", ""), r.get("estado", "")),
                gs(r.get("monto")),
            ])
        col_w = [19*mm, 24*mm, 46*mm, 15*mm, 14*mm, 14*mm,
                 19*mm, 19*mm, 12*mm, 21*mm, 22*mm]
        t = Table(data, colWidths=col_w, repeatRows=1)
        estilo = [
            ("BACKGROUND", (0, 0), (-1, 0), AZUL),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("FONTSIZE", (0, 1), (-1, -1), 7.5),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (3, 0), (-1, -1), "CENTER"),
            ("ALIGN", (10, 0), (10, -1), "RIGHT"),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#F7F6F3")]),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]
        # Marcar en rojo las filas suspendidas
        for i, r in enumerate(rends, start=1):
            if r.get("estado") == "suspendido":
                estilo.append(("TEXTCOLOR", (9, i), (9, i), ROJO))
                estilo.append(("FONTNAME", (9, i), (9, i), "Helvetica-Bold"))
        t.setStyle(TableStyle(estilo))
        elems.append(t)

        # ── Liquidación: tramos + plus semanal ──
        liq = liquidacion_por_chofer(rends)
        if liq:
            elems.append(Spacer(1, 12))
            elems.append(Paragraph("<b>Liquidación del período</b>", sub))
            elems.append(Spacer(1, 4))
            lh = ["Chofer", "Servicios", "Completos", "Medios",
                  "Tramos Gs.", "Semanas", "Plus Gs.", "Total Gs."]
            ldata = [lh]
            tot_general = 0
            for l in liq:
                tot_general += l["total"]
                ldata.append([
                    l["chofer_nombre"], str(l["servicios"]), str(l["completados"]),
                    str(l["medios"]), gs(l["monto_tramos"]),
                    str(l["semanas_trabajadas"]) if l["tiene_plus"] else "—",
                    gs(l["plus"]) if l["tiene_plus"] else "—",
                    gs(l["total"]),
                ])
            ldata.append(["TOTAL", "", "", "", "", "", "", gs(tot_general)])
            lt = Table(ldata, colWidths=[58*mm, 20*mm, 22*mm, 18*mm,
                                         26*mm, 20*mm, 24*mm, 28*mm],
                       repeatRows=1)
            lt.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), AZUL),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2),
                 [colors.white, colors.HexColor("#F7F6F3")]),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EAF1F8")),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]))
            elems.append(lt)

        # Detalle de suspensiones (observaciones)
        susp = [r for r in rends if r.get("estado") == "suspendido" and r.get("observacion")]
        if susp:
            elems.append(Spacer(1, 10))
            elems.append(Paragraph("<b>Servicios suspendidos — motivos:</b>", sub))
            for r in susp:
                elems.append(Paragraph(
                    f"• {r.get('fecha_servicio','')} · {r.get('cliente','')} "
                    f"({r.get('tramo','')}): {r.get('observacion','')}",
                    ParagraphStyle("o", parent=styles["Normal"], fontSize=8.5,
                                   textColor=ROJO, leftIndent=6)))

    doc.build(elems)
    return buf.getvalue()
