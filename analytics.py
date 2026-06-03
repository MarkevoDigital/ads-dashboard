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
def _funnel(meta_cur, google_cur) -> dict:
    """Impressoes -> Cliques -> (cada tipo de conversao com valor no periodo).

    Mostra uma etapa por desfecho que o cliente realmente teve no periodo
    (Conversoes, Leads, Conversas, Visitas, Views) — zerados sao omitidos.
    Taxas = razao entre etapas consecutivas (CTR, taxa de conversao, etc.).
    """
    s = M.sums(meta_cur, google_cur)
    clicks = s["clicks"]
    seq = []
    if s["impressions"] > 0:
        seq.append(("Impressões", round(s["impressions"])))
    seq.append(("Cliques", round(clicks)))
    # desfechos de conversao, na ordem; so entram se > 0 no periodo
    for label, val in [("Conversões", s["conversions"]), ("Leads", s["leads"]),
                       ("Conversas", s["messaging"])]:
        if val and val > 0:
            seq.append((label, round(val)))

    stages = [{"label": lb, "value": v, "fmt": "int"} for lb, v in seq]
    # taxas: CTR (impr->cliques) e, para cada desfecho, % sobre os cliques
    rates = []
    for i in range(len(seq) - 1):
        prev_lb, prev_v = seq[i]
        nxt_lb, nxt_v = seq[i + 1]
        if prev_lb == "Impressões" and nxt_lb == "Cliques":
            rates.append({"label": "CTR", "value": round((nxt_v / prev_v) if prev_v else 0.0, 4)})
        else:
            rates.append({"label": f"Taxa de {nxt_lb.lower()}",
                          "value": round((nxt_v / clicks) if clicks else 0.0, 4)})
    return {"stages": stages, "rates": rates}


# ----------------------------------------------------------------------------
# Blocos por objetivo (KPIs adaptativos, ocultando zerados sem historico)
# ----------------------------------------------------------------------------
def _is_zero(value, fmt) -> bool:
    """True se o valor exibido seria zero (respeita o arredondamento de cada formato)."""
    if fmt == "int":
        return round(value) == 0
    if fmt == "pct":
        return round(value * 100, 2) == 0
    return round(value, 2) == 0  # currency, ratio, dec


def _objective_blocks(meta_cur, google_cur, meta_prev, google_prev) -> list[dict]:
    objs = sorted(set(meta_cur["objective"]).union(set(google_cur["objective"])))
    blocks = []
    for obj in objs:
        cfg = M.objective_config(obj)
        conv_key = cfg.get("conv_key")
        mc = meta_cur[meta_cur["objective"] == obj]
        gc = google_cur[google_cur["objective"] == obj]
        mp = meta_prev[meta_prev["objective"] == obj]
        gp = google_prev[google_prev["objective"] == obj]
        if mc.empty and gc.empty:
            continue
        spend = round(M.kpi_value(mc, gc, "spend"), 2)
        if spend <= 0:
            continue
        # conv_key faz o Google contar no bucket do objetivo (ex.: leads = leads Meta +
        # conversoes Google) — corrige "leads zerados" em contas so-Google.
        cur = M.compute_kpis(mc, gc, cfg["kpis"], conv_key)
        prev = M.compute_kpis(mp, gp, cfg["kpis"], conv_key)
        cards = []
        for key in cfg["kpis"]:
            c = cur[key]
            # OCULTAR zerados: investimento sempre aparece; os demais so com valor no periodo.
            if key != "spend" and _is_zero(c["value"], c["fmt"]):
                continue
            p = prev[key]
            delta = M.pct_change(c["value"], p["value"])
            cards.append({
                **c, "prev_value": p["value"], "delta_pct": delta,
                "good": M.is_good(c["dir"], delta),
                "is_primary": key == cfg["primary"],
            })
        if not cards:
            continue
        blocks.append({
            "objective": obj, "label": cfg["label"], "icone": cfg["icone"],
            "primary": cfg["primary"], "spend": spend, "cards": cards,
        })
    blocks.sort(key=lambda b: b["spend"], reverse=True)
    return blocks


# ----------------------------------------------------------------------------
# Serie temporal
# ----------------------------------------------------------------------------
def _time_series(meta_cur, google_cur) -> dict:
    """Evolucao diaria: Investimento (barra) x Cliques e Conversoes (linhas).

    Conversoes = soma de todos os desfechos (conversoes + leads + conversas).
    """
    days = sorted(set(meta_cur["date"]).union(set(google_cur["date"])))
    labels, spend_s, clicks_s, conv_s = [], [], [], []
    for d in days:
        md = meta_cur[meta_cur["date"] == d]
        gd = google_cur[google_cur["date"] == d]
        s = M.sums(md, gd)
        labels.append(_fmt_date(d))
        spend_s.append(round(s["spend"], 2))
        clicks_s.append(int(round(s["clicks"])))
        conv_s.append(round(s["conversions"] + s["leads"] + s["messaging"], 1))
    return {
        "labels": labels, "spend": spend_s, "clicks": clicks_s,
        "conversions": conv_s, "tem_conversoes": sum(conv_s) > 0,
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
    empty = pd.DataFrame(columns=["impressions", "clicks", "cost", "conversions", "conversion_value"])
    # Unifica anuncios com o MESMO nome (na mesma conta). A Meta gera ad_ids/thumbnails
    # distintos para copias do mesmo criativo (URLs assinadas diferentes); agrupar so por
    # nome+conta junta esses dados em vez de mostrar linhas duplicadas.
    for (ad, acc), g in meta_cur.groupby(["ad_name", "account"], dropna=False):
        if not str(ad).strip():
            continue
        if g["spend"].sum() < min_spend:
            continue
        objs = g["objective"].mode()
        obj = objs.iloc[0] if len(objs) else "outros"
        thumbs = [t for t in g["ad_thumbnail_url"].astype(str) if t and t.lower() != "nan"]
        thumb = thumbs[0] if thumbs else ""
        links = [l for l in g["ad_permalink"].astype(str) if l and l.lower() != "nan"]
        link = links[0] if links else ""
        cfg = M.objective_config(obj)
        # HEROI = numero de resultados do objetivo (conversoes/leads/conversas/views/...)
        result_key = cfg["conv_key"]
        result_spec = M.KPI_CATALOG[result_key]
        result_value = M.kpi_value(g, empty, result_key)
        # SECUNDARIA = eficiencia por resultado (custo por resultado / ROAS do objetivo)
        eff_key = cfg["best_ad_metric"]
        eff_spec = M.KPI_CATALOG[eff_key]
        eff_value = M.kpi_value(g, empty, eff_key)
        rows.append({
            "ad_name": ad, "account": acc, "objective": obj,
            "objective_label": cfg["label"], "thumbnail": thumb, "permalink": link,
            # metrica em destaque = numero de resultados
            "result_key": result_key, "result_label": result_spec["label"],
            "result_fmt": result_spec["fmt"], "result_value": round(result_value, 4),
            # metrica de eficiencia (secundaria)
            "eff_key": eff_key, "eff_label": eff_spec["label"],
            "eff_fmt": eff_spec["fmt"], "eff_value": round(eff_value, 4),
            "spend": round(g["spend"].sum(), 2),
            "impressions": int(g["impressions"].sum()),
            "ctr": round(M.kpi_value(g, empty, "ctr"), 4),
        })
    # ordena pelo numero de resultados (mais resultados = melhor anuncio)
    rows.sort(key=lambda r: r["result_value"], reverse=True)
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
                video = float(g["video_views"].sum()) if "video_views" in g.columns else 0.0
                ig_visits = float(g["profile_visits"].sum()) if "profile_visits" in g.columns else 0.0
                eng = float(g["engagement"].sum()) if "engagement" in g.columns else 0.0
            else:
                conv = float(g["conversions"].sum())
                video = float(g["video_views"].sum()) if "video_views" in g.columns else 0.0
                ig_visits = 0.0  # Google nao tem visitas ao Instagram
                eng = 0.0        # Google nao tem engajamento (tem interacoes)
            rows.append({
                "plataforma": plat, "campanha": str(camp),
                "objetivo": cfg["label"], "spend": round(spend, 2),
                "impressions": int(impr), "clicks": int(clk),
                "ctr": round(clk / impr, 4) if impr else 0.0,
                "conversions": round(conv, 1),
                "cpa": round(spend / conv, 2) if conv else 0.0,
                "video_views": int(video), "profile_visits": int(ig_visits),
                "engagement": int(eng),
            })
    rows.sort(key=lambda r: r["spend"], reverse=True)
    return rows


# ----------------------------------------------------------------------------
# Geo (mapa de calor)
# ----------------------------------------------------------------------------
def _geo(geo_df, scope, start, end, level="estado") -> dict:
    empty = {"points": [], "max": 0, "cidades": []}
    if geo_df is None or geo_df.empty:
        return empty
    df = geo_df
    if "level" in df.columns:
        df = df[df["level"] == level]
    if scope is not None:
        allowed = (scope.get("meta_ids") or set()) | (scope.get("google_ids") or set())
        df = df[df["account_id"].astype(str).map(_digits).isin(allowed)]
    df = _window(df, start, end)
    if df is None or df.empty:
        return empty
    agg = df.groupby(["city", "lat", "lng"], dropna=False)["clicks"].sum().reset_index()
    agg = agg[agg["clicks"] > 0]
    if agg.empty:
        return empty
    # ranking (lista) inclui TODAS as localidades; o mapa so plota as que tem coordenada.
    rank = agg.groupby("city")["clicks"].sum().reset_index().sort_values("clicks", ascending=False)
    cidades = [{"city": r["city"], "clicks": int(r["clicks"])} for _, r in rank.head(12).iterrows()]
    pts = agg[agg["lat"] != 0]
    mx = float(pts["clicks"].max()) if len(pts) else 0
    points = [[float(r["lat"]), float(r["lng"]), float(r["clicks"])] for _, r in pts.iterrows()]
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
    keys = ["spend", "impressions", "clicks", "ctr", "cpc", "conversions",
            "video_views", "profile_visits", "engagement", "revenue", "cpa"]
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
def build_payload(store, account="todas", platform="todas", days=30, scope=None,
                  start=None, end=None) -> dict:
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

    # Janela: intervalo explicito (mes/personalizado) tem prioridade sobre "ultimos N dias".
    rng = None
    if start and end:
        try:
            rng_start, rng_end = pd.Timestamp(start), pd.Timestamp(end)
            if rng_end >= rng_start:
                rng = (rng_start, rng_end)
        except (ValueError, TypeError):
            rng = None
    if rng:
        start, end = rng
        win = (end - start).days + 1
    else:
        end = max(all_dates)
        start = end - pd.Timedelta(days=days - 1)
        win = days
    prev_end = start - pd.Timedelta(days=1)
    prev_start = prev_end - pd.Timedelta(days=win - 1)

    meta_cur, google_cur = _window(meta, start, end), _window(google, start, end)
    meta_prev, google_prev = _window(meta, prev_start, prev_end), _window(google, prev_start, prev_end)

    if platform == "meta":
        google_cur = google_cur.iloc[0:0]; google_prev = google_prev.iloc[0:0]
        google_all = google_all.iloc[0:0]
    elif platform == "google":
        meta_cur = meta_cur.iloc[0:0]; meta_prev = meta_prev.iloc[0:0]
        meta_all = meta_all.iloc[0:0]

    history = M.sums(meta_all, google_all)
    blocks = _objective_blocks(meta_cur, google_cur, meta_prev, google_prev)

    return {
        "vazio": False,
        "filtros": {"account": account, "platform": platform, "days": days},
        "periodo": {
            "inicio": _fmt_date(start), "fim": _fmt_date(end),
            "anterior_inicio": _fmt_date(prev_start), "anterior_fim": _fmt_date(prev_end),
        },
        "contas": contas_visiveis,
        "funil": _funnel(meta_cur, google_cur),
        "blocos_objetivo": blocks,
        "serie_temporal": _time_series(meta_cur, google_cur),
        "melhores_anuncios": _best_ads(meta_cur),
        "palavras_chave": _keywords(google_cur),
        "campanhas": _campaigns(meta_cur, google_cur),
        "geo": _geo(store.geo, scope, start, end, "estado"),
        "geo_cidades": _geo(store.geo, scope, start, end, "cidade"),
        "comparativo_plataforma": _platform_comparison(meta_cur, google_cur),
        "comparativo_periodo": _period_comparison(meta_cur, google_cur, meta_prev, google_prev, history),
    }
