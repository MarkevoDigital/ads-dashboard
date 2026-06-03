"""Reproduz o build_payload com dados REAIS de 1 conta (rapido) p/ ver o traceback."""
import os
import sys
import traceback

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
for line in open(os.path.join(BASE, ".env"), encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
bundle = os.path.join(BASE, "win-ca-bundle.pem")
if os.path.exists(bundle):
    for k in ("GRPC_DEFAULT_SSL_ROOTS_FILE_PATH", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
        os.environ.setdefault(k, bundle)

import pandas as pd  # noqa: E402
import data_sources as d  # noqa: E402
import analytics  # noqa: E402
from connectors import meta_api, google_api  # noqa: E402

cfg = d.load_config()
mc = dict(cfg["api"]["meta"]); mc["ad_account_ids"] = ["457463684925385"]   # dr-carlos Meta
gc = dict(cfg["api"]["google_ads"]); gc["customer_ids"] = ["9152404582"]    # dr-carlos Google

store = d.DataStore(cfg)
store.meta = d._coerce(meta_api.fetch(mc, 60), d.META_COLUMNS, d.NUMERIC_META)
store.google = d._coerce(google_api.fetch(gc, 60), d.GOOGLE_COLUMNS, d.NUMERIC_GOOGLE)
store.geo = d._coerce_geo(pd.DataFrame(columns=d.GEO_COLUMNS))
print("meta linhas:", len(store.meta), "| google linhas:", len(store.google))
if len(store.meta):
    print("meta datas:", store.meta["date"].min(), "->", store.meta["date"].max())
    print("meta objetivos:", list(store.meta["objective"].unique()))

scope = {"meta_ids": {"457463684925385"}, "google_ids": {"9152404582"}}
try:
    p = analytics.build_payload(store, days=30, scope=scope)
    print("BUILD OK | vazio:", p.get("vazio"))
    print("best_ads:", len(p.get("melhores_anuncios", [])),
          "| campanhas:", len(p.get("campanhas", [])))
except Exception:
    print("=== TRACEBACK build_payload ===")
    traceback.print_exc()
