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

# (clave, nombre, ícono). El orden es el de la pantalla.
CATEGORIAS = [
    ("combustible", "Combustible", "gas-station"),
    ("combustible_ext", "Combustible en el exterior", "world"),
    ("peajes", "Peajes", "road"),
    ("comida", "Comida / viáticos", "tools-kitchen-2"),
    ("hotel", "Hotel / estadía", "bed"),
    ("estacionamiento", "Estacionamiento", "parking"),
    ("lavado", "Lavado", "droplets"),
    ("dinatran", "DINATRAN", "building-bank"),
    ("carta_azul", "Carta azul", "file-certificate"),
    ("otros", "Otros", "dots"),
]
CAT = {k: {"clave": k, "nombre": n, "icono": i} for k, n, i in CATEGORIAS}

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
    ("peajes", "Peajes", ("peajes",), ("peajes", "peajes_exterior")),
    ("comida", "Comida y viáticos", ("comida",), ("costo_viaticos", "costo_comidas")),
    ("hotel", "Hotel / estadía", ("hotel",), ("costo_hospedaje",)),
    ("tramites", "Trámites (DINATRAN, carta azul)", ("dinatran", "carta_azul"), ("tramites", "seguro_viaje")),
    ("otros", "Otros (estacionamiento, lavado…)", ("estacionamiento", "lavado", "otros"), ("otros",)),
]


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
    conn.close()


# ════════════════════════════════════════════════════════════════════════════
# VIAJES DE LA AGENDA
# ════════════════════════════════════════════════════════════════════════════

def viajes_agenda(q="", dias_atras=75, dias_adelante=30):
    """Los viajes de la agenda para armar una rendición: la ida y la vuelta
    con el mismo número de orden van juntas. Los que ya tienen rendición
    vienen marcados."""
    hoy = date.fromisoformat(_hoy())
    desde = (hoy - timedelta(days=dias_atras)).isoformat()
    hasta = (hoy + timedelta(days=dias_adelante)).isoformat()
    conn = get_connection()
    try:
        filas = [dict(r) for r in conn.execute(
            """SELECT * FROM agenda_turismo WHERE fecha >= ? AND fecha <= ? AND COALESCE(estado,'') <> 'cancelado'
               ORDER BY fecha, hora, id""", (desde, hasta)).fetchall()]
        ya = conn.execute("SELECT id, agenda_ot, agenda_ids FROM turismo_rendiciones").fetchall()
    except Exception:
        filas, ya = [], []
    finally:
        conn.close()
    con_rend_ot = {r["agenda_ot"]: r["id"] for r in ya if r["agenda_ot"]}
    con_rend_id = {}
    for r in ya:
        for x in str(r["agenda_ids"] or "").split(","):
            if x.strip().isdigit():
                con_rend_id[int(x)] = r["id"]
    grupos = {}
    for f in filas:
        clave = ("OT", f["ot_nr"]) if (f.get("ot_nr") or "").strip() else ("ID", f["id"])
        g = grupos.setdefault(clave, {"ot_nr": f.get("ot_nr") or "", "ids": [], "servicios": []})
        g["ids"].append(f["id"])
        g["servicios"].append(f)
    salida = []
    for g in grupos.values():
        sv = g["servicios"]
        primero = sv[0]
        coche = next((s["coche_interno"] for s in sv if (s.get("coche_interno") or "").strip()), "")
        trip = next((s["tripulacion"] for s in sv if (s.get("tripulacion") or "").strip()), "")
        rend = con_rend_ot.get(g["ot_nr"]) if g["ot_nr"] else None
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


def _cuentas(movs):
    anticipos = sum(float(m["monto_gs"] or 0) for m in movs if m["tipo"] == "anticipo")
    gastos = sum(float(m["monto_gs"] or 0) for m in movs if m["tipo"] == "gasto")
    return round(anticipos), round(gastos), round(anticipos - gastos)


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
        t = tot.setdefault(c, {**CAT[c], "total": 0.0, "n": 0, "litros": 0.0})
        t["total"] += float(m["monto_gs"] or 0)
        t["n"] += 1
        t["litros"] += float(m["litros"] or 0)
    lista = sorted(tot.values(), key=lambda t: -t["total"])
    for t in lista:
        t["total"] = round(t["total"])
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


def _resumen_fila(r, anticipos, gastos, saldo):
    estado = r["estado"] or "abierta"
    if estado in ("aprobada", "saldada"):
        saldo_ref = round(float(r.get("saldo_final") or 0))
    else:
        saldo_ref = saldo
    return {**r, "anticipos": anticipos, "gastos": gastos, "saldo": saldo, "saldo_ref": saldo_ref,
            "dias": _dias(r), "estado_txt": ESTADOS.get(estado, estado)}


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
    anticipos, gastos, saldo = _cuentas(movs)
    d = _resumen_fila(r, anticipos, gastos, saldo)
    for m in movs:
        m["categoria_nombre"] = CAT.get(m["categoria"], {}).get("nombre", "") if m["tipo"] == "gasto" else ""
        m["icono"] = CAT.get(m["categoria"], {}).get("icono", "cash") if m["tipo"] == "gasto" else "cash"
    d["anticipos_lista"] = [m for m in movs if m["tipo"] == "anticipo"]
    d["gastos_lista"] = [m for m in movs if m["tipo"] == "gasto"]
    d["por_categoria"] = _por_categoria(movs)
    d["comparacion"] = comp
    litros = sum(float(m["litros"] or 0) for m in movs if m["tipo"] == "gasto")
    d["litros"] = round(litros, 1)
    d["gasto_por_dia"] = round(gastos / d["dias"]) if d["dias"] else 0
    d["editable"] = (r["estado"] or "abierta") == "abierta"
    return d


def lista(estado="", q="", desde="", hasta=""):
    conn = get_connection()
    try:
        filas = [dict(r) for r in conn.execute(
            "SELECT * FROM turismo_rendiciones ORDER BY fecha_salida DESC, id DESC").fetchall()]
        sumas = {}
        for m in conn.execute("""SELECT rendicion_id, tipo, categoria, SUM(monto_gs) AS t, COUNT(*) AS n
                                 FROM turismo_rend_movs GROUP BY rendicion_id, tipo, categoria""").fetchall():
            s = sumas.setdefault(m["rendicion_id"], {"anticipo": 0.0, "gasto": 0.0, "cats": {}, "n": 0})
            s[m["tipo"]] = s.get(m["tipo"], 0) + float(m["t"] or 0)
            if m["tipo"] == "gasto":
                s["cats"][m["categoria"]] = s["cats"].get(m["categoria"], 0) + float(m["t"] or 0)
                s["n"] += int(m["n"] or 0)
    finally:
        conn.close()
    todas = []
    for r in filas:
        s = sumas.get(r["id"], {"anticipo": 0, "gasto": 0, "cats": {}, "n": 0})
        a, g = round(s["anticipo"]), round(s["gasto"])
        x = _resumen_fila(r, a, g, a - g)
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
                                              "tripulacion")).upper()
               or Q == f"#{x['id']}" or Q == str(x["id"])]

    # Lo gastado en los viajes que salieron en los últimos 90 días, por rubro
    hace90 = (date.fromisoformat(_hoy()) - timedelta(days=90)).isoformat()
    recientes = [x for x in todas if (x["fecha_salida"] or "") >= hace90 and x["gastos"]]
    cats = {}
    for x in recientes:
        for c, t in x["cats"].items():
            cats[c] = cats.get(c, 0) + t
    gastado_90 = sum(x["gastos"] for x in recientes)
    resumen["gastado_90"] = gastado_90
    resumen["viajes_90"] = len(recientes)
    resumen["promedio_viaje_90"] = round(gastado_90 / len(recientes)) if recientes else 0
    dias90 = sum(x["dias"] for x in recientes)
    resumen["por_dia_90"] = round(gastado_90 / dias90) if dias90 else 0
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
                "tripulacion", "pasajeros", "observaciones", "presupuesto_id", "agenda_ot")


def _limpiar_viaje(d):
    out = {}
    for k in CAMPOS_VIAJE:
        if k not in d:
            continue
        v = d.get(k)
        if k in ("fecha_salida", "fecha_regreso"):
            out[k] = _fecha(v)
        elif k == "pasajeros":
            out[k] = int(_num(v))
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
                     "tripulacion": trip, "chofer": _primer_nombre(trip),
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
        if r["estado"] != "abierta" and set(campos) - {"presupuesto_id", "observaciones"}:
            return False, "La rendición ya se presentó: para corregir, la administración la tiene que reabrir."
        conn.execute(f"UPDATE turismo_rendiciones SET {', '.join(k + '=?' for k in campos)} WHERE id=?",
                     list(campos.values()) + [rid])
        conn.commit()
        return True, "Viaje actualizado."
    finally:
        conn.close()


def _valores_mov(d):
    tipo = d.get("tipo") if d.get("tipo") in ("anticipo", "gasto") else "gasto"
    moneda = str(d.get("moneda") or "GS").upper()
    moneda = moneda if moneda in MONEDAS else "GS"
    monto = round(_num(d.get("monto")), 2)
    cot = 1.0 if moneda == "GS" else round(_num(d.get("cotizacion")), 4)
    if monto <= 0:
        return None, "Poné el monto."
    if moneda != "GS" and cot <= 0:
        return None, f"Poné la cotización del {MONEDAS[moneda]} (cuántos guaraníes vale cada uno)."
    cat = d.get("categoria") if d.get("categoria") in CAT else ("otros" if tipo == "gasto" else "")
    return {"tipo": tipo, "fecha": _fecha(d.get("fecha")) or _hoy(), "categoria": cat,
            "detalle": _txt(d.get("detalle"), False, 160), "monto": monto, "moneda": moneda, "cotizacion": cot,
            "monto_gs": round(monto * cot), "litros": round(_num(d.get("litros")), 2) if tipo == "gasto" else 0,
            "comprobante": _txt(d.get("comprobante"), True, 40)}, None


def _insertar_mov(conn, rid, d, usuario):
    v, err = _valores_mov(d)
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
                                       "litros", "comprobante") if k in d})
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
        anticipos, gastos, saldo = _cuentas(movs)
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
        datos = " · ".join(z for z in (d.get("coche") and f"Coche {d['coche']}", d.get("chofer") and f"Rinde: {d['chofer']}",
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
                    caja("GASTOS", _gs(d["gastos"]), NAVY,
                         f"{n_g} comprobante{'s' if n_g != 1 else ''}" + (f" · {_n(d['litros'], 1)} L de combustible" if d["litros"] else "")),
                    caja("SALDO", _gs(abs(saldo)) if saldo else "Gs. 0", col_s,
                         "devuelve el chofer" if saldo > 0 else "se le debe al chofer" if saldo < 0 else "cierra justo")]],
                  colWidths=[ANCHO / 3] * 3)
    cajas.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), FONDO), ("BOX", (0, 0), (-1, -1), 0.6, LINEA),
                               ("LINEAFTER", (0, 0), (1, 0), 0.6, LINEA), ("TOPPADDING", (0, 0), (-1, -1), 8),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 9), ("LEFTPADDING", (0, 0), (-1, -1), 12),
                               ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    el += [cajas, Spacer(1, 7), Paragraph(msg, st("msg", f=F["D8"], s=12, l=15, c=col_s, alignment=TA_CENTER))]
    if d["estado"] == "saldada" and d.get("saldo_forma"):
        el.append(Paragraph(f"Saldado: {d['saldo_forma']}{' · ' + d['saldo_nota'] if d.get('saldo_nota') else ''}"
                            f" · {_f(d.get('saldado_el'))}{' · ' + d['saldado_por'] if d.get('saldado_por') else ''}",
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
        el.append(tabla([[Paragraph(_f(m["fecha"]), sCel), Paragraph(m["categoria_nombre"], sCelB),
                          Paragraph(" · ".join(z for z in (m["detalle"], m["comprobante"] and f"Comp. {m['comprobante']}",
                                                           m["litros"] and f"{_n(m['litros'], 1)} L") if z), sCel),
                          Paragraph(_monto_original(m) if m["moneda"] != "GS" else "", sNumG),
                          Paragraph(_gs(m["monto_gs"]), sNum)] for m in gl],
                        [57, 122, 175, 100, ANCHO - 454],
                        [Paragraph("FECHA", sCab), Paragraph("RUBRO", sCab), Paragraph("DETALLE", sCab),
                         Paragraph("MONEDA", sCabR), Paragraph("GUARANÍES", sCabR)],
                        [Paragraph("", sCel), Paragraph("Total gastos", sCelB), Paragraph("", sCel), Paragraph("", sCel),
                         Paragraph(_gs(d["gastos"]), sNum)]))
    else:
        el.append(Paragraph("Todavía no hay gastos cargados.", st("ng", s=8.5, c=GRIS)))

    # Por rubro
    if d["por_categoria"]:
        el.append(Paragraph("Gastos por rubro", sTit))
        tot = d["gastos"] or 1
        el.append(tabla([[Paragraph(c["nombre"], sCelB), Paragraph(str(c["n"]), sNumG),
                          Paragraph(f"{_n(c['litros'], 1)} L" if c["litros"] else "", sNumG),
                          Paragraph(f"{c['total'] / tot * 100:.0f}%", sNumG), Paragraph(_gs(c["total"]), sNum)]
                         for c in d["por_categoria"]],
                        [200, 70, 80, 60, ANCHO - 410],
                        [Paragraph("RUBRO", sCab), Paragraph("COMPROB.", sCabR), Paragraph("LITROS", sCabR),
                         Paragraph("%", sCabR), Paragraph("GUARANÍES", sCabR)],
                        [Paragraph("Total gastos", sCelB), Paragraph(str(n_g), sNumG),
                         Paragraph(f"{_n(d['litros'], 1)} L" if d["litros"] else "", sNumG),
                         Paragraph("100%", sNumG), Paragraph(_gs(d["gastos"]), sNum)]))

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
