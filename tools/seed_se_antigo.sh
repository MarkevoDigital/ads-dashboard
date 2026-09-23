#!/bin/sh
# Roda o seed SO se o cache estiver velho. Existe porque uma atualizacao agendada
# pode falhar por causa do ambiente (ex.: o DNS da hospedagem parou de resolver
# googleads.googleapis.com em 23/09/2026) — quando isso acontece, o refresh aborta
# de proposito para nao zerar os dados e o cache fica parado ate a proxima janela.
#
# Com este script no cron de hora em hora, o dashboard se recupera sozinho assim que
# o ambiente volta, sem rodar seed a toa: se o cache esta fresco, sai na hora.
#
# Uso no cron (a cada hora, no minuto 31):
#   31 * * * * /home/<conta>/dashboard-ads/tools/seed_se_antigo.sh >> /home/<conta>/dashboard-ads/tmp/cron.log 2>&1
# Ajuste opcional: SEED_MAX_HORAS (padrao 5h, ou seja, mais que o intervalo normal).
BASE="$(cd "$(dirname "$0")/.." && pwd)"
MAXH="${SEED_MAX_HORAS:-5}"
CACHE="$BASE/tmp/store_cache.pkl"
PY="$(ls -d "$HOME"/virtualenv/dashboard-ads/*/bin/python 2>/dev/null | tail -1)"
[ -x "$PY" ] || PY=python3

if [ -f "$CACHE" ]; then
    IDADE=$(( ( $(date +%s) - $(stat -c %Y "$CACHE") ) / 3600 ))
    if [ "$IDADE" -lt "$MAXH" ]; then
        exit 0
    fi
else
    IDADE="sem cache"
fi

echo "[seed-retry] $(date '+%Y-%m-%d %H:%M') cache com ${IDADE}h (limite ${MAXH}h) -> rodando seed"
OPENBLAS_NUM_THREADS=1 nice -n 15 "$PY" "$BASE/tools/seed_cache.py"
# O seed so grava o cache quando o refresh completa; se o ambiente ainda estiver
# quebrado, o arquivo continua velho e a proxima hora tenta de novo.
