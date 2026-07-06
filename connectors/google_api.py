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

import unicodedata
from datetime import datetime, timedelta

import pandas as pd

from connectors.meta_api import BR_STATE_COORDS, _CITY_BY_NORM


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in s if not unicodedata.combining(c)).strip().lower()


def _state_key(name: str) -> str:
    """Normaliza nome de estado do Google ('State of Sao Paulo') p/ casar no lookup."""
    k = _norm(name)
    for pref in ("state of ", "estado de ", "estado do ", "estado da "):
        if k.startswith(pref):
            k = k[len(pref):]
    return k.strip()


# lookup normalizado: nome do estado (sem acento, minusculo) -> (nome, lat, lng)
_STATE_BY_NORM = {_norm(k): (k, v[0], v[1]) for k, v in BR_STATE_COORDS.items()}

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


def _digits(value) -> str:
    return "".join(ch for ch in str(value) if ch.isdigit())


def _customer_ids(g_cfg: dict, client) -> list[str]:
    """IDs das contas a consultar.

    Usa os customer_ids configurados (se houver e nao forem placeholder); caso
    contrario, DESCOBRE automaticamente todas as contas-cliente sob o MCC
    (login_customer_id) via customer_client — espelha a descoberta do Meta, para
    que clientes novos entrem sozinhos sem editar a lista a cada vez.
    """
    ids = []
    for c in (g_cfg.get("customer_ids") or []):
        d = _digits(c)
        if d and set(d) != {"0"}:  # ignora vazio e placeholder (so zeros)
            ids.append(d)
    if ids:
        return ids
    login = _digits(g_cfg.get("login_customer_id", ""))
    if not login:
        return []
    service = client.get_service("GoogleAdsService")
    query = """
        SELECT customer_client.id, customer_client.manager,
               customer_client.status, customer_client.level
        FROM customer_client
        WHERE customer_client.status = 'ENABLED'
    """
    # Retry com backoff: sob limite de processos/grpc (nproc/LVE) a descoberta pode
    # falhar de forma transitoria. Sem retry, um blip zera TODAS as contas Google do
    # seed. Tentamos ate 3x antes de desistir (e ai o guard em _load_raw preserva o
    # cache anterior em vez de persistir Google vazio).
    import time as _t
    last = None
    for _try in range(3):
        try:
            out, seen = [], set()
            for batch in service.search_stream(customer_id=login, query=query):
                for row in batch.results:
                    if row.customer_client.manager:  # pula MCCs (so contas folha)
                        continue
                    cid = str(row.customer_client.id)
                    if cid not in seen:
                        seen.add(cid)
                        out.append(cid)
            print(f"[google] {len(out)} contas descobertas no MCC {login}.")
            return out
        except Exception as exc:  # noqa: BLE001
            last = exc
            _t.sleep(1.5 * (_try + 1))
    print(f"[google] descoberta de contas falhou apos retries: {last}")
    return []


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
               metrics.conversions, metrics.conversions_value,
               metrics.video_trueview_views
        FROM campaign
        WHERE segments.date BETWEEN '{since}' AND '{until}'
          AND campaign.advertising_channel_type != 'SEARCH'
    """
    # Fallback SEM o campo de video: algumas versoes/config da API do Google
    # rejeitam esse campo ("Unrecognized field") e derrubariam TODAS as campanhas
    # nao-SEARCH. Se a query acima falhar por causa dele, usamos esta (video_views=0).
    camp_query_novv = f"""
        SELECT segments.date, customer.descriptive_name, campaign.name,
               campaign.advertising_channel_type,
               metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.conversions, metrics.conversions_value
        FROM campaign
        WHERE segments.date BETWEEN '{since}' AND '{until}'
          AND campaign.advertising_channel_type != 'SEARCH'
    """
    # orcamento diario por campanha (query separada -> nao quebra o fetch principal)
    budget_query = "SELECT campaign.name, campaign_budget.amount_micros FROM campaign"

    match_type_pt = {0: "", 1: "", 2: "Exata", 3: "Frase", 4: "Ampla"}

    for cid in _customer_ids(g_cfg, client):
        budget_map = {}
        try:
            for batch in service.search_stream(customer_id=cid, query=budget_query):
                for row in batch.results:
                    budget_map[row.campaign.name] = row.campaign_budget.amount_micros / 1_000_000.0
        except GoogleAdsException as exc:
            print(f"[google] orcamentos {cid}: {exc}")
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
                        "video_views": 0.0,
                        "interactions": float(row.metrics.clicks),
                        "daily_budget": budget_map.get(row.campaign.name, 0.0),
                    })
            # Demais campanhas (totais). Tenta COM metrics.video_views; se a API
            # rejeitar o campo, refaz SEM ele (video_views=0) — senao perderiamos
            # todas as campanhas nao-SEARCH desta conta.
            try:
                camp_batches = list(service.search_stream(customer_id=cid, query=camp_query))
            except GoogleAdsException as exc:
                if "video" in str(exc) or "Unrecognized field" in str(exc):
                    camp_batches = list(service.search_stream(customer_id=cid, query=camp_query_novv))
                else:
                    raise
            for batch in camp_batches:
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
                        # Views de vídeo (YouTube/Video). Na API v24 o campo e
                        # metrics.video_trueview_views (o antigo video_views nao existe
                        # mais). getattr = seguro caso o nome mude de novo entre versoes.
                        "video_views": float(getattr(row.metrics, "video_trueview_views", 0.0) or 0.0),
                        "interactions": float(row.metrics.clicks),
                        "daily_budget": budget_map.get(row.campaign.name, 0.0),
                    })
        except GoogleAdsException as exc:
            print(f"[google] erro na conta {cid}: {exc}")

    return pd.DataFrame(rows)


def fetch_geo(g_cfg: dict, days: int = 60) -> pd.DataFrame:
    """Cliques por estado (regiao) no Google Ads, com coordenadas p/ o mapa de calor.

    A API nao devolve coordenadas: consultamos geographic_view por geo_target_region,
    resolvemos o id da regiao -> nome via geo_target_constant, e mapeamos o nome do
    estado para os centroides BR_STATE_COORDS (mesmos do Meta -> mapa consistente).
    """
    if not g_cfg.get("developer_token") or not g_cfg.get("refresh_token"):
        return pd.DataFrame()
    from google.ads.googleads.errors import GoogleAdsException

    client = _client(g_cfg)
    service = client.get_service("GoogleAdsService")
    since, until = _date_range(days)
    rows = []

    geo_query = f"""
        SELECT segments.geo_target_region, segments.date,
               geographic_view.location_type, metrics.clicks
        FROM geographic_view
        WHERE segments.date BETWEEN '{since}' AND '{until}'
    """

    def _rid(resource_name):
        # "geoTargetConstants/20106" -> "20106"
        return str(resource_name).rsplit("/", 1)[-1] if resource_name else ""

    for cid in _customer_ids(g_cfg, client):
        raw, region_ids = [], set()
        try:
            for batch in service.search_stream(customer_id=cid, query=geo_query):
                for row in batch.results:
                    # cliques por presenca fisica (evita dupla contagem com area de interesse)
                    if row.geographic_view.location_type.name != "LOCATION_OF_PRESENCE":
                        continue
                    rid = _rid(row.segments.geo_target_region)
                    if not rid:
                        continue
                    region_ids.add(rid)
                    raw.append((str(row.segments.date), rid, float(row.metrics.clicks)))
        except GoogleAdsException as exc:
            print(f"[google-geo] {cid}: {exc}")
            continue
        if not raw:
            continue
        # resolve id da regiao -> nome do estado
        names = {}
        try:
            in_clause = ",".join(sorted(region_ids))
            gtc_query = (
                "SELECT geo_target_constant.id, geo_target_constant.name "
                "FROM geo_target_constant "
                f"WHERE geo_target_constant.id IN ({in_clause})"
            )
            for batch in service.search_stream(customer_id=cid, query=gtc_query):
                for row in batch.results:
                    names[str(row.geo_target_constant.id)] = row.geo_target_constant.name
        except GoogleAdsException as exc:
            print(f"[google-geo] resolve {cid}: {exc}")
        for date, rid, clk in raw:
            match = _STATE_BY_NORM.get(_state_key(names.get(rid, "")))
            if not match:
                continue
            state, lat, lng = match
            rows.append({"date": date, "account_id": cid, "platform": "google",
                         "level": "estado", "city": state, "lat": lat, "lng": lng, "clicks": clk})
    return pd.DataFrame(rows)


def fetch_geo_city(g_cfg: dict, days: int = 60) -> pd.DataFrame:
    """Cliques por CIDADE no Google Ads (segments.geo_target_city).

    A API nao traz coordenadas: resolvemos o id -> nome via geo_target_constant e, p/ o
    mapa, casamos com BR_CITY_COORDS (principais cidades). Cidades sem coordenada entram
    com lat/lng=0 -> aparecem no ranking (lista), nao no mapa.
    """
    if not g_cfg.get("developer_token") or not g_cfg.get("refresh_token"):
        return pd.DataFrame()
    from google.ads.googleads.errors import GoogleAdsException

    client = _client(g_cfg)
    service = client.get_service("GoogleAdsService")
    since, until = _date_range(days)
    rows = []
    # user_location_view = cidade REAL do usuario (geographic_view quase nao popula cidade).
    # AGREGA o periodo (sem segments.date) -> 1 linha por cidade/conta (rapido); seria
    # inviavel por dia (cidades x dias x contas = dezenas de milhares de linhas).
    # ORDER BY + LIMIT: so as cidades com mais cliques (o que importa p/ mapa/ranking).
    # Limita o volume por conta -> refresh rapido e estavel (sem isso, milhares de linhas).
    geo_query = f"""
        SELECT segments.geo_target_city, metrics.clicks
        FROM user_location_view
        WHERE segments.date BETWEEN '{since}' AND '{until}'
        ORDER BY metrics.clicks DESC
        LIMIT 40
    """

    def _rid(rn):
        return str(rn).rsplit("/", 1)[-1] if rn else ""

    for cid in _customer_ids(g_cfg, client):
        by_city = {}
        try:
            for batch in service.search_stream(customer_id=cid, query=geo_query):
                for row in batch.results:
                    rid = _rid(row.segments.geo_target_city)
                    if not rid:
                        continue
                    by_city[rid] = by_city.get(rid, 0.0) + float(row.metrics.clicks)
        except GoogleAdsException as exc:
            print(f"[google-cidade] {cid}: {exc}")
            continue
        if not by_city:
            continue
        names = {}
        try:
            in_clause = ",".join(sorted(by_city))
            gtc_query = (
                "SELECT geo_target_constant.id, geo_target_constant.name "
                "FROM geo_target_constant "
                f"WHERE geo_target_constant.id IN ({in_clause})"
            )
            for batch in service.search_stream(customer_id=cid, query=gtc_query):
                for row in batch.results:
                    names[str(row.geo_target_constant.id)] = row.geo_target_constant.name
        except GoogleAdsException as exc:
            print(f"[google-cidade] resolve {cid}: {exc}")
        for rid, clk in by_city.items():
            cidade = names.get(rid, "")
            if not cidade or clk <= 0:
                continue
            coord = _CITY_BY_NORM.get(_norm(cidade))
            name = coord[0] if coord else cidade
            lat = coord[1] if coord else 0.0
            lng = coord[2] if coord else 0.0
            rows.append({"date": until.isoformat() if hasattr(until, "isoformat") else until,
                         "account_id": cid, "platform": "google", "level": "cidade",
                         "city": name, "lat": lat, "lng": lng, "clicks": clk})
    return pd.DataFrame(rows)
