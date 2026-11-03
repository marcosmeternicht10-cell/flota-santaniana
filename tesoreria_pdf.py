"""
tesoreria_pdf.py — Pedido de fondos para Tesorería (La Santaniana)

Lo que Compras imprime para que el Director General autorice y Tesorería
entregue la plata. Una hoja (o las que hagan falta) por OT:

  · el monto pedido bien grande, en números y en letras;
  · el detalle por coche y por trabajo: cada material con su cantidad, el
    precio por unidad y el subtotal;
  · si Tesorería ya firmó, qué quedó habilitado y qué espera fondos;
  · las firmas de quien pide (Compras), quien autoriza (Director General) y
    quien entrega los fondos (Tesorería).

  datos_pedido(ot_id, usuario)   junta todo lo de la OT (con todos sus coches)
  pdf_pedido_fondos(d)           arma el PDF y devuelve un BytesIO
"""

from nombres import apellido_primero, apellido_primero_varios
import io

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import white

import trafico_pdf
from rend_comb_pdf import (_Lienzo, _logo, _miles, _ahora_txt,
                           NAVY, AZUL, TINTA, GRIS, GRIS2, LINEA, SUAVE, CEBRA,
                           VERDE, VERDE_F, AZUL_F, AMBAR, AMBAR_F, CELESTE)


# ════════════════════════════════════════════════════════════════════════════
# NÚMEROS EN LETRAS ("Son guaraníes: un millón doscientos mil")
# ════════════════════════════════════════════════════════════════════════════

_UNI = ["", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez",
        "once", "doce", "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho",
        "diecinueve", "veinte", "veintiuno", "veintidós", "veintitrés", "veinticuatro",
        "veinticinco", "veintiséis", "veintisiete", "veintiocho", "veintinueve"]
_DEC = ["", "", "", "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa"]
_CEN = ["", "ciento", "doscientos", "trescientos", "cuatrocientos", "quinientos", "seiscientos",
        "setecientos", "ochocientos", "novecientos"]


def _hasta_999(n):
    if n == 100:
        return "cien"
    c, r = divmod(n, 100)
    partes = [_CEN[c]] if c else []
    if r:
        if r < 30:
            partes.append(_UNI[r])
        else:
            d, u = divmod(r, 10)
            partes.append(_DEC[d] + (f" y {_UNI[u]}" if u else ""))
    return " ".join(partes)


def _apocope(t):
    """'uno' delante de mil / millones se dice 'un' (veintiún mil, treinta y un millones)."""
    if t.endswith("veintiuno"):
        return t[: -len("veintiuno")] + "veintiún"
    if t.endswith("uno"):
        return t[:-3] + "un"
    return t


def en_letras(n):
    n = int(round(float(n or 0)))
    if n <= 0:
        return "cero"
    millones, resto = divmod(n, 1_000_000)
    miles, unidades = divmod(resto, 1000)
    partes = []
    if millones:
        partes.append("un millón" if millones == 1 else _apocope(en_letras(millones)) + " millones")
    if miles:
        partes.append("mil" if miles == 1 else _apocope(_hasta_999(miles)) + " mil")
    if unidades:
        partes.append(_hasta_999(unidades))
    return " ".join(partes)


# ════════════════════════════════════════════════════════════════════════════
# DATOS
# ════════════════════════════════════════════════════════════════════════════

def _hoy():
    try:
        from hora_local import hoy
        return hoy()
    except Exception:
        from datetime import date
        return date.today().isoformat()


def datos_pedido(ot_id, usuario=""):
    import database as db
    try:
        from ot_materiales import grupo_ids
        ids = grupo_ids(ot_id)
    except Exception:
        ids = [ot_id]
    coches = [c for c in (db.obtener_ot(i) for i in ids) if c]
    cab = coches[0]
    salida, total, habilitado, espera, firmado = [], 0.0, 0.0, 0.0, False
    n_trab = n_mat = 0
    for c in coches:
        trabajos = []
        for it in c.get("items") or []:
            mats = it.get("materiales") or []
            precio = float(it.get("precio_compras") or 0)
            if not mats and precio <= 0:
                continue          # mano de obra propia: no se le pide plata a Tesorería
            ep = it.get("estado_pago") or ""
            if ep:
                firmado = True
            if ep == "habilitado":
                habilitado += precio
            elif ep == "espera":
                espera += precio
            total += precio
            n_trab += 1
            n_mat += len(mats)
            trabajos.append({"descripcion": it.get("descripcion") or "", "tecnico": it.get("tecnico") or "",
                             "materiales": mats, "precio": precio, "proveedor": it.get("proveedor_compras") or "",
                             "estado_pago": ep})
        salida.append({"n_interno": c.get("n_interno") or "", "patente": c.get("patente") or "",
                       "marca": c.get("marca") or "", "modelo": c.get("modelo") or "",
                       "km": c.get("km") or 0, "trabajos": trabajos,
                       "subtotal": sum(t["precio"] for t in trabajos)})
    # Cuánto va a cada proveedor ("Diesa" y "DIESA S.A." son el mismo)
    import re as _re
    import unicodedata as _ud
    def _clave(t):
        t = "".join(ch for ch in _ud.normalize("NFD", str(t or "").lower()) if _ud.category(ch) != "Mn")
        return " ".join(w for w in _re.sub(r"[^a-z0-9 ]+", " ", t).split()
                        if w not in ("s", "a", "sa", "srl", "sae", "saeca", "eca", "ltda", "cia", "y"))
    provs = {}
    def _sumar(nombre, monto, dep=False):
        k = "__dep" if dep else (_clave(nombre) or "__sin")
        g = provs.setdefault(k, {"proveedor": "Sale del depósito" if dep else (nombre or "Sin proveedor elegido"),
                                 "renglones": 0, "total": 0.0, "deposito": dep, "sin": k == "__sin"})
        if nombre and not dep and len(nombre) > len(g["proveedor"]) and k != "__sin":
            g["proveedor"] = nombre
        g["renglones"] += 1
        g["total"] += monto
    for co in salida:
        for t in co["trabajos"]:
            if t["materiales"]:
                for m in t["materiales"]:
                    dep = (m.get("origen") or "") == "deposito"
                    _sumar((m.get("proveedor") or "").strip() or (t.get("proveedor") or "").strip(),
                           float(m.get("subtotal") or 0), dep)
            else:
                _sumar((t.get("proveedor") or "").strip(), float(t["precio"] or 0))
    por_proveedor = sorted(provs.values(), key=lambda g: (g["deposito"], g["sin"], -g["total"]))
    return {
        "por_proveedor": [{**g, "total": round(g["total"])} for g in por_proveedor],
        "numero": cab.get("numero") or cab["id"],
        "fecha_apertura": cab.get("fecha_apertura") or "",
        "fecha_pedido": (cab.get("fecha_presupuesto") or "")[:10] or _hoy(),
        "procedencia": cab.get("procedencia") or "",
        "proveedor": cab.get("proveedor_compras") or "",
        "nota": cab.get("nota_compras") or "",
        "estado_compras": cab.get("estado_compras") or "",
        "coches": salida,
        "total": round(total), "habilitado": round(habilitado), "espera": round(espera),
        "firmado": firmado, "trabajos": n_trab, "materiales": n_mat,
        "usuario": usuario or "",
    }


# ════════════════════════════════════════════════════════════════════════════
# PDF
# ════════════════════════════════════════════════════════════════════════════

def _dmy(f):
    f = str(f or "")
    return f"{f[8:10]}/{f[5:7]}/{f[0:4]}" if len(f) >= 10 else ""


def _gs(v):
    return "Gs. " + _miles(round(float(v or 0)))


def _cant(q):
    try:
        q = float(q or 0)
    except (TypeError, ValueError):
        return "1"
    return str(int(q)) if q == int(q) else _miles(q, 2)


def _nombre_coche(c):
    return f"COCHE {c['n_interno']}" if c.get("n_interno") else (c.get("patente") or "").upper()


def _partir(L, t, f, s, maxw, max_lineas=3):
    palabras, linea, lineas = str(t or "").split(), "", []
    for p in palabras:
        prueba = (linea + " " + p).strip()
        if linea and L.ancho(prueba, f, s) > maxw:
            lineas.append(linea)
            linea = p
        else:
            linea = prueba
    if linea:
        lineas.append(linea)
    if len(lineas) > max_lineas:
        lineas = lineas[:max_lineas]
        lineas[-1] = L.cortar(lineas[-1] + " …", f, s, maxw)
    return lineas or [""]


def _dibujar(d, c, total_pag):
    """Dibuja el pedido. Devuelve cuántas hojas usó (para el 'Hoja X de N')."""
    F = trafico_pdf._fuentes()
    W, H = A4
    M = 34
    aw = W - 2 * M
    L = _Lienzo(c, H, F)
    logo = _logo()
    impresa = _ahora_txt()
    pie_quien = f" por {d['usuario']}" if d.get("usuario") else ""
    LIMITE = H - 46
    pag = [1]
    coches_txt = " · ".join(str(x["n_interno"] or x["patente"]) for x in d["coches"])

    # Columnas del detalle
    cols = [("TRABAJO", 176, "l"), ("CANT.", 38, "c"), ("MATERIAL", 0, "l"),
            ("P. UNITARIO", 66, "r"), ("SUBTOTAL", 72, "r")]
    cols[2] = ("MATERIAL", aw - sum(w for _, w, _ in cols), "l")
    xs, x = [], M
    for _, w, _ in cols:
        xs.append(x)
        x += w

    def tx(k, y, t, f, s, col=TINTA):
        nombre, w, al = cols[k]
        xx = xs[k] + 7 if al == "l" else (xs[k] + w / 2 if al == "c" else xs[k] + w - 7)
        L.texto(xx, y, t, f, s, col, align=al)

    def pie():
        L.linea(M, H - 30, W - M, H - 30, LINEA, 0.5)
        L.texto(M, H - 18, f"Pedido de fondos · OT N° {d['numero']} · {coches_txt}", "I5", 7.5, GRIS)
        L.texto(W - M, H - 18, f"Hoja {pag[0]} de {total_pag} · impresa el {impresa}{pie_quien}",
                "I5", 7.5, GRIS, align="r")

    def cabecera_tabla(y):
        L.rect(M, y, aw, 20, fill=NAVY, r=3)
        for k, (t, w, al) in enumerate(cols):
            tx(k, y + 13.5, t, "I6", 6.8, white)
        return y + 20

    def hoja_nueva(con_tabla=True):
        pie()
        c.showPage()
        pag[0] += 1
        y = L.encabezado(W, M, "PEDIDO DE FONDOS", "LA SANTANIANA S.A.  ·  DE COMPRAS A TESORERÍA",
                         "OT N°", str(d["numero"]), logo)
        if not con_tabla:
            return y
        L.texto(M, y + 4, "DETALLE (SIGUE)", "I7", 8, NAVY)
        return cabecera_tabla(y + 12)

    def banda_coche(y, co, sigue=False):
        L.rect(M, y, aw, 24, fill=AZUL_F)
        L.rect(M, y, 4, 24, fill=AZUL)
        nom = _nombre_coche(co) + (" (sigue)" if sigue else "")
        L.texto(M + 12, y + 16, nom, "D8", 11.5, NAVY)
        w = L.ancho(nom, "D8", 11.5)
        resto = " · ".join(x for x in (co.get("patente") if co.get("n_interno") else "",
                                       " ".join(y_ for y_ in (co.get("marca"), co.get("modelo")) if y_),
                                       f"{_miles(co['km'])} km" if co.get("km") else "") if x)
        if resto:
            L.texto(M + 18 + w, y + 15.5, L.cortar(resto, "I5", 8, aw - w - 190), "I5", 8, GRIS)
        if not sigue:
            L.texto(W - M - 8, y + 15.5, "Subtotal " + _gs(co["subtotal"]), "D8", 10.5, NAVY, align="r")
        return y + 24

    # ── Hoja 1 ──────────────────────────────────────────────────────────
    y = L.encabezado(W, M, "PEDIDO DE FONDOS", "LA SANTANIANA S.A.  ·  DE COMPRAS A TESORERÍA",
                     "OT N°", str(d["numero"]), logo)

    # Datos en cajas
    celdas = [("Fecha del pedido", _dmy(d["fecha_pedido"]), ""),
              ("OT abierta el", _dmy(d["fecha_apertura"]), d.get("procedencia") or ""),
              ("Coche" + ("s" if len(d["coches"]) > 1 else ""), coches_txt, ""),
              ("Trabajos · materiales", f"{d['trabajos']} · {d['materiales']}", "")]
    anchos = [0.20, 0.22, 0.36, 0.22]
    x = M
    for (etq, val, sub), a in zip(celdas, anchos):
        w = aw * a - (6 if a != anchos[-1] else 0)
        L.rect(x, y, w, 40, stroke=NAVY, lw=1)
        L.texto(x + 8, y + 13, etq.upper(), "I6", 6.6, GRIS)
        L.texto(x + 8, y + 31 - (5 if sub else 0), L.cortar(val or "—", "D8", 12.5, w - 16), "D8", 12.5, TINTA)
        if sub:
            L.texto(x + 8, y + 36, L.cortar(sub, "I4", 6.8, w - 16), "I4", 6.8, GRIS)
        x += aw * a
    y += 50

    nombres = [g["proveedor"] for g in d.get("por_proveedor") or [] if not g["deposito"] and not g["sin"]]
    if nombres:
        L.texto(M, y + 2, "PROVEEDORES:", "I7", 8.2, NAVY)
        wp = L.ancho("PROVEEDORES:", "I7", 8.2) + 6
        L.texto(M + wp, y + 2, L.cortar(" · ".join(nombres), "I6", 8.2, aw - wp), "I6", 8.2, TINTA)
    else:
        L.texto(M, y + 2, "PROVEEDOR: todavía no se eligió", "I6", 8.2, GRIS)
    y += 16

    # El monto, grande, en números y en letras
    alto = 66
    L.rect(M, y, aw, alto, fill=NAVY, r=7)
    L.texto(M + 16, y + 17, "MONTO SOLICITADO A TESORERÍA", "I6", 7.2, CELESTE)
    L.texto(M + 16, y + 44, _gs(d["total"]), "D9", 28, white)
    letras = "Son guaraníes: " + en_letras(d["total"]) + "."
    L.texto(M + 16, y + 58, L.cortar(letras, "I5", 8, aw * 0.62),
            "I5", 8, CELESTE)
    if d.get("firmado"):
        # Lo que Tesorería ya habilitó y lo que espera fondos
        xr = M + aw * 0.64
        wr = aw * 0.36 - 14
        for k, (t, v, col, fondo) in enumerate((("HABILITADO", d["habilitado"], VERDE, VERDE_F),
                                                ("ESPERA FONDOS", d["espera"], AMBAR, AMBAR_F))):
            yy = y + 9 + k * 25
            L.rect(xr, yy, wr, 22, fill=fondo, r=4)
            L.texto(xr + 8, yy + 14.5, t, "I7", 7, col)
            L.texto(xr + wr - 8, yy + 15.5, _gs(v), "D8", 11.5, col, align="r")
    elif len(d["coches"]) > 1:
        # El reparto por coche
        xr = M + aw * 0.64
        wr = aw * 0.36 - 14
        filas = d["coches"][:4]
        paso = min(13, (alto - 14) / max(1, len(filas)))
        for k, co in enumerate(filas):
            yy = y + 16 + k * paso
            L.texto(xr, yy, _nombre_coche(co).title(), "I5", 8, CELESTE)
            L.texto(xr + wr, yy, _gs(co["subtotal"]), "D6", 10, white, align="r")
    y += alto + 14

    if d.get("nota"):
        L.texto(M, y + 2, L.cortar("Nota de Compras: " + d["nota"], "I5", 8.5, aw), "I5", 8.5, GRIS)
        y += 14

    L.texto(M, y + 4, "DETALLE POR COCHE Y TRABAJO", "I7", 8, NAVY)
    y = cabecera_tabla(y + 12)

    if not any(co["trabajos"] for co in d["coches"]):
        L.texto(M + aw / 2, y + 22, "Todavía no hay materiales ni precios cargados en esta OT.",
                "I5", 9.5, GRIS, align="c")
        y += 40

    # ── Detalle ─────────────────────────────────────────────────────────
    for co in d["coches"]:
        if not co["trabajos"]:
            continue
        if y + 24 + 22 > LIMITE:
            y = hoja_nueva()
        y = banda_coche(y, co)
        for n_t, t in enumerate(co["trabajos"], 1):
            mats = t["materiales"] or [None]
            lineas = _partir(L, f"{n_t}. {t['descripcion']}", "I6", 8.4, cols[0][1] - 14)
            extra = []
            if t.get("tecnico"):
                extra.append(("Mecánico: " + apellido_primero_varios(t["tecnico"]), GRIS2))
            if t.get("estado_pago") == "espera":
                extra.append(("ESPERA FONDOS", AMBAR))
            elif t.get("estado_pago") == "habilitado":
                extra.append(("HABILITADO", VERDE))
            alto_trab = 8 + len(lineas) * 10.5 + len(extra) * 9.5 + 4
            def _prov_de(m):
                if m is None:
                    return (t.get("proveedor") or "").strip()
                if (m.get("origen") or "") == "deposito":
                    return "Sale del depósito"
                return (m.get("proveedor") or "").strip() or (t.get("proveedor") or "").strip()
            altos = [27 if _prov_de(m) else 17 for m in mats]
            alto_mats = sum(altos)
            alto_bloque = max(alto_trab, alto_mats) + (16 if len(mats) > 1 else 0)
            if y + alto_bloque > LIMITE:
                y = hoja_nueva()
                y = banda_coche(y, co, sigue=True)
            fondo = CEBRA if n_t % 2 == 0 else white
            L.rect(M, y, aw, alto_bloque, fill=fondo)
            if t.get("estado_pago") == "espera":
                L.rect(M, y, 3, alto_bloque, fill=AMBAR)
            # El trabajo, a la izquierda
            yy = y + 12
            for ln in lineas:
                L.texto(xs[0] + 7, yy, ln, "I6", 8.4, TINTA)
                yy += 10.5
            for txt, col in extra:
                L.texto(xs[0] + 7, yy, L.cortar(txt, "I5", 7, cols[0][1] - 14), "I5" if col == GRIS2 else "I7", 7, col)
                yy += 9.5
            # Sus materiales, uno por renglón
            ym = y
            for m, h in zip(mats, altos):
                prov = _prov_de(m)
                if m is None:
                    tx(1, ym + 12, "—", "I5", 8.4, GRIS2)
                    tx(2, ym + 12, L.cortar("Precio del trabajo (sin materiales anotados)", "I4", 7.7, cols[2][1] - 14), "I4", 7.7, GRIS)
                    tx(3, ym + 12, "—", "I5", 8.4, GRIS2)
                    tx(4, ym + 12, _gs(t["precio"]) if t["precio"] else "—", "D6", 10, TINTA)
                else:
                    tx(1, ym + 12, _cant(m.get("cantidad")), "D6", 10, TINTA)
                    tx(2, ym + 12, L.cortar(m.get("descripcion") or "", "I5", 8.1, cols[2][1] - 14), "I5", 8.1, TINTA)
                    pu = float(m.get("precio_unit") or 0)
                    tx(3, ym + 12, _miles(pu) if pu else "—", "I5", 8.4, TINTA if pu else GRIS2)
                    tx(4, ym + 12, _miles(m.get("subtotal")) if pu else "—", "D6", 10, TINTA if pu else GRIS2)
                if prov:
                    dep = prov == "Sale del depósito"
                    tx(2, ym + 22.5, L.cortar(prov if dep else "Proveedor: " + prov, "I6", 7.2, cols[2][1] - 14),
                       "I6", 7.2, VERDE if dep else AZUL)
                ym += h
                if m is not None and ym < y + alto_mats:
                    L.linea(xs[1] + 4, ym - 2, M + aw - 4, ym - 2, LINEA, 0.4)
            if len(mats) > 1:
                # Total del trabajo cuando tiene varios materiales
                L.linea(xs[3] + 4, y + alto_bloque - 16, M + aw - 4, y + alto_bloque - 16, GRIS2, 0.5)
                tx(3, y + alto_bloque - 5, "Total trabajo", "I6", 7, GRIS)
                tx(4, y + alto_bloque - 4.5, _miles(t["precio"]) if t["precio"] else "—", "D8", 10.5, NAVY)
            L.linea(M, y + alto_bloque, M + aw, y + alto_bloque, LINEA, 0.7)
            y += alto_bloque
        y += 6

    # Total final
    if y + 30 > LIMITE:
        y = hoja_nueva(con_tabla=False)
    L.rect(M, y, aw, 28, fill=SUAVE)
    L.linea(M, y, M + aw, y, NAVY, 1.2)
    L.texto(M + 10, y + 18, "TOTAL SOLICITADO", "I7", 8.5, NAVY)
    L.texto(M + aw - 8, y + 19.5, _gs(d["total"]), "D9", 15, NAVY, align="r")
    y += 40

    # ── A quién se le paga: el total por proveedor ─────────────────────
    grupos = [g for g in d.get("por_proveedor") or [] if g["total"] > 0 or g["deposito"]]
    if grupos:
        alto_res = 22 + 16 * len(grupos)
        if y + alto_res > LIMITE:
            y = hoja_nueva(con_tabla=False)
        L.texto(M, y + 4, "TOTAL POR PROVEEDOR", "I7", 8, NAVY)
        y += 12
        wcol = aw * 0.62
        for k, g in enumerate(grupos):
            if k % 2 == 0:
                L.rect(M, y, wcol, 16, fill=CEBRA)
            col = VERDE if g["deposito"] else (GRIS if g["sin"] else TINTA)
            L.texto(M + 8, y + 11, L.cortar(g["proveedor"], "I6", 8.4, wcol - 170), "I6", 8.4, col)
            L.texto(M + wcol - 110, y + 11, f"{g['renglones']} renglón" + ("" if g["renglones"] == 1 else "es"), "I5", 7.6, GRIS, align="r")
            L.texto(M + wcol - 8, y + 11.5, "no se paga" if g["deposito"] else _gs(g["total"]), "D6", 10,
                    VERDE if g["deposito"] else NAVY, align="r")
            y += 16
        L.linea(M, y, M + wcol, y, LINEA, 0.6)
        y += 14

    # ── Firmas y aclaración (abajo de la última hoja) ─────────────────────
    alto_firmas = 112
    if y + alto_firmas > LIMITE:
        y = hoja_nueva(con_tabla=False)
    yf = max(y + 44, LIMITE - alto_firmas + 44)
    tercio = (aw - 28) / 3
    for k, (rol, quien) in enumerate((("SOLICITA", "Compras"), ("AUTORIZA", "Director General"),
                                      ("ENTREGA LOS FONDOS", "Tesorería"))):
        x = M + k * (tercio + 14)
        L.linea(x, yf, x + tercio, yf, NAVY, 0.9)
        L.texto(x + tercio / 2, yf + 12, rol, "I7", 7.2, NAVY, align="c")
        L.texto(x + tercio / 2, yf + 23, quien, "I5", 8, GRIS, align="c")
        L.texto(x, yf + 40, "Aclaración:", "I4", 7, GRIS2)
        L.linea(x + 42, yf + 41, x + tercio, yf + 41, LINEA, 0.6)
        L.texto(x, yf + 55, "Fecha:", "I4", 7, GRIS2)
        L.texto(x + 42, yf + 55, "____ / ____ / ________", "I4", 7, GRIS2)
    L.texto(M, yf - 32, "Con la firma del Director General, Tesorería entrega los fondos. "
                        "Guardar este pedido junto con las facturas para la rendición.", "I5", 7.8, GRIS)
    pie()
    c.showPage()
    return pag[0]


def pdf_pedido_fondos(d):
    # Primero se cuenta cuántas hojas salen (para poner "Hoja 1 de N")
    prueba = canvas.Canvas(io.BytesIO(), pagesize=A4)
    total = _dibujar(d, prueba, 0)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Pedido de fondos - OT {d['numero']}")
    c.setAuthor("La Santaniana")
    _dibujar(d, c, total)
    c.save()
    buf.seek(0)
    return buf
