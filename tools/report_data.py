"""Gera o payload do dashboard para UM cliente + intervalo, sem depender do store
global (carga rapida de 1 conta). Uso:
    python tools/report_data.py dr-carlos 2026-05-01 2026-05-31 /caminho/saida.json
"""
import os, sys, json
from datetime import datetime

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

# carrega .env -> os.environ (igual app.py)
envp = os.path.join(BASE, ".env")
if os.path.exists(envp):
    for raw in open(envp, encoding="utf-8"):
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k, v = raw.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

import pandas as pd
import data_sources as ds
from data_sources import (DataStore, load_clients, load_config, _coerce, _coerce_geo,
                          META_COLUMNS, GOOGLE_COLUMNS, NUMERIC_META, NUMERIC_GOOGLE, GEO_COLUMNS)
import analytics, commentary
from connectors import meta_api, google_api

key = sys.argv[1] if len(sys.argv) > 1 else "dr-carlos"
start = sys.argv[2] if len(sys.argv) > 2 else "2026-05-01"
end = sys.argv[3] if len(sys.argv) > 3 else "2026-05-31"
outp = sys.argv[4] if len(sys.argv) > 4 else "/home/markevo42/public_html/_report.json"

config = load_config()
clients = load_clients()
cli = next((c for c in clients.get("clientes", []) if c.get("key") == key), None)
if not cli:
    print("CLIENTE NAO ENCONTRADO:", key); sys.exit(1)
meta_ids = sorted(cli.get("_meta_ids", set()))
google_ids = sorted(cli.get("_google_ids", set()))
print("cliente", key, "nome", cli.get("nome"), "meta", meta_ids, "google", google_ids)

api = dict(config.get("api", {}))
mcfg = dict(api.get("meta", {})); mcfg["ad_account_ids"] = ["act_" + m for m in meta_ids]
gcfg = dict(api.get("google_ads", {})); gcfg["customer_ids"] = list(google_ids)

# dias suficientes p/ cobrir o intervalo + periodo anterior (comparativo)
dias = (datetime.now().date() - datetime.strptime(start, "%Y-%m-%d").date()).days + 35
dias = max(dias, 70)

meta_df = meta_api.fetch(mcfg, dias) if meta_ids else pd.DataFrame(columns=META_COLUMNS)
google_df = google_api.fetch(gcfg, dias) if google_ids else pd.DataFrame(columns=GOOGLE_COLUMNS)
print("fetched meta", len(meta_df), "google", len(google_df))

geo_frames = []
try:
    if meta_ids: geo_frames.append(meta_api.fetch_geo(mcfg, dias))
except Exception as e: print("geo meta falhou", e)
try:
    if google_ids: geo_frames.append(google_api.fetch_geo(gcfg, dias))
except Exception as e: print("geo google falhou", e)
geo_frames = [g for g in geo_frames if g is not None and len(g)]
geo_df = pd.concat(geo_frames, ignore_index=True) if geo_frames else pd.DataFrame(columns=GEO_COLUMNS)

store = DataStore(config)
store.meta = _coerce(meta_df, META_COLUMNS, NUMERIC_META)
store.google = _coerce(google_df, GOOGLE_COLUMNS, NUMERIC_GOOGLE)
store.geo = _coerce_geo(geo_df)
store.updated_at = datetime.now()
store.source_label = "API (Meta + Google Ads)"

scope = {"meta_ids": set(meta_ids), "google_ids": set(google_ids)}
payload = analytics.build_payload(store, account="todas", platform="todas",
                                  days=31, scope=scope, start=start, end=end)
try:
    payload["comentarios"] = commentary.generate(payload)
except Exception as e:
    print("commentary falhou", e); payload["comentarios"] = []
payload["_cliente_nome"] = cli.get("nome")
payload["_fonte"] = store.source_label

json.dump(payload, open(outp, "w", encoding="utf-8"), ensure_ascii=False, default=str)
print("OK ->", outp, "| vazio?", payload.get("vazio"),
      "| meta_rows", len(store.meta), "| google_rows", len(store.google))
