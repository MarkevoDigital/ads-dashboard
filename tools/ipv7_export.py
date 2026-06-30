"""Exporta, para UM cliente + intervalo, um JSON enxuto para alimentar o relatorio
IPV7 (template ipv7_report.py): puxa Meta+Google FRESCO das APIs, monta o payload do
dashboard e ainda traz os cliques por CIDADE (Google) do periodo exato.

Uso:
    python tools/ipv7_export.py <key> <start AAAA-MM-DD> <end AAAA-MM-DD> <saida.json>
"""
import json
import os
import sys
from datetime import datetime

# Hospedagem compartilhada (LVE) limita threads/processos. O OpenBLAS tenta abrir 1 thread
# por nucleo (dezenas) e falha ("Resource temporarily unavailable"), derrubando o import do
# pandas/numpy. Forcar 1 thread ANTES de importar pandas resolve (mesmo de seed_cache.py).
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

envp = os.path.join(BASE, ".env")
if os.path.exists(envp):
    for raw in open(envp, encoding="utf-8"):
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k, v = raw.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

import pandas as pd
import analytics
import commentary
from data_sources import (DataStore, load_clients, load_config, _coerce,
                          META_COLUMNS, GOOGLE_COLUMNS, NUMERIC_META, NUMERIC_GOOGLE, GEO_COLUMNS)
from connectors import meta_api, google_api


def _city_clicks(gcfg, google_ids, start, end):
    """Cliques por cidade (Google) no intervalo EXATO [start, end]."""
    out = []
    if not google_ids or not gcfg.get("refresh_token"):
        return out
    try:
        from connectors.google_api import _client, _CITY_BY_NORM, _norm
        client = _client(gcfg)
        svc = client.get_service("GoogleAdsService")
    except Exception as exc:  # noqa: BLE001
        print("city client falhou:", exc)
        return out
    q = ("SELECT segments.geo_target_city, metrics.clicks FROM user_location_view "
         f"WHERE segments.date BETWEEN '{start}' AND '{end}' "
         "ORDER BY metrics.clicks DESC LIMIT 40")
    agg = {}
    for cid in google_ids:
        by = {}
        try:
            for batch in svc.search_stream(customer_id=cid, query=q):
                for row in batch.results:
                    rid = str(row.segments.geo_target_city).rsplit("/", 1)[-1]
                    if rid:
                        by[rid] = by.get(rid, 0.0) + float(row.metrics.clicks)
        except Exception as exc:  # noqa: BLE001
            print(f"city {cid} falhou:", exc)
            continue
        if not by:
            continue
        names = {}
        try:
            inc = ",".join(sorted(by))
            gq = ("SELECT geo_target_constant.id, geo_target_constant.name "
                  f"FROM geo_target_constant WHERE geo_target_constant.id IN ({inc})")
            for batch in svc.search_stream(customer_id=cid, query=gq):
                for row in batch.results:
                    names[str(row.geo_target_constant.id)] = row.geo_target_constant.name
        except Exception as exc:  # noqa: BLE001
            print(f"city names {cid} falhou:", exc)
        for rid, clk in by.items():
            nm = names.get(rid, "")
            if nm and clk > 0:
                agg[nm] = agg.get(nm, 0.0) + clk
    out = [{"city": c, "clicks": int(round(n))} for c, n in
           sorted(agg.items(), key=lambda x: -x[1])]
    return out


key = sys.argv[1] if len(sys.argv) > 1 else "dr-carlos"
start = sys.argv[2] if len(sys.argv) > 2 else "2026-06-05"
end = sys.argv[3] if len(sys.argv) > 3 else "2026-06-11"
outp = sys.argv[4] if len(sys.argv) > 4 else "/home/markevo42/public_html/_ipv7.json"

config = load_config()
clients = load_clients()
cli = next((c for c in clients.get("clientes", []) if c.get("key") == key), None)
if not cli:
    print("CLIENTE NAO ENCONTRADO:", key)
    sys.exit(1)
meta_ids = sorted(cli.get("_meta_ids", set()))
google_ids = sorted(cli.get("_google_ids", set()))

api = dict(config.get("api", {}))
mcfg = dict(api.get("meta", {}))
mcfg["ad_account_ids"] = ["act_" + m for m in meta_ids]
gcfg = dict(api.get("google_ads", {}))
gcfg["customer_ids"] = list(google_ids)

dias = (datetime.now().date() - datetime.strptime(start, "%Y-%m-%d").date()).days + 35
dias = max(dias, 70)

meta_df = meta_api.fetch(mcfg, dias) if meta_ids else pd.DataFrame(columns=META_COLUMNS)
google_df = google_api.fetch(gcfg, dias) if google_ids else pd.DataFrame(columns=GOOGLE_COLUMNS)

store = DataStore(config)
store.meta = _coerce(meta_df, META_COLUMNS, NUMERIC_META)
store.google = _coerce(google_df, GOOGLE_COLUMNS, NUMERIC_GOOGLE)
store.geo = pd.DataFrame(columns=GEO_COLUMNS)
store.updated_at = datetime.now()

scope = {"meta_ids": set(meta_ids), "google_ids": set(google_ids),
         "leads_form_only": bool(cli.get("leads_form_only", False))}
p = analytics.build_payload(store, account="todas", platform="todas",
                            days=31, scope=scope, start=start, end=end)
try:
    p["comentarios"] = commentary.generate(p)
except Exception as exc:  # noqa: BLE001
    print("commentary falhou:", exc)
    p["comentarios"] = {"destaques": []}

# Cliques por CIDADE (Google) no periodo EXATO (user_location_view).
cidades = _city_clicks(gcfg, google_ids, start, end)

out = {
    "cliente_nome": cli.get("nome"),
    "periodo": p.get("periodo"),
    "funil": p.get("funil"),
    "investimento": p.get("investimento"),
    "blocos_objetivo": p.get("blocos_objetivo"),
    "campanhas": p.get("campanhas"),
    "melhores_anuncios": p.get("melhores_anuncios"),
    "palavras_chave": p.get("palavras_chave"),
    "comentarios": p.get("comentarios"),
    "cidades_periodo": cidades,
    "meta_rows": len(store.meta), "google_rows": len(store.google),
}
json.dump(out, open(outp, "w", encoding="utf-8"), ensure_ascii=False, default=str)
print("OK ->", outp, "| meta", len(store.meta), "google", len(store.google),
      "| vazio?", p.get("vazio"), "| cidades", len(cidades))
