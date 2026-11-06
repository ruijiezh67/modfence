/* Alternative views of the same modules. Each one shares selection, scope, hover highlighting and change marks
   with the graph: a module is an element with class "mcard" and data-id, painted by paintAlt(). */
"use strict";

const VIEWS = [
  { id: "graph", label: "Graph", hint: "Modules and the imports between them" },
  { id: "layers", label: "Layers", hint: "Architecture layers, no lines until you hover" },
  { id: "outline", label: "Outline", hint: "Read the project like a document" },
  { id: "map", label: "Map", hint: "Area is lines of code; color shows what changed" },
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
  paintSelection();
  if (v === "graph") fitView(false);
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
  if (ri === real[0]) return "Entry points";
  if (ri === real[real.length - 1]) return "Foundations";
  return `Layer ${real.indexOf(ri) + 1}`;
}
function counts(id) {
  const { dep, use } = related(id);
  return `<span title="depends on">↓ ${dep.size}</span><span title="used by">↑ ${use.size}</span>`;
}
function cardBody(m) {
  const pre = parent(m.id);
  return `<div class="ct"><i class="dot"></i><b>${esc(label(m.id))}</b>${pre ? `<span class="pre">${esc(pre)}/</span>` : ""}</div>
    <div class="cd">${esc(m.doc || "No docstring")}</div>
    <div class="cm"><span>${m.files.length} file${m.files.length === 1 ? "" : "s"}</span><span>${m.lines} lines</span>${counts(m.id)}</div>`;
}
function wireCards(box) {
  box.querySelectorAll(".mcard").forEach((c) => {
    const id = c.dataset.id;
    c.addEventListener("click", (ev) => { if (ev.target.closest("[data-go],details,summary,[data-file]")) return; onNodeClick(id, ev); });
    c.addEventListener("keydown", (ev) => { if ((ev.key === "Enter" || ev.key === " ") && ev.target === c) { ev.preventDefault(); onNodeClick(id, ev); } });
    c.addEventListener("pointerenter", () => hoverNode(id, true));
    c.addEventListener("pointerleave", () => hoverNode(id, false));
  });
  box.querySelectorAll("[data-go]").forEach((b) => b.addEventListener("click", (ev) => { ev.stopPropagation(); select(b.dataset.go); }));
  box.querySelectorAll("[data-file]").forEach((b) => b.addEventListener("click", (ev) => { ev.stopPropagation(); openFile(b.dataset.file); }));
  box.onclick = (ev) => { if (!ev.target.closest(".mcard") && S.selected) closePanel(); };
}
function paintAlt(focus, rel) {
  document.querySelectorAll("#alt .mcard").forEach((n) => {
    const id = n.dataset.id;
    n.classList.toggle("selected", id === S.selected);
    n.classList.toggle("inscope", S.scope.has(id) && id !== S.selected);
    n.classList.toggle("dep", !!focus && rel.dep.has(id));
    n.classList.toggle("use", !!focus && rel.use.has(id));
    n.classList.toggle("faded", !!focus && id !== focus && !rel.dep.has(id) && !rel.use.has(id) && !S.scope.has(id));
    n.classList.toggle("changed", S.marks.changed.has(id));
    n.classList.toggle("ripple", S.marks.ripple.has(id) && !S.marks.changed.has(id));
  });
}
function revealCard(id) {
  const c = document.querySelector(`#alt .mcard[data-id="${CSS.escape(id)}"]`);
  if (c) c.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
}

/* ---------- Layers: bands, no lines ---------- */
function layersHTML() {
  const rows = altRows();
  return `<div class="layers">${rows.map((row, ri) => `
    <section class="band${row.every((id) => mod(id).kind === "tests") ? " tests" : ""}">
      <div class="blab"><b>${esc(rowName(row, ri, rows))}</b><span>${row.length} module${row.length === 1 ? "" : "s"}</span></div>
      <div class="tiles">${row.map((id) => `<div class="mcard tile${mod(id).kind === "tests" ? " tests" : ""}" tabindex="0" role="button" data-id="${esc(id)}">${cardBody(mod(id))}</div>`).join("")}</div>
    </section>`).join("")}
    <p class="foot">Higher layers import from lower ones. Hover a module to see its dependencies (blue) and dependents (clay).</p></div>`;
}

/* ---------- Outline: the project as a document ---------- */
function outlineHTML() {
  const g = S.graph, rows = altRows(), files = Object.keys(g.files).length;
  const lines = g.modules.reduce((a, m) => a + m.lines, 0);
  const chips = (ids, color) => ids.length ? ids.map((d) => `<button class="chip" data-go="${esc(d)}"><i style="background:var(${color})"></i>${esc(d)}</button>`).join("") : '<span class="none">none</span>';
  const sec = (id) => {
    const m = mod(id), { dep, use } = related(id);
    const flist = m.files.map((f) => {
      const fi = g.files[f], names = fi.names.slice(0, 8).map((n) => `<code>${esc(n.name)}</code>`).join(" ");
      return `<li><button class="fl" data-file="${esc(f)}">${esc(f.split("/").pop())}</button><span>${esc(fi.error || fi.doc || "")}</span>${names ? `<div class="nm">${names}</div>` : ""}</li>`;
    }).join("");
    return `<section class="mcard msec${m.kind === "tests" ? " tests" : ""}" tabindex="0" data-id="${esc(id)}">
      <div class="sh"><i class="dot"></i><h2>${esc(label(id))}</h2><span class="pre">${esc(id === "." ? "project root" : id + "/")}</span><span class="st">${m.files.length} files · ${m.lines} lines</span></div>
      <p class="sd">${esc(m.doc || "No docstring.")}</p>
      <div class="rel"><span class="k">Uses</span>${chips([...dep], "--blue")}</div>
      <div class="rel"><span class="k">Used by</span>${chips([...use], "--clay")}</div>
      <details><summary>${m.files.length} file${m.files.length === 1 ? "" : "s"} and public names</summary><ul>${flist}</ul></details>
    </section>`;
  };
  return `<article class="doc">
    <header><div class="eyebrow">Project</div><h1>${esc(g.name)}</h1>
      <p>${g.modules.length} modules, ${files} files, ${lines.toLocaleString()} lines. Read from the top: entry points first, foundations last. Click a section to ask about that module.</p></header>
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
  const W = box.clientWidth - 2 * 18 - (document.body.classList.contains("panel-open") && innerWidth > 760 ? 470 : 0);
  const H = box.clientHeight - 76 - 70;
  const items = S.graph.modules.map((m) => ({ id: m.id, v: Math.max(1, m.lines) })).sort((a, b) => b.v - a.v);
  const rects = squarify(items, 0, 0, Math.max(200, W), Math.max(200, H));
  box.innerHTML = `<div class="map" style="width:${Math.max(200, W)}px;height:${Math.max(200, H)}px">${rects.map((r) => {
    const m = mod(r.id), small = r.w < 130 || r.h < 74;
    return `<div class="mcard cell${m.kind === "tests" ? " tests" : ""}${small ? " small" : ""}" tabindex="0" role="button" data-id="${esc(r.id)}"
      style="left:${r.x}px;top:${r.y}px;width:${r.w}px;height:${r.h}px" title="${esc(r.id)} · ${m.lines} lines">
      <div class="ct"><i class="dot"></i><b>${esc(label(r.id))}</b></div><div class="cm"><span>${m.lines} lines</span><span>${m.files.length} files</span></div>
      ${small ? "" : `<div class="cd">${esc(m.doc || "")}</div>`}</div>`;
  }).join("")}</div>`;
}
let mapT = 0;
addEventListener("resize", () => { clearTimeout(mapT); mapT = setTimeout(() => { if (S.view === "map") renderAltView(); }, 120); });

function wireViews() {
  $("#viewseg").innerHTML = VIEWS.map((v) => `<button data-view="${v.id}" title="${esc(v.hint)}" aria-pressed="false">${esc(v.label)}</button>`).join("");
  $("#viewseg").addEventListener("click", (e) => { const b = e.target.closest("button[data-view]"); if (b) setView(b.dataset.view); });
}
