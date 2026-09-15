"""OAuth do LinkedIn: fluxo de codigo de autorizacao + refresh programatico.

Por que existe: o LinkedIn nao entrega token de longa duracao. O access token vive
60 dias e o refresh token 365 dias FIXOS contados da autorizacao (renovar o access
token nao estende o refresh). Entao o dashboard guarda os dois num arquivo fora do
git e renova sozinho; so volta a precisar de uma pessoa uma vez por ano.

Fluxo: /linkedin/conectar (login admin) grava um `state` aleatorio em disco e manda o
navegador ao consentimento do LinkedIn; /linkedin/callback confere o state, troca o
codigo aqui mesmo no servidor e grava os tokens com permissao 600. Ninguem ve nem cola
token. O client secret vem do .env (LINKEDIN_CLIENT_SECRET) e nunca vai para log,
arquivo ou resposta HTTP.

Docs: learn.microsoft.com/linkedin/shared/authentication/authorization-code-flow
      learn.microsoft.com/linkedin/shared/authentication/programmatic-refresh-tokens
"""
import json
import os
import secrets
import time
from urllib.parse import quote, urlencode

import requests

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOKEN_FILE = os.path.join(BASE_DIR, "linkedin_token.json")
STATE_FILE = os.path.join(BASE_DIR, "tmp", "linkedin_oauth_state.json")
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"

# Anuncios (r_ads, r_ads_reporting) + seguidores da Pagina (rw_organization_admin).
# Pedir um conjunto de escopos DIFERENTE depois invalida todos os tokens anteriores,
# por isso vai tudo numa autorizacao so.
SCOPES = ("r_ads", "r_ads_reporting", "rw_organization_admin")
STATE_TTL = 30 * 60          # o codigo do LinkedIn vale 30 min; o state nao precisa mais
RENOVAR_ANTES = 7 * 86400    # renova o access token quando faltar menos de 7 dias


def _credenciais():
    cid = os.environ.get("LINKEDIN_CLIENT_ID", "").strip().strip('"').strip("'")
    sec = os.environ.get("LINKEDIN_CLIENT_SECRET", "").strip().strip('"').strip("'")
    if not cid or not sec:
        raise RuntimeError("LINKEDIN_CLIENT_ID e LINKEDIN_CLIENT_SECRET precisam estar no .env")
    return cid, sec


def redirect_uri() -> str:
    """Tem de ser IDENTICA a cadastrada em Auth > Authorized redirect URLs do app."""
    return (os.environ.get("LINKEDIN_REDIRECT_URI", "").strip()
            or "https://dashboard.markevo.com.br/linkedin/callback")


def _grava_privado(path: str, dados: dict) -> None:
    """Escrita atomica com permissao 600: o arquivo nunca fica pela metade nem legivel
    por outro usuario do servidor."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(dados, fh)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def url_autorizacao() -> str:
    cid, _ = _credenciais()
    state = secrets.token_urlsafe(32)
    _grava_privado(STATE_FILE, {"state": state, "criado": time.time()})
    query = urlencode({
        "response_type": "code",
        "client_id": cid,
        "redirect_uri": redirect_uri(),
        "state": state,
        "scope": " ".join(SCOPES),
    }, quote_via=quote)  # espacos como %20, como a doc pede
    return f"{AUTH_URL}?{query}"


def _consome_state(state: str) -> bool:
    """State de uso unico: e apagado na primeira tentativa, certa ou errada."""
    try:
        with open(STATE_FILE, encoding="utf-8") as fh:
            salvo = json.load(fh)
    except (OSError, ValueError):
        return False
    try:
        os.remove(STATE_FILE)
    except OSError:
        pass
    esperado = str(salvo.get("state", ""))
    fresco = time.time() - float(salvo.get("criado", 0)) <= STATE_TTL
    return bool(state) and bool(esperado) and fresco and secrets.compare_digest(state, esperado)


def carrega_token():
    try:
        with open(TOKEN_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _salva_resposta(body: dict) -> dict:
    agora = time.time()
    anterior = carrega_token() or {}
    dados = {
        "access_token": body["access_token"],
        "expira_em": agora + int(body.get("expires_in") or 0),
        # O refresh token so vem quando o app tem refresh programatico; ao renovar, o
        # LinkedIn devolve o mesmo refresh com o prazo restante.
        "refresh_token": body.get("refresh_token") or anterior.get("refresh_token"),
        "refresh_expira_em": (agora + int(body["refresh_token_expires_in"])
                              if body.get("refresh_token_expires_in") else anterior.get("refresh_expira_em")),
        "scope": body.get("scope", ""),
        "atualizado_em": agora,
    }
    _grava_privado(TOKEN_FILE, dados)
    return dados


def _post_token(dados: dict) -> dict:
    r = requests.post(TOKEN_URL, data=dados, timeout=60,
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        body = r.json()
    except ValueError:
        body = {}
    if r.status_code != 200 or "access_token" not in body:
        # Mensagem do LinkedIn so tem codigo e descricao do erro; nada de credencial.
        raise RuntimeError(f"LinkedIn recusou (HTTP {r.status_code}): "
                           f"{body.get('error', '')} {body.get('error_description', '')}"[:300])
    return body


def troca_codigo(code: str, state: str) -> dict:
    if not _consome_state(state):
        raise PermissionError("state invalido, expirado ou ja usado")
    cid, sec = _credenciais()
    body = _post_token({"grant_type": "authorization_code", "code": code, "client_id": cid,
                        "client_secret": sec, "redirect_uri": redirect_uri()})
    return _salva_resposta(body)


def access_token():
    """Access token valido para usar nas chamadas, renovando quando faltar menos de 7
    dias. None quando o LinkedIn nao foi conectado ou a autorizacao anual venceu."""
    tok = carrega_token()
    if not tok:
        return None
    agora = time.time()
    if float(tok.get("expira_em") or 0) - agora > RENOVAR_ANTES:
        return tok["access_token"]
    if tok.get("refresh_token") and float(tok.get("refresh_expira_em") or 0) > agora:
        try:
            cid, sec = _credenciais()
            body = _post_token({"grant_type": "refresh_token", "refresh_token": tok["refresh_token"],
                                "client_id": cid, "client_secret": sec})
            return _salva_resposta(body)["access_token"]
        except Exception as exc:  # noqa: BLE001
            print(f"[linkedin] renovacao do token falhou: {exc}")
    return tok["access_token"] if float(tok.get("expira_em") or 0) > agora else None


def status() -> dict:
    tok = carrega_token()
    if not tok:
        return {"conectado": False}
    agora = time.time()
    return {
        "conectado": True,
        "access_token_dias": round((float(tok.get("expira_em") or 0) - agora) / 86400, 1),
        "refresh_token_dias": (round((float(tok["refresh_expira_em"]) - agora) / 86400, 1)
                               if tok.get("refresh_expira_em") else None),
        "escopos": tok.get("scope", ""),
    }
