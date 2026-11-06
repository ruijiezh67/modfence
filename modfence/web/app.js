/* modfence UI: a module graph you can click, and a scoped conversation with Claude Code per module. No dependencies. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const NODE_W = 216, NODE_H = 74, GAP_X = 44, GAP_Y = 78;
const store = { get(k) { try { return localStorage.getItem(k); } catch { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch {} } };

const S = {
  projects: [], p: 0, graph: null, pos: {}, rows: [], view: "graph", selected: null, scope: new Set(), tab: "over",
  marks: { changed: new Set(), ripple: new Set() }, job: null, es: null, tasks: [],
  cam: { x: 0, y: 0, k: 1 }, camV: { x: 0, y: 0, k: 0 }, camTarget: null, raf: 0,
};

/* ---------------- api ---------------- */
async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json", "X-Modfence": "1" }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error(j.error || r.statusText), { status: r.status, data: j });
  return j;
}
const q = (extra = "") => `p=${S.p}${extra}`;

/* ---------------- boot ---------------- */
async function boot() {
  applyTheme(store.get("modfence.theme") || "auto");
  const { projects, claude } = await api("/api/projects");
  S.projects = projects;
  const saved = Number(store.get("modfence.project") || 0);
  S.p = projects[saved] ? saved : 0;
  $("#picker").innerHTML = projects.map((p) => `<option value="${p.i}">${esc(p.name)}</option>`).join("");
  $("#picker").value = S.p;
  const hp = new URLSearchParams(location.hash.slice(1));
  if (hp.get("p") && projects[+hp.get("p")]) { S.p = +hp.get("p"); $("#picker").value = S.p; }
  if (!claude) toast("Claude Code CLI not found: set CLAUDE_BIN and restart modfence.", false, 8000);
  await loadGraph(true);
  setView(hp.get("v") || store.get("modfence.view") || "graph");
  if (hp.get("m") && mod(hp.get("m"))) { if (hp.get("tab")) S.tab = hp.get("tab"); select(hp.get("m")); }
}

async function loadGraph(fit) {
  S.graph = await api(`/api/graph?${q()}`);
  layout();
  drawGraph();
  renderAltView();
  updateStats();
  if (fit) fitView(false);
  loadTasks();
  if (S.selected && !mod(S.selected)) closePanel();
  else if (S.selected) renderOverview();
}

function mod(id) { return S.graph && S.graph.modules.find((m) => m.id === id); }
const label = (id) => (id === "." ? "(root)" : id.split("/").pop());
const parent = (id) => (id.includes("/") ? id.slice(0, id.lastIndexOf("/")) : "");

function updateStats() {
  const g = S.graph, files = Object.keys(g.files).length, lines = g.modules.reduce((a, m) => a + m.lines, 0);
  $("#stats").textContent = `${g.modules.length} modules · ${files} files · ${lines.toLocaleString()} lines`;
}

/* ---------------- layout: layered, foundations at the bottom ---------------- */
function layout() {
  const g = S.graph, ids = g.modules.map((m) => m.id);
  const deps = Object.fromEntries(ids.map((i) => [i, []]));
  g.edges.forEach((e) => deps[e.source] && deps[e.source].push(e.target));
  const rank = {}, busy = new Set();
  const r = (id) => {
    if (id in rank) return rank[id];
    if (busy.has(id)) return 0; // cycle
    busy.add(id);
    const v = deps[id].length ? 1 + Math.max(...deps[id].map(r)) : 0;
    busy.delete(id);
    return (rank[id] = v);
  };
  ids.forEach(r);
  const maxRank = Math.max(0, ...ids.filter((i) => mod(i).kind !== "tests").map((i) => rank[i]));
  ids.forEach((i) => { if (mod(i).kind === "tests") rank[i] = Math.max(rank[i], maxRank + 1); });
  const top = Math.max(0, ...Object.values(rank));
  let rows = [];
  ids.forEach((i) => (rows[top - rank[i]] ||= []).push(i));
  rows = rows.filter(Boolean);
  rows.forEach((row) => row.sort());
  const nb = {};
  ids.forEach((i) => (nb[i] = new Set()));
  g.edges.forEach((e) => { nb[e.source].add(e.target); nb[e.target].add(e.source); });
  const idx = () => Object.fromEntries(rows.flatMap((row) => row.map((id, k) => [id, k - (row.length - 1) / 2])));
  for (let it = 0; it < 8; it++) {
    const order = it % 2 ? [...rows.keys()].reverse() : [...rows.keys()];
    for (const ri of order) {
      const at = idx();
      const bc = (id) => { const ns = [...nb[id]].filter((n) => rows[ri].indexOf(n) < 0); return ns.length ? ns.reduce((a, n) => a + at[n], 0) / ns.length : at[id]; };
      rows[ri].sort((a, b) => bc(a) - bc(b) || a.localeCompare(b));
    }
  }
  S.rows = rows.map((r) => r.slice());
  S.pos = {};
  rows.forEach((row, ri) => row.forEach((id, k) => {
    S.pos[id] = { x: (k - (row.length - 1) / 2) * (NODE_W + GAP_X) - NODE_W / 2, y: ri * (NODE_H + GAP_Y) };
  }));
}

/* ---------------- drawing ---------------- */
const SVGNS = "http://www.w3.org/2000/svg";
const el = (tag, attrs = {}, parentEl) => {
  const n = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (parentEl) parentEl.appendChild(n);
  return n;
};

function edgePath(e, spread) {
  const a = S.pos[e.source], b = S.pos[e.target];
  if (e._lane) {
    const sx = a.x + NODE_W / 2 + spread.out, sy = a.y + NODE_H, tx = b.x + NODE_W / 2 + spread.in, ty = b.y - 3, lx = e._lane;
    return `M${sx},${sy} C${sx},${sy + 30} ${lx},${sy + 8} ${lx},${sy + 46} L${lx},${ty - 46} C${lx},${ty - 8} ${tx},${ty - 30} ${tx},${ty}`;
  }
  if (b.y > a.y) {
    const sx = a.x + NODE_W / 2 + spread.out, sy = a.y + NODE_H, tx = b.x + NODE_W / 2 + spread.in, ty = b.y - 3;
    const dy = Math.max(36, (ty - sy) * 0.5);
    return `M${sx},${sy} C${sx},${sy + dy} ${tx},${ty - dy} ${tx},${ty}`;
  }
  // same row or upward (a cycle): loop around the right side
  const sx = a.x + NODE_W, sy = a.y + NODE_H / 2, tx = b.x + NODE_W + 3, ty = b.y + NODE_H / 2;
  const bulge = 60 + Math.abs(ty - sy) * 0.2;
  return `M${sx},${sy} C${sx + bulge},${sy} ${tx + bulge},${ty} ${tx},${ty}`;
}

function drawGraph() {
  const g = S.graph, eg = $("#edges"), ng = $("#nodes");
  eg.innerHTML = ""; ng.innerHTML = "";
  const outs = {}, ins = {};
  g.edges.forEach((e) => { (outs[e.source] ||= []).push(e); (ins[e.target] ||= []).push(e); });
  const spread = new Map();
  const assign = (list, key, other) => {
    list.sort((x, y) => S.pos[x[other]].x - S.pos[y[other]].x);
    list.forEach((e, k) => { const s = spread.get(e) || {}; s[key] = (k - (list.length - 1) / 2) * Math.min(26, (NODE_W * 0.6) / Math.max(1, list.length)); spread.set(e, s); });
  };
  Object.values(outs).forEach((l) => assign(l, "out", "target"));
  Object.values(ins).forEach((l) => assign(l, "in", "source"));
  routeLanes(g);
  g.edges.forEach((e) => {
    const d = edgePath(e, spread.get(e));
    const w = 1.3 + Math.min(2, Math.log2(e.receipts.length));
    e._base = mod(e.source).kind === "tests" ? "edge from-tests" : "edge";
    const p = el("path", { d, class: e._base, "marker-end": "url(#ah)", "stroke-width": w, "data-s": e.source, "data-t": e.target }, eg);
    const hit = el("path", { d, class: "edge-hit" }, eg);
    hit.addEventListener("pointerdown", (ev) => ev.stopPropagation());
    hit.addEventListener("pointerenter", (ev) => showEdgeTip(ev, e));
    hit.addEventListener("pointermove", moveTip);
    hit.addEventListener("pointerleave", hideTip);
    hit.addEventListener("click", () => { const r = e.receipts[0]; openFile(r.file, e.receipts.filter((x) => x.file === r.file).map((x) => x.line)); });
    e._el = p;
  });
  g.modules.forEach((m) => {
    const { x, y } = S.pos[m.id];
    const n = el("g", { class: `node ${m.kind === "tests" ? "tests" : ""}`, transform: `translate(${x},${y})`, tabindex: 0, role: "button", "aria-label": `Module ${m.id}`, "data-id": m.id }, ng);
    el("rect", { class: "ring", x: -3, y: -3, width: NODE_W + 6, height: NODE_H + 6, rx: 17 }, n);
    el("rect", { class: "card", width: NODE_W, height: NODE_H, rx: 14 }, n);
    el("rect", { class: "accent", x: 14, y: 19, width: 8, height: 8, rx: 4 }, n);
    const name = el("text", { class: "name", x: 30, y: 28 }, n);
    name.textContent = clip(label(m.id), 20);
    const meta = el("text", { class: "meta", x: 14, y: 54 }, n);
    const pre = parent(m.id);
    meta.textContent = clip(`${pre ? pre + " · " : ""}${m.files.length} file${m.files.length === 1 ? "" : "s"} · ${m.lines} lines`, 30);
    if (m.files.some((f) => S.graph.files[f].error)) n.classList.add("error");
    n.addEventListener("pointerdown", (ev) => ev.stopPropagation());
    n.addEventListener("click", (ev) => onNodeClick(m.id, ev));
    n.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); onNodeClick(m.id, ev); } });
    n.addEventListener("pointerenter", () => hoverNode(m.id, true));
    n.addEventListener("pointerleave", () => hoverNode(m.id, false));
  });
  paintSelection();
}
function routeLanes(g) {
  // An edge that skips rows goes around the cards in between: right if its target lies to the right, else left.
  const rowOf = (id) => Math.round(S.pos[id].y / (NODE_H + GAP_Y));
  const byRow = {};
  Object.entries(S.pos).forEach(([id, p]) => (byRow[rowOf(id)] ||= []).push(p));
  const lanes = { left: 0, right: 0 };
  S.extent = { x0: Infinity, x1: -Infinity };
  g.edges.forEach((e, k) => {
    e._lane = 0;
    const rs = rowOf(e.source), rt = rowOf(e.target);
    if (rt - rs < 2) return;
    const mid = [];
    for (let r = rs + 1; r < rt; r++) mid.push(...(byRow[r] || []));
    if (!mid.length) return;
    const minX = Math.min(...mid.map((p) => p.x)), maxX = Math.max(...mid.map((p) => p.x + NODE_W));
    const dx = S.pos[e.target].x - S.pos[e.source].x;
    const side = dx > 1 ? "right" : dx < -1 ? "left" : lanes.right <= lanes.left ? "right" : "left";
    const n = lanes[side]++;
    e._lane = side === "right" ? maxX + 26 + n * 14 : minX - 26 - n * 14;
    S.extent.x0 = Math.min(S.extent.x0, e._lane);
    S.extent.x1 = Math.max(S.extent.x1, e._lane);
  });
}
const clip = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

function related(id) {
  const dep = new Set(), use = new Set();
  S.graph.edges.forEach((e) => { if (e.source === id) dep.add(e.target); if (e.target === id) use.add(e.source); });
  return { dep, use };
}

function paintSelection(hover) {
  const focus = hover || S.selected;
  const rel = focus ? related(focus) : { dep: new Set(), use: new Set() };
  document.querySelectorAll(".node").forEach((n) => {
    const id = n.dataset.id;
    n.classList.toggle("selected", id === S.selected);
    n.classList.toggle("inscope", S.scope.has(id) && id !== S.selected);
    n.classList.toggle("dep", focus && rel.dep.has(id));
    n.classList.toggle("use", focus && rel.use.has(id));
    n.classList.toggle("faded", !!focus && id !== focus && !rel.dep.has(id) && !rel.use.has(id) && !S.scope.has(id));
    n.classList.toggle("changed", S.marks.changed.has(id));
    n.classList.toggle("ripple", S.marks.ripple.has(id) && !S.marks.changed.has(id));
  });
  S.graph.edges.forEach((e) => {
    const k = !focus ? "" : e.source === focus ? "dep" : e.target === focus ? "use" : "faded";
    e._el.setAttribute("class", `${e._base} ${k}`);
    e._el.setAttribute("marker-end", k === "dep" ? "url(#ah-dep)" : k === "use" ? "url(#ah-use)" : "url(#ah)");
  });
  paintAlt(focus, rel);
}
let hoverT = 0;
function hoverNode(id, on) {
  clearTimeout(hoverT);
  if (on) paintSelection(id);
  else hoverT = setTimeout(() => paintSelection(), 60);
}

/* ---------------- camera: 1:1 pan, zoom at pointer, critically damped spring for fit/focus ---------------- */
function applyCam() { $("#world").setAttribute("transform", `translate(${S.cam.x},${S.cam.y}) scale(${S.cam.k})`); }
function springTo(target) {
  S.camTarget = target;
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) { Object.assign(S.cam, target); S.camV = { x: 0, y: 0, k: 0 }; applyCam(); return; }
  if (S.raf) return;
  let last = performance.now();
  const response = 0.42, zeta = 1.0, stiff = (2 * Math.PI / response) ** 2, damp = (4 * Math.PI * zeta) / response;
  const step = (now) => {
    const dt = Math.min(0.032, (now - last) / 1000); last = now;
    let moving = false;
    for (const k of ["x", "y", "k"]) {
      const t = S.camTarget[k], x = S.cam[k];
      S.camV[k] += (-stiff * (x - t) - damp * S.camV[k]) * dt;
      S.cam[k] += S.camV[k] * dt;
      if (Math.abs(S.cam[k] - t) > (k === "k" ? 0.0005 : 0.3) || Math.abs(S.camV[k]) > (k === "k" ? 0.002 : 1)) moving = true;
    }
    applyCam();
    if (moving) S.raf = requestAnimationFrame(step);
    else { Object.assign(S.cam, S.camTarget); S.camV = { x: 0, y: 0, k: 0 }; applyCam(); S.raf = 0; }
  };
  S.raf = requestAnimationFrame(step);
}
function stopSpring() { if (S.raf) cancelAnimationFrame(S.raf); S.raf = 0; S.camV = { x: 0, y: 0, k: 0 }; }

function bounds() {
  const xs = Object.values(S.pos);
  if (!xs.length) return { x0: 0, y0: 0, x1: 1, y1: 1 };
  const ex = S.extent || { x0: Infinity, x1: -Infinity };
  return { x0: Math.min(ex.x0, ...xs.map((p) => p.x)) - 40, y0: Math.min(...xs.map((p) => p.y)) - 30,
           x1: Math.max(ex.x1, ...xs.map((p) => p.x + NODE_W)) + 40, y1: Math.max(...xs.map((p) => p.y + NODE_H)) + 30 };
}
function viewport() {
  const w = innerWidth - (document.body.classList.contains("panel-open") && innerWidth > 760 ? 470 : 0);
  return { w, h: innerHeight, top: 76, bottom: 92 };
}
function fitView(animate = true) {
  const b = bounds(), v = viewport();
  const k = Math.min(1.15, Math.max(0.3, Math.min(v.w / (b.x1 - b.x0), (v.h - v.top - v.bottom) / (b.y1 - b.y0))));
  const t = { k, x: v.w / 2 - ((b.x0 + b.x1) / 2) * k, y: v.top + (v.h - v.top - v.bottom) / 2 - ((b.y0 + b.y1) / 2) * k };
  if (animate) springTo(t); else { stopSpring(); Object.assign(S.cam, t); applyCam(); }
}
function revealNode(id) {
  const p = S.pos[id], v = viewport(), k = S.cam.k;
  const sx = S.cam.x + p.x * k, sy = S.cam.y + p.y * k, w = NODE_W * k, h = NODE_H * k;
  let dx = 0, dy = 0;
  if (sx < 24) dx = 24 - sx; else if (sx + w > v.w - 24) dx = v.w - 24 - (sx + w);
  if (sy < v.top + 10) dy = v.top + 10 - sy; else if (sy + h > v.h - v.bottom) dy = v.h - v.bottom - (sy + h);
  if (dx || dy) springTo({ x: S.cam.x + dx, y: S.cam.y + dy, k });
}
function zoomAt(f, cx, cy) {
  stopSpring();
  const k = Math.min(2.2, Math.max(0.25, S.cam.k * f));
  S.cam.x = cx - ((cx - S.cam.x) * k) / S.cam.k;
  S.cam.y = cy - ((cy - S.cam.y) * k) / S.cam.k;
  S.cam.k = k;
  applyCam();
}

function wireCanvas() {
  const c = $("#canvas");
  let drag = null;
  c.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    stopSpring();
    c.setPointerCapture(e.pointerId);
    drag = { x: e.clientX, y: e.clientY, cx: S.cam.x, cy: S.cam.y, moved: false };
    c.classList.add("panning");
  });
  c.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
    if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
    S.cam.x = drag.cx + dx; S.cam.y = drag.cy + dy; applyCam();
  });
  const end = (e) => {
    if (!drag) return;
    if (!drag.moved && e.type === "pointerup" && S.selected) closePanel();
    drag = null; c.classList.remove("panning");
  };
  c.addEventListener("pointerup", end);
  c.addEventListener("pointercancel", end);
  c.addEventListener("dblclick", () => fitView());
  c.addEventListener("wheel", (e) => {
    e.preventDefault();
    const trackpad = e.deltaMode === 0 && (Math.abs(e.deltaX) > 0 || Math.abs(e.deltaY) < 40);
    if (e.ctrlKey || e.metaKey) zoomAt(Math.exp(-e.deltaY * 0.01), e.clientX, e.clientY); // pinch
    else if (trackpad) { stopSpring(); S.cam.x -= e.deltaX; S.cam.y -= e.deltaY; applyCam(); } // two-finger pan
    else zoomAt(Math.exp(-e.deltaY * (e.deltaMode ? 0.06 : 0.0022)), e.clientX, e.clientY); // mouse wheel
  }, { passive: false });
  $("#zin").onclick = () => zoomAt(1.2, viewport().w / 2, innerHeight / 2);
  $("#zout").onclick = () => zoomAt(1 / 1.2, viewport().w / 2, innerHeight / 2);
  $("#zfit").onclick = () => fitView();
  addEventListener("resize", () => fitView(false));
}

/* ---------------- tooltip ---------------- */
function showEdgeTip(ev, e) {
  const t = $("#tip");
  const rs = e.receipts.slice(0, 6);
  t.innerHTML = `<div class="h">${esc(e.source)} → ${esc(e.target)} <span style="color:var(--text-3);font-weight:400">· ${e.receipts.length} import${e.receipts.length > 1 ? "s" : ""}</span></div>`
    + rs.map((r) => `<code><span class="loc">${esc(r.file)}:${r.line}</span>  ${esc(r.code)}</code>`).join("")
    + (e.receipts.length > rs.length ? `<code>… ${e.receipts.length - rs.length} more</code>` : "")
    + `<div style="color:var(--text-3);margin-top:5px">Click to open the import</div>`;
  t.classList.add("show"); moveTip(ev);
}
function moveTip(ev) { const t = $("#tip"); t.style.left = Math.min(ev.clientX + 14, innerWidth - t.offsetWidth - 10) + "px"; t.style.top = Math.min(ev.clientY + 16, innerHeight - t.offsetHeight - 10) + "px"; }
function hideTip() { $("#tip").classList.remove("show"); }

/* ---------------- selection & panel ---------------- */
function onNodeClick(id, ev) {
  if ((ev.shiftKey || ev.metaKey || ev.ctrlKey) && S.selected) {
    if (id === S.selected) return;
    S.scope.has(id) ? S.scope.delete(id) : S.scope.add(id);
    renderScope(); paintSelection(); loadTalk();
    return;
  }
  select(id);
}
function select(id) {
  const opening = !document.body.classList.contains("panel-open");
  S.selected = id;
  S.scope = new Set([id]);
  document.body.classList.add("panel-open");
  $("#panel").setAttribute("aria-hidden", "false");
  renderHeader(); renderOverview(); renderScope(); loadTalk(); paintSelection();
  setTab(S.tab);
  setTimeout(() => {
    if (S.view === "graph") opening ? fitView() : revealNode(id);
    else { if (opening && S.view === "map") renderAltView(); revealCard(id); }
  }, 30);
  $("#prompt").focus({ preventScroll: true });
}
function closePanel() {
  const wasOpen = document.body.classList.contains("panel-open");
  S.selected = null; S.scope.clear();
  document.body.classList.remove("panel-open");
  if (wasOpen) setTimeout(() => (S.view === "graph" ? fitView() : S.view === "map" && renderAltView()), 30);
  $("#panel").setAttribute("aria-hidden", "true");
  paintSelection();
}
function setTab(t) {
  S.tab = t;
  $("#seg").dataset.tab = t;
  document.querySelectorAll("#seg button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === t)));
  $("#v-over").hidden = t !== "over";
  $("#v-talk").hidden = t !== "talk";
  if (t === "talk") scrollTalk();
}

function renderHeader() {
  const m = mod(S.selected);
  $("#mname").textContent = label(m.id);
  $("#mpath").textContent = m.id === "." ? "project root" : m.id + "/";
  $("#mdoc").textContent = m.doc || "";
  $("#mdoc").hidden = !m.doc;
}

function renderOverview() {
  const m = mod(S.selected); if (!m) return;
  renderHeader();
  const { dep, use } = related(m.id);
  const edgeCount = (a, b) => (S.graph.edges.find((e) => e.source === a && e.target === b) || { receipts: [] }).receipts.length;
  const chip = (id, color, n) => `<button class="chip" data-go="${esc(id)}"><i style="background:var(${color})"></i>${esc(id === "." ? "(root)" : id)}<span class="n">${n}</span></button>`;
  const tasks = S.tasks.filter((t) => t.modules.includes(m.id));
  $("#v-over").innerHTML = `
    <div class="statrow">
      <div class="stat"><b>${m.files.length}</b><span>files</span></div>
      <div class="stat"><b>${m.lines.toLocaleString()}</b><span>lines</span></div>
      <div class="stat"><b>${m.names.length}</b><span>public names</span></div>
    </div>
    <div class="sect"><h4>Depends on</h4><div class="chips">${[...dep].map((d) => chip(d, "--blue", edgeCount(m.id, d))).join("") || '<span class="none">Nothing in this project</span>'}</div></div>
    <div class="sect"><h4>Used by</h4><div class="chips">${[...use].map((u) => chip(u, "--clay", edgeCount(u, m.id))).join("") || '<span class="none">No other module imports it</span>'}</div></div>
    ${tasks.length ? `<div class="sect"><h4>Tasks for this module</h4>${tasks.map((t, i) => `<button class="task" data-task="${i}"><b>${esc(t.title)}</b>${t.level ? `<span class="lv">${esc(t.level)}</span>` : ""}<p>${esc(clip(t.summary, 150))}</p></button>`).join("")}</div>` : ""}
    <div class="sect"><h4>Files</h4><div class="files">${m.files.map((f) => {
      const fi = S.graph.files[f];
      return `<button class="frow" data-file="${esc(f)}"><span class="fn">${esc(f.split("/").pop())}</span><span class="fd">${esc(fi.error || fi.doc)}</span><span class="fl">${fi.lines}</span></button>`;
    }).join("")}</div></div>
    ${m.names.length ? `<div class="sect"><h4>Interface</h4><div class="names">${m.names.slice(0, 60).map((n) => `<span><em>${n.kind}</em> ${esc(n.name)}</span>`).join("")}</div></div>` : ""}`;
  $("#v-over").querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => select(b.dataset.go)));
  $("#v-over").querySelectorAll("[data-file]").forEach((b) => (b.onclick = () => openFile(b.dataset.file)));
  $("#v-over").querySelectorAll("[data-task]").forEach((b) => (b.onclick = () => useTask(tasks[+b.dataset.task])));
}

function renderScope() {
  const testsMod = S.graph.modules.find((m) => m.kind === "tests");
  const items = [...S.scope].map((id) => `<span class="chip">${esc(id === "." ? "(root)" : id)}${S.scope.size > 1 ? `<button data-rm="${esc(id)}" aria-label="Remove ${esc(id)}" style="border:0;background:none;padding:0;display:grid;color:inherit"><svg viewBox="0 0 10 10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><path d="M2 2l6 6M8 2L2 8"/></svg></button>` : ""}</span>`);
  if (testsMod && !S.scope.has(testsMod.id)) items.push(`<button class="chip off" data-add="${esc(testsMod.id)}">+ ${esc(testsMod.id)}</button>`);
  $("#scope").innerHTML = `<span class="lab">Can edit</span>${items.join("")}`;
  $("#scope").querySelectorAll("[data-rm]").forEach((b) => (b.onclick = () => { S.scope.delete(b.dataset.rm); if (!S.scope.has(S.selected)) S.selected = [...S.scope][0]; renderScope(); paintSelection(); loadTalk(); }));
  $("#scope").querySelectorAll("[data-add]").forEach((b) => (b.onclick = () => { S.scope.add(b.dataset.add); renderScope(); paintSelection(); loadTalk(); }));
}
const scopeKey = () => [...S.scope].sort().join("+");

/* ---------------- tasks from TASKS.md ---------------- */
async function loadTasks() {
  S.tasks = [];
  try {
    const { text } = await api(`/api/file?${q("&path=TASKS.md")}`);
    S.tasks = parseTasks(text);
  } catch { /* no TASKS.md */ }
  if (S.selected) renderOverview();
}
function parseTasks(text) {
  // "## 4. Exponent operator (crosses modules: `lexer`, `parser`)" + "Target: `calc.lexer`, `calc.parser`."
  const ids = S.graph.modules.map((m) => m.id);
  return text.split(/\n(?=## )/).filter((sec) => /^## /.test(sec)).map((sec) => {
    const lines = sec.split("\n");
    const head = lines[0].replace(/^##\s*/, "");
    const num = (head.match(/^(\d+)[.)]/) || [])[1] || "";
    const title = head.replace(/^\d+[.)]\s*/, "").replace(/\s*\((single module|crosses modules?)[^)]*\)\s*$/i, "").trim();
    const target = lines.find((l) => /^\s*target/i.test(l)) || "";
    const ticks = (s) => [...s.matchAll(/`([^`]+)`/g)].map((m) => m[1].replace(/\.py$/, ""));
    let modules = ticks(target).map((t) => t.replace(/\./g, "/")).filter((t) => ids.includes(t));
    if (!modules.length) {
      const short = ticks((head.match(/\(([^)]*)\)/) || [])[1] || "");
      modules = ids.filter((id) => short.includes(id.split("/").pop()));
    }
    const body = lines.slice(1).join("\n").trim();
    const summary = body.replace(/^target[^\n]*\n?/i, "").replace(/[*`#>]/g, "").replace(/\s+/g, " ").trim();
    const level = modules.length > 1 ? `${modules.length} modules` : "1 module";
    return { title: num ? `${num}. ${title}` : title, body, modules: [...new Set(modules)], level, summary };
  }).filter((t) => t.modules.length);
}
function useTask(t) {
  S.scope = new Set([S.selected, ...t.modules.filter((m) => m !== S.selected)]);
  renderScope(); paintSelection(); loadTalk();
  const ta = $("#prompt");
  ta.value = `${t.title}\n\n${t.body}`;
  autosize(); ta.focus();
}

/* ---------------- conversation ---------------- */
async function loadTalk() {
  const v = $("#v-talk");
  v.innerHTML = "";
  $("#tcount").textContent = "";
  if (!S.scope.size) return;
  const key = scopeKey();
  try {
    const { runs } = await api(`/api/history?${q("&scope=" + encodeURIComponent(key))}`);
    if (key !== scopeKey()) return;
    runs.forEach((r) => { const view = newRun(r.prompt, r.scope); r.events.forEach((e) => view.add(e, true)); view.flush(); });
    $("#tcount").textContent = runs.length ? String(runs.length) : "";
  } catch { /* none */ }
  if (S.job && !S.job.done && S.job.key === key) S.job.view = attachLive(S.job);
  if (!v.children.length) v.innerHTML = `<p class="none" id="talk-empty">No conversation for this scope yet. Ask something below: Claude reads the whole project, but can only edit ${esc([...S.scope].join(", "))}.</p>`;
}
function attachLive(job) {
  const view = newRun(job.prompt, job.scope);
  job.events.forEach((e) => view.add(e, true));
  view.flush();
  return view;
}
function scrollTalk() { const b = $("#pbody"); requestAnimationFrame(() => (b.scrollTop = b.scrollHeight)); }

function newRun(prompt, scope) {
  $("#talk-empty")?.remove();
  const root = document.createElement("div");
  root.className = "run";
  root.innerHTML = `<div class="you"><div>${esc(prompt)}<span class="sc">scope: ${esc(scope.join(", "))}</span></div></div><div class="stream"></div>`;
  $("#v-talk").appendChild(root);
  const stream = $(".stream", root);
  let textEl = null, textBuf = "", stepsEl = null, typing = null, pending = 0;
  const steps = {};
  const showTyping = (on) => {
    if (on && !typing) { typing = document.createElement("div"); typing.className = "typing"; typing.innerHTML = "<span></span><span></span><span></span>"; stream.appendChild(typing); }
    if (!on && typing) { typing.remove(); typing = null; }
  };
  const renderText = () => { pending = 0; if (textEl) textEl.innerHTML = md(textBuf); };
  const view = {
    add(e, replay) {
      if (e.kind === "text") {
        showTyping(false);
        if (!textEl) { textEl = document.createElement("div"); textEl.className = "md"; stream.appendChild(textEl); stepsEl = null; textBuf = ""; }
        textBuf += e.text;
        if (replay) return;
        if (!pending) pending = requestAnimationFrame(renderText);
      } else if (e.kind === "text_end") {
        renderText(); textEl = null;
      } else if (e.kind === "tool") {
        showTyping(false);
        if (textEl) { renderText(); textEl = null; }
        if (!stepsEl) { stepsEl = document.createElement("div"); stepsEl.className = "steps"; stream.appendChild(stepsEl); }
        const s = document.createElement("div");
        s.className = `step ${e.edit ? "edit" : ""}`;
        s.innerHTML = `<span class="ic">${toolIcon(e.name)}</span><span class="tn">${esc(e.name)}</span><span class="td">${esc(shortPath(e.detail))}</span><span class="st spin"></span>`;
        stepsEl.appendChild(s);
        steps[e.id] = s;
        if (!replay) showTyping(true);
      } else if (e.kind === "tool_result") {
        const s = steps[e.id];
        if (!s) return;
        const st = $(".st", s);
        st.className = "st";
        st.innerHTML = e.denied ? ICON.shield : e.error ? ICON.x : ICON.check;
        if (e.denied) { s.classList.add("denied"); s.title = e.text; $(".tn", s).textContent += " blocked"; }
        else if (e.error) { s.classList.add("err"); s.title = e.text; }
      } else if (e.kind === "status") {
        const d = document.createElement("div"); d.className = "status"; d.textContent = e.text; stream.appendChild(d);
        if (!replay) showTyping(true);
      } else if (e.kind === "error") {
        showTyping(false);
        const d = document.createElement("div"); d.className = "error"; d.textContent = e.text; stream.appendChild(d);
      } else if (e.kind === "result") {
        view.result = e;
      } else if (e.kind === "changes") {
        view.changes = e;
      } else if (e.kind === "done") {
        showTyping(false);
        if (textEl) { renderText(); textEl = null; }
        stream.querySelectorAll(".st.spin").forEach((x) => { x.className = "st"; x.innerHTML = ICON.dash; });
        summary(stream, view.result, view.changes);
      }
      if (!replay) scrollTalk();
    },
    flush() { if (textEl) renderText(); },
  };
  scrollTalk();
  return view;
}

function summary(stream, r, c) {
  const files = c ? [...c.added, ...c.modified] : [];
  const box = document.createElement("div");
  box.className = "summary";
  const fileBtns = files.map((f) => `<button data-file="${esc(f)}">${esc(f)}</button>`).join("") + (c && c.deleted.length ? ` <span class="warn">deleted: ${esc(c.deleted.join(", "))}</span>` : "");
  box.innerHTML = (files.length || (c && c.deleted.length) ? `<div class="row"><span class="k">Changed</span><span class="v">${fileBtns}</span></div>` : `<div class="row"><span class="k">Changed</span><span class="v" style="color:var(--text-3)">no files</span></div>`)
    + (c && c.ripple.length ? `<div class="row"><span class="k">Ripple</span><span class="v">${c.ripple.map((m) => `<button data-go="${esc(m)}" style="color:var(--amber)">${esc(m)}</button>`).join("")}<span style="color:var(--text-3)"> import a changed module</span></span></div>` : "")
    + (c && c.outside_scope.length ? `<div class="row"><span class="k warn">Outside</span><span class="v warn">${esc(c.outside_scope.join(", "))} changed outside the scope</span></div>` : "")
    + (r ? `<div class="meta">${r.ok ? "Done" : "Stopped with an error"}${r.duration_s ? ` in ${r.duration_s} s` : ""}${r.turns ? ` · ${r.turns} turns` : ""}${r.cost_usd != null ? ` · $${r.cost_usd.toFixed(3)}` : ""}</div>` : "");
  box.querySelectorAll("[data-file]").forEach((b) => (b.onclick = () => openFile(b.dataset.file)));
  box.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => select(b.dataset.go)));
  stream.appendChild(box);
}

const fwd = (s) => String(s || "").replace(/\\/g, "/");
const shortPath = (s) => {
  const root = fwd(S.graph && S.graph.root) + "/", v = fwd(s);
  return root.length > 1 && v.toLowerCase().startsWith(root.toLowerCase()) ? v.slice(root.length) : v;
};
const ICON = {
  check: '<svg viewBox="0 0 14 14" fill="none" stroke="var(--green)" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7.5l2.5 2.5L11 4.5"/></svg>',
  x: '<svg viewBox="0 0 14 14" fill="none" stroke="var(--red)" stroke-width="1.8" stroke-linecap="round"><path d="M4 4l6 6M10 4l-6 6"/></svg>',
  shield: '<svg viewBox="0 0 14 14" fill="none" stroke="var(--red)" stroke-width="1.5" stroke-linejoin="round"><path d="M7 1.5l4.5 1.8v3.4c0 2.8-2 4.6-4.5 5.6C4.5 11.3 2.5 9.5 2.5 6.7V3.3z"/><path d="M5 7h4" stroke-linecap="round"/></svg>',
  dash: '<svg viewBox="0 0 14 14" stroke="var(--text-3)" stroke-width="1.6" stroke-linecap="round"><path d="M4 7h6"/></svg>',
};
function toolIcon(name) {
  const p = {
    Read: '<path d="M4 2h5l3 3v7a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z"/><path d="M9 2v3h3"/>',
    Edit: '<path d="M10 2.5l2.5 2.5L6 11.5H3.5V9z"/>', Write: '<path d="M10 2.5l2.5 2.5L6 11.5H3.5V9z"/>', MultiEdit: '<path d="M10 2.5l2.5 2.5L6 11.5H3.5V9z"/>',
    Bash: '<rect x="1.5" y="2.5" width="12" height="10" rx="2"/><path d="M4 6l2 1.5L4 9M7.5 9.5H10"/>',
    Grep: '<circle cx="6.5" cy="6.5" r="4"/><path d="M9.5 9.5L13 13"/>', Glob: '<circle cx="6.5" cy="6.5" r="4"/><path d="M9.5 9.5L13 13"/>',
    TodoWrite: '<path d="M2.5 4h1M2.5 7.5h1M2.5 11h1M6 4h6.5M6 7.5h6.5M6 11h6.5"/>',
  }[name] || '<circle cx="7.5" cy="7.5" r="2.5"/>';
  return `<svg viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round">${p}</svg>`;
}

/* tiny markdown: fenced code, inline code, bold, italics, headings, lists, paragraphs */
function md(src) {
  const blocks = [];
  let s = String(src).replace(/```[^\n]*\n([\s\S]*?)(```|$)/g, (_, code) => { blocks.push(code); return `\u0000${blocks.length - 1}\u0000`; });
  s = esc(s)
    .replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
  const out = [];
  let list = null;
  for (const line of s.split("\n")) {
    const li = line.match(/^\s*([-*]|\d+[.)])\s+(.*)/);
    if (li) {
      const type = /\d/.test(li[1]) ? "ol" : "ul";
      if (!list || list.type !== type) { if (list) out.push(`</${list.type}>`); list = { type }; out.push(`<${type}>`); }
      out.push(`<li>${li[2]}</li>`);
      continue;
    }
    if (list) { out.push(`</${list.type}>`); list = null; }
    const h = line.match(/^(#{1,4})\s+(.*)/);
    if (h) out.push(`<h3>${h[2]}</h3>`);
    else if (/^\u0000\d+\u0000$/.test(line.trim())) out.push(line.trim());
    else if (line.trim()) out.push(`<p>${line}</p>`);
  }
  if (list) out.push(`</${list.type}>`);
  return out.join("").replace(/\u0000(\d+)\u0000/g, (_, i) => `<pre><code>${esc(blocks[+i].replace(/\n$/, ""))}</code></pre>`);
}

/* ---------------- composer & runs ---------------- */
function autosize() { const t = $("#prompt"); t.style.height = "auto"; t.style.height = Math.min(160, t.scrollHeight) + "px"; syncSend(); }
function syncSend() {
  const running = S.job && !S.job.done;
  const b = $("#send");
  b.classList.toggle("stop", !!running);
  b.disabled = !running && !$("#prompt").value.trim();
  b.setAttribute("aria-label", running ? "Stop" : "Send");
  b.innerHTML = running ? '<svg viewBox="0 0 16 16"><rect x="4.5" y="4.5" width="7" height="7" rx="1.5" fill="currentColor"/></svg>'
    : '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M8 13V3M3.5 7.5L8 3l4.5 4.5"/></svg>';
}

async function send() {
  if (S.job && !S.job.done) { await api("/api/cancel", { job: S.job.id }).catch(() => {}); return; }
  const prompt = $("#prompt").value.trim();
  if (!prompt || !S.scope.size) return;
  const scope = [...S.scope];
  let res;
  try { res = await api(`/api/ask?${q()}`, { prompt, scope }); }
  catch (e) { toast(e.message, false); return; }
  $("#prompt").value = ""; autosize();
  S.marks = { changed: new Set(), ripple: new Set() }; paintSelection();
  const job = { id: res.job, prompt, scope, key: scopeKey(), events: [], done: false };
  S.job = job;
  setTab("talk");
  $("#talk-empty")?.remove();
  job.view = newRun(prompt, scope);
  syncSend();
  listen(job);
}

function listen(job) {
  const es = new EventSource(`/api/events?job=${job.id}&from=${job.events.length}`);
  S.es = es;
  es.onmessage = (m) => {
    const e = JSON.parse(m.data);
    if (e.i < job.events.length) return; // already seen
    job.events.push(e);
    if (job.key === scopeKey() && job.view) job.view.add(e);
    if (e.kind === "tool" && e.edit) markEditing(e.detail);
    if (e.kind === "changes") onChanges(e);
    if (e.kind === "done") { job.done = true; es.close(); syncSend(); const n = Number($("#tcount").textContent || 0); if (job.key === scopeKey()) $("#tcount").textContent = String(n + 1); }
  };
  es.onerror = () => { es.close(); if (!job.done) setTimeout(() => listen(job), 800); }; // resume where we left off
}

function markEditing(path) {
  const rel = shortPath(path).replace(/\\/g, "/");
  const id = rel.includes("/") ? rel.slice(0, rel.lastIndexOf("/")) : ".";
  document.querySelectorAll(`.node[data-id="${CSS.escape(id)}"], #alt .mcard[data-id="${CSS.escape(id)}"]`).forEach((n) => {
    n.classList.remove("changed"); void n.getBoundingClientRect(); n.classList.add("changed"); // restart the pulse
  });
}

async function onChanges(c) {
  await loadGraph(false);
  S.marks = { changed: new Set(c.modules), ripple: new Set(c.ripple) };
  paintSelection();
  if (c.outside_scope.length) toast(`Changed outside the scope: ${c.outside_scope.join(", ")}`, false, 6000);
}

/* ---------------- file viewer ---------------- */
async function openFile(path, lines = []) {
  let text;
  try { ({ text } = await api(`/api/file?${q("&path=" + encodeURIComponent(path))}`)); }
  catch (e) { toast(e.message, false); return; }
  const hl = new Set(lines);
  $("#stitle").textContent = path;
  $("#scode").innerHTML = text.split("\n").map((l, i) => `<div class="ln${hl.has(i + 1) ? " hl" : ""}" id="L${i + 1}"><b>${i + 1}</b>${esc(l) || " "}</div>`).join("");
  showSheet(true);
  if (lines.length) requestAnimationFrame(() => $(`#L${lines[0]}`)?.scrollIntoView({ block: "center" }));
}
function showText(title, text) {
  $("#stitle").textContent = title;
  $("#scode").innerHTML = `<pre>${esc(text)}</pre>`;
  showSheet(true);
}
function showSheet(on) {
  $("#scrim").classList.toggle("show", on);
  $("#sheet").classList.toggle("show", on);
  if (on) $("#sclose").focus();
}

/* ---------------- tests, toast, theme ---------------- */
let toastT = 0, lastTests = null;
function toast(text, ok = true, ms = 3600, onclick) {
  const t = $("#toast");
  $("#ttext").textContent = text;
  t.classList.toggle("bad", !ok);
  t.classList.add("show");
  t.onclick = onclick || (() => t.classList.remove("show"));
  clearTimeout(toastT);
  toastT = setTimeout(() => t.classList.remove("show"), ms);
}
async function runTests() {
  const b = $("#tests");
  b.classList.remove("ok", "bad"); b.classList.add("busy");
  $(".lbl", b).textContent = "Testing";
  try {
    const r = await api(`/api/tests?${q()}`, {});
    lastTests = r;
    b.classList.add(r.ok ? "ok" : "bad");
    $(".lbl", b).textContent = r.ok ? "Tests pass" : r.ok === null ? "No tests" : "Tests fail";
    toast(r.summary || "No tests found", r.ok !== false, 4200, () => showText("Test output", r.output || r.summary));
  } catch (e) { toast(e.message, false); $(".lbl", b).textContent = "Run tests"; }
  b.classList.remove("busy");
}
function applyTheme(mode) {
  if (mode === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.dataset.theme = mode;
  store.set("modfence.theme", mode);
  $("#theme").title = `Appearance: ${mode}`;
}

/* ---------------- wiring ---------------- */
function wire() {
  wireCanvas();
  wireViews();
  $("#picker").onchange = async (e) => {
    S.p = Number(e.target.value); store.set("modfence.project", S.p);
    closePanel(); S.marks = { changed: new Set(), ripple: new Set() };
    const b = $("#tests"); b.classList.remove("ok", "bad"); $(".lbl", b).textContent = "Run tests";
    await loadGraph(true);
  };
  $("#refresh").onclick = () => loadGraph(false);
  $("#tests").onclick = runTests;
  $("#theme").onclick = () => { const order = ["auto", "light", "dark"]; const cur = store.get("modfence.theme") || "auto"; applyTheme(order[(order.indexOf(cur) + 1) % 3]); };
  $("#close").onclick = closePanel;
  $("#seg").addEventListener("click", (e) => { const b = e.target.closest("button[data-tab]"); if (b) setTab(b.dataset.tab); });
  $("#prompt").addEventListener("input", autosize);
  $("#prompt").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); } });
  $("#send").onclick = send;
  $("#forget").onclick = async () => {
    if (!S.scope.size || (S.job && !S.job.done)) return;
    await api(`/api/forget?${q()}`, { scope: [...S.scope] }).catch(() => {});
    loadTalk(); toast("Started a new conversation for this scope.");
  };
  $("#sclose").onclick = () => showSheet(false);
  $("#scrim").onclick = () => showSheet(false);
  addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if ($("#sheet").classList.contains("show")) showSheet(false);
    else if (S.selected) closePanel();
  });
}

wire();
boot().catch((e) => toast(`Could not load: ${e.message}`, false, 10000));
