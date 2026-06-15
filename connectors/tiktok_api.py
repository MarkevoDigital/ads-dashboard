"""
Conector da TikTok Marketing API (TikTok Ads).

Busca relatorios (report/integrated/get) por ANUNCIO por DIA e devolve um DataFrame
no MESMO schema do Meta (META_COLUMNS) — assim o TikTok passa pelos mesmos agregadores
de metrics/analytics sem tratamento especial. So aparece para clientes que tiverem
`tiktok_advertiser_ids` no clients.json (escopo _tiktok_ids); para os demais, o store
fica vazio e o TikTok nao aparece em lugar nenhum (data-driven).

Requer apenas `requests`. Credenciais via config["api"]["tiktok"]:
  access_token, app_id, secret, advertiser_ids (ex: ["7891234567890"]), api_version.

A conversao do TikTok ("conversion") e roteada para a coluna meta-equivalente conforme
o objetivo da campanha (vendas->purchases, leads->leads, etc.), igual o Meta faz, para
o funil/blocos por objetivo/melhores anuncios funcionarem de imediato.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta

import pandas as pd
import requests

BASE = "https://business-api.tiktok.com/open_api"

# Objetivo (objective_type da campanha no TikTok) -> bucket do dashboard.
DEFAULT_OBJECTIVE_MAP = {
    "REACH": "alcance",
    "TRAFFIC": "trafego",
    "VIDEO_VIEWS": "video",
    "VIDEO_VIEW": "video",
    "ENGAGEMENT": "alcance",
    "LEAD_GENERATION": "leads",
    "WEB_CONVERSIONS": "vendas",
    "CONVERSIONS": "vendas",
    "PRODUCT_SALES": "vendas",
    "CATALOG_SALES": "vendas",
    "APP_PROMOTION": "vendas",
    "RF_REACH": "alcance",
    "RF_ENGAGEMENT": "alcance",
}

# Bucket do objetivo -> coluna meta onde cai a "conversion" do TikTok (espelha o Meta).
_BUCKET_TO_META_COL = {
    "vendas": "purchases",
    "leads": "leads",
    "mensagens": "messaging_conversations",
    "visitas_instagram": "profile_visits",
    "trafego": "link_clicks",
    "video": "video_views",
    "alcance": "reach",
}

# Metricas pedidas no report/integrated/get (numericas + descritivas).
_METRICS = [
    "spend", "impressions", "reach", "frequency", "clicks", "conversion",
    "total_purchase_value", "video_play_actions", "likes", "comments", "shares",
    "campaign_name", "adgroup_name", "ad_name", "objective_type",
]


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _get(path: str, params: dict, token: str, version: str) -> dict:
    """GET na Graph do TikTok. Erro != code 0 vira RuntimeError. Com retry para
    instabilidades transitorias (code 50002/'rate'/'timeout')."""
    url = f"{BASE}/{version}/{path}/"
    headers = {"Access-Token": token}
    last = None
    for attempt in range(3):
        resp = requests.get(url, params=params, headers=headers, timeout=60)
        try:
            body = resp.json()
        except ValueError:
            raise RuntimeError(f"TikTok API HTTP {resp.status_code}: {resp.text[:200]}")
        code = body.get("code")
        if code == 0:
            return body.get("data", {}) or {}
        msg = f"TikTok API code {code}: {body.get('message', '')[:200]}"
        last = RuntimeError(msg)
        transient = code in (50002, 50000) or "rate" in msg.lower() or "timeout" in msg.lower()
        if transient and attempt < 2:
            time.sleep(1.5 * (attempt + 1))
            continue
        raise last
    raise last  # noqa: RET503


def _advertiser_ids(cfg: dict, token: str, version: str) -> list[str]:
    """IDs configurados; se vazio, descobre os advertisers autorizados ao app."""
    ids = [str(a).strip() for a in (cfg.get("advertiser_ids") or []) if str(a).strip()]
    if ids:
        return ids
    app_id, secret = cfg.get("app_id"), cfg.get("secret")
    if not (app_id and secret):
        return []
    try:  # /oauth2/advertiser/get/ usa app_id+secret (nao Access-Token header)
        data = _get("oauth2/advertiser/get",
                    {"app_id": app_id, "secret": secret, "access_token": token},
                    token, version)
        out = [str(a.get("advertiser_id")) for a in data.get("list", []) if a.get("advertiser_id")]
        print(f"[tiktok] {len(out)} advertisers autorizados descobertos.")
        return out
    except Exception as exc:  # noqa: BLE001
        print(f"[tiktok] descoberta de advertisers falhou: {exc}")
        return []


def _advertiser_names(adv_ids: list[str], token: str, version: str) -> dict:
    """Mapa advertiser_id -> nome (advertiser/info/). Best-effort."""
    names = {}
    if not adv_ids:
        return names
    try:
        data = _get("advertiser/info",
                    {"advertiser_ids": json.dumps(list(adv_ids)),
                     "fields": json.dumps(["advertiser_id", "name"])},
                    token, version)
        for a in data.get("list", []):
            if a.get("advertiser_id"):
                names[str(a["advertiser_id"])] = a.get("name") or str(a["advertiser_id"])
    except Exception as exc:  # noqa: BLE001
        print(f"[tiktok] nomes de advertisers indisponiveis: {exc}")
    return names


def _report_rows(advertiser_id: str, token: str, version: str, since, until) -> list[dict]:
    """Itera todas as paginas de report/integrated/get (nivel anuncio, por dia)."""
    out, page = [], 1
    while True:
        params = {
            "advertiser_id": advertiser_id,
            "report_type": "BASIC",
            "data_level": "AUCTION_AD",
            "dimensions": json.dumps(["ad_id", "stat_time_day"]),
            "metrics": json.dumps(_METRICS),
            "start_date": str(since), "end_date": str(until),
            "page": page, "page_size": 1000,
        }
        data = _get("report/integrated/get", params, token, version)
        out.extend(data.get("list", []))
        info = data.get("page_info", {}) or {}
        total_page = info.get("total_page") or 1
        if page >= total_page:
            break
        page += 1
    return out


def _fetch_advertiser_rows(advertiser_id, adv_name, token, version, since, until, obj_map) -> list[dict]:
    rows = []
    for item in _report_rows(advertiser_id, token, version, since, until):
        dim = item.get("dimensions", {}) or {}
        met = item.get("metrics", {}) or {}
        day = str(dim.get("stat_time_day", ""))[:10]
        if not day:
            continue
        objective_type = str(met.get("objective_type", "")).upper()
        bucket = obj_map.get(objective_type, "outros")
        conversion = _num(met.get("conversion"))
        clicks = _num(met.get("clicks"))
        row = {
            "date": day,
            "account": adv_name or str(advertiser_id),
            "account_id": str(advertiser_id),
            "objective": bucket,
            "campaign": met.get("campaign_name", "") or "",
            "adset": met.get("adgroup_name", "") or "",
            "ad_name": met.get("ad_name", "") or "",
            "ad_thumbnail_url": "", "ad_permalink": "",
            "daily_budget": 0.0,
            "impressions": _num(met.get("impressions")),
            "reach": _num(met.get("reach")),
            "frequency": _num(met.get("frequency")),
            "clicks": clicks,
            "link_clicks": clicks,  # TikTok 'clicks' = cliques no anuncio/destino
            "spend": _num(met.get("spend")),
            "messaging_conversations": 0.0,
            "profile_visits": 0.0,
            "leads": 0.0,
            "purchases": 0.0,
            "purchase_value": _num(met.get("total_purchase_value")),
            "site_visits": 0.0,
            "video_views": _num(met.get("video_play_actions")),
            "engagement": _num(met.get("likes")) + _num(met.get("comments")) + _num(met.get("shares")),
        }
        # Roteia a "conversion" do TikTok para a coluna meta do objetivo (espelha o Meta).
        col = _BUCKET_TO_META_COL.get(bucket)
        if col and col not in ("reach", "link_clicks", "video_views"):
            row[col] = row.get(col, 0.0) + conversion
        elif bucket == "outros":
            row["purchases"] = row.get("purchases", 0.0) + conversion
        rows.append(row)
    return rows


def fetch(tiktok_cfg: dict, days: int = 60) -> pd.DataFrame:
    """DataFrame no schema do Meta (META_COLUMNS) com os dados do TikTok Ads."""
    token = tiktok_cfg.get("access_token")
    if not token:
        return pd.DataFrame()
    version = tiktok_cfg.get("api_version", "v1.3")
    obj_map = {**DEFAULT_OBJECTIVE_MAP, **(tiktok_cfg.get("objective_map") or {})}
    until = datetime.today().date()
    since = until - timedelta(days=days - 1)

    adv_ids = _advertiser_ids(tiktok_cfg, token, version)
    names = _advertiser_names(adv_ids, token, version)
    rows = []
    for adv in adv_ids:
        try:
            rows.extend(_fetch_advertiser_rows(adv, names.get(adv, adv), token, version,
                                               since, until, obj_map))
        except Exception as exc:  # noqa: BLE001
            print(f"[tiktok] advertiser {adv} falhou (ignorado): {exc}")
    return pd.DataFrame(rows)


def fetch_geo(tiktok_cfg: dict, days: int = 60) -> pd.DataFrame:
    """Geo (cliques por regiao) do TikTok para o mapa de calor.

    DESATIVADO na v1: o TikTok reporta geo por `province_id` (codigos numericos
    proprios), que exigem uma tabela de-para province_id -> estado/coordenadas do
    Brasil. Sera implementado quando tivermos o token aprovado e pudermos consultar
    /tools/region/ para montar o de-para. Por ora retorna vazio (o mapa combinado
    Meta+Google segue funcionando). Schema compativel com GEO_COLUMNS.
    """
    return pd.DataFrame(columns=["date", "account_id", "platform", "level", "city",
                                 "lat", "lng", "clicks"])
