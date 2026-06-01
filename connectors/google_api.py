"""
Conector da Google Ads API.

Devolve um DataFrame no schema GOOGLE_COLUMNS combinando:
  - keyword_view  -> palavras-chave de campanhas de Pesquisa (com metricas)
  - campaign      -> demais campanhas (PMax/Display/Video/Shopping), keyword vazia,
                     para que investimento/conversoes entrem nos totais.

Requer a biblioteca oficial `google-ads` (import tardio — so e exigida no modo api).
Credenciais via config["api"]["google_ads"]:
  developer_token, client_id, client_secret, refresh_token,
  login_customer_id, customer_ids (lista)

Nota: campanhas Performance Max nao expoem palavras-chave (limitacao da Google);
por isso aparecem apenas nos totais, nao na tabela de palavras-chave.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

# canal de veiculacao -> bucket do dashboard (ajustavel por campaign_objective_map)
CHANNEL_OBJECTIVE = {
    "SEARCH": "leads",
    "PERFORMANCE_MAX": "vendas",
    "SHOPPING": "vendas",
    "DISPLAY": "trafego",
    "VIDEO": "alcance",
    "DEMAND_GEN": "trafego",
}


def _client(cfg: dict):
    from google.ads.googleads.client import GoogleAdsClient
    return GoogleAdsClient.load_from_dict({
        "developer_token": cfg["developer_token"],
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "refresh_token": cfg["refresh_token"],
        "login_customer_id": str(cfg.get("login_customer_id", "")).replace("-", ""),
        "use_proto_plus": True,
    })


def _objective(channel_name, campaign_name, override) -> str:
    if campaign_name in override:
        return override[campaign_name]
    return CHANNEL_OBJECTIVE.get(channel_name, "outros")


def _date_range(days):
    until = datetime.today().date()
    since = until - timedelta(days=days - 1)
    return since.isoformat(), until.isoformat()


def fetch(g_cfg: dict, days: int = 60) -> pd.DataFrame:
    if not g_cfg.get("developer_token") or not g_cfg.get("refresh_token"):
        return pd.DataFrame()

    from google.ads.googleads.errors import GoogleAdsException

    client = _client(g_cfg)
    service = client.get_service("GoogleAdsService")
    since, until = _date_range(days)
    override = g_cfg.get("campaign_objective_map") or {}
    rows = []

    kw_query = f"""
        SELECT segments.date, customer.descriptive_name, campaign.name,
               campaign.advertising_channel_type, ad_group.name,
               ad_group_criterion.keyword.text, ad_group_criterion.keyword.match_type,
               metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.conversions, metrics.conversions_value
        FROM keyword_view
        WHERE segments.date BETWEEN '{since}' AND '{until}'
          AND campaign.advertising_channel_type = 'SEARCH'
    """
    camp_query = f"""
        SELECT segments.date, customer.descriptive_name, campaign.name,
               campaign.advertising_channel_type,
               metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.conversions, metrics.conversions_value
        FROM campaign
        WHERE segments.date BETWEEN '{since}' AND '{until}'
          AND campaign.advertising_channel_type != 'SEARCH'
    """

    match_type_pt = {0: "", 1: "", 2: "Exata", 3: "Frase", 4: "Ampla"}

    for cid in g_cfg.get("customer_ids", []):
        cid = str(cid).replace("-", "")
        if not cid:
            continue
        try:
            # Palavras-chave (Pesquisa)
            for batch in service.search_stream(customer_id=cid, query=kw_query):
                for row in batch.results:
                    ch = row.campaign.advertising_channel_type.name
                    rows.append({
                        "date": row.segments.date,
                        "account": row.customer.descriptive_name,
                        "account_id": cid,
                        "objective": _objective(ch, row.campaign.name, override),
                        "campaign": row.campaign.name,
                        "campaign_type": ch,
                        "ad_group": row.ad_group.name,
                        "keyword": row.ad_group_criterion.keyword.text,
                        "match_type": match_type_pt.get(
                            int(row.ad_group_criterion.keyword.match_type), ""),
                        "impressions": float(row.metrics.impressions),
                        "clicks": float(row.metrics.clicks),
                        "cost": row.metrics.cost_micros / 1_000_000.0,
                        "conversions": float(row.metrics.conversions),
                        "conversion_value": float(row.metrics.conversions_value),
                    })
            # Demais campanhas (totais)
            for batch in service.search_stream(customer_id=cid, query=camp_query):
                for row in batch.results:
                    ch = row.campaign.advertising_channel_type.name
                    rows.append({
                        "date": row.segments.date,
                        "account": row.customer.descriptive_name,
                        "account_id": cid,
                        "objective": _objective(ch, row.campaign.name, override),
                        "campaign": row.campaign.name,
                        "campaign_type": ch,
                        "ad_group": "",
                        "keyword": "",
                        "match_type": "",
                        "impressions": float(row.metrics.impressions),
                        "clicks": float(row.metrics.clicks),
                        "cost": row.metrics.cost_micros / 1_000_000.0,
                        "conversions": float(row.metrics.conversions),
                        "conversion_value": float(row.metrics.conversions_value),
                    })
        except GoogleAdsException as exc:
            print(f"[google] erro na conta {cid}: {exc}")

    return pd.DataFrame(rows)
