"""Fuso de Brasilia (America/Sao_Paulo) como UNICA fonte de verdade de "agora"/"hoje".

Antes cada ponto do sistema usava datetime.now()/today() = hora LOCAL DO SERVIDOR, e o
timestamp ia para o navegador sem fuso ("2026-07-20T08:09:22"), que o JS interpretava como
hora local de QUEM ACESSA. Resultado: horario errado se o servidor nao estiver em -03 ou se
o usuario acessar de outro fuso. Aqui tudo passa a ser explicitamente Brasilia.
"""
from datetime import datetime, timedelta, timezone

# Fallback de offset FIXO -03:00: o Brasil aboliu o horario de verao em 2019, entao
# America/Sao_Paulo e UTC-3 o ano todo. Usado quando o SO nao tem a base de fusos
# (ex.: Windows sem o pacote tzdata) — assim nunca degradamos para a hora do servidor.
_FIXED_BR = timezone(timedelta(hours=-3), "America/Sao_Paulo")
try:
    from zoneinfo import ZoneInfo
    BR_TZ = ZoneInfo("America/Sao_Paulo")
    datetime.now(BR_TZ)  # valida que ha tzdata de verdade
except Exception:  # noqa: BLE001
    BR_TZ = _FIXED_BR


def now_br() -> datetime:
    """Agora em Brasilia, CIENTE de fuso (isoformat sai com -03:00)."""
    return datetime.now(BR_TZ)


def today_br():
    """A data de hoje em Brasilia (date). Usado para as janelas de busca das APIs."""
    return now_br().date()


def to_br(ts):
    """Converte um datetime para Brasilia. Se vier NAIVE (pickles antigos, gravados com
    a hora local do servidor), o Python presume o fuso local do servidor e converte."""
    if ts is None:
        return ts
    return ts.astimezone(BR_TZ)
