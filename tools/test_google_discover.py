"""Testa a descoberta automatica de contas sob o MCC (customer_client)."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
for line in open(os.path.join(BASE, ".env"), encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()

# Bundle de certificados local (antivirus/proxy intercepta HTTPS) — como no app.py
bundle = os.path.join(BASE, "win-ca-bundle.pem")
if os.path.exists(bundle):
    os.environ.setdefault("GRPC_DEFAULT_SSL_ROOTS_FILE_PATH", bundle)
    os.environ.setdefault("SSL_CERT_FILE", bundle)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle)

from data_sources import load_config  # noqa: E402
from connectors import google_api as G  # noqa: E402

g = dict(load_config()["api"]["google_ads"])
g["customer_ids"] = []  # forca descoberta via MCC
print("login_customer_id:", g.get("login_customer_id"))

client = G._client(g)
ids = G._customer_ids(g, client)
print("Total descoberto:", len(ids))
alvos = {"9152404582": "Dr Carlos", "8965771923": "Piping", "2121479176": "NEP"}
for cid, nome in alvos.items():
    print(f"  {nome} ({cid}):", "ENCONTRADO" if cid in ids else "NAO encontrado")
print("Amostra (10):", ids[:10])
