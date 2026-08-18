#!/usr/bin/env python3
"""
dash_flask_ofc.py  (v10 - simples e direto)
"""
import os, sys, json, csv, io, re, time, threading, glob, base64
from datetime import datetime, date
from calendar import monthrange
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from flask import Flask, request, jsonify, send_file, send_from_directory, Response, session, redirect, render_template_string, url_for
from datetime import datetime, date, timedelta

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'real_acai_2026_secret_key')

import hashlib, secrets
from flask import session, redirect, url_for


import psycopg
from psycopg.rows import dict_row

def get_db_connection():
    db_url = os.environ.get('DATABASE_URL', '')
    if not db_url:
        print("[DEBUG] DATABASE_URL nao configurada", flush=True)
        return None
    try:
        conn = psycopg.connect(db_url, autocommit=True)
        return conn
    except Exception as e:
        print(f"[DEBUG] Erro ao conectar DB: {e}", flush=True)
        return None

def init_db():
    conn = get_db_connection()
    if not conn:
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    id SERIAL PRIMARY KEY,
                    nome TEXT NOT NULL,
                    login TEXT UNIQUE NOT NULL,
                    senha TEXT NOT NULL,
                    setor TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'colaborador'
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS metas (
                    id SERIAL PRIMARY KEY,
                    mes_ano TEXT NOT NULL,
                    nome_mes TEXT,
                    vendedoras JSONB DEFAULT '{}',
                    consolidada NUMERIC DEFAULT 0,
                    UNIQUE(mes_ano)
                );
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS metas_produtos (
                    id SERIAL PRIMARY KEY,
                    mes_ano TEXT NOT NULL,
                    nome_mes TEXT,
                    produtos JSONB DEFAULT '[]',
                    venda_meta NUMERIC DEFAULT 0,
                    UNIQUE(mes_ano)
                );
            """)
            # Criar usuario master fixo (gabriel_adm)
            cur.execute("SELECT * FROM usuarios WHERE login = 'gabriel_adm'")
            if not cur.fetchone():
                cur.execute(
                    "INSERT INTO usuarios (nome, login, senha, setor, role) VALUES (%s, %s, %s, %s, %s)",
                    ('Gabriel Admin', 'gabriel_adm', '132429', 'todas as abas', 'admin_master')
                )
                print("[DEBUG] Usuario gabriel_adm criado", flush=True)
            # Criar admin padrao tambem (mantem compatibilidade)
            cur.execute("SELECT * FROM usuarios WHERE login = 'admin'")
            if not cur.fetchone():
                cur.execute(
                    "INSERT INTO usuarios (nome, login, senha, setor, role) VALUES (%s, %s, %s, %s, %s)",
                    ('Administrador Master', 'admin', 'admin123', 'todas as abas', 'admin_master')
                )
                print("[DEBUG] Admin master padrao criado", flush=True)
        print("[DEBUG] Tabelas criadas/verificadas", flush=True)
    except Exception as e:
        print(f"[DEBUG] Erro ao criar tabelas: {e}", flush=True)
    finally:
        conn.close()


def migrar_dados_json_para_banco():
    """Migra metas e metas_produtos dos arquivos JSON para o PostgreSQL"""
    conn = get_db_connection()
    if not conn:
        return
    try:
        # Migra metas
        if os.path.exists(METAS_FILE):
            try:
                with open(METAS_FILE, 'r', encoding='utf-8') as f:
                    metas = json.load(f)
                if metas and isinstance(metas, dict):
                    with conn.cursor() as cur:
                        for mes_ano, dados in metas.items():
                            nome_mes = dados.get("nome_mes", "")
                            vendedoras = dados.get("vendedoras", {})
                            consolidada = float(dados.get("consolidada", 0) or 0)
                            cur.execute("""
                                INSERT INTO metas (mes_ano, nome_mes, vendedoras, consolidada)
                                VALUES (%s, %s, %s, %s)
                                ON CONFLICT (mes_ano) DO NOTHING
                            """, (mes_ano, nome_mes, json.dumps(vendedoras), consolidada))
                    print(f"[DEBUG] Migradas {len(metas)} metas do JSON", flush=True)
            except Exception as e:
                print(f"[DEBUG] Erro ao migrar metas: {e}", flush=True)
        
        # Migra metas_produtos
        if os.path.exists(METAS_PRODUTOS_FILE):
            try:
                with open(METAS_PRODUTOS_FILE, 'r', encoding='utf-8') as f:
                    metas_prod = json.load(f)
                if metas_prod and isinstance(metas_prod, dict):
                    with conn.cursor() as cur:
                        for mes_ano, dados in metas_prod.items():
                            nome_mes = dados.get("nome_mes", "")
                            produtos = dados.get("produtos", [])
                            venda_meta = float(dados.get("venda_meta", 0) or 0)
                            cur.execute("""
                                INSERT INTO metas_produtos (mes_ano, nome_mes, produtos, venda_meta)
                                VALUES (%s, %s, %s, %s)
                                ON CONFLICT (mes_ano) DO NOTHING
                            """, (mes_ano, nome_mes, json.dumps(produtos), venda_meta))
                    print(f"[DEBUG] Migradas {len(metas_prod)} metas_produtos do JSON", flush=True)
            except Exception as e:
                print(f"[DEBUG] Erro ao migrar metas_produtos: {e}", flush=True)
    except Exception as e:
        print(f"[DEBUG] Erro na migracao: {e}", flush=True)
    finally:
        conn.close()

def hash_senha(senha):
    return hashlib.sha256(senha.encode('utf-8')).hexdigest()

def carregar_usuarios():
    MASTER = {"nome":"Gabriel Admin","login":"gabriel_adm","senha":"132429","setor":"todas as abas","role":"admin_master"}
    conn = get_db_connection()
    if not conn:
        if os.path.exists(USUARIOS_FILE):
            try:
                with open(USUARIOS_FILE, 'r', encoding='utf-8') as f:
                    users = json.load(f)
                    # Garante que o master sempre existe
                    if not any(u.get("login") == "gabriel_adm" for u in users):
                        users.insert(0, MASTER)
                    return users
            except:
                pass
        return [MASTER]
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT nome, login, senha, setor, role FROM usuarios ORDER BY id")
            rows = cur.fetchall()
            usuarios = [dict(r) for r in rows]
            # Garante que o master sempre existe na lista
            if not any(u.get("login") == "gabriel_adm" for u in usuarios):
                usuarios.insert(0, MASTER)
            if not usuarios:
                usuarios = [MASTER]
            return usuarios
    except Exception as e:
        print(f"[DEBUG] Erro ao carregar usuarios: {e}", flush=True)
        return [MASTER]
    finally:
        conn.close()


def carregar_metas():
    conn = get_db_connection()
    if not conn:
        if os.path.exists(METAS_FILE):
            try:
                with open(METAS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT mes_ano, nome_mes, vendedoras, consolidada FROM metas ORDER BY mes_ano")
            rows = cur.fetchall()
            metas = {}
            for r in rows:
                metas[r["mes_ano"]] = {
                    "nome_mes": r.get("nome_mes", ""),
                    "vendedoras": r.get("vendedoras", {}) if isinstance(r.get("vendedoras"), dict) else {},
                    "consolidada": float(r.get("consolidada", 0) or 0)
                }
            return metas
    except Exception as e:
        print(f"[DEBUG] Erro ao carregar metas: {e}", flush=True)
        return {}
    finally:
        conn.close()

def carregar_metas_produtos():
    conn = get_db_connection()
    if not conn:
        if os.path.exists(METAS_PRODUTOS_FILE):
            try:
                with open(METAS_PRODUTOS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        return {}
    try:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT mes_ano, nome_mes, produtos, venda_meta FROM metas_produtos ORDER BY mes_ano")
            rows = cur.fetchall()
            metas = {}
            for r in rows:
                metas[r["mes_ano"]] = {
                    "nome_mes": r.get("nome_mes", ""),
                    "produtos": r.get("produtos", []) if isinstance(r.get("produtos"), list) else [],
                    "venda_meta": float(r.get("venda_meta", 0) or 0)
                }
            return metas
    except Exception as e:
        print(f"[DEBUG] Erro ao carregar metas_produtos: {e}", flush=True)
        return {}
    finally:
        conn.close()

def salvar_usuarios(usuarios):
    conn = get_db_connection()
    if not conn:
        with open(USUARIOS_FILE, 'w', encoding='utf-8') as f:
            json.dump(usuarios, f, ensure_ascii=False, indent=2)
        return
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM usuarios WHERE login NOT IN ('gabriel_adm', 'admin')")
            for u in usuarios:
                if u.get("login") in ("gabriel_adm", "admin"):
                    continue
                cur.execute(
                    "INSERT INTO usuarios (nome, login, senha, setor, role) VALUES (%s, %s, %s, %s, %s) ON CONFLICT (login) DO UPDATE SET nome=%s, senha=%s, setor=%s, role=%s",
                    (u["nome"], u["login"], u["senha"], u["setor"], u["role"], u["nome"], u["senha"], u["setor"], u["role"])
                )
    except Exception as e:
        print(f"[DEBUG] Erro ao salvar usuarios: {e}", flush=True)
    finally:
        conn.close()



def requer_login(f):
    def wrap(*args, **kwargs):
        u = nome_user
        if not u:
            return redirect('/login')
        return f(*args, **kwargs)
    wrap.__name__ = f.__name__
    return wrap

def requer_admin_master(f):
    def wrap(*args, **kwargs):
        u = nome_user
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
    {"nome": "REAL MAIS", "access_token": "GYMMUfafZLDUMCDQUAIaAKUbIKdTEc", "secret_token": "l5efsjlIytX6XpWDx0VNSfujQ24TjW2", "endpoint": "/pedidos/", "data_field": "data_pedido", "order_field": "data_pedido"},
    {"nome": "GP DISTRIBUIDORA", "access_token": "EdPfRWCOGgefDeVcSNNaGJLJeZDMST", "secret_token": "5P4nmO1ONthN5oqfX81lHKX5i0YC3dm", "endpoint": "/vendas-balcao/", "data_field": "data_cad_pedido", "order_field": "data_cad_pedido"},
]
BASE_URL = "https://api.vhsys.com/v2"
STATUS_INCLUIDOS = {"Atendido", "Em Andamento", "Em Aberto"}
SPREADSHEET_ID = "10rPC_-MxKm6o0L1SjHanXuKm0LjEIezjhoclNPlzpfc"

METAS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'metas.json')
_metas_lock = threading.Lock()

def carregar_metas_produtos():
    conn = get_db_connection()
    if not conn:
        if os.path.exists(METAS_PRODUTOS_FILE):
            try:
                with open(METAS_PRODUTOS_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                pass
        default = {"2026-08": {"nome_mes": "Agosto 2026", "produtos": [], "venda_meta": 241500.00}}
        salvar_metas_produtos(default)
        return default
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT mes_ano, nome_mes, produtos, venda_meta FROM metas_produtos")
            rows = cur.fetchall()
            metas = {}
            for r in rows:
                metas[r["mes_ano"]] = {
                    "nome_mes": r["nome_mes"] or "",
                    "produtos": r["produtos"] or [],
                    "venda_meta": float(r["venda_meta"] or 0)
                }
            return metas
    except Exception as e:
        print(f"[DEBUG] Erro ao carregar metas_produtos: {e}", flush=True)
        return {}
    finally:
        conn.close()


def salvar_metas(metas):
    conn = get_db_connection()
    if not conn:
        with open(METAS_FILE, 'w', encoding='utf-8') as f:
            json.dump(metas, f, ensure_ascii=False, indent=2)
        return
    try:
        with conn.cursor() as cur:
            for mes_ano, dados in metas.items():
                nome_mes = dados.get("nome_mes", "")
                vendedoras = dados.get("vendedoras", {})
                consolidada = float(dados.get("consolidada", 0) or 0)
                cur.execute(
                    """INSERT INTO metas (mes_ano, nome_mes, vendedoras, consolidada)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (mes_ano) DO UPDATE SET nome_mes=%s, vendedoras=%s, consolidada=%s""",
                    (mes_ano, nome_mes, json.dumps(vendedoras), consolidada,
                     nome_mes, json.dumps(vendedoras), consolidada)
                )
        print(f"[DEBUG] {len(metas)} metas salvas no banco", flush=True)
    except Exception as e:
        print(f"[DEBUG] Erro ao salvar metas: {e}", flush=True)
    finally:
        conn.close()        

def salvar_metas_produtos(metas):
    conn = get_db_connection()
    if not conn:
        with open(METAS_PRODUTOS_FILE, 'w', encoding='utf-8') as f:
            json.dump(metas, f, ensure_ascii=False, indent=2)
        return
    try:
        with conn.cursor() as cur:
            for mes, dados in metas.items():
                cur.execute(
                    """INSERT INTO metas_produtos (mes_ano, nome_mes, produtos, venda_meta)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (mes_ano) DO UPDATE SET nome_mes=%s, produtos=%s, venda_meta=%s""",
                    (mes, dados.get("nome_mes",""), json.dumps(dados.get("produtos",[])), dados.get("venda_meta",0),
                     dados.get("nome_mes",""), json.dumps(dados.get("produtos",[])), dados.get("venda_meta",0))
                )
    except Exception as e:
        print(f"[DEBUG] Erro ao salvar metas_produtos: {e}", flush=True)
    finally:
        conn.close()

def obter_metas_mes(mes_ano):
    metas = carregar_metas()
    return metas.get(mes_ano, {"nome_mes": "", "consolidada": 0, "vendedoras": {}})

METAS_PRODUTOS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'metas_produtos.json')

def carregar_metas_produtos():
    if os.path.exists(METAS_PRODUTOS_FILE):
        try:
            with open(METAS_PRODUTOS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    default = {"2026-08": {"nome_mes": "Agosto 2026", "produtos": [], "venda_meta": 241500.00}}
    salvar_metas_produtos(default)
    return default

def salvar_metas_produtos(metas):
    with open(METAS_PRODUTOS_FILE, 'w', encoding='utf-8') as f:
        json.dump(metas, f, ensure_ascii=False, indent=2)

def obter_metas_produtos_mes(mes_ano):
    metas = carregar_metas_produtos()
    return metas.get(mes_ano, {"nome_mes": "", "produtos": [], "venda_meta": 0})


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
    while pag <= 20:  # LIMITE de 20 páginas (5000 registros) em vez de 200
        params = {"limit": limit, "offset": offset, "order": ofield, "sort": "Desc"}
        try: resp = requests.get(f"{BASE_URL}{ep}", headers=headers, params=params, timeout=15)
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
        st = str(p.get("status_pedido", "") or "").strip()
        if st.lower() not in {s.lower() for s in STATUS_INCLUIDOS}: continue
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



def login_page_html(erro=""):
    msg = f'<div class="err">{erro}</div>' if erro else ''
    return f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Login - Real Acai Dashboard</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:linear-gradient(135deg,#1e3a5f 0%,#2563eb 100%);min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center}}
.card{{background:#fff;border-radius:16px;box-shadow:0 20px 60px rgba(0,0,0,.3);padding:40px;width:380px;max-width:90vw;margin-bottom:0}}
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
.err{{background:#fee2e2;color:#dc2626;padding:10px 14px;border-radius:8px;font-size:14px;margin-bottom:16px;text-align:center}}
.hint{{text-align:center;margin-top:16px;font-size:12px;color:#94a3b8}}
.footer{{width:100%;max-width:600px;margin:24px auto 0;text-align:center;color:rgba(255,255,255,.6);font-size:12px;line-height:1.8}}
.footer strong{{color:rgba(255,255,255,.85)}}
.footer-divider{{border:none;border-top:1px solid rgba(255,255,255,.15);margin:12px auto;max-width:400px}}
.footer-copy{{font-size:11px;opacity:.7}}
</style>
</head>
<body>
<div class="card">
<div class="logo">
<img src="/logo" alt="Real Acai" onerror="this.style.display='none'" style="max-height:100px;max-width:220px;object-fit:contain">
<h1>Real Acai Distribuidora</h1>
<p>Dashboard Gerencial</p>
</div>
{msg}
<form method="POST" action="/login">
<div class="field"><label>Usuario</label><input type="text" name="username" autofocus required></div>
<div class="field"><label>Senha</label><input type="password" name="senha" required></div>
<button class="btn" type="submit">Entrar</button>
</form>
<div class="hint">Acesso restrito a colaboradores autorizados</div>
</div>
<div class="footer">
<div>Os dados deste sistema sao sincronizados automaticamente atraves do sistema de gestao empresarial <strong>VHSYS</strong></div>
<hr class="footer-divider">
<div class="footer-copy">(c) 2026 Real Acai Distribuidora - Todos os direitos reservados<br>Desenvolvido por Gabriel Freitas</div>
</div>
</body>
</html>'''


def admin_page_html(users):
    linhas = ''
    for u in sorted(users, key=lambda x: x.get("login", "")):
        uname = u["login"]
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
.hdr a:hover{{background:rgba(255,255,255,.25)}}
.ctn{{max-width:1100px;margin:0 auto;padding:24px}}
.card{{background:#fff;border-radius:12px;box-shadow:0 1px 3px rgba(0,0,0,.1);padding:24px;margin-bottom:24px}}
.card h2{{font-size:17px;font-weight:700;margin-bottom:16px;padding-bottom:10px;border-bottom:2px solid #e2e8f0}}
.form-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:12px;align-items:end}}
.fg label{{display:block;font-size:12px;font-weight:600;color:#64748b;text-transform:uppercase;margin-bottom:4px}}
.fg input,.fg select{{width:100%;padding:9px 12px;border:2px solid #e2e8f0;border-radius:8px;font-size:14px;outline:none}}
.fg input:focus,.fg select:focus{{border-color:#2563eb}}
.btn-add{{background:#16a34a;color:#fff;border:none;padding:10px 20px;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer}}
.btn-add:hover{{background:#15803d}}
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
.ok{{background:#dcfce7;color:#16a34a;padding:10px 14px;border-radius:8px;font-size:14px;margin-bottom:16px}}
.err2{{background:#fee2e2;color:#dc2626;padding:10px 14px;border-radius:8px;font-size:14px;margin-bottom:16px}}
</style>
</head>
<body>
<div class="hdr">
<h1>Gerenciar Usuarios</h1>
<a href="/">Voltar ao Dashboard</a>
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


import threading

_atualizando_cache = False

import threading

_atualizando_cache = False

def atualizar_cache_background(meses=1, nome_user='Usuario', forcar=False):
    global _atualizando_cache
    with _cache_lock:
        if _atualizando_cache and not forcar:
            return
        _atualizando_cache = True

    try:
        hoje = date.today()
        # Busca o mês atual
        di = hoje.replace(day=1).isoformat()
        df = hoje.isoformat()

        print(f"[DEBUG] Buscando dados de {di} a {df}", flush=True)

        todos_pedidos = []
        for emp in EMPRESAS:
            try:
                headers = make_headers(emp)
                # CORRIGIDO: listar_pedidos_periodo_rapido (nome real da função)
                pedidos = listar_pedidos_periodo_rapido(di, df, emp, headers)
                processados = processar_pedidos(pedidos, emp)
                todos_pedidos.extend(processados)
                print(f"[DEBUG] {emp.get('nome','?')}: {len(processados)} pedidos", flush=True)
            except Exception as e:
                print(f"[DEBUG] Erro empresa {emp.get('nome','?')}: {e}", flush=True)

        # FALLBACK: se mês atual não tem dados, busca 3 meses
        if not todos_pedidos:
            print("[DEBUG] Sem dados no mes atual, buscando 3 meses...", flush=True)
            di = (hoje.replace(day=1) - timedelta(days=90)).isoformat()
            for emp in EMPRESAS:
                try:
                    headers = make_headers(emp)
                    # CORRIGIDO: listar_pedidos_periodo_rapido (nome real da função)
                    pedidos = listar_pedidos_periodo_rapido(di, df, emp, headers)
                    processados = processar_pedidos(pedidos, emp)
                    todos_pedidos.extend(processados)
                    print(f"[DEBUG] FALLBACK {emp.get('nome','?')}: {len(processados)} pedidos", flush=True)
                except Exception as e:
                    print(f"[DEBUG] Erro fallback {emp.get('nome','?')}: {e}", flush=True)

        entregas = []
        try:
            entregas = ler_dados_entregas()
            print(f"[DEBUG] Entregas: {len(entregas)}", flush=True)
        except Exception as e:
            print(f"[DEBUG] Erro entregas: {e}", flush=True)

        produtos = []

        html = gerar_dashboard_html(todos_pedidos, entregas, produtos)

        with _cache_lock:
            _cache["timestamp"] = time.time()
            _cache["html"] = html
            _cache["periodo_meses"] = meses
            _atualizando_cache = False

        print(f"[DEBUG] Cache atualizado: {len(todos_pedidos)} pedidos totais", flush=True)
    except Exception as e:
        print(f"[DEBUG] Erro cache background: {e}", flush=True)
        with _cache_lock:
            _atualizando_cache = False

def usuario_logado():
    if 'user' not in session:
        return None
    usuarios = carregar_usuarios()
    users = {u["login"]: u for u in usuarios}
    return users.get(session['user'])

@app.route('/dashboard')
def dashboard():
    if not session.get('user'):
        return redirect('/login')
    
    # Captura o nome AQUI (dentro do contexto da requisição - funciona)
    u = usuario_logado()
    nome_user = u.get('nome', 'Usuario') if u else 'Usuario'
    
    # Passa o nome para a thread
    threading.Thread(target=atualizar_cache_background, args=(1, nome_user), daemon=True).start()
    
    with _cache_lock:
        ts = _cache.get("timestamp", 0)
        html_cache = _cache.get("html", "")
        _atualizando = _atualizando_cache
        periodo_cache = _cache.get("periodo_meses", 0)
    
    agora = time.time()
    
    # Se tem cache, retorna instantaneamente
    if html_cache:
        if busca_longa and periodo_cache < 12:
            if not _atualizando:
                threading.Thread(target=atualizar_cache_background, args=(12,), daemon=True).start()
            return LOADING_HTML
        if (agora - ts) > CACHE_TEMPO_SEGUNDOS and not _atualizando:
            threading.Thread(target=atualizar_cache_background, args=(1,), daemon=True).start()
        return html_cache
    usr = usuario_logado()
    nome_user = usr.get('nome', 'Usuario') if usr else 'Usuario'
    threading.Thread(target=atualizar_cache_background, args=(1, nome_user), daemon=True).start()
    
   

LOADING_HTML = '''<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Carregando Dashboard...</title>
<style>
body{margin:0;display:flex;align-items:center;justify-content:center;
min-height:100vh;background:linear-gradient(135deg,#1a0a2e,#4c1d95);
font-family:Arial,sans-serif;color:#fff;text-align:center}
.loader{border:5px solid #f3f3f3;border-top:5px solid #9333ea;
border-radius:50%;width:50px;height:50px;animation:spin 1s linear infinite;margin:20px auto}
@keyframes spin{0%{transform:rotate(0)}100%{transform:rotate(360deg)}}
h2{margin-bottom:10px} p{opacity:0.8}
</style></head>
<body><div>
<h2>Carregando Dashboard...</h2>
<div class="loader"></div>
<p>Buscando dados do mes atual. Aguarde.</p>
</div>
<script>
setTimeout(function(){ window.location.reload(); }, 20000);
</script>
</body></html>'''

def gerar_dashboard_html(pedidos, entregas, produtos):
    def safe_json(obj):
        return json.dumps(obj, ensure_ascii=False, default=str).replace("</", "<\/")
    dj = safe_json(pedidos)
    ej = safe_json(entregas)
    pj = safe_json(produtos)
    with _metas_lock:
        all_metas = carregar_metas()
        mj = safe_json(all_metas)
        mc = 0
        all_metas_prod = carregar_metas_produtos()
        mpr = safe_json(all_metas_prod)
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
<div class="hdr"><div class="hdr-logo"><img src="/logo" alt="Real Acai" style="height:80px;border-radius:10px;object-fit:contain;background:#fff;padding:6px 10px;" onerror="this.style.display='none';document.getElementById('logoFallback').style.display='flex'"><div id="logoFallback" style="display:none;width:80px;height:80px;border-radius:10px;background:#fff;color:#2563eb;align-items:center;justify-content:center;font-size:32px;font-weight:900;flex-shrink:0;">RA</div><div><h1>Real Acai Distribuidora</h1><div class="sub">Dashboard Gerencial - Vhsys API v2</div></div></div><div style="display:flex;align-items:center;gap:16px"><div class="upd">Dados gerados em: __DG__</div><div style="display:flex;align-items:center;gap:8px;background:rgba(255,255,255,.15);padding:8px 14px;border-radius:8px"><span style="font-size:14px;font-weight:600">__USER_NAME__</span><a href="/admin/usuarios" id="btnUsuarios" style="color:#fff;text-decoration:none;font-size:13px;padding:4px 10px;background:rgba(22,163,74,.8);border-radius:6px;display:none">Usuarios</a><a href="/admin/usuarios" id="btnUsuarios" style="color:#fff;text-decoration:none;font-size:13px;padding:4px 10px;background:rgba(22,163,74,.8);border-radius:6px;display:none">Usuarios</a><a href="/logout" style="color:#fff;text-decoration:none;font-size:13px;padding:4px 10px;background:rgba(220,38,38,.8);border-radius:6px">Sair</a></div></div></div>
<div class="tabs" id="navTabs">
<button class="tab act" data-sector="comercial" onclick="sw('comercial',this)">Comercial</button>
<button class="tab" data-sector="logistica" onclick="sw('logistica',this)">Logistica</button>
<button class="tab" data-sector="contabil" onclick="sw('contabil',this)">Contabil</button>
</div>
<div class="ctn">
<div class="fb"><div class="fg"><label>De</label><input type="date" id="dIni" value="__MIN__"></div><div class="fg"><label>Ate</label><input type="date" id="dFim" value="__MAX__"></div><button class="ba" onclick="af()">Aplicar</button><div style="margin-left:auto;display:flex;gap:8px"><button class="bp" onclick="ph()" id="btnHoje">Hoje</button><button class="bp" onclick="p7()" id="btn7d">7d</button><button class="bp" onclick="pm()" id="btnMes">Mes</button><button class="bp" onclick="pt()" id="btnTudo">Tudo</button></div></div>
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
</div>
<div id="tc-con" class="tc">
<div class="kg" id="kpiC"></div>
<div class="st">CMV - Custo de Mercadorias Vendidas</div>
<div class="fb" style="flex-direction:column;align-items:flex-start;gap:12px">
<div class="cig"><div class="fg"><label>Estoque Inicial</label><input type="date" id="cmvDi"></div><div class="fg"><label>Estoque Final</label><input type="date" id="cmvDf"></div></div>
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
<div class="footer-copy">(c) 2026 Real Acai Distribuidora - Todos os direitos reservados<br>Desenvolvido por Gabriel Freitas - Desenvolvedor Autonomo - v1.1.0 - Ultima atualizacao: 15/08/2026</div>
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
var cV,cD,cK,cE,cED;
function renderTudo(){var ini=document.getElementById('dIni').value,fim=document.getElementById('dFim').value;var ped=TP.filter(function(p){return p.data>=ini&&p.data<=fim});if(ef!=='todos')ped=ped.filter(function(p){return p.empresa===ef});var mr=fim.substring(0,7);currentMR=mr;var metasMes=gm(mr);document.getElementById('mesL').textContent=metasMes.nome_mes||fm2(mr);var hoje=new Date();var maStr=hoje.getFullYear()+'-'+String(hoje.getMonth()+1).padStart(2,'0');var fma=TP.filter(function(p){return p.data.substring(0,7)===maStr&&(ef==='todos'||p.empresa===ef)}).reduce(function(s,p){return s+p.valor},0);if(ped.length===0){msd()}else{var pv={};ped.forEach(function(p){var v=nn(p.vendedor);if(!pv[v])pv[v]={n:v,f:0,q:0,e:p.empresa};pv[v].f+=p.valor;pv[v].q+=1});var vs=Object.values(pv).sort(function(a,b){return b.f-a.f});vs.forEach(function(v){v.f=Math.round(v.f*100)/100});var ft=vs.reduce(function(s,v){return s+v.f},0),qv=vs.reduce(function(s,v){return s+v.q},0),tm=qv>0?ft/qv:0,dp=cd(ini,fim);rk(ft,qv,tm,dp,vs.length);rm(vs,mr,fma,maStr);rcV(vs);rcD(ped);rcK(vs,ft);rt(vs,ft);rc(ped,ft,qv)}var ent=TE.filter(function(e){return e.data>=ini&&e.data<=fim});re(ent,ini,fim)}
function sw(t,b){var map={'comercial':'tc-com','logistica':'tc-log','contabil':'tc-con'};document.querySelectorAll('.tc').forEach(function(x){x.classList.remove('act')});document.querySelectorAll('.tab').forEach(function(x){x.classList.remove('act')});var target=document.getElementById(map[t]);if(target){target.classList.add('act')}else{console.log('Aba nao encontrada: '+map[t]);return}b.classList.add('act');var fbE=document.getElementById('fbEmp');if(fbE){if(t==='logistica'||t==='contabil'){fbE.style.display='none'}else{fbE.style.display='flex'}}setTimeout(function(){try{if(t==='comercial'){if(typeof cV!=='undefined'&&cV)cV.resize();if(typeof cD!=='undefined'&&cD)cD.resize();if(typeof cK!=='undefined'&&cK)cK.resize();}else if(t==='logistica'){if(typeof cE!=='undefined'&&cE)cE.resize();if(typeof cED!=='undefined'&&cED)cED.resize();}}catch(e){console.log('Erro resize: '+e)}},50)
}
function nn(n){if(!n)return 'Sem vendedor';return String(n).replace(/[\xa0\t\n\r]/g,' ').replace(/\s+/g,' ').trim().toUpperCase()}
function bm(n){var m=gm(currentMR);var nl=n.toLowerCase();var k=Object.keys(m.vendedoras).find(function(x){return x.toLowerCase()===nl});return k?m.vendedoras[k]:0}
function fm(v){return'R$ '+Number(v).toLocaleString('pt-BR',{minimumFractionDigits:2,maximumFractionDigits:2})}
function fd(i){var p=i.split('-');return p[2]+'/'+p[1]}
function cd(i,f){var d1=new Date(i+'T00:00:00');var d2=new Date(f+'T00:00:00');return Math.round((d2-d1)/86400000)+1}
function fm2(mr){var p=mr.split('-');var n=['Jan','Fev','Mar','Abr','Mai','Jun','Jul','Ago','Set','Out','Nov','Dez'];return n[parseInt(p[1])-1]+' '+p[0]}
function init(){filtrarAbas();if(IS_MASTER){var b=document.getElementById('btnMeta');if(b)b.style.display='';var bp=document.getElementById('btnMetaProd');if(bp)bp.style.display='';var bu=document.getElementById('btnUsuarios');if(bu)bu.style.display=''}renderTudo();carregarProdutos()}
function se(e,b){ef=e;document.querySelectorAll('.be').forEach(function(x){x.classList.remove('act')});if(b)b.classList.add('act');af()}
function ph(){var h=new Date().toISOString().split('T')[0];sd(h,h)}
function p7(){var f=new Date();var i=new Date();i.setDate(i.getDate()-6);sd(i.toISOString().split('T')[0],f.toISOString().split('T')[0])}
function pm(){var a=new Date();var i=new Date(a.getFullYear(),a.getMonth(),1);var f=new Date(a.getFullYear(),a.getMonth()+1,0);sd(i.toISOString().split('T')[0],f.toISOString().split('T')[0])}
function pt(){sd('__MIN__','__MAX__')}
function sd(i,f){document.getElementById('dIni').value=i;document.getElementById('dFim').value=f;af()}
function af(){var btn=document.querySelector('.ba');if(btn){btn.textContent='Filtrando...';btn.disabled=true}setTimeout(function(){renderTudo();if(btn){btn.textContent='Aplicar';btn.disabled=false}},100)}
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
<a href="/dashboard?periodo=completo" style="position:fixed;top:15px;right:15px;background:#9333ea;color:#fff;padding:8px 16px;border-radius:8px;text-decoration:none;font-size:13px;z-index:9999;">📅 Ver 12 meses</a>
<a href="/dashboard" style="position:fixed;top:15px;right:130px;background:#6b21a8;color:#fff;padding:8px 16px;border-radius:8px;text-decoration:none;font-size:13px;z-index:9999;">📅 Ver 3 meses</a>
renderTudo();
</script>
</body>
</html>'''
    html = html.replace("__DJ__", dj).replace("__EJ__", ej).replace("__PJ__", pj).replace("__MJ__", mj).replace("__MC__", str(mc)).replace("__MPR__", mpr).replace("__DG__", dg).replace("__MIN__", mind).replace("__MAX__", maxd).replace("__USER_NAME__", nome_user.get('nome', 'Usuario') if nome_user else 'Usuario')
    return html

@app.route('/debug-files')
def debug_files():
    import os
    caminho = os.path.dirname(os.path.abspath(__file__))
    arquivos = os.listdir(caminho)
    return f"<h3>Diretório: {caminho}</h3><p>Arquivos: {arquivos}</p>"


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = request.form.get('username', '').strip()
        senha = request.form.get('senha', '')
        usuarios = carregar_usuarios()
        users = {u["login"]: u for u in usuarios}
        u = users.get(user)
        
        if u and u["senha"] == senha:
            session['user'] = user
            return redirect('/dashboard')
        return login_page_html("Usuario ou senha invalidos.")
    return login_page_html()

def nome_user():
    if 'user' not in session:
        return None
    usuarios = carregar_usuarios()
    users = {u["login"]: u for u in usuarios}
    u = users.get(nome_user['user'])
    return u

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/login')

@app.route('/admin/usuarios')
@requer_admin_master
def admin_usuarios():
    users = carregar_usuarios()
    return admin_page_html(users)

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
    logins_existentes = [u["login"] for u in users]
    if username in logins_existentes:
        return redirect('/admin/usuarios?erro=existe')
    novo = {
        "nome": nome,
        "login": username,
        "senha": senha,
        "role": role,
        "setor": setor
    }
    users.append(novo)
    salvar_usuarios(users)
    return redirect('/admin/usuarios?ok=1')


@app.route('/admin/usuarios/excluir', methods=['POST'])
@requer_admin_master
def admin_excluir_usuario():
    username = request.form.get('username', '')
    if username == 'admin':
        return redirect('/admin/usuarios?erro=admin')
    users = carregar_usuarios()
    for i, u in enumerate(users):
        if u["login"] == username:
            del users[i]
            break
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
    for u in users:
        if u["login"] == username:
            u["senha"] = nova
            break
    salvar_usuarios(users)
    return redirect('/admin/usuarios?ok=senha')



import os

@app.route('/logo')
def serve_logo():
    caminho = os.path.join(app.root_path, 'Logo_Real_Distribuidora.png')
    try:
        with open(caminho, 'rb') as f:
            return Response(f.read(), mimetype='image/png')
    except FileNotFoundError:
        return "Not found", 404

@app.route('/imagem-fachada')
def imagem_fachada():
    caminho = os.path.join(app.root_path, 'imagem_frente.jpg')
    try:
        with open(caminho, 'rb') as f:
            return Response(f.read(), mimetype='image/jpeg')
    except FileNotFoundError:
        return "Not found", 404
    
def get_produtos_cache():
    with _produtos_lock:
        return dict(_produtos_cache)

def buscar_produtos_background(pedidos):
    with _produtos_lock:
        if _produtos_cache["calculando"]:
            return
        _produtos_cache["calculando"] = True
    try:
        resultado = buscar_produtos_de_pedidos(pedidos)
        with _produtos_lock:
            _produtos_cache["timestamp"] = time.time()
            _produtos_cache["data"] = resultado
            _produtos_cache["calculando"] = False
        print(f"[DEBUG] Produtos cacheados: {len(resultado)}", flush=True)
    except Exception as e:
        print(f"[DEBUG] Erro produtos background: {e}", flush=True)
        with _produtos_lock:
            _produtos_cache["calculando"] = False


LANDING_PAGE_HTML = '''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Real Açaí Distribuidora - Qualidade que você conhece</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;color:#1a1a2e;scroll-behavior:smooth}

/* HEADER */
.header{position:fixed;top:0;left:0;right:0;z-index:100;background:rgba(20,10,30,0.95);backdrop-filter:blur(10px);padding:10px 40px;display:flex;align-items:center;justify-content:space-between;box-shadow:0 2px 10px rgba(0,0,0,0.3)}
.header .logo{display:flex;align-items:center;gap:12px}
.header .logo img{height:42px;border-radius:8px}
.header .logo span{color:#fff;font-size:16px;font-weight:700;letter-spacing:0.5px}
.header nav{display:flex;gap:24px}
.header nav a{color:#c4b5fd;text-decoration:none;font-size:14px;font-weight:500;transition:color .2s;position:relative}
.header nav a:hover{color:#fff}
.header nav a::after{content:"";position:absolute;bottom:-4px;left:0;width:0;height:2px;background:#a855f7;transition:width .3s}
.header nav a:hover::after{width:100%}
.header .btn-login{background:linear-gradient(135deg,#7c3aed,#a855f7);color:#fff;padding:8px 22px;border-radius:8px;text-decoration:none;font-size:14px;font-weight:600;transition:transform .2s,box-shadow .2s}
.header .btn-login:hover{transform:translateY(-1px);box-shadow:0 4px 12px rgba(168,85,247,0.4)}

/* HERO */
.hero{min-height:100vh;display:flex;align-items:center;justify-content:center;position:relative;background:linear-gradient(135deg,rgba(20,10,30,0.88),rgba(76,29,149,0.75)),url('/imagem-fachada') center/cover no-repeat fixed}
.hero-content{text-align:center;max-width:750px;padding:0 20px}
.hero-content .badge-top{display:inline-block;background:rgba(168,85,247,0.2);border:1px solid rgba(168,85,247,0.4);color:#c4b5fd;padding:6px 18px;border-radius:20px;font-size:13px;font-weight:600;margin-bottom:20px}
.hero-content h1{color:#fff;font-size:44px;font-weight:800;line-height:1.2;margin-bottom:18px;text-shadow:0 2px 20px rgba(0,0,0,0.5)}
.hero-content h1 span{color:#a855f7}
.hero-content p{color:#e9d5ff;font-size:18px;margin-bottom:32px;line-height:1.7}
.hero-content .btn-pedido{background:linear-gradient(135deg,#16a34a,#22c55e);color:#fff;padding:16px 42px;border-radius:12px;text-decoration:none;font-size:18px;font-weight:700;display:inline-block;transition:transform .2s,box-shadow .2s;box-shadow:0 4px 15px rgba(22,163,74,0.3)}
.hero-content .btn-pedido:hover{transform:translateY(-2px);box-shadow:0 8px 25px rgba(22,163,74,0.5)}
.hero-content .verse{margin-top:28px;color:#a78bfa;font-size:14px;font-style:italic;opacity:0.8}

/* DIFERENCIAIS */
.diferenciais{background:linear-gradient(180deg,#0f0a1a,#1a1030);padding:50px 40px;display:flex;justify-content:center;gap:40px;flex-wrap:wrap}
.diff-card{text-align:center;max-width:220px}
.diff-card .icon{font-size:40px;margin-bottom:14px}
.diff-card h3{font-size:15px;font-weight:700;margin-bottom:6px;color:#fff}
.diff-card p{font-size:13px;color:#a78bfa;line-height:1.5}

/* SEÇÕES */
.section{padding:70px 40px;max-width:1100px;margin:0 auto}
.section h2{font-size:30px;font-weight:700;margin-bottom:30px;text-align:center;color:#1a1a2e}
.section h2 span{color:#7c3aed}
.section-gray{background:#faf8ff}

/* HISTÓRIA */
.historia-grid{display:grid;grid-template-columns:1fr 1.2fr;gap:50px;align-items:center}
.historia-grid .img-box{border-radius:16px;overflow:hidden;box-shadow:0 8px 30px rgba(76,29,149,0.2);background:linear-gradient(135deg,#2d1b4e,#4c1d95);height:350px;display:flex;align-items:center;justify-content:center;position:relative}
.historia-grid .img-box img{width:100%;height:100%;object-fit:cover}
.historia-grid .img-box .verse-overlay{position:absolute;bottom:0;left:0;right:0;background:rgba(20,10,30,0.85);color:#c4b5fd;padding:12px;text-align:center;font-size:13px;font-style:italic}
.historia-grid .texto p{font-size:16px;line-height:1.9;color:#475569;margin-bottom:16px}
.historia-grid .texto p strong{color:#7c3aed}
.historia-grid .texto .destaque{font-size:20px;font-weight:700;color:#7c3aed;margin-top:20px;text-align:center;padding:16px;background:linear-gradient(135deg,rgba(168,85,247,0.08),rgba(124,58,237,0.05));border-radius:12px;border-left:4px solid #7c3aed}

/* VENDEDORAS */
.vendedoras-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:24px;margin-top:20px}
.vendedora-card{background:#fff;border-radius:16px;padding:28px;text-align:center;box-shadow:0 4px 15px rgba(0,0,0,0.06);transition:transform .2s,box-shadow .2s;border:2px solid transparent}
.vendedora-card:hover{transform:translateY(-6px);box-shadow:0 12px 30px rgba(124,58,237,0.15);border-color:#e9d5ff}
.vendedora-card .avatar{width:70px;height:70px;border-radius:50%;background:linear-gradient(135deg,#7c3aed,#a855f7);margin:0 auto 16px;display:flex;align-items:center;justify-content:center;color:#fff;font-size:28px;font-weight:700}
.vendedora-card h4{font-size:18px;font-weight:700;margin-bottom:4px;color:#1a1a2e}
.vendedora-card .role{font-size:13px;color:#7c3aed;font-weight:600;margin-bottom:12px}
.vendedora-card .telefone{font-size:15px;color:#475569;margin-bottom:16px}
.vendedora-card .btn-wpp{display:inline-flex;align-items:center;gap:8px;background:#25D366;color:#fff;padding:10px 22px;border-radius:10px;text-decoration:none;font-size:14px;font-weight:600;transition:background .2s}
.vendedora-card .btn-wpp:hover{background:#1da851}

/* FAÇA PEDIDO */
.pedido-section{background:linear-gradient(135deg,#1a1030,#4c1d95);color:#fff;padding:80px 40px;text-align:center}
.pedido-section h2{color:#fff}
.pedido-section h2 span{color:#c4b5fd}
.pedido-section .sub{font-size:17px;margin-bottom:30px;opacity:0.9;max-width:600px;margin-left:auto;margin-right:auto}
.pedido-section .btn-wpp-grande{display:inline-flex;align-items:center;gap:10px;background:#25D366;color:#fff;padding:16px 40px;border-radius:12px;text-decoration:none;font-size:18px;font-weight:700;transition:transform .2s}
.pedido-section .btn-wpp-grande:hover{transform:translateY(-2px)}
.pedido-section .ou{margin-top:20px;font-size:14px;color:#c4b5fd}
.pedido-section .ou a{color:#fff;text-decoration:underline}

/* CONTATO */
.contato-grid{display:grid;grid-template-columns:1.2fr 1fr;gap:50px;align-items:start}
.contato-info .item{display:flex;align-items:start;gap:14px;margin-bottom:20px}
.contato-info .item .ic{font-size:24px;flex-shrink:0;margin-top:2px}
.contato-info .item strong{display:block;font-size:14px;color:#7c3aed;text-transform:uppercase;font-weight:700;margin-bottom:4px}
.contato-info .item span{font-size:15px;color:#475569;line-height:1.6}
.contato-info .item a{color:#475569;text-decoration:none}
.contato-info .item a:hover{color:#7c3aed}
.contato-info .social{display:flex;gap:12px;margin-top:20px}
.contato-info .social a{display:flex;align-items:center;justify-content:center;width:44px;height:44px;border-radius:10px;background:linear-gradient(135deg,#7c3aed,#a855f7);color:#fff;text-decoration:none;font-size:20px;transition:transform .2s}
.contato-info .social a:hover{transform:translateY(-3px)}
.qr-box{text-align:center}
.qr-box .qr-placeholder{width:200px;height:200px;margin:0 auto 16px;background:#f3f0ff;border-radius:16px;display:flex;align-items:center;justify-content:center;border:3px solid #7c3aed}
.qr-box .qr-placeholder svg{width:100%;height:100%;padding:10px}
.qr-box p{font-size:14px;color:#64748b}

/* RODAPÉ */
.rodape{background:#0a0510;color:#94a3b8;padding:40px 40px 20px}
.rodape-grid{max-width:1100px;margin:0 auto;display:grid;grid-template-columns:1fr 1fr 1fr;gap:40px;margin-bottom:30px}
.rodape-col h5{color:#fff;font-size:15px;font-weight:700;margin-bottom:14px}
.rodape-col p,.rodape-col a{font-size:13px;color:#94a3b8;text-decoration:none;line-height:1.8;display:block}
.rodape-col a:hover{color:#c4b5fd}
.rodape-bottom{max-width:1100px;margin:0 auto;border-top:1px solid rgba(255,255,255,0.08);padding-top:20px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:10px}
.rodape-bottom .copy{font-size:12px;color:#64748b}
.rodape-bottom .dev{font-size:12px;color:#64748b}
.rodape-bottom .dev strong{color:#a78bfa}

/* MOBILE */
@media(max-width:768px){
.header{padding:8px 16px}
.header nav{display:none}
.header .logo span{font-size:14px}
.hero-content h1{font-size:28px}
.hero-content p{font-size:15px}
.historia-grid,.contato-grid{grid-template-columns:1fr}
.diferenciais{gap:20px}
.rodape-grid{grid-template-columns:1fr}
}
</style>
</head>
<body>

<!-- HEADER -->
<div class="header">
<div class="logo">
<img src="/logo" alt="Real Acai">
<span>REAL AÇAÍ DISTRIBUIDORA</span>
</div>
<nav>
<a href="#inicio">Início</a>
<a href="#historia">Nossa História</a>
<a href="#vendedoras">Vendedoras</a>
<a href="#pedido">Faça seu Pedido</a>
<a href="#contato">Contato</a>
</nav>
<a href="/login" class="btn-login">Login / Dashboard</a>
</div>

<!-- HERO -->
<div class="hero" id="inicio">
<div class="hero-content">
<span class="badge-top">🍇 Tradição em cada detalhe</span>
<h1>A tradição e qualidade que você conhece,<br><span>agora também online</span></h1>
<p>Há mais de 5 anos levando os melhores produtos para sua família.<br>Faça seu pedido de onde estiver, receba com agilidade.</p>
<a href="#pedido" class="btn-pedido">Fazer Pedido</a>
<div class="verse">"Até aqui nos ajudou o Senhor" — 1 Samuel 7:12</div>
</div>
</div>

<!-- DIFERENCIAIS -->
<div class="diferenciais">
<div class="diff-card"><div class="icon">⚡</div><h3>Entrega Rápida</h3><p>Agilidade na entrega dos seus pedidos</p></div>
<div class="diff-card"><div class="icon">✅</div><h3>Qualidade Garantida</h3><p>Produtos selecionados com padrão de excelência</p></div>
<div class="diff-card"><div class="icon">🏭</div><h3>Indústria Própria</h3><p>Desenvolvemos nossos próprios gelatos e açaís</p></div>
<div class="diff-card"><div class="icon">🤝</div><h3>Atendimento Personalizado</h3><p>Equipe dedicada para te atender com cuidado</p></div>
</div>

<!-- NOSSA HISTÓRIA -->
<div class="section" id="historia">
<h2>Conheça um pouco de <span>nossa história</span></h2>
<div class="historia-grid">
<div class="img-box">
<img src="imagem-fachada" alt="Real Acai">
<div class="verse-overlay">"Até aqui nos ajudou o Senhor" — 1 Samuel 7:12</div>
</div>
<div class="texto">
<p>A <strong>Real Açaí Distribuidora</strong> nasceu de um sonho que começou há mais de 5 anos, quando inauguramos nossa primeira loja de self-service de açaí no bairro Cristo Redentor, pioneira nesse modelo de comércio na região.</p>
<p>O sonho cresceu e hoje contamos com <strong>três lojas ativas</strong> e uma <strong>indústria própria</strong>, onde desenvolvemos nossos gelatos e nossas melhores linhas de açaí.</p>
<p>Nossa história é construída com muito trabalho, dedicação e compromisso com a qualidade. Buscamos sempre os melhores produtos e matérias-primas do mercado para oferecer a você, nosso cliente, uma experiência única em sabor e qualidade.</p>
<div class="destaque">Açaí tem muitos, mas Real, só aqui! 🍇</div>
</div>
</div>
</div>

<!-- VENDEDORAS -->
<div class="section section-gray" id="vendedoras">
<h2>Nossas <span>Consultoras de Vendas</span></h2>
<div class="vendedoras-grid">
<div class="vendedora-card">
<div class="avatar">AR</div>
<h4>Ana Ruth</h4>
<div class="role">Consultora de Vendas</div>
<div class="telefone">(85) 9 9288-5598</div>
<a href="https://wa.me/5585992885598?text=Olá!%20Gostaria%20de%20fazer%20um%20pedido" target="_blank" class="btn-wpp">💬 Pedir pelo WhatsApp</a>
</div>
<div class="vendedora-card">
<div class="avatar">IL</div>
<h4>Isa Lima</h4>
<div class="role">Consultora de Vendas</div>
<div class="telefone">(85) 9 9187-3115</div>
<a href="https://wa.me/5585991873115?text=Olá!%20Gostaria%20de%20fazer%20um%20pedido" target="_blank" class="btn-wpp">💬 Pedir pelo WhatsApp</a>
</div>
<div class="vendedora-card">
<div class="avatar">SM</div>
<h4>Simone Moura</h4>
<div class="role">Consultora de Vendas</div>
<div class="telefone">(85) 9 8524-2498</div>
<a href="https://wa.me/5585985242498?text=Olá!%20Gostaria%20de%20fazer%20um%20pedido" target="_blank" class="btn-wpp">💬 Pedir pelo WhatsApp</a>
</div>
</div>
</div>

<!-- FAÇA SEU PEDIDO -->
<div class="pedido-section" id="pedido">
<h2>Faça seu <span>Pedido</span></h2>
<p class="sub">Escolha sua consultora preferida acima ou faça seu pedido direto pelo WhatsApp geral. É rápido e prático!</p>
<a href="https://wa.me/5585992885598?text=Olá!%20Gostaria%20de%20fazer%20um%20pedido" target="_blank" class="btn-wpp-grande">💬 Fazer Pedido Agora</a>
<div class="ou">Prefere acessar o sistema? <a href="/login">Entre no Dashboard →</a></div>
</div>

<!-- CONTATO -->
<div class="section" id="contato">
<h2>Contato e <span>Localização</span></h2>
<div class="contato-grid">
<div class="contato-info">
<div class="item">
<div class="ic">📍</div>
<div><strong>Endereço</strong><span>Av. Pres. Castelo Branco, 3833<br>Próximo à UPA e a Gerdau<br>Fortaleza - CE</span></div>
</div>
<div class="item">
<div class="ic">📞</div>
<div><strong>Telefones</strong><span>Ana Ruth: (85) 9 9288-5598<br>Isa Lima: (85) 9 9187-3115<br>Simone Moura: (85) 9 8524-2498</span></div>
</div>
<div class="item">
<div class="ic">✉️</div>
<div><strong>E-mail</strong><span><a href="mailto:financeiro@realacaidistribuidora.com.br">financeiro@realacaidistribuidora.com.br</a></span></div>
</div>
<div class="item">
<div class="ic">📸</div>
<div><strong>Instagram</strong><span><a href="https://instagram.com/realacaidistribuidora" target="_blank">@realacaidistribuidora</a></span></div>
</div>
<div class="item">
<div class="ic">🕒</div>
<div><strong>Horário</strong><span>Seg a Sex: 08h às 18h<br>Sábado: 08h às 12h</span></div>
</div>
<div class="social">
<a href="https://wa.me/5585992885598" target="_blank" title="WhatsApp">💬</a>
<a href="https://instagram.com/realacaidistribuidora" target="_blank" title="Instagram">📷</a>
<a href="mailto:financeiro@realacaidistribuidora.com.br" title="E-mail">✉️</a>
</div>
</div>
<div class="qr-box">
<div class="qr-placeholder">
<svg viewBox="0 0 100 100" xmlns="http://www.w3.org/2000/svg">
<rect width="100" height="100" fill="#fff"/>
<!-- QR Code simulado -->
<g fill="#1a1a2e">
<rect x="5" y="5" width="25" height="25"/>
<rect x="10" y="10" width="15" height="15" fill="#fff"/>
<rect x="12" y="12" width="11" height="11"/>
<rect x="70" y="5" width="25" height="25"/>
<rect x="75" y="10" width="15" height="15" fill="#fff"/>
<rect x="77" y="12" width="11" height="11"/>
<rect x="5" y="70" width="25" height="25"/>
<rect x="10" y="75" width="15" height="15" fill="#fff"/>
<rect x="12" y="77" width="11" height="11"/>
<rect x="35" y="5" width="5" height="5"/>
<rect x="45" y="5" width="5" height="5"/>
<rect x="55" y="10" width="5" height="5"/>
<rect x="35" y="15" width="10" height="5"/>
<rect x="50" y="15" width="5" height="10"/>
<rect x="40" y="25" width="5" height="5"/>
<rect x="35" y="35" width="5" height="5"/>
<rect x="45" y="35" width="10" height="5"/>
<rect x="60" y="35" width="5" height="10"/>
<rect x="70" y="40" width="5" height="5"/>
<rect x="80" y="40" width="10" height="5"/>
<rect x="35" y="45" width="5" height="10"/>
<rect x="45" y="50" width="5" height="5"/>
<rect x="55" y="45" width="10" height="10"/>
<rect x="70" y="55" width="5" height="5"/>
<rect x="80" y="55" width="5" height="10"/>
<rect x="40" y="60" width="5" height="5"/>
<rect x="50" y="65" width="10" height="5"/>
<rect x="65" y="65" width="5" height="10"/>
<rect x="75" y="70" width="5" height="5"/>
<rect x="85" y="75" width="5" height="5"/>
<rect x="35" y="75" width="5" height="10"/>
<rect x="45" y="80" width="5" height="5"/>
<rect x="55" y="85" width="5" height="5"/>
<rect x="65" y="85" width="10" height="5"/>
<rect x="80" y="85" width="10" height="5"/>
</g>
</svg>
</div>
<p>Escaneie para acessar nosso site</p>
</div>
</div>
</div>

<!-- RODAPÉ -->
<div class="rodape">
<div class="rodape-grid">
<div class="rodape-col">
<h5>Real Açaí Distribuidora</h5>
<p>Açaí tem muitos, mas Real, só aqui!</p>
<p style="margin-top:8px;font-style:italic;color:#a78bfa">"Até aqui nos ajudou o Senhor" — 1 Samuel 7:12</p>
</div>
<div class="rodape-col">
<h5>Links Rápidos</h5>
<a href="#inicio">Início</a>
<a href="#historia">Nossa História</a>
<a href="#vendedoras">Vendedoras</a>
<a href="#pedido">Faça seu Pedido</a>
<a href="#contato">Contato</a>
<a href="/login">Dashboard</a>
</div>
<div class="rodape-col">
<h5>Contato</h5>
<p>Av. Pres. Castelo Branco, 3833</p>
<p>Fortaleza - CE</p>
<p>financeiro@realacaidistribuidora.com.br</p>
<a href="https://instagram.com/realacaidistribuidora" target="_blank">@realacaidistribuidora</a>
</div>
</div>
<div class="rodape-bottom">
<div class="copy">© 2026 Real Açaí Distribuidora. Todos os direitos reservados.</div>
<div class="dev">Desenvolvido por <strong>[Gabriel Freitas]</strong></div>
</div>
</div>

</body>
</html>'''

@app.route('/')
def landing_page():
    return LANDING_PAGE_HTML

def forcar_atualizacao():
    with _cache_lock:
        _cache["timestamp"] = 0
        _cache["html"] = ""
    return "<script>window.location.href='/';</script>"

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
    u = nome_user
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


init_db()
migrar_dados_json_para_banco()
