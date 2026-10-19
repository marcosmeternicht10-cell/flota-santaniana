"""
rend_comb_pdf.py — PDF de la rendición de combustible (La Santaniana)

  pdf_sobre(s)       la hoja de un sobre: datos, consumo, comprobantes,
                     observaciones y firmas (chofer, operador, administración).
  pdf_lista(d, f)    el listado de sobres filtrado, apaisado, con totales.
"""

import io
import os

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.colors import HexColor, white
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics

import trafico_pdf

NAVY, AZUL, ROJO = HexColor("#1D344E"), HexColor("#1E5A96"), HexColor("#DC2641")
TINTA, GRIS, GRIS2 = HexColor("#16202C"), HexColor("#5B6B7F"), HexColor("#8796A8")
LINEA, SUAVE, CEBRA = HexColor("#D5DCE5"), HexColor("#F4F6F9"), HexColor("#F7F9FB")
VERDE, VERDE_F = HexColor("#2F7C46"), HexColor("#EAF5EE")
AZUL_F = HexColor("#E8F1FA")
AMBAR, AMBAR_F = HexColor("#B26A00"), HexColor("#FFF6E0")
ROJO_F = HexColor("#FDECEF")
CELESTE = HexColor("#8CBDEB")

ESTADO_TXT = {"abierto": "ABIERTO", "cerrado": "CERRADO", "rendido": "RENDIDO"}
ESTADO_FONDO = {"abierto": white, "cerrado": VERDE_F, "rendido": AZUL_F}
ESTADO_COLOR = {"abierto": GRIS, "cerrado": VERDE, "rendido": AZUL}
DESVIO_COLOR = {"bien": VERDE, "atencion": AMBAR, "malo": ROJO, "revisar": AZUL}


def _logo():
    try:
        return ImageReader(os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "logo.png"))
    except Exception:
        return None


def _miles(v, dec=0):
    try:
        v = float(v or 0)
    except (TypeError, ValueError):
        return "—"
    s = f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if dec and s.endswith("," + "0" * dec):
        s = s[: -(dec + 1)]
    return s


def _dmy(f):
    f = str(f or "")
    return f"{f[8:10]}/{f[5:7]}/{f[2:4]}" if len(f) >= 10 else ""


def _ahora_txt():
    try:
        from hora_local import ahora_iso
        t = ahora_iso().replace("T", " ")
    except Exception:
        from datetime import datetime
        t = datetime.now().isoformat(sep=" ")
    return f"{t[8:10]}/{t[5:7]}/{t[0:4]} {t[11:16]}"


class _Lienzo:
    def __init__(self, c, H, F):
        self.c, self.H, self.F = c, H, F

    def ancho(self, t, f, s):
        return pdfmetrics.stringWidth(str(t), self.F[f], s)

    def texto(self, x, y, t, f, s, color=TINTA, align="l"):
        c = self.c
        c.setFillColor(color)
        c.setFont(self.F[f], s)
        t = str(t)
        if align == "r":
            c.drawRightString(x, self.H - y, t)
        elif align == "c":
            c.drawCentredString(x, self.H - y, t)
        else:
            c.drawString(x, self.H - y, t)

    def cortar(self, t, f, s, maxw):
        t = str(t or "")
        if self.ancho(t, f, s) <= maxw:
            return t
        while t and self.ancho(t + "…", f, s) > maxw:
            t = t[:-1]
        return t.rstrip() + "…"

    def rect(self, x, y, w, h, fill=None, stroke=None, r=0, lw=0.8):
        c = self.c
        if fill is not None:
            c.setFillColor(fill)
        if stroke is not None:
            c.setStrokeColor(stroke)
            c.setLineWidth(lw)
        if r:
            c.roundRect(x, self.H - y - h, w, h, r, stroke=1 if stroke is not None else 0,
                        fill=1 if fill is not None else 0)
        else:
            c.rect(x, self.H - y - h, w, h, stroke=1 if stroke is not None else 0, fill=1 if fill is not None else 0)

    def linea(self, x1, y1, x2, y2, color=LINEA, lw=0.6):
        self.c.setStrokeColor(color)
        self.c.setLineWidth(lw)
        self.c.line(x1, self.H - y1, x2, self.H - y2)

    def encabezado(self, W, M, titulo, sub, caja_tit, caja_val, logo):
        y = M
        if logo:
            self.c.drawImage(logo, M, self.H - y - 34, 46, 34, mask="auto", preserveAspectRatio=True)
        self.texto(M + 56, y + 17, titulo, "D9", 21, NAVY)
        self.texto(M + 56, y + 32, sub, "I6", 8.5, GRIS)
        wbox = max(132, self.ancho(caja_val, "D9", 19) + 24)
        self.rect(W - M - wbox, y, wbox, 40, fill=NAVY, r=6)
        self.texto(W - M - wbox + 10, y + 15, caja_tit, "I6", 7, CELESTE)
        self.texto(W - M - wbox + 10, y + 33, caja_val, "D9", 19, white)
        self.rect(M, y + 47, (W - 2 * M) * 0.4, 3, fill=ROJO)
        self.rect(M + (W - 2 * M) * 0.4 + 3, y + 47, (W - 2 * M) * 0.6 - 3, 3, fill=AZUL)
        return y + 64


# ════════════════════════════════════════════════════════════════════════════
# HOJA DE UN SOBRE
# ════════════════════════════════════════════════════════════════════════════

def pdf_sobre(s):
    F = trafico_pdf._fuentes()
    W, H = A4
    M = 34
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Sobre {s['numero']} - coche {s['coche']}")
    c.setAuthor("La Santaniana")
    L = _Lienzo(c, H, F)
    logo = _logo()
    aw = W - 2 * M
    comps = s.get("comprobantes_lista") or []
    co = s.get("consumo") or {}

    POR_PRIMERA, POR_OTRA = 16, 34
    trozos = [comps[:POR_PRIMERA]]
    resto = comps[POR_PRIMERA:]
    while resto:
        trozos.append(resto[:POR_OTRA])
        resto = resto[POR_OTRA:]
    total_pag = len(trozos)
    impresa = _ahora_txt()

    def caja(x, y, w, h, etq, valor, grande=False, sub=""):
        L.rect(x, y, w, h, stroke=NAVY, lw=1)
        L.texto(x + 8, y + 13, etq.upper(), "I6", 6.6, GRIS)
        if valor:
            L.texto(x + 8, y + h - 9 - (6 if sub else 0), L.cortar(valor, "D8", 14 if grande else 12, w - 16),
                    "D8", 14 if grande else 12, TINTA)
        if sub:
            L.texto(x + 8, y + h - 6, L.cortar(sub, "I4", 7, w - 16), "I4", 7, GRIS)

    def tabla_comprobantes(y, filas, desde_n, con_total):
        cols = [("#", 22, "c"), ("FECHA", 56, "l"), ("COMPROBANTE", 84, "l"), ("LETRA", 34, "c"),
                ("NÚMERO", 118, "l"), ("LITROS", 62, "r"), ("ADITIVOS", 58, "r"), ("NRO. REF.", 0, "l")]
        fijo = sum(w for _, w, _ in cols)
        cols[-1] = ("NRO. REF.", aw - fijo, "l")
        L.rect(M, y, aw, 20, fill=NAVY, r=3)
        x = M
        for t, w, al in cols:
            xx = x + 6 if al == "l" else (x + w / 2 if al == "c" else x + w - 6)
            L.texto(xx, y + 13.5, t, "I6", 6.8, white, align=al)
            x += w
        y += 20
        if not filas:
            L.texto(M + aw / 2, y + 20, "Todavía no tiene comprobantes", "I5", 9, GRIS, align="c")
            return y + 34
        for k, cc in enumerate(filas):
            if k % 2:
                L.rect(M, y, aw, 18, fill=CEBRA)
            vals = [str(desde_n + k), _dmy(cc.get("fecha")), cc.get("tipo") or "", cc.get("letra") or "",
                    cc.get("numero") or "", _miles(cc.get("litros"), 2) if cc.get("litros") else "—",
                    _miles(cc.get("aditivos"), 2) if cc.get("aditivos") else "—",
                    (cc.get("nro_ref") or "") + ("  · carga del celular" if cc.get("vinculada") else "")]
            x = M
            for (t, w, al), v in zip(cols, vals):
                f = "D8" if t == "LITROS" else ("I5" if t != "#" else "I4")
                tam = 11 if t == "LITROS" else 8.6
                col = GRIS if t in ("#",) or (t == "NRO. REF." and cc.get("vinculada")) else TINTA
                v = L.cortar(v, f, tam, w - 10)
                xx = x + 6 if al == "l" else (x + w / 2 if al == "c" else x + w - 6)
                L.texto(xx, y + 12.5, v, f, tam, col, align=al)
                x += w
            L.linea(M, y + 18, M + aw, y + 18)
            y += 18
        if con_total:
            L.rect(M, y, aw, 22, fill=SUAVE)
            L.linea(M, y, M + aw, y, NAVY, 1)
            L.texto(M + 6, y + 14.5, f"TOTAL · {len(comps)} COMPROBANTE{'S' if len(comps) != 1 else ''}",
                    "I7", 7.6, NAVY)
            xl = M + sum(w for _, w, _ in cols[:6])
            L.texto(xl - 6, y + 15.5, _miles(s.get("litros"), 2) + " L", "D9", 12, NAVY, align="r")
            L.texto(xl + cols[6][1] - 6, y + 15.5, _miles(s.get("aditivos"), 2) if s.get("aditivos") else "—",
                    "D8", 11, NAVY, align="r")
            y += 22
        return y + 10

    for n_pag, filas in enumerate(trozos, 1):
        y = L.encabezado(W, M, "RENDICIÓN DE COMBUSTIBLE",
                         f"LA SANTANIANA S.A.  ·  CUENTA {s.get('cuenta') or '—'}", "SOBRE", f"N° {s['numero']}", logo)
        if n_pag == 1:
            est = s.get("estado") or "abierto"
            # Estado
            L.rect(M, y, aw, 26, fill=ESTADO_FONDO.get(est, white), stroke=LINEA, r=5)
            L.rect(M, y, 4, 26, fill=ESTADO_COLOR.get(est, GRIS))
            L.texto(M + 14, y + 17, ESTADO_TXT.get(est, est.upper()), "D9", 12, ESTADO_COLOR.get(est, GRIS))
            ev = [f"Abierto el {_dmy(s.get('fecha_apertura'))} por {s.get('abierto_por') or '—'}"]
            if s.get("cerrado_por"):
                ev.append(f"cerrado el {_dmy(s.get('fecha_cierre'))} por {s['cerrado_por']}")
            if s.get("rendido_por"):
                ev.append(f"rendido el {_dmy(s.get('rendido_el'))} por {s['rendido_por']}")
            L.texto(M + 84, y + 16.5, L.cortar(" · ".join(ev), "I5", 8, aw - 96), "I5", 8, GRIS)
            y += 36
            # Datos
            coche = f"{s['coche']}" + (f" · {s['patente']}" if s.get("patente") and str(s["patente"]) != s["coche"] else "")
            caja(M, y, aw * 0.30 - 6, 40, "Coche", coche, grande=True,
                 sub=" ".join(x for x in (s.get("marca"), s.get("modelo")) if x))
            caja(M + aw * 0.30, y, aw * 0.45 - 6, 40, "Chofer", s.get("chofer") or "")
            caja(M + aw * 0.75, y, aw * 0.25, 40, "Cuenta", s.get("cuenta") or "")
            y += 50
            # Consumo: números grandes
            celdas = [("KM INICIAL", _miles(s.get("km_inicial")) if s.get("km_inicial") else "—", ""),
                      ("KM FINAL", _miles(s.get("km_final")) if s.get("estado") != "abierto" and s.get("km_final") else "—", ""),
                      ("KM RECORRIDOS", _miles(co.get("km")) if co.get("km") else "—", ""),
                      ("LITROS", _miles(s.get("litros"), 2), "combustible"),
                      ("L / 100 KM", _miles(co.get("l100"), 2) if co.get("l100") else "—", ""),
                      ("ADITIVOS", _miles(s.get("aditivos"), 2) if s.get("aditivos") else "—",
                       f"{_miles(co.get('aditivo_l100'), 2)} L/100km" if co.get("aditivo_l100") else "litros")]
            cw = aw / len(celdas)
            L.rect(M, y, aw, 54, fill=SUAVE, r=6)
            for k, (t, v, sub) in enumerate(celdas):
                x = M + k * cw
                if k:
                    L.linea(x, y + 10, x, y + 44, LINEA)
                L.texto(x + cw / 2, y + 15, t, "I6", 6.4, GRIS, align="c")
                col = NAVY
                if t == "L / 100 KM" and (co.get("comparacion") or {}).get("estado") in DESVIO_COLOR:
                    col = DESVIO_COLOR[co["comparacion"]["estado"]]
                L.texto(x + cw / 2, y + 36, v, "D9", 17, col, align="c")
                if sub:
                    L.texto(x + cw / 2, y + 47, sub, "I4", 6.4, GRIS, align="c")
            comp = co.get("comparacion") or {}
            if comp.get("esperado_litros_100km") and comp.get("desvio_pct") is not None:
                signo = "+" if comp["desvio_pct"] > 0 else ""
                L.texto(M + 5 * cw - cw / 2, y + 47,
                        f"{signo}{_miles(comp['desvio_pct'], 1)}% vs {_miles(comp['esperado_litros_100km'], 1)} esperado",
                        "I5", 6.4, DESVIO_COLOR.get(comp.get("estado"), GRIS), align="c")
            y += 66
            L.texto(M, y + 4, "COMPROBANTES", "I7", 8, NAVY)
            y += 12
        else:
            L.texto(M, y + 4, f"COMPROBANTES (SIGUE)", "I7", 8, NAVY)
            y += 12
        desde_n = 1 + sum(len(t) for t in trozos[: n_pag - 1])
        y = tabla_comprobantes(y, filas, desde_n, n_pag == total_pag)

        if n_pag == total_pag:
            # Observaciones
            obs = (s.get("observaciones") or "").strip()
            h_obs = 46
            L.rect(M, y, aw, h_obs, stroke=NAVY, lw=1)
            L.texto(M + 8, y + 13, "OBSERVACIONES", "I6", 6.6, GRIS)
            if obs:
                c.setFont(F["I5"], 9)
                palabras, linea, lineas = obs.split(), "", []
                for p in palabras:
                    prueba = (linea + " " + p).strip()
                    if linea and L.ancho(prueba, "I5", 9) > aw - 16:
                        lineas.append(linea)
                        linea = p
                    else:
                        linea = prueba
                if linea:
                    lineas.append(linea)
                for k, ln in enumerate(lineas[:2]):
                    L.texto(M + 8, y + 26 + k * 11, ln, "I5", 9, TINTA)
            y += h_obs + 14
            # Firmas, abajo de todo
            yf = max(y + 30, H - 96)
            tercio = (aw - 24) / 3
            for k, t in enumerate(("Chofer", "Operador", "Administración")):
                x = M + k * (tercio + 12)
                L.linea(x, yf, x + tercio, yf, NAVY, 0.8)
                L.texto(x + tercio / 2, yf + 12, t.upper(), "I6", 7, GRIS, align="c")
                nombre = {"Chofer": s.get("chofer"), "Operador": s.get("cerrado_por") or s.get("abierto_por"),
                          "Administración": s.get("rendido_por")}[t]
                if nombre:
                    L.texto(x + tercio / 2, yf + 22, L.cortar(nombre, "I4", 7.5, tercio), "I4", 7.5, GRIS2, align="c")
        else:
            L.texto(W / 2, y + 6, "Sigue en la página siguiente", "I5", 9, GRIS, align="c")

        L.linea(M, H - 30, W - M, H - 30, LINEA, 0.5)
        L.texto(M, H - 18, f"Sobre {s['numero']} · Coche {s['coche']} · {s.get('chofer') or ''}", "I5", 7.5, GRIS)
        L.texto(W - M, H - 18, f"Hoja {n_pag} de {total_pag} · impresa el {impresa}", "I5", 7.5, GRIS, align="r")
        c.showPage()
    c.save()
    buf.seek(0)
    return buf


# ════════════════════════════════════════════════════════════════════════════
# LISTADO
# ════════════════════════════════════════════════════════════════════════════

def pdf_lista(d, filtro):
    F = trafico_pdf._fuentes()
    W, H = landscape(A4)
    M = 28
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setTitle("Sobres de combustible")
    c.setAuthor("La Santaniana")
    L = _Lienzo(c, H, F)
    logo = _logo()
    aw = W - 2 * M
    sobres = d.get("sobres") or []
    t = d.get("totales") or {}

    est_txt = {"pendientes": "sin rendir", "abierto": "abiertos", "cerrado": "cerrados", "rendido": "rendidos"}
    partes = [f"Sobres {est_txt.get(filtro.get('estado'), 'de todos los estados')}"]
    if filtro.get("desde") or filtro.get("hasta"):
        partes.append(f"abiertos {('del ' + _dmy(filtro['desde'])) if filtro.get('desde') else ''}"
                      f"{(' al ' + _dmy(filtro['hasta'])) if filtro.get('hasta') else ''}".strip())
    if filtro.get("q"):
        partes.append(f"búsqueda «{filtro['q']}»")
    impresa = _ahora_txt()

    cols = [("SOBRE", 42, "l"), ("COCHE", 44, "l"), ("CHOFER", 0, "l"), ("CUENTA", 58, "l"),
            ("APERTURA", 46, "c"), ("CIERRE", 46, "c"), ("KM INICIAL", 54, "r"), ("KM FINAL", 54, "r"),
            ("KM", 42, "r"), ("LITROS", 52, "r"), ("ADITIVOS", 44, "r"), ("L/100KM", 46, "r"),
            ("VS MOTOR", 46, "r"), ("COMPR.", 34, "c"), ("ESTADO", 50, "c")]
    fijo = sum(w for _, w, _ in cols)
    cols[2] = ("CHOFER", aw - fijo, "l")
    FILA = 17
    por_pag_1 = int((H - M - 150 - 40) // FILA)
    por_pag = int((H - M - 90 - 40) // FILA)
    trozos = [sobres[:por_pag_1]]
    resto = sobres[por_pag_1:]
    while resto:
        trozos.append(resto[:por_pag])
        resto = resto[por_pag:]
    total_pag = len(trozos)

    for n_pag, filas in enumerate(trozos, 1):
        y = L.encabezado(W, M, "SOBRES DE COMBUSTIBLE", "LA SANTANIANA S.A.  ·  RENDICIÓN DE COMBUSTIBLE",
                         "SOBRES", str(len(sobres)), logo)
        if n_pag == 1:
            L.texto(M, y + 4, " · ".join(partes).upper(), "I6", 7.6, GRIS)
            y += 14
            kp = [("LITROS", _miles(t.get("litros"), 2)), ("COMPROBANTES", _miles(t.get("comprobantes"))),
                  ("KM MEDIDOS", _miles(t.get("km")) if t.get("km") else "—"),
                  ("L/100 KM (CERRADOS)", _miles(t.get("l100"), 2) if t.get("l100") else "—"),
                  ("ADITIVOS", _miles(t.get("aditivos"), 2) if t.get("aditivos") else "—")]
            cw = aw / len(kp)
            L.rect(M, y, aw, 40, fill=SUAVE, r=6)
            for k, (tt, v) in enumerate(kp):
                x = M + k * cw
                if k:
                    L.linea(x, y + 8, x, y + 32)
                L.texto(x + cw / 2, y + 14, tt, "I6", 6.4, GRIS, align="c")
                L.texto(x + cw / 2, y + 32, v, "D9", 15, NAVY, align="c")
            y += 52
        L.rect(M, y, aw, 19, fill=NAVY, r=3)
        x = M
        for tt, w, al in cols:
            xx = x + 5 if al == "l" else (x + w / 2 if al == "c" else x + w - 5)
            L.texto(xx, y + 12.8, tt, "I6", 6.4, white, align=al)
            x += w
        y += 19
        if not filas:
            L.texto(W / 2, y + 22, "No hay sobres con este filtro", "I5", 9, GRIS, align="c")
        for k, s in enumerate(filas):
            est = s.get("estado") or "abierto"
            fondo = ESTADO_FONDO.get(est, white)
            if est == "abierto" and k % 2:
                fondo = CEBRA
            L.rect(M, y, aw, FILA, fill=fondo)
            co = s.get("consumo") or {}
            comp = co.get("comparacion") or {}
            desvio = ""
            if comp.get("desvio_pct") is not None and not comp.get("sin_datos"):
                desvio = ("+" if comp["desvio_pct"] > 0 else "") + _miles(comp["desvio_pct"], 1) + "%"
            vals = [str(s["numero"]), s["coche"], s.get("chofer") or "—", s.get("cuenta") or "",
                    _dmy(s.get("fecha_apertura")), _dmy(s.get("fecha_cierre")) or "—",
                    _miles(s.get("km_inicial")) if s.get("km_inicial") else "—",
                    _miles(s.get("km_final")) if est != "abierto" and s.get("km_final") else "—",
                    _miles(co.get("km")) if co.get("km") else "—",
                    _miles(s.get("litros"), 2), _miles(s.get("aditivos"), 2) if s.get("aditivos") else "—",
                    _miles(co.get("l100"), 2) if co.get("l100") else "—", desvio or "—",
                    str(s.get("comprobantes") or 0), ESTADO_TXT.get(est, est.upper())]
            x = M
            for (tt, w, al), v in zip(cols, vals):
                f, tam, col = "I5", 7.8, TINTA
                if tt in ("SOBRE", "COCHE", "LITROS"):
                    f, tam = "D8", 9.6
                if tt == "VS MOTOR" and desvio:
                    col, f = DESVIO_COLOR.get(comp.get("estado"), GRIS), "I6"
                if tt == "ESTADO":
                    col, f, tam = ESTADO_COLOR.get(est, GRIS), "I7", 7
                if v == "—":
                    col = GRIS2
                v = L.cortar(v, f, tam, w - 8)
                xx = x + 5 if al == "l" else (x + w / 2 if al == "c" else x + w - 5)
                L.texto(xx, y + 11.8, v, f, tam, col, align=al)
                x += w
            L.linea(M, y + FILA, M + aw, y + FILA)
            y += FILA
        if n_pag == total_pag and sobres:
            L.rect(M, y, aw, 20, fill=SUAVE)
            L.linea(M, y, M + aw, y, NAVY, 1)
            L.texto(M + 5, y + 13.5, f"TOTAL · {len(sobres)} SOBRE{'S' if len(sobres) != 1 else ''}", "I7", 7.4, NAVY)
            xl = M + sum(w for _, w, _ in cols[:10])
            L.texto(xl - 5, y + 14, _miles(t.get("litros"), 2), "D9", 11, NAVY, align="r")
            y += 20
        # Leyenda de colores (como el sistema viejo)
        yl = H - 46
        x = M
        for est in ("abierto", "cerrado", "rendido"):
            L.rect(x, yl - 8, 18, 10, fill=ESTADO_FONDO[est], stroke=LINEA, lw=0.6)
            L.texto(x + 24, yl, est.capitalize(), "I5", 7.4, GRIS)
            x += 80
        L.linea(M, H - 30, W - M, H - 30, LINEA, 0.5)
        L.texto(M, H - 18, "Sobres de combustible · La Santaniana", "I5", 7.5, GRIS)
        L.texto(W - M, H - 18, f"Hoja {n_pag} de {total_pag} · impreso el {impresa}", "I5", 7.5, GRIS, align="r")
        c.showPage()
    c.save()
    buf.seek(0)
    return buf
