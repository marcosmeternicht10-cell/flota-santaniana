// ════════════════════════════════════════════════════════════════════════
//  CAJAS — débitos y créditos varios (como Walrus, pero mejor)
//  Varias cajas con su saldo en vivo · egresos e ingresos con comprobante ·
//  IVA separado solo · foto de la factura · cierre diario con arqueo ·
//  libro IVA en Excel para el contador.
// ════════════════════════════════════════════════════════════════════════

const cj = {
  meta: null, cajas: [], caja: null, movs: [], tot: null,
  rango: "mes", desde: "", hasta: "", tipo: "", q: "",
};
const cjEsc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const cjMil = v => Math.round(+v || 0).toLocaleString("es-PY").replace(/,/g, ".");
const cjGs = v => "Gs. " + cjMil(v);
const cjNum = v => {
  let s = String(v ?? "").trim().replace(/\s/g, "");
  if (/^-?\d{1,3}(\.\d{3})+(,\d+)?$/.test(s)) s = s.replace(/\./g, "").replace(",", ".");
  else s = s.replace(",", ".");
  return parseFloat(s) || 0;
};
const cjDmy = f => f ? `${f.slice(8, 10)}/${f.slice(5, 7)}/${f.slice(0, 4)}` : "";
const cjDm = f => f ? `${f.slice(8, 10)}/${f.slice(5, 7)}` : "";
const cjIso = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
const cjPuede = () => cj.meta && cj.meta.puede;
function cjOpts(obj, sel) { return Object.entries(obj).map(([k, t]) => `<option value="${k}" ${k === sel ? "selected" : ""}>${cjEsc(t)}</option>`).join(""); }
async function cjJson(url, metodo = "POST", cuerpo) {
  return api(url, { method: metodo, headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo || {}) }).catch(() => null);
}

// IVA incluido: 10 % → total/11 ; 5 % → total/21
function cjSepararIva(total, tipo, dec = 0) {
  const r = { exento: 0, grav5: 0, grav10: 0, iva5: 0, iva10: 0 };
  const red = v => dec ? Math.round(v * 100) / 100 : Math.round(v);
  total = red(total);
  if (tipo === "10") { r.grav10 = total; r.iva10 = red(total / 11); }
  else if (tipo === "5") { r.grav5 = total; r.iva5 = red(total / 21); }
  else r.exento = total;
  return r;
}
function cjRucDv(base) {
  base = String(base || "").replace(/\D/g, "");
  if (!base) return null;
  let t = 0, k = 2;
  for (const d of base.split("").reverse()) { t += +d * k; k = k === 11 ? 2 : k + 1; }
  const r = t % 11;
  return r > 1 ? 11 - r : 0;
}

function cjRangoFechas() {
  const h = new Date(cj.meta.hoy + "T12:00:00");
  if (cj.rango === "hoy") return [cj.meta.hoy, cj.meta.hoy];
  if (cj.rango === "semana") { const d = new Date(h); d.setDate(d.getDate() - ((d.getDay() + 6) % 7)); return [cjIso(d), cj.meta.hoy]; }
  if (cj.rango === "mes") return [cj.meta.hoy.slice(0, 8) + "01", cj.meta.hoy];
  if (cj.rango === "ant") { const d = new Date(h.getFullYear(), h.getMonth() - 1, 1); const f = new Date(h.getFullYear(), h.getMonth(), 0); return [cjIso(d), cjIso(f)]; }
  if (cj.rango === "abierto") return ["", ""];
  return [cj.desde, cj.hasta];
}

// ─── Pantalla ───────────────────────────────────────────────────────────
async function renderCajas() {
  status("Tesorería — cajas, flujo de caja, pagos, cheques y conciliación");
  content.innerHTML = `<div class="section"><div class="dossier-loading"><div class="dossier-spinner"></div></div></div>`;
  const r = await api("/api/cajas").catch(() => null);
  if (!r || !r.ok) { content.innerHTML = `<div class="section"><div class="empty"><i class="ti ti-alert-triangle"></i>No se pudieron traer las cajas.</div></div>`; return; }
  cj.meta = r;
  cj.cajas = r.cajas;
  let guardada = null;
  try { guardada = +localStorage.getItem("cj_caja"); if (!cj.vista) cj.vista = localStorage.getItem("cj_vista") || "movs"; } catch (e) { }
  cj.caja = cj.cajas.find(c => c.id === (cj.caja && cj.caja.id)) || cj.cajas.find(c => c.id === guardada) || cj.cajas[0] || null;
  content.innerHTML = `
    <div class="page-header cj-head">
      <div>
        <h1><i class="ti ti-cash-register"></i> Tesorería</h1>
        <p>Cajas y cuentas, lo que viene para pagar y cobrar, los cheques y el extracto del banco: la plata de la empresa en un solo lugar.</p>
      </div>
      <div class="cj-head-acc">
        <button class="btn btn-ghost" onclick="cjLibro()"><i class="ti ti-book"></i> Libro IVA</button>
        ${cjPuede() && cj.cajas.length > 1 ? `<button class="btn btn-ghost" onclick="cjTransferir()"><i class="ti ti-arrows-exchange"></i> Transferir</button>` : ""}
        ${r.admin ? `<button class="btn btn-ghost" onclick="cjAjustes()"><i class="ti ti-settings"></i> Cajas y conceptos</button>` : ""}
      </div>
    </div>
    <div class="section">
      <div class="cj-tabs" id="cj-tabs" role="tablist"></div>
      <div class="cj-cajas" id="cj-cajas"></div>
      <div id="cj-cuerpo"></div>
    </div>`;
  cjPintarCajas();
  tsResumen();
  cjIrVista(cj.vista || "movs");
}
// Las pestañas de Tesorería
const CJ_VISTAS = [["movs", "Movimientos", "list-details"], ["flujo", "Flujo de caja", "chart-line"], ["prog", "Pagos y cobros", "calendar-dollar"],
                   ["cheques", "Cheques", "file-dollar"], ["conc", "Conciliación", "building-bank"]];
function cjPintarTabs() {
  const b = document.getElementById("cj-tabs");
  if (!b) return;
  const r = ts.res || {};
  const badge = { prog: (r.vencidos || 0) + (r.por_aprobar || 0), cheques: r.cheques_avisos || 0, conc: r.extracto_pendiente || 0 };
  b.innerHTML = CJ_VISTAS.map(([k, t, ic]) => `<button type="button" role="tab" aria-selected="${cj.vista === k}" class="${cj.vista === k ? "on" : ""}" onclick="cjIrVista('${k}')">
    <i class="ti ti-${ic}"></i> ${t}${badge[k] ? `<span class="cj-tab-n">${badge[k]}</span>` : ""}</button>`).join("");
}
function cjIrVista(v) {
  cj.vista = v;
  try { localStorage.setItem("cj_vista", v); } catch (e) { }
  cjPintarTabs();
  const cards = document.getElementById("cj-cajas");
  if (cards) cards.style.display = v === "movs" ? "" : "none";
  const cuerpo = document.getElementById("cj-cuerpo");
  if (!cuerpo) return;
  if (v === "movs") {
    if (cj.caja) cjCargarMovs();
    else cuerpo.innerHTML = `<div class="empty"><i class="ti ti-cash-register"></i>No hay cajas activas.${cj.meta.admin ? " Creá una en «Cajas y conceptos»." : ""}</div>`;
    return;
  }
  cuerpo.innerHTML = `<div class="dossier-loading"><div class="dossier-spinner"></div></div>`;
  ({ flujo: tsFlujo, prog: tsProg, cheques: tsCheques, conc: tsConc })[v]();
}

function cjPintarCajas() {
  const box = document.getElementById("cj-cajas");
  if (!box) return;
  box.innerHTML = cj.cajas.map(c => {
    const sel = cj.caja && c.id === cj.caja.id;
    const atraso = c.sin_cerrar && c.sin_cerrar_desde && c.sin_cerrar_desde < cj.meta.hoy;
    return `<button type="button" class="cj-caja ${sel ? "sel" : ""}" onclick="cjElegirCaja(${c.id})" aria-pressed="${sel}">
      <span class="cj-caja-nom"><i class="ti ti-${c.tipo === "banco" ? "building-bank" : "cash-register"}"></i> ${cjEsc(c.nombre)}</span>
      <span class="cj-caja-saldo ${c.saldo < 0 ? "neg" : ""}">${c.saldo < 0 ? "−" : ""}${cjGs(Math.abs(c.saldo))}</span>
      ${c.tipo === "banco" ? `<span class="cj-caja-sub">${cjEsc(c.banco || "Banco")}${c.numero_cuenta ? ` · cta. ${cjEsc(c.numero_cuenta)}` : ""}</span>`
        : `<span class="cj-caja-sub">Efectivo en caja <b>${cjGs(c.efectivo)}</b></span>`}
      <span class="cj-caja-pie ${atraso ? "atraso" : ""}">
        ${c.sin_cerrar
          ? `<i class="ti ti-${atraso ? "alert-triangle" : "lock-open"}"></i> ${c.sin_cerrar} sin cerrar${atraso ? ` desde el ${cjDm(c.sin_cerrar_desde)}` : ""}`
          : `<i class="ti ti-lock"></i> ${c.ultimo_cierre ? "Cerrada al " + cjDm(c.ultimo_cierre) : "Sin movimientos"}`}
      </span>
    </button>`;
  }).join("");
}

function cjElegirCaja(id) {
  cj.caja = cj.cajas.find(c => c.id === id);
  try { localStorage.setItem("cj_caja", id); } catch (e) { }
  cjPintarCajas();
  cjCargarMovs();
}

async function cjRefrescarCajas() {
  const r = await api("/api/cajas").catch(() => null);
  if (!r || !r.ok) return;
  cj.meta = r;
  cj.cajas = r.cajas;
  cj.caja = cj.cajas.find(c => c.id === (cj.caja && cj.caja.id)) || cj.cajas[0];
  cjPintarCajas();
}

async function cjCargarMovs() {
  const cuerpo = document.getElementById("cj-cuerpo");
  if (!cuerpo || !cj.caja) return;
  const [d, h] = cjRangoFechas();
  const qs = new URLSearchParams({ desde: d, hasta: h, tipo: cj.tipo, q: cj.q });
  if (cj.rango === "abierto") qs.set("estado", "vigente");
  const r = await api(`/api/cajas/${cj.caja.id}/movs?${qs}`).catch(() => null);
  if (!r || !r.ok) { cuerpo.innerHTML = `<div class="empty">No se pudieron traer los movimientos.</div>`; return; }
  cj.movs = cj.rango === "abierto" ? r.movs.filter(m => !m.cierre_id) : r.movs;
  cj.tot = r.totales;
  if (cj.rango === "abierto") {
    cj.tot = { ingresos: 0, egresos: 0, iva10: 0, iva5: 0, n: 0, sin_foto: 0 };
    cj.movs.forEach(m => { cj.tot.n++; cj.tot[m.tipo === "ingreso" ? "ingresos" : "egresos"] += +m.total_gs; cj.tot.iva10 += m.iva10 * m.cotizacion; cj.tot.iva5 += m.iva5 * m.cotizacion; if (m.doc_tipo !== "interno" && !m.archivos) cj.tot.sin_foto++; });
  }
  cjPintarCuerpo();
}

function cjPintarCuerpo() {
  const cuerpo = document.getElementById("cj-cuerpo");
  if (!cuerpo) return;
  const c = cj.caja, t = cj.tot;
  const rangos = { hoy: "Hoy", semana: "Semana", mes: "Este mes", ant: "Mes pasado", abierto: "Sin cerrar", otro: "Fechas…" };
  cuerpo.innerHTML = `
    <div class="cj-barra">
      ${cjPuede() ? `<div class="cj-nuevos">
        <button class="btn cj-btn-egr" onclick="cjNuevo('egreso')"><i class="ti ti-arrow-up-right"></i> Egreso <small>se pagó algo</small></button>
        <button class="btn cj-btn-ing" onclick="cjNuevo('ingreso')"><i class="ti ti-arrow-down-left"></i> Ingreso <small>entró plata</small></button>
      </div>` : ""}
      <div class="cj-acc">
        ${cjPuede() ? `<button class="btn btn-primary" onclick="cjCierre()"><i class="ti ti-lock"></i> Cerrar caja${c.sin_cerrar ? ` <span class="cj-pill">${c.sin_cerrar}</span>` : ""}</button>` : ""}
        <button class="btn btn-ghost" onclick="cjCierres()"><i class="ti ti-history"></i> Cierres</button>
        <button class="btn btn-ghost" onclick="cjExtracto()"><i class="ti ti-file-spreadsheet"></i> Extracto</button>
      </div>
    </div>
    <div class="cj-filtros">
      <div class="cj-seg" role="tablist" aria-label="Período">
        ${Object.entries(rangos).map(([k, v]) => `<button type="button" class="${cj.rango === k ? "on" : ""}" onclick="cjRango('${k}')">${v}</button>`).join("")}
      </div>
      ${cj.rango === "otro" ? `<span class="cj-fechas">
        <input type="date" value="${cj.desde}" onchange="cj.desde=this.value;cjCargarMovs()" aria-label="Desde">
        <span>a</span>
        <input type="date" value="${cj.hasta}" onchange="cj.hasta=this.value;cjCargarMovs()" aria-label="Hasta"></span>` : ""}
      <select class="cj-sel" onchange="cj.tipo=this.value;cjCargarMovs()" aria-label="Tipo">
        <option value="">Egresos e ingresos</option>
        <option value="egreso" ${cj.tipo === "egreso" ? "selected" : ""}>Solo egresos</option>
        <option value="ingreso" ${cj.tipo === "ingreso" ? "selected" : ""}>Solo ingresos</option>
      </select>
      <label class="cj-buscar"><i class="ti ti-search"></i>
        <input type="search" value="${cjEsc(cj.q)}" placeholder="Proveedor, RUC, factura, concepto o N°" oninput="clearTimeout(cj._qt);cj._qt=setTimeout(()=>{cj.q=this.value;cjCargarMovs()},300)"></label>
    </div>
    <div class="cj-kpis">
      <div class="cj-kpi"><span>Ingresos</span><b class="ing">${cjGs(t.ingresos)}</b></div>
      <div class="cj-kpi"><span>Egresos</span><b class="egr">${cjGs(t.egresos)}</b></div>
      <div class="cj-kpi"><span>Neto del período</span><b>${(t.ingresos - t.egresos) < 0 ? "−" : ""}${cjGs(Math.abs(t.ingresos - t.egresos))}</b></div>
      <div class="cj-kpi"><span>IVA en comprobantes</span><b>${cjGs(t.iva10 + t.iva5)}</b><small>10 %: ${cjMil(t.iva10)} · 5 %: ${cjMil(t.iva5)}</small></div>
      <div class="cj-kpi ${t.sin_foto ? "ojo" : ""}"><span>Sin foto de la factura</span><b>${t.sin_foto}</b><small>${t.sin_foto ? "subilas antes de cerrar" : "todo con su comprobante"}</small></div>
    </div>
    ${cj.movs.length ? `
    <div class="cj-tabla-wrap"><table class="cj-tabla">
      <thead><tr><th>N°</th><th>Fecha</th><th>Proveedor / cliente</th><th>Concepto</th><th>Comprobante</th><th>Medio</th><th class="num">Ingreso</th><th class="num">Egreso</th><th></th></tr></thead>
      <tbody>${cj.movs.map(cjFila).join("")}</tbody>
    </table></div>` : `<div class="empty cj-vacio"><i class="ti ti-receipt-off"></i>${cj.q ? "Nada coincide con la búsqueda." : "No hay movimientos en este período."}${cjPuede() && !cj.q ? `<div class="cj-vacio-acc"><button class="btn cj-btn-egr" onclick="cjNuevo('egreso')"><i class="ti ti-plus"></i> Cargar un egreso</button></div>` : ""}</div>`}`;
}

function cjFila(m) {
  const ing = m.tipo === "ingreso", anul = m.estado !== "vigente";
  const doc = (cj.meta.docs[m.doc_tipo] || "").replace(" (sin factura)", "");
  return `<tr class="${anul ? "anul" : ""}" onclick="cjVer(${m.id})" tabindex="0" onkeydown="if(event.key==='Enter')cjVer(${m.id})">
    <td class="cj-n">${m.numero}</td>
    <td class="cj-fe">${cjDm(m.fecha_oper)}</td>
    <td class="cj-q"><b>${cjEsc(m.contraparte || "—")}</b>${m.ruc ? `<small>${cjEsc(m.ruc)}</small>` : ""}</td>
    <td class="cj-c">${cjEsc((m.conceptos || []).join(", "))}${m.observacion ? `<small>${cjEsc(m.observacion.slice(0, 90))}</small>` : ""}</td>
    <td class="cj-d">${cjEsc(doc)}${m.doc_numero ? `<small>${cjEsc(m.doc_numero)}</small>` : ""}</td>
    <td class="cj-m">${cjEsc(cj.meta.medios[m.medio] || m.medio)}</td>
    <td class="num ing">${ing ? cjMil(m.total_gs) : ""}</td>
    <td class="num egr">${ing ? "" : cjMil(m.total_gs)}</td>
    <td class="cj-ic">
      ${anul ? `<span class="cj-tag anul">Anulado</span>` : ""}
      ${m.transf_id ? `<i class="ti ti-arrows-exchange" title="Transferencia entre cajas"></i>` : ""}
      ${m.archivos ? `<i class="ti ti-paperclip" title="${m.archivos} archivo(s)"></i>` : (m.doc_tipo !== "interno" && !anul ? `<i class="ti ti-camera-off cj-sinfoto" title="Falta la foto de la factura"></i>` : "")}
      ${m.cierre_id ? `<i class="ti ti-lock" title="Día cerrado"></i>` : ""}
    </td>
  </tr>`;
}

function cjRango(k) {
  cj.rango = k;
  if (k === "otro" && !cj.desde) { [cj.desde, cj.hasta] = [cj.meta.hoy.slice(0, 8) + "01", cj.meta.hoy]; }
  cjCargarMovs();
}

// ─── Cargar / corregir un movimiento ────────────────────────────────────
function cjConceptos(tipo) { return (cj.meta.conceptos || []).filter(k => k.tipo === tipo && k.activo); }

function cjNuevo(tipo, base) {
  const ed = base && base.id ? base : null;
  const x = base || { tipo, fecha_oper: cj.meta.hoy, fecha_emision: cj.meta.hoy, doc_tipo: tipo === "egreso" ? "factura" : "recibo", medio: "efectivo", moneda: "PYG", cotizacion: 1, condicion: "contado", imputa_iva: 1, imputa_ire: 1, imputa_irp: 0, no_imputa: 0, detalle: [] };
  tipo = x.tipo;
  cj.form = { tipo, id: ed ? ed.id : 0, lineas: (x.detalle || []).map(l => ({ ...l })), archivos: [], quitar: [] };
  if (!cj.form.lineas.length) cj.form.lineas.push({ concepto_id: 0, concepto: "", detalle: "", tipo_iva: "10", total: "" });
  const ing = tipo === "ingreso";
  const o = rvModal({
    titulo: ed ? `Corregir movimiento N° ${ed.numero}` : (ing ? "Nuevo ingreso" : "Nuevo egreso"),
    icono: ing ? "arrow-down-left" : "arrow-up-right", ancho: 1040, clase: `cj-modal cj-${tipo}`,
    sub: `${cjEsc(cj.caja.nombre)} · ${ing ? "crédito: entra plata a la caja" : "débito: sale plata de la caja"}`,
    cuerpo: `
      <div class="cj-form">
        <div class="cj-col">
          <fieldset class="cj-bloque">
            <legend><i class="ti ti-user"></i> ${ing ? "De quién" : "A quién se le pagó"}</legend>
            <div class="cj-g cj-g-2">
              <label class="cj-f cj-ac-wrap"><span>${ing ? "Cliente / de quién" : "Proveedor"}</span>
                <input id="cj-cp" value="${cjEsc(x.contraparte || "")}" autocomplete="off" placeholder="Escribí el nombre o el RUC">
                <div class="cj-ac" id="cj-ac" hidden></div></label>
              <label class="cj-f"><span>RUC / CI <em id="cj-ruc-ok"></em></span>
                <input id="cj-ruc" value="${cjEsc(x.ruc || "")}" inputmode="numeric" placeholder="80012345-6"></label>
            </div>
            <details class="cj-mas" ${x.telefono || x.direccion ? "open" : ""}><summary>Teléfono y dirección</summary>
              <div class="cj-g cj-g-2">
                <label class="cj-f"><span>Teléfono</span><input id="cj-tel" value="${cjEsc(x.telefono || "")}"></label>
                <label class="cj-f"><span>Dirección</span><input id="cj-dir" value="${cjEsc(x.direccion || "")}"></label>
              </div></details>
          </fieldset>

          <fieldset class="cj-bloque">
            <legend><i class="ti ti-file-invoice"></i> Comprobante</legend>
            <div class="cj-g cj-g-3">
              <label class="cj-f"><span>Tipo</span><select id="cj-doc">${cjOpts(cj.meta.docs, x.doc_tipo)}</select></label>
              <label class="cj-f cj-timb"><span>Número</span><input id="cj-docn" value="${cjEsc(x.doc_numero || "")}" placeholder="001-001-0000123"></label>
              <label class="cj-f"><span>Fecha de la factura</span><input type="date" id="cj-fe" value="${x.fecha_emision || ""}"></label>
              <label class="cj-f cj-timb"><span>Timbrado</span><input id="cj-timb" value="${cjEsc(x.timbrado || "")}" inputmode="numeric" maxlength="8" placeholder="8 números"></label>
              <label class="cj-f cj-timb"><span>Vence el timbrado</span><input type="date" id="cj-tv" value="${x.timbrado_vence || ""}"></label>
              <label class="cj-f"><span>Condición</span><select id="cj-cond">${cjOpts(cj.meta.condiciones, x.condicion)}</select></label>
            </div>
          </fieldset>

          <fieldset class="cj-bloque">
            <legend><i class="ti ti-list-details"></i> Qué se ${ing ? "cobró" : "pagó"} <small>poné el total de cada renglón con IVA incluido: el sistema lo separa</small></legend>
            <div class="cj-lineas" id="cj-lineas"></div>
            <button type="button" class="cj-link" onclick="cjLineaMas()"><i class="ti ti-plus"></i> Otro renglón</button>
          </fieldset>
        </div>

        <div class="cj-col cj-col-der">
          <div class="cj-totales" id="cj-totales"></div>
          <fieldset class="cj-bloque">
            <legend><i class="ti ti-wallet"></i> Pago</legend>
            <div class="cj-g cj-g-2">
              <label class="cj-f"><span>Fecha de la operación</span><input type="date" id="cj-fo" value="${x.fecha_oper || cj.meta.hoy}"></label>
              <label class="cj-f"><span>Medio</span><select id="cj-medio">${cjOpts(cj.meta.medios, x.medio)}</select></label>
              <label class="cj-f cj-medio-det" hidden><span id="cj-md-t">Detalle</span><input id="cj-md" value="${cjEsc(x.medio_detalle || "")}"></label>
              <label class="cj-f"><span>Moneda</span><select id="cj-mon">${cjOpts(cj.meta.monedas, x.moneda)}</select></label>
              <label class="cj-f cj-cot" hidden><span>Cotización (Gs.)</span><input id="cj-cot" inputmode="decimal" value="${x.cotizacion && x.cotizacion !== 1 ? x.cotizacion : ""}"></label>
              <label class="cj-f"><span>Empleado <small>si es un vale o viático</small></span><input id="cj-emp" value="${cjEsc(x.empleado || "")}"></label>
            </div>
          </fieldset>
          <fieldset class="cj-bloque">
            <legend><i class="ti ti-camera"></i> Foto de la factura</legend>
            <div class="cj-drop" id="cj-drop">
              <input type="file" id="cj-file" accept="image/*,application/pdf" multiple hidden>
              <button type="button" class="btn btn-ghost btn-sm" onclick="document.getElementById('cj-file').click()"><i class="ti ti-upload"></i> Elegir o sacar foto</button>
              <span>o arrastrala acá · PDF también</span>
            </div>
            <div class="cj-thumbs" id="cj-thumbs"></div>
          </fieldset>
          <label class="cj-f"><span>Observación</span><textarea id="cj-obs" rows="3" placeholder="Para qué fue, quién lo pidió, a qué coche…">${cjEsc(x.observacion || "")}</textarea></label>
          <details class="cj-mas cj-rg90"><summary>Para el contador (RG 90)</summary>
            <div class="cj-checks">
              <label><input type="checkbox" id="cj-iiva" ${x.imputa_iva ? "checked" : ""}> Imputa IVA</label>
              <label><input type="checkbox" id="cj-iire" ${x.imputa_ire ? "checked" : ""}> Imputa IRE</label>
              <label><input type="checkbox" id="cj-iirp" ${x.imputa_irp ? "checked" : ""}> Imputa IRP-RSP</label>
              <label><input type="checkbox" id="cj-noimp" ${x.no_imputa ? "checked" : ""}> No imputa</label>
            </div></details>
          <div class="cj-avisos" id="cj-avisos"></div>
        </div>
      </div>`,
    pie: `<div class="cj-pie">
        <span class="cj-ayuda">Ctrl + Enter guarda</span>
        <button type="button" class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancelar</button>
        ${ed ? "" : `<button type="button" class="btn btn-ghost" onclick="cjGuardar(this, true)"><i class="ti ti-copy-plus"></i> Guardar y cargar otro</button>`}
        <button type="button" class="btn ${ing ? "cj-btn-ing" : "cj-btn-egr"}" onclick="cjGuardar(this)"><i class="ti ti-check"></i> ${ed ? "Guardar cambios" : "Guardar"}</button>
      </div>`,
  });
  cj.modal = o;
  cjPintarLineas();
  const $ = s => o.querySelector(s);
  const docCambio = () => {
    const con = cj.meta.docs_timbrado.includes($("#cj-doc").value);
    o.querySelectorAll(".cj-timb").forEach(e => e.classList.toggle("off", !con));
    if ($("#cj-doc").value === "interno") $("#cj-docn").placeholder = "Opcional"; else $("#cj-docn").placeholder = "001-001-0000123";
    cjAvisos();
  };
  const medioCambio = () => {
    const m = $("#cj-medio").value;
    const t = { cheque: "Banco y N° de cheque", transferencia: "Banco / N° de operación", tarjeta: "Últimos 4 / lote", vale: "A quién" }[m];
    $(".cj-medio-det").hidden = !t;
    if (t) $("#cj-md-t").textContent = t;
  };
  const monCambio = () => { $(".cj-cot").hidden = $("#cj-mon").value === "PYG"; cjPintarTotales(); };
  $("#cj-doc").onchange = docCambio;
  $("#cj-medio").onchange = medioCambio;
  $("#cj-mon").onchange = monCambio;
  $("#cj-cot").oninput = cjPintarTotales;
  docCambio(); medioCambio(); monCambio();
  // RUC: el dígito verificador al toque
  const ruc = $("#cj-ruc");
  const rucCheck = () => {
    const s = ruc.value.replace(/[.\s]/g, "").toUpperCase(), ok = $("#cj-ruc-ok");
    const m = s.match(/^(\d{3,9})-?(\d)$/);
    if (!s) { ok.className = ""; ok.textContent = ""; return; }
    if (m && cjRucDv(m[1]) === +m[2]) { ok.className = "ok"; ok.innerHTML = `<i class="ti ti-circle-check"></i> válido`; }
    else if (/^\d{3,9}$/.test(s)) { ok.className = "ojo"; ok.innerHTML = `sin dígito: DV ${cjRucDv(s)}`; }
    else { ok.className = "mal"; ok.innerHTML = `<i class="ti ti-alert-circle"></i> ${m ? "DV debería ser " + cjRucDv(m[1]) : "revisar"}`; }
  };
  ruc.oninput = () => { rucCheck(); cjAvisosLuego(); };
  ruc.onblur = () => { const m = ruc.value.replace(/[.\s]/g, "").match(/^(\d{3,9})-?(\d)$/); if (m) ruc.value = `${m[1]}-${m[2]}`; };
  rucCheck();
  // Número de factura: 1-1-123 → 001-001-0000123
  $("#cj-docn").onblur = e => {
    const v = e.target.value.trim(), m = v.match(/^(\d{1,3})-(\d{1,3})-(\d{1,7})$/), d = v.replace(/\D/g, "");
    if (m) e.target.value = `${m[1].padStart(3, "0")}-${m[2].padStart(3, "0")}-${m[3].padStart(7, "0")}`;
    else if (d.length === 13) e.target.value = `${d.slice(0, 3)}-${d.slice(3, 6)}-${d.slice(6)}`;
    cjAvisos();
  };
  ["#cj-timb", "#cj-tv", "#cj-fe", "#cj-fo"].forEach(s => $(s).addEventListener("change", cjAvisos));
  $("#cj-noimp").onchange = e => { if (e.target.checked) ["#cj-iiva", "#cj-iire", "#cj-iirp"].forEach(s => $(s).checked = false); };
  ["#cj-iiva", "#cj-iire", "#cj-iirp"].forEach(s => $(s).addEventListener("change", e => { if (e.target.checked) $("#cj-noimp").checked = false; }));
  cjAutocompletar($("#cj-cp"));
  // Archivos
  const file = $("#cj-file"), drop = $("#cj-drop");
  file.onchange = () => { cjSumarArchivos(file.files); file.value = ""; };
  drop.ondragover = e => { e.preventDefault(); drop.classList.add("sobre"); };
  drop.ondragleave = () => drop.classList.remove("sobre");
  drop.ondrop = e => { e.preventDefault(); drop.classList.remove("sobre"); cjSumarArchivos(e.dataTransfer.files); };
  o.addEventListener("paste", e => { const fs = [...(e.clipboardData?.files || [])]; if (fs.length) cjSumarArchivos(fs); });
  if (ed) cj.form.existentes = (base.archivos || []).map(a => ({ ...a }));
  cjPintarThumbs();
  o.addEventListener("keydown", e => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); cjGuardar(o.querySelector(".cj-pie .btn:last-child")); } });
  setTimeout(() => (ed ? o.querySelector(".cj-lin-tot") : $("#cj-cp")).focus(), 60);
  cjAvisos();
}

function cjPintarLineas() {
  const box = cj.modal && cj.modal.querySelector("#cj-lineas");
  if (!box) return;
  const conc = cjConceptos(cj.form.tipo);
  box.innerHTML = cj.form.lineas.map((l, i) => `
    <div class="cj-lin" data-i="${i}">
      <label class="cj-f cj-lin-c"><span>Concepto</span>
        <select onchange="cjLineaConcepto(${i}, this)">
          <option value="">Elegí…</option>
          ${conc.map(k => `<option value="${k.id}" ${+l.concepto_id === k.id || (!l.concepto_id && l.concepto === k.nombre) ? "selected" : ""}>${cjEsc(k.nombre)}</option>`).join("")}
          ${l.concepto && !conc.some(k => +l.concepto_id === k.id || k.nombre === l.concepto) ? `<option value="x" selected>${cjEsc(l.concepto)}</option>` : ""}
          <option value="nuevo">+ Nuevo concepto…</option>
        </select></label>
      <label class="cj-f cj-lin-d"><span>Detalle</span><input value="${cjEsc(l.detalle || "")}" placeholder="Ej: 2 filtros de aceite, coche 26800" oninput="cj.form.lineas[${i}].detalle=this.value"></label>
      <label class="cj-f cj-lin-i"><span>IVA</span><select onchange="cj.form.lineas[${i}].tipo_iva=this.value;cjPintarTotales()">${cjOpts({ "10": "10 %", "5": "5 %", exento: "Exenta" }, String(l.tipo_iva))}</select></label>
      <label class="cj-f cj-lin-t"><span>Total con IVA</span><input class="cj-lin-tot" inputmode="decimal" value="${l.total ? cjMilDec(l.total) : ""}" placeholder="0"
        oninput="cj.form.lineas[${i}].total=cjNum(this.value);cjPintarTotales()" onblur="this.value=cj.form.lineas[${i}].total?cjMilDec(cj.form.lineas[${i}].total):''"></label>
      <span class="cj-lin-iva" id="cj-li-${i}"></span>
      ${cj.form.lineas.length > 1 ? `<button type="button" class="icon-btn cj-lin-x" title="Quitar renglón" aria-label="Quitar renglón" onclick="cjLineaMenos(${i})"><i class="ti ti-x"></i></button>` : `<span></span>`}
    </div>`).join("");
  cjPintarTotales();
}
function cjMilDec(v) { const n = +v || 0; return Number.isInteger(n) ? cjMil(n) : n.toLocaleString("es-PY", { maximumFractionDigits: 2 }); }
function cjLineaMas() { cj.form.lineas.push({ concepto_id: 0, concepto: "", detalle: "", tipo_iva: cj.form.lineas.at(-1)?.tipo_iva || "10", total: "" }); cjPintarLineas(); cj.modal.querySelectorAll(".cj-lin-c select").forEach((s, i, a) => i === a.length - 1 && s.focus()); }
function cjLineaMenos(i) { cj.form.lineas.splice(i, 1); cjPintarLineas(); }
async function cjLineaConcepto(i, sel) {
  const l = cj.form.lineas[i];
  if (sel.value === "nuevo") {
    const nombre = prompt("Nombre del concepto nuevo (ej: Repuestos eléctricos):");
    if (!nombre || !nombre.trim()) { sel.value = l.concepto_id || ""; return; }
    const r = await cjJson("/api/cajas/conceptos", "POST", { nombre, tipo: cj.form.tipo, iva: l.tipo_iva || "10" });
    if (!r || !r.ok) { toast((r && r.msg) || "No se pudo crear", "error"); sel.value = ""; return; }
    const m = await api("/api/cajas").catch(() => null);
    if (m && m.ok) cj.meta.conceptos = m.conceptos;
    l.concepto_id = r.id; l.concepto = nombre.trim();
    cjPintarLineas();
    return;
  }
  if (sel.value === "x") return;
  const k = cj.meta.conceptos.find(k => k.id === +sel.value);
  l.concepto_id = k ? k.id : 0;
  l.concepto = k ? k.nombre : "";
  if (k) { l.tipo_iva = k.iva; sel.closest(".cj-lin").querySelector(".cj-lin-i select").value = k.iva; }
  cjPintarTotales();
  sel.closest(".cj-lin").querySelector(".cj-lin-d input").focus();
}

function cjPintarTotales() {
  const o = cj.modal;
  if (!o) return;
  const mon = o.querySelector("#cj-mon")?.value || "PYG", dec = mon === "PYG" ? 0 : 2;
  const t = { exento: 0, grav5: 0, grav10: 0, iva5: 0, iva10: 0, total: 0 };
  cj.form.lineas.forEach((l, i) => {
    const s = cjSepararIva(+l.total || 0, String(l.tipo_iva), dec);
    Object.keys(s).forEach(k => t[k] += s[k]);
    t.total += +l.total || 0;
    const e = o.querySelector(`#cj-li-${i}`);
    if (e) e.textContent = l.total ? (l.tipo_iva === "exento" ? "exenta" : `IVA ${cjMilDec(s.iva10 + s.iva5)}`) : "";
  });
  const cot = mon === "PYG" ? 1 : cjNum(o.querySelector("#cj-cot")?.value);
  const sim = mon === "PYG" ? "Gs." : mon;
  const box = o.querySelector("#cj-totales");
  box.innerHTML = `
    <div class="cj-tot-g">
      <span>Exento</span><b>${cjMilDec(t.exento)}</b>
      <span>Gravado 5 %</span><b>${cjMilDec(t.grav5)}</b>
      <span>Gravado 10 %</span><b>${cjMilDec(t.grav10)}</b>
      <span>IVA 5 %</span><b>${cjMilDec(t.iva5)}</b>
      <span>IVA 10 %</span><b>${cjMilDec(t.iva10)}</b>
    </div>
    <div class="cj-tot-big"><span>Total</span><b>${sim} ${cjMilDec(t.total)}</b>
      ${mon !== "PYG" ? `<small>${cot ? "= " + cjGs(t.total * cot) : "poné la cotización"}</small>` : ""}</div>`;
}

// Autocompletar proveedor (como el «Hist» de Walrus, pero mientras escribís)
function cjAutocompletar(inp) {
  const lista = cj.modal.querySelector("#cj-ac");
  let items = [], idx = -1, t;
  const cerrar = () => { lista.hidden = true; idx = -1; };
  const elegir = p => {
    const $ = s => cj.modal.querySelector(s);
    inp.value = p.contraparte;
    if (p.ruc) $("#cj-ruc").value = p.ruc;
    if (p.telefono) $("#cj-tel").value = p.telefono;
    if (p.direccion) $("#cj-dir").value = p.direccion;
    if (p.timbrado && !$("#cj-timb").value) $("#cj-timb").value = p.timbrado;
    if (p.timbrado_vence && !$("#cj-tv").value) $("#cj-tv").value = p.timbrado_vence;
    const l0 = cj.form.lineas[0];
    if (p.concepto && cj.form.lineas.length === 1 && !l0.concepto && !l0.total) {
      Object.assign(l0, { concepto_id: p.concepto.concepto_id, concepto: p.concepto.concepto, tipo_iva: p.concepto.tipo_iva });
      cjPintarLineas();
    }
    $("#cj-ruc").dispatchEvent(new Event("input"));
    cerrar();
    $("#cj-docn").focus();
  };
  const pintar = () => {
    lista.innerHTML = items.map((p, i) => `<button type="button" class="${i === idx ? "on" : ""}" data-i="${i}">
      <b>${cjEsc(p.contraparte)}</b><span>${cjEsc(p.ruc || "sin RUC")}${p.veces ? ` · ${p.veces} vez${p.veces === 1 ? "" : "es"}, último ${cjDm(p.ultimo)} (${cjGs(p.ultimo_total)})` : p.de_proveedores ? " · de Proveedores" : ""}</span></button>`).join("");
    lista.hidden = !items.length;
    lista.querySelectorAll("button").forEach(b => b.onmousedown = e => { e.preventDefault(); elegir(items[+b.dataset.i]); });
  };
  inp.addEventListener("input", () => {
    clearTimeout(t);
    const q = inp.value.trim();
    if (q.length < 2) { items = []; pintar(); return; }
    t = setTimeout(async () => {
      const r = await api(`/api/cajas/contrapartes?q=${encodeURIComponent(q)}`).catch(() => null);
      items = (r && r.lista) || []; idx = -1; pintar();
    }, 200);
  });
  inp.addEventListener("keydown", e => {
    if (lista.hidden) return;
    if (e.key === "ArrowDown") { e.preventDefault(); idx = Math.min(items.length - 1, idx + 1); pintar(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); idx = Math.max(0, idx - 1); pintar(); }
    else if (e.key === "Enter" && idx >= 0) { e.preventDefault(); elegir(items[idx]); }
    else if (e.key === "Escape") { e.stopPropagation(); cerrar(); }
  });
  inp.addEventListener("blur", () => setTimeout(cerrar, 150));
}

function cjAvisosLuego() { clearTimeout(cj._at); cj._at = setTimeout(cjAvisos, 450); }
async function cjAvisos() {
  const o = cj.modal;
  if (!o || !document.body.contains(o)) return;
  const v = s => o.querySelector(s)?.value || "";
  const r = await cjJson("/api/cajas/avisos", "POST", {
    id: cj.form.id, tipo: cj.form.tipo, ruc: v("#cj-ruc"), doc_tipo: v("#cj-doc"), doc_numero: v("#cj-docn"),
    timbrado: v("#cj-timb"), timbrado_vence: v("#cj-tv"), fecha_emision: v("#cj-fe"), fecha_oper: v("#cj-fo"),
  });
  const box = o.querySelector("#cj-avisos");
  if (!box || !r || !r.ok) return;
  box.innerHTML = r.avisos.map(a => `<div class="cj-aviso ${a.nivel}"><i class="ti ti-${a.nivel === "mal" ? "alert-triangle" : "info-circle"}"></i>
    <span>${cjEsc(a.msg)}${a.mov_id ? ` <button type="button" class="cj-link" onclick="cjVer(${a.mov_id})">Ver</button>` : ""}</span></div>`).join("");
}

// Archivos: las fotos se achican antes de subir (llegan rápido aunque sea por datos)
async function cjSumarArchivos(lista) {
  for (const f of [...lista]) {
    if (!f.type.startsWith("image/") && f.type !== "application/pdf") { toast(`${f.name}: subí una foto o un PDF`, "error"); continue; }
    const datos = f.type.startsWith("image/") ? await cjAchicar(f) : await cjLeer(f);
    if (!datos) { toast(`${f.name}: no se pudo leer`, "error"); continue; }
    cj.form.archivos.push({ nombre: f.name, tipo: f.type.startsWith("image/") ? "image/jpeg" : f.type, datos });
  }
  cjPintarThumbs();
}
function cjLeer(f) { return new Promise(res => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = () => res(null); r.readAsDataURL(f); }); }
async function cjAchicar(f) {
  const url = await cjLeer(f);
  if (!url) return null;
  return new Promise(res => {
    const img = new Image();
    img.onload = () => {
      const max = 1800, k = Math.min(1, max / Math.max(img.width, img.height));
      const cv = document.createElement("canvas");
      cv.width = Math.round(img.width * k); cv.height = Math.round(img.height * k);
      cv.getContext("2d").drawImage(img, 0, 0, cv.width, cv.height);
      res(cv.toDataURL("image/jpeg", 0.82));
    };
    img.onerror = () => res(url);
    img.src = url;
  });
}
function cjPintarThumbs() {
  const box = cj.modal && cj.modal.querySelector("#cj-thumbs");
  if (!box) return;
  const ya = (cj.form.existentes || []).filter(a => !cj.form.quitar.includes(a.id));
  box.innerHTML = ya.map(a => `<div class="cj-th">${a.tipo.startsWith("image/") ? `<img src="/api/cajas/archivos/${a.id}" alt="">` : `<i class="ti ti-file-type-pdf"></i>`}
      <button type="button" title="Quitar" aria-label="Quitar" onclick="cj.form.quitar.push(${a.id});cjPintarThumbs()"><i class="ti ti-x"></i></button></div>`).join("")
    + cj.form.archivos.map((a, i) => `<div class="cj-th nuevo">${a.tipo.startsWith("image/") ? `<img src="${a.datos}" alt="">` : `<i class="ti ti-file-type-pdf"></i>`}
      <button type="button" title="Quitar" aria-label="Quitar" onclick="cj.form.archivos.splice(${i},1);cjPintarThumbs()"><i class="ti ti-x"></i></button></div>`).join("");
}

async function cjGuardar(btn, otro, confirmar) {
  const o = cj.modal;
  const v = s => o.querySelector(s)?.value || "";
  const ch = s => !!o.querySelector(s)?.checked;
  const cuerpo = {
    tipo: cj.form.tipo, contraparte: v("#cj-cp"), ruc: v("#cj-ruc"), telefono: v("#cj-tel"), direccion: v("#cj-dir"),
    doc_tipo: v("#cj-doc"), doc_numero: v("#cj-docn"), fecha_emision: v("#cj-fe"), timbrado: v("#cj-timb"), timbrado_vence: v("#cj-tv"),
    condicion: v("#cj-cond"), fecha_oper: v("#cj-fo"), medio: v("#cj-medio"), medio_detalle: v("#cj-md"),
    moneda: v("#cj-mon"), cotizacion: v("#cj-cot"), empleado: v("#cj-emp"), observacion: v("#cj-obs"),
    imputa_iva: ch("#cj-iiva"), imputa_ire: ch("#cj-iire"), imputa_irp: ch("#cj-iirp"), no_imputa: ch("#cj-noimp"),
    detalle: cj.form.lineas.map(l => ({ concepto_id: l.concepto_id, concepto: l.concepto, detalle: l.detalle, tipo_iva: l.tipo_iva, total: l.total })),
    confirmar: !!confirmar,
  };
  const botones = o.querySelectorAll(".cj-pie .btn");
  botones.forEach(b => b.disabled = true);
  const r = cj.form.id
    ? await cjJson(`/api/cajas/movs/${cj.form.id}`, "PUT", cuerpo)
    : await cjJson(`/api/cajas/${cj.caja.id}/movs`, "POST", cuerpo);
  if (r && r.duplicado) {
    botones.forEach(b => b.disabled = false);
    if (confirm(r.msg + "\n\n¿Lo guardo igual?")) return cjGuardar(btn, otro, true);
    return;
  }
  if (!r || !r.ok) { botones.forEach(b => b.disabled = false); toast((r && r.msg) || "No se pudo guardar", "error"); return; }
  const mid = r.id;
  let fallos = 0;
  for (const a of cj.form.archivos) {
    const x = await cjJson(`/api/cajas/movs/${mid}/archivos`, "POST", a);
    if (!x || !x.ok) fallos++;
  }
  for (const aid of cj.form.quitar) await cjJson(`/api/cajas/archivos/${aid}`, "DELETE");
  toast(r.msg + (fallos ? ` · ${fallos} archivo(s) no se pudieron subir` : ""), fallos ? "error" : "success");
  o.remove();
  await cjRefrescarCajas();
  await cjCargarMovs();
  if (otro) cjNuevo(cj.form.tipo);
}

// ─── Ver un movimiento ──────────────────────────────────────────────────
async function cjVer(mid) {
  const r = await api(`/api/cajas/movs/${mid}`).catch(() => null);
  if (!r || !r.ok) { toast("No se pudo abrir", "error"); return; }
  const m = r.mov, ing = m.tipo === "ingreso", anul = m.estado !== "vigente";
  const puedeEd = cjPuede() && !anul && !m.cierre_id;
  const fila = (t, v) => v ? `<div class="cj-dato"><span>${t}</span><b>${v}</b></div>` : "";
  const o = rvModal({
    titulo: `${ing ? "Ingreso" : "Egreso"} N° ${m.numero}`, icono: ing ? "arrow-down-left" : "arrow-up-right", ancho: 860,
    clase: `cj-modal cj-ver cj-${m.tipo}`,
    sub: `${cjEsc(m.caja_nombre)} · ${cjDmy(m.fecha_oper)} · cargó ${cjEsc(m.creado_por)}${m.cierre_id ? " · <i class='ti ti-lock'></i> día cerrado" : ""}`,
    cuerpo: `
      ${anul ? `<div class="cj-aviso mal"><i class="ti ti-ban"></i><span><b>Anulado</b> por ${cjEsc(m.anulado_por)} el ${cjDmy(m.anulado_el)}: ${cjEsc(m.anulado_motivo)}</span></div>` : ""}
      ${(m.avisos || []).map(a => `<div class="cj-aviso ${a.nivel}"><i class="ti ti-info-circle"></i><span>${cjEsc(a.msg)}</span></div>`).join("")}
      ${m.transf ? `<div class="cj-aviso info"><i class="ti ti-arrows-exchange"></i><span>Transferencia: la otra punta es el ${m.transf.tipo} N° ${m.transf.numero} de ${cjEsc(m.transf.caja)}</span></div>` : ""}
      <div class="cj-ver-g">
        <div class="cj-ver-datos">
          ${fila(ing ? "De quién" : "Proveedor", cjEsc(m.contraparte))}
          ${fila("RUC / CI", cjEsc(m.ruc))}
          ${fila("Comprobante", cjEsc((cj.meta.docs[m.doc_tipo] || "") + " " + (m.doc_numero || "")))}
          ${fila("Timbrado", cjEsc(m.timbrado) + (m.timbrado_vence ? ` <small>vence ${cjDmy(m.timbrado_vence)}</small>` : ""))}
          ${fila("Fecha de la factura", cjDmy(m.fecha_emision))}
          ${fila("Medio", cjEsc(cj.meta.medios[m.medio] || m.medio) + (m.medio_detalle ? ` · ${cjEsc(m.medio_detalle)}` : ""))}
          ${fila("Condición", cjEsc(cj.meta.condiciones[m.condicion] || ""))}
          ${m.moneda !== "PYG" ? fila("Moneda", `${m.moneda} · cotización ${cjMilDec(m.cotizacion)}`) : ""}
          ${fila("Empleado", cjEsc(m.empleado))}
          ${fila("Teléfono", cjEsc(m.telefono))}
          ${fila("Dirección", cjEsc(m.direccion))}
        </div>
        <div class="cj-ver-tot">
          <span>Total</span><b>${m.moneda === "PYG" ? "Gs." : m.moneda} ${cjMilDec(m.total)}</b>
          ${m.moneda !== "PYG" ? `<small>= ${cjGs(m.total_gs)}</small>` : ""}
          <div class="cj-tot-g">
            <span>Exento</span><b>${cjMilDec(m.exento)}</b><span>Grav. 5 %</span><b>${cjMilDec(m.grav5)}</b>
            <span>Grav. 10 %</span><b>${cjMilDec(m.grav10)}</b><span>IVA</span><b>${cjMilDec(m.iva5 + m.iva10)}</b>
          </div>
        </div>
      </div>
      <table class="cj-det"><thead><tr><th>Concepto</th><th>IVA</th><th class="num">Total</th></tr></thead>
        <tbody>${m.detalle.map(l => `<tr><td><b>${cjEsc(l.concepto)}</b>${l.detalle ? `<small>${cjEsc(l.detalle)}</small>` : ""}</td>
          <td>${{ "10": "10 %", "5": "5 %" }[l.tipo_iva] || "Exenta"}</td><td class="num">${cjMilDec(l.total)}</td></tr>`).join("")}</tbody></table>
      ${m.observacion ? `<div class="cj-obs-v">${cjEsc(m.observacion)}</div>` : ""}
      <div class="cj-ver-arch">
        ${m.archivos.length ? m.archivos.map(a => `<a class="cj-th grande" href="/api/cajas/archivos/${a.id}" target="_blank" rel="noopener" title="${cjEsc(a.nombre)}">
            ${a.tipo.startsWith("image/") ? `<img src="/api/cajas/archivos/${a.id}" alt="${cjEsc(a.nombre)}" loading="lazy">` : `<i class="ti ti-file-type-pdf"></i><small>${cjEsc(a.nombre)}</small>`}</a>`).join("")
          : `<span class="cj-sin-arch"><i class="ti ti-camera-off"></i> Sin foto del comprobante</span>`}
        ${cjPuede() && !anul ? `<label class="cj-th mas" title="Agregar foto o PDF"><input type="file" accept="image/*,application/pdf" multiple hidden onchange="cjAgregarArchivo(${m.id}, this)"><i class="ti ti-camera-plus"></i><small>Agregar</small></label>` : ""}
      </div>`,
    pie: `<div class="cj-pie">
      ${cjPuede() && !anul && !m.cierre_id ? `<button type="button" class="pv-link cj-anular" onclick="cjAnular(${m.id})"><i class="ti ti-ban"></i> Anular</button>` : ""}
      <button type="button" class="btn btn-ghost" onclick="window.open('/api/cajas/movs/${m.id}/pdf','_blank')"><i class="ti ti-printer"></i> Imprimir</button>
      ${puedeEd && !m.transf_id ? `<button type="button" class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove();cjEditar(${m.id})"><i class="ti ti-pencil"></i> Corregir</button>` : ""}
      <button type="button" class="btn btn-primary" onclick="this.closest('.modal-overlay').remove()">Listo</button>
    </div>`,
  });
  cj.verModal = o;
}
async function cjEditar(mid) {
  const r = await api(`/api/cajas/movs/${mid}`).catch(() => null);
  if (r && r.ok) cjNuevo(r.mov.tipo, r.mov);
}
async function cjAgregarArchivo(mid, inp) {
  for (const f of [...inp.files]) {
    const datos = f.type.startsWith("image/") ? await cjAchicar(f) : await cjLeer(f);
    const x = await cjJson(`/api/cajas/movs/${mid}/archivos`, "POST", { nombre: f.name, tipo: f.type.startsWith("image/") ? "image/jpeg" : f.type, datos });
    if (!x || !x.ok) toast((x && x.msg) || "No se pudo subir", "error");
  }
  inp.closest(".modal-overlay").remove();
  cjVer(mid);
  cjCargarMovs();
}
function cjAnular(mid) {
  const o = rvModal({
    titulo: "Anular movimiento", icono: "ban", ancho: 480, clase: "cj-modal",
    sub: "Queda en la lista tachado, con el motivo. La plata vuelve a la caja.",
    cuerpo: `<label class="cj-f"><span>¿Por qué se anula?</span><textarea id="cj-anul-m" rows="3" placeholder="Ej: se cargó dos veces"></textarea></label>`,
    pie: `<div class="cj-pie"><button type="button" class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancelar</button>
      <button type="button" class="btn btn-danger" id="cj-anul-ok"><i class="ti ti-ban"></i> Anular</button></div>`,
  });
  setTimeout(() => o.querySelector("#cj-anul-m").focus(), 60);
  o.querySelector("#cj-anul-ok").onclick = async () => {
    const r = await cjJson(`/api/cajas/movs/${mid}/anular`, "POST", { motivo: o.querySelector("#cj-anul-m").value });
    if (!r || !r.ok) { toast((r && r.msg) || "No se pudo anular", "error"); return; }
    toast(r.msg, "success");
    o.remove();
    cj.verModal?.remove();
    await cjRefrescarCajas();
    cjCargarMovs();
  };
}

// ─── Cierre del día con arqueo ──────────────────────────────────────────
async function cjCierre(fecha) {
  fecha = fecha || cj.meta.hoy;
  const p = await api(`/api/cajas/${cj.caja.id}/cierre?fecha=${fecha}`).catch(() => null);
  if (!p || !p.ok) { toast("No se pudo preparar el cierre", "error"); return; }
  document.querySelector(".cj-cierre-modal")?.closest(".modal-overlay")?.remove();
  const o = rvModal({
    titulo: `Cerrar ${cjEsc(cj.caja.nombre)}`, icono: "lock", ancho: 900, clase: "cj-modal cj-cierre-modal",
    sub: p.ultimo_cierre ? `Último cierre: ${cjDmy(p.ultimo_cierre)}. Entra todo lo cargado después, hasta la fecha que elijas.` : "Primer cierre de esta caja.",
    cuerpo: `
      <div class="cj-cie-top">
        <label class="cj-f"><span>Cerrar hasta el</span><input type="date" id="cj-cie-f" value="${p.fecha}" max="${cj.meta.hoy}" ${p.ultimo_cierre ? `min="${p.ultimo_cierre}"` : ""}></label>
        ${p.ya_cerrado ? `<div class="cj-aviso mal"><i class="ti ti-lock"></i><span>Ya hay un cierre posterior a esa fecha.</span></div>` : ""}
        ${p.sin_foto ? `<div class="cj-aviso ojo"><i class="ti ti-camera-off"></i><span>${p.sin_foto} movimiento${p.sin_foto === 1 ? "" : "s"} sin foto del comprobante. Se puede cerrar igual, pero conviene subirlas.</span></div>` : ""}
      </div>
      <div class="cj-cie-kpis">
        <div><span>Saldo anterior</span><b>${cjGs(p.saldo_anterior)}</b></div>
        <div class="ing"><span>Ingresos</span><b>+ ${cjMil(p.ingresos)}</b></div>
        <div class="egr"><span>Egresos</span><b>− ${cjMil(p.egresos)}</b></div>
        <div class="fin"><span>Saldo final</span><b>${cjGs(p.saldo_final)}</b></div>
      </div>
      <div class="cj-cie-g">
        <div class="cj-arqueo">
          <h4><i class="ti ti-coins"></i> Arqueo: contá el efectivo</h4>
          <div class="cj-billetes">
            ${cj.meta.billetes.map(b => `<label><span>${cjMil(b)}</span><input inputmode="numeric" data-b="${b}" placeholder="0" aria-label="Cantidad de ${cjMil(b)}"><em data-s="${b}"></em></label>`).join("")}
            <label class="otros"><span>Otros / monedas (Gs.)</span><input inputmode="numeric" id="cj-arq-otros" placeholder="0"></label>
          </div>
        </div>
        <div class="cj-cuadre">
          <div><span>Efectivo que dice el sistema</span><b>${cjGs(p.efectivo_final)}</b></div>
          <div><span>Contado</span><b id="cj-contado">Gs. 0</b></div>
          <div class="cj-dif" id="cj-dif"></div>
          ${p.por_medio.filter(x => x.medio !== "Efectivo").map(x => `<small>${cjEsc(x.medio)}: + ${cjMil(x.ingresos)} / − ${cjMil(x.egresos)} (no va al cajón)</small>`).join("")}
          <label class="cj-f"><span>Nota <small id="cj-nota-oblig"></small></span><textarea id="cj-cie-nota" rows="3" placeholder="Si no cuadra, qué pasó"></textarea></label>
        </div>
      </div>
      <details class="cj-mas" ${p.movs.length <= 8 ? "open" : ""}><summary>Los ${p.movs.length} movimientos que entran</summary>
        ${p.movs.length ? `<div class="cj-tabla-wrap"><table class="cj-tabla mini"><tbody>${p.movs.map(cjFila).join("")}</tbody></table></div>` : `<p class="cj-nada">No hay movimientos para cerrar: se puede cerrar igual para dejar asentado el arqueo.</p>`}
      </details>`,
    pie: `<div class="cj-pie"><span class="cj-ayuda">Después de cerrar, esos movimientos ya no se pueden cambiar</span>
      <button type="button" class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancelar</button>
      <button type="button" class="btn btn-primary" id="cj-cie-ok" ${p.ya_cerrado ? "disabled" : ""}><i class="ti ti-lock"></i> Cerrar y sacar el PDF</button></div>`,
  });
  o.querySelector("#cj-cie-f").onchange = e => { o.remove(); cjCierre(e.target.value); };
  const calc = () => {
    let c = 0;
    o.querySelectorAll("[data-b]").forEach(i => {
      const n = Math.max(0, Math.round(cjNum(i.value))), s = n * +i.dataset.b;
      c += s;
      o.querySelector(`[data-s="${i.dataset.b}"]`).textContent = n ? cjMil(s) : "";
    });
    c += Math.round(cjNum(o.querySelector("#cj-arq-otros").value));
    const dif = c - Math.round(p.efectivo_final);
    o.querySelector("#cj-contado").textContent = cjGs(c);
    const d = o.querySelector("#cj-dif");
    d.className = "cj-dif " + (dif === 0 ? "ok" : dif > 0 ? "mas" : "menos");
    d.innerHTML = dif === 0 ? `<i class="ti ti-circle-check"></i> Cuadra` : `<i class="ti ti-alert-triangle"></i> ${dif > 0 ? "Sobran" : "Faltan"} ${cjGs(Math.abs(dif))}`;
    o.querySelector("#cj-nota-oblig").textContent = dif ? "obligatoria: hay diferencia" : "";
    return { c, dif };
  };
  o.querySelectorAll(".cj-billetes input").forEach(i => i.addEventListener("input", calc));
  calc();
  setTimeout(() => o.querySelector("[data-b]").focus(), 60);
  o.querySelector("#cj-cie-ok").onclick = async e => {
    const billetes = {};
    o.querySelectorAll("[data-b]").forEach(i => { const n = Math.round(cjNum(i.value)); if (n > 0) billetes[i.dataset.b] = n; });
    const { dif } = calc();
    if (dif && !confirm(`El arqueo no cuadra: ${dif > 0 ? "sobran" : "faltan"} ${cjGs(Math.abs(dif))}. ¿Cerrar igual?`)) return;
    e.target.disabled = true;
    const r = await cjJson(`/api/cajas/${cj.caja.id}/cierre`, "POST", {
      fecha: o.querySelector("#cj-cie-f").value, nota: o.querySelector("#cj-cie-nota").value,
      arqueo: { billetes, otros: Math.round(cjNum(o.querySelector("#cj-arq-otros").value)) },
    });
    if (!r || !r.ok) { e.target.disabled = false; toast((r && r.msg) || "No se pudo cerrar", "error"); return; }
    toast(r.msg, r.diferencia ? "error" : "success");
    o.remove();
    window.open(`/api/cajas/cierres/${r.id}/pdf`, "_blank");
    await cjRefrescarCajas();
    cjCargarMovs();
  };
}

async function cjCierres() {
  const r = await api(`/api/cajas/${cj.caja.id}/cierres`).catch(() => null);
  if (!r || !r.ok) return;
  const o = rvModal({
    titulo: `Cierres de ${cjEsc(cj.caja.nombre)}`, icono: "history", ancho: 820, clase: "cj-modal",
    sub: "Cada cierre con su arqueo y el PDF para firmar.",
    cuerpo: r.cierres.length ? `<div class="cj-tabla-wrap"><table class="cj-tabla cj-cierres">
      <thead><tr><th>Fecha</th><th class="num">Movs.</th><th class="num">Ingresos</th><th class="num">Egresos</th><th class="num">Saldo final</th><th class="num">Arqueo</th><th>Cerró</th><th></th></tr></thead>
      <tbody>${r.cierres.map((c, i) => `<tr>
        <td><b>${cjDmy(c.fecha)}</b></td><td class="num">${c.movimientos}</td>
        <td class="num ing">${cjMil(c.ingresos)}</td><td class="num egr">${cjMil(c.egresos)}</td>
        <td class="num"><b>${cjMil(c.saldo_final)}</b></td>
        <td class="num ${c.diferencia ? (c.diferencia > 0 ? "ojo" : "egr") : "ok"}">${c.diferencia ? (c.diferencia > 0 ? "+" : "−") + cjMil(Math.abs(c.diferencia)) : "cuadra"}</td>
        <td>${cjEsc(c.cerrado_por)}<small>${(c.cerrado_el || "").slice(0, 16).replace("T", " ")}</small></td>
        <td class="cj-ic"><button type="button" class="icon-btn" title="PDF" aria-label="PDF del cierre" onclick="window.open('/api/cajas/cierres/${c.id}/pdf','_blank')"><i class="ti ti-printer"></i></button>
          ${i === 0 && cj.meta.admin ? `<button type="button" class="icon-btn" title="Reabrir" aria-label="Reabrir este cierre" onclick="cjReabrir(${c.id})"><i class="ti ti-lock-open"></i></button>` : ""}</td>
      </tr>`).join("")}</tbody></table></div>` : `<div class="empty"><i class="ti ti-lock-open"></i>Esta caja todavía no tiene cierres.</div>`,
    pie: `<div class="cj-pie"><button type="button" class="btn btn-primary" onclick="this.closest('.modal-overlay').remove()">Listo</button></div>`,
  });
  cj.cierresModal = o;
}
async function cjReabrir(cid) {
  if (!confirm("¿Reabrir este cierre? Los movimientos de ese período se van a poder corregir y hay que volver a cerrar.")) return;
  const r = await cjJson(`/api/cajas/cierres/${cid}/reabrir`, "POST");
  if (!r || !r.ok) { toast((r && r.msg) || "No se pudo", "error"); return; }
  toast(r.msg, "success");
  cj.cierresModal?.remove();
  await cjRefrescarCajas();
  cjCargarMovs();
}

function cjExtracto() {
  const [d, h] = cjRangoFechas();
  const desde = d || cj.meta.hoy.slice(0, 8) + "01", hasta = h || cj.meta.hoy;
  window.location.href = `/api/cajas/${cj.caja.id}/extracto.xlsx?desde=${desde}&hasta=${hasta}`;
}

// ─── Libro IVA ──────────────────────────────────────────────────────────
async function cjLibro() {
  const mesAct = cj.meta.hoy.slice(0, 7);
  const o = rvModal({
    titulo: "Libro IVA para el contador", icono: "book", ancho: 760, clase: "cj-modal",
    sub: "Las facturas del mes por fecha de emisión, con el IVA separado y las marcas de la RG 90. Sale en Excel.",
    cuerpo: `<div class="cj-g cj-g-3">
        <label class="cj-f"><span>Mes</span><input type="month" id="cj-lb-mes" value="${mesAct}" max="${mesAct}"></label>
        <label class="cj-f"><span>Libro</span><select id="cj-lb-tipo"><option value="compras">Compras (egresos)</option><option value="ventas">Ventas (ingresos)</option></select></label>
        <label class="cj-f"><span>Caja</span><select id="cj-lb-caja"><option value="">Todas</option>${cj.cajas.map(c => `<option value="${c.id}">${cjEsc(c.nombre)}</option>`).join("")}</select></label>
      </div><div id="cj-lb-prev" class="cj-lb-prev"></div>`,
    pie: `<div class="cj-pie"><button type="button" class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cerrar</button>
      <button type="button" class="btn btn-primary" id="cj-lb-ok"><i class="ti ti-file-spreadsheet"></i> Bajar Excel</button></div>`,
  });
  const qs = () => new URLSearchParams({ mes: o.querySelector("#cj-lb-mes").value, libro: o.querySelector("#cj-lb-tipo").value, caja: o.querySelector("#cj-lb-caja").value });
  const prev = async () => {
    const r = await api(`/api/cajas/libro?${qs()}`).catch(() => null);
    const box = o.querySelector("#cj-lb-prev");
    if (!r || !r.ok) { box.innerHTML = ""; return; }
    const t = r.totales;
    box.innerHTML = `<div class="cj-lb-n"><b>${r.filas.length}</b> comprobante${r.filas.length === 1 ? "" : "s"}</div>
      <div class="cj-tot-g ancho">
        <span>Exento</span><b>${cjMil(t.exento)}</b><span>Gravado 5 %</span><b>${cjMil(t.grav5)}</b><span>IVA 5 %</span><b>${cjMil(t.iva5)}</b>
        <span>Gravado 10 %</span><b>${cjMil(t.grav10)}</b><span>IVA 10 %</span><b>${cjMil(t.iva10)}</b><span>Total</span><b>${cjMil(t.total)}</b>
      </div>
      ${r.filas.filter(f => !f.timbrado || !f.ruc).length ? `<div class="cj-aviso ojo"><i class="ti ti-info-circle"></i><span>${r.filas.filter(f => !f.timbrado || !f.ruc).length} sin RUC o sin timbrado: el contador los va a pedir.</span></div>` : ""}`;
  };
  o.querySelectorAll("select, input").forEach(e => e.addEventListener("change", prev));
  o.querySelector("#cj-lb-ok").onclick = () => { window.location.href = `/api/cajas/libro.xlsx?${qs()}`; };
  prev();
}

// ─── Transferir entre cajas ─────────────────────────────────────────────
function cjTransferir() {
  const op = cj.cajas.map(c => `<option value="${c.id}">${cjEsc(c.nombre)} (${cjGs(c.saldo)})</option>`).join("");
  const o = rvModal({
    titulo: "Transferir entre cajas", icono: "arrows-exchange", ancho: 560, clase: "cj-modal",
    sub: "Sale de una y entra en la otra: quedan los dos movimientos enganchados.",
    cuerpo: `<div class="cj-g cj-g-2">
        <label class="cj-f"><span>Sale de</span><select id="cj-tr-o">${op}</select></label>
        <label class="cj-f"><span>Entra a</span><select id="cj-tr-d">${op}</select></label>
        <label class="cj-f"><span>Monto (Gs.)</span><input id="cj-tr-m" inputmode="numeric" placeholder="0"></label>
        <label class="cj-f"><span>Fecha</span><input type="date" id="cj-tr-f" value="${cj.meta.hoy}" max="${cj.meta.hoy}"></label>
        <label class="cj-f"><span>Medio</span><select id="cj-tr-me">${cjOpts(cj.meta.medios, "efectivo")}</select></label>
      </div>
      <label class="cj-f"><span>Nota</span><textarea id="cj-tr-n" rows="2" placeholder="Ej: reposición del fondo del taller"></textarea></label>`,
    pie: `<div class="cj-pie"><button type="button" class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancelar</button>
      <button type="button" class="btn btn-primary" id="cj-tr-ok"><i class="ti ti-check"></i> Transferir</button></div>`,
  });
  const so = o.querySelector("#cj-tr-o"), sd = o.querySelector("#cj-tr-d");
  so.value = cj.cajas.find(c => c.id !== cj.caja.id)?.id || so.value;
  sd.value = cj.caja.id;
  const m = o.querySelector("#cj-tr-m");
  m.onblur = () => { const n = Math.round(cjNum(m.value)); m.value = n ? cjMil(n) : ""; };
  o.querySelector("#cj-tr-ok").onclick = async e => {
    e.target.disabled = true;
    const r = await cjJson("/api/cajas/transferir", "POST", { origen: so.value, destino: sd.value, monto: cjNum(m.value), fecha: o.querySelector("#cj-tr-f").value, medio: o.querySelector("#cj-tr-me").value, nota: o.querySelector("#cj-tr-n").value });
    if (!r || !r.ok) { e.target.disabled = false; toast((r && r.msg) || "No se pudo", "error"); return; }
    toast(r.msg, "success");
    o.remove();
    await cjRefrescarCajas();
    cjCargarMovs();
  };
}

// ─── Ajustes: cajas y conceptos (administración) ───────────────────────
async function cjAjustes() {
  const r = await api("/api/cajas?todas=1").catch(() => null);
  if (!r || !r.ok) return;
  const o = rvModal({
    titulo: "Cajas y conceptos", icono: "settings", ancho: 900, clase: "cj-modal",
    sub: "Las cajas que se usan y la lista de conceptos para elegir al cargar.",
    cuerpo: `
      <h4 class="cj-h4">Cajas</h4>
      <div class="cj-aj-lista">${r.cajas.map(c => `<div class="cj-aj-fila ${c.activa ? "" : "off"}">
          <input value="${cjEsc(c.nombre)}" aria-label="Nombre" onchange="cjAjCaja(${c.id}, {nombre: this.value})">
          <input value="${cjEsc(c.responsable || "")}" placeholder="Responsable" aria-label="Responsable" onchange="cjAjCaja(${c.id}, {responsable: this.value})">
          <span class="cj-aj-saldo">${cjGs(c.saldo)}</span>
          <label class="cj-sw"><input type="checkbox" ${c.activa ? "checked" : ""} onchange="cjAjCaja(${c.id}, {activa: this.checked})"> Activa</label>
          <div class="cj-aj-banco">
            <select aria-label="Tipo" onchange="tsCuenta(${c.id}, {tipo: this.value})"><option value="caja" ${c.tipo !== "banco" ? "selected" : ""}>Caja (efectivo)</option><option value="banco" ${c.tipo === "banco" ? "selected" : ""}>Cuenta de banco</option></select>
            <input list="ts-bancos" value="${cjEsc(c.banco || "")}" placeholder="Banco" aria-label="Banco" onchange="tsCuenta(${c.id}, {banco: this.value})">
            <input value="${cjEsc(c.numero_cuenta || "")}" placeholder="N° de cuenta" aria-label="Número de cuenta" onchange="tsCuenta(${c.id}, {numero_cuenta: this.value})">
            <input inputmode="numeric" value="${c.saldo_minimo ? cjMil(c.saldo_minimo) : ""}" placeholder="Saldo mínimo (aviso)" aria-label="Saldo mínimo" onchange="tsCuenta(${c.id}, {saldo_minimo: this.value})">
          </div>
        </div>`).join("")}</div>
      <datalist id="ts-bancos">${((ts.res && ts.res.bancos) || []).map(b => `<option value="${cjEsc(b)}">`).join("")}</datalist>
      <h4 class="cj-h4">Aprobación de pagos</h4>
      <label class="cj-aj-umbral">Los pagos programados de <input inputmode="numeric" value="${cjMil((ts.res && ts.res.config && ts.res.config.umbral_aprobacion) || 5000000)}" onchange="tsUmbral(this.value)" aria-label="Monto desde el que se aprueba"> guaraníes o más necesitan que administración los apruebe antes de pagarse.</label>
      <div class="cj-aj-nueva">
        <input id="cj-nc-n" placeholder="Nombre de la caja nueva (ej: Caja chica Ciudad del Este)">
        <input id="cj-nc-s" inputmode="numeric" placeholder="Saldo con el que arranca (Gs.)">
        <button type="button" class="btn btn-ghost" onclick="cjAjNueva()"><i class="ti ti-plus"></i> Crear caja</button>
      </div>
      <h4 class="cj-h4">Conceptos</h4>
      <div class="cj-aj-conc">${["egreso", "ingreso"].map(t => `<div><h5>${t === "egreso" ? "Egresos" : "Ingresos"}</h5>
        ${r.conceptos.filter(k => k.tipo === t).map(k => `<div class="cj-aj-k ${k.activo ? "" : "off"}">
          <input value="${cjEsc(k.nombre)}" aria-label="Concepto" onchange="cjAjConc(${k.id}, {nombre: this.value})">
          <select aria-label="IVA" onchange="cjAjConc(${k.id}, {iva: this.value})">${cjOpts({ "10": "10 %", "5": "5 %", exento: "Exento" }, k.iva)}</select>
          <input value="${cjEsc(k.cuenta || "")}" placeholder="Cuenta" aria-label="Cuenta contable" onchange="cjAjConc(${k.id}, {cuenta: this.value})">
          <label class="cj-sw" title="Usar"><input type="checkbox" ${k.activo ? "checked" : ""} onchange="cjAjConc(${k.id}, {activo: this.checked})"></label>
        </div>`).join("")}</div>`).join("")}</div>`,
    pie: `<div class="cj-pie"><button type="button" class="btn btn-primary" onclick="this.closest('.modal-overlay').remove();renderCajas()">Listo</button></div>`,
  });
}
async function cjAjCaja(id, d) { const r = await cjJson(`/api/cajas/${id}`, "PATCH", d); toast((r && r.msg) || "No se pudo", r && r.ok ? "success" : "error"); }
async function cjAjConc(id, d) { const r = await cjJson(`/api/cajas/conceptos/${id}`, "PATCH", d); if (!r || !r.ok) toast((r && r.msg) || "No se pudo", "error"); }
async function cjAjNueva() {
  const n = document.getElementById("cj-nc-n").value, s = cjNum(document.getElementById("cj-nc-s").value);
  const r = await cjJson("/api/cajas", "POST", { nombre: n, saldo_inicial: s, efectivo_inicial: s });
  if (!r || !r.ok) { toast((r && r.msg) || "No se pudo", "error"); return; }
  toast(r.msg, "success");
  document.querySelector(".cj-modal")?.closest(".modal-overlay")?.remove();
  cjAjustes();
}

// ════════════════════════════════════════════════════════════════════════
//  TESORERÍA: flujo de caja, pagos y cobros, cheques y conciliación
// ════════════════════════════════════════════════════════════════════════
const ts = { res: null, semanas: 13, habitual: true, sel: null, prog: null, chSent: "recibido", chEst: "abiertos", chQ: "", conCaja: 0 };
async function tsJson(url, metodo = "POST", cuerpo) {
  return api(url, { method: metodo, headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo || {}) }).catch(() => null);
}
async function tsResumen() {
  const r = await api("/api/teso/resumen").catch(() => null);
  if (r && r.ok) { ts.res = r; cjPintarTabs(); }
  return r;
}
const tsGs = v => (v < 0 ? "−" : "") + cjGs(Math.abs(v));
const tsDm = f => f ? `${f.slice(8, 10)}/${f.slice(5, 7)}` : "";
const tsDia = f => { const d = new Date(f + "T12:00:00"); return ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"][d.getDay()] + " " + tsDm(f); };
function tsCajasOpts(sel, soloBanco) {
  return (cj.cajas || []).filter(c => !soloBanco || c.tipo === "banco").map(c => `<option value="${c.id}" ${+sel === c.id ? "selected" : ""}>${cjEsc(c.nombre)}${c.tipo === "banco" && c.banco ? " · " + cjEsc(c.banco) : ""}</option>`).join("");
}
async function tsCuenta(id, d) {
  const r = await tsJson(`/api/teso/cuenta/${id}`, "PATCH", d);
  toast((r && r.msg) || "No se pudo", r && r.ok ? "success" : "error");
}
async function tsUmbral(v) {
  const r = await tsJson("/api/teso/config", "POST", { umbral_aprobacion: v });
  if (r && r.ok) { ts.res.config = r.config; toast("Guardado", "success"); }
}

// ─── Flujo de caja ──────────────────────────────────────────────────────
async function tsFlujo() {
  const qs = new URLSearchParams({ semanas: ts.semanas, habitual: ts.habitual ? 1 : 0 });
  if (ts.sel && ts.sel.length) qs.set("cajas", ts.sel.join(","));
  const r = await api(`/api/teso/flujo?${qs}`).catch(() => null);
  const box = document.getElementById("cj-cuerpo");
  if (!box || cj.vista !== "flujo") return;
  if (!r || !r.ok) { box.innerHTML = `<div class="empty">No se pudo calcular el flujo.</div>`; return; }
  ts.flujo = r;
  const a = r.alerta;
  const sem = r.semanas;
  // gráfico: el saldo al final de cada semana
  const W = 900, H = 200, pad = 34;
  const vals = [r.saldo_actual, ...sem.map(s => s.final)];
  const max = Math.max(...vals, r.minimo || 0, 1), min = Math.min(...vals, 0);
  const x = i => pad + i * ((W - pad * 2) / (vals.length - 1));
  const y = v => 14 + (H - 40) * (1 - (v - min) / ((max - min) || 1));
  const linea = vals.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join(" ");
  const etiquetas = ["Hoy", ...sem.map(s => tsDm(s.desde))];
  box.innerHTML = `
    <div class="ts-flujo-top">
      <div class="ts-kpi grande"><span>Saldo hoy (cajas y cuentas elegidas)</span><b class="${r.saldo_actual < 0 ? "neg" : ""}">${tsGs(r.saldo_actual)}</b></div>
      <div class="ts-kpi"><span>Lo más bajo que va a estar</span><b class="${r.minimo_proyectado < 0 ? "neg" : ""}">${tsGs(r.minimo_proyectado)}</b></div>
      <div class="ts-kpi ${r.vencidos.n ? "ojo" : ""}"><span>Vencido sin pagar/cobrar</span><b>${r.vencidos.n}</b><small>${r.vencidos.n ? `pagar ${cjMil(r.vencidos.egresos)} · cobrar ${cjMil(r.vencidos.ingresos)}` : "todo al día"}</small></div>
      <div class="ts-kpi"><span>Gasto habitual por semana</span><b>${ts.habitual ? cjGs(r.habitual_semanal) : "—"}</b><small>promedio de las últimas 8 semanas</small></div>
    </div>
    ${a ? `<div class="cj-aviso ${a.negativo ? "mal" : "ojo"} ts-alerta"><i class="ti ti-alert-triangle"></i><span><b>La semana del ${tsDm(a.desde)} ${a.negativo ? "la plata no alcanza" : "el saldo baja del mínimo"}:</b> quedaría en ${a.saldo < 0 ? "−" : ""}${cjGs(Math.abs(a.saldo))}. Conviene mover un pago, adelantar un cobro o pedir fondos antes.</span></div>`
      : `<div class="cj-aviso ok ts-alerta"><i class="ti ti-circle-check"></i><span>En las próximas ${ts.semanas} semanas la plata alcanza${r.minimo ? " y no baja del mínimo" : ""}.</span></div>`}
    <div class="ts-flujo-op">
      <div class="cj-seg">${[8, 13, 26].map(n => `<button type="button" class="${ts.semanas === n ? "on" : ""}" onclick="ts.semanas=${n};tsFlujo()">${n} semanas</button>`).join("")}</div>
      <label class="cj-check"><input type="checkbox" ${ts.habitual ? "checked" : ""} onchange="ts.habitual=this.checked;tsFlujo()"> Contar el gasto habitual</label>
      <div class="ts-cajas-sel">${r.cajas.map(c => `<label class="${c.sel ? "on" : ""}"><input type="checkbox" ${c.sel ? "checked" : ""} onchange="tsFlujoCaja(${c.id}, this.checked)"> ${cjEsc(c.nombre)} <small>${cjMil(c.saldo)}</small></label>`).join("")}</div>
    </div>
    <figure class="ts-graf" aria-label="Saldo proyectado semana por semana">
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img">
        ${min < 0 ? `<rect x="${pad}" y="${y(0)}" width="${W - pad * 2}" height="${H - 26 - y(0)}" class="ts-zona-neg"/>` : ""}
        <line x1="${pad}" x2="${W - pad}" y1="${y(0)}" y2="${y(0)}" class="ts-cero"/>
        ${r.minimo ? `<line x1="${pad}" x2="${W - pad}" y1="${y(r.minimo)}" y2="${y(r.minimo)}" class="ts-min"/><text x="${W - pad}" y="${y(r.minimo) - 4}" class="ts-min-t" text-anchor="end">mínimo ${cjMil(r.minimo)}</text>` : ""}
        <path d="${linea}" class="ts-linea"/>
        ${vals.map((v, i) => `<circle cx="${x(i)}" cy="${y(v)}" r="5" class="${v < 0 ? "neg" : ""}"><title>${etiquetas[i]}: ${cjGs(v)}</title></circle>`).join("")}
        ${etiquetas.map((t, i) => (i % (vals.length > 15 ? 2 : 1) === 0 ? `<text x="${x(i)}" y="${H - 6}" text-anchor="middle" class="ts-eje">${t}</text>` : "")).join("")}
      </svg>
      <figcaption>Saldo al final de cada semana (Gs.)</figcaption>
    </figure>
    <div class="cj-tabla-wrap"><table class="cj-tabla ts-semanas">
      <thead><tr><th>Semana</th><th class="num">Saldo inicial</th><th class="num">Entra</th><th class="num">Sale</th><th class="num">Saldo final</th><th></th></tr></thead>
      <tbody>${sem.map((s, i) => `<tr class="${s.final < 0 ? "neg" : r.minimo && s.final < r.minimo ? "bajo" : ""}" onclick="tsSemana(${i})" tabindex="0">
        <td><b>${tsDm(s.desde)} al ${tsDm(s.hasta)}</b>${i === 0 ? `<small>esta semana</small>` : ""}</td>
        <td class="num">${cjMil(s.inicial)}</td>
        <td class="num ing">${s.ingresos ? "+ " + cjMil(s.ingresos) : "—"}</td>
        <td class="num egr">${s.egresos ? "− " + cjMil(s.egresos) : "—"}${s.habitual ? `<small>${cjMil(s.habitual)} habitual</small>` : ""}</td>
        <td class="num"><b class="${s.final < 0 ? "neg" : ""}">${s.final < 0 ? "−" : ""}${cjMil(Math.abs(s.final))}</b></td>
        <td class="cj-ic">${s.items.length ? `${s.items.length} <i class="ti ti-chevron-right"></i>` : ""}</td></tr>`).join("")}</tbody>
    </table></div>
    <p class="ts-nota"><i class="ti ti-info-circle"></i> Sale de: los pagos y cobros programados (los vencidos se cuentan en esta semana), los cheques por cobrar y por debitar en su fecha de pago${ts.habitual ? ", y el gasto habitual que no está programado" : ""}.</p>`;
}
function tsFlujoCaja(id, on) {
  const todas = ts.flujo.cajas.map(c => c.id);
  let sel = ts.sel && ts.sel.length ? [...ts.sel] : [...todas];
  sel = on ? [...new Set([...sel, id])] : sel.filter(x => x !== id);
  ts.sel = sel.length === todas.length ? null : sel;
  tsFlujo();
}
function tsSemana(i) {
  const s = ts.flujo.semanas[i];
  rvModal({
    titulo: `Semana del ${tsDm(s.desde)} al ${tsDm(s.hasta)}`, icono: "calendar-week", ancho: 640, clase: "cj-modal",
    sub: `Empieza con ${tsGs(s.inicial)} y termina con ${s.final < 0 ? "−" : ""}${cjGs(Math.abs(s.final))}`,
    cuerpo: s.items.length || s.habitual ? `<div class="ts-items">${s.items.map(it => `<div class="ts-item ${it.tipo}">
        <span class="f">${tsDia(it.fecha)}${it.vencido ? `<em>vencido</em>` : ""}</span>
        <span class="t"><i class="ti ti-${it.origen === "cheque" ? "file-dollar" : "calendar-dollar"}"></i> ${cjEsc(it.txt)}</span>
        <b>${it.tipo === "ingreso" ? "+" : "−"} ${cjMil(it.monto)}</b></div>`).join("")}
        ${s.habitual ? `<div class="ts-item egreso hab"><span class="f">toda la semana</span><span class="t"><i class="ti ti-receipt"></i> Gasto habitual (promedio)</span><b>− ${cjMil(s.habitual)}</b></div>` : ""}</div>`
      : `<p class="cj-nada">No hay nada programado esta semana.</p>`,
    pie: `<div class="cj-pie"><button type="button" class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove();cjIrVista('prog')">Ver pagos y cobros</button><button type="button" class="btn btn-primary" onclick="this.closest('.modal-overlay').remove()">Listo</button></div>`,
  });
}

// ─── Pagos y cobros programados ─────────────────────────────────────────
async function tsProg() {
  const r = await api("/api/teso/programados?dias=60").catch(() => null);
  const box = document.getElementById("cj-cuerpo");
  if (!box || cj.vista !== "prog") return;
  if (!r || !r.ok) { box.innerHTML = `<div class="empty">No se pudieron traer.</div>`; return; }
  ts.prog = r.programados;
  const hoy = r.hoy;
  // la agenda: cada vencimiento (vencidos primero, después los próximos 60 días)
  const agenda = [];
  r.programados.forEach(p => [...p.vencidas, ...p.proximas].forEach(f => agenda.push({ p, f })));
  agenda.sort((a, b) => a.f.localeCompare(b.f) || (a.p.tipo === "egreso" ? -1 : 1));
  const venc = agenda.filter(x => x.f < hoy);
  const en7 = agenda.filter(x => x.f >= hoy && (new Date(x.f) - new Date(hoy)) / 864e5 <= 7);
  const resto = agenda.filter(x => (new Date(x.f) - new Date(hoy)) / 864e5 > 7);
  const porAprobar = r.programados.filter(p => p.aprobacion === "pendiente");
  const suma = (l, t) => l.filter(x => x.p.tipo === t).reduce((s, x) => s + x.p.monto, 0);
  const grupo = (titulo, l, cls) => l.length ? `<h3 class="ts-h3 ${cls}">${titulo} <span>${l.length} · pagar ${cjMil(suma(l, "egreso"))} · cobrar ${cjMil(suma(l, "ingreso"))}</span></h3>
    <div class="ts-agenda">${l.map(x => tsVenc(x.p, x.f, hoy)).join("")}</div>` : "";
  box.innerHTML = `
    <div class="cj-barra">
      ${cjPuede() ? `<div class="cj-nuevos">
        <button class="btn cj-btn-egr" onclick="tsProgEditar(null, 'egreso')"><i class="ti ti-calendar-minus"></i> Programar un pago</button>
        <button class="btn cj-btn-ing" onclick="tsProgEditar(null, 'ingreso')"><i class="ti ti-calendar-plus"></i> Programar un cobro</button></div>` : ""}
      <div class="cj-acc"><button class="btn btn-ghost" onclick="tsProgLista()"><i class="ti ti-repeat"></i> Todos los programados (${r.programados.length})</button></div>
    </div>
    ${porAprobar.length ? `<div class="ts-aprobar"><h3 class="ts-h3 ojo"><i class="ti ti-shield-check"></i> Esperando aprobación <span>${porAprobar.length}</span></h3>
      ${porAprobar.map(p => `<div class="ts-apr-fila"><span><b>${cjEsc(p.descripcion || p.concepto)}</b><small>${cjEsc(p.contraparte)} · cargó ${cjEsc(p.creado_por)} · ${tsDm(p.fecha)}${p.recurrencia ? " · " + cjEsc(p.recurrencia_txt.toLowerCase()) : ""}</small></span>
        <b class="egr">${cjGs(p.monto)}</b>
        ${ts.res && ts.res.admin ? `<span class="ts-apr-acc"><button class="btn btn-sm btn-ghost" onclick="tsAprobar(${p.id}, false)">Rechazar</button><button class="btn btn-sm btn-primary" onclick="tsAprobar(${p.id}, true)"><i class="ti ti-check"></i> Aprobar</button></span>` : `<small class="ts-gris">lo aprueba administración</small>`}</div>`).join("")}</div>` : ""}
    ${agenda.length ? grupo("Vencidos", venc, "mal") + grupo("Próximos 7 días", en7, "") + grupo("Más adelante", resto, "gris")
      : `<div class="empty"><i class="ti ti-calendar-dollar"></i>No hay nada programado. Cargá los pagos fijos (sueldos, alquiler, cuotas) y los vencimientos de proveedores: el flujo de caja se arma con eso.</div>`}`;
}
function tsVenc(p, f, hoy) {
  const dias = Math.round((new Date(f) - new Date(hoy)) / 864e5);
  const bloq = p.tipo === "egreso" && (p.aprobacion === "pendiente" || p.aprobacion === "rechazado");
  return `<div class="ts-venc ${p.tipo} ${f < hoy ? "vencido" : ""}">
    <div class="ts-venc-f"><b>${tsDm(f)}</b><small>${dias < 0 ? `hace ${-dias} día${dias === -1 ? "" : "s"}` : dias === 0 ? "hoy" : dias === 1 ? "mañana" : `en ${dias} días`}</small></div>
    <div class="ts-venc-t"><b>${cjEsc(p.descripcion || p.concepto)}</b><small>${[p.contraparte, p.caja, p.recurrencia ? p.recurrencia_txt : "", p.prioridad === "alta" ? "⚑ prioridad alta" : ""].filter(Boolean).map(cjEsc).join(" · ")}</small>
      ${p.aprobacion === "pendiente" ? `<em class="ojo"><i class="ti ti-shield"></i> falta aprobación</em>` : p.aprobacion === "rechazado" ? `<em class="mal">rechazado</em>` : p.aprobacion === "aprobado" ? `<em class="ok"><i class="ti ti-shield-check"></i> aprobado</em>` : ""}</div>
    <b class="ts-venc-m ${p.tipo === "ingreso" ? "ing" : "egr"}">${p.tipo === "ingreso" ? "+" : "−"} ${cjMil(p.monto)}</b>
    ${cjPuede() ? `<div class="ts-venc-acc">
      <button class="btn btn-sm ${p.tipo === "ingreso" ? "cj-btn-ing" : "cj-btn-egr"}" ${bloq ? "disabled title='Necesita aprobación'" : ""} onclick="tsCumplir(${p.id}, '${f}')">${p.tipo === "ingreso" ? "Cobrado" : "Pagar"}</button>
      <button class="icon-btn" title="Más" aria-label="Más opciones" onclick="tsProgEditar(${p.id})"><i class="ti ti-pencil"></i></button></div>` : ""}
  </div>`;
}
function tsProgLista() {
  const l = ts.prog || [];
  rvModal({
    titulo: "Pagos y cobros programados", icono: "repeat", ancho: 760, clase: "cj-modal",
    sub: "Los fijos que se repiten y los vencimientos cargados",
    cuerpo: l.length ? `<div class="cj-tabla-wrap"><table class="cj-tabla"><thead><tr><th>Qué</th><th>Cuándo</th><th class="num">Monto</th><th></th></tr></thead><tbody>
      ${l.map(p => `<tr onclick="this.closest('.modal-overlay').remove();tsProgEditar(${p.id})"><td><b>${cjEsc(p.descripcion || p.concepto)}</b><small>${cjEsc(p.contraparte || "")}${p.caja ? " · " + cjEsc(p.caja) : ""}</small></td>
        <td>${cjEsc(p.recurrencia_txt)}<small>${p.proximas.length ? "próximo " + tsDm(p.proximas[0]) : ""}${p.vencidas.length ? ` · ${p.vencidas.length} vencido${p.vencidas.length === 1 ? "" : "s"}` : ""}</small></td>
        <td class="num ${p.tipo === "ingreso" ? "ing" : "egr"}">${p.tipo === "ingreso" ? "+" : "−"} ${cjMil(p.monto)}</td><td class="cj-ic"><i class="ti ti-pencil"></i></td></tr>`).join("")}</tbody></table></div>`
      : `<p class="cj-nada">Todavía no hay nada programado.</p>`,
    pie: `<div class="cj-pie"><button type="button" class="btn btn-primary" onclick="this.closest('.modal-overlay').remove()">Listo</button></div>`,
  });
}
function tsProgEditar(id, tipo) {
  const p = id ? ts.prog.find(x => x.id === id) : { tipo, fecha: cj.meta.hoy, recurrencia: "", medio: tipo === "ingreso" ? "transferencia" : "transferencia", prioridad: "normal", caja_id: cj.caja ? cj.caja.id : 0, monto: "" };
  const umbral = (ts.res && ts.res.config && ts.res.config.umbral_aprobacion) || 0;
  const conc = cjConceptos(p.tipo);
  const o = rvModal({
    titulo: id ? (p.tipo === "ingreso" ? "Cobro programado" : "Pago programado") : (p.tipo === "ingreso" ? "Programar un cobro" : "Programar un pago"),
    icono: p.tipo === "ingreso" ? "calendar-plus" : "calendar-minus", ancho: 640, clase: `cj-modal cj-${p.tipo}`,
    sub: p.tipo === "egreso" ? `Un vencimiento o un gasto fijo. ${umbral ? `Desde ${cjGs(umbral)} necesita aprobación de administración.` : ""}` : "Lo que te tienen que pagar y cuándo",
    cuerpo: `<div class="cj-g cj-g-2">
        <label class="cj-f" style="grid-column:1/-1"><span>Qué es</span><input id="tp-desc" value="${cjEsc(p.descripcion || "")}" placeholder="${p.tipo === "egreso" ? "Ej: sueldos del taller, alquiler del galpón, cuota del camión" : "Ej: cobro del corporativo de Paresa"}"></label>
        <label class="cj-f"><span>${p.tipo === "egreso" ? "A quién" : "De quién"}</span><input id="tp-cp" value="${cjEsc(p.contraparte || "")}"></label>
        <label class="cj-f"><span>Monto (Gs.)</span><input id="tp-monto" inputmode="numeric" value="${p.monto ? cjMil(p.monto) : ""}" placeholder="0"></label>
        <label class="cj-f"><span>${p.recurrencia ? "Primera vez" : "Fecha"}</span><input type="date" id="tp-fecha" value="${p.fecha}"></label>
        <label class="cj-f"><span>¿Se repite?</span><select id="tp-rec">${cjOpts(ts.res.recurrencias, p.recurrencia || "")}</select></label>
        <label class="cj-f tp-hasta" ${p.recurrencia ? "" : "hidden"}><span>Hasta <small>vacío = sin fin</small></span><input type="date" id="tp-hasta" value="${p.hasta || ""}"></label>
        <label class="cj-f"><span>${p.tipo === "egreso" ? "Sale de" : "Entra a"}</span><select id="tp-caja"><option value="0">A elegir al pagar</option>${tsCajasOpts(p.caja_id)}</select></label>
        <label class="cj-f"><span>Concepto</span><select id="tp-conc"><option value="">—</option>${conc.map(k => `<option value="${k.id}" ${+p.concepto_id === k.id ? "selected" : ""}>${cjEsc(k.nombre)}</option>`).join("")}</select></label>
        <label class="cj-f"><span>Medio</span><select id="tp-medio">${cjOpts(cj.meta.medios, p.medio)}</select></label>
        ${p.tipo === "egreso" ? `<label class="cj-f"><span>Prioridad</span><select id="tp-prio">${cjOpts({ alta: "Alta (no se puede atrasar)", normal: "Normal", baja: "Baja (se puede mover)" }, p.prioridad)}</select></label>` : ""}
        <label class="cj-f"><span>N° de factura <small>opcional</small></span><input id="tp-doc" value="${cjEsc(p.doc_numero || "")}"></label>
        <label class="cj-f" style="grid-column:1/-1"><span>Nota</span><input id="tp-nota" value="${cjEsc(p.nota || "")}"></label>
      </div>
      ${id && p.hechos.length ? `<p class="ts-nota">Ya ${p.tipo === "ingreso" ? "cobrado" : "pagado"}: ${p.hechos.map(tsDm).join(", ")}</p>` : ""}`,
    pie: `<div class="cj-pie">
      ${id && cjPuede() ? `<button type="button" class="pv-link cj-anular" onclick="tsProgBorrar(${id})">Borrar</button>` : ""}
      <button type="button" class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancelar</button>
      ${cjPuede() ? `<button type="button" class="btn btn-primary" id="tp-ok"><i class="ti ti-check"></i> Guardar</button>` : ""}</div>`,
  });
  o.querySelector("#tp-rec").onchange = e => { o.querySelector(".tp-hasta").hidden = !e.target.value; };
  const m = o.querySelector("#tp-monto");
  m.onblur = () => { const n = Math.round(cjNum(m.value)); m.value = n ? cjMil(n) : ""; };
  o.querySelector("#tp-ok")?.addEventListener("click", async e => {
    const v = s => o.querySelector(s)?.value || "";
    const k = cj.meta.conceptos.find(x => x.id === +v("#tp-conc"));
    e.target.disabled = true;
    const r = await tsJson(id ? `/api/teso/programados/${id}` : "/api/teso/programados", id ? "PUT" : "POST", {
      tipo: p.tipo, descripcion: v("#tp-desc"), contraparte: v("#tp-cp"), monto: v("#tp-monto"), fecha: v("#tp-fecha"),
      recurrencia: v("#tp-rec"), hasta: v("#tp-hasta"), caja_id: v("#tp-caja"), concepto_id: k ? k.id : 0, concepto: k ? k.nombre : "",
      medio: v("#tp-medio"), prioridad: v("#tp-prio") || "normal", doc_numero: v("#tp-doc"), nota: v("#tp-nota"),
    });
    if (!r || !r.ok) { e.target.disabled = false; toast((r && r.msg) || "No se pudo", "error"); return; }
    toast(r.msg, "success");
    o.remove();
    tsResumen();
    tsProg();
  });
  setTimeout(() => o.querySelector("#tp-desc").focus(), 60);
}
async function tsProgBorrar(id) {
  if (!confirm("¿Borrar este pago/cobro programado? Lo que ya se pagó queda en las cajas.")) return;
  const r = await tsJson(`/api/teso/programados/${id}`, "DELETE");
  document.querySelector(".cj-modal")?.closest(".modal-overlay")?.remove();
  toast((r && r.msg) || "No se pudo", r && r.ok ? "success" : "error");
  tsResumen(); tsProg();
}
async function tsAprobar(id, si) {
  let motivo = "";
  if (!si) { motivo = prompt("¿Por qué se rechaza?") || ""; if (!motivo) return; }
  const r = await tsJson(`/api/teso/programados/${id}/aprobar`, "POST", { aprobar: si, motivo });
  toast((r && r.msg) || "No se pudo", r && r.ok ? "success" : "error");
  tsResumen(); tsProg();
}
function tsCumplir(id, f) {
  const p = ts.prog.find(x => x.id === id);
  const ing = p.tipo === "ingreso";
  const o = rvModal({
    titulo: ing ? "Registrar el cobro" : "Registrar el pago", icono: ing ? "cash" : "cash-banknote", ancho: 520, clase: `cj-modal cj-${p.tipo}`,
    sub: `${cjEsc(p.descripcion || p.concepto)} · vencimiento del ${tsDm(f)}`,
    cuerpo: `<div class="cj-g cj-g-2">
        <label class="cj-f"><span>${ing ? "Entró a" : "Salió de"}</span><select id="tc-caja">${tsCajasOpts(p.caja_id || (cj.caja && cj.caja.id))}</select></label>
        <label class="cj-f"><span>Monto (Gs.)</span><input id="tc-monto" inputmode="numeric" value="${cjMil(p.monto)}"></label>
        <label class="cj-f"><span>Fecha</span><input type="date" id="tc-fecha" value="${cj.meta.hoy}"></label>
        <label class="cj-f"><span>Medio</span><select id="tc-medio">${cjOpts(cj.meta.medios, p.medio)}</select></label>
        <label class="cj-f"><span>Comprobante</span><select id="tc-doc">${cjOpts(cj.meta.docs, ing ? "recibo" : "interno")}</select></label>
        <label class="cj-f"><span>N°</span><input id="tc-docn" value="${cjEsc(p.doc_numero || "")}"></label>
      </div><p class="ts-nota"><i class="ti ti-info-circle"></i> Se carga como movimiento en esa caja o cuenta. Si es una factura con IVA, cargala después desde Movimientos con su foto.</p>`,
    pie: `<div class="cj-pie">
      <button type="button" class="pv-link" onclick="tsSaltar(${id}, '${f}')">Este no se ${ing ? "cobra" : "paga"}</button>
      <button type="button" class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancelar</button>
      <button type="button" class="btn ${ing ? "cj-btn-ing" : "cj-btn-egr"}" id="tc-ok"><i class="ti ti-check"></i> ${ing ? "Cobrado" : "Pagado"}</button></div>`,
  });
  o.querySelector("#tc-ok").onclick = async e => {
    const v = s => o.querySelector(s).value;
    e.target.disabled = true;
    const r = await tsJson(`/api/teso/programados/${id}/cumplir`, "POST", { fecha: f, caja_id: v("#tc-caja"), monto: cjNum(v("#tc-monto")), fecha_pago: v("#tc-fecha"), medio: v("#tc-medio"), doc_tipo: v("#tc-doc"), doc_numero: v("#tc-docn") });
    if (!r || !r.ok) { e.target.disabled = false; toast((r && r.msg) || "No se pudo", "error"); return; }
    toast(r.msg, "success");
    o.remove();
    await cjRefrescarCajas(); tsResumen(); tsProg();
  };
}
async function tsSaltar(id, f) {
  if (!confirm("¿Marcar este vencimiento como que no se paga/cobra? No se carga nada en la caja.")) return;
  const r = await tsJson(`/api/teso/programados/${id}/cumplir`, "POST", { fecha: f, accion: "saltar" });
  document.querySelector(".cj-modal")?.closest(".modal-overlay")?.remove();
  toast((r && r.msg) || "No se pudo", r && r.ok ? "success" : "error");
  tsResumen(); tsProg();
}

// ─── Cheques ────────────────────────────────────────────────────────────
async function tsCheques() {
  const qs = new URLSearchParams({ sentido: ts.chSent, estado: ts.chEst, q: ts.chQ });
  const r = await api(`/api/teso/cheques?${qs}`).catch(() => null);
  const box = document.getElementById("cj-cuerpo");
  if (!box || cj.vista !== "cheques") return;
  if (!r || !r.ok) { box.innerHTML = `<div class="empty">No se pudieron traer los cheques.</div>`; return; }
  ts.ch = r.cheques;
  const t = r.totales, rec = ts.chSent === "recibido";
  const est = ts.res.estados_cheque[ts.chSent];
  box.innerHTML = `
    <div class="cj-barra">
      <div class="cj-seg">${[["recibido", "Recibidos (cartera)"], ["emitido", "Emitidos (chequera)"]].map(([k, v]) => `<button type="button" class="${ts.chSent === k ? "on" : ""}" onclick="ts.chSent='${k}';ts.chEst='abiertos';tsCheques()">${v}</button>`).join("")}</div>
      ${cjPuede() ? `<div class="cj-nuevos"><button class="btn btn-primary" onclick="tsChequeEditar(null)"><i class="ti ti-plus"></i> ${rec ? "Cheque recibido" : "Cheque emitido"}</button></div>` : ""}
    </div>
    <div class="ts-flujo-top">
      <div class="ts-kpi"><span>En cartera (por cobrar)</span><b class="ing">${cjGs(t.cartera)}</b><small>${t.n_cartera} cheque${t.n_cartera === 1 ? "" : "s"}</small></div>
      <div class="ts-kpi"><span>Emitidos por debitar</span><b class="egr">${cjGs(t.por_debitar)}</b><small>${t.n_por_debitar} cheque${t.n_por_debitar === 1 ? "" : "s"}</small></div>
      <div class="ts-kpi ${t.avisos ? "ojo" : ""}"><span>Con aviso</span><b>${t.avisos}</b><small>por vencer o para depositar</small></div>
    </div>
    <div class="cj-filtros">
      <select class="cj-sel" onchange="ts.chEst=this.value;tsCheques()" aria-label="Estado"><option value="abiertos" ${ts.chEst === "abiertos" ? "selected" : ""}>Abiertos</option><option value="" ${!ts.chEst ? "selected" : ""}>Todos</option>${Object.entries(est).map(([k, v]) => `<option value="${k}" ${ts.chEst === k ? "selected" : ""}>${v}</option>`).join("")}</select>
      <label class="cj-buscar"><i class="ti ti-search"></i><input type="search" value="${cjEsc(ts.chQ)}" placeholder="Número, banco, ${rec ? "librador" : "beneficiario"}" oninput="clearTimeout(ts._q);ts._q=setTimeout(()=>{ts.chQ=this.value;tsCheques()},300)"></label>
    </div>
    ${r.cheques.length ? `<div class="ts-cheques">${r.cheques.map(tsChequeCard).join("")}</div>`
      : `<div class="empty"><i class="ti ti-file-dollar"></i>No hay cheques ${rec ? "recibidos" : "emitidos"} con ese filtro.</div>`}
    <p class="ts-nota"><i class="ti ti-scale"></i> Cheque de pago diferido (Ley 805/96): la fecha de pago no puede pasar de ${180} días desde la emisión, y hay 30 días después de esa fecha para presentarlo al banco. Si se deposita antes de la fecha de pago, el banco lo rechaza.</p>`;
}
function tsChequeCard(c) {
  const rec = c.sentido === "recibido";
  const abiertos = ["cartera", "depositado", "emitido", "entregado"].includes(c.estado);
  const acc = !cjPuede() ? [] : rec
    ? ({ cartera: [["depositar", "Depositar", "building-bank"], ["cobrar", "Acreditado", "circle-check"], ["endosar", "Endosar", "arrow-forward"], ["rechazar", "Rechazado", "ban"]],
         depositado: [["cobrar", "Acreditado", "circle-check"], ["rechazar", "Rechazado", "ban"]], cobrado: [["rechazar", "Rechazado", "ban"]] }[c.estado] || [])
    : ({ emitido: [["entregar", "Entregado", "hand-finger"], ["debitar", "Debitado", "circle-check"], ["anular", "Anular", "x"]],
         entregado: [["debitar", "Debitado", "circle-check"], ["anular", "Anular", "x"], ["rechazar", "Rechazado", "ban"]], debitado: [["rechazar", "Rechazado", "ban"]] }[c.estado] || []);
  return `<div class="ts-cheque e-${c.estado} ${abiertos ? "" : "cerrado"}">
    <div class="ts-ch-cab"><span class="ts-ch-banco"><i class="ti ti-building-bank"></i> ${cjEsc(c.banco || "Banco")} · N° ${cjEsc(c.numero)}</span>
      <span class="ts-ch-tipo">${c.tipo === "diferido" ? "Diferido" : "Al día"}</span></div>
    <div class="ts-ch-m ${rec ? "ing" : "egr"}">${cjGs(c.monto)}</div>
    <div class="ts-ch-p">${rec ? "De" : "A"} <b>${cjEsc(c.persona || "—")}</b>${c.concepto ? ` · ${cjEsc(c.concepto)}` : ""}</div>
    <div class="ts-ch-f"><span>Emitido ${tsDm(c.fecha_emision)}</span><span><b>Pago ${tsDm(c.fecha_pago)}</b>${abiertos ? ` · ${c.dias > 0 ? `en ${c.dias} días` : c.dias === 0 ? "hoy" : `hace ${-c.dias} días`}` : ""}</span></div>
    <div class="ts-ch-est"><span class="ts-pill e-${c.estado}">${cjEsc(c.estado_txt)}</span>${c.caja ? `<small>${cjEsc(c.caja)}</small>` : ""}</div>
    ${c.avisos.map(a => `<div class="cj-aviso ${a.nivel === "info" ? "info" : a.nivel}"><i class="ti ti-${a.nivel === "mal" ? "alert-triangle" : "info-circle"}"></i><span>${cjEsc(a.msg)}</span></div>`).join("")}
    ${acc.length ? `<div class="ts-ch-acc">${acc.map(([k, t, ic]) => `<button type="button" class="btn btn-sm ${k === "cobrar" || k === "debitar" ? "btn-primary" : "btn-ghost"}" onclick="tsChequeAccion(${c.id}, '${k}')"><i class="ti ti-${ic}"></i> ${t}</button>`).join("")}
      ${!c.mov_id ? `<button type="button" class="icon-btn" title="Corregir" aria-label="Corregir" onclick="tsChequeEditar(${c.id})"><i class="ti ti-pencil"></i></button>` : ""}</div>` : ""}
    ${c.historial.length > 1 ? `<details class="ts-ch-hist"><summary>Historial</summary>${c.historial.map(h => `<div>${tsDm(h.el.slice(0, 10))} ${h.el.slice(11, 16)} · ${cjEsc(h.txt)} <small>${cjEsc(h.por)}</small></div>`).join("")}</details>` : ""}
  </div>`;
}
function tsChequeEditar(id) {
  const c = id ? ts.ch.find(x => x.id === id) : { sentido: ts.chSent, tipo: "diferido", fecha_emision: cj.meta.hoy, fecha_pago: cj.meta.hoy, banco: "", caja_id: 0 };
  const rec = c.sentido === "recibido";
  const o = rvModal({
    titulo: id ? "Corregir cheque" : rec ? "Cheque recibido" : "Cheque emitido", icono: "file-dollar", ancho: 600, clase: "cj-modal",
    sub: rec ? "Un cheque que nos dieron: queda en cartera hasta que se deposita" : "Un cheque que dimos: se descuenta de la cuenta cuando se debita",
    cuerpo: `<div class="cj-g cj-g-2">
        <label class="cj-f"><span>Tipo</span><select id="tq-tipo"><option value="diferido" ${c.tipo === "diferido" ? "selected" : ""}>De pago diferido</option><option value="comun" ${c.tipo === "comun" ? "selected" : ""}>Al día (común)</option></select></label>
        <label class="cj-f"><span>Banco</span><input id="tq-banco" list="ts-bancos-q" value="${cjEsc(c.banco)}" placeholder="Ej: Itaú"></label>
        <label class="cj-f"><span>N° de cheque</span><input id="tq-num" value="${cjEsc(c.numero || "")}" inputmode="numeric"></label>
        <label class="cj-f"><span>Monto (Gs.)</span><input id="tq-monto" inputmode="numeric" value="${c.monto ? cjMil(c.monto) : ""}"></label>
        <label class="cj-f"><span>${rec ? "Librador (quién lo firma)" : "Beneficiario (a quién)"}</span><input id="tq-pers" value="${cjEsc(c.persona || "")}"></label>
        <label class="cj-f"><span>RUC / CI</span><input id="tq-ruc" value="${cjEsc(c.ruc || "")}"></label>
        <label class="cj-f"><span>Fecha de emisión</span><input type="date" id="tq-fe" value="${c.fecha_emision}"></label>
        <label class="cj-f tq-fp"><span>Fecha de pago</span><input type="date" id="tq-fp" value="${c.fecha_pago}"></label>
        ${rec ? "" : `<label class="cj-f"><span>Cuenta de la que sale</span><select id="tq-caja"><option value="0">Elegí…</option>${tsCajasOpts(c.caja_id, true) || tsCajasOpts(c.caja_id)}</select></label>`}
        <label class="cj-f" ${rec ? `style="grid-column:1/-1"` : ""}><span>Por qué</span><input id="tq-conc" value="${cjEsc(c.concepto || "")}" placeholder="${rec ? "Ej: pago del viaje de turismo" : "Ej: repuestos factura 001-001-345"}"></label>
      </div>
      <datalist id="ts-bancos-q">${ts.res.bancos.map(b => `<option value="${cjEsc(b)}">`).join("")}</datalist>
      <div class="cj-aviso info" id="tq-av" hidden></div>`,
    pie: `<div class="cj-pie"><button type="button" class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancelar</button>
      <button type="button" class="btn btn-primary" id="tq-ok"><i class="ti ti-check"></i> Guardar</button></div>`,
  });
  const v = s => o.querySelector(s)?.value || "";
  const revisar = () => {
    const dif = v("#tq-tipo") === "diferido";
    o.querySelector(".tq-fp").hidden = !dif;
    const av = o.querySelector("#tq-av");
    if (dif && v("#tq-fe") && v("#tq-fp")) {
      const d = Math.round((new Date(v("#tq-fp")) - new Date(v("#tq-fe"))) / 864e5);
      av.hidden = false;
      av.className = "cj-aviso " + (d > 180 || d < 0 ? "mal" : "info");
      av.innerHTML = d > 180 ? `<i class="ti ti-alert-triangle"></i><span>A ${d} días: un diferido no puede pasar de 180 días (Ley 805/96).</span>`
        : d < 0 ? `<i class="ti ti-alert-triangle"></i><span>La fecha de pago es antes de la emisión.</span>`
        : `<i class="ti ti-info-circle"></i><span>A ${d} días.${rec ? ` Se puede depositar desde el ${tsDm(v("#tq-fp"))} y hasta 30 días después.` : ""}</span>`;
    } else av.hidden = true;
  };
  ["#tq-tipo", "#tq-fe", "#tq-fp"].forEach(s => o.querySelector(s).addEventListener("change", revisar));
  revisar();
  const m = o.querySelector("#tq-monto");
  m.onblur = () => { const n = Math.round(cjNum(m.value)); m.value = n ? cjMil(n) : ""; };
  o.querySelector("#tq-ok").onclick = async e => {
    e.target.disabled = true;
    const r = await tsJson(id ? `/api/teso/cheques/${id}` : "/api/teso/cheques", id ? "PUT" : "POST", {
      sentido: c.sentido, tipo: v("#tq-tipo"), banco: v("#tq-banco"), numero: v("#tq-num"), monto: v("#tq-monto"), persona: v("#tq-pers"),
      ruc: v("#tq-ruc"), fecha_emision: v("#tq-fe"), fecha_pago: v("#tq-fp"), caja_id: v("#tq-caja"), concepto: v("#tq-conc"),
    });
    if (!r || !r.ok) { e.target.disabled = false; toast((r && r.msg) || "No se pudo", "error"); return; }
    toast(r.msg, "success");
    o.remove();
    tsResumen(); tsCheques();
  };
  setTimeout(() => o.querySelector("#tq-banco").focus(), 60);
}
function tsChequeAccion(id, accion) {
  const c = ts.ch.find(x => x.id === id);
  const titulos = { depositar: "Depositar el cheque", cobrar: "Acreditado en la cuenta", endosar: "Endosar a un tercero", rechazar: "Cheque rechazado",
                    entregar: "Entregar el cheque", debitar: "Debitado de la cuenta", anular: "Anular el cheque" };
  const pideCaja = ["depositar", "cobrar"].includes(accion);
  const pideMotivo = ["rechazar", "anular"].includes(accion);
  const o = rvModal({
    titulo: titulos[accion], icono: "file-dollar", ancho: 480, clase: "cj-modal",
    sub: `${cjEsc(c.banco)} N° ${cjEsc(c.numero)} · ${cjGs(c.monto)} · ${cjEsc(c.persona)}`,
    cuerpo: `${pideCaja ? `<label class="cj-f"><span>Cuenta</span><select id="ta-caja">${tsCajasOpts(c.caja_id, true) || tsCajasOpts(c.caja_id)}</select></label>` : ""}
      ${accion === "endosar" ? `<label class="cj-f"><span>¿A quién se le endosó?</span><input id="ta-quien"></label>` : ""}
      ${pideMotivo ? `<label class="cj-f"><span>Motivo</span><input id="ta-mot" placeholder="${accion === "rechazar" ? "Ej: sin fondos" : "Ej: mal llenado"}"></label>` : ""}
      ${["cobrar", "debitar", "rechazar"].includes(accion) ? `<label class="cj-f"><span>Fecha</span><input type="date" id="ta-fecha" value="${cj.meta.hoy}"></label>` : ""}
      ${accion === "cobrar" || accion === "debitar" ? `<p class="ts-nota"><i class="ti ti-info-circle"></i> Se carga el ${accion === "cobrar" ? "ingreso" : "egreso"} en la cuenta.</p>` : ""}
      ${accion === "rechazar" && (c.estado === "cobrado" || c.estado === "debitado") ? `<p class="ts-nota"><i class="ti ti-info-circle"></i> Como ya estaba ${c.estado}, se carga el movimiento al revés en la cuenta.</p>` : ""}`,
    pie: `<div class="cj-pie"><button type="button" class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancelar</button>
      <button type="button" class="btn btn-primary" id="ta-ok"><i class="ti ti-check"></i> Confirmar</button></div>`,
  });
  o.querySelector("#ta-ok").onclick = async e => {
    const v = s => o.querySelector(s)?.value || "";
    e.target.disabled = true;
    const r = await tsJson(`/api/teso/cheques/${id}/${accion}`, "POST", { caja_id: v("#ta-caja"), a_quien: v("#ta-quien"), motivo: v("#ta-mot"), fecha: v("#ta-fecha") });
    if (!r || !r.ok) { e.target.disabled = false; toast((r && r.msg) || "No se pudo", "error"); return; }
    toast(r.msg, "success");
    o.remove();
    await cjRefrescarCajas(); tsResumen(); tsCheques();
  };
}

// ─── Conciliación bancaria ──────────────────────────────────────────────
async function tsConc() {
  const bancos = (cj.cajas || []).filter(c => c.tipo === "banco");
  const box = document.getElementById("cj-cuerpo");
  if (!bancos.length) {
    box.innerHTML = `<div class="empty"><i class="ti ti-building-bank"></i>No hay cuentas de banco.${cj.meta.admin ? ` En «Cajas y conceptos» marcá cuál es una cuenta de banco (o creá una), con su banco y número.` : " Pedile a administración que cargue las cuentas."}</div>`;
    return;
  }
  if (!bancos.some(b => b.id === ts.conCaja)) ts.conCaja = bancos[0].id;
  const r = await api(`/api/teso/conciliacion/${ts.conCaja}`).catch(() => null);
  if (!box || cj.vista !== "conc") return;
  if (!r || !r.ok) { box.innerHTML = `<div class="empty">No se pudo traer la conciliación.</div>`; return; }
  ts.con = r;
  const pendE = r.extracto.filter(e => e.estado === "pendiente"), pendM = r.movs.filter(m => !m.extracto_id);
  const dif = r.saldo_banco == null ? null : Math.round(r.saldo_banco - r.saldo_sistema);
  box.innerHTML = `
    <div class="cj-barra">
      <div class="ts-cuentas">${bancos.map(b => `<button type="button" class="${b.id === ts.conCaja ? "on" : ""}" onclick="ts.conCaja=${b.id};tsConc()"><i class="ti ti-building-bank"></i> ${cjEsc(b.nombre)}<small>${cjEsc(b.banco || "")} ${cjEsc(b.numero_cuenta || "")}</small></button>`).join("")}</div>
      ${cjPuede() ? `<div class="cj-acc">
        <label class="btn btn-primary"><i class="ti ti-upload"></i> Subir extracto<input type="file" accept=".xlsx,.csv,.txt" hidden onchange="tsSubirExtracto(this)"></label>
        <button class="btn btn-ghost" onclick="tsAuto()"><i class="ti ti-wand"></i> Conciliar solo</button></div>` : ""}
    </div>
    <div class="ts-flujo-top">
      <div class="ts-kpi"><span>Saldo según el banco</span><b>${r.saldo_banco == null ? "—" : tsGs(r.saldo_banco)}</b><small>${r.saldo_banco_fecha ? "al " + tsDm(r.saldo_banco_fecha) : "subí un extracto con saldo"}</small></div>
      <div class="ts-kpi"><span>Saldo en el sistema</span><b>${tsGs(r.saldo_sistema)}</b></div>
      <div class="ts-kpi ${dif ? "ojo" : ""}"><span>Diferencia</span><b>${dif == null ? "—" : dif === 0 ? "Cuadra" : (dif > 0 ? "+" : "−") + cjMil(Math.abs(dif))}</b><small>${dif ? "la explican las líneas sin conciliar" : ""}</small></div>
      <div class="ts-kpi ${pendE.length ? "ojo" : ""}"><span>Sin conciliar</span><b>${pendE.length} / ${pendM.length}</b><small>en el banco / en el sistema</small></div>
    </div>
    ${r.extracto.length ? `<div class="ts-conc">
      <div class="ts-conc-col"><h3 class="ts-h3">Extracto del banco <span>${pendE.length} pendiente${pendE.length === 1 ? "" : "s"}</span></h3>
        ${r.extracto.map(e => `<div class="ts-ext e-${e.estado}" data-id="${e.id}">
          <span class="f">${tsDm(e.fecha)}</span>
          <span class="t"><b>${cjEsc(e.descripcion || "—")}</b>${e.referencia ? `<small>ref. ${cjEsc(e.referencia)}</small>` : ""}</span>
          <b class="m ${e.monto > 0 ? "ing" : "egr"}">${e.monto > 0 ? "+" : "−"} ${cjMil(Math.abs(e.monto))}</b>
          <span class="acc">${e.estado === "conciliado" ? `<span class="ts-pill e-cobrado" title="${e.como === "auto" ? "conciliado solo" : "a mano"}"><i class="ti ti-link"></i> ${e.como === "auto" ? "solo" : "a mano"}</span>${cjPuede() ? `<button class="icon-btn" title="Desenganchar" aria-label="Desenganchar" onclick="tsExt(${e.id}, 'desconciliar')"><i class="ti ti-unlink"></i></button>` : ""}`
            : e.estado === "ignorado" ? `<span class="ts-pill">ignorada</span>`
            : cjPuede() ? `<button class="btn btn-sm btn-ghost" onclick="tsEnganchar(${e.id})"><i class="ti ti-link"></i> Enganchar</button>` : ""}</span>
        </div>`).join("")}</div>
      <div class="ts-conc-col"><h3 class="ts-h3">Cargado en el sistema <span>${pendM.length} sin conciliar</span></h3>
        ${r.movs.map(m => `<div class="ts-ext ${m.extracto_id ? "e-conciliado" : "e-pendiente"}">
          <span class="f">${tsDm(m.fecha_oper)}</span>
          <span class="t"><b>${cjEsc(m.contraparte || m.concepto || "—")}</b><small>N° ${m.numero} · ${cjEsc(m.concepto || "")}</small></span>
          <b class="m ${m.tipo === "ingreso" ? "ing" : "egr"}">${m.tipo === "ingreso" ? "+" : "−"} ${cjMil(m.total_gs)}</b>
          <span class="acc">${m.extracto_id ? `<i class="ti ti-link ts-ok"></i>` : ""}</span></div>`).join("")}</div>
    </div>` : `<div class="empty"><i class="ti ti-file-upload"></i>Subí el extracto del banco (Excel .xlsx o .csv, como lo bajás del home banking). Tiene que tener columnas de Fecha y Débito/Crédito o Importe: el sistema las encuentra solo.</div>`}`;
}
async function tsSubirExtracto(inp) {
  const f = inp.files[0];
  if (!f) return;
  const fd = new FormData();
  fd.append("archivo", f);
  const r = await api(`/api/teso/conciliacion/${ts.conCaja}/importar`, { method: "POST", body: fd }).catch(() => null);
  inp.value = "";
  toast((r && r.msg) || "No se pudo", r && r.ok ? "success" : "error");
  tsResumen(); tsConc();
}
async function tsAuto() {
  const r = await tsJson(`/api/teso/conciliacion/${ts.conCaja}/auto`);
  toast((r && r.msg) || "No se pudo", r && r.ok ? "success" : "error");
  tsResumen(); tsConc();
}
async function tsExt(id, accion, cuerpo) {
  const r = await tsJson(`/api/teso/extracto/${id}/${accion}`, "POST", cuerpo || {});
  toast((r && r.msg) || "No se pudo", r && r.ok ? "success" : "error");
  document.querySelector(".ts-eng")?.closest(".modal-overlay")?.remove();
  await cjRefrescarCajas(); tsResumen(); tsConc();
}
function tsEnganchar(id) {
  const e = ts.con.extracto.find(x => x.id === id);
  const signo = e.monto > 0 ? "ingreso" : "egreso";
  const cand = ts.con.movs.filter(m => !m.extracto_id && m.tipo === signo)
    .map(m => ({ m, dm: Math.abs(m.total_gs - Math.abs(e.monto)), dd: Math.abs((new Date(m.fecha_oper) - new Date(e.fecha)) / 864e5) }))
    .sort((a, b) => a.dm - b.dm || a.dd - b.dd).slice(0, 12);
  const conc = cjConceptos(signo);
  rvModal({
    titulo: "Enganchar la línea del banco", icono: "link", ancho: 640, clase: "cj-modal ts-eng",
    sub: `${tsDm(e.fecha)} · ${cjEsc(e.descripcion)} · ${e.monto > 0 ? "+" : "−"} ${cjMil(Math.abs(e.monto))}`,
    cuerpo: `<h4 class="cj-h4">¿Con cuál movimiento del sistema?</h4>
      ${cand.length ? `<div class="ts-cand">${cand.map(({ m, dm, dd }) => `<button type="button" onclick="tsExt(${id}, 'conciliar', {mov_id: ${m.id}})">
        <span>${tsDm(m.fecha_oper)}</span><span><b>${cjEsc(m.contraparte || m.concepto || "—")}</b><small>N° ${m.numero} · ${cjEsc(m.concepto || "")}</small></span>
        <b class="${signo === "ingreso" ? "ing" : "egr"}">${cjMil(m.total_gs)}</b>${dm < 1 ? `<em class="ok">mismo monto</em>` : `<em>dif. ${cjMil(dm)}</em>`}</button>`).join("")}</div>`
        : `<p class="cj-nada">No hay movimientos sin conciliar de ese tipo.</p>`}
      <h4 class="cj-h4">¿Solo está en el banco? (comisión, interés, débito automático)</h4>
      <div class="ts-crear"><select id="te-conc"><option value="">${e.monto < 0 ? "Gastos bancarios" : "Ingreso bancario"}</option>${conc.map(k => `<option value="${k.id}">${cjEsc(k.nombre)}</option>`).join("")}</select>
        <button type="button" class="btn btn-ghost" onclick="const s=document.getElementById('te-conc');const k=cj.meta.conceptos.find(x=>x.id===+s.value);tsExt(${id}, 'crear', {concepto_id: k?k.id:0, concepto: k?k.nombre:''})"><i class="ti ti-plus"></i> Cargarlo y conciliar</button></div>`,
    pie: `<div class="cj-pie"><button type="button" class="pv-link" onclick="tsExt(${id}, 'ignorar')">Ignorar esta línea</button><button type="button" class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancelar</button></div>`,
  });
}
