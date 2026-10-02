"""Imprime a PRIMEIRA FRASE da 'Visao geral' de cada login, com o cache do servidor.

Serve para conferir como o paragrafo abre em cada conta — em especial as que so tem
Google, onde contar anuncios daria sempre zero e o texto passa a falar em campanhas.

Uso (no servidor, dentro de ~/dashboard-ads):
  OPENBLAS_NUM_THREADS=1 <python da venv> tools/visao_geral_diag.py [dias] [cliente]
Com o nome (ou pedaco do nome) de um cliente, imprime o PARAGRAFO INTEIRO so dele —
util para conferir as frases do fim, como a do Instagram.
Nao mostra senhas nem tokens."""
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

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # noqa: BLE001
    pass

import analytics  # noqa: E402
import commentary  # noqa: E402
import data_sources as d  # noqa: E402

dias = int(sys.argv[1]) if len(sys.argv) > 1 else 30
alvo = sys.argv[2].lower() if len(sys.argv) > 2 else ""
clientes = d.load_clients()
store = d.DataStore(d.load_config())
print("cache:", store.load_cache(max_age_h=9999), "| atualizado:", store.updated_at)

for c in clientes.get("clientes", []):
    if alvo and alvo not in c["key"].lower():
        continue
    sc = {"meta_ids": c.get("_meta_ids", set()), "google_ids": c.get("_google_ids", set()),
          "tiktok_ids": c.get("_tiktok_ids", set()), "linkedin_ids": c.get("_linkedin_ids", set()),
          "instagram_ids": c.get("_instagram_ids", set()),
          "leads_form_only": bool(c.get("leads_form_only", False)),
          "moeda": c.get("_moeda"), "funil_ordem": c.get("_funil_ordem"), "cliente_key": c["key"]}
    try:
        p = analytics.build_payload(store, days=dias, scope=sc)
        if p.get("vazio"):
            print(f"{c['key']:26} (sem dados no periodo)")
            continue
        texto = commentary.generate(p, c.get("idioma", "pt")).get("visao_geral") or ""
        # Sem filtro, uma linha por cliente (a abertura); com filtro, o paragrafo todo.
        frase = texto if alvo else texto.split(". ")[0]
        plats = sorted({b["plataforma"] for b in p.get("resumo_plataformas", [])})
        print(f"{c['key']:26} camp={len(p.get('campanhas') or []):3} "
              f"ads={len(p.get('anuncios') or []):3} {plats}\n    {frase}" + ("" if alvo else "."))
    except Exception as exc:  # noqa: BLE001
        print(f"{c['key']:26} ERRO {exc}")
