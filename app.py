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

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from flask import Flask, Response, g, jsonify, render_template, request

import analytics
import commentary
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
    """Primeira carga em background — nao bloqueia a subida do app (Passenger).

    1) Sobe o store do cache em disco (instantaneo) -> worker reciclado fica PRONTO
       na hora, sem o "carregando" de ~15min.
    2) So busca da API se nao havia cache ou se o cache nao e de hoje (evita refetch
       pesado a cada reciclagem de worker; a atualizacao diaria roda no cron das 8h)."""
    try:
        # Aceita qualquer cache existente (o refresh diario roda no cron, em processo
        # separado). Subir do cache deixa o worker PRONTO na hora, sem refetch pesado.
        loaded = store.load_cache(max_age_h=24 * 365)
        if loaded:
            _cache_mtime[0] = os.path.getmtime(STORE_CACHE)
            print(f"[dados] Cache em disco: Meta={len(store.meta)} Google={len(store.google)} "
                  f"linhas (de {store.updated_at}). Worker pronto.")
        else:
            print("[dados] Sem cache — disparando seed externo.")
            _spawn_seed()
    except Exception as exc:  # noqa: BLE001
        print(f"[dados] carga inicial falhou: {exc}")


threading.Thread(target=_initial_load, daemon=True).start()

app = Flask(__name__)
# Recarrega templates do disco a cada requisicao (evita precisar reiniciar o app
# so para servir HTML novo apos um git pull). Custo desprezivel para este trafego.
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.jinja_env.auto_reload = True

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
        users["admin"] = {"senha": admin_pw, "scope": None, "nome": "Agência (todos os clientes)"}
    for c in clients.get("clientes", []):
        users[c["key"]] = {
            "senha": c.get("senha", ""),
            "scope": {"meta_ids": c.get("_meta_ids", set()),
                      "google_ids": c.get("_google_ids", set()),
                      "tiktok_ids": c.get("_tiktok_ids", set())},
            "nome": c.get("nome", c["key"]),
        }
    return users


USERS = _build_users()
print(f"[auth] {len(USERS)} login(s) configurado(s): {', '.join(USERS) or '(nenhum — acesso aberto)'}")


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
    if store.updated_at and store.updated_at.date() < datetime.now().date():
        _spawn_seed()


def _start_scheduler():
    sched = config.get("atualizacao", {})
    hhmm = sched.get("hora_diaria", "07:00")
    tz = sched.get("fuso", "America/Sao_Paulo")
    hour, minute = (int(x) for x in hhmm.split(":"))
    scheduler = BackgroundScheduler(timezone=tz)
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
@app.route("/")
@requires_auth
def index():
    return render_template("dashboard.html")


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

    # Admin (escopo None) pode "ver como" um cliente: ?client=KEY aplica o escopo
    # daquele cliente, exibindo exatamente o que ele ve. Tambem devolve a lista de
    # clientes para o seletor no front.
    clientes_admin = None
    cliente_sel = ""
    if scope is None and USERS:
        clientes_admin = sorted(
            ({"key": k, "nome": v.get("nome", k)}
             for k, v in USERS.items() if v.get("scope") is not None),
            key=lambda c: c["nome"].lower())
        cliente_sel = request.args.get("client", "")
        chosen = USERS.get(cliente_sel)
        if chosen and chosen.get("scope") is not None:
            scope = chosen["scope"]
        else:
            cliente_sel = ""

    payload = analytics.build_payload(
        store, account=account, platform=platform, days=days, scope=scope,
        start=start, end=end)
    # Distingue "carregando" (cache ainda vazio logo apos reiniciar) de "sem dados".
    if payload.get("vazio") and store.updated_at is None:
        payload["carregando"] = True
    payload["comentarios"] = commentary.generate(payload)
    payload["clientes_admin"] = clientes_admin
    payload["cliente_sel"] = cliente_sel
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
