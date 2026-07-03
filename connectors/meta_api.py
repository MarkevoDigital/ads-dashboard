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

import time
import unicodedata
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
# Nomes acentuados (exibicao); a busca usa forma normalizada (sem acento) p/ casar
# qualquer que seja a grafia retornada pela API.
BR_STATE_COORDS = {
    "Acre": (-9.02, -70.81), "Alagoas": (-9.57, -36.78), "Amapá": (1.41, -51.77),
    "Amazonas": (-3.42, -65.86), "Bahia": (-12.58, -41.70), "Ceará": (-5.20, -39.53),
    "Distrito Federal": (-15.78, -47.93), "Espírito Santo": (-19.19, -40.31),
    "Goiás": (-15.93, -49.84), "Maranhão": (-5.42, -45.44), "Mato Grosso": (-12.64, -55.42),
    "Mato Grosso do Sul": (-20.51, -54.54), "Minas Gerais": (-18.10, -44.38),
    "Pará": (-3.79, -52.48), "Paraíba": (-7.28, -36.72), "Paraná": (-24.89, -51.55),
    "Pernambuco": (-8.38, -37.86), "Piauí": (-6.60, -42.28),
    "Rio de Janeiro": (-22.25, -42.66), "Rio Grande do Norte": (-5.81, -36.59),
    "Rio Grande do Sul": (-30.17, -53.50), "Rondônia": (-10.83, -63.34),
    "Roraima": (1.99, -61.33), "Santa Catarina": (-27.45, -50.95),
    "São Paulo": (-22.19, -48.79), "Sergipe": (-10.57, -37.45), "Tocantins": (-9.46, -48.26),
}


def _norm_state(s: str) -> str:
    """Normaliza nome de estado/cidade (sem acento, minusculo) para casar na busca."""
    s = unicodedata.normalize("NFKD", str(s))
    return "".join(c for c in s if not unicodedata.combining(c)).strip().lower()


# lookup: nome normalizado -> (nome acentuado p/ exibicao, lat, lng)
_STATE_BY_NORM = {_norm_state(k): (k, v[0], v[1]) for k, v in BR_STATE_COORDS.items()}

# Coordenadas das principais cidades do Brasil (capitais + grandes municipios), para
# plotar cliques por cidade no mapa. Cidades fora desta lista ainda aparecem no ranking
# (lista), apenas sem ponto no mapa.
BR_CITY_COORDS = {
    "Rio Branco": (-9.97, -67.81), "Maceió": (-9.67, -35.74), "Macapá": (0.03, -51.07),
    "Manaus": (-3.12, -60.02), "Salvador": (-12.97, -38.50), "Fortaleza": (-3.73, -38.52),
    "Brasília": (-15.79, -47.88), "Vitória": (-20.32, -40.34), "Goiânia": (-16.69, -49.26),
    "São Luís": (-2.53, -44.30), "Cuiabá": (-15.60, -56.10), "Campo Grande": (-20.47, -54.62),
    "Belo Horizonte": (-19.92, -43.94), "Belém": (-1.46, -48.50), "João Pessoa": (-7.12, -34.86),
    "Curitiba": (-25.43, -49.27), "Recife": (-8.05, -34.88), "Teresina": (-5.09, -42.80),
    "Rio de Janeiro": (-22.91, -43.17), "Natal": (-5.79, -35.21), "Porto Alegre": (-30.03, -51.23),
    "Porto Velho": (-8.76, -63.90), "Boa Vista": (2.82, -60.67), "Florianópolis": (-27.59, -48.55),
    "São Paulo": (-23.55, -46.63), "Aracaju": (-10.91, -37.07), "Palmas": (-10.18, -48.33),
    "Várzea Grande": (-15.65, -56.13), "Rondonópolis": (-16.47, -54.64), "Sinop": (-11.86, -55.50),
    "Campinas": (-22.91, -47.06), "Guarulhos": (-23.45, -46.53), "Santo André": (-23.66, -46.53),
    "São Bernardo do Campo": (-23.69, -46.56), "Osasco": (-23.53, -46.79), "Santos": (-23.96, -46.33),
    "Ribeirão Preto": (-21.18, -47.81), "Sorocaba": (-23.50, -47.46), "São José dos Campos": (-23.18, -45.89),
    "Niterói": (-22.88, -43.10), "Duque de Caxias": (-22.79, -43.31), "Nova Iguaçu": (-22.76, -43.45),
    "Contagem": (-19.93, -44.05), "Uberlândia": (-18.91, -48.27), "Juiz de Fora": (-21.76, -43.35),
    "Betim": (-19.97, -44.20), "Londrina": (-23.31, -51.16), "Maringá": (-23.42, -51.94),
    "Joinville": (-26.30, -48.85), "Blumenau": (-26.92, -49.07), "Caxias do Sul": (-29.17, -51.18),
    "Feira de Santana": (-12.27, -38.97), "Jaboatão dos Guararapes": (-8.11, -35.01),
    "Aparecida de Goiânia": (-16.82, -49.24), "Anápolis": (-16.33, -48.95),
}
_CITY_BY_NORM = {_norm_state(k): (k, v[0], v[1]) for k, v in BR_CITY_COORDS.items()}


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


# Erros da Graph API que se resolvem dividindo o intervalo de datas (bisseccao): contas
# com muitos anuncios x dias estouram o limite por requisicao e a Meta devolve mensagens
# vagas ("reduce the amount of data", "unexpected error", subcodes 99/1504044, code 2).
_BISECT_HINTS = (
    "reduce the amount of data", "error_subcode\":99", "an unknown error",
    "service temporarily unavailable", "1504044", "unexpected error",
    "ocorreu um erro", "tente novamente",
)


def _bisectable(exc) -> bool:
    s = str(exc).lower()
    return any(h in s for h in _BISECT_HINTS)


def _insights_windowed(url, params_base, since, until):
    """Busca /insights para [since, until] com resiliencia para contas grandes/instaveis:
    - tenta a janela; em erro 'grande demais'/instavel, divide o intervalo ao meio
      (recursivo, ate 1 dia por janela);
    - numa janela de 1 dia (indivisivel), re-tenta com backoff antes de desistir.
    `params_base` NAO deve conter time_range (e injetado aqui)."""
    params = dict(params_base)
    params["time_range"] = f'{{"since":"{since}","until":"{until}"}}'
    for attempt in range(3):
        try:
            return _paged_get(url, params)
        except RuntimeError as exc:
            if since < until and _bisectable(exc):
                mid = since + (until - since) // 2
                return (_insights_windowed(url, params_base, since, mid)
                        + _insights_windowed(url, params_base, mid + timedelta(days=1), until))
            if attempt < 2:  # janela minima (1 dia) ou erro nao-bissecionavel: backoff e re-tenta
                time.sleep(1.5 * (attempt + 1))
                continue
            raise


def _account_ids(meta_cfg: dict, token: str, version: str) -> list[str]:
    """IDs das contas configuradas; se vazio/placeholder, descobre via /me/adaccounts."""
    ids = []
    for a in (meta_cfg.get("ad_account_ids") or []):
        digits = "".join(c for c in str(a) if c.isdigit())
        if digits and set(digits) != {"0"}:  # ignora vazio e placeholder (so zeros)
            ids.append(a if str(a).startswith("act_") else f"act_{digits}")
    if ids:
        return ids
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
    """Mapa ad_id -> {thumb, link} (print do criativo + link de preview do anuncio).

    A expansao creative{...} e pesada: contas com muitos anuncios estouram
    'Please reduce the amount of data you're asking for' JA na 1a pagina, o que
    zerava thumbs+links de TODOS os anuncios (ex.: Bem me Fiz). Aqui tentamos
    limites de pagina decrescentes (50->25->10->5) ate a Meta aceitar, coletando
    pagina a pagina e mantendo o que ja veio."""
    base_url = f"{GRAPH}/{version}/{account_id}/ads"
    fields = "id,preview_shareable_link,creative{thumbnail_url,image_url}"
    mapa = {}
    for lim in (50, 25, 10, 5):
        mapa = {}
        url, params = base_url, {"fields": fields, "limit": lim, "access_token": token}
        try:
            while url:
                resp = requests.get(url, params=params, timeout=60)
                if resp.status_code != 200:
                    raise RuntimeError(f"Meta API {resp.status_code}: {resp.text[:200]}")
                body = resp.json()
                for ad in body.get("data", []):
                    cre = ad.get("creative", {}) or {}
                    mapa[ad["id"]] = {
                        "thumb": cre.get("thumbnail_url") or cre.get("image_url") or "",
                        "link": ad.get("preview_shareable_link") or "",
                    }
                url = body.get("paging", {}).get("next")
                params = None  # 'next' ja contem a querystring
            return mapa  # sucesso nesse limite
        except RuntimeError as exc:
            if _bisectable(exc) and lim > 5:
                print(f"[meta] thumbnails {account_id}: pagina grande demais (limit={lim}), reduzindo")
                continue
            print(f"[meta] thumbnails/preview indisponiveis ({account_id}): {exc}")
            return mapa  # devolve o parcial que conseguiu
    return mapa


def _campaign_budgets(account_id, token, version) -> dict:
    """Mapa campaign_id -> orcamento diario (na moeda). CBO (campanha) ou soma de adsets."""
    out = {}
    try:  # orcamento no nivel da campanha (CBO)
        url = f"{GRAPH}/{version}/{account_id}/campaigns"
        for c in _paged_get(url, {"fields": "id,daily_budget", "limit": 500, "access_token": token}):
            db = c.get("daily_budget")
            if db:
                out[c["id"]] = float(db) / 100.0
    except Exception as exc:  # noqa: BLE001
        print(f"[meta] orcamentos (campanha) indisponiveis: {exc}")
    try:  # soma dos adsets (p/ campanhas sem CBO)
        url2 = f"{GRAPH}/{version}/{account_id}/adsets"
        adsum = {}
        for a in _paged_get(url2, {"fields": "campaign_id,daily_budget", "limit": 500, "access_token": token}):
            db, cid = a.get("daily_budget"), a.get("campaign_id")
            if db and cid:
                adsum[cid] = adsum.get(cid, 0.0) + float(db) / 100.0
        for cid, v in adsum.items():
            out.setdefault(cid, v)
    except Exception as exc:  # noqa: BLE001
        print(f"[meta] orcamentos (adset) indisponiveis: {exc}")
    return out


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
        try:
            rows.extend(_fetch_account_rows(account_id, token, version, since, until, obj_map))
        except Exception as exc:  # noqa: BLE001
            print(f"[meta] conta {account_id} falhou (ignorada): {exc}")
    return pd.DataFrame(rows)


def _fetch_account_rows(account_id, token, version, since, until, obj_map) -> list[dict]:
    thumbs = _thumbnails(account_id, token, version)
    budgets = _campaign_budgets(account_id, token, version)
    url = f"{GRAPH}/{version}/{account_id}/insights"
    params = {
        "level": "ad", "time_increment": 1,
        "fields": ",".join([
            "ad_id", "ad_name", "adset_name", "campaign_id", "campaign_name", "objective",
            "account_name", "impressions", "reach", "frequency", "clicks",
            "inline_link_clicks", "spend", "actions", "action_values",
        ]),
        "limit": 500, "access_token": token,
    }
    out = []
    for r in _insights_windowed(url, params, since, until):
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
        # Leads SO por formulario (Instant Form = onsite_conversion.lead_grouped) e SO de
        # campanhas com objetivo de geracao de leads. Coluna paralela usada por clientes
        # com a flag leads_form_only no clients.json (ex.: IPV7), para baterem com o
        # gerenciador (a coluna "leads" padrao soma form + pixel + genericos).
        form_leads = (_first_action(actions, ["onsite_conversion.lead_grouped"])
                      if objective == "leads" else 0.0)
        ad_id = r.get("ad_id", "")
        ad_meta = thumbs.get(ad_id, {}) or {}
        out.append({
            "date": r.get("date_start"),
            "account": r.get("account_name") or account_id,
            "account_id": account_id.replace("act_", ""),
            "objective": objective,
            "campaign": r.get("campaign_name", ""),
            "adset": r.get("adset_name", ""),
            "ad_name": r.get("ad_name", ""),
            "ad_thumbnail_url": ad_meta.get("thumb", ""),
            "ad_permalink": ad_meta.get("link", ""),
            "daily_budget": float(budgets.get(r.get("campaign_id", ""), 0.0)),
            "impressions": float(r.get("impressions", 0) or 0),
            "reach": float(r.get("reach", 0) or 0),
            "frequency": float(r.get("frequency", 0) or 0),
            "clicks": float(r.get("clicks", 0) or 0),
            "link_clicks": float(r.get("inline_link_clicks", 0) or 0),
            "spend": float(r.get("spend", 0) or 0),
            "messaging_conversations": msg,
            "profile_visits": visits, "leads": leads, "form_leads": form_leads,
            "purchases": purchases,
            "purchase_value": revenue, "site_visits": site_visits,
            "video_views": video_views, "engagement": engagement,
        })
    return out


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
            "fields": "clicks", "limit": 500, "access_token": token,
        }
        try:
            for r in _insights_windowed(url, params, since, until):
                match = _STATE_BY_NORM.get(_norm_state(r.get("region", "")))
                if not match:
                    continue
                name, lat, lng = match
                rows.append({
                    "date": r.get("date_start"), "account_id": account_id.replace("act_", ""),
                    "platform": "meta", "level": "estado", "city": name,
                    "lat": lat, "lng": lng, "clicks": float(r.get("clicks", 0) or 0),
                })
        except Exception as exc:  # noqa: BLE001
            print(f"[meta-geo] {account_id}: {exc}")
    return pd.DataFrame(rows)
