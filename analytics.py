"""
Monta o payload completo do dashboard a partir dos DataFrames filtrados.

Saida (dict) consumida pelo front e pelo gerador de comentarios:
  filtros, periodo, blocos_objetivo, serie_temporal, melhores_anuncios,
  palavras_chave, comparativo_plataforma, comparativo_periodo.
"""
from __future__ import annotations

import pandas as pd

import metrics as M


def _window(df: pd.DataFrame, start, end) -> pd.DataFrame:
    if df.empty:
        return df
    return df[(df["date"] >= start) & (df["date"] <= end)]


def _fmt_date(ts) -> str:
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


# ----------------------------------------------------------------------------
# Blocos por objetivo (KPIs adaptativos)
# ----------------------------------------------------------------------------
def _objective_blocks(meta_cur, google_cur, meta_prev, google_prev) -> list[dict]:
    objs = sorted(set(meta_cur["objective"]).union(set(google_cur["objective"])))
    blocks = []
    for obj in objs:
        cfg = M.objective_config(obj)
        mc, gc = meta_cur[meta_cur["objective"] == obj], google_cur[google_cur["objective"] == obj]
        mp, gp = meta_prev[meta_prev["objective"] == obj], google_prev[google_prev["objective"] == obj]
        if mc.empty and gc.empty:
            continue
        cur = M.compute_kpis(mc, gc, cfg["kpis"])
        prev = M.compute_kpis(mp, gp, cfg["kpis"])
        cards = []
        for key in cfg["kpis"]:
            c, p = cur[key], prev[key]
            delta = M.pct_change(c["value"], p["value"])
            cards.append({
                **c,
                "prev_value": p["value"],
                "delta_pct": delta,
                "good": M.is_good(c["dir"], delta),
                "is_primary": key == cfg["primary"],
            })
        blocks.append({
            "objective": obj,
            "label": cfg["label"],
            "icone": cfg["icone"],
            "primary": cfg["primary"],
            "spend": round(M.kpi_value(mc, gc, "spend"), 2),
            "cards": cards,
        })
    # ordena por investimento desc
    blocks.sort(key=lambda b: b["spend"], reverse=True)
    return blocks


# ----------------------------------------------------------------------------
# Serie temporal diaria (investimento + KPI principal do objetivo dominante)
# ----------------------------------------------------------------------------
def _time_series(meta_cur, google_cur, primary_obj) -> dict:
    cfg = M.objective_config(primary_obj)
    primary = cfg["primary"]
    days = sorted(set(meta_cur["date"]).union(set(google_cur["date"])))
    labels, spend_s, primary_s = [], [], []
    for d in days:
        md = meta_cur[meta_cur["date"] == d]
        gd = google_cur[google_cur["date"] == d]
        labels.append(_fmt_date(d))
        spend_s.append(round(M.kpi_value(md, gd, "spend"), 2))
        primary_s.append(round(M.kpi_value(md, gd, primary), 4))
    return {
        "labels": labels,
        "spend": spend_s,
        "primary_key": primary,
        "primary_label": M.KPI_CATALOG[primary]["label"],
        "primary_fmt": M.KPI_CATALOG[primary]["fmt"],
        "primary": primary_s,
    }


# ----------------------------------------------------------------------------
# Melhores anuncios (com print/thumbnail) — metrica conforme objetivo
# ----------------------------------------------------------------------------
def _best_ads(meta_cur, limit=6) -> list[dict]:
    if meta_cur.empty:
        return []
    total_spend = meta_cur["spend"].sum()
    min_spend = max(total_spend * 0.01, 20)  # ignora anuncios irrelevantes
    rows = []
    grouped = meta_cur.groupby(["ad_name", "account", "objective", "ad_thumbnail_url", "ad_permalink"], dropna=False)
    for (ad, acc, obj, thumb, link), g in grouped:
        if g["spend"].sum() < min_spend:
            continue
        cfg = M.objective_config(obj)
        metric_key = cfg["best_ad_metric"]
        spec = M.KPI_CATALOG[metric_key]
        empty = pd.DataFrame(columns=["impressions", "clicks", "cost", "conversions", "conversion_value"])
        score = M.kpi_value(g, empty, metric_key)
        rows.append({
            "ad_name": ad, "account": acc, "objective": obj,
            "objective_label": cfg["label"],
            "thumbnail": thumb, "permalink": link,
            "metric_key": metric_key, "metric_label": spec["label"],
            "metric_fmt": spec["fmt"], "metric_value": round(score, 4),
            "metric_dir": spec["dir"],
            "spend": round(g["spend"].sum(), 2),
            "impressions": int(g["impressions"].sum()),
            "ctr": round(M.kpi_value(g, empty, "ctr"), 4),
        })
    for r in rows:
        r["_sort"] = r["metric_value"] if r["metric_dir"] == "up" else -r["metric_value"]
    rows.sort(key=lambda r: r["_sort"], reverse=True)
    for r in rows:
        r.pop("_sort", None)
    return rows[:limit]


# ----------------------------------------------------------------------------
# Palavras-chave (Google Ads)
# ----------------------------------------------------------------------------
def _keywords(google_cur, limit=10) -> list[dict]:
    if google_cur.empty:
        return []
    g = google_cur[google_cur["keyword"].astype(str).str.strip() != ""]
    if g.empty:
        return []
    agg = g.groupby("keyword", dropna=False).agg(
        impressions=("impressions", "sum"),
        clicks=("clicks", "sum"),
        cost=("cost", "sum"),
        conversions=("conversions", "sum"),
        conversion_value=("conversion_value", "sum"),
    ).reset_index()
    agg["ctr"] = agg.apply(lambda r: (r["clicks"] / r["impressions"]) if r["impressions"] else 0, axis=1)
    agg["cpc"] = agg.apply(lambda r: (r["cost"] / r["clicks"]) if r["clicks"] else 0, axis=1)
    agg["cpa"] = agg.apply(lambda r: (r["cost"] / r["conversions"]) if r["conversions"] else 0, axis=1)
    agg["roas"] = agg.apply(lambda r: (r["conversion_value"] / r["cost"]) if r["cost"] else 0, axis=1)
    agg = agg.sort_values(["conversions", "clicks"], ascending=False).head(limit)
    out = []
    for _, r in agg.iterrows():
        out.append({
            "keyword": r["keyword"],
            "impressions": int(r["impressions"]),
            "clicks": int(r["clicks"]),
            "cost": round(r["cost"], 2),
            "conversions": int(r["conversions"]),
            "ctr": round(r["ctr"], 4),
            "cpc": round(r["cpc"], 2),
            "cpa": round(r["cpa"], 2),
            "roas": round(r["roas"], 2),
        })
    return out


# ----------------------------------------------------------------------------
# Comparativos
# ----------------------------------------------------------------------------
def _platform_comparison(meta_cur, google_cur) -> dict:
    empty_g = pd.DataFrame(columns=["impressions", "clicks", "cost", "conversions", "conversion_value"])
    empty_m = pd.DataFrame(columns=meta_cur.columns)
    def block(m, g):
        return {
            "spend": round(M.kpi_value(m, g, "spend"), 2),
            "impressions": int(M.kpi_value(m, g, "impressions")),
            "clicks": int(M.kpi_value(m, g, "clicks")),
            "conversions": round(M.kpi_value(m, g, "conversions"), 1),
            "revenue": round(M.kpi_value(m, g, "revenue"), 2),
            "cpc": round(M.kpi_value(m, g, "cpc"), 2),
        }
    return {
        "meta": block(meta_cur, empty_g),
        "google": block(empty_m, google_cur),
    }


def _period_comparison(meta_cur, google_cur, meta_prev, google_prev) -> list[dict]:
    keys = ["spend", "impressions", "clicks", "conversions", "revenue", "cpc"]
    out = []
    for key in keys:
        cur = M.kpi_value(meta_cur, google_cur, key)
        prev = M.kpi_value(meta_prev, google_prev, key)
        spec = M.KPI_CATALOG[key]
        delta = M.pct_change(cur, prev)
        out.append({
            "key": key, "label": spec["label"], "fmt": spec["fmt"],
            "current": round(cur, 4), "previous": round(prev, 4),
            "delta_pct": delta, "good": M.is_good(spec["dir"], delta),
        })
    return out


# ----------------------------------------------------------------------------
# Orquestrador
# ----------------------------------------------------------------------------
def build_payload(store, account="todas", platform="todas", days=30, scope=None) -> dict:
    meta, google = store.meta.copy(), store.google.copy()

    # Isolamento multi-tenant: limita aos account_ids do cliente (scope=None = admin/tudo).
    if scope is not None:
        meta_ids = scope.get("meta_ids") or set()
        google_ids = scope.get("google_ids") or set()
        if "account_id" in meta.columns:
            meta = meta[meta["account_id"].astype(str).isin(meta_ids)]
        if "account_id" in google.columns:
            google = google[google["account_id"].astype(str).isin(google_ids)]

    # contas visiveis ja respeitam o escopo do cliente
    contas_visiveis = sorted(set(meta["account"]).union(set(google["account"])))

    if account and account != "todas":
        meta = meta[meta["account"] == account]
        google = google[google["account"] == account]

    all_dates = list(meta["date"]) + list(google["date"])
    if not all_dates:
        return {"vazio": True, "filtros": {"account": account, "platform": platform, "days": days}}

    end = max(all_dates)
    start = end - pd.Timedelta(days=days - 1)
    prev_end = start - pd.Timedelta(days=1)
    prev_start = prev_end - pd.Timedelta(days=days - 1)

    meta_cur, google_cur = _window(meta, start, end), _window(google, start, end)
    meta_prev, google_prev = _window(meta, prev_start, prev_end), _window(google, prev_start, prev_end)

    if platform == "meta":
        google_cur = google_cur.iloc[0:0]; google_prev = google_prev.iloc[0:0]
    elif platform == "google":
        meta_cur = meta_cur.iloc[0:0]; meta_prev = meta_prev.iloc[0:0]

    blocks = _objective_blocks(meta_cur, google_cur, meta_prev, google_prev)
    primary_obj = blocks[0]["objective"] if blocks else "outros"

    return {
        "vazio": False,
        "filtros": {"account": account, "platform": platform, "days": days},
        "periodo": {
            "inicio": _fmt_date(start), "fim": _fmt_date(end),
            "anterior_inicio": _fmt_date(prev_start), "anterior_fim": _fmt_date(prev_end),
        },
        "contas": contas_visiveis,
        "blocos_objetivo": blocks,
        "serie_temporal": _time_series(meta_cur, google_cur, primary_obj),
        "melhores_anuncios": _best_ads(meta_cur),
        "palavras_chave": _keywords(google_cur),
        "comparativo_plataforma": _platform_comparison(meta_cur, google_cur),
        "comparativo_periodo": _period_comparison(meta_cur, google_cur, meta_prev, google_prev),
    }
