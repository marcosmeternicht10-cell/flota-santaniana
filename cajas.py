"""
cajas.py — Cajas: débitos y créditos varios (La Santaniana)

Lo mismo que «Débitos y Créditos Varios» de Walrus, pero hecho para usarlo
todos los días:

  · varias cajas (Tesorería – Taller, Casa Central…), cada una con su saldo
    en vivo y el efectivo que tiene que haber en el cajón;
  · cada movimiento es un egreso (débito: se pagó algo) o un ingreso
    (crédito: entró plata), con el comprobante del proveedor o cliente:
    RUC (se controla el dígito verificador), timbrado y su vencimiento,
    número 001-001-0000123;
  · los renglones llevan concepto y el total CON IVA: el sistema separa solo
    exento / gravado 5 % / gravado 10 % y el IVA de cada uno;
  · la foto (o PDF) de la factura queda pegada al movimiento;
  · avisa si el mismo comprobante ya se cargó, si el timbrado está vencido o
    si el RUC está mal escrito;
  · cierre diario con arqueo (lo que se contó contra lo que dice el sistema),
    y el PDF del cierre con las firmas;
  · el libro IVA del mes (compras y ventas) en Excel para el contador, con las
    marcas de la RG 90 (imputa IVA / IRE / IRP-RSP / no imputa).

Un día cerrado no se toca: para corregir algo, administración reabre el
último cierre.

  init_cajas()      tablas + conceptos de siempre + la caja «Tesorería – Taller»
  bp_cajas          las rutas /api/cajas/...
"""

import base64
import io
import json
import re
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, session, send_file, Response

from db_compat import get_connection, USE_POSTGRES
from hora_local import hoy as _hoy, ahora_iso

bp_cajas = Blueprint("cajas", __name__)

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"

TIPOS = {"egreso": "Egreso (débito)", "ingreso": "Ingreso (crédito)"}
TIPOS_IVA = {"10": "Gravado 10 %", "5": "Gravado 5 %", "exento": "Exento"}
DOCS = {
    "factura": "Factura",
    "ticket": "Ticket",
    "autofactura": "Autofactura",
    "nota_credito": "Nota de crédito",
    "recibo": "Recibo",
    "boleta": "Boleta / comprobante de venta",
    "interno": "Comprobante interno (sin factura)",
}
DOCS_CON_TIMBRADO = {"factura", "ticket", "autofactura", "nota_credito", "boleta"}
MEDIOS = {"efectivo": "Efectivo", "transferencia": "Transferencia", "cheque": "Cheque",
          "tarjeta": "Tarjeta", "vale": "Vale"}
CONDICIONES = {"contado": "Contado", "credito": "Crédito"}
MONEDAS = {"PYG": "Guaraníes", "USD": "Dólares", "BRL": "Reales", "ARS": "Pesos arg."}
MAX_ARCHIVO = 6 * 1024 * 1024      # 6 MB por archivo (las fotos se achican en el navegador)
BILLETES = [100000, 50000, 20000, 10000, 5000, 2000, 1000, 500, 100, 50]

CONCEPTOS_BASE = [
    # (código, nombre, tipo, iva por defecto)
    ("REP", "Repuestos y accesorios", "egreso", "10"),
    ("LUB", "Lubricantes y filtros", "egreso", "10"),
    ("NEU", "Neumáticos y reparación de cubiertas", "egreso", "10"),
    ("TEX", "Trabajos de taller externo", "egreso", "10"),
    ("HER", "Herramientas", "egreso", "10"),
    ("LIM", "Limpieza e higiene", "egreso", "10"),
    ("COM", "Combustible", "egreso", "10"),
    ("PEA", "Peajes", "egreso", "exento"),
    ("VIA", "Viáticos", "egreso", "exento"),
    ("FLE", "Fletes y encomiendas", "egreso", "10"),
    ("LIB", "Librería y útiles", "egreso", "10"),
    ("ALI", "Alimentos y bebidas", "egreso", "10"),
    ("MED", "Medicamentos", "egreso", "5"),
    ("TRA", "Trámites y tasas", "egreso", "exento"),
    ("VAR", "Gastos varios", "egreso", "10"),
    ("FON", "Fondos recibidos de Tesorería", "ingreso", "exento"),
    ("REI", "Reintegro / devolución", "ingreso", "exento"),
    ("CHA", "Venta de chatarra / descarte", "ingreso", "10"),
    ("OIN", "Otros ingresos", "ingreso", "10"),
]


def _rollback(conn):
    try:
        conn.rollback()
    except Exception:
        pass


def _quien():
    return session.get("nombre") or session.get("usuario") or "?"


# ════════════════════════════════════════════════════════════════════════════
# TABLAS
# ════════════════════════════════════════════════════════════════════════════

def init_cajas():
    conn = get_connection()
    tablas = [
        f"""CREATE TABLE IF NOT EXISTS cajas (
            id {PK},
            nombre TEXT NOT NULL,
            sucursal TEXT DEFAULT 'Casa Central',
            responsable TEXT DEFAULT '',
            moneda TEXT DEFAULT 'PYG',
            saldo_inicial REAL DEFAULT 0,
            efectivo_inicial REAL DEFAULT 0,
            inicio TEXT DEFAULT '',
            activa INTEGER DEFAULT 1,
            orden INTEGER DEFAULT 0,
            creado_el TEXT DEFAULT '',
            creado_por TEXT DEFAULT '')""",
        f"""CREATE TABLE IF NOT EXISTS caja_conceptos (
            id {PK},
            codigo TEXT DEFAULT '',
            nombre TEXT NOT NULL,
            tipo TEXT DEFAULT 'egreso',
            iva TEXT DEFAULT '10',
            cuenta TEXT DEFAULT '',
            activo INTEGER DEFAULT 1)""",
        f"""CREATE TABLE IF NOT EXISTS caja_movs (
            id {PK},
            caja_id INTEGER NOT NULL,
            numero INTEGER DEFAULT 0,
            tipo TEXT NOT NULL,
            fecha_emision TEXT DEFAULT '',
            fecha_oper TEXT NOT NULL,
            contraparte TEXT DEFAULT '',
            ruc TEXT DEFAULT '',
            telefono TEXT DEFAULT '',
            direccion TEXT DEFAULT '',
            doc_tipo TEXT DEFAULT 'factura',
            doc_numero TEXT DEFAULT '',
            timbrado TEXT DEFAULT '',
            timbrado_vence TEXT DEFAULT '',
            condicion TEXT DEFAULT 'contado',
            moneda TEXT DEFAULT 'PYG',
            cotizacion REAL DEFAULT 1,
            medio TEXT DEFAULT 'efectivo',
            medio_detalle TEXT DEFAULT '',
            empleado TEXT DEFAULT '',
            observacion TEXT DEFAULT '',
            exento REAL DEFAULT 0,
            grav5 REAL DEFAULT 0,
            grav10 REAL DEFAULT 0,
            iva5 REAL DEFAULT 0,
            iva10 REAL DEFAULT 0,
            total REAL DEFAULT 0,
            total_gs REAL DEFAULT 0,
            imputa_iva INTEGER DEFAULT 1,
            imputa_ire INTEGER DEFAULT 1,
            imputa_irp INTEGER DEFAULT 0,
            no_imputa INTEGER DEFAULT 0,
            transf_id INTEGER DEFAULT 0,
            estado TEXT DEFAULT 'vigente',
            anulado_motivo TEXT DEFAULT '',
            anulado_el TEXT DEFAULT '',
            anulado_por TEXT DEFAULT '',
            cierre_id INTEGER DEFAULT 0,
            creado_el TEXT DEFAULT '',
            creado_por TEXT DEFAULT '',
            actualizado_el TEXT DEFAULT '',
            actualizado_por TEXT DEFAULT '')""",
        f"""CREATE TABLE IF NOT EXISTS caja_mov_det (
            id {PK},
            mov_id INTEGER NOT NULL,
            orden INTEGER DEFAULT 0,
            concepto_id INTEGER DEFAULT 0,
            concepto TEXT DEFAULT '',
            detalle TEXT DEFAULT '',
            tipo_iva TEXT DEFAULT '10',
            total REAL DEFAULT 0,
            exento REAL DEFAULT 0,
            grav5 REAL DEFAULT 0,
            grav10 REAL DEFAULT 0,
            iva5 REAL DEFAULT 0,
            iva10 REAL DEFAULT 0)""",
        f"""CREATE TABLE IF NOT EXISTS caja_mov_archivos (
            id {PK},
            mov_id INTEGER NOT NULL,
            nombre TEXT DEFAULT '',
            tipo TEXT DEFAULT '',
            tamano INTEGER DEFAULT 0,
            datos TEXT DEFAULT '',
            subido_el TEXT DEFAULT '',
            subido_por TEXT DEFAULT '')""",
        f"""CREATE TABLE IF NOT EXISTS caja_cierres (
            id {PK},
            caja_id INTEGER NOT NULL,
            fecha TEXT NOT NULL,
            movimientos INTEGER DEFAULT 0,
            saldo_anterior REAL DEFAULT 0,
            ingresos REAL DEFAULT 0,
            egresos REAL DEFAULT 0,
            saldo_final REAL DEFAULT 0,
            efectivo_anterior REAL DEFAULT 0,
            efectivo_final REAL DEFAULT 0,
            contado REAL DEFAULT 0,
            diferencia REAL DEFAULT 0,
            arqueo TEXT DEFAULT '{{}}',
            nota TEXT DEFAULT '',
            cerrado_el TEXT DEFAULT '',
            cerrado_por TEXT DEFAULT '')""",
        "CREATE INDEX IF NOT EXISTS ix_cajamov_caja ON caja_movs (caja_id, fecha_oper)",
        "CREATE INDEX IF NOT EXISTS ix_cajamov_ruc ON caja_movs (ruc)",
        "CREATE INDEX IF NOT EXISTS ix_cajadet_mov ON caja_mov_det (mov_id)",
        "CREATE INDEX IF NOT EXISTS ix_cajaarch_mov ON caja_mov_archivos (mov_id)",
        "CREATE INDEX IF NOT EXISTS ix_cajacierre_caja ON caja_cierres (caja_id, fecha)",
    ]
    try:
        for t in tablas:
            conn.execute(t)
        conn.commit()
        if not conn.execute("SELECT 1 FROM caja_conceptos LIMIT 1").fetchone():
            for cod, nom, tipo, iva in CONCEPTOS_BASE:
                conn.execute("INSERT INTO caja_conceptos (codigo, nombre, tipo, iva) VALUES (?,?,?,?)",
                             (cod, nom, tipo, iva))
            conn.commit()
        if not conn.execute("SELECT 1 FROM cajas LIMIT 1").fetchone():
            conn.execute("""INSERT INTO cajas (nombre, sucursal, moneda, inicio, orden, creado_el, creado_por)
                            VALUES ('Tesorería – Taller', 'Casa Central', 'PYG', ?, 1, ?, 'Sistema')""",
                         (_hoy(), ahora_iso()))
            conn.commit()
    except Exception as e:
        _rollback(conn)
        print(f"[cajas] no se pudieron crear las tablas: {e}")
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# CUENTAS: IVA, RUC, NÚMEROS
# ════════════════════════════════════════════════════════════════════════════

def _num(v):
    """'1.250.000' / '1250000' / 1250000.0 / '12,5' → número."""
    if v is None or v == "":
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "")
    if re.fullmatch(r"-?\d{1,3}(\.\d{3})+(,\d+)?", s):
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return 0.0


def separar_iva(total, tipo_iva, decimales=0):
    """El total CON IVA de un renglón → exento, gravados e IVA.
    En Paraguay el IVA va incluido: 10 % → total/11 ; 5 % → total/21."""
    total = round(float(total or 0), decimales)
    r = {"exento": 0.0, "grav5": 0.0, "grav10": 0.0, "iva5": 0.0, "iva10": 0.0}
    if tipo_iva == "10":
        r["grav10"] = total
        r["iva10"] = round(total / 11, decimales)
    elif tipo_iva == "5":
        r["grav5"] = total
        r["iva5"] = round(total / 21, decimales)
    else:
        r["exento"] = total
    return r


def ruc_dv(base):
    """Dígito verificador del RUC paraguayo (módulo 11, base 11)."""
    base = re.sub(r"\D", "", str(base or ""))
    if not base:
        return None
    total, k = 0, 2
    for d in reversed(base):
        total += int(d) * k
        k = 2 if k == 11 else k + 1
    resto = total % 11
    return 11 - resto if resto > 1 else 0


def ruc_limpio(v):
    """'80.012.345-6' → '80012345-6'. Devuelve (texto, ok, aviso)."""
    s = str(v or "").strip().upper().replace(".", "").replace(" ", "")
    if not s:
        return "", True, ""
    m = re.fullmatch(r"(\d{3,9})-?(\d)", s)
    if not m:
        if re.fullmatch(r"\d{3,9}", s):     # cédula sin DV: se acepta (consumidor final, persona física)
            return s, True, ""
        return s, False, "El RUC tiene que ser números con su dígito: 80012345-6"
    base, dv = m.group(1), int(m.group(2))
    ok = ruc_dv(base) == dv
    return f"{base}-{dv}", ok, "" if ok else f"El dígito verificador no coincide: para {base} es {ruc_dv(base)}"


def doc_numero_limpio(v):
    """'1-1-123' / '001001000123' → '001-001-0000123'."""
    s = re.sub(r"\s", "", str(v or ""))
    if not s:
        return ""
    m = re.fullmatch(r"(\d{1,3})-(\d{1,3})-(\d{1,7})", s)
    if m:
        return f"{int(m.group(1)):03d}-{int(m.group(2)):03d}-{int(m.group(3)):07d}"
    d = re.sub(r"\D", "", s)
    if len(d) == 13:
        return f"{d[:3]}-{d[3:6]}-{d[6:]}"
    return s[:30]


def _fecha(v):
    s = str(v or "")[:10]
    try:
        date.fromisoformat(s)
        return s
    except ValueError:
        return ""


def _txt(v, n):
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def _txt_largo(v, n):
    s = str(v or "").replace("\r", "").strip()
    return re.sub(r"\n{3,}", "\n\n", s)[:n]


# ════════════════════════════════════════════════════════════════════════════
# SALDOS
# ════════════════════════════════════════════════════════════════════════════

def _signo(tipo):
    return 1 if tipo == "ingreso" else -1


def _ultimo_cierre(conn, caja_id):
    return conn.execute("""SELECT * FROM caja_cierres WHERE caja_id=? ORDER BY fecha DESC, id DESC LIMIT 1""",
                        (caja_id,)).fetchone()


def _saldos(conn, caja):
    """Saldo total y efectivo de la caja, con lo que falta cerrar."""
    uc = _ultimo_cierre(conn, caja["id"])
    base = uc["saldo_final"] if uc else (caja["saldo_inicial"] or 0)
    base_ef = uc["efectivo_final"] if uc else (caja["efectivo_inicial"] or 0)
    filas = conn.execute("""SELECT tipo, medio, COUNT(*) AS n, COALESCE(SUM(total_gs),0) AS t, MIN(fecha_oper) AS desde
                            FROM caja_movs WHERE caja_id=? AND estado='vigente' AND COALESCE(cierre_id,0)=0
                            GROUP BY tipo, medio""", (caja["id"],)).fetchall()
    ing = egr = ef = 0.0
    n = 0
    desde = ""
    for f in filas:
        t = float(f["t"] or 0)
        n += f["n"]
        if f["desde"] and (not desde or f["desde"] < desde):
            desde = f["desde"]
        if f["tipo"] == "ingreso":
            ing += t
        else:
            egr += t
        if f["medio"] == "efectivo":
            ef += _signo(f["tipo"]) * t
    return {
        "saldo": base + ing - egr,
        "efectivo": base_ef + ef,
        "sin_cerrar": n,
        "sin_cerrar_desde": desde,
        "ingresos_abiertos": ing,
        "egresos_abiertos": egr,
        "ultimo_cierre": uc["fecha"] if uc else "",
        "ultimo_cierre_id": uc["id"] if uc else 0,
        "ultimo_cierre_dif": float(uc["diferencia"] or 0) if uc else 0,
    }


def _caja_dict(conn, c):
    d = dict(c)
    d.update(_saldos(conn, c))
    hoy = _hoy()
    h = conn.execute("""SELECT tipo, COALESCE(SUM(total_gs),0) AS t, COUNT(*) AS n FROM caja_movs
                        WHERE caja_id=? AND estado='vigente' AND fecha_oper=? GROUP BY tipo""",
                     (c["id"], hoy)).fetchall()
    d["hoy_ingresos"] = sum(float(x["t"]) for x in h if x["tipo"] == "ingreso")
    d["hoy_egresos"] = sum(float(x["t"]) for x in h if x["tipo"] == "egreso")
    d["hoy_movs"] = sum(x["n"] for x in h)
    return d


def listar_cajas(todas=False):
    conn = get_connection()
    try:
        filas = conn.execute(f"""SELECT * FROM cajas {'' if todas else 'WHERE activa=1'}
                                 ORDER BY orden, id""").fetchall()
        return [_caja_dict(conn, c) for c in filas]
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# MOVIMIENTOS
# ════════════════════════════════════════════════════════════════════════════

COLS_LISTA = ("m.id, m.caja_id, m.numero, m.tipo, m.fecha_emision, m.fecha_oper, m.contraparte, m.ruc, "
              "m.doc_tipo, m.doc_numero, m.timbrado, m.moneda, m.cotizacion, m.medio, m.observacion, "
              "m.exento, m.grav5, m.grav10, m.iva5, m.iva10, m.total, m.total_gs, m.estado, m.cierre_id, "
              "m.transf_id, m.creado_por, m.creado_el, m.empleado")


def _conceptos_de(conn, ids):
    if not ids:
        return {}
    m = ",".join("?" * len(ids))
    out = {}
    for r in conn.execute(f"SELECT mov_id, concepto FROM caja_mov_det WHERE mov_id IN ({m}) ORDER BY orden, id",
                          list(ids)).fetchall():
        out.setdefault(r["mov_id"], []).append(r["concepto"])
    return out


def _archivos_cuenta(conn, ids):
    if not ids:
        return {}
    m = ",".join("?" * len(ids))
    return {r["mov_id"]: r["n"] for r in conn.execute(
        f"SELECT mov_id, COUNT(*) AS n FROM caja_mov_archivos WHERE mov_id IN ({m}) GROUP BY mov_id",
        list(ids)).fetchall()}


def listar_movs(caja_id, desde="", hasta="", tipo="", q="", estado="", limite=800):
    conn = get_connection()
    try:
        sql = f"SELECT {COLS_LISTA} FROM caja_movs m WHERE m.caja_id=?"
        p = [caja_id]
        if desde:
            sql += " AND m.fecha_oper>=?"
            p.append(desde)
        if hasta:
            sql += " AND m.fecha_oper<=?"
            p.append(hasta)
        if tipo in TIPOS:
            sql += " AND m.tipo=?"
            p.append(tipo)
        if estado in ("vigente", "anulado"):
            sql += " AND m.estado=?"
            p.append(estado)
        if q:
            like = f"%{q.strip().lower()}%"
            sql += """ AND (LOWER(m.contraparte) LIKE ? OR LOWER(m.ruc) LIKE ? OR LOWER(m.doc_numero) LIKE ?
                       OR LOWER(m.observacion) LIKE ? OR CAST(m.numero AS TEXT) = ?
                       OR m.id IN (SELECT mov_id FROM caja_mov_det WHERE LOWER(concepto) LIKE ? OR LOWER(detalle) LIKE ?))"""
            p += [like, like, like, like, q.strip(), like, like]
        sql += " ORDER BY m.fecha_oper DESC, m.numero DESC LIMIT ?"
        p.append(limite)
        filas = [dict(r) for r in conn.execute(sql, p).fetchall()]
        ids = [f["id"] for f in filas]
        conc, arch = _conceptos_de(conn, ids), _archivos_cuenta(conn, ids)
        tot = {"ingresos": 0.0, "egresos": 0.0, "iva10": 0.0, "iva5": 0.0, "n": 0, "sin_foto": 0}
        for f in filas:
            f["conceptos"] = conc.get(f["id"], [])
            f["archivos"] = arch.get(f["id"], 0)
            if f["estado"] == "vigente":
                tot["n"] += 1
                tot["ingresos" if f["tipo"] == "ingreso" else "egresos"] += float(f["total_gs"] or 0)
                tot["iva10"] += float(f["iva10"] or 0) * float(f["cotizacion"] or 1)
                tot["iva5"] += float(f["iva5"] or 0) * float(f["cotizacion"] or 1)
                if f["doc_tipo"] != "interno" and not f["archivos"]:
                    tot["sin_foto"] += 1
        return {"movs": filas, "totales": tot}
    finally:
        conn.close()


def ver_mov(mid):
    conn = get_connection()
    try:
        m = conn.execute("SELECT * FROM caja_movs WHERE id=?", (mid,)).fetchone()
        if not m:
            return None
        d = dict(m)
        d["detalle"] = [dict(r) for r in conn.execute(
            "SELECT * FROM caja_mov_det WHERE mov_id=? ORDER BY orden, id", (mid,)).fetchall()]
        d["archivos"] = [dict(r) for r in conn.execute(
            "SELECT id, nombre, tipo, tamano, subido_el, subido_por FROM caja_mov_archivos WHERE mov_id=? ORDER BY id",
            (mid,)).fetchall()]
        c = conn.execute("SELECT nombre FROM cajas WHERE id=?", (d["caja_id"],)).fetchone()
        d["caja_nombre"] = c["nombre"] if c else ""
        if d.get("transf_id"):
            o = conn.execute("""SELECT m.id, m.numero, m.tipo, c.nombre AS caja FROM caja_movs m
                                JOIN cajas c ON c.id=m.caja_id WHERE m.id=?""", (d["transf_id"],)).fetchone()
            d["transf"] = dict(o) if o else None
        d["avisos"] = _avisos(conn, d)
        return d
    finally:
        conn.close()


def _avisos(conn, d, excluir_id=None):
    """Lo que conviene revisar (no impide guardar)."""
    av = []
    if d.get("ruc"):
        _, ok, msg = ruc_limpio(d["ruc"])
        if not ok:
            av.append({"nivel": "mal", "msg": msg})
    if d.get("doc_tipo") in DOCS_CON_TIMBRADO:
        if not d.get("timbrado"):
            av.append({"nivel": "ojo", "msg": "Falta el número de timbrado"})
        elif not re.fullmatch(r"\d{8}", str(d["timbrado"])):
            av.append({"nivel": "ojo", "msg": "El timbrado tiene 8 números"})
        v, fe = d.get("timbrado_vence") or "", d.get("fecha_emision") or ""
        if v and fe and v < fe:
            av.append({"nivel": "mal", "msg": f"El timbrado venció el {v[8:10]}/{v[5:7]}/{v[:4]}, antes de la fecha de la factura"})
        if not d.get("doc_numero"):
            av.append({"nivel": "ojo", "msg": "Falta el número del comprobante"})
        elif not re.fullmatch(r"\d{3}-\d{3}-\d{7}", d["doc_numero"]):
            av.append({"nivel": "ojo", "msg": "El número de comprobante va así: 001-001-0000123"})
        if d.get("doc_numero") and d.get("ruc"):
            dup = conn.execute("""SELECT m.id, m.numero, c.nombre AS caja FROM caja_movs m JOIN cajas c ON c.id=m.caja_id
                                  WHERE m.ruc=? AND m.doc_numero=? AND m.estado='vigente' AND m.id<>? AND m.tipo=?""",
                               (d["ruc"], d["doc_numero"], excluir_id or d.get("id") or 0, d.get("tipo") or "")).fetchone()
            if dup:
                av.append({"nivel": "mal", "msg": f"Este comprobante ya está cargado: movimiento N° {dup['numero']} de {dup['caja']}",
                           "mov_id": dup["id"]})
    fe, fo = d.get("fecha_emision") or "", d.get("fecha_oper") or ""
    if fe and fo and fe > fo:
        av.append({"nivel": "ojo", "msg": "La fecha de la factura es posterior a la de la operación"})
    return av


def _armar(d, caja):
    """Valida y arma el movimiento desde lo que mandó la pantalla."""
    tipo = d.get("tipo")
    if tipo not in TIPOS:
        return None, "Elegí si es egreso o ingreso"
    fo = _fecha(d.get("fecha_oper")) or _hoy()
    fe = _fecha(d.get("fecha_emision")) or fo
    doc = d.get("doc_tipo") if d.get("doc_tipo") in DOCS else "factura"
    moneda = d.get("moneda") if d.get("moneda") in MONEDAS else "PYG"
    cot = _num(d.get("cotizacion")) if moneda != "PYG" else 1.0
    if moneda != "PYG" and cot <= 0:
        return None, "Poné la cotización de la moneda"
    dec = 0 if moneda == "PYG" else 2
    ruc, _, _ = ruc_limpio(d.get("ruc"))
    lineas = []
    for i, ln in enumerate(d.get("detalle") or []):
        tot = round(_num(ln.get("total")), dec)
        conc = _txt(ln.get("concepto"), 120)
        det = _txt(ln.get("detalle"), 300)
        if not tot and not conc and not det:
            continue
        if tot <= 0:
            return None, f"El renglón {i + 1} no tiene importe"
        if not conc:
            return None, f"Elegí el concepto del renglón {i + 1}"
        tiva = str(ln.get("tipo_iva") or "10")
        if tiva not in TIPOS_IVA:
            tiva = "10"
        r = {"orden": len(lineas), "concepto_id": int(_num(ln.get("concepto_id"))), "concepto": conc,
             "detalle": det, "tipo_iva": tiva, "total": tot}
        r.update(separar_iva(tot, tiva, dec))
        lineas.append(r)
    if not lineas:
        return None, "Cargá al menos un renglón con concepto e importe"
    suma = lambda k: round(sum(x[k] for x in lineas), dec)
    medio = d.get("medio") if d.get("medio") in MEDIOS else "efectivo"
    no_imp = 1 if d.get("no_imputa") else 0
    m = {
        "caja_id": caja["id"], "tipo": tipo, "fecha_emision": fe, "fecha_oper": fo,
        "contraparte": _txt(d.get("contraparte"), 150), "ruc": ruc,
        "telefono": _txt(d.get("telefono"), 40), "direccion": _txt(d.get("direccion"), 200),
        "doc_tipo": doc, "doc_numero": doc_numero_limpio(d.get("doc_numero")) if doc != "interno" else _txt(d.get("doc_numero"), 30),
        "timbrado": re.sub(r"\D", "", str(d.get("timbrado") or ""))[:8] if doc in DOCS_CON_TIMBRADO else "",
        "timbrado_vence": _fecha(d.get("timbrado_vence")) if doc in DOCS_CON_TIMBRADO else "",
        "condicion": d.get("condicion") if d.get("condicion") in CONDICIONES else "contado",
        "moneda": moneda, "cotizacion": cot, "medio": medio, "medio_detalle": _txt(d.get("medio_detalle"), 120),
        "empleado": _txt(d.get("empleado"), 120), "observacion": _txt_largo(d.get("observacion"), 1500),
        "exento": suma("exento"), "grav5": suma("grav5"), "grav10": suma("grav10"),
        "iva5": suma("iva5"), "iva10": suma("iva10"), "total": suma("total"),
        "imputa_iva": 0 if no_imp else (1 if d.get("imputa_iva", True) else 0),
        "imputa_ire": 0 if no_imp else (1 if d.get("imputa_ire", True) else 0),
        "imputa_irp": 0 if no_imp else (1 if d.get("imputa_irp") else 0),
        "no_imputa": no_imp,
    }
    m["total_gs"] = round(m["total"] * cot)
    if not m["contraparte"] and doc in DOCS_CON_TIMBRADO:
        return None, "Poné a quién se le pagó (o quién pagó): el nombre del proveedor o cliente"
    return (m, lineas), ""


def _dia_cerrado(conn, caja_id, fecha):
    uc = _ultimo_cierre(conn, caja_id)
    # El día del último cierre sigue abierto para lo nuevo (puede haber otro cierre ese día, por turno)
    return bool(uc and fecha < uc["fecha"]), uc


def _proximo_numero(conn, caja_id):
    r = conn.execute("SELECT COALESCE(MAX(numero),0) AS n FROM caja_movs WHERE caja_id=?", (caja_id,)).fetchone()
    return int(r["n"] or 0) + 1


def _insertar(conn, m, lineas):
    m = dict(m)
    m["numero"] = _proximo_numero(conn, m["caja_id"])
    m["creado_el"] = m["actualizado_el"] = ahora_iso()
    m["creado_por"] = m["actualizado_por"] = _quien()
    cols = list(m.keys())
    cur = conn.execute(f"INSERT INTO caja_movs ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                       [m[c] for c in cols])
    mid = cur.lastrowid
    _guardar_lineas(conn, mid, lineas)
    return mid, m["numero"]


def _guardar_lineas(conn, mid, lineas):
    conn.execute("DELETE FROM caja_mov_det WHERE mov_id=?", (mid,))
    for ln in lineas:
        cols = ["mov_id"] + list(ln.keys())
        conn.execute(f"INSERT INTO caja_mov_det ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})",
                     [mid] + [ln[c] for c in cols[1:]])


def crear_mov(caja_id, d):
    conn = get_connection()
    try:
        caja = conn.execute("SELECT * FROM cajas WHERE id=?", (caja_id,)).fetchone()
        if not caja:
            return {"ok": False, "msg": "No existe esa caja"}
        if not caja["activa"]:
            return {"ok": False, "msg": "Esa caja está desactivada"}
        armado, err = _armar(d, caja)
        if err:
            return {"ok": False, "msg": err}
        m, lineas = armado
        cerrado, uc = _dia_cerrado(conn, caja_id, m["fecha_oper"])
        if cerrado:
            return {"ok": False, "msg": f"La caja ya está cerrada al {uc['fecha'][8:10]}/{uc['fecha'][5:7]}: la fecha no puede ser anterior"}
        avisos = _avisos(conn, m)
        if any(a["nivel"] == "mal" and "ya está cargado" in a["msg"] for a in avisos) and not d.get("confirmar"):
            return {"ok": False, "duplicado": True, "avisos": avisos,
                    "msg": next(a["msg"] for a in avisos if "ya está cargado" in a["msg"])}
        mid, numero = _insertar(conn, m, lineas)
        conn.commit()
    except Exception as e:
        _rollback(conn)
        return {"ok": False, "msg": f"No se pudo guardar: {e}"}
    finally:
        conn.close()
    _auditar("Cargó un movimiento de caja", f"{caja['nombre']} N° {numero}: {TIPOS[m['tipo']]} Gs. {m['total_gs']:,.0f}", mid)
    return {"ok": True, "id": mid, "numero": numero, "msg": f"Movimiento N° {numero} guardado", "mov": ver_mov(mid)}


def editar_mov(mid, d):
    conn = get_connection()
    try:
        act = conn.execute("SELECT * FROM caja_movs WHERE id=?", (mid,)).fetchone()
        if not act:
            return {"ok": False, "msg": "No existe ese movimiento"}
        if act["estado"] != "vigente":
            return {"ok": False, "msg": "Está anulado: no se puede cambiar"}
        if act["cierre_id"]:
            return {"ok": False, "msg": "Ese día ya se cerró: para corregir, administración tiene que reabrir el cierre"}
        if act["transf_id"]:
            return {"ok": False, "msg": "Es una transferencia entre cajas: anulala y cargala de nuevo"}
        caja = conn.execute("SELECT * FROM cajas WHERE id=?", (act["caja_id"],)).fetchone()
        d = dict(d)
        d["tipo"] = act["tipo"]
        armado, err = _armar(d, caja)
        if err:
            return {"ok": False, "msg": err}
        m, lineas = armado
        cerrado, uc = _dia_cerrado(conn, caja["id"], m["fecha_oper"])
        if cerrado:
            return {"ok": False, "msg": f"La caja ya está cerrada al {uc['fecha'][8:10]}/{uc['fecha'][5:7]}: la fecha no puede ser anterior"}
        m["actualizado_el"], m["actualizado_por"] = ahora_iso(), _quien()
        m.pop("caja_id")
        sets = ", ".join(f"{c}=?" for c in m)
        conn.execute(f"UPDATE caja_movs SET {sets} WHERE id=?", list(m.values()) + [mid])
        _guardar_lineas(conn, mid, lineas)
        conn.commit()
    except Exception as e:
        _rollback(conn)
        return {"ok": False, "msg": f"No se pudo guardar: {e}"}
    finally:
        conn.close()
    _auditar("Corrigió un movimiento de caja", f"{caja['nombre']} N° {act['numero']}", mid)
    return {"ok": True, "id": mid, "msg": f"Movimiento N° {act['numero']} corregido", "mov": ver_mov(mid)}


def anular_mov(mid, motivo):
    motivo = _txt(motivo, 300)
    if len(motivo) < 4:
        return {"ok": False, "msg": "Escribí por qué se anula"}
    conn = get_connection()
    try:
        act = conn.execute("SELECT * FROM caja_movs WHERE id=?", (mid,)).fetchone()
        if not act:
            return {"ok": False, "msg": "No existe ese movimiento"}
        if act["estado"] != "vigente":
            return {"ok": False, "msg": "Ya estaba anulado"}
        ids = [mid] + ([act["transf_id"]] if act["transf_id"] else [])
        for i in ids:
            r = conn.execute("SELECT cierre_id FROM caja_movs WHERE id=?", (i,)).fetchone()
            if r and r["cierre_id"]:
                return {"ok": False, "msg": "Ese día ya se cerró: administración tiene que reabrir el cierre para anularlo"}
        for i in ids:
            conn.execute("""UPDATE caja_movs SET estado='anulado', anulado_motivo=?, anulado_el=?, anulado_por=?
                            WHERE id=?""", (motivo, ahora_iso(), _quien(), i))
        conn.commit()
    except Exception as e:
        _rollback(conn)
        return {"ok": False, "msg": f"No se pudo anular: {e}"}
    finally:
        conn.close()
    _auditar("Anuló un movimiento de caja", f"N° {act['numero']}: {motivo}", mid)
    return {"ok": True, "msg": f"Movimiento N° {act['numero']} anulado"}


def transferir(d):
    """Pasar plata de una caja a otra: un egreso en la de origen y un ingreso
    en la de destino, enganchados entre sí."""
    o, de = int(_num(d.get("origen"))), int(_num(d.get("destino")))
    monto = round(_num(d.get("monto")))
    fecha = _fecha(d.get("fecha")) or _hoy()
    nota = _txt_largo(d.get("nota"), 600)
    medio = d.get("medio") if d.get("medio") in MEDIOS else "efectivo"
    if not o or not de or o == de:
        return {"ok": False, "msg": "Elegí la caja de origen y otra de destino"}
    if monto <= 0:
        return {"ok": False, "msg": "Poné el monto"}
    conn = get_connection()
    try:
        co = conn.execute("SELECT * FROM cajas WHERE id=?", (o,)).fetchone()
        cd = conn.execute("SELECT * FROM cajas WHERE id=?", (de,)).fetchone()
        if not co or not cd:
            return {"ok": False, "msg": "No existe esa caja"}
        for c in (co, cd):
            cerrado, uc = _dia_cerrado(conn, c["id"], fecha)
            if cerrado:
                return {"ok": False, "msg": f"{c['nombre']} ya está cerrada al {uc['fecha'][8:10]}/{uc['fecha'][5:7]}: la fecha no puede ser anterior"}
        ids = []
        for caja, tipo, otra in ((co, "egreso", cd), (cd, "ingreso", co)):
            m = {"caja_id": caja["id"], "tipo": tipo, "fecha_emision": fecha, "fecha_oper": fecha,
                 "contraparte": otra["nombre"], "ruc": "", "telefono": "", "direccion": "",
                 "doc_tipo": "interno", "doc_numero": "", "timbrado": "", "timbrado_vence": "",
                 "condicion": "contado", "moneda": "PYG", "cotizacion": 1, "medio": medio, "medio_detalle": "",
                 "empleado": "", "observacion": nota, "exento": monto, "grav5": 0, "grav10": 0, "iva5": 0, "iva10": 0,
                 "total": monto, "total_gs": monto, "imputa_iva": 0, "imputa_ire": 0, "imputa_irp": 0, "no_imputa": 1}
            ln = [{"orden": 0, "concepto_id": 0,
                   "concepto": "Transferencia " + ("a " if tipo == "egreso" else "de ") + otra["nombre"],
                   "detalle": "", "tipo_iva": "exento", "total": monto, **separar_iva(monto, "exento")}]
            ids.append(_insertar(conn, m, ln)[0])
        conn.execute("UPDATE caja_movs SET transf_id=? WHERE id=?", (ids[1], ids[0]))
        conn.execute("UPDATE caja_movs SET transf_id=? WHERE id=?", (ids[0], ids[1]))
        conn.commit()
    except Exception as e:
        _rollback(conn)
        return {"ok": False, "msg": f"No se pudo transferir: {e}"}
    finally:
        conn.close()
    _auditar("Transfirió entre cajas", f"{co['nombre']} → {cd['nombre']}: Gs. {monto:,.0f}", ids[0])
    return {"ok": True, "msg": f"Transferidos Gs. {monto:,.0f}".replace(",", ".") + f" de {co['nombre']} a {cd['nombre']}"}


def contrapartes(q, limite=12):
    """Los proveedores / clientes ya usados (como el «Hist» de Walrus): con su
    RUC, teléfono, dirección y el último timbrado."""
    q = (q or "").strip().lower()
    if len(q) < 2:
        return []
    like = f"%{q}%"
    conn = get_connection()
    try:
        filas = conn.execute("""SELECT contraparte, ruc, telefono, direccion, timbrado, timbrado_vence, doc_tipo,
                                       fecha_oper, total_gs, id
                                FROM caja_movs WHERE estado='vigente' AND (LOWER(contraparte) LIKE ? OR LOWER(ruc) LIKE ?)
                                ORDER BY fecha_oper DESC, id DESC LIMIT 400""", (like, like)).fetchall()
        vistos, out = {}, []
        for f in filas:
            k = (f["ruc"] or f["contraparte"]).lower()
            if k in vistos:
                vistos[k]["veces"] += 1
                continue
            d = {"contraparte": f["contraparte"], "ruc": f["ruc"], "telefono": f["telefono"],
                 "direccion": f["direccion"], "timbrado": f["timbrado"], "timbrado_vence": f["timbrado_vence"],
                 "ultimo": f["fecha_oper"], "ultimo_total": f["total_gs"], "veces": 1}
            # el último concepto que se le cargó (para proponerlo)
            c = conn.execute("""SELECT concepto_id, concepto, tipo_iva FROM caja_mov_det WHERE mov_id=?
                                ORDER BY orden LIMIT 1""", (f["id"],)).fetchone()
            d["concepto"] = dict(c) if c else None
            vistos[k] = d
            out.append(d)
            if len(out) >= limite:
                break
        # también los proveedores cargados en Compras, si existe esa tabla
        if len(out) < limite:
            try:
                for p in conn.execute("""SELECT nombre, COALESCE(ruc,'') AS ruc, COALESCE(telefono,'') AS telefono,
                                                COALESCE(direccion,'') AS direccion FROM repuestos_proveedores
                                         WHERE LOWER(nombre) LIKE ? OR LOWER(COALESCE(ruc,'')) LIKE ?
                                         OR LOWER(COALESCE(fantasia,'')) LIKE ? LIMIT 20""",
                                      (like, like, like)).fetchall():
                    k = (p["ruc"] or p["nombre"]).lower()
                    if k in vistos:
                        continue
                    vistos[k] = 1
                    out.append({"contraparte": p["nombre"], "ruc": p["ruc"], "telefono": p["telefono"],
                                "direccion": p["direccion"], "timbrado": "", "timbrado_vence": "", "ultimo": "",
                                "ultimo_total": 0, "veces": 0, "concepto": None, "de_proveedores": True})
                    if len(out) >= limite:
                        break
            except Exception:
                _rollback(conn)
        return out
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# ARCHIVOS (foto o PDF de la factura)
# ════════════════════════════════════════════════════════════════════════════

def subir_archivo(mid, nombre, tipo, datos_b64):
    if "," in (datos_b64 or "")[:100]:
        cab, datos_b64 = datos_b64.split(",", 1)
        m = re.match(r"data:([^;]+);base64", cab)
        if m and not tipo:
            tipo = m.group(1)
    try:
        crudo = base64.b64decode(datos_b64 or "", validate=False)
    except Exception:
        return {"ok": False, "msg": "El archivo no se pudo leer"}
    if not crudo:
        return {"ok": False, "msg": "El archivo está vacío"}
    if len(crudo) > MAX_ARCHIVO:
        return {"ok": False, "msg": "El archivo pesa más de 6 MB"}
    if not (tipo or "").startswith("image/") and tipo != "application/pdf":
        return {"ok": False, "msg": "Subí una foto o un PDF"}
    conn = get_connection()
    try:
        if not conn.execute("SELECT 1 FROM caja_movs WHERE id=?", (mid,)).fetchone():
            return {"ok": False, "msg": "No existe ese movimiento"}
        n = conn.execute("SELECT COUNT(*) AS n FROM caja_mov_archivos WHERE mov_id=?", (mid,)).fetchone()["n"]
        if n >= 8:
            return {"ok": False, "msg": "Ya tiene 8 archivos"}
        cur = conn.execute("""INSERT INTO caja_mov_archivos (mov_id, nombre, tipo, tamano, datos, subido_el, subido_por)
                              VALUES (?,?,?,?,?,?,?)""",
                           (mid, _txt(nombre, 120) or "factura", tipo, len(crudo),
                            base64.b64encode(crudo).decode(), ahora_iso(), _quien()))
        aid = cur.lastrowid
        conn.commit()
        return {"ok": True, "id": aid, "msg": "Archivo guardado"}
    except Exception as e:
        _rollback(conn)
        return {"ok": False, "msg": f"No se pudo guardar el archivo: {e}"}
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# CIERRE DIARIO Y ARQUEO
# ════════════════════════════════════════════════════════════════════════════

def previa_cierre(caja_id, fecha):
    """Lo que entraría en el cierre hasta esa fecha (sin guardar nada)."""
    fecha = _fecha(fecha) or _hoy()
    conn = get_connection()
    try:
        caja = conn.execute("SELECT * FROM cajas WHERE id=?", (caja_id,)).fetchone()
        if not caja:
            return None
        uc = _ultimo_cierre(conn, caja_id)
        ant = float(uc["saldo_final"]) if uc else float(caja["saldo_inicial"] or 0)
        ant_ef = float(uc["efectivo_final"]) if uc else float(caja["efectivo_inicial"] or 0)
        movs = [dict(r) for r in conn.execute(f"""SELECT {COLS_LISTA} FROM caja_movs m
                    WHERE m.caja_id=? AND m.estado='vigente' AND COALESCE(m.cierre_id,0)=0 AND m.fecha_oper<=?
                    ORDER BY m.fecha_oper, m.numero""", (caja_id, fecha)).fetchall()]
        conc = _conceptos_de(conn, [m["id"] for m in movs])
        arch = _archivos_cuenta(conn, [m["id"] for m in movs])
        ing = egr = ef = 0.0
        por_medio = {}
        for m in movs:
            m["conceptos"] = conc.get(m["id"], [])
            m["archivos"] = arch.get(m["id"], 0)
            t = float(m["total_gs"] or 0)
            if m["tipo"] == "ingreso":
                ing += t
            else:
                egr += t
            pm = por_medio.setdefault(m["medio"], {"medio": MEDIOS.get(m["medio"], m["medio"]), "ingresos": 0, "egresos": 0})
            pm["ingresos" if m["tipo"] == "ingreso" else "egresos"] += t
            if m["medio"] == "efectivo":
                ef += _signo(m["tipo"]) * t
        return {
            "caja": dict(caja), "fecha": fecha, "desde": (uc["fecha"] if uc else ""),
            "saldo_anterior": ant, "ingresos": ing, "egresos": egr, "saldo_final": ant + ing - egr,
            "efectivo_anterior": ant_ef, "efectivo_final": ant_ef + ef,
            "movs": movs, "por_medio": list(por_medio.values()),
            "sin_foto": sum(1 for m in movs if m["doc_tipo"] != "interno" and not m["archivos"]),
            "ya_cerrado": bool(uc and fecha < uc["fecha"]),
            "ultimo_cierre": uc["fecha"] if uc else "",
        }
    finally:
        conn.close()


def cerrar(caja_id, d):
    fecha = _fecha(d.get("fecha")) or _hoy()
    if fecha > _hoy():
        return {"ok": False, "msg": "No se puede cerrar un día que todavía no llegó"}
    p = previa_cierre(caja_id, fecha)
    if p is None:
        return {"ok": False, "msg": "No existe esa caja"}
    if p["ya_cerrado"]:
        return {"ok": False, "msg": "Ya hay un cierre posterior a esa fecha"}
    arqueo = d.get("arqueo") or {}
    billetes = {}
    for b in BILLETES:
        n = int(_num((arqueo.get("billetes") or {}).get(str(b))))
        if n > 0:
            billetes[str(b)] = n
    otros = round(_num(arqueo.get("otros")))
    contado = sum(int(k) * v for k, v in billetes.items()) + otros
    if "contado" in d and not billetes and not otros:
        contado = round(_num(d.get("contado")))
    dif = contado - round(p["efectivo_final"])
    nota = _txt_largo(d.get("nota"), 1500)
    if dif and len(nota) < 4:
        return {"ok": False, "msg": "Hay diferencia en el arqueo: escribí en la nota qué pasó", "diferencia": dif}
    conn = get_connection()
    try:
        cur = conn.execute("""INSERT INTO caja_cierres (caja_id, fecha, movimientos, saldo_anterior, ingresos, egresos,
                              saldo_final, efectivo_anterior, efectivo_final, contado, diferencia, arqueo, nota,
                              cerrado_el, cerrado_por) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                           (caja_id, fecha, len(p["movs"]), p["saldo_anterior"], p["ingresos"], p["egresos"],
                            p["saldo_final"], p["efectivo_anterior"], p["efectivo_final"], contado, dif,
                            json.dumps({"billetes": billetes, "otros": otros}), nota, ahora_iso(), _quien()))
        cid = cur.lastrowid
        if p["movs"]:
            ids = [m["id"] for m in p["movs"]]
            conn.execute(f"UPDATE caja_movs SET cierre_id=? WHERE id IN ({','.join('?' * len(ids))})", [cid] + ids)
        conn.commit()
    except Exception as e:
        _rollback(conn)
        return {"ok": False, "msg": f"No se pudo cerrar: {e}"}
    finally:
        conn.close()
    _auditar("Cerró la caja", f"{p['caja']['nombre']} al {fecha}: saldo Gs. {p['saldo_final']:,.0f}, diferencia {dif:,.0f}", cid,
             ref=f"caja_cierre:{cid}")
    return {"ok": True, "id": cid, "diferencia": dif,
            "msg": "Caja cerrada" + ("" if not dif else f" con diferencia de Gs. {abs(dif):,.0f}".replace(",", ".")
                                     + (" de más" if dif > 0 else " de menos"))}


def reabrir(cid):
    conn = get_connection()
    try:
        c = conn.execute("SELECT * FROM caja_cierres WHERE id=?", (cid,)).fetchone()
        if not c:
            return {"ok": False, "msg": "No existe ese cierre"}
        uc = _ultimo_cierre(conn, c["caja_id"])
        if uc["id"] != cid:
            return {"ok": False, "msg": "Solo se puede reabrir el último cierre"}
        conn.execute("UPDATE caja_movs SET cierre_id=0 WHERE cierre_id=?", (cid,))
        conn.execute("DELETE FROM caja_cierres WHERE id=?", (cid,))
        conn.commit()
    except Exception as e:
        _rollback(conn)
        return {"ok": False, "msg": f"No se pudo reabrir: {e}"}
    finally:
        conn.close()
    _auditar("Reabrió un cierre de caja", f"cierre del {c['fecha']}", cid)
    return {"ok": True, "msg": f"Se reabrió el cierre del {c['fecha'][8:10]}/{c['fecha'][5:7]}"}


def listar_cierres(caja_id, limite=60):
    conn = get_connection()
    try:
        return [dict(r) for r in conn.execute("""SELECT * FROM caja_cierres WHERE caja_id=?
                    ORDER BY fecha DESC, id DESC LIMIT ?""", (caja_id, limite)).fetchall()]
    finally:
        conn.close()


def datos_cierre(cid):
    conn = get_connection()
    try:
        c = conn.execute("SELECT * FROM caja_cierres WHERE id=?", (cid,)).fetchone()
        if not c:
            return None
        d = dict(c)
        d["caja"] = dict(conn.execute("SELECT * FROM cajas WHERE id=?", (c["caja_id"],)).fetchone())
        d["arqueo"] = json.loads(c["arqueo"] or "{}")
        movs = [dict(r) for r in conn.execute(f"""SELECT {COLS_LISTA} FROM caja_movs m WHERE m.cierre_id=?
                    ORDER BY m.fecha_oper, m.numero""", (cid,)).fetchall()]
        conc = _conceptos_de(conn, [m["id"] for m in movs])
        for m in movs:
            m["conceptos"] = conc.get(m["id"], [])
        d["movs"] = movs
        ant = conn.execute("""SELECT fecha FROM caja_cierres WHERE caja_id=? AND (fecha<? OR (fecha=? AND id<?))
                              ORDER BY fecha DESC, id DESC LIMIT 1""", (c["caja_id"], c["fecha"], c["fecha"], cid)).fetchone()
        d["desde"] = ant["fecha"] if ant else ""
        return d
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# LIBRO IVA (para el contador) Y EXTRACTO
# ════════════════════════════════════════════════════════════════════════════

def _mes_rango(mes):
    try:
        a, m = int(mes[:4]), int(mes[5:7])
        ini = date(a, m, 1)
    except Exception:
        h = date.fromisoformat(_hoy())
        ini = h.replace(day=1)
    fin = (ini.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return ini.isoformat(), fin.isoformat()


def libro_iva(mes, libro="compras", caja_id=None):
    """Compras = egresos con comprobante; ventas = ingresos con comprobante.
    Por fecha de emisión de la factura, como lo pide la SET."""
    ini, fin = _mes_rango(mes)
    tipo = "egreso" if libro == "compras" else "ingreso"
    conn = get_connection()
    try:
        sql = """SELECT m.*, c.nombre AS caja FROM caja_movs m JOIN cajas c ON c.id=m.caja_id
                 WHERE m.estado='vigente' AND m.tipo=? AND m.doc_tipo<>'interno' AND COALESCE(m.transf_id,0)=0
                 AND m.fecha_emision BETWEEN ? AND ?"""
        p = [tipo, ini, fin]
        if caja_id:
            sql += " AND m.caja_id=?"
            p.append(caja_id)
        sql += " ORDER BY m.fecha_emision, m.doc_numero"
        filas = [dict(r) for r in conn.execute(sql, p).fetchall()]
        conc = _conceptos_de(conn, [f["id"] for f in filas])
        for f in filas:
            f["conceptos"] = conc.get(f["id"], [])
        return {"desde": ini, "hasta": fin, "libro": libro, "filas": filas}
    finally:
        conn.close()


def libro_xlsx(d):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    wb = Workbook()
    ws = wb.active
    ws.title = "Libro " + d["libro"]
    navy = "1E3A5F"
    tit = f"Libro IVA {d['libro']} — {d['desde'][5:7]}/{d['desde'][:4]}"
    ws["A1"] = "La Santaniana S.A."
    ws["A1"].font = Font(bold=True, size=12, color=navy)
    ws["A2"] = tit
    ws["A2"].font = Font(bold=True, size=14, color=navy)
    ws["A3"] = f"Por fecha de la factura, del {d['desde'][8:10]}/{d['desde'][5:7]} al {d['hasta'][8:10]}/{d['hasta'][5:7]}/{d['hasta'][:4]}. Montos en guaraníes."
    ws["A3"].font = Font(italic=True, color="666666")
    cab = ["Fecha", "Tipo comprobante", "Número", "Timbrado", "RUC", "Razón social", "Concepto",
           "Exento", "Gravado 5 %", "IVA 5 %", "Gravado 10 %", "IVA 10 %", "Total",
           "Moneda", "Cotización", "Condición", "Imputa IVA", "Imputa IRE", "Imputa IRP-RSP", "No imputa",
           "Caja", "Mov. N°"]
    fila = 5
    borde = Border(bottom=Side(style="thin", color="CCCCCC"))
    for i, t in enumerate(cab, 1):
        c = ws.cell(row=fila, column=i, value=t)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=navy)
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[fila].height = 30
    sumas = [0.0] * 6
    for f in d["filas"]:
        fila += 1
        cot = float(f["cotizacion"] or 1)
        montos = [round(float(f[k] or 0) * cot) for k in ("exento", "grav5", "iva5", "grav10", "iva10", "total")]
        for i, v in enumerate(montos):
            sumas[i] += v
        vals = [date.fromisoformat(f["fecha_emision"]) if f["fecha_emision"] else None,
                DOCS.get(f["doc_tipo"], f["doc_tipo"]), f["doc_numero"], f["timbrado"], f["ruc"], f["contraparte"],
                ", ".join(f["conceptos"])] + montos + [
                f["moneda"], cot, CONDICIONES.get(f["condicion"], f["condicion"]),
                "Sí" if f["imputa_iva"] else "No", "Sí" if f["imputa_ire"] else "No",
                "Sí" if f["imputa_irp"] else "No", "Sí" if f["no_imputa"] else "No", f["caja"], f["numero"]]
        for i, v in enumerate(vals, 1):
            c = ws.cell(row=fila, column=i, value=v)
            c.border = borde
            if i == 1 and v:
                c.number_format = "DD/MM/YYYY"
            if 8 <= i <= 13:
                c.number_format = "#,##0"
    fila += 1
    ws.cell(row=fila, column=7, value=f"TOTAL ({len(d['filas'])} comprobantes)").font = Font(bold=True)
    for i, v in enumerate(sumas):
        c = ws.cell(row=fila, column=8 + i, value=v)
        c.font = Font(bold=True)
        c.number_format = "#,##0"
        c.fill = PatternFill("solid", fgColor="E8F1FA")
    anchos = [11, 16, 17, 11, 13, 32, 32, 13, 13, 12, 14, 12, 14, 8, 10, 10, 9, 9, 10, 9, 20, 8]
    for i, w in enumerate(anchos, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A6"
    ws.auto_filter.ref = f"A5:{get_column_letter(len(cab))}{max(5, fila - 1)}"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def extracto_xlsx(caja_id, desde, hasta):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    conn = get_connection()
    try:
        caja = conn.execute("SELECT * FROM cajas WHERE id=?", (caja_id,)).fetchone()
        if not caja:
            return None, ""
        # saldo al empezar el rango: inicial + todo lo vigente antes
        r = conn.execute("""SELECT COALESCE(SUM(CASE WHEN tipo='ingreso' THEN total_gs ELSE -total_gs END),0) AS s
                            FROM caja_movs WHERE caja_id=? AND estado='vigente' AND fecha_oper<?""",
                         (caja_id, desde)).fetchone()
        saldo = float(caja["saldo_inicial"] or 0) + float(r["s"] or 0)
        movs = [dict(x) for x in conn.execute(f"""SELECT {COLS_LISTA} FROM caja_movs m WHERE m.caja_id=?
                    AND m.fecha_oper BETWEEN ? AND ? ORDER BY m.fecha_oper, m.numero""", (caja_id, desde, hasta)).fetchall()]
        conc = _conceptos_de(conn, [m["id"] for m in movs])
    finally:
        conn.close()
    wb = Workbook()
    ws = wb.active
    ws.title = "Extracto"
    navy = "1E3A5F"
    ws["A1"] = f"{caja['nombre']} — extracto"
    ws["A1"].font = Font(bold=True, size=14, color=navy)
    ws["A2"] = f"Del {desde[8:10]}/{desde[5:7]}/{desde[:4]} al {hasta[8:10]}/{hasta[5:7]}/{hasta[:4]} · saldo al empezar: {saldo:,.0f}".replace(",", ".")
    cab = ["Fecha", "N°", "Tipo", "Proveedor / cliente", "RUC", "Comprobante", "Concepto", "Medio",
           "Ingreso", "Egreso", "Saldo", "Estado", "Cargó"]
    for i, t in enumerate(cab, 1):
        c = ws.cell(row=4, column=i, value=t)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=navy)
        c.alignment = Alignment(horizontal="center")
    fila = 4
    ti = te = 0.0
    for m in movs:
        fila += 1
        t = float(m["total_gs"] or 0)
        vig = m["estado"] == "vigente"
        if vig:
            saldo += _signo(m["tipo"]) * t
            if m["tipo"] == "ingreso":
                ti += t
            else:
                te += t
        vals = [date.fromisoformat(m["fecha_oper"]), m["numero"], "Ingreso" if m["tipo"] == "ingreso" else "Egreso",
                m["contraparte"], m["ruc"], (DOCS.get(m["doc_tipo"], "") + " " + (m["doc_numero"] or "")).strip(),
                ", ".join(conc.get(m["id"], [])), MEDIOS.get(m["medio"], m["medio"]),
                t if m["tipo"] == "ingreso" else None, t if m["tipo"] == "egreso" else None,
                saldo if vig else None, "Vigente" if vig else "ANULADO", m["creado_por"]]
        for i, v in enumerate(vals, 1):
            c = ws.cell(row=fila, column=i, value=v)
            if i == 1:
                c.number_format = "DD/MM/YYYY"
            if 9 <= i <= 11:
                c.number_format = "#,##0"
            if not vig:
                c.font = Font(color="999999", strike=(i in (9, 10)))
    fila += 1
    ws.cell(row=fila, column=8, value="TOTAL").font = Font(bold=True)
    for col, v in ((9, ti), (10, te), (11, saldo)):
        c = ws.cell(row=fila, column=col, value=v)
        c.font = Font(bold=True)
        c.number_format = "#,##0"
    for i, w in enumerate([11, 6, 9, 30, 13, 26, 30, 13, 13, 13, 14, 10, 16], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A5"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf, caja["nombre"]


# ════════════════════════════════════════════════════════════════════════════
# AUDITORÍA Y PERMISOS
# ════════════════════════════════════════════════════════════════════════════

def _auditar(accion, detalle, mid, ref=None):
    try:
        from database import registrar_auditoria
        registrar_auditoria(usuario=_quien(), rol=session.get("rol") or "", accion=accion,
                            categoria="cajas", detalle=detalle, referencia=ref or f"caja_mov:{mid}")
    except Exception:
        pass


def _puede(escribir=False):
    """admin y compras siempre; taller si tiene la sección (o acceso completo);
    auditor solo mira."""
    if "usuario_id" not in session:
        return False
    rol = session.get("rol")
    if rol in ("admin", "compras"):
        return True
    if rol == "auditor":
        return not escribir
    if rol == "taller":
        try:
            from database import secciones_de_usuario
            secs = secciones_de_usuario(session.get("usuario_id"))
            return not secs or "cajas" in secs
        except Exception:
            return False
    return False


def _es_admin():
    return session.get("rol") == "admin"


def _no(msg="Sin permiso", code=403):
    return jsonify({"ok": False, "msg": msg, "error": msg}), code


# ════════════════════════════════════════════════════════════════════════════
# RUTAS
# ════════════════════════════════════════════════════════════════════════════

@bp_cajas.route("/api/cajas", methods=["GET"])
def api_cajas():
    if not _puede():
        return _no()
    conn = get_connection()
    try:
        conceptos = [dict(r) for r in conn.execute(
            "SELECT * FROM caja_conceptos ORDER BY tipo, nombre").fetchall()]
    finally:
        conn.close()
    return jsonify({"ok": True, "cajas": listar_cajas(request.args.get("todas") == "1"), "conceptos": conceptos,
                    "tipos_iva": TIPOS_IVA, "docs": DOCS, "docs_timbrado": sorted(DOCS_CON_TIMBRADO),
                    "medios": MEDIOS, "monedas": MONEDAS, "condiciones": CONDICIONES, "billetes": BILLETES,
                    "hoy": _hoy(), "puede": _puede(True), "admin": _es_admin()})


@bp_cajas.route("/api/cajas", methods=["POST"])
def api_caja_nueva():
    if not _es_admin():
        return _no("Solo administración crea cajas")
    d = request.get_json(silent=True) or {}
    nombre = _txt(d.get("nombre"), 80)
    if not nombre:
        return _no("Poné el nombre de la caja", 400)
    conn = get_connection()
    try:
        orden = conn.execute("SELECT COALESCE(MAX(orden),0)+1 AS n FROM cajas").fetchone()["n"]
        conn.execute("""INSERT INTO cajas (nombre, sucursal, responsable, moneda, saldo_inicial, efectivo_inicial,
                        inicio, orden, creado_el, creado_por) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                     (nombre, _txt(d.get("sucursal"), 80) or "Casa Central", _txt(d.get("responsable"), 80), "PYG",
                      round(_num(d.get("saldo_inicial"))), round(_num(d.get("efectivo_inicial", d.get("saldo_inicial")))),
                      _fecha(d.get("inicio")) or _hoy(), orden, ahora_iso(), _quien()))
        conn.commit()
    except Exception as e:
        _rollback(conn)
        return _no(f"No se pudo crear: {e}", 400)
    finally:
        conn.close()
    return jsonify({"ok": True, "msg": f"Caja «{nombre}» creada"})


@bp_cajas.route("/api/cajas/<int:cid>", methods=["PATCH"])
def api_caja_editar(cid):
    if not _es_admin():
        return _no("Solo administración cambia las cajas")
    d = request.get_json(silent=True) or {}
    campos, vals = [], []
    if "nombre" in d:
        if not _txt(d["nombre"], 80):
            return _no("Poné el nombre", 400)
        campos.append("nombre=?"); vals.append(_txt(d["nombre"], 80))
    for k in ("sucursal", "responsable"):
        if k in d:
            campos.append(f"{k}=?"); vals.append(_txt(d[k], 80))
    if "activa" in d:
        campos.append("activa=?"); vals.append(1 if d["activa"] else 0)
    conn = get_connection()
    try:
        for k in ("saldo_inicial", "efectivo_inicial"):
            if k in d:
                if conn.execute("SELECT 1 FROM caja_cierres WHERE caja_id=? LIMIT 1", (cid,)).fetchone():
                    return _no("La caja ya tiene cierres: el saldo inicial no se puede cambiar", 400)
                campos.append(f"{k}=?"); vals.append(round(_num(d[k])))
        if not campos:
            return jsonify({"ok": True})
        conn.execute(f"UPDATE cajas SET {', '.join(campos)} WHERE id=?", vals + [cid])
        conn.commit()
    except Exception as e:
        _rollback(conn)
        return _no(f"No se pudo guardar: {e}", 400)
    finally:
        conn.close()
    return jsonify({"ok": True, "msg": "Caja actualizada"})


@bp_cajas.route("/api/cajas/conceptos", methods=["POST"])
def api_concepto_nuevo():
    if not _puede(True):
        return _no()
    d = request.get_json(silent=True) or {}
    nombre = _txt(d.get("nombre"), 100)
    if not nombre:
        return _no("Poné el nombre del concepto", 400)
    tipo = d.get("tipo") if d.get("tipo") in TIPOS else "egreso"
    iva = str(d.get("iva") or "10") if str(d.get("iva") or "10") in TIPOS_IVA else "10"
    conn = get_connection()
    try:
        ya = conn.execute("SELECT id FROM caja_conceptos WHERE LOWER(nombre)=? AND tipo=?", (nombre.lower(), tipo)).fetchone()
        if ya:
            return jsonify({"ok": True, "id": ya["id"], "msg": "Ya existía"})
        cur = conn.execute("INSERT INTO caja_conceptos (codigo, nombre, tipo, iva, cuenta) VALUES (?,?,?,?,?)",
                           (_txt(d.get("codigo"), 10).upper(), nombre, tipo, iva, _txt(d.get("cuenta"), 40)))
        nid = cur.lastrowid
        conn.commit()
    except Exception as e:
        _rollback(conn)
        return _no(f"No se pudo crear: {e}", 400)
    finally:
        conn.close()
    return jsonify({"ok": True, "id": nid, "msg": f"Concepto «{nombre}» creado"})


@bp_cajas.route("/api/cajas/conceptos/<int:kid>", methods=["PATCH"])
def api_concepto_editar(kid):
    if not _es_admin():
        return _no("Solo administración cambia los conceptos")
    d = request.get_json(silent=True) or {}
    campos, vals = [], []
    if "nombre" in d and _txt(d["nombre"], 100):
        campos.append("nombre=?"); vals.append(_txt(d["nombre"], 100))
    if "iva" in d and str(d["iva"]) in TIPOS_IVA:
        campos.append("iva=?"); vals.append(str(d["iva"]))
    if "cuenta" in d:
        campos.append("cuenta=?"); vals.append(_txt(d["cuenta"], 40))
    if "codigo" in d:
        campos.append("codigo=?"); vals.append(_txt(d["codigo"], 10).upper())
    if "activo" in d:
        campos.append("activo=?"); vals.append(1 if d["activo"] else 0)
    if not campos:
        return jsonify({"ok": True})
    conn = get_connection()
    try:
        conn.execute(f"UPDATE caja_conceptos SET {', '.join(campos)} WHERE id=?", vals + [kid])
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "msg": "Concepto actualizado"})


@bp_cajas.route("/api/cajas/<int:cid>/movs", methods=["GET"])
def api_movs(cid):
    if not _puede():
        return _no()
    a = request.args
    return jsonify({"ok": True, **listar_movs(cid, _fecha(a.get("desde")), _fecha(a.get("hasta")), a.get("tipo", ""),
                                              a.get("q", ""), a.get("estado", ""))})


@bp_cajas.route("/api/cajas/<int:cid>/movs", methods=["POST"])
def api_mov_nuevo(cid):
    if not _puede(True):
        return _no()
    r = crear_mov(cid, request.get_json(silent=True) or {})
    return jsonify(r), (200 if r.get("ok") else (409 if r.get("duplicado") else 400))


@bp_cajas.route("/api/cajas/movs/<int:mid>", methods=["GET"])
def api_mov_ver(mid):
    if not _puede():
        return _no()
    m = ver_mov(mid)
    if not m:
        return _no("No existe ese movimiento", 404)
    return jsonify({"ok": True, "mov": m})


@bp_cajas.route("/api/cajas/movs/<int:mid>", methods=["PUT"])
def api_mov_editar(mid):
    if not _puede(True):
        return _no()
    r = editar_mov(mid, request.get_json(silent=True) or {})
    return jsonify(r), (200 if r.get("ok") else 400)


@bp_cajas.route("/api/cajas/movs/<int:mid>/anular", methods=["POST"])
def api_mov_anular(mid):
    if not _puede(True):
        return _no()
    r = anular_mov(mid, (request.get_json(silent=True) or {}).get("motivo"))
    return jsonify(r), (200 if r.get("ok") else 400)


@bp_cajas.route("/api/cajas/movs/<int:mid>/archivos", methods=["POST"])
def api_mov_archivo(mid):
    if not _puede(True):
        return _no()
    d = request.get_json(silent=True) or {}
    r = subir_archivo(mid, d.get("nombre"), d.get("tipo"), d.get("datos"))
    return jsonify(r), (200 if r.get("ok") else 400)


@bp_cajas.route("/api/cajas/archivos/<int:aid>", methods=["GET"])
def api_archivo_ver(aid):
    if not _puede():
        return _no()
    conn = get_connection()
    try:
        r = conn.execute("SELECT nombre, tipo, datos FROM caja_mov_archivos WHERE id=?", (aid,)).fetchone()
    finally:
        conn.close()
    if not r:
        return _no("No existe", 404)
    return Response(base64.b64decode(r["datos"]), mimetype=r["tipo"] or "application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{r["nombre"]}"',
                             "Cache-Control": "private, max-age=3600"})


@bp_cajas.route("/api/cajas/archivos/<int:aid>", methods=["DELETE"])
def api_archivo_borrar(aid):
    if not _puede(True):
        return _no()
    conn = get_connection()
    try:
        r = conn.execute("""SELECT a.mov_id, m.cierre_id FROM caja_mov_archivos a JOIN caja_movs m ON m.id=a.mov_id
                            WHERE a.id=?""", (aid,)).fetchone()
        if not r:
            return _no("No existe", 404)
        if r["cierre_id"] and not _es_admin():
            return _no("Ese día ya se cerró", 400)
        conn.execute("DELETE FROM caja_mov_archivos WHERE id=?", (aid,))
        conn.commit()
    finally:
        conn.close()
    return jsonify({"ok": True, "msg": "Archivo quitado"})


@bp_cajas.route("/api/cajas/transferir", methods=["POST"])
def api_transferir():
    if not _puede(True):
        return _no()
    r = transferir(request.get_json(silent=True) or {})
    return jsonify(r), (200 if r.get("ok") else 400)


@bp_cajas.route("/api/cajas/contrapartes", methods=["GET"])
def api_contrapartes():
    if not _puede():
        return _no()
    return jsonify({"ok": True, "lista": contrapartes(request.args.get("q", ""))})


@bp_cajas.route("/api/cajas/ruc", methods=["GET"])
def api_ruc():
    if not _puede():
        return _no()
    t, ok, msg = ruc_limpio(request.args.get("ruc"))
    return jsonify({"ok": True, "ruc": t, "valido": ok, "msg": msg})


@bp_cajas.route("/api/cajas/avisos", methods=["POST"])
def api_avisos():
    """Los avisos mientras se escribe (RUC, timbrado, repetido)."""
    if not _puede():
        return _no()
    d = request.get_json(silent=True) or {}
    m = {"ruc": ruc_limpio(d.get("ruc"))[0], "doc_tipo": d.get("doc_tipo") or "factura",
         "doc_numero": doc_numero_limpio(d.get("doc_numero")), "timbrado": re.sub(r"\D", "", str(d.get("timbrado") or "")),
         "timbrado_vence": _fecha(d.get("timbrado_vence")), "fecha_emision": _fecha(d.get("fecha_emision")),
         "fecha_oper": _fecha(d.get("fecha_oper")), "tipo": d.get("tipo") or "egreso", "id": int(_num(d.get("id")))}
    conn = get_connection()
    try:
        return jsonify({"ok": True, "avisos": _avisos(conn, m), "doc_numero": m["doc_numero"], "ruc": m["ruc"]})
    finally:
        conn.close()


@bp_cajas.route("/api/cajas/<int:cid>/cierre", methods=["GET"])
def api_cierre_previa(cid):
    if not _puede():
        return _no()
    p = previa_cierre(cid, request.args.get("fecha"))
    if p is None:
        return _no("No existe esa caja", 404)
    return jsonify({"ok": True, **p})


@bp_cajas.route("/api/cajas/<int:cid>/cierre", methods=["POST"])
def api_cierre(cid):
    if not _puede(True):
        return _no()
    r = cerrar(cid, request.get_json(silent=True) or {})
    return jsonify(r), (200 if r.get("ok") else 400)


@bp_cajas.route("/api/cajas/<int:cid>/cierres", methods=["GET"])
def api_cierres(cid):
    if not _puede():
        return _no()
    return jsonify({"ok": True, "cierres": listar_cierres(cid)})


@bp_cajas.route("/api/cajas/cierres/<int:cierre_id>/reabrir", methods=["POST"])
def api_reabrir(cierre_id):
    if not _es_admin():
        return _no("Solo administración puede reabrir un cierre")
    r = reabrir(cierre_id)
    return jsonify(r), (200 if r.get("ok") else 400)


@bp_cajas.route("/api/cajas/cierres/<int:cierre_id>/pdf", methods=["GET"])
def api_cierre_pdf(cierre_id):
    if not _puede():
        return _no()
    d = datos_cierre(cierre_id)
    if not d:
        return _no("No existe ese cierre", 404)
    import cajas_pdf
    buf = cajas_pdf.pdf_cierre(d)
    return send_file(buf, mimetype="application/pdf", as_attachment=False,
                     download_name=f"Cierre {d['caja']['nombre']} {d['fecha']}.pdf")


@bp_cajas.route("/api/cajas/movs/<int:mid>/pdf", methods=["GET"])
def api_mov_pdf(mid):
    if not _puede():
        return _no()
    m = ver_mov(mid)
    if not m:
        return _no("No existe ese movimiento", 404)
    import cajas_pdf
    buf = cajas_pdf.pdf_comprobante(m)
    return send_file(buf, mimetype="application/pdf", as_attachment=False,
                     download_name=f"Movimiento {m['numero']} {m['caja_nombre']}.pdf")


@bp_cajas.route("/api/cajas/libro.xlsx", methods=["GET"])
def api_libro():
    if not _puede():
        return _no()
    a = request.args
    libro = "ventas" if a.get("libro") == "ventas" else "compras"
    d = libro_iva(a.get("mes") or _hoy()[:7], libro, int(_num(a.get("caja"))) or None)
    buf = libro_xlsx(d)
    return send_file(buf, as_attachment=True,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     download_name=f"Libro IVA {libro} {d['desde'][:7]}.xlsx")


@bp_cajas.route("/api/cajas/libro", methods=["GET"])
def api_libro_json():
    if not _puede():
        return _no()
    a = request.args
    libro = "ventas" if a.get("libro") == "ventas" else "compras"
    d = libro_iva(a.get("mes") or _hoy()[:7], libro, int(_num(a.get("caja"))) or None)
    tot = {k: 0.0 for k in ("exento", "grav5", "iva5", "grav10", "iva10", "total")}
    for f in d["filas"]:
        cot = float(f["cotizacion"] or 1)
        for k in tot:
            tot[k] += round(float(f[k] or 0) * cot)
    return jsonify({"ok": True, **d, "totales": tot})


@bp_cajas.route("/api/cajas/<int:cid>/extracto.xlsx", methods=["GET"])
def api_extracto(cid):
    if not _puede():
        return _no()
    a = request.args
    hasta = _fecha(a.get("hasta")) or _hoy()
    desde = _fecha(a.get("desde")) or (date.fromisoformat(hasta).replace(day=1)).isoformat()
    buf, nombre = extracto_xlsx(cid, desde, hasta)
    if buf is None:
        return _no("No existe esa caja", 404)
    return send_file(buf, as_attachment=True,
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                     download_name=f"Extracto {nombre} {desde} a {hasta}.xlsx")
