// Dashboard de Ads — front-end
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  let trendChart = null;
  let platformChart = null;
  let accountsLoaded = false;

  // --------------------------------------------------------------------------
  // Formatadores (pt-BR)
  // --------------------------------------------------------------------------
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

  // --------------------------------------------------------------------------
  // Carregamento
  // --------------------------------------------------------------------------
  async function load() {
    $("loading").classList.remove("hidden");
    const params = new URLSearchParams({
      account: $("f-account").value,
      platform: $("f-platform").value,
      days: $("f-days").value,
    });
    try {
      const res = await fetch("/api/data?" + params.toString());
      const data = await res.json();
      render(data);
    } catch (e) {
      console.error(e);
      $("comments").innerHTML = `<div class="comment alerta">Erro ao carregar dados.</div>`;
    } finally {
      $("loading").classList.add("hidden");
    }
  }

  // --------------------------------------------------------------------------
  // Render principal
  // --------------------------------------------------------------------------
  function render(data) {
    if (!accountsLoaded && data.contas) {
      const sel = $("f-account");
      data.contas.forEach((c) => {
        const o = document.createElement("option");
        o.value = c; o.textContent = c; sel.appendChild(o);
      });
      accountsLoaded = true;
    }

    const mi = data.meta_info || {};
    $("src-info").textContent = "Fonte: " + (mi.fonte || "—") +
      (mi.atualizado_em ? " · atualizado " + new Date(mi.atualizado_em).toLocaleString("pt-BR") : "");

    if (data.vazio) {
      $("period-info").textContent = "";
      $("comments").innerHTML = `<div class="comment info">Sem dados no periodo selecionado.</div>`;
      $("objective-blocks").innerHTML = "";
      $("best-ads").innerHTML = `<div class="empty">Sem anuncios.</div>`;
      $("keywords-wrap").innerHTML = `<div class="empty">Sem palavras-chave.</div>`;
      return;
    }

    const p = data.periodo;
    $("period-info").textContent =
      `Periodo: ${p.inicio} a ${p.fim} (anterior: ${p.anterior_inicio} a ${p.anterior_fim})`;

    renderComments(data.comentarios);
    renderObjectiveBlocks(data.blocos_objetivo);
    renderTrend(data.serie_temporal);
    renderBestAds(data.melhores_anuncios);
    renderKeywords(data.palavras_chave);
    renderPlatform(data.comparativo_plataforma);
    renderPeriod(data.comparativo_periodo);
  }

  // --------------------------------------------------------------------------
  // Comentarios
  // --------------------------------------------------------------------------
  function renderComments(comments) {
    const icons = { positivo: "✅", alerta: "⚠️", info: "💡" };
    $("comments").innerHTML = (comments || []).map((c) =>
      `<div class="comment ${c.tipo}"><span class="ic">${icons[c.tipo] || "•"}</span><span>${c.texto}</span></div>`
    ).join("") || `<div class="comment info">Sem comentarios.</div>`;
  }

  // --------------------------------------------------------------------------
  // Blocos por objetivo (KPIs adaptativos)
  // --------------------------------------------------------------------------
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
      return `
        <div class="card obj-block">
          <div class="obj-head">
            <h3>${b.label}</h3>
            <span class="obj-spend">Investimento: ${fmt(b.spend, "currency")}</span>
          </div>
          <div class="kpi-grid">${cards}</div>
        </div>`;
    }).join("");
  }

  // --------------------------------------------------------------------------
  // Melhores anuncios
  // --------------------------------------------------------------------------
  function renderBestAds(ads) {
    const wrap = $("best-ads");
    if (!ads || !ads.length) { wrap.innerHTML = `<div class="empty">Sem anuncios com investimento relevante.</div>`; return; }
    wrap.innerHTML = ads.map((a, i) => `
      <div class="ad-card" style="position:relative">
        <div class="rank-badge">${i + 1}</div>
        <img class="thumb" src="${a.thumbnail}" alt="Print do anuncio" loading="lazy"
             onerror="this.style.display='none'">
        <div class="ad-body">
          <div class="ad-name">${a.ad_name}</div>
          <div class="ad-tag">${a.account} · ${a.objective_label}</div>
          <div class="ad-metric">${fmt(a.metric_value, a.metric_fmt)}<small>${a.metric_label}</small></div>
          <div class="ad-sub">Invest.: ${fmt(a.spend, "currency")} · CTR ${fmt(a.ctr, "pct")} · ${fmt(a.impressions, "int")} impr.</div>
        </div>
      </div>`).join("");
  }

  // --------------------------------------------------------------------------
  // Palavras-chave
  // --------------------------------------------------------------------------
  function renderKeywords(kws) {
    const wrap = $("keywords-wrap");
    if (!kws || !kws.length) { wrap.innerHTML = `<div class="empty">Sem dados de Google Ads no filtro atual.</div>`; return; }
    const rows = kws.map((k) => `
      <tr>
        <td>${k.keyword}</td>
        <td>${fmt(k.clicks, "int")}</td>
        <td>${fmt(k.ctr, "pct")}</td>
        <td>${fmt(k.cpc, "currency")}</td>
        <td>${fmt(k.conversions, "int")}</td>
        <td>${fmt(k.cpa, "currency")}</td>
        <td>${fmt(k.roas, "ratio")}</td>
      </tr>`).join("");
    wrap.innerHTML = `<table>
      <thead><tr><th>Palavra-chave</th><th>Cliques</th><th>CTR</th><th>CPC</th><th>Conv.</th><th>CPA</th><th>ROAS</th></tr></thead>
      <tbody>${rows}</tbody></table>`;
  }

  // --------------------------------------------------------------------------
  // Comparativo de plataforma
  // --------------------------------------------------------------------------
  function renderPlatform(cp) {
    if (!cp) return;
    const m = cp.meta, g = cp.google;
    $("platform-table").innerHTML = `<table>
      <thead><tr><th>Metrica</th><th>Meta</th><th>Google</th></tr></thead>
      <tbody>
        <tr><td>Investimento</td><td>${fmt(m.spend, "currency")}</td><td>${fmt(g.spend, "currency")}</td></tr>
        <tr><td>Cliques</td><td>${fmt(m.clicks, "int")}</td><td>${fmt(g.clicks, "int")}</td></tr>
        <tr><td>Conversoes</td><td>${fmt(m.conversions, "int")}</td><td>${fmt(g.conversions, "int")}</td></tr>
        <tr><td>Receita</td><td>${fmt(m.revenue, "currency")}</td><td>${fmt(g.revenue, "currency")}</td></tr>
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

  // --------------------------------------------------------------------------
  // Comparativo de periodo
  // --------------------------------------------------------------------------
  function renderPeriod(per) {
    const rows = (per || []).map((r) => {
      const cls = r.delta_pct === null ? "" : r.good ? "delta-up" : "delta-down";
      const dtxt = r.delta_pct === null ? "—" :
        (r.delta_pct > 0 ? "▲" : r.delta_pct < 0 ? "▼" : "■") + " " +
        Math.abs(r.delta_pct).toFixed(1).replace(".", ",") + "%";
      return `<tr>
        <td>${r.label}</td>
        <td>${fmt(r.current, r.fmt)}</td>
        <td>${fmt(r.previous, r.fmt)}</td>
        <td class="${cls}">${dtxt}</td>
      </tr>`;
    }).join("");
    $("period-wrap").innerHTML = `<table>
      <thead><tr><th>Metrica</th><th>Atual</th><th>Anterior</th><th>Variacao</th></tr></thead>
      <tbody>${rows}</tbody></table>`;
  }

  // --------------------------------------------------------------------------
  // Serie temporal
  // --------------------------------------------------------------------------
  function renderTrend(s) {
    const ctx = $("trend-chart");
    if (trendChart) trendChart.destroy();
    if (!s || !s.labels) return;
    trendChart = new Chart(ctx, {
      data: {
        labels: s.labels,
        datasets: [
          {
            type: "bar", label: "Investimento (R$)", data: s.spend,
            backgroundColor: "rgba(91,140,255,.45)", yAxisID: "y", order: 2,
          },
          {
            type: "line", label: s.primary_label, data: s.primary,
            borderColor: "#2ecc8f", backgroundColor: "#2ecc8f",
            tension: .3, yAxisID: "y1", order: 1, pointRadius: 2,
          },
        ],
      },
      options: {
        ...baseOpts({}),
        scales: {
          x: { ticks: { color: "#93a0b8", maxRotation: 0, autoSkip: true }, grid: { color: "#222a3a" } },
          y: { position: "left", ticks: { color: "#93a0b8" }, grid: { color: "#222a3a" } },
          y1: { position: "right", ticks: { color: "#2ecc8f" }, grid: { drawOnChartArea: false } },
        },
      },
    });
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

  // --------------------------------------------------------------------------
  // Eventos
  // --------------------------------------------------------------------------
  ["f-account", "f-platform", "f-days"].forEach((id) =>
    $(id).addEventListener("change", load));

  $("f-refresh").addEventListener("click", async () => {
    $("loading").classList.remove("hidden");
    try { await fetch("/api/refresh", { method: "POST" }); } catch (e) { console.error(e); }
    await load();
  });

  load();
})();
