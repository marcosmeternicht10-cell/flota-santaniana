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
               COALESCE(x.stock_nota,'') AS stock_nota, i.descripcion AS trabajo
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
    taller ('filtro aceite scania' → los filtros de aceite)."""
    palabras = _palabras(descripcion)
    if not palabras:
        return []
    conn = get_connection()
    try:
        # candidatos: los que tienen la palabra más larga en código o descripción
        clave = max(palabras, key=len)
        like = f"%{clave}%"
        filas = conn.execute("""SELECT * FROM repuestos WHERE activo=1 AND
                                (LOWER(descripcion) LIKE ? OR LOWER(codigo) LIKE ? OR LOWER(codigo_alt) LIKE ?
                                 OR LOWER(aplicacion) LIKE ?) LIMIT 200""", (like, like, like, like)).fetchall()
        if len(palabras) > 1 and len(filas) < 200:
            otras = {r["id"] for r in filas}
            for p in palabras:
                if p == clave or len(p) < 4:
                    continue
                for r in conn.execute("""SELECT * FROM repuestos WHERE activo=1 AND
                                         (LOWER(descripcion) LIKE ? OR LOWER(codigo) LIKE ?) LIMIT 80""",
                                      (f"%{p}%", f"%{p}%")).fetchall():
                    if r["id"] not in otras:
                        otras.add(r["id"])
                        filas.append(r)
    finally:
        conn.close()
    pal = set(palabras)
    puntos = []
    for r in filas:
        texto = set(_palabras(f"{r['codigo']} {r['descripcion']} {r['marca']} {r['aplicacion']}"))
        comunes = len(pal & texto)
        # coincidencias parciales (filtros ~ filtro)
        parcial = sum(1 for p in pal - texto if any(t.startswith(p[:5]) for t in texto if len(p) >= 5))
        score = comunes + 0.5 * parcial + (0.2 if float(r["stock_actual"] or 0) > 0 else 0)
        if comunes or parcial:
            puntos.append((score, r))
    puntos.sort(key=lambda x: -x[0])
    return [dict(_repuesto_breve(r), coincide=round(s, 1)) for s, r in puntos[:limite]]


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
            d["sugerencias"] = sugerir(d["descripcion"])
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
        origen = "deposito" if (origen == "deposito" and rid) else ""
        sets = "repuesto_id=?, origen=?"
        vals = [rid, origen]
        if origen == "deposito":
            sets += ", precio_unit=0, proveedor=''"
        conn.execute(f"UPDATE ot_materiales SET {sets} WHERE id=?", vals + [material_id])
        conn.commit()
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


def al_entregar(ot_id, usuario=""):
    """Al entregar: lo del depósito sale para la OT; lo comprado entra al
    inventario (con su costo y proveedor) y sale para la OT. Lo que no
    alcanza no frena la entrega: queda anotado en el material."""
    import repuestos_db as rdb
    import ot_inventario as oti
    conn = get_connection()
    try:
        ids = _ids(conn, ot_id)
        mats = [x for x in _materiales(conn, ids) if x["repuesto_id"] and not x["stock_aplicado"]]
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
    import repuestos_db as rdb
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify({"ok": True, "lista": []})
    reps = rdb.obtener_repuestos(buscar=q)[:30]
    reps.sort(key=lambda r: (float(r.get("stock_actual") or 0) <= 0, r.get("descripcion") or ""))
    return jsonify({"ok": True, "lista": [_repuesto_breve(r) for r in reps[:20]]})
