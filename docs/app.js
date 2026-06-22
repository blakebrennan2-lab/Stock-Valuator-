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
function chart(hist, days, intrinsic) {
  const seg = sliceDays(hist, days);
  const data = seg.map(p => p[1]);
  if (data.length < 2) return `<div class="chart-note">No chart data.</div>`;
  const w = 360, h = 220, padX = 6, padT = 14, padB = 18;
  const pricesLo = Math.min(...data), pricesHi = Math.max(...data);
  // include intrinsic so the dashed fair-value line is visible (caps squash).
  const lo = Math.min(pricesLo, intrinsic ?? pricesLo);
  const hi = Math.max(pricesHi, intrinsic ?? pricesHi);
  const xs = i => padX + (w - 2 * padX) * i / (data.length - 1);
  const ys = v => padT + (h - padT - padB) * (1 - (hi === lo ? .5 : (v - lo) / (hi - lo)));
  const up = data[data.length - 1] >= data[0];
  const col = up ? "var(--green)" : "var(--red)";
  const pts = data.map((v, i) => [xs(i), ys(v)]);
  const line = smooth(pts);
  const area = `${line} L${xs(data.length - 1).toFixed(1)},${h - padB} L${padX},${h - padB} Z`;
  const ivLine = intrinsic != null ? `
    <line x1="${padX}" y1="${ys(intrinsic).toFixed(1)}" x2="${w - padX}" y2="${ys(intrinsic).toFixed(1)}"
      stroke="var(--muted)" stroke-width="1" stroke-dasharray="4 4" opacity="0.7"/>
    <text x="${w - padX}" y="${(ys(intrinsic) - 4).toFixed(1)}" text-anchor="end"
      fill="var(--muted)" font-size="10">fair value ${usd(intrinsic)}</text>` : "";
  const gid = "g" + Math.random().toString(36).slice(2, 7);
  return `<svg class="chart" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <defs><linearGradient id="${gid}" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0" stop-color="${col}" stop-opacity="0.28"/>
      <stop offset="1" stop-color="${col}" stop-opacity="0"/></linearGradient></defs>
    <path d="${area}" fill="url(#${gid})"/>
    ${ivLine}
    <path d="${line}" fill="none" stroke="${col}" stroke-width="2.2"
      stroke-linecap="round" stroke-linejoin="round"/></svg>`;
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
  const cards = DATA.picks.map(p => `
    <button class="card" onclick="location.hash='#/${encodeURIComponent(p.ticker)}'">
      <div class="id"><div class="tk">${esc(p.ticker)}</div>
        <div class="nm">${esc(p.name)}</div></div>
      ${sparkline(p.history || [])}
      <div class="rt"><div class="px">${usd(p.price)}</div>
        <div class="up ${p.upside >= 0 ? "pos" : "neg"}">${pct(p.upside)}</div></div>
    </button>`).join("");
  root.innerHTML = `<div class="title-lg">Strong Buys</div>
    <div class="sub">${sub}</div><div class="list">${cards}</div>`;
}

function renderDetail(p) {
  const stats = (p.stats || []).map(s =>
    `<div class="stat"><div class="l">${esc(s.label)}</div><div class="v">${esc(s.value)}</div></div>`).join("");
  const why = (p.why || []).map(t => `<li>${esc(t)}</li>`).join("");
  const risks = (p.risks || []).map(t => `<li>${esc(t)}</li>`).join("");
  const profile = (p.profile || []).map(t => `<li>${esc(t)}</li>`).join("");
  const news = (p.news || []).slice(0, 3).map(n =>
    `<li>${esc(n.title)} <span class="nm">(${esc([n.publisher, n.date].filter(Boolean).join(" · "))})</span></li>`).join("");

  root.innerHTML = `
    <div class="nav"><button class="back" onclick="location.hash=''">
      <svg viewBox="0 0 12 20"><path d="M10 2 2 10l8 8" fill="none" stroke="currentColor"
        stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>Strong Buys</button></div>
    <div class="dh">
      <div class="nm">${esc(p.name)}</div>
      <div class="price">${usd(p.price)}</div>
      <div class="row">
        <span class="iv">Fair value ${usd(p.intrinsic)}</span>
        <span class="up ${p.upside >= 0 ? "pos" : "neg"}">${pct(p.upside)} upside</span>
        <span class="pill">${esc(p.confidence)} confidence</span>
      </div>
    </div>
    <div class="chart-wrap"><div id="chart"></div></div>
    <div class="ranges" id="ranges"></div>
    <div class="chart-note">prices ${DATA.price_as_of || DATA.as_of} · analysis ${DATA.as_of}</div>

    <div class="sec"><h3>Key stats</h3><div class="grid">${stats}</div></div>
    <div class="sec"><h3>Why it's a buy</h3><div class="panel"><ul class="bullets good">${why}</ul></div></div>
    <div class="sec"><h3>Risks</h3><div class="panel"><ul class="bullets risk">${risks}</ul></div></div>
    ${profile ? `<div class="sec"><h3>Quality profile</h3><div class="panel"><ul class="bullets good">${profile}</ul></div></div>` : ""}
    ${news ? `<div class="sec"><h3>Recent news</h3><div class="panel"><ul class="bullets">${news}</ul></div></div>` : ""}

    <div class="sec"><h3>Valuation breakdown</h3>
      ${modelBlock("DCF — discounted cash flow", p.dcf_html)}
      ${modelBlock("DDM — dividend discount", p.ddm_html)}
      ${modelBlock("Comps — peer multiples", p.comps_html)}
    </div>
    <footer>Mechanical model output — not investment advice or legal due diligence.</footer>`;

  // chart + range toggles
  const ranges = [["1W", 7], ["1M", 30], ["6M", 182], ["1Y", 365], ["All", null]];
  const rEl = document.getElementById("ranges");
  const cEl = document.getElementById("chart");
  let active = "6M";
  const draw = () => {
    const days = ranges.find(r => r[0] === active)[1];
    cEl.innerHTML = chart(p.history || [], days, p.intrinsic);
    rEl.innerHTML = ranges.map(([lab]) =>
      `<button class="range ${lab === active ? "active" : ""}" data-r="${lab}">${lab}</button>`).join("");
    rEl.querySelectorAll(".range").forEach(b =>
      b.addEventListener("click", () => { active = b.dataset.r; draw(); }));
  };
  draw();
}
function modelBlock(title, html) {
  return `<details class="model"><summary>${title}<span class="chev">›</span></summary>
    <div class="body">${html || "<p class='na'>not available</p>"}</div></details>`;
}

window.addEventListener("hashchange", route);
load();
