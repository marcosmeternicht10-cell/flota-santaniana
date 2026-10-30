"""
compras_repuestos.py — El presupuesto de Compras conectado con el depósito
y los proveedores (La Santaniana)

Al presupuestar, cada material de la OT se engancha con su repuesto del
inventario:

  · si hay stock en el depósito, se puede marcar «sale del depósito»: no se le
    pide plata a Tesorería por eso y, al entregar, baja el stock y queda
    anotado en la OT;
  · si se compra, se elige el proveedor entre los que venden ese repuesto,
    cada uno con su último precio (el más barato marcado). El precio que se
    pone queda como el último de ese proveedor;
  · al entregar, lo comprado entra al inventario (a ese costo y de ese
    proveedor) y sale para la OT: el repuesto guarda todo su historial.

Y para pedir: lo que hay que comprar, agrupado por proveedor, con su teléfono
y el texto listo para WhatsApp.

  init_compras_repuestos()                columnas en ot_materiales
  GET  /api/compras/<ot>/repuestos        cada material con su repuesto,
                                          stock, proveedores y sugerencias
  POST /api/compras/<ot>/vincular         {material_id, repuesto_id|0, origen}
  GET  /api/compras/<ot>/por_proveedor    el pedido agrupado por proveedor
  guardar_presupuesto(ot, d)              después del presupuesto: depósito
                                          sin precio y precios a proveedores
  al_entregar(ot, usuario)                los movimientos de stock
"""

import re
import unicodedata

from flask import Blueprint, request, jsonify, session

from db_compat import get_connection, USE_POSTGRES

bp_compras_rep = Blueprint("compras_repuestos", __name__)

COLUMNAS = [
    ("repuesto_id", "INTEGER"),
    ("origen", "TEXT DEFAULT ''"),            # '' = se compra · 'deposito' = sale del depósito
    ("stock_aplicado", "INTEGER DEFAULT 0"),  # 1 cuando ya se movió el stock al entregar
    ("stock_nota", "TEXT DEFAULT ''"),        # qué pasó al mover el stock (o por qué no se pudo)
    ("entregado_el", "TEXT DEFAULT ''"),      # cuándo llegó y se entregó (vacío = pendiente)
    ("entregado_por", "TEXT DEFAULT ''"),
    ("precio_presup", "REAL DEFAULT 0"),      # el precio del presupuesto (precio_unit queda con el real)
    ("factura", "TEXT DEFAULT ''"),           # número de factura del proveedor
]
PALABRAS_VACIAS = {"de", "del", "la", "el", "los", "las", "para", "con", "y", "x", "un", "una", "por", "en", "a"}


def _rollback(conn):
    try:
        conn.rollback()
    except Exception:
        pass


def init_compras_repuestos():
    conn = get_connection()
    try:
        if USE_POSTGRES:
            for col, tipo in COLUMNAS:
                conn.execute(f"ALTER TABLE ot_materiales ADD COLUMN IF NOT EXISTS {col} {tipo}")
        else:
            ya = {r["name"] for r in conn.execute("PRAGMA table_info(ot_materiales)").fetchall()}
            for col, tipo in COLUMNAS:
                if col not in ya:
                    conn.execute(f"ALTER TABLE ot_materiales ADD COLUMN {col} {tipo}")
        conn.commit()
        # Trabajos sin materiales (precio del trabajo): también se reciben
        try:
            import ot_materiales as om
            om._agregar_columna(conn, "ot_items", "entregado_el", "TEXT DEFAULT ''")
        except Exception:
            _rollback(conn)
        # Lo que ya estaba entregado antes de esto queda como entregado
        try:
            conn.execute("""UPDATE ot_materiales SET entregado_el = COALESCE(NULLIF(o.fecha_entrega,''), 'antes')
                            FROM ordenes_trabajo o WHERE o.id = ot_materiales.ot_id AND o.estado_compras='entregado'
                            AND COALESCE(ot_materiales.entregado_el,'')=''""" if USE_POSTGRES else
                         """UPDATE ot_materiales SET entregado_el = COALESCE((SELECT NULLIF(o.fecha_entrega,'') FROM ordenes_trabajo o
                                WHERE o.id = ot_materiales.ot_id AND o.estado_compras='entregado'), '')
                            WHERE COALESCE(entregado_el,'')='' AND ot_id IN (SELECT id FROM ordenes_trabajo WHERE estado_compras='entregado')""")
            conn.commit()
        except Exception:
            _rollback(conn)
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS ix_otmat_rep ON ot_materiales (repuesto_id)")
            conn.commit()
        except Exception:
            _rollback(conn)
    except Exception as e:
        _rollback(conn)
        print(f"[compras_repuestos] no se pudieron agregar las columnas: {e}")
    finally:
        conn.close()


def _norm(t):
    t = unicodedata.normalize("NFD", str(t or "").lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def _palabras(t):
    return [p for p in re.findall(r"[a-z0-9]+", _norm(t)) if len(p) > 1 and p not in PALABRAS_VACIAS]


def _ids(conn, ot_id):
    try:
        import ot_materiales as om
        return om.ids_grupo(conn, ot_id) or [ot_id]
    except Exception:
        _rollback(conn)
        return [ot_id]


def _materiales(conn, ids):
    m = ",".join("?" * len(ids))
    return [dict(r) for r in conn.execute(f"""
        SELECT x.id, x.item_id, x.ot_id, x.descripcion, x.cantidad, x.precio_unit, x.proveedor,
               x.repuesto_id, COALESCE(x.origen,'') AS origen, COALESCE(x.stock_aplicado,0) AS stock_aplicado,
               COALESCE(x.stock_nota,'') AS stock_nota, i.descripcion AS trabajo,
               COALESCE(x.entregado_el,'') AS entregado_el, COALESCE(x.precio_presup,0) AS precio_presup,
               COALESCE(x.factura,'') AS factura
        FROM ot_materiales x LEFT JOIN ot_items i ON i.id = x.item_id
        WHERE x.ot_id IN ({m}) ORDER BY x.ot_id, x.item_id, x.orden, x.id""", ids).fetchall()]


def _repuesto_breve(r):
    import repuestos_db as rdb
    d = rdb._enriquecer(r)
    return {k: d.get(k) for k in ("id", "codigo", "descripcion", "marca", "aplicacion", "unidad", "stock_actual",
                                  "stock_minimo", "costo_unitario", "ubicacion", "estado_stock", "proveedor",
                                  "contenido", "contenido_unidad", "envase")}


def en_contenido(descripcion, rep):
    """¿El material se pidió en litros/kg/metros de un producto que se guarda
    por envase? ('Aceite 15W40 (litros)' de un bidón de 20 L → sí)."""
    try:
        cont = float(rep.get("contenido") or 0)
    except (TypeError, ValueError):
        cont = 0
    u = _norm(rep.get("contenido_unidad") or "")
    if cont <= 0 or not u:
        return False
    d = _norm(descripcion)
    raiz = {"litros": "litro", "kg": "kg", "metros": "metro"}.get(u, u[:5])
    return raiz in d or (raiz == "litro" and re.search(r"\b\d+\s*l\b", d) is not None) or (raiz == "kg" and "kilo" in d)


def sugerir(descripcion, limite=4):
    """Los repuestos del inventario que más se parecen a lo que pidió el
    taller, aunque esté mal escrito ('filto de aseite' → los filtros de
    aceite). Lo que ya se eligió antes para algo parecido sale primero."""
    import buscador
    try:
        res = buscador.buscar_repuestos(descripcion, limite)
    except Exception as e:
        print(f"[compras_repuestos] buscador: {e}")
        return []
    return [dict(_repuesto_breve(r), coincide=s, motivo=m) for r, s, m in res]


def detalle(ot_id):
    """Cada material de la OT con su repuesto, el stock y los proveedores."""
    import repuestos_multi as multi
    conn = get_connection()
    try:
        ids = _ids(conn, ot_id)
        mats = _materiales(conn, ids)
        rep_ids = sorted({m["repuesto_id"] for m in mats if m["repuesto_id"]})
        reps = {}
        if rep_ids:
            for r in conn.execute(f"SELECT * FROM repuestos WHERE id IN ({','.join('?' * len(rep_ids))})",
                                  rep_ids).fetchall():
                reps[r["id"]] = _repuesto_breve(r)
        # cuánto de cada repuesto ya está apartado para otras OTs sin entregar
        apartado = {}
        if rep_ids:
            m = ",".join("?" * len(rep_ids))
            for r in conn.execute(f"""SELECT x.repuesto_id, SUM(x.cantidad) AS q FROM ot_materiales x
                                      JOIN ordenes_trabajo o ON o.id = x.ot_id
                                      WHERE x.repuesto_id IN ({m}) AND x.origen='deposito'
                                      AND COALESCE(x.stock_aplicado,0)=0
                                      AND o.estado_compras IN ('en_espera','presupuestado','en_camino')
                                      AND x.ot_id NOT IN ({','.join('?' * len(ids))})
                                      GROUP BY x.repuesto_id""", rep_ids + ids).fetchall():
                apartado[r["repuesto_id"]] = float(r["q"] or 0)
    finally:
        conn.close()
    out = []
    for mt in mats:
        d = dict(mt)
        d["cantidad"] = float(d["cantidad"] or 0)
        d["precio_unit"] = float(d["precio_unit"] or 0)
        rid = d["repuesto_id"]
        if rid and rid in reps:
            r = reps[rid]
            d["repuesto"] = r
            d["apartado_otras"] = apartado.get(rid, 0)
            d["disponible"] = round(float(r["stock_actual"] or 0) - apartado.get(rid, 0), 3)
            d["en_contenido"] = en_contenido(d["descripcion"], r)
            if d["en_contenido"]:   # el pedido viene en litros: el stock también en litros
                c = float(r["contenido"] or 0)
                d["disponible"] = round(d["disponible"] * c, 2)
                d["apartado_otras"] = round(d["apartado_otras"] * c, 2)
                d["unidad_material"] = r.get("contenido_unidad") or ""
            d["proveedores"] = multi.lista(rid, r.get("proveedor") or "")
            d["sugerencias"] = []
        else:
            d["repuesto"] = None
            d["proveedores"] = []
            d["sugerencias"] = [] if d["origen"] == "suelto" else sugerir(d["descripcion"])
        out.append(d)
    return out


def vincular(ot_id, material_id, repuesto_id, origen):
    conn = get_connection()
    try:
        ids = _ids(conn, ot_id)
        m = conn.execute(f"SELECT id, stock_aplicado FROM ot_materiales WHERE id=? AND ot_id IN ({','.join('?' * len(ids))})",
                         [material_id] + ids).fetchone()
        if not m:
            return False, "Ese material no es de esta OT"
        if m["stock_aplicado"]:
            return False, "Ese material ya se entregó: el stock ya se movió"
        rid = int(repuesto_id or 0) or None
        if rid and not conn.execute("SELECT 1 FROM repuestos WHERE id=?", (rid,)).fetchone():
            return False, "Ese repuesto no está en el inventario"
        # '' = se compra · 'deposito' = sale del depósito · 'suelto' = se compra y no va al inventario
        origen = "deposito" if (origen == "deposito" and rid) else ("suelto" if origen == "suelto" and not rid else "")
        sets = "repuesto_id=?, origen=?"
        vals = [rid, origen]
        if origen == "deposito":
            sets += ", precio_unit=0, proveedor=''"
        conn.execute(f"UPDATE ot_materiales SET {sets} WHERE id=?", vals + [material_id])
        conn.commit()
        if rid:   # aprende: lo que escribió el taller = este repuesto
            try:
                desc = conn.execute("SELECT descripcion FROM ot_materiales WHERE id=?", (material_id,)).fetchone()
                import buscador
                buscador.aprender(desc["descripcion"] if desc else "", rid)
            except Exception:
                pass
        return True, ""
    except Exception as e:
        _rollback(conn)
        return False, f"No se pudo guardar: {e}"
    finally:
        conn.close()


def guardar_presupuesto(ot_id, d, usuario=""):
    """Después de guardar los precios: lo que sale del depósito queda en 0
    (no se le pide plata a Tesorería) y el precio que se puso para cada
    proveedor queda como su último precio en la ficha del repuesto."""
    import repuestos_multi as multi
    vinc = d.get("vinculos") or {}
    for mid, v in vinc.items():
        try:
            vincular(ot_id, int(mid), (v or {}).get("repuesto_id"), (v or {}).get("origen"))
        except Exception:
            pass
    conn = get_connection()
    try:
        ids = _ids(conn, ot_id)
        mats = _materiales(conn, ids)
        m = ",".join("?" * len(ids))
        conn.execute(f"UPDATE ot_materiales SET precio_unit=0, proveedor='' WHERE origen='deposito' AND ot_id IN ({m})", ids)
        try:
            import ot_materiales as om
            for item_id in {x["item_id"] for x in mats if x["origen"] == "deposito"}:
                om.resumir_item(conn, item_id)
        except Exception:
            pass
        conn.commit()
    finally:
        conn.close()
    actualizados = 0
    for x in mats:
        if x["repuesto_id"] and x["origen"] != "deposito" and (x["proveedor"] or "").strip() and float(x["precio_unit"] or 0) > 0:
            ok, _ = multi.agregar(x["repuesto_id"], x["proveedor"], precio=float(x["precio_unit"]))
            actualizados += 1 if ok else 0
    return actualizados


def _num_txt(q):
    q = float(q or 0)
    return str(int(q)) if q == int(q) else f"{q:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def al_entregar(ot_id, usuario="", solo=None):
    """Al entregar: lo del depósito sale para la OT; lo comprado entra al
    inventario (con su costo y proveedor) y sale para la OT. Lo que no
    alcanza no frena la entrega: queda anotado en el material.
    solo = los materiales que se entregan ahora (None = todos)."""
    import repuestos_db as rdb
    import ot_inventario as oti
    conn = get_connection()
    try:
        ids = _ids(conn, ot_id)
        mats = [x for x in _materiales(conn, ids) if x["repuesto_id"] and not x["stock_aplicado"]
                and (solo is None or x["id"] in solo)]
    finally:
        conn.close()
    hechos, problemas = 0, []
    conn = get_connection()
    try:
        reps = {r["id"]: dict(r) for r in conn.execute(
            f"SELECT * FROM repuestos WHERE id IN ({','.join('?' * len(mats)) or '0'})",
            [x["repuesto_id"] for x in mats]).fetchall()} if mats else {}
    finally:
        conn.close()
    for x in mats:
        q = float(x["cantidad"] or 0)
        if q <= 0:
            continue
        rep = reps.get(x["repuesto_id"]) or {}
        litros = en_contenido(x["descripcion"], rep)
        cont = float(rep.get("contenido") or 0)
        envases = round(q / cont, 4) if litros else q
        nota = ""
        if x["origen"] != "deposito":
            prov = (x["proveedor"] or "").strip()
            ok, res = rdb.registrar_movimiento(
                x["repuesto_id"], "entrada", envases,
                motivo=(f"Compra a {prov}" if prov else "Compra") + f" para la OT #{x['ot_id']}",
                costo_unitario=float(x["precio_unit"] or 0) * (cont if litros else 1), referencia=f"compra:OT:{x['ot_id']}", usuario=usuario)
            if not ok:
                problemas.append(f"{x['descripcion']}: no entró al inventario ({res})")
                _nota(x["id"], f"No entró al inventario: {res}", aplicado=False)
                continue
            nota = f"Entró {_num_txt(q)}{' ' + (rep.get('contenido_unidad') or 'litros') if litros else ''} comprado" + (f" a {prov}" if prov else "") + " y salió para la OT"
        ok, res = oti.sacar_para_ot(x["ot_id"], x["repuesto_id"], q, en="contenido" if litros else "envases",
                                    item_id=x["item_id"], usuario=usuario)
        if not ok:
            problemas.append(f"{x['descripcion']}: {res}")
            _nota(x["id"], f"No se pudo sacar del depósito: {res}", aplicado=False)
            continue
        _nota(x["id"], nota or f"Salió {_num_txt(q)}{' ' + (rep.get('contenido_unidad') or 'litros') if litros else ''} del depósito",
              aplicado=True)
        hechos += 1
    return {"movidos": hechos, "problemas": problemas}


# ════════════════════════════════════════════════════════════════════════════
# RECEPCIÓN: qué llegó, a qué precio, con qué factura (y lo que falta)
# ════════════════════════════════════════════════════════════════════════════

def _num_gs(v):
    if isinstance(v, (int, float)):
        return float(v)
    t = str(v or "").strip().replace(".", "").replace(",", ".")
    try:
        return float(t or 0)
    except ValueError:
        return 0.0


def _hoy():
    try:
        from hora_local import ahora_iso
        return ahora_iso()
    except Exception:
        from datetime import datetime
        return datetime.now().isoformat(timespec="seconds")


def recibir(ot_id, d, usuario=""):
    """Registra lo que llegó y se entrega al taller. Lo que no se marca queda
    pendiente y la OT sigue «en camino». Con la factura de cada proveedor
    se carga el pago en Tesorería.
      d = {materiales: [{id, precio}], items: [{id, precio}],
           facturas: [{proveedor, numero, monto, dias, tesoreria}],
           taller_entrega, recibido_por, foto}
    Sin 'materiales' ni 'items': se entrega todo lo pendiente (como antes)."""
    recibe = re.sub(r"\s+", " ", str(d.get("recibido_por") or "")).strip()[:120]
    if not recibe:
        return {"ok": False, "msg": "Indicá quién recibió el material"}
    taller = re.sub(r"\s+", " ", str(d.get("taller_entrega") or "Taller propio")).strip()[:120] or "Taller propio"
    foto = d.get("foto")
    if foto and len(foto) > 800000:
        return {"ok": False, "msg": "La foto es muy grande"}
    ahora = _hoy()
    todo = "materiales" not in d and "items" not in d
    sel_m = {int(x.get("id")): x for x in d.get("materiales") or [] if str(x.get("id") or "").isdigit()}
    sel_i = {int(x.get("id")): x for x in d.get("items") or [] if str(x.get("id") or "").isdigit()}
    facturas = {}
    for f in d.get("facturas") or []:
        for nom in (f.get("nombres") or [f.get("proveedor") or ""]):
            facturas[_norm(nom or "").strip()] = f
    conn = get_connection()
    entregados, tocados = [], set()
    try:
        ids = _ids(conn, ot_id)
        m = ",".join("?" * len(ids))
        items = {r["id"]: dict(r) for r in conn.execute(
            f"SELECT id, ot_id, COALESCE(estado_pago,'') AS estado_pago, COALESCE(entregado_el,'') AS entregado_el, "
            f"COALESCE(proveedor_compras,'') AS proveedor_compras FROM ot_items WHERE ot_id IN ({m})", ids).fetchall()}
        mats = _materiales(conn, ids)
        con_mat = {x["item_id"] for x in mats}
        for x in mats:
            if x["entregado_el"] or x["stock_aplicado"]:
                continue
            if items.get(x["item_id"], {}).get("estado_pago") == "espera":
                continue                      # Tesorería todavía no lo cubrió
            if not todo and x["id"] not in sel_m:
                continue
            sets, vals = ["entregado_el=?", "entregado_por=?"], [ahora, recibe]
            p = sel_m.get(x["id"], {}).get("precio")
            if x["origen"] != "deposito" and p not in (None, ""):
                p = _num_gs(p)
                if p >= 0 and abs(p - float(x["precio_unit"] or 0)) > 0.5:
                    if not float(x["precio_presup"] or 0):
                        sets.append("precio_presup=?")
                        vals.append(float(x["precio_unit"] or 0))
                    sets.append("precio_unit=?")
                    vals.append(p)
            fac = facturas.get(_norm(x["proveedor"] or "").strip())
            if fac and str(fac.get("numero") or "").strip():
                sets.append("factura=?")
                vals.append(str(fac["numero"]).strip()[:40])
            conn.execute(f"UPDATE ot_materiales SET {', '.join(sets)} WHERE id=?", vals + [x["id"]])
            entregados.append(x["id"])
            tocados.add(x["item_id"])
        import ot_materiales as om
        for iid in tocados:
            om.resumir_item(conn, iid)
        # Trabajos sin materiales (precio del trabajo)
        n_items = 0
        for iid, it in items.items():
            if iid in con_mat or it["entregado_el"] or it["estado_pago"] == "espera":
                continue
            if not todo and iid not in sel_i:
                continue
            p = sel_i.get(iid, {}).get("precio")
            if p not in (None, ""):
                conn.execute("UPDATE ot_items SET precio_compras=?, entregado_el=? WHERE id=?", (_num_gs(p), ahora, iid))
            else:
                conn.execute("UPDATE ot_items SET entregado_el=? WHERE id=?", (ahora, iid))
            n_items += 1
        if foto:
            conn.execute("INSERT INTO compras_evidencia (ot_id, datos, nombre, fecha) VALUES (?,?,?,?)",
                         (ot_id, foto, "entrega.jpg", ahora))
        conn.commit()
    except Exception as e:
        _rollback(conn)
        conn.close()
        return {"ok": False, "msg": f"No se pudo registrar: {e}"}
    conn.close()
    if not entregados and not n_items and not todo:
        return {"ok": False, "msg": "Marcá lo que llegó"}
    # El stock: lo del depósito sale, lo comprado entra (a su precio real) y sale
    stock = {"movidos": 0, "problemas": []}
    try:
        stock = al_entregar(ot_id, usuario, solo=set(entregados))
    except Exception as e:
        stock["problemas"].append(f"No se pudo mover el stock: {e}")
    # ¿Queda algo por llegar?
    pend = pendientes(ot_id)
    conn = get_connection()
    try:
        ids = _ids(conn, ot_id)
        for i in ids:
            if pend["cantidad"]:
                conn.execute("UPDATE ordenes_trabajo SET taller_entrega=?, recibido_por=? WHERE id=?", (taller, recibe, i))
            else:
                conn.execute("""UPDATE ordenes_trabajo SET estado_compras='entregado', fecha_entrega=?,
                                taller_entrega=?, recibido_por=? WHERE id=?""", (ahora, taller, recibe, i))
        conn.commit()
    finally:
        conn.close()
    # Facturas → Tesorería (pago a proveedor)
    teso = []
    for f in (d.get("facturas") or []):
        if not f.get("tesoreria"):
            continue
        monto = _num_gs(f.get("monto"))
        if monto <= 0:
            continue
        r = a_tesoreria(f, monto, f"repuestos de la OT #{ot_id}", f"compra:OT:{ot_id}")
        teso.append(r)
    return {"ok": True, "entregados": len(entregados) + n_items, "pendientes": pend, "stock": stock, "tesoreria": teso,
            "msg": ("Entregado. " if not pend["cantidad"] else f"Entregado en parte: faltan {pend['cantidad']}. ")}


def pendientes(ot_id):
    """Lo que falta que llegue (sin contar lo que espera fondos)."""
    conn = get_connection()
    try:
        ids = _ids(conn, ot_id)
        m = ",".join("?" * len(ids))
        espera = {r["id"] for r in conn.execute(f"SELECT id FROM ot_items WHERE ot_id IN ({m}) AND estado_pago='espera'", ids).fetchall()}
        mats = _materiales(conn, ids)
        con_mat = {x["item_id"] for x in mats}
        faltan = [x["descripcion"] for x in mats if not x["entregado_el"] and not x["stock_aplicado"] and x["item_id"] not in espera]
        for r in conn.execute(f"""SELECT id, descripcion FROM ot_items WHERE ot_id IN ({m})
                                  AND COALESCE(entregado_el,'')='' AND COALESCE(estado_pago,'') <> 'espera'
                                  AND COALESCE(precio_compras,0) > 0""", ids).fetchall():
            if r["id"] not in con_mat:
                faltan.append(r["descripcion"])
        return {"cantidad": len(faltan), "lista": faltan[:12]}
    finally:
        conn.close()


def a_tesoreria(f, monto, que, referencia):
    """La factura del proveedor como pago programado en Tesorería."""
    from datetime import date, timedelta
    try:
        import tesoreria
    except Exception as e:
        return {"ok": False, "msg": f"Tesorería no disponible: {e}"}
    try:
        dias = max(0, min(180, int(f.get("dias") or 0)))
    except (TypeError, ValueError):
        dias = 0
    prov = re.sub(r"\s+", " ", str(f.get("proveedor") or "")).strip()[:150]
    num = str(f.get("numero") or "").strip()[:30]
    ruc = ""
    try:
        import repuestos_multi as multi
        conn = get_connection()
        try:
            r = conn.execute("SELECT ruc FROM repuestos_proveedores WHERE clave=?", (multi._clave(prov),)).fetchone()
            ruc = (r["ruc"] or "") if r else ""
        finally:
            conn.close()
    except Exception:
        pass
    vence = (date.today() + timedelta(days=dias)).isoformat()
    r = tesoreria.guardar_programado({
        "tipo": "egreso", "monto": monto, "fecha": vence, "concepto": "Repuestos",
        "descripcion": (f"Factura {num} · " if num else "Factura · ") + que,
        "contraparte": prov, "ruc": ruc, "doc_numero": num, "medio": "transferencia",
        "nota": ("Contado" if not dias else f"A {dias} días") + f" · cargado desde Compras ({referencia})",
    })
    r["proveedor"] = prov
    r["vence"] = vence
    return r


def _nota(mid, texto, aplicado):
    conn = get_connection()
    try:
        conn.execute("UPDATE ot_materiales SET stock_nota=?, stock_aplicado=? WHERE id=?",
                     (texto[:300], 1 if aplicado else 0, mid))
        conn.commit()
    except Exception:
        _rollback(conn)
    finally:
        conn.close()


def por_proveedor(ot_id):
    """Lo que hay que comprar, agrupado por proveedor, con su contacto."""
    conn = get_connection()
    try:
        ids = _ids(conn, ot_id)
        mats = [x for x in _materiales(conn, ids) if x["origen"] != "deposito"]
        coches = {r["id"]: (r["n_interno"] or r["patente"] or "") for r in conn.execute(
            f"""SELECT o.id, v.n_interno, v.patente FROM ordenes_trabajo o JOIN vehiculos v ON v.id=o.vehiculo_id
                WHERE o.id IN ({','.join('?' * len(ids))})""", ids).fetchall()}
        # los trabajos sin materiales anotados también se compran
        sin_mat = [dict(r) for r in conn.execute(f"""
            SELECT i.id AS item_id, i.ot_id, i.descripcion, COALESCE(i.material_pedido,'') AS material,
                   COALESCE(i.precio_compras,0) AS precio, COALESCE(i.proveedor_compras,'') AS proveedor
            FROM ot_items i WHERE i.ot_id IN ({','.join('?' * len(ids))})
            AND i.id NOT IN (SELECT item_id FROM ot_materiales WHERE ot_id IN ({','.join('?' * len(ids))}))
            AND (COALESCE(i.precio_compras,0) > 0 OR COALESCE(i.material_pedido,'') <> '' OR COALESCE(i.proveedor_compras,'') <> '')""",
            ids + ids).fetchall()]
        reps = {}
        rid = sorted({x["repuesto_id"] for x in mats if x["repuesto_id"]})
        if rid:
            for r in conn.execute(f"SELECT id, codigo FROM repuestos WHERE id IN ({','.join('?' * len(rid))})", rid).fetchall():
                reps[r["id"]] = r["codigo"]
        codprov = {}
        if rid:
            for r in conn.execute(f"""SELECT repuesto_id, clave, codigo_prov FROM repuestos_por_proveedor
                                      WHERE repuesto_id IN ({','.join('?' * len(rid))})""", rid).fetchall():
                codprov[(r["repuesto_id"], r["clave"])] = r["codigo_prov"] or ""
        grupos = {}

        def grupo(nombre):
            k = " ".join(str(nombre or "").split()).lower()
            if k not in grupos:
                c = None
                if k:
                    try:
                        c = conn.execute("""SELECT nombre, fantasia, contacto, telefono, ruc FROM repuestos_proveedores
                                            WHERE clave=?""", (k,)).fetchone()
                    except Exception:
                        _rollback(conn)
                grupos[k] = {"proveedor": (c["nombre"] if c else "") or " ".join(str(nombre or "").split()) or "",
                             "fantasia": (c["fantasia"] if c else "") or "", "contacto": (c["contacto"] if c else "") or "",
                             "telefono": (c["telefono"] if c else "") or "", "ruc": (c["ruc"] if c else "") or "",
                             "renglones": [], "total": 0.0}
            return grupos[k]

        for x in mats:
            g = grupo(x["proveedor"])
            k = " ".join(str(x["proveedor"] or "").split()).lower()
            q, p = float(x["cantidad"] or 0), float(x["precio_unit"] or 0)
            g["renglones"].append({"cantidad": q, "descripcion": x["descripcion"],
                                   "codigo": reps.get(x["repuesto_id"], ""),
                                   "codigo_prov": codprov.get((x["repuesto_id"], k), ""),
                                   "precio": p, "subtotal": round(q * p), "coche": coches.get(x["ot_id"], "")})
            g["total"] += q * p
        for x in sin_mat:
            g = grupo(x["proveedor"])
            g["renglones"].append({"cantidad": 1, "descripcion": x["material"] or x["descripcion"], "codigo": "",
                                   "codigo_prov": "", "precio": float(x["precio"]), "subtotal": round(float(x["precio"])),
                                   "coche": coches.get(x["ot_id"], "")})
            g["total"] += float(x["precio"])
        n_dep = sum(1 for x in _materiales(conn, ids) if x["origen"] == "deposito")
    finally:
        conn.close()
    lista = sorted(grupos.values(), key=lambda g: (not g["proveedor"], g["proveedor"].lower()))
    for g in lista:
        g["total"] = round(g["total"])
    return {"grupos": lista, "del_deposito": n_dep}


# ════════════════════════════════════════════════════════════════════════════
# RUTAS
# ════════════════════════════════════════════════════════════════════════════

def _puede(escribir=False):
    rol = session.get("rol")
    if "usuario_id" not in session:
        return False
    if rol in ("admin", "compras"):
        return True
    if rol == "auditor":
        return not escribir
    if rol == "taller":
        try:
            from database import secciones_de_usuario
            secs = secciones_de_usuario(session.get("usuario_id"))
            return not secs or "compras" in secs
        except Exception:
            return False
    return False


@bp_compras_rep.route("/api/compras/<int:ot_id>/repuestos", methods=["GET"])
def api_detalle(ot_id):
    if not _puede():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    return jsonify({"ok": True, "materiales": detalle(ot_id)})


def editar_material(ot_id, material_id, d):
    """Corregir lo que escribió el taller: la descripción y/o la cantidad
    (lo que no viene, queda como estaba)."""
    solo_cant = "descripcion" not in d
    desc = re.sub(r"\s+", " ", str(d.get("descripcion") or "")).strip()[:200]
    try:
        cant = float(str(d.get("cantidad") or "0").replace(",", "."))
    except ValueError:
        cant = 0
    if not solo_cant and not desc:
        return False, "Escribí qué es el material"
    if cant <= 0:
        return False, "La cantidad tiene que ser mayor a cero"
    if cant > 9999:
        return False, "Revisá la cantidad"
    conn = get_connection()
    try:
        ids = _ids(conn, ot_id)
        m = conn.execute(f"SELECT id, item_id, stock_aplicado, descripcion FROM ot_materiales WHERE id=? AND ot_id IN ({','.join('?' * len(ids))})",
                         [material_id] + ids).fetchone()
        if not m:
            return False, "Ese material no es de esta OT"
        if m["stock_aplicado"]:
            return False, "Ese material ya se entregó"
        if solo_cant:
            desc = m["descripcion"] or ""
        conn.execute("UPDATE ot_materiales SET descripcion=?, cantidad=? WHERE id=?", (desc, cant, material_id))
        try:
            import ot_materiales as om
            om.resumir_item(conn, m["item_id"])
        except Exception:
            pass
        conn.commit()
        return True, ""
    except Exception as e:
        _rollback(conn)
        return False, f"No se pudo guardar: {e}"
    finally:
        conn.close()


def crear_repuesto(ot_id, material_id, d, usuario=""):
    """Dar de alta en el inventario un repuesto que no estaba, y engancharlo
    con el material. Si viene proveedor y precio, quedan en su ficha."""
    import repuestos_db as rdb
    import repuestos_multi as multi
    desc = re.sub(r"\s+", " ", str(d.get("descripcion") or "")).strip()[:200]
    if not desc:
        return {"ok": False, "msg": "Escribí la descripción del repuesto"}
    codigo = re.sub(r"\s+", " ", str(d.get("codigo") or "")).strip().upper()[:60]
    if not codigo:
        # sin código del fabricante: uno interno, que se puede cambiar después
        conn = get_connection()
        try:
            usados = {str(x["codigo"]).upper() for x in conn.execute("SELECT codigo FROM repuestos WHERE codigo LIKE 'INT-%'").fetchall()}
        finally:
            conn.close()
        n = len(usados) + 1
        while f"INT-{n:05d}" in usados:
            n += 1
        codigo = f"INT-{n:05d}"
    v = d.get("precio")
    try:
        precio = float(v) if isinstance(v, (int, float)) else float(str(v or "0").replace(".", "").replace(",", ".") or 0)
    except ValueError:
        precio = 0
    prov = re.sub(r"\s+", " ", str(d.get("proveedor") or "")).strip()[:160]
    ok, res = rdb.agregar_repuesto(codigo, desc, categoria=d.get("categoria") or "Varios",
                                   marca=str(d.get("marca") or "").strip()[:80],
                                   aplicacion=str(d.get("aplicacion") or "").strip()[:120],
                                   unidad=d.get("unidad") or "u", costo_unitario=precio, proveedor=prov,
                                   observaciones=f"Dado de alta desde el presupuesto de la OT #{ot_id}", usuario=usuario)
    if not ok:
        return {"ok": False, "msg": res}
    rid = res
    if prov:
        try:
            multi.agregar(rid, prov, precio=precio)
        except Exception:
            pass
    try:
        import buscador
        buscador.olvidar_indice()
    except Exception:
        pass
    ok, msg = vincular(ot_id, material_id, rid, "")
    if not ok:
        return {"ok": False, "msg": msg}
    if prov or precio:
        conn = get_connection()
        try:
            # lo que se puso en la ficha nueva manda sobre lo que estaba escrito
            if prov:
                conn.execute("UPDATE ot_materiales SET proveedor=? WHERE id=?", (prov, material_id))
            if precio:
                conn.execute("UPDATE ot_materiales SET precio_unit=? WHERE id=?", (precio, material_id))
            conn.commit()
        finally:
            conn.close()
    return {"ok": True, "id": rid, "codigo": codigo, "msg": f"Repuesto {codigo} creado en el inventario y enganchado"}


def agregar_material(ot_id, d, usuario=""):
    """Compras agrega un repuesto a un trabajo (aunque el taller no haya
    anotado nada): del inventario (queda enganchado) o escrito a mano."""
    try:
        item_id = int(d.get("item_id") or 0)
        cant = float(str(d.get("cantidad") or "1").replace(",", "."))
    except (TypeError, ValueError):
        return {"ok": False, "msg": "Revisá la cantidad"}
    if cant <= 0 or cant > 9999:
        return {"ok": False, "msg": "La cantidad tiene que ser mayor a cero"}
    rid = int(d.get("repuesto_id") or 0) or None
    desc = re.sub(r"\s+", " ", str(d.get("descripcion") or "")).strip()[:200]
    conn = get_connection()
    try:
        ids = _ids(conn, ot_id)
        it = conn.execute(f"SELECT id, ot_id FROM ot_items WHERE id=? AND ot_id IN ({','.join('?' * len(ids))})",
                          [item_id] + ids).fetchone()
        if not it:
            return {"ok": False, "msg": "Ese trabajo no es de esta OT"}
        if rid:
            r = conn.execute("SELECT descripcion FROM repuestos WHERE id=?", (rid,)).fetchone()
            if not r:
                return {"ok": False, "msg": "Ese repuesto no está en el inventario"}
            desc = desc or (r["descripcion"] or "").strip()
        if not desc:
            return {"ok": False, "msg": "Escribí qué repuesto es"}
        n = conn.execute("SELECT COALESCE(MAX(orden),0) AS m FROM ot_materiales WHERE item_id=?", (item_id,)).fetchone()
        try:
            from hora_local import ahora_iso
            ahora = ahora_iso()
        except Exception:
            ahora = ""
        cur = conn.execute("""INSERT INTO ot_materiales (item_id, ot_id, descripcion, cantidad, precio_unit, orden,
                                  registrado_por, registrado_el, repuesto_id, origen)
                              VALUES (?,?,?,?,0,?,?,?,?,'')""",
                           (item_id, it["ot_id"], desc, cant, int(n["m"] or 0) + 1, (usuario or "Compras")[:80], ahora, rid))
        mid = cur.lastrowid or conn.execute("SELECT MAX(id) AS m FROM ot_materiales WHERE item_id=?", (item_id,)).fetchone()["m"]
        import ot_materiales as om
        om.resumir_item(conn, item_id)
        conn.commit()
    except Exception as e:
        _rollback(conn)
        return {"ok": False, "msg": f"No se pudo agregar: {e}"}
    finally:
        conn.close()
    return {"ok": True, "id": mid, "msg": "Repuesto agregado"}


def quitar_material(ot_id, mid):
    conn = get_connection()
    try:
        ids = _ids(conn, ot_id)
        m = conn.execute(f"SELECT id, item_id, stock_aplicado, COALESCE(entregado_el,'') AS ent FROM ot_materiales WHERE id=? AND ot_id IN ({','.join('?' * len(ids))})",
                         [mid] + ids).fetchone()
        if not m:
            return False, "Ese material no es de esta OT"
        if m["stock_aplicado"] or m["ent"]:
            return False, "Ese material ya se entregó: no se puede quitar"
        conn.execute("DELETE FROM ot_materiales WHERE id=?", (mid,))
        import ot_materiales as om
        om.resumir_item(conn, m["item_id"])
        conn.commit()
        return True, "Material quitado"
    except Exception as e:
        _rollback(conn)
        return False, f"No se pudo quitar: {e}"
    finally:
        conn.close()


@bp_compras_rep.route("/api/compras/<int:ot_id>/material_nuevo", methods=["POST"])
def api_material_nuevo_compras(ot_id):
    if not _puede(True):
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    r = agregar_material(ot_id, request.get_json(silent=True) or {}, session.get("nombre") or session.get("usuario") or "")
    return jsonify(r), (200 if r.get("ok") else 400)


@bp_compras_rep.route("/api/compras/<int:ot_id>/material/<int:mid>", methods=["DELETE"])
def api_quitar_material(ot_id, mid):
    if not _puede(True):
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    ok, msg = quitar_material(ot_id, mid)
    return jsonify({"ok": ok, "msg": msg}), (200 if ok else 400)


@bp_compras_rep.route("/api/compras/<int:ot_id>/material/<int:mid>", methods=["POST"])
def api_editar_material(ot_id, mid):
    if not _puede(True):
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    ok, msg = editar_material(ot_id, mid, request.get_json(silent=True) or {})
    return jsonify({"ok": ok, "msg": msg or "Material corregido"}), (200 if ok else 400)


@bp_compras_rep.route("/api/compras/<int:ot_id>/crear_repuesto", methods=["POST"])
def api_crear_repuesto(ot_id):
    if not _puede(True):
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    d = request.get_json(silent=True) or {}
    r = crear_repuesto(ot_id, int(d.get("material_id") or 0), d, session.get("nombre") or session.get("usuario") or "")
    return jsonify(r), (200 if r.get("ok") else 400)


@bp_compras_rep.route("/api/compras/<int:ot_id>/vincular", methods=["POST"])
def api_vincular(ot_id):
    if not _puede(True):
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    d = request.get_json(silent=True) or {}
    ok, msg = vincular(ot_id, int(d.get("material_id") or 0), d.get("repuesto_id"), d.get("origen"))
    return jsonify({"ok": ok, "msg": msg}), (200 if ok else 400)


@bp_compras_rep.route("/api/compras/<int:ot_id>/por_proveedor", methods=["GET"])
def api_por_proveedor(ot_id):
    if not _puede():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    return jsonify({"ok": True, **por_proveedor(ot_id)})


@bp_compras_rep.route("/api/compras/repuestos_buscar", methods=["GET"])
def api_buscar():
    if not _puede():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    import buscador
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"ok": True, "lista": []})
    res = buscador.buscar_repuestos(q, 25)
    lista = [dict(_repuesto_breve(r), coincide=s, motivo=m) for r, s, m in res]
    return jsonify({"ok": True, "lista": lista, "quisiste": buscador.corregir(q) if lista and lista[0]["motivo"] != "exacto" else ""})


@bp_compras_rep.route("/api/compras/proveedores_buscar", methods=["GET"])
def api_proveedores_buscar():
    """Proveedores aunque esté mal escrito ('dieza' → Diesa S.A.)."""
    if not _puede():
        return jsonify({"ok": False, "msg": "Sin permiso"}), 403
    import buscador
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"ok": True, "lista": []})
    return jsonify({"ok": True, "lista": [{"nombre": p.get("nombre") or "", "fantasia": p.get("fantasia") or "",
                                           "ruc": p.get("ruc") or "", "telefono": p.get("telefono") or ""}
                                          for p, s in buscador.buscar_proveedores(q, 12)]})
