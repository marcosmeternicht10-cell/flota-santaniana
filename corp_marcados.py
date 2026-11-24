"""
corp_marcados.py — Servicios marcados (Corporativos → Servicios marcados)

Todos los servicios de un día, con quién marcó cada uno, y quién marcó más.
Es la pantalla para ver de un vistazo qué cargaron los choferes y borrar lo
que esté de más (el borrado usa las rutas de siempre de corporativos.py, que
no dejan borrar lo ya liquidado y dejan registro en la auditoría).

  GET /api/corp/marcados?fecha=AAAA-MM-DD
"""

from datetime import date, timedelta

from flask import Blueprint, jsonify, request

from db_compat import get_connection
from hora_local import hoy as _hoy
from nombres import apellido_primero
import corporativos as C

bp_corp_marcados = Blueprint("corp_marcados", __name__)

ESTADO_TXT = {"completado": "Completo", "ok": "Completo", "entrante": "Entrante", "saliente": "Saliente", "suspendido": "Suspendido"}


def marcados(fecha):
    conn = get_connection()
    try:
        filas = [dict(r) for r in conn.execute("""
            SELECT id, chofer_usuario, chofer_nombre, cliente, tramo, fecha_servicio, bus_interno, hora_inicio,
                   km_inicial, km_final, pasajeros, estado, observacion, COALESCE(monto, 0) AS monto,
                   COALESCE(liquidado, 0) AS liquidado, cargado_el, fecha_carga, editado_por
            FROM rendiciones_corp WHERE fecha_servicio >= ? AND fecha_servicio <= ?
            ORDER BY id""", (fecha, fecha + "~")).fetchall()]
        d0 = date.fromisoformat(fecha)
        desde = (d0 - timedelta(days=6)).isoformat()
        por_dia = {str(r["f"])[:10]: int(r["n"]) for r in conn.execute("""
            SELECT SUBSTR(fecha_servicio, 1, 10) AS f, COUNT(*) AS n FROM rendiciones_corp
            WHERE fecha_servicio >= ? AND fecha_servicio <= ? GROUP BY 1""", (desde, fecha + "~")).fetchall()}
    finally:
        conn.close()

    # Lo que no cierra: el mismo chofer con dos servicios a la misma hora, y el
    # mismo tramo marcado por dos choferes
    por_chofer, por_tramo = {}, {}
    for r in filas:
        cli, tr = C._canonizar(r["cliente"], r["tramo"])
        r["cliente"] = cli or (r["cliente"] or "").strip().upper()
        r["tramo"] = tr or (r["tramo"] or "").strip()
        r["chofer_usuario"] = (r["chofer_usuario"] or "").strip().lower()
        if r["estado"] != "suspendido":
            por_chofer.setdefault(r["chofer_usuario"], []).append(r)
            if not C._es_variable(r["tramo"]):
                por_tramo.setdefault((r["cliente"], r["tramo"]), []).append(r)
    avisos, choca_con = {}, {}
    viajes = {r["id"]: ([] if C._es_variable(r["tramo"]) else
                        C.viajes_servicio(r["tramo"], r.get("hora_inicio") or "", r["estado"] or "completado"))
              for r in filas}
    for grupo in por_chofer.values():
        for i, a in enumerate(grupo):
            for b in grupo[i + 1:]:
                if viajes[a["id"]] and viajes[b["id"]] and C._mismo_horario(viajes[a["id"]], viajes[b["id"]]):
                    for x, y in ((a, b), (b, a)):
                        avisos[x["id"]] = "Mismo horario que otro servicio suyo"
                        choca_con.setdefault(x["id"], []).append(y["id"])
    for grupo in por_tramo.values():
        choferes = {g["chofer_usuario"] for g in grupo}
        mitades = [g["estado"] for g in grupo]
        if len(choferes) > 1 and not (sorted(mitades) == ["entrante", "saliente"]):
            for g in grupo:
                avisos.setdefault(g["id"], "Este tramo también lo marcó otro chofer")
                choca_con.setdefault(g["id"], []).extend(
                    x["id"] for x in grupo if x["chofer_usuario"] != g["chofer_usuario"] and x["id"] not in choca_con.get(g["id"], []))

    servicios, cuenta, clientes = [], {}, {}
    for r in filas:
        cargado = r.get("cargado_el") or r.get("fecha_carga") or ""
        km = (float(r["km_final"] or 0) - float(r["km_inicial"] or 0)) if r["km_final"] and r["km_inicial"] else 0
        servicios.append({
            "id": r["id"], "usuario": r["chofer_usuario"], "chofer": apellido_primero(r["chofer_nombre"] or r["chofer_usuario"]),
            "cliente": r["cliente"], "tramo": r["tramo"], "estado": r["estado"],
            "estado_txt": ESTADO_TXT.get(r["estado"], r["estado"] or ""),
            "coche": r["bus_interno"] or "", "pasajeros": int(r["pasajeros"] or 0), "km": round(km) if 0 < km < 1500 else 0,
            "monto": float(r["monto"] or 0), "liquidado": bool(r["liquidado"]),
            "cargado_el": cargado[:16].replace("T", " "), "otro_dia": bool(cargado) and cargado[:10] != fecha,
            "observacion": r["observacion"] or "", "editado_por": r["editado_por"] or "",
            "aviso": avisos.get(r["id"], ""), "choca_con": choca_con.get(r["id"], []),
            "horario": C._txt_viajes(viajes[r["id"]]) if viajes[r["id"]] else "",
        })
        c = cuenta.setdefault(r["chofer_usuario"], {"usuario": r["chofer_usuario"], "chofer": servicios[-1]["chofer"],
                                                    "servicios": 0, "suspendidos": 0, "avisos": 0, "clientes": set(),
                                                    "monto": 0.0, "primera": "", "ultima": ""})
        c["servicios"] += 1
        c["suspendidos"] += r["estado"] == "suspendido"
        c["avisos"] += r["id"] in avisos
        c["clientes"].add(r["cliente"])
        c["monto"] += float(r["monto"] or 0)
        hora = cargado[11:16]
        if hora and cargado[:10] == fecha:
            c["primera"] = min(c["primera"] or hora, hora)
            c["ultima"] = max(c["ultima"], hora)
        clientes[r["cliente"]] = clientes.get(r["cliente"], 0) + 1
    choferes = sorted(cuenta.values(), key=lambda c: (-c["servicios"], c["chofer"]))
    for c in choferes:
        c["clientes"] = sorted(c["clientes"])
    prom = round(len(servicios) / len(choferes), 1) if choferes else 0
    semana = []
    for i in range(6, -1, -1):
        f = (d0 - timedelta(days=i)).isoformat()
        semana.append({"fecha": f, "n": por_dia.get(f, 0)})
    return {
        "fecha": fecha, "hoy": _hoy(), "servicios": servicios, "choferes": choferes,
        "clientes": sorted(clientes.items(), key=lambda kv: -kv[1]),
        "total": len(servicios), "suspendidos": sum(1 for s in servicios if s["estado"] == "suspendido"),
        "con_aviso": len(avisos), "promedio": prom, "semana": semana,
        "puede_borrar": C._rol_efectivo() in ("admin", "operador_corp"),
        "choferes_corp": _choferes_corp() if C._rol_efectivo() in ("admin", "operador_corp") else [],
    }


def _choferes_corp():
    conn = get_connection()
    try:
        return [{"usuario": r["usuario"], "nombre": apellido_primero(r["nombre"] or r["usuario"])}
                for r in conn.execute("""SELECT usuario, nombre FROM usuarios WHERE rol='chofer_corp'
                                         AND COALESCE(activo,1)=1 ORDER BY nombre""").fetchall()]
    finally:
        conn.close()


def pasar_a_chofer(rid, usuario, quien):
    """Pasa un servicio marcado a otro chofer: para cuando lo marcó uno y lo
    hizo otro (o alguien entró con el usuario equivocado)."""
    usuario = (usuario or "").strip().lower()
    conn = get_connection()
    try:
        r = conn.execute("""SELECT id, chofer_usuario, chofer_nombre, cliente, tramo, fecha_servicio, estado,
                                   COALESCE(liquidado,0) AS liquidado FROM rendiciones_corp WHERE id=?""", (rid,)).fetchone()
        if not r:
            return None, "Ese servicio ya no existe"
        if r["liquidado"]:
            return None, "Ya está liquidado: para cambiarlo hay que revertir la liquidación"
        u = conn.execute("""SELECT usuario, nombre FROM usuarios WHERE LOWER(usuario)=? AND rol='chofer_corp'""",
                         (usuario,)).fetchone()
        if not u:
            return None, "Elegí un chofer de corporativos"
        if (r["chofer_usuario"] or "").strip().lower() == usuario:
            return None, "Ya está a nombre de ese chofer"
        tc = C._tramo_c(r["cliente"], r["tramo"])
        if not C._es_variable(tc) and any(
                x["tramo_c"] == tc and (x["chofer_usuario"] or "").strip().lower() == usuario
                for x in C._marcas_dia(r["cliente"], str(r["fecha_servicio"])[:10], excluir_id=r["id"])):
            return None, f"{apellido_primero(u['nombre'])} ya tiene marcado ese tramo ese día"
        conn.execute("""UPDATE rendiciones_corp SET chofer_usuario=?, chofer_nombre=?, editado_por=?, fecha_edicion=?
                        WHERE id=?""", (u["usuario"], u["nombre"], quien, C.ahora_iso(), rid))
        conn.commit()
    finally:
        conn.close()
    try:
        from app import auditar
    except Exception:
        auditar = C.auditar
    auditar("Pasó un servicio de corporativos a otro chofer", "Corporativos",
              f"{r['cliente']} {r['tramo']} del {str(r['fecha_servicio'])[:10]}: de {r['chofer_nombre']} a {u['nombre']}")
    return {"chofer": apellido_primero(u["nombre"]), "antes": apellido_primero(r["chofer_nombre"] or "")}, None


@bp_corp_marcados.route("/api/corp/marcados", methods=["GET"])
def api_marcados():
    if C._rol_efectivo() not in ("admin", "auditor", "operador_corp"):
        return jsonify({"error": "Sin permiso"}), 403
    fecha = (request.args.get("fecha") or _hoy())[:10]
    try:
        date.fromisoformat(fecha)
    except ValueError:
        return jsonify({"error": "Fecha inválida"}), 400
    return jsonify(marcados(fecha))


@bp_corp_marcados.route("/api/corp/marcados/<int:rid>/chofer", methods=["POST"])
def api_pasar_a_chofer(rid):
    if C._rol_efectivo() not in ("admin", "operador_corp"):
        return jsonify({"error": "Sin permiso"}), 403
    from flask import session
    r, err = pasar_a_chofer(rid, (request.get_json(silent=True) or {}).get("usuario"),
                            session.get("nombre") or session.get("usuario") or "")
    if err:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, "msg": f"Pasó de {r['antes']} a {r['chofer']}"})
