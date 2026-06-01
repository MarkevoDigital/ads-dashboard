"""
Gera o REFRESH TOKEN do Google Ads (fluxo OAuth de aplicativo Desktop).

Pre-requisitos:
  1) No Google Cloud Console, ative a "Google Ads API" no projeto.
  2) Crie uma credencial OAuth 2.0 do tipo "App para computador" (Desktop)
     e baixe o JSON (client_secret_XXXX.json).
  3) Instale a dependencia deste utilitario:
        pip install google-auth-oauthlib

Como rodar (no seu Windows, dentro de ads-dashboard):
  .\.venv\Scripts\python.exe tools\get_google_refresh_token.py CAMINHO\client_secret.json

  (sem argumento, ele pede o client_id e o client_secret na tela)

O script abre o navegador, voce faz login com a conta que tem acesso ao Google Ads,
autoriza, e ele imprime o REFRESH TOKEN para colar no .env (GOOGLE_REFRESH_TOKEN).
"""
import json
import sys

SCOPES = ["https://www.googleapis.com/auth/adwords"]


def main():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("Falta a dependencia. Rode:  pip install google-auth-oauthlib")
        sys.exit(1)

    if len(sys.argv) > 1:
        flow = InstalledAppFlow.from_client_secrets_file(sys.argv[1], scopes=SCOPES)
    else:
        client_id = input("client_id: ").strip()
        client_secret = input("client_secret: ").strip()
        config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost"],
            }
        }
        flow = InstalledAppFlow.from_client_config(config, scopes=SCOPES)

    # Abre o navegador e sobe um servidor local temporario para receber o codigo.
    creds = flow.run_local_server(port=0, prompt="consent")

    print("\n=================== COPIE PARA O .env ===================")
    print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
    print("=========================================================")
    print("\n(refresh_token completo salvo abaixo, caso o terminal corte)")
    with open("google_refresh_token.txt", "w", encoding="utf-8") as fh:
        fh.write(creds.refresh_token or "")
    print("Tambem gravei em: google_refresh_token.txt (apague depois de copiar).")


if __name__ == "__main__":
    main()
