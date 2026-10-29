"""
cajas_pdf.py — PDF de las cajas (La Santaniana)

  pdf_cierre(d)        el cierre del día: saldos, arqueo de billetes, cada
                       movimiento y las firmas (cajero, quien controla).
  pdf_comprobante(m)   un movimiento: el comprobante interno con el detalle,
                       el IVA separado y la firma de quien recibe / entrega.
"""

import io

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import white

import trafico_pdf
from rend_comb_pdf import (_Lienzo, _logo, _miles, _dmy, _ahora_txt,
                           NAVY, AZUL, ROJO, TINTA, GRIS, GRIS2, LINEA, SUAVE, CEBRA,
                           VERDE, VERDE_F, AZUL_F, AMBAR, AMBAR_F, ROJO_F)
from tesoreria_pdf import en_letras

MEDIOS = {"efectivo": "Efectivo", "transferencia": "Transf.", "cheque": "Cheque", "tarjeta": "Tarjeta", "vale": "Vale"}
DOCS = {"factura": "Factura", "ticket": "Ticket", "autofactura": "Autofactura", "nota_credito": "N. crédito",
        "recibo": "Recibo", "boleta": "Boleta", "interno": "Interno"}


def _gs(v):
    return "Gs. " + _miles(round(float(v or 0)))


def _pie(L, W, M, H, txt, pag, total):
    L.linea(M, H - 30, W - M, H - 30)
    L.texto(M, H - 19, txt, "I4", 7, GRIS2)
    L.texto(W - M, H - 19, f"Hoja {pag} de {total}", "I5", 7, GRIS2, "r")


def _firmas(L, W, M, y, quienes):
    aw = W - 2 * M
    n = len(quienes)
    w = (aw - (n - 1) * 24) / n
    for i, (rol, nombre) in enumerate(quienes):
        x = M + i * (w + 24)
        L.linea(x, y + 34, x + w, y + 34, TINTA, 0.8)
        L.texto(x + w / 2, y + 46, rol, "I6", 8, TINTA, "c")
        if nombre:
            L.texto(x + w / 2, y + 57, L.cortar(nombre, "I4", 7.5, w), "I4", 7.5, GRIS, "c")
    return y + 64


# ════════════════════════════════════════════════════════════════════════════
# CIERRE DEL DÍA
# ════════════════════════════════════════════════════════════════════════════

def _dibujar_cierre(d, c, total_pag):
    F = trafico_pdf._fuentes()
    W, H = A4
    M = 34
    aw = W - 2 * M
    L = _Lienzo(c, H, F)
    logo = _logo()
    caja = d["caja"]
    movs = d["movs"]
    impresa = _ahora_txt()
    pag = 1
    fecha_txt = _dmy(d["fecha"]).replace("/", "/")
    sub = (f"{caja['nombre']} · {caja.get('sucursal') or ''} · "
           + (f"movimientos desde el {_dmy(d['desde'])} hasta el {_dmy(d['fecha'])}" if d.get("desde") else f"hasta el {_dmy(d['fecha'])}"))
    y = L.encabezado(W, M, "Cierre de caja", sub, "CIERRE AL", f"{d['fecha'][8:10]}/{d['fecha'][5:7]}/{d['fecha'][:4]}", logo)

    # ── Cuatro cajas: saldo anterior, ingresos, egresos, saldo final
    w4 = (aw - 3 * 8) / 4
    datos = [("Saldo anterior", d["saldo_anterior"], TINTA, SUAVE),
             ("Ingresos", d["ingresos"], VERDE, VERDE_F),
             ("Egresos", d["egresos"], ROJO, ROJO_F),
             ("Saldo final", d["saldo_final"], white, NAVY)]
    for i, (t, v, col, fondo) in enumerate(datos):
        x = M + i * (w4 + 8)
        L.rect(x, y, w4, 48, fill=fondo, r=6)
        L.texto(x + 10, y + 15, t.upper(), "I6", 7, GRIS if fondo is not NAVY else white)
        L.texto(x + 10, y + 37, _gs(v), "D8", 15, col)
    y += 62

    # ── Arqueo del efectivo
    arq = d.get("arqueo") or {}
    billetes = arq.get("billetes") or {}
    dif = float(d.get("diferencia") or 0)
    alto_arq = 26 + 13 * max(3, len(billetes) + (1 if arq.get("otros") else 0)) + 10
    L.rect(M, y, aw, alto_arq, stroke=LINEA, r=6)
    L.texto(M + 12, y + 17, "ARQUEO DEL EFECTIVO", "I7", 8, NAVY)
    yy = y + 32
    if billetes or arq.get("otros"):
        for b, n in sorted(billetes.items(), key=lambda x: -int(x[0])):
            L.texto(M + 12, yy, f"{n} × {_miles(int(b))}", "I5", 8.5, TINTA)
            L.texto(M + 190, yy, _miles(int(b) * n), "I5", 8.5, TINTA, "r")
            yy += 13
        if arq.get("otros"):
            L.texto(M + 12, yy, "Monedas / otros", "I5", 8.5, TINTA)
            L.texto(M + 190, yy, _miles(arq["otros"]), "I5", 8.5, TINTA, "r")
    else:
        L.texto(M + 12, yy, "Se anotó el total contado, sin el detalle de billetes.", "I4", 8.5, GRIS)
    xr = M + aw / 2 + 10
    filas = [("Efectivo que dice el sistema", d["efectivo_final"], TINTA),
             ("Efectivo contado", d["contado"], TINTA),
             ("Diferencia", dif, VERDE if dif == 0 else (AMBAR if dif > 0 else ROJO))]
    yy = y + 32
    for t, v, col in filas:
        L.texto(xr, yy, t, "I5" if t != "Diferencia" else "I7", 9, TINTA)
        txt = ("OK, cuadra" if t == "Diferencia" and v == 0 else
               (("+" if v > 0 else "−") + _gs(abs(v)) if t == "Diferencia" else _gs(v)))
        L.texto(M + aw - 12, yy, txt, "D8" if t == "Diferencia" else "I6", 11 if t == "Diferencia" else 9, col, "r")
        yy += 16
    y += alto_arq + 10

    if d.get("nota"):
        lineas = _partir(L, d["nota"], "I4", 8.5, aw - 24)[:6]
        h = 22 + 12 * len(lineas)
        L.rect(M, y, aw, h, fill=AMBAR_F, r=6)
        L.texto(M + 12, y + 15, "NOTA DEL CIERRE", "I7", 7.5, AMBAR)
        for i, ln in enumerate(lineas):
            L.texto(M + 12, y + 28 + 12 * i, ln, "I4", 8.5, TINTA)
        y += h + 10

    # ── Movimientos
    cols = [("N°", 24, "l"), ("FECHA", 32, "l"), ("PROVEEDOR / CLIENTE", 120, "l"), ("CONCEPTO", 0, "l"),
            ("COMPROB.", 86, "l"), ("MEDIO", 44, "l"), ("INGRESO", 58, "r"), ("EGRESO", 58, "r")]
    fijo = sum(w for _, w, _ in cols)
    cols[3] = ("CONCEPTO", aw - fijo, "l")

    def cabecera(y):
        L.rect(M, y, aw, 18, fill=NAVY)
        x = M
        for t, w, al in cols:
            L.texto(x + (w - 6 if al == "r" else 6), y + 12, t, "I7", 6.8, white, al)
            x += w
        return y + 18

    L.texto(M, y + 10, f"MOVIMIENTOS ({len(movs)})", "I7", 8, NAVY)
    y = cabecera(y + 16)
    limite = H - 150
    for i, m in enumerate(movs):
        if y > limite:
            _pie(L, W, M, H, f"La Santaniana · {caja['nombre']} · impreso {impresa}", pag, total_pag)
            c.showPage()
            pag += 1
            y = cabecera(M + 10)
        if i % 2:
            L.rect(M, y, aw, 16, fill=CEBRA)
        x = M
        ing = m["tipo"] == "ingreso"
        vals = [str(m["numero"]), _dmy(m["fecha_oper"])[:5], m["contraparte"] or "—", ", ".join(m.get("conceptos") or []),
                (DOCS.get(m["doc_tipo"], "") + " " + (m["doc_numero"] or "")[-11:]).strip(),
                MEDIOS.get(m["medio"], m["medio"]),
                _miles(m["total_gs"]) if ing else "", "" if ing else _miles(m["total_gs"])]
        for (t, w, al), v in zip(cols, vals):
            col = VERDE if (t == "INGRESO" and v) else (ROJO if (t == "EGRESO" and v) else TINTA)
            L.texto(x + (w - 6 if al == "r" else 6), y + 11, L.cortar(v, "I4", 7.6, w - 10), "I4", 7.6, col, al)
            x += w
        y += 16
    L.linea(M, y, M + aw, y, NAVY, 0.8)
    L.texto(M + aw - 64, y + 12, _miles(d["ingresos"]), "I7", 8, VERDE, "r")
    L.texto(M + aw - 6, y + 12, _miles(d["egresos"]), "I7", 8, ROJO, "r")
    y += 24
    if not movs:
        L.texto(M + aw / 2, y, "No hubo movimientos en este período.", "I4", 9, GRIS, "c")
        y += 16

    if y > H - 140:
        _pie(L, W, M, H, f"La Santaniana · {caja['nombre']} · impreso {impresa}", pag, total_pag)
        c.showPage()
        pag += 1
        y = M + 10
    y = max(y + 10, H - 140)
    _firmas(L, W, M, y, [("Cerró la caja", d.get("cerrado_por") or ""), ("Controló", ""), ("Tesorería", "")])
    _pie(L, W, M, H, f"La Santaniana · {caja['nombre']} · cerrado {d.get('cerrado_el', '')[:16].replace('T', ' ')} · impreso {impresa}",
         pag, total_pag)
    return pag


def _partir(L, texto, f, s, maxw):
    out = []
    for parrafo in str(texto or "").split("\n"):
        linea = ""
        for p in parrafo.split(" "):
            prueba = (linea + " " + p).strip()
            if L.ancho(prueba, f, s) <= maxw:
                linea = prueba
            else:
                if linea:
                    out.append(linea)
                linea = p
        out.append(linea)
    return out


def pdf_cierre(d):
    prueba = canvas.Canvas(io.BytesIO(), pagesize=A4)
    total = _dibujar_cierre(d, prueba, 0)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Cierre {d['caja']['nombre']} {d['fecha']}")
    c.setAuthor("La Santaniana")
    _dibujar_cierre(d, c, total)
    c.save()
    buf.seek(0)
    return buf


# ════════════════════════════════════════════════════════════════════════════
# UN MOVIMIENTO (comprobante interno)
# ════════════════════════════════════════════════════════════════════════════

def pdf_comprobante(m):
    F = trafico_pdf._fuentes()
    W, H = A4
    M = 34
    aw = W - 2 * M
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Movimiento {m['numero']} - {m['caja_nombre']}")
    c.setAuthor("La Santaniana")
    L = _Lienzo(c, H, F)
    ing = m["tipo"] == "ingreso"
    y = L.encabezado(W, M, "Ingreso de caja" if ing else "Egreso de caja",
                     f"{m['caja_nombre']} · {'crédito' if ing else 'débito'} varios · operación del {_dmy(m['fecha_oper'])}",
                     "MOVIMIENTO N°", str(m["numero"]), _logo())
    if m["estado"] != "vigente":
        L.rect(M, y, aw, 26, fill=ROJO_F, r=6)
        L.texto(M + 12, y + 17, f"ANULADO — {m.get('anulado_motivo') or ''}", "I7", 9, ROJO)
        y += 34

    def campo(x, y, w, etq, val):
        L.texto(x, y, etq.upper(), "I6", 6.6, GRIS)
        L.texto(x, y + 13, L.cortar(val or "—", "I5", 9.5, w - 6), "I5", 9.5, TINTA)

    w3 = aw / 3
    campo(M, y + 6, w3 * 2, "Proveedor" if not ing else "Cliente / de quién", m["contraparte"])
    campo(M + w3 * 2, y + 6, w3, "RUC / CI", m["ruc"])
    campo(M, y + 36, w3, "Comprobante", (DOCS.get(m["doc_tipo"], "") + " " + (m["doc_numero"] or "")).strip())
    campo(M + w3, y + 36, w3, "Timbrado", (m["timbrado"] or "") + (f" · vence {_dmy(m['timbrado_vence'])}" if m.get("timbrado_vence") else ""))
    campo(M + w3 * 2, y + 36, w3, "Fecha de la factura", _dmy(m["fecha_emision"]))
    campo(M, y + 66, w3, "Medio de pago", MEDIOS.get(m["medio"], m["medio"]) + (f" · {m['medio_detalle']}" if m.get("medio_detalle") else ""))
    campo(M + w3, y + 66, w3, "Moneda", m["moneda"] + (f" · cotización {_miles(m['cotizacion'], 2)}" if m["moneda"] != "PYG" else ""))
    campo(M + w3 * 2, y + 66, w3, "Empleado", m.get("empleado"))
    y += 100

    cols = [("CONCEPTO", 0, "l"), ("IVA", 50, "c"), ("EXENTO", 70, "r"), ("GRAV. 5 %", 70, "r"), ("GRAV. 10 %", 74, "r")]
    fijo = sum(w for _, w, _ in cols)
    cols[0] = ("CONCEPTO", aw - fijo, "l")
    L.rect(M, y, aw, 18, fill=NAVY)
    x = M
    for t, w, al in cols:
        L.texto(x + (w - 6 if al == "r" else (w / 2 if al == "c" else 6)), y + 12, t, "I7", 6.8, white, al)
        x += w
    y += 18
    for i, ln in enumerate(m["detalle"]):
        h = 26 if ln.get("detalle") else 18
        if i % 2:
            L.rect(M, y, aw, h, fill=CEBRA)
        L.texto(M + 6, y + 12, L.cortar(ln["concepto"], "I6", 8.5, cols[0][1] - 10), "I6", 8.5, TINTA)
        if ln.get("detalle"):
            L.texto(M + 6, y + 22, L.cortar(ln["detalle"], "I4", 7.2, cols[0][1] - 10), "I4", 7.2, GRIS)
        x = M + cols[0][1]
        vals = [{"10": "10 %", "5": "5 %"}.get(ln["tipo_iva"], "Exenta"),
                _miles(ln["exento"]) if ln["exento"] else "", _miles(ln["grav5"]) if ln["grav5"] else "",
                _miles(ln["grav10"]) if ln["grav10"] else ""]
        for (t, w, al), v in zip(cols[1:], vals):
            L.texto(x + (w - 6 if al == "r" else w / 2), y + 12, v, "I5", 8.5, TINTA, al)
            x += w
        y += h
    L.linea(M, y, M + aw, y, NAVY, 0.8)
    y += 8
    # Totales
    xr = M + aw
    for t, v in (("IVA 5 %", m["iva5"]), ("IVA 10 %", m["iva10"]), ("Total IVA", (m["iva5"] or 0) + (m["iva10"] or 0))):
        L.texto(xr - 120, y + 10, t, "I5", 8.5, GRIS, "r")
        L.texto(xr - 6, y + 10, _miles(v), "I6", 8.5, TINTA, "r")
        y += 14
    y += 4
    L.rect(M, y, aw, 40, fill=NAVY, r=6)
    L.texto(M + 12, y + 16, "TOTAL", "I6", 7.5, white)
    simbolo = "Gs." if m["moneda"] == "PYG" else m["moneda"]
    L.texto(xr - 12, y + 28, f"{simbolo} {_miles(m['total'], 0 if m['moneda'] == 'PYG' else 2)}", "D9", 19, white, "r")
    if m["moneda"] == "PYG":
        L.texto(M + 12, y + 30, L.cortar("Son guaraníes " + en_letras(m["total"]), "I4", 8, aw * 0.6), "I4", 8, white)
    else:
        L.texto(M + 12, y + 30, f"Equivale a {_gs(m['total_gs'])}", "I4", 8, white)
    y += 52
    if m.get("observacion"):
        lineas = _partir(L, m["observacion"], "I4", 8.5, aw - 24)[:8]
        h = 22 + 12 * len(lineas)
        L.rect(M, y, aw, h, stroke=LINEA, r=6)
        L.texto(M + 12, y + 15, "OBSERVACIÓN", "I7", 7.5, NAVY)
        for i, ln in enumerate(lineas):
            L.texto(M + 12, y + 28 + 12 * i, ln, "I4", 8.5, TINTA)
        y += h + 10
    marcas = []
    if m.get("no_imputa"):
        marcas.append("No imputa")
    else:
        if m.get("imputa_iva"):
            marcas.append("Imputa IVA")
        if m.get("imputa_ire"):
            marcas.append("Imputa IRE")
        if m.get("imputa_irp"):
            marcas.append("Imputa IRP-RSP")
    L.texto(M, y + 6, "RG 90: " + (", ".join(marcas) or "—") + f" · {len(m.get('archivos') or [])} archivo(s) adjunto(s)",
            "I4", 7.5, GRIS)
    _firmas(L, W, M, y + 40, [("Entregó" if not ing else "Recibió", m.get("creado_por") or ""),
                                            ("Recibió" if not ing else "Entregó", m.get("contraparte") or ""),
                                            ("Autorizó", "")])
    _pie(L, W, M, H, f"La Santaniana · {m['caja_nombre']} · cargado por {m.get('creado_por') or ''} el "
                     f"{(m.get('creado_el') or '')[:16].replace('T', ' ')} · impreso {_ahora_txt()}", 1, 1)
    c.save()
    buf.seek(0)
    return buf
