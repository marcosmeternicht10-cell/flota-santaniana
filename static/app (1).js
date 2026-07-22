// ════════════════════════════════════════════════════════════════════════
//  app.js — Sistema de Gestión de Flota v7.0
//  La Santaniana - Mantenimiento Preventivo + Correctivo + Documentos
// ════════════════════════════════════════════════════════════════════════

let cocheActual = null;
let chartBarras = null, chartTorta = null;
let kpiModo = "mes", mantTab = "estado", planActual = null;

const $ = sel => document.querySelector(sel);
const content = $("#content");

// ─── Utilidades ─────────────────────────────────────────────────────────
function gs(v) {
  if (v == null) return "Gs. —";
  const neg = v < 0;
  const s = "Gs. " + Math.abs(Math.round(v)).toLocaleString("es-PY").replace(/,/g, ".");
  return neg ? "- " + s : s;
}
function gsSmall(v) {
  if (v == null) return "Gs. —";
  if (Math.abs(v) >= 1e6) return "Gs. " + (v / 1e6).toFixed(1) + "M";
  if (Math.abs(v) >= 1e3) return "Gs. " + (v / 1e3).toFixed(0) + "k";
  return "Gs. " + Math.round(v).toLocaleString("es-PY").replace(/,/g, ".");
}
function fmtKm(v) { return (v || 0).toLocaleString("es-PY").replace(/,/g, ".") + " km"; }
function fmtNum(v) { return (v || 0).toLocaleString("es-PY").replace(/,/g, "."); }

const MESES_ES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
                  "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"];
function mesLegible(ym) {
  if (!ym) return ym;
  const [a, m] = ym.split("-");
  return `${MESES_ES[parseInt(m)]} ${a}`;
}
function hoy() { return new Date().toISOString().slice(0, 10); }
function mesActual() { return new Date().toISOString().slice(0, 7); }
function diasHasta(fecha) {
  const ms = new Date(fecha) - new Date();
  return Math.floor(ms / (1000 * 60 * 60 * 24));
}

async function api(url, opts) {
  const r = await fetch(url, opts);
  // Sesión expirada → redirigir al login
  if (r.status === 401) {
    window.location.href = "/login";
    return {};
  }
  // Sin permiso para esta acción (solo admin puede gestionar usuarios)
  if (r.status === 403) {
    const data = await r.json().catch(() => ({}));
    toast(data.error || "No tenés permiso para esta acción", "error");
    return { ok: false, msg: data.error };
  }
  return r.json();
}
function status(msg) {
  $("#statusbar").innerHTML = `<i class="ti ti-info-circle" style="vertical-align:-2px"></i> ${msg}`;
}
function toast(msg, tipo = "") {
  const t = $("#toast");
  const icono = tipo === "success" ? "circle-check" : tipo === "error" ? "alert-circle" : "info-circle";
  t.innerHTML = `<i class="ti ti-${icono}"></i> ${msg}`;
  t.className = "toast show " + tipo;
  setTimeout(() => t.className = "toast", 2800);
}

function setCoche(v) {
  cocheActual = v;
  const box = $("#cocheBox");
  if (v) {
    $("#cocheName").textContent = v.patente;
    $("#cocheInfo").textContent = `${v.marca || ""} ${v.modelo || ""}`.trim() || "—";
    box.classList.add("has-coche");
  } else {
    $("#cocheName").textContent = "Ninguno";
    $("#cocheInfo").textContent = "Hacé clic en un vehículo";
    box.classList.remove("has-coche");
  }
  document.querySelectorAll("[data-needs-coche]").forEach(b => b.disabled = !v);
}

// ─── Navegación ─────────────────────────────────────────────────────────
document.querySelectorAll(".nav-item").forEach(btn => {
  btn.addEventListener("click", () => {
    if (btn.disabled) return;
    document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    irA(btn.dataset.sec);
    cerrarSidebar();  // en el celular, cerrar el menú al elegir una opción
  });
});

// ─── Menú lateral en celular (hamburguesa) ───
function toggleSidebar() {
  const sb = document.getElementById("sidebar");
  const ov = document.getElementById("sidebarOverlay");
  if (sb) sb.classList.toggle("abierto");
  if (ov) ov.classList.toggle("visible");
}
function cerrarSidebar() {
  const sb = document.getElementById("sidebar");
  const ov = document.getElementById("sidebarOverlay");
  if (sb) sb.classList.remove("abierto");
  if (ov) ov.classList.remove("visible");
}

function irA(sec) {
  if (["servicios", "costos", "kpis", "mantenimiento", "neumaticos"].includes(sec) && !cocheActual) {
    toast("Seleccioná un coche primero", "error");
    return;
  }
  // Volver al inicio al cambiar de pantalla
  content.scrollTop = 0;
  const map = {
    dashboard: renderDashboard,
    vehiculos: renderVehiculos,
    servicios: renderServicios,
    costos: renderCostos,
    kpis: renderKpis,
    oee: renderOEE,
    turismo: renderTurismo,
    historial: renderHistorial,
    combustible: renderCombustible,
    mantenimiento: renderMantenimiento,
    planes: renderPlanes,
    correctivos: renderCorrectivos,
    documentos: renderDocumentos,
    neumaticos: renderNeumaticos,
    inventario_neu: renderInventarioNeu,
    ots: renderOts,
    compras: renderCompras,
    repuestos: renderRepuestos,
    gerencial: renderGerencial,
    historial_carga: renderHistorialCarga,
  };
  map[sec]();
}

// ════════════════════════════════════════════════════════════════════════
//  DASHBOARD GENERAL
// ════════════════════════════════════════════════════════════════════════
async function renderDashboard() {
  status("Resumen general de la flota");
  const data = await api("/api/dashboard");
  const docs = await api("/api/documentos");

  // Combinar alertas: mantenimientos vencidos + docs próximos
  const alertas = [];
  data.vehiculos.forEach(v => {
    v.alertas.forEach(a => {
      alertas.push({
        tipo: a.estado === "vencido" ? "danger" : "warning",
        icono: a.estado === "vencido" ? "alert-circle" : "clock-hour-4",
        titulo: `${v.patente} · ${a.tarea}`,
        meta: a.estado === "vencido"
          ? `Vencido hace ${Math.abs(a.km_restantes).toLocaleString("es-PY").replace(/,/g,".")} km · ${v.plan_nombre || "Sin plan"}`
          : `Faltan ${a.km_restantes.toLocaleString("es-PY").replace(/,/g,".")} km · ${v.plan_nombre || "Sin plan"}`,
        urgente: a.estado === "vencido"
      });
    });
  });
  // Agregar alertas de documentos
  docs.forEach(d => {
    const dias = diasHasta(d.fecha_vencimiento);
    if (dias <= 30) {
      alertas.push({
        tipo: dias < 0 ? "danger" : "warning",
        icono: "file-alert",
        titulo: `${d.patente} · ${d.tipo} ${dias < 0 ? "vencido" : "vence pronto"}`,
        meta: dias < 0 ? `Hace ${Math.abs(dias)} días (${d.fecha_vencimiento})` : `En ${dias} días (${d.fecha_vencimiento})`,
        urgente: dias < 0
      });
    }
  });
  // Ordenar: urgentes primero
  alertas.sort((a, b) => (b.urgente ? 1 : 0) - (a.urgente ? 1 : 0));

  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-layout-dashboard"></i> Dashboard</h1>
      <p>Resumen general de la flota La Santaniana</p>
    </div>
    <div class="section">

      <div class="metrics">
        <div class="metric">
          <div class="metric-icon blue"><i class="ti ti-bus"></i></div>
          <div class="metric-content">
            <div class="metric-label">Vehículos activos</div>
            <div class="metric-value">${data.vehiculos_activos}</div>
          </div>
        </div>
        <div class="metric ${data.mant_vencidos > 0 ? 'danger' : ''}">
          <div class="metric-icon red"><i class="ti ti-alert-circle"></i></div>
          <div class="metric-content">
            <div class="metric-label">Mantenimientos vencidos</div>
            <div class="metric-value">${data.mant_vencidos}</div>
          </div>
        </div>
        <div class="metric ${data.mant_proximos > 0 ? 'warning' : ''}">
          <div class="metric-icon amber"><i class="ti ti-clock-hour-4"></i></div>
          <div class="metric-content">
            <div class="metric-label">Próximos vencimientos</div>
            <div class="metric-value">${data.mant_proximos}</div>
          </div>
        </div>
        <div class="metric ${data.docs_proximos > 0 ? 'warning' : ''}">
          <div class="metric-icon amber"><i class="ti ti-file-text"></i></div>
          <div class="metric-content">
            <div class="metric-label">Documentos por vencer</div>
            <div class="metric-value">${data.docs_proximos}</div>
          </div>
        </div>
        <div class="metric ${data.correctivos_pendientes > 0 ? 'warning' : ''}">
          <div class="metric-icon red"><i class="ti ti-tool"></i></div>
          <div class="metric-content">
            <div class="metric-label">Correctivos pendientes</div>
            <div class="metric-value">${data.correctivos_pendientes}</div>
          </div>
        </div>
      </div>

      ${alertas.length ? `
        <div class="section-title"><i class="ti ti-bell"></i> Alertas críticas (${alertas.length})</div>
        ${alertas.slice(0, 8).map(a => `
          <div class="dash-alert ${a.tipo}">
            <i class="ti ti-${a.icono}"></i>
            <div class="dash-alert-text">
              <div class="dash-alert-title">${a.titulo}</div>
              <div class="dash-alert-meta">${a.meta}</div>
            </div>
            ${a.urgente ? `<span class="badge danger"><span class="dot"></span> Urgente</span>` : ''}
          </div>
        `).join("")}
        ${alertas.length > 8 ? `<p class="hint" style="margin-top:10px"><i class="ti ti-info-circle"></i> Y ${alertas.length - 8} alerta(s) más. Revisá las pantallas de Mantenimiento y Documentos.</p>` : ''}
      ` : `
        <div class="card" style="border-color:var(--success-bd);background:linear-gradient(135deg, var(--success-bg) 0%, var(--surface) 100%)">
          <div class="card-body" style="text-align:center;padding:36px 24px">
            <div style="display:inline-grid;place-items:center;width:60px;height:60px;border-radius:50%;background:var(--success);box-shadow:0 4px 14px rgba(22,163,74,0.3);margin-bottom:14px">
              <i class="ti ti-check" style="font-size:32px;color:white"></i>
            </div>
            <h3 style="font-size:18px;font-weight:700;margin-bottom:4px">¡Todo en orden!</h3>
            <p class="hint" style="justify-content:center;color:var(--muted);font-size:13.5px">No hay alertas críticas en la flota</p>
          </div>
        </div>
      `}

      <div class="section-title"><i class="ti ti-list"></i> Estado por vehículo</div>
      ${window.USUARIO_ROL === 'admin' && data.vehiculos.length > 0 && data.vehiculos.length < 89 ? `
        <div class="card" style="border-color:var(--warning-bd);background:var(--warning-bg);margin-bottom:14px">
          <div class="card-body" style="display:flex;align-items:center;gap:14px;flex-wrap:wrap">
            <i class="ti ti-alert-triangle" style="font-size:24px;color:var(--warning)"></i>
            <div style="flex:1;min-width:200px">
              <div style="font-weight:600;font-size:14px">La carga quedó incompleta (${data.vehiculos.length} de 89 vehículos)</div>
              <div style="font-size:12.5px;color:var(--muted);margin-top:2px">Tocá el botón para continuar la carga desde donde quedó. No duplica los que ya están.</div>
            </div>
            <button class="btn btn-primary" onclick="cargarFlotaInicial()">
              <i class="ti ti-database-import"></i> Continuar carga
            </button>
          </div>
        </div>
      ` : ''}
      ${data.vehiculos.length === 0 ? `
        <div class="empty">
          <i class="ti ti-bus"></i>
          Aún no tenés vehículos cargados.<br>
          Ir a <b>Vehículos</b> para agregar el primero.
          ${window.USUARIO_ROL === 'admin' ? `
            <div style="margin-top:18px">
              <button class="btn btn-primary" onclick="cargarFlotaInicial()">
                <i class="ti ti-database-import"></i> Cargar flota completa desde Excel
              </button>
              <p style="font-size:11.5px;color:var(--muted);margin-top:8px">
                Solo si subiste el archivo Excel al servidor. Carga los 89 vehículos + documentos.
              </p>
            </div>
          ` : ''}
        </div>
      ` : `
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Patente</th><th>N° interno</th><th>Marca / Modelo</th><th>Motor / Plan</th>
                <th class="num">KM actual</th><th class="center">Estado</th>
              </tr>
            </thead>
            <tbody>
              ${data.vehiculos.map(v => `
                <tr class="clickable" onclick="seleccionarYIr(${v.id}, 'mantenimiento')">
                  <td><b>${v.patente}</b></td>
                  <td>${v.n_interno ? `<span class="badge cat">${v.n_interno}</span>` : "—"}</td>
                  <td>${v.marca || "—"} ${v.modelo || ""}</td>
                  <td>${v.plan_nombre ? `<span class="badge cat">${v.plan_nombre}</span>` : `<span class="badge">Sin plan</span>`}</td>
                  <td class="num">${fmtNum(v.km_actual)}</td>
                  <td class="center">
                    ${v.estado_general === "vencido" ? `<span class="badge danger"><span class="dot"></span> ${v.vencidos} vencidas</span>` : ""}
                    ${v.estado_general === "pronto" ? `<span class="badge warning"><span class="dot"></span> ${v.pronto} próximas</span>` : ""}
                    ${v.estado_general === "ok" ? `<span class="badge success"><span class="dot"></span> Al día</span>` : ""}
                    ${v.estado_general === "sin_plan" ? `<span class="badge">Sin plan</span>` : ""}
                  </td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      `}

    </div>`;
}

async function seleccionarYIr(vid, sec) {
  const vs = await api("/api/vehiculos");
  const v = vs.find(x => x.id === vid);
  if (v) {
    setCoche(v);
    document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
    document.querySelector(`.nav-item[data-sec="${sec}"]`)?.classList.add("active");
    irA(sec);
  }
}

// ════════════════════════════════════════════════════════════════════════
//  VEHÍCULOS
// ════════════════════════════════════════════════════════════════════════
async function renderVehiculos() {
  status("Hacé clic en un coche para seleccionarlo.");
  const planes = await api("/api/planes");
  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-bus"></i> Vehículos</h1>
      <p>Gestión de la flota — datos completos de cada coche</p>
    </div>
    <div class="section">
      <div class="card">
        <div class="card-head"><i class="ti ti-plus"></i> Nuevo vehículo</div>
        <div class="card-body">
          <div class="form-row">
            <div class="field"><label>Patente *</label><input id="v-pat" placeholder="ABC-123" style="width:120px"></div>
            <div class="field"><label>N° interno</label><input id="v-int" placeholder="21200" style="width:100px"></div>
            <div class="field"><label>Tipo</label>
              <select id="v-tipo" style="width:130px">
                <option value="">—</option>
                <option value="Omnibus">Ómnibus</option>
                <option value="Minibus">Minibús</option>
                <option value="Camioneta">Camioneta</option>
              </select>
            </div>
            <div class="field"><label>Marca</label><input id="v-mar" placeholder="Scania" style="width:130px"></div>
            <div class="field"><label>Modelo carrocería</label><input id="v-mod" placeholder="Marcopolo DD" style="width:170px"></div>
            <div class="field"><label>Año</label><input id="v-año" placeholder="2012" style="width:90px"></div>
          </div>
          <div class="form-row" style="margin-top:14px">
            <div class="field" style="flex:1;min-width:280px"><label>Chasis (VIN)</label><input id="v-cha" placeholder="9BSK6X200C3686985"></div>
            <div class="field"><label>Asientos</label><input id="v-asi" placeholder="42" style="width:100px"></div>
            <div class="field"><label>Ejes</label><input id="v-eje" placeholder="3" style="width:80px"></div>
          </div>
          <div class="form-row" style="margin-top:14px">
            <div class="field" style="flex:1;min-width:300px">
              <label>Motor / chasis (asigna plan automáticamente)</label>
              <select id="v-plan">
                <option value="">— Sin plan, asignar después —</option>
                ${planes.map(p => `<option value="${p.id}">${p.nombre}</option>`).join("")}
              </select>
            </div>
            <div class="field"><label>KM actual del odómetro</label><input id="v-km" placeholder="0" style="width:140px"></div>
            <button class="btn btn-primary" onclick="guardarVehiculo()"><i class="ti ti-plus"></i> Agregar</button>
          </div>
          <p class="hint" style="margin-top:14px">
            <i class="ti ti-bulb"></i>
            Tip: elegí el motor/chasis y el plan de mantenimiento se asigna solo. Los km del coche van a ir sumándose con cada servicio que cargues.
          </p>
        </div>
      </div>

      <div class="section-title"><i class="ti ti-list"></i> Flota registrada</div>
      <div class="table-wrap">
        <table>
          <thead><tr>
            <th>Patente</th><th>N° int.</th><th>Tipo</th><th>Marca</th><th>Carrocería</th>
            <th class="center">Año</th><th class="center">Asientos</th><th class="center">Ejes</th>
            <th>Plan asignado</th><th class="num">KM actual</th><th class="td-action"></th>
          </tr></thead>
          <tbody id="v-body"></tbody>
        </table>
      </div>
    </div>`;
  cargarVehiculos();
}

async function cargarVehiculos() {
  const vs = await api("/api/vehiculos");
  const body = $("#v-body");
  if (!vs.length) {
    body.innerHTML = `<tr><td colspan="11" class="empty"><i class="ti ti-bus"></i>Sin vehículos. Agregá el primero arriba.</td></tr>`;
    return;
  }
  const filas = await Promise.all(vs.map(async v => {
    const info = await api(`/api/vehiculos/${v.id}/plan`);
    return { v, plan: info.plan, km: info.km_actual };
  }));
  body.innerHTML = filas.map(({v, plan, km}) => `
    <tr class="clickable ${cocheActual && cocheActual.id === v.id ? 'selected' : ''}" data-id="${v.id}" onclick="seleccionarCoche(${v.id})">
      <td><b>${v.patente}</b></td>
      <td>${v.n_interno || "—"}</td>
      <td>${v.tipo ? `<span class="badge">${v.tipo}</span>` : "—"}</td>
      <td>${v.marca || "—"}</td>
      <td title="${v.chasis || ''}">${v.modelo || "—"}</td>
      <td class="center">${v.año || "—"}</td>
      <td class="center">${v.asientos || "—"}</td>
      <td class="center">${v.ejes || "—"}</td>
      <td>${plan ? `<span class="badge cat">${plan.plan_nombre}</span>` : `<span class="badge">Sin plan</span>`}</td>
      <td class="num">${fmtNum(km)}</td>
      <td class="td-action">
        <button class="icon-btn" onclick="event.stopPropagation();editarVehiculo(${v.id})" title="Editar"><i class="ti ti-edit"></i></button>
        <button class="icon-btn" onclick="event.stopPropagation();bajaVehiculo(${v.id},'${v.patente}')" title="Dar de baja"><i class="ti ti-trash"></i></button>
      </td>
    </tr>`).join("");
  window._vehiculos = vs;
}

function seleccionarCoche(id) {
  const v = window._vehiculos.find(x => x.id === id);
  setCoche(v);
  document.querySelectorAll("#v-body tr").forEach(tr => tr.classList.remove("selected"));
  $(`#v-body tr[data-id="${id}"]`)?.classList.add("selected");
  status(`✓ Coche ${v.patente} seleccionado.`);
  toast(`Seleccionado: ${v.patente}`, "success");
}

async function guardarVehiculo() {
  const pat = $("#v-pat").value.trim();
  if (!pat) { toast("La patente es obligatoria", "error"); return; }
  const r = await api("/api/vehiculos", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      patente: pat,
      marca: $("#v-mar").value.trim(),
      modelo: $("#v-mod").value.trim(),
      año: $("#v-año").value.trim(),
      chasis: $("#v-cha").value.trim(),
      n_interno: $("#v-int").value.trim(),
      asientos: $("#v-asi").value.trim() || 0,
      ejes: $("#v-eje").value.trim() || 0,
      tipo: $("#v-tipo").value,
      plan_id: $("#v-plan").value || null,
      km_inicial: parseFloat($("#v-km").value || 0)
    })
  });
  if (r.ok) {
    toast("Vehículo agregado", "success");
    ["v-pat", "v-int", "v-mar", "v-mod", "v-año", "v-cha", "v-asi", "v-eje", "v-km"].forEach(id => $("#" + id).value = "");
    $("#v-plan").value = ""; $("#v-tipo").value = "";
    cargarVehiculos();
  } else toast(r.msg, "error");
}

async function editarVehiculo(vid) {
  const v = window._vehiculos.find(x => x.id === vid);
  if (!v) return;
  abrirModalEditarVehiculo(v);
}

function abrirModalEditarVehiculo(v) {
  // Modal flotante con todos los campos editables
  const overlay = document.createElement("div");
  overlay.id = "modal-edit-veh";
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(15,23,42,0.55);z-index:999;display:grid;place-items:center;padding:20px";
  overlay.innerHTML = `
    <div style="background:var(--surface);border-radius:var(--radius);box-shadow:var(--shadow-lg);max-width:640px;width:100%;max-height:90vh;overflow:auto">
      <div style="padding:18px 22px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">
        <h3 style="font-size:16px;font-weight:600;display:flex;align-items:center;gap:8px"><i class="ti ti-edit" style="color:var(--brand-blue)"></i> Editar vehículo · ${v.patente}</h3>
        <button class="icon-btn" onclick="cerrarModalEditarVehiculo()"><i class="ti ti-x"></i></button>
      </div>
      <div style="padding:22px">
        <div class="form-row">
          <div class="field"><label>Patente</label><input id="ev-pat" value="${v.patente || ''}" style="width:140px"></div>
          <div class="field"><label>N° interno</label><input id="ev-int" value="${v.n_interno || ''}" style="width:120px"></div>
          <div class="field"><label>Tipo</label>
            <select id="ev-tipo" style="width:140px">
              <option value="">—</option>
              <option value="Omnibus" ${v.tipo==='Omnibus'?'selected':''}>Ómnibus</option>
              <option value="Minibus" ${v.tipo==='Minibus'?'selected':''}>Minibús</option>
              <option value="Camioneta" ${v.tipo==='Camioneta'?'selected':''}>Camioneta</option>
            </select>
          </div>
        </div>
        <div class="form-row" style="margin-top:14px">
          <div class="field"><label>Marca</label><input id="ev-mar" value="${v.marca || ''}" style="width:160px"></div>
          <div class="field" style="flex:1;min-width:240px"><label>Modelo carrocería</label><input id="ev-mod" value="${v.modelo || ''}"></div>
          <div class="field"><label>Año</label><input id="ev-año" value="${v.año || ''}" style="width:90px"></div>
        </div>
        <div class="form-row" style="margin-top:14px">
          <div class="field" style="flex:1"><label>Chasis (VIN)</label><input id="ev-cha" value="${v.chasis || ''}"></div>
          <div class="field"><label>Asientos</label><input id="ev-asi" value="${v.asientos || ''}" style="width:100px"></div>
          <div class="field"><label>Ejes</label><input id="ev-eje" value="${v.ejes || ''}" style="width:80px"></div>
        </div>
        <div class="form-row" style="margin-top:14px">
          <div class="field"><label><i class="ti ti-clock"></i> Horario de salida</label>
            <input id="ev-horario" type="time" value="${v.horario_salida || ''}" style="width:140px">
            <div style="font-size:11px;color:var(--muted);margin-top:4px">Hora fija de salida del coche. Sirve para priorizar las OTs.</div>
          </div>
          <div class="field"><label><i class="ti ti-gas-station"></i> Consumo (km/litro)</label>
            <input id="ev-consumo" type="number" step="0.1" value="${v.consumo_km_litro || ''}" placeholder="2.5" style="width:140px">
            <div style="font-size:11px;color:var(--muted);margin-top:4px">Rendimiento de combustible. Sirve para presupuestos de turismo.</div>
          </div>
        </div>
        <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:22px;padding-top:18px;border-top:1px solid var(--border)">
          <button class="btn btn-ghost" onclick="cerrarModalEditarVehiculo()">Cancelar</button>
          <button class="btn btn-primary" onclick="guardarEdicionVehiculo(${v.id})"><i class="ti ti-device-floppy"></i> Guardar cambios</button>
        </div>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.addEventListener("click", (e) => { if (e.target === overlay) cerrarModalEditarVehiculo(); });
}

function cerrarModalEditarVehiculo() {
  const m = document.getElementById("modal-edit-veh");
  if (m) m.remove();
}

async function guardarEdicionVehiculo(vid) {
  const r = await api(`/api/vehiculos/${vid}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      patente: $("#ev-pat").value.trim(),
      n_interno: $("#ev-int").value.trim(),
      tipo: $("#ev-tipo").value,
      marca: $("#ev-mar").value.trim(),
      modelo: $("#ev-mod").value.trim(),
      año: $("#ev-año").value.trim() || null,
      chasis: $("#ev-cha").value.trim(),
      asientos: $("#ev-asi").value.trim() || 0,
      ejes: $("#ev-eje").value.trim() || 0,
    })
  });
  if (r.ok) {
    // Guardar también el horario de salida (campo aparte)
    const horario = $("#ev-horario").value;
    await api(`/api/vehiculos/${vid}/horario_salida`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ horario })
    });
    // Guardar el consumo (km/litro)
    const consumo = $("#ev-consumo").value;
    await api(`/api/vehiculos/${vid}/consumo`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ consumo_km_litro: consumo })
    });
    toast("Vehículo actualizado", "success");
    cerrarModalEditarVehiculo();
    cargarVehiculos();
  } else toast(r.msg || "Error", "error");
}

async function bajaVehiculo(id, pat) {
  if (!confirm(`¿Dar de baja el coche ${pat}?`)) return;
  await api(`/api/vehiculos/${id}`, { method: "DELETE" });
  if (cocheActual && cocheActual.id === id) setCoche(null);
  toast("Vehículo dado de baja");
  cargarVehiculos();
}

// ════════════════════════════════════════════════════════════════════════
//  SERVICIOS
// ════════════════════════════════════════════════════════════════════════
async function renderServicios() {
  const v = cocheActual;
  status(`Servicios del coche ${v.patente}`);
  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-clipboard-list"></i> Servicios · ${v.patente}</h1>
      <p>${v.marca} ${v.modelo} — cargá y administrá los servicios de este coche</p>
    </div>
    <div class="section">
      <div class="card">
        <div class="card-head"><i class="ti ti-plus"></i> Cargar nuevo servicio</div>
        <div class="card-body">
          <div class="form-row">
            <div class="field"><label>Fecha</label><input id="s-fecha" type="date" value="${hoy()}"></div>
            <div class="field"><label>KM recorridos</label><input id="s-km" placeholder="900" style="width:120px"></div>
            <div class="field"><label>Horas</label><input id="s-hs" placeholder="48" style="width:90px"></div>
            <div class="field"><label>Ingreso (Gs.)</label><input id="s-ing" placeholder="7000000" style="width:150px"></div>
            <div class="field" style="flex:1;min-width:200px"><label>Descripción</label><input id="s-desc" placeholder="Recorrido..."></div>
            <button class="btn btn-primary" onclick="guardarServicio()"><i class="ti ti-device-floppy"></i> Guardar</button>
          </div>
        </div>
      </div>
      <div class="toolbar">
        <label style="font-size:12px;color:var(--muted);font-weight:600;text-transform:uppercase">Ver mes:</label>
        <select id="s-mes" onchange="cargarServicios()" style="padding:8px 12px;border:1px solid var(--border);border-radius:8px;font-size:13px"></select>
        <span class="resumen-tag" id="s-resumen"></span>
      </div>
      <div class="table-wrap">
        <table>
          <thead><tr>
            <th>Fecha</th><th class="num">KM</th><th class="num">Horas</th>
            <th class="num">Ingreso</th><th>Descripción</th><th class="td-action"></th>
          </tr></thead>
          <tbody id="s-body"></tbody>
        </table>
      </div>
    </div>`;
  await cargarMesesServicios();
  cargarServicios();
}

async function cargarMesesServicios() {
  const meses = await api(`/api/meses/${cocheActual.id}`);
  $("#s-mes").innerHTML = `<option value="todos">Todos los meses</option>` +
    meses.map(m => `<option value="${m}">${mesLegible(m)}</option>`).join("");
}

async function cargarServicios() {
  const mes = $("#s-mes").value;
  const servicios = await api(`/api/servicios/${cocheActual.id}?mes=${mes}`);
  const body = $("#s-body");
  if (!servicios.length) {
    body.innerHTML = `<tr><td colspan="6" class="empty"><i class="ti ti-clipboard-off"></i>Sin servicios en este período</td></tr>`;
    $("#s-resumen").textContent = "";
    return;
  }
  let totIng = 0, totKm = 0;
  body.innerHTML = servicios.map(s => {
    totIng += s.ingreso; totKm += s.km;
    return `<tr>
      <td>${s.fecha}</td><td class="num">${fmtNum(s.km)}</td>
      <td class="num">${s.horas}</td><td class="num">${gs(s.ingreso)}</td>
      <td>${s.descripcion || "—"}</td>
      <td class="td-action"><button class="icon-btn" onclick="borrarServicio(${s.id},'${s.fecha}')"><i class="ti ti-trash"></i></button></td>
    </tr>`;
  }).join("");
  $("#s-resumen").innerHTML = `<i class="ti ti-calculator" style="vertical-align:-2px"></i> <b>${servicios.length}</b> servicios · <b>${fmtNum(totKm)}</b> km · <b>${gs(totIng)}</b>`;
}

async function guardarServicio() {
  const ing = $("#s-ing").value.replace(/\./g, "").replace(/,/g, ".");
  const r = await api("/api/servicios", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      vehiculo_id: cocheActual.id, fecha: $("#s-fecha").value,
      km: $("#s-km").value || 0, horas: $("#s-hs").value || 0,
      ingreso: ing || 0, descripcion: $("#s-desc").value
    })
  });
  if (r.ok) {
    toast("Servicio cargado", "success");
    ["s-km", "s-hs", "s-ing", "s-desc"].forEach(id => $("#" + id).value = "");
    await cargarMesesServicios();
    cargarServicios();
  } else toast("Error al guardar", "error");
}

async function borrarServicio(id, fecha) {
  if (!confirm(`¿Eliminar el servicio del ${fecha}?`)) return;
  await api(`/api/servicios/${id}`, { method: "DELETE" });
  toast("Servicio eliminado");
  await cargarMesesServicios();
  cargarServicios();
}

// ════════════════════════════════════════════════════════════════════════
//  COSTOS
// ════════════════════════════════════════════════════════════════════════
async function renderCostos() {
  const v = cocheActual;
  status(`Costos del coche ${v.patente}`);
  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-coin"></i> Costos · ${v.patente}</h1>
      <p>Registro de costos variables, fijos directos e indirectos</p>
    </div>
    <div class="section">
      <div class="card">
        <div class="card-head"><i class="ti ti-plus"></i> Cargar costo</div>
        <div class="card-body">
          <div class="form-row">
            <div class="field"><label>Mes</label><input id="c-mes" type="month" value="${mesActual()}"></div>
            <div class="field"><label>Tipo</label>
              <select id="c-tipo">
                <option value="variable">Variable</option>
                <option value="fijo_directo">Fijo Directo</option>
                <option value="fijo_indirecto">Fijo Indirecto</option>
              </select>
            </div>
            <div class="field" style="flex:1;min-width:200px"><label>Concepto</label><input id="c-con" placeholder="Combustible"></div>
            <div class="field"><label>Monto (Gs.)</label><input id="c-mon" placeholder="22000000" style="width:160px"></div>
            <button class="btn btn-primary" onclick="guardarCosto()"><i class="ti ti-plus"></i> Agregar</button>
          </div>
        </div>
      </div>
      <div class="section-title"><i class="ti ti-list"></i> Costos cargados</div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Mes</th><th>Tipo</th><th>Concepto</th><th class="num">Monto</th><th class="td-action"></th></tr></thead>
          <tbody id="c-body"></tbody>
        </table>
      </div>
    </div>`;
  cargarCostos();
}
const NOMBRE_TIPO = { variable: "Variable", fijo_directo: "Fijo Directo", fijo_indirecto: "Fijo Indirecto" };
async function cargarCostos() {
  const costos = await api(`/api/costos/${cocheActual.id}`);
  const body = $("#c-body");
  if (!costos.length) {
    body.innerHTML = `<tr><td colspan="5" class="empty"><i class="ti ti-coin-off"></i>Sin costos cargados</td></tr>`;
    return;
  }
  body.innerHTML = costos.map(c => `
    <tr><td>${c.mes}</td><td><span class="badge">${NOMBRE_TIPO[c.tipo] || c.tipo}</span></td>
    <td>${c.concepto}</td><td class="num">${gs(c.monto)}</td>
    <td class="td-action"><button class="icon-btn" onclick="borrarCosto(${c.id})"><i class="ti ti-trash"></i></button></td></tr>`).join("");
}
async function guardarCosto() {
  const con = $("#c-con").value.trim();
  if (!con) { toast("Ingresá un concepto", "error"); return; }
  const mon = $("#c-mon").value.replace(/\./g, "").replace(/,/g, ".");
  const r = await api("/api/costos", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      vehiculo_id: cocheActual.id, mes: $("#c-mes").value,
      tipo: $("#c-tipo").value, concepto: con, monto: mon || 0
    })
  });
  if (r.ok) { toast("Costo agregado", "success"); $("#c-con").value = ""; $("#c-mon").value = ""; cargarCostos(); }
  else toast("Error al guardar", "error");
}
async function borrarCosto(id) {
  if (!confirm("¿Eliminar este costo?")) return;
  await api(`/api/costos/${id}`, { method: "DELETE" });
  toast("Costo eliminado");
  cargarCostos();
}

// ════════════════════════════════════════════════════════════════════════
//  KPIs
// ════════════════════════════════════════════════════════════════════════
// ─── OEE de Flota ───
function _colorOEE(pct) {
  if (pct >= 70) return "var(--success)";
  if (pct >= 50) return "var(--warning)";
  return "var(--danger)";
}

// ═══════════════ PRESUPUESTOS DE TURISMO ═══════════════
let turismoTab = "nuevo";

// ═══════════════ HISTORIAL DE AUDITORÍA (solo admin) ═══════════════
let histFiltros = { desde: "", hasta: "", categoria: "", usuario: "" };

const ICONO_CAT = {
  "Acceso": "ti-login", "Órdenes de Trabajo": "ti-clipboard-check", "Compras": "ti-shopping-cart",
  "Turismo": "ti-bus-stop", "Usuarios": "ti-users", "Vehículos": "ti-car",
  "Reportes de chofer": "ti-message-report",
};
const COLOR_CAT = {
  "Acceso": "#6366f1", "Órdenes de Trabajo": "#2563eb", "Compras": "#d97706",
  "Turismo": "#0891b2", "Usuarios": "#dc2626", "Vehículos": "#059669",
  "Reportes de chofer": "#7c3aed",
};

// ═══════════════ COMBUSTIBLE (cargas + rendimiento) ═══════════════
let combTab = "cargar";

async function renderCombustible() {
  status("Control de combustible");
  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-gas-station"></i> Combustible</h1>
      <p>Registro de cargas y rendimiento real de la flota</p>
    </div>
    <div class="section">
      <div class="toolbar">
        <div class="tabs">
          <button class="tab-btn ${combTab==='cargar'?'active':''}" onclick="setCombTab('cargar')"><i class="ti ti-plus"></i> Cargar / Historial</button>
          <button class="tab-btn ${combTab==='rendimiento'?'active':''}" onclick="setCombTab('rendimiento')"><i class="ti ti-gauge"></i> Rendimiento por bus</button>
        </div>
      </div>
      <div id="comb-contenido"></div>
    </div>`;
  if (combTab === "cargar") await renderCombCargar();
  else await renderCombRendimiento();
}

function setCombTab(t) { combTab = t; renderCombustible(); }

async function renderCombCargar() {
  const cont = document.getElementById("comb-contenido");
  const vehiculos = await api("/api/vehiculos");
  const data = await api("/api/combustible");
  const cargas = data.cargas || [];
  const stats = data.stats || {};

  cont.innerHTML = `
    <!-- Resumen -->
    <div class="metrics" style="margin-bottom:18px">
      <div class="metric"><div class="metric-content"><div class="metric-label">Total de cargas</div>
        <div class="metric-value">${stats.total_cargas || 0}</div></div></div>
      <div class="metric"><div class="metric-content"><div class="metric-label">Litros cargados</div>
        <div class="metric-value" style="color:var(--brand-blue)">${fmtNum(stats.total_litros || 0)}</div></div></div>
      <div class="metric"><div class="metric-content"><div class="metric-label">Gasto total</div>
        <div class="metric-value" style="color:#d97706">${gs(stats.total_gasto || 0)}</div></div></div>
    </div>

    <!-- Formulario de carga -->
    <div class="card">
      <div class="card-head"><i class="ti ti-plus"></i> Registrar carga de combustible</div>
      <div class="card-body">
        <div class="form-row">
          <div class="field" style="min-width:220px"><label>Vehículo *</label>
            <select id="cm-veh">
              <option value="">Elegir bus...</option>
              ${vehiculos.map(v => `<option value="${v.id}">${v.patente} — ${v.marca} ${v.modelo}${v.n_interno ? ' (Coche ' + v.n_interno + ')' : ''}</option>`).join("")}
            </select>
          </div>
          <div class="field"><label>Fecha *</label><input id="cm-fecha" type="date" value="${hoy()}"></div>
          <div class="field"><label>Odómetro (km) *</label><input id="cm-odo" type="number" placeholder="458200"></div>
        </div>
        <div class="form-row" style="margin-top:14px">
          <div class="field"><label>Litros *</label><input id="cm-litros" type="number" step="0.1" placeholder="400" oninput="calcCostoComb()"></div>
          <div class="field"><label>Precio por litro</label><input id="cm-precio" type="number" placeholder="7500" oninput="calcCostoComb()"></div>
          <div class="field"><label>Costo total</label><input id="cm-costo" type="number" placeholder="(se calcula solo)"></div>
          <div class="field"><label>Surtidor / Estación</label><input id="cm-estacion" placeholder="Petropar Ruta 2"></div>
        </div>
        <div class="form-row" style="margin-top:14px">
          <div class="field"><label>Chofer</label><input id="cm-chofer" placeholder="Nombre del chofer"></div>
          <div class="field" style="flex:1"><label>Observaciones</label><input id="cm-obs" placeholder="Opcional"></div>
          <button class="btn btn-primary" style="align-self:flex-end" onclick="guardarCargaComb()"><i class="ti ti-device-floppy"></i> Registrar carga</button>
        </div>
      </div>
    </div>

    <!-- Lista de cargas -->
    <div class="section-title"><i class="ti ti-list"></i> Cargas registradas (${cargas.length})</div>
    ${cargas.length === 0 ? `
      <div class="empty"><i class="ti ti-gas-station-off"></i>No hay cargas registradas todavía.</div>
    ` : `
      <div class="table-wrap"><table>
        <thead><tr>
          <th>Fecha</th><th>Vehículo</th><th class="num">Odómetro</th><th class="num">Litros</th>
          <th class="num">Precio/L</th><th class="num">Costo</th><th class="num">Rendimiento</th><th class="td-action"></th>
        </tr></thead>
        <tbody>
          ${cargas.map(c => {
            const coche = c.n_interno ? `${c.patente} (${c.n_interno})` : c.patente;
            const rend = c.rendimiento != null
              ? `<span style="font-weight:700;color:${c.rendimiento >= 2.5 ? '#059669' : c.rendimiento >= 2 ? '#d97706' : '#dc2626'}">${c.rendimiento} km/l</span>`
              : `<span style="color:var(--muted);font-size:12px">primera carga</span>`;
            return `<tr>
              <td>${c.fecha}</td>
              <td><b>${coche}</b></td>
              <td class="num">${fmtNum(c.odometro)}</td>
              <td class="num">${c.litros} L</td>
              <td class="num">${gs(c.precio_litro)}</td>
              <td class="num">${gs(c.costo_total)}</td>
              <td class="num">${rend}</td>
              <td class="td-action"><button class="icon-btn" onclick="borrarCargaComb(${c.id})"><i class="ti ti-trash"></i></button></td>
            </tr>`;
          }).join("")}
        </tbody>
      </table></div>
    `}`;
}

// Calcula el costo total en vivo (litros x precio)
function calcCostoComb() {
  const litros = parseFloat($("#cm-litros").value) || 0;
  const precio = parseFloat($("#cm-precio").value) || 0;
  if (litros > 0 && precio > 0) {
    $("#cm-costo").value = Math.round(litros * precio);
  }
}

async function guardarCargaComb() {
  const datos = {
    vehiculo_id: $("#cm-veh").value,
    fecha: $("#cm-fecha").value,
    odometro: $("#cm-odo").value,
    litros: $("#cm-litros").value,
    precio_litro: $("#cm-precio").value,
    costo_total: $("#cm-costo").value,
    estacion: $("#cm-estacion").value,
    chofer: $("#cm-chofer").value,
    observaciones: $("#cm-obs").value,
  };
  if (!datos.vehiculo_id) { toast("Elegí el vehículo", "error"); return; }
  if (!datos.litros || parseFloat(datos.litros) <= 0) { toast("Cargá los litros", "error"); return; }
  if (!datos.odometro || parseFloat(datos.odometro) <= 0) { toast("Cargá el odómetro", "error"); return; }
  const r = await api("/api/combustible", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(datos)
  });
  if (r.ok) { toast("Carga registrada", "success"); renderCombustible(); }
  else toast(r.msg || "Error", "error");
}

async function borrarCargaComb(id) {
  if (!confirm("¿Eliminar esta carga de combustible?")) return;
  await api(`/api/combustible/${id}`, { method: "DELETE" });
  toast("Carga eliminada");
  renderCombustible();
}

// Ranking de rendimiento por bus
async function renderCombRendimiento() {
  const cont = document.getElementById("comb-contenido");
  const data = await api("/api/combustible");
  const ranking = (data.stats && data.stats.ranking) || [];
  const conRend = ranking.filter(v => v.rendimiento_prom != null);

  cont.innerHTML = `
    <p style="font-size:13px;color:var(--muted);margin-bottom:16px">
      Rendimiento promedio de cada bus (km por litro), ordenado del que <b>más gasta</b> (⚠️ arriba) al <b>más eficiente</b> (🥇 abajo). Revisá los que tienen rendimiento bajo.
    </p>
    ${conRend.length === 0 ? `
      <div class="empty"><i class="ti ti-gauge"></i>Todavía no hay suficientes cargas para calcular el rendimiento.<br>
      Hacen falta al menos 2 cargas por vehículo.</div>
    ` : `
      <div class="table-wrap"><table>
        <thead><tr>
          <th>#</th><th>Vehículo</th><th class="num">Rendimiento</th><th class="num">Litros totales</th>
          <th class="num">Gasto total</th><th class="center">Cargas</th>
        </tr></thead>
        <tbody>
          ${conRend.map((v, i) => {
            const coche = v.n_interno ? `${v.patente} (Coche ${v.n_interno})` : v.patente;
            const color = v.rendimiento_prom >= 2.5 ? '#059669' : v.rendimiento_prom >= 2 ? '#d97706' : '#dc2626';
            // El ranking va de menor a mayor rendimiento: el ÚLTIMO es el más eficiente (oro),
            // el PRIMERO es el que más gasta (alerta).
            const medalla = i === conRend.length - 1 ? '🥇' : i === 0 ? '⚠️' : `${i + 1}`;
            return `<tr>
              <td><b>${medalla}</b></td>
              <td><b>${coche}</b></td>
              <td class="num"><span style="font-weight:700;color:${color};font-size:15px">${v.rendimiento_prom} km/l</span></td>
              <td class="num">${fmtNum(v.litros)} L</td>
              <td class="num">${gs(v.gasto)}</td>
              <td class="center">${v.cargas}</td>
            </tr>`;
          }).join("")}
        </tbody>
      </table></div>
      <div style="margin-top:14px;padding:12px;background:#f0fdf4;border-radius:9px;font-size:13px;color:#166534">
        <i class="ti ti-bulb"></i> El rendimiento de cada bus se usa automáticamente en los presupuestos de Turismo.
      </div>
    `}`;
}

async function renderHistorial() {
  status("Historial de actividad");
  const params = new URLSearchParams();
  if (histFiltros.desde) params.set("desde", histFiltros.desde);
  if (histFiltros.hasta) params.set("hasta", histFiltros.hasta);
  if (histFiltros.categoria) params.set("categoria", histFiltros.categoria);
  if (histFiltros.usuario) params.set("usuario", histFiltros.usuario);
  const data = await api("/api/auditoria?" + params.toString());
  const registros = data.registros || [];
  const stats = data.stats || {};

  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-history"></i> Historial de actividad</h1>
      <p>Todo lo que pasa en el sistema — solo visible para administración</p>
    </div>
    <div class="section">
      <!-- Resumen -->
      <div class="metrics" style="margin-bottom:18px">
        <div class="metric"><div class="metric-content"><div class="metric-label">Total de acciones</div>
          <div class="metric-value">${stats.total || 0}</div></div></div>
        ${(stats.por_categoria || []).slice(0, 3).map(c => `
          <div class="metric"><div class="metric-content"><div class="metric-label">${c.categoria || "Sin categoría"}</div>
          <div class="metric-value" style="color:${COLOR_CAT[c.categoria]||'#64748b'}">${c.n}</div></div></div>
        `).join("")}
      </div>

      <!-- Filtros -->
      <div class="toolbar" style="gap:10px;flex-wrap:wrap;margin-bottom:16px">
        <div class="field" style="margin:0"><label style="font-size:11px">Desde</label>
          <input type="date" id="hist-desde" value="${histFiltros.desde}" onchange="aplicarFiltrosHist()" style="width:150px"></div>
        <div class="field" style="margin:0"><label style="font-size:11px">Hasta</label>
          <input type="date" id="hist-hasta" value="${histFiltros.hasta}" onchange="aplicarFiltrosHist()" style="width:150px"></div>
        <div class="field" style="margin:0"><label style="font-size:11px">Categoría</label>
          <select id="hist-cat" onchange="aplicarFiltrosHist()" style="width:180px">
            <option value="">Todas</option>
            ${Object.keys(ICONO_CAT).map(c => `<option value="${c}" ${histFiltros.categoria===c?'selected':''}>${c}</option>`).join("")}
          </select></div>
        ${histFiltros.desde || histFiltros.hasta || histFiltros.categoria || histFiltros.usuario ?
          `<button class="btn btn-ghost" style="align-self:flex-end" onclick="limpiarFiltrosHist()"><i class="ti ti-x"></i> Limpiar</button>` : ""}
      </div>

      <div class="section-title"><i class="ti ti-list"></i> Actividad (${registros.length})</div>
      ${registros.length === 0 ? `
        <div class="empty"><i class="ti ti-history-off"></i>No hay actividad registrada en este período.</div>
      ` : `
        <div class="timeline-hist">
          ${registros.map(r => {
            const fecha = (r.fecha_hora || "").slice(0, 10);
            const hora = (r.fecha_hora || "").slice(11, 19);
            const color = COLOR_CAT[r.categoria] || "#64748b";
            const icono = ICONO_CAT[r.categoria] || "ti-point";
            return `
              <div class="hist-row">
                <div class="hist-icon" style="background:${color}1a;color:${color}"><i class="ti ${icono}"></i></div>
                <div class="hist-body">
                  <div class="hist-top">
                    <span class="hist-accion">${r.accion}</span>
                    <span class="hist-fecha">${fecha} · ${hora}</span>
                  </div>
                  <div class="hist-meta">
                    <span class="hist-user"><i class="ti ti-user"></i> ${r.usuario || "?"}${r.rol ? ` (${LABEL_ROL[r.rol] || r.rol})` : ""}</span>
                    ${r.categoria ? `<span class="hist-cat" style="color:${color}">${r.categoria}</span>` : ""}
                    ${r.detalle ? `<span class="hist-detalle">${r.detalle}</span>` : ""}
                    ${r.referencia ? `<button class="hist-evidencia" onclick="verEvidenciaHist('${r.referencia}')"><i class="ti ti-photo"></i> Ver evidencia</button>` : ""}
                  </div>
                </div>
              </div>`;
          }).join("")}
        </div>
        ${registros.length >= 500 ? `<div style="text-align:center;color:var(--muted);font-size:13px;margin-top:14px">Mostrando las 500 acciones más recientes. Usá los filtros para ver más.</div>` : ""}
      `}
    </div>`;
}

function aplicarFiltrosHist() {
  histFiltros.desde = $("#hist-desde").value;
  histFiltros.hasta = $("#hist-hasta").value;
  histFiltros.categoria = $("#hist-cat").value;
  renderHistorial();
}

function limpiarFiltrosHist() {
  histFiltros = { desde: "", hasta: "", categoria: "", usuario: "" };
  renderHistorial();
}

// Trae y muestra la(s) foto(s) de evidencia de un registro del historial
async function verEvidenciaHist(referencia) {
  const data = await api("/api/auditoria/evidencia?ref=" + encodeURIComponent(referencia));
  const fotos = data.fotos || [];
  if (!fotos.length) { toast("No se encontró la evidencia", "error"); return; }

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(10,15,26,0.8);z-index:2000;display:grid;place-items:center;padding:20px";
  overlay.innerHTML = `
    <div style="max-width:90vw;max-height:90vh;text-align:center">
      <div style="color:#fff;font-size:15px;margin-bottom:12px;font-weight:600">
        <i class="ti ti-photo"></i> ${fotos[0].tipo || "Evidencia"} ${fotos.length > 1 ? `(${fotos.length} fotos)` : ""}
      </div>
      <div style="display:flex;gap:12px;flex-wrap:wrap;justify-content:center;max-height:75vh;overflow:auto">
        ${fotos.map(f => `<img src="${f.datos}" style="max-width:${fotos.length>1?'42vw':'85vw'};max-height:70vh;border-radius:12px;box-shadow:0 8px 30px rgba(0,0,0,0.5)">`).join("")}
      </div>
      <button class="btn btn-ghost" style="margin-top:14px;background:rgba(255,255,255,0.15);color:#fff;border:none" onclick="this.closest('.modal-overlay').remove()"><i class="ti ti-x"></i> Cerrar</button>
    </div>`;
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
  document.body.appendChild(overlay);
}

async function renderTurismo() {
  status("Presupuestos de Turismo");
  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-bus-stop"></i> Presupuestos de Turismo</h1>
      <p>Calculá el costo y precio de un servicio de turismo o charter</p>
    </div>
    <div class="section">
      <div class="toolbar">
        <div class="tabs">
          <button class="tab-btn ${turismoTab==='nuevo'?'active':''}" onclick="setTurismoTab('nuevo')"><i class="ti ti-calculator"></i> Nuevo presupuesto</button>
          <button class="tab-btn ${turismoTab==='guardados'?'active':''}" onclick="setTurismoTab('guardados')"><i class="ti ti-folder"></i> Guardados</button>
          <button class="tab-btn ${turismoTab==='config'?'active':''}" onclick="setTurismoTab('config')"><i class="ti ti-settings"></i> Configuración</button>
        </div>
      </div>
      <div id="turismo-contenido"></div>
    </div>`;
  if (turismoTab === "nuevo") await renderTurismoNuevo();
  else if (turismoTab === "guardados") await renderTurismoGuardados();
  else await renderTurismoConfig();
}

function setTurismoTab(t) { turismoTab = t; renderTurismo(); }

// ─── Nuevo presupuesto con cálculo en vivo ───
async function renderTurismoNuevo() {
  const cont = document.getElementById("turismo-contenido");
  const vehiculos = await api("/api/vehiculos");
  const cfg = await api("/api/turismo/config");
  cont.innerHTML = `
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
      <!-- Columna de datos -->
      <div>
        <div class="card">
          <div class="card-head"><i class="ti ti-map-pin"></i> Datos del viaje</div>
          <div class="card-body">
            <div class="field" style="margin-bottom:12px"><label>Destino *</label><input id="tu-destino" placeholder="Buenos Aires" oninput="calcularTurismoVivo()"></div>
            <div class="field" style="margin-bottom:12px"><label>Descripción</label><input id="tu-desc" placeholder="Charter 3 días" oninput="calcularTurismoVivo()"></div>
            <div class="field" style="margin-bottom:12px"><label>Cliente</label><input id="tu-cliente" placeholder="Nombre del cliente"></div>
            <div class="field" style="margin-bottom:12px"><label>Vehículo</label>
              <select id="tu-vehiculo" onchange="autoConsumo()">
                <option value="">Elegir bus...</option>
                ${vehiculos.map(v => `<option value="${v.id}" data-consumo="${v.consumo_km_litro || 0}" data-patente="${v.patente}">${v.patente} — ${v.marca} ${v.modelo}${v.n_interno ? ' (Coche ' + v.n_interno + ')' : ''}</option>`).join("")}
              </select>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px">
              <div class="field"><label>Km totales *</label><input id="tu-km" type="number" placeholder="2400" oninput="calcularTurismoVivo()"></div>
              <div class="field"><label>Días</label><input id="tu-dias" type="number" value="1" oninput="calcularTurismoVivo()"></div>
              <div class="field"><label>Noches</label><input id="tu-noches" type="number" value="0" oninput="calcularTurismoVivo()"></div>
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:12px">
              <div class="field"><label>Pasajeros</label><input id="tu-pax" type="number" placeholder="45" oninput="calcularTurismoVivo()"></div>
              <div class="field"><label>Consumo (km/l)</label><input id="tu-consumo" type="number" step="0.1" placeholder="2.5" oninput="calcularTurismoVivo()"></div>
            </div>
          </div>
        </div>

        <div class="card" style="margin-top:16px">
          <div class="card-head"><i class="ti ti-cash"></i> Valores (editables por viaje)</div>
          <div class="card-body">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
              <div class="field"><label>Precio gasoil (Gs/l)</label><input id="tu-gasoil" type="number" value="${cfg.precio_gasoil||''}" oninput="calcularTurismoVivo()"></div>
              <div class="field"><label>Jornal chofer/día</label><input id="tu-jornal" type="number" value="${cfg.jornal_chofer||''}" oninput="calcularTurismoVivo()"></div>
              <div class="field"><label>Viático/día</label><input id="tu-viatico" type="number" value="${cfg.viatico_dia||''}" oninput="calcularTurismoVivo()"></div>
              <div class="field"><label>Comida/día</label><input id="tu-comida" type="number" value="${cfg.comida_dia||''}" oninput="calcularTurismoVivo()"></div>
              <div class="field"><label>Hospedaje/noche</label><input id="tu-hospedaje" type="number" value="${cfg.hospedaje_noche||''}" oninput="calcularTurismoVivo()"></div>
              <div class="field"><label>CPK cubiertas</label><input id="tu-cpk" type="number" value="${cfg.cpk_cubiertas||''}" oninput="calcularTurismoVivo()"></div>
              <div class="field"><label>Mant./km</label><input id="tu-mant" type="number" value="${cfg.costo_mant_km||''}" oninput="calcularTurismoVivo()"></div>
              <div class="field"><label>Peajes (local)</label><input id="tu-peajes" type="number" placeholder="0" oninput="calcularTurismoVivo()"></div>
              <div class="field"><label>Margen (%)</label><input id="tu-margen" type="number" value="${cfg.margen_sugerido||30}" oninput="calcularTurismoVivo()"></div>
              <div class="field"><label>IVA (%)</label><input id="tu-iva" type="number" value="${cfg.iva_porcentaje||10}" oninput="calcularTurismoVivo()"></div>
            </div>
          </div>
        </div>

        <div class="card" style="margin-top:16px;border:2px solid #fef0e6">
          <div class="card-head" style="background:#fff8f3"><i class="ti ti-world"></i> Viajes largos / internacionales (opcional)</div>
          <div class="card-body">
            <label style="display:flex;align-items:center;gap:10px;padding:10px;background:#f9fafb;border-radius:9px;cursor:pointer;margin-bottom:14px">
              <input type="checkbox" id="tu-2chofer" onchange="calcularTurismoVivo()" style="width:18px;height:18px">
              <div>
                <b style="font-size:14px">Segundo chofer</b>
                <div style="font-size:12px;color:var(--muted)">Obligatorio en viajes largos. Duplica chofer, viáticos y comidas.</div>
              </div>
            </label>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
              <div class="field"><label>Peajes en el exterior</label><input id="tu-peajes-ext" type="number" placeholder="0" oninput="calcularTurismoVivo()"></div>
              <div class="field"><label>Seguro del viaje</label><input id="tu-seguro" type="number" placeholder="0" oninput="calcularTurismoVivo()"></div>
              <div class="field"><label>Trámites / habilitaciones</label><input id="tu-tramites" type="number" placeholder="0" oninput="calcularTurismoVivo()"></div>
              <div class="field"><label>Otros gastos</label><input id="tu-otros" type="number" placeholder="0" oninput="calcularTurismoVivo()"></div>
              <div class="field"><label>% Imprevistos (colchón)</label><input id="tu-imprevistos" type="number" placeholder="0" oninput="calcularTurismoVivo()"></div>
            </div>
          </div>
        </div>
      </div>

      <!-- Columna de resultado en vivo -->
      <div>
        <div class="card" style="position:sticky;top:20px">
          <div class="card-head"><i class="ti ti-receipt"></i> Presupuesto</div>
          <div class="card-body" id="tu-resultado">
            <div class="empty" style="padding:40px"><i class="ti ti-calculator"></i>Cargá los datos del viaje para ver el cálculo.</div>
          </div>
        </div>
      </div>
    </div>`;
  calcularTurismoVivo();
}

// Auto-completar el consumo cuando se elige un vehículo
function autoConsumo() {
  const sel = document.getElementById("tu-vehiculo");
  const opt = sel.options[sel.selectedIndex];
  const consumo = opt ? opt.dataset.consumo : 0;
  if (consumo && parseFloat(consumo) > 0) {
    document.getElementById("tu-consumo").value = consumo;
  }
  calcularTurismoVivo();
}

// Junta los datos del formulario
function datosTurismo() {
  const sel = document.getElementById("tu-vehiculo");
  const opt = sel.options[sel.selectedIndex];
  return {
    destino: $("#tu-destino").value, descripcion: $("#tu-desc").value, cliente: $("#tu-cliente").value,
    vehiculo_id: sel.value || null, patente: opt ? (opt.dataset.patente || "") : "",
    km_total: $("#tu-km").value, dias: $("#tu-dias").value, noches: $("#tu-noches").value,
    pasajeros: $("#tu-pax").value, consumo_km_litro: $("#tu-consumo").value,
    precio_gasoil: $("#tu-gasoil").value, jornal_chofer: $("#tu-jornal").value,
    viatico_dia: $("#tu-viatico").value, comida_dia: $("#tu-comida").value,
    hospedaje_noche: $("#tu-hospedaje").value, cpk_cubiertas: $("#tu-cpk").value,
    costo_mant_km: $("#tu-mant").value, peajes: $("#tu-peajes").value, otros: $("#tu-otros").value,
    margen: $("#tu-margen").value, iva: $("#tu-iva").value,
    // Viajes largos / internacionales
    segundo_chofer: $("#tu-2chofer").checked,
    peajes_exterior: $("#tu-peajes-ext").value, seguro_viaje: $("#tu-seguro").value,
    tramites: $("#tu-tramites").value, imprevistos_pct: $("#tu-imprevistos").value,
  };
}

let turismoTimer = null;
function calcularTurismoVivo() {
  clearTimeout(turismoTimer);
  turismoTimer = setTimeout(async () => {
    const datos = datosTurismo();
    if (!datos.km_total || parseFloat(datos.km_total) <= 0) {
      document.getElementById("tu-resultado").innerHTML = `<div class="empty" style="padding:40px"><i class="ti ti-calculator"></i>Ingresá los km del viaje para ver el cálculo.</div>`;
      return;
    }
    const r = await api("/api/turismo/calcular", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(datos)
    });
    mostrarResultadoTurismo(r, datos);
  }, 300);
}

function mostrarResultadoTurismo(r, datos) {
  const cont = document.getElementById("tu-resultado");
  const linea = (concepto, monto, sub) => monto > 0 ?
    `<div style="display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid var(--border)${sub?';color:var(--muted);font-size:13px':''}">
      <span>${concepto}</span><span style="font-weight:600">${gs(monto)}</span></div>` : "";
  cont.innerHTML = `
    <div style="font-size:13px;color:var(--muted);margin-bottom:10px">
      ${r.litros_estimados} litros · ${r.consumo_km_litro} km/l · ${datos.km_total} km${r.segundo_chofer ? ' · 2 choferes' : ''}
    </div>
    ${linea("Combustible", r.costo_combustible)}
    ${linea("Cubiertas", r.costo_cubiertas)}
    ${linea("Mantenimiento", r.costo_mantenimiento)}
    ${linea(r.segundo_chofer ? "Chofer (×2)" : "Chofer", r.costo_chofer)}
    ${linea(r.segundo_chofer ? "Viáticos (×2)" : "Viáticos", r.costo_viaticos)}
    ${linea(r.segundo_chofer ? "Comidas (×2)" : "Comidas", r.costo_comidas)}
    ${linea("Hospedaje", r.costo_hospedaje)}
    ${linea("Peajes (local)", r.peajes)}
    ${linea("Peajes exterior", r.peajes_exterior)}
    ${linea("Seguro del viaje", r.seguro_viaje)}
    ${linea("Trámites", r.tramites)}
    ${linea("Otros", r.otros)}
    <div style="display:flex;justify-content:space-between;padding:10px 0;margin-top:6px;border-top:2px solid var(--border);font-weight:700">
      <span>Subtotal</span><span>${gs(r.subtotal)}</span></div>
    ${r.monto_imprevistos > 0 ? `<div style="display:flex;justify-content:space-between;padding:5px 0;color:var(--muted)">
      <span>Imprevistos (${r.imprevistos_pct}%)</span><span>${gs(r.monto_imprevistos)}</span></div>` : ""}
    <div style="display:flex;justify-content:space-between;padding:5px 0;color:var(--muted)">
      <span>Margen (${r.margen_pct}%)</span><span>${gs(r.monto_margen)}</span></div>
    <div style="display:flex;justify-content:space-between;padding:5px 0;color:var(--muted)">
      <span>IVA (${r.iva_pct}%)</span><span>${gs(r.monto_iva)}</span></div>
    <div style="background:var(--brand-red);color:#fff;padding:14px;border-radius:10px;margin-top:12px;display:flex;justify-content:space-between;align-items:center">
      <span style="font-size:15px;font-weight:700">PRECIO TOTAL</span>
      <span style="font-size:22px;font-weight:800">${gs(r.precio_final)}</span>
    </div>
    ${r.precio_por_pasajero > 0 ? `
      <div style="text-align:center;margin-top:10px;color:var(--brand-blue);font-weight:700;font-size:15px">
        ${gs(r.precio_por_pasajero)} por pasajero (${r.pasajeros})
      </div>` : ""}
    <button class="btn btn-primary" style="width:100%;margin-top:16px" onclick="guardarPresupuestoTurismo()"><i class="ti ti-device-floppy"></i> Guardar presupuesto</button>`;
}

async function guardarPresupuestoTurismo() {
  const datos = datosTurismo();
  if (!datos.destino) { toast("Poné un destino", "error"); return; }
  if (!datos.km_total) { toast("Poné los km", "error"); return; }
  const r = await api("/api/turismo/presupuestos", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ datos })
  });
  if (r.ok) {
    toast("Presupuesto guardado", "success");
    turismoTab = "guardados";
    renderTurismo();
  } else toast("Error al guardar", "error");
}

// ─── Presupuestos guardados ───
async function renderTurismoGuardados() {
  const cont = document.getElementById("turismo-contenido");
  const lista = await api("/api/turismo/presupuestos");
  if (!lista.length) {
    cont.innerHTML = `<div class="empty"><i class="ti ti-folder-open"></i>No hay presupuestos guardados todavía.</div>`;
    return;
  }
  cont.innerHTML = `
    <div class="table-wrap"><table>
      <thead><tr>
        <th>Fecha</th><th>Destino</th><th>Cliente</th><th>Vehículo</th>
        <th class="center">Días</th><th class="center">Pax</th><th class="num">Precio</th><th class="td-action"></th>
      </tr></thead>
      <tbody>
        ${lista.map(p => `<tr>
          <td>${(p.fecha_creacion||"").slice(0,10)}</td>
          <td><b>${p.destino}</b>${p.descripcion ? `<br><span style="font-size:12px;color:var(--muted)">${p.descripcion}</span>` : ""}</td>
          <td>${p.cliente || "—"}</td>
          <td>${p.patente || "—"}</td>
          <td class="center">${p.dias}</td>
          <td class="center">${p.pasajeros || "—"}</td>
          <td class="num"><b>${gs(p.precio_final)}</b></td>
          <td class="td-action" style="white-space:nowrap">
            <button class="icon-btn" title="Imprimir PDF" onclick="window.open('/api/turismo/presupuestos/${p.id}/pdf','_blank')"><i class="ti ti-printer"></i></button>
            <button class="icon-btn" title="Eliminar" onclick="borrarPresupuestoTurismo(${p.id})"><i class="ti ti-trash"></i></button>
          </td>
        </tr>`).join("")}
      </tbody>
    </table></div>`;
}

async function borrarPresupuestoTurismo(pid) {
  if (!confirm("¿Eliminar este presupuesto?")) return;
  await api(`/api/turismo/presupuestos/${pid}`, { method: "DELETE" });
  toast("Eliminado");
  renderTurismo();
}

// ─── Configuración de valores por defecto ───
async function renderTurismoConfig() {
  const cont = document.getElementById("turismo-contenido");
  const cfg = await api("/api/turismo/config");
  cont.innerHTML = `
    <div class="card" style="max-width:640px">
      <div class="card-head"><i class="ti ti-settings"></i> Valores por defecto para presupuestos</div>
      <div class="card-body">
        <p style="font-size:13px;color:var(--muted);margin-bottom:16px">Estos valores se usan como punto de partida en cada presupuesto. Podés ajustarlos por viaje.</p>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
          <div class="field"><label>Precio gasoil (Gs/litro)</label><input id="cfg-gasoil" type="number" value="${cfg.precio_gasoil||''}"></div>
          <div class="field"><label>Jornal chofer por día</label><input id="cfg-jornal" type="number" value="${cfg.jornal_chofer||''}"></div>
          <div class="field"><label>Viático por día</label><input id="cfg-viatico" type="number" value="${cfg.viatico_dia||''}"></div>
          <div class="field"><label>Comida por día</label><input id="cfg-comida" type="number" value="${cfg.comida_dia||''}"></div>
          <div class="field"><label>Hospedaje por noche</label><input id="cfg-hospedaje" type="number" value="${cfg.hospedaje_noche||''}"></div>
          <div class="field"><label>CPK cubiertas (Gs/km)</label><input id="cfg-cpk" type="number" value="${cfg.cpk_cubiertas||''}"></div>
          <div class="field"><label>Mantenimiento (Gs/km)</label><input id="cfg-mant" type="number" value="${cfg.costo_mant_km||''}"></div>
          <div class="field"><label>Consumo por defecto (km/l)</label><input id="cfg-consumo" type="number" step="0.1" value="${cfg.consumo_defecto||2.5}"></div>
          <div class="field"><label>Margen sugerido (%)</label><input id="cfg-margen" type="number" value="${cfg.margen_sugerido||30}"></div>
          <div class="field"><label>IVA (%)</label><input id="cfg-iva" type="number" value="${cfg.iva_porcentaje||10}"></div>
        </div>
        <button class="btn btn-primary" style="margin-top:18px" onclick="guardarConfigTurismo()"><i class="ti ti-device-floppy"></i> Guardar configuración</button>
      </div>
    </div>`;
}

async function guardarConfigTurismo() {
  const datos = {
    precio_gasoil: $("#cfg-gasoil").value, jornal_chofer: $("#cfg-jornal").value,
    viatico_dia: $("#cfg-viatico").value, comida_dia: $("#cfg-comida").value,
    hospedaje_noche: $("#cfg-hospedaje").value, cpk_cubiertas: $("#cfg-cpk").value,
    costo_mant_km: $("#cfg-mant").value, consumo_defecto: $("#cfg-consumo").value,
    margen_sugerido: $("#cfg-margen").value, iva_porcentaje: $("#cfg-iva").value,
  };
  const r = await api("/api/turismo/config", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(datos)
  });
  if (r.ok) toast("Configuración guardada", "success");
  else toast("Error", "error");
}

async function renderOEE() {
  status("OEE — Eficiencia General de la Flota");
  const hoy = new Date().toISOString().slice(0, 10);
  const ini = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-gauge"></i> OEE — Eficiencia de Flota</h1>
      <p>Disponibilidad × Rendimiento × Calidad — qué tan bien se aprovecha cada bus</p>
    </div>
    <div class="section">
      <div style="background:#eaf2fb;border-radius:11px;padding:13px 16px;margin-bottom:18px;font-size:13px;color:var(--text)">
        <b><i class="ti ti-info-circle"></i> Cómo se calcula:</b>
        <b>Disponibilidad</b> = días operativo ÷ días del período ·
        <b>Rendimiento</b> = km recorridos ÷ meta de km ·
        <b>Calidad</b> = días sin fallas ÷ días operativo.
        El OEE es el producto de los tres.
      </div>
      <div class="toolbar">
        <div class="field"><label style="font-size:12px">Desde</label>
          <input type="date" id="oee-desde" value="${ini}" style="padding:9px;border-radius:9px;border:1.5px solid var(--border)"></div>
        <div class="field"><label style="font-size:12px">Hasta</label>
          <input type="date" id="oee-hasta" value="${hoy}" style="padding:9px;border-radius:9px;border:1.5px solid var(--border)"></div>
        <button class="btn btn-primary" style="align-self:flex-end" onclick="calcularOEEFlota()"><i class="ti ti-calculator"></i> Calcular</button>
      </div>
      <div id="oee-result"><div class="empty"><i class="ti ti-gauge"></i>Elegí un período y tocá Calcular.</div></div>
    </div>`;
}

async function calcularOEEFlota() {
  const desde = document.getElementById("oee-desde").value;
  const hasta = document.getElementById("oee-hasta").value;
  if (!desde || !hasta) { toast("Elegí ambas fechas", "error"); return; }
  const cont = document.getElementById("oee-result");
  cont.innerHTML = `<div class="empty"><i class="ti ti-loader"></i> Calculando...</div>`;
  const data = await api(`/api/oee_flota?desde=${desde}&hasta=${hasta}`);
  if (!data.ok || !data.vehiculos.length) {
    cont.innerHTML = `<div class="empty"><i class="ti ti-gauge-off"></i>No hay datos para calcular en ese período.</div>`;
    return;
  }
  const p = data.promedio;
  cont.innerHTML = `
    <div class="metrics" style="margin-bottom:20px">
      <div class="metric"><div class="metric-content">
        <div class="metric-label">Disponibilidad</div>
        <div class="metric-value" style="color:${_colorOEE(p.disponibilidad)}">${p.disponibilidad}%</div></div></div>
      <div class="metric"><div class="metric-content">
        <div class="metric-label">Rendimiento</div>
        <div class="metric-value" style="color:${_colorOEE(p.rendimiento)}">${p.rendimiento}%</div></div></div>
      <div class="metric"><div class="metric-content">
        <div class="metric-label">Calidad</div>
        <div class="metric-value" style="color:${_colorOEE(p.calidad)}">${p.calidad}%</div></div></div>
      <div class="metric" style="border:2px solid ${_colorOEE(p.oee)}"><div class="metric-content">
        <div class="metric-label">OEE de Flota</div>
        <div class="metric-value" style="color:${_colorOEE(p.oee)}">${p.oee}%</div></div></div>
    </div>
    <div class="section-title"><i class="ti ti-list"></i> Detalle por vehículo (peores primero)</div>
    <div class="table-wrap"><table>
      <thead><tr>
        <th>Vehículo</th><th class="center">Disponib.</th><th class="center">Rendim.</th>
        <th class="center">Calidad</th><th class="center">OEE</th><th>Observación</th>
      </tr></thead>
      <tbody>
        ${data.vehiculos.map(v => `<tr>
          <td><b>${v.patente}</b>${v.n_interno ? ` <span class="badge cat">${v.n_interno}</span>` : ""}</td>
          <td class="center" style="color:${_colorOEE(v.disponibilidad)}">${v.disponibilidad}%</td>
          <td class="center" style="color:${_colorOEE(v.rendimiento)}">${v.rendimiento}%</td>
          <td class="center" style="color:${_colorOEE(v.calidad)}">${v.calidad}%</td>
          <td class="center"><b style="color:${_colorOEE(v.oee)}">${v.oee}%</b></td>
          <td style="font-size:12px;color:var(--muted)">${v.faltantes && v.faltantes.length ? "⚠ Falta: " + v.faltantes.join(", ") : "—"}</td>
        </tr>`).join("")}
      </tbody>
    </table></div>`;
}

async function renderKpis() {
  const v = cocheActual;
  status(`KPIs del coche ${v.patente}`);
  const meses = await api(`/api/meses/${v.id}`);
  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-chart-bar"></i> KPIs · ${v.patente}</h1>
      <p>${v.marca} ${v.modelo} — indicadores económicos</p>
    </div>
    <div class="section">
      <div class="toolbar">
        <div class="tabs">
          <button class="tab-btn ${kpiModo==='mes'?'active':''}" onclick="setKpiModo('mes')"><i class="ti ti-calendar"></i> Por mes</button>
          <button class="tab-btn ${kpiModo==='produccion'?'active':''}" onclick="setKpiModo('produccion')"><i class="ti ti-chart-area"></i> Producción</button>
        </div>
        <select id="k-mes" onchange="cargarKpis()" style="padding:8px 12px;border:1px solid var(--border);border-radius:8px;${kpiModo==='produccion'?'display:none':''}">
          ${meses.map(m => `<option value="${m}">${mesLegible(m)}</option>`).join("")}
        </select>
        <button class="btn btn-pdf" style="margin-left:auto" onclick="exportarPdf()"><i class="ti ti-file-type-pdf"></i> Exportar PDF</button>
      </div>
      <div id="k-result"></div>
    </div>`;
  window._meses = meses;
  cargarKpis();
}
function setKpiModo(m) {
  kpiModo = m;
  document.querySelectorAll(".tab-btn").forEach(t => t.classList.remove("active"));
  event.target.closest(".tab-btn").classList.add("active");
  $("#k-mes").style.display = m === "produccion" ? "none" : "";
  cargarKpis();
}
async function cargarKpis() {
  const v = cocheActual;
  let url = `/api/kpis/${v.id}?modo=${kpiModo}`;
  if (kpiModo === "mes") url += `&mes=${$("#k-mes")?.value || ""}`;
  const k = await api(url);
  const res = $("#k-result");
  if (!k || !k.cantidad_servicios) {
    res.innerHTML = `<div class="empty"><i class="ti ti-chart-area-line"></i>Sin datos para mostrar. Cargá servicios y costos primero.</div>`;
    if (chartBarras) { chartBarras.destroy(); chartBarras = null; }
    if (chartTorta) { chartTorta.destroy(); chartTorta = null; }
    return;
  }
  const subtitulo = kpiModo === "produccion"
    ? `Producción total${k.fecha_inicio ? ` · ${k.fecha_inicio} → ${k.fecha_fin}` : ""}`
    : mesLegible($("#k-mes").value);
  const ing = k.ingreso || 1;
  const filas = [
    ["INGRESO", k.ingreso, "var(--brand)", true, 100, "ti-arrow-up-right"],
    ["− Costos Variables", k.costos_variables, "var(--danger)", false, k.costos_variables/ing*100, "ti-minus"],
    ["= MARGEN DE CONTRIBUCIÓN", k.margen_contribucion, "var(--success)", true, k.margen_contribucion/ing*100, "ti-equal"],
    ["− Costos Fijos Directos", k.costos_fijos_directos, "var(--warning)", false, k.costos_fijos_directos/ing*100, "ti-minus"],
    ["− Costos Fijos Indirectos", k.costos_fijos_indirectos, "var(--warning)", false, k.costos_fijos_indirectos/ing*100, "ti-minus"],
    ["= UTILIDAD OPERATIVA", k.utilidad_operativa, "var(--brand-dark)", true, k.utilidad_operativa/ing*100, "ti-equal"],
  ];
  res.innerHTML = `
    <h2 style="color:var(--brand);font-size:17px;margin-bottom:14px;font-weight:600">${subtitulo}</h2>
    <div class="metrics">
      <div class="metric"><div class="metric-icon blue"><i class="ti ti-clipboard-check"></i></div><div class="metric-content"><div class="metric-label">Servicios</div><div class="metric-value">${k.cantidad_servicios}</div></div></div>
      <div class="metric"><div class="metric-icon green"><i class="ti ti-road"></i></div><div class="metric-content"><div class="metric-label">KM totales</div><div class="metric-value">${fmtNum(k.total_km)}</div></div></div>
      <div class="metric"><div class="metric-icon blue"><i class="ti ti-cash"></i></div><div class="metric-content"><div class="metric-label">Ingreso</div><div class="metric-value">${gsSmall(k.ingreso)}</div></div></div>
      <div class="metric ${k.rentabilidad_pct < 15 ? 'warning' : 'success'}"><div class="metric-icon green"><i class="ti ti-trending-up"></i></div><div class="metric-content"><div class="metric-label">Rentabilidad</div><div class="metric-value">${k.rentabilidad_pct.toFixed(1)}%</div></div></div>
    </div>
    <div class="charts-row">
      <div class="chart-card"><h3>Estructura de costos</h3><div class="chart-container"><canvas id="chartBarras"></canvas></div></div>
      <div class="chart-card"><h3>Distribución del ingreso</h3><div class="chart-container"><canvas id="chartTorta"></canvas></div></div>
    </div>
    <div class="card">
      <div class="card-head"><i class="ti ti-calculator"></i> Detalle de la estructura de costos</div>
      <div class="card-body">
        ${filas.map(([lbl, val, col, bold, pct, ic]) => `
          <div class="cost-row">
            <div class="cost-label ${bold?'bold':''}" style="color:${col}">${lbl}</div>
            <div class="cost-bar-track"><div class="cost-bar" style="width:${Math.min(100,Math.abs(pct))}%;background:${col}"></div></div>
            <div class="cost-pct">${Math.round(pct)}%</div>
            <div class="cost-val" style="color:${col}">${gs(val)}</div>
          </div>`).join("")}
      </div>
    </div>
    <div class="section-title"><i class="ti ti-target"></i> Indicadores operativos</div>
    <div class="kpi-grid">
      ${kpiCard("KM prom./servicio", fmtNum(k.km_promedio))}
      ${kpiCard("Horas prom./servicio", k.horas_promedio)}
      ${kpiCard("Ingreso prom./servicio", gsSmall(k.ingreso_promedio_servicio))}
      ${kpiCard("Ingreso por KM", gsSmall(k.ingreso_por_km))}
      ${kpiCard("Ingreso por hora", gsSmall(k.ingreso_por_hora))}
      ${kpiCard("Costo variable por KM", gsSmall(k.costo_variable_por_km))}
      ${kpiCard("Margen contribución", k.margen_pct.toFixed(1)+"%")}
      ${kpiCard("Rentabilidad operativa", k.rentabilidad_pct.toFixed(1)+"%")}
    </div>`;
  dibujarGraficos(k);
}
function kpiCard(label, value) {
  return `<div class="kpi-card"><div class="kpi-card-label">${label}</div><div class="kpi-card-value">${value}</div></div>`;
}
function dibujarGraficos(k) {
  if (chartBarras) chartBarras.destroy();
  if (chartTorta) chartTorta.destroy();
  chartBarras = new Chart($("#chartBarras"), {
    type: "bar",
    data: {
      labels: ["Ingreso", "C. Variables", "Margen", "C.F. Directos", "C.F. Indirectos", "Utilidad"],
      datasets: [{
        data: [k.ingreso, k.costos_variables, k.margen_contribucion, k.costos_fijos_directos, k.costos_fijos_indirectos, k.utilidad_operativa],
        backgroundColor: ["#2D8EF5", "#DC2626", "#16A34A", "#D97706", "#D97706", "#1A6FDB"],
        borderRadius: 6, borderSkipped: false
      }]
    },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => gs(c.raw) } } },
      scales: {
        x: { ticks: { callback: v => v >= 1e6 ? (v/1e6)+"M" : v, font:{size:10} }, grid: { color: "#F1F5F9" } },
        y: { ticks: { font: { size: 11 } }, grid: { display: false } }
      }
    }
  });
  const fijos = k.costos_fijos_directos + k.costos_fijos_indirectos;
  const util = Math.max(0, k.utilidad_operativa);
  chartTorta = new Chart($("#chartTorta"), {
    type: "doughnut",
    data: {
      labels: ["Costos variables", "Costos fijos", "Utilidad operativa"],
      datasets: [{ data: [k.costos_variables, fijos, util], backgroundColor: ["#DC2626", "#D97706", "#1A6FDB"], borderColor: "#fff", borderWidth: 3 }]
    },
    options: {
      responsive: true, maintainAspectRatio: false, cutout: "62%",
      plugins: {
        legend: { position: "bottom", labels: { font: { size: 11 }, padding: 14, boxWidth: 10, usePointStyle: true } },
        tooltip: { callbacks: { label: c => `${c.label}: ${gs(c.raw)}` } }
      }
    }
  });
}
function exportarPdf() {
  const v = cocheActual;
  let url = `/api/exportar_pdf/${v.id}?modo=${kpiModo}`;
  if (kpiModo === "mes") url += `&mes=${$("#k-mes")?.value || ""}`;
  toast("Generando PDF...", "success");
  window.open(url, "_blank");
}

// ════════════════════════════════════════════════════════════════════════
//  MANTENIMIENTO (preventivo, por vehículo)
// ════════════════════════════════════════════════════════════════════════
async function renderMantenimiento() {
  const v = cocheActual;
  status(`Mantenimiento preventivo del coche ${v.patente}`);
  const planVeh = await api(`/api/vehiculos/${v.id}/plan`);
  const planes = await api("/api/planes");
  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-tool"></i> Mantenimiento · ${v.patente}</h1>
      <p>${v.marca} ${v.modelo} — control preventivo por kilometraje</p>
    </div>
    <div class="section">
      ${planVeh.plan ? `<div style="display:flex;justify-content:flex-end;margin-bottom:14px">
        <button class="btn btn-ghost" onclick="window.open('/api/vehiculos/${v.id}/plan_pdf','_blank')"><i class="ti ti-printer"></i> Imprimir plan</button>
      </div>` : ""}
      ${planVeh.plan ? renderOdometro(planVeh) : renderSinPlan(planes, v)}
      ${planVeh.plan ? `
        <div class="tabs">
          <button class="tab-btn ${mantTab==='estado'?'active':''}" onclick="setMantTab('estado')"><i class="ti ti-gauge"></i> Estado actual</button>
          <button class="tab-btn ${mantTab==='realizar'?'active':''}" onclick="setMantTab('realizar')"><i class="ti ti-plus"></i> Registrar</button>
          <button class="tab-btn ${mantTab==='historial'?'active':''}" onclick="setMantTab('historial')"><i class="ti ti-history"></i> Historial</button>
        </div>
        <div id="mant-body"></div>
      ` : ""}
    </div>`;
  if (planVeh.plan) cargarMantTab(planVeh);
}
function renderOdometro(p) {
  const v = cocheActual;
  const coche = v && v.n_interno ? v.n_interno : "—";
  return `<div class="odometer-card">
    <div>
      <div class="odo-label">Odómetro estimado</div>
      <div class="odo-value">${fmtNum(p.km_actual)} km
        <button class="icon-btn" title="Corregir km a mano" onclick="corregirKm(${v.id}, ${p.km_actual})" style="vertical-align:middle;margin-left:6px"><i class="ti ti-edit"></i></button>
      </div>
      <div class="odo-plan"><i class="ti ti-bus"></i> Coche: <b>${coche}</b></div>
    </div>
    <div id="odo-resumen" class="odo-resumen"></div>
  </div>`;
}

// Corregir manualmente el odómetro de un vehículo
function corregirKm(vid, kmActual) {
  const nuevo = prompt(`Odómetro actual: ${fmtNum(kmActual)} km\n\nIngresá el km correcto del tablero:`, Math.round(kmActual));
  if (nuevo === null) return;
  const km = parseFloat(String(nuevo).replace(/\./g, "").replace(/,/g, "."));
  if (isNaN(km) || km < 0) { toast("Km inválido", "error"); return; }
  api(`/api/vehiculos/${vid}/km_manual`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ km })
  }).then(r => {
    if (r.ok) { toast("Odómetro corregido", "success"); renderMantenimiento(); }
    else toast(r.msg || "Error", "error");
  });
}
function renderSinPlan(planes, v) {
  return `<div class="card">
    <div class="card-head"><i class="ti ti-alert-triangle" style="color:var(--warning)"></i> Sin plan asignado</div>
    <div class="card-body">
      <p style="margin-bottom:14px;color:var(--muted);font-size:13.5px">Asignale un plan para empezar a controlar los vencimientos.</p>
      <div class="form-row">
        <div class="field" style="flex:1;min-width:280px"><label>Plan de mantenimiento</label>
          <select id="m-plan">
            <option value="">-- Elegí un plan --</option>
            ${planes.map(p => `<option value="${p.id}">${p.nombre} (${p.cant_tareas} tareas)</option>`).join("")}
          </select>
        </div>
        <div class="field"><label>KM actual del odómetro</label><input id="m-km" placeholder="250000" style="width:140px"></div>
        <button class="btn btn-primary" onclick="asignarPlanCoche(${v.id})"><i class="ti ti-link"></i> Asignar plan</button>
      </div>
    </div>
  </div>`;
}
async function asignarPlanCoche(vid) {
  const pid = $("#m-plan").value;
  if (!pid) { toast("Elegí un plan", "error"); return; }
  await api(`/api/vehiculos/${vid}/plan`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ plan_id: pid, km_inicial: parseFloat($("#m-km").value || 0) })
  });
  toast("Plan asignado", "success");
  renderMantenimiento();
}
function setMantTab(t) {
  mantTab = t;
  document.querySelectorAll(".tab-btn").forEach(b => b.classList.remove("active"));
  event.target.closest(".tab-btn").classList.add("active");
  api(`/api/vehiculos/${cocheActual.id}/plan`).then(p => cargarMantTab(p));
}
async function cargarMantTab(planVeh) {
  if (mantTab === "estado") await tabEstado();
  else if (mantTab === "realizar") await tabRealizar(planVeh);
  else if (mantTab === "historial") await tabHistorial();
}
async function tabEstado() {
  const v = cocheActual;
  const data = await api(`/api/vehiculos/${v.id}/estado_mantenimiento`);
  const estado = data.estado || [];
  const counts = { vencido: 0, pronto: 0, ok: 0 };
  estado.forEach(e => counts[e.estado] = (counts[e.estado] || 0) + 1);
  if ($("#odo-resumen")) $("#odo-resumen").innerHTML = `
    ${counts.vencido > 0 ? `<span class="odo-tag vencido"><i class="ti ti-alert-circle"></i> ${counts.vencido} vencidas</span>` : ""}
    ${counts.pronto > 0 ? `<span class="odo-tag pronto"><i class="ti ti-clock-hour-4"></i> ${counts.pronto} próximas</span>` : ""}
    ${counts.ok > 0 ? `<span class="odo-tag ok"><i class="ti ti-circle-check"></i> ${counts.ok} al día</span>` : ""}`;

  const iconoEstado = { optimo: "circle-check", bueno: "circle-check", regular: "clock-hour-4", atencion: "alert-triangle", vencido: "alert-circle" };
  const labelEstado = { optimo: "Óptimo", bueno: "Bueno", regular: "Regular", atencion: "Atención", vencido: "Vencido" };

  $("#mant-body").innerHTML = !estado.length ? `<div class="empty">El plan no tiene tareas cargadas.</div>` : `
    <div class="alert-list">
      ${estado.map(e => `
        <div class="alert-row ${e.estado}">
          <i class="ti ti-${iconoEstado[e.estado_grad] || 'circle'}"></i>
          <div style="min-width:0">
            <div class="alert-task">${e.tarea}
              ${e.categoria ? `<span class="badge cat">${e.categoria}</span>` : ""}
              <span class="grad-badge grad-${e.estado_grad}"><span class="dot"></span> ${labelEstado[e.estado_grad]} · ${e.porcentaje.toFixed(0)}%</span>
            </div>
            <div class="alert-meta" style="margin:6px 0 6px">
              ${e.ultimo_km !== null
                ? `Último: ${fmtNum(e.ultimo_km)} km${e.ultima_fecha ? ` · ${e.ultima_fecha}` : ""}`
                : "Sin registro previo"}
              · Cada ${fmtNum(e.intervalo_km)} km · Próximo: ${fmtNum(e.proximo_km)} km
            </div>
            <div class="grad-bar-wrap" style="max-width:520px">
              <div class="grad-bar estado-${e.estado_grad}" style="width:${e.porcentaje_visual}%"></div>
            </div>
          </div>
          <div class="alert-km">
            <div class="alert-km-restante">
              ${e.estado === "vencido" ? `▲ ${fmtNum(Math.abs(e.km_restantes))}` : fmtNum(e.km_restantes)}
            </div>
            <div class="alert-meta">${e.estado === 'vencido' ? 'km pasados' : 'km restantes'}</div>
          </div>
          <button class="btn btn-primary btn-sm" onclick="abrirRegistrar(${e.tarea_id})"><i class="ti ti-check"></i> Registrar</button>
        </div>
      `).join("")}
    </div>`;
}
function abrirRegistrar(tareaId) {
  mantTab = "realizar";
  document.querySelectorAll(".tab-btn").forEach((b, i) => b.classList.toggle("active", i === 1));
  api(`/api/vehiculos/${cocheActual.id}/plan`).then(p => tabRealizar(p, tareaId));
}
async function tabRealizar(planVeh, preseleccion = null) {
  const tareas = await api(`/api/planes/${planVeh.plan.plan_id}/tareas`);
  $("#mant-body").innerHTML = `
    <div class="card">
      <div class="card-head"><i class="ti ti-circle-plus"></i> Registrar mantenimiento realizado</div>
      <div class="card-body">
        <p class="hint"><i class="ti ti-bulb"></i> Cuando el taller termina una tarea del plan, registrala acá. El sistema actualiza el próximo vencimiento solo.</p>
        <div class="form-row" style="margin-top:14px">
          <div class="field" style="flex:1;min-width:280px"><label>Tarea realizada</label>
            <select id="mr-tarea">
              ${tareas.map(t => `<option value="${t.id}" ${t.id==preseleccion?'selected':''}>${t.tarea} (cada ${fmtNum(t.intervalo_km)} km)</option>`).join("")}
            </select>
          </div>
          <div class="field"><label>Fecha</label><input id="mr-fecha" type="date" value="${hoy()}"></div>
          <div class="field"><label>KM del coche</label><input id="mr-km" placeholder="${planVeh.km_actual.toFixed(0)}" style="width:130px"></div>
          <div class="field"><label>Costo (Gs.)</label><input id="mr-costo" placeholder="0" style="width:150px"></div>
          <div class="field" style="flex:1;min-width:250px"><label>Observaciones</label><input id="mr-obs" placeholder="Marca de aceite, taller, etc"></div>
          <button class="btn btn-primary" onclick="guardarMantenimiento()"><i class="ti ti-device-floppy"></i> Guardar</button>
        </div>
      </div>
    </div>`;
}
async function guardarMantenimiento() {
  const km = parseFloat($("#mr-km").value);
  if (!km) { toast("Ingresá el km del coche", "error"); return; }
  const costo = ($("#mr-costo").value || "0").replace(/\./g, "").replace(/,/g, ".");
  const r = await api("/api/mantenimientos", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      vehiculo_id: cocheActual.id, tarea_plan_id: parseInt($("#mr-tarea").value),
      fecha: $("#mr-fecha").value, km, costo: costo || 0, observaciones: $("#mr-obs").value
    })
  });
  if (r.ok) {
    toast("Mantenimiento registrado", "success");
    mantTab = "estado";
    renderMantenimiento();
  } else toast("Error al guardar", "error");
}
async function tabHistorial() {
  const hist = await api(`/api/vehiculos/${cocheActual.id}/mantenimientos`);
  $("#mant-body").innerHTML = !hist.length ? `<div class="empty"><i class="ti ti-history"></i>Sin mantenimientos registrados</div>` : `
    <div class="table-wrap">
      <table>
        <thead><tr><th>Fecha</th><th>Tarea</th><th>Categoría</th><th class="num">KM</th><th class="num">Costo</th><th>Observaciones</th><th class="td-action"></th></tr></thead>
        <tbody>${hist.map(h => `
          <tr><td>${h.fecha}</td><td>${h.tarea}</td>
            <td>${h.categoria ? `<span class="badge cat">${h.categoria}</span>` : "—"}</td>
            <td class="num">${fmtNum(h.km)}</td><td class="num">${gs(h.costo)}</td>
            <td>${h.observaciones || "—"}</td>
            <td class="td-action"><button class="icon-btn" onclick="borrarMantenimiento(${h.id})"><i class="ti ti-trash"></i></button></td>
          </tr>`).join("")}
        </tbody>
      </table>
    </div>`;
}
async function borrarMantenimiento(id) {
  if (!confirm("¿Eliminar este registro?")) return;
  await api(`/api/mantenimientos/${id}`, { method: "DELETE" });
  toast("Eliminado"); renderMantenimiento();
}

// ════════════════════════════════════════════════════════════════════════
//  PLANES (biblioteca global)
// ════════════════════════════════════════════════════════════════════════
async function renderPlanes() {
  status("Catálogo de planes de mantenimiento");
  const planes = await api("/api/planes");
  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-clipboard-text"></i> Planes de Mantenimiento</h1>
      <p>Catálogo reutilizable de planes por modelo de motor/coche</p>
    </div>
    <div class="section">
      <div class="card">
        <div class="card-head"><i class="ti ti-plus"></i> Crear plan nuevo</div>
        <div class="card-body">
          <div class="form-row">
            <div class="field" style="flex:1;min-width:240px"><label>Nombre del plan</label><input id="p-nom" placeholder="ej: Mercedes O-500 RSD"></div>
            <div class="field" style="flex:2;min-width:280px"><label>Descripción (opcional)</label><input id="p-desc" placeholder="Notas, marca de motor, etc"></div>
            <button class="btn btn-primary" onclick="crearPlanWeb()"><i class="ti ti-plus"></i> Crear plan</button>
          </div>
        </div>
      </div>
      <div class="section-title"><i class="ti ti-list"></i> Planes existentes</div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Plan</th><th>Descripción</th><th class="center">Tareas</th><th class="center">Vehículos</th><th class="td-action"></th></tr></thead>
          <tbody>
            ${planes.map(p => `<tr class="clickable" onclick="abrirPlan(${p.id})">
              <td><b>${p.nombre}</b></td>
              <td style="color:var(--muted);font-size:12.5px">${p.descripcion || "—"}</td>
              <td class="center"><span class="badge">${p.cant_tareas}</span></td>
              <td class="center"><span class="badge cat">${p.cant_vehiculos}</span></td>
              <td class="td-action"><button class="icon-btn" onclick="event.stopPropagation();borrarPlan(${p.id},'${p.nombre.replace(/'/g,"\\'")}')"><i class="ti ti-trash"></i></button></td>
            </tr>`).join("")}
          </tbody>
        </table>
      </div>
      <p class="hint" style="margin-top:8px"><i class="ti ti-bulb"></i> Hacé clic en un plan para ver y editar sus tareas.</p>
      <div id="plan-detalle"></div>
    </div>`;
}
async function crearPlanWeb() {
  const nom = $("#p-nom").value.trim();
  if (!nom) { toast("Ingresá un nombre", "error"); return; }
  const r = await api("/api/planes", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nombre: nom, descripcion: $("#p-desc").value.trim() })
  });
  if (r.ok) { toast("Plan creado", "success"); renderPlanes(); } else toast(r.msg, "error");
}
async function borrarPlan(id, nom) {
  if (!confirm(`¿Eliminar el plan "${nom}"?`)) return;
  const r = await api(`/api/planes/${id}`, { method: "DELETE" });
  if (r.ok) { toast("Plan eliminado"); renderPlanes(); } else toast(r.msg, "error");
}
async function abrirPlan(pid) {
  planActual = pid;
  const tareas = await api(`/api/planes/${pid}/tareas`);
  const planes = await api("/api/planes");
  const plan = planes.find(p => p.id === pid);

  // Si hay coche seleccionado y tiene ESTE plan, traer su estado real
  let estadoTareas = {};
  let cocheInfo = null;
  if (cocheActual) {
    const planVeh = await api(`/api/vehiculos/${cocheActual.id}/plan`);
    if (planVeh.plan && planVeh.plan.plan_id === pid) {
      const ed = await api(`/api/vehiculos/${cocheActual.id}/estado_mantenimiento`);
      cocheInfo = { patente: cocheActual.patente, km_actual: planVeh.km_actual };
      (ed.estado || []).forEach(e => { estadoTareas[e.tarea_id] = e; });
    }
  }

  $("#plan-detalle").innerHTML = `
    <div class="section-title"><i class="ti ti-tool"></i> Tareas del plan: ${plan.nombre}</div>
    ${cocheInfo ? `
      <div style="background:linear-gradient(135deg, var(--info-bg) 0%, var(--surface) 100%);border:1px solid var(--info-bd);border-radius:var(--radius-sm);padding:12px 16px;margin-bottom:14px;display:flex;align-items:center;gap:12px">
        <i class="ti ti-info-circle" style="font-size:20px;color:var(--info)"></i>
        <div style="font-size:13px">
          Mostrando el estado real de <b>${cocheInfo.patente}</b>
          (odómetro: <b>${fmtNum(cocheInfo.km_actual)} km</b>)
        </div>
      </div>
    ` : `
      <p class="hint" style="margin-bottom:10px">
        <i class="ti ti-bulb"></i>
        Seleccioná un coche que tenga este plan para ver el porcentaje de uso real en cada tarea.
      </p>
    `}
    <div class="card">
      <div class="card-head"><i class="ti ti-plus"></i> Agregar tarea</div>
      <div class="card-body">
        <div class="form-row">
          <div class="field" style="flex:1;min-width:200px"><label>Tarea</label><input id="t-nom" placeholder="ej: Cambio de aceite de motor"></div>
          <div class="field"><label>Intervalo (km)</label><input id="t-km" placeholder="15000" style="width:140px"></div>
          <div class="field"><label>Categoría</label><input id="t-cat" placeholder="ej: Lubricación" style="width:180px"></div>
          <button class="btn btn-primary" onclick="agregarTareaWeb()"><i class="ti ti-plus"></i> Agregar</button>
        </div>
      </div>
    </div>
    <div class="table-wrap" style="margin-top:14px">
      <table>
        <thead><tr>
          <th>Tarea</th><th>Categoría</th><th class="num">Intervalo (km)</th>
          <th style="min-width:220px">Estado de uso</th>
          <th class="td-action"></th>
        </tr></thead>
        <tbody>${tareas.map(t => {
          const e = estadoTareas[t.id];
          let celdaEstado;
          if (e) {
            const labelEst = { optimo:'Óptimo', bueno:'Bueno', regular:'Regular', atencion:'Atención', vencido:'Vencido' };
            celdaEstado = `
              <div style="display:flex;align-items:center;gap:10px">
                <div class="grad-bar-wrap" style="flex:1;max-width:140px">
                  <div class="grad-bar estado-${e.estado_grad}" style="width:${e.porcentaje_visual}%"></div>
                </div>
                <span class="grad-badge grad-${e.estado_grad}" style="white-space:nowrap">
                  <span class="dot"></span> ${e.porcentaje.toFixed(0)}%
                </span>
              </div>`;
          } else {
            celdaEstado = `<span style="color:var(--lighter);font-size:12px">—</span>`;
          }
          return `<tr>
            <td>${t.tarea}</td>
            <td>${t.categoria ? `<span class="badge cat">${t.categoria}</span>` : "—"}</td>
            <td class="num">${fmtNum(t.intervalo_km)}</td>
            <td>${celdaEstado}</td>
            <td class="td-action"><button class="icon-btn" onclick="borrarTarea(${t.id})"><i class="ti ti-trash"></i></button></td>
          </tr>`;
        }).join("")}</tbody>
      </table>
    </div>`;
  $("#plan-detalle").scrollIntoView({ behavior: "smooth" });
}
async function agregarTareaWeb() {
  const nom = $("#t-nom").value.trim();
  const km = parseInt($("#t-km").value);
  if (!nom || !km) { toast("Tarea e intervalo son obligatorios", "error"); return; }
  await api(`/api/planes/${planActual}/tareas`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tarea: nom, intervalo_km: km, categoria: $("#t-cat").value.trim() })
  });
  toast("Tarea agregada", "success"); abrirPlan(planActual);
}
async function borrarTarea(id) {
  if (!confirm("¿Eliminar esta tarea?")) return;
  await api(`/api/tareas/${id}`, { method: "DELETE" });
  toast("Tarea eliminada"); abrirPlan(planActual);
}

// ════════════════════════════════════════════════════════════════════════
//  CORRECTIVOS (averías)
// ════════════════════════════════════════════════════════════════════════
const TIPOS_FALLA = ["Motor", "Frenos", "Eléctrico", "Transmisión", "Suspensión", "Carrocería", "Neumáticos", "Aire acondicionado", "Otro"];
const ESTADOS_CORR = { pendiente: "Pendiente", en_reparacion: "En reparación", completado: "Completado" };

let correctivosTab = "por_ot";  // 'por_ot' o 'manual'

async function renderCorrectivos() {
  status("Mantenimientos correctivos / averías");
  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-alert-triangle"></i> Correctivos</h1>
      <p>Averías y reparaciones — agrupadas por orden de trabajo</p>
    </div>
    <div class="section">
      <div class="toolbar">
        <div class="tabs">
          <button class="tab-btn ${correctivosTab==='por_ot'?'active':''}" onclick="setCorrectivosTab('por_ot')"><i class="ti ti-clipboard-list"></i> Por orden de trabajo</button>
          <button class="tab-btn ${correctivosTab==='manual'?'active':''}" onclick="setCorrectivosTab('manual')"><i class="ti ti-plus"></i> Registro manual</button>
        </div>
        <button class="btn btn-ghost" style="margin-left:auto" onclick="abrirReporteCorrectivos()"><i class="ti ti-printer"></i> Imprimir por fechas</button>
      </div>
      <div id="correctivos-contenido"></div>
    </div>`;
  if (correctivosTab === "por_ot") {
    await renderCorrectivosPorOT();
  } else {
    await renderCorrectivosManual();
  }
}

function setCorrectivosTab(t) { correctivosTab = t; renderCorrectivos(); }

// Vista NUEVA: correctivos agrupados por su orden de trabajo
async function renderCorrectivosPorOT() {
  const cont = document.getElementById("correctivos-contenido");
  const grupos = await api("/api/correctivos_por_ot");
  if (!grupos.length) {
    cont.innerHTML = `<div class="empty"><i class="ti ti-mood-smile"></i>No hay correctivos en ninguna orden de trabajo.<br>¡Buena señal!</div>`;
    return;
  }
  // Total de items correctivos
  const totalItems = grupos.reduce((s, g) => s + g.items.length, 0);
  cont.innerHTML = `
    <div style="margin-bottom:16px;color:var(--muted);font-size:14px">
      <b>${totalItems}</b> trabajos correctivos en <b>${grupos.length}</b> órdenes de trabajo
    </div>
    ${grupos.map(g => {
      const coche = g.n_interno ? `Coche ${g.n_interno}` : g.patente;
      const completados = g.items.filter(i => i.estado === "completado").length;
      const colorEstado = g.estado === "cerrada" ? "success" : g.estado === "en_proceso" ? "warning" : "danger";
      return `
        <div class="card" style="margin-bottom:14px">
          <div class="card-head" style="display:flex;justify-content:space-between;align-items:center;cursor:pointer" onclick="abrirOT(${g.ot_id})">
            <span><i class="ti ti-clipboard-check"></i> OT #${g.ot_id} · ${coche} · ${g.patente}</span>
            <span style="display:flex;gap:8px;align-items:center">
              <span class="badge ${colorEstado}"><span class="dot"></span> ${LABEL_ESTADO_OT[g.estado]}</span>
              <span style="font-size:12px;color:var(--muted)">${g.fecha_apertura}</span>
            </span>
          </div>
          <div class="card-body" style="padding:0">
            <div class="table-wrap"><table>
              <thead><tr>
                <th>Falla / Trabajo</th><th>Técnico</th><th>Material necesario</th><th class="center">Estado</th>
              </tr></thead>
              <tbody>
                ${g.items.map(it => `<tr>
                  <td><b>${it.descripcion}</b></td>
                  <td style="color:var(--muted)">${it.tecnico || "—"}</td>
                  <td>${it.material_pedido || "—"}</td>
                  <td class="center">
                    <span class="badge ${it.estado === 'completado' ? 'success' : 'warning'}">
                      <span class="dot"></span> ${it.estado === 'completado' ? 'Completado' : 'Pendiente'}
                    </span>
                  </td>
                </tr>`).join("")}
              </tbody>
            </table></div>
            <div style="padding:10px 16px;font-size:12px;color:var(--muted);border-top:1px solid var(--border)">
              ${completados}/${g.items.length} completados · ${g.km ? fmtNum(g.km) + ' km' : 'sin km'} · Tocá el encabezado para abrir la OT
            </div>
          </div>
        </div>`;
    }).join("")}`;
}

// Vista vieja: registro manual de correctivos (se mantiene por si se necesita)
async function renderCorrectivosManual() {
  const cont = document.getElementById("correctivos-contenido");
  const correctivos = await api("/api/correctivos");
  const vehiculos = await api("/api/vehiculos");
  cont.innerHTML = `
      <div class="card">
        <div class="card-head"><i class="ti ti-plus"></i> Registrar avería / reparación</div>
        <div class="card-body">
          <div class="form-row">
            <div class="field" style="min-width:200px"><label>Vehículo *</label>
              <select id="co-veh">
                ${vehiculos.map(v => `<option value="${v.id}">${v.patente} — ${v.marca} ${v.modelo}</option>`).join("")}
              </select>
            </div>
            <div class="field"><label>Fecha</label><input id="co-fecha" type="date" value="${hoy()}"></div>
            <div class="field"><label>KM del coche</label><input id="co-km" placeholder="260000" style="width:130px"></div>
            <div class="field"><label>Tipo de falla *</label>
              <select id="co-tipo">${TIPOS_FALLA.map(t => `<option value="${t}">${t}</option>`).join("")}</select>
            </div>
          </div>
          <div class="form-row" style="margin-top:14px">
            <div class="field" style="flex:1;min-width:300px"><label>Descripción de la falla *</label>
              <input id="co-desc" placeholder="ej: Pastillas de freno gastadas, ruido al frenar">
            </div>
            <div class="field" style="flex:1;min-width:250px"><label>Reparación realizada</label>
              <input id="co-rep" placeholder="ej: Cambio de pastillas delanteras">
            </div>
          </div>
          <div class="form-row" style="margin-top:14px">
            <div class="field"><label>Taller</label><input id="co-taller" placeholder="Taller Asunción" style="width:200px"></div>
            <div class="field"><label>Costo (Gs.)</label><input id="co-costo" placeholder="0" style="width:150px"></div>
            <div class="field"><label>Estado</label>
              <select id="co-estado">
                <option value="pendiente">Pendiente</option>
                <option value="en_reparacion">En reparación</option>
                <option value="completado" selected>Completado</option>
              </select>
            </div>
            <button class="btn btn-primary" onclick="guardarCorrectivo()"><i class="ti ti-device-floppy"></i> Guardar</button>
          </div>
        </div>
      </div>

      <div class="section-title"><i class="ti ti-list"></i> Historial manual (${correctivos.length})</div>
      ${correctivos.length === 0 ? `
        <div class="empty"><i class="ti ti-mood-smile"></i>Sin correctivos manuales registrados.</div>
      ` : `
        <div class="table-wrap">
          <table>
            <thead><tr>
              <th>Fecha</th><th>Vehículo</th><th>Tipo</th><th>Descripción</th>
              <th class="num">KM</th><th class="num">Costo</th><th class="center">Estado</th><th class="td-action"></th>
            </tr></thead>
            <tbody>
              ${correctivos.map(c => `
                <tr>
                  <td>${c.fecha}</td>
                  <td><b>${c.patente}</b></td>
                  <td><span class="badge">${c.tipo_falla}</span></td>
                  <td title="${c.reparacion || ''}">${c.descripcion}</td>
                  <td class="num">${fmtNum(c.km)}</td>
                  <td class="num">${gs(c.costo)}</td>
                  <td class="center">
                    <span class="badge ${c.estado === 'completado' ? 'success' : c.estado === 'en_reparacion' ? 'warning' : 'danger'}">
                      <span class="dot"></span> ${ESTADOS_CORR[c.estado]}
                    </span>
                  </td>
                  <td class="td-action"><button class="icon-btn" onclick="borrarCorrectivo(${c.id})"><i class="ti ti-trash"></i></button></td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      `}`;
}
async function guardarCorrectivo() {
  const desc = $("#co-desc").value.trim();
  if (!desc) { toast("Ingresá una descripción de la falla", "error"); return; }
  const costo = ($("#co-costo").value || "0").replace(/\./g, "").replace(/,/g, ".");
  const r = await api("/api/correctivos", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      vehiculo_id: parseInt($("#co-veh").value), fecha: $("#co-fecha").value,
      km: parseFloat($("#co-km").value || 0), tipo_falla: $("#co-tipo").value,
      descripcion: desc, reparacion: $("#co-rep").value,
      taller: $("#co-taller").value, costo: costo || 0, estado: $("#co-estado").value
    })
  });
  if (r.ok) {
    toast("Correctivo registrado", "success");
    ["co-km", "co-desc", "co-rep", "co-taller", "co-costo"].forEach(id => $("#" + id).value = "");
    renderCorrectivos();
  } else toast("Error al guardar", "error");
}
async function borrarCorrectivo(id) {
  if (!confirm("¿Eliminar este registro?")) return;
  await api(`/api/correctivos/${id}`, { method: "DELETE" });
  toast("Eliminado"); renderCorrectivos();
}

// ════════════════════════════════════════════════════════════════════════
//  DOCUMENTOS (VTV, seguro, habilitación, etc.)
// ════════════════════════════════════════════════════════════════════════
const TIPOS_DOC = ["VTV", "Seguro", "Habilitación Municipal", "Habilitación DINATRAN", "Cédula Verde", "Cédula Azul", "Tacógrafo", "Otro"];

async function renderDocumentos() {
  status("Documentos y vencimientos de la flota");
  const docs = await api("/api/documentos");
  const vehiculos = await api("/api/vehiculos");
  // Calcular días hasta vencimiento y ordenar por urgencia (lo más urgente arriba)
  docs.forEach(d => d._dias = diasHasta(d.fecha_vencimiento));
  docs.sort((a, b) => a._dias - b._dias);
  // Contadores para el resumen
  const nVencidos = docs.filter(d => d._dias < 0).length;
  const nPorVencer = docs.filter(d => d._dias >= 0 && d._dias <= 30).length;
  const nAlDia = docs.filter(d => d._dias > 30).length;
  // Guardar para los filtros
  window._todosDocs = docs;
  window._vehiculosDocs = vehiculos;

  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-file-text"></i> Documentos</h1>
      <p>Control de habilitaciones, seguros y otros vencimientos</p>
    </div>
    <div class="section">
      <!-- Resumen de un vistazo -->
      <div class="metrics" style="margin-bottom:18px">
        <div class="metric" style="cursor:pointer" onclick="filtrarDocs('vencidos')">
          <div class="metric-content"><div class="metric-label">Vencidos</div>
          <div class="metric-value" style="color:var(--danger)">${nVencidos}</div></div>
        </div>
        <div class="metric" style="cursor:pointer" onclick="filtrarDocs('porvencer')">
          <div class="metric-content"><div class="metric-label">Por vencer (30 días)</div>
          <div class="metric-value" style="color:var(--warning)">${nPorVencer}</div></div>
        </div>
        <div class="metric" style="cursor:pointer" onclick="filtrarDocs('aldia')">
          <div class="metric-content"><div class="metric-label">Al día</div>
          <div class="metric-value" style="color:var(--success)">${nAlDia}</div></div>
        </div>
        <div class="metric" style="cursor:pointer" onclick="filtrarDocs('')">
          <div class="metric-content"><div class="metric-label">Total</div>
          <div class="metric-value">${docs.length}</div></div>
        </div>
      </div>

      <div class="card">
        <div class="card-head"><i class="ti ti-plus"></i> Registrar documento</div>
        <div class="card-body">
          <div class="form-row">
            <div class="field" style="min-width:200px"><label>Vehículo *</label>
              <select id="d-veh">
                ${vehiculos.map(v => `<option value="${v.id}">${v.patente} — ${v.marca}</option>`).join("")}
              </select>
            </div>
            <div class="field"><label>Tipo *</label>
              <select id="d-tipo">${TIPOS_DOC.map(t => `<option value="${t}">${t}</option>`).join("")}</select>
            </div>
            <div class="field"><label>Nombre / descripción</label><input id="d-nom" placeholder="VTV 2026" style="width:180px"></div>
            <div class="field"><label>Emisión</label><input id="d-emi" type="date"></div>
            <div class="field"><label>Vencimiento *</label><input id="d-venc" type="date"></div>
          </div>
          <div class="form-row" style="margin-top:14px">
            <div class="field" style="flex:1;min-width:200px"><label>Proveedor / aseguradora</label><input id="d-prov" placeholder="ej: Senatran, La Consolidada"></div>
            <div class="field"><label>Costo (Gs.)</label><input id="d-costo" placeholder="0" style="width:150px"></div>
            <div class="field" style="flex:1;min-width:200px"><label>Observaciones</label><input id="d-obs" placeholder="Notas internas"></div>
            <button class="btn btn-primary" onclick="guardarDocumento()"><i class="ti ti-device-floppy"></i> Guardar</button>
          </div>
        </div>
      </div>

      <!-- Barra de filtros y búsqueda -->
      <div class="toolbar" style="margin-top:6px">
        <button class="btn btn-ghost" onclick="abrirReporteDocumentos()"><i class="ti ti-printer"></i> Imprimir por vencer</button>
        <button class="btn ${docVista==='lista'?'btn-primary':'btn-ghost'}" onclick="setDocVista('lista')"><i class="ti ti-list"></i> Lista</button>
        <button class="btn ${docVista==='vehiculo'?'btn-primary':'btn-ghost'}" onclick="setDocVista('vehiculo')"><i class="ti ti-bus"></i> Por vehículo</button>
        <select id="doc-filtro-tipo" onchange="renderDocsTabla()" style="padding:9px;border-radius:9px;border:1.5px solid var(--border)">
          <option value="">Todos los tipos</option>
          ${TIPOS_DOC.map(t => `<option value="${t}">${t}</option>`).join("")}
        </select>
        <input id="doc-buscar" oninput="renderDocsTabla()" placeholder="Buscar por patente..." style="padding:9px;border-radius:9px;border:1.5px solid var(--border);flex:1;min-width:160px">
      </div>

      <div id="docs-contenido"></div>
    </div>`;
  renderDocsTabla();
}

// Estado de la vista de documentos
let docVista = "lista";
let docFiltroEstado = "";
function setDocVista(v) { docVista = v; renderDocumentos(); }
function filtrarDocs(estado) { docFiltroEstado = estado; renderDocsTabla(); }

// Renderiza la tabla/agrupación según filtros activos
function renderDocsTabla() {
  const cont = document.getElementById("docs-contenido");
  if (!cont) return;
  let docs = (window._todosDocs || []).slice();
  const filtroTipo = (document.getElementById("doc-filtro-tipo") || {}).value || "";
  const buscar = ((document.getElementById("doc-buscar") || {}).value || "").toLowerCase().trim();

  // Aplicar filtros
  if (docFiltroEstado === "vencidos") docs = docs.filter(d => d._dias < 0);
  else if (docFiltroEstado === "porvencer") docs = docs.filter(d => d._dias >= 0 && d._dias <= 30);
  else if (docFiltroEstado === "aldia") docs = docs.filter(d => d._dias > 30);
  if (filtroTipo) docs = docs.filter(d => d.tipo === filtroTipo);
  if (buscar) docs = docs.filter(d => (d.patente || "").toLowerCase().includes(buscar));

  const filtroLabel = { vencidos: "Vencidos", porvencer: "Por vencer", aldia: "Al día" }[docFiltroEstado] || "Todos";

  if (docs.length === 0) {
    cont.innerHTML = `<div class="empty"><i class="ti ti-file-off"></i>No hay documentos ${docFiltroEstado || filtroTipo || buscar ? "con ese filtro" : "registrados"}.</div>`;
    return;
  }

  if (docVista === "vehiculo") {
    cont.innerHTML = renderDocsPorVehiculo(docs, filtroLabel);
  } else {
    cont.innerHTML = renderDocsLista(docs, filtroLabel);
  }
}

function _badgeDoc(dias) {
  if (dias < 0) return `<span class="badge danger"><span class="dot"></span> Vencido hace ${Math.abs(dias)} días</span>`;
  if (dias <= 30) return `<span class="badge warning"><span class="dot"></span> En ${dias} días</span>`;
  return `<span class="badge success"><span class="dot"></span> ${dias} días</span>`;
}

function _filaDoc(d) {
  return `<tr>
    <td><b>${d.patente}</b></td>
    <td><span class="badge cat">${d.tipo}</span></td>
    <td>${d.nombre || "—"}</td>
    <td>${d.fecha_vencimiento}</td>
    <td class="center">${_badgeDoc(d._dias)}</td>
    <td style="color:var(--muted)">${d.proveedor || "—"}</td>
    <td class="num">${gs(d.costo)}</td>
    <td class="td-action" style="white-space:nowrap">
      <button class="icon-btn" title="Renovar" onclick="renovarDocumento(${d.id})"><i class="ti ti-refresh"></i></button>
      <button class="icon-btn" title="Eliminar" onclick="borrarDocumento(${d.id})"><i class="ti ti-trash"></i></button>
    </td>
  </tr>`;
}

function renderDocsLista(docs, filtroLabel) {
  return `
    <div class="section-title"><i class="ti ti-calendar"></i> Documentos — ${filtroLabel} (${docs.length})</div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th>Vehículo</th><th>Tipo</th><th>Nombre</th>
          <th>Vencimiento</th><th class="center">Estado</th>
          <th>Proveedor</th><th class="num">Costo</th><th class="td-action"></th>
        </tr></thead>
        <tbody>${docs.map(_filaDoc).join("")}</tbody>
      </table>
    </div>`;
}

function renderDocsPorVehiculo(docs, filtroLabel) {
  // Agrupar por patente
  const grupos = {};
  docs.forEach(d => {
    const key = d.patente || "Sin patente";
    (grupos[key] = grupos[key] || []).push(d);
  });
  // Ordenar vehículos: los que tienen algo más urgente primero
  const patentes = Object.keys(grupos).sort((a, b) => {
    const minA = Math.min(...grupos[a].map(d => d._dias));
    const minB = Math.min(...grupos[b].map(d => d._dias));
    return minA - minB;
  });
  let html = `<div class="section-title"><i class="ti ti-bus"></i> Por vehículo — ${filtroLabel} (${docs.length})</div>`;
  patentes.forEach(pat => {
    const lista = grupos[pat];
    const masUrgente = Math.min(...lista.map(d => d._dias));
    const colorBorde = masUrgente < 0 ? "var(--danger)" : masUrgente <= 30 ? "var(--warning)" : "var(--success)";
    html += `
      <div class="card" style="margin-bottom:12px;border-left:4px solid ${colorBorde}">
        <div class="card-head"><i class="ti ti-bus"></i> ${pat} <span style="color:var(--muted);font-weight:400;font-size:13px">(${lista.length} documento${lista.length>1?"s":""})</span></div>
        <div class="card-body" style="padding:0">
          <div class="table-wrap"><table>
            <tbody>
              ${lista.map(d => `<tr>
                <td><span class="badge cat">${d.tipo}</span></td>
                <td>${d.nombre || "—"}</td>
                <td>${d.fecha_vencimiento}</td>
                <td class="center">${_badgeDoc(d._dias)}</td>
                <td style="color:var(--muted)">${d.proveedor || "—"}</td>
                <td class="td-action" style="white-space:nowrap">
                  <button class="icon-btn" title="Renovar" onclick="renovarDocumento(${d.id})"><i class="ti ti-refresh"></i></button>
                  <button class="icon-btn" title="Eliminar" onclick="borrarDocumento(${d.id})"><i class="ti ti-trash"></i></button>
                </td>
              </tr>`).join("")}
            </tbody>
          </table></div>
        </div>
      </div>`;
  });
  return html;
}
async function guardarDocumento() {
  const venc = $("#d-venc").value;
  if (!venc) { toast("La fecha de vencimiento es obligatoria", "error"); return; }
  const costo = ($("#d-costo").value || "0").replace(/\./g, "").replace(/,/g, ".");
  const r = await api("/api/documentos", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      vehiculo_id: parseInt($("#d-veh").value), tipo: $("#d-tipo").value,
      nombre: $("#d-nom").value, fecha_emision: $("#d-emi").value || null,
      fecha_vencimiento: venc, proveedor: $("#d-prov").value,
      costo: costo || 0, observaciones: $("#d-obs").value
    })
  });
  if (r.ok) {
    toast("Documento agregado", "success");
    ["d-nom", "d-emi", "d-venc", "d-prov", "d-costo", "d-obs"].forEach(id => $("#" + id).value = "");
    renderDocumentos();
  } else toast("Error al guardar", "error");
}
async function borrarDocumento(id) {
  if (!confirm("¿Eliminar este documento?")) return;
  await api(`/api/documentos/${id}`, { method: "DELETE" });
  toast("Eliminado"); renderDocumentos();
}

// Renovar un documento: copia los datos y solo pide la nueva fecha de vencimiento
function renovarDocumento(id) {
  const doc = (window._todosDocs || []).find(d => d.id === id);
  if (!doc) return;
  const o = document.createElement("div");
  o.className = "modal-overlay";
  o.style.cssText = "position:fixed;inset:0;background:rgba(10,15,26,0.55);z-index:1500;display:grid;place-items:center;padding:20px";
  const hoy = new Date().toISOString().slice(0, 10);
  o.innerHTML = `
    <div style="background:#fff;border-radius:16px;max-width:460px;width:100%;padding:24px;box-shadow:0 20px 60px rgba(0,0,0,0.3)">
      <h2 style="font-size:18px;color:var(--brand-blue);margin:0 0 6px;display:flex;align-items:center;gap:8px"><i class="ti ti-refresh"></i> Renovar documento</h2>
      <p style="font-size:13px;color:var(--muted);margin:0 0 4px">${doc.patente} · ${doc.tipo}${doc.nombre ? " · " + doc.nombre : ""}</p>
      <p style="font-size:12px;color:var(--muted);margin:0 0 18px">Vencimiento actual: ${doc.fecha_vencimiento}. Se crea un documento nuevo con los mismos datos y la nueva fecha.</p>
      <div style="display:flex;gap:12px;margin-bottom:14px">
        <div style="flex:1">
          <label style="font-size:12.5px;font-weight:600;display:block;margin-bottom:6px">Nueva emisión</label>
          <input type="date" id="ren-emi" value="${hoy}" style="width:100%;padding:10px;border:1.5px solid var(--border);border-radius:9px;font-size:15px">
        </div>
        <div style="flex:1">
          <label style="font-size:12.5px;font-weight:600;display:block;margin-bottom:6px">Nuevo vencimiento *</label>
          <input type="date" id="ren-venc" style="width:100%;padding:10px;border:1.5px solid var(--border);border-radius:9px;font-size:15px">
        </div>
      </div>
      <div style="margin-bottom:18px">
        <label style="font-size:12.5px;font-weight:600;display:block;margin-bottom:6px">Costo de la renovación (Gs.)</label>
        <input id="ren-costo" placeholder="0" value="${doc.costo || ''}" style="width:100%;padding:10px;border:1.5px solid var(--border);border-radius:9px;font-size:15px">
      </div>
      <div style="display:flex;gap:10px;justify-content:flex-end">
        <button class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancelar</button>
        <button class="btn btn-primary" onclick="confirmarRenovar(${id}, this)"><i class="ti ti-check"></i> Renovar</button>
      </div>
    </div>`;
  o.onclick = (e) => { if (e.target === o) o.remove(); };
  document.body.appendChild(o);
}

async function confirmarRenovar(id, btn) {
  const doc = (window._todosDocs || []).find(d => d.id === id);
  if (!doc) return;
  const venc = document.getElementById("ren-venc").value;
  const emi = document.getElementById("ren-emi").value;
  if (!venc) { toast("Poné la nueva fecha de vencimiento", "error"); return; }
  const costo = (document.getElementById("ren-costo").value || "0").replace(/\./g, "").replace(/,/g, ".");
  const r = await api("/api/documentos", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      vehiculo_id: doc.vehiculo_id, tipo: doc.tipo, nombre: doc.nombre,
      fecha_emision: emi || null, fecha_vencimiento: venc,
      proveedor: doc.proveedor, costo: costo || 0,
      observaciones: doc.observaciones || ""
    })
  });
  if (r.ok) {
    toast("Documento renovado", "success");
    btn.closest(".modal-overlay").remove();
    renderDocumentos();
  } else toast("Error al renovar", "error");
}

// Modal de fechas para el PDF de documentos por vencer
function abrirReporteDocumentos() {
  const hoy = new Date().toISOString().slice(0, 10);
  const en60 = new Date(Date.now() + 60 * 86400000).toISOString().slice(0, 10);
  const o = document.createElement("div");
  o.className = "modal-overlay";
  o.style.cssText = "position:fixed;inset:0;background:rgba(10,15,26,0.55);z-index:1500;display:grid;place-items:center;padding:20px";
  o.innerHTML = `
    <div style="background:#fff;border-radius:16px;max-width:440px;width:100%;padding:24px;box-shadow:0 20px 60px rgba(0,0,0,0.3)">
      <h2 style="font-size:18px;color:var(--brand-blue);margin:0 0 6px;display:flex;align-items:center;gap:8px"><i class="ti ti-printer"></i> Documentos por vencer</h2>
      <p style="font-size:13px;color:var(--muted);margin:0 0 18px">Genera un PDF con los documentos que vencen hasta la fecha que elijas (incluye los ya vencidos).</p>
      <div style="margin-bottom:18px">
        <label style="font-size:12.5px;font-weight:600;display:block;margin-bottom:6px">Mostrar vencimientos hasta:</label>
        <input type="date" id="doc-hasta" value="${en60}" style="width:100%;padding:10px;border:1.5px solid var(--border);border-radius:9px;font-size:15px">
      </div>
      <div style="display:flex;gap:10px;justify-content:flex-end">
        <button class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancelar</button>
        <button class="btn btn-primary" onclick="generarReporteDocumentos(this)"><i class="ti ti-download"></i> Generar PDF</button>
      </div>
    </div>`;
  o.onclick = (e) => { if (e.target === o) o.remove(); };
  document.body.appendChild(o);
}

function generarReporteDocumentos(btn) {
  const hasta = document.getElementById("doc-hasta").value;
  if (!hasta) { toast("Elegí una fecha", "error"); return; }
  window.open(`/api/documentos_pdf?hasta=${hasta}`, "_blank");
  btn.closest(".modal-overlay").remove();
}

// ─── Arranque ───────────────────────────────────────────────────────────
setCoche(null);
if (window.USUARIO_ROL === "compras") {
  // Compras ve su sección + Órdenes de Trabajo (las carga) + Inventario Repuestos (repone)
  const seccionesCompras = ["compras", "ots", "repuestos", "historial_carga"];
  document.querySelectorAll(".nav-item").forEach(b => {
    if (!seccionesCompras.includes(b.dataset.sec)) b.style.display = "none";
  });
  document.querySelectorAll(".nav-section").forEach(s => {
    const t = s.textContent.trim();
    if (t !== "Compras" && t !== "Taller") s.style.display = "none";
  });
  document.querySelector('.nav-item[data-sec="compras"]')?.classList.add("active");
  renderCompras();
} else if (window.USUARIO_ROL === "auditor") {
  // El auditor solo ve la sección de Auditoría (historial + combustible)
  const seccionesAuditor = ["historial", "combustible"];
  document.querySelectorAll(".nav-item").forEach(b => {
    if (!seccionesAuditor.includes(b.dataset.sec)) b.style.display = "none";
  });
  document.querySelectorAll(".nav-section").forEach(s => {
    if (s.textContent.trim() !== "Auditoría") s.style.display = "none";
  });
  document.querySelector('.nav-item[data-sec="combustible"]')?.classList.add("active");
  renderCombustible();
} else {
  renderDashboard();
}


// ════════════════════════════════════════════════════════════════════════
//  NEUMÁTICOS (por vehículo - vista con esquema visual)
// ════════════════════════════════════════════════════════════════════════

const ESTADO_GRAD_LABEL = {
  optimo: "Óptimo", bueno: "Bueno", regular: "Regular",
  atencion: "Atención", vencido: "Vencido"
};

// Confirmar que la config automática es correcta (saca el aviso)
async function confirmarConfig(vid) {
  const data = await api(`/api/vehiculos/${vid}/neumaticos`);
  const r = await api(`/api/vehiculos/${vid}/config_neumaticos`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ configuracion: data.configuracion })
  });
  if (r.ok) { toast("Configuración confirmada", "success"); renderNeumaticos(); }
}

// Abrir selector para cambiar la configuración de ruedas del vehículo
async function cambiarConfigNeumaticos(vid, actual) {
  const configs = await api("/api/configs_neumaticos");
  const o = document.createElement("div");
  o.className = "modal-overlay";
  o.style.cssText = "position:fixed;inset:0;background:rgba(10,15,26,0.55);z-index:1500;display:grid;place-items:center;padding:20px";
  o.innerHTML = `
    <div style="background:#fff;border-radius:16px;max-width:480px;width:100%;padding:24px;box-shadow:0 20px 60px rgba(0,0,0,0.3)">
      <h2 style="font-size:18px;color:var(--brand-blue);margin:0 0 6px;display:flex;align-items:center;gap:8px"><i class="ti ti-settings"></i> Configuración de ruedas</h2>
      <p style="font-size:13px;color:var(--muted);margin:0 0 18px">Elegí cómo es este vehículo. El cambio afecta solo a esta unidad. Recordá: adelante 1 rueda por lado, atrás gemelas.</p>
      <div style="display:flex;flex-direction:column;gap:10px;margin-bottom:18px">
        ${configs.map(c => `
          <label style="display:flex;align-items:center;gap:12px;padding:13px 14px;border:1.5px solid ${c.valor===actual?'var(--brand-blue)':'var(--border)'};border-radius:11px;cursor:pointer;background:${c.valor===actual?'#eaf2fb':'#fff'}">
            <input type="radio" name="cfg-neu" value="${c.valor}" ${c.valor===actual?'checked':''} style="width:18px;height:18px">
            <div style="flex:1">
              <div style="font-weight:600;font-size:14px">${c.label.split('—')[0].trim()}</div>
              <div style="font-size:12px;color:var(--muted)">${c.ruedas} ruedas en total</div>
            </div>
            <span class="badge cat">${c.ruedas}</span>
          </label>
        `).join("")}
      </div>
      <p style="font-size:11.5px;color:var(--muted);margin:0 0 16px"><i class="ti ti-info-circle"></i> Si cambiás la cantidad de ruedas, las posiciones se rearman. Las cubiertas instaladas en posiciones que ya no existan quedarán libres.</p>
      <div style="display:flex;gap:10px;justify-content:flex-end">
        <button class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancelar</button>
        <button class="btn btn-primary" onclick="guardarCambioConfig(${vid}, this)"><i class="ti ti-check"></i> Guardar</button>
      </div>
    </div>`;
  o.onclick = (e) => { if (e.target === o) o.remove(); };
  document.body.appendChild(o);
}

async function guardarCambioConfig(vid, btn) {
  const sel = document.querySelector('input[name="cfg-neu"]:checked');
  if (!sel) { toast("Elegí una configuración", "error"); return; }
  const r = await api(`/api/vehiculos/${vid}/config_neumaticos`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ configuracion: sel.value })
  });
  if (r.ok) {
    toast("Configuración actualizada", "success");
    btn.closest(".modal-overlay").remove();
    renderNeumaticos();
  } else toast("Error al guardar", "error");
}

// ════════════════════════════════════════════════════════════════════════
//  NEUMÁTICOS — plano interactivo con drag & drop
// ════════════════════════════════════════════════════════════════════════

// Coordenadas de cada posición según configuración (bus visto desde arriba).
// Reusa el mismo mapa de layouts que ya existía, centralizado acá.
// ─── Layouts del bus (vista superior, versión robusta) ───
// Cada layout: tamaño del lienzo, caja de la carrocería, líneas de eje, y
// las posiciones con su coordenada central (cx,cy) y etiqueta legible.
// 'lado' indica si la etiqueta va arriba ('top') o abajo ('bot') de la rueda.
const BUS_LAYOUTS = {
  "4x2": { w: 480, h: 300, bus:{x:48,y:70,w:384,h:160}, ejes:[150,360], pos:{
    "DI":{x:108,y:55,lado:"top",l:"Dir. izq"},"DD":{x:108,y:245,lado:"bot",l:"Dir. der"},
    "TI-Ext":{x:392,y:55,lado:"top",l:"Tra. izq"},"TD-Ext":{x:392,y:245,lado:"bot",l:"Tra. der"} } },

  "6x2": { w: 620, h: 320, bus:{x:52,y:72,w:516,h:176}, ejes:[170,430,510], pos:{
    "DI":{x:120,y:54,lado:"top",l:"Dir. izq"},"DD":{x:120,y:266,lado:"bot",l:"Dir. der"},
    "TI-Ext":{x:404,y:48,lado:"top",l:"Tra. izq E"},"TI-Int":{x:404,y:96,lado:"mid",l:""},
    "TD-Ext":{x:404,y:272,lado:"bot",l:"Tra. der E"},"TD-Int":{x:404,y:224,lado:"mid",l:""} } },

  "6x2/3": { w: 700, h: 320, bus:{x:52,y:72,w:596,h:176}, ejes:[170,400,560], pos:{
    "DI":{x:120,y:54,lado:"top",l:"Dir. izq"},"DD":{x:120,y:266,lado:"bot",l:"Dir. der"},
    "TI-Ext":{x:360,y:48,lado:"top",l:"Tra. izq E"},"TI-Int":{x:360,y:96,lado:"mid",l:""},
    "TD-Ext":{x:360,y:272,lado:"bot",l:"Tra. der E"},"TD-Int":{x:360,y:224,lado:"mid",l:""},
    "AI":{x:600,y:54,lado:"top",l:"Aux. izq"},"AD":{x:600,y:266,lado:"bot",l:"Aux. der"} } },

  "8x2": { w: 760, h: 320, bus:{x:52,y:72,w:656,h:176}, ejes:[170,420,580], pos:{
    "DI":{x:120,y:54,lado:"top",l:"Dir. izq"},"DD":{x:120,y:266,lado:"bot",l:"Dir. der"},
    "TI-Ext":{x:400,y:48,lado:"top",l:"Tra. izq E"},"TI-Int":{x:400,y:96,lado:"mid",l:""},
    "TD-Ext":{x:400,y:272,lado:"bot",l:"Tra. der E"},"TD-Int":{x:400,y:224,lado:"mid",l:""},
    "AI-Ext":{x:620,y:48,lado:"top",l:"Aux. izq E"},"AI-Int":{x:620,y:96,lado:"mid",l:""},
    "AD-Ext":{x:620,y:272,lado:"bot",l:"Aux. der E"},"AD-Int":{x:620,y:224,lado:"mid",l:""} } },

  "4patas": { w: 780, h: 330, bus:{x:52,y:76,w:676,h:180}, ejes:[180,420,580], pos:{
    "DI":{x:124,y:56,lado:"top",l:"Dir. izq"},"DD":{x:124,y:276,lado:"bot",l:"Dir. der"},
    "TI-Ext":{x:400,y:50,lado:"top",l:"Tra. izq E"},"TI-Int":{x:400,y:100,lado:"mid",l:""},
    "TD-Ext":{x:400,y:282,lado:"bot",l:"Tra. der E"},"TD-Int":{x:400,y:232,lado:"mid",l:""},
    "AI":{x:540,y:56,lado:"top",l:"Aux. izq"},"AD":{x:540,y:276,lado:"bot",l:"Aux. der"},
    "RI":{x:660,y:56,lado:"top",l:"Ref. izq"},"RD":{x:660,y:276,lado:"bot",l:"Ref. der"} } },

  "camioneta": { w: 460, h: 290, bus:{x:48,y:74,w:364,h:150}, ejes:[150,350], pos:{
    "DI":{x:108,y:56,lado:"top",l:"Del. izq"},"DD":{x:108,y:240,lado:"bot",l:"Del. der"},
    "TI-Ext":{x:392,y:56,lado:"top",l:"Tra. izq"},"TD-Ext":{x:392,y:240,lado:"bot",l:"Tra. der"} } },

  "2ejes": { w: 520, h: 320, bus:{x:52,y:72,w:416,h:176}, ejes:[170,400], pos:{
    "DI":{x:120,y:54,lado:"top",l:"Dir. izq"},"DD":{x:120,y:266,lado:"bot",l:"Dir. der"},
    "TI-Ext":{x:404,y:48,lado:"top",l:"Tra. izq E"},"TI-Int":{x:404,y:96,lado:"mid",l:""},
    "TD-Ext":{x:404,y:272,lado:"bot",l:"Tra. der E"},"TD-Int":{x:404,y:224,lado:"mid",l:""} } },

  "3ejes": { w: 680, h: 340, bus:{x:52,y:84,w:576,h:172}, ejes:[170,420,560], pos:{
    "DI":{x:120,y:62,lado:"top",l:"Dir. izq"},"DD":{x:120,y:278,lado:"bot",l:"Dir. der"},
    "MI-Ext":{x:400,y:56,lado:"top",l:"Med. izq E"},"MI-Int":{x:400,y:106,lado:"mid",l:""},
    "MD-Ext":{x:400,y:284,lado:"bot",l:"Med. der E"},"MD-Int":{x:400,y:234,lado:"mid",l:""},
    "TI-Ext":{x:600,y:62,lado:"top",l:"Tra. izq"},"TD-Ext":{x:600,y:278,lado:"bot",l:"Tra. der"} } },

  "4ejes": { w: 760, h: 320, bus:{x:52,y:72,w:656,h:176}, ejes:[150,250,470,610], pos:{
    "D1I":{x:110,y:54,lado:"top",l:"Dir1 izq"},"D1D":{x:110,y:266,lado:"bot",l:"Dir1 der"},
    "D2I":{x:200,y:54,lado:"top",l:"Dir2 izq"},"D2D":{x:200,y:266,lado:"bot",l:"Dir2 der"},
    "MI-Ext":{x:450,y:48,lado:"top",l:"Pen. izq E"},"MI-Int":{x:450,y:96,lado:"mid",l:""},
    "MD-Ext":{x:450,y:272,lado:"bot",l:"Pen. der E"},"MD-Int":{x:450,y:224,lado:"mid",l:""},
    "TI-Ext":{x:620,y:54,lado:"top",l:"Tra. izq"},"TD-Ext":{x:620,y:266,lado:"bot",l:"Tra. der"} } },
};

const COLOR_DESGASTE = {
  optimo:   { fill:"#C0DD97", stroke:"#3B6D11", text:"#27500A" },
  bueno:    { fill:"#D9ECA8", stroke:"#65A30D", text:"#3B6D11" },
  regular:  { fill:"#FEF08A", stroke:"#CA8A04", text:"#854D0E" },
  atencion: { fill:"#FDBA74", stroke:"#EA580C", text:"#9A3412" },
  vencido:  { fill:"#FCA5A5", stroke:"#DC2641", text:"#991B1B" },
};

// Estado del drag en curso
let neuDrag = null;  // { tipo:'stock'|'rueda', neumaticoId, posicionOrigen, codigo, kmActualBus }

async function renderNeumaticos() {
  const v = cocheActual;
  status(`Neumáticos del coche ${v.patente}`);
  const data = await api(`/api/vehiculos/${v.id}/neumaticos`);

  if (!data.configuracion) {
    content.innerHTML = `
      <div class="page-header">
        <h1><i class="ti ti-disc"></i> Neumáticos · ${v.patente}</h1>
        <p>${v.marca} ${v.modelo}</p>
      </div>
      <div class="section">
        <div class="card">
          <div class="card-head"><i class="ti ti-alert-triangle" style="color:var(--warning)"></i> Sin configuración</div>
          <div class="card-body">
            <p>Este vehículo no tiene un plan de mantenimiento asignado, o el plan no tiene configuración de neumáticos.</p>
            <p style="margin-top:8px;font-size:13px;color:var(--muted)">Andá a <b>Preventivo</b> y asignale un plan al coche. La configuración de neumáticos se asocia automáticamente al modelo del chasis.</p>
          </div>
        </div>
      </div>`;
    return;
  }

  // Disponibles para el panel lateral
  const disponibles = await api("/api/neumaticos?estado=disponible");

  const avisoVerificar = (data.verificado === 0) ? `
    <div class="neu-aviso-verif">
      <i class="ti ti-alert-triangle"></i>
      <div style="flex:1">
        <b>Verificá esta configuración</b>
        <p>El sistema asignó <b>${data.configuracion}</b> según los ejes. Confirmá o cambiala.</p>
      </div>
      <button class="btn btn-primary" onclick="confirmarConfig(${v.id})"><i class="ti ti-check"></i> Es correcta</button>
    </div>` : "";

  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-disc"></i> Neumáticos · ${v.patente}</h1>
      <p>${v.marca} ${v.modelo} — arrastrá las cubiertas al bus</p>
    </div>
    <div class="section">
      ${avisoVerificar}

      <div style="display:flex;justify-content:flex-end;gap:8px;margin-bottom:14px">
        <button class="btn btn-ghost btn-sm" onclick="cambiarConfigNeumaticos(${v.id}, '${data.configuracion}')"><i class="ti ti-settings"></i> Cambiar configuración</button>
      </div>

      <!-- PLANO INTERACTIVO -->
      <div class="neu-board">
        <div class="neu-bus-zone">
          <div class="neu-bus-meta">
            <span><i class="ti ti-settings-2"></i> ${data.configuracion} · ${data.neumaticos.filter(n=>!n.vacia).length}/${data.neumaticos.length} ruedas</span>
            <span><i class="ti ti-ruler-2"></i> ${data.medida || "—"}</span>
            <span><i class="ti ti-gauge"></i> ${fmtNum(data.km_actual_vehiculo)} km</span>
          </div>
          <div id="neu-svg-wrap" class="neu-svg-wrap">${generarSvgBusDrag(data)}</div>
          <div class="neu-leyenda">
            <span><i class="ti ti-circle-filled" style="color:#3B6D11"></i> nueva</span>
            <span><i class="ti ti-circle-filled" style="color:#CA8A04"></i> media</span>
            <span><i class="ti ti-circle-filled" style="color:#DC2641"></i> cambiar</span>
            <span class="neu-leyenda-tip"><i class="ti ti-hand-finger"></i> arrastrá entre ruedas para rotar</span>
          </div>
        </div>

        <div class="neu-stock-zone" id="neu-stock-zone">
          <div class="neu-stock-head">
            <i class="ti ti-stack-2"></i> En stock
            <span class="neu-stock-count">${disponibles.length}</span>
          </div>
          <div id="neu-stock-list" class="neu-stock-list">
            ${disponibles.length === 0
              ? `<div class="neu-stock-empty"><i class="ti ti-package-off"></i>No hay cubiertas disponibles.<br><button class="btn btn-ghost btn-sm" style="margin-top:8px" onclick="irAInventarioNeu()">Ir al inventario</button></div>`
              : disponibles.map(n => tarjetaStock(n)).join("")}
          </div>
          <div class="neu-retirar-zone" id="neu-retirar-zone">
            <i class="ti ti-arrow-down"></i> Soltá acá para retirar del bus
          </div>
        </div>
      </div>

      <!-- DETALLE POR POSICIÓN (respaldo) -->
      <div class="section-title"><i class="ti ti-list"></i> Detalle por posición</div>
      <div class="tire-list">
        ${data.neumaticos.map(n => renderTireCard(n, v.id)).join("")}
      </div>

      <div class="section-title"><i class="ti ti-spare-tire"></i> Cubiertas auxiliares a bordo (Trucky)</div>
      <div id="trucky-section"></div>
    </div>`;

  activarDragNeumaticos(v.id, data.km_actual_vehiculo);
  cargarTruckies(v.id);
}

// Tarjeta de cubierta en el panel de stock (arrastrable)
function tarjetaStock(n) {
  const mm = n.profundidad_mm ? `${n.profundidad_mm}mm` : "—";
  return `
    <div class="neu-stock-card" draggable="true" data-nid="${n.id}" data-cod="${n.codigo}">
      <div class="neu-stock-disc">${mm}</div>
      <div class="neu-stock-info">
        <div class="neu-stock-cod">${n.codigo}</div>
        <div class="neu-stock-med">${n.marca || ""} ${n.medida ? "· " + n.medida : ""}</div>
        ${n.reencauches > 0 ? `<div class="neu-stock-re"><i class="ti ti-refresh"></i> ${n.reencauches}x reenc.</div>` : ""}
      </div>
    </div>`;
}

// SVG del bus con ruedas arrastrables (versión robusta y animada)
function generarSvgBusDrag(data) {
  const layout = BUS_LAYOUTS[data.configuracion] || BUS_LAYOUTS["6x2"];
  const map = {};
  data.neumaticos.forEach(n => { map[n.posicion] = n; });
  const b = layout.bus;
  const cx_frente = b.x + 46;
  const cy_centro = b.y + b.h / 2;

  // Dimensiones de las ruedas (rectángulos redondeados grandes)
  const RW = 48, RH_dir = 30, RH_gem = 28;

  let svg = `<svg class="neu-svg" viewBox="0 0 ${layout.w} ${layout.h}" xmlns="http://www.w3.org/2000/svg" preserveAspectRatio="xMidYMid meet">`;

  // Carrocería (animación de fade)
  svg += `<g class="neu-body">`;
  svg += `<rect x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}" rx="42" fill="#F8FAFC" stroke="#1E5A96" stroke-width="3"/>`;
  // Frente sombreado
  svg += `<path d="M${b.x} ${b.y+34} Q${b.x+2} ${b.y} ${b.x+42} ${b.y} L${b.x+42} ${b.y+b.h} Q${b.x+2} ${b.y+b.h} ${b.x} ${b.y+b.h-34}" fill="#1E5A96" opacity="0.10"/>`;
  // Líneas de eje
  (layout.ejes || []).forEach(ex => {
    svg += `<line x1="${ex}" y1="${b.y}" x2="${ex}" y2="${b.y+b.h}" stroke="#CBD5E1" stroke-width="1.5"/>`;
  });
  svg += `</g>`;
  svg += `<text class="neu-frente" x="${cx_frente}" y="${cy_centro + 4}" text-anchor="middle">FRENTE</text>`;

  // Ruedas
  let i = 0;
  for (const [pos, c] of Object.entries(layout.pos)) {
    const n = map[pos];
    const vacia = !n || n.vacia;
    const delay = (0.08 + i * 0.04).toFixed(2);
    const esGemela = pos.includes("-Int") || pos.includes("-Ext");
    const rh = esGemela ? RH_gem : RH_dir;
    const x = c.x - RW/2;
    const y = c.y - rh/2;

    // Etiqueta de posición (según lado)
    let lblTxt = "";
    if (c.l) {
      const lblY = c.lado === "top" ? (y - 12) : (y + rh + 18);
      lblTxt = `<text class="neu-wheel-lbl" x="${c.x}" y="${lblY}">${c.l}</text>`;
    }

    if (vacia) {
      svg += `<g class="neu-wheel neu-wheel-empty" data-pos="${pos}" style="animation-delay:${delay}s">
        <title>${pos} — vacía, soltá una cubierta acá</title>
        ${lblTxt}
        <rect class="neu-slot" x="${x}" y="${y}" width="${RW}" height="${rh}" rx="9"/>
        <text class="neu-slot-plus" x="${c.x}" y="${c.y + 6}">+</text>
      </g>`;
    } else {
      const col = COLOR_DESGASTE[n.estado_grad] || COLOR_DESGASTE.optimo;
      const pct = Math.round(n.porcentaje_uso);
      svg += `<g class="neu-wheel neu-wheel-full" data-pos="${pos}" data-nid="${n.neumatico_id}" draggable="true" style="animation-delay:${delay}s">
        <title>${n.codigo} — ${pct}% usado (${fmtNum(n.km_totales)} km)</title>
        ${lblTxt}
        <rect class="neu-tire" x="${x}" y="${y}" width="${RW}" height="${rh}" rx="9" fill="${col.fill}" stroke="${col.stroke}" stroke-width="2"/>
        <text class="neu-tire-pct" x="${c.x}" y="${c.y + 5}" fill="${col.text}">${pct}%</text>
      </g>`;
    }
    i++;
  }
  svg += `</svg>`;
  return svg;
}

// ─── Activar el drag & drop sobre el plano ───
function activarDragNeumaticos(vid, kmBus) {
  const wrap = $("#neu-svg-wrap");
  const stockList = $("#neu-stock-list");
  const retirarZone = $("#neu-retirar-zone");
  if (!wrap) return;

  // Helper: limpiar resaltados
  const limpiar = () => {
    wrap.querySelectorAll(".neu-slot.over, .neu-tire.over").forEach(e => e.classList.remove("over"));
    retirarZone?.classList.remove("over");
  };

  // 1. DRAG desde el STOCK (instalar)
  stockList?.querySelectorAll(".neu-stock-card").forEach(card => {
    card.addEventListener("dragstart", e => {
      neuDrag = { tipo: "stock", neumaticoId: +card.dataset.nid, codigo: card.dataset.cod, kmActualBus: kmBus };
      card.classList.add("dragging");
      if (e.dataTransfer) { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text", card.dataset.cod); }
    });
    card.addEventListener("dragend", () => { card.classList.remove("dragging"); limpiar(); neuDrag = null; });
  });

  // 2. DRAG desde una RUEDA instalada (rotar o retirar)
  wrap.querySelectorAll(".neu-wheel-full").forEach(w => {
    w.addEventListener("dragstart", e => {
      neuDrag = { tipo: "rueda", neumaticoId: +w.dataset.nid, posicionOrigen: w.dataset.pos, kmActualBus: kmBus };
      w.classList.add("dragging");
      if (e.dataTransfer) { e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text", w.dataset.nid); }
    });
    w.addEventListener("dragend", () => { w.classList.remove("dragging"); limpiar(); neuDrag = null; });
  });

  // 3. DROP en ruedas (vacías = instalar/rotar)
  wrap.querySelectorAll(".neu-wheel").forEach(w => {
    const slot = w.querySelector(".neu-slot, .neu-tire");
    w.addEventListener("dragover", e => {
      e.preventDefault();
      if (!neuDrag) return;
      const pos = w.dataset.pos;
      const ocupada = w.classList.contains("neu-wheel-full");
      // No resaltar la misma rueda de origen
      if (neuDrag.tipo === "rueda" && neuDrag.posicionOrigen === pos) return;
      // Solo permitir soltar en ruedas vacías (las ocupadas hay que liberarlas antes)
      if (!ocupada) slot?.classList.add("over");
    });
    w.addEventListener("dragleave", () => slot?.classList.remove("over"));
    w.addEventListener("drop", e => {
      e.preventDefault();
      slot?.classList.remove("over");
      if (!neuDrag) return;
      const pos = w.dataset.pos;
      const ocupada = w.classList.contains("neu-wheel-full");
      if (ocupada) { toast("Esa rueda está ocupada. Movela o sacala primero.", "error"); return; }
      if (neuDrag.tipo === "stock") {
        instalarPorDrag(neuDrag.neumaticoId, neuDrag.codigo, pos, vid, kmBus);
      } else if (neuDrag.tipo === "rueda") {
        if (neuDrag.posicionOrigen === pos) return;
        rotarPorDrag(neuDrag.neumaticoId, neuDrag.posicionOrigen, pos, vid, kmBus);
      }
    });
  });

  // 4. DROP en zona de retiro (solo para ruedas)
  retirarZone?.addEventListener("dragover", e => {
    e.preventDefault();
    if (neuDrag && neuDrag.tipo === "rueda") retirarZone.classList.add("over");
  });
  retirarZone?.addEventListener("dragleave", () => retirarZone.classList.remove("over"));
  retirarZone?.addEventListener("drop", e => {
    e.preventDefault();
    retirarZone.classList.remove("over");
    if (neuDrag && neuDrag.tipo === "rueda") {
      retirarPorDrag(neuDrag.neumaticoId, neuDrag.posicionOrigen, vid, kmBus);
    }
  });
}

// ─── Acción: INSTALAR (con mini-cuadro de km) ───
function instalarPorDrag(nid, codigo, posicion, vid, kmBus) {
  const o = document.createElement("div");
  o.className = "neu-mini-overlay visible";
  o.innerHTML = `
    <div class="neu-mini">
      <div class="neu-mini-titulo"><i class="ti ti-arrow-down-circle"></i> Instalar ${codigo}</div>
      <p class="neu-mini-sub">en la posición <b>${posicion}</b></p>
      <label class="neu-mini-lbl">Si la cubierta es nueva, dejá 0. Si ya tiene uso, poné los km que traía:</label>
      <input id="ni-km" class="neu-mini-input" type="text" inputmode="decimal" value="0" autofocus>
      <p class="neu-mini-help"><i class="ti ti-info-circle"></i> El bus está en ${fmtNum(kmBus)} km. La cubierta empezará a contar desde acá.</p>
      <div class="neu-mini-btns">
        <button class="btn btn-ghost" onclick="this.closest('.neu-mini-overlay').remove()">Cancelar</button>
        <button class="btn btn-primary" onclick="confirmarInstalarDrag(${nid}, '${posicion}', ${vid}, ${kmBus}, this)"><i class="ti ti-check"></i> Instalar</button>
      </div>
    </div>`;
  o.onclick = e => { if (e.target === o) o.remove(); };
  document.body.appendChild(o);
  setTimeout(() => { const i = document.getElementById("ni-km"); i?.focus(); i?.select(); }, 50);
}

async function confirmarInstalarDrag(nid, posicion, vid, kmBus, btn) {
  const kmTraia = parseFloat((document.getElementById("ni-km").value || "0").replace(/\./g, "").replace(/,/g, ".")) || 0;
  // Si la cubierta traía km, los seteamos antes de instalar (ajuste de km acumulados)
  if (kmTraia > 0) {
    await api(`/api/neumaticos/${nid}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ km_acumulados: kmTraia })
    });
  }
  const r = await api(`/api/neumaticos/${nid}/instalar`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ vehiculo_id: vid, posicion, fecha: hoy(), km_instalacion: kmBus })
  });
  btn.closest(".neu-mini-overlay").remove();
  if (r.ok) { toast("Cubierta instalada", "success"); renderNeumaticos(); }
  else toast(r.msg, "error");
}

// ─── Acción: ROTAR (mover de una rueda a otra) ───
async function rotarPorDrag(nid, posOrigen, posDestino, vid, kmBus) {
  const r = await api(`/api/neumaticos/${nid}/rotar`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ vehiculo_id: vid, nueva_posicion: posDestino, fecha: hoy(), km_vehiculo: kmBus })
  });
  if (r.ok) { toast(`Rotado: ${posOrigen} → ${posDestino}`, "success"); renderNeumaticos(); }
  else toast(r.msg, "error");
}

// ─── Acción: RETIRAR (sacar del bus) ───
function retirarPorDrag(nid, posicion, vid, kmBus) {
  const o = document.createElement("div");
  o.className = "neu-mini-overlay visible";
  o.innerHTML = `
    <div class="neu-mini">
      <div class="neu-mini-titulo"><i class="ti ti-arrow-up-circle"></i> Sacar de ${posicion}</div>
      <label class="neu-mini-lbl">¿Por qué la sacás?</label>
      <div class="neu-motivos">
        <button class="neu-motivo" data-m="desgaste" data-e="disponible"><i class="ti ti-trending-down"></i> Desgaste<small>vuelve al stock</small></button>
        <button class="neu-motivo" data-m="reencauche" data-e="reencauche"><i class="ti ti-refresh"></i> Reencauche<small>a reencauchar</small></button>
        <button class="neu-motivo" data-m="pinchazo" data-e="disponible"><i class="ti ti-alert-triangle"></i> Pinchazo<small>vuelve al stock</small></button>
        <button class="neu-motivo" data-m="baja" data-e="baja"><i class="ti ti-trash"></i> Baja<small>fin de vida</small></button>
      </div>
      <label class="neu-mini-lbl">KM del bus ahora:</label>
      <input id="nr-km" class="neu-mini-input" type="text" inputmode="decimal" value="${Math.round(kmBus)}">
      <div class="neu-mini-btns">
        <button class="btn btn-ghost" onclick="this.closest('.neu-mini-overlay').remove()">Cancelar</button>
      </div>
    </div>`;
  o.onclick = e => { if (e.target === o) o.remove(); };
  document.body.appendChild(o);
  // Los botones de motivo ejecutan el retiro directo
  o.querySelectorAll(".neu-motivo").forEach(btn => {
    btn.addEventListener("click", async () => {
      const km = parseFloat((document.getElementById("nr-km").value || "0").replace(/\./g, "").replace(/,/g, ".")) || kmBus;
      const r = await api(`/api/neumaticos/${nid}/retirar`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ fecha_retiro: hoy(), km_retiro: km, motivo: btn.dataset.m, nuevo_estado: btn.dataset.e })
      });
      o.remove();
      if (r.ok) { toast(r.msg, "success"); renderNeumaticos(); }
      else toast(r.msg, "error");
    });
  });
}

function irAInventarioNeu() {
  document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
  document.querySelector('.nav-item[data-sec="inventario_neu"]')?.classList.add("active");
  renderInventarioNeu();
}


async function cargarTruckies(vid) {
  const truckies = await api(`/api/vehiculos/${vid}/truckies`);
  const sec = $("#trucky-section");
  if (!sec) return;
  sec.innerHTML = `
    <div class="card">
      <div class="card-head">
        <i class="ti ti-disc"></i> Cubiertas de auxilio a bordo (${truckies.length})
        <button class="btn btn-primary btn-sm" style="margin-left:auto" onclick="abrirAsignarTrucky(${vid})">
          <i class="ti ti-plus"></i> Asignar trucky
        </button>
      </div>
      <div class="card-body">
        ${truckies.length === 0 ? `
          <p class="hint"><i class="ti ti-info-circle"></i>
          Este vehículo no tiene cubiertas de auxilio a bordo. Tocá <b>Asignar trucky</b> para agregar una del inventario disponible.</p>
        ` : `
          <div class="table-wrap" style="border:none;box-shadow:none">
            <table>
              <thead><tr>
                <th>Código</th><th>Marca / Modelo</th><th>Medida</th>
                <th class="num">KM acum.</th><th class="center">Reenc.</th>
                <th>Fecha asignación</th><th class="num">KM al asignar</th>
                <th class="td-action"></th>
              </tr></thead>
              <tbody>
                ${truckies.map(t => `
                  <tr>
                    <td><b>${t.codigo}</b></td>
                    <td>${t.marca || "—"} ${t.modelo || ""}</td>
                    <td style="color:var(--muted)">${t.medida || "—"}</td>
                    <td class="num">${fmtNum(t.km_acumulados)}</td>
                    <td class="center">${t.reencauches > 0 ? `<span class="badge warning">${t.reencauches}x</span>` : "—"}</td>
                    <td>${t.fecha_asignacion}</td>
                    <td class="num">${fmtNum(t.km_asignacion)}</td>
                    <td class="td-action">
                      <button class="btn btn-ghost btn-sm" onclick="usarTrucky(${t.id}, '${t.codigo}', ${vid})" title="Marcar como usada">
                        <i class="ti ti-alert-triangle"></i> Usar
                      </button>
                      <button class="icon-btn" onclick="retirarTrucky(${t.id}, ${vid})" title="Retirar"><i class="ti ti-arrow-back"></i></button>
                    </td>
                  </tr>
                `).join("")}
              </tbody>
            </table>
          </div>
        `}
      </div>
    </div>`;
}

async function abrirAsignarTrucky(vid) {
  const disponibles = await api("/api/neumaticos?estado=disponible");
  if (disponibles.length === 0) {
    if (confirm("No hay neumáticos disponibles. ¿Ir a Inventario para agregar uno?")) {
      document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
      document.querySelector('.nav-item[data-sec="inventario_neu"]').classList.add("active");
      renderInventarioNeu();
    }
    return;
  }
  const lista = disponibles.map((n, i) =>
    `${i+1}. ${n.codigo} — ${n.marca || ''} ${n.modelo || ''} ${n.medida ? '(' + n.medida + ')' : ''}`
  ).join("\n");
  const elegido = prompt(`Cubiertas disponibles:\n\n${lista}\n\nEscribí el número de la cubierta:`);
  if (!elegido) return;
  const idx = parseInt(elegido) - 1;
  if (isNaN(idx) || idx < 0 || idx >= disponibles.length) {
    toast("Número inválido", "error"); return;
  }
  const km = prompt("KM actual del vehículo al momento de asignar:", "0");
  if (km === null) return;

  const r = await api(`/api/vehiculos/${vid}/truckies`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      neumatico_id: disponibles[idx].id,
      fecha_asignacion: hoy(),
      km_asignacion: parseFloat(km) || 0
    })
  });
  if (r.ok) {
    toast("Trucky asignada", "success");
    cargarTruckies(vid);
  } else toast(r.msg, "error");
}

async function usarTrucky(tid, codigo, vid) {
  const motivo = prompt(`Usar trucky ${codigo}\n\nMotivo (ej: pinchazo en ruta):`, "Pinchazo en ruta");
  if (motivo === null) return;
  const km = prompt("KM del vehículo al momento del uso:", "0");
  if (km === null) return;

  const r = await api(`/api/truckies/${tid}/usar`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ fecha_uso: hoy(), km_uso: parseFloat(km) || 0, motivo })
  });
  if (r.ok) {
    toast("Trucky marcada como usada", "success");
    cargarTruckies(vid);
  } else toast(r.msg, "error");
}

async function retirarTrucky(tid, vid) {
  if (!confirm("¿Retirar esta trucky del coche y devolverla al inventario?")) return;
  const r = await api(`/api/truckies/${tid}/retirar`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  if (r.ok) {
    toast("Trucky retirada", "success");
    cargarTruckies(vid);
  } else toast(r.msg, "error");
}

function renderTireCard(n, vid) {
  if (n.vacia) {
    return `<div class="tire-card vacia">
      <div class="tire-card-head">
        <div>
          <div class="tire-card-pos">${n.posicion}</div>
          <div class="tire-card-code" style="color:var(--muted)">${n.posicion_nombre}</div>
        </div>
      </div>
      <div class="tire-card-info">Sin neumático asignado</div>
      <div class="tire-card-actions">
        <button class="btn btn-primary btn-sm" onclick="abrirInstalar('${n.posicion}', ${vid})">
          <i class="ti ti-plus"></i> Instalar
        </button>
      </div>
    </div>`;
  }
  return `<div class="tire-card estado-${n.estado_grad}">
    <div class="tire-card-head">
      <div>
        <div class="tire-card-pos">${n.posicion} · ${n.posicion_nombre}</div>
        <div class="tire-card-code">${n.codigo}</div>
        <div class="tire-card-info">${n.marca || "—"} ${n.modelo || ""} · ${n.medida || ""}</div>
        ${n.reencauches > 0 ? `<div class="tire-card-info"><i class="ti ti-refresh"></i> Reencauchado ${n.reencauches}x</div>` : ""}
      </div>
      <span class="grad-badge grad-${n.estado_grad}"><span class="dot"></span> ${ESTADO_GRAD_LABEL[n.estado_grad]}</span>
    </div>
    <div class="grad-bar-wrap" style="margin-top:6px">
      <div class="grad-bar estado-${n.estado_grad}" style="width:${n.porcentaje_visual}%"></div>
    </div>
    <div class="tire-card-stats">
      <div>
        <div class="tire-card-pct">${n.porcentaje_uso.toFixed(1)}%</div>
        <div class="tire-card-km">${fmtNum(n.km_totales)} / ${fmtNum(n.vida_util_km)} km</div>
      </div>
      <div style="text-align:right">
        <div class="tire-card-pct" style="color:var(--muted);font-size:13px">${fmtNum(n.km_restantes)}</div>
        <div class="tire-card-km">km restantes</div>
      </div>
    </div>
    <div class="tire-card-actions">
      <button class="btn btn-ghost btn-sm" onclick="abrirRetirar(${n.neumatico_id}, '${n.codigo}', ${n.km_totales}, '${n.posicion}')">
        <i class="ti ti-arrow-out-right"></i> Retirar
      </button>
    </div>
  </div>`;
}


// SVG del bus con neumáticos en sus posiciones

// Modal/form para instalar un neumático en una posición
async function abrirInstalar(posicion, vid) {
  // Buscar neumáticos disponibles
  const disponibles = (await api("/api/neumaticos?estado=disponible"));
  if (disponibles.length === 0) {
    if (confirm("No hay neumáticos disponibles en el inventario. ¿Querés ir a Inventario para agregar uno?")) {
      document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
      document.querySelector('.nav-item[data-sec="inventario_neu"]').classList.add("active");
      renderInventarioNeu();
    }
    return;
  }
  const opciones = disponibles.map(n =>
    `${n.codigo} — ${n.marca} ${n.modelo} ${n.medida ? '(' + n.medida + ')' : ''}`
  );
  const elegidos = prompt(
    `Posición: ${posicion}\n\nNeumáticos disponibles:\n` +
    disponibles.map((n, i) => `${i + 1}. ${opciones[i]}`).join("\n") +
    `\n\nEscribí el número del neumático a instalar:`
  );
  if (!elegidos) return;
  const idx = parseInt(elegidos) - 1;
  if (isNaN(idx) || idx < 0 || idx >= disponibles.length) {
    toast("Número inválido", "error");
    return;
  }
  const neu = disponibles[idx];
  const km = prompt(`KM actual del vehículo (al momento de la instalación):`, "0");
  if (km === null) return;

  const r = await api(`/api/neumaticos/${neu.id}/instalar`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      vehiculo_id: vid, posicion: posicion,
      fecha: hoy(), km_instalacion: parseFloat(km) || 0
    })
  });
  if (r.ok) { toast("Neumático instalado", "success"); renderNeumaticos(); }
  else toast(r.msg, "error");
}


async function abrirRetirar(nid, codigo, kmActual, posicion) {
  const motivo = prompt(
    `Retirar neumático ${codigo} de la posición ${posicion}\n\n` +
    `Motivo del retiro:\n` +
    `1. rotación (cambia a otra posición)\n` +
    `2. desgaste (al inventario, disponible)\n` +
    `3. reencauche (se envía a reencauchar)\n` +
    `4. pinchazo / daño\n` +
    `5. baja definitiva\n\n` +
    `Escribí el número (1-5):`
  );
  if (!motivo) return;
  const motivos = {
    "1": { motivo: "rotación", nuevo_estado: "disponible" },
    "2": { motivo: "desgaste", nuevo_estado: "disponible" },
    "3": { motivo: "reencauche", nuevo_estado: "reencauche" },
    "4": { motivo: "pinchazo", nuevo_estado: "disponible" },
    "5": { motivo: "baja", nuevo_estado: "baja" },
  };
  const opc = motivos[motivo.trim()];
  if (!opc) { toast("Opción inválida", "error"); return; }

  const km = prompt(`KM del vehículo al momento del retiro:`, Math.round(kmActual).toString());
  if (km === null) return;

  const r = await api(`/api/neumaticos/${nid}/retirar`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      fecha_retiro: hoy(), km_retiro: parseFloat(km) || 0,
      motivo: opc.motivo, nuevo_estado: opc.nuevo_estado
    })
  });
  if (r.ok) {
    toast(r.msg, "success");
    renderNeumaticos();
  } else toast(r.msg, "error");
}


// ════════════════════════════════════════════════════════════════════════
//  INVENTARIO DE NEUMÁTICOS (catálogo general)
// ════════════════════════════════════════════════════════════════════════

const NOMBRE_ESTADO_NEU = {
  disponible: "Disponible", instalado: "Instalado",
  reencauche: "En reencauche", baja: "Dado de baja"
};

async function renderInventarioNeu() {
  status("Inventario de neumáticos");
  const neus = await api("/api/neumaticos");
  const counts = { disponible: 0, instalado: 0, reencauche: 0, baja: 0 };
  neus.forEach(n => counts[n.estado]++);

  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-box"></i> Inventario de Neumáticos</h1>
      <p>Catálogo completo · cada cubierta con su historial individual</p>
    </div>
    <div class="section">

      <div class="metrics">
        <div class="metric">
          <div class="metric-icon blue"><i class="ti ti-disc"></i></div>
          <div class="metric-content"><div class="metric-label">Total</div><div class="metric-value">${neus.length}</div></div>
        </div>
        <div class="metric success">
          <div class="metric-icon green"><i class="ti ti-checks"></i></div>
          <div class="metric-content"><div class="metric-label">Disponibles</div><div class="metric-value">${counts.disponible}</div></div>
        </div>
        <div class="metric">
          <div class="metric-icon blue"><i class="ti ti-bus"></i></div>
          <div class="metric-content"><div class="metric-label">Instalados</div><div class="metric-value">${counts.instalado}</div></div>
        </div>
        <div class="metric warning">
          <div class="metric-icon amber"><i class="ti ti-refresh"></i></div>
          <div class="metric-content"><div class="metric-label">En reencauche</div><div class="metric-value">${counts.reencauche}</div></div>
        </div>
      </div>

      <div class="card">
        <div class="card-head"><i class="ti ti-plus"></i> Agregar neumático al inventario</div>
        <div class="card-body">
          <div class="form-row">
            <div class="field"><label>Código *</label><input id="n-cod" placeholder="NEU-007" style="width:130px"></div>
            <div class="field"><label>Marca</label><input id="n-mar" placeholder="Michelin" style="width:140px"></div>
            <div class="field"><label>Modelo</label><input id="n-mod" placeholder="X Multi D" style="width:160px"></div>
            <div class="field"><label>Medida</label><input id="n-med" placeholder="295/80 R22.5" style="width:140px"></div>
            <div class="field"><label>DOT</label><input id="n-dot" placeholder="DOT 2024-15" style="width:120px"></div>
          </div>
          <div class="form-row" style="margin-top:14px">
            <div class="field"><label>Fecha compra</label><input id="n-fec" type="date"></div>
            <div class="field"><label>Costo (Gs.)</label><input id="n-cos" placeholder="3500000" style="width:150px"></div>
            <div class="field"><label>Profundidad inicial (mm)</label><input id="n-pro" placeholder="14" style="width:130px"></div>
            <div class="field" style="flex:1;min-width:220px"><label>Observaciones</label><input id="n-obs" placeholder="Notas"></div>
            <button class="btn btn-primary" onclick="guardarNeumatico()"><i class="ti ti-device-floppy"></i> Guardar</button>
          </div>
        </div>
      </div>

      <div class="section-title"><i class="ti ti-list"></i> Stock completo (${neus.length})</div>
      ${neus.length === 0 ? `<div class="empty"><i class="ti ti-disc-off"></i>Sin neumáticos cargados.<br>Agregá el primero arriba.</div>` : `
        <div class="table-wrap">
          <table>
            <thead><tr>
              <th>Código</th><th>Marca / Modelo</th><th>Medida</th><th>DOT</th>
              <th class="num">KM acum.</th><th class="center">Reenc.</th>
              <th>Ubicación actual</th><th class="center">Estado</th><th class="td-action"></th>
            </tr></thead>
            <tbody>
              ${neus.map(n => `
                <tr>
                  <td><b>${n.codigo}</b></td>
                  <td>${n.marca || "—"} ${n.modelo || ""}</td>
                  <td style="color:var(--muted)">${n.medida || "—"}</td>
                  <td style="color:var(--muted);font-size:12px">${n.dot || "—"}</td>
                  <td class="num">${fmtNum(n.km_acumulados)}</td>
                  <td class="center">${n.reencauches > 0 ? `<span class="badge warning">${n.reencauches}x</span>` : "—"}</td>
                  <td>${n.patente_actual ? `<b>${n.patente_actual}</b> <span style="color:var(--muted)">${n.posicion_actual}</span>` : "—"}</td>
                  <td class="center"><span class="estado-pill ${n.estado}">${NOMBRE_ESTADO_NEU[n.estado]}</span></td>
                  <td class="td-action">
                    <button class="icon-btn" onclick="borrarNeumatico(${n.id},'${n.codigo}')"><i class="ti ti-trash"></i></button>
                  </td>
                </tr>`).join("")}
            </tbody>
          </table>
        </div>
      `}

      <p class="hint" style="margin-top:14px">
        <i class="ti ti-bulb"></i>
        Para instalar un neumático en un vehículo, andá a <b>Neumáticos</b> (con el coche seleccionado) y hacé clic en una posición vacía del esquema del bus.
      </p>
    </div>`;
}

async function guardarNeumatico() {
  const cod = $("#n-cod").value.trim();
  if (!cod) { toast("El código es obligatorio", "error"); return; }
  const costo = ($("#n-cos").value || "0").replace(/\./g, "").replace(/,/g, ".");
  const r = await api("/api/neumaticos", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      codigo: cod, marca: $("#n-mar").value, modelo: $("#n-mod").value,
      medida: $("#n-med").value, dot: $("#n-dot").value,
      fecha_compra: $("#n-fec").value || null, costo_compra: costo || 0,
      profundidad_mm: parseFloat($("#n-pro").value || 0),
      observaciones: $("#n-obs").value
    })
  });
  if (r.ok) {
    toast("Neumático agregado", "success");
    ["n-cod","n-mar","n-mod","n-med","n-dot","n-fec","n-cos","n-pro","n-obs"].forEach(id => $("#"+id).value = "");
    renderInventarioNeu();
  } else toast(r.msg, "error");
}

async function borrarNeumatico(id, cod) {
  if (!confirm(`¿Eliminar el neumático ${cod}?`)) return;
  const r = await api(`/api/neumaticos/${id}`, { method: "DELETE" });
  if (r.ok) { toast("Eliminado"); renderInventarioNeu(); }
  else toast(r.msg, "error");
}


// ════════════════════════════════════════════════════════════════════════
//  ÓRDENES DE TRABAJO (OT)
// ════════════════════════════════════════════════════════════════════════

const TIPOS_ITEM = ["control", "preventivo", "correctivo", "neumaticos", "otro"];
const LABEL_TIPO_ITEM = {
  control: "Control", preventivo: "Preventivo", correctivo: "Correctivo",
  neumaticos: "Neumáticos", otro: "Otro"
};
const COLOR_TIPO_ITEM = {
  control: "var(--info)", preventivo: "var(--success)",
  correctivo: "var(--danger)", neumaticos: "#0891B2", otro: "var(--muted)"
};
const LABEL_ESTADO_ITEM = {
  pendiente: "Pendiente", en_proceso: "En proceso", completado: "Completado"
};
const LABEL_ESTADO_OT = {
  abierta: "Abierta", en_proceso: "En proceso", cerrada: "Cerrada"
};

let otFiltroEstado = "";

// ═══════════════ PANTALLA DE COMPRAS / DEPÓSITO ═══════════════
let comprasTab = "en_espera";
const LABEL_EST_COMPRAS = { en_espera: "En espera", presupuestado: "Presupuestadas", en_camino: "En camino", entregado: "Entregadas" };

async function renderCompras() {
  status("Compras / Depósito");
  const todas = await api("/api/compras/ots");
  const enEspera = todas.filter(o => o.estado_compras === "en_espera");
  const presup = todas.filter(o => o.estado_compras === "presupuestado");
  const enCamino = todas.filter(o => o.estado_compras === "en_camino");
  const entreg = todas.filter(o => o.estado_compras === "entregado");
  const lista = comprasTab === "en_espera" ? enEspera
    : comprasTab === "presupuestado" ? presup
    : comprasTab === "en_camino" ? enCamino
    : comprasTab === "entregado" ? entreg : [];
  const totalEspera = todas.reduce((s, o) => s + ((o.pagos && o.pagos.en_espera) || 0), 0);

  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-shopping-cart"></i> Compras / Depósito</h1>
      <p>Pedidos del taller — presupuestar, autorizar y entregar</p>
    </div>
    <div class="section">
      <div class="metrics" style="margin-bottom:18px">
        <div class="metric" style="cursor:pointer;${comprasTab==='en_espera'?'border:2px solid var(--warning)':''}" onclick="setComprasTab('en_espera')">
          <div class="metric-content"><div class="metric-label">En espera</div>
          <div class="metric-value" style="color:var(--warning)">${enEspera.length}</div></div></div>
        <div class="metric" style="cursor:pointer;${comprasTab==='presupuestado'?'border:2px solid var(--brand-blue)':''}" onclick="setComprasTab('presupuestado')">
          <div class="metric-content"><div class="metric-label">Presupuestadas</div>
          <div class="metric-value" style="color:var(--brand-blue)">${presup.length}</div></div></div>
        <div class="metric" style="cursor:pointer;${comprasTab==='en_camino'?'border:2px solid #d97706':''}" onclick="setComprasTab('en_camino')">
          <div class="metric-content"><div class="metric-label">En camino</div>
          <div class="metric-value" style="color:#d97706">${enCamino.length}</div></div></div>
        <div class="metric" style="cursor:pointer;${comprasTab==='entregado'?'border:2px solid var(--success)':''}" onclick="setComprasTab('entregado')">
          <div class="metric-content"><div class="metric-label">Entregadas</div>
          <div class="metric-value" style="color:var(--success)">${entreg.length}</div></div></div>
        <div class="metric" style="cursor:pointer;${comprasTab==='cola'?'border:2px solid var(--warning)':''}" onclick="setComprasTab('cola')">
          <div class="metric-content"><div class="metric-label">Esperando fondos</div>
          <div class="metric-value" style="color:var(--warning)">${totalEspera}</div></div></div>
      </div>

      ${comprasTab === "cola" ? `
        <div class="section-title"><i class="ti ti-hourglass"></i> Cola de Tesorería — esperando fondos</div>
        <p class="hint" style="margin-bottom:14px"><i class="ti ti-info-circle"></i> Ítems presupuestados que Tesorería todavía no pudo cubrir. Cuando entren fondos, marcalos y liberalos: la orden retoma su curso.</p>
        <div id="cola-espera-panel"><div class="dossier-loading"><div class="dossier-spinner"></div></div></div>
      ` : `
        <div class="section-title"><i class="ti ti-list"></i> ${LABEL_EST_COMPRAS[comprasTab] || ""} (${lista.length})</div>
        ${lista.length === 0
          ? `<div class="empty"><i class="ti ti-shopping-cart-off"></i>No hay pedidos en esta etapa.</div>`
          : lista.map(o => tarjetaCompra(o)).join("")}
      `}
    </div>`;

  if (comprasTab === "cola") renderColaEspera();
}

function setComprasTab(t) { comprasTab = t; renderCompras(); }

function tarjetaCompra(o) {
  const coche = o.n_interno ? `Coche ${o.n_interno}` : o.patente;
  const totalPresup = o.items.reduce((s, i) => s + (i.precio_compras || 0), 0);
  let acciones = "";
  if (o.estado_compras === "en_espera") {
    acciones = `<button class="btn btn-primary" onclick="abrirPresupuesto(${o.id})"><i class="ti ti-cash"></i> Cargar presupuesto</button>`;
  } else if (o.estado_compras === "presupuestado") {
    acciones = `
      <button class="btn btn-ghost" onclick="window.open('/api/compras/${o.id}/presupuesto_pdf','_blank')"><i class="ti ti-printer"></i> Imprimir para Tesorería</button>
      <button class="btn btn-ghost" onclick="abrirPresupuesto(${o.id})"><i class="ti ti-edit"></i> Editar precios</button>
      <button class="btn btn-primary" onclick="abrirFirma(${o.id})"><i class="ti ti-writing-sign"></i> Firma de Tesorería</button>`;
  } else if (o.estado_compras === "en_camino") {
    acciones = `
      <button class="btn btn-ghost" onclick="window.open('/api/compras/${o.id}/presupuesto_pdf','_blank')"><i class="ti ti-printer"></i> Ver presupuesto</button>
      <button class="btn btn-success" onclick="abrirEntrega(${o.id})"><i class="ti ti-package"></i> Registrar entrega</button>`;
  } else {
    acciones = `
      ${o.taller_entrega || o.recibido_por ? `<span style="font-size:12.5px;color:var(--muted);display:inline-flex;align-items:center;gap:5px;margin-right:auto"><i class="ti ti-map-pin"></i> ${o.taller_entrega || "Taller propio"}${o.recibido_por ? ` · recibió <b>${o.recibido_por}</b>` : ""}</span>` : ""}
      <button class="btn btn-ghost" onclick="window.open('/api/compras/${o.id}/presupuesto_pdf','_blank')"><i class="ti ti-printer"></i> Ver presupuesto</button>
      <button class="btn btn-ghost" onclick="verEvidencia(${o.id})"><i class="ti ti-photo"></i> Ver evidencia</button>`;
  }

  return `
    <div class="card" style="margin-bottom:14px">
      <div class="card-head" style="display:flex;justify-content:space-between;align-items:center">
        <span><i class="ti ti-clipboard-check"></i> OT #${o.id} · ${coche} · ${o.patente}</span>
        <span style="font-size:12px;color:var(--muted);display:flex;align-items:center;gap:10px">
          ${o.pagos && o.pagos.parcial ? `<span class="badge warning"><i class="ti ti-hourglass"></i> ${o.pagos.en_espera} esperando fondos · ${gs(o.pagos.monto_espera)}</span>` : ""}
          ${o.fecha_envio_compras ? "Enviada: " + o.fecha_envio_compras.slice(0,10) : ""}
        </span>
      </div>
      <div class="card-body">
        <div class="table-wrap"><table>
          <thead><tr>
            <th>Trabajo</th><th>Material necesario</th><th>Mecánico</th>
            ${o.estado_compras !== "en_espera" ? '<th class="num">Precio</th>' : ''}
          </tr></thead>
          <tbody>
            ${o.items.map(it => `<tr class="${it.estado_pago === 'espera' ? 'item-en-espera' : ''}">
              <td>${it.descripcion}${it.estado_pago === 'espera' ? ' <span class="badge warning" style="font-size:10px"><i class="ti ti-hourglass"></i> espera fondos</span>' : ''}</td>
              <td><b>${it.material_pedido || "—"}</b></td>
              <td style="color:var(--muted)">${it.tecnico || "—"}</td>
              ${o.estado_compras !== "en_espera" ? `<td class="num">${gs(it.precio_compras || 0)}</td>` : ''}
            </tr>`).join("")}
          </tbody>
        </table></div>
        ${o.estado_compras !== "en_espera" ? `<div style="text-align:right;margin-top:8px;font-weight:700;color:var(--brand-blue)">Total: ${gs(totalPresup)}</div>` : ''}
        <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:14px;flex-wrap:wrap">${acciones}</div>
      </div>
    </div>`;
}

// Modal para cargar/editar precios del presupuesto
async function abrirPresupuesto(otId) {
  const ots = await api("/api/compras/ots");
  const o = ots.find(x => x.id === otId);
  if (!o) return;
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(10,15,26,0.55);z-index:1500;display:grid;place-items:center;padding:20px";
  overlay.innerHTML = `
    <div style="background:#fff;border-radius:16px;max-width:640px;width:100%;max-height:90vh;overflow:auto;padding:24px">
      <h2 style="font-size:18px;color:var(--brand-blue);margin:0 0 6px;display:flex;align-items:center;gap:8px"><i class="ti ti-cash"></i> Presupuesto — OT #${o.id}</h2>
      <p style="font-size:13px;color:var(--muted);margin:0 0 18px">Poné el precio de cada material. ${o.patente} · ${o.n_interno ? "Coche " + o.n_interno : ""}</p>
      <div class="table-wrap"><table>
        <thead><tr><th>Trabajo</th><th>Material</th><th>Mecánico</th><th class="num">Precio (Gs.)</th></tr></thead>
        <tbody>
          ${o.items.map(it => `<tr>
            <td style="font-size:13px">${it.descripcion}</td>
            <td style="font-size:13px"><b>${it.material_pedido || "—"}</b></td>
            <td style="font-size:13px;color:var(--muted)">${it.tecnico || "—"}</td>
            <td><input type="number" id="precio-${it.id}" value="${it.precio_compras || ''}" placeholder="0"
                 style="width:120px;padding:8px;border:1.5px solid var(--border);border-radius:8px;text-align:right"></td>
          </tr>`).join("")}
        </tbody>
      </table></div>
      <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:20px">
        <button class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancelar</button>
        <button class="btn btn-primary" onclick="guardarPresupuesto(${o.id}, this)"><i class="ti ti-check"></i> Guardar presupuesto</button>
      </div>
    </div>`;
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
  document.body.appendChild(overlay);
}

async function guardarPresupuesto(otId, btn) {
  const ots = await api("/api/compras/ots");
  const o = ots.find(x => x.id === otId);
  const precios = {};
  let alguno = false;
  o.items.forEach(it => {
    const val = document.getElementById(`precio-${it.id}`).value;
    if (val !== "" && val !== null) { precios[it.id] = parseFloat(val) || 0; alguno = true; }
  });
  if (!alguno) { toast("Cargá al menos un precio", "error"); return; }
  const r = await api(`/api/compras/${otId}/presupuesto`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ precios })
  });
  if (r.ok) {
    toast("Presupuesto guardado", "success");
    btn.closest(".modal-overlay").remove();
    renderCompras();
  } else toast(r.msg || "Error", "error");
}

// Modal para registrar la entrega con foto obligatoria
// Comprime una foto antes de subirla (de ~3MB a ~150KB)
function comprimirFoto(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = e => {
      const img = new Image();
      img.onload = () => {
        const maxLado = 1000;
        let { width, height } = img;
        if (width > height && width > maxLado) {
          height = height * maxLado / width; width = maxLado;
        } else if (height > maxLado) {
          width = width * maxLado / height; height = maxLado;
        }
        const canvas = document.createElement("canvas");
        canvas.width = width; canvas.height = height;
        const ctx = canvas.getContext("2d");
        ctx.drawImage(img, 0, 0, width, height);
        resolve(canvas.toDataURL("image/jpeg", 0.6));
      };
      img.onerror = reject;
      img.src = e.target.result;
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function abrirEntrega(otId) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(10,15,26,0.55);z-index:1500;display:grid;place-items:center;padding:20px";
  overlay.innerHTML = `
    <div style="background:#fff;border-radius:16px;max-width:460px;width:100%;padding:24px">
      <h2 style="font-size:18px;color:var(--brand-blue);margin:0 0 6px;display:flex;align-items:center;gap:8px"><i class="ti ti-package"></i> Registrar entrega — OT #${otId}</h2>
      <p style="font-size:13px;color:var(--muted);margin:0 0 16px">Indicá dónde entregás y <b>quién recibe</b> — al registrarlo, la responsabilidad del material pasa a esa persona. La foto es opcional pero recomendada.</p>

      <div class="field" style="margin-bottom:12px">
        <label>¿Dónde se entrega?</label>
        <div style="display:flex;gap:8px">
          <select id="ev-taller-sel" style="flex:1" onchange="document.getElementById('ev-taller-otro').style.display = this.value==='__otro__' ? '' : 'none'">
            <option value="Taller propio">Taller propio</option>
            <option value="__otro__">Otro taller...</option>
          </select>
        </div>
        <input id="ev-taller-otro" placeholder="Nombre del taller externo" list="ev-talleres-list" style="display:none;margin-top:8px">
        <datalist id="ev-talleres-list"></datalist>
      </div>

      <div class="field" style="margin-bottom:16px">
        <label>¿Quién recibe el material? *</label>
        <input id="ev-recibe" placeholder="Nombre de la persona que recibe">
      </div>

      <input type="file" id="ev-camara" accept="image/*" capture="environment" style="display:none">
      <input type="file" id="ev-galeria" accept="image/*" style="display:none">
      <div style="display:flex;gap:10px;margin-bottom:14px">
        <button class="btn btn-ghost" style="flex:1" onclick="document.getElementById('ev-camara').click()"><i class="ti ti-camera"></i> Sacar foto</button>
        <button class="btn btn-ghost" style="flex:1" onclick="document.getElementById('ev-galeria').click()"><i class="ti ti-photo"></i> Elegir foto</button>
      </div>
      <div id="ev-preview" style="margin-bottom:16px"></div>
      <div style="display:flex;gap:10px;justify-content:flex-end">
        <button class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancelar</button>
        <button class="btn btn-success" id="ev-confirmar" onclick="confirmarEntrega(${otId}, this)"><i class="ti ti-check"></i> Confirmar entrega</button>
      </div>
    </div>`;
  overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
  document.body.appendChild(overlay);

  // Cargar talleres externos ya usados para el autocompletar
  api("/api/compras/talleres").then(ts => {
    const dl = document.getElementById("ev-talleres-list");
    if (dl && Array.isArray(ts)) dl.innerHTML = ts.map(t => `<option value="${t}">`).join("");
  });

  let fotoEvidencia = null;
  async function procesarEv(file) {
    fotoEvidencia = await comprimirFoto(file);
    document.getElementById("ev-preview").innerHTML = `<img src="${fotoEvidencia}" style="width:140px;height:140px;object-fit:cover;border-radius:10px;border:1px solid var(--border)">`;
    document.getElementById("ev-confirmar").disabled = false;
  }
  document.getElementById("ev-camara").addEventListener("change", e => { if (e.target.files[0]) procesarEv(e.target.files[0]); });
  document.getElementById("ev-galeria").addEventListener("change", e => { if (e.target.files[0]) procesarEv(e.target.files[0]); });
  window._fotoEvidenciaGetter = () => fotoEvidencia;
}

async function confirmarEntrega(otId, btn) {
  const foto = window._fotoEvidenciaGetter ? window._fotoEvidenciaGetter() : null;
  const recibe = (document.getElementById("ev-recibe")?.value || "").trim();
  if (!recibe) { toast("Indicá quién recibe el material", "error"); return; }
  const tallerSel = document.getElementById("ev-taller-sel")?.value || "Taller propio";
  const taller = tallerSel === "__otro__"
    ? (document.getElementById("ev-taller-otro")?.value || "").trim() || "Taller externo"
    : tallerSel;
  btn.disabled = true;
  const r = await api(`/api/compras/${otId}/entregar`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ foto, taller_entrega: taller, recibido_por: recibe })
  });
  if (r.ok) {
    toast(`Entregado en ${taller} — recibió ${recibe}`, "success");
    btn.closest(".modal-overlay").remove();
    renderCompras();
  } else { toast(r.msg || "Error", "error"); btn.disabled = false; }
}

async function verEvidencia(otId) {
  const fotos = await api(`/api/compras/${otId}/evidencia`);
  if (!fotos.length) { toast("Sin evidencia", "error"); return; }
  verFotoGrande(fotos[0].datos);
}

// Compras marca que fue a buscar los repuestos
async function marcarEnCamino(otId) {
  if (!confirm("¿Marcar que ya fueron a buscar los repuestos?")) return;
  const r = await api(`/api/compras/${otId}/en_camino`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: "{}"
  });
  if (r.ok) { toast("Marcado en camino", "success"); renderCompras(); }
  else toast(r.msg || "Error", "error");
}

// Convierte 'HH:MM' a minutos del día. Sin horario → muy alto (va al final).
function minutosHorario(h) {
  if (!h || !h.includes(":")) return 99999;
  const [hh, mm] = h.split(":");
  return parseInt(hh) * 60 + parseInt(mm);
}

// Badge del horario de salida con color de urgencia
function badgeSalida(horario) {
  if (!horario || !horario.includes(":")) return `<span style="color:var(--muted);font-size:12px">—</span>`;
  // Calcular urgencia según la hora actual
  const ahora = new Date();
  const minAhora = ahora.getHours() * 60 + ahora.getMinutes();
  const minSalida = minutosHorario(horario);
  const faltan = minSalida - minAhora;
  let color, bg;
  if (faltan < 0) { color = "#6b7280"; bg = "#f3f4f6"; }           // ya salió
  else if (faltan <= 60) { color = "#dc2626"; bg = "#fee2e2"; }     // menos de 1h: urgente
  else if (faltan <= 180) { color = "#d97706"; bg = "#fef3c7"; }    // menos de 3h: pronto
  else { color = "#059669"; bg = "#d1fae5"; }                       // tranquilo
  return `<span style="display:inline-flex;align-items:center;gap:4px;background:${bg};color:${color};padding:3px 9px;border-radius:8px;font-size:13px;font-weight:700"><i class="ti ti-clock"></i> ${horario}</span>`;
}

async function renderOts() {
  status("Órdenes de Trabajo");
  const filtro = otFiltroEstado ? `?estado=${otFiltroEstado}` : "";
  const ots = await api("/api/ots" + filtro);
  const counts = { abierta: 0, en_proceso: 0, cerrada: 0 };
  (await api("/api/ots")).forEach(o => counts[o.estado] = (counts[o.estado] || 0) + 1);

  // Ordenar las OTs activas por urgencia de horario de salida (el que sale antes, primero).
  // Las cerradas se dejan por fecha. Las sin horario van al final.
  if (otFiltroEstado !== "cerrada") {
    ots.sort((a, b) => {
      const cerrA = a.estado === "cerrada" ? 1 : 0;
      const cerrB = b.estado === "cerrada" ? 1 : 0;
      if (cerrA !== cerrB) return cerrA - cerrB;  // activas arriba
      const ua = minutosHorario(a.horario_salida);
      const ub = minutosHorario(b.horario_salida);
      return ua - ub;  // más temprano = más urgente
    });
  }

  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-clipboard-check"></i> Órdenes de Trabajo</h1>
      <p>Trabajos de taller agrupados — basadas en los reportes de los choferes</p>
    </div>
    <div class="section">

      <div class="metrics">
        <div class="metric">
          <div class="metric-icon blue"><i class="ti ti-clipboard-list"></i></div>
          <div class="metric-content"><div class="metric-label">Total</div><div class="metric-value">${counts.abierta + counts.en_proceso + counts.cerrada}</div></div>
        </div>
        <div class="metric warning">
          <div class="metric-icon amber"><i class="ti ti-progress"></i></div>
          <div class="metric-content"><div class="metric-label">Abiertas</div><div class="metric-value">${counts.abierta}</div></div>
        </div>
        <div class="metric">
          <div class="metric-icon blue"><i class="ti ti-tool"></i></div>
          <div class="metric-content"><div class="metric-label">En proceso</div><div class="metric-value">${counts.en_proceso}</div></div>
        </div>
        <div class="metric success">
          <div class="metric-icon green"><i class="ti ti-circle-check"></i></div>
          <div class="metric-content"><div class="metric-label">Cerradas</div><div class="metric-value">${counts.cerrada}</div></div>
        </div>
      </div>

      <div class="toolbar">
        <button class="btn btn-primary" onclick="abrirNuevaOT()"><i class="ti ti-plus"></i> Nueva OT</button>
        <button class="btn btn-ghost" onclick="abrirReporteFechas()"><i class="ti ti-file-text"></i> Reporte por fechas</button>
        <div class="tabs">
          <button class="tab-btn ${otFiltroEstado===''?'active':''}" onclick="filtrarOTs('')"><i class="ti ti-list"></i> Todas</button>
          <button class="tab-btn ${otFiltroEstado==='abierta'?'active':''}" onclick="filtrarOTs('abierta')"><i class="ti ti-progress"></i> Abiertas</button>
          <button class="tab-btn ${otFiltroEstado==='en_proceso'?'active':''}" onclick="filtrarOTs('en_proceso')"><i class="ti ti-tool"></i> En proceso</button>
          <button class="tab-btn ${otFiltroEstado==='cerrada'?'active':''}" onclick="filtrarOTs('cerrada')"><i class="ti ti-circle-check"></i> Cerradas</button>
        </div>
      </div>

      ${ots.length === 0 ? `<div class="empty"><i class="ti ti-clipboard-off"></i>Sin OTs ${otFiltroEstado ? 'en este filtro' : 'todavía'}.<br>Tocá <b>Nueva OT</b> para cargar la primera.</div>` : `
        <div class="table-wrap">
          <table>
            <thead><tr>
              <th>OT #</th><th class="center">Salida</th><th>Fecha</th><th>Vehículo</th><th>Conductor</th>
              <th>Procedencia</th><th class="num">KM</th>
              <th class="center">Items</th><th class="num">Costo</th>
              <th class="center">Estado</th><th class="td-action"></th>
            </tr></thead>
            <tbody>
              ${ots.map(o => {
                const progreso = o.total_items ? Math.round((o.items_completados / o.total_items) * 100) : 0;
                return `<tr class="clickable" onclick="abrirOT(${o.id})">
                  <td><b>#${o.id}</b></td>
                  <td class="center">${badgeSalida(o.horario_salida)}</td>
                  <td>${o.fecha_apertura}</td>
                  <td><b>${o.patente}</b>${o.n_interno ? ` <span style="color:var(--muted)">(${o.n_interno})</span>` : ""}</td>
                  <td>${o.conductor || "—"}</td>
                  <td>${o.procedencia || "—"}</td>
                  <td class="num">${o.km ? fmtNum(o.km) : "—"}</td>
                  <td class="center">
                    <div style="font-size:11px;color:var(--muted)">${o.items_completados}/${o.total_items}</div>
                    <div class="grad-bar-wrap" style="width:60px;margin:3px auto 0">
                      <div class="grad-bar" style="width:${progreso}%;background:${progreso === 100 ? 'var(--success)' : progreso > 50 ? 'var(--warning)' : 'var(--info)'}"></div>
                    </div>
                  </td>
                  <td class="num">${gs(o.costo_total || 0)}</td>
                  <td class="center">
                    <span class="badge ${o.estado === 'cerrada' ? 'success' : o.estado === 'en_proceso' ? 'warning' : 'danger'}">
                      <span class="dot"></span> ${LABEL_ESTADO_OT[o.estado]}
                    </span>
                  </td>
                  <td class="td-action">
                    <button class="icon-btn" onclick="event.stopPropagation();borrarOT(${o.id})"><i class="ti ti-trash"></i></button>
                  </td>
                </tr>`;
              }).join("")}
            </tbody>
          </table>
        </div>
      `}
    </div>`;
}

function filtrarOTs(estado) {
  otFiltroEstado = estado;
  renderOts();
}

async function abrirNuevaOT() {
  const vehiculos = await api("/api/vehiculos");
  if (vehiculos.length === 0) {
    toast("Cargá vehículos primero", "error");
    return;
  }
  const overlay = document.createElement("div");
  overlay.id = "modal-ot";
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(15,23,42,0.55);z-index:999;display:grid;place-items:center;padding:20px";
  overlay.innerHTML = `
    <div style="background:var(--surface);border-radius:var(--radius);box-shadow:var(--shadow-lg);max-width:760px;width:100%;max-height:92vh;overflow:auto">
      <div style="padding:18px 22px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center">
        <h3 style="font-size:16px;font-weight:600;display:flex;align-items:center;gap:8px">
          <i class="ti ti-clipboard-plus" style="color:var(--brand-blue)"></i> Nueva Orden de Trabajo
        </h3>
        <button class="icon-btn" onclick="cerrarModalOT()"><i class="ti ti-x"></i></button>
      </div>
      <div style="padding:22px">
        <div class="form-row">
          <div class="field" style="flex:1;min-width:200px"><label>Vehículo *</label>
            <select id="ot-veh">
              ${vehiculos.map(v => `<option value="${v.id}">${v.patente}${v.n_interno?' (#'+v.n_interno+')':''} — ${v.marca} ${v.modelo}</option>`).join("")}
            </select>
          </div>
          <div class="field"><label>Fecha *</label><input id="ot-fecha" type="date" value="${hoy()}"></div>
          <div class="field"><label>KM</label><input id="ot-km" placeholder="765387" style="width:110px"></div>
        </div>
        <div class="form-row" style="margin-top:14px">
          <div class="field" style="flex:1"><label>Conductor</label><input id="ot-cond" placeholder="Marco Aguiar"></div>
          <div class="field" style="flex:1"><label>Procedencia</label><input id="ot-proc" placeholder="Loreto"></div>
        </div>
        <div class="form-row" style="margin-top:14px">
          <div class="field" style="flex:1"><label>Observaciones</label><input id="ot-obs" placeholder="Opcional"></div>
        </div>

        <p style="margin:20px 0 8px;font-weight:600;font-size:13px;color:var(--brand-blue)">
          <i class="ti ti-list-check"></i> Items de la OT
        </p>
        <p class="hint">
          <i class="ti ti-bulb"></i>
          Pegá la lista del chofer abajo, una línea por trabajo. El sistema detecta el tipo automáticamente.
        </p>
        <textarea id="ot-items-raw" rows="8" style="width:100%;padding:10px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);font-family:inherit;font-size:13px;resize:vertical"
          placeholder="Cambio de aceite y filtros
Revisión frenos
Cambiar goma valijera
Control general"></textarea>

        <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:22px;padding-top:18px;border-top:1px solid var(--border)">
          <button class="btn btn-ghost" onclick="cerrarModalOT()">Cancelar</button>
          <button class="btn btn-primary" onclick="guardarNuevaOT()"><i class="ti ti-device-floppy"></i> Crear OT</button>
        </div>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.addEventListener("click", e => { if (e.target === overlay) cerrarModalOT(); });
}

function cerrarModalOT() {
  const m = document.getElementById("modal-ot");
  if (m) m.remove();
}

function detectarTipoItem(desc) {
  const d = desc.toLowerCase();
  if (/aceite|filtro|engrase|engranaje|servicio|preventivo|lubric/.test(d)) return "preventivo";
  if (/cubierta|neumat|cubierto|trucky|llanta|goma rueda|reencauch/.test(d)) return "neumaticos";
  if (/freno|frenos|rotura|perdida|pérdida|fuga|cambiar|reparar|solucionar|reten|arreglar|romp|fall/.test(d)) return "correctivo";
  if (/control|revisar|verificar|chequear|inspecc/.test(d)) return "control";
  return "otro";
}

async function guardarNuevaOT() {
  const vid = parseInt($("#ot-veh").value);
  const fecha = $("#ot-fecha").value;
  if (!fecha) { toast("La fecha es obligatoria", "error"); return; }

  const raw = $("#ot-items-raw").value.trim();
  const items = raw.split("\n").map(l => l.trim()).filter(l => l).map(l => {
    // Sacar guiones, asteriscos, viñetas iniciales
    const limpia = l.replace(/^[-*•·]\s*/, "");
    return { descripcion: limpia, tipo: detectarTipoItem(limpia) };
  });

  const r = await api("/api/ots", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      vehiculo_id: vid, fecha_apertura: fecha,
      km: parseFloat($("#ot-km").value || 0),
      conductor: $("#ot-cond").value,
      procedencia: $("#ot-proc").value,
      observaciones: $("#ot-obs").value,
      items: items
    })
  });
  if (r.ok) {
    toast(`OT #${r.ot_id} creada con ${items.length} items`, "success");
    cerrarModalOT();
    renderOts();
  } else toast(r.msg || "Error", "error");
}

// Modal para elegir fechas y generar el reporte de trabajos en PDF
function abrirReporteFechas() {
  const hoy = new Date().toISOString().slice(0, 10);
  const hace7 = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
  const o = document.createElement("div");
  o.className = "modal-overlay";
  o.style.cssText = "position:fixed;inset:0;background:rgba(10,15,26,0.55);z-index:1500;display:grid;place-items:center;padding:20px";
  o.innerHTML = `
    <div style="background:#fff;border-radius:16px;max-width:440px;width:100%;padding:24px;box-shadow:0 20px 60px rgba(0,0,0,0.3)">
      <h2 style="font-size:18px;color:var(--brand-blue);margin:0 0 6px;display:flex;align-items:center;gap:8px"><i class="ti ti-file-text"></i> Reporte de trabajos</h2>
      <p style="font-size:13px;color:var(--muted);margin:0 0 18px">Elegí el rango de fechas. Se genera un PDF con todas las órdenes de ese período (diario, semanal, lo que necesites).</p>
      <div style="display:flex;gap:12px;margin-bottom:18px">
        <div style="flex:1">
          <label style="font-size:12.5px;font-weight:600;display:block;margin-bottom:6px">Desde</label>
          <input type="date" id="rep-desde" value="${hace7}" style="width:100%;padding:10px;border:1.5px solid var(--border);border-radius:9px;font-size:15px">
        </div>
        <div style="flex:1">
          <label style="font-size:12.5px;font-weight:600;display:block;margin-bottom:6px">Hasta</label>
          <input type="date" id="rep-hasta" value="${hoy}" style="width:100%;padding:10px;border:1.5px solid var(--border);border-radius:9px;font-size:15px">
        </div>
      </div>
      <div style="display:flex;gap:10px;justify-content:flex-end">
        <button class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancelar</button>
        <button class="btn btn-primary" onclick="generarReporteFechas(this)"><i class="ti ti-download"></i> Generar PDF</button>
      </div>
    </div>`;
  o.onclick = (e) => { if (e.target === o) o.remove(); };
  document.body.appendChild(o);
}

function generarReporteFechas(btn) {
  const desde = document.getElementById("rep-desde").value;
  const hasta = document.getElementById("rep-hasta").value;
  if (!desde || !hasta) { toast("Elegí ambas fechas", "error"); return; }
  if (desde > hasta) { toast("La fecha 'desde' no puede ser mayor que 'hasta'", "error"); return; }
  window.open(`/api/reporte_trabajos_pdf?desde=${desde}&hasta=${hasta}`, "_blank");
  btn.closest(".modal-overlay").remove();
}

// Modal de fechas para el PDF de correctivos
function abrirReporteCorrectivos() {
  const hoy = new Date().toISOString().slice(0, 10);
  const hace30 = new Date(Date.now() - 30 * 86400000).toISOString().slice(0, 10);
  const o = document.createElement("div");
  o.className = "modal-overlay";
  o.style.cssText = "position:fixed;inset:0;background:rgba(10,15,26,0.55);z-index:1500;display:grid;place-items:center;padding:20px";
  o.innerHTML = `
    <div style="background:#fff;border-radius:16px;max-width:440px;width:100%;padding:24px;box-shadow:0 20px 60px rgba(0,0,0,0.3)">
      <h2 style="font-size:18px;color:var(--brand-blue);margin:0 0 6px;display:flex;align-items:center;gap:8px"><i class="ti ti-printer"></i> Reporte de correctivos</h2>
      <p style="font-size:13px;color:var(--muted);margin:0 0 18px">Elegí el rango de fechas. Se genera un PDF con todas las averías y reparaciones de ese período.</p>
      <div style="display:flex;gap:12px;margin-bottom:18px">
        <div style="flex:1">
          <label style="font-size:12.5px;font-weight:600;display:block;margin-bottom:6px">Desde</label>
          <input type="date" id="corr-desde" value="${hace30}" style="width:100%;padding:10px;border:1.5px solid var(--border);border-radius:9px;font-size:15px">
        </div>
        <div style="flex:1">
          <label style="font-size:12.5px;font-weight:600;display:block;margin-bottom:6px">Hasta</label>
          <input type="date" id="corr-hasta" value="${hoy}" style="width:100%;padding:10px;border:1.5px solid var(--border);border-radius:9px;font-size:15px">
        </div>
      </div>
      <div style="display:flex;gap:10px;justify-content:flex-end">
        <button class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancelar</button>
        <button class="btn btn-primary" onclick="generarReporteCorrectivos(this)"><i class="ti ti-download"></i> Generar PDF</button>
      </div>
    </div>`;
  o.onclick = (e) => { if (e.target === o) o.remove(); };
  document.body.appendChild(o);
}

function generarReporteCorrectivos(btn) {
  const desde = document.getElementById("corr-desde").value;
  const hasta = document.getElementById("corr-hasta").value;
  if (!desde || !hasta) { toast("Elegí ambas fechas", "error"); return; }
  if (desde > hasta) { toast("La fecha 'desde' no puede ser mayor que 'hasta'", "error"); return; }
  window.open(`/api/correctivos_pdf?desde=${desde}&hasta=${hasta}`, "_blank");
  btn.closest(".modal-overlay").remove();
}

// Enviar una OT al sector Compras
async function enviarACompras(otId) {
  if (!confirm("¿Enviar esta OT a Compras? Quedará en espera de presupuesto.")) return;
  const r = await api(`/api/ots/${otId}/enviar_compras`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ nota: "" })
  });
  if (r.ok) {
    toast("OT enviada a Compras", "success");
    cerrarModalOTDetalle();
    renderOts();
  } else toast(r.msg || "Error", "error");
}

// Ver una foto en grande (toca para cerrar)
function verFotoGrande(src) {
  const o = document.createElement("div");
  o.style.cssText = "position:fixed;inset:0;background:rgba(0,0,0,0.88);z-index:2000;display:grid;place-items:center;padding:20px;cursor:pointer";
  o.onclick = () => o.remove();
  o.innerHTML = `<img src="${src}" style="max-width:100%;max-height:100%;border-radius:8px">`;
  document.body.appendChild(o);
}

async function abrirOT(otId) {
  const ot = await api(`/api/ots/${otId}`);
  if (!ot) return;

  const overlay = document.createElement("div");
  overlay.id = "modal-ot-detalle";
  overlay.style.cssText = "position:fixed;inset:0;background:rgba(15,23,42,0.55);z-index:999;display:grid;place-items:center;padding:20px";

  const compl = ot.items.filter(i => i.estado === "completado").length;
  const LABEL_COMPRAS = { en_espera: "En espera (Compras)", presupuestado: "Presupuestado", en_camino: "En camino 🚚", entregado: "Entregado ✓" };
  const COLOR_COMPRAS = { en_espera: "warning", presupuestado: "cat", en_camino: "warning", entregado: "success" };

  overlay.innerHTML = `
    <div style="background:var(--surface);border-radius:var(--radius);box-shadow:var(--shadow-lg);max-width:880px;width:100%;max-height:92vh;overflow:auto">
      <div style="padding:18px 22px;border-bottom:1px solid var(--border);display:flex;justify-content:space-between;align-items:center;background:linear-gradient(135deg, var(--info-bg) 0%, var(--surface) 100%)">
        <div>
          <h3 style="font-size:17px;font-weight:700;display:flex;align-items:center;gap:8px">
            <i class="ti ti-clipboard-check" style="color:var(--brand-blue)"></i> OT #${ot.id} · ${ot.patente}
            ${ot.n_interno ? `<span style="font-weight:500;color:var(--muted)">Coche ${ot.n_interno}</span>` : ""}
          </h3>
          <p style="font-size:12.5px;color:var(--muted);margin-top:3px">
            ${ot.fecha_apertura} · ${ot.conductor || 'Sin conductor'} · ${ot.procedencia || 'Sin procedencia'} · ${ot.km ? fmtNum(ot.km) + ' km' : 'Sin km'}
          </p>
        </div>
        <button class="icon-btn" onclick="cerrarModalOTDetalle()"><i class="ti ti-x"></i></button>
      </div>

      <div style="padding:18px 22px">
        <div style="display:flex;gap:14px;flex-wrap:wrap;margin-bottom:16px">
          <span class="badge ${ot.estado === 'cerrada' ? 'success' : ot.estado === 'en_proceso' ? 'warning' : 'danger'}">
            <span class="dot"></span> ${LABEL_ESTADO_OT[ot.estado]}
          </span>
          <span class="badge">${compl}/${ot.items.length} completados</span>
          ${ot.estado_compras ? `<span class="badge ${COLOR_COMPRAS[ot.estado_compras]||''}"><i class="ti ti-shopping-cart"></i> ${LABEL_COMPRAS[ot.estado_compras]||ot.estado_compras}</span>` : ''}
          ${ot.fotos && ot.fotos.length ? `<span class="badge" style="background:#eaf2fb;color:var(--brand-blue)"><i class="ti ti-camera"></i> ${ot.fotos.length} foto${ot.fotos.length>1?'s':''}</span>` : ''}
        </div>

        ${ot.fotos && ot.fotos.length ? `
          <div style="margin-bottom:18px">
            <div style="font-size:13px;font-weight:600;color:var(--muted);margin-bottom:8px"><i class="ti ti-camera"></i> Fotos del chofer</div>
            <div style="display:flex;gap:10px;flex-wrap:wrap">
              ${ot.fotos.map(f => `
                <img src="${f.datos}" alt="${f.nombre}" style="width:120px;height:120px;object-fit:cover;border-radius:10px;border:1px solid var(--border);cursor:pointer"
                     onclick="verFotoGrande('${f.datos}')">
              `).join("")}
            </div>
            <p style="font-size:11.5px;color:var(--muted);margin-top:6px"><i class="ti ti-info-circle"></i> Las fotos se borran al cerrar la OT.</p>
          </div>
        ` : ''}

        ${ot.items.length === 0 ? `<div class="empty"><i class="ti ti-list"></i>Sin items en esta OT</div>` : `
          <div class="table-wrap">
            <table>
              <thead><tr>
                <th class="center">#</th><th>Descripción</th><th class="center">Tipo</th>
                <th class="center">Estado</th><th>Técnico</th><th>Material necesario</th><th class="td-action"></th>
              </tr></thead>
              <tbody>
                ${ot.items.map((it, idx) => `
                  <tr>
                    <td class="center" style="color:var(--muted)">${idx+1}</td>
                    <td>${it.descripcion}</td>
                    <td class="center">
                      <select onchange="actualizarItem(${it.id},'tipo',this.value)" style="padding:4px 8px;border:1px solid var(--border);border-radius:6px;font-size:12px;color:${COLOR_TIPO_ITEM[it.tipo]};font-weight:600">
                        ${TIPOS_ITEM.map(t => `<option value="${t}" ${it.tipo===t?'selected':''}>${LABEL_TIPO_ITEM[t]}</option>`).join("")}
                      </select>
                    </td>
                    <td class="center">
                      <select onchange="actualizarItem(${it.id},'estado',this.value)" style="padding:4px 8px;border:1px solid var(--border);border-radius:6px;font-size:12px">
                        <option value="pendiente" ${it.estado==='pendiente'?'selected':''}>Pendiente</option>
                        <option value="en_proceso" ${it.estado==='en_proceso'?'selected':''}>En proceso</option>
                        <option value="completado" ${it.estado==='completado'?'selected':''}>Completado</option>
                      </select>
                    </td>
                    <td>
                      <input type="text" value="${it.tecnico || ''}" placeholder="Nombre"
                        onblur="actualizarItem(${it.id},'tecnico',this.value)"
                        style="width:110px;padding:4px 8px;border:1px solid var(--border);border-radius:6px;font-size:12px">
                    </td>
                    <td>
                      <input type="text" value="${it.material_pedido || ''}" placeholder="ej: WD40, repuesto X"
                        onblur="actualizarItem(${it.id},'material_pedido',this.value)"
                        style="width:160px;padding:4px 8px;border:1px solid var(--border);border-radius:6px;font-size:12px">
                    </td>
                    <td class="td-action">
                      <button class="icon-btn" onclick="borrarItemOT(${it.id}, ${ot.id})"><i class="ti ti-trash"></i></button>
                    </td>
                  </tr>
                `).join("")}
              </tbody>
            </table>
          </div>
        `}

        <div class="form-row" style="margin-top:14px;align-items:flex-end">
          <div class="field" style="flex:1"><label>Agregar item</label><input id="ot-new-item" placeholder="Descripción del trabajo"></div>
          <button class="btn btn-ghost" onclick="agregarItemOT(${ot.id})"><i class="ti ti-plus"></i> Agregar</button>
        </div>

        <div style="display:flex;gap:10px;justify-content:flex-end;margin-top:22px;padding-top:18px;border-top:1px solid var(--border)">
          <button class="btn btn-ghost" onclick="window.open('/api/ots/${ot.id}/pdf','_blank')"><i class="ti ti-printer"></i> Imprimir PDF</button>
          ${!ot.estado_compras ?
            `<button class="btn btn-primary" onclick="enviarACompras(${ot.id})"><i class="ti ti-shopping-cart"></i> Enviar a Compras</button>` :
            `<span class="badge ${COLOR_COMPRAS[ot.estado_compras]||''}" style="align-self:center"><i class="ti ti-shopping-cart"></i> ${LABEL_COMPRAS[ot.estado_compras]||ot.estado_compras}</span>`
          }
          ${ot.estado !== 'cerrada' ?
            `<button class="btn btn-success" onclick="cerrarOT(${ot.id})"><i class="ti ti-circle-check"></i> Cerrar OT</button>` :
            `<button class="btn btn-ghost" onclick="reabrirOT(${ot.id})"><i class="ti ti-arrow-back"></i> Reabrir</button>`
          }
          <button class="btn btn-ghost" onclick="cerrarModalOTDetalle()">Cerrar ventana</button>
        </div>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
  overlay.addEventListener("click", e => { if (e.target === overlay) cerrarModalOTDetalle(); });
}

function cerrarModalOTDetalle() {
  const m = document.getElementById("modal-ot-detalle");
  if (m) m.remove();
  renderOts();
}

async function actualizarItem(itemId, campo, valor) {
  if (campo === "costo") {
    valor = (valor || "0").toString().replace(/\./g, "").replace(/,/g, ".");
  }
  await api(`/api/ot_items/${itemId}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ [campo]: valor })
  });
  toast(`Item actualizado`, "success");
}

async function agregarItemOT(otId) {
  const desc = $("#ot-new-item").value.trim();
  if (!desc) { toast("Escribí una descripción", "error"); return; }
  await api(`/api/ots/${otId}/items`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ descripcion: desc, tipo: detectarTipoItem(desc) })
  });
  cerrarModalOTDetalle();
  abrirOT(otId);
}

async function borrarItemOT(itemId, otId) {
  if (!confirm("¿Eliminar este item?")) return;
  await api(`/api/ot_items/${itemId}`, { method: "DELETE" });
  cerrarModalOTDetalle();
  abrirOT(otId);
}

async function cerrarOT(otId) {
  if (!confirm("¿Cerrar la OT? Los items que queden pendientes se mantendrán.")) return;
  await api(`/api/ots/${otId}/cerrar`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  toast("OT cerrada", "success");
  cerrarModalOTDetalle();
}

async function reabrirOT(otId) {
  await api(`/api/ots/${otId}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ estado: "abierta", fecha_cierre: null })
  });
  toast("OT reabierta", "success");
  cerrarModalOTDetalle();
}

async function borrarOT(otId) {
  if (!confirm(`¿Eliminar la OT #${otId} completa? Se borrarán todos sus items.`)) return;
  await api(`/api/ots/${otId}`, { method: "DELETE" });
  toast("OT eliminada");
  renderOts();
}


// ════════════════════════════════════════════════════════════════════════
//  REPORTE GERENCIAL
// ════════════════════════════════════════════════════════════════════════

async function renderGerencial() {
  status("Reporte gerencial");
  // Por defecto: mes actual
  const hoyD = new Date();
  const desde = `${hoyD.getFullYear()}-${String(hoyD.getMonth()+1).padStart(2,'0')}-01`;
  const ult = new Date(hoyD.getFullYear(), hoyD.getMonth()+1, 0);
  const hasta = `${ult.getFullYear()}-${String(ult.getMonth()+1).padStart(2,'0')}-${String(ult.getDate()).padStart(2,'0')}`;

  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-report"></i> Reporte Gerencial</h1>
      <p>Resumen ejecutivo de toda la flota — para presentar a gerencia</p>
    </div>
    <div class="section">

      <div class="ger-tabs">
        <button class="ger-tab on" data-tab="flota" onclick="gerencialTab('flota')"><i class="ti ti-truck"></i> Flota completa</button>
        <button class="ger-tab" data-tab="coche" onclick="gerencialTab('coche')"><i class="ti ti-file-analytics"></i> Dossier por coche</button>
      </div>

      <div class="ger-panel" data-panel="flota">
        <div class="card">
          <div class="card-head"><i class="ti ti-calendar"></i> Seleccionar período</div>
          <div class="card-body">
            <div class="form-row">
              <div class="field"><label>Desde</label><input id="rg-desde" type="date" value="${desde}"></div>
              <div class="field"><label>Hasta</label><input id="rg-hasta" type="date" value="${hasta}"></div>
              <button class="btn btn-ghost" onclick="rangoRapido('semana')"><i class="ti ti-calendar-week"></i> Última semana</button>
              <button class="btn btn-ghost" onclick="rangoRapido('mes')"><i class="ti ti-calendar-month"></i> Este mes</button>
              <button class="btn btn-ghost" onclick="rangoRapido('mes_pasado')"><i class="ti ti-calendar-stats"></i> Mes pasado</button>
              <button class="btn btn-primary" onclick="cargarReporteGerencial()"><i class="ti ti-search"></i> Generar</button>
              <button class="btn btn-pdf" onclick="descargarReporteGerencial()"><i class="ti ti-file-type-pdf"></i> Descargar PDF</button>
            </div>
          </div>
        </div>
        <div id="rg-resultado"></div>
      </div>

      <div class="ger-panel" data-panel="coche" style="display:none">
        <div class="card">
          <div class="card-head"><i class="ti ti-file-analytics"></i> Dossier completo de un coche</div>
          <div class="card-body">
            <div class="form-row" style="align-items:flex-end">
              <div class="field" style="flex:1;min-width:240px"><label>Coche</label>
                <select id="dossier-coche-sel"><option value="">Cargando...</option></select>
              </div>
              <div class="field"><label>Desde</label><input id="dossier-desde" type="date" value="${desde}"></div>
              <div class="field"><label>Hasta</label><input id="dossier-hasta" type="date" value="${hasta}"></div>
              <button class="btn btn-primary" onclick="generarDossier()"><i class="ti ti-file-search"></i> Generar dossier</button>
            </div>
            <p class="hint" style="margin-top:10px"><i class="ti ti-info-circle"></i> Junta todo el historial del coche en una hoja: OEE, correctivos, neumáticos, costos, y un diagnóstico con foco en soluciones.</p>
          </div>
        </div>
        <div id="dossier-resultado"></div>
      </div>

    </div>`;
  cargarReporteGerencial();
  cargarSelectorDossier();
}

function rangoRapido(periodo) {
  const hoyD = new Date();
  let desde, hasta = hoyD.toISOString().slice(0,10);
  if (periodo === "semana") {
    const d = new Date(hoyD); d.setDate(d.getDate() - 7);
    desde = d.toISOString().slice(0,10);
  } else if (periodo === "mes") {
    desde = `${hoyD.getFullYear()}-${String(hoyD.getMonth()+1).padStart(2,'0')}-01`;
    const ult = new Date(hoyD.getFullYear(), hoyD.getMonth()+1, 0);
    hasta = ult.toISOString().slice(0,10);
  } else if (periodo === "mes_pasado") {
    const mp = new Date(hoyD.getFullYear(), hoyD.getMonth()-1, 1);
    const ult = new Date(hoyD.getFullYear(), hoyD.getMonth(), 0);
    desde = mp.toISOString().slice(0,10);
    hasta = ult.toISOString().slice(0,10);
  }
  $("#rg-desde").value = desde;
  $("#rg-hasta").value = hasta;
  cargarReporteGerencial();
}

async function cargarReporteGerencial() {
  const desde = $("#rg-desde").value;
  const hasta = $("#rg-hasta").value;
  if (!desde || !hasta) { toast("Elegí ambas fechas", "error"); return; }
  const r = await api(`/api/reporte_gerencial?desde=${desde}&hasta=${hasta}`);
  const res = $("#rg-resultado");

  const pendientes = r.ots.filter(o => o.estado !== "cerrada").length;
  const cerradas = r.ots.filter(o => o.estado === "cerrada").length;

  res.innerHTML = `
    <div class="section-title"><i class="ti ti-chart-pie"></i> Resumen del período · ${desde} → ${hasta}</div>

    <div class="metrics">
      <div class="metric">
        <div class="metric-icon blue"><i class="ti ti-clipboard-check"></i></div>
        <div class="metric-content"><div class="metric-label">Órdenes de Trabajo</div><div class="metric-value">${r.ots.length}</div>
          <div class="metric-foot">${pendientes} abiertas · ${cerradas} cerradas</div></div>
      </div>
      <div class="metric success">
        <div class="metric-icon green"><i class="ti ti-tool"></i></div>
        <div class="metric-content"><div class="metric-label">Preventivos</div><div class="metric-value">${r.preventivos_count}</div>
          <div class="metric-foot">${gs(r.preventivos_costo)}</div></div>
      </div>
      <div class="metric danger">
        <div class="metric-icon red"><i class="ti ti-alert-triangle"></i></div>
        <div class="metric-content"><div class="metric-label">Correctivos</div><div class="metric-value">${r.correctivos_count}</div>
          <div class="metric-foot">${gs(r.correctivos_costo)}</div></div>
      </div>
      <div class="metric">
        <div class="metric-icon blue"><i class="ti ti-disc"></i></div>
        <div class="metric-content"><div class="metric-label">Cambios neumáticos</div><div class="metric-value">${r.cambios_neumaticos}</div></div>
      </div>
      <div class="metric warning">
        <div class="metric-icon amber"><i class="ti ti-coin"></i></div>
        <div class="metric-content"><div class="metric-label">Costo total</div><div class="metric-value">${gsSmall(r.costo_total)}</div></div>
      </div>
    </div>

    ${r.items_por_tipo && r.items_por_tipo.length > 0 ? `
      <div class="section-title"><i class="ti ti-chart-bar"></i> Trabajos por tipo</div>
      <div class="card"><div class="card-body">
        ${r.items_por_tipo.map(t => {
          const total = r.items_por_tipo.reduce((s, x) => s + x.cant, 0);
          const pct = total ? (t.cant / total) * 100 : 0;
          return `
            <div class="cost-row">
              <div class="cost-label">${LABEL_TIPO_ITEM[t.tipo] || t.tipo}</div>
              <div class="cost-bar-track"><div class="cost-bar" style="width:${pct}%;background:${COLOR_TIPO_ITEM[t.tipo] || 'var(--brand)'}"></div></div>
              <div class="cost-pct">${t.cant}</div>
              <div class="cost-val">${gs(t.costo)}</div>
            </div>`;
        }).join("")}
      </div></div>
    ` : ""}

    ${r.top_vehiculos && r.top_vehiculos.length > 0 ? `
      <div class="section-title"><i class="ti ti-trending-up"></i> Top vehículos por costo</div>
      <div class="table-wrap">
        <table>
          <thead><tr>
            <th class="center">#</th><th>Patente</th><th>N° int.</th>
            <th>Marca / Modelo</th><th class="num">Costo total</th>
          </tr></thead>
          <tbody>
            ${r.top_vehiculos.map((v, i) => `
              <tr>
                <td class="center"><b>${i+1}</b></td>
                <td><b>${v.patente}</b></td>
                <td>${v.n_interno || "—"}</td>
                <td>${v.marca || ""} ${v.modelo || ""}</td>
                <td class="num"><b>${gs(v.costo_total)}</b></td>
              </tr>`).join("")}
          </tbody>
        </table>
      </div>
    ` : ""}

    ${r.docs_proximos && r.docs_proximos.length > 0 ? `
      <div class="section-title"><i class="ti ti-alert-triangle"></i> Documentos por vencer / vencidos</div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Patente</th><th>Tipo</th><th>Documento</th><th>Vencimiento</th><th class="center">Días</th></tr></thead>
          <tbody>
            ${r.docs_proximos.map(d => `
              <tr>
                <td><b>${d.patente}</b></td>
                <td><span class="badge cat">${d.tipo}</span></td>
                <td>${d.nombre || "—"}</td>
                <td>${d.fecha_vencimiento}</td>
                <td class="center">
                  ${d.dias_restantes < 0
                    ? `<span class="badge danger"><span class="dot"></span> Vencido ${Math.abs(d.dias_restantes)}d</span>`
                    : `<span class="badge warning"><span class="dot"></span> ${d.dias_restantes}d</span>`}
                </td>
              </tr>`).join("")}
          </tbody>
        </table>
      </div>
    ` : ""}
  `;
}

function descargarReporteGerencial() {
  const desde = $("#rg-desde").value;
  const hasta = $("#rg-hasta").value;
  if (!desde || !hasta) { toast("Elegí ambas fechas", "error"); return; }
  toast("Generando PDF...", "success");
  window.open(`/api/exportar_reporte_gerencial?desde=${desde}&hasta=${hasta}`, "_blank");
}


// ════════════════════════════════════════════════════════════════════════
//  USUARIOS Y SESIÓN
// ════════════════════════════════════════════════════════════════════════

async function cerrarSesion() {
  if (!confirm("¿Cerrar sesión?")) return;
  await fetch("/api/logout", { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
  window.location.href = "/login";
}

const LABEL_ROL = { admin: "Administración", taller: "Taller", compras: "Compras", auditor: "Auditor", chofer: "Chofer" };

async function renderUsuarios() {
  status("Gestión de usuarios");
  let usuarios = [];
  try {
    usuarios = await api("/api/usuarios");
  } catch (e) {
    content.innerHTML = `<div class="section"><div class="empty"><i class="ti ti-lock"></i>Solo el administrador puede gestionar usuarios.</div></div>`;
    return;
  }

  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-users"></i> Usuarios del sistema</h1>
      <p>Gestión de accesos — crear usuarios y asignar permisos</p>
    </div>
    <div class="section">

      <div class="card">
        <div class="card-head"><i class="ti ti-user-plus"></i> Nuevo usuario</div>
        <div class="card-body">
          <div class="form-row">
            <div class="field"><label>Usuario *</label><input id="u-user" placeholder="jperez" style="width:140px"></div>
            <div class="field" style="flex:1;min-width:180px"><label>Nombre completo</label><input id="u-nombre" placeholder="Juan Pérez"></div>
            <div class="field"><label>Contraseña *</label><input id="u-pass" type="password" placeholder="••••••" style="width:140px"></div>
            <div class="field"><label>Rol</label>
              <select id="u-rol" style="width:200px">
                <option value="taller">Taller (operación)</option>
                <option value="admin">Administración (todo)</option>
                <option value="compras">Compras / Depósito</option>
                <option value="auditor">Auditor (combustible e historial)</option>
                <option value="chofer">Chofer (solo reportar)</option>
              </select>
            </div>
            <button class="btn btn-primary" onclick="guardarUsuario()"><i class="ti ti-plus"></i> Crear</button>
          </div>
          <p class="hint" style="margin-top:14px">
            <i class="ti ti-info-circle"></i>
            <b>Taller</b>: gestiona órdenes de trabajo, mantenimiento, neumáticos, correctivos y todo lo operativo. <b>Administración</b>: acceso total + puede crear y administrar usuarios. <b>Chofer</b>: solo ve una pantalla simple para cargar sus reportes desde el celular.
          </p>
        </div>
      </div>

      <div class="section-title"><i class="ti ti-list"></i> Usuarios registrados (${usuarios.length})</div>
      <div class="table-wrap">
        <table>
          <thead><tr>
            <th>Usuario</th><th>Nombre</th><th class="center">Rol</th>
            <th class="center">Estado</th><th>Último acceso</th><th class="td-action"></th>
          </tr></thead>
          <tbody>
            ${usuarios.map(u => `
              <tr>
                <td><b>${u.usuario}</b></td>
                <td>${u.nombre || "—"}</td>
                <td class="center"><span class="rol-badge ${u.rol}">${LABEL_ROL[u.rol] || u.rol}</span></td>
                <td class="center">${u.activo ? '<span class="badge success">Activo</span>' : '<span class="badge">Inactivo</span>'}</td>
                <td style="font-size:12px;color:var(--muted)">${u.ultimo_acceso ? u.ultimo_acceso.replace('T',' ') : 'Nunca'}</td>
                <td class="td-action">
                  <button class="icon-btn" onclick="cambiarPassUsuario(${u.id}, '${u.usuario}')" title="Cambiar contraseña"><i class="ti ti-key"></i></button>
                  <button class="icon-btn" onclick="borrarUsuario(${u.id}, '${u.usuario}')" title="Eliminar"><i class="ti ti-trash"></i></button>
                </td>
              </tr>`).join("")}
          </tbody>
        </table>
      </div>
    </div>`;
}

async function guardarUsuario() {
  const user = $("#u-user").value.trim();
  const pass = $("#u-pass").value;
  if (!user || !pass) { toast("Usuario y contraseña obligatorios", "error"); return; }
  const r = await api("/api/usuarios", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      usuario: user, password: pass,
      nombre: $("#u-nombre").value.trim(), rol: $("#u-rol").value
    })
  });
  if (r.ok) {
    toast("Usuario creado", "success");
    renderUsuarios();
  } else toast(r.msg, "error");
}

async function cambiarPassUsuario(uid, usuario) {
  const nueva = prompt(`Nueva contraseña para "${usuario}":`);
  if (!nueva) return;
  const r = await api(`/api/usuarios/${uid}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password: nueva })
  });
  if (r.ok) toast("Contraseña actualizada", "success");
  else toast(r.msg || "Error", "error");
}

async function borrarUsuario(uid, usuario) {
  if (!confirm(`¿Eliminar al usuario "${usuario}"?`)) return;
  const r = await api(`/api/usuarios/${uid}`, { method: "DELETE" });
  if (r.ok) { toast("Usuario eliminado"); renderUsuarios(); }
  else toast(r.msg || "Error", "error");
}


async function cargarFlotaInicial() {
  if (!confirm("¿Cargar la flota completa desde el Excel?\n\nSe hace en 2 pasos: primero los 89 vehículos, después los documentos. Puede tardar un minuto.")) return;

  // Paso 1: vehículos
  status("Cargando vehículos... (paso 1 de 2)");
  toast("Cargando vehículos, aguardá...", "success");
  let r = await api("/api/cargar_flota_inicial", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paso: "vehiculos" })
  });
  if (!r.ok) {
    toast(r.msg || "Error al cargar vehículos", "error");
    return;
  }
  toast(r.msg, "success");

  // Paso 2: documentos
  status("Cargando documentos... (paso 2 de 2)");
  toast("Ahora los documentos, un momento más...", "success");
  r = await api("/api/cargar_flota_inicial", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ paso: "documentos" })
  });
  if (r.ok) {
    toast("¡Flota cargada completa! " + r.msg, "success");
  } else {
    toast("Vehículos cargados. Documentos: " + (r.msg || "error"), "error");
  }
  setTimeout(() => renderDashboard(), 1200);
}



// ════════════════════════════════════════════════════════════════════════
//  INVENTARIO DE REPUESTOS (DEPÓSITO) — vista de búsqueda rápida
// ════════════════════════════════════════════════════════════════════════

const CAT_REPUESTOS = [
  "Filtros", "Correas y mangueras", "Lubricantes y aditivos",
  "Rulemanes / rodamientos", "Tensores / bombas", "Embragues / frenos",
  "Eléctricos", "Tornillería / ferretería", "Neumáticos",
  "Usados recuperables", "Varios",
];

// Color de cada zona (coincide con la zonificación física del depósito)
// pasillo (primera letra) → color. A=alta rotación, B=mecánicos, C=eléctricos, D=usados.
const COLOR_ZONA = {
  A: "#185FA5", B: "#3B6D11", C: "#854F0B", D: "#993C1D",
  _: "#5F5E5A",  // por defecto si no tiene pasillo conocido
};
function colorZona(pasillo) {
  const p = (pasillo || "").trim().toUpperCase().charAt(0);
  return COLOR_ZONA[p] || COLOR_ZONA._;
}
function nombreZona(categoria) {
  return categoria || "Repuesto";
}

const LABEL_ESTADO_STOCK = { ok: "en stock", bajo: "queda poco", sin_stock: "sin stock" };

let repBuscar = "";
let repFiltroCategoria = "";
let repVistaAdmin = false;   // toggle para mostrar el panel de gestión/cargar

async function renderRepuestos() {
  status("Inventario de repuestos");

  // Traer resumen (para los números de arriba) y la lista filtrada
  const resumen = await api("/api/repuestos/resumen");
  let qs = [];
  if (repBuscar) qs.push("buscar=" + encodeURIComponent(repBuscar));
  if (repFiltroCategoria) qs.push("categoria=" + encodeURIComponent(repFiltroCategoria));
  const reps = await api("/api/repuestos" + (qs.length ? "?" + qs.join("&") : ""));

  const puedeEditar = (window.USUARIO_ROL === "admin" || window.USUARIO_ROL === "taller");

  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-packages"></i> Depósito de Repuestos</h1>
    </div>

    <div class="section">

      <!-- BUSCADOR GRANDE -->
      <div class="rep-search-box">
        <i class="ti ti-search rep-search-ico"></i>
        <input id="rep-search" class="rep-search-input" autocomplete="off"
               placeholder="Filtro de aceite, correa, código..."
               value="${repBuscar.replace(/"/g, "&quot;")}"
               oninput="repBuscarDebounce(this.value)">
        ${repBuscar ? `<button class="rep-search-clear" onclick="repLimpiarBusqueda()"><i class="ti ti-x"></i></button>` : ""}
      </div>

      <!-- chips de categoría para filtrar rápido -->
      <div class="rep-chips">
        <button class="rep-chip ${!repFiltroCategoria ? "on" : ""}" onclick="repFiltrarCat('')">Todo</button>
        ${CAT_REPUESTOS.map(c => `<button class="rep-chip ${repFiltroCategoria === c ? "on" : ""}" onclick="repFiltrarCat('${c.replace(/'/g, "")}')">${c}</button>`).join("")}
      </div>

      <!-- resumen mini -->
      <div class="rep-summary">
        <span><b>${resumen.total_items}</b> repuestos</span>
        <span class="rep-dot">·</span>
        <span><b>${gsSmall(resumen.valor_total)}</b> en stock</span>
        ${resumen.cant_bajos + resumen.cant_sin_stock > 0 ? `
          <span class="rep-dot">·</span>
          <span class="rep-alerta-link" onclick="repFiltrarBajos()">
            <i class="ti ti-alert-triangle"></i> ${resumen.cant_bajos + resumen.cant_sin_stock} para pedir
          </span>` : ""}
      </div>

      <!-- RESULTADOS -->
      <div id="rep-resultados">
        ${renderListaRepuestos(reps)}
      </div>

      ${puedeEditar ? `
        <div class="rep-admin-toggle">
          <button class="btn btn-ghost" onclick="repToggleAdmin()">
            <i class="ti ti-${repVistaAdmin ? "chevron-up" : "plus"}"></i>
            ${repVistaAdmin ? "Ocultar" : "Cargar un repuesto nuevo"}
          </button>
        </div>
        <div id="rep-admin-panel" style="${repVistaAdmin ? "" : "display:none"}">
          ${renderPanelCargar()}
        </div>
      ` : ""}

    </div>`;

  // refocus al buscador si venías escribiendo
  const inp = $("#rep-search");
  if (inp && repBuscar) { inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length); }
}

// ─── Lista de tarjetas de resultado ───
function renderListaRepuestos(reps) {
  if (!reps.length) {
    if (repBuscar || repFiltroCategoria) {
      return `<div class="empty"><i class="ti ti-search-off"></i>No encontré nada con eso.<br>Probá con otra palabra o el código.</div>`;
    }
    return `<div class="empty"><i class="ti ti-package-off"></i>El depósito está vacío.<br>Cargá el primer repuesto abajo.</div>`;
  }
  return reps.map(r => {
    const col = colorZona(r.ubic_pasillo);
    const est = r.estado_stock;
    const stkClass = est === "ok" ? "ok" : est === "bajo" ? "bajo" : "sin";
    const stkIcon = est === "ok" ? "circle-check" : est === "bajo" ? "alert-triangle" : "circle-x";
    const stkTxt = est === "sin_stock" ? "sin stock"
                 : `${fmtNum(r.stock_actual)} ${r.unidad}${est === "bajo" ? " — poco" : ""}`;
    return `
      <div class="rep-card" style="border-left-color:${col}" onclick="abrirRepuesto(${r.id})">
        <div class="rep-card-main">
          <div class="rep-card-info">
            <div class="rep-card-titulo">${r.descripcion}</div>
            <div class="rep-card-sub">${[r.aplicacion, r.codigo].filter(Boolean).join(" · ")}</div>
          </div>
          <div class="rep-stock-badge ${stkClass}">
            <i class="ti ti-${stkIcon}"></i> ${stkTxt}
          </div>
        </div>
        ${r.ubicacion ? `
          <div class="rep-card-ubic" style="background:${col}14">
            <i class="ti ti-map-pin" style="color:${col};font-size:24px"></i>
            <div>
              <div class="rep-card-zona" style="color:${col}">${nombreZona(r.categoria)}</div>
              <div class="rep-card-codubic" style="color:${col}">${r.ubicacion}</div>
            </div>
          </div>
        ` : `
          <div class="rep-card-ubic rep-sin-ubic">
            <i class="ti ti-map-pin-off" style="font-size:20px"></i>
            <span>Sin ubicación asignada</span>
          </div>
        `}
      </div>`;
  }).join("");
}

// ─── Panel de carga (solo admin/taller) ───
function renderPanelCargar() {
  return `
    <div class="card">
      <div class="card-head"><i class="ti ti-plus"></i> Nuevo repuesto</div>
      <div class="card-body">
        <div class="form-row">
          <div class="field"><label>Código fabricante *</label><input id="r-cod" placeholder="MANN-W1374" style="width:160px"></div>
          <div class="field" style="flex:1;min-width:200px"><label>Descripción *</label><input id="r-desc" placeholder="Filtro de aceite"></div>
          <div class="field"><label>Categoría</label>
            <select id="r-cat">${CAT_REPUESTOS.map(c => `<option value="${c}">${c}</option>`).join("")}</select>
          </div>
        </div>
        <div class="form-row" style="margin-top:14px">
          <div class="field"><label>Marca</label><input id="r-mar" placeholder="Mann" style="width:130px"></div>
          <div class="field"><label>Aplicación (qué coche)</label><input id="r-apl" placeholder="Scania DC12" style="width:170px"></div>
          <div class="field"><label>Código alt.</label><input id="r-codalt" placeholder="opcional" style="width:130px"></div>
          <div class="field"><label>Proveedor</label><input id="r-prov" placeholder="opcional" style="width:150px"></div>
        </div>

        <div class="rep-ubic-form">
          <div class="rep-ubic-form-label"><i class="ti ti-map-pin"></i> ¿Dónde se guarda?</div>
          <div class="rep-ubic-inputs">
            <div class="field"><label>Pasillo</label><input id="r-up" placeholder="A" maxlength="2" style="width:64px;text-transform:uppercase;text-align:center;font-size:18px;font-weight:600"></div>
            <span class="rep-ubic-sep">-</span>
            <div class="field"><label>Estante</label><input id="r-ue" placeholder="02" maxlength="3" style="width:64px;text-align:center;font-size:18px;font-weight:600"></div>
            <span class="rep-ubic-sep">-</span>
            <div class="field"><label>Nivel</label><input id="r-un" placeholder="03" maxlength="3" style="width:64px;text-align:center;font-size:18px;font-weight:600"></div>
            <span class="rep-ubic-sep">-</span>
            <div class="field"><label>Posición</label><input id="r-uo" placeholder="04" maxlength="3" style="width:64px;text-align:center;font-size:18px;font-weight:600"></div>
          </div>
        </div>

        <div class="form-row" style="margin-top:14px">
          <div class="field"><label>Cantidad inicial</label><input id="r-stk" placeholder="0" style="width:110px"></div>
          <div class="field"><label>Avisar cuando baje de</label><input id="r-min" placeholder="10" style="width:130px"></div>
          <div class="field"><label>Unidad</label>
            <select id="r-uni" style="width:110px">
              <option value="u">unidad</option><option value="litros">litros</option>
              <option value="metros">metros</option><option value="kg">kg</option>
            </select>
          </div>
          <div class="field"><label>Precio c/u (Gs.)</label><input id="r-cos" placeholder="85000" style="width:150px"></div>
          <button class="btn btn-primary" onclick="guardarRepuesto()" style="align-self:flex-end"><i class="ti ti-device-floppy"></i> Guardar</button>
        </div>
      </div>
    </div>`;
}

// ─── Búsqueda con debounce (no recargar en cada tecla) ───
let _repBuscarTimer = null;
function repBuscarDebounce(v) {
  repBuscar = v;
  clearTimeout(_repBuscarTimer);
  _repBuscarTimer = setTimeout(async () => {
    let qs = [];
    if (repBuscar) qs.push("buscar=" + encodeURIComponent(repBuscar));
    if (repFiltroCategoria) qs.push("categoria=" + encodeURIComponent(repFiltroCategoria));
    const reps = await api("/api/repuestos" + (qs.length ? "?" + qs.join("&") : ""));
    const cont = $("#rep-resultados");
    if (cont) cont.innerHTML = renderListaRepuestos(reps);
    // mostrar/ocultar la X del buscador
    const box = document.querySelector(".rep-search-box");
    let clr = box?.querySelector(".rep-search-clear");
    if (repBuscar && !clr && box) {
      clr = document.createElement("button");
      clr.className = "rep-search-clear"; clr.innerHTML = '<i class="ti ti-x"></i>';
      clr.onclick = repLimpiarBusqueda; box.appendChild(clr);
    } else if (!repBuscar && clr) clr.remove();
  }, 250);
}
function repLimpiarBusqueda() { repBuscar = ""; renderRepuestos(); }
function repFiltrarCat(c) { repFiltroCategoria = (repFiltroCategoria === c ? "" : c); renderRepuestos(); }
function repFiltrarBajos() { repBuscar = ""; repFiltroCategoria = ""; renderRepuestos().then(filtrarSoloBajosEnPantalla); }

async function filtrarSoloBajosEnPantalla() {
  const reps = await api("/api/repuestos?solo_bajos=1");
  const cont = $("#rep-resultados");
  if (cont) cont.innerHTML = `<div class="rep-filtro-aviso"><i class="ti ti-filter"></i> Mostrando solo lo que hay que pedir <button onclick="renderRepuestos()">ver todo</button></div>` + renderListaRepuestos(reps);
}

function repToggleAdmin() {
  repVistaAdmin = !repVistaAdmin;
  renderRepuestos();
  if (repVistaAdmin) setTimeout(() => $("#rep-admin-panel")?.scrollIntoView({ behavior: "smooth", block: "nearest" }), 100);
}

async function guardarRepuesto() {
  const cod = $("#r-cod").value.trim();
  const desc = $("#r-desc").value.trim();
  if (!cod) { toast("Falta el código", "error"); return; }
  if (!desc) { toast("Falta la descripción", "error"); return; }
  const limpiar = s => (s || "0").replace(/\./g, "").replace(/,/g, ".");
  const r = await api("/api/repuestos", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      codigo: cod, descripcion: desc,
      categoria: $("#r-cat").value, marca: $("#r-mar").value,
      aplicacion: $("#r-apl").value, codigo_alt: $("#r-codalt").value,
      proveedor: $("#r-prov").value,
      ubic_pasillo: $("#r-up").value, ubic_estanteria: $("#r-ue").value,
      ubic_nivel: $("#r-un").value, ubic_posicion: $("#r-uo").value,
      stock_inicial: parseFloat(limpiar($("#r-stk").value)) || 0,
      stock_minimo: parseFloat(limpiar($("#r-min").value)) || 0,
      unidad: $("#r-uni").value,
      costo_unitario: parseFloat(limpiar($("#r-cos").value)) || 0,
    })
  });
  if (r.ok) { toast("Repuesto guardado", "success"); repVistaAdmin = false; renderRepuestos(); }
  else toast(r.msg, "error");
}

// ════════════════════════════════════════════════════════════════════════
//  DETALLE DE UN REPUESTO (modal con ubicación desglosada y "Saqué 1")
// ════════════════════════════════════════════════════════════════════════

async function abrirRepuesto(id) {
  const r = await api(`/api/repuestos/${id}`);
  if (!r || r.error) { toast("No se encontró el repuesto", "error"); return; }
  const puedeEditar = (window.USUARIO_ROL === "admin" || window.USUARIO_ROL === "taller");
  const puedeEntrada = puedeEditar || window.USUARIO_ROL === "compras";
  const col = colorZona(r.ubic_pasillo);
  const est = r.estado_stock;

  const LABEL_MOV = { entrada: "Entró", salida: "Salió", ajuste: "Ajuste" };
  const COLOR_MOV = { entrada: "success", salida: "danger", ajuste: "cat" };

  // Frase explicativa de la ubicación en lenguaje natural
  let fraseUbic = "";
  if (r.ubic_pasillo || r.ubic_estanteria || r.ubic_nivel || r.ubic_posicion) {
    let p = [];
    if (r.ubic_pasillo) p.push(`pasillo <b>${r.ubic_pasillo}</b>`);
    if (r.ubic_estanteria) p.push(`estantería <b>${r.ubic_estanteria}</b>`);
    if (r.ubic_nivel) p.push(`nivel <b>${r.ubic_nivel}</b>`);
    if (r.ubic_posicion) p.push(`posición <b>${r.ubic_posicion}</b>`);
    fraseUbic = p.join(", ");
  }

  const estBadge = est === "ok"
    ? `<div class="rep-d-stockbox ok"><div class="rep-d-stocknum">${fmtNum(r.stock_actual)} ${r.unidad}</div><div class="rep-d-stocklbl">en stock</div></div>`
    : est === "bajo"
    ? `<div class="rep-d-stockbox bajo"><div class="rep-d-stocknum">${fmtNum(r.stock_actual)} ${r.unidad}</div><div class="rep-d-stocklbl">queda poco — pedir</div></div>`
    : `<div class="rep-d-stockbox sin"><div class="rep-d-stocknum">0</div><div class="rep-d-stocklbl">sin stock</div></div>`;

  const o = document.createElement("div");
  o.className = "rep-modal-overlay";
  o.innerHTML = `
    <div class="rep-modal">
      <div class="rep-modal-head" style="background:${col}">
        <div>
          <div class="rep-modal-titulo">${r.descripcion}</div>
          <div class="rep-modal-sub">${[r.aplicacion, r.codigo, r.codigo_alt].filter(Boolean).join(" · ")}</div>
        </div>
        <button class="rep-modal-x" onclick="cerrarRepuesto()"><i class="ti ti-x"></i></button>
      </div>

      <div class="rep-modal-body">

        ${r.ubicacion ? `
          <div class="rep-d-section-lbl">Dónde está</div>
          <div class="rep-d-ubic-grid">
            <div class="rep-d-ubic-cell" style="background:${col}14">
              <div class="rep-d-ubic-k" style="color:${col}">Pasillo</div>
              <div class="rep-d-ubic-v" style="color:${col}">${r.ubic_pasillo || "—"}</div>
            </div>
            <div class="rep-d-ubic-cell" style="background:${col}14">
              <div class="rep-d-ubic-k" style="color:${col}">Estante</div>
              <div class="rep-d-ubic-v" style="color:${col}">${r.ubic_estanteria || "—"}</div>
            </div>
            <div class="rep-d-ubic-cell" style="background:${col}14">
              <div class="rep-d-ubic-k" style="color:${col}">Nivel</div>
              <div class="rep-d-ubic-v" style="color:${col}">${r.ubic_nivel || "—"}</div>
            </div>
            <div class="rep-d-ubic-cell" style="background:${col}14">
              <div class="rep-d-ubic-k" style="color:${col}">Posición</div>
              <div class="rep-d-ubic-v" style="color:${col}">${r.ubic_posicion || "—"}</div>
            </div>
          </div>
          <div class="rep-d-ubic-frase">${fraseUbic}</div>
        ` : `<div class="rep-d-sin-ubic"><i class="ti ti-map-pin-off"></i> Este repuesto no tiene ubicación asignada todavía${puedeEditar ? ". Editalo para agregarla." : ""}</div>`}

        <div class="rep-d-stats">
          ${estBadge}
          <div class="rep-d-statbox">
            <div class="rep-d-statlbl">Mínimo</div>
            <div class="rep-d-statval">${fmtNum(r.stock_minimo)}</div>
          </div>
          <div class="rep-d-statbox">
            <div class="rep-d-statlbl">Valor del stock</div>
            <div class="rep-d-statval">${gsSmall(r.valor_stock)}</div>
          </div>
        </div>

        ${puedeEntrada ? `
          <div class="rep-d-acciones-main">
            <button class="rep-btn-saque" ${r.stock_actual <= 0 ? "disabled" : ""} onclick="saqueRapido(${r.id})">
              <i class="ti ti-minus"></i> Saqué 1
            </button>
            <button class="rep-btn-saque-otro" ${r.stock_actual <= 0 ? "disabled" : ""} onclick="movimientoManual(${r.id}, 'salida')">
              otra cantidad
            </button>
          </div>
          <div class="rep-d-acciones-sec">
            <button onclick="movimientoManual(${r.id}, 'entrada')"><i class="ti ti-plus"></i> Entró stock</button>
            ${puedeEditar ? `<button onclick="ajusteStock(${r.id}, ${r.stock_actual})"><i class="ti ti-adjustments"></i> Ajustar conteo</button>` : ""}
            ${puedeEditar ? `<button onclick="editarRepuesto(${r.id})"><i class="ti ti-edit"></i> Editar</button>` : ""}
          </div>
        ` : ""}

        <div class="rep-d-section-lbl" style="margin-top:22px">Últimos movimientos</div>
        ${r.movimientos.length === 0
          ? `<div class="rep-d-sin-mov">Todavía no se registró ningún movimiento.</div>`
          : `<div class="rep-d-movs">
              ${r.movimientos.slice(0, 12).map(m => `
                <div class="rep-d-mov">
                  <span class="rep-d-mov-tipo ${COLOR_MOV[m.tipo]}">${m.tipo === "salida" ? "−" : m.tipo === "entrada" ? "+" : "="}${fmtNum(m.cantidad)}</span>
                  <span class="rep-d-mov-mot">${m.motivo || LABEL_MOV[m.tipo]}</span>
                  <span class="rep-d-mov-meta">${m.fecha}${m.usuario ? " · " + m.usuario : ""}</span>
                  ${puedeEditar ? `<button class="rep-d-mov-del" onclick="borrarMovimiento(${m.id}, ${r.id})"><i class="ti ti-x"></i></button>` : ""}
                </div>`).join("")}
            </div>`}

        ${puedeEditar ? `
          <div class="rep-d-baja">
            <button onclick="borrarRepuesto(${r.id}, '${(r.codigo || "").replace(/'/g, "")}')"><i class="ti ti-trash"></i> Dar de baja este repuesto</button>
          </div>
        ` : ""}

      </div>
    </div>`;
  o.onclick = (e) => { if (e.target === o) cerrarRepuesto(); };
  document.body.appendChild(o);
  requestAnimationFrame(() => o.classList.add("visible"));
}

function cerrarRepuesto() {
  document.querySelectorAll(".rep-modal-overlay").forEach(o => {
    o.classList.remove("visible");
    setTimeout(() => o.remove(), 180);
  });
}

// "Saqué 1" — descuenta una unidad al toque, sin preguntar nada
async function saqueRapido(rid) {
  const r = await api(`/api/repuestos/${rid}/movimiento`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tipo: "salida", cantidad: 1, motivo: "Saqué del depósito" })
  });
  if (r.ok) {
    toast(`Listo, queda ${fmtNum(r.stock_actual)}`, "success");
    refrescarTrasMovimiento(rid);
  } else toast(r.msg, "error");
}

// Movimiento con cantidad escrita (salida grande o entrada)
function movimientoManual(rid, tipo) {
  const esEntrada = tipo === "entrada";
  const o = document.createElement("div");
  o.className = "rep-modal-overlay visible";
  o.style.zIndex = "1600";
  o.innerHTML = `
    <div class="rep-mini-modal">
      <div class="rep-mini-titulo">${esEntrada ? "Entró stock" : "Saqué del depósito"}</div>
      <label class="rep-mini-lbl">¿Cuántas unidades?</label>
      <input id="mm-cant" class="rep-mini-input" type="text" inputmode="decimal" placeholder="1" autofocus>
      <label class="rep-mini-lbl">Motivo (opcional)</label>
      <input id="mm-mot" class="rep-mini-input" placeholder="${esEntrada ? "Compra, devolución..." : "Uso en coche 47, rotura..."}">
      ${esEntrada ? `<label class="rep-mini-lbl">Precio c/u (opcional)</label><input id="mm-cos" class="rep-mini-input" placeholder="Gs.">` : ""}
      <div class="rep-mini-btns">
        <button class="btn btn-ghost" onclick="this.closest('.rep-modal-overlay').remove()">Cancelar</button>
        <button class="btn btn-primary" onclick="confirmarMovManual(${rid}, '${tipo}', this)">
          <i class="ti ti-check"></i> ${esEntrada ? "Sumar" : "Descontar"}
        </button>
      </div>
    </div>`;
  o.onclick = (e) => { if (e.target === o) o.remove(); };
  document.body.appendChild(o);
  setTimeout(() => document.getElementById("mm-cant")?.focus(), 50);
}

async function confirmarMovManual(rid, tipo, btn) {
  const cant = parseFloat((document.getElementById("mm-cant").value || "").replace(/\./g, "").replace(/,/g, "."));
  if (!cant || cant <= 0) { toast("Poné una cantidad", "error"); return; }
  const mot = document.getElementById("mm-mot").value;
  const cosEl = document.getElementById("mm-cos");
  const cos = cosEl ? parseFloat((cosEl.value || "0").replace(/\./g, "").replace(/,/g, ".")) : 0;
  const r = await api(`/api/repuestos/${rid}/movimiento`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tipo, cantidad: cant, motivo: mot, costo_unitario: cos || 0 })
  });
  if (r.ok) {
    toast(`Hecho, queda ${fmtNum(r.stock_actual)}`, "success");
    btn.closest(".rep-modal-overlay").remove();
    refrescarTrasMovimiento(rid);
  } else toast(r.msg, "error");
}

// Ajuste de inventario físico (fijar el stock al número contado)
function ajusteStock(rid, actual) {
  const o = document.createElement("div");
  o.className = "rep-modal-overlay visible";
  o.style.zIndex = "1600";
  o.innerHTML = `
    <div class="rep-mini-modal">
      <div class="rep-mini-titulo">Ajustar conteo</div>
      <p class="rep-mini-help">Contaste físicamente y el número no coincide. Poné cuántas hay realmente y el sistema lo corrige.</p>
      <label class="rep-mini-lbl">Cantidad real contada</label>
      <input id="aj-cant" class="rep-mini-input" type="text" inputmode="decimal" placeholder="${fmtNum(actual)}" autofocus>
      <div class="rep-mini-btns">
        <button class="btn btn-ghost" onclick="this.closest('.rep-modal-overlay').remove()">Cancelar</button>
        <button class="btn btn-primary" onclick="confirmarAjuste(${rid}, this)"><i class="ti ti-check"></i> Corregir</button>
      </div>
    </div>`;
  o.onclick = (e) => { if (e.target === o) o.remove(); };
  document.body.appendChild(o);
  setTimeout(() => document.getElementById("aj-cant")?.focus(), 50);
}

async function confirmarAjuste(rid, btn) {
  const cant = parseFloat((document.getElementById("aj-cant").value || "").replace(/\./g, "").replace(/,/g, "."));
  if (isNaN(cant) || cant < 0) { toast("Poné un número válido", "error"); return; }
  const r = await api(`/api/repuestos/${rid}/movimiento`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ tipo: "ajuste", cantidad: cant, motivo: "Conteo físico" })
  });
  if (r.ok) {
    toast(`Corregido a ${fmtNum(r.stock_actual)}`, "success");
    btn.closest(".rep-modal-overlay").remove();
    refrescarTrasMovimiento(rid);
  } else toast(r.msg, "error");
}

// Refresca el modal de detalle y la lista de fondo
function refrescarTrasMovimiento(rid) {
  cerrarRepuesto();
  setTimeout(() => abrirRepuesto(rid), 200);
  // refrescar la lista de fondo si está visible
  const cont = $("#rep-resultados");
  if (cont) {
    let qs = [];
    if (repBuscar) qs.push("buscar=" + encodeURIComponent(repBuscar));
    if (repFiltroCategoria) qs.push("categoria=" + encodeURIComponent(repFiltroCategoria));
    api("/api/repuestos" + (qs.length ? "?" + qs.join("&") : "")).then(reps => {
      if ($("#rep-resultados")) $("#rep-resultados").innerHTML = renderListaRepuestos(reps);
    });
  }
}

async function borrarMovimiento(mid, rid) {
  if (!confirm("¿Borrar este movimiento? El stock se recalcula.")) return;
  const r = await api(`/api/repuestos/movimientos/${mid}`, { method: "DELETE" });
  if (r.ok) { toast("Movimiento borrado"); refrescarTrasMovimiento(rid); }
  else toast(r.msg, "error");
}

async function borrarRepuesto(id, cod) {
  if (!confirm(`¿Dar de baja ${cod}? Se conserva el historial pero deja de aparecer.`)) return;
  const r = await api(`/api/repuestos/${id}`, { method: "DELETE" });
  if (r.ok) { toast("Repuesto dado de baja"); cerrarRepuesto(); renderRepuestos(); }
  else toast(r.msg, "error");
}

// Editar: reusa el modal de carga pero precargado
async function editarRepuesto(id) {
  const r = await api(`/api/repuestos/${id}`);
  if (!r || r.error) return;
  const o = document.createElement("div");
  o.className = "rep-modal-overlay visible";
  o.style.zIndex = "1600";
  o.innerHTML = `
    <div class="rep-mini-modal" style="max-width:560px">
      <div class="rep-mini-titulo">Editar repuesto</div>
      <div class="form-row">
        <div class="field"><label>Código *</label><input id="e-cod" value="${(r.codigo||'').replace(/"/g,'&quot;')}" style="width:150px"></div>
        <div class="field" style="flex:1;min-width:180px"><label>Descripción *</label><input id="e-desc" value="${(r.descripcion||'').replace(/"/g,'&quot;')}"></div>
      </div>
      <div class="form-row" style="margin-top:12px">
        <div class="field"><label>Categoría</label><select id="e-cat">${CAT_REPUESTOS.map(c => `<option value="${c}" ${r.categoria===c?"selected":""}>${c}</option>`).join("")}</select></div>
        <div class="field"><label>Marca</label><input id="e-mar" value="${(r.marca||'').replace(/"/g,'&quot;')}" style="width:120px"></div>
        <div class="field"><label>Aplicación</label><input id="e-apl" value="${(r.aplicacion||'').replace(/"/g,'&quot;')}" style="width:150px"></div>
      </div>
      <div class="rep-ubic-form" style="margin-top:12px">
        <div class="rep-ubic-form-label"><i class="ti ti-map-pin"></i> Ubicación</div>
        <div class="rep-ubic-inputs">
          <div class="field"><label>Pasillo</label><input id="e-up" value="${r.ubic_pasillo||''}" maxlength="2" style="width:60px;text-align:center;text-transform:uppercase;font-size:17px;font-weight:600"></div>
          <span class="rep-ubic-sep">-</span>
          <div class="field"><label>Estante</label><input id="e-ue" value="${r.ubic_estanteria||''}" maxlength="3" style="width:60px;text-align:center;font-size:17px;font-weight:600"></div>
          <span class="rep-ubic-sep">-</span>
          <div class="field"><label>Nivel</label><input id="e-un" value="${r.ubic_nivel||''}" maxlength="3" style="width:60px;text-align:center;font-size:17px;font-weight:600"></div>
          <span class="rep-ubic-sep">-</span>
          <div class="field"><label>Posición</label><input id="e-uo" value="${r.ubic_posicion||''}" maxlength="3" style="width:60px;text-align:center;font-size:17px;font-weight:600"></div>
        </div>
      </div>
      <div class="form-row" style="margin-top:12px">
        <div class="field"><label>Avisar bajo de</label><input id="e-min" value="${r.stock_minimo||0}" style="width:120px"></div>
        <div class="field"><label>Precio c/u (Gs.)</label><input id="e-cos" value="${r.costo_unitario||0}" style="width:140px"></div>
      </div>
      <div class="rep-mini-btns">
        <button class="btn btn-ghost" onclick="this.closest('.rep-modal-overlay').remove()">Cancelar</button>
        <button class="btn btn-primary" onclick="confirmarEditar(${id}, this)"><i class="ti ti-device-floppy"></i> Guardar cambios</button>
      </div>
    </div>`;
  o.onclick = (e) => { if (e.target === o) o.remove(); };
  document.body.appendChild(o);
}

async function confirmarEditar(id, btn) {
  const limpiar = s => (s || "0").replace(/\./g, "").replace(/,/g, ".");
  const cod = $("#e-cod").value.trim();
  const desc = $("#e-desc").value.trim();
  if (!cod || !desc) { toast("Código y descripción son obligatorios", "error"); return; }
  const r = await api(`/api/repuestos/${id}`, {
    method: "PATCH", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      codigo: cod, descripcion: desc, categoria: $("#e-cat").value,
      marca: $("#e-mar").value, aplicacion: $("#e-apl").value,
      ubic_pasillo: $("#e-up").value, ubic_estanteria: $("#e-ue").value,
      ubic_nivel: $("#e-un").value, ubic_posicion: $("#e-uo").value,
      stock_minimo: parseFloat(limpiar($("#e-min").value)) || 0,
      costo_unitario: parseFloat(limpiar($("#e-cos").value)) || 0,
    })
  });
  if (r.ok) {
    toast("Cambios guardados", "success");
    btn.closest(".rep-modal-overlay").remove();
    refrescarTrasMovimiento(id);
  } else toast(r.msg, "error");
}


// ════════════════════════════════════════════════════════════════════════
//  DOSSIER POR COCHE (dentro del Reporte Gerencial)
// ════════════════════════════════════════════════════════════════════════

let dossierVehiculoId = null;

// Cambia entre la pestaña "Flota" y "Por coche"
function gerencialTab(tab) {
  document.querySelectorAll(".ger-tab").forEach(t => t.classList.toggle("on", t.dataset.tab === tab));
  document.querySelectorAll(".ger-panel").forEach(p => p.style.display = p.dataset.panel === tab ? "" : "none");
  if (tab === "coche" && !$("#dossier-vehiculos-cargados")) {
    cargarSelectorDossier();
  }
}

async function cargarSelectorDossier() {
  const sel = $("#dossier-coche-sel");
  if (!sel) return;
  const vehiculos = await api("/api/vehiculos");
  sel.innerHTML = `<option value="">— Elegí un coche —</option>` +
    vehiculos.map(v => `<option value="${v.id}">${v.n_interno ? "#" + v.n_interno + " · " : ""}${v.patente} — ${v.marca} ${v.modelo}</option>`).join("");
  const marca = document.createElement("span");
  marca.id = "dossier-vehiculos-cargados";
  marca.style.display = "none";
  sel.parentElement.appendChild(marca);
}

async function generarDossier() {
  const vid = $("#dossier-coche-sel").value;
  const desde = $("#dossier-desde").value;
  const hasta = $("#dossier-hasta").value;
  if (!vid) { toast("Elegí un coche", "error"); return; }
  if (!desde || !hasta) { toast("Elegí ambas fechas", "error"); return; }
  dossierVehiculoId = vid;

  const cont = $("#dossier-resultado");
  cont.innerHTML = `<div class="dossier-loading"><div class="dossier-spinner"></div><p>Armando el dossier completo...</p></div>`;

  const d = await api(`/api/dossier/${vid}?desde=${desde}&hasta=${hasta}`);
  if (!d || d.error) { cont.innerHTML = `<div class="empty"><i class="ti ti-alert-circle"></i>${d?.error || "No se pudo generar"}</div>`; return; }

  cont.innerHTML = renderDossierCompleto(d);
}

function renderDossierCompleto(d) {
  const v = d.vehiculo;
  const o = d.oee;
  const m = d.metricas;
  const diag = d.diagnostico;

  // Color del OEE según valor
  const oeeColor = o.oee >= 75 ? "var(--success)" : o.oee >= 55 ? "#65A30D" : o.oee >= 35 ? "var(--warning)" : "var(--danger)";

  return `
    <div class="dossier" id="dossier-hoja">

      <!-- Encabezado del coche -->
      <div class="dossier-header">
        <div class="dossier-header-info">
          <div class="dossier-coche-num">${v.n_interno ? "#" + v.n_interno : v.patente}</div>
          <div>
            <div class="dossier-coche-nombre">${v.marca} ${v.modelo}</div>
            <div class="dossier-coche-pat">${v.patente}${v.anio ? " · " + v.anio : ""} · ${fmtNum(v.km_actual || 0)} km</div>
          </div>
        </div>
        <div class="dossier-periodo">
          <i class="ti ti-calendar"></i> ${d.periodo.desde} → ${d.periodo.hasta}
          <span>(${d.periodo.dias} días)</span>
        </div>
      </div>

      <!-- DIAGNÓSTICO (lo primero y más importante) -->
      <div class="dossier-diag dossier-diag-${diag.nivel}">
        <div class="dossier-diag-head">
          <i class="ti ti-${diagIcono(diag.nivel)}"></i>
          <div class="dossier-diag-resumen">${diag.resumen}</div>
        </div>

        ${diag.fortalezas.length ? `
          <div class="dossier-diag-block">
            <div class="dossier-diag-label dossier-label-ok"><i class="ti ti-thumb-up"></i> Lo que está funcionando</div>
            ${diag.fortalezas.map(f => `<div class="dossier-diag-item"><i class="ti ti-check"></i> ${f}</div>`).join("")}
          </div>
        ` : ""}

        ${diag.focos.length ? `
          <div class="dossier-diag-block">
            <div class="dossier-diag-label dossier-label-foco"><i class="ti ti-target"></i> Dónde enfocarse</div>
            ${diag.focos.map(fc => `
              <div class="dossier-foco">
                <div class="dossier-foco-area">${fc.area}</div>
                <div class="dossier-foco-porque">${fc.porque}</div>
                <div class="dossier-foco-sug"><i class="ti ti-bulb"></i> ${fc.sugerencia}</div>
              </div>
            `).join("")}
          </div>
        ` : ""}

        ${diag.faltantes && diag.faltantes.length ? `
          <div class="dossier-faltantes"><i class="ti ti-info-circle"></i> Para un diagnóstico más preciso, falta cargar: ${diag.faltantes.join(", ")}.</div>
        ` : ""}

        <div class="dossier-diag-cierre"><i class="ti ti-arrow-right"></i> ${diag.cierre}</div>
      </div>

      <!-- OEE visual -->
      <div class="dossier-oee">
        <div class="dossier-oee-main">
          <svg viewBox="0 0 120 120" class="dossier-oee-ring">
            <circle cx="60" cy="60" r="50" fill="none" stroke="var(--surface2)" stroke-width="12"/>
            <circle cx="60" cy="60" r="50" fill="none" stroke="${oeeColor}" stroke-width="12"
              stroke-dasharray="${2 * Math.PI * 50}" stroke-dashoffset="${2 * Math.PI * 50 * (1 - o.oee / 100)}"
              stroke-linecap="round" transform="rotate(-90 60 60)" class="dossier-oee-arc"/>
            <text x="60" y="56" text-anchor="middle" class="dossier-oee-num" fill="${oeeColor}">${o.oee || 0}%</text>
            <text x="60" y="74" text-anchor="middle" class="dossier-oee-lbl">OEE</text>
          </svg>
        </div>
        <div class="dossier-oee-factores">
          ${factorBar("Disponibilidad", o.disponibilidad, "días operativo vs. parado en taller")}
          ${factorBar("Rendimiento", o.rendimiento, "km recorridos vs. meta")}
          ${factorBar("Confiabilidad", o.calidad, "días sin fallas")}
        </div>
      </div>

      <!-- Métricas clave -->
      <div class="dossier-metricas">
        ${metricaCard("ti-road", "Km recorridos", fmtNum(m.km_recorridos), "")}
        ${metricaCard("ti-tool", "Correctivos", m.cant_correctivos, m.cant_correctivos > 0 ? `Gs. ${gsSmall(m.costo_correctivos)}` : "ninguno")}
        ${metricaCard("ti-clipboard-list", "Órdenes de trabajo", m.cant_ots, "")}
        ${metricaCard("ti-coin", "Costo por km", m.costo_por_km > 0 ? "Gs. " + fmtNum(m.costo_por_km) : "—", "")}
        ${metricaCard("ti-alert-triangle", "Km entre fallas", m.km_entre_fallas > 0 ? fmtNum(m.km_entre_fallas) : "—", "")}
        ${metricaCard("ti-parking", "Días parado", m.dias_fuera, m.dias_operativo + " operativo")}
      </div>

      <!-- Fallas por tipo -->
      ${d.fallas_ranking.length ? `
        <div class="dossier-seccion">
          <div class="dossier-seccion-titulo"><i class="ti ti-alert-octagon"></i> Fallas por tipo</div>
          <div class="dossier-fallas">
            ${d.fallas_ranking.map(f => `
              <div class="dossier-falla">
                <div class="dossier-falla-info">
                  <span class="dossier-falla-tipo">${f.tipo}</span>
                  <span class="dossier-falla-cant">${f.cantidad} ${f.cantidad === 1 ? "vez" : "veces"}</span>
                </div>
                <div class="dossier-falla-costo">Gs. ${gsSmall(f.costo)}</div>
              </div>
            `).join("")}
          </div>
        </div>
      ` : ""}

      <!-- Historial de correctivos -->
      ${d.correctivos.length ? `
        <div class="dossier-seccion">
          <div class="dossier-seccion-titulo"><i class="ti ti-tool"></i> Correctivos del período (${d.correctivos.length})</div>
          <div class="table-wrap">
            <table>
              <thead><tr><th>Fecha</th><th>Tipo</th><th>Descripción</th><th class="num">Km</th><th class="num">Costo</th></tr></thead>
              <tbody>
                ${d.correctivos.map(c => `
                  <tr>
                    <td style="font-size:12px">${c.fecha}</td>
                    <td><span class="badge">${c.tipo_falla || "—"}</span></td>
                    <td style="font-size:13px">${c.descripcion || "—"}</td>
                    <td class="num">${fmtNum(c.km)}</td>
                    <td class="num">${gsSmall(c.costo)}</td>
                  </tr>`).join("")}
              </tbody>
            </table>
          </div>
        </div>
      ` : ""}

      <!-- Neumáticos -->
      ${d.neumaticos_actuales.length || d.neumaticos_movimientos.length ? `
        <div class="dossier-seccion">
          <div class="dossier-seccion-titulo"><i class="ti ti-disc"></i> Neumáticos</div>
          ${d.neumaticos_actuales.length ? `
            <div class="dossier-sub">Instalados actualmente (${d.neumaticos_actuales.length})</div>
            <div class="dossier-neu-grid">
              ${d.neumaticos_actuales.map(n => `
                <div class="dossier-neu-item">
                  <span class="dossier-neu-pos">${n.posicion}</span>
                  <span class="dossier-neu-cod">${n.codigo}</span>
                  <span class="dossier-neu-km">${fmtNum(n.km_acumulados || 0)} km</span>
                </div>`).join("")}
            </div>
          ` : ""}
          ${d.neumaticos_movimientos.length ? `
            <div class="dossier-sub" style="margin-top:14px">Movimientos en el período (${d.neumaticos_movimientos.length})</div>
            <div class="table-wrap">
              <table>
                <thead><tr><th>Cubierta</th><th>Posición</th><th>Instalada</th><th>Retirada</th><th>Motivo</th></tr></thead>
                <tbody>
                  ${d.neumaticos_movimientos.map(n => `
                    <tr>
                      <td><b>${n.codigo}</b> <span style="color:var(--muted);font-size:11px">${n.marca || ""}</span></td>
                      <td><span class="badge">${n.posicion}</span></td>
                      <td style="font-size:12px">${n.fecha_instalacion || "—"}</td>
                      <td style="font-size:12px">${n.fecha_retiro || "—"}</td>
                      <td style="font-size:12px">${n.motivo_retiro || (n.fecha_retiro ? "—" : "instalada")}</td>
                    </tr>`).join("")}
                </tbody>
              </table>
            </div>
          ` : ""}
        </div>
      ` : ""}

      <!-- Acción de imprimir -->
      <div class="dossier-acciones">
        <button class="btn btn-ghost" onclick="window.print()"><i class="ti ti-printer"></i> Imprimir / Guardar PDF</button>
      </div>

    </div>`;
}

// Helpers visuales del dossier
function diagIcono(nivel) {
  return { excelente: "trophy", bueno: "thumb-up", atencion: "alert-triangle", critico: "urgent", sin_datos: "info-circle" }[nivel] || "info-circle";
}

function factorBar(nombre, valor, ayuda) {
  const col = valor >= 80 ? "var(--success)" : valor >= 50 ? "var(--warning)" : "var(--danger)";
  return `
    <div class="dossier-factor">
      <div class="dossier-factor-top">
        <span class="dossier-factor-nombre">${nombre}</span>
        <span class="dossier-factor-val" style="color:${col}">${valor || 0}%</span>
      </div>
      <div class="dossier-factor-bar"><div class="dossier-factor-fill" style="width:${Math.min(valor || 0, 100)}%;background:${col}"></div></div>
      <div class="dossier-factor-ayuda">${ayuda}</div>
    </div>`;
}

function metricaCard(icono, label, valor, sub) {
  return `
    <div class="dossier-metrica">
      <i class="ti ${icono}"></i>
      <div class="dossier-metrica-val">${valor}</div>
      <div class="dossier-metrica-lbl">${label}</div>
      ${sub ? `<div class="dossier-metrica-sub">${sub}</div>` : ""}
    </div>`;
}


// ════════════════════════════════════════════════════════════════════════
//  CARGA DE HISTORIAL RETROACTIVO (el papel al sistema)
// ════════════════════════════════════════════════════════════════════════

const TIPOS_HIST = [
  { v: "correctivo", l: "Correctivo / Avería", i: "alert-triangle" },
  { v: "preventivo", l: "Preventivo / Service", i: "shield-check" },
  { v: "neumaticos", l: "Neumáticos", i: "disc" },
  { v: "servicio", l: "Servicio / Viaje", i: "route" },
  { v: "otro", l: "Otro", i: "notes" },
];

let histCargaVehiculo = null;   // coche seleccionado (queda fijo entre cargas)
let histCargaSesion = [];       // eventos cargados en esta sesión (para deshacer)

async function renderHistorialCarga() {
  status("Carga de historial retroactivo");
  const vehiculos = await api("/api/vehiculos");

  content.innerHTML = `
    <div class="page-header">
      <h1><i class="ti ti-archive"></i> Cargar Historial</h1>
      <p>Pasá el historial en papel al sistema — todo lo cargado suma a los reportes y al dossier de cada coche</p>
    </div>
    <div class="section">

      <div class="card">
        <div class="card-body" style="padding-bottom:14px">
          <div class="form-row" style="align-items:flex-end">
            <div class="field" style="flex:1;min-width:260px">
              <label>Coche (queda fijo mientras cargás sus papeles)</label>
              <select id="hc-coche" onchange="hcSeleccionarCoche(this.value)">
                <option value="">— Elegí el coche —</option>
                ${vehiculos.map(v => `<option value="${v.id}" ${histCargaVehiculo == v.id ? "selected" : ""}>${v.n_interno ? "#" + v.n_interno + " · " : ""}${v.patente} — ${v.marca} ${v.modelo}</option>`).join("")}
              </select>
            </div>
          </div>
        </div>
      </div>

      <div id="hc-zona" style="${histCargaVehiculo ? "" : "display:none"}">

        <div class="card" style="border-left:3px solid var(--brand-blue)">
          <div class="card-head"><i class="ti ti-pencil-plus"></i> Nuevo evento del papel</div>
          <div class="card-body">
            <div class="form-row">
              <div class="field"><label>Fecha</label><input id="hc-fecha" type="date"></div>
              <div class="field"><label>Tipo</label>
                <select id="hc-tipo">${TIPOS_HIST.map(t => `<option value="${t.v}">${t.l}</option>`).join("")}</select>
              </div>
              <div class="field"><label>Categoría <span style="color:var(--light);font-weight:400">(opcional)</span></label>
                <input id="hc-cat" placeholder="Motor, Frenos, Aceite..." style="width:160px"></div>
            </div>
            <div class="form-row" style="margin-top:12px">
              <div class="field" style="flex:1;min-width:260px">
                <label>Descripción — qué se hizo *</label>
                <input id="hc-desc" placeholder="Lo que dice el papel, tal cual">
              </div>
            </div>
            <div class="form-row" style="margin-top:12px;align-items:flex-end">
              <div class="field"><label>Km <span style="color:var(--light);font-weight:400">(si figura)</span></label><input id="hc-km" placeholder="0" style="width:110px"></div>
              <div class="field"><label>Costo Gs. <span style="color:var(--light);font-weight:400">(si figura)</span></label><input id="hc-costo" placeholder="0" style="width:140px"></div>
              <div class="field"><label>Taller <span style="color:var(--light);font-weight:400">(si figura)</span></label><input id="hc-taller" placeholder="opcional" style="width:150px"></div>
              <button class="btn btn-primary" onclick="hcAgregar()" style="min-width:130px"><i class="ti ti-plus"></i> Agregar</button>
            </div>
            <p class="hint" style="margin-top:12px"><i class="ti ti-keyboard"></i> Tip: <b>Enter</b> en cualquier campo agrega el evento. La fecha se mantiene para el siguiente — solo ajustá el día si cambia.</p>
          </div>
        </div>

        <div class="section-title" style="display:flex;align-items:center;gap:8px">
          <i class="ti ti-list-check"></i> <span id="hc-lista-titulo">Historial cargado</span>
        </div>
        <div id="hc-lista"></div>

      </div>
    </div>`;

  // Enter agrega desde cualquier campo del formulario
  ["hc-fecha", "hc-tipo", "hc-cat", "hc-desc", "hc-km", "hc-costo", "hc-taller"].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.addEventListener("keydown", e => { if (e.key === "Enter") { e.preventDefault(); hcAgregar(); } });
  });

  if (histCargaVehiculo) {
    // fecha por defecto: la última usada, o hoy
    const f = document.getElementById("hc-fecha");
    if (f && !f.value) f.value = window._hcUltimaFecha || hoy();
    hcCargarLista();
  }
}

function hcSeleccionarCoche(vid) {
  histCargaVehiculo = vid || null;
  histCargaSesion = [];
  renderHistorialCarga();
}

async function hcAgregar() {
  if (!histCargaVehiculo) { toast("Elegí un coche primero", "error"); return; }
  const fecha = $("#hc-fecha").value;
  const desc = $("#hc-desc").value.trim();
  if (!fecha) { toast("Falta la fecha", "error"); return; }
  if (!desc) { toast("Falta la descripción", "error"); $("#hc-desc").focus(); return; }
  const limpiar = s => (s || "0").replace(/\./g, "").replace(/,/g, ".");

  const r = await api("/api/historial_carga", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      vehiculo_id: histCargaVehiculo, fecha,
      tipo: $("#hc-tipo").value, categoria: $("#hc-cat").value,
      descripcion: desc,
      km: parseFloat(limpiar($("#hc-km").value)) || 0,
      costo: parseFloat(limpiar($("#hc-costo").value)) || 0,
      taller: $("#hc-taller").value,
    })
  });
  if (!r.ok) { toast(r.msg || "Error", "error"); return; }

  histCargaSesion.push(r.id);
  window._hcUltimaFecha = fecha;   // recordar la fecha para el próximo
  toast("Evento guardado", "success");

  // Limpiar solo lo que cambia entre eventos; fecha, tipo y categoría quedan
  $("#hc-desc").value = ""; $("#hc-km").value = "";
  $("#hc-costo").value = ""; $("#hc-taller").value = "";
  $("#hc-desc").focus();
  hcCargarLista();
}

async function hcCargarLista() {
  const cont = $("#hc-lista");
  if (!cont || !histCargaVehiculo) return;
  const eventos = await api(`/api/historial_carga/${histCargaVehiculo}`);
  $("#hc-lista-titulo").textContent = `Historial cargado (${eventos.length})`;

  if (!eventos.length) {
    cont.innerHTML = `<div class="empty"><i class="ti ti-archive-off"></i>Todavía no hay historial cargado para este coche.<br>Arrancá con el papel más viejo.</div>`;
    return;
  }
  const iconoDe = t => (TIPOS_HIST.find(x => x.v === t) || TIPOS_HIST[4]).i;
  const labelDe = t => (TIPOS_HIST.find(x => x.v === t) || TIPOS_HIST[4]).l;
  cont.innerHTML = `
    <div class="table-wrap">
      <table>
        <thead><tr><th>Fecha</th><th>Tipo</th><th>Descripción</th><th class="num">Km</th><th class="num">Costo</th><th>Taller</th><th class="td-action"></th></tr></thead>
        <tbody>
          ${eventos.map(e => `
            <tr class="${histCargaSesion.includes(e.id) && e.origen === 'historial_eventos' ? 'hc-nuevo' : ''}">
              <td style="font-size:12.5px;white-space:nowrap">${e.fecha}</td>
              <td><span class="badge"><i class="ti ti-${iconoDe(e.tipo)}" style="font-size:11px"></i> ${labelDe(e.tipo)}</span>${e.categoria ? `<br><span style="font-size:11px;color:var(--muted)">${e.categoria}</span>` : ""}</td>
              <td style="font-size:13px">${e.descripcion}</td>
              <td class="num" style="font-size:12.5px">${e.km ? fmtNum(e.km) : "—"}</td>
              <td class="num" style="font-size:12.5px">${e.costo ? gsSmall(e.costo) : "—"}</td>
              <td style="font-size:12px;color:var(--muted)">${e.taller || "—"}</td>
              <td class="td-action">
                <button class="icon-btn" title="Borrar (cargado por error)" onclick="hcBorrar('${e.origen}', ${e.id})"><i class="ti ti-trash"></i></button>
              </td>
            </tr>`).join("")}
        </tbody>
      </table>
    </div>`;
}

async function hcBorrar(origen, id) {
  if (!confirm("¿Borrar este evento del historial?")) return;
  const r = await api(`/api/historial_carga/${origen}/${id}`, { method: "DELETE" });
  if (r.ok) { toast("Evento borrado"); hcCargarLista(); }
  else toast(r.msg || "Error", "error");
}


// ════════════════════════════════════════════════════════════════════════
//  STAND-BY PRESUPUESTARIO — firma de tesorería y cola de espera
// ════════════════════════════════════════════════════════════════════════
// El dinero se aprueba por ítem, no por orden. Tesorería marca lo que cubre;
// lo que no, queda en una cola visible en vez de perderse.

async function abrirFirma(otId) {
  const todas = await api("/api/compras/ots");
  const o = todas.find(x => x.id === otId);
  if (!o) { toast("No encontré la orden", "error"); return; }

  const overlay = document.createElement("div");
  overlay.className = "modal-overlay firma-overlay";
  overlay.innerHTML = `
    <div class="firma-modal">
      <div class="firma-head">
        <div>
          <h2><i class="ti ti-writing-sign"></i> Firma de Tesorería — OT #${o.id}</h2>
          <p>Marcá lo que Tesorería puede cubrir ahora. Lo que dejes sin marcar queda esperando fondos, y el trabajo avanza igual con lo habilitado.</p>
        </div>
        <button class="firma-x" onclick="this.closest('.modal-overlay').remove()"><i class="ti ti-x"></i></button>
      </div>

      <div class="firma-items">
        ${o.items.map(it => `
          <label class="firma-item">
            <input type="checkbox" class="firma-check" data-id="${it.id}" data-precio="${it.precio_compras || 0}"
                   ${it.estado_pago !== "espera" ? "checked" : ""} onchange="firmaRecalcular()">
            <span class="firma-item-info">
              <span class="firma-item-desc">${it.descripcion}</span>
              <span class="firma-item-mat">${it.material_pedido || "—"}</span>
            </span>
            <span class="firma-item-precio">${gs(it.precio_compras || 0)}</span>
          </label>`).join("")}
      </div>

      <div class="firma-totales">
        <div class="firma-total-row">
          <span><i class="ti ti-circle-check" style="color:var(--success)"></i> Se habilita ahora</span>
          <b id="firma-total-hab">—</b>
        </div>
        <div class="firma-total-row">
          <span><i class="ti ti-hourglass" style="color:var(--warning)"></i> Queda esperando fondos</span>
          <b id="firma-total-esp">—</b>
        </div>
      </div>

      <div class="firma-acciones">
        <button class="btn btn-ghost" onclick="firmaMarcarTodo(true)">Marcar todo</button>
        <button class="btn btn-ghost" onclick="firmaMarcarTodo(false)">Desmarcar todo</button>
        <span style="flex:1"></span>
        <button class="btn btn-ghost" onclick="this.closest('.modal-overlay').remove()">Cancelar</button>
        <button class="btn btn-primary" onclick="confirmarFirma(${o.id}, this)"><i class="ti ti-check"></i> Confirmar firma</button>
      </div>
    </div>`;
  overlay.onclick = e => { if (e.target === overlay) overlay.remove(); };
  document.body.appendChild(overlay);
  firmaRecalcular();
}

function firmaRecalcular() {
  let hab = 0, esp = 0;
  document.querySelectorAll(".firma-check").forEach(ch => {
    const p = parseFloat(ch.dataset.precio) || 0;
    if (ch.checked) hab += p; else esp += p;
    ch.closest(".firma-item").classList.toggle("sin-fondos", !ch.checked);
  });
  const h = document.getElementById("firma-total-hab");
  const e = document.getElementById("firma-total-esp");
  if (h) h.textContent = gs(hab);
  if (e) { e.textContent = gs(esp); e.style.color = esp > 0 ? "var(--warning)" : "var(--muted)"; }
}

function firmaMarcarTodo(v) {
  document.querySelectorAll(".firma-check").forEach(ch => ch.checked = v);
  firmaRecalcular();
}

async function confirmarFirma(otId, btn) {
  const habilitados = [...document.querySelectorAll(".firma-check:checked")].map(ch => +ch.dataset.id);
  const total = document.querySelectorAll(".firma-check").length;
  if (habilitados.length === 0 &&
      !confirm("No marcaste ningún ítem: la orden completa va a quedar esperando fondos. ¿Confirmás?")) return;
  btn.disabled = true;
  const r = await api(`/api/compras/${otId}/firmar`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ habilitados })
  });
  if (r.ok) {
    toast(r.msg, habilitados.length < total ? "warning" : "success");
    btn.closest(".modal-overlay").remove();
    renderCompras();
  } else { toast(r.msg || "Error", "error"); btn.disabled = false; }
}

// ─── Cola de espera de fondos ───

async function renderColaEspera() {
  const cont = document.getElementById("cola-espera-panel");
  if (!cont) return;
  const cola = await api("/api/compras/cola_espera");
  if (!cola.cantidad) {
    cont.innerHTML = `<div class="cola-vacia"><i class="ti ti-circle-check"></i> No hay ítems esperando fondos. Todo lo presupuestado está cubierto.</div>`;
    return;
  }
  cont.innerHTML = `
    <div class="cola-resumen">
      <div class="cola-stat">
        <div class="cola-stat-val">${cola.cantidad}</div>
        <div class="cola-stat-lbl">ítems esperando</div>
      </div>
      <div class="cola-stat">
        <div class="cola-stat-val">${gs(cola.total)}</div>
        <div class="cola-stat-lbl">demanda sin cubrir</div>
      </div>
      <div class="cola-stat">
        <div class="cola-stat-val">${cola.dias_espera_max}</div>
        <div class="cola-stat-lbl">días el más viejo</div>
      </div>
    </div>
    <div class="table-wrap">
      <table>
        <thead><tr>
          <th style="width:34px"><input type="checkbox" onchange="colaMarcarTodo(this.checked)"></th>
          <th>Esperando desde</th><th>Coche</th><th>Trabajo</th><th>Material</th><th class="num">Monto</th>
        </tr></thead>
        <tbody>
          ${cola.items.map(i => `<tr>
            <td><input type="checkbox" class="cola-check" data-id="${i.id}" data-precio="${i.precio_compras || 0}" onchange="colaRecalcular()"></td>
            <td style="font-size:12.5px;white-space:nowrap">${(i.fecha_espera || "").slice(0,10)}</td>
            <td><b>${i.n_interno ? "#" + i.n_interno : i.patente}</b><br><span style="font-size:11px;color:var(--muted)">OT #${i.ot_id}</span></td>
            <td style="font-size:13px">${i.descripcion}</td>
            <td style="font-size:12.5px;color:var(--muted)">${i.material_pedido || "—"}</td>
            <td class="num">${gs(i.precio_compras || 0)}</td>
          </tr>`).join("")}
        </tbody>
      </table>
    </div>
    <div class="cola-acciones">
      <span id="cola-seleccion" class="cola-seleccion">Ninguno seleccionado</span>
      <button class="btn btn-success" id="cola-liberar-btn" onclick="liberarSeleccionados(this)" disabled>
        <i class="ti ti-lock-open"></i> Liberar seleccionados
      </button>
    </div>`;
}

function colaMarcarTodo(v) {
  document.querySelectorAll(".cola-check").forEach(ch => ch.checked = v);
  colaRecalcular();
}

function colaRecalcular() {
  const sel = [...document.querySelectorAll(".cola-check:checked")];
  const total = sel.reduce((s, ch) => s + (parseFloat(ch.dataset.precio) || 0), 0);
  const lbl = document.getElementById("cola-seleccion");
  const btn = document.getElementById("cola-liberar-btn");
  if (lbl) lbl.textContent = sel.length
    ? `${sel.length} ítem(s) seleccionado(s) — ${gs(total)}`
    : "Ninguno seleccionado";
  if (btn) btn.disabled = sel.length === 0;
}

async function liberarSeleccionados(btn) {
  const ids = [...document.querySelectorAll(".cola-check:checked")].map(ch => +ch.dataset.id);
  if (!ids.length) return;
  btn.disabled = true;
  const r = await api("/api/compras/liberar", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items: ids })
  });
  if (r.ok) { toast(r.msg, "success"); renderCompras(); }
  else { toast(r.msg || "Error", "error"); btn.disabled = false; }
}

