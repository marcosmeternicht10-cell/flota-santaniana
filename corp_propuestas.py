"""
corp_propuestas.py — Correcciones de rendiciones listas para aplicar con un botón

Cuando la oficina detecta que un grupo de servicios quedó a nombre de otro
chofer (o directamente no está), se anota acá la lista de lo que hizo de
verdad y a quién corresponde. En Rendiciones y pagos aparece un aviso con un
botón: al tocarlo, cada servicio de la lista

  · si ya está a nombre del chofer correcto, queda como está;
  · si está a nombre de otro chofer, se le pasa (salvo que esté liquidado);
  · si no está, se carga a su nombre («cargado por …»).

Se aplica una sola vez (queda en cargas_datos) y todo queda en la auditoría.

  GET  /api/corp/propuestas                 las que faltan aplicar, con cómo está cada servicio hoy
  POST /api/corp/propuestas/<clave>/aplicar
"""

from flask import Blueprint, jsonify, session

from db_compat import get_connection
from hora_local import ahora_iso
from nombres import apellido_primero, clave_persona
import corporativos as C

bp_corp_propuestas = Blueprint("corp_propuestas", __name__)

# (fecha, cliente, tramo, estado)
PROPUESTAS = [
    {
        "clave": "sosa_carlos_16_20_nov_2026",
        "titulo": "Servicios del coche 21018, del 16 al 20 de noviembre",
        "chofer": "SOSA, CARLOS",
        "coche": "21018",
        "motivo": "Los tiene en el celular; tienen que quedar a nombre de Sosa Carlos.",
        "servicios": [
            ("2026-11-16", "CERVEPAR", "ITAUGUA 22:00/22:20", "completado"),
            ("2026-11-16", "LASCA", "ADMIN. RUTA 2 (7:00 A 17:30 HS.)", "saliente"),
            ("2026-11-16", "CERVEPAR", "ADMIN. LUQUE", "entrante"),
            ("2026-11-16", "LASCA", "TURNANTE RUTA 1 (4:30 HS.)", "completado"),
            ("2026-11-17", "CERVEPAR", "ADMIN. LUQUE", "completado"),
            ("2026-11-17", "CERVEPAR", "ITAUGUA 14:00/14:20", "completado"),
            ("2026-11-17", "LASCA", "TURNANTE RUTA 2 (4:30 HS.)", "completado"),
            ("2026-11-18", "CERVEPAR", "ITAUGUA 22:00/22:20", "completado"),
            ("2026-11-18", "LASCA", "ADMIN. RUTA 2 (7:00 A 17:30 HS.)", "saliente"),
            ("2026-11-18", "CERVEPAR", "ADMIN. LUQUE", "entrante"),
            ("2026-11-19", "CERVEPAR", "ITAUGUA 22:00/22:20", "completado"),
            ("2026-11-19", "CERVEPAR", "ADMIN. LUQUE", "completado"),
            ("2026-11-20", "CERVEPAR", "ITAUGUA 22:00/22:20", "completado"),
            ("2026-11-20", "LASCA", "TURNANTE RUTA 2 (13:30 HS.)", "completado"),
            ("2026-11-20", "CERVEPAR", "ITAUGUA 6:00/6:20", "completado"),
        ],
    },
]

MITADES = {"completado": {"entrante", "saliente"}, "entrante": {"entrante"}, "saliente": {"saliente"}}


def _aplicadas():
    conn = get_connection()
    try:
        return {r["clave"] for r in conn.execute("SELECT clave FROM cargas_datos").fetchall()}
    except Exception:
        conn.rollback()
        return set()
    finally:
        conn.close()


def _chofer(nombre):
    """El usuario de corporativos de esa persona (sin importar orden ni tildes)."""
    k = clave_persona(nombre)
    conn = get_connection()
    try:
        filas = conn.execute("""SELECT usuario, nombre FROM usuarios WHERE rol='chofer_corp'
                                AND COALESCE(activo,1)=1""").fetchall()
    finally:
        conn.close()
    for f in filas:
        if clave_persona(f["nombre"] or "") == k:
            return {"usuario": f["usuario"], "nombre": f["nombre"]}
    return None


def estado_propuesta(p):
    """Cómo está hoy cada servicio de la lista."""
    ch = _chofer(p["chofer"])
    yo = (ch["usuario"] if ch else "").lower()
    items = []
    for fecha, cliente, tramo, estado in p["servicios"]:
        cli, tc = C._canonizar(cliente, tramo)
        hay = [r for r in C._marcas_dia(cli or cliente, fecha)
               if r["tramo_c"] == (tc or tramo) and MITADES.get(r["estado"], set()) & MITADES[estado]]
        mio = next((r for r in hay if (r["chofer_usuario"] or "").strip().lower() == yo), None)
        it = {"fecha": fecha, "cliente": cli or cliente, "tramo": tc or tramo, "estado": estado}
        if mio:
            it.update(situacion="ok", id=mio["id"])
        elif hay:
            otro = hay[0]
            liq = _liquidado(otro["id"])
            it.update(situacion="liquidado" if liq else "otro", id=otro["id"],
                      quien=apellido_primero(otro["chofer_nombre"] or otro["chofer_usuario"] or ""),
                      quien_usuario=otro["chofer_usuario"], estado_actual=otro["estado"])
        else:
            it.update(situacion="falta")
        items.append(it)
    cuenta = {k: sum(1 for i in items if i["situacion"] == k) for k in ("ok", "otro", "falta", "liquidado")}
    return {"clave": p["clave"], "titulo": p["titulo"], "motivo": p.get("motivo", ""),
            "chofer": apellido_primero(p["chofer"]), "chofer_usuario": ch["usuario"] if ch else "",
            "existe_chofer": bool(ch), "items": items, "cuenta": cuenta}


def _liquidado(rid):
    conn = get_connection()
    try:
        r = conn.execute("SELECT COALESCE(liquidado,0) AS l FROM rendiciones_corp WHERE id=?", (rid,)).fetchone()
        return bool(r and r["l"])
    finally:
        conn.close()


def aplicar(p, quien):
    from corp_marcados import pasar_a_chofer
    est = estado_propuesta(p)
    if not est["existe_chofer"]:
        return None, f"No encontré la cuenta de corporativos de {p['chofer']}"
    pasados, cargados, ya, errores = 0, 0, 0, []
    for it in est["items"]:
        donde = f"{it['fecha'][8:10]}/{it['fecha'][5:7]} {it['cliente']} {it['tramo']}"
        if it["situacion"] == "ok":
            ya += 1
        elif it["situacion"] == "otro":
            r, err = pasar_a_chofer(it["id"], est["chofer_usuario"], quien)
            if r:
                pasados += 1
            else:
                errores.append(f"{donde}: {err}")
        elif it["situacion"] == "liquidado":
            errores.append(f"{donde}: está liquidado a nombre de {it['quien']}")
        else:
            ch = _chofer(p["chofer"])
            ok, msg = C.registrar_rendicion({
                "chofer_usuario": ch["usuario"], "chofer_nombre": ch["nombre"], "cliente": it["cliente"],
                "tramo": it["tramo"], "fecha_servicio": it["fecha"], "estado": it["estado"],
                "bus_interno": p.get("coche", ""), "cargado_por": f"cargado por {quien}",
                "observacion": "Cargado por la oficina (lo tenía en el celular)",
            }, limitar_fecha=False)
            if ok:
                cargados += 1
            else:
                errores.append(f"{donde}: {msg if isinstance(msg, str) else msg.get('msg', 'no se pudo')}")
    resumen = f"{pasados} pasados a {est['chofer']}, {cargados} cargados, {ya} ya estaban" + \
              (f", {len(errores)} con problema" if errores else "")
    conn = get_connection()
    try:
        conn.execute("INSERT INTO cargas_datos (clave, aplicada_el, resumen) VALUES (?,?,?)",
                     (p["clave"], ahora_iso(), resumen[:500]))
        conn.commit()
    except Exception:
        conn.rollback()
    finally:
        conn.close()
    try:
        from app import auditar
        auditar(f"Aplicó la corrección «{p['titulo']}»", "Corporativos",
                resumen + ("" if not errores else " — " + "; ".join(errores)[:900]))
    except Exception:
        pass
    return {"resumen": resumen, "errores": errores}, None


@bp_corp_propuestas.route("/api/corp/propuestas", methods=["GET"])
def api_propuestas():
    if C._rol_efectivo() not in ("admin", "operador_corp"):
        return jsonify({"propuestas": []})
    hechas = _aplicadas()
    return jsonify({"propuestas": [estado_propuesta(p) for p in PROPUESTAS if p["clave"] not in hechas]})


@bp_corp_propuestas.route("/api/corp/propuestas/<clave>/aplicar", methods=["POST"])
def api_aplicar(clave):
    if C._rol_efectivo() not in ("admin", "operador_corp"):
        return jsonify({"ok": False, "error": "Sin permiso"}), 403
    p = next((x for x in PROPUESTAS if x["clave"] == clave), None)
    if not p:
        return jsonify({"ok": False, "error": "No existe esa corrección"}), 404
    if clave in _aplicadas():
        return jsonify({"ok": False, "error": "Ya se aplicó"}), 400
    r, err = aplicar(p, session.get("nombre") or session.get("usuario") or "")
    if err:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "msg": r["resumen"], "errores": r["errores"]})
