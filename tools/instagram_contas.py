"""Lista as contas de Instagram que o token do Meta enxerga (via Paginas do Facebook).

Uso (no servidor, dentro de ~/dashboard-ads):
  OPENBLAS_NUM_THREADS=1 <python da venv> tools/instagram_contas.py [filtro]

Serve para mapear cada conta ao cliente (instagram_ids no clients.json e
INSTAGRAM_IDS no .env). Mostra id, @usuario, Pagina e seguidores; nunca o token.
O filtro opcional (trecho do @ ou da Pagina, sem diferenciar maiusculas) enxuga a lista.
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

import data_sources as d  # noqa: E402
from connectors import instagram_api  # noqa: E402

filtro = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
contas = instagram_api.accounts(d.load_config()["api"].get("meta", {}))
print(f"{len(contas)} conta(s) acessiveis")
for c in sorted(contas, key=lambda x: x["username"].lower()):
    if filtro and filtro not in c["username"].lower() and filtro not in c["page"].lower():
        continue
    print(f"{c['ig_id']}  @{c['username']:<28} {c['followers']:>8}  {c['page']}")
