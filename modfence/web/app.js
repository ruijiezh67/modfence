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
  if (!S.level) S.level = S.roles && S.roles.roles.length ? "roles" : "modules";
  regroup();
  if (S.roles && S.roles.status === "none" && S.full.modules.length > ROLE_AT && S.claude && !S.proposed) { S.proposed = true; proposeRoles(); }
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
const shown = (id) => (id === "." ? "(root)" : id);
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
const callCache = new Map(); // call graphs fetched for the card; dropped whenever the view is rebuilt, so never stale
function regroup() {
  callCache.clear();
  if (!(S.roles && S.roles.roles.length) && (S.level === "roles" || S.level === "parts")) S.level = "modules";
  if (S.level === "funcs" && !S.calls) S.level = "parts";
  S.hiddenLinks = 0; S.outside = 0;
  if (S.picked) unpick();
  S.graph = S.level === "roles" ? roleGraph() : S.level === "parts" ? partGraph(S.role) : S.level === "funcs" ? funcGraph() : viewGraph(S.full, S.focus);
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
function prune(edges) {
  const by = new Map();
  edges.forEach((e) => { if (!by.has(e.source)) by.set(e.source, []); by.get(e.source).push(e); });
  const kept = [...by.values()].flatMap((l) => l.sort((a, b) => b.receipts.length - a.receipts.length).slice(0, KEEP_LINKS));
  S.hiddenLinks = edges.length - kept.length;
  return kept;
}
function roleNode(r, kind = "group") {
  const lines = r.files.reduce((a, f) => a + (S.full.files[f]?.lines || 0), 0);
  return { id: "role:" + r.id, role: r.id, kind: r.name === "shared" ? "tests" : kind, label: r.name, meta: plural(r.files.length, "file"),
    files: r.files, lines, names: [], doc: r.purpose || "", members: [...new Set(r.files.map((f) => S.full.files[f].module))] };
}
function roleGraph() {
  const fr = fileRoles(), rs = [...S.roles.roles];
  if (S.roles.unassigned.length) rs.push({ id: "?", name: "not placed yet", purpose: "New files: place them in a role.", files: S.roles.unassigned });
  return { ...S.full, modules: rs.filter((r) => r.files.length).map((r) => roleNode(r)), edges: prune(aggregate((f) => fr[f] && "role:" + fr[f])) };
}
function partGraph(rid) {
  const fr = fileRoles(), mine = new Set(Object.keys(fr).filter((f) => fr[f] === rid));
  // Only the role's own parts are drawn. A part is a folder of its files, or a single file when the role lives in
  // three folders or fewer (a folder would then be most of the role).
  const dir = (f) => (f.includes("/") ? f.slice(0, f.lastIndexOf("/")) : ".");
  const byFile = new Set([...mine].map(dir)).size <= 3;
  const key = (f) => (byFile ? "part:" + f : "dir:" + dir(f));
  const parts = new Map();
  mine.forEach((f) => { const d = key(f); if (!parts.has(d)) parts.set(d, []); parts.get(d).push(f); });
  const nodes = [...parts].map(([d, fs]) => ({ id: d, kind: "module", label: byFile ? d.split("/").pop() : d.slice(4).split("/").slice(-2).join("/") + "/",
    meta: byFile ? dir(fs[0]).split("/").slice(-2).join("/") + "/" : plural(fs.length, "file"),
    files: fs.sort(), names: [], doc: fs.map((f) => S.full.files[f].doc).find(Boolean) || "", lines: fs.reduce((a, f) => a + S.full.files[f].lines, 0) }));
  const edges = prune(aggregate((f) => (mine.has(f) ? key(f) : null)));
  S.outside = aggregate((f) => (mine.has(f) ? "in" : fr[f] ? "out" : null)).reduce((a, e) => a + e.receipts.length, 0);
  return { ...S.full, modules: nodes, edges };
}
function funcGraph() {
  const c = S.calls, fr = fileRoles();
  const oneFile = new Set(c.nodes.map((n) => n.file)).size === 1;
  const nodes = c.nodes.map((n) => ({ id: n.id, kind: "fn", label: n.name + (n.kind === "class" ? "" : "()"), meta: oneFile ? `line ${n.line}` : `${clip(n.file.split("/").pop(), 14)}:${n.line}`,
    files: [n.file], lines: n.lines, names: [], doc: n.doc }));
  const edges = c.edges.map((e) => ({ source: e.source, target: e.target, receipts: Array.from({ length: Math.min(e.count, 8) }, () => ({ file: e.source.split("::")[0], line: 0, code: e.kind, name: e.target.split("::")[1] })) }));
  // in a big part, functions that call nothing here and nobody here calls are listed by count only; a small part shows all
  const linked = new Set(c.edges.flatMap((e) => [e.source, e.target]));
  if (linked.size && nodes.length > 20) { S.lonely = nodes.length - nodes.filter((n) => linked.has(n.id)).length; nodes.splice(0, nodes.length, ...nodes.filter((n) => linked.has(n.id))); } else S.lonely = 0;
  S.outside = c.boundary.reduce((a, b) => a + b.count, 0); // calls leaving this part: counted, not drawn
  return { ...S.full, modules: nodes, edges };
}
function pick(id) { // a click only selects; the card below says what it is and opens it on purpose
  S.picked = id;
  const m = mod(id), card = $("#pick"), role = id.startsWith("role:"), folder = !!m.group, plain = S.level === "modules";
  const name = m.label || shown(id);
  card.innerHTML = `<div class="pk"><b>${esc(name)}</b><span class="mono">${plural(m.files.length, "file")} · ${m.lines.toLocaleString()} ln</span>`
    + `<button type="button" class="btn quiet" data-x aria-label="Close">${X_ICON}</button></div>`
    + (m.doc && !folder ? `<p title="${esc(m.doc)}">${esc(m.doc)}</p>` : "")
    + `<div class="pa"><button type="button" class="btn primary" data-open>${role ? "Open parts" : folder ? "Open folder" : "Open functions"} ▸</button>`
    + (plain && !folder ? `<button type="button" class="btn" data-ask>Ask / edit</button>` : "")
    + (role && id !== "role:?" ? `<button type="button" class="btn" data-fence>Fence role</button>` : "") + `</div>`;
  card.hidden = false;
  $("[data-open]", card).onclick = () => { unpick(); role ? openRole(id.slice(5)) : folder ? select(id) : openFuncs(m.files, name, !plain); };
  $("[data-ask]", card)?.addEventListener("click", () => { unpick(); select(id); });
  if (!role && !folder) callsOf(m.files).then((c) => { // nothing to draw: say so on the button instead of opening an empty level
    const b = S.picked === id && $("[data-open]", card);
    if (b && c && !c.nodes.length) { b.disabled = true; b.textContent = "No functions here"; $("[data-ask]", card)?.focus(); }
  });
  $("[data-fence]", card)?.addEventListener("click", () => { unpick(); fenceRole(id.slice(5)); });
  $("[data-x]", card).onclick = unpick;
  $("[data-open]", card).focus();
  paintSelection();
}
function unpick() { S.picked = null; $("#pick").hidden = true; paintSelection(); }
async function callsOf(files) {
  const k = q() + "|" + files.join("|");
  if (!callCache.has(k)) callCache.set(k, api(`/api/calls?${q()}`, { files }).catch((e) => { callCache.delete(k); throw e; }));
  return callCache.get(k);
}
async function openFuncs(files, title, inRole) {
  let c;
  try { c = await callsOf(files); } catch (e) { toast(e.message, false); return; }
  if (!c.nodes.length) { toast(`${title} has no functions or classes.`); return; }
  if (!inRole) S.role = null; // opened from the module graph: the way back is the project
  S.level = "funcs"; S.callTitle = title; S.calls = c;
  regroup(); fitView();
}
function openRole(rid) {
  if (rid === "?" || !S.roles) { S.level = "parts"; S.role = rid; regroup(); fitView(); return; }
  const r = S.roles.roles.find((x) => x.id === rid);
  S.role = rid;
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
  if (await rolesDo("propose", {}, null)) { S.level = "roles"; regroup(); fitView(); toast(`Roles proposed (${S.roles.how}${S.roles.cost_usd != null ? `, $${S.roles.cost_usd.toFixed(3)}` : ""}). Rename, move files, then confirm.`); }
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
function fenceRole(rid) {
  const r = S.roles.roles.find((x) => x.id === rid);
  const first = S.full.files[r.files[0]].module;
  select(first);
  S.scope = new Set(r.files); S.fenceRole = rid;
  afterFenceChange();
  toast(`The agent may edit the ${plural(r.files.length, "file")} of ${r.name}.`);
}
function renderCrumbs() {
  const c = $("#crumbs"), big = S.full.modules.length > GROUP_AT, has = S.roles && S.roles.roles.length;
  const step = (n, text, attrs, cur) => `<button type="button" ${attrs}${cur ? ' aria-current="true"' : ""}><b>${n}</b> ${esc(text)}</button>`;
  let h = "";
  if (S.level === "funcs" && !S.role) {
    h = `<button type="button" data-lv="modules">${esc(S.full.name)}</button><span>/</span>` + step(3, S.callTitle, "", true)
      + `<em>${S.calls.resolved}/${S.calls.calls} calls traced${S.outside ? ` · ${S.outside} leave` : ""}</em>`;
  } else if (S.level === "modules") {
    if (!big && !has && S.full.modules.length <= ROLE_AT) { c.hidden = true; return; }
    const parts = S.focus ? S.focus.split("/") : [];
    h = (has ? step(1, "Roles", 'data-lv="roles"') + `<span>/</span>` : "") + `<button type="button" data-f="" aria-current="${!S.focus}">${esc(S.full.name)}</button>`
      + parts.map((p, i) => `<span>/</span><button type="button" data-f="${esc(parts.slice(0, i + 1).join("/"))}">${esc(p)}</button>`).join("")
      + (big ? `<em>${plural(S.full.modules.length, "module")}, grouped by folder</em>` : "")
      + (!has && S.claude ? `<button type="button" class="act" data-propose>Group into roles</button>` : "");
  } else {
    const r = S.roles.roles.find((x) => x.id === S.role);
    h = step(1, "Roles", 'data-lv="roles"', S.level === "roles");
    if (S.level !== "roles") h += `<span>/</span>` + step(2, S.role === "?" ? "not placed yet" : rname(S.role), `data-role="${esc(S.role)}"`, S.level === "parts");
    if (S.level === "funcs") h += `<span>/</span>` + step(3, S.callTitle, "", true);
    if (S.level !== "funcs" && S.hiddenLinks) h += `<em title="Strongest ${KEEP_LINKS} links per box">${S.hiddenLinks} weak links hidden</em>`;
    if (S.level === "roles") h += `<em title="${esc(S.roles.how || "")}">${S.roles.status === "confirmed" ? "Confirmed" : "Proposed"}</em>`
      + (S.roles.status !== "confirmed" ? `<button type="button" class="act" data-confirm>Confirm roles</button>` : "") + `<button type="button" class="act q" data-propose>Propose again</button><button type="button" class="act q" data-lv="modules">All modules</button>`;
    if (S.level === "parts" && r && S.outside) h += `<em title="${esc(r.purpose || "")}">${S.outside} imports to other roles</em>`;
    if (r && S.level !== "roles") h += `<button type="button" class="act q" data-rename>Rename</button><button type="button" class="act q" data-files>Files</button><button type="button" class="act" data-fence>Fence this role</button>`;
    if (S.role === "?" && S.level !== "roles") h += `<button type="button" class="act" data-files>Place files</button>`;
    if (S.level === "funcs") h += `<em title="Static and approximate. Click a function to mention it; shift-click to fence it alone.">${S.calls.resolved}/${S.calls.calls} calls traced${S.outside ? ` · ${S.outside} leave` : ""}</em>`;
  }
  c.hidden = false;
  c.innerHTML = h;
  c.querySelectorAll("[data-f]").forEach((b) => (b.onclick = () => { S.focus = b.dataset.f; regroup(); fitView(); }));
  c.querySelectorAll("[data-lv]").forEach((b) => (b.onclick = () => { S.level = b.dataset.lv; regroup(); fitView(); }));
  c.querySelectorAll("[data-role]").forEach((b) => (b.onclick = () => openRole(b.dataset.role)));
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
const inSet = (set, id) => set.has(id) || !!(mod(id)?.members && mod(id).members.some((x) => set.has(x)));

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
  const WRAP = 10; // ponytail: a wide rank wraps onto extra rows, so a 40-function rank stays on screen
  rows = rows.flatMap((row) => Array.from({ length: Math.ceil(row.length / WRAP) }, (_, i) => row.slice(i * WRAP, (i + 1) * WRAP)));
  S.rows = rows.map((row) => row.slice());
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
    const dy = Math.max(32, (ty - sy) * 0.5);
    return `M${sx},${sy} C${sx},${sy + dy} ${tx},${ty - dy} ${tx},${ty}`;
  }
  const sx = a.x + NODE_W, sy = a.y + NODE_H / 2, tx = b.x + NODE_W + 3, ty = b.y + NODE_H / 2; // a cycle: around the right
  const bulge = 60 + Math.abs(ty - sy) * 0.2;
  return `M${sx},${sy} C${sx + bulge},${sy} ${tx + bulge},${ty} ${tx},${ty}`;
}

function drawGraph() {
  const g = S.graph, eg = $("#edges"), ng = $("#nodes"), mx = maxLines();
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
    const d = (e._d = edgePath(e, spread.get(e)));
    e._base = mod(e.source).kind === "tests" ? "edge from-tests" : "edge";
    e._el = el("path", { d, class: e._base, "marker-end": "url(#ah)", "stroke-width": 1.3 + Math.min(2, Math.log2(e.receipts.length)) }, eg);
    const hit = el("path", { d, class: "edge-hit" }, eg);
    hit.addEventListener("pointerdown", (ev) => ev.stopPropagation());
    hit.addEventListener("pointerenter", (ev) => showEdgeTip(ev, e));
    hit.addEventListener("pointermove", moveTip);
    hit.addEventListener("pointerleave", hideTip);
    hit.addEventListener("click", () => S.level !== "funcs" && pick(e.target));
  });
  g.modules.forEach((m) => {
    const { x, y } = S.pos[m.id];
    const n = el("g", { class: `node${m.kind === "tests" ? " tests" : ""}`, transform: `translate(${x},${y})`, tabindex: 0, role: "button", "data-id": m.id }, ng);
    el("rect", { class: "ring", x: -3, y: -3, width: NODE_W + 6, height: NODE_H + 6, rx: 10 }, n);
    if (m.group) { n.classList.add("group"); el("rect", { class: "stack", x: 5, y: 5, width: NODE_W, height: NODE_H, rx: 7 }, n); }
    el("rect", { class: "card", width: NODE_W, height: NODE_H, rx: 7 }, n);
    el("rect", { class: "fill", width: NODE_W, height: NODE_H, rx: 7 }, n);
    const name = el("text", { class: "name", x: 12, y: 25 }, n);
    name.textContent = clip(m.label || label(m.id), 22);
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
function diffTag(id) { const st = S.marks.stats[id]; return st ? `+${st.plus} −${st.minus}` : ""; }

function paintSelection(hover) {
  const focus = hover || S.selected;
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
    const k = !focus ? "" : e.source === focus ? "dep" : e.target === focus ? "use" : "faded";
    e._el.setAttribute("class", `${e._base} ${k}`);
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
function viewport() { const c = $("#canvas").getBoundingClientRect(); return { w: c.width || innerWidth, h: c.height || innerHeight, bottom: 52 }; }
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
function showEdgeTip(ev, e) {
  const t = $("#tip"), names = takes(e);
  t.innerHTML = `<div class="h">${esc(shown(e.source))} uses ${esc(shown(e.target))}</div>`
    + (names.length ? `<div class="tn">${names.slice(0, 12).map((n) => `<b class="mono">${esc(n)}</b>`).join(" ")}${names.length > 12 ? ` +${names.length - 12}` : ""}</div>` : `<div class="tn">the whole module</div>`)
    + (S.level !== "funcs" ? `<div class="tk">Click: ${esc(shown(e.target))}</div>` : "");
  t.classList.add("show"); moveTip(ev);
}
function moveTip(ev) { const t = $("#tip"); t.style.left = Math.min(ev.clientX + 14, innerWidth - t.offsetWidth - 10) + "px"; t.style.top = Math.min(ev.clientY + 16, innerHeight - t.offsetHeight - 10) + "px"; }
function hideTip() { $("#tip").classList.remove("show"); }

/* ---------------- selection, fence & panel ---------------- */
function onNodeClick(id, ev) {
  if (id.startsWith("role:") || id.startsWith("dir:") || id.startsWith("part:")) { pick(id); return; }
  if (S.level === "funcs") { // mention the function in the instruction; shift-click fences it alone (file kept, others flagged)
    const [file, name] = id.split("::"), m = S.full.files[file].module;
    if (ev.shiftKey || ev.metaKey || ev.ctrlKey) { if (S.selected !== m) select(m); S.scope = new Set([id]); afterFenceChange(); toast(`Fenced ${name}(): its file may change, other functions in it are flagged.`); return; }
    if (S.selected !== m) select(m);
    insertRef(`\`${name}()\` in ${file}`);
    return;
  }
  // a click only picks (the card opens it on purpose); shift-click with a module open grows the fence
  if (!((ev.shiftKey || ev.metaKey || ev.ctrlKey) && S.selected) || mod(id)?.group) { pick(id); return; }
  if (S.scope.has(id) && S.scope.size > 1) S.scope.delete(id); else S.scope.add(id);
  if (!S.scope.has(S.selected)) S.selected = [...S.scope][0];
  afterFenceChange();
}
function select(id) {
  if (id.endsWith("/")) { S.focus = id.slice(0, -1); regroup(); fitView(); return; } // a grouped folder: open it
  S.fenceRole = null;
  if (S.level === "roles" || (S.level === "parts" && !S.graph.modules.some((m) => m.id === id))) { // show the module among its role's parts
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
  document.body.classList.remove("panel-open");
  $("#panel").inert = true;
  if (wasOpen) requestAnimationFrame(() => S.view === "graph" && !S.userCam && fitView());
  paintSelection();
}
function afterFenceChange() { renderFence(); renderHeader(); paintSelection(); loadTalk(); }
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
  if (!S.fn[id]) { try { S.fn[id] = await api(`/api/module?${q("&m=" + encodeURIComponent(id))}`); } catch { return null; } }
  const v = S.fn[id];
  if (describe && S.claude && !describing.has(id) && (v.undescribed || !v.purpose)) {
    describing.add(id); paintFns(id);
    try {
      const r = await api(`/api/describe?${q()}`, { module: id });
      S.fn[id] = r;
      if (r.purpose_source === "ai") { (S.full.ai_purposes ||= {})[id] = r.purpose; }
      if (r.error) toast(`Could not describe the functions: ${r.error}`, false);
    } catch (e) { toast(`Could not describe the functions: ${e.message}`, false); }
    describing.delete(id);
  }
  return S.fn[id];
}
const AI_TAG = '<i class="ai" title="Written by a small model from the code; the author wrote no docstring">AI</i>';
function fnRows(v) {
  const byFile = {};
  v.functions.forEach((f) => (byFile[f.file] ||= []).push(f));
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
  box.innerHTML = fnRows(v);
  box.querySelectorAll("[data-ref]").forEach((b) => (b.onclick = () => insertRef(b.dataset.ref)));
  const u = v.functions.filter((f) => !f.purpose).length;
  $("#fncount").textContent = `${plural(v.functions.length, "unit")}${u && !describing.has(id) ? `, ${u} undescribed` : ""}`;
  if (v.purpose && !mod(id).doc) $("#mdoc").innerHTML = esc(v.purpose) + " " + AI_TAG;
}
function insertRef(text) {
  const ta = $("#prompt"), s = ta.selectionStart ?? ta.value.length;
  const pad = s && !/\s$/.test(ta.value.slice(0, s)) ? " " : "";
  ta.setRangeText(pad + text + " ", s, ta.selectionEnd ?? s, "end");
  ta.focus(); autosize();
}

function renderOverview() {
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
    const chips = S.fenceRole && S.scope.size > 3 ? `<span class="fchip">role ${esc(rname(S.fenceRole))} (${plural(S.scope.size, "file")})</span>`
      : [...S.scope].map((id) => `<span class="fchip">${esc(chipName(id))}${S.scope.size > 1 ? `<button type="button" data-rm="${esc(id)}" aria-label="Remove ${esc(shown(id))} from the fence">${X_ICON}</button>` : ""}</span>`).join("");
    const add = testsMod && !S.scope.has(testsMod.id) ? `<button type="button" class="fadd" data-add="${esc(testsMod.id)}">+ ${esc(testsMod.id)}</button>` : "";
    line = `<div class="fline"><span class="lab">Can edit:</span>${chips}${add}</div>`;
  }
  const nocli = S.claude ? "" : `<div class="nocli">Claude Code CLI not found. Install it and log in, or start modfence with CLAUDE_BIN set to its path, then restart. Reading the project still works.</div>`;
  $("#fence").innerHTML = nocli + mode + line;
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
      } else if (e.kind === "done") {
        if (textEl) { renderText(); textEl = null; }
        body.querySelectorAll(".step .st").forEach((x) => { if (x.textContent === "…") x.textContent = "stopped"; });
        const r = view.result, quiet = phase === "plan" && !(view.changes && view.changes.files && view.changes.files.length);
        st.className = `st ${r && r.ok ? (view.check && !view.check.ok ? "bad" : "ok") : "bad"}`;
        st.textContent = r ? (r.ok ? `${phase === "plan" ? "Planned" : view.check && !view.check.ok ? "Done, check failed" : "Done"}${r.duration_s ? ` · ${r.duration_s}s` : ""}` : "Stopped with an error") : "Stopped";
        if (quiet) { const f = document.createElement("div"); f.className = "rfoot"; f.innerHTML = r ? `<span class="meta">${r.turns ? plural(r.turns, "turn") : ""}${r.cost_usd != null ? ` · $${r.cost_usd.toFixed(3)}` : ""}</span>` : ""; root.appendChild(f); }
        else renderChanges(root, view.changes, r, view.check, !replay);
      }
      if (!replay) scrollTalk();
    },
    flush() { if (textEl) renderText(); },
  };
  scrollTalk();
  return view;
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
  box.innerHTML = (outside.length ? `<div class="banner bad">${plural(outside.length, "file")} changed outside the fence: <span class="mono">${esc(outside.map((f) => f.path).join(", "))}</span>${rev ? `<button class="btn" type="button" data-rev-out>Revert those</button>` : ""}</div>` : "")
    + (files.length ? files.map((f, i) => `<div class="cfile${f.outside ? " out" : ""}">
        <div class="cfh"><span class="mono p" title="${esc(f.path)}">${esc(f.path)}</span>${f.outside ? '<span class="tagout">outside fence</span>' : ""}${f.status !== "modified" ? `<span class="st">${f.status}</span>` : ""}
          <span class="s mono">${f.plus == null ? "N/A" : `<span class="plus">+${f.plus}</span> <span class="minus">−${f.minus}</span>`}</span>
          ${c.run ? `<button class="btn quiet" type="button" data-diff="${i}" aria-expanded="false" title="Show the line diff">Source</button>` : ""}</div>
        ${units(f)}</div>`).join("")
      : `<p class="none" style="padding:8px 10px">No files changed.</p>`);
  const foot = document.createElement("div");
  foot.className = "rfoot";
  foot.innerHTML = (check ? `<div class="chk ${check.ok ? "ok" : "bad"}">${check.ok ? "Done check passed" : "Done check failed"}: ${esc(check.summary || "project tests")}${check.blocked ? `. The agent was sent back ${plural(check.blocked, "time")}.` : "."}</div>` : "")
    + (c && c.ripple.length ? `<div class="ripple">Uses the changed code: ${c.ripple.map((m) => `<button type="button" data-go="${esc(m)}">${esc(shown(m))}</button>`).join("")} run the tests to check them.</div>` : "")
    + (files.length ? `<button class="btn" type="button" data-tests>Run tests</button>` : "")
    + (rev ? `<button class="btn" type="button" data-rev>Revert this run</button>` : "")
    + (r ? `<span class="meta">${r.turns ? plural(r.turns, "turn") : ""}${r.cost_usd != null ? ` · $${r.cost_usd.toFixed(3)}` : ""}</span>` : "");
  root.appendChild(box);
  root.appendChild(foot);
  box.querySelectorAll("[data-diff]").forEach((b) => (b.onclick = () => toggleDiff(b, c.run, files[+b.dataset.diff].path)));
  foot.querySelectorAll("[data-go]").forEach((b) => (b.onclick = () => select(b.dataset.go)));
  $("[data-tests]", foot)?.addEventListener("click", runTests);
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
function syncSend() {
  const running = S.job && !S.job.done;
  const b = $("#send");
  b.classList.toggle("stop", !!running);
  b.textContent = running ? "Stop" : S.readOnly ? "Explain" : "Plan";
  b.disabled = !running && (!$("#prompt").value.trim() || !S.claude);
}

// Fence coding: an edit starts as a read-only plan you answer and approve; Build then edits inside the fence.
async function send() {
  if (S.job && !S.job.done) { await api("/api/cancel", { job: S.job.id }).catch(() => {}); return; }
  const prompt = $("#prompt").value.trim();
  if (!prompt || !S.scope.size || !S.claude) return;
  if (await startRun(prompt, [...S.scope], S.readOnly, S.readOnly ? null : "plan")) { $("#prompt").value = ""; autosize(); }
}
async function startRun(prompt, scope, readOnly, phase) {
  let res;
  try { res = await api(`/api/ask?${q()}`, { prompt, scope, read_only: readOnly, phase }); }
  catch (e) { toast(e.message, false); return false; }
  if (phase !== "plan") { S.marks = { changed: new Set(), ripple: new Set(), stats: {} }; paintSelection(); }
  const key = [...scope].sort().join("+");
  if (key !== scopeKey()) { S.scope = new Set(scope); afterFenceChange(); }
  const job = { id: res.job, prompt, scope, readOnly, phase, key, events: [], done: false, at: Date.now() / 1000 };
  S.job = job;
  setTab("talk");
  job.view = newRun(prompt, scope, job.at, readOnly, phase);
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
  paintSelection();
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
    closePanel(); S.marks = { changed: new Set(), ripple: new Set(), stats: {} }; S.userCam = false; S.focus = ""; S.level = null; S.role = null; S.calls = null; S.proposed = false;
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
