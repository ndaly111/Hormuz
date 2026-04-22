"use strict";

const CLOSURE_DATE = "2026-03-04";
const SITE_NAME = "hormuz-traffic.com";

const RANGES = {
  all: { min: null, label: "2019 – present" },
  war: { min: "2025-06-01", label: "Jun 2025 – present" },
  closure: { min: "2026-02-01", label: "Feb 2026 – present" },
};

/* Watermark plugin — paints site name on every chart so screenshots carry attribution */
const watermarkPlugin = {
  id: "watermark",
  afterDraw(chart) {
    const { ctx, chartArea } = chart;
    if (!chartArea) return;
    ctx.save();
    ctx.font = "600 11px -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, sans-serif";
    ctx.fillStyle = "rgba(149, 163, 184, 0.55)";
    ctx.textAlign = "right";
    ctx.textBaseline = "bottom";
    ctx.fillText(SITE_NAME, chartArea.right - 8, chartArea.bottom - 6);
    ctx.restore();
  },
};
Chart.register(watermarkPlugin);

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

// Subtle vertical lines only (no labels on chart). Numbered markers handled by chips.
function makeAnnotations(events) {
  const ann = {};
  events.forEach((e, i) => {
    ann["evt" + i] = {
      type: "line",
      xMin: e.date,
      xMax: e.date,
      borderColor: "rgba(245, 166, 35, 0.45)",
      borderWidth: 1,
      borderDash: [3, 4],
    };
  });
  return ann;
}

function highlightAnnotation(chart, idx) {
  Object.entries(chart.options.plugins.annotation.annotations).forEach(([key, a]) => {
    const isTarget = key === "evt" + idx;
    a.borderColor = isTarget ? "rgba(245, 166, 35, 1)" : "rgba(245, 166, 35, 0.25)";
    a.borderWidth = isTarget ? 2.5 : 1;
  });
  chart.update("none");
}

function clearAnnotationHighlight(chart) {
  Object.values(chart.options.plugins.annotation.annotations).forEach((a) => {
    a.borderColor = "rgba(245, 166, 35, 0.45)";
    a.borderWidth = 1;
  });
  chart.update("none");
}

/* --- MAIN CHART --- */

let mainChartRef = null;
let allSeries = null;

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
  const range = RANGES[rangeKey];
  const x = mainChartRef.options.scales.x;
  if (range.min) {
    x.min = range.min;
    x.time.unit = "month";
  } else {
    delete x.min;
    x.time.unit = "year";
  }
  mainChartRef.update();
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
  const sorted = events.slice().sort((a, b) => (a.date < b.date ? -1 : 1));
  const chipsEl = document.getElementById("eventChips");
  const detailEl = document.getElementById("eventDetail");

  chipsEl.innerHTML = sorted
    .map((e, i) => `
      <button class="event-chip" data-idx="${i}" data-date="${e.date}" type="button">
        <span class="chip-num">${i + 1}</span>
        <span class="chip-date">${fmt.dateShort(e.date)} '${String(new Date(e.date).getUTCFullYear()).slice(2)}</span>
      </button>`)
    .join("");

  // Map sorted index -> original event annotation index (they're in the same order)
  const showDetail = (i) => {
    const e = sorted[i];
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

    renderStats(data);
    renderMainChart(data, events);
    renderVesselChart(data);
    renderEventChips(events);
    renderUpdated(data);

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
