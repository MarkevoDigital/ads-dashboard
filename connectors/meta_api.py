"""
Conector da Meta Marketing API (Facebook/Instagram Ads).

Busca insights por ANUNCIO por DIA e os thumbnails (print) dos criativos,
devolvendo um DataFrame no schema esperado pelo dashboard (META_COLUMNS).

Requer apenas `requests`. Credenciais via config["api"]["meta"]:
  access_token, ad_account_ids (ex: ["act_123..."]), api_version (ex: "v21.0")

Observacoes:
  - 'profile_visits' (visitas ao Instagram) nem sempre vem na API; e best-effort.
  - O mapeamento objetivo Meta -> nosso bucket pode ser ajustado em objective_map.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import requests

GRAPH = "https://graph.facebook.com"

# Objetivo da campanha (Meta) -> bucket do dashboard
DEFAULT_OBJECTIVE_MAP = {
    "OUTCOME_SALES": "vendas",
    "CONVERSIONS": "vendas",
    "PRODUCT_CATALOG_SALES": "vendas",
    "OUTCOME_LEADS": "leads",
    "LEAD_GENERATION": "leads",
    "MESSAGES": "mensagens",
    "OUTCOME_TRAFFIC": "trafego",
    "LINK_CLICKS": "trafego",
    "OUTCOME_AWARENESS": "alcance",
    "BRAND_AWARENESS": "alcance",
    "REACH": "alcance",
    "OUTCOME_ENGAGEMENT": "mensagens",
    "POST_ENGAGEMENT": "visitas_instagram",
    "PROFILE_VISITS": "visitas_instagram",
}

# action_type candidatos por metrica (ordem = prioridade)
ACTION_KEYS = {
    "purchases": ["omni_purchase", "offsite_conversion.fb_pixel_purchase", "purchase"],
    "leads": ["onsite_conversion.lead_grouped", "offsite_conversion.fb_pixel_lead", "lead"],
    "messaging_conversations": [
        "onsite_conversion.messaging_conversation_started_7d",
        "messaging_conversation_started_7d",
    ],
    "profile_visits": [
        "onsite_conversion.ig_profile_visit", "ig_profile_visit", "profile_visit",
    ],
    "site_visits": ["landing_page_view", "omni_landing_page_view"],
    "video_views": ["video_view"],
    "engagement": ["post_engagement"],
}

# Centroides aproximados dos estados (Meta faz breakdown por "region" = estado).
BR_STATE_COORDS = {
    "Acre": (-9.02, -70.81), "Alagoas": (-9.57, -36.78), "Amapa": (1.41, -51.77),
    "Amazonas": (-3.42, -65.86), "Bahia": (-12.58, -41.70), "Ceara": (-5.20, -39.53),
    "Distrito Federal": (-15.78, -47.93), "Espirito Santo": (-19.19, -40.31),
    "Goias": (-15.93, -49.84), "Maranhao": (-5.42, -45.44), "Mato Grosso": (-12.64, -55.42),
    "Mato Grosso do Sul": (-20.51, -54.54), "Minas Gerais": (-18.10, -44.38),
    "Para": (-3.79, -52.48), "Paraiba": (-7.28, -36.72), "Parana": (-24.89, -51.55),
    "Pernambuco": (-8.38, -37.86), "Piaui": (-6.60, -42.28),
    "Rio de Janeiro": (-22.25, -42.66), "Rio Grande do Norte": (-5.81, -36.59),
    "Rio Grande do Sul": (-30.17, -53.50), "Rondonia": (-10.83, -63.34),
    "Roraima": (1.99, -61.33), "Santa Catarina": (-27.45, -50.95),
    "Sao Paulo": (-22.19, -48.79), "Sergipe": (-10.57, -37.45), "Tocantins": (-9.46, -48.26),
}


def _first_action(actions, keys) -> float:
    """Retorna o valor do primeiro action_type encontrado na lista de candidatos."""
    if not actions:
        return 0.0
    by_type = {a.get("action_type"): a.get("value", 0) for a in actions}
    for k in keys:
        if k in by_type:
            try:
                return float(by_type[k])
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def _paged_get(url, params):
    """Itera por todas as paginas de uma resposta paginada da Graph API."""
    out = []
    while url:
        resp = requests.get(url, params=params, timeout=60)
        if resp.status_code != 200:
            raise RuntimeError(f"Meta API {resp.status_code}: {resp.text[:300]}")
        body = resp.json()
        out.extend(body.get("data", []))
        url = body.get("paging", {}).get("next")
        params = None  # 'next' ja contem a querystring
    return out


def _account_ids(meta_cfg: dict, token: str, version: str) -> list[str]:
    """IDs das contas configuradas; se vazio, descobre todas via /me/adaccounts."""
    ids = [a for a in (meta_cfg.get("ad_account_ids") or []) if a]
    if ids:
        return [a if a.startswith("act_") else f"act_{a}" for a in ids]
    url = f"{GRAPH}/{version}/me/adaccounts"
    params = {"fields": "account_id", "limit": 500, "access_token": token}
    out = []
    try:
        for a in _paged_get(url, params):
            aid = a.get("account_id")
            if aid:
                out.append(f"act_{aid}")
    except Exception as exc:  # noqa: BLE001
        print(f"[meta] descoberta de contas falhou: {exc}")
    print(f"[meta] {len(out)} contas descobertas automaticamente.")
    return out


def _thumbnails(account_id, token, version) -> dict:
    """Mapa ad_id -> URL do thumbnail do criativo (o 'print' do anuncio)."""
    url = f"{GRAPH}/{version}/{account_id}/ads"
    params = {
        "fields": "id,creative{thumbnail_url,image_url}",
        "limit": 500,
        "access_token": token,
    }
    mapa = {}
    try:
        for ad in _paged_get(url, params):
            cre = ad.get("creative", {}) or {}
            mapa[ad["id"]] = cre.get("thumbnail_url") or cre.get("image_url") or ""
    except Exception as exc:  # noqa: BLE001
        print(f"[meta] thumbnails indisponiveis: {exc}")
    return mapa


def _resolve_objective(meta_obj, msg, visits, obj_map) -> str:
    bucket = obj_map.get(meta_obj, "outros")
    if bucket in ("outros", "mensagens", "visitas_instagram"):
        if msg > 0:
            return "mensagens"
        if visits > 0:
            return "visitas_instagram"
    return bucket


def fetch(meta_cfg: dict, days: int = 60) -> pd.DataFrame:
    token = meta_cfg.get("access_token")
    if not token:
        return pd.DataFrame()

    version = meta_cfg.get("api_version", "v21.0")
    obj_map = {**DEFAULT_OBJECTIVE_MAP, **(meta_cfg.get("objective_map") or {})}
    until = datetime.today().date()
    since = until - timedelta(days=days - 1)

    rows = []
    for account_id in _account_ids(meta_cfg, token, version):
        thumbs = _thumbnails(account_id, token, version)

        url = f"{GRAPH}/{version}/{account_id}/insights"
        params = {
            "level": "ad",
            "time_increment": 1,
            "time_range": f'{{"since":"{since}","until":"{until}"}}',
            "fields": ",".join([
                "ad_id", "ad_name", "adset_name", "campaign_name", "objective",
                "account_name", "impressions", "reach", "frequency", "clicks",
                "inline_link_clicks", "spend", "actions", "action_values",
            ]),
            "limit": 500,
            "access_token": token,
        }
        for r in _paged_get(url, params):
            actions = r.get("actions", [])
            action_values = r.get("action_values", [])
            msg = _first_action(actions, ACTION_KEYS["messaging_conversations"])
            visits = _first_action(actions, ACTION_KEYS["profile_visits"])
            purchases = _first_action(actions, ACTION_KEYS["purchases"])
            leads = _first_action(actions, ACTION_KEYS["leads"])
            revenue = _first_action(action_values, ACTION_KEYS["purchases"])
            site_visits = _first_action(actions, ACTION_KEYS["site_visits"])
            video_views = _first_action(actions, ACTION_KEYS["video_views"])
            engagement = _first_action(actions, ACTION_KEYS["engagement"])
            objective = _resolve_objective(r.get("objective", ""), msg, visits, obj_map)
            ad_id = r.get("ad_id", "")
            rows.append({
                "date": r.get("date_start"),
                "account": r.get("account_name") or account_id,
                "account_id": account_id.replace("act_", ""),
                "objective": objective,
                "campaign": r.get("campaign_name", ""),
                "adset": r.get("adset_name", ""),
                "ad_name": r.get("ad_name", ""),
                "ad_thumbnail_url": thumbs.get(ad_id, ""),
                "ad_permalink": "",
                "impressions": float(r.get("impressions", 0) or 0),
                "reach": float(r.get("reach", 0) or 0),
                "frequency": float(r.get("frequency", 0) or 0),
                "clicks": float(r.get("clicks", 0) or 0),
                "link_clicks": float(r.get("inline_link_clicks", 0) or 0),
                "spend": float(r.get("spend", 0) or 0),
                "messaging_conversations": msg,
                "profile_visits": visits,
                "leads": leads,
                "purchases": purchases,
                "purchase_value": revenue,
                "site_visits": site_visits,
                "video_views": video_views,
                "engagement": engagement,
            })

    return pd.DataFrame(rows)


def fetch_geo(meta_cfg: dict, days: int = 60) -> pd.DataFrame:
    """Cliques por estado (breakdown=region) com coordenadas, p/ o mapa de calor."""
    token = meta_cfg.get("access_token")
    if not token:
        return pd.DataFrame()
    version = meta_cfg.get("api_version", "v21.0")
    until = datetime.today().date()
    since = until - timedelta(days=days - 1)
    rows = []
    for account_id in _account_ids(meta_cfg, token, version):
        url = f"{GRAPH}/{version}/{account_id}/insights"
        params = {
            "level": "account", "breakdowns": "region", "time_increment": 1,
            "time_range": f'{{"since":"{since}","until":"{until}"}}',
            "fields": "clicks", "limit": 500, "access_token": token,
        }
        try:
            for r in _paged_get(url, params):
                region = r.get("region", "")
                coords = BR_STATE_COORDS.get(region)
                if not coords:
                    continue
                rows.append({
                    "date": r.get("date_start"), "account_id": account_id.replace("act_", ""),
                    "platform": "meta", "city": region,
                    "lat": coords[0], "lng": coords[1], "clicks": float(r.get("clicks", 0) or 0),
                })
        except Exception as exc:  # noqa: BLE001
            print(f"[meta-geo] {account_id}: {exc}")
    return pd.DataFrame(rows)
