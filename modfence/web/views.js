/* Alternative views of the same modules. Each shares selection, fence, hover highlighting and change marks with the
   graph: a module is an element with class "mcard" and data-id, painted by paintAlt(). */
"use strict";

const VIEWS = [
  { id: "graph", label: "Graph", hint: "Modules and the imports between them" },
  { id: "layers", label: "Layers", hint: "Architecture layers, no lines until you hover" },
  { id: "outline", label: "Outline", hint: "Read the project like a document" },
  { id: "map", label: "Map", hint: "Area is lines of code; color shows what changed" },
];
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

/* View Transitions: the browser snapshots old and new DOM and morphs elements that share a view-transition-name,
   so a module's tile in Layers flies to its cell in Map. Falls back to an instant swap. */
function transition(fn) {
  if (!document.startViewTransition || reduced()) { fn(); return; }
  document.startViewTransition(fn);
}
const vtName = (id) => "m-" + id.replace(/[^A-Za-z0-9_-]/g, "_");

function setView(v) {
  if (!VIEWS.some((x) => x.id === v)) v = "graph";
  const first = !S.view || !document.body.dataset.view;
  const apply = () => {
    S.view = v;
    store.set("modfence.view", v);
    document.body.dataset.view = v;
    document.querySelectorAll("#viewseg button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === v)));
    $("#canvas").hidden = v !== "graph";
    $("#alt").hidden = v === "graph";
    renderAltView();
    paintSelection();
    if (v === "graph") fitView(false);
    slideInk($("#viewseg"), "[aria-pressed=true]");
  };
  if (first || S.view === v) apply(); else transition(apply);
}

function renderAltView() {
  const box = $("#alt");
  if (!S.graph || S.view === "graph") { box.innerHTML = ""; return; }
  if (S.view === "layers") box.innerHTML = layersHTML();
  if (S.view === "outline") box.innerHTML = outlineHTML();
  if (S.view === "map") renderMap(box);
  wireCards(box);
  paintSelection();
}

/* ---------- shared pieces ---------- */
function altRows() {
  // Reading order for the HTML views: entry points first, foundations next, tests last.
  const rows = S.rows || [], isTests = (r) => r.every((id) => mod(id).kind === "tests");
  return [...rows.filter((r) => !isTests(r)), ...rows.filter(isTests)];
}
function rowName(row, ri, rows) {
  if (row.every((id) => mod(id).kind === "tests")) return "Tests";
  const real = rows.map((r, i) => (r.every((id) => mod(id).kind === "tests") ? -1 : i)).filter((i) => i >= 0);
  if (real.length === 1) return "Modules";
  if (ri === real[0]) return "Entry points";
  if (ri === real[real.length - 1]) return "Foundations";
  return `Layer ${real.indexOf(ri) + 1}`;
}
function counts(id) {
  const { dep, use } = related(id);
  return `<span title="uses ${dep.size}"><i class="sw dep"></i>${dep.size}</span><span title="used by ${use.size}"><i class="sw use"></i>${use.size}</span>`;
}
function cardBody(m) {
  const pre = parent(m.id);
  return `<div class="ct"><b class="mono">${esc(label(m.id))}</b>${pre ? `<span class="pre mono">${esc(pre)}/</span>` : ""}<span class="badge mono" data-badge></span></div>
    <div class="cd">${esc(mdoc(m) || "Not described yet")}</div>
    <div class="cm mono"><span>${plural(m.files.length, "file")}</span><span>${m.lines} ln</span>${counts(m.id)}</div>`;
}
const cardAttrs = (id, cls) => `class="mcard ${cls}${mod(id).kind === "tests" ? " tests" : ""}" tabindex="0" role="button" data-id="${esc(id)}" style="view-transition-name:${vtName(id)}"`;

function wireCards(box) {
  box.querySelectorAll(".mcard").forEach((c) => {
    const id = c.dataset.id;
    c.addEventListener("click", (ev) => { if (ev.target.closest("[data-go],details,summary,[data-file]")) return; onNodeClick(id, ev); });
    c.addEventListener("keydown", (ev) => { if ((ev.key === "Enter" || ev.key === " ") && ev.target === c) { ev.preventDefault(); onNodeClick(id, ev); } });
    c.addEventListener("pointerenter", () => hoverNode(id, true));
    c.addEventListener("pointerleave", () => hoverNode(id, false));
    c.addEventListener("focus", () => hoverNode(id, true));
    c.addEventListener("blur", () => hoverNode(id, false));
  });
  box.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", (ev) => { ev.stopPropagation(); select(b.dataset.go); }));
  box.querySelector("[data-maptests]")?.addEventListener("click", () => { S.mapTests = !S.mapTests; store.set("modfence.maptests", S.mapTests ? "1" : ""); transition(renderAltView); });
  box.onclick = (ev) => { if (!ev.target.closest(".mcard,button") && S.selected) closePanel(); };
}
// Spotlight: a soft highlight follows the pointer across a card's border (set once on the container, read by CSS).
addEventListener("pointermove", (e) => {
  const c = e.target.closest && e.target.closest("#alt .mcard");
  if (!c) return;
  const r = c.getBoundingClientRect();
  c.style.setProperty("--mx", `${e.clientX - r.left}px`);
  c.style.setProperty("--my", `${e.clientY - r.top}px`);
}, { passive: true });

function paintAlt(focus, rel) {
  document.querySelectorAll("#alt .mcard").forEach((n) => {
    const id = n.dataset.id;
    n.classList.toggle("selected", id === S.selected);
    n.classList.toggle("fenced", fenced(id));
    n.classList.toggle("dep", !!focus && rel.dep.has(id));
    n.classList.toggle("use", !!focus && rel.use.has(id));
    n.classList.toggle("faded", !!focus && id !== focus && !rel.dep.has(id) && !rel.use.has(id) && !fenced(id) && !S.marks.changed.has(id));
    n.classList.toggle("changed", S.marks.changed.has(id));
    n.classList.toggle("ripple", S.marks.ripple.has(id) && !S.marks.changed.has(id));
    const b = n.querySelector("[data-badge]");
    if (b) {
      const st = S.marks.stats[id];
      b.className = `badge mono${st ? " diff" : fenced(id) ? " fence" : ""}`;
      b.innerHTML = st ? `<span class="plus">+${st.plus}</span> <span class="minus">−${st.minus}</span>` : fenced(id) ? "editable" : "";
    }
    n.setAttribute("aria-label", `Module ${shown(id)}${stateWords(id, rel, focus).length ? ", " + stateWords(id, rel, focus).join(", ") : ""}`);
  });
}
function revealCard(id) {
  const c = document.querySelector(`#alt .mcard[data-id="${CSS.escape(id)}"]`);
  if (c) c.scrollIntoView({ block: "nearest", behavior: reduced() ? "auto" : "smooth" });
}

/* ---------- Layers: bands, no lines ---------- */
function layersHTML() {
  const rows = altRows();
  return `<div class="layers">${rows.map((row, ri) => `
    <section class="band${row.every((id) => mod(id).kind === "tests") ? " tests" : ""}">
      <div class="blab"><b>${esc(rowName(row, ri, rows))}</b><span class="mono">${row.length}</span></div>
      <div class="tiles">${row.map((id) => `<div ${cardAttrs(id, "tile")}>${cardBody(mod(id))}</div>`).join("")}</div>
    </section>`).join("")}
    <p class="foot">Each layer uses only layers below it. Hover a module to see what it uses and who uses it.</p></div>`;
}

/* ---------- Outline: the project as a document ---------- */
function outlineHTML() {
  const g = S.graph, rows = altRows(), files = Object.keys(g.files).length;
  const lines = g.modules.reduce((a, m) => a + m.lines, 0);
  const chips = (ids, kind) => ids.length ? ids.map((d) => `<button class="chip mono" data-go="${esc(d)}"><i class="sw ${kind}"></i>${esc(shown(d))}</button>`).join("") : '<span class="none">none</span>';
  const sec = (id) => {
    const m = mod(id), { dep, use } = related(id);
    const flist = m.files.map((f) => {
      const fi = g.files[f], names = fi.names.slice(0, 8).map((n) => `<code>${esc(n.name)}</code>`).join(" ");
      return `<li><span class="fl mono">${esc(f.split("/").pop())}</span><span>${esc(fi.error || fi.doc || "")}</span>${names ? `<div class="nm">${names}</div>` : ""}</li>`;
    }).join("");
    return `<section ${cardAttrs(id, "msec")}>
      <div class="sh"><h2 class="mono">${esc(shown(id))}</h2><span class="badge mono" data-badge></span><span class="st mono">${plural(m.files.length, "file")} · ${m.lines} ln</span></div>
      <p class="sd">${esc(mdoc(m) || "Not described yet.")}</p>
      <div class="rel"><span class="k">Uses</span>${chips([...dep], "dep")}</div>
      <div class="rel"><span class="k">Used by</span>${chips([...use], "use")}</div>
      <details><summary>${plural(m.files.length, "file")} and their public names</summary><ul>${flist}</ul></details>
    </section>`;
  };
  return `<article class="doc">
    <header><h1 class="mono">${esc(g.name)}</h1>
      <p>${plural(g.modules.length, "module")}, ${plural(files, "file")}, ${lines.toLocaleString()} lines. Read from the top: entry points first, foundations last.</p></header>
    ${rows.map((row, ri) => `<div class="part"><div class="eyebrow">${esc(rowName(row, ri, rows))}</div>${row.map(sec).join("")}</div>`).join("")}
  </article>`;
}

/* ---------- Map: squarified treemap, area = lines ---------- */
function squarify(items, x, y, w, h) {
  // Bruls et al. squarified treemap. items: [{id, v}] sorted by v desc; returns [{id, x, y, w, h}].
  const out = [], total = items.reduce((a, b) => a + b.v, 0) || 1;
  let rest = items.map((it) => ({ ...it, a: (it.v / total) * w * h }));
  const worst = (row, side) => {
    const s = row.reduce((a, r) => a + r.a, 0), mx = Math.max(...row.map((r) => r.a)), mn = Math.min(...row.map((r) => r.a));
    return Math.max((side * side * mx) / (s * s), (s * s) / (side * side * mn));
  };
  while (rest.length) {
    const side = Math.min(w, h);
    let row = [rest[0]], k = 1;
    while (k < rest.length && worst([...row, rest[k]], side) <= worst(row, side)) row.push(rest[k++]);
    rest = rest.slice(k);
    const s = row.reduce((a, r) => a + r.a, 0);
    if (w >= h) { const cw = s / h; let cy = y; row.forEach((r) => { const ch = r.a / cw; out.push({ id: r.id, x, y: cy, w: cw, h: ch }); cy += ch; }); x += cw; w -= cw; }
    else { const ch = s / w; let cx = x; row.forEach((r) => { const rw = r.a / ch; out.push({ id: r.id, x: cx, y, w: rw, h: ch }); cx += rw; }); y += ch; h -= ch; }
  }
  return out;
}
function renderMap(box) {
  if (S.mapTests === undefined) S.mapTests = !!store.get("modfence.maptests");
  const hasTests = S.graph.modules.some((m) => m.kind === "tests");
  const W = Math.max(240, box.clientWidth - 32), H = Math.max(200, box.clientHeight - 32 - 40);
  const items = S.graph.modules.filter((m) => S.mapTests || m.kind !== "tests").map((m) => ({ id: m.id, v: Math.max(1, m.lines) })).sort((a, b) => b.v - a.v);
  const rects = squarify(items, 0, 0, W, H);
  box.innerHTML = `<div class="maphead"><span>Area = lines of code.</span>${hasTests ? `<button class="btn" type="button" data-maptests aria-pressed="${S.mapTests}">Include tests</button>` : ""}</div>
    <div class="map" style="width:${W}px;height:${H}px">${rects.map((r) => {
      const m = mod(r.id), small = r.w < 140 || r.h < 80, tiny = r.w < 70 || r.h < 40;
      return `<div ${cardAttrs(r.id, `cell${small ? " small" : ""}${tiny ? " tiny" : ""}`)} title="${esc(shown(r.id))} · ${m.lines} lines" data-pos="${r.x},${r.y},${r.w},${r.h}">
        <div class="ct"><b class="mono">${esc(label(r.id))}</b><span class="badge mono" data-badge></span></div><div class="cm mono"><span>${m.lines} ln</span></div>
        ${small ? "" : `<div class="cd">${esc(mdoc(m))}</div>`}</div>`;
    }).join("")}</div>`;
  box.querySelectorAll(".cell").forEach((c) => { const [x, y, w, h] = c.dataset.pos.split(",").map(Number); Object.assign(c.style, { left: x + "px", top: y + "px", width: w + "px", height: h + "px" }); });
}
let mapT = 0;
addEventListener("resize", () => { clearTimeout(mapT); mapT = setTimeout(() => { if (S.view === "map") renderAltView(); slideInk($("#viewseg"), "[aria-pressed=true]"); slideInk($("#seg"), "[aria-selected=true]"); }, 120); });

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

function wireViews() {
  $("#viewseg").innerHTML = VIEWS.map((v, i) => `<button type="button" data-view="${v.id}" title="${esc(v.hint)} (${i + 1})" aria-pressed="false">${esc(v.label)}<kbd>${i + 1}</kbd></button>`).join("");
  $("#viewseg").addEventListener("click", (e) => { const b = e.target.closest("button[data-view]"); if (b) setView(b.dataset.view); });
  document.fonts?.ready.then(() => { slideInk($("#viewseg"), "[aria-pressed=true]"); slideInk($("#seg"), "[aria-selected=true]"); });
}
