/* Two views of a project: Modules (the graph) and History (every run that changed code, as numbered versions).
   History answers "what have the agents done to my project so far, and how do I go back?" */
"use strict";

const VIEWS = [
  { id: "graph", label: "Modules", hint: "Modules and the imports between them" },
  { id: "history", label: "History", hint: "Every run that changed code: which modules and functions, the tests, and a way back" },
];

function setView(v) {
  if (!VIEWS.some((x) => x.id === v)) v = "graph";
  S.view = v;
  store.set("modfence.view", v);
  document.body.dataset.view = v;
  document.querySelectorAll("#viewseg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === v)));
  $("#canvas").hidden = v !== "graph";
  $("#alt").hidden = v === "graph";
  renderAltView();
  if (v === "graph") { paintSelection(); fitView(false); }
  slideInk($("#viewseg"), "[aria-pressed=true]");
}

function renderAltView() {
  if (!S.graph || S.view !== "history") { $("#alt").innerHTML = ""; return; }
  renderHistory();
}

/* ---------- History ---------- */
const when = (t) => new Date(t * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const asked = (p) => ((p || "").match(/^Request: (.*)$/m) || [])[1] || p; // a build shows the user's request, not the composed brief
const unitsOf = (v) => v.files.flatMap((f) => (f.funcs || []).map((u) => ({ ...u, file: f.path })));

async function renderHistory() {
  const box = $("#alt");
  let vs;
  try { ({ versions: vs } = await api(`/api/versions?${q()}`)); }
  catch (e) { box.innerHTML = `<p class="none">Could not load the history: ${esc(e.message)}</p>`; return; }
  if (S.view !== "history") return;
  if (!vs.length) {
    box.innerHTML = `<div class="hist"><div class="hempty"><h2>No versions yet</h2><p>Every run that changes code becomes a version here: what it was asked, which modules and functions it touched, whether the tests passed, and a way back. Select a module in <b>Modules</b>, give an instruction, and build.</p></div></div>`;
    return;
  }
  vs.forEach((v, i) => (v.n = i + 1));
  const mods = [...new Set(vs.flatMap((v) => v.modules || []))].sort();
  const cell = (v, m) => {
    if (!(v.modules || []).includes(m)) return `<td></td>`;
    const n = unitsOf(v).filter((u) => moduleOf(u.file) === m).length;
    return `<td class="hit${v.reverted ? " rev" : ""}" title="v${v.n} changed ${esc(m)}${n ? `: ${plural(n, "function")}` : ""}">${n || "•"}</td>`;
  };
  box.innerHTML = `<div class="hist">
    <div class="hhead"><h2>History</h2><p>${plural(vs.length, "version")} · ${plural(mods.length, "module")} touched · $${vs.reduce((a, v) => a + (v.cost_usd || 0), 0).toFixed(2)} on these runs${vs.some((v) => v.cost_usd == null) ? " (some N/A)" : ""}, planning not counted</p></div>
    <div class="hmat-wrap"><table class="hmat" aria-label="Which version changed which module">
      <thead><tr><th scope="col">module</th>${vs.map((v) => `<th scope="col"><button type="button" data-v="${v.n}" title="${esc(v.prompt || "")}">v${v.n}</button></th>`).join("")}</tr></thead>
      <tbody>${mods.map((m) => `<tr><th scope="row"><button type="button" class="mono" data-go="${esc(m)}">${esc(shown(m))}</button></th>${vs.map((v) => cell(v, m)).join("")}</tr>`).join("")}</tbody>
    </table></div>
    <ol class="vlist" reversed>${vs.slice().reverse().map(versionCard).join("")}</ol></div>`;
  box.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => { setView("graph"); select(b.dataset.go); }));
  box.querySelectorAll("[data-v]").forEach((b) => (b.onclick = () => { const c = box.querySelector(`#ver-${b.dataset.v}`); c.scrollIntoView({ block: "start", behavior: "smooth" }); c.classList.add("flash"); setTimeout(() => c.classList.remove("flash"), 900); }));
  box.querySelectorAll(".ver").forEach((card) => {
    const v = vs[+card.dataset.n - 1];
    $("[data-show]", card).onclick = () => { markRun(v); setView("graph"); };
    $("[data-open]", card).onclick = (ev) => {
      const body = $(".vbody", card), btn = ev.currentTarget;
      if (body.childElementCount) { body.innerHTML = ""; btn.setAttribute("aria-expanded", "false"); return; }
      btn.setAttribute("aria-expanded", "true");
      renderChanges(body, { ...v, outside_scope: v.files.filter((f) => f.outside).map((f) => f.path) },
        { turns: v.turns, cost_usd: v.cost_usd }, v.check, false);
    };
  });
}

function versionCard(v) {
  const us = unitsOf(v), count = (s) => us.filter((u) => u.status === s).length;
  const names = us.slice(0, 8).map((u) => `<span class="u ${u.status}">${SYM[u.status]}&#8202;${esc(u.name)}${u.kind === "def" || u.kind === "method" ? "()" : ""}</span>`).join("")
    + (us.length > 8 ? `<span class="more">+${us.length - 8} more</span>` : "");
  const chk = v.check ? `<span class="vchk ${v.check.ok ? "ok" : "bad"}">${v.check.ok ? "tests passed" : "tests failed"}</span>` : "";
  return `<li class="ver${v.reverted ? " reverted" : ""}" id="ver-${v.n}" data-n="${v.n}">
    <div class="vh"><b class="vn mono">v${v.n}</b><span class="vt">${esc(when(v.at))}</span>${v.phase ? `<span class="vp">${esc(v.phase)}</span>` : ""}
      <span class="vf mono" title="fence">${(v.editable || v.scope || []).map((m) => esc(shown(m))).join(" · ")}</span>
      ${chk}${v.reverted ? `<span class="vrev">reverted</span>` : ""}<span class="vc mono">${v.cost_usd != null ? "$" + v.cost_usd.toFixed(2) : "N/A"}</span></div>
    <p class="vq">${esc(asked(v.prompt) || "(prompt not recorded)")}</p>
    <div class="vu">${names || `<span class="more">${plural(v.files.length, "file")}, no Python functions</span>`}</div>
    <div class="va"><span class="vs mono"><span class="plus">+${count("added")}</span> <span class="chg">~${count("changed")}</span> <span class="minus">−${count("removed")}</span> functions · ${plural(v.files.length, "file")}</span>
      <button class="btn quiet" type="button" data-show title="Paint this version's changes on the module graph">Show on graph</button>
      <button class="btn quiet" type="button" data-open aria-expanded="false">Changes, diff and revert</button></div>
    <div class="vbody"></div></li>`;
}

/* Sliding indicator under the active tab: one element that moves, instead of a border that jumps. */
function slideInk(bar, activeSel) {
  if (!bar) return;
  let ink = bar.querySelector(":scope > .ink");
  if (!ink) { ink = document.createElement("span"); ink.className = "ink"; ink.setAttribute("aria-hidden", "true"); bar.appendChild(ink); }
  const a = bar.querySelector(activeSel);
  if (!a || !a.offsetWidth) { ink.style.opacity = "0"; return; }
  ink.style.opacity = "1";
  ink.style.width = a.offsetWidth + "px";
  ink.style.transform = `translateX(${a.offsetLeft}px)`;
}
addEventListener("resize", () => { slideInk($("#viewseg"), "[aria-pressed=true]"); slideInk($("#seg"), "[aria-selected=true]"); });

function wireViews() {
  $("#viewseg").innerHTML = VIEWS.map((v, i) => `<button type="button" data-view="${v.id}" title="${esc(v.hint)} (${i + 1})" aria-pressed="false">${esc(v.label)}<kbd>${i + 1}</kbd></button>`).join("");
  $("#viewseg").addEventListener("click", (e) => { const b = e.target.closest("button[data-view]"); if (b) setView(b.dataset.view); });
  document.fonts?.ready.then(() => { slideInk($("#viewseg"), "[aria-pressed=true]"); slideInk($("#seg"), "[aria-selected=true]"); });
}
