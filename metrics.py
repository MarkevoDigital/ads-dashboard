"""
Motor de metricas adaptativas.

A ideia central: o conjunto de KPIs em destaque MUDA conforme o objetivo da
campanha. Cada objetivo aponta para uma lista ordenada de KPIs do catalogo.
Tudo e calculado a partir de somas agregadas (forma correta de agregar razoes).
"""
from __future__ import annotations

import pandas as pd

# ----------------------------------------------------------------------------
# Catalogo de KPIs
#   dir: "up"  -> maior e melhor | "down" -> menor e melhor | "neutral"
#   fmt: como formatar no front (currency, int, pct, ratio, dec)
#   calc: recebe dict de somas e devolve o valor
# ----------------------------------------------------------------------------
def _safe(n, d):
    return (n / d) if d else 0.0


KPI_CATALOG = {
    "spend":        {"label": "Investimento",        "fmt": "currency", "dir": "neutral", "calc": lambda s: s["spend"]},
    "impressions":  {"label": "Impressoes",          "fmt": "int",      "dir": "up",      "calc": lambda s: s["impressions"]},
    "reach":        {"label": "Alcance",             "fmt": "int",      "dir": "up",      "calc": lambda s: s["reach"]},
    "frequency":    {"label": "Frequencia",          "fmt": "dec",      "dir": "down",    "calc": lambda s: _safe(s["impressions"], s["reach"])},
    "clicks":       {"label": "Cliques",             "fmt": "int",      "dir": "up",      "calc": lambda s: s["clicks"]},
    "link_clicks":  {"label": "Cliques no link",     "fmt": "int",      "dir": "up",      "calc": lambda s: s["link_clicks"]},
    "ctr":          {"label": "CTR",                 "fmt": "pct",      "dir": "up",      "calc": lambda s: _safe(s["clicks"], s["impressions"])},
    "cpc":          {"label": "CPC",                 "fmt": "currency", "dir": "down",    "calc": lambda s: _safe(s["spend"], s["clicks"])},
    "cpm":          {"label": "CPM",                 "fmt": "currency", "dir": "down",    "calc": lambda s: _safe(s["spend"], s["impressions"]) * 1000},
    "conversions":  {"label": "Conversoes",          "fmt": "int",      "dir": "up",      "calc": lambda s: s["conversions"]},
    "revenue":      {"label": "Receita",             "fmt": "currency", "dir": "up",      "calc": lambda s: s["revenue"]},
    "roas":         {"label": "ROAS",                "fmt": "ratio",    "dir": "up",      "calc": lambda s: _safe(s["revenue"], s["spend"])},
    "cpa":          {"label": "CPA",                 "fmt": "currency", "dir": "down",    "calc": lambda s: _safe(s["spend"], s["conversions"])},
    "conv_rate":    {"label": "Taxa de conversao",   "fmt": "pct",      "dir": "up",      "calc": lambda s: _safe(s["conversions"], s["clicks"])},
    "leads":        {"label": "Leads",               "fmt": "int",      "dir": "up",      "calc": lambda s: s["leads"]},
    "cpl":          {"label": "Custo por lead",      "fmt": "currency", "dir": "down",    "calc": lambda s: _safe(s["spend"], s["leads"])},
    "lead_rate":    {"label": "Taxa de lead",        "fmt": "pct",      "dir": "up",      "calc": lambda s: _safe(s["leads"], s["link_clicks"])},
    "messaging":    {"label": "Conversas iniciadas", "fmt": "int",      "dir": "up",      "calc": lambda s: s["messaging"]},
    "cost_per_msg": {"label": "Custo por conversa",  "fmt": "currency", "dir": "down",    "calc": lambda s: _safe(s["spend"], s["messaging"])},
    "profile_visits":{"label": "Visitas ao perfil",  "fmt": "int",      "dir": "up",      "calc": lambda s: s["profile_visits"]},
    "cost_per_visit":{"label": "Custo por visita",   "fmt": "currency", "dir": "down",    "calc": lambda s: _safe(s["spend"], s["profile_visits"])},
}

# ----------------------------------------------------------------------------
# Configuracao por objetivo: KPIs em destaque + KPI principal (heroi)
# ----------------------------------------------------------------------------
OBJECTIVE_CONFIG = {
    "vendas": {
        "label": "Vendas / Conversoes", "icone": "shopping-cart",
        "kpis": ["spend", "revenue", "roas", "conversions", "cpa", "conv_rate"],
        "primary": "roas",
        "best_ad_metric": "roas",
    },
    "leads": {
        "label": "Geracao de leads", "icone": "user-plus",
        "kpis": ["spend", "leads", "cpl", "lead_rate", "ctr", "cpc"],
        "primary": "cpl",
        "best_ad_metric": "cpl",
    },
    "mensagens": {
        "label": "Conversas por mensagem", "icone": "message-circle",
        "kpis": ["spend", "messaging", "cost_per_msg", "ctr", "cpc", "impressions"],
        "primary": "cost_per_msg",
        "best_ad_metric": "cost_per_msg",
    },
    "visitas_instagram": {
        "label": "Visitas ao Instagram", "icone": "instagram",
        "kpis": ["spend", "profile_visits", "cost_per_visit", "ctr", "cpc", "reach"],
        "primary": "cost_per_visit",
        "best_ad_metric": "cost_per_visit",
    },
    "trafego": {
        "label": "Trafego / Cliques", "icone": "mouse-pointer",
        "kpis": ["spend", "link_clicks", "cpc", "ctr", "impressions", "cpm"],
        "primary": "cpc",
        "best_ad_metric": "cpc",
    },
    "alcance": {
        "label": "Alcance / Reconhecimento", "icone": "radio",
        "kpis": ["spend", "reach", "cpm", "frequency", "impressions", "clicks"],
        "primary": "cpm",
        "best_ad_metric": "cpm",
    },
    "outros": {
        "label": "Outros", "icone": "bar-chart",
        "kpis": ["spend", "impressions", "clicks", "ctr", "cpc", "cpm"],
        "primary": "ctr",
        "best_ad_metric": "ctr",
    },
}


def objective_config(obj: str) -> dict:
    return OBJECTIVE_CONFIG.get(obj, OBJECTIVE_CONFIG["outros"])


# ----------------------------------------------------------------------------
# Agregacao de somas (unifica Meta + Google num mesmo dicionario)
# ----------------------------------------------------------------------------
def _sums(meta: pd.DataFrame, google: pd.DataFrame) -> dict:
    m = {c: float(meta[c].sum()) if len(meta) else 0.0 for c in
         ["impressions", "reach", "clicks", "link_clicks", "spend",
          "messaging_conversations", "profile_visits", "leads",
          "purchases", "purchase_value"]}
    g = {c: float(google[c].sum()) if len(google) else 0.0 for c in
         ["impressions", "clicks", "cost", "conversions", "conversion_value"]}
    return {
        "impressions": m["impressions"] + g["impressions"],
        "reach": m["reach"],
        "clicks": m["clicks"] + g["clicks"],
        "link_clicks": m["link_clicks"] + g["clicks"],
        "spend": m["spend"] + g["cost"],
        "messaging": m["messaging_conversations"],
        "profile_visits": m["profile_visits"],
        "leads": m["leads"],
        # conversoes/receita combinam compras (Meta) + conversoes (Google)
        "conversions": m["purchases"] + g["conversions"],
        "revenue": m["purchase_value"] + g["conversion_value"],
    }


def compute_kpis(meta: pd.DataFrame, google: pd.DataFrame, kpi_keys: list[str]) -> dict:
    s = _sums(meta, google)
    out = {}
    for key in kpi_keys:
        spec = KPI_CATALOG[key]
        out[key] = {
            "key": key, "label": spec["label"], "fmt": spec["fmt"],
            "dir": spec["dir"], "value": round(spec["calc"](s), 4),
        }
    return out


def kpi_value(meta: pd.DataFrame, google: pd.DataFrame, key: str) -> float:
    return KPI_CATALOG[key]["calc"](_sums(meta, google))


# ----------------------------------------------------------------------------
# Variacao percentual periodo vs periodo
# ----------------------------------------------------------------------------
def pct_change(curr: float, prev: float) -> float | None:
    if prev == 0:
        return None
    return round((curr - prev) / abs(prev) * 100, 1)


def is_good(direction: str, delta: float | None) -> bool | None:
    if delta is None or direction == "neutral":
        return None
    return delta >= 0 if direction == "up" else delta <= 0
