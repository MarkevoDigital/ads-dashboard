#!/usr/bin/env python
"""Diagnostico da integracao com o LinkedIn Ads, para rodar no servidor.

Uso (dentro de ~/dashboard-ads):
  OPENBLAS_NUM_THREADS=1 <python da venv> tools/linkedin_teste.py [conta_id]

Mostra: status da autorizacao (dias restantes, sem exibir token), contas, numero de
campanhas e criativos, amostra de 7 dias do relatorio, Paginas administradas e seus
seguidores. Nao grava nada.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for linha in open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
                  encoding="utf-8"):
    k, _, v = linha.strip().partition("=")
    if k and not k.startswith("#"):
        os.environ.setdefault(k, v.strip().strip('"').strip("'"))

from connectors import linkedin_api as li  # noqa: E402
from connectors import linkedin_auth  # noqa: E402


def passo(titulo, fn):
    try:
        r = fn()
        print(f"OK    {titulo}: {r}")
        return r
    except Exception as exc:  # noqa: BLE001
        print(f"FALHA {titulo}: {str(exc)[:300]}")
        return None


print("autorizacao:", linkedin_auth.status())
token = linkedin_auth.access_token()
if not token:
    print("Sem token valido. Abra https://dashboard.markevo.com.br/linkedin/conectar com o login admin.")
    raise SystemExit(1)

contas = sys.argv[1:] or [c for c in os.environ.get("LINKEDIN_ACCOUNT_IDS", "").split(",") if c.strip()]
print("contas:", contas or "(nenhuma em LINKEDIN_ACCOUNT_IDS)")
for c in contas:
    c = li._digitos(c)
    passo(f"conta {c}", lambda: li._info_conta(c, token))
    camps = passo(f"campanhas {c}", lambda: {k: (v['nome'], v['objetivo']) for k, v in li._campanhas(c, token).items()})
    cria = passo(f"criativos {c}", lambda: len(li._criativos(c, token)))
    df = passo(f"relatorio 7 dias {c}", lambda: (lambda d: f"{len(d)} linhas | invest {d['spend'].sum():.2f} | "
                                                         f"impr {int(d['impressions'].sum())} | cliques {int(d['clicks'].sum())}"
                                                         if len(d) else "0 linhas")(li.fetch({"account_ids": [c]}, 7)))

paginas = passo("paginas administradas", lambda: li.paginas_administradas(token))
for p in paginas or []:
    passo(f"seguidores {p['nome']} ({p['id']})", lambda: li.seguidores(p["id"], token))
