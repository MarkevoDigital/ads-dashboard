"""Faz um refresh completo do store FORA do Passenger e grava tmp/store_cache.pkl.
Uso (no servidor): python tools/seed_cache.py
Depois e so reiniciar o app (touch tmp/restart.txt) -> o worker sobe do cache em ~1s."""
import os, sys

# Limita threads de BLAS ANTES de importar numpy/pandas (LVE/RLIMIT_NPROC).
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")

# Locale ASCII (ex.: markevo42) quebraria prints com acento/travessao. UTF-8 seguro.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)

# Lock cross-process: garante UM UNICO seed por vez em TODA a conta (nproc/LVE).
# Sem isto, o cron + o agendador + um refresh manual poderiam rodar 2-3 seeds
# simultaneos (cada um carrega pandas) e estourar o limite de processos -> 503.
# O flock e liberado automaticamente quando este processo termina.
_LOCK_FD = None
try:
    import fcntl
    os.makedirs(os.path.join(BASE, "tmp"), exist_ok=True)
    _LOCK_FD = os.open(os.path.join(BASE, "tmp", "seed.lock"), os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(_LOCK_FD, fcntl.LOCK_EX | fcntl.LOCK_NB)
except ImportError:
    pass  # Windows (dev): sem lock cross-process.
except OSError:
    print("SEED_SKIP: outro seed ja esta em andamento (lock ocupado).")
    sys.exit(0)

envp = os.path.join(BASE, ".env")
if os.path.exists(envp):
    for raw in open(envp, encoding="utf-8"):
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k, v = raw.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from data_sources import DataStore, load_config, STORE_CACHE

store = DataStore(load_config())
# Carrega o historico ja gravado ANTES de atualizar: a rodada incremental busca poucos
# dias na API e mescla com o que ja existe. Sem isto o store comecaria vazio e a janela
# curta apagaria meses de dados. max_age alto de proposito: mesmo um cache velho serve
# de historico (as datas recentes sao substituidas pela coleta de agora).
store.load_cache(max_age_h=24 * 365 * 5)
# Argumento opcional: janela em dias a buscar (carga inicial de historico).
#   python tools/seed_cache.py 180   -> busca 180 dias de uma vez
dias = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else None
info = store.refresh(dias)
ok = os.path.exists(STORE_CACHE)
size = os.path.getsize(STORE_CACHE) if ok else 0
print("SEEDED", info, "| pickle?", ok, "| bytes", size, "| path", STORE_CACHE)

# Seguidores das Paginas LinkedIn dos clientes (1 medicao por dia, via cron do seed).
try:
    from data_sources import atualiza_seguidores_linkedin
    print("SEGUIDORES_LINKEDIN", atualiza_seguidores_linkedin())
except Exception as exc:  # noqa: BLE001
    print("SEGUIDORES_LINKEDIN falhou:", exc)
