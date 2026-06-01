# Ponto de entrada WSGI para cPanel "Setup Python App" (Passenger).
#
# Em cPanel > Setup Python App, defina:
#   - Application startup file:  passenger_wsgi.py
#   - Application Entry point:   application
#
# As variaveis de ambiente (tokens, senha etc.) devem ser cadastradas na propria
# tela do Setup Python App (secao "Environment variables") ou num arquivo .env.

import os
import sys

# Garante que o diretorio do app esteja no path.
sys.path.insert(0, os.path.dirname(__file__))

# Carrega .env se existir (opcional).
_envfile = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(_envfile):
    for _line in open(_envfile, encoding="utf-8"):
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

from app import app as application  # noqa: E402
