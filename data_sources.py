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
import threading
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAMPLE_DIR = os.path.join(BASE_DIR, "sample_data")

# Colunas canonicas que o resto do app espera encontrar.
META_COLUMNS = [
    "date", "account", "account_id", "objective", "campaign", "adset", "ad_name",
    "ad_thumbnail_url", "ad_permalink", "impressions", "reach", "frequency",
    "clicks", "link_clicks", "spend", "messaging_conversations",
    "profile_visits", "leads", "purchases", "purchase_value",
]
GOOGLE_COLUMNS = [
    "date", "account", "account_id", "objective", "campaign", "campaign_type",
    "ad_group", "keyword", "match_type", "impressions", "clicks", "cost",
    "conversions", "conversion_value",
]

NUMERIC_META = [
    "impressions", "reach", "frequency", "clicks", "link_clicks", "spend",
    "messaging_conversations", "profile_visits", "leads", "purchases",
    "purchase_value",
]
NUMERIC_GOOGLE = [
    "impressions", "clicks", "cost", "conversions", "conversion_value",
]


# ----------------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------------
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
    df = df.dropna(subset=["date"])
    # objetivo normalizado em minusculas/sem espacos
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
        ("Loja Moda Bella", "vendas", "PMax | Loja Online", "Performance Max", "—",
         ["vestido floral", "roupa feminina online", "moda praia", "comprar vestido"],
         (150, 280)),
        ("Clinica Sorriso", "leads", "Search | Implante", "Search", "Implante Dentario",
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
                    date=d.date(), account=acc, objective=obj, campaign=camp,
                    adset=f"{obj}-conjunto-{adi+1}", ad_name=ad,
                    ad_thumbnail_url=thumb, ad_permalink="https://facebook.com/ads/library",
                    impressions=impressions, reach=reach,
                    frequency=round(impressions / max(reach, 1), 2),
                    clicks=clicks, link_clicks=link_clicks, spend=round(spend, 2),
                    messaging_conversations=0, profile_visits=0, leads=0,
                    purchases=0, purchase_value=0.0,
                )
                if obj == "vendas":
                    cr = rng.uniform(0.02, 0.06)
                    row["purchases"] = int(link_clicks * cr)
                    row["purchase_value"] = round(row["purchases"] * rng.uniform(140, 260), 2)
                elif obj == "leads":
                    row["leads"] = int(link_clicks * rng.uniform(0.08, 0.18))
                elif obj == "mensagens":
                    row["messaging_conversations"] = int(link_clicks * rng.uniform(0.15, 0.35))
                elif obj == "visitas_instagram":
                    row["profile_visits"] = int(clicks * rng.uniform(0.4, 0.8))
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
                if obj == "vendas":
                    conv = int(clicks * rng.uniform(0.02, 0.07))
                    cval = round(conv * rng.uniform(150, 280), 2)
                else:
                    conv = int(clicks * rng.uniform(0.05, 0.14))
                    cval = 0.0
                google_rows.append(dict(
                    date=d.date(), account=acc, objective=obj, campaign=camp,
                    campaign_type=ctype, ad_group=agroup, keyword=kw,
                    match_type=rng.choice(["Ampla", "Frase", "Exata"]),
                    impressions=impressions, clicks=clicks, cost=round(cost, 2),
                    conversions=conv, conversion_value=cval,
                ))

    return pd.DataFrame(meta_rows), pd.DataFrame(google_rows)


def _ensure_sample_files():
    """Grava os CSVs de exemplo em sample_data/ para servir de modelo de planilha."""
    os.makedirs(SAMPLE_DIR, exist_ok=True)
    meta_path = os.path.join(SAMPLE_DIR, "meta_ads.csv")
    google_path = os.path.join(SAMPLE_DIR, "google_ads.csv")
    if not (os.path.exists(meta_path) and os.path.exists(google_path)):
        meta_df, google_df = _synthesize()
        meta_df.to_csv(meta_path, index=False, encoding="utf-8")
        google_df.to_csv(google_path, index=False, encoding="utf-8")
    return meta_path, google_path


# ----------------------------------------------------------------------------
# Cache
# ----------------------------------------------------------------------------
class DataStore:
    def __init__(self, config: dict):
        self.config = config
        self.meta = pd.DataFrame(columns=META_COLUMNS)
        self.google = pd.DataFrame(columns=GOOGLE_COLUMNS)
        self.updated_at: datetime | None = None
        self.source_label = "—"
        self._lock = threading.Lock()

    def refresh(self) -> dict:
        with self._lock:
            meta_df, google_df, label = self._load_raw()
            self.meta = _coerce(meta_df, META_COLUMNS, NUMERIC_META)
            self.google = _coerce(google_df, GOOGLE_COLUMNS, NUMERIC_GOOGLE)
            self.updated_at = datetime.now()
            self.source_label = label
        return {
            "updated_at": self.updated_at.isoformat(),
            "source": self.source_label,
            "meta_rows": len(self.meta),
            "google_rows": len(self.google),
        }

    def _load_raw(self):
        mode = self.config.get("fonte_dados", "auto")
        gs = self.config.get("google_sheets", {})

        def via_service_account():
            return (
                _read_service_account(self.config, gs.get("aba_meta", "meta_ads")),
                _read_service_account(self.config, gs.get("aba_google", "google_ads")),
                "Google Sheets (conta de servico)",
            )

        def via_csv():
            return (
                _read_csv_url(gs["meta_csv_url"]),
                _read_csv_url(gs["google_csv_url"]),
                "Google Sheets (CSV publicado)",
            )

        def via_sample():
            meta_path, google_path = _ensure_sample_files()
            return (
                pd.read_csv(meta_path),
                pd.read_csv(google_path),
                "Dados de exemplo",
            )

        def via_api():
            from connectors import meta_api, google_api
            api = self.config.get("api", {})
            dias = int(api.get("dias_busca", 60))
            meta_df = meta_api.fetch(api.get("meta", {}), dias)
            google_df = google_api.fetch(api.get("google_ads", {}), dias)
            if meta_df.empty and google_df.empty:
                raise RuntimeError("API sem dados (verifique tokens/contas).")
            return meta_df, google_df, "API (Meta + Google Ads)"

        api_cfg = self.config.get("api", {})
        has_api = bool(api_cfg.get("meta", {}).get("access_token")
                       or api_cfg.get("google_ads", {}).get("refresh_token"))

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
