"""
ot_unica.py — Una sola OT abierta por coche (La Santaniana)

Antes cada reporte del chofer abría una OT nueva y un coche terminaba con
varias OTs abiertas a la vez. Ahora:

  · Cada coche tiene UNA OT abierta. Lo nuevo de ese coche (el reporte del
    chofer, una OT nueva, el turno del preventivo, sumarlo a una OT de varios
    coches) se agrega ahí, con su fecha.
  · Las OTs pendientes que ya había se juntan en la más vieja de cada coche
    (con sus trabajos, materiales, fotos, lo sacado del depósito, lo cargado
    en el preventivo, los turnos y la verificación del km). Las que están en
    Compras no se tocan: tienen su presupuesto y su firma.
  · Cada trabajo guarda su fecha y quién lo reportó, para verlos separados
    por día.
  · La OT se cierra recién cuando todos sus trabajos están completados.

Enganche en app.py (después de ot_materiales):
    from ot_unica import init_ot_unica
    init_ot_unica()
"""

from db_compat import get_connection, USE_POSTGRES

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"


def _rollback(conn):
    try:
        conn.rollback()
    except Exception:
        pass


def _hoy():
    try:
        from hora_local import hoy
        return hoy()
    except Exception:
        from datetime import date
        return date.today().isoformat()


def _ahora():
    try:
        from hora_local import ahora_iso
        return ahora_iso()
    except Exception:
        from datetime import datetime
        return datetime.now().isoformat(timespec="seconds")


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


def origen_de(procedencia):
    p = str(procedencia or "").lower()
    if "chofer" in p:
        return "chofer"
    if "preventivo" in p:
        return "preventivo"
    return "taller"


def init_ot_unica():
    conn = get_connection()
    for col, tipo in (("fecha", "TEXT DEFAULT ''"), ("origen", "TEXT DEFAULT ''"),
                      ("reportado_por", "TEXT DEFAULT ''")):
        _agregar_columna(conn, "ot_items", col, tipo)
    try:
        conn.execute(f"""CREATE TABLE IF NOT EXISTS ot_fusiones (
            id {PK},
            origen INTEGER NOT NULL,
            destino INTEGER NOT NULL,
            vehiculo_id INTEGER,
            items INTEGER DEFAULT 0,
            fecha TEXT DEFAULT '')""")
        conn.commit()
    except Exception:
        _rollback(conn)
    # Los trabajos que ya estaban: la fecha y el origen son los de su OT
    try:
        conn.execute("""UPDATE ot_items SET fecha = (SELECT o.fecha_apertura FROM ordenes_trabajo o
                                                    WHERE o.id = ot_items.ot_id)
                        WHERE COALESCE(fecha, '') = ''""")
        conn.execute("""UPDATE ot_items SET
                          origen = CASE WHEN (SELECT LOWER(COALESCE(o.procedencia,'')) FROM ordenes_trabajo o
                                              WHERE o.id = ot_items.ot_id) LIKE '%chofer%' THEN 'chofer'
                                        WHEN (SELECT LOWER(COALESCE(o.procedencia,'')) FROM ordenes_trabajo o
                                              WHERE o.id = ot_items.ot_id) LIKE '%preventivo%' THEN 'preventivo'
                                        ELSE 'taller' END,
                          reportado_por = COALESCE((SELECT o.conductor FROM ordenes_trabajo o
                                                    WHERE o.id = ot_items.ot_id), '')
                        WHERE COALESCE(origen, '') = ''""")
        conn.commit()
    except Exception as e:
        _rollback(conn)
        print("[ot_unica] no se pudieron completar las fechas de los trabajos:", e)
    conn.close()
    try:
        n = juntar_pendientes()
        if n:
            print(f"[ot_unica] {n} OT(s) pendiente(s) juntada(s) en la OT abierta de su coche")
    except Exception as e:
        print("[ot_unica] no se pudieron juntar las OTs pendientes:", e)


# ════════════════════════════════════════════════════════════════════════════
# LA OT ABIERTA DE CADA COCHE
# ════════════════════════════════════════════════════════════════════════════

ABIERTA = "COALESCE(estado,'') <> 'cerrada' AND COALESCE(estado_compras,'') = ''"


def ot_abierta_de(conn, vehiculo_id, salvo=None):
    """La OT abierta del coche (la más vieja), sin contar las que están en
    Compras. None si no tiene."""
    sql = f"SELECT id FROM ordenes_trabajo WHERE vehiculo_id=? AND {ABIERTA}"
    params = [vehiculo_id]
    if salvo:
        sql += f" AND id NOT IN ({','.join('?' * len(salvo))})"
        params += list(salvo)
    r = conn.execute(sql + " ORDER BY id LIMIT 1", params).fetchone()
    return r["id"] if r else None


def abierta(vehiculo_id):
    """Para la pantalla: la OT abierta del coche, su número y cuánto falta."""
    conn = get_connection()
    try:
        oid = ot_abierta_de(conn, vehiculo_id)
        if not oid:
            return None
        o = conn.execute("SELECT id, ot_grupo, fecha_apertura FROM ordenes_trabajo WHERE id=?", (oid,)).fetchone()
        r = conn.execute("""SELECT COUNT(*) AS n, SUM(CASE WHEN estado='completado' THEN 0 ELSE 1 END) AS p
                            FROM ot_items WHERE ot_id=?""", (oid,)).fetchone()
        return {"ot_id": oid, "numero": o["ot_grupo"] or oid, "desde": o["fecha_apertura"],
                "trabajos": int(r["n"] or 0), "pendientes": int(r["p"] or 0)}
    finally:
        conn.close()


def agregar_items(ot_id, items, origen="taller", reportado_por="", fecha=None, conn=None):
    """Suma trabajos a la OT con su fecha y quién los reportó. Devuelve los ids."""
    propia = conn is None
    conn = conn or get_connection()
    fecha = fecha or _hoy()
    ids = []
    try:
        for it in items or []:
            desc = " ".join(str(it.get("descripcion") or "").split())[:300]
            if not desc:
                continue
            cur = conn.execute("""INSERT INTO ot_items (ot_id, descripcion, tipo, estado, costo, fecha, origen, reportado_por)
                                  VALUES (?,?,?,?,?,?,?,?)""",
                               (ot_id, desc, it.get("tipo") or "control", it.get("estado") or "pendiente",
                                float(it.get("costo") or 0), fecha, origen, (reportado_por or "")[:80]))
            ids.append(cur.lastrowid)
        # Si la OT ya estaba en proceso o vuelve a tener pendientes, sigue abierta
        if propia:
            conn.commit()
    finally:
        if propia:
            conn.close()
    return ids


def sumar_al_grupo(conn, cabeza, ot_id):
    """La OT abierta de un coche pasa a ser parte de una OT de varios coches
    (con todo lo que tenía). Solo si está suelta y la del grupo no está en
    Compras. Devuelve True si quedó en el grupo."""
    if not cabeza or not ot_id or cabeza == ot_id:
        return False
    o = conn.execute("""SELECT o.ot_grupo, (SELECT COUNT(*) FROM ordenes_trabajo h WHERE h.ot_grupo = o.id) AS hijos
                        FROM ordenes_trabajo o WHERE o.id=?""", (ot_id,)).fetchone()
    cab = conn.execute("SELECT COALESCE(estado_compras,'') AS ec, ot_grupo FROM ordenes_trabajo WHERE id=?",
                       (cabeza,)).fetchone()
    if not o or not cab or o["ot_grupo"] == cabeza:
        return bool(o and o["ot_grupo"] == cabeza)
    if o["ot_grupo"] or o["hijos"] or cab["ec"] or cab["ot_grupo"]:
        return False
    conn.execute("UPDATE ordenes_trabajo SET ot_grupo=? WHERE id=?", (cabeza, ot_id))
    return True


def subir_km(conn, ot_id, km):
    """El km más nuevo del coche queda en su OT abierta (si el de la OT no es
    una lectura verificada en el tablero)."""
    try:
        km = float(km or 0)
    except (TypeError, ValueError):
        return
    if km <= 0:
        return
    o = conn.execute("""SELECT o.km, COALESCE(v.km_verif_ot, 0) AS verif FROM ordenes_trabajo o
                        JOIN vehiculos v ON v.id = o.vehiculo_id WHERE o.id=?""", (ot_id,)).fetchone()
    if o and int(o["verif"] or 0) != ot_id and km > float(o["km"] or 0):
        conn.execute("UPDATE ordenes_trabajo SET km=? WHERE id=?", (km, ot_id))


# ════════════════════════════════════════════════════════════════════════════
# JUNTAR
# ════════════════════════════════════════════════════════════════════════════

def _ejecutar(conn, sql, params):
    """Una tabla que puede no existir (módulos opcionales) no frena la fusión."""
    try:
        conn.execute("SAVEPOINT otu" if USE_POSTGRES else "SAVEPOINT otu")
        conn.execute(sql, params)
        conn.execute("RELEASE SAVEPOINT otu")
    except Exception:
        try:
            conn.execute("ROLLBACK TO SAVEPOINT otu")
            conn.execute("RELEASE SAVEPOINT otu")
        except Exception:
            pass


def juntar(conn, origen, destino):
    """Pasa todo lo de la OT 'origen' a 'destino' (del mismo coche) y borra
    'origen'. No hace commit: lo hace quien llama."""
    o = conn.execute("SELECT * FROM ordenes_trabajo WHERE id=?", (origen,)).fetchone()
    d = conn.execute("SELECT * FROM ordenes_trabajo WHERE id=?", (destino,)).fetchone()
    if not o or not d or o["vehiculo_id"] != d["vehiculo_id"]:
        return 0
    o, d = dict(o), dict(d)
    n = conn.execute("SELECT COUNT(*) AS n FROM ot_items WHERE ot_id=?", (origen,)).fetchone()["n"]
    # Los trabajos guardan la fecha y quién los reportó en su OT de origen
    conn.execute("UPDATE ot_items SET fecha=? WHERE ot_id=? AND COALESCE(fecha,'')=''",
                 (o.get("fecha_apertura") or "", origen))
    conn.execute("UPDATE ot_items SET reportado_por=? WHERE ot_id=? AND COALESCE(reportado_por,'')=''",
                 (o.get("conductor") or "", origen))
    conn.execute("UPDATE ot_items SET origen=? WHERE ot_id=? AND COALESCE(origen,'')=''",
                 (origen_de(o.get("procedencia")), origen))
    for sql in ("UPDATE ot_items SET ot_id=? WHERE ot_id=?",
                "UPDATE ot_fotos SET ot_id=? WHERE ot_id=?"):
        conn.execute(sql, (destino, origen))
    for sql in ("UPDATE ot_materiales SET ot_id=? WHERE ot_id=?",
                "UPDATE repuestos_movimientos SET ot_id=? WHERE ot_id=?",
                "UPDATE mantenimientos_realizados SET ot_id=? WHERE ot_id=?",
                "UPDATE taller_turnos SET ot_id=? WHERE ot_id=?"):
        _ejecutar(conn, sql, (destino, origen))
    # Los correctivos que se generaron solos llevan el número de la OT
    _ejecutar(conn, "UPDATE correctivos SET observaciones = REPLACE(observaciones, ?, ?) WHERE observaciones LIKE ?",
              (f"[OT#{origen}-item", f"[OT#{destino}-item", f"%[OT#{origen}-item%"))
    # El km: el verificado manda; si no, el más nuevo
    verif = conn.execute("SELECT COALESCE(km_verif_ot,0) AS v FROM vehiculos WHERE id=?",
                         (d["vehiculo_id"],)).fetchone()
    km_d = float(d.get("km") or 0)
    if verif and int(verif["v"] or 0) == origen:
        conn.execute("UPDATE vehiculos SET km_verif_ot=? WHERE id=?", (destino, d["vehiculo_id"]))
        km_d = float(o.get("km") or 0) or km_d
    elif not (verif and int(verif["v"] or 0) == destino):
        km_d = max(km_d, float(o.get("km") or 0))
    obs = [x for x in (d.get("observaciones") or "",
                       f"OT #{origen} ({o.get('fecha_apertura') or ''}): {o['observaciones']}" if o.get("observaciones") else "")
           if x]
    estado = "en_proceso" if "en_proceso" in (d.get("estado"), o.get("estado")) else (d.get("estado") or "abierta")
    fecha = min(x for x in (d.get("fecha_apertura"), o.get("fecha_apertura")) if x) if (d.get("fecha_apertura") or o.get("fecha_apertura")) else ""
    conn.execute("""UPDATE ordenes_trabajo SET km=?, observaciones=?, estado=?, fecha_apertura=?,
                       conductor=COALESCE(NULLIF(conductor,''), ?) WHERE id=?""",
                 (km_d, " · ".join(obs)[:1000], estado, fecha, o.get("conductor") or "", destino))
    conn.execute("DELETE FROM ordenes_trabajo WHERE id=?", (origen,))
    conn.execute("INSERT INTO ot_fusiones (origen, destino, vehiculo_id, items, fecha) VALUES (?,?,?,?,?)",
                 (origen, destino, d["vehiculo_id"], n, _ahora()))
    return n


def juntar_pendientes():
    """Cada coche con más de una OT pendiente queda con una sola: la más
    vieja, con todo lo de las otras. Las OTs de varios coches no se desarman
    (pueden recibir, no se mudan) y las que están en Compras no se tocan."""
    conn = get_connection()
    juntadas = []
    try:
        filas = conn.execute(f"""SELECT o.id, o.vehiculo_id, o.ot_grupo,
                                        (SELECT COUNT(*) FROM ordenes_trabajo h WHERE h.ot_grupo = o.id) AS hijos
                                 FROM ordenes_trabajo o WHERE {ABIERTA.replace('estado', 'o.estado')}
                                 ORDER BY o.vehiculo_id, o.id""").fetchall()
        por_coche = {}
        for f in filas:
            por_coche.setdefault(f["vehiculo_id"], []).append(dict(f))
        for vid, ots in por_coche.items():
            if len(ots) < 2:
                continue
            destino = ots[0]["id"]
            for o in ots[1:]:
                if o["ot_grupo"] or o["hijos"]:
                    continue                  # es parte de una OT de varios coches
                n = juntar(conn, o["id"], destino)
                juntadas.append((o["id"], destino, vid, n))
        conn.commit()
    except Exception:
        _rollback(conn)
        raise
    finally:
        conn.close()
    if juntadas:
        try:
            from database import registrar_auditoria
            for origen, destino, vid, n in juntadas:
                registrar_auditoria(usuario="Sistema", rol="", accion=f"Juntó la OT #{origen} en la #{destino}",
                                    categoria="Órdenes de Trabajo",
                                    detalle=f"Una sola OT abierta por coche · {n} trabajo(s) pasaron a la #{destino}")
        except Exception:
            pass
    return len(juntadas)


# ════════════════════════════════════════════════════════════════════════════
# CERRAR: solo con todo terminado
# ════════════════════════════════════════════════════════════════════════════

def pendientes_de(conn, ids):
    """Los trabajos sin completar de esas OTs."""
    if not ids:
        return []
    return [dict(r) for r in conn.execute(
        f"""SELECT i.id, i.descripcion, i.estado, i.ot_id FROM ot_items i
            WHERE i.ot_id IN ({','.join('?' * len(ids))}) AND COALESCE(i.estado,'') <> 'completado'
            ORDER BY i.id""", list(ids)).fetchall()]


def motivo_para_no_cerrar(ot_id):
    """None si se puede cerrar; si no, el mensaje (cuántos trabajos faltan)."""
    conn = get_connection()
    try:
        try:
            import ot_materiales
            ids = ot_materiales.ids_grupo(conn, ot_id) or [ot_id]
        except Exception:
            ids = [ot_id]
        p = pendientes_de(conn, ids)
    finally:
        conn.close()
    if not p:
        return None
    lista = ", ".join(x["descripcion"] for x in p[:3]) + ("…" if len(p) > 3 else "")
    return (f"No se puede cerrar: falta{'n' if len(p) != 1 else ''} {len(p)} trabajo{'s' if len(p) != 1 else ''} "
            f"por completar ({lista}). Completalos o, si no se hacen, sacalos de la OT.")


def motivo_para_no_reabrir(ot_id):
    """Reabrir una OT vieja no puede dejar al coche con dos OTs abiertas."""
    conn = get_connection()
    try:
        try:
            import ot_materiales
            ids = ot_materiales.ids_grupo(conn, ot_id) or [ot_id]
        except Exception:
            ids = [ot_id]
        for i in ids:
            r = conn.execute("""SELECT o.vehiculo_id, v.n_interno, v.patente, COALESCE(o.estado_compras,'') AS ec
                                FROM ordenes_trabajo o JOIN vehiculos v ON v.id = o.vehiculo_id WHERE o.id=?""",
                             (i,)).fetchone()
            if not r or r["ec"]:
                continue
            otra = ot_abierta_de(conn, r["vehiculo_id"], salvo=ids)
            if otra:
                g = conn.execute("SELECT COALESCE(ot_grupo, id) AS n FROM ordenes_trabajo WHERE id=?", (otra,)).fetchone()
                return (f"El coche {r['n_interno'] or r['patente']} ya tiene abierta la OT #{g['n']}: "
                        f"agregá ahí lo que falte.")
        return None
    finally:
        conn.close()
