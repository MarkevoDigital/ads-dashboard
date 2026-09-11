#!/usr/bin/env python
"""Registra o total de seguidores de uma rede SEM API de leitura (hoje, o LinkedIn).

Por que existe: o numero de seguidores de uma Pagina do LinkedIn so sai pelo
Community Management API, que exige um app exclusivo e aprovacao de parceiro, e o
termo de uso do LinkedIn proibe ler a pagina por robo. Entao o numero entra a mao,
uma linha por medicao, e o dashboard calcula o crescimento sozinho.

Uso:
  python tools/seguidores.py <cliente> <numero> [--data AAAA-MM-DD]
                             [--rede LinkedIn] [--url https://...]
  python tools/seguidores.py --listar [cliente]

Exemplos:
  python tools/seguidores.py carreirha 1420
  python tools/seguidores.py carreirha 1435 --data 2026-09-15
  python tools/seguidores.py --listar carreirha

O arquivo (seguidores_manuais.json, ao lado do app) e lido a cada requisicao:
o numero novo aparece no dashboard na hora, sem restart.
"""
import json
import os
import sys
from datetime import date

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARQUIVO = os.path.join(BASE_DIR, "seguidores_manuais.json")


def carregar() -> dict:
    try:
        with open(ARQUIVO, encoding="utf-8") as fh:
            return json.load(fh) or {}
    except FileNotFoundError:
        return {}


def salvar(dados: dict) -> None:
    """Escreve em .tmp e troca — nunca deixa o arquivo pela metade se cair no meio."""
    tmp = ARQUIVO + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dados, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, ARQUIVO)


def mostrar(cliente: str, reg: dict) -> None:
    hist = sorted(reg.get("historico") or [], key=lambda h: str(h.get("data", "")))
    rede = reg.get("rede") or "LinkedIn"
    print(f"\n{cliente} — {rede}  ({len(hist)} medicao(oes))")
    if reg.get("url"):
        print(f"  {reg['url']}")
    anterior = None
    for h in hist[-8:]:
        n = int(h["seguidores"])
        if anterior is None:
            print(f"  {h['data']}  {n:>8,}".replace(",", "."))
        else:
            d = n - anterior
            pct = (d / anterior * 100.0) if anterior else 0.0
            sinal = "+" if d >= 0 else ""
            print(f"  {h['data']}  {n:>8,}   {sinal}{d}  ({sinal}{pct:.2f}%)".replace(",", "."))
        anterior = n


def main(argv) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0

    dados = carregar()

    if argv[0] == "--listar":
        alvo = argv[1] if len(argv) > 1 else None
        if not dados:
            print(f"Nenhum registro ainda ({ARQUIVO} nao existe).")
            return 0
        for cliente, reg in sorted(dados.items()):
            if alvo and cliente != alvo:
                continue
            mostrar(cliente, reg)
        return 0

    if len(argv) < 2:
        print(__doc__)
        return 2

    cliente, bruto = argv[0], argv[1]
    try:
        numero = int(str(bruto).replace(".", "").replace(",", "").strip())
    except ValueError:
        print(f"Numero invalido: {bruto!r}")
        return 2
    if numero < 0:
        print("Numero de seguidores nao pode ser negativo.")
        return 2

    quando = str(date.today())
    rede, url = None, None
    i = 2
    while i < len(argv):
        if argv[i] == "--data" and i + 1 < len(argv):
            quando = argv[i + 1]; i += 2
        elif argv[i] == "--rede" and i + 1 < len(argv):
            rede = argv[i + 1]; i += 2
        elif argv[i] == "--url" and i + 1 < len(argv):
            url = argv[i + 1]; i += 2
        else:
            print(f"Argumento desconhecido: {argv[i]}")
            return 2

    reg = dados.setdefault(cliente, {})
    if rede:
        reg["rede"] = rede
    if url:
        reg["url"] = url
    reg.setdefault("rede", "LinkedIn")
    hist = [h for h in (reg.get("historico") or []) if str(h.get("data")) != quando]
    substituiu = len(hist) != len(reg.get("historico") or [])
    hist.append({"data": quando, "seguidores": numero})
    reg["historico"] = sorted(hist, key=lambda h: str(h["data"]))

    salvar(dados)
    print(f"{'Substituida' if substituiu else 'Registrada'} a medicao de {quando}: "
          f"{numero} seguidores para '{cliente}'.")
    mostrar(cliente, reg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
