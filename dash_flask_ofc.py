#!/usr/bin/env python3
"""
dash_flask_ofc.py  (v17 — correção Render + menu de datas)

Correções:
  - Removida rota duplicada 'dashboard' (causava AssertionError no Render)
  - Inicialização em background fora do if __name__ (gunicorn não executa esse bloco)
  - Menu de datas com: dia específico, 7 dias, mês atual, ano atual, tudo
  - Filtro funciona instantaneamente no navegador (sem buscar na API de novo)

Deploy no Render:
  Build:  pip install -r requirements.txt
  Start:  gunicorn dash_flask_ofc:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 300
"""

import os, sys, json, re, threading, traceback
from datetime import datetime, date, timedelta
from pathlib import Path
from calendar import monthrange
import requests
from flask import Flask, send_file, jsonify

# ── CONFIG
BASE_URL = "https://api.vhsys.com/v2"
ACCESS_TOKEN = "YYeHeFaNAfVfLegOLXedMFZMLNPLQT"
SECRET_TOKEN = "k9Qhe0oaSAchTjWgpvLeUvxmZcyLVfO"

OUTPUT_DIR = Path(__file__).resolve().parent
DADOS_JSON = OUTPUT_DIR / "vhsys_dados_pedidos.json"
DASHBOARD_HTML = OUTPUT_DIR / "dashboard_vhsys.html"

STATUS_EXCLUIDOS = {"Cancelado"}
HEADERS_BASE = {
    "access-token": ACCESS_TOKEN,
    "secret-access-token": SECRET_TOKEN,
    "Cache-Control": "no-cache",
    "User-Agent": "MinhaAplicacao/1.0",
    "Content-Type": "application/json",
}

METAS_MENSAIS = {
    "SIMONE MOURA": 215000.00,
    "ISA":          241500.00,
    "ANA RUTH":     65000.00,
}

CORES = ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899',
         '#14b8a6','#f97316','#6366f1','#84cc16','#06b6d4','#a855f7']

# ── NORMALIZAÇÃO
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
    return ""

def normalizar_nome_vendedor(nome):
    if not nome:
        return "SEM VENDEDOR"
    s = str(nome).replace('\xa0',' ').replace('\t',' ').replace('\n',' ').replace('\r',' ')
    s = ' '.join(s.split()).upper()
    return s if s else "SEM VENDEDOR"

# ── API
def listar_pedidos_periodo(data_inicio, data_fim):
    if not ACCESS_TOKEN or not SECRET_TOKEN:
        raise RuntimeError("Tokens nao configurados.")
    todos = []
    offset = 0
    limit = 250
    pagina = 1
    max_paginas = 200
    print(f"[API] Buscando {data_inicio} a {data_fim}...")
    while pagina &lt;= max_paginas:
        params = {"limit": limit, "offset": offset, "order": "data_pedido", "sort": "Desc"}
        try:
            resp = requests.get(f"{BASE_URL}/pedidos/", headers=HEADERS_BASE, params=params, timeout=30)
        except requests.RequestException as e:
            print(f"  ERRO pag {pagina}: {e}")
            break
        if resp.status_code == 403:
            break
        if resp.status_code != 200:
            break
        try:
            payload = resp.json()
        except ValueError:
            break
        lote = payload.get("data", [])
        if isinstance(lote, dict):
            lote = [lote]
        if not lote or not isinstance(lote, list):
            break
        todos.extend(lote)
        datas_pagina = []
        pedidos_antes = 0
        for p in lote:
            if not isinstance(p, dict):
                continue
            dp = normalizar_data(p.get("data_pedido", ""))
            if dp and dp != "0000-00-00":
                datas_pagina.append(dp)
                if dp &lt; data_inicio:
                    pedidos_antes += 1
        if datas_pagina:
            print(f"  Pag {pagina}: {len(lote)} | {min(datas_pagina)} a {max(datas_pagina)} | antes: {pedidos_antes} | acum: {len(todos)}")
        if pedidos_antes > 0:
            print("  OK — parada inteligente.")
            break
        offset += limit
        pagina += 1
    filtrados = []
    for p in todos:
        if not isinstance(p, dict):
            continue
        dp = normalizar_data(p.get("data_pedido", ""))
        if dp and dp != "0000-00-00" and data_inicio &lt;= dp &lt;= data_fim:
            p["data_pedido"] = dp
            filtrados.append(p)
    print(f"[API] Filtrado: {len(filtrados)} pedidos")
    return filtrados

def processar_pedidos(pedidos):
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
        except (TypeError, ValueError):
            valor = 0.0
        vendedor = normalizar_nome_vendedor(p.get("vendedor_pedido", ""))
        data_ped = normalizar_data(p.get("data_pedido", ""))
        processados.append({
            "id": str(p.get("id_ped", p.get("id_pedido", ""))),
            "data": data_ped,
            "vendedor": vendedor,
            "valor": round(valor, 2),
            "status": status,
            "cliente": p.get("nome_cliente", ""),
        })
    return processados

# ── DASHBOARD HTML
def gerar_dashboard_html(pedidos, fase="2"):
    dados_json = json.dumps(pedidos, ensure_ascii=False)
    metas_upper = {k.upper(): v for k, v in METAS_MENSAIS.items()}
    metas_json = json.dumps(metas_upper, ensure_ascii=False)
    data_geracao = datetime.now().strftime("%d/%m/%Y às %H:%M:%S")

    if fase == "1":
        banner = '<div style="background:#fef3c7;color:#92400e;padding:8px 16px;font-size:13px;text-align:center;">⚠️ Dados parciais (últimos 3 meses). Carregando ano completo em segundo plano...</div>'
    else:
        banner = '<div style="background:#dcfce7;color:#16a34a;padding:8px 16px;font-size:13px;text-align:center;">✅ Dados completos do ano carregados.</div>'

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
<title>Dashboard de Faturamento | Vhsys</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
:root{--bg:#f0f2f5;--card-bg:#fff;--primary:#2563eb;--primary-light:#dbeafe;--green:#16a34a;--green-light:#dcfce7;--amber:#f59e0b;--amber-light:#fef3c7;--red:#dc2626;--red-light:#fee2e2;--text:#1e293b;--text-muted:#64748b;--border:#e2e8f0;--shadow:0 1px 3px rgba(0,0,0,.1),0 1px 2px rgba(0,0,0,.06);--shadow-lg:0 4px 6px rgba(0,0,0,.07),0 2px 4px rgba(0,0,0,.06);--radius:12px;}
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;}
.header{background:linear-gradient(135deg,#1e3a5f 0%,#2563eb 100%);color:#fff;padding:24px 32px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;}
.header h1{font-size:24px;font-weight:700;}
.header .subtitle{font-size:13px;opacity:.85;margin-top:4px;}
.header .updated{font-size:12px;opacity:.7;margin-top:8px;}
.btn-refresh{background:rgba(255,255,255,.2);color:#fff;border:1px solid rgba(255,255,255,.4);padding:8px 16px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;transition:all .2s;text-decoration:none;}
.btn-refresh:hover{background:rgba(255,255,255,.3);}
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
.btn-preset.active{background:var(--primary);color:#fff;}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:24px;}
.kpi-card{background:var(--card-bg);border-radius:var(--radius);box-shadow:var(--shadow);padding:20px 24px;border-left:4px solid var(--primary);transition:box-shadow .2s;}
.kpi-card:hover{box-shadow:var(--shadow-lg);}
.kpi-card.green{border-left-color:var(--green);}
.kpi-card.amber{border-left-color:var(--amber);}
.kpi-card.red{border-left-color:var(--red);}
.kpi-card.purple{border-left-color:#8b5cf6;}
.kpi-label{font-size:12px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px;}
.kpi-value{font-size:26px;font-weight:700;color:var(--text);}
.kpi-sub{font-size:12px;color:var(--text-muted);margin-top:4px;}
.meta-section-title{font-size:18px;font-weight:700;margin-bottom:16px;color:var(--text);display:flex;align-items:center;gap:8px;}
.meta-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px;margin-bottom:24px;}
.meta-card{background:var(--card-bg);border-radius:var(--radius);box-shadow:var(--shadow);padding:20px 22px;transition:box-shadow .2s;}
.meta-card:hover{box-shadow:var(--shadow-lg);}
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
<div>
<h1>📊 Dashboard de Faturamento & Metas</h1>
<div class="subtitle">Vendas por vendedora • Vhsys API v2</div>
<div class="updated">Dados gerados em: __DATA_GERACAO__</div>
</div>
<a href="/atualizar" class="btn-refresh">🔄 Atualizar</a>
</div>
__BANNER_FASE__
<div class="container">
<div class="filter-bar">
<div class="filter-group"><label>🗓️ Inicial</label><input type="date" id="dataInicio" value="__MIN_DATA__"></div>
<div class="filter-group"><label>🗓️ Final</label><input type="date" id="dataFim" value="__MAX_DATA__"></div>
<button class="btn-apply" onclick="aplicarFiltro()">🔍 Aplicar</button>
<div style="margin-left:auto;display:flex;gap:8px;flex-wrap:wrap;">
<button class="btn-preset" onclick="presetHoje()">Hoje</button>
<button class="btn-preset" onclick="presetOntem()">Ontem</button>
<button class="btn-preset" onclick="preset7()">7 dias</button>
<button class="btn-preset" onclick="presetMesAtual()">Mês Atual</button>
<button class="btn-preset" onclick="presetAnoAtual()">Ano Atual</button>
<button class="btn-preset" onclick="presetTudo()">Tudo</button>
</div>
</div>
<div class="kpi-grid" id="kpiGrid"></div>
<div id="metaSection"><div class="meta-section-title">🎯 Metas Mensais — <span id="mesMetaLabel"></span></div><div class="meta-grid" id="metaGrid"></div></div>
<div class="charts-grid">
<div class="chart-card"><div class="chart-title">💰 Faturamento por Vendedora</div><div class="chart-wrapper"><canvas id="chartVendedor"></canvas></div></div>
<div class="chart-card"><div class="chart-title">📈 Faturamento Diário</div><div class="chart-wrapper"><canvas id="chartDiario"></canvas></div></div>
<div class="chart-card full"><div class="chart-title">🍩 Participação no Faturamento</div><div class="chart-wrapper"><canvas id="chartDonut"></canvas></div></div>
</div>
<div class="table-card"><div class="chart-title">📋 Detalhamento por Vendedora</div>
<table><thead><tr><th>Vendedora</th><th>Faturamento</th><th>Vendas</th><th>Ticket Médio</th><th>Meta Mensal</th><th>% Meta</th><th>% do Total</th></tr></thead>
<tbody id="tabelaBody"></tbody></table>
</div>
</div>
<script>
const TODOS_PEDIDOS=__DADOS_JSON__;const METAS=__METAS_JSON__;const CORES=['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#14b8a6','#f97316','#6366f1','#84cc16','#06b6d4','#a855f7'];let chartVend=null,chartDia=null,chartDonut=null;
function fmtNome(n){if(!n)return 'Sem vendedor';if(n.toUpperCase()==='SEM VENDEDOR')return 'Sem vendedor';return n.split(' ').map(w=>w.charAt(0).toUpperCase()+w.slice(1).toLowerCase()).join(' ');}
function init(){document.getElementById('dataInicio').value='__MIN_DATA__';document.getElementById('dataFim').value='__MAX_DATA__';aplicarFiltro();}
function presetHoje(){const h=new Date().toISOString().split('T')[0];setDatas(h,h);}
function presetOntem(){const o=new Date();o.setDate(o.getDate()-1);const s=o.toISOString().split('T')[0];setDatas(s,s);}
function preset7(){const f=new Date();const i=new Date();i.setDate(i.getDate()-6);setDatas(i.toISOString().split('T')[0],f.toISOString().split('T')[0]);}
function presetMesAtual(){const a=new Date();const ini=new Date(a.getFullYear(),a.getMonth(),1);const fim=new Date(a.getFullYear(),a.getMonth()+1,0);setDatas(ini.toISOString().split('T')[0],fim.toISOString().split('T')[0]);}
function presetAnoAtual(){const a=new Date();setDatas(a.getFullYear()+'-01-01',a.toISOString().split('T')[0]);}
function presetTudo(){setDatas('__MIN_DATA__','__MAX_DATA__');}
function setDatas(ini,fim){document.getElementById('dataInicio').value=ini;document.getElementById('dataFim').value=fim;aplicarFiltro();}
function aplicarFiltro(){const ini=document.getElementById('dataInicio').value;const fim=document.getElementById('dataFim').value;if(!ini||!fim)return;const pedidos=TODOS_PEDIDOS.filter(p=>p.data>=ini&&p.data&lt;=fim);const mesRef=fim.substring(0,7);document.getElementById('mesMetaLabel').textContent=formatarMes(mesRef);if(pedidos.length===0){mostrarSemDados();return;}const porVend={};pedidos.forEach(p=>{const v=String(p.vendedor||'SEM VENDEDOR').toUpperCase().replace(/\s+/g,' ').trim();if(!porVend[v])porVend[v]={nome:v,faturamento:0,vendas:0};porVend[v].faturamento+=p.valor;porVend[v].vendas+=1;});let vendedores=Object.values(porVend).sort((a,b)=>b.faturamento-a.faturamento);vendedores.forEach(v=>v.faturamento=Math.round(v.faturamento*100)/100);const fatTotal=vendedores.reduce((s,v)=>s+v.faturamento,0);const qtdVendas=vendedores.reduce((s,v)=>s+v.vendas,0);const ticketMedio=qtdVendas>0?fatTotal/qtdVendas:0;const diasPeriodo=contarDias(ini,fim);renderKPIs(fatTotal,qtdVendas,ticketMedio,diasPeriodo,vendedores.length);renderMetas(vendedores,mesRef);renderChartVendedor(vendedores);renderChartDiario(pedidos);renderChartDonut(vendedores,fatTotal);renderTabela(vendedores,fatTotal);}
function renderKPIs(fatTotal,qtdVendas,ticketMedio,dias,nVend){document.getElementById('kpiGrid').innerHTML='<div class="kpi-card"><div class="kpi-label">💵 Faturamento Total</div><div class="kpi-value">'+fmtMoeda(fatTotal)+'</div><div class="kpi-sub">'+dias+' dia(s)</div></div><div class="kpi-card green"><div class="kpi-label">🛒 Vendas</div><div class="kpi-value">'+qtdVendas+'</div><div class="kpi-sub">não cancelados</div></div><div class="kpi-card amber"><div class="kpi-label">🎯 Ticket Médio</div><div class="kpi-value">'+fmtMoeda(ticketMedio)+'</div><div class="kpi-sub">por venda</div></div><div class="kpi-card purple"><div class="kpi-label">👥 Vendedoras</div><div class="kpi-value">'+nVend+'</div><div class="kpi-sub">ativas</div></div>';}
function renderMetas(vendedores,mesRef){let html='';const nomesComVendas=new Set(vendedores.map(v=>v.nome.toUpperCase()));const todas=[...vendedores];Object.keys(METAS).forEach(nome=>{if(!nomesComVendas.has(nome.toUpperCase()))todas.push({nome:nome.toUpperCase(),faturamento:0,vendas:0});});todas.sort((a,b)=>{const ma=METAS[a.nome.toUpperCase()]||0;const mb=METAS[b.nome.toUpperCase()]||0;const pa=ma>0?a.faturamento/ma:0;const pb=mb>0?b.faturamento/mb:0;return pb-pa;});todas.forEach((v,i)=>{const meta=METAS[v.nome.toUpperCase()]||0;const cor=CORES[i%CORES.length];const iniciais=v.nome.split(' ').map(p=>p[0]).join('').substring(0,2).toUpperCase();const pctMeta=meta>0?(v.faturamento/meta*100):0;const pctBar=Math.min(pctMeta,100);let sc,st,cb;if(meta===0){sc='status-semmeta';st='Sem meta';cb='#94a3b8';}else if(pctMeta>=100){sc='status-bateu';st='✅ Meta';cb='#16a34a';}else if(pctMeta>=70){sc='status-perto';st='🔥 Quase';cb='#f59e0b';}else{sc='status-longe';st='📈 Progresso';cb='#dc2626';}const falta=meta>0?Math.max(meta-v.faturamento,0):0;const tm=v.vendas>0?v.faturamento/v.vendas:0;let tf='';if(meta>0&&pctMeta&lt;100){tf='Faltam <strong>'+fmtMoeda(falta)+'</strong>';if(tm>0)tf+=' • ≈ '+Math.ceil(falta/tm)+' venda(s)';}else if(meta>0&&pctMeta>=100){tf='🎉 Superou em <strong>'+fmtMoeda(v.faturamento-meta)+'</strong>';}html+='<div class="meta-card"><div class="meta-header"><div class="meta-avatar" style="background:'+cor+'">'+iniciais+'</div><div><div class="meta-name">'+fmtNome(v.nome)+'</div><div class="meta-sub">'+v.vendas+' venda(s) • Ticket: '+fmtMoeda(tm)+'</div></div></div><div class="meta-progress-bar"><div class="meta-progress-fill" style="width:'+pctBar+'%;background:'+cb+'">'+pctMeta.toFixed(0)+'%</div></div><div class="meta-stats"><div><span class="meta-valor '+(pctMeta>=100?'atingido':'abaixo')+'">'+fmtMoeda(v.faturamento)+'</span><span style="color:var(--text-muted);font-size:13px;"> / '+(meta>0?fmtMoeda(meta):'—')+'</span></div><span class="meta-status '+sc+'">'+st+'</span></div>'+(tf?'<div class="meta-falta">'+tf+'</div>':'')+'</div>';});document.getElementById('metaGrid').innerHTML=html;}
function renderChartVendedor(v){const ctx=document.getElementById('chartVendedor').getContext('2d');if(chartVend)chartVend.destroy();chartVend=new Chart(ctx,{type:'bar',data:{labels:v.map(x=>fmtNome(x.nome)),datasets:[{label:'Faturamento',data:v.map(x=>x.faturamento),backgroundColor:v.map((_,i)=>CORES[i%CORES.length]+'cc'),borderColor:v.map((_,i)=>CORES[i%CORES.length]),borderWidth:2,borderRadius:6}]},options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>'Faturamento: '+fmtMoeda(c.raw)}}},scales:{x:{ticks:{callback:v=>'R$ '+v.toLocaleString('pt-BR')}}}}});}
function renderChartDiario(pedidos){const ctx=document.getElementById('chartDiario').getContext('2d');if(chartDia)chartDia.destroy();const pd={};pedidos.forEach(p=>{if(!pd[p.data])pd[p.data]=0;pd[p.data]+=p.valor;});const todasDatas=Object.keys(pd).sort();const datasCompletas=[];if(todasDatas.length>0){const ini=new Date(todasDatas[0]+'T00:00:00');const fim=new Date(todasDatas[todasDatas.length-1]+'T00:00:00');const d=new Date(ini);while(d&lt;=fim){datasCompletas.push(d.toISOString().split('T')[0]);d.setDate(d.getDate()+1);}}const valores=datasCompletas.map(d=>pd[d]||0);const g=ctx.createLinearGradient(0,0,0,320);g.addColorStop(0,'rgba(37,99,235,0.3)');g.addColorStop(1,'rgba(37,99,235,0.02)');chartDia=new Chart(ctx,{type:'line',data:{labels:datasCompletas.map(fmtData),datasets:[{label:'Faturamento',data:valores,borderColor:'#2563eb',backgroundColor:g,borderWidth:3,fill:true,tension:0.3,pointRadius:4,pointBackgroundColor:'#2563eb',pointHoverRadius:7}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>'Faturamento: '+fmtMoeda(c.raw)}}},scales:{y:{ticks:{callback:v=>'R$ '+v.toLocaleString('pt-BR')}}}}});}
function renderChartDonut(v,fatTotal){const ctx=document.getElementById('chartDonut').getContext('2d');if(chartDonut)chartDonut.destroy();chartDonut=new Chart(ctx,{type:'doughnut',data:{labels:v.map(x=>fmtNome(x.nome)),datasets:[{data:v.map(x=>x.faturamento),backgroundColor:v.map((_,i)=>CORES[i%CORES.length]),borderColor:'#fff',borderWidth:3}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'right',labels:{padding:16,font:{size:13}}},tooltip:{callbacks:{label:c=>{const pct=((c.raw/fatTotal)*100).toFixed(1);return c.label+': '+fmtMoeda(c.raw)+' ('+pct+'%)';}}}}}});}
function renderTabela(v,fatTotal){let html='';v.forEach((x,i)=>{const pct=fatTotal>0?(x.faturamento/fatTotal*100):0;const t=x.vendas>0?x.faturamento/x.vendas:0;const meta=METAS[x.nome.toUpperCase()]||0;const pm=meta>0?(x.faturamento/meta*100):0;const cor=CORES[i%CORES.length];const cm=pm>=100?'#16a34a':pm>=70?'#f59e0b':'#dc2626';html+='<tr><td class="vendedor-name"><span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:'+cor+';margin-right:8px;"></span>'+fmtNome(x.nome)+'</td><td class="valor-cell">'+fmtMoeda(x.faturamento)+'</td><td>'+x.vendas+'</td><td>'+fmtMoeda(t)+'</td><td>'+(meta>0?fmtMoeda(meta):'<span style="color:var(--text-muted)">—</span>')+'</td><td><span class="pct-bar"><span class="pct-fill" style="width:'+Math.min(pm,100)+'%;background:'+cm+'"></span></span><strong style="color:'+cm+'">'+pm.toFixed(0)+'%</strong></td><td><span class="pct-bar"><span class="pct-fill" style="width:'+pct+'%;background:'+cor+'"></span></span>'+pct.toFixed(1)+'%</td></tr>';});document.getElementById('tabelaBody').innerHTML=html;}
function mostrarSemDados(){document.getElementById('kpiGrid').innerHTML='<div class="no-data">⚠️ Nenhum pedido no período.</div>';document.getElementById('metaGrid').innerHTML='';document.getElementById('tabelaBody').innerHTML='';if(chartVend)chartVend.destroy();if(chartDia)chartDia.destroy();if(chartDonut)chartDonut.destroy();}
function fmtMoeda(v){return 'R$ '+Number(v).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});}
function fmtData(iso){const[y,m,d]=iso.split('-');return d+'/'+m;}
function contarDias(ini,fim){const d1=new Date(ini+'T00:00:00');const d2=new Date(fim+'T00:00:00');return Math.round((d2-d1)/86400000)+1;}
function formatarMes(mr){const[ano,mes]=mr.split('-');const n=['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'];return n[parseInt(mes)-1]+' '+ano;}
__AUTO_RELOAD__
document.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.type==='date')aplicarFiltro();});
window.addEventListener('DOMContentLoaded',init);
</script>
</body>
</html>'''

    if fase == "1":
        html = html.replace("__AUTO_RELOAD__", "setTimeout(function(){location.reload();},15000);")
    else:
        html = html.replace("__AUTO_RELOAD__", "")

    html = html.replace("__DADOS_JSON__", dados_json)
    html = html.replace("__METAS_JSON__", metas_json)
    html = html.replace("__DATA_GERACAO__", data_geracao)
    html = html.replace("__MIN_DATA__", min_data)
    html = html.replace("__MAX_DATA__", max_data)
    html = html.replace("__BANNER_FASE__", banner)
    return html

# ── PÁGINA DE BOAS-VINDAS
def gerar_pagina_boas_vindas():
    return r'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dashboard Corporativo</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 50%,#2563eb 100%);
color:#fff;min-height:100vh;display:flex;align-items:center;justify-content:center;padding:20px;}
.container{max-width:800px;text-align:center;}
.logo{width:80px;height:80px;background:rgba(255,255,255,.15);border-radius:20px;
display:flex;align-items:center;justify-content:center;font-size:36px;margin:0 auto 24px;
backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,.2);}
h1{font-size:32px;font-weight:700;margin-bottom:12px;}
.subtitle{font-size:16px;opacity:.8;margin-bottom:32px;line-height:1.6;}
.spinner{border:4px solid rgba(255,255,255,.2);border-top:4px solid #fff;
border-radius:50%;width:48px;height:48px;animation:spin 1s linear infinite;margin:0 auto 16px;}
@keyframes spin{0%{transform:rotate(0)}100%{transform:rotate(360deg)}}
.loading-text{font-size:15px;opacity:.9;}
.loading-sub{font-size:13px;opacity:.6;margin-top:4px;}
.footer{margin-top:40px;font-size:12px;opacity:.5;}
</style>
</head>
<body><div class="container">
<div class="logo">📊</div>
<h1>Dashboard Corporativo</h1>
<p class="subtitle">Sistema de gestão de vendas e metas<br>Acompanhamento em tempo real do faturamento</p>
<div class="spinner"></div>
<div class="loading-text">Carregando dados...</div>
<div class="loading-sub">Buscando pedidos na API Vhsys</div>
<div class="footer">© 2026 • Integração Vhsys API v2</div>
</div>
<script>
async function verificar(){try{const r=await fetch('/status');const d=await r.json();
if(d.ready){window.location.href='/dash';}}catch(e){}}
setInterval(verificar,5000);verificar();
</script>
</body></html>'''

# ── FASES DE CARREGAMENTO
def gerar_fase1():
    hoje = date.today()
    data_fim = hoje.isoformat()
    data_inicio = (hoje - timedelta(days=90)).isoformat()
    print(f"[FASE 1] {data_inicio} a {data_fim}")
    pedidos_brutos = listar_pedidos_periodo(data_inicio, data_fim)
    pedidos = processar_pedidos(pedidos_brutos)
    with open(DADOS_JSON, "w", encoding="utf-8") as f:
        json.dump(pedidos, f, ensure_ascii=False, indent=2)
    html = gerar_dashboard_html(pedidos, fase="1")
    with open(DASHBOARD_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[FASE 1] OK: {len(pedidos)} pedidos")

def gerar_fase2():
    hoje = date.today()
    data_fim_fase2 = (hoje - timedelta(days=91)).isoformat()
    data_inicio_ano = f"{hoje.year}-01-01"
    print(f"[FASE 2] {data_inicio_ano} a {data_fim_fase2}")
    pedidos_brutos_fase2 = listar_pedidos_periodo(data_inicio_ano, data_fim_fase2)
    pedidos_fase2 = processar_pedidos(pedidos_brutos_fase2)
    pedidos_fase1 = []
    if DADOS_JSON.exists():
        with open(DADOS_JSON, "r", encoding="utf-8") as f:
            pedidos_fase1 = json.load(f)
    ids_existentes = set(p.get("id", "") for p in pedidos_fase1)
    pedidos_mesclados = list(pedidos_fase1)
    for p in pedidos_fase2:
        if p.get("id", "") not in ids_existentes:
            pedidos_mesclados.append(p)
    print(f"[FASE 2] Mesclagem: {len(pedidos_fase1)} + {len(pedidos_fase2)} = {len(pedidos_mesclados)}")
    with open(DADOS_JSON, "w", encoding="utf-8") as f:
        json.dump(pedidos_mesclados, f, ensure_ascii=False, indent=2)
    html = gerar_dashboard_html(pedidos_mesclados, fase="2")
    with open(DASHBOARD_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[FASE 2] OK: {len(pedidos_mesclados)} pedidos")

# ── FLASK APP (sem rotas duplicadas!)
app = Flask(__name__)
fase1_pronta = False
fase2_pronta = False

@app.route('/')
def pagina_inicial():
    """Página de boas-vindas OU dashboard se já pronto."""
    global fase1_pronta
    if fase1_pronta and DASHBOARD_HTML.exists():
        return send_file(str(DASHBOARD_HTML))
    return gerar_pagina_boas_vindas()

@app.route('/dash')
def ver_dashboard():
    """Serve o dashboard diretamente."""
    if DASHBOARD_HTML.exists():
        return send_file(str(DASHBOARD_HTML))
    return gerar_pagina_boas_vindas()

@app.route('/status')
def verificar_status():
    global fase1_pronta, fase2_pronta
    return jsonify({"ready": fase1_pronta, "fase2": fase2_pronta})

@app.route('/atualizar')
def forcar_atualizacao():
    global fase1_pronta, fase2_pronta
    fase1_pronta = False
    fase2_pronta = False
    def rodar():
        global fase1_pronta, fase2_pronta
        try:
            gerar_fase1()
            fase1_pronta = True
            print("[BG] Fase 1 OK")
            gerar_fase2()
            fase2_pronta = True
            print("[BG] Fase 2 OK")
        except Exception as e:
            print(f"[BG] ERRO: {e}")
            traceback.print_exc()
    threading.Thread(target=rodar, daemon=True).start()
    return gerar_pagina_boas_vindas()

@app.route('/health')
def health_check():
    return jsonify({"status": "ok"})

# ── INICIALIZAÇÃO EM BACKGROUND (FORA do if __name__)
def iniciar_background():
    global fase1_pronta, fase2_pronta
    threading.Event().wait(3)
    if DASHBOARD_HTML.exists() and DADOS_JSON.exists():
        print("[INIT] Dashboard já existe.")
        fase1_pronta = True
        try:
            with open(DADOS_JSON, "r", encoding="utf-8") as f:
                dados = json.load(f)
            if len(dados) > 1000:
                print("[INIT] Dados completos. Fase 2 também pronta.")
                fase2_pronta = True
                return
        except:
            pass
    try:
        if not fase1_pronta:
            print("[BG] Fase 1...")
            gerar_fase1()
            fase1_pronta = True
        if not fase2_pronta:
            print("[BG] Fase 2...")
            gerar_fase2()
            fase2_pronta = True
    except Exception as e:
        print(f"[BG] ERRO: {e}")
        traceback.print_exc()

# ESTA LINHA RODA SEMPRE (gunicorn ou python direto)
threading.Thread(target=iniciar_background, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"[FLASK] Porta {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
