"use strict";

const app = document.getElementById("app");
const titleEl = document.getElementById("title");
const asofEl = document.getElementById("asof");
const backBtn = document.getElementById("back");

let DATA = { as_of: "", count: 0, picks: [] };

async function load() {
  try {
    const res = await fetch("results.json?t=" + Date.now(), { cache: "no-store" });
    DATA = await res.json();
  } catch (e) {
    app.innerHTML = `<div class="empty"><div class="big">Couldn't load data</div>
      <div>Check back after the next refresh.</div></div>`;
    return;
  }
  asofEl.textContent = DATA.as_of ? "as of " + DATA.as_of : "";
  route();
}

function route() {
  const tk = decodeURIComponent(location.hash.replace(/^#\/?/, ""));
  const pick = DATA.picks.find(p => p.ticker === tk);
  if (pick) renderDetail(pick);
  else renderHome();
}

function fmtPct(x) { return x == null ? "" : (x * 100).toFixed(0) + "%"; }
function fmtUsd(x) { return x == null ? "" : "$" + Number(x).toLocaleString(undefined, { maximumFractionDigits: 2 }); }

function renderHome() {
  backBtn.classList.add("hidden");
  titleEl.textContent = "Strong Buys";
  if (!DATA.picks.length) {
    app.innerHTML = `<div class="empty">
      <div class="big">🟢 No strong buys this cycle</div>
      <div>Nothing cleared the quality + 20% margin-of-safety bar.
      The screen ran fine — it's just being disciplined.</div></div>`;
    return;
  }
  app.innerHTML = DATA.picks.map(p => `
    <a class="card" href="#/${encodeURIComponent(p.ticker)}">
      <div class="row">
        <span class="tk">${p.ticker}</span>
        <span class="up">+${fmtPct(p.upside)} <span class="chev">›</span></span>
      </div>
      <div class="nm">${p.name || ""}</div>
      <div class="px">${fmtUsd(p.price)} → intrinsic <b>${fmtUsd(p.intrinsic)}</b>
        · ${p.confidence} confidence</div>
    </a>`).join("");
}

function renderDetail(p) {
  backBtn.classList.remove("hidden");
  titleEl.textContent = p.ticker;
  app.innerHTML = `
    <div class="summary">${p.summary_html || ""}</div>
    <div class="tabs">
      <div class="tab active" data-t="dcf">DCF</div>
      <div class="tab" data-t="ddm">DDM</div>
      <div class="tab" data-t="comps">Comps</div>
    </div>
    <div id="report" class="report">${p.dcf_html || ""}</div>`;
  const report = document.getElementById("report");
  const html = { dcf: p.dcf_html, ddm: p.ddm_html, comps: p.comps_html };
  app.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => {
      app.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      report.innerHTML = html[tab.dataset.t] || "";
    });
  });
  window.scrollTo(0, 0);
}

backBtn.addEventListener("click", () => { location.hash = ""; });
window.addEventListener("hashchange", route);
load();
