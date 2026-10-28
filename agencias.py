"""
agencias.py — Agencias de venta de pasajes y sus contratos (La Santaniana)

Las agencias que venden pasajes de la empresa, en qué condiciones lo hacen y
qué vence. Fase 1: fichas, contratos con versiones, papeles, vencimientos y
avisos, y la ubicación de cada local con botones a Google Maps (sin clave ni
costo: son enlaces que abren Maps).

  agencias              la ficha: datos, responsable, estado y ubicación
  agencia_contratos     cada versión del contrato (contrato, renovación,
                        adenda). Nunca se pisa una versión: la que rige en una
                        fecha es la de "desde" más reciente que ya empezó. Así
                        queda el historial de qué condiciones había en cada
                        momento (lo va a usar la cuenta de comisiones).
  agencia_documentos    los papeles (RUC, patente, cédula…) con su archivo y
                        su vencimiento

Semáforo de cada agencia:
  mal   contrato vencido o sin contrato, garantía vencida, papel obligatorio
        vencido
  ojo   contrato que vence en 60 días o menos, garantía que vence en 30,
        papel que falta o vence en 30, contrato que todavía no empezó
  ok    al día
  (las suspendidas y dadas de baja van aparte)

Un contrato con renovación automática no "vence": al pasar la fecha sigue por
otro período igual. Lo que se avisa es la fecha límite para avisar que no se
renueva (hasta − días de preaviso).

Enganche en app.py:
    from agencias import bp_agencias, init_agencias
    init_agencias()
    app.register_blueprint(bp_agencias)
"""

import base64
import json
import re
import unicodedata
import urllib.parse
import urllib.request
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, session, Response
from db_compat import get_connection, USE_POSTGRES

from hora_local import hoy as _hoy, ahora_iso

bp_agencias = Blueprint("agencias", __name__)

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"

ESTADOS_AGENCIA = ("activa", "suspendida", "baja")
TIPOS_VERSION = {"contrato": "Contrato", "renovacion": "Renovación", "adenda": "Adenda"}
FRECUENCIAS = {"diario": "Todos los días", "cada_2": "Cada 2 días", "semanal": "Una vez por semana",
               "quincenal": "Cada 15 días", "mensual": "Una vez por mes", "otro": "Otro"}
GARANTIAS = {"": "Sin garantía", "pagare": "Pagaré", "deposito": "Depósito en garantía",
             "poliza": "Póliza de caución", "otra": "Otra"}
# Los papeles que se le piden a cada agencia (los obligatorios cuentan como
# "falta" en el semáforo). Para sumar uno, se agrega acá.
TIPOS_DOC = [
    ("ruc", "Constancia de RUC", True),
    ("patente", "Patente municipal", True),
    ("cedula", "Cédula del representante", True),
    ("local", "Habilitación o permiso del local", False),
    ("otro", "Otro", False),
]
NOMBRE_DOC = {k: n for k, n, _ in TIPOS_DOC}
REQUERIDOS = [k for k, _, r in TIPOS_DOC if r]

AVISO_CONTRATO = 60          # días antes del vencimiento en que se empieza a avisar
AVISO_DOC = 30               # papeles y garantía
MAX_ARCHIVO = 9_000_000      # data URL (~6,5 MB de archivo)


# ════════════════════════════════════════════════════════════════════════════
# TABLAS
# ════════════════════════════════════════════════════════════════════════════

def _rollback(conn):
    try:
        conn.rollback()
    except Exception:
        pass


def init_agencias():
    conn = get_connection()
    for sql in (
        f"""CREATE TABLE IF NOT EXISTS agencias (
            id {PK},
            nombre TEXT NOT NULL,
            razon_social TEXT DEFAULT '',
            ruc TEXT DEFAULT '',
            representante TEXT DEFAULT '',
            ci_representante TEXT DEFAULT '',
            telefono TEXT DEFAULT '',
            whatsapp TEXT DEFAULT '',
            email TEXT DEFAULT '',
            direccion TEXT DEFAULT '',
            ciudad TEXT DEFAULT '',
            lugar TEXT DEFAULT '',
            ubicacion_link TEXT DEFAULT '',
            lat REAL,
            lng REAL,
            estado TEXT DEFAULT 'activa',
            estado_motivo TEXT DEFAULT '',
            estado_el TEXT DEFAULT '',
            nota TEXT DEFAULT '',
            creado_el TEXT DEFAULT '',
            creado_por TEXT DEFAULT '',
            actualizado_el TEXT DEFAULT '',
            actualizado_por TEXT DEFAULT '')""",
        f"""CREATE TABLE IF NOT EXISTS agencia_contratos (
            id {PK},
            agencia_id INTEGER NOT NULL,
            tipo TEXT DEFAULT 'contrato',
            numero TEXT DEFAULT '',
            desde TEXT NOT NULL,
            hasta TEXT DEFAULT '',
            renov_auto INTEGER DEFAULT 0,
            preaviso_dias INTEGER DEFAULT 0,
            comision_tipo TEXT DEFAULT 'porcentaje',
            comision REAL DEFAULT 0,
            comisiones_ruta TEXT DEFAULT '[]',
            autorizado TEXT DEFAULT '',
            exclusividad INTEGER DEFAULT 0,
            zona_exclusiva TEXT DEFAULT '',
            deposito_frec TEXT DEFAULT '',
            deposito_detalle TEXT DEFAULT '',
            cuenta_deposito TEXT DEFAULT '',
            tope_sin_depositar REAL DEFAULT 0,
            devoluciones TEXT DEFAULT '',
            garantia_tipo TEXT DEFAULT '',
            garantia_monto REAL DEFAULT 0,
            garantia_vence TEXT DEFAULT '',
            garantia_detalle TEXT DEFAULT '',
            nota TEXT DEFAULT '',
            archivo TEXT DEFAULT '',
            archivo_nombre TEXT DEFAULT '',
            anulado INTEGER DEFAULT 0,
            anulado_motivo TEXT DEFAULT '',
            creado_el TEXT DEFAULT '',
            creado_por TEXT DEFAULT '',
            actualizado_el TEXT DEFAULT '',
            actualizado_por TEXT DEFAULT '')""",
        f"""CREATE TABLE IF NOT EXISTS agencia_documentos (
            id {PK},
            agencia_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,
            descripcion TEXT DEFAULT '',
            vence TEXT DEFAULT '',
            archivo TEXT DEFAULT '',
            archivo_nombre TEXT DEFAULT '',
            subido_el TEXT DEFAULT '',
            subido_por TEXT DEFAULT '')""",
        "CREATE INDEX IF NOT EXISTS ix_agcontr_ag ON agencia_contratos (agencia_id)",
        "CREATE INDEX IF NOT EXISTS ix_agdoc_ag ON agencia_documentos (agencia_id)",
        """CREATE TABLE IF NOT EXISTS agencias_cargas (
            tanda TEXT PRIMARY KEY,
            aplicada_el TEXT DEFAULT '')""",
    ):
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            _rollback(conn)
    # El código con que la agencia figura en Delta (A61, ACD…)
    try:
        if USE_POSTGRES:
            conn.execute("ALTER TABLE agencias ADD COLUMN IF NOT EXISTS codigo TEXT DEFAULT ''")
        else:
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(agencias)").fetchall()}
            if "codigo" not in cols:
                conn.execute("ALTER TABLE agencias ADD COLUMN codigo TEXT DEFAULT ''")
        conn.commit()
    except Exception:
        _rollback(conn)
    conn.close()
    try:
        importar_delta()
    except Exception as e:
        print(f"[agencias] no se pudo importar el listado de Delta: {e}")
    aplicar_comision_general()


# ════════════════════════════════════════════════════════════════════════════
# LISTADO DE DELTA: las agencias activas de ADS (se carga una sola vez)
# ════════════════════════════════════════════════════════════════════════════

TANDA_DELTA = "delta-ads-2026-10-28"
COMISION_GENERAL = 10          # todos los agencieros cobran el 10 % del pasaje
TANDA_COMISION = "comision-10-2026-10-28"


def aplicar_comision_general():
    """Una sola vez: pone el 10 % a todos los contratos que ya estaban cargados
    (los del listado de Delta venían sin comisión). Después cada agencia se
    puede cambiar a mano en su contrato."""
    conn = get_connection()
    try:
        if conn.execute("SELECT 1 FROM agencias_cargas WHERE tanda=?", (TANDA_COMISION,)).fetchone():
            return 0
        ahora = ahora_iso()
        n = conn.execute("SELECT COUNT(*) AS n FROM agencia_contratos WHERE COALESCE(anulado,0)=0").fetchone()["n"] or 0
        conn.execute("""UPDATE agencia_contratos SET comision_tipo='porcentaje', comision=?,
                              nota=REPLACE(COALESCE(nota,''), '. Falta cargar la comisión.', ?),
                              actualizado_el=?, actualizado_por='Comisión general 10 %'
                              WHERE COALESCE(anulado,0)=0""",
                           (COMISION_GENERAL, f". Comisión general del {COMISION_GENERAL:g}%.", ahora))
        conn.execute("INSERT INTO agencias_cargas (tanda, aplicada_el) VALUES (?, ?) ON CONFLICT (tanda) DO NOTHING",
                     (TANDA_COMISION, ahora))
        conn.commit()
        if n:
            print(f"[agencias] comisión general del {COMISION_GENERAL}%: {n} contratos")
        return n
    except Exception as e:
        _rollback(conn)
        print(f"[agencias] no se pudo poner la comisión general: {e}")
        return 0
    finally:
        conn.close()



def importar_delta(forzar=False):
    """Carga las agencias del listado de Delta (agencias_delta.json) con su
    contrato: el tope de crédito y, si lo tiene, el vencimiento. Se hace una
    sola vez; las que ya existen (mismo código o mismo nombre) no se tocan."""
    import os
    ruta = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agencias_delta.json")
    if not os.path.exists(ruta):
        return 0
    conn = get_connection()
    try:
        if not forzar and conn.execute("SELECT 1 FROM agencias_cargas WHERE tanda=?", (TANDA_DELTA,)).fetchone():
            return 0
        lista = json.load(open(ruta, encoding="utf-8")).get("agencias") or []
        ya_cod, ya_nom = set(), set()
        for r in conn.execute("SELECT nombre, COALESCE(codigo,'') AS codigo FROM agencias").fetchall():
            ya_nom.add(_norm(r["nombre"]))
            if r["codigo"]:
                ya_cod.add(r["codigo"].strip().upper())
        ahora, hoy = ahora_iso(), _hoy()
        nuevas = 0
        for a in lista:
            cod, nom = str(a.get("codigo") or "").strip().upper(), _limpio(a.get("nombre"), 120)
            if not nom or cod in ya_cod or _norm(nom) in ya_nom:
                continue
            est = a.get("estado") if a.get("estado") in ESTADOS_AGENCIA else "activa"
            cur = conn.execute("""INSERT INTO agencias (nombre, codigo, representante, telefono, ciudad, estado, estado_motivo,
                                  estado_el, nota, creado_el, creado_por, actualizado_el, actualizado_por)
                                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                               (nom, cod, _limpio(a.get("representante"), 120), _limpio(a.get("telefono"), 40),
                                _limpio(a.get("ciudad"), 80), est, _limpio(a.get("motivo"), 200),
                                hoy if est != "activa" else "", _texto(a.get("nota"), 800),
                                ahora, "Listado de Delta", ahora, "Listado de Delta"))
            aid = cur.lastrowid
            hasta = str(a.get("hasta") or "")[:10]
            conn.execute("""INSERT INTO agencia_contratos (agencia_id, tipo, desde, hasta, comision_tipo, comision,
                            comisiones_ruta, tope_sin_depositar, nota, creado_el, creado_por, actualizado_el, actualizado_por)
                            VALUES (?,'contrato',?,?,'porcentaje',?,'[]',?,?,?,?,?,?)""",
                         (aid, hoy, hasta if hasta > hoy else "", COMISION_GENERAL, float(a.get("tope") or 0),
                          "Condiciones traídas de Delta: tope de crédito" + (" y vencimiento" if hasta > hoy else "")
                          + f". Comisión general del {COMISION_GENERAL:g}%.", ahora, "Listado de Delta", ahora, "Listado de Delta"))
            ya_cod.add(cod)
            ya_nom.add(_norm(nom))
            nuevas += 1
        conn.execute("INSERT INTO agencias_cargas (tanda, aplicada_el) VALUES (?, ?) ON CONFLICT (tanda) DO NOTHING",
                     (TANDA_DELTA, ahora))
        conn.commit()
        if nuevas:
            print(f"[agencias] listado de Delta: {nuevas} agencias cargadas")
        return nuevas
    except Exception:
        _rollback(conn)
        raise
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# UBICACIÓN (Google Maps sin clave: solo enlaces)
# ════════════════════════════════════════════════════════════════════════════

_COORD = r"(-?\d{1,2}(?:\.\d+)?)"
_COORD_LNG = r"(-?\d{1,3}(?:\.\d+)?)"


def _coords_validas(lat, lng):
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return None
    if -90 <= lat <= 90 and -180 <= lng <= 180 and not (lat == 0 and lng == 0):
        return round(lat, 6), round(lng, 6)
    return None


def coords_de_texto(texto):
    """Las coordenadas que trae un link de Google Maps o un texto tipo
    '-23.4064, -57.4344'. Prefiere las del lugar marcado (!3d…!4d…) a las
    del centro de la vista (@lat,lng)."""
    t = urllib.parse.unquote(str(texto or "")).replace("−", "-")
    for pat in (rf"!3d{_COORD}!4d{_COORD_LNG}",
                rf"[?&](?:q|query|ll|destination|center|daddr)=(?:loc:)?{_COORD}\s*,\s*{_COORD_LNG}",
                rf"@{_COORD}\s*,\s*{_COORD_LNG}",
                rf"^\s*{_COORD}\s*,\s*{_COORD_LNG}\s*$",
                rf"/(?:search|place|dir)/{_COORD}\s*,\s*\+?{_COORD_LNG}"):
        m = re.search(pat, t)
        if m:
            c = _coords_validas(m.group(1), m.group(2))
            if c:
                return c
    return None


def _es_link_corto(t):
    return bool(re.search(r"(maps\.app\.goo\.gl|goo\.gl/maps|g\.co/kgs)/", t or ""))


def _expandir(link):
    """Sigue el link corto de Google Maps (maps.app.goo.gl/…) hasta el largo,
    que trae las coordenadas. Si no se puede (sin internet, Google lo
    bloquea), devuelve None y el link se guarda igual: abre lo mismo."""
    try:
        req = urllib.request.Request(link, headers={"User-Agent": "Mozilla/5.0"}, method="GET")
        with urllib.request.urlopen(req, timeout=6) as r:
            return r.geturl()
    except Exception:
        return None


def ubicacion(texto):
    """De lo que se pegó en 'Ubicación' saca (link limpio, lat, lng)."""
    t = re.sub(r"\s+", " ", str(texto or "")).strip()[:600]
    if not t:
        return "", None, None
    # Del texto que comparte Maps ("Nombre del lugar https://maps.app.goo.gl/…")
    m = re.search(r"https?://\S+", t)
    link = m.group(0) if m else t
    c = coords_de_texto(link) or coords_de_texto(t)
    if not c and _es_link_corto(link):
        largo = _expandir(link)
        if largo:
            c = coords_de_texto(largo)
    if not m and c:
        link = ""          # pegaron solo coordenadas
    return link, (c[0] if c else None), (c[1] if c else None)


# ════════════════════════════════════════════════════════════════════════════
# AYUDAS
# ════════════════════════════════════════════════════════════════════════════

def _limpio(s, n=200):
    return re.sub(r"\s+", " ", str(s or "")).strip()[:n]


def _texto(s, n=1500):
    s = str(s or "").replace("\r", "").strip()
    return re.sub(r"\n{3,}", "\n\n", s)[:n]


def _norm(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def _fecha(f, obligatoria=False, nombre="La fecha"):
    f = str(f or "").strip()[:10]
    if not f:
        if obligatoria:
            raise Error(f"{nombre} es obligatoria")
        return ""
    try:
        return date.fromisoformat(f).isoformat()
    except ValueError:
        raise Error(f"{nombre} no es válida")


def _numero(v, decimales=True):
    """'1.500.000' → 1500000 · '7,5' → 7.5 · '7.5' → 7.5"""
    if isinstance(v, (int, float)):
        return float(v)
    s = re.sub(r"[^\d.,-]", "", str(v or ""))
    if not s:
        return 0.0
    if "," in s:                      # 1.500,5 · 7,5
        s = s.replace(".", "").replace(",", ".")
    elif "." in s and (not decimales or s.count(".") > 1):
        s = s.replace(".", "")        # 1.500.000 · 150.000 (plata, sin decimales)
    try:
        return float(s)
    except ValueError:
        raise Error(f"«{v}» no es un número")


def _gs(n):
    try:
        return "Gs. " + f"{int(round(float(n or 0))):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "Gs. 0"


def _pct(n):
    n = float(n or 0)
    s = f"{n:.2f}".rstrip("0").rstrip(".").replace(".", ",")
    return f"{s} %"


def comision_txt(tipo, valor):
    return _gs(valor) + " por pasaje" if tipo == "monto" else _pct(valor)


def _dias(f, hoy):
    if not f:
        return None
    try:
        return (date.fromisoformat(f) - date.fromisoformat(hoy)).days
    except ValueError:
        return None


def _fmt(f):
    try:
        d = date.fromisoformat(str(f)[:10])
        return d.strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return ""


class Error(Exception):
    pass


# ════════════════════════════════════════════════════════════════════════════
# ESTADO: qué contrato rige, qué vence
# ════════════════════════════════════════════════════════════════════════════

def _vigencia_efectiva(c, hoy):
    """(hasta efectivo, se renovó solo). Con renovación automática, al pasar
    el 'hasta' sigue otro período igual, las veces que haga falta."""
    hasta = c.get("hasta") or ""
    if not hasta or not c.get("renov_auto"):
        return hasta, False
    try:
        d0, d1, h = date.fromisoformat(c["desde"]), date.fromisoformat(hasta), date.fromisoformat(hoy)
    except ValueError:
        return hasta, False
    # El período en meses (un año = 12) cuando el contrato va de un día al
    # anterior del mismo día (1/11 al 31/10); si no, en días
    fin1 = d1 + timedelta(days=1)
    meses = (fin1.year - d0.year) * 12 + fin1.month - d0.month if fin1.day == d0.day else 0
    dias = (d1 - d0).days + 1
    renovo = False
    vueltas = 0
    while d1 < h and vueltas < 120:
        if meses > 0:
            fin1 = _sumar_meses(fin1, meses)
            d1 = fin1 - timedelta(days=1)
        else:
            d1 = d1 + timedelta(days=max(dias, 28))
        renovo = True
        vueltas += 1
    return d1.isoformat(), renovo


def _sumar_meses(d, n):
    m = d.month - 1 + n
    y, m = d.year + m // 12, m % 12 + 1
    ultimo = [31, 29 if y % 4 == 0 and (y % 100 or y % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1]
    return date(y, m, min(d.day, ultimo))


def contrato_que_rige(contratos, fecha):
    """La versión vigente en esa fecha: la de 'desde' más reciente que ya
    empezó (las anuladas no cuentan)."""
    vivos = [c for c in contratos if not c.get("anulado") and (c.get("desde") or "") <= fecha]
    return max(vivos, key=lambda c: (c["desde"], c["id"])) if vivos else None


def _estado_contrato(contratos, hoy):
    vig = contrato_que_rige(contratos, hoy)
    futuros = sorted([c for c in contratos if not c.get("anulado") and c["desde"] > hoy], key=lambda c: c["desde"])
    if not vig:
        if futuros:
            return {"estado": "por_empezar", "nivel": "ojo", "contrato": futuros[0],
                    "txt": f"El contrato arranca el {_fmt(futuros[0]['desde'])}"}
        return {"estado": "sin_contrato", "nivel": "mal", "contrato": None, "txt": "Sin contrato cargado"}
    hasta, renovo = _vigencia_efectiva(vig, hoy)
    out = {"contrato": vig, "hasta": hasta, "renovado_auto": renovo, "dias": _dias(hasta, hoy),
           "proximo": futuros[0] if futuros else None}
    if not hasta:
        return {**out, "estado": "sin_vencimiento", "nivel": "ok", "txt": "Vigente, sin fecha de fin"}
    d = out["dias"]
    if vig.get("renov_auto"):
        limite = (date.fromisoformat(hasta) - timedelta(days=int(vig.get("preaviso_dias") or 0))).isoformat()
        dl = _dias(limite, hoy)
        out["limite_preaviso"] = limite
        if vig.get("preaviso_dias") and dl is not None and 0 <= dl <= 30:
            return {**out, "estado": "preaviso", "nivel": "ojo",
                    "txt": f"Se renueva solo el {_fmt(hasta)}: si no se quiere renovar, hay que avisar antes del {_fmt(limite)}"}
        return {**out, "estado": "renueva", "nivel": "ok",
                "txt": f"Se renueva solo el {_fmt(hasta)}" + (" (ya se renovó)" if renovo else "")}
    if futuros and d is not None and d <= AVISO_CONTRATO:
        return {**out, "estado": "renovado", "nivel": "ok",
                "txt": f"Vence el {_fmt(hasta)}; ya está cargado el que sigue desde el {_fmt(futuros[0]['desde'])}"}
    if d < 0:
        return {**out, "estado": "vencido", "nivel": "mal",
                "txt": f"Contrato vencido hace {-d} día{'s' if d != -1 else ''} ({_fmt(hasta)})"}
    if d <= 15:
        return {**out, "estado": "urgente", "nivel": "ojo", "txt": f"El contrato vence en {d} día{'s' if d != 1 else ''} ({_fmt(hasta)})"}
    if d <= 30:
        return {**out, "estado": "alerta", "nivel": "ojo", "txt": f"El contrato vence en {d} días ({_fmt(hasta)})"}
    if d <= AVISO_CONTRATO:
        return {**out, "estado": "aviso", "nivel": "ojo", "txt": f"El contrato vence en {d} días ({_fmt(hasta)})"}
    return {**out, "estado": "vigente", "nivel": "ok", "txt": f"Vigente hasta el {_fmt(hasta)}"}


def _estado_garantia(c, hoy):
    if not c or not c.get("garantia_tipo"):
        return None
    base = {"tipo": c["garantia_tipo"], "nombre": GARANTIAS.get(c["garantia_tipo"], c["garantia_tipo"]),
            "monto": c.get("garantia_monto") or 0, "vence": c.get("garantia_vence") or ""}
    d = _dias(base["vence"], hoy)
    if d is None:
        return {**base, "nivel": "ok", "dias": None, "txt": base["nombre"]}
    if d < 0:
        return {**base, "nivel": "mal", "dias": d, "txt": f"{base['nombre']} vencido el {_fmt(base['vence'])}"}
    if d <= AVISO_DOC:
        return {**base, "nivel": "ojo", "dias": d, "txt": f"{base['nombre']} vence en {d} días ({_fmt(base['vence'])})"}
    return {**base, "nivel": "ok", "dias": d, "txt": f"{base['nombre']} hasta el {_fmt(base['vence'])}"}


def _estado_papeles(docs, hoy):
    """Por tipo, el último papel subido. Faltan los obligatorios sin subir."""
    ultimo = {}
    for d in sorted(docs, key=lambda x: (x.get("subido_el") or "", x["id"])):
        if d["tipo"] != "otro":
            ultimo[d["tipo"]] = d
    out = {"faltan": [], "vencidos": [], "por_vencer": [], "al_dia": []}
    for k in REQUERIDOS:
        if k not in ultimo:
            out["faltan"].append(NOMBRE_DOC[k])
    for k, d in ultimo.items():
        dd = _dias(d.get("vence"), hoy)
        nombre = NOMBRE_DOC.get(k, k)
        if dd is not None and dd < 0:
            out["vencidos"].append({"nombre": nombre, "vence": d["vence"], "obligatorio": k in REQUERIDOS})
        elif dd is not None and dd <= AVISO_DOC:
            out["por_vencer"].append({"nombre": nombre, "vence": d["vence"], "dias": dd})
        else:
            out["al_dia"].append(nombre)
    return out


ORDEN_NIVEL = {"mal": 0, "ojo": 1, "ok": 2, "suspendida": 3, "baja": 4}


def evaluar(ag, contratos, docs, hoy):
    """Todo lo que hay que saber de una agencia para la lista y la ficha."""
    ec = _estado_contrato(contratos, hoy)
    c = ec.get("contrato")
    gar = _estado_garantia(c, hoy) if ec["estado"] not in ("sin_contrato", "por_empezar") else None
    pap = _estado_papeles(docs, hoy)
    avisos = []
    if ec["nivel"] != "ok" or ec["estado"] in ("renovado",):
        avisos.append({"nivel": ec["nivel"], "que": "contrato", "txt": ec["txt"]})
    if gar and gar["nivel"] != "ok":
        avisos.append({"nivel": gar["nivel"], "que": "garantia", "txt": gar["txt"]})
    for v in pap["vencidos"]:
        avisos.append({"nivel": "mal" if v["obligatorio"] else "ojo", "que": "papel",
                       "txt": f"{v['nombre']} vencida el {_fmt(v['vence'])}"})
    for v in pap["por_vencer"]:
        avisos.append({"nivel": "ojo", "que": "papel", "txt": f"{v['nombre']} vence en {v['dias']} días"})
    if pap["faltan"]:
        avisos.append({"nivel": "ojo", "que": "papel", "txt": "Falta: " + ", ".join(pap["faltan"])})
    avisos = [a for a in avisos if a["nivel"] in ("mal", "ojo")]
    avisos.sort(key=lambda a: ORDEN_NIVEL[a["nivel"]])
    if ag["estado"] == "baja":
        nivel = "baja"
    elif ag["estado"] == "suspendida":
        nivel = "suspendida"
    else:
        nivel = avisos[0]["nivel"] if avisos else "ok"
    resumen_c = None
    if c:
        rutas = _rutas(c)
        resumen_c = {"id": c["id"], "tipo": c["tipo"], "numero": c.get("numero") or "", "desde": c["desde"],
                     "hasta": ec.get("hasta") or c.get("hasta") or "", "hasta_firmado": c.get("hasta") or "",
                     "dias": ec.get("dias"), "renov_auto": bool(c.get("renov_auto")),
                     "renovado_auto": ec.get("renovado_auto", False), "limite_preaviso": ec.get("limite_preaviso"),
                     "comision_tipo": c.get("comision_tipo") or "porcentaje", "comision": c.get("comision") or 0,
                     "comision_txt": comision_txt(c.get("comision_tipo"), c.get("comision")),
                     "rutas": rutas, "exclusividad": bool(c.get("exclusividad")),
                     "zona_exclusiva": c.get("zona_exclusiva") or "",
                     "deposito_txt": _deposito_txt(c), "por_empezar": ec["estado"] == "por_empezar"}
    return {"nivel": nivel, "avisos": avisos, "contrato": resumen_c, "estado_contrato": ec["estado"],
            "contrato_txt": ec["txt"], "garantia": gar, "papeles": pap}


def _rutas(c):
    try:
        rs = json.loads(c.get("comisiones_ruta") or "[]")
    except (TypeError, ValueError):
        rs = []
    out = []
    for r in rs if isinstance(rs, list) else []:
        if r.get("ruta"):
            out.append({"ruta": r["ruta"], "tipo": r.get("tipo") or "porcentaje", "valor": r.get("valor") or 0,
                        "txt": comision_txt(r.get("tipo") or "porcentaje", r.get("valor"))})
    return out


def _deposito_txt(c):
    f = FRECUENCIAS.get(c.get("deposito_frec") or "", "")
    det = c.get("deposito_detalle") or ""
    if f == "Otro":
        f = ""
    return " · ".join(x for x in (f, det) if x)


# ════════════════════════════════════════════════════════════════════════════
# LECTURA
# ════════════════════════════════════════════════════════════════════════════

COLS_CONTRATO_LISTA = ("id, agencia_id, tipo, numero, desde, hasta, renov_auto, preaviso_dias, comision_tipo, "
                       "comision, comisiones_ruta, autorizado, exclusividad, zona_exclusiva, deposito_frec, "
                       "deposito_detalle, cuenta_deposito, tope_sin_depositar, devoluciones, garantia_tipo, "
                       "garantia_monto, garantia_vence, garantia_detalle, nota, archivo_nombre, anulado, "
                       "anulado_motivo, creado_el, creado_por, actualizado_el, actualizado_por, "
                       "CASE WHEN COALESCE(archivo,'') <> '' THEN 1 ELSE 0 END AS tiene_archivo")
COLS_DOC_LISTA = ("id, agencia_id, tipo, descripcion, vence, archivo_nombre, subido_el, subido_por, "
                  "CASE WHEN COALESCE(archivo,'') <> '' THEN 1 ELSE 0 END AS tiene_archivo")


def _leer_todo(conn, agencia_id=None):
    w, p = ("WHERE agencia_id=?", (agencia_id,)) if agencia_id else ("", ())
    contratos, docs = {}, {}
    for r in conn.execute(f"SELECT {COLS_CONTRATO_LISTA} FROM agencia_contratos {w} ORDER BY desde, id", p).fetchall():
        contratos.setdefault(r["agencia_id"], []).append(dict(r))
    for r in conn.execute(f"SELECT {COLS_DOC_LISTA} FROM agencia_documentos {w} ORDER BY subido_el, id", p).fetchall():
        docs.setdefault(r["agencia_id"], []).append(dict(r))
    return contratos, docs


def _fila_lista(ag, ev):
    return {k: ag.get(k) for k in ("id", "nombre", "codigo", "razon_social", "ruc", "representante", "telefono", "whatsapp",
                                    "email", "direccion", "ciudad", "lugar", "ubicacion_link", "lat", "lng",
                                    "estado", "estado_motivo")} | ev


def listar(q="", hoy=None):
    hoy = hoy or _hoy()
    conn = get_connection()
    try:
        ags = [dict(r) for r in conn.execute("SELECT * FROM agencias ORDER BY nombre").fetchall()]
        contratos, docs = _leer_todo(conn)
    finally:
        conn.close()
    filas = []
    for ag in ags:
        ev = evaluar(ag, contratos.get(ag["id"], []), docs.get(ag["id"], []), hoy)
        filas.append(_fila_lista(ag, ev))
    palabras = [w for w in _norm(q).split() if w]
    if palabras:
        def texto(f):
            return _norm(" ".join(str(f.get(k) or "") for k in ("nombre", "razon_social", "ruc", "representante",
                                                                  "ciudad", "lugar", "direccion", "telefono")))
        filas = [f for f in filas if all(w in texto(f) for w in palabras)]
    filas.sort(key=lambda f: (ORDEN_NIVEL.get(f["nivel"], 9),
                              f["contrato"]["dias"] if f["contrato"] and f["contrato"]["dias"] is not None else 99999,
                              _norm(f["nombre"])))
    activas = [f for f in filas if f["estado"] == "activa"]
    resumen = {
        "total": len(filas), "activas": len(activas),
        "mal": len([f for f in activas if f["nivel"] == "mal"]),
        "ojo": len([f for f in activas if f["nivel"] == "ojo"]),
        "ok": len([f for f in activas if f["nivel"] == "ok"]),
        "vigentes": len([f for f in activas if f["estado_contrato"] in ("vigente", "aviso", "alerta", "urgente",
                                                                       "renueva", "preaviso", "renovado",
                                                                       "sin_vencimiento")]),
        "por_vencer": len([f for f in activas if f["estado_contrato"] in ("aviso", "alerta", "urgente", "preaviso")]),
        "vencidos": len([f for f in activas if f["estado_contrato"] in ("vencido", "sin_contrato")]),
        "papeles": len([f for f in activas if f["papeles"]["faltan"] or f["papeles"]["vencidos"]]),
        "suspendidas": len([f for f in filas if f["estado"] == "suspendida"]),
        "bajas": len([f for f in filas if f["estado"] == "baja"]),
        "ciudades": sorted({f["ciudad"] for f in filas if f.get("ciudad")}, key=_norm),
        "con_ubicacion": len([f for f in filas if f.get("lat") is not None or f.get("ubicacion_link")]),
    }
    return {"hoy": hoy, "agencias": filas, "resumen": resumen}


CAMPOS_DIFF = [
    ("hasta", "Hasta", _fmt),
    ("renov_auto", "Renovación automática", lambda v: "sí" if v else "no"),
    ("preaviso_dias", "Preaviso", lambda v: f"{int(v or 0)} días"),
    ("comision", "Comisión", None), ("comisiones_ruta", "Comisión por ruta", None),
    ("autorizado", "Qué puede vender", None),
    ("exclusividad", "Exclusividad", lambda v: "sí" if v else "no"),
    ("zona_exclusiva", "Zona exclusiva", None),
    ("deposito_frec", "Depósitos", lambda v: FRECUENCIAS.get(v or "", v or "—")),
    ("deposito_detalle", "Detalle del depósito", None),
    ("cuenta_deposito", "Cuenta", None),
    ("tope_sin_depositar", "Tope sin depositar", _gs),
    ("devoluciones", "Devoluciones y anulaciones", None),
    ("garantia_tipo", "Garantía", lambda v: GARANTIAS.get(v or "", v)),
    ("garantia_monto", "Monto de la garantía", _gs),
    ("garantia_vence", "Vencimiento de la garantía", _fmt),
]


def _diferencias(a, b):
    """Qué cambió de la versión a a la b (texto corto para el historial)."""
    out = []
    for k, nombre, fmt in CAMPOS_DIFF:
        if k == "comision":
            va, vb = comision_txt(a.get("comision_tipo"), a.get("comision")), comision_txt(b.get("comision_tipo"), b.get("comision"))
        elif k == "comisiones_ruta":
            va = " · ".join(f"{r['ruta']} {r['txt']}" for r in _rutas(a)) or "—"
            vb = " · ".join(f"{r['ruta']} {r['txt']}" for r in _rutas(b)) or "—"
        else:
            va, vb = a.get(k), b.get(k)
            if (va or "") == (vb or "") or (not va and not vb):
                continue
            va = fmt(va) if fmt else (va or "—")
            vb = fmt(vb) if fmt else (vb or "—")
        if va != vb:
            if isinstance(va, str) and len(va) > 60:
                out.append(f"{nombre}: cambió")
            else:
                out.append(f"{nombre}: {va or '—'} → {vb or '—'}")
    return out


def ficha(aid, hoy=None):
    hoy = hoy or _hoy()
    conn = get_connection()
    try:
        r = conn.execute("SELECT * FROM agencias WHERE id=?", (aid,)).fetchone()
        if not r:
            return None
        ag = dict(r)
        contratos, docs = _leer_todo(conn, aid)
    finally:
        conn.close()
    cs, ds = contratos.get(aid, []), docs.get(aid, [])
    ev = evaluar(ag, cs, ds, hoy)
    vig = contrato_que_rige(cs, hoy)
    versiones = []
    previo = None
    for c in cs:
        v = {**c, "tipo_txt": TIPOS_VERSION.get(c["tipo"], c["tipo"]), "rutas": _rutas(c),
             "comision_txt": comision_txt(c.get("comision_tipo"), c.get("comision")),
             "deposito_txt": _deposito_txt(c), "garantia_txt": GARANTIAS.get(c.get("garantia_tipo") or "", ""),
             "rige": bool(vig and c["id"] == vig["id"]), "futuro": c["desde"] > hoy and not c.get("anulado"),
             "cambios": _diferencias(previo, c) if previo and not c.get("anulado") else []}
        versiones.append(v)
        if not c.get("anulado"):
            previo = c
    versiones.reverse()
    papeles = []
    for d in sorted(ds, key=lambda x: (x.get("subido_el") or "", x["id"]), reverse=True):
        dd = _dias(d.get("vence"), hoy)
        papeles.append({**d, "tipo_txt": NOMBRE_DOC.get(d["tipo"], d["tipo"]), "dias": dd,
                        "nivel": "mal" if dd is not None and dd < 0 else "ojo" if dd is not None and dd <= AVISO_DOC else "ok"})
    # Los reemplazados (hay uno más nuevo del mismo tipo) se marcan
    vistos = set()
    for p in papeles:
        if p["tipo"] != "otro":
            p["reemplazado"] = p["tipo"] in vistos
            vistos.add(p["tipo"])
        else:
            p["reemplazado"] = False
    return {"hoy": hoy, "agencia": ag, **ev, "versiones": versiones,
            "vigente": next((v for v in versiones if v["rige"]), None), "papeles_lista": papeles,
            "tipos_doc": [{"k": k, "nombre": n, "obligatorio": o} for k, n, o in TIPOS_DOC]}


def avisos(hoy=None):
    """Lo que hay que atender (para el dashboard y el número del menú)."""
    d = listar(hoy=hoy)
    out = []
    for f in d["agencias"]:
        if f["estado"] != "activa":
            continue
        for a in f["avisos"]:
            urgente = a["nivel"] == "mal" or (a["que"] == "contrato" and f["contrato"]
                                              and (f["contrato"]["dias"] or 999) <= 30)
            out.append({"agencia_id": f["id"], "agencia": f["nombre"], "ciudad": f.get("ciudad") or "",
                        "nivel": a["nivel"], "que": a["que"], "txt": a["txt"], "urgente": bool(urgente)})
    out.sort(key=lambda a: (not a["urgente"], ORDEN_NIVEL[a["nivel"]], _norm(a["agencia"])))
    atender = len({a["agencia_id"] for a in out if a["urgente"]})
    return {"avisos": out, "atender": atender, "mal": d["resumen"]["mal"], "ojo": d["resumen"]["ojo"]}


# ════════════════════════════════════════════════════════════════════════════
# CAMBIOS
# ════════════════════════════════════════════════════════════════════════════

CAMPOS_AGENCIA = {"nombre": 120, "codigo": 12, "razon_social": 160, "ruc": 30, "representante": 120, "ci_representante": 30,
                  "telefono": 40, "whatsapp": 40, "email": 120, "direccion": 200, "ciudad": 80, "lugar": 160}


def _datos_agencia(d, parcial=False):
    out = {}
    for k, n in CAMPOS_AGENCIA.items():
        if k in d or not parcial:
            out[k] = _limpio(d.get(k), n)
    if "nota" in d or not parcial:
        out["nota"] = _texto(d.get("nota"), 800)
    if "nombre" in out and not out["nombre"]:
        raise Error("Poné el nombre de la agencia")
    if out.get("email") and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", out["email"]):
        raise Error("El correo no parece válido")
    if "ubicacion" in d or not parcial:
        link, lat, lng = ubicacion(d.get("ubicacion"))
        out["ubicacion_link"], out["lat"], out["lng"] = link, lat, lng
    return out


def crear_agencia(d, quien=""):
    datos = _datos_agencia(d)
    conn = get_connection()
    try:
        ya = conn.execute("SELECT id FROM agencias WHERE LOWER(nombre)=LOWER(?)", (datos["nombre"],)).fetchone()
        if ya:
            raise Error("Ya hay una agencia con ese nombre")
        ahora = ahora_iso()
        cols = list(datos) + ["estado", "creado_el", "creado_por", "actualizado_el", "actualizado_por"]
        vals = list(datos.values()) + ["activa", ahora, quien[:80], ahora, quien[:80]]
        cur = conn.execute(f"INSERT INTO agencias ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})", vals)
        aid = cur.lastrowid
        conn.commit()
        return aid
    finally:
        conn.close()


def editar_agencia(aid, d, quien=""):
    datos = _datos_agencia(d, parcial=True)
    if "estado" in d:
        est = str(d.get("estado") or "")
        if est not in ESTADOS_AGENCIA:
            raise Error("Estado inválido")
        datos["estado"] = est
        datos["estado_motivo"] = _limpio(d.get("motivo"), 200)
        datos["estado_el"] = ahora_iso()
        if est != "activa" and not datos["estado_motivo"]:
            raise Error("Contá el motivo (queda en la ficha)")
    if not datos:
        return
    conn = get_connection()
    try:
        if not conn.execute("SELECT id FROM agencias WHERE id=?", (aid,)).fetchone():
            raise Error("Esa agencia no existe")
        if datos.get("nombre"):
            ya = conn.execute("SELECT id FROM agencias WHERE LOWER(nombre)=LOWER(?) AND id<>?",
                              (datos["nombre"], aid)).fetchone()
            if ya:
                raise Error("Ya hay otra agencia con ese nombre")
        datos["actualizado_el"], datos["actualizado_por"] = ahora_iso(), quien[:80]
        conn.execute(f"UPDATE agencias SET {', '.join(k + '=?' for k in datos)} WHERE id=?",
                     list(datos.values()) + [aid])
        conn.commit()
    finally:
        conn.close()


def borrar_agencia(aid):
    conn = get_connection()
    try:
        n = conn.execute("SELECT COUNT(*) AS n FROM agencia_contratos WHERE agencia_id=?", (aid,)).fetchone()["n"]
        m = conn.execute("SELECT COUNT(*) AS n FROM agencia_documentos WHERE agencia_id=?", (aid,)).fetchone()["n"]
        if n or m:
            raise Error("Tiene contratos o papeles cargados: para sacarla de la lista, dala de baja")
        conn.execute("DELETE FROM agencias WHERE id=?", (aid,))
        conn.commit()
    finally:
        conn.close()


def _archivo_ok(a, nombre):
    a = str(a or "")
    if not a:
        return "", ""
    if not re.match(r"data:(image/(png|jpe?g|webp|gif)|application/pdf);base64,", a):
        raise Error("El archivo tiene que ser una foto o un PDF")
    if len(a) > MAX_ARCHIVO:
        raise Error("El archivo es muy pesado (máximo unos 6 MB)")
    return a, _limpio(nombre, 120) or ("contrato.pdf" if "pdf" in a[:40] else "foto.jpg")


def _datos_contrato(d):
    tipo = d.get("tipo") or "contrato"
    if tipo not in TIPOS_VERSION:
        raise Error("Tipo inválido")
    desde = _fecha(d.get("desde"), True, "La fecha de inicio")
    hasta = _fecha(d.get("hasta"), False, "La fecha de fin")
    if hasta and hasta < desde:
        raise Error("La fecha de fin es anterior a la de inicio")
    renov = 1 if d.get("renov_auto") in (1, True, "1", "true", "on") else 0
    if renov and not hasta:
        raise Error("Con renovación automática hace falta la fecha de fin del período")
    ctipo = d.get("comision_tipo") or "porcentaje"
    if ctipo not in ("porcentaje", "monto"):
        raise Error("Tipo de comisión inválido")
    com = _numero(d.get("comision"), decimales=(ctipo == "porcentaje"))
    if ctipo == "porcentaje" and not (0 <= com <= 100):
        raise Error("La comisión tiene que estar entre 0 y 100 %")
    if com < 0:
        raise Error("La comisión no puede ser negativa")
    rutas = []
    for r in d.get("rutas") or []:
        ruta = _limpio((r or {}).get("ruta"), 80)
        if not ruta:
            continue
        rt = (r.get("tipo") or "porcentaje") if r.get("tipo") in ("porcentaje", "monto") else "porcentaje"
        v = _numero(r.get("valor"), decimales=(rt == "porcentaje"))
        if rt == "porcentaje" and not (0 <= v <= 100):
            raise Error(f"La comisión de {ruta} tiene que estar entre 0 y 100 %")
        rutas.append({"ruta": ruta, "tipo": rt, "valor": v})
    frec = d.get("deposito_frec") or ""
    if frec and frec not in FRECUENCIAS:
        raise Error("Frecuencia de depósito inválida")
    gtipo = d.get("garantia_tipo") or ""
    if gtipo not in GARANTIAS:
        raise Error("Tipo de garantía inválido")
    return {
        "tipo": tipo, "numero": _limpio(d.get("numero"), 40), "desde": desde, "hasta": hasta,
        "renov_auto": renov, "preaviso_dias": int(_numero(d.get("preaviso_dias"), False)) if renov else 0,
        "comision_tipo": ctipo, "comision": com, "comisiones_ruta": json.dumps(rutas, ensure_ascii=False),
        "autorizado": _texto(d.get("autorizado"), 600),
        "exclusividad": 1 if d.get("exclusividad") in (1, True, "1", "true", "on") else 0,
        "zona_exclusiva": _limpio(d.get("zona_exclusiva"), 160),
        "deposito_frec": frec, "deposito_detalle": _limpio(d.get("deposito_detalle"), 160),
        "cuenta_deposito": _limpio(d.get("cuenta_deposito"), 160),
        "tope_sin_depositar": _numero(d.get("tope_sin_depositar"), False),
        "devoluciones": _texto(d.get("devoluciones"), 600),
        "garantia_tipo": gtipo, "garantia_monto": _numero(d.get("garantia_monto"), False) if gtipo else 0,
        "garantia_vence": _fecha(d.get("garantia_vence"), False, "El vencimiento de la garantía") if gtipo else "",
        "garantia_detalle": _limpio(d.get("garantia_detalle"), 200) if gtipo else "",
        "nota": _texto(d.get("nota"), 800),
    }


def nuevo_contrato(aid, d, quien=""):
    datos = _datos_contrato(d)
    archivo, nombre = _archivo_ok(d.get("archivo"), d.get("archivo_nombre"))
    conn = get_connection()
    try:
        if not conn.execute("SELECT id FROM agencias WHERE id=?", (aid,)).fetchone():
            raise Error("Esa agencia no existe")
        ahora = ahora_iso()
        datos.update(agencia_id=aid, archivo=archivo, archivo_nombre=nombre if archivo else "",
                     creado_el=ahora, creado_por=quien[:80], actualizado_el=ahora, actualizado_por=quien[:80])
        cur = conn.execute(f"INSERT INTO agencia_contratos ({', '.join(datos)}) VALUES ({', '.join('?' * len(datos))})",
                           list(datos.values()))
        cid = cur.lastrowid
        conn.commit()
        return cid
    finally:
        conn.close()


def corregir_contrato(cid, d, quien=""):
    """Arreglar un error de carga de una versión (no es una adenda: no deja
    versión nueva). El archivo se cambia solo si viene uno."""
    conn = get_connection()
    try:
        r = conn.execute(f"SELECT {COLS_CONTRATO_LISTA} FROM agencia_contratos WHERE id=?", (cid,)).fetchone()
        if not r:
            raise Error("Ese contrato no existe")
        actual = dict(r)
        if actual["anulado"]:
            raise Error("Esa versión está anulada")
        datos = _datos_contrato({**actual, "rutas": _rutas(actual), **d})
        if d.get("archivo"):
            datos["archivo"], datos["archivo_nombre"] = _archivo_ok(d.get("archivo"), d.get("archivo_nombre"))
        elif d.get("quitar_archivo"):
            datos["archivo"], datos["archivo_nombre"] = "", ""
        datos["actualizado_el"], datos["actualizado_por"] = ahora_iso(), quien[:80]
        conn.execute(f"UPDATE agencia_contratos SET {', '.join(k + '=?' for k in datos)} WHERE id=?",
                     list(datos.values()) + [cid])
        conn.commit()
        return actual["agencia_id"]
    finally:
        conn.close()


def anular_contrato(cid, motivo, quien=""):
    motivo = _limpio(motivo, 200)
    if not motivo:
        raise Error("Contá por qué se anula (queda en el historial)")
    conn = get_connection()
    try:
        r = conn.execute("SELECT agencia_id FROM agencia_contratos WHERE id=?", (cid,)).fetchone()
        if not r:
            raise Error("Ese contrato no existe")
        conn.execute("""UPDATE agencia_contratos SET anulado=1, anulado_motivo=?, actualizado_el=?, actualizado_por=?
                        WHERE id=?""", (motivo, ahora_iso(), quien[:80], cid))
        conn.commit()
        return r["agencia_id"]
    finally:
        conn.close()


def subir_documento(aid, d, quien=""):
    tipo = d.get("tipo") or ""
    if tipo not in NOMBRE_DOC:
        raise Error("Elegí qué papel es")
    archivo, nombre = _archivo_ok(d.get("archivo"), d.get("archivo_nombre"))
    desc = _limpio(d.get("descripcion"), 120)
    if tipo == "otro" and not desc:
        raise Error("Contá qué papel es")
    if not archivo and not d.get("sin_archivo"):
        raise Error("Subí la foto o el PDF del papel")
    vence = _fecha(d.get("vence"), False, "El vencimiento")
    conn = get_connection()
    try:
        if not conn.execute("SELECT id FROM agencias WHERE id=?", (aid,)).fetchone():
            raise Error("Esa agencia no existe")
        cur = conn.execute("""INSERT INTO agencia_documentos (agencia_id, tipo, descripcion, vence, archivo, archivo_nombre,
                                                               subido_el, subido_por) VALUES (?,?,?,?,?,?,?,?)""",
                           (aid, tipo, desc, vence, archivo, nombre if archivo else "", ahora_iso(), quien[:80]))
        did = cur.lastrowid
        conn.commit()
        return did
    finally:
        conn.close()


def borrar_documento(did):
    conn = get_connection()
    try:
        r = conn.execute("SELECT agencia_id, tipo, descripcion FROM agencia_documentos WHERE id=?", (did,)).fetchone()
        if not r:
            raise Error("Ese papel no existe")
        conn.execute("DELETE FROM agencia_documentos WHERE id=?", (did,))
        conn.commit()
        return dict(r)
    finally:
        conn.close()


def archivo(tabla, iid):
    if tabla not in ("agencia_contratos", "agencia_documentos"):
        return None
    conn = get_connection()
    try:
        r = conn.execute(f"SELECT archivo, archivo_nombre FROM {tabla} WHERE id=?", (iid,)).fetchone()
    finally:
        conn.close()
    if not r or not r["archivo"]:
        return None
    m = re.match(r"data:([\w/+.-]+);base64,(.*)$", r["archivo"], re.S)
    if not m:
        return None
    return m.group(1), base64.b64decode(m.group(2)), r["archivo_nombre"] or "archivo"


# ════════════════════════════════════════════════════════════════════════════
# RUTAS
# ════════════════════════════════════════════════════════════════════════════

def _rol():
    return session.get("rol")


def _puede_ver():
    return _rol() in ("admin", "taller", "auditor")


def _puede_editar():
    return _rol() in ("admin", "taller")


def _quien():
    return session.get("nombre") or session.get("usuario") or ""


def _no(msg="No tenés permiso para esto", codigo=403):
    return jsonify({"ok": False, "msg": msg, "error": msg}), codigo


def _auditar(accion, detalle=""):
    try:
        from database import registrar_auditoria
        registrar_auditoria(usuario=_quien() or "?", rol=_rol() or "", accion=accion,
                            categoria="Agencias", detalle=str(detalle)[:200])
    except Exception:
        pass


def _nombre_agencia(aid):
    conn = get_connection()
    try:
        r = conn.execute("SELECT nombre FROM agencias WHERE id=?", (aid,)).fetchone()
        return r["nombre"] if r else f"#{aid}"
    finally:
        conn.close()


def _envuelto(fn, editar=True):
    def f(*a, **k):
        if not (_puede_editar() if editar else _puede_ver()):
            return _no()
        try:
            return fn(*a, **k)
        except Error as e:
            return jsonify({"ok": False, "msg": str(e), "error": str(e)}), 400
    f.__name__ = fn.__name__
    return f


@bp_agencias.route("/api/agencias", methods=["GET"])
def api_lista():
    if not _puede_ver():
        return _no()
    return jsonify(listar(request.args.get("q", "")))


@bp_agencias.route("/api/agencias/avisos", methods=["GET"])
def api_avisos():
    if not _puede_ver():
        return _no()
    return jsonify(avisos())


@bp_agencias.route("/api/agencias/opciones", methods=["GET"])
def api_opciones():
    if not _puede_ver():
        return _no()
    return jsonify({"frecuencias": FRECUENCIAS, "garantias": GARANTIAS, "tipos_version": TIPOS_VERSION,
                    "tipos_doc": [{"k": k, "nombre": n, "obligatorio": o} for k, n, o in TIPOS_DOC]})


@bp_agencias.route("/api/agencias/ubicacion", methods=["POST"])
def api_ubicacion():
    """Para mostrar en el formulario qué se entendió del link pegado."""
    if not _puede_editar():
        return _no()
    link, lat, lng = ubicacion((request.get_json(silent=True) or {}).get("ubicacion"))
    return jsonify({"ok": True, "link": link, "lat": lat, "lng": lng})


@bp_agencias.route("/api/agencias/<int:aid>", methods=["GET"])
def api_ficha(aid):
    if not _puede_ver():
        return _no()
    f = ficha(aid)
    if not f:
        return _no("Esa agencia no existe", 404)
    return jsonify(f)


@bp_agencias.route("/api/agencias", methods=["POST"])
def api_crear():
    def hacer():
        d = request.get_json(silent=True) or {}
        aid = crear_agencia(d, _quien())
        _auditar("Cargó una agencia de venta de pasajes", d.get("nombre"))
        return jsonify({"ok": True, "id": aid, "ficha": ficha(aid)})
    return _envuelto(hacer)()


@bp_agencias.route("/api/agencias/<int:aid>", methods=["PATCH"])
def api_editar(aid):
    def hacer():
        d = request.get_json(silent=True) or {}
        editar_agencia(aid, d, _quien())
        if "estado" in d:
            _auditar(f"Cambió el estado de una agencia a «{d.get('estado')}»",
                     f"{_nombre_agencia(aid)}: {d.get('motivo') or ''}")
        else:
            _auditar("Editó los datos de una agencia", _nombre_agencia(aid))
        return jsonify({"ok": True, "ficha": ficha(aid)})
    return _envuelto(hacer)()


@bp_agencias.route("/api/agencias/<int:aid>", methods=["DELETE"])
def api_borrar(aid):
    def hacer():
        if _rol() != "admin":
            return _no("Solo el administrador puede borrar una agencia")
        nombre = _nombre_agencia(aid)
        borrar_agencia(aid)
        _auditar("Borró una agencia (sin contratos ni papeles)", nombre)
        return jsonify({"ok": True})
    return _envuelto(hacer)()


@bp_agencias.route("/api/agencias/<int:aid>/contratos", methods=["POST"])
def api_contrato_nuevo(aid):
    def hacer():
        d = request.get_json(silent=True) or {}
        cid = nuevo_contrato(aid, d, _quien())
        _auditar(f"Cargó {TIPOS_VERSION.get(d.get('tipo') or 'contrato', 'un contrato').lower()} de agencia",
                 f"{_nombre_agencia(aid)} desde {d.get('desde')}")
        return jsonify({"ok": True, "id": cid, "ficha": ficha(aid)})
    return _envuelto(hacer)()


@bp_agencias.route("/api/agencias/contratos/<int:cid>", methods=["PATCH"])
def api_contrato_corregir(cid):
    def hacer():
        aid = corregir_contrato(cid, request.get_json(silent=True) or {}, _quien())
        _auditar("Corrigió una versión del contrato de una agencia", _nombre_agencia(aid))
        return jsonify({"ok": True, "ficha": ficha(aid)})
    return _envuelto(hacer)()


@bp_agencias.route("/api/agencias/contratos/<int:cid>", methods=["DELETE"])
def api_contrato_anular(cid):
    def hacer():
        motivo = (request.get_json(silent=True) or {}).get("motivo") or request.args.get("motivo")
        aid = anular_contrato(cid, motivo, _quien())
        _auditar("Anuló una versión del contrato de una agencia", f"{_nombre_agencia(aid)}: {motivo}")
        return jsonify({"ok": True, "ficha": ficha(aid)})
    return _envuelto(hacer)()


@bp_agencias.route("/api/agencias/<int:aid>/documentos", methods=["POST"])
def api_doc_subir(aid):
    def hacer():
        d = request.get_json(silent=True) or {}
        subir_documento(aid, d, _quien())
        _auditar("Subió un papel de una agencia", f"{_nombre_agencia(aid)}: {NOMBRE_DOC.get(d.get('tipo'), '')}")
        return jsonify({"ok": True, "ficha": ficha(aid)})
    return _envuelto(hacer)()


@bp_agencias.route("/api/agencias/documentos/<int:did>", methods=["DELETE"])
def api_doc_borrar(did):
    def hacer():
        r = borrar_documento(did)
        _auditar("Borró un papel de una agencia",
                 f"{_nombre_agencia(r['agencia_id'])}: {NOMBRE_DOC.get(r['tipo'], r['tipo'])} {r['descripcion'] or ''}")
        return jsonify({"ok": True, "ficha": ficha(r["agencia_id"])})
    return _envuelto(hacer)()


def _servir(tabla, iid):
    if not _puede_ver():
        return _no()
    a = archivo(tabla, iid)
    if not a:
        return _no("No hay archivo", 404)
    mime, datos, nombre = a
    nombre_seguro = re.sub(r"[^\w.\- ]+", "_", nombre)[:100] or "archivo"
    return Response(datos, mimetype=mime, headers={
        "Content-Disposition": f"inline; filename=\"{nombre_seguro}\"",
        "Cache-Control": "private, max-age=300"})


@bp_agencias.route("/api/agencias/contratos/<int:cid>/archivo", methods=["GET"])
def api_contrato_archivo(cid):
    return _servir("agencia_contratos", cid)


@bp_agencias.route("/api/agencias/documentos/<int:did>/archivo", methods=["GET"])
def api_doc_archivo(did):
    return _servir("agencia_documentos", did)


@bp_agencias.route("/api/agencias/<int:aid>/pdf", methods=["GET"])
def api_pdf(aid):
    if not _puede_ver():
        return _no()
    f = ficha(aid)
    if not f:
        return _no("Esa agencia no existe", 404)
    from agencias_pdf import generar_ficha
    pdf = generar_ficha(f)
    nombre = re.sub(r"[^\w\-]+", "_", _norm(f["agencia"]["nombre"]))[:50] or "agencia"
    return Response(pdf, mimetype="application/pdf", headers={
        "Content-Disposition": f"inline; filename=\"Agencia_{nombre}.pdf\""})
