// Añade la fecha exacta a cada pedido de OT sin alterar el render original.
(function () {
  const renderOriginal = window.pdFila;
  if (typeof renderOriginal !== "function") return;

  window.pdFila = function (pedido) {
    const html = renderOriginal(pedido);
    const fecha = pedido.fecha
      ? `${pedido.fecha.slice(8, 10)}/${pedido.fecha.slice(5, 7)}/${pedido.fecha.slice(0, 4)}`
      : "Sin fecha";
    const relativo = `<span><i class="ti ti-clock"></i> ${window.pdCuando(pedido)}</span>`;
    const exacta = `<span title="Fecha del pedido"><i class="ti ti-calendar"></i> ${fecha}</span>`;
    return html.replace(relativo, `${relativo}\n          ${exacta}`);
  };
})();
