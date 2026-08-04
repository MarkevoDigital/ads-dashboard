"""
Conector da Instagram Graph API: seguidores (total, novos por dia).

Usa o MESMO token do Meta Ads (usuario de sistema). Requer, alem do que o Ads ja
usa, os escopos `instagram_basic` + `instagram_manage_insights` + `pages_show_list`
E as Paginas atribuidas ao usuario de sistema na Business Manager (sem isso,
/me/accounts volta vazio e nao ha como chegar na conta de IG).

Caminho: Pagina do Facebook -> instagram_business_account -> insights.
  - followers_count: TOTAL atual (a API nao devolve historico do total).
  - follower_count (insight, period=day): NOVOS seguidores por dia (~30 dias).

Devolve um DataFrame no formato longo: uma linha por (conta, dia).
"""
from __future__ import annotations

from datetime import timedelta

import pandas as pd
import requests

from tz_br import today_br
from connectors.meta_api import GRAPH, _ensure_dns, _paged_get, _safe

COLUMNS = ["date", "ig_id", "username", "account", "new_followers", "followers_total"]

# A Meta so entrega o insight diario de seguidores para contas com >= 100 seguidores.
MIN_FOLLOWERS_INSIGHT = 100
# ...e so dos ULTIMOS ~30 DIAS. Pedir uma janela maior faz a chamada falhar inteira
# (voltando "novos = 0" para todo mundo), entao limitamos aqui. O dashboard busca
# 60 dias de Ads por padrao — a serie de seguidores fica com os 30 disponiveis.
INSIGHT_MAX_DAYS = 30


def accounts(meta_cfg: dict) -> list[dict]:
    """Contas de Instagram visiveis pelo token (via Paginas do Facebook).

    Util tambem fora do fetch: e o que permite mapear cada conta de IG ao cliente.
    """
    token = meta_cfg.get("access_token")
    if not token:
        return []
    _ensure_dns()
    version = meta_cfg.get("api_version", "v21.0")
    url = f"{GRAPH}/{version}/me/accounts"
    params = {
        "fields": "name,instagram_business_account{id,username,followers_count,media_count}",
        "limit": 200, "access_token": token,
    }
    out = []
    try:
        for p in _paged_get(url, params):
            ig = p.get("instagram_business_account") or {}
            if not ig.get("id"):
                continue
            out.append({
                "ig_id": str(ig["id"]),
                "username": str(ig.get("username") or ""),
                "page": str(p.get("name") or ""),
                "followers": int(ig.get("followers_count") or 0),
                "media": int(ig.get("media_count") or 0),
            })
    except Exception as exc:  # noqa: BLE001
        print(f"[instagram] descoberta de contas falhou: {_safe(exc)}")
    return out


def _daily_new(ig_id: str, token: str, version: str, since, until) -> dict:
    """Novos seguidores por dia. Retorna {'YYYY-MM-DD': valor}.

    A Meta datat o ponto pelo `end_time` = FIM do periodo; para period=day o valor
    corresponde ao dia ANTERIOR ao end_time (end_time vem a meia-noite PST). Por isso
    subtraimos 1 dia para reportar a data que o numero realmente representa.
    """
    out: dict = {}
    try:
        r = requests.get(
            f"{GRAPH}/{version}/{ig_id}/insights",
            params={"metric": "follower_count", "period": "day",
                    "since": str(since), "until": str(until + timedelta(days=1)),
                    "access_token": token},
            timeout=60,
        )
        j = r.json()
        if "error" in j:
            raise RuntimeError(j["error"].get("message"))
        for m in j.get("data", []):
            for v in m.get("values", []):
                et = str(v.get("end_time", ""))[:10]
                if not et:
                    continue
                try:
                    ref = (pd.Timestamp(et) - pd.Timedelta(days=1)).date()
                except Exception:  # noqa: BLE001
                    continue
                out[ref.isoformat()] = float(v.get("value") or 0)
    except Exception as exc:  # noqa: BLE001
        print(f"[instagram] insights {ig_id}: {_safe(exc)}")
    return out


def fetch(meta_cfg: dict, days: int = 60) -> pd.DataFrame:
    """Seguidores por conta de IG e por dia.

    A janela termina em ONTEM: o dia corrente ainda nao fechou na Meta e volta 0,
    o que sujaria o "novos seguidores de hoje". Mesma convencao do resto do dashboard.
    """
    token = meta_cfg.get("access_token")
    if not token:
        return pd.DataFrame(columns=COLUMNS)
    version = meta_cfg.get("api_version", "v21.0")
    until = today_br() - timedelta(days=1)
    janela = max(1, min(int(days), INSIGHT_MAX_DAYS))
    since = until - timedelta(days=janela - 1)

    rows: list[dict] = []
    accs = accounts(meta_cfg)
    if accs:
        print(f"[instagram] {len(accs)} conta(s) de Instagram acessiveis.")
    for acc in accs:
        daily = ({} if acc["followers"] < MIN_FOLLOWERS_INSIGHT
                 else _daily_new(acc["ig_id"], token, version, since, until))
        d = since
        while d <= until:
            key = d.isoformat()
            rows.append({
                "date": key,
                "ig_id": acc["ig_id"],
                "username": acc["username"],
                "account": acc["page"],
                "new_followers": float(daily.get(key, 0.0)),
                # snapshot do total ATUAL, repetido em todas as linhas da conta (a API
                # nao da historico do total; o valor "de hoje" e o unico disponivel).
                "followers_total": float(acc["followers"]),
            })
            d += timedelta(days=1)
    return pd.DataFrame(rows, columns=COLUMNS)
