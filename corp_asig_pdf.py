"""
corp_asig_pdf.py — La hoja de la asignación de corporativos (La Santaniana)

La misma hoja que el tráfico (banda azul con la fecha en tablillas, chapas de
los coches, la franja roja y azul), pero con los tramos de cada cliente: la
hora, el tramo, el chofer y el coche. Si el tramo está dividido, el entrante
y el saliente van uno arriba del otro. Lo que cambió desde la versión
anterior sale en rojo, y lo que falta asignar en ámbar. Dos columnas para
que se lea en el celular; si no entra, la hoja se alarga.
"""

import io

from reportlab.lib.colors import white

import trafico_pdf as T
from trafico_pdf import (Hoja, W, H, M, NAVY, AZUL, ROJO, TINTA, GRIS, GRIS2, LINEA, CEBRA, AMBAR, AMBAR_V,
                         AMBAR_F, ROJO_F, FONDO)

GAP = 14
CW = (W - 2 * M - GAP) / 2
FILA = 21            # tramo completo
FILA2 = 30           # tramo dividido (entrante y saliente)
CAB_CLI = 24
ENTRE_CLI = 8

X_HORA, X_TRAMO, X_CHOFER = 6, 46, 140
W_CHAPA = 36
X_CHAPA = CW - W_CHAPA - 4


def _x(col):
    return M if col == 0 else M + CW + GAP


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


def _alto_cliente(c):
    filas = [t for t in c["tramos"] if t["estado"] != "no_corre"]
    alto = CAB_CLI + sum(FILA2 if t["modo"] == "dividido" else FILA for t in filas)
    alto += len(c["variables"]) * FILA
    if any(t["estado"] == "no_corre" for t in c["tramos"]):
        alto += 16
    if not filas and not c["variables"]:
        alto += 18
    return alto + ENTRE_CLI


def _cab_cliente(h, x0, y, c):
    h.rect(x0, y + 8, 6.5, 6.5, fill=NAVY, r=1.2)
    w = h.texto(x0 + 11, y + 15.2, c["cliente"], "D9", 12.5, NAVY, cs=0.8)
    n = c["cuenta"]["tramos"] + len(c["variables"])
    cuenta = f"{n} TRAMO{'S' if n != 1 else ''}"
    wc = h.ancho(cuenta, "I6", 5.6, 0.8)
    h.linea(x0 + 11 + w + 8, y + 11.4, x0 + CW - wc - 8, y + 11.4, LINEA, 0.7)
    h.texto(x0 + CW, y + 13.4, cuenta, "I6", 5.6, GRIS2, cs=0.8, align="r")
    h.rect(x0, y + CAB_CLI - 3, CW, 1.2, fill=AZUL)
    return y + CAB_CLI


def _persona(h, x, y, nombre, maxw, tam=8.4):
    if not nombre:
        h.texto(x, y, "SIN ASIGNAR", "D8", 6.8, AMBAR, cs=0.6)
        return
    t, s = h.ajustar(_nombre(nombre), "D5", tam, maxw, tam * 0.78)
    h.texto(x, y, t, "D5", s, TINTA)


def _fila(h, x0, y, t, i, cambiada):
    alto = FILA2 if t["modo"] == "dividido" else FILA
    falta = t["estado"] in ("vacio", "incompleto")
    if cambiada:
        h.rect(x0, y, CW, alto, fill=ROJO_F)
        h.rect(x0, y, 2.2, alto, fill=ROJO)
    elif falta:
        h.rect(x0, y, CW, alto, fill=AMBAR_F)
    elif i % 2:
        h.rect(x0, y, CW, alto, fill=CEBRA)
    medio = y + alto / 2
    # Hora: la de entrada grande y, si tiene, la de salida abajo
    if t.get("hora"):
        if t.get("hora_fin"):
            h.texto(x0 + X_HORA, medio + 0.6, t["hora"], "D8", 11.6, TINTA)
            h.texto(x0 + X_HORA, medio + 8.4, "a " + t["hora_fin"], "I5", 6, GRIS)
        else:
            h.texto(x0 + X_HORA, medio + 4.2, t["hora"], "D8", 11.6, TINTA)
    else:
        h.texto(x0 + X_HORA, medio + 3.6, "--:--", "D8", 10.5, GRIS2)
    # Tramo
    tt, ss = h.ajustar(t.get("corto") or t["tramo"], "D6", 9.2, X_CHOFER - X_TRAMO - 6, 7)
    h.texto(x0 + X_TRAMO, medio + 3.3, tt, "D6", ss, TINTA)
    # Chofer y coche
    if t["modo"] == "dividido":
        for k, s in enumerate(t["slots"]):
            yy = y + 4 + k * 13
            h.texto(x0 + X_CHOFER, yy + 8.2, "ENT" if s["lado"] == "entrante" else "SAL", "I7", 5.4,
                    AZUL if s["lado"] == "entrante" else ROJO, cs=0.7)
            _persona(h, x0 + X_CHOFER + 17, yy + 8.6, s.get("chofer_nombre"), X_CHAPA - X_CHOFER - 22, 7.9)
            h.chapa(x0 + X_CHAPA, yy + 0.8, W_CHAPA, 11.4, s.get("coche"), 8.6)
    else:
        s = t["slots"][0]
        _persona(h, x0 + X_CHOFER, medio + 3, s.get("chofer_nombre"), X_CHAPA - X_CHOFER - 6)
        h.chapa(x0 + X_CHAPA, medio - 7, W_CHAPA, 14, s.get("coche"), 10)
    return y + alto


def _fila_variable(h, x0, y, s, i, cambiada):
    if cambiada:
        h.rect(x0, y, CW, FILA, fill=ROJO_F)
        h.rect(x0, y, 2.2, FILA, fill=ROJO)
    elif not s.get("chofer_usuario") or not s.get("coche"):
        h.rect(x0, y, CW, FILA, fill=AMBAR_F)
    elif i % 2:
        h.rect(x0, y, CW, FILA, fill=CEBRA)
    medio = y + FILA / 2
    h.texto(x0 + X_HORA, medio + 4.2, s.get("hora") or "--:--", "D8", 11.6, TINTA if s.get("hora") else GRIS2)
    w = h.chip(x0 + X_TRAMO, medio - 5, "VARIABLE", "lleno", 5.6, NAVY)
    det = s.get("detalle") or (s.get("tramo_corto") if s.get("tramo_corto") != "VARIABLE" else "")
    if det:
        tt, ss = h.ajustar(det.upper(), "D6", 8.4, X_CHOFER - X_TRAMO - w - 8, 6.4)
        h.texto(x0 + X_TRAMO + w + 3, medio + 3, tt, "D6", ss, TINTA)
    _persona(h, x0 + X_CHOFER, medio + 3, s.get("chofer_nombre"), X_CHAPA - X_CHOFER - 6)
    h.chapa(x0 + X_CHAPA, medio - 7, W_CHAPA, 14, s.get("coche"), 10)
    return y + FILA


def _bloque(h, x0, y, c, cambiadas):
    y = _cab_cliente(h, x0, y, c)
    vivos = [t for t in c["tramos"] if t["estado"] != "no_corre"]
    i = 0
    for t in vivos:
        y = _fila(h, x0, y, t, i, f"{t['cliente']}|{t['tramo']}" in cambiadas)
        i += 1
    for s in c["variables"]:
        y = _fila_variable(h, x0, y, s, i, _clave_var(s) in cambiadas)
        i += 1
    if not vivos and not c["variables"]:
        h.texto(x0 + X_HORA, y + 12, "Hoy no tiene servicios", "I5", 7, GRIS)
        y += 18
    nc = [t for t in c["tramos"] if t["estado"] == "no_corre"]
    if nc:
        txt = "NO CORREN HOY: " + " · ".join(f"{t.get('corto') or t['tramo']} {t.get('hora') or ''}".strip() for t in nc)
        tt, ss = h.ajustar(txt, "I6", 6.2, CW - 8, 5.2)
        h.texto(x0 + X_HORA, y + 11, tt, "I6", ss, GRIS, cs=0.3)
        y += 16
    return y + ENTRE_CLI


def _columnas(clientes):
    """Reparte los clientes en dos columnas lo más parejas posible (en orden)."""
    altos = [_alto_cliente(c) for c in clientes]
    if len(clientes) <= 1:
        return [clientes, []]
    mejor, corte = None, 1
    for k in range(1, len(clientes)):
        m = max(sum(altos[:k]), sum(altos[k:]))
        if mejor is None or m < mejor:
            mejor, corte = m, k
    return [clientes[:corte], clientes[corte:]]


def _cambios(h, y, info):
    cambios = info.get("cambios") or []
    if not cambios:
        return y
    tit = "CAMBIOS SIN PUBLICAR" if info.get("borrador") else f"CAMBIOS DESDE LA VERSIÓN {(info.get('version') or 2) - 1}"
    lineas = []
    for c in cambios:
        lineas += h.partir(c["txt"], "I5", 7.2, W - 2 * M - 26) or [""]
    alto = 24 + len(lineas) * 10.5
    h.rect(M, y, W - 2 * M, alto, fill=ROJO_F, r=6)
    h.rect(M, y, 3, alto, fill=ROJO)
    h.texto(M + 12, y + 15, tit, "I7", 6.6, ROJO, cs=1.1)
    yy = y + 27
    for ln in lineas:
        h.texto_flechas(M + 12, yy, ln, "I5", 7.2, TINTA)
        yy += 10.5
    return y + alto + 10


def _dibujar(info, alto):
    h = Hoja({**info, "titulo": "CORPORATIVOS", "subtitulo": "Tramos del día, choferes y coches"}, alto)
    h.c.setTitle(f"Corporativos {info['nombre_dia']}")
    h.c.setSubject("Asignación de corporativos")
    if info.get("borrador"):
        h.marca_agua()
    y = h.encabezado_grande() + 14
    clientes = [c for c in info["clientes"] if c["tramos"] or c["variables"]]
    if not clientes:
        h.texto(W / 2, y + 60, "Todavía no hay nada asignado.", "I5", 10, GRIS, align="c")
        y += 80
    else:
        cambiadas = info.get("cambiadas") or set()
        cols = _columnas(clientes)
        fines = []
        for k, grupo in enumerate(cols):
            yy = y
            for c in grupo:
                yy = _bloque(h, _x(k), yy, c, cambiadas)
            fines.append(yy)
        y = max(fines)
    y = _cambios(h, y + 4, info)
    h.pie()
    h.c.showPage()
    h.c.save()
    return h.buf.getvalue(), y


def _stats(info):
    r = info.get("resumen") or {}
    stats = [(r.get("tramos", 0) + r.get("variables", 0), "TRAMOS", white),
             (r.get("choferes", 0), "CHOFERES", white), (r.get("coches", 0), "COCHES", white)]
    falta = (r.get("sin_asignar") or 0) + (r.get("incompletos") or 0)
    if falta:
        stats.append((falta, "A COMPLETAR", AMBAR_V))
    return stats


def generar_pdf(info):
    info = {**info, "stats": _stats(info)}
    _, y = _dibujar(info, 6000)
    pdf, _ = _dibujar(info, max(H * 0.75, y + 46))
    return pdf


def generar_imagen(info, ancho_px=1654):
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
