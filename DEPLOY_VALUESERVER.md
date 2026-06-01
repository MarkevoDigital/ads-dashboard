# Deploy na ValueServer (cPanel) — passo a passo do seu ambiente

Ambiente detectado: **cPanel** `us151-cp.valueserver.com.br`, usuário **markevo42**,
domínio **markevo.com.br**, SSL ativo. Arquitetura: **uma única aplicação multi-cliente**
(cada cliente loga e vê só as contas dele; `admin` vê tudo).

Visão geral do deploy:
**GitHub** guarda o código → **cPanel "Git Version Control"** clona/atualiza no servidor →
**"Setup Python App" (Passenger)** roda o Flask → **.env + clients.json** ficam só no
servidor (fora do GitHub) → **Cron** atualiza os dados 1x/dia.

---

## 1. Subdomínio para o cliente
cPanel → **Domínios** → **Criar um domínio** → `dashboard.markevo.com.br`
(desmarque "compartilhar raiz do documento"; o Setup Python App define a pasta).
O SSL costuma ser emitido automaticamente (AutoSSL).

## 2. GitHub: repositório
Crie um repositório **privado** (ex.: `ads-dashboard`). O código já está commitado
localmente; o push é feito da sua máquina (veja a conversa) ou:
```powershell
git remote add origin https://github.com/SEU_USUARIO/ads-dashboard.git
git push -u origin main
```

## 3. cPanel: clonar o repositório
cPanel → **Git Version Control** → **Criar**:
- **Clone URL**: `https://github.com/SEU_USUARIO/ads-dashboard.git`
  (repo privado: gere um *Personal Access Token* no GitHub e use
  `https://SEU_USUARIO:TOKEN@github.com/SEU_USUARIO/ads-dashboard.git`)
- **Repository Path**: `/home/markevo42/dashboard-ads`
- Criar. Depois, em **Pull or Deploy → Update from Remote** sempre que houver mudanças.

## 4. cPanel: Setup Python App
cPanel → **Setup Python App** → **Create Application**:
- **Python version**: a mais nova (3.10+)
- **Application root**: `dashboard-ads` (a pasta clonada)
- **Application URL**: `dashboard.markevo.com.br`
- **Application startup file**: `passenger_wsgi.py`
- **Application Entry point**: `application`
- **Create**.

Depois, no **Terminal** do cPanel (ou no botão de comando da tela), entre no virtualenv
(a página mostra o comando `source ...activate`) e instale as dependências:
```bash
pip install -r requirements.txt
```
> A `google-ads` é pesada (puxa grpcio). Se faltar memória/tempo no plano compartilhado,
> instale em partes: `pip install grpcio` e depois `pip install -r requirements.txt`.
> Se mesmo assim falhar, me avise — migramos esse pedaço para um VPS ou modo Sheets.

## 5. Segredos no servidor (NÃO vão para o GitHub)
Pela tela do Setup Python App (**Environment variables**) **ou** via **File Manager**,
crie na pasta `dashboard-ads`:
- **`.env`** — copie o conteúdo do seu `.env` local (tokens Google/Meta, CRON_TOKEN).
- **`clients.json`** — o mapa de clientes (key, nome, senha, contas Meta+Google).

> Dica: no File Manager, "Upload" do `.env` e `clients.json` direto da sua máquina.
> Eles estão no `.gitignore`, então nunca sobem ao GitHub.

Reinicie o app (**Restart** na tela do Setup Python App).

## 6. Atualização diária (Cron)
cPanel → **Cron Jobs** → adicionar (ex. 07:00):
```
curl -s "https://dashboard.markevo.com.br/cron/refresh?token=SEU_CRON_TOKEN" > /dev/null 2>&1
```
(o `CRON_TOKEN` está no seu `.env`.)

## 7. Entregar ao cliente
Cada cliente acessa **https://dashboard.markevo.com.br** e faz login com o **usuário
(key) e senha** definidos no `clients.json`. Ele verá **apenas as contas dele**.
A agência usa o login **admin** para ver todos.

## Atualizar o app depois (fluxo normal)
1. `git push` da sua máquina → 2. cPanel **Git Version Control → Update from Remote**
→ 3. **Restart** no Setup Python App. (Os dados se atualizam sozinhos pelo cron/cache.)

---

### Observações
- O `win-ca-bundle.pem` é **só do seu PC** (antivírus/proxy). No servidor Linux não existe
  e não é necessário — o `app.py` só o usa se o arquivo estiver presente.
- Se o plano compartilhado não aguentar a `google-ads`, a alternativa mais robusta é um
  **VPS** (já há `Dockerfile`/`docker-compose.yml` prontos) — deploy em 1 comando.
