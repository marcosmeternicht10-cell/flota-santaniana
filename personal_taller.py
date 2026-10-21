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

# Los que se suman después de la lista inicial. Cada tanda entra una sola vez
# al arrancar el sistema (si después se borra a alguien, no vuelve a aparecer;
# si ya lo habían cargado a mano con el mismo nombre, no se duplica).
AGREGADOS = [
    ("2026-10-15", [
        (23, "Asterio Torres", "Mecánica general", None),
        (24, "Rodrigo Flecha", "Mecánica general", None),
        (25, "Joel Morel", "Mecánica general", None),
    ]),
    ("2026-10-15b", [
        (26, "Victor Ramirez", "Electricista", None),
    ]),
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
        """CREATE TABLE IF NOT EXISTS taller_personal_cargas (
            tanda TEXT PRIMARY KEY,
            aplicada_el TEXT DEFAULT '')""",
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
    try:
        hechas = {r["tanda"] for r in conn.execute("SELECT tanda FROM taller_personal_cargas").fetchall()}
        for tanda, gente in AGREGADOS:
            if tanda in hechas:
                continue
            _sumar(conn, gente)
            conn.execute("INSERT INTO taller_personal_cargas (tanda, aplicada_el) VALUES (?,?) ON CONFLICT (tanda) DO NOTHING",
                         (tanda, ahora_iso()))
            conn.commit()
    except Exception:
        _rollback(conn)
    conn.close()


def _sumar(conn, gente):
    """Agrega gente a la lista: si ya está (mismo nombre) no la repite; si su
    número ya lo tiene otra persona, le toca el siguiente libre."""
    ahora = ahora_iso()
    filas = conn.execute("SELECT numero, nombre FROM taller_personal").fetchall()
    nombres = {_norm(r["nombre"]) for r in filas}
    usados = {r["numero"] for r in filas}
    for numero, nombre, puesto, edad in gente:
        if _norm(nombre) in nombres:
            continue
        if numero in usados:
            numero = max(usados | {0}) + 1
        conn.execute("""INSERT INTO taller_personal (numero, nombre, puesto, edad, activo, creado_el, actualizado_el)
                        VALUES (?,?,?,?,1,?,?) ON CONFLICT (numero) DO NOTHING""",
                     (numero, nombre, puesto, edad, ahora, ahora))
        usados.add(numero)
        nombres.add(_norm(nombre))


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
                            NULLIF(SUBSTR(COALESCE(i.fecha,''),1,10),''),
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
            WHERE COALESCE(NULLIF(SUBSTR(COALESCE(i.fecha,''),1,10),''), o.fecha_apertura) BETWEEN ? AND ?""",
            (desde, hasta)).fetchall()]
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
    # Más gente, renglones más bajos: la idea es que entre en una hoja
    pad = 4 if len(activos) <= 21 else 2.5 if len(activos) <= 27 else 1.5
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
        ("TOPPADDING", (0, 1), (-1, -1), pad), ("BOTTOMPADDING", (0, 1), (-1, -1), pad),
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
# FICHA DE UN TÉCNICO EN PDF (lo mismo que la ventana, para imprimir)
# ════════════════════════════════════════════════════════════════════════════

PERIODO_TXT = {"7": "últimos 7 días", "30": "últimos 30 días", "90": "últimos 90 días",
               "anio": "este año", "mes": "este mes", "todo": "desde siempre"}
TIPO_TXT = {"preventivo": "Preventivo", "correctivo": "Correctivo", "neumaticos": "Neumáticos",
            "control": "Control", "otro": "Otro"}


def pdf_ficha(f, etiqueta_periodo="", coche=""):
    """La ficha del técnico: sus números del período, los coches donde más
    trabajó, lo que tiene en curso y cada trabajo terminado con su OT."""
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    import os
    import trafico_pdf

    F = trafico_pdf._fuentes()
    W, H = A4
    M = 34
    aw = W - 2 * M
    NAVY, AZUL, ROJO = HexColor("#1D344E"), HexColor("#1E5A96"), HexColor("#DC2641")
    TINTA, GRIS, GRIS2 = HexColor("#16202C"), HexColor("#5B6B7F"), HexColor("#8796A8")
    LINEA, SUAVE, CEBRA, CELESTE = HexColor("#D5DCE5"), HexColor("#F4F6F9"), HexColor("#F7F9FB"), HexColor("#8CBDEB")
    AMBAR_F, AMBAR = HexColor("#FFF6E0"), HexColor("#B26A00")
    COL_TIPO = {"preventivo": HexColor("#2F7C46"), "correctivo": ROJO, "neumaticos": HexColor("#6B4FA0"),
                "control": AZUL, "otro": GRIS}
    try:
        logo = ImageReader(os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "logo.png"))
    except Exception:
        logo = None

    p = f["persona"]
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"N°{p['numero']} {p['nombre']} - trabajos")
    c.setAuthor("La Santaniana")

    def ancho(t, fu, sz):
        return pdfmetrics.stringWidth(str(t), F[fu], sz)

    def texto(x, y, t, fu, sz, color=TINTA, align="l"):
        c.setFillColor(color)
        c.setFont(F[fu], sz)
        t = str(t)
        if align == "r":
            c.drawRightString(x, H - y, t)
        elif align == "c":
            c.drawCentredString(x, H - y, t)
        else:
            c.drawString(x, H - y, t)

    def cortar(t, fu, sz, maxw):
        t = str(t or "")
        if ancho(t, fu, sz) <= maxw:
            return t
        while t and ancho(t + "…", fu, sz) > maxw:
            t = t[:-1]
        return t.rstrip() + "…"

    def partir(t, fu, sz, maxw):
        palabras, lineas, actual = str(t or "").split(), [], ""
        for w in palabras:
            prueba = (actual + " " + w).strip()
            if actual and ancho(prueba, fu, sz) > maxw:
                lineas.append(actual)
                actual = w
            else:
                actual = prueba
        if actual:
            lineas.append(actual)
        return lineas or [""]

    def rect(x, y, w, h, fill=None, stroke=None, r=0, lw=0.8):
        if fill is not None:
            c.setFillColor(fill)
        if stroke is not None:
            c.setStrokeColor(stroke)
            c.setLineWidth(lw)
        args = dict(stroke=1 if stroke is not None else 0, fill=1 if fill is not None else 0)
        if r:
            c.roundRect(x, H - y - h, w, h, r, **args)
        else:
            c.rect(x, H - y - h, w, h, **args)

    def linea(x1, y1, x2, y2, color=LINEA, lw=0.6):
        c.setStrokeColor(color)
        c.setLineWidth(lw)
        c.line(x1, H - y1, x2, H - y2)

    impresa = ahora_iso().replace("T", " ")[:16]
    impresa = f"{impresa[8:10]}/{impresa[5:7]}/{impresa[0:4]} {impresa[11:16]}"
    per_txt = PERIODO_TXT.get(etiqueta_periodo) or f"del {_fdm(f['desde'])} al {_fdm(f['hasta'])}"
    pagina = [1]

    def pie():
        linea(M, H - 30, W - M, H - 30, LINEA, 0.5)
        texto(M, H - 18, f"N°{p['numero']} {p['nombre']} · trabajos {per_txt}", "I5", 7.5, GRIS)
        texto(W - M, H - 18, f"Hoja {pagina[0]} · impresa el {impresa}", "I5", 7.5, GRIS, align="r")

    def encabezado(primera):
        y = M
        if logo:
            c.drawImage(logo, M, H - y - 34, 46, 34, mask="auto", preserveAspectRatio=True)
        texto(M + 56, y + 17, "FICHA DEL TÉCNICO", "D9", 21, NAVY)
        texto(M + 56, y + 32, "LA SANTANIANA S.A.  ·  PERSONAL DE TALLER", "I6", 8.5, GRIS)
        wbox = 120
        rect(W - M - wbox, y, wbox, 40, fill=NAVY, r=6)
        texto(W - M - wbox + 10, y + 15, "TÉCNICO", "I6", 7, CELESTE)
        texto(W - M - wbox + 10, y + 34, f"N° {p['numero']}", "D9", 20, white)
        rect(M, y + 47, aw * 0.4, 3, fill=ROJO)
        rect(M + aw * 0.4 + 3, y + 47, aw * 0.6 - 3, 3, fill=AZUL)
        y += 64
        if not primera:
            texto(M, y + 4, f"{p['nombre'].upper()} · SIGUE", "I7", 8, NAVY)
            return y + 14
        return y

    def nueva_pagina():
        pie()
        c.showPage()
        pagina[0] += 1
        return encabezado(False)

    # ── Primera hoja: quién es y sus números ──
    y = encabezado(True)
    texto(M, y + 18, p["nombre"].upper(), "D9", 22, TINTA)
    datos = [p.get("puesto") or "Sin puesto"]
    if p.get("edad_actual"):
        datos.append(f"{p['edad_actual']} años")
    if not p.get("activo", 1):
        datos.append("de baja")
    texto(M, y + 33, " · ".join(datos), "I5", 10, GRIS)
    alcance = f"Trabajos {per_txt}" + (f" · solo el coche {coche}" if coche else "")
    texto(W - M, y + 18, alcance.upper(), "I7", 7.5, AZUL, align="r")
    texto(W - M, y + 31, f"del {_fdm(f['desde'])} al {_fdm(f['hasta'])}" if etiqueta_periodo != "todo" else "",
          "I5", 8, GRIS, align="r")
    y += 46

    celdas = [("TRABAJOS", len(f["trabajos"]), "terminados"), ("OT", f["ots"], "distintas"),
              ("COCHES", len(f["coches"]), "atendidos"), ("EN CURSO", len(f["en_curso"]), "OT abiertas"),
              ("DESDE SIEMPRE", f["historico"], "terminados")]
    cw = aw / len(celdas)
    rect(M, y, aw, 56, fill=SUAVE, r=6)
    for k, (t, v, sub) in enumerate(celdas):
        x = M + k * cw
        if k:
            linea(x, y + 10, x, y + 46)
        texto(x + cw / 2, y + 15, t, "I6", 6.6, GRIS, align="c")
        texto(x + cw / 2, y + 38, str(v), "D9", 21, NAVY if k < 4 else GRIS, align="c")
        texto(x + cw / 2, y + 49, sub, "I4", 6.6, GRIS, align="c")
    y += 66

    if f["tipos"]:
        x = M
        texto(x, y + 9, "POR TIPO:", "I7", 7, GRIS)
        x += ancho("POR TIPO:", "I7", 7) + 8
        for k, n in sorted(f["tipos"].items(), key=lambda kv: -kv[1]):
            plural = {"preventivo": "preventivos", "correctivo": "correctivos", "neumaticos": "neumáticos",
                      "control": "controles", "otro": "otros"}
            lbl = f"{n} {(TIPO_TXT.get(k, k).lower() if n == 1 else plural.get(k, TIPO_TXT.get(k, k).lower()))}"
            w = ancho(lbl, "I6", 8) + 14
            rect(x, y, w, 13, fill=SUAVE, r=3)
            c.setFillColor(COL_TIPO.get(k, GRIS))
            c.circle(x + 6, H - (y + 6.5), 2.2, fill=1, stroke=0)
            texto(x + 11, y + 9.3, lbl, "I6", 8, TINTA)
            x += w + 6
        y += 22

    # ── Coches donde más trabajó (dos columnas de barras) ──
    if f["coches"]:
        texto(M, y + 10, "COCHES DONDE MÁS TRABAJÓ", "I7", 8, NAVY)
        y += 18
        top = f["coches"][:10]
        maxn = max(x["n"] for x in top) or 1
        colw = (aw - 20) / 2
        filas = (len(top) + 1) // 2
        for k, cc in enumerate(top):
            col, fila = (0, k) if k < filas else (1, k - filas)
            x = M + col * (colw + 20)
            yy = y + fila * 17
            texto(x, yy + 11, cortar(cc["coche"], "D8", 11, 50), "D8", 11, NAVY)
            bw = colw - 90
            rect(x + 56, yy + 4, bw, 8, fill=SUAVE, r=3)
            rect(x + 56, yy + 4, max(4, bw * cc["n"] / maxn), 8, fill=AZUL, r=3)
            texto(x + colw - 4, yy + 11, str(cc["n"]), "D8", 11, TINTA, align="r")
        y += filas * 17 + 10

    # ── Tabla de trabajos ──
    COLS = [("FECHA", 50), ("COCHE", 50), ("TIPO", 66), ("TRABAJO", 0), ("OT", 44)]
    fijo = sum(w for _, w in COLS)
    COLS[3] = ("TRABAJO", aw - fijo)
    LIM = H - 70

    def cabecera_tabla(y, titulo, sub=""):
        texto(M, y + 10, titulo, "I7", 8, NAVY)
        if sub:
            texto(M + ancho(titulo, "I7", 8) + 6, y + 10, sub, "I5", 7.5, GRIS)
        y += 16
        rect(M, y, aw, 18, fill=NAVY, r=3)
        x = M
        for t, w in COLS:
            texto(x + 6 if t != "OT" else x + w - 6, y + 12, t, "I6", 6.6, white, align="l" if t != "OT" else "r")
            x += w
        return y + 18

    def tabla(y, lista, titulo, sub="", fondo=None):
        if y + 60 > LIM:
            y = nueva_pagina()
        y = cabecera_tabla(y, titulo, sub)
        for k, t in enumerate(lista):
            desc = t.get("descripcion") or ""
            con = t.get("con") or []
            lineas = partir(desc, "I5", 8.6, COLS[3][1] - 12)
            extra = ("con " + ", ".join(f"N°{x['numero']} {x['nombre'].split(' ')[0]}" for x in con)) if con else ""
            alto = 8 + len(lineas) * 11 + (10 if extra else 0) + 2
            if y + alto > LIM:
                y = nueva_pagina()
                y = cabecera_tabla(y, titulo, "(sigue)")
            if fondo:
                rect(M, y, aw, alto, fill=fondo)
            elif k % 2:
                rect(M, y, aw, alto, fill=CEBRA)
            x = M
            fe = str(t.get("fecha") or "")
            texto(x + 6, y + 13, f"{fe[8:10]}/{fe[5:7]}/{fe[2:4]}" if len(fe) >= 10 else "—", "I5", 8.4, TINTA)
            x += COLS[0][1]
            texto(x + 6, y + 13.5, cortar(t.get("coche") or "—", "D8", 11, COLS[1][1] - 10), "D8", 11, NAVY)
            x += COLS[1][1]
            tipo = t.get("tipo") or "otro"
            c.setFillColor(COL_TIPO.get(tipo, GRIS))
            c.circle(x + 9, H - (y + 10.5), 2.4, fill=1, stroke=0)
            texto(x + 15, y + 13, TIPO_TXT.get(tipo, tipo.capitalize()), "I5", 8, GRIS)
            x += COLS[2][1]
            for i, ln in enumerate(lineas):
                texto(x + 6, y + 13 + i * 11, ln, "I5", 8.6, TINTA)
            if extra:
                texto(x + 6, y + 13 + len(lineas) * 11, cortar(extra, "I4", 7.4, COLS[3][1] - 12), "I4", 7.4, GRIS)
            x += COLS[3][1]
            texto(x + COLS[4][1] - 6, y + 13, f"#{t.get('ot_id')}", "I6", 8.4, AZUL, align="r")
            linea(M, y + alto, M + aw, y + alto)
            y += alto
        return y + 12

    if f["en_curso"]:
        y = tabla(y, f["en_curso"], "EN CURSO", "OT abiertas, todavía sin terminar", fondo=AMBAR_F)
    if f["trabajos"]:
        y = tabla(y, f["trabajos"], "TRABAJOS TERMINADOS", per_txt)
    else:
        if y + 40 > LIM:
            y = nueva_pagina()
        rect(M, y, aw, 34, fill=SUAVE, r=6)
        texto(W / 2, y + 21, f"Sin trabajos terminados {per_txt}: puede que no haya trabajado en OT "
                             f"o que no se haya anotado su número.", "I5", 8.5, GRIS, align="c")
        y += 46

    pie()
    c.showPage()
    c.save()
    buf.seek(0)
    return buf


# ════════════════════════════════════════════════════════════════════════════
# HOJAS POR TÉCNICO: cada uno con su hoja de la OT (sin costos)
# ════════════════════════════════════════════════════════════════════════════
# Como la planilla de papel del taller: fecha, OT, coche, km, chofer, el
# detalle de lo que tiene que hacer ESE técnico, materiales, horas y firmas.
# Una hoja por técnico: el pintor no recibe lo del gomero. Sin montos.

def _fecha_item(ot, it):
    return str(it.get("fecha") or ot.get("fecha_apertura") or "")[:10]


def items_de_hojas(ot, cuales="pendientes"):
    """Qué trabajos van en las hojas. Un coche tiene una sola OT abierta que
    junta trabajos de varios días: por defecto sale lo pendiente; también un
    día puntual ('dia:2026-10-21') o todo."""
    its = ot.get("items") or []
    if cuales == "todo":
        return its
    if str(cuales).startswith("dia:"):
        d = str(cuales)[4:14]
        return [i for i in its if _fecha_item(ot, i) == d]
    return [i for i in its if i.get("estado") != "completado"]


def opciones_hojas(ot):
    its = ot.get("items") or []
    dias = {}
    for i in its:
        dias.setdefault(_fecha_item(ot, i), []).append(i)
    ops = [{"clave": "pendientes", "txt": "Lo pendiente", "n": len([i for i in its if i.get("estado") != "completado"])}]
    if len(dias) > 1:
        for d in sorted(dias, reverse=True):
            ops.append({"clave": f"dia:{d}", "txt": d, "n": len(dias[d]), "dia": d})
    ops.append({"clave": "todo", "txt": "Todo", "n": len(its)})
    return ops


def hojas_de_ot(ot, cuales="pendientes"):
    """Agrupa los ítems de la OT por técnico. Devuelve la lista de hojas, en
    orden de número (los escritos sin número al final), y los ítems que no
    tienen a nadie."""
    grupos, sin_nadie = {}, []
    for it in items_de_hojas(ot, cuales):
        gente = it.get("personal") or []
        otros = [t for t in re.split(r"\s*,\s*", it.get("tecnico_otro") or "") if t.strip()]
        if not gente and not otros:
            sin_nadie.append(it)
            continue
        for p in gente:
            g = grupos.setdefault(f"p{p['id']}", {"clave": f"p{p['id']}", "numero": p["numero"],
                                                   "nombre": p["nombre"], "puesto": p.get("puesto") or "",
                                                   "items": []})
            g["items"].append({**it, "con": [etiqueta(x) for x in gente if x["id"] != p["id"]] + otros})
        for t in otros:
            g = grupos.setdefault("o:" + _norm(t), {"clave": "o:" + _norm(t), "numero": None, "nombre": t.strip(),
                                                    "puesto": "", "items": []})
            g["items"].append({**it, "con": [etiqueta(x) for x in gente] + [o for o in otros if o != t]})
    hojas = sorted(grupos.values(), key=lambda g: (g["numero"] is None, g["numero"] or 0, _norm(g["nombre"])))
    return hojas, sin_nadie


def pdf_hojas(ot, hojas):
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.colors import HexColor, white
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    import os
    import trafico_pdf

    F = trafico_pdf._fuentes()
    W, H = A4
    M = 34
    NAVY, AZUL, ROJO = HexColor("#1D344E"), HexColor("#1E5A96"), HexColor("#DC2641")
    TINTA, GRIS, LINEA, SUAVE = HexColor("#16202C"), HexColor("#5B6B7F"), HexColor("#9AA6B4"), HexColor("#F4F6F9")
    PUNTEO = HexColor("#C9D1DB")
    try:
        logo = ImageReader(os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "logo.png"))
    except Exception:
        logo = None

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"OT {ot['id']} - hojas por técnico")
    c.setAuthor("La Santaniana")

    def ancho(t, f, s):
        return pdfmetrics.stringWidth(t, F[f], s)

    def texto(x, y, t, f, s, color=TINTA, align="l"):
        c.setFillColor(color)
        c.setFont(F[f], s)
        if align == "r":
            c.drawRightString(x, H - y, t)
        elif align == "c":
            c.drawCentredString(x, H - y, t)
        else:
            c.drawString(x, H - y, t)

    def cortar(t, f, s, maxw):
        t = str(t or "")
        if ancho(t, f, s) <= maxw:
            return t
        while t and ancho(t + "…", f, s) > maxw:
            t = t[:-1]
        return t.rstrip() + "…"

    def partir(t, f, s, maxw):
        palabras, lineas, actual = str(t or "").split(), [], ""
        for p in palabras:
            prueba = (actual + " " + p).strip()
            if actual and ancho(prueba, f, s) > maxw:
                lineas.append(actual)
                actual = p
            else:
                actual = prueba
        if actual:
            lineas.append(actual)
        return lineas or [""]

    def caja(x, y, w, h, etiqueta_txt, valor="", grande=False):
        c.setStrokeColor(NAVY)
        c.setLineWidth(1)
        c.rect(x, H - y - h, w, h, stroke=1, fill=0)
        texto(x + 8, y + h / 2 + 4, etiqueta_txt, "I7", 10.5, NAVY)
        wl = ancho(etiqueta_txt, "I7", 10.5)
        if valor:
            v = cortar(valor, "D8", 15 if grande else 13, w - wl - 22)
            texto(x + 14 + wl, y + h / 2 + 5, v, "D8", 15 if grande else 13, TINTA)

    def renglones(x, y, w, n, alto):
        c.setStrokeColor(PUNTEO)
        c.setLineWidth(0.6)
        for k in range(1, n + 1):
            yy = y + k * alto
            c.line(x + 8, H - yy, x + w - 8, H - yy)

    fdm = lambda f: f"{str(f)[8:10]}/{str(f)[5:7]}/{str(f)[2:4]}" if f and len(str(f)) >= 10 else ""
    km = ot.get("km")
    km_txt = f"{int(km):,}".replace(",", ".") if km else ""
    coche = str(ot.get("n_interno") or ot.get("patente") or "")
    impresa = ahora_iso().replace("T", " ")[:16]
    impresa = f"{impresa[8:10]}/{impresa[5:7]}/{impresa[0:4]} {impresa[11:16]}"

    # Cada hoja puede necesitar más de una página si tiene muchos trabajos
    POR_HOJA = 16
    paginas = []
    for g in hojas:
        items = g["items"]
        trozos = [items[i:i + POR_HOJA] for i in range(0, len(items), POR_HOJA)] or [[]]
        for k, tz in enumerate(trozos):
            paginas.append((g, tz, k, len(trozos)))

    for n_pag, (g, items, k, total_k) in enumerate(paginas, 1):
        quien = (f"N°{g['numero']} " if g["numero"] is not None else "") + g["nombre"]
        # ── Encabezado ──
        y = M
        if logo:
            c.drawImage(logo, M, H - y - 34, 46, 34, mask="auto", preserveAspectRatio=True)
        texto(M + 56, y + 17, "ORDEN DE TRABAJO", "D9", 21, NAVY)
        texto(M + 56, y + 32, "LA SANTANIANA S.A.  ·  HOJA DEL TÉCNICO", "I6", 8.5, GRIS)
        # El número del técnico, grande, para repartir las hojas
        wbox = 132
        c.setFillColor(NAVY)
        c.roundRect(W - M - wbox, H - y - 40, wbox, 40, 6, fill=1, stroke=0)
        if g["numero"] is not None:
            texto(W - M - wbox + 10, y + 15, "TÉCNICO", "I6", 7, HexColor("#8CBDEB"))
            texto(W - M - wbox + 10, y + 33, f"N° {g['numero']}", "D9", 19, white)
        else:
            texto(W - M - wbox + 10, y + 15, "SIN NÚMERO", "I6", 7, HexColor("#8CBDEB"))
            texto(W - M - wbox + 10, y + 32, cortar(g["nombre"].upper(), "D8", 12, wbox - 20), "D8", 12, white)
        c.setFillColor(ROJO)
        c.rect(M, H - y - 50, (W - 2 * M) * 0.4, 3, fill=1, stroke=0)
        c.setFillColor(AZUL)
        c.rect(M + (W - 2 * M) * 0.4 + 3, H - y - 50, (W - 2 * M) * 0.6 - 3, 3, fill=1, stroke=0)
        y += 64

        # ── Datos de la OT ──
        aw = W - 2 * M
        # Los días de los trabajos de esta hoja (una OT junta varios días)
        dias_h = sorted({_fecha_item(ot, it) for it in g["items"] if _fecha_item(ot, it)})
        fecha_txt = fdm(dias_h[0]) if len(dias_h) == 1 else \
            (f"{fdm(dias_h[0])[:5]} al {fdm(dias_h[-1])}" if dias_h else fdm(ot.get("fecha_apertura")))
        caja(M, y, aw * 0.55 - 6, 34, "Fecha:", fecha_txt)
        caja(M + aw * 0.55, y, aw * 0.45, 34, "OT Nro.:", str(ot["id"]), grande=True)
        y += 44
        caja(M, y, aw * 0.30 - 6, 34, "Coche:", coche, grande=True)
        caja(M + aw * 0.30, y, aw * 0.30 - 6, 34, "Km:", km_txt)
        caja(M + aw * 0.60, y, aw * 0.40, 34, "Chofer:", str(ot.get("conductor") or ""))
        y += 46

        # ── Detalle: lo que hace este técnico ──
        alto = 25
        filas = []
        for it in items:
            lineas = partir(it.get("descripcion") or "", "I5", 11.5, aw - 40)
            extra = []
            if it.get("con"):
                extra.append("con " + ", ".join(it["con"]))
            if it.get("estado") == "completado":
                extra.append("ya completado")
            filas.append((lineas, " · ".join(extra)))
        usados = sum(len(l) for l, _ in filas)
        mats = []
        for it in g["items"]:
            m = (it.get("material_pedido") or "").strip()
            if m and m not in mats:
                mats.append(m)
        n_mat = max(len(mats) + 1, 3)
        h_mat = 22 + n_mat * 22 + 6
        if k == total_k - 1:
            # Los renglones del detalle llenan la hoja (para anotar a mano)
            resto = h_mat + 12 + 46 + 50 + 56
            libre = H - y - resto - 50 - 28
            n_lin = max(usados + 3, int(libre // alto))
        else:
            n_lin = usados
        h_det = 22 + n_lin * alto + 6
        c.setStrokeColor(NAVY)
        c.setLineWidth(1)
        c.rect(M, H - y - h_det, aw, h_det, stroke=1, fill=0)
        c.setFillColor(SUAVE)
        c.rect(M + 0.5, H - y - 22, 86, 21.5, stroke=0, fill=1)
        texto(M + 8, y + 15, "Detalle:", "I7", 10.5, NAVY)
        if total_k > 1:
            texto(M + aw - 8, y + 15, f"parte {k + 1} de {total_k}", "I5", 8, GRIS, align="r")
        renglones(M, y + 22, aw, n_lin, alto)
        yy = y + 22
        for lineas, extra in filas:
            for i, ln in enumerate(lineas):
                if i == 0:
                    c.setFillColor(NAVY)
                    c.circle(M + 15, H - (yy + alto - 9), 2.2, fill=1, stroke=0)
                texto(M + 26, yy + alto - 6, ln, "I5", 11.5, TINTA)
                if i == len(lineas) - 1 and extra:
                    texto(M + aw - 10, yy + alto - 6, cortar(extra, "I5", 8, 200), "I5", 8, GRIS, align="r")
                yy += alto
        y += h_det + 10

        if k == total_k - 1:
            # ── Materiales (lo que se anotó en la OT para sus trabajos) ──
            c.setStrokeColor(NAVY)
            c.rect(M, H - y - h_mat, aw, h_mat, stroke=1, fill=0)
            c.setFillColor(SUAVE)
            c.rect(M + 0.5, H - y - 22, 100, 21.5, stroke=0, fill=1)
            texto(M + 8, y + 15, "Materiales:", "I7", 10.5, NAVY)
            renglones(M, y + 22, aw, n_mat, 22)
            for i, m in enumerate(mats):
                c.setFillColor(NAVY)
                c.circle(M + 15, H - (y + 22 + i * 22 + 13), 2, fill=1, stroke=0)
                texto(M + 26, y + 22 + i * 22 + 17, cortar(m, "I5", 11, aw - 40), "I5", 11, TINTA)
            y += h_mat + 12

            # ── Horas, técnico, firmas ──
            tercio = (aw - 12) / 3
            caja(M, y, tercio, 36, "Hora Inicio:")
            caja(M + tercio + 6, y, tercio, 36, "Hora Entrega:")
            caja(M + 2 * (tercio + 6), y, tercio, 36, "Total Horas:")
            y += 46
            caja(M, y, aw * 0.6 - 6, 40, "Técnico Asignado:", quien)
            caja(M + aw * 0.6, y, aw * 0.4, 40, "Firmas:")
            y += 50
            caja(M, y, aw, 46, "Verificación Jefe Técnico:")
            y += 56
        else:
            texto(W / 2, y + 10, "Sigue en la página siguiente", "I5", 9, GRIS, align="c")

        # ── Pie ──
        c.setStrokeColor(LINEA)
        c.setLineWidth(0.5)
        c.line(M, 30, W - M, 30)
        texto(M, H - 18, f"OT #{ot['id']} · Coche {coche} · {quien}", "I5", 7.5, GRIS)
        texto(W - M, H - 18, f"Hoja {n_pag} de {len(paginas)} · impresa el {impresa}", "I5", 7.5, GRIS, align="r")
        c.showPage()

    c.save()
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


@bp_personal.route("/api/personal/<int:pid>/ficha.pdf", methods=["GET"])
def api_ficha_pdf(pid):
    if not _puede_ver():
        return _no()
    desde, hasta, etq = _periodo_req()
    vid = request.args.get("vehiculo_id") or None
    f = ficha(pid, desde, hasta, vid)
    if not f:
        return jsonify({"ok": False, "msg": "No existe"}), 404
    coche = ""
    if vid:
        conn = get_connection()
        try:
            v = conn.execute("SELECT n_interno, patente FROM vehiculos WHERE id=?", (int(vid),)).fetchone()
            coche = str((v["n_interno"] or v["patente"]) if v else "")
        finally:
            conn.close()
    p = f["persona"]
    nombre = re.sub(r"[^A-Za-z0-9]+", "-", unicodedata.normalize("NFD", p["nombre"]).encode("ascii", "ignore").decode()).strip("-").lower()
    return send_file(pdf_ficha(f, etq, coche), mimetype="application/pdf", as_attachment=False,
                     download_name=f"tecnico-{p['numero']}-{nombre}.pdf")


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


@bp_personal.route("/api/ots/<int:ot_id>/hojas", methods=["GET"])
def api_hojas_info(ot_id):
    """Qué hojas salen de esta OT (para elegir cuáles imprimir)."""
    if not _puede_ver():
        return _no()
    import database as db
    ot = db.obtener_ot(ot_id)
    if not ot:
        return jsonify({"ok": False, "msg": "La OT no existe"}), 404
    cuales = request.args.get("cuales") or ""
    hojas, sin = hojas_de_ot(ot, cuales or "pendientes")
    if not cuales and not hojas:
        # Ya está todo hecho: se ofrece todo (por si es para archivar)
        cuales = "todo"
        hojas, sin = hojas_de_ot(ot, cuales)
    return jsonify({"ok": True, "cuales": cuales or "pendientes", "opciones": opciones_hojas(ot),
                    "hojas": [{"clave": g["clave"], "numero": g["numero"], "nombre": g["nombre"],
                               "puesto": g["puesto"], "trabajos": len(g["items"])} for g in hojas],
                    "sin_tecnico": [it.get("descripcion") for it in sin]})


@bp_personal.route("/api/ots/<int:ot_id>/hojas.pdf", methods=["GET"])
def api_hojas_pdf(ot_id):
    """Una hoja por técnico con sus trabajos de la OT (sin costos)."""
    if not _puede_ver():
        return _no()
    import database as db
    ot = db.obtener_ot(ot_id)
    if not ot:
        return jsonify({"ok": False, "msg": "La OT no existe"}), 404
    cuales = request.args.get("cuales") or "pendientes"
    hojas, _ = hojas_de_ot(ot, cuales)
    pedidas = [q for q in (request.args.get("quienes") or "").split("|") if q]
    if pedidas:
        hojas = [g for g in hojas if g["clave"] in pedidas]
    if not hojas:
        msg = "Ningún trabajo de esta OT tiene técnico asignado" if cuales == "todo" else \
            "En lo elegido no hay trabajos con técnico asignado"
        return jsonify({"ok": False, "msg": msg}), 400
    buf = pdf_hojas(ot, hojas)
    return send_file(buf, mimetype="application/pdf", as_attachment=False,
                     download_name=f"OT_{ot_id}_hojas_tecnicos.pdf")
