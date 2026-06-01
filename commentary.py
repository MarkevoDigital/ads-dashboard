"""
Gerador de comentarios automaticos (PT-BR) baseado em regras.

Le o payload de analytics.build_payload e produz frases curtas e acionaveis:
resumo de investimento, variacao do KPI principal por objetivo, melhor anuncio,
melhor palavra-chave, comparativo de plataforma e alertas (fadiga, CTR baixo etc).
"""
from __future__ import annotations


# ----------------------------------------------------------------------------
# Formatadores (espelham o front, mas em texto pt-BR)
# ----------------------------------------------------------------------------
def fmt(value, kind: str) -> str:
    if value is None:
        return "—"
    if kind == "currency":
        return "R$ " + f"{value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    if kind == "int":
        return f"{int(round(value)):,}".replace(",", ".")
    if kind == "pct":
        return f"{value * 100:.2f}".replace(".", ",") + "%"
    if kind == "ratio":
        return f"{value:.2f}".replace(".", ",") + "x"
    if kind == "dec":
        return f"{value:.2f}".replace(".", ",")
    return str(value)


def _delta_txt(delta) -> str:
    if delta is None:
        return "sem base de comparacao"
    if delta > 0:
        return f"alta de {delta:.1f}%".replace(".", ",")
    if delta < 0:
        return f"queda de {abs(delta):.1f}%".replace(".", ",")
    return "estavel"


def _sentido(good) -> str:
    if good is True:
        return "positivo"
    if good is False:
        return "ponto de atencao"
    return "neutro"


# ----------------------------------------------------------------------------
# Geracao
# ----------------------------------------------------------------------------
def generate(payload: dict) -> list[dict]:
    if payload.get("vazio"):
        return [{"tipo": "info", "texto": "Sem dados no periodo selecionado para esta conta."}]

    comments: list[dict] = []
    per = payload["comparativo_periodo"]
    by_key = {p["key"]: p for p in per}

    # 1) Investimento total
    spend = by_key.get("spend")
    if spend:
        comments.append({
            "tipo": "info",
            "texto": (
                f"Investimento de {fmt(spend['current'], 'currency')} no periodo "
                f"({payload['periodo']['inicio']} a {payload['periodo']['fim']}), "
                f"{_delta_txt(spend['delta_pct'])} frente ao periodo anterior."
            ),
        })

    # 2) KPI principal de cada objetivo
    for b in payload["blocos_objetivo"]:
        primary = next((c for c in b["cards"] if c.get("is_primary")), None)
        if not primary:
            continue
        tipo = {True: "positivo", False: "alerta", None: "info"}[primary["good"]]
        comments.append({
            "tipo": tipo,
            "texto": (
                f"[{b['label']}] {primary['label']} em {fmt(primary['value'], primary['fmt'])} "
                f"({_delta_txt(primary['delta_pct'])}), {_sentido(primary['good'])}. "
                f"Investimento do objetivo: {fmt(b['spend'], 'currency')}."
            ),
        })

    # 3) Melhor anuncio
    ads = payload.get("melhores_anuncios") or []
    if ads:
        a = ads[0]
        comments.append({
            "tipo": "positivo",
            "texto": (
                f"Melhor anuncio: \"{a['ad_name']}\" ({a['account']}) com "
                f"{a['metric_label']} de {fmt(a['metric_value'], a['metric_fmt'])} "
                f"e investimento de {fmt(a['spend'], 'currency')}. "
                f"Considere escalar o orcamento deste criativo."
            ),
        })

    # 4) Melhor palavra-chave
    kws = payload.get("palavras_chave") or []
    if kws:
        k = kws[0]
        if k["conversions"] > 0:
            extra = f"gerando {k['conversions']} conversoes a um CPA de {fmt(k['cpa'], 'currency')}"
        else:
            extra = f"com {k['clicks']} cliques e CTR de {fmt(k['ctr'], 'pct')}"
        comments.append({
            "tipo": "info",
            "texto": f"Palavra-chave destaque no Google Ads: \"{k['keyword']}\", {extra}.",
        })

    # 5) Comparativo de plataforma
    cp = payload.get("comparativo_plataforma") or {}
    m, g = cp.get("meta", {}), cp.get("google", {})
    if m.get("spend") or g.get("spend"):
        total = (m.get("spend", 0) + g.get("spend", 0)) or 1
        share_meta = m.get("spend", 0) / total * 100
        comments.append({
            "tipo": "info",
            "texto": (
                f"Divisao de verba: Meta Ads {share_meta:.0f}% "
                f"({fmt(m.get('spend', 0), 'currency')}) x Google Ads "
                f"{100 - share_meta:.0f}% ({fmt(g.get('spend', 0), 'currency')})."
            ),
        })

    # 6) Alertas baseados em limiares
    for b in payload["blocos_objetivo"]:
        cards = {c["key"]: c for c in b["cards"]}
        freq = cards.get("frequency")
        if freq and freq["value"] >= 3.0:
            comments.append({
                "tipo": "alerta",
                "texto": (
                    f"[{b['label']}] Frequencia de {fmt(freq['value'], 'dec')} indica possivel "
                    f"fadiga de criativo. Atualize os anuncios ou amplie o publico."
                ),
            })
        ctr = cards.get("ctr")
        if ctr and 0 < ctr["value"] < 0.008:
            comments.append({
                "tipo": "alerta",
                "texto": (
                    f"[{b['label']}] CTR de {fmt(ctr['value'], 'pct')} esta abaixo do esperado. "
                    f"Reveja criativo e segmentacao."
                ),
            })

    return comments
