"""
trafico.py — Tráfico nacional e internacional: las salidas del día (La Santaniana)

Hoy el tráfico se arma en un Excel y se manda al grupo de WhatsApp. Acá se
arma en el sistema y sale un PDF único para mandar. Cómo está pensado:

  - Cada día tiene sus corredores (Concepción, Pedro Juan Caballero...) y en
    cada uno las salidas de IDA (salen de Asunción) y de REGRESO. Cada salida
    lleva hora, tramo tal como lo escriben (ASU/COP X 25, LOT/ASU...), coche
    y dos tripulantes. Las siglas se respetan tal cual.
  - El sistema sabe dónde quedó cada coche: si ayer salió de ASU a COP, hoy
    está en COP. Con eso sugiere qué coche (y con qué tripulación) hace cada
    regreso, y avisa si se asigna un coche que está en otro lado.
  - También avisa si el coche está fuera de servicio o si no existe en la
    flota (y marca los papeles vencidos). Que una hora se repita no es aviso:
    de noche hay refuerzos (REFUERZO en el tramo), y el coche del refuerzo
    queda allá para el día siguiente. Avisa, no bloquea: decide quien arma.
  - Publicar guarda una versión. Si después se cambia algo, la versión
    siguiente marca las filas que cambiaron, así nadie se queda con la vieja.
  - Hay dos tráficos por día con la misma fórmula: el NACIONAL y el
    INTERNACIONAL (Buenos Aires: Retiro, Liniers, San Justo, La Plata). Cada
    uno se arma y se publica por separado; dónde está cada coche se calcula
    con los dos juntos, porque el coche es uno solo: el que fue a Retiro
    amanece en Buenos Aires y no puede salir a Concepción.

Enganche en app.py:
    from trafico import bp_trafico, init_trafico
    init_trafico()
    app.register_blueprint(bp_trafico)
"""

import io
import json
import re
import unicodedata
from datetime import date, datetime, timedelta, time as dtime

from flask import Blueprint, request, jsonify, session, send_file
from db_compat import get_connection, USE_POSTGRES

bp_trafico = Blueprint("trafico", __name__)

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
LADOS = ("ida", "regreso")
DIAS_ATRAS_UBICACION = 12          # hasta cuántos días atrás se busca dónde quedó un coche
DIAS_SEMANA = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO", "DOMINGO"]


# ════════════════════════════════════════════════════════════════════════════
# TABLAS
# ════════════════════════════════════════════════════════════════════════════

def init_trafico():
    conn = get_connection()
    c = conn.cursor()
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS trafico_dias (
            id {PK},
            fecha TEXT NOT NULL,
            tipo TEXT DEFAULT 'nacional',       -- nacional | internacional
            titulo TEXT DEFAULT 'HORARIOS NACIONALES',
            version INTEGER DEFAULT 0,          -- cuántas veces se publicó
            publicado_el TEXT DEFAULT '',
            publicado_por TEXT DEFAULT '',
            modificado INTEGER DEFAULT 0,       -- 1 = hay cambios sin publicar
            actualizado TEXT DEFAULT ''
        )""")
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS trafico_bloques (
            id {PK},
            dia_id INTEGER NOT NULL,
            orden INTEGER DEFAULT 0,
            nombre TEXT NOT NULL,               -- el corredor: CONCEPCION, PEDRO JUAN CABALLERO...
            nota_ida TEXT DEFAULT '',
            nota_regreso TEXT DEFAULT '',       -- ej: TRASBORDO BSAS
            reserva_ida_coche TEXT DEFAULT '',
            reserva_ida_trip TEXT DEFAULT '',
            reserva_regreso_coche TEXT DEFAULT '',
            reserva_regreso_trip TEXT DEFAULT ''
        )""")
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS trafico_salidas (
            id {PK},
            dia_id INTEGER NOT NULL,
            bloque_id INTEGER NOT NULL,
            lado TEXT NOT NULL DEFAULT 'ida',   -- ida | regreso
            hora TEXT DEFAULT '',               -- HH:MM
            destino TEXT DEFAULT '',            -- tal como lo escriben: ASU/COP X 25
            coche TEXT DEFAULT '',              -- número interno, o A CONF
            trip1 TEXT DEFAULT '',
            trip2 TEXT DEFAULT '',
            nota TEXT DEFAULT ''
        )""")
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS trafico_versiones (
            id {PK},
            dia_id INTEGER NOT NULL,
            version INTEGER NOT NULL,
            publicado_el TEXT DEFAULT '',
            publicado_por TEXT DEFAULT '',
            datos TEXT DEFAULT '',              -- cómo quedó el día al publicar (JSON)
            cambios TEXT DEFAULT ''             -- qué cambió respecto de la anterior (JSON)
        )""")
    c.execute(f"""
        CREATE TABLE IF NOT EXISTS trafico_tripulantes (
            id {PK},
            nombre TEXT NOT NULL UNIQUE,
            usos INTEGER DEFAULT 0,
            ultimo TEXT DEFAULT ''
        )""")
    for sql in ("CREATE INDEX IF NOT EXISTS ix_trafico_salidas_dia ON trafico_salidas (dia_id)",
                "CREATE INDEX IF NOT EXISTS ix_trafico_bloques_dia ON trafico_bloques (dia_id)"):
        try:
            c.execute(sql)
        except Exception:
            pass
    conn.commit()
    conn.close()
    _migrar_tipo()


def _migrar_tipo():
    """Antes había un solo tráfico por día (el nacional) y la fecha era única.
    Ahora el día tiene dos: nacional e internacional. Se agrega la columna y
    la fecha pasa a ser única junto con el tipo. Lo ya cargado queda como
    nacional."""
    from db_compat import columnas_de_tabla
    conn = get_connection()
    try:
        if "tipo" not in columnas_de_tabla(conn, "trafico_dias"):
            conn.execute("ALTER TABLE trafico_dias ADD COLUMN tipo TEXT DEFAULT 'nacional'")
            conn.execute("UPDATE trafico_dias SET tipo='nacional' WHERE tipo IS NULL OR tipo=''")
            conn.commit()
        if USE_POSTGRES:
            conn.execute("ALTER TABLE trafico_dias DROP CONSTRAINT IF EXISTS trafico_dias_fecha_key")
            conn.commit()
        else:
            # SQLite no deja sacar el UNIQUE de una columna: se rehace la tabla
            fila = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='trafico_dias'").fetchone()
            if fila and "fecha TEXT NOT NULL UNIQUE" in (fila["sql"] or ""):
                conn.execute("ALTER TABLE trafico_dias RENAME TO trafico_dias_vieja")
                conn.execute("""CREATE TABLE trafico_dias (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL,
                    tipo TEXT DEFAULT 'nacional', titulo TEXT DEFAULT 'HORARIOS NACIONALES',
                    version INTEGER DEFAULT 0, publicado_el TEXT DEFAULT '', publicado_por TEXT DEFAULT '',
                    modificado INTEGER DEFAULT 0, actualizado TEXT DEFAULT '')""")
                conn.execute("""INSERT INTO trafico_dias (id, fecha, tipo, titulo, version, publicado_el,
                                    publicado_por, modificado, actualizado)
                                SELECT id, fecha, COALESCE(NULLIF(tipo,''),'nacional'), titulo, version, publicado_el,
                                       publicado_por, modificado, actualizado FROM trafico_dias_vieja""")
                conn.execute("DROP TABLE trafico_dias_vieja")
                conn.commit()
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_trafico_dias_fecha_tipo ON trafico_dias (fecha, tipo)")
        conn.commit()
    finally:
        conn.close()


TIPOS = ("nacional", "internacional")
TITULOS = {"nacional": "HORARIOS NACIONALES", "internacional": "HORARIOS INTERNACIONALES"}


def tipo_ok(t):
    t = str(t or "").strip().lower()
    return t if t in TIPOS else "nacional"


# ════════════════════════════════════════════════════════════════════════════
# TEXTO: horas, nombres y tramos
# ════════════════════════════════════════════════════════════════════════════

def _sin_tildes(s):
    t = unicodedata.normalize("NFD", str(s or ""))
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")


def limpiar(s):
    """Mayúsculas y espacios prolijos, sin tocar las siglas ni las tildes."""
    return " ".join(str(s or "").split()).upper()


def normalizar_hora(v):
    """09:00:00, 9:00, 06.30, 0630, un time de Excel → 'HH:MM'. Vacío si no se entiende."""
    if v is None or v == "":
        return ""
    if isinstance(v, (dtime, datetime)):
        return f"{v.hour:02d}:{v.minute:02d}"
    if isinstance(v, (int, float)) and 0 <= float(v) < 1:          # fracción de día de Excel
        m = round(float(v) * 24 * 60)
        return f"{(m // 60) % 24:02d}:{m % 60:02d}"
    s = str(v).strip().replace(".", ":").replace(" ", "")
    m = re.match(r"^(\d{1,2}):(\d{2})(:\d{2})?$", s) or re.match(r"^(\d{1,2})(\d{2})$", s)
    if not m:
        return ""
    h, mi = int(m.group(1)), int(m.group(2))
    if h > 23 or mi > 59:
        return ""
    return f"{h:02d}:{mi:02d}"


# Lugares que aparecen en los tramos. La sigla es como la escriben ellos.
LUGARES = {
    "ASU": "ASU", "ASUNCION": "ASU",
    "COP": "COP", "CONCEPCION": "COP",
    "LOT": "LOT", "LORETO": "LOT",
    "PJC": "PJC", "PEDRO JUAN CABALLERO": "PJC", "PEDRO JUAN": "PJC",
    "CDE": "CDE", "CIUDAD DEL ESTE": "CDE",
    "ATQ": "ATQ",
    "SAN PEDRO": "SAN PEDRO",
    "TACUATI": "TACUATI",
    "SAN VICENTE": "SAN VICENTE",
    "VCA": "VILLARRICA", "VILLARRICA": "VILLARRICA",
    "CARAPEGUA": "CARAPEGUA",
    "ROQUE GONZALEZ": "ROQUE GONZALEZ",
}
# Internacional: dónde llegan en Buenos Aires. El primero que aparece en el
# texto es el que manda ("LA NORIA A LA PLATA" llega a LA PLATA: se busca
# primero LA PLATA).
LUGARES_AR = ("LA PLATA", "LA NORIA", "SAN JUSTO", "LINIERS", "RETIRO", "BUENOS AIRES", "BS AS", "BSAS", "CLORINDA")
LUGAR_AR_DEFECTO = "BUENOS AIRES"


def _lugar_ar(txt):
    t = _sin_tildes(limpiar(txt)).replace(".", " ")
    t = " ".join(t.split())
    for k in LUGARES_AR:
        if re.search(rf"\b{k}\b", t):
            return "BUENOS AIRES" if k in ("BS AS", "BSAS") else k
    return ""


def es_argentina(lugar):
    """Si un lugar (ya en siglas o nombre) queda del lado argentino."""
    return bool(lugar) and bool(_lugar_ar(lugar))


def _lugar_conocido(txt):
    """El lugar si se reconoce (del interior o de Argentina); si no, vacío."""
    a = _lugar_ar(txt)
    if a:
        return a
    t = _sin_tildes(limpiar(txt)).strip(" /-")
    if t in LUGARES:
        return LUGARES[t]
    for k, v in LUGARES.items():
        if t.startswith(k + " "):
            return v
    return ""
_CLASES = ("REFUERZO", "LEITO", "SEMI CAMA", "SEMICAMA", "CAMA", "EJECUTIVO", "DIRECTO")


def partes_destino(destino):
    """'ASU/COP X CHACO' → ('ASU/COP', ['X CHACO']); 'ASU PJC LEITO' → ('ASU PJC', ['LEITO']).
    Separa el tramo de lo que lo acompaña (por dónde va, la clase), para el PDF."""
    s = limpiar(destino)
    extras = []
    for cl in _CLASES:
        if re.search(rf"\b{cl}\b", s):
            extras.append(cl)
            s = re.sub(rf"\s*\b{cl}\b", "", s).strip()
    m = re.search(r"(^|\s+)X\s+(.+)$", s)
    if m:
        extras.insert(0, "X " + m.group(2).strip())
        s = s[:m.start()].strip()
    s = re.sub(r"\s*/\s*", " / ", s).strip(" /")
    return s, extras


def _lugar(txt):
    t = _sin_tildes(limpiar(txt)).strip(" /-")
    if t in LUGARES:
        return LUGARES[t]
    for k, v in LUGARES.items():                 # "ASUNCION" dentro de un texto más largo
        if t.startswith(k + " ") or t == k:
            return v
    return t or ""


def lugar_del_corredor(nombre):
    return _lugar(nombre)


def tramo_internacional(destino, lado, corredor=""):
    """Como tramo(), para los viajes a Buenos Aires. Se escriben de muchas
    formas: 'ASUNCION / RETIRO X RUTA 1', 'VILLARRICA/ SAN JUSTO',
    'ROQUE GONZALEZ - RETIRO', 'LA PLATA / VILLARRICA', o solo 'ASUNCION'
    en el regreso. Lo que no se reconoce de este lado se toma como Asunción,
    y del otro como Buenos Aires."""
    base, _ = partes_destino(destino)
    base = _sin_tildes(base)
    partes = [p.strip() for p in re.split(r"\s*/\s*|\s*-\s*", base) if p.strip()]
    ar_corr = _lugar_ar(corredor) or LUGAR_AR_DEFECTO
    if len(partes) >= 2:
        o, d = _lugar_conocido(partes[0]) or _lugar(partes[0]), _lugar_conocido(partes[-1]) or _lugar(partes[-1])
        return o, d
    if len(partes) == 1:
        x = _lugar_conocido(partes[0])
        if lado == "ida":
            return ("ASU", x) if es_argentina(x) else (x or "ASU", ar_corr)
        if x and es_argentina(x):
            return x, "ASU"
        return ar_corr, (x or "ASU")
    return ("ASU", ar_corr) if lado == "ida" else (ar_corr, "ASU")


def tramo(destino, lado, corredor, tipo="nacional"):
    """De dónde sale y a dónde llega una salida, en siglas. Sirve para saber
    dónde queda el coche. Si no se puede saber, devuelve ('', '')."""
    if tipo == "internacional":
        return tramo_internacional(destino, lado, corredor)
    base, _ = partes_destino(destino)
    base = _sin_tildes(base)
    if not base:
        lugar_corr = lugar_del_corredor(corredor)
        if not lugar_corr or lugar_corr == "ASU":
            return "", ""
        return ("ASU", lugar_corr) if lado == "ida" else (lugar_corr, "ASU")
    if "/" in base:
        o, d = [p.strip() for p in base.split("/", 1)]
        return _lugar(o), _lugar(d)
    lugar_corr = lugar_del_corredor(corredor)
    if base.startswith("ASU "):                  # "ASU PJC" sin barra
        return "ASU", _lugar(base[4:])
    l = _lugar(base)
    if lado == "ida":
        return "ASU", l
    if l == "ASU":
        return lugar_corr, "ASU"
    return l, "ASU"


def nombre_dia(fecha):
    d = date.fromisoformat(fecha)
    return f"{DIAS_SEMANA[d.weekday()]} {d.strftime('%d/%m/%y')}"


# ════════════════════════════════════════════════════════════════════════════
# LECTURA DEL DÍA
# ════════════════════════════════════════════════════════════════════════════

def _dia_por_fecha(conn, fecha, tipo="nacional"):
    r = conn.execute("SELECT * FROM trafico_dias WHERE fecha=? AND COALESCE(tipo,'nacional')=?",
                     (fecha, tipo_ok(tipo))).fetchone()
    return dict(r) if r else None


def _orden_hora(h):
    return h if h else "99:99"


def _flota(conn):
    """Los coches de la flota por número interno."""
    out = {}
    for r in conn.execute("""SELECT id, n_interno, patente, marca, modelo, COALESCE(activo,1) AS activo
                             FROM vehiculos""").fetchall():
        n = str(r["n_interno"] or "").strip()
        if n:
            out[n] = dict(r)
    return out


def _tramos_recientes(conn, fecha, dias=DIAS_ATRAS_UBICACION):
    """Todas las salidas con coche de los últimos días hasta la fecha (incluida),
    en orden: con esto se sabe dónde está cada coche en cada momento."""
    desde = (date.fromisoformat(fecha) - timedelta(days=dias)).isoformat()
    # Nacional e internacional juntos: el coche es uno solo
    filas = conn.execute("""
        SELECT s.id, s.lado, s.hora, s.destino, s.coche, s.trip1, s.trip2,
               b.nombre AS corredor, d.fecha, COALESCE(d.tipo, 'nacional') AS tipo
        FROM trafico_salidas s
        JOIN trafico_bloques b ON b.id = s.bloque_id
        JOIN trafico_dias d ON d.id = s.dia_id
        WHERE d.fecha >= ? AND d.fecha <= ? AND s.coche <> ''""", (desde, fecha)).fetchall()
    tramos = []
    for f in filas:
        coche = limpiar(f["coche"])
        if not coche.isdigit():
            continue
        o, de = tramo(f["destino"], f["lado"], f["corredor"], f["tipo"])
        tramos.append({"id": f["id"], "fecha": f["fecha"], "hora": f["hora"] or "00:00", "coche": coche,
                       "origen": o, "llega": de, "destino": f["destino"], "corredor": f["corredor"],
                       "tipo": f["tipo"], "trip1": f["trip1"] or "", "trip2": f["trip2"] or ""})
    tramos.sort(key=lambda t: (t["fecha"], t["hora"], t["id"]))
    return tramos


def ubicaciones(tramos, fecha, hora="00:00", excluir_id=None):
    """Dónde está cada coche en (fecha, hora): el destino de su último tramo
    anterior. Devuelve {coche: {lugar, desde_fecha, desde_hora, destino, trip1, trip2}}."""
    donde = {}
    for t in tramos:
        if t["id"] == excluir_id:
            continue
        if (t["fecha"], t["hora"]) >= (fecha, hora):
            continue
        donde[t["coche"]] = {"lugar": t["llega"], "desde_fecha": t["fecha"], "desde_hora": t["hora"],
                             "destino": t["destino"], "corredor": t["corredor"], "tipo": t.get("tipo", "nacional"),
                             "trip1": t["trip1"], "trip2": t["trip2"]}
    return donde


def _estado_coches(conn, fecha, numeros, flota):
    """OT abierta, fuera de servicio y documentos vencidos de los coches del día."""
    ids = {flota[n]["id"]: n for n in numeros if n in flota}
    if not ids:
        return {}
    marcas = ",".join("?" * len(ids))
    estado = {n: [] for n in ids.values()}
    # Fuera de servicio: no debería salir (rojo)
    try:
        for r in conn.execute(f"""SELECT vehiculo_id, motivo FROM fuera_servicio
                                  WHERE vehiculo_id IN ({marcas}) AND fecha_desde <= ?
                                  AND (fecha_hasta IS NULL OR fecha_hasta = '' OR fecha_hasta >= ?)""",
                              list(ids) + [fecha, fecha]).fetchall():
            m = f" ({r['motivo']})" if r["motivo"] else ""
            estado[ids[r["vehiculo_id"]]].append(("error", f"está fuera de servicio{m}"))
    except Exception:
        pass
    # Papeles vencidos: todos juntos en un solo aviso por coche
    try:
        venc = {}
        for r in conn.execute(f"""SELECT vehiculo_id, tipo, fecha_vencimiento FROM documentos
                                  WHERE vehiculo_id IN ({marcas}) AND reemplazado_por IS NULL
                                  AND fecha_vencimiento < ? ORDER BY fecha_vencimiento""",
                              list(ids) + [fecha]).fetchall():
            venc.setdefault(ids[r["vehiculo_id"]], [])
            if r["tipo"] not in venc[ids[r["vehiculo_id"]]]:
                venc[ids[r["vehiculo_id"]]].append(r["tipo"])
        for n, tipos in venc.items():
            estado[n].append(("doc", "tiene vencido: " + ", ".join(tipos)))
    except Exception:
        pass
    return estado


def armar_dia(fecha, conn=None, tipo="nacional"):
    """El día completo con lo que necesita la pantalla y el PDF: corredores,
    salidas, avisos, resumen y dónde están los coches al empezar el día."""
    tipo = tipo_ok(tipo)
    propia = conn is None
    conn = conn or get_connection()
    try:
        dia = _dia_por_fecha(conn, fecha, tipo)
        flota = _flota(conn)
        tramos = _tramos_recientes(conn, fecha)
        inicio = ubicaciones(tramos, fecha, "00:00")
        if not dia:
            return {"existe": False, "fecha": fecha, "tipo": tipo, "nombre_dia": nombre_dia(fecha),
                    "ubicaciones": _ubicaciones_para_panel(inicio, [], flota, tipo)}
        bloques = [dict(b) for b in conn.execute(
            "SELECT * FROM trafico_bloques WHERE dia_id=? ORDER BY orden, id", (dia["id"],)).fetchall()]
        salidas = [dict(s) for s in conn.execute(
            "SELECT * FROM trafico_salidas WHERE dia_id=? ORDER BY id", (dia["id"],)).fetchall()]
        numeros = {limpiar(s["coche"]) for s in salidas if limpiar(s["coche"]).isdigit()}
        estado = _estado_coches(conn, fecha, numeros, flota)
    finally:
        if propia:
            conn.close()

    por_bloque = {b["id"]: {"ida": [], "regreso": []} for b in bloques}
    for s in salidas:
        if s["bloque_id"] in por_bloque:
            por_bloque[s["bloque_id"]][s["lado"] if s["lado"] in LADOS else "ida"].append(s)
    nombres_bloque = {b["id"]: b["nombre"] for b in bloques}

    for s in salidas:
        avisos = []
        coche = limpiar(s["coche"])
        s["origen"], s["llega"] = tramo(s["destino"], s["lado"], nombres_bloque.get(s["bloque_id"], ""), tipo)
        s["destino_base"], s["destino_extras"] = partes_destino(s["destino"])
        if not coche or not coche.isdigit():
            avisos.append({"nivel": "falta", "txt": "Falta el coche" if not coche
                           else "Coche a confirmar" if "CONF" in coche else f"Coche: {coche}"})
        else:
            v = flota.get(coche)
            if not v:
                avisos.append({"nivel": "error", "txt": f"El {coche} no está en la flota"})
            else:
                s["modelo"] = f"{v['marca'] or ''} {v['modelo'] or ''}".strip()
                for nivel, txt in estado.get(coche, []):
                    avisos.append({"nivel": nivel, "txt": f"El {coche} {txt}"})
            # ¿El coche está donde sale?
            if s["hora"] and s["origen"]:
                u = ubicaciones(tramos, fecha, s["hora"], excluir_id=s["id"]).get(coche)
                if u and u["lugar"] and esta_ahi(u, s["origen"], nombres_bloque.get(s["bloque_id"], ""), tipo) is None:
                    cuando = "hoy" if u["desde_fecha"] == fecha else _cuando(u["desde_fecha"], fecha)
                    avisos.append({"nivel": "aviso",
                                   "txt": f"El {coche} está en {u['lugar']} (salió {cuando} {u['desde_hora']} {u['destino']})"})
        trips = [t for t in (s["trip1"], s["trip2"]) if t]
        if not trips:
            avisos.append({"nivel": "falta", "txt": "Faltan los tripulantes"})
        if not s["hora"]:
            avisos.append({"nivel": "falta", "txt": "Falta la hora"})
        s["avisos"] = avisos

    for b in bloques:
        for lado in LADOS:
            b[lado] = sorted(por_bloque[b["id"]][lado], key=lambda s: (_orden_hora(s["hora"]), s["id"]))

    # Resumen
    con_coche = {limpiar(s["coche"]) for s in salidas if limpiar(s["coche"]).isdigit()}
    trip_dia = {limpiar(t) for s in salidas for t in (s["trip1"], s["trip2"]) if t}
    a_confirmar = sum(1 for s in salidas if any(a["nivel"] == "falta" for a in s["avisos"]))
    con_aviso = sum(1 for s in salidas if any(a["nivel"] in ("error", "aviso") for a in s["avisos"]))
    papeles = len({limpiar(s["coche"]) for s in salidas if any(a["nivel"] == "doc" for a in s["avisos"])})
    refuerzos = sum(1 for s in salidas if "REFUERZO" in (s.get("destino_extras") or []))

    return {
        "existe": True, "fecha": fecha, "tipo": tipo, "nombre_dia": nombre_dia(fecha), "dia": dia,
        "bloques": bloques,
        "resumen": {"salidas": len(salidas), "coches": len(con_coche), "tripulantes": len(trip_dia),
                    "a_confirmar": a_confirmar, "con_aviso": con_aviso, "papeles": papeles,
                    "refuerzos": refuerzos},
        "ubicaciones": _ubicaciones_para_panel(inicio, salidas, flota, tipo),
    }


def _cuando(f, hoy):
    dias = (date.fromisoformat(hoy) - date.fromisoformat(f)).days
    return "ayer" if dias == 1 else f"el {f[8:10]}/{f[5:7]}"


def _ubicaciones_para_panel(inicio, salidas_dia, flota, tipo="nacional"):
    """Dónde amanece cada coche, agrupado por lugar, y si ya tiene salida hoy.
    En el internacional van primero los que están en Buenos Aires (ahí están
    los regresos)."""
    asignados = {}
    for s in salidas_dia:
        c = limpiar(s["coche"])
        if c.isdigit():
            asignados.setdefault(c, []).append(s["hora"] or "")
    grupos = {}
    for coche, u in inicio.items():
        lugar = u["lugar"] or "?"
        # En el internacional interesan los que están en Buenos Aires y los
        # que volvieron de allá (no los 89 coches del nacional)
        if tipo == "internacional" and not es_argentina(lugar) and u.get("tipo") != "internacional" \
                and coche not in asignados:
            continue
        v = flota.get(coche)
        grupos.setdefault(lugar, []).append({
            "coche": coche, "desde_fecha": u["desde_fecha"], "desde_hora": u["desde_hora"],
            "destino": u["destino"], "trip1": u["trip1"], "trip2": u["trip2"],
            "modelo": f"{v['marca'] or ''} {v['modelo'] or ''}".strip() if v else "",
            "hoy": sorted(asignados.get(coche, [])),
        })
    if tipo == "internacional":
        orden = sorted(grupos, key=lambda l: (not es_argentina(l), l == "ASU", l))
    else:
        orden = sorted(grupos, key=lambda l: (l == "ASU", l))  # el interior primero: ahí están los regresos
    return [{"lugar": l, "coches": sorted(grupos[l], key=lambda x: (x["desde_fecha"], x["desde_hora"]))}
            for l in orden]


# ════════════════════════════════════════════════════════════════════════════
# SUGERENCIAS: qué coche hace cada salida
# ════════════════════════════════════════════════════════════════════════════

def _clave(s):
    return _sin_tildes(limpiar(s))


def esta_ahi(u, origen, corredor, tipo="nacional"):
    """Si un coche que está en u puede hacer una salida desde origen: está en
    ese lugar, o en otro punto del mismo corredor del interior (el que llegó
    a COP puede salir de LOT, el que llegó a SAN PEDRO puede salir de ATQ).
    Internacional: del lado argentino sirve cualquier coche que esté en Buenos
    Aires (Retiro, Liniers, La Plata quedan cerca); de este lado, cualquiera
    que esté en el país."""
    if not u or not u.get("lugar") or not origen:
        return None
    if u["lugar"] == origen:
        return 0
    if es_argentina(u["lugar"]) != es_argentina(origen):
        return None                              # está del otro lado de la frontera
    if tipo == "internacional":
        return 1
    if origen != "ASU" and u["lugar"] != "ASU" and u.get("corredor") and _clave(u["corredor"]) == _clave(corredor):
        return 1
    return None


def candidatos_para(donde, origen, corredor, fecha, hora, ya_hoy, flota, tomados=(), tipo="nacional"):
    """Los coches que pueden hacer una salida, del más indicado al menos:
    primero los que están en el lugar, después los del mismo corredor, y
    entre iguales el que llegó antes. Los que ya tienen otra salida hoy
    después de esta hora van al final; los que salen a la misma hora, no van."""
    lista = []
    for coche, u in donde.items():
        if coche in tomados:
            continue
        rango = esta_ahi(u, origen, corredor, tipo)
        if rango is None:
            continue
        horas = [h for h in ya_hoy.get(coche, []) if h]
        if hora and hora in horas:
            continue
        if hora and any(h > hora for h in horas):
            rango += 2
        v = flota.get(coche)
        lista.append({
            "coche": coche, "lugar": u["lugar"], "rango": rango,
            "desde_fecha": u["desde_fecha"], "desde_hora": u["desde_hora"], "destino": u["destino"],
            "trip1": u["trip1"], "trip2": u["trip2"],
            "cuando": "hoy" if u["desde_fecha"] == fecha else _cuando(u["desde_fecha"], fecha),
            "modelo": f"{v['marca'] or ''} {v['modelo'] or ''}".strip() if v else "",
            "ya_hoy": sorted(horas),
        })
    lista.sort(key=lambda c: (c["rango"], c["desde_fecha"], c["desde_hora"], c["coche"]))
    return lista


def sugerencias(salida_id):
    conn = get_connection()
    try:
        s = conn.execute("""SELECT s.*, b.nombre AS corredor, d.fecha, COALESCE(d.tipo,'nacional') AS tipo FROM trafico_salidas s
                            JOIN trafico_bloques b ON b.id=s.bloque_id
                            JOIN trafico_dias d ON d.id=s.dia_id WHERE s.id=?""", (salida_id,)).fetchone()
        if not s:
            return None
        s = dict(s)
        flota = _flota(conn)
        tramos = _tramos_recientes(conn, s["fecha"])
        hoy_salidas = conn.execute("SELECT coche, hora FROM trafico_salidas WHERE dia_id=? AND id<>?",
                                   (s["dia_id"], salida_id)).fetchall()
    finally:
        conn.close()
    origen, _ = tramo(s["destino"], s["lado"], s["corredor"], s["tipo"])
    donde = ubicaciones(tramos, s["fecha"], s["hora"] or "23:59", excluir_id=salida_id)
    ya_hoy = {}
    for r in hoy_salidas:
        c = limpiar(r["coche"])
        if c.isdigit():
            ya_hoy.setdefault(c, []).append(r["hora"] or "")
    cands = candidatos_para(donde, origen, s["corredor"], s["fecha"], s["hora"], ya_hoy, flota, tipo=s["tipo"])
    # Desde Asunción hay muchos: se muestran los que llegaron hace más tiempo
    return {"salida": {"id": s["id"], "hora": s["hora"], "destino": s["destino"], "origen": origen},
            "candidatos": cands[:12], "total": len(cands)}


def completar_con_ubicacion(fecha, simular=False, tipo="nacional"):
    """Llena las salidas sin coche que no salen de Asunción con los coches que
    están en ese lugar, con la misma tripulación con la que llegaron. Es el
    caso de todos los días: el que fue a Concepción vuelve de Concepción.
    Con simular=True solo cuenta cuántas podría llenar (para el botón).
    Internacional: los regresos desde Buenos Aires con los coches que están allá."""
    tipo = tipo_ok(tipo)
    conn = get_connection()
    try:
        dia = _dia_por_fecha(conn, fecha, tipo)
        if not dia:
            return 0
        if not simular:
            _bloquear_dia(conn, dia["id"])
        filas = conn.execute("""SELECT s.*, b.nombre AS corredor FROM trafico_salidas s
                                JOIN trafico_bloques b ON b.id=s.bloque_id
                                WHERE s.dia_id=?""", (dia["id"],)).fetchall()
        tramos = _tramos_recientes(conn, fecha)
        flota = _flota(conn)
        vacias, ya_hoy = [], {}
        for f in filas:
            c = limpiar(f["coche"])
            if c.isdigit():
                ya_hoy.setdefault(c, []).append(f["hora"] or "")
            elif not c:
                o, _ = tramo(f["destino"], f["lado"], f["corredor"], tipo)
                desde_alla = es_argentina(o) if tipo == "internacional" else (o and o != "ASU")
                if o and desde_alla and f["hora"]:
                    vacias.append((f["hora"], dict(f), o))
        vacias.sort(key=lambda x: x[0])
        tomados = set()
        llenadas = 0
        for hora, f, origen in vacias:
            donde = ubicaciones(tramos, fecha, hora)
            cand = [c for c in candidatos_para(donde, origen, f["corredor"], fecha, hora, ya_hoy, flota, tomados, tipo)
                    if c["rango"] < 2]          # no tocar los que ya tienen otra salida más tarde
            if not cand:
                continue
            u = cand[0]
            coche = u["coche"]
            tomados.add(coche)
            ya_hoy.setdefault(coche, []).append(hora)
            if not simular:
                conn.execute("""UPDATE trafico_salidas SET coche=?,
                                trip1=CASE WHEN COALESCE(trip1,'')='' THEN ? ELSE trip1 END,
                                trip2=CASE WHEN COALESCE(trip2,'')='' THEN ? ELSE trip2 END
                                WHERE id=?""", (coche, u["trip1"], u["trip2"], f["id"]))
            # el coche ya salió de ahí: para las siguientes cuenta donde llega
            o, d = tramo(f["destino"], f["lado"], f["corredor"], tipo)
            tramos.append({"id": f["id"], "fecha": fecha, "hora": hora, "coche": coche, "origen": o,
                           "llega": d, "destino": f["destino"], "corredor": f["corredor"], "tipo": tipo,
                           "trip1": u["trip1"], "trip2": u["trip2"]})
            tramos.sort(key=lambda t: (t["fecha"], t["hora"], t["id"]))
            llenadas += 1
        if simular:
            return llenadas
        if llenadas:
            _marcar_modificado(conn, dia["id"])
        conn.commit()
        return llenadas
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# ESCRITURA
# ════════════════════════════════════════════════════════════════════════════

def _ahora():
    try:
        from hora_local import ahora_iso
        return ahora_iso()
    except Exception:
        return datetime.now().isoformat(timespec="seconds")


def _marcar_modificado(conn, dia_id):
    conn.execute("""UPDATE trafico_dias SET actualizado=?,
                    modificado=CASE WHEN version > 0 THEN 1 ELSE 0 END WHERE id=?""", (_ahora(), dia_id))


def crear_dia(fecha, conn=None, tipo="nacional"):
    tipo = tipo_ok(tipo)
    propia = conn is None
    conn = conn or get_connection()
    try:
        d = _dia_por_fecha(conn, fecha, tipo)
        if d:
            return d["id"]
        conn.execute("""INSERT INTO trafico_dias (fecha, tipo, titulo, actualizado) VALUES (?, ?, ?, ?)
                        ON CONFLICT (fecha, tipo) DO NOTHING""", (fecha, tipo, TITULOS[tipo], _ahora()))
        conn.commit()
        return _dia_por_fecha(conn, fecha, tipo)["id"]
    finally:
        if propia:
            conn.close()


def _bloquear_dia(conn, dia_id):
    """Si llegan dos pedidos para el mismo día (doble clic en Importar porque
    tarda), el segundo espera a que termine el primero y después lo reemplaza:
    nunca quedan las salidas dos veces. En SQLite la base ya escribe de a uno."""
    if USE_POSTGRES:
        conn.execute("SELECT id FROM trafico_dias WHERE id=? FOR UPDATE", (dia_id,))


def agregar_bloque(fecha, nombre, tipo="nacional"):
    nombre = limpiar(nombre)
    if not nombre:
        return None
    conn = get_connection()
    try:
        dia_id = crear_dia(fecha, conn, tipo)
        orden = conn.execute("SELECT COALESCE(MAX(orden), 0) AS m FROM trafico_bloques WHERE dia_id=?",
                             (dia_id,)).fetchone()["m"] + 1
        cur = conn.execute("INSERT INTO trafico_bloques (dia_id, orden, nombre) VALUES (?,?,?)",
                           (dia_id, orden, nombre))
        bid = cur.lastrowid
        if not bid:
            bid = conn.execute("SELECT MAX(id) AS m FROM trafico_bloques WHERE dia_id=?", (dia_id,)).fetchone()["m"]
        _marcar_modificado(conn, dia_id)
        conn.commit()
        return bid
    finally:
        conn.close()


CAMPOS_BLOQUE = {"nombre", "nota_ida", "nota_regreso", "reserva_ida_coche", "reserva_ida_trip",
                 "reserva_regreso_coche", "reserva_regreso_trip"}
CAMPOS_SALIDA = {"hora", "destino", "coche", "trip1", "trip2", "nota", "lado"}


def editar_bloque(bid, datos):
    campos = {k: limpiar(v) for k, v in datos.items() if k in CAMPOS_BLOQUE}
    if "nombre" in campos and not campos["nombre"]:
        campos.pop("nombre")
    if not campos:
        return None
    conn = get_connection()
    try:
        b = conn.execute("SELECT dia_id FROM trafico_bloques WHERE id=?", (bid,)).fetchone()
        if not b:
            return None
        conn.execute(f"UPDATE trafico_bloques SET {', '.join(k + '=?' for k in campos)} WHERE id=?",
                     list(campos.values()) + [bid])
        _registrar_tripulantes(conn, [campos.get("reserva_ida_trip"), campos.get("reserva_regreso_trip")])
        _marcar_modificado(conn, b["dia_id"])
        conn.commit()
        return b["dia_id"]
    finally:
        conn.close()


def mover_bloque(bid, paso):
    conn = get_connection()
    try:
        b = conn.execute("SELECT id, dia_id FROM trafico_bloques WHERE id=?", (bid,)).fetchone()
        if not b:
            return None
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM trafico_bloques WHERE dia_id=? ORDER BY orden, id", (b["dia_id"],)).fetchall()]
        i = ids.index(bid)
        j = max(0, min(len(ids) - 1, i + (1 if paso > 0 else -1)))
        ids[i], ids[j] = ids[j], ids[i]
        for k, x in enumerate(ids):
            conn.execute("UPDATE trafico_bloques SET orden=? WHERE id=?", (k + 1, x))
        _marcar_modificado(conn, b["dia_id"])
        conn.commit()
        return b["dia_id"]
    finally:
        conn.close()


def borrar_bloque(bid):
    conn = get_connection()
    try:
        b = conn.execute("SELECT dia_id FROM trafico_bloques WHERE id=?", (bid,)).fetchone()
        if not b:
            return None
        conn.execute("DELETE FROM trafico_salidas WHERE bloque_id=?", (bid,))
        conn.execute("DELETE FROM trafico_bloques WHERE id=?", (bid,))
        _marcar_modificado(conn, b["dia_id"])
        conn.commit()
        return b["dia_id"]
    finally:
        conn.close()


def agregar_salida(bid, lado, datos=None):
    lado = lado if lado in LADOS else "ida"
    datos = datos or {}
    conn = get_connection()
    try:
        b = conn.execute("SELECT dia_id FROM trafico_bloques WHERE id=?", (bid,)).fetchone()
        if not b:
            return None
        cur = conn.execute("""INSERT INTO trafico_salidas (dia_id, bloque_id, lado, hora, destino, coche, trip1, trip2)
                              VALUES (?,?,?,?,?,?,?,?)""",
                           (b["dia_id"], bid, lado, normalizar_hora(datos.get("hora")), limpiar(datos.get("destino")),
                            limpiar(datos.get("coche")), limpiar(datos.get("trip1")), limpiar(datos.get("trip2"))))
        sid = cur.lastrowid or conn.execute("SELECT MAX(id) AS m FROM trafico_salidas WHERE bloque_id=?",
                                            (bid,)).fetchone()["m"]
        _marcar_modificado(conn, b["dia_id"])
        conn.commit()
        return sid
    finally:
        conn.close()


def editar_salida(sid, datos):
    campos = {}
    for k, v in datos.items():
        if k not in CAMPOS_SALIDA:
            continue
        if k == "hora":
            h = normalizar_hora(v)
            if v and not h:
                continue                 # una hora que no se entiende no borra la que había
            campos[k] = h
        elif k == "lado":
            if v in LADOS:
                campos[k] = v
        else:
            campos[k] = limpiar(v)
    conn = get_connection()
    try:
        s = conn.execute("SELECT dia_id FROM trafico_salidas WHERE id=?", (sid,)).fetchone()
        if not s:
            return None
        if not campos:                   # nada que cambiar: igual se devuelve el día
            return s["dia_id"]
        conn.execute(f"UPDATE trafico_salidas SET {', '.join(k + '=?' for k in campos)} WHERE id=?",
                     list(campos.values()) + [sid])
        _registrar_tripulantes(conn, [campos.get("trip1"), campos.get("trip2")])
        _marcar_modificado(conn, s["dia_id"])
        conn.commit()
        return s["dia_id"]
    finally:
        conn.close()


def borrar_salida(sid):
    conn = get_connection()
    try:
        s = conn.execute("SELECT dia_id FROM trafico_salidas WHERE id=?", (sid,)).fetchone()
        if not s:
            return None
        conn.execute("DELETE FROM trafico_salidas WHERE id=?", (sid,))
        _marcar_modificado(conn, s["dia_id"])
        conn.commit()
        return s["dia_id"]
    finally:
        conn.close()


def _registrar_tripulantes(conn, nombres):
    """La lista de tripulantes se arma sola con lo que se va cargando."""
    hoy = _ahora()[:10]
    for n in nombres:
        n = limpiar(n)
        if not n or len(n) < 3:
            continue
        r = conn.execute("SELECT id FROM trafico_tripulantes WHERE nombre=?", (n,)).fetchone()
        if r:
            conn.execute("UPDATE trafico_tripulantes SET usos=usos+1, ultimo=? WHERE id=?", (hoy, r["id"]))
        else:
            conn.execute("INSERT INTO trafico_tripulantes (nombre, usos, ultimo) VALUES (?,1,?)", (n, hoy))


def lista_tripulantes():
    conn = get_connection()
    try:
        return [r["nombre"] for r in conn.execute(
            "SELECT nombre FROM trafico_tripulantes ORDER BY nombre").fetchall()]
    finally:
        conn.close()


def lista_destinos(tipo="nacional"):
    """Los tramos ya usados en ese tráfico, para completar al escribir."""
    conn = get_connection()
    try:
        return [r["destino"] for r in conn.execute(
            """SELECT DISTINCT s.destino FROM trafico_salidas s JOIN trafico_dias d ON d.id = s.dia_id
               WHERE s.destino<>'' AND COALESCE(d.tipo,'nacional')=? ORDER BY s.destino""",
            (tipo_ok(tipo),)).fetchall()]
    finally:
        conn.close()


def vaciar_dia(conn, dia_id):
    conn.execute("DELETE FROM trafico_salidas WHERE dia_id=?", (dia_id,))
    conn.execute("DELETE FROM trafico_bloques WHERE dia_id=?", (dia_id,))


def copiar_dia(fecha, desde, con_asignaciones=True, tipo="nacional"):
    """Arma el día copiando otro del mismo tráfico: los corredores y las
    salidas con sus horas y tramos, y si se pide, también coches y tripulantes."""
    conn = get_connection()
    try:
        origen = _dia_por_fecha(conn, desde, tipo)
        if not origen:
            return False, "Ese día no tiene tráfico cargado."
        dia_id = crear_dia(fecha, conn, tipo)
        _bloquear_dia(conn, dia_id)
        vaciar_dia(conn, dia_id)
        bloques = conn.execute("SELECT * FROM trafico_bloques WHERE dia_id=? ORDER BY orden, id",
                               (origen["id"],)).fetchall()
        for b in bloques:
            b = dict(b)
            cur = conn.execute("""INSERT INTO trafico_bloques (dia_id, orden, nombre, nota_ida, nota_regreso,
                                    reserva_ida_coche, reserva_ida_trip, reserva_regreso_coche, reserva_regreso_trip)
                                  VALUES (?,?,?,?,?,?,?,?,?)""",
                               (dia_id, b["orden"], b["nombre"], b["nota_ida"], b["nota_regreso"],
                                b["reserva_ida_coche"] if con_asignaciones else "",
                                b["reserva_ida_trip"] if con_asignaciones else "",
                                b["reserva_regreso_coche"] if con_asignaciones else "",
                                b["reserva_regreso_trip"] if con_asignaciones else ""))
            nb = cur.lastrowid or conn.execute("SELECT MAX(id) AS m FROM trafico_bloques WHERE dia_id=?",
                                               (dia_id,)).fetchone()["m"]
            for s in conn.execute("SELECT * FROM trafico_salidas WHERE bloque_id=? ORDER BY id", (b["id"],)).fetchall():
                conn.execute("""INSERT INTO trafico_salidas (dia_id, bloque_id, lado, hora, destino, coche, trip1, trip2, nota)
                                VALUES (?,?,?,?,?,?,?,?,?)""",
                             (dia_id, nb, s["lado"], s["hora"], s["destino"],
                              s["coche"] if con_asignaciones else "",
                              s["trip1"] if con_asignaciones else "",
                              s["trip2"] if con_asignaciones else "", s["nota"]))
        _marcar_modificado(conn, dia_id)
        conn.commit()
        return True, "Día copiado."
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# IMPORTAR EL EXCEL DE SIEMPRE
# ════════════════════════════════════════════════════════════════════════════

def leer_excel(contenido):
    """Lee la planilla como la arman hoy: a la izquierda las idas y a la
    derecha los regresos (hora, destino, coche, tripulantes en dos renglones),
    cada corredor con su título y su renglón de RESERVA. Devuelve
    (fecha o None, titulo, [bloques])."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(contenido), data_only=True)
    ws = wb.worksheets[0]

    def val(r, c):
        if r < 1 or c < 1:
            return None
        return ws.cell(r, c).value

    def txt(r, c):
        v = val(r, c)
        return "" if v is None else " ".join(str(v).split())

    # La fila de títulos: la que dice Destino / Coche / Tripulantes
    fila_tit, grupos = None, []
    for r in range(1, min(ws.max_row, 15) + 1):
        fila = [_sin_tildes(txt(r, c)).upper() for c in range(1, ws.max_column + 1)]
        cols_dest = [i + 1 for i, x in enumerate(fila) if x.startswith("DESTINO")]
        if cols_dest:
            fila_tit = r
            for cd in cols_dest:
                g = {"hora": cd - 1, "destino": cd}
                for c in range(cd + 1, min(cd + 5, ws.max_column + 1)):
                    x = fila[c - 1]
                    if x.startswith("COCHE") and "coche" not in g:
                        g["coche"] = c
                    elif x.startswith("TRIPUL") and "trip" not in g:
                        g["trip"] = c
                g.setdefault("coche", cd + 1)
                g.setdefault("trip", cd + 2)
                grupos.append(g)
            break
    if not fila_tit or not grupos:
        raise ValueError("No encontré la fila de títulos (Destino, Coche, Tripulantes).")

    # Fecha y título: en los renglones de arriba
    fecha, titulo = None, "HORARIOS NACIONALES"
    for r in range(1, fila_tit):
        for c in range(1, ws.max_column + 1):
            v = val(r, c)
            if isinstance(v, datetime):
                fecha = v.date().isoformat()
            s = txt(r, c)
            m = re.search(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})", s)
            if m and not fecha:
                d, mo, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
                a = a + 2000 if a < 100 else a
                try:
                    fecha = date(a, mo, d).isoformat()
                except ValueError:
                    pass
            if s and r == 1 and not m:
                titulo = limpiar(s)

    bloques, por_nombre = [], {}

    def bloque(nombre):
        clave = _sin_tildes(nombre)
        if clave not in por_nombre:
            por_nombre[clave] = {"nombre": nombre, "nota_ida": "", "nota_regreso": "",
                                 "reserva_ida_coche": "", "reserva_ida_trip": "",
                                 "reserva_regreso_coche": "", "reserva_regreso_trip": "", "salidas": []}
            bloques.append(por_nombre[clave])
        return por_nombre[clave]

    def es_hora(v):
        return bool(normalizar_hora(v)) and not (isinstance(v, str) and not re.match(r"^\s*\d", v))

    for gi, g in enumerate(grupos[:2]):
        lado = "ida" if gi == 0 else "regreso"
        actual = None
        r = fila_tit + 1
        while r <= ws.max_row:
            vh = val(r, g["hora"])
            th = txt(r, g["hora"])
            if th and not es_hora(vh):
                t = limpiar(th)
                if t.startswith("RESERVA"):
                    if actual:
                        coche = limpiar(txt(r, g["coche"]))
                        trips = [limpiar(txt(rr, g["trip"])) for rr in (r, r + 1) if txt(rr, g["trip"])]
                        dest = limpiar(txt(r, g["destino"]))
                        actual[f"reserva_{lado}_coche"] = coche
                        actual[f"reserva_{lado}_trip"] = " / ".join([x for x in [dest] + trips if x and x != coche])
                elif len(t) > 3:                       # título de corredor (lo corto, como "sub", se ignora)
                    nombre, nota = t, ""
                    if "-" in nombre:
                        nombre, nota = [x.strip() for x in nombre.split("-", 1)]
                    nombre = re.sub(r"\s+(IDA|REGRESO|VUELTA)\b.*$", "", nombre).strip()
                    actual = bloque(nombre)
                    if nota:
                        actual[f"nota_{lado}"] = limpiar(nota)
                r += 1
                continue
            if es_hora(vh) and actual is not None:
                trips = [limpiar(txt(r, g["trip"]))]
                # el segundo tripulante va en el renglón de abajo (la hora está combinada)
                if r + 1 <= ws.max_row and not txt(r + 1, g["hora"]):
                    trips.append(limpiar(txt(r + 1, g["trip"])))
                coche = val(r, g["coche"])
                coche = str(int(coche)) if isinstance(coche, (int, float)) else limpiar(coche)
                actual["salidas"].append({
                    "lado": lado, "hora": normalizar_hora(vh), "destino": limpiar(txt(r, g["destino"])),
                    "coche": coche, "trip1": trips[0] if trips else "", "trip2": trips[1] if len(trips) > 1 else ""})
            r += 1
    bloques = [b for b in bloques if b["salidas"]]
    if not bloques:
        raise ValueError("No encontré salidas en la planilla.")
    return fecha, titulo, bloques


def importar_excel(contenido, fecha_forzada=None):
    fecha_excel, titulo, bloques = leer_excel(contenido)
    fecha = fecha_forzada or fecha_excel
    if not fecha:
        raise ValueError("No encontré la fecha en la planilla: elegila antes de importar.")
    conn = get_connection()
    try:
        dia_id = crear_dia(fecha, conn)
        _bloquear_dia(conn, dia_id)
        vaciar_dia(conn, dia_id)
        conn.execute("UPDATE trafico_dias SET titulo=? WHERE id=?", (titulo or "HORARIOS NACIONALES", dia_id))
        n = 0
        for i, b in enumerate(bloques):
            cur = conn.execute("""INSERT INTO trafico_bloques (dia_id, orden, nombre, nota_ida, nota_regreso,
                                    reserva_ida_coche, reserva_ida_trip, reserva_regreso_coche, reserva_regreso_trip)
                                  VALUES (?,?,?,?,?,?,?,?,?)""",
                               (dia_id, i + 1, b["nombre"], b["nota_ida"], b["nota_regreso"],
                                b["reserva_ida_coche"], b["reserva_ida_trip"],
                                b["reserva_regreso_coche"], b["reserva_regreso_trip"]))
            bid = cur.lastrowid or conn.execute("SELECT MAX(id) AS m FROM trafico_bloques WHERE dia_id=?",
                                                (dia_id,)).fetchone()["m"]
            for s in b["salidas"]:
                conn.execute("""INSERT INTO trafico_salidas (dia_id, bloque_id, lado, hora, destino, coche, trip1, trip2)
                                VALUES (?,?,?,?,?,?,?,?)""",
                             (dia_id, bid, s["lado"], s["hora"], s["destino"], s["coche"], s["trip1"], s["trip2"]))
                _registrar_tripulantes(conn, [s["trip1"], s["trip2"]])
                n += 1
        _marcar_modificado(conn, dia_id)
        conn.commit()
        return fecha, n, fecha_excel
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# IMPORTAR LA PLANILLA INTERNACIONAL (varios días en una hoja)
# ════════════════════════════════════════════════════════════════════════════
# Como la arman hoy: cada día con su título ("viernes, 2 de octubre de 2026"),
# a la izquierda las idas (de acá a Retiro, Liniers, San Justo, La Plata) y a
# la derecha los regresos. Cada salida ocupa dos renglones: hora, destino y
# coche combinados y un tripulante por renglón. La hora puede traer la salida
# de antes ("00:20 CDE / 9:35 VCA"). El renglón amarillo de abajo de cada lado
# es la nota del día ("SIN RESERVA", "26300 LASTRE A ASU").

MESES = {"ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6, "JULIO": 7,
         "AGOSTO": 8, "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12}
_RE_FECHA_LARGA = re.compile(r"(\d{1,2})\s+DE\s+([A-Z]+)(?:\s+(?:DE|DEL)\s+(\d{4}))?")
_RE_FECHA_CORTA = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})\b")
_RE_HORA_LUGAR = re.compile(r"(\d{1,2})[:.](\d{2})(?:\s*(?:HS|H)\b)?\s*([A-Z][A-Z ]{1,20})?")


def _fecha_de_texto(v, anio_def=None):
    """Una fecha escrita como título de día: 'viernes, 2 de octubre de 2026',
    '02/10/2026' o una fecha de verdad de Excel."""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    t = _sin_tildes(limpiar(v))
    if not t or len(t) > 60:
        return None
    m = _RE_FECHA_LARGA.search(t)
    if m and m.group(2) in MESES:
        anio = int(m.group(3)) if m.group(3) else anio_def
        if anio:
            try:
                return date(anio, MESES[m.group(2)], int(m.group(1))).isoformat()
            except ValueError:
                return None
    m = _RE_FECHA_CORTA.search(t)
    if m and not re.search(r"\d{1,2}:\d{2}", t):
        d, mo, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
        a = a + 2000 if a < 100 else a
        try:
            return date(a, mo, d).isoformat()
        except ValueError:
            return None
    return None


def _hora_y_antes(v):
    """'00:20 CDE\\n9:35 VCA' → ('09:35', '00:20 CDE'); '12:30' → ('12:30', '').
    Si la celda trae varias horas, la última es la de la salida y las de antes
    van a la nota (sale antes de otro lado)."""
    if isinstance(v, (dtime, datetime)) or isinstance(v, (int, float)):
        return normalizar_hora(v), ""
    t = _sin_tildes(limpiar(v))
    if not t:
        return "", ""
    pares = []
    for m in _RE_HORA_LUGAR.finditer(t):
        h = normalizar_hora(f"{m.group(1)}:{m.group(2)}")
        if h:
            pares.append((h, (m.group(3) or "").strip()))
    if not pares:
        return "", ""
    hora = pares[-1][0]
    antes = " ".join(f"{h} {l}".strip() for h, l in pares[:-1])
    return hora, antes


def leer_excel_internacional(contenido):
    """Devuelve [{fecha, salidas: [...], nota_ida, nota_regreso}] con todos los
    días que encuentre en la primera hoja."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(contenido), data_only=True)
    ws = wb.worksheets[0]
    max_r, max_c = ws.max_row, ws.max_column

    # Celdas combinadas: el valor está arriba a la izquierda; las demás quedan "tapadas"
    tapada, alto = set(), {}
    for rg in ws.merged_cells.ranges:
        alto[(rg.min_row, rg.min_col)] = (rg.max_row, rg.max_col)
        for r in range(rg.min_row, rg.max_row + 1):
            for c in range(rg.min_col, rg.max_col + 1):
                if (r, c) != (rg.min_row, rg.min_col):
                    tapada.add((r, c))

    def val(r, c):
        if (r, c) in tapada or r < 1 or c < 1 or r > max_r or c > max_c:
            return None
        return ws.cell(r, c).value

    def txt(r, c):
        v = val(r, c)
        if v is None:
            return ""
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        return " ".join(str(v).split())

    def es_hora(v):
        if isinstance(v, (dtime,)):
            return True
        if isinstance(v, datetime):
            return v.year < 1901 or (v.hour or v.minute)       # una hora pura de Excel
        if isinstance(v, (int, float)):
            return 0 <= float(v) < 1 and float(v) > 0
        return bool(re.match(r"^\s*\d{1,2}[:.]\d{2}", str(v or "")))

    # 1. Los títulos de los días
    anio_def = None
    titulos = []
    for r in range(1, max_r + 1):
        f = None
        for c in range(1, max_c + 1):
            v = val(r, c)
            if v is None or (es_hora(v) and not isinstance(v, datetime)):
                continue
            if isinstance(v, datetime) and v.year < 1901:
                continue
            f = _fecha_de_texto(v, anio_def)
            if f:
                break
        if f:
            anio_def = int(f[:4])
            titulos.append((r, f))
    if not titulos:
        raise ValueError("No encontré los días en la planilla (los títulos tipo «viernes, 2 de octubre de 2026»).")

    # 2. Las columnas de hora: las que tienen horas en varios renglones
    cuenta = {}
    filas_titulo = {r for r, _ in titulos}
    for r in range(titulos[0][0] + 1, max_r + 1):
        if r in filas_titulo:
            continue
        for c in range(1, max_c + 1):
            v = val(r, c)
            if v is not None and es_hora(v):
                cuenta[c] = cuenta.get(c, 0) + 1
    cols_hora = sorted(c for c, n in cuenta.items() if n >= 2)
    # dos columnas de hora pegadas son la misma (ej. una columna auxiliar)
    limpias = []
    for c in cols_hora:
        if limpias and c - limpias[-1] <= 2:
            if cuenta[c] > cuenta[limpias[-1]]:
                limpias[-1] = c
            continue
        limpias.append(c)
    cols_hora = limpias[:2]
    if not cols_hora:
        raise ValueError("No encontré las columnas de las horas.")

    # 3. Para cada lado: destino, coche y tripulantes (lo que sigue a la hora)
    def armar_grupo(h, hasta):
        cols = list(range(h + 1, hasta))
        def puntaje(c, prueba):
            n = 0
            for r in range(titulos[0][0] + 1, max_r + 1):
                t = txt(r, c)
                if t and prueba(t):
                    n += 1
            return n
        es_coche = lambda t: bool(re.match(r"^(\d{3,6}|A\s*CONF\.?)$", _sin_tildes(t.upper())))
        coche = max(cols, key=lambda c: puntaje(c, es_coche), default=None)
        if coche is None or puntaje(coche, es_coche) == 0:
            raise ValueError("No encontré la columna de los coches.")
        antes = [c for c in cols if c < coche]
        despues = [c for c in cols if c > coche]
        hay_texto = lambda t: bool(re.search(r"[A-Za-z]", t))
        destino = max(antes, key=lambda c: puntaje(c, hay_texto), default=None)
        trip = max(despues, key=lambda c: puntaje(c, hay_texto), default=None)
        return {"hora": h, "destino": destino, "coche": coche, "trip": trip, "ultima": hasta - 1}

    grupos = []
    for i, h in enumerate(cols_hora):
        hasta = cols_hora[i + 1] if i + 1 < len(cols_hora) else max_c + 1
        grupos.append(armar_grupo(h, hasta))

    # 4. Cada día, cada lado
    dias = []
    for k, (r0, fecha) in enumerate(titulos):
        r_fin = titulos[k + 1][0] - 1 if k + 1 < len(titulos) else max_r
        dia = {"fecha": fecha, "salidas": [], "nota_ida": "", "nota_regreso": ""}
        for gi, g in enumerate(grupos):
            lado = "ida" if gi == 0 else "regreso"
            r = r0 + 1
            while r <= r_fin:
                vh = val(r, g["hora"])
                if vh is not None and es_hora(vh):
                    hora, antes = _hora_y_antes(vh)
                    # cuántos renglones ocupa la salida: lo combinado de la hora
                    # o, si no está combinada, hasta la próxima hora (máximo 2)
                    fin = alto.get((r, g["hora"]), (r, 0))[0]
                    if fin == r and r + 1 <= r_fin and val(r + 1, g["hora"]) is None and (r + 1, g["hora"]) not in tapada \
                            and txt(r + 1, g["trip"]) and not txt(r + 1, g["destino"]):
                        fin = r + 1
                    trips = [limpiar(txt(rr, g["trip"])) for rr in range(r, fin + 1)] if g["trip"] else []
                    trips = [t for t in trips if t]
                    coche = txt(r, g["coche"])
                    coche = limpiar(coche).rstrip(".") if not coche.isdigit() else coche
                    dia["salidas"].append({
                        "lado": lado, "hora": hora, "destino": limpiar(txt(r, g["destino"])) if g["destino"] else "",
                        "coche": coche, "trip1": trips[0] if trips else "", "trip2": trips[1] if len(trips) > 1 else "",
                        "nota": antes})
                    r = fin + 1
                    continue
                # Renglón sin hora: si tiene texto en la parte de la hora, el destino
                # o el coche (el renglón amarillo, combinado), es la nota del día
                ult = g["trip"] or g["coche"]
                textos = []
                for c in range(g["hora"], ult + 1):
                    if c == g["trip"] and not ((r, g["hora"]) in alto and alto[(r, g["hora"])][1] >= ult):
                        continue                          # un tripulante suelto no es nota
                    t = txt(r, c)
                    if t and t not in textos:
                        textos.append(t)
                nota = limpiar(" ".join(textos))
                if nota and not _fecha_de_texto(nota):
                    viejo = dia[f"nota_{lado}"]
                    dia[f"nota_{lado}"] = f"{viejo} · {nota}" if viejo else nota
                r += 1
        if dia["salidas"]:
            dias.append(dia)
    if not dias:
        raise ValueError("Encontré los días pero ninguna salida.")
    return dias


def importar_excel_internacional(contenido, probar=False):
    """Carga cada día de la planilla en su fecha (internacional). Si el día ya
    tenía tráfico, se reemplaza. Con probar=True solo dice qué haría."""
    dias = leer_excel_internacional(contenido)
    conn = get_connection()
    try:
        resumen = []
        # el nombre del corredor: el que ya usan en el internacional (si hay)
        r = conn.execute("""SELECT b.nombre FROM trafico_bloques b JOIN trafico_dias d ON d.id = b.dia_id
                            WHERE COALESCE(d.tipo,'nacional')='internacional' ORDER BY d.fecha DESC, b.orden LIMIT 1""").fetchone()
        nombre_def = r["nombre"] if r else "BUENOS AIRES"
        for d in dias:
            ya = _dia_por_fecha(conn, d["fecha"], "internacional")
            n_ya = 0
            nombre = nombre_def
            if ya:
                n_ya = conn.execute("SELECT COUNT(*) AS n FROM trafico_salidas WHERE dia_id=?", (ya["id"],)).fetchone()["n"]
                b = conn.execute("SELECT nombre FROM trafico_bloques WHERE dia_id=? ORDER BY orden, id LIMIT 1",
                                 (ya["id"],)).fetchone()
                if b:
                    nombre = b["nombre"]
            resumen.append({"fecha": d["fecha"], "salidas": len(d["salidas"]), "ya_tenia": n_ya,
                            "publicado": bool(ya and ya["version"]),
                            "ida": sum(1 for s in d["salidas"] if s["lado"] == "ida"),
                            "regreso": sum(1 for s in d["salidas"] if s["lado"] == "regreso"),
                            "coches": sorted({s["coche"] for s in d["salidas"] if s["coche"].isdigit()})})
            if probar:
                continue
            dia_id = crear_dia(d["fecha"], conn, "internacional")
            _bloquear_dia(conn, dia_id)
            vaciar_dia(conn, dia_id)
            cur = conn.execute("""INSERT INTO trafico_bloques (dia_id, orden, nombre, nota_ida, nota_regreso)
                                  VALUES (?,?,?,?,?)""", (dia_id, 1, nombre, d["nota_ida"], d["nota_regreso"]))
            bid = cur.lastrowid or conn.execute("SELECT MAX(id) AS m FROM trafico_bloques WHERE dia_id=?",
                                                (dia_id,)).fetchone()["m"]
            for s in d["salidas"]:
                conn.execute("""INSERT INTO trafico_salidas (dia_id, bloque_id, lado, hora, destino, coche, trip1, trip2, nota)
                                VALUES (?,?,?,?,?,?,?,?,?)""",
                             (dia_id, bid, s["lado"], s["hora"], s["destino"], s["coche"], s["trip1"], s["trip2"], s["nota"]))
                _registrar_tripulantes(conn, [s["trip1"], s["trip2"]])
            _marcar_modificado(conn, dia_id)
        if not probar:
            conn.commit()
        return resumen
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# PUBLICAR: versiones y cambios
# ════════════════════════════════════════════════════════════════════════════

def foto_del_dia(d):
    """Lo que se guarda al publicar: lo justo para rehacer el PDF y comparar."""
    return {"fecha": d["fecha"], "titulo": d["dia"]["titulo"], "bloques": [
        {k: b[k] for k in ("id", "nombre", "nota_ida", "nota_regreso", "reserva_ida_coche", "reserva_ida_trip",
                           "reserva_regreso_coche", "reserva_regreso_trip")}
        | {lado: [{k: s.get(k, "") for k in ("id", "hora", "destino", "coche", "trip1", "trip2", "nota")}
                  for s in b[lado]] for lado in LADOS}
        for b in d["bloques"]]}


def _describe(s):
    return f"{s['hora'] or '--:--'} {s['destino']}".strip()


def comparar(antes, ahora):
    """Qué cambió entre dos fotos del día, en frases cortas para el PDF."""
    if not antes:
        return []
    viejas = {s["id"]: s for b in antes["bloques"] for lado in LADOS for s in b[lado]}
    nuevas = {s["id"]: (s, b["nombre"], lado) for b in ahora["bloques"] for lado in LADOS for s in b[lado]}
    cambios = []
    for sid, (s, corredor, lado) in nuevas.items():
        v = viejas.get(sid)
        if not v:
            cambios.append({"id": sid, "tipo": "nueva", "txt": f"Nueva salida: {_describe(s)}"})
            continue
        partes = []
        if v["hora"] != s["hora"]:
            partes.append(f"hora {v['hora'] or '--:--'} → {s['hora'] or '--:--'}")
        if v["destino"] != s["destino"]:
            partes.append(f"tramo {v['destino']} → {s['destino']}")
        if v["coche"] != s["coche"]:
            if not v["coche"]:
                partes.append(f"va el coche {s['coche']}")
            elif not s["coche"]:
                partes.append(f"se sacó el coche {v['coche']}, queda a confirmar")
            else:
                partes.append(f"coche {v['coche']} → {s['coche']}")
        tv = [x for x in (v["trip1"], v["trip2"]) if x]
        tn = [x for x in (s["trip1"], s["trip2"]) if x]
        if sorted(tv) != sorted(tn):
            salen = [x for x in tv if x not in tn]
            entran = [x for x in tn if x not in tv]
            frases = []
            if salen:
                frases.append(("salen " if len(salen) > 1 else "sale ") + " y ".join(salen))
            if entran:
                frases.append(("entran " if len(entran) > 1 else "entra ") + " y ".join(entran))
            if frases:
                partes.append(", ".join(frases))
        if partes:
            cambios.append({"id": sid, "tipo": "cambio", "txt": f"{_describe(s)}: " + "; ".join(partes)})
    for sid, v in viejas.items():
        if sid not in nuevas:
            cambios.append({"id": sid, "tipo": "quitada", "txt": f"Se quitó la salida {_describe(v)}"})
    rv = {b["id"]: b for b in antes["bloques"]}
    for b in ahora["bloques"]:
        a = rv.get(b["id"])
        if not a:
            continue
        for lado in LADOS:
            if (a[f"reserva_{lado}_coche"], a[f"reserva_{lado}_trip"]) != (b[f"reserva_{lado}_coche"], b[f"reserva_{lado}_trip"]):
                r = " ".join(x for x in (b[f"reserva_{lado}_coche"], b[f"reserva_{lado}_trip"]) if x) or "sin reserva"
                cambios.append({"id": None, "tipo": "reserva", "txt": f"Reserva {b['nombre']} ({lado}): {r}"})
    return cambios


def publicar(fecha, usuario, tipo="nacional"):
    d = armar_dia(fecha, tipo=tipo)
    if not d.get("existe"):
        return None, "No hay tráfico armado para ese día."
    conn = get_connection()
    try:
        dia = d["dia"]
        ultima = conn.execute("""SELECT * FROM trafico_versiones WHERE dia_id=?
                                 ORDER BY version DESC LIMIT 1""", (dia["id"],)).fetchone()
        foto = foto_del_dia(d)
        cambios = comparar(json.loads(ultima["datos"]) if ultima else None, foto)
        if ultima and not cambios and not dia["modificado"]:
            return {"version": dia["version"], "cambios": [], "sin_cambios": True}, None
        version = (dia["version"] or 0) + 1
        cuando = _ahora()
        conn.execute("""INSERT INTO trafico_versiones (dia_id, version, publicado_el, publicado_por, datos, cambios)
                        VALUES (?,?,?,?,?,?)""",
                     (dia["id"], version, cuando, usuario, json.dumps(foto, ensure_ascii=False),
                      json.dumps(cambios, ensure_ascii=False)))
        conn.execute("""UPDATE trafico_dias SET version=?, publicado_el=?, publicado_por=?, modificado=0
                        WHERE id=?""", (version, cuando, usuario, dia["id"]))
        conn.commit()
        return {"version": version, "cambios": cambios, "publicado_el": cuando}, None
    finally:
        conn.close()


def versiones(fecha, tipo="nacional"):
    conn = get_connection()
    try:
        dia = _dia_por_fecha(conn, fecha, tipo)
        if not dia:
            return []
        return [dict(r) for r in conn.execute(
            """SELECT version, publicado_el, publicado_por, cambios FROM trafico_versiones
               WHERE dia_id=? ORDER BY version DESC""", (dia["id"],)).fetchall()]
    finally:
        conn.close()


def datos_para_pdf(fecha, version=None, tipo="nacional"):
    """Lo que necesita el PDF: el día armado (para borrador o la última versión
    sin cambios) o la foto de una versión publicada, con sus cambios."""
    tipo = tipo_ok(tipo)
    d = armar_dia(fecha, tipo=tipo)
    if not d.get("existe"):
        return None
    dia = d["dia"]
    info = {"fecha": fecha, "tipo": tipo, "nombre_dia": d["nombre_dia"], "titulo": dia["titulo"] or TITULOS[tipo],
            "version": dia["version"], "borrador": bool(dia["modificado"]) or not dia["version"],
            "publicado_el": dia["publicado_el"], "publicado_por": dia["publicado_por"],
            "cambios": [], "cambiadas": set(), "anterior": None}
    conn = get_connection()
    try:
        if version:
            v = conn.execute("SELECT * FROM trafico_versiones WHERE dia_id=? AND version=?",
                             (dia["id"], int(version))).fetchone()
            if v:
                foto = json.loads(v["datos"])
                d = _rearmar_desde_foto(foto, fecha, conn, tipo)
                info.update(version=v["version"], borrador=False, publicado_el=v["publicado_el"],
                            publicado_por=v["publicado_por"])
                info["cambios"] = json.loads(v["cambios"] or "[]")
        elif not info["borrador"]:
            v = conn.execute("SELECT * FROM trafico_versiones WHERE dia_id=? AND version=?",
                             (dia["id"], dia["version"])).fetchone()
            if v:
                info["cambios"] = json.loads(v["cambios"] or "[]")
        if info["version"] and info["version"] > 1:
            prev = conn.execute("SELECT publicado_el FROM trafico_versiones WHERE dia_id=? AND version=?",
                                (dia["id"], info["version"] - 1 if not info["borrador"] else info["version"])).fetchone()
            info["anterior"] = prev["publicado_el"] if prev else None
        if info["borrador"] and info["version"]:
            ultima = conn.execute("SELECT datos FROM trafico_versiones WHERE dia_id=? AND version=?",
                                  (dia["id"], dia["version"])).fetchone()
            if ultima:
                info["cambios"] = comparar(json.loads(ultima["datos"]), foto_del_dia(d))
        flota = _flota(conn)
    finally:
        conn.close()
    info["cambiadas"] = {c["id"] for c in info["cambios"] if c.get("id")}
    info["dia"] = d
    info["flota"] = flota
    return info


def _rearmar_desde_foto(foto, fecha, conn, tipo="nacional"):
    """Una versión vieja como si fuera el día armado (sin avisos: es historia)."""
    bloques = []
    for b in foto["bloques"]:
        nb = dict(b)
        for lado in LADOS:
            nb[lado] = []
            for s in b[lado]:
                ns = dict(s, lado=lado, avisos=[])
                ns["origen"], ns["llega"] = tramo(s["destino"], lado, b["nombre"], tipo)
                ns["destino_base"], ns["destino_extras"] = partes_destino(s["destino"])
                if not limpiar(s["coche"]).isdigit():
                    ns["avisos"].append({"nivel": "falta", "txt": "Falta el coche"})
                nb[lado].append(ns)
        bloques.append(nb)
    salidas = [s for b in bloques for lado in LADOS for s in b[lado]]
    return {"existe": True, "fecha": fecha, "nombre_dia": nombre_dia(fecha), "bloques": bloques,
            "dia": {"titulo": foto.get("titulo") or TITULOS[tipo_ok(tipo)]},
            "resumen": {"salidas": len(salidas),
                        "coches": len({limpiar(s["coche"]) for s in salidas if limpiar(s["coche"]).isdigit()}),
                        "tripulantes": len({limpiar(t) for s in salidas for t in (s["trip1"], s["trip2"]) if t}),
                        "a_confirmar": sum(1 for s in salidas if not limpiar(s["coche"]).isdigit()
                                           or not (s["trip1"] or s["trip2"])),
                        "con_aviso": 0}}


def dias_recientes(hasta, cantidad=21, tipo="nacional"):
    conn = get_connection()
    try:
        desde = (date.fromisoformat(hasta) - timedelta(days=cantidad)).isoformat()
        tope = (date.fromisoformat(hasta) + timedelta(days=7)).isoformat()
        return [dict(r) for r in conn.execute(
            """SELECT d.fecha, d.version, d.modificado,
                      (SELECT COUNT(*) FROM trafico_salidas s WHERE s.dia_id=d.id) AS salidas
               FROM trafico_dias d WHERE d.fecha BETWEEN ? AND ? AND COALESCE(d.tipo,'nacional')=?
               ORDER BY d.fecha DESC""",
            (desde, tope, tipo_ok(tipo))).fetchall()]
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ════════════════════════════════════════════════════════════════════════════

def _puede_ver():
    return session.get("rol") in ("admin", "taller", "auditor")


def _puede_editar():
    return session.get("rol") in ("admin", "taller")


def _quien():
    return session.get("nombre") or session.get("usuario") or ""


def _fecha_ok(f):
    try:
        return date.fromisoformat(f).isoformat()
    except (TypeError, ValueError):
        return None


def _tipo():
    """El tráfico que se está mirando: viene en la dirección (?tipo=), en el
    cuerpo o en el formulario. Sin nada, el nacional (como siempre)."""
    t = request.args.get("tipo")
    if not t and request.is_json:
        t = (request.get_json(silent=True) or {}).get("tipo")
    if not t:
        t = request.form.get("tipo")
    return tipo_ok(t)


def _etq(tipo):
    return "" if tipo == "nacional" else " internacional"


def _auditar(accion, detalle=""):
    try:
        from database import registrar_auditoria
        registrar_auditoria(usuario=_quien() or "?", rol=session.get("rol") or "",
                            accion=accion, categoria="Tráfico", detalle=detalle[:200])
    except Exception:
        pass


def dia_completo(fecha, tipo="nacional"):
    """El día para la pantalla: lo armado más lo que cambió desde la última
    versión publicada y de qué día se puede partir si está vacío."""
    tipo = tipo_ok(tipo)
    d = armar_dia(fecha, tipo=tipo)
    conn = get_connection()
    try:
        r = conn.execute("""SELECT d.fecha FROM trafico_dias d WHERE d.fecha < ? AND COALESCE(d.tipo,'nacional')=?
                            AND EXISTS (SELECT 1 FROM trafico_salidas s WHERE s.dia_id = d.id)
                            ORDER BY d.fecha DESC LIMIT 1""", (fecha, tipo)).fetchone()
        d["dia_anterior"] = r["fecha"] if r else None
        d["cambios_pendientes"] = []
        if d.get("existe") and d["dia"]["version"] and d["dia"]["modificado"]:
            u = conn.execute("SELECT datos FROM trafico_versiones WHERE dia_id=? AND version=?",
                             (d["dia"]["id"], d["dia"]["version"])).fetchone()
            if u:
                d["cambios_pendientes"] = comparar(json.loads(u["datos"]), foto_del_dia(d))
    finally:
        conn.close()
    d["puede_editar"] = _puede_editar()
    d["completables"] = (completar_con_ubicacion(fecha, simular=True, tipo=tipo)
                         if d.get("existe") and d["puede_editar"] else 0)
    return d


def _respuesta_dia(fecha, tipo="nacional", **extra):
    return jsonify({"ok": True, **extra, **dia_completo(fecha, tipo)})


@bp_trafico.route("/api/trafico/dia/<fecha>", methods=["GET"])
def api_dia(fecha):
    if not _puede_ver():
        return jsonify({"error": "Sin permiso"}), 403
    fecha = _fecha_ok(fecha)
    if not fecha:
        return jsonify({"error": "Fecha inválida"}), 400
    return jsonify(dia_completo(fecha, _tipo()))


@bp_trafico.route("/api/trafico/dias", methods=["GET"])
def api_dias():
    if not _puede_ver():
        return jsonify({"error": "Sin permiso"}), 403
    hasta = _fecha_ok(request.args.get("hasta")) or _ahora()[:10]
    return jsonify(dias_recientes(hasta, tipo=_tipo()))


@bp_trafico.route("/api/trafico/listas", methods=["GET"])
def api_listas():
    if not _puede_ver():
        return jsonify({"error": "Sin permiso"}), 403
    conn = get_connection()
    try:
        flota = _flota(conn)
    finally:
        conn.close()
    return jsonify({"tripulantes": lista_tripulantes(), "destinos": lista_destinos(_tipo()),
                    "coches": [{"coche": n, "modelo": f"{v['marca'] or ''} {v['modelo'] or ''}".strip()}
                               for n, v in sorted(flota.items(), key=lambda x: (len(x[0]), x[0]))
                               if v["activo"]]})


@bp_trafico.route("/api/trafico/dia/<fecha>/bloque", methods=["POST"])
def api_agregar_bloque(fecha):
    if not _puede_editar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    fecha = _fecha_ok(fecha)
    nombre = (request.json or {}).get("nombre", "")
    if not fecha or not limpiar(nombre):
        return jsonify({"ok": False, "msg": "Poné el nombre del corredor."}), 400
    tipo = _tipo()
    bid = agregar_bloque(fecha, nombre, tipo)
    return _respuesta_dia(fecha, tipo, bloque_id=bid)


@bp_trafico.route("/api/trafico/bloque/<int:bid>", methods=["PATCH", "DELETE"])
def api_bloque(bid):
    if not _puede_editar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    dia_id = borrar_bloque(bid) if request.method == "DELETE" else editar_bloque(bid, request.json or {})
    return _respuesta_por_dia_id(dia_id)


@bp_trafico.route("/api/trafico/bloque/<int:bid>/mover", methods=["POST"])
def api_mover_bloque(bid):
    if not _puede_editar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    return _respuesta_por_dia_id(mover_bloque(bid, int((request.json or {}).get("paso", 1))))


@bp_trafico.route("/api/trafico/bloque/<int:bid>/salida", methods=["POST"])
def api_agregar_salida(bid):
    if not _puede_editar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    d = request.json or {}
    sid = agregar_salida(bid, d.get("lado", "ida"), d)
    if not sid:
        return jsonify({"ok": False, "msg": "No existe ese corredor"}), 404
    conn = get_connection()
    try:
        r = conn.execute("""SELECT d.fecha, COALESCE(d.tipo,'nacional') AS tipo FROM trafico_salidas s
                            JOIN trafico_dias d ON d.id=s.dia_id WHERE s.id=?""", (sid,)).fetchone()
    finally:
        conn.close()
    return _respuesta_dia(r["fecha"], r["tipo"], salida_id=sid)


@bp_trafico.route("/api/trafico/salida/<int:sid>", methods=["PATCH", "DELETE"])
def api_salida(sid):
    if not _puede_editar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    dia_id = borrar_salida(sid) if request.method == "DELETE" else editar_salida(sid, request.json or {})
    return _respuesta_por_dia_id(dia_id)


def _respuesta_por_dia_id(dia_id):
    if not dia_id:
        return jsonify({"ok": False, "msg": "No se encontró"}), 404
    conn = get_connection()
    try:
        r = conn.execute("SELECT fecha, COALESCE(tipo,'nacional') AS tipo FROM trafico_dias WHERE id=?",
                         (dia_id,)).fetchone()
    finally:
        conn.close()
    return _respuesta_dia(r["fecha"], r["tipo"])


@bp_trafico.route("/api/trafico/salida/<int:sid>/sugerencias", methods=["GET"])
def api_sugerencias(sid):
    if not _puede_ver():
        return jsonify({"error": "Sin permiso"}), 403
    r = sugerencias(sid)
    return jsonify(r) if r else (jsonify({"error": "No existe"}), 404)


@bp_trafico.route("/api/trafico/dia/<fecha>/completar", methods=["POST"])
def api_completar(fecha):
    if not _puede_editar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    fecha = _fecha_ok(fecha)
    tipo = _tipo()
    n = completar_con_ubicacion(fecha, tipo=tipo)
    if n:
        _auditar(f"Completó {n} regreso(s) del tráfico{_etq(tipo)} del {fecha} con los coches que estaban allá")
    return _respuesta_dia(fecha, tipo, completadas=n)


@bp_trafico.route("/api/trafico/dia/<fecha>/copiar", methods=["POST"])
def api_copiar(fecha):
    if not _puede_editar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    fecha = _fecha_ok(fecha)
    d = request.json or {}
    desde = _fecha_ok(d.get("desde"))
    if not fecha or not desde:
        return jsonify({"ok": False, "msg": "Elegí de qué día copiar."}), 400
    tipo = _tipo()
    ok, msg = copiar_dia(fecha, desde, bool(d.get("con_asignaciones", True)), tipo)
    if not ok:
        return jsonify({"ok": False, "msg": msg}), 400
    # "Armar desde ayer": los horarios de ayer y en cada regreso el coche que quedó allá
    n = completar_con_ubicacion(fecha, tipo=tipo) if d.get("completar") else 0
    _auditar(f"Armó el tráfico{_etq(tipo)} del {fecha} copiando el del {desde}")
    return _respuesta_dia(fecha, tipo, completadas=n)


@bp_trafico.route("/api/trafico/dia/<fecha>", methods=["DELETE"])
def api_vaciar(fecha):
    if not _puede_editar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    fecha = _fecha_ok(fecha)
    tipo = _tipo()
    conn = get_connection()
    try:
        dia = _dia_por_fecha(conn, fecha, tipo)
        if dia:
            _bloquear_dia(conn, dia["id"])
            vaciar_dia(conn, dia["id"])
            _marcar_modificado(conn, dia["id"])
            conn.commit()
    finally:
        conn.close()
    _auditar(f"Vació el tráfico{_etq(tipo)} del {fecha}")
    return _respuesta_dia(fecha, tipo)


@bp_trafico.route("/api/trafico/importar", methods=["POST"])
def api_importar():
    if not _puede_editar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    f = request.files.get("archivo")
    if not f:
        return jsonify({"ok": False, "msg": "Elegí el archivo de Excel."}), 400
    if _tipo() == "internacional":
        # La planilla internacional trae varios días: cada uno va a su fecha
        probar = request.form.get("probar") == "1"
        try:
            dias = importar_excel_internacional(f.read(), probar=probar)
        except ValueError as e:
            return jsonify({"ok": False, "msg": str(e)}), 400
        except Exception as e:
            return jsonify({"ok": False, "msg": f"No se pudo leer la planilla ({str(e)[:80]})."}), 400
        if probar:
            return jsonify({"ok": True, "probar": True, "dias": dias})
        n = sum(d["salidas"] for d in dias)
        _auditar(f"Importó el tráfico internacional desde Excel ({len(dias)} día{'s' if len(dias) != 1 else ''}, {n} salidas)",
                 ", ".join(d["fecha"] for d in dias))
        fecha_ver = _fecha_ok(request.form.get("ver")) or dias[0]["fecha"]
        return _respuesta_dia(fecha_ver, "internacional", importadas=n, dias_importados=dias)
    try:
        fecha, n, fecha_excel = importar_excel(f.read(), _fecha_ok(request.form.get("fecha")))
    except ValueError as e:
        return jsonify({"ok": False, "msg": str(e)}), 400
    except Exception as e:
        return jsonify({"ok": False, "msg": f"No se pudo leer la planilla ({str(e)[:80]})."}), 400
    _auditar(f"Importó el tráfico del {fecha} desde Excel ({n} salidas)")
    return _respuesta_dia(fecha, importadas=n, fecha_excel=fecha_excel)


@bp_trafico.route("/api/trafico/dia/<fecha>/publicar", methods=["POST"])
def api_publicar(fecha):
    if not _puede_editar():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    fecha = _fecha_ok(fecha)
    tipo = _tipo()
    r, err = publicar(fecha, _quien(), tipo)
    if err:
        return jsonify({"ok": False, "msg": err}), 400
    if not r.get("sin_cambios"):
        _auditar(f"Publicó el tráfico{_etq(tipo)} del {fecha} (versión {r['version']})",
                 f"{len(r['cambios'])} cambio(s)" if r["cambios"] else "")
    return jsonify({"ok": True, **r, "estado": dia_completo(fecha, tipo)})


@bp_trafico.route("/api/trafico/dia/<fecha>/versiones", methods=["GET"])
def api_versiones(fecha):
    if not _puede_ver():
        return jsonify({"error": "Sin permiso"}), 403
    return jsonify(versiones(_fecha_ok(fecha), _tipo()))


def _nombre_archivo(fecha, info, ext):
    d = date.fromisoformat(fecha)
    nombre = ("Trafico-Internacional-" if info.get("tipo") == "internacional" else "Trafico-") + \
        f"{DIAS_SEMANA[d.weekday()].capitalize()}-{d.strftime('%d-%m-%y')}"
    nombre += f"-v{info['version']}" if not info["borrador"] and info["version"] else "-borrador"
    return _sin_tildes(nombre) + ext


@bp_trafico.route("/api/trafico/dia/<fecha>/pdf", methods=["GET"])
def api_pdf(fecha):
    if not _puede_ver():
        return jsonify({"error": "Sin permiso"}), 403
    fecha = _fecha_ok(fecha)
    info = datos_para_pdf(fecha, request.args.get("v"), _tipo())
    if not info:
        return jsonify({"error": "No hay tráfico armado para ese día"}), 404
    from trafico_pdf import generar_pdf_trafico
    pdf = generar_pdf_trafico(info)
    return send_file(io.BytesIO(pdf), mimetype="application/pdf",
                     as_attachment=request.args.get("descargar") == "1",
                     download_name=_nombre_archivo(fecha, info, ".pdf"))


@bp_trafico.route("/api/trafico/dia/<fecha>/imagen", methods=["GET"])
def api_imagen(fecha):
    """La misma hoja del PDF como imagen PNG (se ve directo en el chat)."""
    if not _puede_ver():
        return jsonify({"error": "Sin permiso"}), 403
    fecha = _fecha_ok(fecha)
    info = datos_para_pdf(fecha, request.args.get("v"), _tipo())
    if not info:
        return jsonify({"error": "No hay tráfico armado para ese día"}), 404
    try:
        from trafico_pdf import generar_imagen_trafico
        png = generar_imagen_trafico(info)
    except ImportError:
        return jsonify({"error": "Falta instalar pypdfium2 en el servidor (requirements-nube.txt)"}), 501
    return send_file(io.BytesIO(png), mimetype="image/png",
                     as_attachment=request.args.get("descargar") == "1",
                     download_name=_nombre_archivo(fecha, info, ".png"))
