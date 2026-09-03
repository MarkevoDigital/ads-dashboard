// Dashboard de Ads — front-end
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  let trendChart = null, platformChart = null, clientLoaded = false, accountsSig = null;
  let geoMap = null, geoMarkers = null, monthsLoaded = false;
  const MESES =["janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];

  // ---- Idioma e moeda (vem do payload; o login define os dois) -----------
  // O dashboard nasceu em pt-BR e continua assim por padrao. Clientes com
  // "idioma": "en" recebem a interface em ingles; a moeda vem da conta de
  // anuncios (nao e chutada), entao ha cliente em US$ e cliente em R$.
  let LANG = "pt";
  let MOEDA = { codigo: "BRL", simbolo: "R$", locale: "pt-BR" };
  let nf = new Intl.NumberFormat("pt-BR");
  let cf = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });
  let domTraduzido = false;

  const I18N_EN = {
    "Dashboard de Ads": "Ads Dashboard",
    "Ver como": "View as",
    "Conta": "Account",
    "Todas as contas": "All accounts",
    "Plataforma": "Platform",
    "Meta + Google": "Meta + Google",
    "Somente Meta": "Meta only",
    "Somente Google": "Google only",
    "Somente TikTok": "TikTok only",
    "Período": "Date range",
    "Últimos 7 dias": "Last 7 days",
    "Últimos 14 dias": "Last 14 days",
    "Últimos 30 dias": "Last 30 days",
    "Últimos 60 dias": "Last 60 days",
    "Por mês": "By month",
    "Personalizado…": "Custom…",
    "Datas": "Dates",
    "⟳ Atualizar": "⟳ Refresh",
    "⬇ Exportar em PDF": "⬇ Export to PDF",
    "SAIR": "⎋ Sign out",
    "Recarregar dados da fonte": "Reload data from the source",
    "Exportar a visualização atual em PDF": "Export the current view to PDF",
    "Sair e entrar com outro acesso": "Sign out and use another login",
    "Agência (todos os clientes)": "Agency (all clients)",
    "Relatório de Tráfego Pago": "Paid Media Report",
    "🔻 Funil de resultados": "🔻 Results funnel",
    "🧠 Análise de dados": "🧠 Data analysis",
    "💰 Investimento": "💰 Spend",
    "📈 Evolução diária": "📈 Daily trend",
    "🗂️ Campanhas por plataforma": "🗂️ Campaigns by platform",
    "Campanhas com veiculação no período filtrado.": "Campaigns that delivered in the selected period.",
    "📸 Seguidores do Instagram": "📸 Instagram followers",
    "Dados orgânicos da conta (todos os seguidores, não só os vindos de anúncios).": "Organic account data (all followers, not only those coming from ads).",
    "🎯 Conjuntos de anúncios / Grupos de recursos": "🎯 Ad sets / Asset groups",
    "Conjuntos de anúncios (Meta) e grupos de anúncios/recursos (Google) com veiculação no período.": "Meta ad sets and Google ad/asset groups that delivered in the period.",
    "Campanha": "Campaign",
    "Todas as campanhas": "All campaigns",
    "Conjunto": "Ad set",
    "Todos os conjuntos": "All ad sets",
    "🏆 Melhores anúncios do Meta Ads": "🏆 Top Meta Ads creatives",
    "Criativo destaque por objetivo (com print do anúncio).": "Top creative per objective (with a preview).",
    "🖼️ Anúncios veiculados": "🖼️ Ads delivered",
    "Anúncios do Meta com entrega no período, agrupados por nome, campanha e conjunto.": "Meta ads that delivered in the period, grouped by name, campaign and ad set.",
    "🎵 TikTok Ads": "🎵 TikTok Ads",
    "Desempenho do TikTok no período (também já somado aos totais e gráficos acima).": "TikTok performance in the period (already included in the totals and charts above).",
    "🏆 Melhores anúncios do TikTok": "🏆 Top TikTok ads",
    "🔑 Palavras-chave (Google Ads)": "🔑 Keywords (Google Ads)",
    "⚖️ Meta x Google": "⚖️ Meta vs. Google",
    "🔁 Período atual vs. anterior": "🔁 Current vs. previous period",
    "📍 Mapa de calor — cliques por estado": "📍 Heat map — clicks by state",
    "Carregando…": "Loading…",
    "Atualização automática diária · Meta Ads + Google Ads": "Updated automatically every day · Meta Ads + Google Ads",
    "Sem dados no período selecionado.": "No data for the selected period.",
    "Erro ao carregar dados.": "Failed to load data.",
    "⏳ Carregando os dados pela primeira vez (pode levar 1–2 min). Atualize a página em instantes.": "⏳ Loading data for the first time (it may take 1–2 min). Refresh the page shortly.",
    "Sem anúncios TikTok com investimento relevante no período.": "No TikTok ads with relevant spend in the period.",
    "Sem anúncios com investimento relevante.": "No ads with relevant spend.",
    "Sem campanhas no período.": "No campaigns in the period.",
    "Sem conjuntos/grupos no período": "No ad sets/groups in the period",
    " para esta campanha": " for this campaign",
    "Sem anúncios veiculados no período": "No ads delivered in the period",
    " para este filtro": " for this filter",
    "Objetivo": "Objective",
    "Orç./dia": "Budget/day",
    "Orçamento diário": "Daily budget",
    "Invest.": "Spend",
    "Impr.": "Impr.",
    "Cliques": "Clicks",
    "Conv.": "Conv.",
    "Conjunto / Grupo": "Ad set / Group",
    "Anúncio": "Ad",
    "Palavra-chave": "Keyword",
    "Métrica": "Metric",
    "Atual": "Current",
    "Anterior": "Previous",
    "Variação": "Change",
    "Página": "Page",
    "Seguidores": "Followers",
    "Novos": "New",
    "Crescimento": "Growth",
    "Cidade": "City",
    "Views vídeo": "Video views",
    "Visitas IG": "IG visits",
    "Engaj.": "Engagement",
    "Verde = em veiculação · Vermelho = inativa": "Green = delivering · Red = inactive",
    "Verde = em veiculação · Vermelho = inativo": "Green = delivering · Red = inactive",
    "Em veiculação": "Delivering",
    "Não ativa no momento": "Not active right now",
    "Não ativo no momento": "Not active right now",
    "Abrir anúncio": "Open ad",
    "Ver anúncio ↗": "View ad ↗",
    "Investimento": "Spend",
    "Conversões": "Conversions",
    "Cliques / Conversões": "Clicks / Conversions",
    "Novos seguidores/dia": "New followers/day",
    "Vendo como: ": "Viewing as: ",
    "Fonte: ": "Source: ",
    " · atualizado ": " · updated ",
    "Anterior: ": "Previous: ",
    "— vs. período anterior": "— vs. previous period",
    "vs. anterior": "vs. previous",
  };

  const MESES_EN = ["January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"];

  function T(txt) {
    if (LANG !== "en") return txt;
    return Object.prototype.hasOwnProperty.call(I18N_EN, txt) ? I18N_EN[txt] : txt;
  }

  function setLocale(idioma, moeda) {
    if (moeda && moeda.codigo) MOEDA = moeda;
    LANG = idioma === "en" ? "en" : "pt";
    const loc = LANG === "en" ? "en-US" : "pt-BR";
    nf = new Intl.NumberFormat(loc);
    try {
      cf = new Intl.NumberFormat(loc, { style: "currency", currency: MOEDA.codigo || "BRL" });
    } catch (e) {
      cf = new Intl.NumberFormat(loc, { style: "currency", currency: "BRL" });
    }
    if (LANG === "en" && !domTraduzido) { traduzirDOM(); domTraduzido = true; }
  }

  // Traduz o texto ESTATICO da pagina (marcado com data-i18n no HTML). Roda uma
  // unica vez, quando o payload informa que este login e em ingles.
  function traduzirDOM() {
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      const v = I18N_EN[el.getAttribute("data-i18n")];
      if (v) el.textContent = v;
    });
    document.querySelectorAll("[data-i18n-title]").forEach((el) => {
      const v = I18N_EN[el.getAttribute("data-i18n-title")];
      if (v) el.setAttribute("title", v);
    });
    document.querySelectorAll("select[data-all]").forEach((el) => {
      const v = I18N_EN[el.getAttribute("data-all")];
      if (v) { el.setAttribute("data-all", v); if (el.options[0]) el.options[0].textContent = v; }
    });
    document.title = "Ads Dashboard";
  }

  // Separador decimal do idioma (pt-BR usa virgula; ingles usa ponto).
  function dec(v, casas) {
    const t = v.toFixed(casas);
    return LANG === "en" ? t : t.replace(".", ",");
  }

  function fmt(value, kind) {
    if (value === null || value === undefined) return "—";
    switch (kind) {
      case "currency": return cf.format(value);
      case "int": return nf.format(Math.round(value));
      case "pct": return dec(value * 100, 2) + "%";
      case "ratio": return dec(value, 2) + "x";
      case "dec": return dec(value, 2);
      default: return String(value);
    }
  }

  // Percentual de variacao com o separador decimal do idioma (3,0% x 3.0%).
  function pctVar(v) {
    const t = Math.abs(v).toFixed(1);
    return (LANG === "en" ? t : t.replace(".", ",")) + "%";
  }

  function deltaHtml(delta, good) {
    if (delta === null || delta === undefined)
      return `<span class="k-delta neutral">—</span>`;
    const cls = good === true ? "good" : good === false ? "bad" : "neutral";
    const arrow = delta > 0 ? "▲" : delta < 0 ? "▼" : "■";
    return `<span class="k-delta ${cls}">${arrow} ${pctVar(delta)}</span>`;
  }

  async function load() {
    $("loading").classList.remove("hidden");
    const params = new URLSearchParams({
      account: $("f-account").value, platform: $("f-platform").value,
      client: $("f-client") ? $("f-client").value : "",
    });
    const pv = $("f-days").value;
    if (pv === "custom") {
      const s = $("f-start").value, e = $("f-end").value;
      if (!s || !e) { $("loading").classList.add("hidden"); return; }  // espera as 2 datas
      params.set("start", s); params.set("end", e);
    } else if (pv.startsWith("m:")) {
      const [y, m] = pv.slice(2).split("-").map(Number);
      const last = new Date(y, m, 0).getDate();
      const mm = String(m).padStart(2, "0");
      params.set("start", `${y}-${mm}-01`);
      params.set("end", `${y}-${mm}-${String(last).padStart(2, "0")}`);
    } else {
      params.set("days", pv);
    }
    try {
      const res = await fetch("/api/data?" + params.toString());
      render(await res.json());
    } catch (e) {
      console.error(e);
      $("comments").innerHTML = `<div class="comment alerta">${T("Erro ao carregar dados.")}</div>`;
    } finally {
      $("loading").classList.add("hidden");
    }
  }

  function render(data) {
    // Idioma e moeda deste login, antes de qualquer formatacao.
    setLocale(data.idioma, data.moeda);
    // Seletor "Ver como" (somente admin/agência): popula uma vez e revela.
    if (data.clientes_admin && !clientLoaded) {
      const cs = $("f-client");
      // Agencia de grupo: a opcao "todos" e o grupo, nao a agencia inteira.
      if (data.agencia_grupo && cs.options.length) {
        cs.options[0].textContent = ((data.meta_info || {}).cliente || "Grupo") + " (todos do grupo)";
      }
      data.clientes_admin.forEach((c) => {
        const o = document.createElement("option"); o.value = c.key; o.textContent = c.nome; cs.appendChild(o);
      });
      $("f-client-wrap").classList.remove("hidden");
      clientLoaded = true;
    }
    // Contas: (re)popula quando o conjunto muda (ex.: admin trocou de cliente).
    if (data.contas) {
      const sig = data.contas.join("|");
      if (sig !== accountsSig) {
        const sel = $("f-account");
        sel.innerHTML = `<option value="todas">${T("Todas as contas")}</option>`;
        data.contas.forEach((c) => {
          const o = document.createElement("option"); o.value = c; o.textContent = c; sel.appendChild(o);
        });
        accountsSig = sig;
      }
    }
    const mi = data.meta_info || {};
    let reportClient = "";
    if (data.cliente_sel && $("f-client")) {
      const opt = $("f-client").options[$("f-client").selectedIndex];
      reportClient = opt ? opt.textContent : data.cliente_sel;
      $("cliente-sub").textContent = T("Vendo como: ") + reportClient;
    } else if (mi.cliente) {
      reportClient = mi.cliente;
      $("cliente-sub").textContent = mi.cliente;
    }
    if ($("report-client")) $("report-client").textContent = reportClient;
    $("src-info").textContent = T("Fonte: ") + (mi.fonte || "—") +
      (mi.atualizado_em ? T(" · atualizado ") + new Date(mi.atualizado_em)
        .toLocaleString(LANG === "en" ? "en-US" : "pt-BR",
                        { timeZone: "America/Sao_Paulo" }) : "");

    if (data.vazio) {
      $("period-info").textContent = "";
      $("funnel").innerHTML = "";
      if (data.carregando) {
        $("comments").innerHTML = `<div class="comment info">${T("⏳ Carregando os dados pela primeira vez (pode levar 1–2 min). Atualize a página em instantes.")}</div>`;
        setTimeout(load, 15000);  // re-tenta sozinho enquanto carrega
      } else {
        $("comments").innerHTML = `<div class="comment info">${T("Sem dados no período selecionado.")}</div>`;
      }
      $("objective-blocks").innerHTML = "";
      $("keywords-wrap").innerHTML = ""; $("campaigns-wrap").innerHTML = "";
      $("ads-wrap").innerHTML = ""; $("adsets-wrap").innerHTML = "";
      // Sem dados no período: as seções de anúncios/conjuntos também somem inteiras.
      $("best-ads-section").classList.add("hidden");
      $("ads-table-section").classList.add("hidden");
      $("adsets-table-section").classList.add("hidden");
      $("keywords-section").classList.add("hidden");
      $("kw-platform-row").classList.add("one-col");
      $("geo-section").classList.add("hidden");
      $("tiktok-section").classList.add("hidden");
      // Instagram é orgânico: aparece mesmo sem veiculação de anúncios no período.
      renderInstagram(data);
      return;
    }

    const p = data.periodo;
    $("period-info").textContent =
      LANG === "en"
        ? `Period: ${p.inicio} to ${p.fim} (previous: ${p.anterior_inicio} to ${p.anterior_fim})`
        : `Período: ${p.inicio} a ${p.fim} (anterior: ${p.anterior_inicio} a ${p.anterior_fim})`;
    if ($("report-period")) $("report-period").textContent =
      LANG === "en" ? `Period: ${p.inicio} to ${p.fim}` : `Período: ${p.inicio} a ${p.fim}`;

    populateMonths(p.fim);

    renderFunnel(data.funil);
    renderComments(data.comentarios);
    renderInvestimento(data.investimento);
    renderObjectiveBlocks(data.blocos_objetivo);
    renderTrend(data.serie_temporal);
    renderBestAds(data.melhores_anuncios);
    renderAdSets(data.conjuntos);
    renderAds(data.anuncios);
    // TikTok: opção no seletor de plataforma + seção dedicada (data-driven: só p/ clientes
    // com TikTok). ensurePlatformOption insere/remove a opção conforme tem_tiktok.
    ensurePlatformOption(!!data.tem_tiktok);
    const plat = (data.filtros || {}).platform;
    // Melhores anúncios (Meta) e Anúncios veiculados: ocultar em "Somente Google".
    // Em "Somente TikTok" os melhores do Meta somem; a tabela de anúncios mostra TikTok.
    // Somem por completo quando NAO HA DADOS (cliente sem Meta/TikTok, por exemplo),
    // em vez de aparecerem zeradas — mesma regra data-driven das seções TikTok/Instagram.
    // Obs.: a tabela de anúncios usa os dados SEM filtro; se o usuário filtrar por
    // campanha e não sobrar linha, a seção continua visível (senão ele não conseguiria
    // desfazer o filtro).
    $("best-ads-section").classList.toggle("hidden",
      plat === "google" || plat === "tiktok" || !(data.melhores_anuncios || []).length);
    $("ads-table-section").classList.toggle("hidden",
      plat === "google" || !(data.anuncios || []).length);
    renderTikTok(data, plat);
    renderCampaigns(data.campanhas);
    renderInstagram(data);
    renderKeywords(data.palavras_chave);
    renderPlatform(data.comparativo_plataforma);
    renderPeriod(data.comparativo_periodo);
    // Mapa de calor SEMPRE por Estados (Meta + Google somados). As cidades vão numa
    // tabela abaixo do mapa (oculta para clientes sem dados de cidade / sem Google).
    renderGeo(data.geo);
    renderGeoCities(data.geo_cidades);
  }

  // ---- Seletor de meses (gera os últimos 6 meses a partir da data final dos dados) ----
  function populateMonths(fim) {
    if (monthsLoaded || !fim) return;
    const og = $("f-months"); if (!og) return;
    const [y, m] = fim.split("-").map(Number);
    let yy = y, mm = m;
    for (let i = 0; i < 6; i++) {
      const o = document.createElement("option");
      o.value = `m:${yy}-${String(mm).padStart(2, "0")}`;
      o.textContent = LANG === "en" ? `${MESES_EN[mm - 1]} ${yy}`
                                    : `${MESES[mm - 1]} de ${yy}`;
      og.appendChild(o);
      mm--; if (mm < 1) { mm = 12; yy--; }
    }
    monthsLoaded = true;
  }

  // ---- Funil ----
  function renderFunnel(f) {
    const wrap = $("funnel");
    if (!f || !f.stages || !f.stages.length) { wrap.innerHTML = ""; return; }
    const maxV = Math.max(...f.stages.map((s) => s.value)) || 1;
    let html = "";
    f.stages.forEach((s, i) => {
      const w = Math.max((s.value / maxV) * 100, 26);
      const cost = s.cost_label
        ? `<span class="fn-cost">${s.cost_label}: ${fmt(s.cost, "currency")}</span>` : "";
      // Etapa orgânica (seguidores do IG): estilo próprio, para não ser lida como
      // conversão das campanhas — o número é da conta inteira.
      const cls = s.organico ? "fn-stage organico" : "fn-stage";
      html += `<div class="${cls}" style="width:${w}%">
        <span class="fn-label">${s.label}</span>
        <span class="fn-value">${fmt(s.value, s.fmt)}</span>
        ${cost}</div>`;
      if (i < f.stages.length - 1 && f.rates && f.rates[i]) {
        html += `<div class="fn-rate">▼ ${f.rates[i].label}: <b>${fmt(f.rates[i].value, "pct")}</b></div>`;
      }
    });
    wrap.innerHTML = html;
  }

  // ---- Investimento por plataforma ----
  function renderInvestimento(inv) {
    const wrap = $("investimento");
    if (!inv) { wrap.innerHTML = ""; return; }
    const card = (label, cls, d) => {
      const dt = (d.delta_pct === null || d.delta_pct === undefined)
        ? `<span class="iv-delta">${T("— vs. período anterior")}</span>`
        : `<span class="iv-delta">${d.delta_pct > 0 ? "▲" : d.delta_pct < 0 ? "▼" : "■"} ${pctVar(d.delta_pct)} ${T("vs. anterior")}</span>`;
      return `<div class="invest-card ${cls}">
        <div class="iv-label">${label}</div>
        <div class="iv-value">${fmt(d.atual, "currency")}</div>
        ${dt}
        <div class="iv-prev">${T("Anterior: ")}${fmt(d.anterior, "currency")}</div>
      </div>`;
    };
    wrap.innerHTML = card("Meta Ads", "iv-meta", inv.meta)
      + card("Google Ads", "iv-google", inv.google)
      + (inv.tiktok ? card("TikTok Ads", "iv-tiktok", inv.tiktok) : "")
      + card("Total", "iv-total", inv.total);
  }

  // ---- TikTok: opção de plataforma (insere/remove conforme o cliente tem TikTok) ----
  function ensurePlatformOption(hasTikTok) {
    const sel = $("f-platform");
    const combined = sel.querySelector('option[value="todas"]');
    let opt = sel.querySelector('option[value="tiktok"]');
    if (hasTikTok) {
      if (combined) combined.textContent = "Meta + Google + TikTok";
      if (!opt) {
        opt = document.createElement("option");
        opt.value = "tiktok"; opt.textContent = "Somente TikTok";
        sel.appendChild(opt);
      }
    } else {
      if (combined) combined.textContent = "Meta + Google";
      if (opt) {
        if (sel.value === "tiktok") { sel.value = "todas"; }
        opt.remove();
      }
    }
  }

  // ---- TikTok: seção dedicada (KPIs de destaque + melhores anúncios do TikTok) ----
  function renderTikTok(data, plat) {
    const sec = $("tiktok-section");
    const tk = data.tiktok;
    // Mostra só quando o cliente tem TikTok e o filtro não está em Meta/Google.
    if (!data.tem_tiktok || !tk || plat === "meta" || plat === "google") {
      sec.classList.add("hidden"); return;
    }
    sec.classList.remove("hidden");
    $("tiktok-kpis").innerHTML = (tk.kpis || []).map((c) => `
      <div class="kpi">
        <div class="k-label">${c.label}</div>
        <div class="k-value">${fmt(c.value, c.fmt)}</div>
        ${deltaHtml(c.delta_pct, c.good)}
      </div>`).join("");
    const ads = tk.melhores_anuncios || [];
    $("tiktok-best-ads").innerHTML = ads.length
      ? ads.map((a, i) => {
        const link = a.permalink || "";
        const img = a.thumbnail
          ? `<img class="thumb" src="${a.thumbnail}" alt="Print do anuncio" loading="lazy" onerror="this.style.display='none'">`
          : "";
        const thumb = link && img ? `<a href="${link}" target="_blank" rel="noopener" title="${T("Abrir anúncio")}">${img}</a>` : img;
        const verLink = link ? `<a class="ad-link" href="${link}" target="_blank" rel="noopener">${T("Ver anúncio ↗")}</a>` : "";
        return `
        <div class="ad-card" style="position:relative">
          <div class="rank-badge">${i + 1}</div>
          ${thumb}
          <div class="ad-body">
            <div class="ad-name">${a.ad_name}</div>
            <div class="ad-tag">${a.account} · ${a.objective_label}</div>
            <div class="ad-metric">${fmt(a.result_value, a.result_fmt)}<small>${a.result_label}</small></div>
            <div class="ad-sub">${a.eff_label}: ${fmt(a.eff_value, a.eff_fmt)} · Invest.: ${fmt(a.spend, "currency")} · CTR ${fmt(a.ctr, "pct")} · ${fmt(a.impressions, "int")} impr.</div>
            ${verLink}
          </div></div>`;
      }).join("")
      : `<div class="empty">${T("Sem anúncios TikTok com investimento relevante no período.")}</div>`;
  }

  // ---- Comentario unico ----
  function renderComments(c) {
    const wrap = $("comments");
    if (!c) { wrap.innerHTML = ""; return; }
    const bullets = (c.destaques || []).map((d) => `<li>${d}</li>`).join("");
    wrap.innerHTML = `<p class="cm-resumo">${c.resumo || ""}</p><ul class="cm-list">${bullets}</ul>`;
  }

  // ---- Blocos por objetivo ----
  function renderObjectiveBlocks(blocks) {
    const wrap = $("objective-blocks");
    if (!blocks || !blocks.length) { wrap.innerHTML = ""; return; }
    wrap.innerHTML = blocks.map((b) => {
      const cards = b.cards.map((c) => `
        <div class="kpi ${c.is_primary ? "primary" : ""}">
          <div class="k-label">${c.label}${c.is_primary ? " ★" : ""}</div>
          <div class="k-value">${fmt(c.value, c.fmt)}</div>
          ${deltaHtml(c.delta_pct, c.good)}
        </div>`).join("");
      return `<div class="card obj-block">
          <div class="obj-head"><h3>${b.label}</h3>
            <span class="obj-spend">Investimento: ${fmt(b.spend, "currency")}</span></div>
          <div class="kpi-grid">${cards}</div></div>`;
    }).join("");
  }

  // ---- Melhores anuncios ----
  function renderBestAds(ads) {
    const wrap = $("best-ads");
    if (!ads || !ads.length) { wrap.innerHTML = `<div class="empty">${T("Sem anúncios com investimento relevante.")}</div>`; return; }
    wrap.innerHTML = ads.map((a, i) => {
      const link = a.permalink || "";
      const img = `<img class="thumb" src="${a.thumbnail}" alt="Print do anuncio" loading="lazy" onerror="this.style.display='none'">`;
      const thumb = link ? `<a href="${link}" target="_blank" rel="noopener" title="${T("Abrir anúncio")}">${img}</a>` : img;
      const verLink = link ? `<a class="ad-link" href="${link}" target="_blank" rel="noopener">${T("Ver anúncio ↗")}</a>` : "";
      return `
      <div class="ad-card" style="position:relative">
        <div class="rank-badge">${i + 1}</div>
        ${thumb}
        <div class="ad-body">
          <div class="ad-name">${a.ad_name}</div>
          <div class="ad-tag">${a.account} · ${a.objective_label}</div>
          <div class="ad-metric">${fmt(a.result_value, a.result_fmt)}<small>${a.result_label}</small></div>
          <div class="ad-sub">${a.eff_label}: ${fmt(a.eff_value, a.eff_fmt)} · Invest.: ${fmt(a.spend, "currency")} · CTR ${fmt(a.ctr, "pct")} · ${fmt(a.impressions, "int")} impr.</div>
          ${verLink}
        </div></div>`;
    }).join("");
  }

  // ---- Campanhas por plataforma ----
  function renderCampaigns(rows) {
    const wrap = $("campaigns-wrap");
    if (!rows || !rows.length) { wrap.innerHTML = `<div class="empty">${T("Sem campanhas no período.")}</div>`; return; }
    // Colunas extras (views de video, visitas ao Instagram, engajamento) so aparecem
    // se houver valor > 0 em alguma campanha — respeita a regra de ocultar zerados.
    const extra = [
      { key: "video_views", label: T("Views vídeo"), fmt: "int" },
      { key: "profile_visits", label: T("Visitas IG"), fmt: "int" },
      { key: "engagement", label: T("Engaj."), fmt: "int" },
    ].filter((c) => rows.some((r) => (r[c.key] || 0) > 0));
    const extraHead = extra.map((c) => `<th>${c.label}</th>`).join("");
    const body = rows.map((r) => {
      const extraCells = extra.map((c) => `<td>${fmt(r[c.key], c.fmt)}</td>`).join("");
      const dot = `<span class="status-dot ${r.ativo ? "on" : "off"}" title="${r.ativo ? T("Em veiculação") : T("Não ativa no momento")}"></span>`;
      const orc = r.orcamento_diario ? fmt(r.orcamento_diario, "currency") : "—";
      return `<tr>
        <td class="status-cell">${dot}</td>
        <td><span class="plat ${r.plataforma.toLowerCase()}">${r.plataforma}</span></td>
        <td>${r.campanha}</td><td>${r.objetivo}</td>
        <td>${orc}</td><td>${fmt(r.spend, "currency")}</td><td>${fmt(r.impressions, "int")}</td>
        <td>${fmt(r.clicks, "int")}</td><td>${fmt(r.ctr, "pct")}</td>
        <td>${fmt(r.conversions, "int")}</td><td>${fmt(r.cpa, "currency")}</td>${extraCells}</tr>`;
    }).join("");
    wrap.innerHTML = `<table><thead><tr><th title="${T("Verde = em veiculação · Vermelho = inativa")}">●</th>
      <th>${T("Plataforma")}</th><th>${T("Campanha")}</th><th>${T("Objetivo")}</th>
      <th title="${T("Orçamento diário")}">${T("Orç./dia")}</th><th>${T("Invest.")}</th><th>${T("Impr.")}</th><th>${T("Cliques")}</th><th>CTR</th><th>${T("Conv.")}</th><th>CPA</th>${extraHead}</tr></thead>
      <tbody>${body}</tbody></table>`;
  }

  // Escapa texto p/ uso seguro em atributos/opcoes (nomes com &, <, >, ").
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  // Repovoa um <select> preservando a selecao atual (se ainda existir nas opcoes).
  function fillSelectPreserve(sel, values) {
    const cur = sel.value;
    const allLabel = sel.dataset.all || "Todos";
    sel.innerHTML = `<option value="">${esc(allLabel)}</option>` +
      values.map((v) => `<option value="${esc(v)}">${esc(v)}</option>`).join("");
    sel.value = values.includes(cur) ? cur : "";
  }

  // Colunas extras (views vídeo, visitas IG, engaj.) só quando há valor > 0. Compartilhado
  // pelas tabelas de conjuntos e de anúncios.
  function extraCols(rows) {
    return [
      { key: "video_views", label: T("Views vídeo"), fmt: "int" },
      { key: "profile_visits", label: T("Visitas IG"), fmt: "int" },
      { key: "engagement", label: T("Engaj."), fmt: "int" },
    ].filter((c) => rows.some((r) => (r[c.key] || 0) > 0));
  }

  // ---- Conjuntos de anúncios / Grupos de recursos ----
  let _adsetData = [];
  function renderAdSets(rows) {
    _adsetData = rows || [];
    // Sem nenhum conjunto/grupo no período: some a seção inteira (data-driven).
    $("adsets-table-section").classList.toggle("hidden", !_adsetData.length);
    if (!_adsetData.length) return;
    const camps = [...new Set(_adsetData.map((r) => r.campanha))].sort((a, b) => a.localeCompare(b, "pt"));
    fillSelectPreserve($("f-adset-camp"), camps);
    drawAdSets();
  }
  function drawAdSets() {
    const wrap = $("adsets-wrap");
    const camp = $("f-adset-camp").value;
    let rows = _adsetData;
    if (camp) rows = rows.filter((r) => r.campanha === camp);
    if (!rows.length) {
      wrap.innerHTML = `<div class="empty">${T("Sem conjuntos/grupos no período")}${camp ? T(" para esta campanha") : ""}.</div>`;
      return;
    }
    const extra = extraCols(rows);
    const extraHead = extra.map((c) => `<th>${c.label}</th>`).join("");
    const body = rows.map((r) => {
      const extraCells = extra.map((c) => `<td>${fmt(r[c.key], c.fmt)}</td>`).join("");
      const dot = `<span class="status-dot ${r.ativo ? "on" : "off"}" title="${r.ativo ? T("Em veiculação") : T("Não ativo no momento")}"></span>`;
      return `<tr>
        <td class="status-cell">${dot}</td>
        <td><span class="plat ${r.plataforma.toLowerCase()}">${r.plataforma}</span></td>
        <td>${r.campanha}</td><td>${esc(r.conjunto)}</td><td>${r.objetivo}</td>
        <td>${fmt(r.spend, "currency")}</td><td>${fmt(r.impressions, "int")}</td>
        <td>${fmt(r.clicks, "int")}</td><td>${fmt(r.ctr, "pct")}</td>
        <td>${fmt(r.conversions, "int")}</td><td>${fmt(r.cpa, "currency")}</td>${extraCells}</tr>`;
    }).join("");
    wrap.innerHTML = `<table><thead><tr><th title="${T("Verde = em veiculação · Vermelho = inativo")}">●</th>
      <th>${T("Plataforma")}</th><th>${T("Campanha")}</th><th>${T("Conjunto / Grupo")}</th><th>${T("Objetivo")}</th>
      <th>${T("Invest.")}</th><th>${T("Impr.")}</th><th>${T("Cliques")}</th><th>CTR</th><th>${T("Conv.")}</th><th>CPA</th>${extraHead}</tr></thead>
      <tbody>${body}</tbody></table>`;
  }

  // ---- Anúncios veiculados (Meta) ----
  let _adsData = [];
  function renderAds(rows) {
    _adsData = rows || [];
    const camps = [...new Set(_adsData.map((r) => r.campanha))].sort((a, b) => a.localeCompare(b, "pt"));
    fillSelectPreserve($("f-ads-camp"), camps);
    syncAdsConj();
    drawAds();
  }
  // O filtro por Conjunto só é clicável após escolher uma Campanha, e lista os conjuntos
  // daquela campanha.
  function syncAdsConj() {
    const selC = $("f-ads-camp"), selS = $("f-ads-conj");
    if (!selC.value) {
      selS.value = ""; selS.disabled = true;
      selS.innerHTML = `<option value="">${esc(selS.dataset.all || "Todos")}</option>`;
      return;
    }
    selS.disabled = false;
    const conj = [...new Set(_adsData.filter((r) => r.campanha === selC.value)
      .map((r) => r.conjunto).filter((c) => c))].sort((a, b) => a.localeCompare(b, "pt"));
    fillSelectPreserve(selS, conj);
  }
  function drawAds() {
    const wrap = $("ads-wrap");
    const camp = $("f-ads-camp").value, conj = $("f-ads-conj").value;
    let rows = _adsData;
    if (camp) rows = rows.filter((r) => r.campanha === camp);
    if (camp && conj) rows = rows.filter((r) => r.conjunto === conj);
    if (!rows.length) {
      wrap.innerHTML = `<div class="empty">${T("Sem anúncios veiculados no período")}${camp ? T(" para este filtro") : ""}.</div>`;
      return;
    }
    const extra = extraCols(rows);
    const extraHead = extra.map((c) => `<th>${c.label}</th>`).join("");
    const body = rows.map((r) => {
      const extraCells = extra.map((c) => `<td>${fmt(r[c.key], c.fmt)}</td>`).join("");
      const dot = `<span class="status-dot ${r.ativo ? "on" : "off"}" title="${r.ativo ? T("Em veiculação") : T("Não ativo no momento")}"></span>`;
      return `<tr>
        <td class="status-cell">${dot}</td>
        <td><span class="plat ${r.plataforma.toLowerCase()}">${r.plataforma}</span></td>
        <td>${r.anuncio}</td><td>${r.campanha}</td><td>${esc(r.conjunto || "—")}</td><td>${r.objetivo}</td>
        <td>${fmt(r.spend, "currency")}</td><td>${fmt(r.impressions, "int")}</td>
        <td>${fmt(r.clicks, "int")}</td><td>${fmt(r.ctr, "pct")}</td>
        <td>${fmt(r.conversions, "int")}</td><td>${fmt(r.cpa, "currency")}</td>${extraCells}</tr>`;
    }).join("");
    wrap.innerHTML = `<table><thead><tr><th title="${T("Verde = em veiculação · Vermelho = inativo")}">●</th>
      <th>${T("Plataforma")}</th><th>${T("Anúncio")}</th><th>${T("Campanha")}</th><th>${T("Conjunto")}</th><th>${T("Objetivo")}</th>
      <th>${T("Invest.")}</th><th>${T("Impr.")}</th><th>${T("Cliques")}</th><th>CTR</th><th>${T("Conv.")}</th><th>CPA</th>${extraHead}</tr></thead>
      <tbody>${body}</tbody></table>`;
  }

  // ---- Palavras-chave ----
  function renderKeywords(kws) {
    const wrap = $("keywords-wrap");
    // Sem palavras-chave (ex.: cliente só de Meta): some o card inteiro e o "Meta x
    // Google" ao lado passa a ocupar a linha toda, sem deixar vão no layout.
    const tem = !!(kws && kws.length);
    $("keywords-section").classList.toggle("hidden", !tem);
    $("kw-platform-row").classList.toggle("one-col", !tem);
    if (!tem) { wrap.innerHTML = ""; return; }
    const rows = kws.map((k) => `<tr>
      <td>${k.keyword}</td><td>${fmt(k.clicks, "int")}</td><td>${fmt(k.ctr, "pct")}</td>
      <td>${fmt(k.cpc, "currency")}</td><td>${fmt(k.conversions, "int")}</td>
      <td>${fmt(k.cpa, "currency")}</td><td>${fmt(k.roas, "ratio")}</td></tr>`).join("");
    wrap.innerHTML = `<table><thead><tr><th>${T("Palavra-chave")}</th><th>${T("Cliques")}</th><th>CTR</th>
      <th>CPC</th><th>${T("Conv.")}</th><th>CPA</th><th>ROAS</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  // ---- Comparativo de plataforma ----
  function renderPlatform(cp) {
    if (!cp) return;
    const m = cp.meta, g = cp.google, t = cp.tiktok;  // t presente só quando há TikTok
    const th = `<th>Meta</th><th>Google</th>${t ? "<th>TikTok</th>" : ""}`;
    const cells = (key, kind) => `<td>${fmt(m[key], kind)}</td><td>${fmt(g[key], kind)}</td>` +
      (t ? `<td>${fmt(t[key], kind)}</td>` : "");
    $("platform-table").innerHTML = `<table>
      <thead><tr><th>${T("Métrica")}</th>${th}</tr></thead><tbody>
        <tr><td>${T("Investimento")}</td>${cells("spend", "currency")}</tr>
        <tr><td>${T("Cliques")}</td>${cells("clicks", "int")}</tr>
        <tr><td>${T("Conversões")}</td>${cells("conversions", "int")}</tr>
        <tr><td>CPC</td>${cells("cpc", "currency")}</tr>
      </tbody></table>`;
    const ctx = $("platform-chart");
    if (platformChart) platformChart.destroy();
    const datasets = [
      { label: "Meta", data: [m.spend, m.clicks, m.conversions], backgroundColor: "#5b8cff" },
      { label: "Google", data: [g.spend, g.clicks, g.conversions], backgroundColor: "#2ecc8f" },
    ];
    if (t) datasets.push({ label: "TikTok", data: [t.spend, t.clicks, t.conversions], backgroundColor: "#ff4d67" });
    platformChart = new Chart(ctx, {
      type: "bar",
      data: { labels: [T("Investimento"), T("Cliques"), T("Conversões")], datasets },
      options: baseOpts({ stacked: false }),
    });
  }

  // ---- Comparativo de periodo ----
  function renderPeriod(per) {
    const rows = (per || []).map((r) => {
      const cls = r.delta_pct === null ? "" : r.good ? "delta-up" : "delta-down";
      const dtxt = r.delta_pct === null ? "—" :
        (r.delta_pct > 0 ? "▲" : r.delta_pct < 0 ? "▼" : "■") + " " +
        pctVar(r.delta_pct);
      return `<tr><td>${r.label}</td><td>${fmt(r.current, r.fmt)}</td>
        <td>${fmt(r.previous, r.fmt)}</td><td class="${cls}">${dtxt}</td></tr>`;
    }).join("");
    $("period-wrap").innerHTML = `<table><thead><tr><th>${T("Métrica")}</th><th>${T("Atual")}</th>
      <th>${T("Anterior")}</th><th>${T("Variação")}</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  // ---- Serie temporal ----
  function renderTrend(s) {
    const ctx = $("trend-chart");
    if (trendChart) trendChart.destroy();
    if (!s || !s.labels) return;
    const datasets = [
      { type: "bar", label: `${T("Investimento")} (${MOEDA.simbolo})`, data: s.spend, backgroundColor: "rgba(91,140,255,.45)", yAxisID: "y", order: 3 },
      { type: "line", label: T("Cliques"), data: s.clicks, borderColor: "#2ecc8f", backgroundColor: "#2ecc8f", tension: .3, yAxisID: "y1", order: 2, pointRadius: 2 },
    ];
    if (s.tem_conversoes) {
      datasets.push({ type: "line", label: T("Conversões"), data: s.conversions, borderColor: "#ffb547", backgroundColor: "#ffb547", tension: .3, yAxisID: "y1", order: 1, pointRadius: 2 });
    }
    trendChart = new Chart(ctx, {
      data: { labels: s.labels, datasets },
      options: {
        ...baseOpts({}),
        plugins: { legend: { labels: { color: "#e6eaf2" } } },
        scales: {
          x: { ticks: { color: "#93a0b8", maxRotation: 0, autoSkip: true }, grid: { color: "#222a3a" } },
          y: { position: "left", title: { display: true, text: `${T("Investimento")} (${MOEDA.simbolo})`, color: "#93a0b8" }, ticks: { color: "#93a0b8" }, grid: { color: "#222a3a" } },
          y1: { position: "right", title: { display: true, text: T("Cliques / Conversões"), color: "#93a0b8" }, ticks: { color: "#93a0b8" }, grid: { drawOnChartArea: false } },
        },
      },
    });
  }

  // ---- Seguidores do Instagram (orgânico) ----
  let igChart = null;
  function renderInstagram(data) {
    const sec = $("instagram-section");
    const ig = data.instagram;
    // Data-driven: some por completo se o cliente não tem conta de IG vinculada.
    if (!data.tem_instagram || !ig || !ig.contas || !ig.contas.length) {
      sec.classList.add("hidden");
      if (igChart) { igChart.destroy(); igChart = null; }
      return;
    }
    sec.classList.remove("hidden");

    const cresc = (ig.crescimento || 0);
    const sinal = cresc > 0 ? "▲" : cresc < 0 ? "▼" : "■";
    $("ig-kpis").innerHTML = `
      <div class="invest-card iv-ig">
        <div class="iv-label">Seguidores (total)</div>
        <div class="iv-value">${fmt(ig.total, "int")}</div>
        <div class="iv-prev">Somando ${ig.contas.length} conta${ig.contas.length > 1 ? "s" : ""}</div>
      </div>
      <div class="invest-card iv-ig">
        <div class="iv-label">Novos no período</div>
        <div class="iv-value">${cresc >= 0 ? "+" : ""}${fmt(ig.novos, "int")}</div>
        <div class="iv-prev">Seguidores ganhos no período filtrado</div>
      </div>
      <div class="invest-card iv-ig">
        <div class="iv-label">Crescimento</div>
        <div class="iv-value">${sinal} ${Math.abs(cresc).toFixed(2).replace(".", ",")}%</div>
        <div class="iv-prev">Sobre a base no início do período</div>
      </div>`;

    // série diária de novos seguidores
    const s = ig.serie || { labels: [], novos: [] };
    if (igChart) igChart.destroy();
    igChart = new Chart($("chart-ig"), {
      data: {
        labels: s.labels,
        datasets: [{
          type: "bar", label: T("Novos seguidores/dia"), data: s.novos,
          backgroundColor: "rgba(225,48,108,.55)", borderColor: "#e1306c", borderWidth: 1,
        }],
      },
      options: {
        ...baseOpts({}),
        plugins: { legend: { labels: { color: "#e6eaf2" } } },
        scales: {
          x: { ticks: { color: "#93a0b8", maxRotation: 0, autoSkip: true }, grid: { color: "#222a3a" } },
          y: { ticks: { color: "#93a0b8" }, grid: { color: "#222a3a" } },
        },
      },
    });

    // tabela por conta (só faz sentido quando há mais de uma)
    if (ig.contas.length > 1) {
      const linhas = ig.contas.map((c) => `<tr>
        <td>@${esc(c.username)}</td><td>${esc(c.conta)}</td>
        <td>${fmt(c.total, "int")}</td><td>${c.novos >= 0 ? "+" : ""}${fmt(c.novos, "int")}</td>
        <td>${(c.crescimento || 0).toFixed(2).replace(".", ",")}%</td></tr>`).join("");
      $("ig-wrap").innerHTML = `<table><thead><tr><th>${T("Conta")}</th><th>${T("Página")}</th>
        <th>${T("Seguidores")}</th><th>${T("Novos")}</th><th>${T("Crescimento")}</th></tr></thead><tbody>${linhas}</tbody></table>`;
    } else {
      $("ig-wrap").innerHTML = "";
    }
  }

  // ---- Mapa geografico por ESTADOS (Meta + Google somados): bolhas proporcionais.
  // Tamanho E cor escalam com o volume de cliques (degradê: pouco = pequeno/claro;
  // muito = grande/verde forte). Determinístico e legível sem zoom.
  function renderGeo(geo) {
    const sec = $("geo-section");
    const pts = (geo && geo.points) || [];
    const estados = (geo && geo.cidades) || [];
    if (!pts.length) { sec.classList.add("hidden"); return; }
    sec.classList.remove("hidden");
    if (!geoMap) {
      geoMap = L.map("geo-map", { scrollWheelZoom: false }).setView([-15.6, -47.8], 4);
      L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        { maxZoom: 18, crossOrigin: true, attribution: "© OpenStreetMap · © CARTO" }).addTo(geoMap);
    }
    // A seção acabou de sair de "hidden": sem isto o Leaflet mede o container com 0px
    // e o enquadramento abaixo sai errado.
    geoMap.invalidateSize();
    if (geoMarkers) geoMap.removeLayer(geoMarkers);
    const mx = geo.max || 1;
    geoMarkers = L.layerGroup();
    // do maior p/ o menor -> bolhas pequenas ficam por cima e visíveis.
    [...pts].sort((a, b) => b[2] - a[2]).forEach((p) => {
      const s = Math.sqrt(Math.min(p[2] / mx, 1));      // 0..1 (escala suave)
      const radius = 6 + 34 * s;                          // tamanho ∝ volume
      const color = `hsl(128, ${50 + 45 * s}%, ${80 - 47 * s}%)`;  // claro -> verde forte
      L.circleMarker([p[0], p[1]], {
        radius, fillColor: color, color: "#0a4d18", weight: 0.6,
        opacity: 0.55, fillOpacity: 0.78,
      }).bindTooltip(fmt(p[2], "int") + " cliques", { direction: "top" }).addTo(geoMarkers);
    });
    geoMarkers.addTo(geoMap);
    // Enquadra os estados com veiculação. maxZoom é obrigatório: com um estado só
    // (ou dois vizinhos) o fitBounds ia ao zoom 18 (nível de rua) e o mapa virava um
    // tile cinza com uma bolha gigante — era o "mapa quebrado" dos clientes regionais.
    const fit = () => {
      try {
        geoMap.invalidateSize();
        geoMap.fitBounds(L.latLngBounds(pts.map((p) => [p[0], p[1]])).pad(0.3),
          { maxZoom: 6, padding: [16, 16] });
      } catch (e) {}
    };
    fit();
    setTimeout(fit, 250);
    $("geo-top").innerHTML = estados.map((c) =>
      `<span class="geo-chip">${c.city}: <b>${fmt(c.clicks, "int")}</b></span>`).join("");
  }

  // ---- Tabela de cliques por CIDADE (abaixo do mapa; só clientes com dados de cidade) ----
  function renderGeoCities(geo) {
    const wrap = $("geo-cities");
    if (!wrap) return;
    const cidades = (geo && geo.cidades) || [];
    if (!cidades.length) { wrap.classList.add("hidden"); wrap.innerHTML = ""; return; }
    wrap.classList.remove("hidden");
    const body = cidades.map((c, i) => `<tr>
      <td>${i + 1}</td><td>${c.city}</td><td>${fmt(c.clicks, "int")}</td></tr>`).join("");
    wrap.innerHTML = `<h3 class="geo-cities-title">Cliques por cidade (Google)</h3>
      <div class="table-wrap"><table><thead><tr><th>#</th><th>${T("Cidade")}</th>
      <th>${T("Cliques")}</th></tr></thead><tbody>${body}</tbody></table></div>`;
  }

  function baseOpts({ stacked }) {
    return {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { labels: { color: "#e6eaf2" } } },
      scales: {
        x: { stacked: !!stacked, ticks: { color: "#93a0b8" }, grid: { color: "#222a3a" } },
        y: { stacked: !!stacked, ticks: { color: "#93a0b8" }, grid: { color: "#222a3a" } },
      },
    };
  }

  ["f-account", "f-platform"].forEach((id) => $(id).addEventListener("change", load));
  // Período: "Personalizado" revela os campos de data; meses/dias carregam direto.
  $("f-days").addEventListener("change", () => {
    const custom = $("f-days").value === "custom";
    $("f-range-wrap").classList.toggle("hidden", !custom);
    if (!custom) load();
    else if ($("f-start").value && $("f-end").value) load();
  });
  $("f-start").addEventListener("change", () => { if ($("f-end").value) load(); });
  $("f-end").addEventListener("change", () => { if ($("f-start").value) load(); });
  // Filtros das tabelas (client-side; não recarregam dados, só re-filtram o já carregado).
  $("f-adset-camp").addEventListener("change", drawAdSets);
  $("f-ads-camp").addEventListener("change", () => { syncAdsConj(); drawAds(); });
  $("f-ads-conj").addEventListener("change", drawAds);
  // Admin troca de cliente: zera a conta selecionada e força repopular as contas.
  $("f-client").addEventListener("change", () => {
    $("f-account").value = "todas"; accountsSig = null; load();
  });
  $("f-refresh").addEventListener("click", async () => {
    $("loading").classList.remove("hidden");
    try { await fetch("/api/refresh", { method: "POST" }); } catch (e) { console.error(e); }
    await load();
  });

  // ---- Sair (logout do HTTP Basic Auth) ----
  // Um XHR com credenciais propositalmente inválidas faz o navegador descartar o
  // login salvo; ao recarregar, ele volta a pedir usuário/senha (entrar como outro cliente).
  $("f-logout") && $("f-logout").addEventListener("click", () => {
    if (!confirm("Sair do dashboard e entrar com outro acesso?")) return;
    const done = () => window.location.replace("/");
    try {
      const xhr = new XMLHttpRequest();
      xhr.open("GET", "/logout", true, "sair", "sair-" + Date.now());
      xhr.onreadystatechange = () => { if (xhr.readyState === 4) done(); };
      xhr.onerror = done;
      xhr.send();
    } catch (e) { done(); }
  });

  // ---- Exportar em PDF (impressão nativa) ----
  // Usa window.print() + CSS @media print (papel carta, sem margens, fundo
  // ativado). Não rasteriza a tela (texto vetorial, sem cortes) e NÃO gera
  // nenhuma carga no servidor. Os gráficos (Chart.js/Leaflet) são
  // redimensionados p/ a largura da folha no evento beforeprint.
  const resizeCharts = () => {
    try { if (trendChart) trendChart.resize(); } catch (e) {}
    try { if (platformChart) platformChart.resize(); } catch (e) {}
    try { if (igChart) igChart.resize(); } catch (e) {}
    try { if (geoMap) geoMap.invalidateSize(); } catch (e) {}
  };
  window.addEventListener("beforeprint", resizeCharts);
  window.addEventListener("afterprint", resizeCharts);
  $("f-pdf").addEventListener("click", () => { resizeCharts(); window.print(); });

  load();
})();
