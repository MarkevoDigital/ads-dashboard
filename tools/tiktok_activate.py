# -*- coding: utf-8 -*-
"""Ativa o TikTok: troca auth_code por access_token e grava TIKTOK_* no .env.
NAO imprime secret/token (so o tamanho), so os advertiser_ids (p/ o clients.json).

Uso (secret vem do ambiente TK_SECRET, nunca em argv/history):
    TK_SECRET=... python tools/tiktok_activate.py <app_id> <auth_code>
"""
import os
import sys

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV = os.path.join(BASE_DIR, ".env")

app_id = sys.argv[1]
auth_code = sys.argv[2]
secret = os.environ.get("TK_SECRET", "").strip()
if not secret:
    print("ERRO: TK_SECRET vazio")
    sys.exit(1)

r = requests.post("https://business-api.tiktok.com/open_api/v1.3/oauth2/access_token/",
                  json={"app_id": app_id, "secret": secret, "auth_code": auth_code}, timeout=60)
try:
    body = r.json()
except ValueError:
    print("ERRO HTTP", r.status_code, r.text[:200])
    sys.exit(1)
if body.get("code") != 0:
    print("ERRO code", body.get("code"), "|", str(body.get("message"))[:200])
    sys.exit(1)

data = body.get("data", {}) or {}
token = data.get("access_token", "") or ""
advs = [str(x) for x in (data.get("advertiser_ids") or [])]
scope = data.get("scope")
if not token:
    print("ERRO: sem access_token na resposta")
    sys.exit(1)

# Atualiza .env: remove TIKTOK_* antigas e acrescenta as novas.
old = []
if os.path.exists(ENV):
    old = [l for l in open(ENV, encoding="utf-8").read().splitlines()
           if not l.strip().startswith(("TIKTOK_ACCESS_TOKEN=", "TIKTOK_APP_ID=", "TIKTOK_SECRET="))]
new = old + ["TIKTOK_APP_ID=" + app_id, "TIKTOK_SECRET=" + secret, "TIKTOK_ACCESS_TOKEN=" + token]
tmp = ENV + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    fh.write("\n".join(new) + "\n")
os.replace(tmp, ENV)

print("OK | .env atualizado | token_len", len(token),
      "| advertisers", ",".join(advs) or "(vazio)", "| scope", scope)
