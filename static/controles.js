// controles.js — Controles: el módulo de administración para lo que pasa con
// los servicios y las agencias (como los "Controles" de Delta). Se carga
// después de app.js y alpha.js y usa sus datos y utilidades.
// ════════════════════════════════════════════════════════════════════════════
//   Servicios      las salidas del día con su ocupación; cerrar o abrir la
//                  venta, cancelar; el recorrido con los que suben y bajan
//   Transbordos    se rompe un coche: otro coche sigue la salida o los
//                  pasajeros pasan a otra salida (del mismo día o del siguiente)
//   Agencias       lo que cada una tiene sin liquidar y sin depositar contra el
//                  tope de su contrato; suspender o habilitar
//   Liquidaciones  lo que se le liquida a cada agencia hasta un corte
//   Recaudación    por servicio, por agencia y vendedor, o por día
//   Tarifas        recorridos (paradas), precio de cada tramo y descuentos
//   Planos         el plano de asientos de cada modelo y qué plano usa cada coche
// Lo ve solo administración. Alpha queda para vender.
// ════════════════════════════════════════════════════════════════════════════

const CT_VISTAS = [["servicios", "bus", "Servicios"], ["transbordos", "arrows-shuffle", "Transbordos"], ["programacion", "calendar-event", "Programación"],
                   ["agencias", "building-store", "Agencias"],
                   ["liquidaciones", "report-money", "Liquidaciones"], ["recaudacion", "chart-bar", "Recaudación"],
                   ["tarifas", "currency-dollar", "Tarifas"], ["planos", "armchair", "Planos"]];
const ct = {
  vista: "servicios",
  tb: { origen: "", parada: 0, motivoChip: "", motivo: "", tipo: "coche", coche: "", destDia: 0, destino: "", fuera: [],
        avisar: false, cancelar: true, sug: null, sugDe: "", hecho: null, hist: [], histF: "", manual: {}, selPas: null },
  pg: { tipo: "desactivar", corredor: "", lado: "ida", horario: "", hora: "", destino: "", desde: "", hasta: "", dias: "0123456", plano: "", motivo: "" },
};

async function renderControles() {
  if (typeof status === "function") status("Controles: salidas del día, transbordos, agencias, liquidaciones, recaudación, tarifas y planos");
  if (window.USUARIO_ROL !== "admin") {
    content.innerHTML = `<div class="page-header"><h1>Controles</h1><p>Esta sección es de administración.</p></div>`;
    return;
  }
  if (typeof alCfgTraer !== "function") {
    content.innerHTML = `<div class="section"><div class="empty"><i class="ti ti-alert-triangle"></i>Falta subir <b>static/alpha.js</b>: Controles usa los datos de Alpha.</div></div>`;
    return;
  }
  if (!document.getElementById("al-fuentes")) {
    const l = document.createElement("link");
    l.id = "al-fuentes"; l.rel = "stylesheet";
    l.href = "https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible+Next:wght@400..800&family=Big+Shoulders:opsz,wght@10..72,600..900&display=swap";
    document.head.appendChild(l);
  }
  ctRender(true);
}
function ctIr(v) {
  if (v === ct.vista) return;
  ct.vista = v; alModalCerrar();
  if (v === "planos") { al.pla.draft = null; al.pla.selec = new Set(); }
  if (v === "tarifas") { al.tar.rec = al.tar.pre = al.tar.des = null; }
  ctRender(true);
}
function ctRender(animar) {
  const v = ct.vista;
  if (v === "transbordos") return ctVistaTransbordos(animar);
  if (v === "programacion") return ctVistaProgramacion(animar);
  if (v === "agencias") return ctVistaAgencias(animar);
  if (v === "liquidaciones") return ctVistaLiquidaciones(animar);
  if (v === "recaudacion") return ctVistaRecaudacion(animar);
  if (v === "tarifas") return alVistaTarifas(animar); // los editores viven en alpha.js
  if (v === "planos") return alVistaPlanos(animar);
  return ctVistaServicios(animar);
}
function ctShell(cuerpo, animar) {
  return `<div class="al ct ${animar ? "al-entra" : ""}" id="ct-raiz">
    <header class="al-cab">
      <div class="al-marca"><span class="ct-logo" aria-hidden="true"><i class="ti ti-adjustments-horizontal"></i></span><span class="al-d al-marca-t">Controles</span></div>
      <nav class="al-nav" aria-label="Secciones de Controles">${CT_VISTAS.map(([k, ic, t]) => `<button type="button" class="al-nav-b ${ct.vista === k ? "on" : ""}" aria-current="${ct.vista === k ? "page" : "false"}" onclick="ctIr('${k}')"><i class="ti ti-${ic}"></i><span>${t}</span></button>`).join("")}</nav>
      <div class="al-caja"><button type="button" class="al-sec" onclick="ctAbrirAlpha()"><i class="ti ti-ticket"></i> Ir a Alpha</button></div>
    </header>
    ${cuerpo}
  </div>`;
}
function ctCargando(animar) {
  content.innerHTML = ctShell(`<div class="al-vacio"><i class="ti ti-loader-2 al-gira"></i><b>Trayendo los datos…</b></div>`, animar);
}
function ctAbrirAlpha() {
  alModalCerrar();
  const b = document.querySelector('.nav-item[data-sec="alpha"]');
  if (b) b.click(); else if (typeof renderAlpha === "function") renderAlpha();
}
// La configuración, el tráfico y los asientos de un día (cualquier día, no solo el de Alpha)
async function ctDatos(fecha, forzar) {
  if (!al.cfg) await alCfgTraer();
  const t = [];
  if (forzar || !al.datos[fecha]) t.push(api(`/api/alpha/dia/${fecha}`).then(d => { if (d && d.corredores) al.datos[fecha] = d; }).catch(() => {}));
  if (forzar || !al.ocup[fecha] || Date.now() - ((al.ocupEl || {})[fecha] || 0) > AL_OCUP_FRESCO) t.push(alTraerOcup(fecha, true));
  await Promise.all(t);
}
function ctFechaMas(fecha, d) { const x = alDeISO(fecha); x.setDate(x.getDate() + d); return alISO(x); }
// Los mismos chips de día de Alpha, pero acá repintan Controles
function ctChipsDias() { return alChipsDias().replace(/alDia\(/g, "ctDia(").replace(/alOtraFecha\(/g, "ctOtraFecha("); }
function ctDia(i) { al.dia = i; ctRender(false); }
function ctOtraFecha(v) {
  if (!v) return;
  const i = Math.round((alDeISO(v) - alFechaDe(0)) / 864e5);
  if (i < 0 || i > 90) { toast("Elegí una fecha desde hoy y hasta 3 meses", "error"); return; }
  ctDia(i);
}
function ctHistItem(h) {
  const cuando = `${alDM(h.el.slice(0, 10))} ${h.el.slice(11, 16)} · ${trEsc(h.por || "")}`;
  if (h.transbordo) return `<li><i class="ti ti-arrows-shuffle"></i><div><b>Transbordo: ${h.pasajeros} ${h.pasajeros === 1 ? "pasajero" : "pasajeros"} ${h.transbordo === "coche" ? "siguen en el " + trEsc(String(h.destino || "").replace(/^Coche /, "coche ")) : "a la salida de las " + trEsc(h.destino || "")}${h.estado === "cancelado" ? " · salida cancelada" : ""}</b><small>${trEsc(h.motivo || "")}${h.parada ? " · " + trEsc(h.parada) : ""} · ${cuando}</small></div></li>`;
  const est = CT_EST_SERV[h.estado] || [h.estado || "", ""];
  return `<li><i class="ti ti-${h.estado === "abierto" ? "lock-open" : h.estado === "cerrado" ? "lock" : "ban"}"></i><div><b>${est[0]}${h.motivo ? ": " + trEsc(h.motivo) : ""}</b><small>${cuando}</small></div></li>`;
}

// ════════════════════════════════════════════════════════════════════════════
// LIQUIDACIONES DE LAS AGENCIAS (solo administración)
// Lo que vendió cada agencia hasta un corte: efectivo, tarjeta, transferencia,
// devoluciones, la comisión de su contrato y lo que tiene que depositar.
// ════════════════════════════════════════════════════════════════════════════
const CT_LIQ_COLS = [["venta_ef", "Venta EF"], ["venta_tc", "Venta TC"], ["venta_tr", "Transf."], ["devoluciones", "Devol."], ["ie", "I/E"], ["comision", "Comisión"], ["saldo", "Saldo"], ["saldo_neto", "Saldo neto"]];
async function ctVistaLiquidaciones(animar) {
  if (!document.querySelector(".al-liq")) ctCargando(animar);
  const d = await api("/api/alpha/liquidaciones");
  if (ct.vista !== "liquidaciones" || !d || !d.liquidaciones) return;
  al.liqDatos = d;
  if (!al.liq.hasta) al.liq.hasta = (d.ahora || alAhoraISO()).slice(0, 16);
  const pend = d.agencias.filter(a => a.pendiente_movs);
  const filtro = al.liq.filtro || "";
  const liqs = d.liquidaciones.filter(l => !filtro || String(l.agencia_id) === filtro);
  const fila = l => `<tr class="${l.estado}">
      <td class="al-t-n"><b>${l.id}</b></td><td><b>${trEsc(l.agencia)}</b><small>${l.desde ? alDM(l.desde.slice(0, 10)) + " " + l.desde.slice(11, 16) + " → " : ""}${alDM(l.hasta.slice(0, 10))} ${l.hasta.slice(11, 16)}</small></td>
      ${CT_LIQ_COLS.map(([k]) => `<td class="al-t-m ${k === "saldo_neto" ? "fuerte" : ""}">${fmtNum(l[k])}</td>`).join("")}
      <td class="al-t-c">${l.boletos}</td>
      <td><span class="al-est ${l.estado === "depositada" ? "vendido" : "reserva"}">${l.estado === "depositada" ? "Depositada" : "Pendiente"}</span>${l.estado === "depositada" ? `<small>${alDM(l.depositada_el.slice(0, 10))}${l.referencia ? " · " + trEsc(l.referencia) : ""}</small>` : ""}</td>
      <td class="al-t-a">
        <button type="button" class="al-ic" title="Ver el detalle" aria-label="Detalle" onclick="ctLiqDetalle(${l.id})"><i class="ti ti-list-details"></i></button>
        <button type="button" class="al-ic" title="Imprimir" aria-label="Imprimir" onclick="ctLiqImprimir(${l.id})"><i class="ti ti-printer"></i></button>
        ${l.estado !== "depositada" ? `<button type="button" class="al-ic" title="Marcar como depositada" aria-label="Depositada" onclick="ctLiqDepositada(${l.id})"><i class="ti ti-building-bank"></i></button>` : ""}
        ${l.estado !== "depositada" && l.ultima ? `<button type="button" class="al-ic rojo" title="Deshacer (vuelve a quedar pendiente)" aria-label="Deshacer" onclick="ctLiqDeshacer(${l.id})"><i class="ti ti-arrow-back-up"></i></button>` : ""}
      </td></tr>`;
  const tot = k => liqs.reduce((a, l) => a + (l[k] || 0), 0);
  content.innerHTML = ctShell(`
    <div class="al-vista al-liq">
      <div class="al-v-cab"><h1 class="al-d">Liquidaciones</h1><span>Lo que vendió cada agencia hasta un corte, con la comisión de su contrato y lo que tiene que depositar.</span></div>
      <section class="al-card">
        <div class="al-card-cab"><h2 class="al-d">Generar</h2><span>${pend.length ? `${pend.length} agencia${pend.length === 1 ? "" : "s"} con ventas sin liquidar.` : "No hay ventas de agencias sin liquidar."} La comisión sale del contrato que regía el día de cada venta (Comercial → Agencias).</span></div>
        <div class="al-liq-gen">
          <label class="al-campo"><span>Agencia</span><select id="al-liq-ag" onchange="al.liq.agencia=this.value">
            <option value="todas">Todas las que tienen pendiente</option>
            ${d.agencias.map(a => `<option value="${a.id}" ${String(a.id) === al.liq.agencia ? "selected" : ""}>${trEsc(a.nombre)}${a.pendiente_movs ? ` · ${a.pendiente_movs} mov. · ${alGs(a.pendiente_monto)}` : " · nada pendiente"}</option>`).join("")}
          </select></label>
          <label class="al-campo"><span>Corte (hasta)</span><input type="datetime-local" id="al-liq-hasta" value="${al.liq.hasta}" onchange="al.liq.hasta=this.value"></label>
          <label class="al-check"><input type="checkbox" ${al.liq.soloEf ? "checked" : ""} onchange="al.liq.soloEf=this.checked"> Comisión solo sobre lo cobrado en efectivo</label>
          <button type="button" class="al-sec" onclick="ctLiqPrevia()"><i class="ti ti-eye"></i> Ver lo pendiente</button>
          <button type="button" class="al-btn-r" onclick="ctLiqGenerar()"><i class="ti ti-file-dollar"></i> Generar liquidación</button>
        </div>
        ${pend.length ? `<div class="al-liq-pend">${pend.map(a => `<button type="button" class="al-liq-p" onclick="al.liq.agencia='${a.id}';ctLiqPrevia()"><b>${trEsc(a.nombre)}</b><span>${a.pendiente_movs} movimiento${a.pendiente_movs === 1 ? "" : "s"} desde el ${alDM(a.pendiente_desde.slice(0, 10))}</span><em>${alGs(a.pendiente_monto)}</em></button>`).join("")}</div>` : ""}
      </section>
      <div class="al-man-sel">
        <label class="al-campo"><span>Ver liquidaciones de</span><select onchange="al.liq.filtro=this.value;ctVistaLiquidaciones(false)"><option value="">Todas las agencias</option>${d.agencias.map(a => `<option value="${a.id}" ${String(a.id) === filtro ? "selected" : ""}>${trEsc(a.nombre)}</option>`).join("")}</select></label>
        ${liqs.length ? `<button type="button" class="al-sec" onclick="ctLiqCSV()"><i class="ti ti-file-spreadsheet"></i> CSV</button>` : ""}
      </div>
      ${liqs.length ? `<div class="al-tabla-w"><table class="al-tabla al-liq-t">
        <thead><tr><th>Nro</th><th>Agencia · período</th>${CT_LIQ_COLS.map(([, t]) => `<th class="al-t-m">${t}</th>`).join("")}<th class="al-t-c">Boletos</th><th>Estado</th><th></th></tr></thead>
        <tbody>${liqs.map(fila).join("")}</tbody>
        <tfoot><tr><th></th><th>Total</th>${CT_LIQ_COLS.map(([k]) => `<th class="al-t-m">${fmtNum(tot(k))}</th>`).join("")}<th class="al-t-c">${tot("boletos")}</th><th></th><th></th></tr></tfoot></table></div>`
        : `<div class="al-vacio"><i class="ti ti-report-money"></i><b>Todavía no hay liquidaciones</b><span>Se generan arriba, con el corte que elijas.</span></div>`}
    </div>`, animar);
}
function ctLiqTablaMovs(movs) {
  return `<div class="al-tabla-w"><table class="al-tabla">
    <thead><tr><th>Fecha</th><th>Boleto</th><th>Pasajero</th><th>Viaje</th><th>Movimiento</th><th>Pago</th><th class="al-t-m">Gs.</th><th class="al-t-m">Comisión</th></tr></thead>
    <tbody>${movs.map(m => `<tr><td>${alDM(m.el.slice(0, 10))} ${m.el.slice(11, 16)}</td><td>${m.nro ? alNro(m.nro) : "—"}</td><td>${trEsc(m.nombre)}<small>${trEsc(m.vendedor)}</small></td>
      <td>${m.nro ? `${trEsc(m.origen)} → ${trEsc(m.destino)}<small>${alDM(m.fecha)} ${m.sale}${m.asiento != null ? " · asiento " + m.asiento : ""}</small>` : ""}</td>
      <td>${AL_MOV_TXT[m.t] || m.t}${m.estado_venta && m.estado_venta !== "vendido" && (m.t === "venta" || m.t === "cobro") ? `<small>(${AL_ESTADOS[m.estado_venta] || m.estado_venta})</small>` : ""}</td>
      <td>${(AL_PAGOS.find(p => p[0] === m.pago) || ["", m.pago || ""])[1]}</td>
      <td class="al-t-m ${m.monto < 0 ? "neg" : ""}">${m.monto < 0 ? "−" : ""}${fmtNum(Math.abs(m.monto))}</td>
      <td class="al-t-m">${m.comision ? fmtNum(m.comision) : "—"}${m.comision_txt ? `<small>${trEsc(m.comision_txt)}</small>` : ""}</td></tr>`).join("")}</tbody></table></div>`;
}
function ctLiqResumen(t) {
  return `<div class="al-man-res">${CT_LIQ_COLS.map(([k, n]) => `<div class="${k === "saldo_neto" ? "fuerte" : ""}"><span>${k === "saldo_neto" ? "Saldo neto (a depositar)" : n}</span><b class="al-d">${alGs(t[k])}</b></div>`).join("")}<div><span>Boletos</span><b class="al-d">${t.boletos}</b></div></div>`;
}
async function ctLiqPrevia() {
  const ag = al.liq.agencia && al.liq.agencia !== "todas" ? al.liq.agencia : "";
  if (!ag) { toast("Elegí una agencia para ver lo pendiente", "error"); return; }
  const hasta = (document.getElementById("al-liq-hasta")?.value || al.liq.hasta);
  const t = await api(`/api/alpha/liquidaciones/pendiente?agencia_id=${ag}&hasta=${encodeURIComponent(hasta)}&solo_ef=${al.liq.soloEf ? 1 : 0}`);
  if (!t || !t.movs) return;
  const nombre = ((al.liqDatos?.agencias || []).find(a => String(a.id) === ag) || {}).nombre || "";
  alModal({ titulo: `Pendiente de ${nombre}`, ancho: 1100, cuerpo: t.movs.length
      ? `<p class="al-m-txt">Hasta el ${alDM(hasta.slice(0, 10))} a las ${hasta.slice(11, 16)}.</p>${ctLiqResumen(t)}${ctLiqTablaMovs(t.movs)}`
      : `<p class="al-m-txt">No tiene nada sin liquidar hasta ese corte.</p>`,
    pie: `<button type="button" class="al-sec" onclick="alModalCerrar()">Cerrar</button>${t.movs.length ? `<button type="button" class="al-btn-r" onclick="alModalCerrar();ctLiqGenerar()"><i class="ti ti-file-dollar"></i> Generar esta liquidación</button>` : ""}` });
}
async function ctLiqGenerar() {
  const ag = document.getElementById("al-liq-ag")?.value || al.liq.agencia || "todas";
  const hasta = document.getElementById("al-liq-hasta")?.value || al.liq.hasta;
  const nombre = ag === "todas" ? "todas las agencias con ventas pendientes" : ((al.liqDatos?.agencias || []).find(a => String(a.id) === ag) || {}).nombre;
  if (!confirm(`¿Generar la liquidación de ${nombre} hasta el ${alDM(hasta.slice(0, 10))} a las ${hasta.slice(11, 16)}?`)) return;
  const r = await alPost("/api/alpha/liquidaciones", { agencia_id: ag, hasta, solo_ef: al.liq.soloEf });
  if (!r) return;
  toast(`${r.ids.length} liquidación${r.ids.length === 1 ? "" : "es"} generada${r.ids.length === 1 ? "" : "s"}`, "success");
  ctVistaLiquidaciones(false);
}
async function ctLiqDetalle(id) {
  const l = await api(`/api/alpha/liquidaciones/${id}`);
  if (!l || !l.movs) return;
  alModal({ titulo: `Liquidación ${l.id} · ${l.agencia}`, ancho: 1100,
    cuerpo: `<p class="al-m-txt">${l.desde ? `Del ${alDM(l.desde.slice(0, 10))} ${l.desde.slice(11, 16)} ` : ""}al ${alDM(l.hasta.slice(0, 10))} ${l.hasta.slice(11, 16)} · generada el ${alDM(l.el.slice(0, 10))} por ${trEsc(l.por)}${l.solo_ef ? " · comisión solo sobre efectivo" : ""}.</p>${ctLiqResumen(l)}${ctLiqTablaMovs(l.movs)}`,
    pie: `<button type="button" class="al-sec" onclick="alModalCerrar()">Cerrar</button><button type="button" class="al-btn-r" onclick="ctLiqImprimir(${l.id})"><i class="ti ti-printer"></i> Imprimir</button>` });
}
async function ctLiqImprimir(id) {
  const l = await api(`/api/alpha/liquidaciones/${id}`);
  if (!l || !l.movs) return;
  const e = trEsc;
  const html = `<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Liquidación ${l.id}</title>
<style>@page{size:A4;margin:12mm}*{box-sizing:border-box}body{margin:0;font-family:Arial,sans-serif;color:#000;font-size:11px}
.cab{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:2px solid #000;padding-bottom:6px;margin-bottom:8px}h1{font-size:18px;margin:0}
.res{display:grid;grid-template-columns:repeat(5,1fr);gap:6px;margin:8px 0 12px}.res div{border:1px solid #999;padding:6px}.res span{display:block;font-size:9.5px;text-transform:uppercase;color:#444}.res b{font-size:14px}
.res .f{background:#000;color:#fff;-webkit-print-color-adjust:exact;print-color-adjust:exact}.res .f span{color:#ddd}
table{width:100%;border-collapse:collapse}th,td{border:1px solid #bbb;padding:3px 5px;text-align:left}th{background:#eee;font-size:9.5px;text-transform:uppercase}.n{text-align:right;white-space:nowrap}
.firmas{display:flex;gap:40px;margin-top:40px}.firmas div{flex:1;border-top:1px solid #000;padding-top:4px;text-align:center}.maq{margin-top:12px;font-size:9.5px;color:#555;text-align:center}</style></head><body>
<div class="cab"><div><b>LA SANTANIANA</b><h1>Liquidación ${l.id} · ${e(l.agencia)}</h1></div><span>${l.desde ? "Del " + alDM(l.desde.slice(0, 10)) + "/" + l.desde.slice(0, 4) + " " + l.desde.slice(11, 16) + " " : ""}al ${alDM(l.hasta.slice(0, 10))}/${l.hasta.slice(0, 4)} ${l.hasta.slice(11, 16)}</span></div>
<div class="res">${CT_LIQ_COLS.map(([k, n]) => `<div class="${k === "saldo_neto" ? "f" : ""}"><span>${k === "saldo_neto" ? "Saldo neto a depositar" : n}</span><b>Gs. ${fmtNum(l[k])}</b></div>`).join("")}<div><span>Boletos</span><b>${l.boletos}</b></div></div>
<table><thead><tr><th>Fecha</th><th>Boleto</th><th>Pasajero</th><th>Viaje</th><th>Movimiento</th><th>Pago</th><th class="n">Gs.</th><th class="n">Comisión</th></tr></thead><tbody>
${l.movs.map(m => `<tr><td>${alDM(m.el.slice(0, 10))} ${m.el.slice(11, 16)}</td><td>${m.nro ? alNro(m.nro) : "—"}</td><td>${e(m.nombre)}</td><td>${m.nro ? `${e(m.origen)} → ${e(m.destino)}, ${alDM(m.fecha)} ${m.sale}` : ""}</td><td>${AL_MOV_TXT[m.t] || m.t}</td><td>${(AL_PAGOS.find(p => p[0] === m.pago) || ["", m.pago || ""])[1]}</td><td class="n">${m.monto < 0 ? "−" : ""}${fmtNum(Math.abs(m.monto))}</td><td class="n">${m.comision ? fmtNum(m.comision) : "—"}</td></tr>`).join("")}
</tbody></table>
<div class="firmas"><div>Por la agencia</div><div>Por La Santaniana</div></div>
<div class="maq">Generada el ${alDM(l.el.slice(0, 10))}/${l.el.slice(0, 4)} por ${e(l.por)}${l.estado === "depositada" ? ` · Depositada el ${alDM(l.depositada_el.slice(0, 10))}${l.referencia ? " (" + e(l.referencia) + ")" : ""}` : ""} · Maqueta de Alpha: sin valor fiscal</div></body></html>`;
  alImprimir(html, "210mm");
}
async function ctLiqDepositada(id) {
  const ref = prompt("¿Con qué se depositó? (número de depósito o transferencia, opcional)", "");
  if (ref === null) return;
  const r = await alPost(`/api/alpha/liquidaciones/${id}/depositada`, { referencia: ref });
  if (!r) return;
  toast("Liquidación marcada como depositada", "success");
  ctVistaLiquidaciones(false);
}
async function ctLiqDeshacer(id) {
  if (!confirm(`¿Deshacer la liquidación ${id}? Sus ventas vuelven a quedar pendientes.`)) return;
  const r = await api(`/api/alpha/liquidaciones/${id}`, { method: "DELETE" });
  if (!r || !r.ok) { toast((r && r.msg) || "No se pudo", "error"); return; }
  toast("Liquidación deshecha", "success");
  ctVistaLiquidaciones(false);
}
function ctLiqCSV() {
  const d = al.liqDatos; if (!d) return;
  const filtro = al.liq.filtro || "";
  const liqs = d.liquidaciones.filter(l => !filtro || String(l.agencia_id) === filtro);
  const q = x => `"${String(x ?? "").replace(/"/g, '""')}"`;
  const filas = [["Nro", "Agencia", "Desde", "Corte", ...CT_LIQ_COLS.map(c => c[1]), "Boletos", "Estado", "Depositada", "Referencia"]]
    .concat(liqs.map(l => [l.id, l.agencia, l.desde, l.hasta, ...CT_LIQ_COLS.map(([k]) => Math.round(l[k])), l.boletos, l.estado, l.depositada_el, l.referencia]));
  const blob = new Blob(["﻿" + filas.map(f => f.map(q).join(";")).join("\r\n")], { type: "text/csv;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = `liquidaciones-${alISO(new Date())}.csv`;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
}

// ════════════════════════════════════════════════════════════════════════════
// RECAUDACIÓN (solo administración): por servicio (fecha del viaje, con lo que
// vendió cada agencia), por agencia y vendedor, o por día (fecha del cobro)
// ════════════════════════════════════════════════════════════════════════════
const CT_REC_POR = [["servicio", "Por servicio"], ["agencia", "Por agencia y vendedor"], ["dia", "Por día"]];
const CT_REC_PLATA = [["boletos", "Boletos", "n"], ["efectivo", "Efectivo", "g"], ["tarjeta", "Tarjeta", "g"], ["transferencia", "Transf.", "g"], ["salidas", "Devol. y anul.", "-"], ["ie", "I/E", "g"], ["neto", "Neto", "g"]];
const CT_REC_COLS = {
  servicio: [["pasajeros", "Pasajeros", "n"], ["parados", "Parados", "n"], ["menores", "Menores", "n"], ["devueltos", "Devueltos", "n"], ["boletos", "Boletos", "g"], ["equipaje", "Equipaje", "g"], ["retenido", "Retenido", "g"], ["total", "Total", "g"]],
  agencia: CT_REC_PLATA, dia: CT_REC_PLATA,
};
function ctRecRango(k) {
  const h = new Date(), d = x => { const y = new Date(h); y.setDate(y.getDate() + x); return alISO(y); };
  if (k === "hoy") return [d(0), d(0)];
  if (k === "ayer") return [d(-1), d(-1)];
  if (k === "7") return [d(-6), d(0)];
  if (k === "mes") return [alISO(new Date(h.getFullYear(), h.getMonth(), 1)), d(0)];
  if (k === "prox") return [d(0), d(7)];
  return [al.rec.desde, al.rec.hasta];
}
function ctRecPoner(k) { [al.rec.desde, al.rec.hasta] = ctRecRango(k); ctVistaRecaudacion(false); }
async function ctVistaRecaudacion(animar) {
  if (!al.rec.desde) [al.rec.desde, al.rec.hasta] = ctRecRango("hoy");
  if (!document.querySelector(".al-recv")) ctCargando(animar);
  if (!al.cfg) await alCfgTraer();
  const d = await api(`/api/alpha/recaudacion?desde=${al.rec.desde}&hasta=${al.rec.hasta}&por=${al.rec.por}`);
  if (ct.vista !== "recaudacion" || !d || !d.filas) return;
  al.recDatos = d;
  const por = d.por, cols = CT_REC_COLS[por], filas = d.filas;
  const cor = k => ((al.cfg.corredores || []).find(c => c.clave === k) || {}).titulo || String(k || "").split("|").pop();
  const val = (f, [k, , t]) => t === "n" ? (f[k] || "") : t === "-" ? (f[k] ? "− " + fmtNum(f[k]) : "") : fmtNum(f[k] || 0);
  const tot = Object.fromEntries(cols.map(([k]) => [k, filas.reduce((a, f) => a + (f[k] || 0), 0)]));
  const lead = f => por === "servicio"
    ? `<td><b>${alDM(f.fecha)}</b> ${f.hora}</td><td><b>${trEsc(f.tramo)}</b><small>${trEsc(cor(f.cor))} · ${f.lado === "regreso" ? "regreso" : "ida"}${f.coche ? " · coche " + trEsc(f.coche) : ""}</small>${f.agencias.length > 1 || (f.agencias[0] && f.agencias[0].agencia !== "Administración") ? `<small>${f.agencias.map(a => `${trEsc(a.agencia)} ${a.pasajeros}`).join(" · ")}</small>` : ""}</td>`
    : por === "dia" ? `<td><b>${alDiaTxt(alDeISO(f.fecha))}</b></td>` : `<td><b>${trEsc(f.agencia)}</b></td><td>${trEsc(f.vendedor)}</td>`;
  const leadTh = por === "servicio" ? "<th>Salida</th><th>Servicio</th>" : por === "dia" ? "<th>Día</th>" : "<th>Agencia</th><th>Vendedor</th>";
  const pctTxt = f => { const sent = f.pasajeros - f.parados; return f.asientos ? `<small>${Math.round(sent * 100 / f.asientos)} % de ${f.asientos}</small>` : ""; };
  const resumen = por === "servicio"
    ? [["Servicios con ventas", filas.length], ["Pasajeros", tot.pasajeros], ["Boletos", alGs(tot.boletos)], ["Equipaje y retenido", alGs(tot.equipaje + tot.retenido)], ["Total", alGs(tot.total), 1]]
    : [["Boletos vendidos", tot.boletos], ["Efectivo", alGs(tot.efectivo)], ["Tarjeta y transf.", alGs(tot.tarjeta + tot.transferencia)], ["Devol. y anul.", "− " + alGs(tot.salidas)], ["Neto", alGs(tot.neto), 1]];
  content.innerHTML = ctShell(`
    <div class="al-vista al-recv">
      <div class="al-v-cab"><h1 class="al-d">Recaudación</h1><span>${por === "servicio" ? "Lo que dejó cada salida, por la fecha del viaje, y qué agencia vendió." : "La plata que entró y salió, por la fecha en que se cobró."}</span></div>
      <div class="al-chips">${CT_REC_POR.map(([k, t]) => `<button type="button" class="al-chip ${k === por ? "on" : ""}" aria-pressed="${k === por}" onclick="al.rec.por='${k}';ctVistaRecaudacion(false)">${t}</button>`).join("")}</div>
      <div class="al-man-sel">
        <label class="al-campo"><span>Desde</span><input type="date" value="${al.rec.desde}" onchange="al.rec.desde=this.value;ctVistaRecaudacion(false)"></label>
        <label class="al-campo"><span>Hasta</span><input type="date" value="${al.rec.hasta}" onchange="al.rec.hasta=this.value;ctVistaRecaudacion(false)"></label>
        <div class="al-chips al-rec-r">${[["hoy", "Hoy"], ["ayer", "Ayer"], ["7", "Últimos 7 días"], ["mes", "Este mes"], ...(por === "servicio" ? [["prox", "Próximos 7 días"]] : [])].map(([k, t]) => { const [a, b] = ctRecRango(k); return `<button type="button" class="al-chip ${a === al.rec.desde && b === al.rec.hasta ? "on" : ""}" onclick="ctRecPoner('${k}')">${t}</button>`; }).join("")}</div>
        ${filas.length ? `<button type="button" class="al-btn-r" onclick="ctRecImprimir()"><i class="ti ti-printer"></i> Imprimir</button><button type="button" class="al-sec" onclick="ctRecCSV()"><i class="ti ti-file-spreadsheet"></i> CSV</button>` : ""}
      </div>
      <div class="al-man-res">${resumen.map(([t, v, f]) => `<div class="${f ? "fuerte" : ""}"><span>${t}</span><b class="al-d">${v}</b></div>`).join("")}</div>
      ${filas.length ? `<div class="al-tabla-w"><table class="al-tabla">
        <thead><tr>${leadTh}${cols.map(([, t]) => `<th class="al-t-m">${t}</th>`).join("")}</tr></thead>
        <tbody>${filas.map(f => `<tr>${lead(f)}${cols.map(c => `<td class="al-t-m ${c[0] === "total" || c[0] === "neto" ? "fuerte" : ""} ${c[2] === "-" && f[c[0]] ? "neg" : ""}">${val(f, c)}${por === "servicio" && c[0] === "pasajeros" ? pctTxt(f) : ""}</td>`).join("")}</tr>`).join("")}</tbody>
        <tfoot><tr><th${por === "dia" ? "" : ' colspan="2"'}>Total</th>${cols.map(c => `<th class="al-t-m">${val(tot, c)}</th>`).join("")}</tr></tfoot></table></div>`
        : `<div class="al-vacio"><i class="ti ti-chart-bar-off"></i><b>No hay ${por === "servicio" ? "ventas para viajes" : "movimientos"} en esas fechas</b></div>`}
    </div>`, animar);
}
function ctRecFilasPlanas() {
  const d = al.recDatos; if (!d) return [];
  const cols = CT_REC_COLS[d.por];
  const cab = d.por === "servicio" ? ["Fecha", "Hora", "Servicio", "Corredor", "Sentido", "Coche", "Asientos", "Agencias"] : d.por === "dia" ? ["Día"] : ["Agencia", "Vendedor"];
  const cor = k => (((al.cfg || {}).corredores || []).find(c => c.clave === k) || {}).titulo || String(k || "").split("|").pop();
  return [cab.concat(cols.map(c => c[1]))].concat(d.filas.map(f => (d.por === "servicio"
    ? [f.fecha, f.hora, f.tramo, cor(f.cor), f.lado, f.coche, f.asientos, f.agencias.map(a => `${a.agencia} ${a.pasajeros}`).join(" / ")]
    : d.por === "dia" ? [f.fecha] : [f.agencia, f.vendedor]).concat(cols.map(([k, , t]) => t === "-" ? -Math.round(f[k] || 0) : Math.round(f[k] || 0)))));
}
function ctRecCSV() { const d = al.recDatos; if (d) alCSV(`recaudacion-${d.por}-${d.desde}-a-${d.hasta}.csv`, ctRecFilasPlanas()); }
function ctRecImprimir() {
  const d = al.recDatos; if (!d) return;
  const filas = ctRecFilasPlanas(), cab = filas.shift(), e = trEsc, nCols = CT_REC_COLS[d.por].length;
  const tot = cab.map((_, i) => i < cab.length - nCols ? "" : fmtNum(filas.reduce((a, f) => a + (+f[i] || 0), 0)));
  tot[0] = "Total";
  const html = `<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Recaudación ${d.desde} a ${d.hasta}</title>
<style>@page{size:A4 landscape;margin:10mm}*{box-sizing:border-box}body{margin:0;font-family:Arial,sans-serif;color:#000;font-size:10.5px}
.cab{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:2px solid #000;padding-bottom:6px;margin-bottom:8px}h1{font-size:18px;margin:0}
table{width:100%;border-collapse:collapse}th,td{border:1px solid #bbb;padding:3px 5px;text-align:left}th{background:#eee;font-size:9.5px;text-transform:uppercase}.n{text-align:right;white-space:nowrap}
tfoot td{font-weight:800;background:#f3f3f3}.maq{margin-top:12px;font-size:9.5px;color:#555;text-align:center}</style></head><body>
<div class="cab"><div><b>LA SANTANIANA</b><h1>Recaudación ${(CT_REC_POR.find(x => x[0] === d.por) || [, ""])[1].toLowerCase()}</h1></div><span>Del ${alDM(d.desde)}/${d.desde.slice(0, 4)} al ${alDM(d.hasta)}/${d.hasta.slice(0, 4)} · impresa ${alAhoraISO().replace("T", " ")}</span></div>
<table><thead><tr>${cab.map((c, i) => `<th class="${i >= cab.length - nCols ? "n" : ""}">${e(c)}</th>`).join("")}</tr></thead>
<tbody>${filas.map(f => `<tr>${f.map((x, i) => `<td class="${i >= cab.length - nCols ? "n" : ""}">${i >= cab.length - nCols ? (x ? fmtNum(x) : "") : e(String(x ?? ""))}</td>`).join("")}</tr>`).join("")}</tbody>
<tfoot><tr>${tot.map((x, i) => `<td class="${i >= cab.length - nCols ? "n" : ""}">${x}</td>`).join("")}</tr></tfoot></table>
<div class="maq">Maqueta de Alpha: sin valor fiscal</div></body></html>`;
  alImprimir(html, "hoja");
}

// ════════════════════════════════════════════════════════════════════════════
// CONTROLES (solo administración)
//   Servicios: todas las salidas del día con su ocupación (resalta las que
//   pasan el % elegido), el recorrido con los que suben y bajan en cada parada,
//   y cerrar la venta, reabrirla o cancelar el servicio.
//   Agencias: lo que cada una tiene sin liquidar y sin depositar contra el tope
//   de su contrato, la última liquidación y el vencimiento del contrato.
// ════════════════════════════════════════════════════════════════════════════
const CT_EST_SERV = { abierto: ["Abierto", "vendido"], cerrado: ["Venta cerrada", "reserva"], cancelado: ["Cancelado", "anulado"], desactivado: ["Desactivado", "anulado"] };
async function ctVistaServicios(animar) {
  const fecha = alISO(alFechaDe(al.dia));
  if (!al.cfg || !al.datos[fecha] || !al.ocup[fecha] || Date.now() - ((al.ocupEl || {})[fecha] || 0) > AL_OCUP_FRESCO) {
    if (!document.querySelector(".ct-serv")) ctCargando(animar);
    await ctDatos(fecha);
    if (ct.vista !== "servicios") return;
  }
  const filas = ctServicios(fecha), um = +al.ctl.umbral || 0;
  const q = alNorm(al.ctl.q || "");
  const vis = filas.filter(f => !q || alNorm([f.sv.hora, f.sv.cod, f.sv.origen_nombre, f.sv.llega_nombre, f.sv.coche, f.titulo].join(" ")).includes(q));
  if (!filas.some(f => f.sv.clave === al.ctl.clave)) al.ctl.clave = (filas[0] || { sv: {} }).sv.clave || "";
  const sel = filas.find(f => f.sv.clave === al.ctl.clave);
  const tot = k => filas.reduce((a, f) => a + f[k], 0);
  const fila = f => `<tr class="${f.sv.clave === al.ctl.clave ? "on" : ""} ${f.est === "cancelado" ? "anulado" : ""}" onclick="ctElegir('${f.sv.clave.replace(/'/g, "\\'")}')" tabindex="0" onkeydown="if(event.key==='Enter')this.click()">
      <td><b>${f.sv.hora}</b></td><td><b>${trEsc(f.sv.origen_nombre)} → ${trEsc(f.sv.llega_nombre)}</b><small>${trEsc(f.sv.cod)} · ${f.sv.lado === "regreso" ? "regreso" : "ida"}${f.sv.adicional ? " · agregado" : ""}</small></td>
      <td>${f.sv.coche ? trEsc(f.sv.coche) : `<i class="al-conf">${f.sv.habitual ? "a conf. (" + trEsc(f.sv.habitual) + ")" : "a confirmar"}</i>`}${f.sv.reemplazo ? `<small>reemplaza al ${trEsc(f.sv.reemplazo.de)}</small>` : ""}</td>
      <td class="al-t-c">${f.libres}<small>de ${f.asientos}${f.bloqueados ? ` · ${f.bloqueados} bloq.` : ""}</small></td>
      <td class="al-t-c">${f.pax}${f.parados ? `<small>${f.parados} parados</small>` : ""}</td><td class="al-t-c">${f.reservas || ""}</td>
      <td class="al-t-c"><span class="al-pct ${f.pct >= um && um ? "alto" : ""}">${f.pct} %</span></td><td class="al-t-m">${fmtNum(f.recaudado)}</td>
      <td><span class="al-est ${CT_EST_SERV[f.est][1]}">${CT_EST_SERV[f.est][0]}</span></td></tr>`;
  content.innerHTML = ctShell(`
    <div class="al-vista al-ctl ct-serv">
      <div class="al-v-cab"><h1 class="al-d">Servicios</h1><span>Cómo vienen las salidas del día: ocupación, venta abierta o cerrada, y qué hacer si un coche falla.</span></div>
      <div class="al-filtros"><div class="al-dias" role="group" aria-label="Día del viaje">${ctChipsDias()}</div></div>
      <div class="al-man-sel">
        <label class="al-campo"><span>Buscar</span><input type="search" value="${trEsc(al.ctl.q)}" placeholder="Hora, destino, coche" oninput="al.ctl.q=this.value;clearTimeout(window._alCtlT);window._alCtlT=setTimeout(()=>{ctVistaServicios(false).then(()=>{const i=document.querySelector('.al-ctl input[type=search]');if(i){i.focus();i.setSelectionRange(i.value.length,i.value.length)}})},250)"></label>
        <label class="al-campo ci"><span>Resaltar si supera (%)</span><input type="number" min="0" max="100" step="5" value="${al.ctl.umbral}" onchange="al.ctl.umbral=+this.value;ctVistaServicios(false)"></label>
        <button type="button" class="al-sec" onclick="ctServiciosCSV()"><i class="ti ti-file-spreadsheet"></i> CSV</button>
        <button type="button" class="al-sec" onclick="alTraerOcup(null,true).then(()=>ctVistaServicios(false))"><i class="ti ti-refresh"></i> Actualizar</button>
      </div>
      <div class="al-man-res">
        <div><span>Salidas</span><b class="al-d">${filas.length}${filas.filter(f => f.est !== "abierto").length ? ` <small>· ${filas.filter(f => f.est === "cerrado").length} cerradas · ${filas.filter(f => f.est === "cancelado").length} canceladas</small>` : ""}</b></div>
        <div><span>Pasajeros</span><b class="al-d">${tot("pax")}</b></div>
        <div><span>Asientos libres</span><b class="al-d">${tot("libres")} <small>de ${tot("asientos")}</small></b></div>
        <div><span>Pasan el ${um} %</span><b class="al-d">${filas.filter(f => um && f.pct >= um).length}</b></div>
        <div class="fuerte"><span>Vendido para estas salidas</span><b class="al-d">${alGs(tot("recaudado"))}</b></div>
      </div>
      <div class="al-ctl-cuerpo">
        <div class="al-tabla-w"><table class="al-tabla al-ctl-t">
          <thead><tr><th>Sale</th><th>Servicio</th><th>Coche</th><th class="al-t-c">Libres</th><th class="al-t-c">Pasajeros</th><th class="al-t-c">Reservas</th><th class="al-t-c">Ocupado</th><th class="al-t-m">Vendido</th><th>Estado</th></tr></thead>
          <tbody>${vis.map(fila).join("") || `<tr><td colspan="9">No hay salidas${q ? " con esa búsqueda" : ""}.</td></tr>`}</tbody></table></div>
        ${sel ? ctDetalle(sel, fecha) : ""}
      </div>
    </div>`, animar);
}
function ctServicios(fecha) {
  const ventas = alOcupDe(fecha), out = [];
  alTodasSalidas().forEach(({ c, l, k }) => {
    const sv = alServiciosDe(c, l)[k], pl = alPlano(sv), asientos = alAsientos(pl).length;
    const vs = ventas.filter(v => v.servicio === sv.clave && alOcupa(v));
    const sentados = new Set(vs.filter(v => v.asiento !== "P").map(v => v.asiento));
    const vend = vs.filter(v => v.estado === "vendido");
    out.push({ sv, titulo: c.titulo, asientos, ocupados: sentados.size, libres: Math.max(0, asientos - sentados.size),
      pax: vend.length, parados: vend.filter(v => v.asiento === "P").length, reservas: vs.filter(v => v.estado === "reserva").length,
      bloqueados: vs.filter(v => v.estado === "bloqueado").length, menores: vend.filter(v => v.menor).length,
      pct: asientos ? Math.round(sentados.size * 100 / asientos) : 0, recaudado: vend.reduce((a, v) => a + (v.total || 0), 0),
      est: sv.desactivado ? "desactivado" : alEstadoServ(fecha, sv.clave), vend });
  });
  return out.sort((a, b) => a.sv.hora.localeCompare(b.sv.hora) || a.titulo.localeCompare(b.titulo));
}
// En pantallas angostas el detalle de la salida se abre en una ventanita
const CT_ANGOSTO = "(max-width: 1500px)";
function ctElegir(clave) {
  al.ctl.clave = clave;
  if (!window.matchMedia(CT_ANGOSTO).matches) return ctVistaServicios(false);
  document.querySelectorAll(".al-ctl-t tbody tr").forEach(tr => tr.classList.toggle("on", tr.getAttribute("onclick").includes(`'${clave.replace(/'/g, "\\'")}'`)));
  const fecha = alISO(alFechaDe(al.dia)), f = ctServicios(fecha).find(x => x.sv.clave === clave);
  if (f) alModal({ titulo: `${f.sv.hora} · ${f.sv.cod}`, ancho: 560, cuerpo: ctDetalle(f, fecha, true),
    pie: `<button type="button" class="al-sec" onclick="alModalCerrar()">Cerrar</button>` });
}
function ctDetalle(f, fecha, enModal) {
  const sv = f.sv, hr = alHojaRuta(sv, f.vend), info = (al.servEst[fecha] || {})[sv.clave] || {}, hist = info.historial || [];
  const cl = sv.clave.replace(/'/g, "\\'");
  return `<${enModal ? "div" : "aside"} class="${enModal ? "al-ctl-mod" : "al-card al-ctl-det"}" aria-label="Detalle de la salida">
    <div class="al-card-cab">${enModal ? "" : `<h2 class="al-d">${sv.hora} · ${trEsc(sv.cod)}</h2>`}<span>${trEsc(sv.origen_nombre)} → ${trEsc(sv.llega_nombre)} · ${sv.coche ? "coche " + trEsc(sv.coche) : "coche a confirmar"}${sv.reemplazo ? ` (reemplaza al ${trEsc(sv.reemplazo.de)})` : ""}${sv.tripulacion.length ? " · " + sv.tripulacion.map(trEsc).join(" y ") : ""}</span>
      ${f.est === "desactivado" ? `<span><span class="al-est anulado">Desactivado</span> ${trEsc(sv.desactivado.motivo || "")} · hasta el ${alDM(sv.desactivado.hasta)} (Programación)</span>`
        : f.est !== "abierto" ? `<span><span class="al-est ${CT_EST_SERV[f.est][1]}">${CT_EST_SERV[f.est][0]}</span>${info.motivo ? " " + trEsc(info.motivo) : ""} · ${trEsc(info.por || "")}, ${alDM((info.el || "").slice(0, 10))} ${(info.el || "").slice(11, 16)}</span>` : ""}
      ${sv.adicional ? `<span><span class="al-est vendido">Agregado</span> ${trEsc(sv.adicional.motivo || "")} · hasta el ${alDM(sv.adicional.hasta)} (Programación)</span>` : ""}</div>
    <ol class="al-ruta">${hr.map((p, i) => `<li><span class="al-ruta-h">${p.hora || "—"}</span><b>${trEsc(p.nombre)}</b><span class="al-ruta-n">${p.suben.length ? `<em class="s">+${p.suben.length}</em>` : ""}${p.bajan.length ? `<em class="b">−${p.bajan.length}</em>` : ""}${i < hr.length - 1 ? `<small>${p.abordo} a bordo</small>` : ""}</span></li>`).join("")}</ol>
    <div class="al-acc">
      ${f.est === "abierto" ? `<button type="button" class="al-sec" onclick="ctIrAlpha('vender','${cl}')"><i class="ti ti-ticket"></i> Vender</button>` : ""}
      <button type="button" class="al-sec" onclick="ctIrAlpha('manifiesto','${cl}')"><i class="ti ti-list-details"></i> Manifiesto</button>
      <button type="button" class="al-sec" onclick="alHojaRutaImprimir('${cl}')"><i class="ti ti-route"></i> Hoja de ruta</button>
      <button type="button" class="al-sec" onclick="ctTransbordoDesde('${cl}')"><i class="ti ti-arrows-shuffle"></i> Transbordo</button>
      ${f.est === "desactivado" || sv.adicional ? `<button type="button" class="al-sec" onclick="ctIr('programacion')"><i class="ti ti-calendar-event"></i> Programación</button>` : ""}
      ${f.est === "desactivado" ? "" : f.est === "abierto" ? `<button type="button" class="al-sec" onclick="ctServEstado('${cl}','cerrado')"><i class="ti ti-lock"></i> Cerrar la venta</button>` : `<button type="button" class="al-sec" onclick="ctServEstado('${cl}','abierto')"><i class="ti ti-lock-open"></i> Abrir la venta</button>`}
      ${f.est !== "cancelado" && f.est !== "desactivado" ? `<button type="button" class="al-sec rojo" onclick="ctServEstado('${cl}','cancelado')"><i class="ti ti-ban"></i> Cancelar el servicio</button>` : ""}
    </div>
    ${f.pax && (f.est === "cancelado" || f.est === "desactivado") ? `<p class="al-hint al-rojo-t">Este servicio tiene ${f.pax} pasajeros: pasalos a otra salida con el transbordo.</p>` : ""}
    ${hist.length ? `<details class="al-ayuda"><summary>Historial del servicio (${hist.length})</summary><ol class="al-hist">${hist.slice().reverse().map(ctHistItem).join("")}</ol></details>` : ""}
  </${enModal ? "div" : "aside"}>`;
}
async function ctIrAlpha(vista, clave) {
  alModalCerrar();
  let hit = null;
  alTodasSalidas().forEach(({ c, l, k }) => { if (!hit && alServiciosDe(c, l)[k].clave === clave) hit = { c, l, k }; });
  if (!hit) return;
  if (vista === "manifiesto") { al.man.clave = clave; al.manClave = ""; al.vista = "manifiesto"; }
  else { alLimpiarVenta(); al.cor = hit.c.clave; al.lado = hit.l; al.dep = hit.k; al.sube = 0; al.baja = -1; al.vista = "vender"; }
  ctAbrirAlpha();
}
async function ctServEstado(clave, estado) {
  const fecha = alISO(alFechaDe(al.dia)), f = ctServicios(fecha).find(x => x.sv.clave === clave);
  if (!f) return;
  let motivo = "";
  if (estado === "cancelado") {
    motivo = prompt(`¿Por qué se cancela la salida de las ${f.sv.hora} (${f.sv.cod})? Queda en el historial.${f.pax ? `\n\nTiene ${f.pax} pasajeros: después cambiales el boleto o devolvéselos.` : ""}`, "");
    if (motivo === null) return;
    if (!motivo.trim()) { toast("Contá por qué se cancela", "error"); return; }
  } else if (estado === "cerrado") {
    motivo = prompt(`Cerrar la venta de la salida de las ${f.sv.hora} (${f.sv.cod}): nadie más la puede vender, ni las agencias. Motivo (opcional):`, "");
    if (motivo === null) return;
  } else if (!confirm(`¿Abrir de nuevo la venta de la salida de las ${f.sv.hora}?`)) return;
  const r = await alPost("/api/alpha/servicios/estado", { fecha, servicio: clave, estado, motivo, hora: f.sv.hora, tramo: f.sv.cod });
  if (!r) return;
  al.servEst[fecha] = Object.assign({}, al.servEst[fecha], { [clave]: r.servicio });
  toast(estado === "abierto" ? "Venta abierta" : estado === "cerrado" ? "Venta cerrada" : "Servicio cancelado", "success");
  const enModal = !!document.getElementById("al-modal");
  alModalCerrar();
  await ctVistaServicios(false);
  if (enModal) ctElegir(clave);
}
function ctServiciosCSV() {
  const fecha = alISO(alFechaDe(al.dia));
  alCSV(`servicios-${fecha}.csv`, [["Sale", "Servicio", "Corredor", "Sentido", "Origen", "Destino", "Coche", "Asientos", "Libres", "Ocupados", "Pasajeros", "Parados", "Reservas", "Bloqueados", "Ocupación %", "Vendido Gs.", "Estado"]]
    .concat(ctServicios(fecha).map(f => [f.sv.hora, f.sv.cod, f.titulo, f.sv.lado, f.sv.origen_nombre, f.sv.llega_nombre, f.sv.coche || "", f.asientos, f.libres, f.ocupados, f.pax, f.parados, f.reservas, f.bloqueados, f.pct, f.recaudado, CT_EST_SERV[f.est][0]])));
}
async function ctVistaAgencias(animar) {
  if (!document.querySelector(".ct-ag")) ctCargando(animar);
  const d = await api("/api/alpha/control/agencias");
  if (ct.vista !== "agencias" || !d || !d.agencias) return;
  al.ctlAg = d;
  const hoy = d.hoy, t = d.totales;
  const fecha = x => x ? `${alDM(x.slice(0, 10))}/${x.slice(2, 4)}` : "—";
  const aviso = a => {
    const l = [];
    if (a.estado !== "activa") l.push(a.estado === "baja" ? "De baja" : "Suspendida");
    if (a.porc != null && a.porc >= 100) l.push("Pasó el tope");
    else if (a.porc != null && a.porc >= 85) l.push("Cerca del tope");
    if (!a.contrato) l.push("Sin contrato");
    else if (a.contrato_hasta && a.contrato_hasta < hoy) l.push("Contrato vencido");
    if (a.debe_desde && a.debe_desde.slice(0, 10) < alISO(new Date(Date.now() - 7 * 864e5))) l.push("Debe un depósito hace más de 7 días");
    return l;
  };
  const fila = a => {
    const av = aviso(a);
    return `<tr class="${a.estado !== "activa" ? "anulado" : ""}">
      <td><b>${trEsc(a.nombre)}</b><small>${trEsc(a.ciudad)}${a.comision ? " · " + trEsc(a.comision) : ""}</small></td>
      <td class="al-t-m">${a.tope ? fmtNum(a.tope) : "—"}</td>
      <td class="al-t-m">${fmtNum(a.sin_liquidar)}<small>${a.sin_liq_desde ? "desde " + fecha(a.sin_liq_desde) : ""}</small></td>
      <td class="al-t-m">${fmtNum(a.sin_depositar)}<small>${a.liq_pendientes ? `${a.liq_pendientes} liq. desde ${fecha(a.debe_desde)}` : ""}</small></td>
      <td class="al-t-m fuerte">${fmtNum(a.saldo)}</td>
      <td class="al-t-c">${a.porc != null ? `<span class="al-pct ${a.porc >= 100 ? "rojo" : a.porc >= 85 ? "alto" : ""}">${a.porc} %</span>` : "—"}</td>
      <td class="al-t-m">${a.hoy ? fmtNum(a.hoy) : ""}<small>${a.boletos_hoy ? a.boletos_hoy + " bol." : ""}</small></td>
      <td>${fecha(a.ultima_liq)}</td><td>${a.contrato_hasta ? fecha(a.contrato_hasta) : a.contrato ? "sin fin" : "—"}</td>
      <td>${av.length ? av.map(x => `<span class="al-est ${/tope|baja|Suspendida|vencido|Debe/.test(x) ? "anulado" : "reserva"}">${x}</span>`).join(" ") : `<span class="al-est vendido">Al día</span>`}</td>
      <td class="al-t-a">${a.estado === "activa" ? `<button type="button" class="al-ic rojo" title="Suspender: no puede vender" aria-label="Suspender" onclick="ctAgEstado(${a.id}, 'suspendida')"><i class="ti ti-player-pause"></i></button>` : a.estado === "suspendida" ? `<button type="button" class="al-ic" title="Habilitar de nuevo" aria-label="Habilitar" onclick="ctAgEstado(${a.id}, 'activa')"><i class="ti ti-player-play"></i></button>` : ""}
        <button type="button" class="al-ic" title="Liquidar" aria-label="Liquidar" onclick="al.liq.agencia='${a.id}';ctIr('liquidaciones')"><i class="ti ti-report-money"></i></button></td></tr>`;
  };
  content.innerHTML = ctShell(`
    <div class="al-vista al-ctl ct-ag">
      <div class="al-v-cab"><h1 class="al-d">Agencias</h1><span>Lo que cada agencia tiene sin liquidar y sin depositar contra el tope de su contrato.</span></div>
      <div class="al-man-res">
        <div><span>Sin liquidar</span><b class="al-d">${alGs(t.sin_liquidar)}</b></div>
        <div><span>Liquidado sin depositar</span><b class="al-d">${alGs(t.sin_depositar)}</b></div>
        <div class="fuerte"><span>En manos de las agencias</span><b class="al-d">${alGs(t.saldo)}</b></div>
        <div><span>Vendieron hoy</span><b class="al-d">${alGs(t.hoy)}</b></div>
        <div><span>Ya depositado</span><b class="al-d">${alGs(t.depositado)}</b></div>
      </div>
      <p class="al-nota">El tope es el «Tope de venta sin depositar» del contrato (Comercial → Agencias). Una agencia que lo pasa, o que está suspendida, no puede vender en Alpha hasta que deposite o la habiliten.</p>
      <div class="al-man-sel"><button type="button" class="al-sec" onclick="ctAgenciasCSV()"><i class="ti ti-file-spreadsheet"></i> CSV</button><button type="button" class="al-sec" onclick="ctVistaAgencias(false)"><i class="ti ti-refresh"></i> Actualizar</button></div>
      ${d.agencias.length ? `<div class="al-tabla-w"><table class="al-tabla al-ctl-ag">
        <thead><tr><th>Agencia</th><th class="al-t-m">Tope</th><th class="al-t-m">Sin liquidar</th><th class="al-t-m">Sin depositar</th><th class="al-t-m">Saldo</th><th class="al-t-c">% del tope</th><th class="al-t-m">Hoy</th><th>Últ. liquid.</th><th>Contrato hasta</th><th>Situación</th><th></th></tr></thead>
        <tbody>${d.agencias.map(fila).join("")}</tbody>
        <tfoot><tr><th>Total</th><th></th><th class="al-t-m">${fmtNum(t.sin_liquidar)}</th><th class="al-t-m">${fmtNum(t.sin_depositar)}</th><th class="al-t-m">${fmtNum(t.saldo)}</th><th></th><th class="al-t-m">${fmtNum(t.hoy)}</th><th></th><th></th><th></th><th></th></tr></tfoot></table></div>`
        : `<div class="al-vacio"><i class="ti ti-building-store"></i><b>No hay agencias cargadas</b><span>Se cargan en Comercial → Agencias.</span></div>`}
    </div>`, animar);
}
async function ctAgEstado(id, estado) {
  const a = ((al.ctlAg || {}).agencias || []).find(x => x.id === id);
  if (!a) return;
  let motivo = "";
  if (estado !== "activa") {
    motivo = prompt(`¿Por qué se suspende a ${a.nombre}? No va a poder vender en Alpha hasta que la habiliten.`, a.porc >= 100 ? "Pasó el tope de venta sin depositar" : "");
    if (motivo === null) return;
    if (!motivo.trim()) { toast("Contá el motivo (queda en la ficha de la agencia)", "error"); return; }
  } else if (!confirm(`¿Habilitar de nuevo a ${a.nombre}?`)) return;
  const r = await api(`/api/agencias/${id}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ estado, motivo }) });
  if (!r || r.ok === false || r.error) { toast((r && (r.msg || r.error)) || "No se pudo", "error"); return; }
  toast(estado === "activa" ? `${a.nombre} habilitada` : `${a.nombre} suspendida`, "success");
  ctVistaAgencias(false);
}
function ctAgenciasCSV() {
  const d = al.ctlAg; if (!d) return;
  alCSV(`agencias-control-${d.hoy}.csv`, [["Agencia", "Ciudad", "Estado", "Comisión", "Tope", "Sin liquidar", "Sin liquidar desde", "Sin depositar", "Liquidaciones pendientes", "Saldo", "% del tope", "Vendido hoy", "Última liquidación", "Contrato hasta"]]
    .concat(d.agencias.map(a => [a.nombre, a.ciudad, a.estado, a.comision, Math.round(a.tope), Math.round(a.sin_liquidar), a.sin_liq_desde.slice(0, 10), Math.round(a.sin_depositar), a.liq_pendientes, Math.round(a.saldo), a.porc ?? "", Math.round(a.hoy), a.ultima_liq.slice(0, 10), a.contrato_hasta])));
}


// ════════════════════════════════════════════════════════════════════════════
// TRANSBORDOS: se rompe un coche (o pasa algo) y los pasajeros siguen en otro
// coche en la misma salida, o pasan a otra salida. Acá se arma el plan (qué
// asiento le toca a cada uno) y se ve antes de confirmar; el servidor revisa
// que no choque con nada y lo aplica todo junto. No se mueve plata.
// ════════════════════════════════════════════════════════════════════════════
const CT_MOTIVOS = ["Se rompió el coche", "Accidente", "Coche más chico", "Otro"];
function ctSalidasDe(fecha) {
  const out = [];
  ((al.datos[fecha] || {}).corredores || []).forEach(c => ["ida", "regreso"].forEach(l =>
    alServiciosDe(c, l).forEach(sv => out.push(Object.assign(sv, { _titulo: c.titulo })))));
  return out.sort((a, b) => a.hora.localeCompare(b.hora) || a._titulo.localeCompare(b._titulo));
}
function ctPasajeros(fecha, sv) {
  const cam = alCamino(sv), n = cam.length;
  return alOcupDe(fecha).filter(v => v.servicio === sv.clave && v.nro != null && (v.estado === "vendido" || alReservaViva(v)))
    .map(v => ({ v, s: Math.min(v.subeIdx ?? alIdxDe(cam, v.sube, 0), n - 2), b: Math.min(v.bajaIdx ?? alIdxDe(cam, v.baja, n - 1), n - 1) }))
    .sort((a, b) => (a.v.asiento === "P") - (b.v.asiento === "P") || (+a.v.asiento || 0) - (+b.v.asiento || 0));
}
function ctLibres(fecha, sv) {
  const sent = new Set(alOcupDe(fecha).filter(v => v.servicio === sv.clave && alOcupa(v) && v.asiento !== "P").map(v => String(v.asiento)));
  return Math.max(0, alAsientos(alPlano(sv)).length - sent.size);
}
function ctModeloDe(coche) {
  const c = ((al.cfg && al.cfg.coches) || []).find(x => x.coche === coche);
  return c ? [c.marca, c.modelo].filter(Boolean).join(" ") : "";
}
// El plan: a quién se mueve, a dónde y a qué asiento
function ctPlan(fecha, sv, pas) {
  const tb = ct.tb, cam = alCamino(sv), P = Math.max(0, Math.min(tb.parada || 0, cam.length - 2));
  let destSv, destCam, destFecha, destPl, existentes;
  const movers = [], fuera = [];
  if (tb.tipo === "coche") {
    if (!tb.coche) return null;
    const modelo = ctModeloDe(tb.coche), plano = alPlanoDe(tb.coche, modelo);
    destSv = Object.assign({}, sv, { coche: tb.coche, modelo, habitual: "", plano });
    destCam = cam; destFecha = fecha; destPl = alPlanos()[plano] || alPlano(sv);
    // Los bloqueados (tripulación…) siguen como están
    existentes = alOcupDe(fecha).filter(v => v.servicio === sv.clave && v.estado === "bloqueado").map(v => ({ a: String(v.asiento), s: 0, b: 99, nombre: "Bloqueado: " + (v.motivo || v.nombre || "") }));
    pas.forEach(p => movers.push(Object.assign({}, p, { s2: p.s, b2: p.b })));
  } else {
    destFecha = ctFechaMas(fecha, tb.destDia || 0);
    destSv = ctSalidasDe(destFecha).find(x => x.clave === tb.destino);
    if (!destSv) return null;
    destCam = alCamino(destSv); destPl = alPlano(destSv);
    const n2 = destCam.length;
    existentes = alOcupDe(destFecha).filter(v => v.servicio === destSv.clave && alOcupa(v))
      .map(v => ({ a: String(v.asiento), s: v.subeIdx ?? alIdxDe(destCam, v.sube, 0), b: Math.min(v.bajaIdx ?? alIdxDe(destCam, v.baja, n2 - 1), n2 - 1),
                   nombre: v.estado === "bloqueado" ? "Bloqueado: " + (v.motivo || v.nombre || "") : (v.nombre || "") + (v.estado === "reserva" ? " (reserva)" : "") }));
    pas.forEach(p => {
      if (P > 0 && p.b <= P) { fuera.push(Object.assign({}, p, { problema: `Ya bajó en ${cam[p.b].nombre}`, fijo: true })); return; }
      if ((tb.fuera || []).includes(p.v.nro)) { fuera.push(Object.assign({}, p, { problema: "Queda en esta salida" })); return; }
      // Los que ya iban a bordo suben donde quedó el coche
      const subeN = P > 0 && p.s <= P ? cam[P].nombre : cam[p.s].nombre, bajaN = cam[p.b].nombre;
      const s2 = alIdxDe(destCam, subeN, -1), b2 = alIdxDe(destCam, bajaN, -1);
      if (s2 < 0 || b2 < 0 || b2 <= s2) { fuera.push(Object.assign({}, p, { problema: `La otra salida no pasa por ${s2 < 0 ? subeN : bajaN}`, fijo: true })); return; }
      movers.push(Object.assign({}, p, { s2, b2 }));
    });
  }
  const asi = alAsientos(destPl), ocup = existentes.slice(), topeP = destPl.parados || 0;
  let parados = ocup.filter(o => o.a === "P").length;
  const libre = (a, s, b) => !ocup.some(o => o.a === String(a) && o.s < b && s < o.b);
  const poner = (m, a) => { m.nuevo = a; ocup.push({ a: String(a), s: m.s2, b: m.b2 }); if (a === "P") parados++; };
  // 0) los que se acomodaron a mano (si el lugar sigue libre)
  const man = tb.manual || {};
  movers.forEach(m => {
    const a = man[m.v.nro];
    if (a == null) return;
    if (a === "P") { if (m.v.estado === "vendido" && parados < topeP) { poner(m, "P"); m.aMano = true; } return; }
    if (asi.some(x => x.n === +a) && libre(+a, m.s2, m.b2)) { poner(m, +a); m.aMano = true; }
  });
  // 1) el mismo número si está libre (y los parados siguen parados si hay lugar)
  movers.forEach(m => {
    if (m.nuevo != null) return;
    if (m.v.asiento === "P") { if (parados < topeP) poner(m, "P"); return; }
    const x = asi.find(a => a.n === +m.v.asiento);
    if (x && libre(x.n, m.s2, m.b2)) poner(m, x.n);
  });
  // 2) los demás: el primero libre de la misma clase, si no cualquiera, si no parado
  movers.forEach(m => {
    if (m.nuevo != null) return;
    const clase = (m.v.asDesc && m.v.asDesc.clase) || "CO";
    const x = asi.find(a => a.clase === clase && libre(a.n, m.s2, m.b2)) || asi.find(a => libre(a.n, m.s2, m.b2));
    if (x) poner(m, x.n);
    else if (m.v.estado === "vendido" && parados < topeP) poner(m, "P");
    else m.problema = "No hay lugar";
  });
  return { destSv, destCam, destFecha, destPl, movers, fuera, ext: existentes, topeP, sinLugar: movers.filter(m => m.nuevo == null).length,
    cambian: movers.filter(m => m.nuevo != null && String(m.nuevo) !== String(m.v.asiento)).length };
}
// Lo que se le manda al servidor por cada pasajero
function ctMovs(plan) {
  const sv = plan.destSv, cam = plan.destCam, fD = alDeISO(plan.destFecha);
  return plan.movers.filter(m => m.nuevo != null).map(m => {
    const s = m.s2, b = m.b2, hor = alHorasTramo(sv, cam, s, b), d = alDescAsiento(m.nuevo, plan.destPl);
    let llegaDia = "";
    if (hor.llega != null && hor.llega >= 1440) { const x = new Date(fD); x.setDate(x.getDate() + Math.floor(hor.llega / 1440)); llegaDia = AL_DIAS[x.getDay()] + " " + x.getDate(); }
    return { nro: m.v.nro, sube_idx: s, baja_idx: b, viaje: {
      fecha: plan.destFecha, servicio: sv.clave, cor: sv.cor, lado: sv.lado, hora: sv.hora, sale: alHH(hor.sale),
      llega: hor.llega != null ? alHH(hor.llega) : "", llegaDia, tramo: sv.cod, coche: sv.coche || "", plano: sv.plano,
      sube: cam[s].nombre, baja: cam[b].nombre, origen: cam[s].nombre, destino: cam[b].nombre, intl: !!sv.intl,
      asiento: m.nuevo, asDesc: d ? { piso: d.piso, pos: d.pos, tipo: d.tipo, clase: d.clase, pisoIdx: d.pisoIdx } : null } };
  });
}
async function ctVistaTransbordos(animar) {
  const tb = ct.tb, fecha = alISO(alFechaDe(al.dia));
  if (!document.querySelector(".ct-tb")) ctCargando(animar);
  await ctDatos(fecha);
  if (tb.tipo === "salida" && tb.destDia) await ctDatos(ctFechaMas(fecha, tb.destDia));
  if (tb.histF !== fecha) { const r = await api(`/api/alpha/transbordos?fecha=${fecha}`); tb.hist = (r && r.transbordos) || []; tb.histF = fecha; }
  if (ct.vista !== "transbordos") return;
  const e = trEsc, salidas = ctSalidasDe(fecha), sv = salidas.find(x => x.clave === tb.origen);
  const cuenta = {};
  alOcupDe(fecha).forEach(v => { if (v.nro != null && (v.estado === "vendido" || alReservaViva(v))) cuenta[v.servicio] = (cuenta[v.servicio] || 0) + 1; });
  const elegir = `<section class="al-card">
      <div class="al-card-cab"><h2 class="al-d">1. La salida con problemas</h2><span>Elegí el día y la salida. ${salidas.length} salidas este día.</span></div>
      <div class="al-dias" role="group" aria-label="Día">${ctChipsDias()}</div>
      <label class="al-campo"><span>Salida</span><select onchange="ctTbOrigen(this.value)"><option value="">Elegí la salida</option>${salidas.map(x => `<option value="${e(x.clave)}" ${x.clave === tb.origen ? "selected" : ""}>${x.hora} · ${e(x.origen_nombre)} → ${e(x.llega_nombre)} · ${e(x.cod)} · ${x.coche ? "coche " + e(x.coche) : "coche a conf."} · ${cuenta[x.clave] || 0} pasajeros</option>`).join("")}</select></label>
      ${sv ? `<p class="al-nota">${alDiaTxt(alFechaDe(al.dia))} · ${sv.coche ? "Coche " + e(sv.coche) + (sv.modelo ? ", " + e(sv.modelo) : "") : "Coche a confirmar"}${sv.reemplazo ? ` (ya reemplaza al ${e(sv.reemplazo.de)})` : ""}${sv.tripulacion.length ? " · " + sv.tripulacion.map(e).join(" y ") : ""} · ${cuenta[sv.clave] || 0} pasajeros</p>` : ""}
    </section>`;
  let cuerpo = "";
  if (tb.hecho) cuerpo = ctTbHechoHTML();
  else if (sv) cuerpo = ctTbForm(fecha, sv);
  const hist = tb.hist.length ? `<h2 class="al-d al-h2">Transbordos del día</h2><div class="al-cierres">${tb.hist.map(t => `<div class="al-cierre"><b>${t.el.slice(11, 16)}</b><span>${e(t.hora)} ${e(t.tramo)} → ${t.tipo === "coche" ? `coche ${e(t.coche_nuevo)} (era el ${e(t.coche_antes)})` : e(t.destino)} · ${t.pasajeros} ${t.pasajeros === 1 ? "pasajero" : "pasajeros"} · ${e(t.motivo)} · ${e(t.por)}${t.taller ? " · " + e(t.taller) + " al taller" : ""}</span><button type="button" class="al-link" onclick="ctPlanilla(${t.id})">Imprimir planilla</button></div>`).join("")}</div>` : "";
  content.innerHTML = ctShell(`
    <div class="al-vista ct-tb">
      <div class="al-v-cab"><h1 class="al-d">Transbordos</h1><span>Se rompió un coche o pasó algo: otro coche sigue la salida, o los pasajeros pasan a otra.</span></div>
      ${elegir}
      ${cuerpo}
      ${hist}
    </div>`, animar);
  if (sv && tb.tipo === "coche" && !tb.hecho) ctTbSugerencias(sv);
}
function ctTbForm(fecha, sv) {
  const tb = ct.tb, e = trEsc, cam = alCamino(sv), P = Math.max(0, Math.min(tb.parada || 0, cam.length - 2));
  const pas = ctPasajeros(fecha, sv), plan = ctPlan(fecha, sv, pas), cocheAntes = sv.coche || sv.habitual || "";
  // 2. Qué pasó
  const paso = `<section class="al-card">
      <div class="al-card-cab"><h2 class="al-d">2. Qué pasó</h2></div>
      <div class="al-chips">${CT_MOTIVOS.map(m => `<button type="button" class="al-chip ${tb.motivoChip === m ? "on" : ""}" aria-pressed="${tb.motivoChip === m}" onclick="ctTbMotivo('${m}')">${m}</button>`).join("")}</div>
      <div class="al-fila">
        <label class="al-campo"><span>Detalle</span><input id="ct-tb-mot" maxlength="140" value="${e(tb.motivo)}" oninput="ct.tb.motivo=this.value" placeholder="Ej.: se rompió la caja a la altura de Yby Yaú"></label>
        <label class="al-campo"><span>Dónde</span><select onchange="ct.tb.parada=+this.value;ctVistaTransbordos(false)">${cam.slice(0, -1).map((p, i) => `<option value="${i}" ${i === P ? "selected" : ""}>${i === 0 ? `Antes de salir de ${e(p.nombre)}` : `Pasando ${e(p.nombre)}`}</option>`).join("")}</select></label>
      </div>
    </section>`;
  // 3. Qué se hace
  const coches = (al.cfg && al.cfg.coches) || [];
  const plNuevo = tb.tipo === "coche" && tb.coche ? alPlanoDe(tb.coche, ctModeloDe(tb.coche)) : "";
  const destF = ctFechaMas(fecha, tb.destDia || 0);
  const cands = tb.tipo === "salida" ? ctSalidasDe(destF).filter(x => x.clave !== sv.clave) : [];
  const mismo = cands.filter(x => x.cor === sv.cor && x.lado === sv.lado), otras = cands.filter(x => !(x.cor === sv.cor && x.lado === sv.lado));
  const opt = x => `<option value="${e(x.clave)}" ${x.clave === tb.destino ? "selected" : ""}>${x.hora} · ${e(x.origen_nombre)} → ${e(x.llega_nombre)} · ${e(x.cod)} · ${ctLibres(destF, x)} libres${x.desactivado ? " · DESACTIVADA" : alEstadoServ(destF, x.clave) === "cancelado" ? " · CANCELADA" : ""}</option>`;
  const hace = `<section class="al-card">
      <div class="al-card-cab"><h2 class="al-d">3. Qué se hace</h2></div>
      <div class="ct-opc" role="radiogroup" aria-label="Qué se hace">
        <button type="button" class="ct-op ${tb.tipo === "coche" ? "on" : ""}" role="radio" aria-checked="${tb.tipo === "coche"}" onclick="ctTbTipo('coche')"><i class="ti ti-bus"></i><b>Otro coche sigue esta salida</b><span>Los pasajeros siguen en la misma salida. Si el coche tiene otro plano, los asientos se reacomodan.</span></button>
        <button type="button" class="ct-op ${tb.tipo === "salida" ? "on" : ""}" role="radio" aria-checked="${tb.tipo === "salida"}" onclick="ctTbTipo('salida')"><i class="ti ti-arrows-shuffle"></i><b>Pasan a otra salida</b><span>Todos o algunos, a otra salida del mismo día o del siguiente.</span></button>
      </div>
      ${tb.tipo === "coche" ? `
        <div class="al-fila">
          <label class="al-campo ct-coche"><span>Coche que sigue la salida</span><input list="ct-coches" value="${e(tb.coche)}" placeholder="Número interno" onchange="ctTbCoche(this.value)" onkeydown="if(event.key==='Enter')this.blur()"></label>
          <datalist id="ct-coches">${coches.filter(c => c.coche !== cocheAntes).map(c => `<option value="${e(c.coche)}">${e([c.marca, c.modelo].filter(Boolean).join(" "))}</option>`).join("")}</datalist>
          ${plNuevo ? `<p class="al-nota ct-plano">Plano: <b>${e((alPlanos()[plNuevo] || {}).nombre || plNuevo)}</b>${plNuevo !== sv.plano ? ` (el ${e(cocheAntes || "anterior")} tenía ${e((alPlanos()[sv.plano] || {}).nombre || sv.plano)})` : " (el mismo)"}</p>` : ""}
        </div>
        ${tb.sug && tb.sug.length ? `<div class="ct-sug"><span>Según el tráfico, disponibles en ${e(sv.origen_nombre)}:</span><div class="al-chips">${tb.sug.slice(0, 8).map(c => `<button type="button" class="al-chip ${c.coche === tb.coche ? "on" : ""}" onclick="ctTbCoche('${e(c.coche)}')">${e(c.coche)} <small>${e([c.lugar, c.desde_hora ? "desde " + c.desde_hora : ""].filter(Boolean).join(" "))}</small></button>`).join("")}</div></div>` : ""}
        <p class="al-hint">${sv.id ? "El cambio de coche queda también en el Tráfico del día (como cambio sin publicar)." : "Este día todavía no tiene el tráfico armado: el coche queda anotado en Controles y Alpha."}</p>` : `
        <div class="al-fila ct-dest">
          <div class="al-chips" role="group" aria-label="Día de la otra salida">${[[0, "Mismo día"], [1, "Día siguiente"]].map(([d, t]) => `<button type="button" class="al-chip ${(tb.destDia || 0) === d ? "on" : ""}" onclick="ctTbDestDia(${d})">${t}</button>`).join("")}</div>
          <label class="al-campo"><span>Salida de destino</span><select onchange="ctTbDestino(this.value)"><option value="">Elegí la salida</option>
            ${mismo.length ? `<optgroup label="Mismo recorrido">${mismo.map(opt).join("")}</optgroup>` : ""}${otras.length ? `<optgroup label="Otras">${otras.map(opt).join("")}</optgroup>` : ""}</select></label>
        </div>`}
    </section>`;
  // 4. Cómo queda
  let queda = "";
  if (plan) {
    const filas = plan.movers.concat(plan.fuera).sort((a, b) => (+a.v.asiento || 999) - (+b.v.asiento || 999));
    const fila = m => {
      const mueve = plan.movers.includes(m), ok = mueve && m.nuevo != null;
      const ahora = !mueve ? `<span class="ct-q">${e(m.problema || "")}</span>` : !ok ? `<span class="ct-mal">${e(m.problema || "No hay lugar")}</span>`
        : String(m.nuevo) === String(m.v.asiento) ? `<span class="ct-ok">${m.nuevo === "P" ? "Sigue parado" : "Sigue en el " + m.nuevo}</span>` : `<b class="ct-cambia">${m.nuevo === "P" ? "Parado" : "Asiento " + m.nuevo}</b>${m.aMano ? " <small>a mano</small>" : ""}`;
      const check = tb.tipo === "salida" ? `<td class="al-t-c"><input type="checkbox" aria-label="Pasa ${e(m.v.nombre)}" ${m.fijo ? "disabled" : ""} ${mueve ? "checked" : ""} onchange="ctTbToggle(${m.v.nro}, this.checked)"></td>` : "";
      return `<tr class="${mueve ? "" : "cerrado"}">${check}<td class="al-t-c"><b>${m.v.asiento}</b></td><td><b>${e(m.v.nombre)}</b><small>${m.v.mig ? e(m.v.tipoDoc) : "CI"} ${e(m.v.doc)}${m.v.estado === "reserva" ? " · reserva" : ""}</small></td>
        <td>${e(cam[m.s].nombre)} → ${e(cam[m.b].nombre)}${mueve && tb.tipo === "salida" && plan.destCam[m.s2].nombre !== cam[m.s].nombre ? `<small>sube en ${e(plan.destCam[m.s2].nombre)}</small>` : ""}</td><td>${ahora}</td></tr>`;
    };
    const n = plan.movers.filter(m => m.nuevo != null).length, aMano = plan.movers.filter(m => m.aMano).length;
    queda = `<section class="al-card ct-queda">
      <div class="al-card-cab"><h2 class="al-d">4. Cómo queda</h2><span>${tb.tipo === "coche" ? `${n} ${n === 1 ? "pasajero sigue" : "pasajeros siguen"} en el coche ${e(tb.coche)}${plan.cambian ? ` · <b>${plan.cambian} cambian de asiento</b>` : " · nadie cambia de asiento"}` : `${n} ${n === 1 ? "pasa" : "pasan"} a la salida de las ${plan.destSv.hora} (${e(plan.destSv.cod)})${plan.fuera.length ? ` · ${plan.fuera.length} no` : ""}${plan.cambian ? ` · ${plan.cambian} con otro asiento` : ""}`}${plan.sinLugar ? ` · <b class="ct-mal">${plan.sinLugar} sin lugar</b>` : ""}</span></div>
      ${filas.length ? `<div class="ct-auto"><button type="button" class="al-sec" onclick="ctTbAuto()"><i class="ti ti-wand"></i> Mudar automáticamente</button>
        <span>Cada pasajero a su mismo número (el 1 al 1, el 2 al 2). Si ese número no existe o está ocupado, al primero libre de la misma clase.${aMano ? ` <b>${aMano} acomodado${aMano === 1 ? "" : "s"} a mano</b> (se pierden si mudás de nuevo).` : ""}</span></div>
        ${ctPlanosHTML(sv, plan)}` : ""}
      ${filas.length ? `<details class="ct-lista" ${tb.tipo === "salida" ? "open" : ""}><summary>La lista: ${filas.length} ${filas.length === 1 ? "pasajero" : "pasajeros"}</summary><div class="al-tabla-w"><table class="al-tabla"><thead><tr>${tb.tipo === "salida" ? `<th class="al-t-c"><input type="checkbox" aria-label="Todos" ${plan.fuera.every(m => m.fijo) ? "checked" : ""} onchange="ctTbTodos(this.checked)"></th>` : ""}<th class="al-t-c">Asiento</th><th>Pasajero</th><th>Tramo</th><th>${tb.tipo === "coche" ? "En el coche " + e(tb.coche) : "En la otra salida"}</th></tr></thead>
        <tbody>${filas.map(fila).join("")}</tbody></table></div></details>` : `<p class="al-nota">Esta salida no tiene pasajeros: ${tb.tipo === "coche" ? "solo se cambia el coche." : "no hay a quién pasar."}</p>`}
      ${cocheAntes ? `<label class="al-check"><input type="checkbox" ${tb.avisar ? "checked" : ""} onchange="ct.tb.avisar=this.checked"> Avisar al taller: pedido de reparación para el coche ${e(cocheAntes)}</label>` : ""}
      ${tb.tipo === "salida" ? `<label class="al-check"><input type="checkbox" ${tb.cancelar ? "checked" : ""} onchange="ct.tb.cancelar=this.checked"> Cancelar esta salida (no se vende más)</label>` : ""}
      <div class="al-card-pie"><button type="button" class="al-btn-r" onclick="ctTbHacer()" ${tb.tipo === "salida" && !n ? "disabled" : ""}><i class="ti ti-check"></i> Hacer el transbordo${n ? ` (${n} ${n === 1 ? "pasajero" : "pasajeros"})` : ""}</button></div>
    </section>`;
  } else {
    queda = `<p class="al-nota">${tb.tipo === "coche" ? "Elegí el coche que sigue la salida para ver cómo quedan los asientos." : "Elegí la salida de destino para ver cómo quedan los pasajeros."}</p>`;
  }
  return paso + hace + queda;
}
function ctTbHechoHTML() {
  const h = ct.tb.hecho, e = trEsc;
  return `<section class="al-card ct-hecho">
    <div class="al-card-cab"><h2 class="al-d"><i class="ti ti-circle-check"></i> Transbordo hecho</h2>
      <span>${h.pasajeros} ${h.pasajeros === 1 ? "pasajero" : "pasajeros"} ${h.tipo === "coche" ? `siguen en el ${e(h.destTxt.toLowerCase())}` : `pasaron a la salida de las ${e(h.destTxt)}`}.
      ${h.tipo === "coche" ? (h.trafico ? "El Tráfico del día ya tiene el coche nuevo (cambio sin publicar)." : "El coche quedó anotado en Controles y Alpha.") : ""}
      ${h.cancelado ? "La salida original quedó cancelada." : ""}
      ${h.taller ? `Se mandó el ${e(h.taller)} al taller.` : ""}</span></div>
    <div class="al-card-pie">
      <button type="button" class="al-sec" onclick="ct.tb.hecho=null;ct.tb.origen='';ctVistaTransbordos(false)"><i class="ti ti-plus"></i> Otro transbordo</button>
      <button type="button" class="al-sec" onclick="ctTbVerManifiesto()"><i class="ti ti-list-details"></i> Ver el manifiesto</button>
      <button type="button" class="al-btn-r" onclick="ctPlanilla(${h.id})"><i class="ti ti-printer"></i> Imprimir la planilla</button>
    </div>
  </section>`;
}
function ctTbOrigen(v) {
  Object.assign(ct.tb, { origen: v, parada: 0, coche: "", destino: "", fuera: [], sug: null, sugDe: "", hecho: null,
                         motivoChip: "", motivo: "", avisar: false, cancelar: true, manual: {}, selPas: null });
  ctVistaTransbordos(false);
}
function ctTransbordoDesde(clave) { alModalCerrar(); ctTbOrigen(clave); ct.vista = "transbordos"; ctRender(true); }
function ctTbMotivo(m) {
  ct.tb.motivoChip = ct.tb.motivoChip === m ? "" : m;
  ct.tb.avisar = ct.tb.motivoChip === "Se rompió el coche";
  const m2 = document.getElementById("ct-tb-mot"); if (m2) ct.tb.motivo = m2.value;
  ctVistaTransbordos(false);
}
function ctTbTipo(t) { if (t === ct.tb.tipo) return; ct.tb.tipo = t; ct.tb.manual = {}; ct.tb.selPas = null; ctVistaTransbordos(false); }
function ctTbCoche(c) { const v = String(c || "").trim(); if (v !== ct.tb.coche) { ct.tb.manual = {}; ct.tb.selPas = null; } ct.tb.coche = v; ctVistaTransbordos(false); }
function ctTbDestDia(d) { ct.tb.destDia = d; ct.tb.destino = ""; ct.tb.manual = {}; ct.tb.selPas = null; ctVistaTransbordos(false); }
function ctTbDestino(c) { ct.tb.destino = c; ct.tb.fuera = []; ct.tb.manual = {}; ct.tb.selPas = null; ctVistaTransbordos(false); }
function ctTbToggle(nro, on) {
  const f = new Set(ct.tb.fuera || []);
  if (on) f.delete(nro); else f.add(nro);
  ct.tb.fuera = [...f]; ct.tb.cancelar = !f.size;
  ctVistaTransbordos(false);
}
function ctTbTodos(on) {
  const fecha = alISO(alFechaDe(al.dia)), sv = ctSalidasDe(fecha).find(x => x.clave === ct.tb.origen);
  ct.tb.fuera = on || !sv ? [] : ctPasajeros(fecha, sv).map(p => p.v.nro);
  ct.tb.cancelar = !!on;
  ctVistaTransbordos(false);
}
// Los coches que el tráfico sugiere para esa salida (los que están en el lugar)
async function ctTbSugerencias(sv) {
  if (!sv.id || ct.tb.sugDe === sv.clave) return;
  ct.tb.sugDe = sv.clave;
  let r = null;
  try { r = await api(`/api/trafico/salida/${sv.id}/sugerencias`); } catch (e) { r = null; }
  ct.tb.sug = ((r && r.candidatos) || []).filter(c => c.coche !== (sv.coche || sv.habitual));
  if (ct.vista === "transbordos" && ct.tb.origen === sv.clave && ct.tb.tipo === "coche" && ct.tb.sug.length) ctVistaTransbordos(false);
}
async function ctTbHacer() {
  const tb = ct.tb, fecha = alISO(alFechaDe(al.dia)), sv = ctSalidasDe(fecha).find(x => x.clave === tb.origen);
  if (!sv) return;
  const motivo = [tb.motivoChip, String(document.getElementById("ct-tb-mot")?.value || tb.motivo || "").trim()].filter(Boolean).join(": ");
  if (!motivo) { toast("Contá qué pasó: elegí un motivo o escribilo", "error"); document.getElementById("ct-tb-mot")?.focus(); return; }
  const pas = ctPasajeros(fecha, sv), plan = ctPlan(fecha, sv, pas);
  if (!plan) { toast(tb.tipo === "coche" ? "Elegí el coche que sigue la salida" : "Elegí la salida de destino", "error"); return; }
  if (tb.tipo === "salida" && alEstadoServ(plan.destFecha, plan.destSv.clave) === "cancelado") { toast("La salida de destino está cancelada", "error"); return; }
  if (tb.tipo === "salida" && plan.destSv.desactivado) { toast("La salida de destino está desactivada en la programación", "error"); return; }
  const movs = ctMovs(plan), cam = alCamino(sv), P = Math.max(0, Math.min(tb.parada || 0, cam.length - 2));
  if (tb.tipo === "salida" && !movs.length) { toast("No hay pasajeros para pasar", "error"); return; }
  const cocheAntes = sv.coche || sv.habitual || "";
  const destTxt = tb.tipo === "coche" ? `Coche ${tb.coche}` : `${plan.destSv.hora} (${plan.destSv.cod})${plan.destFecha !== fecha ? " del " + alDM(plan.destFecha) : ""}`;
  const pregunta = tb.tipo === "coche"
    ? `¿El coche ${tb.coche} sigue la salida de las ${sv.hora} en lugar del ${cocheAntes || "anterior"}?\n\n${movs.length} pasajeros${plan.cambian ? `, ${plan.cambian} cambian de asiento` : ""}.`
    : `¿Pasar ${movs.length} pasajeros a la salida de las ${destTxt}?${tb.cancelar ? "\n\nLa salida de las " + sv.hora + " queda cancelada." : ""}`;
  if (plan.sinLugar && !confirm(`${plan.sinLugar} ${plan.sinLugar === 1 ? "pasajero no tiene" : "pasajeros no tienen"} lugar y ${plan.sinLugar === 1 ? "queda" : "quedan"} en esta salida. ¿Seguir igual?`)) return;
  if (!confirm(pregunta)) return;
  const r = await alPost("/api/alpha/transbordos", {
    tipo: tb.tipo, fecha, servicio: sv.clave, motivo, parada: P ? `pasando ${cam[P].nombre}` : `antes de salir de ${cam[0].nombre}`,
    coche_antes: cocheAntes, coche_nuevo: tb.tipo === "coche" ? tb.coche : "", salida_id: tb.tipo === "coche" ? sv.id : null,
    movs, destino_txt: destTxt, hora: sv.hora, tramo: sv.cod, cancelar_origen: tb.tipo === "salida" && tb.cancelar,
    avisar_taller: !!(tb.avisar && cocheAntes) });
  if (!r) { await ctDatos(fecha, true); ctVistaTransbordos(false); return; }
  tb.hecho = { id: r.id, pasajeros: r.pasajeros, trafico: r.trafico, taller: r.taller, cancelado: r.cancelado, tipo: tb.tipo, destTxt,
               destFecha: plan.destFecha, destClave: plan.destSv.clave };
  tb.histF = "";
  delete al.datos[fecha]; delete al.datos[plan.destFecha];
  al.ocup = {}; al.manClave = "";
  toast(`Transbordo hecho: ${r.pasajeros} ${r.pasajeros === 1 ? "pasajero" : "pasajeros"}`, "success");
  await ctDatos(fecha, true);
  ctVistaTransbordos(false);
}
async function ctTbVerManifiesto() {
  const h = ct.tb.hecho; if (!h) return;
  al.dia = Math.round((alDeISO(h.destFecha) - alFechaDe(0)) / 864e5);
  await ctDatos(h.destFecha);
  ctIrAlpha("manifiesto", h.destClave);
}
// La planilla para el guarda y el despacho: quién pasó a dónde y a qué asiento
async function ctPlanilla(id) {
  let t = (ct.tb.hist || []).find(x => x.id === id);
  if (!t) { const r = await api("/api/alpha/transbordos"); t = ((r && r.transbordos) || []).find(x => x.id === id); }
  if (!t) return;
  const e = trEsc, det = (t.detalle || []).slice().sort((a, b) => (+a.antes.asiento || 999) - (+b.antes.asiento || 999));
  const as = a => a === "P" ? "Parado" : a;
  const html = `<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Transbordo ${t.id}</title>
<style>@page{size:A4;margin:12mm}*{box-sizing:border-box}body{margin:0;font-family:Arial,sans-serif;color:#000;font-size:11px}
.cab{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:2px solid #000;padding-bottom:6px;margin-bottom:8px}h1{font-size:18px;margin:0}
.dat{display:grid;grid-template-columns:120px 1fr;gap:3px 12px;margin-bottom:10px;font-size:11.5px}.dat b{font-weight:700}
table{width:100%;border-collapse:collapse}th,td{border:1px solid #999;padding:4px 5px;text-align:left;vertical-align:top}th{background:#eee;font-size:10px;text-transform:uppercase}
.c{text-align:center}.cam{font-weight:700}.firmas{display:flex;gap:40px;margin-top:40px}.firmas div{flex:1;border-top:1px solid #000;padding-top:4px;text-align:center}
.maq{margin-top:12px;font-size:9.5px;color:#555;text-align:center}</style></head><body>
<div class="cab"><div><b>LA SANTANIANA</b><h1>Planilla de transbordo N.º ${t.id}</h1></div><span>Impresa ${alAhoraISO().replace("T", " ")}</span></div>
<div class="dat"><b>Salida</b><span>${alDiaTxt(alDeISO(t.fecha))}, ${e(t.hora)} · ${e(t.tramo)}</span>
<b>Qué pasó</b><span>${e(t.motivo)}${t.parada ? ", " + e(t.parada) : ""}</span>
<b>Qué se hizo</b><span>${t.tipo === "coche" ? `El coche ${e(t.coche_nuevo)} sigue la salida en lugar del ${e(t.coche_antes || "anterior")}` : `Los pasajeros pasan a la salida de las ${e(t.destino)}`}</span>
<b>Pasajeros</b><span>${t.pasajeros}</span><b>Hecho por</b><span>${e(t.por)}, ${alDM(t.el.slice(0, 10))} a las ${t.el.slice(11, 16)}${t.taller ? ` · ${e(t.taller)} al taller` : ""}</span></div>
<table><thead><tr><th>#</th><th>Pasajero</th><th>Documento</th><th class="c">Antes</th><th>Ahora</th><th>Sube</th><th>Baja</th><th class="c">Subió</th></tr></thead><tbody>
${det.map((p, i) => `<tr><td>${i + 1}</td><td><b>${e(p.nombre)}</b>${p.estado === "reserva" ? " (reserva)" : ""}</td><td>${e(p.doc)}</td><td class="c">${as(p.antes.asiento)}</td>
<td class="${String(p.antes.asiento) !== String(p.despues.asiento) || t.tipo === "salida" ? "cam" : ""}">${t.tipo === "salida" ? `${e(p.despues.hora || "")} ${e(p.despues.tramo || "")}${p.despues.fecha !== p.antes.fecha ? " del " + alDM(p.despues.fecha) : ""} · ` : ""}${p.despues.asiento === "P" ? "Parado" : "Asiento " + p.despues.asiento}</td>
<td>${e(p.despues.sube || "")}</td><td>${e(p.despues.baja || "")}</td><td class="c">☐</td></tr>`).join("") || `<tr><td colspan="8" class="c">Sin pasajeros</td></tr>`}
</tbody></table>
<div class="firmas"><div>Chofer</div><div>Guarda</div><div>Despacho</div></div>
<div class="maq">Maqueta de Alpha: sin valor fiscal</div></body></html>`;
  alImprimir(html, "hoja");
}

// ─── Los dos planos: el coche que queda (izquierda) y el que hace el transbordo (derecha) ───
function ctPlanoHTML(pl, celda) {
  if (!pl || !pl.pisos) return "";
  return pl.pisos.map((p, pi) => {
    const nf = p.filas.length, ultimo = pi === pl.pisos.length - 1, usa4 = p.filas.some(f => f[3] != null);
    let cel = "";
    p.filas.forEach((f, fi) => f.forEach((n, pos) => {
      if (n == null) return;
      const c = celda(n) || {};
      cel += `<button type="button" class="ct-as ${c.cls || ""}" style="grid-column:${nf - fi};grid-row:${pos + 1}" ${c.dis ? "disabled" : ""} ${c.click ? `onclick="${c.click}"` : ""} title="${trEsc(c.title || "")}" aria-label="Asiento ${n}${c.title ? ": " + trEsc(c.title) : ""}"><b>${n}</b>${c.sub ? `<small>${trEsc(c.sub)}</small>` : ""}</button>`;
    }));
    if (ultimo) cel += `<div class="ct-cel" style="grid-column:${nf + 1};grid-row:1/3" aria-hidden="true"><i class="ti ti-steering-wheel"></i></div>`;
    return `<div class="ct-piso">${pl.pisos.length > 1 ? `<span class="ct-piso-t">${trEsc(p.nombre)}</span>` : ""}
      <div class="ct-grid" style="grid-template-columns:repeat(${nf}, 36px)${ultimo ? " 28px" : ""};grid-template-rows:36px 36px 8px ${usa4 ? "36px" : "0"} 36px">${cel}</div></div>`;
  }).join("");
}
function ctTbRes(plan, m) { return !plan.movers.includes(m) ? "queda" : m.nuevo == null ? "sin" : String(m.nuevo) === String(m.v.asiento) ? "igual" : "cambia"; }
function ctPlanosHTML(sv, plan) {
  const tb = ct.tb, e = trEsc, cam = alCamino(sv), sel = tb.selPas, todos = plan.movers.concat(plan.fuera);
  const res = m => ctTbRes(plan, m);
  const porAs = {};
  todos.forEach(m => { if (m.v.asiento !== "P") (porAs[+m.v.asiento] = porAs[+m.v.asiento] || []).push(m); });
  const izq = ctPlanoHTML(alPlano(sv), n => {
    const l = porAs[n];
    if (!l) return { cls: "vacio", dis: true };
    const m = l.find(x => x.v.nro === sel) || l[0], r = res(m);
    return { cls: `${r} ${l.some(x => x.v.nro === sel) ? "sel" : ""}`,
      sub: l.length > 1 ? `${l.length} pas.` : r === "cambia" ? `→ ${m.nuevo}` : r === "sin" ? "sin lugar" : r === "queda" ? "queda" : "",
      title: l.map(x => `${x.v.nombre} (${cam[x.s].nombre} → ${cam[x.b].nombre})`).join(" · "), click: `ctTbSelAsiento(${n})` };
  });
  const asig = {}, ext = {};
  plan.movers.forEach(m => { if (m.nuevo != null && m.nuevo !== "P") (asig[m.nuevo] = asig[m.nuevo] || []).push(m); });
  plan.ext.forEach(o => { if (o.a !== "P") (ext[o.a] = ext[o.a] || []).push(o); });
  const mSel = plan.movers.find(m => m.v.nro === sel);
  const der = ctPlanoHTML(plan.destPl, n => {
    const as = asig[n], ocu = ext[String(n)];
    if (as) {
      const m = as.find(x => x.v.nro === sel) || as[0], r = res(m);
      return { cls: `${r} ${as.some(x => x.v.nro === sel) ? "sel" : ""} ${m.aMano ? "mano" : ""}`, sub: r === "cambia" ? `era ${m.v.asiento}` : "",
        title: as.map(x => x.v.nombre).join(" · "),
        // Con otro pasajero elegido, tocar un asiento ya asignado los intercambia
        click: mSel && !as.includes(mSel) ? `ctTbPoner(${n})` : `ctTbSelPas(${m.v.nro})` };
    }
    if (ocu) {
      const choca = mSel ? ocu.some(o => o.s < mSel.b2 && mSel.s2 < o.b) : true;
      return { cls: choca ? "ocupado" : "libre parcial", dis: choca, title: ocu.map(o => o.nombre).join(" · "),
        sub: choca ? "" : "libre", click: choca ? "" : `ctTbPoner(${n})` };
    }
    return { cls: `libre ${mSel ? "puede" : ""}`, click: `ctTbPoner(${n})` };
  });
  const extP = plan.ext.filter(o => o.a === "P").length, parP = plan.movers.filter(m => m.nuevo === "P");
  const quedanP = Math.max(0, (plan.topeP || 0) - extP - parP.length);
  const sinL = plan.movers.filter(m => m.nuevo == null), parOrig = todos.filter(m => m.v.asiento === "P");
  const chip = (m, txt) => `<button type="button" class="al-chip ct-chip ${res(m)} ${m.v.nro === sel ? "on" : ""}" onclick="ctTbSelPas(${m.v.nro})">${txt}</button>`;
  const fechaO = alISO(alFechaDe(al.dia));
  return `<div class="ct-planos">
    <div class="ct-plano-c">
      <div class="ct-plano-t"><b>${tb.tipo === "coche" ? `Coche ${e(sv.coche || sv.habitual || "a confirmar")}` : `Salida de las ${sv.hora}`}</b><span>${e((alPlano(sv) || {}).nombre || sv.plano || "")} · el que queda</span></div>
      <div class="ct-plano-g">${izq}</div>
      ${parOrig.length ? `<div class="ct-par"><span>Parados</span>${parOrig.map(m => chip(m, `${e(m.v.nombre)}${res(m) === "cambia" ? " → " + m.nuevo : ""}`)).join("")}</div>` : ""}
    </div>
    <div class="ct-flecha" aria-hidden="true"><i class="ti ti-arrow-right"></i></div>
    <div class="ct-plano-c">
      <div class="ct-plano-t"><b>${tb.tipo === "coche" ? `Coche ${e(tb.coche)}` : `Salida de las ${plan.destSv.hora}${plan.destFecha !== fechaO ? " del " + alDM(plan.destFecha) : ""}`}</b><span>${e((plan.destPl || {}).nombre || "")} · ${tb.tipo === "coche" ? "el que sigue la salida" : e(plan.destSv.cod)}</span></div>
      <div class="ct-plano-g">${der}</div>
      ${plan.topeP ? `<div class="ct-par"><button type="button" class="al-chip ${mSel ? "ct-puede" : ""}" onclick="ctTbPoner('P')" ${quedanP || (mSel && mSel.nuevo === "P") ? "" : "disabled"}><i class="ti ti-man"></i> Parado <small>${quedanP} ${quedanP === 1 ? "lugar" : "lugares"}</small></button>${parP.map(m => chip(m, e(m.v.nombre))).join("")}</div>` : ""}
      ${sinL.length ? `<div class="ct-par ct-mal"><span>Sin lugar</span>${sinL.map(m => chip(m, `${e(m.v.nombre)} (${m.v.asiento})`)).join("")}</div>` : ""}
    </div>
  </div>
  <div class="ct-plano-ayuda" role="status">
    ${mSel ? `<span><b>${e(mSel.v.nombre)}</b> (era el ${mSel.v.asiento}, ${e(cam[mSel.s].nombre)} → ${e(cam[mSel.b].nombre)}): tocá un asiento libre a la derecha${mSel.nuevo != null ? " o uno ocupado por otro de los que se mudan para intercambiarlos" : ""}. <button type="button" class="al-link" onclick="ctTbSelPas(null)">Soltar</button></span>`
      : `<span>Para acomodar a alguien a mano, tocalo en el plano de la izquierda y después tocá el asiento en el de la derecha.</span>`}
    <span class="ct-ley"><i class="igual"></i>mismo número <i class="cambia"></i>otro asiento <i class="sin"></i>sin lugar <i class="ocupado"></i>ya ocupado <i class="libre"></i>libre</span>
  </div>`;
}
function ctTbActual() {
  const fecha = alISO(alFechaDe(al.dia)), sv = ctSalidasDe(fecha).find(x => x.clave === ct.tb.origen);
  if (!sv) return {};
  const pas = ctPasajeros(fecha, sv);
  return { fecha, sv, pas, plan: ctPlan(fecha, sv, pas) };
}
function ctTbSelPas(nro) { ct.tb.selPas = nro == null || ct.tb.selPas === nro ? null : nro; ctVistaTransbordos(false); }
function ctTbSelAsiento(n) {
  const { plan } = ctTbActual();
  if (!plan) return;
  const l = plan.movers.concat(plan.fuera).filter(m => +m.v.asiento === n);
  if (!l.length) return;
  const i = l.findIndex(m => m.v.nro === ct.tb.selPas);
  if (l.length === 1 && i === 0) ct.tb.selPas = null;
  else {
    const m = l[(i + 1) % l.length];
    if (!plan.movers.includes(m)) {
      toast(m.fijo ? m.problema : "Ese pasajero no pasa: tildalo en la lista para que pase", "info");
      return;
    }
    ct.tb.selPas = m.v.nro;
  }
  ctVistaTransbordos(false);
}
function ctTbPoner(a) {
  const tb = ct.tb;
  if (tb.selPas == null) { toast("Primero tocá un pasajero en el plano de la izquierda", "info"); return; }
  const { plan } = ctTbActual();
  const m = plan && plan.movers.find(x => x.v.nro === tb.selPas);
  if (!m) { toast("Ese pasajero no se muda", "error"); return; }
  const man = Object.assign({}, tb.manual);
  if (a === "P") {
    if (m.v.estado !== "vendido") { toast("Una reserva no puede ir parada", "error"); return; }
    const usados = plan.ext.filter(o => o.a === "P").length + plan.movers.filter(x => x !== m && x.nuevo === "P").length;
    if (usados >= (plan.topeP || 0)) { toast("No quedan lugares parados", "error"); return; }
  } else {
    const otro = plan.movers.find(x => x !== m && String(x.nuevo) === String(a));
    if (otro) {
      // Se intercambian: el otro va al lugar que tenía este
      if (m.nuevo != null) man[otro.v.nro] = m.nuevo; else delete man[otro.v.nro];
    } else if (plan.ext.some(o => o.a === String(a) && o.s < m.b2 && m.s2 < o.b)) {
      toast(`El ${a} ya está ocupado en ese tramo`, "error"); return;
    }
  }
  man[m.v.nro] = a;
  tb.manual = man; tb.selPas = null;
  ctVistaTransbordos(false);
}
function ctTbAuto() {
  ct.tb.manual = {}; ct.tb.selPas = null;
  ctVistaTransbordos(false);
  toast("Mudados automáticamente: cada uno a su mismo número cuando se puede", "success");
}

// ════════════════════════════════════════════════════════════════════════════
// PROGRAMACIÓN: desactivar horarios por un período (no se venden; la agencia
// no los ve) y agregar servicios que no están en el tráfico (refuerzos)
// ════════════════════════════════════════════════════════════════════════════
const CT_DIAS = [["0", "L", "lunes"], ["1", "M", "martes"], ["2", "X", "miércoles"], ["3", "J", "jueves"], ["4", "V", "viernes"], ["5", "S", "sábado"], ["6", "D", "domingo"]];
function ctDiasTxt(d) {
  d = d || "0123456";
  if (d === "0123456") return "todos los días";
  if (d === "01234") return "de lunes a viernes";
  if (d === "56") return "sábados y domingos";
  return CT_DIAS.filter(x => d.includes(x[0])).map(x => x[2]).join(", ");
}
function ctHorariosConocidos(cor, lado) {
  const vistos = new Map();
  Object.values(al.datos).forEach(dia => ((dia && dia.corredores) || []).filter(c => c.clave === cor).forEach(c =>
    ["ida", "regreso"].filter(l => !lado || l === lado).forEach(l => (c[l] || []).forEach(x => {
      if (x.adicional) return;
      const k = `${x.hora}|${x.destino}`;
      if (!vistos.has(k)) vistos.set(k, { hora: x.hora, destino: x.destino, lado: l });
    }))));
  return [...vistos.values()].sort((a, b) => a.hora.localeCompare(b.hora) || a.destino.localeCompare(b.destino));
}
async function ctVistaProgramacion(animar) {
  const pg = ct.pg, hoy = alISO(new Date()), e = trEsc;
  if (!document.querySelector(".ct-pg")) ctCargando(animar);
  await ctDatos(alISO(alFechaDe(al.dia)));
  // Los horarios de toda la semana, para elegir
  const faltan = [];
  for (let i = 0; i < 7; i++) { const f = alISO(alFechaDe(i)); if (!al.datos[f]) faltan.push(api(`/api/alpha/dia/${f}`).then(d => { if (d && d.corredores) al.datos[f] = d; }).catch(() => {})); }
  const [r] = await Promise.all([api("/api/alpha/programacion"), ...faltan]);
  if (ct.vista !== "programacion") return;
  const reglas = (r && r.reglas) || [], cors = (al.cfg && al.cfg.corredores) || [];
  ct.pgReglas = reglas;
  if (!pg.desde) { pg.desde = hoy; pg.hasta = hoy; }
  if (!pg.corredor || !cors.some(c => c.clave === pg.corredor)) pg.corredor = cors.some(c => c.clave === al.cor) ? al.cor : (cors[0] || {}).clave || "";
  if (pg.tipo === "activar" && !pg.lado) pg.lado = "ida";
  const conocidos = ctHorariosConocidos(pg.corredor, pg.lado), titulo = k => ((cors.find(c => c.clave === k) || {}).titulo || String(k).split("|").pop());
  const des = pg.tipo === "desactivar";
  const chipsLado = (des ? [["ida", "Ida"], ["regreso", "Regreso"], ["", "Los dos"]] : [["ida", "Ida"], ["regreso", "Regreso"]])
    .map(([k, t]) => `<button type="button" class="al-chip ${pg.lado === k ? "on" : ""}" aria-pressed="${pg.lado === k}" onclick="ct.pg.lado='${k}';ct.pg.horario='';ctVistaProgramacion(false)">${t}</button>`).join("");
  const form = `<section class="al-card">
      <div class="al-card-cab"><h2 class="al-d">Nueva regla</h2><span>Para un período y los días de la semana que elijas. Se quita cuando quieras.</span></div>
      <div class="ct-opc" role="radiogroup" aria-label="Qué hacer">
        <button type="button" class="ct-op ${des ? "on" : ""}" role="radio" aria-checked="${des}" onclick="ct.pg.tipo='desactivar';ctVistaProgramacion(false)"><i class="ti ti-calendar-off"></i><b>Desactivar un horario</b><span>No sale en ese período: no se vende y las agencias no lo ven.</span></button>
        <button type="button" class="ct-op ${!des ? "on" : ""}" role="radio" aria-checked="${!des}" onclick="ct.pg.tipo='activar';if(!ct.pg.lado)ct.pg.lado='ida';ctVistaProgramacion(false)"><i class="ti ti-calendar-plus"></i><b>Agregar un servicio</b><span>Un refuerzo o un horario de temporada que no está en el tráfico.</span></button>
      </div>
      <div class="al-fila">
        <label class="al-campo"><span>Recorrido</span><select onchange="ct.pg.corredor=this.value;ct.pg.horario='';ctVistaProgramacion(false)">${cors.map(c => `<option value="${e(c.clave)}" ${c.clave === pg.corredor ? "selected" : ""}>Asunción ⇄ ${e(c.titulo)}${c.tipo === "internacional" ? " (internacional)" : ""}</option>`).join("")}</select></label>
        <div class="ct-campo-chips"><span>Sentido</span><div class="al-chips">${chipsLado}</div></div>
      </div>
      ${des ? `<label class="al-campo"><span>Horario</span><select onchange="ct.pg.horario=this.value"><option value="">Todos los horarios de ese recorrido${pg.lado ? " y sentido" : ""}</option>${conocidos.map(h => `<option value="${e(h.hora + "|" + h.destino)}" ${pg.horario === h.hora + "|" + h.destino ? "selected" : ""}>${h.hora} · ${e(h.destino)}${pg.lado ? "" : " · " + h.lado}</option>`).join("")}</select></label>`
        : `<div class="al-fila">
          <label class="al-campo ci"><span>Hora</span><input type="time" value="${e(pg.hora)}" onchange="ct.pg.hora=this.value"></label>
          <label class="al-campo"><span>Destino (como en el tráfico)</span><input list="ct-pg-dest" value="${e(pg.destino)}" placeholder="Ej.: ASU/COP X 25" oninput="ct.pg.destino=this.value.toUpperCase();this.value=ct.pg.destino"></label>
          <datalist id="ct-pg-dest">${[...new Set(conocidos.map(h => h.destino))].map(d => `<option value="${e(d)}"></option>`).join("")}</datalist>
          <label class="al-campo"><span>Plano (si todavía no tiene coche)</span><select onchange="ct.pg.plano=this.value"><option value="">El de siempre</option>${Object.entries(alPlanos()).map(([k, p]) => `<option value="${e(k)}" ${pg.plano === k ? "selected" : ""}>${e(p.nombre || k)}</option>`).join("")}</select></label>
        </div>`}
      <div class="al-fila ct-pg-f">
        <label class="al-campo ci"><span>Desde</span><input type="date" value="${pg.desde}" onchange="ct.pg.desde=this.value;if(ct.pg.hasta<this.value){ct.pg.hasta=this.value};ctVistaProgramacion(false)"></label>
        <label class="al-campo ci"><span>Hasta</span><input type="date" value="${pg.hasta}" min="${pg.desde}" onchange="ct.pg.hasta=this.value"></label>
        <div class="ct-campo-chips"><span>Días</span><div class="al-chips ct-dias">${CT_DIAS.map(([k, t, n]) => `<button type="button" class="al-chip ${pg.dias.includes(k) ? "on" : ""}" aria-pressed="${pg.dias.includes(k)}" title="${n}" onclick="ctPgDia('${k}')">${t}</button>`).join("")}
          <button type="button" class="al-link" onclick="ct.pg.dias='0123456';ctVistaProgramacion(false)">todos</button><button type="button" class="al-link" onclick="ct.pg.dias='01234';ctVistaProgramacion(false)">lun a vie</button><button type="button" class="al-link" onclick="ct.pg.dias='56';ctVistaProgramacion(false)">fin de semana</button></div></div>
      </div>
      <label class="al-campo"><span>Motivo${des ? "" : " (opcional)"}</span><input maxlength="160" value="${e(pg.motivo)}" placeholder="${des ? "Ej.: temporada baja" : "Ej.: refuerzo de fin de año"}" oninput="ct.pg.motivo=this.value"></label>
      <div class="al-card-pie"><button type="button" class="al-btn-r" onclick="ctPgCrear()"><i class="ti ti-${des ? "calendar-off" : "calendar-plus"}"></i> ${des ? "Desactivar" : "Agregar el servicio"}</button></div>
    </section>`;
  const fila = x => `<div class="al-cierre ct-regla ${x.hasta < hoy ? "pasada" : ""}">
      <span class="al-est ${x.tipo === "desactivar" ? "anulado" : "vendido"}">${x.tipo === "desactivar" ? "Desactivado" : "Agregado"}</span>
      <div class="ct-regla-t"><b>Asunción ⇄ ${e(titulo(x.corredor))} · ${x.lado === "ida" ? "ida" : x.lado === "regreso" ? "regreso" : "ida y regreso"} · ${x.hora ? `${x.hora}${x.destino ? " " + e(x.destino) : ""}` : "todos los horarios"}</b>
        <small>Del ${alDM(x.desde)}/${x.desde.slice(2, 4)} al ${alDM(x.hasta)}/${x.hasta.slice(2, 4)}, ${ctDiasTxt(x.dias)}${x.motivo ? " · " + e(x.motivo) : ""}${x.plano ? " · plano " + e(x.plano) : ""} · ${e(x.por || "")}</small></div>
      ${x.hasta >= hoy ? `<button type="button" class="al-sec" onclick="ctPgQuitar(${x.id})"><i class="ti ti-${x.tipo === "desactivar" ? "calendar-check" : "trash"}"></i> ${x.tipo === "desactivar" ? "Reactivar" : "Sacar"}</button>` : ""}
    </div>`;
  const vig = reglas.filter(x => x.hasta >= hoy), pas = reglas.filter(x => x.hasta < hoy);
  content.innerHTML = ctShell(`
    <div class="al-vista ct-pg">
      <div class="al-v-cab"><h1 class="al-d">Programación</h1><span>Activar y desactivar servicios por período. Lo que está en el tráfico se vende salvo que se desactive acá.</span></div>
      ${form}
      <h2 class="al-d al-h2">Vigentes y próximas</h2>
      ${vig.length ? `<div class="al-cierres">${vig.map(fila).join("")}</div>` : `<p class="al-nota">No hay reglas: se vende todo lo que trae el tráfico.</p>`}
      ${pas.length ? `<details class="al-ayuda"><summary>Pasadas (${pas.length})</summary><div class="al-cierres">${pas.map(fila).join("")}</div></details>` : ""}
    </div>`, animar);
}
function ctPgDia(k) {
  const d = new Set(ct.pg.dias.split(""));
  if (d.has(k)) d.delete(k); else d.add(k);
  ct.pg.dias = [...d].sort().join("");
  ctVistaProgramacion(false);
}
async function ctPgCrear() {
  const pg = ct.pg, cors = (al.cfg && al.cfg.corredores) || [], cor = cors.find(c => c.clave === pg.corredor);
  if (!cor) { toast("Elegí el recorrido", "error"); return; }
  if (!pg.dias) { toast("Elegí al menos un día de la semana", "error"); return; }
  const des = pg.tipo === "desactivar";
  const [hora, destino] = des ? (pg.horario ? pg.horario.split("|") : ["", ""]) : [pg.hora, pg.destino.trim()];
  if (!des && (!hora || !destino)) { toast("Poné la hora y el destino del servicio", "error"); return; }
  if (des && !pg.motivo.trim()) { toast("Contá por qué se desactiva", "error"); return; }
  const que = `${des ? "Desactivar" : "Agregar"} Asunción ⇄ ${cor.titulo}, ${pg.lado || "ida y regreso"}, ${hora ? hora + " " + destino : "todos los horarios"}, del ${alDM(pg.desde)} al ${alDM(pg.hasta)}, ${ctDiasTxt(pg.dias)}`;
  if (!confirm(`¿${que}?`)) return;
  const r = await alPost("/api/alpha/programacion", { tipo: pg.tipo, corredor: cor.clave, corredor_nombre: cor.corredor, lado: pg.lado,
    hora, destino, desde: pg.desde, hasta: pg.hasta, dias: pg.dias, plano: des ? "" : pg.plano, motivo: pg.motivo.trim() });
  if (!r) return;
  al.datos = {}; al.ocup = {};
  pg.motivo = ""; pg.horario = ""; pg.hora = ""; pg.destino = "";
  toast(des ? "Horario desactivado en ese período" : "Servicio agregado en ese período", "success");
  await ctVistaProgramacion(false);
  if (r.afectados && r.afectados.length) {
    const tot = r.afectados.reduce((a, x) => a + x.pasajeros, 0), x0 = r.afectados[0];
    al.ctPgAf = r.afectados;
    alModal({ titulo: "Hay pasajes vendidos en esas salidas", ancho: 520, cuerpo: `
      <p class="al-m-txt">Quedaron desactivadas salidas que ya tienen <b>${tot} ${tot === 1 ? "pasajero" : "pasajeros"}</b> (vendidos o con reserva). Pasalos a otra salida con el transbordo.</p>
      <ul class="ct-af">${r.afectados.slice(0, 12).map((x, i) => `<li><span>${alDiaTxt(alDeISO(x.fecha))}, ${x.hora}</span><b>${x.pasajeros}</b><button type="button" class="al-link" onclick="ctPgTransbordo(${i})">Transbordo</button></li>`).join("")}</ul>
      ${r.afectados.length > 12 ? `<p class="al-hint">y ${r.afectados.length - 12} salidas más</p>` : ""}`,
      pie: `<button type="button" class="al-sec" onclick="alModalCerrar()">Después</button><button type="button" class="al-btn-r" onclick="ctPgTransbordo(0)"><i class="ti ti-arrows-shuffle"></i> Hacer el transbordo de ${alDM(x0.fecha)} ${x0.hora}</button>` });
  }
}
async function ctPgTransbordo(i) {
  const x = (al.ctPgAf || [])[i]; if (!x) return;
  alModalCerrar();
  const d = Math.round((alDeISO(x.fecha) - alFechaDe(0)) / 864e5);
  if (d < 0) { toast("Esa salida ya pasó", "error"); return; }
  al.dia = d;
  await ctDatos(x.fecha);
  ctTbOrigen(x.servicio);
  ct.tb.tipo = "salida"; ct.tb.motivoChip = "Otro"; ct.tb.motivo = "Servicio desactivado";
  ct.vista = "transbordos"; ctRender(true);
}
async function ctPgQuitar(id) {
  const x = (ct.pgReglas || []).find(r => r.id === id);
  if (!x || !confirm(x.tipo === "desactivar" ? "¿Reactivar? Esos horarios se vuelven a vender." : "¿Sacar el servicio agregado? Si tiene pasajes vendidos, quedan en un servicio que ya no aparece: pasalos antes con el transbordo.")) return;
  const r = await api(`/api/alpha/programacion/${id}`, { method: "DELETE" });
  if (!r || !r.ok) { toast((r && (r.msg || r.error)) || "No se pudo", "error"); return; }
  al.datos = {}; al.ocup = {};
  toast(x.tipo === "desactivar" ? "Reactivado" : "Servicio sacado", "success");
  ctVistaProgramacion(false);
}
