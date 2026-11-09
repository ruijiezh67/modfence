/* modfence UI: see the modules, fence the ones the agent may edit, give an instruction, review what changed. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const NODE_W = 220, NODE_H = 76, GAP_X = 36, GAP_Y = 52;
const store = { get(k) { try { return localStorage.getItem(k); } catch { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch {} } };
const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || "");

const S = {
  projects: [], p: 0, graph: null, full: null, focus: "", level: null, roles: null, role: null, calls: null, pos: {}, rows: [], view: "graph", selected: null, scope: new Set(), readOnly: false,
  tab: "over", marks: { changed: new Set(), ripple: new Set(), stats: {} }, job: null, tasks: [], claude: null, fn: {},
  cam: { x: 0, y: 0, k: 1 }, camV: { x: 0, y: 0, k: 0 }, camTarget: null, raf: 0, userCam: false,
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
  S.projects = projects; S.claude = claude;
  const saved = Number(store.get("modfence.project") || 0);
  S.p = projects[saved] ? saved : 0;
  $("#picker").innerHTML = projects.map((p) => `<option value="${p.i}">${esc(p.name)}</option>`).join("");
  const hp = new URLSearchParams(location.hash.slice(1));
  if (hp.get("p") && projects[+hp.get("p")]) S.p = +hp.get("p");
  $("#picker").value = S.p;
  $("#picker").hidden = projects.length < 2; // one project (the usual case): nothing to pick
  if (IS_MAC) $("#chint").innerHTML = "<kbd>⌘</kbd> <kbd>Enter</kbd> to send";
  await loadGraph(true);
  setView(hp.get("v") || store.get("modfence.view") || "graph");
  if (hp.get("m") && mod(hp.get("m"))) {
    if (hp.get("tab")) S.tab = hp.get("tab");
    select(hp.get("m"));
    const f = (hp.get("f") || "").split(/[+ ]/).filter(mod); // #...&f=a+b: open with that fence (and its run log)
    if (f.length) { S.scope = new Set([hp.get("m"), ...f]); afterFenceChange(); }
  }
}

async function loadGraph(fit) {
  if (!S.full) $("#stats").textContent = "Reading the project…"; // a big project's first scan takes seconds
  S.full = await api(`/api/graph?${q()}`);
  S.fn = {};
  try { S.roles = await api(`/api/roles?${q()}`); } catch { S.roles = null; }
  try { S.docs = await api(`/api/docs?${q()}`); } catch { S.docs = { docs: [], links: {} }; }
  if (!S.level) S.level = S.roles?.areas?.length ? "areas" : S.roles && S.roles.roles.length ? "roles" : "modules";
  regroup();
  if (S.roles && S.roles.status === "none" && S.full.modules.length > ROLE_AT && S.claude && !S.proposed) { S.proposed = true; proposeRoles(); }
  else if (S.roles?.roles.length && !S.roles.areas?.length && S.claude && !S.proposedAreas) { S.proposedAreas = true; proposeAreas(); }
  renderAltView();
  updateStats();
  if (fit) fitView(false);
  loadTasks();
  if (S.selected && !mod(S.selected)) closePanel();
  else if (S.selected) { renderHeader(); renderOverview(); renderFence(); }
}

function mod(id) { return S.graph && (S.graph.modules.find((m) => m.id === id) || S.full.modules.find((m) => m.id === id)); }
const label = (id) => (id === "." ? "(root)" : id.endsWith("/") ? id.slice(0, -1).split("/").pop() + "/" : id.split("/").pop());
const parent = (id) => (id.includes("/") ? id.slice(0, id.lastIndexOf("/")) : "");
const shown = (id) => (id === "." ? "(root)" : id.startsWith("role:") ? rname(id.slice(5)) : id.startsWith("area:") ? ((S.roles?.areas || []).find((a) => a.id === id.slice(5)) || {}).name || id : id.startsWith("part:") || id.startsWith("dir:") ? (mod(id)?.label || id.slice(id.indexOf(":") + 1)) : id);
const moduleOf = (p) => { // mirrors analyze.module_of
  const d = p.includes("/") ? p.slice(0, p.lastIndexOf("/")) : "";
  const own = p.endsWith(".py") && !p.endsWith("/__init__.py") && p !== "__init__.py";
  return d && !(own && (S.graph.split || []).includes(d)) ? d : own ? p : d || ".";
};
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
const mdoc = (m) => m.doc || (S.full.ai_purposes || {})[m.id] || "";  // the author's docstring, else a cached summary
const maxLines = () => Math.max(1, ...S.graph.modules.map((m) => m.lines));

function updateStats() {
  const g = S.full, files = Object.keys(g.files).length, lines = g.modules.reduce((a, m) => a + m.lines, 0);
  $("#stats").textContent = `${plural(g.modules.length, "module")} · ${plural(files, "file")} · ${lines.toLocaleString()} lines`;
}

/* ---------------- big projects: folders with many modules shown as one node ---------------- */
const GROUP_AT = 60; // ponytail: fixed; a project with more modules than this opens folder by folder
function viewGraph(full, focus) {
  // Modules outside the open folder are grouped by their first differing path segment, so a 400-module project
  // shows a few dozen nodes. A folder holding one module shows that module.
  if (full.modules.length <= GROUP_AT) return full;
  const f = focus ? focus.split("/") : [];
  const keyOf = (id) => {
    if (id === ".") return id;
    const s = id.split("/");
    let k = 0;
    while (k < f.length && k < s.length && s[k] === f[k]) k++;
    return k >= s.length ? id : s.slice(0, k + 1).join("/");
  };
  const groups = new Map(), idOf = {}, modules = [];
  full.modules.forEach((m) => { const k = keyOf(m.id); if (!groups.has(k)) groups.set(k, []); groups.get(k).push(m); });
  groups.forEach((ms, k) => {
    if (ms.length === 1) { idOf[ms[0].id] = ms[0].id; modules.push(ms[0]); return; }
    const gid = k + "/";
    ms.forEach((m) => (idOf[m.id] = gid));
    modules.push({ id: gid, group: true, kind: ms.every((m) => m.kind === "tests") ? "tests" : "group", members: ms.map((m) => m.id),
      files: ms.flatMap((m) => m.files), lines: ms.reduce((a, m) => a + m.lines, 0), names: [], doc: `${ms.length} modules`, mtime: 0 });
  });
  const edges = new Map();
  full.edges.forEach((e) => {
    const a = idOf[e.source], b = idOf[e.target];
    if (a === b) return;
    if (!edges.has(a + "\n" + b)) edges.set(a + "\n" + b, { source: a, target: b, receipts: [] });
    edges.get(a + "\n" + b).receipts.push(...e.receipts);
  });
  return { ...full, modules: modules.sort((x, y) => x.id.localeCompare(y.id)), edges: [...edges.values()] };
}
function regroup() {
  if (!(S.roles && S.roles.roles.length) && ["areas", "roles", "parts"].includes(S.level)) S.level = "modules";
  if (S.level === "areas" && !S.roles.areas?.length) S.level = "roles";
  S.hiddenLinks = 0; S.outside = 0;
  if (S.picked) unpick();
  S.graph = S.level === "areas" ? areaGraph() : S.level === "roles" ? roleGraph() : S.level === "parts" ? partGraph(S.role) : viewGraph(S.full, S.focus);
  document.body.dataset.level = S.level;
  layout();
  drawGraph();
  renderCrumbs();
}
/* ---------------- levels: 1 roles → 2 parts of a role → 3 functions and classes ---------------- */
// Roles are what the system does (observer, segmenter ...), proposed by modfence and confirmed or renamed by you.
// A role's parts are the modules its files live in; the lowest level is a graph of functions and classes, across files.
const ROLE_AT = 12; // ponytail: below this many modules the module graph already reads as roles, so none are proposed
const rname = (rid) => (S.roles?.roles.find((r) => r.id === rid) || {}).name || rid;
function fileRoles() {
  const out = {};
  (S.roles?.roles || []).forEach((r) => r.files.forEach((f) => (out[f] = r.id)));
  (S.roles?.unassigned || []).forEach((f) => (out[f] = "?"));
  return out;
}
function aggregate(nodeOf) { // edges between view nodes from the file-level import receipts
  const edges = new Map();
  S.full.edges.forEach((e) => e.receipts.forEach((r) => {
    const a = nodeOf(r.file), b = nodeOf(r.target_file);
    if (!a || !b || a === b) return;
    const k = a + "\n" + b;
    if (!edges.has(k)) edges.set(k, { source: a, target: b, receipts: [] });
    edges.get(k).receipts.push(r);
  }));
  return [...edges.values()];
}
const KEEP_LINKS = 3; // ponytail: roles import each other freely; the 3 strongest links per node keep the picture readable
function prune(edges) { // never drops an edge that closes a loop: those are the ones worth seeing
  const by = new Map(), back = loopEdges(edges);
  edges.forEach((e) => { if (!by.has(e.source)) by.set(e.source, []); by.get(e.source).push(e); });
  const kept = [...by.values()].flatMap((l) => l.sort((a, b) => b.receipts.length - a.receipts.length).filter((e, i) => i < KEEP_LINKS || back.has(e)));
  S.hiddenLinks = edges.length - kept.length;
  return kept;
}
// The imports that close a loop, by structure and strength, never by name: keep the strongest imports while the graph
// stays acyclic (greedy, strongest first); each import that would close a loop is a loop edge, the weakest link of
// that loop and so the cheapest one to cut. ponytail: O(E·(V+E)) reachability, fine for the few hundred edges drawn.
function loopEdges(edges) {
  const adj = {}, back = new Set();
  const reaches = (a, b) => { const seen = new Set([a]), st = [a]; while (st.length) { const v = st.pop(); if (v === b) return true; for (const w of adj[v] || []) if (!seen.has(w)) { seen.add(w); st.push(w); } } return false; };
  [...edges].sort((x, y) => y.receipts.length - x.receipts.length || (x.source + "\n" + x.target).localeCompare(y.source + "\n" + y.target))
    .forEach((e) => { if (reaches(e.target, e.source)) back.add(e); else (adj[e.source] ||= []).push(e.target); });
  return back;
}
// Cross-cutting files (roles.kinds): entry points, doors (HTTP routes) and shared config are not features, so they are
// not boxes, draw no edges and stay out of a role's fence: the side bar lists them with the role they serve.
const kindOf = (f) => (S.roles?.kinds || {})[f];
const ownFiles = (r) => r.files.filter((f) => !kindOf(f));
const doorsOf = (rid) => Object.keys(S.roles?.doors || {}).filter((f) => S.roles.doors[f] === rid).sort();
function roleNode(r, kind = "group") {
  const files = ownFiles(r), doors = doorsOf(r.id), lines = files.reduce((a, f) => a + (S.full.files[f]?.lines || 0), 0);
  return { id: "role:" + r.id, role: r.id, kind: r.name === "shared" ? "tests" : kind, label: r.name,
    meta: plural(files.length, "file"), doors, // doors and roles are in the side bar: the box stays short
    files, lines, names: [], doc: r.purpose || "", members: [...new Set(files.map((f) => S.full.files[f].module))] };
}
function usersOf(files) { // roles whose code imports any of these files
  const fs = new Set(files), fr = fileRoles(), out = new Set();
  S.full.edges.forEach((e) => e.receipts.forEach((r) => { if (fs.has(r.target_file) && !fs.has(r.file) && fr[r.file] && !kindOf(r.file)) out.add(fr[r.file]); }));
  return [...out];
}
// Golden rule 2: a role named like its function ("recorder" in recorder) reads as that function's core, so the two
// levels never show two different boxes with one name.
function boxName(m) {
  const n = m.label || label(m.id);
  if (!m.role || !S.roles?.areas) return n;
  const a = (S.roles.areas || []).find((x) => x.roles.includes(m.role));
  return a && a.name.toLowerCase() === n.toLowerCase() ? `${n} core` : n;
}
function roleGraph() {
  const fr = fileRoles(), rs = [...S.roles.roles];
  if (S.roles.unassigned.length) rs.push({ id: "?", name: "not placed yet", purpose: "New files: place them in a role.", files: S.roles.unassigned });
  const area = S.area && (S.roles.areas || []).find((a) => a.id === S.area), inArea = area && new Set(area.roles);
  // Inside an area, a role's links often lead out of it: the roles at the other end are drawn too, faded ("ghosts",
  // labelled with their area), so every box shows what it is tied to. Click one to go there.
  const all = rs.filter((r) => ownFiles(r).length).map((r) => roleNode(r));
  const nodeOf = (f) => { const r = S.roles.doors?.[f] || fr[f]; return r && "role:" + r; };
  const raw = aggregate((f) => !kindOf(f) && nodeOf(f));
  const edges = linked(all, inArea ? raw : prune(raw), nodeOf, (r) => "role:" + r); // inside a function: few boxes, every link
  if (!inArea) return { ...S.full, modules: all, edges };
  // The outside is drawn at the level the user came from: each other function (first level) is one faded box, and
  // every link from a role here to anything in it is merged into one line. The function itself is a frame around
  // its roles (drawFrame), so inside and outside read at a glance.
  const mine = new Set(all.filter((b) => inArea.has(b.role)).map((b) => b.id)), ar = areaOf();
  const outer = (id) => (mine.has(id) ? id : ar[id.slice(5)] && ar[id.slice(5)] !== S.area ? "area:" + ar[id.slice(5)] : null);
  const merged = new Map();
  edges.forEach((e) => {
    const a = outer(e.source), b = outer(e.target);
    if (!a || !b || a === b || (!mine.has(a) && !mine.has(b))) return;
    const k = `${a}\n${b}\n${e.kind || ""}`;
    if (!merged.has(k)) merged.set(k, { source: a, target: b, kind: e.kind, n: e.n, receipts: [] });
    merged.get(k).receipts.push(...e.receipts);
  });
  const fns = new Map(areaBoxes().map((b) => [b.id, b]));
  const ghosts = [...new Set([...merged.values()].flatMap((e) => [e.source, e.target]).filter((id) => !mine.has(id)))]
    .filter((id) => fns.has(id)).map((id) => ({ ...fns.get(id), ghost: true, meta: "another function" }));
  return { ...S.full, edges: [...merged.values()].filter((e) => mine.has(e.source) || fns.has(e.source)),
    modules: [...all.filter((b) => mine.has(b.id)), ...ghosts], frame: area.name };
}
function partGraph(rid) {
  const fr = fileRoles(), mine = new Set(Object.keys(fr).filter((f) => fr[f] === rid && !kindOf(f)));
  // Only the role's own parts are drawn: at most 8, grouped on the server by shared file-name words, else folders
  // (roles.role_parts). A small role shows its files.
  const named = (S.roles.roles.find((x) => x.id === rid) || {}).parts || {};
  const key = (f) => "part:" + (named[f] || f);
  const parts = new Map();
  mine.forEach((f) => { const d = key(f); if (!parts.has(d)) parts.set(d, []); parts.get(d).push(f); });
  const short = (p) => (p.endsWith("/") ? p.split("/").slice(-3).join("/") : p); // demo_lab/service/demo/capture/ -> demo/capture/
  const nodes = [...parts].map(([d, fs]) => ({ id: d, kind: "module", label: short(d.slice(5)),
    meta: fs.length === 1 ? fs[0].split("/").slice(-3, -1).join("/") + "/" : plural(fs.length, "file"),
    files: fs.sort(), names: [], doc: fs.map((f) => S.full.files[f].doc).find(Boolean) || "", lines: fs.reduce((a, f) => a + S.full.files[f].lines, 0) }));
  const edges = prune(aggregate((f) => (mine.has(f) ? key(f) : null)));
  S.outside = aggregate((f) => (mine.has(f) ? "in" : fr[f] ? "out" : null)).reduce((a, e) => a + e.receipts.length, 0);
  return { ...S.full, modules: nodes, edges };
}
function pick(id) { // a click only selects; the card below says what it is and opens it on purpose
  S.picked = id;
  const m = mod(id), card = $("#pick"), area = id.startsWith("area:"), role = id.startsWith("role:") || area, folder = !!m.group, plain = S.level === "modules";
  const name = m.label || shown(id);
  // a side bar, read top to bottom: what it is, what to do, then the facts behind it (uses, used by, files)
  // each link in a few plain words, strongest first; the names behind it are in the hover text, not here
  const link = (e, other) => `<li><button type="button" class="lk" data-go="${esc(other)}">${esc(shown(other))}</button><span>${esc(linkPhrase(e))}</span></li>`;
  const strong = (a, b) => b.receipts.length - a.receipts.length;
  const out = (S.graph.edges || []).filter((e) => e.source === id).sort(strong), inn = (S.graph.edges || []).filter((e) => e.target === id).sort(strong);
  const mine = new Set(m.files), shared = [...new Set(S.full.edges.flatMap((e) => e.receipts).filter((r) => mine.has(r.file) && kindOf(r.target_file) === "shared").map((r) => r.target_file))].sort();
  const doc = folder ? "" : m.doc || mdoc(m);
  const fdoc = (f) => S.full.files[f]?.doc || "";
  card.innerHTML = `<div class="pk"><b>${esc(name)}</b><button type="button" class="btn quiet" data-x aria-label="Close">${X_ICON}</button></div>`
    + `<div class="pm mono">${plural(m.files.length, "file")} · ${m.lines.toLocaleString()} ln</div>`
    + (doc ? `<p>${esc(doc)}</p>` : `<p class="none">No description in the code.</p>`)
    // golden rule 2: say what to change right here; the box is the fence, the map stays where it is
    + (folder || id === "role:?" ? "" : `<div class="ask"><textarea data-q rows="3" placeholder="What should change in ${esc(name)}?"></textarea>`
      + `<div class="route" data-route></div><div class="pa"><button type="button" class="btn primary" data-run>Build</button><span class="meta">Ctrl Enter</span></div></div>`)
    + (role || folder ? `<div class="pa"><button type="button" class="btn" data-open>${area ? "Open roles" : role ? "Open parts" : "Open folder"} ▸</button></div>` : "")
    + (out.length ? `<h4>Uses <i>${out.length}</i></h4><ul class="pl">${out.map((e) => link(e, e.target)).join("")}</ul>` : "")
    + (inn.length ? `<h4>Used by <i>${inn.length}</i></h4><ul class="pl">${inn.map((e) => link(e, e.source)).join("")}</ul>` : "")
    + (area ? `<h4>Roles <i>${m.roles.length}</i></h4><ul class="pf">${m.roles.map((r) => `<li><span class="mono">${esc(r.name)}</span><span>${esc(r.purpose || "")}</span></li>`).join("")}</ul>` : "")
    + (m.doors?.length ? `<h4>Start files and routes <i>${m.doors.length}</i></h4><ul class="pf">${m.doors.map((f) => `<li><span class="mono">${esc(f)}</span><span>${kindOf(f) === "entry" ? "starts the program" : "HTTP routes into it"} · read-only by default</span></li>`).join("")}</ul>` : "")
    + (shared.length ? `<h4>Shared config it reads <i>${shared.length}</i></h4><ul class="pf">${shared.map((f) => `<li><span class="mono">${esc(f)}</span><span>${esc(S.full.files[f]?.doc || "")} · read-only by default</span></li>`).join("")}</ul>` : "")
    + `<h4>Files <i>${m.files.length}</i></h4>` + (m.files.length <= 8 ? fileList(m.files, fdoc) : fileGroups(m).map(([title, fs]) => `<details class="fg"><summary>${esc(title)} <i>${fs.length}</i></summary>`
      + fileList(fs, fdoc) + `</details>`).join(""));
  const opening = card.hidden;
  card.hidden = false; card.scrollTop = 0;
  if (opening && !S.userCam) fitView();
  card.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => pick(b.dataset.go)));
  const files = plain ? [id] : m.files, label = role ? "role " + name : name, qbox = $("[data-q]", card);
  const showRoute = () => { const r = route(files), el = $("[data-route]", card), b = $("[data-run]", card); if (!el || !r) return;
    el.className = `route ${r.full ? "full" : "fast"}`;
    el.innerHTML = r.full ? `<b>Plans first</b>: the box ${esc(r.why.join("; ") || "is set to plan")}.` : `<b>Builds now</b>: one role, nothing outside depends on it.`;
    b.textContent = r.full ? "Plan" : "Build"; };
  showRoute();
  $("[data-route]", card)?.addEventListener("click", () => { const r = route(files); S.forceRoute = r && r.full ? "fast" : "full"; showRoute(); });
  const go = async () => { const prompt = qbox.value.trim(); if (!prompt || !S.claude) return; const r = route(files);
    openFence(files, label, m.doc); unpick();
    await startRun(prompt, files, false, r && !r.full ? "build" : "plan"); };
  $("[data-run]", card)?.addEventListener("click", go);
  qbox?.addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); go(); } });
  $("[data-open]", card)?.addEventListener("click", () => { unpick(); area ? openArea(id.slice(5)) : role ? openRole(id.slice(5)) : select(id); });
  $("[data-x]", card).onclick = unpick;
  (qbox || $("[data-open]", card) || $("[data-x]", card)).focus();
  paintSelection();
}
function unpick() { const was = !$("#pick").hidden; S.picked = null; $("#pick").hidden = true; paintSelection(); if (was && !S.userCam && !document.body.classList.contains("panel-open")) fitView(); }
function openRole(rid) {
  if (rid === "?" || !S.roles) { S.level = "parts"; S.role = rid; regroup(); fitView(); return; }
  const r = S.roles.roles.find((x) => x.id === rid);
  S.role = rid; S.area = areaOf()[rid] || S.area;
  S.level = "parts"; regroup(); fitView();
}
async function rolesDo(action, body, okText) {
  try { S.roles = await api(`/api/roles/${action}?${q()}`, body || {}); }
  catch (e) { toast(e.message, false); return false; }
  if (okText) toast(okText);
  regroup();
  return true;
}
async function proposeRoles() {
  $("#crumbs").hidden = false;
  $("#crumbs").innerHTML = `<em>Grouping the project into roles: folders and file names first, then one small-model call names them…</em>`;
  if (await rolesDo("propose", {}, null)) { S.level = "roles"; regroup(); fitView(); toast(`Roles proposed (${S.roles.how}${S.roles.cost_usd != null ? `, $${S.roles.cost_usd.toFixed(3)}` : ""}). Rename, move files, then confirm.`); proposeAreas(); }
}
async function proposeAreas() { // the first level: at most 7 areas of roles, one model call with the imports as evidence
  $("#crumbs").hidden = false;
  $("#crumbs").innerHTML = `<em>Grouping the roles into at most 7 areas…</em>`;
  if (await rolesDo("areas", {}, null)) { S.level = "areas"; S.area = null; regroup(); fitView(); toast(`Areas proposed (${S.roles.areas_how}${S.roles.areas_cost_usd != null ? `, $${S.roles.areas_cost_usd.toFixed(3)}` : ""}). Rename an area or move a role any time.`); }
}
const areaOf = () => Object.fromEntries((S.roles?.areas || []).flatMap((a) => a.roles.map((r) => [r, a.id])));
function openArea(aid) { S.area = aid; S.level = "roles"; regroup(); fitView(); }
function areaGraph() { // level 1: the areas, each the own files of its roles
  const fr = fileRoles(), ar = areaOf(), boxes = areaBoxes();
  const nodeOf = (f) => { const a = ar[S.roles.doors?.[f] || fr[f]]; return a && "area:" + a; };
  return { ...S.full, modules: boxes, edges: linked(boxes, aggregate((f) => !kindOf(f) && nodeOf(f)), nodeOf, (r) => ar[r] && "area:" + ar[r]) };
}
function areaBoxes() {
  return S.roles.areas.map((a) => {
    const rs = a.roles.map((rid) => S.roles.roles.find((r) => r.id === rid)).filter(Boolean), files = rs.flatMap(ownFiles);
    return { id: "area:" + a.id, area: a.id, kind: "group", label: a.name, meta: plural(files.length, "file"),
      files, lines: files.reduce((n, f) => n + (S.full.files[f]?.lines || 0), 0), names: [], doc: a.purpose || "",
      roles: rs, members: [...new Set(files.map((f) => S.full.files[f].module))] };
  }).filter((b) => b.files.length);
}
// Imports are not the only way boxes talk: programs call each other over HTTP or start each other (roles.runtime_links,
// dashed), and a box with no link at all is tied to the box it most often changed with in git (dotted). Every link
// keeps its evidence: the file and line, the route or file named, or the number of commits.
function linked(boxes, edges, nodeOf, roleBox) {
  const has = new Set(edges.map((e) => e.source + "\n" + e.target)), extra = new Map();
  (S.roles?.links || []).forEach((l) => {
    const a = nodeOf(l.file), b = nodeOf(l.target_file);
    if (!a || !b || a === b || has.has(a + "\n" + b)) return;
    const k = a + "\n" + b;
    if (!extra.has(k)) extra.set(k, { source: a, target: b, kind: l.kind === "copy" ? "copy" : "runtime", receipts: [] });
    extra.get(k).receipts.push({ file: l.file, line: l.line, target_file: l.target_file, name: ({ http: "HTTP ", runs: "runs ", copy: "copy of " })[l.kind] + l.name });
  });
  const all = [...edges, ...extra.values()], linkedBox = new Set(all.flatMap((e) => [e.source, e.target])), ids = new Set(boxes.map((b) => b.id));
  boxes.filter((b) => !linkedBox.has(b.id)).forEach((b) => { // an island: tie it to its strongest co-change partner
    let best = null;
    (S.roles?.cochange || []).forEach(([ra, rb, n]) => {
      const a = roleBox(ra), c = roleBox(rb);
      if (!a || !c || a === c || ![a, c].includes(b.id) || !ids.has(a) || !ids.has(c)) return;
      if (!best || n > best.n) best = { n, other: a === b.id ? c : a };
    });
    if (best) all.push({ source: b.id, target: best.other, kind: "cochange", n: best.n, receipts: [{ name: `changed together in ${best.n} commits` }] });
  });
  return all;
}
function renameRole(rid) {
  const r = S.roles.roles.find((x) => x.id === rid);
  const name = prompt(`Rename the role "${r.name}" (at most 3 words, 24 characters).\n\n${r.purpose || ""}`, r.name);
  if (name != null && name.trim() !== r.name) rolesDo("rename", { id: rid, name }, "Renamed. Files, fences and history keep it.");
}
function roleFiles(rid) { // a sheet: every file of the role, each with a role picker to move it
  const fr = fileRoles(), files = Object.keys(fr).filter((f) => fr[f] === rid).sort();
  const opts = (cur) => S.roles.roles.map((r) => `<option value="${esc(r.id)}"${r.id === cur ? " selected" : ""}>${esc(r.name)}</option>`).join("");
  $("#stitle").textContent = `${rid === "?" ? "Files not placed yet" : rname(rid)}: ${plural(files.length, "file")}`;
  $("#scode").innerHTML = `<p class="sub">Move a file by picking another role. ${rid === "?" ? "" : `<button class="btn quiet" type="button" data-newrole>New role…</button>`}</p>
    <ul class="rfiles">${files.map((f) => `<li><span class="mono">${esc(f)}</span><span class="d">${esc(S.full.files[f].doc || "")}</span><select data-f="${esc(f)}" aria-label="Role of ${esc(f)}">${rid === "?" ? `<option selected disabled>choose…</option>` : ""}${opts(rid)}</select></li>`).join("")}</ul>`;
  $("#scode").querySelectorAll("select[data-f]").forEach((s) => (s.onchange = async () => { if (await rolesDo("move", { path: s.dataset.f, id: s.value }, `Moved to ${rname(s.value)}.`)) s.closest("li").remove(); }));
  $("[data-newrole]", $("#scode"))?.addEventListener("click", () => { const n = prompt("Name of the new role (at most 3 words):"); if (n) rolesDo("add", { name: n }, "Role added; move files into it.").then(() => roleFiles(rid)); });
  showSheet(true);
}
function fenceRole(rid) { const r = S.roles.roles.find((x) => x.id === rid); fenceFiles(ownFiles(r), "role " + r.name, r.purpose); }
// The fence for a box without leaving the map: the run panel opens beside it and the level stays as it is.
function openFence(files, label, doc) {
  S.fenceLabel = label; S.fenceDoc = doc || "";
  S.selected = S.full.files[files[0]]?.module || files[0]; S.scope = new Set(files);
  document.body.classList.add("panel-open"); $("#panel").inert = false;
  renderHeader(); renderOverview(); afterFenceChange(); setTab("talk", false);
}
function fileList(files, fdoc) {
  return `<ul class="pf">${files.map((f) => `<li><span class="mono">${esc(f.split("/").pop())}</span>${fdoc(f) ? `<span>${esc(fdoc(f))}</span>` : ""}</li>`).join("")}</ul>`;
}
function fenceFiles(files, label, doc) { // a role or part as the fence: its files, under one name
  S.fenceLabel = label; S.fenceDoc = doc || ""; // set first: select() renders the panel for the fence, not one module
  select(S.full.files[files[0]].module, true);
  S.scope = new Set(files); renderHeader(); renderOverview();
  afterFenceChange();
  toast(`The agent may edit the ${plural(files.length, "file")} of ${label}.`);
}
function renderCrumbs() {
  const c = $("#crumbs"), big = S.full.modules.length > GROUP_AT, has = S.roles && S.roles.roles.length;
  const step = (n, text, attrs, cur) => `<button type="button" ${attrs}${cur ? ' aria-current="true"' : ""}><b>${n}</b> ${esc(text)}</button>`;
  let h = "";
  if (S.level === "modules") {
    if (!big && !has && S.full.modules.length <= ROLE_AT) { c.hidden = true; return; }
    const parts = S.focus ? S.focus.split("/") : [];
    h = (has ? step(1, S.roles.areas?.length ? "Areas" : "Roles", `data-lv="${S.roles.areas?.length ? "areas" : "roles"}"`) + `<span>/</span>` : "") + `<button type="button" data-f="" aria-current="${!S.focus}">${esc(S.full.name)}</button>`
      + parts.map((p, i) => `<span>/</span><button type="button" data-f="${esc(parts.slice(0, i + 1).join("/"))}">${esc(p)}</button>`).join("")
      + (big ? `<em>${plural(S.full.modules.length, "module")}, grouped by folder</em>` : "")
      + (!has && S.claude ? `<button type="button" class="act" data-propose>Group into roles</button>` : "");
  } else {
    const r = S.roles.roles.find((x) => x.id === S.role), A = (S.roles.areas || []).find((a) => a.id === S.area);
    let n = 1;
    if (S.roles.areas?.length) {
      h = step(n++, "Areas", 'data-lv="areas"', S.level === "areas");
      if (S.level !== "areas" && A) h += `<span>/</span>` + step(n++, A.name, `data-area="${esc(A.id)}"`, S.level === "roles");
    } else h = step(n++, "Roles", 'data-lv="roles"', S.level === "roles");
    if (S.level === "parts") h += `<span>/</span>` + step(n, S.role === "?" ? "not placed yet" : rname(S.role), `data-role="${esc(S.role)}"`, true);
    if (S.level === "areas") h += `<em title="${esc(S.roles.areas_how || "")}">${plural(S.roles.areas.length, "area")}</em><button type="button" class="act q" data-regroup>Regroup areas</button><button type="button" class="act q" data-skills>Skills for this project</button><button type="button" class="act q" data-lv="modules">All modules</button>`;
    if (S.level === "roles" && A) h += `<button type="button" class="act q" data-arename>Rename area</button>`;
    if (S.hiddenLinks && !S.dense) h += `<em title="Strongest ${KEEP_LINKS} links per box">${S.hiddenLinks} weak links hidden</em>`;
    if (S.level === "roles" && !A) h += `<em title="${esc(S.roles.how || "")}">${S.roles.status === "confirmed" ? "Confirmed" : "Proposed"}</em>`
      + (S.roles.status !== "confirmed" ? `<button type="button" class="act" data-confirm>Confirm roles</button>` : "") + `<button type="button" class="act q" data-propose>Propose again</button><button type="button" class="act q" data-lv="modules">All modules</button>`;
    if (S.level === "parts" && r && S.outside) h += `<em title="${esc(r.purpose || "")}">${S.outside} imports to other roles</em>`;
    if (r && S.level !== "roles") h += `<button type="button" class="act q" data-rename>Rename</button><button type="button" class="act q" data-files>Files</button><button type="button" class="act" data-fence>Fence this role</button>`;
    if (S.role === "?" && S.level !== "roles") h += `<button type="button" class="act" data-files>Place files</button>`;
  }
  c.hidden = false;
  c.innerHTML = h + roundLine();
  c.querySelectorAll("[data-f]").forEach((b) => (b.onclick = () => { S.focus = b.dataset.f; regroup(); fitView(); }));
  c.querySelectorAll("[data-lv]").forEach((b) => (b.onclick = () => { S.level = b.dataset.lv; regroup(); fitView(); }));
  c.querySelectorAll("[data-role]").forEach((b) => (b.onclick = () => openRole(b.dataset.role)));
  c.querySelectorAll("[data-area]").forEach((b) => (b.onclick = () => openArea(b.dataset.area)));
  $("[data-skills]", c)?.addEventListener("click", openSkills);
  $("[data-regroup]", c)?.addEventListener("click", () => confirm("Group the roles into areas again? Your area names and moves are replaced.") && proposeAreas());
  $("[data-arename]", c)?.addEventListener("click", () => { const a = S.roles.areas.find((x) => x.id === S.area), n = prompt(`Rename the area "${a.name}":`, a.name); if (n && n.trim() !== a.name) rolesDo("area_rename", { id: a.id, name: n }, "Renamed."); });
  $("[data-propose]", c)?.addEventListener("click", () => (!has || confirm("Propose roles again? Your renames and moves are replaced.")) && proposeRoles());
  $("[data-confirm]", c)?.addEventListener("click", () => rolesDo("confirm", {}, "Roles confirmed. Rename or move files any time."));
  $("[data-rename]", c)?.addEventListener("click", () => renameRole(S.role));
  $("[data-files]", c)?.addEventListener("click", () => roleFiles(S.role));
  $("[data-fence]", c)?.addEventListener("click", () => fenceRole(S.role));
}

function reveal(id) { // a module hidden in a grouped folder: open the folders down to it
  if (S.graph.modules.some((m) => m.id === id)) return;
  S.focus = S.full.modules.some((m) => m.id.startsWith(id + "/")) ? id : parent(id);
  regroup();
}
const inSet = (set, id) => set.has(id) || !!(mod(id)?.members && mod(id).members.some((x) => set.has(x))) || !!(id.includes(":") && mod(id)?.files.some((f) => set.has(f)));

/* ---------------- layout: layered, foundations at the bottom ---------------- */
function layout() {
  const g = S.graph, all = g.modules.map((m) => m.id), ids = all;
  // Rank on the directed links left once loop edges are set aside (loopEdges): an acyclic graph. A layered map puts high
  // ranks (importers) on top; the free levels put rank 0 (used by others) on top, as a tree from back end to front end.
  const directed = g.edges.filter((e) => !e.kind || e.kind === "runtime"); // copies and co-change have no direction
  S.back = loopEdges(directed);
  const deps = {};
  directed.forEach((e) => { if (!S.back.has(e)) (deps[e.source] ||= new Set()).add(e.target); });
  const crank = {};
  const r = (c) => (c in crank ? crank[c] : (crank[c] = deps[c] ? 1 + Math.max(...[...deps[c]].map(r)) : 0));
  const rank = Object.fromEntries(ids.map((i) => [i, r(i)]));
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
  const WRAP = 10; // ponytail: a wide rank wraps onto extra rows, so a 40-function rank stays on screen
  rows = rows.flatMap((row) => Array.from({ length: Math.ceil(row.length / WRAP) }, (_, i) => row.slice(i * WRAP, (i + 1) * WRAP)));
  // Areas, roles and parts import each other in rings, so any strict layering is one tall column: they get a stress
  // layout instead (stressLayout). A dense module map layers into a tower too: it becomes a grid, edges on focus only.
  S.free = ["areas", "roles", "parts"].includes(S.level);
  S.dense = !S.free && g.edges.length > DENSE;
  if (S.free) return placeFree(g, all, ids, rank);
  if (S.dense) { const order = rows.flat(), cols = Math.ceil(Math.sqrt(order.length * 1.8)); rows = Array.from({ length: Math.ceil(order.length / cols) }, (_, i) => order.slice(i * cols, (i + 1) * cols)); }
  S.rows = rows.map((row) => row.slice());
  S.pos = {};
  rows.forEach((row, ri) => row.forEach((id, k) => {
    S.pos[id] = { x: (k - (row.length - 1) / 2) * (NODE_W + GAP_X) - NODE_W / 2, y: ri * (NODE_H + GAP_Y) };
  }));
}

// A tree's logic on top of the stress layout: what others use (back ends, cores) sits on top, what uses them (front
// ends, scripts) below, in at most BANDS rows, so the picture reads top to bottom yet never becomes one tall column.
// Inside a row, boxes keep the left-to-right order the stress layout gave them, so linked boxes stay near.
const BANDS = 4;
function placeFree(g, all, ids0, rank) {
  // Boxes with no link at all are not part of the structure: they go to a row of chips under it (drawChip).
  const linkedIds = new Set(g.edges.flatMap((e) => [e.source, e.target]));
  const lone = ids0.filter((i) => !linkedIds.has(i)), ids = ids0.filter((i) => linkedIds.has(i));
  // Inside a function, the other functions sit outside its frame: those its roles use above, those using them below.
  const ghost = new Set(ids.filter((i) => mod(i)?.ghost)), inner = ids.filter((i) => !ghost.has(i));
  const P = stressLayout(ids, g.edges, rank), maxR = Math.max(0, ...inner.map((i) => rank[i] || 0));
  const B = Math.min(BANDS, maxR + 1), rows = Array.from({ length: B }, () => []);
  const directed = new Set(g.edges.filter((e) => !e.kind || e.kind === "runtime").flatMap((e) => [e.source, e.target]));
  // a box with no directed link is a program on its own: it sits with the users at the bottom, not with the cores
  inner.forEach((i) => rows[!directed.has(i) ? B - 1 : maxR ? Math.round(((rank[i] || 0) / maxR) * (B - 1)) : 0].push(i));
  if (ghost.size) {
    const usedHere = new Set(g.edges.filter((e) => ghost.has(e.target) && !ghost.has(e.source)).map((e) => e.target));
    rows.unshift([...ghost].filter((i) => usedHere.has(i)));
    rows.push([...ghost].filter((i) => !usedHere.has(i)));
  }
  rows.forEach((row, b) => {
    row.sort((a, c) => P[a].x - P[c].x || a.localeCompare(c));
    const mean = row.reduce((t, i) => t + P[i].x, 0) / (row.length || 1);
    for (let k = 1; k < row.length; k++) P[row[k]].x = Math.max(P[row[k]].x, P[row[k - 1]].x + NODE_W + GAP_X);
    const shift = mean - row.reduce((t, i) => t + P[i].x, 0) / (row.length || 1);
    row.forEach((i) => { P[i].x = Math.round(P[i].x + shift); P[i].y = b * (NODE_H + GAP_Y * 1.6) + (ghost.size && b > 0 ? 40 : 0) + (ghost.size && b === rows.length - 1 && b > 0 ? 40 : 0); });
  });
  const ys = ids.map((i) => P[i].y), xs = ids.map((i) => P[i].x), x0 = xs.length ? Math.min(...xs) : 0, y1 = ys.length ? Math.max(...ys) + NODE_H : 0;
  lone.forEach((i, k) => (P[i] = { x: x0 + k * (CHIP_W + 12), y: y1 + GAP_Y + 34, chip: true }));
  S.pos = P; S.rows = rows.filter((r) => r.length); S.lone = lone;
}
// Stress majorization (Gansner, Koren and North 2004), the per-node update with weights d^-2: boxes that import each
// other sit close, the drawing comes nearest to a hand-made one on small graphs. Distance = import hops. Start from the
// import ranks (deterministic, upstream on top); a light pull keeps each import pointing down unless it closes a loop.
// Then boxes are pushed apart until none overlap. ponytail: O(n^2) per sweep, fine for the 7 to 15 boxes of these levels.
function stressLayout(ids, edges, rank) {
  const n = ids.length, ix = Object.fromEntries(ids.map((id, i) => [id, i])), U = 300; // px per hop; a box is 220 wide
  const adj = ids.map(() => new Set());
  edges.forEach((e) => { if (e.source in ix && e.target in ix) { adj[ix[e.source]].add(ix[e.target]); adj[ix[e.target]].add(ix[e.source]); } });
  const d = ids.map((_, s) => {
    const dist = Array(n).fill(Infinity), q = [s];
    dist[s] = 0;
    while (q.length) { const v = q.shift(); adj[v].forEach((w) => { if (dist[w] === Infinity) { dist[w] = dist[v] + 1; q.push(w); } }); }
    return dist;
  });
  const far = 1.4; // boxes with no import path between them sit just beyond a neighbour, not across the screen
  d.forEach((row) => row.forEach((v, j) => (row[j] = (Number.isFinite(v) ? v : far) * U)));
  const P = ids.map((id, i) => ({ x: Math.cos(i * 2.39996) * U * 0.7 * Math.sqrt(i + 1), y: (rank[id] || 0) * U * 0.8 + Math.sin(i * 2.39996) * 20 }));
  for (let it = 0; it < 300; it++) {
    let moved = 0;
    for (let i = 0; i < n; i++) {
      let sx = 0, sy = 0, sw = 0;
      for (let j = 0; j < n; j++) {
        if (i === j) continue;
        const w = 1 / (d[i][j] * d[i][j]), dx = P[i].x - P[j].x, dy = P[i].y - P[j].y, len = Math.hypot(dx, dy) || 1e-6;
        sx += w * (P[j].x + (d[i][j] * dx) / len); sy += w * (P[j].y + (d[i][j] * dy) / len); sw += w;
      }
      if (!sw) continue;
      moved += Math.abs(sx / sw - P[i].x) + Math.abs(sy / sw - P[i].y);
      P[i].x = sx / sw; P[i].y = sy / sw;
    }
    edges.forEach((e) => { // light flow: a directed link that does not close a loop has its caller half a hop below
      if (e.kind === "copy" || e.kind === "cochange" || S.back.has(e) || !(e.source in ix) || !(e.target in ix)) return;
      const a = P[ix[e.source]], b = P[ix[e.target]], gap = U * 0.5 - (a.y - b.y);
      if (gap > 0) { a.y += gap * 0.2; b.y -= gap * 0.2; }
    });
    if (moved < 0.5) break;
  }
  const W = NODE_W + 48, H = NODE_H + 56;
  for (let pass = 0; pass < 200; pass++) { // remove box overlaps along the axis that overlaps less
    let any = false;
    for (let i = 0; i < n; i++) for (let j = i + 1; j < n; j++) {
      const dx = P[j].x - P[i].x, dy = P[j].y - P[i].y, ox = W - Math.abs(dx), oy = H - Math.abs(dy);
      if (ox <= 0 || oy <= 0) continue;
      any = true;
      if (ox / W < oy / H) { const m = ((dx >= 0 ? 1 : -1) * ox) / 2; P[i].x -= m; P[j].x += m; }
      else { const m = ((dy >= 0 ? 1 : -1) * oy) / 2; P[i].y -= m; P[j].y += m; }
    }
    if (!any) break;
  }
  return Object.fromEntries(ids.map((id, i) => [id, { x: Math.round(P[i].x - NODE_W / 2), y: Math.round(P[i].y - NODE_H / 2) }]));
}
function straightPath(e) { // box edge to box edge along the centre line; a two-way pair is drawn as two parallel lines
  const a = S.pos[e.source], b = S.pos[e.target];
  const ax = a.x + NODE_W / 2, ay = a.y + NODE_H / 2, bx = b.x + NODE_W / 2, by = b.y + NODE_H / 2;
  const dx = bx - ax, dy = by - ay, len = Math.hypot(dx, dy) || 1, off = e._two ? 5 : 0, ox = (-dy / len) * off, oy = (dx / len) * off;
  const cut = (hw, hh) => Math.min(hw / Math.abs(dx || 1e-9), hh / Math.abs(dy || 1e-9)); // centre to the box border
  const s = cut(NODE_W / 2 + 2, NODE_H / 2 + 2), t = cut(NODE_W / 2 + 5, NODE_H / 2 + 5);
  return `M${ax + dx * s + ox},${ay + dy * s + oy} L${bx - dx * t + ox},${by - dy * t + oy}`;
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
  if (S.free) return straightPath(e);
  const a = S.pos[e.source], b = S.pos[e.target];
  if (e._lane) {
    const sx = a.x + NODE_W / 2 + spread.out, sy = a.y + NODE_H, tx = b.x + NODE_W / 2 + spread.in, ty = b.y - 3, lx = e._lane;
    return `M${sx},${sy} C${sx},${sy + 30} ${lx},${sy + 8} ${lx},${sy + 46} L${lx},${ty - 46} C${lx},${ty - 8} ${tx},${ty - 30} ${tx},${ty}`;
  }
  if (b.y > a.y) {
    const sx = a.x + NODE_W / 2 + spread.out, sy = a.y + NODE_H, tx = b.x + NODE_W / 2 + spread.in, ty = b.y - 3;
    const dy = Math.max(32, (ty - sy) * 0.5);
    return `M${sx},${sy} C${sx},${sy + dy} ${tx},${ty - dy} ${tx},${ty}`;
  }
  const sx = a.x + NODE_W, sy = a.y + NODE_H / 2, tx = b.x + NODE_W + 3, ty = b.y + NODE_H / 2; // a cycle: around the right
  const bulge = 60 + Math.abs(ty - sy) * 0.2;
  return `M${sx},${sy} C${sx + bulge},${sy} ${tx + bulge},${ty} ${tx},${ty}`;
}

const CHIP_W = 170, CHIP_H = 40;
function drawFrame(eg) { // the function around its roles, so inside and outside read at a glance
  const ids = S.graph.modules.filter((m) => !m.ghost && !S.pos[m.id]?.chip).map((m) => m.id);
  if (!S.graph.frame || !ids.length) return;
  const xs = ids.map((i) => S.pos[i].x), ys = ids.map((i) => S.pos[i].y), pad = 26;
  const x = Math.min(...xs) - pad, y = Math.min(...ys) - pad - 18, w = Math.max(...xs) + NODE_W + pad - x, h = Math.max(...ys) + NODE_H + pad - y;
  el("rect", { class: "frame", x, y, width: w, height: h, rx: 14 }, eg);
  el("text", { class: "frame-name", x: x + 14, y: y + 20 }, eg).textContent = S.graph.frame;
}
function drawChip(m, ng) { // a box with no link: a small chip under the map, not a vertex of it
  const { x, y } = S.pos[m.id];
  const n = el("g", { class: "node chip", transform: `translate(${x},${y})`, tabindex: 0, role: "button", "data-id": m.id }, ng);
  el("rect", { class: "ring", x: -3, y: -3, width: CHIP_W + 6, height: CHIP_H + 6, rx: 8 }, n);
  el("rect", { class: "card", width: CHIP_W, height: CHIP_H, rx: 6 }, n);
  el("rect", { class: "fill", width: CHIP_W, height: CHIP_H, rx: 6 }, n);
  el("text", { class: "name", x: 10, y: 25 }, n).textContent = clip(boxName(m), 18);
  el("text", { class: "tag", x: CHIP_W - 8, y: 12, "text-anchor": "end", "data-tag": "" }, n);
  el("title", {}, n).textContent = `${boxName(m)}: no import, call, copy or shared history with the rest`;
  n.addEventListener("pointerdown", (ev) => ev.stopPropagation());
  n.addEventListener("click", (ev) => onNodeClick(m.id, ev));
}
function drawGraph() {
  const g = S.graph, eg = $("#edges"), ng = $("#nodes"), mx = maxLines();
  eg.innerHTML = ""; ng.innerHTML = "";
  if (S.free) drawFrame(eg);
  if (S.lone?.length) {
    const x0 = Math.min(...S.lone.map((i) => S.pos[i].x)), y0 = S.pos[S.lone[0]].y;
    el("text", { class: "lone-cap", x: x0, y: y0 - 10 }, eg).textContent = "Standalone: no import, call, copy or shared history with the rest";
  }
  const outs = {}, ins = {};
  g.edges.forEach((e) => { (outs[e.source] ||= []).push(e); (ins[e.target] ||= []).push(e); });
  const spread = new Map();
  const assign = (list, key, other) => {
    list.sort((x, y) => S.pos[x[other]].x - S.pos[y[other]].x);
    list.forEach((e, k) => { const s = spread.get(e) || {}; s[key] = (k - (list.length - 1) / 2) * Math.min(26, (NODE_W * 0.6) / Math.max(1, list.length)); spread.set(e, s); });
  };
  Object.values(outs).forEach((l) => assign(l, "out", "target"));
  Object.values(ins).forEach((l) => assign(l, "in", "source"));
  if (S.free) { S.extent = { x0: Infinity, x1: -Infinity }; const keys = new Set(g.edges.map((e) => e.source + "\n" + e.target)); g.edges.forEach((e) => (e._two = keys.has(e.target + "\n" + e.source))); }
  else routeLanes(g);
  const counts = g.edges.map((e) => e.receipts.length).sort((x, y) => x - y), weak = counts[Math.floor(counts.length / 2)] || 0, wmax = counts[counts.length - 1] || 1;
  g.edges.forEach((e) => {
    const d = (e._d = edgePath(e, spread.get(e)));
    e._back = !S.free && S.back.has(e); // closes a loop: drawn red, the cheapest import to cut (layered maps only)
    e._base = (mod(e.source).kind === "tests" ? "edge from-tests" : "edge") + (e._back ? " back" : "") + (e.kind ? " " + e.kind : "") + (S.free && !e.kind && e.receipts.length < weak ? " weak" : "");
    const sw = S.free ? 1 + 3 * Math.sqrt(e.receipts.length / wmax) : 1.3 + Math.min(2, Math.log2(e.receipts.length)); // free: grows with every import
    e._sw = sw;
    e._el = el("path", { d, class: e._base, "marker-end": "url(#ah)", style: `stroke-width:${sw.toFixed(2)}px` }, eg); // inline: the .edge CSS rule would override an attribute
    const hit = (e._hit = el("path", { d, class: "edge-hit" }, eg));
    hit.addEventListener("pointerdown", (ev) => ev.stopPropagation());
    hit.addEventListener("pointerenter", (ev) => showEdgeTip(ev, e));
    hit.addEventListener("pointermove", moveTip);
    hit.addEventListener("pointerleave", () => { hideTip(); hotEdge(e, false); });
    hit.addEventListener("click", () => pick(e.target));
  });
  g.modules.forEach((m) => {
    if (S.pos[m.id]?.chip) return drawChip(m, ng);
    const { x, y } = S.pos[m.id];
    const n = el("g", { class: `node${m.kind === "tests" ? " tests" : ""}`, transform: `translate(${x},${y})`, tabindex: 0, role: "button", "data-id": m.id }, ng);
    el("rect", { class: "ring", x: -3, y: -3, width: NODE_W + 6, height: NODE_H + 6, rx: 10 }, n);
    if (m.group) { n.classList.add("group"); el("rect", { class: "stack", x: 5, y: 5, width: NODE_W, height: NODE_H, rx: 7 }, n); }
    if (m.ghost) n.classList.add("ghost");
    el("rect", { class: "card", width: NODE_W, height: NODE_H, rx: 7 }, n);
    el("rect", { class: "fill", width: NODE_W, height: NODE_H, rx: 7 }, n);
    const name = el("text", { class: "name", x: 12, y: 25 }, n);
    name.textContent = clip(boxName(m), 22);
    const meta = el("text", { class: "meta", x: 12, y: 45 }, n);
    meta.textContent = clip(m.meta ? m.meta : m.group ? plural(m.members.length, "module") : `${parent(m.id) ? parent(m.id) + "/ · " : ""}${plural(m.files.length, "file")}`, 30);
    el("rect", { class: "bar-bg", x: 12, y: 57, width: NODE_W - 24, height: 5, rx: 2.5 }, n);
    el("rect", { class: "bar", x: 12, y: 57, width: Math.max(3, (NODE_W - 24) * (m.lines / mx)), height: 5, rx: 2.5 }, n);
    const lines = el("text", { class: "meta", x: NODE_W - 12, y: 45, "text-anchor": "end" }, n);
    lines.textContent = `${m.lines} ln`;
    el("text", { class: "tag", x: NODE_W - 12, y: 25, "text-anchor": "end", "data-tag": "" }, n);
    if (m.files.some((f) => S.graph.files[f].error)) n.classList.add("error");
    n.addEventListener("pointerdown", (ev) => ev.stopPropagation());
    n.addEventListener("click", (ev) => onNodeClick(m.id, ev));
    if (m.kind === "fn" || m.kind === "edge") n.classList.add(m.kind);
    if (m.doc) el("title", {}, n).textContent = m.doc;
    n.addEventListener("keydown", (ev) => { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); onNodeClick(m.id, ev); } });
    n.addEventListener("pointerenter", () => hoverNode(m.id, true));
    n.addEventListener("pointerleave", () => hoverNode(m.id, false));
    n.addEventListener("focus", () => hoverNode(m.id, true));
    n.addEventListener("blur", () => hoverNode(m.id, false));
  });
  paintSelection();
}
const DENSE = 20; // ponytail: 20 edges is a guess at where a node-link picture stops reading
function routeLanes(g) {
  // An edge that skips rows goes around the cards in between: right if its target lies to the right, else left.
  const rowOf = (id) => Math.round(S.pos[id].y / (NODE_H + GAP_Y));
  const byRow = {};
  Object.entries(S.pos).forEach(([id, p]) => (byRow[rowOf(id)] ||= []).push(p));
  const lanes = { left: 0, right: 0 };
  S.extent = { x0: Infinity, x1: -Infinity };
  g.edges.forEach((e) => {
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
    e._lane = side === "right" ? maxX + 24 + n * 12 : minX - 24 - n * 12;
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
function fenced(id) { return S.selected !== null && !S.readOnly && inSet(S.scope, id); }
function stateWords(id, rel, focus) {
  const w = [];
  if (id === S.selected) w.push("selected");
  if (fenced(id)) w.push("editable");
  if (focus && rel.dep.has(id)) w.push(`${shown(focus)} uses it`);
  if (focus && rel.use.has(id)) w.push(`uses ${shown(focus)}`);
  const st = S.marks.stats[id];
  if (S.marks.changed.has(id)) w.push(st ? `changed, ${st.plus} added and ${st.minus} removed lines` : "changed");
  else if (S.marks.ripple.has(id)) w.push("uses changed code");
  return w;
}
function diffTag(id) { // a box's added and removed lines; an area, role or part adds up its modules
  const st = S.marks.stats[id] || (mod(id)?.members || []).reduce((a, m) => (S.marks.stats[m] ? { plus: (a?.plus || 0) + S.marks.stats[m].plus, minus: (a?.minus || 0) + S.marks.stats[m].minus } : a), null);
  return st ? `+${st.plus} −${st.minus}` : "";
}
function roundLine() { // golden rule 7: which boxes at this level the last run changed, and which use changed code
  if (!S.marks.changed.size) return "";
  const at = (set) => S.graph.modules.filter((m) => inSet(set, m.id)).map((m) => shown(m.id));
  const ch = at(S.marks.changed), rp = at(S.marks.ripple).filter((x) => !ch.includes(x));
  return `<em class="round">Last run changed <b>${esc(ch.join(", ") || "nothing on this level")}</b>${rp.length ? ` · uses changed code: ${esc(rp.join(", "))}` : ""}</em>`;
}

function paintSelection(hover) {
  const focus = hover || S.selected || S.picked;
  const rel = focus ? related(focus) : { dep: new Set(), use: new Set() };
  document.querySelectorAll(".node").forEach((n) => {
    const id = n.dataset.id, m = mod(id);
    n.classList.toggle("selected", id === S.selected || id === S.picked);
    n.classList.toggle("fenced", fenced(id));
    n.classList.toggle("dep", !!focus && rel.dep.has(id));
    n.classList.toggle("use", !!focus && rel.use.has(id));
    const ch = inSet(S.marks.changed, id), rp = inSet(S.marks.ripple, id);
    n.classList.toggle("faded", !!focus && id !== focus && !rel.dep.has(id) && !rel.use.has(id) && !fenced(id) && !ch);
    n.classList.toggle("changed", ch);
    n.classList.toggle("ripple", rp && !ch);
    const tag = $("[data-tag]", n);
    const d = diffTag(id);
    tag.setAttribute("class", `tag ${d ? "plus" : fenced(id) ? "fence" : ""}`);
    tag.textContent = d || (fenced(id) ? "editable" : "");
    n.setAttribute("aria-label", `Module ${shown(id)}, ${plural(m.files.length, "file")}, ${m.lines} lines${stateWords(id, rel, focus).length ? ", " + stateWords(id, rel, focus).join(", ") : ""}`);
  });
  document.querySelectorAll("#edges .flow").forEach((f) => f.remove());
  S.graph.edges.forEach((e) => {
    if (!e._el) return; // a graph not drawn yet (a project switch repaints before its first draw)
    const k = !focus ? "" : e.source === focus ? "dep" : e.target === focus ? "use" : "faded";
    // a dense map draws only the focused box's edges; a loop edge among them stays red (the cheapest import to cut)
    const quiet = S.dense && (k === "" || k === "faded");
    e._el.setAttribute("class", `${e._base} ${k}${quiet ? " quiet" : ""}`); e._hit.classList.toggle("quiet", quiet);
    e._el.setAttribute("marker-end", k === "dep" ? "url(#ah-dep)" : k === "use" ? "url(#ah-use)" : "url(#ah)");
    // A short pulse travels each highlighted edge in import direction. pathLength=100 makes the dash the same share of any edge.
    if (k === "dep" || k === "use") el("path", { d: e._d, class: `flow ${k}`, pathLength: 100 }, $("#edges"));
  });
  renderLegend(!!focus);
}
let hoverT = 0;
function hoverNode(id, on) {
  clearTimeout(hoverT);
  if (on) paintSelection(id);
  else hoverT = setTimeout(() => paintSelection(), 120);
}
function renderLegend(focus) {
  const items = [];
  if (focus) items.push(["var(--select)", "", "selected"], ["var(--dep)", "", "uses"], ["var(--use)", "", "used by"]);
  if (S.free && S.graph.edges.some((e) => e.kind)) items.push(["var(--text-3)", "line", "imports"], ["var(--text-3)", "dash", "calls over HTTP or starts"], ["var(--text-3)", "dashdot", "copied code"], ["var(--text-3)", "dot", "changed together (git)"]);
  if (S.selected && !S.readOnly) items.push(["var(--fence)", "hatch", "editable (in the fence)"]);
  if (S.marks.changed.size) items.push(["var(--ok)", "", "changed by the last run"]);
  if (S.marks.ripple.size) items.push(["var(--warn)", "", "uses changed code"]);
  $("#legend").innerHTML = items.map(([c, cls, t]) => `<span><i class="${cls}" style="border-color:${c}"></i>${esc(t)}</span>`).join("");
}

/* ---------------- camera: 1:1 pan, zoom at pointer, critically damped spring for fit/focus ---------------- */
function applyCam() { $("#world").setAttribute("transform", `translate(${S.cam.x},${S.cam.y}) scale(${S.cam.k})`); }
function springTo(target) {
  S.camTarget = target;
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) { Object.assign(S.cam, target); S.camV = { x: 0, y: 0, k: 0 }; applyCam(); return; }
  if (S.raf) return;
  let last = performance.now();
  const response = 0.62, stiff = (2 * Math.PI / response) ** 2, damp = (4 * Math.PI) / response;
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
  return { x0: Math.min(ex.x0, ...xs.map((p) => p.x)) - 30, y0: Math.min(...xs.map((p) => p.y)) - 24,
           x1: Math.max(ex.x1, ...xs.map((p) => p.x + NODE_W)) + 30, y1: Math.max(...xs.map((p) => p.y + NODE_H)) + 24 };
}
function viewport() { // the side bar covers the right of the canvas, so the graph fits in what is left
  const c = $("#canvas").getBoundingClientRect(), side = $("#pick").hidden ? 0 : $("#pick").offsetWidth;
  return { w: (c.width || innerWidth) - side, h: c.height || innerHeight, bottom: 52 };
}
function fitView(animate = true) {
  const b = bounds(), v = viewport(), top = $("#crumbs").hidden ? 16 : $("#crumbs").offsetHeight + 24; // below the path bar
  const k = Math.min(1.2, Math.max(0.35, Math.min((v.w - 40) / (b.x1 - b.x0), (v.h - v.bottom - top - 4) / (b.y1 - b.y0))));
  const t = { k, x: v.w / 2 - ((b.x0 + b.x1) / 2) * k, y: top + (v.h - v.bottom - top) / 2 - ((b.y0 + b.y1) / 2) * k };
  if (animate) springTo(t); else { stopSpring(); Object.assign(S.cam, t); applyCam(); }
}
function revealNode(id) {
  if (!S.pos[id]) return; // not drawn at this level (a function view, say)
  const p = S.pos[id], v = viewport(), k = S.cam.k;
  const sx = S.cam.x + p.x * k, sy = S.cam.y + p.y * k, w = NODE_W * k, h = NODE_H * k;
  let dx = 0, dy = 0;
  if (sx < 20) dx = 20 - sx; else if (sx + w > v.w - 20) dx = v.w - 20 - (sx + w);
  if (sy < 16) dy = 16 - sy; else if (sy + h > v.h - v.bottom) dy = v.h - v.bottom - (sy + h);
  if (dx || dy) springTo({ x: S.cam.x + dx, y: S.cam.y + dy, k });
}
function zoomAt(f, cx, cy) {
  stopSpring(); S.userCam = true;
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
    if (Math.abs(dx) + Math.abs(dy) > 3) { drag.moved = true; S.userCam = true; }
    S.cam.x = drag.cx + dx; S.cam.y = drag.cy + dy; applyCam();
  });
  const end = (e) => {
    if (!drag) return;
    if (!drag.moved && e.type === "pointerup" && S.selected) closePanel();
    drag = null; c.classList.remove("panning");
  };
  c.addEventListener("pointerup", end);
  c.addEventListener("pointercancel", end);
  c.addEventListener("dblclick", () => { S.userCam = false; fitView(); });
  c.addEventListener("wheel", (e) => {
    e.preventDefault();
    const r = c.getBoundingClientRect(), cx = e.clientX - r.left, cy = e.clientY - r.top;
    const trackpad = e.deltaMode === 0 && (Math.abs(e.deltaX) > 0 || Math.abs(e.deltaY) < 40);
    if (e.ctrlKey || e.metaKey) zoomAt(Math.exp(-e.deltaY * 0.01), cx, cy);
    else if (trackpad) { stopSpring(); S.userCam = true; S.cam.x -= e.deltaX; S.cam.y -= e.deltaY; applyCam(); }
    else zoomAt(Math.exp(-e.deltaY * (e.deltaMode ? 0.06 : 0.0022)), cx, cy);
  }, { passive: false });
  $("#zin").onclick = () => { const v = viewport(); zoomAt(1.2, v.w / 2, v.h / 2); };
  $("#zout").onclick = () => { const v = viewport(); zoomAt(1 / 1.2, v.w / 2, v.h / 2); };
  $("#zfit").onclick = () => { S.userCam = false; fitView(); };
  addEventListener("resize", () => { if (!S.userCam) fitView(false); });
}

/* ---------------- edge tooltip (keyboard users get the same receipts in the panel) ---------------- */
// What one module takes from another, by name: the functions and classes behind an import arrow.
const takes = (e) => [...new Set(e.receipts.map((r) => r.name).filter(Boolean))];
// Golden rule 2: hovering a line says in plain words what the link is and what it means for a change, with its
// An optional second look (off by default, golden rule 1): a read-only run that reads only what this run changed and
// reports real bugs and broken contracts, nothing about style.
function renderReview(root, job, c) {
  const files = c && c.files ? c.files.map((f) => f.path) : [];
  if (!files.length || job.readOnly || job.phase === "plan") return;
  const b = document.createElement("button");
  b.className = "btn quiet review"; b.type = "button"; b.textContent = "Review this run";
  b.title = "A read-only run reads the changed files and reports real bugs or broken contracts (costs a run)";
  root.appendChild(b);
  b.onclick = () => { b.disabled = true; startRun(`Review the last change for bugs, nothing else. Changed files: ${files.join(", ")}. Task it did: ${job.prompt}. `
    + `Read only those files and what they call. Report at most 5 real problems (wrong behaviour, broken callers, missing edge cases), each with file:line and why. No style comments. If none, say so in one line.`, job.scope, true, null); };
}
// evidence counted; the line and its two boxes light up. No lists of names to decode.
function readEdge(e) {
  const a = `<b>${esc(shown(e.source))}</b>`, b = `<b>${esc(shown(e.target))}</b>`, r = e.receipts;
  const few = (xs) => xs.slice(0, 3).map((x) => `<code>${esc(x)}</code>`).join(", ") + (xs.length > 3 ? ` and ${xs.length - 3} more` : "");
  const uniq = (xs) => [...new Set(xs)];
  if (e.kind === "runtime") {
    const http = uniq(r.filter((x) => x.name.startsWith("HTTP ")).map((x) => x.name.slice(5)));
    const runs = uniq(r.filter((x) => x.name.startsWith("runs ")).map((x) => x.name.slice(5)));
    return [http.length && `${a} calls ${plural(http.length, "HTTP route")} of ${b}: ${few(http)}.`,
      runs.length && `${a} starts ${few(runs)} from ${b}.`,
      `If ${b} changes them, ${a} breaks with no import error to warn you. Fence both, or keep them as they are.`].filter(Boolean);
  }
  if (e.kind === "copy") {
    const files = uniq(r.map((x) => x.file.split("/").pop()));
    return [`${a} keeps copies of ${plural(files.length, "file")} from ${b}: ${few(files)}.`, `A fix in one usually belongs in the other too.`];
  }
  if (e.kind === "cochange") {
    const n = e.n || 0;
    return [`${a} and ${b} were changed in the same commit ${n === 1 ? "once" : `${n} times`}.`,
      n < 3 ? "Weak evidence: no import or call links them, so they mostly change apart." : "They tend to change together: consider fencing both."];
  }
  const names = takes(e);
  return [`${a} uses ${names.length ? `${plural(names.length, "name")} from ${b}: ${few(names)}` : `${b} as a whole`} (${plural(r.length, "import line")}).`,
    `Editing ${b} can break ${a}. Fencing ${a} keeps ${b} read-only, so the agent sees only its interface.`];
}
function showEdgeTip(ev, e) {
  const t = $("#tip");
  t.innerHTML = readEdge(e).map((line, k) => `<p${k ? ' class="so"' : ""}>${line}</p>`).join("");
  t.classList.add("show"); moveTip(ev);
  hotEdge(e, true);
}
function linkPhrase(e) { // the side bar's few words for a link: what kind, how much
  const r = e.receipts, uniq = (xs) => new Set(xs).size;
  if (e.kind === "runtime") {
    const http = uniq(r.filter((x) => x.name.startsWith("HTTP ")).map((x) => x.name)), runs = uniq(r.filter((x) => x.name.startsWith("runs ")).map((x) => x.name));
    return [http && `calls ${plural(http, "HTTP route")}`, runs && `starts ${plural(runs, "file")}`].filter(Boolean).join(" · ");
  }
  if (e.kind === "copy") return `copies of ${plural(uniq(r.map((x) => x.file)), "file")}`;
  if (e.kind === "cochange") return e.n === 1 ? "changed together once" : `changed together ${e.n} times`;
  const n = takes(e).length;
  return `${n ? `uses ${plural(n, "name")}` : "imports it"} · ${plural(r.length, "line")}`;
}
function fileGroups(m) { // files under the level below: a function by role, a role by part, a part by folder
  const by = new Map(), add = (k, f) => (by.get(k) || by.set(k, []).get(k)).push(f);
  const fr = fileRoles(), parts = (S.roles?.roles || []).find((r) => r.id === m.role)?.parts || {};
  m.files.forEach((f) => add(m.area ? rname(fr[f]) : m.role ? parts[f] || "other" : (f.includes("/") ? f.slice(0, f.lastIndexOf("/") + 1) : "./"), f));
  return [...by].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0])).map(([k, fs]) => [k, fs.sort()]);
}
function hotEdge(e, on) { // the hovered line and its two boxes light up a little
  e._el.classList.toggle("hot", on);
  e._el.style.strokeWidth = on ? `${(e._sw || 1.4) + 1.6}px` : `${e._sw || 1.4}px`;
  [e.source, e.target].forEach((id) => document.querySelector(`.node[data-id="${CSS.escape(id)}"]`)?.classList.toggle("hot", on));
}
function moveTip(ev) { const t = $("#tip"); t.style.left = Math.min(ev.clientX + 14, innerWidth - t.offsetWidth - 10) + "px"; t.style.top = Math.min(ev.clientY + 16, innerHeight - t.offsetHeight - 10) + "px"; }
function hideTip() { $("#tip").classList.remove("show"); }

/* ---------------- selection, fence & panel ---------------- */
function onNodeClick(id, ev) {
  if (/^(role|dir|part|area):/.test(id)) { pick(id); return; }
  // a click only picks (the card opens it on purpose); shift-click with a module open grows the fence
  if (!((ev.shiftKey || ev.metaKey || ev.ctrlKey) && S.selected) || mod(id)?.group) { pick(id); return; }
  if (S.scope.has(id) && S.scope.size > 1) S.scope.delete(id); else S.scope.add(id);
  if (!S.scope.has(S.selected)) S.selected = [...S.scope][0];
  afterFenceChange();
}
function select(id, keepLabel) {
  if (id.endsWith("/")) { S.focus = id.slice(0, -1); regroup(); fitView(); return; } // a grouped folder: open it
  if (!keepLabel) S.fenceLabel = null;
  if (S.level === "areas" || S.level === "roles" || (S.level === "parts" && !S.graph.modules.some((m) => m.id === id))) { // show the module among its role's parts
    const fr = fileRoles(), f = (S.full.modules.find((m) => m.id === id) || { files: [] }).files.find((x) => fr[x]);
    if (f) { S.level = "parts"; S.role = fr[f]; regroup(); } else { S.level = "modules"; regroup(); }
  }
  if (S.level === "modules") reveal(id);
  const opening = !document.body.classList.contains("panel-open");
  S.selected = id;
  // A plain click starts a new fence, unless a multi-module fence is set: then the fence is kept and the module is only shown.
  if (!(S.scope.size > 1 && !opening)) S.scope = new Set([id]);
  document.body.classList.add("panel-open");
  $("#panel").inert = false;
  renderHeader(); renderOverview(); renderFence(); loadTalk(); paintSelection();
  setTab(S.tab, false);
  requestAnimationFrame(() => {
    if (S.view !== "graph") setView("graph");
    if (opening && !S.userCam) fitView(); else revealNode(id);
  });
}
function closePanel() {
  const wasOpen = document.body.classList.contains("panel-open");
  S.selected = null; S.scope.clear();
  if (wasOpen) api(`/api/fence/clear?${q()}`, {}).catch(() => {}); // agents started by hand are no longer fenced (409 while a run goes: it stays)
  document.body.classList.remove("panel-open");
  $("#panel").inert = true;
  if (wasOpen) requestAnimationFrame(() => S.view === "graph" && !S.userCam && fitView());
  paintSelection();
}
function afterFenceChange() { S.forceRoute = null; renderFence(); renderHeader(); paintSelection(); loadTalk(); syncSend(); }
function setTab(t, focus) {
  S.tab = t;
  document.querySelectorAll("#seg [role=tab]").forEach((b) => {
    const on = b.dataset.tab === t;
    b.setAttribute("aria-selected", String(on));
    b.tabIndex = on ? 0 : -1;
    if (on && focus) b.focus();
  });
  $("#v-over").hidden = t !== "over";
  $("#v-talk").hidden = t !== "talk";
  requestAnimationFrame(() => slideInk($("#seg"), "[aria-selected=true]"));
  if (t === "talk") scrollTalk();
}

function renderHeader() {
  if (S.fenceLabel) { // a role or part: the panel is about the whole fence
    const fs = [...S.scope].filter((f) => S.full.files[f]);
    $("#mname").textContent = S.fenceLabel; $("#mdoc").textContent = S.fenceDoc || "";
    $("#mfacts").textContent = `${plural(fs.length, "file")} · ${fs.reduce((a, f) => a + S.full.files[f].lines, 0).toLocaleString()} lines`;
    return;
  }
  const m = mod(S.selected);
  if (!m) return;
  $("#mname").textContent = m.id === "." ? "(project root)" : m.id.endsWith(".py") ? m.id : m.id + "/";
  $("#mdoc").textContent = m.doc || "";
  $("#mfacts").textContent = `${plural(m.files.length, "file")} · ${m.lines} lines`;
}

function relRows(ids, other, dir) {
  if (!ids.length) return `<p class="none">${dir === "dep" ? "Uses nothing else in this project." : "No other module uses it."}</p>`;
  return `<div class="rows">${ids.map((id) => {
    const e = S.graph.edges.find((x) => (dir === "dep" ? x.source === other && x.target === id : x.source === id && x.target === other));
    const names = e ? takes(e) : [];
    return `<button class="row rel" data-go="${esc(id)}"><span class="sw ${dir}"></span><span class="k">${esc(shown(id))}</span>
      <span class="d mono">${names.length ? esc(clip(names.join(", "), 90)) : "the whole module"}</span></button>`;
  }).join("")}</div>`;
}

/* The module as functions: the finest grain modfence shows. Purposes are the author's docstrings, else a cached
   one-sentence summary that the server asks a small model for the first time a module is opened. */
const describing = new Set();
async function moduleFns(id, describe) {
  let v = S.fn[id]; // read into a local: a reload during the wait replaces S.fn
  if (!v) { try { v = await api(`/api/module?${q("&m=" + encodeURIComponent(id))}`); } catch { return null; } S.fn[id] = v; }
  if (describe && S.claude && !describing.has(id) && (v.undescribed || !v.purpose)) {
    describing.add(id); paintFns(id);
    try {
      const r = await api(`/api/describe?${q()}`, { module: id });
      S.fn[id] = v = r;
      if (r.purpose_source === "ai") { (S.full.ai_purposes ||= {})[id] = r.purpose; }
      if (r.error) toast(`Could not describe the functions: ${r.error}`, false);
    } catch (e) { toast(`Could not describe the functions: ${e.message}`, false); }
    describing.delete(id);
  }
  return S.fn[id] || v;
}
const AI_TAG = '<i class="ai" title="Written by a small model from the code; the author wrote no docstring">AI</i>';
const testsIds = () => new Set(S.full.modules.filter((m) => m.kind === "tests").map((m) => m.id));
const usedElsewhere = (f) => { const t = testsIds(); return f.used_by.some((m) => !t.has(m)); }; // tests use everything; not interface
function fnRows(v) { // folded: only what other modules use (the module's interface); unfold for all
  const byFile = {};
  v.functions.filter((f) => S.allFns || usedElsewhere(f)).forEach((f) => (byFile[f.file] ||= []).push(f));
  const busy = describing.has(v.module);
  return Object.entries(byFile).map(([file, fs]) => `<div class="fgroup"><div class="fhead mono">${esc(file.split("/").pop())}<span>${plural(fs.length, "unit")}</span></div>
    ${fs.map((f) => {
      const short = f.kind === "method" ? f.name.split(".").pop() : f.name;
      const call = f.kind === "def" || f.kind === "method";
      const ref = `\`${f.name}${call ? "()" : ""}\` in ${f.file}`;
      const desc = f.purpose ? esc(f.purpose) + (f.source === "ai" ? " " + AI_TAG : "") : busy ? '<span class="wait">Describing…</span>' : '<span class="wait">No description</span>';
      return `<button type="button" class="fn ${f.kind}${short.startsWith("_") ? " private" : ""}" data-ref="${esc(ref)}" title="Insert into the instruction">
        <span class="fname mono">${f.kind === "class" || f.kind === "const" ? `<em>${f.kind}</em> ` : ""}${esc(short)}${call ? `<span class="args">(${esc(f.args)})</span>` : ""}</span>
        <span class="fdesc">${desc}</span>
        ${f.used_by.length ? `<span class="fuse mono" title="Imported by ${esc(f.used_by.map(shown).join(", "))}">${f.used_by.length} ↗</span>` : ""}</button>`;
    }).join("")}</div>`).join("") || `<p class="none">No functions or classes.</p>`;
}
function paintFns(id) {
  const box = $("#fns"), v = S.fn[id];
  if (!box || S.selected !== id || !v) return;
  const used = v.functions.filter(usedElsewhere).length;
  box.innerHTML = (S.allFns || used ? fnRows(v) : "")
    + (used < v.functions.length ? `<button type="button" class="btn quiet" data-allfns>${S.allFns ? "Only what other modules use" : `Show all ${v.functions.length}`}</button>` : "");
  box.querySelectorAll("[data-ref]").forEach((b) => (b.onclick = () => insertRef(b.dataset.ref)));
  $("[data-allfns]", box)?.addEventListener("click", () => { S.allFns = !S.allFns; paintFns(id); });
  $("#fncount").textContent = `${used} used by other modules`;
  if (v.purpose && !mod(id).doc) $("#mdoc").innerHTML = esc(v.purpose) + " " + AI_TAG;
}
function insertRef(text) {
  const ta = $("#prompt"), s = ta.selectionStart ?? ta.value.length;
  const pad = s && !/\s$/.test(ta.value.slice(0, s)) ? " " : "";
  ta.setRangeText(pad + text + " ", s, ta.selectionEnd ?? s, "end");
  ta.focus(); autosize();
}

function renderOverview() {
  if (S.fenceLabel) { // the fence's files, one line each
    const fs = [...S.scope].filter((f) => S.full.files[f]).sort();
    $("#v-over").innerHTML = `<div class="sect"><h3>Files</h3><div class="rows">${fs.map((f) => `<button class="row" data-file="${esc(f)}"><span class="k">${esc(f.split("/").pop())}</span><span class="d">${esc(S.full.files[f].doc || "")}</span><span class="n">${S.full.files[f].lines} ln</span></button>`).join("")}</div></div>`;
    $("#v-over").querySelectorAll("[data-file]").forEach((b) => (b.onclick = () => openFile(b.dataset.file)));
    return;
  }
  const m = mod(S.selected); if (!m) return;
  const { dep, use } = related(m.id);
  const tasks = S.tasks.filter((t) => t.modules.includes(m.id));
  $("#v-over").innerHTML = `
    ${tasks.length ? `<div class="sect"><h3>Exercises</h3><div class="rows">${tasks.map((t, i) => `<button class="task" data-task="${i}" title="${esc(t.summary)}"><b>${esc(t.title)}</b></button>`).join("")}</div></div>` : ""}
    <div class="sect"><h3>Functions <small id="fncount"></small></h3><div id="fns"><p class="none">Loading…</p></div></div>
    <div class="sect"><h3>Uses</h3>${relRows([...dep], m.id, "dep")}</div>
    <div class="sect"><h3>Used by</h3>${relRows([...use], m.id, "use")}</div>
    <details class="src"><summary>Source files</summary><div class="rows">${m.files.map((f) => {
      const fi = S.graph.files[f];
      return `<button class="row" data-file="${esc(f)}"><span class="k">${esc(f.split("/").pop())}</span><span class="d">${esc(fi.error || "")}</span><span class="n">${fi.lines} ln</span></button>`;
    }).join("")}</div></details>`;
  const v = $("#v-over");
  v.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => select(b.dataset.go)));
  v.querySelectorAll("[data-file]").forEach((b) => (b.onclick = () => openFile(b.dataset.file)));
  v.querySelectorAll("[data-task]").forEach((b) => (b.onclick = () => useTask(tasks[+b.dataset.task])));
  const id = m.id;
  moduleFns(id).then(() => { paintFns(id); return moduleFns(id, true); }).then(() => paintFns(id));
}

const X_ICON = '<svg viewBox="0 0 10 10" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M2 2l6 6M8 2L2 8"/></svg>';
function renderFence() {
  if (!S.selected) return;
  const testsMod = S.full.modules.find((m) => m.kind === "tests");
  const mode = `<div class="mode" role="group" aria-label="Fence mode">
    <button type="button" data-ro="0" aria-pressed="${!S.readOnly}" title="Edits only inside the fence; reads everything">Edit</button>
    <button type="button" data-ro="1" aria-pressed="${S.readOnly}" title="Explains, edits nothing">Explain</button></div>`;
  let line;
  if (S.readOnly) {
    line = `<div class="fline ro"><span class="lab">Read only.</span> ${[...S.scope].map((id) => `<span class="mono">${esc(shown(id))}</span>`).join(", ")}: explain, no edits.</div>`;
  } else {
    const chipName = (id) => (id.includes("::") ? id.split("::")[1] + "()" : shown(id));
    const chips = S.fenceLabel && S.scope.size > 1 ? `<span class="fchip">${esc(S.fenceLabel)} (${plural(S.scope.size, "file")})</span>`
      : [...S.scope].map((id) => `<span class="fchip">${esc(chipName(id))}${S.scope.size > 1 ? `<button type="button" data-rm="${esc(id)}" aria-label="Remove ${esc(shown(id))} from the fence">${X_ICON}</button>` : ""}</span>`).join("");
    const add = testsMod && !S.scope.has(testsMod.id) ? `<button type="button" class="fadd" data-add="${esc(testsMod.id)}">+ ${esc(testsMod.id)}</button>` : "";
    const seal = `<button type="button" class="fseal" data-seal aria-pressed="${!S.unsealed}" title="${S.unsealed ? "The agent may read every file in this run. Click to seal." : "Sealed: other modules' code is hidden; the agent gets their interfaces, so it cannot lean on or break their internals. Click to let it read everything."}">${S.unsealed ? "Unsealed" : "Sealed"}</button>`;
    line = `<div class="fline"><span class="lab">Can edit:</span>${chips}${add}${seal}</div>`;
  }
  const nocli = S.claude ? "" : `<div class="nocli">Claude Code CLI not found. Install it and log in, or start modfence with CLAUDE_BIN set to its path, then restart. Reading the project still works.</div>`;
  $("#fence").innerHTML = nocli + mode + line;
  $("[data-seal]", $("#fence"))?.addEventListener("click", () => { S.unsealed = !S.unsealed; renderFence(); });
  $("#fence").querySelectorAll("[data-ro]").forEach((b) => (b.onclick = () => { S.readOnly = b.dataset.ro === "1"; afterFenceChange(); }));
  $("#fence").querySelectorAll("[data-rm]").forEach((b) => (b.onclick = () => { S.scope.delete(b.dataset.rm); if (!S.scope.has(S.selected)) S.selected = [...S.scope][0]; afterFenceChange(); }));
  $("#fence").querySelectorAll("[data-add]").forEach((b) => (b.onclick = () => { S.scope.add(b.dataset.add); afterFenceChange(); }));
  syncSend();
}
const scopeKey = () => [...S.scope].sort().join("+");

/* ---------------- tasks from TASKS.md ---------------- */
async function loadTasks() {
  S.tasks = [];
  try { S.tasks = parseTasks((await api(`/api/file?${q("&path=TASKS.md")}`)).text); } catch { /* no TASKS.md */ }
  if (S.selected) renderOverview();
}
function parseTasks(text) {
  // "## 4. Exponent operator (crosses modules: `lexer`, `parser`)" + "Target: `calc.lexer`, `calc.parser`."
  const ids = S.full.modules.map((m) => m.id);
  return text.split(/\n(?=## )/).filter((sec) => /^## /.test(sec)).map((sec) => {
    const lines = sec.split("\n");
    const head = lines[0].replace(/^##\s*/, "");
    const num = (head.match(/^(\d+)[.)]/) || [])[1] || "";
    const title = head.replace(/^\d+[.)]\s*/, "").replace(/\s*\((single module|crosses modules?)[^)]*\)\s*$/i, "").trim();
    const target = lines.find((l) => /^\s*target/i.test(l)) || "";
    const ticks = (s) => [...s.matchAll(/`([^`]+)`/g)].map((m) => m[1].replace(/\.py$/, ""));
    let modules = ticks(target).flatMap((t) => [t.replace(/\./g, "/"), t + ".py"]).filter((t) => ids.includes(t));
    if (!modules.length) {
      const short = ticks((head.match(/\(([^)]*)\)/) || [])[1] || "");
      modules = ids.filter((id) => short.includes(id.split("/").pop()));
    }
    const body = lines.slice(1).join("\n").trim();
    const summary = body.replace(/^target[^\n]*\n?/i, "").replace(/[*`#>]/g, "").replace(/\s+/g, " ").trim();
    return { title: num ? `${num}. ${title}` : title, body, modules: [...new Set(modules)], level: modules.length > 1 ? `${modules.length} modules` : "1 module", summary };
  }).filter((t) => t.modules.length);
}
function fillPrompt(text) {
  const ta = $("#prompt");
  if (ta.value.trim() && ta.value.trim() !== text.trim() && !confirm("Replace the instruction you are writing?")) return false;
  ta.value = text; autosize(); ta.focus();
  return true;
}
function useTask(t) {
  if (!fillPrompt(`${t.title}\n\n${t.body}`)) return;
  S.readOnly = false;
  // An exercise changes behavior, so its tests must change too: fence the tests module with it.
  const tests = S.full.modules.filter((m) => m.kind === "tests").map((m) => m.id);
  S.scope = new Set([S.selected, ...t.modules.filter((m) => m !== S.selected), ...tests]);
  afterFenceChange();
}

/* ---------------- runs: a log per fence ---------------- */
async function loadTalk() {
  const v = $("#v-talk");
  v.innerHTML = "";
  $("#tcount").textContent = "";
  if (!S.scope.size) return;
  const key = scopeKey();
  let runs = [];
  try { runs = (await api(`/api/history?${q("&scope=" + encodeURIComponent(key))}`)).runs; } catch { /* none */ }
  if (key !== scopeKey()) return;
  v.innerHTML = "";
  runs.forEach((r) => { const view = newRun(r.prompt, r.scope, r.at, r.read_only, r.phase); r.events.forEach((e) => view.add(e, true)); view.flush(); });
  const plans = v.querySelectorAll(".plan [data-build]"); // only the newest run's plan can still be built
  plans.forEach((b, i) => (b.disabled = i < plans.length - 1 || v.lastElementChild !== b.closest(".run")));
  $("#tcount").textContent = runs.length ? String(runs.length) : "";
  if (S.job && !S.job.done && S.job.key === key) S.job.view = attachLive(S.job);
  if (!v.children.length) renderStarters();
}
function renderStarters() {
  const m = mod(S.selected);
  const name = shown(m ? m.id : "");
  const starters = [
    ["Read only", `Explain what ${name} does, how data flows through it, and which file I should read first.`, true],
    ["Read only", `Find one bug or unhandled edge case in ${name}. Point to the exact line and explain why, but do not fix it.`, true],
    ["Plan, then build", `Add one test for ${name} that covers a case the current tests miss, and run the tests.`, false],
  ];
  $("#v-talk").innerHTML = `<p class="none">No runs in this fence yet. An edit starts with a plan: the agent reads the project, asks what it needs to know and lists the functions it will touch. You answer, press Build, and review every function it changed.</p>
    <div class="starters">${starters.map(([k, t], i) => `<button type="button" data-st="${i}"><b>${k}</b>${esc(t)}</button>`).join("")}</div>`;
  $("#v-talk").querySelectorAll("[data-st]").forEach((b) => (b.onclick = () => {
    const [, text, ro] = starters[+b.dataset.st];
    if (fillPrompt(text)) { S.readOnly = ro; afterFenceChange(); }
  }));
}
function attachLive(job) {
  const view = newRun(job.prompt, job.scope, job.at, job.readOnly, job.phase);
  job.events.forEach((e) => view.add(e, true));
  view.flush();
  return view;
}
function scrollTalk() { const b = $("#pbody"); requestAnimationFrame(() => (b.scrollTop = b.scrollHeight)); }
const hhmm = (t) => (t ? new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "now");

function newRun(prompt, scope, at, readOnly, phase) {
  $("#v-talk .starters")?.remove(); $("#v-talk > p.none")?.remove();
  const root = document.createElement("article");
  root.className = `run${phase ? " " + phase : ""}`;
  const what = phase === "plan" ? "planning, read only" : phase === "build" ? "building, can edit" : readOnly ? "read only" : "can edit";
  root.innerHTML = `<div class="rhead"><span class="mono">${hhmm(at)}</span><span>${what} <span class="mono">${esc(scope.map(shown).join(", "))}</span></span><span class="st live">${phase === "plan" ? "Planning" : "Running"}</span></div>
    <p class="instr">${esc(prompt)}</p><div class="rbody"></div>`;
  $("#v-talk").appendChild(root);
  const body = $(".rbody", root), st = $(".rhead .st", root);
  let textEl = null, textBuf = "", stepsEl = null, pending = 0;
  const steps = {};
  const renderText = () => { pending = 0; if (textEl) textEl.innerHTML = md(textBuf); };
  const view = {
    root,
    add(e, replay) {
      if (e.kind === "text") {
        if (!textEl) { textEl = document.createElement("div"); textEl.className = "md"; body.appendChild(textEl); stepsEl = null; textBuf = ""; }
        textBuf += e.text;
        if (!replay && !pending) pending = requestAnimationFrame(renderText);
      } else if (e.kind === "text_end") {
        renderText(); textEl = null;
      } else if (e.kind === "tool") {
        if (textEl) { renderText(); textEl = null; }
        if (!stepsEl) { stepsEl = document.createElement("div"); stepsEl.className = "steps"; body.appendChild(stepsEl); }
        const s = document.createElement("div");
        s.className = `step${e.edit ? " edit" : ""}`;
        s.innerHTML = `<span class="ic">${toolIcon(e.name)}</span><span class="tn">${esc(e.name)}</span><span class="td">${esc(shortPath(e.detail))}</span><span class="st">…</span>`;
        stepsEl.appendChild(s);
        steps[e.id] = s;
      } else if (e.kind === "tool_result") {
        const s = steps[e.id];
        if (!s) return;
        $(".st", s).textContent = e.denied ? "blocked" : e.error ? "failed" : "ok";
        if (e.denied || e.error) {
          s.classList.add(e.denied ? "denied" : "err");
          const why = document.createElement("span");
          why.className = "why";
          why.textContent = e.denied ? "Outside the fence, so the edit was blocked." : clip(String(e.text || "").trim(), 240);
          s.after(why);
        }
      } else if (e.kind === "status") {
        const d = document.createElement("div"); d.className = "status"; d.textContent = e.text; body.appendChild(d);
      } else if (e.kind === "error") {
        const d = document.createElement("div"); d.className = "error"; d.textContent = e.text; body.appendChild(d);
      } else if (e.kind === "result") {
        view.result = e;
      } else if (e.kind === "plan") {
        if (textEl) { renderText(); textEl = null; }
        stepsEl = null;
        renderPlan(body, e.plan, prompt, scope);
      } else if (e.kind === "check") {
        view.check = e;
      } else if (e.kind === "changes") {
        view.changes = e;
      } else if (e.kind === "requests") {
        view.requests = e.items;
      } else if (e.kind === "done") {
        if (textEl) { renderText(); textEl = null; }
        body.querySelectorAll(".step .st").forEach((x) => { if (x.textContent === "…") x.textContent = "stopped"; });
        const r = view.result, quiet = phase === "plan" && !(view.changes && view.changes.files && view.changes.files.length);
        st.className = `st ${r && r.ok ? (view.check && !view.check.ok ? "bad" : "ok") : "bad"}`;
        st.textContent = r ? (r.ok ? `${phase === "plan" ? "Planned" : view.check && !view.check.ok ? "Done, check failed" : "Done"}${r.duration_s ? ` · ${r.duration_s}s` : ""}` : "Stopped with an error") : "Stopped";
        if (quiet) { const f = document.createElement("div"); f.className = "rfoot"; f.innerHTML = r ? `<span class="meta">${r.turns ? plural(r.turns, "turn") : ""}${r.cost_usd != null ? ` · $${r.cost_usd.toFixed(3)}` : ""}</span>` : ""; root.appendChild(f); }
        else { renderChanges(root, view.changes, r, view.check, !replay); if (!replay && view.job) { renderReview(root, view.job, view.changes); renderLesson(root, view.job); } }
        if (view.requests?.length) renderRequests(root, view.requests, view.job, replay);
      }
      if (!replay) scrollTalk();
    },
    flush() { if (textEl) renderText(); },
  };
  scrollTalk();
  return view;
}

/* ---------------- the project's own docs on the map (golden rules 1, 2, 7) ----------------
   Docs stay the project's markdown files; modfence places each on the boxes it is about (docs.py) and the user can
   add or remove a place, on a box or on a link. A run fenced to a box gets pointers to its docs, not their text. */
const docsOn = (keys) => (S.docs?.docs || []).filter((d) => d.boxes.some((b) => keys.includes(b)));
async function openSkills(refresh) {
  $("#stitle").textContent = "Skills for this project";
  $("#scode").innerHTML = `<p class="sub">Reading the project's libraries and searching skills.sh…</p>`;
  showSheet(true);
  let d;
  try { d = await api(`/api/skills?${q(refresh === true ? "&refresh=1" : "")}`); }
  catch (e) { $("#scode").innerHTML = `<p class="sub">${esc(e.message)}</p>`; return; }
  const libs = Object.entries(d.stack?.libs || {}).sort((a, b) => b[1] - a[1]).slice(0, 10);
  const row = (k) => `<li class="${k.match === "fuzzy" ? "weak" : ""}"><div><b>${esc(k.name)}</b> <span class="mono">${esc(k.source)}</span></div>`
    + `<span>${esc(k.reason)} · ${k.installs.toLocaleString()} installs · ${k.stars == null ? "stars N/A" : k.stars.toLocaleString() + " stars"}${k.match === "fuzzy" ? " · loose match" : ""}</span>`
    + `<div class="pa">${k.installed ? `<span class="meta">In this project</span>` : `<button class="btn" type="button" data-inst="${esc(k.source)}|${esc(k.name)}">Add to this project</button>`} <a href="${esc(k.url)}" target="_blank" rel="noopener">Read it</a></div></li>`;
  $("#scode").innerHTML = `<p class="sub">This project uses ${libs.map(([n, c]) => `<b>${esc(n)}</b> (${c})`).join(", ") || "no third-party library modfence can see"}. `
    + `Skills are matched to these, kept when installed 1,000+ times and their repo has 100+ stars. A skill is third-party instructions Claude Code will follow in this project: read it before adding. modfence never runs it.</p>`
    + (d.errors?.length ? `<p class="sub bad">${esc(d.errors.join("; "))}</p>` : "")
    + `<ul class="pf skills">${(d.skills || []).map(row).join("") || "<li>No skill passed the filters.</li>"}</ul>`
    + (d.installed?.length ? `<p class="sub">Already in this project: ${d.installed.map(esc).join(", ")}</p>` : "")
    + `<button class="btn quiet" type="button" data-refresh>Search again</button>`;
  $("[data-refresh]", $("#scode")).onclick = () => openSkills(true);
  $("#scode").querySelectorAll("[data-inst]").forEach((b) => (b.onclick = async () => {
    const [source, skill] = b.dataset.inst.split("|");
    b.disabled = true;
    try { const r = await api(`/api/skills/install?${q()}`, { source, skill }); b.outerHTML = `<span class="meta">Added: ${r.written.length} files in .claude/skills/${esc(skill)}</span>`; }
    catch (e) { b.disabled = false; toast(e.message, false); }
  }));
}
function renderLesson(root, job) { // golden rule 7: what this run taught goes into the docs of the box it changed
  const fr = fileRoles(), keys = [...new Set(job.scope.flatMap((s) => Object.keys(fr).filter((f) => f === s || f.startsWith(s + "/")).map((f) => "role:" + fr[f])))];
  const docs = docsOn(keys), rid = keys[0]?.slice(5), fallback = `docs/${(rname(rid) || "notes").replace(/[^a-z0-9]+/gi, "_").toLowerCase()}.md`;
  const box = document.createElement("div");
  box.className = "lesson";
  box.innerHTML = `<label>Anything the agent should know next time? <input type="text" placeholder="e.g. server/ has a copy of this file: change both"></label>`
    + `<select>${docs.map((d) => `<option value="${esc(d.path)}">${esc(d.path)}</option>`).join("")}<option value="${esc(fallback)}">${esc(fallback)} (new)</option></select>`
    + `<button class="btn" type="button">Remember</button>`;
  root.appendChild(box);
  $("button", box).onclick = async () => {
    const text = $("input", box).value.trim(), path = $("select", box).value;
    if (!text) return;
    try {
      await api(`/api/docs/lesson?${q()}`, { path, text });
      if (rid && !docs.some((d) => d.path === path)) await api(`/api/docs/choose?${q()}`, { path, box: "role:" + rid, on: true });
      S.docs = await api(`/api/docs?${q()}`);
      box.innerHTML = `<span class="meta">Written under Gotchas in ${esc(path)}.</span>`;
    } catch (e) { toast(e.message, false); }
  };
}

/* Golden rules 4 and 7: the agent stopped at the fence. Each file it needs is a card: the change it wants and why, and
   the user's choice. Approving continues the same conversation with the file (or its whole role) inside the fence. */
function renderRequests(root, items, job, replay) {
  const fr = fileRoles(), box = document.createElement("div");
  box.className = "requests";
  box.innerHTML = `<h4>The agent asks to edit outside the fence</h4>` + items.map((it, k) => {
    const rid = fr[it.path], role = rid && S.roles?.roles.find((r) => r.id === rid);
    return `<div class="req" data-k="${k}"><div class="rp"><span class="mono">${esc(it.path)}</span>${role ? ` <span class="rr">in ${esc(role.name)}</span>` : ""}</div>`
      + `<p>${it.why ? esc(it.why) : "It tried to edit this file; no reason given."}</p>`
      + (replay || !job ? "" : `<div class="pa"><button class="btn primary" type="button" data-file>Allow this file</button>`
        + (role ? `<button class="btn" type="button" data-role>Allow all of ${esc(role.name)}</button>` : "")
        + `<button class="btn quiet" type="button" data-no>Refuse</button></div>`) + `</div>`;
  }).join("");
  root.appendChild(box);
  items.forEach((it) => { const n = [...document.querySelectorAll(".node")].find((x) => mod(x.dataset.id)?.files?.includes(it.path)); n?.classList.add("asks"); });
  box.querySelectorAll(".req").forEach((el) => {
    const it = items[el.dataset.k], role = S.roles?.roles.find((r) => r.id === fr[it.path]);
    const go = (paths) => { box.querySelectorAll("button").forEach((b) => (b.disabled = true)); document.querySelectorAll(".node.asks").forEach((n) => n.classList.remove("asks"));
      startRun(`Approved: ${paths.length > 1 ? (role ? role.name : plural(paths.length, "file")) : paths[0]}`, [...new Set([...job.scope, ...paths])], false, job.phase, { job: job.id, paths }); };
    $("[data-file]", el)?.addEventListener("click", () => go([it.path]));
    $("[data-role]", el)?.addEventListener("click", () => go(ownFiles(role)));
    $("[data-no]", el)?.addEventListener("click", () => { el.classList.add("refused"); el.querySelector(".pa").innerHTML = `<span class="meta">Refused. The fence stays as it was.</span>`; document.querySelectorAll(".node.asks").forEach((n) => n.classList.remove("asks")); });
  });
}

/* A run's changes, read as functions: what was added, changed or removed, and what each now does. The line diff
   is one click further, for whoever wants it. */
const SYM = { added: "+", changed: "~", removed: "−" };
function renderChanges(root, c, r, check, live) {
  const files = c && c.files ? c.files : c ? [...c.added, ...c.modified, ...c.deleted].map((p) => ({ path: p, status: "modified", plus: null, minus: null, outside: c.outside_scope.includes(p), revertible: false })) : [];
  const box = document.createElement("div");
  box.className = "changes";
  const outside = files.filter((f) => f.outside);
  const rev = files.some((f) => f.revertible) && c && c.run;
  const units = (f) => f.funcs == null ? (f.path.endsWith(".py") && f.status !== "deleted" ? `<p class="none">Could not read its functions.</p>` : "")
    : f.funcs.map((u) => `<div class="cf ${u.status}"><span class="sym" aria-label="${u.status}">${SYM[u.status]}</span><span class="mono nm">${esc(u.name)}${u.kind === "def" || u.kind === "method" ? "()" : ""}</span><span class="fdesc" data-unit="${esc(f.path + "::" + u.name)}"></span></div>`).join("");
  const broke = (c && c.contract) || [];
  box.innerHTML = (broke.length ? `<div class="banner bad"><b>Contract broken</b>: other modules use ${broke.length === 1 ? "this name" : "these names"} and the run changed ${broke.length === 1 ? "it" : "them"}.<ul class="broke">${broke.map((b) => `<li><span class="mono">${esc(b.name)}</span> ${esc(b.change)} <span class="u">used by ${esc([...new Set(b.users.map((u) => u.split(":")[0]))].slice(0, 3).join(", "))}${b.users.length > 3 ? " …" : ""}</span></li>`).join("")}</ul></div>` : "")
    + (outside.length ? `<div class="banner bad">${plural(outside.length, "file")} changed outside the fence: <span class="mono">${esc(outside.map((f) => f.path).join(", "))}</span>${rev ? `<button class="btn" type="button" data-rev-out>Revert those</button>` : ""}</div>` : "")
    + (files.length ? files.map((f, i) => `<div class="cfile${f.outside ? " out" : ""}">
        <div class="cfh"><span class="mono p" title="${esc(f.path)}">${esc(f.path)}</span>${f.outside ? '<span class="tagout">outside fence</span>' : ""}${f.status !== "modified" ? `<span class="st">${f.status}</span>` : ""}
          <span class="s mono">${f.plus == null ? "N/A" : `<span class="plus">+${f.plus}</span> <span class="minus">−${f.minus}</span>`}</span>
          ${c.run ? `<button class="btn quiet" type="button" data-diff="${i}" aria-expanded="false" title="Show the line diff">Source</button>` : ""}</div>
        ${units(f)}</div>`).join("")
      : `<p class="none" style="padding:8px 10px">No files changed.</p>`);
  const foot = document.createElement("div");
  foot.className = "rfoot";
  const sel = check && check.selected, which = sel ? `${plural(sel.files.length, "test file")} covering the fence${sel.users?.length ? ` and ${plural(sel.users.length, "module")} using it` : ""}` : "the whole suite";
  foot.innerHTML = (check ? `<div class="chk ${check.ok ? "ok" : "bad"}">${check.ok ? "Done check passed" : "Done check failed"} (ran ${which}): ${esc(check.summary || "project tests")}${check.blocked ? `. The agent was sent back ${plural(check.blocked, "time")}.` : "."}</div>` : "")
    + (check && check.untested?.length ? `<div class="chk bad">Changed without a test: <span class="mono">${esc(check.untested.join(", "))}</span></div>` : "")
    + (c && c.commit_message ? `<div class="commit"><span class="mono">${esc(c.commit_message.split("\n")[0])}</span><button class="btn quiet mini" type="button" data-copy title="Copy the drafted commit message">Copy commit message</button></div>` : "")
    + (c && c.ripple.length ? `<div class="ripple">Uses the changed code: ${c.ripple.map((m) => `<button type="button" data-go="${esc(m)}">${esc(shown(m))}</button>`).join("")} run the tests to check them.</div>` : "")
    + (files.length ? `<button class="btn" type="button" data-tests>Run tests</button>` : "")
    + (rev ? `<button class="btn" type="button" data-rev>Revert this run</button>` : "")
    + (r ? `<span class="meta">${r.turns ? plural(r.turns, "turn") : ""}${r.cost_usd != null ? ` · $${r.cost_usd.toFixed(3)}` : ""}</span>` : "");
  root.appendChild(box);
  root.appendChild(foot);
  box.querySelectorAll("[data-diff]").forEach((b) => (b.onclick = () => toggleDiff(b, c.run, files[+b.dataset.diff].path)));
  foot.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => select(b.dataset.go)));
  $("[data-tests]", foot)?.addEventListener("click", runTests);
  $("[data-copy]", foot)?.addEventListener("click", () => navigator.clipboard?.writeText(c.commit_message).then(() => toast("Commit message copied."), () => toast("Copy failed: select the text instead.", false)));
  $("[data-rev]", foot)?.addEventListener("click", () => revert(root, c.run, null, files.length));
  $("[data-rev-out]", box)?.addEventListener("click", () => revert(root, c.run, outside.map((f) => f.path), outside.length));
  // What the changed functions do now. A live run asks for summaries of the new code; a replay shows what is cached.
  const mods = [...new Set(files.filter((f) => f.funcs && f.funcs.length && f.status !== "deleted").map((f) => moduleOf(f.path)))].filter(mod);
  mods.forEach((id) => moduleFns(id, live).then((v) => v && v.functions.forEach((u) => {
    const cell = box.querySelector(`[data-unit="${CSS.escape(u.file + "::" + u.name)}"]`);
    if (cell && u.purpose) cell.innerHTML = esc(u.purpose) + (u.source === "ai" ? " " + AI_TAG : "");
  })));
}
async function toggleDiff(btn, run, path) {
  const box = btn.closest(".cfile"), open = $("pre.diff", box);
  if (open) { open.remove(); btn.setAttribute("aria-expanded", "false"); btn.textContent = "Source"; return; }
  let diff;
  try { ({ diff } = await api(`/api/diff?${q(`&run=${encodeURIComponent(run)}&path=${encodeURIComponent(path)}`)}`)); }
  catch (e) { toast(`Could not load the diff: ${e.message}`, false); return; }
  const pre = document.createElement("pre");
  pre.className = "diff";
  pre.innerHTML = diff.split("\n").map((l) => `<span class="${l.startsWith("@@") ? "hunk" : l.startsWith("+") && !l.startsWith("+++") ? "add" : l.startsWith("-") && !l.startsWith("---") ? "del" : ""}">${esc(l) || " "}</span>`).join("");
  box.appendChild(pre);
  btn.setAttribute("aria-expanded", "true"); btn.textContent = "Hide source";
}

/* The plan card: a planning run's questions (recommended answer preselected), the functions it means to touch, and
   how we will know it works. Build resumes the same session, so nothing the planner read is read again. */
function renderPlan(body, p, prompt, scope) {
  const card = document.createElement("div");
  card.className = "plan";
  const plan = p.plan || {}, fns = Array.isArray(plan.functions) ? plan.functions : [];
  const pick = p.questions.map((x) => (Number.isInteger(x.recommended) && x.options[x.recommended] !== undefined ? x.recommended : 0));
  card.innerHTML = `<div class="ph">Plan</div>
    <p class="goal">${esc(plan.goal || "")}</p>
    ${p.questions.length ? `<ol class="pq">${p.questions.map((x, qi) => `<li><b>${esc(x.q)}</b><div class="opts" role="radiogroup" aria-label="${esc(x.q)}">${x.options.map((o, oi) => `<button type="button" role="radio" data-q="${qi}" data-o="${oi}" aria-checked="${oi === pick[qi]}">${esc(o)}${oi === x.recommended ? '<small>recommended</small>' : ""}</button>`).join("")}</div></li>`).join("")}</ol>` : `<p class="none">No open questions.</p>`}
    ${fns.length ? `<div class="pf">${fns.map((f) => `<div class="cf ${f.change === "add" ? "added" : f.change === "remove" ? "removed" : "changed"}"><span class="sym">${SYM[f.change === "add" ? "added" : f.change === "remove" ? "removed" : "changed"]}</span><span class="mono nm">${esc(f.name || "")}</span><span class="fdesc">${esc(f.why || "")} <span class="mono fl">${esc(String(f.file || "").split("/").pop())}</span></span></div>`).join("")}</div>` : ""}
    <p class="pd"><b>Done when:</b> ${esc(String(plan.done || "N/A").replace(/[.。]\s*$/, ""))}. <span class="sub">Before the agent may finish, the project's tests run; if they fail it is sent back once.</span></p>
    <div class="pa"><button class="btn primary" type="button" data-build>Build</button><span class="sub">Or write a different instruction below.</span></div>`;
  body.appendChild(card);
  card.querySelectorAll("[role=radio]").forEach((b) => (b.onclick = () => {
    pick[+b.dataset.q] = +b.dataset.o;
    card.querySelectorAll(`[data-q="${b.dataset.q}"]`).forEach((x) => x.setAttribute("aria-checked", String(x === b)));
  }));
  $("[data-build]", card).onclick = () => {
    if (S.job && !S.job.done) { toast("Wait for the current run to finish.", false); return; }
    const answers = p.questions.map((x, qi) => `- ${x.q} ${x.options[pick[qi]]}`).join("\n");
    const text = `Build the plan we agreed on.\nRequest: ${prompt}${answers ? `\nAnswers:\n${answers}` : ""}\nDone when: ${plan.done || "the tests pass"}`;
    document.querySelectorAll(".plan [data-build]").forEach((x) => (x.disabled = true));
    startRun(text, scope, false, "build");
  };
}
async function revert(root, run, paths, n) {
  if (S.job && !S.job.done) { toast("Wait for the current run to finish.", false); return; }
  if (!confirm(`Revert ${plural(n, "file")} to how they were before this run? Files edited again since then are left alone.`)) return;
  let res;
  try { res = await api(`/api/revert?${q()}`, { run, paths }); }
  catch (e) { toast(`Revert failed: ${e.message}`, false); return; }
  const note = document.createElement("div");
  note.className = "rfoot";
  note.innerHTML = `<span class="reverted">Reverted ${plural(res.reverted.length, "file")}.</span>${res.skipped.length ? ` Left alone: ${res.skipped.map((s) => `<span class="mono">${esc(s.path)}</span> (${esc(s.why)})`).join(", ")}.` : ""}`;
  root.appendChild(note);
  S.marks = { changed: new Set(), ripple: new Set(), stats: {} };
  await loadGraph(false);
  toast(`Reverted ${plural(res.reverted.length, "file")}${res.skipped.length ? `, left ${res.skipped.length} alone` : ""}.`);
  if (S.view === "history") renderHistory();
}

const fwd = (s) => String(s || "").replace(/\\/g, "/");
const shortPath = (s) => {
  const root = fwd(S.graph && S.graph.root) + "/", v = fwd(s);
  return root.length > 1 && v.toLowerCase().startsWith(root.toLowerCase()) ? v.slice(root.length) : v;
};
function toolIcon(name) {
  const p = {
    Read: '<path d="M4 2h5l3 3v7a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V3a1 1 0 0 1 1-1z"/><path d="M9 2v3h3"/>',
    Edit: '<path d="M10 2.5l2.5 2.5L6 11.5H3.5V9z"/>', Write: '<path d="M10 2.5l2.5 2.5L6 11.5H3.5V9z"/>', MultiEdit: '<path d="M10 2.5l2.5 2.5L6 11.5H3.5V9z"/>',
    Bash: '<rect x="1.5" y="2.5" width="12" height="10" rx="2"/><path d="M4 6l2 1.5L4 9M7.5 9.5H10"/>',
    Grep: '<circle cx="6.5" cy="6.5" r="4"/><path d="M9.5 9.5L13 13"/>', Glob: '<circle cx="6.5" cy="6.5" r="4"/><path d="M9.5 9.5L13 13"/>',
    TodoWrite: '<path d="M2.5 4h1M2.5 7.5h1M2.5 11h1M6 4h6.5M6 7.5h6.5M6 11h6.5"/>',
  }[name] || '<circle cx="7.5" cy="7.5" r="2.5"/>';
  return `<svg viewBox="0 0 15 15" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${p}</svg>`;
}

/* tiny markdown: fenced code, inline code, bold, italics, headings, lists, paragraphs */
function md(src) {
  const blocks = [];
  let s = String(src).replace(/```[^\n]*\n([\s\S]*?)(```|$)/g, (_, code) => { blocks.push(code); return `\u0000${blocks.length - 1}\u0000`; });
  s = esc(s).replace(/`([^`\n]+)`/g, "<code>$1</code>").replace(/\*\*([^*\n]+)\*\*/g, "<strong>$1</strong>").replace(/(^|[^*])\*([^*\n]+)\*/g, "$1<em>$2</em>");
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
function autosize() { const t = $("#prompt"); t.style.height = "auto"; t.style.height = Math.min(200, Math.max(54, t.scrollHeight)) + "px"; syncSend(); }
// Golden rule 1: the pipeline routes by what the fence touches. A task inside one role that nothing outside depends
// on through copies, HTTP or shared history takes the fast path (build at once, lean rule, tests). Anything else takes
// the full path (plan first; questions only where the task is unclear), and the reasons are shown. One click switches.
function route(scope = [...S.scope]) {
  if (!scope.length || S.readOnly) return null;
  const fr = fileRoles(), sc = scope.map((s) => s.split("::")[0]);
  const mine = new Set(Object.keys(S.full.files).filter((f) => sc.some((s) => f === s || f.startsWith(s + "/") || s === "." && !f.includes("/"))));
  const rids = new Set([...mine].map((f) => fr[f]).filter(Boolean)), links = S.roles?.links || [], why = [];
  if (rids.size > 1) why.push(`spans ${rids.size} roles`);
  const copies = new Set(links.filter((l) => l.kind === "copy" && mine.has(l.file) !== mine.has(l.target_file)).map((l) => (mine.has(l.file) ? l.file : l.target_file)));
  if (copies.size) why.push(`${plural(copies.size, "file")} here ${copies.size === 1 ? "has a copy" : "have copies"} outside the fence`);
  const http = new Set(links.filter((l) => l.kind === "http" && mine.has(l.target_file) && !mine.has(l.file)).map((l) => l.name));
  if (http.size) why.push(`${plural(http.size, "HTTP route")} served here ${http.size === 1 ? "is" : "are"} called from outside`);
  const co = (S.roles?.cochange || []).filter(([a, b, n]) => n >= 5 && rids.has(a) !== rids.has(b)).sort((x, y) => y[2] - x[2]);
  if (co.length) why.push(`usually changes together with ${co.slice(0, 2).map(([a, b]) => rname(rids.has(a) ? b : a)).join(" and ")}`);
  const full = S.forceRoute ? S.forceRoute === "full" : why.length > 0;
  return { full, why };
}
function renderRoute() {
  const r = route(), el = $("#route");
  el.hidden = !r;
  if (!r) return;
  el.className = `route ${r.full ? "full" : "fast"}`;
  el.innerHTML = r.full ? `<b>Full path</b>: plan first${r.why.length ? `, because the fence ${esc(r.why.join("; "))}` : " (your choice)"}.`
    : `<b>Fast path</b>: build now with the lean rule and the tests${r.why.length ? ` (your choice; the fence ${esc(r.why.join("; "))})` : ": one role, nothing outside depends on it"}.`;
}
function syncSend() {
  const running = S.job && !S.job.done;
  const b = $("#send"), r = route();
  renderRoute();
  b.classList.toggle("stop", !!running);
  b.textContent = running ? "Stop" : S.readOnly ? "Explain" : r && !r.full ? "Build" : "Plan";
  b.disabled = !running && (!$("#prompt").value.trim() || !S.claude);
}

// Fence coding: an edit starts as a read-only plan you answer and approve; Build then edits inside the fence.
async function send() {
  if (S.job && !S.job.done) { await api("/api/cancel", { job: S.job.id }).catch(() => {}); return; }
  const prompt = $("#prompt").value.trim();
  if (!prompt || !S.scope.size || !S.claude) return;
  const r = route();
  if (await startRun(prompt, [...S.scope], S.readOnly, S.readOnly ? null : r && !r.full ? "build" : "plan")) { $("#prompt").value = ""; autosize(); }
}
async function startRun(prompt, scope, readOnly, phase, approve) {
  let res;
  try { res = approve ? await api(`/api/approve?${q()}`, approve) : await api(`/api/ask?${q()}`, { prompt, scope, read_only: readOnly, phase, unsealed: !!S.unsealed }); }
  catch (e) { toast(e.message, false); return false; }
  if (phase !== "plan") { S.marks = { changed: new Set(), ripple: new Set(), stats: {} }; paintSelection(); }
  const key = [...scope].sort().join("+");
  if (key !== scopeKey()) { S.scope = new Set(scope); afterFenceChange(); }
  const job = { id: res.job, prompt, scope, readOnly, phase, key, events: [], done: false, at: Date.now() / 1000 };
  S.job = job;
  setTab("talk");
  job.view = newRun(prompt, scope, job.at, readOnly, phase);
  job.view.job = job;
  syncSend(); showRunbar();
  listen(job);
  return true;
}
function listen(job) {
  const es = new EventSource(`/api/events?job=${job.id}&from=${job.events.length}`);
  es.onmessage = (m) => {
    const e = JSON.parse(m.data);
    if (e.i < job.events.length) return;
    job.events.push(e);
    if (job.key === scopeKey() && job.view && job.view.root.isConnected) job.view.add(e);
    if (e.kind === "tool" && e.edit) markEditing(e.detail);
    if (e.kind === "changes") onChanges(e);
    if (e.kind === "done") {
      job.done = true; es.close(); syncSend(); showRunbar();
      if (job.key === scopeKey()) $("#tcount").textContent = String(Number($("#tcount").textContent || 0) + 1);
      const r = job.events.find((x) => x.kind === "result");
      const planned = job.events.some((x) => x.kind === "plan");
      toast(!(r && r.ok) ? "Run stopped." : planned ? "Plan ready. Answer the questions, then Build." : job.phase === "plan" ? "The planner did not return a plan; read its reply." : "Run finished. Review the changed functions in the Runs tab.", !!(r && r.ok));
    }
  };
  es.onerror = () => { es.close(); if (!job.done) setTimeout(() => listen(job), 800); };
}
let runTimer = 0;
function showRunbar() {
  const bar = $("#runbar"), job = S.job, on = !!(job && !job.done);
  bar.hidden = !on;
  document.body.classList.toggle("running", on);
  clearInterval(runTimer);
  if (!on) return;
  const draw = () => {
    const secs = Math.round(Date.now() / 1000 - job.at);
    bar.innerHTML = `<span class="dot" aria-hidden="true"></span><span>Agent ${job.phase === "plan" ? "planning · read only" : job.readOnly ? "running · read only" : "building · can edit"} <span class="mono">${esc(job.scope.map(shown).join(", "))}</span> · ${secs}s</span><button class="btn" type="button" id="rb-open">Show</button><button class="btn" type="button" id="rb-stop">Stop</button>`;
    $("#rb-open").onclick = () => { select(job.scope[0]); S.scope = new Set(job.scope); afterFenceChange(); setTab("talk"); };
    $("#rb-stop").onclick = () => api("/api/cancel", { job: job.id }).catch(() => {});
  };
  draw();
  runTimer = setInterval(draw, 1000);
}
function markEditing(path) {
  const rel = shortPath(path);
  const id = moduleOf(rel);
  document.querySelectorAll(`.node[data-id="${CSS.escape(id)}"]`).forEach((n) => {
    n.classList.remove("changed"); void n.getBoundingClientRect(); n.classList.add("changed");
  });
}
async function onChanges(c) {
  await loadGraph(false);
  markRun(c);
}
function markRun(c) { // paint a run's changed modules (green dots, +n −m) and the modules that use them (yellow)
  const stats = {};
  (c.files || []).forEach((f) => {
    if (!f.path.endsWith(".py")) return;
    const id = moduleOf(f.path);
    const s = (stats[id] ||= { plus: 0, minus: 0 });
    s.plus += f.plus || 0; s.minus += f.minus || 0;
  });
  S.marks = { changed: new Set(c.modules || []), ripple: new Set(c.ripple || []), stats };
  paintSelection(); renderCrumbs();
}

/* ---------------- sheet: file, diff, help, output ---------------- */
let sheetReturn = null;
function showSheet(on) {
  $("#scrim").classList.toggle("show", on);
  $("#sheet").hidden = !on;
  document.body.classList.toggle("sheet-open", on);
  if (on) { sheetReturn = document.activeElement; $("#sclose").focus(); }
  else if (sheetReturn && sheetReturn.isConnected) sheetReturn.focus();
}
async function openFile(path, lines = []) {
  let text;
  try { ({ text } = await api(`/api/file?${q("&path=" + encodeURIComponent(path))}`)); }
  catch (e) { toast(e.message, false); return; }
  const hl = new Set(lines);
  $("#stitle").textContent = path;
  $("#scode").innerHTML = `<div class="code">${text.split("\n").map((l, i) => `<div class="ln${hl.has(i + 1) ? " hl" : ""}" id="L${i + 1}"><b>${i + 1}</b>${esc(l) || " "}</div>`).join("")}</div>`;
  showSheet(true);
  if (lines.length) requestAnimationFrame(() => $(`#L${lines[0]}`)?.scrollIntoView({ block: "center" }));
}
function showText(title, text) { $("#stitle").textContent = title; $("#scode").innerHTML = `<pre class="out">${esc(text)}</pre>`; showSheet(true); }
function showHelp() {
  $("#stitle").textContent = "How modfence works";
  $("#scode").innerHTML = `<div class="help">
    <p>modfence is for fence coding: working with an AI agent on a codebase you read as modules and functions, not lines. The agent is your own Claude Code; modfence decides what it may touch and shows you, function by function, what it did.</p>
    <h3>An edit in five steps</h3>
    <ol><li><b>Pick a module.</b> Click it in any view, or press <kbd>/</kbd> and type its name. Its functions are listed with what each one does.</li>
      <li><b>Set the fence.</b> The selected module is editable. <kbd>Shift</kbd>-click adds more. Switch to <i>Read only</i> for explanations, with no edits at all.</li>
      <li><b>Say what you want.</b> Click a function to mention it. Press <i>Plan</i>: the agent reads the project, asks what it needs to decide, and lists the functions it will touch.</li>
      <li><b>Answer and build.</b> Pick the answers (its recommendation is preselected) and press <i>Build</i>. A hook blocks every edit outside the fence; before the agent may finish, the project's tests run, and if they fail it is sent back once.</li>
      <li><b>Review.</b> Each run lists the functions added, changed and removed, and what they now do. The line diff is behind <i>Source</i>. Run the tests or revert the run.</li></ol>
    <h3>Inks on the screen</h3>
    <dl><dt>fence</dt><dd>The modules the agent may edit (pink, hatched).</dd>
      <dt>uses</dt><dd>Modules this one takes functions from (blue). Hover an arrow to see which names.</dd>
      <dt>used by</dt><dd>Modules that take functions from this one (orange). Changing those functions can break them.</dd>
      <dt>changed</dt><dd>Changed by the last run (green dots).</dd>
      <dt>uses changed code</dt><dd>After a run: modules that use what changed (yellow, dashed). Run the tests.</dd>
      <dt>AI</dt><dd>A one-line description written by a small model because the author wrote no docstring. Cached until the file changes.</dd>
      <dt>layers</dt><dd>Modules that import others sit above the ones they import. The bottom layer imports nothing in the project.</dd></dl>
    <h3>Keys</h3>
    <dl><dt>/</dt><dd>Find a module</dd><dt>1 2</dt><dd>Modules, History</dd><dt>${IS_MAC ? "⌘" : "Ctrl"} Enter</dt><dd>Run the instruction</dd><dt>Esc</dt><dd>Close the panel or this sheet</dd><dt>?</dt><dd>This help</dd></dl></div>`;
  showSheet(true);
}

/* ---------------- tests, toast, theme, search, resize ---------------- */
let toastT = 0;
function toast(text, ok = true, ms = 4200, onclick) {
  const t = $("#toast");
  $("#ttext").textContent = text;
  t.classList.toggle("bad", !ok);
  t.classList.add("show");
  t.onclick = onclick || (() => t.classList.remove("show"));
  clearTimeout(toastT);
  toastT = setTimeout(() => t.classList.remove("show"), ms);
}
async function runTests() {
  const b = $("#tests"), lbl = $(".lbl", b);
  b.classList.remove("ok", "bad"); b.disabled = true; lbl.textContent = "Testing…";
  try {
    const r = await api(`/api/tests?${q()}`, {});
    const ran = (r.summary.match(/Ran (\d+)/) || r.summary.match(/(\d+) passed/) || [])[1];
    b.classList.add(r.ok ? "ok" : r.ok === false ? "bad" : "");
    lbl.textContent = r.ok === null ? "No tests" : `Tests: ${ran || "?"} ${r.ok ? "passed" : "· failing"}`;
    toast(`${r.summary || "No tests found"}. Show output`, r.ok !== false, 8000, () => showText("Test output", r.output || r.summary));
  } catch (e) { toast(e.message, false); lbl.textContent = "Run tests"; }
  b.disabled = false;
}
function applyTheme(mode) {
  if (mode === "auto") document.documentElement.removeAttribute("data-theme"); else document.documentElement.dataset.theme = mode;
  store.set("modfence.theme", mode);
  $("#theme .lbl").textContent = { auto: "Auto", light: "Light", dark: "Dark" }[mode];
  $("#theme").setAttribute("aria-label", `Appearance: ${mode}. Click to change.`);
}
function wireSearch() {
  const input = $("#find"), list = $("#findlist");
  let hits = [], at = 0;
  const close = () => { list.hidden = true; input.setAttribute("aria-expanded", "false"); };
  const draw = () => {
    const t = input.value.trim().toLowerCase();
    hits = S.full.modules.filter((m) => !t || m.id.toLowerCase().includes(t) || mdoc(m).toLowerCase().includes(t)).slice(0, 12);
    at = Math.min(at, Math.max(0, hits.length - 1));
    list.innerHTML = hits.map((m, i) => `<li role="option" id="fo${i}" aria-selected="${i === at}" data-id="${esc(m.id)}">${esc(shown(m.id))}<span>${m.lines} ln</span></li>`).join("") || `<li aria-disabled="true">No module matches</li>`;
    list.hidden = false; input.setAttribute("aria-expanded", "true");
    input.setAttribute("aria-activedescendant", hits.length ? `fo${at}` : "");
  };
  const pick = (id) => { close(); input.value = ""; select(id); };
  input.addEventListener("input", () => { at = 0; draw(); });
  input.addEventListener("focus", draw);
  input.addEventListener("blur", () => setTimeout(close, 150));
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { at = Math.min(hits.length - 1, at + 1); draw(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { at = Math.max(0, at - 1); draw(); e.preventDefault(); }
    else if (e.key === "Enter" && hits[at]) { pick(hits[at].id); e.preventDefault(); }
    else if (e.key === "Escape") { close(); input.blur(); }
  });
  list.addEventListener("mousedown", (e) => { const li = e.target.closest("li[data-id]"); if (li) pick(li.dataset.id); });
}
function wireResize() {
  const grip = $("#grip");
  const setW = (w) => { w = Math.max(340, Math.min(Math.round(innerWidth * 0.7), w)); document.documentElement.style.setProperty("--panel-w", w + "px"); store.set("modfence.panel", w); };
  const saved = Number(store.get("modfence.panel")); if (saved) setW(saved);
  grip.addEventListener("pointerdown", (e) => {
    grip.setPointerCapture(e.pointerId);
    const move = (ev) => setW(innerWidth - ev.clientX);
    const up = () => { grip.removeEventListener("pointermove", move); grip.removeEventListener("pointerup", up); };
    grip.addEventListener("pointermove", move); grip.addEventListener("pointerup", up);
  });
  grip.addEventListener("keydown", (e) => {
    const w = $("#panel").getBoundingClientRect().width;
    if (e.key === "ArrowLeft") { setW(w + 24); e.preventDefault(); }
    if (e.key === "ArrowRight") { setW(w - 24); e.preventDefault(); }
  });
}

/* ---------------- wiring ---------------- */
const typing = () => /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "") || document.activeElement?.isContentEditable;
function wire() {
  wireCanvas(); wireViews(); wireSearch(); wireResize();
  $("#panel").inert = true;
  $("#picker").onchange = async (e) => {
    S.p = Number(e.target.value); store.set("modfence.project", S.p);
    closePanel(); S.marks = { changed: new Set(), ripple: new Set(), stats: {} }; S.userCam = false; S.focus = ""; S.level = null; S.role = null; S.area = null; S.proposed = false; S.proposedAreas = false;
    const b = $("#tests"); b.classList.remove("ok", "bad"); $(".lbl", b).textContent = "Run tests";
    await loadGraph(true);
  };
  $("#refresh").onclick = () => loadGraph(false).then(() => toast("Project re-scanned."));
  $("#tests").onclick = runTests;
  $("#help").onclick = showHelp;
  $("#theme").onclick = () => { const order = ["auto", "light", "dark"], cur = store.get("modfence.theme") || "auto"; applyTheme(order[(order.indexOf(cur) + 1) % 3]); };
  $("#close").onclick = closePanel;
  $("#seg").addEventListener("click", (e) => { const b = e.target.closest("[data-tab]"); if (b) setTab(b.dataset.tab, true); });
  $("#seg").addEventListener("keydown", (e) => { if (e.key === "ArrowRight" || e.key === "ArrowLeft") { setTab(S.tab === "over" ? "talk" : "over", true); e.preventDefault(); } });
  $("#prompt").addEventListener("input", autosize);
  $("#route").addEventListener("click", () => { const r = route(); S.forceRoute = r && r.full ? "fast" : "full"; syncSend(); });
  $("#prompt").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); } });
  $("#send").onclick = send;
  $("#forget").onclick = async () => {
    if (!S.scope.size || (S.job && !S.job.done)) return;
    if (!confirm(`Clear the run history and the agent's session for the fence ${[...S.scope].map(shown).join(", ")}? Files are not touched.`)) return;
    await api(`/api/forget?${q()}`, { scope: [...S.scope] }).catch(() => {});
    loadTalk(); toast("Run history cleared for this fence.");
  };
  $("#sclose").onclick = () => showSheet(false);
  $("#scrim").onclick = () => showSheet(false);
  addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (!$("#sheet").hidden) showSheet(false);
      else if (S.selected && !typing()) closePanel();
      return;
    }
    if (!$("#sheet").hidden) {
      if (e.key === "Tab") { e.preventDefault(); $("#sclose").focus(); } // the sheet has one control: keep focus there
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); $("#find").focus(); $("#find").select(); return; }
    if (typing() || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "/") { e.preventDefault(); $("#find").focus(); }
    else if (e.key === "?") { e.preventDefault(); showHelp(); }
    else if ("12".includes(e.key) && e.key.length === 1) setView(VIEWS[+e.key - 1].id);
  });
}

wire();
boot().catch((e) => toast(`Could not load: ${e.message}`, false, 10000));
