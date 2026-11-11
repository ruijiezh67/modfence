/* The .mod page: what the agent understood from your words, judged in seconds. No reading is preselected or marked as
   recommended, and their order is shuffled (per intent, so it does not move while you look). Keys: 1-3 pick a reading,
   Enter continues. */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const S = { p: 0, data: null, cur: null, pick: null, own: "", edits: {}, seen: new Set() };
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

async function load(first) {
  try { S.data = await api(`/api/mod?${q()}`); } catch (e) { $("#main").innerHTML = `<p class="empty">${esc(e.message)}</p>`; return; }
  const waiting = S.data.intents.find((i) => i.status === "waiting" && !S.seen.has(i.id));
  if (waiting) { S.seen.add(waiting.id); select(waiting.id); document.title = "● modfence: your agent is waiting"; return; }
  if (first) select(S.data.intents[0]?.id || "project"); else drawList();
}
function drawList() {
  const list = $("#list"), it = S.data.intents;
  list.innerHTML = it.map((i) => `<li><button type="button" class="item${i.status === "waiting" ? " waiting" : ""}" data-id="${esc(i.id)}"${S.cur === i.id ? ' aria-current="true"' : ""}>`
    + `<b>${esc(i.words)}</b><span>${esc(i.status === "waiting" ? "your agent is waiting" : i.status === "answered" ? "answered" : "open")} · ${esc(i.id)}</span></button></li>`).join("")
    || `<li class="empty">No intents yet. When you give your agent a task it cannot do without guessing, it writes one here.</li>`;
  list.querySelectorAll("[data-id]").forEach((b) => (b.onclick = () => select(b.dataset.id)));
  $("#proj").setAttribute("aria-current", String(S.cur === "project"));
}
function select(id) {
  if (S.cur !== id) { S.pick = null; S.own = ""; S.edits = {}; }
  S.cur = id; drawList();
  if (id === "project") return drawProject();
  const i = S.data.intents.find((x) => x.id === id);
  if (i) drawIntent(i);
}

/* ---------- one intent ---------- */
function drawIntent(i) {
  const words = String(i.words || ""), settings = (i.settings || []).slice().sort((a, b) => ORDER[a.source] - ORDER[b.source]);
  // align: each setting that came from your words gets a number on those words; the rest say "not in your words"
  let quote = esc(words), n = 0; const num = {};
  settings.forEach((s) => {
    const f = String(s.from || "").trim(), at = f ? quote.toLowerCase().indexOf(esc(f).toLowerCase()) : -1;
    if (at < 0) return;
    num[s.key] = ++n;
    quote = quote.slice(0, at) + `<mark data-n="${n}">${quote.slice(at, at + esc(f).length)}<sup>${n}</sup></mark>` + quote.slice(at + esc(f).length);
  });
  const count = (src) => settings.filter((s) => s.source === src).length;
  const cands = i.candidates || [], order = shuffled(cands.length, i.id || ""), keys = [...new Set(cands.flatMap((c) => Object.keys(c.differs || {})))]
    .filter((k) => new Set(cands.map((c) => String((c.differs || {})[k] ?? "—"))).size > 1);
  const answered = i.status === "answered";
  const row = (s) => `<tr class="${s.source}${s.source === "user" || s.source === "default" ? " quiet" : ""}${S.edits[s.key] !== undefined ? " changed" : ""}" data-key="${esc(s.key)}">`
    + `<td class="src">${SRC[s.source]?.[0] || ""} ${SRC[s.source]?.[1] || esc(s.source)}${s.source === "memory" && s.at ? ` ${esc(short(s.at))}` : ""}</td>`
    + `<td class="key">${esc(s.key)}</td><td class="val${answered ? "" : " edit"}" title="${answered ? "" : "Click to change"}">${esc(S.edits[s.key] ?? s.value)}</td>`
    + `<td class="from">${num[s.key] ? `from your words <span class="n">${num[s.key]}</span>` : "not in your words"}</td></tr>`;
  const need = settings.filter((s) => s.source === "guess" || s.source === "memory"), rest = settings.filter((s) => !need.includes(s));
  const sc = i.scale || {}, stops = [["one", "one run"], ["sample", "a sample"], ["full", "everything"]];
  const plan = Array.isArray(i.plan) ? i.plan : [];
  $("#main").innerHTML = `<p class="quote">“${quote}”</p>`
    + `<p class="counts"><b class="g">${count("guess")} guessed</b> · <b class="m">${count("memory")} from memory</b> · ${count("user")} you said · ${count("default")} default</p>`
    + (cands.length ? `<section><h3>Which did you mean?</h3><div class="readings" style="--n:${cands.length}">${order.map((ci, k) => {
      const c = cands[ci];
      return `<button type="button" class="reading" data-ci="${ci}" aria-pressed="${S.pick === ci}" ${answered ? "disabled" : ""}><span class="k">${k + 1}</span><strong>${esc(c.name)}</strong>`
        + (c.description ? `<p>${esc(c.description)}</p>` : "")
        + (keys.length ? `<dl>${keys.map((key) => `<dt>${esc(key)}</dt><dd>${esc((c.differs || {})[key] ?? "—")}</dd>`).join("")}</dl>` : "")
        + `<span class="ev">${esc(c.evidence || "")}</span></button>`; }).join("")}</div>`
      + (answered ? "" : `<div class="own"><input type="text" id="own" placeholder="Or say it in your own words" value="${esc(S.own)}"${S.pick === "own" ? ' class="on"' : ""}></div>`) + `</section>` : "")
    + (settings.length ? `<section><h3>Settings</h3><table><tbody>${need.map(row).join("")}</tbody></table>`
      + (rest.length ? `<details${need.length ? "" : " open"}><summary>${rest.length} you said or default</summary><table><tbody>${rest.map(row).join("")}</tbody></table></details>` : "") + `</section>` : "")
    + (sc.pick ? `<section><h3>How much</h3><div class="scale">${stops.map(([k, t]) => `<div class="stop${sc.pick === k ? " on" : ""}">${t}</div>`).join("")}</div>`
      + `<p class="cost">${sc.runs != null ? `${esc(sc.runs)} runs` : "runs N/A"} · ${esc(sc.cost || "cost N/A")} · ${esc(sc.time || "time N/A")}</p></section>` : "")
    + (plan.length ? `<section><h3>Where it is</h3><p class="plan">${plan.map((p, k) => k === 1 ? `<b>→ ${esc(p)}</b>` : `<span>${esc(p)}</span>`).join("")}</p></section>` : "")
    + (answered ? `<p class="done">Answered: ${esc(i.choice?.kind === "own" ? i.choice.text : cands[i.choice?.index]?.name || "")}. Your agent has it.</p>` : "")
    + (answered ? "" : `<div class="bar"><span class="what" id="what"></span><button type="button" class="go" id="go" disabled>Continue <kbd>Enter</kbd></button></div>`);
  wireIntent(i);
}
function wireIntent(i) {
  const main = $("#main");
  main.querySelectorAll(".reading").forEach((b) => (b.onclick = () => choose(+b.dataset.ci)));
  const own = $("#own");
  if (own) own.oninput = () => { S.own = own.value; S.pick = own.value.trim() ? "own" : null; mark(i); };
  main.querySelectorAll("tr[data-key]").forEach((tr) => {
    const m = main.querySelector(`.quote mark[data-n="${tr.querySelector(".n")?.textContent}"]`);
    tr.onmouseenter = () => { tr.classList.add("hot"); m?.classList.add("hot"); };
    tr.onmouseleave = () => { tr.classList.remove("hot"); m?.classList.remove("hot"); };
    const td = tr.querySelector(".val.edit");
    if (td) td.onclick = () => { // change a value in place; Enter keeps it, Esc drops it
      if (td.querySelector("input")) return;
      const key = tr.dataset.key, input = document.createElement("input");
      input.value = td.textContent; td.textContent = ""; td.appendChild(input); input.focus(); input.select();
      const done = (keep) => { if (keep && input.value !== (i.settings.find((s) => s.key === key) || {}).value) S.edits[key] = input.value; drawIntent(i); };
      input.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); e.stopPropagation(); done(true); } if (e.key === "Escape") done(false); };
      input.onblur = () => done(true);
    };
  });
  $("#go") && ($("#go").onclick = () => send(i));
  mark(i);
}
function choose(ci) { S.pick = ci; S.own = ""; const i = S.data.intents.find((x) => x.id === S.cur); drawIntent(i); }
function mark(i) {
  document.querySelectorAll(".reading").forEach((b) => b.setAttribute("aria-pressed", String(S.pick === +b.dataset.ci)));
  $("#own")?.classList.toggle("on", S.pick === "own");
  const go = $("#go"), what = $("#what"), n = Object.keys(S.edits).length;
  if (!go) return;
  go.disabled = S.pick === null;
  what.textContent = S.pick === null ? "Pick a reading (1-3) or write your own." : (S.pick === "own" ? `Your words: “${S.own}”` : `“${i.candidates[S.pick].name}”`) + (n ? ` · ${n} setting${n > 1 ? "s" : ""} changed` : "");
}
async function send(i) {
  if (S.pick === null) return;
  const choice = S.pick === "own" ? { kind: "own", text: S.own } : { kind: "pick", index: S.pick };
  try { await api(`/api/mod/answer?${q()}`, { id: i.id, choice, edits: S.edits }); }
  catch (e) { toast(e.message); return; }
  toast("Sent. Your agent continues."); document.title = "modfence intents";
  await load(false); select(i.id);
}

/* ---------- the project: modules and the settings you confirmed ---------- */
function drawProject() {
  const p = S.data.project || { modules: [], settings: [] }, mods = p.modules || [], sets = p.settings || [];
  $("#main").innerHTML = `<p class="quote">Project</p><p class="counts">${mods.length} modules · ${sets.length} settings you confirmed (never asked again)</p>`
    + `<section><h3>Modules</h3><div class="mods">${mods.map((m, k) => `<div class="modc" data-k="${k}"><input class="name" value="${esc(m.name)}" aria-label="Module name">`
      + `<input class="purpose" value="${esc(m.purpose || "")}" placeholder="What it does, in one line" aria-label="Purpose">`
      + `<textarea class="paths" rows="${Math.min(6, Math.max(2, m.paths.length))}" aria-label="Folders and files, one per line">${esc(m.paths.join("\n"))}</textarea></div>`).join("")
      || `<p class="empty">No modules yet: open the map and save its modules.</p>`}</div>`
    + `<div class="row"><button type="button" class="btn" id="addm">Add a module</button><button type="button" class="go" id="savem">Save modules</button></div></section>`
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
  const i = S.data?.intents.find((x) => x.id === S.cur);
  if (!i || i.status === "answered") return;
  const order = shuffled((i.candidates || []).length, i.id || "");
  if (/^[1-9]$/.test(e.key) && order[+e.key - 1] !== undefined) { e.preventDefault(); choose(order[+e.key - 1]); }
  else if (e.key === "Enter" && S.pick !== null) { e.preventDefault(); send(i); }
});
(async function boot() {
  const hp = new URLSearchParams(location.hash.slice(1));
  const { projects } = await api("/api/projects");
  S.p = projects[+hp.get("p")] ? +hp.get("p") : 0;
  $("#picker").innerHTML = projects.map((p) => `<option value="${p.i}">${esc(p.name)}</option>`).join("");
  $("#picker").value = S.p;
  $("#picker").onchange = (e) => { S.p = +e.target.value; location.hash = `p=${S.p}`; S.cur = null; S.seen.clear(); load(true); };
  $("#proj").onclick = () => select("project");
  await load(true);
  setInterval(() => { if (!document.hidden) load(false); }, 2000); // ponytail: a 2 s poll of small files; an event stream if it ever matters
})();
