"""
agenda_pdf.py — Informe de la agenda del taller, para imprimir (La Santaniana)

  pdf_agenda(d, quien)   qué se hizo y qué no de los turnos agendados entre dos
                         fechas. Arriba, el resumen y si la agenda se está
                         cumpliendo; después, primero lo que NO se hizo y luego
                         todos los turnos por fecha, con su resultado.

Los datos salen de plan_preventivo.informe_agenda().
"""

import io

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib.colors import white

import trafico_pdf
from rend_comb_pdf import (_Lienzo, _logo, _dmy, _ahora_txt,
                           NAVY, AZUL, ROJO, TINTA, GRIS, GRIS2, LINEA, SUAVE, CEBRA,
                           VERDE, VERDE_F, AZUL_F, AMBAR, AMBAR_F, ROJO_F)
from cajas_pdf import _partir, _pie, _firmas

DIAS = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]
# resultado → (color del texto, fondo de la etiqueta)
COLOR = {"hecho": (VERDE, VERDE_F), "en_taller": (AZUL, AZUL_F), "no_hecho": (ROJO, ROJO_F),
         "pendiente": (GRIS, SUAVE), "cancelado": (GRIS2, SUAVE)}
NIVEL = {"bien": (VERDE, VERDE_F), "atencion": (AMBAR, AMBAR_F), "mal": (ROJO, ROJO_F), "sin_datos": (GRIS, SUAVE)}


def _dia(f):
    from datetime import date
    try:
        d = date.fromisoformat(str(f)[:10])
        return f"{DIAS[d.weekday()]} {d.day:02d}/{d.month:02d}"
    except ValueError:
        return str(f or "")


def _dibujar(d, quien, c, total_pag):
    F = trafico_pdf._fuentes()
    W, H = A4
    M = 34
    aw = W - 2 * M
    L = _Lienzo(c, H, F)
    logo = _logo()
    r = d["resumen"]
    pie_txt = f"Agenda del taller · del {_dmy(d['desde'])} al {_dmy(d['hasta'])} · impreso el {_ahora_txt()}" + (f" por {quien}" if quien else "")
    pag = [1]

    def nueva_hoja():
        _pie(L, W, M, H, pie_txt, pag[0], total_pag)
        c.showPage()
        pag[0] += 1
        return M + 6

    pct_txt = f"{r['pct']} %" if r["pct"] is not None else "—"
    y = L.encabezado(W, M, "Agenda del taller", f"Qué se hizo y qué no · del {_dmy(d['desde'])} al {_dmy(d['hasta'])}",
                     "CUMPLIMIENTO", pct_txt, logo)

    # ── Si se está cumpliendo o no, en una frase
    col, fondo = NIVEL.get(r["nivel"], NIVEL["sin_datos"])
    lineas = _partir(L, r["frase"], "I6", 10.5, aw - 28)
    alto = 16 + 14 * len(lineas)
    L.rect(M, y, aw, alto, fill=fondo, r=6)
    L.rect(M, y, 5, alto, fill=col)
    for i, ln in enumerate(lineas):
        L.texto(M + 16, y + 19 + 14 * i, ln, "I6", 10.5, col)
    y += alto + 10

    # ── Los números
    cajas = [("Debían hacerse", r["debian"], TINTA, SUAVE), ("Se hicieron", r["hecho"], VERDE, VERDE_F),
             ("En el taller", r["en_taller"], AZUL, AZUL_F), ("No se hicieron", r["no_hecho"], ROJO, ROJO_F),
             ("Pendientes", r["pendiente"], GRIS, SUAVE)]
    w5 = (aw - 4 * 8) / 5
    for i, (t, v, colv, fon) in enumerate(cajas):
        x = M + i * (w5 + 8)
        L.rect(x, y, w5, 46, fill=fon, r=6)
        L.texto(x + 10, y + 15, t.upper(), "I6", 6.8, GRIS)
        L.texto(x + 10, y + 37, str(v), "D8", 19, colv)
    y += 56
    nota = "«Debían hacerse» son los turnos cuya fecha ya pasó, más los de hoy que ya entraron. Los cancelados no cuentan."
    if r["cancelado"]:
        nota += f" Cancelados en el período: {r['cancelado']}."
    L.texto(M, y, nota, "I4", 7.2, GRIS2)
    y += 16

    cols = [("FECHA", 54), ("COCHE", 44), ("QUÉ LE TOCABA", 0), ("TÉCNICOS", 92), ("RESULTADO", 68), ("DETALLE", 138)]
    cols[2] = ("QUÉ LE TOCABA", aw - sum(w for _, w in cols))
    xs = [M]
    for _, w in cols[:-1]:
        xs.append(xs[-1] + w)

    def cabecera(y):
        L.rect(M, y, aw, 17, fill=NAVY, r=3)
        for (t, _), x in zip(cols, xs):
            L.texto(x + 6, y + 11.5, t, "I7", 6.6, white)
        return y + 17

    def seccion(y, titulo, sub, color):
        if y > H - 120:
            y = nueva_hoja()
        L.texto(M, y + 12, titulo, "D8", 13, color)
        if sub:
            L.texto(M + L.ancho(titulo, "D8", 13) + 8, y + 12, sub, "I5", 8, GRIS)
        return cabecera(y + 19)

    def filas(y, turnos):
        for i, t in enumerate(turnos):
            que = ", ".join(t["tareas"]) or t["notas"] or "Sin detalle"
            if t["tareas"] and t["notas"]:
                que += f" · {t['notas']}"
            l_que = _partir(L, que, "I4", 7.8, cols[2][1] - 12)[:4]
            l_tec = _partir(L, ", ".join(x for x in t["tecnicos"] if x) or "—", "I4", 7.5, cols[3][1] - 12)[:4]
            l_det = _partir(L, t["detalle"], "I4", 7.5, cols[5][1] - 12)[:4]
            alto = 9 + 10 * max(len(l_que), len(l_tec), len(l_det), 2 if t["hora"] else 1) + 3
            if y + alto > H - 44:
                y = cabecera(nueva_hoja())
            if i % 2:
                L.rect(M, y, aw, alto, fill=CEBRA)
            colr, fonr = COLOR.get(t["resultado"], COLOR["pendiente"])
            L.rect(M, y, 3, alto, fill=colr)
            L.texto(xs[0] + 6, y + 12, _dia(t["fecha"]), "I6", 7.8, TINTA)
            if t["hora"]:
                L.texto(xs[0] + 6, y + 22, t["hora"], "I4", 7, GRIS)
            L.texto(xs[1] + 6, y + 13, L.cortar(t["coche"], "D8", 11.5, cols[1][1] - 8), "D8", 11.5, NAVY)
            for k, ln in enumerate(l_que):
                L.texto(xs[2] + 6, y + 12 + 10 * k, ln, "I4", 7.8, TINTA)
            for k, ln in enumerate(l_tec):
                L.texto(xs[3] + 6, y + 12 + 10 * k, ln, "I4", 7.5, GRIS)
            wr = L.ancho(t["resultado_txt"], "I7", 7.2) + 12
            L.rect(xs[4] + 5, y + 3.5, wr, 12.5, fill=fonr, r=6)
            L.texto(xs[4] + 11, y + 12.3, t["resultado_txt"], "I7", 7.2, colr)
            for k, ln in enumerate(l_det):
                L.texto(xs[5] + 6, y + 12 + 10 * k, ln, "I4", 7.5, colr if t["resultado"] == "no_hecho" else GRIS)
            L.linea(M, y + alto, M + aw, y + alto, LINEA, 0.4)
            y += alto
        return y

    # ── Primero, lo que no se hizo
    no = [t for t in d["turnos"] if t["resultado"] == "no_hecho"]
    if no:
        y = seccion(y, "No se hicieron", f"{len(no)} {'turno' if len(no) == 1 else 'turnos'}: hay que reprogramarlos o anotar por qué", ROJO)
        y = filas(y, no) + 16

    # ── Después, todo, por fecha
    todos = [t for t in d["turnos"] if t["resultado"] != "cancelado"]
    if todos:
        y = seccion(y, "Todos los turnos", f"{len(todos)} en el período, por fecha", NAVY)
        y = filas(y, todos) + 10
    else:
        L.rect(M, y, aw, 44, fill=SUAVE, r=6)
        L.texto(M + aw / 2, y + 26, "No hay turnos agendados en este período.", "I5", 10, GRIS, "c")
        y += 54
    cancel = [t for t in d["turnos"] if t["resultado"] == "cancelado"]
    if cancel:
        y = seccion(y + 6, "Cancelados", f"{len(cancel)}, no cuentan para el cumplimiento", GRIS)
        y = filas(y, cancel) + 10

    if y > H - 120:
        y = nueva_hoja()
    _firmas(L, W, M, y + 22, [("Jefe de taller", ""), ("Gerencia", "")])
    _pie(L, W, M, H, pie_txt, pag[0], total_pag)
    return pag[0]


def pdf_agenda(d, quien=""):
    total = _dibujar(d, quien, canvas.Canvas(io.BytesIO(), pagesize=A4), 0)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(f"Agenda del taller del {d['desde']} al {d['hasta']}")
    c.setAuthor("La Santaniana")
    _dibujar(d, quien, c, total)
    c.save()
    buf.seek(0)
    return buf
