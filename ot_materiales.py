"""
ot_materiales.py — Material por trabajo y OTs con varios coches (La Santaniana)

MATERIAL POR TRABAJO
Cada trabajo de la OT puede pedir varios materiales: cantidad, qué es y el
precio por unidad que pone Compras. El ítem guarda además un resumen
(material_pedido = "2 × Filtro de aceite · WD40") y el total (precio_compras),
así todo lo que ya leía esos dos campos (la firma de Tesorería, la cola de
fondos, las hojas por técnico) sigue andando igual.

OT CON VARIOS COCHES
Una OT puede abarcar varios coches. Cada coche se guarda como una OT hija
(ot_grupo = número de la OT principal) con sus trabajos, su km y su chofer:
así el historial, los costos, el preventivo y el km de cada coche quedan en
ese coche. Para el taller, Compras y Tesorería es una sola OT: se crea, se
manda a Compras, se presupuesta, se firma, se cierra y se borra junta, con el
número de la principal.

Enganche en app.py:
    from ot_materiales import bp_ot_mat, init_ot_materiales
    init_ot_materiales()
    app.register_blueprint(bp_ot_mat)
"""

from flask import Blueprint, request, jsonify, session
from db_compat import get_connection, USE_POSTGRES

bp_ot_mat = Blueprint("ot_materiales", __name__)

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"


def _rollback(conn):
    try:
        conn.rollback()
    except Exception:
        pass


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


def _agregar_columna(conn, tabla, col, tipo):
    try:
        if USE_POSTGRES:
            conn.execute(f"ALTER TABLE {tabla} ADD COLUMN IF NOT EXISTS {col} {tipo}")
        else:
            existentes = {r["name"] for r in conn.execute(f"PRAGMA table_info({tabla})").fetchall()}
            if col not in existentes:
                conn.execute(f"ALTER TABLE {tabla} ADD COLUMN {col} {tipo}")
        conn.commit()
    except Exception:
        _rollback(conn)


def init_ot_materiales():
    conn = get_connection()
    _agregar_columna(conn, "ordenes_trabajo", "ot_grupo", "INTEGER")
    nueva = not _existe_tabla(conn, "ot_materiales")
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS ot_materiales (
            id           {PK},
            item_id      INTEGER NOT NULL,
            ot_id        INTEGER NOT NULL,
            descripcion  TEXT NOT NULL DEFAULT '',
            cantidad     REAL DEFAULT 1,
            precio_unit  REAL DEFAULT 0,
            orden        INTEGER DEFAULT 0,
            registrado_por TEXT DEFAULT '',
            registrado_el  TEXT DEFAULT ''
        )
    """)
    conn.commit()
    for sql in ("CREATE INDEX IF NOT EXISTS ix_otmat_item ON ot_materiales (item_id)",
                "CREATE INDEX IF NOT EXISTS ix_otmat_ot ON ot_materiales (ot_id)",
                "CREATE INDEX IF NOT EXISTS ix_ot_grupo ON ordenes_trabajo (ot_grupo)"):
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            _rollback(conn)
    if nueva:
        # Lo que ya estaba cargado pasa a ser el primer material de cada
        # trabajo, con su precio: no se pierde nada ni cambia ningún total.
        try:
            filas = conn.execute("""
                SELECT id, ot_id, COALESCE(material_pedido,'') AS m, COALESCE(precio_compras,0) AS p
                FROM ot_items
                WHERE COALESCE(material_pedido,'') <> '' OR COALESCE(precio_compras,0) > 0
            """).fetchall()
            for f in filas:
                conn.execute("""INSERT INTO ot_materiales (item_id, ot_id, descripcion, cantidad, precio_unit, orden)
                                VALUES (?,?,?,?,?,0)""",
                             (f["id"], f["ot_id"], (f["m"] or "").strip() or "Material", 1, float(f["p"] or 0)))
            conn.commit()
        except Exception:
            _rollback(conn)
    conn.close()


# ════════════════════════════════════════════════════════════════════════════
# GRUPO: la OT principal y los coches que cuelgan de ella
# ════════════════════════════════════════════════════════════════════════════

def cabeza_de(conn, ot_id):
    """El número de la OT principal (la misma si no tiene coches agregados)."""
    try:
        r = conn.execute("SELECT id, ot_grupo FROM ordenes_trabajo WHERE id=?", (ot_id,)).fetchone()
    except Exception:
        _rollback(conn)
        r = conn.execute("SELECT id FROM ordenes_trabajo WHERE id=?", (ot_id,)).fetchone()
        return r["id"] if r else None
    if not r:
        return None
    return r["ot_grupo"] or r["id"]


def ids_grupo(conn, ot_id):
    """Las OTs del grupo, la principal primero. Una OT de un solo coche
    devuelve solo su número."""
    h = cabeza_de(conn, ot_id)
    if h is None:
        return []
    try:
        filas = conn.execute("SELECT id FROM ordenes_trabajo WHERE id=? OR ot_grupo=? ORDER BY id",
                             (h, h)).fetchall()
    except Exception:
        _rollback(conn)
        return [ot_id]
    ids = [f["id"] for f in filas]
    if h in ids:
        ids.remove(h)
        ids.insert(0, h)
    return ids or [ot_id]


def grupo_ids(ot_id):
    conn = get_connection()
    try:
        return ids_grupo(conn, ot_id)
    finally:
        conn.close()


def marcas(ids):
    return ",".join("?" * len(ids))


def miembros(conn, ids):
    """Los coches del grupo con lo justo para mostrarlos (en el orden de ids)."""
    if not ids:
        return []
    filas = conn.execute(f"""
        SELECT o.id, o.vehiculo_id, o.km, o.conductor, o.estado, v.n_interno, v.patente, v.marca, v.modelo,
               (SELECT COUNT(*) FROM ot_items i WHERE i.ot_id=o.id) AS items,
               (SELECT COUNT(*) FROM ot_items i WHERE i.ot_id=o.id AND i.estado='completado') AS completados
        FROM ordenes_trabajo o JOIN vehiculos v ON v.id = o.vehiculo_id
        WHERE o.id IN ({marcas(ids)})
    """, list(ids)).fetchall()
    por_id = {f["id"]: dict(f) for f in filas}
    return [por_id[i] for i in ids if i in por_id]


def agrupar_lista(ots):
    """La lista de OTs con una fila por OT: los coches agregados se juntan en
    la fila de la principal (trabajos, completados y costo sumados)."""
    grupos, orden = {}, []
    for o in ots:
        k = o.get("ot_grupo") or o["id"]
        if k not in grupos:
            grupos[k] = []
            orden.append(k)
        grupos[k].append(o)
    salida = []
    for k in orden:
        ms = grupos[k]
        rep = next((m for m in ms if m["id"] == k), None) or min(ms, key=lambda m: m["id"])
        o = dict(rep)
        o["numero"] = k if rep["id"] == k else rep["id"]
        if len(ms) > 1:
            ms = sorted(ms, key=lambda m: (m["id"] != rep["id"], m["id"]))
            o["coches"] = [{"id": m["id"], "n_interno": m.get("n_interno"), "patente": m.get("patente"),
                            "marca": m.get("marca"), "modelo": m.get("modelo")} for m in ms]
            o["total_items"] = sum(int(m.get("total_items") or 0) for m in ms)
            o["items_completados"] = sum(int(m.get("items_completados") or 0) for m in ms)
            o["costo_total"] = sum(float(m.get("costo_total") or 0) for m in ms)
            o["ultima_fecha"] = max((m.get("ultima_fecha") or "" for m in ms), default="")
            estados = {m.get("estado") for m in ms}
            if estados == {"cerrada"}:
                o["estado"] = "cerrada"
            elif "en_proceso" in estados:
                o["estado"] = "en_proceso"
        salida.append(o)
    return salida


COPIA_DE_LA_PRINCIPAL = ("fecha_apertura", "procedencia", "observaciones", "estado",
                         "estado_compras", "fecha_envio_compras", "fecha_presupuesto",
                         "fecha_en_camino", "nota_compras")


def agregar_coche(ot_id, vehiculo_id, km=0, conductor=""):
    """Suma un coche a la OT. Devuelve (ok, id_nuevo | mensaje)."""
    conn = get_connection()
    try:
        h = cabeza_de(conn, ot_id)
        if h is None:
            return False, "La OT no existe."
        cab = conn.execute("SELECT * FROM ordenes_trabajo WHERE id=?", (h,)).fetchone()
        cab = dict(cab)
        if cab.get("estado") == "cerrada":
            return False, "La OT está cerrada: reabrila para agregar un coche."
        if not conn.execute("SELECT 1 FROM vehiculos WHERE id=?", (vehiculo_id,)).fetchone():
            return False, "Ese coche no existe."
        ids = ids_grupo(conn, h)
        ya = conn.execute(f"SELECT 1 FROM ordenes_trabajo WHERE id IN ({marcas(ids)}) AND vehiculo_id=?",
                          list(ids) + [vehiculo_id]).fetchone()
        if ya:
            return False, "Ese coche ya está en esta OT."
        # Un coche tiene una sola OT abierta: si ya tiene una, esa pasa a ser
        # parte de esta OT (con todo lo que tenía), en vez de abrir otra
        try:
            import ot_unica
            suya = ot_unica.ot_abierta_de(conn, vehiculo_id)
        except Exception:
            suya = None
        if suya:
            s = dict(conn.execute("""SELECT o.id, o.ot_grupo, v.n_interno, v.patente,
                                            (SELECT COUNT(*) FROM ordenes_trabajo x WHERE x.ot_grupo = o.id) AS hijos
                                     FROM ordenes_trabajo o JOIN vehiculos v ON v.id = o.vehiculo_id WHERE o.id=?""",
                                  (suya,)).fetchone())
            if s["ot_grupo"] or s["hijos"]:
                return False, (f"El coche {s['n_interno'] or s['patente']} ya está en la OT "
                               f"#{s['ot_grupo'] or s['id']}, que es de varios coches.")
            if cab.get("estado_compras"):
                return False, (f"El coche {s['n_interno'] or s['patente']} ya tiene abierta la OT #{suya} "
                               f"y esta OT ya está en Compras: no se pueden juntar.")
            conn.execute("UPDATE ordenes_trabajo SET ot_grupo=? WHERE id=?", (h, suya))
            conn.commit()
            return True, suya
        cols = ["vehiculo_id", "km", "conductor", "ot_grupo"] + [c for c in COPIA_DE_LA_PRINCIPAL if c in cab]
        vals = [vehiculo_id, float(km or 0), conductor or "", h] + [cab.get(c) for c in COPIA_DE_LA_PRINCIPAL if c in cab]
        cur = conn.cursor()
        cur.execute(f"INSERT INTO ordenes_trabajo ({', '.join(cols)}) VALUES ({marcas(cols)})", vals)
        nuevo = cur.lastrowid
        conn.commit()
        return True, nuevo
    except Exception as e:
        _rollback(conn)
        return False, f"No se pudo agregar el coche: {e}"
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# MATERIALES
# ════════════════════════════════════════════════════════════════════════════

def fmt_cant(q):
    try:
        q = float(q or 0)
    except (TypeError, ValueError):
        return "1"
    if q == int(q):
        return str(int(q))
    return f"{q:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def materiales_de_items(conn, item_ids):
    """{item_id: [materiales]} en el orden en que se cargaron."""
    item_ids = [int(i) for i in item_ids or []]
    if not item_ids:
        return {}
    out = {i: [] for i in item_ids}
    try:
        filas = conn.execute(f"""
            SELECT id, item_id, ot_id, descripcion, cantidad, precio_unit
            FROM ot_materiales WHERE item_id IN ({marcas(item_ids)}) ORDER BY orden, id
        """, item_ids).fetchall()
    except Exception:
        _rollback(conn)
        return out
    for f in filas:
        d = dict(f)
        d["cantidad"] = float(d.get("cantidad") or 0)
        d["precio_unit"] = float(d.get("precio_unit") or 0)
        d["subtotal"] = round(d["cantidad"] * d["precio_unit"])
        out.setdefault(d["item_id"], []).append(d)
    return out


def resumir_item(conn, item_id):
    """Deja en el ítem el resumen de sus materiales y el total."""
    filas = conn.execute("""SELECT descripcion, cantidad, precio_unit FROM ot_materiales
                            WHERE item_id=? ORDER BY orden, id""", (item_id,)).fetchall()
    partes, total = [], 0.0
    for f in filas:
        d = (f["descripcion"] or "").strip()
        if not d:
            continue
        q = float(f["cantidad"] or 0)
        partes.append(d if q == 1 else f"{fmt_cant(q)} × {d}")
        total += q * float(f["precio_unit"] or 0)
    conn.execute("UPDATE ot_items SET material_pedido=?, precio_compras=? WHERE id=?",
                 (" · ".join(partes), round(total), item_id))


def borrar_de_items(conn, item_ids):
    item_ids = [int(i) for i in item_ids or []]
    if not item_ids:
        return
    try:
        conn.execute(f"DELETE FROM ot_materiales WHERE item_id IN ({marcas(item_ids)})", item_ids)
    except Exception:
        _rollback(conn)


def precios_de_materiales(conn, ot_ids, precios):
    """Compras pone el precio por unidad de cada material ({id: precio}).
    Solo toca materiales de esas OTs. Devuelve los ítems tocados."""
    tocados = set()
    if not precios or not ot_ids:
        return tocados
    for mid, precio in precios.items():
        try:
            p = float(precio or 0)
        except (TypeError, ValueError):
            continue
        r = conn.execute(f"SELECT item_id FROM ot_materiales WHERE id=? AND ot_id IN ({marcas(ot_ids)})",
                         [int(mid)] + list(ot_ids)).fetchone()
        if not r:
            continue
        conn.execute("UPDATE ot_materiales SET precio_unit=? WHERE id=?", (max(0.0, p), int(mid)))
        tocados.add(r["item_id"])
    for iid in tocados:
        resumir_item(conn, iid)
    return tocados


def _num(v, defecto=None):
    if v is None or v == "":
        return defecto
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(" ", "")
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return defecto


def _quien():
    return session.get("nombre") or session.get("usuario") or ""


def _ahora():
    try:
        from hora_local import ahora_iso
        return ahora_iso()
    except Exception:
        from datetime import datetime
        return datetime.now().isoformat(timespec="seconds")


def _puede_editar():
    return session.get("rol") in ("admin", "taller", "compras")


def _puede_precios():
    """Precios: administración, Compras y los de taller con la sección Compras
    (o acceso completo), igual que la pantalla de Compras."""
    rol = session.get("rol")
    if rol in ("admin", "compras"):
        return True
    if rol == "taller":
        try:
            from database import secciones_de_usuario
            secs = secciones_de_usuario(session.get("usuario_id"))
        except Exception:
            secs = []
        return not secs or "compras" in secs
    return False


def _no(msg="No tenés permiso para esto"):
    return jsonify({"ok": False, "msg": msg, "error": msg}), 403


def _item_y_lista(conn, item_id):
    it = conn.execute("SELECT id, ot_id, material_pedido, precio_compras FROM ot_items WHERE id=?",
                      (item_id,)).fetchone()
    if not it:
        return None
    d = dict(it)
    d["materiales"] = materiales_de_items(conn, [item_id]).get(item_id, [])
    return d


def _auditar(accion, detalle=""):
    try:
        from database import registrar_auditoria
        registrar_auditoria(usuario=_quien() or "?", rol=session.get("rol") or "",
                            accion=accion, categoria="Órdenes de Trabajo", detalle=detalle)
    except Exception:
        pass


@bp_ot_mat.route("/api/ot_items/<int:item_id>/materiales", methods=["POST"])
def api_material_nuevo(item_id):
    if not _puede_editar():
        return _no()
    d = request.json or {}
    desc = " ".join(str(d.get("descripcion") or "").split())[:160]
    if not desc:
        return jsonify({"ok": False, "msg": "Escribí qué material es."}), 400
    cant = _num(d.get("cantidad"), 1)
    if cant is None or cant <= 0:
        return jsonify({"ok": False, "msg": "La cantidad tiene que ser mayor que cero."}), 400
    precio = _num(d.get("precio_unit"), 0) if _puede_precios() else 0
    conn = get_connection()
    try:
        it = conn.execute("SELECT id, ot_id FROM ot_items WHERE id=?", (item_id,)).fetchone()
        if not it:
            return jsonify({"ok": False, "msg": "Ese trabajo ya no existe."}), 404
        r = conn.execute("SELECT COALESCE(MAX(orden), 0) AS m FROM ot_materiales WHERE item_id=?",
                         (item_id,)).fetchone()
        cur = conn.cursor()
        cur.execute("""INSERT INTO ot_materiales (item_id, ot_id, descripcion, cantidad, precio_unit, orden,
                                                  registrado_por, registrado_el)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (item_id, it["ot_id"], desc, cant, max(0.0, precio or 0), int(r["m"] or 0) + 1,
                     _quien(), _ahora()))
        mid = cur.lastrowid
        resumir_item(conn, item_id)
        conn.commit()
        item = _item_y_lista(conn, item_id)
    finally:
        conn.close()
    return jsonify({"ok": True, "id": mid, "item": item})


@bp_ot_mat.route("/api/ot_items/materiales/<int:mid>", methods=["PATCH"])
def api_material_editar(mid):
    if not _puede_editar():
        return _no()
    d = request.json or {}
    campos = {}
    if "descripcion" in d:
        desc = " ".join(str(d.get("descripcion") or "").split())[:160]
        if not desc:
            return jsonify({"ok": False, "msg": "Escribí qué material es (o borralo)."}), 400
        campos["descripcion"] = desc
    if "cantidad" in d:
        cant = _num(d.get("cantidad"))
        if cant is None or cant <= 0:
            return jsonify({"ok": False, "msg": "La cantidad tiene que ser mayor que cero."}), 400
        campos["cantidad"] = cant
    if "precio_unit" in d:
        if not _puede_precios():
            return _no("Los precios los pone Compras.")
        p = _num(d.get("precio_unit"), 0)
        campos["precio_unit"] = max(0.0, p or 0)
    if not campos:
        return jsonify({"ok": True})
    conn = get_connection()
    try:
        m = conn.execute("SELECT item_id FROM ot_materiales WHERE id=?", (mid,)).fetchone()
        if not m:
            return jsonify({"ok": False, "msg": "Ese material ya no existe."}), 404
        sets = ", ".join(f"{k}=?" for k in campos)
        conn.execute(f"UPDATE ot_materiales SET {sets} WHERE id=?", list(campos.values()) + [mid])
        resumir_item(conn, m["item_id"])
        conn.commit()
        item = _item_y_lista(conn, m["item_id"])
    finally:
        conn.close()
    return jsonify({"ok": True, "item": item})


@bp_ot_mat.route("/api/ot_items/materiales/<int:mid>", methods=["DELETE"])
def api_material_borrar(mid):
    if not _puede_editar():
        return _no()
    conn = get_connection()
    try:
        m = conn.execute("SELECT item_id FROM ot_materiales WHERE id=?", (mid,)).fetchone()
        if not m:
            return jsonify({"ok": True})
        conn.execute("DELETE FROM ot_materiales WHERE id=?", (mid,))
        resumir_item(conn, m["item_id"])
        conn.commit()
        item = _item_y_lista(conn, m["item_id"])
    finally:
        conn.close()
    return jsonify({"ok": True, "item": item})


# ════════════════════════════════════════════════════════════════════════════
# COCHES DE LA OT
# ════════════════════════════════════════════════════════════════════════════

@bp_ot_mat.route("/api/ots/<int:ot_id>/coches", methods=["POST"])
def api_agregar_coche(ot_id):
    if not _puede_editar():
        return _no()
    d = request.json or {}
    try:
        vid = int(d.get("vehiculo_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Elegí el coche."}), 400
    km = _num(d.get("km"), 0) or 0
    if km < 0 or km > 5_000_000:
        return jsonify({"ok": False, "msg": "Ese kilometraje no es posible: revisá el número."}), 400
    conductor = " ".join(str(d.get("conductor") or "").split())[:80]
    ok, res = agregar_coche(ot_id, vid, km, conductor)
    if not ok:
        return jsonify({"ok": False, "msg": res}), 400
    # Los trabajos de ese coche, si vinieron con él
    import database as db
    for it in (d.get("items") or [])[:60]:
        desc = " ".join(str((it or {}).get("descripcion") or "").split())[:300]
        if desc:
            db.agregar_item_ot(res, desc, (it or {}).get("tipo") or "control")
    conn = get_connection()
    try:
        h = cabeza_de(conn, res)
        v = conn.execute("SELECT n_interno, patente FROM vehiculos WHERE id=?", (vid,)).fetchone()
    finally:
        conn.close()
    _auditar(f"Agregó un coche a la OT #{h}", f"Coche {(v and (v['n_interno'] or v['patente'])) or vid}")
    return jsonify({"ok": True, "ot_id": res, "numero": h})


@bp_ot_mat.route("/api/ots/<int:ot_id>/quitar_coche", methods=["POST"])
def api_quitar_coche(ot_id):
    """Saca un coche de la OT (no el principal: para eso se borra la OT).
    Si el coche ya tiene trabajos cargados, hace falta el permiso de borrar
    OTs, porque se van con él."""
    if not _puede_editar():
        return _no()
    import database as db
    conn = get_connection()
    try:
        r = conn.execute("""SELECT o.id, o.ot_grupo, v.n_interno, v.patente,
                                   (SELECT COUNT(*) FROM ot_items i WHERE i.ot_id=o.id) AS n
                            FROM ordenes_trabajo o JOIN vehiculos v ON v.id=o.vehiculo_id WHERE o.id=?""",
                         (ot_id,)).fetchone()
    finally:
        conn.close()
    if not r:
        return jsonify({"ok": False, "msg": "Ese coche ya no está en la OT."}), 404
    if not r["ot_grupo"]:
        return jsonify({"ok": False, "msg": "Es el coche principal de la OT: para sacarlo hay que borrar la OT."}), 400
    if r["n"] and not db.puede_borrar_ots(session.get("usuario_id"), session.get("rol")):
        return _no("Este coche ya tiene trabajos cargados: sacarlo los borra. Pedile a administración.")
    db.eliminar_ot(ot_id)
    _auditar(f"Sacó un coche de la OT #{r['ot_grupo']}",
             f"Coche {r['n_interno'] or r['patente']} · {r['n']} trabajo(s)")
    return jsonify({"ok": True, "numero": r["ot_grupo"]})
