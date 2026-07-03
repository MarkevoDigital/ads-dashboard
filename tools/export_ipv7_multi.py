"""Exporta o relatorio mensal MULTI-CONTA do cliente IPV7 (geral + por conta Meta),
com comparativo do mes informado vs. o anterior, para alimentar o gerador de PDF.

Uso: python tools/export_ipv7_multi.py [YYYY-MM-01] [YYYY-MM-DD]
Default: junho/2026.
"""
import os, sys, json

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
_envp = os.path.join(BASE, ".env")
if os.path.exists(_envp):
    for _raw in open(_envp, encoding="utf-8"):
        _raw = _raw.strip()
        if _raw and not _raw.startswith("#") and "=" in _raw:
            _k, _v = _raw.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

import pandas as pd
import analytics
from data_sources import (DataStore, load_clients, load_config, _coerce,
                          META_COLUMNS, GOOGLE_COLUMNS, NUMERIC_META, NUMERIC_GOOGLE, GEO_COLUMNS)
from connectors import meta_api, google_api

start = sys.argv[1] if len(sys.argv) > 1 else "2026-06-01"
end = sys.argv[2] if len(sys.argv) > 2 else "2026-06-30"

config = load_config()
clients = load_clients()
cli = next(c for c in clients["clientes"] if c.get("key") == "ipv7")
meta_ids = sorted(cli.get("_meta_ids", set()))
google_ids = sorted(cli.get("_google_ids", set()))
lfo = bool(cli.get("leads_form_only", False))

mcfg = dict(config.get("api", {}).get("meta", {}))
mcfg["ad_account_ids"] = ["act_" + m for m in meta_ids]
gcfg = dict(config.get("api", {}).get("google_ads", {}))
gcfg["customer_ids"] = list(google_ids)

dias = 75  # cobre o mes + o anterior p/ o comparativo
meta_df = meta_api.fetch(mcfg, dias)
google_df = google_api.fetch(gcfg, dias) if google_ids else pd.DataFrame(columns=GOOGLE_COLUMNS)

store = DataStore(config)
store.meta = _coerce(meta_df, META_COLUMNS, NUMERIC_META)
store.google = _coerce(google_df, GOOGLE_COLUMNS, NUMERIC_GOOGLE)
store.geo = pd.DataFrame(columns=GEO_COLUMNS)
store.updated_at = None

names = {}
if "account_id" in store.meta.columns and len(store.meta):
    for aid, g in store.meta.groupby(store.meta["account_id"].astype(str)):
        names[aid] = str(g["account"].iloc[0]) if "account" in g.columns and len(g) else aid


def payload(ids, google):
    scope = {"meta_ids": set(str(x) for x in ids),
             "google_ids": set(google_ids) if google else set(),
             "tiktok_ids": set(), "leads_form_only": lfo}
    return analytics.build_payload(store, account="todas", platform="todas", days=30,
                                   scope=scope, start=start, end=end)


out = {
    "cliente": cli.get("nome") or "IPV7",
    "meta_ids": meta_ids, "google_ids": google_ids, "names": names, "leads_form_only": lfo,
    "overall": payload(meta_ids, True),
    "contas": [{"account_id": a, "nome": names.get(a, a), "payload": payload([a], False)}
               for a in meta_ids],
}
outp = os.path.join(BASE, "static", "_ipv7rep.json")
json.dump(out, open(outp, "w", encoding="utf-8"), ensure_ascii=False, default=str)
print("DONE accounts", len(meta_ids), "| names", names,
      "| meta_rows", len(store.meta), "| google_rows", len(store.google), "->", outp)
