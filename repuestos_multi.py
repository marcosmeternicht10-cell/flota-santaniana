"""
repuestos_multi.py — Un repuesto, varios proveedores (La Santaniana)

El mismo código de fabricante se puede comprar a más de un proveedor. El
repuesto sigue siendo UNO solo (un stock, una ubicación en el estante), y en
su ficha se anotan los proveedores que lo venden, cada uno con su precio.

- El proveedor "principal" es el que ya existía en repuestos.proveedor: se
  sigue mostrando primero y es al que se le pide por WhatsApp desde la ficha.
- Cada proveedor guarda su último precio y, si se quiere, el código con el
  que él lo vende (a veces no es el del fabricante).
- Si alguien intenta cargar un código que ya existe, en vez de rebotar se le
  ofrece sumar ese proveedor al repuesto que ya está.
- Al registrar una entrada de stock eligiendo el proveedor, su precio se
  actualiza solo.

Los contactos (teléfono, RUC, fantasía) siguen saliendo del directorio de
proveedores (repuestos_proveedores): se cargan una vez y valen para todos.
"""

from db_compat import get_connection, USE_POSTGRES, IntegrityError

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"


def _hoy():
    try:
        from hora_local import hoy
        return hoy()
    except Exception:
        import datetime
        return datetime.date.today().isoformat()


def _clave(nombre):
    return " ".join(str(nombre or "").split()).lower()


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


# ─── Tabla ───────────────────────────────────────────────────────────────────

def inicializar():
    conn = get_connection()
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS repuestos_por_proveedor (
            id {PK},
            repuesto_id INTEGER NOT NULL,
            clave TEXT NOT NULL,              -- nombre del proveedor en minúsculas
            proveedor TEXT NOT NULL,          -- como figura en el directorio
            precio REAL DEFAULT 0,            -- último precio por unidad
            codigo_prov TEXT DEFAULT '',      -- cómo lo llama ese proveedor (opcional)
            actualizado TEXT DEFAULT '',
            UNIQUE (repuesto_id, clave)
        )
    """)
    try:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_rep_prov_clave ON repuestos_por_proveedor (clave)")
    except Exception:
        pass
    conn.commit()
    conn.close()
    sincronizar()


def sincronizar(repuesto_id=None):
    """Que el proveedor principal de cada repuesto figure también en la lista.

    Cubre los repuestos cargados antes de que existiera esto y los que se
    editan desde la ficha cambiando el proveedor. No pisa precios ya
    anotados."""
    conn = get_connection()
    try:
        q = "SELECT id, proveedor, costo_unitario, fecha_alta FROM repuestos WHERE proveedor<>''"
        params = []
        if repuesto_id:
            q += " AND id=?"
            params.append(repuesto_id)
        reps = conn.execute(q, params).fetchall()
        if not reps:
            return
        q2 = "SELECT repuesto_id, clave FROM repuestos_por_proveedor"
        if repuesto_id:
            q2 += " WHERE repuesto_id=?"
        ya = {(r["repuesto_id"], r["clave"]) for r in conn.execute(q2, params).fetchall()}
        for r in reps:
            k = _clave(r["proveedor"])
            if not k or (r["id"], k) in ya:
                continue
            try:
                conn.execute("""INSERT INTO repuestos_por_proveedor
                                (repuesto_id, clave, proveedor, precio, actualizado)
                                VALUES (?,?,?,?,?)""",
                             (r["id"], k, " ".join(str(r["proveedor"]).split()),
                              _num(r["costo_unitario"]), str(r["fecha_alta"] or "")[:10] or _hoy()))
                ya.add((r["id"], k))
            except IntegrityError:
                pass
        conn.commit()
    finally:
        conn.close()


# ─── Consultas ───────────────────────────────────────────────────────────────

def lista(repuesto_id, principal=""):
    """Los proveedores de un repuesto, con su contacto del directorio.
    Primero el principal; después del más barato al más caro."""
    conn = get_connection()
    filas = [dict(r) for r in conn.execute(
        "SELECT * FROM repuestos_por_proveedor WHERE repuesto_id=?", (repuesto_id,)).fetchall()]
    contactos = {}
    claves = sorted({f["clave"] for f in filas})
    if claves:
        try:
            for c in conn.execute(
                    f"""SELECT clave, nombre, fantasia, contacto, telefono, ruc
                        FROM repuestos_proveedores WHERE clave IN ({','.join('?' * len(claves))})""",
                    claves).fetchall():
                contactos[c["clave"]] = c
        except Exception:
            pass
    conn.close()
    kp = _clave(principal)
    con_precio = [f["precio"] for f in filas if _num(f["precio"]) > 0]
    minimo = min(con_precio) if len(con_precio) > 1 else None
    salida = []
    for f in filas:
        c = contactos.get(f["clave"])
        salida.append({
            "id": f["id"],
            "proveedor": (c["nombre"] if c else "") or f["proveedor"],
            "fantasia": (c["fantasia"] if c else "") or "",
            "contacto": (c["contacto"] if c else "") or "",
            "telefono": (c["telefono"] if c else "") or "",
            "ruc": (c["ruc"] if c else "") or "",
            "precio": _num(f["precio"]),
            "codigo_prov": f.get("codigo_prov") or "",
            "actualizado": f.get("actualizado") or "",
            "principal": f["clave"] == kp,
            "mas_barato": minimo is not None and _num(f["precio"]) == minimo,
        })
    salida.sort(key=lambda x: (not x["principal"], x["precio"] <= 0, x["precio"], x["proveedor"].lower()))
    return salida


def conteos():
    """Cuántos proveedores tiene cada repuesto (para la lista)."""
    conn = get_connection()
    try:
        filas = conn.execute("""SELECT repuesto_id, COUNT(*) AS n FROM repuestos_por_proveedor
                                GROUP BY repuesto_id""").fetchall()
        return {r["repuesto_id"]: int(r["n"]) for r in filas}
    except Exception:
        return {}
    finally:
        conn.close()


def usos_por_clave(conn):
    """En cuántos repuestos activos figura cada proveedor (principal o no)."""
    try:
        filas = conn.execute("""SELECT x.clave AS k, COUNT(DISTINCT x.repuesto_id) AS n
                                FROM repuestos_por_proveedor x
                                JOIN repuestos r ON r.id = x.repuesto_id
                                WHERE r.activo=1 GROUP BY x.clave""").fetchall()
        return {r["k"]: int(r["n"]) for r in filas}
    except Exception:
        return {}


def repuesto_por_codigo(codigo):
    """Si el código ya está cargado: qué repuesto es y quién lo vende."""
    cod = str(codigo or "").upper().strip()
    if not cod:
        return None
    conn = get_connection()
    r = conn.execute("""SELECT id, codigo, descripcion, aplicacion, activo, proveedor, stock_actual, unidad
                        FROM repuestos WHERE UPPER(TRIM(codigo))=?""", (cod,)).fetchone()
    conn.close()
    if not r:
        return None
    d = dict(r)
    d["activo"] = int(d.get("activo") if d.get("activo") is not None else 1)
    d["proveedores"] = [p["fantasia"] or p["proveedor"] for p in lista(d["id"], d.get("proveedor"))]
    return d


# ─── Cambios ─────────────────────────────────────────────────────────────────

def agregar(repuesto_id, proveedor, precio=0, codigo_prov=None, contacto=None, telefono=None):
    """Suma un proveedor al repuesto, o actualiza su precio si ya estaba.

    Si el repuesto no tenía proveedor principal, este pasa a serlo. Si
    estaba dado de baja, se reactiva (lo que pasa cuando alguien vuelve a
    cargar un código viejo)."""
    from repuestos_db import guardar_contacto_proveedor
    if not str(proveedor or "").strip():
        return False, "Poné el nombre del proveedor."
    nombre = guardar_contacto_proveedor(proveedor, contacto, telefono)
    k = _clave(nombre)
    precio = _num(precio)
    conn = get_connection()
    try:
        rep = conn.execute("SELECT id, proveedor, costo_unitario, activo FROM repuestos WHERE id=?",
                           (repuesto_id,)).fetchone()
        if not rep:
            return False, "El repuesto no existe."
        fila = conn.execute("SELECT id, precio FROM repuestos_por_proveedor WHERE repuesto_id=? AND clave=?",
                            (repuesto_id, k)).fetchone()
        nuevo = fila is None
        if nuevo:
            conn.execute("""INSERT INTO repuestos_por_proveedor
                            (repuesto_id, clave, proveedor, precio, codigo_prov, actualizado)
                            VALUES (?,?,?,?,?,?)""",
                         (repuesto_id, k, nombre, precio, str(codigo_prov or "").upper().strip(), _hoy()))
        else:
            sets, vals = ["actualizado=?"], [_hoy()]
            if precio > 0:
                sets.append("precio=?")
                vals.append(precio)
            if codigo_prov is not None:
                sets.append("codigo_prov=?")
                vals.append(str(codigo_prov or "").upper().strip())
            conn.execute(f"UPDATE repuestos_por_proveedor SET {', '.join(sets)} WHERE id=?", vals + [fila["id"]])
        reactivado = not int(rep["activo"] if rep["activo"] is not None else 1)
        cambios, vals = [], []
        if not str(rep["proveedor"] or "").strip():
            cambios.append("proveedor=?")
            vals.append(nombre)
        if _num(rep["costo_unitario"]) <= 0 and precio > 0:
            cambios.append("costo_unitario=?")
            vals.append(precio)
        if reactivado:
            cambios.append("activo=1")
        if cambios:
            conn.execute(f"UPDATE repuestos SET {', '.join(cambios)} WHERE id=?", vals + [repuesto_id])
        conn.commit()
        return True, {"nuevo": nuevo, "reactivado": reactivado, "proveedor": nombre}
    finally:
        conn.close()


def _fila(conn, pid):
    return conn.execute("SELECT * FROM repuestos_por_proveedor WHERE id=?", (pid,)).fetchone()


def editar(pid, precio=None, codigo_prov=None):
    conn = get_connection()
    try:
        f = _fila(conn, pid)
        if not f:
            return False, "Ese proveedor ya no está en el repuesto."
        sets, vals = ["actualizado=?"], [_hoy()]
        if precio is not None:
            sets.append("precio=?")
            vals.append(_num(precio))
        if codigo_prov is not None:
            sets.append("codigo_prov=?")
            vals.append(str(codigo_prov or "").upper().strip())
        conn.execute(f"UPDATE repuestos_por_proveedor SET {', '.join(sets)} WHERE id=?", vals + [pid])
        conn.commit()
        return True, f["repuesto_id"]
    finally:
        conn.close()


def quitar(pid):
    """Saca un proveedor del repuesto. Si era el principal, pasa a serlo el
    más barato de los que quedan (o ninguno)."""
    conn = get_connection()
    try:
        f = _fila(conn, pid)
        if not f:
            return False, "Ese proveedor ya no está en el repuesto."
        rid = f["repuesto_id"]
        rep = conn.execute("SELECT proveedor FROM repuestos WHERE id=?", (rid,)).fetchone()
        conn.execute("DELETE FROM repuestos_por_proveedor WHERE id=?", (pid,))
        if rep and _clave(rep["proveedor"]) == f["clave"]:
            resto = conn.execute("""SELECT proveedor, precio FROM repuestos_por_proveedor
                                    WHERE repuesto_id=?""", (rid,)).fetchall()
            resto = sorted(resto, key=lambda r: (_num(r["precio"]) <= 0, _num(r["precio"])))
            conn.execute("UPDATE repuestos SET proveedor=? WHERE id=?",
                         (resto[0]["proveedor"] if resto else "", rid))
        conn.commit()
        return True, rid
    finally:
        conn.close()


def hacer_principal(pid):
    conn = get_connection()
    try:
        f = _fila(conn, pid)
        if not f:
            return False, "Ese proveedor ya no está en el repuesto."
        conn.execute("UPDATE repuestos SET proveedor=? WHERE id=?", (f["proveedor"], f["repuesto_id"]))
        conn.commit()
        return True, f["repuesto_id"]
    finally:
        conn.close()
