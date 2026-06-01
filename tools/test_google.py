"""Teste rapido da conexao Google Ads: carrega .env e busca 1 conta ativa."""
import os
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

# Carrega .env -> os.environ
envp = os.path.join(BASE, ".env")
for line in open(envp, encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()

from data_sources import load_config  # noqa: E402
from connectors import google_api  # noqa: E402

cfg = load_config()
g = dict(cfg["api"]["google_ads"])
g["customer_ids"] = ["4844302999"]  # DR LUCIANA (conta ativa)

print("Tem developer_token:", bool(g.get("developer_token")))
print("Tem refresh_token:", bool(g.get("refresh_token")))
print("login_customer_id:", g.get("login_customer_id"))
print("Buscando 30 dias da conta 4844302999...\n")

df = google_api.fetch(g, days=30)
print("Linhas retornadas:", len(df))
if not df.empty:
    print("Colunas:", list(df.columns))
    print("Investimento total (R$): %.2f" % df["cost"].sum())
    print("Cliques: %d | Conversoes: %.1f" % (df["clicks"].sum(), df["conversions"].sum()))
    kw = df[df["keyword"] != ""]
    print("Linhas com palavra-chave:", len(kw))
    if not kw.empty:
        top = kw.groupby("keyword")["clicks"].sum().sort_values(ascending=False).head(5)
        print("\nTop 5 palavras-chave por cliques:")
        for k, v in top.items():
            print(f"  {k}: {int(v)} cliques")
