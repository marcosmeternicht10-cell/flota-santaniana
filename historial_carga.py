"""
historial_carga.py — Carga retroactiva del historial en papel (La Santaniana)

El historial de los buses está en papel. Este módulo permite tipearlo al
sistema de forma rápida, bus por bus, con fecha retroactiva. La regla de
destino es la clave:

  - tipo 'correctivo'  → va a la tabla REAL `correctivos` (estado completado).
    Así el OEE y el dossier lo cuentan como falla, que es lo correcto.
  - cualquier otro tipo (preventivo, neumáticos, servicio, otro) → va a la
    tabla `historial_eventos`. Un cambio de aceite histórico NO es una falla
    y no debe ensuciar las métricas de confiabilidad.

El dossier lee ambas fuentes, así que todo lo cargado suma a los reportes.

Enganche en app.py (2 líneas, después de los otros blueprints):
    from historial_carga import bp_historial, init_historial_module
    init_historial_module(app)
    app.register_blueprint(bp_historial)
"""

from flask import Blueprint, request, jsonify, session
from db_compat import get_connection, USE_POSTGRES, OperationalError, columnas_de_tabla

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"

TIPOS_EVENTO = ["correctivo", "preventivo", "neumaticos", "servicio", "otro"]

bp_historial = Blueprint("historial_carga", __name__)


# ════════════════════════════════════════════════════════════════════════════
# TABLA
# ════════════════════════════════════════════════════════════════════════════

def inicializar_historial():
    """Crea la tabla de eventos históricos. Idempotente."""
    conn = get_connection()
    c = conn.cursor()
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS historial_eventos (
            id {PK},
            vehiculo_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            tipo TEXT NOT NULL DEFAULT 'otro',   -- preventivo | neumaticos | servicio | otro
            categoria TEXT DEFAULT '',           -- ej: 'Cambio de aceite', 'Rotación', libre
            descripcion TEXT NOT NULL,
            km REAL DEFAULT 0,
            costo REAL DEFAULT 0,
            taller TEXT DEFAULT '',
            observaciones TEXT DEFAULT '',
            cargado_por TEXT DEFAULT '',
            fecha_carga TEXT DEFAULT (date('now')),
            FOREIGN KEY (vehiculo_id) REFERENCES vehiculos(id)
        )
    """)
    conn.commit()
    conn.close()


def init_historial_module(app):
    inicializar_historial()


# ════════════════════════════════════════════════════════════════════════════
# LÓGICA
# ════════════════════════════════════════════════════════════════════════════

def agregar_evento(vehiculo_id, fecha, tipo, descripcion, categoria="",
                   km=0, costo=0, taller="", usuario=""):
    """Registra un evento histórico en su tabla de destino según el tipo.
    Devuelve (ok, {origen, id}) — 'origen' indica en qué tabla quedó,
    necesario para poder borrarlo si se cargó mal."""
    tipo = (tipo or "otro").lower().strip()
    if tipo not in TIPOS_EVENTO:
        tipo = "otro"
    descripcion = (descripcion or "").strip()
    if not descripcion:
        return False, "La descripción es obligatoria."

    conn = get_connection()
    try:
        if tipo == "correctivo":
            # A la tabla real de correctivos, como falla ya resuelta.
            # La categoría del papel (ej: "Motor") es el tipo_falla.
            cur = conn.execute("""
                INSERT INTO correctivos
                    (vehiculo_id, fecha, km, tipo_falla, descripcion,
                     reparacion, costo, taller, estado, observaciones)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (vehiculo_id, fecha, float(km or 0),
                  (categoria or "Otros").strip(), descripcion,
                  "", float(costo or 0), taller.strip(), "completado",
                  f"[Historial cargado por {usuario}]" if usuario else "[Historial]"))
            rid = cur.lastrowid
            conn.commit()
            return True, {"origen": "correctivos", "id": rid}
        else:
            cur = conn.execute("""
                INSERT INTO historial_eventos
                    (vehiculo_id, fecha, tipo, categoria, descripcion,
                     km, costo, taller, cargado_por)
                VALUES (?,?,?,?,?,?,?,?,?)
            """, (vehiculo_id, fecha, tipo, categoria.strip(), descripcion,
                  float(km or 0), float(costo or 0), taller.strip(), usuario))
            rid = cur.lastrowid
            conn.commit()
            return True, {"origen": "historial_eventos", "id": rid}
    finally:
        conn.close()


def obtener_historial_vehiculo(vehiculo_id, limite=100):
    """Todo lo cargado retroactivamente para un coche: eventos de la tabla
    propia + correctivos marcados como históricos. Más recientes primero."""
    conn = get_connection()
    eventos = conn.execute("""
        SELECT id, fecha, tipo, categoria, descripcion, km, costo, taller,
               cargado_por, 'historial_eventos' AS origen
        FROM historial_eventos WHERE vehiculo_id=?
    """, (vehiculo_id,)).fetchall()
    correctivos = conn.execute("""
        SELECT id, fecha, 'correctivo' AS tipo, tipo_falla AS categoria,
               descripcion, km, costo, taller, '' AS cargado_por,
               'correctivos' AS origen
        FROM correctivos
        WHERE vehiculo_id=? AND observaciones LIKE '[Historial%'
    """, (vehiculo_id,)).fetchall()
    conn.close()
    todos = [dict(r) for r in eventos] + [dict(r) for r in correctivos]
    todos.sort(key=lambda x: (x.get("fecha") or "", x.get("id") or 0), reverse=True)
    return todos[:limite]


def eliminar_evento(origen, evento_id):
    """Borra un evento cargado por error, de la tabla que corresponda."""
    if origen not in ("historial_eventos", "correctivos"):
        return False, "Origen inválido."
    conn = get_connection()
    if origen == "correctivos":
        # Solo permitir borrar correctivos que son de carga histórica
        row = conn.execute(
            "SELECT observaciones FROM correctivos WHERE id=?", (evento_id,)).fetchone()
        if not row or not str(row["observaciones"] or "").startswith("[Historial"):
            conn.close()
            return False, "Ese correctivo no es de carga histórica."
    conn.execute(f"DELETE FROM {origen} WHERE id=?", (evento_id,))
    conn.commit()
    conn.close()
    return True, "Evento eliminado."


def eventos_historial_periodo(vehiculo_id, desde, hasta):
    """Para el dossier: eventos históricos (no-correctivos) de un período."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT fecha, tipo, categoria, descripcion, km, costo, taller
        FROM historial_eventos
        WHERE vehiculo_id=? AND fecha BETWEEN ? AND ?
        ORDER BY fecha DESC
    """, (vehiculo_id, desde, hasta)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ════════════════════════════════════════════════════════════════════════════

def _puede_cargar():
    return session.get("rol") in ("admin", "taller", "compras")


@bp_historial.route("/api/historial_carga/<int:vid>", methods=["GET"])
def api_historial_vehiculo(vid):
    if not _puede_cargar():
        return jsonify({"error": "Sin permiso"}), 403
    return jsonify(obtener_historial_vehiculo(vid))


@bp_historial.route("/api/historial_carga", methods=["POST"])
def api_agregar_evento():
    if not _puede_cargar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    d = request.json or {}
    vid = d.get("vehiculo_id")
    fecha = (d.get("fecha") or "").strip()
    if not vid or not fecha:
        return jsonify({"ok": False, "msg": "Faltan coche o fecha"}), 400
    ok, res = agregar_evento(
        int(vid), fecha, d.get("tipo", "otro"), d.get("descripcion", ""),
        categoria=d.get("categoria", ""), km=d.get("km", 0),
        costo=d.get("costo", 0), taller=d.get("taller", ""),
        usuario=session.get("nombre") or session.get("usuario") or "")
    if not ok:
        return jsonify({"ok": False, "msg": res}), 400
    # Auditoría (import perezoso para evitar circular)
    try:
        from database import registrar_auditoria
        registrar_auditoria(
            usuario=session.get("nombre") or "?", rol=session.get("rol") or "",
            accion=f"Cargó evento histórico ({d.get('tipo','otro')}) del {fecha}",
            categoria="Historial", detalle=d.get("descripcion", "")[:120],
            referencia=f"vehiculo:{vid}")
    except Exception:
        pass
    return jsonify({"ok": True, **res})


@bp_historial.route("/api/historial_carga/<origen>/<int:eid>", methods=["DELETE"])
def api_eliminar_evento(origen, eid):
    if not _puede_cargar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    ok, msg = eliminar_evento(origen, eid)
    return jsonify({"ok": ok, "msg": msg}), (200 if ok else 400)


# ════════════════════════════════════════════════════════════════════════════
#  MÓDULO MANTENIMIENTOS — historia completa de cada coche
# ════════════════════════════════════════════════════════════════════════════
# Junta en una sola historia lo que hoy está repartido en cuatro lugares:
#   - lo cargado del libro de a bordo y del día a día (historial_eventos)
#   - los correctivos (incluye los que vienen de OT y del historial)
#   - los preventivos del plan (mantenimientos_realizados)
#   - las tareas completadas de las órdenes de trabajo, SALVO las de tipo
#     correctivo: esas el sistema ya las copia solo a correctivos y se
#     contarían dos veces.
# Pensado para ser liviano: la lista trae 10 coches por página y las
# estadísticas salen de consultas agrupadas, nunca de una consulta por coche.

POR_PAGINA_COCHES = 10
POR_PAGINA_HISTORIA = 20


def _fuentes(filtro_vid=None, desde=None, hasta=None):
    """La historia de mantenimiento de todas las fuentes como una sola
    consulta (UNION ALL), con los filtros pedidos. Devuelve (sql, params)."""
    partes, params = [], []

    def where(col_vid, col_fecha):
        cond, p = [], []
        if filtro_vid:
            cond.append(f"{col_vid} IN ({','.join('?' * len(filtro_vid))})")
            p += list(filtro_vid)
        if desde:
            cond.append(f"{col_fecha} >= ?"); p.append(desde)
        if hasta:
            cond.append(f"{col_fecha} <= ?"); p.append(hasta)
        return (" AND ".join(cond) or "1=1"), p

    w, p = where("h.vehiculo_id", "h.fecha")
    partes.append(f"""SELECT h.vehiculo_id, h.fecha, h.km, h.costo, h.tipo,
        h.categoria, h.descripcion, h.taller, 'historial_eventos' AS origen, h.id,
        1 AS de_historial
        FROM historial_eventos h WHERE {w}"""); params += p

    w, p = where("c.vehiculo_id", "c.fecha")
    partes.append(f"""SELECT c.vehiculo_id, c.fecha, c.km, c.costo, 'correctivo' AS tipo,
        c.tipo_falla AS categoria, c.descripcion, c.taller, 'correctivos' AS origen, c.id,
        CASE WHEN COALESCE(c.observaciones, '') LIKE '[Historial%' THEN 1 ELSE 0 END AS de_historial
        FROM correctivos c WHERE {w}"""); params += p

    w, p = where("m.vehiculo_id", "m.fecha")
    partes.append(f"""SELECT m.vehiculo_id, m.fecha, m.km, m.costo, 'preventivo' AS tipo,
        t.categoria, t.tarea AS descripcion, '' AS taller, 'plan' AS origen, m.id,
        0 AS de_historial
        FROM mantenimientos_realizados m JOIN tareas_plan t ON t.id = m.tarea_plan_id
        WHERE {w}"""); params += p

    w, p = where("o.vehiculo_id", "COALESCE(i.fecha_completado, o.fecha_apertura)")
    partes.append(f"""SELECT o.vehiculo_id, COALESCE(i.fecha_completado, o.fecha_apertura) AS fecha,
        o.km, i.costo, i.tipo, 'Orden de trabajo' AS categoria, i.descripcion,
        i.tecnico AS taller, 'ot' AS origen, i.id, 0 AS de_historial
        FROM ot_items i JOIN ordenes_trabajo o ON o.id = i.ot_id
        WHERE i.estado = 'completado' AND COALESCE(i.tipo, '') <> 'correctivo' AND {w}"""); params += p

    return " UNION ALL ".join(partes), params


def _grupo(tipo):
    """Para las estadísticas: preventivo, correctivo, neumáticos u otros."""
    t = (tipo or "").lower()
    if t in ("preventivo", "control"):
        return "preventivo"
    if t == "correctivo":
        return "correctivo"
    if t == "neumaticos":
        return "neumaticos"
    return "otros"


def _orden_coche(n):
    n = str(n or "").strip()
    return (0, int(n), "") if n.isdigit() else (1, 0, n.upper() or "~")


def lista_coches_mant(q="", pagina=1, por_pagina=POR_PAGINA_COCHES):
    """Una página de coches con el resumen de su historia de mantenimiento."""
    from datetime import date
    conn = get_connection()
    coches = [dict(r) for r in conn.execute(
        """SELECT id, n_interno, patente, marca, modelo FROM vehiculos
           WHERE COALESCE(activo, 1) = 1""").fetchall()]
    q = (q or "").strip().lower()
    if q:
        coches = [v for v in coches if q in
                  f"{v['n_interno'] or ''} {v['patente'] or ''} {v['marca'] or ''} {v['modelo'] or ''}".lower()]
    coches.sort(key=lambda v: _orden_coche(v["n_interno"]))
    total = len(coches)
    paginas = max(1, -(-total // por_pagina))
    pagina = min(max(1, pagina), paginas)
    pag = coches[(pagina - 1) * por_pagina: pagina * por_pagina]

    if pag:
        sql, params = _fuentes(filtro_vid=[v["id"] for v in pag])
        hace90 = date.fromordinal(date.today().toordinal() - 90).isoformat()
        filas = conn.execute(f"""
            SELECT vehiculo_id, COUNT(*) AS registros, MAX(fecha) AS ultimo,
                   MAX(km) AS km_max, COALESCE(SUM(costo), 0) AS costo,
                   SUM(CASE WHEN tipo = 'correctivo' THEN 1 ELSE 0 END) AS correctivos,
                   SUM(CASE WHEN fecha >= ? THEN 1 ELSE 0 END) AS ultimos_90
            FROM ({sql}) t GROUP BY vehiculo_id
        """, [hace90] + params).fetchall()
        por_vid = {r["vehiculo_id"]: dict(r) for r in filas}
        hoy = date.today()
        for v in pag:
            r = por_vid.get(v["id"], {})
            v["registros"] = int(r.get("registros") or 0)
            v["ultimo"] = r.get("ultimo")
            v["km"] = float(r.get("km_max") or 0)
            v["costo"] = float(r.get("costo") or 0)
            v["correctivos"] = int(r.get("correctivos") or 0)
            v["ultimos_90"] = int(r.get("ultimos_90") or 0)
            try:
                v["dias_desde"] = (hoy - date.fromisoformat(str(v["ultimo"])[:10])).days if v["ultimo"] else None
            except Exception:
                v["dias_desde"] = None
    conn.close()
    return {"coches": pag, "total": total, "pagina": pagina, "paginas": paginas,
            "por_pagina": por_pagina}


def historia_coche(vid, pagina=1, por_pagina=POR_PAGINA_HISTORIA, tipo=""):
    """La historia completa de un coche, más reciente primero, por páginas."""
    conn = get_connection()
    v = conn.execute("SELECT id, n_interno, patente, marca, modelo FROM vehiculos WHERE id=?",
                     (vid,)).fetchone()
    if not v:
        conn.close()
        return None
    sql, params = _fuentes(filtro_vid=[vid])
    resumen = conn.execute(f"""
        SELECT COUNT(*) AS registros, MAX(fecha) AS ultimo, MIN(fecha) AS primero,
               MAX(km) AS km_max, COALESCE(SUM(costo), 0) AS costo,
               SUM(CASE WHEN tipo IN ('preventivo','control') THEN 1 ELSE 0 END) AS preventivos,
               SUM(CASE WHEN tipo = 'correctivo' THEN 1 ELSE 0 END) AS correctivos
        FROM ({sql}) t""", params).fetchone()
    filtro, extra = "", []
    if tipo == "preventivo":
        filtro = "WHERE tipo IN ('preventivo','control')"
    elif tipo in ("correctivo", "neumaticos"):
        filtro, extra = "WHERE tipo = ?", [tipo]
    elif tipo == "otros":
        filtro = "WHERE tipo NOT IN ('preventivo','control','correctivo','neumaticos')"
    total = conn.execute(f"SELECT COUNT(*) AS n FROM ({sql}) t {filtro}", params + extra).fetchone()["n"]
    paginas = max(1, -(-int(total) // por_pagina))
    pagina = min(max(1, pagina), paginas)
    filas = conn.execute(f"""SELECT * FROM ({sql}) t {filtro}
                             ORDER BY fecha DESC, id DESC LIMIT ? OFFSET ?""",
                         params + extra + [por_pagina, (pagina - 1) * por_pagina]).fetchall()
    conn.close()
    items = []
    for r in filas:
        d = dict(r)
        d["grupo"] = _grupo(d["tipo"])
        # Se puede borrar lo que se cargó desde acá o desde "Cargar historial";
        # lo del plan y lo de las OT se corrige en su propia pantalla
        d["borrable"] = bool(d.pop("de_historial", 0))
        items.append(d)
    r = dict(resumen)
    return {"coche": dict(v), "items": items, "total": int(total), "pagina": pagina,
            "paginas": paginas,
            "resumen": {"registros": int(r["registros"] or 0), "ultimo": r["ultimo"],
                        "primero": r["primero"], "km": float(r["km_max"] or 0),
                        "costo": float(r["costo"] or 0),
                        "preventivos": int(r["preventivos"] or 0),
                        "correctivos": int(r["correctivos"] or 0)}}


def estadisticas_mant(meses=6):
    """Lo importante del área, para acompañar visualmente."""
    from datetime import date
    hoy = date.today()
    y, m = hoy.year, hoy.month - (meses - 1)
    while m <= 0:
        m += 12; y -= 1
    desde = date(y, m, 1).isoformat()
    hace30 = date.fromordinal(hoy.toordinal() - 30).isoformat()
    hace90 = date.fromordinal(hoy.toordinal() - 90).isoformat()
    conn = get_connection()
    sql, params = _fuentes(desde=desde)
    # Por mes y por tipo, en una consulta
    por_mes_tipo = conn.execute(f"""
        SELECT substr(CAST(fecha AS TEXT), 1, 7) AS mes, tipo, COUNT(*) AS n,
               COALESCE(SUM(costo), 0) AS costo
        FROM ({sql}) t GROUP BY 1, 2""", params).fetchall()
    meses_lista = []
    yy, mm = y, m
    for _ in range(meses):
        meses_lista.append(f"{yy:04d}-{mm:02d}")
        mm += 1
        if mm > 12:
            mm, yy = 1, yy + 1
    serie = {k: {"preventivo": 0, "correctivo": 0, "neumaticos": 0, "otros": 0} for k in meses_lista}
    totales = {"preventivo": 0, "correctivo": 0, "neumaticos": 0, "otros": 0}
    for r in por_mes_tipo:
        g = _grupo(r["tipo"])
        if r["mes"] in serie:
            serie[r["mes"]][g] += int(r["n"])
        totales[g] += int(r["n"])
    # Últimos 30 días
    sql30, p30 = _fuentes(desde=hace30)
    u30 = conn.execute(f"SELECT COUNT(*) AS n, COALESCE(SUM(costo),0) AS costo FROM ({sql30}) t", p30).fetchone()
    # Coches que más correctivos tuvieron en 90 días
    sql90, p90 = _fuentes(desde=hace90)
    top = conn.execute(f"""
        SELECT t.vehiculo_id, v.n_interno, v.patente, COUNT(*) AS n
        FROM ({sql90}) t JOIN vehiculos v ON v.id = t.vehiculo_id
        WHERE t.tipo = 'correctivo' GROUP BY t.vehiculo_id, v.n_interno, v.patente
        ORDER BY n DESC LIMIT 5""", p90).fetchall()
    # Coches activos sin ningún mantenimiento en 90 días
    activos = conn.execute("SELECT COUNT(*) AS n FROM vehiculos WHERE COALESCE(activo,1)=1").fetchone()["n"]
    con90 = conn.execute(f"SELECT COUNT(DISTINCT vehiculo_id) AS n FROM ({sql90}) t", p90).fetchone()["n"]
    conn.close()
    base = totales["preventivo"] + totales["correctivo"]
    return {
        "meses": [{"mes": k, **serie[k]} for k in meses_lista],
        "totales": totales,
        "pct_preventivo": round(totales["preventivo"] / base * 100) if base else None,
        "ultimos_30": {"registros": int(u30["n"] or 0), "costo": float(u30["costo"] or 0)},
        "sin_mant_90": max(0, int(activos) - int(con90)),
        "activos": int(activos),
        "top_correctivos": [dict(r) for r in top],
    }


def _puede_ver_mant():
    return session.get("rol") in ("admin", "taller", "compras", "auditor")


@bp_historial.route("/api/mant/coches", methods=["GET"])
def api_mant_coches():
    if not _puede_ver_mant():
        return jsonify({"error": "Sin permiso"}), 403
    try:
        pagina = int(request.args.get("pagina") or 1)
    except ValueError:
        pagina = 1
    return jsonify(lista_coches_mant(request.args.get("q", ""), pagina))


@bp_historial.route("/api/mant/coche/<int:vid>", methods=["GET"])
def api_mant_coche(vid):
    if not _puede_ver_mant():
        return jsonify({"error": "Sin permiso"}), 403
    try:
        pagina = int(request.args.get("pagina") or 1)
    except ValueError:
        pagina = 1
    d = historia_coche(vid, pagina, tipo=request.args.get("tipo", ""))
    if not d:
        return jsonify({"error": "No existe ese coche"}), 404
    return jsonify(d)


@bp_historial.route("/api/mant/estadisticas", methods=["GET"])
def api_mant_estadisticas():
    if not _puede_ver_mant():
        return jsonify({"error": "Sin permiso"}), 403
    return jsonify(estadisticas_mant())


def registros_flota(tipo, meses=6, pagina=1, por_pagina=POR_PAGINA_HISTORIA):
    """Los registros de un tipo (preventivo / correctivo) de toda la flota en
    los últimos meses, más recientes primero. Es lo que se abre al tocar las
    tarjetas de Preventivo y Correctivos: el mismo período que cuentan."""
    from datetime import date
    hoy = date.today()
    y, m = hoy.year, hoy.month - (meses - 1)
    while m <= 0:
        m += 12; y -= 1
    desde = date(y, m, 1).isoformat()
    sql, params = _fuentes(desde=desde)
    if tipo == "preventivo":
        filtro, extra = "t.tipo IN ('preventivo','control')", []
    else:
        filtro, extra = "t.tipo = ?", ["correctivo"]
    conn = get_connection()
    total = conn.execute(f"SELECT COUNT(*) AS n FROM ({sql}) t WHERE {filtro}",
                         params + extra).fetchone()["n"]
    paginas = max(1, -(-int(total) // por_pagina))
    pagina = min(max(1, pagina), paginas)
    filas = conn.execute(f"""
        SELECT t.*, v.n_interno, v.patente FROM ({sql}) t
        JOIN vehiculos v ON v.id = t.vehiculo_id
        WHERE {filtro} ORDER BY t.fecha DESC, t.id DESC LIMIT ? OFFSET ?""",
        params + extra + [por_pagina, (pagina - 1) * por_pagina]).fetchall()
    conn.close()
    items = []
    for r in filas:
        d = dict(r)
        d.pop("de_historial", None)
        d["grupo"] = _grupo(d["tipo"])
        items.append(d)
    return {"tipo": tipo, "desde": desde, "items": items, "total": int(total),
            "pagina": pagina, "paginas": paginas}


@bp_historial.route("/api/mant/registros", methods=["GET"])
def api_mant_registros():
    if not _puede_ver_mant():
        return jsonify({"error": "Sin permiso"}), 403
    tipo = request.args.get("tipo", "preventivo")
    if tipo not in ("preventivo", "correctivo"):
        return jsonify({"error": "Tipo inválido"}), 400
    try:
        pagina = int(request.args.get("pagina") or 1)
    except ValueError:
        pagina = 1
    return jsonify(registros_flota(tipo, pagina=pagina))
