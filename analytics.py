"""
Monta o payload do dashboard a partir dos DataFrames filtrados.

Destaques desta versao:
  - Funil (Impressoes -> Cliques -> Conversoes) com taxas entre etapas.
  - Ocultacao de metricas zeradas: um card so aparece se a metrica tiver
    historico (>0) nas contas do cliente (escopo). Tabelas sao excecao.
  - Tabela de campanhas por plataforma no periodo.
  - Mapa de calor geografico (cliques por cidade).
  - Comentario automatico unico e positivo (em commentary.py).
"""
from __future__ import annotations

import pandas as pd

import metrics as M


def _window(df, start, end):
    if df is None or df.empty:
        return df
    return df[(df["date"] >= start) & (df["date"] <= end)]


def _fmt_date(ts):
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def _digits(v):
    return "".join(ch for ch in str(v) if ch.isdigit())


# ----------------------------------------------------------------------------
# Funil
# ----------------------------------------------------------------------------
def _funnel(meta_cur, google_cur, cfg, has_conv_history) -> dict:
    s = M.sums(meta_cur, google_cur)
    impressions = s["impressions"]
    clicks = s["clicks"]
    conv_key = cfg.get("conv_key", "conversions")
    conversions = s.get(conv_key, s.get("conversions", 0))

    stages = [
        {"label": "Impressões", "value": round(impressions), "fmt": "int"},
        {"label": "Cliques", "value": round(clicks), "fmt": "int"},
    ]
    ctr = (clicks / impressions) if impressions else 0.0
    rates = [{"label": "CTR", "value": round(ctr, 4)}]
    if has_conv_history:
        stages.append({"label": cfg.get("conv_label", "Conversões"),
                       "value": round(conversions), "fmt": "int"})
        rates.append({"label": "Taxa de conversão",
                      "value": round(conversions / clicks if clicks else 0.0, 4)})
    return {"stages": stages, "rates": rates}


# ----------------------------------------------------------------------------
# Blocos por objetivo (KPIs adaptativos, ocultando zerados sem historico)
# ----------------------------------------------------------------------------
def _objective_blocks(meta_cur, google_cur, meta_prev, google_prev,
                      meta_all, google_all) -> list[dict]:
    objs = sorted(set(meta_cur["objective"]).union(set(google_cur["objective"])))
    blocks = []
    for obj in objs:
        cfg = M.objective_config(obj)
        mc = meta_cur[meta_cur["objective"] == obj]
        gc = google_cur[google_cur["objective"] == obj]
        mp = meta_prev[meta_prev["objective"] == obj]
        gp = google_prev[google_prev["objective"] == obj]
        ma = meta_all[meta_all["objective"] == obj]
        ga = google_all[google_all["objective"] == obj]
        if mc.empty and gc.empty:
            continue
        # historico do objetivo -> define quais cards aparecem
        hist = M.sums(ma, ga)
        keys = M.active_keys(hist, cfg["kpis"])
        if not keys:
            continue
        cur = M.compute_kpis(mc, gc, keys)
        prev = M.compute_kpis(mp, gp, keys)
        cards = []
        for key in keys:
            c, p = cur[key], prev[key]
            delta = M.pct_change(c["value"], p["value"])
            cards.append({
                **c, "prev_value": p["value"], "delta_pct": delta,
                "good": M.is_good(c["dir"], delta),
                "is_primary": key == cfg["primary"],
            })
        blocks.append({
            "objective": obj, "label": cfg["label"], "icone": cfg["icone"],
            "primary": cfg["primary"],
            "spend": round(M.kpi_value(mc, gc, "spend"), 2),
            "cards": cards,
        })
    blocks.sort(key=lambda b: b["spend"], reverse=True)
    return blocks


# ----------------------------------------------------------------------------
# Serie temporal
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
        "labels": labels, "spend": spend_s, "primary_key": primary,
        "primary_label": M.KPI_CATALOG[primary]["label"],
        "primary_fmt": M.KPI_CATALOG[primary]["fmt"], "primary": primary_s,
    }


# ----------------------------------------------------------------------------
# Melhores anuncios
# ----------------------------------------------------------------------------
def _best_ads(meta_cur, limit=6) -> list[dict]:
    if meta_cur.empty:
        return []
    total_spend = meta_cur["spend"].sum()
    min_spend = max(total_spend * 0.01, 20)
    rows = []
    grouped = meta_cur.groupby(
        ["ad_name", "account", "objective", "ad_thumbnail_url", "ad_permalink"], dropna=False)
    empty = pd.DataFrame(columns=["impressions", "clicks", "cost", "conversions", "conversion_value"])
    for (ad, acc, obj, thumb, link), g in grouped:
        if g["spend"].sum() < min_spend:
            continue
        cfg = M.objective_config(obj)
        metric_key = cfg["best_ad_metric"]
        spec = M.KPI_CATALOG[metric_key]
        score = M.kpi_value(g, empty, metric_key)
        rows.append({
            "ad_name": ad, "account": acc, "objective": obj,
            "objective_label": cfg["label"], "thumbnail": thumb, "permalink": link,
            "metric_key": metric_key, "metric_label": spec["label"],
            "metric_fmt": spec["fmt"], "metric_value": round(score, 4),
            "metric_dir": spec["dir"], "spend": round(g["spend"].sum(), 2),
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
# Palavras-chave (Google)
# ----------------------------------------------------------------------------
def _keywords(google_cur, limit=10) -> list[dict]:
    if google_cur.empty:
        return []
    g = google_cur[google_cur["keyword"].astype(str).str.strip() != ""]
    if g.empty:
        return []
    agg = g.groupby("keyword", dropna=False).agg(
        impressions=("impressions", "sum"), clicks=("clicks", "sum"),
        cost=("cost", "sum"), conversions=("conversions", "sum"),
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
            "keyword": r["keyword"], "impressions": int(r["impressions"]),
            "clicks": int(r["clicks"]), "cost": round(r["cost"], 2),
            "conversions": int(r["conversions"]), "ctr": round(r["ctr"], 4),
            "cpc": round(r["cpc"], 2), "cpa": round(r["cpa"], 2), "roas": round(r["roas"], 2),
        })
    return out


# ----------------------------------------------------------------------------
# Campanhas por plataforma (tabela)
# ----------------------------------------------------------------------------
_META_CONV_COL = {
    "conversions": "purchases", "leads": "leads", "messaging": "messaging_conversations",
    "profile_visits": "profile_visits", "video_views": "video_views",
    "link_clicks": "link_clicks", "reach": "reach",
}


def _campaigns(meta_cur, google_cur) -> list[dict]:
    rows = []
    for plat, df, is_meta in [("Meta", meta_cur, True), ("Google", google_cur, False)]:
        if df is None or df.empty:
            continue
        for camp, g in df.groupby("campaign"):
            if not str(camp).strip():
                continue
            objs = g["objective"].mode()
            obj = objs.iloc[0] if len(objs) else "outros"
            cfg = M.objective_config(obj)
            spend = float(g["spend"].sum()) if is_meta else float(g["cost"].sum())
            impr = float(g["impressions"].sum())
            clk = float(g["clicks"].sum())
            if is_meta:
                col = _META_CONV_COL.get(cfg.get("conv_key"))
                conv = float(g[col].sum()) if col and col in g.columns else 0.0
            else:
                conv = float(g["conversions"].sum())
            rows.append({
                "plataforma": plat, "campanha": str(camp),
                "objetivo": cfg["label"], "spend": round(spend, 2),
                "impressions": int(impr), "clicks": int(clk),
                "ctr": round(clk / impr, 4) if impr else 0.0,
                "conversions": round(conv, 1),
                "cpa": round(spend / conv, 2) if conv else 0.0,
            })
    rows.sort(key=lambda r: r["spend"], reverse=True)
    return rows


# ----------------------------------------------------------------------------
# Geo (mapa de calor)
# ----------------------------------------------------------------------------
def _geo(geo_df, scope, start, end) -> dict:
    if geo_df is None or geo_df.empty:
        return {"points": [], "max": 0, "cidades": []}
    df = geo_df
    if scope is not None:
        allowed = (scope.get("meta_ids") or set()) | (scope.get("google_ids") or set())
        df = df[df["account_id"].astype(str).map(_digits).isin(allowed)]
    df = _window(df, start, end)
    if df is None or df.empty:
        return {"points": [], "max": 0, "cidades": []}
    agg = df.groupby(["city", "lat", "lng"], dropna=False)["clicks"].sum().reset_index()
    agg = agg[(agg["clicks"] > 0) & (agg["lat"] != 0)]
    if agg.empty:
        return {"points": [], "max": 0, "cidades": []}
    mx = float(agg["clicks"].max())
    points = [[float(r["lat"]), float(r["lng"]), float(r["clicks"])] for _, r in agg.iterrows()]
    cidades = [{"city": r["city"], "clicks": int(r["clicks"])}
               for _, r in agg.sort_values("clicks", ascending=False).head(10).iterrows()]
    return {"points": points, "max": mx, "cidades": cidades}


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
    return {"meta": block(meta_cur, empty_g), "google": block(empty_m, google_cur)}


def _period_comparison(meta_cur, google_cur, meta_prev, google_prev, history) -> list[dict]:
    keys = ["spend", "impressions", "clicks", "ctr", "cpc", "conversions", "revenue", "cpa"]
    out = []
    for key in keys:
        if M.KPI_CATALOG[key]["base"] not in ("spend", "impressions", "clicks") \
           and history.get(M.KPI_CATALOG[key]["base"], 0) <= 0:
            continue
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

    if scope is not None:
        meta_ids = scope.get("meta_ids") or set()
        google_ids = scope.get("google_ids") or set()
        if "account_id" in meta.columns:
            meta = meta[meta["account_id"].astype(str).map(_digits).isin(meta_ids)]
        if "account_id" in google.columns:
            google = google[google["account_id"].astype(str).map(_digits).isin(google_ids)]

    contas_visiveis = sorted(set(meta["account"]).union(set(google["account"])))

    if account and account != "todas":
        meta = meta[meta["account"] == account]
        google = google[google["account"] == account]

    # historico completo (escopo+conta), p/ ocultar metricas sem historico
    meta_all, google_all = meta.copy(), google.copy()

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
        google_all = google_all.iloc[0:0]
    elif platform == "google":
        meta_cur = meta_cur.iloc[0:0]; meta_prev = meta_prev.iloc[0:0]
        meta_all = meta_all.iloc[0:0]

    history = M.sums(meta_all, google_all)
    blocks = _objective_blocks(meta_cur, google_cur, meta_prev, google_prev, meta_all, google_all)
    primary_obj = blocks[0]["objective"] if blocks else "outros"
    cfg = M.objective_config(primary_obj)
    has_conv_hist = history.get(cfg.get("conv_key", "conversions"), 0) > 0

    return {
        "vazio": False,
        "filtros": {"account": account, "platform": platform, "days": days},
        "periodo": {
            "inicio": _fmt_date(start), "fim": _fmt_date(end),
            "anterior_inicio": _fmt_date(prev_start), "anterior_fim": _fmt_date(prev_end),
        },
        "contas": contas_visiveis,
        "funil": _funnel(meta_cur, google_cur, cfg, has_conv_hist),
        "blocos_objetivo": blocks,
        "serie_temporal": _time_series(meta_cur, google_cur, primary_obj),
        "melhores_anuncios": _best_ads(meta_cur),
        "palavras_chave": _keywords(google_cur),
        "campanhas": _campaigns(meta_cur, google_cur),
        "geo": _geo(store.geo, scope, start, end),
        "comparativo_plataforma": _platform_comparison(meta_cur, google_cur),
        "comparativo_periodo": _period_comparison(meta_cur, google_cur, meta_prev, google_prev, history),
    }
