import os, sys, json, re, threading, traceback
from datetime import datetime, date, timedelta
from pathlib import Path
from calendar import monthrange
import requests
from flask import Flask, send_file, jsonify

BASE_URL = "https://api.vhsys.com/v2"
ACCESS_TOKEN = "YYeHeFaNAfVfLegOLXedMFZMLNPLQT"
SECRET_TOKEN = "k9Qhe0oaSAchTjWgpvLeUvxmZcyLVfO"

OUTPUT_DIR = Path(__file__).resolve().parent
DADOS_JSON = OUTPUT_DIR / "vhsys_dados_pedidos.json"
DASHBOARD_HTML = OUTPUT_DIR / "dashboard_vhsys.html"
FLAG_FASE1 = OUTPUT_DIR / "fase1.flag"
FLAG_FASE2 = OUTPUT_DIR / "fase2.flag"

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
    s = str(nome)
    s = s.replace('\xa0', ' ').replace('\t', ' ').replace('\n', ' ').replace('\r', ' ')
    s = ' '.join(s.split())
    s = s.upper()
    return s if s else "SEM VENDEDOR"

def listar_pedidos_periodo(data_inicio, data_fim):
    todos = []
    offset = 0
    limit = 250
    pagina = 1
    max_paginas = 200
    print(f"[API] Buscando {data_inicio} a {data_fim}...")
    while pagina <= max_paginas:
        params = {"limit": limit, "offset": offset, "order": "data_pedido", "sort": "Desc"}
        try:
            resp = requests.get(f"{BASE_URL}/pedidos/", headers=HEADERS_BASE, params=params, timeout=30)
        except requests.RequestException as e:
            print(f"  ERRO pag {pagina}: {e}")
            break
        if resp.status_code == 403:
            break
        if resp.status_code != 200:
            print(f"  ERRO Status {resp.status_code}")
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
                if dp < data_inicio:
                    pedidos_antes += 1
        dmin = min(datas_pagina) if datas_pagina else "?"
        dmax = max(datas_pagina) if datas_pagina else "?"
        print(f"  Pag {pagina}: {len(lote)} | {dmin} a {dmax} | antes:{pedidos_antes} | total:{len(todos)}")
        if pedidos_antes > 0:
            break
        offset += limit
        pagina += 1
    filtrados = []
    for p in todos:
        if not isinstance(p, dict):
            continue
        dp = normalizar_data(p.get("data_pedido", ""))
        if dp and dp != "0000-00-00" and data_inicio <= dp and dp <= data_fim:
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

def gerar_fase1():
    hoje = date.today()
    data_fim = hoje.isoformat()
    data_inicio = (hoje - timedelta(days=90)).isoformat()
    print(f"[F1] {data_inicio} a {data_fim}")
    pedidos = processar_pedidos(listar_pedidos_periodo(data_inicio, data_fim))
    with open(DADOS_JSON, "w", encoding="utf-8") as f:
        json.dump(pedidos, f, ensure_ascii=False, indent=2)
    html = gerar_dashboard_html(pedidos, 1)
    with open(DASHBOARD_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    FLAG_FASE1.touch()
    print(f"[F1] OK: {len(pedidos)} pedidos")

def gerar_fase2():
    hoje = date.today()
    ano = hoje.year
    data_fim_f2 = (hoje - timedelta(days=91)).isoformat()
    data_ini_f2 = f"{ano}-01-01"
    print(f"[F2] {data_ini_f2} a {data_fim_f2}")
    pedidos_f2 = processar_pedidos(listar_pedidos_periodo(data_ini_f2, data_fim_f2))
    pedidos_f1 = []
    if DADOS_JSON.exists():
        with open(DADOS_JSON, "r", encoding="utf-8") as f:
            pedidos_f1 = json.load(f)
    ids_existentes = set(p.get("id", "") for p in pedidos_f1)
    mesclados = list(pedidos_f1)
    for p in pedidos_f2:
        if p.get("id", "") not in ids_existentes:
            mesclados.append(p)
    print(f"[F2] Mescla: {len(pedidos_f1)} + {len(pedidos_f2)} = {len(mesclados)}")
    with open(DADOS_JSON, "w", encoding="utf-8") as f:
        json.dump(mesclados, f, ensure_ascii=False, indent=2)
    html = gerar_dashboard_html(mesclados, 2)
    with open(DASHBOARD_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    FLAG_FASE2.touch()
    print(f"[F2] OK: {len(mesclados)} pedidos")

def gerar_dashboard_html(pedidos, fase=2):
    dados_json = json.dumps(pedidos, ensure_ascii=False)
    metas_upper = {k.upper(): v for k, v in METAS_MENSAIS.items()}
    metas_json = json.dumps(metas_upper, ensure_ascii=False)
    data_geracao = datetime.now().strftime("%d/%m/%Y as %H:%M:%S")
    if fase == 1:
        banner = '<div style="background:#fef3c7;color:#92400e;padding:8px 16px;font-size:13px;text-align:center;">Dados parciais (3 meses). Carregando ano completo...</div>'
        auto_reload = "setTimeout(function(){location.reload();},15000);"
    else:
        banner = '<div style="background:#dcfce7;color:#16a34a;padding:8px 16px;font-size:13px;text-align:center;">Dados completos do ano carregados.</div>'
        auto_reload = ""
    if pedidos:
        datas = sorted([p["data"] for p in pedidos if p["data"]])
        min_data = datas[0] if datas else date.today().isoformat()
        max_data = datas[-1] if datas else date.today().isoformat()
    else:
        min_data = date.today().replace(day=1).isoformat()
        max_data = date.today().isoformat()
    html = '''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dashboard de Faturamento</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
:root{--bg:#f0f2f5;--card-bg:#fff;--primary:#2563eb;--primary-light:#dbeafe;--green:#16a34a;--green-light:#dcfce7;--amber:#f59e0b;--amber-light:#fef3c7;--red:#dc2626;--red-light:#fee2e2;--text:#1e293b;--text-muted:#64748b;--border:#e2e8f0;--shadow:0 1px 3px rgba(0,0,0,.1),0 1px 2px rgba(0,0,0,.06);--shadow-lg:0 4px 6px rgba(0,0,0,.07),0 2px 4px rgba(0,0,0,.06);--radius:12px;}
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;}
.header{background:linear-gradient(135deg,#1e3a5f 0%,#2563eb 100%);color:#fff;padding:24px 32px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;}
.header h1{font-size:24px;font-weight:700;}
.header .subtitle{font-size:13px;opacity:.85;margin-top:4px;}
.header .updated{font-size:12px;opacity:.7;margin-top:8px;}
.btn-refresh{background:rgba(255,255,255,.2);color:#fff;border:1px solid rgba(255,255,255,.4);padding:8px 16px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;text-decoration:none;}
.btn-refresh:hover{background:rgba(255,255,255,.3);}
.container{max-width:1400px;margin:0 auto;padding:24px;}
.filter-bar{background:var(--card-bg);border-radius:var(--radius);box-shadow:var(--shadow);padding:20px 24px;margin-bottom:24px;display:flex;align-items:center;gap:16px;flex-wrap:wrap;}
.filter-group{display:flex;align-items:center;gap:8px;}
.filter-group label{font-size:13px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;}
.filter-group input[type="date"]{padding:8px 12px;border:2px solid var(--border);border-radius:8px;font-size:14px;color:var(--text);outline:none;}
.filter-group input[type="date"]:focus{border-color:var(--primary);}
.btn-apply{background:var(--primary);color:#fff;border:none;padding:9px 24px;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;}
.btn-apply:hover{background:#1d4ed8;}
.btn-preset{background:var(--primary-light);color:var(--primary);border:none;padding:7px 14px;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer;}
.btn-preset:hover{background:var(--primary);color:#fff;}
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:24px;}
.kpi-card{background:var(--card-bg);border-radius:var(--radius);box-shadow:var(--shadow);padding:20px 24px;border-left:4px solid var(--primary);}
.kpi-card.green{border-left-color:var(--green);}.kpi-card.amber{border-left-color:var(--amber);}.kpi-card.purple{border-left-color:#8b5cf6;}
.kpi-label{font-size:12px;font-weight:600;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px;}
.kpi-value{font-size:26px;font-weight:700;color:var(--text);}
.kpi-sub{font-size:12px;color:var(--text-muted);margin-top:4px;}
.meta-section-title{font-size:18px;font-weight:700;margin-bottom:16px;color:var(--text);display:flex;align-items:center;gap:8px;}
.meta-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px;margin-bottom:24px;}
.meta-card{background:var(--card-bg);border-radius:var(--radius);box-shadow:var(--shadow);padding:20px 22px;}
.meta-header{display:flex;align-items:center;gap:12px;margin-bottom:14px;}
.meta-avatar{width:42px;height:42px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:700;color:#fff;flex-shrink:0;}
.meta-name{font-size:15px;font-weight:700;color:var(--text);}
.meta-sub{font-size:12px;color:var(--text-muted);margin-top:2px;}
.meta-progress-bar{background:var(--border);border-radius:12px;height:28px;overflow:hidden;margin-bottom:10px;}
.meta-progress-fill{height:100%;border-radius:12px;display:flex;align-items:center;padding-left:12px;color:#fff;font-size:12px;font-weight:700;min-width:0;}
.meta-stats{display:flex;justify-content:space-between;align-items:center;font-size:13px;}
.meta-valor{font-weight:700;font-size:16px;}
.meta-valor.atingido{color:var(--green);}
.meta-status{padding:4px 10px;border-radius:6px;font-size:11px;font-weight:700;text-transform:uppercase;}
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
.table-card th{text-align:left;padding:12px 14px;font-size:12px;font-weight:700;color:var(--text-muted);text-transform:uppercase;border-bottom:2px solid var(--border);}
.table-card td{padding:12px 14px;font-size:14px;border-bottom:1px solid var(--border);}
.table-card tr:last-child td{border-bottom:none;}
.vendedor-name{font-weight:600;}
.valor-cell{font-weight:600;color:var(--green);}
.pct-bar{background:var(--border);border-radius:6px;height:8px;width:80px;overflow:hidden;display:inline-block;vertical-align:middle;margin-right:8px;}
.pct-fill{height:100%;border-radius:6px;}
.no-data{text-align:center;padding:48px;color:var(--text-muted);font-size:16px;}
.footer{text-align:center;padding:24px;color:var(--text-muted);font-size:12px;border-top:1px solid var(--border);margin-top:24px;}
</style>
</head>
<body>
<div class="header">
<div>
<h1>Dashboard de Faturamento &amp; Metas</h1>
<div class="subtitle">Vendas por vendedora - Vhsys API v2</div>
<div class="updated">Dados gerados em: ''' + data_geracao + '''</div>
</div>
<a href="/atualizar" class="btn-refresh">Atualizar</a>
</div>
''' + banner + '''
<div class="container">
<div class="filter-bar">
<div class="filter-group"><label>Inicial</label><input type="date" id="dataInicio" value="''' + min_data + '''"></div>
<div class="filter-group"><label>Final</label><input type="date" id="dataFim" value="''' + max_data + '''"></div>
<button class="btn-apply" onclick="aplicarFiltro()">Aplicar</button>
<div style="margin-left:auto;display:flex;gap:8px;flex-wrap:wrap;">
<button class="btn-preset" onclick="presetHoje()">Hoje</button>
<button class="btn-preset" onclick="preset7()">7 dias</button>
<button class="btn-preset" onclick="presetMesAtual()">Mes</button>
<button class="btn-preset" onclick="presetAnoAtual()">Ano</button>
<button class="btn-preset" onclick="presetTudo()">Tudo</button>
</div>
</div>
<div class="kpi-grid" id="kpiGrid"></div>
<div id="metaSection"><div class="meta-section-title">Metas Mensais - <span id="mesMetaLabel"></span></div><div class="meta-grid" id="metaGrid"></div></div>
<div class="charts-grid">
<div class="chart-card"><div class="chart-title">Faturamento por Vendedora</div><div class="chart-wrapper"><canvas id="chartVendedor"></canvas></div></div>
<div class="chart-card"><div class="chart-title">Faturamento Diario</div><div class="chart-wrapper"><canvas id="chartDiario"></canvas></div></div>
<div class="chart-card full"><div class="chart-title">Participacao</div><div class="chart-wrapper"><canvas id="chartDonut"></canvas></div></div>
</div>
<div class="table-card"><div class="chart-title">Detalhamento</div>
<table><thead><tr><th>Vendedora</th><th>Faturamento</th><th>Vendas</th><th>Ticket</th><th>Meta</th><th>% Meta</th><th>% Total</th></tr></thead>
<tbody id="tabelaBody"></tbody></table>
</div>
</div>
<div class="footer">
(c) 2026 Real Mais - Sistema integrado Vhsys API v2<br>
Dashboard Corporativo - Acompanhamento de vendas e metas em tempo real
</div>
<script>
var PEDIDOS = ''' + dados_json + ''';
var METAS = ''' + metas_json + ''';
var CORES = ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#14b8a6','#f97316','#6366f1','#84cc16','#06b6d4','#a855f7'];
var chartV=null,chartD=null,chartDN=null;
function fmtN(n){if(!n)return 'Sem vendedor';if(n.toUpperCase()==='SEM VENDEDOR')return 'Sem vendedor';return n.split(' ').map(function(w){return w.charAt(0).toUpperCase()+w.slice(1).toLowerCase()}).join(' ');}
function init(){aplicarFiltro();}
function presetHoje(){var h=new Date().toISOString().split('T')[0];setD(h,h);}
function preset7(){var f=new Date();var i=new Date();i.setDate(i.getDate()-6);setD(i.toISOString().split('T')[0],f.toISOString().split('T')[0]);}
function presetMesAtual(){var a=new Date();var i=new Date(a.getFullYear(),a.getMonth(),1);var f=new Date(a.getFullYear(),a.getMonth()+1,0);setD(i.toISOString().split('T')[0],f.toISOString().split('T')[0]);}
function presetAnoAtual(){var a=new Date();setD(a.getFullYear()+'-01-01',a.toISOString().split('T')[0]);}
function presetTudo(){setD("''' + min_data + '''","''' + max_data + '''");}
function setD(i,f){document.getElementById('dataInicio').value=i;document.getElementById('dataFim').value=f;aplicarFiltro();}
function aplicarFiltro(){var i=document.getElementById('dataInicio').value;var f=document.getElementById('dataFim').value;if(!i||!f)return;var ps=PEDIDOS.filter(function(p){return p.data>=i&&p.data<=f});var mr=f.substring(0,7);document.getElementById('mesMetaLabel').textContent=fmtMes(mr);if(ps.length===0){document.getElementById('kpiGrid').innerHTML='<div class="no-data">Sem pedidos.</div>';document.getElementById('metaGrid').innerHTML='';document.getElementById('tabelaBody').innerHTML='';return;}var pv={};ps.forEach(function(p){var v=(p.vendedor||'SEM VENDEDOR').toUpperCase().replace(/\s+/g,' ').trim();if(!pv[v])pv[v]={nome:v,fat:0,ven:0};pv[v].fat+=p.valor;pv[v].ven+=1;});var vs=Object.values(pv).sort(function(a,b){return b.fat-a.fat});vs.forEach(function(v){v.fat=Math.round(v.fat*100)/100});var ft=vs.reduce(function(s,v){return s+v.fat},0);var qv=vs.reduce(function(s,v){return s+v.ven},0);var tm=qv>0?ft/qv:0;var dp=Math.round((new Date(f+'T00:00:00')-new Date(i+'T00:00:00'))/86400000)+1;document.getElementById('kpiGrid').innerHTML='<div class="kpi-card"><div class="kpi-label">Faturamento</div><div class="kpi-value">'+fmtM(ft)+'</div><div class="kpi-sub">'+dp+' dia(s)</div></div><div class="kpi-card green"><div class="kpi-label">Vendas</div><div class="kpi-value">'+qv+'</div><div class="kpi-sub">nao cancelados</div></div><div class="kpi-card amber"><div class="kpi-label">Ticket</div><div class="kpi-value">'+fmtM(tm)+'</div><div class="kpi-sub">por venda</div></div><div class="kpi-card purple"><div class="kpi-label">Vendedoras</div><div class="kpi-value">'+vs.length+'</div><div class="kpi-sub">ativas</div></div>';renderMetas(vs,mr);renderCharts(vs,ps,ft);renderTab(vs,ft);}
function renderMetas(vs,mr){var html='';var ncv=new Set(vs.map(function(v){return v.nome.toUpperCase()}));var todos=vs.slice();Object.keys(METAS).forEach(function(n){if(!ncv.has(n.toUpperCase()))todos.push({nome:n.toUpperCase(),fat:0,ven:0})});todos.sort(function(a,b){var ma=METAS[a.nome.toUpperCase()]||0;var mb=METAS[b.nome.toUpperCase()]||0;var pa=ma>0?a.fat/ma:0;var pb=mb>0?b.fat/mb:0;return pb-pa});todos.forEach(function(v,i){var meta=METAS[v.nome.toUpperCase()]||0;var cor=CORES[i%CORES.length];var ini=v.nome.split(' ').map(function(p){return p[0]}).join('').substring(0,2).toUpperCase();var pm=meta>0?(v.fat/meta*100):0;var pb=Math.min(pm,100);var sc,st,cb;if(meta===0){sc='status-semmeta';st='Sem meta';cb='#94a3b8'}else if(pm>=100){sc='status-bateu';st='Meta';cb='#16a34a'}else if(pm>=70){sc='status-perto';st='Quase';cb='#f59e0b'}else{sc='status-longe';st='Progresso';cb='#dc2626'}var fal=meta>0?Math.max(meta-v.fat,0):0;var t=v.ven>0?v.fat/v.ven:0;var tf='';if(meta>0&&pm<100){tf='Faltam '+fmtM(fal);if(t>0)tf+=' - aprox '+Math.ceil(fal/t)+' venda(s)'}html+='<div class="meta-card"><div class="meta-header"><div class="meta-avatar" style="background:'+cor+'">'+ini+'</div><div><div class="meta-name">'+fmtN(v.nome)+'</div><div class="meta-sub">'+v.ven+' venda(s) - Ticket: '+fmtM(t)+'</div></div></div><div class="meta-progress-bar"><div class="meta-progress-fill" style="width:'+pb+'%;background:'+cb+'">'+pm.toFixed(0)+'%</div></div><div class="meta-stats"><div><span class="meta-valor">'+fmtM(v.fat)+'</span> / '+(meta>0?fmtM(meta):'--')+'</div><span class="meta-status '+sc+'">'+st+'</span></div>'+(tf?'<div class="meta-falta">'+tf+'</div>':'')+'</div>'});document.getElementById('metaGrid').innerHTML=html;}
function renderCharts(vs,ps,ft){var c1=document.getElementById('chartVendedor').getContext('2d');if(chartV)chartV.destroy();chartV=new Chart(c1,{type:'bar',data:{labels:vs.map(function(x){return fmtN(x.nome)}),datasets:[{data:vs.map(function(x){return x.fat}),backgroundColor:vs.map(function(_,i){return CORES[i%CORES.length]+'cc'}),borderColor:vs.map(function(_,i){return CORES[i%CORES.length]}),borderWidth:2,borderRadius:6}]},options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:function(c){return fmtM(c.raw)}}}},scales:{x:{ticks:{callback:function(v){return 'R$ '+v.toLocaleString('pt-BR')}}}}}});var c2=document.getElementById('chartDiario').getContext('2d');if(chartD)chartD.destroy();var pd={};ps.forEach(function(p){if(!pd[p.data])pd[p.data]=0;pd[p.data]+=p.valor});var tds=Object.keys(pd).sort();var dc=[];if(tds.length>0){var di=new Date(tds[0]+'T00:00:00');var df=new Date(tds[tds.length-1]+'T00:00:00');var d=new Date(di);while(d<=df){dc.push(d.toISOString().split('T')[0]);d.setDate(d.getDate()+1)}}var vals=dc.map(function(d){return pd[d]||0});var g=c2.createLinearGradient(0,0,0,320);g.addColorStop(0,'rgba(37,99,235,0.3)');g.addColorStop(1,'rgba(37,99,235,0.02)');chartD=new Chart(c2,{type:'line',data:{labels:dc.map(fmtData),datasets:[{data:vals,borderColor:'#2563eb',backgroundColor:g,borderWidth:3,fill:true,tension:0.3,pointRadius:4,pointBackgroundColor:'#2563eb'}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:function(c){return fmtM(c.raw)}}}},scales:{y:{ticks:{callback:function(v){return 'R$ '+v.toLocaleString('pt-BR')}}}}}});var c3=document.getElementById('chartDonut').getContext('2d');if(chartDN)chartDN.destroy();chartDN=new Chart(c3,{type:'doughnut',data:{labels:vs.map(function(x){return fmtN(x.nome)}),datasets:[{data:vs.map(function(x){return x.fat}),backgroundColor:vs.map(function(_,i){return CORES[i%CORES.length]}),borderColor:'#fff',borderWidth:3}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'right',labels:{padding:16,font:{size:13}}},tooltip:{callbacks:{label:function(c){var pct=((c.raw/ft)*100).toFixed(1);return c.label+': '+fmtM(c.raw)+' ('+pct+'%)'}}}}}});}
function renderTab(vs,ft){var html='';vs.forEach(function(x,i){var pct=ft>0?(x.fat/ft*100):0;var t=x.ven>0?x.fat/x.ven:0;var meta=METAS[x.nome.toUpperCase()]||0;var pm=meta>0?(x.fat/meta*100):0;var cor=CORES[i%CORES.length];var cm=pm>=100?'#16a34a':pm>=70?'#f59e0b':'#dc2626';html+='<tr><td class="vendedor-name">'+fmtN(x.nome)+'</td><td class="valor-cell">'+fmtM(x.fat)+'</td><td>'+x.ven+'</td><td>'+fmtM(t)+'</td><td>'+(meta>0?fmtM(meta):'--')+'</td><td>'+pm.toFixed(0)+'%</td><td>'+pct.toFixed(1)+'%</td></tr>'});document.getElementById('tabelaBody').innerHTML=html;}
function fmtM(v){return 'R$ '+Number(v).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})}
function fmtData(iso){var p=iso.split('-');return p[2]+'/'+p[1]}
function fmtMes(mr){var p=mr.split('-');var n=['Janeiro','Fevereiro','Marco','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'];return n[parseInt(p[1])-1]+' '+p[0]}
''' + auto_reload + '''
document.addEventListener('keydown',function(e){if(e.key==='Enter'&&e.target.type==='date')aplicarFiltro()});
window.addEventListener('DOMContentLoaded',init);
</script>
</body>
</html>'''
    return html

def gerar_boas_vindas():
    return '''<!DOCTYPE html>
<html lang="pt-BR"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Dashboard - Real Mais</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:sans-serif;background:linear-gradient(135deg,#0f172a,#1e3a5f,#2563eb);color:#fff;min-height:100vh;display:flex;align-items:center;justify-content:center}
.c{text-align:center}.l{width:80px;height:80px;background:rgba(255,255,255,.15);border-radius:20px;display:flex;align-items:center;justify-content:center;font-size:36px;margin:0 auto 24px}
h1{font-size:32px;margin-bottom:12px}
p{opacity:.8;margin-bottom:32px}
.s{border:4px solid rgba(255,255,255,.2);border-top:4px solid #fff;border-radius:50%;width:48px;height:48px;animation:sp 1s linear infinite;margin:0 auto 16px}
@keyframes sp{100%{transform:rotate(360deg)}}
.f{margin-top:40px;font-size:12px;opacity:.5}
</style></head><body><div class="c">
<div class="l">📊</div>
<h1>Dashboard Corporativo</h1>
<p>Carregando dados da API Vhsys...</p>
<div class="s"></div>
<div class="f">(c) 2026 Real Mais - Vhsys API v2</div>
</div>
<script>
async function v(){try{var r=await fetch('/status');var d=await r.json();if(d.ready)window.location.href='/'}catch(e){}}
setInterval(v,5000);v();
</script>
</body></html>'''

app = Flask(__name__)

@app.route('/')
def raiz():
    # SEM variaveis globais - usa ARQUIVO como sinal (compativel com gunicorn multi-worker)
    if DASHBOARD_HTML.exists():
        return send_file(str(DASHBOARD_HTML))
    return gerar_boas_vindas()

@app.route('/dash')
def painel():
    if DASHBOARD_HTML.exists():
        return send_file(str(DASHBOARD_HTML))
    return gerar_boas_vindas()

@app.route('/status')
def checar():
    # SEM variaveis globais - checa se o arquivo existe no disco
    return jsonify({
        "ready": DASHBOARD_HTML.exists(),
        "fase1": FLAG_FASE1.exists(),
        "fase2": FLAG_FASE2.exists()
    })

@app.route('/atualizar')
def refresh():
    # Apagar flags e HTML antigo
    for f in [FLAG_FASE1, FLAG_FASE2, DASHBOARD_HTML]:
        if f.exists():
            f.unlink()

    def rodar():
        try:
            gerar_fase1()
            print("[BG] F1 OK")
            gerar_fase2()
            print("[BG] F2 OK")
        except Exception as e:
            print(f"[BG] ERRO: {e}")
            traceback.print_exc()
    threading.Thread(target=rodar, daemon=True).start()
    return gerar_boas_vindas()

@app.route('/health')
def saude():
    return jsonify({"status": "ok", "dashboard": DASHBOARD_HTML.exists()})

# Lock para evitar que multiplos workers rodem a busca ao mesmo tempo
_lock = threading.Lock()
_buscando = False

def iniciar():
    global _buscando
    threading.Event().wait(3)

    # Se ja tem dashboard pronto, nao fazer nada
    if DASHBOARD_HTML.exists() and FLAG_FASE2.exists():
        print("[INIT] Dashboard completo ja existe.")
        return

    # Se ja tem fase 1, so fazer fase 2
    if DASHBOARD_HTML.exists() and FLAG_FASE1.exists() and not FLAG_FASE2.exists():
        print("[INIT] Fase 1 ja existe. Buscando fase 2...")
        try:
            gerar_fase2()
        except Exception as e:
            print(f"[INIT] ERRO F2: {e}")
            traceback.print_exc()
        return

    # Se nao tem nada, fazer as 2 fases
    with _lock:
        if _buscando:
            print("[INIT] Outro worker ja esta buscando. Aguardando...")
            return
        _buscando = True

    try:
        print("[BG] Fase 1...")
        gerar_fase1()
        print("[BG] Fase 2...")
        gerar_fase2()
    except Exception as e:
        print(f"[BG] ERRO: {e}")
        traceback.print_exc()
    finally:
        with _lock:
            _buscando = False

threading.Thread(target=iniciar, daemon=True).start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
