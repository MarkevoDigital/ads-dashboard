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

import os

import pandas as pd

import metrics as M
import i18n
from tz_br import today_br


def _window(df, start, end):
    if df is None or df.empty:
        return df
    return df[(df["date"] >= start) & (df["date"] <= end)]


def _junta(a, b):
    """Concatena duas fontes no schema do Meta ignorando as vazias. TikTok e LinkedIn
    entram JUNTOS nas somas (a matematica e a mesma); so as funcoes que rotulam por
    plataforma recebem cada um separado."""
    frames = [x for x in (a, b) if x is not None and not x.empty]
    if not frames:
        return a if a is not None else b
    return frames[0] if len(frames) == 1 else pd.concat(frames, ignore_index=True)


def _fmt_date(ts):
    return pd.Timestamp(ts).strftime("%Y-%m-%d")


def _digits(v):
    return "".join(ch for ch in str(v) if ch.isdigit())


# ----------------------------------------------------------------------------
# Funil
# ----------------------------------------------------------------------------
# Etapas possiveis do funil: chave (igual a de M.sums) -> rotulo exibido.
_FUNNEL_LABELS = {
    "impressions": "Impressões",
    "video_views": "Visualizações de vídeo",
    "clicks": "Cliques",
    "engagement": "Engajamentos",
    "registrations": "Inscrições",
    "profile_visits": "Visitas ao perfil",
    "leads": "Leads",
    "messaging": "Conversas",
    "conversions": "Conversões",
    # E-commerce
    "add_to_cart": "Adições ao carrinho",
    "initiate_checkout": "Checkouts iniciados",
    "purchases": "Compras",
}

# Cadeia de e-commerce: cada etapa converte da ANTERIOR (carrinho dos cliques,
# checkout dos carrinhos, compra dos checkouts) — nao dos cliques como as demais.
_ECOM_RATES = {
    "add_to_cart": "Taxa de carrinho",
    "initiate_checkout": "Taxa de checkout",
    "purchases": "Taxa de compra",
}
# Ordem padrao (preserva o comportamento historico do dashboard).
_FUNNEL_DEFAULT = ["impressions", "clicks", "conversions", "leads", "messaging",
                   "profile_visits", "video_views"]

# Metrica de custo de cada etapa (rotulo + funcao sobre os sums). Usa o investimento
# TOTAL (mesma convencao dos KPIs de destaque do dashboard). CPM = custo por mil impressoes.
_FUNNEL_COST = {
    "impressions":    ("CPM",            lambda s: (s["spend"] / s["impressions"] * 1000) if s["impressions"] else 0.0),
    "video_views":    ("Custo/view",     lambda s: (s["spend"] / s["video_views"]) if s["video_views"] else 0.0),
    "clicks":         ("CPC",            lambda s: (s["spend"] / s["clicks"]) if s["clicks"] else 0.0),
    "engagement":     ("Custo/engajamento", lambda s: (s["spend"] / s["engagement"]) if s.get("engagement") else 0.0),
    "registrations":  ("Custo/inscrição", lambda s: (s["spend"] / s["registrations"]) if s.get("registrations") else 0.0),
    "profile_visits": ("Custo/visita",   lambda s: (s["spend"] / s["profile_visits"]) if s["profile_visits"] else 0.0),
    "conversions":    ("CPA",            lambda s: (s["spend"] / s["conversions"]) if s["conversions"] else 0.0),
    "leads":          ("CPL",            lambda s: (s["spend"] / s["leads"]) if s["leads"] else 0.0),
    "messaging":      ("Custo/conversa", lambda s: (s["spend"] / s["messaging"]) if s["messaging"] else 0.0),
    "add_to_cart":    ("Custo/carrinho",  lambda s: (s["spend"] / s["add_to_cart"]) if s.get("add_to_cart") else 0.0),
    "initiate_checkout": ("Custo/checkout", lambda s: (s["spend"] / s["initiate_checkout"]) if s.get("initiate_checkout") else 0.0),
    "purchases":      ("Custo/compra",   lambda s: (s["spend"] / s["purchases"]) if s.get("purchases") else 0.0),
}


# Etapa de DESFECHO do funil -> objetivo de campanha que a justifica.
_ETAPA_OBJETIVO = {
    "messaging": {"mensagens"},
    # Lead tambem nasce de campanha de CONVERSAO: "[LEADS] [SITE] PREVENT MASTER"
    # otimiza por conversao offsite e cai no bucket "vendas", mas gera lead de verdade.
    # O mapa e generoso de proposito -- ele existe para tirar o desfecho ORFAO, nao
    # para brigar com a classificacao de objetivo.
    "leads": {"leads", "vendas"},
    "profile_visits": {"visitas_instagram", "trafego", "engajamento"},
    "add_to_cart": {"vendas"},
    "registrations": {"vendas", "leads"},
    "initiate_checkout": {"vendas"},
    "purchases": {"vendas"},
}
# Impressoes, cliques, video e engajamento ficam FORA do mapa de proposito: sao
# subproduto de qualquer veiculacao (todo anuncio gera impressao, todo criativo em
# video gera view), entao nao dependem do objetivo da campanha.


def _funnel_order(ordem=None):
    """Ordem das etapas do funil — configuravel por deploy via env FUNIL_ORDEM
    (chaves de _FUNNEL_LABELS separadas por virgula). Ex.:
      FUNIL_ORDEM=impressions,video_views,clicks,profile_visits,leads,messaging
    Chaves invalidas sao ignoradas; sem a env, usa a ordem padrao.

    Uma ordem vinda do PROPRIO CLIENTE (clients.json -> "funil_ordem") tem
    prioridade: assim uma loja e um cliente de leads convivem no mesmo deploy,
    cada um com o seu funil."""
    if ordem:
        if isinstance(ordem, str):
            ordem = ordem.split(",")
        keys = [str(k).strip() for k in ordem if str(k).strip() in _FUNNEL_LABELS]
        if keys:
            return keys
    raw = os.environ.get("FUNIL_ORDEM", "").strip()
    if not raw:
        return _FUNNEL_DEFAULT
    keys = [k.strip() for k in raw.split(",") if k.strip() in _FUNNEL_LABELS]
    return keys or _FUNNEL_DEFAULT


def _funnel(meta_cur, google_cur, tiktok_cur=None, ig_novos=0.0, ordem=None) -> dict:
    """Funil de resultados. Cada etapa entra so se tiver valor no periodo (cliques
    sempre aparece). A ORDEM e configuravel por deploy (FUNIL_ORDEM), entao cada
    agencia prioriza etapas diferentes sem alterar codigo.

    Taxas: CTR = cliques/impressoes; Taxa de visualizacao = views/impressoes (views
    vem das impressoes, nao dos cliques); demais desfechos = valor/cliques.
    """
    s = M.sums(meta_cur, google_cur, tiktok_cur)
    clicks = s["clicks"]
    # Alguma campanha do periodo tem mensagens como objetivo? O custo por conversa
    # divide o investimento do periodo INTEIRO pelas conversas; sem campanha de
    # mensagem, uma conversa acidental de campanha de video vira "custo/conversa" =
    # conta toda. Nesse caso mostramos a contagem (resultado real) e omitimos o custo.
    msg_e_objetivo = any(
        "mensagens" in set(df["objective"].dropna().unique())
        for df in (meta_cur, google_cur, tiktok_cur)
        if df is not None and not df.empty and "objective" in df.columns)
    impr = round(s["impressions"])
    # Sem ordem propria do cliente, o funil segue as CAMPANHAS do periodo: etapa de
    # desfecho so entra se existe campanha com aquele objetivo. Sem isso, uma conversa
    # acidental numa conta que so roda visita ao perfil virava etapa do funil. Objetivo
    # "outros" (nao identificado) desliga o filtro, para nunca esconder dado real.
    objetivos = set()
    for df in (meta_cur, google_cur, tiktok_cur):
        if df is not None and not df.empty and "objective" in df.columns:
            objetivos |= set(df["objective"].dropna().unique())
    # Atencao: cliente sem funil proprio chega aqui com [] (nao None), entao a
    # checagem e por truthiness -- lista vazia = usa o padrao = filtra.
    filtrar = not ordem and "outros" not in objetivos

    seq = []  # (key, label, value)
    for key in _funnel_order(ordem):
        val = round(s.get(key, 0))
        if filtrar and key in _ETAPA_OBJETIVO and not (_ETAPA_OBJETIVO[key] & objetivos):
            continue
        # Cliques entra mesmo zerado (ancora do funil), mas so quando houve veiculacao:
        # cliente sem anuncio no periodo e so com Instagram mostrava "Cliques 0 / CPC
        # R$ 0,00" antes dos seguidores.
        if val > 0 or (key == "clicks" and impr > 0):
            seq.append((key, _FUNNEL_LABELS[key], val))

    # Visualizacoes de video ficam logo abaixo das impressoes, em qualquer ordem
    # configurada: a taxa de visualizacao sai delas (e o CTR seguinte tambem).
    chaves = [k for k, _, _ in seq]
    if "video_views" in chaves and "impressions" in chaves:
        vv = seq.pop(chaves.index("video_views"))
        seq.insert([k for k, _, _ in seq].index("impressions") + 1, vv)

    stages = []
    for (k, lb, v) in seq:
        st = {"label": lb, "value": v, "fmt": "int"}
        cost = _FUNNEL_COST.get(k)
        if k == "messaging" and not msg_e_objetivo:
            cost = None
        if cost:
            st["cost_label"] = cost[0]
            st["cost"] = round(cost[1](s), 2)
        stages.append(st)
    rates = []
    for i in range(len(seq) - 1):
        nkey, nlb, nv = seq[i + 1]
        if nkey == "clicks":
            rates.append({"label": "CTR", "value": round((nv / impr) if impr else 0.0, 4)})
        elif nkey == "engagement":
            # Engajamento sai das IMPRESSOES, como a taxa de visualizacao: dividir
            # pelos cliques daria taxa acima de 100% quase sempre (curtida, comentario
            # e compartilhamento nao exigem clique).
            rates.append({"label": "Taxa de engajamento",
                          "value": round((nv / impr) if impr else 0.0, 4)})
        elif nkey == "video_views":
            rates.append({"label": "Taxa de visualização",
                          "value": round((nv / impr) if impr else 0.0, 4)})
        elif nkey in _ECOM_RATES:
            # Converte da etapa ANTERIOR do funil de loja (checkout/carrinho, compra/
            # checkout). A cadeia comeca nos CLIQUES: num funil misto (engajamento +
            # venda), o carrinho que vem depois de "Engajamentos" nao divide por eles.
            pkey, _, pv = seq[i]
            if pkey not in _ECOM_RATES:
                pv = clicks
            rates.append({"label": _ECOM_RATES[nkey],
                          "value": round((nv / pv) if pv else 0.0, 4)})
        else:
            rates.append({"label": f"Taxa de {nlb.lower()}",
                          "value": round((nv / clicks) if clicks else 0.0, 4)})

    # Novos seguidores do Instagram: entra como ULTIMA etapa, quando houver. Fica FORA
    # das taxas e sem custo de proposito — o numero e da CONTA inteira (anuncios +
    # organico) e a API de Ads nao atribui seguidores por campanha, entao dividi-lo
    # pelos cliques daria uma "taxa de conversao" falsa. O rotulo deixa isso explicito.
    if ig_novos and round(ig_novos) > 0:
        stages.append({"label": "Novos seguidores (conta)", "value": round(ig_novos),
                       "fmt": "int", "organico": True})
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


def _objective_blocks(meta_cur, google_cur, meta_prev, google_prev,
                      tiktok_cur=None, tiktok_prev=None) -> list[dict]:
    tk_objs = set(tiktok_cur["objective"]) if tiktok_cur is not None and not tiktok_cur.empty else set()
    objs = sorted(set(meta_cur["objective"]).union(set(google_cur["objective"])).union(tk_objs))
    empty_tk = tiktok_cur.iloc[0:0] if tiktok_cur is not None else None
    blocks = []
    for obj in objs:
        cfg = M.objective_config(obj)
        conv_key = cfg.get("conv_key")
        mc = meta_cur[meta_cur["objective"] == obj]
        gc = google_cur[google_cur["objective"] == obj]
        mp = meta_prev[meta_prev["objective"] == obj]
        gp = google_prev[google_prev["objective"] == obj]
        tc = tiktok_cur[tiktok_cur["objective"] == obj] if tiktok_cur is not None else empty_tk
        tp = tiktok_prev[tiktok_prev["objective"] == obj] if tiktok_prev is not None else empty_tk
        if mc.empty and gc.empty and (tc is None or tc.empty):
            continue
        spend = round(M.kpi_value(mc, gc, "spend", tc), 2)
        if spend <= 0:
            continue
        # conv_key faz o Google contar no bucket do objetivo (ex.: leads = leads Meta +
        # conversoes Google) — corrige "leads zerados" em contas so-Google.
        cur = M.compute_kpis(mc, gc, cfg["kpis"], conv_key, tc)
        prev = M.compute_kpis(mp, gp, cfg["kpis"], conv_key, tp)
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
def _time_series(meta_cur, google_cur, tiktok_cur=None, start=None, end=None) -> dict:
    """Evolucao diaria: Investimento (barra) x Cliques e Conversoes (linhas).

    Conversoes = soma de todos os desfechos (conversoes + leads + conversas).

    Quando start/end sao dados (janela "ultimos N dias"), percorre TODOS os dias do
    intervalo de calendario — os dias sem entrega aparecem zerados, em vez de sumirem do
    grafico (casa com a predefinicao de datas por calendario, mesmo com dados atrasados).
    """
    if start is not None and end is not None:
        days = list(pd.date_range(pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize(), freq="D"))
    else:
        tk_days = set(tiktok_cur["date"]) if tiktok_cur is not None and not tiktok_cur.empty else set()
        days = sorted(set(meta_cur["date"]).union(set(google_cur["date"])).union(tk_days))
    labels, spend_s, clicks_s, conv_s = [], [], [], []
    for d in days:
        md = meta_cur[meta_cur["date"] == d]
        gd = google_cur[google_cur["date"] == d]
        td = tiktok_cur[tiktok_cur["date"] == d] if tiktok_cur is not None else None
        s = M.sums(md, gd, td)
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
# LinkedIn so roda alcance e engajamento, e a API dele NAO informa alcance por dia
# (reach vem 0). O destaque de alcance usa entao impressoes + CPM; engajamento ja usa
# engajamentos + custo por engajamento, que o LinkedIn entrega.
_DESTAQUE_LINKEDIN = {
    "alcance": ("impressions", "cpm"),
    "engajamento": ("engagement", "cost_per_engagement"),
}


def _best_ads(meta_cur, limit=6, destaque=None) -> list[dict]:
    """destaque: {objetivo: (metrica_resultado, metrica_eficiencia)} para plataformas
    cujo resultado padrao do objetivo nao existe na API (ex.: alcance no LinkedIn)."""
    if meta_cur is None or meta_cur.empty:
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
        result_key, eff_key = (destaque or {}).get(obj, (cfg["conv_key"], cfg["best_ad_metric"]))
        result_spec = M.KPI_CATALOG[result_key]
        result_value = M.kpi_value(g, empty, result_key)
        # Sem resultado nao e destaque: o anuncio so lidera porque a lista ordena por
        # resultado e ninguem pontuou no periodo. Vale para o card do Meta e para o da
        # secao TikTok (as duas usam esta funcao); os comentarios ja aplicavam a regra.
        if result_value <= 0:
            continue
        # SECUNDARIA = eficiencia por resultado (custo por resultado / ROAS do objetivo)
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
    kw = google_cur["keyword"].astype(str).str.strip()
    g = google_cur[~kw.isin(["", "nan", "NaN", "None"])]
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


def _campaigns(meta_cur, google_cur, tiktok_cur=None, linkedin_cur=None) -> list[dict]:
    rows = []
    # TikTok usa o schema do Meta -> agrega como "meta" (is_meta=True).
    sources = [("Meta", meta_cur, True), ("Google", google_cur, False),
               ("TikTok", tiktok_cur, True), ("LinkedIn", linkedin_cur, True)]
    for plat, df, is_meta in sources:
        if df is None or df.empty:
            continue
        spend_col = "spend" if is_meta else "cost"
        # "Em veiculacao" = teve entrega no dia mais recente DESTA plataforma (Meta e Google
        # podem ter datas finais diferentes; usar a data global marcaria Meta como inativo).
        last = df["date"].max()
        for camp, g in df.groupby("campaign"):
            if not str(camp).strip():
                continue
            objs = g["objective"].mode()
            obj = objs.iloc[0] if len(objs) else "outros"
            cfg = M.objective_config(obj)
            spend = float(g["spend"].sum()) if is_meta else float(g["cost"].sum())
            impr = float(g["impressions"].sum())
            # Sem veiculacao na janela escolhida -> fora da tabela. Campanha pausada
            # continua aparecendo desde que tenha tido impressao no periodo; o que sai
            # sao as linhas zeradas, que so poluem a leitura. Mesma regra que a tabela de
            # anuncios ja aplica. O custo entra na condicao para nunca esconder dinheiro
            # gasto (e manter a soma da tabela igual ao KPI de investimento).
            if impr <= 0 and spend <= 0:
                continue
            clk = float(g["clicks"].sum())
            gl = g[g["date"] == last] if last is not None else g.iloc[0:0]
            ativo = bool(len(gl) and (float(gl[spend_col].sum()) > 0
                                      or float(gl["impressions"].sum()) > 0))
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
            budget = float(g["daily_budget"].max()) if "daily_budget" in g.columns else 0.0
            rows.append({
                "plataforma": plat, "campanha": str(camp),
                "objetivo": cfg["label"], "orcamento_diario": round(budget, 2),
                "spend": round(spend, 2),
                "impressions": int(impr), "clicks": int(clk),
                "ctr": round(clk / impr, 4) if impr else 0.0,
                "conversions": round(conv, 1),
                "cpa": round(spend / conv, 2) if conv else 0.0,
                "video_views": int(video), "profile_visits": int(ig_visits),
                "engagement": int(eng), "ativo": ativo,
            })
    # ordena por numero de conversoes (desc); desempate por investimento.
    rows.sort(key=lambda r: (r["conversions"], r["spend"]), reverse=True)
    return rows


def _ad_sets(meta_cur, google_cur, tiktok_cur=None) -> list[dict]:
    """Desempenho por CONJUNTO DE ANUNCIOS (Meta/TikTok = coluna 'adset') e por GRUPO DE
    RECURSOS/ANUNCIOS do Google (coluna 'ad_group' — grupos de anuncio da Pesquisa e grupos
    de recursos da PMax). Mesmo formato das tabelas de campanhas e anuncios; cada linha traz
    a 'campanha' a que o conjunto pertence, para o filtro por campanha no front."""
    rows = []
    sources = [("Meta", meta_cur, True, "adset"), ("Google", google_cur, False, "ad_group"),
               ("TikTok", tiktok_cur, True, "adset")]
    for plat, df, is_meta, gcol in sources:
        if df is None or df.empty or gcol not in df.columns:
            continue
        spend_col = "spend" if is_meta else "cost"
        last = df["date"].max()
        for (camp, conj), g in df.groupby(["campaign", gcol], dropna=False):
            conj = str(conj)
            if conj.strip().lower() in ("", "nan", "none", "—") or not str(camp).strip():
                continue
            objs = g["objective"].mode()
            obj = objs.iloc[0] if len(objs) else "outros"
            cfg = M.objective_config(obj)
            spend = float(g[spend_col].sum())
            impr = float(g["impressions"].sum())
            # Mesma regra das campanhas: conjunto/grupo sem entrega no periodo nao entra.
            if impr <= 0 and spend <= 0:
                continue
            clk = float(g["clicks"].sum())
            gl = g[g["date"] == last] if last is not None else g.iloc[0:0]
            ativo = bool(len(gl) and (float(gl[spend_col].sum()) > 0
                                      or float(gl["impressions"].sum()) > 0))
            if is_meta:
                col = _META_CONV_COL.get(cfg.get("conv_key"))
                conv = float(g[col].sum()) if col and col in g.columns else 0.0
                video = float(g["video_views"].sum()) if "video_views" in g.columns else 0.0
                ig_visits = float(g["profile_visits"].sum()) if "profile_visits" in g.columns else 0.0
                eng = float(g["engagement"].sum()) if "engagement" in g.columns else 0.0
            else:
                conv = float(g["conversions"].sum())
                video = float(g["video_views"].sum()) if "video_views" in g.columns else 0.0
                ig_visits = 0.0
                eng = 0.0
            rows.append({
                "plataforma": plat, "campanha": str(camp), "conjunto": conj,
                "objetivo": cfg["label"], "spend": round(spend, 2),
                "impressions": int(impr), "clicks": int(clk),
                "ctr": round(clk / impr, 4) if impr else 0.0,
                "conversions": round(conv, 1),
                "cpa": round(spend / conv, 2) if conv else 0.0,
                "video_views": int(video), "profile_visits": int(ig_visits),
                "engagement": int(eng), "ativo": ativo,
            })
    rows.sort(key=lambda r: (r["conversions"], r["spend"]), reverse=True)
    return rows


def _ads(meta_cur, tiktok_cur=None, linkedin_cur=None) -> list[dict]:
    """Anuncios veiculados (Meta e TikTok), agrupados por nome+campanha. Meta e TikTok
    tem dados por anuncio; o Google e nivel campanha/palavra-chave. Mesmo formato da
    tabela de campanhas, com a coluna 'campanha' indicando a campanha do anuncio."""
    rows = []
    for plat, df in [("Meta", meta_cur), ("TikTok", tiktok_cur), ("LinkedIn", linkedin_cur)]:
        if df is None or df.empty:
            continue
        has_adset = "adset" in df.columns
        last = df["date"].max()
        # Agrupa tambem por CONJUNTO (adset): permite o filtro por conjunto na tabela e e
        # mais fiel (um anuncio pode rodar em conjuntos distintos). Sem a coluna, fica "".
        keys = ["ad_name", "campaign", "adset"] if has_adset else ["ad_name", "campaign"]
        for gkey, g in df.groupby(keys, dropna=False):
            ad, camp = gkey[0], gkey[1]
            conjunto = gkey[2] if has_adset else ""
            conjunto = "" if str(conjunto).strip().lower() in ("", "nan", "none", "—") else str(conjunto)
            if not str(ad).strip():
                continue
            impr = float(g["impressions"].sum())
            if impr <= 0:          # "veiculados" = anuncios que tiveram entrega
                continue
            objs = g["objective"].mode()
            obj = objs.iloc[0] if len(objs) else "outros"
            cfg = M.objective_config(obj)
            spend = float(g["spend"].sum())
            clk = float(g["clicks"].sum())
            col = _META_CONV_COL.get(cfg.get("conv_key"))
            conv = float(g[col].sum()) if col and col in g.columns else 0.0
            gl = g[g["date"] == last] if last is not None else g.iloc[0:0]
            ativo = bool(len(gl) and (float(gl["spend"].sum()) > 0 or float(gl["impressions"].sum()) > 0))
            rows.append({
                "plataforma": plat, "anuncio": str(ad), "campanha": str(camp),
                "conjunto": conjunto,
                "objetivo": cfg["label"], "spend": round(spend, 2),
                "impressions": int(impr), "clicks": int(clk),
                "ctr": round(clk / impr, 4) if impr else 0.0,
                "conversions": round(conv, 1),
                "cpa": round(spend / conv, 2) if conv else 0.0,
                "video_views": int(g["video_views"].sum()) if "video_views" in g.columns else 0,
                "profile_visits": int(g["profile_visits"].sum()) if "profile_visits" in g.columns else 0,
                "engagement": int(g["engagement"].sum()) if "engagement" in g.columns else 0,
                "ativo": ativo,
            })
    rows.sort(key=lambda r: (r["conversions"], r["spend"]), reverse=True)
    return rows


# ----------------------------------------------------------------------------
# Instagram (organico): seguidores
# ----------------------------------------------------------------------------
def _ig_novos(ig_df, start, end) -> float:
    """Novos seguidores no periodo (soma de todas as contas de IG do escopo)."""
    if ig_df is None or ig_df.empty:
        return 0.0
    win = _window(ig_df, start, end)
    if win is None or win.empty:
        return 0.0
    return float(win["new_followers"].sum())


def _instagram(ig_df, scope, start, end) -> dict:
    """Total de seguidores, novos no periodo e crescimento — por conta e consolidado.

    'total' e um SNAPSHOT do momento da coleta (a API nao devolve historico do total),
    entao nao depende da janela; 'novos' e a soma do periodo filtrado. O crescimento
    compara os novos com a base estimada no inicio do periodo (total - novos)."""
    vazio = {"contas": [], "total": 0, "novos": 0, "crescimento": 0.0, "serie": {"labels": [], "novos": []}}
    if ig_df is None or ig_df.empty:
        return vazio
    df = ig_df
    if scope is not None:
        permitidos = scope.get("instagram_ids") or set()
        df = df[df["ig_id"].astype(str).map(_digits).isin(permitidos)]
    if df.empty:
        return vazio
    win = _window(df, start, end)
    if win is None or win.empty:
        return vazio

    contas = []
    for ig_id, g in win.groupby("ig_id", dropna=False):
        novos = float(g["new_followers"].sum())
        total = float(g["followers_total"].max())
        base = total - novos
        contas.append({
            "ig_id": str(ig_id),
            "username": str(g["username"].iloc[0]),
            "conta": str(g["account"].iloc[0]),
            "total": int(round(total)),
            "novos": int(round(novos)),
            "crescimento": round((novos / base * 100.0), 2) if base > 0 else 0.0,
        })
    contas.sort(key=lambda c: -c["total"])

    total = sum(c["total"] for c in contas)
    novos = sum(c["novos"] for c in contas)
    base = total - novos
    dia = win.groupby("date", dropna=False)["new_followers"].sum().reset_index().sort_values("date")
    return {
        "contas": contas,
        "total": total,
        "novos": novos,
        "crescimento": round((novos / base * 100.0), 2) if base > 0 else 0.0,
        "serie": {
            "labels": [_fmt_date(d) for d in dia["date"]],
            "novos": [int(round(v)) for v in dia["new_followers"]],
        },
    }


# ----------------------------------------------------------------------------
# Canais de veiculacao (Facebook/Instagram/WhatsApp, Pesquisa/PMax/YouTube...)
# ----------------------------------------------------------------------------
# O TikTok aparece por SISTEMA, nao por posicionamento: a API da v1.3 nao tem
# dimensao de placement (ver connectors/tiktok_api.py).
_CANAL_PLATAFORMA = {"meta": "Meta Ads", "google": "Google Ads",
                     "tiktok": "TikTok Ads — por sistema", "linkedin": "LinkedIn Ads"}


def _canais(canais_df, scope, start, end, platform="todas") -> list:
    """Impressoes, cliques e conversoes por canal, agrupados por plataforma.

    Uma lista por plataforma para o front desenhar um grafico de cada, porque as
    escalas nao se comparam (Pesquisa e Facebook nao dividem eixo)."""
    if canais_df is None or canais_df.empty:
        return []
    df = canais_df
    if platform in ("meta", "google", "tiktok", "linkedin") and "platform" in df.columns:
        df = df[df["platform"] == platform]
    if scope is not None:
        allowed = ((scope.get("meta_ids") or set()) | (scope.get("google_ids") or set())
                   | (scope.get("tiktok_ids") or set()))
        df = df[df["account_id"].astype(str).map(_digits).isin(allowed)]
    df = _window(df, start, end)
    if df is None or df.empty:
        return []
    saida = []
    for plat in ("meta", "google", "tiktok", "linkedin"):
        sub = df[df["platform"] == plat]
        if sub.empty:
            continue
        g = (sub.groupby("canal")[["impressions", "clicks", "conversions", "spend"]]
             .sum().sort_values("impressions", ascending=False))
        itens = [{"canal": str(canal),
                  "impressions": int(round(float(r["impressions"]))),
                  "clicks": int(round(float(r["clicks"]))),
                  "conversions": int(round(float(r["conversions"]))),
                  "spend": round(float(r["spend"]), 2)}
                 for canal, r in g.iterrows()
                 if float(r["impressions"]) > 0 or float(r["clicks"]) > 0]
        if itens:
            saida.append({"plataforma": plat, "label": _CANAL_PLATAFORMA.get(plat, plat.title()),
                          "itens": itens})
    return saida


# ----------------------------------------------------------------------------
# Seguidores anotados a mao (rede sem API liberada)
# ----------------------------------------------------------------------------
def _seguidores_escopo(scope, start, end) -> dict:
    """Seguidores da Pagina (LinkedIn, seguidores_manuais.json) do que o login enxerga:
    o proprio cliente, os clientes de uma agencia de grupo ou, no admin, todos. Sem
    isso o admin nunca via o bloco (nao tem cliente_key). Varios registros somam total
    e novos. Import tardio: data_sources nao importa analytics."""
    vazio = {"tem": False}
    try:
        from data_sources import load_seguidores_manuais
        todos = load_seguidores_manuais() or {}
    except Exception as exc:  # noqa: BLE001
        print(f"[seguidores] {exc}")
        return vazio
    if scope is None:
        chaves = sorted(todos)
    elif scope.get("cliente_key"):
        chaves = [scope["cliente_key"]]
    else:
        chaves = list(scope.get("cliente_keys") or [])
    partes = [p for p in (_seguidores_manuais(todos.get(k), start, end) for k in chaves) if p.get("tem")]
    if not partes:
        return vazio
    if len(partes) == 1:
        return partes[0]
    total = sum(p["total"] for p in partes)
    novos = sum(p["novos"] for p in partes if p["comparavel"])
    base = total - novos
    return {
        "tem": True, "rede": partes[0]["rede"], "url": "", "total": total, "novos": novos,
        "crescimento": round(novos / base * 100.0, 2) if base > 0 else 0.0,
        "comparavel": any(p["comparavel"] for p in partes),
        "medido_em": max(p["medido_em"] for p in partes),
        "base_em": min((p["base_em"] for p in partes if p["base_em"]), default=""),
        "serie": {"labels": [], "total": []},
    }


def _seguidores_manuais(registro, start, end) -> dict:
    """Total e crescimento de seguidores a partir de medicoes manuais.

    'total' e a ultima medicao ate o FIM da janela; a base e a ultima medicao ate
    o INICIO dela (ou a primeira de dentro, quando nao existe nada anterior). Com
    uma medicao so nao ha crescimento a mostrar, e o painel diz isso em vez de
    fingir 0%."""
    vazio = {"tem": False}
    if not registro:
        return vazio
    hist = sorted((h for h in (registro.get("historico") or [])
                   if h.get("seguidores") is not None and h.get("data")),
                  key=lambda h: str(h["data"]))
    if not hist:
        return vazio
    ini = _fmt_date(start)
    # Seguidores sao um SNAPSHOT, nao um acumulado da janela: o total exibido e SEMPRE
    # a medicao mais recente, como no card do Instagram ("nao depende da janela"). Isso
    # tambem resolve o descompasso natural de um dia — o painel fecha o periodo no
    # ultimo dia CHEIO (em "30 dias", ontem) e o numero costuma ser anotado hoje.
    atual = hist[-1]
    # A base do crescimento e a ultima medicao ATE o inicio da janela; nao havendo
    # nenhuma antes, a primeira de DENTRO dela serve. Sem as duas, nao ha o que comparar
    # e o card mostra so o total, em vez de inventar 0%.
    antes = [h for h in hist if str(h["data"]) <= ini]
    if antes:
        base_reg = antes[-1]
    else:
        dentro_ant = [h for h in hist if ini <= str(h["data"]) < str(atual["data"])]
        base_reg = dentro_ant[0] if dentro_ant else None
    total = int(round(float(atual["seguidores"])))
    novos = total - int(round(float(base_reg["seguidores"]))) if base_reg else 0
    base = total - novos
    dentro = [h for h in hist if str(h["data"]) >= ini]
    return {
        "tem": True,
        "rede": registro.get("rede") or "LinkedIn",
        "url": registro.get("url") or "",
        "total": total,
        "novos": novos,
        "crescimento": round(novos / base * 100.0, 2) if base > 0 else 0.0,
        "comparavel": base_reg is not None,
        "medido_em": str(atual["data"]),
        "base_em": str(base_reg["data"]) if base_reg else "",
        "serie": {"labels": [str(h["data"]) for h in dentro],
                  "total": [int(round(float(h["seguidores"]))) for h in dentro]},
    }


# ----------------------------------------------------------------------------
# Geo (mapa de calor)
# ----------------------------------------------------------------------------
def _geo(geo_df, scope, start, end, level="estado", platform=None) -> dict:
    empty = {"points": [], "max": 0, "cidades": []}
    if geo_df is None or geo_df.empty:
        return empty
    df = geo_df
    if "level" in df.columns:
        df = df[df["level"] == level]
    if platform is not None and "platform" in df.columns:
        df = df[df["platform"] == platform]
    if scope is not None:
        allowed = ((scope.get("meta_ids") or set()) | (scope.get("google_ids") or set())
                   | (scope.get("tiktok_ids") or set()))
        df = df[df["account_id"].astype(str).map(_digits).isin(allowed)]
    # Estados e cidades respeitam o periodo selecionado. (As cidades vinham como um
    # agregado dos 60 dias datado em 'until' e ficavam fora da janela -- a tabela nao
    # acompanhava o filtro de dias e nao batia com o mapa. Agora o coletor traz cidade
    # por dia; o fallback do coletor, quando a consulta diaria falha, ainda chega datado
    # em 'until' e entra em qualquer janela que inclua o ultimo dia.)
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
# Publico (genero e faixa etaria)
# ----------------------------------------------------------------------------
_GENERO_ORDEM = ["feminino", "masculino", "desconhecido"]
_DEMO_LABELS = {"feminino": "Feminino", "masculino": "Masculino", "desconhecido": "Desconhecido"}


def _idade_sort(bucket):
    # '13-17' -> 13, '65+' -> 65; 'desconhecido' vai para o fim.
    d = "".join(ch for ch in str(bucket) if ch.isdigit())
    return (0, int(d[:2])) if d else (1, 0)


def _demographics(demo_df, scope, start, end, platform="todas") -> dict:
    """Impressoes/cliques/investimento por genero e por faixa etaria no periodo,
    somando as plataformas (ou so a filtrada). Vazio -> a secao some no front."""
    empty = {"genero": [], "idade": []}
    if demo_df is None or demo_df.empty:
        return empty
    df = demo_df
    if platform in ("meta", "google", "tiktok", "linkedin") and "platform" in df.columns:
        df = df[df["platform"] == platform]
    if scope is not None:
        allowed = ((scope.get("meta_ids") or set()) | (scope.get("google_ids") or set())
                   | (scope.get("tiktok_ids") or set()))
        df = df[df["account_id"].astype(str).map(_digits).isin(allowed)]
    df = _window(df, start, end)
    if df is None or df.empty:
        return empty
    out = {}
    for dim in ("genero", "idade"):
        g = df[df["dimension"] == dim].groupby("bucket")[["impressions", "clicks", "spend"]].sum()
        g = g[g["impressions"] > 0]
        if g.empty:
            out[dim] = []
            continue
        buckets = list(g.index)
        if dim == "genero":
            buckets.sort(key=lambda b: _GENERO_ORDEM.index(b) if b in _GENERO_ORDEM else 9)
        else:
            buckets.sort(key=_idade_sort)
        tot_clicks = float(g["clicks"].sum())
        items = []
        for b in buckets:
            r = g.loc[b]
            imp, clk, sp = float(r["impressions"]), float(r["clicks"]), float(r["spend"])
            items.append({
                "key": b, "label": _DEMO_LABELS.get(b, b),
                "impressions": round(imp), "clicks": round(clk), "spend": round(sp, 2),
                "ctr": round(clk / imp, 4) if imp else 0.0,
                "cpc": round(sp / clk, 2) if clk else 0.0,
                "share": round(clk / tot_clicks, 4) if tot_clicks else 0.0,
            })
        out[dim] = items
    return out


# ----------------------------------------------------------------------------
# Comparativos
# ----------------------------------------------------------------------------
def _platform_comparison(meta_cur, google_cur, tiktok_cur=None, linkedin_cur=None) -> dict:
    empty_g = pd.DataFrame(columns=["impressions", "clicks", "cost", "conversions", "conversion_value"])
    empty_m = pd.DataFrame(columns=meta_cur.columns)
    def block(m, g, t=None):
        return {
            "spend": round(M.kpi_value(m, g, "spend", t), 2),
            "impressions": int(M.kpi_value(m, g, "impressions", t)),
            "clicks": int(M.kpi_value(m, g, "clicks", t)),
            "conversions": round(M.kpi_value(m, g, "conversions", t), 1),
            "revenue": round(M.kpi_value(m, g, "revenue", t), 2),
            "cpc": round(M.kpi_value(m, g, "cpc", t), 2),
        }
    out = {"meta": block(meta_cur, empty_g), "google": block(empty_m, google_cur)}
    if tiktok_cur is not None and not tiktok_cur.empty:
        # TikTok usa schema do Meta -> passa como frame meta vazio + tiktok.
        out["tiktok"] = block(empty_m, empty_g, tiktok_cur)
    if linkedin_cur is not None and not linkedin_cur.empty:
        out["linkedin"] = block(empty_m, empty_g, linkedin_cur)
    return out


def _investimento(meta_cur, google_cur, meta_prev, google_prev,
                  tiktok_cur=None, tiktok_prev=None, linkedin_cur=None, linkedin_prev=None) -> dict:
    """Gasto do periodo por plataforma + total, com variacao vs periodo anterior.
    O bucket 'tiktok' so entra quando ha dados TikTok no escopo."""
    eg = pd.DataFrame(columns=["impressions", "clicks", "cost", "conversions", "conversion_value"])
    em = pd.DataFrame(columns=meta_cur.columns)
    sp = lambda m, g, t=None: round(M.kpi_value(m, g, "spend", t), 2)
    meta_a, meta_p = sp(meta_cur, eg), sp(meta_prev, eg)
    goog_a, goog_p = sp(em, google_cur), sp(em, google_prev)
    blk = lambda a, p: {"atual": a, "anterior": p, "delta_pct": M.pct_change(a, p)}
    has_tk = tiktok_cur is not None and not tiktok_cur.empty
    tik_a = sp(em, eg, tiktok_cur) if has_tk else 0.0
    tik_p = sp(em, eg, tiktok_prev) if (tiktok_prev is not None and not tiktok_prev.empty) else 0.0
    has_li = linkedin_cur is not None and not linkedin_cur.empty
    lin_a = sp(em, eg, linkedin_cur) if has_li else 0.0
    lin_p = sp(em, eg, linkedin_prev) if (linkedin_prev is not None and not linkedin_prev.empty) else 0.0
    tot_a = round(meta_a + goog_a + tik_a + lin_a, 2)
    tot_p = round(meta_p + goog_p + tik_p + lin_p, 2)
    out = {"meta": blk(meta_a, meta_p), "google": blk(goog_a, goog_p), "total": blk(tot_a, tot_p)}
    if has_tk:
        out["tiktok"] = blk(tik_a, tik_p)
    if has_li:
        out["linkedin"] = blk(lin_a, lin_p)
    return out


def _period_comparison(meta_cur, google_cur, meta_prev, google_prev, history,
                       tiktok_cur=None, tiktok_prev=None) -> list[dict]:
    keys = ["spend", "impressions", "clicks", "ctr", "cpc", "conversions",
            "video_views", "profile_visits", "engagement", "revenue", "cpa"]
    out = []
    for key in keys:
        if M.KPI_CATALOG[key]["base"] not in ("spend", "impressions", "clicks") \
           and history.get(M.KPI_CATALOG[key]["base"], 0) <= 0:
            continue
        cur = M.kpi_value(meta_cur, google_cur, key, tiktok_cur)
        prev = M.kpi_value(meta_prev, google_prev, key, tiktok_prev)
        spec = M.KPI_CATALOG[key]
        delta = M.pct_change(cur, prev)
        out.append({
            "key": key, "label": spec["label"], "fmt": spec["fmt"],
            "current": round(cur, 4), "previous": round(prev, 4),
            "delta_pct": delta, "good": M.is_good(spec["dir"], delta),
        })
    return out


# ----------------------------------------------------------------------------
# Secao dedicada do TikTok (KPIs headline + melhores anuncios + geo)
# ----------------------------------------------------------------------------
_RESUMO_KPIS = ["spend", "impressions", "clicks", "conversions", "ctr", "cpc"]
# LinkedIn so roda alcance e engajamento: conversao ficaria sempre zerada.
_RESUMO_KPIS_LINKEDIN = ["spend", "impressions", "clicks", "engagement", "ctr", "cpc"]


def _resumo_plataformas(meta_cur, google_cur, tiktok_cur, linkedin_cur,
                        meta_prev, google_prev, tiktok_prev, linkedin_prev) -> list[dict]:
    """KPIs de destaque de CADA plataforma com investimento no periodo (o mesmo bloco
    que antes existia so para o TikTok). Os frames ja chegam filtrados por escopo,
    conta e plataforma."""
    vm, vg = meta_cur.iloc[0:0], google_cur.iloc[0:0]
    fontes = [
        ("meta", "Meta Ads", (meta_cur, vg, None), (meta_prev, vg, None), _RESUMO_KPIS),
        ("google", "Google Ads", (vm, google_cur, None), (vm, google_prev, None), _RESUMO_KPIS),
        ("tiktok", "TikTok Ads", (vm, vg, tiktok_cur), (vm, vg, tiktok_prev), _RESUMO_KPIS),
        ("linkedin", "LinkedIn Ads", (vm, vg, linkedin_cur), (vm, vg, linkedin_prev), _RESUMO_KPIS_LINKEDIN),
    ]
    out = []
    for plat, label, (mc, gc, xc), (mp, gp, xp), chaves in fontes:
        if M.kpi_value(mc, gc, "spend", xc) <= 0:
            continue
        kpis = []
        for key in chaves:
            spec = M.KPI_CATALOG[key]
            cur = M.kpi_value(mc, gc, key, xc)
            prev = M.kpi_value(mp, gp, key, xp)
            delta = M.pct_change(cur, prev)
            kpis.append({"key": key, "label": spec["label"], "fmt": spec["fmt"],
                         "value": round(cur, 4), "delta_pct": delta,
                         "good": M.is_good(spec["dir"], delta)})
        out.append({"plataforma": plat, "label": label, "kpis": kpis})
    return out


def _tiktok_section(tiktok_cur, tiktok_prev, geo_df, scope, start, end) -> dict:
    """Secao propria do TikTok. O investimento e as campanhas/anuncios TikTok ja
    aparecem combinados (investimento.tiktok + tabelas de campanhas/anuncios); aqui
    ficam os KPIs de destaque, os melhores anuncios TikTok e o geo TikTok."""
    eg = pd.DataFrame(columns=["impressions", "clicks", "cost", "conversions", "conversion_value"])
    em = tiktok_cur.iloc[0:0]
    headline = []
    for key in ["spend", "impressions", "clicks", "conversions", "ctr", "cpc"]:
        spec = M.KPI_CATALOG[key]
        cur = M.kpi_value(em, eg, key, tiktok_cur)
        prev = M.kpi_value(em, eg, key, tiktok_prev)
        delta = M.pct_change(cur, prev)
        headline.append({
            "key": key, "label": spec["label"], "fmt": spec["fmt"],
            "value": round(cur, 4), "delta_pct": delta,
            "good": M.is_good(spec["dir"], delta),
        })
    return {
        "contas": sorted(set(tiktok_cur["account"])) if not tiktok_cur.empty else [],
        "kpis": headline,
        "melhores_anuncios": _best_ads(tiktok_cur),
        "geo": _geo(geo_df, scope, start, end, "estado", platform="tiktok"),
    }


# ----------------------------------------------------------------------------
# Orquestrador
# ----------------------------------------------------------------------------
def _moeda_escopo(store, dfs, forcada=None) -> dict:
    """Moeda a usar nos valores do payload.

    Vem das CONTAS que o cliente realmente enxerga (store.moedas, preenchido pela API
    de cada plataforma). Uma moeda forcada no clients.json tem prioridade — util
    quando a descoberta falha. Se o escopo mistura moedas, marca "misto": somar sem
    conversao seria mentira, entao a interface avisa em vez de esconder o problema.
    """
    mapa = getattr(store, "moedas", None) or {}
    codigos = set()
    for df in dfs:
        if df is None or df.empty or "account_id" not in df.columns:
            continue
        for aid in df["account_id"].astype(str).unique():
            cod = mapa.get(_digits(aid))
            if cod:
                codigos.add(cod)
    if forcada:
        info = i18n.moeda_info(forcada)
        info["misto"] = False
        info["codigos"] = [forcada]
        return info
    info = i18n.moeda_info(sorted(codigos)[0] if codigos else None)
    info["misto"] = len(codigos) > 1
    info["codigos"] = sorted(codigos)
    return info


def build_payload(store, account="todas", platform="todas", days=30, scope=None,
                  start=None, end=None) -> dict:
    meta, google = store.meta.copy(), store.google.copy()
    tiktok = store.tiktok.copy() if getattr(store, "tiktok", None) is not None \
        else pd.DataFrame(columns=meta.columns)
    linkedin = store.linkedin.copy() if getattr(store, "linkedin", None) is not None \
        else pd.DataFrame(columns=meta.columns)
    instagram = getattr(store, "instagram", None)
    instagram = instagram.copy() if instagram is not None else pd.DataFrame()

    # Cliente com leads_form_only (ex.: IPV7): "Leads" passa a contar SO os leads por
    # formulario (Instant Form) de campanhas com objetivo lead-gen, batendo com o
    # gerenciador. A coluna padrao "leads" soma form + pixel + genericos.
    if scope and scope.get("leads_form_only") and "form_leads" in meta.columns:
        meta["leads"] = meta["form_leads"]

    if scope is not None:
        meta_ids = scope.get("meta_ids") or set()
        google_ids = scope.get("google_ids") or set()
        tiktok_ids = scope.get("tiktok_ids") or set()
        if "account_id" in meta.columns:
            meta = meta[meta["account_id"].astype(str).map(_digits).isin(meta_ids)]
        if "account_id" in google.columns:
            google = google[google["account_id"].astype(str).map(_digits).isin(google_ids)]
        if "account_id" in tiktok.columns:
            tiktok = tiktok[tiktok["account_id"].astype(str).map(_digits).isin(tiktok_ids)]
        linkedin_ids = scope.get("linkedin_ids") or set()
        if "account_id" in linkedin.columns:
            linkedin = linkedin[linkedin["account_id"].astype(str).map(_digits).isin(linkedin_ids)]

    contas_visiveis = sorted(set(meta["account"]).union(set(google["account"]))
                             .union(set(tiktok["account"])).union(set(linkedin["account"])))

    if account and account != "todas":
        meta = meta[meta["account"] == account]
        google = google[google["account"] == account]
        tiktok = tiktok[tiktok["account"] == account]
        linkedin = linkedin[linkedin["account"] == account]

    # tem_tiktok controla a visibilidade da secao/opcao TikTok no front (data-driven):
    # so quando o cliente em escopo tem dados TikTok.
    tem_tiktok = not tiktok.empty
    tem_linkedin = not linkedin.empty
    # Instagram: mesma logica — a secao so aparece p/ clientes com conta de IG vinculada.
    if scope is not None and instagram is not None and not instagram.empty:
        instagram = instagram[instagram["ig_id"].astype(str).map(_digits)
                              .isin(scope.get("instagram_ids") or set())]
    tem_instagram = instagram is not None and not instagram.empty

    # historico completo (escopo+conta), p/ ocultar metricas sem historico
    meta_all, google_all, tiktok_all = meta.copy(), google.copy(), tiktok.copy()
    linkedin_all = linkedin.copy()

    all_dates = (list(meta["date"]) + list(google["date"]) + list(tiktok["date"])
                 + list(linkedin["date"]))
    if not all_dates:
        # Sem dados de ANUNCIO no periodo. O Instagram e organico e independe de
        # veiculacao, entao ainda assim entregamos a secao de seguidores (ha clientes
        # com conta de IG e sem campanha ativa) — a janela usa o calendario padrao.
        _end = pd.Timestamp(today_br()) - pd.Timedelta(days=1)
        _start = _end - pd.Timedelta(days=days - 1)
        return {"vazio": True, "tem_tiktok": tem_tiktok, "tem_linkedin": tem_linkedin,
                "tem_instagram": tem_instagram,
                "instagram": _instagram(instagram, scope, _start, _end),
                "seguidores_manuais": _seguidores_escopo(scope, _start, _end),
                "moeda": _moeda_escopo(store, (meta, google, tiktok, linkedin),
                                       (scope or {}).get("moeda")),
                "filtros": {"account": account, "platform": platform, "days": days}}

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
        # "Ultimos N dias" = janela de CALENDARIO terminando em ONTEM (exclui hoje), igual
        # as plataformas de anuncio (Meta/Google contam de ontem p/ tras). A janela e sempre
        # de N dias corridos ate ontem, MESMO que os dias finais estejam zerados (ex.: conta
        # sem veiculacao recente) — reflete o calendario vigente, nao "os ultimos N dias com
        # dados". "ontem" pela data de BRASILIA (as datas das linhas sao datas de calendario;
        # usar o relogio do servidor podia virar o dia antes/depois da virada local).
        end = pd.Timestamp(today_br()) - pd.Timedelta(days=1)
        start = end - pd.Timedelta(days=days - 1)
        win = days
    prev_end = start - pd.Timedelta(days=1)
    prev_start = prev_end - pd.Timedelta(days=win - 1)

    meta_cur, google_cur = _window(meta, start, end), _window(google, start, end)
    meta_prev, google_prev = _window(meta, prev_start, prev_end), _window(google, prev_start, prev_end)
    tiktok_cur = _window(tiktok, start, end)
    tiktok_prev = _window(tiktok, prev_start, prev_end)
    linkedin_cur = _window(linkedin, start, end)
    linkedin_prev = _window(linkedin, prev_start, prev_end)

    if platform == "meta":
        google_cur = google_cur.iloc[0:0]; google_prev = google_prev.iloc[0:0]
        google_all = google_all.iloc[0:0]
        tiktok_cur = tiktok_cur.iloc[0:0]; tiktok_prev = tiktok_prev.iloc[0:0]; tiktok_all = tiktok_all.iloc[0:0]
    elif platform == "google":
        meta_cur = meta_cur.iloc[0:0]; meta_prev = meta_prev.iloc[0:0]
        meta_all = meta_all.iloc[0:0]
        tiktok_cur = tiktok_cur.iloc[0:0]; tiktok_prev = tiktok_prev.iloc[0:0]; tiktok_all = tiktok_all.iloc[0:0]
    elif platform == "tiktok":
        meta_cur = meta_cur.iloc[0:0]; meta_prev = meta_prev.iloc[0:0]; meta_all = meta_all.iloc[0:0]
        google_cur = google_cur.iloc[0:0]; google_prev = google_prev.iloc[0:0]; google_all = google_all.iloc[0:0]

    if platform in ("meta", "google", "tiktok"):
        linkedin_cur = linkedin_cur.iloc[0:0]; linkedin_prev = linkedin_prev.iloc[0:0]
        linkedin_all = linkedin_all.iloc[0:0]
    elif platform == "linkedin":
        meta_cur = meta_cur.iloc[0:0]; meta_prev = meta_prev.iloc[0:0]; meta_all = meta_all.iloc[0:0]
        google_cur = google_cur.iloc[0:0]; google_prev = google_prev.iloc[0:0]; google_all = google_all.iloc[0:0]
        tiktok_cur = tiktok_cur.iloc[0:0]; tiktok_prev = tiktok_prev.iloc[0:0]; tiktok_all = tiktok_all.iloc[0:0]

    # Nas SOMAS, TikTok + LinkedIn ocupam juntos o slot "tiktok" (mesmo schema, mesma conta).
    extra_cur, extra_prev = _junta(tiktok_cur, linkedin_cur), _junta(tiktok_prev, linkedin_prev)
    extra_all = _junta(tiktok_all, linkedin_all)
    history = M.sums(meta_all, google_all, extra_all)
    blocks = _objective_blocks(meta_cur, google_cur, meta_prev, google_prev, extra_cur, extra_prev)

    # "Visitas ao Instagram": alem das metricas de Ads, mostra os SEGUIDORES ganhos.
    # ATENCAO: a API de Ads da Meta NAO expoe "seguidores" por campanha (o numero que
    # aparece no Gerenciador) — conferido campo a campo. Este valor vem da Instagram
    # Graph API e e da CONTA inteira no periodo (anuncios + organico); por isso o
    # rotulo deixa "(conta)" explicito, para nao ser lido como atribuicao da campanha.
    ig_cur = ig_prev = 0.0
    d_ig = None
    if tem_instagram:
        ig_cur = _ig_novos(instagram, start, end)
        ig_prev = _ig_novos(instagram, prev_start, prev_end)
        d_ig = M.pct_change(ig_cur, ig_prev)

    def _com_seguidores_ig(lista):
        if not tem_instagram:
            return lista
        for b in lista:
            if b.get("objective") == "visitas_instagram":
                b["cards"].append({
                    "key": "ig_new_followers", "label": "Novos seguidores (conta)",
                    "fmt": "int", "dir": "up", "value": round(ig_cur, 1),
                    "prev_value": round(ig_prev, 1), "delta_pct": d_ig,
                    "good": M.is_good("up", d_ig), "is_primary": False,
                })
        return lista

    _com_seguidores_ig(blocks)

    # Os mesmos blocos por plataforma, para o filtro da visao geral (o padrao continua
    # sendo o somado acima). Seguidores do IG so entram no bloco do Meta.
    vazio_m, vazio_g = meta_cur.iloc[0:0], google_cur.iloc[0:0]
    blocos_plataforma = {}
    for nome, mc_, mp_, gc_, gp_, xc_, xp_ in (
            ("meta", meta_cur, meta_prev, vazio_g, vazio_g, None, None),
            ("google", vazio_m, vazio_m, google_cur, google_prev, None, None),
            ("tiktok", vazio_m, vazio_m, vazio_g, vazio_g, tiktok_cur, tiktok_prev),
            ("linkedin", vazio_m, vazio_m, vazio_g, vazio_g, linkedin_cur, linkedin_prev)):
        if mc_.empty and gc_.empty and (xc_ is None or xc_.empty):
            continue
        bl = _objective_blocks(mc_, gc_, mp_, gp_, xc_, xp_)
        if bl:
            blocos_plataforma[nome] = _com_seguidores_ig(bl) if nome == "meta" else bl

    # Comparativo dos novos seguidores vs. periodo anterior: alimenta o comentario
    # automatico (o card do bloco de objetivo ja usa os mesmos numeros).
    ig_payload = _instagram(instagram, scope, start, end)
    if tem_instagram:
        ig_payload["novos_anterior"] = int(round(ig_prev))
        ig_payload["delta_pct"] = d_ig

    payload = {
        "vazio": False,
        "tem_tiktok": tem_tiktok,
        "tem_linkedin": tem_linkedin,
        "tem_instagram": tem_instagram,
        "instagram": ig_payload,
        "moeda": _moeda_escopo(store, (meta_cur, google_cur, tiktok_cur, linkedin_cur),
                               (scope or {}).get("moeda")),
        "filtros": {"account": account, "platform": platform, "days": days},
        "periodo": {
            "inicio": _fmt_date(start), "fim": _fmt_date(end),
            "anterior_inicio": _fmt_date(prev_start), "anterior_fim": _fmt_date(prev_end),
        },
        "contas": contas_visiveis,
        "funil": _funnel(meta_cur, google_cur, extra_cur, ig_cur,
                         (scope or {}).get("funil_ordem")),
        "investimento": _investimento(meta_cur, google_cur, meta_prev, google_prev, tiktok_cur, tiktok_prev,
                                      linkedin_cur, linkedin_prev),
        "blocos_objetivo": blocks,
        "blocos_objetivo_plataforma": blocos_plataforma,
        "serie_temporal": _time_series(meta_cur, google_cur, extra_cur, start, end),
        "melhores_anuncios": _best_ads(meta_cur),
        "melhores_anuncios_linkedin": _best_ads(linkedin_cur, destaque=_DESTAQUE_LINKEDIN),
        "palavras_chave": _keywords(google_cur),
        "campanhas": _campaigns(meta_cur, google_cur, tiktok_cur, linkedin_cur),
        "conjuntos": _ad_sets(meta_cur, google_cur, tiktok_cur),
        "anuncios": _ads(meta_cur, tiktok_cur, linkedin_cur),
        "geo": _geo(store.geo, scope, start, end, "estado"),
        "geo_cidades": _geo(store.geo, scope, start, end, "cidade"),
        "demografia": _demographics(getattr(store, "demo", None), scope, start, end, platform),
        "canais": _canais(getattr(store, "canais", None), scope, start, end, platform),
        "seguidores_manuais": _seguidores_escopo(scope, start, end),
        "resumo_plataformas": _resumo_plataformas(meta_cur, google_cur, tiktok_cur, linkedin_cur,
                                                  meta_prev, google_prev, tiktok_prev, linkedin_prev),
        "comparativo_plataforma": _platform_comparison(meta_cur, google_cur, tiktok_cur, linkedin_cur),
        "comparativo_periodo": _period_comparison(meta_cur, google_cur, meta_prev, google_prev,
                                                  history, extra_cur, extra_prev),
    }
    # Secao dedicada do TikTok (so quando o cliente tem TikTok).
    if tem_tiktok:
        payload["tiktok"] = _tiktok_section(tiktok_cur, tiktok_prev, store.geo, scope, start, end)
    return payload
