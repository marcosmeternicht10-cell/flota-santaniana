"""
personal_taller.py — El personal del taller, cada uno con su número (La Santaniana)

  · La lista del taller: número, nombre, puesto, edad y datos de contacto. El
    número es fijo: si alguien se va se lo da de baja y su número no se vuelve
    a usar (así lo que hizo sigue siendo suyo).
  · En la OT, en cada ítem, se pone el número de quién hizo el trabajo (uno o
    varios: un cambio de pulmón entre el 20 y el 21). También se puede escribir
    un nombre sin número (un taller de afuera, por ejemplo).
  · Con eso sale quién trabaja más y quién no, en qué coches, y lo que quedó
    sin número para completarlo.

La columna ot_items.tecnico sigue existiendo y se mantiene sola con el texto
("N°20 Rodrigo Rolón"), así el PDF de la OT, Compras y el historial por coche
la siguen mostrando sin cambios.

Enganche en app.py:
    from personal_taller import bp_personal, init_personal_taller
    init_personal_taller()
    app.register_blueprint(bp_personal)
"""

import io
import re
import unicodedata
from datetime import date, timedelta

from flask import Blueprint, request, jsonify, session, send_file
from db_compat import get_connection, USE_POSTGRES

from hora_local import hoy as _hoy_txt, ahora_iso

bp_personal = Blueprint("personal_taller", __name__)

PK = "SERIAL PRIMARY KEY" if USE_POSTGRES else "INTEGER PRIMARY KEY AUTOINCREMENT"

# La lista que pasó el taller (octubre 2026). Los números son los de la lista:
# el 7 no está (quedó libre).
LISTA_INICIAL = [
    (1, "Carlos Galloso", "Jefe de taller", None),
    (2, "Juan Bautista Prieto Fernandez", "Motorista", 67),
    (3, "Angelino Candia Bogado", "Motor, caja y diferencial", 64),
    (4, "Rodrigo Ruben Duarte Núñez", "Electricista", 20),
    (5, "Pablino Cabañas Giménez", "Mecánica general", 46),
    (6, "Benicio Torres Bogado", "Mecánica general", 57),
    (8, "Miguel Ayala Rodríguez", "Inspección / veedor", 71),
    (9, "Mario Luis González", "Aire acondicionado / electricidad", 38),
    (10, "Juan Ignacio González Alvarez", "Chapería / pintura", 50),
    (11, "Miguel Angel Irala Esquivel", "Chapería / pintura", 53),
    (12, "Ignacio Andres Silva Martínez", "Chapería / pintura", 50),
    (13, "Miguel Angel Cano Salinas", "Caja y diferencial", 59),
    (14, "Crispin Arce Villalba", "Engrase", 60),
    (15, "Catalino Garcete Candia", "Lavadero", 56),
    (16, "Hugo Rodriguez", "Lavadero", 57),
    (17, "Jorge Luis Campuzano", "Lavadero / limpieza interior", 38),
    (18, "Carlos Cipriano Saldivar Sanabria", "Lavadero / limpieza interior", 62),
    (19, "Wilfrido Torres García", "Mecánica general", 42),
    (20, "Rodrigo Rolón", "Mecánica general", None),
    (21, "Claudio Diaz", "Mecánica general", None),
    (22, "Alfredo Riveros", "Mecánica general", None),
]

CAMPOS = ("numero", "nombre", "puesto", "edad", "nacimiento", "ci", "telefono", "activo")


# ════════════════════════════════════════════════════════════════════════════
# TABLAS
# ════════════════════════════════════════════════════════════════════════════

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


def init_personal_taller():
    conn = get_connection()
    nueva = not _existe_tabla(conn, "taller_personal")
    for sql in (
        f"""CREATE TABLE IF NOT EXISTS taller_personal (
            id {PK},
            numero INTEGER NOT NULL UNIQUE,
            nombre TEXT NOT NULL,
            puesto TEXT DEFAULT '',
            edad INTEGER,
            nacimiento TEXT DEFAULT '',
            ci TEXT DEFAULT '',
            telefono TEXT DEFAULT '',
            activo INTEGER DEFAULT 1,
            creado_el TEXT DEFAULT '',
            actualizado_el TEXT DEFAULT '')""",
        f"""CREATE TABLE IF NOT EXISTS ot_item_personal (
            id {PK},
            item_id INTEGER NOT NULL,
            personal_id INTEGER NOT NULL,
            asignado_el TEXT DEFAULT '',
            asignado_por TEXT DEFAULT '',
            UNIQUE (item_id, personal_id))""",
        "CREATE INDEX IF NOT EXISTS ix_itpers_item ON ot_item_personal (item_id)",
        "CREATE INDEX IF NOT EXISTS ix_itpers_pers ON ot_item_personal (personal_id)",
    ):
        try:
            conn.execute(sql)
            conn.commit()
        except Exception:
            _rollback(conn)
    # Lo que se escribe a mano (sin número): un taller de afuera, un nombre viejo
    _agregar_columna(conn, "ot_items", "tecnico_otro", "TEXT DEFAULT ''")

    if nueva:
        ahora = ahora_iso()
        for numero, nombre, puesto, edad in LISTA_INICIAL:
            try:
                conn.execute("""INSERT INTO taller_personal (numero, nombre, puesto, edad, activo, creado_el, actualizado_el)
                                VALUES (?,?,?,?,1,?,?) ON CONFLICT (numero) DO NOTHING""",
                             (numero, nombre, puesto, edad, ahora, ahora))
                conn.commit()
            except Exception:
                _rollback(conn)
        # Lo que ya estaba escrito en el técnico de las OT queda como texto
        # (no se adivina quién es: se asigna a mano desde Personal). Solo si
        # alguien escribió directamente un número de la lista, se vincula.
        try:
            _migrar_texto_viejo(conn)
            conn.commit()
        except Exception:
            _rollback(conn)
    conn.close()


def _migrar_texto_viejo(conn):
    por_numero = {r["numero"]: r["id"] for r in conn.execute("SELECT id, numero FROM taller_personal").fetchall()}
    filas = conn.execute("""SELECT id, tecnico FROM ot_items
                            WHERE COALESCE(tecnico,'') != '' AND COALESCE(tecnico_otro,'') = ''""").fetchall()
    for f in filas:
        texto = (f["tecnico"] or "").strip()
        m = re.fullmatch(r"(?:n[°º.]?\s*)?#?\s*(\d{1,4})", texto, re.I)
        pid = por_numero.get(int(m.group(1))) if m else None
        if pid:
            conn.execute("""INSERT INTO ot_item_personal (item_id, personal_id, asignado_el, asignado_por)
                            VALUES (?,?,?,?) ON CONFLICT (item_id, personal_id) DO NOTHING""",
                         (f["id"], pid, ahora_iso(), "sistema"))
            _recalcular_texto(conn, [f["id"]])
        else:
            conn.execute("UPDATE ot_items SET tecnico_otro=? WHERE id=?", (texto[:120], f["id"]))


# ════════════════════════════════════════════════════════════════════════════
# UTILIDADES
# ════════════════════════════════════════════════════════════════════════════

def _norm(s):
    s = unicodedata.normalize("NFD", str(s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).strip()


def _edad(p):
    nac = str(p.get("nacimiento") or "")[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", nac):
        try:
            n = date.fromisoformat(nac)
            h = date.fromisoformat(_hoy_txt())
            return h.year - n.year - ((h.month, h.day) < (n.month, n.day))
        except ValueError:
            pass
    return p.get("edad")


def _persona(r):
    p = dict(r)
    p["activo"] = 1 if p.get("activo") in (1, True, "1", None) else 0
    p["edad_actual"] = _edad(p)
    return p


def etiqueta(p):
    return f"N°{p['numero']} {p['nombre']}"


def _texto(personas, otro):
    partes = [etiqueta(p) for p in sorted(personas, key=lambda x: x["numero"])]
    if (otro or "").strip():
        partes.append(otro.strip())
    return ", ".join(partes)


def _personas_de_items(conn, item_ids):
    """{item_id: [persona, ...]} en una sola consulta."""
    res = {int(i): [] for i in item_ids}
    if not res:
        return res
    ids = list(res)
    for k in range(0, len(ids), 500):
        tramo = ids[k:k + 500]
        marcas = ",".join("?" * len(tramo))
        for r in conn.execute(f"""SELECT ip.item_id, p.id, p.numero, p.nombre, p.puesto, p.activo
                                  FROM ot_item_personal ip JOIN taller_personal p ON p.id = ip.personal_id
                                  WHERE ip.item_id IN ({marcas}) ORDER BY p.numero""", tuple(tramo)).fetchall():
            res[r["item_id"]].append({"id": r["id"], "numero": r["numero"], "nombre": r["nombre"],
                                      "puesto": r["puesto"] or "", "activo": 0 if r["activo"] in (0, "0", False) else 1})
    return res


def _recalcular_texto(conn, item_ids):
    """Deja ot_items.tecnico con el texto que corresponde (para lo que ya lo muestra)."""
    if not item_ids:
        return
    pers = _personas_de_items(conn, item_ids)
    marcas = ",".join("?" * len(pers))
    otros = {r["id"]: r["tecnico_otro"] or "" for r in conn.execute(
        f"SELECT id, tecnico_otro FROM ot_items WHERE id IN ({marcas})", tuple(pers)).fetchall()}
    for iid, personas in pers.items():
        if iid in otros:
            conn.execute("UPDATE ot_items SET tecnico=? WHERE id=?", (_texto(personas, otros[iid]), iid))


def asignaciones(item_ids):
    """Para el detalle de la OT: quién está en cada ítem."""
    conn = get_connection()
    try:
        return _personas_de_items(conn, item_ids)
    finally:
        conn.close()


def _quien():
    return session.get("nombre") or session.get("usuario") or ""


# ════════════════════════════════════════════════════════════════════════════
# LA LISTA
# ════════════════════════════════════════════════════════════════════════════

def listar():
    conn = get_connection()
    try:
        filas = conn.execute("SELECT * FROM taller_personal ORDER BY numero").fetchall()
        cuenta = {r["personal_id"]: (r["n"], r["hechos"] or 0) for r in conn.execute(
            """SELECT ip.personal_id, COUNT(*) AS n,
                      SUM(CASE WHEN i.estado = 'completado' THEN 1 ELSE 0 END) AS hechos
               FROM ot_item_personal ip
               JOIN ot_items i ON i.id = ip.item_id GROUP BY ip.personal_id""").fetchall()}
        out = []
        for r in filas:
            p = _persona(r)
            n, hechos = cuenta.get(p["id"], (0, 0))
            p["asignados"] = n          # en cualquier OT, terminados o no
            p["trabajos"] = hechos      # terminados, desde siempre
            out.append(p)
        return out
    finally:
        conn.close()


def _limpiar_datos(d, conn, pid=None):
    """Valida lo que viene del formulario. Devuelve (datos, error)."""
    datos = {}
    if "numero" in d:
        try:
            n = int(str(d.get("numero")).strip())
        except (TypeError, ValueError):
            return None, "El número tiene que ser un número"
        if n <= 0 or n > 9999:
            return None, "El número va de 1 a 9999"
        otro = conn.execute("SELECT id, nombre, activo FROM taller_personal WHERE numero=?", (n,)).fetchone()
        if otro and otro["id"] != pid:
            baja = " (está dado de baja, pero el número sigue siendo suyo)" if otro["activo"] in (0, "0") else ""
            return None, f"El N°{n} ya es de {otro['nombre']}{baja}"
        datos["numero"] = n
    if "nombre" in d:
        nombre = re.sub(r"\s+", " ", str(d.get("nombre") or "")).strip()
        if not nombre:
            return None, "Falta el nombre"
        datos["nombre"] = nombre[:120]
    if "puesto" in d:
        datos["puesto"] = re.sub(r"\s+", " ", str(d.get("puesto") or "")).strip()[:80]
    if "edad" in d:
        e = str(d.get("edad") if d.get("edad") is not None else "").strip()
        if e == "":
            datos["edad"] = None
        else:
            try:
                e = int(e)
            except ValueError:
                return None, "La edad tiene que ser un número"
            if not 14 <= e <= 99:
                return None, "Revisá la edad"
            datos["edad"] = e
    if "nacimiento" in d:
        nac = str(d.get("nacimiento") or "").strip()[:10]
        if nac and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", nac):
            return None, "La fecha de nacimiento no se entiende"
        datos["nacimiento"] = nac
    for k in ("ci", "telefono"):
        if k in d:
            datos[k] = re.sub(r"\s+", " ", str(d.get(k) or "")).strip()[:40]
    if "activo" in d:
        datos["activo"] = 1 if d.get("activo") in (1, True, "1", "true") else 0
    return datos, None


def crear(d):
    conn = get_connection()
    try:
        if not str(d.get("numero") or "").strip():
            r = conn.execute("SELECT MAX(numero) AS m FROM taller_personal").fetchone()
            d = dict(d, numero=(r["m"] or 0) + 1)
        datos, err = _limpiar_datos(dict({"nombre": ""}, **d), conn)
        if err:
            return None, err
        datos.setdefault("activo", 1)
        datos["creado_el"] = datos["actualizado_el"] = ahora_iso()
        cols = list(datos)
        cur = conn.execute(f"INSERT INTO taller_personal ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                           tuple(datos[c] for c in cols))
        conn.commit()
        pid = cur.lastrowid or conn.execute("SELECT id FROM taller_personal WHERE numero=?",
                                            (datos["numero"],)).fetchone()["id"]
        return _persona(conn.execute("SELECT * FROM taller_personal WHERE id=?", (pid,)).fetchone()), None
    finally:
        conn.close()


def actualizar(pid, d):
    conn = get_connection()
    try:
        antes = conn.execute("SELECT * FROM taller_personal WHERE id=?", (pid,)).fetchone()
        if not antes:
            return None, "No existe"
        datos, err = _limpiar_datos({k: v for k, v in d.items() if k in CAMPOS}, conn, pid)
        if err:
            return None, err
        if not datos:
            return _persona(antes), None
        datos["actualizado_el"] = ahora_iso()
        conn.execute(f"UPDATE taller_personal SET {', '.join(f'{k}=?' for k in datos)} WHERE id=?",
                     tuple(datos.values()) + (pid,))
        # Si cambió el número o el nombre, el texto de sus trabajos también
        if datos.get("numero", antes["numero"]) != antes["numero"] or datos.get("nombre", antes["nombre"]) != antes["nombre"]:
            items = [r["item_id"] for r in conn.execute(
                "SELECT item_id FROM ot_item_personal WHERE personal_id=?", (pid,)).fetchall()]
            _recalcular_texto(conn, items)
        conn.commit()
        return _persona(conn.execute("SELECT * FROM taller_personal WHERE id=?", (pid,)).fetchone()), None
    finally:
        conn.close()


def borrar(pid):
    """Solo si no tiene trabajos: si tiene, se lo da de baja (el número queda)."""
    conn = get_connection()
    try:
        p = conn.execute("SELECT * FROM taller_personal WHERE id=?", (pid,)).fetchone()
        if not p:
            return None, "No existe"
        n = conn.execute("""SELECT COUNT(*) AS n FROM ot_item_personal ip JOIN ot_items i ON i.id = ip.item_id
                            WHERE ip.personal_id=?""", (pid,)).fetchone()["n"]
        if n:
            return None, f"Tiene {n} trabajo{'s' if n != 1 else ''} en las OT: en vez de borrarlo, dalo de baja"
        conn.execute("DELETE FROM ot_item_personal WHERE personal_id=?", (pid,))
        conn.execute("DELETE FROM taller_personal WHERE id=?", (pid,))
        conn.commit()
        return dict(p), None
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# EN LA OT: quién hizo cada ítem
# ════════════════════════════════════════════════════════════════════════════

def _estado_item(conn, item_id):
    it = conn.execute("SELECT id, tecnico, tecnico_otro FROM ot_items WHERE id=?", (item_id,)).fetchone()
    if not it:
        return None
    return {"id": it["id"], "tecnico": it["tecnico"] or "", "tecnico_otro": it["tecnico_otro"] or "",
            "personal": _personas_de_items(conn, [item_id])[int(item_id)]}


def asignar(item_id, ids, otro=None, quien=""):
    """Deja el ítem con exactamente esas personas (y el texto libre, si viene)."""
    conn = get_connection()
    try:
        if not conn.execute("SELECT 1 FROM ot_items WHERE id=?", (item_id,)).fetchone():
            return None, "Ese ítem ya no existe"
        quiero = []
        for x in ids or []:
            try:
                quiero.append(int(x))
            except (TypeError, ValueError):
                pass
        quiero = list(dict.fromkeys(quiero))
        if quiero:
            marcas = ",".join("?" * len(quiero))
            existen = {r["id"] for r in conn.execute(
                f"SELECT id FROM taller_personal WHERE id IN ({marcas})", tuple(quiero)).fetchall()}
            quiero = [i for i in quiero if i in existen]
        tenia = {r["personal_id"] for r in conn.execute(
            "SELECT personal_id FROM ot_item_personal WHERE item_id=?", (item_id,)).fetchall()}
        for pid in tenia - set(quiero):
            conn.execute("DELETE FROM ot_item_personal WHERE item_id=? AND personal_id=?", (item_id, pid))
        ahora = ahora_iso()
        for pid in quiero:
            if pid not in tenia:
                conn.execute("""INSERT INTO ot_item_personal (item_id, personal_id, asignado_el, asignado_por)
                                VALUES (?,?,?,?) ON CONFLICT (item_id, personal_id) DO NOTHING""",
                             (item_id, pid, ahora, quien[:80]))
        if otro is not None:
            conn.execute("UPDATE ot_items SET tecnico_otro=? WHERE id=?",
                         (re.sub(r"\s+", " ", str(otro)).strip()[:120], item_id))
        _recalcular_texto(conn, [item_id])
        conn.commit()
        return _estado_item(conn, item_id), None
    finally:
        conn.close()


def asignar_texto(item_id, texto, quien=""):
    """Para quien todavía manda el técnico como texto (la pantalla vieja en
    caché): los números de la lista se vinculan, el resto queda como texto."""
    conn = get_connection()
    try:
        por_numero = {r["numero"]: r["id"] for r in conn.execute("SELECT id, numero FROM taller_personal").fetchall()}
    finally:
        conn.close()
    ids, resto = [], []
    for parte in re.split(r"\s*(?:,|;|/|\+|\by\b)\s*", str(texto or "")):
        parte = parte.strip()
        if not parte:
            continue
        m = re.match(r"(?:n[°º.]?\s*)?#?\s*(\d{1,4})(?:\s|$)", parte, re.I)
        if m and int(m.group(1)) in por_numero:
            ids.append(por_numero[int(m.group(1))])
        else:
            resto.append(parte)
    return asignar(item_id, ids, ", ".join(resto), quien)


def al_borrar_items(item_ids):
    if not item_ids:
        return
    conn = get_connection()
    try:
        marcas = ",".join("?" * len(item_ids))
        conn.execute(f"DELETE FROM ot_item_personal WHERE item_id IN ({marcas})", tuple(int(i) for i in item_ids))
        conn.commit()
    except Exception:
        _rollback(conn)
    finally:
        conn.close()


def al_borrar_ot(ot_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM ot_item_personal WHERE item_id IN (SELECT id FROM ot_items WHERE ot_id=?)", (ot_id,))
        conn.commit()
    except Exception:
        _rollback(conn)
    finally:
        conn.close()


def asignar_escrito(texto, pid, quien=""):
    """Todo lo que está escrito igual (ej. 'cesar') sin número pasa a ser de esa persona."""
    clave = _norm(texto)
    if not clave:
        return 0, "Falta el texto"
    conn = get_connection()
    try:
        p = conn.execute("SELECT * FROM taller_personal WHERE id=?", (pid,)).fetchone()
        if not p:
            return 0, "Esa persona no existe"
        items = [r["id"] for r in conn.execute(
            "SELECT id, tecnico_otro FROM ot_items WHERE COALESCE(tecnico_otro,'') != ''").fetchall()
            if _norm(r["tecnico_otro"]) == clave]
        ahora = ahora_iso()
        for iid in items:
            conn.execute("""INSERT INTO ot_item_personal (item_id, personal_id, asignado_el, asignado_por)
                            VALUES (?,?,?,?) ON CONFLICT (item_id, personal_id) DO NOTHING""",
                         (iid, pid, ahora, quien[:80]))
            conn.execute("UPDATE ot_items SET tecnico_otro='' WHERE id=?", (iid,))
        _recalcular_texto(conn, items)
        conn.commit()
        return len(items), None
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# QUIÉN TRABAJA (ranking, por coche, sin número)
# ════════════════════════════════════════════════════════════════════════════

FECHA_TRABAJO = """COALESCE(NULLIF(SUBSTR(COALESCE(i.fecha_completado,''),1,10),''),
                            NULLIF(SUBSTR(COALESCE(o.fecha_cierre,''),1,10),''),
                            SUBSTR(o.fecha_apertura,1,10))"""


def periodo(p, desde=None, hasta=None):
    """'7', '30', '90', 'anio', 'mes', 'todo' o desde/hasta → (desde, hasta, etiqueta)."""
    h = date.fromisoformat(_hoy_txt())
    if desde or hasta:
        return (desde or "2000-01-01"), (hasta or h.isoformat()), "rango"
    p = str(p or "30")
    if p == "todo":
        return "2000-01-01", h.isoformat(), "todo"
    if p == "anio":
        return f"{h.year}-01-01", h.isoformat(), "anio"
    if p == "mes":
        return h.replace(day=1).isoformat(), h.isoformat(), "mes"
    try:
        n = max(1, min(3650, int(p)))
    except ValueError:
        n = 30
    return (h - timedelta(days=n - 1)).isoformat(), h.isoformat(), str(n)


def _filas_trabajo(conn, vehiculo_id=None, personal_id=None):
    sql = f"""SELECT ip.personal_id, i.id AS item_id, i.estado, i.tipo, i.descripcion,
                     {FECHA_TRABAJO} AS fecha, o.id AS ot_id, o.estado AS ot_estado, o.vehiculo_id,
                     v.n_interno, v.patente
              FROM ot_item_personal ip
              JOIN ot_items i ON i.id = ip.item_id
              JOIN ordenes_trabajo o ON o.id = i.ot_id
              LEFT JOIN vehiculos v ON v.id = o.vehiculo_id
              WHERE 1=1"""
    args = []
    if vehiculo_id:
        sql += " AND o.vehiculo_id=?"
        args.append(int(vehiculo_id))
    if personal_id:
        sql += " AND ip.personal_id=?"
        args.append(int(personal_id))
    return [dict(r) for r in conn.execute(sql, tuple(args)).fetchall()]


def _coche(f):
    return str(f.get("n_interno") or f.get("patente") or f.get("vehiculo_id") or "")


def resumen(desde, hasta, vehiculo_id=None):
    conn = get_connection()
    try:
        personas = [_persona(r) for r in conn.execute("SELECT * FROM taller_personal ORDER BY numero").fetchall()]
        filas = _filas_trabajo(conn, vehiculo_id)

        por = {p["id"]: {"hechos": set(), "en_curso": set(), "coches": {}, "ots": set(),
                         "tipos": {}, "ultimo": "", "historico": 0} for p in personas}
        items_hechos, coches_hechos = set(), set()
        for f in filas:
            x = por.get(f["personal_id"])
            if x is None:
                continue
            fecha = f["fecha"] or ""
            if f["estado"] == "completado":
                x["historico"] += 1
                if fecha > x["ultimo"]:
                    x["ultimo"] = fecha
                if desde <= fecha <= hasta:
                    x["hechos"].add(f["item_id"])
                    x["ots"].add(f["ot_id"])
                    c = _coche(f)
                    x["coches"][c] = x["coches"].get(c, 0) + 1
                    x["tipos"][f["tipo"] or "otro"] = x["tipos"].get(f["tipo"] or "otro", 0) + 1
                    items_hechos.add(f["item_id"])
                    coches_hechos.add(f["vehiculo_id"])
            elif f["ot_estado"] != "cerrada":
                x["en_curso"].add(f["item_id"])

        ranking = []
        for p in personas:
            x = por[p["id"]]
            if not p["activo"] and not x["hechos"] and not x["en_curso"]:
                continue
            top = sorted(x["coches"].items(), key=lambda kv: (-kv[1], kv[0]))
            ranking.append({
                "id": p["id"], "numero": p["numero"], "nombre": p["nombre"], "puesto": p["puesto"] or "",
                "activo": p["activo"], "edad": p["edad_actual"],
                "trabajos": len(x["hechos"]), "en_curso": len(x["en_curso"]), "ots": len(x["ots"]),
                "coches": len(x["coches"]), "coches_top": [{"coche": c, "n": n} for c, n in top[:3]],
                "tipos": x["tipos"], "ultimo": x["ultimo"], "historico": x["historico"],
            })
        ranking.sort(key=lambda r: (-r["trabajos"], -r["en_curso"], r["numero"]))

        # Lo terminado en el período, con o sin número
        sql = f"""SELECT i.id, i.descripcion, i.tipo, i.tecnico_otro, {FECHA_TRABAJO} AS fecha,
                         o.id AS ot_id, o.vehiculo_id, v.n_interno, v.patente,
                         (SELECT COUNT(*) FROM ot_item_personal ip WHERE ip.item_id = i.id) AS con_numero
                  FROM ot_items i JOIN ordenes_trabajo o ON o.id = i.ot_id
                  LEFT JOIN vehiculos v ON v.id = o.vehiculo_id
                  WHERE i.estado = 'completado'"""
        args = []
        if vehiculo_id:
            sql += " AND o.vehiculo_id=?"
            args.append(int(vehiculo_id))
        terminados = [dict(r) for r in conn.execute(sql, tuple(args)).fetchall()]
        en_periodo = [t for t in terminados if desde <= (t["fecha"] or "") <= hasta]
        # Sin número = no tiene a nadie ni nada escrito. Lo escrito a mano (un
        # taller de afuera, un nombre viejo) se cuenta aparte.
        sin_numero = [t for t in en_periodo if not t["con_numero"] and not (t["tecnico_otro"] or "").strip()]
        a_mano = [t for t in en_periodo if not t["con_numero"] and (t["tecnico_otro"] or "").strip()]
        sin_numero.sort(key=lambda t: (t["fecha"] or "", t["id"]), reverse=True)

        # Nombres escritos a mano, sin número (de cualquier fecha): para pasarlos a alguien
        escritos = {}
        sql_e = """SELECT i.tecnico_otro FROM ot_items i JOIN ordenes_trabajo o ON o.id = i.ot_id
                   WHERE COALESCE(i.tecnico_otro,'') != ''
                     AND NOT EXISTS (SELECT 1 FROM ot_item_personal ip WHERE ip.item_id = i.id)"""
        args_e = []
        if vehiculo_id:
            sql_e += " AND o.vehiculo_id=?"
            args_e.append(int(vehiculo_id))
        for r in conn.execute(sql_e, tuple(args_e)).fetchall():
            k = _norm(r["tecnico_otro"])
            if k not in escritos:
                escritos[k] = {"texto": r["tecnico_otro"].strip(), "n": 0}
            escritos[k]["n"] += 1
        activos = [p for p in personas if p["activo"]]
        for k, e in escritos.items():
            e["sugerido"] = _sugerir(k, activos)
        escritos = sorted(escritos.values(), key=lambda e: (-e["n"], _norm(e["texto"])))

        coche_txt = ""
        if vehiculo_id:
            v = conn.execute("SELECT n_interno, patente FROM vehiculos WHERE id=?", (int(vehiculo_id),)).fetchone()
            coche_txt = str((v["n_interno"] or v["patente"]) if v else vehiculo_id)

        con = [r for r in ranking if r["activo"]]
        return {
            "desde": desde, "hasta": hasta, "hoy": _hoy_txt(),
            "vehiculo_id": int(vehiculo_id) if vehiculo_id else None, "coche": coche_txt,
            "ranking": ranking,
            "totales": {
                "trabajos": len(items_hechos),
                "terminados": len(en_periodo),
                "con_numero": len([t for t in en_periodo if t["con_numero"]]),
                "a_mano": len(a_mano),
                "sin_numero": len(sin_numero),
                "coches": len(coches_hechos),
                "personas": len([r for r in con if r["trabajos"]]),
                "activos": len(con),
                "sin_trabajos": len([r for r in con if not r["trabajos"]]),
                "en_curso": len({i for x in por.values() for i in x["en_curso"]}),
            },
            "sin_numero": [{
                "id": t["id"], "descripcion": t["descripcion"], "tipo": t["tipo"], "fecha": t["fecha"],
                "ot_id": t["ot_id"], "coche": _coche(t), "otro": t["tecnico_otro"] or "",
            } for t in sin_numero[:150]],
            "escritos": escritos[:60],
        }
    finally:
        conn.close()


def _sugerir(clave, personas):
    """Si un texto escrito a mano coincide con una sola persona, se sugiere (no se asigna solo)."""
    m = re.fullmatch(r"(?:n[°º.]?\s*)?#?\s*(\d{1,4})", clave)
    if m:
        for p in personas:
            if p["numero"] == int(m.group(1)):
                return p["id"]
        return None
    pal = [w for w in re.split(r"[^a-z0-9ñ]+", clave) if len(w) >= 3]
    if not pal:
        return None
    hits = [p for p in personas if all(w in _norm(p["nombre"]).split() for w in pal)]
    return hits[0]["id"] if len(hits) == 1 else None


def ficha(pid, desde, hasta, vehiculo_id=None):
    conn = get_connection()
    try:
        p = conn.execute("SELECT * FROM taller_personal WHERE id=?", (pid,)).fetchone()
        if not p:
            return None
        p = _persona(p)
        filas = _filas_trabajo(conn, vehiculo_id, pid)
        companeros = {}
        if filas:
            ids = [f["item_id"] for f in filas]
            for iid, gente in _personas_de_items(conn, ids).items():
                companeros[iid] = [{"numero": g["numero"], "nombre": g["nombre"]} for g in gente if g["id"] != pid]
        trabajos, coches, tipos, en_curso = [], {}, {}, []
        historico = 0
        for f in filas:
            t = {"item_id": f["item_id"], "ot_id": f["ot_id"], "descripcion": f["descripcion"], "tipo": f["tipo"],
                 "estado": f["estado"], "fecha": f["fecha"], "coche": _coche(f), "vehiculo_id": f["vehiculo_id"],
                 "con": companeros.get(f["item_id"], [])}
            if f["estado"] == "completado":
                historico += 1
                if desde <= (f["fecha"] or "") <= hasta:
                    trabajos.append(t)
                    coches[t["coche"]] = coches.get(t["coche"], 0) + 1
                    tipos[f["tipo"] or "otro"] = tipos.get(f["tipo"] or "otro", 0) + 1
            elif f["ot_estado"] != "cerrada":
                en_curso.append(t)
        trabajos.sort(key=lambda t: (t["fecha"] or "", t["item_id"]), reverse=True)
        en_curso.sort(key=lambda t: (t["fecha"] or "", t["item_id"]), reverse=True)
        return {
            "persona": p, "desde": desde, "hasta": hasta,
            "trabajos": trabajos, "en_curso": en_curso, "historico": historico,
            "coches": [{"coche": c, "n": n} for c, n in sorted(coches.items(), key=lambda kv: (-kv[1], kv[0]))],
            "tipos": tipos, "ots": len({t["ot_id"] for t in trabajos}),
        }
    finally:
        conn.close()


def tecnicos_para_gerencial(desde, hasta):
    """Página 'Personal técnico' del reporte gerencial: por persona (con su
    número) y, aparte, lo escrito a mano. Si un trabajo lo hicieron dos, el
    costo se reparte entre los dos."""
    conn = get_connection()
    try:
        items = [dict(r) for r in conn.execute("""
            SELECT i.id, i.tipo, COALESCE(i.costo,0) AS costo, i.tecnico_otro, i.tecnico
            FROM ot_items i JOIN ordenes_trabajo o ON o.id = i.ot_id
            WHERE o.fecha_apertura BETWEEN ? AND ?""", (desde, hasta)).fetchall()]
        gente = _personas_de_items(conn, [i["id"] for i in items])
        out = {}
        for it in items:
            quienes = [etiqueta(g) for g in gente.get(it["id"], [])]
            if not quienes:
                t = (it.get("tecnico_otro") or it.get("tecnico") or "").strip()
                if not t:
                    continue
                quienes = [t]
            parte = (it["costo"] or 0) / len(quienes)
            for q in quienes:
                x = out.setdefault(q, {"nombre": q, "total": 0, "preventivos": 0, "correctivos": 0, "costo": 0})
                x["total"] += 1
                x["preventivos"] += 1 if it["tipo"] == "preventivo" else 0
                x["correctivos"] += 1 if it["tipo"] == "correctivo" else 0
                x["costo"] += parte
        return sorted(out.values(), key=lambda x: (-x["total"], x["nombre"]))
    finally:
        conn.close()


# ════════════════════════════════════════════════════════════════════════════
# PDF: la lista con los números (para pegar en el taller) y el informe
# ════════════════════════════════════════════════════════════════════════════

def _fdm(f):
    f = str(f or "")
    return f"{f[8:10]}/{f[5:7]}/{f[0:4]}" if len(f) >= 10 else f


def pdf_lista(personas):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image
    from pdf_export import AZUL, ROJO, GRIS, GRIS_CLARO, _logo_path

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=14 * mm, bottomMargin=14 * mm,
                            leftMargin=16 * mm, rightMargin=16 * mm,
                            title="Personal de taller", author="La Santaniana")
    st = getSampleStyleSheet()
    normal = st["Normal"]
    tit = ParagraphStyle("PtTit", parent=st["Heading1"], fontSize=18, textColor=colors.HexColor(AZUL), spaceAfter=2)
    sub = ParagraphStyle("PtSub", parent=normal, fontSize=9, textColor=colors.HexColor(GRIS))
    num = ParagraphStyle("PtNum", parent=normal, fontName="Helvetica-Bold", fontSize=16, leading=19,
                         alignment=1, textColor=colors.HexColor(AZUL))
    nom = ParagraphStyle("PtNom", parent=normal, fontName="Helvetica-Bold", fontSize=11, leading=13)
    pue = ParagraphStyle("PtPue", parent=normal, fontSize=9, leading=11, textColor=colors.HexColor(GRIS))

    cab = [Paragraph("<b>LA SANTANIANA</b>", ParagraphStyle("PtE", parent=normal, fontSize=12, textColor=colors.HexColor(ROJO))),
           Paragraph("Personal de taller", tit),
           Paragraph(f"Cada uno con su número: en la OT se anota el número de quién hizo el trabajo. "
                     f"Lista al {_fdm(_hoy_txt())}.", sub)]
    story = []
    logo = _logo_path()
    if logo:
        try:
            head = Table([[cab, Image(logo, width=26 * mm, height=18 * mm)]], colWidths=[150 * mm, 28 * mm])
            head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, 0), "RIGHT")]))
            story.append(head)
        except Exception:
            story += cab
    else:
        story += cab
    story.append(Spacer(1, 5 * mm))

    activos = [p for p in personas if p["activo"]]
    data = [["N°", "Nombre y apellido", "Puesto"]]
    for p in activos:
        data.append([Paragraph(str(p["numero"]), num), Paragraph(p["nombre"], nom), Paragraph(p["puesto"] or "—", pue)])
    t = Table(data, colWidths=[20 * mm, 92 * mm, 66 * mm], repeatRows=1)
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(AZUL)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 1), (-1, -1), 4), ("BOTTOMPADDING", (0, 1), (-1, -1), 4),
        ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor("#D9E2EE")),
        ("BACKGROUND", (0, 1), (0, -1), colors.HexColor("#EAF2FB")),
    ]
    for k in range(2, len(data), 2):
        estilo.append(("BACKGROUND", (1, k), (-1, k), colors.HexColor(GRIS_CLARO)))
    t.setStyle(TableStyle(estilo))
    story.append(t)
    bajas = [p for p in personas if not p["activo"]]
    if bajas:
        story.append(Spacer(1, 4 * mm))
        story.append(Paragraph("Números que no se vuelven a usar (de baja): " +
                               ", ".join(f"N°{p['numero']} {p['nombre']}" for p in bajas), sub))
    doc.build(story)
    buf.seek(0)
    return buf


def pdf_informe(res):
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer
    from pdf_export import AZUL, ROJO, GRIS, GRIS_CLARO

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=14 * mm, bottomMargin=14 * mm,
                            leftMargin=14 * mm, rightMargin=14 * mm,
                            title="Trabajo del personal de taller", author="La Santaniana")
    st = getSampleStyleSheet()
    normal = st["Normal"]
    tit = ParagraphStyle("PiTit", parent=st["Heading1"], fontSize=17, textColor=colors.HexColor(AZUL), spaceAfter=2)
    sub = ParagraphStyle("PiSub", parent=normal, fontSize=9, textColor=colors.HexColor(GRIS))
    sm = ParagraphStyle("PiSm", parent=normal, fontSize=8.5, leading=10.5)
    smg = ParagraphStyle("PiSmg", parent=sm, textColor=colors.HexColor(GRIS))
    tot = res["totales"]
    alcance = f"Coche {res['coche']} · " if res.get("coche") else ""
    story = [
        Paragraph("<b>LA SANTANIANA</b>", ParagraphStyle("PiE", parent=normal, fontSize=12, textColor=colors.HexColor(ROJO))),
        Paragraph("Trabajo del personal de taller", tit),
        Paragraph(f"{alcance}Del {_fdm(res['desde'])} al {_fdm(res['hasta'])}. Sale de las OT: cuenta cada ítem "
                  f"terminado con el número de quién lo hizo (si lo hicieron dos, cuenta para los dos).", sub),
        Spacer(1, 4 * mm),
    ]
    cob = round(100 * tot["con_numero"] / tot["terminados"]) if tot["terminados"] else 0
    kp = Table([[
        Paragraph(f"<font size=16><b>{tot['trabajos']}</b></font><br/>trabajos con número", sm),
        Paragraph(f"<font size=16><b>{tot['personas']}</b></font> de {tot['activos']}<br/>personas con trabajos", sm),
        Paragraph(f"<font size=16><b>{tot['coches']}</b></font><br/>coches atendidos", sm),
        Paragraph(f"<font size=16><b>{cob} %</b></font><br/>de lo terminado tiene número"
                  + (f" ({tot['sin_numero']} sin nada"
                     + (f", {tot['a_mano']} escritos a mano" if tot["a_mano"] else "") + ")"
                     if tot["sin_numero"] or tot["a_mano"] else ""), sm),
    ]], colWidths=[45.5 * mm] * 4)
    kp.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(GRIS_CLARO)),
                            ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#D9E2EE")),
                            ("LINEAFTER", (0, 0), (-2, -1), 0.5, colors.HexColor("#D9E2EE")),
                            ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7)]))
    story += [kp, Spacer(1, 5 * mm)]

    data = [["N°", "Nombre", "Puesto", "Trabajos", "Prev.", "Corr.", "Coches", "En curso", "Último"]]
    for r in res["ranking"]:
        data.append([str(r["numero"]), Paragraph(r["nombre"] + ("" if r["activo"] else " (baja)"), sm),
                     Paragraph(r["puesto"] or "—", smg), str(r["trabajos"]),
                     str(r["tipos"].get("preventivo", 0)), str(r["tipos"].get("correctivo", 0)),
                     str(r["coches"]), str(r["en_curso"] or "—"), _fdm(r["ultimo"])[:5] if r["ultimo"] else "—"])
    t = Table(data, colWidths=[10 * mm, 50 * mm, 36 * mm, 16 * mm, 12 * mm, 12 * mm, 14 * mm, 15 * mm, 17 * mm],
              repeatRows=1)
    estilo = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(AZUL)),
              ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
              ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 8.5),
              ("ALIGN", (3, 0), (-1, -1), "CENTER"), ("ALIGN", (0, 0), (0, -1), "CENTER"),
              ("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold"), ("FONTNAME", (3, 1), (3, -1), "Helvetica-Bold"),
              ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
              ("LINEBELOW", (0, 1), (-1, -1), 0.4, colors.HexColor("#D9E2EE")),
              ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]
    for k, r in enumerate(res["ranking"], 1):
        if not r["trabajos"]:
            estilo.append(("TEXTCOLOR", (0, k), (-1, k), colors.HexColor(GRIS)))
    t.setStyle(TableStyle(estilo))
    story.append(t)
    sin = [r for r in res["ranking"] if r["activo"] and not r["trabajos"]]
    if sin:
        story += [Spacer(1, 3 * mm),
                  Paragraph(f"Sin trabajos registrados en el período: {len(sin)} "
                            f"({', '.join('N°' + str(r['numero']) for r in sin)}). Puede ser que no hayan trabajado en "
                            f"OT o que no se haya anotado su número.", sub)]
    doc.build(story)
    buf.seek(0)
    return buf


# ════════════════════════════════════════════════════════════════════════════
# API
# ════════════════════════════════════════════════════════════════════════════

def _puede_ver():
    return session.get("rol") in ("admin", "taller", "compras", "auditor")


def _puede_editar():
    return session.get("rol") in ("admin", "taller", "compras")


def _no():
    return jsonify({"ok": False, "msg": "No tenés permiso para esto"}), 403


def _auditar(accion, detalle=""):
    try:
        from database import registrar_auditoria
        registrar_auditoria(usuario=_quien() or "?", rol=session.get("rol") or "", accion=accion,
                            categoria="Personal de taller", detalle=str(detalle)[:200], referencia="")
    except Exception:
        pass


def _periodo_req():
    return periodo(request.args.get("p"), request.args.get("desde"), request.args.get("hasta"))


@bp_personal.route("/api/personal", methods=["GET"])
def api_lista():
    if not _puede_ver():
        return _no()
    return jsonify(listar())


@bp_personal.route("/api/personal", methods=["POST"])
def api_crear():
    if not _puede_editar():
        return _no()
    p, err = crear(request.get_json(silent=True) or {})
    if err:
        return jsonify({"ok": False, "msg": err}), 400
    _auditar("Agregó al personal", etiqueta(p))
    return jsonify({"ok": True, "persona": p})


@bp_personal.route("/api/personal/<int:pid>", methods=["PATCH"])
def api_actualizar(pid):
    if not _puede_editar():
        return _no()
    p, err = actualizar(pid, request.get_json(silent=True) or {})
    if err:
        return jsonify({"ok": False, "msg": err}), 400 if err != "No existe" else 404
    _auditar("Modificó datos del personal", etiqueta(p) + ("" if p["activo"] else " (de baja)"))
    return jsonify({"ok": True, "persona": p})


@bp_personal.route("/api/personal/<int:pid>", methods=["DELETE"])
def api_borrar(pid):
    if not _puede_editar():
        return _no()
    p, err = borrar(pid)
    if err:
        return jsonify({"ok": False, "msg": err}), 409 if err != "No existe" else 404
    _auditar("Borró del personal", etiqueta(p))
    return jsonify({"ok": True})


@bp_personal.route("/api/personal/resumen", methods=["GET"])
def api_resumen():
    if not _puede_ver():
        return _no()
    desde, hasta, _ = _periodo_req()
    return jsonify(resumen(desde, hasta, request.args.get("vehiculo_id") or None))


@bp_personal.route("/api/personal/<int:pid>/trabajos", methods=["GET"])
def api_ficha(pid):
    if not _puede_ver():
        return _no()
    desde, hasta, _ = _periodo_req()
    f = ficha(pid, desde, hasta, request.args.get("vehiculo_id") or None)
    if not f:
        return jsonify({"ok": False, "msg": "No existe"}), 404
    return jsonify(f)


@bp_personal.route("/api/ot_items/<int:item_id>/personal", methods=["PUT"])
def api_asignar(item_id):
    if not _puede_editar():
        return _no()
    d = request.get_json(silent=True) or {}
    est, err = asignar(item_id, d.get("ids") or [], d.get("otro"), _quien())
    if err:
        return jsonify({"ok": False, "msg": err}), 404
    return jsonify({"ok": True, "item": est})


@bp_personal.route("/api/personal/escritos", methods=["POST"])
def api_escritos():
    if not _puede_editar():
        return _no()
    d = request.get_json(silent=True) or {}
    try:
        pid = int(d.get("personal_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "msg": "Elegí a quién"}), 400
    n, err = asignar_escrito(d.get("texto"), pid, _quien())
    if err:
        return jsonify({"ok": False, "msg": err}), 400
    _auditar("Pasó trabajos escritos a mano a un número", f"'{d.get('texto')}' → id {pid} ({n})")
    return jsonify({"ok": True, "n": n})


@bp_personal.route("/api/personal/pdf", methods=["GET"])
def api_pdf_lista():
    if not _puede_ver():
        return _no()
    buf = pdf_lista(listar())
    return send_file(buf, mimetype="application/pdf", as_attachment=False,
                     download_name=f"personal-taller-{_hoy_txt()}.pdf")


@bp_personal.route("/api/personal/informe.pdf", methods=["GET"])
def api_pdf_informe():
    if not _puede_ver():
        return _no()
    desde, hasta, _ = _periodo_req()
    buf = pdf_informe(resumen(desde, hasta, request.args.get("vehiculo_id") or None))
    return send_file(buf, mimetype="application/pdf", as_attachment=False,
                     download_name=f"trabajo-personal-{desde}-{hasta}.pdf")
