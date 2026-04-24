"use strict";

const SITE_URL = "hormuz-traffic.com";
const CLOSURE_DATE = "2026-03-04";

const SHARE_RANGES = {
  d7:      { dynamic: 7,        label: "Last 7 days" },
  d30:     { dynamic: 30,       label: "Last 30 days" },
  closure: { min: "2026-02-01", label: "Since closure" },
  war:     { min: "2025-06-01", label: "Iran war era" },
  all:     { min: null,         label: "All time" },
};

/* Dispatch palette (mirrored from CSS tokens) */
const C = {
  paper:       "#ede4cb",
  paperDim:    "#c0b89e",
  paperFaint:  "#6f6a58",
  steelFaint:  "#5a6680",
  ink:         "#0a0f1c",
  inkDeep:     "#060912",
  inkEdge:     "#2a3548",
  alert:       "#c83232",
  caution:     "#d99a2b",
  dataBlue:    "#5a8fc2",
};

const FONT_MONO = "JetBrains Mono, IBM Plex Mono, Menlo, monospace";
const FONT_DISPLAY = "Bebas Neue, Oswald, sans-serif";

let currentRangeKey = "d30";
let dataCache = null;
let eventsCache = null;

const fmt = {
  num: (n) => Number(n).toLocaleString(undefined, { maximumFractionDigits: 1 }),
  int: (n) => Math.round(n).toLocaleString(),
  pct: (n) => `${n > 0 ? "+" : ""}${n.toFixed(1)}%`,
  date: (s) => new Date(s + "T00:00:00Z").toLocaleDateString("en-US",
    { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" }),
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

/* Build a 1200x675 share image in dispatch style */
async function generateShareImage(data, events, rangeKey) {
  const W = 1200, H = 675;
  const cur = data.current;
  const range = SHARE_RANGES[rangeKey];
  const { min, max } = resolveRange(rangeKey, cur.latest_date);
  const daysSince = daysBetween(CLOSURE_DATE, cur.latest_date);

  const out = document.createElement("canvas");
  out.width = W;
  out.height = H;
  const ctx = out.getContext("2d");

  // Background
  ctx.fillStyle = C.inkDeep;
  ctx.fillRect(0, 0, W, H);

  // Subtle navigational grid (very faint)
  ctx.save();
  ctx.strokeStyle = "rgba(138, 152, 181, 0.05)";
  ctx.lineWidth = 1;
  for (let x = 0; x < W; x += 60) {
    ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
  }
  for (let y = 0; y < H; y += 60) {
    ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
  }
  ctx.restore();

  // Wire ticker bar at very top
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, W, 32);

  // Pulsing dot (static, just red dot here)
  ctx.fillStyle = C.alert;
  ctx.beginPath();
  ctx.arc(50, 16, 4, 0, Math.PI * 2);
  ctx.fill();

  ctx.fillStyle = C.paper;
  ctx.font = `500 11px ${FONT_MONO}`;
  ctx.textBaseline = "middle";
  ctx.fillText("STATUS: STRAIT CLOSED", 64, 16);
  ctx.fillStyle = C.paperFaint;
  ctx.fillText(`DAY ${daysSince}  ·  DATA THRU ${fmt.dateMonoFull(cur.latest_date)}`, 244, 16);
  ctx.textAlign = "right";
  ctx.fillStyle = C.paperDim;
  ctx.fillText("HORMUZ-TRAFFIC.COM", W - 24, 16);
  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";

  // Kicker
  ctx.fillStyle = C.caution;
  ctx.font = `500 14px ${FONT_MONO}`;
  ctx.fillText("DISPATCH №01 — PERSIAN GULF", 50, 70);

  // Title
  ctx.fillStyle = C.paper;
  ctx.font = `400 64px ${FONT_DISPLAY}`;
  ctx.fillText("HORMUZ TRACKER", 50, 130);

  // Headline collapse % — large, alert-colored
  const pct = cur.vs_pre_feb_2026_pct;
  const pctStr = pct == null ? "—" : `${pct > 0 ? "+" : pct < 0 ? "−" : ""}${Math.abs(pct).toFixed(1)}%`;
  ctx.fillStyle = pct < -2 ? C.alert : pct > 2 ? "#4caf6d" : C.caution;
  ctx.font = `400 86px ${FONT_DISPLAY}`;
  ctx.fillText(pctStr, 50, 220);

  // Headline label
  ctx.fillStyle = C.paperDim;
  ctx.font = `500 13px ${FONT_MONO}`;
  ctx.fillText("VS. PRE-CLOSURE BASELINE  ·  7-DAY AVG " + fmt.num(cur.last_7d_avg) + "/DAY  ·  " + range.label.toUpperCase(), 50, 248);

  // ----- Chart area -----
  const chartTop = 280;
  const chartH = H - chartTop - 70;
  const hidden = document.getElementById("hiddenChart");
  hidden.width = W - 100;
  hidden.height = chartH;
  hidden.style.width = (W - 100) + "px";
  hidden.style.height = chartH + "px";

  const series = data.series.filter((d) => (!min || d.date >= min) && (!max || d.date <= max));
  const labels = series.map((d) => d.date);
  const totals = series.map((d) => d.total);
  const ma7 = series.map((d) => d.ma7);

  const span = (max ? new Date(max) : new Date(cur.latest_date)) - new Date(min || data.series[0].date);
  const days = span / 86400000;
  let unit;
  if (days <= 14) unit = "day";
  else if (days <= 120) unit = "week";
  else if (days <= 730) unit = "month";
  else unit = "year";

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
          borderColor: "rgba(90, 143, 194, 0.65)",
          backgroundColor: "rgba(90, 143, 194, 0.1)",
          borderWidth: 1.5,
          pointRadius: 0,
          tension: 0.1,
          fill: true,
        },
        {
          label: "7-day average",
          data: ma7,
          borderColor: C.caution,
          backgroundColor: "transparent",
          borderWidth: 3.2,
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
          grid: { color: "rgba(138, 152, 181, 0.08)", drawTicks: false },
          ticks: { color: C.steelFaint, font: { family: FONT_MONO, size: 12 }, padding: 6 },
          border: { color: C.inkEdge },
        },
        y: {
          beginAtZero: true,
          grid: { color: "rgba(138, 152, 181, 0.08)", drawTicks: false },
          ticks: { color: C.steelFaint, font: { family: FONT_MONO, size: 12 }, padding: 8 },
          border: { color: C.inkEdge },
          title: {
            display: true,
            text: "TRANSITS / DAY",
            color: C.paperFaint,
            font: { family: FONT_MONO, size: 11, weight: "500" },
          },
        },
      },
    },
  });

  await new Promise((r) => requestAnimationFrame(r));

  // Draw event annotations onto the hidden chart
  const chartCtx = hidden.getContext("2d");
  const xScale = window.__shareChart.scales.x;
  const chartArea = window.__shareChart.chartArea;
  if (chartArea && eventsInRange.length) {
    chartCtx.save();
    eventsInRange.forEach((e) => {
      const x = xScale.getPixelForValue(new Date(e.date + "T00:00:00Z").getTime());
      if (!Number.isFinite(x) || x < chartArea.left || x > chartArea.right) return;
      chartCtx.strokeStyle = e.priority === "major" ? "rgba(217, 154, 43, 0.7)" : "rgba(217, 154, 43, 0.4)";
      chartCtx.lineWidth = e.priority === "major" ? 1.5 : 1;
      chartCtx.setLineDash([4, 4]);
      chartCtx.beginPath();
      chartCtx.moveTo(x, chartArea.top);
      chartCtx.lineTo(x, chartArea.bottom);
      chartCtx.stroke();
    });
    chartCtx.restore();
  }

  // Composite chart onto output
  ctx.drawImage(hidden, 50, chartTop, W - 100, chartH);

  // Footer bar
  ctx.fillStyle = C.caution;
  ctx.font = `400 28px ${FONT_DISPLAY}`;
  ctx.fillText(SITE_URL.toUpperCase(), 50, H - 28);

  ctx.fillStyle = C.paperFaint;
  ctx.font = `500 13px ${FONT_MONO}`;
  ctx.textAlign = "right";
  ctx.fillText("SOURCE · IMF PORTWATCH (SAT. AIS)", W - 50, H - 28);
  ctx.textAlign = "left";

  return out.toDataURL("image/png");
}

function buildTweetText(data) {
  const cur = data.current;
  const daysSince = daysBetween(CLOSURE_DATE, cur.latest_date);
  return `Day ${daysSince} of Hormuz closure: 7-day avg ${fmt.num(cur.last_7d_avg)} ships/day (${fmt.pct(cur.vs_pre_feb_2026_pct)} vs pre-closure norm)`;
}

function buildReplyText() {
  return `Daily updates + historical chart: ${SITE_URL}`;
}

function updateTweetUI(data) {
  const text = buildTweetText(data);
  const reply = buildReplyText();
  document.getElementById("tweetText").value = text;
  document.getElementById("replyText").value = reply;
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

    document.querySelectorAll(".share-range-buttons .range-btn").forEach((btn) => {
      btn.addEventListener("click", async () => {
        document.querySelectorAll(".share-range-buttons .range-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        currentRangeKey = btn.dataset.range;
        await updateShareImage();
      });
    });

    function wireCopy(btnId, taId) {
      document.getElementById(btnId).addEventListener("click", async () => {
        const ta = document.getElementById(taId);
        try {
          await navigator.clipboard.writeText(ta.value);
          const btn = document.getElementById(btnId);
          const orig = btn.querySelector("span") ? btn.querySelector("span").textContent : btn.textContent;
          if (btn.querySelector("span")) btn.querySelector("span").textContent = "Copied ✓";
          else btn.textContent = "Copied ✓";
          setTimeout(() => {
            if (btn.querySelector("span")) btn.querySelector("span").textContent = orig;
            else btn.textContent = orig;
          }, 1500);
        } catch (e) {
          ta.select();
          document.execCommand("copy");
        }
      });
    }
    wireCopy("copyTextBtn", "tweetText");
    wireCopy("copyReplyBtn", "replyText");
  } catch (e) {
    console.error(e);
    document.getElementById("imageLoader").textContent = "Failed to load: " + e.message;
  }
})();
