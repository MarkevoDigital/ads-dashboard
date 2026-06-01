"""
Monta o arquivo .env lendo os segredos diretamente dos arquivos locais
(JSON do cliente OAuth + google_refresh_token.txt), sem expô-los no terminal.

Uso:
  python tools/build_env.py "CAMINHO\\client_secret_xxx.json"

Preserva placeholders para o developer token e para o Meta (preenchidos depois).
Nao sobrescreve um .env existente: grava em .env (cria) ou avisa.
"""
import json
import os
import secrets
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- Valores ja conhecidos (nao secretos) ---
LOGIN_CUSTOMER_ID = "8231413591"
CUSTOMER_IDS = ",".join([
    "2733779024", "1968689935", "2872669837", "5860573615", "7352629878",
    "9829933950", "4844302999", "7351551713", "4599767501", "7819317770",
    "1540486778", "9370550280", "7011987345", "9917064692", "8523428407",
    "8302034244", "7225600099", "4709621582", "8303486817", "1126682944",
    "9651812631", "6121813305", "5568504721", "1330907737", "3160891105",
])


def main():
    if len(sys.argv) < 2:
        print("Falta o caminho do client_secret JSON.")
        sys.exit(1)

    with open(sys.argv[1], "r", encoding="utf-8") as fh:
        cfg = json.load(fh)
    inst = cfg.get("installed") or cfg.get("web") or {}
    client_id = inst["client_id"]
    client_secret = inst["client_secret"]

    rt_path = os.path.join(BASE, "google_refresh_token.txt")
    with open(rt_path, "r", encoding="utf-8") as fh:
        refresh_token = fh.read().strip()

    cron_token = secrets.token_urlsafe(24)

    env_path = os.path.join(BASE, ".env")
    if os.path.exists(env_path):
        print(".env ja existe — nao sobrescrevi. Renomeie/remova antes.")
        sys.exit(1)

    lines = [
        "# Gerado por tools/build_env.py. NUNCA versionar este arquivo.",
        "FONTE_DADOS=api",
        "DIAS_BUSCA=60",
        "",
        "# --- Meta Ads (preencher apos gerar o token do usuario de sistema) ---",
        "META_ACCESS_TOKEN=",
        "META_AD_ACCOUNT_IDS=",
        "META_API_VERSION=v21.0",
        "",
        "# --- Google Ads ---",
        "# Cole o developer token do API Center (MCC) abaixo:",
        "GOOGLE_DEVELOPER_TOKEN=",
        f"GOOGLE_CLIENT_ID={client_id}",
        f"GOOGLE_CLIENT_SECRET={client_secret}",
        f"GOOGLE_REFRESH_TOKEN={refresh_token}",
        f"GOOGLE_LOGIN_CUSTOMER_ID={LOGIN_CUSTOMER_ID}",
        f"GOOGLE_CUSTOMER_IDS={CUSTOMER_IDS}",
        "",
        "# --- Acesso do cliente (defina uma senha) ---",
        "DASH_USER=cliente",
        "DASH_PASSWORD=",
        "",
        "# --- Token do cron diario (gerado automaticamente) ---",
        f"CRON_TOKEN={cron_token}",
        "",
    ]
    with open(env_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))

    print("OK: .env criado.")
    print(f"  GOOGLE_CLIENT_ID  = {client_id}")
    print(f"  client_secret     = ({len(client_secret)} chars, oculto)")
    print(f"  refresh_token     = ({len(refresh_token)} chars, oculto)")
    print(f"  customer_ids      = 25 contas")
    print("  FALTA: GOOGLE_DEVELOPER_TOKEN, META_*, DASH_PASSWORD")


if __name__ == "__main__":
    main()
