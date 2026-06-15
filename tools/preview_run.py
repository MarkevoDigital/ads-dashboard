"""Launcher de preview LOCAL: roda o app em modo sample com TikTok de exemplo ligado.
Uso interno de verificacao (nao usar em producao)."""
import os
import runpy
import sys

os.environ.setdefault("FONTE_DADOS", "sample")
os.environ.setdefault("TIKTOK_SAMPLE", "1")
os.environ.setdefault("HOST", "127.0.0.1")
# Preview local sem login: zera DASH_PASSWORD ANTES do app carregar o .env
# (_load_dotenv usa setdefault, entao este valor vence e a auth fica desligada).
os.environ["DASH_PASSWORD"] = ""

_here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _here)   # garante que app.py ache analytics/data_sources/etc.
os.chdir(_here)
runpy.run_path(os.path.join(_here, "app.py"), run_name="__main__")
