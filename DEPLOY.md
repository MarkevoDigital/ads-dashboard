# Guia de Deploy — dados reais + publicação na web

Este guia leva o dashboard de "dados de exemplo na sua máquina" para
"**dados reais via API**, no ar, acessível pelo cliente por um link com senha".

São 3 etapas:
1. **Obter os tokens de API** (Meta e Google Ads)
2. **Configurar o `.env`** com esses tokens
3. **Publicar no servidor da ValueServer** + agendar a atualização diária

> Os segredos ficam todos em variáveis de ambiente (`.env` / painel), nunca no código.

---

## Etapa 1 — Tokens de API

### 1A. Meta Ads (Facebook/Instagram)
Você precisa de **3 informações**: `access_token`, `ad_account_id`, versão da API.

1. Acesse **developers.facebook.com** → crie um App do tipo **Business** (ou use um existente).
2. Adicione o produto **Marketing API**.
3. Gere um **token de acesso** com a permissão **`ads_read`**.
   - Para produção, o ideal é um **token de Usuário de Sistema** (System User) no
     **Business Manager → Configurações → Usuários do sistema**, que **não expira**.
   - O token de teste do painel expira rápido — serve só para validar.
4. Pegue o **ID da conta de anúncios** no Gerenciador de Anúncios (formato `act_1234567890`).

Preencha no `.env`: `META_ACCESS_TOKEN`, `META_AD_ACCOUNT_IDS` (pode ter várias separadas por vírgula).

### 1B. Google Ads
Você precisa de **5 informações**: `developer_token`, `client_id`, `client_secret`,
`refresh_token`, `login_customer_id` (+ os `customer_ids` das contas).

1. **Developer token**: em **ads.google.com** → Ferramentas → **API Center**
   (precisa de uma conta **MCC/administrador**; o token pode exigir aprovação do Google).
2. **client_id / client_secret**: no **Google Cloud Console** → crie credenciais
   **OAuth 2.0 (tipo: App para computador/Desktop)**. Ative a **Google Ads API** no projeto.
3. **refresh_token**: gere uma vez autorizando sua conta. Caminho rápido com a lib oficial:
   ```bash
   pip install google-ads
   # use o utilitario oficial de exemplo "generate_user_credentials.py"
   # (https://developers.google.com/google-ads/api/docs/oauth/cloud-project)
   ```
4. **login_customer_id**: o ID da sua **MCC** (sem traços). `customer_ids`: as contas a ler.

Preencha no `.env`: `GOOGLE_DEVELOPER_TOKEN`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`,
`GOOGLE_REFRESH_TOKEN`, `GOOGLE_LOGIN_CUSTOMER_ID`, `GOOGLE_CUSTOMER_IDS`.

> **Posso te ajudar a gerar cada um desses** — é a parte mais chata. Me diga em qual
> trava que eu detalho o passo exato (inclusive o script do refresh_token).

---

## Etapa 2 — Configurar o `.env`

1. Copie `.env.example` para `.env`.
2. Preencha os tokens das etapas acima.
3. Defina `FONTE_DADOS=api`, e uma senha em `DASH_PASSWORD` (login do cliente) e um
   `CRON_TOKEN` aleatório (para o cron diário).

### Testar a conexão localmente antes de subir
```powershell
# na sua maquina, dentro de ads-dashboard
.\.venv\Scripts\python.exe -m pip install -r requirements.txt   # instala google-ads tambem
# carregue o .env e rode:
$env:FONTE_DADOS="api"; .\.venv\Scripts\python.exe app.py
```
Veja no terminal: `Carregado: API (Meta + Google Ads) (Meta=... linhas, Google=... linhas)`.
Se aparecer erro de token, corrija antes de publicar.

---

## Etapa 3A — Publicar na ValueServer via cPanel (mais comum)

A ValueServer usa **cPanel**, que tem **"Setup Python App"** (Passenger). Caminho:

1. **Envie os arquivos** do projeto para o servidor (Gerenciador de Arquivos do cPanel
   ou FTP). **NÃO** envie as pastas `.venv/` nem `__pycache__/`, nem o `config.json`.
   Sugestão de pasta no servidor: `~/dashboard`.
2. cPanel → **Setup Python App** → **Create Application**:
   - **Python version**: a mais nova disponível (3.10+).
   - **Application root**: `dashboard` (a pasta que você enviou).
   - **Application URL**: o domínio/subdomínio do cliente (ex: `dashboard.suaagencia.com.br`).
   - **Application startup file**: `passenger_wsgi.py`
   - **Application Entry point**: `application`
   - Clique em **Create**.
3. Ainda nessa tela, em **Environment variables**, cadastre as chaves do seu `.env`
   (`FONTE_DADOS=api`, `META_ACCESS_TOKEN`, `GOOGLE_*`, `DASH_PASSWORD`, `CRON_TOKEN` …).
   *(Alternativa: deixar um arquivo `.env` na pasta — o `passenger_wsgi.py` lê automaticamente.)*
4. Instale as dependências: a tela mostra um comando tipo
   `source /home/USUARIO/virtualenv/dashboard/3.x/bin/activate`. Rode-o no **Terminal**
   do cPanel e depois:
   ```bash
   pip install -r requirements.txt
   ```
   > Se a instalação do `google-ads` estourar limite de memória/tempo do plano
   > compartilhado, veja a observação no fim deste guia.
5. Clique em **Restart**. Acesse a URL — o navegador vai pedir **usuário e senha** (o que
   você definiu). Pronto: é esse link + senha que você entrega ao cliente.

### Atualização diária (cron do cPanel)
cPanel → **Cron Jobs** → adicione um job diário (ex.: 07:00):
```
curl -s "https://dashboard.suaagencia.com.br/cron/refresh?token=SEU_CRON_TOKEN" > /dev/null 2>&1
```
Isso força a releitura das APIs todo dia. (O app também se atualiza sozinho na primeira
visita de cada dia, então o cron é uma garantia extra.)

---

## Etapa 3B — Alternativa: VPS / Docker (se o "servidor" for um VPS)

Se vocês têm um **VPS** (acesso root/SSH), é ainda mais simples e robusto:

```bash
git clone <seu-repo>  # ou envie os arquivos
cd ads-dashboard
cp .env.example .env   # e preencha
docker compose up -d --build
```
O app sobe na porta **8000**. Coloque um **Nginx** na frente para domínio + HTTPS
(posso gerar o `nginx.conf` e o certificado Let's Encrypt se quiser).

Sem Docker, com gunicorn + systemd:
```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
gunicorn --bind 0.0.0.0:8000 --workers 2 --timeout 120 app:app
```

---

## Observações importantes

- **Performance Max (Google)** não expõe palavras-chave (limitação da Google); essas
  campanhas entram nos totais/comparativos, mas não na tabela de palavras-chave.
- **Visitas ao Instagram** nem sempre vêm pela API do Meta como ação rastreável; quando
  não vier, o card aparece zerado — me avise que ajusto o mapeamento de ações.
- **Mapeamento de objetivo**: o app traduz o objetivo do Meta/o canal do Google para os
  buckets do dashboard (vendas, leads, mensagens, visitas_instagram, trafego, alcance).
  Dá para sobrescrever caso a caso em `config.json` (`objective_map` / `campaign_objective_map`).
- **`google-ads` em hospedagem compartilhada**: é uma lib pesada (puxa gRPC). Se o plano
  da ValueServer não conseguir instalar, há 2 saídas: (a) usar um **VPS** (Etapa 3B), ou
  (b) trocar para o modo **Google Sheets**, onde um conector externo puxa os dados e o
  app só lê a planilha (sem precisar do `google-ads` no servidor). Posso adaptar.
- **Segurança**: nunca versione `.env` / `config.json` / `credentials.json` (já estão no
  `.gitignore`). Troque tokens se algum vazar.
