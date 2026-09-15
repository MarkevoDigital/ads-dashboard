"""
Dashboard de Meta Ads + Google Ads.

Servidor Flask que:
  - le os dados (API Meta/Google, Google Sheets, CSV ou exemplo) num cache em memoria
  - mantem os dados frescos de tres formas (robusto para qualquer hospedagem):
      1) agendador interno diario (APScheduler)
      2) auto-refresh por validade: 1a requisicao de um novo dia recarrega
      3) endpoint /cron/refresh?token=... para cron externo (cPanel/Linux)
  - protege o acesso com login (se uma senha estiver configurada)
  - expoe /api/data com KPIs adaptativos, melhores anuncios, palavras-chave,
    comparativos e comentarios automaticos

Local:        python app.py
Producao:     gunicorn app:app   (ou Passenger via passenger_wsgi.py)
"""
from __future__ import annotations

import atexit
import os
import secrets
import subprocess
import sys
import threading
from datetime import datetime
from functools import wraps

# Hospedagem compartilhada (LVE) limita o numero de threads/processos. O numpy/OpenBLAS
# tenta abrir 1 thread por nucleo (dezenas) e falha ("Resource temporarily unavailable").
# Forcar 1 thread ANTES de importar pandas/numpy resolve.
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")

# O locale de algumas contas (ex.: markevo42) e ASCII -> um print com caractere
# nao-ASCII (acento, travessao "—") lanca UnicodeEncodeError e quebra o worker/
# agendador. Forca stdout/stderr em UTF-8 com errors="replace" (no-op se ja for).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.triggers.cron import CronTrigger
from flask import Flask, Response, g, jsonify, redirect, render_template, request

import analytics
import commentary
import i18n
from data_sources import STORE_CACHE, DataStore, load_clients, load_config


def _load_dotenv():
    """Carrega .env para o ambiente em execucao local (gunicorn/Passenger ja tratam)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(path):
        return
    for raw in open(path, encoding="utf-8"):
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k, v = raw.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())
    # No Windows com antivirus/proxy que inspeciona HTTPS, gRPC precisa do bundle local.
    bundle = os.path.join(os.path.dirname(os.path.abspath(__file__)), "win-ca-bundle.pem")
    if os.path.exists(bundle):
        os.environ.setdefault("GRPC_DEFAULT_SSL_ROOTS_FILE_PATH", bundle)
        os.environ.setdefault("SSL_CERT_FILE", bundle)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)


_load_dotenv()
config = load_config()
store = DataStore(config)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_cache_mtime = [0.0]      # mtime do pickle ja carregado em memoria
_seed_proc = [None]       # subprocesso de seed em andamento (se houver)
_seed_lock = threading.Lock()


def _spawn_seed() -> bool:
    """Roda o refresh PESADO (fetch da API + processamento) em PROCESSO SEPARADO via
    tools/seed_cache.py. Nunca no worker web: o Passenger roda 1 processo e um refresh
    de ~10min (latencia de DNS do us172) travaria o dashboard inteiro. O seed grava o
    pickle; o web app o rele depois (maybe_refresh). Retorna False se ja houver um seed
    rodando."""
    with _seed_lock:
        p = _seed_proc[0]
        if p is not None and p.poll() is None:
            return False  # ja ha um seed em andamento
        try:
            # nice(19) = baixa prioridade de CPU: o worker web tem preferencia e o
            # dashboard segue responsivo mesmo durante o seed (~10min). preexec_fn so
            # existe em POSIX; no Windows (dev) cai no except e roda sem nice.
            kwargs = {}
            if hasattr(os, "nice"):
                kwargs["preexec_fn"] = lambda: os.nice(19)
            _seed_proc[0] = subprocess.Popen(
                [sys.executable, os.path.join(BASE_DIR, "tools", "seed_cache.py")],
                cwd=BASE_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True, **kwargs,
            )
            print("[dados] Seed externo disparado (processo separado, nice).")
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"[dados] falha ao disparar seed externo: {exc}")
            return False


def _initial_load():
    """No boot do worker NAO carregamos o cache: o unpickle (~2.6MB de DataFrames)
    segura o GIL por segundos e, com spawn sob demanda do LSAPI, bloqueava o worker
    frio -> "Request Timeout" ao abrir o dashboard. O cache passa a ser carregado
    SOB DEMANDA no 1o /api/data (via maybe_refresh), deixando /, /static e /healthz
    instantaneos mesmo em worker frio. Aqui so tratamos o caso de ainda NAO existir
    cache: dispara um seed (barato, sem unpickle)."""
    try:
        if not os.path.exists(STORE_CACHE):
            print("[dados] Sem cache - disparando seed externo.")
            _spawn_seed()
    except Exception as exc:  # noqa: BLE001
        print(f"[dados] carga inicial falhou: {exc}")


threading.Thread(target=_initial_load, daemon=True).start()

app = Flask(__name__)
# Recarrega templates do disco a cada requisicao (evita precisar reiniciar o app
# so para servir HTML novo apos um git pull). Custo desprezivel para este trafego.
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

@app.after_request
def _sem_cache_compartilhado(resp):
    """Toda resposta e POR CLIENTE: nenhum cache compartilhado pode guarda-la.

    Em 09/09/2026, depois da migracao dos dois deploys para nginx + Passenger, um
    cache na frente do app passou a guardar /api/data indexado SO pela URL,
    ignorando o header Authorization: quem logasse depois recebia o payload do
    cliente anterior (NEP viu os dados do Kan; CarreiRHa viu os da Bem me Fiz).
    'private, no-store' faz qualquer cache intermediario desistir de guardar, e
    'Vary: Authorization' cobre os que respeitam Vary. /static fica de fora: e o
    mesmo arquivo para todo mundo e ja tem versao no nome (?v=mtime)."""
    if not request.path.startswith("/static/"):
        resp.headers["Cache-Control"] = "private, no-store, no-cache, max-age=0, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
        anterior = resp.headers.get("Vary")
        resp.headers["Vary"] = f"{anterior}, Authorization" if anterior else "Authorization"
    return resp


CRON_TOKEN = config.get("cron", {}).get("token", "")
AUTO_REFRESH_HORAS = float(config.get("atualizacao", {}).get("auto_refresh_horas", 12))


# ----------------------------------------------------------------------------
# Multi-tenant: cada cliente loga e ve so as proprias contas. "admin" ve tudo.
# ----------------------------------------------------------------------------
def _build_users():
    clients = load_clients()
    users = {}
    admin_pw = (clients.get("admin", {}) or {}).get("senha") or config.get("auth", {}).get("senha", "")
    if admin_pw:
        users["admin"] = {"senha": admin_pw, "scope": None,
                          "nome": "Agência (todos os clientes)", "idioma": "pt"}
    for c in clients.get("clientes", []):
        users[c["key"]] = {
            "senha": c.get("senha", ""),
            "scope": {"meta_ids": c.get("_meta_ids", set()),
                      "google_ids": c.get("_google_ids", set()),
                      "tiktok_ids": c.get("_tiktok_ids", set()),
                      "linkedin_ids": c.get("_linkedin_ids", set()),
                      "instagram_ids": c.get("_instagram_ids", set()),
                      "leads_form_only": bool(c.get("leads_form_only", False)),
                      "moeda": c.get("_moeda"),
                      "funil_ordem": c.get("_funil_ordem"),
                      # usada para achar o cliente no seguidores_manuais.json
                      "cliente_key": c["key"]},
            "nome": c.get("nome", c["key"]),
            "idioma": c.get("_idioma", "pt"),
        }
    # Agencia de grupo: um login que enxerga a UNIAO dos escopos de uma lista de
    # clientes e pode "ver como" cada um deles - nunca nada fora da lista.
    for a in clients.get("agencias", []):
        subs = [k for k in a.get("clientes", [])
                if users.get(k, {}).get("scope") is not None]
        uniao = {"meta_ids": set(), "google_ids": set(), "tiktok_ids": set(), "linkedin_ids": set(),
                 "instagram_ids": set(), "leads_form_only": False,
                 # clientes do grupo: seguidores da Pagina (LinkedIn) somados no bloco
                 "cliente_keys": list(subs),
                 "moeda": a.get("_moeda")}
        for k in subs:
            sc = users[k]["scope"]
            for campo in ("meta_ids", "google_ids", "tiktok_ids", "linkedin_ids", "instagram_ids"):
                uniao[campo] |= set(sc.get(campo) or ())
        users[a["key"]] = {
            "senha": a.get("senha", ""),
            "scope": uniao,
            "nome": a.get("nome", a["key"]),
            "idioma": a.get("_idioma", "pt"),
            "subclientes": subs,
        }
    return users


USERS = _build_users()
print(f"[auth] {len(USERS)} login(s) configurado(s): {', '.join(USERS) or '(nenhum - acesso aberto)'}")


def requires_auth(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        # Sem usuarios configurados -> acesso aberto (dev local).
        if not USERS:
            g.client = {"scope": None, "nome": ""}
            return fn(*args, **kwargs)
        auth = request.authorization
        if (auth and auth.username in USERS and auth.password
                and secrets.compare_digest(auth.password, USERS[auth.username]["senha"])):
            g.client = USERS[auth.username]
            return fn(*args, **kwargs)
        return Response(
            "Acesso restrito.", 401,
            {"WWW-Authenticate": 'Basic realm="Dashboard de Ads"'},
        )
    return wrapper


# ----------------------------------------------------------------------------
# Frescor dos dados
# ----------------------------------------------------------------------------
def maybe_refresh():
    """Chamado por requisicao. NUNCA faz fetch de API no processo web (saturaria o
    unico worker do Passenger). Faz duas coisas baratas/nao-bloqueantes:
      1) rele o pickle do disco se o seed externo gerou um mais novo;
      2) se o cache for de outro dia e nenhum seed estiver rodando, dispara o seed
         externo (processo separado) — auto-cura caso o cron nao tenha rodado."""
    try:
        mtime = os.path.getmtime(STORE_CACHE)
    except OSError:
        return
    if mtime > _cache_mtime[0] + 1:
        if store.load_cache(max_age_h=24 * 365):
            _cache_mtime[0] = mtime
            print(f"[dados] Cache recarregado do disco (de {store.updated_at}).")
    # Auto-seed-on-stale REMOVIDO: varios workers disparavam seeds simultaneos (guard
    # por-processo) -> tempestade que derrubava o servidor. Refresh fica so no cron.


# Segura o flock do agendador enquanto o worker viver (impede N schedulers).
_sched_lock_fd = [None]


def _acquire_scheduler_lock() -> bool:
    """So UM worker do Passenger deve rodar o agendador. Sem isto, cada worker cria
    seu proprio BackgroundScheduler e, as 07:00, TODOS disparam o seed ao mesmo tempo
    -> tempestade de processos que estoura o limite de nproc (LVE) e gera 503.
    flock exclusivo nao-bloqueante: o 1o worker segura; os demais pulam o agendador.
    O lock e liberado quando esse worker morre, e o proximo a subir assume."""
    try:
        import fcntl
    except ImportError:
        return True  # Windows (dev): roda o agendador normalmente.
    try:
        os.makedirs(os.path.join(BASE_DIR, "tmp"), exist_ok=True)
        fd = os.open(os.path.join(BASE_DIR, "tmp", "scheduler.lock"),
                     os.O_CREAT | os.O_RDWR, 0o644)
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        _sched_lock_fd[0] = fd  # mantem aberto -> mantem o lock
        return True
    except OSError:
        return False  # outro worker ja e o dono do agendador.


def _start_scheduler():
    if not _acquire_scheduler_lock():
        print("[agendador] outro worker ja roda o agendador - este worker nao inicia.")
        return
    sched = config.get("atualizacao", {})
    hhmm = sched.get("hora_diaria", "07:00")
    tz = sched.get("fuso", "America/Sao_Paulo")
    hour, minute = (int(x) for x in hhmm.split(":"))
    # Pool de 1 thread: o job so dispara um subprocesso (leve). Menos threads = menos nproc.
    scheduler = BackgroundScheduler(
        timezone=tz, executors={"default": ThreadPoolExecutor(1)})
    scheduler.add_job(
        _spawn_seed,  # seed em processo separado (nao satura o worker web)
        CronTrigger(hour=hour, minute=minute),
        id="refresh_diario", replace_existing=True,
    )
    scheduler.start()
    atexit.register(scheduler.shutdown)
    print(f"[agendador] Atualizacao diaria as {hhmm} ({tz}).")


# ----------------------------------------------------------------------------
# Rotas
# ----------------------------------------------------------------------------
def _asset_version() -> str:
    """Versao dos assets (css/js) para o cache-busting do navegador. Vem do mtime
    dos arquivos: todo deploy (git pull) gera uma versao nova sozinho. Antes era um
    numero fixo no template, e quando alguem esquecia de subir o numero o cliente
    ficava com o dashboard.js antigo do cache contra um payload novo — secoes
    sumindo/quebrando so em alguns navegadores."""
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
    mt = 0
    for rel in ("js/dashboard.js", "css/style.css"):
        try:
            mt = max(mt, int(os.path.getmtime(os.path.join(base, rel))))
        except OSError:
            pass
    return str(mt or 1)


ASSET_V = _asset_version()


@app.route("/")
@requires_auth
def index():
    return render_template("dashboard.html", asset_v=ASSET_V)


@app.route("/logout")
def logout():
    """Sempre 401. O front faz um XHR aqui com credenciais invalidas para que o
    navegador troque o basic-auth em cache e volte a pedir login (entrar como outro
    cliente). Sem usuarios configurados (dev), apenas redireciona para a home."""
    if not USERS:
        return Response('<meta http-equiv="refresh" content="0;url=/">', 200,
                        {"Content-Type": "text/html"})
    return Response("Sessão encerrada.", 401,
                    {"WWW-Authenticate": 'Basic realm="Dashboard de Ads"'})


# ----------------------------------------------------------------------------
# LinkedIn Ads: autorizacao OAuth (uma vez por ano)
# ----------------------------------------------------------------------------
def _pagina_linkedin(titulo, texto, status=200):
    import html as _html
    corpo = (f'<!doctype html><meta charset="utf-8"><title>{_html.escape(titulo)}</title>'
             f'<body style="font-family:Arial,sans-serif;max-width:560px;margin:60px auto;color:#222">'
             f'<h2>{_html.escape(titulo)}</h2><p>{_html.escape(texto)}</p></body>')
    return Response(corpo, status, {"Content-Type": "text/html; charset=utf-8"})


@app.route("/linkedin/conectar")
@requires_auth
def linkedin_conectar():
    """So o login admin inicia a autorizacao: ela vale para o deploy inteiro."""
    if (g.client or {}).get("scope") is not None:
        return _pagina_linkedin("Acesso restrito", "Somente o login admin pode conectar o LinkedIn.", 403)
    from connectors import linkedin_auth
    try:
        return redirect(linkedin_auth.url_autorizacao())
    except RuntimeError as exc:
        return _pagina_linkedin("LinkedIn não configurado", str(exc), 500)


@app.route("/linkedin/callback")
def linkedin_callback():
    """Sem basic-auth de proposito: quem chega aqui e o redirecionamento do LinkedIn.
    A protecao e o `state` de uso unico gravado pelo /linkedin/conectar."""
    from connectors import linkedin_auth
    if request.args.get("error"):
        return _pagina_linkedin("Autorização não concluída",
                                request.args.get("error_description") or request.args.get("error"), 400)
    try:
        linkedin_auth.troca_codigo(request.args.get("code", ""), request.args.get("state", ""))
    except PermissionError:
        return _pagina_linkedin("Link expirado", "Abra /linkedin/conectar de novo para gerar outra autorização.", 401)
    except Exception as exc:  # noqa: BLE001
        print(f"[linkedin] callback falhou: {exc}")
        return _pagina_linkedin("Falha ao conectar", "O LinkedIn recusou a troca do código. Tente de novo.", 502)
    return _pagina_linkedin("LinkedIn conectado", "O dashboard já pode ler os anúncios. Pode fechar esta aba.")


@app.route("/api/data")
@requires_auth
def api_data():
    maybe_refresh()
    account = request.args.get("account", "todas")
    platform = request.args.get("platform", "todas")
    start = request.args.get("start") or None   # AAAA-MM-DD (mes/personalizado)
    end = request.args.get("end") or None
    try:
        days = int(request.args.get("days", 30))
    except ValueError:
        days = 30

    scope = g.client.get("scope") if hasattr(g, "client") else None
    subclientes = g.client.get("subclientes") if hasattr(g, "client") else None
    # Idioma da interface: do proprio login. "Ver como" um cliente adota o idioma dele,
    # porque a proposta do seletor e mostrar exatamente o que aquele cliente enxerga.
    idioma = (g.client.get("idioma") if hasattr(g, "client") else "pt") or "pt"

    # Quem pode "ver como" um cliente: o admin (escopo None, ve todos) e as agencias
    # de grupo (so os clientes do proprio grupo). ?client=KEY aplica o escopo daquele
    # cliente, exibindo exatamente o que ele ve; KEY fora da lista e ignorado.
    clientes_admin = None
    cliente_sel = ""
    visiveis = None
    if scope is None and USERS:
        visiveis = [k for k, v in USERS.items()
                    if v.get("scope") is not None and not v.get("subclientes")]
    elif subclientes:
        visiveis = list(subclientes)
    if visiveis is not None:
        clientes_admin = sorted(
            ({"key": k, "nome": USERS[k].get("nome", k)} for k in visiveis),
            key=lambda c: c["nome"].lower())
        cliente_sel = request.args.get("client", "")
        if cliente_sel in visiveis:
            scope = USERS[cliente_sel]["scope"]
            idioma = USERS[cliente_sel].get("idioma", idioma)
        else:
            cliente_sel = ""

    payload = analytics.build_payload(
        store, account=account, platform=platform, days=days, scope=scope,
        start=start, end=end)
    # Distingue "carregando" (cache ainda vazio logo apos reiniciar) de "sem dados".
    if payload.get("vazio") and store.updated_at is None:
        payload["carregando"] = True
    i18n.traduzir_payload(payload, idioma)
    payload["idioma"] = idioma
    payload["comentarios"] = commentary.generate(payload, idioma)
    payload["clientes_admin"] = clientes_admin
    payload["cliente_sel"] = cliente_sel
    payload["agencia_grupo"] = bool(subclientes)
    payload["meta_info"] = {
        "atualizado_em": store.updated_at.isoformat() if store.updated_at else None,
        "fonte": store.source_label,
        "cliente": g.client.get("nome", "") if hasattr(g, "client") else "",
    }
    return jsonify(payload)


@app.route("/api/refresh", methods=["POST"])
@requires_auth
def api_refresh():
    started = _spawn_seed()
    return jsonify({"ok": True, "msg": "Atualizacao iniciada (processo separado)."
                    if started else "Ja ha uma atualizacao em andamento."})


@app.route("/cron/refresh")
def cron_refresh():
    """Para tarefa agendada (cron): GET /cron/refresh?token=SEU_TOKEN.
    Dispara o seed em PROCESSO SEPARADO (nao satura o worker web)."""
    if not CRON_TOKEN or request.args.get("token") != CRON_TOKEN:
        return jsonify({"erro": "token invalido"}), 403
    started = _spawn_seed()
    return jsonify({"ok": True, "msg": "Seed iniciado." if started else "Seed ja em andamento."})


@app.route("/healthz")
def healthz():
    return jsonify({"ok": True, "atualizado_em":
                    store.updated_at.isoformat() if store.updated_at else None})


# Agendador inicia tambem sob gunicorn/Passenger (nao so no __main__).
try:
    _start_scheduler()
except Exception as exc:  # noqa: BLE001
    print(f"[agendador] nao iniciado: {exc}")


if __name__ == "__main__":
    srv = config.get("servidor", {})
    host = os.environ.get("HOST", srv.get("host", "127.0.0.1"))
    port = int(os.environ.get("PORT", srv.get("port", 5000)))
    app.run(host=host, port=port, debug=False)
