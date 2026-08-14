#!/usr/bin/env python3
"""
dash_flask_ofc.py  (v5 - abas Comercial/Logistica/Contabil + logo Real Aciai)
"""
import os, sys, json, csv, io, re, time, threading
from datetime import datetime, date
from calendar import monthrange
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

EMPRESAS = [
    {"nome": "REAL MAIS", "access_token": "YYeHeFaNAfVfLegOLXedMFZMLNPLQT", "secret_token": "k9Qhe0oaSAchTjWgpvLeUvxmZcyLVfO", "endpoint": "/pedidos/", "data_field": "data_pedido", "order_field": "data_pedido"},
    {"nome": "GP DISTRIBUIDORA", "access_token": "EdPfRWCOGgefDeVcSNNaGJLJeZDMST", "secret_token": "5P4nmO1ONthN5oqfX81lHKX5i0YC3dm", "endpoint": "/vendas-balcao/", "data_field": "data_cad_pedido", "order_field": "data_cad_pedido"},
]

BASE_URL = "https://api.vhsys.com/v2"
STATUS_EXCLUIDOS = {"Cancelado"}
SPREADSHEET_ID = "10rPC_-MxKm6o0L1SjHanXuKm0LjEIezjhoclNPlzpfc"

_metas_lock = threading.Lock()
_metas = {"Simone Moura": 215000.00, "Isa": 241500.00, "Ana Ruth": 65000.00, "GP DISTRIBUIDORA": 100000.00}
_metas_consolidada = 1005277.76
CORES = ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#14b8a6','#f97316','#6366f1','#84cc16','#06b6d4','#a855f7']
CACHE_TEMPO_SEGUNDOS = 1800
_cache_lock = threading.Lock()
_cache = {"timestamp": 0, "html": "", "erro": "", "buscando": False}
_cmv_cache = {"timestamp": 0, "data": None, "calculando": False, "params": ""}
_cmv_lock = threading.Lock()

def make_headers(empresa):
    return {"access-token": empresa["access_token"], "secret-access-token": empresa["secret_token"], "Cache-Control": "no-cache", "User-Agent": "MinhaAplicacao/1.0", "Content-Type": "application/json"}

def normalizar_data(valor_bruto):
    if not valor_bruto: return ""
    s = str(valor_bruto).strip()
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', s)
    if m: return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r'^(\d{1,2})[/-](\d{1,2})[/-](\d{4})', s)
    if m: return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    m = re.match(r'^(\d{1,2})[/-](\d{1,2})[/-](\d{2})', s)
    if m: return f"20{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    return ""

def normalizar_nome_vendedor(nome):
    if not nome: return "Sem vendedor"
    s = str(nome).replace('\xa0',' ').replace('\t',' ').replace('\n',' ').replace('\r',' ')
    s = ' '.join(s.split())
    return s if s else "Sem vendedor"

def ler_dados_entregas():
    urls = [f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid=0", f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv", f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/gviz/tq?tqx=out:csv"]
    content = None
    for url in urls:
        try:
            resp = requests.get(url, timeout=30, allow_redirects=True)
            t = resp.text[:500].strip()
            if '<html' in t.lower() or '<!doctype' in t.lower(): continue
            if resp.status_code == 200 and len(resp.content) > 50:
                content = resp.content.decode('utf-8'); break
        except: continue
    if content is None: return []
    entregas = []
    try:
        reader = csv.reader(io.StringIO(content))
        data_atual = ""
        for row in reader:
            if not row or all(c.strip()=="" for c in row): continue
            pc = row[0].strip() if row[0] else ""
            if "PLANILHA DE ENTREGAS" in pc.upper():
                mt = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})', pc)
                data_atual = f"{mt.group(3)}-{mt.group(2).zfill(2)}-{mt.group(1).zfill(2)}" if mt else ""
                continue
            if pc.upper() == "CLIENTES": continue
            if data_atual and len(row) >= 3:
                ent = row[2].strip().upper() if row[2] else ""
                if ent in ("RETIRADA","RETRADA","RETITADA"): ent = "RETIRADA"
                if ent: entregas.append({"data": data_atual, "entregador": ent, "cliente": row[0].strip() if row[0] else "", "nota": row[1].strip() if row[1] else ""})
    except: return []
    return entregas

def listar_pedidos_periodo(data_inicio, data_fim, empresa, headers):
    endpoint = empresa["endpoint"]; df = empresa["data_field"]; of = empresa["order_field"]
    todos = []; offset = 0; limit = 500; pag = 1
    while pag <= 200:
        params = {"limit": limit, "offset": offset, "order": of, "sort": "Desc"}
        try: resp = requests.get(f"{BASE_URL}{endpoint}", headers=headers, params=params, timeout=30)
        except: break
        if resp.status_code != 200: break
        try: payload = resp.json()
        except: break
        lote = payload.get("data", [])
        if isinstance(lote, dict): lote = [lote]
        if not lote or not isinstance(lote, list): break
        todos.extend(lote)
        antes = sum(1 for p in lote if isinstance(p, dict) and normalizar_data(p.get(df,"")) and normalizar_data(p.get(df,"")) != "0000-00-00" and normalizar_data(p.get(df,"")) < data_inicio)
        if antes > 0: break
        offset += limit; pag += 1
    return [p for p in todos if isinstance(p, dict) and (lambda dp: dp and dp != "0000-00-00" and data_inicio <= dp <= data_fim)(normalizar_data(p.get(df,""))) and not p.update({df: normalizar_data(p.get(df,""))})]

def processar_pedidos(pedidos, empresa):
    en = empresa["nome"]; df = empresa["data_field"]; procs = []
    for p in pedidos:
        if not isinstance(p, dict): continue
        st = p.get("status_pedido", "")
        if st in STATUS_EXCLUIDOS: continue
        try: vl = float(p.get("valor_total_nota","0") or "0")
        except: vl = 0.0
        vd = "GP DISTRIBUIDORA" if en == "GP DISTRIBUIDORA" else normalizar_nome_vendedor(p.get("vendedor_pedido",""))
        procs.append({"id": str(p.get("id_ped", p.get("id_frente", p.get("id_pedido","")))), "data": normalizar_data(p.get(df,"")), "vendedor": vd, "empresa": en, "valor": round(vl,2), "status": st, "cliente": p.get("nome_cliente","")})
    return procs

def buscar_compras_periodo(empresa, di, df):
    headers = make_headers(empresa); compras = []; offset = 0; limit = 250; pag = 0
    while pag < 50:
        params = {"limit": limit, "offset": offset, "order": "data_pedido", "sort": "Desc"}
        try: resp = requests.get(f"{BASE_URL}/entradas-mercadoria/", headers=headers, params=params, timeout=30)
        except: break
        if resp.status_code != 200: break
        try: payload = resp.json()
        except: break
        lote = payload.get("data", [])
        if not lote or isinstance(lote, dict): break
        ta = False
        for c in lote:
            if not isinstance(c, dict): continue
            dc = normalizar_data(c.get("data_pedido","")); st = c.get("status_pedido","")
            if dc and di <= dc <= df and st == "Atendido": compras.append(c)
            if dc and dc < di: ta = True
        if ta: break
        offset += limit; pag += 1
        if len(lote) < limit: break
    return compras

def calcular_cmv_background(di, df, eirm, eigp, efrm, efgp):
    with _cmv_lock:
        if _cmv_cache["calculando"]: return
        _cmv_cache["calculando"] = True; _cmv_cache["params"] = f"{di}_{df}_{eirm}_{eigp}_{efrm}_{efgp}"
    try:
        crm = buscar_compras_periodo(EMPRESAS[0], di, df)
        tcrm = sum(float(c.get("valor_total_nota",0) or 0) for c in crm)
        eit = eirm + eigp; eft = efrm + efgp; cmv = eit + tcrm - eft
        r = {"status":"concluido","data_inicial":di,"data_final":df,"estoque_inicial_rm":eirm,"estoque_inicial_gp":eigp,"estoque_inicial_total":round(eit,2),"compras_rm":round(tcrm,2),"compras_gp":0.0,"compras_total":round(tcrm,2),"estoque_final_rm":efrm,"estoque_final_gp":efgp,"estoque_final_total":round(eft,2),"cmv":round(cmv,2)}
        with _cmv_lock: _cmv_cache["timestamp"] = time.time(); _cmv_cache["data"] = r; _cmv_cache["calculando"] = False
    except Exception as e:
        with _cmv_lock: _cmv_cache["calculando"] = False; _cmv_cache["data"] = {"status":"erro","erro":str(e)}

# ── FUNÇÃO: Fase 1 — Busca rápida (3 meses) ──────────────────────────────
def gerar_fase1():
    """
    FASE 1: Busca os últimos 3 meses rapidamente.
    Gera um dashboard parcial para exibir imediatamente.
    """
    hoje = date.today()
    data_fim = hoje.isoformat()
    data_inicio = (hoje - timedelta(days=90)).isoformat()

    print(f"[FASE 1] Busca rápida: {data_inicio} a {data_fim} (90 dias)")

    pedidos_brutos = listar_pedidos_periodo(data_inicio, data_fim)
    pedidos = processar_pedidos(pedidos_brutos)

    with open(DADOS_JSON, "w", encoding="utf-8") as f:
        json.dump(pedidos, f, ensure_ascii=False, indent=2)

    html = gerar_dashboard_html(pedidos, fase="1")
    with open(DASHBOARD_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    fat_total = sum(p["valor"] for p in pedidos)
    print(f"[FASE 1] Concluída! {len(pedidos)} pedidos, R$ {fat_total:,.2f}")

    # Marcar que a fase 1 terminou
    with open(OUTPUT_DIR / "fase1_ok.flag", "w") as f:
        f.write("ok")

    return True

# ── FUNÇÃO: Fase 2 — Resto do ano (background) ──────────────────────────
def gerar_fase2():
    """
    FASE 2: Busca o restante do ano (jan até 3 meses atrás).
    Mescla com os dados da fase 1 e regera o dashboard completo.
    """
    hoje = date.today()
    ano = hoje.year
    data_fim_fase2 = (hoje - timedelta(days=91)).isoformat()
    data_inicio_ano = f"{ano}-01-01"

    print(f"[FASE 2] Busca complementar: {data_inicio_ano} a {data_fim_fase2}")

    # Buscar período complementar
    pedidos_brutos_fase2 = listar_pedidos_periodo(data_inicio_ano, data_fim_fase2)
    pedidos_fase2 = processar_pedidos(pedidos_brutos_fase2)

    # Carregar dados da fase 1
    pedidos_fase1 = []
    if DADOS_JSON.exists():
        with open(DADOS_JSON, "r", encoding="utf-8") as f:
            pedidos_fase1 = json.load(f)

    # Mesclar (evitar duplicatas por ID)
    ids_existentes = set(p.get("id", "") for p in pedidos_fase1)
    pedidos_mesclados = list(pedidos_fase1)
    for p in pedidos_fase2:
        if p.get("id", "") not in ids_existentes:
            pedidos_mesclados.append(p)

    print(f"[FASE 2] Mesclagem: {len(pedidos_fase1)} + {len(pedidos_fase2)} = {len(pedidos_mesclados)} pedidos")

    # Salvar dados completos
    with open(DADOS_JSON, "w", encoding="utf-8") as f:
        json.dump(pedidos_mesclados, f, ensure_ascii=False, indent=2)

    # Gerar dashboard completo
    html = gerar_dashboard_html(pedidos_mesclados, fase="2")
    with open(DASHBOARD_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    fat_total = sum(p["valor"] for p in pedidos_mesclados)
    print(f"[FASE 2] Concluída! Total anual: {len(pedidos_mesclados)} pedidos, R$ {fat_total:,.2f}")

    # Marcar que a fase 2 terminou
    with open(OUTPUT_DIR / "fase2_ok.flag", "w") as f:
        f.write("ok")

    return True

# ── DASHBOARD HTML (com parâmetro de fase) ───────────────────────────────
def gerar_dashboard_html(pedidos, fase="2"):
    dados_json = json.dumps(pedidos, ensure_ascii=False)
    metas_upper = {k.upper(): v for k, v in METAS_MENSAIS.items()}
    metas_json = json.dumps(metas_upper, ensure_ascii=False)
    data_geracao = datetime.now().strftime("%d/%m/%Y às %H:%M:%S")

    # Texto indicador de fase
    if fase == "1":
        banner_fase = '<div style="background:#fef3c7;color:#92400e;padding:8px 16px;font-size:13px;text-align:center;">⚠️ Dados parciais (últimos 3 meses). Carregando ano completo em segundo plano...</div>'
    else:
        banner_fase = '<div style="background:#dcfce7;color:#16a34a;padding:8px 16px;font-size:13px;text-align:center;">✅ Dados completos do ano carregados.</div>'

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
function presetMesAtual(){const a=new Date();const ini=new Date(a.getFullYear(),a.getMonth(),1);const fim=new Date(a.getFullYear(),a.getMonth()+1,0);setDatas(ini.toISOString().split('T')[0],fim.toISOString().split('T')[0]);}
function presetAnoAtual(){const a=new Date();setDatas(a.getFullYear()+'-01-01',a.toISOString().split('T')[0]);}
function presetTudo(){setDatas('__MIN_DATA__','__MAX_DATA__');}
function setDatas(ini,fim){document.getElementById('dataInicio').value=ini;document.getElementById('dataFim').value=fim;aplicarFiltro();}
function aplicarFiltro(){const ini=document.getElementById('dataInicio').value;const fim=document.getElementById('dataFim').value;if(!ini||!fim)return;const pedidos=TODOS_PEDIDOS.filter(p=>p.data>=ini&&p.data<=fim);const mesRef=fim.substring(0,7);document.getElementById('mesMetaLabel').textContent=formatarMes(mesRef);if(pedidos.length===0){mostrarSemDados();return;}const porVend={};pedidos.forEach(p=>{const v=String(p.vendedor||'SEM VENDEDOR').toUpperCase().replace(/\s+/g,' ').trim();if(!porVend[v])porVend[v]={nome:v,faturamento:0,vendas:0};porVend[v].faturamento+=p.valor;porVend[v].vendas+=1;});let vendedores=Object.values(porVend).sort((a,b)=>b.faturamento-a.faturamento);vendedores.forEach(v=>v.faturamento=Math.round(v.faturamento*100)/100);const fatTotal=vendedores.reduce((s,v)=>s+v.faturamento,0);const qtdVendas=vendedores.reduce((s,v)=>s+v.vendas,0);const ticketMedio=qtdVendas>0?fatTotal/qtdVendas:0;const diasPeriodo=contarDias(ini,fim);renderKPIs(fatTotal,qtdVendas,ticketMedio,diasPeriodo,vendedores.length);renderMetas(vendedores,mesRef);renderChartVendedor(vendedores);renderChartDiario(pedidos);renderChartDonut(vendedores,fatTotal);renderTabela(vendedores,fatTotal);}
function renderKPIs(fatTotal,qtdVendas,ticketMedio,dias,nVend){document.getElementById('kpiGrid').innerHTML='<div class="kpi-card"><div class="kpi-label">💵 Faturamento Total</div><div class="kpi-value">'+fmtMoeda(fatTotal)+'</div><div class="kpi-sub">'+dias+' dia(s)</div></div><div class="kpi-card green"><div class="kpi-label">🛒 Vendas</div><div class="kpi-value">'+qtdVendas+'</div><div class="kpi-sub">não cancelados</div></div><div class="kpi-card amber"><div class="kpi-label">🎯 Ticket Médio</div><div class="kpi-value">'+fmtMoeda(ticketMedio)+'</div><div class="kpi-sub">por venda</div></div><div class="kpi-card purple"><div class="kpi-label">👥 Vendedoras</div><div class="kpi-value">'+nVend+'</div><div class="kpi-sub">ativas</div></div>';}
function renderMetas(vendedores,mesRef){let html='';const nomesComVendas=new Set(vendedores.map(v=>v.nome.toUpperCase()));const todas=[...vendedores];Object.keys(METAS).forEach(nome=>{if(!nomesComVendas.has(nome.toUpperCase()))todas.push({nome:nome.toUpperCase(),faturamento:0,vendas:0});});todas.sort((a,b)=>{const ma=METAS[a.nome.toUpperCase()]||0;const mb=METAS[b.nome.toUpperCase()]||0;const pa=ma>0?a.faturamento/ma:0;const pb=mb>0?b.faturamento/mb:0;return pb-pa;});todas.forEach((v,i)=>{const meta=METAS[v.nome.toUpperCase()]||0;const cor=CORES[i%CORES.length];const iniciais=v.nome.split(' ').map(p=>p[0]).join('').substring(0,2).toUpperCase();const pctMeta=meta>0?(v.faturamento/meta*100):0;const pctBar=Math.min(pctMeta,100);let sc,st,cb;if(meta===0){sc='status-semmeta';st='Sem meta';cb='#94a3b8';}else if(pctMeta>=100){sc='status-bateu';st='✅ Meta';cb='#16a34a';}else if(pctMeta>=70){sc='status-perto';st='🔥 Quase';cb='#f59e0b';}else{sc='status-longe';st='📈 Progresso';cb='#dc2626';}const falta=meta>0?Math.max(meta-v.faturamento,0):0;const tm=v.vendas>0?v.faturamento/v.vendas:0;let tf='';if(meta>0&&pctMeta<100){tf='Faltam <strong>'+fmtMoeda(falta)+'</strong>';if(tm>0)tf+=' • ≈ '+Math.ceil(falta/tm)+' venda(s)';}else if(meta>0&&pctMeta>=100){tf='🎉 Superou em <strong>'+fmtMoeda(v.faturamento-meta)+'</strong>';}html+='<div class="meta-card"><div class="meta-header"><div class="meta-avatar" style="background:'+cor+'">'+iniciais+'</div><div><div class="meta-name">'+fmtNome(v.nome)+'</div><div class="meta-sub">'+v.vendas+' venda(s) • Ticket: '+fmtMoeda(tm)+'</div></div></div><div class="meta-progress-bar"><div class="meta-progress-fill" style="width:'+pctBar+'%;background:'+cb+'">'+pctMeta.toFixed(0)+'%</div></div><div class="meta-stats"><div><span class="meta-valor '+(pctMeta>=100?'atingido':'abaixo')+'">'+fmtMoeda(v.faturamento)+'</span><span style="color:var(--text-muted);font-size:13px;"> / '+(meta>0?fmtMoeda(meta):'—')+'</span></div><span class="meta-status '+sc+'">'+st+'</span></div>'+(tf?'<div class="meta-falta">'+tf+'</div>':'')+'</div>';});document.getElementById('metaGrid').innerHTML=html;}
function renderChartVendedor(v){const ctx=document.getElementById('chartVendedor').getContext('2d');if(chartVend)chartVend.destroy();chartVend=new Chart(ctx,{type:'bar',data:{labels:v.map(x=>fmtNome(x.nome)),datasets:[{label:'Faturamento',data:v.map(x=>x.faturamento),backgroundColor:v.map((_,i)=>CORES[i%CORES.length]+'cc'),borderColor:v.map((_,i)=>CORES[i%CORES.length]),borderWidth:2,borderRadius:6}]},options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>'Faturamento: '+fmtMoeda(c.raw)}}},scales:{x:{ticks:{callback:v=>'R$ '+v.toLocaleString('pt-BR')}}}}});}
function renderChartDiario(pedidos){const ctx=document.getElementById('chartDiario').getContext('2d');if(chartDia)chartDia.destroy();const pd={};pedidos.forEach(p=>{if(!pd[p.data])pd[p.data]=0;pd[p.data]+=p.valor;});const todasDatas=Object.keys(pd).sort();const datasCompletas=[];if(todasDatas.length>0){const ini=new Date(todasDatas[0]+'T00:00:00');const fim=new Date(todasDatas[todasDatas.length-1]+'T00:00:00');const d=new Date(ini);while(d<=fim){datasCompletas.push(d.toISOString().split('T')[0]);d.setDate(d.getDate()+1);}}const valores=datasCompletas.map(d=>pd[d]||0);const g=ctx.createLinearGradient(0,0,0,320);g.addColorStop(0,'rgba(37,99,235,0.3)');g.addColorStop(1,'rgba(37,99,235,0.02)');chartDia=new Chart(ctx,{type:'line',data:{labels:datasCompletas.map(fmtData),datasets:[{label:'Faturamento',data:valores,borderColor:'#2563eb',backgroundColor:g,borderWidth:3,fill:true,tension:0.3,pointRadius:4,pointBackgroundColor:'#2563eb',pointHoverRadius:7}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>'Faturamento: '+fmtMoeda(c.raw)}}},scales:{y:{ticks:{callback:v=>'R$ '+v.toLocaleString('pt-BR')}}}}});}
function renderChartDonut(v,fatTotal){const ctx=document.getElementById('chartDonut').getContext('2d');if(chartDonut)chartDonut.destroy();chartDonut=new Chart(ctx,{type:'doughnut',data:{labels:v.map(x=>fmtNome(x.nome)),datasets:[{data:v.map(x=>x.faturamento),backgroundColor:v.map((_,i)=>CORES[i%CORES.length]),borderColor:'#fff',borderWidth:3}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'right',labels:{padding:16,font:{size:13}}},tooltip:{callbacks:{label:c=>{const pct=((c.raw/fatTotal)*100).toFixed(1);return c.label+': '+fmtMoeda(c.raw)+' ('+pct+'%)';}}}}}});}
function renderTabela(v,fatTotal){let html='';v.forEach((x,i)=>{const pct=fatTotal>0?(x.faturamento/fatTotal*100):0;const t=x.vendas>0?x.faturamento/x.vendas:0;const meta=METAS[x.nome.toUpperCase()]||0;const pm=meta>0?(x.faturamento/meta*100):0;const cor=CORES[i%CORES.length];const cm=pm>=100?'#16a34a':pm>=70?'#f59e0b':'#dc2626';html+='<tr><td class="vendedor-name"><span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:'+cor+';margin-right:8px;"></span>'+fmtNome(x.nome)+'</td><td class="valor-cell">'+fmtMoeda(x.faturamento)+'</td><td>'+x.vendas+'</td><td>'+fmtMoeda(t)+'</td><td>'+(meta>0?fmtMoeda(meta):'<span style="color:var(--text-muted)">—</span>')+'</td><td><span class="pct-bar"><span class="pct-fill" style="width:'+Math.min(pm,100)+'%;background:'+cm+'"></span></span><strong style="color:'+cm+'">'+pm.toFixed(0)+'%</strong></td><td><span class="pct-bar"><span class="pct-fill" style="width:'+pct+'%;background:'+cor+'"></span></span>'+pct.toFixed(1)+'%</td></tr>';});document.getElementById('tabelaBody').innerHTML=html;}
function mostrarSemDados(){document.getElementById('kpiGrid').innerHTML='<div class="no-data">⚠️ Nenhum pedido no período.</div>';document.getElementById('metaGrid').innerHTML='';document.getElementById('tabelaBody').innerHTML='';if(chartVend)chartVend.destroy();if(chartDia)chartDia.destroy();if(chartDonut)chartDonut.destroy();}
function fmtMoeda(v){return 'R$ '+Number(v).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2});}
function fmtData(iso){const[y,m,d]=iso.split('-');return d+'/'+m;}
function contarDias(ini,fim){const d1=new Date(ini+'T00:00:00');const d2=new Date(fim+'T00:00:00');return Math.round((d2-d1)/86400000)+1;}
function formatarMes(mr){const[ano,mes]=mr.split('-');const n=['Janeiro','Fevereiro','Março','Abril','Maio','Junho','Julho','Agosto','Setembro','Outubro','Novembro','Dezembro'];return n[parseInt(mes)-1]+' '+ano;}
// Auto-recarregar se estiver na fase 1 (a cada 15s, até a fase 2 completar)
__AUTO_RELOAD__
document.addEventListener('keydown',e=>{if(e.key==='Enter'&&e.target.type==='date')aplicarFiltro();});
window.addEventListener('DOMContentLoaded',init);
</script>
</body>
</html>'''

    # Auto-reload só na fase 1
    if fase == "1":
        html = html.replace("__AUTO_RELOAD__",
            "setTimeout(function(){location.reload();},15000);")
    else:
        html = html.replace("__AUTO_RELOAD__", "")

    html = html.replace("__DADOS_JSON__", dados_json)
    html = html.replace("__METAS_JSON__", metas_json)
    html = html.replace("__DATA_GERACAO__", data_geracao)
    html = html.replace("__MIN_DATA__", min_data)
    html = html.replace("__MAX_DATA__", max_data)
    html = html.replace("__BANNER_FASE__", banner_fase)
    return html

# ── PÁGINA DE BOAS-VINDAS INSTITUCIONAL ──────────────────────────────────
def gerar_pagina_boas_vindas():
    """Gera a página institucional de boas-vindas com loading."""
    return r'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bem-vindo | Dashboard Corporativo</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
  background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 50%,#2563eb 100%);
  color:#fff;min-height:100vh;display:flex;align-items:center;justify-content:center;
  padding:20px;}
.container{max-width:800px;text-align:center;}
.logo{width:80px;height:80px;background:rgba(255,255,255,.15);border-radius:20px;
  display:flex;align-items:center;justify-content:center;font-size:36px;margin:0 auto 24px;
  backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,.2);}
h1{font-size:32px;font-weight:700;margin-bottom:12px;letter-spacing:-0.5px;}
.subtitle{font-size:16px;opacity:.8;margin-bottom:32px;line-height:1.6;}
.features{display:grid;grid-template-columns:repeat(3,1fr);gap:20px;margin-bottom:40px;}
.feature{background:rgba(255,255,255,.1);border-radius:12px;padding:20px;
  backdrop-filter:blur(10px);border:1px solid rgba(255,255,255,.15);}
.feature-icon{font-size:28px;margin-bottom:8px;}
.feature-title{font-size:14px;font-weight:700;margin-bottom:4px;}
.feature-desc{font-size:12px;opacity:.7;}
.loading-section{margin-top:20px;}
.spinner{border:4px solid rgba(255,255,255,.2);border-top:4px solid #fff;
  border-radius:50%;width:48px;height:48px;animation:spin 1s linear infinite;margin:0 auto 16px;}
@keyframes spin{0%{transform:rotate(0)}100%{transform:rotate(360deg)}}
.loading-text{font-size:15px;opacity:.9;}
.loading-sub{font-size:13px;opacity:.6;margin-top:4px;}
.progress-bar{background:rgba(255,255,255,.15);border-radius:10px;height:6px;
  max-width:400px;margin:16px auto 0;overflow:hidden;}
.progress-fill{background:#fff;height:100%;border-radius:10px;width:0%;
  transition:width .5s ease;animation:pulse 2s ease-in-out infinite;}
@keyframes pulse{0%,100%{width:30%}50%{width:70%}}
.footer{margin-top:40px;font-size:12px;opacity:.5;}
</style>
</head>
<body>
<div class="container">
  <div class="logo">📊</div>
  <h1>Dashboard Corporativo</h1>
  <p class="subtitle">
    Sistema de gestão de vendas e metas<br>
    Acompanhamento em tempo real do faturamento da equipe
  </p>
  
  <div class="features">
    <div class="feature">
      <div class="feature-icon">📈</div>
      <div class="feature-title">Faturamento</div>
      <div class="feature-desc">Acompanhe vendas em tempo real</div>
    </div>
    <div class="feature">
      <div class="feature-icon">🎯</div>
      <div class="feature-title">Metas</div>
      <div class="feature-desc">Progresso mensal por vendedora</div>
    </div>
    <div class="feature">
      <div class="feature-icon">👥</div>
      <div class="feature-title">Equipe</div>
      <div class="feature-desc">Performance individual detalhada</div>
    </div>
  </div>
  
  <div class="loading-section">
    <div class="spinner"></div>
    <div class="loading-text">Carregando dados do ano...</div>
    <div class="loading-sub">Buscando pedidos na API Vhsys</div>
    <div class="progress-bar"><div class="progress-fill"></div></div>
  </div>
  
  <div class="footer">
    © 2026 • Sistema integrado Vhsys API v2
  </div>
</div>
<script>
// Verificar a cada 5 segundos se o dashboard já está pronto
async function verificar() {
  try {
    const r = await fetch('/status');
    const d = await r.json();
    if (d.ready) {
      window.location.href = '/dashboard';
    } else if (d.fase1_ready) {
      // Fase 1 pronta — ir para dashboard parcial
      window.location.href = '/dashboard';
    }
  } catch(e) {}
}
setInterval(verificar, 5000);
verificar();
</script>
</body>
</html>'''

# ── FLASK APP 
app = Flask(__name__)

# Variável global para controle de fases
fase1_pronta = False
fase2_pronta = False

@app.route('/')
def home():
    """Página de boas-vindas institucional."""
    global fase1_pronta, fase2_pronta
    # Se fase 1 já está pronta, vai direto pro dashboard
    if fase1_pronta and DASHBOARD_HTML.exists():
        return send_file(str(DASHBOARD_HTML))
    # Senão, mostra a página de boas-vindas
    return gerar_pagina_boas_vindas()

@app.route('/dashboard')
def dashboard():
    """Serve o dashboard diretamente."""
    if DASHBOARD_HTML.exists():
        return send_file(str(DASHBOARD_HTML))
    return gerar_pagina_boas_vindas()

@app.route('/status')
def status():
    """Endpoint para verificar se o dashboard está pronto."""
    global fase1_pronta, fase2_pronta
    return jsonify({
        "fase1_ready": fase1_pronta,
        "fase2_ready": fase2_pronta,
        "ready": fase1_pronta,
        "dashboard_exists": DASHBOARD_HTML.exists()
    })

@app.route('/atualizar')
def atualizar():
    """Força atualização completa (2 fases)."""
    global fase1_pronta, fase2_pronta
    fase1_pronta = False
    fase2_pronta = False
    
    def rodar_em_background():
        global fase1_pronta, fase2_pronta
        try:
            # FASE 1: rápida (3 meses)
            gerar_fase1()
            fase1_pronta = True
            print("[BG] Fase 1 concluída — dashboard parcial disponível")
            
            # FASE 2: resto do ano
            gerar_fase2()
            fase2_pronta = True
            print("[BG] Fase 2 concluída — dashboard completo disponível")
        except Exception as e:
            print(f"[BG] Erro: {e}")
            traceback.print_exc()
    
    threading.Thread(target=rodar_em_background, daemon=True).start()
    return gerar_pagina_boas_vindas()

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

# ── INICIALIZAÇÃO (não bloqueia o Flask) 
def inicializar_background():
    """Roda as 2 fases em background sem bloquear o Flask."""
    global fase1_pronta, fase2_pronta
    threading.Event().wait(3)  # aguardar Flask subir
    
    # Se já existe dashboard salvo, marcar como pronto
    if DASHBOARD_HTML.exists() and DADOS_JSON.exists():
        print("[INIT] Dashboard já existe. Marcando como pronto.")
        fase1_pronta = True
        # Verificar se tem dados do ano todo (mais de 1000 pedidos)
        try:
            with open(DADOS_JSON, "r", encoding="utf-8") as f:
                dados = json.load(f)
            if len(dados) > 1000:
                print("[INIT] Dados completos detectados. Fase 2 também pronta.")
                fase2_pronta = True
                return
        except:
            pass
        # Se não tem dados do ano todo, buscar complemento em background
        print("[INIT] Buscando complemento do ano em background...")
    
    try:
        if not fase1_pronta:
            print("[BG] Iniciando Fase 1...")
            gerar_fase1()
            fase1_pronta = True
            print("[BG] Fase 1 concluída!")
        
        if not fase2_pronta:
            print("[BG] Iniciando Fase 2...")
            gerar_fase2()
            fase2_pronta = True
            print("[BG] Fase 2 concluída!")
    except Exception as e:
        print(f"[BG] Erro: {e}")
        traceback.print_exc()

if __name__ == '__main__':
    # Iniciar carregamento em background (não bloqueia)
    t = threading.Thread(target=inicializar_background, daemon=True)
    t.start()
    
    # Flask inicia imediatamente
    port = int(os.environ.get('PORT', 5000))
    print(f"[FLASK] Servidor na porta {port}")
    print(f"[FLASK] Acesse: http://localhost:{port}")
    app.run(host='0.0.0.0', port=port, debug=False)

def buscar_dados_de_mes(ano, mes, empresa):
    df = monthrange(ano, mes)[1]
    di = f"{ano}-{mes:02d}-01"; dff = f"{ano}-{mes:02d}-{df:02d}"
    h = make_headers(empresa)
    return processar_pedidos(listar_pedidos_periodo(di, dff, empresa, h), empresa)

def buscar_dados_background():
    with _cache_lock:
        if _cache["buscando"]: return
        _cache["buscando"] = True
    try:
        hoje = date.today(); ano = hoje.year; ma = hoje.month
        tarefas = [(ano, mes, emp) for mes in range(1, ma+1) for emp in EMPRESAS]
        todos = []
        with ThreadPoolExecutor(max_workers=12) as ex:
            fs = {ex.submit(buscar_dados_de_mes, a, m, e): (m, e["nome"]) for (a, m, e) in tarefas}
            for f in as_completed(fs):
                try: todos.extend(f.result())
                except: pass
        ent = ler_dados_entregas()
        html = gerar_dashboard_html(todos, ent)
        with _cache_lock:
            _cache["timestamp"] = time.time(); _cache["html"] = html; _cache["erro"] = ""; _cache["buscando"] = False
    except Exception as e:
        with _cache_lock: _cache["erro"] = str(e); _cache["buscando"] = False

LOADING_HTML = '''<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Carregando...</title><style>body{font-family:sans-serif;background:#f0f2f5;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}.l{text-align:center;padding:40px;background:#fff;border-radius:16px;box-shadow:0 4px 6px rgba(0,0,0,.07)}.s{width:50px;height:50px;border:5px solid #dbeafe;border-top-color:#2563eb;border-radius:50%;margin:0 auto 20px;animation:sp 1s linear infinite}@keyframes sp{to{transform:rotate(360deg)}}h1{color:#1e293b;font-size:20px}p{color:#64748b;font-size:14px}</style><meta http-equiv="refresh" content="10"></head><body><div class="l"><div class="s"></div><h1>Buscando dados...</h1><p>Aguarde, coletando vendas e entregas.</p></div></body></html>'''

@app.route('/')
def dashboard():
    with _cache_lock:
        if _cache["html"] and (time.time() - _cache["timestamp"]) < CACHE_TEMPO_SEGUNDOS: return _cache["html"]
        if _cache["buscando"]: return LOADING_HTML
    threading.Thread(target=buscar_dados_background, daemon=True).start()
    return LOADING_HTML

@app.route('/atualizar')
def forcar_atualizacao():
    with _cache_lock: _cache["timestamp"] = 0; _cache["html"] = ""; _cache["buscando"] = False
    threading.Thread(target=buscar_dados_background, daemon=True).start()
    return "<script>window.location.href='/';</script>"

import base64

# Carregar logo como base64 na inicializacao
_logo_base64 = ""
try:
    for caminho in [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Logo_Real_Distribuidora.png'),
        os.path.join(os.getcwd(), 'Logo_Real_Distribuidora.png'),
        'Logo_Real_Distribuidora.png',
    ]:
        if os.path.exists(caminho):
            with open(caminho, 'rb') as f:
                _logo_base64 = base64.b64encode(f.read()).decode('utf-8')
            break
except:
    pass

@app.route('/logo')
def logo():
    import os, glob
    from flask import send_file, Response
    # Buscar o arquivo em varios caminhos possiveis
    caminhos = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Logo_Real_Distribuidora.png'),
        os.path.join(os.getcwd(), 'Logo_Real_Distribuidora.png'),
        'Logo_Real_Distribuidora.png',
        '/app/Logo_Real_Distribuidora.png',
    ]
    for c in caminhos:
        if os.path.isfile(c):
            return send_file(c, mimetype='image/png')
    # Busca recursiva como ultimo recurso
    matches = glob.glob('**/*ogo*.png', recursive=True)
    if matches:
        return send_file(matches[0], mimetype='image/png')
    # Fallback: retornar pixel transparente
    pixel = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\xfe\x02\xfe\xdc\xcc\x59\xe7\x00\x00\x00\x00IEND\xaeB`\x82'
    return Response(pixel, mimetype='image/png')


@app.route('/cmv')
def cmv_endpoint():
    di = request.args.get('data_inicial', ''); df = request.args.get('data_final', '')
    eirm = float(request.args.get('est_ini_rm', 0) or 0); eigp = float(request.args.get('est_ini_gp', 0) or 0)
    efrm = float(request.args.get('est_fin_rm', 0) or 0); efgp = float(request.args.get('est_fin_gp', 0) or 0)
    if not di or not df: return jsonify({"status": "erro", "erro": "Datas nao informadas"})
    pk = f"{di}_{df}_{eirm}_{eigp}_{efrm}_{efgp}"
    with _cmv_lock:
        if _cmv_cache["data"] and _cmv_cache["params"] == pk and not _cmv_cache["calculando"]: return jsonify(_cmv_cache["data"])
        if _cmv_cache["calculando"] and _cmv_cache["params"] == pk: return jsonify({"status": "calculando"})
    threading.Thread(target=calcular_cmv_background, args=(di, df, eirm, eigp, efrm, efgp), daemon=True).start()
    return jsonify({"status": "iniciando"})

@app.route('/api/metas', methods=['GET', 'POST'])
def api_metas():
    global _metas_consolidada
    if request.method == 'GET':
        with _metas_lock: return jsonify({"metas": _metas, "consolidada": _metas_consolidada})
    dados = request.get_json()
    if not dados: return jsonify({"status": "erro", "erro": "Dados nao enviados"}), 400
    with _metas_lock:
        if '_consolidada' in dados: _metas_consolidada = float(dados['_consolidada'])
        for k, v in dados.items():
            if k != '_consolidada': _metas[k] = float(v)
    with _cache_lock: _cache["timestamp"] = 0; _cache["html"] = ""
    return jsonify({"status": "ok"})

def init_background():
    time.sleep(2); buscar_dados_background()

threading.Thread(target=init_background, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Dashboard online em http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
