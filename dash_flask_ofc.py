#!/usr/bin/env python3
"""
dash_flask_ofc.py  (v8 - mes atual + busca sob demanda + ajax loading)
"""
import os, sys, json, csv, io, re, time, threading, glob
from datetime import datetime, date
from calendar import monthrange
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from flask import Flask, request, jsonify, send_file, Response

app = Flask(__name__)

EMPRESAS = [
    {"nome": "REAL MAIS", "access_token": "YYeHeFaNAfVfLegOLXedMFZMLNPLQT", "secret_token": "k9Qhe0oaSAchTjWgpvLeUvxmZcyLVfO", "endpoint": "/pedidos/", "data_field": "data_pedido", "order_field": "data_pedido"},
    {"nome": "GP DISTRIBUIDORA", "access_token": "EdPfRWCOGgefDeVcSNNaGJLJeZDMST", "secret_token": "5P4nmO1ONthN5oqfX81lHKX5i0YC3dm", "endpoint": "/vendas-balcao/", "data_field": "data_cad_pedido", "order_field": "data_cad_pedido"},
]
BASE_URL = "https://api.vhsys.com/v2"
STATUS_INCLUIDOS = {"Atendido", "Em Andamento"}
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

def normalizar_data(v):
    if not v: return ""
    s = str(v).strip()
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})', s)
    if m: return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r'^(\d{1,2})[/-](\d{1,2})[/-](\d{4})', s)
    if m: return f"{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    m = re.match(r'^(\d{1,2})[/-](\d{1,2})[/-](\d{2})', s)
    if m: return f"20{m.group(3)}-{m.group(2).zfill(2)}-{m.group(1).zfill(2)}"
    return ""

def normalizar_nome(n):
    if not n: return "Sem vendedor"
    s = str(n).replace('\xa0',' ').replace('\t',' ').replace('
',' ').replace('\r',' ')
    s = ' '.join(s.split())
    return s if s else "Sem vendedor"

def ler_dados_entregas():
    urls = [f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid=0", f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv", f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/gviz/tq?tqx=out:csv"]
    content = None
    for url in urls:
        try:
            resp = requests.get(url, timeout=30, allow_redirects=True)
            t = resp.text[:500].strip()
            if '
            if resp.status_code == 200 and len(resp.content) > 50:
                content = resp.content.decode('utf-8'); break
        except: continue
    if content is None: return []
    entregas = []
    try:
        reader = csv.reader(io.StringIO(content)); data_atual = ""
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

def listar_pedidos_periodo(di, df, empresa, headers):
    ep = empresa["endpoint"]; dfield = empresa["data_field"]; ofield = empresa["order_field"]
    todos = []; offset = 0; limit = 250; pag = 1
    while pag <= 200:
        params = {"limit": limit, "offset": offset, "order": ofield, "sort": "Desc"}
        try: resp = requests.get(f"{BASE_URL}{ep}", headers=headers, params=params, timeout=30)
        except: break
        if resp.status_code != 200: break
        try: payload = resp.json()
        except: break
        lote = payload.get("data", [])
        if isinstance(lote, dict): lote = [lote]
        if not lote or not isinstance(lote, list): break
        todos.extend(lote)
        antes = 0
        for p in lote:
            if not isinstance(p, dict): continue
            dp = normalizar_data(p.get(dfield,""))
            if dp and dp != "0000-00-00" and dp < di: antes += 1
        if antes > 0: break
        if len(lote) < limit: break
        offset += limit; pag += 1
    filtrados = []
    for p in todos:
        if not isinstance(p, dict): continue
        dp = normalizar_data(p.get(dfield,""))
        if dp and dp != "0000-00-00" and di <= dp <= df:
            p[dfield] = dp
            filtrados.append(p)
    return filtrados

def processar_pedidos(pedidos, empresa):
    en = empresa["nome"]; dfield = empresa["data_field"]; procs = []
    for p in pedidos:
        if not isinstance(p, dict): continue
        st = p.get("status_pedido", "")
        if st not in STATUS_INCLUIDOS: continue
        try: vl = float(p.get("valor_total_nota","0") or "0")
        except: vl = 0.0
        vd = "GP DISTRIBUIDORA" if en == "GP DISTRIBUIDORA" else normalizar_nome(p.get("vendedor_pedido",""))
        procs.append({"id": str(p.get("id_ped", p.get("id_frente", p.get("id_pedido","")))), "data": normalizar_data(p.get(dfield,"")), "vendedor": vd, "empresa": en, "valor": round(vl,2), "status": st, "cliente": p.get("nome_cliente","")})
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
        _cmv_cache["calculando"] = True
        _cmv_cache["params"] = f"{di}_{df}_{eirm}_{eigp}_{efrm}_{efgp}"
    try:
        crm = buscar_compras_periodo(EMPRESAS[0], di, df)
        tcrm = sum(float(c.get("valor_total_nota",0) or 0) for c in crm)
        eit = eirm + eigp; eft = efrm + efgp; cmv = eit + tcrm - eft
        r = {"status":"concluido","data_inicial":di,"data_final":df,"estoque_inicial_rm":eirm,"estoque_inicial_gp":eigp,"estoque_inicial_total":round(eit,2),"compras_rm":round(tcrm,2),"compras_gp":0.0,"compras_total":round(tcrm,2),"estoque_final_rm":efrm,"estoque_final_gp":efgp,"estoque_final_total":round(eft,2),"cmv":round(cmv,2)}
        with _cmv_lock:
            _cmv_cache["timestamp"] = time.time()
            _cmv_cache["data"] = r
            _cmv_cache["calculando"] = False
    except Exception as e:
        with _cmv_lock:
            _cmv_cache["calculando"] = False
            _cmv_cache["data"] = {"status":"erro","erro":str(e)}

def buscar_dados_de_mes(ano, mes, empresa):
    df = monthrange(ano, mes)[1]
    di = f"{ano}-{mes:02d}-01"
    dff = f"{ano}-{mes:02d}-{df:02d}"
    h = make_headers(empresa)
    return processar_pedidos(listar_pedidos_periodo(di, dff, empresa, h), empresa)

def buscar_dados_background():
    with _cache_lock:
        if _cache["buscando"]: return
        _cache["buscando"] = True
    try:
        hoje = date.today()
        ano = hoje.year
        ma = hoje.month
        print(f"[DEBUG] Iniciando busca - {ano}/{ma}", flush=True)
        tarefas = [(ano, ma, emp) for emp in EMPRESAS]
        todos = []
        with ThreadPoolExecutor(max_workers=16) as ex:
            fs = {ex.submit(buscar_dados_de_mes, a, m, e): (m, e["nome"]) for (a, m, e) in tarefas}
            for f in as_completed(fs):
                try:
                    result = f.result()
                    todos.extend(result)
                    print(f"[DEBUG] Empresa concluida - {len(result)} pedidos", flush=True)
                except Exception as ex2:
                    print(f"[DEBUG] ERRO em empresa: {ex2}", flush=True)
        print(f"[DEBUG] Total pedidos: {len(todos)}", flush=True)
        ent = ler_dados_entregas()
        print(f"[DEBUG] Entregas: {len(ent)}", flush=True)
        html = gerar_dashboard_html(todos, ent)
        print(f"[DEBUG] HTML gerado: {len(html)} chars", flush=True)
        with _cache_lock:
            _cache["timestamp"] = time.time()
            _cache["html"] = html
            _cache["erro"] = ""
            _cache["buscando"] = False
        print("[DEBUG] Concluido com sucesso!", flush=True)
    except Exception as e:
        print(f"[DEBUG] ERRO FATAL: {e}", flush=True)
        with _cache_lock:
            _cache["erro"] = str(e)
            _cache["buscando"] = False

def gerar_dashboard_html(pedidos, entregas):
    dj = json.dumps(pedidos, ensure_ascii=False)
    ej = json.dumps(entregas, ensure_ascii=False)
    with _metas_lock:
        mj = json.dumps(_metas, ensure_ascii=False)
        mc = _metas_consolidada
    dg = datetime.now().strftime("%d/%m/%Y as %H:%M:%S")
    if pedidos:
        ds = sorted([p["data"] for p in pedidos if p["data"]])
        mind = ds[0] if ds else date.today().isoformat()
        maxd = ds[-1] if ds else date.today().isoformat()
    else:
        mind = date.today().replace(day=1).isoformat()
        maxd = date.today().isoformat()
    html = r'''




Real Acai Distribuidora - Dashboard


:root{--bg:#f0f2f5;--card:#fff;--pri:#2563eb;--pl:#dbeafe;--grn:#16a34a;--gl:#dcfce7;--amb:#f59e0b;--al:#fef3c7;--red:#dc2626;--rl:#fee2e2;--txt:#1e293b;--mut:#64748b;--brd:#e2e8f0;--sh:0 1px 3px rgba(0,0,0,.1);--shl:0 4px 6px rgba(0,0,0,.07);--r:12px}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:var(--bg);color:var(--txt);min-height:100vh}
.hdr{background:linear-gradient(135deg,#1e3a5f 0%,#2563eb 100%);color:#fff;padding:16px 32px;display:flex;align-items:center;justify-content:space-between}
.hdr-logo{display:flex;align-items:center;gap:16px}
.hdr h1{font-size:21px;font-weight:700}
.hdr .sub{font-size:13px;opacity:.85;margin-top:2px}
.hdr .upd{font-size:12px;opacity:.7;text-align:right}
.tabs{display:flex;background:var(--card);box-shadow:var(--sh);overflow-x:auto}
.tab{flex:1;padding:14px 24px;border:none;background:none;font-size:15px;font-weight:600;color:var(--mut);cursor:pointer;transition:all .2s;border-bottom:4px solid transparent;white-space:nowrap}
.tab:hover{background:var(--pl);color:var(--pri)}
.tab.act{color:var(--pri);border-bottom-color:var(--pri);background:var(--pl)}
.ctn{max-width:1400px;margin:0 auto;padding:24px}
.tc{display:none}.tc.act{display:block}
.fb{background:var(--card);border-radius:var(--r);box-shadow:var(--sh);padding:20px 24px;margin-bottom:24px;display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.fg{display:flex;align-items:center;gap:8px}
.fg label{font-size:13px;font-weight:600;color:var(--mut);text-transform:uppercase;letter-spacing:.5px}
.fg input[type=date]{padding:8px 12px;border:2px solid var(--brd);border-radius:8px;font-size:14px;outline:none}
.fg input[type=number]{padding:8px 12px;border:2px solid var(--brd);border-radius:8px;font-size:14px;width:180px}
.ba{background:var(--pri);color:#fff;border:none;padding:9px 24px;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer}
.bp{background:var(--pl);color:var(--pri);border:none;padding:7px 14px;border-radius:6px;font-size:12px;font-weight:600;cursor:pointer}
.bs{background:var(--grn);color:#fff;border:none;padding:9px 24px;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer}
.ef{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.el{font-size:13px;font-weight:600;color:var(--mut);margin-right:4px}
.be{background:var(--pl);color:var(--pri);border:none;padding:8px 16px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer}
.be:hover{background:var(--pri);color:#fff}.be.act{background:var(--pri);color:#fff}
.st{font-size:18px;font-weight:700;margin:24px 0 16px;padding-bottom:8px;border-bottom:2px solid var(--brd)}
.kg{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:16px;margin-bottom:24px}
.kc{background:var(--card);border-radius:var(--r);box-shadow:var(--sh);padding:20px 24px;border-left:4px solid var(--pri)}
.kc:hover{box-shadow:var(--shl)}.kc.grn{border-left-color:var(--grn)}.kc.amb{border-left-color:var(--amb)}.kc.red{border-left-color:var(--red)}.kc.pur{border-left-color:#8b5cf6}.kc.tel{border-left-color:#14b8a6}
.kl{font-size:12px;font-weight:600;color:var(--mut);text-transform:uppercase;margin-bottom:6px}
.kv{font-size:26px;font-weight:700}.ks{font-size:12px;color:var(--mut);margin-top:4px}
.mg{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:16px;margin-bottom:24px}
.mc{background:var(--card);border-radius:var(--r);box-shadow:var(--sh);padding:20px 22px}.mc:hover{box-shadow:var(--shl)}
.mc.con{grid-column:1/-1;background:linear-gradient(135deg,#1e3a5f 0%,#2563eb 100%);color:#fff}
.mc.con .mn{color:#fff}.mc.con .ms{color:rgba(255,255,255,.8)}.mc.con .mpb{background:rgba(255,255,255,.2)}.mc.con .mv{color:#fff}.mc.con .mf{color:rgba(255,255,255,.8)}
.mh{display:flex;align-items:center;gap:12px;margin-bottom:14px}
.ma{width:42px;height:42px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:700;color:#fff;flex-shrink:0}
.mn{font-size:15px;font-weight:700}.ms{font-size:12px;color:var(--mut);margin-top:2px}
.mpb{background:var(--brd);border-radius:12px;height:28px;overflow:hidden;margin-bottom:10px}
.mpf{height:100%;border-radius:12px;display:flex;align-items:center;padding-left:12px;color:#fff;font-size:12px;font-weight:700;min-width:0}
.mst{display:flex;justify-content:space-between;align-items:center;font-size:13px}
.mv{font-weight:700;font-size:16px}.mv.at{color:var(--grn)}
.msb{padding:4px 10px;border-radius:6px;font-size:11px;font-weight:700;text-transform:uppercase}
.sb{background:var(--gl);color:var(--grn)}.sp{background:var(--al);color:var(--amb)}.sl{background:var(--rl);color:var(--red)}.sn{background:#f1f5f9;color:var(--mut)}
.mf{font-size:12px;color:var(--mut);margin-top:6px}
.cg{display:grid;grid-template-columns:1fr 1fr;gap:24px;margin-bottom:24px}
@media(max-width:900px){.cg{grid-template-columns:1fr}}
.cc{background:var(--card);border-radius:var(--r);box-shadow:var(--sh);padding:20px 24px}.cc.f{grid-column:1/-1}
.ct{font-size:16px;font-weight:700;margin-bottom:16px}.cw{position:relative;height:320px}
.tc2{background:var(--card);border-radius:var(--r);box-shadow:var(--sh);padding:20px 24px;margin-bottom:24px}
.tc2 table{width:100%;border-collapse:collapse}
.tc2 th{text-align:left;padding:12px 14px;font-size:12px;font-weight:700;color:var(--mut);text-transform:uppercase;border-bottom:2px solid var(--brd)}
.tc2 td{padding:12px 14px;font-size:14px;border-bottom:1px solid var(--brd)}
.tc2 tr:hover td{background:#f8fafc}.tc2 tr:last-child td{border-bottom:none}
.vn{font-weight:600}.vc{font-weight:600;color:var(--grn)}
.pb{background:var(--brd);border-radius:6px;height:8px;width:80px;overflow:hidden;display:inline-block;vertical-align:middle;margin-right:8px}
.pf{height:100%;border-radius:6px}
.nd{text-align:center;padding:48px;color:var(--mut);font-size:16px}
.mp{background:var(--card);border-radius:var(--r);box-shadow:var(--sh);padding:20px 24px;margin-bottom:24px;display:none}.mp.act{display:block}
.mer{display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid var(--brd)}.mer:last-child{border-bottom:none}
.mel{flex:1;font-weight:600;font-size:14px}
.cig{display:flex;gap:16px;flex-wrap:wrap;align-items:center;margin-bottom:12px}
.footer{background:#1e293b;color:#94a3b8;padding:32px 24px;text-align:center;font-size:13px;line-height:1.8}
.footer strong{color:#e2e8f0}
.footer-divider{border:none;border-top:1px solid #334155;margin:16px auto;max-width:600px}
.footer-section{margin:8px 0}
.footer-name{font-size:15px;font-weight:700;color:#fff;letter-spacing:1px}
.footer-tags{font-size:11px;color:#64748b;text-transform:uppercase;letter-spacing:1.5px;margin:4px 0}
.footer-copy{font-size:12px;color:#64748b;margin-top:12px}



RAReal Acai DistribuidoraDashboard Gerencial - Vhsys API v2Dados gerados em: __DG__

Comercial
Logistica
Contabil


DeAteAplicarHoje7dMesTudo
Empresa:ConsolidadoREAL MAISGP


Metas -  Gerenciar Metas

Editar MetasSalvarCancelar
Faturamento por VendedoraFaturamento DiarioParticipacao
Detalhamento por VendedoraVendedoraEmpFaturamentoVendasTicketMeta%Meta%Tot



Entregas por EntregadorEntregas por Dia
Detalhamento de EntregasEntregadorTotal%



CMV - Custo de Mercadorias Vendidas

Estoque InicialEstoque Final
Est.Ini RMEst.Ini GPEst.Fin RMEst.Fin GP
Calcular CMV


Faturamento por EmpresaEmpresaFaturamentoVendasTicket%


Gabriel Freitas
Desenvolvedor Autonomo - Desenvolvimento - Sistemas - Automacao - Inteligencia de Dados

Os dados deste sistema sao sincronizados automaticamente atraves do sistema de gestao empresarial VHSYS, utilizado pela Real Acai Distribuidora.
Sistema desenvolvido exclusivamente para: REAL ACAI DISTRIBUIDORA

(c) 2026 Real Acai Distribuidora - Todos os direitos reservadosDesenvolvido por Gabriel Freitas - Desenvolvedor Autonomo - v1.0.0 - Ultima atualizacao: 14/08/2026



const TP=__DJ__,TE=__EJ__,M=__MJ__,MC=__MC__,C=['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#14b8a6','#f97316','#6366f1','#84cc16','#06b6d4','#a855f7'];
let cV=null,cD=null,cK=null,cE=null,cED=null,ef='todos';
var loadedRange={start:null,end:null};
function mostrarLoad(){var o=document.createElement('div');o.id='ovLoad';o.style.cssText='position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:9999;display:flex;justify-content:center;align-items:center;';o.innerHTML='<div style="background:#fff;padding:40px;border-radius:16px;text-align:center;box-shadow:0 4px 20px rgba(0,0,0,0.3);max-width:420px;"><div style="width:50px;height:50px;border:5px solid #dbeafe;border-top-color:#2563eb;border-radius:50%;margin:0 auto 20px;animation:spin 1s linear infinite;"></div><h3 style="color:#1e293b;margin-bottom:8px;font-size:18px;">Buscando dados no VHSys...</h3><p style="color:#64748b;font-size:14px;line-height:1.6;">Estamos buscando no banco de dados do VHSys.<br>Esta funcao pode demorar um pouco, aguarde.</p></div><style>@keyframes spin{to{transform:rotate(360deg)}}</style>';document.body.appendChild(o)}
function removerLoad(){var o=document.getElementById('ovLoad');if(o)o.remove()}
function buscarPeriodo(ini,fim){fetch('/buscar_periodo?data_inicial='+ini+'&data_final='+fim).then(function(r){return r.json()}).then(function(d){if(d.status==='ok'){var ids=new Set(TP.map(function(p){return p.id}));d.pedidos.forEach(function(p){if(!ids.has(p.id)){TP.push(p);ids.add(p.id)}});if(!loadedRange.start||ini<loadedRange.start)loadedRange.start=ini;if(!loadedRange.end||fim>loadedRange.end)loadedRange.end=fim}removerLoad();renderTudo()}).catch(function(){removerLoad();alert('Erro ao buscar dados. Tente novamente.')})}
function renderTudo(){var ini=document.getElementById('dIni').value,fim=document.getElementById('dFim').value;var ped=TP.filter(function(p){return p.data>=ini&&p.data<=fim});if(ef!=='todos')ped=ped.filter(function(p){return p.empresa===ef});var mr=fim.substring(0,7);document.getElementById('mesL').textContent=fm2(mr);var hoje=new Date();var maStr=hoje.getFullYear()+'-'+String(hoje.getMonth()+1).padStart(2,'0');var fma=TP.filter(function(p){return p.data.substring(0,7)===maStr&&(ef==='todos'||p.empresa===ef)}).reduce(function(s,p){return s+p.valor},0);if(ped.length===0){msd()}else{var pv={};ped.forEach(function(p){var v=nn(p.vendedor);if(!pv[v])pv[v]={n:v,f:0,q:0,e:p.empresa};pv[v].f+=p.valor;pv[v].q+=1});var vs=Object.values(pv).sort(function(a,b){return b.f-a.f});vs.forEach(function(v){v.f=Math.round(v.f*100)/100});var ft=vs.reduce(function(s,v){return s+v.f},0),qv=vs.reduce(function(s,v){return s+v.q},0),tm=qv>0?ft/qv:0,dp=cd(ini,fim);rk(ft,qv,tm,dp,vs.length);rm(vs,mr,fma,maStr);rcV(vs);rcD(ped);rcK(vs,ft);rt(vs,ft);rc(ped,ft,qv)}var ent=TE.filter(function(e){return e.data>=ini&&e.data<=fim});re(ent,ini,fim)}
function sw(t,b){var map={'comercial':'tc-com','logistica':'tc-log','contabil':'tc-con'};document.querySelectorAll('.tc').forEach(function(x){x.classList.remove('act')});document.querySelectorAll('.tab').forEach(function(x){x.classList.remove('act')});document.getElementById(map[t]).classList.add('act');b.classList.add('act');var fbE=document.getElementById('fbEmp');if(fbE){if(t==='logistica'){fbE.style.display='none'}else{fbE.style.display='flex'}}setTimeout(function(){try{if(t==='comercial'){if(cV)cV.resize();if(cD)cD.resize();if(cK)cK.resize()}else if(t==='logistica'){if(cE)cE.resize();if(cED)cED.resize()}}catch(e){}},50)}
function nn(n){if(!n)return'Sem vendedor';return String(n).replace(/[\xa0\t
\r]/g,' ').replace(/\s+/g,' ').trim()}
function bm(n){var nl=n.toLowerCase();var k=Object.keys(M).find(function(x){return x.toLowerCase()===nl});return k?M[k]:0}
function fm(v){return'R$ '+Number(v).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})}
function fd(i){var p=i.split('-');return p[2]+'/'+p[1]}
function cd(i,f){var d1=new Date(i+'T00:00:00');var d2=new Date(f+'T00:00:00');return Math.round((d2-d1)/86400000)+1}
function fm2(mr){var p=mr.split('-');var n=['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];return n[parseInt(p[1])-1]+' '+p[0]}
function init(){var h=new Date().toISOString().split('T')[0];document.getElementById('dIni').value=h;document.getElementById('dFim').value=h;var hoje=new Date();var p=new Date(hoje.getFullYear(),hoje.getMonth(),1).toISOString().split('T')[0];var u=new Date(hoje.getFullYear(),hoje.getMonth()+1,0).toISOString().split('T')[0];loadedRange={start:p,end:u};renderTudo()}
function se(e,b){ef=e;document.querySelectorAll('.be').forEach(function(x){x.classList.remove('act')});if(b)b.classList.add('act');af()}
function ph(){var h=new Date().toISOString().split('T')[0];sd(h,h)}
function p7(){var f=new Date();var i=new Date();i.setDate(i.getDate()-6);sd(i.toISOString().split('T')[0],f.toISOString().split('T')[0])}
function pm(){var a=new Date();var i=new Date(a.getFullYear(),a.getMonth(),1);var f=new Date(a.getFullYear(),a.getMonth()+1,0);sd(i.toISOString().split('T')[0],f.toISOString().split('T')[0])}
function pt(){sd('__MIN__','__MAX__')}
function sd(i,f){document.getElementById('dIni').value=i;document.getElementById('dFim').value=f;af()}
function af(){var ini=document.getElementById('dIni').value,fim=document.getElementById('dFim').value;if(!ini||!fim)return;if(loadedRange.start&&(ini<loadedRange.start||fim>loadedRange.end)){mostrarLoad();buscarPeriodo(ini,fim);return}renderTudo()}
function rk(ft,qv,tm,dp,nv){var el='Consolidado';if(ef==='REAL MAIS')el='REAL MAIS';else if(ef==='GP DISTRIBUIDORA')el='GP';document.getElementById('kpi').innerHTML='<div class="kc"><div class="kl">Faturamento '+el+'</div><div class="kv">'+fm(ft)+'</div><div class="ks">'+dp+' dia(s)</div></div><div class="kc grn"><div class="kl">Vendas</div><div class="kv">'+qv+'</div><div class="ks">nao cancelados</div></div><div class="kc amb"><div class="kl">Ticket Medio</div><div class="kv">'+fm(tm)+'</div><div class="ks">por venda</div></div><div class="kc pur"><div class="kl">Vendedoras Ativas</div><div class="kv">'+nv+'</div><div class="ks">no periodo</div></div>'}
function rc(ped,ft,qv){var pe={};ped.forEach(function(p){if(!pe[p.empresa])pe[p.empresa]={f:0,q:0};pe[p.empresa].f+=p.valor;pe[p.empresa].q+=1});document.getElementById('kpiC').innerHTML='<div class="kc"><div class="kl">Faturamento Total</div><div class="kv">'+fm(ft)+'</div><div class="ks">'+qv+' venda(s)</div></div><div class="kc grn"><div class="kl">REAL MAIS</div><div class="kv">'+fm(pe['REAL MAIS']?pe['REAL MAIS'].f:0)+'</div><div class="ks">'+(pe['REAL MAIS']?pe['REAL MAIS'].q:0)+' venda(s)</div></div><div class="kc amb"><div class="kl">GP DISTRIBUIDORA</div><div class="kv">'+fm(pe['GP DISTRIBUIDORA']?pe['GP DISTRIBUIDORA'].f:0)+'</div><div class="ks">'+(pe['GP DISTRIBUIDORA']?pe['GP DISTRIBUIDORA'].q:0)+' venda(s)</div></div><div class="kc pur"><div class="kl">Ticket Geral</div><div class="kv">'+fm(qv>0?ft/qv:0)+'</div><div class="ks">consolidado</div></div>';var h='';Object.entries(pe).sort(function(a,b){return b[1].f-a[1].f}).forEach(function(entry,i){var n=entry[0],d=entry[1];var p=ft>0?(d.f/ft*100):0;var t=d.q>0?d.f/d.q:0;var c=C[i%C.length];h+='<tr><td class="vn"><span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:'+c+';margin-right:8px"></span>'+n+'</td><td class="vc">'+fm(d.f)+'</td><td>'+d.q+'</td><td>'+fm(t)+'</td><td><span class="pb"><span class="pf" style="width:'+p+'%;background:'+c+'"></span></span>'+p.toFixed(1)+'%</td></tr>'});document.getElementById('tbEmp').innerHTML=h}
function rm(vs,mr,fma,maStr){var h='';var pvMes={};TP.filter(function(p){return p.data.substring(0,7)===maStr&&(ef==='todos'||p.empresa===ef)}).forEach(function(p){var v=nn(p.vendedor);if(!pvMes[v])pvMes[v]={f:0,q:0};pvMes[v].f+=p.valor;pvMes[v].q+=1});if(ef==='todos'){var tm2=MC,tf=fma,pc=tm2>0?(tf/tm2*100):0,pb=Math.min(pc,100),fl=Math.max(tm2-tf,0);var sc,st,cb;if(pc>=100){sc='sb';st='Meta atingida';cb='#16a34a'}else if(pc>=70){sc='sp';st='Quase la';cb='#f59e0b'}else{sc='sl';st='Em progresso';cb='#dc2626'}var tv=TP.filter(function(p){return p.data.substring(0,7)===maStr}).reduce(function(s,p){return s+1},0);var nm=fm2(maStr);var tf2='';if(tm2>0&&pc<100){tf2='Faltam <strong style="color:#fff">'+fm(fl)+'</strong> para a meta de '+nm}else if(tm2>0&&pc>=100){tf2='Superou a meta de '+nm+' em <strong style="color:#fff">'+fm(tf-tm2)+'</strong>'}h+='<div class="mc con"><div class="mh"><div class="ma" style="background:#fff;color:#2563eb">C</div><div><div class="mn">META CONSOLIDADA - '+nm+'</div><div class="ms">'+tv+' venda(s) em '+nm+' - Ticket: '+fm(tv>0?tf/tv:0)+'</div></div></div><div class="mpb"><div class="mpf" style="width:'+pb+'%;background:'+cb+'">'+pc.toFixed(0)+'%</div></div><div class="mst"><div><span class="mv">'+fm(tf)+'</span><span style="color:rgba(255,255,255,.7);font-size:13px"> / '+fm(tm2)+'</span></div><span class="msb '+sc+'">'+st+'</span></div>'+(tf2?'<div class="mf">'+tf2+'</div>':'')+'</div>'}var nw=new Set(vs.map(function(v){return v.n.toLowerCase()}));var td=vs.slice();Object.keys(M).forEach(function(n){if(!nw.has(n.toLowerCase())){var ee=(n==='GP DISTRIBUIDORA')?'GP DISTRIBUIDORA':'REAL MAIS';if(ef==='todos'||ef===ee)td.push({n:n,f:0,q:0,e:ee})}});td.sort(function(a,b){var ma2=bm(a.n),mb2=bm(b.n);var fa=pvMes[a.n]?pvMes[a.n].f:0;var fb=pvMes[b.n]?pvMes[b.n].f:0;return(mb2>0?fb/mb2:0)-(ma2>0?fa/ma2:0)});td.forEach(function(v,i){var m2=bm(v.n),c=C[i%C.length],ini=v.n.split(' ').map(function(p){return p[0]}).join('').substring(0,2).toUpperCase();var fatMes=pvMes[v.n]?pvMes[v.n].f:0;var qtdMes=pvMes[v.n]?pvMes[v.n].q:0;var pm2=m2>0?(fatMes/m2*100):0,pb2=Math.min(pm2,100);var sc,st,cb;if(m2===0){sc='sn';st='Sem meta';cb='#94a3b8'}else if(pm2>=100){sc='sb';st='Batida';cb='#16a34a'}else if(pm2>=70){sc='sp';st='Quase';cb='#f59e0b'}else{sc='sl';st='Progresso';cb='#dc2626'}var fl=m2>0?Math.max(m2-fatMes,0):0,tm3=qtdMes>0?fatMes/qtdMes:0;var tf3='';if(m2>0&&pm2<100){tf3='Faltam <strong>'+fm(fl)+'</strong>'}else if(m2>0&&pm2>=100){tf3='Superou <strong>'+fm(fatMes-m2)+'</strong>'}var be=v.e==='GP DISTRIBUIDORA'?'<span style="background:#fef3c7;color:#f59e0b;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:700;margin-left:8px">GP</span>':'<span style="background:#dbeafe;color:#2563eb;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:700;margin-left:8px">RM</span>';h+='<div class="mc"><div class="mh"><div class="ma" style="background:'+c+'">'+ini+'</div><div><div class="mn">'+v.n+be+'</div><div class="ms">'+qtdMes+' venda(s) - Ticket: '+fm(tm3)+'</div></div></div><div class="mpb"><div class="mpf" style="width:'+pb2+'%;background:'+cb+'">'+pm2.toFixed(0)+'%</div></div><div class="mst"><div><span class="mv '+(pm2>=100?'at':'')+'">'+fm(fatMes)+'</span><span style="color:var(--mut);font-size:13px"> / '+(m2>0?fm(m2):'-')+'</span></div><span class="msb '+sc+'">'+st+'</span></div>'+(tf3?'<div class="mf">'+tf3+'</div>':'')+'</div>'});document.getElementById('metas').innerHTML=h}
function tmp(){var p=document.getElementById('mp');if(p.classList.contains('act')){p.classList.remove('act');return}p.classList.add('act');var h='';Object.keys(M).forEach(function(n){h+='<div class="mer"><div class="mel">'+n+'</div><input type="number" id="m_'+n.replace(/\s+/g,'_')+'" value="'+M[n]+'" step="0.01" style="padding:8px;border:2px solid var(--brd);border-radius:8px;width:180px"></div>'});h+='<div class="mer"><div class="mel"><strong>CONSOLIDADA</strong></div><input type="number" id="m_c" value="'+MC+'" step="0.01" style="padding:8px;border:2px solid var(--brd);border-radius:8px;width:180px"></div>';document.getElementById('mef').innerHTML=h}
function svm(){var d={};Object.keys(M).forEach(function(n){var e=document.getElementById('m_'+n.replace(/\s+/g,'_'));if(e)d[n]=parseFloat(e.value)||0});var ec=document.getElementById('m_c');if(ec)d['_consolidada']=parseFloat(ec.value)||0;fetch('/api/metas',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)}).then(function(r){return r.json()}).then(function(x){if(x.status==='ok'){alert('Metas salvas!');location.reload()}else alert('Erro')}).catch(function(e){alert('Erro:'+e)})}
function re(ent,ini,fim){if(!ent||ent.length===0){document.getElementById('kpiE').innerHTML='<div class="nd">Nenhuma entrega no periodo.</div>';document.getElementById('tbE').innerHTML='';if(cE)cE.destroy();if(cED)cED.destroy();return}var pe={},pd={};ent.forEach(function(e){var nome=e.entregador;if(!pe[nome])pe[nome]=0;pe[nome]++;if(!pd[e.data])pd[e.data]=0;pd[e.data]++});var te=ent.length,er=Object.keys(pe).filter(function(n){return n!=='RETIRADA'}),ter=er.length,tr=pe['RETIRADA']||0,dp=cd(ini,fim);document.getElementById('kpiE').innerHTML='<div class="kc tel"><div class="kl">Total Entregas</div><div class="kv">'+te+'</div><div class="ks">'+dp+' dia(s)</div></div><div class="kc"><div class="kl">Entregadores</div><div class="kv">'+ter+'</div><div class="ks">ativos</div></div><div class="kc amb"><div class="kl">Retiradas</div><div class="kv">'+tr+'</div><div class="ks">no balcao</div></div><div class="kc grn"><div class="kl">Media</div><div class="kv">'+(ter>0?(te/ter).toFixed(0):0)+'</div><div class="ks">por pessoa</div></div>';var x=document.getElementById('cE').getContext('2d');if(cE)cE.destroy();var eo=Object.entries(pe).sort(function(a,b){return b[1]-a[1]}).filter(function(entry){return entry[0]!=='RETIRADA'});cE=new Chart(x,{type:'bar',data:{labels:eo.map(function(x){return x[0]}),datasets:[{data:eo.map(function(x){return x[1]}),backgroundColor:eo.map(function(_,i){return C[i%C.length]+'cc'}),borderColor:eo.map(function(_,i){return C[i%C.length]}),borderWidth:2,borderRadius:6}]},options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{x:{ticks:{stepSize:1}}}}});var x2=document.getElementById('cED').getContext('2d');if(cED)cED.destroy();var tk=Object.keys(pd).sort(),dc=[],vd=[];tk.forEach(function(d){if(pd[d]>0){dc.push(d);vd.push(pd[d])}});var g=x2.createLinearGradient(0,0,0,320);g.addColorStop(0,'rgba(20,184,166,0.3)');g.addColorStop(1,'rgba(20,184,166,0.02)');cED=new Chart(x2,{type:'line',data:{labels:dc.map(fd),datasets:[{data:vd,borderColor:'#14b8a6',backgroundColor:g,borderWidth:3,fill:true,tension:0.3,pointRadius:4,pointBackgroundColor:'#14b8a6'}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false}},scales:{y:{ticks:{stepSize:1}}}}});var h='';Object.entries(pe).sort(function(a,b){return b[1]-a[1]}).forEach(function(entry,i){var n=entry[0],q=entry[1];var p=te>0?(q/te*100):0;var c=C[i%C.length];h+='<tr><td class="vn"><span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:'+c+';margin-right:8px"></span>'+(n==='RETIRADA'?'RETIRADA':n)+'</td><td>'+q+'</td><td><span class="pb"><span class="pf" style="width:'+p+'%;background:'+c+'"></span></span>'+p.toFixed(1)+'%</td></tr>'});document.getElementById('tbE').innerHTML=h}
function rcV(v){var x=document.getElementById('cV').getContext('2d');if(cV)cV.destroy();cV=new Chart(x,{type:'bar',data:{labels:v.map(function(x){return x.n}),datasets:[{data:v.map(function(x){return x.f}),backgroundColor:v.map(function(_,i){return C[i%C.length]+'cc'}),borderColor:v.map(function(_,i){return C[i%C.length]}),borderWidth:2,borderRadius:6}]},options:{indexAxis:'y',responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:function(c){return fm(c.raw)}}}},scales:{x:{ticks:{callback:function(v){return'R$ '+v.toLocaleString('pt-BR')}}}}}})}
function rcD(ped){var x=document.getElementById('cD').getContext('2d');if(cD)cD.destroy();var pd={};ped.forEach(function(p){if(!pd[p.data])pd[p.data]=0;pd[p.data]+=p.valor});var dk=Object.keys(pd).sort(),vl=dk.map(function(d){return pd[d]});var g=x.createLinearGradient(0,0,0,320);g.addColorStop(0,'rgba(37,99,235,0.3)');g.addColorStop(1,'rgba(37,99,235,0.02)');cD=new Chart(x,{type:'line',data:{labels:dk.map(fd),datasets:[{data:vl,borderColor:'#2563eb',backgroundColor:g,borderWidth:3,fill:true,tension:0.3,pointRadius:4,pointBackgroundColor:'#2563eb'}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{display:false},tooltip:{callbacks:{label:function(c){return fm(c.raw)}}}},scales:{y:{ticks:{callback:function(v){return'R$ '+v.toLocaleString('pt-BR')}}}}}})}
function rcK(v,ft){var x=document.getElementById('cK').getContext('2d');if(cK)cK.destroy();cK=new Chart(x,{type:'doughnut',data:{labels:v.map(function(x){return x.n}),datasets:[{data:v.map(function(x){return x.f}),backgroundColor:v.map(function(_,i){return C[i%C.length]}),borderColor:'#fff',borderWidth:3}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{position:'right',labels:{padding:16,font:{size:13}}},tooltip:{callbacks:{label:function(c){var p=((c.raw/ft)*100).toFixed(1);return c.label+': '+fm(c.raw)+' ('+p+'%)'}}}}}})}
function rt(v,ft){var h='';v.forEach(function(x,i){var p=ft>0?(x.f/ft*100):0;var t=x.q>0?x.f/x.q:0;var m2=bm(x.n),pm2=m2>0?(x.f/m2*100):0;var c=C[i%C.length],cm=pm2>=100?'#16a34a':pm2>=70?'#f59e0b':'#dc2626';var be=x.e==='GP DISTRIBUIDORA'?'<span style="background:#fef3c7;color:#f59e0b;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:700">GP</span>':'<span style="background:#dbeafe;color:#2563eb;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:700">RM</span>';h+='<tr><td class="vn"><span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:'+c+';margin-right:8px"></span>'+x.n+'</td><td>'+be+'</td><td class="vc">'+fm(x.f)+'</td><td>'+x.q+'</td><td>'+fm(t)+'</td><td>'+(m2>0?fm(m2):'-')+'</td><td><span class="pb"><span class="pf" style="width:'+Math.min(pm2,100)+'%;background:'+cm+'"></span></span><strong style="color:'+cm+'">'+pm2.toFixed(0)+'%</strong></td><td><span class="pb"><span class="pf" style="width:'+p+'%;background:'+c+'"></span></span>'+p.toFixed(1)+'%</td></tr>'});document.getElementById('tb').innerHTML=h}
function msd(){document.getElementById('kpi').innerHTML='<div class="nd">Nenhum pedido no periodo.</div>';document.getElementById('metas').innerHTML='';document.getElementById('tb').innerHTML='';document.getElementById('kpiC').innerHTML='<div class="nd">Sem dados.</div>';document.getElementById('tbEmp').innerHTML='';if(cV)cV.destroy();if(cD)cD.destroy();if(cK)cK.destroy()}
function calcCMV(){var i=document.getElementById('cmvDi').value,f=document.getElementById('cmvDf').value;if(!i||!f){alert('Selecione as datas');return}var ei=document.getElementById('cmvEi').value||0,eig=document.getElementById('cmvEig').value||0,ef=document.getElementById('cmvEf').value||0,efg=document.getElementById('cmvEfg').value||0;document.getElementById('cmvR').innerHTML='<div class="kc" style="text-align:center;padding:40px"><div style="width:40px;height:40px;border:4px solid #dbeafe;border-top-color:#2563eb;border-radius:50%;margin:0 auto 16px;animation:sp 1s linear infinite"></div><p style="color:#64748b">Buscando compras...</p></div><style>@keyframes sp{to{transform:rotate(360deg)}}</style>';bCMV(i,f,ei,eig,ef,efg)}
function bCMV(i,f,ei,eig,ef,efg){fetch('/cmv?data_inicial='+i+'&data_final='+f+'&est_ini_rm='+ei+'&est_ini_gp='+eig+'&est_fin_rm='+ef+'&est_fin_gp='+efg).then(function(r){return r.json()}).then(function(d){if(d.status==='calculando'||d.status==='iniciando'){setTimeout(function(){bCMV(i,f,ei,eig,ef,efg)},5000)}else if(d.status==='erro'){document.getElementById('cmvR').innerHTML='<div class="kc red"><div class="kl">Erro</div><div class="kv" style="font-size:16px">'+d.erro+'</div></div>'}else{rCMV(d)}}).catch(function(){setTimeout(function(){bCMV(i,f,ei,eig,ef,efg)},5000)})}
function rCMV(d){var f=function(v){return'R$ '+Number(v).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})};document.getElementById('cmvR').innerHTML='<div class="tc2"><div class="ct">CMV de '+d.data_inicial.split('-').reverse().join('/')+' a '+d.data_final.split('-').reverse().join('/')+'</div><table><thead><tr><th>Componente</th><th>REAL MAIS</th><th>GP</th><th>Total</th></tr></thead><tbody><tr><td class="vn">(+) Estoque Inicial</td><td class="vc">'+f(d.estoque_inicial_rm)+'</td><td class="vc">'+f(d.estoque_inicial_gp)+'</td><td class="vc" style="font-size:16px">'+f(d.estoque_inicial_total)+'</td></tr><tr><td class="vn">(+) Compras (auto)</td><td class="vc">'+f(d.compras_rm)+'</td><td class="vc">'+f(d.compras_gp)+'</td><td class="vc" style="font-size:16px">'+f(d.compras_total)+'</td></tr><tr><td class="vn">(-) Estoque Final</td><td>'+f(d.estoque_final_rm)+'</td><td>'+f(d.estoque_final_gp)+'</td><td style="font-size:16px">'+f(d.estoque_final_total)+'</td></tr><tr style="border-top:3px solid #2563eb"><td class="vn" style="font-size:16px">= CMV</td><td></td><td></td><td class="vc" style="font-size:20px;color:#dc2626">'+f(d.cmv)+'</td></tr></tbody></table></div>'}
document.addEventListener('keydown',function(e){if(e.key==='Enter'&&e.target.type==='date')af()});
window.addEventListener('DOMContentLoaded',init);


'''
    html = html.replace("__DJ__", dj).replace("__EJ__", ej).replace("__MJ__", mj).replace("__MC__", str(mc)).replace("__DG__", dg).replace("__MIN__", mind).replace("__MAX__", maxd)
    return html

LOADING_HTML = '''Carregando...body{font-family:sans-serif;background:#f0f2f5;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0}.l{text-align:center;padding:40px;background:#fff;border-radius:16px;box-shadow:0 4px 6px rgba(0,0,0,.07)}.s{width:50px;height:50px;border:5px solid #dbeafe;border-top-color:#2563eb;border-radius:50%;margin:0 auto 20px;animation:sp 1s linear infinite}@keyframes sp{to{transform:rotate(360deg)}}h1{color:#1e293b;font-size:20px}p{color:#64748b;font-size:14px}#erro{color:#dc2626;font-size:14px;margin-top:12px;display:none}#retry{display:none;margin-top:16px;padding:10px 24px;background:#2563eb;color:#fff;border:none;border-radius:8px;cursor:pointer;font-size:14px}function check(){fetch('/status').then(function(r){return r.json()}).then(function(d){if(d.erro){document.getElementById('s').style.display='none';document.getElementById('h').textContent='Erro ao buscar dados';document.getElementById('p').textContent=d.erro;document.getElementById('erro').style.display='block';document.getElementById('retry').style.display='inline-block'}else if(d.tem_html){window.location.reload()}else{setTimeout(check,3000)}}).catch(function(){setTimeout(check,5000)})}check()Buscando dados...Coletando vendas do mes atual no VHSys.Tentar novamente(c) 2026 Real Acai Distribuidora - Desenvolvido por Gabriel Freitas - v1.0.0'''

@app.route('/logo')
def logo():
    caminhos = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Logo_Real_Distribuidora.png'),
        os.path.join(os.getcwd(), 'Logo_Real_Distribuidora.png'),
        'Logo_Real_Distribuidora.png',
        '/app/Logo_Real_Distribuidora.png',
    ]
    for c in caminhos:
        if os.path.isfile(c):
            return send_file(c, mimetype='image/png')
    matches = glob.glob('**/*ogo*.png', recursive=True)
    if matches:
        return send_file(matches[0], mimetype='image/png')
    pixel = b'\x89PNG\r
\x1a
\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\xfe\x02\xfe\xdc\xcc\x59\xe7\x00\x00\x00\x00IEND\xaeB`\x82'
    return Response(pixel, mimetype='image/png')

@app.route('/')
def dashboard():
    with _cache_lock:
        if _cache["html"] and (time.time() - _cache["timestamp"]) < CACHE_TEMPO_SEGUNDOS:
            return _cache["html"]
        if _cache["buscando"]:
            return LOADING_HTML
        if _cache["erro"]:
            return f"Erro ao buscar dados:{_cache['erro']}Tentar novamente"
    threading.Thread(target=buscar_dados_background, daemon=True).start()
    return LOADING_HTML

@app.route('/status')
def status():
    with _cache_lock:
        return jsonify({"tem_html": bool(_cache["html"]), "buscando": _cache["buscando"], "erro": _cache["erro"], "timestamp": _cache["timestamp"]})

@app.route('/atualizar')
def forcar_atualizacao():
    with _cache_lock:
        _cache["timestamp"] = 0
        _cache["html"] = ""
        _cache["buscando"] = False
    threading.Thread(target=buscar_dados_background, daemon=True).start()
    return "window.location.href='/';"

@app.route('/buscar_periodo')
def buscar_periodo_endpoint():
    di = request.args.get('data_inicial', '')
    df = request.args.get('data_final', '')
    if not di or not df:
        return jsonify({"status": "erro", "erro": "Datas nao informadas"})
    ano_i = int(di[:4]); mes_i = int(di[5:7])
    ano_f = int(df[:4]); mes_f = int(df[5:7])
    tarefas = []
    ano = ano_i; mes = mes_i
    while (ano < ano_f) or (ano == ano_f and mes <= mes_f):
        for emp in EMPRESAS:
            tarefas.append((ano, mes, emp))
        mes += 1
        if mes > 12:
            mes = 1; ano += 1
    todos = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        fs = {ex.submit(buscar_dados_de_mes, a, m, e): (m, e["nome"]) for (a, m, e) in tarefas}
        for f in as_completed(fs):
            try: todos.extend(f.result())
            except: pass
    return jsonify({"status": "ok", "pedidos": todos})

@app.route('/cmv')
def cmv_endpoint():
    di = request.args.get('data_inicial', '')
    df = request.args.get('data_final', '')
    eirm = float(request.args.get('est_ini_rm', 0) or 0)
    eigp = float(request.args.get('est_ini_gp', 0) or 0)
    efrm = float(request.args.get('est_fin_rm', 0) or 0)
    efgp = float(request.args.get('est_fin_gp', 0) or 0)
    if not di or not df:
        return jsonify({"status": "erro", "erro": "Datas nao informadas"})
    pk = f"{di}_{df}_{eirm}_{eigp}_{efrm}_{efgp}"
    with _cmv_lock:
        if _cmv_cache["data"] and _cmv_cache["params"] == pk and not _cmv_cache["calculando"]:
            return jsonify(_cmv_cache["data"])
        if _cmv_cache["calculando"] and _cmv_cache["params"] == pk:
            return jsonify({"status": "calculando"})
    threading.Thread(target=calcular_cmv_background, args=(di, df, eirm, eigp, efrm, efgp), daemon=True).start()
    return jsonify({"status": "iniciando"})

@app.route('/api/metas', methods=['GET', 'POST'])
def api_metas():
    global _metas_consolidada
    if request.method == 'GET':
        with _metas_lock:
            return jsonify({"metas": _metas, "consolidada": _metas_consolidada})
    dados = request.get_json()
    if not dados:
        return jsonify({"status": "erro", "erro": "Dados nao enviados"}), 400
    with _metas_lock:
        if '_consolidada' in dados:
            _metas_consolidada = float(dados['_consolidada'])
        for k, v in dados.items():
            if k != '_consolidada':
                _metas[k] = float(v)
    with _cache_lock:
        _cache["timestamp"] = 0
        _cache["html"] = ""
    return jsonify({"status": "ok"})

def init_background():
    buscar_dados_background()

threading.Thread(target=init_background, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"Dashboard online em http://0.0.0.0:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
