"""
rendicion_combustible.py — Rendición de combustible por sobre (La Santaniana)

Como el sistema que usaba la oficina de Concepción ("Rendición de Gastos"):
cada coche tiene un SOBRE abierto donde van los comprobantes de las cargas
del coche (en la base, afuera, o en Puma por el convenio). El sobre se
abre con el km del tablero, se le van cargando los comprobantes y se cierra
con el km final: ahí salen los km recorridos, los litros y el consumo.

    abierto  → se cargan los comprobantes
    cerrado  → se puso el km final; los comprobantes ya no se tocan
    rendido  → administración controló el sobre

Cada comprobante con litros es además una CARGA del coche en la tabla de
combustible (origen 'rendicion'): suma al consumo del coche y al control de
robos. Los comprobantes no traen kilometraje, así que al cerrar el sobre la
última carga toma el km final. Con eso el cálculo general (de tanque a
tanque) mide el sobre entero: del km final del sobre anterior al de este,
con todos los litros del medio, que es lo mismo que hacía el sistema viejo.

Si el chofer ya había cargado esa misma carga desde el celular, al agregar el
comprobante se avisa y se puede usar esa carga en vez de crear otra, para que
los litros no se cuenten dos veces.

El número del sobre lo propone el sistema (el último + 1) y se puede cambiar
por el que viene escrito en el sobre de papel. No se puede repetir.
"""

import re
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, session, send_file
from db_compat import get_connection, USE_POSTGRES

bp_rend_comb = Blueprint("rendicion_combustible", __name__)

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
SECCION = "comb_rendicion"
ESTADOS = ("abierto", "cerrado", "rendido")
TIPOS = ["FACTURA", "TICKET", "VALE", "REMISIÓN"]
# Dónde se carga (lo que el sistema viejo llamaba "Cuenta asociada a la
# Unidad"). Lo pidió la oficina de Concepción: en la base (el tanque del
# taller), afuera en cualquier estación, o en Puma por el convenio. Shell
# queda por los sobres que ya se cargaron así. Se puede escribir otro.
LUGARES = [("BASE", "Base (taller)"), ("FUERA", "Fuera"), ("PUMA", "Puma (convenio)"), ("PY SHELL", "Shell")]
CUENTA_INICIAL = "BASE"
MAX_ADITIVOS = 200          # litros de aditivo (AdBlue) en un comprobante
MAX_KM_SOBRE = 60000        # más que esto entre apertura y cierre es un error de tipeo


def _rollback(conn):
    try:
        conn.rollback()
    except Exception:
        pass


def _ahora():
    try:
        from hora_local import ahora_iso
        return ahora_iso()
    except Exception:
        from datetime import datetime
        return datetime.now().isoformat(timespec="seconds")


def _hoy():
    try:
        from hora_local import hoy
        return hoy()
    except Exception:
        return date.today().isoformat()


def _num(v):
    """'1.250' → 1250 ; '50,5' → 50.5 ; '201.35' → 201.35 ; números tal cual."""
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif s.count(".") > 1 or (s.count(".") == 1 and len(s.split(".")[1]) == 3):
        s = s.replace(".", "")            # punto de miles
    try:
        return float(s)
    except ValueError:
        return 0.0


def _fecha(v):
    try:
        return date.fromisoformat(str(v)[:10]).isoformat()
    except (TypeError, ValueError):
        return ""


def _txt(v, mayus=False, largo=120):
    s = " ".join(str(v or "").split())[:largo]
    return s.upper() if mayus else s


def _lugar_carga(lugar):
    """Cómo lo ve el resto del sistema de combustible: en el taller o en una
    estación (y de qué emblema, si se sabe)."""
    l = (lugar or "").upper().strip()
    if l in ("BASE", "TALLER") or "BASE" in l.split():
        return "taller", ""
    if l in ("FUERA", "AFUERA", ""):
        return "tercerizado", ""
    return "tercerizado", _emblema(l)


def _emblema(cuenta):
    """'PY SHELL' → 'SHELL': el emblema de la estación para el resto del sistema."""
    try:
        from corporativos import EMBLEMAS
    except Exception:
        EMBLEMAS = ["PETROPAR", "COPETROL", "SHELL", "PUMA", "PETROBRAS", "BARCOS Y RODADOS"]
    c = (cuenta or "").upper()
    for e in EMBLEMAS:
        if e in c:
            return e
    return c[:40]


def _existe_tabla(conn, tabla):
    try:
        if USE_POSTGRES:
            r = conn.execute("SELECT 1 FROM information_schema.tables WHERE table_name=?", (tabla,)).fetchone()
        else:
            r = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tabla,)).fetchone()
        return bool(r)
    except Exception:
        _rollback(conn)
        return False


# ════════════════════════════════════════════════════════════════════════════
# TABLAS
# ════════════════════════════════════════════════════════════════════════════

def init_rendicion_combustible():
    conn = get_connection()
    nueva = not _existe_tabla(conn, "comb_sobres")
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS comb_sobres (
            id {PK},
            numero INTEGER NOT NULL,
            vehiculo_id INTEGER NOT NULL,
            chofer TEXT DEFAULT '',
            cuenta TEXT DEFAULT '',             -- dónde carga: BASE, FUERA, PUMA, PY SHELL...
            estado TEXT DEFAULT 'abierto',      -- abierto | cerrado | rendido
            km_inicial REAL DEFAULT 0,
            km_final REAL DEFAULT 0,
            fecha_apertura TEXT DEFAULT '',
            fecha_cierre TEXT DEFAULT '',
            observaciones TEXT DEFAULT '',
            abierto_por TEXT DEFAULT '',
            abierto_el TEXT DEFAULT '',
            cerrado_por TEXT DEFAULT '',
            cerrado_el TEXT DEFAULT '',
            rendido_por TEXT DEFAULT '',
            rendido_el TEXT DEFAULT '',
            carga_cierre_id INTEGER             -- la carga que tomó el km final
        )""")
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS comb_comprobantes (
            id {PK},
            sobre_id INTEGER NOT NULL,
            fecha TEXT DEFAULT '',
            tipo TEXT DEFAULT '',               -- FACTURA, TICKET, VALE...
            letra TEXT DEFAULT '',
            numero TEXT DEFAULT '',
            litros REAL DEFAULT 0,
            aditivos REAL DEFAULT 0,            -- litros de aditivo (AdBlue)
            nro_ref TEXT DEFAULT '',
            carga_id INTEGER,                   -- su carga en la tabla de combustible
            carga_propia INTEGER DEFAULT 1,     -- 1: la creó el sobre · 0: era una carga del celular
            registrado_por TEXT DEFAULT '',
            registrado_el TEXT DEFAULT ''
        )""")
    # Cada comprobante dice dónde se cargó (por defecto, lo del sobre): un
    # coche puede cargar en la base y afuera dentro del mismo sobre
    try:
        if USE_POSTGRES:
            conn.execute("ALTER TABLE comb_comprobantes ADD COLUMN IF NOT EXISTS lugar TEXT DEFAULT ''")
        else:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(comb_comprobantes)").fetchall()}
            if "lugar" not in cols:
                conn.execute("ALTER TABLE comb_comprobantes ADD COLUMN lugar TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        _rollback(conn)
    for sql in ("CREATE UNIQUE INDEX IF NOT EXISTS ux_comb_sobres_numero ON comb_sobres (numero)",
                "CREATE INDEX IF NOT EXISTS ix_comb_sobres_veh ON comb_sobres (vehiculo_id)",
                "CREATE INDEX IF NOT EXISTS ix_comb_sobres_estado ON comb_sobres (estado)",
                "CREATE INDEX IF NOT EXISTS ix_comb_comp_sobre ON comb_comprobantes (sobre_id)",
                "CREATE INDEX IF NOT EXISTS ix_comb_comp_carga ON comb_comprobantes (carga_id)"):
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            _rollback(conn)
    conn.commit()
    if nueva:
        _habilitar_a_quien_lo_pidio(conn)
    conn.close()


def _habilitar_a_quien_lo_pidio(conn):
    """La primera vez se le habilita la sección a Lorena, que fue quien la
    pidió. Si un usuario ve todo el sistema (sin secciones elegidas) ya la ve;
    después se maneja desde el panel de Usuarios."""
    try:
        from permisos import desde_texto, a_texto
        filas = conn.execute("""SELECT id, COALESCE(secciones,'') AS s FROM usuarios
                                WHERE rol='taller' AND (LOWER(COALESCE(nombre,'')) LIKE ? OR LOWER(usuario) LIKE ?)""",
                             ("%lorena%", "%lorena%")).fetchall()
        for r in filas:
            secs = desde_texto(r["s"])
            if secs and SECCION not in secs:
                conn.execute("UPDATE usuarios SET secciones=? WHERE id=?", (a_texto(secs + [SECCION]), r["id"]))
        conn.commit()
    except Exception:
        _rollback(conn)


# ════════════════════════════════════════════════════════════════════════════
# CONSULTAS
# ════════════════════════════════════════════════════════════════════════════

def _consumo(s):
    """Km recorridos, litros cada 100 km y la comparación con su motor."""
    km = (s.get("km_final") or 0) - (s.get("km_inicial") or 0)
    litros = float(s.get("litros") or 0)
    out = {"km": None, "l100": None, "km_l": None, "aditivo_l100": None, "comparacion": None}
    if s.get("estado") != "abierto" and (s.get("km_final") or 0) > 0 and km > 0:
        out["km"] = round(km)
        if litros > 0:
            out["l100"] = round(litros / km * 100, 2)
            out["km_l"] = round(km / litros, 2)
            try:
                from database import comparar_con_referencia
                comp = comparar_con_referencia(s["vehiculo_id"], {"litros_100km": out["l100"], "km_l": out["km_l"]})
                out["comparacion"] = comp
            except Exception:
                pass
        if float(s.get("aditivos") or 0) > 0:
            out["aditivo_l100"] = round(float(s["aditivos"]) / km * 100, 2)
    return out


def _coche(s):
    return str(s.get("n_interno") or s.get("patente") or "")


SELECT_SOBRES = """
    SELECT s.*, v.n_interno, v.patente, v.marca, v.modelo,
           COUNT(cc.id) AS comprobantes,
           COALESCE(SUM(cc.litros), 0) AS litros,
           COALESCE(SUM(cc.aditivos), 0) AS aditivos,
           MIN(cc.fecha) AS primera, MAX(cc.fecha) AS ultima
    FROM comb_sobres s
    JOIN vehiculos v ON v.id = s.vehiculo_id
    LEFT JOIN comb_comprobantes cc ON cc.sobre_id = s.id
"""
GROUP_SOBRES = " GROUP BY s.id, v.n_interno, v.patente, v.marca, v.modelo"


def _fila(r):
    s = dict(r)
    s["litros"] = round(float(s.get("litros") or 0), 2)
    s["aditivos"] = round(float(s.get("aditivos") or 0), 2)
    s["coche"] = _coche(s)
    s.update({"consumo": _consumo(s)})
    return s


def siguiente_numero(conn=None):
    propia = conn is None
    conn = conn or get_connection()
    try:
        r = conn.execute("SELECT MAX(numero) AS m FROM comb_sobres").fetchone()
        return int(r["m"]) + 1 if r and r["m"] else None
    finally:
        if propia:
            conn.close()


def lista(estado="", q="", desde="", hasta=""):
    conn = get_connection()
    try:
        where, params = ["1=1"], []
        if estado == "pendientes":
            where.append("s.estado IN ('abierto','cerrado')")
        elif estado in ESTADOS:
            where.append("s.estado = ?")
            params.append(estado)
        if desde:
            where.append("s.fecha_apertura >= ?")
            params.append(desde)
        if hasta:
            where.append("s.fecha_apertura <= ?")
            params.append(hasta)
        q = _txt(q, largo=60)
        if q:
            if q.isdigit():
                where.append("(CAST(s.numero AS TEXT) = ? OR CAST(v.n_interno AS TEXT) LIKE ?)")
                params += [q, q + "%"]
            else:
                where.append("(UPPER(s.chofer) LIKE ? OR UPPER(v.patente) LIKE ? OR UPPER(s.cuenta) LIKE ?)")
                params += [f"%{q.upper()}%"] * 3
        filas = [_fila(r) for r in conn.execute(
            SELECT_SOBRES + " WHERE " + " AND ".join(where) + GROUP_SOBRES + " ORDER BY s.numero DESC",
            params).fetchall()]

        # Cuántos hay en cada estado (sin el filtro de estado, con el resto)
        cuenta = {e: 0 for e in ESTADOS}
        for r in conn.execute("SELECT estado, COUNT(*) AS n FROM comb_sobres GROUP BY estado").fetchall():
            cuenta[r["estado"]] = r["n"]

        # Coches activos sin sobre abierto: en el sistema viejo cada unidad
        # tiene siempre uno abierto
        abiertos = {r["vehiculo_id"] for r in conn.execute(
            "SELECT DISTINCT vehiculo_id FROM comb_sobres WHERE estado='abierto'").fetchall()}
        con_sobre = {r["vehiculo_id"] for r in conn.execute(
            "SELECT DISTINCT vehiculo_id FROM comb_sobres").fetchall()}
        sin_abierto = []
        for v in conn.execute("""SELECT id, n_interno, patente FROM vehiculos
                                 WHERE COALESCE(activo, 1) = 1 ORDER BY n_interno""").fetchall():
            if v["id"] in con_sobre and v["id"] not in abiertos:
                sin_abierto.append({"id": v["id"], "coche": str(v["n_interno"] or v["patente"] or "")})
        sig = siguiente_numero(conn)
    finally:
        conn.close()
    total_litros = round(sum(s["litros"] for s in filas), 2)
    km = sum(s["consumo"]["km"] or 0 for s in filas if s["consumo"]["l100"])
    lit_med = sum(s["litros"] for s in filas if s["consumo"]["l100"])
    return {
        "sobres": filas,
        "cuenta": cuenta,
        "sin_abierto": sin_abierto,
        "siguiente_numero": sig,
        "totales": {"sobres": len(filas), "litros": total_litros,
                    "aditivos": round(sum(s["aditivos"] for s in filas), 2),
                    "comprobantes": sum(s["comprobantes"] for s in filas),
                    "km": round(km),
                    "l100": round(lit_med / km * 100, 2) if km else None},
    }


def _sobre(conn, sid):
    r = conn.execute(SELECT_SOBRES + " WHERE s.id = ?" + GROUP_SOBRES, (sid,)).fetchone()
    return _fila(r) if r else None


def detalle(sid):
    conn = get_connection()
    try:
        s = _sobre(conn, sid)
        if not s:
            return None
        comps = [dict(r) for r in conn.execute(
            """SELECT cc.*, c.origen AS carga_origen, c.chofer AS carga_chofer, c.odometro AS carga_odometro,
                      c.registrado_por AS carga_registrada_por
               FROM comb_comprobantes cc LEFT JOIN combustible c ON c.id = cc.carga_id
               WHERE cc.sobre_id = ? ORDER BY cc.fecha, cc.id""", (sid,)).fetchall()]
        # El sobre anterior y el siguiente del mismo coche, para moverse entre ellos
        ant = conn.execute("""SELECT id, numero, km_final FROM comb_sobres
                              WHERE vehiculo_id=? AND numero < ? ORDER BY numero DESC LIMIT 1""",
                           (s["vehiculo_id"], s["numero"])).fetchone()
        sig = conn.execute("""SELECT id, numero, estado FROM comb_sobres
                              WHERE vehiculo_id=? AND numero > ? ORDER BY numero LIMIT 1""",
                           (s["vehiculo_id"], s["numero"])).fetchone()
    finally:
        conn.close()
    for c in comps:
        c["lugar"] = c.get("lugar") or s.get("cuenta") or ""
        c["litros"] = round(float(c.get("litros") or 0), 2)
        c["aditivos"] = round(float(c.get("aditivos") or 0), 2)
        c["vinculada"] = not c.get("carga_propia") and bool(c.get("carga_id"))
    s["comprobantes_lista"] = comps
    s["anterior"] = dict(ant) if ant else None
    s["siguiente"] = dict(sig) if sig else None
    return s


def sugerencia(vid):
    """Lo que se propone al abrir un sobre para ese coche: el km inicial (el
    final del último sobre cerrado o, si no hay, el km que tiene el coche en
    el sistema), el chofer y la cuenta del último sobre, y si ya tiene uno
    abierto."""
    conn = get_connection()
    try:
        ult = conn.execute("""SELECT * FROM comb_sobres WHERE vehiculo_id=? ORDER BY numero DESC LIMIT 1""",
                           (vid,)).fetchone()
        cerrado = conn.execute("""SELECT km_final, numero FROM comb_sobres
                                  WHERE vehiculo_id=? AND estado<>'abierto' AND km_final > 0
                                  ORDER BY numero DESC LIMIT 1""", (vid,)).fetchone()
        abierto = conn.execute("""SELECT id, numero, fecha_apertura FROM comb_sobres
                                  WHERE vehiculo_id=? AND estado='abierto' ORDER BY numero DESC LIMIT 1""",
                               (vid,)).fetchone()
        cuenta = conn.execute("""SELECT cuenta, COUNT(*) AS n FROM comb_sobres WHERE cuenta<>''
                                 GROUP BY cuenta ORDER BY COUNT(*) DESC LIMIT 1""").fetchone()
    finally:
        conn.close()
    km, de_donde = 0, ""
    if cerrado:
        km, de_donde = cerrado["km_final"], f"km final del sobre {cerrado['numero']}"
    else:
        try:
            from database import km_actual_vehiculo
            km = km_actual_vehiculo(vid) or 0
            de_donde = "km que tiene el coche en el sistema" if km else ""
        except Exception:
            km = 0
    return {
        "km_inicial": round(km or 0),
        "km_de_donde": de_donde,
        "chofer": ult["chofer"] if ult else "",
        "cuenta": (ult["cuenta"] if ult and ult["cuenta"] else (cuenta["cuenta"] if cuenta else CUENTA_INICIAL)),
        "abierto": dict(abierto) if abierto else None,
    }


def listas():
    conn = get_connection()
    try:
        cuentas = [r["cuenta"] for r in conn.execute(
            "SELECT cuenta, COUNT(*) AS n FROM comb_sobres WHERE cuenta<>'' GROUP BY cuenta ORDER BY COUNT(*) DESC").fetchall()]
        tipos = [r["tipo"] for r in conn.execute(
            "SELECT tipo, COUNT(*) AS n FROM comb_comprobantes WHERE tipo<>'' GROUP BY tipo ORDER BY COUNT(*) DESC").fetchall()]
        ult = conn.execute("SELECT tipo FROM comb_comprobantes WHERE tipo<>'' ORDER BY id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    try:
        from database import nombres_de_choferes
        choferes = nombres_de_choferes()
    except Exception:
        choferes = []
    fijos = [v for v, _ in LUGARES]
    cuentas = fijos + [c for c in cuentas if c not in fijos]
    for t in TIPOS:
        if t not in tipos:
            tipos.append(t)
    return {"choferes": choferes, "cuentas": cuentas, "tipos": tipos,
            "lugares": [{"valor": v, "texto": t} for v, t in LUGARES],
            "ultimo_tipo": ult["tipo"] if ult else TIPOS[0]}


# ════════════════════════════════════════════════════════════════════════════
# SOBRES
# ════════════════════════════════════════════════════════════════════════════

class Pregunta(Exception):
    """Algo para confirmar antes de seguir (409): número de comprobante
    repetido, coche con otro sobre abierto, carga que ya cargó el chofer..."""
    def __init__(self, tipo, msg, **extra):
        super().__init__(msg)
        self.tipo, self.msg, self.extra = tipo, msg, extra


def _numero_ok(conn, numero, sid=None):
    try:
        n = int(_num(numero))
    except (TypeError, ValueError):
        n = 0
    if n <= 0 or n > 2_000_000_000:
        raise ValueError("Poné el número del sobre.")
    r = conn.execute("SELECT id FROM comb_sobres WHERE numero=?" + (" AND id<>?" if sid else ""),
                     (n, sid) if sid else (n,)).fetchone()
    if r:
        raise ValueError(f"Ya existe el sobre {n}. Poné otro número.")
    return n


def _vehiculo(conn, vid):
    try:
        vid = int(vid)
    except (TypeError, ValueError):
        return None
    return conn.execute("SELECT id, n_interno, patente FROM vehiculos WHERE id=?", (vid,)).fetchone()


def crear(d, quien, forzar=False):
    conn = get_connection()
    try:
        v = _vehiculo(conn, d.get("vehiculo_id"))
        if not v:
            raise ValueError("Elegí el coche.")
        numero = _numero_ok(conn, d.get("numero"))
        fecha = _fecha(d.get("fecha_apertura")) or _hoy()
        if fecha > _hoy():
            raise ValueError("La fecha de apertura no puede ser futura.")
        km_ini = _num(d.get("km_inicial"))
        if km_ini < 0 or km_ini > 5_000_000:
            raise ValueError("Revisá el km inicial.")
        if not forzar:
            ab = conn.execute("""SELECT numero, fecha_apertura FROM comb_sobres
                                 WHERE vehiculo_id=? AND estado='abierto' ORDER BY numero DESC LIMIT 1""",
                              (v["id"],)).fetchone()
            if ab:
                raise Pregunta("otro_abierto",
                               f"El {v['n_interno'] or v['patente']} ya tiene abierto el sobre {ab['numero']} "
                               f"(desde el {_dm(ab['fecha_apertura'])}). ¿Abrir otro igual?")
        cur = conn.execute("""INSERT INTO comb_sobres (numero, vehiculo_id, chofer, cuenta, estado, km_inicial,
                                  fecha_apertura, observaciones, abierto_por, abierto_el)
                              VALUES (?,?,?,?,'abierto',?,?,?,?,?)""",
                           (numero, v["id"], _txt(d.get("chofer"), True, 80), _txt(d.get("cuenta"), True, 60),
                            km_ini, fecha, _txt(d.get("observaciones"), largo=400), quien, _ahora()))
        sid = cur.lastrowid or conn.execute("SELECT id FROM comb_sobres WHERE numero=?", (numero,)).fetchone()["id"]
        conn.commit()
        return sid, numero, str(v["n_interno"] or v["patente"])
    except Exception:
        _rollback(conn)
        raise
    finally:
        conn.close()


def _dm(f):
    f = str(f or "")
    return f"{f[8:10]}/{f[5:7]}" if len(f) >= 10 else f


def _cargas_propias(conn, sid):
    return [r["carga_id"] for r in conn.execute(
        "SELECT carga_id FROM comb_comprobantes WHERE sobre_id=? AND carga_propia=1 AND carga_id IS NOT NULL",
        (sid,)).fetchall()]


def editar(sid, d, es_admin=False):
    """Los datos del sobre. Abierto se puede cambiar todo; cerrado o rendido,
    solo las observaciones (para tocar el resto hay que reabrirlo)."""
    conn = get_connection()
    try:
        s = conn.execute("SELECT * FROM comb_sobres WHERE id=?", (sid,)).fetchone()
        if not s:
            raise LookupError("Ese sobre ya no existe.")
        cambios = {}
        if "observaciones" in d:
            cambios["observaciones"] = _txt(d.get("observaciones"), largo=400)
        otros = {k for k in d if k != "observaciones"}
        if otros and s["estado"] != "abierto":
            raise ValueError("El sobre está cerrado: para cambiar los datos hay que reabrirlo.")
        if "numero" in d:
            cambios["numero"] = _numero_ok(conn, d.get("numero"), sid)
        if "chofer" in d:
            cambios["chofer"] = _txt(d.get("chofer"), True, 80)
        if "cuenta" in d:
            cambios["cuenta"] = _txt(d.get("cuenta"), True, 60)
        if "km_inicial" in d:
            k = _num(d.get("km_inicial"))
            if k < 0 or k > 5_000_000:
                raise ValueError("Revisá el km inicial.")
            cambios["km_inicial"] = k
        if "km_final" in d:
            k = _num(d.get("km_final"))
            if k < 0 or k > 5_000_000:
                raise ValueError("Revisá el km final.")
            cambios["km_final"] = k
        if "fecha_apertura" in d:
            f = _fecha(d.get("fecha_apertura"))
            if not f or f > _hoy():
                raise ValueError("Revisá la fecha de apertura.")
            cambios["fecha_apertura"] = f
        if "vehiculo_id" in d:
            v = _vehiculo(conn, d.get("vehiculo_id"))
            if not v:
                raise ValueError("Elegí el coche.")
            if v["id"] != s["vehiculo_id"]:
                vinc = conn.execute("""SELECT COUNT(*) AS n FROM comb_comprobantes
                                       WHERE sobre_id=? AND carga_propia=0 AND carga_id IS NOT NULL""",
                                    (sid,)).fetchone()["n"]
                if vinc:
                    raise ValueError("Este sobre usa cargas que el chofer hizo desde el celular con ese coche: "
                                     "para cambiar el coche, sacá primero esos comprobantes.")
                cambios["vehiculo_id"] = v["id"]
        if not cambios:
            return
        conn.execute(f"UPDATE comb_sobres SET {', '.join(k + '=?' for k in cambios)} WHERE id=?",
                     tuple(cambios.values()) + (sid,))
        if "cuenta" in cambios:
            # Los comprobantes que tenían el lugar del sobre (o ninguno) lo
            # siguen; los que se marcaron distinto a mano quedan como están
            lc, emb = _lugar_carga(cambios["cuenta"])
            for cc in conn.execute("""SELECT id, carga_id, carga_propia FROM comb_comprobantes
                                      WHERE sobre_id=? AND (COALESCE(lugar,'')='' OR lugar=?)""",
                                   (sid, s["cuenta"] or "")).fetchall():
                conn.execute("UPDATE comb_comprobantes SET lugar=? WHERE id=?", (cambios["cuenta"], cc["id"]))
                if cc["carga_propia"] and cc["carga_id"]:
                    conn.execute("UPDATE combustible SET estacion=?, lugar_carga=?, emblema=? WHERE id=?",
                                 (cambios["cuenta"], lc, emb, cc["carga_id"]))
        # Las cargas que creó el sobre siguen al sobre
        propias = _cargas_propias(conn, sid)
        if propias:
            marcas = ",".join("?" * len(propias))
            if "chofer" in cambios:
                conn.execute(f"UPDATE combustible SET chofer=? WHERE id IN ({marcas})", [cambios["chofer"]] + propias)
            if "vehiculo_id" in cambios:
                conn.execute(f"UPDATE combustible SET vehiculo_id=? WHERE id IN ({marcas})",
                             [cambios["vehiculo_id"]] + propias)
            if "numero" in cambios:
                for cc in conn.execute("SELECT * FROM comb_comprobantes WHERE sobre_id=? AND carga_propia=1",
                                       (sid,)).fetchall():
                    conn.execute("UPDATE combustible SET observaciones=? WHERE id=?",
                                 (_obs_carga(cambios["numero"], cc), cc["carga_id"]))
        conn.commit()
        if "vehiculo_id" in cambios:
            _recalcular(s["vehiculo_id"])
            _recalcular(cambios["vehiculo_id"])
        return cambios
    except Exception:
        _rollback(conn)
        raise
    finally:
        conn.close()


def borrar(sid, es_admin=False):
    """Un sobre vacío lo borra cualquiera que cargue; con comprobantes, solo
    administración (se van también las cargas que había creado)."""
    conn = get_connection()
    try:
        s = conn.execute("SELECT * FROM comb_sobres WHERE id=?", (sid,)).fetchone()
        if not s:
            raise LookupError("Ese sobre ya no existe.")
        n = conn.execute("SELECT COUNT(*) AS n FROM comb_comprobantes WHERE sobre_id=?", (sid,)).fetchone()["n"]
        if n and not es_admin:
            raise PermissionError("Este sobre tiene comprobantes: solo administración lo puede borrar.")
        if s["estado"] == "rendido" and not es_admin:
            raise PermissionError("El sobre ya está rendido.")
        propias = _cargas_propias(conn, sid)
        if propias:
            conn.execute(f"DELETE FROM combustible WHERE id IN ({','.join('?' * len(propias))})", propias)
        # Si el km final había quedado en una carga del celular, se le saca
        if s["carga_cierre_id"] and s["carga_cierre_id"] not in propias:
            conn.execute("UPDATE combustible SET odometro=0 WHERE id=?", (s["carga_cierre_id"],))
        conn.execute("DELETE FROM comb_comprobantes WHERE sobre_id=?", (sid,))
        conn.execute("DELETE FROM comb_sobres WHERE id=?", (sid,))
        conn.commit()
        _recalcular(s["vehiculo_id"])
        return dict(s), n
    except Exception:
        _rollback(conn)
        raise
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# COMPROBANTES
# ════════════════════════════════════════════════════════════════════════════

def _obs_carga(numero_sobre, cc):
    comp = " ".join(x for x in (cc["tipo"], cc["letra"], cc["numero"]) if x)
    return f"Sobre {numero_sobre}" + (f" · {comp}" if comp else "")


def _recalcular(vid):
    try:
        from database import _actualizar_consumo_desde_combustible
        _actualizar_consumo_desde_combustible(int(vid))
    except Exception:
        pass


def _precio():
    try:
        from corporativos import ultimo_precio_litro
        return float(ultimo_precio_litro() or 0)
    except Exception:
        return 0.0


def _datos_comprobante(d):
    fecha = _fecha(d.get("fecha"))
    if not fecha:
        raise ValueError("Poné la fecha del comprobante.")
    if fecha > _hoy():
        raise ValueError("La fecha del comprobante no puede ser futura.")
    if fecha < "2020-01-01":
        raise ValueError("Revisá la fecha del comprobante.")
    litros = round(_num(d.get("litros")), 2)
    aditivos = round(_num(d.get("aditivos")), 2)
    try:
        from corporativos import MAX_LITROS_POR_CARGA as MAXL
    except Exception:
        MAXL = 700
    if litros < 0 or litros > MAXL:
        raise ValueError(f"Revisá los litros: {litros:g} no entra en ningún tanque de la flota (máximo {MAXL}).")
    if aditivos < 0 or aditivos > MAX_ADITIVOS:
        raise ValueError(f"Revisá los litros de aditivo (máximo {MAX_ADITIVOS}).")
    if litros <= 0 and aditivos <= 0:
        raise ValueError("Poné los litros (o los litros de aditivo).")
    return {
        "fecha": fecha,
        "tipo": _txt(d.get("tipo"), True, 20),
        "letra": _txt(d.get("letra"), True, 3),
        "numero": _txt(d.get("numero"), True, 30),
        "litros": litros,
        "aditivos": aditivos,
        "nro_ref": _txt(d.get("nro_ref"), True, 30),
        "lugar": _txt(d.get("lugar"), True, 60),
    }


def _controles(conn, s, c, comp_id=None, forzar=False, vincular=None):
    """Antes de guardar: el número de comprobante repetido y la misma carga
    ya cargada por el chofer desde el celular."""
    if c["numero"] and not forzar:
        r = conn.execute("""SELECT cc.id, cc.fecha, s.numero AS sobre FROM comb_comprobantes cc
                            JOIN comb_sobres s ON s.id = cc.sobre_id
                            WHERE cc.numero=? AND cc.tipo=? AND cc.letra=?""" + (" AND cc.id<>?" if comp_id else ""),
                         (c["numero"], c["tipo"], c["letra"], comp_id) if comp_id else
                         (c["numero"], c["tipo"], c["letra"])).fetchone()
        if r:
            comp = " ".join(x for x in (c["tipo"], c["letra"], c["numero"]) if x)
            raise Pregunta("repetido", f"El comprobante {comp} ya está cargado en el sobre {r['sobre']} "
                                       f"(del {_dm(r['fecha'])}). ¿Cargarlo igual?")
    if comp_id is not None or c["litros"] <= 0 or vincular == 0:
        return None
    # Una carga del mismo coche, del mismo día (o del anterior/siguiente), con
    # los mismos litros, que no venga de un sobre: probablemente la cargó el
    # chofer desde el celular.
    f = date.fromisoformat(c["fecha"])
    cands = [dict(r) for r in conn.execute(
        """SELECT c.id, c.fecha, c.litros, c.chofer, c.origen, c.odometro, c.registrado_por FROM combustible c
           WHERE c.vehiculo_id=? AND c.fecha BETWEEN ? AND ? AND ABS(c.litros - ?) <= 1.0
             AND COALESCE(c.origen, '') <> 'rendicion'
             AND NOT EXISTS (SELECT 1 FROM comb_comprobantes x WHERE x.carga_id = c.id)
           ORDER BY c.fecha, c.id""",
        (s["vehiculo_id"], (f - timedelta(days=1)).isoformat(), (f + timedelta(days=1)).isoformat(),
         c["litros"])).fetchall()]
    if vincular:
        elegida = next((x for x in cands if x["id"] == int(vincular)), None)
        if not elegida:
            raise ValueError("Esa carga ya no está disponible para usar.")
        return elegida
    if cands:
        x = cands[0]
        quien = x["chofer"] or x["registrado_por"] or "alguien"
        desde = "desde el celular" if x["origen"] == "corporativo" else "en el sistema"
        raise Pregunta("misma_carga",
                       f"Ya hay una carga del {s['coche']} del {_dm(x['fecha'])} de {x['litros']:g} L "
                       f"que cargó {quien} {desde}. ¿Es la misma del comprobante?",
                       candidatas=cands)
    return None


def agregar_comprobante(sid, d, quien, forzar=False, vincular=None):
    conn = get_connection()
    try:
        s = _sobre(conn, sid)
        if not s:
            raise LookupError("Ese sobre ya no existe.")
        if s["estado"] != "abierto":
            raise ValueError("El sobre está cerrado: para agregar comprobantes hay que reabrirlo.")
        c = _datos_comprobante(d)
        c["lugar"] = c["lugar"] or s["cuenta"] or CUENTA_INICIAL
        elegida = _controles(conn, s, c, forzar=forzar, vincular=vincular)
        carga_id, propia = None, 1
        if elegida:
            carga_id, propia = elegida["id"], 0
        elif c["litros"] > 0:
            precio = _precio()
            lc, emb = _lugar_carga(c["lugar"])
            cur = conn.execute("""INSERT INTO combustible
                (vehiculo_id, fecha, odometro, litros, precio_litro, costo_total, estacion, chofer, tanque_lleno,
                 observaciones, registrado_por, origen, cliente, cargado_el, lugar_carga, emblema)
                VALUES (?,?,0,?,?,?,?,?,1,?,?,'rendicion','',?,?,?)""",
                (s["vehiculo_id"], c["fecha"], c["litros"], precio, round(c["litros"] * precio, 2),
                 c["lugar"], s["chofer"], _obs_carga(s["numero"], c), quien, _ahora(), lc, emb))
            carga_id = cur.lastrowid or conn.execute(
                "SELECT MAX(id) AS m FROM combustible WHERE vehiculo_id=?", (s["vehiculo_id"],)).fetchone()["m"]
        cur = conn.execute("""INSERT INTO comb_comprobantes (sobre_id, fecha, tipo, letra, numero, litros, aditivos,
                                  nro_ref, lugar, carga_id, carga_propia, registrado_por, registrado_el)
                              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                           (sid, c["fecha"], c["tipo"], c["letra"], c["numero"], c["litros"], c["aditivos"],
                            c["nro_ref"], c["lugar"], carga_id, propia, quien, _ahora()))
        cid = cur.lastrowid
        conn.commit()
        _recalcular(s["vehiculo_id"])
        return cid, s, c, bool(elegida)
    except Exception:
        _rollback(conn)
        raise
    finally:
        conn.close()


def _comprobante(conn, cid):
    r = conn.execute("""SELECT cc.*, s.estado, s.numero AS sobre_numero, s.vehiculo_id, s.id AS sid
                        FROM comb_comprobantes cc JOIN comb_sobres s ON s.id = cc.sobre_id
                        WHERE cc.id=?""", (cid,)).fetchone()
    return dict(r) if r else None


def editar_comprobante(cid, d, forzar=False):
    conn = get_connection()
    try:
        cc = _comprobante(conn, cid)
        if not cc:
            raise LookupError("Ese comprobante ya no existe.")
        if cc["estado"] != "abierto":
            raise ValueError("El sobre está cerrado: para corregir comprobantes hay que reabrirlo.")
        s = _sobre(conn, cc["sid"])
        base = {k: cc[k] for k in ("fecha", "tipo", "letra", "numero", "litros", "aditivos", "nro_ref")}
        base["lugar"] = cc.get("lugar") or s["cuenta"]
        base.update({k: v for k, v in d.items() if k in base})
        c = _datos_comprobante(base)
        c["lugar"] = c["lugar"] or s["cuenta"] or CUENTA_INICIAL
        lc, emb = _lugar_carga(c["lugar"])
        _controles(conn, s, c, comp_id=cid, forzar=forzar)
        carga_id, propia = cc["carga_id"], cc["carga_propia"]
        if propia:
            if c["litros"] > 0 and carga_id:
                precio = _precio()
                conn.execute("""UPDATE combustible SET fecha=?, litros=?, precio_litro=?, costo_total=?, observaciones=?,
                                    estacion=?, lugar_carga=?, emblema=? WHERE id=?""",
                             (c["fecha"], c["litros"], precio, round(c["litros"] * precio, 2),
                              _obs_carga(cc["sobre_numero"], c), c["lugar"], lc, emb, carga_id))
            elif c["litros"] > 0 and not carga_id:
                precio = _precio()
                cur = conn.execute("""INSERT INTO combustible
                    (vehiculo_id, fecha, odometro, litros, precio_litro, costo_total, estacion, chofer, tanque_lleno,
                     observaciones, registrado_por, origen, cliente, cargado_el, lugar_carga, emblema)
                    VALUES (?,?,0,?,?,?,?,?,1,?,?,'rendicion','',?,?,?)""",
                    (s["vehiculo_id"], c["fecha"], c["litros"], precio, round(c["litros"] * precio, 2),
                     c["lugar"], s["chofer"], _obs_carga(s["numero"], c), cc["registrado_por"], _ahora(), lc, emb))
                carga_id = cur.lastrowid
            elif c["litros"] <= 0 and carga_id:
                # Quedó solo con aditivo: ya no es una carga de combustible
                conn.execute("DELETE FROM combustible WHERE id=?", (carga_id,))
                carga_id = None
        conn.execute("""UPDATE comb_comprobantes SET fecha=?, tipo=?, letra=?, numero=?, litros=?, aditivos=?,
                            nro_ref=?, lugar=?, carga_id=? WHERE id=?""",
                     (c["fecha"], c["tipo"], c["letra"], c["numero"], c["litros"], c["aditivos"], c["nro_ref"],
                      c["lugar"], carga_id, cid))
        conn.commit()
        _recalcular(cc["vehiculo_id"])
        return cc, c
    except Exception:
        _rollback(conn)
        raise
    finally:
        conn.close()


def borrar_comprobante(cid):
    conn = get_connection()
    try:
        cc = _comprobante(conn, cid)
        if not cc:
            raise LookupError("Ese comprobante ya no existe.")
        if cc["estado"] != "abierto":
            raise ValueError("El sobre está cerrado: para sacar comprobantes hay que reabrirlo.")
        if cc["carga_propia"] and cc["carga_id"]:
            conn.execute("DELETE FROM combustible WHERE id=?", (cc["carga_id"],))
        conn.execute("DELETE FROM comb_comprobantes WHERE id=?", (cid,))
        conn.commit()
        _recalcular(cc["vehiculo_id"])
        return cc
    except Exception:
        _rollback(conn)
        raise
    finally:
        conn.close()


def sobre_de_carga(carga_id):
    """Si esa carga de combustible es de un sobre: (número del sobre, si la
    creó el sobre). Lo usa la pantalla general de combustible para no tocar
    por fuera lo que se maneja desde la rendición."""
    conn = get_connection()
    try:
        r = conn.execute("""SELECT s.numero, cc.carga_propia FROM comb_comprobantes cc
                            JOIN comb_sobres s ON s.id = cc.sobre_id WHERE cc.carga_id=?""", (carga_id,)).fetchone()
        return (r["numero"], bool(r["carga_propia"])) if r else None
    except Exception:
        _rollback(conn)
        return None
    finally:
        conn.close()


def soltar_carga(carga_id):
    """Una carga del celular que estaba usada en un sobre se borró: el
    comprobante queda, sin carga."""
    conn = get_connection()
    try:
        conn.execute("UPDATE comb_comprobantes SET carga_id=NULL WHERE carga_id=?", (carga_id,))
        conn.execute("UPDATE comb_sobres SET carga_cierre_id=NULL WHERE carga_cierre_id=?", (carga_id,))
        conn.commit()
    except Exception:
        _rollback(conn)
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# CERRAR · REABRIR · RENDIR
# ════════════════════════════════════════════════════════════════════════════

def cerrar(sid, d, quien, forzar=False):
    """Se pone el km final. La última carga del sobre (por fecha) toma ese km:
    así el consumo general mide el sobre entero, de tanque a tanque."""
    conn = get_connection()
    try:
        s = _sobre(conn, sid)
        if not s:
            raise LookupError("Ese sobre ya no existe.")
        if s["estado"] != "abierto":
            raise ValueError("El sobre ya está cerrado.")
        km_f = _num(d.get("km_final")) or float(s.get("km_final") or 0)
        km_i = float(s.get("km_inicial") or 0)
        if km_f <= 0:
            raise ValueError("Poné el km final del tablero.")
        if km_i and km_f <= km_i:
            raise ValueError(f"El km final ({km_f:,.0f}) tiene que ser mayor que el inicial ({km_i:,.0f}).".replace(",", "."))
        if km_i and km_f - km_i > MAX_KM_SOBRE:
            raise ValueError(f"Son {km_f - km_i:,.0f} km en un sobre: revisá el km final.".replace(",", "."))
        fecha = _fecha(d.get("fecha_cierre")) or _hoy()
        if fecha > _hoy() or fecha < (s["fecha_apertura"] or ""):
            raise ValueError("Revisá la fecha de cierre.")
        if not forzar and not s["comprobantes"]:
            raise Pregunta("vacio", "El sobre no tiene comprobantes. ¿Cerrarlo igual?")
        # La última carga del sobre toma el km final. Si es una carga del
        # celular que ya traía su kilometraje, se respeta el que puso el chofer.
        ult = conn.execute("""SELECT c.id, c.odometro FROM comb_comprobantes cc
                              JOIN combustible c ON c.id = cc.carga_id
                              WHERE cc.sobre_id=? ORDER BY c.fecha DESC, c.id DESC LIMIT 1""", (sid,)).fetchone()
        carga_cierre = None
        if ult and not float(ult["odometro"] or 0):
            conn.execute("UPDATE combustible SET odometro=?, tanque_lleno=1 WHERE id=?", (km_f, ult["id"]))
            carga_cierre = ult["id"]
        conn.execute("""UPDATE comb_sobres SET estado='cerrado', km_final=?, fecha_cierre=?, cerrado_por=?,
                            cerrado_el=?, carga_cierre_id=? WHERE id=?""",
                     (km_f, fecha, quien, _ahora(), carga_cierre, sid))
        conn.commit()
        _recalcular(s["vehiculo_id"])
        return _sobre_simple(sid)
    except Exception:
        _rollback(conn)
        raise
    finally:
        conn.close()


def _sobre_simple(sid):
    conn = get_connection()
    try:
        return _sobre(conn, sid)
    finally:
        conn.close()


def reabrir(sid, es_admin=False):
    """Rendido → cerrado (solo administración). Cerrado → abierto: la carga
    que había tomado el km final vuelve a quedar sin kilometraje."""
    conn = get_connection()
    try:
        s = conn.execute("SELECT * FROM comb_sobres WHERE id=?", (sid,)).fetchone()
        if not s:
            raise LookupError("Ese sobre ya no existe.")
        if s["estado"] == "rendido":
            if not es_admin:
                raise PermissionError("El sobre ya está rendido: solo administración lo puede volver atrás.")
            conn.execute("UPDATE comb_sobres SET estado='cerrado', rendido_por='', rendido_el='' WHERE id=?", (sid,))
            nuevo = "cerrado"
        elif s["estado"] == "cerrado":
            if s["carga_cierre_id"]:
                conn.execute("UPDATE combustible SET odometro=0 WHERE id=?", (s["carga_cierre_id"],))
            conn.execute("""UPDATE comb_sobres SET estado='abierto', fecha_cierre='', cerrado_por='', cerrado_el='',
                                carga_cierre_id=NULL WHERE id=?""", (sid,))
            nuevo = "abierto"
        else:
            raise ValueError("El sobre ya está abierto.")
        conn.commit()
        _recalcular(s["vehiculo_id"])
        return dict(s), nuevo
    except Exception:
        _rollback(conn)
        raise
    finally:
        conn.close()


def rendir(sid, quien):
    conn = get_connection()
    try:
        s = conn.execute("SELECT * FROM comb_sobres WHERE id=?", (sid,)).fetchone()
        if not s:
            raise LookupError("Ese sobre ya no existe.")
        if s["estado"] != "cerrado":
            raise ValueError("Primero hay que cerrar el sobre con el km final." if s["estado"] == "abierto"
                             else "El sobre ya está rendido.")
        conn.execute("UPDATE comb_sobres SET estado='rendido', rendido_por=?, rendido_el=? WHERE id=?",
                     (quien, _ahora(), sid))
        conn.commit()
        return dict(s)
    except Exception:
        _rollback(conn)
        raise
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ════════════════════════════════════════════════════════════════════════════

def _puede_ver():
    return session.get("rol") in ("admin", "taller", "auditor")


def _puede_cargar():
    return session.get("rol") in ("admin", "taller")


def _es_admin():
    return session.get("rol") == "admin"


def _quien():
    return session.get("nombre") or session.get("usuario") or ""


def _auditar(accion, detalle=""):
    try:
        from database import registrar_auditoria
        registrar_auditoria(usuario=_quien() or "?", rol=session.get("rol") or "",
                            accion=accion, categoria="Combustible", detalle=str(detalle)[:200])
    except Exception:
        pass


def _no():
    return jsonify({"ok": False, "msg": "Sin permiso"}), 403


def _error(e):
    if isinstance(e, Pregunta):
        return jsonify({"ok": False, "pregunta": e.tipo, "msg": e.msg, **e.extra}), 409
    if isinstance(e, LookupError):
        return jsonify({"ok": False, "msg": str(e)}), 404
    if isinstance(e, PermissionError):
        return jsonify({"ok": False, "msg": str(e)}), 403
    if isinstance(e, ValueError):
        return jsonify({"ok": False, "msg": str(e)}), 400
    raise e


def _det(sid):
    """El detalle del sobre con lo que puede hacer quien lo pide."""
    d = detalle(sid)
    if d:
        d.update(puede_cargar=_puede_cargar(), es_admin=_es_admin())
    return d


def _si(v):
    return v in (1, True, "1", "true", "si", "sí")


@bp_rend_comb.route("/api/comb_rend", methods=["GET"])
def api_lista():
    if not _puede_ver():
        return _no()
    a = request.args
    d = lista(a.get("estado", ""), a.get("q", ""), _fecha(a.get("desde")), _fecha(a.get("hasta")))
    d.update(puede_cargar=_puede_cargar(), es_admin=_es_admin(), hoy=_hoy())
    return jsonify(d)


@bp_rend_comb.route("/api/comb_rend/listas", methods=["GET"])
def api_listas():
    if not _puede_ver():
        return _no()
    return jsonify(listas())


@bp_rend_comb.route("/api/comb_rend/sugerencia", methods=["GET"])
def api_sugerencia():
    if not _puede_ver():
        return _no()
    vid = request.args.get("vehiculo_id", type=int)
    if not vid:
        return jsonify({"error": "Falta el coche"}), 400
    return jsonify(sugerencia(vid))


@bp_rend_comb.route("/api/comb_rend", methods=["POST"])
def api_crear():
    if not _puede_cargar():
        return _no()
    d = request.get_json(silent=True) or {}
    try:
        sid, numero, coche = crear(d, _quien(), forzar=_si(d.get("forzar")))
    except Exception as e:
        return _error(e)
    _auditar(f"Abrió el sobre de combustible {numero}", f"Coche {coche}")
    return jsonify({"ok": True, "id": sid, "sobre": _det(sid)})


@bp_rend_comb.route("/api/comb_rend/<int:sid>", methods=["GET"])
def api_detalle(sid):
    if not _puede_ver():
        return _no()
    s = detalle(sid)
    if not s:
        return jsonify({"ok": False, "msg": "Ese sobre ya no existe."}), 404
    return jsonify({**s, "puede_cargar": _puede_cargar(), "es_admin": _es_admin()})


@bp_rend_comb.route("/api/comb_rend/<int:sid>", methods=["PATCH"])
def api_editar(sid):
    if not _puede_cargar():
        return _no()
    d = request.get_json(silent=True) or {}
    try:
        cambios = editar(sid, d, _es_admin())
    except Exception as e:
        return _error(e)
    s = detalle(sid)
    if cambios:
        _auditar(f"Corrigió el sobre de combustible {s['numero']}", ", ".join(sorted(cambios)))
    return jsonify({"ok": True, "sobre": s})


@bp_rend_comb.route("/api/comb_rend/<int:sid>", methods=["DELETE"])
def api_borrar(sid):
    if not _puede_cargar():
        return _no()
    try:
        s, n = borrar(sid, _es_admin())
    except Exception as e:
        return _error(e)
    _auditar(f"Borró el sobre de combustible {s['numero']}", f"{n} comprobante(s)")
    return jsonify({"ok": True})


@bp_rend_comb.route("/api/comb_rend/<int:sid>/comprobantes", methods=["POST"])
def api_agregar_comprobante(sid):
    if not _puede_cargar():
        return _no()
    d = request.get_json(silent=True) or {}
    # vincular: el id de la carga del celular que es la misma; 0 = "es otra carga"
    vinc = d.get("vincular")
    try:
        vinc = None if vinc is None or vinc == "" else int(vinc)
    except (TypeError, ValueError):
        vinc = None
    try:
        cid, s, c, vinculada = agregar_comprobante(sid, d, _quien(), forzar=_si(d.get("forzar")), vincular=vinc)
    except Exception as e:
        return _error(e)
    _auditar(f"Cargó un comprobante en el sobre {s['numero']}",
             f"{c['tipo']} {c['numero']} · {c['litros']:g} L" + (" (usó la carga del celular)" if vinculada else ""))
    return jsonify({"ok": True, "id": cid, "sobre": _det(sid)})


@bp_rend_comb.route("/api/comb_rend/comprobantes/<int:cid>", methods=["PATCH", "DELETE"])
def api_comprobante(cid):
    if not _puede_cargar():
        return _no()
    try:
        if request.method == "DELETE":
            cc = borrar_comprobante(cid)
            _auditar(f"Sacó un comprobante del sobre {cc['sobre_numero']}",
                     f"{cc['tipo']} {cc['numero']} · {cc['litros']:g} L")
        else:
            d = request.get_json(silent=True) or {}
            cc, c = editar_comprobante(cid, d, forzar=_si(d.get("forzar")))
            _auditar(f"Corrigió un comprobante del sobre {cc['sobre_numero']}",
                     f"{c['tipo']} {c['numero']} · {cc['litros']:g} → {c['litros']:g} L")
    except Exception as e:
        return _error(e)
    return jsonify({"ok": True, "sobre": _det(cc["sid"])})


@bp_rend_comb.route("/api/comb_rend/<int:sid>/cerrar", methods=["POST"])
def api_cerrar(sid):
    if not _puede_cargar():
        return _no()
    d = request.get_json(silent=True) or {}
    try:
        s = cerrar(sid, d, _quien(), forzar=_si(d.get("forzar")))
    except Exception as e:
        return _error(e)
    co = s["consumo"]
    _auditar(f"Cerró el sobre de combustible {s['numero']}",
             f"Coche {s['coche']}: {co['km'] or 0} km, {s['litros']:g} L"
             + (f", {co['l100']} L/100km" if co["l100"] else ""))
    return jsonify({"ok": True, "sobre": _det(sid)})


@bp_rend_comb.route("/api/comb_rend/<int:sid>/reabrir", methods=["POST"])
def api_reabrir(sid):
    if not _puede_cargar():
        return _no()
    try:
        s, nuevo = reabrir(sid, _es_admin())
    except Exception as e:
        return _error(e)
    _auditar(f"Volvió el sobre de combustible {s['numero']} a {nuevo}")
    return jsonify({"ok": True, "sobre": _det(sid)})


@bp_rend_comb.route("/api/comb_rend/<int:sid>/rendir", methods=["POST"])
def api_rendir(sid):
    if not _es_admin():
        return jsonify({"ok": False, "msg": "Solo administración marca los sobres como rendidos."}), 403
    try:
        s = rendir(sid, _quien())
    except Exception as e:
        return _error(e)
    _auditar(f"Marcó rendido el sobre de combustible {s['numero']}")
    return jsonify({"ok": True, "sobre": _det(sid)})


@bp_rend_comb.route("/api/comb_rend/<int:sid>/pdf", methods=["GET"])
def api_pdf(sid):
    if not _puede_ver():
        return _no()
    s = detalle(sid)
    if not s:
        return jsonify({"ok": False, "msg": "Ese sobre ya no existe."}), 404
    import rend_comb_pdf
    buf = rend_comb_pdf.pdf_sobre(s)
    return send_file(buf, mimetype="application/pdf", as_attachment=False,
                     download_name=f"sobre-{s['numero']}-coche-{s['coche']}.pdf")


@bp_rend_comb.route("/api/comb_rend/pdf", methods=["GET"])
def api_pdf_lista():
    if not _puede_ver():
        return _no()
    a = request.args
    d = lista(a.get("estado", ""), a.get("q", ""), _fecha(a.get("desde")), _fecha(a.get("hasta")))
    import rend_comb_pdf
    filtro = {"estado": a.get("estado", ""), "q": a.get("q", ""), "desde": _fecha(a.get("desde")),
              "hasta": _fecha(a.get("hasta"))}
    buf = rend_comb_pdf.pdf_lista(d, filtro)
    return send_file(buf, mimetype="application/pdf", as_attachment=False,
                     download_name=f"sobres-combustible-{_hoy()}.pdf")
