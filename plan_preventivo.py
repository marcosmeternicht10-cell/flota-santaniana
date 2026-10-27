"""
plan_preventivo.py — El plan preventivo por kilómetro (La Santaniana)

Todo lo del preventivo en un lugar:

  · Estado de cada coche y de toda la flota: qué le toca, cuántos km faltan y
    para qué día cae, según lo que anda por día (sale de las cargas de
    combustible y de las OT; se puede fijar a mano).
  · "Cada cuánto": el intervalo es el del plan, pero se puede cambiar para un
    coche solo (este coche cambia el aceite cada 12.000 y no cada 15.000).
  · Agenda del taller con turnos: se elige el coche y el día, el sistema
    sugiere la fecha y avisa si el día está lleno (cupos por día).
  · Conectado con la OT: cuando un ítem de la OT queda completado y es una
    tarea del plan ("cambio de aceite" → Aceite de motor), se carga solo en el
    preventivo con el km de la OT. Si se borra el ítem o la OT, se saca.
  · Cumplimiento por coche y de la flota: si se hizo a tiempo (con una
    tolerancia) o tarde, cuántos km de atraso, turnos cumplidos.

Lo que ya estaba cargado (planes, tareas, registros) se respeta tal cual.

Enganche en app.py:
    from plan_preventivo import bp_prev, init_plan_preventivo
    init_plan_preventivo()
    app.register_blueprint(bp_prev)
"""

import re
import unicodedata
from datetime import date, timedelta
from functools import lru_cache

from flask import Blueprint, request, jsonify, session
from db_compat import get_connection, USE_POSTGRES

import database as db
from hora_local import hoy as _hoy_txt, ahora_iso

bp_prev = Blueprint("plan_preventivo", __name__)

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"

CONFIG_DEFECTO = {
    "cupos_dia": "4",            # cuántos coches entran por día al taller
    "dias_taller": "1,2,3,4,5,6",  # lunes a sábado (1 = lunes … 7 = domingo)
    "aviso_dias": "15",          # "próximo" si vence en estos días…
    "aviso_km": "1500",          # …o si faltan estos km
    "tolerancia_pct": "10",      # se hizo "a tiempo" hasta un 10 % pasado
}
ESTADOS_TURNO = ("agendado", "en_taller", "cumplido", "cancelado", "ausente")
TURNO_ACTIVO = ("agendado", "en_taller")
KM_DIA_DEFECTO = 250.0


# ════════════════════════════════════════════════════════════════════════════
# TABLAS
# ════════════════════════════════════════════════════════════════════════════

def _agregar_columnas(conn, tabla, columnas):
    for col, tipo in columnas:
        try:
            if USE_POSTGRES:
                conn.execute(f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS {col} {tipo}")
            else:
                existentes = {r["name"] for r in conn.execute(f"PRAGMA table_info({tabla})").fetchall()}
                if col not in existentes:
                    conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {tipo}")
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass


def init_plan_preventivo():
    conn = get_connection()
    _agregar_columnas(conn, "vehiculos", [("km_dia_manual", "REAL DEFAULT 0")])
    _agregar_columnas(conn, "mantenimientos_realizados", [
        ("ot_id", "INTEGER"),
        ("ot_item_id", "INTEGER"),
        ("turno_id", "INTEGER"),
        ("origen", "TEXT DEFAULT 'manual'"),        # manual | ot | inicial
        ("registrado_por", "TEXT DEFAULT ''"),
        ("intervalo_km", "INTEGER"),                # el "cada cuánto" que regía
    ])
    # '' = todavía no se decidió (al completarse se busca solo)
    # '12,15' = tareas del plan que hace este ítem · '-' = no es del plan
    _agregar_columnas(conn, "ot_items", [("tareas_plan", "TEXT DEFAULT ''")])
    for sql in (
        f"""CREATE TABLE IF NOT EXISTS prev_intervalos (
            id {PK},
            vehiculo_id INTEGER NOT NULL,
            tarea_id INTEGER NOT NULL,
            intervalo_km INTEGER NOT NULL,
            actualizado_por TEXT DEFAULT '',
            actualizado_el TEXT DEFAULT '',
            UNIQUE (vehiculo_id, tarea_id))""",
        f"""CREATE TABLE IF NOT EXISTS taller_turnos (
            id {PK},
            vehiculo_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            hora TEXT DEFAULT '',
            tareas TEXT DEFAULT '',
            notas TEXT DEFAULT '',
            estado TEXT DEFAULT 'agendado',
            ot_id INTEGER,
            km_previsto REAL DEFAULT 0,
            motivo TEXT DEFAULT '',
            creado_por TEXT DEFAULT '',
            creado_el TEXT DEFAULT '',
            cerrado_el TEXT DEFAULT '')""",
        """CREATE TABLE IF NOT EXISTS prev_config (
            clave TEXT PRIMARY KEY,
            valor TEXT DEFAULT '')""",
        """CREATE TABLE IF NOT EXISTS prev_cupos_dia (
            fecha TEXT PRIMARY KEY,
            cupo INTEGER DEFAULT 0)""",
        "CREATE INDEX IF NOT EXISTS ix_turnos_fecha ON taller_turnos (fecha)",
        "CREATE INDEX IF NOT EXISTS ix_turnos_veh ON taller_turnos (vehiculo_id)",
        "CREATE INDEX IF NOT EXISTS ix_mantreal_item ON mantenimientos_realizados (ot_item_id)",
        "CREATE INDEX IF NOT EXISTS ix_mantreal_veh ON mantenimientos_realizados (vehiculo_id)",
    ):
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
    # Los técnicos que van a hacer el turno (números del personal, separados por coma)
    _agregar_columnas(conn, "taller_turnos", [("tecnicos", "TEXT DEFAULT ''")])
    conn.close()


# ════════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN DEL TALLER
# ════════════════════════════════════════════════════════════════════════════

def _cfg(conn=None):
    propia = conn is None
    if propia:
        conn = get_connection()
    c = dict(CONFIG_DEFECTO)
    try:
        for r in conn.execute("SELECT clave, valor FROM prev_config").fetchall():
            c[r["clave"]] = r["valor"]
    except Exception:
        pass
    if propia:
        conn.close()

    def entero(k, defecto):
        try:
            return int(float(c.get(k)))
        except (TypeError, ValueError):
            return defecto
    dias = []
    for x in str(c.get("dias_taller") or "").split(","):
        try:
            n = int(x)
            if 1 <= n <= 7:
                dias.append(n)
        except ValueError:
            pass
    return {
        "cupos_dia": max(0, entero("cupos_dia", 4)),
        "dias_taller": sorted(set(dias)) or [1, 2, 3, 4, 5, 6],
        "aviso_dias": max(0, entero("aviso_dias", 15)),
        "aviso_km": max(0, entero("aviso_km", 1500)),
        "tolerancia_pct": max(0, entero("tolerancia_pct", 10)),
    }


def guardar_config(d):
    conn = get_connection()
    for k in CONFIG_DEFECTO:
        if k not in d:
            continue
        v = d[k]
        if k == "dias_taller":
            if isinstance(v, (list, tuple)):
                v = ",".join(str(int(x)) for x in v if 1 <= int(x) <= 7)
        else:
            v = str(max(0, int(float(v or 0))))
        # (con ON CONFLICT: la tabla no tiene columna id)
        conn.execute("""INSERT INTO prev_config (clave, valor) VALUES (?,?)
                        ON CONFLICT (clave) DO UPDATE SET valor=excluded.valor""", (k, str(v)))
    conn.commit()
    conn.close()
    return _cfg()


def _cupos_especiales(conn, desde, hasta):
    try:
        return {r["fecha"]: int(r["cupo"] or 0) for r in conn.execute(
            "SELECT fecha, cupo FROM prev_cupos_dia WHERE fecha >= ? AND fecha <= ?", (desde, hasta)).fetchall()}
    except Exception:
        return {}


def _cupo_dia(fecha, cfg, especiales):
    if fecha in especiales:
        return especiales[fecha]
    try:
        dsem = date.fromisoformat(fecha).isoweekday()
    except ValueError:
        return 0
    return cfg["cupos_dia"] if dsem in cfg["dias_taller"] else 0


def guardar_cupo_dia(fecha, cupo):
    conn = get_connection()
    if cupo is None or cupo == "":
        conn.execute("DELETE FROM prev_cupos_dia WHERE fecha=?", (fecha,))
    else:
        conn.execute("""INSERT INTO prev_cupos_dia (fecha, cupo) VALUES (?,?)
                        ON CONFLICT (fecha) DO UPDATE SET cupo=excluded.cupo""", (fecha, max(0, int(cupo))))
    conn.commit()
    conn.close()


# ════════════════════════════════════════════════════════════════════════════
# TEXTO: qué tarea del plan es un ítem de la OT
# ════════════════════════════════════════════════════════════════════════════
# "Cambio de aceite y filtro" tiene que dar Aceite de motor + Filtro de aceite
# de motor, y "Pérdida de aceite en cárter" no tiene que dar nada.

_FRASES = [
    (r"aire acondicionado", "cabina"),
    (r"caja de cambios?", "caja"),
    (r"i ?shift", "caja"),
    (r"freno motor", "frenomotor"),
    (r"liquido de freno", "liquido freno"),
]
_SINONIMOS = {
    "lubricante": "aceite", "aceit": "aceite",
    "gasoil": "combustible", "gasoleo": "combustible", "diesel": "combustible", "combust": "combustible",
    "engrasar": "engrase", "engrasado": "engrase", "grasa": "engrase", "engrasada": "engrase",
    "lubricacion": "engrase",
    "calibrar": "calibracion", "regular": "calibracion", "regulacion": "calibracion", "reglaje": "calibracion",
    "calibrado": "calibracion",
    "taque": "valvula", "taques": "valvula",
    "separador": "racor", "trampa": "racor",
    "scr": "adblue", "urea": "adblue", "arla": "adblue",
    "retardador": "retarder", "intarder": "retarder",
    "hidraulica": "direccion", "hidraulico": "direccion",
    "transmision": "caja",
    "puente": "diferencial", "corona": "diferencial",
    "habitaculo": "cabina", "polen": "cabina",
    "revisar": "inspeccion", "revision": "inspeccion", "verificar": "inspeccion", "verificacion": "inspeccion",
    "chequear": "inspeccion", "chequeo": "inspeccion", "inspeccionar": "inspeccion", "control": "inspeccion",
    "controlar": "inspeccion",
    "frenos": "freno", "valvulas": "valvula",
    "veb": "frenomotor",
}
_STOP = {"de", "del", "la", "las", "el", "los", "y", "e", "en", "a", "al", "con", "por", "para", "un",
         "una", "se", "que", "lo", "le", "su", "sus", "cambio", "cambiar", "cambiado", "cambia",
         "reemplazo", "reemplazar", "reemplazado", "colocar", "colocacion", "poner", "nuevo", "nueva",
         "mantenimiento", "hacer", "realizar", "realizado", "hecho", "si", "aplica", "euro", "km", "kms",
         "cada", "trabajo", "x2", "2", "completo", "total", "service", "servicio", "preventivo", "o"}
_NEGATIVAS = {"perdida", "fuga", "ruido", "falla", "roto", "rotura", "pierde", "gotea", "goteo", "mancha",
              "humo", "nivel", "completar", "agregar", "rellenar", "reponer", "pinchado", "quemado",
              "golpe", "vibracion", "olor"}
# Palabras que distinguen una tarea de otra: si el ítem las nombra y la tarea
# no, no es esa tarea ("aceite de caja" no es "Aceite de motor").
_CLAVE = {"filtro", "aceite", "caja", "diferencial", "direccion", "retarder", "cabina", "secador",
          "combustible", "adblue", "valvula", "freno", "frenomotor", "purificador", "racor", "secundario",
          "distribucion", "correa", "aire", "liquido", "engrase", "inspeccion", "calibracion",
          "refrigerante", "embrague", "bateria", "bujia", "pastilla", "zapata", "amortiguador"}
# Lo que cuenta para "qué es" una tarea (marcas, códigos y números no)
_VOCAB = _CLAVE | {"motor", "primario", "agua", "radiador", "bomba", "inyector", "turbo", "tensor",
                   "polea", "rodamiento", "alineacion", "balanceo", "centrifugo", "general"}
_OPCIONALES = {"motor", "primario", "general", "centrifugo", "agua"}
_SIST_ACEITE = {"caja", "diferencial", "direccion", "retarder"}
_DE_FILTRO = {"aire", "combustible", "cabina", "adblue", "secador", "racor"}


def _sin_acentos(s):
    s = unicodedata.normalize("NFKD", str(s or "").lower())
    return "".join(c for c in s if not unicodedata.combining(c))


def _raiz(p):
    if len(p) > 4 and p.endswith("es") and p[-3] in "lrnd":
        return p[:-2]
    if len(p) > 3 and p.endswith("s") and not p.endswith("ss"):
        return p[:-1]
    return p


def _tokens(texto):
    t = _sin_acentos(texto)
    for patron, reemplazo in _FRASES:
        t = re.sub(patron, reemplazo, t)
    t = re.sub(r"[^a-z0-9]+", " ", t)
    salida = []
    for p in t.split():
        p = _SINONIMOS.get(p, p)
        p = _SINONIMOS.get(_raiz(p), _raiz(p))
        if p in _STOP or not p:
            continue
        salida.append(p)
    return salida


@lru_cache(maxsize=4096)
def _nombre_norm(tarea):
    return " ".join(sorted(set(_tokens(tarea))))


@lru_cache(maxsize=4096)
def _firma_tarea(nombre):
    """(lo que define a la tarea, todas sus palabras)."""
    fuera = re.sub(r"\([^)]*\)", " ", str(nombre or ""))
    todas = set(_tokens(nombre))
    nucleo = (set(_tokens(fuera)) & _VOCAB) - _OPCIONALES
    if not nucleo:
        nucleo = {p for p in _tokens(fuera) if not p.isdigit() and len(p) > 2} - _OPCIONALES
    return frozenset(nucleo), frozenset(todas)


def _segmentos(texto):
    t = _sin_acentos(texto)
    partes = re.split(r"\s+y\s+|\s+e\s+|,|\+|/|;|\s+mas\s+|\s+con\s+|\n", t)
    segs = [set(_tokens(p)) for p in partes]
    segs = [s for s in segs if s]
    # Lo que no se repite se sobreentiende: "aceite y filtro" → filtro de aceite;
    # "aceite y filtro de caja" → aceite de caja.
    for i, s in enumerate(segs):
        prev = segs[i - 1] if i > 0 else set()
        nxt = segs[i + 1] if i + 1 < len(segs) else set()
        if "secador" in s:
            s.add("aire")
        # "filtro de combustible y racor" → filtro racor
        if "filtro" not in s and "aceite" not in s and "filtro" in prev and s & _DE_FILTRO:
            s.add("filtro")
        if "filtro" in s and not (s & (_CLAVE - {"filtro", "inspeccion"})):
            if prev & _SIST_ACEITE:
                s |= prev & _SIST_ACEITE
            elif "aceite" in prev:
                s.add("aceite")
            elif nxt & _SIST_ACEITE:
                s |= nxt & _SIST_ACEITE
        if "aceite" in s and not (s & _SIST_ACEITE) and "filtro" not in s:
            if nxt & _SIST_ACEITE and not ("filtro" in nxt and "aceite" in nxt):
                s |= nxt & _SIST_ACEITE
    return segs


def _numero_service(texto):
    """'service de 15.000', 'mantenimiento 60 mil' → 15000 / 60000."""
    t = _sin_acentos(texto)
    m = re.search(r"(?:service|servicio|preventivo|mantenimiento|revision)\D{0,14}?"
                  r"(\d{1,3}(?:[.\s]\d{3})+|\d{4,6}|\d{1,3}\s*(?:mil|k)\b)", t)
    if not m:
        return None
    s = m.group(1)
    if re.search(r"mil|k", s):
        return int(re.sub(r"\D", "", s)) * 1000
    return int(re.sub(r"\D", "", s))


def sugerir_tareas(descripcion, tareas):
    """Las tareas del plan que hace un ítem. tareas: [{id, tarea, intervalo_km}].
    Devuelve la lista de ids (vacía si no se reconoce con seguridad)."""
    if not descripcion or not tareas:
        return []
    n = _numero_service(descripcion)
    if n:
        ids = [t["id"] for t in tareas if int(t.get("intervalo_km") or 0) == n]
        if ids:
            return ids
    segs = _segmentos(descripcion)
    if not segs:
        return []
    firmas = {t["id"]: _firma_tarea(t["tarea"]) for t in tareas}

    def mejores(toks):
        if toks & _NEGATIVAS:
            return []
        cands = []
        for tid, (nucleo, todas) in firmas.items():
            if not nucleo:
                continue
            if not nucleo <= toks:
                # "Aceite y filtro de caja" también se cumple con "cambio de
                # aceite de caja" (el filtro va con el aceite).
                if not ({"aceite", "filtro"} <= nucleo and nucleo & _SIST_ACEITE
                        and (nucleo - {"filtro"}) <= toks):
                    continue
            if (toks & _CLAVE) - todas:
                continue
            sobra = len(((todas & (_VOCAB | {"secundario"})) - _OPCIONALES) - toks)
            cands.append((sobra, tid))
        if not cands:
            return []
        menor = min(c[0] for c in cands)
        return [tid for s, tid in cands if s == menor]

    elegidas = []
    for s in segs:
        for tid in mejores(s):
            if tid not in elegidas:
                elegidas.append(tid)
    if len(segs) > 1:
        juntas = set().union(*segs)
        if not (juntas & _NEGATIVAS):
            for tid in mejores(juntas):
                if tid not in elegidas:
                    elegidas.append(tid)
    return elegidas


def _ids(texto):
    out = []
    for x in str(texto or "").split(","):
        x = x.strip()
        if x.isdigit():
            out.append(int(x))
    return out


# ════════════════════════════════════════════════════════════════════════════
# DATOS DE TODA LA FLOTA (pocas consultas grandes)
# ════════════════════════════════════════════════════════════════════════════

def _en(vids):
    vids = list(vids)
    return ",".join("?" * len(vids)), vids


class _Ctx:
    pass


def _cargar(conn, vids=None):
    """Junta todo lo que hace falta para el estado del preventivo de varios
    coches (o de toda la flota activa)."""
    c = _Ctx()
    c.hoy = _hoy_txt()
    c.hoy_ord = date.fromisoformat(c.hoy).toordinal()
    c.cfg = _cfg(conn)
    if vids:
        marcas, ps = _en(vids)
        filas = conn.execute(f"SELECT * FROM vehiculos WHERE id IN ({marcas})", ps).fetchall()
    else:
        filas = conn.execute("SELECT * FROM vehiculos WHERE activo=1").fetchall()
    c.veh = {r["id"]: dict(r) for r in filas}
    ids = list(c.veh.keys())
    c.ids = ids
    if not ids:
        c.km, c.plan, c.tareas, c.over, c.regs, c.turnos, c.en_ot, c.lect = {}, {}, {}, {}, {}, {}, {}, {}
        c.km_dia = {}
        return c
    marcas, ps = _en(ids)
    c.km = db.km_actual_flota(conn, ids)
    c.plan = {}
    for r in conn.execute(f"""SELECT vp.vehiculo_id, vp.plan_id, vp.km_inicial, p.nombre AS plan_nombre
                              FROM vehiculo_plan vp JOIN planes_mantenimiento p ON p.id = vp.plan_id
                              WHERE vp.vehiculo_id IN ({marcas})""", ps).fetchall():
        c.plan[r["vehiculo_id"]] = dict(r)
    planes = sorted({p["plan_id"] for p in c.plan.values()})
    c.tareas = {}
    if planes:
        mp, pp = _en(planes)
        for r in conn.execute(f"""SELECT id, plan_id, tarea, intervalo_km, categoria FROM tareas_plan
                                  WHERE plan_id IN ({mp}) ORDER BY intervalo_km, tarea""", pp).fetchall():
            c.tareas.setdefault(r["plan_id"], []).append(dict(r))
    c.over = {}
    for r in conn.execute(f"SELECT vehiculo_id, tarea_id, intervalo_km FROM prev_intervalos WHERE vehiculo_id IN ({marcas})",
                          ps).fetchall():
        c.over[(r["vehiculo_id"], r["tarea_id"])] = int(r["intervalo_km"] or 0)
    c.regs = {}
    for r in conn.execute(f"""SELECT m.id, m.vehiculo_id, m.tarea_plan_id, m.fecha, m.km, m.costo, m.observaciones,
                                     m.ot_id, m.ot_item_id, m.turno_id, COALESCE(m.origen,'manual') AS origen,
                                     COALESCE(m.registrado_por,'') AS registrado_por, m.intervalo_km,
                                     t.tarea, t.categoria, t.intervalo_km AS intervalo_tarea
                              FROM mantenimientos_realizados m LEFT JOIN tareas_plan t ON t.id = m.tarea_plan_id
                              WHERE m.vehiculo_id IN ({marcas})""", ps).fetchall():
        c.regs.setdefault(r["vehiculo_id"], []).append(dict(r))
    c.turnos = {}
    for r in conn.execute(f"""SELECT * FROM taller_turnos WHERE vehiculo_id IN ({marcas})
                              AND estado IN ('agendado','en_taller') ORDER BY fecha, hora""", ps).fetchall():
        c.turnos.setdefault(r["vehiculo_id"], []).append(dict(r))
    c.en_ot = {}
    for r in conn.execute(f"""SELECT i.id AS item_id, i.estado, COALESCE(i.tareas_plan,'') AS tareas_plan,
                                     o.id AS ot_id, o.vehiculo_id
                              FROM ot_items i JOIN ordenes_trabajo o ON o.id = i.ot_id
                              WHERE o.vehiculo_id IN ({marcas}) AND COALESCE(o.estado,'') <> 'cerrada'
                                AND COALESCE(i.estado,'') <> 'completado'
                                AND COALESCE(i.tareas_plan,'') NOT IN ('', '-')""", ps).fetchall():
        for tid in _ids(r["tareas_plan"]):
            c.en_ot.setdefault(r["vehiculo_id"], {})[tid] = r["ot_id"]
    c.lect = _lecturas_km(conn, ids, c.hoy_ord)
    c.km_dia = _km_dia_todos(c)
    return c


def _lecturas_km(conn, ids, hoy_ord):
    """Lecturas de odómetro (fecha, km) de cada coche en los últimos meses:
    cargas de combustible, OT, preventivos, correctivos e historial."""
    desde = date.fromordinal(hoy_ord - 130).isoformat()
    marcas, ps = _en(ids)
    lect = db._lecturas_combustible(conn, ids, desde)
    for sql in (
        f"SELECT vehiculo_id, fecha_apertura AS fecha, km FROM ordenes_trabajo WHERE km > 0 AND fecha_apertura >= ? AND vehiculo_id IN ({marcas})",
        f"SELECT vehiculo_id, fecha, km FROM mantenimientos_realizados WHERE km > 0 AND fecha >= ? AND vehiculo_id IN ({marcas})",
        f"SELECT vehiculo_id, fecha, km FROM correctivos WHERE km > 0 AND fecha >= ? AND vehiculo_id IN ({marcas})",
        f"SELECT vehiculo_id, fecha, km FROM historial_eventos WHERE km > 0 AND fecha >= ? AND vehiculo_id IN ({marcas})",
    ):
        try:
            for r in conn.execute(sql, [desde] + ps).fetchall():
                lect.setdefault(r["vehiculo_id"], []).append((r["fecha"], r["km"]))
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
    return lect


def _km_dia_todos(c):
    """Cuánto anda por día cada coche: lo que se fijó a mano, o lo que dicen
    sus lecturas, o su meta mensual, o lo que anda el resto de la flota."""
    est = {}
    for vid in c.ids:
        r = db.estimar_km_dia(c.lect.get(vid) or [], c.hoy_ord)
        if r and r[0] > 0:
            est[vid] = r
    flota = db._mediana([r[0] for r in est.values()]) or KM_DIA_DEFECTO
    salida = {}
    for vid in c.ids:
        v = c.veh[vid]
        manual = float(v.get("km_dia_manual") or 0)
        meta = float(v.get("meta_km_mensual") or 0)
        if manual > 0:
            salida[vid] = {"valor": manual, "fuente": "manual", "estimado": round(est[vid][0]) if vid in est else None}
        elif vid in est:
            salida[vid] = {"valor": est[vid][0], "fuente": "lecturas", "lecturas": est[vid][1], "dias": est[vid][2],
                           "estimado": round(est[vid][0])}
        elif meta > 0:
            salida[vid] = {"valor": meta / 30.0, "fuente": "meta", "estimado": None}
        else:
            salida[vid] = {"valor": float(flota), "fuente": "flota", "estimado": None}
    return salida


# ════════════════════════════════════════════════════════════════════════════
# ESTADO DE UN COCHE
# ════════════════════════════════════════════════════════════════════════════

def _fecha_mas(ctx, dias):
    return date.fromordinal(ctx.hoy_ord + int(dias)).isoformat()


def _grad(pct):
    if pct is None:
        return "sin_dato"
    if pct >= 100:
        return "vencido"
    if pct >= 85:
        return "atencion"
    if pct >= 70:
        return "regular"
    if pct >= 50:
        return "bueno"
    return "optimo"


def _historia_tarea(regs, t):
    """Los registros de esa tarea en el coche: los suyos y los de una tarea con
    el mismo nombre de otro plan (si se le cambió el plan, no se pierde)."""
    nombre = _nombre_norm(t["tarea"])
    vistos, salida = set(), []
    for r in regs:
        if r["id"] in vistos:
            continue
        if r["tarea_plan_id"] == t["id"] or (r.get("tarea") and _nombre_norm(r["tarea"]) == nombre):
            vistos.add(r["id"])
            salida.append(r)
    salida.sort(key=lambda r: (float(r["km"] or 0), str(r["fecha"] or "")))
    return salida


def _cumplimiento_hist(hist, intervalo, tol, desde=None):
    """Para cada vez que se hizo (después de la primera): a tiempo o tarde."""
    ev = []
    for a, b in zip(hist, hist[1:]):
        ia = int(b.get("intervalo_km") or intervalo or 0)
        if ia <= 0:
            continue
        hecho_a = float(b["km"] or 0) - float(a["km"] or 0)
        if hecho_a <= 0:
            continue
        if desde and str(b["fecha"] or "") < desde:
            continue
        limite = ia * (1 + tol / 100.0)
        ev.append({"fecha": b["fecha"], "km": b["km"], "intervalo": ia, "hecho_a": round(hecho_a),
                   "a_tiempo": hecho_a <= limite, "atraso": max(0, round(hecho_a - ia)),
                   "registro_id": b["id"]})
    return ev


def _estado_coche(vid, ctx, con_historia=False):
    v = ctx.veh.get(vid)
    if not v:
        return None
    p = ctx.plan.get(vid)
    km = float(ctx.km.get(vid) or 0)
    kmd = ctx.km_dia.get(vid, {"valor": KM_DIA_DEFECTO, "fuente": "flota"})
    vel = float(kmd["valor"] or 0)
    cfg = ctx.cfg
    base = {
        "vehiculo_id": vid, "n_interno": v.get("n_interno") or "", "patente": v.get("patente") or "",
        "marca": v.get("marca") or "", "modelo": v.get("modelo") or "",
        "km_actual": round(km), "km_dia": round(vel), "km_dia_fuente": kmd["fuente"],
        "km_dia_estimado": kmd.get("estimado"), "km_dia_manual": float(v.get("km_dia_manual") or 0),
        "plan_id": p["plan_id"] if p else None, "plan_nombre": p["plan_nombre"] if p else None,
    }
    turnos = ctx.turnos.get(vid) or []
    base["turno"] = _turno_corto(turnos[0]) if turnos else None
    if not p:
        base.update({"estado": "sin_plan", "tareas": [], "n_tareas": 0, "vencidas": 0, "proximas": 0,
                     "sin_dato": 0, "al_dia": 0, "proximo": None, "cumplimiento": None})
        return base
    regs = ctx.regs.get(vid) or []
    tol = cfg["tolerancia_pct"]
    hace_un_anio = date.fromordinal(ctx.hoy_ord - 365).isoformat()
    en_ot = ctx.en_ot.get(vid) or {}
    tids_turno = set()
    for tu in turnos:
        tids_turno |= set(_ids(tu.get("tareas")))
    tareas, eventos = [], []
    for t in ctx.tareas.get(p["plan_id"], []):
        ip = int(t["intervalo_km"] or 0)
        io = ctx.over.get((vid, t["id"]))
        intervalo = int(io or ip)
        hist = _historia_tarea(regs, t)
        ult = hist[-1] if hist else None
        fila = {
            "tarea_id": t["id"], "tarea": t["tarea"], "categoria": t["categoria"] or "",
            "intervalo_km": intervalo, "intervalo_plan": ip, "propio": bool(io and io != ip),
            "veces": len(hist), "en_ot": en_ot.get(t["id"]),
            "en_turno": bool(turnos) and (t["id"] in tids_turno or not tids_turno),
        }
        if ult:
            ukm = float(ult["km"] or 0)
            prox = ukm + intervalo
            rest = prox - km
            pct = ((km - ukm) / intervalo * 100) if intervalo else 0
            fila.update({"ultimo_km": round(ukm), "ultima_fecha": ult["fecha"], "ultimo_origen": ult["origen"],
                         "ultimo_ot": ult.get("ot_id"), "ultimo_id": ult["id"],
                         "proximo_km": round(prox), "km_restantes": round(rest),
                         "porcentaje": round(pct, 1), "porcentaje_visual": max(0, min(100, round(pct, 1)))})
            dias = (rest / vel) if vel > 0 else None
            if km <= 0:
                est = "sin_km"
            elif rest < 0:
                est = "vencido"
            elif rest <= cfg["aviso_km"] or (dias is not None and dias <= cfg["aviso_dias"]):
                est = "pronto"
            else:
                est = "ok"
            fila["estado"] = est
            fila["dias_restantes"] = int(dias) if dias is not None else None
            fila["fecha_estimada"] = _fecha_mas(ctx, fila["dias_restantes"]) if dias is not None else None
        else:
            fila.update({"ultimo_km": None, "ultima_fecha": None, "ultimo_origen": None, "ultimo_ot": None,
                         "ultimo_id": None, "proximo_km": None, "km_restantes": None, "porcentaje": None,
                         "porcentaje_visual": 0, "estado": "sin_dato", "dias_restantes": None,
                         "fecha_estimada": None})
        fila["estado_grad"] = _grad(fila["porcentaje"])
        ev = _cumplimiento_hist(hist, intervalo, tol, hace_un_anio)
        fila["a_tiempo"] = sum(1 for e in ev if e["a_tiempo"])
        fila["tarde"] = sum(1 for e in ev if not e["a_tiempo"])
        for e in ev:
            e["tarea"] = t["tarea"]
        eventos += ev
        if con_historia:
            fila["historia"] = [{"id": r["id"], "fecha": r["fecha"], "km": r["km"], "origen": r["origen"],
                                 "ot_id": r.get("ot_id")} for r in reversed(hist)]
        tareas.append(fila)

    orden = {"vencido": 0, "pronto": 1, "ok": 2, "sin_km": 3, "sin_dato": 4}
    tareas.sort(key=lambda x: (orden.get(x["estado"], 5),
                               x["km_restantes"] if x["km_restantes"] is not None else 10 ** 9, x["tarea"]))
    cuenta = {k: 0 for k in orden}
    for t in tareas:
        cuenta[t["estado"]] = cuenta.get(t["estado"], 0) + 1
    if not tareas:
        estado = "sin_dato"
    elif km <= 0:
        estado = "sin_km"
    elif cuenta["vencido"]:
        estado = "vencido"
    elif cuenta["pronto"]:
        estado = "pronto"
    elif cuenta["ok"]:
        estado = "ok"
    else:
        estado = "sin_dato"
    conocidas = [t for t in tareas if t["km_restantes"] is not None]
    proximo = None
    if conocidas and km > 0:
        primero = min(conocidas, key=lambda x: x["km_restantes"])
        ventana = max(1500.0, vel * 7)
        tope = max(primero["km_restantes"], 0) + ventana
        grupo = [t for t in conocidas if t["km_restantes"] <= tope]
        proximo = {
            "tareas": [t["tarea"] for t in grupo], "ids": [t["tarea_id"] for t in grupo],
            "km_restantes": primero["km_restantes"], "proximo_km": primero["proximo_km"],
            "dias": primero["dias_restantes"], "fecha_estimada": primero["fecha_estimada"],
            "porcentaje": primero["porcentaje"], "estado": primero["estado"],
            "intervalo_km": primero["intervalo_km"], "vencidas": sum(1 for t in grupo if t["estado"] == "vencido"),
        }
    n_ev = len(eventos)
    ok_ev = sum(1 for e in eventos if e["a_tiempo"])
    tarde = [e for e in eventos if not e["a_tiempo"]]
    base.update({
        "estado": estado, "tareas": tareas, "n_tareas": len(tareas),
        "vencidas": cuenta["vencido"], "proximas": cuenta["pronto"], "sin_dato": cuenta["sin_dato"],
        "al_dia": cuenta["ok"] + cuenta["pronto"], "proximo": proximo,
        "peor_vencida": -min((t["km_restantes"] for t in tareas if t["estado"] == "vencido"), default=0),
        "cumplimiento": {
            "evaluados": n_ev, "a_tiempo": ok_ev, "tarde": len(tarde),
            "pct": round(ok_ev * 100.0 / n_ev) if n_ev else None,
            "atraso_prom": round(sum(e["atraso"] for e in tarde) / len(tarde)) if tarde else 0,
        },
    })
    base["_eventos"] = eventos
    return base


def _turno_corto(t):
    return {"id": t["id"], "fecha": t["fecha"], "hora": t.get("hora") or "", "estado": t["estado"],
            "ot_id": t.get("ot_id"), "tareas": _ids(t.get("tareas")), "notas": t.get("notas") or ""}


def _limpio(e):
    if e is None:
        return None
    return {k: v for k, v in e.items() if not k.startswith("_")}


def estado_coche(vehiculo_id, con_historia=False):
    conn = get_connection()
    try:
        ctx = _cargar(conn, [vehiculo_id])
        return _estado_coche(vehiculo_id, ctx, con_historia)
    finally:
        conn.close()


def estado_legacy(vehiculo_id):
    """Para lo que ya usaba database.estado_mantenimiento (el PDF, por ejemplo):
    las mismas claves de siempre."""
    e = estado_coche(vehiculo_id)
    if not e or not e.get("plan_id"):
        return None
    salida = []
    for t in e["tareas"]:
        salida.append({**t, "km_actual": e["km_actual"],
                       "estado": t["estado"] if t["estado"] in ("ok", "pronto", "vencido") else "nunca"})
    return salida


def resumen_para_dashboard():
    conn = get_connection()
    try:
        ctx = _cargar(conn)
    finally:
        conn.close()
    salida = {}
    for vid in ctx.ids:
        e = _estado_coche(vid, ctx)
        # Una alerta por coche: lo que le toca (el service entero, no tarea por tarea)
        pr = e.get("proximo")
        alertas = []
        if pr and pr["estado"] in ("vencido", "pronto"):
            n = len(pr["tareas"])
            nombre = (f"Service de {pr['intervalo_km']:,} km ({n} tareas)".replace(",", ".") if n >= 3
                      else " y ".join(pr["tareas"]))
            alertas = [{"tarea": nombre, "estado": pr["estado"], "km_restantes": pr["km_restantes"]}]
        salida[vid] = {"vencidos": e.get("vencidas", 0), "pronto": e.get("proximas", 0),
                       "alertas": alertas, "estado": e["estado"]}
    return salida


# ════════════════════════════════════════════════════════════════════════════
# AGENDA: cupos por día y fecha sugerida
# ════════════════════════════════════════════════════════════════════════════

def _ocupacion(conn, desde, hasta, sin_turno=None):
    occ = {}
    q = "SELECT fecha, COUNT(*) AS n FROM taller_turnos WHERE estado <> 'cancelado' AND fecha >= ? AND fecha <= ?"
    ps = [desde, hasta]
    if sin_turno:
        q += " AND id <> ?"
        ps.append(sin_turno)
    for r in conn.execute(q + " GROUP BY fecha", ps).fetchall():
        occ[r["fecha"]] = int(r["n"])
    return occ


def _fecha_ideal(e, ctx):
    """El día que convendría que entre: un par de días antes de que venza."""
    pr = e.get("proximo")
    if not pr:
        return ctx.hoy
    if pr["km_restantes"] < 0 or pr["dias"] is None:
        return ctx.hoy
    d = max(0, int(pr["dias"]) - 2)
    return _fecha_mas(ctx, d)


def _buscar_dia(ideal, hoy, cfg, occ, especiales, limite_atras=6, limite_adelante=21):
    """El día con lugar más cerca del ideal: primero hacia atrás (mejor antes
    que tarde), después hacia adelante."""
    i = date.fromisoformat(ideal).toordinal()
    h = date.fromisoformat(hoy).toordinal()
    candidatos = [i - k for k in range(0, limite_atras + 1) if i - k >= h]
    candidatos += [i + k for k in range(1, limite_adelante + 1)]
    if i < h:
        candidatos = [h + k for k in range(0, limite_adelante + 1)]
    for o in candidatos:
        f = date.fromordinal(o).isoformat()
        if occ.get(f, 0) < _cupo_dia(f, cfg, especiales):
            return f
    return None


def sugerir_fecha(conn, e, ctx, sin_turno=None):
    ideal = _fecha_ideal(e, ctx)
    hasta = date.fromordinal(date.fromisoformat(ideal).toordinal() + 30).isoformat()
    occ = _ocupacion(conn, ctx.hoy, hasta, sin_turno)
    esp = _cupos_especiales(conn, ctx.hoy, hasta)
    return _buscar_dia(ideal, ctx.hoy, ctx.cfg, occ, esp) or ideal, ideal


# ════════════════════════════════════════════════════════════════════════════
# REGISTROS (lo que se hizo)
# ════════════════════════════════════════════════════════════════════════════

def _intervalo_vigente(conn, vid, tid):
    r = conn.execute("SELECT intervalo_km FROM prev_intervalos WHERE vehiculo_id=? AND tarea_id=?", (vid, tid)).fetchone()
    if r and r["intervalo_km"]:
        return int(r["intervalo_km"])
    r = conn.execute("SELECT intervalo_km FROM tareas_plan WHERE id=?", (tid,)).fetchone()
    return int(r["intervalo_km"] or 0) if r else 0


def registrar(vid, registros, origen="manual", usuario="", observaciones="", costo=0, turno_id=None):
    """registros: [{tarea_id, km, fecha}]. Devuelve cuántos quedaron."""
    conn = get_connection()
    n = 0
    try:
        for r in registros:
            tid = int(r["tarea_id"])
            km = float(r.get("km") or 0)
            fecha = str(r.get("fecha") or _hoy_txt())[:10]
            if km <= 0:
                continue
            conn.execute("""INSERT INTO mantenimientos_realizados
                (vehiculo_id, tarea_plan_id, fecha, km, costo, observaciones, origen, registrado_por,
                 intervalo_km, turno_id)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (vid, tid, fecha, km, float(r.get("costo", costo) or 0),
                 str(r.get("observaciones", observaciones) or ""), origen, usuario,
                 _intervalo_vigente(conn, vid, tid), turno_id))
            n += 1
        conn.commit()
    finally:
        conn.close()
    if n and origen != "inicial":
        _turnos_cumplidos_por_registros(vid, None)
    return n


def borrar_registro(rid):
    conn = get_connection()
    r = conn.execute("SELECT * FROM mantenimientos_realizados WHERE id=?", (rid,)).fetchone()
    if not r:
        conn.close()
        return False, "Ese registro ya no existe."
    if r["ot_item_id"] and (r["origen"] or "") == "ot":
        # Se saca del preventivo y el ítem queda marcado como "no es del plan"
        # para que no vuelva a cargarse solo.
        conn.execute("UPDATE ot_items SET tareas_plan=? WHERE id=?",
                     (_quitar_id(conn, r["ot_item_id"], r["tarea_plan_id"]), r["ot_item_id"]))
    conn.execute("DELETE FROM mantenimientos_realizados WHERE id=?", (rid,))
    conn.commit()
    conn.close()
    return True, dict(r)


def _quitar_id(conn, item_id, tid):
    it = conn.execute("SELECT COALESCE(tareas_plan,'') AS t FROM ot_items WHERE id=?", (item_id,)).fetchone()
    ids = [x for x in _ids(it["t"] if it else "") if x != int(tid)]
    return ",".join(str(x) for x in ids) if ids else "-"


# ════════════════════════════════════════════════════════════════════════════
# CONEXIÓN CON LA OT
# ════════════════════════════════════════════════════════════════════════════

def _tareas_del_coche(conn, vid):
    r = conn.execute("SELECT plan_id FROM vehiculo_plan WHERE vehiculo_id=?", (vid,)).fetchone()
    if not r:
        return []
    return [dict(x) for x in conn.execute(
        "SELECT id, tarea, intervalo_km, categoria FROM tareas_plan WHERE plan_id=? ORDER BY intervalo_km, tarea",
        (r["plan_id"],)).fetchall()]


def sincronizar_item(item_id, usuario=""):
    """Después de tocar un ítem de la OT: si quedó completado y es del plan, se
    carga en el preventivo (con el km de la OT); si dejó de estar completado o
    de ser del plan, se saca. Nunca rompe la OT: los errores se tragan."""
    try:
        return _sincronizar_item(item_id, usuario)
    except Exception:
        return None


def _sincronizar_item(item_id, usuario=""):
    conn = get_connection()
    try:
        it = conn.execute("""SELECT i.id, i.ot_id, i.descripcion, i.tipo, i.estado, i.fecha_completado,
                                    COALESCE(i.tareas_plan,'') AS tareas_plan,
                                    o.vehiculo_id, o.km AS km_ot, o.fecha_apertura
                             FROM ot_items i JOIN ordenes_trabajo o ON o.id = i.ot_id WHERE i.id=?""",
                          (item_id,)).fetchone()
        if not it:
            return None
        vid = it["vehiculo_id"]
        enlace = it["tareas_plan"]
        tareas = _tareas_del_coche(conn, vid)
        validas = {t["id"] for t in tareas}
        completado = (it["estado"] or "") == "completado"
        if completado and enlace == "" and (it["tipo"] or "") != "correctivo":
            sug = sugerir_tareas(it["descripcion"], tareas)
            if sug:
                enlace = ",".join(str(x) for x in sug)
                conn.execute("UPDATE ot_items SET tareas_plan=? WHERE id=?", (enlace, item_id))
        quiere = [x for x in _ids(enlace) if x in validas] if completado else []
        ya = {r["tarea_plan_id"]: r for r in conn.execute(
            "SELECT id, tarea_plan_id, km, fecha FROM mantenimientos_realizados WHERE ot_item_id=?",
            (item_id,)).fetchall()}
        km = float(it["km_ot"] or 0)
        if km <= 0:
            km = float(db.km_actual_flota(conn, [vid]).get(vid) or 0)
        fecha = str(it["fecha_completado"] or _hoy_txt())[:10]
        nuevos = 0
        for tid in quiere:
            if tid in ya:
                r = ya[tid]
                if float(r["km"] or 0) != km or str(r["fecha"]) != fecha:
                    conn.execute("UPDATE mantenimientos_realizados SET km=?, fecha=? WHERE id=?", (km, fecha, r["id"]))
                continue
            if km <= 0:
                continue
            conn.execute("""INSERT INTO mantenimientos_realizados
                (vehiculo_id, tarea_plan_id, fecha, km, costo, observaciones, ot_id, ot_item_id, origen,
                 registrado_por, intervalo_km)
                VALUES (?,?,?,?,0,?,?,?,'ot',?,?)""",
                (vid, tid, fecha, km, f"OT #{it['ot_id']}: {it['descripcion']}"[:200], it["ot_id"], item_id,
                 usuario or "", _intervalo_vigente(conn, vid, tid)))
            nuevos += 1
        for tid, r in ya.items():
            if tid not in quiere:
                conn.execute("DELETE FROM mantenimientos_realizados WHERE id=?", (r["id"],))
        conn.commit()
    finally:
        conn.close()
    if nuevos:
        _turnos_cumplidos_por_registros(vid, it["ot_id"])
    return {"vehiculo_id": vid, "tareas": quiere}


def al_borrar_items(item_ids):
    """Se borran ítems de la OT: lo que habían cargado en el preventivo se va."""
    if not item_ids:
        return
    try:
        conn = get_connection()
        marcas, ps = _en(item_ids)
        conn.execute(f"DELETE FROM mantenimientos_realizados WHERE origen='ot' AND ot_item_id IN ({marcas})", ps)
        conn.commit()
        conn.close()
    except Exception:
        pass


def al_borrar_ot(ot_id):
    try:
        conn = get_connection()
        conn.execute("DELETE FROM mantenimientos_realizados WHERE origen='ot' AND ot_id=?", (ot_id,))
        conn.execute("""UPDATE taller_turnos SET ot_id=NULL, estado='agendado'
                        WHERE ot_id=? AND estado IN ('en_taller','cumplido')""", (ot_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass


def al_cerrar_ot(ot_id):
    try:
        conn = get_connection()
        conn.execute("""UPDATE taller_turnos SET estado='cumplido', cerrado_el=?
                        WHERE ot_id=? AND estado IN ('agendado','en_taller')""", (ahora_iso(), ot_id))
        conn.commit()
        conn.close()
    except Exception:
        pass


def al_reabrir_ot(ot_id):
    try:
        conn = get_connection()
        conn.execute("UPDATE taller_turnos SET estado='en_taller', cerrado_el='' WHERE ot_id=? AND estado='cumplido'",
                     (ot_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass


def al_verificar_km(ot_id, km):
    """Se corrigió el km de la OT: lo que esa OT cargó en el preventivo también."""
    try:
        conn = get_connection()
        conn.execute("UPDATE mantenimientos_realizados SET km=? WHERE origen='ot' AND ot_id=?", (float(km), ot_id))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _turnos_cumplidos_por_registros(vid, ot_id):
    """Si el coche tenía turno y ya se hizo lo del turno (aunque haya entrado
    por otra OT), el turno queda cumplido."""
    try:
        conn = get_connection()
        turnos = conn.execute("""SELECT * FROM taller_turnos WHERE vehiculo_id=? AND estado IN ('agendado','en_taller')""",
                              (vid,)).fetchall()
        for t in turnos:
            desde = str(t["creado_el"] or "")[:10] or "0000-00-00"
            hechas = {r["tarea_plan_id"] for r in conn.execute(
                """SELECT tarea_plan_id FROM mantenimientos_realizados WHERE vehiculo_id=? AND fecha >= ?
                   AND COALESCE(origen,'manual') <> 'inicial'""", (vid, desde)).fetchall()}
            pide = set(_ids(t["tareas"]))
            if (pide and pide <= hechas) or (not pide and hechas):
                conn.execute("""UPDATE taller_turnos SET estado='cumplido', cerrado_el=?,
                                ot_id=COALESCE(ot_id, ?) WHERE id=?""", (ahora_iso(), ot_id, t["id"]))
        conn.commit()
        conn.close()
    except Exception:
        pass


def info_ot(ot_id):
    """Para la ventana de la OT: el plan del coche y, por ítem, qué tareas hace."""
    conn = get_connection()
    try:
        ot = conn.execute("SELECT id, vehiculo_id, estado FROM ordenes_trabajo WHERE id=?", (ot_id,)).fetchone()
        if not ot:
            return None
        vid = ot["vehiculo_id"]
        ctx = _cargar(conn, [vid])
        e = _estado_coche(vid, ctx)
        tareas = _tareas_del_coche(conn, vid)
        items = conn.execute("""SELECT id, descripcion, tipo, estado, COALESCE(tareas_plan,'') AS tareas_plan
                                FROM ot_items WHERE ot_id=? ORDER BY id""", (ot_id,)).fetchall()
        cargadas = {}
        for r in conn.execute("SELECT ot_item_id, tarea_plan_id FROM mantenimientos_realizados WHERE ot_id=? AND origen='ot'",
                              (ot_id,)).fetchall():
            cargadas.setdefault(r["ot_item_id"], []).append(r["tarea_plan_id"])
        turno = conn.execute("SELECT * FROM taller_turnos WHERE ot_id=? ORDER BY id DESC LIMIT 1", (ot_id,)).fetchone()
    finally:
        conn.close()
    por_id = {t["tarea_id"]: t for t in (e or {}).get("tareas", [])}
    salida_items = []
    for it in items:
        enlace = it["tareas_plan"]
        vinc = _ids(enlace)
        sug = [] if vinc or enlace == "-" else sugerir_tareas(it["descripcion"], tareas)
        salida_items.append({"item_id": it["id"], "vinculadas": vinc, "no_es": enlace == "-",
                             "sugeridas": sug, "cargadas": cargadas.get(it["id"], []),
                             "estado": it["estado"], "tipo": it["tipo"]})
    return {
        "plan": {"id": e["plan_id"], "nombre": e["plan_nombre"]} if e and e.get("plan_id") else None,
        "km_actual": e["km_actual"] if e else 0,
        "tareas": [{"id": t["id"], "tarea": t["tarea"], "intervalo_km": por_id.get(t["id"], {}).get("intervalo_km", t["intervalo_km"]),
                    "estado": por_id.get(t["id"], {}).get("estado"),
                    "km_restantes": por_id.get(t["id"], {}).get("km_restantes")} for t in tareas],
        "items": salida_items,
        "turno": _turno_corto(dict(turno)) if turno else None,
    }


def agregar_a_ot(ot_id, tareas):
    """Desde la OT: suma como líneas las tareas del plan que le tocan al coche
    (ya conectadas, así al completarlas se cargan en el preventivo)."""
    conn = get_connection()
    try:
        ot = conn.execute("SELECT id, vehiculo_id FROM ordenes_trabajo WHERE id=?", (ot_id,)).fetchone()
        if not ot:
            return 0
        del_coche = {t["id"]: t for t in _tareas_del_coche(conn, ot["vehiculo_id"])}
        ya = set()
        for r in conn.execute("SELECT COALESCE(tareas_plan,'') AS t FROM ot_items WHERE ot_id=?", (ot_id,)).fetchall():
            ya |= set(_ids(r["t"]))
        n = 0
        for tid in tareas:
            tid = int(tid)
            if tid not in del_coche or tid in ya:
                continue
            conn.execute("""INSERT INTO ot_items (ot_id, descripcion, tipo, estado, costo, tareas_plan, fecha, origen)
                            VALUES (?,?,'preventivo','pendiente',0,?,?,'preventivo')""",
                         (ot_id, del_coche[tid]["tarea"], str(tid), _hoy_txt()))
            n += 1
        conn.commit()
        return n
    finally:
        conn.close()


def vincular_item(item_id, tareas, usuario=""):
    conn = get_connection()
    texto = ",".join(str(int(x)) for x in tareas) if tareas else "-"
    conn.execute("UPDATE ot_items SET tareas_plan=? WHERE id=?", (texto, item_id))
    conn.commit()
    conn.close()
    return _sincronizar_item(item_id, usuario)


# ════════════════════════════════════════════════════════════════════════════
# TURNOS
# ════════════════════════════════════════════════════════════════════════════

def _tecnicos_ids(lista):
    out = []
    for x in lista or []:
        try:
            out.append(int(x))
        except (TypeError, ValueError):
            pass
    return list(dict.fromkeys(out))


def _tecnicos_de(conn, texto, cache=None):
    """'3,20' → [{id, numero, nombre, puesto}] en orden de número."""
    ids = _ids(texto)
    if not ids:
        return []
    if cache is None:
        cache = {}
    falta = [i for i in ids if i not in cache]
    if falta:
        mk, pk = _en(falta)
        try:
            for r in conn.execute(f"SELECT id, numero, nombre, puesto FROM taller_personal WHERE id IN ({mk})", pk).fetchall():
                cache[r["id"]] = {"id": r["id"], "numero": r["numero"], "nombre": r["nombre"], "puesto": r["puesto"] or ""}
        except Exception:
            pass
    return sorted([cache[i] for i in ids if i in cache], key=lambda p: p["numero"])


def _turno_de(conn, tid):
    r = conn.execute("""SELECT t.*, v.n_interno, v.patente, v.marca, v.modelo FROM taller_turnos t
                        JOIN vehiculos v ON v.id = t.vehiculo_id WHERE t.id=?""", (tid,)).fetchone()
    if not r:
        return None
    t = dict(r)
    t["tecnicos_lista"] = _tecnicos_de(conn, t.get("tecnicos"))
    return t


def crear_turno(d, usuario=""):
    vid = int(d["vehiculo_id"])
    fecha = str(d.get("fecha") or "")[:10]
    try:
        date.fromisoformat(fecha)
    except ValueError:
        return {"ok": False, "msg": "Elegí el día."}
    conn = get_connection()
    try:
        cfg = _cfg(conn)
        if fecha < _hoy_txt() and not d.get("forzar"):
            return {"ok": False, "msg": "Ese día ya pasó."}
        if not d.get("forzar"):
            otro = conn.execute("""SELECT id, fecha FROM taller_turnos WHERE vehiculo_id=? AND estado IN ('agendado','en_taller')
                                   ORDER BY fecha LIMIT 1""", (vid,)).fetchone()
            if otro:
                return {"ok": False, "duplicado": True, "turno_id": otro["id"], "fecha": otro["fecha"],
                        "msg": f"El coche ya tiene turno el {_fecha_txt(otro['fecha'])}."}
            esp = _cupos_especiales(conn, fecha, fecha)
            cupo = _cupo_dia(fecha, cfg, esp)
            ocup = _ocupacion(conn, fecha, fecha).get(fecha, 0)
            if ocup >= cupo:
                alt_occ = _ocupacion(conn, _hoy_txt(), date.fromordinal(date.fromisoformat(fecha).toordinal() + 40).isoformat())
                alt_esp = _cupos_especiales(conn, _hoy_txt(), date.fromordinal(date.fromisoformat(fecha).toordinal() + 40).isoformat())
                alt = _buscar_dia(fecha, _hoy_txt(), cfg, alt_occ, alt_esp, limite_atras=3, limite_adelante=21)
                return {"ok": False, "lleno": True, "cupo": cupo, "ocupados": ocup, "alternativa": alt,
                        "msg": (f"El {_fecha_txt(fecha)} el taller no trabaja." if cupo == 0
                                else f"El {_fecha_txt(fecha)} ya tiene {ocup} de {cupo} lugares.")}
        ctx = _cargar(conn, [vid])
        e = _estado_coche(vid, ctx)
        tareas = [int(x) for x in (d.get("tareas") or [])]
        if not tareas and e and e.get("proximo"):
            tareas = list(e["proximo"]["ids"])
        dias = date.fromisoformat(fecha).toordinal() - ctx.hoy_ord
        km_prev = float(ctx.km.get(vid) or 0) + max(0, dias) * float(ctx.km_dia.get(vid, {}).get("valor") or 0)
        cur = conn.execute("""INSERT INTO taller_turnos (vehiculo_id, fecha, hora, tareas, notas, estado,
                              km_previsto, creado_por, creado_el, tecnicos) VALUES (?,?,?,?,?,'agendado',?,?,?,?)""",
                           (vid, fecha, str(d.get("hora") or "")[:5], ",".join(str(x) for x in tareas),
                            str(d.get("notas") or "")[:300], round(km_prev), usuario, ahora_iso(),
                            ",".join(str(x) for x in _tecnicos_ids(d.get("tecnicos")))))
        conn.commit()
        tid = cur.lastrowid
        return {"ok": True, "turno": _turno_de(conn, tid)}
    finally:
        conn.close()


def _fecha_txt(f):
    try:
        d = date.fromisoformat(str(f)[:10])
    except ValueError:
        return str(f)
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    return f"{dias[d.weekday()]} {d.day:02d}/{d.month:02d}"


def actualizar_turno(tid, d, usuario=""):
    conn = get_connection()
    try:
        t = _turno_de(conn, tid)
        if not t:
            return {"ok": False, "msg": "Ese turno ya no existe."}
        cambios = {}
        if "fecha" in d and str(d["fecha"])[:10] != t["fecha"]:
            fecha = str(d["fecha"])[:10]
            try:
                date.fromisoformat(fecha)
            except ValueError:
                return {"ok": False, "msg": "Fecha inválida."}
            if not d.get("forzar"):
                cfg = _cfg(conn)
                cupo = _cupo_dia(fecha, cfg, _cupos_especiales(conn, fecha, fecha))
                ocup = _ocupacion(conn, fecha, fecha, sin_turno=tid).get(fecha, 0)
                if ocup >= cupo:
                    return {"ok": False, "lleno": True, "cupo": cupo, "ocupados": ocup,
                            "msg": (f"El {_fecha_txt(fecha)} el taller no trabaja." if cupo == 0
                                    else f"El {_fecha_txt(fecha)} ya tiene {ocup} de {cupo} lugares.")}
            cambios["fecha"] = fecha
        for k in ("hora", "notas", "motivo"):
            if k in d:
                cambios[k] = str(d[k] or "")[:300]
        if "tareas" in d:
            cambios["tareas"] = ",".join(str(int(x)) for x in (d["tareas"] or []))
        if "tecnicos" in d:
            cambios["tecnicos"] = ",".join(str(x) for x in _tecnicos_ids(d["tecnicos"]))
        if "estado" in d:
            if d["estado"] not in ESTADOS_TURNO:
                return {"ok": False, "msg": "Estado inválido."}
            cambios["estado"] = d["estado"]
            cambios["cerrado_el"] = ahora_iso() if d["estado"] in ("cumplido", "cancelado", "ausente") else ""
        if cambios:
            sets = ", ".join(f"{k}=?" for k in cambios)
            conn.execute(f"UPDATE taller_turnos SET {sets} WHERE id=?", list(cambios.values()) + [tid])
            conn.commit()
        return {"ok": True, "turno": _turno_de(conn, tid)}
    finally:
        conn.close()


def borrar_turno(tid):
    conn = get_connection()
    conn.execute("UPDATE mantenimientos_realizados SET turno_id=NULL WHERE turno_id=?", (tid,))
    conn.execute("DELETE FROM taller_turnos WHERE id=?", (tid,))
    conn.commit()
    conn.close()


def abrir_ot_de_turno(tid, usuario=""):
    """El coche llegó: se abre la OT con una línea por tarea del turno, ya
    conectadas al plan (al completarlas se cargan solas en el preventivo)."""
    conn = get_connection()
    try:
        t = _turno_de(conn, tid)
        if not t:
            return {"ok": False, "msg": "Ese turno ya no existe."}
        if t.get("ot_id"):
            existe = conn.execute("SELECT id FROM ordenes_trabajo WHERE id=?", (t["ot_id"],)).fetchone()
            if existe:
                return {"ok": True, "ot_id": t["ot_id"], "ya_estaba": True}
        vid = t["vehiculo_id"]
        tareas = {x["id"]: x for x in _tareas_del_coche(conn, vid)}
        ids = [x for x in _ids(t["tareas"]) if x in tareas]
        if not ids:
            ctx = _cargar(conn, [vid])
            e = _estado_coche(vid, ctx)
            ids = list((e.get("proximo") or {}).get("ids") or [])
        km = float(db.km_actual_flota(conn, [vid]).get(vid) or 0)
    finally:
        conn.close()
    items = [{"descripcion": tareas[x]["tarea"], "tipo": "preventivo", "estado": "pendiente", "costo": 0} for x in ids]
    obs = "Turno del preventivo" + (f" · {t['notas']}" if t.get("notas") else "")
    # Si el coche ya tiene su OT abierta, las tareas del turno se suman ahí
    import ot_unica
    conn = get_connection()
    try:
        abierta = ot_unica.ot_abierta_de(conn, vid)
    finally:
        conn.close()
    if abierta:
        ot_id = abierta
        nuevos = ot_unica.agregar_items(ot_id, items, origen="preventivo", fecha=_hoy_txt())
    else:
        ot_id = db.crear_ot(vid, _hoy_txt(), km=km, conductor="", procedencia="Preventivo (turno)",
                            observaciones=obs, items=items)
        nuevos = None
    conn = get_connection()
    if nuevos is None:
        nuevos = [r["id"] for r in conn.execute("SELECT id FROM ot_items WHERE ot_id=? ORDER BY id", (ot_id,)).fetchall()]
    for iid, tid_tarea in zip(nuevos, ids):
        conn.execute("UPDATE ot_items SET tareas_plan=? WHERE id=?", (str(tid_tarea), iid))
    # Queda en el día que vino de verdad (si se adelantó, libera el lugar del otro día)
    conn.execute("UPDATE taller_turnos SET estado='en_taller', ot_id=?, fecha=? WHERE id=?", (ot_id, _hoy_txt(), tid))
    conn.commit()
    conn.close()
    # Los técnicos que se asignaron al agendar quedan puestos en cada trabajo
    tecs = _ids(t.get("tecnicos"))
    if tecs and nuevos:
        try:
            import personal_taller
            for iid in nuevos:
                personal_taller.asignar(iid, tecs, quien=usuario)
        except Exception:
            pass
    return {"ok": True, "ot_id": ot_id, "sumada": bool(abierta), "tecnicos": len(tecs)}


def turnos_por_tecnico(dias=14):
    """{personal_id: [turno, ...]} de los turnos agendados desde hoy hasta
    `dias` días adelante (para avisarle a cada técnico con anticipación)."""
    hoy = _hoy_txt()
    hasta = date.fromordinal(date.fromisoformat(hoy).toordinal() + dias).isoformat()
    conn = get_connection()
    try:
        filas = conn.execute("""SELECT t.id, t.fecha, t.hora, t.tareas, t.notas, t.tecnicos, v.n_interno, v.patente
                                FROM taller_turnos t JOIN vehiculos v ON v.id = t.vehiculo_id
                                WHERE t.estado='agendado' AND t.fecha >= ? AND t.fecha <= ?
                                  AND COALESCE(t.tecnicos,'') <> '' ORDER BY t.fecha, t.hora""", (hoy, hasta)).fetchall()
        nombres = {}
        ids = sorted({x for r in filas for x in _ids(r["tareas"])})
        if ids:
            mk, pk = _en(ids)
            for r in conn.execute(f"SELECT id, tarea FROM tareas_plan WHERE id IN ({mk})", pk).fetchall():
                nombres[r["id"]] = r["tarea"]
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        filas = []
    finally:
        conn.close()
    out = {}
    for r in filas:
        t = {"id": r["id"], "fecha": r["fecha"], "hora": r["hora"] or "", "coche": r["n_interno"] or r["patente"] or "",
             "tareas": [nombres[x] for x in _ids(r["tareas"]) if x in nombres], "notas": r["notas"] or ""}
        for pid in _ids(r["tecnicos"]):
            out.setdefault(pid, []).append(t)
    return out


def cumplir_turno(tid, d, usuario=""):
    """Marcar cumplido sin OT: se registran las tareas con el km que se diga."""
    conn = get_connection()
    t = _turno_de(conn, tid)
    conn.close()
    if not t:
        return {"ok": False, "msg": "Ese turno ya no existe."}
    vid = t["vehiculo_id"]
    km = float(d.get("km") or 0)
    if km <= 0:
        return {"ok": False, "msg": "Poné el km del tablero."}
    fecha = str(d.get("fecha") or _hoy_txt())[:10]
    ids = [int(x) for x in (d.get("tareas") or _ids(t["tareas"]))]
    n = registrar(vid, [{"tarea_id": x, "km": km, "fecha": fecha} for x in ids], origen="manual",
                  usuario=usuario, observaciones=f"Turno del {t['fecha']}", turno_id=tid)
    conn = get_connection()
    conn.execute("UPDATE taller_turnos SET estado='cumplido', cerrado_el=? WHERE id=?", (ahora_iso(), tid))
    conn.commit()
    conn.close()
    return {"ok": True, "registradas": n}


def agenda(desde, hasta):
    conn = get_connection()
    try:
        cfg = _cfg(conn)
        esp = _cupos_especiales(conn, desde, hasta)
        filas = conn.execute("""SELECT t.*, v.n_interno, v.patente, v.marca, v.modelo FROM taller_turnos t
                                JOIN vehiculos v ON v.id = t.vehiculo_id
                                WHERE t.fecha >= ? AND t.fecha <= ? ORDER BY t.fecha, t.hora, t.id""",
                             (desde, hasta)).fetchall()
        turnos = [dict(r) for r in filas]
        nombres = {}
        todas_ids = sorted({x for t in turnos for x in _ids(t.get("tareas"))})
        if todas_ids:
            mk, pk = _en(todas_ids)
            for r in conn.execute(f"SELECT id, tarea FROM tareas_plan WHERE id IN ({mk})", pk).fetchall():
                nombres[r["id"]] = r["tarea"]
        hoy = _hoy_txt()
        cache_tec = {}
        for t in turnos:
            t["tecnicos_lista"] = _tecnicos_de(conn, t.get("tecnicos"), cache_tec)
        dias = {}
        d0 = date.fromisoformat(desde).toordinal()
        d1 = date.fromisoformat(hasta).toordinal()
        for o in range(d0, d1 + 1):
            f = date.fromordinal(o).isoformat()
            dias[f] = {"fecha": f, "cupo": _cupo_dia(f, cfg, esp), "especial": f in esp, "turnos": [], "ocupados": 0}
        for t in turnos:
            t["tareas_ids"] = _ids(t.get("tareas"))
            t["tareas_nombres"] = [nombres.get(x, "") for x in t["tareas_ids"] if nombres.get(x)]
            t["atrasado"] = t["estado"] == "agendado" and t["fecha"] < hoy
            dia = dias.get(t["fecha"])
            if dia is not None:
                dia["turnos"].append(t)
                if t["estado"] != "cancelado":
                    dia["ocupados"] += 1
        return {"dias": list(dias.values()), "config": cfg, "hoy": hoy}
    finally:
        conn.close()


def para_agendar(dias_adelante=None):
    """Coches que necesitan turno: vencidos o que vencen pronto y no tienen
    turno. Con la fecha sugerida (respetando los cupos)."""
    conn = get_connection()
    try:
        ctx = _cargar(conn)
        cfg = ctx.cfg
        lim = cfg["aviso_dias"] if dias_adelante is None else int(dias_adelante)
        hasta = date.fromordinal(ctx.hoy_ord + lim + 40).isoformat()
        occ = _ocupacion(conn, ctx.hoy, hasta)
        esp = _cupos_especiales(conn, ctx.hoy, hasta)
        lista = []
        for vid in ctx.ids:
            e = _estado_coche(vid, ctx)
            if not e or e.get("turno") or not e.get("proximo"):
                continue
            pr = e["proximo"]
            if not (pr["km_restantes"] < 0 or (pr["dias"] is not None and pr["dias"] <= lim)):
                continue
            lista.append(e)
        lista.sort(key=lambda e: (e["proximo"]["km_restantes"] >= 0, e["proximo"]["dias"] if e["proximo"]["dias"] is not None else 999,
                                  e["proximo"]["km_restantes"]))
        salida = []
        for e in lista:
            ideal = _fecha_ideal(e, ctx)
            f = _buscar_dia(ideal, ctx.hoy, cfg, occ, esp)
            if f:
                occ[f] = occ.get(f, 0) + 1     # para que el siguiente no caiga en el mismo lugar
            salida.append({**{k: e[k] for k in ("vehiculo_id", "n_interno", "patente", "marca", "modelo",
                                                 "plan_nombre", "km_actual", "km_dia", "estado", "vencidas")},
                           "proximo": e["proximo"], "fecha_sugerida": f, "fecha_ideal": ideal})
        return salida
    finally:
        conn.close()


def agendar_lote(propuestas, usuario=""):
    hechos, saltados = [], []
    for p in propuestas:
        r = crear_turno({"vehiculo_id": p["vehiculo_id"], "fecha": p["fecha"], "tareas": p.get("tareas") or []}, usuario)
        (hechos if r.get("ok") else saltados).append({**p, "msg": r.get("msg", "")})
    return {"ok": True, "agendados": len(hechos), "saltados": saltados}


# ════════════════════════════════════════════════════════════════════════════
# FLOTA Y CUMPLIMIENTO
# ════════════════════════════════════════════════════════════════════════════

def flota():
    conn = get_connection()
    try:
        ctx = _cargar(conn)
    finally:
        conn.close()
    coches = []
    for vid in ctx.ids:
        e = _estado_coche(vid, ctx)
        e.pop("_eventos", None)
        pr = e.get("proximo")
        coches.append({**{k: e.get(k) for k in (
            "vehiculo_id", "n_interno", "patente", "marca", "modelo", "plan_id", "plan_nombre", "km_actual",
            "km_dia", "km_dia_fuente", "estado", "n_tareas", "vencidas", "proximas", "sin_dato", "al_dia",
            "turno", "cumplimiento", "peor_vencida")}, "proximo": pr})
    orden = {"vencido": 0, "pronto": 1, "ok": 2, "sin_km": 3, "sin_dato": 4, "sin_plan": 5}

    def clave(c):
        pr = c.get("proximo") or {}
        return (orden.get(c["estado"], 9), pr.get("km_restantes") if pr.get("km_restantes") is not None else 10 ** 9,
                _num_interno(c["n_interno"]))
    coches.sort(key=clave)
    k = {"coches": len(coches), "con_plan": sum(1 for c in coches if c["plan_id"]),
         "vencidos": sum(1 for c in coches if c["estado"] == "vencido"),
         "pronto": sum(1 for c in coches if c["estado"] == "pronto"),
         "al_dia": sum(1 for c in coches if c["estado"] == "ok"),
         "sin_dato": sum(1 for c in coches if c["estado"] in ("sin_dato", "sin_km")),
         "sin_plan": sum(1 for c in coches if c["estado"] == "sin_plan"),
         "con_turno": sum(1 for c in coches if c.get("turno")),
         "tareas_sin_dato": sum(c.get("sin_dato") or 0 for c in coches if c["plan_id"])}
    ev = sum((c["cumplimiento"] or {}).get("evaluados", 0) for c in coches)
    ok = sum((c["cumplimiento"] or {}).get("a_tiempo", 0) for c in coches)
    k["pct_a_tiempo"] = round(ok * 100.0 / ev) if ev else None
    k["evaluados"] = ev
    return {"coches": coches, "kpis": k, "config": ctx.cfg, "hoy": ctx.hoy}


def _num_interno(n):
    m = re.match(r"\d+", str(n or ""))
    return (int(m.group()) if m else 10 ** 6, str(n or ""))


def cumplimiento(meses=6):
    conn = get_connection()
    try:
        ctx = _cargar(conn)
        hace = date.fromordinal(ctx.hoy_ord - 365).isoformat()
        # Los últimos 90 días (y los que ya se resolvieron aunque fueran para más adelante)
        turnos = conn.execute("""SELECT estado, fecha FROM taller_turnos WHERE fecha >= ?
                                 AND (fecha <= ? OR estado IN ('cumplido','ausente'))""",
                              (date.fromordinal(ctx.hoy_ord - 90).isoformat(), ctx.hoy)).fetchall()
    finally:
        conn.close()
    coches, eventos = [], []
    planes = {}
    for vid in ctx.ids:
        e = _estado_coche(vid, ctx)
        if not e.get("plan_id"):
            continue
        ev = e.pop("_eventos", [])
        for x in ev:
            x["vehiculo_id"] = vid
        eventos += ev
        cu = e["cumplimiento"]
        coches.append({**{k: e.get(k) for k in ("vehiculo_id", "n_interno", "patente", "marca", "modelo", "plan_nombre",
                                                "estado", "n_tareas", "vencidas", "proximas", "sin_dato", "al_dia",
                                                "peor_vencida", "km_actual")}, "cumplimiento": cu})
        p = planes.setdefault(e["plan_id"], {"plan_id": e["plan_id"], "plan_nombre": e["plan_nombre"], "coches": 0,
                                             "al_dia": 0, "vencidos": 0, "sin_dato": 0, "evaluados": 0, "a_tiempo": 0})
        p["coches"] += 1
        p["al_dia"] += 1 if e["estado"] in ("ok", "pronto") else 0
        p["vencidos"] += 1 if e["estado"] == "vencido" else 0
        p["sin_dato"] += 1 if e["estado"] in ("sin_dato", "sin_km") else 0
        p["evaluados"] += cu["evaluados"]
        p["a_tiempo"] += cu["a_tiempo"]
    # Por mes: lo que se hizo a tiempo y lo que se hizo tarde
    hoy_d = date.fromisoformat(ctx.hoy)
    mes_list = []
    y, m = hoy_d.year, hoy_d.month
    for _ in range(meses):
        mes_list.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    mes_list.reverse()
    por_mes = {k: {"mes": k, "a_tiempo": 0, "tarde": 0} for k in mes_list}
    for x in eventos:
        k = str(x["fecha"] or "")[:7]
        if k in por_mes:
            por_mes[k]["a_tiempo" if x["a_tiempo"] else "tarde"] += 1
    tarde = [x for x in eventos if not x["a_tiempo"]]
    tc = {"cumplido": 0, "ausente": 0, "cancelado": 0, "pendiente": 0}
    for t in turnos:
        if t["estado"] == "cumplido":
            tc["cumplido"] += 1
        elif t["estado"] == "ausente":
            tc["ausente"] += 1
        elif t["estado"] == "cancelado":
            tc["cancelado"] += 1
        elif t["fecha"] < ctx.hoy:
            tc["pendiente"] += 1
    base_t = tc["cumplido"] + tc["ausente"] + tc["pendiente"]
    con_dato = [c for c in coches if c["estado"] not in ("sin_dato", "sin_km")]
    kpis = {
        "coches": len(coches),
        "evaluados": len(eventos),
        "a_tiempo": len(eventos) - len(tarde),
        "pct_a_tiempo": round((len(eventos) - len(tarde)) * 100.0 / len(eventos)) if eventos else None,
        "atraso_prom": round(sum(x["atraso"] for x in tarde) / len(tarde)) if tarde else 0,
        "coches_al_dia": sum(1 for c in con_dato if c["estado"] in ("ok", "pronto")),
        "coches_con_dato": len(con_dato),
        "pct_coches_al_dia": round(sum(1 for c in con_dato if c["estado"] in ("ok", "pronto")) * 100.0 / len(con_dato)) if con_dato else None,
        "tareas_vencidas": sum(c["vencidas"] or 0 for c in coches),
        "turnos": tc,
        "pct_turnos": round(tc["cumplido"] * 100.0 / base_t) if base_t else None,
    }
    for p in planes.values():
        p["pct_a_tiempo"] = round(p["a_tiempo"] * 100.0 / p["evaluados"]) if p["evaluados"] else None
    orden = {"vencido": 0, "pronto": 1, "ok": 2, "sin_km": 3, "sin_dato": 4}
    coches.sort(key=lambda c: (orden.get(c["estado"], 9), -(c["vencidas"] or 0), -(c["peor_vencida"] or 0),
                               (c["cumplimiento"] or {}).get("pct") if (c["cumplimiento"] or {}).get("pct") is not None else 101))
    ultimos_tarde = sorted(tarde, key=lambda x: str(x["fecha"]), reverse=True)[:12]
    nombres = {vid: ctx.veh[vid] for vid in ctx.ids}
    for x in ultimos_tarde:
        v = nombres.get(x["vehiculo_id"], {})
        x["n_interno"] = v.get("n_interno") or ""
        x["patente"] = v.get("patente") or ""
    return {"kpis": kpis, "por_mes": [por_mes[k] for k in mes_list], "coches": coches,
            "planes": sorted(planes.values(), key=lambda p: p["plan_nombre"] or ""),
            "ultimos_tarde": ultimos_tarde, "config": ctx.cfg, "hoy": ctx.hoy}


# ════════════════════════════════════════════════════════════════════════════
# PLANES (biblioteca) Y CADA CUÁNTO POR COCHE
# ════════════════════════════════════════════════════════════════════════════

def planes_detalle():
    conn = get_connection()
    try:
        planes = [dict(r) for r in conn.execute("SELECT * FROM planes_mantenimiento ORDER BY nombre").fetchall()]
        tareas = {}
        for r in conn.execute("SELECT * FROM tareas_plan ORDER BY intervalo_km, tarea").fetchall():
            tareas.setdefault(r["plan_id"], []).append(dict(r))
        usos = {}
        for r in conn.execute("""SELECT tarea_plan_id, COUNT(*) AS n FROM mantenimientos_realizados
                                 GROUP BY tarea_plan_id""").fetchall():
            usos[r["tarea_plan_id"]] = int(r["n"])
        propios = {}
        for r in conn.execute("SELECT tarea_id, COUNT(*) AS n FROM prev_intervalos GROUP BY tarea_id").fetchall():
            propios[r["tarea_id"]] = int(r["n"])
        coches = {}
        for r in conn.execute("""SELECT vp.plan_id, v.id, v.n_interno, v.patente, v.marca, v.modelo, v.activo
                                 FROM vehiculo_plan vp JOIN vehiculos v ON v.id = vp.vehiculo_id""").fetchall():
            coches.setdefault(r["plan_id"], []).append(dict(r))
    finally:
        conn.close()
    for p in planes:
        p["tareas"] = tareas.get(p["id"], [])
        for t in p["tareas"]:
            t["registros"] = usos.get(t["id"], 0)
            t["coches_propios"] = propios.get(t["id"], 0)
        p["coches"] = sorted(coches.get(p["id"], []), key=lambda c: _num_interno(c["n_interno"]))
    return planes


def crear_plan(nombre, descripcion="", copiar_de=None):
    nombre = (nombre or "").strip()
    if not nombre:
        return False, "Poné un nombre."
    conn = get_connection()
    try:
        if conn.execute("SELECT id FROM planes_mantenimiento WHERE LOWER(nombre)=LOWER(?)", (nombre,)).fetchone():
            return False, f"Ya hay un plan que se llama \"{nombre}\"."
        cur = conn.execute("INSERT INTO planes_mantenimiento (nombre, descripcion) VALUES (?,?)",
                           (nombre, (descripcion or "").strip()))
        pid = cur.lastrowid
        if copiar_de:
            for t in conn.execute("SELECT tarea, intervalo_km, categoria FROM tareas_plan WHERE plan_id=?",
                                  (int(copiar_de),)).fetchall():
                conn.execute("INSERT INTO tareas_plan (plan_id, tarea, intervalo_km, categoria) VALUES (?,?,?,?)",
                             (pid, t["tarea"], t["intervalo_km"], t["categoria"]))
        conn.commit()
        return True, pid
    finally:
        conn.close()


def _no_volver_a_sembrar(conn, nombre):
    """Los planes que vienen de fábrica se cargan solos al arrancar si no
    existe uno con ese nombre. Si se renombró o se borró, se anota para que
    no vuelva a aparecer."""
    conn.execute("""INSERT INTO prev_config (clave, valor) VALUES (?, '1')
                    ON CONFLICT (clave) DO UPDATE SET valor='1'""", ("seed_omitir:" + nombre,))


def plan_omitido(nombre):
    try:
        conn = get_connection()
        r = conn.execute("SELECT valor FROM prev_config WHERE clave=?", ("seed_omitir:" + nombre,)).fetchone()
        conn.close()
        return bool(r)
    except Exception:
        return False


def editar_plan(pid, d):
    conn = get_connection()
    try:
        if "nombre" in d:
            n = (d["nombre"] or "").strip()
            if not n:
                return False, "El nombre no puede quedar vacío."
            if conn.execute("SELECT id FROM planes_mantenimiento WHERE LOWER(nombre)=LOWER(?) AND id<>?", (n, pid)).fetchone():
                return False, f"Ya hay un plan que se llama \"{n}\"."
            viejo = conn.execute("SELECT nombre FROM planes_mantenimiento WHERE id=?", (pid,)).fetchone()
            conn.execute("UPDATE planes_mantenimiento SET nombre=? WHERE id=?", (n, pid))
            if viejo and viejo["nombre"] != n:
                _no_volver_a_sembrar(conn, viejo["nombre"])
        if "descripcion" in d:
            conn.execute("UPDATE planes_mantenimiento SET descripcion=? WHERE id=?", ((d["descripcion"] or "").strip(), pid))
        conn.commit()
        return True, "ok"
    finally:
        conn.close()


def agregar_tarea(pid, d):
    tarea = (d.get("tarea") or "").strip()
    try:
        km = int(float(str(d.get("intervalo_km") or 0).replace(".", "").replace(",", ".")))
    except ValueError:
        km = 0
    if not tarea or km <= 0:
        return False, "Poné la tarea y cada cuántos km."
    conn = get_connection()
    cur = conn.execute("INSERT INTO tareas_plan (plan_id, tarea, intervalo_km, categoria) VALUES (?,?,?,?)",
                       (pid, tarea, km, (d.get("categoria") or "").strip()))
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    return True, tid


def editar_tarea(tid, d):
    conn = get_connection()
    try:
        t = conn.execute("SELECT * FROM tareas_plan WHERE id=?", (tid,)).fetchone()
        if not t:
            return False, "Esa tarea ya no existe."
        if "tarea" in d:
            n = (d["tarea"] or "").strip()
            if not n:
                return False, "El nombre no puede quedar vacío."
            conn.execute("UPDATE tareas_plan SET tarea=? WHERE id=?", (n, tid))
        if "intervalo_km" in d:
            try:
                km = int(float(str(d["intervalo_km"]).replace(".", "").replace(",", ".")))
            except ValueError:
                km = 0
            if km <= 0:
                return False, "Cada cuántos km tiene que ser un número."
            conn.execute("UPDATE tareas_plan SET intervalo_km=? WHERE id=?", (km, tid))
        if "categoria" in d:
            conn.execute("UPDATE tareas_plan SET categoria=? WHERE id=?", ((d["categoria"] or "").strip(), tid))
        conn.commit()
        return True, dict(t)
    finally:
        conn.close()


def borrar_tarea(tid):
    conn = get_connection()
    try:
        n = conn.execute("SELECT COUNT(*) AS c FROM mantenimientos_realizados WHERE tarea_plan_id=?", (tid,)).fetchone()["c"]
        if n:
            return False, f"Tiene {n} registro{'s' if n != 1 else ''} hecho{'s' if n != 1 else ''}: no se puede borrar sin perder la historia."
        conn.execute("DELETE FROM prev_intervalos WHERE tarea_id=?", (tid,))
        conn.execute("DELETE FROM tareas_plan WHERE id=?", (tid,))
        conn.commit()
        return True, "ok"
    finally:
        conn.close()


def borrar_plan(pid):
    conn = get_connection()
    try:
        n = conn.execute("SELECT COUNT(*) AS c FROM vehiculo_plan WHERE plan_id=?", (pid,)).fetchone()["c"]
        if n:
            return False, f"Lo usan {n} coche{'s' if n != 1 else ''}: pasalos a otro plan primero."
        m = conn.execute("""SELECT COUNT(*) AS c FROM mantenimientos_realizados WHERE tarea_plan_id IN
                            (SELECT id FROM tareas_plan WHERE plan_id=?)""", (pid,)).fetchone()["c"]
        if m:
            return False, f"Tiene {m} registros hechos: no se puede borrar sin perder la historia."
        conn.execute("DELETE FROM prev_intervalos WHERE tarea_id IN (SELECT id FROM tareas_plan WHERE plan_id=?)", (pid,))
        conn.execute("DELETE FROM tareas_plan WHERE plan_id=?", (pid,))
        viejo = conn.execute("SELECT nombre FROM planes_mantenimiento WHERE id=?", (pid,)).fetchone()
        conn.execute("DELETE FROM planes_mantenimiento WHERE id=?", (pid,))
        if viejo:
            _no_volver_a_sembrar(conn, viejo["nombre"])
        conn.commit()
        return True, "ok"
    finally:
        conn.close()


def asignar(vids, pid):
    conn = get_connection()
    for vid in vids:
        if conn.execute("SELECT vehiculo_id FROM vehiculo_plan WHERE vehiculo_id=?", (vid,)).fetchone():
            conn.execute("UPDATE vehiculo_plan SET plan_id=? WHERE vehiculo_id=?", (pid, vid))
        else:
            conn.execute("INSERT INTO vehiculo_plan (vehiculo_id, plan_id, km_inicial) VALUES (?,?,0)", (vid, pid))
    conn.commit()
    conn.close()
    try:
        db._olvidar_referencias()
    except Exception:
        pass


def guardar_intervalo(vid, tid, km, usuario=""):
    conn = get_connection()
    conn.execute("DELETE FROM prev_intervalos WHERE vehiculo_id=? AND tarea_id=?", (vid, tid))
    if km and int(km) > 0:
        plan = conn.execute("SELECT intervalo_km FROM tareas_plan WHERE id=?", (tid,)).fetchone()
        if not plan or int(plan["intervalo_km"] or 0) != int(km):
            conn.execute("""INSERT INTO prev_intervalos (vehiculo_id, tarea_id, intervalo_km, actualizado_por, actualizado_el)
                            VALUES (?,?,?,?,?)""", (vid, tid, int(km), usuario, ahora_iso()))
    conn.commit()
    conn.close()


def guardar_km_dia(vid, km_dia):
    conn = get_connection()
    conn.execute("UPDATE vehiculos SET km_dia_manual=? WHERE id=?", (max(0.0, float(km_dia or 0)), vid))
    conn.commit()
    conn.close()


def ficha_coche(vid):
    conn = get_connection()
    try:
        ctx = _cargar(conn, [vid])
        if vid not in ctx.veh:
            return None
        e = _estado_coche(vid, ctx, con_historia=True)
        ev = e.pop("_eventos", [])
        if e.get("plan_id"):
            sug, ideal = sugerir_fecha(conn, e, ctx)
        else:
            sug, ideal = None, None
        turnos = [dict(r) for r in conn.execute(
            "SELECT * FROM taller_turnos WHERE vehiculo_id=? ORDER BY fecha DESC, id DESC LIMIT 12", (vid,)).fetchall()]
        planes = [dict(r) for r in conn.execute("""SELECT p.id, p.nombre,
                     (SELECT COUNT(*) FROM tareas_plan t WHERE t.plan_id=p.id) AS tareas
                     FROM planes_mantenimiento p ORDER BY p.nombre""").fetchall()]
        verif = None
        try:
            verif = db.km_verificacion(vid)
        except Exception:
            pass
    finally:
        conn.close()
    hist = sorted(ctx.regs.get(vid) or [], key=lambda r: (str(r["fecha"] or ""), float(r["km"] or 0)), reverse=True)
    ev_por_reg = {x["registro_id"]: x for x in ev}
    for r in hist:
        x = ev_por_reg.get(r["id"])
        r["a_tiempo"] = x["a_tiempo"] if x else None
        r["hecho_a"] = x["hecho_a"] if x else None
    for t in turnos:
        t["tareas_ids"] = _ids(t.get("tareas"))
        t["atrasado"] = t["estado"] == "agendado" and t["fecha"] < ctx.hoy
    e.update({"historial": hist[:200], "turnos": turnos, "planes": planes, "fecha_sugerida": sug,
              "fecha_ideal": ideal, "km_verif": verif, "config": ctx.cfg, "hoy": ctx.hoy})
    return e


# ════════════════════════════════════════════════════════════════════════════
# API
# ════════════════════════════════════════════════════════════════════════════

def _puede_ver():
    return session.get("rol") in ("admin", "taller", "auditor", "compras")


def _puede_editar():
    return session.get("rol") in ("admin", "taller")


def _quien():
    return session.get("nombre") or session.get("usuario") or ""


def _auditar(accion, detalle=""):
    try:
        from database import registrar_auditoria
        registrar_auditoria(usuario=_quien() or "?", rol=session.get("rol") or "", accion=accion,
                            categoria="Preventivo", detalle=str(detalle)[:200], referencia="")
    except Exception:
        pass


def _no():
    return jsonify({"ok": False, "msg": "No tenés permiso para esto"}), 403


def _coche_txt(vid):
    try:
        conn = get_connection()
        r = conn.execute("SELECT n_interno, patente FROM vehiculos WHERE id=?", (vid,)).fetchone()
        conn.close()
        if r:
            return f"coche {r['n_interno'] or ''} {r['patente'] or ''}".strip()
    except Exception:
        pass
    return f"coche {vid}"


@bp_prev.route("/api/prev/flota", methods=["GET"])
def api_flota():
    if not _puede_ver():
        return _no()
    return jsonify(flota())


@bp_prev.route("/api/prev/coche/<int:vid>", methods=["GET"])
def api_coche(vid):
    if not _puede_ver():
        return _no()
    f = ficha_coche(vid)
    if not f:
        return jsonify({"ok": False, "msg": "Ese coche no existe"}), 404
    return jsonify(f)


@bp_prev.route("/api/prev/coche/<int:vid>/plan", methods=["POST"])
def api_coche_plan(vid):
    if not _puede_editar():
        return _no()
    d = request.json or {}
    pid = d.get("plan_id")
    if pid:
        asignar([vid], int(pid))
        _auditar(f"Asignó un plan al {_coche_txt(vid)}", f"plan {pid}")
    else:
        conn = get_connection()
        conn.execute("DELETE FROM vehiculo_plan WHERE vehiculo_id=?", (vid,))
        conn.commit()
        conn.close()
        _auditar(f"Le sacó el plan al {_coche_txt(vid)}")
    return jsonify({"ok": True})


@bp_prev.route("/api/prev/coche/<int:vid>/km_dia", methods=["POST"])
def api_km_dia(vid):
    if not _puede_editar():
        return _no()
    d = request.json or {}
    try:
        v = float(str(d.get("km_dia") or 0).replace(".", "").replace(",", "."))
    except ValueError:
        return jsonify({"ok": False, "msg": "Poné un número"}), 400
    if v > db.KM_DIA_MAXIMO:
        return jsonify({"ok": False, "msg": f"Más de {db.KM_DIA_MAXIMO:,} km por día no parece real".replace(",", ".")}), 400
    guardar_km_dia(vid, v)
    _auditar(f"Fijó los km por día del {_coche_txt(vid)}", f"{v:g} km/día" if v else "automático")
    return jsonify({"ok": True})


@bp_prev.route("/api/prev/coche/<int:vid>/intervalo", methods=["POST"])
def api_intervalo(vid):
    if not _puede_editar():
        return _no()
    d = request.json or {}
    try:
        km = int(float(str(d.get("intervalo_km") or 0).replace(".", "").replace(",", ".")))
    except ValueError:
        return jsonify({"ok": False, "msg": "Poné un número"}), 400
    guardar_intervalo(vid, int(d["tarea_id"]), km, _quien())
    _auditar(f"Cambió cada cuánto se hace una tarea en el {_coche_txt(vid)}",
             f"tarea {d['tarea_id']} · {km if km else 'la del plan'}")
    return jsonify({"ok": True})


@bp_prev.route("/api/prev/coche/<int:vid>/registrar", methods=["POST"])
def api_registrar(vid):
    if not _puede_editar():
        return _no()
    d = request.json or {}
    regs = d.get("registros") or []
    origen = d.get("origen") if d.get("origen") in ("manual", "inicial") else "manual"
    try:
        costo = float(str(d.get("costo") or 0).replace(".", "").replace(",", "."))
    except ValueError:
        costo = 0
    n = registrar(vid, regs, origen=origen, usuario=_quien(), observaciones=d.get("observaciones") or "",
                  costo=costo)
    if not n:
        return jsonify({"ok": False, "msg": "No quedó nada registrado: falta el km."}), 400
    _auditar(f"Registró {n} tarea{'s' if n != 1 else ''} del preventivo del {_coche_txt(vid)}",
             "último hecho (carga inicial)" if origen == "inicial" else "")
    return jsonify({"ok": True, "registradas": n})


@bp_prev.route("/api/prev/registros/<int:rid>", methods=["DELETE"])
def api_borrar_registro(rid):
    if not _puede_editar():
        return _no()
    ok, r = borrar_registro(rid)
    if not ok:
        return jsonify({"ok": False, "msg": r}), 404
    _auditar(f"Borró un registro del preventivo del {_coche_txt(r['vehiculo_id'])}",
             f"{r['fecha']} · {int(r['km'] or 0)} km")
    return jsonify({"ok": True})


@bp_prev.route("/api/prev/ot/<int:ot_id>", methods=["GET"])
def api_info_ot(ot_id):
    if not _puede_ver():
        return _no()
    r = info_ot(ot_id)
    if r is None:
        return jsonify({"ok": False, "msg": "Esa OT no existe"}), 404
    return jsonify(r)


@bp_prev.route("/api/prev/ot/<int:ot_id>/agregar", methods=["POST"])
def api_agregar_a_ot(ot_id):
    if not _puede_editar():
        return _no()
    n = agregar_a_ot(ot_id, (request.json or {}).get("tareas") or [])
    if n:
        _auditar(f"Agregó {n} tarea{'s' if n != 1 else ''} del plan a la OT #{ot_id}")
    return jsonify({"ok": True, "agregadas": n})


@bp_prev.route("/api/prev/ot_item/<int:item_id>", methods=["POST"])
def api_vincular(item_id):
    if not _puede_editar():
        return _no()
    d = request.json or {}
    r = vincular_item(item_id, [int(x) for x in (d.get("tareas") or [])], _quien())
    return jsonify({"ok": True, "resultado": r})


@bp_prev.route("/api/prev/agenda", methods=["GET"])
def api_agenda():
    if not _puede_ver():
        return _no()
    hoy = date.fromisoformat(_hoy_txt())
    desde = request.args.get("desde") or hoy.replace(day=1).isoformat()
    hasta = request.args.get("hasta") or (hoy.replace(day=1) + timedelta(days=41)).isoformat()
    try:
        date.fromisoformat(desde)
        date.fromisoformat(hasta)
    except ValueError:
        return jsonify({"ok": False, "msg": "Fechas inválidas"}), 400
    if date.fromisoformat(hasta).toordinal() - date.fromisoformat(desde).toordinal() > 120:
        return jsonify({"ok": False, "msg": "Rango muy largo"}), 400
    return jsonify(agenda(desde, hasta))


@bp_prev.route("/api/prev/para_agendar", methods=["GET"])
def api_para_agendar():
    if not _puede_ver():
        return _no()
    dias = request.args.get("dias")
    return jsonify(para_agendar(int(dias) if dias and dias.isdigit() else None))


@bp_prev.route("/api/prev/agendar_lote", methods=["POST"])
def api_agendar_lote():
    if not _puede_editar():
        return _no()
    d = request.json or {}
    r = agendar_lote(d.get("turnos") or [], _quien())
    if r["agendados"]:
        _auditar(f"Agendó {r['agendados']} turno{'s' if r['agendados'] != 1 else ''} del preventivo de una vez")
    return jsonify(r)


@bp_prev.route("/api/prev/turnos", methods=["POST"])
def api_crear_turno():
    if not _puede_editar():
        return _no()
    d = request.json or {}
    if not d.get("vehiculo_id"):
        return jsonify({"ok": False, "msg": "Elegí el coche"}), 400
    r = crear_turno(d, _quien())
    if r.get("ok"):
        t = r["turno"]
        _auditar(f"Agendó un turno de taller para el {_coche_txt(t['vehiculo_id'])}", f"{t['fecha']} {t.get('hora') or ''}")
    return jsonify(r)


@bp_prev.route("/api/prev/turnos/<int:tid>", methods=["PATCH"])
def api_editar_turno(tid):
    if not _puede_editar():
        return _no()
    d = request.json or {}
    r = actualizar_turno(tid, d, _quien())
    if r.get("ok"):
        t = r["turno"]
        que = {"cancelado": "Canceló", "ausente": "Marcó que no vino", "cumplido": "Marcó cumplido",
               "en_taller": "Marcó que llegó", "agendado": "Volvió a agendar"}.get(d.get("estado"), "Cambió")
        _auditar(f"{que} el turno del {_coche_txt(t['vehiculo_id'])}", f"{t['fecha']} · {d.get('motivo') or ''}")
    return jsonify(r)


@bp_prev.route("/api/prev/turnos/<int:tid>", methods=["DELETE"])
def api_borrar_turno(tid):
    if not _puede_editar():
        return _no()
    borrar_turno(tid)
    _auditar(f"Borró el turno #{tid} del taller")
    return jsonify({"ok": True})


@bp_prev.route("/api/prev/turnos/<int:tid>/ot", methods=["POST"])
def api_turno_ot(tid):
    if not _puede_editar():
        return _no()
    r = abrir_ot_de_turno(tid, _quien())
    if r.get("ok") and not r.get("ya_estaba"):
        _auditar(f"Abrió la OT #{r['ot_id']} desde un turno del preventivo")
    return jsonify(r)


@bp_prev.route("/api/prev/turnos/<int:tid>/cumplir", methods=["POST"])
def api_cumplir_turno(tid):
    if not _puede_editar():
        return _no()
    r = cumplir_turno(tid, request.json or {}, _quien())
    return jsonify(r)


@bp_prev.route("/api/prev/cumplimiento", methods=["GET"])
def api_cumplimiento():
    if not _puede_ver():
        return _no()
    return jsonify(cumplimiento())


@bp_prev.route("/api/prev/config", methods=["GET", "POST"])
def api_config():
    if request.method == "GET":
        if not _puede_ver():
            return _no()
        return jsonify(_cfg())
    if not _puede_editar():
        return _no()
    cfg = guardar_config(request.json or {})
    _auditar("Cambió los cupos del taller", f"{cfg['cupos_dia']} por día")
    return jsonify({"ok": True, "config": cfg})


@bp_prev.route("/api/prev/cupo_dia", methods=["POST"])
def api_cupo_dia():
    if not _puede_editar():
        return _no()
    d = request.json or {}
    guardar_cupo_dia(str(d.get("fecha") or "")[:10], d.get("cupo"))
    return jsonify({"ok": True})


@bp_prev.route("/api/prev/planes", methods=["GET"])
def api_planes():
    if not _puede_ver():
        return _no()
    return jsonify(planes_detalle())


@bp_prev.route("/api/prev/planes", methods=["POST"])
def api_crear_plan():
    if not _puede_editar():
        return _no()
    d = request.json or {}
    ok, r = crear_plan(d.get("nombre"), d.get("descripcion") or "", d.get("copiar_de"))
    if ok:
        _auditar(f"Creó el plan \"{d.get('nombre')}\"", "copia" if d.get("copiar_de") else "")
        return jsonify({"ok": True, "id": r})
    return jsonify({"ok": False, "msg": r}), 400


@bp_prev.route("/api/prev/planes/<int:pid>", methods=["PATCH", "DELETE"])
def api_plan(pid):
    if not _puede_editar():
        return _no()
    if request.method == "DELETE":
        ok, r = borrar_plan(pid)
        if ok:
            _auditar(f"Borró el plan #{pid}")
        return jsonify({"ok": ok, "msg": r}), (200 if ok else 400)
    ok, r = editar_plan(pid, request.json or {})
    return jsonify({"ok": ok, "msg": r}), (200 if ok else 400)


@bp_prev.route("/api/prev/planes/<int:pid>/tareas", methods=["POST"])
def api_agregar_tarea(pid):
    if not _puede_editar():
        return _no()
    ok, r = agregar_tarea(pid, request.json or {})
    if ok:
        _auditar(f"Agregó una tarea al plan #{pid}", (request.json or {}).get("tarea", ""))
        return jsonify({"ok": True, "id": r})
    return jsonify({"ok": False, "msg": r}), 400


@bp_prev.route("/api/prev/planes/<int:pid>/asignar", methods=["POST"])
def api_asignar(pid):
    if not _puede_editar():
        return _no()
    vids = [int(x) for x in ((request.json or {}).get("vehiculos") or [])]
    if not vids:
        return jsonify({"ok": False, "msg": "Elegí los coches"}), 400
    asignar(vids, pid)
    _auditar(f"Asignó el plan #{pid} a {len(vids)} coche{'s' if len(vids) != 1 else ''}")
    return jsonify({"ok": True, "asignados": len(vids)})


@bp_prev.route("/api/prev/tareas/<int:tid>", methods=["PATCH", "DELETE"])
def api_tarea(tid):
    if not _puede_editar():
        return _no()
    if request.method == "DELETE":
        ok, r = borrar_tarea(tid)
        if ok:
            _auditar(f"Borró la tarea #{tid} de un plan")
        return jsonify({"ok": ok, "msg": r}), (200 if ok else 400)
    d = request.json or {}
    ok, r = editar_tarea(tid, d)
    if ok and "intervalo_km" in d:
        _auditar(f"Cambió cada cuánto se hace \"{r['tarea']}\"", f"{r['intervalo_km']} → {d['intervalo_km']} km")
    return jsonify({"ok": ok, "msg": r if not ok else "ok"}), (200 if ok else 400)


@bp_prev.route("/api/prev/sugerir", methods=["POST"])
def api_sugerir():
    """Para probar a qué tarea del plan corresponde un texto."""
    if not _puede_ver():
        return _no()
    d = request.json or {}
    vid = d.get("vehiculo_id")
    conn = get_connection()
    tareas = _tareas_del_coche(conn, int(vid)) if vid else []
    conn.close()
    ids = sugerir_tareas(d.get("texto") or "", tareas)
    return jsonify({"ids": ids, "tareas": [t["tarea"] for t in tareas if t["id"] in ids]})
