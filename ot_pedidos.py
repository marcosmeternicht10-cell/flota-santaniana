"""
ot_pedidos.py — Pedidos de OT de los choferes (La Santaniana)

Lo que reportan los choferes de viaje ya no entra directo a la OT del coche:
queda como PEDIDO para que los encargados lo miren, decidan y prioricen. Si
todo lo que se reporta se hace OT, el taller se llena y es un caos.

Cada línea del reporte es un pedido (un problema). Para cada uno el encargado:

  - lo pasa a la OT del coche, con su prioridad (urgente, alta, normal, baja)
  - lo deja para más adelante (en espera, con fecha para volver a mirarlo)
  - lo descarta, con el motivo (repetido, ya está hecho, no es falla…)

Para decidir tiene a mano: la prioridad que sugiere el sistema por lo que
dice el texto (frenos, dirección, humo… urgente; cortina, radio… baja), si ese
problema ya se reportó o se trabajó en el coche hace poco, la OT abierta del
coche con cuántos trabajos tiene, y si el coche sale hoy o mañana en el
tráfico. El chofer ve en su celular en qué quedó cada cosa.

Enganche en app.py:
    from ot_pedidos import bp_ot_pedidos, init_ot_pedidos
    init_ot_pedidos()
    app.register_blueprint(bp_ot_pedidos)
"""

import base64
import re
import unicodedata
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, session, Response
from db_compat import get_connection, USE_POSTGRES

from hora_local import hoy, ahora_iso

bp_ot_pedidos = Blueprint("ot_pedidos", __name__)

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
ESTADOS = ("nuevo", "espera", "aceptado", "descartado")
PRIORIDADES = ("urgente", "alta", "normal", "baja")
MOTIVOS_DESCARTE = ["Repetido", "Ya está hecho", "No es una falla", "No corresponde al taller", "No se encontró la falla"]
DIAS_REPETIDO = 60

# Lo que el texto deja ver: la seguridad primero. Es una sugerencia: decide el encargado.
REGLAS_PRIORIDAD = [
    ("urgente", [
        (r"no frena|frena mal|(?<!luz de )(?<!luces de )fren[oa]s?\b|pastilla|disco de freno|liquido de freno", "frenos"),
        (r"direcci[oó]n|volante|barra de direcci", "dirección"),
        (r"humo|fuego|incendi|olor a quemad|chispa|cortocircuit", "humo o fuego"),
        (r"recalient|calienta|temperatura|se apaga|se para el motor|no arranca", "motor"),
        (r"rueda floja|bul[oó]n|tuerca de rueda|revent|cubierta (lisa|rota)|neum[aá]tico (liso|roto)", "ruedas"),
        (r"(?:pierd\w*|perdid\w*|fuga) (?:de )?aire|sin aire", "aire de frenos"),
        (r"(?:pierd\w*|perdid\w*|fuga) (?:de )?(?:combustible|gasoil|diesel)|olor a gasoil", "combustible"),
        (r"embrague|no entra (?:la )?marcha|caja de cambio|se sale la marcha", "embrague o caja"),
        (r"suspensi[oó]n rota|eje|el[aá]stico roto|amortiguador roto|muelle rot", "suspensión"),
    ]),
    ("alta", [
        (r"pierd|perdid|fuga|gotea|chorrea|tira aceite|tira agua", "pérdida"),
        (r"luz de freno|luces de freno|faro|luces? delanter|luz trasera|guiñ|giro|baliza", "luces"),
        (r"puerta|parabrisas|vidrio|espejo|limpiaparabrisas|escobilla", "seguridad"),
        (r"ruido|golpe|vibra|tiembla|zumba|chirr", "ruido"),
        (r"aire acondicionado|a/?a\b|no enfr[ií]a|calefacc", "aire acondicionado"),
        (r"bater[ií]a|no carga|alternador|arranque", "eléctrico"),
        (r"tac[oó]grafo|cron[oó]tac", "tacógrafo"),
        (r"neum[aá]tic|cubierta|goma|pinchad", "neumáticos"),
    ]),
    ("baja", [
        (r"asiento|cortina|tapizad|apoyabrazo|portaequipaje|bandeja|cinta|alfombra", "comodidad"),
        (r"radio|est[eé]reo|parlante|tv\b|televis|pantalla|wifi|usb|enchufe", "entretenimiento"),
        (r"limpieza|lavar|pintura|ray[oó]n|calcoman|logo|stiker|sticker|est[eé]tic", "estética"),
        (r"luz interior|luces interiores|lucecita|lampara de lectura", "luz interior"),
    ]),
]

# Palabras que no sirven para decir si dos reportes hablan de lo mismo
VACIAS = set("""de del la las el los un una unos unas y o a al en con sin por para que se le lo
no si ya hay esta este esto muy mas más poco cuando donde lado derecho izquierdo atras atrás
adelante delante trasero trasera delantero delantera cambiar cambio revisar revision revisión
arreglar ver mirar hacer problema coche bus colectivo motor anda funciona hace tiene favor
tambien también otra otro nuevo nueva falta poner sacar pierde pierden perdida perdiendo rompio
rompió roto rota rotos rotas falla fallas mucho bien esta está quemada quemado quemadas suelto
suelta flojo floja dura duro chofer pasajero pasajeros""".split())


def _rollback(conn):
    try:
        conn.rollback()
    except Exception:
        pass


def _agregar_columna(conn, tabla, col, tipo):
    try:
        if USE_POSTGRES:
            conn.execute(f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS {col} {tipo}")
        else:
            ya = {r["name"] for r in conn.execute(f"PRAGMA table_info({tabla})").fetchall()}
            if col not in ya:
                conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {tipo}")
        conn.commit()
    except Exception:
        _rollback(conn)


def init_ot_pedidos():
    conn = get_connection()
    try:
        for sql in (
            f"""CREATE TABLE IF NOT EXISTS ot_pedido_reportes (
                id {PK},
                vehiculo_id INTEGER NOT NULL,
                chofer TEXT DEFAULT '',
                km REAL DEFAULT 0,
                fecha TEXT NOT NULL,
                creado_el TEXT DEFAULT '',
                fotos_pasadas INTEGER DEFAULT 0)""",
            f"""CREATE TABLE IF NOT EXISTS ot_pedidos (
                id {PK},
                reporte_id INTEGER NOT NULL,
                vehiculo_id INTEGER NOT NULL,
                descripcion TEXT NOT NULL,
                tipo TEXT DEFAULT 'otro',
                sugerida TEXT DEFAULT 'normal',
                sugerida_por TEXT DEFAULT '',
                prioridad TEXT DEFAULT '',
                estado TEXT DEFAULT 'nuevo',
                motivo TEXT DEFAULT '',
                nota TEXT DEFAULT '',
                revisar_el TEXT DEFAULT '',
                decidido_por TEXT DEFAULT '',
                decidido_el TEXT DEFAULT '',
                ot_id INTEGER,
                item_id INTEGER)""",
            f"""CREATE TABLE IF NOT EXISTS ot_pedido_fotos (
                id {PK},
                reporte_id INTEGER NOT NULL,
                datos TEXT NOT NULL,
                nombre TEXT DEFAULT '')""",
            "CREATE INDEX IF NOT EXISTS ix_ot_pedidos_estado ON ot_pedidos (estado)",
            "CREATE INDEX IF NOT EXISTS ix_ot_pedidos_vehiculo ON ot_pedidos (vehiculo_id)",
            "CREATE INDEX IF NOT EXISTS ix_ot_pedidos_reporte ON ot_pedidos (reporte_id)",
            "CREATE INDEX IF NOT EXISTS ix_ot_pedido_fotos_rep ON ot_pedido_fotos (reporte_id)",
        ):
            try:
                conn.execute(sql)
                conn.commit()
            except Exception:
                _rollback(conn)
        # La prioridad que se le dio al pasar a la OT (para verla en la OT)
        _agregar_columna(conn, "ot_items", "prioridad", "TEXT DEFAULT ''")
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# ANÁLISIS: prioridad sugerida y repetidos
# ════════════════════════════════════════════════════════════════════════════

def _norm(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def sugerir_prioridad(texto):
    """(prioridad, por qué) según lo que dice el texto."""
    t = _norm(texto)
    for prioridad, reglas in REGLAS_PRIORIDAD:
        for patron, por in reglas:
            if re.search(_norm(patron), t):
                return prioridad, por
    return "normal", ""


def _palabras(texto):
    """Las palabras que dicen de qué se trata (sin las de relleno)."""
    t = re.sub(r"[^a-z0-9ñ ]+", " ", _norm(texto))
    out = set()
    for w in t.split():
        if len(w) < 4 or w in VACIAS or w.isdigit():
            continue
        out.add(w[:4])          # "frena"/"frenos", "puerta"/"puertas" cuentan igual
    return out


def _parecidos(texto, candidatos):
    """Los candidatos (dict con descripcion) que hablan de lo mismo."""
    p = _palabras(texto)
    if not p:
        return []
    return [c for c in candidatos if p & _palabras(c["descripcion"])]


# ════════════════════════════════════════════════════════════════════════════
# CREAR (desde el celular del chofer)
# ════════════════════════════════════════════════════════════════════════════

def crear_reporte(vehiculo_id, items, chofer, km=0, fotos=None):
    """Guarda lo que mandó el chofer como pedidos (uno por problema).
    Devuelve el id del reporte."""
    conn = get_connection()
    try:
        cur = conn.execute("""INSERT INTO ot_pedido_reportes (vehiculo_id, chofer, km, fecha, creado_el)
                              VALUES (?,?,?,?,?)""", (int(vehiculo_id), (chofer or "")[:80], float(km or 0), hoy(), ahora_iso()))
        rid = cur.lastrowid
        for it in items:
            desc = " ".join(str(it.get("descripcion") or "").split())[:300]
            if not desc:
                continue
            sug, por = sugerir_prioridad(desc)
            conn.execute("""INSERT INTO ot_pedidos (reporte_id, vehiculo_id, descripcion, tipo, sugerida, sugerida_por, estado)
                            VALUES (?,?,?,?,?,?, 'nuevo')""", (rid, int(vehiculo_id), desc, it.get("tipo") or "otro", sug, por))
        for i, f in enumerate((fotos or [])[:3]):
            if f and str(f).startswith("data:image/") and len(f) < 800000:
                conn.execute("INSERT INTO ot_pedido_fotos (reporte_id, datos, nombre) VALUES (?,?,?)",
                             (rid, f, f"foto_{i + 1}.jpg"))
        conn.commit()
        return rid
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# LA BANDEJA (para los encargados)
# ════════════════════════════════════════════════════════════════════════════

ORDEN_PRIO = {"urgente": 0, "alta": 1, "normal": 2, "baja": 3}


def _prio(p):
    return p.get("prioridad") or p.get("sugerida") or "normal"


def _salidas_del_coche(conn, numeros, desde, hasta):
    """Las salidas del tráfico (nacional e internacional) de esos coches entre
    esas fechas: {n_interno: [{fecha, hora, destino, tipo}]}"""
    out = {}
    if not numeros:
        return out
    try:
        m = ",".join("?" * len(numeros))
        for r in conn.execute(f"""SELECT s.coche, s.hora, s.destino, d.fecha, COALESCE(d.tipo,'nacional') AS tipo
                                  FROM trafico_salidas s JOIN trafico_dias d ON d.id = s.dia_id
                                  WHERE d.fecha >= ? AND d.fecha <= ? AND s.coche IN ({m})
                                  ORDER BY d.fecha, s.hora""", [desde, hasta] + list(numeros)).fetchall():
            out.setdefault(str(r["coche"]).strip(), []).append(
                {"fecha": r["fecha"], "hora": r["hora"] or "", "destino": r["destino"] or "", "tipo": r["tipo"]})
    except Exception:
        _rollback(conn)
    return out


def bandeja(estado="nuevo", q=""):
    estado = estado if estado in ESTADOS else "nuevo"
    conn = get_connection()
    try:
        sql = """SELECT p.*, r.chofer, r.km, r.fecha, r.creado_el, v.n_interno, v.patente, v.marca, v.modelo
                 FROM ot_pedidos p JOIN ot_pedido_reportes r ON r.id = p.reporte_id
                 JOIN vehiculos v ON v.id = p.vehiculo_id WHERE p.estado=?"""
        params = [estado]
        if estado in ("aceptado", "descartado"):
            sql += " AND COALESCE(p.decidido_el, '') >= ?"
            params.append((date.fromisoformat(hoy()) - timedelta(days=45)).isoformat())
        filas = [dict(r) for r in conn.execute(sql + " ORDER BY r.creado_el DESC, p.id", params).fetchall()]
        if q:
            qn = _norm(q)
            filas = [f for f in filas if qn in _norm(f"{f['n_interno']} {f['patente']} {f['descripcion']} {f['chofer']}")]
        conteos = {e: 0 for e in ESTADOS}
        for r in conn.execute("SELECT estado, COUNT(*) AS n FROM ot_pedidos GROUP BY estado").fetchall():
            if r["estado"] in conteos:
                conteos[r["estado"]] = int(r["n"])
        urgentes = conn.execute("""SELECT COUNT(*) AS n FROM ot_pedidos WHERE estado='nuevo'
                                   AND COALESCE(NULLIF(prioridad,''), sugerida)='urgente'""").fetchone()["n"]
        vids = sorted({f["vehiculo_id"] for f in filas})
        fotos = {}
        reportes = sorted({f["reporte_id"] for f in filas})
        if reportes:
            m = ",".join("?" * len(reportes))
            for r in conn.execute(f"SELECT id, reporte_id FROM ot_pedido_fotos WHERE reporte_id IN ({m}) ORDER BY id",
                                  reportes).fetchall():
                fotos.setdefault(r["reporte_id"], []).append(r["id"])
        # Para analizar: lo que ya se pidió o se trabajó en el coche hace poco
        historia = {}
        abiertas = {}
        if vids and estado in ("nuevo", "espera"):
            m = ",".join("?" * len(vids))
            desde = (date.fromisoformat(hoy()) - timedelta(days=DIAS_REPETIDO)).isoformat()
            for r in conn.execute(f"""SELECT i.id, o.vehiculo_id, i.descripcion, i.estado, COALESCE(i.fecha, o.fecha_apertura) AS fecha,
                                             o.id AS ot_id, 'ot' AS fuente
                                      FROM ot_items i JOIN ordenes_trabajo o ON o.id = i.ot_id
                                      WHERE o.vehiculo_id IN ({m}) AND COALESCE(i.fecha, o.fecha_apertura) >= ?""",
                                  vids + [desde]).fetchall():
                historia.setdefault(r["vehiculo_id"], []).append(dict(r))
            for r in conn.execute(f"""SELECT p.id, p.vehiculo_id, p.descripcion, p.estado, r.fecha, p.motivo, 'pedido' AS fuente
                                      FROM ot_pedidos p JOIN ot_pedido_reportes r ON r.id = p.reporte_id
                                      WHERE p.vehiculo_id IN ({m}) AND r.fecha >= ?""", vids + [desde]).fetchall():
                historia.setdefault(r["vehiculo_id"], []).append(dict(r))
            import ot_unica
            for vid in vids:
                oid = ot_unica.ot_abierta_de(conn, vid)
                if oid:
                    o = conn.execute("SELECT id, ot_grupo FROM ordenes_trabajo WHERE id=?", (oid,)).fetchone()
                    c = conn.execute("""SELECT COUNT(*) AS n, SUM(CASE WHEN estado='completado' THEN 0 ELSE 1 END) AS p,
                                               SUM(CASE WHEN estado<>'completado' AND COALESCE(prioridad,'')='urgente' THEN 1 ELSE 0 END) AS u
                                        FROM ot_items WHERE ot_id=?""", (oid,)).fetchone()
                    abiertas[vid] = {"id": oid, "numero": o["ot_grupo"] or oid, "trabajos": int(c["n"] or 0),
                                     "pendientes": int(c["p"] or 0), "urgentes": int(c["u"] or 0)}
        numeros = sorted({str(f["n_interno"]).strip() for f in filas if f.get("n_interno")})
        h = hoy()
        salidas = _salidas_del_coche(conn, numeros, h, (date.fromisoformat(h) + timedelta(days=1)).isoformat()) \
            if estado in ("nuevo", "espera") else {}
    finally:
        conn.close()

    coches = {}
    for f in filas:
        c = coches.setdefault(f["vehiculo_id"], {
            "vehiculo_id": f["vehiculo_id"], "n_interno": f["n_interno"], "patente": f["patente"],
            "modelo": f"{f['marca'] or ''} {f['modelo'] or ''}".strip(),
            "ot_abierta": abiertas.get(f["vehiculo_id"]),
            "salidas": salidas.get(str(f["n_interno"] or "").strip(), [])[:4],
            "pedidos": []})
        f["prioridad_final"] = _prio(f)
        f["fotos"] = fotos.get(f["reporte_id"], [])
        try:
            f["dias"] = (date.fromisoformat(h) - date.fromisoformat(f["fecha"])).days
        except Exception:
            f["dias"] = 0
        otros = [x for x in historia.get(f["vehiculo_id"], [])
                 if not (x["fuente"] == "pedido" and (x["id"] == f["id"] or x["id"] in {y["id"] for y in filas if y["reporte_id"] == f["reporte_id"]}))
                 and not (x["fuente"] == "ot" and x["id"] == f.get("item_id"))]
        par = _parecidos(f["descripcion"], otros)
        f["repetido"] = [{"fecha": x["fecha"], "txt": x["descripcion"], "fuente": x["fuente"],
                          "estado": x.get("estado"), "ot_id": x.get("ot_id")} for x in
                         sorted(par, key=lambda x: str(x["fecha"]), reverse=True)][:4]
        for k in ("creado_el",):
            f[k] = f[k] or ""
        c["pedidos"].append(f)
    lista = list(coches.values())
    for c in lista:
        c["pedidos"].sort(key=lambda p: (ORDEN_PRIO.get(p["prioridad_final"], 2), -(p["dias"] or 0), p["id"]))
        c["peor"] = min((ORDEN_PRIO.get(p["prioridad_final"], 2) for p in c["pedidos"]), default=2)
        c["sale_pronto"] = bool(c["salidas"])
    if estado in ("nuevo", "espera"):
        lista.sort(key=lambda c: (c["peor"], not c["sale_pronto"], -max(p["dias"] or 0 for p in c["pedidos"]),
                                  str(c["n_interno"] or "")))
    else:
        lista.sort(key=lambda c: max((p["decidido_el"] or "") for p in c["pedidos"]), reverse=True)
    return {"ok": True, "estado": estado, "coches": lista, "conteos": conteos, "urgentes": int(urgentes or 0),
            "motivos": MOTIVOS_DESCARTE, "hoy": h}


# ════════════════════════════════════════════════════════════════════════════
# DECIDIR
# ════════════════════════════════════════════════════════════════════════════

def _quien():
    return session.get("nombre") or session.get("usuario") or ""


def _pasar_a_ot(conn, pedidos, prioridad):
    """Pasa los pedidos a la OT abierta de cada coche (o le abre una)."""
    import ot_unica
    from database import crear_ot
    h = hoy()
    hechos = []
    por_coche = {}
    for p in pedidos:
        por_coche.setdefault(p["vehiculo_id"], []).append(p)
    for vid, ps in por_coche.items():
        oid = ot_unica.ot_abierta_de(conn, vid)
        if not oid:
            primero = ps[0]
            conn.commit()                  # crear_ot usa su propia conexión
            oid = crear_ot(vid, h, km=primero.get("km") or 0, conductor=primero.get("chofer") or "",
                           procedencia="Pedido de chofer",
                           observaciones="Abierta al aprobar pedidos de los choferes.", items=[])
        for p in ps:
            prio = prioridad or _prio(p)
            ids = ot_unica.agregar_items(oid, [{"descripcion": p["descripcion"], "tipo": p.get("tipo") or "control",
                                                "estado": "pendiente"}],
                                         origen="chofer", reportado_por=p.get("chofer") or "", fecha=h, conn=conn)
            iid = ids[0] if ids else None
            if iid:
                f = p.get("fecha") or ""
                obs = f"Pedido de {p.get('chofer') or 'un chofer'} del {f[8:10]}/{f[5:7]}" if f else "Pedido de un chofer"
                conn.execute("UPDATE ot_items SET prioridad=?, observaciones=? WHERE id=?", (prio, obs, iid))
            conn.execute("""UPDATE ot_pedidos SET estado='aceptado', prioridad=?, ot_id=?, item_id=?,
                            decidido_por=?, decidido_el=?, motivo='' WHERE id=?""",
                         (prio, oid, iid, _quien()[:80], ahora_iso(), p["id"]))
            ot_unica.subir_km(conn, oid, p.get("km") or 0)
            hechos.append({"pedido": p["id"], "ot_id": oid, "item_id": iid})
        # Las fotos del reporte van a la OT una sola vez
        for rid in {p["reporte_id"] for p in ps}:
            r = conn.execute("SELECT fotos_pasadas FROM ot_pedido_reportes WHERE id=?", (rid,)).fetchone()
            if r and not int(r["fotos_pasadas"] or 0):
                for fo in conn.execute("SELECT datos, nombre FROM ot_pedido_fotos WHERE reporte_id=? ORDER BY id",
                                       (rid,)).fetchall():
                    conn.execute("INSERT INTO ot_fotos (ot_id, datos, nombre, fecha) VALUES (?,?,?,?)",
                                 (oid, fo["datos"], fo["nombre"], ahora_iso()))
                conn.execute("UPDATE ot_pedido_reportes SET fotos_pasadas=1 WHERE id=?", (rid,))
    return hechos


def decidir(ids, accion, prioridad="", motivo="", revisar_el="", nota=""):
    ids = [int(i) for i in ids or [] if str(i).isdigit()]
    if not ids:
        return False, "Elegí al menos un pedido", None
    if prioridad and prioridad not in PRIORIDADES:
        return False, "Esa prioridad no existe", None
    conn = get_connection()
    try:
        m = ",".join("?" * len(ids))
        pedidos = [dict(r) for r in conn.execute(
            f"""SELECT p.*, r.chofer, r.km, r.fecha FROM ot_pedidos p JOIN ot_pedido_reportes r ON r.id = p.reporte_id
                WHERE p.id IN ({m})""", ids).fetchall()]
        if not pedidos:
            return False, "Esos pedidos ya no existen", None
        res = None
        if accion == "aceptar":
            ya = [p for p in pedidos if p["estado"] == "aceptado"]
            pedidos = [p for p in pedidos if p["estado"] != "aceptado"]
            if not pedidos:
                return False, "Ya estaban en la OT", None
            res = _pasar_a_ot(conn, pedidos, prioridad)
            msg = (f"{len(res)} pasado{'s' if len(res) != 1 else ''} a la OT"
                   + (f" ({len(ya)} ya estaba{'n' if len(ya) != 1 else ''})" if ya else ""))
        elif accion == "esperar":
            if any(p["estado"] == "aceptado" for p in pedidos):
                return False, "Alguno ya está en la OT: se saca desde la OT", None
            conn.execute(f"""UPDATE ot_pedidos SET estado='espera', revisar_el=?, prioridad=COALESCE(NULLIF(?, ''), prioridad),
                             nota=CASE WHEN ?<>'' THEN ? ELSE nota END, decidido_por=?, decidido_el=?, motivo=''
                             WHERE id IN ({m})""",
                         [str(revisar_el or "")[:10], prioridad, nota, nota[:200], _quien()[:80], ahora_iso()] + ids)
            msg = f"{len(ids)} para más adelante"
        elif accion == "descartar":
            motivo = " ".join(str(motivo or "").split())[:120]
            if not motivo:
                return False, "Poné por qué no se hace", None
            if any(p["estado"] == "aceptado" for p in pedidos):
                return False, "Alguno ya está en la OT: se saca desde la OT", None
            conn.execute(f"""UPDATE ot_pedidos SET estado='descartado', motivo=?, decidido_por=?, decidido_el=?
                             WHERE id IN ({m})""", [motivo, _quien()[:80], ahora_iso()] + ids)
            msg = f"{len(ids)} descartado{'s' if len(ids) != 1 else ''}"
        elif accion == "reabrir":
            if any(p["estado"] == "aceptado" for p in pedidos):
                return False, "Lo que ya está en la OT se maneja desde la OT", None
            conn.execute(f"""UPDATE ot_pedidos SET estado='nuevo', motivo='', revisar_el='', decidido_por='', decidido_el=''
                             WHERE id IN ({m})""", ids)
            msg = "Vuelve a pedidos nuevos"
        else:
            return False, "No sé qué hacer con eso", None
        conn.commit()
    except Exception:
        _rollback(conn)
        raise
    finally:
        conn.close()
    try:
        from database import registrar_auditoria
        nombres = {"aceptar": "Pasó a la OT", "esperar": "Dejó para más adelante", "descartar": "Descartó", "reabrir": "Reabrió"}
        registrar_auditoria(usuario=_quien() or "?", rol=session.get("rol") or "",
                            accion=f"{nombres.get(accion, accion)} {len(ids)} pedido{'s' if len(ids) != 1 else ''} de choferes",
                            categoria="Órdenes de Trabajo", detalle=(motivo or prioridad or "")[:200])
    except Exception:
        pass
    return True, msg, res


def poner(pid, prioridad=None, nota=None):
    conn = get_connection()
    try:
        p = conn.execute("SELECT id, estado, item_id FROM ot_pedidos WHERE id=?", (pid,)).fetchone()
        if not p:
            return False, "Ese pedido no existe"
        if prioridad is not None:
            if prioridad and prioridad not in PRIORIDADES:
                return False, "Esa prioridad no existe"
            conn.execute("UPDATE ot_pedidos SET prioridad=? WHERE id=?", (prioridad, pid))
            if p["item_id"]:
                conn.execute("UPDATE ot_items SET prioridad=? WHERE id=?", (prioridad, p["item_id"]))
        if nota is not None:
            conn.execute("UPDATE ot_pedidos SET nota=? WHERE id=?", (" ".join(str(nota).split())[:200], pid))
        conn.commit()
        return True, "Guardado"
    finally:
        conn.close()


def pendientes():
    """Para el menú: cuántos pedidos nuevos hay y cuántos urgentes, y los en
    espera que ya hay que volver a mirar."""
    conn = get_connection()
    try:
        r = conn.execute("""SELECT COUNT(*) AS n,
                                   SUM(CASE WHEN COALESCE(NULLIF(prioridad,''), sugerida)='urgente' THEN 1 ELSE 0 END) AS u
                            FROM ot_pedidos WHERE estado='nuevo'""").fetchone()
        v = conn.execute("""SELECT COUNT(*) AS n FROM ot_pedidos WHERE estado='espera'
                            AND COALESCE(revisar_el,'') <> '' AND revisar_el <= ?""", (hoy(),)).fetchone()
        return {"nuevos": int(r["n"] or 0), "urgentes": int(r["u"] or 0), "a_revisar": int(v["n"] or 0)}
    except Exception:
        _rollback(conn)
        return {"nuevos": 0, "urgentes": 0, "a_revisar": 0}
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# LO QUE VE EL CHOFER
# ════════════════════════════════════════════════════════════════════════════

def reportes_del_chofer(chofer, limite=20):
    """Los reportes del chofer con cómo quedó cada problema."""
    conn = get_connection()
    try:
        filas = [dict(r) for r in conn.execute("""
            SELECT r.id AS reporte_id, r.fecha, r.creado_el, v.patente, v.n_interno,
                   p.descripcion, p.estado, p.motivo, p.revisar_el, i.estado AS estado_item, p.ot_id
            FROM ot_pedido_reportes r JOIN ot_pedidos p ON p.reporte_id = r.id
            JOIN vehiculos v ON v.id = r.vehiculo_id
            LEFT JOIN ot_items i ON i.id = p.item_id
            WHERE r.chofer = ? ORDER BY r.creado_el DESC, p.id""", (chofer,)).fetchall()]
    except Exception:
        _rollback(conn)
        filas = []
    finally:
        conn.close()
    reps = {}
    for f in filas:
        r = reps.setdefault(f["reporte_id"], {"reporte_id": f["reporte_id"], "fecha": f["fecha"], "creado_el": f["creado_el"],
                                              "patente": f["patente"], "n_interno": f["n_interno"], "problemas": []})
        if f["estado"] == "aceptado":
            est = "resuelto" if f["estado_item"] == "completado" else "en_taller"
        elif f["estado"] == "descartado":
            est = "no_se_hace"
        elif f["estado"] == "espera":
            est = "mas_adelante"
        else:
            est = "en_revision"
        r["problemas"].append({"txt": f["descripcion"], "estado": est, "motivo": f["motivo"] or "",
                               "ot_id": f["ot_id"]})
    return list(reps.values())[:limite]


# ════════════════════════════════════════════════════════════════════════════
# RUTAS
# ════════════════════════════════════════════════════════════════════════════

def _puede_ver():
    return session.get("rol") in ("admin", "taller")


def _no(msg="No tenés permiso para esto", codigo=403):
    return jsonify({"ok": False, "msg": msg, "error": msg}), codigo


@bp_ot_pedidos.route("/api/ot_pedidos", methods=["GET"])
def api_bandeja():
    if not _puede_ver():
        return _no()
    return jsonify(bandeja(request.args.get("estado") or "nuevo", request.args.get("q") or ""))


@bp_ot_pedidos.route("/api/ot_pedidos/pendientes", methods=["GET"])
def api_pendientes():
    if not _puede_ver():
        return jsonify({"nuevos": 0, "urgentes": 0, "a_revisar": 0})
    return jsonify(pendientes())


@bp_ot_pedidos.route("/api/ot_pedidos/decidir", methods=["POST"])
def api_decidir():
    if not _puede_ver():
        return _no()
    d = request.get_json(silent=True) or {}
    ok, msg, res = decidir(d.get("ids"), d.get("accion"), d.get("prioridad") or "", d.get("motivo") or "",
                           d.get("revisar_el") or "", d.get("nota") or "")
    if not ok:
        return _no(msg, 400)
    return jsonify({"ok": True, "msg": msg, "resultado": res, "pendientes": pendientes()})


@bp_ot_pedidos.route("/api/ot_pedidos/<int:pid>", methods=["PATCH"])
def api_poner(pid):
    if not _puede_ver():
        return _no()
    d = request.get_json(silent=True) or {}
    ok, msg = poner(pid, d.get("prioridad") if "prioridad" in d else None, d.get("nota") if "nota" in d else None)
    if not ok:
        return _no(msg, 400)
    return jsonify({"ok": True, "msg": msg})


@bp_ot_pedidos.route("/api/ot_pedidos/foto/<int:fid>", methods=["GET"])
def api_foto(fid):
    if not _puede_ver():
        return _no()
    conn = get_connection()
    try:
        r = conn.execute("SELECT datos FROM ot_pedido_fotos WHERE id=?", (fid,)).fetchone()
    finally:
        conn.close()
    if not r:
        return _no("No está", 404)
    m = re.match(r"data:(image/[a-z+]+);base64,(.*)$", r["datos"] or "", re.S)
    if not m:
        return _no("No es una imagen", 400)
    return Response(base64.b64decode(m.group(2)), mimetype=m.group(1),
                    headers={"Cache-Control": "private, max-age=86400"})
