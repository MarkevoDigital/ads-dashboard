"""Diagnostico do funil e dos blocos de objetivo de UM cliente, com os dados do cache.

Uso (no servidor, dentro de ~/dashboard-ads):
  OPENBLAS_NUM_THREADS=1 <python da venv> tools/funil_diag.py <cliente> [dias]

Mostra, sem senhas nem tokens: a ordem de funil configurada (env e cliente), as
somas por campanha/objetivo na janela (carrinho, checkout, compra, leads...) e o
funil e os blocos que o dashboard monta para o cliente.
"""
import os
import sys

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)
for raw in open(os.path.join(BASE, ".env"), encoding="utf-8"):
    raw = raw.strip()
    if raw and not raw.startswith("#") and "=" in raw:
        k, v = raw.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import pandas as pd  # noqa: E402
import analytics  # noqa: E402
import data_sources as d  # noqa: E402

chave = sys.argv[1] if len(sys.argv) > 1 else ""
dias = int(sys.argv[2]) if len(sys.argv) > 2 else 7
clientes = {c["key"]: c for c in d.load_clients().get("clientes", [])}
if chave not in clientes:
    print("clientes:", sorted(clientes))
    raise SystemExit(2)
c = clientes[chave]
print("FUNIL_ORDEM env:", os.environ.get("FUNIL_ORDEM"), "| funil_ordem cliente:", c.get("_funil_ordem"))

store = d.DataStore(d.load_config())
print("cache:", store.load_cache(max_age_h=9999), "| atualizado:", store.updated_at)
cols = ["spend", "clicks", "link_clicks", "add_to_cart", "initiate_checkout", "purchases",
        "leads", "registrations", "site_visits", "engagement", "profile_visits", "video_views"]
for nome, df, ids in (("meta", store.meta, c.get("_meta_ids", set())),
                      ("tiktok", store.tiktok, c.get("_tiktok_ids", set())),
                      ("linkedin", store.linkedin, c.get("_linkedin_ids", set()))):
    m = df[df["account_id"].astype(str).map(d.only_digits).isin(ids)].copy()
    if m.empty:
        continue
    m["date"] = pd.to_datetime(m["date"])
    fim = pd.Timestamp(d.today_br()) - pd.Timedelta(days=1)
    w = m[(m["date"] > fim - pd.Timedelta(days=dias)) & (m["date"] <= fim)]
    pres = [x for x in cols if x in w.columns]
    print(f"\n[{nome}] {len(w)} linhas em {dias}d ate {fim.date()}")
    if len(w):
        print(w.groupby(["campaign", "objective"])[pres].sum().round(1).to_string())
        print("TOTAL", {k: v for k, v in w[pres].sum().round(1).to_dict().items() if v})

scope = {"meta_ids": c.get("_meta_ids", set()), "google_ids": c.get("_google_ids", set()),
         "tiktok_ids": c.get("_tiktok_ids", set()), "linkedin_ids": c.get("_linkedin_ids", set()),
         "instagram_ids": c.get("_instagram_ids", set()), "moeda": c.get("_moeda"),
         "funil_ordem": c.get("_funil_ordem"), "cliente_key": chave}
p = analytics.build_payload(store, days=dias, scope=scope)
print("\nFUNIL:", [(s["label"], s["value"]) for s in p["funil"]["stages"]])
print("TAXAS:", [(r["label"], r["value"]) for r in p["funil"]["rates"]])
for b in p.get("blocos_objetivo", []):
    print("BLOCO", b["objective"], "|", [(k["key"], k["value"]) for k in b["cards"]])
