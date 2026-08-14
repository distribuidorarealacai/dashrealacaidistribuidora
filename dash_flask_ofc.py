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
