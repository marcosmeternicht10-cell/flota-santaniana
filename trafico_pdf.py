"""
trafico_pdf.py — El PDF del tráfico del día (La Santaniana)

Un solo archivo para mandar al grupo, pensado para leerse en el celular:

  1. Las salidas del día. Arriba la fecha bien grande, la versión y los
     números del día. Si es la versión 2 o más, las filas que cambiaron
     salen marcadas en rojo. Después cada corredor con sus idas a la
     izquierda y sus regresos a la derecha, como siempre: hora, tramo (con
     las siglas tal cual), coche y los dos tripulantes.
  2. Buscá tu nombre: todos los tripulantes por orden alfabético con lo que
     les toca, para que cada chofer se encuentre en dos segundos.
  3. Los coches del día: qué hace cada coche y dónde amanece mañana.

Las fuentes (Barlow Semi Condensed e Inter, las mismas del sistema) van
dentro del PDF desde static/fonts. Si faltan, se usa Helvetica y el PDF
sale igual.
"""

import io
import os
import unicodedata
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
LIMITE = 800                 # hasta dónde baja el contenido (medido desde arriba)

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


def sin_tildes(s):
    t = unicodedata.normalize("NFD", str(s or ""))
    return "".join(ch for ch in t if unicodedata.category(ch) != "Mn")


def es_coche(c):
    return str(c or "").strip().isdigit()


# ════════════════════════════════════════════════════════════════════════════
# PRIMITIVAS DE DIBUJO (todo medido desde arriba de la hoja)
# ════════════════════════════════════════════════════════════════════════════

class Hoja:
    def __init__(self, info, total):
        _fuentes()
        self.info = info
        self.total = total
        self.buf = io.BytesIO()
        self.c = rl_canvas.Canvas(self.buf, pagesize=A4)
        self.c.setTitle(f"Tráfico {info['nombre_dia']}")
        self.c.setAuthor("La Santaniana")
        self.c.setSubject(info.get("titulo") or "Horarios nacionales")
        self.c.setCreator("Sistema de gestión de flota — La Santaniana")
        self.pagina = 0
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
            c.drawString(x, H - y, t, charSpace=cs)
        else:
            c.drawString(x, H - y, t)
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
        c.line(x, H - y, x + w - cabeza * 0.8, H - y)
        p = c.beginPath()
        p.moveTo(x + w, H - y)
        p.lineTo(x + w - cabeza * 1.5, H - y + cabeza)
        p.lineTo(x + w - cabeza * 1.5, H - y - cabeza)
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
            c.roundRect(x, H - y - h, w, h, r, fill=1 if fill is not None else 0,
                        stroke=1 if stroke is not None else 0)
        else:
            c.rect(x, H - y - h, w, h, fill=1 if fill is not None else 0,
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
        c.line(x1, H - y1, x2, H - y2)
        if dash:
            c.setDash()
        c.setLineCap(0)

    def punto(self, x, y, r, fill, anillo=None, anillo_w=1.2):
        c = self.c
        if anillo is not None:
            c.setFillColor(anillo)
            c.circle(x, H - y, r + anillo_w, fill=1, stroke=0)
        c.setFillColor(fill)
        c.circle(x, H - y, r, fill=1, stroke=0)

    def poligono(self, puntos, fill, alpha=None):
        c = self.c
        p = c.beginPath()
        p.moveTo(puntos[0][0], H - puntos[0][1])
        for x, y in puntos[1:]:
            p.lineTo(x, H - y)
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

    # ── páginas ──
    def nueva_pagina(self):
        if self.pagina:
            self.pie()
            self.c.showPage()
        self.pagina += 1
        if self.info.get("borrador"):
            self.marca_agua()

    def marca_agua(self):
        c = self.c
        c.saveState()
        c.translate(W / 2, H / 2 - 40)
        c.rotate(32)
        c.setFillColor(NAVY)
        c.setFillAlpha(0.045)
        c.setFont(F["D9"], 118)
        c.drawCentredString(0, 0, "BORRADOR")
        c.restoreState()

    def pie(self):
        info = self.info
        self.linea(M, 812, W - M, 812, LINEA, 0.6)
        izq = f"LA SANTANIANA  ·  {info.get('titulo') or 'HORARIOS NACIONALES'}  ·  {info['nombre_dia']}"
        self.texto(M, 824, izq, "I6", 6.2, GRIS2, cs=0.6)
        v = "BORRADOR" if info.get("borrador") else f"VERSIÓN {info.get('version') or 1}"
        der = f"{v}  ·  PÁGINA {self.pagina} DE {self.total or '—'}"
        self.texto(W - M, 824, der, "I6", 6.2, GRIS2, cs=0.6, align="r")

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
            self.c.drawImage(self.logo, x + (lado - w) / 2, H - y - lado + (lado - h) / 2, w, h, mask="auto")

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

    def encabezado_chico(self):
        """Hojas que siguen: una banda finita con lo justo."""
        info = self.info
        alto = 44
        self.rect(0, 0, W, alto, fill=NAVY)
        self.poligono([(W - 170, 0), (W - 110, 0), (W - 136, alto), (W - 196, alto)], NAVY3, alpha=0.25)
        self.tile_logo(M, 8, 28, 6)
        self.texto(M + 38, 21, "LA SANTANIANA", "I6", 5.8, CELESTE, cs=1.8)
        titulo, s = self.ajustar(info.get("titulo") or "HORARIOS NACIONALES", "D9", 14, 240, 10)
        self.texto(M + 38, 35, titulo, "D9", s, white, cs=0.2)
        self.texto(W - M, 23, info["nombre_dia"], "D8", 12, white, cs=0.6, align="r")
        self.texto(W - M, 35, self.version_txt(), "I6", 6, AMBAR_V if info.get("borrador") else CELESTE,
                   cs=1.2, align="r")
        self.franja(alto, 3)
        return alto + 3

    def titulo_seccion(self, y, titulo, bajada):
        self.texto(M, y + 20, titulo, "D9", 21, NAVY, cs=0.4)
        self.texto(M, y + 33, bajada, "I4", 8, GRIS)
        return y + 46


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
    info = h.info
    bloques = info["dia"]["bloques"]
    cambiadas = info.get("cambiadas") or set()
    h.nueva_pagina()
    y = h.encabezado_grande()
    y = _encabezado_columnas(h, y + 12)

    def salto():
        h.nueva_pagina()
        yy = h.encabezado_chico()
        return _encabezado_columnas(h, yy + 12)

    if not bloques:
        h.texto(W / 2, y + 60, "Todavía no hay salidas cargadas.", "I5", 10, GRIS, align="c")
        return
    for b in bloques:
        ida, reg = b.get("ida") or [], b.get("regreso") or []
        filas = max(len(ida), len(reg), 1)
        alto_res = 18 if _tiene_reserva(b) else 0
        alto = CAB_CORR + filas * FILA + alto_res
        # El corredor entero en la hoja; si es más largo que una hoja, que arranque con al menos 3 filas
        necesita = alto if alto < LIMITE - 120 else CAB_CORR + 3 * FILA
        if y + necesita > LIMITE:
            y = salto()
        y = _encabezado_corredor(h, y, b)
        for i in range(filas):
            if y + FILA > LIMITE:
                y = salto()
                y = _encabezado_corredor(h, y, b, sigue=True)
            for lado, lista in (("ida", ida), ("regreso", reg)):
                if i < len(lista):
                    s = lista[i]
                    _celda(h, _col_x(lado), y, s, lado, s.get("id") in cambiadas, i,
                           primera=(i == 0), ultima=(i == len(lista) - 1))
            y += FILA
        if alto_res:
            if y + alto_res > LIMITE:
                y = salto()
            y = _reserva(h, y, b)
        y += ENTRE_CORR


# ════════════════════════════════════════════════════════════════════════════
# HOJA 2: BUSCÁ TU NOMBRE
# ════════════════════════════════════════════════════════════════════════════

def _todas(info):
    for b in info["dia"]["bloques"]:
        for lado in ("ida", "regreso"):
            for s in b.get(lado) or []:
                yield b, lado, s


def hoja_tripulantes(h):
    info = h.info
    gente = {}
    for b, lado, s in _todas(info):
        for t in (s.get("trip1"), s.get("trip2")):
            t = (t or "").strip()
            if t:
                gente.setdefault(t, []).append((s.get("hora") or "99:99", lado, s))
    if not gente:
        return
    nombres = sorted(gente, key=lambda n: sin_tildes(n))

    h.nueva_pagina()
    y0 = h.encabezado_chico()
    y0 = h.titulo_seccion(y0 + 16, "BUSCÁ TU NOMBRE",
                          f"Los {len(nombres)} tripulantes del día por orden alfabético, con sus salidas.")
    RENG = 12.2
    col, y = 0, y0
    letra_ant = None
    x_tramos = CW - 132

    for n in nombres:
        legs = sorted(gente[n], key=lambda x: x[0])
        alto = len(legs) * RENG + 5
        letra = sin_tildes(n)[:1]
        nueva_letra = letra != letra_ant
        if y + alto + (6 if nueva_letra else 0) > LIMITE:
            col += 1
            y = y0
            if col > 1:
                h.nueva_pagina()
                y0 = h.encabezado_chico() + 16
                y, col = y0, 0
            nueva_letra = True
        x0 = M + col * (CW + GAP)
        if nueva_letra:
            if y > y0:
                y += 5
                h.linea(x0, y - 2.5, x0 + CW, y - 2.5, LINEA, 0.6)
            h.texto(x0, y + 10.6, letra, "D9", 12.5, ROJO)
            letra_ant = letra
        # Nombre y puntitos hasta las salidas
        nn, ss = h.ajustar(n, "D8", 9.4, x_tramos - 22, 7.2)
        wn = h.texto(x0 + 15, y + 10, nn, "D8", ss, NAVY)
        h.linea(x0 + 15 + wn + 4, y + 8.6, x0 + x_tramos - 6, y + 8.6, GRIS2, 0.8, dash=([0.1, 2.4], 0), cap=1)
        yy = y
        for hora, lado, s in legs:
            xl = x0 + x_tramos
            h.punto(xl + 2, yy + 6.9, 1.9, AZUL if lado == "ida" else ROJO)
            h.texto(xl + 7.5, yy + 10, s.get("hora") or "--:--", "D8", 9.2, TINTA)
            base = s.get("destino_base") or s.get("destino") or ""
            extra = " ".join(s.get("destino_extras") or [])
            tr = f"{base} {extra}".strip()
            t, z = h.ajustar(tr, "D5", 8.2, 132 - 32 - 36, 6.3)
            h.texto(xl + 33, yy + 9.8, t, "D5", z, TINTA)
            h.chapa(x0 + CW - 31, yy + 1.6, 31, 11, s.get("coche"), 8)
            yy += RENG
        y += alto


# ════════════════════════════════════════════════════════════════════════════
# HOJA 3: LOS COCHES DEL DÍA
# ════════════════════════════════════════════════════════════════════════════

def hoja_coches(h):
    info = h.info
    flota = info.get("flota") or {}
    coches = {}
    for b, lado, s in _todas(info):
        c = str(s.get("coche") or "").strip()
        if es_coche(c):
            coches.setdefault(c, []).append((s.get("hora") or "99:99", lado, s))
    if not coches:
        return
    orden = sorted(coches, key=lambda c: (len(c), c))

    h.nueva_pagina()
    y0 = h.encabezado_chico()
    y = h.titulo_seccion(y0 + 16, "COCHES DEL DÍA",
                         f"Qué hace cada uno de los {len(orden)} coches y dónde amanece mañana.")
    COLS, G = 5, 7
    cw = (W - 2 * M - G * (COLS - 1)) / COLS
    RENG = 11.4
    terminan = {}

    def alto_tarjeta(c):
        return 30 + len(coches[c]) * RENG + 21

    fila = [orden[i:i + COLS] for i in range(0, len(orden), COLS)]
    for grupo in fila:
        alto = max(alto_tarjeta(c) for c in grupo)
        if y + alto > LIMITE:
            h.nueva_pagina()
            y = h.encabezado_chico() + 16
        for k, c in enumerate(grupo):
            x = M + k * (cw + G)
            legs = sorted(coches[c], key=lambda l: l[0])
            h.rect(x, y, cw, alto, fill=FONDO, r=5)
            h.chapa(x + 7, y + 7, 40, 16, c, 11)
            v = flota.get(c) or {}
            modelo = f"{v.get('marca') or ''} {v.get('modelo') or ''}".strip()
            if modelo:
                t, z = h.ajustar(modelo.upper(), "I6", 5.6, cw - 56, 4.6)
                h.texto(x + 52, y + 13.4, t, "I6", z, GRIS, cs=0.4)
            vueltas = len(legs)
            h.texto(x + 52, y + 21, f"{vueltas} SALIDA{'S' if vueltas != 1 else ''}", "I6", 5.2, GRIS2, cs=0.6)
            yy = y + 33
            for hora, lado, s in legs:
                h.punto(x + 10, yy + 4.6, 1.8, AZUL if lado == "ida" else ROJO)
                h.texto(x + 15, yy + 8, s.get("hora") or "--:--", "D8", 8.4, TINTA)
                base = s.get("destino_base") or s.get("destino") or ""
                extra = " ".join(s.get("destino_extras") or [])
                t, z = h.ajustar(f"{base} {extra}".strip(), "D5", 7.6, cw - 46, 5.8)
                h.texto(x + 40, yy + 7.9, t, "D5", z, TINTA)
                yy += RENG
            # Dónde amanece mañana: donde llega su último tramo
            ultimo = legs[-1][2]
            lugar = ultimo.get("llega") or "?"
            terminan.setdefault(lugar, []).append(c)
            h.linea(x + 7, y + alto - 19, x + cw - 7, y + alto - 19, LINEA, 0.6)
            wl = h.texto(x + 7, y + alto - 7.6, "MAÑANA EN", "I6", 5.2, GRIS2, cs=0.8)
            t, z = h.ajustar(lugar, "D9", 10, cw - 14 - wl - 5, 6.5, cs=0.4)
            h.texto(x + cw - 7, y + alto - 7, t, "D9", z, ROJO if lugar != "ASU" else NAVY, align="r", cs=0.4)
        y += alto + G

    # Resumen: dónde amanecen los coches mañana (lo que necesita quien arma el
    # día siguiente). Cada lugar con sus coches, uno al lado del otro.
    lugares = sorted(terminan, key=lambda l: (l == "ASU", l))
    ancho_util = W - 2 * M - 28
    RL, CH, CG = 19, 30, 3.5          # alto de renglón, ancho de chapa, aire entre chapas
    piezas, x, renglon = [], 0, 0
    for l in lugares:
        cs = sorted(terminan[l], key=lambda c: (len(c), c))
        we = h.ancho(l, "D9", 8.6, 0.4) + 12
        w_grupo = we + 5 + len(cs) * (CH + CG)
        if x and x + w_grupo > ancho_util:
            x, renglon = 0, renglon + 1
        piezas.append(("lugar", x, renglon, l, we))
        x += we + 5
        for c in cs:
            if x + CH > ancho_util:
                x, renglon = we + 5, renglon + 1
            piezas.append(("coche", x, renglon, c, CH))
            x += CH + CG
        x += 12
    alto_res = 34 + (renglon + 1) * RL + 8
    if y + alto_res + 8 > LIMITE:
        h.nueva_pagina()
        y = h.encabezado_chico() + 16
    y += 8
    h.rect(M, y, W - 2 * M, alto_res, fill=NAVY, r=6)
    h.poligono([(W - M - 120, y), (W - M - 70, y), (W - M - 96, y + alto_res), (W - M - 146, y + alto_res)],
               NAVY3, alpha=0.3)
    wt = h.texto(M + 14, y + 19, "DÓNDE AMANECEN MAÑANA", "D9", 12, white, cs=0.9)
    h.texto(M + 14 + wt + 10, y + 18.6,
            "Para armar el tráfico de mañana: cada coche está donde terminó hoy.", "I4", 7.2, CELESTE)
    for tipo, px, rg, txt, w in piezas:
        xx, yy = M + 14 + px, y + 30 + rg * RL
        if tipo == "lugar":
            h.rect(xx, yy, w, 14, fill=ROJO if txt != "ASU" else AZUL, r=3)
            h.texto(xx + w / 2, yy + 10.1, txt, "D9", 8.6, white, align="c", cs=0.4)
        else:
            h.rect(xx, yy + 1, w, 12, fill=NAVY2, r=2.5)
            h.texto(xx + w / 2, yy + 9.9, txt, "D8", 8.3, white, align="c")


# ════════════════════════════════════════════════════════════════════════════

def _dibujar(info, total):
    h = Hoja(info, total)
    hoja_salidas(h)
    hoja_tripulantes(h)
    hoja_coches(h)
    h.pie()
    h.c.showPage()
    h.c.save()
    return h.buf.getvalue(), h.pagina


def generar_pdf_trafico(info):
    """info: lo que arma trafico.datos_para_pdf. Devuelve los bytes del PDF."""
    _, paginas = _dibujar(info, None)      # primera pasada: contar las hojas
    pdf, _ = _dibujar(info, paginas)
    return pdf
