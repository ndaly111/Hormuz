"use strict";

const CLOSURE_DATE = "2026-03-04";
const SITE_NAME = "hormuz-traffic.com";

const RANGES = {
  all: { min: null, label: "2019 – present" },
  war: { min: "2025-06-01", label: "Jun 2025 – present" },
  closure: { min: "2026-02-01", label: "Feb 2026 – present" },
  d30: { dynamic: 30, label: "Last 30 days" },
  d7: { dynamic: 7, label: "Last 7 days" },
  custom: { custom: true, label: "Custom range" },
};

let customRangeMin = null;
let customRangeMax = null;
let dataLatestDate = null;

/* Event markers plugin — draws numbered chips in a strip below the chart,
   with dotted connectors. Caps stagger at 2 rows; nudges edge markers inward.
   Reads its config from chart.options.plugins.eventMarkers. */
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

    // Filter to visible events; keep dataX (true position) and adjust x for edge nudge.
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

    // Edge nudging — keep marker fully inside the chart horizontally
    const RADIUS_MAJOR = 11;
    const RADIUS_MINOR = 8;
    positions.forEach((p) => {
      const r = (p.priority === "major" ? RADIUS_MAJOR : RADIUS_MINOR) + 2;
      if (p.x - r < chartArea.left) p.x = chartArea.left + r;
      if (p.x + r > chartArea.right) p.x = chartArea.right - r;
    });

    // Stagger: cap at 2 rows. If both rows are too close, accept slight overlap.
    const MAX_ROWS = 2;
    const MARKER_GAP_PX = 26;
    const lastInRow = [];
    positions.forEach((p) => {
      let chosen = 0;
      for (let r = 0; r < MAX_ROWS; r++) {
        if (lastInRow[r] === undefined || p.x - lastInRow[r] >= MARKER_GAP_PX) {
          chosen = r;
          break;
        }
        chosen = r; // remember; if no row fits, last iteration wins
      }
      p.row = chosen;
      lastInRow[chosen] = p.x;
    });

    const ROW_HEIGHT = 24;
    const ROW_OFFSET = 22;

    // Draw connectors first (under markers)
    positions.forEach((p) => {
      const major = p.priority === "major";
      const isHi = p.idx === highlightedIdx;
      const radius = major ? RADIUS_MAJOR : RADIUS_MINOR;
      const yMarker = chartArea.bottom + ROW_OFFSET + p.row * ROW_HEIGHT;

      ctx.save();
      ctx.strokeStyle = isHi
        ? "rgba(245, 166, 35, 0.95)"
        : major
          ? "rgba(245, 166, 35, 0.55)"
          : "rgba(245, 166, 35, 0.32)";
      ctx.lineWidth = isHi ? 1.5 : 1;
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      // Connector goes from the true date position at chart bottom
      // diagonally to the (possibly nudged) marker position.
      ctx.moveTo(p.dataX, chartArea.bottom);
      ctx.lineTo(p.x, yMarker - radius);
      ctx.stroke();
      ctx.restore();
    });

    // Draw markers and numbers
    positions.forEach((p) => {
      const major = p.priority === "major";
      const isHi = p.idx === highlightedIdx;
      const radius = major ? RADIUS_MAJOR : RADIUS_MINOR;
      const yMarker = chartArea.bottom + ROW_OFFSET + p.row * ROW_HEIGHT;

      ctx.save();
      // Major: filled solid. Minor: outlined ring (visual differentiation beyond size).
      if (major) {
        ctx.fillStyle = isHi ? "#ffffff" : "rgba(245, 166, 35, 0.95)";
        if (isHi) {
          ctx.shadowColor = "rgba(245, 166, 35, 0.8)";
          ctx.shadowBlur = 8;
        }
        ctx.beginPath();
        ctx.arc(p.x, yMarker, radius, 0, Math.PI * 2);
        ctx.fill();
      } else {
        ctx.fillStyle = "#0a0e1a";
        ctx.beginPath();
        ctx.arc(p.x, yMarker, radius, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = isHi ? "#ffffff" : "rgba(245, 166, 35, 0.85)";
        ctx.lineWidth = isHi ? 2 : 1.5;
        ctx.beginPath();
        ctx.arc(p.x, yMarker, radius, 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.restore();

      // Number
      ctx.save();
      ctx.fillStyle = major ? "#0a0e1a" : isHi ? "#ffffff" : "rgba(245, 166, 35, 0.95)";
      ctx.font = `bold ${major ? 12 : 10}px -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText(String(p.idx + 1), p.x, yMarker + 0.5);
      ctx.restore();
    });
  },
};
Chart.register(eventMarkersPlugin);

const fmt = {
  int: (n) => (n == null ? "—" : Math.round(n).toLocaleString()),
  num: (n) => (n == null ? "—" : Number(n).toLocaleString(undefined, { maximumFractionDigits: 1 })),
  pct: (n) => (n == null ? "—" : `${n > 0 ? "+" : ""}${n.toFixed(1)}%`),
  date: (s) => new Date(s + "T00:00:00Z").toLocaleDateString("en-US",
    { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }),
  dateShort: (s) => new Date(s + "T00:00:00Z").toLocaleDateString("en-US",
    { month: "short", day: "numeric", timeZone: "UTC" }),
  dateShortYr: (s) => {
    const d = new Date(s + "T00:00:00Z");
    return d.toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" })
      + " '" + String(d.getUTCFullYear()).slice(2);
  },
};

const daysBetween = (a, b) =>
  Math.round((new Date(b + "T00:00:00Z") - new Date(a + "T00:00:00Z")) / 86400000);

async function loadJson(path) {
  const r = await fetch(path, { cache: "no-store" });
  if (!r.ok) throw new Error(`failed to load ${path}: ${r.status}`);
  return r.json();
}

/* --- STATS --- */

function renderStats(data) {
  const cur = data.current;
  const preFeb = data.baselines.pre_feb_2026;
  const daysSinceClosure = daysBetween(CLOSURE_DATE, cur.latest_date);

  const pctClass = (p) => (p == null ? "" : p < -2 ? "down" : p > 2 ? "up" : "");

  const cards = [
    {
      label: "vs pre-closure baseline",
      value: fmt.pct(cur.vs_pre_feb_2026_pct),
      sub: `pre-Feb 2026: ${fmt.num(preFeb.avg_total)}/day`,
      cls: pctClass(cur.vs_pre_feb_2026_pct),
      highlight: true,
    },
    {
      label: "Days since closure",
      value: daysSinceClosure >= 0 ? daysSinceClosure : "—",
      sub: `since ${fmt.dateShort(CLOSURE_DATE)} '26`,
      highlight: true,
    },
    {
      label: "30-day average",
      value: fmt.num(cur.last_30d_avg),
      sub: `transits/day`,
    },
    {
      label: "Latest day",
      value: fmt.int(cur.latest_total),
      sub: `${fmt.dateShort(cur.latest_date)} · ${cur.latest_tanker} tankers`,
    },
  ];

  document.getElementById("stats").innerHTML = cards
    .map((c) => `
      <div class="stat-card${c.highlight ? " highlight" : ""}">
        <div class="stat-label">${c.label}</div>
        <div class="stat-value ${c.cls || ""}">${c.value}</div>
        <div class="stat-sub">${c.sub}</div>
      </div>`)
    .join("");
}

/* --- ANNOTATIONS (subtle vertical lines through chart data area) --- */

function makeAnnotations(events) {
  const ann = {};
  events.forEach((e, i) => {
    const major = e.priority === "major";
    ann["evt" + i] = {
      type: "line",
      xMin: e.date,
      xMax: e.date,
      borderColor: major ? "rgba(245, 166, 35, 0.5)" : "rgba(245, 166, 35, 0.25)",
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
      a.borderColor = "rgba(245, 166, 35, 1)";
      a.borderWidth = 2;
    } else {
      a.borderColor = a._major ? "rgba(245, 166, 35, 0.25)" : "rgba(245, 166, 35, 0.15)";
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
    a.borderColor = a._major ? "rgba(245, 166, 35, 0.5)" : "rgba(245, 166, 35, 0.25)";
    a.borderWidth = a._major ? 1 : 0.8;
  });
  if (chart.options.plugins.eventMarkers) {
    chart.options.plugins.eventMarkers.highlightedIdx = -1;
  }
  chart.update("none");
}

/* --- MAIN CHART --- */

let mainChartRef = null;
let sortedEvents = [];
let currentRangeKey = "closure";
let activeEventIdx = -1;

function renderMainChart(data, events) {
  const labels = data.series.map((d) => d.date);
  const totals = data.series.map((d) => d.total);
  const ma7 = data.series.map((d) => d.ma7);
  const isMobile = window.innerWidth < 600;

  mainChartRef = new Chart(document.getElementById("mainChart"), {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Daily transits",
          data: totals,
          borderColor: "rgba(74, 144, 226, 0.45)",
          backgroundColor: "rgba(74, 144, 226, 0.06)",
          borderWidth: 1,
          pointRadius: 0,
          pointHoverRadius: 4,
          tension: 0.1,
          fill: true,
        },
        {
          label: "7-day average",
          data: ma7,
          borderColor: "#f5a623",
          backgroundColor: "transparent",
          borderWidth: 2,
          pointRadius: 0,
          pointHoverRadius: 4,
          tension: 0.2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      interaction: { mode: "index", intersect: false },
      layout: { padding: { bottom: 70 } }, // room for 2-row marker strip
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "#0a0e1a",
          borderColor: "#1f2940",
          borderWidth: 1,
          titleColor: "#e8eaed",
          bodyColor: "#e8eaed",
          padding: 10,
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
          grid: { color: "rgba(95, 107, 133, 0.08)" },
          ticks: { color: "#5c6b85" },
        },
        y: {
          beginAtZero: true,
          title: isMobile ? { display: false } : { display: true, text: "Transits per day", color: "#95a3b8" },
          grid: { color: "rgba(95, 107, 133, 0.08)" },
          ticks: { color: "#5c6b85" },
        },
      },
    },
  });
}

// Compute the effective min/max for a given range key.
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

  if (min) { x.min = min; } else { delete x.min; }
  if (max) { x.max = max; } else { delete x.max; }

  // Pick a sensible time-axis unit based on window size
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

  // Toggle custom date input row
  const customEl = document.getElementById("customRange");
  if (customEl) customEl.hidden = rangeKey !== "custom";
}

/* --- VESSEL CHART --- */

function renderVesselChart(data) {
  const last90 = data.series.slice(-90);
  const labels = last90.map((d) => d.date);
  const tanker = last90.map((d) => d.tanker);
  const dryBulk = last90.map((d) => d.dry_bulk);
  const container = last90.map((d) => d.container);
  const cargoOther = last90.map((d) => Math.max(d.cargo - d.dry_bulk - d.container, 0));

  new Chart(document.getElementById("vesselChart"), {
    type: "bar",
    data: {
      labels,
      datasets: [
        { label: "Tankers", data: tanker, backgroundColor: "#f5a623" },
        { label: "Dry bulk", data: dryBulk, backgroundColor: "#4a90e2" },
        { label: "Container", data: container, backgroundColor: "#9b59b6" },
        { label: "Other cargo", data: cargoOther, backgroundColor: "#5c6b85" },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { labels: { color: "#e8eaed", boxWidth: 14, padding: 12 } },
        tooltip: {
          backgroundColor: "#0a0e1a",
          borderColor: "#1f2940",
          borderWidth: 1,
          titleColor: "#e8eaed",
          bodyColor: "#e8eaed",
          padding: 10,
        },
      },
      scales: {
        x: {
          type: "time",
          time: { unit: "month", tooltipFormat: "MMM d, yyyy" },
          stacked: true,
          grid: { display: false },
          ticks: { color: "#5c6b85" },
        },
        y: {
          stacked: true,
          beginAtZero: true,
          grid: { color: "rgba(95, 107, 133, 0.08)" },
          ticks: { color: "#5c6b85" },
        },
      },
    },
  });
}

/* --- EVENT LIST (informative rows, not duplicate chips) --- */

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
          <span class="ev-num">${e.idx + 1}</span>
          <span class="ev-date">${fmt.dateShortYr(e.date)}</span>
          <span class="ev-label">${e.label}</span>
          ${e.source ? `<a class="ev-source" href="${e.source}" rel="noopener" target="_blank" onclick="event.stopPropagation();">Source ↗</a>` : ""}
        </button>`;
    })
    .join("");

  listEl.querySelectorAll(".event-row").forEach((row) => {
    const idx = Number(row.dataset.idx);
    row.addEventListener("click", () => {
      activeEventIdx = activeEventIdx === idx ? -1 : idx;
      renderEventList(); // re-render to update active state
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

/* --- DATA TABLE --- */

let allSeriesData = null;

function renderDataTable(data) {
  allSeriesData = data;
  const tbody = document.getElementById("dataTableBody");
  const footer = document.getElementById("dataTableFooter");
  if (!tbody) return;

  const preFebAvg = data.baselines.pre_feb_2026.avg_total;
  const series = data.series;

  // Show last 60 days; user can scroll within the wrapper
  const SHOW_N = 60;
  const recent = series.slice(-SHOW_N).reverse(); // most recent first

  tbody.innerHTML = recent
    .map((row) => {
      const pct = preFebAvg ? ((row.total - preFebAvg) / preFebAvg) * 100 : null;
      const pctClass = pct == null ? "" : pct < -2 ? "down" : pct > 2 ? "up" : "";
      return `
        <tr>
          <td class="td-date">${fmt.date(row.date)}</td>
          <td class="td-num">${row.total}</td>
          <td class="td-num">${row.tanker}</td>
          <td class="td-num">${row.ma7 != null ? row.ma7.toFixed(1) : "—"}</td>
          <td class="td-num ${pctClass}">${pct == null ? "—" : (pct > 0 ? "+" : "") + pct.toFixed(0) + "%"}</td>
        </tr>`;
    })
    .join("");

  if (footer) {
    footer.textContent = `Showing latest ${recent.length} of ${series.length.toLocaleString()} days`;
  }
}

/* --- DOWNLOAD AS PNG --- */

function downloadChartAsImage(data) {
  if (!mainChartRef) return;
  const W = 1600;
  const H = 900;

  const out = document.createElement("canvas");
  out.width = W;
  out.height = H;
  const ctx = out.getContext("2d");

  ctx.fillStyle = "#0a0e1a";
  ctx.fillRect(0, 0, W, H);

  ctx.fillStyle = "#e8eaed";
  ctx.font = "bold 36px -apple-system, Segoe UI, Roboto, sans-serif";
  ctx.fillText("Strait of Hormuz — Daily Ship Transits", 60, 70);

  const cur = data.current;
  const sub = `30-day avg: ${fmt.num(cur.last_30d_avg)}/day · ${fmt.pct(cur.vs_pre_feb_2026_pct)} vs pre-closure baseline · through ${fmt.date(cur.latest_date)}`;
  ctx.fillStyle = "#95a3b8";
  ctx.font = "20px -apple-system, Segoe UI, Roboto, sans-serif";
  ctx.fillText(sub, 60, 110);

  const chartImg = new Image();
  chartImg.onload = () => {
    ctx.drawImage(chartImg, 60, 150, W - 120, H - 240);

    // Footer watermark
    ctx.fillStyle = "#f5a623";
    ctx.font = "bold 20px -apple-system, Segoe UI, Roboto, sans-serif";
    ctx.fillText(SITE_NAME, 60, H - 38);
    ctx.fillStyle = "#5c6b85";
    ctx.font = "16px -apple-system, Segoe UI, Roboto, sans-serif";
    ctx.textAlign = "right";
    ctx.fillText("Source: IMF PortWatch (satellite AIS)", W - 60, H - 38);
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

/* --- FOOTER --- */

function renderUpdated(data) {
  const el = document.getElementById("updatedAt");
  el.textContent = new Date(data.updated).toLocaleString("en-US", {
    month: "short", day: "numeric", year: "numeric",
    hour: "numeric", minute: "2-digit", timeZone: "UTC", timeZoneName: "short",
  });
}

/* --- INIT --- */

(async function init() {
  try {
    const [data, events] = await Promise.all([
      loadJson("data/transits.json"),
      loadJson("data/events.json"),
    ]);

    sortedEvents = events.slice().sort((a, b) => (a.date < b.date ? -1 : 1));
    dataLatestDate = data.current.latest_date;

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

    // Initialize custom date inputs with sensible defaults
    const fromEl = document.getElementById("customFrom");
    const toEl = document.getElementById("customTo");
    if (fromEl && toEl) {
      const earliest = data.series[0].date;
      fromEl.min = earliest;
      fromEl.max = dataLatestDate;
      toEl.min = earliest;
      toEl.max = dataLatestDate;
      // Default to a 90-day window ending on latest
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
          const isMobile = window.innerWidth < 600;
          mainChartRef.options.scales.y.title.display = !isMobile;
          mainChartRef.update();
        }
      }, 200);
    });
  } catch (e) {
    console.error(e);
    document.getElementById("stats").innerHTML =
      `<p style="color:#e74c3c">Failed to load data: ${e.message}</p>`;
  }
})();
