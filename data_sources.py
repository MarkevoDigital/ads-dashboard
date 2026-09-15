"""
Camada de dados do dashboard.

Resolve a fonte de dados nesta ordem de preferencia (config["fonte_dados"]):
  - "service_account": le do Google Sheets via conta de servico (gspread)
  - "csv_publicado":   le de URLs CSV publicadas do Google Sheets
  - "sample":          usa dados de exemplo sinteticos
  - "auto":            tenta service_account -> csv_publicado -> sample

Expoe um cache em memoria (DataFrames) com timestamp de ultima atualizacao,
recarregavel sob demanda (/api/refresh) ou pelo agendador diario.
"""
from __future__ import annotations

import io
import json
import os
import pickle
import threading
from datetime import datetime, timedelta

from tz_br import now_br, to_br, today_br

import numpy as np
import pandas as pd
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLE_DIR = os.path.join(BASE_DIR, "sample_data")
# Cache do store em disco: deixa um worker reciclado pelo Passenger subir PRONTO
# em ~1s (sem refazer ~15min de busca de API). Resolve o "carregando" recorrente.
STORE_CACHE = os.path.join(BASE_DIR, "tmp", "store_cache.pkl")

# Colunas canonicas que o resto do app espera encontrar.
META_COLUMNS = [
    "date", "account", "account_id", "objective", "campaign", "adset", "ad_name",
    "ad_thumbnail_url", "ad_permalink", "daily_budget", "impressions", "reach", "frequency",
    "clicks", "link_clicks", "spend", "messaging_conversations",
    "profile_visits", "leads", "form_leads", "purchases", "purchase_value",
    "site_visits", "video_views", "engagement",
    # E-commerce (Meta/TikTok): etapas antes da compra. Zero para quem nao tem pixel
    # de loja — a regra de ocultar zerados cuida de nao poluir o dashboard.
    "add_to_cart", "initiate_checkout", "registrations",
]
GOOGLE_COLUMNS = [
    "date", "account", "account_id", "objective", "campaign", "campaign_type",
    "ad_group", "keyword", "match_type", "daily_budget", "impressions", "clicks", "cost",
    "conversions", "conversion_value", "video_views", "interactions",
]
GEO_COLUMNS = [
    "date", "account_id", "platform", "level", "city", "lat", "lng", "clicks",
]

NUMERIC_META = [
    "daily_budget", "impressions", "reach", "frequency", "clicks", "link_clicks", "spend",
    "messaging_conversations", "profile_visits", "leads", "form_leads", "purchases",
    "purchase_value", "site_visits", "video_views", "engagement",
    "add_to_cart", "initiate_checkout", "registrations",
]
NUMERIC_GOOGLE = [
    "daily_budget", "impressions", "clicks", "cost", "conversions", "conversion_value",
    "video_views", "interactions",
]
NUMERIC_GEO = ["lat", "lng", "clicks"]

# Publico (genero e faixa etaria) por conta e por dia, p/ a secao "Publico".
# 'dimension' = "genero" | "idade"; 'bucket' = valor normalizado entre plataformas
# ("feminino", "25-34", "65+", "desconhecido" -- ver connectors/demo_norm.py).
DEMO_COLUMNS = ["date", "account_id", "platform", "dimension", "bucket",
                "impressions", "clicks", "spend"]
NUMERIC_DEMO = ["impressions", "clicks", "spend"]

# Canal de veiculacao por conta e por dia: no Meta a plataforma (Facebook, Instagram,
# WhatsApp...), no Google o tipo de campanha (Pesquisa, PMax, YouTube...), no TikTok o
# posicionamento. Mesmo schema para as tres -> a secao e um groupby simples.
CANAIS_COLUMNS = ["date", "account_id", "platform", "canal",
                  "impressions", "clicks", "conversions", "spend"]
NUMERIC_CANAIS = ["impressions", "clicks", "conversions", "spend"]

# TikTok usa o MESMO schema do Meta (mesmas colunas/numericas): assim passa pelos
# mesmos agregadores (metrics/analytics) sem tratamento especial. So e populado para
# clientes com tiktok_advertiser_ids; senao fica vazio e o TikTok nao aparece.
TIKTOK_COLUMNS = META_COLUMNS
NUMERIC_TIKTOK = NUMERIC_META
# LinkedIn tambem entra no schema do Meta (connectors/linkedin_api.py monta as linhas).
LINKEDIN_COLUMNS = META_COLUMNS
NUMERIC_LINKEDIN = NUMERIC_META

# Instagram (organico): seguidores por conta e por dia. Vem da Instagram Graph API
# com o MESMO token do Meta Ads (escopos instagram_basic/instagram_manage_insights).
INSTAGRAM_COLUMNS = ["date", "ig_id", "username", "account", "new_followers", "followers_total"]
NUMERIC_INSTAGRAM = ["new_followers", "followers_total"]


# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
SEGUIDORES_FILE = os.path.join(BASE_DIR, "seguidores_manuais.json")


def load_seguidores_manuais() -> dict:
    """Seguidores anotados a mao, por cliente, para redes sem API de leitura.

    Existe porque o LinkedIn so entrega numero de seguidores pelo Community
    Management API, que exige app exclusivo e aprovacao de parceiro, e o termo
    de uso dele proibe ler a pagina por robo. Arquivo opcional: sem ele a secao
    simplesmente nao aparece. Lido a cada requisicao (e minusculo), entao
    registrar um numero novo aparece na hora, sem restart."""
    try:
        with open(SEGUIDORES_FILE, encoding="utf-8") as fh:
            return json.load(fh) or {}
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001
        print(f"[seguidores] falha ao ler {SEGUIDORES_FILE}: {exc}")
        return {}


def load_config() -> dict:
    path = os.path.join(BASE_DIR, "config.json")
    if not os.path.exists(path):
        path = os.path.join(BASE_DIR, "config.example.json")
    with open(path, "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    return apply_env_overrides(cfg)


def _split(value):
    return [v.strip() for v in str(value).split(",") if v.strip()]


def apply_env_overrides(cfg: dict) -> dict:
    """Variaveis de ambiente sobrescrevem o config.json (recomendado em producao)."""
    cfg.setdefault("api", {}).setdefault("meta", {})
    cfg["api"].setdefault("google_ads", {})
    cfg["api"].setdefault("tiktok", {})
    cfg["api"].setdefault("linkedin", {})
    cfg.setdefault("google_sheets", {})
    cfg.setdefault("auth", {})
    cfg.setdefault("cron", {})
    e = os.environ

    if e.get("FONTE_DADOS"):
        cfg["fonte_dados"] = e["FONTE_DADOS"]
    if e.get("DIAS_BUSCA"):
        cfg["api"]["dias_busca"] = int(e["DIAS_BUSCA"])

    m = cfg["api"]["meta"]
    if e.get("META_ACCESS_TOKEN"):
        m["access_token"] = e["META_ACCESS_TOKEN"]
    if e.get("META_AD_ACCOUNT_IDS"):
        m["ad_account_ids"] = _split(e["META_AD_ACCOUNT_IDS"])
    if e.get("META_API_VERSION"):
        m["api_version"] = e["META_API_VERSION"]

    g = cfg["api"]["google_ads"]
    for env_key, cfg_key in [
        ("GOOGLE_DEVELOPER_TOKEN", "developer_token"),
        ("GOOGLE_CLIENT_ID", "client_id"),
        ("GOOGLE_CLIENT_SECRET", "client_secret"),
        ("GOOGLE_REFRESH_TOKEN", "refresh_token"),
        ("GOOGLE_LOGIN_CUSTOMER_ID", "login_customer_id"),
    ]:
        if e.get(env_key):
            g[cfg_key] = e[env_key]
    if e.get("GOOGLE_CUSTOMER_IDS"):
        g["customer_ids"] = _split(e["GOOGLE_CUSTOMER_IDS"])

    tk = cfg["api"]["tiktok"]
    if e.get("TIKTOK_ACCESS_TOKEN"):
        tk["access_token"] = e["TIKTOK_ACCESS_TOKEN"]
    if e.get("TIKTOK_APP_ID"):
        tk["app_id"] = e["TIKTOK_APP_ID"]
    if e.get("TIKTOK_SECRET"):
        tk["secret"] = e["TIKTOK_SECRET"]
    if e.get("TIKTOK_ADVERTISER_IDS"):
        tk["advertiser_ids"] = _split(e["TIKTOK_ADVERTISER_IDS"])
    if e.get("TIKTOK_API_VERSION"):
        tk["api_version"] = e["TIKTOK_API_VERSION"]

    # LinkedIn: o token OAuth fica em linkedin_token.json (connectors/linkedin_auth.py);
    # aqui so as contas de anuncio que o deploy coleta.
    li = cfg["api"]["linkedin"]
    if e.get("LINKEDIN_ACCOUNT_IDS"):
        li["account_ids"] = _split(e["LINKEDIN_ACCOUNT_IDS"])

    gs = cfg["google_sheets"]
    if e.get("META_CSV_URL"):
        gs["meta_csv_url"] = e["META_CSV_URL"]
    if e.get("GOOGLE_CSV_URL"):
        gs["google_csv_url"] = e["GOOGLE_CSV_URL"]
    if e.get("SPREADSHEET_ID"):
        gs["spreadsheet_id"] = e["SPREADSHEET_ID"]
    if e.get("GOOGLE_SERVICE_ACCOUNT_JSON"):
        # JSON cru da conta de servico (util em hosts sem upload de arquivo)
        gs["service_account_info"] = json.loads(e["GOOGLE_SERVICE_ACCOUNT_JSON"])

    if e.get("DASH_USER"):
        cfg["auth"]["usuario"] = e["DASH_USER"]
    if e.get("DASH_PASSWORD"):
        cfg["auth"]["senha"] = e["DASH_PASSWORD"]
    if e.get("CRON_TOKEN"):
        cfg["cron"]["token"] = e["CRON_TOKEN"]

    return cfg


def only_digits(value: str) -> str:
    return "".join(ch for ch in str(value) if ch.isdigit())


def load_clients() -> dict:
    """Carrega clients.json (mapa de clientes -> contas + senha). Multi-tenant.

    Estrutura:
      {"admin": {"senha": "..."},
       "clientes": [{"key","nome","senha","meta_ad_account_ids":[],
                     "google_customer_ids":[]}]}
    Retorna {} se nao existir (modo single-tenant via DASH_PASSWORD).
    """
    path = os.path.join(BASE_DIR, "clients.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    # indexa por key e normaliza ids para digitos
    for c in data.get("clientes", []):
        c["_meta_ids"] = {only_digits(x) for x in c.get("meta_ad_account_ids", []) if x}
        c["_google_ids"] = {only_digits(x) for x in c.get("google_customer_ids", []) if x}
        # TikTok: so clientes com tiktok_advertiser_ids veem dados/secao TikTok.
        c["_tiktok_ids"] = {only_digits(x) for x in c.get("tiktok_advertiser_ids", []) if x}
        # LinkedIn: so clientes com linkedin_account_ids veem dados/opcao LinkedIn.
        c["_linkedin_ids"] = {only_digits(x) for x in c.get("linkedin_account_ids", []) if x}
        # Instagram: so clientes com instagram_ids veem a secao de seguidores.
        c["_instagram_ids"] = {only_digits(x) for x in c.get("instagram_ids", []) if x}
        # Idioma da interface ("pt" padrao, "en" para clientes internacionais) e
        # moeda FORCADA (opcional). Sem "moeda", vale a que veio da API da conta.
        c["_idioma"] = str(c.get("idioma") or "pt").lower()
        c["_moeda"] = (str(c["moeda"]).upper() if c.get("moeda") else None)
        # Funil proprio (opcional): lista de etapas em clients.json, ex.
        # "funil_ordem": ["impressions","video_views","add_to_cart",
        #                 "initiate_checkout","purchases"]. Vazio = funil do deploy.
        _fo = c.get("funil_ordem")
        if isinstance(_fo, str):
            _fo = _fo.split(",")
        c["_funil_ordem"] = [str(k).strip() for k in (_fo or []) if str(k).strip()]
    for a in data.get("agencias", []):
        a["_idioma"] = str(a.get("idioma") or "pt").lower()
        a["_moeda"] = (str(a["moeda"]).upper() if a.get("moeda") else None)
    return data


# ----------------------------------------------------------------------------
# Normalizacao
# ----------------------------------------------------------------------------
def _coerce(df: pd.DataFrame, columns: list[str], numeric: list[str]) -> pd.DataFrame:
    for col in columns:
        if col not in df.columns:
            df[col] = 0 if col in numeric else ""
    df = df[columns].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in numeric:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    # Colunas de TEXTO: NaN vira "" (ex.: keyword/ad_group/adset vazios, que o read_csv le
    # como NaN). Sem isto, um texto nulo viraria `NaN` no JSON — invalido p/ o JSON.parse do
    # navegador, quebrando TODO o render do dashboard.
    text_cols = [c for c in columns if c not in numeric and c != "date"]
    if text_cols:
        df[text_cols] = df[text_cols].fillna("")
    df = df.dropna(subset=["date"])
    # objetivo normalizado em minusculas/sem espacos (so nos schemas de Ads; o do
    # Instagram, por exemplo, nao tem essa coluna)
    if "objective" in df.columns:
        df["objective"] = (
            df["objective"].astype(str).str.strip().str.lower().replace("", "outros")
        )
    return df


# ----------------------------------------------------------------------------
# Leitores
# ----------------------------------------------------------------------------
def _read_csv_url(url: str) -> pd.DataFrame:
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return pd.read_csv(io.StringIO(resp.text))


def _read_service_account(cfg: dict, aba: str) -> pd.DataFrame:
    import gspread
    from google.oauth2.service_account import Credentials

    gs = cfg["google_sheets"]
    scopes = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    if gs.get("service_account_info"):
        creds = Credentials.from_service_account_info(gs["service_account_info"], scopes=scopes)
    else:
        cred_path = gs["service_account_json"]
        if not os.path.isabs(cred_path):
            cred_path = os.path.join(BASE_DIR, cred_path)
        creds = Credentials.from_service_account_file(cred_path, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(gs["spreadsheet_id"]).worksheet(aba)
    return pd.DataFrame(sheet.get_all_records())


# ----------------------------------------------------------------------------
# Dados de exemplo (sinteticos, deterministicos)
# ----------------------------------------------------------------------------
def _synthesize(days: int = 75):
    """Gera Meta + Google realistas terminando hoje. Semente fixa = reproducivel."""
    rng = np.random.default_rng(42)
    end = pd.Timestamp(datetime.today().date())
    dates = [end - timedelta(days=i) for i in range(days - 1, -1, -1)]

    # (conta, objetivo, campanha, [anuncios], faixa_invest_dia, base_metricas)
    meta_plan = [
        ("Loja Moda Bella", "vendas", "Vendas | Catalogo Verao",
         ["Vestido Floral - Carrossel", "Promo Frete Gratis - Video", "Look Praia - Imagem"],
         (180, 320)),
        ("Loja Moda Bella", "trafego", "Trafego | Blog Tendencias",
         ["Tendencias 2026 - Imagem", "Guia de Estilo - Video"],
         (40, 90)),
        ("Loja Moda Bella", "video", "Video | Lancamento Colecao",
         ["Reels Colecao - Video", "Making Of - Video"],
         (35, 75)),
        ("Clinica Sorriso", "leads", "Leads | Implante Dentario",
         ["Avaliacao Gratis - Imagem", "Antes e Depois - Carrossel", "Depoimento - Video"],
         (90, 160)),
        ("Restaurante Sabor", "mensagens", "Mensagens | Reservas WhatsApp",
         ["Rodizio Sexta - Imagem", "Happy Hour - Video"],
         (50, 110)),
        ("Restaurante Sabor", "visitas_instagram", "Engajamento | Perfil",
         ["Bastidores Cozinha - Reels", "Prato do Chef - Imagem"],
         (25, 60)),
    ]

    google_plan = [
        # PMax: dois GRUPOS DE RECURSOS na mesma campanha (sem palavra-chave)
        ("Loja Moda Bella", "vendas", "PMax | Loja Online", "Performance Max",
         "Grupo de recursos — Vestidos", [""], (80, 150)),
        ("Loja Moda Bella", "vendas", "PMax | Loja Online", "Performance Max",
         "Grupo de recursos — Moda Praia", [""], (60, 130)),
        ("Loja Moda Bella", "video", "Video | YouTube Colecao", "Video", "—",
         [""],
         (30, 70)),
        ("Clinica Sorriso", "leads", "Search | Implante", "Search", "Grupo de anúncios — Implante",
         ["implante dentario preco", "clinica implante dentario", "dentista perto de mim",
          "implante dentario sao paulo"],
         (110, 200)),
    ]

    def season(i, n):  # leve tendencia de alta + ruido semanal
        return 1.0 + 0.18 * (i / n) + 0.10 * np.sin(i / 7 * 2 * np.pi)

    meta_rows = []
    for ai, (acc, obj, camp, ads, (lo, hi)) in enumerate(meta_plan):
        for adi, ad in enumerate(ads):
            seed = f"{acc}-{ad}".replace(" ", "")
            thumb = f"https://picsum.photos/seed/{abs(hash(seed)) % 100000}/480/360"
            share = rng.uniform(0.6, 1.4)
            for i, d in enumerate(dates):
                s = season(i, days) * share
                spend = rng.uniform(lo, hi) / len(ads) * s
                cpm = rng.uniform(12, 32)
                impressions = max(1, int(spend / cpm * 1000))
                reach = int(impressions / rng.uniform(1.3, 2.4))
                ctr = rng.uniform(0.008, 0.028)
                clicks = max(0, int(impressions * ctr))
                link_clicks = int(clicks * rng.uniform(0.6, 0.9))
                row = dict(
                    date=d.date(), account=acc, account_id=acc, objective=obj, campaign=camp,
                    adset=f"{obj}-conjunto-{adi+1}", ad_name=ad,
                    ad_thumbnail_url=thumb, ad_permalink="https://facebook.com/ads/library",
                    impressions=impressions, reach=reach,
                    frequency=round(impressions / max(reach, 1), 2),
                    clicks=clicks, link_clicks=link_clicks, spend=round(spend, 2),
                    messaging_conversations=0, profile_visits=0, leads=0,
                    purchases=0, purchase_value=0.0,
                    site_visits=0, video_views=0, engagement=0,
                )
                if obj == "vendas":
                    cr = rng.uniform(0.02, 0.06)
                    row["purchases"] = int(link_clicks * cr)
                    row["purchase_value"] = round(row["purchases"] * rng.uniform(140, 260), 2)
                    row["site_visits"] = int(link_clicks * rng.uniform(0.6, 0.85))
                elif obj == "leads":
                    row["leads"] = int(link_clicks * rng.uniform(0.08, 0.18))
                    row["site_visits"] = int(link_clicks * rng.uniform(0.6, 0.85))
                elif obj == "mensagens":
                    row["messaging_conversations"] = int(link_clicks * rng.uniform(0.15, 0.35))
                elif obj == "visitas_instagram":
                    row["profile_visits"] = int(clicks * rng.uniform(0.4, 0.8))
                    row["engagement"] = int(clicks * rng.uniform(1.5, 3.0))
                elif obj == "trafego":
                    row["site_visits"] = int(link_clicks * rng.uniform(0.7, 0.9))
                elif obj == "video":
                    row["video_views"] = int(impressions * rng.uniform(0.18, 0.35))
                    row["engagement"] = int(clicks * rng.uniform(1.2, 2.2))
                meta_rows.append(row)

    google_rows = []
    for acc, obj, camp, ctype, agroup, kws, (lo, hi) in google_plan:
        for kwi, kw in enumerate(kws):
            share = rng.uniform(0.5, 1.5)
            for i, d in enumerate(dates):
                s = season(i, days) * share
                cost = rng.uniform(lo, hi) / len(kws) * s
                cpc = rng.uniform(0.8, 3.5)
                clicks = max(0, int(cost / cpc))
                ctr = rng.uniform(0.03, 0.12)
                impressions = max(clicks, int(clicks / max(ctr, 0.01)))
                video_views = 0
                interactions = clicks
                if obj == "vendas":
                    conv = int(clicks * rng.uniform(0.02, 0.07))
                    cval = round(conv * rng.uniform(150, 280), 2)
                elif obj == "video":
                    conv = 0
                    cval = 0.0
                    video_views = int(impressions * rng.uniform(0.2, 0.4))
                    interactions = video_views
                else:
                    conv = int(clicks * rng.uniform(0.05, 0.14))
                    cval = 0.0
                google_rows.append(dict(
                    date=d.date(), account=acc, account_id=acc, objective=obj, campaign=camp,
                    campaign_type=ctype, ad_group=agroup, keyword=kw,
                    match_type=rng.choice(["Ampla", "Frase", "Exata"]),
                    impressions=impressions, clicks=clicks, cost=round(cost, 2),
                    conversions=conv, conversion_value=cval,
                    video_views=video_views, interactions=interactions,
                ))

    # ---- Geo (cliques por cidade, com coordenadas) ----
    cities = [
        ("Cuiaba", -15.601, -56.097), ("Varzea Grande", -15.646, -56.132),
        ("Rondonopolis", -16.470, -54.635), ("Sinop", -11.864, -55.502),
        ("Sao Paulo", -23.550, -46.633), ("Campinas", -22.905, -47.060),
        ("Rio de Janeiro", -22.906, -43.172),
    ]
    geo_rows = []
    accounts = sorted({r["account_id"] for r in meta_rows} | {r["account_id"] for r in google_rows})
    for acc in accounts:
        weights = rng.uniform(0.3, 1.0, size=len(cities))
        weights = weights / weights.sum()
        for i, d in enumerate(dates):
            base = rng.uniform(20, 120) * season(i, days)
            for (city, lat, lng), w in zip(cities, weights):
                clk = int(base * w)
                if clk <= 0:
                    continue
                for plat in ("meta", "google"):
                    geo_rows.append(dict(
                        date=d.date(), account_id=acc, platform=plat, city=city,
                        lat=lat, lng=lng, clicks=int(clk * rng.uniform(0.4, 0.6)),
                    ))

    # Publico de exemplo: distribuicao fixa por genero e faixa etaria, escalada pelos
    # cliques do dia (mesma semente -> reproducivel).
    demo_rows = []
    generos = [("feminino", 0.58), ("masculino", 0.40), ("desconhecido", 0.02)]
    idades = [("18-24", 0.12), ("25-34", 0.30), ("35-44", 0.26), ("45-54", 0.17),
              ("55-64", 0.10), ("65+", 0.05)]
    for acc in accounts:
        for i, d in enumerate(dates):
            base_clk = rng.uniform(40, 200) * season(i, days)
            for plat in ("meta", "google"):
                for dim, dist in (("genero", generos), ("idade", idades)):
                    for bucket, w in dist:
                        clk = int(base_clk * w * rng.uniform(0.8, 1.2))
                        if clk <= 0:
                            continue
                        demo_rows.append(dict(
                            date=d.date(), account_id=acc, platform=plat, dimension=dim,
                            bucket=bucket, impressions=int(clk * rng.uniform(25, 60)),
                            clicks=clk, spend=round(clk * rng.uniform(0.6, 1.8), 2),
                        ))

    # Canais de exemplo: participacao fixa por plataforma, escalada pelo dia.
    canais_rows = []
    mix = {"meta": [("Facebook", 0.46), ("Instagram", 0.34), ("WhatsApp", 0.12),
                    ("Audience Network", 0.05), ("Threads", 0.03)],
           "google": [("Pesquisa", 0.44), ("Performance Max", 0.28), ("YouTube", 0.18),
                      ("Display", 0.10)]}
    for acc in accounts:
        for i, d in enumerate(dates):
            base_imp = rng.uniform(3000, 12000) * season(i, days)
            for plat, dist in mix.items():
                for canal, w in dist:
                    imp = int(base_imp * w * rng.uniform(0.85, 1.15))
                    if imp <= 0:
                        continue
                    clk = int(imp * rng.uniform(0.008, 0.03))
                    canais_rows.append(dict(
                        date=d.date(), account_id=acc, platform=plat, canal=canal,
                        impressions=imp, clicks=clk,
                        conversions=int(clk * rng.uniform(0.02, 0.12)),
                        spend=round(clk * rng.uniform(0.6, 1.9), 2)))

    return (pd.DataFrame(meta_rows), pd.DataFrame(google_rows), pd.DataFrame(geo_rows),
            pd.DataFrame(demo_rows), pd.DataFrame(canais_rows))


def _synthesize_instagram(days: int = 60) -> pd.DataFrame:
    """Seguidores de exemplo (modo sample), para desenvolver/testar a secao sem API."""
    rng = np.random.default_rng(7)
    end = pd.Timestamp(today_br()) - pd.Timedelta(days=1)
    plano = [
        ("17841400000000001", "lojamodabella", "Loja Moda Bella", 18420, (25, 90)),
        ("17841400000000002", "clinicasorriso", "Clínica Sorriso", 4310, (5, 28)),
        ("17841400000000003", "restaurantesabor", "Restaurante Sabor", 9765, (10, 45)),
    ]
    rows = []
    for ig_id, user, page, total, (lo, hi) in plano:
        for i in range(days):
            d = (end - pd.Timedelta(days=days - 1 - i)).date()
            rows.append({
                "date": d.isoformat(), "ig_id": ig_id, "username": user, "account": page,
                "new_followers": float(int(rng.integers(lo, hi))),
                "followers_total": float(total),
            })
    return pd.DataFrame(rows, columns=INSTAGRAM_COLUMNS)


def _ensure_sample_files():
    """Grava os CSVs de exemplo em sample_data/ (modelo de planilha + geo)."""
    os.makedirs(SAMPLE_DIR, exist_ok=True)
    meta_path = os.path.join(SAMPLE_DIR, "meta_ads.csv")
    google_path = os.path.join(SAMPLE_DIR, "google_ads.csv")
    geo_path = os.path.join(SAMPLE_DIR, "geo.csv")
    demo_path = os.path.join(SAMPLE_DIR, "publico.csv")
    canais_path = os.path.join(SAMPLE_DIR, "canais.csv")
    if not all(os.path.exists(p) for p in (meta_path, google_path, geo_path, demo_path, canais_path)):
        meta_df, google_df, geo_df, demo_df, canais_df = _synthesize()
        meta_df.to_csv(meta_path, index=False, encoding="utf-8")
        google_df.to_csv(google_path, index=False, encoding="utf-8")
        geo_df.to_csv(geo_path, index=False, encoding="utf-8")
        demo_df.to_csv(demo_path, index=False, encoding="utf-8")
        canais_df.to_csv(canais_path, index=False, encoding="utf-8")
    return meta_path, google_path, geo_path, demo_path, canais_path


# ----------------------------------------------------------------------------
# Cache
# ----------------------------------------------------------------------------
def _coerce_geo(df: pd.DataFrame) -> pd.DataFrame:
    for col in GEO_COLUMNS:
        if col not in df.columns:
            df[col] = 0 if col in NUMERIC_GEO else ""
    df = df[GEO_COLUMNS].copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in NUMERIC_GEO:
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    # 'level' default = estado (dados antigos/exemplo nao tinham essa coluna)
    df["level"] = df["level"].replace("", "estado").fillna("estado")
    return df.dropna(subset=["date"])


class DataStore:
    def __init__(self, config: dict):
        self.config = config
        self.meta = pd.DataFrame(columns=META_COLUMNS)
        self.google = pd.DataFrame(columns=GOOGLE_COLUMNS)
        self.tiktok = pd.DataFrame(columns=TIKTOK_COLUMNS)
        self.linkedin = pd.DataFrame(columns=LINKEDIN_COLUMNS)
        self.instagram = pd.DataFrame(columns=INSTAGRAM_COLUMNS)
        self.geo = pd.DataFrame(columns=GEO_COLUMNS)
        self.demo = pd.DataFrame(columns=DEMO_COLUMNS)
        self.canais = pd.DataFrame(columns=CANAIS_COLUMNS)
        # account_id (so digitos) -> codigo ISO da moeda, vindo da API de cada
        # plataforma. Vazio = tudo cai no padrao (BRL).
        self.moedas: dict[str, str] = {}
        self.updated_at: datetime | None = None
        self.source_label = "—"
        self._lock = threading.Lock()

    def refresh(self) -> dict:
        with self._lock:
            meta_df, google_df, tiktok_df, geo_df, demo_df, canais_df, label = self._load_raw()
            self.meta = _coerce(meta_df, META_COLUMNS, NUMERIC_META)
            self.google = _coerce(google_df, GOOGLE_COLUMNS, NUMERIC_GOOGLE)
            self.tiktok = _coerce(tiktok_df, TIKTOK_COLUMNS, NUMERIC_TIKTOK)
            self.instagram = _coerce(self._load_instagram(label), INSTAGRAM_COLUMNS, NUMERIC_INSTAGRAM)
            self.linkedin = _coerce(self._load_linkedin(label), LINKEDIN_COLUMNS, NUMERIC_LINKEDIN)
            if not self.linkedin.empty and "LinkedIn" not in label:
                label = label.replace(" Ads)", " + LinkedIn Ads)")
            self.geo = _coerce_geo(geo_df)
            self.demo = _coerce(demo_df, DEMO_COLUMNS, NUMERIC_DEMO)
            self.canais = _coerce(canais_df, CANAIS_COLUMNS, NUMERIC_CANAIS)
            self.moedas = self._load_moedas(label)
            self.updated_at = now_br()
            self.source_label = label
            self._save_cache()
        return {
            "updated_at": self.updated_at.isoformat(),
            "source": self.source_label,
            "meta_rows": len(self.meta),
            "google_rows": len(self.google),
            "tiktok_rows": len(self.tiktok),
            "linkedin_rows": len(self.linkedin),
            "instagram_rows": len(self.instagram),
            "demo_rows": len(self.demo),
            "canais_rows": len(self.canais),
        }

    def _load_instagram(self, label: str) -> pd.DataFrame:
        """Seguidores do Instagram (organico). Fica FORA do _load_raw de proposito:
        e uma fonte independente (Instagram Graph API) e nunca pode derrubar o Ads —
        qualquer falha aqui vira DataFrame vazio e o dashboard segue normal."""
        api = self.config.get("api", {})
        dias = int(api.get("dias_busca", 60))
        if label == "Dados de exemplo":
            return _synthesize_instagram(min(dias, 60))
        # O conector varre TODAS as contas de IG do usuario de sistema. Num dashboard
        # dedicado a um cliente isso traria dados de terceiros para o cache, entao:
        #   INSTAGRAM_OFF=1        -> nao busca nada
        #   INSTAGRAM_IDS=a,b,c    -> busca so essas contas
        if os.environ.get("INSTAGRAM_OFF") == "1":
            return pd.DataFrame(columns=INSTAGRAM_COLUMNS)
        permitidos = {only_digits(x) for x in _split(os.environ.get("INSTAGRAM_IDS", "")) if x}
        try:
            from connectors import instagram_api
            df = instagram_api.fetch(api.get("meta", {}), dias)
            if permitidos and len(df):
                df = df[df["ig_id"].astype(str).map(only_digits).isin(permitidos)]
            return df
        except Exception as exc:  # noqa: BLE001
            print(f"[instagram] fetch falhou (ignorado): {exc}")
            return pd.DataFrame(columns=INSTAGRAM_COLUMNS)

    def _load_linkedin(self, label: str) -> pd.DataFrame:
        """LinkedIn Ads: so com contas em LINKEDIN_ACCOUNT_IDS e token OAuth valido.
        Best-effort, no molde do Instagram: nao derruba o refresh. Se a API falhar,
        MANTEM o que ja havia no store em vez de gravar vazio por cima."""
        vazio = pd.DataFrame(columns=LINKEDIN_COLUMNS)
        cfg = self.config.get("api", {}).get("linkedin", {})
        if label == "Dados de exemplo" or not cfg.get("account_ids"):
            return vazio
        try:
            from connectors import linkedin_api
            dias = int(self.config.get("api", {}).get("dias_busca", 60))
            df = linkedin_api.fetch(cfg, dias)
            print(f"[linkedin] {len(df)} linha(s) coletada(s)")
            return df if not df.empty else vazio
        except Exception as exc:  # noqa: BLE001
            print(f"[linkedin] fetch falhou, mantendo dados anteriores: {exc}")
            return self.linkedin if getattr(self, "linkedin", None) is not None else vazio

    def _ids_configurados(self) -> set:
        """IDs de conta fixados no deploy (env/config). Vazio = descoberta automatica."""
        api = self.config.get("api", {})
        ids = set()
        for chave, campo in (("meta", "ad_account_ids"), ("google_ads", "customer_ids"),
                             ("tiktok", "advertiser_ids")):
            # LinkedIn fica de fora: sua lista e SEMPRE fixa (nao ha descoberta), entao
            # entrar aqui transformaria um deploy em descoberta automatica num "restrito"
            # e apagaria as moedas de Meta/Google. linkedin_api.currencies ja se limita a ela.
            for x in (api.get(chave, {}).get(campo) or []):
                d = only_digits(x)
                if d:
                    ids.add(d)
        return ids

    def _load_moedas(self, label: str) -> dict:
        """Moeda de cada conta, direto da API de cada plataforma. Best-effort por
        plataforma: uma falhar nao afeta as outras nem os dados de anuncios."""
        if label == "Dados de exemplo":
            return {}
        api = self.config.get("api", {})
        out = {}
        # ATENCAO: a chave do Google no config e "google_ads" (nao "google"). Usar o
        # nome do modulo aqui deixava o Google FORA do mapa, sem erro nenhum.
        for nome, cfg_key in (("meta", "meta"), ("google", "google_ads"), ("tiktok", "tiktok")):
            try:
                mod = __import__(f"connectors.{nome}_api", fromlist=["currencies"])
                achado = mod.currencies(api.get(cfg_key, {})) or {}
                out.update({only_digits(k): v for k, v in achado.items() if only_digits(k)})
            except Exception as exc:  # noqa: BLE001
                print(f"[{nome}] moedas indisponiveis: {exc}")
        # Deploy restrito a contas especificas: o mapa nao guarda moeda de conta alheia.
        alvo = self._ids_configurados()
        if alvo:
            out = {k: v for k, v in out.items() if k in alvo}
        # LinkedIn depois do filtro: currencies() so consulta as contas de LINKEDIN_ACCOUNT_IDS.
        if api.get("linkedin", {}).get("account_ids"):
            try:
                from connectors import linkedin_api
                out.update({only_digits(k): v for k, v in (linkedin_api.currencies(api["linkedin"]) or {}).items()
                            if only_digits(k)})
            except Exception as exc:  # noqa: BLE001
                print(f"[linkedin] moedas indisponiveis: {exc}")
        if out:
            print(f"[moedas] {len(out)} conta(s) mapeada(s): {sorted(set(out.values()))}")
        return out

    def _save_cache(self) -> None:
        """Persiste o store em disco (best-effort). Chamado dentro do lock no fim
        do refresh. Escreve em .tmp e faz os.replace (troca atomica)."""
        try:
            os.makedirs(os.path.dirname(STORE_CACHE), exist_ok=True)
            tmp = STORE_CACHE + ".tmp"
            with open(tmp, "wb") as fh:
                pickle.dump({
                    "meta": self.meta, "google": self.google, "tiktok": self.tiktok,
                    "linkedin": self.linkedin,
                    "instagram": self.instagram, "geo": self.geo, "demo": self.demo,
                    "canais": self.canais,
                    "moedas": self.moedas,
                    "updated_at": self.updated_at, "source_label": self.source_label,
                }, fh, protocol=pickle.HIGHEST_PROTOCOL)
            os.replace(tmp, STORE_CACHE)
        except Exception as exc:  # noqa: BLE001
            print(f"[cache] falha ao salvar store: {exc}")

    def load_cache(self, max_age_h: float = 36.0) -> bool:
        """Sobe o store a partir do cache em disco, se houver e nao estiver velho.
        Deixa o worker pronto instantaneamente apos restart/reciclagem. True se carregou."""
        try:
            if not os.path.exists(STORE_CACHE):
                return False
            with open(STORE_CACHE, "rb") as fh:
                data = pickle.load(fh)
            # to_br: pickles antigos gravaram updated_at NAIVE; converte p/ Brasilia antes
            # de comparar (comparar aware com naive levantaria TypeError e o cache nunca
            # carregaria).
            ts = to_br(data.get("updated_at"))
            if not ts or (now_br() - ts) > timedelta(hours=max_age_h):
                return False
            with self._lock:
                self.meta = data["meta"]
                self.google = data["google"]
                # retrocompat: pickles antigos (pre-TikTok) nao tem a chave 'tiktok'
                tk = data.get("tiktok")
                self.tiktok = tk if tk is not None else pd.DataFrame(columns=TIKTOK_COLUMNS)
                # retrocompat: pickles anteriores ao LinkedIn nao tem a chave
                lk = data.get("linkedin")
                self.linkedin = lk if lk is not None else pd.DataFrame(columns=LINKEDIN_COLUMNS)
                # retrocompat: pickles anteriores ao Instagram nao tem a chave
                ig = data.get("instagram")
                self.instagram = ig if ig is not None else pd.DataFrame(columns=INSTAGRAM_COLUMNS)
                self.geo = data["geo"]
                # retrocompat: pickles anteriores ao publico nao tem a chave
                dm = data.get("demo")
                self.demo = dm if dm is not None else pd.DataFrame(columns=DEMO_COLUMNS)
                # retrocompat: pickles anteriores aos canais nao tem a chave
                cn = data.get("canais")
                self.canais = cn if cn is not None else pd.DataFrame(columns=CANAIS_COLUMNS)
                # retrocompat: pickles anteriores as moedas nao tem a chave
                self.moedas = data.get("moedas") or {}
                self.updated_at = ts
                self.source_label = data.get("source_label") or "—"
            return True
        except Exception as exc:  # noqa: BLE001
            print(f"[cache] falha ao carregar store: {exc}")
            return False

    def _load_raw(self):
        mode = self.config.get("fonte_dados", "auto")
        gs = self.config.get("google_sheets", {})

        empty_geo = pd.DataFrame(columns=GEO_COLUMNS)
        empty_tiktok = pd.DataFrame(columns=TIKTOK_COLUMNS)
        empty_demo = pd.DataFrame(columns=DEMO_COLUMNS)
        empty_canais = pd.DataFrame(columns=CANAIS_COLUMNS)

        def via_service_account():
            return (
                _read_service_account(self.config, gs.get("aba_meta", "meta_ads")),
                _read_service_account(self.config, gs.get("aba_google", "google_ads")),
                empty_tiktok, empty_geo, empty_demo, empty_canais,
                "Google Sheets (conta de servico)",
            )

        def via_csv():
            return (
                _read_csv_url(gs["meta_csv_url"]),
                _read_csv_url(gs["google_csv_url"]),
                empty_tiktok, empty_geo, empty_demo, empty_canais,
                "Google Sheets (CSV publicado)",
            )

        def via_sample():
            meta_path, google_path, geo_path, demo_path, canais_path = _ensure_sample_files()
            meta_sample = pd.read_csv(meta_path)
            # TikTok de exemplo (so p/ testar a UI): TIKTOK_SAMPLE=1 reaproveita uma fatia
            # do sample do Meta como um advertiser TikTok ficticio (id 7000000000001).
            tiktok_sample = empty_tiktok
            if os.environ.get("TIKTOK_SAMPLE") == "1" and not meta_sample.empty:
                tk = meta_sample[meta_sample["objective"].isin(["mensagens", "video", "vendas"])].copy()
                tk["account"] = "TikTok — Loja Bella"
                tk["account_id"] = "7000000000001"
                tk["campaign"] = "[TikTok] " + tk["campaign"].astype(str)
                tiktok_sample = tk
            return (
                meta_sample,
                pd.read_csv(google_path),
                tiktok_sample, pd.read_csv(geo_path), pd.read_csv(demo_path),
                pd.read_csv(canais_path),
                "Dados de exemplo",
            )

        def via_api():
            from connectors import meta_api, google_api, tiktok_api
            api = self.config.get("api", {})
            dias = int(api.get("dias_busca", 60))
            meta_df = meta_api.fetch(api.get("meta", {}), dias)
            google_df = google_api.fetch(api.get("google_ads", {}), dias)
            # TikTok: so busca se houver access_token configurado; resiliente (nao derruba
            # Meta/Google se falhar). Vazio = TikTok nao aparece em lugar nenhum.
            tiktok_df = empty_tiktok
            if api.get("tiktok", {}).get("access_token"):
                try:
                    tiktok_df = tiktok_api.fetch(api.get("tiktok", {}), dias)
                except Exception as exc:  # noqa: BLE001
                    print(f"[tiktok] fetch falhou: {exc}")
            if meta_df.empty and google_df.empty and tiktok_df.empty:
                raise RuntimeError("API sem dados (verifique tokens/contas).")
            # Falha PARCIAL de UMA plataforma: se ela esta configurada mas voltou VAZIA
            # enquanto a OUTRA trouxe dados, isso e anomalo (token expirado, descoberta de
            # contas falhando por nproc/grpc, rate limit...) e NAO pode virar cache: gravar
            # zeros apaga os dados de todos os clientes daquela plataforma. Abortamos o
            # refresh para preservar o ultimo cache bom; o proximo seed recupera.
            # (Os conectores engolem erro por conta e retornam DataFrame vazio, entao sem
            # este guard a falha passaria silenciosa.)
            g_api = api.get("google_ads", {})
            google_ligado = bool(g_api.get("developer_token") and g_api.get("refresh_token")
                                 and (g_api.get("customer_ids") or g_api.get("login_customer_id")))
            meta_ligado = bool(api.get("meta", {}).get("access_token"))
            # Escape hatch por deploy: num dashboard restrito a UM cliente, "0 linhas"
            # numa plataforma pode ser legitimo (ele simplesmente nao veicula la). Sem
            # isso o guard aborta todo refresh para sempre. Ex.: PLATAFORMAS_SEM_DADOS=google
            sem_dados_ok = {p.strip().lower()
                            for p in os.environ.get("PLATAFORMAS_SEM_DADOS", "").split(",")
                            if p.strip()}
            if google_ligado and google_df.empty and not meta_df.empty                     and "google" not in sem_dados_ok:
                raise RuntimeError("Google Ads configurado retornou 0 linhas (descoberta/fetch "
                                   "falhou) — refresh abortado para preservar o cache anterior.")
            if meta_ligado and meta_df.empty and not google_df.empty                     and "meta" not in sem_dados_ok:
                raise RuntimeError("Meta Ads configurado retornou 0 linhas (token expirado? "
                                   "contas inacessiveis?) — refresh abortado para preservar o "
                                   "cache anterior.")
            geo_frames = []
            try:
                geo_frames.append(meta_api.fetch_geo(api.get("meta", {}), dias))
            except Exception as exc:  # noqa: BLE001
                print(f"[geo] meta falhou: {exc}")
            try:
                geo_frames.append(google_api.fetch_geo(api.get("google_ads", {}), dias))
            except Exception as exc:  # noqa: BLE001
                print(f"[geo] google falhou: {exc}")
            if api.get("tiktok", {}).get("access_token"):
                try:
                    geo_frames.append(tiktok_api.fetch_geo(api.get("tiktok", {}), dias))
                except Exception as exc:  # noqa: BLE001
                    print(f"[geo] tiktok falhou: {exc}")
            # Geo por CIDADE (user_location_view) so qun GEO_CIDADE_ON=1: a consulta e
            # pesada/lenta e estava travando o refresh sincrono. Mantido opcional ate
            # migrar para carga assincrona/cacheada.
            if os.environ.get("GEO_CIDADE_ON") == "1":
                try:
                    geo_frames.append(google_api.fetch_geo_city(api.get("google_ads", {}), dias))
                except Exception as exc:  # noqa: BLE001
                    print(f"[geo-cidade] google falhou: {exc}")
            geo_frames = [g for g in geo_frames if g is not None and len(g)]
            geo_df = pd.concat(geo_frames, ignore_index=True) if geo_frames else empty_geo
            # Publico (genero/faixa etaria): best-effort por plataforma, nunca derruba
            # o refresh. Vazio = a secao some no dashboard.
            demo_frames = []
            for nome, fn, cfg_key in (("meta", meta_api.fetch_demo, "meta"),
                                      ("google", google_api.fetch_demo, "google_ads"),
                                      ("tiktok", tiktok_api.fetch_demo, "tiktok")):
                if nome == "tiktok" and not api.get("tiktok", {}).get("access_token"):
                    continue
                try:
                    demo_frames.append(fn(api.get(cfg_key, {}), dias))
                except Exception as exc:  # noqa: BLE001
                    print(f"[publico] {nome} falhou: {exc}")
            demo_frames = [d for d in demo_frames if d is not None and len(d)]
            demo_df = pd.concat(demo_frames, ignore_index=True) if demo_frames else empty_demo
            # Canal de veiculacao: best-effort por plataforma, igual ao publico.
            canais_frames = []
            for nome, fn, cfg_key in (("meta", meta_api.fetch_canais, "meta"),
                                      ("google", google_api.fetch_canais, "google_ads"),
                                      ("tiktok", tiktok_api.fetch_canais, "tiktok")):
                if nome == "tiktok" and not api.get("tiktok", {}).get("access_token"):
                    continue
                try:
                    canais_frames.append(fn(api.get(cfg_key, {}), dias))
                except Exception as exc:  # noqa: BLE001
                    print(f"[canais] {nome} falhou: {exc}")
            canais_frames = [c for c in canais_frames if c is not None and len(c)]
            canais_df = pd.concat(canais_frames, ignore_index=True) if canais_frames else empty_canais
            label = "API (Meta + Google Ads)"
            if not tiktok_df.empty:
                label = "API (Meta + Google + TikTok Ads)"
            return meta_df, google_df, tiktok_df, geo_df, demo_df, canais_df, label

        api_cfg = self.config.get("api", {})
        has_api = bool(api_cfg.get("meta", {}).get("access_token")
                       or api_cfg.get("google_ads", {}).get("refresh_token")
                       or api_cfg.get("tiktok", {}).get("access_token"))

        if mode == "api":
            return via_api()
        if mode == "service_account":
            return via_service_account()
        if mode == "csv_publicado":
            return via_csv()
        if mode == "sample":
            return via_sample()

        # auto: tenta a melhor fonte disponivel e cai para exemplo.
        if has_api:
            try:
                return via_api()
            except Exception as exc:  # noqa: BLE001
                print(f"[dados] api falhou: {exc}")
        if gs.get("spreadsheet_id") and os.path.exists(
            os.path.join(BASE_DIR, gs.get("service_account_json", ""))
        ):
            try:
                return via_service_account()
            except Exception as exc:  # noqa: BLE001
                print(f"[dados] service_account falhou: {exc}")
        if gs.get("meta_csv_url") and gs.get("google_csv_url"):
            try:
                return via_csv()
            except Exception as exc:  # noqa: BLE001
                print(f"[dados] csv_publicado falhou: {exc}")
        return via_sample()
