"""LinkedIn Ads: relatorio por anuncio (criativo) por dia, no MESMO schema de linhas do
Meta/TikTok (META_COLUMNS), mais o numero de seguidores das Paginas administradas.

Autenticacao: connectors/linkedin_auth.py (token OAuth guardado no servidor e
renovado sozinho). Sem token valido, tudo aqui devolve vazio e o dashboard segue.

Hierarquia: o LinkedIn tem grupo de campanhas > campanha > criativo. Orcamento e
segmentacao ficam na CAMPANHA, entao ela vira a "campanha" do dashboard e o criativo
vira o "anuncio"; o grupo de campanhas nao aparece (nao ha nivel equivalente util).

Docs (versao 202608):
  ads-reporting            /rest/adAnalytics  (q=analytics, pivot=CREATIVE, DAILY)
  create-and-manage-campaigns  /rest/adAccounts/{id}/adCampaigns (q=search)
  create-and-manage-creatives  /rest/adAccounts/{id}/creatives   (q=criteria, FINDER)
  organization-lookup-api  /rest/networkSizes (seguidores)
  organization-access-control-by-role /rest/organizationAcls (Paginas que o usuario administra)
"""
import os
import time
from datetime import timedelta
from urllib.parse import quote

import pandas as pd
import requests

from connectors import linkedin_auth
from tz_br import today_br

BASE = "https://api.linkedin.com/rest"
VERSAO = "202608"   # Marketing August 2026; cada versao vale no minimo 1 ano

# objectiveType da campanha -> bucket de objetivo do dashboard (mesmos do Meta/TikTok).
OBJETIVO = {
    "WEBSITE_CONVERSION": "vendas",
    "LEAD_GENERATION": "leads",
    "WEBSITE_VISIT": "trafego",
    "VIDEO_VIEW": "video",
    "BRAND_AWARENESS": "alcance",
    "ENGAGEMENT": "engajamento",
    "CREATOR_FOLLOWER": "engajamento",
    "JOB_APPLICANT": "outros",
    "TALENT_LEAD": "outros",
}

# Metricas pedidas no relatorio diario. approximateMemberReach fica de fora: alcance
# nao soma por dia e um campo recusado derruba a requisicao inteira.
CAMPOS = ("impressions,clicks,costInLocalCurrency,externalWebsiteConversions,"
          "conversionValueInLocalCurrency,landingPageClicks,videoViews,oneClickLeads,"
          "totalEngagements,follows,dateRange,pivotValues")

STATUS_CAMPANHA = "ACTIVE,PAUSED,ARCHIVED,COMPLETED,CANCELED,DRAFT,PENDING_DELETION,REMOVED"


def _versao():
    return os.environ.get("LINKEDIN_VERSION", "").strip() or VERSAO


def _headers(token, finder=False):
    h = {"Authorization": f"Bearer {token}", "Linkedin-Version": _versao(),
         "X-Restli-Protocol-Version": "2.0.0"}
    if finder:
        h["X-RestLi-Method"] = "FINDER"
    return h


def _get(path_e_query, token, finder=False):
    """GET com a query JA MONTADA: a sintaxe Rest.li (List(...), (start:(...))) nao pode
    ser reescapada pelo requests. Retry curto para 429/5xx."""
    url = f"{BASE}/{path_e_query}"
    ultimo = None
    for tentativa in range(3):
        r = requests.get(url, headers=_headers(token, finder), timeout=90)
        if r.status_code == 200:
            return r.json()
        ultimo = f"HTTP {r.status_code}: {r.text[:240]}"
        if r.status_code in (429, 500, 503) and tentativa < 2:
            time.sleep(3 * (tentativa + 1))
            continue
        break
    raise RuntimeError(f"LinkedIn {path_e_query.split('?')[0]} -> {ultimo}")


def _urn_conta(conta_id):
    return quote(f"urn:li:sponsoredAccount:{conta_id}", safe="")


def _digitos(v):
    return "".join(ch for ch in str(v) if ch.isdigit())


def _data_rest(d):
    return f"(year:{d.year},month:{d.month},day:{d.day})"


def _contas(cfg):
    ids = [_digitos(x) for x in (cfg.get("account_ids") or []) if _digitos(x)]
    return list(dict.fromkeys(ids))


def _info_conta(conta_id, token):
    try:
        d = _get(f"adAccounts/{conta_id}", token)
        return {"nome": d.get("name") or f"LinkedIn {conta_id}", "moeda": d.get("currency") or ""}
    except Exception as exc:  # noqa: BLE001
        print(f"[linkedin] conta {conta_id}: {exc}")
        return {"nome": f"LinkedIn {conta_id}", "moeda": ""}


def _campanhas(conta_id, token):
    """id numerico -> {nome, objetivo, orcamento_diario}."""
    out, page_token = {}, None
    while True:
        q = (f"adAccounts/{conta_id}/adCampaigns?q=search"
             f"&search=(status:(values:List({STATUS_CAMPANHA})))&pageSize=1000")
        if page_token:
            q += f"&pageToken={quote(page_token, safe='')}"
        d = _get(q, token)
        for c in d.get("elements", []) or []:
            orc = (c.get("dailyBudget") or {}).get("amount")
            out[_digitos(c.get("id"))] = {
                "nome": c.get("name") or f"Campanha {c.get('id')}",
                "objetivo": OBJETIVO.get(str(c.get("objectiveType") or "").upper(), "outros"),
                "orcamento": float(orc) if orc not in (None, "") else 0.0,
            }
        page_token = (d.get("metadata") or {}).get("nextPageToken")
        if not page_token:
            return out


def _criativos(conta_id, token):
    """id numerico do criativo -> {nome, campanha_id}."""
    out, page_token = {}, None
    while True:
        q = f"adAccounts/{conta_id}/creatives?q=criteria&pageSize=100"
        if page_token:
            q += f"&pageToken={quote(page_token, safe='')}"
        d = _get(q, token, finder=True)
        for c in d.get("elements", []) or []:
            cid = _digitos(str(c.get("id", "")).rsplit(":", 1)[-1])
            out[cid] = {"nome": (c.get("name") or "").strip(),
                        "campanha": _digitos(str(c.get("campaign", "")).rsplit(":", 1)[-1])}
        page_token = (d.get("metadata") or {}).get("nextPageToken")
        if not page_token:
            return out


def _num(v):
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def fetch(cfg: dict, days: int = 60) -> pd.DataFrame:
    token = linkedin_auth.access_token()
    contas = _contas(cfg)
    if not token or not contas:
        return pd.DataFrame()
    fim = today_br()
    inicio = fim - timedelta(days=days - 1)
    rows = []
    for conta in contas:
        try:
            info = _info_conta(conta, token)
            camps = _campanhas(conta, token)
            cria = _criativos(conta, token)
            # Janelas de 30 dias: o adAnalytics nao pagina e corta em 15 mil linhas.
            ini = inicio
            while ini <= fim:
                fim_janela = min(ini + timedelta(days=29), fim)
                q = (f"adAnalytics?q=analytics&pivot=CREATIVE&timeGranularity=DAILY"
                     f"&dateRange=(start:{_data_rest(ini)},end:{_data_rest(fim_janela)})"
                     f"&accounts=List({_urn_conta(conta)})&fields={CAMPOS}")
                for el in (_get(q, token).get("elements") or []):
                    dr = (el.get("dateRange") or {}).get("start") or {}
                    data = f"{dr.get('year')}-{int(dr.get('month', 1)):02d}-{int(dr.get('day', 1)):02d}"
                    pv = (el.get("pivotValues") or [""])[0]
                    cid = _digitos(str(pv).rsplit(":", 1)[-1])
                    cr = cria.get(cid, {})
                    camp = camps.get(cr.get("campanha", ""), {})
                    objetivo = camp.get("objetivo", "outros")
                    conv = _num(el.get("externalWebsiteConversions"))
                    leads = _num(el.get("oneClickLeads"))
                    rows.append({
                        "date": data, "account": info["nome"], "account_id": conta,
                        "objective": objetivo,
                        "campaign": camp.get("nome") or f"Campanha {cr.get('campanha') or '?'}",
                        "adset": "", "ad_name": cr.get("nome") or f"Anúncio {cid}",
                        "ad_thumbnail_url": "", "ad_permalink": "",
                        "daily_budget": camp.get("orcamento", 0.0),
                        "impressions": _num(el.get("impressions")), "reach": 0.0, "frequency": 0.0,
                        "clicks": _num(el.get("clicks")), "link_clicks": _num(el.get("landingPageClicks")),
                        "spend": _num(el.get("costInLocalCurrency")),
                        "messaging_conversations": 0.0, "profile_visits": 0.0,
                        # Mesmo criterio do TikTok: a conversao do site conta como compra so em
                        # campanha de conversao; em campanha de leads ela soma aos leads.
                        "leads": leads + (conv if objetivo == "leads" else 0.0),
                        "form_leads": leads,
                        "purchases": conv if objetivo == "vendas" else 0.0,
                        "purchase_value": _num(el.get("conversionValueInLocalCurrency")),
                        "site_visits": _num(el.get("landingPageClicks")),
                        "video_views": _num(el.get("videoViews")),
                        "engagement": _num(el.get("totalEngagements")),
                        "add_to_cart": 0.0, "initiate_checkout": 0.0, "registrations": 0.0,
                    })
                ini = fim_janela + timedelta(days=1)
        except Exception as exc:  # noqa: BLE001
            print(f"[linkedin] conta {conta} falhou (ignorada): {exc}")
    return pd.DataFrame(rows)


def currencies(cfg: dict) -> dict:
    token = linkedin_auth.access_token()
    if not token:
        return {}
    return {c: _info_conta(c, token)["moeda"] for c in _contas(cfg) if _info_conta(c, token)["moeda"]}


def paginas_administradas(token=None) -> list:
    """[{id, nome}] das Paginas em que o usuario autorizado e ADMINISTRATOR."""
    token = token or linkedin_auth.access_token()
    if not token:
        return []
    d = _get("organizationAcls?q=roleAssignee&role=ADMINISTRATOR&state=APPROVED&count=100", token)
    ids = []
    for el in d.get("elements", []) or []:
        urn = el.get("organization") or el.get("organizationTarget") or ""
        if _digitos(urn):
            ids.append(_digitos(urn.rsplit(":", 1)[-1]))
    out = []
    for oid in dict.fromkeys(ids):
        try:
            org = _get(f"organizations/{oid}", token)
            out.append({"id": oid, "nome": org.get("localizedName") or org.get("vanityName") or oid})
        except Exception as exc:  # noqa: BLE001
            out.append({"id": oid, "nome": oid})
            print(f"[linkedin] organizacao {oid}: {exc}")
    return out


def seguidores(org_id: str, token=None):
    """Total de seguidores da Pagina (firstDegreeSize). None se sem acesso."""
    token = token or linkedin_auth.access_token()
    if not token:
        return None
    urn = quote(f"urn:li:organization:{_digitos(org_id)}", safe="")
    d = _get(f"networkSizes/{urn}?edgeType=COMPANY_FOLLOWED_BY_MEMBER", token)
    v = d.get("firstDegreeSize")
    return int(v) if v is not None else None
