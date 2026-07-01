// Dashboard de Ads — front-end
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  let trendChart = null, platformChart = null, clientLoaded = false, accountsSig = null;
  let geoMap = null, geoMarkers = null, monthsLoaded = false;
  const MESES =["janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"];

  const nf = new Intl.NumberFormat("pt-BR");
  const cf = new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" });

  function fmt(value, kind) {
    if (value === null || value === undefined) return "—";
    switch (kind) {
      case "currency": return cf.format(value);
      case "int": return nf.format(Math.round(value));
      case "pct": return (value * 100).toFixed(2).replace(".", ",") + "%";
      case "ratio": return value.toFixed(2).replace(".", ",") + "x";
      case "dec": return value.toFixed(2).replace(".", ",");
      default: return String(value);
    }
  }

  function deltaHtml(delta, good) {
    if (delta === null || delta === undefined)
      return `<span class="k-delta neutral">—</span>`;
    const cls = good === true ? "good" : good === false ? "bad" : "neutral";
    const arrow = delta > 0 ? "▲" : delta < 0 ? "▼" : "■";
    return `<span class="k-delta ${cls}">${arrow} ${Math.abs(delta).toFixed(1).replace(".", ",")}%</span>`;
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
      $("comments").innerHTML = `<div class="comment alerta">Erro ao carregar dados.</div>`;
    } finally {
      $("loading").classList.add("hidden");
    }
  }

  function render(data) {
    // Seletor "Ver como" (somente admin/agência): popula uma vez e revela.
    if (data.clientes_admin && !clientLoaded) {
      const cs = $("f-client");
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
        sel.innerHTML = `<option value="todas">Todas as contas</option>`;
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
      $("cliente-sub").textContent = "Vendo como: " + reportClient;
    } else if (mi.cliente) {
      reportClient = mi.cliente;
      $("cliente-sub").textContent = mi.cliente;
    }
    if ($("report-client")) $("report-client").textContent = reportClient;
    $("src-info").textContent = "Fonte: " + (mi.fonte || "—") +
      (mi.atualizado_em ? " · atualizado " + new Date(mi.atualizado_em).toLocaleString("pt-BR") : "");

    if (data.vazio) {
      $("period-info").textContent = "";
      $("funnel").innerHTML = "";
      if (data.carregando) {
        $("comments").innerHTML = `<div class="comment info">⏳ Carregando os dados pela primeira vez (pode levar 1–2 min). Atualize a página em instantes.</div>`;
        setTimeout(load, 15000);  // re-tenta sozinho enquanto carrega
      } else {
        $("comments").innerHTML = `<div class="comment info">Sem dados no período selecionado.</div>`;
      }
      $("objective-blocks").innerHTML = "";
      $("best-ads").innerHTML = `<div class="empty">${data.carregando ? "Carregando…" : "Sem anúncios."}</div>`;
      $("keywords-wrap").innerHTML = ""; $("campaigns-wrap").innerHTML = "";
      $("ads-wrap").innerHTML = "";
      $("geo-section").classList.add("hidden");
      $("tiktok-section").classList.add("hidden");
      return;
    }

    const p = data.periodo;
    $("period-info").textContent =
      `Período: ${p.inicio} a ${p.fim} (anterior: ${p.anterior_inicio} a ${p.anterior_fim})`;
    if ($("report-period")) $("report-period").textContent = `Período: ${p.inicio} a ${p.fim}`;

    populateMonths(p.fim);

    renderFunnel(data.funil);
    renderComments(data.comentarios);
    renderInvestimento(data.investimento);
    renderObjectiveBlocks(data.blocos_objetivo);
    renderTrend(data.serie_temporal);
    renderBestAds(data.melhores_anuncios);
    renderAds(data.anuncios);
    // TikTok: opção no seletor de plataforma + seção dedicada (data-driven: só p/ clientes
    // com TikTok). ensurePlatformOption insere/remove a opção conforme tem_tiktok.
    ensurePlatformOption(!!data.tem_tiktok);
    const plat = (data.filtros || {}).platform;
    // Melhores anúncios (Meta) e Anúncios veiculados: ocultar em "Somente Google".
    // Em "Somente TikTok" os melhores do Meta somem; a tabela de anúncios mostra TikTok.
    $("best-ads-section").classList.toggle("hidden", plat === "google" || plat === "tiktok");
    $("ads-table-section").classList.toggle("hidden", plat === "google");
    renderTikTok(data, plat);
    renderCampaigns(data.campanhas);
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
      o.textContent = `${MESES[mm - 1]} de ${yy}`;
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
      html += `<div class="fn-stage" style="width:${w}%">
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
        ? `<span class="iv-delta">— vs. período anterior</span>`
        : `<span class="iv-delta">${d.delta_pct > 0 ? "▲" : d.delta_pct < 0 ? "▼" : "■"} ${Math.abs(d.delta_pct).toFixed(1).replace(".", ",")}% vs. anterior</span>`;
      return `<div class="invest-card ${cls}">
        <div class="iv-label">${label}</div>
        <div class="iv-value">${fmt(d.atual, "currency")}</div>
        ${dt}
        <div class="iv-prev">Anterior: ${fmt(d.anterior, "currency")}</div>
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
        const thumb = link && img ? `<a href="${link}" target="_blank" rel="noopener" title="Abrir anúncio">${img}</a>` : img;
        const verLink = link ? `<a class="ad-link" href="${link}" target="_blank" rel="noopener">Ver anúncio ↗</a>` : "";
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
      : `<div class="empty">Sem anúncios TikTok com investimento relevante no período.</div>`;
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
    if (!ads || !ads.length) { wrap.innerHTML = `<div class="empty">Sem anúncios com investimento relevante.</div>`; return; }
    wrap.innerHTML = ads.map((a, i) => {
      const link = a.permalink || "";
      const img = `<img class="thumb" src="${a.thumbnail}" alt="Print do anuncio" loading="lazy" onerror="this.style.display='none'">`;
      const thumb = link ? `<a href="${link}" target="_blank" rel="noopener" title="Abrir anúncio">${img}</a>` : img;
      const verLink = link ? `<a class="ad-link" href="${link}" target="_blank" rel="noopener">Ver anúncio ↗</a>` : "";
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
    if (!rows || !rows.length) { wrap.innerHTML = `<div class="empty">Sem campanhas no período.</div>`; return; }
    // Colunas extras (views de video, visitas ao Instagram, engajamento) so aparecem
    // se houver valor > 0 em alguma campanha — respeita a regra de ocultar zerados.
    const extra = [
      { key: "video_views", label: "Views vídeo", fmt: "int" },
      { key: "profile_visits", label: "Visitas IG", fmt: "int" },
      { key: "engagement", label: "Engaj.", fmt: "int" },
    ].filter((c) => rows.some((r) => (r[c.key] || 0) > 0));
    const extraHead = extra.map((c) => `<th>${c.label}</th>`).join("");
    const body = rows.map((r) => {
      const extraCells = extra.map((c) => `<td>${fmt(r[c.key], c.fmt)}</td>`).join("");
      const dot = `<span class="status-dot ${r.ativo ? "on" : "off"}" title="${r.ativo ? "Em veiculação" : "Não ativa no momento"}"></span>`;
      const orc = r.orcamento_diario ? fmt(r.orcamento_diario, "currency") : "—";
      return `<tr>
        <td class="status-cell">${dot}</td>
        <td><span class="plat ${r.plataforma.toLowerCase()}">${r.plataforma}</span></td>
        <td>${r.campanha}</td><td>${r.objetivo}</td>
        <td>${orc}</td><td>${fmt(r.spend, "currency")}</td><td>${fmt(r.impressions, "int")}</td>
        <td>${fmt(r.clicks, "int")}</td><td>${fmt(r.ctr, "pct")}</td>
        <td>${fmt(r.conversions, "int")}</td><td>${fmt(r.cpa, "currency")}</td>${extraCells}</tr>`;
    }).join("");
    wrap.innerHTML = `<table><thead><tr><th title="Verde = em veiculação · Vermelho = inativa">●</th>
      <th>Plataforma</th><th>Campanha</th><th>Objetivo</th>
      <th title="Orçamento diário">Orç./dia</th><th>Invest.</th><th>Impr.</th><th>Cliques</th><th>CTR</th><th>Conv.</th><th>CPA</th>${extraHead}</tr></thead>
      <tbody>${body}</tbody></table>`;
  }

  // ---- Anúncios veiculados (Meta) ----
  function renderAds(rows) {
    const wrap = $("ads-wrap");
    if (!rows || !rows.length) { wrap.innerHTML = `<div class="empty">Sem anúncios veiculados no período.</div>`; return; }
    const extra = [
      { key: "video_views", label: "Views vídeo", fmt: "int" },
      { key: "profile_visits", label: "Visitas IG", fmt: "int" },
      { key: "engagement", label: "Engaj.", fmt: "int" },
    ].filter((c) => rows.some((r) => (r[c.key] || 0) > 0));
    const extraHead = extra.map((c) => `<th>${c.label}</th>`).join("");
    const body = rows.map((r) => {
      const extraCells = extra.map((c) => `<td>${fmt(r[c.key], c.fmt)}</td>`).join("");
      const dot = `<span class="status-dot ${r.ativo ? "on" : "off"}" title="${r.ativo ? "Em veiculação" : "Não ativo no momento"}"></span>`;
      return `<tr>
        <td class="status-cell">${dot}</td>
        <td><span class="plat ${r.plataforma.toLowerCase()}">${r.plataforma}</span></td>
        <td>${r.anuncio}</td><td>${r.campanha}</td><td>${r.objetivo}</td>
        <td>${fmt(r.spend, "currency")}</td><td>${fmt(r.impressions, "int")}</td>
        <td>${fmt(r.clicks, "int")}</td><td>${fmt(r.ctr, "pct")}</td>
        <td>${fmt(r.conversions, "int")}</td><td>${fmt(r.cpa, "currency")}</td>${extraCells}</tr>`;
    }).join("");
    wrap.innerHTML = `<table><thead><tr><th title="Verde = em veiculação · Vermelho = inativo">●</th>
      <th>Plataforma</th><th>Anúncio</th><th>Campanha</th><th>Objetivo</th>
      <th>Invest.</th><th>Impr.</th><th>Cliques</th><th>CTR</th><th>Conv.</th><th>CPA</th>${extraHead}</tr></thead>
      <tbody>${body}</tbody></table>`;
  }

  // ---- Palavras-chave ----
  function renderKeywords(kws) {
    const wrap = $("keywords-wrap");
    if (!kws || !kws.length) { wrap.innerHTML = `<div class="empty">Sem dados de Google Ads no filtro atual.</div>`; return; }
    const rows = kws.map((k) => `<tr>
      <td>${k.keyword}</td><td>${fmt(k.clicks, "int")}</td><td>${fmt(k.ctr, "pct")}</td>
      <td>${fmt(k.cpc, "currency")}</td><td>${fmt(k.conversions, "int")}</td>
      <td>${fmt(k.cpa, "currency")}</td><td>${fmt(k.roas, "ratio")}</td></tr>`).join("");
    wrap.innerHTML = `<table><thead><tr><th>Palavra-chave</th><th>Cliques</th><th>CTR</th>
      <th>CPC</th><th>Conv.</th><th>CPA</th><th>ROAS</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  // ---- Comparativo de plataforma ----
  function renderPlatform(cp) {
    if (!cp) return;
    const m = cp.meta, g = cp.google, t = cp.tiktok;  // t presente só quando há TikTok
    const th = `<th>Meta</th><th>Google</th>${t ? "<th>TikTok</th>" : ""}`;
    const cells = (key, kind) => `<td>${fmt(m[key], kind)}</td><td>${fmt(g[key], kind)}</td>` +
      (t ? `<td>${fmt(t[key], kind)}</td>` : "");
    $("platform-table").innerHTML = `<table>
      <thead><tr><th>Métrica</th>${th}</tr></thead><tbody>
        <tr><td>Investimento</td>${cells("spend", "currency")}</tr>
        <tr><td>Cliques</td>${cells("clicks", "int")}</tr>
        <tr><td>Conversões</td>${cells("conversions", "int")}</tr>
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
      data: { labels: ["Investimento", "Cliques", "Conversões"], datasets },
      options: baseOpts({ stacked: false }),
    });
  }

  // ---- Comparativo de periodo ----
  function renderPeriod(per) {
    const rows = (per || []).map((r) => {
      const cls = r.delta_pct === null ? "" : r.good ? "delta-up" : "delta-down";
      const dtxt = r.delta_pct === null ? "—" :
        (r.delta_pct > 0 ? "▲" : r.delta_pct < 0 ? "▼" : "■") + " " +
        Math.abs(r.delta_pct).toFixed(1).replace(".", ",") + "%";
      return `<tr><td>${r.label}</td><td>${fmt(r.current, r.fmt)}</td>
        <td>${fmt(r.previous, r.fmt)}</td><td class="${cls}">${dtxt}</td></tr>`;
    }).join("");
    $("period-wrap").innerHTML = `<table><thead><tr><th>Métrica</th><th>Atual</th>
      <th>Anterior</th><th>Variação</th></tr></thead><tbody>${rows}</tbody></table>`;
  }

  // ---- Serie temporal ----
  function renderTrend(s) {
    const ctx = $("trend-chart");
    if (trendChart) trendChart.destroy();
    if (!s || !s.labels) return;
    const datasets = [
      { type: "bar", label: "Investimento (R$)", data: s.spend, backgroundColor: "rgba(91,140,255,.45)", yAxisID: "y", order: 3 },
      { type: "line", label: "Cliques", data: s.clicks, borderColor: "#2ecc8f", backgroundColor: "#2ecc8f", tension: .3, yAxisID: "y1", order: 2, pointRadius: 2 },
    ];
    if (s.tem_conversoes) {
      datasets.push({ type: "line", label: "Conversões", data: s.conversions, borderColor: "#ffb547", backgroundColor: "#ffb547", tension: .3, yAxisID: "y1", order: 1, pointRadius: 2 });
    }
    trendChart = new Chart(ctx, {
      data: { labels: s.labels, datasets },
      options: {
        ...baseOpts({}),
        plugins: { legend: { labels: { color: "#e6eaf2" } } },
        scales: {
          x: { ticks: { color: "#93a0b8", maxRotation: 0, autoSkip: true }, grid: { color: "#222a3a" } },
          y: { position: "left", title: { display: true, text: "Investimento (R$)", color: "#93a0b8" }, ticks: { color: "#93a0b8" }, grid: { color: "#222a3a" } },
          y1: { position: "right", title: { display: true, text: "Cliques / Conversões", color: "#93a0b8" }, ticks: { color: "#93a0b8" }, grid: { drawOnChartArea: false } },
        },
      },
    });
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
    try { geoMap.fitBounds(L.latLngBounds(pts.map((p) => [p[0], p[1]])).pad(0.3)); } catch (e) {}
    setTimeout(() => geoMap.invalidateSize(), 250);
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
      <div class="table-wrap"><table><thead><tr><th>#</th><th>Cidade</th>
      <th>Cliques</th></tr></thead><tbody>${body}</tbody></table></div>`;
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
    try { if (geoMap) geoMap.invalidateSize(); } catch (e) {}
  };
  window.addEventListener("beforeprint", resizeCharts);
  window.addEventListener("afterprint", resizeCharts);
  $("f-pdf").addEventListener("click", () => { resizeCharts(); window.print(); });

  load();
})();
