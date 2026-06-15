"""Troca o auth_code do TikTok (apos o advertiser autorizar o app) por um
access_token + a lista de advertiser_ids autorizados.

Fluxo:
  1) Gere a URL de autorizacao e abra no navegador (logado no TikTok For Business):
       python tools/get_tiktok_token.py <app_id> <secret> --auth-url https://dashboard.markevo.com.br/tiktok/callback
     Autorize a(s) conta(s) do cliente; o navegador redireciona para a redirect_uri
     com ...?auth_code=XXXX&code=... (copie o valor de auth_code).
  2) Troque o auth_code por um token:
       python tools/get_tiktok_token.py <app_id> <secret> <auth_code>

Imprime o ACCESS_TOKEN e os ADVERTISER_IDS para colar no .env / clients.json do servidor.
NUNCA versione o token; coloque-o so via variavel de ambiente no servidor.
"""
import json
import sys
from urllib.parse import urlencode

import requests

BASE = "https://business-api.tiktok.com/open_api/v1.3"


def auth_url(app_id, redirect_uri, state="markevo"):
    return "https://business-api.tiktok.com/portal/auth?" + urlencode(
        {"app_id": app_id, "state": state, "redirect_uri": redirect_uri})


def exchange(app_id, secret, auth_code):
    r = requests.post(BASE + "/oauth2/access_token/",
                      json={"app_id": app_id, "secret": secret, "auth_code": auth_code},
                      timeout=60)
    return r.status_code, r.json()


def main():
    args = sys.argv[1:]
    if len(args) >= 4 and args[2] == "--auth-url":
        print(auth_url(args[0], args[3]))
        return
    if len(args) < 3:
        print(__doc__)
        sys.exit(1)
    app_id, secret, auth_code = args[0], args[1], args[2]
    code, body = exchange(app_id, secret, auth_code)
    if body.get("code") != 0:
        print("ERRO:", code, json.dumps(body, ensure_ascii=False))
        sys.exit(1)
    data = body.get("data", {})
    advs = [str(x) for x in (data.get("advertiser_ids") or [])]
    print("ACCESS_TOKEN:", data.get("access_token"))
    print("ADVERTISER_IDS:", ",".join(advs))
    print("SCOPE:", data.get("scope"))
    print("\n--- .env do servidor ---")
    print("TIKTOK_ACCESS_TOKEN=" + str(data.get("access_token")))
    print("TIKTOK_APP_ID=" + app_id)
    print("TIKTOK_SECRET=<o secret do app>")
    print('--- clients.json (no cliente, ex.: Bem me Fiz) ---')
    print('  "tiktok_advertiser_ids": ' + json.dumps(advs))


if __name__ == "__main__":
    main()
