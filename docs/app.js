"use strict";

const root = document.getElementById("app");
let DATA = { as_of: "", count: 0, picks: [], etfs: [] };
let homeTab = "stocks";   // "stocks" | "etfs"

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
  const p = [...(DATA.picks || []), ...(DATA.etfs || [])].find(x => x.ticker === tk);
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
function fmtDate(iso) {
  const intra = iso.length > 10;               // "YYYY-MM-DD HH:MM"
  const d = new Date(iso.replace(" ", "T") + (intra ? "" : "T00:00:00"));
  return d.toLocaleString(undefined, intra
    ? { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }
    : { month: "short", day: "numeric", year: "numeric" });
}

// Renders `data` ([[date, price]], already windowed) into `host` with
// Apple-Stocks scrubbing PLUS press-and-drag span selection:
//   tap/hover -> price + % vs range start; press & drag -> % between the two points.
function mountChart(host, readout, data, label, intrinsic) {
  if (!data || data.length < 2) { host.innerHTML = '<div class="chart-note">No chart data.</div>'; return; }
  const W = 360, H = 220, padX = 6, padT = 14, padB = 18;
  const prices = data.map(d => d[1]);
  const lo = Math.min(...prices, intrinsic ?? Infinity);
  const hi = Math.max(...prices, intrinsic ?? -Infinity);
  const xs = i => padX + (W - 2 * padX) * i / (data.length - 1);
  const ys = v => padT + (H - padT - padB) * (1 - (hi === lo ? .5 : (v - lo) / (hi - lo)));
  const first = prices[0], last = prices[prices.length - 1];
  const col = last >= first ? "var(--green)" : "var(--red)";
  const line = smooth(data.map((d, i) => [xs(i), ys(d[1])]));
  const area = `${line} L${xs(data.length - 1).toFixed(1)},${H - padB} L${padX},${H - padB} Z`;
  const ivl = intrinsic != null ? `<line x1="${padX}" y1="${ys(intrinsic).toFixed(1)}" x2="${W - padX}" y2="${ys(intrinsic).toFixed(1)}" stroke="var(--muted)" stroke-width="1" stroke-dasharray="4 4" opacity="0.6"/>` : "";
  const gid = "g" + Math.random().toString(36).slice(2, 7);
  host.innerHTML = `<svg class="chart" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <defs><linearGradient id="${gid}" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0" stop-color="${col}" stop-opacity="0.25"/><stop offset="1" stop-color="${col}" stop-opacity="0"/></linearGradient></defs>
    <path d="${area}" fill="url(#${gid})"/>${ivl}
    <path d="${line}" fill="none" stroke="${col}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>
    <div class="anchor" hidden><div class="cvline"></div><div class="cdot"></div></div>
    <div class="cross" hidden><div class="cvline"></div><div class="cdot"></div></div>`;

  const svg = host.querySelector("svg");
  const cross = host.querySelector(".cross"), vline = cross.querySelector(".cvline"), dot = cross.querySelector(".cdot");
  const anc = host.querySelector(".anchor"), aline = anc.querySelector(".cvline"), adot = anc.querySelector(".cdot");
  dot.style.background = col;

  const out = (price, chg, dateLabel) => {
    readout.price.textContent = usd(price);
    readout.chg.textContent = `${chg >= 0 ? "+" : ""}${(chg * 100).toFixed(2)}%`;
    readout.chg.className = "chg " + (chg >= 0 ? "pos" : "neg");
    readout.date.textContent = dateLabel;
  };
  const place = (lineEl, dotEl, i, r) => {
    const px = (xs(i) / W) * r.width, py = (ys(data[i][1]) / H) * r.height;
    lineEl.style.left = px + "px"; dotEl.style.left = px + "px"; dotEl.style.top = py + "px";
  };
  const base = () => out(last, (last - first) / first, label);
  base();

  const idxAt = clientX => {
    const r = host.getBoundingClientRect();
    let f = (clientX - r.left) / r.width; f = Math.max(0, Math.min(1, f));
    return { i: Math.round(f * (data.length - 1)), r };
  };
  let anchorIdx = null;
  const render = (a, b, r) => {
    cross.hidden = false; place(vline, dot, b, r);
    if (a != null && a !== b) {                          // span selection
      anc.hidden = false; place(aline, adot, a, r);
      out(data[b][1], (data[b][1] - data[a][1]) / data[a][1],
          `${fmtDate(data[a][0])} → ${fmtDate(data[b][0])}`);
    } else {                                             // single point
      anc.hidden = true;
      out(data[b][1], (data[b][1] - first) / first, fmtDate(data[b][0]));
    }
  };
  const end = () => { cross.hidden = true; anc.hidden = true; anchorIdx = null; base(); };

  svg.addEventListener("pointerdown", e => {
    const { i, r } = idxAt(e.clientX); anchorIdx = i;
    try { svg.setPointerCapture(e.pointerId); } catch (_) {}
    render(i, i, r); e.preventDefault();
  });
  svg.addEventListener("pointermove", e => {
    const { i, r } = idxAt(e.clientX);
    if (anchorIdx != null) render(anchorIdx, i, r);
    else if (e.pointerType === "mouse") render(null, i, r);
  });
  svg.addEventListener("pointerup", end);
  svg.addEventListener("pointercancel", end);
  svg.addEventListener("pointerleave", () => { if (anchorIdx == null) end(); });
}

/* ---------- views ---------- */
function stockCard(p) {
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
}
function etfCard(e) {
  return `
    <button class="card" onclick="location.hash='#/${encodeURIComponent(e.ticker)}'">
      <div class="id"><div class="tk">${esc(e.ticker)}</div>
        <div class="nm">${esc(e.name)}</div></div>
      ${sparkline(e.history || [])}
      <div class="rt"><div class="px">${usd(e.price)}</div>
        <div class="up neg">▼ ${Math.abs(Math.round((e.drawdown || 0) * 100))}% off high</div></div>
    </button>`;
}
function renderHome() {
  const sub = DATA.price_as_of
    ? `Prices ${DATA.price_as_of} · analysis ${DATA.as_of}`
    : (DATA.as_of ? `Updated ${DATA.as_of}` : "");
  const tabs = `<div class="tabs-home">
    <button class="htab ${homeTab === "stocks" ? "active" : ""}" data-tab="stocks">Stocks</button>
    <button class="htab ${homeTab === "etfs" ? "active" : ""}" data-tab="etfs">ETFs</button></div>`;

  let body;
  if (homeTab === "stocks") {
    body = DATA.picks.length
      ? `<div class="list">${DATA.picks.map(stockCard).join("")}</div>`
      : `<div class="empty"><div class="dot">🟢</div><div class="big">Nothing today</div>
         <div>No strong company pulled back on sentiment while staying at/below fair
         value. The screen ran fine — it's just being patient.</div></div>`;
  } else {
    body = (DATA.etfs || []).length
      ? `<div class="list">${DATA.etfs.map(etfCard).join("")}</div>`
      : `<div class="empty"><div class="dot">🟢</div><div class="big">No ETF dips today</div>
         <div>No quality ETF has pulled back within its uptrend right now.</div></div>`;
  }
  root.innerHTML = `<div class="title-lg">Quality Dips</div><div class="sub">${sub}</div>
    ${tabs}${body}`;
  root.querySelectorAll(".htab").forEach(b =>
    b.addEventListener("click", () => { homeTab = b.dataset.tab; renderHome(); }));
}

function acc(title, body, open) {
  return `<details class="acc"${open ? " open" : ""}>
    <summary>${title}<span class="chev">›</span></summary>
    <div class="acc-body">${body}</div></details>`;
}

function mountDetailChart(p) {
  const ranges = ["1D", "1W", "1M", "6M", "1Y", "All"];
  const id = p.intraday || {};
  const seriesFor = r => {
    if (r === "1D") return [id.day, "Today"];
    if (r === "1W") return [id.week, "Past week"];
    if (r === "1M") return [id.month, "Past month"];
    const days = { "6M": 182, "1Y": 365, "All": 0 }[r];
    return [sliceDays(p.history || [], days),
            { "6M": "Past 6 months", "1Y": "Past year", "All": "All time" }[r]];
  };
  const fb = { "1D": 5, "1W": 7, "1M": 30 };
  const rEl = document.getElementById("ranges"), cEl = document.getElementById("chart");
  const readout = { price: document.getElementById("cprice"),
    chg: document.getElementById("cchg"), date: document.getElementById("cdate") };
  let active = "1D";
  const draw = () => {
    let [data, label] = seriesFor(active);
    if (!data || data.length < 2) data = sliceDays(p.history || [], fb[active] || 30);
    mountChart(cEl, readout, data, label, p.intrinsic);
    rEl.innerHTML = ranges.map(l =>
      `<button class="range ${l === active ? "active" : ""}" data-r="${l}">${l}</button>`).join("");
    rEl.querySelectorAll(".range").forEach(b =>
      b.addEventListener("click", () => { active = b.dataset.r; draw(); }));
  };
  draw();
}

function renderEtfDetail(e) {
  const statsGrid = (e.stats || []).map(s =>
    `<div class="stat"><div class="l">${esc(s.label)}</div><div class="v">${esc(s.value)}</div></div>`).join("");
  root.innerHTML = `
    <div class="nav"><button class="back" onclick="location.hash=''">
      <svg viewBox="0 0 12 20"><path d="M10 2 2 10l8 8" fill="none" stroke="currentColor"
        stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>Quality Dips</button></div>
    <div class="dh">
      <div class="nm">${esc(e.name)} · ETF</div>
      <div class="price">${usd(e.price)}</div>
      <div class="row"><span class="up neg">▼ ${Math.abs(Math.round((e.drawdown || 0) * 100))}% from 52-wk high</span>
        <span class="pill">${esc(e.category || "ETF")}</span></div>
    </div>
    ${e.thesis ? `<div class="thesis">${esc(e.thesis)}</div>` : ""}
    <div class="chartread"><span class="cprice" id="cprice"></span>
      <span class="chg" id="cchg"></span><span class="cdate" id="cdate"></span></div>
    <div class="chart-wrap"><div id="chart"></div></div>
    <div class="ranges" id="ranges"></div>
    <div class="chart-note">drag to scrub · hold & drag to measure a span · prices ${DATA.price_as_of || DATA.as_of}</div>
    <div class="sec"><h3>Fund facts</h3><div class="grid">${statsGrid}</div></div>
    <footer>ETFs are screened on trend + pullback, not DCF (a fund has no earnings).
      Mechanical model output — not investment advice.</footer>`;
  mountDetailChart(e);
}

function renderDetail(p) {
  if (p.is_etf) { renderEtfDetail(p); return; }
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
        stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>Quality Dips</button></div>
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

  // chart + range toggles — granular intraday for 1D/1W/1M, daily for longer
  const ranges = ["1D", "1W", "1M", "6M", "1Y", "All"];
  const id = p.intraday || {};
  const seriesFor = r => {
    if (r === "1D") return [id.day, "Today"];
    if (r === "1W") return [id.week, "Past week"];
    if (r === "1M") return [id.month, "Past month"];
    const days = { "6M": 182, "1Y": 365, "All": 0 }[r];
    const lab = { "6M": "Past 6 months", "1Y": "Past year", "All": "All time" }[r];
    return [sliceDays(p.history || [], days), lab];
  };
  const fallbackDays = { "1D": 5, "1W": 7, "1M": 30 };
  const rEl = document.getElementById("ranges");
  const cEl = document.getElementById("chart");
  const readout = {
    price: document.getElementById("cprice"),
    chg: document.getElementById("cchg"),
    date: document.getElementById("cdate"),
  };
  let active = "1D";
  const draw = () => {
    let [data, label] = seriesFor(active);
    if (!data || data.length < 2) {            // intraday missing -> daily fallback
      data = sliceDays(p.history || [], fallbackDays[active] || 30);
    }
    mountChart(cEl, readout, data, label, p.intrinsic);
    rEl.innerHTML = ranges.map(lab =>
      `<button class="range ${lab === active ? "active" : ""}" data-r="${lab}">${lab}</button>`).join("");
    rEl.querySelectorAll(".range").forEach(b =>
      b.addEventListener("click", () => { active = b.dataset.r; draw(); }));
  };
  draw();
}

window.addEventListener("hashchange", route);
load();
