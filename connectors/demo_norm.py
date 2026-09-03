"""Normalizacao dos rotulos de PUBLICO (genero e faixa etaria) entre plataformas.

Meta: gender = male/female/unknown, age = "25-34" / "65+".
Google: MALE/FEMALE/UNDETERMINED, AGE_RANGE_25_34 / AGE_RANGE_65_UP / AGE_RANGE_UNDETERMINED.
TikTok: MALE/FEMALE/NONE, AGE_25_34 / AGE_55_100.
Tudo cai nas mesmas chaves para as tres plataformas somarem na mesma tabela.
"""
import re

_GENDER = {"male": "masculino", "m": "masculino", "female": "feminino", "f": "feminino"}


def norm_gender(v) -> str:
    return _GENDER.get(str(v or "").strip().lower(), "desconhecido")


def norm_age(v) -> str:
    """'25-34' | '65+' | 'AGE_RANGE_25_34' | 'AGE_RANGE_65_UP' | 'AGE_55_100' -> faixa."""
    s = str(v or "").lower()
    nums = [int(n) for n in re.findall(r"\d+", s)]
    if len(nums) >= 2:
        a, b = nums[0], nums[1]
        return f"{a}+" if b >= 100 else f"{a}-{b}"
    if len(nums) == 1:
        return f"{nums[0]}+"
    return "desconhecido"
