"use strict";

const CLOSURE_DATE = "2026-03-04";
const SITE_NAME = "hormuz-traffic.com";

const RANGES = {
  all: { min: null, label: "2019 – present" },
  war: { min: "2025-06-01", label: "Jun 2025 – present" },
  closure: { min: "2026-02-01", label: "Feb 2026 – present" },
};

/* Watermark plugin — paints site name in top-right of every chart so screenshots carry attribution */
const watermarkPlugin = {
  id: "watermark",
  afterDraw(chart) {
    const { ctx, chartArea } = chart;
    if (!chartArea) return;
    ctx.save();
    ctx.font = "600 11px -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif";
    ctx.fillStyle = "rgba(149, 163, 184, 0.55)";
    ctx.textAlign = "right";
    ctx.textBaseline = "top";
    ctx.fillText(SITE_NAME, chartArea.right - 8, chartArea.top + 6);
    ctx.restore();
  },
};
Chart.register(watermarkPlugin);

/* Event markers plugin — draws numbered chips in a strip below the chart,
   with dotted connectors up to the chart and staggering for close events.
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
    const highlightedIdx = cfg.highlightedIdx ?? -1;

    // Convert date string to UTC timestamp for Chart.js time scale
    const tsFor = (d) => new Date(d + "T00:00:00Z").getTime();

    // Filter to visible events within current x-axis range
    const positions = cfg.events
      .map((e, i) => ({ ...e, idx: i }))
      .filter((e) => !minDate || e.date >= minDate)
      .map((e) => ({ ...e, x: xScale.getPixelForValue(tsFor(e.date)) }))
      .filter((p) => Number.isFinite(p.x) && p.x >= chartArea.left && p.x <= chartArea.right + 2);

    // Pack into rows: try row 0 first; if too close to last marker in that row, try row 1, etc.
    const MARKER_GAP_PX = 26;
    const rows = [];
    positions.forEach((p) => {
      let r = 0;
      while (rows[r] !== undefined && p.x - rows[r] < MARKER_GAP_PX) r++;
      p.row = r;
      rows[r] = p.x;
    });

    const ROW_HEIGHT = 22;
    const ROW_OFFSET = 24; // gap between chart and first row of markers

    positions.forEach((p) => {
      const major = p.priority === "major";
      const isHi = p.idx === highlightedIdx;
      const radius = major ? 11 : 8;
      const yMarker = chartArea.bottom + ROW_OFFSET + p.row * ROW_HEIGHT;

      // Dotted connector from chart bottom to the marker
      ctx.save();
      ctx.strokeStyle = isHi
        ? "rgba(245, 166, 35, 0.95)"
        : major
          ? "rgba(245, 166, 35, 0.5)"
          : "rgba(245, 166, 35, 0.3)";
      ctx.lineWidth = isHi ? 1.5 : 1;
      ctx.setLineDash([2, 3]);
      ctx.beginPath();
      ctx.moveTo(p.x, chartArea.bottom);
      ctx.lineTo(p.x, yMarker - radius);
      ctx.stroke();
      ctx.restore();

      // Filled circle
      ctx.save();
      ctx.fillStyle = isHi
        ? "#ffffff"
        : major
          ? "rgba(245, 166, 35, 0.95)"
          : "rgba(245, 166, 35, 0.75)";
      if (isHi) {
        ctx.shadowColor = "rgba(245, 166, 35, 0.8)";
        ctx.shadowBlur = 8;
      }
      ctx.beginPath();
      ctx.arc(p.x, yMarker, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      // Number
      ctx.save();
      ctx.fillStyle = isHi ? "#0a0e1a" : "#0a0e1a";
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
      label: "30-day average",
      value: fmt.num(cur.last_30d_avg),
      sub: `transits per day · through ${fmt.dateShort(cur.latest_date)}`,
    },
    {
      label: "vs pre-closure baseline",
      value: fmt.pct(cur.vs_pre_feb_2026_pct),
      sub: `pre-Feb 2026 avg: ${fmt.num(preFeb.avg_total)}/day`,
      cls: pctClass(cur.vs_pre_feb_2026_pct),
      highlight: true,
    },
    {
      label: "Days since closure",
      value: daysSinceClosure >= 0 ? daysSinceClosure : "—",
      sub: `Iran closed strait ${fmt.dateShort(CLOSURE_DATE)}, 2026`,
      highlight: true,
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

/* --- ANNOTATIONS --- */

// Vertical lines through the data area only (no labels — numbered chips live below).
function makeAnnotations(events) {
  const ann = {};
  events.forEach((e, i) => {
    const major = e.priority === "major";
    ann["evt" + i] = {
      type: "line",
      xMin: e.date,
      xMax: e.date,
      borderColor: major ? "rgba(245, 166, 35, 0.55)" : "rgba(245, 166, 35, 0.3)",
      borderWidth: major ? 1.25 : 1,
      borderDash: major ? [5, 4] : [3, 4],
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
      a.borderWidth = 2.5;
    } else {
      a.borderColor = a._major ? "rgba(245, 166, 35, 0.3)" : "rgba(245, 166, 35, 0.18)";
      a.borderWidth = a._major ? 1.25 : 1;
    }
  });
  if (chart.options.plugins.eventMarkers) {
    chart.options.plugins.eventMarkers.highlightedIdx = idx;
  }
  chart.update("none");
}

function clearAnnotationHighlight(chart) {
  Object.values(chart.options.plugins.annotation.annotations).forEach((a) => {
    a.borderColor = a._major ? "rgba(245, 166, 35, 0.55)" : "rgba(245, 166, 35, 0.3)";
    a.borderWidth = a._major ? 1.25 : 1;
  });
  if (chart.options.plugins.eventMarkers) {
    chart.options.plugins.eventMarkers.highlightedIdx = -1;
  }
  chart.update("none");
}

/* --- MAIN CHART --- */

let mainChartRef = null;
let allSeries = null;
let sortedEvents = [];
let currentRangeKey = "closure";

function renderMainChart(data, events) {
  const labels = data.series.map((d) => d.date);
  const totals = data.series.map((d) => d.total);
  const ma7 = data.series.map((d) => d.ma7);

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
      layout: { padding: { bottom: 80 } }, // room below for event marker strip
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
          grid: { color: "rgba(95, 107, 133, 0.1)" },
          ticks: { color: "#5c6b85" },
        },
        y: {
          beginAtZero: true,
          title: { display: true, text: "Transits per day", color: "#95a3b8" },
          grid: { color: "rgba(95, 107, 133, 0.1)" },
          ticks: { color: "#5c6b85" },
        },
      },
    },
  });

  allSeries = { latestDate: data.current.latest_date };
}

function applyRange(rangeKey) {
  if (!mainChartRef) return;
  currentRangeKey = rangeKey;
  const range = RANGES[rangeKey];
  const x = mainChartRef.options.scales.x;
  if (range.min) {
    x.min = range.min;
    x.time.unit = "month";
  } else {
    delete x.min;
    x.time.unit = "year";
  }
  if (mainChartRef.options.plugins.eventMarkers) {
    mainChartRef.options.plugins.eventMarkers.minDate = range.min;
  }
  mainChartRef.update();
  renderEventChips();
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
          title: { display: true, text: "Transits per day", color: "#95a3b8" },
          grid: { color: "rgba(95, 107, 133, 0.1)" },
          ticks: { color: "#5c6b85" },
        },
      },
    },
  });
}

/* --- EVENT CHIPS --- */

function renderEventChips(events) {
  if (events) {
    sortedEvents = events.slice().sort((a, b) => (a.date < b.date ? -1 : 1));
  }
  const chipsEl = document.getElementById("eventChips");
  const detailEl = document.getElementById("eventDetail");

  const minDate = RANGES[currentRangeKey] ? RANGES[currentRangeKey].min : null;
  const visible = sortedEvents
    .map((e, i) => ({ ...e, idx: i }))
    .filter((e) => !minDate || e.date >= minDate);

  if (visible.length === 0) {
    chipsEl.innerHTML = `<div style="color:var(--text-faint);font-size:0.85rem">No events in this range.</div>`;
    detailEl.hidden = true;
    return;
  }

  chipsEl.innerHTML = visible
    .map((e) => `
      <button class="event-chip" data-idx="${e.idx}" data-date="${e.date}" type="button">
        <span class="chip-num">${e.idx + 1}</span>
        <span class="chip-date">${fmt.dateShort(e.date)} '${String(new Date(e.date).getUTCFullYear()).slice(2)}</span>
      </button>`)
    .join("");

  detailEl.hidden = true;

  const showDetail = (i) => {
    const e = sortedEvents[i];
    detailEl.hidden = false;
    detailEl.innerHTML = `
      <span class="ed-num">${i + 1}</span>
      <span class="ed-date">${fmt.date(e.date)}</span>
      <span class="ed-label">${e.label}</span>
      ${e.source ? `<div class="ed-source"><a href="${e.source}" rel="noopener" target="_blank">↗ Source</a></div>` : ""}
    `;
    chipsEl.querySelectorAll(".event-chip").forEach((c) => {
      c.classList.toggle("active", Number(c.dataset.idx) === i);
    });
    if (mainChartRef) highlightAnnotation(mainChartRef, i);
  };

  chipsEl.querySelectorAll(".event-chip").forEach((chip) => {
    chip.addEventListener("click", () => showDetail(Number(chip.dataset.idx)));
    chip.addEventListener("mouseenter", () => {
      if (mainChartRef) highlightAnnotation(mainChartRef, Number(chip.dataset.idx));
    });
    chip.addEventListener("mouseleave", () => {
      const active = chipsEl.querySelector(".event-chip.active");
      if (active) highlightAnnotation(mainChartRef, Number(active.dataset.idx));
      else clearAnnotationHighlight(mainChartRef);
    });
  });
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

  // Background
  ctx.fillStyle = "#0a0e1a";
  ctx.fillRect(0, 0, W, H);

  // Title
  ctx.fillStyle = "#e8eaed";
  ctx.font = "bold 36px -apple-system, Segoe UI, Roboto, sans-serif";
  ctx.fillText("Strait of Hormuz — Daily Ship Transits", 60, 70);

  // Subtitle (current state)
  const cur = data.current;
  const sub = `30-day avg: ${fmt.num(cur.last_30d_avg)}/day · ${fmt.pct(cur.vs_pre_feb_2026_pct)} vs pre-closure baseline · through ${fmt.date(cur.latest_date)}`;
  ctx.fillStyle = "#95a3b8";
  ctx.font = "20px -apple-system, Segoe UI, Roboto, sans-serif";
  ctx.fillText(sub, 60, 110);

  // Chart image
  const chartImg = new Image();
  chartImg.onload = () => {
    ctx.drawImage(chartImg, 60, 150, W - 120, H - 240);

    // Watermark
    ctx.fillStyle = "#5c6b85";
    ctx.font = "18px -apple-system, Segoe UI, Roboto, sans-serif";
    ctx.fillText("hormuz-traffic.com", 60, H - 40);
    ctx.textAlign = "right";
    ctx.fillText("Source: IMF PortWatch (satellite AIS)", W - 60, H - 40);
    ctx.textAlign = "left";

    // Trigger download
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

    // Sort events once and cache so chart annotations + chips + plugin all use the same idx
    sortedEvents = events.slice().sort((a, b) => (a.date < b.date ? -1 : 1));

    renderStats(data);
    renderMainChart(data, sortedEvents);
    renderVesselChart(data);
    renderEventChips();
    renderUpdated(data);
    applyRange(currentRangeKey);

    document.querySelectorAll(".range-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".range-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        applyRange(btn.dataset.range);
      });
    });

    document.getElementById("downloadBtn").addEventListener("click", () => downloadChartAsImage(data));
  } catch (e) {
    console.error(e);
    document.getElementById("stats").innerHTML =
      `<p style="color:#e74c3c">Failed to load data: ${e.message}</p>`;
  }
})();
