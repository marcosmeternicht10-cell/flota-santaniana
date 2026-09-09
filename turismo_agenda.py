"""
turismo_agenda.py — Agenda de servicios de turismo

Reemplaza la planilla donde se anotan los viajes contratados: qué día, a qué
hora, para qué cliente, de dónde a dónde, con qué coche y qué chofer.

Dos cosas del proceso real que el módulo respeta:

  - Un servicio se agenda ANTES de saber qué coche y qué chofer van a ir. En la
    planilla eso se anota como "A DEF". Acá es un estado propio, y el sistema
    avisa cuáles quedan sin asignar para que no se pasen por alto.

  - Un mismo número de orden puede tener varios servicios: la ida y la vuelta
    de un mismo viaje van con el mismo número.
"""

from flask import Blueprint, request, jsonify, session
from db_compat import get_connection, USE_POSTGRES
from hora_local import ahora_iso, hoy

try:
    from database import auditar
except Exception:
    def auditar(*a, **k):
        pass

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"

bp_turismo = Blueprint("turismo_agenda", __name__)

DIAS = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES",
        "VIERNES", "SÁBADO", "DOMINGO"]

# Un servicio pasa por estos momentos
ESTADOS = ["agendado", "confirmado", "en_curso", "completado", "cancelado"]


def inicializar_agenda_turismo():
    conn = get_connection()
    c = conn.cursor()
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS agenda_turismo (
            id            {PK},
            fecha         TEXT NOT NULL,
            hora          TEXT DEFAULT '',
            cliente       TEXT NOT NULL,
            ot_nr         TEXT DEFAULT '',
            salida        TEXT DEFAULT '',
            destino       TEXT DEFAULT '',
            vehiculo_id   INTEGER,
            coche_interno TEXT DEFAULT '',
            tripulacion   TEXT DEFAULT '',
            estado        TEXT DEFAULT 'agendado',
            pasajeros     INTEGER DEFAULT 0,
            observaciones TEXT DEFAULT '',
            creado_por    TEXT DEFAULT '',
            fecha_creacion TEXT
        )
    """)
    conn.commit()
    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_agenda_fecha ON agenda_turismo (fecha)")
        conn.commit()
    except Exception:
        conn.rollback()
    conn.close()


def dia_de_la_semana(fecha_iso):
    """El día que le corresponde a una fecha — se calcula, no se carga."""
    import datetime as _dt
    try:
        return DIAS[_dt.date.fromisoformat(fecha_iso).weekday()]
    except Exception:
        return ""


def _enriquecer(s):
    """Agrega lo que se deduce: el día de la semana y si falta asignar."""
    s["dia_servicio"] = dia_de_la_semana(s.get("fecha", ""))
    sin_coche = not (s.get("coche_interno") or "").strip()
    sin_chofer = not (s.get("tripulacion") or "").strip()
    s["sin_asignar"] = sin_coche or sin_chofer
    s["falta"] = ("coche y chofer" if (sin_coche and sin_chofer)
                  else "coche" if sin_coche
                  else "chofer" if sin_chofer else "")
    return s


def listar_servicios(desde=None, hasta=None, cliente=None, estado=None,
                     solo_sin_asignar=False):
    """Los servicios agendados en un rango, del más próximo al más lejano."""
    q = """SELECT a.*, v.patente, v.marca, v.modelo
           FROM agenda_turismo a
           LEFT JOIN vehiculos v ON v.id = a.vehiculo_id
           WHERE 1=1"""
    params = []
    if desde:
        q += " AND a.fecha >= ?"; params.append(desde)
    if hasta:
        q += " AND a.fecha <= ?"; params.append(hasta)
    if cliente:
        q += " AND a.cliente = ?"; params.append(cliente)
    if estado:
        q += " AND a.estado = ?"; params.append(estado)
    q += " ORDER BY a.fecha ASC, a.hora ASC, a.id ASC"

    conn = get_connection()
    rows = [_enriquecer(dict(r)) for r in conn.execute(q, params).fetchall()]
    conn.close()
    if solo_sin_asignar:
        rows = [r for r in rows if r["sin_asignar"] and r["estado"] != "cancelado"]
    return rows


def agrupar_por_dia(servicios):
    """Los servicios agrupados por fecha, que es como se lee una agenda."""
    dias = {}
    for s in servicios:
        d = dias.setdefault(s["fecha"], {
            "fecha": s["fecha"],
            "dia_servicio": s["dia_servicio"],
            "servicios": [], "sin_asignar": 0,
        })
        d["servicios"].append(s)
        if s["sin_asignar"] and s["estado"] != "cancelado":
            d["sin_asignar"] += 1
    return sorted(dias.values(), key=lambda x: x["fecha"])


def resumen_agenda(servicios):
    """Los números de arriba: cuántos hay, cuántos faltan asignar, por cliente."""
    activos = [s for s in servicios if s["estado"] != "cancelado"]
    por_cliente = {}
    for s in activos:
        c = por_cliente.setdefault(s["cliente"], {"cliente": s["cliente"], "servicios": 0})
        c["servicios"] += 1
    return {
        "total": len(activos),
        "sin_asignar": sum(1 for s in activos if s["sin_asignar"]),
        "completados": sum(1 for s in servicios if s["estado"] == "completado"),
        "cancelados": sum(1 for s in servicios if s["estado"] == "cancelado"),
        "dias": len({s["fecha"] for s in activos}),
        "por_cliente": sorted(por_cliente.values(), key=lambda x: -x["servicios"]),
    }


def sugerir_ot(cliente):
    """Propone el próximo número de orden para ese cliente.

    Sigue el formato de la planilla: tres letras del cliente, el año en dos
    dígitos y un correlativo — REC 26-42, GUA 26-43. Es una sugerencia: el
    número se puede escribir a mano si la empresa usa otro.
    """
    import datetime as _dt
    letras = "".join(ch for ch in (cliente or "").upper() if ch.isalpha())[:3] or "TUR"
    anio = _dt.date.today().strftime("%y")
    prefijo = f"{letras} {anio}-"

    conn = get_connection()
    rows = conn.execute("SELECT ot_nr FROM agenda_turismo WHERE ot_nr LIKE ?",
                        (prefijo + "%",)).fetchall()
    # También se mira el correlativo global del año, para que los números no
    # se pisen entre clientes distintos.
    todos = conn.execute("SELECT ot_nr FROM agenda_turismo WHERE ot_nr LIKE ?",
                         (f"% {anio}-%",)).fetchall()
    conn.close()

    def numero(v):
        try:
            return int(str(v["ot_nr"]).rsplit("-", 1)[-1])
        except Exception:
            return 0

    ultimo = max([numero(r) for r in todos] + [0])
    return f"{prefijo}{ultimo + 1}"


def guardar_servicio(datos, usuario=""):
    """Agenda un servicio nuevo."""
    if not (datos.get("fecha") or "").strip():
        return False, "Falta la fecha del servicio.", None
    if not (datos.get("cliente") or "").strip():
        return False, "Falta el cliente.", None

    conn = get_connection()
    cur = conn.execute("""
        INSERT INTO agenda_turismo
            (fecha, hora, cliente, ot_nr, salida, destino, vehiculo_id,
             coche_interno, tripulacion, estado, pasajeros, observaciones,
             creado_por, fecha_creacion)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        datos["fecha"].strip(), (datos.get("hora") or "").strip(),
        datos["cliente"].strip().upper(), (datos.get("ot_nr") or "").strip().upper(),
        (datos.get("salida") or "").strip(), (datos.get("destino") or "").strip(),
        int(datos["vehiculo_id"]) if datos.get("vehiculo_id") else None,
        (datos.get("coche_interno") or "").strip(),
        (datos.get("tripulacion") or "").strip().upper(),
        datos.get("estado", "agendado"),
        int(datos.get("pasajeros") or 0),
        (datos.get("observaciones") or "").strip(),
        usuario, ahora_iso(),
    ))
    sid = cur.lastrowid
    conn.commit()
    conn.close()
    return True, "Servicio agendado.", sid


def actualizar_servicio(sid, datos):
    """Corrige un servicio agendado."""
    conn = get_connection()
    actual = conn.execute("SELECT * FROM agenda_turismo WHERE id=?", (sid,)).fetchone()
    if not actual:
        conn.close()
        return False, "No encontré ese servicio."
    a = dict(actual)

    def v(clave, mayus=False):
        if clave not in datos:
            return a.get(clave)
        x = (datos.get(clave) or "")
        x = x.strip() if isinstance(x, str) else x
        return x.upper() if (mayus and isinstance(x, str)) else x

    conn.execute("""
        UPDATE agenda_turismo SET
            fecha=?, hora=?, cliente=?, ot_nr=?, salida=?, destino=?,
            vehiculo_id=?, coche_interno=?, tripulacion=?, estado=?,
            pasajeros=?, observaciones=?
        WHERE id=?
    """, (
        v("fecha") or a["fecha"], v("hora"), v("cliente", True) or a["cliente"],
        v("ot_nr", True), v("salida"), v("destino"),
        (int(datos["vehiculo_id"]) if datos.get("vehiculo_id")
         else (None if "vehiculo_id" in datos else a.get("vehiculo_id"))),
        v("coche_interno"), v("tripulacion", True),
        v("estado") or a.get("estado", "agendado"),
        int(datos.get("pasajeros", a.get("pasajeros") or 0) or 0),
        v("observaciones"), sid,
    ))
    conn.commit()
    conn.close()
    return True, "Servicio actualizado."


def asignar(sid, vehiculo_id=None, coche_interno="", tripulacion=""):
    """Asigna coche y chofer a un servicio que estaba en 'a definir'.
    Es la acción más frecuente, por eso va aparte del editar completo."""
    conn = get_connection()
    fila = conn.execute("SELECT id FROM agenda_turismo WHERE id=?", (sid,)).fetchone()
    if not fila:
        conn.close()
        return False, "No encontré ese servicio."
    conn.execute("""UPDATE agenda_turismo
                    SET vehiculo_id=?, coche_interno=?, tripulacion=?
                    WHERE id=?""",
                 (int(vehiculo_id) if vehiculo_id else None,
                  (coche_interno or "").strip(),
                  (tripulacion or "").strip().upper(), sid))
    conn.commit()
    conn.close()
    return True, "Coche y tripulación asignados."


def cambiar_estado(sid, estado):
    if estado not in ESTADOS:
        return False, "Ese estado no existe."
    conn = get_connection()
    conn.execute("UPDATE agenda_turismo SET estado=? WHERE id=?", (estado, sid))
    conn.commit()
    conn.close()
    return True, f"Servicio marcado como {estado.replace('_', ' ')}."


def eliminar_servicio(sid):
    conn = get_connection()
    conn.execute("DELETE FROM agenda_turismo WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    return True, "Servicio eliminado de la agenda."


def clientes_frecuentes():
    """Los clientes ya cargados, para ofrecerlos al escribir."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT cliente, COUNT(*) AS veces FROM agenda_turismo
        GROUP BY cliente ORDER BY veces DESC, cliente ASC
    """).fetchall()
    conn.close()
    return [r["cliente"] for r in rows]


def choferes_frecuentes():
    """Las tripulaciones ya usadas, para no reescribir el nombre cada vez."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT tripulacion, COUNT(*) AS veces FROM agenda_turismo
        WHERE tripulacion <> '' GROUP BY tripulacion
        ORDER BY veces DESC, tripulacion ASC
    """).fetchall()
    conn.close()
    return [r["tripulacion"] for r in rows]


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ════════════════════════════════════════════════════════════════════════════

def _puede_gestionar():
    return session.get("rol") in ("admin", "taller")


@bp_turismo.route("/api/turismo/agenda", methods=["GET"])
def api_agenda():
    if not session.get("usuario_id"):
        return jsonify({"error": "Sin sesión"}), 401
    servicios = listar_servicios(
        desde=request.args.get("desde") or None,
        hasta=request.args.get("hasta") or None,
        cliente=request.args.get("cliente") or None,
        estado=request.args.get("estado") or None,
        solo_sin_asignar=request.args.get("sin_asignar") == "1")
    return jsonify({
        "servicios": servicios,
        "dias": agrupar_por_dia(servicios),
        "resumen": resumen_agenda(servicios),
        "clientes": clientes_frecuentes(),
        "choferes": choferes_frecuentes(),
    })


@bp_turismo.route("/api/turismo/agenda", methods=["POST"])
def api_agendar():
    if not _puede_gestionar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    ok, msg, sid = guardar_servicio(
        request.json or {},
        usuario=session.get("nombre") or session.get("usuario", ""))
    if ok:
        auditar("Agendó un servicio de turismo", "Turismo",
                f"{(request.json or {}).get('cliente','')} · {(request.json or {}).get('fecha','')}")
    return jsonify({"ok": ok, "msg": msg, "id": sid}), (200 if ok else 400)


@bp_turismo.route("/api/turismo/agenda/<int:sid>", methods=["PATCH"])
def api_editar_servicio(sid):
    if not _puede_gestionar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    d = request.json or {}
    if "estado" in d and len(d) == 1:
        ok, msg = cambiar_estado(sid, d["estado"])
    elif "asignar" in d:
        ok, msg = asignar(sid, d.get("vehiculo_id"), d.get("coche_interno", ""),
                          d.get("tripulacion", ""))
    else:
        ok, msg = actualizar_servicio(sid, d)
    if ok:
        auditar(f"Modificó un servicio de turismo (#{sid})", "Turismo", msg)
    return jsonify({"ok": ok, "msg": msg}), (200 if ok else 400)


@bp_turismo.route("/api/turismo/agenda/<int:sid>", methods=["DELETE"])
def api_borrar_servicio(sid):
    if session.get("rol") != "admin":
        return jsonify({"ok": False, "msg": "Solo un administrador puede borrar"}), 403
    ok, msg = eliminar_servicio(sid)
    auditar(f"Eliminó un servicio de turismo (#{sid})", "Turismo")
    return jsonify({"ok": ok, "msg": msg})


@bp_turismo.route("/api/turismo/sugerir_ot", methods=["GET"])
def api_sugerir_ot():
    if not _puede_gestionar():
        return jsonify({"error": "Sin permiso"}), 403
    return jsonify({"ot_nr": sugerir_ot(request.args.get("cliente", ""))})


@bp_turismo.route("/api/turismo/agenda_pdf", methods=["GET"])
def api_agenda_pdf():
    if not session.get("usuario_id"):
        return jsonify({"error": "Sin sesión"}), 401
    from flask import send_file
    import io
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    servicios = listar_servicios(desde=desde, hasta=hasta,
                                 cliente=request.args.get("cliente") or None)
    return send_file(io.BytesIO(generar_pdf_agenda(servicios, desde, hasta)),
                     mimetype="application/pdf", as_attachment=False,
                     download_name="agenda_turismo.pdf")


def generar_pdf_agenda(servicios, desde, hasta):
    """La agenda impresa, con el mismo orden de columnas que la planilla."""
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
                            topMargin=13*mm, bottomMargin=12*mm,
                            title="Agenda de turismo")
    S = getSampleStyleSheet()
    AZUL = colors.HexColor("#1E5A96")
    ROJO = colors.HexColor("#DC2641")
    GRIS = colors.HexColor("#666666")
    st_tit = ParagraphStyle("t", parent=S["Title"], fontSize=15, textColor=AZUL,
                            alignment=1, spaceAfter=1)
    st_per = ParagraphStyle("p", parent=S["Normal"], fontSize=9.5,
                            textColor=GRIS, alignment=1, spaceAfter=10)

    elems = [Paragraph("Agenda de Servicios de Turismo", st_tit)]
    elems.append(Paragraph(
        f"Del {desde or '...'} al {hasta or '...'}" if (desde or hasta)
        else "Todos los servicios agendados", st_per))

    if not servicios:
        elems.append(Paragraph("No hay servicios agendados en ese período.", S["Normal"]))
        doc.build(elems)
        return buf.getvalue()

    data = [["Fecha", "Hora", "Cliente", "OT Nº", "Salida", "Destino",
             "Coche", "Tripulación", "Día"]]
    for s in servicios:
        data.append([
            s.get("fecha", ""), s.get("hora", "") or "—",
            s.get("cliente", ""), s.get("ot_nr", "") or "—",
            (s.get("salida", "") or "")[:26], (s.get("destino", "") or "")[:26],
            s.get("coche_interno") or "A DEF",
            (s.get("tripulacion") or "A DEF")[:22],
            s.get("dia_servicio", ""),
        ])

    t = Table(data, repeatRows=1,
              colWidths=[21*mm, 15*mm, 34*mm, 22*mm, 48*mm, 48*mm,
                         18*mm, 38*mm, 22*mm])
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), AZUL),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 8),
        ("FONTSIZE", (0, 1), (-1, -1), 7.5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F6F3")]),
        ("ALIGN", (6, 0), (6, -1), "CENTER"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    # Lo que falta asignar se marca en rojo: es lo que hay que resolver
    for i, s in enumerate(servicios, start=1):
        if not (s.get("coche_interno") or "").strip():
            estilo.append(("TEXTCOLOR", (6, i), (6, i), ROJO))
            estilo.append(("FONTNAME", (6, i), (6, i), "Helvetica-Bold"))
        if not (s.get("tripulacion") or "").strip():
            estilo.append(("TEXTCOLOR", (7, i), (7, i), ROJO))
            estilo.append(("FONTNAME", (7, i), (7, i), "Helvetica-Bold"))
        if s.get("estado") == "cancelado":
            estilo.append(("TEXTCOLOR", (0, i), (-1, i), colors.HexColor("#AAAAAA")))
    t.setStyle(TableStyle(estilo))
    elems.append(t)

    sin = sum(1 for s in servicios
              if (s.get("sin_asignar") and s.get("estado") != "cancelado"))
    elems.append(Spacer(1, 9))
    elems.append(Paragraph(
        f"{len(servicios)} servicio(s)" +
        (f" · <font color='#DC2641'><b>{sin} sin coche o tripulación asignada</b></font>" if sin else ""),
        ParagraphStyle("f", parent=S["Normal"], fontSize=9.5, alignment=2)))

    doc.build(elems)
    return buf.getvalue()


def init_turismo_agenda(app):
    inicializar_agenda_turismo()
