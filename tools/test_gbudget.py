import os
B = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
for l in open(os.path.join(B, ".env"), encoding="utf-8"):
    l = l.strip()
    if l and not l.startswith("#") and "=" in l:
        k, v = l.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())
bd = os.path.join(B, "win-ca-bundle.pem")
for k in ("GRPC_DEFAULT_SSL_ROOTS_FILE_PATH", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE"):
    os.environ.setdefault(k, bd)
import sys
sys.path.insert(0, B)
from data_sources import load_config
from connectors import google_api as G
g = dict(load_config()["api"]["google_ads"]); g["customer_ids"] = ["9152404582"]
df = G.fetch(g, 30)
print("linhas:", len(df))
if len(df):
    print("tem daily_budget:", "daily_budget" in df.columns)
    print("campanhas:", df["campaign"].nunique())
    print("orcamentos (amostra):", sorted(set(round(x, 2) for x in df["daily_budget"] if x > 0))[:8])
    print("linhas com orcamento>0:", int((df["daily_budget"] > 0).sum()))
