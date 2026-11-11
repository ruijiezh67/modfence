/* The .mod page: what the agent understood from your words, judged in seconds. No reading is preselected or marked as
   recommended, and their order is shuffled (per intent, so it does not move while you look). Keys: 1-3 pick a reading,
   Enter continues. */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const S = { p: 0, data: null, cur: null, pick: null, own: "", edits: {}, rx: {}, seen: new Set() };
const SRC = { guess: ["?", "guess"], memory: ["◷", "memory"], user: ["●", "you said"], default: ["○", "default"] };
const ORDER = { guess: 0, memory: 1, user: 2, default: 3 };

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json", "X-Modfence": "1" }, body: JSON.stringify(body) });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}
const q = () => `p=${S.p}`;
let toastT = 0;
function toast(t) { const el = $("#toast"); el.textContent = t; el.classList.add("show"); clearTimeout(toastT); toastT = setTimeout(() => el.classList.remove("show"), 2600); }

function shuffled(n, seed) { // a fixed order per intent id, so nothing jumps between redraws
  const idx = [...Array(n).keys()];
  let h = 0; for (const c of seed) h = (h * 31 + c.charCodeAt(0)) >>> 0;
  for (let i = n - 1; i > 0; i--) { h = (h * 1103515245 + 12345) >>> 0; const j = h % (i + 1); [idx[i], idx[j]] = [idx[j], idx[i]]; }
  return idx;
}
const short = (d) => (d ? String(d).slice(5) : ""); // 2026-11-10 -> 11-10
const left = (i) => i.status !== "waiting" ? null : !i.waiting_at ? Infinity // seconds the agent still waits; <= 0: it stopped
  : Math.round((i.wait_s ?? 110) - (Date.now() - Date.parse(i.waiting_at)) / 1000);
function stateText(i) {
  if (i.status === "answered") return "Answered";
  const s = left(i);
  if (s === null) return "Open";
  if (s <= 0) return "<b>Your agent stopped waiting.</b> Answer here, then tell it to continue in the chat.";
  return `<b>Your agent is waiting for you</b>${s === Infinity ? "" : ` · ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")} left`}`;
}
setInterval(() => { const i = S.data?.intents.find((x) => x.id === S.cur), el = $("#state"); if (i && el) el.innerHTML = stateText(i); }, 1000);

async function load(first) {
  try { S.data = await api(`/api/mod?${q()}`); } catch (e) { $("#main").innerHTML = `<p class="empty">${esc(e.message)}</p>`; return; }
  try { S.fence = await api(`/api/fence?${q()}`); } catch { S.fence = null; } // what the agent may edit, shown beside where it stopped
  const waiting = S.data.intents.find((i) => left(i) > 0 && !S.seen.has(i.id));
  if (waiting) { S.seen.add(waiting.id); select(waiting.id); document.title = "● modfence: your agent is waiting"; return; }
  if (first) return select(S.data.intents[0]?.id || "project");
  const cur = S.data.intents.find((i) => i.id === S.cur);
  if (cur && cur.status === "answered" && S.drawn === "open") return select(S.cur); // answered elsewhere (the agent, another tab)
  drawList();
}
function drawList() {
  const list = $("#list"), it = S.data.intents;
  const html = it.map((i) => `<li><button type="button" class="item${left(i) > 0 ? " waiting" : ""}" data-id="${esc(i.id)}"${S.cur === i.id ? ' aria-current="true"' : ""}>`
    + `<b>${esc(i.words)}</b><span>${esc(left(i) > 0 ? "your agent is waiting" : left(i) !== null ? "your agent stopped waiting" : i.status === "answered" ? "answered" : "open")} · ${esc(i.id)}</span></button></li>`).join("")
    || `<li class="empty">No intents yet. When you give your agent a task it cannot do without guessing, it writes one here.</li>`;
  if (list.innerHTML !== html) list.innerHTML = html; // unchanged: keep focus on the list (a 2 s poll calls this)
  list.querySelectorAll("[data-id]").forEach((b) => (b.onclick = () => select(b.dataset.id)));
  $("#proj").setAttribute("aria-current", String(S.cur === "project"));
}
function select(id) {
  if (S.cur !== id) { S.pick = null; S.own = ""; S.edits = {}; S.rx = {}; S.openedAt = Date.now(); }
  S.cur = id; drawList();
  if (id === "project") return drawProject();
  const i = S.data.intents.find((x) => x.id === id);
  if (i) drawIntent(i);
}

/* ---------- one intent, one column ----------
   Your words and the values you never said; the readings, as Lam's just-in-time objectives (select one, edit its name,
   description or a value, delete it, or say it in your own words); then where the agent stopped. Nothing is preselected
   or recommended, and the order is shuffled per intent. (A three-column graph with wires and per-reading weights was
   dropped after a design review, 2026-11-11: the wires told nothing and the weights read as scores.) */
const SRCWORD = { guess: "guessed", memory: "remembered", user: "you said", default: "default" };
const rx = (ci) => (S.rx[ci] ||= {});
const scaleText = (sc) => `${{ one: "one run", sample: "a sample", full: "everything" }[sc.pick] || esc(sc.pick || "")} · ${sc.runs != null ? esc(sc.runs) + (+sc.runs === 1 ? " run" : " runs") : "runs N/A"} · ${esc(sc.cost || "cost N/A")} · ${esc(sc.time || "time N/A")}`;
function chip(s, editable) {
  const v = S.edits[s.key] ?? s.value, changed = S.edits[s.key] !== undefined;
  return `<span class="chip ${changed ? "user changed" : s.source}" data-key="${esc(s.key)}" title="${esc(s.key)}: ${changed ? "changed by you" : SRCWORD[s.source] || s.source}${s.source === "memory" && s.at ? " on " + esc(s.at) : ""}">`
    + `<span class="sg" aria-hidden="true">${changed ? "●" : (SRC[s.source] || ["·"])[0]}</span><span class="vh">${changed ? "changed by you" : SRCWORD[s.source] || s.source}: </span>`
    + `<span class="ck">${esc(s.key)}</span>` + (editable ? `<button type="button" class="cv">${esc(v ?? "?")}</button>` : `<span class="cv">${esc(v ?? "?")}</span>`)
    + (s.source === "memory" && !changed && s.at ? `<span class="cd">${esc(short(s.at))}</span>` : "") + `</span>`;
}
function drawIntent(i) {
  S.drawn = i.status === "answered" ? "answered" : "open";
  const settings = (i.settings || []).slice().sort((a, b) => ORDER[a.source] - ORDER[b.source]);
  let quote = esc(String(i.words || ""));
  settings.forEach((s) => {
    const f = esc(String(s.from || "").trim()), at = f ? quote.toLowerCase().indexOf(f.toLowerCase()) : -1;
    if (at >= 0) quote = quote.slice(0, at) + `<u data-key="${esc(s.key)}">${quote.slice(at, at + f.length)}</u>` + quote.slice(at + f.length);
  });
  const cands = i.candidates || [], order = shuffled(cands.length, i.id || ""), done = i.status === "answered";
  const keys = [...new Set(cands.flatMap((c) => Object.keys(c.differs || {})))].filter((k) => new Set(cands.map((c) => String((c.differs || {})[k] ?? "—"))).size > 1);
  const open = settings.filter((s) => s.source === "guess" || s.source === "memory");
  const took = settings.filter((s) => !open.includes(s) && s.from && quote.includes(`data-key="${esc(s.key)}"`)), rest = settings.filter((s) => !open.includes(s) && !took.includes(s));
  const pc = typeof S.pick === "number" ? cands[S.pick] : done && i.choice?.kind === "pick" ? cands[i.choice.index] : null;
  const multi = new Set(cands.map((c) => JSON.stringify(c.scale || null))).size > 1; // a cost line only where they differ
  const sc = pc?.scale || i.scale || {}, plan = Array.isArray(i.plan) && i.plan.length ? i.plan : ["", "this step", ""];
  const node = (ci, k) => {
    const c = cands[ci], r = rx(ci), name = r.name ?? c.name, desc = r.description ?? c.description ?? "";
    if (r.deleted) return `<div class="node reading gone" id="n-r${ci}"><s>${esc(name)}</s> <button type="button" class="link" data-undo="${ci}">undo</button></div>`;
    const on = S.pick === ci || (done && i.choice?.kind === "pick" && i.choice.index === ci); // an answered intent shows what was picked
    return `<div class="node reading${on ? " on" : ""}" id="n-r${ci}" data-ci="${ci}" role="group" aria-label="Reading ${k + 1}: ${esc(name)}">`
      + `<div class="rh"><button type="button" class="pk" data-pick="${ci}" aria-pressed="${on}" title="Pick this reading (key ${k + 1})"${done ? " disabled" : ""}>${k + 1}</button>` + (r.editing && !done
        ? `<input class="rn-in" value="${esc(name)}" aria-label="Reading name">` : `<b class="rn">${esc(name)}</b>`)
      + (done ? "" : `<span class="tools"><button type="button" data-edit="${ci}" title="Edit this reading">${r.editing ? "Done" : "Edit"}</button><button type="button" data-del="${ci}" title="Delete: this is not what I meant" aria-label="Delete">×</button></span>`) + `</div>`
      + (r.editing && !done ? `<textarea class="rd-in" rows="2" aria-label="Description">${esc(desc)}</textarea>` : desc ? `<p class="rd" title="${esc(desc)}">${esc(desc)}</p>` : "")
      + (keys.length ? `<p class="diffs">${keys.map((key) => { const ch = (r.differs || {})[key] !== undefined, v = ch ? r.differs[key] : (c.differs || {})[key] ?? "—";
        return `<span class="chip alt${ch ? " changed" : ""}" data-ci="${ci}" data-dk="${esc(key)}"><span class="ck">${esc(key)}</span>${done ? `<span class="cv">${esc(v)}</span>` : `<button type="button" class="cv" title="Change this value">${esc(v)}</button>`}</span>`; }).join(" ")}</p>` : "")
      + (c.scale && multi && ["pick", "runs", "cost", "time"].some((f) => c.scale[f] != null) ? `<p class="cost">${scaleText(c.scale)}</p>` : "") // an empty scale says nothing
      + (c.evidence ? `<p class="ev" title="${esc(c.evidence)}"><b>why</b> ${esc(c.evidence)}</p>` : "") + `</div>`;
  };
  $("#main").innerHTML = `<p class="state" id="state" role="status" title="${esc(i.id)}">${stateText(i)}</p>`
    + `<div class="graph" id="graph">`
    + `<div class="col"><p class="cap">What you said</p>`
    + `<div class="node words" id="n-words"><p class="said">“${quote}”</p>`
      + (took.length ? `<p class="took">${took.map((s) => `<span class="tw">${esc(s.from)}</span><span class="ar">→</span>${chip(s, !done)}`).join("")}</p>` : "") + `</div>`
    + (open.length ? `<div class="node assume" id="n-assume"><span class="nl">${open.length} value${open.length > 1 ? "s" : ""} you never said</span><p class="chips">${open.map((s) => chip(s, !done)).join(" ")}</p></div>` : "")
    + (rest.length ? `<details class="node more"><summary>${rest.length} ${rest.every((s) => s.source === "default") ? "default" : "more value"}${rest.length > 1 ? "s" : ""}</summary><p class="chips">${rest.map((s) => chip(s, !done)).join(" ")}</p></details>` : "")
    + `</div><div class="col"><p class="cap">${done ? "What it understood" : "Which one did you mean?"}</p>${order.map(node).join("")}`
    + (done ? "" : `<div class="node reading own${S.pick === "own" ? " on" : ""}" id="n-own"><div class="rh"><kbd>${cands.length + 1}</kbd><b class="rn">None of these</b></div><input type="text" id="own" placeholder="Say it in your own words${keys.length ? `, e.g. ${esc(keys.map((k) => k + " …").join(", "))}` : ""}" value="${esc(S.own)}"></div>`)
    + `</div><div class="col plan"><p class="cap">Where the agent is</p>${plan.map((p, k) => `<div class="node step${k === 1 ? " here" : ""}" id="n-p${k}">${k === 1 ? `<span class="nl">The agent stopped here</span>` : ""}<span class="st" title="${esc(p)}">${esc(p || (k ? "next" : "before"))}</span>`
      + (k === 1 && !multi && sc.pick ? `<span class="sc">${scaleText(sc)}</span>` : "") + `</div>`).join("")}${fenceNode()}</div>`  // a reading's own cost is on the reading
    + `</div>`
    + `<p class="legend"><span class="chip guess"><span class="sg">?</span></span> guessed <span class="chip memory"><span class="sg">◷</span><span class="cd">date</span></span> remembered <span class="chip user"><span class="sg">●</span></span> you said <span class="chip default"><span class="sg">○</span></span> default${done ? "" : " · click a value to change it"}</p>`
    + (done ? `<p class="done">You ${i.choice?.kind === "chat" ? "answered in the chat" : "chose"}: ${esc(["own", "chat"].includes(i.choice?.kind) ? i.choice.text : i.choice?.name || cands[i.choice?.index]?.name || "")}. Your agent has it.</p>`
      : `<div class="bar"><span class="what" id="what"></span><button type="button" class="go" id="go" disabled>Continue <kbd>Enter</kbd></button></div>`);
  wireIntent(i);
}
function fenceNode() { // the scope the agent works in, so an answer is read against it
  const f = S.fence?.fence, n = S.fence?.asks?.length || 0;
  if (!f) return "";
  const mods = (f.files || []).map((x) => String(x).replace(/^@module:/, "")).join(" + ");
  return `<a class="node fencen" href="/#p=${S.p}" title="Open the map"><span class="nl">It may edit</span>${esc(mods || f.label || "")}`
    + `<span class="sc">${f.by === "jit" ? "picked from your task" : "set by you"}${n ? ` · <b>${n} request${n > 1 ? "s" : ""}</b> on the map` : ""}</span></a>`;
}

function wireIntent(i) {
  const main = $("#main"), redraw = () => drawIntent(i);
  main.querySelectorAll(".reading[data-ci]").forEach((n) => {
    n.onclick = (e) => { if (e.target.closest("button:not(.pk), input, textarea")) return; choose(+n.dataset.ci); }; // the number is the pick button
  });
  main.querySelectorAll("[data-edit]").forEach((b) => (b.onclick = () => { // Lam's Edit: your wording replaces the agent's
    const ci = +b.dataset.edit, r = rx(ci), n = $(`#n-r${ci}`);
    if (r.editing) { r.name = $(".rn-in", n).value.trim() || r.name; r.description = $(".rd-in", n).value.trim(); }
    r.editing = !r.editing; if (!r.editing && S.pick === null) S.pick = ci; redraw();
  }));
  main.querySelectorAll("[data-del]").forEach((b) => (b.onclick = () => { const ci = +b.dataset.del; rx(ci).deleted = true; if (S.pick === ci) S.pick = null; redraw(); }));
  main.querySelectorAll("[data-undo]").forEach((b) => (b.onclick = () => { rx(+b.dataset.undo).deleted = false; redraw(); }));
  const own = $("#own");
  if (own) { own.onkeydown = (e) => { if (e.key === "Enter" && S.pick === "own") { e.preventDefault(); send(i); } }; own.oninput = () => { S.own = own.value; S.pick = own.value.trim() ? "own" : null; mark(i); $("#n-own").classList.toggle("on", S.pick === "own"); }; }
  main.querySelectorAll(".diffs .chip[data-dk]").forEach((c) => {
    const b = c.querySelector("button.cv");
    if (b) b.onclick = () => {
      const ci = +c.dataset.ci, key = c.dataset.dk, input = document.createElement("input");
      input.value = b.textContent; input.size = Math.max(4, b.textContent.length + 2); b.replaceWith(input); input.focus(); input.select();
      const fin = (keep) => { const r = rx(ci); if (keep && input.value !== String((cands(i)[ci].differs || {})[key] ?? "—")) { (r.differs ||= {})[key] = input.value; S.pick = ci; } redraw(); };
      input.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); fin(true); } if (e.key === "Escape") fin(false); };
      input.onblur = () => fin(true);
    };
  });
  main.querySelectorAll(".chips .chip").forEach((c) => {
    const b = c.querySelector("button.cv");
    if (b) b.onclick = () => {
      const key = c.dataset.key, input = document.createElement("input");
      input.value = b.textContent; input.size = Math.max(4, b.textContent.length + 2); b.replaceWith(input); input.focus(); input.select();
      const fin = (keep) => { if (keep && input.value !== String((i.settings.find((s) => s.key === key) || {}).value)) S.edits[key] = input.value; redraw(); };
      input.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); fin(true); } if (e.key === "Escape") fin(false); };
      input.onblur = () => fin(true);
    };
  });
  $("#go") && ($("#go").onclick = () => send(i));
  mark(i);
}
const cands = (i) => i.candidates || [];
function choose(ci) { S.pick = ci; S.own = ""; const i = S.data.intents.find((x) => x.id === S.cur); drawIntent(i); $(`#n-r${ci} .pk`)?.focus(); }
function mark(i) {
  const go = $("#go"), what = $("#what"), n = Object.keys(S.edits).length + Object.keys((typeof S.pick === "number" && S.rx[S.pick]?.differs) || {}).length;
  if (!go) return;
  go.disabled = S.pick === null;
  what.textContent = S.pick === null ? `Press 1-${(i.candidates || []).length + 1}, or click the one you meant.` : (S.pick === "own" ? `Your words: “${S.own}”` : `“${S.rx[S.pick]?.name ?? i.candidates[S.pick].name}”`) + (n ? ` · ${n} value${n > 1 ? "s" : ""} changed` : "");
}
async function send(i) {
  if (S.pick === null) return;
  const r = S.rx[S.pick] || {}, c = i.candidates[S.pick] || {}, choice = S.pick === "own" ? { kind: "own", text: S.own } : { kind: "pick", index: S.pick };
  if (S.pick !== "own" && ((r.name && r.name !== c.name) || (r.description !== undefined && r.description !== (c.description || "")))) { choice.name = r.name ?? c.name; choice.description = r.description ?? c.description; }
  if (S.pick !== "own" && r.differs && Object.keys(r.differs).length) choice.differs = r.differs;
  if (S.pick !== "own") choice.shown = shuffled(i.candidates.length, i.id || "").indexOf(S.pick) + 1; // where it stood on screen
  choice.ms = Date.now() - S.openedAt; // with "shown": do you read, or confirm the first thing you see?
  choice.deleted = Object.entries(S.rx).filter(([, v]) => v.deleted).map(([k]) => +k);
  try { await api(`/api/mod/answer?${q()}`, { id: i.id, choice, edits: S.edits }); }
  catch (e) { toast(e.message); return; }
  toast("Sent. Your agent continues."); document.title = "modfence intents";
  await load(false); select(i.id);
}

/* ---------- the project: modules and the settings you confirmed ---------- */
function habits() { // Lam: people confirm quickly unless a reading is clearly off; these numbers show if you do
  const a = S.data.intents.filter((i) => i.status === "answered" && i.choice), n = a.length;
  if (!n) return "";
  const c = (f) => a.filter(f).length, ms = a.map((i) => i.choice.ms).filter((x) => x > 0).sort((x, y) => x - y);
  const timed = a.filter((i) => i.choice.shown), first = c((i) => i.choice.shown === 1);
  const cell = (k, v, t) => `<div><b>${v}</b><span>${k}</span>${t ? `<i>${t}</i>` : ""}</div>`;
  return `<section><h3>Your answers</h3><div class="habits">`
    + cell("answered", n)
    + cell("picked the first one shown", timed.length ? `${first}/${timed.length}` : "N/A", timed.length >= 3 && first / timed.length > 0.6 ? "more than chance: read before you pick" : "")
    + cell("changed a value or a reading", `${c((i) => i.choice.name || i.choice.differs || Object.values(i.settings || []).some((s) => s.edited))}/${n}`)
    + cell("wrote their own", `${c((i) => i.choice.kind === "own")}/${n}`)
    + cell("answered in the chat", `${c((i) => i.choice.kind === "chat")}/${n}`)
    + cell("median time to answer", ms.length ? `${Math.round(ms[ms.length >> 1] / 1000)} s` : "N/A")
    + `</div></section>`;
}
function drawProject() {
  const p = S.data.project || { modules: [], settings: [] }, mods = p.modules || [], sets = p.settings || [];
  $("#main").innerHTML = `<p class="quote">Project</p><p class="counts">${mods.length} modules · ${sets.length} settings you confirmed (never asked again)</p>`
    + `<section><h3>Modules</h3><div class="mods">${mods.map((m, k) => `<div class="modc" data-k="${k}"><input class="name" value="${esc(m.name)}" aria-label="Module name">`
      + `<textarea class="purpose" rows="2" placeholder="What it does, in one line" aria-label="Purpose">${esc(m.purpose || "")}</textarea>`
      + `<textarea class="paths" rows="${Math.min(6, Math.max(2, m.paths.length))}" aria-label="Folders and files, one per line">${esc(m.paths.join("\n"))}</textarea></div>`).join("")
      || `<p class="empty">No modules yet: open the map and save its modules.</p>`}</div>`
    + `<div class="row"><button type="button" class="btn" id="addm">Add a module</button><button type="button" class="go" id="savem">Save modules</button></div></section>`
    + habits()
    + `<section><h3>Confirmed settings</h3><table><tbody>${sets.map((s) => `<tr><td class="key">${esc(s.key)}</td><td class="val">${esc(s.value)}</td>`
      + `<td class="from">${esc(short(s.at))}</td><td><button type="button" class="x" data-forget="${esc(s.key)}" aria-label="Forget ${esc(s.key)}">forget</button></td></tr>`).join("")
      || `<tr><td class="empty">None yet.</td></tr>`}</tbody></table></section>`;
  const read = () => [...document.querySelectorAll(".modc")].map((c) => ({ name: $(".name", c).value, purpose: $(".purpose", c).value, paths: $(".paths", c).value.split("\n") }));
  $("#addm").onclick = () => { S.data.project = { ...p, modules: [...read(), { name: "new module", purpose: "", paths: [] }] }; drawProject(); };
  $("#savem").onclick = async () => { try { S.data.project = (await api(`/api/mod/project?${q()}`, { modules: read() })).project; toast("Modules saved."); drawProject(); } catch (e) { toast(e.message); } };
  document.querySelectorAll("[data-forget]").forEach((b) => (b.onclick = async () => { S.data.project = (await api(`/api/mod/project?${q()}`, { forget: b.dataset.forget })).project; drawProject(); }));
}

/* ---------- wiring ---------- */
addEventListener("keydown", (e) => {
  if (/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "")) return;
  if (e.key === "Enter" && e.target.closest?.("button, a, summary") && e.target.id !== "go") return; // that control's own action
  const i = S.data?.intents.find((x) => x.id === S.cur);
  if (!i || i.status === "answered") return;
  const order = shuffled((i.candidates || []).length, i.id || "");
  if (/^[1-9]$/.test(e.key) && order[+e.key - 1] !== undefined && !S.rx[order[+e.key - 1]]?.deleted) { e.preventDefault(); choose(order[+e.key - 1]); }
  else if (/^[1-9]$/.test(e.key) && +e.key === order.length + 1) { e.preventDefault(); $("#own")?.focus(); }
  else if (e.key === "Enter" && S.pick !== null) { e.preventDefault(); send(i); }
});
(async function boot() {
  const hp = new URLSearchParams(location.hash.slice(1));
  const { projects } = await api("/api/projects");
  S.p = projects[+hp.get("p")] ? +hp.get("p") : 0;
  $("#picker").innerHTML = projects.map((p) => `<option value="${p.i}">${esc(p.name)}</option>`).join("");
  $("#picker").value = S.p;
  document.querySelector(".brand a").href = `/#p=${S.p}`;
  $("#picker").onchange = (e) => { S.p = +e.target.value; location.hash = `p=${S.p}`; S.cur = null; S.seen.clear(); load(true); };
  $("#proj").onclick = () => select("project");
  await load(true);
  if (hp.get("v") === "project") select("project");
  setInterval(() => { if (!document.hidden) load(false); }, 2000); // ponytail: a 2 s poll of small files; an event stream if it ever matters
})();
