"""Cadastra um cliente no clients.json com backup e validacao.

Evita o caminho que da errado: editar o JSON a mao no terminal (uma virgula fora do
lugar derruba o login de TODO MUNDO) e colar senha na linha de comando. Sem --senha,
a senha e sorteada aqui dentro e so aparece na saida, para ser entregue ao cliente.

Uso (no servidor, dentro de ~/dashboard-ads):
  python tools/add_client.py --key sanny --nome "Sanny" \
      --meta act_123 --google 895-768-6003 --instagram 17841456695698704

Depois: touch tmp/restart.txt e rodar o seed (as contas novas so entram na proxima
coleta). Varios ids por plataforma: repita a opcao ou separe por virgula.
"""
import argparse
import json
import os
import secrets
import shutil
import string
import sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMINHO = os.path.join(BASE, "clients.json")

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass


def _lista(valores):
    """--meta a,b --meta c  ->  [a, b, c]; descarta vazios."""
    out = []
    for v in valores or []:
        out += [x.strip() for x in str(v).split(",") if x.strip()]
    return out


def _so_digitos(s):
    return "".join(c for c in str(s) if c.isdigit())


def senha_sorteada(n=14):
    """Sem caracteres ambiguos (l/1/I, O/0) — a senha costuma ser digitada a mao."""
    alfabeto = (string.ascii_lowercase.replace("l", "").replace("o", "")
                + string.ascii_uppercase.replace("I", "").replace("O", "")
                + "23456789")
    return "".join(secrets.choice(alfabeto) for _ in range(n))


ap = argparse.ArgumentParser(description="Cadastra um cliente no clients.json")
ap.add_argument("--key", required=True, help="usuario do login (minusculas, sem espaco)")
ap.add_argument("--nome", required=True, help="nome exibido no dashboard")
ap.add_argument("--meta", action="append", help="conta(s) de Meta Ads (com ou sem 'act_')")
ap.add_argument("--google", action="append", help="conta(s) do Google Ads (com ou sem tracos)")
ap.add_argument("--instagram", action="append", help="id(s) de conta do Instagram")
ap.add_argument("--tiktok", action="append", help="advertiser id(s) do TikTok")
ap.add_argument("--linkedin", action="append", help="conta(s) do LinkedIn Ads")
ap.add_argument("--senha", help="senha fixa; sem isto, uma senha e sorteada")
ap.add_argument("--idioma", help="'en' para o cliente ver o dashboard em ingles")
a = ap.parse_args()

chave = a.key.strip().lower()
if not chave or " " in chave:
    sys.exit("ERRO: --key nao pode ter espaco.")

with open(CAMINHO, encoding="utf-8") as fh:
    dados = json.load(fh)

clientes = dados.setdefault("clientes", [])
if any(c.get("key", "").lower() == chave for c in clientes):
    sys.exit(f"ERRO: ja existe um cliente com key '{chave}'. Nada foi alterado.")

meta = [x if str(x).startswith("act_") else "act_" + _so_digitos(x) for x in _lista(a.meta)]
google = [_so_digitos(x) for x in _lista(a.google)]
insta = [_so_digitos(x) for x in _lista(a.instagram)]
tiktok = [_so_digitos(x) for x in _lista(a.tiktok)]
linkedin = [_so_digitos(x) for x in _lista(a.linkedin)]
if not (meta or google or tiktok or linkedin):
    sys.exit("ERRO: o cliente precisa de pelo menos uma conta de anuncios.")

# Mesma conta em dois clientes = um veria os dados do outro. Barra antes de gravar.
for c in clientes:
    for campo, novos in (("meta_ad_account_ids", meta), ("google_customer_ids", google),
                         ("tiktok_advertiser_ids", tiktok), ("linkedin_account_ids", linkedin)):
        ja = {_so_digitos(x) for x in c.get(campo, [])}
        bate = ja & {_so_digitos(x) for x in novos}
        if bate:
            sys.exit(f"ERRO: a conta {sorted(bate)} ja pertence ao cliente "
                     f"'{c.get('key')}' em {campo}. Nada foi alterado.")

senha = a.senha or senha_sorteada()
novo = {"key": chave, "nome": a.nome.strip(), "senha": senha}
if meta:
    novo["meta_ad_account_ids"] = meta
if google:
    novo["google_customer_ids"] = google
if insta:
    novo["instagram_ids"] = insta
if tiktok:
    novo["tiktok_advertiser_ids"] = tiktok
if linkedin:
    novo["linkedin_account_ids"] = linkedin
if a.idioma:
    novo["idioma"] = a.idioma
clientes.append(novo)

backup = CAMINHO + ".bak_" + chave
shutil.copy2(CAMINHO, backup)
tmp = CAMINHO + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    json.dump(dados, fh, ensure_ascii=False, indent=2)
    fh.write("\n")
os.replace(tmp, CAMINHO)

with open(CAMINHO, encoding="utf-8") as fh:  # le de volta: JSON quebrado derruba o login
    json.load(fh)

print(f"OK  cliente '{chave}' cadastrado ({len(clientes)} clientes no total)")
print(f"    backup   {backup}")
print(f"    meta     {meta or '-'}")
print(f"    google   {google or '-'}")
print(f"    insta    {insta or '-'}")
print(f"    LOGIN    {chave}")
print(f"    SENHA    {senha}")
print("    Agora: touch tmp/restart.txt e rode o seed para trazer os dados novos.")
