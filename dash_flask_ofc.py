function calcularCMV() {
  const ini = document.getElementById('cmvDataInicial').value;
  const fim = document.getElementById('cmvDataFinal').value;
  const estIniRM = document.getElementById('cmvEstIniRM').value || 0;
  const estIniGP = document.getElementById('cmvEstIniGP').value || 0;
  const estFinRM = document.getElementById('cmvEstFinRM').value || 0;
  const estFinGP = document.getElementById('cmvEstFinGP').value || 0;
  if (!ini || !fim) { alert('Selecione as duas datas'); return; }
  if (!estIniRM && !estIniGP && !estFinRM && !estFinGP) { alert('Informe ao menos um valor de estoque'); return; }
  document.getElementById('cmvResultado').innerHTML = '<div class="kpi-card" style="text-align:center;padding:40px;"><div style="width:40px;height:40px;border:4px solid #dbeafe;border-top-color:#2563eb;border-radius:50%;margin:0 auto 16px;animation:spin 1s linear infinite;"></div><p style="color:#64748b;">Buscando compras do periodo...</p></div><style>@keyframes spin{to{transform:rotate(360deg);}}</style>';
  buscarCMV(ini, fim, estIniRM, estIniGP, estFinRM, estFinGP);
}
function buscarCMV(ini, fim, estIniRM, estIniGP, estFinRM, estFinGP) {
  const url = '/cmv?data_inicial=' + ini + '&data_final=' + fim + '&est_ini_rm=' + estIniRM + '&est_ini_gp=' + estIniGP + '&est_fin_rm=' + estFinRM + '&est_fin_gp=' + estFinGP;
  fetch(url)
    .then(r => r.json())
    .then(data => {
      if (data.status === 'calculando' || data.status === 'iniciando') { setTimeout(() => buscarCMV(ini, fim, estIniRM, estIniGP, estFinRM, estFinGP), 5000); }
      else if (data.status === 'erro') { document.getElementById('cmvResultado').innerHTML = '<div class="kpi-card red"><div class="kpi-label">Erro</div><div class="kpi-value" style="font-size:16px;">' + data.erro + '</div></div>'; }
      else { renderCMV(data); }
    })
    .catch(() => { setTimeout(() => buscarCMV(ini, fim, estIniRM, estIniGP, estFinRM, estFinGP), 5000); });
}
function renderCMV(d) {
  const fmt = v => 'R$ ' + Number(v).toLocaleString('pt-BR', {minimumFractionDigits:2, maximumFractionDigits:2});
  document.getElementById('cmvResultado').innerHTML =
    '<div class="table-card"><div class="chart-title">CMV de ' + d.data_inicial.split('-').reverse().join('/') + ' a ' + d.data_final.split('-').reverse().join('/') + '</div>' +
    '<table><thead><tr><th>Componente</th><th>REAL MAIS</th><th>GP DISTRIBUIDORA</th><th>Total</th></tr></thead><tbody>' +
    '<tr><td class="vendedor-name">(+) Estoque Inicial</td><td class="valor-cell">' + fmt(d.estoque_inicial_rm) + '</td><td class="valor-cell">' + fmt(d.estoque_inicial_gp) + '</td><td class="valor-cell" style="font-size:16px;">' + fmt(d.estoque_inicial_total) + '</td></tr>' +
    '<tr><td class="vendedor-name">(+) Compras no Periodo (automatico)</td><td class="valor-cell">' + fmt(d.compras_rm) + '</td><td class="valor-cell">' + fmt(d.compras_gp) + '</td><td class="valor-cell" style="font-size:16px;">' + fmt(d.compras_total) + '</td></tr>' +
    '<tr><td class="vendedor-name">(-) Estoque Final</td><td>' + fmt(d.estoque_final_rm) + '</td><td>' + fmt(d.estoque_final_gp) + '</td><td style="font-size:16px;">' + fmt(d.estoque_final_total) + '</td></tr>' +
    '<tr style="border-top:3px solid #2563eb;"><td class="vendedor-name" style="font-size:16px;">= CMV Total</td><td></td><td></td><td class="valor-cell" style="font-size:20px;color:#dc2626;">' + fmt(d.cmv) + '</td></tr>' +
    '</tbody></table></div>';
}
