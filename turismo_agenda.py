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

  - Un servicio puede llevar hasta 3 coches (el principal y adicionales si el
    grupo lo amerita), cada uno con su tripulación. Cada coche que falta
    definir cuenta como "a definir".

  - Un servicio tiene fecha de inicio y de fin: un viaje de varios días
    aparece en la agenda el día que sale y, los días siguientes, como "en
    viaje" (el coche y el chofer están afuera).
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

# Coches por servicio: el principal (vehiculo_id, coche_interno, tripulacion)
# y los adicionales (…_2, …_3)
MAX_COCHES = 3
SUFIJOS = {1: "", 2: "_2", 3: "_3"}


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
    # Fecha de fin y coches adicionales
    nuevas = [("fecha_fin", "TEXT DEFAULT ''"), ("cant_coches", "INTEGER DEFAULT 1")]
    for n in (2, 3):
        nuevas += [(f"vehiculo_id_{n}", "INTEGER"), (f"coche_interno_{n}", "TEXT DEFAULT ''"),
                   (f"tripulacion_{n}", "TEXT DEFAULT ''")]
    for col, tipo in nuevas:
        try:
            if USE_POSTGRES:
                c.execute(f"ALTER TABLE agenda_turismo ADD COLUMN IF NOT EXISTS {col} {tipo}")
            else:
                ya = {r["name"] for r in conn.execute("PRAGMA table_info(agenda_turismo)").fetchall()}
                if col not in ya:
                    c.execute(f"ALTER TABLE agenda_turismo ADD COLUMN {col} {tipo}")
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


def fecha_fin_de(s):
    """La fecha en que termina el servicio (la de inicio si no tiene)."""
    ini = str(s.get("fecha") or "")[:10]
    fin = str(s.get("fecha_fin") or "")[:10]
    return fin if fin and fin > ini else ini


def coches_de(s):
    """Los coches del servicio, cada uno con su tripulación (vacíos = a definir)."""
    try:
        cant = int(s.get("cant_coches") or 1)
    except (TypeError, ValueError):
        cant = 1
    for n in (3, 2):   # si un adicional tiene algo, cuenta aunque cant_coches diga menos
        suf = SUFIJOS[n]
        if (s.get("coche_interno" + suf) or "").strip() or (s.get("tripulacion" + suf) or "").strip():
            cant = max(cant, n)
            break
    cant = max(1, min(MAX_COCHES, cant))
    salida = []
    for n in range(1, cant + 1):
        suf = SUFIJOS[n]
        salida.append({"n": n, "vehiculo_id": s.get("vehiculo_id" + suf),
                       "coche_interno": (s.get("coche_interno" + suf) or "").strip(),
                       "tripulacion": (s.get("tripulacion" + suf) or "").strip()})
    return salida


def por_coche(s):
    """El servicio repetido por cada coche que lleva, con su coche y su
    tripulación en los campos de siempre (cada coche rinde por separado)."""
    return [{**s, "vehiculo_id": c["vehiculo_id"], "coche_interno": c["coche_interno"],
             "tripulacion": c["tripulacion"], "coche_n": c["n"]} for c in coches_de(s)]


def _plural(n, uno, varios):
    return f"{n} {uno if n == 1 else varios}"


def _enriquecer(s):
    """Agrega lo que se deduce: el día de la semana, los días que dura y si
    falta asignar algún coche o chofer."""
    import datetime as _dt
    s["dia_servicio"] = dia_de_la_semana(s.get("fecha", ""))
    s["fecha_fin"] = fecha_fin_de(s)
    try:
        s["dias"] = (_dt.date.fromisoformat(s["fecha_fin"]) - _dt.date.fromisoformat(s["fecha"][:10])).days + 1
    except Exception:
        s["dias"] = 1
    s["dia_fin"] = dia_de_la_semana(s["fecha_fin"]) if s["dias"] > 1 else ""
    s["coches"] = coches_de(s)
    s["cant_coches"] = len(s["coches"])
    sin_coche = sum(1 for c in s["coches"] if not c["coche_interno"])
    sin_chofer = sum(1 for c in s["coches"] if not c["tripulacion"])
    s["sin_asignar"] = bool(sin_coche or sin_chofer)
    if len(s["coches"]) == 1:
        s["falta"] = ("coche y chofer" if (sin_coche and sin_chofer)
                      else "coche" if sin_coche
                      else "chofer" if sin_chofer else "")
    else:
        partes = ([_plural(sin_coche, "coche", "coches")] if sin_coche else []) + \
                 ([_plural(sin_chofer, "chofer", "choferes")] if sin_chofer else [])
        s["falta"] = " y ".join(partes)
    return s


def listar_servicios(desde=None, hasta=None, cliente=None, estado=None,
                     solo_sin_asignar=False):
    """Los servicios agendados en un rango, del más próximo al más lejano."""
    q = """SELECT a.*, v.patente, v.marca, v.modelo
           FROM agenda_turismo a
           LEFT JOIN vehiculos v ON v.id = a.vehiculo_id
           WHERE 1=1"""
    params = []
    # Un viaje de varios días entra si alguno de sus días cae en el período
    if desde:
        q += " AND (CASE WHEN COALESCE(a.fecha_fin,'') > a.fecha THEN a.fecha_fin ELSE a.fecha END) >= ?"
        params.append(desde)
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


def _en_periodo(f, desde, hasta):
    return (not desde or f >= desde) and (not hasta or f <= hasta)


def agrupar_por_dia(servicios, desde=None, hasta=None):
    """Los servicios agrupados por fecha, que es como se lee una agenda. Un
    viaje de varios días sale el día que arranca y, los días siguientes, en
    "en_viaje" (día 2 de 3…)."""
    import datetime as _dt
    dias = {}

    def dia(f):
        return dias.setdefault(f, {"fecha": f, "dia_servicio": dia_de_la_semana(f),
                                   "servicios": [], "en_viaje": [], "sin_asignar": 0})
    for s in servicios:
        if _en_periodo(s["fecha"], desde, hasta):
            d = dia(s["fecha"])
            d["servicios"].append(s)
            if s["sin_asignar"] and s["estado"] != "cancelado":
                d["sin_asignar"] += 1
        if s.get("dias", 1) > 1 and s["estado"] != "cancelado":
            ini = _dt.date.fromisoformat(s["fecha"][:10])
            for k in range(1, s["dias"]):
                f = (ini + _dt.timedelta(days=k)).isoformat()
                if _en_periodo(f, desde, hasta):
                    dia(f)["en_viaje"].append({**s, "dia_n": k + 1, "continua": True})
    return sorted(dias.values(), key=lambda x: x["fecha"])


def resumen_agenda(servicios, desde=None, hasta=None):
    """Los números de arriba: cuántos hay, cuántos faltan asignar, por cliente.
    Cuenta los que salen en el período (los que vienen de antes están en viaje)."""
    activos = [s for s in servicios if s["estado"] != "cancelado" and _en_periodo(s["fecha"], desde, hasta)]
    por_cliente = {}
    for s in activos:
        c = por_cliente.setdefault(s["cliente"], {"cliente": s["cliente"], "servicios": 0})
        c["servicios"] += 1
    return {
        "total": len(activos),
        "sin_asignar": sum(1 for s in activos if s["sin_asignar"]),
        "coches": sum(s["cant_coches"] for s in activos),
        "varios_dias": sum(1 for s in activos if s.get("dias", 1) > 1),
        "completados": sum(1 for s in servicios if s["estado"] == "completado" and _en_periodo(s["fecha"], desde, hasta)),
        "cancelados": sum(1 for s in servicios if s["estado"] == "cancelado" and _en_periodo(s["fecha"], desde, hasta)),
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


def _int_o_none(v):
    try:
        return int(v) if str(v or "").strip() else None
    except (TypeError, ValueError):
        return None


def _columnas_coches(datos, actual=None):
    """Lo que viene del formulario → las columnas de los coches. Acepta la
    lista nueva ("coches": [{vehiculo_id, coche_interno, tripulacion}, …]) o
    los campos de siempre (un solo coche). Lo que no viene queda como estaba."""
    actual = actual or {}
    out = {}
    if isinstance(datos.get("coches"), list):
        lista = datos["coches"][:MAX_COCHES] or [{}]
        out["cant_coches"] = len(lista)
        for n in range(1, MAX_COCHES + 1):
            suf = SUFIJOS[n]
            c = lista[n - 1] if n <= len(lista) and isinstance(lista[n - 1], dict) else {}
            out["vehiculo_id" + suf] = _int_o_none(c.get("vehiculo_id"))
            out["coche_interno" + suf] = str(c.get("coche_interno") or "").strip()
            out["tripulacion" + suf] = str(c.get("tripulacion") or "").strip().upper()
        return out
    if "vehiculo_id" in datos:
        out["vehiculo_id"] = _int_o_none(datos.get("vehiculo_id"))
    if "coche_interno" in datos:
        out["coche_interno"] = str(datos.get("coche_interno") or "").strip()
    if "tripulacion" in datos:
        out["tripulacion"] = str(datos.get("tripulacion") or "").strip().upper()
    return out


def _coche_repetido(cols):
    """El mismo coche dos veces en un servicio es un error de carga."""
    if "cant_coches" not in cols:
        return None
    vistos = set()
    for n in range(1, cols["cant_coches"] + 1):
        c = (cols.get("coche_interno" + SUFIJOS[n]) or "").strip().upper()
        v = cols.get("vehiculo_id" + SUFIJOS[n])
        k = f"v{v}" if v else (f"c{c}" if c else "")
        if k:
            if k in vistos:
                return f"El coche {c or ''} está dos veces en el mismo servicio.".replace("coche  ", "coche ")
            vistos.add(k)
    return None


def _fecha_fin_valida(datos, fecha):
    """La fecha de fin: vacía o igual a la de inicio = un solo día."""
    fin = str(datos.get("fecha_fin") or "").strip()[:10]
    if not fin or fin == fecha:
        return "", None
    if fin < fecha:
        return None, "La fecha de fin es antes de la de inicio."
    return fin, None


def guardar_servicio(datos, usuario=""):
    """Agenda un servicio nuevo."""
    if not (datos.get("fecha") or "").strip():
        return False, "Falta la fecha del servicio.", None
    if not (datos.get("cliente") or "").strip():
        return False, "Falta el cliente.", None
    fin, err = _fecha_fin_valida(datos, datos["fecha"].strip())
    err = err or _coche_repetido(_columnas_coches(datos))
    if err:
        return False, err, None

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
    extra = _columnas_coches(datos)
    extra["fecha_fin"] = fin
    conn.execute(f"UPDATE agenda_turismo SET {', '.join(f'{k}=?' for k in extra)} WHERE id=?",
                 list(extra.values()) + [sid])
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

    fecha = v("fecha") or a["fecha"]
    if "fecha_fin" in datos:
        fin, err = _fecha_fin_valida(datos, fecha)
    else:
        fin, err = _fecha_fin_valida({"fecha_fin": a.get("fecha_fin")}, fecha)
        if err:   # se movió el inicio después del fin: queda de un día
            fin, err = "", None
    coches = _columnas_coches(datos, a)
    err = err or _coche_repetido(coches)
    if err:
        conn.close()
        return False, err
    conn.execute("""
        UPDATE agenda_turismo SET
            fecha=?, hora=?, cliente=?, ot_nr=?, salida=?, destino=?,
            estado=?, pasajeros=?, observaciones=?, fecha_fin=?
        WHERE id=?
    """, (
        fecha, v("hora"), v("cliente", True) or a["cliente"],
        v("ot_nr", True), v("salida"), v("destino"),
        v("estado") or a.get("estado", "agendado"),
        int(datos.get("pasajeros", a.get("pasajeros") or 0) or 0),
        v("observaciones"), fin, sid,
    ))
    if coches:
        conn.execute(f"UPDATE agenda_turismo SET {', '.join(f'{k}=?' for k in coches)} WHERE id=?",
                     list(coches.values()) + [sid])
    conn.commit()
    conn.close()
    return True, "Servicio actualizado."


def asignar(sid, vehiculo_id=None, coche_interno="", tripulacion="", coches=None):
    """Asigna coche y chofer (o los coches, si lleva varios) a un servicio que
    estaba en 'a definir'. Es la acción más frecuente, por eso va aparte del
    editar completo."""
    conn = get_connection()
    fila = conn.execute("SELECT id FROM agenda_turismo WHERE id=?", (sid,)).fetchone()
    if not fila:
        conn.close()
        return False, "No encontré ese servicio."
    datos = {"coches": coches} if isinstance(coches, list) else \
        {"vehiculo_id": vehiculo_id, "coche_interno": coche_interno, "tripulacion": tripulacion}
    cols = _columnas_coches(datos)
    err = _coche_repetido(cols)
    if err:
        conn.close()
        return False, err
    conn.execute(f"UPDATE agenda_turismo SET {', '.join(f'{k}=?' for k in cols)} WHERE id=?",
                 list(cols.values()) + [sid])
    conn.commit()
    conn.close()
    return True, ("Coches y tripulación asignados." if isinstance(coches, list) and len(coches) > 1
                  else "Coche y tripulación asignados.")


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
    """Las tripulaciones ya usadas (en cualquiera de los coches), para no
    reescribir el nombre cada vez."""
    conn = get_connection()
    veces = {}
    try:
        for col in ("tripulacion", "tripulacion_2", "tripulacion_3"):
            for r in conn.execute(f"""SELECT {col} AS t, COUNT(*) AS n FROM agenda_turismo
                                      WHERE COALESCE({col},'') <> '' GROUP BY {col}""").fetchall():
                veces[r["t"]] = veces.get(r["t"], 0) + int(r["n"])
    finally:
        conn.close()
    return [t for t, _ in sorted(veces.items(), key=lambda x: (-x[1], x[0]))]


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
    desde = request.args.get("desde") or None
    hasta = request.args.get("hasta") or None
    return jsonify({
        "servicios": servicios,
        "dias": agrupar_por_dia(servicios, desde, hasta),
        "resumen": resumen_agenda(servicios, desde, hasta),
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
                          d.get("tripulacion", ""), d.get("coches"))
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
        cs = s.get("coches") or coches_de(s)
        varios_dias = s.get("dias", 1) > 1
        data.append([
            s.get("fecha", "") + (f"\nal {s['fecha_fin']}" if varios_dias else ""),
            s.get("hora", "") or "—",
            s.get("cliente", ""), s.get("ot_nr", "") or "—",
            (s.get("salida", "") or "")[:26], (s.get("destino", "") or "")[:26],
            "\n".join(c["coche_interno"] or "A DEF" for c in cs),
            "\n".join((c["tripulacion"] or "A DEF")[:22] for c in cs),
            s.get("dia_servicio", "") + (f"\na {s.get('dia_fin', '')}\n({s['dias']} días)" if varios_dias else ""),
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
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]
    # Lo que falta asignar se marca en rojo: es lo que hay que resolver
    for i, s in enumerate(servicios, start=1):
        cs = s.get("coches") or coches_de(s)
        if any(not c["coche_interno"] for c in cs):
            estilo.append(("TEXTCOLOR", (6, i), (6, i), ROJO))
            estilo.append(("FONTNAME", (6, i), (6, i), "Helvetica-Bold"))
        if any(not c["tripulacion"] for c in cs):
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
