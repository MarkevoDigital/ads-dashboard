// Dashboard de Ads — front-end
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  let trendChart = null, platformChart = null, accountsLoaded = false;
  let geoMap = null, heatLayer = null;

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
      account: $("f-account").value, platform: $("f-platform").value, days: $("f-days").value,
    });
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
    if (!accountsLoaded && data.contas) {
      const sel = $("f-account");
      data.contas.forEach((c) => {
        const o = document.createElement("option"); o.value = c; o.textContent = c; sel.appendChild(o);
      });
      accountsLoaded = true;
    }
    const mi = data.meta_info || {};
    if (mi.cliente) $("cliente-sub").textContent = mi.cliente;
    $("src-info").textContent = "Fonte: " + (mi.fonte || "—") +
      (mi.atualizado_em ? " · atualizado " + new Date(mi.atualizado_em).toLocaleString("pt-BR") : "");

    if (data.vazio) {
      $("period-info").textContent = "";
      $("funnel").innerHTML = "";
      if (data.carregando) {
        $("comments").innerHTML = `<div class="comment info">⏳ Carregando os dados pela primeira vez (pode levar 1–2 min). Atualize a página em instantes.</div>`;
        setTimeout(load, 15000);  // re-tenta sozinho enquanto carrega
      } else {
        $("comments").innerHTML = `<div class="comment info">Sem dados no periodo selecionado.</div>`;
      }
      $("objective-blocks").innerHTML = "";
      $("best-ads").innerHTML = `<div class="empty">${data.carregando ? "Carregando…" : "Sem anuncios."}</div>`;
      $("keywords-wrap").innerHTML = ""; $("campaigns-wrap").innerHTML = "";
      $("geo-section").classList.add("hidden");
      return;
    }

    const p = data.periodo;
    $("period-info").textContent =
      `Periodo: ${p.inicio} a ${p.fim} (anterior: ${p.anterior_inicio} a ${p.anterior_fim})`;

    renderFunnel(data.funil);
    renderComments(data.comentarios);
    renderObjectiveBlocks(data.blocos_objetivo);
    renderTrend(data.serie_temporal);
    renderBestAds(data.melhores_anuncios);
    renderCampaigns(data.campanhas);
    renderKeywords(data.palavras_chave);
    renderPlatform(data.comparativo_plataforma);
    renderPeriod(data.comparativo_periodo);
    renderGeo(data.geo);
  }

  // ---- Funil ----
  function renderFunnel(f) {
    const wrap = $("funnel");
    if (!f || !f.stages || !f.stages.length) { wrap.innerHTML = ""; return; }
    const maxV = Math.max(...f.stages.map((s) => s.value)) || 1;
    let html = "";
    f.stages.forEach((s, i) => {
      const w = Math.max((s.value / maxV) * 100, 26);
      html += `<div class="fn-stage" style="width:${w}%">
        <span class="fn-label">${s.label}</span>
        <span class="fn-value">${fmt(s.value, s.fmt)}</span></div>`;
      if (i < f.stages.length - 1 && f.rates && f.rates[i]) {
        html += `<div class="fn-rate">▼ ${f.rates[i].label}: <b>${fmt(f.rates[i].value, "pct")}</b></div>`;
      }
    });
    wrap.innerHTML = html;
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
    if (!ads || !ads.length) { wrap.innerHTML = `<div class="empty">Sem anuncios com investimento relevante.</div>`; return; }
    wrap.innerHTML = ads.map((a, i) => `
      <div class="ad-card" style="position:relative">
        <div class="rank-badge">${i + 1}</div>
        <img class="thumb" src="${a.thumbnail}" alt="Print do anuncio" loading="lazy" onerror="this.style.display='none'">
        <div class="ad-body">
          <div class="ad-name">${a.ad_name}</div>
          <div class="ad-tag">${a.account} · ${a.objective_label}</div>
          <div class="ad-metric">${fmt(a.metric_value, a.metric_fmt)}<small>${a.metric_label}</small></div>
          <div class="ad-sub">Invest.: ${fmt(a.spend, "currency")} · CTR ${fmt(a.ctr, "pct")} · ${fmt(a.impressions, "int")} impr.</div>
        </div></div>`).join("");
  }

  // ---- Campanhas por plataforma ----
  function renderCampaigns(rows) {
    const wrap = $("campaigns-wrap");
    if (!rows || !rows.length) { wrap.innerHTML = `<div class="empty">Sem campanhas no periodo.</div>`; return; }
    const body = rows.map((r) => `<tr>
      <td><span class="plat ${r.plataforma.toLowerCase()}">${r.plataforma}</span></td>
      <td>${r.campanha}</td><td>${r.objetivo}</td>
      <td>${fmt(r.spend, "currency")}</td><td>${fmt(r.impressions, "int")}</td>
      <td>${fmt(r.clicks, "int")}</td><td>${fmt(r.ctr, "pct")}</td>
      <td>${fmt(r.conversions, "int")}</td><td>${fmt(r.cpa, "currency")}</td></tr>`).join("");
    wrap.innerHTML = `<table><thead><tr><th>Plataforma</th><th>Campanha</th><th>Objetivo</th>
      <th>Invest.</th><th>Impr.</th><th>Cliques</th><th>CTR</th><th>Conv.</th><th>CPA</th></tr></thead>
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
    const m = cp.meta, g = cp.google;
    $("platform-table").innerHTML = `<table>
      <thead><tr><th>Metrica</th><th>Meta</th><th>Google</th></tr></thead><tbody>
        <tr><td>Investimento</td><td>${fmt(m.spend, "currency")}</td><td>${fmt(g.spend, "currency")}</td></tr>
        <tr><td>Cliques</td><td>${fmt(m.clicks, "int")}</td><td>${fmt(g.clicks, "int")}</td></tr>
        <tr><td>Conversoes</td><td>${fmt(m.conversions, "int")}</td><td>${fmt(g.conversions, "int")}</td></tr>
        <tr><td>CPC</td><td>${fmt(m.cpc, "currency")}</td><td>${fmt(g.cpc, "currency")}</td></tr>
      </tbody></table>`;
    const ctx = $("platform-chart");
    if (platformChart) platformChart.destroy();
    platformChart = new Chart(ctx, {
      type: "bar",
      data: {
        labels: ["Investimento", "Cliques", "Conversoes"],
        datasets: [
          { label: "Meta", data: [m.spend, m.clicks, m.conversions], backgroundColor: "#5b8cff" },
          { label: "Google", data: [g.spend, g.clicks, g.conversions], backgroundColor: "#2ecc8f" },
        ],
      },
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
    $("period-wrap").innerHTML = `<table><thead><tr><th>Metrica</th><th>Atual</th>
      <th>Anterior</th><th>Variacao</th></tr></thead><tbody>${rows}</tbody></table>`;
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

  // ---- Mapa de calor geografico ----
  function renderGeo(geo) {
    const sec = $("geo-section");
    if (!geo || !geo.points || !geo.points.length) { sec.classList.add("hidden"); return; }
    sec.classList.remove("hidden");
    if (!geoMap) {
      geoMap = L.map("geo-map", { scrollWheelZoom: false }).setView([-15.6, -47.8], 4);
      L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
        { maxZoom: 18, attribution: "© OpenStreetMap · © CARTO" }).addTo(geoMap);
    }
    if (heatLayer) geoMap.removeLayer(heatLayer);
    const mx = geo.max || 1;
    const pts = geo.points.map((p) => [p[0], p[1], Math.max(p[2] / mx, 0.15)]);
    heatLayer = L.heatLayer(pts, { radius: 32, blur: 22, maxZoom: 10 }).addTo(geoMap);
    try { geoMap.fitBounds(L.latLngBounds(geo.points.map((p) => [p[0], p[1]])).pad(0.3)); } catch (e) {}
    setTimeout(() => geoMap.invalidateSize(), 250);
    $("geo-top").innerHTML = (geo.cidades || []).map((c) =>
      `<span class="geo-chip">${c.city}: <b>${fmt(c.clicks, "int")}</b></span>`).join("");
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

  ["f-account", "f-platform", "f-days"].forEach((id) => $(id).addEventListener("change", load));
  $("f-refresh").addEventListener("click", async () => {
    $("loading").classList.remove("hidden");
    try { await fetch("/api/refresh", { method: "POST" }); } catch (e) { console.error(e); }
    await load();
  });

  load();
})();
