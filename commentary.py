"""
Gerador de comentario automatico, consolidado em UM card e com foco em pontos
positivos: crescimento de resultados, reducao de custo, alta de CTR, melhor
anuncio/palavra-chave, seguidores do Instagram etc.

Fala pt-BR por padrao e ingles para clientes com "idioma": "en" (MB Creative e
seus clientes). Os textos ficam em TEXTOS[idioma]; a logica de QUANDO comentar e
uma so — assim as duas versoes nunca divergem em criterio.

Os valores em dinheiro usam a moeda do proprio escopo (payload["moeda"]), nunca
um "R$" fixo: ha clientes investindo em USD.

Retorna: {"resumo": "<abertura>", "destaques": ["<bullet>", ...]}
"""
from __future__ import annotations

PADRAO = {"simbolo": "R$", "codigo": "BRL"}


def fmt(value, kind: str, sim: str = "R$", idioma: str = "pt") -> str:
    """Formata um numero. Em pt-BR: 1.234,56 · em ingles: 1,234.56."""
    if value is None:
        return "—"
    if kind == "currency":
        base = f"{value:,.2f}"
        if idioma == "pt":
            base = base.replace(",", "X").replace(".", ",").replace("X", ".")
        # pt-BR escreve "R$ 1.234,56"; ingles escreve "$1,234.56" (igual ao Intl).
        return f"{sim} {base}" if idioma == "pt" else f"{sim}{base}"
    if kind == "int":
        base = f"{int(round(value)):,}"
        return base.replace(",", ".") if idioma == "pt" else base
    if kind == "pct":
        base = f"{value * 100:.2f}"
        return (base.replace(".", ",") if idioma == "pt" else base) + "%"
    if kind == "ratio":
        base = f"{value:.2f}"
        return (base.replace(".", ",") if idioma == "pt" else base) + "x"
    if kind == "dec":
        base = f"{value:.2f}"
        return base.replace(".", ",") if idioma == "pt" else base
    return str(value)


def _pct(d, idioma: str = "pt") -> str:
    base = f"{abs(d):.1f}"
    return (base.replace(".", ",") if idioma == "pt" else base) + "%"


# ----------------------------------------------------------------------------
# Textos por idioma
# ----------------------------------------------------------------------------
TEXTOS = {
    "pt": {
        "sem_dados": "Sem dados no período selecionado para esta conta.",
        "so_organico": "Sem veiculação de anúncios no período — abaixo, o desempenho orgânico do Instagram.",
        "resumo_invest": "Investimento de {spend} no período ({ini} a {fim}).",
        "resumo_simples": "Resumo do período {ini} a {fim}.",
        "misto": "⚠️ Este acesso reúne contas em moedas diferentes ({codigos}); os totais somam valores sem conversão cambial.",
        "metricas": {
            "conversions": ("as conversões", True), "revenue": ("a receita", False),
            "ctr": ("o CTR", False), "clicks": ("os cliques", True),
            "impressions": ("as impressões", True), "cpc": ("o CPC", False),
            "cpa": ("o custo por conversão (CPA)", False), "spend": ("o investimento", False),
        },
        "reduziu": ("reduziram", "reduziu"),
        "cresceu": ("cresceram", "cresceu"),
        "caiu": ("caíram", "caiu"),
        "custo_txt": "💸 {cap} {verbo} {d}, agora em {v}.",
        "var_txt": "📈 {cap} {verbo} {d}, chegando a {v}.",
        "leads": ("lead captado", "leads captados"),
        "leads_txt": "📋 {v} {noun} no período",
        "cpl": "CPL de {v}",
        "taxa": "taxa de {v}",
        "video_txt": "🎬 {v} visualizações de vídeo",
        "delta_sufixo": " — {dir} de {d} vs. período anterior",
        "alta": "alta", "queda": "queda",
        "desfecho": {"Conversões": ("conversão", "conversões"), "Conversas": ("conversa", "conversas"),
                     "Compras": ("compra", "compras"),
                     "Adições ao carrinho": ("adição ao carrinho", "adições ao carrinho"),
                     "Checkouts iniciados": ("checkout iniciado", "checkouts iniciados")},
        "desfecho_txt": "🎯 {v} {noun} no período",
        "custo_de": "{rot} de {v}",
        "ig_uma": "📸 @{user} ganhou {v} {plural} no período",
        "ig_varias": "📸 {v} {plural} no Instagram",
        "ig_contas": " em {n} contas",
        "ig_plural": ("novo seguidor", "novos seguidores"),
        "ig_cresc": "crescimento de {v}",
        "ig_base": "base de {v} seguidores",
        "melhor_ad": "🏆 Melhor anúncio: \"{nome}\" — {v} {rot}",
        "melhor_ad_fim": ". Bom candidato a escalar.",
        "kw": "🔑 Palavra-chave destaque: \"{kw}\" gerou {n} conversões a CPA de {cpa}.",
        "cidade": "📍 {cidade} liderou em cliques ({v}).",
        "estavel": "✅ Campanhas em veiculação estável no período. Acompanhe os próximos dias para identificar tendências.",
        # Visao geral: paragrafo corrido, de leitura. Regra do cliente: nunca apontar
        # queda de resultado nem alta de custo — as nuances entram como contexto.
        "vg": {
            "abre": "Entre {ini} e {fim}, o investimento foi de {gasto}, distribuído em {nc} {camp} e {na} {anun} com veiculação",
            "campanha": ("campanha", "campanhas"),
            "anuncio": ("anúncio", "anúncios"),
            "ativos_todos": ", todos ativos agora",
            "ativos_parte": ", sendo {n} ainda ativos",
            "volume": "No total, foram {impr} impressões e {cliques} cliques, com CTR de {ctr}.",
            "volume_simples": "No total, foram {impr} impressões e {cliques} cliques.",
            "termos": "No Google, {n} {termo} de pesquisa {verbo} veiculação no período.",
            "termo": ("termo", "termos"),
            "termo_verbo": ("teve", "tiveram"),
            "conv_menos_gasto": "As conversões somaram {v} e cresceram {d} em relação ao período anterior, mesmo com investimento menor — sinal de que a verba rendeu mais.",
            "conv_cresceu": "As conversões somaram {v}, {d} acima do período anterior.",
            "conv_simples": "As conversões somaram {v} no período.",
            "cpa_melhor": "O custo por conversão ficou em {v}, abaixo do período anterior.",
            "pausa": "Vale notar que {n} {dia} do intervalo {verbo} sem veiculação, então o resultado se concentra nos {ativos} dias em que os anúncios rodaram.",
            "dia": ("dia", "dias"),
            "dia_verbo": ("ficou", "ficaram"),
            "pico": "O melhor dia foi {data}, que sozinho respondeu por {v} do investimento.",
            "ig": "No orgânico, o Instagram ganhou {v} seguidores no mesmo intervalo.",
        },
    },
    "en": {
        "sem_dados": "No data for the selected period on this account.",
        "so_organico": "No ads ran in this period — below, the organic Instagram performance.",
        "resumo_invest": "Spend of {spend} in the period ({ini} to {fim}).",
        "resumo_simples": "Summary for {ini} to {fim}.",
        "misto": "⚠️ This login covers accounts in different currencies ({codigos}); totals add the values up without any currency conversion.",
        "metricas": {
            "conversions": ("conversions", True), "revenue": ("revenue", False),
            "ctr": ("CTR", False), "clicks": ("clicks", True),
            "impressions": ("impressions", True), "cpc": ("CPC", False),
            "cpa": ("cost per conversion (CPA)", False), "spend": ("spend", False),
        },
        "reduziu": ("dropped", "dropped"),
        "cresceu": ("grew", "grew"),
        "caiu": ("fell", "fell"),
        "custo_txt": "💸 {cap} {verbo} {d}, now at {v}.",
        "var_txt": "📈 {cap} {verbo} {d}, reaching {v}.",
        "leads": ("lead captured", "leads captured"),
        "leads_txt": "📋 {v} {noun} in the period",
        "cpl": "CPL of {v}",
        "taxa": "{v} rate",
        "video_txt": "🎬 {v} video views",
        "delta_sufixo": " — {dir} {d} vs. previous period",
        "alta": "up", "queda": "down",
        "desfecho": {"Conversões": ("conversion", "conversions"), "Conversas": ("conversation", "conversations"),
                     "Compras": ("purchase", "purchases"),
                     "Adições ao carrinho": ("add to cart", "add to carts"),
                     "Checkouts iniciados": ("checkout initiated", "checkouts initiated")},
        "desfecho_txt": "🎯 {v} {noun} in the period",
        "custo_de": "{rot} of {v}",
        "ig_uma": "📸 @{user} gained {v} {plural} in the period",
        "ig_varias": "📸 {v} {plural} on Instagram",
        "ig_contas": " across {n} accounts",
        "ig_plural": ("new follower", "new followers"),
        "ig_cresc": "{v} growth",
        "ig_base": "{v} followers base",
        "melhor_ad": "🏆 Top ad: \"{nome}\" — {v} {rot}",
        "melhor_ad_fim": ". A good candidate to scale.",
        "kw": "🔑 Top keyword: \"{kw}\" drove {n} conversions at a {cpa} CPA.",
        "cidade": "📍 {cidade} led in clicks ({v}).",
        "estavel": "✅ Campaigns delivered steadily in the period. Keep an eye on the coming days to spot trends.",
        "vg": {
            "abre": "Between {ini} and {fim}, spend reached {gasto}, spread across {nc} {camp} and {na} {anun} that delivered",
            "campanha": ("campaign", "campaigns"),
            "anuncio": ("ad", "ads"),
            "ativos_todos": ", all of them still running",
            "ativos_parte": ", {n} of them still running",
            "volume": "All in all, that meant {impr} impressions and {cliques} clicks, at a {ctr} CTR.",
            "volume_simples": "All in all, that meant {impr} impressions and {cliques} clicks.",
            "termos": "On Google, {n} search {termo} {verbo} impressions in the period.",
            "termo": ("term", "terms"),
            "termo_verbo": ("had", "had"),
            "conv_menos_gasto": "Conversions added up to {v} and grew {d} against the previous period, even on a smaller budget — the spend went further.",
            "conv_cresceu": "Conversions added up to {v}, {d} above the previous period.",
            "conv_simples": "Conversions added up to {v} in the period.",
            "cpa_melhor": "Cost per conversion came in at {v}, below the previous period.",
            "pausa": "Worth noting that {n} {dia} in the range {verbo} without delivery, so the results come from the {ativos} days the ads actually ran.",
            "dia": ("day", "days"),
            "dia_verbo": ("went", "went"),
            "pico": "The strongest day was {data}, which alone took {v} of the spend.",
            "ig": "On the organic side, Instagram gained {v} followers over the same range.",
        },
    },
}


def _visao_geral(payload: dict, by_key: dict, T: dict, f, idioma: str) -> str:
    """Paragrafo de leitura corrida sobre o periodo: volume, o que sustentou os numeros
    e as nuances que ajudam a interpretar (dias sem veiculacao, conversao crescendo com
    investimento menor, dia de pico).

    Regra do cliente: NUNCA apontar ponto negativo — queda de resultado e alta de custo
    ficam de fora. O que nao melhorou simplesmente nao vira frase."""
    V = T.get("vg")
    if not V:
        return ""

    def data(s):
        """31/08 em pt, 08/31 em ingles — num paragrafo de leitura, ISO trava o texto."""
        try:
            a, m, d = str(s).split("-")
        except ValueError:
            return str(s)
        return f"{d}/{m}" if idioma == "pt" else f"{m}/{d}"

    def pct_inteiro(v):
        base = f"{v * 100:.0f}"
        return base + "%"

    p = payload.get("periodo", {})
    cur = lambda k: (by_key.get(k) or {}).get("current") or 0  # noqa: E731
    dlt = lambda k: (by_key.get(k) or {}).get("delta_pct")     # noqa: E731

    def plural(n, par):
        return par[0] if n == 1 else par[1]

    campanhas = payload.get("campanhas") or []
    anuncios = payload.get("anuncios") or []
    frases = []

    abre = V["abre"].format(ini=data(p.get("inicio")), fim=data(p.get("fim")),
                            gasto=f(cur("spend"), "currency"),
                            nc=f(len(campanhas), "int"), camp=plural(len(campanhas), V["campanha"]),
                            na=f(len(anuncios), "int"), anun=plural(len(anuncios), V["anuncio"]))
    ativos = sum(1 for a in anuncios if a.get("ativo"))
    if anuncios and ativos == len(anuncios):
        abre += V["ativos_todos"]
    elif ativos:
        abre += V["ativos_parte"].format(n=f(ativos, "int"))
    frases.append(abre + ".")

    impr, cliques, ctr = cur("impressions"), cur("clicks"), cur("ctr")
    if impr or cliques:
        chave = "volume" if ctr else "volume_simples"
        frases.append(V[chave].format(impr=f(impr, "int"), cliques=f(cliques, "int"),
                                      ctr=f(ctr, "pct")))

    termos = int(payload.get("palavras_chave_total") or 0)
    if termos:
        frases.append(V["termos"].format(n=f(termos, "int"), termo=plural(termos, V["termo"]),
                                         verbo=plural(termos, V["termo_verbo"])))

    conv, d_conv, d_spend = cur("conversions"), dlt("conversions"), dlt("spend")
    if conv:
        if d_conv and d_conv >= 1 and d_spend is not None and d_spend < 0:
            frases.append(V["conv_menos_gasto"].format(v=f(conv, "int"), d=_pct(d_conv, idioma)))
        elif d_conv and d_conv >= 1:
            frases.append(V["conv_cresceu"].format(v=f(conv, "int"), d=_pct(d_conv, idioma)))
        else:
            frases.append(V["conv_simples"].format(v=f(conv, "int")))
    d_cpa = dlt("cpa")
    if cur("cpa") and d_cpa is not None and d_cpa <= -1:
        frases.append(V["cpa_melhor"].format(v=f(cur("cpa"), "currency")))

    # Nuances da serie diaria: dias sem entrega e dia de pico.
    serie = payload.get("serie_temporal") or {}
    gastos = list(serie.get("spend") or [])
    labels = list(serie.get("labels") or [])
    if gastos and len(gastos) == len(labels):
        zerados = sum(1 for v in gastos if not v)
        rodou = len(gastos) - zerados
        if zerados and rodou:
            frases.append(V["pausa"].format(n=f(zerados, "int"), dia=plural(zerados, V["dia"]),
                                            verbo=plural(zerados, V["dia_verbo"]),
                                            ativos=f(rodou, "int")))
        total = sum(gastos)
        if total > 0 and rodou > 2:
            i = gastos.index(max(gastos))
            fatia = gastos[i] / total
            if fatia >= 0.2:
                frases.append(V["pico"].format(data=data(labels[i]), v=pct_inteiro(fatia)))

    ig = payload.get("instagram") or {}
    if int(ig.get("novos") or 0) > 0:
        frases.append(V["ig"].format(v=f(ig["novos"], "int")))

    return " ".join(frases)


def _ig_destaque(ig: dict, T: dict, sim: str, idioma: str) -> str:
    """Bullet dos novos seguidores do Instagram.

    ATENCAO: e um dado ORGANICO da conta inteira (anuncios + organico) — a API de Ads
    nao atribui seguidores por campanha. O texto nunca credita o ganho as campanhas.
    """
    novos = int(ig.get("novos") or 0)
    contas = ig.get("contas") or []
    det = []
    if ig.get("crescimento"):
        det.append(T["ig_cresc"].format(v=fmt(ig["crescimento"] / 100.0, "pct", sim, idioma)))
    if ig.get("total"):
        det.append(T["ig_base"].format(v=fmt(ig["total"], "int", sim, idioma)))
    plural = T["ig_plural"][0] if novos == 1 else T["ig_plural"][1]
    v = fmt(novos, "int", sim, idioma)
    if len(contas) == 1 and contas[0].get("username"):
        txt = T["ig_uma"].format(user=contas[0]["username"], v=v, plural=plural)
    else:
        txt = T["ig_varias"].format(v=v, plural=plural)
        if len(contas) > 1:
            txt += T["ig_contas"].format(n=len(contas))
    if det:
        txt += " (" + ", ".join(det) + ")"
    d = ig.get("delta_pct")
    if d is not None and abs(d) >= 1:
        txt += T["delta_sufixo"].format(dir=T["alta"] if d > 0 else T["queda"], d=_pct(d, idioma))
    return txt + "."


def generate(payload: dict, idioma: str = "pt") -> dict:
    idioma = "en" if idioma == "en" else "pt"
    T = TEXTOS[idioma]
    moeda = payload.get("moeda") or PADRAO
    # Mesma convencao do Intl do navegador, para o texto nao divergir dos cards:
    # em ingles o dolar e "$"; em pt-BR e "US$" (e o real e "R$" nos dois).
    sim = moeda.get("simbolo") or "R$"
    if idioma == "en" and moeda.get("codigo") == "USD":
        sim = "$"

    def f(v, k):
        return fmt(v, k, sim, idioma)

    if payload.get("vazio"):
        # Sem anuncios no periodo, mas o Instagram e organico e pode ter crescido:
        # cliente so-Instagram nao pode ver "sem dados" com a secao de seguidores cheia.
        ig = payload.get("instagram") or {}
        if int(ig.get("novos") or 0) > 0:
            return {"resumo": T["so_organico"], "destaques": [_ig_destaque(ig, T, sim, idioma)]}
        return {"resumo": T["sem_dados"], "destaques": []}

    per = payload.get("comparativo_periodo", [])
    by_key = {p["key"]: p for p in per}
    destaques: list[str] = []

    # Abertura: investimento do periodo
    spend = by_key.get("spend")
    p = payload.get("periodo", {})
    if spend:
        resumo = T["resumo_invest"].format(spend=f(spend["current"], "currency"),
                                           ini=p.get("inicio"), fim=p.get("fim"))
    else:
        resumo = T["resumo_simples"].format(ini=p.get("inicio"), fim=p.get("fim"))

    # Escopo com mais de uma moeda: avisa em vez de fingir que o total faz sentido.
    if moeda.get("misto"):
        destaques.append(T["misto"].format(codigos=", ".join(moeda.get("codigos") or [])))

    # 1) Variacoes FAVORAVEIS (foco positivo).
    for key, (label, plural) in T["metricas"].items():
        m = by_key.get(key)
        if not m or m.get("delta_pct") is None or not m.get("good"):
            continue
        # Metrica zerada nao e conquista: custo por resultado so chega a zero quando
        # NAO houve resultado no periodo (CPA "reduziu 100%, agora R$ 0,00" com zero
        # compras). A queda e ausencia de dado, nao eficiencia -- a linha sai.
        if not m.get("current"):
            continue
        d = m["delta_pct"]
        if abs(d) < 1:
            continue
        cap = label[0].upper() + label[1:]  # preserva siglas (CTR/CPC/CPA)
        if m["fmt"] == "currency" and key in ("cpc", "cpa"):
            verbo = T["reduziu"][0] if plural else T["reduziu"][1]
            destaques.append(T["custo_txt"].format(cap=cap, verbo=verbo, d=_pct(d, idioma),
                                                   v=f(m["current"], m["fmt"])))
        else:
            chave = "cresceu" if d > 0 else "caiu"
            verbo = T[chave][0] if plural else T[chave][1]
            destaques.append(T["var_txt"].format(cap=cap, verbo=verbo, d=_pct(d, idioma),
                                                 v=f(m["current"], m["fmt"])))

    # 2) Funil: desfechos do periodo, na ordem configurada do funil. Os rotulos podem
    # ja ter sido traduzidos (payload em ingles), entao aceitamos os dois idiomas.
    fun = payload.get("funil") or {}
    stages = fun.get("stages", [])

    # Conversas so viram destaque quando alguma campanha do periodo tem mensagens
    # como objetivo. Sem isso, uma conversa acidental de campanha de video vira linha
    # de relatorio com "custo por conversa" = investimento inteiro da conta. Sem
    # blocos (payload vazio) mantemos o comportamento antigo, para nao esconder dado.
    blocos_obj = payload.get("blocos_objetivo") or []
    msg_e_objetivo = (not blocos_obj
                      or any(b.get("objective") == "mensagens" for b in blocos_obj))

    def _rate(*prefixos):
        return next((r for r in fun.get("rates", [])
                     if any(r.get("label", "").startswith(px) for px in prefixos)), None)

    for st in stages:
        lbl = st.get("label")
        val = st.get("value", 0) or 0
        if lbl == "Leads" and val > 0:
            det = []
            if st.get("cost"):
                det.append(T["cpl"].format(v=f(st["cost"], "currency")))
            tl = _rate("Taxa de leads", "Lead rate")
            if tl:
                det.append(T["taxa"].format(v=f(tl["value"], "pct")))
            noun = T["leads"][0] if val == 1 else T["leads"][1]
            txt = T["leads_txt"].format(v=f(val, "int"), noun=noun)
            if det:
                txt += " (" + ", ".join(det) + ")"
            destaques.append(txt + ".")
        elif lbl in ("Visualizações de vídeo", "Video views") and val >= 500:
            det = []
            tv = _rate("Taxa de visualização", "View rate")
            if tv:
                det.append(T["taxa"].format(v=f(tv["value"], "pct")))
            if st.get("cost"):
                det.append(T["custo_de"].format(rot=st["cost_label"].lower(),
                                                v=f(st["cost"], "currency")))
            txt = T["video_txt"].format(v=f(val, "int"))
            if det:
                txt += " (" + ", ".join(det) + ")"
            vv = by_key.get("video_views")
            if vv and vv.get("delta_pct") is not None and abs(vv["delta_pct"]) >= 1:
                d = vv["delta_pct"]
                txt += T["delta_sufixo"].format(dir=T["alta"] if d > 0 else T["queda"],
                                                d=_pct(d, idioma))
            destaques.append(txt + ".")
        elif lbl in ("Conversões", "Conversas", "Compras", "Adições ao carrinho",
                     "Checkouts iniciados", "Conversions", "Conversations", "Purchases",
                     "Add to cart", "Checkouts initiated") and val > 0:
            chave = {"Conversions": "Conversões", "Conversations": "Conversas",
                     "Purchases": "Compras", "Add to cart": "Adições ao carrinho",
                     "Checkouts initiated": "Checkouts iniciados"}.get(lbl, lbl)
            if chave == "Conversas" and not msg_e_objetivo:
                continue
            par = T["desfecho"][chave]
            noun = par[0] if val == 1 else par[1]
            txt = T["desfecho_txt"].format(v=f(val, "int"), noun=noun)
            if st.get("cost"):
                txt += " (" + T["custo_de"].format(rot=st["cost_label"].lower(),
                                                   v=f(st["cost"], "currency")) + ")"
            destaques.append(txt + ".")

    # 2b) Instagram: novos seguidores do periodo (dado organico da conta inteira).
    ig = payload.get("instagram") or {}
    if int(ig.get("novos") or 0) > 0:
        destaques.append(_ig_destaque(ig, T, sim, idioma))

    # 3) Melhor anuncio (destaque = nº de resultados; eficiencia como apoio)
    # Anuncio com ZERO resultado nao e "bom candidato a escalar": ele so lidera a
    # lista porque ninguem pontuou no periodo. Ficam de fora; se nenhum pontuou, a
    # linha nao sai. Nao ha o que escalar.
    ads = [a for a in (payload.get("melhores_anuncios") or []) if a.get("result_value")]
    if ads:
        a = ads[0]
        txt = T["melhor_ad"].format(nome=a["ad_name"], v=f(a["result_value"], a["result_fmt"]),
                                    rot=a["result_label"].lower())
        if a.get("eff_label"):
            txt += " (" + T["custo_de"].format(rot=a["eff_label"],
                                               v=f(a["eff_value"], a["eff_fmt"])) + ")"
        destaques.append(txt + T["melhor_ad_fim"])

    # 4) Melhor palavra-chave (se houver conversoes)
    kws = payload.get("palavras_chave") or []
    if kws and kws[0].get("conversions", 0) > 0:
        k = kws[0]
        destaques.append(T["kw"].format(kw=k["keyword"], n=k["conversions"],
                                        cpa=f(k["cpa"], "currency")))

    # 5) Top cidade (geo)
    cidades = (payload.get("geo") or {}).get("cidades") or []
    if cidades:
        c = cidades[0]
        destaques.append(T["cidade"].format(cidade=c["city"], v=f(c["clicks"], "int")))

    if not destaques:
        destaques.append(T["estavel"])

    return {"resumo": resumo, "visao_geral": _visao_geral(payload, by_key, T, f, idioma),
            "destaques": destaques}
