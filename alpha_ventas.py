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

from db_compat import get_connection, columnas_de_tabla, USE_POSTGRES
from hora_local import ahora_iso

bp_alpha_ventas = Blueprint("alpha_ventas", __name__)

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"
PAGOS = ("efectivo", "tarjeta", "transferencia")
MOVS_ENTRADA = ("venta", "cobro", "cambio", "equipaje")
MOVS_IE = ("ingreso", "egreso")       # ingresos y egresos de caja que no son de un boleto


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
            f"""CREATE TABLE IF NOT EXISTS alpha_servicios (
                clave TEXT PRIMARY KEY,
                fecha TEXT NOT NULL,
                servicio TEXT NOT NULL,
                estado TEXT DEFAULT 'abierto',
                motivo TEXT DEFAULT '',
                por TEXT DEFAULT '',
                el TEXT DEFAULT '',
                historial TEXT DEFAULT '[]',
                coche TEXT DEFAULT '',
                reemplazo TEXT DEFAULT '')""",
            f"""CREATE TABLE IF NOT EXISTS alpha_transbordos (
                id {PK},
                el TEXT NOT NULL,
                por TEXT DEFAULT '',
                fecha TEXT NOT NULL,
                servicio TEXT NOT NULL,
                tipo TEXT NOT NULL,
                motivo TEXT DEFAULT '',
                parada TEXT DEFAULT '',
                hora TEXT DEFAULT '',
                tramo TEXT DEFAULT '',
                destino TEXT DEFAULT '',
                coche_antes TEXT DEFAULT '',
                coche_nuevo TEXT DEFAULT '',
                pasajeros INTEGER DEFAULT 0,
                taller TEXT DEFAULT '',
                detalle TEXT DEFAULT '[]')""",
            "CREATE INDEX IF NOT EXISTS ix_alpha_transbordos_f ON alpha_transbordos (fecha)",
            "CREATE INDEX IF NOT EXISTS ix_alpha_servicios_f ON alpha_servicios (fecha)",
            "CREATE INDEX IF NOT EXISTS ix_alpha_ventas_serv ON alpha_ventas (fecha, servicio)",
            "CREATE INDEX IF NOT EXISTS ix_alpha_ventas_ag ON alpha_ventas (agencia_id)",
            "CREATE INDEX IF NOT EXISTS ix_alpha_movs_el ON alpha_movs (el)",
            "CREATE INDEX IF NOT EXISTS ix_alpha_movs_venta ON alpha_movs (venta_id)",
            "CREATE INDEX IF NOT EXISTS ix_alpha_movs_liq ON alpha_movs (agencia_id, liquidacion_id)",
        ):
            conn.execute(sql)
        conn.commit()
        # Ingresos y egresos de caja (sin boleto) y su total en la liquidación
        if "concepto" not in columnas_de_tabla(conn, "alpha_movs"):
            conn.execute("ALTER TABLE alpha_movs ADD COLUMN concepto TEXT DEFAULT ''")
            conn.commit()
        if "ie" not in columnas_de_tabla(conn, "alpha_liquidaciones"):
            conn.execute("ALTER TABLE alpha_liquidaciones ADD COLUMN ie REAL DEFAULT 0")
            conn.commit()
        # El coche que reemplaza al que se rompió (cuando el tráfico no tiene la salida)
        cols = columnas_de_tabla(conn, "alpha_servicios")
        for col in ("coche", "reemplazo"):
            if col not in cols:
                conn.execute(f"ALTER TABLE alpha_servicios ADD COLUMN {col} TEXT DEFAULT ''")
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
    """Si ocupa el asiento: vendido, bloqueado por administración o reserva vigente."""
    return v["estado"] in ("vendido", "bloqueado") or (v["estado"] == "reserva" and (v.get("vence") or "") > ahora)


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
# CONTROLES: venta cerrada o servicio cancelado; tope de crédito de la agencia
# ════════════════════════════════════════════════════════════════════════════

ESTADOS_SERVICIO = ("abierto", "cerrado", "cancelado")


def _estados_servicios(conn, fecha):
    try:
        out = {}
        for r in conn.execute("SELECT * FROM alpha_servicios WHERE fecha=?", (fecha,)).fetchall():
            x = dict(r)
            x["historial"] = json.loads(x.get("historial") or "[]")
            try:
                x["reemplazo_obj"] = json.loads(x.get("reemplazo") or "null")
            except ValueError:
                x["reemplazo_obj"] = None
            out[x["servicio"]] = x
        return out
    except Exception:
        _rollback(conn)
        return {}


def _servicio_err(conn, fecha, servicio):
    e = (_estados_servicios(conn, fecha).get(servicio) or {}).get("estado")
    if e == "cerrado":
        return "La venta de ese servicio está cerrada"
    if e == "cancelado":
        return "Ese servicio está cancelado"
    return None


def _servicio_guardar(conn, fecha, servicio, entrada, estado=None, motivo=None, coche=None, reemplazo=None):
    """Agrega una entrada al historial del servicio y cambia lo que venga."""
    ant = _estados_servicios(conn, fecha).get(servicio) or {}
    hist = (ant.get("historial") or []) + [entrada]
    est = estado or ant.get("estado") or "abierto"
    mot = motivo if motivo is not None else (ant.get("motivo") or "")
    co = coche if coche is not None else (ant.get("coche") or "")
    rz = json.dumps(reemplazo, ensure_ascii=False) if reemplazo is not None else (ant.get("reemplazo") or "")
    conn.execute("""INSERT INTO alpha_servicios (clave, fecha, servicio, estado, motivo, por, el, historial, coche, reemplazo)
                    VALUES (?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT (clave) DO UPDATE SET estado=excluded.estado, motivo=excluded.motivo, por=excluded.por,
                    el=excluded.el, historial=excluded.historial, coche=excluded.coche, reemplazo=excluded.reemplazo""",
                 (f"{fecha}|{servicio}", fecha, servicio, est, mot, entrada.get("por") or "", entrada.get("el") or "",
                  json.dumps(hist, ensure_ascii=False), co, rz))
    return {"fecha": fecha, "servicio": servicio, "estado": est, "motivo": mot, "por": entrada.get("por"),
            "el": entrada.get("el"), "historial": hist}


def estado_servicio(d):
    fecha, servicio, estado = str(d.get("fecha") or ""), str(d.get("servicio") or "")[:200], d.get("estado")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha) or not servicio:
        return None, "Falta el servicio"
    if estado not in ESTADOS_SERVICIO:
        return None, "Estado inválido"
    motivo = " ".join(str(d.get("motivo") or "").split())[:160]
    if estado == "cancelado" and not motivo:
        return None, "Contá por qué se cancela (queda en el historial)"
    ahora = ahora_iso()
    conn = get_connection()
    try:
        out = _servicio_guardar(conn, fecha, servicio, {
            "el": ahora, "por": _vendedor(), "estado": estado, "motivo": motivo,
            "hora": str(d.get("hora") or "")[:5], "tramo": str(d.get("tramo") or "")[:60]}, estado=estado, motivo=motivo)
        conn.commit()
        return out, None
    except Exception:
        _rollback(conn)
        raise
    finally:
        conn.close()


def _credito(conn, agencia_id):
    """Lo que la agencia tiene en la mano: lo vendido sin liquidar más las
    liquidaciones sin depositar, contra el tope de su contrato."""
    hoy = ahora_iso()[:10]
    out = {"tope": 0.0, "sin_liquidar": 0.0, "sin_depositar": 0.0, "saldo": 0.0, "disponible": None,
           "estado": "activa", "motivo": "", "contrato_hasta": ""}
    try:
        a = conn.execute("SELECT estado, estado_motivo FROM agencias WHERE id=?", (agencia_id,)).fetchone()
        if a:
            out["estado"], out["motivo"] = a["estado"] or "activa", a["estado_motivo"] or ""
        c = conn.execute("""SELECT tope_sin_depositar, hasta FROM agencia_contratos
                            WHERE agencia_id=? AND desde <= ? AND COALESCE(anulado, 0) = 0
                            ORDER BY desde DESC, id DESC LIMIT 1""", (agencia_id, hoy)).fetchone()
        if c:
            out["tope"], out["contrato_hasta"] = _num(c["tope_sin_depositar"]), c["hasta"] or ""
    except Exception:
        _rollback(conn)
    out["sin_liquidar"] = _num(conn.execute(
        "SELECT COALESCE(SUM(monto), 0) AS m FROM alpha_movs WHERE agencia_id=? AND liquidacion_id IS NULL",
        (agencia_id,)).fetchone()["m"])
    out["sin_depositar"] = _num(conn.execute(
        "SELECT COALESCE(SUM(saldo_neto), 0) AS m FROM alpha_liquidaciones WHERE agencia_id=? AND estado <> 'depositada'",
        (agencia_id,)).fetchone()["m"])
    out["saldo"] = out["sin_liquidar"] + out["sin_depositar"]
    if out["tope"] > 0:
        out["disponible"] = out["tope"] - out["saldo"]
    return out


def _tope_err(conn, monto):
    """Si la agencia que vende no puede cobrar esto: suspendida, de baja o pasada del tope."""
    aid = _agencia()
    if not aid:
        return None
    c = _credito(conn, aid)
    if c["estado"] in ("suspendida", "baja"):
        return (f"Tu agencia está {'suspendida' if c['estado'] == 'suspendida' else 'dada de baja'}"
                f"{': ' + c['motivo'] if c['motivo'] else ''}. Para vender, hablá con La Santaniana.")
    if c["tope"] > 0 and c["saldo"] + monto > c["tope"]:
        return (f"Llegaste al tope de venta sin depositar (Gs. {_gs(c['tope'])}): tenés Gs. {_gs(c['saldo'])} "
                f"sin depositar. Depositá lo pendiente para seguir vendiendo.")
    return None


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


def _extras(d):
    """Lo que va con el pasajero: un menor en brazos (sin asiento) y los bultos en bodega."""
    out = {}
    m = d.get("menor")
    if isinstance(m, dict) and str(m.get("nombre") or "").strip():
        edad = int(_num(m.get("edad"), -1))
        out["menor"] = {"nombre": " ".join(str(m["nombre"]).split()).upper()[:80],
                        "doc": str(m.get("doc") or "").strip()[:30],
                        "edad": edad if 0 <= edad <= 17 else None}
    b = int(_num(d.get("bultos"), 0))
    if 0 < b <= 20:
        out["bultos"] = b
    return out


def _poner_extras(datos, d):
    for k in ("menor", "bultos"):
        datos.pop(k, None)
    datos.update(_extras(d))


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
        err = _servicio_err(conn, viaje["fecha"], viaje["servicio"]) or _tope_err(conn, total if accion == "vender" else 0)
        if err:
            return None, err
        if _choca(conn, viaje["fecha"], viaje["servicio"], viaje["asiento"], s, b, viaje["plano"], ahora):
            return None, "Ese asiento ya está tomado en ese tramo" if viaje["asiento"] != "P" else "No quedan pasajes parados"
        datos = dict(viaje, **pas, tarifa=str(d.get("tarifa") or "general")[:30])
        datos.update(_extras(d))
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


MOTIVOS_BLOQUEO = ("Tripulación", "Guarda", "Compromiso", "Asiento roto", "Otro")


def bloquear(d):
    """Administración saca un asiento de la venta en todo el recorrido de la salida
    (tripulación, un compromiso, un asiento roto)."""
    viaje, err = _limpiar_viaje(d.get("viaje") or {})
    if err:
        return None, err
    if viaje["asiento"] == "P":
        return None, "Los parados no se bloquean"
    motivo = " ".join(str(d.get("motivo") or "").split())[:60] or "Bloqueado"
    ahora = ahora_iso()
    conn = get_connection()
    try:
        if _choca(conn, viaje["fecha"], viaje["servicio"], viaje["asiento"], 0, 99, viaje["plano"], ahora):
            return None, "Ese asiento ya está vendido o reservado en algún tramo de esta salida"
        datos = dict(viaje, motivo=motivo, bloqueado_en=ahora, bloqueado_por=_vendedor())
        cur = conn.execute("""INSERT INTO alpha_ventas (estado, fecha, servicio, asiento, sube_idx, baja_idx, vence,
                                  agencia_id, usuario, vendedor, doc, nombre, total, datos, creado_el, actualizado_el)
                              VALUES ('bloqueado',?,?,?,0,99,'',NULL,?,?,'',?,0,?,?,?)""",
                           (viaje["fecha"], viaje["servicio"], viaje["asiento"], _yo(), _vendedor(), motivo.upper(),
                            json.dumps(datos, ensure_ascii=False), ahora, ahora))
        v = _ve(conn, cur.lastrowid)
        conn.commit()
        return _salida(v), None
    except Exception:
        _rollback(conn)
        raise
    finally:
        conn.close()


def una(vid):
    conn = get_connection()
    try:
        v = _ve(conn, vid)
        if not v or not _es_mia(v):
            return None
        return _completa(conn, v)
    finally:
        conn.close()


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
            if (_estados_servicios(conn, v["fecha"]).get(v["servicio"]) or {}).get("estado") == "cancelado":
                return None, "Ese servicio está cancelado"
            err = _tope_err(conn, total)
            if err:
                return None, err
            datos.update(pas, pago=pago, recibe=d.get("recibe"), vendido_en=ahora, tarifa=str(d.get("tarifa") or datos.get("tarifa") or "general"))
            _poner_extras(datos, d)
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
            if viaje["servicio"] != v["servicio"] or viaje["fecha"] != v["fecha"]:
                err = _servicio_err(conn, viaje["fecha"], viaje["servicio"])
                if err:
                    return None, err
            if total > v["total"]:
                err = _tope_err(conn, total - v["total"])
                if err:
                    return None, err
            antes = {k: datos.get(k) for k in ("fecha", "sale", "origen", "destino", "asiento", "tramo")}
            antes["total"] = v["total"]
            datos.update(viaje, **pas, tarifa=str(d.get("tarifa") or "general"))
            _poner_extras(datos, d)
            datos.pop("embarque", None)
            datos["cambios"] =(datos.get("cambios") or []) + [{"el": ahora, "por": _vendedor(), "antes": antes}]
            conn.execute("""UPDATE alpha_ventas SET fecha=?, servicio=?, asiento=?, sube_idx=?, baja_idx=?, doc=?, nombre=?,
                            total=?, datos=?, actualizado_el=? WHERE id=?""",
                         (viaje["fecha"], viaje["servicio"], viaje["asiento"], s, b, pas["doc"], pas["nombre"], total,
                          json.dumps(datos, ensure_ascii=False), ahora, v["id"]))
            dif = total - v["total"]
            if dif:
                pago = d.get("pago") if d.get("pago") in PAGOS and dif > 0 else "efectivo"
                _mov(conn, v, "cambio", dif, pago, d.get("recibe") if dif > 0 else None, ahora)
        elif accion == "reimpresion":
            if v["estado"] != "vendido":
                return None, "Solo se reimprime un boleto vendido"
            copias = [c for c in (d.get("copias") or []) if c in ("original", "duplicado", "triplicado", "etiquetas", "comprobante")]
            datos["reimpresiones"] = (datos.get("reimpresiones") or []) + [{"el": ahora, "por": _vendedor(), "copias": copias}]
            conn.execute("UPDATE alpha_ventas SET datos=?, actualizado_el=? WHERE id=?",
                         (json.dumps(datos, ensure_ascii=False), ahora, v["id"]))
        elif accion == "equipaje":
            # Bultos que se agregan después de la venta y el exceso de equipaje cobrado
            if v["estado"] != "vendido":
                return None, "Solo se agrega equipaje a un boleto vendido"
            bultos, kg, monto = int(_num(d.get("bultos"), 0)), _num(d.get("kg"), 0), _num(d.get("monto"), 0)
            if not 0 <= bultos <= 20 or not 0 <= kg <= 500 or not 0 <= monto <= 5_000_000:
                return None, "Revisá los bultos, los kilos y el monto"
            if not bultos and not kg and not monto:
                return None, "Poné los bultos, los kilos o lo que se cobra"
            pago = d.get("pago") if d.get("pago") in PAGOS else "efectivo"
            recibe = d.get("recibe") if monto and pago == "efectivo" else None
            err = _tope_err(conn, monto) if monto else None
            if err:
                return None, err
            datos["equipaje"] = (datos.get("equipaje") or []) + [{
                "el": ahora, "por": _vendedor(), "bultos": bultos, "kg": kg, "monto": monto,
                "pago": pago if monto else "", "recibe": recibe,
                "nota": " ".join(str(d.get("nota") or "").split())[:120]}]
            conn.execute("UPDATE alpha_ventas SET datos=?, actualizado_el=? WHERE id=?",
                         (json.dumps(datos, ensure_ascii=False), ahora, v["id"]))
            if monto:
                _mov(conn, v, "equipaje", monto, pago, recibe, ahora)
        elif accion == "embarque":
            if session.get("rol") != "admin":
                return None, "El embarque lo marca administración"
            if v["estado"] != "vendido":
                return None, "Solo se embarca un boleto vendido"
            e = d.get("estado") or ""
            if e not in ("subio", "no_vino", ""):
                return None, "No sé qué marcar"
            if e:
                datos["embarque"] = {"estado": e, "el": ahora, "por": _vendedor()}
            else:
                datos.pop("embarque", None)
            conn.execute("UPDATE alpha_ventas SET datos=?, actualizado_el=? WHERE id=?",
                         (json.dumps(datos, ensure_ascii=False), ahora, v["id"]))
        elif accion == "desbloquear":
            if session.get("rol") != "admin":
                return None, "Los asientos los bloquea y desbloquea administración"
            if v["estado"] != "bloqueado":
                return None, "Ese asiento no está bloqueado"
            conn.execute("DELETE FROM alpha_ventas WHERE id=?", (v["id"],))
            conn.commit()
            out = _salida(v)
            out["estado"] = "desbloqueado"
            return out, None
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
# TRANSBORDOS (solo administración): se rompe un coche y
#   - otro coche sigue la misma salida (los asientos se reacomodan si el plano
#     es otro y el cambio queda en el tráfico), o
#   - los pasajeros pasan a otra salida (del mismo día o del siguiente).
# La pantalla arma el plan (qué asiento le toca a cada uno) y acá se revisa que
# no choque con nada y se aplica todo junto. No mueve plata: el boleto sigue
# siendo el mismo, con otro servicio o asiento, y queda anotado el transbordo.
# ════════════════════════════════════════════════════════════════════════════

def _taller_aviso(coche, texto, quien):
    """Un pedido de reparación en la bandeja del taller (Pedidos de los choferes)."""
    try:
        from ot_pedidos import crear_reporte
        conn = get_connection()
        try:
            v = conn.execute("SELECT id FROM vehiculos WHERE TRIM(CAST(n_interno AS TEXT))=?", (str(coche).strip(),)).fetchone()
        finally:
            conn.close()
        if not v:
            return ""
        rid = crear_reporte(v["id"], [{"descripcion": texto[:300], "tipo": "correctivo"}], f"Controles · {quien}"[:80])
        return f"pedido {rid}"
    except Exception:
        return ""


def aplicar_transbordo(d):
    tipo = d.get("tipo")
    if tipo not in ("coche", "salida"):
        return None, "¿Otro coche o otra salida?"
    fecha, servicio = str(d.get("fecha") or ""), str(d.get("servicio") or "")[:200]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha) or not servicio:
        return None, "Falta la salida con problemas"
    motivo = " ".join(str(d.get("motivo") or "").split())[:160]
    if not motivo:
        return None, "Contá qué pasó (queda en el historial)"
    parada = " ".join(str(d.get("parada") or "").split())[:80]
    coche_antes = str(d.get("coche_antes") or "").strip()[:20]
    coche_nuevo = str(d.get("coche_nuevo") or "").strip()[:20]
    if tipo == "coche" and not coche_nuevo:
        return None, "Elegí el coche que sigue la salida"
    if tipo == "coche" and coche_nuevo == coche_antes:
        return None, "Es el mismo coche"
    movs = d.get("movs") or []
    if not isinstance(movs, list) or len(movs) > 300:
        return None, "Lista de pasajeros inválida"
    if tipo == "salida" and not movs:
        return None, "Elegí qué pasajeros pasan a la otra salida"
    ahora, quien = ahora_iso(), _vendedor()
    conn = get_connection()
    try:
        limpios, ids = [], set()
        for m in movs:
            try:
                nro = int(m.get("nro"))
            except (TypeError, ValueError):
                return None, "Pasajero inválido"
            v = _ve(conn, nro)
            if not v or v["fecha"] != fecha or v["servicio"] != servicio or not _viva(v, ahora) or v["estado"] == "bloqueado":
                return None, f"El boleto {nro:07d} ya no está en esa salida: volvé a armar el transbordo"
            viaje, err = _limpiar_viaje(m.get("viaje") or {})
            if err:
                return None, err
            s, b = int(_num(m.get("sube_idx"), 0)), int(_num(m.get("baja_idx"), 99))
            if b <= s:
                return None, f"El tramo del boleto {nro:07d} no es válido"
            if tipo == "coche" and (viaje["fecha"] != fecha or viaje["servicio"] != servicio):
                return None, "Con otro coche, la salida es la misma"
            if v["estado"] == "reserva" and viaje["asiento"] == "P":
                return None, "Una reserva no puede quedar parada"
            limpios.append((v, viaje, s, b))
            ids.add(nro)
        # Que nadie quede en un asiento ocupado (ni dos de los que se mueven en el mismo)
        destinos = {}
        for v, viaje, s, b in limpios:
            destinos.setdefault((viaje["fecha"], viaje["servicio"]), []).append((v, viaje, s, b))
        for (f, sv), lista in destinos.items():
            if tipo == "salida":
                est = (_estados_servicios(conn, f).get(sv) or {}).get("estado")
                if est == "cancelado":
                    return None, "La salida de destino está cancelada"
            otros = [dict(r) for r in conn.execute(
                "SELECT id, estado, vence, asiento, sube_idx, baja_idx FROM alpha_ventas WHERE fecha=? AND servicio=?",
                (f, sv)).fetchall()]
            ocup = [o for o in otros if o["id"] not in ids and _viva(o, ahora)]
            tope = _parados_max(conn, lista[0][1]["plano"])
            for v, viaje, s, b in lista:
                a = viaje["asiento"]
                if a == "P":
                    if len([o for o in ocup if o["asiento"] == "P"]) >= tope:
                        return None, f"En la salida de destino no quedan lugares parados (boleto {v['id']:07d})"
                elif any(o["asiento"] == a and o["sube_idx"] < b and s < o["baja_idx"] for o in ocup):
                    return None, f"El asiento {a} de la salida de destino ya está ocupado: volvé a armar el transbordo"
                ocup.append({"asiento": a, "sube_idx": s, "baja_idx": b})
        # Aplicar
        detalle = []
        for v, viaje, s, b in limpios:
            datos = json.loads(v.get("datos") or "{}")
            antes = {k: datos.get(k) for k in ("hora", "sale", "llega", "tramo", "coche", "sube", "baja")}
            antes.update(fecha=v["fecha"], servicio=v["servicio"], asiento=v["asiento"])
            for k in CAMPOS_VIAJE:
                if viaje.get(k) is not None and k != "intl":
                    datos[k] = viaje[k]
            if tipo == "salida":
                datos.pop("embarque", None)
            datos["transbordos"] = (datos.get("transbordos") or []) + [
                {"el": ahora, "por": quien, "tipo": tipo, "motivo": motivo, "parada": parada, "antes": antes}]
            conn.execute("""UPDATE alpha_ventas SET fecha=?, servicio=?, asiento=?, sube_idx=?, baja_idx=?, datos=?, actualizado_el=?
                            WHERE id=?""", (viaje["fecha"], viaje["servicio"], viaje["asiento"], s, b,
                                            json.dumps(datos, ensure_ascii=False), ahora, v["id"]))
            detalle.append({"nro": v["id"], "nombre": v["nombre"], "doc": v["doc"], "estado": v["estado"],
                            "antes": antes, "despues": {k: datos.get(k) for k in ("fecha", "hora", "sale", "llega", "tramo", "coche",
                                                                                  "sube", "baja", "asiento")}})
        destino_txt = str(d.get("destino_txt") or "")[:160]
        entrada = {"el": ahora, "por": quien, "estado": None, "transbordo": tipo, "motivo": motivo, "parada": parada,
                   "destino": destino_txt, "pasajeros": len(limpios), "hora": str(d.get("hora") or "")[:5],
                   "tramo": str(d.get("tramo") or "")[:60]}
        cancelar = tipo == "salida" and bool(d.get("cancelar_origen"))
        salida_id = d.get("salida_id")
        reemplazo = {"de": coche_antes, "a": coche_nuevo, "motivo": motivo, "parada": parada, "el": ahora, "por": quien} if tipo == "coche" else None
        entrada["estado"] = "cancelado" if cancelar else None
        _servicio_guardar(conn, fecha, servicio, entrada, estado="cancelado" if cancelar else None,
                          motivo=f"Transbordo: {motivo}" if cancelar else None,
                          coche=coche_nuevo if tipo == "coche" and not salida_id else None, reemplazo=reemplazo)
        cur = conn.execute("""INSERT INTO alpha_transbordos (el, por, fecha, servicio, tipo, motivo, parada, hora, tramo, destino,
                                  coche_antes, coche_nuevo, pasajeros, taller, detalle)
                              VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                           (ahora, quien, fecha, servicio, tipo, motivo, parada, entrada["hora"], entrada["tramo"],
                            destino_txt, coche_antes, coche_nuevo if tipo == "coche" else "", len(limpios), "",
                            json.dumps(detalle, ensure_ascii=False)))
        tid = cur.lastrowid
        conn.commit()
    except Exception:
        _rollback(conn)
        raise
    finally:
        conn.close()
    # Después de guardar: el coche nuevo en el tráfico y el aviso al taller
    trafico_ok = False
    if tipo == "coche" and salida_id:
        try:
            import trafico as tr
            trafico_ok = bool(tr.editar_salida(int(salida_id), {"coche": coche_nuevo}))
        except Exception:
            trafico_ok = False
    taller = ""
    if d.get("avisar_taller") and coche_antes:
        taller = _taller_aviso(coche_antes, f"Se rompió en servicio ({entrada['tramo']} {entrada['hora']} del "
                                            f"{fecha[8:10]}/{fecha[5:7]}{', en ' + parada if parada else ''}): {motivo}", quien)
        if taller:
            conn = get_connection()
            try:
                conn.execute("UPDATE alpha_transbordos SET taller=? WHERE id=?", (taller, tid))
                conn.commit()
            finally:
                conn.close()
    return {"id": tid, "pasajeros": len(detalle), "detalle": detalle, "trafico": trafico_ok, "taller": taller,
            "cancelado": cancelar}, None


def transbordos(fecha="", limite=50):
    conn = get_connection()
    try:
        sql, args = "SELECT * FROM alpha_transbordos", []
        if fecha:
            sql += " WHERE fecha=?"; args.append(fecha)
        filas = [dict(r) for r in conn.execute(sql + " ORDER BY id DESC LIMIT ?", args + [int(limite)]).fetchall()]
        for f in filas:
            f["detalle"] = json.loads(f.get("detalle") or "[]")
        return filas
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
        servicios = {k: {"estado": e["estado"], "motivo": e["motivo"], "por": e["por"], "el": e["el"],
                         "historial": e["historial"] if session.get("rol") == "admin" else [],
                         "reemplazo": e.get("reemplazo_obj") if session.get("rol") == "admin" else None}
                     for k, e in _estados_servicios(conn, fecha).items() if e["estado"] != "abierto" or session.get("rol") == "admin"}
        credito = None
        if _agencia():
            c = _credito(conn, _agencia())
            credito = {k: c[k] for k in ("tope", "saldo", "disponible", "estado", "motivo")}
        return {"fecha": fecha, "ventas": out, "mi_caja_hoy": caja or 0, "reservas": int(res or 0), "ahora": ahora,
                "servicios": servicios, "credito": credito}
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
        for t in ("alpha_movs", "alpha_ventas", "alpha_cierres", "alpha_liquidaciones", "alpha_transbordos", "alpha_servicios"):
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# CAJA
# ════════════════════════════════════════════════════════════════════════════

def _totales(movs):
    """Lo que entró por forma de pago, lo que salió (devoluciones y anulaciones),
    los ingresos y egresos sueltos y el efectivo que tiene que haber en la caja."""
    t = {"pago": {}, "salidas": 0, "efectivoNeto": 0, "boletos": 0, "entradas": 0, "ingresos": 0, "egresos": 0,
         "equipaje": 0}
    for m in movs:
        if m["t"] == "ingreso":
            t["ingresos"] += m["monto"]
        elif m["t"] == "egreso":
            t["egresos"] += -m["monto"]
        elif m["monto"] >= 0:
            t["pago"][m["pago"]] = t["pago"].get(m["pago"], 0) + m["monto"]
            t["entradas"] += m["monto"]
            if m["t"] == "equipaje":
                t["equipaje"] += m["monto"]
        else:
            t["salidas"] += -m["monto"]
        # Una anulación de una venta con tarjeta no saca efectivo de la caja
        if m["pago"] == "efectivo":
            t["efectivoNeto"] += m["monto"]
        if m["t"] in ("venta", "cobro"):
            t["boletos"] += 1
    return t


def movimiento_caja(d):
    """Un ingreso o un egreso que no es de un boleto (I/E de la agencia)."""
    tipo = d.get("tipo")
    if tipo not in MOVS_IE:
        return None, "¿Es un ingreso o un egreso?"
    concepto = " ".join(str(d.get("concepto") or "").split())[:120]
    if not concepto:
        return None, "Poné el concepto"
    monto = _num(d.get("monto"))
    if not 0 < monto <= 50_000_000:
        return None, "El monto no es válido"
    pago = d.get("pago") if d.get("pago") in PAGOS else "efectivo"
    ahora = ahora_iso()
    conn = get_connection()
    try:
        cur = conn.execute("""INSERT INTO alpha_movs (venta_id, t, el, monto, pago, recibe, usuario, vendedor, agencia_id, concepto)
                              VALUES (0,?,?,?,?,NULL,?,?,?,?)""",
                           (tipo, ahora, monto if tipo == "ingreso" else -monto, pago, _yo(), _vendedor(), _agencia(), concepto))
        mid = cur.lastrowid
        conn.commit()
        return {"id": mid, "t": tipo, "el": ahora, "monto": monto if tipo == "ingreso" else -monto, "pago": pago,
                "concepto": concepto}, None
    except Exception:
        _rollback(conn)
        raise
    finally:
        conn.close()


def borrar_movimiento(mid):
    conn = get_connection()
    try:
        m = conn.execute("SELECT * FROM alpha_movs WHERE id=?", (int(mid),)).fetchone()
        if not m or m["t"] not in MOVS_IE:
            return "Ese movimiento no se puede borrar"
        if session.get("rol") != "admin" and m["usuario"] != _yo():
            return "Solo podés borrar tus movimientos"
        if m["cierre_id"] or m["liquidacion_id"]:
            return "Ya está en un cierre de caja o en una liquidación"
        conn.execute("DELETE FROM alpha_movs WHERE id=?", (int(mid),))
        conn.commit()
        return None
    finally:
        conn.close()


def caja(fecha, usuario=""):
    conn = get_connection()
    try:
        sql, args = """SELECT m.*, v.nombre, v.datos FROM alpha_movs m LEFT JOIN alpha_ventas v ON v.id = m.venta_id
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
            m.update(nro=m["venta_id"], origen=d.get("origen") or "", destino=d.get("destino") or "",
                     nombre=m.get("nombre") or m.get("concepto") or "", concepto=m.get("concepto") or "")
            movs.append(m)
        cierres = [dict(r) for r in conn.execute(
            "SELECT * FROM alpha_cierres WHERE fecha=? AND usuario=? ORDER BY hasta", (fecha, usuario)).fetchall()]
        for c in cierres:
            c["tot"] = json.loads(c["tot"] or "{}")
        return {"fecha": fecha, "usuario": usuario, "yo": _yo(),
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
            return {"movs": [], "venta_ef": 0, "venta_tc": 0, "venta_tr": 0, "devoluciones": 0, "ie": 0, "comision": 0,
                    "saldo": 0, "saldo_neto": 0, "boletos": 0, "desde": "", "hasta": hasta}
        movs = [dict(r) for r in conn.execute(
            f"""SELECT m.*, v.datos, v.estado AS estado_venta, v.nombre, v.total AS total_venta FROM alpha_movs m
                LEFT JOIN alpha_ventas v ON v.id = m.venta_id WHERE m.id IN ({','.join('?' * len(ids_movs))}) ORDER BY m.el, m.id""",
            list(ids_movs)).fetchall()]
    else:
        movs = [dict(r) for r in conn.execute(
            """SELECT m.*, v.datos, v.estado AS estado_venta, v.nombre, v.total AS total_venta FROM alpha_movs m
               LEFT JOIN alpha_ventas v ON v.id = m.venta_id
               WHERE m.agencia_id=? AND m.liquidacion_id IS NULL AND m.el <= ? ORDER BY m.el, m.id""",
            (agencia_id, hasta)).fetchall()]
    cache = {}
    tot = {"venta_ef": 0.0, "venta_tc": 0.0, "venta_tr": 0.0, "devoluciones": 0.0, "ie": 0.0, "comision": 0.0, "boletos": 0}
    det = []
    for m in movs:
        d = json.loads(m.pop("datos") or "{}")
        com, com_txt = 0.0, ""
        if m["t"] in MOVS_IE:
            tot["ie"] += m["monto"]          # ingresos y egresos de la agencia
        elif m["monto"] >= 0:
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
                    "vendedor": m["vendedor"], "nombre": m["nombre"] or m.get("concepto") or "", "comision": com, "comision_txt": com_txt,
                    "origen": d.get("origen") or "", "destino": d.get("destino") or "", "fecha": d.get("fecha") or "",
                    "sale": d.get("sale") or "", "asiento": d.get("asiento"), "estado_venta": m["estado_venta"]})
    saldo = tot["venta_ef"] + tot["venta_tc"] + tot["venta_tr"] - tot["devoluciones"] + tot["ie"]
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
                                     venta_ef, venta_tc, venta_tr, devoluciones, ie, comision, saldo, saldo_neto, boletos, estado)
                                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'pendiente')""",
                               (aid, (ags.get(aid) or {}).get("nombre") or f"Agencia {aid}", t["desde"], hasta, ahora_iso(),
                                quien[:80], 1 if solo_ef else 0, t["venta_ef"], t["venta_tc"], t["venta_tr"],
                                t["devoluciones"], t["ie"], t["comision"], t["saldo"], t["saldo_neto"], t["boletos"]))
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


def control_agencias():
    """Cada agencia: lo que tiene sin liquidar, lo liquidado sin depositar, el
    tope de su contrato y cuánto usó, la última liquidación y el contrato."""
    hoy = ahora_iso()[:10]
    conn = get_connection()
    try:
        try:
            ags = [dict(r) for r in conn.execute(
                "SELECT id, nombre, ciudad, estado, estado_motivo FROM agencias ORDER BY nombre").fetchall()]
        except Exception:
            _rollback(conn)
            ags = []
        sinliq = {r["agencia_id"]: dict(r) for r in conn.execute(
            """SELECT agencia_id, COALESCE(SUM(monto), 0) AS m, MIN(el) AS desde, COUNT(*) AS n FROM alpha_movs
               WHERE agencia_id IS NOT NULL AND liquidacion_id IS NULL GROUP BY agencia_id""").fetchall()}
        pend = {r["agencia_id"]: dict(r) for r in conn.execute(
            """SELECT agencia_id, COALESCE(SUM(saldo_neto), 0) AS m, MIN(el) AS desde, COUNT(*) AS n FROM alpha_liquidaciones
               WHERE estado <> 'depositada' GROUP BY agencia_id""").fetchall()}
        ult = {r["agencia_id"]: r["el"] for r in conn.execute(
            "SELECT agencia_id, MAX(el) AS el FROM alpha_liquidaciones GROUP BY agencia_id").fetchall()}
        hoy_v = {r["agencia_id"]: dict(r) for r in conn.execute(
            """SELECT agencia_id, COALESCE(SUM(monto), 0) AS m, SUM(CASE WHEN t IN ('venta', 'cobro') THEN 1 ELSE 0 END) AS boletos
               FROM alpha_movs WHERE agencia_id IS NOT NULL AND el >= ? AND el < ? GROUP BY agencia_id""",
            (hoy, hoy + "T99")).fetchall()}
        contratos = {}
        try:
            for r in conn.execute("""SELECT agencia_id, tope_sin_depositar, hasta, comision_tipo, comision, desde
                                     FROM agencia_contratos WHERE desde <= ? AND COALESCE(anulado, 0) = 0
                                     ORDER BY agencia_id, desde DESC, id DESC""", (hoy,)).fetchall():
                contratos.setdefault(r["agencia_id"], dict(r))
        except Exception:
            _rollback(conn)
        filas = []
        for a in ags:
            aid = a["id"]
            if a["estado"] == "baja" and aid not in sinliq and aid not in pend:
                continue
            c, sl, pd = contratos.get(aid) or {}, sinliq.get(aid) or {}, pend.get(aid) or {}
            tope = _num(c.get("tope_sin_depositar"))
            saldo = _num(sl.get("m")) + _num(pd.get("m"))
            filas.append({
                "id": aid, "nombre": a["nombre"], "ciudad": a.get("ciudad") or "", "estado": a.get("estado") or "activa",
                "motivo": a.get("estado_motivo") or "", "tope": tope, "sin_liquidar": _num(sl.get("m")),
                "sin_liq_desde": sl.get("desde") or "", "sin_depositar": _num(pd.get("m")),
                "liq_pendientes": int(pd.get("n") or 0), "debe_desde": pd.get("desde") or "", "saldo": saldo,
                "porc": round(saldo * 100 / tope, 1) if tope > 0 else None,
                "ultima_liq": ult.get(aid) or "", "contrato": bool(c), "contrato_hasta": c.get("hasta") or "",
                "comision": (f"{_num(c.get('comision')):g} %" if (c.get("comision_tipo") or "porcentaje") == "porcentaje"
                             else f"Gs. {_gs(c.get('comision'))} por pasaje") if c else "",
                "hoy": _num((hoy_v.get(aid) or {}).get("m")), "boletos_hoy": int((hoy_v.get(aid) or {}).get("boletos") or 0)})
        tot = {k: sum(f[k] for f in filas) for k in ("sin_liquidar", "sin_depositar", "saldo", "hoy")}
        tot["depositado"] = _num(conn.execute(
            "SELECT COALESCE(SUM(saldo_neto), 0) AS m FROM alpha_liquidaciones WHERE estado = 'depositada'").fetchone()["m"])
        return {"agencias": filas, "totales": tot, "hoy": hoy}
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# RECAUDACIÓN (solo administración)
#   por servicio: lo que dejó cada salida (por la fecha del viaje), con el
#                 detalle de qué agencia vendió cuánto
#   por agencia:  la plata que movió cada agencia y vendedor en esas fechas
#   por día:      la plata de cada día
# ════════════════════════════════════════════════════════════════════════════

def _config(conn, clave, defecto):
    try:
        r = conn.execute("SELECT valor FROM alpha_config WHERE clave=?", (clave,)).fetchone()
        return json.loads(r["valor"]) if r else defecto
    except Exception:
        _rollback(conn)
        return defecto


def _asientos_plano(planos, cod):
    p = planos.get(cod) or {}
    return sum(1 for piso in p.get("pisos") or [] for f in piso.get("filas") or [] for n in f if n is not None)


def recaudacion(desde, hasta, por):
    conn = get_connection()
    try:
        ags = _agencias(conn)

        def nombre_ag(aid):
            return (ags.get(aid) or {}).get("nombre") or (f"Agencia {aid}" if aid else "Administración")

        if por == "servicio":
            planos = _config(conn, "planos", {})
            filas = [dict(r) for r in conn.execute(
                """SELECT * FROM alpha_ventas WHERE fecha >= ? AND fecha <= ? AND estado IN ('vendido', 'devuelto')
                   ORDER BY fecha, id""", (desde, hasta)).fetchall()]
            svs = {}
            for f in filas:
                d = json.loads(f["datos"] or "{}")
                s = svs.get((f["fecha"], f["servicio"]))
                if not s:
                    s = svs[(f["fecha"], f["servicio"])] = {
                        "fecha": f["fecha"], "servicio": f["servicio"], "hora": d.get("hora") or "",
                        "tramo": d.get("tramo") or "", "cor": d.get("cor") or "", "lado": d.get("lado") or "",
                        "coche": d.get("coche") or "", "asientos": _asientos_plano(planos, d.get("plano")),
                        "pasajeros": 0, "parados": 0, "menores": 0, "devueltos": 0, "boletos": 0.0,
                        "retenido": 0.0, "equipaje": 0.0, "total": 0.0, "agencias": {}}
                if not s["coche"] and d.get("coche"):
                    s["coche"] = d["coche"]           # las ventas de agencias no guardan el coche
                eq = sum(_num(e.get("monto")) for e in d.get("equipaje") or [])
                ag = s["agencias"].setdefault(nombre_ag(f["agencia_id"]), {"pasajeros": 0, "total": 0.0})
                s["equipaje"] += eq
                if f["estado"] == "vendido":
                    s["pasajeros"] += 1
                    s["boletos"] += f["total"] or 0
                    s["parados"] += 1 if f["asiento"] == "P" else 0
                    s["menores"] += 1 if d.get("menor") else 0
                    ag["pasajeros"] += 1
                    ag["total"] += (f["total"] or 0) + eq
                else:
                    # Del boleto devuelto queda lo que se retuvo
                    ret = max(0.0, (f["total"] or 0) - _num(d.get("devuelto")))
                    s["devueltos"] += 1
                    s["retenido"] += ret
                    ag["total"] += ret + eq
            for s in svs.values():
                s["total"] = s["boletos"] + s["retenido"] + s["equipaje"]
                s["agencias"] = sorted(({"agencia": k, **v} for k, v in s["agencias"].items()), key=lambda x: -x["total"])
            lista = sorted(svs.values(), key=lambda s: (s["fecha"], s["hora"], s["tramo"]))
            return {"por": por, "desde": desde, "hasta": hasta, "filas": lista}

        movs = [dict(r) for r in conn.execute(
            "SELECT * FROM alpha_movs WHERE el >= ? AND el < ? ORDER BY el, id", (desde, hasta + "T99")).fetchall()]
        grupos = {}
        for m in movs:
            if por == "dia":
                k, base = m["el"][:10], {"fecha": m["el"][:10]}
            else:
                k = (m["agencia_id"] or 0, m["usuario"] or "")
                base = {"agencia": nombre_ag(m["agencia_id"]), "agencia_id": m["agencia_id"],
                        "vendedor": m["vendedor"] or m["usuario"] or "", "usuario": m["usuario"] or ""}
            g = grupos.setdefault(k, dict(base, boletos=0, efectivo=0.0, tarjeta=0.0, transferencia=0.0,
                                          equipaje=0.0, salidas=0.0, ie=0.0, neto=0.0))
            if m["t"] in MOVS_IE:
                g["ie"] += m["monto"]
            elif m["monto"] >= 0:
                g[m["pago"] if m["pago"] in PAGOS else "efectivo"] += m["monto"]
                g["equipaje"] += m["monto"] if m["t"] == "equipaje" else 0
            else:
                g["salidas"] += -m["monto"]
            g["boletos"] += 1 if m["t"] in ("venta", "cobro") else 0
            g["neto"] += m["monto"]
        if por == "dia":
            lista = sorted(grupos.values(), key=lambda g: g["fecha"])
        else:
            lista = sorted(grupos.values(), key=lambda g: (1 if g["agencia_id"] else 0, _norm(g["agencia"]), _norm(g["vendedor"])))
        return {"por": por, "desde": desde, "hasta": hasta, "filas": lista}
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# EL BOLETO EN PDF (para mandárselo al pasajero por WhatsApp o por correo)
# ════════════════════════════════════════════════════════════════════════════

DIAS_TXT = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
MESES_TXT = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "setiembre", "octubre",
             "noviembre", "diciembre")
BOLETO_DEF = {"presentarse_min": 15, "equipaje_kg": 20, "telefono": "", "leyenda": ""}


def _dia_txt(f):
    from datetime import date as _d
    try:
        x = _d.fromisoformat(f)
    except ValueError:
        return f
    return f"{DIAS_TXT[x.weekday()].capitalize()} {x.day} de {MESES_TXT[x.month - 1]}"


def _gs(n):
    return f"{round(n or 0):,}".replace(",", ".")


def pdf_boleto(v, cfg_boleto, descuentos):
    """El original del boleto en una tira de 80 mm, como el impreso."""
    import io
    import os
    from reportlab.lib.units import mm
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfgen import canvas

    W, M = 80 * mm, 5 * mm
    ops, y = [], [M]          # cada dibujo se guarda con su altura desde arriba; al final se sabe el alto

    def txt(x, s, font="Helvetica", size=9, align="l", color=(0, 0, 0), dy=None):
        ops.append(("t", x, y[0] + (dy if dy is not None else size), str(s), font, size, align, color))

    def baja(h):
        y[0] += h

    def parrafo(s, size=8, font="Helvetica", ancho=W - 2 * M, interl=1.3):
        for linea in simpleSplit(str(s), font, size, ancho):
            txt(M, linea, font, size)
            baja(size * interl)

    def corte():
        baja(2.5 * mm)
        ops.append(("dash", y[0]))
        baja(2.5 * mm)

    d = v
    nro = f"001-001-{int(d['nro']):07d}"
    em = (d.get("cambios") or [{}])[-1].get("el") if d.get("cambios") else d.get("vendido_en")
    em = em or ahora_iso()
    sale, llega = d.get("sale") or d.get("hora") or "", d.get("llega") or ""
    desc = next((x for x in descuentos if x.get("id") == d.get("tarifa")), None)
    tarifa = (desc or {}).get("nombre") or "General"
    pago = {"efectivo": "efectivo", "tarjeta": "tarjeta", "transferencia": "transferencia"}.get(d.get("pago"), "efectivo")
    asd = d.get("asDesc") or {}
    parado = str(d.get("asiento")) == "P"

    logo = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "logo.png")
    if os.path.exists(logo):
        ops.append(("img", logo, M, y[0], 16 * mm, 11 * mm))
    txt(M + 19 * mm, "La Santaniana", "Helvetica-Bold", 15, dy=(5.5 if cfg_boleto.get("telefono") else 7) * mm)
    if cfg_boleto.get("telefono"):
        txt(M + 19 * mm, f"Tel. {cfg_boleto['telefono']}", "Helvetica", 8, dy=9.5 * mm)
    baja(12 * mm)
    corte()
    txt(M, f"Boleto {nro}", "Helvetica-Bold", 10)
    txt(W - M, f"{em[8:10]}/{em[5:7]}/{em[:4]} {em[11:16]}", "Helvetica", 8, "r")
    baja(5 * mm)
    txt(M, _dia_txt(d.get("fecha") or ""), "Helvetica-Bold", 14)
    baja(7.5 * mm)
    for lugar, hora, lleno in ((d.get("origen") or "", sale, True), (d.get("destino") or "", llega, False)):
        ops.append(("punto", M + 1.6 * mm, y[0] + 3 * mm, lleno))
        txt(M + 5 * mm, lugar.upper()[:22], "Helvetica-Bold", 17)
        txt(W - M, hora, "Helvetica-Bold", 17, "r")
        baja(7.5 * mm)
        if lleno:
            serv = f"Servicio {d.get('tramo') or ''}."
            if llega:
                serv += f" {'Llega el ' + d['llegaDia'] + '; la hora' if d.get('llegaDia') else 'La llegada'} es aproximada."
            for linea in simpleSplit(serv, "Helvetica", 7.5, W - 2 * M - 5 * mm):
                txt(M + 5 * mm, linea, "Helvetica", 7.5)
                baja(3.4 * mm)
            baja(1.5 * mm)
    corte()
    ops.append(("caja", M, y[0], 22 * mm, 17 * mm))
    if parado:
        txt(M + 11 * mm, "Pasaje", "Helvetica-Bold", 7, "c", (1, 1, 1), dy=4.5 * mm)
        txt(M + 11 * mm, "PARADO", "Helvetica-Bold", 12, "c", (1, 1, 1), dy=11.5 * mm)
    else:
        txt(M + 11 * mm, "Asiento", "Helvetica-Bold", 7, "c", (1, 1, 1), dy=4 * mm)
        txt(M + 11 * mm, str(d.get("asiento")), "Helvetica-Bold", 26, "c", (1, 1, 1), dy=14.5 * mm)
    x2 = M + 25 * mm
    txt(x2, asd.get("piso") or ("Parado" if parado else ""), "Helvetica-Bold", 12, dy=5 * mm)
    txt(x2, asd.get("pos") or "", "Helvetica", 9, dy=9.5 * mm)
    txt(x2, asd.get("tipo") or "", "Helvetica", 8, dy=13.5 * mm)
    baja(17 * mm)
    corte()
    txt(M, d.get("nombre") or "", "Helvetica-Bold", 12)
    baja(5 * mm)
    doc = f"{d.get('tipoDoc')} {d.get('doc')}" if d.get("mig") else f"CI {d.get('doc') or ''}"
    txt(M, doc, "Helvetica", 9)
    baja(4.5 * mm)
    if d.get("menor"):
        m = d["menor"]
        parrafo(f"Con un menor en brazos (sin asiento): {m.get('nombre')}"
                f"{', ' + str(m['edad']) + ' años' if m.get('edad') is not None else ''}{', doc. ' + m['doc'] if m.get('doc') else ''}", 8)
    bultos = int(d.get("bultos") or 0) + sum(int(e.get("bultos") or 0) for e in d.get("equipaje") or [])
    if bultos:
        parrafo(f"Bultos en bodega: {bultos}", 8)
    corte()
    txt(M, f"{asd.get('tipo') or 'Pasaje'}, tarifa {tarifa.lower()}", "Helvetica", 8.5)
    txt(W - M, _gs(d.get("total")), "Helvetica", 8.5, "r")
    baja(6 * mm)
    txt(M, "Total Gs.", "Helvetica-Bold", 10, dy=7 * mm)
    txt(W - M, _gs(d.get("total")), "Helvetica-Bold", 20, "r", dy=7 * mm)
    baja(9 * mm)
    parrafo(f"Pagó con {pago}. Vendió {d.get('vendedor') or ''}.", 7.5)
    corte()
    nota = (f"Mostrá este boleto al subir. Presentate {cfg_boleto.get('presentarse_min') or 15} minutos antes de la salida. "
            f"Equipaje incluido: {cfg_boleto.get('equipaje_kg') or 20} kg.")
    if d.get("mig"):
        nota += " Viajá con el mismo documento que figura acá."
    if cfg_boleto.get("leyenda"):
        nota += " " + cfg_boleto["leyenda"]
    parrafo(nota, 7.5)
    baja(2 * mm)
    ops.append(("barra", y[0], 10 * mm))
    txt(M, "Original", "Helvetica-Bold", 13, "l", (1, 1, 1), dy=6.8 * mm)
    txt(W - M, "para el pasajero", "Helvetica", 8, "r", (1, 1, 1), dy=6.5 * mm)
    baja(13 * mm)
    txt(W / 2, "Copia digital · Maqueta de Alpha: sin valor fiscal", "Helvetica", 6.5, "c")
    baja(5 * mm)

    H = y[0] + M
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setTitle(f"Boleto {nro}")
    for op in ops:
        k = op[0]
        if k == "t":
            _, x, yt, s, font, size, align, color = op
            c.setFillColorRGB(*color)
            c.setFont(font, size)
            (c.drawRightString if align == "r" else c.drawCentredString if align == "c" else c.drawString)(x, H - yt, s)
        elif k == "dash":
            c.setDash(2, 2); c.setLineWidth(0.8); c.setStrokeColorRGB(0, 0, 0)
            c.line(M, H - op[1], W - M, H - op[1]); c.setDash()
        elif k == "img":
            try:
                c.drawImage(op[1], op[2], H - op[3] - op[5], op[4], op[5], preserveAspectRatio=True, mask="auto")
            except Exception:
                pass
        elif k == "punto":
            _, x, yc, lleno = op
            c.setFillColorRGB(0, 0, 0); c.setLineWidth(1.6)
            c.circle(x, H - yc, 1.5 * mm, stroke=1, fill=1 if lleno else 0)
        elif k == "caja":
            _, x, yt, w, h = op
            c.setFillColorRGB(0, 0, 0)
            c.rect(x, H - yt - h, w, h, stroke=0, fill=1)
        elif k == "barra":
            _, yt, h = op
            c.setFillColorRGB(0, 0, 0)
            c.rect(0, H - yt - h, W, h, stroke=0, fill=1)
    c.showPage()
    c.save()
    buf.seek(0)
    return buf, nro


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
    if accion not in ("cobrar", "liberar", "anular", "devolver", "cambiar", "reimpresion", "equipaje", "embarque",
                      "desbloquear"):
        return _no("No sé qué hacer con eso", 400)
    d = request.get_json(silent=True) or {}
    v, err = accion_venta(vid, accion, d)
    if err:
        return _no(err, 409 if "tomado" in err else 400)
    if accion != "embarque":     # el embarque se marca uno por uno: no llena la auditoría
        nombres = {"cobrar": "cobró la reserva", "liberar": "liberó la reserva", "anular": "anuló", "devolver": "devolvió",
                   "cambiar": "cambió", "reimpresion": "reimprimió el boleto", "equipaje": "agregó equipaje al boleto"}
        if accion == "desbloquear":
            _auditar(f"Alpha: desbloqueó el asiento {v.get('asiento')}", f"{v.get('fecha')} {v.get('sale') or v.get('hora')} {v.get('tramo')}")
        else:
            extra = ""
            if accion == "reimpresion":
                extra = f" (vez {len(v.get('reimpresiones') or [])})"
            elif accion == "equipaje":
                extra = f" (Gs. {_gs(_num(d.get('monto')))})"
            _auditar(f"Alpha: {nombres[accion]} {vid:07d}{extra}", v.get("nombre"))
    return jsonify({"ok": True, "venta": v})


@bp_alpha_ventas.route("/api/alpha/ventas/<int:vid>", methods=["GET"])
def api_una(vid):
    if not _rol():
        return _no()
    v = una(vid)
    return jsonify({"ok": True, "venta": v}) if v else _no("Ese boleto no existe o es de otra agencia", 404)


@bp_alpha_ventas.route("/api/alpha/ventas/<int:vid>/pdf", methods=["GET"])
def api_pdf(vid):
    if not _rol():
        return _no()
    v = una(vid)
    if not v or v.get("estado") != "vendido":
        return _no("Ese boleto no existe, no está vendido o es de otra agencia", 404)
    from flask import send_file
    conn = get_connection()
    try:
        cfg = dict(BOLETO_DEF, **(_config(conn, "boleto", {}) or {}))
        descuentos = _config(conn, "descuentos", []) or []
    finally:
        conn.close()
    buf, nro = pdf_boleto(v, cfg, descuentos)
    return send_file(buf, mimetype="application/pdf", as_attachment=request.args.get("descargar") == "1",
                     download_name=f"boleto-{nro}.pdf")


@bp_alpha_ventas.route("/api/alpha/bloqueos", methods=["POST"])
def api_bloquear():
    if session.get("rol") != "admin":
        return _no("Los asientos los bloquea administración")
    d = request.get_json(silent=True) or {}
    v, err = bloquear(d)
    if err:
        return _no(err, 409)
    _auditar(f"Alpha: bloqueó el asiento {v.get('asiento')}", f"{v.get('fecha')} {v.get('sale') or v.get('hora')} {v.get('tramo')}: {v.get('motivo')}")
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


@bp_alpha_ventas.route("/api/alpha/caja/movimiento", methods=["POST"])
def api_movimiento():
    if not _rol():
        return _no()
    if session.get("rol") == "agencia" and not _agencia():
        return _no("Tu usuario no tiene una agencia asignada")
    m, err = movimiento_caja(request.get_json(silent=True) or {})
    if err:
        return _no(err, 400)
    _auditar(f"Alpha: registró un {m['t']} de caja", f"{m['concepto']}: Gs. {_gs(abs(m['monto']))}")
    return jsonify({"ok": True, "mov": m})


@bp_alpha_ventas.route("/api/alpha/caja/movimiento/<int:mid>", methods=["DELETE"])
def api_borrar_movimiento(mid):
    if not _rol():
        return _no()
    err = borrar_movimiento(mid)
    if err:
        return _no(err, 400)
    _auditar(f"Alpha: borró el movimiento de caja {mid}")
    return jsonify({"ok": True})


@bp_alpha_ventas.route("/api/alpha/servicios/estado", methods=["POST"])
def api_estado_servicio():
    if session.get("rol") != "admin":
        return _no("El estado de los servicios lo maneja administración")
    e, err = estado_servicio(request.get_json(silent=True) or {})
    if err:
        return _no(err, 400)
    txt = {"abierto": "abrió la venta de", "cerrado": "cerró la venta de", "cancelado": "canceló"}[e["estado"]]
    ult = e["historial"][-1]
    _auditar(f"Alpha: {txt} {ult.get('tramo') or 'un servicio'} {ult.get('hora')}", f"{e['fecha']} {e['motivo']}")
    return jsonify({"ok": True, "servicio": e})


@bp_alpha_ventas.route("/api/alpha/transbordos", methods=["GET"])
def api_transbordos():
    if session.get("rol") != "admin":
        return _no("Los transbordos los ve administración")
    f = request.args.get("fecha") or ""
    if f and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", f):
        return _no("Fecha inválida", 400)
    return jsonify({"transbordos": transbordos(f)})


@bp_alpha_ventas.route("/api/alpha/transbordos", methods=["POST"])
def api_transbordo():
    if session.get("rol") != "admin":
        return _no("Los transbordos los hace administración")
    d = request.get_json(silent=True) or {}
    r, err = aplicar_transbordo(d)
    if err:
        return _no(err, 409 if "ocupado" in err or "ya no está" in err or "parados" in err else 400)
    _auditar(f"Alpha: transbordo de {r['pasajeros']} pasajero(s) " + ("a otro coche" if d.get("tipo") == "coche" else "a otra salida"),
             f"{d.get('tramo')} {d.get('hora')} {d.get('fecha')}: {d.get('motivo')}")
    return jsonify(dict(r, ok=True))


@bp_alpha_ventas.route("/api/alpha/control/agencias", methods=["GET"])
def api_control_agencias():
    if session.get("rol") != "admin":
        return _no("El control de agencias lo ve solo administración")
    return jsonify(control_agencias())


@bp_alpha_ventas.route("/api/alpha/recaudacion", methods=["GET"])
def api_recaudacion():
    if session.get("rol") != "admin":
        return _no("La recaudación la ve solo administración")
    a = request.args
    hoy = ahora_iso()[:10]
    desde, hasta = a.get("desde") or hoy, a.get("hasta") or a.get("desde") or hoy
    if not (re.fullmatch(r"\d{4}-\d{2}-\d{2}", desde) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", hasta)):
        return _no("Fechas inválidas", 400)
    if hasta < desde:
        desde, hasta = hasta, desde
    por = a.get("por") if a.get("por") in ("servicio", "agencia", "dia") else "servicio"
    return jsonify(recaudacion(desde, hasta, por))


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
