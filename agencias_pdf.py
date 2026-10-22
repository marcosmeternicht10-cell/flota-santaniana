"""
agencias_pdf.py — La ficha de una agencia en PDF (La Santaniana)

Una o más hojas A4 con la misma cara que el resto de los PDF del sistema
(banda azul con el logo, franja roja y azul): los datos de la agencia y su
ubicación (con el enlace a Google Maps), lo que hay que atender, las
condiciones del contrato que rige, los papeles y el historial de versiones.

  generar_ficha(ficha)    ficha = agencias.ficha(id)
"""

from datetime import date

from reportlab.lib.colors import white, HexColor

from trafico_pdf import Hoja, W, H, NAVY, NAVY3, AZUL, ROJO, TINTA, GRIS, GRIS2, LINEA, CEBRA, AMBAR, AMBAR_F, ROJO_F, VERDE
from hora_local import ahora_iso

M = 36
AW = W - 2 * M
PIE = 34
VERDE_F = HexColor("#E7F4EA")
COLOR_NIVEL = {"mal": (ROJO, ROJO_F), "ojo": (AMBAR, AMBAR_F), "ok": (VERDE, VERDE_F),
               "suspendida": (GRIS, CEBRA), "baja": (GRIS, CEBRA)}
NOMBRE_NIVEL = {"mal": "HAY QUE ATENDER", "ojo": "A TENER EN CUENTA", "ok": "AL DÍA",
                "suspendida": "SUSPENDIDA", "baja": "DADA DE BAJA"}


def _fmt(f):
    try:
        return date.fromisoformat(str(f)[:10]).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return "—"


def _gs(n):
    try:
        return "Gs. " + f"{int(round(float(n or 0))):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def _maps(ag):
    if ag.get("lat") is not None and ag.get("lng") is not None:
        return f"https://www.google.com/maps/search/?api=1&query={ag['lat']},{ag['lng']}"
    link = ag.get("ubicacion_link") or ""
    if link.startswith("http"):
        return link
    import urllib.parse
    q = " ".join(x for x in (link or ag.get("nombre"), ag.get("direccion"), ag.get("ciudad"), "Paraguay") if x)
    return "https://www.google.com/maps/search/?api=1&query=" + urllib.parse.quote(q)


class Ficha:
    """Una hoja con cursor: si lo que sigue no entra, pasa a la siguiente."""

    def __init__(self, f):
        self.f = f
        ag = f["agencia"]
        self.h = Hoja({"nombre_dia": ag["nombre"], "titulo": "Ficha de agencia"})
        self.h.c.setTitle(f"Agencia {ag['nombre']}")
        self.h.c.setSubject("Ficha de agencia de venta de pasajes")
        self.pagina = 1
        self.y = 0

    # ── páginas ──
    def pie(self):
        h = self.h
        h.linea(M, H - PIE + 8, W - M, H - PIE + 8, LINEA, 0.6)
        h.texto(M, H - PIE + 20, f"LA SANTANIANA  ·  AGENCIAS Y CONTRATOS  ·  {self.f['agencia']['nombre'].upper()}",
                "D6", 7, GRIS2, cs=0.6)
        h.texto(W - M, H - PIE + 20, f"HOJA {self.pagina}", "D8", 7, GRIS2, cs=0.6, align="r")

    def nueva_hoja(self):
        self.pie()
        self.h.c.showPage()
        self.pagina += 1
        self.h.franja(0, 4)
        self.y = 26

    def lugar(self, alto):
        if self.y + alto > H - PIE - 8:
            self.nueva_hoja()

    # ── piezas ──
    def encabezado(self):
        h, f, ag = self.h, self.f, self.f["agencia"]
        alto = 118
        h.rect(0, 0, W, alto, fill=NAVY)
        for i, (x, ancho) in enumerate([(W - 230, 44), (W - 170, 28), (W - 128, 70)]):
            h.poligono([(x + 40, 0), (x + 40 + ancho, 0), (x + ancho, alto), (x, alto)], NAVY3, alpha=0.28 - i * 0.05)
        h.tile_logo(M, 26, 46, 9)
        h.texto(M + 60, 38, "LA SANTANIANA  ·  AGENCIA DE VENTA DE PASAJES", "D8", 8.4, HexColor("#A9C4E3"), cs=1.2)
        t, s = h.ajustar(ag["nombre"].upper(), "D9", 27, W - 2 * M - 60 - 130, 16)
        h.texto(M + 60, 66, t, "D9", s, white, cs=0.3)
        sub = " · ".join(x for x in (ag.get("razon_social"), f"RUC {ag['ruc']}" if ag.get("ruc") else "",
                                     ag.get("ciudad")) if x)
        if sub:
            t, s = h.ajustar(sub, "I5", 9.2, W - 2 * M - 60 - 130, 7.5)
            h.texto(M + 60, 84, t, "I5", s, HexColor("#C9D7E8"))
        # Estado a la derecha
        col, fondo = COLOR_NIVEL.get(f["nivel"], (GRIS, CEBRA))
        etiqueta = NOMBRE_NIVEL.get(f["nivel"], "")
        w = h.ancho(etiqueta, "D8", 8.6, 0.6) + 22
        h.rect(W - M - w, 30, w, 20, fill=fondo, r=10)
        h.punto(W - M - w + 10, 40, 3, col)
        h.texto(W - M - w + 17, 43.2, etiqueta, "D8", 8.6, col, cs=0.6)
        h.texto(W - M, 70, f"FICHA AL {_fmt(f['hoy'])}", "D8", 8, HexColor("#A9C4E3"), cs=0.8, align="r")
        h.franja(alto, 4)
        self.y = alto + 22

    def titulo(self, txt, extra=""):
        self.lugar(40)
        h = self.h
        h.texto(M, self.y + 10, txt.upper(), "D8", 10.5, AZUL, cs=1.1)
        if extra:
            h.texto(W - M, self.y + 10, extra, "I5", 8.4, GRIS, align="r")
        h.linea(M, self.y + 16, W - M, self.y + 16, LINEA, 0.8)
        self.y += 26

    def parrafo(self, x, y, txt, f, s, maxw, color=TINTA, inter=None):
        """Texto partido en renglones (respeta los saltos de línea). Devuelve el alto."""
        inter = inter or s * 1.35
        renglones = []
        for linea in str(txt or "").split("\n"):
            renglones += self.h.partir(linea, f, s, maxw) or [""]
        for i, r in enumerate(renglones):
            if "→" in r:
                self.h.texto_flechas(x, y + s + i * inter, r, f, s, color)
            else:
                self.h.texto(x, y + s + i * inter, r, f, s, color)
        return len(renglones) * inter

    def alto_parrafo(self, txt, f, s, maxw, inter=None):
        inter = inter or s * 1.35
        n = sum(len(self.h.partir(l, f, s, maxw) or [""]) for l in str(txt or "").split("\n"))
        return n * inter

    def pares(self, filas, col=2):
        """Etiqueta arriba y valor abajo, en columnas."""
        h = self.h
        ancho = (AW - (col - 1) * 18) / col
        for i in range(0, len(filas), col):
            grupo = filas[i:i + col]
            altos = [12 + self.alto_parrafo(v or "—", "I5", 9.6, ancho) for _, v, *_ in grupo]
            alto = max(altos) + 8
            self.lugar(alto)
            for j, (et, v, *link) in enumerate(grupo):
                x = M + j * (ancho + 18)
                h.texto(x, self.y + 7, et.upper(), "D6", 7.2, GRIS, cs=0.8)
                self.parrafo(x, self.y + 11, v or "—", "I5", 9.6, ancho, TINTA if v else GRIS2)
                if link and link[0]:
                    w = min(h.ancho(v or "", "I5", 9.6), ancho)
                    h.c.linkURL(link[0], (x, H - self.y - 26, x + w, H - self.y - 10), relative=0)
            self.y += alto

    def avisos(self):
        f, h = self.f, self.h
        if not f["avisos"]:
            self.lugar(34)
            h.rect(M, self.y, AW, 26, fill=VERDE_F, r=6)
            h.punto(M + 14, self.y + 13, 3.2, VERDE)
            h.texto(M + 24, self.y + 16.6, "Contrato, garantía y papeles al día.", "I6", 9.6, VERDE)
            self.y += 36
            return
        alto = 14 + sum(4 + self.alto_parrafo(a["txt"], "I5", 9.4, AW - 40) for a in f["avisos"])
        self.lugar(alto + 10)
        hay_mal = any(a["nivel"] == "mal" for a in f["avisos"])
        h.rect(M, self.y, AW, alto, fill=ROJO_F if hay_mal else AMBAR_F, r=6)
        yy = self.y + 8
        for a in f["avisos"]:
            col = ROJO if a["nivel"] == "mal" else AMBAR
            h.punto(M + 14, yy + 7.5, 3, col)
            yy += 4 + self.parrafo(M + 24, yy, a["txt"], "I5", 9.4, AW - 40, TINTA)
        self.y += alto + 12

    def tabla(self, columnas, filas, tam=8.8):
        """columnas: [(titulo, ancho, align)]. filas: listas de textos (el último
        puede ser largo: se parte)."""
        h = self.h
        self.lugar(22 + 18)
        x = M
        h.rect(M, self.y, AW, 18, fill=NAVY, r=3)
        for t, w, al in columnas:
            h.texto(x + (w - 8 if al == "r" else 8), self.y + 12, t.upper(), "D8", 7.2, white, cs=0.8,
                    align="r" if al == "r" else "l")
            x += w
        self.y += 18
        for i, fila in enumerate(filas):
            altos = [self.alto_parrafo(str(v), "I5", tam, w - 16) for v, (_, w, _) in zip(fila, columnas)]
            alto = max(altos) + 10
            if self.y + alto > H - PIE - 8:
                self.nueva_hoja()
            if i % 2:
                h.rect(M, self.y, AW, alto, fill=CEBRA)
            x = M
            for v, (_, w, al) in zip(fila, columnas):
                if al == "r":
                    h.texto(x + w - 8, self.y + 5 + tam, str(v), "I5", tam, TINTA, align="r")
                else:
                    self.parrafo(x + 8, self.y + 5, str(v), "I5", tam, w - 16, TINTA)
                x += w
            h.linea(M, self.y + alto, W - M, self.y + alto, LINEA, 0.5)
            self.y += alto
        self.y += 12


def generar_ficha(f):
    p = Ficha(f)
    ag = f["agencia"]
    p.encabezado()
    p.avisos()

    # Datos y ubicación
    p.titulo("Datos de la agencia", "Suspendida: " + ag.get("estado_motivo") if ag.get("estado") == "suspendida"
             else ("Dada de baja: " + ag.get("estado_motivo") if ag.get("estado") == "baja" else ""))
    rep = ag.get("representante") or ""
    if ag.get("ci_representante"):
        rep += f" (CI {ag['ci_representante']})"
    ubic = ""
    if ag.get("lat") is not None:
        ubic = f"{ag['lat']:.5f}, {ag['lng']:.5f} — Ver en Google Maps"
    elif ag.get("ubicacion_link") or ag.get("direccion"):
        ubic = "Ver en Google Maps"
    p.pares([
        ("Razón social", ag.get("razon_social")), ("RUC", ag.get("ruc")),
        ("Representante", rep), ("Teléfono / WhatsApp", " · ".join(x for x in (ag.get("telefono"), ag.get("whatsapp")) if x)),
        ("Correo", ag.get("email")), ("Ciudad", ag.get("ciudad")),
        ("Dirección", ag.get("direccion")), ("Local / terminal", ag.get("lugar")),
        ("Ubicación", ubic, _maps(ag) if ubic else ""), ("Nota", ag.get("nota")),
    ])

    # Contrato que rige
    v = f.get("vigente")
    if v:
        extra = f"{v['tipo_txt']}{(' Nº ' + v['numero']) if v.get('numero') else ''} · cargado por {(v.get('creado_por') or '—').split(' ')[0]}"
        p.titulo("Último contrato (vencido)" if f.get("estado_contrato") == "vencido" else "Contrato que rige hoy", extra)
        c = f["contrato"] or {}
        vig = f"Del {_fmt(v['desde'])} al {_fmt(c.get('hasta'))}" if c.get("hasta") else f"Desde el {_fmt(v['desde'])}, sin fecha de fin"
        if v.get("renov_auto"):
            vig += f" · se renueva solo{(' (preaviso de ' + str(v['preaviso_dias']) + ' días)') if v.get('preaviso_dias') else ''}"
        gar = ""
        if v.get("garantia_tipo"):
            gar = " · ".join(x for x in (v["garantia_txt"], _gs(v.get("garantia_monto")) if v.get("garantia_monto") else "",
                                         f"vence {_fmt(v['garantia_vence'])}" if v.get("garantia_vence") else "",
                                         v.get("garantia_detalle")) if x)
        p.pares([
            ("Vigencia", vig), ("Comisión general", v["comision_txt"]),
            ("Qué puede vender", v.get("autorizado")),
            ("Exclusividad", ("Sí" + (f" — {v['zona_exclusiva']}" if v.get("zona_exclusiva") else "")) if v.get("exclusividad") else "No"),
            ("Depósitos", v.get("deposito_txt")), ("Cuenta para depositar", v.get("cuenta_deposito")),
            ("Tope sin depositar", _gs(v["tope_sin_depositar"]) if v.get("tope_sin_depositar") else ""),
            ("Garantía", gar or "Sin garantía"),
            ("Devoluciones y anulaciones", v.get("devoluciones")), ("Nota", v.get("nota")),
        ])
        if v.get("rutas"):
            p.tabla([("Comisión por ruta", AW * 0.62, "l"), ("Comisión", AW * 0.38, "r")],
                    [[r["ruta"], r["txt"]] for r in v["rutas"]])
    else:
        p.titulo("Contrato")
        p.lugar(24)
        p.h.texto(M, p.y + 10, f.get("contrato_txt") or "Sin contrato cargado", "I6", 9.8, ROJO)
        p.y += 24

    # Papeles
    pap = [x for x in f.get("papeles_lista") or [] if not x.get("reemplazado")]
    p.titulo("Papeles", f"Faltan: {', '.join(f['papeles']['faltan'])}" if f["papeles"]["faltan"] else "")
    if pap:
        filas = []
        for d in pap:
            est = "Vencido" if d["nivel"] == "mal" else (f"Vence en {d['dias']} días" if d["nivel"] == "ojo" else "Al día")
            if not d.get("vence"):
                est = "No vence"
            nombre = d["tipo_txt"] + (f" — {d['descripcion']}" if d.get("descripcion") else "")
            filas.append([nombre, _fmt(d["vence"]) if d.get("vence") else "—", est,
                          f"{_fmt(d['subido_el'])} · {(d.get('subido_por') or '').split(' ')[0]}"])
        p.tabla([("Papel", AW * 0.40, "l"), ("Vence", AW * 0.15, "l"), ("Estado", AW * 0.20, "l"),
                 ("Subido", AW * 0.25, "l")], filas)
    else:
        p.lugar(22)
        p.h.texto(M, p.y + 10, "Todavía no se subió ningún papel.", "I5", 9.4, GRIS)
        p.y += 22

    # Historial
    vers = f.get("versiones") or []
    if vers:
        p.titulo("Historial del contrato", f"{len(vers)} " + ("versiones" if len(vers) != 1 else "versión"))
        filas = []
        for x in vers:
            nombre = x["tipo_txt"] + (" (rige)" if x.get("rige") else " (próxima)" if x.get("futuro") else "")
            if x.get("anulado"):
                nombre += " — anulada"
            det = "; ".join(x.get("cambios") or [])
            if x.get("anulado"):
                det = f"Anulada: {x.get('anulado_motivo') or ''}"
            elif not det:
                det = f"Comisión {x['comision_txt']}"
            filas.append([nombre, _fmt(x["desde"]), _fmt(x["hasta"]) if x.get("hasta") else "—", det])
        p.tabla([("Versión", AW * 0.20, "l"), ("Desde", AW * 0.13, "l"), ("Hasta", AW * 0.13, "l"),
                 ("Qué cambió", AW * 0.54, "l")], filas, tam=8.4)

    p.lugar(16)
    p.h.texto(M, p.y + 6, f"Generado el {_fmt(ahora_iso()[:10])} a las {ahora_iso()[11:16]}.", "I4", 7.6, GRIS2)
    p.pie()
    p.h.c.save()
    return p.h.buf.getvalue()
