"use strict";

const root = document.getElementById("app");
let DATA = { as_of: "", count: 0, picks: [] };

/* ---------- data ---------- */
async function load() {
  try {
    const r = await fetch("results.json?t=" + Date.now(), { cache: "no-store" });
    DATA = await r.json();
  } catch (e) {
    root.innerHTML = `<div class="empty"><div class="big">Couldn't load data</div>
      <div>Check back after the next refresh.</div></div>`;
    return;
  }
  route();
}
function route() {
  const tk = decodeURIComponent(location.hash.replace(/^#\/?/, ""));
  const p = DATA.picks.find(x => x.ticker === tk);
  p ? renderDetail(p) : renderHome();
  window.scrollTo(0, 0);
}

/* ---------- format ---------- */
const usd = x => x == null ? "—" : "$" + Number(x).toLocaleString(undefined,
  { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const pct = x => x == null ? "" : (x >= 0 ? "+" : "") + Math.round(x * 100) + "%";
const esc = s => { const d = document.createElement("div"); d.textContent = s ?? ""; return d.innerHTML; };

/* ---------- charts (pure SVG) ---------- */
function smooth(pts) {
  if (pts.length < 2) return "";
  let d = `M${pts[0][0]},${pts[0][1]}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i], p1 = pts[i], p2 = pts[i + 1], p3 = pts[i + 2] || p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = p1[1] + (p2[1] - p0[1]) / 6;
    const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = p2[1] - (p3[1] - p1[1]) / 6;
    d += ` C${c1x.toFixed(1)},${c1y.toFixed(1)} ${c2x.toFixed(1)},${c2y.toFixed(1)} ${p2[0].toFixed(1)},${p2[1].toFixed(1)}`;
  }
  return d;
}
function sliceDays(hist, days) {
  if (!days || !hist.length) return hist;
  const last = new Date(hist[hist.length - 1][0]);
  const cut = new Date(last); cut.setDate(cut.getDate() - days);
  const out = hist.filter(([d]) => new Date(d) >= cut);
  return out.length >= 2 ? out : hist.slice(-2);
}
function sparkline(hist) {
  const data = sliceDays(hist, 30).map(p => p[1]);
  if (data.length < 2) return "";
  const w = 72, h = 40, pad = 3, lo = Math.min(...data), hi = Math.max(...data);
  const xs = i => pad + (w - 2 * pad) * i / (data.length - 1);
  const ys = v => pad + (h - 2 * pad) * (1 - (hi === lo ? .5 : (v - lo) / (hi - lo)));
  const col = data[data.length - 1] >= data[0] ? "var(--green)" : "var(--red)";
  return `<svg class="spark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <path d="${smooth(data.map((v, i) => [xs(i), ys(v)]))}" fill="none"
      stroke="${col}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}
const RANGE_LABEL = { 7: "Past week", 30: "Past month", 182: "Past 6 months",
  365: "Past year", 0: "All time" };
function fmtDate(iso) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

// Renders the chart into `host` and wires Apple-Stocks-style scrubbing.
// `readout` = { price, chg, date } DOM elements updated live.
function mountChart(host, readout, hist, days, intrinsic) {
  const seg = sliceDays(hist, days);
  const data = seg.map(p => ({ date: p[0], price: p[1] }));
  if (data.length < 2) { host.innerHTML = '<div class="chart-note">No chart data.</div>'; return; }
  const W = 360, H = 220, padX = 6, padT = 14, padB = 18;
  const prices = data.map(d => d.price);
  const lo = Math.min(...prices, intrinsic ?? Infinity);
  const hi = Math.max(...prices, intrinsic ?? -Infinity);
  const xs = i => padX + (W - 2 * padX) * i / (data.length - 1);
  const ys = v => padT + (H - padT - padB) * (1 - (hi === lo ? .5 : (v - lo) / (hi - lo)));
  const first = prices[0], last = prices[prices.length - 1];
  const col = last >= first ? "var(--green)" : "var(--red)";
  const pts = data.map((d, i) => [xs(i), ys(d.price)]);
  const line = smooth(pts);
  const area = `${line} L${xs(data.length - 1).toFixed(1)},${H - padB} L${padX},${H - padB} Z`;
  const iv = intrinsic != null ? `<line x1="${padX}" y1="${ys(intrinsic).toFixed(1)}" x2="${W - padX}" y2="${ys(intrinsic).toFixed(1)}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="4 4" opacity="0.6"/>` : "";
  const gid = "g" + Math.random().toString(36).slice(2, 7);
  host.innerHTML = `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <defs><linearGradient id="${gid}" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0" stop-color="${col}" stop-opacity="0.25"/><stop offset="1" stop-color="${col}" stop-opacity="0"/></linearGradient></defs>
    <path d="${area}" fill="url(#${gid})"/>${iv}
    <path d="${line}" fill="none" stroke="${col}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
    <div class="cross" hidden><div class="cvline"></div><div class="cdot"></div></div>`;

  const svg = host.querySelector("svg");
  const cross = host.querySelector(".cross");
  const vline = host.querySelector(".cvline");
  const dot = host.querySelector(".cdot");
  dot.style.background = last >= first ? "var(--green)" : "var(--red)";

  const set = (price, dateLabel) => {
    const chg = (price - first) / first;
    readout.price.textContent = usd(price);
    readout.chg.textContent = `${chg >= 0 ? "+" : ""}${(chg * 100).toFixed(2)}%`;
    readout.chg.className = "chg " + (chg >= 0 ? "pos" : "neg");
    readout.date.textContent = dateLabel;
  };
  const rest = () => { cross.hidden = true; set(last, RANGE_LABEL[days || 0]); };
  rest();

  const scrub = clientX => {
    const r = host.getBoundingClientRect();
    let f = (clientX - r.left) / r.width;
    f = Math.max(0, Math.min(1, f));
    const i = Math.round(f * (data.length - 1));
    const px = (xs(i) / W) * r.width, py = (ys(data[i].price) / H) * r.height;
    cross.hidden = false;
    vline.style.left = px + "px";
    dot.style.left = px + "px";
    dot.style.top = py + "px";
    set(data[i].price, fmtDate(data[i].date));
  };
  svg.addEventListener("touchstart", e => { scrub(e.touches[0].clientX); e.preventDefault(); }, { passive: false });
  svg.addEventListener("touchmove", e => { scrub(e.touches[0].clientX); e.preventDefault(); }, { passive: false });
  svg.addEventListener("touchend", rest);
  svg.addEventListener("mousemove", e => scrub(e.clientX));
  svg.addEventListener("mouseleave", rest);
}

/* ---------- views ---------- */
function renderHome() {
  const sub = DATA.price_as_of
    ? `Prices ${DATA.price_as_of} · analysis ${DATA.as_of}`
    : (DATA.as_of ? `Updated ${DATA.as_of}` : "");
  if (!DATA.picks.length) {
    root.innerHTML = `
      <div class="title-lg">Strong Buys</div><div class="sub">${sub}</div>
      <div class="empty"><div class="dot">🟢</div>
        <div class="big">No strong buys this cycle</div>
        <div>Nothing cleared the quality bar at a 20% margin of safety.
        The screen ran fine — it's just being disciplined.</div></div>`;
    return;
  }
  const cards = DATA.picks.map(p => {
    const low = p.confidence === "low";
    return `
    <button class="card" onclick="location.hash='#/${encodeURIComponent(p.ticker)}'">
      <div class="id"><div class="tk">${esc(p.ticker)}</div>
        <div class="nm">${esc(p.name)}</div></div>
      ${sparkline(p.history || [])}
      <div class="rt"><div class="px">${usd(p.price)}</div>
        <div class="up ${p.upside >= 0 ? "pos" : "neg"}">${low ? "see range" : pct(p.upside)}</div>
        ${low ? '<div class="lowflag">⚠ low confidence</div>' : ""}</div>
    </button>`;
  }).join("");
  root.innerHTML = `<div class="title-lg">Strong Buys</div>
    <div class="sub">${sub}</div><div class="list">${cards}</div>`;
}

function acc(title, body, open) {
  return `<details class="acc"${open ? " open" : ""}>
    <summary>${title}<span class="chev">›</span></summary>
    <div class="acc-body">${body}</div></details>`;
}

function renderDetail(p) {
  const low = p.confidence === "low";
  const statsGrid = (p.stats || []).map(s =>
    `<div class="stat"><div class="l">${esc(s.label)}</div><div class="v">${esc(s.value)}</div></div>`).join("");

  const methods = (p.methods || []).map(m => `
    <div class="mrow"><span class="${m.used ? "mok" : "mno"}">${m.used ? "✓" : "✗"}</span>
      <div class="mtext"><div class="mname">${esc(m.name)}</div>
        <div class="mreason">${esc(m.reason)}</div></div></div>`).join("");

  const rec = p.reconciliation || { values: {}, sentence: "" };
  const recVals = Object.entries(rec.values || {}).map(([k, v]) =>
    `<div class="stat"><div class="l">${esc(k)}</div><div class="v">${usd(v)}</div></div>`).join("");
  const checklist = (p.profile || []).map(t => `<li>${esc(t)}</li>`).join("");
  const risks = (p.risks || []).map(t => `<li>${esc(t)}</li>`).join("");
  const news = (p.news || []).slice(0, 3).map(n =>
    `<li>${esc(n.title)} <span class="nm">(${esc([n.publisher, n.date].filter(Boolean).join(" · "))})</span></li>`).join("");

  // verdict header — always visible
  const header = low
    ? `<div class="fv">Fair value ${usd(p.range_low)}–${usd(p.range_high)}</div>
       <div class="lowbanner">⚠ LOW confidence — the models disagree. Treat the value as a wide range, not a target.</div>`
    : `<div class="fv">Fair value ${usd(p.intrinsic)} <span class="rng">(${usd(p.range_low)}–${usd(p.range_high)})</span></div>
       <div class="row"><span class="up ${p.upside >= 0 ? "pos" : "neg"}">${pct(p.upside)} upside</span>
         <span class="pill">${esc(p.confidence)} confidence</span></div>`;

  root.innerHTML = `
    <div class="nav"><button class="back" onclick="location.hash=''">
      <svg viewBox="0 0 12 20"><path d="M10 2 2 10l8 8" fill="none" stroke="currentColor"
        stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>Strong Buys</button></div>
    <div class="dh">
      <div class="nm">${esc(p.name)}</div>
      <div class="price">${usd(p.price)}</div>
      ${header}
    </div>
    ${p.thesis ? `<div class="thesis">${esc(p.thesis)}</div>` : ""}
    <div class="chartread">
      <span class="cprice" id="cprice"></span>
      <span class="chg" id="cchg"></span>
      <span class="cdate" id="cdate"></span>
    </div>
    <div class="chart-wrap"><div id="chart"></div></div>
    <div class="ranges" id="ranges"></div>
    <div class="chart-note">drag the chart to scrub · prices ${DATA.price_as_of || DATA.as_of}</div>

    <div class="sec"><h3>Key stats</h3><div class="grid">${statsGrid}</div></div>

    <div class="accordions">
      ${acc("How we valued it", `<div class="methods">${methods}</div>`, true)}
      ${acc("DCF — discounted cash flow", `<div class="report">${p.dcf_html || ""}</div>`)}
      ${acc("DDM — dividend discount", `<div class="report">${p.ddm_html || ""}</div>`)}
      ${acc("Comps — peer multiples", `<div class="report">${p.comps_html || ""}</div>`)}
      ${acc("Reconciliation & confidence",
          `<p class="recsent">${esc(rec.sentence)}</p><div class="grid">${recVals}</div>`)}
      ${acc("Quality checklist", `<ul class="bullets good">${checklist}</ul>`)}
      ${acc("Risks", `<ul class="bullets risk">${risks}</ul>` +
          (news ? `<div class="newshead">Recent news</div><ul class="bullets">${news}</ul>` : ""))}
    </div>
    <footer>Mechanical model output — not investment advice or legal due diligence.</footer>`;

  // chart + range toggles
  const ranges = [["1W", 7], ["1M", 30], ["6M", 182], ["1Y", 365], ["All", 0]];
  const rEl = document.getElementById("ranges");
  const cEl = document.getElementById("chart");
  const readout = {
    price: document.getElementById("cprice"),
    chg: document.getElementById("cchg"),
    date: document.getElementById("cdate"),
  };
  let active = "6M";
  const draw = () => {
    const days = ranges.find(r => r[0] === active)[1];
    mountChart(cEl, readout, p.history || [], days, p.intrinsic);
    rEl.innerHTML = ranges.map(([lab]) =>
      `<button class="range ${lab === active ? "active" : ""}" data-r="${lab}">${lab}</button>`).join("");
    rEl.querySelectorAll(".range").forEach(b =>
      b.addEventListener("click", () => { active = b.dataset.r; draw(); }));
  };
  draw();
}

window.addEventListener("hashchange", route);
load();
