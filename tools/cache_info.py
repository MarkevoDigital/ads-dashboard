"""Raio-x do cache em disco (tmp/store_cache.pkl): quantas linhas e QUE INTERVALO DE
DATAS cada plataforma tem guardado. E a forma rapida de confirmar se o historico de
180 dias esta completo depois de uma carga inicial, sem subir o app nem chamar API.

Uso (no servidor):  python tools/cache_info.py
Nao importa pandas por si so; o pickle ja traz DataFrames, entao mantemos o
OPENBLAS_NUM_THREADS=1 como no seed (LVE/RLIMIT_NPROC)."""
import os, sys, pickle, datetime

for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS",
           "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
    os.environ.setdefault(_v, "1")

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CAMINHO = sys.argv[1] if len(sys.argv) > 1 else os.path.join(BASE, "tmp", "store_cache.pkl")

if not os.path.exists(CAMINHO):
    print("SEM CACHE:", CAMINHO)
    sys.exit(1)

tam = os.path.getsize(CAMINHO)
mtime = datetime.datetime.fromtimestamp(os.path.getmtime(CAMINHO))
print(f"arquivo  {CAMINHO}")
print(f"tamanho  {tam / 1048576:.1f} MB   gravado em {mtime:%d/%m/%Y %H:%M}")

with open(CAMINHO, "rb") as fh:
    dados = pickle.load(fh)

print(f"updated_at {dados.get('updated_at')}  fonte {dados.get('source_label')}")
print(f"{'frame':<12}{'linhas':>9}  {'de':<12}{'ate':<12}{'dias':>5}")
for chave, df in dados.items():
    if not hasattr(df, "columns"):
        continue
    linhas = len(df)
    if "date" in df.columns and linhas:
        dt = df["date"]
        ini, fim = str(dt.min())[:10], str(dt.max())[:10]
        dias = dt.nunique()
    else:
        ini = fim = "-"
        dias = 0
    print(f"{chave:<12}{linhas:>9}  {ini:<12}{fim:<12}{dias:>5}")
