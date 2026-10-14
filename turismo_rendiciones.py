"""
turismo_rendiciones.py — Rendiciones de los viajes de turismo (La Santaniana)

Antes de un viaje se le da al chofer un anticipo; a la vuelta entrega los
comprobantes y la oficina los carga acá. La cuenta es simple:

    anticipos − gastos = saldo
      saldo > 0  → el chofer devuelve lo que sobró
      saldo < 0  → la empresa le paga lo que puso de su bolsillo

Cómo está pensado:

  - Cada rendición es un VIAJE. Se arma a partir de la Agenda de servicios
    (la ida y la vuelta que comparten el número de orden se juntan solas) o a
    mano, si el viaje no estaba agendado.
  - Los gastos van por categoría: combustible (acá y en el exterior), peajes,
    comida / viáticos, hotel, estacionamiento, lavado, DINATRAN, carta azul y
    otros. Sin foto: la oficina carga lo que dice el comprobante.
  - En los viajes al exterior se gasta en otra moneda (dólares, pesos
    argentinos, reales): cada gasto guarda su moneda y la cotización, y todo
    se suma en guaraníes. La cotización que se usó la última vez se ofrece
    sola.
  - Pasos: se carga (abierta) → se presenta para aprobar → la administración
    la aprueba (o la devuelve con un motivo) → se registra que el chofer
    devolvió o que se le pagó (saldada). Si cierra justo, queda saldada al
    aprobarla.
  - Si el viaje tenía un presupuesto de Turismo, se compara lo presupuestado
    con lo que realmente se gastó, rubro por rubro. Sirve para presupuestar
    mejor el próximo.

Enganche en app.py:
    from turismo_rendiciones import bp_rendiciones, init_rendiciones
    init_rendiciones()
    app.register_blueprint(bp_rendiciones)
"""

import io
import json
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, session, send_file
from db_compat import get_connection, USE_POSTGRES

bp_rendiciones = Blueprint("turismo_rendiciones", __name__)

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"

# (clave, nombre, ícono). El orden es el de la pantalla: primero lo de todos los
# viajes, después lo de frontera y lo de ruta. Son los renglones de la planilla
# de rendición de turismo, más lo que aparecía escrito a mano.
CATEGORIAS = [
    ("combustible", "Combustible", "gas-station"),
    ("combustible_ext", "Combustible en el exterior", "world"),
    ("peajes", "Peajes", "road"),
    ("peajes_ext", "Peajes en el exterior", "road-sign"),
    ("salario", "Salario + viático", "user-dollar"),
    ("comida", "Comida / viáticos", "tools-kitchen-2"),
    ("hotel", "Hotel / estadía", "bed"),
    ("estacionamiento", "Estacionamiento", "parking"),
    ("lavado", "Lavado", "droplets"),
    ("dinatran", "DINATRAN", "building-bank"),
    ("carta_azul", "Carta azul", "file-certificate"),
    ("aduana", "Aduana", "building-arch"),
    ("migraciones", "Migraciones", "id-badge-2"),
    ("senasa", "SENASA / sanidad", "shield-check"),
    ("desinfeccion", "Desinfección", "spray"),
    ("gomeria", "Gomería", "tire"),
    ("mantenimiento", "Mantenimiento en ruta", "tool"),
    ("limpieza", "Limpieza / insumos", "bucket"),
    ("taxi", "Taxi / traslados", "car"),
    ("otros", "Otros", "dots"),
]
CAT = {k: {"clave": k, "nombre": n, "icono": i} for k, n, i in CATEGORIAS}
COMBUSTIBLES = ("combustible", "combustible_ext")

MONEDAS = {"GS": "Gs.", "USD": "US$", "ARS": "AR$", "BRL": "R$"}

ESTADOS = {
    "abierta": "Cargando",
    "presentada": "Para aprobar",
    "aprobada": "Aprobada · falta saldar",
    "saldada": "Saldada",
}

# Cómo se comparan los gastos con los rubros del presupuesto de Turismo
GRUPOS_PRESUPUESTO = [
    ("combustible", "Combustible", ("combustible", "combustible_ext"), ("costo_combustible",)),
    ("choferes", "Choferes (salario + viático)", ("salario",), ("costo_chofer",)),
    ("peajes", "Peajes", ("peajes", "peajes_ext"), ("peajes", "peajes_exterior")),
    ("comida", "Comida y viáticos", ("comida",), ("costo_viaticos", "costo_comidas")),
    ("hotel", "Hotel / estadía", ("hotel",), ("costo_hospedaje",)),
    ("tramites", "Trámites (DINATRAN, aduana, frontera…)",
     ("dinatran", "carta_azul", "aduana", "migraciones", "senasa", "desinfeccion"), ("tramites", "seguro_viaje")),
    ("otros", "Otros (lavado, gomería, ruta…)",
     ("estacionamiento", "lavado", "gomeria", "mantenimiento", "limpieza", "taxi", "otros"), ("otros",)),
]

# Columnas que se agregaron después de la primera versión
COLUMNAS_NUEVAS = {
    "turismo_rendiciones": [
        ("chofer2", "TEXT DEFAULT ''"), ("matricula", "TEXT DEFAULT ''"), ("tramo", "TEXT DEFAULT ''"),
        ("hora_salida", "TEXT DEFAULT ''"), ("hora_llegada", "TEXT DEFAULT ''"), ("dias_trabajados", "REAL DEFAULT 0"),
        ("km_inicial", "REAL DEFAULT 0"), ("km_final", "REAL DEFAULT 0"), ("ingreso", "REAL DEFAULT 0"),
        ("descuentos", "REAL DEFAULT 0"), ("fecha_rendicion", "TEXT DEFAULT ''"), ("elaborado_por", "TEXT DEFAULT ''"),
        ("origen", "TEXT DEFAULT ''"),
    ],
    "turismo_rend_movs": [("pagado_por", "TEXT DEFAULT 'chofer'"), ("precio_litro", "REAL DEFAULT 0")],
}


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
    """'1.250.000' → 1250000 ; '50,5' → 50.5 ; números tal cual."""
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


def _txt(v, mayus=False, largo=200):
    s = " ".join(str(v or "").split())[:largo]
    return s.upper() if mayus else s


# ════════════════════════════════════════════════════════════════════════════
# TABLAS
# ════════════════════════════════════════════════════════════════════════════

def init_rendiciones():
    conn = get_connection()
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS turismo_rendiciones (
            id {PK},
            agenda_ot TEXT DEFAULT '',          -- número de orden del viaje (REC 26-42)
            agenda_ids TEXT DEFAULT '',         -- servicios de la agenda que lo forman
            presupuesto_id INTEGER,
            cliente TEXT DEFAULT '',
            salida TEXT DEFAULT '',
            destino TEXT DEFAULT '',
            fecha_salida TEXT DEFAULT '',
            fecha_regreso TEXT DEFAULT '',
            coche TEXT DEFAULT '',
            chofer TEXT DEFAULT '',             -- quien recibe el anticipo y rinde
            tripulacion TEXT DEFAULT '',
            pasajeros INTEGER DEFAULT 0,
            observaciones TEXT DEFAULT '',
            estado TEXT DEFAULT 'abierta',      -- abierta | presentada | aprobada | saldada
            creado_por TEXT DEFAULT '',
            creado_el TEXT DEFAULT '',
            presentado_por TEXT DEFAULT '',
            presentado_el TEXT DEFAULT '',
            aprobado_por TEXT DEFAULT '',
            aprobado_el TEXT DEFAULT '',
            devuelta_motivo TEXT DEFAULT '',    -- si la administración la devolvió para corregir
            saldo_final REAL DEFAULT 0,         -- el saldo al aprobar (lo que hay que devolver o pagar)
            saldado_por TEXT DEFAULT '',
            saldado_el TEXT DEFAULT '',
            saldo_forma TEXT DEFAULT '',        -- efectivo, transferencia, descuento...
            saldo_nota TEXT DEFAULT ''
        )""")
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS turismo_rend_movs (
            id {PK},
            rendicion_id INTEGER NOT NULL,
            tipo TEXT NOT NULL,                 -- anticipo | gasto
            fecha TEXT DEFAULT '',
            categoria TEXT DEFAULT '',
            detalle TEXT DEFAULT '',
            monto REAL DEFAULT 0,               -- en su moneda
            moneda TEXT DEFAULT 'GS',
            cotizacion REAL DEFAULT 1,          -- guaraníes por unidad de esa moneda
            monto_gs REAL DEFAULT 0,
            litros REAL DEFAULT 0,              -- si es combustible
            comprobante TEXT DEFAULT '',        -- número de factura o ticket
            registrado_por TEXT DEFAULT '',
            registrado_el TEXT DEFAULT ''
        )""")
    for sql in ("CREATE INDEX IF NOT EXISTS ix_rend_movs ON turismo_rend_movs (rendicion_id)",
                "CREATE INDEX IF NOT EXISTS ix_rend_salida ON turismo_rendiciones (fecha_salida)"):
        try:
            conn.execute(sql)
        except Exception:
            pass
    conn.commit()
    for tabla, cols in COLUMNAS_NUEVAS.items():
        for col, tipo in cols:
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
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS ix_rend_origen ON turismo_rendiciones (origen)")
        conn.commit()
    except Exception:
        pass
    conn.close()


# ════════════════════════════════════════════════════════════════════════════
# VIAJES DE LA AGENDA
# ════════════════════════════════════════════════════════════════════════════

def viajes_agenda(q="", dias_atras=75, dias_adelante=30):
    """Los viajes de la agenda para armar una rendición: la ida y la vuelta
    con el mismo número de orden y el mismo coche van juntas (cada coche rinde
    por separado, como en la planilla). Los que ya tienen rendición vienen
    marcados."""
    hoy = date.fromisoformat(_hoy())
    desde = (hoy - timedelta(days=dias_atras)).isoformat()
    hasta = (hoy + timedelta(days=dias_adelante)).isoformat()
    conn = get_connection()
    try:
        filas = [dict(r) for r in conn.execute(
            """SELECT * FROM agenda_turismo WHERE fecha >= ? AND fecha <= ? AND COALESCE(estado,'') <> 'cancelado'
               ORDER BY fecha, hora, id""", (desde, hasta)).fetchall()]
        ya = conn.execute("SELECT id, agenda_ot, agenda_ids, coche FROM turismo_rendiciones").fetchall()
    except Exception:
        filas, ya = [], []
    finally:
        conn.close()
    norm_ot = lambda x: "".join(ch for ch in str(x or "").upper() if ch.isalnum())
    con_rend_ot = {(norm_ot(r["agenda_ot"]), str(r["coche"] or "").strip().upper()): r["id"] for r in ya if r["agenda_ot"]}
    con_rend_id = {}
    for r in ya:
        for x in str(r["agenda_ids"] or "").split(","):
            if x.strip().isdigit():
                con_rend_id[int(x)] = r["id"]
    grupos = {}
    for f in filas:
        clave = (("OT", f["ot_nr"], (f.get("coche_interno") or "").strip().upper())
                 if (f.get("ot_nr") or "").strip() else ("ID", f["id"], ""))
        g = grupos.setdefault(clave, {"ot_nr": f.get("ot_nr") or "", "ids": [], "servicios": []})
        g["ids"].append(f["id"])
        g["servicios"].append(f)
    salida = []
    for g in grupos.values():
        sv = g["servicios"]
        primero = sv[0]
        coche = next((s["coche_interno"] for s in sv if (s.get("coche_interno") or "").strip()), "")
        trip = next((s["tripulacion"] for s in sv if (s.get("tripulacion") or "").strip()), "")
        rend = con_rend_ot.get((norm_ot(g["ot_nr"]), coche.strip().upper())) if g["ot_nr"] else None
        rend = rend or next((con_rend_id[i] for i in g["ids"] if i in con_rend_id), None)
        v = {
            "ot_nr": g["ot_nr"], "ids": g["ids"], "cliente": primero.get("cliente") or "",
            "salida": primero.get("salida") or "", "destino": primero.get("destino") or "",
            "fecha_salida": min(s["fecha"] for s in sv), "fecha_regreso": max(s["fecha"] for s in sv),
            "coche": coche, "tripulacion": trip, "chofer": _primer_nombre(trip),
            "pasajeros": max(int(s.get("pasajeros") or 0) for s in sv),
            "servicios": len(sv), "rendicion_id": rend,
        }
        txt = " ".join(str(v[k]) for k in ("ot_nr", "cliente", "salida", "destino", "coche", "tripulacion")).upper()
        if q and q.upper() not in txt:
            continue
        salida.append(v)
    salida.sort(key=lambda v: (v["rendicion_id"] is not None, abs((date.fromisoformat(v["fecha_salida"]) - hoy).days)))
    return salida


def _segundo_nombre(tripulacion):
    """De 'JUAN PEREZ / LUIS GOMEZ' se queda con el segundo (chofer 2)."""
    t = str(tripulacion or "")
    for sep in ("/", " Y ", ",", "+"):
        if sep in t:
            return _txt(t.split(sep)[1], True, 80)
    return ""


def _primer_nombre(tripulacion):
    """De 'JUAN PEREZ / LUIS GOMEZ' se queda con el primero (el que rinde)."""
    t = str(tripulacion or "")
    for sep in ("/", " Y ", ",", "-", "+"):
        if sep in t:
            t = t.split(sep)[0]
            break
    return _txt(t, True, 80)


# ════════════════════════════════════════════════════════════════════════════
# LECTURA
# ════════════════════════════════════════════════════════════════════════════

def _movs(conn, rid):
    return [dict(r) for r in conn.execute(
        "SELECT * FROM turismo_rend_movs WHERE rendicion_id=? ORDER BY fecha, id", (rid,)).fetchall()]


def _es_admin_pago(m):
    return (m.get("pagado_por") or "chofer") == "administracion"


def _cuentas(movs, descuentos=0):
    """anticipos, gastos del chofer, saldo y lo que pagó administración.
    El saldo es solo entre el chofer y la empresa: lo que pagó administración
    directo (el combustible con la tarjeta, por ejemplo) no entra."""
    anticipos = sum(float(m["monto_gs"] or 0) for m in movs if m["tipo"] == "anticipo")
    gastos = sum(float(m["monto_gs"] or 0) for m in movs if m["tipo"] == "gasto" and not _es_admin_pago(m))
    admin = sum(float(m["monto_gs"] or 0) for m in movs if m["tipo"] == "gasto" and _es_admin_pago(m))
    saldo = anticipos - gastos + float(descuentos or 0)
    return round(anticipos), round(gastos), round(saldo), round(admin)


def _saldos_moneda(movs):
    """Lo que tiene que devolver (o poner) el chofer en cada moneda, como en la
    planilla: los pesos sobrantes se devuelven en pesos."""
    out = {}
    for m in movs:
        if m["tipo"] == "gasto" and _es_admin_pago(m):
            continue
        mon = m.get("moneda") or "GS"
        x = out.setdefault(mon, {"moneda": mon, "simbolo": MONEDAS.get(mon, mon), "anticipos": 0.0, "gastos": 0.0,
                                 "sin_cotizacion": False})
        x["anticipos" if m["tipo"] == "anticipo" else "gastos"] += float(m["monto"] or 0)
        if mon != "GS" and not float(m.get("cotizacion") or 0):
            x["sin_cotizacion"] = True
    lista = []
    for mon in MONEDAS:
        if mon in out:
            x = out[mon]
            x["saldo"] = round(x["anticipos"] - x["gastos"], 2)
            x["anticipos"], x["gastos"] = round(x["anticipos"], 2), round(x["gastos"], 2)
            lista.append(x)
    return lista


def _dias(r):
    a, b = _fecha(r.get("fecha_salida")), _fecha(r.get("fecha_regreso"))
    if not a:
        return 0
    if not b or b < a:
        return 1
    return (date.fromisoformat(b) - date.fromisoformat(a)).days + 1


def _por_categoria(movs):
    tot = {}
    for m in movs:
        if m["tipo"] != "gasto":
            continue
        c = m["categoria"] if m["categoria"] in CAT else "otros"
        t = tot.setdefault(c, {**CAT[c], "total": 0.0, "n": 0, "litros": 0.0, "admin": 0.0})
        t["total"] += float(m["monto_gs"] or 0)
        t["n"] += 1
        t["litros"] += float(m["litros"] or 0)
        if _es_admin_pago(m):
            t["admin"] += float(m["monto_gs"] or 0)
    lista = sorted(tot.values(), key=lambda t: -t["total"])
    for t in lista:
        t["total"] = round(t["total"])
        t["admin"] = round(t["admin"])
        t["litros"] = round(t["litros"], 1)
    return lista


def _comparacion(conn, r, movs):
    """Presupuestado contra gastado, rubro por rubro."""
    pid = r.get("presupuesto_id")
    if not pid:
        return None
    fila = conn.execute("SELECT * FROM presupuestos_turismo WHERE id=?", (pid,)).fetchone()
    if not fila:
        return None
    try:
        res = (json.loads(fila["datos_json"] or "{}").get("resultado") or {})
    except (ValueError, TypeError):
        res = {}
    gastado = {}
    for m in movs:
        if m["tipo"] == "gasto":
            gastado[m["categoria"]] = gastado.get(m["categoria"], 0) + float(m["monto_gs"] or 0)
    filas = []
    for clave, nombre, cats, rubros in GRUPOS_PRESUPUESTO:
        pres = sum(float(res.get(x) or 0) for x in rubros)
        real = sum(gastado.get(c, 0) for c in cats)
        if not pres and not real:
            continue
        filas.append({"clave": clave, "nombre": nombre, "presupuestado": round(pres), "real": round(real),
                      "diferencia": round(real - pres),
                      "pct": round((real - pres) / pres * 100, 1) if pres else None})
    tp = sum(f["presupuestado"] for f in filas)
    tr = sum(f["real"] for f in filas)
    return {"presupuesto_id": pid, "destino": fila["destino"], "cliente": fila["cliente"],
            "fecha": str(fila["fecha_creacion"] or "")[:10], "precio_final": round(float(fila["precio_final"] or 0)),
            "filas": filas, "total_presupuestado": tp, "total_real": tr, "diferencia": tr - tp,
            "pct": round((tr - tp) / tp * 100, 1) if tp else None}


def _resumen_fila(r, anticipos, gastos, saldo, admin=0):
    estado = r["estado"] or "abierta"
    if estado in ("aprobada", "saldada"):
        saldo_ref = round(float(r.get("saldo_final") or 0))
    else:
        saldo_ref = saldo
    costo = gastos + admin
    ingreso = round(float(r.get("ingreso") or 0))
    ki, kf = float(r.get("km_inicial") or 0), float(r.get("km_final") or 0)
    km = round(kf - ki) if ki and kf and kf > ki else 0
    return {**r, "anticipos": anticipos, "gastos": gastos, "gastos_admin": admin, "costo_total": costo,
            "saldo": saldo, "saldo_ref": saldo_ref, "dias": _dias(r), "estado_txt": ESTADOS.get(estado, estado),
            "ingreso": ingreso, "resultado": (ingreso - costo) if ingreso else None,
            "rentabilidad": round((ingreso - costo) / ingreso * 100, 1) if ingreso else None, "km_recorridos": km}


def detalle(rid):
    conn = get_connection()
    try:
        r = conn.execute("SELECT * FROM turismo_rendiciones WHERE id=?", (rid,)).fetchone()
        if not r:
            return None
        r = dict(r)
        movs = _movs(conn, rid)
        comp = _comparacion(conn, r, movs)
    finally:
        conn.close()
    anticipos, gastos, saldo, admin = _cuentas(movs, r.get("descuentos"))
    d = _resumen_fila(r, anticipos, gastos, saldo, admin)
    for m in movs:
        m["pagado_por"] = m.get("pagado_por") or "chofer"
        m["categoria_nombre"] = CAT.get(m["categoria"], {}).get("nombre", "") if m["tipo"] == "gasto" else ""
        m["icono"] = CAT.get(m["categoria"], {}).get("icono", "cash") if m["tipo"] == "gasto" else "cash"
    d["anticipos_lista"] = [m for m in movs if m["tipo"] == "anticipo"]
    d["gastos_lista"] = [m for m in movs if m["tipo"] == "gasto"]
    d["por_categoria"] = _por_categoria(movs)
    d["saldos_moneda"] = _saldos_moneda(movs)
    d["sin_cotizacion"] = any(x["sin_cotizacion"] for x in d["saldos_moneda"]) or any(
        m["moneda"] != "GS" and not float(m["cotizacion"] or 0) for m in movs)
    d["comparacion"] = comp
    litros = sum(float(m["litros"] or 0) for m in movs if m["tipo"] == "gasto")
    d["litros"] = round(litros, 1)
    d["consumo"] = round(d["km_recorridos"] / litros, 2) if litros and d["km_recorridos"] else None
    d["gasto_por_dia"] = round(d["costo_total"] / d["dias"]) if d["dias"] else 0
    d["editable"] = (r["estado"] or "abierta") == "abierta"
    return d


def lista(estado="", q="", desde="", hasta=""):
    conn = get_connection()
    try:
        filas = [dict(r) for r in conn.execute(
            "SELECT * FROM turismo_rendiciones ORDER BY fecha_salida DESC, id DESC").fetchall()]
        sumas = {}
        for m in conn.execute("""SELECT rendicion_id, tipo, categoria, COALESCE(pagado_por,'chofer') AS pp,
                                        SUM(monto_gs) AS t, COUNT(*) AS n
                                 FROM turismo_rend_movs GROUP BY rendicion_id, tipo, categoria, COALESCE(pagado_por,'chofer')""").fetchall():
            s = sumas.setdefault(m["rendicion_id"], {"anticipo": 0.0, "gasto": 0.0, "admin": 0.0, "cats": {}, "n": 0})
            t = float(m["t"] or 0)
            if m["tipo"] == "anticipo":
                s["anticipo"] += t
            else:
                s["admin" if m["pp"] == "administracion" else "gasto"] += t
                s["cats"][m["categoria"]] = s["cats"].get(m["categoria"], 0) + t
                s["n"] += int(m["n"] or 0)
    finally:
        conn.close()
    todas = []
    for r in filas:
        s = sumas.get(r["id"], {"anticipo": 0, "gasto": 0, "admin": 0, "cats": {}, "n": 0})
        a, g, ad = round(s["anticipo"]), round(s["gasto"]), round(s["admin"])
        x = _resumen_fila(r, a, g, round(a - g + float(r.get("descuentos") or 0)), ad)
        x["n_gastos"] = s["n"]
        x["cats"] = s["cats"]
        todas.append(x)

    # Los números de arriba miran todas, no solo lo filtrado
    resumen = {
        "cargando": sum(1 for x in todas if x["estado"] == "abierta"),
        "para_aprobar": sum(1 for x in todas if x["estado"] == "presentada"),
        "por_saldar": sum(1 for x in todas if x["estado"] == "aprobada"),
        "devuelven": sum(x["saldo_ref"] for x in todas if x["estado"] == "aprobada" and x["saldo_ref"] > 0),
        "se_les_debe": -sum(x["saldo_ref"] for x in todas if x["estado"] == "aprobada" and x["saldo_ref"] < 0),
        "en_la_calle": sum(x["anticipos"] for x in todas if x["estado"] in ("abierta", "presentada")),
    }

    sel = todas
    if estado == "activas":
        sel = [x for x in sel if x["estado"] != "saldada"]
    elif estado in ESTADOS:
        sel = [x for x in sel if x["estado"] == estado]
    if desde:
        sel = [x for x in sel if (x["fecha_salida"] or "") >= desde]
    if hasta:
        sel = [x for x in sel if (x["fecha_salida"] or "") <= hasta]
    if q:
        Q = q.upper()
        sel = [x for x in sel if Q in " ".join(str(x.get(k) or "") for k in
                                             ("agenda_ot", "cliente", "salida", "destino", "coche", "chofer",
                                              "chofer2", "tripulacion", "tramo")).upper()
               or Q == f"#{x['id']}" or Q == str(x["id"])]

    # Lo que costaron los viajes que salieron en los últimos 90 días, por rubro
    hace90 = (date.fromisoformat(_hoy()) - timedelta(days=90)).isoformat()
    recientes = [x for x in todas if (x["fecha_salida"] or "") >= hace90 and x["costo_total"]]
    cats = {}
    for x in recientes:
        for c, t in x["cats"].items():
            cats[c] = cats.get(c, 0) + t
    gastado_90 = sum(x["costo_total"] for x in recientes)
    resumen["gastado_90"] = gastado_90
    resumen["viajes_90"] = len(recientes)
    resumen["promedio_viaje_90"] = round(gastado_90 / len(recientes)) if recientes else 0
    dias90 = sum(x["dias"] for x in recientes)
    resumen["por_dia_90"] = round(gastado_90 / dias90) if dias90 else 0
    con_ingreso = [x for x in recientes if x["ingreso"]]
    ing = sum(x["ingreso"] for x in con_ingreso)
    cos = sum(x["costo_total"] for x in con_ingreso)
    resumen["ingreso_90"] = ing
    resumen["rentabilidad_90"] = round((ing - cos) / ing * 100, 1) if ing else None
    resumen["categorias_90"] = sorted(
        [{**CAT.get(c, CAT["otros"]), "total": round(t)} for c, t in cats.items()], key=lambda z: -z["total"])
    for x in sel:
        x.pop("cats", None)
    return {"rendiciones": sel, "resumen": resumen, "total": len(todas)}


def cotizaciones():
    """La última cotización usada de cada moneda, para ofrecerla al cargar."""
    conn = get_connection()
    try:
        out = {}
        for m in MONEDAS:
            if m == "GS":
                continue
            r = conn.execute("""SELECT cotizacion FROM turismo_rend_movs WHERE moneda=? AND cotizacion > 0
                                ORDER BY id DESC LIMIT 1""", (m,)).fetchone()
            if r:
                out[m] = float(r["cotizacion"])
        return out
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# ESCRITURA
# ════════════════════════════════════════════════════════════════════════════

CAMPOS_VIAJE = ("cliente", "salida", "destino", "fecha_salida", "fecha_regreso", "coche", "chofer",
                "tripulacion", "pasajeros", "observaciones", "presupuesto_id", "agenda_ot",
                "chofer2", "matricula", "tramo", "hora_salida", "hora_llegada", "dias_trabajados",
                "km_inicial", "km_final", "ingreso", "descuentos", "fecha_rendicion", "elaborado_por")
# Lo que se puede corregir aunque la rendición ya esté presentada (no cambia la cuenta con el chofer)
CAMPOS_SIEMPRE = {"presupuesto_id", "observaciones", "ingreso", "km_inicial", "km_final", "matricula",
                  "hora_salida", "hora_llegada", "elaborado_por", "fecha_rendicion", "tramo"}


def _limpiar_viaje(d):
    out = {}
    for k in CAMPOS_VIAJE:
        if k not in d:
            continue
        v = d.get(k)
        if k in ("fecha_salida", "fecha_regreso", "fecha_rendicion"):
            out[k] = _fecha(v)
        elif k == "pasajeros":
            out[k] = int(_num(v))
        elif k in ("dias_trabajados", "km_inicial", "km_final", "ingreso", "descuentos"):
            out[k] = round(_num(v), 2)
        elif k in ("hora_salida", "hora_llegada"):
            out[k] = _txt(v, False, 5)
        elif k == "tramo":
            out[k] = _txt(v, True, 200)
        elif k == "presupuesto_id":
            out[k] = int(v) if str(v or "").strip().isdigit() else None
        elif k == "observaciones":
            out[k] = _txt(v, False, 500)
        elif k in ("salida", "destino"):
            out[k] = _txt(v, False, 80)
        else:
            out[k] = _txt(v, True, 120)
    return out


def crear(datos, usuario):
    viaje = {}
    ids = [int(x) for x in (datos.get("agenda_ids") or []) if str(x).isdigit()]
    if ids:
        conn = get_connection()
        try:
            marcas = ",".join("?" * len(ids))
            sv = [dict(r) for r in conn.execute(
                f"SELECT * FROM agenda_turismo WHERE id IN ({marcas}) ORDER BY fecha, hora, id", ids).fetchall()]
        finally:
            conn.close()
        if sv:
            trip = next((s["tripulacion"] for s in sv if (s.get("tripulacion") or "").strip()), "")
            viaje = {"agenda_ot": sv[0].get("ot_nr") or "", "cliente": sv[0].get("cliente") or "",
                     "salida": sv[0].get("salida") or "", "destino": sv[0].get("destino") or "",
                     "fecha_salida": min(s["fecha"] for s in sv), "fecha_regreso": max(s["fecha"] for s in sv),
                     "coche": next((s["coche_interno"] for s in sv if (s.get("coche_interno") or "").strip()), ""),
                     "tripulacion": trip, "chofer": _primer_nombre(trip), "chofer2": _segundo_nombre(trip),
                     "pasajeros": max(int(s.get("pasajeros") or 0) for s in sv)}
    viaje.update({k: v for k, v in _limpiar_viaje(datos).items() if v not in ("", None) or k == "presupuesto_id"})
    viaje = _limpiar_viaje(viaje)
    if not viaje.get("cliente") and not viaje.get("destino"):
        return False, "Poné al menos el cliente o el destino del viaje."
    if not viaje.get("fecha_salida"):
        viaje["fecha_salida"] = _hoy()
    conn = get_connection()
    try:
        campos = list(viaje.keys()) + ["agenda_ids", "estado", "creado_por", "creado_el"]
        valores = list(viaje.values()) + [",".join(str(i) for i in ids), "abierta", usuario, _ahora()]
        cur = conn.execute(f"INSERT INTO turismo_rendiciones ({', '.join(campos)}) VALUES ({', '.join('?' * len(campos))})",
                           valores)
        rid = cur.lastrowid or conn.execute("SELECT MAX(id) AS m FROM turismo_rendiciones").fetchone()["m"]
        # Anticipo inicial, si se cargó al crearla
        if _num(datos.get("anticipo")) > 0:
            _insertar_mov(conn, rid, {"tipo": "anticipo", "monto": datos.get("anticipo"),
                                      "moneda": datos.get("anticipo_moneda") or "GS",
                                      "cotizacion": datos.get("anticipo_cotizacion"),
                                      "fecha": datos.get("anticipo_fecha") or viaje.get("fecha_salida"),
                                      "detalle": "Anticipo"}, usuario)
        conn.commit()
        return True, rid
    finally:
        conn.close()


def editar_viaje(rid, datos):
    campos = _limpiar_viaje(datos)
    if not campos:
        return False, "Nada para cambiar."
    conn = get_connection()
    try:
        r = conn.execute("SELECT estado FROM turismo_rendiciones WHERE id=?", (rid,)).fetchone()
        if not r:
            return False, "La rendición no existe."
        # El presupuesto se puede vincular siempre (es para comparar); el resto, solo cargando
        if r["estado"] != "abierta" and set(campos) - CAMPOS_SIEMPRE:
            return False, "La rendición ya se presentó: para corregir, la administración la tiene que reabrir."
        conn.execute(f"UPDATE turismo_rendiciones SET {', '.join(k + '=?' for k in campos)} WHERE id=?",
                     list(campos.values()) + [rid])
        conn.commit()
        return True, "Viaje actualizado."
    finally:
        conn.close()


def _valores_mov(d, planilla=False):
    """planilla=True: viene de la planilla de Excel, se carga tal cual estaba (si
    no tenía cotización o monto, queda en blanco)."""
    tipo = d.get("tipo") if d.get("tipo") in ("anticipo", "gasto") else "gasto"
    moneda = str(d.get("moneda") or "GS").upper()
    moneda = moneda if moneda in MONEDAS else "GS"
    monto = round(_num(d.get("monto")), 2)
    cot = 1.0 if moneda == "GS" else round(_num(d.get("cotizacion")), 4)
    litros = round(_num(d.get("litros")), 2) if tipo == "gasto" else 0
    precio = round(_num(d.get("precio_litro")), 2) if tipo == "gasto" else 0
    if monto <= 0 and litros > 0 and precio > 0:
        monto = round(litros * precio, 2)          # litros × precio del litro
    if monto <= 0 and not (planilla and litros > 0):
        return None, "Poné el monto."
    if moneda != "GS" and cot <= 0 and not planilla:
        return None, f"Poné la cotización del {MONEDAS[moneda]} (cuántos guaraníes vale cada uno)."
    cat = d.get("categoria") if d.get("categoria") in CAT else ("otros" if tipo == "gasto" else "")
    pago = "administracion" if (tipo == "gasto" and d.get("pagado_por") == "administracion") else "chofer"
    return {"tipo": tipo, "fecha": _fecha(d.get("fecha")) or _hoy(), "categoria": cat,
            "detalle": _txt(d.get("detalle"), False, 160), "monto": monto, "moneda": moneda, "cotizacion": cot,
            "monto_gs": round(monto * cot), "litros": litros, "precio_litro": precio, "pagado_por": pago,
            "comprobante": _txt(d.get("comprobante"), True, 40)}, None


def _insertar_mov(conn, rid, d, usuario, planilla=False):
    v, err = _valores_mov(d, planilla)
    if err:
        return None, err
    v.update(rendicion_id=rid, registrado_por=usuario, registrado_el=_ahora())
    cur = conn.execute(f"INSERT INTO turismo_rend_movs ({', '.join(v)}) VALUES ({', '.join('?' * len(v))})",
                       list(v.values()))
    return cur.lastrowid, None


def _estado_de(conn, rid):
    r = conn.execute("SELECT estado FROM turismo_rendiciones WHERE id=?", (rid,)).fetchone()
    return r["estado"] if r else None


def agregar_mov(rid, d, usuario):
    conn = get_connection()
    try:
        est = _estado_de(conn, rid)
        if est is None:
            return False, "La rendición no existe."
        if est != "abierta":
            return False, "La rendición ya se presentó: para cargar algo más, la administración la tiene que reabrir."
        mid, err = _insertar_mov(conn, rid, d, usuario)
        if err:
            return False, err
        conn.commit()
        return True, mid
    finally:
        conn.close()


def editar_mov(mid, d):
    conn = get_connection()
    try:
        m = conn.execute("SELECT * FROM turismo_rend_movs WHERE id=?", (mid,)).fetchone()
        if not m:
            return False, "Ese movimiento ya no existe."
        if _estado_de(conn, m["rendicion_id"]) != "abierta":
            return False, "La rendición ya se presentó: no se puede cambiar."
        base = dict(m)
        base.update({k: d[k] for k in ("fecha", "categoria", "detalle", "monto", "moneda", "cotizacion",
                                       "litros", "comprobante", "pagado_por", "precio_litro") if k in d})
        v, err = _valores_mov(base)
        if err:
            return False, err
        v.pop("tipo")
        conn.execute(f"UPDATE turismo_rend_movs SET {', '.join(k + '=?' for k in v)} WHERE id=?",
                     list(v.values()) + [mid])
        conn.commit()
        return True, m["rendicion_id"]
    finally:
        conn.close()


def borrar_mov(mid):
    conn = get_connection()
    try:
        m = conn.execute("SELECT rendicion_id FROM turismo_rend_movs WHERE id=?", (mid,)).fetchone()
        if not m:
            return False, "Ese movimiento ya no existe."
        if _estado_de(conn, m["rendicion_id"]) != "abierta":
            return False, "La rendición ya se presentó: no se puede borrar."
        conn.execute("DELETE FROM turismo_rend_movs WHERE id=?", (mid,))
        conn.commit()
        return True, m["rendicion_id"]
    finally:
        conn.close()


def cambiar_estado(rid, accion, usuario, es_admin, datos=None):
    """presentar · aprobar · devolver · saldar · reabrir"""
    datos = datos or {}
    conn = get_connection()
    try:
        r = conn.execute("SELECT * FROM turismo_rendiciones WHERE id=?", (rid,)).fetchone()
        if not r:
            return False, "La rendición no existe."
        est = r["estado"]
        movs = _movs(conn, rid)
        anticipos, gastos, saldo, _admin = _cuentas(movs, r["descuentos"] if "descuentos" in r.keys() else 0)
        ahora = _ahora()
        if accion == "presentar":
            if est != "abierta":
                return False, "Ya estaba presentada."
            if not movs:
                return False, "Cargá al menos el anticipo o un gasto antes de presentarla."
            conn.execute("""UPDATE turismo_rendiciones SET estado='presentada', presentado_por=?, presentado_el=?,
                            devuelta_motivo='' WHERE id=?""", (usuario, ahora, rid))
            msg = "Presentada: queda para que la administración la apruebe."
        elif accion in ("aprobar", "devolver", "saldar", "reabrir") and not es_admin:
            return False, "Eso lo hace la administración."
        elif accion == "aprobar":
            if est != "presentada":
                return False, "Solo se aprueba una rendición presentada."
            nuevo = "saldada" if saldo == 0 else "aprobada"
            conn.execute(f"""UPDATE turismo_rendiciones SET estado=?, aprobado_por=?, aprobado_el=?, saldo_final=?
                             {", saldado_por=?, saldado_el=?, saldo_forma='Cierra justo'" if nuevo == "saldada" else ""}
                             WHERE id=?""",
                         [nuevo, usuario, ahora, saldo] + ([usuario, ahora] if nuevo == "saldada" else []) + [rid])
            msg = "Aprobada: cierra justo, no hay nada que devolver ni pagar." if nuevo == "saldada" \
                else "Aprobada. Falta registrar la devolución o el pago."
        elif accion == "devolver":
            if est != "presentada":
                return False, "Solo se devuelve una rendición presentada."
            motivo = _txt(datos.get("motivo"), False, 300)
            if len(motivo) < 4:
                return False, "Escribí qué hay que corregir."
            conn.execute("UPDATE turismo_rendiciones SET estado='abierta', devuelta_motivo=? WHERE id=?", (motivo, rid))
            msg = "Devuelta para corregir."
        elif accion == "saldar":
            if est != "aprobada":
                return False, "Primero hay que aprobarla."
            forma = _txt(datos.get("forma"), False, 60) or "Efectivo"
            conn.execute("""UPDATE turismo_rendiciones SET estado='saldada', saldado_por=?, saldado_el=?,
                            saldo_forma=?, saldo_nota=? WHERE id=?""",
                         (usuario, _fecha(datos.get("fecha")) or ahora, forma, _txt(datos.get("nota"), False, 200), rid))
            msg = "Saldada: la cuenta del viaje quedó cerrada."
        elif accion == "reabrir":
            if est == "abierta":
                return False, "Ya está abierta."
            conn.execute("""UPDATE turismo_rendiciones SET estado='abierta', aprobado_por='', aprobado_el='',
                            saldado_por='', saldado_el='', saldo_forma='', saldo_nota='', saldo_final=0
                            WHERE id=?""", (rid,))
            msg = "Reabierta: se puede volver a cargar."
        else:
            return False, "Acción desconocida."
        conn.commit()
        return True, msg
    finally:
        conn.close()


def borrar(rid):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM turismo_rend_movs WHERE rendicion_id=?", (rid,))
        conn.execute("DELETE FROM turismo_rendiciones WHERE id=?", (rid,))
        conn.commit()
        return True
    finally:
        conn.close()


def presupuestos_para_vincular(q=""):
    conn = get_connection()
    try:
        filas = [dict(r) for r in conn.execute(
            """SELECT id, fecha_creacion, destino, cliente, km_total, dias, precio_final
               FROM presupuestos_turismo ORDER BY fecha_creacion DESC LIMIT 200""").fetchall()]
    except Exception:
        filas = []
    finally:
        conn.close()
    if q:
        Q = q.upper()
        filas = [f for f in filas if Q in f"{f['destino']} {f['cliente']}".upper()]
    return [{**f, "fecha": str(f["fecha_creacion"] or "")[:10], "precio_final": round(float(f["precio_final"] or 0))}
            for f in filas[:40]]


# ════════════════════════════════════════════════════════════════════════════
# IMPORTAR LAS PLANILLAS DE EXCEL ("RENDICION TURISMO")
# ════════════════════════════════════════════════════════════════════════════
# Una hoja por día y, al costado, una rendición por coche (columnas A-I, K-S…).
# Cada rendición: coche, choferes, tramo, salida y llegada, km, viático al
# chofer (en guaraníes y en pesos/reales), los gastos (de la columna del chofer
# en guaraníes, pesos/reales o dólares, y la de ADMINISTRACION, que paga la
# empresa directo) y lo cobrado por el servicio. No todas las hojas tienen las
# columnas en el mismo lugar: todo se busca por el nombre del renglón.
import re as _re
import unicodedata as _ud
import hashlib as _hl
from datetime import datetime as _dt, time as _time

_PL_MESES = {"ENERO": 1, "FEBRERO": 2, "MARZO": 3, "ABRIL": 4, "MAYO": 5, "JUNIO": 6, "JULIO": 7, "AGOSTO": 8,
         "SEPTIEMBRE": 9, "SETIEMBRE": 9, "OCTUBRE": 10, "NOVIEMBRE": 11, "DICIEMBRE": 12}

_PL_AR = ("BUENOS AIRES", "ARGENTINA", "CORDOBA", "CARLOS PAZ", "MENDOZA", "SALTA", "JUJUY", "JUJUI", "TUCUMAN", "BARILOCHE",
      "ROSARIO", "CORRIENTES", "RESISTENCIA", "POSADAS", "CLORINDA", "FORMOSA", "SAN RAFAEL", "MAR DEL PLATA", "CAFAYATE",
      "HUMAHUACA", "IGUAZU ARG", "PUERTO IGUAZU", "SANTA FE", "CHAJARI", "ROCCA", "NEUQUEN", "TAFI")
_PL_BR = ("BRASIL", "FOZ", "CAMBORIU", "FLORIANOPOLIS", "RIO DE JANEIRO", "SAO PAULO", "CURITIBA", "PORTO ALEGRE", "GRAMADO",
      "PONTA PORA", "BOMBINHAS", "CASCAVEL", "BALNEARIO")


def _pl_norm(s):
    return " ".join(_ud.normalize("NFD", str(s if s is not None else "")).encode("ascii", "ignore")
                    .decode().upper().replace(" ", " ").split())


def _pl_es_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _pl_num(v):
    if _pl_es_num(v):
        return float(v)
    if isinstance(v, str):
        s = v.strip().replace(" ", "")
        if not s or s.startswith("#"):
            return 0.0
        if "," in s:
            s = s.replace(".", "").replace(",", ".")
        elif s.count(".") > 1 or _re.fullmatch(r"\d+\.\d{3}", s):
            s = s.replace(".", "")
        try:
            return float(s)
        except ValueError:
            return 0.0
    return 0.0


def _pl_fecha(v):
    if isinstance(v, _dt):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, str):
        m = _re.search(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", v)
        if m:
            d, mm, a = int(m.group(1)), int(m.group(2)), int(m.group(3))
            a = a + 2000 if a < 100 else a
            try:
                return date(a, mm, d).isoformat()
            except ValueError:
                return ""
    return ""


def _pl_hora(v):
    if isinstance(v, _time):
        return f"{v.hour:02d}:{v.minute:02d}"
    if isinstance(v, _dt):
        return f"{v.hour:02d}:{v.minute:02d}"
    if _pl_es_num(v) and 0 <= v < 1:                     # fracción del día
        m = round(v * 1440)
        return f"{m // 60:02d}:{m % 60:02d}"
    if isinstance(v, str):
        m = _re.search(r"(\d{1,2})\s*[:.;,hH]\s*(\d{2})", v)
        if m and int(m.group(1)) < 24:
            return f"{int(m.group(1)):02d}:{m.group(2)}"
        m = _re.fullmatch(r"\s*(\d{1,2})\s*(HS|H)?\s*", v.upper())
        if m and int(m.group(1)) < 24:
            return f"{int(m.group(1)):02d}:00"
    return ""


def _pl_texto(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = " ".join(str(v).split())
    return "" if s in (".", "-", ".-") else s


# Rubro del sistema según cómo lo escribieron en la planilla
def _pl_rubro(etiqueta):
    e = _pl_norm(etiqueta)
    reglas = [
        ("combustible_ext", ("COMBUSTIBLE INTERNACIONAL", "COMBUSTIBLE EXTERIOR", "COMBUSTIBLE ARG", "COMBUSTIBLE _PL_BR")),
        ("combustible", ("COMBUSTIBLE", "GASOIL", "DIESEL")),
        ("peajes_ext", ("PEAJE INTERNACIONAL", "PEAJES INTERNACIONAL", "TELEPASE", "TELEPEAJE")),
        ("peajes", ("PEAJE",)),
        ("salario", ("SALARIO", "SUELDO", "JORNAL")),
        ("hotel", ("HOSPEDAJE", "HOTEL", "ESTADIA", "ALOJAMIENTO")),
        ("lavado", ("LAVADO",)),
        ("estacionamiento", ("ESTACIONAMIENTO", "PLAYA")),
        ("dinatran", ("DINATRAN",)),
        ("carta_azul", ("CARTA AZUL",)),
        ("aduana", ("ADUANA",)),
        ("migraciones", ("MIGRACION",)),
        ("senasa", ("SENASA", "SANIDAD")),
        ("desinfeccion", ("DESINFECCION",)),
        ("gomeria", ("GOMERIA", "VULCANIZ", "CUBIERTA")),
        ("mantenimiento", ("ENGRASE", "ACEITE", "CALIBRACION", "REPUESTO", "MECANIC", "FILTRO")),
        ("limpieza", ("LIMPIEZA", "AROMATIZ", "HIELO", "ESCOBA", "MANGUERA", "SUPERMERCADO")),
        ("comida", ("VIATICO", "COMIDA", "CAFE", "ALMUERZO", "CENA", "DESAYUNO")),
        ("taxi", ("TAXI", "REMIS", "UBER", "TRANSPORTE")),
    ]
    for clave, palabras in reglas:
        if any(p in e for p in palabras):
            return clave
    return "otros"


# Las etiquetas que ya trae la planilla: si dice eso, no hace falta repetirlo en el detalle
_PL_ETIQUETAS_MODELO = {_pl_norm(x) for x in (
    "COMBUSTIBLE NACIONAL", "COMBUSTIBLE INTERNACIONAL", "PEAJE INTERNACIONAL", "PEAJES NACIONAL", "SALARIO + VIATICO",
    "SENASA", "GOMERIA", "PEAJES", "DINATRAN", "HIELO", "GASTOS VARIOS", "ADUANA", "MIGRACIONES", "CARTA AZUL",
    "HOSPEDAJE", "TAXI", "DESINFECCION", "LAVADO", "ESTACIONAMIENTO")}


def _pl_moneda_por_tramo(t):
    t = _pl_norm(t)
    if any(p in t for p in _PL_AR):
        return "ARS"
    if any(p in t for p in _PL_BR):
        return "BRL"
    return ""


class _PlBloque:
    def __init__(self, ws, c0, c1):
        self.ws, self.c0, self.c1 = ws, c0, c1
        self.max_r = min(ws.max_row, 80)
        self.celdas = {}
        for r in range(1, self.max_r + 1):
            for c in range(c0, c1 + 1):
                v = ws.cell(r, c).value
                if v is not None and not (isinstance(v, str) and not v.strip()):
                    self.celdas[(r, c)] = v

    def buscar(self, *etiquetas, desde=1, hasta=None, empieza=True):
        hasta = hasta or self.max_r
        objetivos = [_pl_norm(e) for e in etiquetas]
        for (r, c), v in sorted(self.celdas.items()):
            if r < desde or r > hasta or not isinstance(v, str):
                continue
            t = _pl_norm(v)
            for o in objetivos:
                if (t.startswith(o) if empieza else t == o):
                    return r, c
        return None

    def a_la_derecha(self, r, c, cuantos=1, saltear_texto=False):
        """Los valores que siguen a una etiqueta, en la misma fila."""
        out = []
        for cc in range(c + 1, self.c1 + 1):
            v = self.celdas.get((r, cc))
            if v is None:
                continue
            if isinstance(v, str) and _pl_norm(v) in _PL_ETIQUETAS_FILA:
                break
            if saltear_texto and isinstance(v, str) and not v.strip(" .-"):
                continue
            out.append(v)
            if len(out) >= cuantos:
                break
        return out

    def valor(self, *etiquetas, tipo="texto"):
        p = self.buscar(*etiquetas)
        if not p:
            return "" if tipo == "texto" else 0.0
        vals = self.a_la_derecha(*p, cuantos=3)
        if tipo == "texto":
            for v in vals:
                t = _pl_texto(v)
                if t:
                    return t
            return ""
        if tipo == "num":
            for v in vals:
                if _pl_es_num(v) or (isinstance(v, str) and _pl_num(v)):
                    return _pl_num(v)
            return 0.0
        if tipo == "fecha":
            for v in vals:
                if _pl_fecha(v):
                    return _pl_fecha(v)
            return ""
        return vals


_PL_ETIQUETAS_FILA = {_pl_norm(x) for x in (
    "PERIODO", "FECHA RENDICION", "VEHICULO", "MATRICULA", "ORDEN DE", "SERVICIO", "CHOFER 1", "CHOFER 2",
    "DIAS TRABAJADOS", "TRAMO", "SALIDA", "LLEGADA", "KMS. INICIAL", "KMS. FINAL", "KM.RECORRIDO", "PROM.CONSUMO",
    "LTS.CONSUMIDO", "VIATICO AL CHOFER", "GS.", "REALES", "PESOS", "DOLAR", "DOLARES")}


def _pl_leer_bloque(b, archivo="", hoja=""):
    r = {"archivo": archivo, "hoja": hoja}
    r["periodo"] = b.valor("PERIODO")
    r["fecha_rendicion"] = b.valor("FECHA RENDICION", tipo="fecha")
    r["coche"] = b.valor("VEHICULO")
    r["matricula"] = b.valor("MATRICULA")
    r["chofer"] = b.valor("CHOFER 1")
    r["chofer2"] = b.valor("CHOFER 2")
    r["dias_trabajados"] = b.valor("DIAS TRABAJADOS", tipo="num")
    r["tramo"] = b.valor("TRAMO")
    r["km_inicial"] = b.valor("KMS. INICIAL", tipo="num")
    r["km_final"] = b.valor("KMS. FINAL", tipo="num")
    # Salida y llegada: fecha y hora
    for clave in ("SALIDA", "LLEGADA"):
        p = b.buscar(clave)
        f, h = "", ""
        if p:
            vals = b.a_la_derecha(*p, cuantos=3)
            for v in vals:
                if not f and _pl_fecha(v):
                    f = _pl_fecha(v)
                    if isinstance(v, _dt) and (v.hour or v.minute):
                        h = _pl_hora(v)
                elif f and not h and _pl_hora(v):
                    h = _pl_hora(v)
        r["fecha_" + clave.lower()] = f
        r["hora_" + clave.lower()] = h
    # Orden de servicio: debajo de "ORDEN DE / SERVICIO"
    p = b.buscar("ORDEN DE")
    r["orden"] = ""
    if p:
        for rr in range(p[0] + 1, p[0] + 6):
            v = b.celdas.get((rr, p[1]))
            if v is not None and _pl_norm(v) not in ("SERVICIO", ""):
                r["orden"] = _pl_texto(v).upper()
                break
    # Viático al chofer (el anticipo): en guaraníes y en otra moneda
    r["viatico_gs"], r["viatico_otra"], r["viatico_moneda"] = 0.0, 0.0, ""
    p = b.buscar("VIATICO AL CHOFER", empieza=False) or b.buscar("VIATICO AL CHOFER")
    if not p:
        for (rr, cc), v in b.celdas.items():
            if isinstance(v, str) and "VIATICO AL CHOFER" in _pl_norm(v):
                p = (rr, cc)
                break
    if p:
        for rr in (p[0] - 1, p[0]):
            for cc in range(p[1] + 1, b.c1 + 1):
                v = b.celdas.get((rr, cc))
                if isinstance(v, str) and _pl_norm(v) in ("GS.", "GS", "REALES", "REAL", "PESOS", "DOLAR", "DOLARES", "USD"):
                    # el número está a la izquierda de la etiqueta de moneda
                    monto = 0.0
                    for c2 in range(cc - 1, p[1], -1):
                        if _pl_es_num(b.celdas.get((rr, c2))):
                            monto = float(b.celdas[(rr, c2)])
                            break
                    m = _pl_norm(v)
                    if m.startswith("GS"):
                        r["viatico_gs"] = monto
                    else:
                        r["viatico_otra"] = monto
                        r["viatico_moneda"] = {"REALES": "BRL", "REAL": "BRL", "PESOS": "ARS"}.get(m, "USD")
                    break
    # Cotizaciones (cuadro de moneda extranjera)
    r["cambio"] = {}
    p = b.buscar("MONEDA EXTRANJERA")
    if p:
        hc = b.buscar("CAMBIO", desde=p[0], hasta=p[0])
        for rr in range(p[0] + 1, p[0] + 5):
            nombre = _pl_norm(b.celdas.get((rr, p[1]), ""))
            mon = {"PESOS": "ARS", "PESO": "ARS", "REAL": "BRL", "REALES": "BRL", "DOLAR": "USD", "DOLARES": "USD"}.get(nombre)
            if mon and hc:
                c = _pl_num(b.celdas.get((rr, hc[1])))
                if c > 0:
                    r["cambio"][mon] = c
    # Gastos
    r["gastos"] = []
    p = b.buscar("GASTOS", empieza=False)
    cols = {}
    if p:
        for (rr, cc), v in b.celdas.items():
            if rr == p[0] and isinstance(v, str):
                t = _pl_norm(v)
                for clave, nombre in (("litros", "LITROS"), ("precio", "PRECIO"), ("gs", "GUARANIES"),
                                      ("otra", "PESOS/REAL"), ("usd", "DOLAR"), ("adm", "ADMINISTRACION")):
                    if t.startswith(nombre):
                        cols[clave] = cc
        fin = b.buscar("CAMBIO A MONEDA", desde=p[0]) or b.buscar("TOTAL GASTOS", desde=p[0])
        fin_r = (fin[0] - 1) if fin else p[0] + 26
        for rr in range(p[0] + 1, fin_r + 1):
            etiqueta = _pl_texto(b.celdas.get((rr, b.c0)))
            if not etiqueta:
                continue
            g = {"etiqueta": etiqueta, "rubro": _pl_rubro(etiqueta)}
            for k in ("litros", "precio", "gs", "otra", "usd", "adm"):
                g[k] = _pl_num(b.celdas.get((rr, cols[k]))) if k in cols else 0.0
            if any(g[k] for k in ("litros", "gs", "otra", "usd", "adm")):
                r["gastos"].append(g)
    r["descuentos"] = b.valor("DESCTOS", tipo="num")
    r["ingreso"] = b.valor("INGRESO", tipo="num")
    p = b.buscar("ELABORADO POR")
    r["elaborado_por"] = ""
    if p:
        t = _pl_texto(b.celdas.get(p)).split(":", 1)[1].strip() if ":" in str(b.celdas.get(p)) else ""
        r["elaborado_por"] = t or " ".join(_pl_texto(v) for v in b.a_la_derecha(*p, cuantos=3) if _pl_texto(v))
    p = b.buscar("OBS")
    r["obs"] = ""
    if p:
        t = _pl_texto(b.celdas.get(p))
        t = _re.sub(r"^OBS\s*[:.]?\s*", "", t, flags=_re.I).strip(" .-")
        resto = " ".join(_pl_texto(v) for v in b.a_la_derecha(*p, cuantos=6) if _pl_texto(v))
        r["obs"] = " ".join(x for x in (t, resto) if x).strip(" .-")
    # Moneda de la columna "PESOS/REAL"
    mon = ""
    for m in ("ARS", "BRL"):
        if m in r["cambio"]:
            mon = mon or m
    mon = mon or (r["viatico_moneda"] if r["viatico_moneda"] in ("ARS", "BRL") and r["viatico_otra"] else "")
    mon = mon or _pl_moneda_por_tramo(r["tramo"])
    if not mon:
        p = b.buscar("SALDO")
        mon = "BRL"
        if p:
            for v in b.a_la_derecha(*p, cuantos=3):
                if isinstance(v, str) and _pl_norm(v) == "PESOS":
                    mon = "ARS"
    r["moneda_otra"] = mon
    if r["viatico_otra"] and r["viatico_moneda"] in ("ARS", "BRL"):
        r["viatico_moneda"] = mon if r["viatico_moneda"] != mon and mon in r["cambio"] else r["viatico_moneda"]
    r["vacio"] = not (r["chofer"] or r["tramo"] or r["gastos"] or r["viatico_gs"] or r["viatico_otra"])
    return r


def _pl_leer_libro(wb, archivo=""):
    salida = []
    for ws in wb.worksheets:
        inicios = sorted(c.column for c in ws[1] if _pl_norm(c.value).startswith("RENDICION TURISMO"))
        if not inicios:
            continue
        for i, c0 in enumerate(inicios):
            c1 = (inicios[i + 1] - 1) if i + 1 < len(inicios) else ws.max_column
            r = _pl_leer_bloque(_PlBloque(ws, c0, c1), archivo, ws.title)
            r["bloque"] = i + 1
            if not r["vacio"]:
                salida.append(r)
    return salida


def _pl_titulo(s):
    """'COMBUSTIBLE INTERNACIONAL ROCCA' → 'Combustible internacional Rocca' (lo justo para leer)."""
    s = _pl_texto(s)
    if not s:
        return ""
    s = s.lower()
    return s[0].upper() + s[1:]


def _pl_salida_destino(tramo):
    """'ASUNCION - PJC - ASUNCION' → ('ASUNCION', 'PJC'). 'ASUNCION BUENOS AIRES - ASUNCION' → ('ASUNCION', 'BUENOS AIRES')."""
    t = _pl_texto(tramo)
    partes = [p.strip(" .-") for p in _re.split(r"\s+-\s*|\s*-\s+|\s*/\s*|\s+X\s+", t) if p.strip(" .-")]
    if not partes:
        return "", ""
    if len(partes) == 1:
        p = partes[0]
        n = _pl_norm(p)
        if n.startswith("ASUNCION ") and len(n) > 10:
            return "Asunción", p.split(" ", 1)[1].title()
        return "", p.title()
    a, b = partes[0], partes[1]
    if _pl_norm(a).startswith("ASUNCION ") and len(_pl_norm(a)) > 10:
        return "Asunción", a.split(" ", 1)[1].title()
    return a.title(), b.title()


def _pl_a_rendicion(bl):
    """Una rendición de la planilla → los datos del viaje y sus movimientos."""
    salida, destino = _pl_salida_destino(bl["tramo"])
    fs = bl["fecha_salida"] or bl["fecha_rendicion"]
    choferes = [x for x in (bl["chofer"], bl["chofer2"]) if x]
    viaje = {
        "agenda_ot": bl["orden"], "cliente": "", "salida": salida, "destino": destino, "tramo": bl["tramo"].upper(),
        "fecha_salida": fs, "fecha_regreso": bl["fecha_llegada"] or fs, "hora_salida": bl["hora_salida"],
        "hora_llegada": bl["hora_llegada"], "coche": bl["coche"], "matricula": bl["matricula"],
        "chofer": (bl["chofer"] or "").upper(), "chofer2": (bl["chofer2"] or "").upper(),
        "tripulacion": " / ".join(choferes).upper(), "dias_trabajados": bl["dias_trabajados"],
        "km_inicial": bl["km_inicial"], "km_final": bl["km_final"], "ingreso": bl["ingreso"],
        "descuentos": bl["descuentos"], "fecha_rendicion": bl["fecha_rendicion"], "elaborado_por": bl["elaborado_por"],
        "observaciones": bl["obs"],
    }
    mon = bl["moneda_otra"] or "BRL"
    cot = bl["cambio"]
    movs = []
    if bl["viatico_gs"]:
        movs.append({"tipo": "anticipo", "fecha": fs, "detalle": "Viático al chofer", "monto": bl["viatico_gs"], "moneda": "GS"})
    if bl["viatico_otra"]:
        m = bl["viatico_moneda"] if bl["viatico_moneda"] in MONEDAS and bl["viatico_moneda"] != "GS" else mon
        movs.append({"tipo": "anticipo", "fecha": fs, "detalle": "Viático al chofer", "monto": bl["viatico_otra"],
                     "moneda": m, "cotizacion": cot.get(m, 0)})
    n_salario = 0
    for g in bl["gastos"]:
        cat = g["rubro"]
        detalle = "" if _pl_norm(g["etiqueta"]) in _PL_ETIQUETAS_MODELO else _pl_titulo(g["etiqueta"])
        if cat == "salario":
            # Los dos renglones de salario son el del chofer 1 y el del chofer 2
            quien = choferes[n_salario] if n_salario < len(choferes) else ""
            n_salario += 1
            detalle = quien.title() if quien else detalle
        litros = g["litros"]
        partes = [("gs", "GS", "chofer"), ("otra", mon, "chofer"), ("usd", "USD", "chofer"), ("adm", "GS", "administracion")]
        hechos = 0
        for k, moneda, pago in partes:
            monto = g[k]
            if not monto:
                continue
            precio = g["precio"] if (litros and moneda == "GS" and g["precio"]
                                     and abs(litros * g["precio"] - monto) <= max(1, monto * 0.02)) else 0
            movs.append({"tipo": "gasto", "fecha": fs, "categoria": cat, "detalle": detalle, "monto": monto,
                         "moneda": moneda, "cotizacion": cot.get(moneda, 0) if moneda != "GS" else 1,
                         "litros": litros if hechos == 0 else 0, "precio_litro": precio, "pagado_por": pago})
            hechos += 1
        if not hechos and litros:
            # Litros sin plata anotada: se cargan los litros y el monto queda en blanco
            movs.append({"tipo": "gasto", "fecha": fs, "categoria": cat, "detalle": detalle, "monto": 0, "moneda": "GS",
                         "litros": litros, "pagado_por": "administracion" if cat in COMBUSTIBLES else "chofer"})
    return viaje, movs


def _pl_origen(bl):
    clave = "|".join(_pl_norm(x) for x in (bl["fecha_salida"], bl["coche"], bl["orden"], bl["chofer"], bl["tramo"],
                                          bl["fecha_rendicion"]))
    return "planilla:" + _hl.sha1(clave.encode()).hexdigest()[:20]


def importar_planillas(archivos, usuario, probar=True):
    """archivos: [(nombre, bytes)]. Con probar=True solo cuenta lo que va a entrar."""
    import openpyxl
    resumen = {"archivos": [], "nuevas": 0, "repetidas": 0, "gastos": 0, "sin_fecha_rendicion": 0,
               "sin_cotizacion": 0, "errores": [], "importadas": 0}
    conn = get_connection()
    try:
        ya = {r["origen"] for r in conn.execute("SELECT origen FROM turismo_rendiciones WHERE origen <> ''").fetchall()}
        vistos = set()
        for nombre, datos in archivos:
            info = {"nombre": nombre, "periodos": [], "rendiciones": 0, "nuevas": 0, "repetidas": 0, "gastos": 0,
                    "desde": "", "hasta": "", "costo": 0, "ingreso": 0}
            try:
                wb = openpyxl.load_workbook(io.BytesIO(datos), data_only=True)
                bloques = _pl_leer_libro(wb, nombre)
            except Exception as e:
                resumen["errores"].append(f"{nombre}: no se pudo leer ({e.__class__.__name__}).")
                continue
            if not bloques:
                resumen["errores"].append(f"{nombre}: no tiene hojas de rendición de turismo.")
            for bl in bloques:
                info["rendiciones"] += 1
                fs = bl["fecha_salida"] or bl["fecha_rendicion"]
                if fs:
                    per = f"{[k for k, v in _PL_MESES.items() if v == int(fs[5:7])][0].title()} {fs[:4]}"
                    if per not in info["periodos"]:
                        info["periodos"].append(per)
                if fs:
                    info["desde"] = min(info["desde"] or fs, fs)
                    info["hasta"] = max(info["hasta"] or fs, fs)
                origen = _pl_origen(bl)
                if origen in ya or origen in vistos:
                    info["repetidas"] += 1
                    continue
                vistos.add(origen)
                viaje, movs = _pl_a_rendicion(bl)
                gastos = [m for m in movs if m["tipo"] == "gasto"]
                info["nuevas"] += 1
                info["gastos"] += len(gastos)
                info["ingreso"] += round(viaje["ingreso"] or 0)
                info["costo"] += round(sum(m["monto"] * (m.get("cotizacion") or 0 if m["moneda"] != "GS" else 1)
                                           for m in gastos))
                if not bl["fecha_rendicion"]:
                    resumen["sin_fecha_rendicion"] += 1
                if any(m["moneda"] != "GS" and not m.get("cotizacion") for m in movs):
                    resumen["sin_cotizacion"] += 1
                if probar:
                    continue
                # Cargar
                completa = bool(bl["fecha_rendicion"])
                v = _limpiar_viaje(viaje)
                v.update(origen=origen, creado_por=f"{usuario} (planilla)", creado_el=_ahora(),
                         estado="saldada" if completa else "abierta")
                if completa:
                    f = bl["fecha_rendicion"]
                    v.update(presentado_por="Planilla", presentado_el=f, aprobado_por="Planilla", aprobado_el=f,
                             saldado_por="Planilla", saldado_el=f, saldo_forma="Rendida en la planilla")
                campos = list(v.keys())
                cur = conn.execute(f"INSERT INTO turismo_rendiciones ({', '.join(campos)}) VALUES ({', '.join('?' * len(campos))})",
                                   list(v.values()))
                rid = cur.lastrowid or conn.execute("SELECT MAX(id) AS m FROM turismo_rendiciones").fetchone()["m"]
                for m in movs:
                    _insertar_mov(conn, rid, m, f"{usuario} (planilla)", planilla=True)
                if completa:
                    a, g, sal, _ad = _cuentas(_movs(conn, rid), v.get("descuentos"))
                    conn.execute("UPDATE turismo_rendiciones SET saldo_final=? WHERE id=?", (sal, rid))
                resumen["importadas"] += 1
            resumen["nuevas"] += info["nuevas"]
            resumen["repetidas"] += info["repetidas"]
            resumen["gastos"] += info["gastos"]
            resumen["archivos"].append(info)
        if not probar:
            conn.commit()
    finally:
        conn.close()
    resumen["archivos"].sort(key=lambda a: a["desde"] or "9")
    return resumen


# ════════════════════════════════════════════════════════════════════════════
# PDF (para firmar)
# ════════════════════════════════════════════════════════════════════════════

def _gs(v):
    v = round(float(v or 0))
    s = f"{abs(v):,}".replace(",", ".")
    return f"{'- ' if v < 0 else ''}Gs. {s}"


def _f(d):
    d = _fecha(d)
    return f"{d[8:10]}/{d[5:7]}/{d[2:4]}" if d else "—"


def _n(v, dec=2):
    """1234.5 → '1.234,5' (sin ceros de más)."""
    txt = f"{float(v or 0):,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if dec:
        txt = txt.rstrip("0").rstrip(",")
    return txt


def _cot(v):
    """La cotización: con decimales si es chica (el peso argentino), redonda si no."""
    v = float(v or 0)
    return _n(v, 2) if v < 100 else _n(v, 0)


def _monto_original(m):
    if (m.get("moneda") or "GS") == "GS":
        return _gs(m["monto"])
    mon = MONEDAS.get(m["moneda"], m["moneda"])
    if not float(m.get("cotizacion") or 0):
        return f"{mon} {_n(m['monto'])} (sin cotización)"
    return f"{mon} {_n(m['monto'])} × {_cot(m['cotizacion'])}"


def _dif(v):
    v = round(float(v or 0))
    if not v:
        return "Gs. 0"
    return f"{'+' if v > 0 else '-'} Gs. {abs(v):,}".replace(",", ".")


def generar_pdf(d):
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import (BaseDocTemplate, PageTemplate, Frame, NextPageTemplate, Paragraph, Spacer,
                                    Table, TableStyle, KeepTogether)
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER
    try:
        from trafico_pdf import _fuentes, _LOGO
        F = _fuentes()
    except Exception:
        F = {"D9": "Helvetica-Bold", "D8": "Helvetica-Bold", "D6": "Helvetica-Bold", "D5": "Helvetica",
             "I4": "Helvetica", "I5": "Helvetica", "I6": "Helvetica-Bold", "I7": "Helvetica-Bold"}
        _LOGO = None
    NAVY, AZUL, ROJO = HexColor("#1D344E"), HexColor("#1E5A96"), HexColor("#DC2641")
    VERDE, GRIS, LINEA = HexColor("#2F7C46"), HexColor("#5B6B7F"), HexColor("#E1E6ED")
    FONDO, TINTA, CEL = HexColor("#F4F6F9"), HexColor("#16202C"), HexColor("#8CBDEB")
    CLARO = HexColor("#C9D7E6")
    W, H = A4
    M = 32
    ANCHO = W - 2 * M
    buf = io.BytesIO()

    def st(nombre, f=None, s=9, l=None, c=TINTA, **k):
        return ParagraphStyle(nombre, fontName=f or F["I4"], fontSize=s, leading=l or round(s * 1.3, 1),
                              textColor=c, **k)

    sTit = st("tit", f=F["D8"], s=12.5, l=15, c=NAVY, spaceBefore=12, spaceAfter=6, keepWithNext=1)
    sCel = st("cel", s=8.6, l=10.5)
    sCelB = st("celb", f=F["I6"], s=8.6, l=10.5)
    sNum = st("num", f=F["I6"], s=8.6, l=10.5, alignment=TA_RIGHT)
    sNumG = st("numg", s=8, l=10, alignment=TA_RIGHT, c=GRIS)
    sCab = st("cab", f=F["I7"], s=7.2, l=9, c=white)
    sCabR = st("cabr", f=F["I7"], s=7.2, l=9, c=white, alignment=TA_RIGHT)
    sNota = st("nota", s=7.5, c=GRIS, spaceBefore=4)

    saldo = d["saldo_ref"] if d["estado"] in ("aprobada", "saldada") else d["saldo"]
    ahora = _ahora()

    def flecha(c, x, y, largo):
        """Una flecha dibujada (las fuentes no siempre traen el carácter)."""
        c.setLineWidth(1.3)
        c.line(x, y, x + largo - 4, y)
        p = c.beginPath()
        p.moveTo(x + largo, y)
        p.lineTo(x + largo - 5.5, y + 3.4)
        p.lineTo(x + largo - 5.5, y - 3.4)
        p.close()
        c.drawPath(p, stroke=0, fill=1)

    def ruta(c, derecha, y, fuente, tam, color):
        c.setFillColor(color)
        c.setStrokeColor(color)
        a = (d.get("salida") or "—").upper()[:30]
        b = (d.get("destino") or "—").upper()[:30]
        wb = c.stringWidth(b, fuente, tam)
        wa = c.stringWidth(a, fuente, tam)
        c.setFont(fuente, tam)
        c.drawRightString(derecha, y, b)
        xf = derecha - wb - 30
        flecha(c, xf + 6, y + tam * 0.32, 18)
        c.drawRightString(xf, y, a)
        return derecha - wb - 30 - wa

    def pie(c, doc):
        c.setFillColor(GRIS)
        c.setFont(F["I5"], 7)
        c.drawString(M, 22, f"La Santaniana · Rendición #{d['id']} · generada el {_f(ahora)} {ahora[11:16]}")
        c.drawRightString(W - M, 22, f"Hoja {doc.page}")

    def franja(c, y):
        c.setFillColor(ROJO)
        c.rect(0, y - 4, W * 0.42, 4, stroke=0, fill=1)
        c.setFillColor(AZUL)
        c.rect(W * 0.42, y - 4, W * 0.58, 4, stroke=0, fill=1)

    def primera(c, doc):
        c.saveState()
        alto = 128
        c.setFillColor(NAVY)
        c.rect(0, H - alto, W, alto, stroke=0, fill=1)
        franja(c, H - alto)
        x = M
        if _LOGO:
            try:
                c.setFillColor(white)
                c.roundRect(M, H - 86, 54, 54, 12, stroke=0, fill=1)
                c.drawImage(_LOGO, M + 7, H - 79, 40, 40, mask="auto", preserveAspectRatio=True)
                x = M + 70
            except Exception:
                x = M
        c.setFillColor(CEL)
        c.setFont(F["I6"], 7.5)
        c.drawString(x, H - 44, "LA SANTANIANA  ·  TURISMO")
        c.setFillColor(white)
        c.setFont(F["D9"], 22)
        c.drawString(x, H - 68, "RENDICIÓN DE VIAJE")
        c.setFont(F["I5"], 9)
        c.setFillColor(CLARO)
        sub = " · ".join(z for z in (d.get("agenda_ot") and f"OT {d['agenda_ot']}", f"Rendición #{d['id']}",
                                     d.get("cliente")) if z)
        c.drawString(x, H - 84, sub[:80])
        # Estado arriba a la derecha
        etq = d["estado_txt"].upper()
        c.setFont(F["D8"], 9)
        ancho = c.stringWidth(etq, F["D8"], 9) + 20
        color = {"saldada": VERDE, "aprobada": AZUL, "presentada": HexColor("#B26A00")}.get(d["estado"], GRIS)
        c.setFillColor(color)
        c.roundRect(W - M - ancho, H - 52, ancho, 18, 9, stroke=0, fill=1)
        c.setFillColor(white)
        c.drawCentredString(W - M - ancho / 2, H - 46, etq)
        # Ruta y fechas
        ruta(c, W - M, H - 77, F["D8"], 12.5, white)
        c.setFont(F["I5"], 8.5)
        c.setFillColor(CLARO)
        dias = d["dias"]
        fechas = f"{_f(d.get('fecha_salida'))} al {_f(d.get('fecha_regreso') or d.get('fecha_salida'))} · {dias} día{'s' if dias != 1 else ''}"
        c.drawRightString(W - M, H - 93, fechas)
        choferes = " y ".join(z for z in (d.get("chofer"), d.get("chofer2")) if z)
        datos = " · ".join(z for z in (d.get("coche") and f"Coche {d['coche']}",
                                       choferes and (f"Choferes: {choferes}" if d.get("chofer2") else f"Rinde: {choferes}"),
                                       d.get("km_recorridos") and f"{_n(d['km_recorridos'], 0)} km",
                                       d.get("pasajeros") and f"{d['pasajeros']} pasajeros") if z)
        c.drawString(M, H - 113, datos[:110])
        pie(c, doc)
        c.restoreState()

    def resto(c, doc):
        c.saveState()
        alto = 46
        c.setFillColor(NAVY)
        c.rect(0, H - alto, W, alto, stroke=0, fill=1)
        franja(c, H - alto)
        c.setFillColor(white)
        c.setFont(F["D8"], 12.5)
        c.drawString(M, H - 28, f"RENDICIÓN #{d['id']}" + (f"  ·  OT {d['agenda_ot']}" if d.get("agenda_ot") else ""))
        ruta(c, W - M, H - 28, F["D6"], 10.5, CLARO)
        pie(c, doc)
        c.restoreState()

    def tabla(filas, anchos, cab, total=None, zebra=True):
        t = Table([cab] + filas + ([total] if total else []), colWidths=anchos, repeatRows=1)
        estilo = [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                  ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                  ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                  ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINEA)]
        if zebra:
            for i in range(1, len(filas) + 1):
                if i % 2 == 0:
                    estilo.append(("BACKGROUND", (0, i), (-1, i), FONDO))
        if total:
            estilo += [("LINEABOVE", (0, -1), (-1, -1), 1.2, NAVY), ("BACKGROUND", (0, -1), (-1, -1), HexColor("#EAF1F8"))]
        t.setStyle(TableStyle(estilo))
        return t

    el = [NextPageTemplate("resto")]
    # Las tres cajas: anticipos, gastos, saldo
    if d["estado"] == "abierta":          # todavía se está cargando: la cuenta es provisoria
        if saldo > 0:
            msg, col_s = f"Hasta ahora, el chofer devolvería {_gs(saldo)}", VERDE
        elif saldo < 0:
            msg, col_s = f"Hasta ahora, habría que pagarle al chofer {_gs(-saldo)}", ROJO
        else:
            msg, col_s = "Hasta ahora, cierra justo", NAVY
    elif d["estado"] == "saldada":
        msg, col_s = ((f"El chofer devolvió {_gs(saldo)}", VERDE) if saldo > 0 else
                      (f"Se le pagó al chofer {_gs(-saldo)}", ROJO) if saldo < 0 else ("Cerró justo", NAVY))
    elif saldo > 0:
        msg, col_s = f"El chofer devuelve {_gs(saldo)}", VERDE
    elif saldo < 0:
        msg, col_s = f"Hay que pagarle al chofer {_gs(-saldo)}", ROJO
    else:
        msg, col_s = "Cierra justo: no hay nada que devolver ni pagar", NAVY

    def caja(t, v, c, sub):
        return [Paragraph(t, st("ct" + t, f=F["I6"], s=7.5, c=GRIS)),
                Paragraph(v, st("cv" + t, f=F["D8"], s=17, l=21, c=c)),
                Paragraph(sub, st("cs" + t, s=7.5, l=9.5, c=GRIS))]
    n_g = len(d["gastos_lista"])
    cajas = Table([[caja("ANTICIPOS", _gs(d["anticipos"]), NAVY,
                         f"{len(d['anticipos_lista'])} entrega{'s' if len(d['anticipos_lista']) != 1 else ''}"),
                    caja("GASTOS DEL CHOFER" if d.get("gastos_admin") else "GASTOS", _gs(d["gastos"]), NAVY,
                         f"{n_g} comprobante{'s' if n_g != 1 else ''}" + (f" · {_n(d['litros'], 1)} L de combustible" if d["litros"] else "")),
                    caja("SALDO", _gs(abs(saldo)) if saldo else "Gs. 0", col_s,
                         "devuelve el chofer" if saldo > 0 else "se le debe al chofer" if saldo < 0 else "cierra justo")]],
                  colWidths=[ANCHO / 3] * 3)
    cajas.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), FONDO), ("BOX", (0, 0), (-1, -1), 0.6, LINEA),
                               ("LINEAFTER", (0, 0), (1, 0), 0.6, LINEA), ("TOPPADDING", (0, 0), (-1, -1), 8),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 9), ("LEFTPADDING", (0, 0), (-1, -1), 12),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    el += [cajas, Spacer(1, 7), Paragraph(msg, st("msg", f=F["D8"], s=12, l=15, c=col_s, alignment=TA_CENTER))]
    monedas = d.get("saldos_moneda") or []
    if any(x["moneda"] != "GS" for x in monedas):
        partes = []
        for x in monedas:
            v = _gs(abs(x["saldo"])) if x["moneda"] == "GS" else f"{x['simbolo']} {_n(abs(x['saldo']))}"
            que = "devuelve" if x["saldo"] > 0 else "se le debe" if x["saldo"] < 0 else "justo"
            partes.append(f"{'Guaraníes' if x['moneda'] == 'GS' else x['simbolo']}: {que}{' ' + v if x['saldo'] else ''}")
        el.append(Paragraph("En cada moneda — " + " · ".join(partes), st("mon", f=F["I6"], s=8.6, c=TINTA, alignment=TA_CENTER, spaceBefore=3)))
    if d.get("gastos_admin"):
        el.append(Paragraph(f"Pagado directo por administración: {_gs(d['gastos_admin'])} (no entra en la cuenta del chofer) · "
                            f"Costo total del viaje: {_gs(d['costo_total'])}", st("adm", s=8, c=GRIS, alignment=TA_CENTER, spaceBefore=2)))
    if d["estado"] == "saldada" and d.get("saldo_forma"):
        el.append(Paragraph(f"Saldado: {d['saldo_forma']}{' · ' + d['saldo_nota'] if d.get('saldo_nota') else ''}"
                            f" · {_f(d.get('saldado_el'))}{' · ' + d['saldado_por'] if d.get('saldado_por') not in (None, '', 'Planilla') else ''}",
                            st("sald", s=8, c=GRIS, alignment=TA_CENTER)))

    # Anticipos
    el.append(Paragraph("Anticipos entregados", sTit))
    ant = d["anticipos_lista"]
    if ant:
        el.append(tabla([[Paragraph(_f(m["fecha"]), sCel), Paragraph(m["detalle"] or "Anticipo", sCel),
                          Paragraph(_monto_original(m) if m["moneda"] != "GS" else "", sNumG),
                          Paragraph(_gs(m["monto_gs"]), sNum)] for m in ant],
                        [57, 251, 130, ANCHO - 438],
                        [Paragraph("FECHA", sCab), Paragraph("DETALLE", sCab), Paragraph("MONEDA", sCabR),
                         Paragraph("GUARANÍES", sCabR)],
                        [Paragraph("", sCel), Paragraph("Total anticipos", sCelB), Paragraph("", sCel),
                         Paragraph(_gs(d["anticipos"]), sNum)]))
    else:
        el.append(Paragraph("No se cargó ningún anticipo.", st("na", s=8.5, c=GRIS)))

    # Detalle (lo que el chofer rinde, comprobante por comprobante)
    el.append(Paragraph("Detalle de los gastos", sTit))
    gl = d["gastos_lista"]
    if gl:
        el.append(tabla([[Paragraph(_f(m["fecha"]), sCel),
                          Paragraph(m["categoria_nombre"] + (" <font size=6.5 color='#8A5A00'>ADM.</font>" if m.get("pagado_por") == "administracion" else ""), sCelB),
                          Paragraph(" · ".join(z for z in (m["detalle"], m["comprobante"] and f"Comp. {m['comprobante']}",
                                                           m["litros"] and f"{_n(m['litros'], 1)} L") if z), sCel),
                          Paragraph(_monto_original(m) if m["moneda"] != "GS" else "", sNumG),
                          Paragraph(_gs(m["monto_gs"]) if m["monto_gs"] else "—", sNum)] for m in gl],
                        [57, 122, 175, 100, ANCHO - 454],
                        [Paragraph("FECHA", sCab), Paragraph("RUBRO", sCab), Paragraph("DETALLE", sCab),
                         Paragraph("MONEDA", sCabR), Paragraph("GUARANÍES", sCabR)],
                        [Paragraph("", sCel), Paragraph("Total gastos", sCelB),
                         Paragraph(f"Chofer {_gs(d['gastos'])} · administración {_gs(d['gastos_admin'])}" if d.get("gastos_admin") else "", sNumG),
                         Paragraph("", sCel), Paragraph(_gs(d["costo_total"]), sNum)]))
    else:
        el.append(Paragraph("Todavía no hay gastos cargados.", st("ng", s=8.5, c=GRIS)))

    # Por rubro
    if d["por_categoria"]:
        el.append(Paragraph("Gastos por rubro", sTit))
        tot = d["costo_total"] or 1
        el.append(tabla([[Paragraph(c["nombre"], sCelB), Paragraph(str(c["n"]), sNumG),
                          Paragraph(f"{_n(c['litros'], 1)} L" if c["litros"] else "", sNumG),
                          Paragraph(f"{c['total'] / tot * 100:.0f}%", sNumG), Paragraph(_gs(c["total"]), sNum)]
                         for c in d["por_categoria"]],
                        [200, 70, 80, 60, ANCHO - 410],
                        [Paragraph("RUBRO", sCab), Paragraph("COMPROB.", sCabR), Paragraph("LITROS", sCabR),
                         Paragraph("%", sCabR), Paragraph("GUARANÍES", sCabR)],
                        [Paragraph("Total gastos", sCelB), Paragraph(str(n_g), sNumG),
                         Paragraph(f"{_n(d['litros'], 1)} L" if d["litros"] else "", sNumG),
                         Paragraph("100%", sNumG), Paragraph(_gs(d["costo_total"]), sNum)]))

    # Presupuesto contra real
    comp = d.get("comparacion")
    if comp and comp["filas"]:
        el.append(Paragraph(f"Presupuestado contra gastado · presupuesto #{comp['presupuesto_id']}"
                            + (f" ({comp['destino']})" if comp.get("destino") else ""), sTit))
        filas = []
        for f in comp["filas"]:
            dif = f["diferencia"]
            col = ROJO if dif > 0 else VERDE if dif < 0 else GRIS
            filas.append([Paragraph(f["nombre"], sCel), Paragraph(_gs(f["presupuestado"]), sNum),
                          Paragraph(_gs(f["real"]), sNum),
                          Paragraph(_dif(dif) + (f" ({f['pct']:+.0f}%)" if f["pct"] is not None else ""),
                                    st("df" + f["clave"], f=F["I6"], s=8.6, l=10.5, c=col, alignment=TA_RIGHT))])
        dif = comp["diferencia"]
        el.append(tabla(filas, [190, 110, 110, ANCHO - 410],
                        [Paragraph("RUBRO", sCab), Paragraph("PRESUPUESTADO", sCabR), Paragraph("GASTADO", sCabR),
                         Paragraph("DIFERENCIA", sCabR)],
                        [Paragraph("Total", sCelB), Paragraph(_gs(comp["total_presupuestado"]), sNum),
                         Paragraph(_gs(comp["total_real"]), sNum),
                         Paragraph(_dif(dif) + (f" ({comp['pct']:+.0f}%)" if comp.get("pct") is not None else ""),
                                   st("dft", f=F["I7"], s=8.6, l=10.5,
                                      c=ROJO if dif > 0 else VERDE if dif < 0 else GRIS, alignment=TA_RIGHT))]))
        el.append(Paragraph("Solo se comparan los rubros que se rinden (no el jornal, las cubiertas ni el mantenimiento). "
                            "En rojo, lo que se gastó de más.", sNota))

    if d.get("observaciones"):
        el += [Paragraph("Observaciones", sTit), Paragraph(d["observaciones"], sCel)]

    # Firmas: tres rayas separadas
    hueco = 22
    col = (ANCHO - 2 * hueco) / 3
    fs = lambda t, n: Paragraph(t, st("f" + n, f=F["I6"], s=8, alignment=TA_CENTER))
    fsub = lambda t, n: Paragraph(t, st("fs" + n, s=7, c=GRIS, alignment=TA_CENTER))
    firmas = Table([["", "", "", "", ""],
                    [fs(d.get("chofer") or "Chofer", "1"), "", fs("Encargado de turismo", "2"), "", fs("Administración", "3")],
                    [fsub("Recibí el anticipo y rindo estos gastos", "1"), "", fsub("Controló los comprobantes", "2"), "",
                     fsub("Aprobó", "3")]],
                   colWidths=[col, hueco, col, hueco, col], rowHeights=[42, 14, 12])
    firmas.setStyle(TableStyle([("LINEABOVE", (0, 1), (0, 1), 0.8, TINTA), ("LINEABOVE", (2, 1), (2, 1), 0.8, TINTA),
                                ("LINEABOVE", (4, 1), (4, 1), 0.8, TINTA), ("TOPPADDING", (0, 1), (-1, -1), 3),
                                ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    el += [Spacer(1, 14), KeepTogether([firmas])]

    doc = BaseDocTemplate(buf, pagesize=A4, leftMargin=M, rightMargin=M, topMargin=150, bottomMargin=40,
                          title=f"Rendición #{d['id']}", author="La Santaniana")
    doc.addPageTemplates([
        PageTemplate("primera", frames=[Frame(M, 40, ANCHO, H - 150 - 40, id="f1", leftPadding=0, rightPadding=0,
                                              topPadding=0, bottomPadding=0)], onPage=primera),
        PageTemplate("resto", frames=[Frame(M, 40, ANCHO, H - 70 - 40, id="f2", leftPadding=0, rightPadding=0,
                                            topPadding=0, bottomPadding=0)], onPage=resto),
    ])
    doc.build(el)
    return buf.getvalue()


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
                            accion=accion, categoria="Turismo", detalle=str(detalle)[:200])
    except Exception:
        pass


def _no():
    return jsonify({"ok": False, "msg": "Sin permiso"}), 403


@bp_rendiciones.route("/api/turismo/rendiciones", methods=["GET"])
def api_lista():
    if not _puede_ver():
        return _no()
    a = request.args
    r = lista(a.get("estado", ""), a.get("q", "").strip(), _fecha(a.get("desde")), _fecha(a.get("hasta")))
    r.update(categorias=[CAT[k] for k, _, _ in CATEGORIAS], monedas=MONEDAS,
             puede_cargar=_puede_cargar(), es_admin=_es_admin())
    return jsonify(r)


@bp_rendiciones.route("/api/turismo/rendiciones/viajes", methods=["GET"])
def api_viajes():
    if not _puede_ver():
        return _no()
    return jsonify(viajes_agenda(request.args.get("q", "").strip()))


@bp_rendiciones.route("/api/turismo/rendiciones/presupuestos", methods=["GET"])
def api_presupuestos():
    if not _puede_ver():
        return _no()
    return jsonify(presupuestos_para_vincular(request.args.get("q", "").strip()))


@bp_rendiciones.route("/api/turismo/rendiciones/cotizaciones", methods=["GET"])
def api_cotizaciones():
    if not _puede_ver():
        return _no()
    return jsonify(cotizaciones())


@bp_rendiciones.route("/api/turismo/rendiciones", methods=["POST"])
def api_crear():
    if not _puede_cargar():
        return _no()
    ok, res = crear(request.json or {}, _quien())
    if not ok:
        return jsonify({"ok": False, "msg": res}), 400
    _auditar(f"Abrió la rendición de turismo #{res}")
    return jsonify({"ok": True, "id": res, "rendicion": detalle(res)})


def _respuesta(rid, **extra):
    d = detalle(rid)
    if not d:
        return jsonify({"ok": False, "msg": "La rendición no existe."}), 404
    return jsonify({"ok": True, **extra, "rendicion": d, "es_admin": _es_admin(), "puede_cargar": _puede_cargar()})


@bp_rendiciones.route("/api/turismo/rendiciones/<int:rid>", methods=["GET"])
def api_detalle(rid):
    if not _puede_ver():
        return _no()
    r = _respuesta(rid)
    return r


@bp_rendiciones.route("/api/turismo/rendiciones/<int:rid>", methods=["PATCH"])
def api_editar(rid):
    if not _puede_cargar():
        return _no()
    ok, msg = editar_viaje(rid, request.json or {})
    if not ok:
        return jsonify({"ok": False, "msg": msg}), 400
    return _respuesta(rid, msg=msg)


@bp_rendiciones.route("/api/turismo/rendiciones/<int:rid>", methods=["DELETE"])
def api_borrar(rid):
    if not _es_admin():
        return jsonify({"ok": False, "msg": "Solo la administración puede borrar una rendición."}), 403
    d = detalle(rid)
    if not d:
        return jsonify({"ok": False, "msg": "La rendición no existe."}), 404
    borrar(rid)
    _auditar(f"Borró la rendición de turismo #{rid}",
             f"{d.get('cliente')} · {d.get('destino')} · anticipos {_gs(d['anticipos'])} · gastos {_gs(d['gastos'])}")
    return jsonify({"ok": True})


@bp_rendiciones.route("/api/turismo/rendiciones/<int:rid>/movs", methods=["POST"])
def api_agregar_mov(rid):
    if not _puede_cargar():
        return _no()
    ok, res = agregar_mov(rid, request.json or {}, _quien())
    if not ok:
        return jsonify({"ok": False, "msg": res}), 400
    return _respuesta(rid, mov_id=res)


@bp_rendiciones.route("/api/turismo/rendiciones/movs/<int:mid>", methods=["PATCH", "DELETE"])
def api_mov(mid):
    if not _puede_cargar():
        return _no()
    ok, res = borrar_mov(mid) if request.method == "DELETE" else editar_mov(mid, request.json or {})
    if not ok:
        return jsonify({"ok": False, "msg": res}), 400
    return _respuesta(res)


@bp_rendiciones.route("/api/turismo/rendiciones/<int:rid>/estado", methods=["POST"])
def api_estado(rid):
    if not _puede_cargar():
        return _no()
    d = request.json or {}
    accion = d.get("accion", "")
    ok, msg = cambiar_estado(rid, accion, _quien(), _es_admin(), d)
    if not ok:
        return jsonify({"ok": False, "msg": msg}), 400
    _auditar({"presentar": "Presentó", "aprobar": "Aprobó", "devolver": "Devolvió para corregir",
              "saldar": "Saldó", "reabrir": "Reabrió"}.get(accion, accion) + f" la rendición de turismo #{rid}",
             d.get("motivo") or d.get("forma") or "")
    return _respuesta(rid, msg=msg)


@bp_rendiciones.route("/api/turismo/rendiciones/importar", methods=["POST"])
def api_importar():
    """Carga las planillas de Excel de rendición de turismo. Con ?probar=1 solo
    dice qué va a entrar, sin cargar nada."""
    if not _puede_cargar():
        return _no()
    archivos = [(f.filename or "planilla.xlsx", f.read()) for f in request.files.getlist("archivos")]
    archivos = [(n, d) for n, d in archivos if d]
    if not archivos:
        return jsonify({"ok": False, "msg": "Elegí al menos una planilla de Excel."}), 400
    probar = request.args.get("probar") == "1"
    res = importar_planillas(archivos, _quien(), probar=probar)
    if not probar and res["importadas"]:
        _auditar(f"Cargó {res['importadas']} rendiciones de turismo desde planillas",
                 ", ".join(a["nombre"] for a in res["archivos"]))
    return jsonify({"ok": True, "probar": probar, **res})


@bp_rendiciones.route("/api/turismo/rendiciones/<int:rid>/pdf", methods=["GET"])
def api_pdf(rid):
    if not _puede_ver():
        return _no()
    d = detalle(rid)
    if not d:
        return jsonify({"error": "No existe"}), 404
    pdf = generar_pdf(d)
    nombre = f"Rendicion-{rid}" + (f"-{d['agenda_ot'].replace(' ', '')}" if d.get("agenda_ot") else "") + ".pdf"
    return send_file(io.BytesIO(pdf), mimetype="application/pdf",
                     as_attachment=request.args.get("descargar") == "1", download_name=nombre)
