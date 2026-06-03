"""Diagnostica o bloco de objetivo (ex.: Geração de leads) com dados REAIS de 1 cliente."""
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
import metrics as M  # noqa: E402
from connectors import meta_api, google_api  # noqa: E402

# NEP Objetivo
MID, GID = "1427648885223339", "2121479176"
mc = dict(d.load_config()["api"]["meta"]); mc["ad_account_ids"] = [MID]
gc = dict(d.load_config()["api"]["google_ads"]); gc["customer_ids"] = [GID]

store = d.DataStore(d.load_config())
store.meta = d._coerce(meta_api.fetch(mc, 60), d.META_COLUMNS, d.NUMERIC_META)
store.google = d._coerce(google_api.fetch(gc, 60), d.GOOGLE_COLUMNS, d.NUMERIC_GOOGLE)
store.geo = d._coerce_geo(pd.DataFrame(columns=d.GEO_COLUMNS))
print("meta linhas:", len(store.meta), "| google linhas:", len(store.google))

scope = {"meta_ids": {MID}, "google_ids": {GID}}
try:
    p = analytics.build_payload(store, days=30, scope=scope)
    for b in p.get("blocos_objetivo", []):
        print(f"\n=== BLOCO: {b['objective']} ({b['label']}) spend={b['spend']} ===")
        for c in b["cards"]:
            print(f"   card {c['key']:14} = {c['value']}")
    # foco no objetivo leads
    g = store.google
    gl = g[g["objective"] == "leads"]
    ml = store.meta[store.meta["objective"] == "leads"]
    print("\n--- leads obj: google conv =", float(gl["conversions"].sum()),
          "| meta leads =", float(ml["leads"].sum()) if len(ml) else 0)
    print("sums leads-obj:", {k: round(v, 1) for k, v in M.sums(ml, gl).items()
                              if k in ("leads", "conversions", "site_visits", "video_views", "engagement")})
except Exception:
    traceback.print_exc()
