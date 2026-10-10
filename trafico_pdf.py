"""
trafico_pdf.py — El PDF del tráfico del día (La Santaniana)

Una sola hoja para mandar al grupo, pensada para leerse en el celular: arriba
la fecha bien grande, la versión y los números del día; después cada
corredor con sus idas a la izquierda y sus regresos a la derecha, como
siempre: hora, tramo (con las siglas tal cual), coche y los dos tripulantes.
Si es la versión 2 o más, las filas que cambiaron salen marcadas en rojo.
Si el día tiene muchas salidas, la hoja se alarga (no se parte en dos ni se
achica la letra). También sale como imagen PNG (generar_imagen_trafico).

Las fuentes (Barlow Semi Condensed e Inter, las mismas del sistema) van
dentro del PDF desde static/fonts. Si faltan, se usa Helvetica y el PDF
sale igual.
"""

import io
import os
from datetime import date

from reportlab.pdfgen import canvas as rl_canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import HexColor, white
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader

W, H = A4
M = 26                       # margen a los costados
GAP = 14                     # entre la columna de idas y la de regresos
CW = (W - 2 * M - GAP) / 2   # ancho de cada columna

# ─── Colores de la marca ──────────────────────────────────────────────────
NAVY = HexColor("#1D344E")
NAVY2 = HexColor("#192B41")
NAVY3 = HexColor("#264466")
AZUL = HexColor("#1E5A96")
ROJO = HexColor("#DC2641")
CELESTE = HexColor("#8CBDEB")
VERDE = HexColor("#2F7C46")
TINTA = HexColor("#16202C")
GRIS = HexColor("#5B6B7F")
GRIS2 = HexColor("#8D99A8")
LINEA = HexColor("#E1E6ED")
FONDO = HexColor("#F4F6F9")
CEBRA = HexColor("#F7F9FB")
AMBAR = HexColor("#B26A00")
AMBAR_V = HexColor("#F5B544")
AMBAR_F = HexColor("#FFF6E0")
ROJO_F = HexColor("#FDECEF")
AZUL_T = HexColor("#A9C4E3")
ROJO_T = HexColor("#EFAEB9")

MESES = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]
DIAS = ["LUNES", "MARTES", "MIÉRCOLES", "JUEVES", "VIERNES", "SÁBADO", "DOMINGO"]

_AQUI = os.path.dirname(os.path.abspath(__file__))
_DIR_FUENTES = os.path.join(_AQUI, "static", "fonts")
_LOGO = os.path.join(_AQUI, "static", "logo.png")

# ─── Fuentes ──────────────────────────────────────────────────────────────
# D = Barlow Semi Condensed (títulos, horas, coches) · I = Inter (textos chicos)
_ARCHIVOS = {"D9": "BarlowSC-ExtraBold", "D8": "BarlowSC-Bold", "D6": "BarlowSC-SemiBold",
             "D5": "BarlowSC-Medium", "I4": "Inter-Regular", "I5": "Inter-Medium",
             "I6": "Inter-SemiBold", "I7": "Inter-Bold"}
_RESPALDO = {"D9": "Helvetica-Bold", "D8": "Helvetica-Bold", "D6": "Helvetica-Bold", "D5": "Helvetica",
             "I4": "Helvetica", "I5": "Helvetica", "I6": "Helvetica-Bold", "I7": "Helvetica-Bold"}
F = {}


def _fuentes():
    if F:
        return F
    for k, arch in _ARCHIVOS.items():
        nombre = "LS-" + arch
        try:
            if nombre not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(nombre, os.path.join(_DIR_FUENTES, arch + ".ttf")))
            F[k] = nombre
        except Exception:
            F[k] = _RESPALDO[k]
    return F


def es_coche(c):
    return str(c or "").strip().isdigit()


# ════════════════════════════════════════════════════════════════════════════
# PRIMITIVAS DE DIBUJO (todo medido desde arriba de la hoja)
# ════════════════════════════════════════════════════════════════════════════

class Hoja:
    def __init__(self, info, alto=None):
        _fuentes()
        self.info = info
        self.H = alto or H                     # el alto de la hoja: A4 o más larga si no entra
        self.buf = io.BytesIO()
        self.c = rl_canvas.Canvas(self.buf, pagesize=(W, self.H))
        self.c.setTitle(f"Tráfico {info['nombre_dia']}")
        self.c.setAuthor("La Santaniana")
        self.c.setSubject(info.get("titulo") or "Horarios nacionales")
        self.c.setCreator("Sistema de gestión de flota — La Santaniana")
        try:
            self.logo = ImageReader(_LOGO)
        except Exception:
            self.logo = None

    # ── medidas ──
    @staticmethod
    def ancho(t, f, s, cs=0):
        return pdfmetrics.stringWidth(t, F[f], s) + cs * max(0, len(t) - 1)

    def ajustar(self, t, f, s, maxw, minimo=None, cs=0):
        """El tamaño para que entre en maxw; si ni así entra, se corta con …"""
        minimo = minimo or s * 0.8
        while s > minimo and self.ancho(t, f, s, cs) > maxw:
            s = round(s - 0.2, 2)
        if self.ancho(t, f, s, cs) <= maxw:
            return t, s
        while t and self.ancho(t + "…", f, s, cs) > maxw:
            t = t[:-1]
        return t.rstrip() + "…", s

    # ── texto ──
    def texto(self, x, y, t, f, s, color=TINTA, cs=0, align="l", alpha=None):
        c = self.c
        c.setFillColor(color)
        if alpha is not None:
            c.setFillAlpha(alpha)
        w = self.ancho(t, f, s, cs)
        if align == "r":
            x -= w
        elif align == "c":
            x -= w / 2
        c.setFont(F[f], s)
        if cs:
            c.drawString(x, self.H - y, t, charSpace=cs)
        else:
            c.drawString(x, self.H - y, t)
        if alpha is not None:
            c.setFillAlpha(1)
        return w

    def flecha(self, x, y, w, color, grosor=0.9, cabeza=2.4):
        """Flecha horizontal → de x a x+w, a la altura y (centro)."""
        c = self.c
        c.setStrokeColor(color)
        c.setFillColor(color)
        c.setLineWidth(grosor)
        c.setLineCap(1)
        c.line(x, self.H - y, x + w - cabeza * 0.8, self.H - y)
        p = c.beginPath()
        p.moveTo(x + w, self.H - y)
        p.lineTo(x + w - cabeza * 1.5, self.H - y + cabeza)
        p.lineTo(x + w - cabeza * 1.5, self.H - y - cabeza)
        p.close()
        c.drawPath(p, fill=1, stroke=0)

    def rect(self, x, y, w, h, fill=None, stroke=None, r=0, lw=0.6, dash=None, alpha=None):
        c = self.c
        if fill is not None:
            c.setFillColor(fill)
        if stroke is not None:
            c.setStrokeColor(stroke)
            c.setLineWidth(lw)
        if dash:
            c.setDash(*dash)
        if alpha is not None:
            c.setFillAlpha(alpha)
        if r:
            c.roundRect(x, self.H - y - h, w, h, r, fill=1 if fill is not None else 0,
                        stroke=1 if stroke is not None else 0)
        else:
            c.rect(x, self.H - y - h, w, h, fill=1 if fill is not None else 0,
                   stroke=1 if stroke is not None else 0)
        if dash:
            c.setDash()
        if alpha is not None:
            c.setFillAlpha(1)

    def linea(self, x1, y1, x2, y2, color=LINEA, lw=0.5, dash=None, cap=0):
        c = self.c
        c.setStrokeColor(color)
        c.setLineWidth(lw)
        c.setLineCap(cap)
        if dash:
            c.setDash(*dash)
        c.line(x1, self.H - y1, x2, self.H - y2)
        if dash:
            c.setDash()
        c.setLineCap(0)

    def punto(self, x, y, r, fill, anillo=None, anillo_w=1.2):
        c = self.c
        if anillo is not None:
            c.setFillColor(anillo)
            c.circle(x, self.H - y, r + anillo_w, fill=1, stroke=0)
        c.setFillColor(fill)
        c.circle(x, self.H - y, r, fill=1, stroke=0)

    def poligono(self, puntos, fill, alpha=None):
        c = self.c
        p = c.beginPath()
        p.moveTo(puntos[0][0], self.H - puntos[0][1])
        for x, y in puntos[1:]:
            p.lineTo(x, self.H - y)
        p.close()
        c.setFillColor(fill)
        if alpha is not None:
            c.setFillAlpha(alpha)
        c.drawPath(p, fill=1, stroke=0)
        if alpha is not None:
            c.setFillAlpha(1)

    # ── piezas que se repiten ──
    def chapa(self, x, y, w, h, coche, tam=10, borde=False):
        """El número del coche como una chapa: azul oscuro con letras blancas.
        Si falta, un recuadro punteado ámbar que dice A CONFIRMAR."""
        coche = str(coche or "").strip()
        if not coche or "CONF" in coche:
            self.rect(x + 0.4, y + 0.4, w - 0.8, h - 0.8, fill=AMBAR_F, stroke=AMBAR, r=3, lw=0.7, dash=([1.6, 1.3], 0))
            t, s = self.ajustar("A CONFIRMAR", "D8", tam * 0.56, w - 4)
            self.texto(x + w / 2, y + h / 2 + s * 0.36, t, "D8", s, AMBAR, align="c")
            return
        if borde or not es_coche(coche):
            self.rect(x + 0.35, y + 0.35, w - 0.7, h - 0.7, fill=white, stroke=NAVY, r=3, lw=0.7)
            t, s = self.ajustar(coche, "D8", tam, w - 4, tam * 0.6)
            self.texto(x + w / 2, y + h / 2 + s * 0.35, t, "D8", s, NAVY, align="c")
            return
        self.rect(x, y, w, h, fill=NAVY, r=3)
        # un brillo finito arriba, como una chapa
        self.linea(x + 3, y + 1.1, x + w - 3, y + 1.1, NAVY3, 0.6)
        t, s = self.ajustar(coche, "D8", tam, w - 4, tam * 0.7)
        self.texto(x + w / 2, y + h / 2 + s * 0.35, t, "D8", s, white, align="c", cs=0.2)

    def chip(self, x, y, t, tipo="borde", tam=6.2, color=NAVY):
        """Etiqueta chica: X 25 (borde), LEITO (lleno), notas (rojo)."""
        w = self.ancho(t, "D8", tam, 0.25) + 6
        h = tam + 3.6
        if tipo == "lleno":
            self.rect(x, y, w, h, fill=color, r=2)
            self.texto(x + 3, y + h / 2 + tam * 0.36, t, "D8", tam, white, cs=0.25)
        else:
            self.rect(x + 0.3, y + 0.3, w - 0.6, h - 0.6, fill=white, stroke=color, r=2, lw=0.6)
            self.texto(x + 3, y + h / 2 + tam * 0.36, t, "D8", tam, color, cs=0.25)
        return w

    def ancho_chip(self, t, tam=6.2):
        return self.ancho(t, "D8", tam, 0.25) + 6

    def texto_flechas(self, x, y, t, f, s, color=TINTA):
        """Texto que trae → (la fuente no lo tiene): la flecha se dibuja."""
        partes = t.split("→")
        for i, p in enumerate(partes):
            p = p.strip() if i else p.rstrip()
            if i:
                x += 2.2
                self.flecha(x, y - s * 0.33, s * 0.95, color, 0.7, 1.7)
                x += s * 0.95 + 2.6
            x += self.texto(x, y, p, f, s, color)
        return x

    def ancho_flechas(self, t, f, s):
        partes = t.split("→")
        return sum(self.ancho(p.strip(), f, s) for p in partes) + (len(partes) - 1) * (s * 0.95 + 4.8)

    def partir(self, t, f, s, maxw):
        """Corta un texto en renglones que entren (las flechas cuentan)."""
        palabras = t.replace("→", " → ").split()
        renglones, actual = [], ""
        for p in palabras:
            prueba = (actual + " " + p).strip()
            if actual and self.ancho_flechas(prueba, f, s) > maxw:
                renglones.append(actual)
                actual = p
            else:
                actual = prueba
        if actual:
            renglones.append(actual)
        return renglones

    def tramo(self, x, y, base, maxw, tam=9.5, f="D6"):
        """'ASU / COP': las siglas fuertes y la barra suave."""
        t, s = self.ajustar(base, f, tam, maxw, tam * 0.75)
        if "/" not in t:
            return self.texto(x, y, t, f, s, TINTA)
        partes = [p.strip() for p in t.split("/")]
        x0 = x
        for i, p in enumerate(partes):
            if i:
                x += self.texto(x, y, " / ", f, s, GRIS2)
            x += self.texto(x, y, p, f, s, TINTA)
        return x - x0

    def ancho_tramo(self, base, tam=9.5, f="D6"):
        return self.ancho(" / ".join(p.strip() for p in base.split("/")), f, tam)

    # ── la hoja ──
    def marca_agua(self):
        c = self.c
        c.saveState()
        c.translate(W / 2, self.H / 2 - 40)
        c.rotate(32)
        c.setFillColor(NAVY)
        c.setFillAlpha(0.045)
        c.setFont(F["D9"], 118)
        c.drawCentredString(0, 0, "BORRADOR")
        c.restoreState()

    def pie(self):
        info = self.info
        self.linea(M, self.H - 30, W - M, self.H - 30, LINEA, 0.6)
        izq = f"LA SANTANIANA  ·  {info.get('titulo') or 'HORARIOS NACIONALES'}  ·  {info['nombre_dia']}"
        self.texto(M, self.H - 18, izq, "I6", 6.2, GRIS2, cs=0.6)
        v = "BORRADOR" if info.get("borrador") else f"VERSIÓN {info.get('version') or 1}"
        self.texto(W - M, self.H - 18, v, "I6", 6.2, GRIS2, cs=0.6, align="r")

    def franja(self, y, alto=4):
        """La franja roja y azul con el corte en diagonal, como el logo."""
        corte = W * 0.40
        self.poligono([(0, y), (corte + alto, y), (corte, y + alto), (0, y + alto)], ROJO)
        self.poligono([(corte + alto + 3, y), (W, y), (W, y + alto), (corte + 3, y + alto)], AZUL)

    def tile_logo(self, x, y, lado, r):
        self.rect(x, y, lado, lado, fill=white, r=r)
        if self.logo:
            iw, ih = self.logo.getSize()
            w = lado * 0.78
            h = w * ih / iw
            self.c.drawImage(self.logo, x + (lado - w) / 2, self.H - y - lado + (lado - h) / 2, w, h, mask="auto")

    def version_txt(self):
        info = self.info
        if info.get("borrador"):
            return "BORRADOR"
        return f"VERSIÓN {info.get('version') or 1}"

    def encabezado_grande(self):
        """Primera hoja: banda azul oscuro con el logo, el título, la fecha en
        tablillas (como los carteles de las terminales) y los números del día."""
        info = self.info
        d = date.fromisoformat(info["fecha"])
        alto = 120
        self.rect(0, 0, W, alto, fill=NAVY)
        # Barras en diagonal de fondo, el dibujo del logo, muy suaves
        for i, (x, ancho) in enumerate([(W - 250, 46), (W - 186, 30), (W - 140, 74)]):
            self.poligono([(x + 40, 0), (x + 40 + ancho, 0), (x + ancho, alto), (x, alto)], NAVY3, alpha=0.28 - i * 0.05)
        # Logo y título
        self.tile_logo(M, 22, 52, 10)
        x = M + 64
        self.texto(x, 31, "LA SANTANIANA", "I6", 7.2, CELESTE, cs=2.4)
        titulo, s = self.ajustar(info.get("titulo") or "HORARIOS NACIONALES", "D9", 25, 262, 16)
        self.texto(x, 57, titulo, "D9", s, white, cs=0.3)
        self.texto(x, 71, "Salidas del día, coches y tripulantes", "I4", 7.6, CELESTE, alpha=0.85)

        # Fecha en tablillas: día de la semana arriba, "14 SEP" en fichas
        dia_nombre = DIAS[d.weekday()]
        grupos = [f"{d.day:02d}", MESES[d.month - 1]]
        tw, th, tg, gg = 22, 32, 2.8, 9
        total = sum(len(g) * tw + (len(g) - 1) * tg for g in grupos) + gg * (len(grupos) - 1)
        x = W - M - total
        self.texto(W - M, 28, dia_nombre, "D8", 11.5, CELESTE, cs=2.6, align="r")
        y = 35
        for g in grupos:
            for ch in g:
                # la ficha: mitad de arriba un poco más clara, como las de los carteles
                self.rect(x, y, tw, th, fill=HexColor("#0E1A28"), stroke=HexColor("#2C4766"), r=3.2, lw=0.5)
                self.rect(x + 0.4, y + 0.4, tw - 0.8, th / 2 - 0.4, fill=HexColor("#182A3F"), r=2.9)
                self.rect(x + 0.4, y + th / 2 - 3, tw - 0.8, 3, fill=HexColor("#182A3F"))
                self.texto(x + tw / 2, y + th / 2 + 7.9, ch, "D8", 22.5, white, align="c")
                # la ranura del medio
                self.linea(x + 0.4, y + th / 2, x + tw - 0.4, y + th / 2, HexColor("#050B13"), 1.1)
                x += tw + tg
            x += gg - tg

        # Números del día
        r = info["dia"].get("resumen") or {}
        stats = [(r.get("salidas", 0), "SALIDAS", white), (r.get("coches", 0), "COCHES", white),
                 (r.get("tripulantes", 0), "TRIPULANTES", white)]
        if r.get("a_confirmar"):
            stats.append((r["a_confirmar"], "A CONFIRMAR", AMBAR_V))
        x, y = M, 104
        for i, (n, etq, color) in enumerate(stats):
            if i:
                self.linea(x - 9, 92, x - 9, 106, NAVY3, 0.8)
            w = self.texto(x, y, str(n), "D9", 16, color)
            w += self.texto(x + w + 4, y - 1, etq, "I6", 6.2, CELESTE if color == white else AMBAR_V, cs=1.1) + 4
            x += w + 18

        # Versión
        v = self.version_txt()
        if info.get("borrador"):
            fondo, tinta = AMBAR_V, NAVY2
            sub = "Todavía no se publicó" if not info.get("version") else f"Cambios sin publicar · última: versión {info['version']}"
        else:
            fondo, tinta = white, NAVY
            sub = _cuando_publico(info)
        pw = self.ancho(v, "D8", 8.6, 1.2) + 16
        self.rect(W - M - pw, 88, pw, 17, fill=fondo, r=8.5)
        self.texto(W - M - pw / 2, 99.6, v, "D8", 8.6, tinta, cs=1.2, align="c")
        if sub:
            self.texto(W - M - pw - 8, 99.4, sub, "I5", 6.4, CELESTE, align="r")
        self.franja(alto)
        return alto + 4



def _cuando_publico(info):
    p = str(info.get("publicado_el") or "")
    if len(p) < 16:
        return ""
    txt = f"Publicada el {p[8:10]}/{p[5:7]} a las {p[11:16]}"
    quien = (info.get("publicado_por") or "").strip()
    if quien:
        txt += f" · {quien.split()[0].capitalize()}"
    return txt


# ════════════════════════════════════════════════════════════════════════════
# HOJA 1: LAS SALIDAS
# ════════════════════════════════════════════════════════════════════════════

FILA = 22.5          # alto de cada fila de salidas
CAB_CORR = 23        # título del corredor
ENTRE_CORR = 7       # aire entre corredores
CAB_COLS = 27        # IDA / REGRESO arriba de todo

# Posiciones dentro de cada columna
X_PUNTO, X_HORA, X_TRAMO, X_CHAPA, W_CHAPA, X_NOMBRES = 5, 12.5, 48.5, 133, 39, 177


def _col_x(lado):
    return M if lado == "ida" else M + CW + GAP


def _encabezado_columnas(h, y):
    for lado, etq, color in (("ida", "IDA", AZUL), ("regreso", "REGRESO", ROJO)):
        x0 = _col_x(lado)
        w = h.texto(x0 + X_HORA, y + 11, etq, "D9", 11.5, color, cs=1.6)
        # IDA: sale →  ·  REGRESO: ← vuelve (dibujada al revés)
        if lado == "ida":
            h.flecha(x0 + X_HORA + w + 5, y + 7.2, 14, color, 1.1, 2.4)
        else:
            c = h.c
            c.saveState()
            c.translate(x0 + X_HORA + w + 5 + 14, 0)
            c.scale(-1, 1)
            h.flecha(0, y + 7.2, 14, color, 1.1, 2.4)
            c.restoreState()
        for etq2, dx in (("HORA", X_HORA), ("TRAMO", X_TRAMO), ("COCHE", X_CHAPA), ("TRIPULANTES", X_NOMBRES)):
            h.texto(x0 + dx, y + 21.5, etq2, "I6", 5.2, GRIS2, cs=0.9)
        h.rect(x0, y + 24.5, CW, 1.7, fill=color)
    return y + CAB_COLS


def _encabezado_corredor(h, y, b, sigue=False):
    nombre = b["nombre"] + ("  (SIGUE)" if sigue else "")
    h.rect(M, y + 7.5, 6.5, 6.5, fill=NAVY, r=1.2)
    w = h.texto(M + 11, y + 14.6, nombre, "D9", 12, NAVY, cs=0.7)
    fin_izq = M + 11 + w + 8
    # Notas de cada lado (ej: TRASBORDO BSAS en el regreso)
    if b.get("nota_ida"):
        fin_izq += h.chip(fin_izq, y + 5.6, b["nota_ida"], "borde", 6.4, ROJO) + 6
    x_der = _col_x("regreso") + X_HORA
    tope_linea = W - M
    ni, nr = len(b.get("ida") or []), len(b.get("regreso") or [])
    cuenta = f"{ni} IDA{'S' if ni != 1 else ''} · {nr} REGRESO{'S' if nr != 1 else ''}"
    wc = h.ancho(cuenta, "I6", 5.6, 0.8)
    h.linea(fin_izq, y + 10.8, tope_linea - wc - 8, y + 10.8, LINEA, 0.7)
    h.texto(W - M, y + 12.8, cuenta, "I6", 5.6, GRIS2, cs=0.8, align="r")
    if b.get("nota_regreso"):
        xr = max(x_der, fin_izq + 4)
        wch = h.ancho_chip(b["nota_regreso"], 6.4)
        h.rect(xr - 3, y + 4, wch + 6, 14, fill=white)
        h.chip(xr, y + 5.6, b["nota_regreso"], "borde", 6.4, ROJO)
    return y + CAB_CORR


def _celda(h, x0, y, s, lado, cambiada, i, primera, ultima):
    """Una salida: punto de la línea, hora, tramo, coche y tripulantes."""
    color = AZUL if lado == "ida" else ROJO
    tenue = AZUL_T if lado == "ida" else ROJO_T
    falta = not es_coche(s.get("coche")) or not (s.get("trip1") or s.get("trip2"))
    # Fondo: cambiada (rojo), a confirmar (ámbar) o cebra
    if cambiada:
        h.rect(x0, y, CW, FILA, fill=ROJO_F)
        h.rect(x0, y, 2.2, FILA, fill=ROJO)
    elif falta:
        h.rect(x0, y, CW, FILA, fill=AMBAR_F)
    elif i % 2:
        h.rect(x0, y, CW, FILA, fill=CEBRA)
    medio = y + FILA / 2
    # La línea del recorrido con su parada
    h.linea(x0 + X_PUNTO, y if not primera else medio, x0 + X_PUNTO, y + FILA if not ultima else medio, tenue, 1.4)
    if falta:
        h.punto(x0 + X_PUNTO, medio, 2.1, white, AMBAR, 1.1)
    else:
        h.punto(x0 + X_PUNTO, medio, 2.3, color, white, 1.2)

    # Hora
    hora = s.get("hora") or "--:--"
    h.texto(x0 + X_HORA, medio + 4.5, hora, "D8", 12.8, TINTA if s.get("hora") else GRIS2)

    # Tramo con lo que lo acompaña (X 25, LEITO, notas)
    base = s.get("destino_base") or s.get("destino") or ""
    extras = list(s.get("destino_extras") or [])
    if s.get("nota"):
        extras.append(s["nota"])
    maxw = X_CHAPA - X_TRAMO - 5
    w_base = min(h.ancho_tramo(base), maxw)
    w_chips = sum(h.ancho_chip(e, 5.9) + 3 for e in extras)
    if not extras:
        h.tramo(x0 + X_TRAMO, medio + 3.4, base, maxw)
    elif w_base + 4 + w_chips <= maxw:
        w = h.tramo(x0 + X_TRAMO, medio + 3.4, base, maxw)
        xc = x0 + X_TRAMO + w + 4
        for e in extras:
            xc += _chip_extra(h, xc, medio - 4.9, e) + 3
    else:
        h.tramo(x0 + X_TRAMO, y + 9.6, base, maxw, 9)
        xc = x0 + X_TRAMO
        for e in extras:
            if xc + h.ancho_chip(e, 5.9) > x0 + X_CHAPA - 3:
                break
            xc += _chip_extra(h, xc, y + 12.2, e) + 3

    # Coche
    h.chapa(x0 + X_CHAPA, medio - 7.5, W_CHAPA, 15, s.get("coche"), 10.5)

    # Tripulantes: uno arriba del otro, como en la planilla
    trips = [t for t in (s.get("trip1"), s.get("trip2")) if t]
    maxn = CW - X_NOMBRES - 3
    if len(trips) == 2:
        for k, t in enumerate(trips):
            tt, ss = h.ajustar(t, "D5", 8.1, maxn, 6.4)
            h.texto(x0 + X_NOMBRES, y + 9.4 + k * 8.9, tt, "D5", ss, TINTA)
    elif trips:
        tt, ss = h.ajustar(trips[0], "D5", 8.1, maxn, 6.4)
        h.texto(x0 + X_NOMBRES, medio + 2.9, tt, "D5", ss, TINTA)
    else:
        h.texto(x0 + X_NOMBRES, medio + 2.4, "A CONFIRMAR", "D8", 6.8, AMBAR, cs=0.6)


def _chip_extra(h, x, y, e):
    clases = ("LEITO", "SEMI CAMA", "SEMICAMA", "CAMA", "EJECUTIVO", "DIRECTO")
    if e == "REFUERZO":                          # el coche extra de la noche, que se vea
        return h.chip(x, y, e, "lleno", 5.9, ROJO)
    if e in clases:
        return h.chip(x, y, e, "lleno", 5.9, NAVY)
    if e.startswith("X "):
        return h.chip(x, y, e, "borde", 5.9, NAVY)
    return h.chip(x, y, e, "borde", 5.9, ROJO)


def _reserva(h, y, b):
    for lado in ("ida", "regreso"):
        coche, trip = b.get(f"reserva_{lado}_coche") or "", b.get(f"reserva_{lado}_trip") or ""
        if not (coche or trip):
            continue
        x0 = _col_x(lado)
        h.rect(x0, y + 1, CW, 15, fill=FONDO, r=3)
        h.texto(x0 + X_HORA, y + 11, "RESERVA", "I7", 5.8, GRIS, cs=1.1)
        if coche:
            h.chapa(x0 + X_TRAMO, y + 3, 30, 11, coche, 8, borde=True)
        if trip:
            t, s = h.ajustar(trip, "D5", 7.6, CW - X_TRAMO - 40, 6)
            h.texto(x0 + X_TRAMO + 36, y + 11, t, "D5", s, TINTA)
    return y + 18


def _tiene_reserva(b):
    return any(b.get(f"reserva_{l}_{k}") for l in ("ida", "regreso") for k in ("coche", "trip"))


def hoja_salidas(h):
    """Toda la grilla en una sola hoja. Devuelve hasta dónde llegó (desde arriba)."""
    info = h.info
    bloques = info["dia"]["bloques"]
    cambiadas = info.get("cambiadas") or set()
    y = h.encabezado_grande()
    y = _encabezado_columnas(h, y + 12)
    if not bloques:
        h.texto(W / 2, y + 60, "Todavía no hay salidas cargadas.", "I5", 10, GRIS, align="c")
        return y + 80
    for b in bloques:
        ida, reg = b.get("ida") or [], b.get("regreso") or []
        filas = max(len(ida), len(reg), 1)
        y = _encabezado_corredor(h, y, b)
        for i in range(filas):
            for lado, lista in (("ida", ida), ("regreso", reg)):
                if i < len(lista):
                    s = lista[i]
                    _celda(h, _col_x(lado), y, s, lado, s.get("id") in cambiadas, i,
                           primera=(i == 0), ultima=(i == len(lista) - 1))
            y += FILA
        if _tiene_reserva(b):
            y = _reserva(h, y, b)
        y += ENTRE_CORR
    return y


# ════════════════════════════════════════════════════════════════════════════

def _dibujar(info, alto):
    h = Hoja(info, alto)
    if info.get("borrador"):
        h.marca_agua()
    y = hoja_salidas(h)
    h.pie()
    h.c.showPage()
    h.c.save()
    return h.buf.getvalue(), y


def generar_pdf_trafico(info):
    """info: lo que arma trafico.datos_para_pdf. Devuelve los bytes del PDF:
    una sola hoja, del ancho de un A4 y tan larga como haga falta (si el día
    tiene muchas salidas no se parte en dos ni se achica la letra)."""
    _, y = _dibujar(info, 6000)                 # primera pasada: medir
    pdf, _ = _dibujar(info, max(H, y + 46))
    return pdf


def generar_imagen_trafico(info, ancho_px=1654):
    """La misma hoja como imagen PNG, para mandarla al grupo y que se vea sin
    abrir nada. 1654 px de ancho = un A4 a 200 ppp: nítida en el celular."""
    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(generar_pdf_trafico(info))
    try:
        hoja = pdf[0]
        imagen = hoja.render(scale=ancho_px / W).to_pil()
        if imagen.mode != "RGB":
            imagen = imagen.convert("RGB")
        salida = io.BytesIO()
        imagen.save(salida, format="PNG", optimize=True)
        return salida.getvalue()
    finally:
        pdf.close()
