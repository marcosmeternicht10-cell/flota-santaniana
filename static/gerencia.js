// Panel del gerente: lee /api/gerencia/panel y pinta cómo viene el día y la
// plata del mes. Solo lectura: no hay nada que guardar desde acá.
"use strict";

const G = { fecha: null, mes: null, d: null, todas: false, soloSin: false, parados: false, cargado: 0 };
const NF = new Intl.NumberFormat("es-PY", { maximumFractionDigits: 0 });
const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
  "setiembre", "octubre", "noviembre", "diciembre"];
const NOMBRE = (() => {
  const t = (document.getElementById("gSaludo").textContent || "").trim().replace(/,/g, " ");
  const p = t.split(/\s+/).filter(Boolean);
  // "FRANCO, JAVIER" → Javier · "Javier Franco" → Javier
  const n = (t === t.toUpperCase() && p.length > 1) ? p[p.length - 1] : (p[0] || "");
  return n ? n[0].toUpperCase() + n.slice(1).toLowerCase() : "";
})();

function num(n) { return NF.format(Math.round(n || 0)); }
function gs(n) { return "Gs. " + num(n); }
function corto(n) {
  n = Math.round(n || 0);
  const a = Math.abs(n);
  const f = (v, dec) => v.toLocaleString("es-PY", { maximumFractionDigits: dec });
  if (a >= 1e9) return f(n / 1e9, 2) + " mil M";
  if (a >= 1e6) return f(n / 1e6, a >= 1e8 ? 0 : 1) + " M";
  if (a >= 1e3) return f(n / 1e3, 0) + " mil";
  return String(n);
}
function gsCorto(n) { return "Gs. " + corto(n); }
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function plural(n, uno, varios) { return `${num(n)} ${n === 1 ? uno : varios}`; }
function cap(s) { s = String(s || ""); return s ? s[0].toUpperCase() + s.slice(1) : s; }
function isoMas(iso, dias) {
  const d = new Date(iso + "T12:00:00");
  d.setDate(d.getDate() + dias);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function minutos(h) { return (+String(h).slice(0, 2)) * 60 + (+String(h).slice(3, 5)); }

// ─── Carga ──────────────────────────────────────────────────────────────────
async function gCargar() {
  const act = document.getElementById("gAct");
  act.classList.add("g-girando");
  const q = new URLSearchParams();
  if (G.fecha) q.set("fecha", G.fecha);
  if (G.mes) q.set("mes", G.mes);
  try {
    const r = await fetch("/api/gerencia/panel?" + q.toString(), { credentials: "same-origin", cache: "no-store" });
    if (r.status === 401) { location.href = "/login"; return; }
    if (!r.ok) throw new Error("HTTP " + r.status);
    G.d = await r.json();
    G.cargado = Date.now();
    pintar();
    act.innerHTML = `<i class="ti ti-refresh"></i> Actualizado ${esc(G.d.actualizado)}`;
  } catch (e) {
    act.innerHTML = `<i class="ti ti-wifi-off"></i> Sin conexión, reintento en un rato`;
  } finally {
    act.classList.remove("g-girando");
  }
}

function gMoverDia(n) {
  if (!G.d) return;
  const f = isoMas(G.d.operacion.fecha, n);
  G.fecha = f === G.d.hoy ? null : f;
  G.todas = false; G.soloSin = false;
  gCargar();
}
function gIrHoy() { G.fecha = null; G.todas = false; G.soloSin = false; gCargar(); }
function gMes(m) { G.mes = m; gCargar(); }
function gVerTodas() { G.todas = !G.todas; G.soloSin = false; pintarOperacion(); }
function gSoloSin() { G.soloSin = !G.soloSin; G.todas = false; pintarOperacion(); }
function gVerParados() { G.parados = !G.parados; pintarOperacion(); }
async function gSalir() {
  try { await fetch("/api/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }); } catch (e) { /* sigue */ }
  location.href = "/login";
}

// ─── Pintado ────────────────────────────────────────────────────────────────
function pintar() {
  const d = G.d, op = d.operacion;
  document.getElementById("gSaludo").textContent = NOMBRE ? `${d.saludo}, ${NOMBRE}` : d.saludo;
  document.getElementById("gFecha").textContent = op.fecha_larga;
  document.getElementById("gResumen").innerHTML = resumenHero(op);
  document.getElementById("gBtnHoy").classList.toggle("g-activo", op.es_hoy);
  document.getElementById("gOpTit").textContent = op.es_hoy ? "Cómo viene el día" : cap(op.fecha_larga);
  pintarOperacion();
  pintarPlata();
}

function resumenHero(op) {
  const t = op.trafico, tu = op.turismo, fl = op.flota;
  const partes = [];
  if (!t.existe) {
    partes.push(op.es_hoy ? "Todavía no se cargó el tráfico de hoy." : "Ese día no tiene tráfico cargado.");
  } else if (op.es_hoy) {
    partes.push(`Hoy hay <b>${plural(t.total, "salida", "salidas")}</b> en el tráfico: ` +
      `${num(t.salieron)} ya ${t.salieron === 1 ? "salió" : "salieron"} y ${num(t.por_salir)} ${t.por_salir === 1 ? "está" : "están"} por salir.`);
  } else {
    partes.push(`<b>${plural(t.total, "salida", "salidas")}</b> en el tráfico de ese día.`);
  }
  if (t.existe && t.sin_coche) {
    partes.push(`<span class="g-alerta-txt">${plural(t.sin_coche, "salida todavía no tiene", "salidas todavía no tienen")} coche.</span>`);
  } else if (t.existe && t.total) {
    partes.push("Todas tienen coche.");
  }
  if (tu.total) partes.push(`Turismo: ${plural(tu.total, "servicio", "servicios")}.`);
  partes.push(`Hay <b>${num(fl.disponibles)} de ${num(fl.activos)}</b> coches disponibles.`);
  return partes.join(" ");
}

// ─── Operación del día ─────────────────────────────────────────────────────
function pintarOperacion() {
  const cont = document.getElementById("gOperacion");
  cont.classList.remove("g-cargando");
  cont.innerHTML = htmlOperacion(G.d.operacion);
}

function htmlOperacion(op) {
  const t = op.trafico, tu = op.turismo, fl = op.flota;
  const pct = t.total ? Math.round(t.salieron * 100 / t.total) : 0;
  const subSalidas = !t.existe ? "sin tráfico cargado"
    : op.es_hoy ? `${num(t.salieron)} salieron · ${num(t.por_salir)} por salir`
      : (op.fecha < G.d.hoy ? `${plural(t.coches, "coche", "coches")} en ruta` : "programadas");
  const tuSub = [];
  if (tu.completados) tuSub.push(`${num(tu.completados)} ${tu.completados === 1 ? "cumplido" : "cumplidos"}`);
  if (tu.sin_asignar) tuSub.push(`${num(tu.sin_asignar)} sin asignar`);
  if (tu.en_viaje.length) tuSub.push(`${num(tu.en_viaje.length)} en viaje`);
  const flSub = [];
  flSub.push(`${num(fl.en_taller)} en taller`);
  if (fl.fuera_servicio) flSub.push(`${num(fl.fuera_servicio)} fuera de servicio`);

  return `
    <div class="g-kpis">
      <div class="g-kpi">
        <div class="g-kpi-lbl"><i class="ti ti-bus"></i> Salidas</div>
        <div class="g-kpi-num">${num(t.total)}</div>
        <div class="g-kpi-sub">${subSalidas}</div>
        ${op.es_hoy && t.total ? `<div class="g-barrita" title="${pct}% del día ya salió"><i style="width:${pct}%"></i></div>` : ""}
      </div>
      <button type="button" class="g-kpi ${t.sin_coche ? "g-rojo" : t.total ? "g-verde" : ""}" onclick="gSoloSin()" ${t.sin_coche ? "" : "disabled"}
        title="${t.sin_coche ? "Ver cuáles son" : ""}">
        <div class="g-kpi-lbl"><i class="ti ${t.sin_coche ? "ti-alert-triangle" : "ti-circle-check"}"></i> Sin coche</div>
        <div class="g-kpi-num">${num(t.sin_coche)}</div>
        <div class="g-kpi-sub">${t.sin_coche ? (G.soloSin ? "mostrando cuáles son" : "tocá para ver cuáles") : (t.total ? "todas tienen coche" : "—")}</div>
      </button>
      <div class="g-kpi">
        <div class="g-kpi-lbl"><i class="ti ti-map-2"></i> Turismo</div>
        <div class="g-kpi-num">${num(tu.total)}</div>
        <div class="g-kpi-sub">${tuSub.join(" · ") || (tu.total ? "agendados" : "sin servicios")}</div>
      </div>
      <button type="button" class="g-kpi" onclick="gVerParados()" title="${G.parados ? "Ocultar" : "Ver"} los coches que no están disponibles">
        <div class="g-kpi-lbl"><i class="ti ti-tool"></i> Flota disponible</div>
        <div class="g-kpi-num">${num(fl.disponibles)}<small>/${num(fl.activos)}</small></div>
        <div class="g-kpi-sub">${flSub.join(" · ")}</div>
      </button>
    </div>
    ${G.parados ? htmlParados(fl) : ""}
    ${htmlFranja(op)}
    <div class="g-dos g-bloque">
      <div>${htmlSalidas(op)}</div>
      <div>${htmlTurismo(op)}</div>
    </div>
    ${htmlCorporativos(op)}`;
}

function htmlParados(fl) {
  if (!fl.parados.length) {
    return `<div class="g-parados"><span class="g-parado">Están todos disponibles</span></div>`;
  }
  return `<div class="g-parados">${fl.parados.map(p => `
    <span class="g-parado ${p.tipo}" title="${esc(p.motivo)} desde el ${esc(p.desde.split("-").reverse().join("/"))}">
      <b>${esc(p.coche)}</b>${p.tipo === "fuera" ? esc(p.motivo) : "en taller"} · ${p.dias ? plural(p.dias, "día", "días") : "desde hoy"}
    </span>`).join("")}</div>`;
}

function htmlFranja(op) {
  const t = op.trafico;
  const conHora = t.salidas.map((s, i) => ({ s, i })).filter(x => x.s.hora);
  if (!conHora.length) return "";
  const pos = m => 2 + (m / 1440) * 96;
  const bins = {};
  conHora.forEach(x => { const b = Math.floor(minutos(x.s.hora) / 20); (bins[b] = bins[b] || []).push(x); });
  const piezas = [];
  Object.values(bins).forEach(lista => {
    lista.forEach((x, k) => {
      const m = minutos(x.s.hora);
      if (k < 3) {
        const cls = x.s.sin_coche ? "sin" : x.s.estado;
        piezas.push(`<button type="button" class="g-dot ${cls}" style="left:${pos(m).toFixed(2)}%;bottom:${28 + k * 17}px"
          data-i="${x.i}" aria-label="${esc(x.s.hora + " " + (x.s.corredor || x.s.destino))}"></button>`);
      } else if (k === 3) {
        piezas.push(`<span class="g-dot-mas" style="left:${pos(m).toFixed(2)}%;bottom:${28 + 3 * 17}px">+${lista.length - 3}</span>`);
      }
    });
  });
  const eje = [0, 3, 6, 9, 12, 15, 18, 21, 24].map(h => `<span style="left:${pos(h * 60)}%">${h} h</span>`).join("");
  let ahora = "";
  if (op.es_hoy && op.hora) {
    const p = pos(minutos(op.hora));
    ahora = `<div class="g-franja-pasado" style="width:${p.toFixed(2)}%"></div>
      <span class="g-franja-ahora" style="left:${Math.min(94, Math.max(6, p)).toFixed(2)}%">Ahora ${esc(op.hora)}</span>`;
  }
  return `
    <div class="g-bloque">
      <div class="g-bloque-cab">
        <h3>Las salidas a lo largo del día</h3>
        <div class="g-leyenda">
          ${op.es_hoy ? `<span><i class="g-pt salio"></i> Ya salió</span><span><i class="g-pt por_salir"></i> Por salir</span>`
            : `<span><i class="g-pt ${op.fecha < G.d.hoy ? "salio" : "programada"}"></i> Salida</span>`}
          <span><i class="g-pt sin"></i> Sin coche</span>
        </div>
      </div>
      <div class="g-franja" id="gFranja">${ahora}${piezas.join("")}<div class="g-franja-eje">${eje}</div></div>
    </div>`;
}

function filaSalida(s) {
  const tramo = s.origen && s.llega ? `${esc(s.origen)} → ${esc(s.llega)}` : esc(s.destino);
  const extra = [];
  if (s.tipo === "internacional") extra.push("Internacional");
  if (s.lado === "regreso") extra.push("regreso");
  const der = s.sin_coche
    ? `<span class="g-pill rojo"><i class="ti ti-alert-triangle"></i> ${s.a_confirmar ? "A confirmar" : "Sin coche"}</span>`
    : `<span class="g-pill coche">${esc(s.coche)}</span>`;
  return `<li class="g-fila ${s.estado === "salio" && !s.sin_coche ? "salio" : ""}">
    <span class="g-hora">${esc(s.hora || "--:--")}</span>
    <div style="min-width:0">
      <div class="g-fila-tit">${esc(s.corredor || s.destino || "Salida")}</div>
      <div class="g-fila-sub">${tramo}${extra.length ? " · " + esc(extra.join(" · ")) : ""}</div>
    </div>
    ${der}
  </li>`;
}

function htmlSalidas(op) {
  const t = op.trafico;
  if (!t.existe || !t.total) {
    return `<div class="g-bloque-cab"><h3>Salidas</h3></div>
      <div class="g-vacio"><i class="ti ti-calendar-off"></i>${op.es_hoy ? "Todavía no se cargó el tráfico de hoy" : "No hay tráfico cargado ese día"}</div>`;
  }
  let lista, titulo;
  if (G.soloSin) {
    lista = t.salidas.filter(s => s.sin_coche);
    titulo = "Salidas sin coche";
  } else if (G.todas) {
    lista = t.salidas;
    titulo = `Todas las salidas (${num(t.total)})`;
  } else if (op.es_hoy) {
    lista = t.salidas.filter(s => s.estado === "por_salir").slice(0, 6);
    titulo = "Próximas salidas";
  } else {
    lista = t.salidas.slice(0, 6);
    titulo = "Primeras salidas del día";
  }
  const cuerpo = lista.length
    ? `<ul class="g-lista">${lista.map(filaSalida).join("")}</ul>`
    : `<div class="g-vacio"><i class="ti ti-circle-check"></i>Ya salieron todas las salidas del día</div>`;
  const boton = G.soloSin
    ? `<button type="button" class="g-mas" onclick="gSoloSin()"><i class="ti ti-arrow-back-up"></i> Volver a las próximas</button>`
    : `<button type="button" class="g-mas" onclick="gVerTodas()">${G.todas ? `<i class="ti ti-chevron-up"></i> Ver menos` : `<i class="ti ti-list"></i> Ver las ${num(t.total)} salidas`}</button>`;
  return `<div class="g-bloque-cab"><h3>${titulo}</h3></div>${cuerpo}${boton}`;
}

const ESTADO_TUR = {
  agendado: ["gris", "Agendado"], confirmado: ["", "Confirmado"], en_curso: ["", "En curso"],
  completado: ["verde", "Cumplido"], cancelado: ["gris", "Cancelado"],
};

function filaTurismo(s, enViaje) {
  const [cls, txt] = ESTADO_TUR[s.estado] || ["gris", s.estado];
  const pills = [];
  if (enViaje) pills.push(`<span class="g-pill gris">Día ${num(s.dia_n)} de ${num(s.dias)}</span>`);
  else if (s.sin_asignar) pills.push(`<span class="g-pill rojo"><i class="ti ti-alert-triangle"></i> Falta ${esc(s.falta || "asignar")}</span>`);
  else pills.push(`<span class="g-pill ${cls}">${esc(txt)}</span>`);
  const sub = [];
  if (s.salida || s.destino) sub.push(`${esc(s.salida || "?")} → ${esc(s.destino || "?")}`);
  if (s.coches.length) sub.push((s.coches.length > 1 ? "coches " : "coche ") + esc(s.coches.join(", ")));
  if (s.pasajeros) sub.push(`${num(s.pasajeros)} pasajeros`);
  return `<li class="g-fila g-fila-2 ${s.estado === "cancelado" ? "salio" : ""}">
    <span class="g-hora">${esc(enViaje ? "···" : (s.hora || "--:--"))}</span>
    <div style="min-width:0">
      <div class="g-fila-tit">${esc(s.cliente)}</div>
      <div class="g-fila-sub">${sub.join(" · ")}</div>
      <div class="g-pills">${pills.join("")}</div>
    </div>
  </li>`;
}

function htmlTurismo(op) {
  const tu = op.turismo;
  const filas = tu.servicios.map(s => filaTurismo(s, false)).concat(tu.en_viaje.map(s => filaTurismo(s, true)));
  return `<div class="g-bloque-cab"><h3>Turismo</h3></div>` + (filas.length
    ? `<ul class="g-lista">${filas.join("")}</ul>`
    : `<div class="g-vacio"><i class="ti ti-beach"></i>No hay servicios de turismo ese día</div>`);
}

function htmlCorporativos(op) {
  const co = op.corporativos;
  const det = co.servicios || co.suspendidos
    ? `<span><b>${plural(co.servicios, "servicio", "servicios")}</b> de corporativos reportados por los choferes` +
      (co.suspendidos ? ` · <span class="g-pill ambar">${plural(co.suspendidos, "suspendido", "suspendidos")}</span>` : "") + `</span>` +
      co.clientes.map(c => `<span class="g-pill gris">${esc(c.cliente)} ${num(c.servicios)}</span>`).join("")
    : `<span>${op.es_hoy ? "Los choferes de corporativos todavía no reportaron servicios de hoy." : "No hay servicios de corporativos reportados ese día."}</span>`;
  return `<div class="g-bloque"><div class="g-linea-info"><i class="ti ti-building-factory-2"></i><div class="g-linea-txt">${det}</div></div></div>`;
}

// ─── Plata del mes ─────────────────────────────────────────────────────────
const COLOR_CAT = { combustible: "var(--c-combustible)", taller: "var(--c-taller)", corporativos: "var(--c-corporativos)" };

function pintarPlata() {
  const p = G.d.plata;
  const actual = p.mes_actual_param;
  const anterior = isoMas(actual + "-01", -1).slice(0, 7);
  document.getElementById("gMeses").innerHTML = [[actual, "Este mes"], [anterior, "Mes pasado"]]
    .map(([m, txt]) => `<button type="button" class="${p.mes === m ? "g-activo" : ""}" onclick="gMes('${m}')">${txt}</button>`).join("");
  document.getElementById("gPlataTit").textContent = cap(p.mes_txt);
  const cont = document.getElementById("gPlata");
  cont.classList.remove("g-cargando");
  cont.innerHTML = htmlPlata(p);
  dibujarGrafico();
}

function deltaTxt(monto, ant) {
  if (!ant) return "";
  const v = Math.round((monto - ant) * 100 / ant);
  if (v === 0) return `<span class="g-delta">igual</span>`;
  return `<span class="g-delta ${v > 0 ? "sube" : "baja"}">${v > 0 ? "▲" : "▼"} ${Math.abs(v)} % ${v > 0 ? "más" : "menos"}</span>`;
}

function detalleCat(c, p) {
  const i = c.info || {};
  if (c.clave === "combustible") {
    const t = [`${num(i.litros)} litros`, plural(i.cargas || 0, "carga", "cargas")];
    if (i.estimadas) t.push("precio estimado");
    return t.join(" · ");
  }
  if (c.clave === "taller") return plural(i.items || 0, "trabajo o repuesto comprado", "trabajos y repuestos comprados");
  if (c.clave === "corporativos") {
    return `${plural(i.servicios || 0, "servicio", "servicios")}${i.pagado ? ` · ${gsCorto(i.pagado)} ya liquidados` : ""}`;
  }
  return "";
}

function htmlPlata(p) {
  const comparaCon = p.es_actual ? `a esta altura de ${p.mes_ant_txt}` : `en ${p.mes_ant_txt}`;
  let variacion;
  if (p.variacion === null || p.variacion === undefined) {
    variacion = `<span class="g-sub">Sin gastos registrados en ${esc(p.mes_ant_txt)} para comparar</span>`;
  } else if (p.variacion === 0) {
    variacion = `<span class="g-pill gris">Igual</span><span>que ${esc(comparaCon)} (${esc(gsCorto(p.total_ant))})</span>`;
  } else {
    const sube = p.variacion > 0;
    variacion = `<span class="g-pill ${sube ? "rojo" : "verde"}">${sube ? "▲" : "▼"} ${Math.abs(p.variacion)} % ${sube ? "más" : "menos"}</span>
      <span>que ${esc(comparaCon)} (${esc(gsCorto(p.total_ant))})</span>`;
  }
  const comb = p.categorias.find(c => c.clave === "combustible");
  const sinPrecio = comb && comb.monto === 0 && comb.info && comb.info.litros > 0;
  const cats = p.categorias.map(c => {
    const share = p.total ? Math.max(c.monto ? 1.5 : 0, c.monto * 100 / p.total) : 0;
    const montoTxt = (c.clave === "combustible" && sinPrecio) ? `<span class="g-sub">sin precio</span>` : esc(gs(c.monto));
    const d = deltaTxt(c.monto, c.monto_ant);
    return `<div class="g-cat">
      <div class="g-cat-cab">
        <span class="g-cat-nom"><i style="background:${COLOR_CAT[c.clave]}"></i>${esc(c.nombre)}</span>
        <span class="g-cat-monto">${montoTxt}</span>
      </div>
      <div class="g-cat-barra"><i style="width:${share.toFixed(1)}%;background:${COLOR_CAT[c.clave]}"></i></div>
      <div class="g-cat-pie"><span>${esc(detalleCat(c, p))}</span>
        <span>${d ? `${d} que ${esc(p.mes_ant_txt)}` : ""}</span></div>
    </div>`;
  }).join("");
  const e = p.espera_fondos;
  const espera = e.items
    ? `<div class="g-espera"><i class="ti ti-hourglass-high"></i><div><b>${esc(gs(e.monto))}</b> esperando fondos de tesorería
        · ${plural(e.items, "trabajo o repuesto", "trabajos y repuestos")}${e.dias_max ? `, el más viejo hace ${plural(e.dias_max, "día", "días")}` : ""}.
        <div style="margin-top:2px">No está sumado en el gasto del mes porque todavía no se pagó.</div></div></div>`
    : `<div class="g-espera ok"><i class="ti ti-circle-check"></i><div>No hay trabajos ni repuestos esperando fondos de tesorería.</div></div>`;
  const notas = [];
  if (comb && comb.info && comb.info.estimadas && comb.info.precio) {
    notas.push(`Combustible: ${plural(comb.info.estimadas, "carga sin precio se valuó", "cargas sin precio se valuaron")} al último precio cargado (${gs(comb.info.precio)} el litro).`);
  }
  if (sinPrecio) notas.push("Combustible: no hay ninguna carga con precio, por eso no se puede pasar a guaraníes. Se muestran los litros.");
  return `
    <div class="g-total-lbl">${p.es_actual ? `Gastado del 1 al ${num(p.hasta_dia)} de ${esc(p.mes_txt.split(" ")[0])}` : `Gastado en ${esc(p.mes_txt)}`}</div>
    <div class="g-total"><small>Gs.</small>${num(p.total)}</div>
    <div class="g-var">${variacion}</div>
    <div class="g-graf">
      <div class="g-graf-leyenda">
        <span><i></i>${esc(cap(p.mes_txt.split(" ")[0]))}, acumulado</span>
        <span><i class="ant"></i>${esc(cap(p.mes_ant_txt))}</span>
      </div>
      <div id="gGraf"></div>
    </div>
    <div class="g-cats">${cats}</div>
    ${espera}
    ${notas.length ? `<div class="g-nota">${notas.map(esc).join("<br>")}</div>` : ""}`;
}

function pasoLindo(bruto) {
  if (bruto <= 0) return 1;
  const e = Math.pow(10, Math.floor(Math.log10(bruto)));
  const f = bruto / e;
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 2.5 ? 2.5 : f <= 5 ? 5 : 10) * e;
}

function dibujarGrafico() {
  const cont = document.getElementById("gGraf");
  const p = G.d && G.d.plata;
  if (!cont || !p) return;
  const act = p.acumulado.actual, ant = p.acumulado.anterior;
  const W = Math.max(280, cont.clientWidth || 560), H = 210;
  const m = { l: 48, r: 14, t: 14, b: 24 };
  const nDias = Math.max(p.dias_mes, p.dias_mes_ant, 2);
  const maxV = Math.max(1, ...act, ...ant);
  const paso = pasoLindo(maxV / 3);
  const tope = Math.ceil(maxV / paso) * paso;
  const x = dia => m.l + (dia - 1) / (nDias - 1) * (W - m.l - m.r);
  const y = v => m.t + (1 - v / tope) * (H - m.t - m.b);
  const linea = serie => serie.map((v, i) => `${i ? "L" : "M"}${x(i + 1).toFixed(1)},${y(v).toFixed(1)}`).join("");
  let s = "";
  for (let v = 0; v <= tope + 1; v += paso) {
    s += `<line x1="${m.l}" x2="${W - m.r}" y1="${y(v)}" y2="${y(v)}" stroke="#EFEDE8" stroke-width="1"/>`;
    s += `<text x="${m.l - 8}" y="${y(v) + 4}" text-anchor="end">${esc(corto(v))}</text>`;
  }
  const marcas = [1, 5, 10, 15, 20, 25, nDias].filter((d, i, a) => d <= nDias && a.indexOf(d) === i && !(d !== nDias && nDias - d < 3));
  marcas.forEach(d => { s += `<text x="${x(d)}" y="${H - 6}" text-anchor="middle">${d}</text>`; });
  if (ant.length) s += `<path d="${linea(ant)}" fill="none" stroke="var(--serie-ant)" stroke-width="2" stroke-dasharray="5 4" stroke-linejoin="round"/>`;
  if (act.length) {
    const area = `${linea(act)}L${x(act.length).toFixed(1)},${y(0)}L${x(1)},${y(0)}Z`;
    s += `<defs><linearGradient id="gArea" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#14263D" stop-opacity=".14"/><stop offset="1" stop-color="#14263D" stop-opacity="0"/></linearGradient></defs>`;
    s += `<path d="${area}" fill="url(#gArea)"/>`;
    s += `<path d="${linea(act)}" fill="none" stroke="var(--navy)" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`;
    const ux = x(act.length), uy = y(act[act.length - 1]);
    s += `<circle cx="${ux}" cy="${uy}" r="4.5" fill="var(--navy)" stroke="#fff" stroke-width="2"/>`;
  }
  s += `<line id="gCruz" x1="0" x2="0" y1="${m.t}" y2="${H - m.b}" stroke="#9AA7B6" stroke-width="1" opacity="0"/>`;
  s += `<circle id="gCruzA" r="4" fill="var(--navy)" stroke="#fff" stroke-width="2" opacity="0"/>`;
  s += `<circle id="gCruzB" r="4" fill="var(--serie-ant)" stroke="#fff" stroke-width="2" opacity="0"/>`;
  s += `<rect id="gZona" x="${m.l}" y="${m.t}" width="${W - m.l - m.r}" height="${H - m.t - m.b}" fill="transparent"/>`;
  cont.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img"
    aria-label="Gasto acumulado día por día de ${esc(p.mes_txt)} contra ${esc(p.mes_ant_txt)}">${s}</svg>`;

  const zona = document.getElementById("gZona");
  const mover = ev => {
    const svg = zona.ownerSVGElement.getBoundingClientRect();
    const px = (ev.touches ? ev.touches[0].clientX : ev.clientX) - svg.left;
    const dia = Math.max(1, Math.min(nDias, Math.round((px - m.l) / (W - m.l - m.r) * (nDias - 1) + 1)));
    const va = act[dia - 1], vb = ant[dia - 1];
    const cx = x(dia);
    const cruz = document.getElementById("gCruz");
    cruz.setAttribute("x1", cx); cruz.setAttribute("x2", cx); cruz.setAttribute("opacity", "1");
    const a = document.getElementById("gCruzA"), b = document.getElementById("gCruzB");
    if (va !== undefined) { a.setAttribute("cx", cx); a.setAttribute("cy", y(va)); a.setAttribute("opacity", "1"); } else a.setAttribute("opacity", "0");
    if (vb !== undefined) { b.setAttribute("cx", cx); b.setAttribute("cy", y(vb)); b.setAttribute("opacity", "1"); } else b.setAttribute("opacity", "0");
    const filas = [];
    if (va !== undefined) filas.push(`${esc(cap(p.mes_txt.split(" ")[0]))}: <b>${esc(gsCorto(va))}</b>`);
    if (vb !== undefined) filas.push(`<span class="g-tip-sub">${esc(cap(p.mes_ant_txt))}: ${esc(gsCorto(vb))}</span>`);
    mostrarTip(`<div class="g-tip-sub">Al día ${dia}</div>${filas.join("<br>")}`,
      svg.left + cx, svg.top + Math.min(y(va ?? 0), y(vb ?? 0)));
  };
  const salir = () => {
    ["gCruz", "gCruzA", "gCruzB"].forEach(id => document.getElementById(id).setAttribute("opacity", "0"));
    ocultarTip();
  };
  zona.addEventListener("mousemove", mover);
  zona.addEventListener("touchstart", mover, { passive: true });
  zona.addEventListener("touchmove", mover, { passive: true });
  zona.addEventListener("mouseleave", salir);
  zona.addEventListener("touchend", () => setTimeout(salir, 1500));
}

// ─── Tooltip ────────────────────────────────────────────────────────────────
function mostrarTip(html, cx, cy) {
  const tip = document.getElementById("gTip");
  tip.innerHTML = html;
  tip.classList.add("ver");
  const r = tip.getBoundingClientRect();
  let left = cx - r.width / 2, top = cy - r.height - 12;
  left = Math.max(8, Math.min(window.innerWidth - r.width - 8, left));
  if (top < 8) top = cy + 16;
  tip.style.left = left + "px";
  tip.style.top = top + "px";
}
function ocultarTip() { document.getElementById("gTip").classList.remove("ver"); }

function tipSalida(btn) {
  const s = G.d.operacion.trafico.salidas[+btn.dataset.i];
  if (!s) return;
  const r = btn.getBoundingClientRect();
  const tramo = s.origen && s.llega ? `${s.origen} → ${s.llega}` : s.destino;
  const estado = s.estado === "salio" ? "ya salió" : s.estado === "por_salir" ? "por salir" : "programada";
  mostrarTip(`<b>${esc(s.hora)}</b> · ${esc(s.corredor || s.destino)}<br>
    <span class="g-tip-sub">${esc(tramo)} · ${esc(estado)}</span><br>
    ${s.sin_coche ? `<span style="color:#FFB3BE">${s.a_confirmar ? "Coche a confirmar" : "Sin coche asignado"}</span>` : `Coche ${esc(s.coche)}`}`,
  r.left + r.width / 2, r.top);
}

document.addEventListener("mouseover", ev => {
  const b = ev.target.closest && ev.target.closest(".g-dot");
  if (b) tipSalida(b);
});
document.addEventListener("mouseout", ev => {
  if (ev.target.closest && ev.target.closest(".g-dot")) ocultarTip();
});
document.addEventListener("focusin", ev => {
  const b = ev.target.closest && ev.target.closest(".g-dot");
  if (b) tipSalida(b);
});
document.addEventListener("focusout", ev => {
  if (ev.target.closest && ev.target.closest(".g-dot")) ocultarTip();
});
document.addEventListener("click", ev => {
  const b = ev.target.closest && ev.target.closest(".g-dot");
  if (b) { tipSalida(b); setTimeout(ocultarTip, 2500); }
});

// ─── Arranque y refresco ───────────────────────────────────────────────────
let _redim = null;
window.addEventListener("resize", () => { clearTimeout(_redim); _redim = setTimeout(dibujarGrafico, 150); });
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && Date.now() - G.cargado > 60 * 1000) gCargar();
});
setInterval(() => { if (document.visibilityState === "visible") gCargar(); }, 5 * 60 * 1000);
gCargar();
