"""Monta o payload do dashboard para TODOS os logins (clientes e agencias de grupo)
com o cache do servidor e confere o isolamento: nenhuma conta fora do escopo do
login pode aparecer. Rodar depois de todo deploy.

Uso (no servidor, dentro de ~/dashboard-ads):
  OPENBLAS_NUM_THREADS=1 <python da venv> tools/validar_payloads.py [dias]

Nao mostra senhas nem tokens: uma linha por login e um resumo final.
"""
import os
import sys
import traceback

os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
os.chdir(BASE)
for raw in open(os.path.join(BASE, ".env"), encoding="utf-8"):
    raw = raw.strip()
    if raw and not raw.startswith("#") and "=" in raw:
        k, v = raw.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())

import analytics  # noqa: E402
import data_sources as d  # noqa: E402

CAMPOS = ("meta_ids", "google_ids", "tiktok_ids", "linkedin_ids", "instagram_ids")
dias = int(sys.argv[1]) if len(sys.argv) > 1 else 30
clientes = d.load_clients()
store = d.DataStore(d.load_config())
print("cache:", store.load_cache(max_age_h=9999), "| atualizado:", store.updated_at)


def escopo_cliente(c):
    # Mesmo formato do app.py::_build_users
    return {"meta_ids": c.get("_meta_ids", set()), "google_ids": c.get("_google_ids", set()),
            "tiktok_ids": c.get("_tiktok_ids", set()), "linkedin_ids": c.get("_linkedin_ids", set()),
            "instagram_ids": c.get("_instagram_ids", set()),
            "leads_form_only": bool(c.get("leads_form_only", False)),
            "moeda": c.get("_moeda"), "funil_ordem": c.get("_funil_ordem"), "cliente_key": c["key"]}


logins = [(c["key"], escopo_cliente(c)) for c in clientes.get("clientes", [])]
por_chave = dict(logins)
for a in clientes.get("agencias", []):
    subs = [k for k in a.get("clientes", []) if k in por_chave]
    uniao = {campo: set() for campo in CAMPOS}
    uniao.update({"leads_form_only": False, "moeda": a.get("_moeda"), "cliente_keys": subs})
    for k in subs:
        for campo in CAMPOS:
            uniao[campo] |= set(por_chave[k].get(campo) or ())
    logins.append((f"{a['key']} (agencia)", uniao))


def contas_permitidas(sc):
    ok = set()
    for df, campo in ((store.meta, "meta_ids"), (store.google, "google_ids"),
                      (store.tiktok, "tiktok_ids"), (store.linkedin, "linkedin_ids")):
        if df is None or df.empty:
            continue
        ids = sc.get(campo) or set()
        ok |= set(df[df["account_id"].astype(str).map(d.only_digits).isin(ids)]["account"])
    return ok


erros = vazamentos = 0
for chave, sc in logins:
    try:
        p = analytics.build_payload(store, days=dias, scope=sc)
        fora = set(p.get("contas", [])) - contas_permitidas(sc)
        if fora:
            vazamentos += 1
        funil = [s["label"] for s in (p.get("funil") or {}).get("stages", [])][:3]
        print(f"{'VAZAMENTO' if fora else 'OK':9} {chave:28} contas={len(p.get('contas', []))} "
              f"resumo={[b['plataforma'] for b in p.get('resumo_plataformas', [])]} "
              f"ig={bool(p.get('tem_instagram'))} li_seg={(p.get('seguidores_manuais') or {}).get('tem')} "
              f"funil={funil}" + (f" FORA={sorted(fora)}" if fora else ""))
    except Exception as exc:  # noqa: BLE001
        erros += 1
        print(f"ERRO      {chave:28} {exc}")
        traceback.print_exc(limit=2)
print(f"RESUMO logins={len(logins)} erros={erros} vazamentos={vazamentos}")
