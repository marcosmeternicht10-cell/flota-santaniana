"""
cargas_datos.py — Cargas de datos que se aplican una sola vez (La Santaniana)

Cuando llega un documento con datos para pasar al sistema (la póliza del
seguro, por ejemplo), se anota acá y el sistema lo aplica al arrancar, UNA
sola vez. Cada carga tiene una clave; la tabla `cargas_datos` guarda cuáles ya
se aplicaron y qué hizo cada una, así no se repite aunque el sistema reinicie
ni se pisa si dos procesos arrancan a la vez.

Cargas:

  poliza_rc_2026   Póliza de responsabilidad civil N° 1.0501.262140.0
                   (El Comercio Paraguayo), vigencia 05/11/2026 al 05/11/2027.
                   51 certificados, uno por coche. A cada coche le renueva su
                   seguro de responsabilidad civil en Documentos: el anterior
                   pasa al historial y queda el nuevo como vigente.

Enganche en app.py:
    from cargas_datos import init_cargas_datos
    init_cargas_datos()
"""

import json
import re

from db_compat import get_connection
from hora_local import ahora_iso

# ─── Póliza de responsabilidad civil 2026-2027 ──────────────────────────────
POLIZA_RC_2026 = {
    "clave": "poliza_rc_2026",
    "poliza": "1.0501.262140.0",
    "aseguradora": "El Comercio Paraguayo",
    "desde": "2026-11-05",
    "hasta": "2027-11-05",
    "nombre": "Responsabilidad Civil (RC)",
    "cobertura": ("Responsabilidad civil (cobertura básica 3): hasta Gs. 80.000.000 por una persona, "
                  "Gs. 160.000.000 por dos o más y Gs. 70.000.000 por daños a cosas de terceros. Sin franquicia."),
    # (certificado, coche, chapa, chasis), tal como figuran en la póliza
    "certificados": [
        (1, "21160", "BEZ 381", "9BSK6X200B3663756"), (2, "21170", "BEZ 429", "9BSK6X200B3663765"),
        (3, "21180", "BEZ 394", "9BSK6X200B3663768"), (4, "21200", "BHD 665", "9BSK6X200C3686985"),
        (5, "21260", "BGZ 759", "9BSK6X200C3688141"), (6, "21280", "KAJ 704", "9BSK6X200C3686988"),
        (7, "21300", "BHY 132", "9BSK6X200C3804640"), (8, "21330", "KAN 774", "9BSK6X200D3806407"),
        (9, "21350", "KAN 750", "9BSK6X200D3806391"), (10, "21600", "BVN 270", "9BM634061GB016368"),
        (11, "21610", "BVL 131", "9BM634061GB016404"), (12, "21640", "BVN 811", "9BM634061GB016338"),
        (13, "21650", "BVL 895", "9BM634061GB016475"), (14, "21700", "BZL 158", "9BSK6X200H3891405"),
        (15, "21800", "BZJ 936", "9BVT2T420HE386688"), (16, "21810", "BZJ 935", "9BVT2T422HE386689"),
        (17, "21820", "BZJ 949", "9BVT2T429HE386690"), (18, "21830", "HBC 062", "9BSK8X200G3883685"),
        (19, "21840", "HBC 060", "9BSK8X200G3882999"), (20, "21850", "HBC 058", "9BSK8X200H3896589"),
        (21, "21220", "KAJ 707", "9BSK6X200C3687007"), (22, "22330", "AAEY 641", "9BSK8X200M3973675"),
        (23, "22310", "AAEY 580", "9BSK8X200M3974438"), (24, "24000", "AAOI 991", "9BSK8X200R4044580"),
        (25, "24100", "AAOI 981", "9BSK8X200R4044114"), (26, "24200", "AAOI 999", "9BSK8X200R4044107"),
        (27, "21680", "BYH 570", "9BVT2T425FE384979"), (28, "2613", "BBF 168", "9BSK4X2B083607724"),
        (29, "21027", "BFA 266", "9BSK4X200B3662828"), (30, "21030", "GAD 110", "9BSK4X200A3672539"),
        (31, "21034", "BKP 690", "9BSK4X200D3821820"), (32, "21038", "BKO 660", "9BSK4X200D3821833"),
        (33, "21660", "BVL 138", "9BM634061GB015920"), (34, "21760", "BYR 992", "9BSK4X200H3889959"),
        (35, "21860", "HDE 728", "9BSK4X200H3890273"), (36, "21865", "HFB 251", "9BSK4X200G3876139"),
        (37, "21870", "HFB 255", "9BSK4X200G3876144"), (38, "21875", "HFB 254", "9BSK4X200G3884288"),
        (39, "21880", "HFB 249", "9BSK4X200G3884290"), (40, "26000", "AAXU 515", "9BSK8X200T4104877"),
        (41, "26100", "AAXU 509", "9BSK8X200T4103148"), (42, "26200", "AAXU 512", "9BSK8X200T4103157"),
        (43, "26300", "AAXU 520", "9BSK8X200T4100072"), (44, "26400", "AAXU 506", "9BSK8X200T4100051"),
        (45, "21016", "BDG 576", "9BSK4X200A3648088"), (46, "26500", "ABAD 455", "9BSK8X200T4110283"),
        (47, "26600", "ABAD 457", "9BSK8X200T4108843"), (48, "26700", "ABAD 459", "9BSK8X200T4106731"),
        (49, "26800", "ABAD 458", "9BSK8X200T4106695"), (50, "26900", "ABAD 340", "9BSK8X200T4107093"),
        (51, "21250", "KAJ 711", "9BSK6X200C3686990"),
    ],
}

# Un documento de seguro es el de responsabilidad civil si su nombre lo dice
_ES_RC = re.compile(r"responsab|civil|\brc\b|r\.\s*c\.", re.I)


def _limpio(s):
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def _buscar_coche(vehiculos, coche, chapa, chasis):
    """El coche del sistema que corresponde al certificado. Se busca por número
    de coche, chapa y chasis, y gana el que coincide en más datos: así un error
    de tipeo en uno de los tres no deja al coche afuera ni lo confunde con otro."""
    votos = {}
    for campo, valor in (("n_interno", coche), ("patente", chapa), ("chasis", chasis)):
        v = _limpio(valor)
        if not v:
            continue
        for x in vehiculos:
            if _limpio(x[campo]) == v:
                votos[x["id"]] = votos.get(x["id"], 0) + 1
    if not votos:
        return None, 0
    vid = max(votos, key=votos.get)
    if sum(1 for n in votos.values() if n == votos[vid]) > 1:
        return None, 0                       # empate entre dos coches: no se adivina
    return vid, votos[vid]


def _aplicar_poliza_rc(conn, p):
    """Devuelve el resumen de lo que hizo."""
    vehiculos = [dict(r) for r in conn.execute("SELECT id, n_interno, patente, chasis FROM vehiculos").fetchall()]
    res = {"renovados": 0, "nuevos": 0, "ya_estaban": 0, "sin_coche": [], "datos_distintos": []}
    for cert, coche, chapa, chasis in p["certificados"]:
        vid, coincidencias = _buscar_coche(vehiculos, coche, chapa, chasis)
        if not vid:
            res["sin_coche"].append(f"certificado {cert}: coche {coche} ({chapa})")
            continue
        if coincidencias < 3:
            v = next(x for x in vehiculos if x["id"] == vid)
            res["datos_distintos"].append(
                f"coche {coche}: póliza {chapa} / {chasis} · sistema {v['patente']} / {v['chasis']}")
        obs = f"Póliza N° {p['poliza']}, certificado N° {cert}. {p['cobertura']}"
        vigentes = [dict(r) for r in conn.execute(
            """SELECT id, nombre, fecha_vencimiento, observaciones FROM documentos
               WHERE vehiculo_id=? AND tipo='Seguro' AND reemplazado_por IS NULL""", (vid,)).fetchall()]
        if any(p["poliza"] in (d["observaciones"] or "") for d in vigentes):
            res["ya_estaban"] += 1
            continue
        de_rc = [d for d in vigentes if _ES_RC.search(d["nombre"] or "")]
        # Si alguien ya lo renovó a mano con esta misma vigencia, se completa ese
        ya = next((d for d in de_rc if (d["fecha_vencimiento"] or "")[:10] == p["hasta"]), None)
        if ya:
            conn.execute("""UPDATE documentos SET proveedor=?, fecha_emision=COALESCE(NULLIF(fecha_emision, ''), ?),
                                   observaciones=? WHERE id=?""",
                         (p["aseguradora"], p["desde"],
                          (obs + (" " + ya["observaciones"] if ya["observaciones"] else "")).strip(), ya["id"]))
            res["ya_estaban"] += 1
            continue
        cur = conn.execute("""
            INSERT INTO documentos (vehiculo_id, tipo, nombre, fecha_emision, fecha_vencimiento,
                                    proveedor, costo, observaciones)
            VALUES (?,?,?,?,?,?,?,?)""",
            (vid, "Seguro", p["nombre"], p["desde"], p["hasta"], p["aseguradora"], 0, obs))
        nuevo = cur.lastrowid
        for d in de_rc:                      # el anterior pasa al historial, como al renovar
            conn.execute("UPDATE documentos SET reemplazado_por=?, fecha_renovacion=? WHERE id=?",
                         (nuevo, p["hasta"], d["id"]))
        res["renovados" if de_rc else "nuevos"] += 1
    return res


CARGAS = [(POLIZA_RC_2026["clave"], lambda conn: _aplicar_poliza_rc(conn, POLIZA_RC_2026))]


def init_cargas_datos():
    conn = get_connection()
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS cargas_datos (
                            clave        TEXT PRIMARY KEY,
                            aplicada_el  TEXT NOT NULL,
                            resumen      TEXT DEFAULT '')""")
        conn.commit()
    except Exception as e:
        print(f"[cargas_datos] no se pudo preparar la tabla: {e}")
        try: conn.rollback()
        except Exception: pass
        conn.close()
        return
    for clave, aplicar in CARGAS:
        try:
            # Se anota primero: si otro proceso ya la tomó, esta no hace nada.
            # Todo va en una sola transacción: si algo falla, no queda a medias
            # y se vuelve a intentar en el próximo arranque.
            cur = conn.execute("""INSERT INTO cargas_datos (clave, aplicada_el, resumen) VALUES (?,?,'')
                                  ON CONFLICT (clave) DO NOTHING RETURNING 1 AS id""", (clave, ahora_iso()))
            if not cur.lastrowid:
                conn.rollback()
                continue
            res = aplicar(conn)
            conn.execute("UPDATE cargas_datos SET resumen=? WHERE clave=?", (json.dumps(res, ensure_ascii=False), clave))
            conn.execute("""INSERT INTO auditoria (fecha_hora, usuario, rol, accion, categoria, detalle, referencia)
                            VALUES (?,?,?,?,?,?,?)""",
                         (ahora_iso(), "sistema", "sistema", "Cargó la póliza de responsabilidad civil 2026-2027",
                          "documentos",
                          f"{res['renovados']} seguros renovados, {res['nuevos']} nuevos, {res['ya_estaban']} ya estaban"
                          + (f", {len(res['sin_coche'])} sin coche en el sistema" if res["sin_coche"] else ""),
                          f"carga:{clave}"))
            conn.commit()
            print(f"[cargas_datos] {clave}: {res}")
        except Exception as e:
            print(f"[cargas_datos] {clave} no se aplicó: {e}")
            try: conn.rollback()
            except Exception: pass
    conn.close()


def resumen_carga(clave):
    conn = get_connection()
    try:
        r = conn.execute("SELECT aplicada_el, resumen FROM cargas_datos WHERE clave=?", (clave,)).fetchone()
    finally:
        conn.close()
    if not r:
        return None
    try:
        return {"aplicada_el": r["aplicada_el"], **json.loads(r["resumen"] or "{}")}
    except Exception:
        return {"aplicada_el": r["aplicada_el"]}
