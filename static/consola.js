// ════════════════════════════════════════════════════════════════════════════
// VISTA CONSOLA (solo el administrador)
//
// El sistema presentado como el inicio de una PlayStation 5: arriba la fila de
// divisiones (Flota, Operación, Taller, Corporativos…), al elegir una el fondo
// toma su color y abajo aparecen sus subdivisiones como tarjetas, cada una con
// un dato en vivo. Al entrar a una subdivisión se abre la sección de siempre,
// con una barra arriba para saltar a las otras de la misma división o volver
// al inicio.
//
// Convive con el menú clásico: el botón «Consola» del menú la prende y
// «Vista clásica» la apaga. Se recuerda cuál se usó por última vez.
//
// Se maneja con el mouse, con el teclado (flechas, Enter, Esc) y con un
// joystick (cruceta o palanca, A/✕ para entrar, B/○ para volver, botón
// central para el inicio).
// ════════════════════════════════════════════════════════════════════════════

// Por usuario: en una PC compartida cada uno tiene su vista
const _vcU = String(window.USUARIO_NOMBRE || "");
const VC_CLAVE_VISTA = "santaniana.vista." + _vcU;
const VC_CLAVE_DIV = "santaniana.consola.division." + _vcU;
const VC_CLAVE_SONIDO = "santaniana.consola.sonido." + _vcU;

const vcGs = n => "Gs. " + Math.round(+n || 0).toLocaleString("es-PY");
const vcN = n => (+n || 0).toLocaleString("es-PY");
const vcEsc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const vcPlural = (n, uno, varios) => `${vcN(n)} ${+n === 1 ? uno : varios}`;

// ── Las divisiones y sus subdivisiones ─────────────────────────────────────
// sec: la sección de siempre. abrir: una página aparte. fn: una función.
// dato(r): el número en vivo de la tarjeta → { txt, tono } (tono: "alerta" | "ok" | "")
const VC_DIVISIONES = [
  {
    id: "flota", nombre: "Flota", icono: "ti-bus", tono: "#3D8BDB",
    lema: "Los coches, su estado y sus papeles.",
    cifras: r => [
      r.flota && { n: r.flota.disponibles, de: r.flota.activos, txt: "coches disponibles hoy" },
      r.flota && { n: r.flota.en_taller + r.flota.fuera_servicio, txt: "con OT abierta o fuera de servicio" },
      r.docs && { n: r.docs.vencidos, txt: "documentos vencidos", alerta: r.docs.vencidos > 0 },
    ],
    subs: [
      { sec: "dashboard", nombre: "Dashboard", icono: "ti-layout-dashboard", desc: "El resumen de toda la flota",
        dato: r => r.flota && { txt: `${vcN(r.flota.disponibles)} de ${vcN(r.flota.activos)} disponibles` } },
      { sec: "vehiculos", nombre: "Vehículos", icono: "ti-bus", desc: "La ficha de cada coche",
        dato: r => r.flota && { txt: vcPlural(r.flota.activos, "coche activo", "coches activos") } },
      { sec: "documentos", nombre: "Documentos", icono: "ti-file-text", desc: "Habilitaciones, seguros y vencimientos",
        dato: r => r.docs && (r.docs.vencidos ? { txt: vcPlural(r.docs.vencidos, "vencido", "vencidos"), tono: "alerta" }
                                              : { txt: `${vcN(r.docs.por_vencer)} vencen en 30 días`, tono: r.docs.por_vencer ? "aviso" : "ok" }) },
    ],
  },
  {
    id: "operacion", nombre: "Operación", icono: "ti-route", tono: "#1FB5A8",
    lema: "Las salidas del día y lo que rinden los servicios.",
    cifras: r => [
      r.trafico && { n: r.trafico.total, txt: r.trafico.existe ? "salidas hoy" : "sin tráfico cargado hoy" },
      r.trafico && { n: r.trafico.por_salir, txt: "por salir" },
      r.trafico && { n: r.trafico.sin_coche, txt: "sin coche asignado", alerta: r.trafico.sin_coche > 0 },
    ],
    subs: [
      { sec: "trafico", nombre: "Tráfico", icono: "ti-route", desc: "La planilla de salidas del día",
        dato: r => r.trafico && (r.trafico.existe ? { txt: `${vcN(r.trafico.salieron)} de ${vcN(r.trafico.total)} ya salieron` } : { txt: "Sin planilla hoy", tono: "aviso" }) },
      { sec: "servicios", nombre: "Servicios", icono: "ti-chart-histogram", desc: "Pasajeros y recaudación por servicio" },
      { sec: "comb_rendicion", nombre: "Rendición de combustible", icono: "ti-mail-opened", desc: "Lo que rinden los choferes",
        dato: r => r.combustible && { txt: vcPlural(r.combustible.cargas_hoy, "carga hoy", "cargas hoy") } },
    ],
  },
  {
    id: "taller", nombre: "Taller", icono: "ti-tool", tono: "#F08A3C",
    lema: "Órdenes de trabajo, preventivos y el día a día del taller.",
    cifras: r => [
      r.ots && { n: r.ots.abiertas, txt: "OTs sin cerrar" },
      r.flota && { n: r.flota.en_taller, txt: "coches en el taller" },
      { n: r.correctivos, txt: "correctivos pendientes", alerta: r.correctivos > 0 },
    ],
    subs: [
      { sec: "ots", nombre: "Órdenes de trabajo", icono: "ti-clipboard-check", desc: "Abrir, seguir y cerrar OTs",
        dato: r => r.ots && { txt: `${vcN(r.ots.abiertas)} sin cerrar` } },
      { sec: "pedidos_ot", nombre: "Pedidos de choferes", icono: "ti-inbox", desc: "Lo que reportan desde la ruta",
        dato: r => r.pedidos && { txt: r.pedidos.nuevos ? `${vcN(r.pedidos.nuevos)} sin decidir` : "Nada pendiente",
                                  tono: r.pedidos.urgentes ? "alerta" : r.pedidos.nuevos ? "aviso" : "ok" } },
      { sec: "planes", nombre: "Plan preventivo", icono: "ti-calendar-check", desc: "Qué le toca a cada coche y cuándo",
        dato: r => r.preventivo && (r.preventivo.vencidos ? { txt: `${vcN(r.preventivo.vencidos)} vencidos`, tono: "alerta" }
                                    : { txt: r.preventivo.pronto ? `${vcN(r.preventivo.pronto)} por vencer` : "Al día", tono: r.preventivo.pronto ? "aviso" : "ok" }) },
      { sec: "mantenimientos", nombre: "Mantenimientos", icono: "ti-book", desc: "El catálogo de tareas" },
      { sec: "correctivos", nombre: "Correctivos", icono: "ti-alert-triangle", desc: "Fallas por reparar",
        dato: r => r.correctivos != null && { txt: vcPlural(r.correctivos, "pendiente", "pendientes"), tono: r.correctivos ? "alerta" : "ok" } },
      { sec: "tablero_taller", nombre: "Tablero de control", icono: "ti-layout-grid", desc: "Cómo viene el taller" },
      { sec: "inventario_neu", nombre: "Inventario de neumáticos", icono: "ti-box", desc: "Cubiertas en stock y montadas" },
      { sec: "historial_carga", nombre: "Historial por coche", icono: "ti-timeline-event", desc: "Todo lo que se le hizo a un coche" },
      { sec: "personal", nombre: "Personal de taller", icono: "ti-users", desc: "Mecánicos y turnos" },
      { abrir: "/tablero", nombre: "Tablero (TV)", icono: "ti-device-tv", desc: "La pantalla del taller, en otra pestaña" },
    ],
  },
  {
    id: "coche", nombre: "Por coche", icono: "ti-steering-wheel", tono: "#9B7BF0",
    lema: "Los números de un coche: costos, rendimiento, preventivo y cubiertas.",
    porCoche: true,
    cifras: () => [],
    subs: [
      { sec: "costos", nombre: "Costos", icono: "ti-coin", desc: "Cuánto cuesta mantenerlo" },
      { sec: "kpis", nombre: "KPIs", icono: "ti-chart-bar", desc: "Rendimiento y consumo" },
      { sec: "mantenimiento", nombre: "Preventivo", icono: "ti-tool", desc: "Sus tareas y vencimientos" },
      { sec: "neumaticos", nombre: "Neumáticos", icono: "ti-disc", desc: "Sus cubiertas, posición por posición" },
    ],
  },
  {
    id: "corporativos", nombre: "Corporativos", icono: "ti-building-factory-2", tono: "#35B26F",
    lema: "Los servicios a empresas: asignación, rendiciones y pagos.",
    cifras: r => [
      r.corp_hoy && { n: r.corp_hoy.servicios, txt: "servicios reportados hoy" },
      r.corp_pend && { n: r.corp_pend.servicios, txt: "sin liquidar" },
      r.corp_pend && { plata: r.corp_pend.monto, txt: "a pagar a choferes" },
    ],
    subs: [
      { sec: "corp_asignacion", nombre: "Asignación del día", icono: "ti-calendar-user", desc: "Qué chofer y qué coche en cada tramo",
        dato: r => r.corp_hoy && { txt: vcPlural(r.corp_hoy.servicios, "servicio hoy", "servicios hoy") } },
      { sec: "corp_resumen", nombre: "Resumen de rendiciones", icono: "ti-clipboard-check", desc: "Revisar y liquidar",
        dato: r => r.corp_pend && { txt: `${vcN(r.corp_pend.servicios)} sin liquidar · ${vcGs(r.corp_pend.monto)}`, tono: r.corp_pend.servicios ? "aviso" : "ok" } },
      { sec: "corp_historial", nombre: "Histórico de pagos", icono: "ti-receipt", desc: "Lo que ya se pagó" },
      { sec: "corp_empresas", nombre: "Control por empresa", icono: "ti-building-factory", desc: "Lo que se le factura a cada una" },
      { sec: "corp_servicios", nombre: "Servicios", icono: "ti-chart-histogram", desc: "Cuántos y de qué tipo" },
      { sec: "corp_combustible", nombre: "Combustible", icono: "ti-gas-station", desc: "Cargas de los coches corporativos" },
      { sec: "corp_cargas", nombre: "Cargas", icono: "ti-map-pin", desc: "Dónde y cuándo se cargó" },
    ],
  },
  {
    id: "turismo", nombre: "Turismo", icono: "ti-beach", tono: "#E9568C",
    lema: "Viajes contratados, de la agenda a la rendición.",
    cifras: r => [
      r.turismo_hoy && { n: r.turismo_hoy.total, txt: "salen hoy" },
      r.turismo_hoy && { n: r.turismo_hoy.en_viaje, txt: "en viaje" },
      { n: r.turismo_rend, txt: "rendiciones para aprobar", alerta: r.turismo_rend > 0 },
    ],
    subs: [
      { sec: "turismo_agenda", nombre: "Agenda de servicios", icono: "ti-calendar-event", desc: "Los viajes de cada día",
        dato: r => r.turismo_hoy && { txt: `${vcN(r.turismo_hoy.total)} hoy · ${vcN(r.turismo_hoy.en_viaje)} en viaje`,
                                      tono: r.turismo_hoy.sin_asignar ? "alerta" : "" } },
      { sec: "turismo_rendiciones", nombre: "Rendiciones de viaje", icono: "ti-receipt-2", desc: "Gastos y saldos de cada viaje",
        dato: r => r.turismo_rend != null && { txt: `${vcN(r.turismo_rend)} para aprobar`, tono: r.turismo_rend ? "aviso" : "ok" } },
      { sec: "turismo", nombre: "Presupuestos", icono: "ti-bus-stop", desc: "Cotizar un viaje" },
    ],
  },
  {
    id: "pasajes", nombre: "Pasajes", icono: "ti-ticket", tono: "#E5404F",
    lema: "La venta de boletos, las agencias y sus controles.",
    cifras: r => [
      r.alpha_hoy && { n: r.alpha_hoy.boletos, txt: "boletos vendidos hoy" },
      r.alpha_hoy && { plata: r.alpha_hoy.total, txt: "vendido hoy" },
    ],
    subs: [
      { sec: "alpha", nombre: "Alpha", icono: "ti-ticket", desc: "Vender pasajes",
        dato: r => r.alpha_hoy && { txt: vcPlural(r.alpha_hoy.boletos, "boleto hoy", "boletos hoy") } },
      { sec: "controles", nombre: "Controles", icono: "ti-adjustments-horizontal", desc: "Servicios, tarifas, planos y liquidaciones" },
      { sec: "agencias", nombre: "Agencias y contratos", icono: "ti-building-store", desc: "Quién vende y con qué comisión" },
    ],
  },
  {
    id: "compras", nombre: "Compras", icono: "ti-packages", tono: "#5C7CFA",
    lema: "Repuestos, depósito y proveedores.",
    cifras: r => [
      r.ots && { n: r.ots.en_compras, txt: "OTs esperando repuestos", alerta: r.ots.en_compras > 0 },
    ],
    subs: [
      { sec: "compras", nombre: "Compras / Depósito", icono: "ti-shopping-cart", desc: "Pedidos del taller y entregas",
        dato: r => r.ots && { txt: `${vcN(r.ots.en_compras)} esperando repuestos`, tono: r.ots.en_compras ? "aviso" : "ok" } },
      { sec: "repuestos", nombre: "Inventario de repuestos", icono: "ti-packages", desc: "Stock y movimientos" },
      { sec: "proveedores", nombre: "Proveedores", icono: "ti-address-book", desc: "Contactos y condiciones" },
    ],
  },
  {
    id: "finanzas", nombre: "Finanzas", icono: "ti-cash-register", tono: "#D6A531",
    lema: "Cajas, tesorería y contabilidad.",
    cifras: () => [],
    subs: [
      { sec: "cajas", nombre: "Cajas y tesorería", icono: "ti-cash-register", desc: "Ingresos, egresos y cierres" },
      { abrir: "/contabilidad", mismaPestana: true, nombre: "Contabilidad", icono: "ti-calculator", desc: "Asientos, balances e impuestos" },
    ],
  },
  {
    id: "reportes", nombre: "Reportes", icono: "ti-chart-arcs", tono: "#36B3E8",
    lema: "Los números para decidir.",
    cifras: r => [
      r.ots && { n: r.ots.cerradas_mes, txt: "OTs cerradas este mes" },
      r.combustible && { n: r.combustible.litros_mes, txt: "litros de gasoil este mes" },
    ],
    subs: [
      { sec: "gerencial", nombre: "Reporte gerencial", icono: "ti-report", desc: "El mes de un vistazo" },
      { sec: "oee", nombre: "OEE de flota", icono: "ti-gauge", desc: "Disponibilidad, rendimiento y calidad" },
      { abrir: "/gerencia", nombre: "Panel del gerente", icono: "ti-crown", desc: "Lo que ve la gerencia, en otra pestaña" },
    ],
  },
  {
    id: "auditoria", nombre: "Auditoría", icono: "ti-shield-search", tono: "#B47FD8",
    lema: "Quién hizo qué, y el combustible bajo la lupa.",
    cifras: r => [
      r.combustible && { n: r.combustible.cargas_hoy, txt: "cargas de combustible hoy" },
    ],
    subs: [
      { sec: "combustible", nombre: "Combustible", icono: "ti-gas-station", desc: "Todas las cargas, con sus controles",
        dato: r => r.combustible && { txt: `${vcN(r.combustible.litros_mes)} litros este mes` } },
      { sec: "historial", nombre: "Historial", icono: "ti-history", desc: "Cada cambio, con usuario y hora" },
    ],
  },
  {
    id: "sistema", nombre: "Sistema", icono: "ti-settings", tono: "#8796AC",
    lema: "Usuarios, integraciones con otros sistemas y mantenimiento.",
    cifras: r => [
      { n: r.integ_revisar, txt: "datos recibidos para revisar", alerta: r.integ_revisar > 0 },
    ],
    subs: [
      { fn: "renderUsuarios", nombre: "Usuarios", icono: "ti-users", desc: "Quién entra y qué puede ver" },
      { sec: "integraciones", nombre: "Integraciones", icono: "ti-plug-connected", desc: "Delta, planillas, avisos y API",
        dato: r => r.integ_revisar != null && { txt: r.integ_revisar ? `${vcN(r.integ_revisar)} para revisar` : "Todo en orden", tono: r.integ_revisar ? "alerta" : "ok" } },
      { sec: "salud", nombre: "Salud del sistema", icono: "ti-heartbeat", desc: "Errores, avisos al celular y vigilancia",
        dato: r => r.errores_sin_ver != null && { txt: r.errores_sin_ver ? `${vcN(r.errores_sin_ver)} errores sin mirar` : "Sin errores", tono: r.errores_sin_ver ? "alerta" : "ok" } },
      { sec: "limpieza", nombre: "Limpiar datos de prueba", icono: "ti-eraser", desc: "Borrar lo cargado para probar" },
    ],
  },
];

// La foto de fondo de todas las divisiones: los tres coches de la flota, teñidos
// con el color de cada una. Una división puede tener la suya propia con
// `foto`, `fotoPos`, `fotoPosCel` y `fotoLuz` (hay más en static/consola/ para
// más adelante: operacion.jpg, taller.jpg, turismo.jpg).
const VC_FOTO_GENERAL = { foto: "/static/consola/flota.jpg?v=2", fotoPos: "50% 62%", fotoPosCel: "88% 60%" };

// ── Estado ───────────────────────────────────────────────────────────────────
const vc = {
  activa: false,          // la vista consola está prendida
  enInicio: false,        // se está viendo el inicio (no una sección)
  divs: [],               // las divisiones que existen en este sistema (con sus subs)
  div: 0,                 // división elegida
  sub: 0,                 // tarjeta elegida
  zona: "divs",           // "avisos" | "divs" | "subs": dónde está el foco
  av: 0,                  // aviso elegido
  datos: {},              // los números en vivo
  datosAt: 0,
  actual: null,           // { div, sub } de la sección abierta
  sonido: false,
  mouse: false,           // el mouse se movió desde la última tecla
  timer: null,
  fondo: 0,               // cuál de las dos capas de fondo está visible
};

function vcLeer(k, def) { try { const v = localStorage.getItem(k); return v == null ? def : v; } catch (e) { return def; } }
function vcGuardar(k, v) { try { localStorage.setItem(k, v); } catch (e) { } }

// Las secciones que existen en el menú de este sistema. Lo que la consola no
// conoce (una sección nueva) se agrega solo a la división con el mismo título
// del menú, o a «Sistema», para que nunca quede nada afuera.
function vcSeVe(el) { return el && el.style.display !== "none" && getComputedStyle(el).display !== "none"; }
function vcArmar() {
  // Cada usuario ve su sector: solo las secciones que tiene en su menú
  const enMenu = new Map();
  let grupo = "";
  const links = [...document.querySelectorAll(".sidebar .nav > .nav-item:not([data-sec])")].filter(vcSeVe)
    .map(b => b.getAttribute("onclick") || "");
  document.querySelectorAll(".sidebar .nav > .nav-section, .sidebar .nav > .nav-item[data-sec]").forEach(el => {
    if (el.classList.contains("nav-section")) { grupo = el.textContent.trim(); return; }
    if (!vcSeVe(el)) return;
    enMenu.set(el.dataset.sec, { grupo, nombre: el.textContent.trim(), icono: (el.querySelector(".ti")?.className || "ti ti-point").replace(/^ti\s+/, "") });
  });
  const conocidas = new Set();
  const divs = VC_DIVISIONES.map(d => ({ ...d, subs: d.subs.filter(s => {
    if (s.abrir) return links.some(l => l.includes(`'${s.abrir}'`));
    if (s.fn) return s.fn !== "renderUsuarios" || window.USUARIO_ROL === "admin";
    conocidas.add(s.sec);
    return enMenu.has(s.sec);
  }) }));
  const porNombre = n => divs.find(d => d.nombre.toLowerCase() === String(n).toLowerCase());
  enMenu.forEach((v, sec) => {
    if (conocidas.has(sec)) return;
    const d = porNombre(v.grupo) || divs.find(x => x.id === "sistema");
    d.subs.push({ sec, nombre: v.nombre, icono: v.icono, desc: v.grupo });
  });
  vc.divs = divs.filter(d => d.subs.length);
  [VC_FOTO_GENERAL, ...vc.divs].forEach(d => { if (d.foto && !d._img) { d._img = new Image(); d._img.src = d.foto; } });
}

// ── Prender / apagar ─────────────────────────────────────────────────────────
function vcPrender(irAlInicio = true) {
  vc.activa = true;
  vcGuardar(VC_CLAVE_VISTA, "consola");
  document.body.classList.add("vc-modo");
  vcArmar();
  if (!vc.actual) {
    const sec = document.querySelector(".sidebar .nav-item.active[data-sec]")?.dataset.sec || "dashboard";
    for (let i = 0; i < vc.divs.length && !vc.actual; i++) {
      const k = vc.divs[i].subs.findIndex(s => s.sec === sec);
      if (k >= 0) vc.actual = { div: i, sub: k };
    }
  }
  vcBarra();
  if (irAlInicio) vcInicio();
}
function vcApagar() {
  vc.activa = false;
  vcGuardar(VC_CLAVE_VISTA, "clasica");
  vcCerrarInicio(true);
  document.body.classList.remove("vc-modo");
  document.getElementById("vc-barra")?.remove();
  clearInterval(vc.timer);
}

// ── El inicio ────────────────────────────────────────────────────────────────
function vcInicio() {
  if (!vc.activa) return;
  vc.enInicio = true;
  let o = document.getElementById("consola");
  if (!o) {
    o = document.createElement("div");
    o.id = "consola";
    o.className = "vc";
    o.setAttribute("role", "application");
    o.setAttribute("aria-label", "Inicio de La Santaniana");
    o.innerHTML = `
      <div class="vc-fondo" data-capa="0"></div><div class="vc-fondo" data-capa="1"></div>
      <div class="vc-grano"></div>
      <header class="vc-top">
        <div class="vc-marca"><img src="/static/logo.png" alt=""><span>La Santaniana</span></div>
        <div class="vc-top-der">
          <button type="button" class="vc-ico" onclick="abrirDestino()" title="Buscar un coche o una sección (Ctrl+K)" aria-label="Buscar"><i class="ti ti-search"></i></button>
          <button type="button" class="vc-ico" id="vc-sonido" onclick="vcCambiarSonido()" aria-label="Sonido"></button>
          <button type="button" class="vc-ico vc-ico-txt" onclick="vcApagar()" title="Volver al menú de siempre"><i class="ti ti-layout-sidebar"></i><span>Vista clásica</span></button>
          <div class="vc-yo" title="${vcEsc(window.USUARIO_NOMBRE || "")}">${vcEsc((window.USUARIO_NOMBRE || "A")[0].toUpperCase())}</div>
          <div class="vc-reloj" id="vc-reloj"></div>
        </div>
      </header>
      <section class="vc-avisos" id="vc-avisos" aria-label="Avisos de hoy"></section>
      <nav class="vc-divs" id="vc-divs" aria-label="Divisiones"></nav>
      <section class="vc-hero" id="vc-hero" aria-live="polite"></section>
      <section class="vc-subs-wrap">
        <div class="vc-subs-tit" id="vc-subs-tit"></div>
        <div class="vc-subs" id="vc-subs" role="list"></div>
      </section>
      <footer class="vc-ayuda">
        <span><kbd>←</kbd><kbd>→</kbd> moverse</span><span><kbd>↑</kbd> avisos</span><span><kbd>↓</kbd> subdivisiones</span>
        <span><kbd>Enter</kbd> entrar</span><span><kbd>Esc</kbd> volver</span>
        <span class="vc-pad" id="vc-pad" hidden><i class="ti ti-device-gamepad-2"></i> Joystick conectado</span>
        <span class="vc-firma">Desarrollado por <b>Aureum</b></span>
      </footer>`;
    document.body.appendChild(o);
    o.addEventListener("mousemove", e => { if (e.movementX || e.movementY) vc.mouse = true; }, { passive: true });
    o.querySelector("#vc-divs").addEventListener("wheel", e => {
      if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) { e.currentTarget.scrollLeft += e.deltaY; e.preventDefault(); }
    }, { passive: false });
    o.querySelector("#vc-subs").addEventListener("wheel", e => {
      if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) { e.currentTarget.scrollLeft += e.deltaY; e.preventDefault(); }
    }, { passive: false });
  }
  o.classList.remove("vc-sale");
  vc.mouse = false;
  o.hidden = false;
  document.body.classList.add("vc-en-inicio");
  const guardada = vc.divs.findIndex(d => d.id === vcLeer(VC_CLAVE_DIV, ""));
  if (vc.actual && vc.volviendo) { vc.div = vc.actual.div; vc.sub = vc.actual.sub; vc.zona = "subs"; }
  else {
    // La primera vez, la división de su sector (compras arranca en Compras, el auditor en Corporativos)
    const principal = vc.divs.findIndex(d => d.id === ({ compras: "compras", auditor: "corporativos" }[window.USUARIO_ROL] || ""));
    vc.div = guardada >= 0 ? guardada : Math.max(0, principal);
    vc.sub = 0; vc.zona = "divs";
  }
  vc.volviendo = false;
  vcPintarSonido();
  vcPintarAvisos();
  vcPintarDivs();
  vcElegirDiv(vc.div, { sinSonido: true, inmediato: true });
  vcReloj();
  vcTraerDatos();
  clearInterval(vc.timer);
  vc.timer = setInterval(() => { vcReloj(); if (Date.now() - vc.datosAt > 60000) vcTraerDatos(); }, 1000 * 15);
  vcPadArrancar();
  requestAnimationFrame(() => vcFoco());
}
function vcCerrarInicio(rapido) {
  const o = document.getElementById("consola");
  vc.enInicio = false;
  document.body.classList.remove("vc-en-inicio");
  if (!o) return;
  if (rapido) { o.hidden = true; return; }
  o.classList.add("vc-sale");
  setTimeout(() => { if (!vc.enInicio) o.hidden = true; }, 360);
}

function vcReloj() {
  const el = document.getElementById("vc-reloj");
  if (!el) return;
  const d = new Date();
  el.textContent = d.toLocaleTimeString("es-PY", { hour: "2-digit", minute: "2-digit", hour12: false });
}

async function vcTraerDatos() {
  try {
    const r = await fetch("/api/consola/resumen", { credentials: "same-origin" });
    if (!r.ok) return;
    vc.datos = await r.json();
    vc.datosAt = Date.now();
    if (vc.enInicio) { vcPintarAvisos(); vcPintarBadges(); vcPintarHero(false); vcPintarSubs(false); }
  } catch (e) { /* sin red: se queda con lo que había */ }
}

// ── Avisos: lo que hay que resolver hoy, del sector de cada uno ─────────────
function vcDondeSec(sec) {
  for (let i = 0; i < vc.divs.length; i++) {
    const k = vc.divs[i].subs.findIndex(s => s.sec === sec);
    if (k >= 0) return { div: i, sub: k };
  }
  return null;
}
function vcAvisos() {
  return ((vc.datos && vc.datos.avisos) || []).filter(a => vcDondeSec(a.sec));
}
function vcPintarAvisos() {
  const box = document.getElementById("vc-avisos");
  if (!box) return;
  const avs = vcAvisos();
  if (!vc.datosAt) { box.innerHTML = `<div class="vc-av-tit"><i class="ti ti-bell"></i> Para hoy</div><div class="vc-av-fila"><span class="vc-av vacio">Revisando…</span></div>`; return; }
  if (vc.av >= avs.length) vc.av = Math.max(0, avs.length - 1);
  const alertas = avs.filter(a => a.nivel === "alerta").length;
  box.innerHTML = `
    <div class="vc-av-tit"><i class="ti ${avs.length ? "ti-bell-ringing" : "ti-bell-check"}"></i> Para hoy
      ${avs.length ? `<b class="${alertas ? "alerta" : ""}">${avs.length}</b>` : ""}</div>
    <div class="vc-av-fila" id="vc-av-fila" role="list">
      ${avs.length ? avs.map((a, i) => {
        const donde = vcDondeSec(a.sec), d = vc.divs[donde.div];
        return `<button type="button" role="listitem" class="vc-av ${a.nivel}" data-i="${i}" style="--vc-tono:${d.tono}"
            onclick="vcAbrirAviso(${i})" onmouseenter="vcSobreAviso(${i})">
            <i class="ti ${a.icono || "ti-bell"} vc-av-ico"></i>
            <span class="vc-av-txt"><b>${vcEsc(a.titulo)}</b><small>${vcEsc(a.detalle ? a.detalle + " · " : "")}${vcEsc(d.nombre)}</small></span>
            <i class="ti ti-chevron-right vc-av-ir"></i></button>`;
      }).join("") : `<span class="vc-av ok"><i class="ti ti-circle-check vc-av-ico"></i><span class="vc-av-txt"><b>Todo en orden</b><small>No hay nada urgente en tu sector</small></span></span>`}
    </div>`;
  const fila = box.querySelector("#vc-av-fila");
  fila?.addEventListener("wheel", e => {
    if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) { e.currentTarget.scrollLeft += e.deltaY; e.preventDefault(); }
  }, { passive: false });
  vcMarcarAviso(false);
}
function vcMarcarAviso(scroll = true) {
  document.querySelectorAll("#vc-avisos .vc-av[data-i]").forEach((b, i) => b.classList.toggle("on", vc.zona === "avisos" && i === vc.av));
  if (scroll && vc.zona === "avisos") document.querySelector(`#vc-avisos .vc-av[data-i="${vc.av}"]`)?.scrollIntoView({ behavior: "smooth", inline: "nearest", block: "nearest" });
}
function vcSobreAviso(i) {
  if (!vc.mouse) return;
  vc.zona = "avisos"; vc.av = i;
  vcMarcarAviso(false); vcMarcarSub(false);
}
function vcAbrirAviso(i) {
  const a = vcAvisos()[i];
  const donde = a && vcDondeSec(a.sec);
  if (!donde) return;
  vc.div = donde.div;
  vcAbrir(donde.div, donde.sub);
}
// Cuántos avisos tiene cada división, en su ícono
function vcPintarBadges() {
  const por = {};
  vcAvisos().forEach(a => {
    const d = vcDondeSec(a.sec);
    if (!d) return;
    por[d.div] = por[d.div] || { n: 0, alerta: false };
    por[d.div].n++;
    if (a.nivel === "alerta") por[d.div].alerta = true;
  });
  document.querySelectorAll("#vc-divs .vc-div").forEach((b, i) => {
    let g = b.querySelector(".vc-div-badge");
    const x = por[i];
    if (!x) { g?.remove(); return; }
    if (!g) { g = document.createElement("span"); g.className = "vc-div-badge"; b.querySelector(".vc-div-ico").appendChild(g); }
    g.textContent = x.n;
    g.classList.toggle("alerta", x.alerta);
    g.title = `${x.n} ${x.n === 1 ? "aviso" : "avisos"}`;
  });
}

// ── Dibujo ───────────────────────────────────────────────────────────────────
function vcPintarDivs() {
  const nav = document.getElementById("vc-divs");
  if (!nav) return;
  nav.innerHTML = vc.divs.map((d, i) => `
    <button type="button" class="vc-div" data-i="${i}" style="--vc-tono:${d.tono}" aria-label="${vcEsc(d.nombre)}"
      onclick="vcClicDiv(${i})" onmouseenter="vcSobreDiv(${i})">
      <span class="vc-div-ico"><i class="ti ${d.icono}"></i></span>
      <span class="vc-div-nom">${vcEsc(d.nombre)}</span>
    </button>`).join("");
  vcPintarBadges();
}

function vcElegirDiv(i, op = {}) {
  const n = vc.divs.length;
  if (!n) return;
  i = (i + n) % n;
  const cambio = i !== vc.div || op.inmediato;
  vc.div = i;
  vcGuardar(VC_CLAVE_DIV, vc.divs[i].id);
  document.querySelectorAll("#vc-divs .vc-div").forEach((b, k) => {
    b.classList.toggle("on", k === i);
    b.setAttribute("aria-current", k === i ? "true" : "false");
  });
  const b = document.querySelector(`#vc-divs .vc-div[data-i="${i}"]`);
  b?.scrollIntoView({ behavior: op.inmediato ? "auto" : "smooth", inline: "center", block: "nearest" });
  if (!cambio) return;
  if (!op.mantenerSub) vc.sub = Math.min(vc.sub, vc.divs[i].subs.length - 1);
  vcFondo(vc.divs[i], op.inmediato);
  vcPintarHero(true);
  vcPintarSubs(true);
  if (!op.sinSonido) vcSonar("mover");
}

function vcFondo(d, inmediato) {
  const capas = document.querySelectorAll("#consola .vc-fondo");
  if (capas.length < 2) return;
  const nueva = capas[1 - vc.fondo], vieja = capas[vc.fondo];
  nueva.style.setProperty("--vc-tono", d.tono);
  // La foto propia de la división, o la general de la flota; sin foto, el ícono grande
  const f = d.foto ? d : VC_FOTO_GENERAL;
  nueva.innerHTML = f.foto
    ? `<div class="vc-foto" style="background-image:url('${f.foto}');--vc-foto-pos:${f.fotoPos || "center"};--vc-foto-pos-cel:${f.fotoPosCel || f.fotoPos || "center"};--vc-foto-luz:${f.fotoLuz || 0.62}"></div><div class="vc-foto-tinte"></div>`
    : `<i class="ti ${d.icono} vc-arte"></i>`;
  nueva.classList.toggle("con-foto", !!f.foto);
  if (inmediato) { nueva.style.transition = "none"; requestAnimationFrame(() => { nueva.style.transition = ""; }); }
  nueva.classList.add("on");
  vieja.classList.remove("on");
  vc.fondo = 1 - vc.fondo;
  document.getElementById("consola")?.style.setProperty("--vc-tono", d.tono);
}

function vcCifraHtml(c) {
  if (!c) return "";
  if (c.plata != null) {
    return `<div class="vc-cifra"><b>${vcGs(c.plata)}</b><span>${vcEsc(c.txt)}</span></div>`;
  }
  if (c.n == null) return "";
  return `<div class="vc-cifra ${c.alerta ? "alerta" : ""}"><b>${vcN(c.n)}${c.de != null ? `<small> / ${vcN(c.de)}</small>` : ""}</b><span>${vcEsc(c.txt)}</span></div>`;
}

function vcPintarHero(animar) {
  const h = document.getElementById("vc-hero");
  if (!h) return;
  const d = vc.divs[vc.div], r = vc.datos || {};
  let cifras = "";
  try { cifras = (d.cifras(r) || []).filter(Boolean).map(vcCifraHtml).join(""); } catch (e) { cifras = ""; }
  const sinDatos = !vc.datosAt;
  let coche = "";
  if (d.porCoche) {
    const c = typeof cocheActual !== "undefined" ? cocheActual : null;
    coche = c
      ? `<div class="vc-coche"><i class="ti ti-bus"></i><div><b>${vcEsc(c.n_interno ? "#" + c.n_interno : c.patente)}</b><span>${vcEsc([c.patente, c.marca, c.modelo].filter(Boolean).join(" · "))}</span></div>
           <button type="button" class="vc-btn-2" onclick="vcCambiarCoche()"><i class="ti ti-switch-horizontal"></i> Otro coche</button></div>`
      : `<div class="vc-coche vacio"><i class="ti ti-bus-off"></i><div><b>Ningún coche elegido</b><span>Al entrar te pregunta cuál</span></div>
           <button type="button" class="vc-btn-2" onclick="vcCambiarCoche()"><i class="ti ti-search"></i> Elegir coche</button></div>`;
  }
  const sub0 = d.subs[0];
  h.innerHTML = `
    <div class="vc-hero-in ${animar ? "vc-entra" : ""}">
      <div class="vc-hero-eti"><i class="ti ${d.icono}"></i> División</div>
      <h1 class="vc-hero-tit">${vcEsc(d.nombre)}</h1>
      <p class="vc-hero-lema">${vcEsc(d.lema)}</p>
      ${coche}
      ${cifras ? `<div class="vc-cifras ${sinDatos ? "cargando" : ""}">${cifras}</div>` : (sinDatos && !d.porCoche ? `<div class="vc-cifras cargando"><div class="vc-cifra"><b>—</b><span>cargando…</span></div></div>` : "")}
      <div class="vc-hero-acc">
        <button type="button" class="vc-btn" onclick="vcAbrir(${vc.div}, 0)"><i class="ti ti-player-play-filled"></i> Abrir ${vcEsc(sub0.nombre)}</button>
      </div>
    </div>`;
}

function vcSubDato(s, r) {
  if (!s.dato) return null;
  try { return s.dato(r) || null; } catch (e) { return null; }
}

function vcPintarSubs(animar) {
  const cont = document.getElementById("vc-subs"), tit = document.getElementById("vc-subs-tit");
  if (!cont) return;
  const d = vc.divs[vc.div], r = vc.datos || {};
  tit.innerHTML = `<span>${vcEsc(d.nombre)}</span> · ${vcPlural(d.subs.length, "subdivisión", "subdivisiones")}`;
  cont.style.setProperty("--vc-tono", d.tono);
  cont.innerHTML = d.subs.map((s, k) => {
    const dato = vcSubDato(s, r);
    const fuera = s.abrir && !s.mismaPestana;
    return `
    <button type="button" class="vc-sub ${animar ? "vc-entra" : ""}" role="listitem" data-k="${k}" style="--vc-retraso:${Math.min(k, 8) * 35}ms"
      onclick="vcClicSub(${k})" onmouseenter="vcSobreSub(${k})">
      <span class="vc-sub-ico"><i class="ti ${s.icono}"></i></span>
      ${fuera ? `<i class="ti ti-external-link vc-sub-fuera" title="Se abre en otra pestaña"></i>` : ""}
      <span class="vc-sub-nom">${vcEsc(s.nombre)}</span>
      <span class="vc-sub-desc">${vcEsc(s.desc || "")}</span>
      ${dato ? `<span class="vc-sub-dato ${dato.tono || ""}"><i></i>${vcEsc(dato.txt)}</span>` : `<span class="vc-sub-dato vacio"></span>`}
    </button>`;
  }).join("");
  vcMarcarSub(false);
}

function vcMarcarSub(scroll = true) {
  document.querySelectorAll("#vc-subs .vc-sub").forEach((b, k) => b.classList.toggle("on", vc.zona === "subs" && k === vc.sub));
  document.getElementById("consola")?.classList.toggle("vc-zona-subs", vc.zona !== "divs");
  vcMarcarAviso(false);
  if (scroll && vc.zona === "subs") {
    document.querySelector(`#vc-subs .vc-sub[data-k="${vc.sub}"]`)?.scrollIntoView({ behavior: "smooth", inline: "nearest", block: "nearest" });
  }
}

// El foco del teclado acompaña lo que está marcado (para lectores de pantalla y Tab)
function vcFoco() {
  if (!vc.enInicio) return;
  const el = vc.zona === "subs" ? document.querySelector(`#vc-subs .vc-sub[data-k="${vc.sub}"]`)
           : vc.zona === "avisos" ? document.querySelector(`#vc-avisos .vc-av[data-i="${vc.av}"]`)
           : document.querySelector(`#vc-divs .vc-div[data-i="${vc.div}"]`);
  el?.focus({ preventScroll: true });
}

// ── Mouse ────────────────────────────────────────────────────────────────────
function vcClicDiv(i) {
  if (i === vc.div && vc.zona === "divs") { vc.zona = "subs"; vc.sub = 0; vcMarcarSub(); vcFoco(); vcSonar("mover"); return; }
  vc.zona = "divs";
  vcElegirDiv(i);
  vcMarcarSub(false);
  vcFoco();
}
function vcSobreDiv(i) { /* como en la consola: se elige con clic, no al pasar */ }
function vcSobreSub(k) {
  // Solo si el mouse se movió: una tarjeta que aparece debajo del puntero
  // quieto (al abrir la consola o al cambiar de división) no se roba el foco
  if (!vc.mouse) return;
  if (vc.zona === "subs" && vc.sub === k) return;
  vc.zona = "subs"; vc.sub = k;
  vcMarcarSub(false);
}
function vcClicSub(k) { vcAbrir(vc.div, k); }

// ── Teclado ──────────────────────────────────────────────────────────────────
function vcHayAlgoAbierto() {
  return !!document.querySelector(".destino-overlay, .modal-overlay, .firma-overlay, .tr-modal-fondo, .al-modal-fondo, [role=dialog]:not(#consola)");
}
function vcTecla(e) {
  if (!vc.activa) return;
  vc.mouse = false;
  const t = e.target, escribiendo = t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
  if (!vc.enInicio) {
    // Dentro de una sección: Esc vuelve al inicio solo si no hay nada abierto
    if (e.key === "Escape" && !escribiendo && !vcHayAlgoAbierto()) { e.preventDefault(); vcVolver(); }
    return;
  }
  if (vcHayAlgoAbierto() || escribiendo) return;
  const k = e.key;
  if (k === "ArrowRight" || k === "ArrowLeft") {
    e.preventDefault();
    const paso = k === "ArrowRight" ? 1 : -1;
    if (vc.zona === "divs") vcElegirDiv(vc.div + paso);
    else if (vc.zona === "avisos") {
      const n = vcAvisos().length;
      const nuevo = Math.max(0, Math.min(n - 1, vc.av + paso));
      if (nuevo !== vc.av) { vc.av = nuevo; vcMarcarAviso(); vcSonar("mover"); } else vcSonar("tope");
    } else {
      const n = vc.divs[vc.div].subs.length;
      const nuevo = Math.max(0, Math.min(n - 1, vc.sub + paso));
      if (nuevo !== vc.sub) { vc.sub = nuevo; vcMarcarSub(); vcSonar("mover"); } else vcSonar("tope");
    }
    vcFoco();
  } else if (k === "ArrowDown") {
    e.preventDefault();
    if (vc.zona === "avisos") { vc.zona = "divs"; vcMarcarSub(false); vcSonar("mover"); vcFoco(); }
    else if (vc.zona === "divs") { vc.zona = "subs"; vc.sub = Math.min(vc.sub, vc.divs[vc.div].subs.length - 1); vcMarcarSub(); vcSonar("mover"); vcFoco(); }
  } else if (k === "ArrowUp") {
    e.preventDefault();
    if (vc.zona === "subs") { vc.zona = "divs"; vcMarcarSub(); vcSonar("mover"); vcFoco(); }
    else if (vc.zona === "divs" && vcAvisos().length) { vc.zona = "avisos"; vcMarcarSub(false); vcMarcarAviso(); vcSonar("mover"); vcFoco(); }
  } else if (k === "Enter" || k === " ") {
    e.preventDefault();
    if (vc.zona === "divs") { vc.zona = "subs"; vc.sub = 0; vcMarcarSub(); vcSonar("mover"); vcFoco(); }
    else if (vc.zona === "avisos") vcAbrirAviso(vc.av);
    else vcAbrir(vc.div, vc.sub);
  } else if (k === "Escape" || k === "Backspace") {
    e.preventDefault();
    if (vc.zona !== "divs") { vc.zona = "divs"; vcMarcarSub(); vcSonar("mover"); vcFoco(); }
    else if (vc.actual) vcVolverASeccion();
  } else if (k === "Home") {
    e.preventDefault(); vc.zona = "divs"; vcElegirDiv(0); vcMarcarSub(false); vcFoco();
  } else if (k === "End") {
    e.preventDefault(); vc.zona = "divs"; vcElegirDiv(vc.divs.length - 1); vcMarcarSub(false); vcFoco();
  } else if (/^[1-9]$/.test(k) && vc.divs[+k - 1]) {
    vc.zona = "divs"; vcElegirDiv(+k - 1); vcMarcarSub(false); vcFoco();
  }
}
window.addEventListener("keydown", vcTecla, true);

// ── Entrar a una subdivisión ─────────────────────────────────────────────────
function vcAbrir(di, k) {
  const d = vc.divs[di], s = d && d.subs[k];
  if (!s) return;
  vcSonar("entrar");
  if (s.abrir && !s.mismaPestana) { window.open(s.abrir, "_blank"); return; }
  if (s.abrir) { window.location.href = s.abrir; return; }
  // Animación: la tarjeta se agranda mientras el inicio se va
  const card = vc.enInicio && document.querySelector(`#vc-subs .vc-sub[data-k="${k}"]`);
  if (card) card.classList.add("vc-elegida");
  vc.actual = { div: di, sub: k };
  const desdeInicio = vc.enInicio;
  vcCerrarInicio(false);
  vcAnimarEntrada(desdeInicio);
  if (s.fn) { if (typeof window[s.fn] === "function") window[s.fn](); }
  else {
    document.querySelectorAll(".nav-item").forEach(b => b.classList.toggle("active", b.dataset.sec === s.sec));
    irA(s.sec);
  }
  vcBarra();
}
function vcVolver() { vcSonar("volver"); vc.volviendo = true; vcInicio(); }

// La sección que se abre entra subiendo: primero el título, después cada bloque
// en cascada. Si la sección trae sus datos más tarde, lo que llega también sube.
function vcAnimarEntrada(desdeInicio) {
  const c = document.getElementById("content");
  if (!c) return;
  c.classList.remove("vc-entra", "vc-entra-tarde");
  void c.offsetWidth;                       // reinicia la animación aunque sea la misma sección
  c.classList.add("vc-entra");
  if (desdeInicio) c.classList.add("vc-entra-tarde");   // espera a que el inicio empiece a irse
  clearTimeout(vc.entraT);
  vc.entraT = setTimeout(() => c.classList.remove("vc-entra", "vc-entra-tarde"), 2600);
}
function vcVolverASeccion() {
  // Esc en el inicio, si se venía de una sección: vuelve a ella tal como estaba
  vcSonar("volver");
  vcCerrarInicio(false);
  vcAnimarEntrada(true);
  vcBarra();
}
function vcCambiarCoche() {
  // El selector de coche de siempre: al elegirlo entra a la subdivisión marcada
  const d = vc.divs[vc.div];
  const s = d.subs[vc.zona === "subs" ? vc.sub : 0] || d.subs[0];
  if (typeof elegirCocheYIr !== "function" || !s?.sec) return;
  vc.actual = { div: vc.div, sub: d.subs.indexOf(s) };
  elegirCocheYIr(s.sec);
}

// ── La barra de arriba cuando se está dentro de una sección ──────────────────
function vcBarra() {
  if (!vc.activa) return;
  const main = document.querySelector(".main");
  if (!main) return;
  let b = document.getElementById("vc-barra");
  if (!b) {
    b = document.createElement("div");
    b.id = "vc-barra";
    b.className = "vc-barra";
    main.insertBefore(b, main.firstChild);
  }
  const a = vc.actual && vc.divs[vc.actual.div];
  const der = `
    <div class="vc-barra-der">
      <button type="button" class="vc-barra-ico" onclick="abrirDestino()" title="Buscar (Ctrl+K)" aria-label="Buscar"><i class="ti ti-search"></i></button>
      <button type="button" class="vc-barra-ico" onclick="vcApagar()" title="Vista clásica" aria-label="Vista clásica"><i class="ti ti-layout-sidebar"></i></button>
    </div>`;
  if (!a) {
    b.innerHTML = `<button type="button" class="vc-home" onclick="vcVolver()" title="Inicio (Esc)"><i class="ti ti-home-2"></i><span>Inicio</span></button><div style="flex:1"></div>${der}`;
    return;
  }
  b.style.setProperty("--vc-tono", a.tono);
  b.innerHTML = `
    <button type="button" class="vc-home" onclick="vcVolver()" title="Volver al inicio (Esc)"><i class="ti ti-home-2"></i><span>Inicio</span></button>
    <div class="vc-barra-div"><i class="ti ${a.icono}"></i><span>${vcEsc(a.nombre)}</span></div>
    <div class="vc-barra-tabs" role="tablist">
      ${a.subs.map((s, k) => `<button type="button" role="tab" class="vc-tab ${k === vc.actual.sub ? "on" : ""}" aria-selected="${k === vc.actual.sub}"
          onclick="vcAbrir(${vc.actual.div}, ${k})"><i class="ti ${s.icono}"></i>${vcEsc(s.nombre)}${s.abrir && !s.mismaPestana ? ` <i class="ti ti-external-link vc-tab-fuera"></i>` : ""}</button>`).join("")}
    </div>${der}`;
  b.querySelector(".vc-tab.on")?.scrollIntoView({ block: "nearest", inline: "center" });
}

// Si se navega por otro camino (el buscador, un enlace dentro de una sección),
// la barra sigue a la sección que quedó abierta
(function vcSeguirNavegacion() {
  if (typeof irA !== "function") return;
  const original = irA;
  window.irA = irA = function (sec) {
    const r = original.apply(this, arguments);
    if (vc.activa) {
      const ya = vc.actual && vc.divs[vc.actual.div]?.subs[vc.actual.sub];
      if (!ya || ya.sec !== sec) {
        for (let i = 0; i < vc.divs.length; i++) {
          const k = vc.divs[i].subs.findIndex(s => s.sec === sec);
          if (k >= 0) { vc.actual = { div: i, sub: k }; break; }
        }
      }
      const c = document.getElementById("content");
      if (!c || !c.classList.contains("vc-entra")) vcAnimarEntrada(vc.enInicio);
      if (vc.enInicio) vcCerrarInicio(false);
      vcBarra();
    }
    return r;
  };
})();

// ── Sonido (apagado de entrada) ──────────────────────────────────────────────
let _vcAudio = null;
function vcSonar(tipo) {
  if (!vc.sonido) return;
  try {
    _vcAudio = _vcAudio || new (window.AudioContext || window.webkitAudioContext)();
    const ctx = _vcAudio, t = ctx.currentTime;
    const notas = { mover: [880, 0.035, 0.05], tope: [330, 0.05, 0.04], entrar: [660, 0.09, 0.07], volver: [520, 0.07, 0.05] }[tipo] || [700, 0.04, 0.04];
    const o = ctx.createOscillator(), g = ctx.createGain();
    o.type = "sine";
    o.frequency.setValueAtTime(notas[0], t);
    if (tipo === "entrar") o.frequency.exponentialRampToValueAtTime(notas[0] * 1.5, t + notas[1]);
    if (tipo === "volver") o.frequency.exponentialRampToValueAtTime(notas[0] * 0.7, t + notas[1]);
    g.gain.setValueAtTime(0.0001, t);
    g.gain.exponentialRampToValueAtTime(notas[2], t + 0.008);
    g.gain.exponentialRampToValueAtTime(0.0001, t + notas[1] + 0.06);
    o.connect(g).connect(ctx.destination);
    o.start(t); o.stop(t + notas[1] + 0.08);
  } catch (e) { }
}
function vcCambiarSonido() {
  vc.sonido = !vc.sonido;
  vcGuardar(VC_CLAVE_SONIDO, vc.sonido ? "1" : "0");
  vcPintarSonido();
  vcSonar("mover");
}
function vcPintarSonido() {
  const b = document.getElementById("vc-sonido");
  if (!b) return;
  b.innerHTML = `<i class="ti ${vc.sonido ? "ti-volume" : "ti-volume-off"}"></i>`;
  b.title = vc.sonido ? "Apagar los sonidos" : "Prender los sonidos";
}

// ── Joystick ─────────────────────────────────────────────────────────────────
// Botones estándar: 0 = A/✕ (entrar), 1 = B/○ (volver), 12-15 = cruceta,
// 16 = botón central (inicio). Palanca izquierda = ejes 0 y 1.
const _vcPad = { corriendo: false, antes: {}, repetir: {} };
function vcPadArrancar() {
  if (_vcPad.corriendo || !navigator.getGamepads) return;
  const hay = [...navigator.getGamepads()].some(Boolean);
  const aviso = document.getElementById("vc-pad");
  if (aviso) aviso.hidden = !hay;
  if (!hay) return;
  _vcPad.corriendo = true;
  requestAnimationFrame(vcPadLeer);
}
window.addEventListener("gamepadconnected", () => { const a = document.getElementById("vc-pad"); if (a) a.hidden = false; vcPadArrancar(); });
window.addEventListener("gamepaddisconnected", () => { if (![...navigator.getGamepads()].some(Boolean)) { _vcPad.corriendo = false; const a = document.getElementById("vc-pad"); if (a) a.hidden = true; } });
function vcPadLeer(ts) {
  if (!_vcPad.corriendo) return;
  const p = [...navigator.getGamepads()].find(Boolean);
  if (p && vc.activa) {
    const b = i => !!(p.buttons[i] && p.buttons[i].pressed);
    const ax = p.axes[0] || 0, ay = p.axes[1] || 0;
    const estado = {
      der: b(15) || ax > 0.55, izq: b(14) || ax < -0.55, abajo: b(13) || ay > 0.55, arriba: b(12) || ay < -0.55,
      a: b(0), b: b(1), home: b(16) || b(9),
    };
    const tecla = { der: "ArrowRight", izq: "ArrowLeft", abajo: "ArrowDown", arriba: "ArrowUp", a: "Enter", b: "Escape" };
    for (const [k, on] of Object.entries(estado)) {
      const antes = _vcPad.antes[k];
      if (on && !antes) {
        _vcPad.repetir[k] = ts + 380;
        vcPadAccion(k, tecla[k]);
      } else if (on && ["der", "izq"].includes(k) && ts > (_vcPad.repetir[k] || 0)) {
        _vcPad.repetir[k] = ts + 130;      // mantener apretado: sigue moviéndose
        vcPadAccion(k, tecla[k]);
      }
      _vcPad.antes[k] = on;
    }
  }
  requestAnimationFrame(vcPadLeer);
}
function vcPadAccion(k, tecla) {
  if (k === "home") { if (vc.enInicio) { vc.zona = "divs"; vcMarcarSub(false); vcFoco(); } else vcVolver(); return; }
  if (!vc.enInicio) { if (k === "b" && !vcHayAlgoAbierto()) vcVolver(); return; }
  vcTecla({ key: tecla, target: document.body, preventDefault() { } });
}

// ── Botón para prenderla, en el menú clásico ─────────────────────────────────
(function vcArrancar() {
  vc.sonido = vcLeer(VC_CLAVE_SONIDO, "0") === "1";
  const acc = document.querySelector(".user-actions");
  if (acc && !document.getElementById("vc-prender")) {
    const b = document.createElement("button");
    b.id = "vc-prender";
    b.className = "user-btn";
    b.title = "Ver el sistema como una consola";
    b.innerHTML = `<i class="ti ti-device-gamepad-2"></i><span class="btn-txt">Consola</span>`;
    b.onclick = () => vcPrender(true);
    acc.insertBefore(b, acc.firstChild);
  }
  if (vcLeer(VC_CLAVE_VISTA, "") === "consola") vcPrender(true);
})();
