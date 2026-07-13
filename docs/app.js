"use strict";

const root = document.getElementById("app");
let DATA = { as_of: "", count: 0, picks: [], etfs: [] };
let homeTab = "stocks";   // "stocks" | "etfs"
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ---------- motion helpers ---------- */
// Eased count-up on a key figure; always lands on the exact final string.
function countUp(el, target, fmt, dur = 700) {
  if (!el || target == null) return;
  if (reduceMotion) { el.textContent = fmt(target); return; }
  const t0 = performance.now(), from = target * 0.92;
  const tick = now => {
    const p = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - p, 3);
    el.textContent = fmt(from + (target - from) * e);
    if (p < 1) requestAnimationFrame(tick); else el.textContent = fmt(target);
  };
  requestAnimationFrame(tick);
}
// Eased accordion expand/collapse on native <details>.
function animateAccordions(scope) {
  scope.querySelectorAll("details.acc").forEach(d => {
    const sum = d.querySelector("summary"), body = d.querySelector(".acc-body");
    if (!sum || !body) return;
    sum.addEventListener("click", e => {
      if (reduceMotion || !body.animate) return;   // native toggle
      e.preventDefault();
      body.style.overflow = "hidden";
      if (d.open) {
        const a = body.animate(
          [{ height: body.offsetHeight + "px", opacity: 1 }, { height: "0px", opacity: 0 }],
          { duration: 240, easing: "cubic-bezier(.4,0,.2,1)" });
        a.onfinish = () => { d.open = false; body.style.overflow = ""; };
      } else {
        d.open = true;
        const a = body.animate(
          [{ height: "0px", opacity: 0 }, { height: body.offsetHeight + "px", opacity: 1 }],
          { duration: 300, easing: "cubic-bezier(.4,0,.2,1)" });
        a.onfinish = () => { body.style.overflow = ""; };
      }
    });
  });
}

/* ---------- news (live-first, honest fallback) ---------- */
// Real headlines only, straight from Yahoo's feed via a CORS relay. If the
// relay is down we fall back to the headlines baked at the last hourly
// refresh; if there are none, we say so. Nothing is ever generated.
async function fetchLiveNews(tk) {
  const y = `https://query1.finance.yahoo.com/v1/finance/search?q=${encodeURIComponent(tk)}&newsCount=10&quotesCount=0`;
  const ctl = new AbortController();
  const to = setTimeout(() => ctl.abort(), 6000);
  try {
    const r = await fetch("https://corsproxy.io/?url=" + encodeURIComponent(y),
                          { signal: ctl.signal });
    const j = await r.json();
    clearTimeout(to);
    return (j.news || [])
      .filter(n => n.title)
      .map(n => ({ title: n.title, publisher: n.publisher || "", link: n.link || "",
                   ts: n.providerPublishTime || null,
                   // Yahoo lists the article's true subject first — the story
                   // is primarily about this name only when it leads that list.
                   primary: (n.relatedTickers || [tk])[0] === tk,
                   date: n.providerPublishTime
                     ? new Date(n.providerPublishTime * 1000).toISOString().slice(0, 10) : "" }))
      .sort((a, b) => (b.primary ? 1 : 0) - (a.primary ? 1 : 0));
  } catch (e) { clearTimeout(to); return null; }   // null = live feed unreachable
}
function relTime(n) {
  const d = n.ts ? new Date(n.ts * 1000) : (n.date ? new Date(n.date + "T12:00:00") : null);
  if (!d || isNaN(d)) return "";
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 3600) return Math.max(1, Math.round(s / 60)) + "m ago";
  if (s < 86400) return Math.round(s / 3600) + "h ago";
  if (s < 86400 * 8) return Math.round(s / 86400) + "d ago";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}
function newsRow(n, extra = "") {
  const meta = [esc(n.publisher), relTime(n)].filter(Boolean).join(" · ");
  const inner = `<div class="nsrc">${meta}${extra}</div><div class="nti">${esc(n.title)}</div>`;
  return /^https?:\/\//.test(n.link)
    ? `<a class="news" href="${esc(n.link)}" target="_blank" rel="noopener">${inner}<span class="ngo">›</span></a>`
    : `<div class="news">${inner}</div>`;
}
// Pair the recent move with the headlines around it — context, never causation.
function renderDipContext(host, p, items) {
  if (!host) return;
  const hist = p.history || [];
  if (hist.length < 20) { host.innerHTML = ""; return; }
  const win = hist.slice(-180);
  let hiI = 0;
  win.forEach((d, i) => { if (d[1] > win[hiI][1]) hiI = i; });
  const cur = win[win.length - 1][1], hi = win[hiI][1], dd = cur / hi - 1;
  if (dd > -0.03) { host.innerHTML = ""; return; }   // no meaningful recent dip
  const hiDate = win[hiI][0];
  // Prefer stories actually about this name (leads Yahoo's ticker list, or the
  // company/ticker appears in the headline); fall back to any dated coverage.
  const nameKey = (p.name || "").split(/[\s-]/)[0].toLowerCase();
  const isAbout = n => n.primary === true
    || (nameKey.length > 2 && n.title.toLowerCase().includes(nameKey))
    || n.title.toUpperCase().includes(p.ticker);
  const dated = (items || []).filter(n => n.date && n.date >= hiDate);
  const strict = dated.filter(isAbout);
  const around = (strict.length ? strict : dated).slice(0, 3);
  const byDate = new Map(hist.map((d, i) => [d[0], i]));
  const badge = n => {
    const i = byDate.get(n.date);
    if (i == null || i === 0) return "";
    const chg = hist[i][1] / hist[i - 1][1] - 1;
    return ` · <span class="${chg >= 0 ? "pos" : "neg"}">${(chg >= 0 ? "+" : "")}${(chg * 100).toFixed(1)}% that day</span>`;
  };
  host.innerHTML = `<div class="dipx">
    <div class="dxk">The dip in context</div>
    <div class="dxline">Down <b>${Math.abs(dd * 100).toFixed(0)}%</b> since ${fmtDate(hiDate)}.</div>
    ${around.length ? around.map(n => newsRow(n, badge(n))).join("")
      : `<div class="dxnone">No headlines dated since the pre-dip high — often a sign
         the move is sentiment rather than news. Verify before buying.</div>`}
    <div class="dxcap">Headlines shown for context around the move — not a claim of cause.</div>
  </div>`;
}
async function initNews(p) {
  const list = document.getElementById("nlist");
  const note = document.getElementById("nnote");
  const dip = document.getElementById("dipctx");
  if (!list) return;
  let items = await fetchLiveNews(p.ticker);
  const live = !!(items && items.length);
  if (!live) items = (p.news || []).map(n => ({ title: n.title, publisher: n.publisher || "",
      ts: null, date: n.date || "", link: n.link || "" }));
  if (!location.hash.includes(p.ticker)) return;   // user navigated away mid-fetch
  if (items.length) {
    const first = items.slice(0, 3), rest = items.slice(3, 8);
    list.innerHTML = first.map(n => newsRow(n)).join("")
      + (rest.length ? `<button class="morebtn" id="nmore">More news (${rest.length})</button>` : "");
    const mb = document.getElementById("nmore");
    if (mb) mb.addEventListener("click", () => {
      mb.outerHTML = rest.map(n => newsRow(n)).join("");
    });
    note.textContent = live
      ? "Live headlines via Yahoo Finance — tap to read the source."
      : "Headlines from the last data refresh (live feed unreachable).";
  } else {
    list.innerHTML = `<div class="nempty">No recent news for ${esc(p.ticker)} — a quiet tape.</div>`;
    note.textContent = "";
  }
  renderDipContext(dip, p, items);
}

/* ---------- data ---------- */
function skeletonHome() {
  const card = `<div class="sk-card"><div style="flex:1">
      <div class="sk a"></div><div class="sk b"></div></div><div class="sk c"></div></div>`;
  root.innerHTML = `
    <header class="mast"><div class="kicker">Daily Value Screen</div>
      <h1 class="title-lg">Quality Dips</h1><div class="rule"></div>
      <div class="sub">&nbsp;</div></header>
    <div class="tabs-home"><button class="htab active">Stocks</button>
      <button class="htab">ETFs</button></div>
    <div class="list">${card.repeat(3)}</div>`;
}
async function load() {
  skeletonHome();
  try {
    const r = await fetch("results.json?t=" + Date.now(), { cache: "no-store" });
    DATA = await r.json();
  } catch (e) {
    root.innerHTML = `<div class="empty">
      <div class="big">Couldn't load data</div>
      <div>Check your connection, or check back after the next refresh.</div>
      <button class="retry" onclick="load()">Try again</button></div>`;
    return;
  }
  route();
}
function route() {
  const render = () => {
    const tk = decodeURIComponent(location.hash.replace(/^#\/?/, ""));
    const p = [...(DATA.picks || []), ...(DATA.etfs || [])].find(x => x.ticker === tk);
    p ? renderDetail(p) : renderHome();
    window.scrollTo(0, 0);
  };
  // Smooth list <-> detail crossfade where the browser supports it.
  if (document.startViewTransition && !reduceMotion) document.startViewTransition(render);
  else render();
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
  const ivl = intrinsic != null ? `<line x1="${padX}" y1="${ys(intrinsic).toFixed(1)}" x2="${W - padX}" y2="${ys(intrinsic).toFixed(1)}" stroke="var(--accent)" stroke-width="1.2" stroke-dasharray="5 4" opacity="0.75"/>` : "";
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

  // Draw-in: the price line traces itself, the fill fades up behind it.
  if (!reduceMotion) {
    const stroke = svg.querySelector("path:last-of-type");
    const fill = svg.querySelector("path:first-of-type");
    try {
      const L = stroke.getTotalLength();
      stroke.style.strokeDasharray = L; stroke.style.strokeDashoffset = L;
      fill.style.opacity = "0";
      requestAnimationFrame(() => {
        stroke.style.transition = "stroke-dashoffset .55s cubic-bezier(.3,.6,.3,1)";
        fill.style.transition = "opacity .45s ease .2s";
        stroke.style.strokeDashoffset = "0"; fill.style.opacity = "1";
      });
    } catch (e) { /* older engines: draw instantly */ }
  }

  const out = (price, chg, dateLabel) => {
    readout.price.textContent = usd(price);
    readout.chg.textContent = `${chg >= 0 ? "+" : ""}${(chg * 100).toFixed(2)}%`;
    readout.chg.className = "chg " + (chg >= 0 ? "pos" : "neg");
    readout.date.textContent = dateLabel;
  };
  const place = (lineEl, dotEl, i) => {
    const r = host.getBoundingClientRect();
    const px = (xs(i) / W) * r.width, py = (ys(data[i][1]) / H) * r.height;
    lineEl.style.left = px + "px"; dotEl.style.left = px + "px"; dotEl.style.top = py + "px";
  };
  const base = () => out(last, (last - first) / first, label);
  base();

  const idxAt = clientX => {
    const r = host.getBoundingClientRect();
    let f = (clientX - r.left) / r.width; f = Math.max(0, Math.min(1, f));
    return Math.round(f * (data.length - 1));
  };
  // One point: price + % vs range start. Two points: % between them.
  const showOne = i => {
    cross.hidden = false; anc.hidden = true; place(vline, dot, i);
    out(data[i][1], (data[i][1] - first) / first, fmtDate(data[i][0]));
  };
  const showTwo = (i, j) => {
    const a = Math.min(i, j), b = Math.max(i, j);
    cross.hidden = false; anc.hidden = false;
    place(aline, adot, a); place(vline, dot, b);
    out(data[b][1], (data[b][1] - data[a][1]) / data[a][1],
        `${fmtDate(data[a][0])} → ${fmtDate(data[b][0])}`);
  };
  const reset = () => { cross.hidden = true; anc.hidden = true; base(); };

  // Touch: read ALL active fingers each event -> smooth 1-finger scrub, and a
  // 2nd finger anywhere instantly compares the two points (Apple Stocks style).
  const onTouch = e => {
    e.preventDefault();                                   // own the gesture (no scroll/stick)
    const t = e.touches;
    if (t.length >= 2) showTwo(idxAt(t[0].clientX), idxAt(t[1].clientX));
    else if (t.length === 1) showOne(idxAt(t[0].clientX));
  };
  host.addEventListener("touchstart", onTouch, { passive: false });
  host.addEventListener("touchmove", onTouch, { passive: false });
  host.addEventListener("touchend", e => {
    e.preventDefault();
    if (e.touches.length === 1) showOne(idxAt(e.touches[0].clientX));
    else if (e.touches.length === 0) reset();
  }, { passive: false });
  host.addEventListener("touchcancel", reset);
  // Mouse (desktop): hover scrubs a single point.
  host.addEventListener("mousemove", e => showOne(idxAt(e.clientX)));
  host.addEventListener("mouseleave", reset);
}

/* ---------- views ---------- */
function stockRow(p, i) {
  const low = p.confidence === "low";
  return `
    <button class="row" style="animation-delay:${45 * (i + 1)}ms"
      onclick="location.hash='#/${encodeURIComponent(p.ticker)}'">
      <div class="id"><div class="tk">${esc(p.ticker)}</div>
        <div class="nm">${esc(p.name)}</div></div>
      ${sparkline(p.history || [])}
      <div class="rt"><div class="px">${usd(p.price)}</div>
        ${low ? '<span class="chip warn">wide range</span>'
              : `<span class="chip ${p.upside >= 0 ? "pos" : "neg"}">${pct(p.upside)}</span>`}</div>
    </button>`;
}
// Hero: today's #1 pick gets the front page, not a whisper in a list.
function heroSpark(hist) {
  const data = sliceDays(hist || [], 90);
  if (data.length < 2) return "";
  const w = 340, h = 92, pad = 4;
  const vals = data.map(d => d[1]);
  const lo = Math.min(...vals), hi = Math.max(...vals);
  const xs = i => pad + (w - 2 * pad) * i / (vals.length - 1);
  const ys = v => pad + (h - 2 * pad) * (1 - (hi === lo ? .5 : (v - lo) / (hi - lo)));
  const col = vals[vals.length - 1] >= vals[0] ? "var(--green)" : "var(--red)";
  const line = smooth(vals.map((v, i) => [xs(i), ys(v)]));
  return `<svg class="hspark" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <defs><linearGradient id="hg" x1="0" x2="0" y1="0" y2="1">
      <stop offset="0" stop-color="${col}" stop-opacity="0.22"/>
      <stop offset="1" stop-color="${col}" stop-opacity="0"/></linearGradient></defs>
    <path d="${line} L${xs(vals.length - 1).toFixed(1)},${h - pad} L${pad},${h - pad} Z" fill="url(#hg)"/>
    <path d="${line}" fill="none" stroke="${col}" stroke-width="2"
      stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}
function heroCard(p) {
  const low = p.confidence === "low";
  const why = (p.thesis || "").split(". ")[0];
  const verdict = low
    ? `<span class="chip warn">wide range ${usd(p.range_low)}–${usd(p.range_high)}</span>`
    : `Worth <b>${usd(p.intrinsic)}</b>
       <span class="chip ${p.upside >= 0 ? "pos" : "neg"}">${pct(p.upside)}</span>
       <span class="hconf">${esc(p.confidence)} confidence</span>`;
  return `
    <button class="hero" onclick="location.hash='#/${encodeURIComponent(p.ticker)}'">
      <div class="hk">Top pick today</div>
      <div class="hrow"><div>
          <div class="htk">${esc(p.ticker)}</div>
          <div class="hnm">${esc(p.name)}</div></div>
        <div class="hpx">${usd(p.price)}</div></div>
      ${heroSpark(p.history)}
      <div class="hverdict">${verdict}</div>
      ${why ? `<div class="hwhy">${esc(why)}.</div>` : ""}
    </button>`;
}
// Editorial "patience" illustration: the price line dips and recovers.
const dipArt = `<svg class="dipart" viewBox="0 0 210 86" aria-hidden="true">
  <line x1="8" y1="78" x2="202" y2="78" stroke="var(--line-strong)" stroke-width="1"/>
  <path d="M8 30 C 46 24, 68 30, 92 56 C 101 66 110 68 119 60 C 142 40 170 22 202 16"
        fill="none" stroke="var(--muted)" stroke-width="2.5" stroke-linecap="round"/>
  <circle cx="105" cy="63" r="7" fill="var(--accent)"/>
</svg>`;
function etfRow(e, i) {
  return `
    <button class="row" style="animation-delay:${45 * (i + 1)}ms"
      onclick="location.hash='#/${encodeURIComponent(e.ticker)}'">
      <div class="id"><div class="tk">${esc(e.ticker)}</div>
        <div class="nm">${esc(e.name)}</div></div>
      ${sparkline(e.history || [])}
      <div class="rt"><div class="px">${usd(e.price)}</div>
        <span class="chip neg">▼${Math.abs(Math.round((e.drawdown || 0) * 100))}% off high</span></div>
    </button>`;
}
// "Prices 2026-07-13 22:14Z" -> live freshness ("14m ago") + pulse when recent.
function freshness() {
  const raw = DATA.price_as_of || "";
  const d = new Date(raw.replace(" ", "T").replace("Z", ":00Z"));
  if (isNaN(d)) return { text: DATA.as_of ? `Updated ${DATA.as_of}` : "", live: false };
  const mins = Math.round((Date.now() - d.getTime()) / 60000);
  const text = mins < 2 ? "Prices updated just now"
    : mins < 90 ? `Prices updated ${mins}m ago`
    : mins < 60 * 36 ? `Prices updated ${Math.round(mins / 60)}h ago`
    : `Prices as of ${raw}`;
  return { text: `${text} · analysis ${DATA.as_of}`, live: mins < 90 };
}
function renderHome() {
  const f = freshness();
  const d = new Date((DATA.as_of || "") + "T12:00:00");
  const dateStr = isNaN(d) ? "" : " · " + d.toLocaleDateString(undefined,
    { weekday: "short", month: "short", day: "numeric" });
  const tabs = `<div class="tabs-home" role="tablist">
    <button class="htab ${homeTab === "stocks" ? "active" : ""}" data-tab="stocks"
      role="tab" aria-selected="${homeTab === "stocks"}">Stocks</button>
    <button class="htab ${homeTab === "etfs" ? "active" : ""}" data-tab="etfs"
      role="tab" aria-selected="${homeTab === "etfs"}">ETFs</button></div>`;

  let body;
  if (homeTab === "stocks") {
    const picks = DATA.picks || [];
    if (picks.length) {
      const rest = picks.slice(1);
      body = heroCard(picks[0])
        + (rest.length
          ? `<div class="curated">Also cleared all seven gates today:</div>
             <div class="list">${rest.map(stockRow).join("")}</div>`
          : "")
        + `<div class="meta-strip">S&amp;P 500 · 7 quality gates · valued 3 ways · refreshed hourly</div>`;
    } else {
      body = `<div class="empty">${dipArt}
         <div class="big">Nothing worth buying today.</div>
         <div>No strong company pulled back on sentiment while staying at/below fair
         value. The screen ran fine — it's just being patient so you don't overpay.</div></div>`;
    }
  } else {
    const etfs = DATA.etfs || [];
    body = etfs.length
      ? `<div class="curated">Quality funds in a pullback — <b>${etfs.length}</b> today.</div>
         <div class="list">${etfs.map(etfRow).join("")}</div>
         <div class="meta-strip">Screened on trend + pullback · funds have no earnings to value</div>`
      : `<div class="empty">${dipArt}
         <div class="big">No ETF dips today.</div>
         <div>No quality ETF has pulled back within its uptrend right now.</div></div>`;
  }
  root.innerHTML = `
    <header class="mast"><div class="kicker">Daily Value Screen${dateStr}</div>
      <h1 class="title-lg">Quality Dips</h1><div class="rule"></div>
      <div class="sub">${f.live ? '<span class="livedot"></span>' : ""}${f.text}</div></header>
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
  const readout = { price: document.getElementById("dprice"),
    chg: document.getElementById("dchg"), date: document.getElementById("ddate") };
  let active = "1D";
  const draw = () => {
    let [data, label] = seriesFor(active);
    if (!data || data.length < 2) data = sliceDays(p.history || [], fb[active] || 30);
    mountChart(cEl, readout, data, label, p.intrinsic);
    rEl.innerHTML = ranges.map(l =>
      `<button class="range ${l === active ? "active" : ""}" data-r="${l}"
        aria-pressed="${l === active}">${l}</button>`).join("");
    rEl.querySelectorAll(".range").forEach(b =>
      b.addEventListener("click", () => { active = b.dataset.r; draw(); }));
  };
  draw();
}

function renderEtfDetail(e) {
  const statsGrid = (e.stats || []).map(s =>
    `<div class="stat"><div class="l">${esc(s.label)}</div><div class="v">${esc(s.value)}</div></div>`).join("");
  root.innerHTML = `
    <div class="nav"><button class="back" onclick="location.hash=''" aria-label="Back to list">
      <svg viewBox="0 0 12 20"><path d="M10 2 2 10l8 8" fill="none" stroke="currentColor"
        stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>Quality Dips</button></div>
    <div class="dh">
      <div class="nm"><b>${esc(e.ticker)}</b> · ${esc(e.name)} · ETF</div>
      <div class="price" id="dprice">${usd(e.price)}</div>
      <div class="chgline"><span class="chg" id="dchg"></span>
        <span class="cdate" id="ddate"></span></div>
      <div class="verdict"><span class="chip neg">▼${Math.abs(Math.round((e.drawdown || 0) * 100))}% from 52-wk high</span>
        <span class="pill">${esc(e.category || "ETF")}</span></div>
    </div>
    ${e.thesis ? `<div class="thesis">${esc(e.thesis)}</div>` : ""}
    <div class="chart-wrap"><div id="chart"></div></div>
    <div class="ranges" id="ranges"></div>
    <div class="chart-note">one finger scrubs · add a second to measure</div>
    <div class="sec"><h3>Fund facts</h3><div class="grid">${statsGrid}</div></div>
    <footer>ETFs are screened on trend + pullback, not DCF (a fund has no earnings).</footer>`;
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
  const statCell = s =>
    `<div class="stat"><div class="l">${esc(s.label)}</div>
     <div class="v${s.value === "not available" ? " na" : ""}">${esc(s.value)}</div>
     ${s.src ? `<div class="s">${esc(s.src)}</div>` : ""}</div>`;
  const health = (p.health || []).map(statCell).join("");
  const analyst = (p.analyst || []).map(statCell).join("");
  const capital = (p.capital || []).map(t => `<li>${esc(t)}</li>`).join("");
  const mind = (p.change_mind || []).map(t => `<li>${esc(t)}</li>`).join("");
  const manual = (p.manual || []).map(t => `<li>${esc(t)}</li>`).join("");

  // verdict — one compact line: worth · upside · confidence (honesty intact)
  const header = low
    ? `<div class="verdict">Fair value <b>${usd(p.range_low)}–${usd(p.range_high)}</b>
         <span class="pill" style="color:var(--amber);border-color:rgba(217,176,79,.45);background:rgba(217,176,79,.08)">low confidence</span></div>
       <div class="lowbanner">⚠ The models disagree — treat the value as a wide range, not a target.</div>`
    : `<div class="verdict">Worth <b id="dfv">${usd(p.intrinsic)}</b>
         <span class="up ${p.upside >= 0 ? "pos" : "neg"}" id="dup">${pct(p.upside)}</span>
         <span class="pill">${esc(p.confidence)} confidence</span></div>`;

  // value runway: price vs the model range, $-labeled at the band's ends
  let runway = "";
  if (p.range_low != null && p.range_high != null && p.price != null) {
    const min = Math.min(p.range_low, p.price) * 0.97;
    const max = Math.max(p.range_high, p.price) * 1.03;
    const X = v => ((v - min) / (max - min) * 100).toFixed(1) + "%";
    const bw = ((p.range_high - p.range_low) / (max - min) * 100).toFixed(1) + "%";
    runway = `<div class="vbar"><div class="vtrack">
        <div class="vband${low ? " warn" : ""}" style="left:${X(p.range_low)};width:${bw}"></div>
        ${p.intrinsic != null && !low ? `<div class="vtick fv" style="left:${X(p.intrinsic)}"></div>` : ""}
        <div class="vtick pr" style="left:${X(p.price)}"></div></div>
      <div class="vlab"><span>${usd(p.range_low)}</span>
        <span class="vleg"><i class="ipr"></i>price <i class="ifv"></i>fair value</span>
        <span>${usd(p.range_high)}</span></div></div>`;
  }

  root.innerHTML = `
    <div class="nav"><button class="back" onclick="location.hash=''" aria-label="Back to list">
      <svg viewBox="0 0 12 20"><path d="M10 2 2 10l8 8" fill="none" stroke="currentColor"
        stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"/></svg>Quality Dips</button></div>
    <div class="dh">
      <div class="nm"><b>${esc(p.ticker)}</b> · ${esc(p.name)}</div>
      <div class="price" id="dprice">${usd(p.price)}</div>
      <div class="chgline"><span class="chg" id="dchg"></span>
        <span class="cdate" id="ddate"></span></div>
      ${header}
    </div>
    ${runway}
    ${p.thesis ? `<div class="thesis clamp" id="thesis"><div class="tx">${esc(p.thesis)}</div>
      <div class="thmore">more ▾</div></div>` : ""}
    <div class="ribbon">${(p.stats || []).map(s =>
      `<div class="rchip"><div class="l">${esc(s.label)}</div>
       <div class="v">${esc(String(s.value).split("  (")[0])}</div></div>`).join("")}</div>
    <div class="chart-wrap"><div id="chart"></div></div>
    <div class="ranges" id="ranges"></div>
    <div id="dipctx"></div>

    <div class="accordions">
      <div class="agroup">Valuation</div>
      ${acc("How we valued it", `<div class="methods">${methods}</div>`)}
      ${acc("DCF — discounted cash flow", `<div class="report">${p.dcf_html || ""}</div>`)}
      ${acc("DDM — dividend discount", `<div class="report">${p.ddm_html || ""}</div>`)}
      ${acc("Comps — peer multiples", `<div class="report">${p.comps_html || ""}</div>`)}
      ${acc("Reconciliation & confidence",
          `<p class="recsent">${esc(rec.sentence)}</p><div class="grid">${recVals}</div>`)}
      <div class="agroup">Quality &amp; risk</div>
      ${acc("Quality checklist", `<ul class="bullets good">${checklist}</ul>`)}
      ${capital ? acc("Capital allocation", `<ul class="bullets cap">${capital}</ul>`) : ""}
      ${acc("Risks", `<ul class="bullets risk">${risks}</ul>`)}
      ${mind ? acc("What would change our mind", `<ul class="bullets mind">${mind}</ul>`) : ""}
      ${manual ? acc("Needs your own research", `<p class="recsent">The models can't
          judge these — check them yourself before buying:</p>
          <ul class="bullets manual">${manual}</ul>`) : ""}
      <div class="agroup">More data</div>
      ${health ? acc("Financial health", `<div class="grid">${health}</div>
        <div class="src-note">Computed from the latest reported annual statements (Yahoo Finance).</div>`) : ""}
      ${analyst ? acc("Catalysts & Street view", `<div class="grid">${analyst}</div>
        <div class="src-note">Consensus and dates via Yahoo Finance — the Street's view, not ours.</div>`) : ""}
      ${acc("All key stats", `<div class="grid">${statsGrid}</div>`)}
    </div>

    <div class="sec"><h3>News</h3>
      <div class="nlist" id="nlist">
        ${'<div class="sk-news"><div class="sk a"></div><div class="sk b"></div></div>'.repeat(3)}
      </div>
      <div class="src-note" id="nnote">Fetching live headlines…</div></div>
    <footer>Prices, statements &amp; headlines via Yahoo Finance.</footer>`;

  mountDetailChart(p);
  animateAccordions(root);
  const th = document.getElementById("thesis");
  if (th) th.addEventListener("click", () => {
    th.classList.toggle("clamp");
    th.querySelector(".thmore").textContent = th.classList.contains("clamp") ? "more ▾" : "less ▴";
  });
  if (!low) {
    countUp(document.getElementById("dfv"), p.intrinsic, usd);
    countUp(document.getElementById("dup"), p.upside, pct);
  }
  initNews(p);
}

window.addEventListener("hashchange", route);
load();
