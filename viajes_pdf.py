"""
viajes_pdf.py — Viajes de los choferes de internacional en el mes (La Santaniana)

Una hoja A4 (o más, si hay muchos choferes) con la misma cara que el resto de
los PDF del sistema: cuántos viajes lleva cada chofer en el mes, del que más al
que menos, contra el tope de 8 (un viaje es la ida y la vuelta).

  generar(datos)    datos = trafico.resumen_viajes(mes)
"""

from reportlab.lib.colors import white, HexColor

from trafico_pdf import Hoja, W, H, NAVY, NAVY3, AZUL, ROJO, TINTA, GRIS, GRIS2, LINEA, CEBRA, AMBAR, AMBAR_F, ROJO_F
from hora_local import ahora_iso

M = 36
PIE = 34
FILA = 27
CELESTE = HexColor("#A9C4E3")
PROG = HexColor("#9DB8D9")
ROJO_CLARO = HexColor("#F2A7AE")
GRIS_CAJA = HexColor("#E5E7EB")
VERDE_F = HexColor("#E7F4EA")

# Columnas: (título, x, ancho, alineación)
COLS = [("#", M, 18, "l"), ("CHOFER", M + 18, 150, "l"), ("IDAS", M + 168, 32, "c"),
        ("REGRESOS", M + 200, 48, "c"), ("VIAJES DEL MES", M + 252, 136, "l"), ("TOTAL", M + 388, 32, "c")]
X_ESTADO = M + 428


class Hojas:
    def __init__(self, d):
        self.d = d
        self.h = Hoja({"nombre_dia": d["mes_txt"], "titulo": "Viajes de los choferes"})
        self.h.c.setTitle(f"Viajes de los choferes, {d['mes_txt']}")
        self.h.c.setSubject("Tráfico internacional: viajes de cada chofer en el mes")
        self.pagina = 1
        self.y = 0

    def pie(self):
        h = self.h
        h.linea(M, H - PIE + 8, W - M, H - PIE + 8, LINEA, 0.6)
        h.texto(M, H - PIE + 20, f"LA SANTANIANA  ·  TRÁFICO INTERNACIONAL  ·  VIAJES DE {self.d['mes_txt'].upper()}",
                "D6", 7, GRIS2, cs=0.6)
        h.texto(W - M, H - PIE + 20, f"HOJA {self.pagina}", "D8", 7, GRIS2, cs=0.6, align="r")

    def encabezado(self):
        h, d = self.h, self.d
        alto = 118
        h.rect(0, 0, W, alto, fill=NAVY)
        for i, (x, ancho) in enumerate([(W - 230, 44), (W - 170, 28), (W - 128, 70)]):
            h.poligono([(x + 40, 0), (x + 40 + ancho, 0), (x + ancho, alto), (x, alto)], NAVY3, alpha=0.28 - i * 0.05)
        h.tile_logo(M, 24, 46, 9)
        h.texto(M + 60, 36, "LA SANTANIANA  ·  TRÁFICO INTERNACIONAL", "D8", 8.4, CELESTE, cs=1.2)
        h.texto(M + 60, 63, "VIAJES DE LOS CHOFERES", "D9", 24, white, cs=0.3)
        h.texto(M + 60, 80, f"El tope es {d['tope']} viajes por mes. Un viaje es la ida y la vuelta.", "I5", 9, HexColor("#C9D7E8"))
        h.texto(W - M, 44, d["mes_txt"].upper(), "D9", 20, white, cs=0.6, align="r")
        # Números
        stats = [(len(d["choferes"]), "CHOFERES", white)]
        if d["pasados"]:
            stats.append((d["pasados"], "PASAN EL TOPE", ROJO_CLARO))
        if d["en_tope"]:
            stats.append((d["en_tope"], "EN EL TOPE", HexColor("#F5B544")))
        x = W - M
        for n, etq, color in reversed(stats):
            w2 = h.ancho(etq, "I6", 6.4, 1.1)
            h.texto(x, 100, etq, "I6", 6.4, color if color != white else CELESTE, cs=1.1, align="r")
            w1 = h.ancho(str(n), "D9", 17)
            h.texto(x - w2 - 5, 101, str(n), "D9", 17, color, align="r")
            x -= w1 + w2 + 22
        h.franja(alto, 4)
        self.y = alto + 26

    def cabecera_tabla(self):
        h = self.h
        for t, x, w, al in COLS:
            xx = x + (w / 2 if al == "c" else 0)
            h.texto(xx, self.y, t, "D8", 7.2, GRIS, cs=0.8, align="c" if al == "c" else "l")
        h.texto(X_ESTADO, self.y, "ESTADO", "D8", 7.2, GRIS, cs=0.8)
        h.linea(M, self.y + 6, W - M, self.y + 6, LINEA, 0.8)
        self.y += 12

    def nueva_hoja(self):
        self.pie()
        self.h.c.showPage()
        self.pagina += 1
        self.h.franja(0, 4)
        self.y = 34
        self.cabecera_tabla()

    def fila(self, i, c):
        h, tope = self.h, self.d["tope"]
        if self.y + FILA > H - PIE - 40:
            self.nueva_hoja()
        y = self.y
        pasado = c["viajes"] > tope
        if pasado:
            h.rect(M - 6, y, W - 2 * M + 12, FILA, fill=ROJO_F, r=4)
        elif i % 2:
            h.rect(M - 6, y, W - 2 * M + 12, FILA, fill=CEBRA, r=4)
        base = y + FILA / 2 + 3.4
        h.texto(COLS[0][1], base, str(i + 1), "D8", 9, GRIS2)
        nombre, s = h.ajustar(c["chofer"], "D8", 10, COLS[1][2] - 6, 7.5)
        h.texto(COLS[1][1], base, nombre, "D8", s, TINTA)
        h.texto(COLS[2][1] + COLS[2][2] / 2, base, str(c["idas"]), "I5", 9.5, TINTA, align="c")
        h.texto(COLS[3][1] + COLS[3][2] / 2, base, str(c["regresos"]), "I5", 9.5, TINTA, align="c")
        # Barrita: una caja por viaje (lleno = ya hecho, claro = programado, rojo = pasado del tope)
        n = max(tope, c["viajes"])
        lado, gap = (9, 2.6) if n <= 10 else (7, 2) if n <= 14 else (5.5, 1.6)
        x = COLS[4][1]
        for k in range(n):
            if k < c["viajes"]:
                hecho = k < c["hechos"]
                color = (ROJO if hecho else ROJO_CLARO) if k >= tope else (AZUL if hecho else PROG)
            else:
                color = GRIS_CAJA
            h.rect(x, y + (FILA - lado) / 2, lado, lado, fill=color, r=1.6)
            x += lado + gap
        h.texto(COLS[5][1] + COLS[5][2] / 2, base + 0.6, str(c["viajes"]), "D9", 12, ROJO if pasado else TINTA, align="c")
        # Estado
        if pasado:
            txt, col, fondo = f"PASADO POR {c['pasado']}", ROJO, HexColor("#FBD5DB")
        elif c["viajes"] == tope:
            txt, col, fondo = "EN EL TOPE", AMBAR, AMBAR_F
        elif c["viajes"] == tope - 1:
            txt, col, fondo = "LE QUEDA 1", AMBAR, AMBAR_F
        else:
            txt, col, fondo = f"LE QUEDAN {tope - c['viajes']}", GRIS, HexColor("#EEF2F7")
        w = h.ancho(txt, "D8", 7.4, 0.5) + 14
        h.rect(X_ESTADO, y + (FILA - 15) / 2, w, 15, fill=fondo, r=7.5)
        h.texto(X_ESTADO + 7, y + FILA / 2 + 2.7, txt, "D8", 7.4, col, cs=0.5)
        self.y += FILA


def generar(d):
    p = Hojas(d)
    p.encabezado()
    if not d["choferes"]:
        p.h.texto(M, p.y + 10, f"Todavía no hay tripulantes cargados en el tráfico internacional de {d['mes_txt']}.",
                  "I5", 10, GRIS)
        p.y += 30
    else:
        p.cabecera_tabla()
        for i, c in enumerate(d["choferes"]):
            p.fila(i, c)
        # Cómo leer
        if p.y + 46 > H - PIE - 10:
            p.nueva_hoja()
        p.y += 14
        h = p.h
        x = M
        for color, txt in ((AZUL, "Ya hecho"), (PROG, "Programado en el tráfico"), (ROJO, "Pasa el tope")):
            h.rect(x, p.y - 7, 9, 9, fill=color, r=1.6)
            x += 13 + h.texto(x + 13, p.y + 0.6, txt, "I5", 8, GRIS) + 14
        p.y += 16
        h.texto(M, p.y, "Se cuenta lo cargado en el tráfico internacional de cada día del mes, también lo que todavía no salió. "
                        "Idas y regresos: vale el mayor.", "I4", 7.6, GRIS2)
        p.y += 12
    a = ahora_iso()
    p.h.texto(M, p.y + 4, f"Generado el {a[8:10]}/{a[5:7]}/{a[:4]} a las {a[11:16]}.", "I4", 7.6, GRIS2)
    p.pie()
    p.h.c.save()
    return p.h.buf.getvalue()
