"""
Editor de películas para los buses — la ventana.

Abrís una película, marcás desde dónde hasta dónde va (y si hay partes del
medio para sacar), elegís el audio y los subtítulos, ponés cuánto querés que
pese (1 GB) y lo guarda en .vob listo para el pendrive.

El trabajo lo hace motor.py (con ffmpeg); esto es solo la ventana.
"""

import base64
import os
import queue
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import motor as M

# ─── Colores ─────────────────────────────────────────────────────────────────
FONDO = "#0E1626"
PANEL = "#16213A"
PANEL2 = "#1D2B4A"
LINEA = "#2A3A5E"
TEXTO = "#EAF0FA"
SUAVE = "#93A3C2"
ACENTO = "#3B82F6"
ACENTO2 = "#60A5FA"
VERDE = "#34D399"
ROJO = "#F87171"
AMARILLO = "#FBBF24"
FUENTE = ("Segoe UI", 10) if M.EN_WINDOWS else ("DejaVu Sans", 10)
FUENTE_B = (FUENTE[0], 10, "bold")
FUENTE_T = (FUENTE[0], 15, "bold")
FUENTE_N = (FUENTE[0], 22, "bold")
FUENTE_CH = (FUENTE[0], 9)


class Editor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Editor de películas · DVD (.vob)")
        self.configure(bg=FONDO)
        self.geometry("1180x760")
        self.minsize(1000, 680)
        self.info = None
        self.inicio, self.fin = 0.0, 0.0
        self.sacar = []            # [(desde, hasta)]
        self.marca_sacar = None    # desde, mientras se marca un tramo para sacar
        self.posicion = 0.0
        self.srt = None
        self.cola = queue.Queue()
        self.cancelar = None
        self.trabajando = False
        self._cuadro_pedido = None
        self._cuadro_img = None
        self._estilos()
        self._armar()
        self.after(80, self._mirar_cola)
        if M.falta_ffmpeg():
            self.after(300, lambda: messagebox.showerror(
                "Falta ffmpeg",
                "No se encontró ffmpeg, que es el programa que hace la conversión.\n\n"
                "Ejecutá «INSTALAR.bat» (una sola vez) o poné la carpeta «ffmpeg» al lado de este programa."))

    # ─── Estilo ──────────────────────────────────────────────────────────────
    def _estilos(self):
        st = ttk.Style(self)
        st.theme_use("clam")
        st.configure(".", background=FONDO, foreground=TEXTO, font=FUENTE, fieldbackground=PANEL2,
                     bordercolor=LINEA, lightcolor=LINEA, darkcolor=LINEA, troughcolor=PANEL2)
        st.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2, foreground=TEXTO, arrowcolor=TEXTO,
                     selectbackground=PANEL2, selectforeground=TEXTO, padding=5)
        st.map("TCombobox", fieldbackground=[("readonly", PANEL2)], foreground=[("readonly", TEXTO)])
        self.option_add("*TCombobox*Listbox.background", PANEL2)
        self.option_add("*TCombobox*Listbox.foreground", TEXTO)
        self.option_add("*TCombobox*Listbox.selectBackground", ACENTO)
        self.option_add("*TCombobox*Listbox.font", FUENTE)
        st.configure("Barra.Horizontal.TProgressbar", troughcolor=PANEL2, background=ACENTO,
                     bordercolor=PANEL2, lightcolor=ACENTO2, darkcolor=ACENTO, thickness=14)
        st.configure("TRadiobutton", background=PANEL, foreground=TEXTO, font=FUENTE)
        st.map("TRadiobutton", background=[("active", PANEL)], indicatorcolor=[("selected", ACENTO)])

    def _boton(self, padre, texto, cmd, tipo="normal", **kw):
        colores = {"normal": (PANEL2, TEXTO, LINEA), "primario": (ACENTO, "white", ACENTO2),
                   "peligro": ("#3A1E28", ROJO, "#4A2530"), "suave": (PANEL, SUAVE, PANEL2)}[tipo]
        b = tk.Button(padre, text=texto, command=cmd, bg=colores[0], fg=colores[1], activebackground=colores[2],
                      activeforeground=colores[1], relief="flat", bd=0, padx=12, pady=6, cursor="hand2",
                      font=FUENTE_B if tipo == "primario" else FUENTE, highlightthickness=0, **kw)
        return b

    def _tarjeta(self, padre, titulo):
        f = tk.Frame(padre, bg=PANEL, highlightbackground=LINEA, highlightthickness=1)
        tk.Label(f, text=titulo.upper(), bg=PANEL, fg=SUAVE, font=(FUENTE[0], 8, "bold")).pack(anchor="w", padx=14, pady=(12, 6))
        return f

    # ─── Armado ──────────────────────────────────────────────────────────────
    def _armar(self):
        arriba = tk.Frame(self, bg=FONDO)
        arriba.pack(fill="x", padx=18, pady=(14, 8))
        tk.Label(arriba, text="🎬  Editor de películas", bg=FONDO, fg=TEXTO, font=FUENTE_T).pack(side="left")
        self._boton(arriba, "📂  Abrir película", self.abrir, "primario").pack(side="right")
        self.lbl_archivo = tk.Label(arriba, text="Abrí una película para empezar (mkv, mp4, avi…)", bg=FONDO, fg=SUAVE, font=FUENTE)
        self.lbl_archivo.pack(side="right", padx=14)

        cuerpo = tk.Frame(self, bg=FONDO)
        cuerpo.pack(fill="both", expand=True, padx=18, pady=(0, 14))
        cuerpo.columnconfigure(0, weight=1)
        cuerpo.columnconfigure(1, weight=0, minsize=330)
        cuerpo.rowconfigure(0, weight=1)

        # ── Izquierda: vista previa y línea de tiempo
        izq = tk.Frame(cuerpo, bg=FONDO)
        izq.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        self.pantalla = tk.Label(izq, bg="#05080F", fg=SUAVE, text="Vista previa", font=FUENTE, anchor="center")
        self.pantalla.pack(fill="both", expand=True)
        self.pantalla.bind("<Configure>", lambda e: self._pedir_cuadro())

        linea = tk.Frame(izq, bg=PANEL, highlightbackground=LINEA, highlightthickness=1)
        linea.pack(fill="x", pady=(10, 0))
        fila = tk.Frame(linea, bg=PANEL)
        fila.pack(fill="x", padx=12, pady=(10, 0))
        self.lbl_pos = tk.Label(fila, text="0:00:00", bg=PANEL, fg=TEXTO, font=(FUENTE[0], 13, "bold"))
        self.lbl_pos.pack(side="left")
        self.lbl_dur = tk.Label(fila, text=" / 0:00:00", bg=PANEL, fg=SUAVE, font=FUENTE)
        self.lbl_dur.pack(side="left")
        for txt, s in reversed((("−1 min", -60), ("−10 s", -10), ("−1 s", -1), ("+1 s", 1), ("+10 s", 10), ("+1 min", 60))):
            self._boton(fila, txt, lambda s=s: self.mover(s), "suave").pack(side="right", padx=1)

        self.tiempo = tk.Canvas(linea, height=58, bg=PANEL, highlightthickness=0, cursor="hand2")
        self.tiempo.pack(fill="x", padx=12, pady=8)
        self.tiempo.bind("<Configure>", lambda e: self._pintar_tiempo())
        self.tiempo.bind("<Button-1>", self._click_tiempo)
        self.tiempo.bind("<B1-Motion>", self._click_tiempo)

        marcas = tk.Frame(linea, bg=PANEL)
        marcas.pack(fill="x", padx=12, pady=(0, 12))
        self._boton(marcas, "⏮  Empieza acá", self.marcar_inicio).pack(side="left")
        self._boton(marcas, "Termina acá  ⏭", self.marcar_fin).pack(side="left", padx=6)
        self.btn_sacar = self._boton(marcas, "✂  Sacar desde acá…", self.marcar_sacar, "peligro")
        self.btn_sacar.pack(side="left", padx=(14, 0))
        self.lbl_ayuda = tk.Label(linea, text="Tocá la línea o usá las flechas ← → para moverte", bg=PANEL, fg=SUAVE, font=FUENTE_CH, anchor="w")
        self.lbl_ayuda.pack(fill="x", padx=12, pady=(0, 10))

        # ── Derecha: opciones y guardar
        der = tk.Frame(cuerpo, bg=FONDO)
        der.grid(row=0, column=1, sticky="nsew")

        t1 = self._tarjeta(der, "Qué queda")
        t1.pack(fill="x")
        self.lbl_corte = tk.Label(t1, text="—", bg=PANEL, fg=TEXTO, font=FUENTE, justify="left", anchor="w")
        self.lbl_corte.pack(fill="x", padx=14)
        self.lista_sacar = tk.Frame(t1, bg=PANEL)
        self.lista_sacar.pack(fill="x", padx=14, pady=(4, 12))

        t2 = self._tarjeta(der, "Audio y subtítulos")
        t2.pack(fill="x", pady=10)
        tk.Label(t2, text="Audio", bg=PANEL, fg=SUAVE, font=FUENTE_CH).pack(anchor="w", padx=14)
        self.cmb_audio = ttk.Combobox(t2, state="readonly", values=["—"])
        self.cmb_audio.pack(fill="x", padx=14, pady=(2, 8))
        tk.Label(t2, text="Subtítulos (quedan dibujados en la imagen)", bg=PANEL, fg=SUAVE, font=FUENTE_CH).pack(anchor="w", padx=14)
        self.cmb_sub = ttk.Combobox(t2, state="readonly", values=["Sin subtítulos"])
        self.cmb_sub.pack(fill="x", padx=14, pady=(2, 4))
        self.cmb_sub.bind("<<ComboboxSelected>>", self._elegir_sub)
        self.cmb_sub.current(0)
        tk.Frame(t2, bg=PANEL, height=8).pack()

        t3 = self._tarjeta(der, "Tamaño del archivo")
        t3.pack(fill="x")
        fila = tk.Frame(t3, bg=PANEL)
        fila.pack(fill="x", padx=14)
        self.var_gb = tk.StringVar(value="1")
        self.ent_gb = tk.Spinbox(fila, from_=0.3, to=4.3, increment=0.1, textvariable=self.var_gb, width=5,
                                 bg=PANEL2, fg=TEXTO, buttonbackground=PANEL2, relief="flat", font=FUENTE_N,
                                 insertbackground=TEXTO, highlightthickness=0, command=self._calcular)
        self.ent_gb.pack(side="left")
        tk.Label(fila, text="GB", bg=PANEL, fg=SUAVE, font=FUENTE_T).pack(side="left", padx=(6, 0))
        self.var_gb.trace_add("write", lambda *a: self._calcular())
        self.lbl_plan = tk.Label(t3, text="", bg=PANEL, fg=TEXTO, font=FUENTE, justify="left", anchor="w", wraplength=290)
        self.lbl_plan.pack(fill="x", padx=14, pady=(8, 4))

        fila = tk.Frame(t3, bg=PANEL)
        fila.pack(fill="x", padx=14, pady=(4, 2))
        tk.Label(fila, text="Resolución", bg=PANEL, fg=SUAVE, font=FUENTE_CH).pack(side="left")
        self.var_res = tk.StringVar(value="auto")
        for v, t in (("auto", "Automática"), ("completa", "Completa"), ("media", "Media")):
            ttk.Radiobutton(fila, text=t, value=v, variable=self.var_res, command=self._calcular).pack(side="left", padx=(8, 0))
        fila = tk.Frame(t3, bg=PANEL)
        fila.pack(fill="x", padx=14, pady=(2, 12))
        tk.Label(fila, text="Norma", bg=PANEL, fg=SUAVE, font=FUENTE_CH).pack(side="left")
        self.var_norma = tk.StringVar(value="PAL")
        for v in ("PAL", "NTSC"):
            ttk.Radiobutton(fila, text=v, value=v, variable=self.var_norma, command=self._calcular).pack(side="left", padx=(8, 0))

        abajo = tk.Frame(der, bg=FONDO)
        abajo.pack(fill="x", side="bottom")
        self.lbl_estado = tk.Label(abajo, text="", bg=FONDO, fg=SUAVE, font=FUENTE, anchor="w", justify="left", wraplength=320)
        self.lbl_estado.pack(fill="x", pady=(0, 6))
        self.barra = ttk.Progressbar(abajo, style="Barra.Horizontal.TProgressbar", maximum=1000)
        self.barra.pack(fill="x", pady=(0, 10))
        self.btn_guardar = self._boton(abajo, "💾  Guardar en .vob", self.guardar, "primario")
        self.btn_guardar.pack(fill="x", ipady=6)
        self.btn_cancelar = self._boton(abajo, "Cancelar", self.cancelar_trabajo, "peligro")

        for k, s in (("<Left>", -1), ("<Right>", 1), ("<Shift-Left>", -10), ("<Shift-Right>", 10),
                     ("<Prior>", 60), ("<Next>", -60)):
            self.bind(k, lambda e, s=s: self.mover(s))
        self._habilitar(False)

    # ─── Abrir ───────────────────────────────────────────────────────────────
    def abrir(self):
        if self.trabajando:
            return
        ruta = filedialog.askopenfilename(title="Elegí la película", filetypes=[
            ("Videos", "*.mkv *.mp4 *.avi *.mov *.m4v *.wmv *.ts *.m2ts *.mpg *.mpeg *.vob *.webm *.flv"),
            ("Todos los archivos", "*.*")])
        if ruta:
            self.cargar(ruta)

    def cargar(self, ruta):
        try:
            info = M.leer(ruta)
        except Exception as e:
            messagebox.showerror("No se pudo abrir", str(e))
            return
        self.info = info
        self.inicio, self.fin, self.sacar, self.marca_sacar, self.posicion = 0.0, info["duracion"], [], None, 0.0
        self.srt = None
        nombre = os.path.basename(ruta)
        self.lbl_archivo.config(text=f"{nombre}  ·  {M.hhmmss(info['duracion'])}  ·  {info['ancho']}×{info['alto']}"
                                     f"  ·  {info['bytes'] / 1024 ** 3:.2f} GB", fg=TEXTO)
        self.lbl_dur.config(text=" / " + M.hhmmss(info["duracion"]))
        self.cmb_audio["values"] = [a["nombre"] for a in info["audios"]] or ["(sin audio)"]
        # Si hay una pista en español, esa por defecto
        esp = next((a["idx"] for a in info["audios"] if any(x in a["nombre"].upper() for x in ("SPA", "ESP", "LAT"))), 0)
        self.cmb_audio.current(esp if info["audios"] else 0)
        self._opciones_sub()
        self._habilitar(True)
        self.title(f"{nombre} · Editor de películas")
        self.lbl_estado.config(text="", fg=SUAVE)
        self.barra["value"] = 0
        self._actualizar()

    def _opciones_sub(self):
        ops = ["Sin subtítulos"] + [s["nombre"] for s in self.info["subs"]] + ["Elegir un archivo .srt…"]
        if self.srt:
            ops.insert(-1, "Archivo: " + os.path.basename(self.srt))
        self.cmb_sub["values"] = ops
        self.cmb_sub.current(len(ops) - 2 if self.srt else 0)

    def _elegir_sub(self, e=None):
        if self.cmb_sub.get() == "Elegir un archivo .srt…":
            r = filedialog.askopenfilename(title="Elegí los subtítulos", filetypes=[("Subtítulos", "*.srt *.ass *.ssa"), ("Todos", "*.*")])
            if r:
                self.srt = r
            self._opciones_sub()

    def _sub_elegido(self):
        v = self.cmb_sub.get()
        if v.startswith("Archivo: ") and self.srt:
            return {"archivo": self.srt}
        for s in self.info["subs"]:
            if s["nombre"] == v:
                return {"idx": s["idx"], "texto": s["texto"]}
        return None

    # ─── Moverse ─────────────────────────────────────────────────────────────
    def mover(self, seg):
        if self.info and not isinstance(self.focus_get(), tk.Spinbox):
            self.ir_a(self.posicion + seg)

    def ir_a(self, seg):
        self.posicion = min(max(0.0, seg), self.info["duracion"])
        self.lbl_pos.config(text=M.hhmmss(self.posicion))
        self._pintar_tiempo()
        self._pedir_cuadro()

    def _click_tiempo(self, e):
        if not self.info:
            return
        w = self.tiempo.winfo_width()
        self.ir_a((min(max(e.x, 0), w) / w) * self.info["duracion"])

    def _pedir_cuadro(self):
        """Pide el cuadro un instante después: si se arrastra la línea, no se
        pide uno por cada píxel."""
        if not self.info:
            return
        if self._cuadro_pedido:
            self.after_cancel(self._cuadro_pedido)
        self._cuadro_pedido = self.after(140, self._traer_cuadro)

    def _traer_cuadro(self):
        self._cuadro_pedido = None
        ruta, seg = self.info["ruta"], self.posicion
        ancho = max(320, min(1280, self.pantalla.winfo_width()))
        threading.Thread(target=lambda: self.cola.put(("cuadro", seg, M.cuadro(ruta, seg, ancho))), daemon=True).start()

    def _mostrar_cuadro(self, png):
        if not png:
            return
        try:
            img = tk.PhotoImage(data=base64.b64encode(png))
        except tk.TclError:
            return
        alto_max = max(100, self.pantalla.winfo_height())
        if img.height() > alto_max:
            f = -(-img.height() // alto_max)
            img = img.subsample(f, f)
        self._cuadro_img = img
        self.pantalla.config(image=img, text="")

    # ─── Marcar ──────────────────────────────────────────────────────────────
    def marcar_inicio(self):
        if self.posicion >= self.fin - 1:
            messagebox.showwarning("Inicio", "El inicio tiene que estar antes del final.")
            return
        self.inicio = self.posicion
        self._actualizar()

    def marcar_fin(self):
        if self.posicion <= self.inicio + 1:
            messagebox.showwarning("Final", "El final tiene que estar después del inicio.")
            return
        self.fin = self.posicion
        self._actualizar()

    def marcar_sacar(self):
        if self.marca_sacar is None:
            self.marca_sacar = self.posicion
            self.btn_sacar.config(text="✂  …hasta acá (sacar)")
            self.lbl_ayuda.config(text=f"Sacando desde {M.hhmmss(self.posicion)}: andá hasta donde termina y tocá «hasta acá»", fg=AMARILLO)
        else:
            a, b = sorted((self.marca_sacar, self.posicion))
            self.marca_sacar = None
            self.btn_sacar.config(text="✂  Sacar desde acá…")
            self.lbl_ayuda.config(text="Tocá la línea o usá las flechas ← → para moverte", fg=SUAVE)
            if b - a < 1:
                messagebox.showwarning("Sacar", "Moviste menos de un segundo: andá hasta donde termina la parte a sacar.")
            else:
                self.sacar.append((a, b))
        self._actualizar()

    def quitar_sacar(self, i):
        del self.sacar[i]
        self._actualizar()

    # ─── Pintar ──────────────────────────────────────────────────────────────
    def _actualizar(self):
        self._pintar_tiempo()
        self._pintar_corte()
        self._calcular()
        self._pedir_cuadro()

    def _pintar_tiempo(self):
        c = self.tiempo
        c.delete("all")
        w, h = c.winfo_width(), 58
        if w < 10:
            return
        c.create_rectangle(0, 14, w, 40, fill=PANEL2, outline="")
        if not self.info:
            return
        d = self.info["duracion"]
        x = lambda s: s / d * w
        partes = M.partes_que_quedan(d, self.inicio, self.fin, self.sacar)
        for a, b in partes:
            c.create_rectangle(x(a), 14, x(b), 40, fill=ACENTO, outline="")
        for a, b in self.sacar:
            c.create_rectangle(x(a), 14, x(b), 40, fill="#7F1D1D", outline="", stipple="gray50")
        if self.marca_sacar is not None:
            a, b = sorted((self.marca_sacar, self.posicion))
            c.create_rectangle(x(a), 14, x(b), 40, fill=AMARILLO, outline="", stipple="gray50")
        for s, col in ((self.inicio, VERDE), (self.fin, ROJO)):
            c.create_line(x(s), 8, x(s), 46, fill=col, width=3)
        # Marcas de tiempo cada 10 o 15 minutos
        paso = 900 if d > 5400 else 600 if d > 1800 else 300 if d > 600 else 60
        for s in range(paso, int(d), paso):
            c.create_line(x(s), 40, x(s), 46, fill=SUAVE)
            c.create_text(x(s), 53, text=M.hhmmss(s)[:-3], fill=SUAVE, font=(FUENTE[0], 7))
        px = x(self.posicion)
        c.create_line(px, 4, px, 48, fill="white", width=2)
        c.create_polygon(px - 6, 2, px + 6, 2, px, 10, fill="white", outline="")

    def _pintar_corte(self):
        if not self.info:
            self.lbl_corte.config(text="—")
            return
        partes = M.partes_que_quedan(self.info["duracion"], self.inicio, self.fin, self.sacar)
        dur = sum(b - a for a, b in partes)
        self.lbl_corte.config(text=f"Empieza en {M.hhmmss(self.inicio)} y termina en {M.hhmmss(self.fin)}\n"
                                   f"Duración final: {M.hhmmss(dur)}")
        for w in self.lista_sacar.winfo_children():
            w.destroy()
        for i, (a, b) in enumerate(self.sacar):
            f = tk.Frame(self.lista_sacar, bg=PANEL2)
            f.pack(fill="x", pady=2)
            tk.Label(f, text=f"✂  Sacar {M.hhmmss(a)} → {M.hhmmss(b)}  ({M.hhmmss(b - a)})", bg=PANEL2, fg=TEXTO,
                     font=FUENTE_CH).pack(side="left", padx=8, pady=4)
            tk.Button(f, text="✕", command=lambda i=i: self.quitar_sacar(i), bg=PANEL2, fg=ROJO, relief="flat", bd=0,
                      activebackground=PANEL2, cursor="hand2").pack(side="right", padx=6)

    def _gb(self):
        try:
            return float(self.var_gb.get().replace(",", "."))
        except ValueError:
            return None

    def _calcular(self):
        if not self.info:
            self.lbl_plan.config(text="")
            return
        gb = self._gb()
        if not gb or gb < 0.01:
            self.lbl_plan.config(text="Poné un tamaño en GB (por ejemplo 1).", fg=AMARILLO)
            return
        partes = M.partes_que_quedan(self.info["duracion"], self.inicio, self.fin, self.sacar)
        dur = sum(b - a for a, b in partes)
        if dur <= 0:
            return
        p = M.plan(dur, gb, self.var_norma.get(), self.var_res.get())
        color = VERDE if p["video_kbps"] >= 2500 else AMARILLO if p["video_kbps"] >= 1300 else ROJO
        extra = ""
        if p["limitado"] == "max":
            extra = f"\nEntra de sobra: el DVD no admite más calidad, va a pesar ≈ {p['estimado_bytes'] / 1024 ** 3:.2f} GB."
        elif p["limitado"] == "min":
            extra = f"\nNo entra en ese tamaño: va a pesar ≈ {p['estimado_bytes'] / 1024 ** 3:.2f} GB con la calidad mínima."
        if gb > 4.0:
            extra += "\nOjo: un pendrive en FAT32 no acepta archivos de más de 4 GB."
        self.lbl_plan.config(fg=color, text=f"{p['calidad']}\n"
                                            f"Imagen {p['ancho']}×{p['alto']} a {p['video_kbps']} kbps · sonido AC-3 {p['audio_kbps']} kbps{extra}")

    # ─── Guardar ─────────────────────────────────────────────────────────────
    def guardar(self):
        if not self.info or self.trabajando:
            return
        gb = self._gb()
        if not gb or gb < 0.01:
            messagebox.showwarning("Tamaño", "Poné un tamaño en GB (por ejemplo 1).")
            return
        if self.marca_sacar is not None:
            messagebox.showwarning("Sacar", "Estás marcando una parte para sacar: tocá «hasta acá» o volvé a tocar para terminar.")
            return
        base = os.path.splitext(os.path.basename(self.info["ruta"]))[0]
        salida = filedialog.asksaveasfilename(title="Guardar como", defaultextension=".vob", initialfile=base + ".vob",
                                              filetypes=[("Video de DVD", "*.vob")])
        if not salida:
            return
        if not salida.lower().endswith(".vob"):
            salida += ".vob"
        if os.path.abspath(salida) == os.path.abspath(self.info["ruta"]):
            messagebox.showerror("Guardar", "Elegí otro nombre: no se puede guardar encima de la película original.")
            return
        audio = self.cmb_audio.current() if self.info["audios"] else 0
        args = dict(gb=gb, norma=self.var_norma.get(), resolucion=self.var_res.get(), inicio=self.inicio, fin=self.fin,
                    sacar=list(self.sacar), audio_idx=max(0, audio), sub=self._sub_elegido())
        self.cancelar = threading.Event()
        self.trabajando = True
        self._habilitar(False)
        self.btn_guardar.pack_forget()
        self.btn_cancelar.pack(fill="x", ipady=6)
        self.barra["value"] = 0
        self.t0 = time.time()
        self.lbl_estado.config(text="Arrancando…", fg=SUAVE)

        def trabajo():
            try:
                r = M.convertir(self.info, salida, al_avanzar=lambda f, t: self.cola.put(("avance", f, t)),
                                cancelar=self.cancelar, **args)
                self.cola.put(("listo", salida, r))
            except M.Cancelado:
                self.cola.put(("cancelado",))
            except Exception as e:
                self.cola.put(("error", str(e)))
        threading.Thread(target=trabajo, daemon=True).start()

    def cancelar_trabajo(self):
        if self.cancelar and messagebox.askyesno("Cancelar", "¿Cortar la conversión? Lo que se hizo hasta ahora se pierde."):
            self.cancelar.set()
            self.lbl_estado.config(text="Cancelando…")

    def _terminar(self):
        self.trabajando = False
        self.btn_cancelar.pack_forget()
        self.btn_guardar.pack(fill="x", ipady=6)
        self._habilitar(True)

    def _mirar_cola(self):
        try:
            while True:
                m = self.cola.get_nowait()
                if m[0] == "cuadro":
                    if self.info and abs(m[1] - self.posicion) < 0.01:
                        self._mostrar_cuadro(m[2])
                elif m[0] == "avance":
                    f, txt = m[1], m[2]
                    self.barra["value"] = int(f * 1000)
                    pasado = time.time() - self.t0
                    falta = pasado / f - pasado if f > 0.02 else None
                    self.lbl_estado.config(text=txt + (f"\nFaltan ≈ {M.hhmmss(falta)}" if falta else ""), fg=SUAVE)
                elif m[0] == "listo":
                    salida, r = m[1], m[2]
                    self.barra["value"] = 1000
                    self._terminar()
                    gb = r["bytes"] / 1024 ** 3
                    self.lbl_estado.config(fg=VERDE, text=f"✓ Listo: {os.path.basename(salida)} · {gb:.2f} GB · "
                                                         f"{M.hhmmss(r['duracion'])} · tardó {M.hhmmss(time.time() - self.t0)}")
                    if messagebox.askyesno("Listo", f"Se guardó {os.path.basename(salida)} ({gb:.2f} GB).\n\n¿Abrir la carpeta?"):
                        self._abrir_carpeta(salida)
                elif m[0] == "cancelado":
                    self._terminar()
                    self.barra["value"] = 0
                    self.lbl_estado.config(text="Conversión cancelada.", fg=AMARILLO)
                elif m[0] == "error":
                    self._terminar()
                    self.lbl_estado.config(text="Hubo un error. Mirá el detalle.", fg=ROJO)
                    messagebox.showerror("No se pudo convertir", m[1])
        except queue.Empty:
            pass
        self.after(80, self._mirar_cola)

    def _abrir_carpeta(self, ruta):
        carpeta = os.path.dirname(ruta)
        if M.EN_WINDOWS:
            os.startfile(carpeta)

    def _habilitar(self, si):
        estado = "normal" if si else "disabled"
        for w in (self.btn_sacar, self.ent_gb):
            w.config(state=estado)
        for w in (self.cmb_audio, self.cmb_sub):
            w.config(state="readonly" if si else "disabled")
        self.btn_guardar.config(state=estado if self.info else "disabled")


if __name__ == "__main__":
    app = Editor()
    if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
        app.after(200, lambda: app.cargar(sys.argv[1]))
    app.mainloop()
