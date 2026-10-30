"""
compras_reposicion.py — Reposición del depósito (La Santaniana)

Lo que está en el mínimo o sin stock se pide al proveedor sin que haya una
OT de por medio:

  1. «Para pedir»: los repuestos bajo el mínimo, con la cantidad sugerida
     (hasta el doble del mínimo, descontando lo que ya está pedido) y el
     proveedor más barato con su último precio.
  2. Se arma el pedido: uno por proveedor, con el texto para WhatsApp.
  3. Cuando llega se registra lo que vino (todo o una parte), a qué precio y
     con qué factura: entra al stock a ese costo, el precio queda como el
     último de ese proveedor y la factura se carga en Tesorería.

Rutas (Compras):
  GET  /api/compras/reposicion                 pedidos abiertos y recientes
  GET  /api/compras/reposicion/sugerido        lo que hay que pedir
  POST /api/compras/reposicion                 {items:[{repuesto_id, cantidad, proveedor, precio}]}
  POST /api/compras/reposicion/<id>/recibir    {items:[{id, cantidad, precio}], factura:{...}}
  POST /api/compras/reposicion/<id>/anular

Enganche en app.py:
    from compras_reposicion import bp_reposicion, init_compras_reposicion
    init_compras_reposicion()
    app.register_blueprint(bp_reposicion)
"""

import math
import re
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, session

from db_compat import get_connection, USE_POSTGRES

bp_reposicion = Blueprint("compras_reposicion", __name__)
PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"


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


def _quien():
    return session.get("nombre") or session.get("usuario") or ""


def _num(v):
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v or "").strip()
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    elif t.count(".") >= 1 and len(t.split(".")[-1]) == 3:
        t = t.replace(".", "")          # 85.000 → 85000
    try:
        return float(t or 0)
    except ValueError:
        return 0.0


def init_compras_reposicion():
    conn = get_connection()
    try:
        conn.execute(f"""CREATE TABLE IF NOT EXISTS compras_repo (
            id {PK},
            proveedor TEXT DEFAULT '',
            estado TEXT DEFAULT 'pedido',       -- pedido | parcial | recibido | anulado
            total REAL DEFAULT 0,
            nota TEXT DEFAULT '',
            creado_por TEXT DEFAULT '',
            creado_el TEXT DEFAULT '',
            recibido_el TEXT DEFAULT '',
            factura TEXT DEFAULT '')""")
        conn.execute(f"""CREATE TABLE IF NOT EXISTS compras_repo_items (
            id {PK},
            repo_id INTEGER NOT NULL,
            repuesto_id INTEGER NOT NULL,
            descripcion TEXT DEFAULT '',
            codigo TEXT DEFAULT '',
            cantidad REAL DEFAULT 0,
            precio REAL DEFAULT 0,
            recibido REAL DEFAULT 0,
            recibido_el TEXT DEFAULT '')""")
        conn.commit()
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS ix_crepo_items ON compras_repo_items (repo_id)")
            conn.commit()
        except Exception:
            _rollback(conn)
    except Exception as e:
        _rollback(conn)
        print(f"[compras_reposicion] init: {e}")
    finally:
        conn.close()


def _pedido_abierto(conn):
    """{repuesto_id: cantidad pedida que todavía no llegó}"""
    out = {}
    for r in conn.execute("""SELECT i.repuesto_id, SUM(i.cantidad - i.recibido) AS q FROM compras_repo_items i
                             JOIN compras_repo p ON p.id = i.repo_id
                             WHERE p.estado IN ('pedido','parcial') AND i.cantidad > i.recibido
                             GROUP BY i.repuesto_id""").fetchall():
        out[r["repuesto_id"]] = float(r["q"] or 0)
    return out


def sugerido():
    """Lo que está en el mínimo o sin stock, con cuánto pedir y a quién."""
    import repuestos_db as rdb
    import repuestos_multi as multi
    todos = rdb.obtener_repuestos(solo_bajos=True)
    conn = get_connection()
    try:
        pedido = _pedido_abierto(conn)
    finally:
        conn.close()
    con_min, sin_min = [], []
    for r in todos:
        stock = float(r.get("stock_actual") or 0)
        minimo = float(r.get("stock_minimo") or 0)
        ya = pedido.get(r["id"], 0)
        if minimo > 0:
            sug = max(0, math.ceil(2 * minimo - stock - ya))
        else:
            sug = 0 if ya else 1
        provs = multi.lista(r["id"], r.get("proveedor") or "")
        con_precio = [p for p in provs if p["precio"] > 0]
        elegido = min(con_precio, key=lambda p: p["precio"]) if con_precio else (provs[0] if provs else None)
        x = {
            "id": r["id"], "codigo": r.get("codigo") or "", "descripcion": r.get("descripcion") or "",
            "marca": r.get("marca") or "", "categoria": r.get("categoria") or "", "unidad": r.get("unidad") or "u",
            "stock": stock, "minimo": minimo, "en_pedido": ya, "sugerido": sug,
            "estado": r.get("estado_stock"), "ubicacion": r.get("ubicacion") or "",
            "proveedor": (elegido["proveedor"] if elegido else (r.get("proveedor") or "")),
            "precio": (elegido["precio"] if elegido and elegido["precio"] else float(r.get("costo_unitario") or 0)),
            "proveedores": [{"proveedor": p["proveedor"], "fantasia": p.get("fantasia") or "", "precio": p["precio"],
                             "mas_barato": p.get("mas_barato")} for p in provs],
        }
        (con_min if minimo > 0 else sin_min).append(x)
    orden = lambda x: (x["en_pedido"] >= x["sugerido"] and x["sugerido"] == 0, x["estado"] != "sin_stock", x["categoria"], x["descripcion"])
    con_min.sort(key=orden)
    sin_min.sort(key=lambda x: (x["categoria"], x["descripcion"]))
    return {"con_minimo": con_min, "sin_minimo": sin_min}


def _contacto(conn, proveedor):
    try:
        import repuestos_multi as multi
        c = conn.execute("SELECT nombre, fantasia, contacto, telefono, ruc FROM repuestos_proveedores WHERE clave=?",
                         (multi._clave(proveedor),)).fetchone()
        return dict(c) if c else {}
    except Exception:
        _rollback(conn)
        return {}


def crear(items, quien=""):
    """Un pedido por proveedor con los repuestos elegidos."""
    grupos = {}
    for x in items or []:
        try:
            rid = int(x.get("repuesto_id") or 0)
        except (TypeError, ValueError):
            continue
        q = _num(x.get("cantidad"))
        if not rid or q <= 0:
            continue
        prov = " ".join(str(x.get("proveedor") or "").split())[:160]
        grupos.setdefault(prov.lower(), {"proveedor": prov, "items": []})["items"].append(
            {"repuesto_id": rid, "cantidad": q, "precio": max(0.0, _num(x.get("precio")))})
    if not grupos:
        return {"ok": False, "msg": "Elegí al menos un repuesto con cantidad"}
    sin_prov = [g for k, g in grupos.items() if not k]
    if sin_prov:
        return {"ok": False, "msg": "A cada repuesto ponele a quién se le pide (proveedor)"}
    conn = get_connection()
    creados = []
    try:
        for g in grupos.values():
            total = sum(i["cantidad"] * i["precio"] for i in g["items"])
            cur = conn.execute("""INSERT INTO compras_repo (proveedor, estado, total, creado_por, creado_el)
                                  VALUES (?, 'pedido', ?, ?, ?)""", (g["proveedor"], round(total), quien, _ahora()))
            pid = cur.lastrowid or conn.execute("SELECT MAX(id) AS m FROM compras_repo").fetchone()["m"]
            for i in g["items"]:
                r = conn.execute("SELECT codigo, descripcion FROM repuestos WHERE id=?", (i["repuesto_id"],)).fetchone()
                if not r:
                    continue
                conn.execute("""INSERT INTO compras_repo_items (repo_id, repuesto_id, descripcion, codigo, cantidad, precio)
                                VALUES (?,?,?,?,?,?)""", (pid, i["repuesto_id"], r["descripcion"] or "", r["codigo"] or "",
                                                         i["cantidad"], i["precio"]))
            creados.append(pid)
        conn.commit()
    except Exception as e:
        _rollback(conn)
        return {"ok": False, "msg": f"No se pudo armar el pedido: {e}"}
    finally:
        conn.close()
    return {"ok": True, "pedidos": creados,
            "msg": f"{len(creados)} pedido{'s' if len(creados) != 1 else ''} armado{'s' if len(creados) != 1 else ''}"}


def listar(dias=30):
    desde = (date.today() - timedelta(days=dias)).isoformat()
    conn = get_connection()
    try:
        peds = [dict(r) for r in conn.execute("""SELECT * FROM compras_repo
                                                 WHERE estado IN ('pedido','parcial') OR (estado='recibido' AND recibido_el >= ?)
                                                 ORDER BY CASE WHEN estado IN ('pedido','parcial') THEN 0 ELSE 1 END, id DESC""",
                                              (desde,)).fetchall()]
        ids = [p["id"] for p in peds]
        items = {}
        if ids:
            for r in conn.execute(f"""SELECT i.*, COALESCE(x.unidad,'u') AS unidad, COALESCE(x.stock_actual,0) AS stock
                                      FROM compras_repo_items i LEFT JOIN repuestos x ON x.id = i.repuesto_id
                                      WHERE i.repo_id IN ({','.join('?' * len(ids))}) ORDER BY i.id""", ids).fetchall():
                items.setdefault(r["repo_id"], []).append(dict(r))
        codprov = {}
        try:
            import repuestos_multi as multi
            for r in conn.execute("SELECT repuesto_id, clave, codigo_prov FROM repuestos_por_proveedor WHERE COALESCE(codigo_prov,'')<>''").fetchall():
                codprov[(r["repuesto_id"], r["clave"])] = r["codigo_prov"]
        except Exception:
            _rollback(conn)
            multi = None
        for p in peds:
            p["items"] = items.get(p["id"], [])
            p["contacto"] = _contacto(conn, p["proveedor"])
            if multi:
                k = multi._clave(p["proveedor"])
                for i in p["items"]:
                    i["codigo_prov"] = codprov.get((i["repuesto_id"], k), "")
            p["pendiente"] = sum(max(0, float(i["cantidad"]) - float(i["recibido"])) for i in p["items"])
    finally:
        conn.close()
    return peds


def recibir(pid, d, quien=""):
    """Lo que llegó del pedido: entra al stock a ese costo y la factura
    va a Tesorería."""
    import repuestos_db as rdb
    import repuestos_multi as multi
    conn = get_connection()
    try:
        p = conn.execute("SELECT * FROM compras_repo WHERE id=?", (pid,)).fetchone()
        if not p:
            return {"ok": False, "msg": "Ese pedido ya no existe"}
        p = dict(p)
        if p["estado"] not in ("pedido", "parcial"):
            return {"ok": False, "msg": "Ese pedido ya está cerrado"}
        items = {r["id"]: dict(r) for r in conn.execute("SELECT * FROM compras_repo_items WHERE repo_id=?", (pid,)).fetchall()}
    finally:
        conn.close()
    llegaron, problemas, total = 0, [], 0.0
    ahora = _ahora()
    for x in d.get("items") or []:
        try:
            iid = int(x.get("id"))
        except (TypeError, ValueError):
            continue
        it = items.get(iid)
        q = _num(x.get("cantidad"))
        if not it or q <= 0:
            continue
        precio = _num(x.get("precio")) if x.get("precio") not in (None, "") else float(it["precio"] or 0)
        ok, res = rdb.registrar_movimiento(it["repuesto_id"], "entrada", q,
                                           motivo=f"Reposición: pedido #{pid} a {p['proveedor']}",
                                           costo_unitario=precio, referencia=f"reposicion:{pid}", usuario=quien)
        if not ok:
            problemas.append(f"{it['descripcion']}: {res}")
            continue
        if precio > 0:
            try:
                multi.agregar(it["repuesto_id"], p["proveedor"], precio=precio)
            except Exception:
                pass
        conn = get_connection()
        try:
            conn.execute("UPDATE compras_repo_items SET recibido = COALESCE(recibido,0) + ?, precio=?, recibido_el=? WHERE id=?",
                         (q, precio, ahora, iid))
            conn.commit()
        finally:
            conn.close()
        llegaron += 1
        total += q * precio
    if not llegaron:
        return {"ok": False, "msg": "; ".join(problemas) or "Poné cuánto llegó de cada repuesto"}
    fac = d.get("factura") or {}
    conn = get_connection()
    try:
        falta = conn.execute("SELECT COUNT(*) AS n FROM compras_repo_items WHERE repo_id=? AND recibido < cantidad",
                             (pid,)).fetchone()["n"]
        estado = "parcial" if falta and not d.get("cerrar") else "recibido"
        conn.execute("UPDATE compras_repo SET estado=?, recibido_el=?, factura=CASE WHEN ?<>'' THEN ? ELSE factura END WHERE id=?",
                     (estado, ahora, str(fac.get("numero") or "").strip()[:40], str(fac.get("numero") or "").strip()[:40], pid))
        conn.commit()
    finally:
        conn.close()
    teso = None
    if fac.get("tesoreria"):
        monto = _num(fac.get("monto")) or round(total)
        if monto > 0:
            import compras_repuestos
            teso = compras_repuestos.a_tesoreria({**fac, "proveedor": p["proveedor"]}, monto,
                                                 f"reposición del depósito (pedido #{pid})", f"reposicion:{pid}")
    try:
        import buscador
        buscador.olvidar_indice()
    except Exception:
        pass
    return {"ok": True, "estado": estado, "llegaron": llegaron, "problemas": problemas, "tesoreria": teso,
            "msg": ("Recibido completo" if estado == "recibido" else f"Recibido en parte: quedan {falta} renglón(es) por llegar")}


def anular(pid):
    conn = get_connection()
    try:
        p = conn.execute("SELECT estado FROM compras_repo WHERE id=?", (pid,)).fetchone()
        if not p:
            return False, "Ese pedido ya no existe"
        if p["estado"] not in ("pedido", "parcial"):
            return False, "Ese pedido ya está cerrado"
        # lo que ya llegó queda; lo que falta deja de esperarse
        conn.execute("UPDATE compras_repo SET estado=? WHERE id=?",
                     ("recibido" if p["estado"] == "parcial" else "anulado", pid))
        if p["estado"] == "parcial":
            conn.execute("UPDATE compras_repo_items SET cantidad = recibido WHERE repo_id=?", (pid,))
        conn.commit()
        return True, "Pedido cerrado" if p["estado"] == "parcial" else "Pedido anulado"
    finally:
        conn.close()


def resumen():
    """Para el contador de la pestaña: cuántos para pedir y pedidos abiertos."""
    try:
        s = sugerido()
        para = sum(1 for x in s["con_minimo"] if x["sugerido"] > 0)
    except Exception:
        para = 0
    conn = get_connection()
    try:
        abiertos = conn.execute("SELECT COUNT(*) AS n FROM compras_repo WHERE estado IN ('pedido','parcial')").fetchone()["n"]
    except Exception:
        _rollback(conn)
        abiertos = 0
    finally:
        conn.close()
    return {"para_pedir": para, "abiertos": abiertos}


# ════════════════════════════════════════════════════════════════════════════
# RUTAS
# ════════════════════════════════════════════════════════════════════════════

def _puede(escribir=False):
    try:
        import compras_repuestos
        return compras_repuestos._puede(escribir)
    except Exception:
        return session.get("rol") in ("admin", "compras")


def _no():
    return jsonify({"ok": False, "msg": "Sin permiso"}), 403


@bp_reposicion.route("/api/compras/reposicion", methods=["GET"])
def api_listar():
    if not _puede():
        return _no()
    return jsonify({"ok": True, "pedidos": listar(), "resumen": resumen()})


@bp_reposicion.route("/api/compras/reposicion/sugerido", methods=["GET"])
def api_sugerido():
    if not _puede():
        return _no()
    return jsonify({"ok": True, **sugerido()})


@bp_reposicion.route("/api/compras/reposicion/resumen", methods=["GET"])
def api_resumen():
    if not _puede():
        return _no()
    return jsonify({"ok": True, **resumen()})


@bp_reposicion.route("/api/compras/reposicion", methods=["POST"])
def api_crear():
    if not _puede(True):
        return _no()
    r = crear((request.get_json(silent=True) or {}).get("items"), _quien())
    if r.get("ok"):
        _auditar(f"Armó {len(r['pedidos'])} pedido(s) de reposición del depósito")
    return jsonify(r), (200 if r.get("ok") else 400)


@bp_reposicion.route("/api/compras/reposicion/<int:pid>/recibir", methods=["POST"])
def api_recibir(pid):
    if not _puede(True):
        return _no()
    r = recibir(pid, request.get_json(silent=True) or {}, _quien())
    if r.get("ok"):
        _auditar(f"Recibió el pedido de reposición #{pid}", r.get("msg", ""))
    return jsonify(r), (200 if r.get("ok") else 400)


@bp_reposicion.route("/api/compras/reposicion/<int:pid>/anular", methods=["POST"])
def api_anular(pid):
    if not _puede(True):
        return _no()
    ok, msg = anular(pid)
    if ok:
        _auditar(f"{msg}: reposición #{pid}")
    return jsonify({"ok": ok, "msg": msg}), (200 if ok else 400)


def _auditar(accion, detalle=""):
    try:
        from database import registrar_auditoria
        registrar_auditoria(usuario=_quien() or "?", rol=session.get("rol") or "",
                            accion=accion, categoria="Compras", detalle=(detalle or "")[:200])
    except Exception:
        pass
