"""
Idioma e moeda por cliente.

IDIOMA — o dashboard nasceu em pt-BR e continua assim por padrao. Clientes/agencias
com "idioma": "en" no clients.json recebem a interface em ingles. A traducao do
BACKEND acontece numa unica passada no fim do build_payload (traduzir_payload): o
payload e percorrido e os campos de ROTULO conhecidos sao trocados pelo texto em
ingles. Rotulo desconhecido passa intacto — nunca quebra a tela.

MOEDA — a maioria das contas investe em BRL, mas ha contas em USD. A moeda NAO e
adivinhada: vem da propria API de cada plataforma (store.moedas: account_id -> codigo)
e o escopo do cliente define qual usar. Se o escopo misturar moedas, o payload marca
"misto" e a interface avisa, porque somar USD com BRL sem conversao seria mentira.
"""
from __future__ import annotations

IDIOMA_PADRAO = "pt"
MOEDA_PADRAO = "BRL"

# Simbolo e locale por codigo ISO. O front usa Intl com o proprio codigo; este mapa
# atende o Python (comentario automatico) e o fallback do front.
MOEDAS = {
    "BRL": {"simbolo": "R$", "locale": "pt-BR"},
    "USD": {"simbolo": "US$", "locale": "en-US"},
    "EUR": {"simbolo": "€", "locale": "de-DE"},
    "GBP": {"simbolo": "£", "locale": "en-GB"},
    "CAD": {"simbolo": "C$", "locale": "en-CA"},
    "MXN": {"simbolo": "MX$", "locale": "es-MX"},
    "ARS": {"simbolo": "AR$", "locale": "es-AR"},
    "PYG": {"simbolo": "₲", "locale": "es-PY"},
}


def moeda_info(codigo: str | None) -> dict:
    codigo = (codigo or MOEDA_PADRAO).upper()
    base = MOEDAS.get(codigo, {"simbolo": codigo, "locale": "en-US"})
    return {"codigo": codigo, "simbolo": base["simbolo"], "locale": base["locale"]}


# ----------------------------------------------------------------------------
# Rotulos gerados pelo BACKEND (metrics.py + analytics.py)
# ----------------------------------------------------------------------------
EN = {
    # --- KPIs (metrics.KPI_CATALOG) ---
    "Investimento": "Spend",
    "Impressões": "Impressions",
    "Alcance": "Reach",
    "Frequência": "Frequency",
    "Cliques": "Clicks",
    "Cliques no link": "Link clicks",
    "CTR": "CTR",
    "CPC": "CPC",
    "CPM": "CPM",
    "Conversões": "Conversions",
    "Taxa de conversão": "Conversion rate",
    "CPA": "CPA",
    "Receita": "Revenue",
    "ROAS": "ROAS",
    "Leads": "Leads",
    "Taxa de lead": "Lead rate",
    "Custo por lead": "Cost per lead",
    "Conversas iniciadas": "Conversations started",
    "Conversas por mensagem": "Messaging conversations",
    "Custo por conversa": "Cost per conversation",
    "Visitas ao perfil": "Profile visits",
    "Custo/visita perfil": "Cost/profile visit",
    "Visitas ao site": "Site visits",
    "Custo/visita site": "Cost/site visit",
    "Visualizações de vídeo": "Video views",
    "Taxa de visualização": "View rate",
    "Custo por view": "Cost per view",
    "Engajamentos": "Engagements",
    "Taxa de engajamento": "Engagement rate",
    "Interações": "Interactions",
    "Adições ao carrinho": "Add to cart",
    "Custo por carrinho": "Cost per cart",
    "Taxa de carrinho": "Cart rate",
    "Checkouts iniciados": "Checkouts initiated",
    "Custo por checkout": "Cost per checkout",
    "Taxa de checkout": "Checkout rate",
    "Compras": "Purchases",
    "Custo por compra": "Cost per purchase",
    "Taxa de compra": "Purchase rate",
    "Custo/carrinho": "Cost/cart",
    "Custo/checkout": "Cost/checkout",
    "Custo/compra": "Cost/purchase",
    # --- Blocos por objetivo (metrics.OBJECTIVE_CONFIG) ---
    "Geração de leads": "Lead generation",
    "Vendas / Conversões": "Sales / Conversions",
    "Tráfego / Cliques": "Traffic / Clicks",
    "Conversas": "Conversations",
    "Visitas ao Instagram": "Instagram visits",
    "Alcance / Reconhecimento": "Reach / Awareness",
    "Outros": "Other",
    "Engajamento": "Engagement",
    "Custo por engajamento": "Cost per engagement",
    "Views": "Views",
    # --- Funil (analytics) ---
    "Novos seguidores (conta)": "New followers (account)",
    "Feminino": "Female",
    "Masculino": "Male",
    "Desconhecido": "Unknown",
    "Custo/view": "Cost/view",
    "Custo/visita": "Cost/visit",
    "CPL": "CPL",
    "Custo/conversa": "Cost/conversation",
    # taxas entre etapas ("Taxa de " + rotulo da etapa seguinte, em minusculas)
    "Taxa de conversões": "Conversion rate",
    "Taxa de leads": "Lead rate",
    "Taxa de conversas": "Conversation rate",
    "Taxa de visitas ao perfil": "Profile visit rate",
    "Taxa de visualizações de vídeo": "Video view rate",
    "Taxa de impressões": "Impression rate",
    # --- Rotulos de plataforma / diversos ---
    "Meta Ads": "Meta Ads",
    "Google Ads": "Google Ads",
    "TikTok Ads": "TikTok Ads",
    "Total": "Total",
}

# Campos do payload que carregam ROTULO (e nao dado do cliente). Nome de campanha,
# de anuncio e de conta NUNCA entram aqui: sao dados, nao interface.
CAMPOS_ROTULO = ("label", "cost_label", "eff_label", "result_label",
                 "objective_label", "objetivo", "metrica")


def t(texto, idioma: str = IDIOMA_PADRAO) -> str:
    """Traduz um rotulo. Desconhecido volta igual (nunca quebra a tela)."""
    if idioma != "en" or not isinstance(texto, str):
        return texto
    return EN.get(texto, texto)


def traduzir_payload(payload, idioma: str = IDIOMA_PADRAO):
    """Percorre o payload trocando SO os campos de rotulo. In-place, recursivo."""
    if idioma != "en":
        return payload
    if isinstance(payload, dict):
        for k, v in payload.items():
            if k in CAMPOS_ROTULO and isinstance(v, str):
                payload[k] = t(v, idioma)
            else:
                traduzir_payload(v, idioma)
    elif isinstance(payload, list):
        for item in payload:
            traduzir_payload(item, idioma)
    return payload
