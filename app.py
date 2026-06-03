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
from data_sources import DataStore, load_clients, load_config


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


def _initial_load():
    """Primeira carga em background — nao bloqueia a subida do app (Passenger)."""
    try:
        info = store.refresh()
        print(f"[dados] Carregado: {info['source']} "
              f"(Meta={info['meta_rows']} linhas, Google={info['google_rows']} linhas)")
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
            "scope": {"meta_ids": c.get("_meta_ids", set()), "google_ids": c.get("_google_ids", set())},
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
    """Recarrega se o cache for de um dia anterior ou exceder a validade em horas."""
    if store.updated_at is None:
        return  # carga inicial roda em background; evita bloquear a requisicao
    now = datetime.now()
    stale_dia = store.updated_at.date() < now.date()
    stale_horas = (now - store.updated_at).total_seconds() > AUTO_REFRESH_HORAS * 3600
    if stale_dia or stale_horas:
        try:
            print("[dados] Auto-refresh:", store.refresh())
        except Exception as exc:  # noqa: BLE001
            print(f"[dados] auto-refresh falhou (mantendo cache): {exc}")


def _start_scheduler():
    sched = config.get("atualizacao", {})
    hhmm = sched.get("hora_diaria", "07:00")
    tz = sched.get("fuso", "America/Sao_Paulo")
    hour, minute = (int(x) for x in hhmm.split(":"))
    scheduler = BackgroundScheduler(timezone=tz)
    scheduler.add_job(
        lambda: print("[dados] Atualizacao diaria:", store.refresh()),
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


def _bg_refresh():
    """Refresh em background (nao bloqueia a requisicao -> sem timeout no cron)."""
    try:
        print("[refresh]", store.refresh())
    except Exception as exc:  # noqa: BLE001
        print(f"[refresh] falhou: {exc}")


@app.route("/api/refresh", methods=["POST"])
@requires_auth
def api_refresh():
    threading.Thread(target=_bg_refresh, daemon=True).start()
    return jsonify({"ok": True, "msg": "Atualizacao iniciada em background."})


@app.route("/cron/refresh")
def cron_refresh():
    """Para tarefa agendada (cron): GET /cron/refresh?token=SEU_TOKEN"""
    if not CRON_TOKEN or request.args.get("token") != CRON_TOKEN:
        return jsonify({"erro": "token invalido"}), 403
    threading.Thread(target=_bg_refresh, daemon=True).start()
    return jsonify({"ok": True, "msg": "Refresh iniciado em background."})


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
