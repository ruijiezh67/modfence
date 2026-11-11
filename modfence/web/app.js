/* modfence UI: see the modules; when you give your agent a task in Claude Code, see which module it was fenced to,
   why, and switch it or allow a crossing. As few buttons as the loop needs. */
"use strict";

const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const NODE_W = 220, NODE_H = 76, GAP_X = 36, GAP_Y = 52;
const store = { get(k) { try { return localStorage.getItem(k); } catch { return null; } }, set(k, v) { try { localStorage.setItem(k, v); } catch {} } };

const S = {
  projects: [], p: 0, graph: null, full: null, focus: "", level: null, roles: null, role: null, calls: null, pos: {}, rows: [], view: "graph", selected: null, scope: new Set(), readOnly: false,
  tab: "over", marks: { changed: new Set(), ripple: new Set(), stats: {} }, job: null, tasks: [], claude: null, fn: {},
  unsealed: true, // golden rule 4: sealing made agents hit the hook about twice a run for no measured gain; one click turns it on
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
function fillPicker() { // every project this server has, and a way to open another folder on the same port
  $("#picker").innerHTML = S.projects.map((p) => `<option value="${p.i}" title="${esc(p.path)}">${esc(p.name)}</option>`).join("")
    + `<option value="add">Open another project…</option>`;
}
async function boot() {
  const { projects, claude } = await api("/api/projects");
  S.projects = projects; S.claude = claude;
  const saved = Number(store.get("modfence.project") || 0);
  S.p = projects[saved] ? saved : 0;
  fillPicker();
  const hp = new URLSearchParams(location.hash.slice(1));
  if (hp.get("p") && projects[+hp.get("p")]) S.p = +hp.get("p");
  $("#picker").value = S.p;
  await loadGraph(true);
  pollFence(); setInterval(pollFence, 3000); // ponytail: a 3 s poll of one small file; an event stream when it matters
  pollIntents(); setInterval(pollIntents, 5000);
}

async function loadGraph(fit) {
  if (!S.full) $("#loading").hidden = false; // a big project's first scan takes seconds: say so where the map will be
  S.full = await api(`/api/graph?${q()}`);
  try { S.roles = await api(`/api/roles?${q()}`); } catch { S.roles = null; }
  S.sig = JSON.stringify(S.full) + JSON.stringify(S.roles); S.loadedAt = Date.now(); // a rescan redraws only on a change
  $("#loading").hidden = true;
  if (!S.level) S.level = S.roles?.areas?.length ? "areas" : S.roles && S.roles.roles.length ? "roles" : "modules";
  regroup();
  if (S.roles && S.roles.status === "none" && S.full.modules.length > ROLE_AT && S.claude && !S.proposed) { S.proposed = true; proposeRoles(); }
  else if (S.roles?.roles.length && !S.roles.areas?.length && S.claude && !S.proposedAreas) { S.proposedAreas = true; proposeAreas(); }
  updateStats();
  restoreHand();
  if (fit) fitView(false);
  if (S.selected) { S.fenceSet = new Set(filesOf([...S.scope])); renderHeader(); paintSelection(); }
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
  $("#stats").textContent = `${plural(files, "file")} · ${lines.toLocaleString()} lines`; // golden rule 1: "module" means a box of MODULES.md only
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
// Golden rule 3: a role named like its function ("recorder" in recorder) reads as that function's core, so the two
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
  card.innerHTML = `<div class="pk"><b>${esc(name)}</b></div>`
    + `<div class="pm mono">${plural(m.files.length, "file")} · ${m.lines.toLocaleString()} ln</div>`
    + (doc ? `<p>${esc(doc)}</p>` : `<p class="none">No description in the code.</p>`)
    // golden rule 3: say what to change right here; the box is the fence, the map stays where it is
    + (folder || id === "role:?" ? "" : `<p class="meta">To change it, give your agent the task in Claude Code: modfence fences the module the task needs (the top bar shows which, and why).</p>`)
    + `<div class="pa">${role || folder ? `<button type="button" class="btn" data-open>${area ? "Open roles" : role ? "Open parts" : "Open folder"} ▸</button>` : ""}</div>`
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
  $("[data-open]", card)?.addEventListener("click", () => { unpick(); area ? openArea(id.slice(5)) : role ? openRole(id.slice(5)) : (S.focus = id.slice(0, -1), regroup(), fitView()); });
  $("[data-open]", card)?.focus();
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
  $("#crumbs").innerHTML = `<em>Grouping the roles into about 7 modules…</em>`;
  if (await rolesDo("areas", {}, null)) { S.level = "areas"; S.area = null; regroup(); fitView(); toast(`Modules proposed (${S.roles.areas_how}${S.roles.areas_cost_usd != null ? `, $${S.roles.areas_cost_usd.toFixed(3)}` : ""}). Rename a module or move a role any time.`); }
}
const areaOf = () => Object.fromEntries((S.roles?.areas || []).flatMap((a) => a.roles.map((r) => [r, a.id])));
function openArea(aid) { S.area = aid; S.level = "roles"; regroup(); fitView(); }
function areaGraph() { // level 1: the areas, each the own files of its roles
  const fr = fileRoles(), ar = areaOf(), boxes = areaBoxes();
  const nodeOf = (f) => { const a = S.roles.file_area ? S.roles.file_area[f] : ar[S.roles.doors?.[f] || fr[f]]; return a && "area:" + a; };
  return { ...S.full, modules: boxes, edges: linked(boxes, aggregate((f) => !kindOf(f) && nodeOf(f)), nodeOf, (r) => ar[r] && "area:" + ar[r]) };
}
function areaBoxes() {
  return S.roles.areas.map((a) => {
    const rs = a.roles.map((rid) => S.roles.roles.find((r) => r.id === rid)).filter(Boolean);
    const files = S.roles.file_area ? Object.keys(S.roles.file_area).filter((f) => S.roles.file_area[f] === a.id) : rs.flatMap(ownFiles);
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
// The fence for a box without leaving the map: the run panel opens beside it and the level stays as it is.
function openFence(scope, label, doc) {
  S.fenceLabel = label; S.fenceDoc = doc || "";
  S.selected = S.full.files[scope[0]]?.module || scope[0]; S.scope = new Set(scope);
  document.body.classList.add("panel-open"); $("#panel").inert = false;
  if (!S.userCam) requestAnimationFrame(() => fitView()); // the map moves left of the panel, so no box hides under it
  return afterFenceChange(); // resolves once the fence's log is drawn, so a card added after it is not drawn over
}
// The project files a fence covers: files, folders, and modules of MODULES.md ("@module:name").
function filesOf(scope) {
  const area = (n) => (S.roles?.areas || []).find((a) => a.name === n)?.id;
  return Object.keys(S.full.files).filter((f) => scope.some((s) => s.startsWith("@module:")
    ? !!area(s.slice(8)) && S.roles.file_area?.[f] === area(s.slice(8)) : f === s || f.startsWith(s + "/") || (s === "." && !f.includes("/"))));
}
function fileList(files, fdoc) {
  return `<ul class="pf">${files.map((f) => `<li><span class="mono">${esc(f.split("/").pop())}</span>${fdoc(f) ? `<span>${esc(fdoc(f))}</span>` : ""}</li>`).join("")}</ul>`;
}
function renderCrumbs() {
  const c = $("#crumbs"), big = S.full.modules.length > GROUP_AT, has = S.roles && S.roles.roles.length;
  const step = (n, text, attrs, cur) => `<button type="button" ${attrs}${cur ? ' aria-current="true"' : ""}><b>${n}</b> ${esc(text)}</button>`;
  let h = "";
  if (S.level === "modules") {
    if (!big && !has && S.full.modules.length <= ROLE_AT) { c.hidden = true; return; }
    const parts = S.focus ? S.focus.split("/") : [];
    h = (has ? step(1, S.roles.areas?.length ? "Modules" : "Roles", `data-lv="${S.roles.areas?.length ? "areas" : "roles"}"`) + `<span>/</span>` : "") + `<button type="button" data-f="" aria-current="${!S.focus}">${esc(S.full.name)}</button>`
      + parts.map((p, i) => `<span>/</span><button type="button" data-f="${esc(parts.slice(0, i + 1).join("/"))}">${esc(p)}</button>`).join("")
      + (big ? `<em>${plural(S.full.modules.length, "folder")} and files</em>` : "");
  } else {
    const r = S.roles.roles.find((x) => x.id === S.role), A = (S.roles.areas || []).find((a) => a.id === S.area);
    let n = 1;
    if (S.roles.areas?.length) {
      h = step(n++, "Modules", 'data-lv="areas"', S.level === "areas");
      if (S.level !== "areas" && A) h += `<span>/</span>` + step(n++, A.name, `data-area="${esc(A.id)}"`, S.level === "roles");
    } else h = step(n++, "Roles", 'data-lv="roles"', S.level === "roles");
    if (S.level === "parts") h += `<span>/</span>` + step(n, S.role === "?" ? "not placed yet" : rname(S.role), `data-role="${esc(S.role)}"`, true);
    if (S.level === "areas") h += `<em title="${esc(S.roles.areas_how || "")}">${plural(S.roles.areas.length, "module")}</em>${S.roles.modules_file ? `<a class="act q" href="/mod.html#p=${S.p}&v=project" title="Rename, split or merge the modules on the Intents page">Edit modules</a>` : `<button type="button" class="act" data-savemods title="Keep these modules for the fence and your agent (in .mod/project.mod)">Save modules</button>`}`;
    if (S.hiddenLinks && !S.dense) h += `<em title="Strongest ${KEEP_LINKS} links per box">${S.hiddenLinks} weak links hidden</em>`;
    if (S.level === "roles" && !A) h += `<em title="${esc(S.roles.how || "")}">${S.roles.status === "confirmed" ? "Confirmed" : "Proposed"}</em>`
;
    if (S.level === "parts" && r && S.outside) h += `<em title="${esc(r.purpose || "")}">${S.outside} imports to other roles</em>`;
  }
  c.hidden = false;
  c.innerHTML = h + roundLine();
  c.querySelectorAll("[data-f]").forEach((b) => (b.onclick = () => { S.focus = b.dataset.f; regroup(); fitView(); }));
  c.querySelectorAll("[data-lv]").forEach((b) => (b.onclick = () => { S.level = b.dataset.lv; regroup(); fitView(); }));
  c.querySelectorAll("[data-role]").forEach((b) => (b.onclick = () => openRole(b.dataset.role)));
  c.querySelectorAll("[data-area]").forEach((b) => (b.onclick = () => openArea(b.dataset.area)));
  $("[data-savemods]", c)?.addEventListener("click", () => rolesDo("save_modules", {}, "Modules saved. Edit them any time on the Intents page; the map and the fence follow."));
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
// Every map (golden rule 3): each link leaves a box side square to it, the links on one side spread along it in the
// order of their other ends (so they do not cross at the box), and an S or L curve joins the two ports. A link uses
// only sides that face the other box; it prefers the pair facing each other along the map's main direction, then a
// corner (one side up or down, the other sideways), and leaves those when the curve runs far behind another box.
const NORMAL = { top: [0, -1], bottom: [0, 1], left: [-1, 0], right: [1, 0] };
function port(p, side, f) {
  return side === "top" ? [p.x + NODE_W * f, p.y] : side === "bottom" ? [p.x + NODE_W * f, p.y + NODE_H]
    : side === "left" ? [p.x, p.y + NODE_H * f] : [p.x + NODE_W, p.y + NODE_H * f];
}
function sCurve([sx, sy], ss, [tx, ty], ts) {
  const [ax, ay] = NORMAL[ss], [bx, by] = NORMAL[ts];
  tx += bx * 4; ty += by * 4; // room for the arrow head
  const k = ss === ts ? 0 : !ax === !bx ? 0.5 : 0.6, along = (nx) => (nx ? Math.abs(tx - sx) : Math.abs(ty - sy));
  const ds = k ? Math.max(30, along(ax) * k) : 34 + Math.hypot(tx - sx, ty - sy) * 0.18, dt = k ? Math.max(30, along(bx) * k) : ds;
  return [sx, sy, sx + ax * ds, sy + ay * ds, tx + bx * dt, ty + by * dt, tx, ty];
}
const pathOf = (c) => { const f = c.map((v) => v.toFixed(1)); return `M${f[0]},${f[1]} C${f[2]},${f[3]} ${f[4]},${f[5]} ${f[6]},${f[7]}`; };
function routeEdges(g) {
  const boxes = Object.entries(S.pos).filter(([, p]) => !p.chip);
  const hits = (c, a, b) => { // ponytail: 20 samples per curve against every box; fine for the 7 to 30 boxes of a free map
    let n = 0;
    for (let i = 1; i < 20; i++) {
      const t = i / 20, u = 1 - t, w = [u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t];
      const x = w[0] * c[0] + w[1] * c[2] + w[2] * c[4] + w[3] * c[6], y = w[0] * c[1] + w[1] * c[3] + w[2] * c[5] + w[3] * c[7];
      if (boxes.some(([id, p]) => id !== a && id !== b && x > p.x - 6 && x < p.x + NODE_W + 6 && y > p.y - 6 && y < p.y + NODE_H + 6)) n++;
    }
    return n;
  };
  const centre = (id) => [S.pos[id].x + NODE_W / 2, S.pos[id].y + NODE_H / 2];
  g.edges.forEach((e) => {
    const a = S.pos[e.source], b = S.pos[e.target], [ax, ay] = centre(e.source), [bx, by] = centre(e.target), dx = bx - ax, dy = by - ay;
    const faces = (p, side, [ox, oy]) => side === "top" ? oy < p.y : side === "bottom" ? oy > p.y + NODE_H : side === "left" ? ox < p.x : ox > p.x + NODE_W;
    const gapX = Math.abs(dx) > NODE_W + 16, gapY = Math.abs(dy) > NODE_H + 16, upright = Math.abs(dy) * NODE_W > Math.abs(dx) * NODE_H * 0.8;
    const tries = [];
    for (const ss of ["top", "bottom", "left", "right"]) for (const ts of ["top", "bottom", "left", "right"]) {
      if (!faces(a, ss, [bx, by]) || !faces(b, ts, [ax, ay])) continue;
      const vs = ss === "top" || ss === "bottom", vt = ts === "top" || ts === "bottom";
      if (vs === vt && !(vs ? gapY : gapX)) continue; // facing sides with no room between them would curl back
      tries.push([ss, ts, vs !== vt ? 1 : vs === upright ? 0 : 2]);
    }
    if (Math.abs(dy) < NODE_H) tries.push(["bottom", "bottom", 3]); // a U under the row, only for boxes side by side
    if (!tries.length) tries.push(dy > 0 ? ["bottom", "top", 0] : ["top", "bottom", 0]);
    let best = null;
    tries.forEach(([ss, ts, rank]) => { // a graze behind a box is fine, a long run behind one is not
      const score = hits(sCurve(port(a, ss, 0.5), ss, port(b, ts, 0.5), ts), e.source, e.target) * 0.5 + rank;
      if (!best || score < best.score) best = { score, ss, ts };
    });
    e._ss = best.ss; e._ts = best.ts;
  });
  const at = {}; // box and side: the link ends there, in the order of their other ends
  g.edges.forEach((e) => { (at[e.source + "|" + e._ss] ||= []).push([e, "s", e.target]); (at[e.target + "|" + e._ts] ||= []).push([e, "t", e.source]); });
  Object.entries(at).forEach(([key, list]) => {
    const side = key.slice(key.lastIndexOf("|") + 1), axis = side === "top" || side === "bottom" ? 0 : 1, n = list.length, step = Math.min(0.2, 0.72 / n);
    list.sort((x, y) => centre(x[2])[axis] - centre(y[2])[axis]);
    list.forEach(([e, end], k) => (e["_f" + end] = 0.5 + (k - (n - 1) / 2) * step));
  });
  g.edges.forEach((e) => (e._d = pathOf(sCurve(port(S.pos[e.source], e._ss, e._fs), e._ss, port(S.pos[e.target], e._ts, e._ft), e._ts))));
}

/* ---------------- drawing ---------------- */
const SVGNS = "http://www.w3.org/2000/svg";
const el = (tag, attrs = {}, parentEl) => {
  const n = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, v);
  if (parentEl) parentEl.appendChild(n);
  return n;
};

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
  routeEdges(g);
  const counts = g.edges.map((e) => e.receipts.length).sort((x, y) => x - y), weak = counts[Math.floor(counts.length / 2)] || 0, wmax = counts[counts.length - 1] || 1;
  g.edges.forEach((e) => {
    const d = e._d;
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
const clip = (s, n) => (s.length > n ? s.slice(0, n - 1) + "…" : s);

function related(id) {
  const dep = new Set(), use = new Set();
  S.graph.edges.forEach((e) => { if (e.source === id) dep.add(e.target); if (e.target === id) use.add(e.source); });
  return { dep, use };
}
function fenced(id) { return (S.selected !== null || S.fenceOn) && (inSet(S.scope, id) || !!mod(id)?.files?.some((f) => S.fenceSet?.has(f))); }
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
function roundLine() { // golden rule 5: which boxes at this level the last run changed, and which use changed code
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
  return { x0: Math.min(...xs.map((p) => p.x)) - 30, y0: Math.min(...xs.map((p) => p.y)) - 24,
           x1: Math.max(...xs.map((p) => p.x + NODE_W)) + 30, y1: Math.max(...xs.map((p) => p.y + NODE_H)) + 24 };
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
    if (!drag.moved && e.type === "pointerup") { if (S.picked) unpick(); else if (S.selected) closePanel(); }
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
  addEventListener("resize", () => { if (!S.userCam) fitView(false); });
}

/* ---------------- edge tooltip (keyboard users get the same receipts in the panel) ---------------- */
// What one module takes from another, by name: the functions and classes behind an import arrow.
const takes = (e) => [...new Set(e.receipts.map((r) => r.name).filter(Boolean))];
// Golden rule 3: hovering a line says in plain words what the link is and what it means for a change, with its
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
function onNodeClick(id) { pick(id); }
function closePanel() {
  const wasOpen = document.body.classList.contains("panel-open");
  S.selected = null; S.scope.clear(); S.fenceSet = new Set();
  if (wasOpen) api(`/api/fence/clear?${q()}`, {}).catch(() => {}); // agents started by hand are no longer fenced (409 while a run goes: it stays)
  document.body.classList.remove("panel-open");
  $("#panel").inert = true;
  if (wasOpen) requestAnimationFrame(() => S.view === "graph" && !S.userCam && fitView());
  paintSelection();
}
function afterFenceChange() { S.fenceSet = new Set(filesOf([...S.scope])); renderHeader(); paintSelection(); return loadTalk(); }

function renderHeader() {
  if (S.fenceLabel) { // a role or part: the panel is about the whole fence
    const fs = filesOf([...S.scope]);
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

const scopeKey = () => [...S.scope].sort().join("+");

/* ---------------- runs: a log per fence ---------------- */
async function loadTalk() {
  const v = $("#v-talk");
  v.innerHTML = "";
  if (!S.scope.size) return;
  const key = scopeKey();
  let runs = [];
  try { runs = (await api(`/api/history?${q("&scope=" + encodeURIComponent(key))}`)).runs; } catch { /* none */ }
  if (key !== scopeKey()) return;
  v.innerHTML = "";
  runs.forEach((r) => { const view = newRun(r.prompt, r.scope, r.at, r.read_only, r.phase); r.events.forEach((e) => view.add(e, true)); view.flush(); });
  const plans = v.querySelectorAll(".plan [data-build]"); // only the newest run's plan can still be built
  plans.forEach((b, i) => (b.disabled = i < plans.length - 1 || v.lastElementChild !== b.closest(".run")));
  if (S.job && !S.job.done && S.job.key === key) S.job.view = attachLive(S.job);
}
function attachLive(job) {
  const view = newRun(job.prompt, job.scope, job.at, job.readOnly, job.phase);
  job.events.forEach((e) => view.add(e, true));
  view.flush();
  if (job.wait) view.root.appendChild(job.wait); // a hand-off's waiting card survives a redraw of the log
  return view;
}
function scrollTalk() { const b = $("#pbody"); requestAnimationFrame(() => (b.scrollTop = b.scrollHeight)); }
const hhmm = (t) => (t ? new Date(t * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "now");

function newRun(prompt, scope, at, readOnly, phase) {
  $("#v-talk .starters")?.remove(); $("#v-talk > p.none")?.remove();
  scope = scope.length > 3 ? [plural(scope.length, "file")] : scope.map((s) => s.replace("@module:", "module "));
  const root = document.createElement("article");
  root.className = `run${phase ? " " + phase : ""}`;
  const what = phase === "plan" ? "planning, read only" : phase === "build" ? "building, can edit" : readOnly ? "read only" : "can edit";
  root.innerHTML = `<div class="rhead"><span class="mono">${hhmm(at)}</span><span>${what} <span class="mono">${esc(scope.map(shown).join(", "))}</span></span><span class="st live">${phase === "plan" ? "Planning" : phase === "hand" ? "Fence on" : "Running"}</span></div>
    ${prompt ? `<p class="instr">${esc(prompt)}</p>` : ""}<div class="rbody"></div>`; // a hand-off's task is typed in the agent
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
        else renderChanges(root, view.changes, r, view.check);
        if (view.requests?.length) renderRequests(root, view.requests, view.job, replay);
      }
      if (!replay) scrollTalk();
    },
    flush() { if (textEl) renderText(); },
  };
  scrollTalk();
  return view;
}

/* Golden rules 4 and 5: the agent stopped at the fence. Each file it needs is a card: the change it wants and why, and
   the user's choice. Approving continues the same conversation with the file (or its whole role) inside the fence. */
function renderRequests(root, items, job, replay, hand) { // hand: answers the user's own agent in place
  const box = document.createElement("div");
  box.className = "requests";
  box.innerHTML = `<h4>The agent asks to edit outside the fence</h4>` + items.map((it, k) => `<div class="req" data-k="${k}"><div class="rp"><span class="mono">${esc(it.path)}</span>${it.module ? ` <span class="rr">in ${esc(it.module)}</span>` : ""}</div>`
    + `<p>${it.why ? esc(it.why) : "Your agent tried to edit this file. Its reason is in your agent's chat."}</p>`
    + (replay || !hand ? "" : `<div class="pa"><button class="btn primary" type="button" data-yes>Allow ${it.module ? "module " + esc(it.module) : "this file"}</button><button class="btn quiet" type="button" data-no>Refuse</button></div>`) + `</div>`).join("");
  root.appendChild(box);
  items.forEach((it) => { const n = [...document.querySelectorAll(".node")].find((x) => mod(x.dataset.id)?.files?.includes(it.path)); n?.classList.add("asks"); });
  box.querySelectorAll(".req").forEach((el) => {
    const it = items[el.dataset.k];
    const go = (ok) => { el.querySelectorAll("button").forEach((b) => (b.disabled = true)); document.querySelectorAll(".node.asks").forEach((n) => n.classList.remove("asks"));
      hand(el, [it.module ? "@module:" + it.module : it.path], ok);
      if (!ok) { el.classList.add("refused"); el.querySelector(".pa").innerHTML = `<span class="meta">Refused. The fence stays as it was.</span>`; } };
    $("[data-yes]", el)?.addEventListener("click", () => go(true)); // golden rule 4: a whole module is granted at once
    $("[data-no]", el)?.addEventListener("click", () => go(false));
  });
}
// A click asks again instead of a confirm dialog, which VS Code's Simple Browser blocks.
function twice(btn, what, go) {
  btn.addEventListener("click", () => {
    if (btn.dataset.armed) return go();
    const text = btn.textContent;
    btn.dataset.armed = "1"; btn.textContent = `Click again to ${what}`;
    setTimeout(() => { delete btn.dataset.armed; btn.textContent = text; }, 4000);
  });
}

/* A run's changes, read as functions: what was added, changed or removed, and what each now does. The line diff
   is one click further, for whoever wants it. */
const SYM = { added: "+", changed: "~", removed: "−" };
function renderChanges(root, c, r, check) {
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
</div>
        ${units(f)}</div>`).join("")
      : `<p class="none" style="padding:8px 10px">No files changed.</p>`);
  const foot = document.createElement("div");
  foot.className = "rfoot";
  const sel = check && check.selected, which = sel ? `${plural(sel.files.length, "test file")} covering the fence${sel.users?.length ? ` and ${plural(sel.users.length, "module")} using it` : ""}` : "the whole suite";
  foot.innerHTML = (check ? `<div class="chk ${check.ok ? "ok" : "bad"}">${check.ok ? "Done check passed" : "Done check failed"} (ran ${which}): ${esc(check.summary || "project tests")}${check.blocked ? `. The agent was sent back ${plural(check.blocked, "time")}.` : "."}</div>` : "")
    + (check && check.untested?.length ? `<div class="chk bad">Changed without a test: <span class="mono">${esc(check.untested.join(", "))}</span></div>` : "")
    + (c && c.ripple.length ? `<div class="ripple">Uses the changed code: <span class="mono">${esc(c.ripple.map(shown).join(", "))}</span>. Its tests show whether they still work.</div>` : "")
    + (rev ? `<button class="btn quiet" type="button" data-rev>Revert this round</button>` : "")
    + (r ? `<span class="meta">${r.turns ? plural(r.turns, "turn") : ""}${r.cost_usd != null ? ` · $${r.cost_usd.toFixed(3)}` : ""}</span>` : "");
  root.appendChild(box);
  root.appendChild(foot);
  $("[data-rev]", foot) && twice($("[data-rev]", foot), `revert ${plural(files.length, "file")}`, () => revert(root, c.run, null, files.length));
  $("[data-rev-out]", box) && twice($("[data-rev-out]", box), `revert ${plural(outside.length, "file")}`, () => revert(root, c.run, outside.map((f) => f.path), outside.length));
}
async function revert(root, run, paths, n) {
  if (S.job && !S.job.done) { toast("Wait for the current run to finish.", false); return; }
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

async function restoreHand() { // a hand-off outlives a reload: the agent works in a terminal for minutes
  let res;
  try { res = await api(`/api/hand/active?${q()}`); } catch { return; }
  if (!res.job || (S.job && S.job.id === res.job)) return;
  await openFence(res.scope, res.label, "");
  showHand(res, false);
}
function showHand(res, copied) {
  const { prompt, scope, label } = res;
  const job = { id: res.job, prompt, scope, readOnly: false, phase: "hand", label, key: [...scope].sort().join("+"), events: [], done: false, at: res.at || Date.now() / 1000, asked: new Set() };
  S.job = job;
  S.scope = new Set(scope); S.fenceSet = new Set(filesOf(scope)); renderHeader(); // the log is keyed by the fence the server armed
  S.marks = { changed: new Set(), ripple: new Set(), stats: {} }; paintSelection();
  job.view = newRun(prompt, scope, job.at, false, "hand");
  job.view.job = job;
  const w = document.createElement("div");
  w.className = "handwait";
  w.innerHTML = `<p><b>Fence on: ${esc(label)}.</b> ${copied ? "This line is copied" : "Click the line to copy it"}: paste it into your agent's chat and type the task after it. Edits outside the box are blocked.</p>`
    + `<textarea class="handtext line" readonly rows="2" title="Click to copy">${esc(res.line)}</textarea>`
    + `<p class="meta" data-live>No edits yet. Nothing runs until you paste the line and a task into your agent.</p><div class="pa"><button class="btn primary" type="button" data-review>Review changes</button></div>`;
  job.view.root.appendChild(w);
  job.wait = w;
  $(".handtext", w).onclick = (e) => { // execCommand works where the async clipboard is not allowed (an editor's web view)
    e.target.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch {}
    toast(ok ? "Line copied." : "Line selected: press Ctrl+C.");
  };
  const answer = async (el, paths, ok) => { // golden rule 4: widen the fence for the agent already working, or not
    try {
      const r = await api(`/api/hand/answer?${q()}`, { job: job.id, paths, ok });
      if (!ok) return;
      job.scope = r.scope; job.key = [...r.scope].sort().join("+"); S.scope = new Set(r.scope); S.fenceSet = new Set(filesOf(r.scope)); renderHeader(); paintSelection();
      el.querySelector(".pa").innerHTML = `<span class="meta">Allowed. Tell your agent: <b>approved, continue</b>.</span>`;
    } catch (e) { toast(e.message, false); }
  };
  job.poll = setInterval(async () => {
    if (job.done || job.reviewing) return clearInterval(job.poll);
    try {
      const s = await api(`/api/hand/status?${q("&job=" + job.id)}`);
      if (job.reviewing) return;
      job.changed = s.changed.length;
      $("[data-live]", w) && ($("[data-live]", w).textContent = s.changed.length ? `Your agent changed ${plural(s.changed.length, "file")} so far: ${s.changed.slice(0, 4).join(", ")}${s.changed.length > 4 ? " …" : ""}` : "No edits yet. Nothing runs until you paste the line and a task into your agent.");
      S.marks = { changed: new Set(s.modules), ripple: new Set(), stats: {} }; paintSelection();
      const fresh = s.asks.filter((p) => !job.asked.has(p));
      if (fresh.length) {
        fresh.forEach((p) => job.asked.add(p));
        if (!w.isConnected || !document.body.classList.contains("panel-open")) await openFence(job.scope, job.label, "");
        renderRequests(w, fresh.map((path) => ({ path, module: s.owners?.[path] })), job, false, answer); scrollTalk();
        toast(`Your agent asks to edit ${fresh.length > 1 ? plural(fresh.length, "file") + " outside the fence" : fresh[0]}.`);
      }
    } catch {}
  }, 4000);
  $("[data-review]", w).onclick = async (e) => { // the review takes a few seconds on a big project: say so
    clearInterval(job.poll); job.reviewing = true; e.currentTarget.disabled = true; // a poll in flight must not overwrite this
    $("[data-live]", w).textContent = "Reviewing: the changed functions, the names other modules use, the map…";
    const btn = e.currentTarget;
    try { await api(`/api/hand/finish?${q()}`, { job: job.id }); } catch (err) { toast(err.message, false); btn.disabled = false; job.reviewing = false; }
  };
  showRunbar(); listen(job);
}
function listen(job) {
  const es = new EventSource(`/api/events?job=${job.id}&from=${job.events.length}`);
  es.onmessage = (m) => {
    const e = JSON.parse(m.data);
    job.tries = 0;
    if (e.i < job.events.length) return;
    job.events.push(e);
    if (job.key === scopeKey() && job.view && job.view.root.isConnected) job.view.add(e);
    if (e.kind === "tool" && e.edit) markEditing(e.detail);
    if (e.kind === "changes") onChanges(e);
    if (e.kind === "done") {
      job.done = true; es.close(); clearInterval(job.poll); job.wait?.remove(); job.wait = null; showRunbar(); S.fenceKey = null; pollFence();
      const r = job.events.find((x) => x.kind === "result");
      toast(r && r.ok ? "Review ready in the side bar." : "Stopped.", !!(r && r.ok));
    }
  };
  es.onerror = () => { es.close(); job.tries = (job.tries || 0) + 1; if (!job.done && job.tries < 30) setTimeout(() => listen(job), Math.min(10000, 800 * job.tries)); };
}
let runTimer = 0;
function showRunbar() { // while your agent works: one line at the top; a click shows the fence and its Review button
  const bar = $("#runbar"), job = S.job, on = !!(job && !job.done);
  bar.hidden = !on;
  document.body.classList.toggle("running", on);
  clearInterval(runTimer);
  if (!on) return;
  bar.onclick = () => { if (!document.body.classList.contains("panel-open")) openFence(job.scope, job.label, ""); };
  const draw = () => { // nothing runs here: modfence only holds the fence until your agent edits inside it
    const n = job.changed || 0, open = document.body.classList.contains("panel-open");
    bar.innerHTML = `<span class="dot" aria-hidden="true"></span><span>Fence on <b>${esc(job.label || "")}</b> · ${n ? `your agent changed ${plural(n, "file")}` : "no agent edit yet"}${open ? "" : " · click to review"}</span>`;
  };
  draw();
  runTimer = setInterval(draw, 1000);
}
/* The task's fence (jit.py, golden rule 4): set when you give your agent a task in Claude Code. The bar says which
   module, for which task, because of which functions, and what else it could have been; a click switches. A file the
   agent was blocked from is a request: allow its module, or refuse. */
async function pollIntents() { // the header link says when your agent waits for you on the Intents page
  if (document.hidden) return;
  let r;
  try { r = await api(`/api/mod?${q()}`); } catch { return; }
  const n = r.intents.filter((i) => i.status === "waiting").length, a = $("#intents");
  a.href = `/mod.html#p=${S.p}`;
  a.classList.toggle("waiting", n > 0);
  a.textContent = n ? `Your agent waits (${n})` : "Intents";
}
async function pollFence() {
  if (document.hidden || !S.full) return;
  let r;
  try { r = await api(`/api/fence?${q()}`); } catch { return; }
  const key = JSON.stringify(r);
  if (key === S.fenceKey) return;
  S.fenceKey = key; S.fence = r; showFence();
}
function showFence() {
  if (S.job && !S.job.done) return; // a hand-off from an older page holds the bar until it is reviewed
  const bar = $("#runbar"), f = S.fence?.fence;
  S.fenceOn = !!f; S.fenceSet = new Set(f ? filesOf(f.files) : []); paintSelection();
  bar.hidden = !f; bar.classList.toggle("still", !!f); document.body.classList.toggle("running", !!f);
  if (!f) return;
  const names = (c) => [...new Set(c.where.map((w) => w[2]))].slice(0, 3).join(", ");
  const cands = f.candidates || [], held = (c) => f.files.includes("@module:" + c.module);
  const why = cands.filter(held).map(names).join("; "), others = cands.filter((c) => !held(c));
  bar.onclick = null;
  bar.innerHTML = `<span class="dot" aria-hidden="true"></span><span>Fence <b>${esc(f.label || f.files.join(", "))}</b>${f.task ? ` for “${esc(clip(f.task, 70))}”` : ""}${why ? ` · because ${esc(why)}` : ""}</span>`
    + (others.length ? `<span class="others">other:${others.map((c) => ` <button type="button" class="lk" data-to="${esc(c.module)}" title="Fence this task to ${esc(c.module)} instead (${esc(names(c))})">${esc(c.module)}</button>`).join("")}</span>` : "")
    + (S.fence.asks || []).map((a, i) => `<span class="ask">asks to edit <span class="mono">${esc(a)}</span> <button type="button" class="btn primary" data-allow="${i}">Allow ${S.fence.owners[a] ? "module " + esc(S.fence.owners[a]) : "this file"}</button><button type="button" class="btn quiet" data-refuse="${i}">Refuse</button></span>`).join("");
  const set = async (body, ok) => { try { await api(`/api/fence/set?${q()}`, body); toast(ok); S.fenceKey = null; pollFence(); } catch (e) { toast(e.message, false); } };
  bar.querySelectorAll("[data-to]").forEach((b) => (b.onclick = () => set({ scope: ["@module:" + b.dataset.to] }, `This task is now fenced to ${b.dataset.to}. Tell your agent if it already started.`)));
  bar.querySelectorAll("[data-allow]").forEach((b) => (b.onclick = () => { const a = S.fence.asks[+b.dataset.allow], o = S.fence.owners[a];
    set({ scope: [...new Set([...f.files, o ? "@module:" + o : a])] }, "Allowed. Tell your agent: approved, continue."); }));
  bar.querySelectorAll("[data-refuse]").forEach((b) => (b.onclick = () => set({ refuse: [S.fence.asks[+b.dataset.refuse]] }, "Refused. The fence stays as it was.")));
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
function wireSearch() {
  const input = $("#find"), list = $("#findlist");
  let hits = [], at = 0;
  const close = () => { list.hidden = true; input.setAttribute("aria-expanded", "false"); };
  const draw = () => {
    const t = input.value.trim().toLowerCase();
    if (!S.graph) return; // a big project's first scan is still running
    hits = S.graph.modules.filter((m) => !t || boxName(m).toLowerCase().includes(t) || (m.doc || "").toLowerCase().includes(t)).slice(0, 12); // the boxes on screen
    at = Math.min(at, Math.max(0, hits.length - 1));
    list.innerHTML = hits.map((m, i) => `<li role="option" id="fo${i}" aria-selected="${i === at}" data-id="${esc(m.id)}">${esc(boxName(m))}<span>${m.lines} ln</span></li>`).join("") || `<li aria-disabled="true">No box matches</li>`;
    list.hidden = false; input.setAttribute("aria-expanded", "true");
    input.setAttribute("aria-activedescendant", hits.length ? `fo${at}` : "");
  };
  const choose = (id) => { close(); input.value = ""; pick(id); revealNode(id); };
  input.addEventListener("input", () => { at = 0; draw(); });
  input.addEventListener("focus", draw);
  input.addEventListener("blur", () => setTimeout(close, 150));
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { at = Math.min(hits.length - 1, at + 1); draw(); e.preventDefault(); }
    else if (e.key === "ArrowUp") { at = Math.max(0, at - 1); draw(); e.preventDefault(); }
    else if (e.key === "Enter" && hits[at]) { choose(hits[at].id); e.preventDefault(); }
    else if (e.key === "Escape") { close(); input.blur(); }
  });
  list.addEventListener("mousedown", (e) => { const li = e.target.closest("li[data-id]"); if (li) choose(li.dataset.id); });
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
async function switchProject(p) {
  S.p = p; $("#picker").value = p; store.set("modfence.project", p); location.hash = `p=${p}`;
  if (S.job) { clearInterval(S.job.poll); S.job = null; showRunbar(); } // found again by restoreHand when you come back
  unpick(); closePanel(); S.marks = { changed: new Set(), ripple: new Set(), stats: {} }; S.userCam = false; S.focus = ""; S.level = null; S.role = null; S.area = null; S.proposed = false; S.proposedAreas = false;
  S.fence = null; S.fenceKey = null; showFence(); pollIntents();
  await loadGraph(true);
  pollFence();
}
// No refresh button: the map reads the project again when you come back to it (after editing MODULES.md, say), and
// redraws only if something changed, so a card you just opened stays open.
async function rescan() {
  if (document.hidden || !S.full || Date.now() - (S.loadedAt || 0) < 3000) return;
  S.loadedAt = Date.now();
  try {
    const [g, r] = await Promise.all([api(`/api/graph?${q()}`), api(`/api/roles?${q()}`).catch(() => null)]);
    if (JSON.stringify(g) + JSON.stringify(r) === S.sig) return;
  } catch { return; }
  await loadGraph(false);
}
function wire() {
  wireCanvas(); wireSearch(); wireResize();
  $("#panel").inert = true;
  $("#picker").onchange = (e) => {
    if (e.target.value !== "add") return switchProject(Number(e.target.value));
    e.target.value = S.p; e.target.hidden = true; // another folder on the same port: typed here, not in a prompt dialog
    const i = $("#addpath"); i.hidden = false; i.value = ""; i.focus();
  };
  const addpath = $("#addpath"), done = () => { addpath.hidden = true; $("#picker").hidden = false; };
  addpath.addEventListener("keydown", async (e) => {
    if (e.key === "Escape") return done();
    if (e.key !== "Enter" || !addpath.value.trim()) return;
    try {
      const { i } = await api(`/api/projects/add`, { path: addpath.value.trim() });
      S.projects = (await api("/api/projects")).projects; fillPicker(); done(); await switchProject(i);
    } catch (err) { toast(err.message, false); }
  });
  addpath.addEventListener("blur", () => setTimeout(done, 200));
  $("#close").onclick = closePanel;
  addEventListener("focus", rescan);
  document.addEventListener("visibilitychange", rescan);
  addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (S.picked) unpick();
      else if (S.selected && !typing()) closePanel();
      return;
    }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") { e.preventDefault(); $("#find").focus(); $("#find").select(); return; }
    if (typing() || e.ctrlKey || e.metaKey || e.altKey) return;
    if (e.key === "/") { e.preventDefault(); $("#find").focus(); }
  });
}

wire();
boot().catch((e) => toast(`Could not load: ${e.message}`, false, 10000));
