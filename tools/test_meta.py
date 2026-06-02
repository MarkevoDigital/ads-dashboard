"""Teste rapido do Meta: descobre contas + busca insights de 1 conta."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
for line in open(os.path.join(BASE, ".env"), encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()

from data_sources import load_config  # noqa
from connectors import meta_api as M  # noqa

m = load_config()["api"]["meta"]
ver = m.get("api_version", "v21.0")
print("api_version:", ver)
ids = M._account_ids(m, m["access_token"], ver)
print("contas descobertas:", len(ids), "| amostra:", ids[:3])
if ids:
    m2 = dict(m)
    m2["ad_account_ids"] = ids[:1]
    df = M.fetch(m2, 7)
    print("insights 1 conta/7 dias -> linhas:", len(df))
    if len(df):
        print("spend:", round(float(df["spend"].sum()), 2),
              "| impressoes:", int(df["impressions"].sum()),
              "| objetivos:", list(df["objective"].unique())[:5])
