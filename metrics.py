"""
Motor de metricas adaptativas.

- O conjunto de KPIs em destaque MUDA conforme o objetivo da campanha.
- Tudo e calculado a partir de somas agregadas (forma correta de agregar razoes).
- Regra de ocultacao: um KPI so aparece se sua metrica-base tiver historico (>0)
  nas contas do cliente. O mapa BASE_KEY define essa dependencia.
"""
from __future__ import annotations

import pandas as pd


def _safe(n, d):
    return (n / d) if d else 0.0


# ----------------------------------------------------------------------------
# Catalogo de KPIs
#   dir: "up" (maior=melhor) | "down" (menor=melhor) | "neutral"
#   fmt: currency | int | pct | ratio | dec
#   base: chave de soma que precisa ter historico (>0) p/ o card aparecer
# ----------------------------------------------------------------------------
KPI_CATALOG = {
    "spend":          {"label": "Investimento",          "fmt": "currency", "dir": "neutral", "base": "spend",        "calc": lambda s: s["spend"]},
    "impressions":    {"label": "Impressões",            "fmt": "int",      "dir": "up",      "base": "impressions",  "calc": lambda s: s["impressions"]},
    "reach":          {"label": "Alcance",               "fmt": "int",      "dir": "up",      "base": "reach",        "calc": lambda s: s["reach"]},
    "frequency":      {"label": "Frequência",            "fmt": "dec",      "dir": "down",    "base": "reach",        "calc": lambda s: _safe(s["impressions"], s["reach"])},
    "clicks":         {"label": "Cliques",               "fmt": "int",      "dir": "up",      "base": "clicks",       "calc": lambda s: s["clicks"]},
    "link_clicks":    {"label": "Cliques no link",       "fmt": "int",      "dir": "up",      "base": "link_clicks",  "calc": lambda s: s["link_clicks"]},
    "ctr":            {"label": "CTR",                   "fmt": "pct",      "dir": "up",      "base": "impressions",  "calc": lambda s: _safe(s["clicks"], s["impressions"])},
    "cpc":            {"label": "CPC",                   "fmt": "currency", "dir": "down",    "base": "clicks",       "calc": lambda s: _safe(s["spend"], s["clicks"])},
    "cpm":            {"label": "CPM",                   "fmt": "currency", "dir": "down",    "base": "impressions",  "calc": lambda s: _safe(s["spend"], s["impressions"]) * 1000},
    "conversions":    {"label": "Conversões",            "fmt": "int",      "dir": "up",      "base": "conversions",  "calc": lambda s: s["conversions"]},
    "revenue":        {"label": "Receita",               "fmt": "currency", "dir": "up",      "base": "revenue",      "calc": lambda s: s["revenue"]},
    "roas":           {"label": "ROAS",                  "fmt": "ratio",    "dir": "up",      "base": "revenue",      "calc": lambda s: _safe(s["revenue"], s["spend"])},
    "cpa":            {"label": "CPA",                   "fmt": "currency", "dir": "down",    "base": "conversions",  "calc": lambda s: _safe(s["spend"], s["conversions"])},
    "conv_rate":      {"label": "Taxa de conversão",     "fmt": "pct",      "dir": "up",      "base": "conversions",  "calc": lambda s: _safe(s["conversions"], s["clicks"])},
    "leads":          {"label": "Leads",                 "fmt": "int",      "dir": "up",      "base": "leads",        "calc": lambda s: s["leads"]},
    "cpl":            {"label": "Custo por lead",        "fmt": "currency", "dir": "down",    "base": "leads",        "calc": lambda s: _safe(s["spend"], s["leads"])},
    "lead_rate":      {"label": "Taxa de lead",          "fmt": "pct",      "dir": "up",      "base": "leads",        "calc": lambda s: _safe(s["leads"], s["link_clicks"])},
    "messaging":      {"label": "Conversas iniciadas",   "fmt": "int",      "dir": "up",      "base": "messaging",    "calc": lambda s: s["messaging"]},
    "cost_per_msg":   {"label": "Custo por conversa",    "fmt": "currency", "dir": "down",    "base": "messaging",    "calc": lambda s: _safe(s["spend"], s["messaging"])},
    "profile_visits": {"label": "Visitas ao perfil",     "fmt": "int",      "dir": "up",      "base": "profile_visits","calc": lambda s: s["profile_visits"]},
    "cost_per_visit": {"label": "Custo/visita perfil",   "fmt": "currency", "dir": "down",    "base": "profile_visits","calc": lambda s: _safe(s["spend"], s["profile_visits"])},
    "site_visits":    {"label": "Visitas ao site",       "fmt": "int",      "dir": "up",      "base": "site_visits",  "calc": lambda s: s["site_visits"]},
    "cost_per_site":  {"label": "Custo/visita site",     "fmt": "currency", "dir": "down",    "base": "site_visits",  "calc": lambda s: _safe(s["spend"], s["site_visits"])},
    "video_views":    {"label": "Visualizações de vídeo","fmt": "int",      "dir": "up",      "base": "video_views",  "calc": lambda s: s["video_views"]},
    "cpv":            {"label": "Custo por view",        "fmt": "currency", "dir": "down",    "base": "video_views",  "calc": lambda s: _safe(s["spend"], s["video_views"])},
    "view_rate":      {"label": "Taxa de visualização",  "fmt": "pct",      "dir": "up",      "base": "video_views",  "calc": lambda s: _safe(s["video_views"], s["impressions"])},
    "engagement":     {"label": "Engajamentos",          "fmt": "int",      "dir": "up",      "base": "engagement",   "calc": lambda s: s["engagement"]},
    "eng_rate":       {"label": "Taxa de engajamento",   "fmt": "pct",      "dir": "up",      "base": "engagement",   "calc": lambda s: _safe(s["engagement"], s["impressions"])},
    "interactions":   {"label": "Interações",            "fmt": "int",      "dir": "up",      "base": "interactions", "calc": lambda s: s["interactions"]},
}

# ----------------------------------------------------------------------------
# Configuracao por objetivo: KPIs candidatos (ocultos se zerados) + heroi
# A ordem importa: os primeiros aparecem primeiro.
# ----------------------------------------------------------------------------
OBJECTIVE_CONFIG = {
    "vendas": {
        "label": "Vendas / Conversões", "icone": "shopping-cart", "conv_label": "Conversões",
        "kpis": ["spend", "revenue", "roas", "conversions", "cpa", "conv_rate",
                 "clicks", "ctr", "cpc", "impressions", "cpm", "site_visits"],
        "primary": "roas", "best_ad_metric": "roas", "conv_key": "conversions",
    },
    "leads": {
        "label": "Geração de leads", "icone": "user-plus", "conv_label": "Leads",
        "kpis": ["spend", "leads", "cpl", "lead_rate", "clicks", "ctr", "cpc",
                 "impressions", "cpm", "site_visits"],
        "primary": "cpl", "best_ad_metric": "cpl", "conv_key": "leads",
    },
    "mensagens": {
        "label": "Conversas por mensagem", "icone": "message-circle", "conv_label": "Conversas",
        "kpis": ["spend", "messaging", "cost_per_msg", "clicks", "ctr", "cpc",
                 "impressions", "cpm", "reach"],
        "primary": "cost_per_msg", "best_ad_metric": "cost_per_msg", "conv_key": "messaging",
    },
    "visitas_instagram": {
        "label": "Visitas ao Instagram", "icone": "instagram", "conv_label": "Visitas ao perfil",
        "kpis": ["spend", "profile_visits", "cost_per_visit", "engagement", "eng_rate",
                 "clicks", "ctr", "cpc", "reach", "impressions", "cpm"],
        "primary": "cost_per_visit", "best_ad_metric": "cost_per_visit", "conv_key": "profile_visits",
    },
    "trafego": {
        "label": "Tráfego / Cliques", "icone": "mouse-pointer", "conv_label": "Cliques no link",
        "kpis": ["spend", "link_clicks", "site_visits", "cost_per_site", "cpc", "ctr",
                 "clicks", "impressions", "cpm"],
        "primary": "cpc", "best_ad_metric": "cpc", "conv_key": "link_clicks",
    },
    "video": {
        "label": "Visualizações de vídeo", "icone": "play-circle", "conv_label": "Views",
        "kpis": ["spend", "video_views", "cpv", "view_rate", "engagement",
                 "clicks", "ctr", "impressions", "cpm", "reach"],
        "primary": "cpv", "best_ad_metric": "cpv", "conv_key": "video_views",
    },
    "alcance": {
        "label": "Alcance / Reconhecimento", "icone": "radio", "conv_label": "Alcance",
        "kpis": ["spend", "reach", "cpm", "frequency", "impressions", "clicks",
                 "ctr", "engagement"],
        "primary": "cpm", "best_ad_metric": "cpm", "conv_key": "reach",
    },
    "outros": {
        "label": "Outros", "icone": "bar-chart", "conv_label": "Conversões",
        "kpis": ["spend", "impressions", "clicks", "ctr", "cpc", "cpm",
                 "conversions", "conv_rate"],
        "primary": "ctr", "best_ad_metric": "ctr", "conv_key": "conversions",
    },
}


# Metricas que devem aparecer em QUALQUER objetivo quando tiverem historico (>0):
# visualizacoes de video, visitas ao Instagram e engajamento. A regra de ocultacao
# (active_keys) garante que so aparecem se nao forem zeradas no escopo do cliente.
_EXTRA_KPIS = ["video_views", "profile_visits", "engagement"]


def objective_config(obj: str) -> dict:
    base = OBJECTIVE_CONFIG.get(obj, OBJECTIVE_CONFIG["outros"])
    cfg = dict(base)
    kpis = list(cfg["kpis"])
    for k in _EXTRA_KPIS:
        if k not in kpis:
            kpis.append(k)
    cfg["kpis"] = kpis
    return cfg


# ----------------------------------------------------------------------------
# Agregacao de somas (unifica Meta + Google)
# ----------------------------------------------------------------------------
_META_NUM = ["impressions", "reach", "clicks", "link_clicks", "spend",
             "messaging_conversations", "profile_visits", "leads",
             "purchases", "purchase_value", "site_visits", "video_views",
             "engagement"]
_GOOGLE_NUM = ["impressions", "clicks", "cost", "conversions", "conversion_value",
               "video_views", "interactions"]


def _col(df, c):
    return float(df[c].sum()) if (len(df) and c in df.columns) else 0.0


def _sums(meta: pd.DataFrame, google: pd.DataFrame, tiktok: pd.DataFrame = None) -> dict:
    m = {c: _col(meta, c) for c in _META_NUM}
    g = {c: _col(google, c) for c in _GOOGLE_NUM}
    # TikTok usa o MESMO schema do Meta (_META_NUM) -> soma como uma "segunda fonte meta".
    t = {c: _col(tiktok, c) for c in _META_NUM} if tiktok is not None else {c: 0.0 for c in _META_NUM}
    return {
        "impressions": m["impressions"] + g["impressions"] + t["impressions"],
        "reach": m["reach"] + t["reach"],
        "clicks": m["clicks"] + g["clicks"] + t["clicks"],
        "link_clicks": m["link_clicks"] + g["clicks"] + t["link_clicks"],
        "spend": m["spend"] + g["cost"] + t["spend"],
        "messaging": m["messaging_conversations"] + t["messaging_conversations"],
        "profile_visits": m["profile_visits"] + t["profile_visits"],
        "leads": m["leads"] + t["leads"],
        "site_visits": m["site_visits"] + t["site_visits"],
        "video_views": m["video_views"] + g["video_views"] + t["video_views"],
        "engagement": m["engagement"] + t["engagement"],
        "interactions": g["interactions"],
        "conversions": m["purchases"] + g["conversions"] + t["purchases"],
        "revenue": m["purchase_value"] + g["conversion_value"] + t["purchase_value"],
    }


def sums(meta, google, tiktok=None) -> dict:
    return _sums(meta, google, tiktok)


def sums_for(meta, google, conv_key=None, tiktok=None) -> dict:
    """Somas ajustadas ao objetivo do bloco.

    O Google reporta todos os desfechos em 'conversions'. Em blocos cujo resultado e
    uma conversao especifica (leads, conversas), essas conversoes do Google SAO o
    resultado do objetivo -> contabiliza no bucket certo (ex.: leads = leads do Meta +
    conversoes do Google). Para 'conversions' (vendas) ja esta incluso em _sums.
    (O TikTok ja roteia sua conversao para a coluna meta certa no conector.)
    """
    s = _sums(meta, google, tiktok)
    if conv_key in ("leads", "messaging"):
        s = dict(s)
        s[conv_key] = s[conv_key] + _col(google, "conversions")
    return s


def compute_kpis(meta, google, kpi_keys, conv_key=None, tiktok=None) -> dict:
    s = sums_for(meta, google, conv_key, tiktok)
    out = {}
    for key in kpi_keys:
        spec = KPI_CATALOG[key]
        out[key] = {
            "key": key, "label": spec["label"], "fmt": spec["fmt"],
            "dir": spec["dir"], "value": round(spec["calc"](s), 4),
        }
    return out


def kpi_value(meta, google, key: str, tiktok=None) -> float:
    return KPI_CATALOG[key]["calc"](_sums(meta, google, tiktok))


def active_keys(history_sums: dict, candidate_keys: list[str]) -> list[str]:
    """Filtra KPIs cuja metrica-base tem historico (>0). Mantem a ordem."""
    out = []
    for k in candidate_keys:
        base = KPI_CATALOG[k]["base"]
        if history_sums.get(base, 0) > 0:
            out.append(k)
    return out


# ----------------------------------------------------------------------------
# Variacao percentual
# ----------------------------------------------------------------------------
def pct_change(curr: float, prev: float):
    if prev == 0:
        return None
    return round((curr - prev) / abs(prev) * 100, 1)


def is_good(direction: str, delta):
    if delta is None or direction == "neutral":
        return None
    return delta >= 0 if direction == "up" else delta <= 0
