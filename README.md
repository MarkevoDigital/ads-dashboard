# Dashboard de Ads — Meta Ads + Google Ads

Dashboard web que se atualiza diariamente, com **KPIs que se adaptam ao objetivo
de cada campanha** (vendas, leads, conversas por mensagem, visitas ao Instagram,
tráfego, alcance), destaque dos **melhores anúncios com print**, **palavras-chave**
do Google Ads, **comparativos** (período e plataforma) e **comentários automáticos**
em português sobre os dados na tela.

Os dados vêm de uma planilha **Google Sheets**. Sem nenhuma configuração, o app já
roda com **dados de exemplo** para você validar o layout.

---

## 1. Rodar

O ambiente virtual (`.venv`) já está criado e com as dependências instaladas.
**Não precisa ativar o ambiente** — basta chamar o Python dele direto. No PowerShell:

```powershell
cd "C:\Users\User\OneDrive\Documentos\Claude\ads-dashboard"
.\.venv\Scripts\python.exe app.py
```

Abra no navegador: **http://127.0.0.1:5000**

> Já vem com dados de exemplo. Os CSVs modelo são gravados em `sample_data/`
> (`meta_ads.csv` e `google_ads.csv`) — use-os como **molde da sua planilha**.

> **Erro "execução de scripts foi desabilitada" / `Activate.ps1`?** Isso só acontece
> se você tentar *ativar* o ambiente. Use o comando acima (`.venv\Scripts\python.exe`),
> que **dispensa a ativação**. Se ainda assim quiser ativar, libere os scripts só para
> o seu usuário: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` (responda `S`).
> E confira que você está **dentro da pasta `ads-dashboard`** (use o `cd` acima).

### Recriar o ambiente do zero (se necessário)

```powershell
cd "C:\Users\User\OneDrive\Documentos\Claude\ads-dashboard"
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

---

## 2. Conectar dados reais e publicar na web

> **Para dados reais via API (Meta/Google Ads) + publicação no servidor com login do
> cliente, siga o [DEPLOY.md](DEPLOY.md)** — passo a passo de tokens, `.env` e cPanel/VPS.

Modos de fonte de dados (`config.json` ou variáveis de ambiente):
`api` · `service_account` · `csv_publicado` · `sample`. Abaixo, os modos via Google Sheets.

Copie `config.example.json` para `config.json` e escolha **um** dos modos.

### Modo A — CSV publicado (mais simples)
1. No Google Sheets: **Arquivo → Compartilhar → Publicar na web**.
2. Publique **cada aba** (meta_ads e google_ads) no formato **CSV**.
3. Cole as URLs em `config.json`:
```json
"fonte_dados": "csv_publicado",
"google_sheets": {
  "meta_csv_url": "https://docs.google.com/.../pub?gid=0&output=csv",
  "google_csv_url": "https://docs.google.com/.../pub?gid=1&output=csv"
}
```

### Modo B — Conta de serviço (privado, recomendado)
1. No Google Cloud, crie uma **conta de serviço**, ative a **Google Sheets API**
   e baixe o JSON de credenciais como `credentials.json` nesta pasta.
2. **Compartilhe a planilha** com o e-mail da conta de serviço (acesso de leitor).
3. Em `config.json`:
```json
"fonte_dados": "service_account",
"google_sheets": {
  "service_account_json": "credentials.json",
  "spreadsheet_id": "ID_DA_PLANILHA_NA_URL",
  "aba_meta": "meta_ads",
  "aba_google": "google_ads"
}
```

> **Como preencher a planilha automaticamente?** Use conectores como
> **Supermetrics**, **Coupler.io**, **Windsor.ai** ou os add-ons oficiais para
> puxar Meta/Google Ads para o Sheets todo dia. O dashboard apenas lê o resultado.

---

## 3. Estrutura da planilha (colunas)

**Aba `meta_ads`** (uma linha por anúncio por dia):

`date, account, objective, campaign, adset, ad_name, ad_thumbnail_url,
ad_permalink, impressions, reach, frequency, clicks, link_clicks, spend,
messaging_conversations, profile_visits, leads, purchases, purchase_value`

**Aba `google_ads`** (uma linha por palavra-chave por dia):

`date, account, objective, campaign, campaign_type, ad_group, keyword,
match_type, impressions, clicks, cost, conversions, conversion_value`

**Valores de `objective`** (definem quais KPIs aparecem em destaque):
`vendas` · `leads` · `mensagens` · `visitas_instagram` · `trafego` · `alcance`

> `ad_thumbnail_url` é o **print/criativo do anúncio** (uma URL de imagem). É o que
> aparece na seção "Melhores anúncios".

---

## 4. Atualização diária

O app recarrega os dados da planilha **todo dia** no horário definido em
`config.json` (`atualizacao.hora_diaria`, padrão **07:00**, fuso
`America/Sao_Paulo`). O servidor precisa estar rodando.

Para manter rodando sempre, agende `python app.py` no **Agendador de Tarefas do
Windows** (na inicialização) ou hospede em um servidor.

Botão **⟳ Atualizar** força a releitura na hora.

---

## 5. Como os KPIs se adaptam

| Objetivo            | KPI principal       | KPIs em destaque                                   |
|---------------------|---------------------|----------------------------------------------------|
| vendas              | ROAS                | Investimento, Receita, ROAS, Conversões, CPA, Taxa |
| leads               | Custo por lead      | Investimento, Leads, CPL, Taxa de lead, CTR, CPC   |
| mensagens           | Custo por conversa  | Investimento, Conversas, Custo/conversa, CTR, CPC  |
| visitas_instagram   | Custo por visita    | Investimento, Visitas, Custo/visita, CTR, CPC      |
| trafego             | CPC                 | Investimento, Cliques no link, CPC, CTR, CPM       |
| alcance             | CPM                 | Investimento, Alcance, CPM, Frequência, Impressões |

Cada conta mostra um bloco por objetivo presente nos dados, ordenado por investimento.

---

## Arquivos

```
app.py            servidor Flask + agendador diario + API
data_sources.py   leitura (Sheets/CSV/exemplo) + cache + dados de exemplo
metrics.py        catalogo de KPIs e configuracao por objetivo
analytics.py      melhores anuncios, palavras-chave, series, comparativos
commentary.py     comentarios automaticos (pt-BR)
templates/        dashboard.html
static/           css + js (Chart.js)
sample_data/      CSVs de exemplo (molde da planilha)
config.example.json  modelo de configuracao
```
