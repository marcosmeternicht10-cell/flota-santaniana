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
    "FAPASA Y LASCA": [
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
            estado TEXT DEFAULT 'completado',  -- completado | suspendido
            observacion TEXT DEFAULT '',       -- obligatoria si suspendido
            fecha_carga TEXT DEFAULT (date('now'))
        )
    """)
    conn.commit()
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

def registrar_rendicion(datos):
    """Guarda una rendición cargada por un chofer. Valida lo mínimo:
    cliente, tramo, fecha, bus, y observación si el estado es suspendido."""
    req = ["cliente", "tramo", "fecha_servicio", "bus_interno"]
    for r in req:
        if not str(datos.get(r, "")).strip():
            return False, f"Falta {r.replace('_',' ')}."
    estado = datos.get("estado", "completado")
    if estado == "suspendido" and not str(datos.get("observacion", "")).strip():
        return False, "Si el servicio fue suspendido, explicá el motivo en la observación."

    def num(v):
        try: return float(str(v).replace(".", "").replace(",", ".") or 0)
        except: return 0

    conn = get_connection()
    conn.execute("""INSERT INTO rendiciones_corp
        (chofer_usuario, chofer_nombre, cliente, tramo, fecha_servicio,
         bus_interno, hora_inicio, hora_fin, km_inicial, km_final,
         pasajeros, estado, observacion)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (datos.get("chofer_usuario", ""), datos.get("chofer_nombre", ""),
         datos["cliente"].strip(), datos["tramo"].strip(),
         datos["fecha_servicio"].strip(), str(datos["bus_interno"]).strip(),
         datos.get("hora_inicio", ""), datos.get("hora_fin", ""),
         num(datos.get("km_inicial")), num(datos.get("km_final")),
         int(num(datos.get("pasajeros"))), estado,
         datos.get("observacion", "").strip()))
    conn.commit()
    conn.close()
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
    """Clientes y tramos para los selectores encadenados del reporte."""
    return jsonify({"clientes_tramos": CLIENTES_TRAMOS})


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
    return jsonify(rendiciones_de_chofer(session.get("usuario", "")))


@bp_corp.route("/api/corp/rendiciones", methods=["GET"])
def api_corp_rendiciones():
    """Resumen para admin/auditor: filtrable por chofer, período, cliente."""
    if session.get("rol") not in ("admin", "auditor"):
        return jsonify({"error": "Sin permiso"}), 403
    return jsonify(obtener_rendiciones(
        chofer_usuario=request.args.get("chofer") or None,
        desde=request.args.get("desde") or None,
        hasta=request.args.get("hasta") or None,
        cliente=request.args.get("cliente") or None))


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
        head = ["Fecha", "Cliente", "Tramo", "Bus", "Inicio", "Fin",
                "Km ini", "Km fin", "Pasaj.", "Estado"]
        data = [head]
        for r in rends:
            data.append([
                r.get("fecha_servicio", ""), r.get("cliente", ""),
                (r.get("tramo", "")[:26]), str(r.get("bus_interno", "")),
                r.get("hora_inicio", ""), r.get("hora_fin", ""),
                f'{r.get("km_inicial") or 0:,.0f}'.replace(",", "."),
                f'{r.get("km_final") or 0:,.0f}'.replace(",", "."),
                str(r.get("pasajeros") or 0),
                r.get("estado", ""),
            ])
        col_w = [20*mm, 26*mm, 52*mm, 16*mm, 16*mm, 16*mm,
                 20*mm, 20*mm, 16*mm, 24*mm]
        t = Table(data, colWidths=col_w, repeatRows=1)
        estilo = [
            ("BACKGROUND", (0, 0), (-1, 0), AZUL),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, 0), 8),
            ("FONTSIZE", (0, 1), (-1, -1), 7.5),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN", (3, 0), (-1, -1), "CENTER"),
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
