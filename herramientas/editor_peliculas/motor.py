"""
motor.py — Lo que hace el trabajo: leer la película, sacar cuadros para la
vista previa y convertir a .vob (formato DVD) con el tamaño pedido.

Todo pasa por ffmpeg y ffprobe. Se buscan primero al lado de este archivo
(carpeta "ffmpeg" o sueltos) y si no, en el PATH de Windows.

La conversión:
  · Se queda con las partes elegidas (inicio, fin y lo que se saca del medio).
  · Una pista de audio, y subtítulos quemados en la imagen si se piden
    (de un .srt aparte o de los que trae la película).
  · MPEG-2 + AC-3 en un .vob, en dos pasadas: la primera mide la película y
    la segunda reparte la calidad para que el archivo quede en el tamaño
    pedido (con una tolerancia de un par de por ciento).
  · La resolución sale sola del tamaño: con poca calidad disponible conviene
    media resolución de DVD (352 de ancho), que se ve más limpia que la
    resolución completa con cuadritos.
"""

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading

AQUI = os.path.dirname(os.path.abspath(sys.argv[0] if getattr(sys, "frozen", False) else __file__))
EN_WINDOWS = os.name == "nt"
SIN_VENTANA = 0x08000000 if EN_WINDOWS else 0      # que no aparezca una consola negra por cada ffmpeg

# ─── Normas de DVD ───────────────────────────────────────────────────────────
NORMAS = {
    "PAL": {"alto": 576, "fps": "25", "nombre": "PAL (25 cuadros)"},
    "NTSC": {"alto": 480, "fps": "30000/1001", "nombre": "NTSC (29,97 cuadros)"},
}
ANCHOS = {"completa": 720, "media": 352}
AUDIO_KBPS = 192            # AC-3 estéreo: suena bien y ocupa poco
VIDEO_MIN_KBPS = 400        # menos que esto ya no se ve
VIDEO_MAX_KBPS = 8000       # el tope que aceptan los reproductores de DVD
UMBRAL_MEDIA_KBPS = 2500    # por debajo de esto, media resolución se ve mejor
MARGEN = 0.97               # lo que se pierde en el contenedor .vob y los redondeos


def _buscar(prog):
    exe = prog + (".exe" if EN_WINDOWS else "")
    for p in (os.path.join(AQUI, "ffmpeg", "bin", exe), os.path.join(AQUI, "ffmpeg", exe), os.path.join(AQUI, exe)):
        if os.path.isfile(p):
            return p
    return shutil.which(prog)


FFMPEG = _buscar("ffmpeg")
FFPROBE = _buscar("ffprobe")


def falta_ffmpeg():
    return not (FFMPEG and FFPROBE)


def _correr(args, **kw):
    return subprocess.run(args, capture_output=True, creationflags=SIN_VENTANA, **kw)


# ─── Leer la película ────────────────────────────────────────────────────────
SUBS_TEXTO = {"subrip", "srt", "ass", "ssa", "mov_text", "webvtt", "text"}


def leer(ruta):
    """Duración, tamaño de imagen, pistas de audio y subtítulos."""
    ruta = os.path.abspath(ruta)
    r = _correr([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", ruta])
    if r.returncode:
        raise ValueError("No se pudo leer el archivo: " + r.stderr.decode("utf-8", "replace").strip()[-300:])
    d = json.loads(r.stdout.decode("utf-8", "replace"))
    video = next((s for s in d["streams"] if s["codec_type"] == "video"
                  and not s.get("disposition", {}).get("attached_pic")), None)
    if not video:
        raise ValueError("El archivo no tiene imagen.")
    dur = float(d["format"].get("duration") or video.get("duration") or 0)
    if dur <= 0:
        raise ValueError("No se pudo saber cuánto dura la película.")

    def etiqueta(s, n):
        t = s.get("tags", {})
        idioma = (t.get("language") or "").upper()
        titulo = t.get("title") or ""
        partes = [f"Pista {n}", idioma if idioma not in ("", "UND") else "", titulo]
        return " · ".join(p for p in partes if p)

    audios, subs = [], []
    for s in d["streams"]:
        if s["codec_type"] == "audio":
            n = len(audios) + 1
            audios.append({"idx": len(audios), "nombre": etiqueta(s, n)
                           + f" ({s.get('codec_name', '?')}, {s.get('channels', '?')} canales)"})
        elif s["codec_type"] == "subtitle":
            texto = s.get("codec_name") in SUBS_TEXTO
            subs.append({"idx": len(subs), "texto": texto, "codec": s.get("codec_name", "?"),
                         "nombre": etiqueta(s, len(subs) + 1) + ("" if texto else " (imagen)")})
    ancho, alto = int(video.get("width") or 0), int(video.get("height") or 0)
    sar = video.get("sample_aspect_ratio") or "1:1"
    try:
        a, b = (int(x) for x in sar.split(":"))
        par = a / b if a and b else 1
    except ValueError:
        par = 1
    return {"ruta": ruta, "duracion": dur, "ancho": ancho, "alto": alto,
            "proporcion": (ancho * par / alto) if alto else 16 / 9,
            "audios": audios, "subs": subs, "bytes": int(d["format"].get("size") or 0)}


def cuadro(ruta, segundo, ancho=640):
    """Un cuadro de la película en PNG (para la vista previa)."""
    r = _correr([FFMPEG, "-v", "error", "-ss", f"{max(0, segundo):.3f}", "-i", ruta, "-frames:v", "1",
                 "-vf", f"scale={ancho}:-2", "-f", "image2", "-c:v", "png", "pipe:1"], timeout=20)
    return r.stdout if r.returncode == 0 and r.stdout else None


# ─── Partes que quedan ───────────────────────────────────────────────────────
def partes_que_quedan(duracion, inicio, fin, sacar):
    """De [inicio, fin] le resta los tramos de `sacar`. Devuelve [(desde, hasta)]."""
    fin = min(fin or duracion, duracion)
    quedan = [(max(0.0, inicio), fin)]
    for a, b in sorted(sacar):
        nuevo = []
        for x, y in quedan:
            if b <= x or a >= y:
                nuevo.append((x, y))
                continue
            if a > x:
                nuevo.append((x, a))
            if b < y:
                nuevo.append((b, y))
        quedan = nuevo
    return [(x, y) for x, y in quedan if y - x >= 0.5]


# ─── Calidad según el tamaño ─────────────────────────────────────────────────
def plan(duracion_final, gb, norma="PAL", resolucion="auto"):
    """Cuánta calidad de imagen entra para llegar a `gb` gigas, y en qué
    resolución. Devuelve también una frase para mostrar."""
    bits = gb * 1024 ** 3 * 8 * MARGEN
    total_kbps = bits / duracion_final / 1000
    video = total_kbps - AUDIO_KBPS
    limitado = None
    if video > VIDEO_MAX_KBPS:
        video, limitado = VIDEO_MAX_KBPS, "max"
    if video < VIDEO_MIN_KBPS:
        video, limitado = VIDEO_MIN_KBPS, "min"
    if resolucion == "auto":
        resolucion = "completa" if video >= UMBRAL_MEDIA_KBPS else "media"
    estimado = (video + AUDIO_KBPS) * 1000 * duracion_final / 8 / MARGEN
    if video >= 4500:
        calidad = "Muy buena"
    elif video >= 2500:
        calidad = "Buena"
    elif video >= 1300:
        calidad = "Aceptable (media resolución)" if resolucion == "media" else "Justa: conviene media resolución"
    else:
        calidad = "Baja: hay poco espacio para tanta película"
    return {"video_kbps": int(video), "audio_kbps": AUDIO_KBPS, "resolucion": resolucion,
            "ancho": ANCHOS[resolucion], "alto": NORMAS[norma]["alto"], "estimado_bytes": int(estimado),
            "calidad": calidad, "limitado": limitado}


# ─── La conversión ───────────────────────────────────────────────────────────
class Cancelado(Exception):
    pass


def _filtros(info, partes, p, norma, audio_idx, sub, carpeta):
    """El armado de la imagen y el sonido: subtítulos, cortes, tamaño de DVD."""
    alto = NORMAS[norma]["alto"]
    ancha = info["proporcion"] >= 1.5               # 16:9 o más ancha; si no, 4:3
    pantalla_w = round(alto * (16 / 9 if ancha else 4 / 3) / 2) * 2
    f, entradas = [], []

    v = "[0:v:0]"
    if sub and sub.get("archivo"):                  # .srt aparte (copiado a la carpeta temporal)
        f.append(f"{v}subtitles=sub.srt:force_style='FontSize=24,Outline=2'[vs]")
        v = "[vs]"
    elif sub and sub.get("idx") is not None:
        if sub.get("texto"):                        # los que trae la película, de texto (extraídos antes)
            f.append(f"{v}subtitles=subs.ass:force_style='FontSize=24,Outline=2'[vs]")
            entradas.append("subs.ass")
        else:                                       # los que trae, en imagen (DVD, Blu-ray)
            f.append(f"[0:s:{sub['idx']}]scale={info['ancho']}:{info['alto']}[sb];{v}[sb]overlay[vs]")
        v = "[vs]"

    a = f"[0:a:{audio_idx}]" if info["audios"] else None
    n = len(partes)
    if n == 1 and partes[0][0] < 0.05 and partes[0][1] >= info["duracion"] - 0.05:
        vv, aa = v, a
    else:
        f.append(f"{v}split={n}" + "".join(f"[v{i}]" for i in range(n)) if n > 1 else f"{v}null[v0]")
        if a:
            f.append(f"{a}asplit={n}" + "".join(f"[a{i}]" for i in range(n)) if n > 1 else f"{a}anull[a0]")
        une = ""
        for i, (x, y) in enumerate(partes):
            f.append(f"[v{i}]trim=start={x:.3f}:end={y:.3f},setpts=PTS-STARTPTS[vc{i}]")
            if a:
                f.append(f"[a{i}]atrim=start={x:.3f}:end={y:.3f},asetpts=PTS-STARTPTS[ac{i}]")
            une += f"[vc{i}]" + (f"[ac{i}]" if a else "")
        f.append(f"{une}concat=n={n}:v=1:a={1 if a else 0}[vj]" + ("[aj]" if a else ""))
        vv, aa = "[vj]", ("[aj]" if a else None)

    # Al tamaño de DVD sin deformar: entra en la pantalla (con franjas negras si
    # hace falta) y después se lleva a los píxeles del DVD.
    f.append(f"{vv}scale={pantalla_w}:{alto}:force_original_aspect_ratio=decrease,"
             f"pad={pantalla_w}:{alto}:(ow-iw)/2:(oh-ih)/2,scale={p['ancho']}:{alto},"
             f"fps={NORMAS[norma]['fps']},setsar=1,format=yuv420p[vo]")
    if aa:
        f.append(f"{aa}aresample=48000,aformat=channel_layouts=stereo[ao]")
    return ";".join(f), ("16:9" if ancha else "4:3"), bool(aa), entradas


def convertir(info, salida, gb=1.0, norma="PAL", resolucion="auto", inicio=0.0, fin=None, sacar=(),
              audio_idx=0, sub=None, al_avanzar=None, cancelar=None):
    """Convierte a .vob. `al_avanzar(fraccion, texto)` informa el avance;
    `cancelar` es un threading.Event para cortar a mitad de camino."""
    salida = os.path.abspath(salida)
    partes = partes_que_quedan(info["duracion"], inicio, fin, sacar)
    if not partes:
        raise ValueError("No queda nada de la película con esos cortes.")
    dur = sum(y - x for x, y in partes)
    p = plan(dur, gb, norma, resolucion)

    tmp = tempfile.mkdtemp(prefix="editor_vob_")
    try:
        if sub and sub.get("archivo"):
            shutil.copyfile(os.path.abspath(sub["archivo"]), os.path.join(tmp, "sub.srt"))
        filtros, aspecto, con_audio, entradas = _filtros(info, partes, p, norma, audio_idx, sub, tmp)
        if "subs.ass" in entradas:                   # se sacan aparte: el filtro los lee por un nombre simple
            al_avanzar and al_avanzar(0, "Preparando los subtítulos…")
            r = _correr([FFMPEG, "-v", "error", "-y", "-i", info["ruta"], "-map", f"0:s:{sub['idx']}",
                         os.path.join(tmp, "subs.ass")], cwd=tmp)
            if r.returncode:
                raise RuntimeError("No se pudieron leer los subtítulos de la película.")

        vbr = p["video_kbps"]
        comun = [FFMPEG, "-hide_banner", "-nostdin", "-y", "-i", info["ruta"], "-filter_complex", filtros,
                 "-map", "[vo]", "-c:v", "mpeg2video", "-b:v", f"{vbr}k",
                 "-maxrate", f"{min(9000, max(vbr * 2, vbr + 1500))}k", "-minrate", "0", "-bufsize", "1835k",
                 "-g", "15" if norma == "PAL" else "18", "-bf", "2", "-aspect", aspecto,
                 "-dc", "10", "-sc_threshold", "1000000000", "-flags", "+cgop",
                 "-passlogfile", os.path.join(tmp, "pasada"), "-progress", "pipe:1", "-stats_period", "0.5"]
        audio = ["-map", "[ao]", "-c:a", "ac3", "-b:a", f"{AUDIO_KBPS}k"] if con_audio else []
        pasadas = [
            (1, comun + ["-pass", "1"] + audio + ["-f", "vob", os.devnull]),
            (2, comun + ["-pass", "2"] + audio + ["-f", "vob", "-packetsize", "2048", "-muxrate", "10080000", salida]),
        ]
        for num, args in pasadas:
            _ejecutar(args, tmp, dur, num, al_avanzar, cancelar)
        tam = os.path.getsize(salida)
        return {"bytes": tam, "duracion": dur, "plan": p, "partes": partes}
    except Cancelado:
        try:
            os.remove(salida)
        except OSError:
            pass
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _ejecutar(args, cwd, dur, pasada, al_avanzar, cancelar):
    proc = subprocess.Popen(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=SIN_VENTANA, text=True, encoding="utf-8", errors="replace")
    errores = []
    hilo = threading.Thread(target=lambda: errores.extend(proc.stderr.readlines()), daemon=True)
    hilo.start()
    nombre = "Midiendo la película" if pasada == 1 else "Convirtiendo"
    for linea in proc.stdout:
        if cancelar is not None and cancelar.is_set():
            proc.kill()
            proc.wait()
            raise Cancelado()
        m = re.match(r"out_time_us=(\d+)", linea) or re.match(r"out_time_ms=(\d+)", linea)
        if m and al_avanzar:
            seg = int(m.group(1)) / 1e6
            frac = min(1.0, seg / dur) if dur else 0
            al_avanzar((pasada - 1 + frac) / 2, f"{nombre} (paso {pasada} de 2)… {int(frac * 100)} %")
    proc.wait()
    hilo.join(timeout=2)
    if cancelar is not None and cancelar.is_set():
        raise Cancelado()
    if proc.returncode:
        detalle = "".join(errores[-12:]).strip()
        raise RuntimeError(f"ffmpeg falló en el paso {pasada}:\n{detalle[-1200:]}")


def hhmmss(seg):
    seg = max(0, int(round(seg)))
    return f"{seg // 3600}:{seg % 3600 // 60:02d}:{seg % 60:02d}"


def leer_tiempo(txt):
    """'1:02:03', '62:03', '3723' → segundos. None si no se entiende."""
    txt = (txt or "").strip().replace(",", ".")
    if not txt:
        return None
    try:
        partes = [float(x) for x in txt.split(":")]
    except ValueError:
        return None
    s = 0.0
    for x in partes:
        s = s * 60 + x
    return s
