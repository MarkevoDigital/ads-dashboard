"""Acrescenta contas (ou renomeia) um cliente que JA existe no clients.json.

Mesmas protecoes do add_client.py: backup, gravacao atomica, releitura para garantir
que o JSON continua valido e recusa de conta que ja pertence a outro cliente — este
ultimo caso faria um cliente ver os dados do outro.

Uso (no servidor, dentro de ~/dashboard-ads):
  python tools/set_client.py --key ybya-studio --add-instagram 17841433610162098
  python tools/set_client.py --key jotaz --add-google 874-844-2401

As contas sao ACRESCENTADAS as que ja existem (sem repetir). Para trocar o conjunto
inteiro de uma plataforma, use --trocar junto com a opcao daquela plataforma.
Depois: touch tmp/restart.txt e rodar o seed se a conta nova ainda nao foi coletada.
"""
import argparse
import json
import os
import shutil
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMINHO = os.path.join(BASE, "clients.json")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def _lista(valores):
    out = []
    for v in valores or []:
        out += [x.strip() for x in str(v).split(",") if x.strip()]
    return out


def _so_digitos(s):
    return "".join(c for c in str(s) if c.isdigit())


ap = argparse.ArgumentParser(description="Acrescenta contas a um cliente existente")
ap.add_argument("--key", required=True)
ap.add_argument("--add-meta", action="append")
ap.add_argument("--add-google", action="append")
ap.add_argument("--add-instagram", action="append")
ap.add_argument("--add-tiktok", action="append")
ap.add_argument("--add-linkedin", action="append")
ap.add_argument("--nome", help="renomeia o cliente")
ap.add_argument("--trocar", action="store_true",
                help="substitui o conjunto da plataforma em vez de acrescentar")
a = ap.parse_args()

chave = a.key.strip().lower()
with open(CAMINHO, encoding="utf-8") as fh:
    dados = json.load(fh)

clientes = dados.get("clientes", [])
alvo = next((c for c in clientes if c.get("key", "").lower() == chave), None)
if alvo is None:
    sys.exit(f"ERRO: nao existe cliente com key '{chave}'. Nada foi alterado.")

campos = [
    ("meta_ad_account_ids", _lista(a.add_meta),
     lambda x: x if str(x).startswith("act_") else "act_" + _so_digitos(x)),
    ("google_customer_ids", _lista(a.add_google), _so_digitos),
    ("instagram_ids", _lista(a.add_instagram), _so_digitos),
    ("tiktok_advertiser_ids", _lista(a.add_tiktok), _so_digitos),
    ("linkedin_account_ids", _lista(a.add_linkedin), _so_digitos),
]
if not any(novos for _, novos, _ in campos) and not a.nome:
    sys.exit("ERRO: nada a fazer. Informe ao menos uma conta ou --nome.")

for campo, novos, normaliza in campos:
    if not novos:
        continue
    novos = [normaliza(x) for x in novos]
    for c in clientes:
        if c is alvo:
            continue
        ja = {_so_digitos(x) for x in c.get(campo, [])}
        bate = ja & {_so_digitos(x) for x in novos}
        if bate:
            sys.exit(f"ERRO: a conta {sorted(bate)} ja pertence ao cliente "
                     f"'{c.get('key')}' em {campo}. Nada foi alterado.")
    atual = [] if a.trocar else list(alvo.get(campo, []))
    for x in novos:
        if x not in atual:
            atual.append(x)
    alvo[campo] = atual

if a.nome:
    alvo["nome"] = a.nome.strip()

backup = CAMINHO + ".bak_set_" + chave
shutil.copy2(CAMINHO, backup)
tmp = CAMINHO + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(dados, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
os.replace(tmp, CAMINHO)
with open(CAMINHO, encoding="utf-8") as fh:
    json.load(fh)

print(f"OK  cliente '{chave}' atualizado")
print(f"    backup   {backup}")
for campo, _, _ in campos:
    if alvo.get(campo):
        print(f"    {campo:22} {alvo[campo]}")
print("    Agora: touch tmp/restart.txt (e o seed, se a conta e nova na coleta).")
