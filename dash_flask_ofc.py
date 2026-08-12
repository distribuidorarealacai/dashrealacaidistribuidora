#!/usr/bin/env python3
"""
vhsys_dashboard_web.py  (v2 — background fetch + loading page)
"""
import os, sys, json, csv, io, re, time, threading
from datetime import datetime, date, timedelta
from pathlib import Path
from calendar import monthrange
import requests
from flask import Flask

app = Flask(__name__)

EMPRESAS = [
    {
        "nome": "REAL MAIS",
        "access_token": "YYeHeFaNAfVfLegOLXedMFZMLNPLQT",
        "secret_token": "k9Qhe0oaSAchTjWgpvLeUvxmZcyLVfO",
        "endpoint": "/pedidos/",
        "data_field": "data_pedido",
        "order_field": "data_pedido",
    },
    {
        "nome": "GP DISTRIBUIDORA",
        "access_token": "EdPfRWCOGgefDeVcSNNaGJLJeZDMST",
        "secret_token": "5P4nmO1ONthN5oqfX81lHKX5i0YC3dm",
        "endpoint": "/vendas-balcao/",
        "data_field": "data_cad_pedido",
        "order_field": "data_cad_pedido",
    },
]

BASE_URL = "https://api.vhsys.com/v2"
STATUS_EXCLUIDOS = {"Cancelado"}
SPREADSHEET_ID = "10rPC_-MxKm6o0L1SjHanXuKm0LjEIezjhoclNPlzpfc"

METAS_MENSAIS = {
    "Simone Moura":      215000.00,
    "Isa":               241500.00,
    "Ana Ruth":           65000.00,
    "GP DISTRIBUIDORA":  100000.00,
}
META_CONSOLIDADA = 1005277.76

CORES = ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899',
         '#14b8a6','#f97316','#6366f1','#84cc16','#06b6d4','#a855f7']

# ── CACHE + ESTADO DE LOADING ──────────────────────────────────────────────
CACHE_TEMPO_SEGUNDOS = 300
_cache_lock = threading.Lock()
_cache = {"timestamp": 0, "html": "", "erro": "", "buscando": False}

def make_headers(empresa):
    return {
        "access-token": empresa["access_token"],
        "secret-access-token": empresa["secret_token"],
        "Cache-Control": "no-cache",
        "User-Agent": "MinhaAplicacao/1.0",
        "Content-Type": "application/json",
    }

def normalizar_data(valor_bruto):
    if not valor_bruto:
        return ""
    s = str(valor_bruto).strip()
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r'^(\d{1,2})[/-](\d{1,2})[/-](\d{4})', s)
    if m:
        return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    m = re.match(r'^(\d{1,2})[/-](\d{1,2})[/-](\d{2})', s)
    if m:
        return f"20{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    return ""

def normalizar_nome_vendedor(nome):
    if not nome:
        return "Sem vendedor"
    s = str(nome)
    s = s.replace('\xa0', ' ').replace('\t', ' ').replace('\n', ' ').replace('\r', ' ')
    s = ' '.join(s.split())
    return s if s else "Sem vendedor"

def ler_dados_entregas():
    urls_export = [
        f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid=0",
        f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv",
        f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/gviz/tq?tqx=out:csv",
        f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid=0&usp=sharing",
    ]
    content = None
    for url in urls_export:
        try:
            resp = requests.get(url, timeout=30, allow_redirects=True)
            texto = resp.text[:500].strip()
            if '<html' in texto.lower() or '<!doctype' in texto.lower():
                continue
            if resp.status_code == 200 and len(resp.content) > 50:
                content = resp.content.decode('utf-8')
                break
        except:
            continue
    if content is None:
        return []
    entregas = []
    try:
        reader = csv.reader(io.StringIO(content))
        data_atual = ""
        for row in reader:
            if not row or all(c.strip() == "" for c in row):
                continue
            primeira_coluna = row[0].strip() if row[0] else ""
            if "PLANILHA DE ENTREGAS" in primeira_coluna.upper():
                match = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', primeira_coluna)
                if match:
                    data_atual = f"{match.group(3)}-{match.group(2).zfill(2)}-{match.group(1).zfill(2)}"
                else:
                    data_atual = ""
                continue
            if primeira_coluna.upper() == "CLIENTES":
                continue
            if data_atual and len(row) >= 3:
                entregador = row[2].strip().upper() if row[2] else ""
                if entregador in ("RETIRADA", "RETRADA", "RETITADA"):
                    entregador = "RETIRADA"
                if entregador:
                    entregas.append({
                        "data": data_atual, "entregador": entregador,
                        "cliente": row[0].strip() if row[0] else "",
                        "nota": row[1].strip() if row[1] else "",
                        "veiculo": row[6].strip() if len(row) > 6 and row[6] else "",
                    })
    except:
        return []
    return entregas

def listar_pedidos_periodo(data_inicio, data_fim, empresa, headers):
    endpoint = empresa["endpoint"]
    data_field = empresa["data_field"]
    order_field = empresa["order_field"]
    todos = []
    offset = 0
    limit = 250
    pagina = 1
    max_paginas = 200
    while pagina <= max_paginas:
        params = {"limit": limit, "offset": offset, "order": order_field, "sort": "Desc"}
        try:
            resp = requests.get(f"{BASE_URL}{endpoint}", headers=headers, params=params, timeout=30)
        except:
            break
        if resp.status_code == 403:
            break
        if resp.status_code != 200:
            break
        try:
            payload = resp.json()
        except:
            break
        lote = payload.get("data", [])
        if isinstance(lote, dict):
            lote = [lote]
        if not lote or not isinstance(lote, list):
            break
        todos.extend(lote)
        pedidos_antes = 0
        for p in lote:
            if not isinstance(p, dict):
                continue
            dp = normalizar_data(p.get(data_field, ""))
            if dp and dp != "0000-00-00" and dp < data_inicio:
                pedidos_antes += 1
        if pedidos_antes > 0:
            break
        offset += limit
        pagina += 1
    filtrados = []
    for p in todos:
        if not isinstance(p, dict):
            continue
        dp = normalizar_data(p.get(data_field, ""))
        if dp and dp != "0000-00-00" and data_inicio <= dp <= data_fim:
            p[data_field] = dp
            filtrados.append(p)
    return filtrados

def processar_pedidos(pedidos, empresa):
    empresa_nome = empresa["nome"]
    data_field = empresa["data_field"]
    processados = []
    for p in pedidos:
        if not isinstance(p, dict):
            continue
        status = p.get("status_pedido", "")
        if status in STATUS_EXCLUIDOS:
            continue
        valor_str = p.get("valor_total_nota", "0") or "0"
        try:
            valor = float(valor_str)
        except:
            valor = 0.0
        if empresa_nome == "GP DISTRIBUIDORA":
            vendedor = "GP DISTRIBUIDORA"
        else:
            vendedor = normalizar_nome_vendedor(p.get("vendedor_pedido", ""))
        data_ped = normalizar_data(p.get(data_field, ""))
        id_pedido = str(p.get("id_ped", p.get("id_frente", p.get("id_pedido", ""))))
        processados.append({
            "id": id_pedido, "data": data_ped, "vendedor": vendedor,
            "empresa": empresa_nome, "valor": round(valor, 2),
            "status": status, "cliente": p.get("nome_cliente", ""),
        })
    return processados

def gerar_dashboard_html(pedidos, entregas):
    dados_json = json.dumps(pedidos, ensure_ascii=False)
    entregas_json = json.dumps(entregas, ensure_ascii=False)
    metas_json = json.dumps(METAS_MENSAIS, ensure_ascii=False)
    data_geracao = datetime.now().strftime("%d/%m/%Y as %H:%M:%S")
    if pedidos:
        datas = sorted([p["data"] for p in pedidos if p["data"]])
        min_data = datas[0] if datas else date.today().isoformat()
        max_data = datas[-1] if datas else date.today().isoformat()
    else:
        min_data = date.today().replace(day=1).isoformat()
        max_data = date.today().isoformat()
    html = r'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dashboard de Faturamento & Entregas</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
:root{--bg:#f0f2f5;--card-bg:#fff;--primary:#2563eb;--primary-light:#dbeafe;--green:#16a34a;--green-light:#dcfce7;--amber:#f59e0b;--amber-light:#fef3c7;--red:#dc2626;--red-light:#fee2e2;--text:#1e293b;--text-muted:#64748b;--border:#e2e8f0;--shadow:0 1px 3px rgba(0,0,0,.1),0 1px 2px rgba(0,0,0,.06);--shadow-lg:0 4px 6px rgba(0,0,0,.07),0 2px 4px rgba(0,0,0,.06);--radius:12px;}
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;}
.header{background:linear-gradient(135deg,#1e3a5f 0%,#2563eb 100%);color:#fff;padding:24px 32px;}
.header h1{font-size:24px;font-weight:700;}
.header .subtitle{font-size:13px;opacity:.85;margin-top:4px;}
.header .updated{font-size:12px;opacity:.7;margin-top:8px;}
.container{max-width:1400px;margin:0 auto;padding:24px;}
.filter-bar{background:var(--card-bg);border-radius:var(--radius);box-shadow:var(--shadow);padding:20px 24px;margin-bottom:24px;display:flex;align-items:center;gap:16px;flex-wrap:wrap;}
.filter-group{display:flex;align-items:center;gap:8px;}
.filter-group label{font-size:13px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;}
.filter-group input[type="date"]{padding:8px 12px;border:2px solid var(--border);border-radius:8px;font-size:14px;color:var(--text);outline:none;transition:border-color .2s;}
.filter-group input[type="date"]:focus{border-color:var(--primary);}
.btn-apply{background:var(--primary);color:#fff;border:none;padding:9px 24px;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;transition:background .2s;}
.btn-apply:hover{background:#1d4ed8;}
.btn-preset{background:var(--primary-light);color:var(--primary);border:none;padding:7px 14px;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer;transition:all .2s;}
.btn-preset:hover{background:var(--primary);color:#fff;}
.empresa-filter{display:flex;gap:8px;align-items:center;flex-wrap:wrap;}
.empresa-label{font-size:13px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin-right:4px;}
.btn-empresa{background:var(--primary-light);color:var(--primary);border:none;padding:8px 16px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;transition:all .2s;}
.btn-empresa:hover{background:var(--primary);color:#fff;}
.btn-empresa.active{background:var(--primary);color:#fff;}
.section-title{font-size:20px;font-weight:700;margin:32px 0 16px;color:var(--text);display:flex;align-items:center;gap:8px;padding-bottom:8px;border-bottom:2px solid var(--border);}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:24px;}
.kpi-card{background:var(--card-bg);border-radius:var(--radius);box-shadow:var(--shadow);padding:20px 24px;border-left:4px solid var(--primary);transition:box-shadow .2s;}
.kpi-card:hover{box-shadow:var(--shadow-lg);}
.kpi-card.green{border-left-color:var(--green);}
.kpi-card.amber{border-left-color:var(--amber);}
.kpi-card.red{border-left-color:var(--red);}
.kpi-card.purple{border-left-color:#8b5cf6;}
.kpi-card.teal{border-left-color:#14b8a6;}
.kpi-label{font-size:12px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px;}
.kpi-value{font-size:26px;font-weight:700;color:var(--text);}
.kpi-sub{font-size:12px;color:var(--text-muted);margin-top:4px;}
.meta-section-title{font-size:18px;font-weight:700;margin-bottom:16px;color:var(--text);display:flex;align-items:center;gap:8px;}
.meta-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px;margin-bottom:24px;}
.meta-card{background:var(--card-bg);border-radius:var(--radius);box-shadow:var(--shadow);padding:20px 22px;transition:box-shadow .2s;}
.meta-card:hover{box-shadow:var(--shadow-lg);}
.meta-card.consolidado{grid-column:1/-1;background:linear-gradient(135deg,#1e3a5f 0%,#2563eb 100%);color:#fff;}
.meta-card.consolidado .meta-name{color:#fff;}
.meta-card.consolidado .meta-sub{color:rgba(255,255,255,0.8);}
.meta-card.consolidado .meta-progress-bar{background:rgba(255,255,255,0.2);}
.meta-card.consolidado .meta-valor{color:#fff;}
.meta-card.consolidado .meta-falta{color:rgba(255,255,255,0.8);}
.meta-header{display:flex;align-items:center;gap:12px;margin-bottom:14px;}
.meta-avatar{width:42px;height:42px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:700;color:#fff;flex-shrink:0;}
.meta-name{font-size:15px;font-weight:700;color:var(--text);}
.meta-sub{font-size:12px;color:var(--text-muted);margin-top:2px;}
.meta-progress-bar{background:var(--border);border-radius:12px;height:28px;overflow:hidden;position:relative;margin-bottom:10px;}
.meta-progress-fill{height:100%;border-radius:12px;display:flex;align-items:center;padding-left:12px;color:#fff;font-size:12px;font-weight:700;transition:width .5s ease;min-width:0;}
.meta-stats{display:flex;justify-content:space-between;align-items:center;font-size:13px;}
.meta-valor{font-weight:700;font-size:16px;}
.meta-valor.atingido{color:var(--green);}
.meta-valor.abaixo{color:var(--text);}
.meta-status{padding:4px 10px;border-radius:6px;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.5px;}
.status-bateu{background:var(--green-light);color:var(--green);}
.status-perto{background:var(--amber-light);color:var(--amber);}
.status-longe{background:var(--red-light);color:var(--red);}
.status-semmeta{background:#f1f5f9;color:var(--text-muted);}
.meta-falta{font-size:12px;color:var(--text-muted);margin-top:6px;}
.charts-grid{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-bottom:24px;}
@media(max-width:900px){.charts-grid{grid-template-columns:1fr;}}
.chart-card{background:var(--card-bg);border-radius:var(--radius);box-shadow:var(--shadow);padding:20px 24px;}
.chart-card.full{grid-column:1/-1;}
.chart-title{font-size:16px;font-weight:700;margin-bottom:16px;}
.chart-wrapper{position:relative;height:320px;}
.table-card{background:var(--card-bg);border-radius:var(--radius);box-shadow:var(--shadow);padding:20px 24px;margin-bottom:24px;}
.table-card table{width:100%;border-collapse:collapse;}
.table-card th{text-align:left;padding:12px 14px;font-size:12px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;border-bottom:2px solid var(--border);}
.table-card td{padding:12px 14px;font-size:14px;border-bottom:1px solid var(--border);}
.table-card tr:hover td{background:#f8fafc;}
.table-card tr:last-child td{border-bottom:none;}
.vendedor-name{font-weight:600;}
.valor-cell{font-weight:600;color:var(--green);}
.pct-bar{background:var(--border);border-radius:6px;height:8px;width:80px;overflow:hidden;display:inline-block;vertical-align:middle;margin-right:8px;}
.pct-fill{height:100%;border-radius:6px;transition:width .3s;}
.no-data{text-align:center;padding:48px;color:var(--text-muted);font-size:16px;}
</style>
</head>
<body>
<div class="header">
<h1>Dashboard de Faturamento, Metas & Entregas</h1>
<div class="subtitle">REAL MAIS + GP DISTRIBUIDORA + Entregas - Vhsys API v2</div>
<div class="updated">Dados gerados em: __DATA_GERACAO__</div>
</div>
<div class="container">
<div class="filter-bar">
<div class="filter-group"><label>Data Inicial</label><input type="date" id="dataInicio" value="__MIN_DATA__"></div>
<div class="filter-group"><label>Data Final</label><input type="date" id="dataFim" value="__MAX_DATA__"></div>
<button class="btn-apply" onclick="aplicarFiltro()">Aplicar</button>
<div style="margin-left:auto;display:flex;gap:8px;flex-wrap:wrap;">
<button class="btn-preset" onclick="presetHoje()">Hoje</button>
<button class="btn-preset" onclick="preset7()">7 dias</button>
<button class="btn-preset" onclick="presetMesAtual()">Mes Atual</button>
<button class="btn-preset" onclick="presetTudo()">Tudo</button>
</div>
</div>
<div class="filter-bar" style="padding:14px 24px;">
<div class="empresa-filter">
<span class="empresa-label">Empresa:</span>
<button class="btn-empresa active" onclick="setEmpresa('todos', this)">Consolidado</button>
<button class="btn-empresa" onclick="setEmpresa('REAL MAIS', this)">REAL MAIS</button>
<button class="btn-empresa" onclick="setEmpresa('GP DISTRIBUIDORA', this)">GP Distribuidora</button>
</div>
</div>
<div class="kpi-grid" id="kpiGrid"></div>
<div id="metaSection"><div class="meta-section-title">Metas Mensais - <span id="mesMetaLabel"></span></div><div class="meta-grid" id="metaGrid"></div></div>
<div class="charts-grid">
<div class="chart-card"><div class="chart-title">Faturamento por Vendedora</div><div class="chart-wrapper"><canvas id="chartVendedor"></canvas></div></div>
<div class="chart-card"><div class="chart-title">Faturamento Diario</div><div class="chart-wrapper"><canvas id="chartDiario"></canvas></div></div>
<div class="chart-card full"><div class="chart-title">Participacao no Faturamento</div><div class="chart-wrapper"><canvas id="chartDonut"></canvas></div></div>
</div>
<div class="table-card"><div class="chart-title">Detalhamento por Vendedora</div>
<table><thead><tr><th>Vendedora</th><th>Empresa</th><th>Faturamento</th><th>Vendas</th><th>Ticket Medio</th><th>Meta Mensal</th><th>% Meta</th><th>% do Total</th></tr></thead>
<tbody id="tabelaBody"></tbody></table>
</div>
<div class="section-title">Entregas por Entregador</div>
<div class="kpi-grid" id="kpiEntregas"></div>
<div class="charts-grid">
<div class="chart-card"><div class="chart-title">Entregas por Entregador</div><div class="chart-wrapper"><canvas id="chartEntregador"></canvas></div></div>
<div class="chart-card"><div class="chart-title">Entregas por Dia</div><div class="chart-wrapper"><canvas id="chartEntregasDia"></canvas></div></div>
</div>
<div class="table-card"><div class="chart-title">Detalhamento de Entregas</div>
<table><thead><tr><th>Entregador</th><th>Total de Entregas</th><th>% do Total</th></tr></thead>
<tbody id="tabelaEntregas"></tbody></table>
</div>
</div>
<script>
const TODOS_PEDIDOS = __DADOS_JSON__;
const TODAS_ENTREGAS = __ENTREGAS_JSON__;
const METAS = __METAS_JSON__;
const META_CONSOLIDADA = __META_CONSOLIDADA__;
const CORES = ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#14b8a6','#f97316','#6366f1','#84cc16','#06b6d4','#a855f7'];
let chartVend=null, chartDia=null, chartDonut=null, chartEntregador=null, chartEntregasDia=null;
let empresaFilter = 'todos';
function normNome(nome) { if (!nome) return 'Sem vendedor'; return String(nome).replace(/[\xa0\t\n\r]/g, ' ').replace(/\s+/g, ' ').trim(); }
function buscarMeta(nome) { const nomeLower = nome.toLowerCase(); const chave = Object.keys(METAS).find(k => k.toLowerCase() === nomeLower); return chave ? METAS[chave] : 0; }
function init() { const hoje = new Date().toISOString().split('T')[0]; document.getElementById('dataInicio').value = hoje; document.getElementById('dataFim').value = hoje; aplicarFiltro(); }
function setEmpresa(emp, btn) { empresaFilter = emp; document.querySelectorAll('.btn-empresa').forEach(b => b.classList.remove('active')); if (btn) btn.classList.add('active'); aplicarFiltro(); }
function presetHoje() { const h=new Date().toISOString().split('T')[0]; setDatas(h,h); }
function preset7() { const f=new Date(); const i=new Date(); i.setDate(i.getDate()-6); setDatas(i.toISOString().split('T')[0], f.toISOString().split('T')[0]); }
function presetMesAtual() { const a=new Date(); const ini=new Date(a.getFullYear(), a.getMonth(), 1); const fim=new Date(a.getFullYear(), a.getMonth()+1, 0); setDatas(ini.toISOString().split('T')[0], fim.toISOString().split('T')[0]); }
function presetTudo() { setDatas('__MIN_DATA__', '__MAX_DATA__'); }
function setDatas(ini, fim) { document.getElementById('dataInicio').value = ini; document.getElementById('dataFim').value = fim; aplicarFiltro(); }
function aplicarFiltro() {
  const ini = document.getElementById('dataInicio').value;
  const fim = document.getElementById('dataFim').value;
  if (!ini || !fim) return;
  let pedidos = TODOS_PEDIDOS.filter(p => p.data >= ini && p.data <= fim);
  if (empresaFilter !== 'todos') { pedidos = pedidos.filter(p => p.empresa === empresaFilter); }
  const mesRef = fim.substring(0, 7);
  document.getElementById('mesMetaLabel').textContent = formatarMes(mesRef);
  if (pedidos.length === 0) { mostrarSemDados(); } else {
    const porVend = {};
    pedidos.forEach(p => { const v = normNome(p.vendedor); if (!porVend[v]) porVend[v] = { nome: v, faturamento: 0, vendas: 0, empresa: p.empresa }; porVend[v].faturamento += p.valor; porVend[v].vendas += 1; });
    let vendedores = Object.values(porVend).sort((a, b) => b.faturamento - a.faturamento);
    vendedores.forEach(v => v.faturamento = Math.round(v.faturamento * 100) / 100);
    const fatTotal = vendedores.reduce((s, v) => s + v.faturamento, 0);
    const qtdVendas = vendedores.reduce((s, v) => s + v.vendas, 0);
    const ticketMedio = qtdVendas > 0 ? fatTotal / qtdVendas : 0;
    const diasPeriodo = contarDias(ini, fim);
    renderKPIs(fatTotal, qtdVendas, ticketMedio, diasPeriodo, vendedores.length);
    renderMetas(vendedores, mesRef, fatTotal);
    renderChartVendedor(vendedores);
    renderChartDiario(pedidos);
    renderChartDonut(vendedores, fatTotal);
    renderTabela(vendedores, fatTotal);
  }
  let entregas = TODAS_ENTREGAS.filter(e => e.data >= ini && e.data <= fim);
  renderEntregas(entregas, ini, fim);
}
function renderKPIs(fatTotal, qtdVendas, ticketMedio, dias, nVend) {
  let el = 'Consolidado'; if (empresaFilter === 'REAL MAIS') el = 'REAL MAIS'; else if (empresaFilter === 'GP DISTRIBUIDORA') el = 'GP Distribuidora';
  document.getElementById('kpiGrid').innerHTML =
    '<div class="kpi-card"><div class="kpi-label">Faturamento ' + el + '</div><div class="kpi-value">' + fmtMoeda(fatTotal) + '</div><div class="kpi-sub">' + dias + ' dia(s)</div></div>' +
    '<div class="kpi-card green"><div class="kpi-label">Quantidade de Vendas</div><div class="kpi-value">' + qtdVendas + '</div><div class="kpi-sub">pedidos nao cancelados</div></div>' +
    '<div class="kpi-card amber"><div class="kpi-label">Ticket Medio</div><div class="kpi-value">' + fmtMoeda(ticketMedio) + '</div><div class="kpi-sub">por venda</div></div>' +
    '<div class="kpi-card purple"><div class="kpi-label">Vendedoras Ativas</div><div class="kpi-value">' + nVend + '</div><div class="kpi-sub">com vendas no periodo</div></div>';
}
function renderMetas(vendedores, mesRef, fatTotal) {
  let html = '';
  if (empresaFilter === 'todos') {
    const totalMeta = META_CONSOLIDADA; const totalFat = fatTotal;
    const pctCons = totalMeta > 0 ? (totalFat / totalMeta * 100) : 0; const pctBarCons = Math.min(pctCons, 100);
    const faltaCons = Math.max(totalMeta - totalFat, 0);
    let scCons, stCons, cbCons;
    if (pctCons >= 100) { scCons='status-bateu'; stCons='Meta atingida'; cbCons='#16a34a'; }
    else if (pctCons >= 70) { scCons='status-perto'; stCons='Quase la'; cbCons='#f59e0b'; }
    else { scCons='status-longe'; stCons='Em progresso'; cbCons='#dc2626'; }
    const totalVendas = vendedores.reduce((s,v) => s + v.vendas, 0);
    let tfCons = '';
    if (totalMeta > 0 && pctCons < 100) { tfCons = 'Faltam <strong style="color:#fff;">' + fmtMoeda(faltaCons) + '</strong> para a meta consolidada'; }
    else if (totalMeta > 0 && pctCons >= 100) { tfCons = 'Superou a meta consolidada em <strong style="color:#fff;">' + fmtMoeda(totalFat - totalMeta) + '</strong>'; }
    html += '<div class="meta-card consolidado"><div class="meta-header"><div class="meta-avatar" style="background:#fff;color:#2563eb;">C</div><div><div class="meta-name">META CONSOLIDADA - Real Mais + GP Distribuidora</div><div class="meta-sub">' + totalVendas + ' venda(s) no total - Ticket: ' + fmtMoeda(totalVendas > 0 ? totalFat / totalVendas : 0) + '</div></div></div><div class="meta-progress-bar"><div class="meta-progress-fill" style="width:' + pctBarCons + '%;background:' + cbCons + '">' + pctCons.toFixed(0) + '%</div></div><div class="meta-stats"><div><span class="meta-valor">' + fmtMoeda(totalFat) + '</span><span style="color:rgba(255,255,255,0.7);font-size:13px;"> / ' + fmtMoeda(totalMeta) + '</span></div><span class="meta-status ' + scCons + '">' + stCons + '</span></div>' + (tfCons ? '<div class="meta-falta">' + tfCons + '</div>' : '') + '</div>';
  }
  const nomesComVendas = new Set(vendedores.map(v => v.nome.toLowerCase()));
  const todas = [...vendedores];
  Object.keys(METAS).forEach(nome => { if (!nomesComVendas.has(nome.toLowerCase())) { const empMeta = (nome === 'GP DISTRIBUIDORA') ? 'GP DISTRIBUIDORA' : 'REAL MAIS'; if (empresaFilter === 'todos' || empresaFilter === empMeta) { todas.push({ nome: nome, faturamento: 0, vendas: 0, empresa: empMeta }); } } });
  todas.sort((a, b) => { const ma = buscarMeta(a.nome); const mb = buscarMeta(b.nome); const pa = ma > 0 ? a.faturamento / ma : 0; const pb = mb > 0 ? b.faturamento / mb : 0; return pb - pa; });
  todas.forEach((v, i) => {
    const meta = buscarMeta(v.nome); const cor = CORES[i % CORES.length];
    const iniciais = v.nome.split(' ').map(p => p[0]).join('').substring(0, 2).toUpperCase();
    const pctMeta = meta > 0 ? (v.faturamento / meta * 100) : 0; const pctBar = Math.min(pctMeta, 100);
    let sc, st, cb;
    if (meta === 0) { sc='status-semmeta'; st='Sem meta'; cb='#94a3b8'; }
    else if (pctMeta >= 100) { sc='status-bateu'; st='Meta atingida'; cb='#16a34a'; }
    else if (pctMeta >= 70) { sc='status-perto'; st='Quase la'; cb='#f59e0b'; }
    else { sc='status-longe'; st='Em progresso'; cb='#dc2626'; }
    const falta = meta > 0 ? Math.max(meta - v.faturamento, 0) : 0;
    const tm = v.vendas > 0 ? v.faturamento / v.vendas : 0;
    let tf = '';
    if (meta > 0 && pctMeta < 100) { tf = 'Faltam <strong>' + fmtMoeda(falta) + '</strong> para a meta'; if (tm > 0) { tf += ' - approx ' + Math.ceil(falta / tm) + ' venda(s)'; } }
    else if (meta > 0 && pctMeta >= 100) { tf = 'Superou a meta em <strong>' + fmtMoeda(v.faturamento - meta) + '</strong>'; }
    const badgeEmp = v.empresa === 'GP DISTRIBUIDORA' ? '<span style="background:#fef3c7;color:#f59e0b;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:700;margin-left:8px;">GP</span>' : '<span style="background:#dbeafe;color:#2563eb;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:700;margin-left:8px;">RM</span>';
    html += '<div class="meta-card"><div class="meta-header"><div class="meta-avatar" style="background:' + cor + '">' + iniciais + '</div><div><div class="meta-name">' + v.nome + badgeEmp + '</div><div class="meta-sub">' + v.vendas + ' venda(s) - Ticket: ' + fmtMoeda(tm) + '</div></div></div><div class="meta-progress-bar"><div class="meta-progress-fill" style="width:' + pctBar + '%;background:' + cb + '">' + pctMeta.toFixed(0) + '%</div></div><div class="meta-stats"><div><span class="meta-valor ' + (pctMeta >= 100 ? 'atingido' : 'abaixo') + '">' + fmtMoeda(v.faturamento) + '</span><span style="color:var(--text-muted);font-size:13px;"> / ' + (meta > 0 ? fmtMoeda(meta) : '-') + '</span></div><span class="meta-status ' + sc + '">' + st + '</span></div>' + (tf ? '<div class="meta-falta">' + tf + '</div>' : '') + '</div>';
  });
  document.getElementById('metaGrid').innerHTML = html;
}
function renderEntregas(entregas, ini, fim) {
  if (!entregas || entregas.length === 0) {
    document.getElementById('kpiEntregas').innerHTML = '<div class="no-data">Nenhuma entrega registrada no periodo.</div>';
    document.getElementById('tabelaEntregas').innerHTML = '';
    if (chartEntregador) chartEntregador.destroy();
    if (chartEntregasDia) chartEntregasDia.destroy();
    return;
  }
  const porEntregador = {}; const porDia = {};
  entregas.forEach(e => { const nome = e.entregador; if (!porEntregador[nome]) porEntregador[nome] = 0; porEntregador[nome]++; if (!porDia[e.data]) porDia[e.data] = 0; porDia[e.data]++; });
  const totalEntregas = entregas.length;
  const entregadoresReais = Object.keys(porEntregador).filter(n => n !== 'RETIRADA');
  const totalEntregadoresReais = entregadoresReais.length;
  const totalRetiradas = porEntregador['RETIRADA'] || 0;
  const diasPeriodo = contarDias(ini, fim);
  document.getElementById('kpiEntregas').innerHTML =
    '<div class="kpi-card teal"><div class="kpi-label">Total de Entregas</div><div class="kpi-value">' + totalEntregas + '</div><div class="kpi-sub">' + diasPeriodo + ' dia(s)</div></div>' +
    '<div class="kpi-card"><div class="kpi-label">Entregadores Ativos</div><div class="kpi-value">' + totalEntregadoresReais + '</div><div class="kpi-sub">no periodo</div></div>' +
    '<div class="kpi-card amber"><div class="kpi-label">Retiradas no Balcao</div><div class="kpi-value">' + totalRetiradas + '</div><div class="kpi-sub">sem entregador</div></div>' +
    '<div class="kpi-card green"><div class="kpi-label">Media por Entregador</div><div class="kpi-value">' + (totalEntregadoresReais > 0 ? (totalEntregas / totalEntregadoresReais).toFixed(0) : 0) + '</div><div class="kpi-sub">entregas por pessoa</div></div>';
  const ctxE = document.getElementById('chartEntregador').getContext('2d');
  if (chartEntregador) chartEntregador.destroy();
  const entrOrdenados = Object.entries(porEntregador).sort((a, b) => b[1] - a[1]).filter(([nome]) => nome !== 'RETIRADA');
  chartEntregador = new Chart(ctxE, { type: 'bar', data: { labels: entrOrdenados.map(x => x[0]), datasets: [{ label: 'Entregas', data: entrOrdenados.map(x => x[1]), backgroundColor: entrOrdenados.map((_, i) => CORES[i % CORES.length] + 'cc'), borderColor: entrOrdenados.map((_, i) => CORES[i % CORES.length]), borderWidth: 2, borderRadius: 6 }] }, options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => 'Entregas: ' + c.raw } } }, scales: { x: { ticks: { stepSize: 1 } } } } });
  const ctxED = document.getElementById('chartEntregasDia').getContext('2d');
  if (chartEntregasDia) chartEntregasDia.destroy();
  const todasDatas = Object.keys(porDia).sort();
  const datasComVendas = []; const valoresDia = [];
  todasDatas.forEach(d => { if (porDia[d] > 0) { datasComVendas.push(d); valoresDia.push(porDia[d]); } });
  const g2 = ctxED.createLinearGradient(0, 0, 0, 320);
  g2.addColorStop(0, 'rgba(20,184,166,0.3)'); g2.addColorStop(1, 'rgba(20,184,166,0.02)');
  chartEntregasDia = new Chart(ctxED, { type: 'line', data: { labels: datasComVendas.map(fmtData), datasets: [{ label: 'Entregas', data: valoresDia, borderColor: '#14b8a6', backgroundColor: g2, borderWidth: 3, fill: true, tension: 0.3, pointRadius: 4, pointBackgroundColor: '#14b8a6', pointHoverRadius: 7 }] }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => 'Entregas: ' + c.raw } } }, scales: { y: { ticks: { stepSize: 1 } } } } });
  let htmlT = '';
  const entrTabela = Object.entries(porEntregador).sort((a, b) => b[1] - a[1]);
  entrTabela.forEach(([nome, qtd], i) => { const pct = totalEntregas > 0 ? (qtd / totalEntregas * 100) : 0; const cor = CORES[i % CORES.length]; const isRetirada = nome === 'RETIRADA'; htmlT += '<tr><td class="vendedor-name"><span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:' + cor + ';margin-right:8px;"></span>' + (isRetirada ? 'RETIRADA' : nome) + '</td><td>' + qtd + '</td><td><span class="pct-bar"><span class="pct-fill" style="width:' + pct + '%;background:' + cor + '"></span></span>' + pct.toFixed(1) + '%</td></tr>'; });
  document.getElementById('tabelaEntregas').innerHTML = htmlT;
}
function renderChartVendedor(v) {
  const ctx = document.getElementById('chartVendedor').getContext('2d');
  if (chartVend) chartVend.destroy();
  chartVend = new Chart(ctx, { type: 'bar', data: { labels: v.map(x => x.nome), datasets: [{ label: 'Faturamento', data: v.map(x => x.faturamento), backgroundColor: v.map((_, i) => CORES[i % CORES.length] + 'cc'), borderColor: v.map((_, i) => CORES[i % CORES.length]), borderWidth: 2, borderRadius: 6 }] }, options: { indexAxis: 'y', responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => 'Faturamento: ' + fmtMoeda(c.raw) } } }, scales: { x: { ticks: { callback: v => 'R$ ' + v.toLocaleString('pt-BR') } } } } });
}
function renderChartDiario(pedidos) {
  const ctx = document.getElementById('chartDiario').getContext('2d');
  if (chartDia) chartDia.destroy();
  const pd = {};
  pedidos.forEach(p => { if (!pd[p.data]) pd[p.data] = 0; pd[p.data] += p.valor; });
  const datasComVendas = Object.keys(pd).sort();
  const valores = datasComVendas.map(d => pd[d]);
  const g = ctx.createLinearGradient(0, 0, 0, 320);
  g.addColorStop(0, 'rgba(37,99,235,0.3)'); g.addColorStop(1, 'rgba(37,99,235,0.02)');
  chartDia = new Chart(ctx, { type: 'line', data: { labels: datasComVendas.map(fmtData), datasets: [{ label: 'Faturamento', data: valores, borderColor: '#2563eb', backgroundColor: g, borderWidth: 3, fill: true, tension: 0.3, pointRadius: 4, pointBackgroundColor: '#2563eb', pointHoverRadius: 7 }] }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false }, tooltip: { callbacks: { label: c => 'Faturamento: ' + fmtMoeda(c.raw) } } }, scales: { y: { ticks: { callback: v => 'R$ ' + v.toLocaleString('pt-BR') } } } } });
}
function renderChartDonut(v, fatTotal) {
  const ctx = document.getElementById('chartDonut').getContext('2d');
  if (chartDonut) chartDonut.destroy();
  chartDonut = new Chart(ctx, { type: 'doughnut', data: { labels: v.map(x => x.nome), datasets: [{ data: v.map(x => x.faturamento), backgroundColor: v.map((_, i) => CORES[i % CORES.length]), borderColor: '#fff', borderWidth: 3 }] }, options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: 'right', labels: { padding: 16, font: { size: 13 } } }, tooltip: { callbacks: { label: c => { const pct = ((c.raw / fatTotal) * 100).toFixed(1); return c.label + ': ' + fmtMoeda(c.raw) + ' (' + pct + '%)'; } } } } } });
}
function renderTabela(v, fatTotal) {
  let html = '';
  v.forEach((x, i) => { const pct = fatTotal > 0 ? (x.faturamento / fatTotal * 100) : 0; const t = x.vendas > 0 ? x.faturamento / x.vendas : 0; const meta = buscarMeta(x.nome); const pm = meta > 0 ? (x.faturamento / meta * 100) : 0; const cor = CORES[i % CORES.length]; const cm = pm >= 100 ? '#16a34a' : pm >= 70 ? '#f59e0b' : '#dc2626'; const badgeEmp = x.empresa === 'GP DISTRIBUIDORA' ? '<span style="background:#fef3c7;color:#f59e0b;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:700;">GP</span>' : '<span style="background:#dbeafe;color:#2563eb;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:700;">RM</span>'; html += '<tr><td class="vendedor-name"><span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:' + cor + ';margin-right:8px;"></span>' + x.nome + '</td><td>' + badgeEmp + '</td><td class="valor-cell">' + fmtMoeda(x.faturamento) + '</td><td>' + x.vendas + '</td><td>' + fmtMoeda(t) + '</td><td>' + (meta > 0 ? fmtMoeda(meta) : '<span style="color:var(--text-muted)">-</span>') + '</td><td><span class="pct-bar"><span class="pct-fill" style="width:' + Math.min(pm, 100) + '%;background:' + cm + '"></span></span><strong style="color:' + cm + '">' + pm.toFixed(0) + '%</strong></td><td><span class="pct-bar"><span class="pct-fill" style="width:' + pct + '%;background:' + cor + '"></span></span>' + pct.toFixed(1) + '%</td></tr>'; });
  document.getElementById('tabelaBody').innerHTML = html;
}
function mostrarSemDados() { document.getElementById('kpiGrid').innerHTML = '<div class="no-data">Nenhum pedido no periodo.</div>'; document.getElementById('metaGrid').innerHTML = ''; document.getElementById('tabelaBody').innerHTML = ''; if (chartVend) chartVend.destroy(); if (chartDia) chartDia.destroy(); if (chartDonut) chartDonut.destroy(); }
function fmtMoeda(v) { return 'R$ ' + Number(v).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
function fmtData(iso) { const [y, m, d] = iso.split('-'); return d + '/' + m; }
function contarDias(ini, fim) { const d1 = new Date(ini + 'T00:00:00'); const d2 = new Date(fim + 'T00:00:00'); return Math.round((d2 - d1) / 86400000) + 1; }
function formatarMes(mr) { const [ano, mes] = mr.split('-'); const n = ['Janeiro','Fevereiro','Marco','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro']; return n[parseInt(mes) - 1] + ' ' + ano; }
document.addEventListener('keydown', e => { if (e.key === 'Enter' && e.target.type === 'date') aplicarFiltro(); });
window.addEventListener('DOMContentLoaded', init);
</script>
</body>
</html>'''
    html = html.replace("__DADOS_JSON__", dados_json)
    html = html.replace("__ENTREGAS_JSON__", entregas_json)
    html = html.replace("__METAS_JSON__", metas_json)
    html = html.replace("__META_CONSOLIDADA__", str(META_CONSOLIDADA))
    html = html.replace("__DATA_GERACAO__", data_geracao)
    html = html.replace("__MIN_DATA__", min_data)
    html = html.replace("__MAX_DATA__", max_data)
    return html

# ── BUSCA DE DADOS EM SEGUNDO PLANO ───────────────────────────────────────
def buscar_dados_background():
    """Roda em uma thread separada para não bloquear o servidor."""
    with _cache_lock:
        if _cache["buscando"]:
            return
        _cache["buscando"] = True

    try:
        hoje = date.today()
        data_inicio = f"{hoje.year}-01-01"
        data_fim = f"{hoje.year}-12-31"

        todos_pedidos = []
        for emp in EMPRESAS:
            headers = make_headers(emp)
            pedidos_brutos = listar_pedidos_periodo(data_inicio, data_fim, emp, headers)
            pedidos = processar_pedidos(pedidos_brutos, emp)
            todos_pedidos.extend(pedidos)

        entregas = ler_dados_entregas()
        html = gerar_dashboard_html(todos_pedidos, entregas)

        with _cache_lock:
            _cache["timestamp"] = time.time()
            _cache["html"] = html
            _cache["erro"] = ""
            _cache["buscando"] = False
    except Exception as e:
        with _cache_lock:
            _cache["erro"] = str(e)
            _cache["buscando"] = False

# ── PÁGINA DE LOADING ─────────────────────────────────────────────────────
LOADING_HTML = '''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Carregando Dashboard...</title>
<style>
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f0f2f5;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;}
.loader{text-align:center;padding:40px;background:#fff;border-radius:16px;box-shadow:0 4px 6px rgba(0,0,0,.07);}
.spinner{width:50px;height:50px;border:5px solid #dbeafe;border-top-color:#2563eb;border-radius:50%;margin:0 auto 20px;animation:spin 1s linear infinite;}
@keyframes spin{to{transform:rotate(360deg);}}
h1{color:#1e293b;font-size:20px;margin:0 0 8px;}
p{color:#64748b;font-size:14px;margin:0;}
</style>
<meta http-equiv="refresh" content="10">
</head>
<body>
<div class="loader">
<div class="spinner"></div>
<h1>Buscando dados...</h1>
<p>Aguarde, estamos coletando as informacoes de vendas e entregas.</p>
<p style="margin-top:8px;font-size:12px;color:#94a3b8;">Esta pagina vai atualizar automaticamente em 10 segundos.</p>
</div>
</body>
</html>'''

# ── ROTAS FLASK ───────────────────────────────────────────────────────────
@app.route('/')
def dashboard():
    agora = time.time()
    with _cache_lock:
        tempo_decorrido = agora - _cache["timestamp"]
        if _cache["html"] and tempo_decorrido < CACHE_TEMPO_SEGUNDOS:
            return _cache["html"]
        if _cache["buscando"]:
            return LOADING_HTML

    # Iniciar busca em background
    thread = threading.Thread(target=buscar_dados_background, daemon=True)
    thread.start()
    return LOADING_HTML

@app.route('/atualizar')
def forcar_atualizacao():
    with _cache_lock:
        _cache["timestamp"] = 0
        _cache["html"] = ""
        _cache["buscando"] = False
    thread = threading.Thread(target=buscar_dados_background, daemon=True)
    thread.start()
    return "<script>window.location.href='/';</script>"

# ── INICIALIZAÇÃO: BUSCAR DADOS AO SUBIR ──────────────────────────────────
def init_background():
    """Inicia a primeira busca de dados assim que o servidor sobe."""
    time.sleep(2)
    buscar_dados_background()

# Thread que busca dados ao iniciar
_init_thread = threading.Thread(target=init_background, daemon=True)
_init_thread.start()
