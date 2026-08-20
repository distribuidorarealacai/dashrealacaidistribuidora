#!/usr/bin/env python3
"""
dash_flask_ofc.py  (v12 - CORRIGIDO - com painel de entrada e novo token REAL MAIS)
"""
import os, sys, json, csv, io, re, time, threading, glob, base64
from datetime import datetime, date
from calendar import monthrange
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from flask import Flask, request, jsonify, send_file, Response, render_template_string
app = Flask(__name__)
import hashlib, secrets
from flask import session, redirect, url_for
app.secret_key = secrets.token_hex(32)

# ===== MÓDULO SOU MOTORISTA =====
import sqlite3
from werkzeug.security import generate_password_hash, check_password_hash
import os
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'motoristas.db')

from functools import wraps

def login_necessario(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return wrapper

# ⚠️ TROQUE ESTA SENHA pela senha do Admin Master
ADMIN_SENHA = 'Xd@132429'

def get_db():
    db = sqlite3.connect('motoristas.db')
    db.row_factory = sqlite3.Row
    return db

def init_motorista_db():
    db = get_db()
    db.execute('''CREATE TABLE IF NOT EXISTS veiculos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        placa TEXT UNIQUE NOT NULL,
        descricao TEXT
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS motoristas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        usuario TEXT UNIQUE NOT NULL,
        senha_hash TEXT NOT NULL
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS abastecimentos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        motorista_id INTEGER,
        veiculo_id INTEGER,
        data TEXT,
        litros REAL,
        km INTEGER,
        valor REAL,
        FOREIGN KEY (motorista_id) REFERENCES motoristas(id),
        FOREIGN KEY (veiculo_id) REFERENCES veiculos(id)
    )''')
    db.commit()
    db.close()

init_motorista_db()

def corrigir_estrutura_banco():
    db = get_db()
    try:
        colunas_veic = [r[1] for r in db.execute('PRAGMA table_info(veiculos)').fetchall()]
        colunas_mot = [r[1] for r in db.execute('PRAGMA table_info(motoristas)').fetchall()]
        if 'km_atual' in colunas_veic or 'veiculo_id' in colunas_mot:
            db.close()
            os.remove('motoristas.db')
            init_motorista_db()
            return
    except Exception:
        pass
    db.close()

corrigir_estrutura_banco()

def corrigir_estrutura_banco():
    """Recria o banco se a tabela motoristas tiver a estrutura antiga (com veiculo_id)."""
    db = get_db()
    try:
        colunas = [r[1] for r in db.execute('PRAGMA table_info(motoristas)').fetchall()]
        if 'veiculo_id' in colunas:
            db.close()
            os.remove('motoristas.db')
            init_motorista_db()
            return
    except Exception:
        pass
    db.close()

corrigir_estrutura_banco()

USERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'users.json')

def hash_senha(senha):
    return hashlib.sha256(senha.encode('utf-8')).hexdigest()

def carregar_usuarios():
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    admin_padrao = {
        "admin": {
            "nome": "Administrador Master",
            "senha_hash": hash_senha("Xd@132429"),
            "role": "admin_master",
            "setor": "all"
        }
    }
    salvar_usuarios(admin_padrao)
    return admin_padrao

def salvar_usuarios(users):
    with open(USERS_FILE, 'w', encoding='utf-8') as f:
        json.dump(users, f, ensure_ascii=False, indent=2)

def usuario_logado():
    if 'user' not in session:
        return None
    users = carregar_usuarios()
    u = users.get(session['user'])
    if not u:
        session.clear()
        return None
    return {"username": session['user'], "nome": u["nome"], "role": u["role"], "setor": u["setor"]}

def requer_login(f):
    def wrap(*args, **kwargs):
        u = usuario_logado()
        if not u:
            return redirect('/login')
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__
    return wrap

def requer_admin_master(f):
    def wrap(*args, **kwargs):
        u = usuario_logado()
        if not u:
            return redirect('/login')
        if u["role"] != 'admin_master':
            return '<h1 style="color:red;text-align:center;margin-top:100px;font-family:sans-serif">Acesso negado. Apenas o Administrador Master.</h1>'
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__
    return wrap

SETORES = {
    "comercial": "Comercial",
    "logistica": "Logistica",
    "contabil": "Contabil",
    "all": "Todas as abas"
}

EMPRESAS = [
    {"nome": "REAL MAIS", "access_token": "afYgGNDHGUUfOTJAHfDMGISOaTZQLH", "secret_token": "d7uCnP9cJSZ8PrjQ5xifLYp9Ig2Hiu", "endpoint": "/pedidos/", "data_field": "data_pedido", "order_field": "data_pedido"},
    {"nome": "GP DISTRIBUIDORA", "access_token": "EdPfRWCOGgefDeVcSNNaGJLJeZDMST", "secret_token": "5P4nmO1ONthN5oqfX81lHKX5i0YC3dm", "endpoint": "/vendas-balcao/", "data_field": "data_cad_pedido", "order_field": "data_cad_pedido"},
]
BASE_URL = "https://api.vhsys.com/v2"
STATUS_INCLUIDOS = {"Atendido", "Em Andamento", "Em Aberto"}
SPREADSHEET_ID = "10rPC_-MxKm6o0L1SjHanXuKm0LjEIezjhoclNPlzpfc"

METAS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'metas.json')
_metas_lock = threading.Lock()

def carregar_metas():
    if os.path.exists(METAS_FILE):
        try:
            with open(METAS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    default = {"2026-08": {"nome_mes": "Agosto 2026", "consolidada": 1005277.76, "vendedoras": {"SIMONE MOURA": 215000.00, "ISA": 241500.00, "ANA RUTH": 65000.00, "GP DISTRIBUIDORA": 100000.00}}}
    salvar_metas(default)
    return default

def salvar_metas(metas):
    with open(METAS_FILE, 'w', encoding='utf-8') as f:
        json.dump(metas, f, ensure_ascii=False, indent=2)

def obter_metas_mes(mes_ano):
    metas = carregar_metas()
    return metas.get(mes_ano, {"nome_mes": "", "consolidada": 0, "vendedoras": {}})

CORES = ['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#14b8a6','#f97316','#6366f1','#84cc16','#06b6d4','#a855f7']
CACHE_TEMPO_SEGUNDOS = 1800
_cache_lock = threading.Lock()
_cache = {"timestamp": 0, "html": "", "erro": ""}
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
    s = str(n).replace('\xa0',' ').replace('\t',' ').replace('\n',' ').replace('\r',' ')
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

def buscar_dados_mes_atual():
    hoje = date.today()
    ano = hoje.year
    mes = hoje.month
    print(f"[DEBUG] Buscando {ano}/{mes}", flush=True)
    tarefas = [(ano, mes, emp) for emp in EMPRESAS]
    todos = []
    with ThreadPoolExecutor(max_workers=16) as ex:
        fs = {ex.submit(buscar_dados_de_mes, a, m, e): (m, e["nome"]) for (a, m, e) in tarefas}
        for f in as_completed(fs):
            try:
                result = f.result()
                todos.extend(result)
                print(f"[DEBUG] {len(result)} pedidos", flush=True)
            except Exception as ex2:
                print(f"[DEBUG] ERRO: {ex2}", flush=True)
    print(f"[DEBUG] Total: {len(todos)}", flush=True)
    return todos


PAGINA_INICIAL = '''<!DOCTYPE html>
<html lang="pt-br">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Real Açaí Distribuidora</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;}
body{font-family:'Segoe UI',Arial,sans-serif;background:#1a0b2e;color:#fff;}
header{display:flex;justify-content:space-between;align-items:center;padding:18px 40px;background:rgba(20,8,40,0.95);position:fixed;width:100%;top:0;z-index:100;}
.logo{display:flex;align-items:center;font-size:20px;font-weight:800;color:#c084fc;letter-spacing:1px;}
.logo img{height:45px;margin-right:10px;border-radius:8px;background:#fff;padding:4px 8px;object-fit:contain;}
.logo span{color:#fff;}
nav a{color:#e9d5ff;text-decoration:none;margin:0 14px;font-size:14px;font-weight:500;transition:color .2s;}
nav a:hover{color:#c084fc;}
.btn-login{border:2px solid #c084fc;color:#c084fc;padding:8px 18px;border-radius:25px;text-decoration:none;font-size:14px;font-weight:600;transition:all .2s;}
.btn-login:hover{background:#c084fc;color:#1a0b2e;}
.hero{min-height:100vh;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:120px 20px 60px;background:linear-gradient(rgba(91,45,145,0.72),rgba(91,45,145,0.82)),url('/fachada') center/cover no-repeat;background-color:#5b2d91;}
.badge{background:rgba(192,132,252,0.15);border:1px solid #c084fc;color:#e9d5ff;padding:8px 22px;border-radius:30px;font-size:14px;margin-bottom:22px;letter-spacing:0.5px;}
.hero h1{font-size:44px;font-weight:800;max-width:800px;line-height:1.2;margin-bottom:18px;}
.hero h1 .destaque{color:#c084fc;}
.hero p{font-size:18px;color:#d8b4fe;max-width:620px;line-height:1.7;margin-bottom:36px;}
.btn-pedido{background:#22c55e;color:#fff;padding:15px 42px;border-radius:30px;text-decoration:none;font-weight:700;font-size:17px;box-shadow:0 6px 20px rgba(34,197,94,0.35);transition:transform .2s,box-shadow .2s;}
.btn-pedido:hover{transform:translateY(-2px);box-shadow:0 10px 28px rgba(34,197,94,0.5);}
.versiculo{margin-top:55px;font-style:italic;color:#a78bfa;font-size:15px;letter-spacing:0.5px;}
.sec{padding:80px 40px;text-align:center;}
.sec h2{color:#c084fc;font-size:32px;margin-bottom:18px;}
.sec h2:after{content:'';display:block;width:60px;height:3px;background:#22c55e;margin:14px auto 0;border-radius:2px;}
.sec p{max-width:720px;margin:0 auto;color:#d8b4fe;line-height:1.9;font-size:17px;}
#historia{background:#221040;}
#fachada{background:#1a0b2e;}
#fachada img{width:100%;border-radius:16px;border:3px solid #3b1a6b;box-shadow:0 12px 40px rgba(0,0,0,0.5);}
#vendedoras{background:#1a0b2e;}
.vend-grid{display:flex;justify-content:center;gap:24px;flex-wrap:wrap;margin-top:30px;}
.vend-card{background:#221040;border:1px solid #3b1a6b;border-radius:14px;padding:28px 24px;width:250px;text-align:center;transition:transform .2s,box-shadow .2s;}
.vend-card:hover{transform:translateY(-4px);box-shadow:0 12px 30px rgba(0,0,0,0.4);}
.vend-card .avatar{width:90px;height:90px;border-radius:50%;background:#7c3aed;color:#fff;font-size:24px;font-weight:800;display:flex;align-items:center;justify-content:center;margin:0 auto 14px;overflow:hidden;border:3px solid #c084fc;position:relative;}
.vend-card .avatar img{width:100%;height:100%;object-fit:cover;position:absolute;top:0;left:0;z-index:1;}
.vend-card h3{font-size:17px;color:#fff;margin-bottom:4px;}
.vend-card .cargo{font-size:13px;color:#a78bfa;margin-bottom:10px;}
.vend-card .tel{font-size:14px;color:#e9d5ff;margin-bottom:14px;}
.btn-wa{display:inline-block;background:#25d366;color:#fff;text-decoration:none;padding:10px 20px;border-radius:25px;font-size:14px;font-weight:700;transition:background .2s;}
.btn-wa:hover{background:#1ebe5b;}
#local{background:#1a0b2e;}
.mapa{max-width:900px;margin:30px auto 0;border-radius:16px;overflow:hidden;border:3px solid #3b1a6b;box-shadow:0 12px 40px rgba(0,0,0,0.5);}
.mapa iframe{width:100%;height:400px;border:0;display:block;}
footer{text-align:center;padding:40px 20px;background:#12061f;color:#a78bfa;font-size:14px;border-top:1px solid #2a1448;}
footer .social{display:flex;justify-content:center;gap:16px;margin-bottom:16px;}
footer .social a{color:#c084fc;text-decoration:none;font-size:14px;font-weight:600;}
footer .social a:hover{color:#fff;}
footer .contato-rodape{margin-bottom:12px;font-size:13px;color:#a78bfa;}
footer .contato-rodape a{color:#e9d5ff;text-decoration:none;}
footer .contato-rodape a:hover{color:#c084fc;}
footer .copy{margin-top:16px;font-size:12px;color:#7c6ba8;}
@media(max-width:768px){
header{flex-direction:column;gap:12px;padding:15px 20px;position:static;}
nav a{margin:0 8px;font-size:13px;}
.hero h1{font-size:30px;}
.hero{padding-top:60px;}
.contato-item{min-width:100%;}
.mapa iframe{height:300px;}
}
</style>
</head>
<body>
<header>
<div class="logo"><img src="/logo" alt="Logo Real Açaí"></div>
<nav>
<a href="/">Início</a>
<a href="#historia">Nossa História</a>
<a href="#vendedoras">Vendedoras</a>
<a href="#contato">Contato</a>
<a href="#local">Localização</a>
</nav>
<a href="/login" class="btn-login">Login / Dashboard</a>
</header>

<section class="hero">
<span class="badge">✨ Tradição em cada detalhe</span>
<h1>A tradição e qualidade que você conhece, <span class="destaque">agora também online</span></h1>
<p>Há mais de 5 anos levando os melhores produtos para sua família. Faça seu pedido de onde estiver, receba com agilidade.</p>
<a href="https://wa.me/5585992885598?text=Ol%C3%A1%20Ana%20Ruth!%20Quero%20fazer%20um%20pedido" class="btn-pedido" target="_blank">🛒 Fazer Pedido</a>
<div class="versiculo">"Até aqui nos ajudou o Senhor" — 1 Samuel 7:12</div>
</section>

<section id="historia" class="sec">
<h2>Nossa História</h2>
<p>Há mais de 5 anos a Real Açaí Distribuidora leva qualidade, tradição e sabor autêntico para as famílias da nossa região. Começamos com um sonho e um propósito: entregar o melhor açaí e os melhores produtos, com agilidade e carinho em cada entrega. Hoje somos referência em distribuição, atendendo clientes de onde estiverem — sempre com a qualidade que você já conhece.</p>
</section>

<section id="fachada" class="sec">
<h2>Nossa Loja</h2>
<div style="max-width:900px;margin:0 auto;">
<img src="/fachada" alt="Fachada da Loja">
</div>
</section>

<section id="vendedoras" class="sec">
<h2>Nossas Consultoras de Vendas</h2>
<p>Fale diretamente com a sua consultora e faça seu pedido pelo WhatsApp!</p>
<div class="vend-grid">
<div class="vend-card"><div class="avatar"><img src="/foto_vendedora/ANA_RUTH.png" alt="Ana Ruth"></div><h3>Ana Ruth</h3><div class="cargo">Consultora de Vendas</div><div class="tel">(85) 9 9288-5598</div><a class="btn-wa" href="https://wa.me/5585992885598?text=Ol%C3%A1%20Ana%20Ruth!%20Quero%20fazer%20um%20pedido" target="_blank">💬 WhatsApp</a></div>
<div class="vend-card"><div class="avatar"><img src="/foto_vendedora/ISA_LIMA.png" alt="Isa Lima"></div><h3>Isa Lima</h3><div class="cargo">Consultora de Vendas</div><div class="tel">(85) 9 9187-3115</div><a class="btn-wa" href="https://wa.me/5585991873115?text=Ol%C3%A1%20Isa!%20Quero%20fazer%20um%20pedido" target="_blank">💬 WhatsApp</a></div>
<div class="vend-card"><div class="avatar"><img src="/foto_vendedora/SIMONE_MOURA.png" alt="Simone Moura"></div><h3>Simone Moura</h3><div class="cargo">Consultora de Vendas</div><div class="tel">(85) 9 8524-2498</div><a class="btn-wa" href="https://wa.me/5585985242498?text=Ol%C3%A1%20Simone!%20Quero%20fazer%20um%20pedido" target="_blank">💬 WhatsApp</a></div>
</div>
</section>


<section id="local" class="sec">
<h2>Onde Estamos</h2>
<p>Venha nos visitar ou retire seu pedido na loja.</p>
<div class="mapa">
<iframe src="https://maps.google.com/maps?q=Av.%20Leste%20Oeste%2C%203833%20-%20Cristo%20Redentor%2C%20Fortaleza%20-%20CE%2C%2060010-450&t=&z=16&ie=UTF8&iwloc=&output=embed" loading="lazy" referrerpolicy="no-referrer-when-downgrade" allowfullscreen></iframe>
</div>
</section>

<footer>
<div class="footer-grid">
<div class="footer-col">
<h4>Real Açaí Distribuidora</h4>
<p>Há mais de 5 anos levando qualidade, tradição e sabor autêntico para as famílias da nossa região.</p>
</div>
<div class="footer-col">
<h4>Contato</h4>
<p>📍 Av. Leste Oeste, 3833A - Cristo Redentor, Fortaleza - CE, 60010-450</p>
<p>✉️ <a href="mailto:financeiro@distribuidorarealacai.com.br">financeiro@distribuidorarealacai.com.br</a></p>
<p>📞 <a href="tel:+5585985242498">(85) 98524-2498</a></p>
</div>
<div class="footer-col">
<h4>Redes Sociais</h4>
<a href="https://www.instagram.com/realacaidistribuidora" target="_blank" class="footer-social">📸 Instagram</a>
</div>
</div>
<div class="footer-bottom">
<p>"Até aqui nos ajudou o Senhor" — 1 Samuel 7:12</p>
<p class="dev">Desenvolvido por <strong>Gabriel Freitas</strong> — Desenvolvedor Autônomo · V2.5 © 2026 Real Açaí Distribuidora</p>
</div>
</footer>
</body>
</html>'''

def login_page_html(erro=""):
    msg = f'<div style="background:#fee2e2;color:#dc2626;padding:10px 14px;border-radius:8px;font-size:14px;margin-bottom:16px;text-align:center">{erro}</div>' if erro else ''
    return f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Login - Real Acai Dashboard</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:linear-gradient(135deg,#1e3a5f 0%,#2563eb 100%);min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center}}
.card{{background:#fff;border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,.3);padding:40px;width:380px;max-width:90vw}}
.logo{{text-align:center;margin-bottom:28px}}
.logo img{{max-height:100px;max-width:220px;object-fit:contain;margin-bottom:8px}}
.logo h1{{font-size:22px;color:#1e3a5f;font-weight:800}}
.logo p{{font-size:13px;color:#64748b;margin-top:4px}}
.field{{margin-bottom:20px}}
.field label{{display:block;font-size:13px;font-weight:600;color:#475569;margin-bottom:6px;text-transform:uppercase;letter-spacing:.5px}}
.field input{{width:100%;padding:12px 16px;border:2px solid #e2e8f0;border-radius:10px;font-size:15px;outline:none;transition:border .2s}}
.field input:focus{{border-color:#2563eb}}
.btn{{width:100%;background:linear-gradient(135deg,#2563eb,#1e3a5f);color:#fff;border:none;padding:13px;border-radius:10px;font-size:16px;font-weight:700;cursor:pointer;transition:transform .1s}}
.btn:hover{{transform:translateY(-1px);box-shadow:0 4px 12px rgba(37,99,235,.4)}}
.hint{{text-align:center;margin-top:16px;font-size:12px;color:#94a3b8}}
.voltar{{display:block;text-align:center;margin-top:16px;color:#2563eb;text-decoration:none;font-size:13px;font-weight:600}}
.footer{{width:100%;max-width:600px;margin:24px auto 0;text-align:center;color:rgba(255,255,255,.6);font-size:12px;line-height:1.8}}
.btn-admin{{display:inline-block;background:#7c3aed;color:#fff;padding:10px 18px;border-radius:25px;font-weight:700;text-decoration:none;transition:background .2s;}}
.btn-admin:hover{{background:#6d28d9;}}
.btn-motorista{{display:inline-block;background:#25d366;color:#fff;padding:10px 18px;border-radius:25px;font-weight:700;text-decoration:none;transition:background .2s;}}
.btn-motorista:hover{{background:#1ebe5b;}}
.acessos{{display:flex;gap:10px;margin-top:14px;}}
.acesso{{flex:1;text-align:center;padding:12px;border-radius:8px;font-weight:700;text-decoration:none;font-size:14px;border:2px solid #7c3aed;color:#c084fc;background:transparent;transition:background .2s,color .2s;}}
.acesso:hover{{background:#7c3aed;color:#fff;}}
</style>
</head>
<body>
<div class="card">
<div class="logo">
<img src="/logo" alt="Logo Real Acai" onerror="this.style.display='none'" style="max-height:100px;max-width:220px;object-fit:contain">
<h1>Real Acai Distribuidora</h1>
<p>Dashboard Gerencial</p>
</div>
{msg}
<form method="POST" action="/login">
<div class="field"><label>Usuario</label><input type="text" name="user" autofocus required></div>
<div class="field"><label>Senha</label><input type="password" name="senha" required></div>
<button class="btn" type="submit">Entrar</button>
<div class="acessos">
<a href="/admin/login" class="acesso">🔐 Admin</a>
<a href="/motorista/login" class="acesso">🚚 Sou Motorista</a>
</div>
<a href="/">Voltar ao site</a>
</div>
<div class="footer">
<div>Os dados deste sistema sao sincronizados automaticamente atraves do sistema de gestao empresarial <strong>VHSYS</strong></div>
</div>
</body>
</html>'''

def admin_page_html(users):
    linhas = ''
    for uname, u in sorted(users.items()):
        setor_label = SETORES.get(u["setor"], u["setor"])
        role_label = {"admin_master": "Admin Master", "admin": "Admin (Visualizador)", "user": "Colaborador"}.get(u["role"], u["role"])
        is_master = u["role"] == "admin_master"
        btn_excluir = '' if is_master else f'<form method="POST" action="/admin/usuarios/excluir" style="display:inline" onsubmit="return confirm(\'Excluir {u["nome"]}?\')"><input type="hidden" name="username" value="{uname}"><button class="btn-d" type="submit">Excluir</button></form>'
        btn_senha = f'<form method="POST" action="/admin/usuarios/senha" style="display:inline"><input type="hidden" name="username" value="{uname}"><input type="password" name="nova_senha" placeholder="Nova senha" class="inp-sm" required><button class="btn-s" type="submit">Trocar</button></form>'
        badge = '<span class="badge master">MASTER</span>' if is_master else f'<span class="badge">{role_label}</span>'
        linhas += f'''<tr>
<td class="vn">{u["nome"]}{badge}</td>
<td>{uname}</td>
<td>{setor_label}</td>
<td>{role_label}</td>
<td class="actions">{btn_senha} {btn_excluir}</td>
</tr>'''
    opts_setor = ''.join([f'<option value="{k}">{v}</option>' for k, v in SETORES.items()])
    opts_role = '<option value="user">Colaborador (por setor)</option><option value="admin">Admin (ver tudo)</option>'
    return f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Gerenciar Usuarios - Real Acai</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#f0f2f5;color:#1e293b;min-height:100vh}}
.hdr{{background:linear-gradient(135deg,#1e3a5f 0%,#2563eb 100%);color:#fff;padding:16px 32px;display:flex;align-items:center;justify-content:space-between}}
.hdr h1{{font-size:20px;font-weight:700}}
.hdr a{{color:#fff;text-decoration:none;font-size:14px;background:rgba(255,255,255,.15);padding:8px 16px;border-radius:8px}}
.ctn{{max-width:1100px;margin:0 auto;padding:24px}}
.card{{background:#fff;border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,.1);padding:24px;margin-bottom:24px}}
.card h2{{font-size:17px;font-weight:700;margin-bottom:16px;padding-bottom:10px;border-bottom:2px solid #e2e8f0}}
.form-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;align-items:end}}
.fg label{{display:block;font-size:12px;font-weight:600;color:#64748b;text-transform:uppercase;margin-bottom:4px}}
.fg input,.fg select{{width:100%;padding:9px 12px;border:2px solid #e2e8f0;border-radius:8px;font-size:14px;outline:none}}
.btn-add{{background:#16a34a;color:#fff;border:none;padding:10px 20px;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer}}
table{{width:100%;border-collapse:collapse;margin-top:8px}}
th{{text-align:left;padding:12px;font-size:12px;font-weight:700;color:#64748b;text-transform:uppercase;border-bottom:2px solid #e2e8f0}}
td{{padding:12px;font-size:14px;border-bottom:1px solid #f1f5f9}}
td.vn{{font-weight:600}}
.badge{{display:inline-block;background:#dbeafe;color:#2563eb;padding:3px 8px;border-radius:4px;font-size:11px;font-weight:700;margin-left:8px}}
.badge.master{{background:#fef3c7;color:#f59e0b}}
.actions{{display:flex;gap:6px;align-items:center;flex-wrap:wrap}}
.inp-sm{{padding:6px 10px;border:1px solid #e2e8f0;border-radius:6px;font-size:13px;width:120px}}
.btn-s{{background:#2563eb;color:#fff;border:none;padding:6px 12px;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer}}
.btn-d{{background:#dc2626;color:#fff;border:none;padding:6px 12px;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer}}
</style>
</head>
<body>
<div class="hdr">
<h1>Gerenciar Usuarios</h1>
<a href="/dashboard">Voltar ao Dashboard</a>
</div>
<div class="ctn">
<div class="card">
<h2>Adicionar Novo Usuario</h2>
<form method="POST" action="/admin/usuarios/novo">
<div class="form-grid">
<div class="fg"><label>Nome Completo</label><input type="text" name="nome" required></div>
<div class="fg"><label>Usuario (login)</label><input type="text" name="username" required></div>
<div class="fg"><label>Senha</label><input type="password" name="senha" required></div>
<div class="fg"><label>Setor</label><select name="setor">{opts_setor}</select></div>
<div class="fg"><label>Tipo de Conta</label><select name="role">{opts_role}</select></div>
<div class="fg"><button class="btn-add" type="submit">Adicionar</button></div>
</div>
</form>
</div>
<div class="card">
<h2>Usuarios Cadastrados</h2>
<table>
<thead><tr><th>Nome</th><th>Login</th><th>Setor</th><th>Tipo</th><th>Acoes</th></tr></thead>
<tbody>
{linhas}
</tbody>
</table>
</div>
</div>
</body>
</html>'''
def gerar_dashboard_html(pedidos, entregas):
    def safe_json(obj):
        return json.dumps(obj, ensure_ascii=False, default=str).replace('<', '\u003c').replace('>', '\u003e')
    dj = safe_json(pedidos)
    ej = safe_json(entregas)
    with _metas_lock:
        all_metas = carregar_metas()
        mj = safe_json(all_metas)
        mc = 0
        dg = datetime.now().strftime("%d/%m/%Y as %H:%M:%S")
    if pedidos:
        ds = sorted([p["data"] for p in pedidos if p["data"]])
        mind = ds[0] if ds else date.today().isoformat()
        maxd = ds[-1] if ds else date.today().isoformat()
    else:
        mind = date.today().replace(day=1).isoformat()
        maxd = date.today().isoformat()
    html = r'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Real Acai Distribuidora - Dashboard</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<style>
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
</style>
</head>
<body>
<div class="hdr"><div class="hdr-logo"><img src="/logo" alt="Logo" style="height:80px;border-radius:10px;object-fit:contain;background:#fff;padding:6px 10px;" onerror="this.style.display='none';document.getElementById('logoFallback').style.display='flex'"><div id="logoFallback" style="display:none;width:80px;height:80px;border-radius:10px;background:#fff;color:#2563eb;align-items:center;justify-content:center;font-size:32px;font-weight:900;flex-shrink:0;">RA</div><div><h1>Real Acai Distribuidora</h1><div class="sub">Dashboard Gerencial - Vhsys API v2</div></div></div><div style="display:flex;align-items:center;gap:16px"><div class="upd">Dados gerados em: __DG__</div><div style="display:flex;align-items:center;gap:8px;background:rgba(255,255,255,.15);padding:8px 14px;border-radius:8px"><span style="font-size:14px;font-weight:600">__USER_NAME__</span><a href="/admin/usuarios" id="btnUsuarios" style="color:#fff;text-decoration:none;font-size:13px;padding:4px 10px;background:rgba(22,163,74,.8);border-radius:6px;display:none">Usuarios</a><a href="/logout" style="color:#fff;text-decoration:none;font-size:13px;padding:4px 10px;background:rgba(220,38,38,.8);border-radius:6px">Sair</a></div></div></div>
<div class="tabs" id="navTabs">
<button class="tab act" data-sector="comercial" onclick="sw('comercial',this)">Comercial</button>
<button class="tab" data-sector="logistica" onclick="sw('logistica',this)">Logistica</button>
<button class="tab" data-sector="contabil" onclick="sw('contabil',this)">Contabil</button>
</div>
<div class="ctn">
<div class="fb"><div class="fg"><label>De</label><input type="text" class="datepicker" id="dIni" value="__MIN__"></div><div class="fg"><label>Ate</label><input type="text" class="datepicker" id="dFim" value="__MAX__"></div><button class="ba" onclick="af()">Aplicar</button><div style="margin-left:auto;display:flex;gap:8px"><button class="bp" onclick="ph()">Hoje</button><button class="bp" onclick="p7()">7d</button><button class="bp" onclick="pm()">Mes</button><button class="bp" onclick="pt()">Tudo</button></div></div>
<div class="fb" id="fbEmp" style="padding:14px 24px"><div class="ef"><span class="el">Empresa:</span><button class="be act" onclick="se('todos',this)">Consolidado</button><button class="be" onclick="se('REAL MAIS',this)">REAL MAIS</button><button class="be" onclick="se('GP DISTRIBUIDORA',this)">GP</button></div></div>
<div id="tc-com" class="tc act">
<div class="kg" id="kpi"></div>
<div class="st">Metas - <span id="mesL"></span> <button id="btnMeta" class="bp" onclick="tmp()" style="background:var(--al);color:var(--amb);float:right;display:none">Gerenciar Metas</button></div>
<div class="mg" id="metas"></div>
<div class="mp" id="mp"><div class="ct">Editar Metas</div><div id="mef"></div><div style="margin-top:16px;display:flex;gap:8px"><button class="bs" onclick="svm()">Salvar</button><button class="bp" onclick="tmp()">Cancelar</button></div></div>
<div class="cg"><div class="cc"><div class="ct">Faturamento por Vendedora</div><div class="cw"><canvas id="cV"></canvas></div></div><div class="cc"><div class="ct">Faturamento Diario</div><div class="cw"><canvas id="cD"></canvas></div></div><div class="cc f"><div class="ct">Participacao</div><div class="cw"><canvas id="cK"></canvas></div></div></div>
<div class="tc2"><div class="ct">Detalhamento por Vendedora</div><table><thead><tr><th>Vendedora</th><th>Emp</th><th>Faturamento</th><th>Vendas</th><th>Ticket</th><th>Meta</th><th>%Meta</th><th>%Tot</th></tr></thead><tbody id="tb"></tbody></table></div>
</div>
<div id="tc-log" class="tc">
<div class="kg" id="kpiE"></div>
<div class="cg"><div class="cc"><div class="ct">Entregas por Entregador</div><div class="cw"><canvas id="cE"></canvas></div></div><div class="cc"><div class="ct">Entregas por Dia</div><div class="cw"><canvas id="cED"></canvas></div></div></div>
<div class="tc2"><div class="ct">Detalhamento de Entregas</div><table><thead><tr><th>Entregador</th><th>Total</th><th>%</th></tr></thead><tbody id="tbE"></tbody></table></div>
<a href="/logistica_abastecimentos" style="display:inline-block; background:#7c3aed; color:#fff; padding:10px 18px; border-radius:8px; text-decoration:none; font-weight:600; margin:10px 0;">📊 Relatório de Abastecimentos</a>
</div>
<div id="tc-con" class="tc">
<div class="kg" id="kpiC"></div>
<div class="st">CMV - Custo de Mercadorias Vendidas</div>
<div class="fb" style="flex-direction:column;align-items:flex-start;gap:12px">
<div class="cig"><div class="fg"><label>Estoque Inicial</label><input type="text" class="datepicker" id="cmvDi"></div><div class="fg"><label>Estoque Final</label><input type="text" class="datepicker" id="cmvDf"></div></div>
<div class="cig"><div class="fg"><label>Est.Ini RM</label><input type="number" id="cmvEi" step="0.01" placeholder="0" style="width:160px"></div><div class="fg"><label>Est.Ini GP</label><input type="number" id="cmvEig" step="0.01" placeholder="0" style="width:160px"></div><div class="fg"><label>Est.Fin RM</label><input type="number" id="cmvEf" step="0.01" placeholder="0" style="width:160px"></div><div class="fg"><label>Est.Fin GP</label><input type="number" id="cmvEfg" step="0.01" placeholder="0" style="width:160px"></div></div>
<button class="ba" onclick="calcCMV()">Calcular CMV</button>
</div>
<div id="cmvR" style="margin-bottom:24px"></div>
<div class="tc2"><div class="ct">Faturamento por Empresa</div><table><thead><tr><th>Empresa</th><th>Faturamento</th><th>Vendas</th><th>Ticket</th><th>%</th></tr></thead><tbody id="tbEmp"></tbody></table></div>
</div>
<div class="footer">
<div class="footer-name">Gabriel Freitas</div>
<div class="footer-tags">Desenvolvedor Autonomo - Desenvolvimento - Sistemas - Automacao - Inteligencia de Dados</div>
<hr class="footer-divider">
<div class="footer-section">Os dados deste sistema sao sincronizados automaticamente atraves do sistema de gestao empresarial <strong>VHSYS</strong>, utilizado pela Real Acai Distribuidora.</div>
<div class="footer-section">Sistema desenvolvido exclusivamente para: <strong>REAL ACAI DISTRIBUIDORA</strong></div>
<hr class="footer-divider">
<div class="footer-copy">(c) 2026 Real Acai Distribuidora - Todos os direitos reservados<br>Desenvolvido por Gabriel Freitas - Desenvolvedor Autonomo - v1.0.0 - Ultima atualizacao: 15/08/2026</div>
</div>
</div>
<script>
const TP=__DJ__,TE=__EJ__,METAS=__MJ__,C=['#3b82f6','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#14b8a6','#f97316','#6366f1','#84cc16','#06b6d4','#a855f7'];
var ef='todos';
var cV,cD,cK,cE,cED;
var currentMR='';
function gm(mr){return METAS[mr]||{nome_mes:'',consolidada:0,vendedoras:{}}}
var USER_SECTOR='__USER_SECTOR__';
var USER_ROLE='__USER_ROLE__';
var IS_MASTER=__IS_MASTER__;
function filtrarAbas(){var tabs=document.querySelectorAll('#navTabs .tab');tabs.forEach(function(t){var s=t.getAttribute('data-sector');if(USER_ROLE==='admin_master'||USER_ROLE==='admin'||USER_SECTOR==='all'){t.style.display=''}else{t.style.display=(s===USER_SECTOR)?'':'none'}});if(USER_ROLE!=='admin_master'&&USER_ROLE!=='admin'&&USER_SECTOR!=='all'){var p=document.querySelector('#navTabs .tab[style=""], #navTabs .tab:not([style])');if(p)p.click()}}
function renderTudo(){var ini=document.getElementById('dIni').value,fim=document.getElementById('dFim').value;var ped=TP.filter(function(p){return p.data>=ini&&p.data<=fim});if(ef!=='todos')ped=ped.filter(function(p){return p.empresa===ef});var mr=fim.substring(0,7);currentMR=mr;var metasMes=gm(mr);document.getElementById('mesL').textContent=metasMes.nome_mes||fm2(mr);var hoje=new Date();var maStr=hoje.getFullYear()+'-'+String(hoje.getMonth()+1).padStart(2,'0');var fma=TP.filter(function(p){return p.data.substring(0,7)===maStr&&(ef==='todos'||p.empresa===ef)}).reduce(function(s,p){return s+p.valor},0);if(ped.length===0){msd()}else{var pv={};ped.forEach(function(p){var v=nn(p.vendedor);if(!pv[v])pv[v]={n:v,f:0,q:0,e:p.empresa};pv[v].f+=p.valor;pv[v].q+=1});var vs=Object.values(pv).sort(function(a,b){return b.f-a.f});vs.forEach(function(v){v.f=Math.round(v.f*100)/100});var ft=vs.reduce(function(s,v){return s+v.f},0),qv=vs.reduce(function(s,v){return s+v.q},0),tm=qv>0?ft/qv:0,dp=cd(ini,fim);rk(ft,qv,tm,dp,vs.length);rm(vs,mr,fma,maStr);rcV(vs);rcD(ped);rcK(vs,ft);rt(vs,ft);rc(ped,ft,qv)}var ent=TE.filter(function(e){return e.data>=ini&&e.data<=fim});re(ent,ini,fim)}
function sw(t,b){var map={'comercial':'tc-com','logistica':'tc-log','contabil':'tc-con'};document.querySelectorAll('.tc').forEach(function(x){x.classList.remove('act')});document.querySelectorAll('.tab').forEach(function(x){x.classList.remove('act')});document.getElementById(map[t]).classList.add('act');b.classList.add('act');var fbE=document.getElementById('fbEmp');if(fbE){if(t==='logistica'||t==='contabil'){fbE.style.display='none'}else{fbE.style.display='flex'}}setTimeout(function(){try{if(t==='comercial'){if(cV)cV.resize();if(cD)cD.resize();if(cK)cK.resize()}else if(t==='logistica'){if(cE)cE.resize();if(cED)cED.resize()}}catch(e){}},50)}
function nn(n){if(!n)return 'Sem vendedor';return String(n).replace(/[\xa0\t\n\r]/g,' ').replace(/\s+/g,' ').trim().toUpperCase()}
function bm(n){var m=gm(currentMR);var nl=n.toLowerCase();var k=Object.keys(m.vendedoras).find(function(x){return x.toLowerCase()===nl});return k?m.vendedoras[k]:0}
function fm(v){return'R$ '+Number(v).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})}
function fd(i){var p=i.split('-');return p[2]+'/'+p[1]}
function cd(i,f){var d1=new Date(i+'T00:00:00');var d2=new Date(f+'T00:00:00');return Math.round((d2-d1)/86400000)+1}
function fm2(mr){var p=mr.split('-');var n=['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];return n[parseInt(p[1])-1]+' '+p[0]}
function init(){filtrarAbas();if(IS_MASTER){var b=document.getElementById('btnMeta');if(b)b.style.display='';var bu=document.getElementById('btnUsuarios');if(bu)bu.style.display=''}renderTudo()}
function se(e,b){ef=e;document.querySelectorAll('.be').forEach(function(x){x.classList.remove('act')});if(b)b.classList.add('act');af()}
function ph(){var h=new Date().toISOString().split('T')[0];sd(h,h)}
function p7(){var f=new Date();var i=new Date();i.setDate(i.getDate()-6);sd(i.toISOString().split('T')[0],f.toISOString().split('T')[0])}
function pm(){var a=new Date();var i=new Date(a.getFullYear(),a.getMonth(),1);var f=new Date(a.getFullYear(),a.getMonth()+1,0);sd(i.toISOString().split('T')[0],f.toISOString().split('T')[0])}
function pt(){sd('__MIN__','__MAX__')}
function sd(i,f){document.getElementById('dIni').value=i;document.getElementById('dFim').value=f;af()}
function af(){renderTudo()}
function rk(ft,qv,tm,dp,nv){var el='Consolidado';if(ef==='REAL MAIS')el='REAL MAIS';else if(ef==='GP DISTRIBUIDORA')el='GP';document.getElementById('kpi').innerHTML='<div class="kc"><div class="kl">Faturamento '+el+'</div><div class="kv">'+fm(ft)+'</div><div class="ks">'+dp+' dia(s)</div></div><div class="kc grn"><div class="kl">Vendas</div><div class="kv">'+qv+'</div><div class="ks">nao cancelados</div></div><div class="kc amb"><div class="kl">Ticket Medio</div><div class="kv">'+fm(tm)+'</div><div class="ks">por venda</div></div><div class="kc pur"><div class="kl">Vendedoras Ativas</div><div class="kv">'+nv+'</div><div class="ks">no periodo</div></div>'}
function rc(ped,ft,qv){var pe={};TP.forEach(function(p){var ini=document.getElementById('dIni').value,fim=document.getElementById('dFim').value;if(p.data>=ini&&p.data<=fim){if(!pe[p.empresa])pe[p.empresa]={f:0,q:0};pe[p.empresa].f+=p.valor;pe[p.empresa].q+=1}});var ftT=Object.values(pe).reduce(function(s,v){return s+v.f},0),qvT=Object.values(pe).reduce(function(s,v){return s+v.q},0);document.getElementById('kpiC').innerHTML='<div class="kc"><div class="kl">Faturamento Consolidado</div><div class="kv">'+fm(ftT)+'</div><div class="ks">'+qvT+' venda(s)</div></div><div class="kc grn"><div class="kl">Faturamento REAL MAIS</div><div class="kv">'+fm(pe['REAL MAIS']?pe['REAL MAIS'].f:0)+'</div><div class="ks">'+(pe['REAL MAIS']?pe['REAL MAIS'].q:0)+' venda(s)</div></div><div class="kc amb"><div class="kl">Faturamento GP DISTRIBUIDORA</div><div class="kv">'+fm(pe['GP DISTRIBUIDORA']?pe['GP DISTRIBUIDORA'].f:0)+'</div><div class="ks">'+(pe['GP DISTRIBUIDORA']?pe['GP DISTRIBUIDORA'].q:0)+' venda(s)</div></div><div class="kc pur"><div class="kl">Ticket Geral</div><div class="kv">'+fm(qvT>0?ftT/qvT:0)+'</div><div class="ks">consolidado</div></div>';var h='';Object.entries(pe).sort(function(a,b){return b[1].f-a[1].f}).forEach(function(entry,i){var n=entry[0],d=entry[1];var p=ftT>0?(d.f/ftT*100):0;var t=d.q>0?d.f/d.q:0;var c=C[i%C.length];h+='<tr><td class="vn"><span style="display:inline-block;width:12px;height:12px;border-radius:50%;background:'+c+';margin-right:8px"></span>'+n+'</td><td class="vc">'+fm(d.f)+'</td><td>'+d.q+'</td><td>'+fm(t)+'</td><td><span class="pb"><span class="pf" style="width:'+p+'%;background:'+c+'"></span></span>'+p.toFixed(1)+'%</td></tr>'});document.getElementById('tbEmp').innerHTML=h}
function rm(vs,mr,fma,maStr){var h='';var pvMes={};TP.filter(function(p){return p.data.substring(0,7)===maStr&&(ef==='todos'||p.empresa===ef)}).forEach(function(p){var v=nn(p.vendedor);if(!pvMes[v])pvMes[v]={f:0,q:0};pvMes[v].f+=p.valor;pvMes[v].q+=1});if(ef==='todos'){var metasMes=gm(mr);var tm2=metasMes.consolidada,tf=fma,pc=tm2>0?(tf/tm2*100):0,pb=Math.min(pc,100),fl=Math.max(tm2-tf,0);var sc,st,cb;if(pc>=100){sc='sb';st='Meta atingida';cb='#16a34a'}else if(pc>=70){sc='sp';st='Quase la';cb='#f59e0b'}else{sc='sl';st='Em progresso';cb='#dc2626'}var tv=TP.filter(function(p){return p.data.substring(0,7)===maStr}).reduce(function(s,p){return s+1},0);var nm=fm2(maStr);var tf2='';if(tm2>0&&pc<100){tf2='Faltam <strong style="color:#fff">'+fm(fl)+'</strong> para a meta de '+nm}else if(tm2>0&&pc>=100){tf2='Superou a meta de '+nm+' em <strong style="color:#fff">'+fm(tf-tm2)+'</strong>'}h+='<div class="mc con"><div class="mh"><div class="ma" style="background:#fff;color:#2563eb">C</div><div><div class="mn">META CONSOLIDADA - '+nm+'</div><div class="ms">'+tv+' venda(s) em '+nm+' - Ticket: '+fm(tv>0?tf/tv:0)+'</div></div></div><div class="mpb"><div class="mpf" style="width:'+pb+'%;background:'+cb+'">'+pc.toFixed(0)+'%</div></div><div class="mst"><div><span class="mv">'+fm(tf)+'</span><span style="color:rgba(255,255,255,.7);font-size:13px"> / '+fm(tm2)+'</span></div><span class="msb '+sc+'">'+st+'</span></div>'+(tf2?'<div class="mf">'+tf2+'</div>':'')+'</div>'}var nw=new Set(vs.map(function(v){return v.n.toLowerCase()}));var td=vs.slice();Object.keys(metasMes.vendedoras).forEach(function(n){if(!nw.has(n.toLowerCase())){var ee=(n==='GP DISTRIBUIDORA')?'GP DISTRIBUIDORA':'REAL MAIS';if(ef==='todos'||ef===ee)td.push({n:n,f:0,q:0,e:ee})}});td.sort(function(a,b){var ma2=bm(a.n),mb2=bm(b.n);var fa=pvMes[a.n]?pvMes[a.n].f:0;var fb=pvMes[b.n]?pvMes[b.n].f:0;return(mb2>0?fb/mb2:0)-(ma2>0?fa/ma2:0)});td.forEach(function(v,i){var m2=bm(v.n),c=C[i%C.length],ini=v.n.split(' ').map(function(p){return p[0]}).join('').substring(0,2).toUpperCase();var fatMes=pvMes[v.n]?pvMes[v.n].f:0;var qtdMes=pvMes[v.n]?pvMes[v.n].q:0;var pm2=m2>0?(fatMes/m2*100):0,pb2=Math.min(pm2,100);var sc,st,cb;if(m2===0){sc='sn';st='Sem meta';cb='#94a3b8'}else if(pm2>=100){sc='sb';st='Batida';cb='#16a34a'}else if(pm2>=70){sc='sp';st='Quase';cb='#f59e0b'}else{sc='sl';st='Progresso';cb='#dc2626'}var fl=m2>0?Math.max(m2-fatMes,0):0,tm3=qtdMes>0?fatMes/qtdMes:0;var tf3='';if(m2>0&&pm2<100){tf3='Faltam <strong>'+fm(fl)+'</strong>'}else if(m2>0&&pm2>=100){tf3='Superou <strong>'+fm(fatMes-m2)+'</strong>'}var be=v.e==='GP DISTRIBUIDORA'?'<span style="background:#fef3c7;color:#f59e0b;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:700;margin-left:8px">GP</span>':'<span style="background:#dbeafe;color:#2563eb;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:700;margin-left:8px">RM</span>';h+='<div class="mc"><div class="mh"><div class="ma" style="background:'+c+'">'+ini+'</div><div><div class="mn">'+v.n+be+'</div><div class="ms">'+qtdMes+' venda(s) - Ticket: '+fm(tm3)+'</div></div></div><div class="mpb"><div class="mpf" style="width:'+pb2+'%;background:'+cb+'">'+pm2.toFixed(0)+'%</div></div><div class="mst"><div><span class="mv '+(pm2>=100?'at':'')+'">'+fm(fatMes)+'</span><span style="color:var(--mut);font-size:13px"> / '+(m2>0?fm(m2):'-')+'</span></div><span class="msb '+sc+'">'+st+'</span></div>'+(tf3?'<div class="mf">'+tf3+'</div>':'')+'</div>'});document.getElementById('metas').innerHTML=h}
function tmp(){var p=document.getElementById('mp');if(p.classList.contains('act')){p.classList.remove('act');return}p.classList.add('act');var metasMes=gm(currentMR);var h='<div class="fg" style="margin-bottom:12px"><label style="display:block;font-size:12px;font-weight:600;color:#64748b;text-transform:uppercase;margin-bottom:4px">Nome do Mes</label><input type="text" id="mNome" value="'+metasMes.nome_mes+'" placeholder="Ex: Setembro 2026" style="padding:8px;border:2px solid var(--brd);border-radius:8px;width:300px"></div>';h+='<div class="fg" style="margin-bottom:12px"><label style="display:block;font-size:12px;font-weight:600;color:#64748b;text-transform:uppercase;margin-bottom:4px">Meta Consolidada</label><input type="number" id="mCons" value="'+metasMes.consolidada+'" step="0.01" style="padding:8px;border:2px solid var(--brd);border-radius:8px;width:200px"></div>';h+='<div style="font-weight:700;margin:16px 0 8px">Metas por Vendedora</div>';var nomes=new Set();Object.keys(metasMes.vendedoras).forEach(function(n){nomes.add(n)});TP.forEach(function(p){nomes.add(nn(p.vendedor))});nomes.forEach(function(n){var v=metasMes.vendedoras[n]||0;h+='<div class="mer"><div class="mel">'+n+'</div><input type="number" data-nome="'+n+'" value="'+v+'" step="0.01" style="padding:8px;border:2px solid var(--brd);border-radius:8px;width:180px"></div>'});document.getElementById('mef').innerHTML=h}
function svm(){var nome=document.getElementById('mNome').value;var cons=parseFloat(document.getElementById('mCons').value)||0;var vendedoras={};var inputs=document.querySelectorAll('[data-nome]');inputs.forEach(function(inp){var n=inp.getAttribute('data-nome');vendedoras[n]=parseFloat(inp.value)||0});var d={mes:currentMR,nome_mes:nome,consolidada:cons,vendedoras:vendedoras};fetch('/api/metas',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)}).then(function(r){return r.json()}).then(function(x){if(x.status==='ok'){alert('Metas salvas para '+nome+'!');location.reload()}else alert('Erro: '+(x.erro||''))}).catch(function(e){alert('Erro: '+e)})}
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
</script>
</body>
</html>'''
    html = html.replace("__DJ__", dj).replace("__EJ__", ej).replace("__MJ__", mj).replace("__MC__", str(mc)).replace("__DG__", dg).replace("__MIN__", mind).replace("__MAX__", maxd)
    return html



# ===== LOGIN DO ADMIN MASTER =====
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form['senha'] == ADMIN_SENHA:
            session['admin_logado'] = True
            return redirect('/admin/motoristas')
        return '<script>alert("Senha incorreta");window.location="/admin/login";</script>'
    return '''<!DOCTYPE html><html><head><title>Login Admin</title>
    <style>
    body{font-family:Arial;background:#12061f;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;}
    .login{background:#221040;border:1px solid #3b1a6b;border-radius:12px;padding:40px;width:320px;text-align:center;}
    h1{color:#c084fc;}input{width:100%;padding:10px;margin:8px 0;border-radius:6px;border:1px solid #3b1a6b;background:#1a0b2e;color:#fff;}
    button{width:100%;background:#7c3aed;color:#fff;border:none;padding:12px;border-radius:8px;cursor:pointer;font-weight:700;}
    a{color:#c084fc;display:block;margin-top:10px;}
    </style></head><body>
    <div class="login"><h1>🔐 Admin Master</h1>
    <form method="POST">
    <input name="senha" type="password" placeholder="Senha do Admin" required>
    <button>Entrar</button></form>
    <a href="/">← Voltar ao site</a></div></body></html>'''

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logado', None)
    return redirect('/admin/login')


@app.route('/admin/motoristas')
def admin_motoristas():
    if not session.get('admin_logado'):
        return redirect('/admin/login')
    db = get_db()
    veiculos = db.execute('SELECT * FROM veiculos').fetchall()
    motoristas = db.execute('SELECT * FROM motoristas').fetchall()
    db.close()
    return f'''<!DOCTYPE html><html><head><title>Admin - Motoristas</title>
    <style>
    body{{font-family:Arial;background:#12061f;color:#fff;padding:30px;}}
    h1,h2{{color:#c084fc;}}
    .card{{background:#221040;border:1px solid #3b1a6b;border-radius:12px;padding:20px;margin-bottom:20px;}}
    input,select{{width:100%;padding:10px;margin:6px 0;border-radius:6px;border:1px solid #3b1a6b;background:#1a0b2e;color:#fff;}}
    button{{background:#7c3aed;color:#fff;border:none;padding:12px 20px;border-radius:8px;cursor:pointer;font-weight:700;}}
    button:hover{{background:#6d28d9;}}
    table{{width:100%;border-collapse:collapse;margin-top:10px;}}
    th,td{{border:1px solid #3b1a6b;padding:10px;text-align:left;}}
    th{{background:#2a1448;}}
    a{{color:#c084fc;}}
    </style></head><body>
    <h1>⚙️ Admin Master — Motoristas e Veículos</h1>
    <a href="/admin/logout">Sair do admin</a> | <a href="/">← Voltar ao site</a>
    <div class="card"><h2>➕ Cadastrar Veículo</h2>
    <form method="POST" action="/admin/veiculo">
    <input name="placa" placeholder="Placa (ex: ABC1234)" required>
    <input name="descricao" placeholder="Descrição (ex: Fiorino 2019)">
    <button>Salvar Veículo</button></form></div>
    <div class="card"><h2>➕ Cadastrar Motorista</h2>
    <form method="POST" action="/admin/motorista">
    <input name="nome" placeholder="Nome do motorista" required>
    <input name="usuario" placeholder="Usuário de login" required>
    <input name="senha" type="password" placeholder="Senha" required>
    <button>Salvar Motorista</button></form></div>
    <div class="card"><h2>🚚 Veículos Cadastrados</h2>
    <table><tr><th>ID</th><th>Placa</th><th>Descrição</th><th>Ações</th></tr>
    {"".join(f'<tr><td>{v["id"]}</td><td>{v["placa"]}</td><td>{v["descricao"]}</td><td><a href="/admin/veiculo/editar/{v["id"]}" style="color:#38bdf8;">✏️ Editar</a> | <a href="/admin/veiculo/excluir/{v["id"]}" style="color:#f87171;" onclick="return confirm(\'Excluir este veículo?\')">🗑️ Excluir</a></td></tr>' for v in veiculos)}
    </table></div>
    <div class="card"><h2>👤 Motoristas Cadastrados</h2>
    <table><tr><th>ID</th><th>Nome</th><th>Usuário</th><th>Ações</th></tr>
    {"".join(f'<tr><td>{m["id"]}</td><td>{m["nome"]}</td><td>{m["usuario"]}</td><td><a href="/admin/motorista/editar/{m["id"]}" style="color:#38bdf8;">✏️ Editar</a> | <a href="/admin/motorista/excluir/{m["id"]}" style="color:#f87171;" onclick="return confirm(\'Excluir este motorista?\')">🗑️ Excluir</a></td></tr>' for m in motoristas)}
    </table></div>
    </body></html>'''



@app.route('/admin/veiculo', methods=['POST'])
def admin_add_veiculo():
    if not session.get('admin_logado'):
        return redirect('/admin/login')
    placa = request.form['placa'].upper().strip()
    descricao = request.form['descricao'].strip()
    db = get_db()
    try:
        db.execute('INSERT INTO veiculos (placa, descricao) VALUES (?,?)', (placa, descricao))
        db.commit()
    except sqlite3.IntegrityError:
        pass
    db.close()
    return redirect('/admin/motoristas')

@app.route('/admin/motorista', methods=['POST'])
def admin_add_motorista():
    if not session.get('admin_logado'):
        return redirect('/admin/login')
    nome = request.form['nome'].strip()
    usuario = request.form['usuario'].strip()
    senha = request.form['senha']
    db = get_db()
    try:
        db.execute('INSERT INTO motoristas (nome, usuario, senha_hash) VALUES (?,?,?)',
                   (nome, usuario, generate_password_hash(senha)))
        db.commit()
    except sqlite3.IntegrityError:
        pass
    db.close()
    return redirect('/admin/motoristas')


# ===== ROTAS DO MOTORISTA =====
@app.route('/motorista/login', methods=['GET', 'POST'])
def motorista_login():
    if request.method == 'POST':
        usuario = request.form['usuario'].strip()
        senha = request.form['senha']
        db = get_db()
        m = db.execute('SELECT * FROM motoristas WHERE usuario = ?', (usuario,)).fetchone()
        db.close()
        if m and check_password_hash(m['senha_hash'], senha):
            session['motorista_id'] = m['id']
            return redirect('/motorista/painel')
        return '<script>alert("Usuário ou senha inválidos");window.location="/motorista/login";</script>'
    return '''<!DOCTYPE html><html><head><title>Login Motorista</title>
    <style>
    body{font-family:Arial;background:#12061f;color:#fff;display:flex;align-items:center;justify-content:center;height:100vh;}
    .login{background:#221040;border:1px solid #3b1a6b;border-radius:12px;padding:40px;width:320px;text-align:center;}
    h1{color:#c084fc;}input{width:100%;padding:10px;margin:8px 0;border-radius:6px;border:1px solid #3b1a6b;background:#1a0b2e;color:#fff;}
    button{width:100%;background:#7c3aed;color:#fff;border:none;padding:12px;border-radius:8px;cursor:pointer;font-weight:700;}
    a{color:#c084fc;display:block;margin-top:10px;}
    </style></head><body>
    <div class="login"><h1>🚚 Área do Motorista</h1>
    <form method="POST">
    <input name="usuario" placeholder="Usuário" required>
    <input name="senha" type="password" placeholder="Senha" required>
    <button>Entrar</button></form>
    <a href="/">← Voltar ao site</a></div></body></html>'''

@app.route('/motorista/painel', methods=['GET', 'POST'])
def motorista_painel():
    if 'motorista_id' not in session:
        return redirect('/motorista/login')
    db = get_db()
    m = db.execute('SELECT * FROM motoristas WHERE id = ?', (session['motorista_id'],)).fetchone()
    veiculos = db.execute('SELECT * FROM veiculos ORDER BY placa').fetchall()

    # Salvar novo abastecimento
    if request.method == 'POST':
        veiculo_id = request.form['veiculo_id']
        litros = request.form['litros']
        km = request.form['km']
        valor = request.form['valor']
        data = request.form.get('data', '')
        db.execute('INSERT INTO abastecimentos (motorista_id, veiculo_id, data, litros, km, valor) VALUES (?,?,?,?,?,?)',
                   (m['id'], veiculo_id, data, litros, km, valor))
        db.commit()
        return redirect('/motorista/painel')

    abastecimentos = db.execute('''SELECT a.*, v.placa, v.descricao FROM abastecimentos a
        LEFT JOIN veiculos v ON a.veiculo_id = v.id
        WHERE a.motorista_id = ? ORDER BY a.id DESC''', (m['id'],)).fetchall()
    resumo = db.execute('''SELECT COUNT(*) as qtd, COALESCE(SUM(litros),0) as total_litros,
        COALESCE(SUM(km),0) as total_km, COALESCE(SUM(valor),0) as total_valor
        FROM abastecimentos WHERE motorista_id = ?''', (m['id'],)).fetchone()
    db.close()
    return f'''<!DOCTYPE html><html><head><title>Painel do Motorista</title>
    <style>
    body{{font-family:Arial;background:#12061f;color:#fff;padding:30px;}}
    h1{{color:#c084fc;}}h2{{color:#a78bfa;}}
    .cards{{display:flex;gap:20px;flex-wrap:wrap;margin:20px 0;}}
    .kpi{{background:#221040;border:1px solid #3b1a6b;border-radius:12px;padding:20px;flex:1;min-width:150px;text-align:center;}}
    .kpi .num{{font-size:26px;font-weight:800;color:#c084fc;}}
    .form-abastecimento{{background:#221040;border:1px solid #3b1a6b;border-radius:12px;padding:20px;margin:20px 0;}}
    input,select{{width:100%;padding:10px;margin:6px 0;border-radius:6px;border:1px solid #3b1a6b;background:#1a0b2e;color:#fff;}}
    button{{background:#7c3aed;color:#fff;border:none;padding:12px 20px;border-radius:8px;cursor:pointer;font-weight:700;}}
    table{{width:100%;border-collapse:collapse;}}
    th,td{{border:1px solid #3b1a6b;padding:10px;text-align:left;}}
    th{{background:#2a1448;}}
    a{{color:#c084fc;}}
    </style></head><body>
    <h1>🚚 Painel — {m["nome"]}</h1>
    <a href="/motorista/logout">Sair</a>
    <div class="form-abastecimento"><h2>⛽ Registrar Abastecimento</h2>
    <form method="POST">
    <select name="veiculo_id" required><option value="">Selecione o veículo</option>
    {"".join(f'<option value="{v["id"]}">{v["placa"]} - {v["descricao"]}</option>' for v in veiculos)}
    </select>
    <input name="litros" type="number" step="0.01" placeholder="Litros abastecidos" required>
    <input name="km" type="number" placeholder="Km no momento do abastecimento" required>
    <input name="valor" type="number" step="0.01" placeholder="Valor abastecido (R$)" required>
    <input name="data" type="date">
    <button>Salvar Abastecimento</button></form></div>
    <div class="cards">
    <div class="kpi"><div class="num">{resumo["qtd"]}</div>Abastecimentos</div>
    <div class="kpi"><div class="num">R$ {resumo["total_valor"]:.2f}</div>Valor Total</div>
    <div class="kpi"><div class="num">{resumo["total_litros"]:.2f} L</div>Total Litros</div>
    <div class="kpi"><div class="num">{resumo["total_km"]:.0f} km</div>Total Km</div>
    </div>
    <h2>Meus Abastecimentos</h2>
    <table><tr><th>Data</th><th>Veículo</th><th>Litros</th><th>Km</th><th>Valor</th></tr>
    {"".join(f'<tr><td>{a["data"] or "-"}</td><td>{a["placa"]} - {a["descricao"]}</td><td>{a["litros"]}</td><td>{a["km"]}</td><td>R$ {a["valor"]:.2f}</td></tr>' for a in abastecimentos) if abastecimentos else '<tr><td colspan="5">Nenhum abastecimento registrado ainda.</td></tr>'}
    </table>
    </body></html>'''

@app.route('/motorista/logout')
def motorista_logout():
    session.pop('motorista_id', None)
    return redirect('/motorista/login')

@app.route('/admin/veiculo/excluir/<int:id>')
def admin_excluir_veiculo(id):
    if not session.get('admin_logado'):
        return redirect('/admin/login')
    db = get_db()
    db.execute('DELETE FROM veiculos WHERE id = ?', (id,))
    db.commit()
    db.close()
    return redirect('/admin/motoristas')

@app.route('/admin/veiculo/editar/<int:id>', methods=['GET', 'POST'])
def admin_editar_veiculo(id):
    if not session.get('admin_logado'):
        return redirect('/admin/login')
    db = get_db()
    if request.method == 'POST':
        placa = request.form['placa'].upper().strip()
        descricao = request.form['descricao'].strip()
        db.execute('UPDATE veiculos SET placa = ?, descricao = ? WHERE id = ?', (placa, descricao, id))
        db.commit()
        db.close()
        return redirect('/admin/motoristas')
    v = db.execute('SELECT * FROM veiculos WHERE id = ?', (id,)).fetchone()
    db.close()
    return f'''<!DOCTYPE html><html><head><title>Editar Veículo</title>
    <style>
    body{{font-family:Arial;background:#12061f;color:#fff;padding:30px;}}
    h1{{color:#c084fc;}}
    .card{{background:#221040;border:1px solid #3b1a6b;border-radius:12px;padding:20px;max-width:400px;}}
    input{{width:100%;padding:10px;margin:6px 0;border-radius:6px;border:1px solid #3b1a6b;background:#1a0b2e;color:#fff;}}
    button{{background:#7c3aed;color:#fff;border:none;padding:12px 20px;border-radius:8px;cursor:pointer;font-weight:700;}}
    a{{color:#c084fc;}}
    </style></head><body>
    <h1>✏️ Editar Veículo</h1>
    <div class="card">
    <form method="POST">
    <input name="placa" value="{v["placa"]}" required>
    <input name="descricao" value="{v["descricao"]}">
    <button>Salvar Alterações</button></form>
    <a href="/admin/motoristas">← Voltar</a></div>
    </body></html>'''

@app.route('/admin/motorista/excluir/<int:id>')
def admin_excluir_motorista(id):
    if not session.get('admin_logado'):
        return redirect('/admin/login')
    db = get_db()
    db.execute('DELETE FROM motoristas WHERE id = ?', (id,))
    db.commit()
    db.close()
    return redirect('/admin/motoristas')

@app.route('/admin/motorista/editar/<int:id>', methods=['GET', 'POST'])
def admin_editar_motorista(id):
    if not session.get('admin_logado'):
        return redirect('/admin/login')
    db = get_db()
    if request.method == 'POST':
        nome = request.form['nome'].strip()
        usuario = request.form['usuario'].strip()
        senha = request.form['senha']
        if senha:
            db.execute('UPDATE motoristas SET nome = ?, usuario = ?, senha_hash = ? WHERE id = ?',
                       (nome, usuario, generate_password_hash(senha), id))
        else:
            db.execute('UPDATE motoristas SET nome = ?, usuario = ? WHERE id = ?', (nome, usuario, id))
        db.commit()
        db.close()
        return redirect('/admin/motoristas')
    m = db.execute('SELECT * FROM motoristas WHERE id = ?', (id,)).fetchone()
    db.close()
    return f'''<!DOCTYPE html><html><head><title>Editar Motorista</title>
    <style>
    body{{font-family:Arial;background:#12061f;color:#fff;padding:30px;}}
    h1{{color:#c084fc;}}
    .card{{background:#221040;border:1px solid #3b1a6b;border-radius:12px;padding:20px;max-width:400px;}}
    input{{width:100%;padding:10px;margin:6px 0;border-radius:6px;border:1px solid #3b1a6b;background:#1a0b2e;color:#fff;}}
    button{{background:#7c3aed;color:#fff;border:none;padding:12px 20px;border-radius:8px;cursor:pointer;font-weight:700;}}
    a{{color:#c084fc;}}
    </style></head><body>
    <h1>✏️ Editar Motorista</h1>
    <div class="card">
    <form method="POST">
    <input name="nome" value="{m["nome"]}" required>
    <input name="usuario" value="{m["usuario"]}" required>
    <input name="senha" type="password" placeholder="Nova senha (deixe em branco para manter)">
    <button>Salvar Alterações</button></form>
    <a href="/admin/motoristas">← Voltar</a></div>
    </body></html>'''


@app.route('/')
def index():
    return Response(PAGINA_INICIAL, mimetype='text/html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = request.form.get('user', '').strip()
        senha = request.form.get('senha', '')
        users = carregar_usuarios()
        u = users.get(user)
        if u and u["senha_hash"] == hash_senha(senha):
            session['user'] = user
            return redirect('/dashboard')
        return Response(login_page_html("Usuario ou senha invalidos."), mimetype='text/html')
    return Response(login_page_html(), mimetype='text/html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/dashboard')
@requer_login
def dashboard():
    u = usuario_logado()
    with _cache_lock:
        if _cache["html"] and (time.time() - _cache["timestamp"]) < CACHE_TEMPO_SEGUNDOS:
            html = _cache["html"]
            html = html.replace("__USER_NAME__", u["nome"])
            html = html.replace("__USER_SECTOR__", u["setor"])
            html = html.replace("__USER_ROLE__", u["role"])
            html = html.replace("__IS_MASTER__", "1" if u["role"] == "admin_master" else "0")
            return Response(html, mimetype='text/html')
    print("[DEBUG] Cache vazio, buscando dados...", flush=True)
    try:
        todos = buscar_dados_mes_atual()
        ent = ler_dados_entregas()
        html = gerar_dashboard_html(todos, ent)
        html = html.replace("__USER_NAME__", u["nome"])
        html = html.replace("__USER_SECTOR__", u["setor"])
        html = html.replace("__USER_ROLE__", u["role"])
        html = html.replace("__IS_MASTER__", "1" if u["role"] == "admin_master" else "0")
        with _cache_lock:
            _cache["timestamp"] = time.time()
            _cache["html"] = html
        return Response(html, mimetype='text/html')
    except Exception as e:
        return f"<h1 style='color:red;text-align:center;margin-top:100px;font-family:sans-serif'>Erro: {e}</h1>"

@app.route('/atualizar')
def forcar_atualizacao():
    with _cache_lock:
        _cache["timestamp"] = 0
        _cache["html"] = ""
    return "<script>window.location.href='/dashboard';</script>"


@app.route('/insta_img')
@app.route('/INSTA_IMG')
def insta_img():
    import re as _re
    # Procura em qualquer subpasta, ignorando maiúsculas/minúsculas
    for raiz, _, arquivos in os.walk(os.path.dirname(os.path.abspath(__file__))):
        for arq in arquivos:
            if _re.match(r'^insta_img\.(png|jpe?g|webp|gif)$', arq, _re.IGNORECASE):
                return send_file(os.path.join(raiz, arq))
    # Fallback: busca recursiva com glob case-insensitive
    matches = [p for p in glob.glob('**/*', recursive=True) if _re.match(r'^insta_img\.(png|jpe?g|webp|gif)$', os.path.basename(p), _re.IGNORECASE)]
    if matches:
        return send_file(matches[0])
    return Response('', status=404)

@app.route('/foto_vendedora/<nome>')
def foto_vendedora(nome):
    import re as _re
    nome_limpo = _re.sub(r'[^A-Za-z0-9_.-]', '', nome)
    caminhos = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), nome_limpo),
        os.path.join(os.getcwd(), nome_limpo),
        nome_limpo,
        '/app/' + nome_limpo,
    ]
    for c in caminhos:
        if os.path.isfile(c):
            return send_file(c)
    matches = glob.glob('**/' + nome_limpo, recursive=True)
    if matches:
        return send_file(matches[0])
    return Response('', status=404)



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
    pixel = b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\xfe\x02\xfe\xdc\xcc\x59\xe7\x00\x00\x00\x00IEND\xaeB`\x82'
    return Response(pixel, mimetype='image/png')

@app.route('/admin/usuarios')
@requer_admin_master
def admin_usuarios():
    users = carregar_usuarios()
    return Response(admin_page_html(users), mimetype='text/html')

@app.route('/admin/usuarios/novo', methods=['POST'])
@requer_admin_master
def admin_novo_usuario():
    nome = request.form.get('nome', '').strip()
    username = request.form.get('username', '').strip().lower()
    senha = request.form.get('senha', '')
    setor = request.form.get('setor', 'comercial')
    role = request.form.get('role', 'user')
    if not nome or not username or not senha:
        return redirect('/admin/usuarios?erro=campos')
    if username == 'admin':
        return redirect('/admin/usuarios?erro=admin')
    users = carregar_usuarios()
    if username in users:
        return redirect('/admin/usuarios?erro=existe')
    users[username] = {
        "nome": nome,
        "senha_hash": hash_senha(senha),
        "role": role,
        "setor": setor
    }
    salvar_usuarios(users)
    return redirect('/admin/usuarios?ok=1')

@app.route('/admin/usuarios/excluir', methods=['POST'])
@requer_admin_master
def admin_excluir_usuario():
    username = request.form.get('username', '')
    if username == 'admin':
        return redirect('/admin/usuarios?erro=admin')
    users = carregar_usuarios()
    if username in users:
        del users[username]
        salvar_usuarios(users)
    return redirect('/admin/usuarios?ok=excluido')

@app.route('/admin/usuarios/senha', methods=['POST'])
@requer_admin_master
def admin_trocar_senha():
    username = request.form.get('username', '')
    nova = request.form.get('nova_senha', '')
    if not nova:
        return redirect('/admin/usuarios?erro=senha')
    users = carregar_usuarios()
    if username in users:
        users[username]["senha_hash"] = hash_senha(nova)
        salvar_usuarios(users)
    return redirect('/admin/usuarios?ok=senha')



# ===== RELATÓRIO DE ABASTECIMENTOS CONSOLIDADO (ABA LOGÍSTICA) =====
@app.route('/logistica_abastecimentos')
def logistica_abastecimentos():
    if 'user' not in session:
        return redirect('/login')

    inicio = request.args.get('inicio', '')
    fim = request.args.get('fim', '')

    conn = sqlite3.connect('motoristas.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    filtro = ""
    params = []
    if inicio and fim:
        filtro = "AND a.data BETWEEN ? AND ?"
        params = [inicio, fim]

    # Totais gerais
    cur.execute(f"""
        SELECT COUNT(*) AS qtd,
               COALESCE(SUM(a.litros), 0) AS total_litros,
               COALESCE(SUM(a.valor), 0) AS total_valor,
               COALESCE(SUM(a.km), 0) AS total_km
        FROM abastecimentos a
        WHERE 1=1 {filtro}
    """, params)
    totais = cur.fetchone()

    # Consolidação POR VEÍCULO
    cur.execute(f"""
        SELECT v.placa, v.descricao,
               COUNT(a.id) AS qtd,
               COALESCE(SUM(a.litros), 0) AS litros,
               COALESCE(SUM(a.valor), 0) AS valor
        FROM abastecimentos a
        JOIN veiculos v ON v.id = a.veiculo_id
        WHERE 1=1 {filtro}
        GROUP BY v.id
        ORDER BY valor DESC
    """, params)
    por_veiculo = cur.fetchall()

    # Consolidação POR MOTORISTA
    cur.execute(f"""
        SELECT m.nome,
               COUNT(a.id) AS qtd,
               COALESCE(SUM(a.litros), 0) AS litros,
               COALESCE(SUM(a.valor), 0) AS valor
        FROM abastecimentos a
        JOIN motoristas m ON m.id = a.motorista_id
        WHERE 1=1 {filtro}
        GROUP BY m.id
        ORDER BY valor DESC
    """, params)
    por_motorista = cur.fetchall()

    conn.close()

    return render_template_string('''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Logística — Abastecimentos Consolidado</title>
    <style>
        * { margin:0; padding:0; box-sizing:border-box; font-family:'Segoe UI', Arial, sans-serif; }
        body { background:#12061f; color:#e9d5ff; padding:24px; min-height:100vh; }
        h1 { color:#c084fc; margin-bottom:20px; font-size:24px; }
        h2 { color:#a78bfa; margin:28px 0 12px; font-size:18px; }
        .filtro { display:flex; gap:12px; align-items:flex-end; flex-wrap:wrap; margin-bottom:20px;
                  background:#221040; padding:16px; border-radius:12px; border:1px solid #3b1a6b; }
        .filtro label { font-size:13px; color:#c4b5fd; display:block; margin-bottom:4px; }
        .filtro input { background:#1a0b2e; border:1px solid #3b1a6b; color:#e9d5ff;
                        padding:8px 10px; border-radius:8px; }
        .filtro button { background:#7c3aed; color:#fff; border:none; padding:9px 18px;
                         border-radius:8px; cursor:pointer; font-weight:600; }
        .filtro button:hover { background:#6d28d9; }
        .filtro a { color:#38bdf8; text-decoration:none; font-size:13px; align-self:center; }
        .kpis { display:grid; grid-template-columns:repeat(auto-fit, minmax(180px,1fr)); gap:14px; margin-bottom:10px; }
        .kpi { background:#221040; border:1px solid #3b1a6b; border-radius:12px; padding:18px; text-align:center; }
        .kpi .num { font-size:26px; font-weight:700; color:#c084fc; }
        .kpi .lbl { font-size:13px; color:#a78bfa; margin-top:4px; }
        table { width:100%; border-collapse:collapse; background:#221040; border-radius:12px;
                overflow:hidden; border:1px solid #3b1a6b; }
        th { background:#2a1450; color:#c084fc; padding:11px 12px; text-align:left; font-size:13px; }
        td { padding:10px 12px; border-top:1px solid #3b1a6b; font-size:14px; }
        tr:hover td { background:#2a1450; }
        .valor { color:#34d399; font-weight:600; }
        .vazio { text-align:center; color:#a78bfa; padding:24px; }
        .voltar { display:inline-block; margin-top:24px; color:#38bdf8; text-decoration:none; font-size:14px; }
    </style>
</head>
<body>
    <h1>⛽ Logística — Abastecimentos Consolidado</h1>

    <form class="filtro" method="get" action="/logistica_abastecimentos">
        <div><label>Data início</label><input type="text" class="datepicker" name="inicio" value="{{ inicio }}"></div>
        <div><label>Data fim</label><input type="text" class="datepicker" name="fim" value="{{ fim }}"></div>
        <button type="submit">Filtrar</button>
        <a href="/logistica_abastecimentos">Limpar</a>
    </form>

    <div class="kpis">
        <div class="kpi"><div class="num">{{ totais['qtd'] }}</div><div class="lbl">Abastecimentos</div></div>
        <div class="kpi"><div class="num">R$ {{ "%.2f"|format(totais['total_valor']) }}</div><div class="lbl">Valor Total</div></div>
        <div class="kpi"><div class="num">{{ "%.2f"|format(totais['total_litros']) }} L</div><div class="lbl">Total Litros</div></div>
        <div class="kpi"><div class="num">{{ "%.0f"|format(totais['total_km']) }} km</div><div class="lbl">Total Km</div></div>
    </div>

    <h2>🚗 Por Veículo</h2>
    <table>
        <thead><tr><th>Veículo</th><th>Qtd</th><th>Litros</th><th>Valor Total</th></tr></thead>
        <tbody>
        {% for v in por_veiculo %}
            <tr>
                <td>{{ v['placa'] }} — {{ v['descricao'] }}</td>
                <td>{{ v['qtd'] }}</td>
                <td>{{ "%.2f"|format(v['litros']) }} L</td>
                <td class="valor">R$ {{ "%.2f"|format(v['valor']) }}</td>
            </tr>
        {% else %}
            <tr><td colspan="4" class="vazio">Nenhum abastecimento no período.</td></tr>
        {% endfor %}
        </tbody>
    </table>

    <h2>👤 Por Motorista</h2>
    <table>
        <thead><tr><th>Motorista</th><th>Qtd</th><th>Litros</th><th>Valor Total</th></tr></thead>
        <tbody>
        {% for m in por_motorista %}
            <tr>
                <td>{{ m['nome'] }}</td>
                <td>{{ m['qtd'] }}</td>
                <td>{{ "%.2f"|format(m['litros']) }} L</td>
                <td class="valor">R$ {{ "%.2f"|format(m['valor']) }}</td>
            </tr>
        {% else %}
            <tr><td colspan="4" class="vazio">Nenhum abastecimento no período.</td></tr>
        {% endfor %}
        </tbody>
    </table>

    <a class="voltar" href="/dashboard">← Voltar ao Dashboard</a>
</body>
</html>
''', inicio=inicio, fim=fim, totais=totais,
     por_veiculo=por_veiculo, por_motorista=por_motorista)

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
    if request.method == 'GET':
        return jsonify(carregar_metas())
    u = usuario_logado()
    if not u or u["role"] != 'admin_master':
        return jsonify({"status": "erro", "erro": "Apenas admin master"}), 403
    dados = request.get_json()
    if not dados:
        return jsonify({"status": "erro", "erro": "Dados nao enviados"}), 400
    mes = dados.get('mes', '')
    if not mes:
        return jsonify({"status": "erro", "erro": "Mes nao informado"}), 400
    with _metas_lock:
        metas = carregar_metas()
        vendedoras = {}
        for k, v in dados.get("vendedoras", {}).items():
            vendedoras[k] = float(v)
        metas[mes] = {
            "nome_mes": dados.get("nome_mes", ""),
            "consolidada": float(dados.get("consolidada", 0)),
            "vendedoras": vendedoras
        }
        salvar_metas(metas)
    with _cache_lock:
        _cache["timestamp"] = 0
        _cache["html"] = ""
    return jsonify({"status": "ok"})

@app.route('/debug_rm')
def debug_rm():
    BASE_URL = "https://api.vhsys.com/v2"
    headers = {
        "access-token": "GYMMUfafZLDUMCDQUAIaAKUblKdTEc",
        "secret-access-token": "I5efsjIytX6XpWDx0VNSfujQ24TjW2",
        "Content-Type": "application/json",
        "User-Agent": "Debug/1.0"
    }
    saida = []
    saida.append("<h2>DEBUG - Token Novo REAL MAIS</h2>")

    # Teste 1: endpoint /pedidos/ com order (igual ao código atual)
    try:
        r = requests.get(f"{BASE_URL}/pedidos/", headers=headers,
                         params={"limit": 10, "offset": 0, "order": "data_pedido", "sort": "Desc"},
                         timeout=30)
        saida.append(f"<h3>Teste 1: /pedidos/ (com order)</h3><p><b>STATUS:</b> {r.status_code}</p>")
        saida.append(f"<pre>{r.text[:3000]}</pre>")
    except Exception as e:
        saida.append(f"<h3>Teste 1 ERRO</h3><pre>{e}</pre>")

    # Teste 2: endpoint /pedidos/ SEM order (padrão da API)
    try:
        r2 = requests.get(f"{BASE_URL}/pedidos/", headers=headers,
                          params={"limit": 10, "offset": 0},
                          timeout=30)
        saida.append(f"<h3>Teste 2: /pedidos/ (sem order)</h3><p><b>STATUS:</b> {r2.status_code}</p>")
        saida.append(f"<pre>{r2.text[:3000]}</pre>")
    except Exception as e:
        saida.append(f"<h3>Teste 2 ERRO</h3><pre>{e}</pre>")

    # Teste 3: endpoint /vendas-balcao/ (como a GP usa)
    try:
        r3 = requests.get(f"{BASE_URL}/vendas-balcao/", headers=headers,
                          params={"limit": 10, "offset": 0},
                          timeout=30)
        saida.append(f"<h3>Teste 3: /vendas-balcao/</h3><p><b>STATUS:</b> {r3.status_code}</p>")
        saida.append(f"<pre>{r3.text[:3000]}</pre>")
    except Exception as e:
        saida.append(f"<h3>Teste 3 ERRO</h3><pre>{e}</pre>")

    return Response("<html><body style='font-family:monospace;padding:20px'>" + "".join(saida) + "</body></html>", mimetype='text/html')

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
