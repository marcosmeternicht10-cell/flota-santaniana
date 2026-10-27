"""
corp_asig_pdf.py — La hoja de la asignación de corporativos (La Santaniana)

Una hoja por empresa (ADM, Cervepar, Ball, Lasca…), con la misma cara que el
tráfico: banda azul con la fecha en tablillas, chapas de los coches, la
franja roja y azul.

Cada tramo es un renglón con dos columnas: la ENTRADA y la SALIDA, cada una
con su hora, su chofer y su coche, porque muchas veces el entrante lo hace
uno y el saliente otro. Lo que cambió desde la versión anterior sale en rojo
y lo que falta asignar en ámbar.

  generar_pdf(info)       la hoja de la empresa de info["cliente"]; sin
                          empresa, todas, una hoja cada una, en un PDF
  generar_imagen(info)    la misma hoja como imagen (para el grupo)
"""

import io

from reportlab.lib.colors import white

from trafico_pdf import (Hoja, W, H, M, NAVY, AZUL, ROJO, TINTA, GRIS, GRIS2, LINEA, CEBRA, AMBAR, AMBAR_V,
                         AMBAR_F, ROJO_F)

AW = W - 2 * M
W_TRAMO = 158
W_MITAD = (AW - W_TRAMO) / 2
X_TRAMO = M
X_ENT = M + W_TRAMO
X_SAL = X_ENT + W_MITAD
FILA = 24
CAB = 20
W_HORA = 34
W_CHAPA = 40


def _nombre(n):
    """'PEREZ, WALTER' → 'WALTER PEREZ', como en la hoja del tráfico."""
    s = str(n or "").strip()
    if "," in s:
        ap, no = s.split(",", 1)
        s = f"{no.strip()} {ap.strip()}"
    return s.upper()


def _clave_var(s):
    i = str(s.get("id") or "")
    return i if i.startswith("var|") else f"var|{i}"


def _mitades(t):
    """La entrada y la salida del tramo. Un tramo completo es el mismo chofer
    y el mismo coche en las dos."""
    if t.get("modo") == "dividido":
        por = {s["lado"]: s for s in t["slots"]}
        return [por.get("entrante") or {}, por.get("saliente") or {}]
    s = t["slots"][0] if t.get("slots") else {}
    return [s, s]


def _mitad(h, x, y, hora, s, solo_raya=False):
    """Una celda: la hora, el chofer y la chapa del coche."""
    medio = y + FILA / 2
    if solo_raya:
        h.texto(x + 10, medio + 3, "—", "D6", 9, GRIS2)
        return
    if hora:
        h.texto(x + 8, medio + 3.6, hora, "D8", 10, TINTA)
    else:
        h.texto(x + 8, medio + 3.2, "--:--", "D8", 9, GRIS2)
    xn = x + 8 + W_HORA
    maxw = W_MITAD - W_HORA - W_CHAPA - 22
    if s.get("chofer_nombre"):
        t, sz = h.ajustar(_nombre(s["chofer_nombre"]), "D5", 8.8, maxw, 6.6)
        h.texto(xn, medio + 3.1, t, "D5", sz, TINTA)
    else:
        h.texto(xn, medio + 2.6, "SIN ASIGNAR", "D8", 7, AMBAR, cs=0.6)
    h.chapa(x + W_MITAD - W_CHAPA - 6, medio - 7, W_CHAPA, 14, s.get("coche"), 10)


def _fondo(h, y, alto, i, cambiada, falta):
    if cambiada:
        h.rect(M, y, AW, alto, fill=ROJO_F)
        h.rect(M, y, 2.4, alto, fill=ROJO)
    elif falta:
        h.rect(M, y, AW, alto, fill=AMBAR_F)
    elif i % 2:
        h.rect(M, y, AW, alto, fill=CEBRA)


def _fila_tramo(h, y, t, i, cambiada):
    ent, sal = _mitades(t)
    falta = t["estado"] in ("vacio", "incompleto")
    _fondo(h, y, FILA, i, cambiada, falta)
    medio = y + FILA / 2
    tt, ss = h.ajustar(t.get("corto") or t["tramo"], "D6", 9.6, W_TRAMO - 14, 7)
    h.texto(X_TRAMO + 8, medio + 3.4, tt, "D6", ss, TINTA)
    _mitad(h, X_ENT, y, t.get("hora"), ent)
    _mitad(h, X_SAL, y, t.get("hora_fin") or t.get("hora"), sal)
    h.linea(X_ENT, y + 4, X_ENT, y + FILA - 4, LINEA, 0.6)
    h.linea(X_SAL, y + 4, X_SAL, y + FILA - 4, LINEA, 0.6)
    return y + FILA


def _fila_variable(h, y, s, i, cambiada):
    _fondo(h, y, FILA, i, cambiada, not s.get("chofer_usuario") or not s.get("coche"))
    medio = y + FILA / 2
    w = h.chip(X_TRAMO + 8, medio - 5, "VARIABLE", "lleno", 5.6, NAVY)
    det = s.get("detalle") or (s.get("tramo_corto") if s.get("tramo_corto") != "VARIABLE" else "")
    if det:
        tt, ss = h.ajustar(det.upper(), "D6", 8.6, W_TRAMO - w - 18, 6.4)
        h.texto(X_TRAMO + 8 + w + 4, medio + 3, tt, "D6", ss, TINTA)
    _mitad(h, X_ENT, y, s.get("hora"), s)
    _mitad(h, X_SAL, y, "", s, solo_raya=True)
    h.linea(X_ENT, y + 4, X_ENT, y + FILA - 4, LINEA, 0.6)
    h.linea(X_SAL, y + 4, X_SAL, y + FILA - 4, LINEA, 0.6)
    return y + FILA


def _cabecera(h, y):
    h.rect(M, y, AW, CAB, fill=NAVY, r=3)
    h.texto(X_TRAMO + 8, y + 13.2, "TRAMO", "I7", 6.4, white, cs=1)
    for x, t, col in ((X_ENT, "ENTRADA", AZUL), (X_SAL, "SALIDA", ROJO)):
        h.rect(x + 8, y + 7.2, 5, 5, fill=col, r=1)
        h.texto(x + 17, y + 13.2, t, "I7", 6.4, white, cs=1)
        h.texto(x + W_MITAD - 8, y + 13.2, "CHOFER · COCHE", "I6", 5.4, white, cs=0.6, align="r", alpha=0.6)
    return y + CAB


def _cambios(h, y, info):
    cambios = info.get("cambios") or []
    if not cambios:
        return y
    tit = "CAMBIOS SIN PUBLICAR" if info.get("borrador") else f"CAMBIOS DESDE LA VERSIÓN {(info.get('version') or 2) - 1}"
    lineas = []
    for c in cambios:
        lineas += h.partir(c["txt"], "I5", 7.4, AW - 26) or [""]
    alto = 24 + len(lineas) * 10.8
    h.rect(M, y, AW, alto, fill=ROJO_F, r=6)
    h.rect(M, y, 3, alto, fill=ROJO)
    h.texto(M + 12, y + 15, tit, "I7", 6.6, ROJO, cs=1.1)
    yy = y + 27
    for ln in lineas:
        h.texto_flechas(M + 12, yy, ln, "I5", 7.4, TINTA)
        yy += 10.8
    return y + alto + 10


def _stats(c):
    vivos = [t for t in c["tramos"] if t["estado"] != "no_corre"]
    mitades = [s for t in vivos for s in _mitades(t)] + list(c["variables"])
    choferes = {s.get("chofer_usuario") for s in mitades if s.get("chofer_usuario")}
    coches = {str(s.get("coche")).strip().upper() for s in mitades if s.get("coche")}
    falta = len([t for t in vivos if t["estado"] in ("vacio", "incompleto")]) + \
        len([s for s in c["variables"] if not s.get("chofer_usuario") or not s.get("coche")])
    stats = [(len(vivos) + len(c["variables"]), "TRAMOS", white), (len(choferes), "CHOFERES", white),
             (len(coches), "COCHES", white)]
    if falta:
        stats.append((falta, "A COMPLETAR", AMBAR_V))
    return stats


def _dibujar(info, c, alto):
    datos = {**info, "titulo": f"CORPORATIVOS · {c['cliente']}",
             "subtitulo": "Entrada y salida de cada tramo · choferes y coches", "stats": _stats(c)}
    h = Hoja(datos, alto)
    h.c.setTitle(f"Corporativos {c['cliente']} {info['nombre_dia']}")
    h.c.setSubject(f"Asignación de corporativos · {c['cliente']}")
    if info.get("borrador"):
        h.marca_agua()
    y = h.encabezado_grande() + 14
    cambiadas = info.get("cambiadas") or set()
    vivos = [t for t in c["tramos"] if t["estado"] != "no_corre"]
    if not vivos and not c["variables"]:
        h.texto(W / 2, y + 40, f"{c['cliente']} no tiene servicios este día.", "I5", 10, GRIS, align="c")
        y += 64
    else:
        y = _cabecera(h, y)
        i = 0
        for t in vivos:
            y = _fila_tramo(h, y, t, i, f"{t['cliente']}|{t['tramo']}" in cambiadas)
            i += 1
        for s in c["variables"]:
            y = _fila_variable(h, y, s, i, _clave_var(s) in cambiadas)
            i += 1
        h.linea(M, y, M + AW, y, LINEA, 0.7)
        y += 6
    # Solo se avisa de los que suelen correr ese día y no corren (un feriado,
    # por ejemplo); los quitados porque no se hacen ese día no hacen falta
    nc = [t for t in c["tramos"] if t["estado"] == "no_corre" and t.get("esperado", True)]
    if nc:
        txt = "NO CORREN ESTE DÍA: " + " · ".join(f"{t.get('corto') or t['tramo']} {t.get('hora') or ''}".strip() for t in nc)
        for ln in h.partir(txt, "I6", 6.6, AW - 8):
            h.texto(M + 8, y + 11, ln, "I6", 6.6, GRIS, cs=0.3)
            y += 10
        y += 6
    y = _cambios(h, y + 6, info)
    h.pie()
    h.c.showPage()
    h.c.save()
    return h.buf.getvalue(), y


def _pdf_empresa(info, c):
    _, y = _dibujar(info, c, 6000)
    pdf, _ = _dibujar(info, c, max(H * 0.5, y + 46))
    return pdf


def _con_algo(info):
    """Las empresas que tienen algo ese día (con todo vacío, la primera)."""
    cs = [c for c in info["clientes"] if c["tramos"] or c["variables"]]
    return cs or info["clientes"][:1]


def generar_pdf(info):
    hojas = [_pdf_empresa(info, c) for c in _con_algo(info)]
    if len(hojas) == 1:
        return hojas[0]
    import pypdfium2 as pdfium
    todo = pdfium.PdfDocument.new()
    try:
        for b in hojas:
            todo.import_pages(pdfium.PdfDocument(b))
        salida = io.BytesIO()
        todo.save(salida)
        return salida.getvalue()
    finally:
        todo.close()


def generar_imagen(info, ancho_px=1654):
    """La hoja como imagen. Si son varias empresas, una debajo de la otra."""
    import pypdfium2 as pdfium
    from PIL import Image
    imagenes = []
    for c in _con_algo(info):
        pdf = pdfium.PdfDocument(_pdf_empresa(info, c))
        try:
            im = pdf[0].render(scale=ancho_px / W).to_pil()
            imagenes.append(im.convert("RGB") if im.mode != "RGB" else im)
        finally:
            pdf.close()
    if len(imagenes) == 1:
        final = imagenes[0]
    else:
        final = Image.new("RGB", (max(i.width for i in imagenes), sum(i.height for i in imagenes)), "white")
        y = 0
        for im in imagenes:
            final.paste(im, (0, y))
            y += im.height
    salida = io.BytesIO()
    final.save(salida, format="PNG", optimize=True)
    return salida.getvalue()
