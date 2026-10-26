"""
turismo_asig_pdf.py — La asignación de turismo para compartir (La Santaniana)

La misma cara que la hoja del tráfico y la de corporativos: banda azul con
las fechas en tablillas, las chapas de los coches y la franja roja y azul.
Sirve para mandar al grupo qué coche y qué tripulación lleva cada servicio
de turismo en las fechas que se elijan (un día, una semana…).

Cada día es un bloque con sus servicios ordenados por hora: hora, cliente,
de dónde sale y a dónde va, y a la derecha cada coche con su tripulación.
Lo que falta asignar sale en ámbar (A CONFIRMAR) y lo cancelado, apagado.
Los viajes de varios días que siguen en curso se listan al pie de cada día.

  generar_pdf(info)       una sola hoja, tan larga como haga falta
  generar_imagen(info)    la misma hoja como imagen PNG (para WhatsApp)
  datos(desde, hasta, cliente, cancelados)   arma info desde la agenda
"""

import io
from datetime import date, timedelta

from reportlab.lib.colors import white, HexColor

from trafico_pdf import (Hoja, W, H, M, NAVY, NAVY2, NAVY3, AZUL, ROJO, VERDE, CELESTE, TINTA, GRIS, GRIS2,
                         LINEA, CEBRA, AMBAR, AMBAR_V, AMBAR_F, MESES, DIAS)

AW = W - 2 * M
X_HORA = M + 10
X_SERV = M + 60
W_SERV = 262
X_ASIG = M + 334
W_CHAPA = 42
X_TRIP = X_ASIG + W_CHAPA + 8
W_TRIP = W - M - X_TRIP - 8
SUBFILA = 20
MAX_DIAS = 31

GRIS_APAG = HexColor("#AEB7C2")


def _fecha_corta(f):
    d = date.fromisoformat(f)
    return f"{d.day:02d}/{d.month:02d}"


def _dia_titulo(f):
    d = date.fromisoformat(f)
    return f"{DIAS[d.weekday()]} {d.day:02d} {MESES[d.month - 1]}"


# ════════════════════════════════════════════════════════════════════════════
# DATOS
# ════════════════════════════════════════════════════════════════════════════

def rango_ok(desde, hasta, hoy_iso):
    """Las fechas pedidas, ordenadas y con un tope de 31 días."""
    try:
        d = date.fromisoformat(str(desde)[:10])
    except Exception:
        d = date.fromisoformat(hoy_iso)
    try:
        h = date.fromisoformat(str(hasta)[:10])
    except Exception:
        h = d
    if h < d:
        d, h = h, d
    if (h - d).days >= MAX_DIAS:
        h = d + timedelta(days=MAX_DIAS - 1)
    return d.isoformat(), h.isoformat()


def datos(desde, hasta, cliente=None, cancelados=False, generado=""):
    """Lo que necesita la hoja: los días con sus servicios y los que siguen en viaje."""
    import turismo_agenda as TA
    servicios = TA.listar_servicios(desde=desde, hasta=hasta, cliente=cliente or None)
    if not cancelados:
        servicios = [s for s in servicios if s.get("estado") != "cancelado"]
    dias = TA.agrupar_por_dia(servicios, desde, hasta)
    for d in dias:
        d["servicios"].sort(key=lambda s: ((s.get("hora") or "99:99"), s.get("cliente") or ""))
    activos = [s for d in dias for s in d["servicios"] if s.get("estado") != "cancelado"]
    coches = {c["coche_interno"] for s in activos for c in (s.get("coches") or []) if c.get("coche_interno")}
    falta = sum(1 for s in activos if s.get("sin_asignar"))
    pasajeros = sum(int(s.get("pasajeros") or 0) for s in activos)
    stats = [(len(activos), "SERVICIOS", white), (len(coches), "COCHES", white)]
    if pasajeros:
        stats.append((pasajeros, "PASAJEROS", white))
    if falta:
        stats.append((falta, "A CONFIRMAR", AMBAR_V))
    rango = _fecha_corta(desde) if desde == hasta else f"DEL {_fecha_corta(desde)} AL {_fecha_corta(hasta)}"
    return {
        "desde": desde, "hasta": hasta, "cliente": cliente or "", "dias": dias, "stats": stats,
        "generado": generado, "rango": rango,
        # lo que usa la Hoja del tráfico para el título del PDF
        "nombre_dia": rango, "titulo": "TURISMO · ASIGNACIÓN", "fecha": desde,
    }


# ════════════════════════════════════════════════════════════════════════════
# DIBUJO
# ════════════════════════════════════════════════════════════════════════════

def _tablillas(h, x, y, texto, tw, th, tam):
    """Las fichas de los carteles de terminal, una por letra. Devuelve el ancho."""
    x0 = x
    for grupo in texto.split(" "):
        for ch in grupo:
            h.rect(x, y, tw, th, fill=HexColor("#0E1A28"), stroke=HexColor("#2C4766"), r=3, lw=0.5)
            h.rect(x + 0.4, y + 0.4, tw - 0.8, th / 2 - 0.4, fill=HexColor("#182A3F"), r=2.7)
            h.rect(x + 0.4, y + th / 2 - 3, tw - 0.8, 3, fill=HexColor("#182A3F"))
            h.texto(x + tw / 2, y + th / 2 + tam * 0.35, ch, "D8", tam, white, align="c")
            h.linea(x + 0.4, y + th / 2, x + tw - 0.4, y + th / 2, HexColor("#050B13"), 1.0)
            x += tw + 2.4
        x += 6
    return x - x0 - 8.4


def _ancho_tablillas(texto, tw):
    letras = len(texto.replace(" ", ""))
    grupos = len(texto.split(" "))
    return letras * tw + (letras - grupos) * 2.4 + (grupos - 1) * 8.4


def _encabezado(h, info):
    alto = 120
    h.rect(0, 0, W, alto, fill=NAVY)
    for i, (x, ancho) in enumerate([(W - 250, 46), (W - 186, 30), (W - 140, 74)]):
        h.poligono([(x + 40, 0), (x + 40 + ancho, 0), (x + ancho, alto), (x, alto)], NAVY3, alpha=0.28 - i * 0.05)
    h.tile_logo(M, 22, 52, 10)
    x = M + 64
    h.texto(x, 31, "LA SANTANIANA", "I6", 7.2, CELESTE, cs=2.4)
    titulo, s = h.ajustar("TURISMO", "D9", 25, 200, 16)
    h.texto(x, 57, titulo, "D9", s, white, cs=0.3)
    sub = "Servicios, coches y tripulación" + (f" · {info['cliente']}" if info.get("cliente") else "")
    sub, ss = h.ajustar(sub, "I4", 7.6, 200, 6.4)
    h.texto(x, 71, sub, "I4", ss, CELESTE, alpha=0.85)

    # Las fechas en tablillas: un día, o desde → hasta
    d0, d1 = date.fromisoformat(info["desde"]), date.fromisoformat(info["hasta"])
    t0 = f"{d0.day:02d} {MESES[d0.month - 1]}"
    if d0 == d1:
        tw, th, tam = 22, 32, 22.5
        total = _ancho_tablillas(t0, tw)
        h.texto(W - M, 28, DIAS[d0.weekday()], "D8", 11.5, CELESTE, cs=2.6, align="r")
        _tablillas(h, W - M - total, 35, t0, tw, th, tam)
    else:
        t1 = f"{d1.day:02d} {MESES[d1.month - 1]}"
        tw, th, tam = 16, 25, 17
        flecha = 20
        total = _ancho_tablillas(t0, tw) + flecha + _ancho_tablillas(t1, tw)
        x = W - M - total
        h.texto(W - M, 28, f"DEL {DIAS[d0.weekday()]} AL {DIAS[d1.weekday()]}", "D8", 10, CELESTE, cs=2, align="r")
        x += _tablillas(h, x, 37, t0, tw, th, tam) + 5
        h.flecha(x, 37 + th / 2, flecha - 10, CELESTE, 1.4, 2.8)
        x += flecha - 5
        _tablillas(h, x, 37, t1, tw, th, tam)

    # Los números
    x, y = M, 104
    for i, (n, etq, color) in enumerate(info["stats"]):
        if i:
            h.linea(x - 9, 92, x - 9, 106, NAVY3, 0.8)
        w = h.texto(x, y, str(n), "D9", 16, color)
        w += h.texto(x + w + 4, y - 1, etq, "I6", 6.2, CELESTE if color == white else AMBAR_V, cs=1.1) + 4
        x += w + 18
    if info.get("generado"):
        v = f"AL {info['generado']}"
        pw = h.ancho(v, "D8", 8.6, 1.2) + 16
        h.rect(W - M - pw, 88, pw, 17, fill=white, r=8.5)
        h.texto(W - M - pw / 2, 99.6, v, "D8", 8.6, NAVY, cs=1.2, align="c")
    h.franja(alto)
    return alto + 4


def _cabecera(h, y):
    h.rect(M, y, AW, 20, fill=NAVY, r=3)
    h.texto(X_HORA, y + 13.2, "HORA", "I7", 6.4, white, cs=1)
    h.texto(X_SERV, y + 13.2, "SERVICIO", "I7", 6.4, white, cs=1)
    h.texto(X_ASIG, y + 13.2, "COCHE", "I7", 6.4, white, cs=1)
    h.texto(X_TRIP, y + 13.2, "TRIPULACIÓN", "I7", 6.4, white, cs=1)
    return y + 20


def _encabezado_dia(h, y, d):
    activos = [s for s in d["servicios"] if s.get("estado") != "cancelado"]
    falta = sum(1 for s in activos if s.get("sin_asignar"))
    h.rect(M, y + 9.5, 6.5, 6.5, fill=ROJO if falta else NAVY, r=1.2)
    w = h.texto(M + 11, y + 16.6, _dia_titulo(d["fecha"]), "D9", 12, NAVY, cs=0.7)
    partes = [f"{len(activos)} SERVICIO{'S' if len(activos) != 1 else ''}"]
    if falta:
        partes.append(f"{falta} A CONFIRMAR")
    if d.get("en_viaje"):
        partes.append(f"{len(d['en_viaje'])} EN VIAJE")
    cuenta = " · ".join(partes)
    wc = h.ancho(cuenta, "I6", 5.8, 0.8)
    h.linea(M + 11 + w + 8, y + 12.8, W - M - wc - 8, y + 12.8, LINEA, 0.7)
    h.texto(W - M, y + 14.8, cuenta, "I6", 5.8, AMBAR if falta else GRIS2, cs=0.8, align="r")
    return y + 25


ESTADO_CHIP = {
    "completado": ("CUMPLIDO", "lleno", VERDE),
    "cancelado": ("CANCELADO", "lleno", GRIS2),
    "en_curso": ("EN CURSO", "lleno", AZUL),
    "confirmado": ("CONFIRMADO", "borde", AZUL),
}


def _chips(s):
    chips = []
    if s.get("dias", 1) > 1:
        chips.append((f"{s['dias']} DÍAS · HASTA {(s.get('dia_fin') or '').upper()[:3]} {_fecha_corta(s['fecha_fin'])}",
                      "lleno", NAVY))
    if s.get("pasajeros"):
        chips.append((f"{s['pasajeros']} PASAJEROS", "borde", NAVY))
    if s.get("estado") in ESTADO_CHIP:
        chips.append(ESTADO_CHIP[s["estado"]])
    return chips


def _trip_lineas(h, t, maxw):
    """La tripulación en hasta dos renglones (a veces son dos o tres nombres)."""
    t = " ".join(str(t or "").split()).upper()
    if h.ancho(t, "D5", 8.6) <= maxw:
        return [t], 8.6
    rs = h.partir(t, "D5", 7.6, maxw)
    if len(rs) <= 2:
        return rs, 7.6
    t2, s2 = h.ajustar(" ".join(rs[1:]), "D5", 7.6, maxw, 6.2)
    return [rs[0], t2], s2


def _alto_fila(h, s):
    coches = s.get("coches") or [{}]
    base = 46 if _chips(s) else 36
    alto_coches = 10
    for c in coches:
        lineas, _ = _trip_lineas(h, c.get("tripulacion") or "", W_TRIP)
        alto_coches += SUBFILA + (8 if len(lineas) > 1 else 0)
    return max(base, alto_coches)


def _fila(h, y, s, i):
    alto = _alto_fila(h, s)
    cancelado = s.get("estado") == "cancelado"
    falta = s.get("sin_asignar") and not cancelado
    if falta:
        h.rect(M, y, AW, alto, fill=AMBAR_F)
        h.rect(M, y, 2.4, alto, fill=AMBAR)
    elif i % 2:
        h.rect(M, y, AW, alto, fill=CEBRA)
    tinta = GRIS_APAG if cancelado else TINTA
    # Hora
    h.texto(X_HORA, y + 18, s.get("hora") or "--:--", "D8", 13.5, tinta if s.get("hora") else GRIS2)
    # Cliente + OT
    cli, cs = h.ajustar((s.get("cliente") or "").upper(), "D8", 11, W_SERV - 70, 8)
    w = h.texto(X_SERV, y + 16, cli, "D8", cs, tinta)
    if s.get("ot_nr"):
        ot = f"OT {s['ot_nr']}"
        if w + 6 + h.ancho_chip(ot, 5.8) <= W_SERV:
            h.chip(X_SERV + w + 6, y + 7.4, ot, "borde", 5.8, GRIS if not cancelado else GRIS_APAG)
    # Salida → destino
    if s.get("salida") or s.get("destino"):
        ruta = f"{(s.get('salida') or '?').upper()} → {(s.get('destino') or '?').upper()}"
        if h.ancho_flechas(ruta, "I5", 7.6) > W_SERV:
            sal, _ = h.ajustar((s.get("salida") or "?").upper(), "I5", 7.6, W_SERV * 0.45, 7.6)
            des, _ = h.ajustar((s.get("destino") or "?").upper(), "I5", 7.6, W_SERV * 0.45, 7.6)
            ruta = f"{sal} → {des}"
        h.texto_flechas(X_SERV, y + 28, ruta, "I5", 7.6, GRIS if not cancelado else GRIS_APAG)
    else:
        h.texto(X_SERV, y + 28, "Recorrido sin cargar", "I4", 7.4, GRIS2)
    # Chips (varios días, pasajeros, estado)
    xc = X_SERV
    for t, tipo, color in _chips(s):
        if xc + h.ancho_chip(t, 5.8) > X_SERV + W_SERV:
            break
        xc += h.chip(xc, y + 33.5, t, tipo, 5.8, color if not cancelado or t == "CANCELADO" else GRIS_APAG) + 4
    # Coches y tripulación
    yy = y + 6
    for c in (s.get("coches") or [{}]):
        coche = c.get("coche_interno") or ""
        if cancelado and not coche:
            h.texto(X_ASIG + 2, yy + 11, "—", "D6", 9, GRIS_APAG)
        else:
            h.chapa(X_ASIG, yy, W_CHAPA, 16, coche, 10.5)
        lineas, sz = _trip_lineas(h, c.get("tripulacion") or "", W_TRIP)
        if not lineas or not lineas[0]:
            if not cancelado:
                h.texto(X_TRIP, yy + 11, "A CONFIRMAR", "D8", 7, AMBAR, cs=0.6)
        else:
            for k, ln in enumerate(lineas):
                h.texto(X_TRIP, yy + (11 if len(lineas) == 1 else 7 + k * 9), ln, "D5", sz, tinta)
        yy += SUBFILA + (8 if len(lineas) > 1 else 0)
    if cancelado:
        h.linea(X_SERV, y + 13, X_SERV + min(w, W_SERV - 70), y + 13, GRIS_APAG, 0.9)
    return y + alto


def _en_viaje(h, y, lista):
    partes = []
    for s in lista:
        coches = ", ".join(c["coche_interno"] for c in (s.get("coches") or []) if c.get("coche_interno"))
        partes.append(f"{(s.get('cliente') or '').upper()} (DÍA {s.get('dia_n', 2)} DE {s.get('dias', 2)})"
                      + (f" · {coches}" if coches else ""))
    txt = "SIGUEN EN VIAJE: " + "  ·  ".join(partes)
    lineas = h.partir(txt, "I6", 6.8, AW - 20)
    alto = 8 + len(lineas) * 10
    h.rect(M, y + 2, AW, alto, fill=HexColor("#EEF3F9"), r=4)
    yy = y + 11
    for ln in lineas:
        h.texto(M + 10, yy, ln, "I6", 6.8, NAVY2, cs=0.3)
        yy += 10
    return y + alto + 4


def _pie(h, info):
    h.linea(M, h.H - 30, W - M, h.H - 30, LINEA, 0.6)
    izq = f"LA SANTANIANA  ·  TURISMO  ·  {info['rango']}" + (f"  ·  {info['cliente'].upper()}" if info.get("cliente") else "")
    h.texto(M, h.H - 18, izq, "I6", 6.2, GRIS2, cs=0.6)
    if info.get("generado"):
        h.texto(W - M, h.H - 18, f"ACTUALIZADO {info['generado']}", "I6", 6.2, GRIS2, cs=0.6, align="r")


def _dibujar(info, alto):
    h = Hoja(info, alto)
    h.c.setTitle(f"Turismo {info['rango']}")
    h.c.setSubject("Asignación de turismo: coches y tripulación")
    y = _encabezado(h, info) + 14
    dias = info["dias"]
    if not dias:
        h.texto(W / 2, y + 44, "No hay servicios de turismo en esas fechas.", "I5", 10, GRIS, align="c")
        y += 70
    else:
        y = _cabecera(h, y) + 4
        for d in dias:
            y = _encabezado_dia(h, y, d)
            for i, s in enumerate(d["servicios"]):
                y = _fila(h, y, s, i)
            if d["servicios"]:
                h.linea(M, y, M + AW, y, LINEA, 0.7)
            if d.get("en_viaje"):
                y = _en_viaje(h, y + 4, d["en_viaje"])
            y += 8
    _pie(h, info)
    h.c.showPage()
    h.c.save()
    return h.buf.getvalue(), y


def generar_pdf(info):
    """Una sola hoja del ancho de un A4 y tan larga como haga falta."""
    _, y = _dibujar(info, 14000)
    pdf, _ = _dibujar(info, max(H * 0.5, y + 46))
    return pdf


def generar_imagen(info, ancho_px=1654):
    """La misma hoja como PNG: 1654 px de ancho = A4 a 200 ppp."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(generar_pdf(info))
    try:
        imagen = pdf[0].render(scale=ancho_px / W).to_pil()
        if imagen.mode != "RGB":
            imagen = imagen.convert("RGB")
        salida = io.BytesIO()
        imagen.save(salida, format="PNG", optimize=True)
        return salida.getvalue()
    finally:
        pdf.close()
