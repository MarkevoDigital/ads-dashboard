"""
Gerador de comentario automatico (PT-BR), consolidado em UM card e com foco
em pontos positivos: crescimento de resultados, reducao de custo, alta de CTR,
melhor anuncio/palavra-chave, etc.

Retorna um dict:
  {"resumo": "<frase de abertura>", "destaques": ["<bullet positivo>", ...]}
"""
from __future__ import annotations


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


def _pct(d) -> str:
    return f"{abs(d):.1f}".replace(".", ",") + "%"


# verbos positivos por metrica (quando a variacao e favoravel)
_UP_VERB = {"up": "cresceu", "down": "caiu"}


def generate(payload: dict) -> dict:
    if payload.get("vazio"):
        return {"resumo": "Sem dados no período selecionado para esta conta.", "destaques": []}

    per = payload.get("comparativo_periodo", [])
    by_key = {p["key"]: p for p in per}
    destaques: list[str] = []

    # Abertura: investimento do periodo
    spend = by_key.get("spend")
    p = payload.get("periodo", {})
    if spend:
        resumo = (f"Investimento de {fmt(spend['current'], 'currency')} no período "
                  f"({p.get('inicio')} a {p.get('fim')}).")
    else:
        resumo = f"Resumo do período {p.get('inicio')} a {p.get('fim')}."

    # 1) Variacoes FAVORAVEIS (foco positivo). Cada metrica traz (rotulo, plural)
    # para a concordancia verbal correta (ex.: "as conversões cresceram").
    nomes_amig = {
        "conversions": ("as conversões", True), "revenue": ("a receita", False),
        "ctr": ("o CTR", False), "clicks": ("os cliques", True),
        "impressions": ("as impressões", True), "cpc": ("o CPC", False),
        "cpa": ("o custo por conversão (CPA)", False), "spend": ("o investimento", False),
    }
    for key, (label, plural) in nomes_amig.items():
        m = by_key.get(key)
        if not m or m.get("delta_pct") is None or not m.get("good"):
            continue
        d = m["delta_pct"]
        if abs(d) < 1:
            continue
        # capitaliza so a 1a letra (preserva siglas como CTR/CPC/CPA)
        cap = label[0].upper() + label[1:]
        if m["fmt"] in ("currency",) and key in ("cpc", "cpa"):
            verbo = "reduziram" if plural else "reduziu"
            destaques.append(f"💸 {cap} {verbo} {_pct(d)}, agora em {fmt(m['current'], m['fmt'])}.")
        else:
            if d > 0:
                verbo = "cresceram" if plural else "cresceu"
            else:
                verbo = "caíram" if plural else "caiu"
            destaques.append(f"📈 {cap} {verbo} {_pct(d)}, chegando a {fmt(m['current'], m['fmt'])}.")

    # 2) Funil: conversoes geradas
    fun = payload.get("funil") or {}
    stages = {s["label"]: s for s in fun.get("stages", [])}
    if len(fun.get("stages", [])) >= 3:
        conv = fun["stages"][-1]
        taxa = next((r for r in fun.get("rates", []) if r["label"].startswith("Taxa")), None)
        txt = f"🎯 {fmt(conv['value'], 'int')} {conv['label'].lower()} no período"
        if taxa:
            txt += f" (taxa de conversão de {fmt(taxa['value'], 'pct')})"
        destaques.append(txt + ".")

    # 3) Melhor anuncio (destaque = nº de resultados; eficiencia como apoio)
    ads = payload.get("melhores_anuncios") or []
    if ads:
        a = ads[0]
        txt = (f"🏆 Melhor anúncio: \"{a['ad_name']}\" — "
               f"{fmt(a['result_value'], a['result_fmt'])} {a['result_label'].lower()}")
        if a.get("eff_label"):
            txt += f" ({a['eff_label']} de {fmt(a['eff_value'], a['eff_fmt'])})"
        destaques.append(txt + ". Bom candidato a escalar.")

    # 4) Melhor palavra-chave (se houver conversoes)
    kws = payload.get("palavras_chave") or []
    if kws and kws[0].get("conversions", 0) > 0:
        k = kws[0]
        destaques.append(
            f"🔑 Palavra-chave destaque: \"{k['keyword']}\" gerou {k['conversions']} "
            f"conversões a CPA de {fmt(k['cpa'], 'currency')}.")

    # 5) Top cidade (geo)
    cidades = (payload.get("geo") or {}).get("cidades") or []
    if cidades:
        c = cidades[0]
        destaques.append(f"📍 {c['city']} liderou em cliques ({fmt(c['clicks'], 'int')}).")

    if not destaques:
        destaques.append("✅ Campanhas em veiculação estável no período. Acompanhe os próximos dias para identificar tendências.")

    return {"resumo": resumo, "destaques": destaques}
