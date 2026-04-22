"use strict";

const SITE_URL = "hormuz-traffic.com";
const CLOSURE_DATE = "2026-03-04";

const SHARE_RANGES = {
  d7: { dynamic: 7, label: "Last 7 days" },
  d30: { dynamic: 30, label: "Last 30 days" },
  closure: { min: "2026-02-01", label: "Since closure" },
  war: { min: "2025-06-01", label: "Iran war era" },
  all: { min: null, label: "All time" },
};

let currentRangeKey = "d30";
let dataCache = null;
let eventsCache = null;

const fmt = {
  num: (n) => Number(n).toLocaleString(undefined, { maximumFractionDigits: 1 }),
  int: (n) => Math.round(n).toLocaleString(),
  pct: (n) => `${n > 0 ? "+" : ""}${n.toFixed(1)}%`,
  date: (s) => new Date(s + "T00:00:00Z").toLocaleDateString("en-US",
    { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }),
};

const daysBetween = (a, b) =>
  Math.round((new Date(b + "T00:00:00Z") - new Date(a + "T00:00:00Z")) / 86400000);

async function loadJson(path) {
  const r = await fetch(path, { cache: "no-store" });
  if (!r.ok) throw new Error(`failed to load ${path}: ${r.status}`);
  return r.json();
}

function resolveRange(rangeKey, latestDate) {
  const range = SHARE_RANGES[rangeKey];
  if (!range) return { min: null };
  if (range.dynamic) {
    const end = new Date(latestDate + "T00:00:00Z");
    const start = new Date(end);
    start.setUTCDate(start.getUTCDate() - range.dynamic + 1);
    return { min: start.toISOString().slice(0, 10), max: latestDate };
  }
  return { min: range.min || null, max: null };
}

/* Build a 1200x675 share image: title bar + chart + footer with watermark + key stat */
async function generateShareImage(data, events, rangeKey) {
  const W = 1200, H = 675;
  const cur = data.current;
  const range = SHARE_RANGES[rangeKey];
  const { min, max } = resolveRange(rangeKey, cur.latest_date);
  const daysSince = daysBetween(CLOSURE_DATE, cur.latest_date);

  // Output canvas
  const out = document.createElement("canvas");
  out.width = W;
  out.height = H;
  const ctx = out.getContext("2d");

  // Background
  ctx.fillStyle = "#0a0e1a";
  ctx.fillRect(0, 0, W, H);

  // Top bar — title + headline stat
  ctx.fillStyle = "#e8eaed";
  ctx.font = "bold 32px -apple-system, Segoe UI, Roboto, sans-serif";
  ctx.fillText("Strait of Hormuz — Daily Ship Transits", 40, 50);

  ctx.fillStyle = "#95a3b8";
  ctx.font = "18px -apple-system, Segoe UI, Roboto, sans-serif";
  const sub = `${range.label} · 7-day avg ${fmt.num(cur.last_7d_avg)}/day · ${fmt.pct(cur.vs_pre_feb_2026_pct)} vs pre-closure baseline · Day ${daysSince} since closure`;
  ctx.fillText(sub, 40, 78);

  // Render the inner chart on a hidden canvas, then draw image of it onto out
  const hidden = document.getElementById("hiddenChart");
  const chartH = H - 95 - 60; // leave room for top bar (95) and footer (60)
  hidden.width = W - 60;
  hidden.height = chartH;
  hidden.style.width = (W - 60) + "px";
  hidden.style.height = chartH + "px";

  // Build chart data filtered to range
  const series = data.series.filter((d) => (!min || d.date >= min) && (!max || d.date <= max));
  const labels = series.map((d) => d.date);
  const totals = series.map((d) => d.total);
  const ma7 = series.map((d) => d.ma7);

  // Compute time unit
  const span = (max ? new Date(max) : new Date(cur.latest_date)) - new Date(min || data.series[0].date);
  const days = span / 86400000;
  let unit;
  if (days <= 14) unit = "day";
  else if (days <= 120) unit = "week";
  else if (days <= 730) unit = "month";
  else unit = "year";

  // Annotation lines for events in range
  const eventsInRange = events.filter((e) => (!min || e.date >= min) && (!max || e.date <= max));

  if (window.__shareChart) window.__shareChart.destroy();
  window.__shareChart = new Chart(hidden, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Daily transits",
          data: totals,
          borderColor: "rgba(74, 144, 226, 0.55)",
          backgroundColor: "rgba(74, 144, 226, 0.08)",
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.1,
          fill: true,
        },
        {
          label: "7-day average",
          data: ma7,
          borderColor: "#f5a623",
          backgroundColor: "transparent",
          borderWidth: 3,
          pointRadius: 0,
          tension: 0.2,
        },
      ],
    },
    options: {
      responsive: false,
      animation: false,
      devicePixelRatio: 2,
      plugins: {
        legend: { display: false },
        tooltip: { enabled: false },
      },
      scales: {
        x: {
          type: "time",
          time: { unit, tooltipFormat: "MMM d, yyyy" },
          grid: { color: "rgba(95, 107, 133, 0.15)" },
          ticks: { color: "#95a3b8", font: { size: 12 } },
        },
        y: {
          beginAtZero: true,
          grid: { color: "rgba(95, 107, 133, 0.15)" },
          ticks: { color: "#95a3b8", font: { size: 12 } },
          title: { display: true, text: "Transits per day", color: "#95a3b8", font: { size: 13 } },
        },
      },
    },
  });

  // Wait one frame for chart to render
  await new Promise((r) => requestAnimationFrame(r));

  // Draw event annotation lines manually onto the hidden chart canvas
  const chartCtx = hidden.getContext("2d");
  const xScale = window.__shareChart.scales.x;
  const chartArea = window.__shareChart.chartArea;
  if (chartArea && eventsInRange.length) {
    chartCtx.save();
    eventsInRange.forEach((e) => {
      const x = xScale.getPixelForValue(new Date(e.date + "T00:00:00Z").getTime());
      if (!Number.isFinite(x) || x < chartArea.left || x > chartArea.right) return;
      chartCtx.strokeStyle = e.priority === "major" ? "rgba(245, 166, 35, 0.7)" : "rgba(245, 166, 35, 0.4)";
      chartCtx.lineWidth = e.priority === "major" ? 1.5 : 1;
      chartCtx.setLineDash([4, 4]);
      chartCtx.beginPath();
      chartCtx.moveTo(x, chartArea.top);
      chartCtx.lineTo(x, chartArea.bottom);
      chartCtx.stroke();
    });
    chartCtx.restore();
  }

  // Composite hidden chart onto out
  ctx.drawImage(hidden, 30, 95, W - 60, chartH);

  // Footer bar
  ctx.fillStyle = "#f5a623";
  ctx.font = "bold 22px -apple-system, Segoe UI, Roboto, sans-serif";
  ctx.fillText(SITE_URL, 40, H - 25);

  ctx.fillStyle = "#5c6b85";
  ctx.font = "15px -apple-system, Segoe UI, Roboto, sans-serif";
  ctx.textAlign = "right";
  ctx.fillText(`Source: IMF PortWatch · Updated ${fmt.date(cur.latest_date)}`, W - 40, H - 25);
  ctx.textAlign = "left";

  return out.toDataURL("image/png");
}

function buildTweetText(data) {
  const cur = data.current;
  const daysSince = daysBetween(CLOSURE_DATE, cur.latest_date);
  return `🚢 Strait of Hormuz transit update — Day ${daysSince} since closure

Latest day: ${cur.latest_total} transits (${cur.latest_tanker} tankers)
7-day avg: ${fmt.num(cur.last_7d_avg)}/day vs ~89/day pre-closure (${fmt.pct(cur.vs_pre_feb_2026_pct)})

📊 Live tracker: ${SITE_URL}`;
}

function updateTweetUI(data) {
  const text = buildTweetText(data);
  document.getElementById("tweetText").value = text;
  const tweetLink = document.getElementById("tweetLink");
  tweetLink.href = `https://twitter.com/intent/tweet?text=${encodeURIComponent(text)}`;
}

async function updateShareImage() {
  if (!dataCache || !eventsCache) return;
  const loader = document.getElementById("imageLoader");
  const img = document.getElementById("shareImage");
  loader.hidden = false;
  loader.textContent = "Generating image…";
  img.hidden = true;

  try {
    const dataUrl = await generateShareImage(dataCache, eventsCache, currentRangeKey);
    img.src = dataUrl;
    img.hidden = false;
    loader.hidden = true;
  } catch (e) {
    console.error(e);
    loader.textContent = "Failed to generate image: " + e.message;
  }
}

(async function init() {
  try {
    const [data, events] = await Promise.all([
      loadJson("data/transits.json"),
      loadJson("data/events.json"),
    ]);
    dataCache = data;
    eventsCache = events.slice().sort((a, b) => (a.date < b.date ? -1 : 1));

    updateTweetUI(data);
    await updateShareImage();

    // Range buttons
    document.querySelectorAll(".share-range-buttons .range-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        document.querySelectorAll(".share-range-buttons .range-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        currentRangeKey = btn.dataset.range;
        await updateShareImage();
      });
    });

    // Copy text
    document.getElementById("copyTextBtn").addEventListener("click", async () => {
      const ta = document.getElementById("tweetText");
      try {
        await navigator.clipboard.writeText(ta.value);
        const btn = document.getElementById("copyTextBtn");
        const orig = btn.textContent;
        btn.textContent = "Copied ✓";
        setTimeout(() => (btn.textContent = orig), 1500);
      } catch (e) {
        // Fallback for browsers without clipboard API
        ta.select();
        document.execCommand("copy");
      }
    });
  } catch (e) {
    console.error(e);
    document.getElementById("imageLoader").textContent = "Failed to load: " + e.message;
  }
})();
