"""Verifica, como um cliente real (basic-auth), quais contas ele enxerga no dashboard.

Uso:  python3 tools/verify_client.py dr-carlos
Le a senha do clients.json local (servidor) e chama /api/data autenticado.
"""
import base64
import json
import os
import sys
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = sys.argv[1] if len(sys.argv) > 1 else "dr-carlos"
URL = os.environ.get("DASH_URL", "https://dashboard.markevo.com.br")

clientes = json.load(open(os.path.join(BASE, "clients.json")))["clientes"]
c = next(x for x in clientes if x["key"] == KEY)
tok = base64.b64encode(f"{KEY}:{c['senha']}".encode()).decode()

req = urllib.request.Request(f"{URL}/api/data?days=30",
                             headers={"Authorization": f"Basic {tok}"})
d = json.load(urllib.request.urlopen(req, timeout=60))

print("cliente:", c.get("nome"), f"({KEY})")
print("vazio:", d.get("vazio"), "| carregando:", d.get("carregando"))
print("contas visiveis:", d.get("contas"))
camps = d.get("campanhas", [])
plats = sorted({r.get("plataforma") for r in camps})
print("plataformas com campanhas:", plats)
print("nº campanhas:", len(camps), "| nº palavras-chave:", len(d.get("palavras_chave", [])))
