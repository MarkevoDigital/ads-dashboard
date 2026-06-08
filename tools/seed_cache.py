"""Faz um refresh completo do store FORA do Passenger e grava tmp/store_cache.pkl.
Uso (no servidor): python tools/seed_cache.py
Depois e so reiniciar o app (touch tmp/restart.txt) -> o worker sobe do cache em ~1s."""
import os, sys

# Limita threads de BLAS ANTES de importar numpy/pandas (LVE/RLIMIT_NPROC).
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE)
envp = os.path.join(BASE, ".env")
if os.path.exists(envp):
    for raw in open(envp, encoding="utf-8"):
        raw = raw.strip()
        if raw and not raw.startswith("#") and "=" in raw:
            k, v = raw.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from data_sources import DataStore, load_config, STORE_CACHE

store = DataStore(load_config())
info = store.refresh()
ok = os.path.exists(STORE_CACHE)
size = os.path.getsize(STORE_CACHE) if ok else 0
print("SEEDED", info, "| pickle?", ok, "| bytes", size, "| path", STORE_CACHE)
