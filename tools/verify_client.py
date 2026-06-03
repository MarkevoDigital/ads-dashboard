"""Verifica, como um usuario real (basic-auth), o que ele enxerga no dashboard.

Uso:
  python3 tools/verify_client.py dr-carlos        # ve como o cliente dr-carlos
  python3 tools/verify_client.py admin            # ve como admin (todas as contas)
  python3 tools/verify_client.py admin piping     # admin usando "Ver como" piping

Le as senhas do clients.json (servidor) e chama /api/data autenticado.
"""
import base64
import json
import os
import sys
import urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = sys.argv[1] if len(sys.argv) > 1 else "dr-carlos"
VIEW_AS = sys.argv[2] if len(sys.argv) > 2 else ""
URL = os.environ.get("DASH_URL", "https://dashboard.markevo.com.br")

data = json.load(open(os.path.join(BASE, "clients.json")))
if KEY == "admin":
    senha = (data.get("admin", {}) or {}).get("senha") or os.environ.get("DASH_PASSWORD", "")
    nome = "Agência (admin)"
else:
    c = next(x for x in data["clientes"] if x["key"] == KEY)
    senha, nome = c["senha"], c.get("nome")

tok = base64.b64encode(f"{KEY}:{senha}".encode()).decode()
qs = "days=30" + (f"&client={VIEW_AS}" if VIEW_AS else "")
req = urllib.request.Request(f"{URL}/api/data?{qs}",
                             headers={"Authorization": f"Basic {tok}"})
d = json.load(urllib.request.urlopen(req, timeout=60))

print("login:", nome, f"({KEY})", f"| ver como: {VIEW_AS}" if VIEW_AS else "")
print("cliente_sel:", d.get("cliente_sel"))
ca = d.get("clientes_admin")
print("clientes_admin:", [x["key"] for x in ca] if ca else None)
print("vazio:", d.get("vazio"), "| carregando:", d.get("carregando"))
print("contas visiveis:", d.get("contas"))
camps = d.get("campanhas", [])
print("plataformas com campanhas:", sorted({r.get("plataforma") for r in camps}))
print("nº campanhas:", len(camps), "| nº palavras-chave:", len(d.get("palavras_chave", [])))
ba = d.get("melhores_anuncios", [])
if ba:
    a = ba[0]
    print("best_ad[0]: destaque", a.get("result_label"), "=", a.get("result_value"),
          "| sec", a.get("eff_label"), "=", a.get("eff_value"))
