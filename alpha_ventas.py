"""
alpha_ventas.py — Las ventas de Alpha en la base, la caja y las liquidaciones
de las agencias (La Santaniana)

Hasta ahora las ventas de prueba quedaban en cada navegador. Con varias
agencias vendiendo hace falta que estén en un solo lugar: que un asiento
vendido por una agencia figure ocupado para todas, y que administración pueda
liquidarle a cada agencia lo que vendió.

Siguen siendo VENTAS DE PRUEBA, sin valor fiscal (falta lo fiscal). Por eso hay
un botón para borrarlas todas.

  alpha_ventas          cada boleto o reserva (el detalle va en "datos", JSON)
  alpha_movs            la plata: venta, cobro de reserva, diferencia por
                        cambio, devolución, anulación. De acá salen la caja y
                        las liquidaciones
  alpha_cierres         los cierres de caja de cada vendedor
  alpha_liquidaciones   lo que se le liquida a una agencia hasta un corte

El asiento se cuida por tramo: el 5 vendido de Asunción a Horqueta está libre
de Horqueta a Concepción. Cada venta guarda en qué parada sube y baja (su
posición en el recorrido de la salida) y el servidor no deja vender dos veces
el mismo asiento en tramos que se pisan.

Lo que ve cada uno:
  - administración: todo
  - una agencia: sus ventas, su caja; de las demás solo que el asiento está
    ocupado (sin nombre ni documento). No ve las liquidaciones.

La comisión de cada agencia sale de su contrato (Comercial → Agencias), el que
regía el día de la venta: porcentaje o monto por pasaje, y la comisión por
ruta si el contrato la tiene.

Enganche en app.py:
    from alpha_ventas import bp_alpha_ventas, init_alpha_ventas
    init_alpha_ventas()
    app.register_blueprint(bp_alpha_ventas)
"""

import json
import re
import unicodedata

from flask import Blueprint, jsonify, request, session

from db_compat import get_connection, USE_POSTGRES
from hora_local import ahora_iso

bp_alpha_ventas = Blueprint("alpha_ventas", __name__)

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
PAGOS = ("efectivo", "tarjeta", "transferencia")
MOVS_ENTRADA = ("venta", "cobro", "cambio")


def init_alpha_ventas():
    conn = get_connection()
    try:
        for sql in (
            f"""CREATE TABLE IF NOT EXISTS alpha_ventas (
                id {PK},
                estado TEXT NOT NULL,
                fecha TEXT NOT NULL,
                servicio TEXT NOT NULL,
                asiento TEXT NOT NULL,
                sube_idx INTEGER DEFAULT 0,
                baja_idx INTEGER DEFAULT 99,
                vence TEXT DEFAULT '',
                agencia_id INTEGER,
                usuario TEXT DEFAULT '',
                vendedor TEXT DEFAULT '',
                doc TEXT DEFAULT '',
                nombre TEXT DEFAULT '',
                total REAL DEFAULT 0,
                datos TEXT DEFAULT '{{}}',
                creado_el TEXT DEFAULT '',
                actualizado_el TEXT DEFAULT '')""",
            f"""CREATE TABLE IF NOT EXISTS alpha_movs (
                id {PK},
                venta_id INTEGER NOT NULL,
                t TEXT NOT NULL,
                el TEXT NOT NULL,
                monto REAL DEFAULT 0,
                pago TEXT DEFAULT '',
                recibe REAL,
                usuario TEXT DEFAULT '',
                vendedor TEXT DEFAULT '',
                agencia_id INTEGER,
                cierre_id INTEGER,
                liquidacion_id INTEGER,
                comision REAL DEFAULT 0)""",
            f"""CREATE TABLE IF NOT EXISTS alpha_cierres (
                id {PK},
                fecha TEXT NOT NULL,
                usuario TEXT DEFAULT '',
                vendedor TEXT DEFAULT '',
                agencia_id INTEGER,
                desde TEXT DEFAULT '',
                hasta TEXT NOT NULL,
                tot TEXT DEFAULT '{{}}',
                el TEXT DEFAULT '')""",
            f"""CREATE TABLE IF NOT EXISTS alpha_liquidaciones (
                id {PK},
                agencia_id INTEGER NOT NULL,
                agencia TEXT DEFAULT '',
                desde TEXT DEFAULT '',
                hasta TEXT NOT NULL,
                el TEXT DEFAULT '',
                por TEXT DEFAULT '',
                solo_ef INTEGER DEFAULT 0,
                venta_ef REAL DEFAULT 0,
                venta_tc REAL DEFAULT 0,
                venta_tr REAL DEFAULT 0,
                devoluciones REAL DEFAULT 0,
                comision REAL DEFAULT 0,
                saldo REAL DEFAULT 0,
                saldo_neto REAL DEFAULT 0,
                boletos INTEGER DEFAULT 0,
                estado TEXT DEFAULT 'pendiente',
                depositada_el TEXT DEFAULT '',
                depositada_por TEXT DEFAULT '',
                referencia TEXT DEFAULT '')""",
            "CREATE INDEX IF NOT EXISTS ix_alpha_ventas_serv ON alpha_ventas (fecha, servicio)",
            "CREATE INDEX IF NOT EXISTS ix_alpha_ventas_ag ON alpha_ventas (agencia_id)",
            "CREATE INDEX IF NOT EXISTS ix_alpha_movs_el ON alpha_movs (el)",
            "CREATE INDEX IF NOT EXISTS ix_alpha_movs_venta ON alpha_movs (venta_id)",
            "CREATE INDEX IF NOT EXISTS ix_alpha_movs_liq ON alpha_movs (agencia_id, liquidacion_id)",
        ):
            conn.execute(sql)
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# QUIÉN ES QUIÉN
# ════════════════════════════════════════════════════════════════════════════

def _rol():
    r = session.get("rol")
    return r if r in ("admin", "agencia") else None


def _agencia():
    """La agencia del que está vendiendo (None = administración)."""
    return session.get("agencia_id") if session.get("rol") == "agencia" else None


def _yo():
    return session.get("usuario") or ""


def _vendedor():
    n = session.get("nombre") or session.get("usuario") or ""
    if session.get("rol") == "agencia":
        return " · ".join(x for x in (session.get("agencia") or "Agencia", n) if x)
    return n or "Administración"


def _no(msg="No tenés permiso para esto", codigo=403):
    return jsonify({"ok": False, "msg": msg, "error": msg}), codigo


def _rollback(conn):
    try:
        conn.rollback()
    except Exception:
        pass


def _norm(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    return re.sub(r"\s+", " ", "".join(c for c in s if unicodedata.category(c) != "Mn")).strip()


def _num(x, d=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return d


def _ve(conn, vid):
    r = conn.execute("SELECT * FROM alpha_ventas WHERE id=?", (int(vid),)).fetchone()
    return dict(r) if r else None


def _es_mia(v):
    """Si el que pregunta puede ver los datos de esta venta."""
    if session.get("rol") == "admin":
        return True
    return v.get("agencia_id") is not None and v.get("agencia_id") == _agencia()


def _viva(v, ahora):
    return v["estado"] == "vendido" or (v["estado"] == "reserva" and (v.get("vence") or "") > ahora)


def _salida(v):
    """Cómo se le manda una venta a la pantalla (como la tenía el navegador)."""
    d = {}
    try:
        d = json.loads(v.get("datos") or "{}")
    except ValueError:
        pass
    d.update({"nro": v["id"], "estado": v["estado"], "fecha": v["fecha"], "servicio": v["servicio"],
              "asiento": int(v["asiento"]) if str(v["asiento"]).isdigit() else v["asiento"],
              "subeIdx": v["sube_idx"], "bajaIdx": v["baja_idx"], "vence": v.get("vence") or "",
              "agencia_id": v.get("agencia_id"), "usuario": v.get("usuario") or "",
              "vendedor": v.get("vendedor") or "", "doc": v.get("doc") or d.get("doc") or "",
              "nombre": v.get("nombre") or d.get("nombre") or "", "total": v.get("total") or 0})
    return d


def _movs_de(conn, ids):
    out = {}
    if not ids:
        return out
    ids = list(ids)
    for k in range(0, len(ids), 500):
        tramo = ids[k:k + 500]
        for r in conn.execute(f"SELECT * FROM alpha_movs WHERE venta_id IN ({','.join('?' * len(tramo))}) ORDER BY el, id",
                              tramo).fetchall():
            out.setdefault(r["venta_id"], []).append({
                "t": r["t"], "el": r["el"], "monto": r["monto"], "pago": r["pago"], "recibe": r["recibe"],
                "vendedor": r["vendedor"], "usuario": r["usuario"], "liquidacion_id": r["liquidacion_id"]})
    return out


def _mov(conn, v, t, monto, pago, recibe=None, ahora=None):
    conn.execute("""INSERT INTO alpha_movs (venta_id, t, el, monto, pago, recibe, usuario, vendedor, agencia_id)
                    VALUES (?,?,?,?,?,?,?,?,?)""",
                 (v["id"], t, ahora or ahora_iso(), float(monto), pago or "", recibe, _yo(), _vendedor(), _agencia()))


def _parados_max(conn, plano):
    try:
        r = conn.execute("SELECT valor FROM alpha_config WHERE clave='planos'").fetchone()
        pls = json.loads(r["valor"]) if r else {}
        return int((pls.get(plano) or {}).get("parados") or 0)
    except Exception:
        _rollback(conn)
        return 0


def _choca(conn, fecha, servicio, asiento, s, b, plano, ahora, salvo=None):
    """Si el asiento ya está tomado en un tramo que se pisa con s..b."""
    filas = [dict(r) for r in conn.execute(
        "SELECT id, estado, vence, asiento, sube_idx, baja_idx FROM alpha_ventas WHERE fecha=? AND servicio=?",
        (fecha, servicio)).fetchall()]
    vivas = [f for f in filas if f["id"] != salvo and _viva(f, ahora)]
    if str(asiento) == "P":
        tope = _parados_max(conn, plano)
        return len([f for f in vivas if f["asiento"] == "P"]) >= tope if tope else True
    return any(f["asiento"] == str(asiento) and f["sube_idx"] < b and s < f["baja_idx"] for f in vivas)


# ════════════════════════════════════════════════════════════════════════════
# VENDER, RESERVAR Y LO QUE SE HACE CON UN BOLETO
# ════════════════════════════════════════════════════════════════════════════

CAMPOS_VIAJE = ("fecha", "servicio", "cor", "lado", "hora", "sale", "llega", "llegaDia", "tramo", "coche", "plano",
                "sube", "baja", "origen", "destino", "intl", "asiento", "asDesc")
CAMPOS_PASAJERO = ("nombre", "doc", "tipoDoc", "tipoDocId", "mig")


def _limpiar_viaje(d):
    v = {k: d.get(k) for k in CAMPOS_VIAJE}
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(v["fecha"] or "")):
        return None, "Falta la fecha del viaje"
    if not v["servicio"]:
        return None, "Falta el servicio"
    a = str(v["asiento"] if v["asiento"] is not None else "")
    if not (a == "P" or (a.isdigit() and 0 < int(a) < 200)):
        return None, "Falta el asiento"
    v["asiento"] = a
    for k in ("sube", "baja", "origen", "destino", "tramo", "coche", "plano", "cor", "lado", "hora", "sale", "llega", "llegaDia"):
        v[k] = str(v[k] or "")[:120]
    return v, None


def _limpiar_pasajero(d):
    p = {k: d.get(k) for k in CAMPOS_PASAJERO}
    p["nombre"] = " ".join(str(p["nombre"] or "").split()).upper()[:120]
    p["doc"] = str(p["doc"] or "").strip()[:30]
    if not p["nombre"] or not p["doc"]:
        return None, "Faltan el nombre y el documento del pasajero"
    if p.get("mig") is not None and not isinstance(p["mig"], dict):
        p["mig"] = None
    return p, None


def vender(d, accion):
    viaje, err = _limpiar_viaje(d.get("viaje") or {})
    if err:
        return None, err
    pas, err = _limpiar_pasajero(d.get("pasajero") or {})
    if err:
        return None, err
    total = max(0.0, _num(d.get("total")))
    pago = d.get("pago") if d.get("pago") in PAGOS else "efectivo"
    s, b = int(_num(d.get("sube_idx"), 0)), int(_num(d.get("baja_idx"), 99))
    if b <= s:
        return None, "El tramo no es válido"
    ahora = ahora_iso()
    vence = ""
    if accion == "reservar":
        if viaje["asiento"] == "P":
            return None, "Los pasajes parados no se reservan"
        vence = str(d.get("vence") or "")[:19]
        if not vence or vence <= ahora:
            return None, "Falta menos de una hora para la salida: ya no se reserva, se vende"
    conn = get_connection()
    try:
        if _choca(conn, viaje["fecha"], viaje["servicio"], viaje["asiento"], s, b, viaje["plano"], ahora):
            return None, "Ese asiento ya está tomado en ese tramo" if viaje["asiento"] != "P" else "No quedan pasajes parados"
        datos = dict(viaje, **pas, tarifa=str(d.get("tarifa") or "general")[:30])
        if accion == "vender":
            datos.update(pago=pago, recibe=d.get("recibe"), vendido_en=ahora)
        else:
            datos.update(reservado_en=ahora)
        cur = conn.execute("""INSERT INTO alpha_ventas (estado, fecha, servicio, asiento, sube_idx, baja_idx, vence,
                                  agencia_id, usuario, vendedor, doc, nombre, total, datos, creado_el, actualizado_el)
                              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                           ("vendido" if accion == "vender" else "reserva", viaje["fecha"], viaje["servicio"],
                            viaje["asiento"], s, b, vence, _agencia(), _yo(), _vendedor(), pas["doc"], pas["nombre"],
                            total, json.dumps(datos, ensure_ascii=False), ahora, ahora))
        vid = cur.lastrowid
        v = _ve(conn, vid)
        if accion == "vender":
            _mov(conn, v, "venta", total, pago, d.get("recibe"), ahora)
        conn.commit()
        return _completa(conn, v), None
    except Exception:
        _rollback(conn)
        raise
    finally:
        conn.close()


def _completa(conn, v):
    out = _salida(v)
    out["movs"] = _movs_de(conn, [v["id"]]).get(v["id"], [])
    return out


def accion_venta(vid, accion, d):
    conn = get_connection()
    ahora = ahora_iso()
    try:
        v = _ve(conn, vid)
        if not v:
            return None, "Ese boleto no existe"
        if not _es_mia(v):
            return None, "Ese boleto es de otra agencia"
        datos = json.loads(v.get("datos") or "{}")
        salida = f"{v['fecha']}T{datos.get('sale') or datos.get('hora') or '00:00'}"
        if accion == "liberar":
            if v["estado"] != "reserva":
                return None, "No es una reserva"
            datos.update(liberada_en=ahora, liberada_por=_vendedor())
            conn.execute("UPDATE alpha_ventas SET estado='liberada', datos=?, actualizado_el=? WHERE id=?",
                         (json.dumps(datos, ensure_ascii=False), ahora, v["id"]))
        elif accion == "cobrar":
            if v["estado"] != "reserva" or (v.get("vence") or "") <= ahora:
                return None, "La reserva ya no está vigente"
            pas, err = _limpiar_pasajero(d.get("pasajero") or {})
            if err:
                return None, err
            pago = d.get("pago") if d.get("pago") in PAGOS else "efectivo"
            total = max(0.0, _num(d.get("total"), v["total"]))
            datos.update(pas, pago=pago, recibe=d.get("recibe"), vendido_en=ahora, tarifa=str(d.get("tarifa") or datos.get("tarifa") or "general"))
            conn.execute("""UPDATE alpha_ventas SET estado='vendido', doc=?, nombre=?, total=?, datos=?, vendedor=?, usuario=?,
                            agencia_id=?, actualizado_el=? WHERE id=?""",
                         (pas["doc"], pas["nombre"], total, json.dumps(datos, ensure_ascii=False), _vendedor(), _yo(),
                          _agencia() if session.get("rol") == "agencia" else v.get("agencia_id"), ahora, v["id"]))
            v = _ve(conn, vid)
            _mov(conn, v, "cobro", total, pago, d.get("recibe"), ahora)
        elif accion == "anular":
            if v["estado"] != "vendido":
                return None, "Solo se anula un boleto vendido"
            if (datos.get("vendido_en") or "")[:10] != ahora[:10]:
                return None, "Solo se anula el mismo día de la venta: si no, es una devolución"
            if salida <= ahora:
                return None, "El viaje ya salió"
            datos.update(anulado_en=ahora, anulado_por=_vendedor())
            conn.execute("UPDATE alpha_ventas SET estado='anulado', datos=?, actualizado_el=? WHERE id=?",
                         (json.dumps(datos, ensure_ascii=False), ahora, v["id"]))
            _mov(conn, v, "anulacion", -v["total"], datos.get("pago") or "efectivo", None, ahora)
        elif accion == "devolver":
            if v["estado"] != "vendido":
                return None, "Solo se devuelve un boleto vendido"
            if salida <= ahora:
                return None, "El viaje ya salió"
            m = _num(d.get("monto"), -1)
            if m < 0 or m > v["total"]:
                return None, "Lo que se devuelve no puede ser más de lo que pagó"
            datos.update(devuelto=m, devuelto_en=ahora, devuelto_por=_vendedor())
            conn.execute("UPDATE alpha_ventas SET estado='devuelto', datos=?, actualizado_el=? WHERE id=?",
                         (json.dumps(datos, ensure_ascii=False), ahora, v["id"]))
            _mov(conn, v, "devolucion", -m, "efectivo", None, ahora)
        elif accion == "cambiar":
            if v["estado"] != "vendido":
                return None, "Solo se cambia un boleto vendido"
            if salida <= ahora:
                return None, "El viaje ya salió"
            viaje, err = _limpiar_viaje(d.get("viaje") or {})
            if err:
                return None, err
            pas, err = _limpiar_pasajero(d.get("pasajero") or {})
            if err:
                return None, err
            s, b = int(_num(d.get("sube_idx"), 0)), int(_num(d.get("baja_idx"), 99))
            if _choca(conn, viaje["fecha"], viaje["servicio"], viaje["asiento"], s, b, viaje["plano"], ahora, salvo=v["id"]):
                return None, "Ese asiento ya está tomado en ese tramo"
            total = max(0.0, _num(d.get("total")))
            antes = {k: datos.get(k) for k in ("fecha", "sale", "origen", "destino", "asiento", "tramo")}
            antes["total"] = v["total"]
            datos.update(viaje, **pas, tarifa=str(d.get("tarifa") or "general"))
            datos["cambios"] = (datos.get("cambios") or []) + [{"el": ahora, "por": _vendedor(), "antes": antes}]
            conn.execute("""UPDATE alpha_ventas SET fecha=?, servicio=?, asiento=?, sube_idx=?, baja_idx=?, doc=?, nombre=?,
                            total=?, datos=?, actualizado_el=? WHERE id=?""",
                         (viaje["fecha"], viaje["servicio"], viaje["asiento"], s, b, pas["doc"], pas["nombre"], total,
                          json.dumps(datos, ensure_ascii=False), ahora, v["id"]))
            dif = total - v["total"]
            if dif:
                pago = d.get("pago") if d.get("pago") in PAGOS and dif > 0 else "efectivo"
                _mov(conn, v, "cambio", dif, pago, d.get("recibe") if dif > 0 else None, ahora)
        else:
            return None, "No sé qué hacer con eso"
        conn.commit()
        return _completa(conn, _ve(conn, vid)), None
    except Exception:
        _rollback(conn)
        raise
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# CONSULTAS: ocupación, pasajes, pasajero conocido
# ════════════════════════════════════════════════════════════════════════════

def ocupacion(fecha):
    conn = get_connection()
    ahora = ahora_iso()
    try:
        filas = [dict(r) for r in conn.execute("SELECT * FROM alpha_ventas WHERE fecha=?", (fecha,)).fetchall()]
        vivas = [f for f in filas if _viva(f, ahora)]
        mias = [f for f in vivas if _es_mia(f)]
        movs = _movs_de(conn, [f["id"] for f in mias])
        out = []
        for f in vivas:
            if _es_mia(f):
                x = _salida(f); x["movs"] = movs.get(f["id"], []); x["mia"] = True
            else:
                # De otra agencia: solo que está ocupado y en qué tramo
                x = {"nro": None, "estado": f["estado"], "fecha": f["fecha"], "servicio": f["servicio"],
                     "asiento": int(f["asiento"]) if str(f["asiento"]).isdigit() else f["asiento"],
                     "subeIdx": f["sube_idx"], "bajaIdx": f["baja_idx"], "mia": False, "vence": f.get("vence") or ""}
            out.append(x)
        hoy = ahora[:10]
        caja = conn.execute("SELECT COALESCE(SUM(monto),0) AS m FROM alpha_movs WHERE usuario=? AND el >= ? AND el < ?",
                            (_yo(), hoy, hoy + "T99")).fetchone()["m"]
        q = "SELECT COUNT(*) AS n FROM alpha_ventas WHERE estado='reserva' AND vence > ?"
        args = [ahora]
        if session.get("rol") == "agencia":
            q += " AND agencia_id=?"; args.append(_agencia())
        res = conn.execute(q, args).fetchone()["n"]
        return {"fecha": fecha, "ventas": out, "mi_caja_hoy": caja or 0, "reservas": int(res or 0), "ahora": ahora}
    finally:
        conn.close()


def listar(q="", estado="", fecha="", servicio="", limite=300):
    conn = get_connection()
    try:
        sql, args = "SELECT * FROM alpha_ventas WHERE 1=1", []
        if session.get("rol") == "agencia":
            sql += " AND agencia_id=?"; args.append(_agencia())
        if fecha:
            sql += " AND fecha=?"; args.append(fecha)
        if servicio:
            sql += " AND servicio=?"; args.append(servicio)
        filas = [dict(r) for r in conn.execute(sql + " ORDER BY id DESC", args).fetchall()]
        ahora = ahora_iso()
        for f in filas:
            f["_estado"] = "vencida" if f["estado"] == "reserva" and (f.get("vence") or "") <= ahora else f["estado"]
        cuenta = {}
        for f in filas:
            cuenta[f["_estado"]] = cuenta.get(f["_estado"], 0) + 1
        if estado:
            filas = [f for f in filas if f["_estado"] == estado]
        palabras = _norm(q).split()
        if palabras:
            def txt(f):
                d = f.get("datos") or ""
                dig = re.sub(r"\D", "", f["doc"] or "")
                return _norm(" ".join([f"{f['id']:07d}", str(f["id"]), f["nombre"] or "", f["doc"] or "", dig, f["fecha"],
                                       f"{f['fecha'][8:10]}/{f['fecha'][5:7]}", f["vendedor"] or "", d]))
            filas = [f for f in filas if all(w in txt(f) for w in palabras)]
        total = len(filas)
        filas = filas[:int(limite)]
        movs = _movs_de(conn, [f["id"] for f in filas])
        out = []
        for f in filas:
            x = _salida(f); x["movs"] = movs.get(f["id"], [])
            out.append(x)
        return {"ventas": out, "total": total, "cuenta": cuenta}
    finally:
        conn.close()


def pasajero(doc):
    dig = re.sub(r"\D", "", str(doc or ""))
    if not dig:
        return None
    conn = get_connection()
    try:
        sql, args = "SELECT * FROM alpha_ventas WHERE estado IN ('vendido', 'devuelto') ", []
        if session.get("rol") == "agencia":
            sql += " AND agencia_id=?"; args.append(_agencia())
        filas = [dict(r) for r in conn.execute(sql + " ORDER BY id", args).fetchall()
                 if re.sub(r"\D", "", r["doc"] or "") == dig]
    finally:
        conn.close()
    if not filas:
        return None
    ult = _salida(filas[-1])
    datos = dict(ult.get("mig") or {})
    if not datos.get("nombres"):
        datos["nombreCompleto"] = ult.get("nombre")
    return {"datos": datos, "viajes": len(filas)}


def borrar_todo():
    conn = get_connection()
    try:
        for t in ("alpha_movs", "alpha_ventas", "alpha_cierres", "alpha_liquidaciones"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# CAJA
# ════════════════════════════════════════════════════════════════════════════

def _totales(movs):
    t = {"pago": {}, "salidas": 0, "efectivoNeto": 0, "boletos": 0, "entradas": 0}
    for m in movs:
        if m["monto"] >= 0:
            t["pago"][m["pago"]] = t["pago"].get(m["pago"], 0) + m["monto"]
            t["entradas"] += m["monto"]
        else:
            t["salidas"] += -m["monto"]
        if m["pago"] == "efectivo" or m["monto"] < 0:
            t["efectivoNeto"] += m["monto"]
        if m["t"] in ("venta", "cobro"):
            t["boletos"] += 1
    return t


def caja(fecha, usuario=""):
    conn = get_connection()
    try:
        sql, args = """SELECT m.*, v.nombre, v.datos FROM alpha_movs m JOIN alpha_ventas v ON v.id = m.venta_id
                       WHERE m.el >= ? AND m.el < ?""", [fecha, fecha + "T99"]
        if session.get("rol") == "agencia":
            sql += " AND m.agencia_id=?"; args.append(_agencia())
        todos = [dict(r) for r in conn.execute(sql + " ORDER BY m.el, m.id", args).fetchall()]
        vendedores = {}
        for m in todos:
            vendedores.setdefault(m["usuario"], m["vendedor"])
        vendedores.setdefault(_yo(), _vendedor())
        if usuario not in vendedores:
            usuario = _yo()
        movs = []
        for m in todos:
            if m["usuario"] != usuario:
                continue
            d = json.loads(m.pop("datos") or "{}")
            m.update(nro=m["venta_id"], origen=d.get("origen") or "", destino=d.get("destino") or "")
            movs.append(m)
        cierres = [dict(r) for r in conn.execute(
            "SELECT * FROM alpha_cierres WHERE fecha=? AND usuario=? ORDER BY hasta", (fecha, usuario)).fetchall()]
        for c in cierres:
            c["tot"] = json.loads(c["tot"] or "{}")
        return {"fecha": fecha, "usuario": usuario,
                "vendedores": [{"usuario": u, "vendedor": n} for u, n in sorted(vendedores.items(), key=lambda kv: kv[1])],
                "movs": movs, "cierres": cierres}
    finally:
        conn.close()


def cerrar_caja(fecha, usuario):
    c = caja(fecha, usuario)
    usuario = c["usuario"]
    if session.get("rol") == "agencia" and usuario != _yo():
        return None, "Solo podés cerrar tu caja"
    prev = c["cierres"][-1]["hasta"] if c["cierres"] else ""
    ahora = ahora_iso()
    hasta = ahora if fecha == ahora[:10] else f"{fecha}T23:59:59"
    movs = [m for m in c["movs"] if prev < m["el"] <= hasta]
    if not movs:
        return None, "No hay nada para cerrar"
    tot = _totales(movs)
    vend = next((x["vendedor"] for x in c["vendedores"] if x["usuario"] == usuario), usuario)
    conn = get_connection()
    try:
        ag = movs[0].get("agencia_id")
        cur = conn.execute("""INSERT INTO alpha_cierres (fecha, usuario, vendedor, agencia_id, desde, hasta, tot, el)
                              VALUES (?,?,?,?,?,?,?,?)""",
                           (fecha, usuario, vend, ag, prev, hasta, json.dumps(tot), ahora))
        cid = cur.lastrowid
        ids = [m["id"] for m in movs]
        conn.execute(f"UPDATE alpha_movs SET cierre_id=? WHERE id IN ({','.join('?' * len(ids))})", [cid] + ids)
        conn.commit()
    finally:
        conn.close()
    return {"id": cid, "fecha": fecha, "usuario": usuario, "vendedor": vend, "desde": prev, "hasta": hasta, "tot": tot,
            "el": ahora}, None


# ════════════════════════════════════════════════════════════════════════════
# LIQUIDACIONES DE LAS AGENCIAS (solo administración)
# ════════════════════════════════════════════════════════════════════════════

def _agencias(conn):
    try:
        return {r["id"]: dict(r) for r in conn.execute("SELECT id, nombre, ciudad, estado FROM agencias").fetchall()}
    except Exception:
        _rollback(conn)
        return {}


def _contrato(conn, agencia_id, fecha, cache):
    """El contrato que regía ese día: el de "desde" más reciente que ya empezó."""
    k = (agencia_id, fecha)
    if k not in cache:
        try:
            r = conn.execute("""SELECT comision_tipo, comision, comisiones_ruta FROM agencia_contratos
                                WHERE agencia_id=? AND desde <= ? ORDER BY desde DESC, id DESC LIMIT 1""",
                             (agencia_id, fecha)).fetchone()
            cache[k] = dict(r) if r else None
        except Exception:
            _rollback(conn)
            cache[k] = None
    return cache[k]


def _comision(c, datos, total):
    """La comisión de un boleto según el contrato (por ruta si coincide)."""
    if not c:
        return 0.0, "sin contrato"
    tipo, valor = c.get("comision_tipo") or "porcentaje", _num(c.get("comision"))
    try:
        rutas = json.loads(c.get("comisiones_ruta") or "[]")
    except (TypeError, ValueError):
        rutas = []
    texto = _norm(" ".join(str(datos.get(k) or "") for k in ("origen", "destino", "tramo", "cor")))
    for r in rutas if isinstance(rutas, list) else []:
        ruta = _norm(r.get("ruta"))
        if ruta and all(w in texto for w in ruta.replace("-", " ").replace("/", " ").split() if len(w) > 2):
            tipo, valor = r.get("tipo") or "porcentaje", _num(r.get("valor"))
            break
    if tipo == "monto":
        return valor, f"Gs. {valor:,.0f} por pasaje".replace(",", ".")
    return round(total * valor / 100), f"{valor:g} %"


def _calcular(conn, agencia_id, hasta, solo_ef, ids_movs=None):
    """Lo que falta liquidar de una agencia hasta el corte."""
    if ids_movs is not None:
        if not ids_movs:
            return {"movs": [], "venta_ef": 0, "venta_tc": 0, "venta_tr": 0, "devoluciones": 0, "comision": 0,
                    "saldo": 0, "saldo_neto": 0, "boletos": 0, "desde": "", "hasta": hasta}
        movs = [dict(r) for r in conn.execute(
            f"""SELECT m.*, v.datos, v.estado AS estado_venta, v.nombre, v.total AS total_venta FROM alpha_movs m
                JOIN alpha_ventas v ON v.id = m.venta_id WHERE m.id IN ({','.join('?' * len(ids_movs))}) ORDER BY m.el, m.id""",
            list(ids_movs)).fetchall()]
    else:
        movs = [dict(r) for r in conn.execute(
            """SELECT m.*, v.datos, v.estado AS estado_venta, v.nombre, v.total AS total_venta FROM alpha_movs m
               JOIN alpha_ventas v ON v.id = m.venta_id
               WHERE m.agencia_id=? AND m.liquidacion_id IS NULL AND m.el <= ? ORDER BY m.el, m.id""",
            (agencia_id, hasta)).fetchall()]
    cache = {}
    tot = {"venta_ef": 0.0, "venta_tc": 0.0, "venta_tr": 0.0, "devoluciones": 0.0, "comision": 0.0, "boletos": 0}
    det = []
    for m in movs:
        d = json.loads(m.pop("datos") or "{}")
        com, com_txt = 0.0, ""
        if m["monto"] >= 0:
            tot[{"efectivo": "venta_ef", "tarjeta": "venta_tc", "transferencia": "venta_tr"}.get(m["pago"], "venta_ef")] += m["monto"]
        else:
            tot["devoluciones"] += -m["monto"]
        if m["t"] in ("venta", "cobro"):
            tot["boletos"] += 1
            # La comisión es por boleto que sigue vendido (anulado o devuelto no cobra)
            if m["estado_venta"] == "vendido" and (not solo_ef or m["pago"] == "efectivo"):
                c = _contrato(conn, agencia_id, m["el"][:10], cache)
                com, com_txt = _comision(c, d, m["monto"])
        tot["comision"] += com
        det.append({"id": m["id"], "nro": m["venta_id"], "t": m["t"], "el": m["el"], "monto": m["monto"], "pago": m["pago"],
                    "vendedor": m["vendedor"], "nombre": m["nombre"], "comision": com, "comision_txt": com_txt,
                    "origen": d.get("origen") or "", "destino": d.get("destino") or "", "fecha": d.get("fecha") or "",
                    "sale": d.get("sale") or "", "asiento": d.get("asiento"), "estado_venta": m["estado_venta"]})
    saldo = tot["venta_ef"] + tot["venta_tc"] + tot["venta_tr"] - tot["devoluciones"]
    tot.update(saldo=saldo, saldo_neto=saldo - tot["comision"], movs=det,
               desde=det[0]["el"] if det else "", hasta=hasta)
    return tot


def liquidaciones():
    conn = get_connection()
    try:
        ags = _agencias(conn)
        liqs = [dict(r) for r in conn.execute("SELECT * FROM alpha_liquidaciones ORDER BY el DESC, id DESC").fetchall()]
        pend = {r["agencia_id"]: dict(r) for r in conn.execute(
            """SELECT agencia_id, COUNT(*) AS movs, COALESCE(SUM(monto),0) AS monto, MIN(el) AS desde
               FROM alpha_movs WHERE agencia_id IS NOT NULL AND liquidacion_id IS NULL GROUP BY agencia_id""").fetchall()}
        ultimas = {}
        for l in liqs:
            ultimas.setdefault(l["agencia_id"], l["id"])
        for l in liqs:
            l["ultima"] = ultimas.get(l["agencia_id"]) == l["id"]
        agencias = []
        for aid, a in sorted(ags.items(), key=lambda kv: _norm(kv[1]["nombre"])):
            if a.get("estado") == "baja" and aid not in pend:
                continue
            p = pend.get(aid) or {}
            agencias.append({"id": aid, "nombre": a["nombre"], "ciudad": a.get("ciudad") or "",
                             "pendiente_movs": int(p.get("movs") or 0), "pendiente_monto": p.get("monto") or 0,
                             "pendiente_desde": p.get("desde") or ""})
        return {"liquidaciones": liqs, "agencias": agencias, "ahora": ahora_iso()}
    finally:
        conn.close()


def generar(agencia_id, hasta, solo_ef, quien):
    conn = get_connection()
    try:
        ags = _agencias(conn)
        ids = [int(agencia_id)] if str(agencia_id).isdigit() else [r["agencia_id"] for r in conn.execute(
            "SELECT DISTINCT agencia_id FROM alpha_movs WHERE agencia_id IS NOT NULL AND liquidacion_id IS NULL AND el <= ?",
            (hasta,)).fetchall()]
        hechas = []
        for aid in ids:
            t = _calcular(conn, aid, hasta, solo_ef)
            if not t["movs"]:
                continue
            cur = conn.execute("""INSERT INTO alpha_liquidaciones (agencia_id, agencia, desde, hasta, el, por, solo_ef,
                                     venta_ef, venta_tc, venta_tr, devoluciones, comision, saldo, saldo_neto, boletos, estado)
                                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'pendiente')""",
                               (aid, (ags.get(aid) or {}).get("nombre") or f"Agencia {aid}", t["desde"], hasta, ahora_iso(),
                                quien[:80], 1 if solo_ef else 0, t["venta_ef"], t["venta_tc"], t["venta_tr"],
                                t["devoluciones"], t["comision"], t["saldo"], t["saldo_neto"], t["boletos"]))
            lid = cur.lastrowid
            for m in t["movs"]:
                conn.execute("UPDATE alpha_movs SET liquidacion_id=?, comision=? WHERE id=?", (lid, m["comision"], m["id"]))
            hechas.append(lid)
        conn.commit()
        return hechas
    except Exception:
        _rollback(conn)
        raise
    finally:
        conn.close()


def detalle(lid):
    conn = get_connection()
    try:
        l = conn.execute("SELECT * FROM alpha_liquidaciones WHERE id=?", (int(lid),)).fetchone()
        if not l:
            return None
        l = dict(l)
        ids = [r["id"] for r in conn.execute("SELECT id FROM alpha_movs WHERE liquidacion_id=?", (l["id"],)).fetchall()]
        t = _calcular(conn, l["agencia_id"], l["hasta"], l["solo_ef"], ids)
        # La comisión guardada al liquidar es la que vale (si después cambia el contrato, no se mueve)
        guard = {r["id"]: r["comision"] for r in conn.execute("SELECT id, comision FROM alpha_movs WHERE liquidacion_id=?",
                                                               (l["id"],)).fetchall()}
        for m in t["movs"]:
            m["comision"] = guard.get(m["id"], m["comision"])
        l["movs"] = t["movs"]
        return l
    finally:
        conn.close()


def deshacer(lid):
    conn = get_connection()
    try:
        l = conn.execute("SELECT * FROM alpha_liquidaciones WHERE id=?", (int(lid),)).fetchone()
        if not l:
            return "No existe"
        if l["estado"] == "depositada":
            return "Ya está depositada: no se deshace"
        otra = conn.execute("SELECT id FROM alpha_liquidaciones WHERE agencia_id=? AND id > ?", (l["agencia_id"], l["id"])).fetchone()
        if otra:
            return "Solo se deshace la última liquidación de la agencia"
        conn.execute("UPDATE alpha_movs SET liquidacion_id=NULL, comision=0 WHERE liquidacion_id=?", (l["id"],))
        conn.execute("DELETE FROM alpha_liquidaciones WHERE id=?", (l["id"],))
        conn.commit()
        return None
    finally:
        conn.close()


def depositada(lid, referencia, quien):
    conn = get_connection()
    try:
        l = conn.execute("SELECT estado FROM alpha_liquidaciones WHERE id=?", (int(lid),)).fetchone()
        if not l:
            return "No existe"
        conn.execute("""UPDATE alpha_liquidaciones SET estado='depositada', depositada_el=?, depositada_por=?, referencia=?
                        WHERE id=?""", (ahora_iso(), quien[:80], str(referencia or "")[:120], int(lid)))
        conn.commit()
        return None
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# RUTAS
# ════════════════════════════════════════════════════════════════════════════

def _auditar(accion, detalle=""):
    try:
        from database import registrar_auditoria
        registrar_auditoria(usuario=session.get("nombre") or session.get("usuario") or "?", rol=session.get("rol") or "",
                            accion=accion, categoria="Alpha", detalle=str(detalle)[:200])
    except Exception:
        pass


@bp_alpha_ventas.route("/api/alpha/ocupacion", methods=["GET"])
def api_ocupacion():
    if not _rol():
        return _no()
    f = request.args.get("fecha") or ""
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", f):
        return _no("Fecha inválida", 400)
    return jsonify(ocupacion(f))


@bp_alpha_ventas.route("/api/alpha/ventas", methods=["GET"])
def api_listar():
    if not _rol():
        return _no()
    a = request.args
    return jsonify(listar(a.get("q", ""), a.get("estado", ""), a.get("fecha", ""), a.get("servicio", ""),
                          min(1000, int(a.get("limite") or 300))))


@bp_alpha_ventas.route("/api/alpha/ventas", methods=["POST"])
def api_vender():
    if not _rol():
        return _no()
    if session.get("rol") == "agencia" and not _agencia():
        return _no("Tu usuario no tiene una agencia asignada")
    d = request.get_json(silent=True) or {}
    accion = "reservar" if d.get("accion") == "reservar" else "vender"
    v, err = vender(d, accion)
    if err:
        return _no(err, 409 if "tomado" in err or "parados" in err else 400)
    _auditar("Alpha: " + ("vendió" if accion == "vender" else "reservó") + f" el boleto {v['nro']:07d}",
             f"{v.get('origen')} → {v.get('destino')} {v.get('fecha')} {v.get('sale')} asiento {v.get('asiento')}")
    return jsonify({"ok": True, "venta": v})


@bp_alpha_ventas.route("/api/alpha/ventas", methods=["DELETE"])
def api_borrar_todo():
    if session.get("rol") != "admin":
        return _no("Solo administración puede borrar las ventas de prueba")
    borrar_todo()
    _auditar("Alpha: borró todas las ventas de prueba")
    return jsonify({"ok": True})


@bp_alpha_ventas.route("/api/alpha/ventas/<int:vid>/<accion>", methods=["POST"])
def api_accion(vid, accion):
    if not _rol():
        return _no()
    if accion not in ("cobrar", "liberar", "anular", "devolver", "cambiar"):
        return _no("No sé qué hacer con eso", 400)
    v, err = accion_venta(vid, accion, request.get_json(silent=True) or {})
    if err:
        return _no(err, 409 if "tomado" in err else 400)
    nombres = {"cobrar": "cobró la reserva", "liberar": "liberó la reserva", "anular": "anuló", "devolver": "devolvió",
               "cambiar": "cambió"}
    _auditar(f"Alpha: {nombres[accion]} {vid:07d}", v.get("nombre"))
    return jsonify({"ok": True, "venta": v})


@bp_alpha_ventas.route("/api/alpha/pasajero", methods=["GET"])
def api_pasajero():
    if not _rol():
        return _no()
    return jsonify(pasajero(request.args.get("doc")) or {})


@bp_alpha_ventas.route("/api/alpha/caja", methods=["GET"])
def api_caja():
    if not _rol():
        return _no()
    f = request.args.get("fecha") or ahora_iso()[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", f):
        return _no("Fecha inválida", 400)
    u = request.args.get("usuario") or _yo()
    return jsonify(caja(f, u))


@bp_alpha_ventas.route("/api/alpha/caja/cerrar", methods=["POST"])
def api_cerrar_caja():
    if not _rol():
        return _no()
    d = request.get_json(silent=True) or {}
    f = d.get("fecha") or ahora_iso()[:10]
    c, err = cerrar_caja(f, d.get("usuario") or _yo())
    if err:
        return _no(err, 400)
    _auditar(f"Alpha: cerró la caja de {c['vendedor']}", f"{c['tot'].get('boletos')} boletos")
    return jsonify({"ok": True, "cierre": c})


@bp_alpha_ventas.route("/api/alpha/liquidaciones", methods=["GET"])
def api_liquidaciones():
    if session.get("rol") != "admin":
        return _no("Las liquidaciones las ve solo administración")
    return jsonify(liquidaciones())


@bp_alpha_ventas.route("/api/alpha/liquidaciones/pendiente", methods=["GET"])
def api_pendiente():
    if session.get("rol") != "admin":
        return _no("Las liquidaciones las ve solo administración")
    aid = request.args.get("agencia_id") or ""
    if not aid.isdigit():
        return _no("Elegí la agencia", 400)
    hasta = (request.args.get("hasta") or ahora_iso())[:19]
    if len(hasta) == 16:
        hasta += ":59"      # el minuto del corte entra entero
    conn = get_connection()
    try:
        t = _calcular(conn, int(aid), hasta, request.args.get("solo_ef") == "1")
    finally:
        conn.close()
    return jsonify(t)


@bp_alpha_ventas.route("/api/alpha/liquidaciones", methods=["POST"])
def api_generar():
    if session.get("rol") != "admin":
        return _no("Las liquidaciones las hace solo administración")
    d = request.get_json(silent=True) or {}
    hasta = str(d.get("hasta") or ahora_iso())[:19]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2})?", hasta):
        return _no("El corte no se entiende", 400)
    if len(hasta) == 16:
        hasta += ":59"
    hechas = generar(d.get("agencia_id"), hasta, bool(d.get("solo_ef")), session.get("nombre") or session.get("usuario") or "")
    if not hechas:
        return _no("No hay nada para liquidar hasta ese corte", 400)
    _auditar(f"Alpha: generó {len(hechas)} liquidación(es) de agencias", f"corte {hasta}")
    return jsonify({"ok": True, "ids": hechas})


@bp_alpha_ventas.route("/api/alpha/liquidaciones/<int:lid>", methods=["GET"])
def api_detalle(lid):
    if session.get("rol") != "admin":
        return _no("Las liquidaciones las ve solo administración")
    l = detalle(lid)
    return jsonify(l) if l else _no("No existe", 404)


@bp_alpha_ventas.route("/api/alpha/liquidaciones/<int:lid>", methods=["DELETE"])
def api_deshacer(lid):
    if session.get("rol") != "admin":
        return _no("Las liquidaciones las maneja solo administración")
    err = deshacer(lid)
    if err:
        return _no(err, 400)
    _auditar(f"Alpha: deshizo la liquidación {lid}")
    return jsonify({"ok": True})


@bp_alpha_ventas.route("/api/alpha/liquidaciones/<int:lid>/depositada", methods=["POST"])
def api_depositada(lid):
    if session.get("rol") != "admin":
        return _no("Las liquidaciones las maneja solo administración")
    d = request.get_json(silent=True) or {}
    err = depositada(lid, d.get("referencia"), session.get("nombre") or session.get("usuario") or "")
    if err:
        return _no(err, 400)
    _auditar(f"Alpha: marcó depositada la liquidación {lid}", d.get("referencia"))
    return jsonify({"ok": True})
