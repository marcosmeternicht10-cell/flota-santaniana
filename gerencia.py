"""
Panel del gerente: una sola pantalla, liviana, para mirar desde la compu o el
celular cómo viene el día y cómo viene la plata del mes.

Es de SOLO LECTURA: el rol 'gerente' entra únicamente a esta pantalla y a su
endpoint (app.py le bloquea todo lo demás y cualquier pedido que escriba).
Administración también la puede abrir, para ver lo mismo que ve el gerente.

  · Operación del día: las salidas del tráfico (cuántas, cuáles faltan salir,
    cuáles no tienen coche), los servicios de turismo, los servicios de
    corporativos reportados y los coches que están en el taller o fuera de
    servicio.
  · Plata del mes: combustible, compras del taller y lo que se les paga a los
    choferes de corporativos, comparado con el mes anterior a la misma altura,
    más lo que está esperando fondos de tesorería.

No carga nada aparte: todo sale de lo que ya se registra en los otros módulos.
"""
from datetime import date, timedelta

from flask import Blueprint, jsonify, request, session

from db_compat import get_connection
from hora_local import ahora, hoy

bp_gerencia = Blueprint("gerencia", __name__)

ROLES_PANEL = ("gerente", "admin")

DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "setiembre", "octubre", "noviembre", "diciembre"]


# ════════════════════════════════════════════════════════════════════════════
# FECHAS
# ════════════════════════════════════════════════════════════════════════════

def _fecha_ok(txt, defecto):
    try:
        return date.fromisoformat(str(txt)[:10])
    except Exception:
        return defecto


def _fin_de_mes(d):
    sig = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return sig - timedelta(days=1)


def _mes_anterior(d):
    return (d.replace(day=1) - timedelta(days=1)).replace(day=1)


def fecha_larga(d):
    return f"{DIAS[d.weekday()]} {d.day} de {MESES[d.month - 1]}"


def _rollback(conn):
    try:
        conn.rollback()
    except Exception:
        pass


# ════════════════════════════════════════════════════════════════════════════
# OPERACIÓN DEL DÍA
# ════════════════════════════════════════════════════════════════════════════

def _titulo(txt):
    """CONCEPCION → Concepcion (los corredores vienen en mayúsculas)."""
    return " ".join(p[:1].upper() + p[1:].lower() for p in str(txt or "").split())


def trafico_del_dia(conn, f, es_hoy, hora_ahora):
    """Las salidas del día (nacional e internacional), con su estado según el
    horario: las de antes de ahora ya salieron, las de después están por salir.
    Es lo que dice el tráfico publicado; el sistema no sabe si el coche salió."""
    import trafico as T
    fecha = f.isoformat()
    dias = [dict(r) for r in conn.execute(
        "SELECT * FROM trafico_dias WHERE fecha=? ORDER BY id", (fecha,)).fetchall()]
    salidas = []
    planillas = []
    for d in dias:
        tipo = T.tipo_ok(d.get("tipo") or "nacional")
        planillas.append({"tipo": tipo, "version": int(d.get("version") or 0),
                          "publicado_el": (d.get("publicado_el") or "")[11:16],
                          "modificado": bool(d.get("modificado"))})
        bloques = {b["id"]: b["nombre"] for b in conn.execute(
            "SELECT id, nombre FROM trafico_bloques WHERE dia_id=?", (d["id"],)).fetchall()}
        for s in conn.execute("SELECT * FROM trafico_salidas WHERE dia_id=?", (d["id"],)).fetchall():
            s = dict(s)
            corredor = bloques.get(s["bloque_id"], "")
            lado = s.get("lado") if s.get("lado") in ("ida", "regreso") else "ida"
            try:
                origen, llega = T.tramo(s.get("destino") or "", lado, corredor, tipo)
            except Exception:
                origen, llega = "", ""
            coche = T.limpiar(s.get("coche"))
            hora = T.normalizar_hora(s.get("hora")) if s.get("hora") else ""
            if f < date.fromisoformat(hoy()):
                estado = "salio"
            elif es_hoy:
                estado = "salio" if (hora and hora <= hora_ahora) else "por_salir"
            else:
                estado = "programada"
            salidas.append({
                "hora": hora or "", "corredor": _titulo(corredor), "tipo": tipo, "lado": lado,
                "origen": origen, "llega": llega, "destino": T.limpiar(s.get("destino")),
                "coche": coche if coche.isdigit() else "",
                "sin_coche": not coche.isdigit(),
                "a_confirmar": "CONF" in coche,
                "estado": estado,
            })
    salidas.sort(key=lambda s: (s["hora"] or "99:99", s["corredor"]))
    return {
        "existe": bool(dias),
        "planillas": planillas,
        "total": len(salidas),
        "salieron": sum(1 for s in salidas if s["estado"] == "salio"),
        "por_salir": sum(1 for s in salidas if s["estado"] in ("por_salir", "programada")),
        "sin_coche": sum(1 for s in salidas if s["sin_coche"]),
        "internacional": sum(1 for s in salidas if s["tipo"] == "internacional"),
        "coches": len({s["coche"] for s in salidas if s["coche"]}),
        "salidas": salidas,
    }


def internacional_proximo(conn, f, dias=7):
    """La próxima fecha (después de f, hasta una semana) con salidas
    internacionales cargadas en el tráfico, para avisar cuándo sale el próximo
    a Buenos Aires si ese día no hay."""
    hasta = (f + timedelta(days=dias)).isoformat()
    filas = conn.execute("""SELECT DISTINCT d.fecha FROM trafico_dias d JOIN trafico_salidas s ON s.dia_id = d.id
                            WHERE COALESCE(d.tipo,'nacional') = 'internacional' AND d.fecha > ? AND d.fecha <= ?
                            ORDER BY d.fecha LIMIT 1""", (f.isoformat(), hasta)).fetchall()
    if not filas:
        return None
    fp = date.fromisoformat(str(filas[0]["fecha"])[:10])
    t = trafico_del_dia(conn, fp, False, "")
    sal = [x for x in t["salidas"] if x["tipo"] == "internacional"]
    return {"fecha": fp.isoformat(), "fecha_larga": fecha_larga(fp), "salidas": sal} if sal else None


def turismo_del_dia(f):
    """Los servicios de turismo que salen ese día y los viajes que siguen en curso."""
    try:
        import turismo_agenda as TA
        fecha = f.isoformat()
        servs = TA.listar_servicios(desde=fecha, hasta=fecha)
        dias = TA.agrupar_por_dia(servs, fecha, fecha)
    except Exception:
        return {"total": 0, "completados": 0, "cancelados": 0, "sin_asignar": 0, "servicios": [], "en_viaje": []}
    d = dias[0] if dias else {"servicios": [], "en_viaje": []}

    def fila(s, continua=False):
        return {
            "hora": (s.get("hora") or "")[:5], "cliente": s.get("cliente") or "",
            "salida": s.get("salida") or "", "destino": s.get("destino") or "",
            "coches": [c["coche_interno"] for c in (s.get("coches") or []) if c.get("coche_interno")],
            "estado": s.get("estado") or "agendado", "falta": s.get("falta") or "",
            "sin_asignar": bool(s.get("sin_asignar")) and s.get("estado") != "cancelado",
            "dias": s.get("dias", 1), "dia_n": s.get("dia_n", 1) if continua else 1,
            "pasajeros": s.get("pasajeros") or 0,
        }
    salen = [fila(s) for s in d.get("servicios", [])]
    siguen = [fila(s, True) for s in d.get("en_viaje", [])]
    activos = [s for s in salen if s["estado"] != "cancelado"]
    return {
        "total": len(activos),
        "completados": sum(1 for s in salen if s["estado"] == "completado"),
        "cancelados": sum(1 for s in salen if s["estado"] == "cancelado"),
        "sin_asignar": sum(1 for s in salen if s["sin_asignar"]),
        "servicios": salen,
        "en_viaje": siguen,
    }


def corporativos_del_dia(conn, f):
    """Los servicios de corporativos que los choferes reportaron para ese día."""
    try:
        filas = conn.execute("""SELECT cliente, estado FROM rendiciones_corp
                                WHERE fecha_servicio=?""", (f.isoformat(),)).fetchall()
    except Exception:
        _rollback(conn)
        return {"servicios": 0, "completos": 0, "medios": 0, "suspendidos": 0, "clientes": []}
    por_cliente = {}
    for r in filas:
        por_cliente[r["cliente"]] = por_cliente.get(r["cliente"], 0) + (0 if r["estado"] == "suspendido" else 1)
    return {
        "servicios": sum(1 for r in filas if r["estado"] != "suspendido"),
        "completos": sum(1 for r in filas if r["estado"] == "completado"),
        "medios": sum(1 for r in filas if r["estado"] in ("entrante", "saliente")),
        "suspendidos": sum(1 for r in filas if r["estado"] == "suspendido"),
        "clientes": [{"cliente": c, "servicios": n} for c, n in sorted(por_cliente.items(), key=lambda x: -x[1])],
    }


def flota_del_dia(conn, f):
    """Cuántos coches hay y cuáles no están disponibles ese día: los que tienen
    una OT abierta en el taller y los marcados fuera de servicio."""
    fecha = f.isoformat()
    activos = {r["id"]: dict(r) for r in conn.execute(
        "SELECT id, n_interno, patente FROM vehiculos WHERE COALESCE(activo,1)=1").fetchall()}
    parados = {}

    def nombre(v):
        return str(v.get("n_interno") or "").strip() or v.get("patente") or "?"

    try:
        for r in conn.execute("""SELECT vehiculo_id, fecha_desde, motivo FROM fuera_servicio
                                 WHERE fecha_desde <= ? AND (fecha_hasta IS NULL OR fecha_hasta = '' OR fecha_hasta >= ?)""",
                              (fecha, fecha)).fetchall():
            v = activos.get(r["vehiculo_id"])
            if v:
                parados[r["vehiculo_id"]] = {"coche": nombre(v), "desde": str(r["fecha_desde"])[:10],
                                             "motivo": r["motivo"] or "Fuera de servicio", "tipo": "fuera"}
    except Exception:
        _rollback(conn)
    try:
        for r in conn.execute("""SELECT vehiculo_id, MIN(fecha_apertura) AS desde FROM ordenes_trabajo
                                 WHERE substr(fecha_apertura,1,10) <= ?
                                   AND (estado <> 'cerrada' OR (fecha_cierre IS NOT NULL AND substr(fecha_cierre,1,10) > ?))
                                 GROUP BY vehiculo_id""", (fecha, fecha)).fetchall():
            v = activos.get(r["vehiculo_id"])
            if v and r["vehiculo_id"] not in parados:
                parados[r["vehiculo_id"]] = {"coche": nombre(v), "desde": str(r["desde"])[:10],
                                             "motivo": "En el taller", "tipo": "taller"}
    except Exception:
        _rollback(conn)
    lista = []
    for p in parados.values():
        try:
            p["dias"] = max(0, (f - date.fromisoformat(p["desde"])).days)
        except Exception:
            p["dias"] = 0
        lista.append(p)
    lista.sort(key=lambda p: -p["dias"])
    return {
        "activos": len(activos),
        "disponibles": len(activos) - len(lista),
        "en_taller": sum(1 for p in lista if p["tipo"] == "taller"),
        "fuera_servicio": sum(1 for p in lista if p["tipo"] == "fuera"),
        "parados": lista,
    }


def operacion_del_dia(f):
    ah = ahora()
    es_hoy = f.isoformat() == ah.date().isoformat()
    conn = get_connection()
    try:
        try:
            trafico = trafico_del_dia(conn, f, es_hoy, ah.strftime("%H:%M"))
        except Exception:
            _rollback(conn)
            trafico = {"existe": False, "planillas": [], "total": 0, "salieron": 0, "por_salir": 0,
                       "sin_coche": 0, "internacional": 0, "coches": 0, "salidas": []}
        corp = corporativos_del_dia(conn, f)
        flota = flota_del_dia(conn, f)
        try:
            inter_prox = None if trafico["internacional"] else internacional_proximo(conn, f)
        except Exception:
            _rollback(conn)
            inter_prox = None
    finally:
        conn.close()
    return {
        "fecha": f.isoformat(), "fecha_larga": fecha_larga(f), "es_hoy": es_hoy,
        "hora": ah.strftime("%H:%M") if es_hoy else "",
        "trafico": trafico, "turismo": turismo_del_dia(f),
        "corporativos": corp, "flota": flota, "internacional_proximo": inter_prox,
    }


# ════════════════════════════════════════════════════════════════════════════
# PLATA DEL MES
# ════════════════════════════════════════════════════════════════════════════

def _por_dia_combustible(conn, desde, hasta):
    """Gasto de combustible por día. Cada carga vale lo que se anotó; si solo
    tiene litros, se valúa al último precio por litro registrado (estimado)."""
    filas = conn.execute("""SELECT substr(fecha,1,10) AS f, litros, precio_litro, costo_total
                            FROM combustible WHERE substr(fecha,1,10) BETWEEN ? AND ?""",
                         (desde, hasta)).fetchall()
    try:
        from corporativos import ultimo_precio_litro
        ultimo = float(ultimo_precio_litro() or 0)
    except Exception:
        ultimo = 0
    por_dia, litros, estimadas, sin_valor = {}, 0.0, 0, 0
    for r in filas:
        l = float(r["litros"] or 0)
        litros += l
        if float(r["costo_total"] or 0) > 0:
            g = float(r["costo_total"])
        elif float(r["precio_litro"] or 0) > 0:
            g = l * float(r["precio_litro"])
        elif ultimo > 0:
            g = l * ultimo
            estimadas += 1
        else:
            g = 0
            sin_valor += 1
        por_dia[r["f"]] = por_dia.get(r["f"], 0) + g
    return por_dia, {"litros": round(litros), "cargas": len(filas), "estimadas": estimadas,
                     "sin_valor": sin_valor, "precio": round(ultimo)}


def _por_dia_compras(conn, desde, hasta):
    """Lo que compró el taller: el precio de cada trabajo o repuesto, el día que
    tesorería lo habilitó (o, si no pasó por tesorería, el día que compras lo
    entregó o presupuestó). Lo que espera fondos no cuenta: todavía no se gastó."""
    filas = conn.execute("""
        SELECT substr(COALESCE(i.fecha_habilitado, o.fecha_entrega, o.fecha_presupuesto), 1, 10) AS f,
               i.precio_compras AS p
        FROM ot_items i JOIN ordenes_trabajo o ON o.id = i.ot_id
        WHERE COALESCE(i.precio_compras, 0) > 0 AND COALESCE(i.estado_pago, '') <> 'espera'
          AND substr(COALESCE(i.fecha_habilitado, o.fecha_entrega, o.fecha_presupuesto), 1, 10) BETWEEN ? AND ?
    """, (desde, hasta)).fetchall()
    por_dia = {}
    for r in filas:
        por_dia[r["f"]] = por_dia.get(r["f"], 0) + float(r["p"] or 0)
    return por_dia, {"items": len(filas)}


def _por_dia_corporativos(conn, desde, hasta):
    """Lo que se les paga a los choferes de corporativos por los servicios del
    período, con el plus semanal (igual que la liquidación: una vez por semana
    trabajada, el primer día que trabajó esa semana)."""
    filas = [dict(r) for r in conn.execute("""
        SELECT fecha_servicio, chofer_nombre, chofer_usuario, estado, monto, liquidado
        FROM rendiciones_corp WHERE fecha_servicio BETWEEN ? AND ?
        ORDER BY fecha_servicio""", (desde, hasta)).fetchall()]
    por_dia, pagado = {}, 0.0
    for r in filas:
        f = str(r["fecha_servicio"])[:10]
        m = float(r["monto"] or 0)
        por_dia[f] = por_dia.get(f, 0) + m
        if r.get("liquidado"):
            pagado += m
    plus_total = 0
    try:
        import corporativos as C
        cfg = C.config_plus()
        vistos = set()
        for r in filas:
            if r["estado"] == "suspendido":
                continue
            nom = r.get("chofer_nombre") or r.get("chofer_usuario") or ""
            sem = C._semana_de(r["fecha_servicio"])
            if not sem or (nom, sem) in vistos:
                continue
            vistos.add((nom, sem))
            p = C.monto_plus_de(nom, cfg) if C._tiene_plus(nom, cfg["choferes"]) else 0
            if p:
                f = str(r["fecha_servicio"])[:10]
                por_dia[f] = por_dia.get(f, 0) + p
                plus_total += p
    except Exception:
        pass
    servicios = sum(1 for r in filas if r["estado"] != "suspendido")
    return por_dia, {"servicios": servicios, "pagado": round(pagado), "plus": round(plus_total)}


def _espera_fondos(conn):
    try:
        filas = conn.execute("""SELECT precio_compras, fecha_espera FROM ot_items
                                WHERE estado_pago='espera'""").fetchall()
    except Exception:
        _rollback(conn)
        return {"monto": 0, "items": 0, "dias_max": 0}
    dias_max = 0
    h = date.fromisoformat(hoy())
    for r in filas:
        try:
            dias_max = max(dias_max, (h - date.fromisoformat(str(r["fecha_espera"])[:10])).days)
        except Exception:
            pass
    return {"monto": round(sum(float(r["precio_compras"] or 0) for r in filas)),
            "items": len(filas), "dias_max": dias_max}


CATEGORIAS = [
    ("combustible", "Combustible", _por_dia_combustible),
    ("taller", "Compras del taller", _por_dia_compras),
    ("corporativos", "Choferes de corporativos", _por_dia_corporativos),
]


def plata_del_mes(mes_txt=None):
    """Gasto del mes por categoría, día por día, contra el mes anterior.

    Si el mes es el actual, la comparación es "a esta altura": del 1 al mismo
    día del mes anterior, para no comparar medio mes contra un mes entero."""
    h = date.fromisoformat(hoy())
    try:
        ini = date(int(mes_txt[:4]), int(mes_txt[5:7]), 1)
    except Exception:
        ini = h.replace(day=1)
    if ini > h.replace(day=1):
        ini = h.replace(day=1)
    fin = _fin_de_mes(ini)
    es_actual = ini == h.replace(day=1)
    hasta = h if es_actual else fin
    ini_ant = _mes_anterior(ini)
    fin_ant = _fin_de_mes(ini_ant)
    # Mismo tramo del mes anterior (si el mes anterior es más corto, hasta su último día)
    hasta_ant_igual = min(fin_ant, ini_ant + timedelta(days=hasta.day - 1)) if es_actual else fin_ant

    conn = get_connection()
    cats = []
    serie_act = [0.0] * hasta.day
    serie_ant = [0.0] * fin_ant.day
    try:
        for clave, nombre, fn in CATEGORIAS:
            try:
                act, info = fn(conn, ini.isoformat(), hasta.isoformat())
                ant, _ = fn(conn, ini_ant.isoformat(), fin_ant.isoformat())
            except Exception:
                _rollback(conn)
                act, info, ant = {}, {}, {}
            monto = sum(act.values())
            monto_ant = sum(v for f, v in ant.items() if f <= hasta_ant_igual.isoformat())
            for f, v in act.items():
                try:
                    serie_act[int(f[8:10]) - 1] += v
                except Exception:
                    pass
            for f, v in ant.items():
                try:
                    serie_ant[int(f[8:10]) - 1] += v
                except Exception:
                    pass
            cats.append({"clave": clave, "nombre": nombre, "monto": round(monto),
                         "monto_ant": round(monto_ant), "info": info})
        espera = _espera_fondos(conn)
    finally:
        conn.close()

    def acumulado(serie):
        out, t = [], 0
        for v in serie:
            t += v
            out.append(round(t))
        return out

    total = sum(c["monto"] for c in cats)
    total_ant = sum(c["monto_ant"] for c in cats)
    return {
        "mes": ini.isoformat()[:7], "mes_txt": f"{MESES[ini.month - 1]} {ini.year}",
        "mes_ant_txt": MESES[ini_ant.month - 1], "es_actual": es_actual,
        "hasta_dia": hasta.day, "dias_mes": fin.day, "dias_mes_ant": fin_ant.day,
        "total": total, "total_ant": total_ant,
        "variacion": (round((total - total_ant) * 100 / total_ant) if total_ant else None),
        "categorias": cats,
        "acumulado": {"actual": acumulado(serie_act), "anterior": acumulado(serie_ant)},
        "espera_fondos": espera,
        "mes_anterior_param": ini_ant.isoformat()[:7],
        "mes_actual_param": h.isoformat()[:7],
    }


# ════════════════════════════════════════════════════════════════════════════
# RUTAS
# ════════════════════════════════════════════════════════════════════════════

def puede_ver():
    return session.get("rol") in ROLES_PANEL


# La pantalla (/gerencia) está en app.py, junto a las otras pantallas propias
# de un rol (/boleteria, /corp): usa el número de versión de los estáticos.

@bp_gerencia.route("/api/gerencia/panel", methods=["GET"])
def api_panel():
    if not puede_ver():
        return jsonify({"error": "Sin permiso"}), 403
    h = date.fromisoformat(hoy())
    f = _fecha_ok(request.args.get("fecha"), h)
    ah = ahora()
    return jsonify({
        "hoy": h.isoformat(), "actualizado": ah.strftime("%H:%M"),
        "saludo": ("Buen día" if ah.hour < 12 else "Buenas tardes" if ah.hour < 20 else "Buenas noches"),
        "operacion": operacion_del_dia(f),
        "plata": plata_del_mes(request.args.get("mes")),
    })
