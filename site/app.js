"use strict";

const CLOSURE_DATE = "2026-03-04";
const SITE_NAME = "hormuz-traffic.com";

const RANGES = {
  all:     { min: null,         label: "2019 – present" },
  war:     { min: "2025-06-01", label: "Jun 2025 – present" },
  closure: { min: "2026-02-01", label: "Feb 2026 – present" },
  d30:     { dynamic: 30,       label: "Last 30 days" },
  d7:      { dynamic: 7,        label: "Last 7 days" },
  custom:  { custom: true,      label: "Custom range" },
};

/* Dispatch palette (mirrored from CSS tokens) */
const C = {
  paper:       "#ede4cb",
  paperDim:    "#c0b89e",
  paperFaint:  "#6f6a58",
  steel:       "#8a98b5",
  steelFaint:  "#5a6680",
  ink:         "#0a0f1c",
  inkDeep:     "#060912",
  inkRaised:   "#121a2c",
  inkEdge:     "#2a3548",
  alert:       "#c83232",
  caution:     "#d99a2b",
  cautionLine: "rgba(217, 154, 43, 1)",
  dataBlue:    "#5a8fc2",
  dataViolet:  "#8a6fb8",
  dataMute:    "#4a5670",
};

const FONT_MONO = "JetBrains Mono, IBM Plex Mono, Menlo, monospace";
const FONT_DISPLAY = "Bebas Neue, Oswald, sans-serif";

let customRangeMin = null;
let customRangeMax = null;
let dataLatestDate = null;

/* ============================================================
   EVENT MARKERS PLUGIN — strip below chart with staggered chips
   ============================================================ */
const eventMarkersPlugin = {
  id: "eventMarkers",
  afterDatasetsDraw(chart) {
    const cfg = chart.options.plugins.eventMarkers;
    if (!cfg || !cfg.events || !cfg.events.length) return;

    const { ctx, chartArea, scales } = chart;
    if (!chartArea) return;
    const xScale = scales.x;
    const minDate = cfg.minDate || null;
    const maxDate = cfg.maxDate || null;
    const highlightedIdx = cfg.highlightedIdx ?? -1;

    const tsFor = (d) => new Date(d + "T00:00:00Z").getTime();

    const positions = cfg.events
      .map((e, i) => ({ ...e, idx: i }))
      .filter((e) => (!minDate || e.date >= minDate) && (!maxDate || e.date <= maxDate))
      .map((e) => {
        const x = xScale.getPixelForValue(tsFor(e.date));
        return { ...e, x, dataX: x };
      })
      .filter((p) => Number.isFinite(p.x) && p.x >= chartArea.left - 4 && p.x <= chartArea.right + 4)
      .sort((a, b) => a.x - b.x);

    if (!positions.length) return;

    const RADIUS_MAJOR = 11;
    const RADIUS_MINOR = 8;
    positions.forEach((p) => {
      const r = (p.priority === "major" ? RADIUS_MAJOR : RADIUS_MINOR) + 2;
      if (p.x - r < chartArea.left) p.x = chartArea.left + r;
      if (p.x + r > chartArea.right) p.x = chartArea.right - r;
    });

    const MAX_ROWS = 2;
    const MARKER_GAP_PX = 28;
    const lastInRow = [];
    positions.forEach((p) => {
      let chosen = 0;
      for (let r = 0; r < MAX_ROWS; r++) {
        if (lastInRow[r] === undefined || p.x - lastInRow[r] >= MARKER_GAP_PX) {
          chosen = r;
          break;
        }
        chosen = r;
      }
      p.row = chosen;
      lastInRow[chosen] = p.x;
    });

    const ROW_HEIGHT = 24;
    const ROW_OFFSET = 22;

    // Connectors first (under markers)
    positions.forEach((p) => {
      const major = p.priority === "major";
      const isHi = p.idx === highlightedIdx;
      const radius = major ? RADIUS_MAJOR : RADIUS_MINOR;
      const yMarker = chartArea.bottom + ROW_OFFSET + p.row * ROW_HEIGHT;

      ctx.save();
      ctx.strokeStyle = isHi
        ? "rgba(217, 154, 43, 0.95)"
        : major
          ? "rgba(217, 154, 43, 0.55)"
          : "rgba(217, 154, 43, 0.32)";
      ctx.lineWidth = isHi ? 1.5 : 1;
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      ctx.moveTo(p.dataX, chartArea.bottom);
      ctx.lineTo(p.x, yMarker - radius);
      ctx.stroke();
      ctx.restore();
    });

    // Markers + numbers
    positions.forEach((p) => {
      const major = p.priority === "major";
      const isHi = p.idx === highlightedIdx;
      const radius = major ? RADIUS_MAJOR : RADIUS_MINOR;
      const yMarker = chartArea.bottom + ROW_OFFSET + p.row * ROW_HEIGHT;

      ctx.save();
      if (major) {
        ctx.fillStyle = isHi ? C.paper : "rgba(217, 154, 43, 0.95)";
        if (isHi) {
          ctx.shadowColor = "rgba(217, 154, 43, 0.8)";
          ctx.shadowBlur = 8;
        }
        ctx.beginPath();
        ctx.arc(p.x, yMarker, radius, 0, Math.PI * 2);
        ctx.fill();
      } else {
        ctx.fillStyle = C.ink;
        ctx.beginPath();
        ctx.arc(p.x, yMarker, radius, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = isHi ? C.paper : "rgba(217, 154, 43, 0.85)";
        ctx.lineWidth = isHi ? 2 : 1.5;
        ctx.beginPath();
        ctx.arc(p.x, yMarker, radius, 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.restore();

      ctx.save();
      ctx.fillStyle = major ? C.ink : (isHi ? C.paper : "rgba(217, 154, 43, 0.95)");
      ctx.font = `bold ${major ? 12 : 10}px ${FONT_MONO}`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(String(p.idx + 1), p.x, yMarker + 0.5);
      ctx.restore();
    });
  },
};
Chart.register(eventMarkersPlugin);

/* ============================================================
   FORMATTERS
   ============================================================ */
const fmt = {
  int: (n) => (n == null ? "—" : Math.round(n).toLocaleString()),
  num: (n) => (n == null ? "—" : Number(n).toLocaleString(undefined, { maximumFractionDigits: 1 })),
  pct: (n) => (n == null ? "—" : `${n > 0 ? "+" : ""}${n.toFixed(1)}%`),
  pctHero: (n) => (n == null ? "—" : `${n > 0 ? "+" : n < 0 ? "−" : ""}${Math.abs(n).toFixed(1)}%`),
  date: (s) => new Date(s + "T00:00:00Z").toLocaleDateString("en-US",
    { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }),
  dateShort: (s) => new Date(s + "T00:00:00Z").toLocaleDateString("en-US",
    { month: "short", day: "numeric", timeZone: "UTC" }),
  dateMonoShort: (s) => {
    const d = new Date(s + "T00:00:00Z");
    return d.toLocaleDateString("en-US", { month: "short", day: "2-digit", timeZone: "UTC" }).toUpperCase();
  },
  dateShortYr: (s) => {
    const d = new Date(s + "T00:00:00Z");
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })
      + " '" + String(d.getUTCFullYear()).slice(2);
  },
  dateMonoFull: (s) => {
    const d = new Date(s + "T00:00:00Z");
    return d.toLocaleDateString("en-US", { month: "short", day: "2-digit", year: "numeric", timeZone: "UTC" }).toUpperCase();
  },
};

const daysBetween = (a, b) =>
  Math.round((new Date(b + "T00:00:00Z") - new Date(a + "T00:00:00Z")) / 86400000);

async function loadJson(path) {
  const r = await fetch(path, { cache: "no-store" });
  if (!r.ok) throw new Error(`failed to load ${path}: ${r.status}`);
  return r.json();
}

/* ============================================================
   COUNT-UP ANIMATION (eased, percentage-aware)
   ============================================================ */
function animatePercent(el, target, durationMs = 1100) {
  if (target == null) { el.textContent = "—"; return; }
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    el.textContent = fmt.pctHero(target);
    return;
  }
  const start = performance.now();
  const ease = (t) => 1 - Math.pow(1 - t, 3); // easeOutCubic
  function frame(now) {
    const t = Math.min(1, (now - start) / durationMs);
    const v = target * ease(t);
    el.textContent = fmt.pctHero(v);
    if (t < 1) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

function animateInt(el, target, durationMs = 900, suffix = "") {
  if (target == null) { el.textContent = "—"; return; }
  if (window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
    el.textContent = fmt.int(target) + suffix;
    return;
  }
  const start = performance.now();
  const ease = (t) => 1 - Math.pow(1 - t, 3);
  function frame(now) {
    const t = Math.min(1, (now - start) / durationMs);
    const v = Math.round(target * ease(t));
    el.textContent = v.toLocaleString() + suffix;
    if (t < 1) requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

/* ============================================================
   WIRE TICKER (top strip)
   ============================================================ */
function renderTicker(data) {
  const cur = data.current;
  const daysSince = daysBetween(CLOSURE_DATE, cur.latest_date);
  const dt = document.getElementById("tickerDays");
  if (dt) dt.textContent = daysSince >= 0 ? String(daysSince) : "—";
  const dthru = document.getElementById("tickerDataThrough");
  if (dthru) dthru.textContent = fmt.dateMonoShort(cur.latest_date);
  const refreshed = document.getElementById("tickerRefreshed");
  if (refreshed) {
    const d = new Date(data.updated);
    refreshed.textContent = d.toLocaleString("en-US", {
      month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit",
      timeZone: "UTC", hour12: false,
    }).toUpperCase().replace(",", "") + " UTC";
  }
}

/* ============================================================
   HERO HEADLINE (count-up + editorial deck)
   ============================================================ */
function renderHero(data) {
  const cur = data.current;
  const pct = cur.vs_pre_feb_2026_pct;
  const headline = document.getElementById("heroHeadline");
  const deck = document.getElementById("heroDeck");
  if (!headline) return;

  // Direction class
  headline.classList.remove("up", "down", "flat");
  if (pct == null) headline.classList.add("flat");
  else if (pct < -2) headline.classList.add("down");
  else if (pct > 2) headline.classList.add("up");
  else headline.classList.add("flat");

  animatePercent(headline, pct);

  // Editorial deck — context-aware framing
  const daysSince = daysBetween(CLOSURE_DATE, cur.latest_date);
  const deckText = composeDeck(pct, daysSince, cur);
  if (deck) deck.innerHTML = deckText;
}

function composeDeck(pct, daysSince, cur) {
  const pre = "~89/day";
  const latest = `${cur.latest_total} transits`;
  const sevenDay = fmt.num(cur.last_7d_avg);
  if (pct == null) {
    return `Live count of ship traffic through the world's most critical oil chokepoint, refreshed daily from satellite AIS.`;
  }
  if (pct < -50) {
    return `Ship traffic through the strait has <strong>collapsed</strong> from a pre-closure baseline near <strong>${pre}</strong> to a 7-day average of <strong>${sevenDay}/day</strong>. Iran has held the chokepoint closed for <strong>${daysSince} days</strong>.`;
  }
  if (pct < -15) {
    return `Transit traffic remains materially below pre-closure levels (~${pre}) at <strong>${sevenDay}/day</strong> on a 7-day average. <strong>Day ${daysSince}</strong> of the closure crisis.`;
  }
  if (pct > 15) {
    return `Transit traffic now exceeds pre-closure norms — <strong>${sevenDay}/day</strong> vs. a baseline of <strong>${pre}</strong>.`;
  }
  return `Transit traffic is hovering near pre-closure norms — <strong>${sevenDay}/day</strong> vs. a baseline of <strong>${pre}</strong>. ${daysSince > 0 ? `Day ${daysSince} since the closure was declared.` : ""}`;
}

/* ============================================================
   SUPPORTING STATS (3 cards in a tight row)
   ============================================================ */
function renderStats(data) {
  const cur = data.current;
  const daysSinceClosure = daysBetween(CLOSURE_DATE, cur.latest_date);

  const cards = [
    {
      label: "Days closed",
      value: daysSinceClosure >= 0 ? String(daysSinceClosure) : "—",
      sub: `since ${fmt.dateShort(CLOSURE_DATE)} '26`,
      animate: { kind: "int", target: daysSinceClosure },
    },
    {
      label: "30-day avg",
      value: fmt.num(cur.last_30d_avg),
      sub: "transits/day",
    },
    {
      label: "Latest day",
      value: fmt.int(cur.latest_total),
      sub: `${fmt.dateShort(cur.latest_date)} · ${cur.latest_tanker} tankers`,
      animate: { kind: "int", target: cur.latest_total },
    },
  ];

  document.getElementById("stats").innerHTML = cards
    .map((c, i) => `
      <div class="stat-card">
        <div class="stat-label">${c.label}</div>
        <div class="stat-value" data-stat-idx="${i}">${c.value}</div>
        <div class="stat-sub">${c.sub}</div>
      </div>`)
    .join("");

  // Apply count-up animations after a tiny delay so stagger is visible
  setTimeout(() => {
    cards.forEach((c, i) => {
      if (!c.animate) return;
      const el = document.querySelector(`[data-stat-idx="${i}"]`);
      if (!el) return;
      if (c.animate.kind === "int") animateInt(el, c.animate.target);
    });
  }, 380);
}

/* ============================================================
   ANNOTATIONS (subtle vertical lines)
   ============================================================ */
function makeAnnotations(events) {
  const ann = {};
  events.forEach((e, i) => {
    const major = e.priority === "major";
    ann["evt" + i] = {
      type: "line",
      xMin: e.date,
      xMax: e.date,
      borderColor: major ? "rgba(217, 154, 43, 0.5)" : "rgba(217, 154, 43, 0.25)",
      borderWidth: major ? 1 : 0.8,
      borderDash: [3, 4],
      _major: major,
    };
  });
  return ann;
}

function highlightAnnotation(chart, idx) {
  Object.entries(chart.options.plugins.annotation.annotations).forEach(([key, a]) => {
    const isTarget = key === "evt" + idx;
    if (isTarget) {
      a.borderColor = "rgba(217, 154, 43, 1)";
      a.borderWidth = 2;
    } else {
      a.borderColor = a._major ? "rgba(217, 154, 43, 0.25)" : "rgba(217, 154, 43, 0.15)";
      a.borderWidth = a._major ? 1 : 0.8;
    }
  });
  if (chart.options.plugins.eventMarkers) {
    chart.options.plugins.eventMarkers.highlightedIdx = idx;
  }
  chart.update("none");
}

function clearAnnotationHighlight(chart) {
  Object.values(chart.options.plugins.annotation.annotations).forEach((a) => {
    a.borderColor = a._major ? "rgba(217, 154, 43, 0.5)" : "rgba(217, 154, 43, 0.25)";
    a.borderWidth = a._major ? 1 : 0.8;
  });
  if (chart.options.plugins.eventMarkers) {
    chart.options.plugins.eventMarkers.highlightedIdx = -1;
  }
  chart.update("none");
}

/* ============================================================
   MAIN CHART
   ============================================================ */
let mainChartRef = null;
let sortedEvents = [];
let currentRangeKey = "closure";
let activeEventIdx = -1;

function renderMainChart(data, events) {
  const labels = data.series.map((d) => d.date);
  const totals = data.series.map((d) => d.total);
  const ma7 = data.series.map((d) => d.ma7);
  const isMobile = window.innerWidth < 720;

  const tickFont = { family: FONT_MONO, size: 11 };

  mainChartRef = new Chart(document.getElementById("mainChart"), {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Daily transits",
          data: totals,
          borderColor: "rgba(90, 143, 194, 0.55)",
          backgroundColor: "rgba(90, 143, 194, 0.07)",
          borderWidth: 1,
          pointRadius: 0,
          pointHoverRadius: 4,
          tension: 0.1,
          fill: true,
        },
        {
          label: "7-day average",
          data: ma7,
          borderColor: C.caution,
          backgroundColor: "transparent",
          borderWidth: 2.2,
          pointRadius: 0,
          pointHoverRadius: 4,
          tension: 0.2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 350 },
      interaction: { mode: "index", intersect: false },
      layout: { padding: { bottom: 70 } },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#000",
          borderColor: C.inkEdge,
          borderWidth: 1,
          titleColor: C.paper,
          bodyColor: C.paper,
          titleFont: { family: FONT_MONO, size: 11, weight: "600" },
          bodyFont: { family: FONT_MONO, size: 11 },
          padding: 10,
          cornerRadius: 0,
        },
        annotation: { annotations: makeAnnotations(events) },
        eventMarkers: {
          events: events,
          minDate: RANGES[currentRangeKey] ? RANGES[currentRangeKey].min : null,
          highlightedIdx: -1,
        },
      },
      scales: {
        x: {
          type: "time",
          time: { unit: "year", tooltipFormat: "MMM d, yyyy" },
          grid: { color: "rgba(138, 152, 181, 0.06)", drawTicks: false },
          ticks: { color: C.steelFaint, font: tickFont, padding: 6 },
          border: { color: C.inkEdge },
        },
        y: {
          beginAtZero: true,
          title: isMobile ? { display: false } : {
            display: true,
            text: "TRANSITS / DAY",
            color: C.paperFaint,
            font: { family: FONT_MONO, size: 10, weight: "500" },
          },
          grid: { color: "rgba(138, 152, 181, 0.06)", drawTicks: false },
          ticks: { color: C.steelFaint, font: tickFont, padding: 8 },
          border: { color: C.inkEdge },
        },
      },
    },
  });
}

function resolveRange(rangeKey) {
  const range = RANGES[rangeKey];
  if (!range) return { min: null, max: null };
  if (range.dynamic && dataLatestDate) {
    const end = new Date(dataLatestDate + "T00:00:00Z");
    const start = new Date(end);
    start.setUTCDate(start.getUTCDate() - range.dynamic + 1);
    return { min: start.toISOString().slice(0, 10), max: dataLatestDate };
  }
  if (range.custom) {
    return { min: customRangeMin, max: customRangeMax };
  }
  return { min: range.min || null, max: null };
}

function applyRange(rangeKey) {
  if (!mainChartRef) return;
  currentRangeKey = rangeKey;
  const { min, max } = resolveRange(rangeKey);
  const x = mainChartRef.options.scales.x;

  if (min) x.min = min; else delete x.min;
  if (max) x.max = max; else delete x.max;

  if (min) {
    const span = (max ? new Date(max) : new Date()) - new Date(min);
    const days = span / 86400000;
    if (days <= 14) x.time.unit = "day";
    else if (days <= 120) x.time.unit = "week";
    else if (days <= 730) x.time.unit = "month";
    else x.time.unit = "year";
  } else {
    x.time.unit = "year";
  }

  if (mainChartRef.options.plugins.eventMarkers) {
    mainChartRef.options.plugins.eventMarkers.minDate = min;
    mainChartRef.options.plugins.eventMarkers.maxDate = max;
  }
  mainChartRef.update();
  renderEventList();

  const customEl = document.getElementById("customRange");
  if (customEl) customEl.hidden = rangeKey !== "custom";
}

/* ============================================================
   VESSEL CHART
   ============================================================ */
function renderVesselChart(data) {
  const last90 = data.series.slice(-90);
  const labels = last90.map((d) => d.date);
  const tanker = last90.map((d) => d.tanker);
  const dryBulk = last90.map((d) => d.dry_bulk);
  const container = last90.map((d) => d.container);
  const cargoOther = last90.map((d) => Math.max(d.cargo - d.dry_bulk - d.container, 0));

  const tickFont = { family: FONT_MONO, size: 11 };
  const legendFont = { family: FONT_MONO, size: 10, weight: "500" };

  new Chart(document.getElementById("vesselChart"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "TANKERS",     data: tanker,     backgroundColor: C.caution },
        { label: "DRY BULK",    data: dryBulk,    backgroundColor: C.dataBlue },
        { label: "CONTAINER",   data: container,  backgroundColor: C.dataViolet },
        { label: "OTHER CARGO", data: cargoOther, backgroundColor: C.dataMute },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: {
          labels: {
            color: C.paperDim,
            boxWidth: 12,
            boxHeight: 12,
            padding: 14,
            font: legendFont,
          },
          align: "start",
        },
        tooltip: {
          backgroundColor: "#000",
          borderColor: C.inkEdge,
          borderWidth: 1,
          titleColor: C.paper,
          bodyColor: C.paper,
          titleFont: { family: FONT_MONO, size: 11, weight: "600" },
          bodyFont: { family: FONT_MONO, size: 11 },
          padding: 10,
          cornerRadius: 0,
        },
      },
      scales: {
        x: {
          type: "time",
          time: { unit: "month", tooltipFormat: "MMM d, yyyy" },
          stacked: true,
          grid: { display: false },
          ticks: { color: C.steelFaint, font: tickFont, padding: 6 },
          border: { color: C.inkEdge },
        },
        y: {
          stacked: true,
          beginAtZero: true,
          grid: { color: "rgba(138, 152, 181, 0.06)", drawTicks: false },
          ticks: { color: C.steelFaint, font: tickFont, padding: 8 },
          border: { color: C.inkEdge },
        },
      },
    },
  });
}

/* ============================================================
   EVENT LIST (dispatch footnotes)
   ============================================================ */
function renderEventList() {
  const listEl = document.getElementById("eventList");
  if (!listEl) return;
  if (!sortedEvents.length) return;

  const { min: minDate, max: maxDate } = resolveRange(currentRangeKey);
  const visible = sortedEvents
    .map((e, i) => ({ ...e, idx: i }))
    .filter((e) => (!minDate || e.date >= minDate) && (!maxDate || e.date <= maxDate));

  if (visible.length === 0) {
    listEl.innerHTML = `<div class="event-empty">No events in this range.</div>`;
    return;
  }

  listEl.innerHTML = visible
    .map((e) => {
      const major = e.priority === "major";
      const isActive = e.idx === activeEventIdx;
      return `
        <button class="event-row${isActive ? " active" : ""}${major ? " major" : ""}" data-idx="${e.idx}" type="button">
          <span class="ev-num">${String(e.idx + 1).padStart(2, "0")}</span>
          <span class="ev-date">${fmt.dateMonoShort(e.date)} '${String(new Date(e.date).getUTCFullYear()).slice(2)}</span>
          <span class="ev-label">${e.label}</span>
          ${e.source ? `<a class="ev-source" href="${e.source}" rel="noopener" target="_blank" onclick="event.stopPropagation();">Source ↗</a>` : ""}
        </button>`;
    })
    .join("");

  listEl.querySelectorAll(".event-row").forEach((row) => {
    const idx = Number(row.dataset.idx);
    row.addEventListener("click", () => {
      activeEventIdx = activeEventIdx === idx ? -1 : idx;
      renderEventList();
      if (mainChartRef) {
        if (activeEventIdx >= 0) highlightAnnotation(mainChartRef, activeEventIdx);
        else clearAnnotationHighlight(mainChartRef);
      }
    });
    row.addEventListener("mouseenter", () => {
      if (mainChartRef) highlightAnnotation(mainChartRef, idx);
    });
    row.addEventListener("mouseleave", () => {
      if (mainChartRef) {
        if (activeEventIdx >= 0) highlightAnnotation(mainChartRef, activeEventIdx);
        else clearAnnotationHighlight(mainChartRef);
      }
    });
  });
}

/* ============================================================
   DATA TABLE
   ============================================================ */
let allSeriesData = null;

function renderDataTable(data) {
  allSeriesData = data;
  const tbody = document.getElementById("dataTableBody");
  const footer = document.getElementById("dataTableFooter");
  if (!tbody) return;

  const preFebAvg = data.baselines.pre_feb_2026.avg_total;
  const series = data.series;

  const SHOW_N = 60;
  const recent = series.slice(-SHOW_N).reverse();

  tbody.innerHTML = recent
    .map((row) => {
      const pct = preFebAvg ? ((row.total - preFebAvg) / preFebAvg) * 100 : null;
      const pctClass = pct == null ? "" : pct < -2 ? "down" : pct > 2 ? "up" : "";
      return `
        <tr>
          <td class="td-date">${fmt.dateMonoFull(row.date)}</td>
          <td class="td-num">${row.total}</td>
          <td class="td-num">${row.tanker}</td>
          <td class="td-num">${row.ma7 != null ? row.ma7.toFixed(1) : "—"}</td>
          <td class="td-num ${pctClass}">${pct == null ? "—" : (pct > 0 ? "+" : "") + pct.toFixed(0) + "%"}</td>
        </tr>`;
    })
    .join("");

  if (footer) {
    footer.textContent = `Latest ${recent.length} of ${series.length.toLocaleString()} days`;
  }
}

/* ============================================================
   DOWNLOAD AS PNG (matches dispatch styling)
   ============================================================ */
function downloadChartAsImage(data) {
  if (!mainChartRef) return;
  const W = 1600;
  const H = 900;

  const out = document.createElement("canvas");
  out.width = W;
  out.height = H;
  const ctx = out.getContext("2d");

  // Background
  ctx.fillStyle = C.inkDeep;
  ctx.fillRect(0, 0, W, H);

  // Top kicker bar
  ctx.fillStyle = C.caution;
  ctx.font = `500 18px ${FONT_MONO}`;
  ctx.fillText("DISPATCH №01 — PERSIAN GULF", 60, 60);

  // Title
  ctx.fillStyle = C.paper;
  ctx.font = `400 56px ${FONT_DISPLAY}`;
  ctx.fillText("HORMUZ TRACKER", 60, 115);

  // Subtitle
  const cur = data.current;
  const sub = `30-DAY AVG ${fmt.num(cur.last_30d_avg)}/DAY · ${fmt.pct(cur.vs_pre_feb_2026_pct)} VS PRE-CLOSURE · THROUGH ${fmt.dateMonoFull(cur.latest_date)}`;
  ctx.fillStyle = C.paperDim;
  ctx.font = `500 18px ${FONT_MONO}`;
  ctx.fillText(sub, 60, 145);

  // Chart image
  const chartImg = new Image();
  chartImg.onload = () => {
    ctx.drawImage(chartImg, 60, 175, W - 120, H - 260);

    // Footer
    ctx.fillStyle = C.caution;
    ctx.font = `700 22px ${FONT_DISPLAY}`;
    ctx.fillText(SITE_NAME.toUpperCase(), 60, H - 38);

    ctx.fillStyle = C.paperFaint;
    ctx.font = `500 14px ${FONT_MONO}`;
    ctx.textAlign = "right";
    ctx.fillText("SOURCE · IMF PORTWATCH (SAT. AIS)", W - 60, H - 38);
    ctx.textAlign = "left";

    const url = out.toDataURL("image/png");
    const a = document.createElement("a");
    a.href = url;
    a.download = `hormuz-transits-${cur.latest_date}.png`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  };
  chartImg.src = mainChartRef.toBase64Image("image/png", 1);
}

/* ============================================================
   COLOPHON
   ============================================================ */
function renderUpdated(data) {
  const el = document.getElementById("updatedAt");
  if (!el) return;
  const d = new Date(data.updated);
  const formatted = d.toLocaleString("en-US", {
    month: "short", day: "2-digit", year: "numeric",
    hour: "2-digit", minute: "2-digit", timeZone: "UTC", hour12: false,
  }).toUpperCase().replace(",", "") + " UTC";
  el.textContent = formatted;
}

/* ============================================================
   INIT
   ============================================================ */
(async function init() {
  try {
    const [data, events] = await Promise.all([
      loadJson("data/transits.json"),
      loadJson("data/events.json"),
    ]);

    sortedEvents = events.slice().sort((a, b) => (a.date < b.date ? -1 : 1));
    dataLatestDate = data.current.latest_date;

    renderTicker(data);
    renderHero(data);
    renderStats(data);
    renderMainChart(data, sortedEvents);
    renderVesselChart(data);
    renderEventList();
    renderDataTable(data);
    renderUpdated(data);
    applyRange(currentRangeKey);

    document.querySelectorAll(".range-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".range-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        applyRange(btn.dataset.range);
      });
    });

    const fromEl = document.getElementById("customFrom");
    const toEl = document.getElementById("customTo");
    if (fromEl && toEl) {
      const earliest = data.series[0].date;
      fromEl.min = earliest;
      fromEl.max = dataLatestDate;
      toEl.min = earliest;
      toEl.max = dataLatestDate;
      const latest = new Date(dataLatestDate + "T00:00:00Z");
      const ninetyAgo = new Date(latest);
      ninetyAgo.setUTCDate(ninetyAgo.getUTCDate() - 89);
      fromEl.value = ninetyAgo.toISOString().slice(0, 10);
      toEl.value = dataLatestDate;
    }

    const customApplyBtn = document.getElementById("customApplyBtn");
    if (customApplyBtn) {
      customApplyBtn.addEventListener("click", () => {
        const f = document.getElementById("customFrom").value;
        const t = document.getElementById("customTo").value;
        if (!f || !t) return;
        if (f > t) {
          alert("'From' date must be before 'To' date.");
          return;
        }
        customRangeMin = f;
        customRangeMax = t;
        applyRange("custom");
      });
    }

    document.getElementById("downloadBtn").addEventListener("click", () => downloadChartAsImage(data));

    // Re-render on resize so y-axis title shows/hides correctly
    let resizeTimer;
    window.addEventListener("resize", () => {
      clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        if (mainChartRef) {
          const isMobile = window.innerWidth < 720;
          mainChartRef.options.scales.y.title.display = !isMobile;
          mainChartRef.update();
        }
      }, 200);
    });
  } catch (e) {
    console.error(e);
    const stats = document.getElementById("stats");
    if (stats) stats.innerHTML = `<p style="color:${C.alert}; padding: 1rem;">Failed to load data: ${e.message}</p>`;
  }
})();
