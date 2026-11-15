"use strict";
// memory-core item D (2026-10-13): the store's own page. No new API - every call below is the
// same /memory HTTP surface the web app, OpenCode and curl use; the page is a window, not a wall.
const $ = id => document.getElementById(id);
let apiKey = sessionStorage.getItem("strata.memory.key") || "";
document.documentElement.dataset.theme = localStorage.getItem("strata.theme") || "dark";
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
async function api(path, body) {
  const response = await fetch(path, { cache: "no-store",
    headers: { ...(apiKey ? { Authorization: `Bearer ${apiKey}` } : {}),
               ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    ...(body !== undefined ? { method: "POST", body: JSON.stringify(body) } : {}) });
  const value = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error((value.error && value.error.message) || `HTTP ${response.status}`);
  return value;
}
function note(msg, bad) { const e = $("error"); e.hidden = !msg; e.textContent = msg || ""; if (bad) e.scrollTop = 0; }
const when = t => typeof t === "number" ? new Date(t * 1000).toLocaleString() : "—";
// 18th-century print typography, for READING only. Blackstone's and Blackstone's contemporaries
// were set with the long-s — `uſe`, `conſtitution`, `ſeveral` — and the print line breaks mid-word,
// so a row carries `per- haps` and `rea- ſon`. The ledger keeps the scan verbatim (the apparatus
// is not the text); this transforms the display, not the row, so a copy out of the page still
// matches the stored bytes in the browser's own normalizing form.
// The transform belongs to the CORPUS, not the store (audit 2026-11-07): a MEM/CAT label is stored
// as `STR - cache, decode, auto` and the join ate its separator, so the index panel read
// "STR cache, decode, auto" for 4 of the 50 most recent rows.
const readable = (t, cls) => {
  const s = String(t ?? "");
  return cls && String(cls).startsWith("DOC/")
    ? s.replace(/\u017F/g, "s").replace(/-\s+/g, "")   // long-s AND the print line-break hyphen
    : s.replace(/\u017F/g, "s");                        // everything else: the long-s only
};
let lastView = { q: "" };
let STATS = {};          // last stats read, so the tier-2 view can paint without a second call
let TIER = "t3";

function factRow(m) {
  const li = document.createElement("li");
  li.className = "fact";
  const cls = m.class ? `<span class="chip cls">${esc(m.class)}</span>` : `<span class="chip">wild</span>`;
  li.innerHTML = `<div class="body"><div class="txt">${esc(readable(m.text, m.class))}</div>
    <div class="meta">#${m.id} · ${cls}<span class="chip">${esc(m.scope || "default")}</span>
      conf ${Number(m.confidence ?? 1).toFixed(2)} · ${m.hits || 0} recall${m.hits === 1 ? "" : "s"} · ${when(m.updated_at || m.created_at)}</div>
    ${m.invalid_at ? `<div class="meta"><span class="chip stale">superseded ${when(m.invalid_at)}</span>${
        m.superseded_by ? `by <a href="#fact-${m.superseded_by}" style="color:inherit">#${m.superseded_by}</a>` : ""
      }</div>` : ""}
    ${m.links ? `<div class="meta">${m.links.map(l =>
        `<span class="chip${l.kind === "contradicts" ? " stale" : " cls"}">${esc(l.direction === "incoming" ? "←" : "→")}${esc(l.kind)} #${l.id}</span>`).join("")}</div>` : ""}</div>`;
  const btn = document.createElement("button");
  btn.textContent = "Forget";
  btn.onclick = async () => {
    if (!confirm(`Forget fact #${m.id}?`)) return;
    try { await api("/memory", { op: "forget", id: m.id }); show(lastView.q, true); }
    catch (e) { note(e.message, true); }
  };
  li.append(btn);
  return li;
}

async function show(q, repeat) {
  lastView = { q };
  note("");
  try {
    if (q) {
      const p = new URLSearchParams({ q, limit: "50" });
      if ($("scope").value.trim()) p.set("scope", $("scope").value.trim());
      if ($("klass").value.trim()) p.set("class", $("klass").value.trim());
      const d = await api(`/memory?${p}`);
      cards(d.stats || STATS);      // the tiles follow the write (audit 2026-11-07: the ?q= reply
      //   carried no stats, so Remember-then-search left Facts and Curation on the old numbers)
      render(d.hits || [], `${(d.hits || []).length} hit${(d.hits || []).length === 1 ? "" : "s"} for “${q}”`,
             d.scope);
    } else {
      const p = new URLSearchParams({ limit: "50", docs: "1", links: "1" });   // the ledger rides the stats card
      if ($("inval") && $("inval").checked) p.set("include_invalid", "1");      // the scar, on demand
      if ($("scope").value.trim()) p.set("scope", $("scope").value.trim());
      if ($("klass").value.trim()) p.set("class", $("klass").value.trim());
      const d = await api(`/memory?${p}`);
      cards(d.stats || {});
      const n = (d.memories || []).length, total = (d.stats || {}).facts;
      render(d.memories || [], total && n < total ? `the ${n} newest of ${total.toLocaleString()} facts`
                                                  : `${n} fact${n === 1 ? "" : "s"}`, d.scope);
    }
  } catch (e) { note(e.message, true); $("list").innerHTML = `<li class="empty">Could not read the store.</li>`; }
}

function render(list, title, scope) {
  const ul = $("list");
  ul.innerHTML = "";
  // The caption is PAINTED (audit 2026-11-07: it was built by both callers and thrown away, so a
  // 50-row cut of a 2,081-fact store looked like the whole store and a search never said what it
  // searched). The scope rides with it because the SEARCH arm is scope-filtered and the BROWSE
  // arm is not, and a 0-hit answer with an empty scope box is unreadable without that.
  if ($("caption")) {
    $("caption").textContent = (title || "") + (scope ? ` · scope ${scope}` : "")
      + ($("klass").value.trim() ? ` · shelf ${$("klass").value.trim()}` : "");
  }
  if (!list.length) { ul.innerHTML = `<li class="empty">Nothing found.</li>`; return; }
  for (const m of list) ul.append(factRow(m));
}

function cards(s) {
  STATS = s;
  $("rows").textContent = s.facts ?? s.memories ?? "—";
  $("rowsub").textContent = (s.max_memories ? `of ${s.max_memories} cap${s.pressure ? " · pressure" : ""}` : "no cap")
    // the two numbers the sweep is judged by, both already on the wire (audit 2026-11-07: sent
    // and never painted): over_cap is the rows the budget pushed out, invalid is the version chain
    + (s.over_cap ? ` · ${s.over_cap} over cap` : "")
    + (s.invalid ? ` · ${s.invalid.toLocaleString()} superseded` : "");
  // The semantic arm is a TILE (audit 2026-11-07): stats.embedder carries loaded, model, vectors
  // and unembedded, and a dead embedder used to leave the page looking normal while recall dropped
  // to lexical-only in silence.
  if ($("embed")) {
    const e = s.embedder || {};
    $("embed").textContent = e.on ? (e.loaded ? "on" : "degraded") : "off";
    $("embedsub").textContent = e.on
      ? (e.loaded
        ? `${e.model || "?"} · ${(e.vectors || 0).toLocaleString()} vectors`
          + (e.unembedded ? ` · ${e.unembedded.toLocaleString()} unembedded` : "")
          + (e.foreign ? ` · ${e.foreign.toLocaleString()} foreign` : "")
        : (e.error || "the model did not load - recall is lexical only"))
      : "no embedder configured - the cosine arm is not running";
  }
  // the two families (2026-11-03): Facts is what the server remembers; Docs is the corpus
  // routing map - chunks that route to files, not memories the sweep tends.
  if ($("docs")) {
    $("docs").textContent = s.doc_chunks ?? "—";
    const cor = (s.docs || []).map(c => `${c.corpus}·${c.files}f`).join(" ");
    $("docssub").textContent = cor || (s.doc_chunks ? "indexed folders" : "no corpus indexed yet");
  }
  $("pending").textContent = s.turns_pending ?? "—";
  $("pendsub").textContent = "journaled turns awaiting the sweep";
  const rest = s.at_rest || {};
  // The mode string is COMPOUND on this box - "pgdata-0700 + key-file" (+ "+passphrase-env") - and
  // the tile compared it with === "key-file", so a store with a 0600 key-file said "plain".
  const sealed = typeof rest.mode === "string" && rest.mode.includes("key-file");
  $("rest").textContent = sealed ? "sealed" : (rest.mode === "off" ? "off" : "plain");
  $("restsub").textContent = sealed ? `key-file · ${rest.cluster || "cluster"} · ${rest.data || ""}`
    : (typeof rest.mode === "string" && rest.mode !== "off" ? rest.mode : "plaintext at rest");
  const c = s.cartridges;
  $("reseed").hidden = !c;
  // the address boxes offer what the store HAS (audit 2026-11-07: a shelf typed as POLITICS
  // answers "Nothing found", indistinguishable from a real empty drawer, and stats.by_class
  // has carried every shelf name on this same response since the map shipped)
  if ($("shelves"))
    $("shelves").innerHTML = Object.keys(s.by_class || {}).slice(0, 300)
      .map(k => `<option value="${esc(k)}"></option>`).join("");
  if ($("scopes"))
    $("scopes").innerHTML = Object.keys(s.by_scope || {}).filter(k => k !== "default")
      .map(k => `<option value="${esc(k)}"></option>`).join("");
  if (TIER === "t2") renderCart();
}

// ---- the tier-2 view (2026-10-24, owner's ask): the Cartridge card slot became a flip switch -
// tier-3 is the text system (cards, search, the fact list); tier-2 is the cartridge system: the
// standing cart's state, the slot vault's files, and the MEM/CAT index the catalog writes.
function renderCart() {
  const c = STATS.cartridges;
  $("c-state").textContent = c ? c.state : "off";
  // "loaded" is the LEDGER's state; kv_standing is whether THIS engine's slot holds those bytes
  // (audit 2026-11-07: after an engine restart the tile read `loaded` over an empty slot, which is
  // exactly the report a stale cart hides - server.py added kv_standing for this on 2026-10-24).
  $("c-sub").textContent = c
    ? `${c.file || "(not applied yet)"} · soul ${c.soul_chars} ch`
      + (c.state === "off" ? "" : c.kv_standing ? " · standing in this engine" : " · NOT in this engine's slot")
    : "memory.cartridges in the config";
  // `sources` is a list of NAMES on the wire; the guard is so that one absent key costs one tile
  // and not the five below it (measured 2026-11-07: the Rust arm answered the ledger's object,
  // `.join` threw, and Carts / Index / Re-seed / the vault / the ledger all kept their placeholders)
  const src = (c && Array.isArray(c.sources)) ? c.sources : [];
  $("c-facts").textContent = c ? (c.facts_mode === false ? src.length + " files" : c.facts) : "—";
  $("c-factsub").textContent = c ? (c.facts_mode === false
    ? `${(src.join(" + ") || "(nothing to stand)")} · ${((c.bytes || 0) / 1048576).toFixed(0)} MB · shelved facts ride the block`
    : `${(c.bytes / 1048576).toFixed(0)} MB · ${c.left_for_block} left for the block · cap ${c.max_chars} ch`) : "";
  $("c-index").textContent = (STATS.by_class && STATS.by_class["MEM/CAT"]) ?? "—";
  $("c-indexsub").textContent = "MEM/CAT labels on the map of the shelves";
  $("c-window").textContent = c ? (c.reseed_in_s ? `in ${c.reseed_in_s}s` : "open") : "—";
  $("c-windowsub").textContent = "moved standing text waits the window; Reseed now bypasses it";
  // The S3 cart ledger (2026-10-25): the server already ships stats.carts - every row, and
  // whether its .bin actually stands. Painted here, in the page's own dialect; when the
  // pipeline is OFF the panel says so rather than showing an empty list (anti-vacuity: an
  // absent thing is never silently "not enough"). Retire is the page's only pen: staleness
  // and re-mints belong to the hook and the sweep window, not to a button.
  const carts = STATS.carts;
  const fresh = (carts || []).filter(k => k.state === "fresh").length;
  const staleN = (carts || []).filter(k => k.state === "stale").length;
  $("c-carts").textContent = carts ? String(fresh) : "off";
  $("c-cartsub").textContent = carts
    ? `fresh of ${carts.length} on the ledger${staleN ? ` · ${staleN} stale, waiting the window` : ""}`
    : "the mint pipeline is off (memory.cartridges.minted)";
  const cl = $("carts");
  cl.innerHTML = "";
  if (!carts) cl.innerHTML = `<li class="empty">No ledger is kept while the mint pipeline is off.</li>`;
  else if (!carts.length) cl.innerHTML = `<li class="empty">The ledger is empty: row zero registers at the first standing request.</li>`;
  for (const k of carts || []) {
    const li = document.createElement("li");
    li.className = "fact";
    const state = k.state === "stale" ? `<span class="chip stale">stale</span>`
                : k.state === "retired" ? `<span class="chip">retired</span>`
                : `<span class="chip cls">fresh</span>`;
    li.innerHTML = `<div class="body"><div class="txt" style="font-family:ui-monospace,monospace">${esc(k.name)}</div>
      <div class="meta"><span class="chip${k.kind === "standing" ? " cls" : ""}">${esc(k.kind)}</span>${state}
        ${(k.tokens || 0).toLocaleString()} tok saved · ${((k.bytes || 0) / 1048576).toFixed(0)} MB
        · <span style="font-family:ui-monospace,monospace">${esc(k.file)}</span>${k.file_exists ? "" : " · file GONE"}
        ${k.remint_count ? ` · ${k.remint_count} re-mint${k.remint_count === 1 ? "" : "s"}` : ""} · ${when(k.minted)}</div>
      ${k.stale_reason ? `<div class="meta">why: ${esc(k.stale_reason)}</div>` : ""}</div>`;
    if (k.state !== "retired") {
      const btn = document.createElement("button");
      btn.textContent = "Retire";
      if (k.name === "standing") { btn.disabled = true; btn.title = "row zero does not shelve (op=retire refuses it)"; }
      btn.onclick = async () => {
        if (!confirm(`Retire cart "${k.name}"? The ledger keeps the row and the scar; the index line goes quiet.`)) return;
        btn.disabled = true;
        try { await api("/memory", { op: "retire", name: k.name, reason: "retired from the page" });
              const d = await api(`/memory?limit=1`); STATS = d.stats || STATS; renderCart(); }
        catch (e) { note(e.message, true); btn.disabled = false; }
      };
      li.append(btn);
    }
    cl.append(li);
  }
  const ul = $("files");
  ul.innerHTML = "";
  const files = (c && c.files && c.files.length) ? c.files
    : (c && c.file ? [{ name: c.file, mb: (c.bytes / 1048576).toFixed(1), mtime: null,
                        kind: "standing", live: true }] : []);
  if (!files.length) { ul.innerHTML = `<li class="empty">No slot files visible to the server.</li>`; return; }
  // The vault list is CUT at 24 and the server now says so (audit 2026-11-07: after a venue day the
  // panel listed 24 files and read like the whole shelf).
  if ($("vaultnote"))
    $("vaultnote").textContent = (c.files_total && c.files_total > files.length)
      ? `${files.length} of ${c.files_total} files, newest first` : "one standing cartridge per engine pin";
  for (const f of files) {
    const li = document.createElement("li");
    li.className = "fact";
    li.innerHTML = `<div class="body"><div class="txt" style="font-family:ui-monospace,monospace">${esc(f.name)}</div>
      <div class="meta"><span class="chip${f.kind === "standing" ? " cls" : ""}">${esc(f.kind)}</span>${f.live ? `<span class="chip cls">applied</span>` : ""} ${f.mb} MB · ${when(f.mtime)}</div></div>`;
    ul.append(li);
  }
}
async function renderCatlog() {
  try {
    const d = await api("/memory?class=MEM%2FCAT&limit=50");
    const ul = $("catlog");
    ul.innerHTML = "";
    const rows = d.memories || [];
    if (!rows.length) { ul.innerHTML = `<li class="empty">No labels yet - the catalog tick writes them.</li>`; return; }
    for (const m of rows) ul.append(factRow(m));
  } catch (e) { $("catlog").innerHTML = `<li class="empty">Could not read the index.</li>`; }
}
function tier(t) {
  TIER = t;
  $("t3wrap").hidden = t !== "t3";
  $("t2wrap").hidden = t !== "t2";
  $("grwrap").hidden = t !== "gr";
  $("t3btn").className = t === "t3" ? "primary" : "";
  $("t2btn").className = t === "t2" ? "primary" : "";
  $("grbtn").className = t === "gr" ? "primary" : "";
  // the toggle says which one is showing (audit 2026-11-07: colour was the only signal)
  $("t3btn").setAttribute("aria-pressed", t === "t3");
  $("t2btn").setAttribute("aria-pressed", t === "t2");
  $("grbtn").setAttribute("aria-pressed", t === "gr");
  if (t === "t2") { renderCart(); renderCatlog(); }
  if (t === "gr") graphView();
}
$("t3btn").onclick = () => tier("t3");
$("t2btn").onclick = () => tier("t2");
$("grbtn").onclick = () => tier("gr");

$("search").onclick = () => show($("q").value.trim());
$("q").onkeydown = e => { if (e.key === "Enter") show($("q").value.trim()); };
$("browse").onclick = () => show("");
$("remember").onclick = async () => {
  const lines = $("addtext").value.split("\n").map(t => t.trim()).filter(Boolean);
  if (!lines.length) return;
  // BUSY STATE (audit 2026-11-07): fifteen lines are fifteen embed-and-insert round trips, and the
  // button looked idle through all of them - twice meant the list was written twice. The note now
  // counts as it goes, and the textarea keeps ONLY the line that failed, so a 5,000-character
  // paragraph (the store's ceiling) is the one thing left to fix.
  const btn = $("remember");
  btn.disabled = true;
  let at = 0;                                  // the line the store refused, for the rewrite-back
  try {
    let ids = [], dup = 0;
    for (const [i, text] of lines.entries()) {
      at = i;
      $("addnote").textContent = `storing ${i + 1} of ${lines.length}…`;
      const body = { op: "remember", text };
      if ($("addscope").value.trim()) body.scope = $("addscope").value.trim();
      if ($("addclass").value.trim()) body.class = $("addclass").value.trim();
      const r = await api("/memory", body);
      if (r.id) ids.push(r.id);
      if (r.deduped) dup++;
    }
    $("addnote").textContent = `stored #${ids.join(", #")}${dup ? ` (${dup} were near-duplicates)` : ""}`;
    $("addtext").value = "";
    show(lastView.q, true);
  } catch (e) {
    note(e.message, true);
    $("addnote").textContent = `${at} of ${lines.length} stored - fix the line below and press again`;
    $("addtext").value = lines.slice(at).join("\n");
  } finally {
    btn.disabled = false;
  }
};
$("reseed").onclick = async () => {
  $("reseed").disabled = true;
  try { await api("/memory", { op: "cartridge" });
        const d = await api(`/memory?limit=1`); STATS = d.stats || STATS; renderCart(); }
  catch (e) { note(e.message, true); }
  $("reseed").disabled = false;
};
// The vault's pen (audit 2026-11-07, item 9): the C-series and the venue days left ~500 MB of bench
// slot saves in the vault and nothing on any page could clear them. Seven days: older than a working
// week, newer than the pins that would want them.
$("purge").onclick = async () => {
  if (!confirm("Delete the vault's bench slot saves older than 7 days?\nThe standing cart and the file this engine applied stay.")) return;
  $("purge").disabled = true;
  try {
    const r = await api("/memory", { op: "cartridge", purge_older_than_s: 7 * 86400 });
    const g = ((r.cartridge || {}).files) || [];
    note("");
    $("addnote").textContent = g.length
      ? `cleared ${g.length} save${g.length === 1 ? "" : "s"} · ${(r.cartridge.freed_mb || 0).toFixed(0)} MB freed`
      : "nothing older than 7 days";
    const d = await api(`/memory?limit=1`); STATS = d.stats || STATS; renderCart();
  } catch (e) { note(e.message, true); }
  $("purge").disabled = false;
};
// tier-2 as a flip switch, not a config edit: facts:false stands the five files, facts:true stands
// the shelved facts. One call re-seeds; the config write beside it is what survives a reboot.
$("tierflip").onclick = async () => {
  const want = !(STATS.cartridges && STATS.cartridges.facts_mode === true);
  $("tierflip").disabled = true;
  try {
    await api("/memory", { op: "cartridge", facts: want });
    try { await api("/config", { set: { "memory.cartridges.facts": want } }); } catch (_) { /* no config file: the live flip stands */ }
    const d = await api(`/memory?limit=1`); STATS = d.stats || STATS; renderCart();
  } catch (e) { note(e.message, true); }
  $("tierflip").disabled = false;
};
$("inval").onchange = () => show(lastView.q);
$("key").onclick = () => {
  const k = prompt("API key for this server (blank for none):", apiKey);
  if (k === null) return;
  apiKey = k.trim();
  sessionStorage.setItem("strata.memory.key", apiKey);
  show("");
};
$("theme").onclick = () => {
  document.documentElement.dataset.theme = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  localStorage.setItem("strata.theme", document.documentElement.dataset.theme);
};

// ---- the graph view (2026-11-15). strata.graphify builds the store's graph from the fact text
// on the served model and keeps it in <store>/strata-graphify/, so the page, the CLI and a
// cloned box all read the same file. A pass is LLM work, so it runs on a server thread and this
// view polls it through op=graph.
//
// The drawing is a dependency-free canvas in three dimensions: the layout is a force simulation
// over x/y/z, the camera orbits with the mouse and zooms with the wheel, and depth drives size
// and opacity the way a star chart does. Positions are computed once per graph and cached, so
// orbiting costs a projection, not a re-simulation.
let GPOLL = null, GDATA = null, GSTATE = null;
const GVIS = new Set();                       // visible community ids
let GCAM = { yaw: -0.55, pitch: 0.42, k: 1, x: 0, y: 0 };
const GCOLORS = ["#7aa2f7", "#9ece6a", "#f7768e", "#e0af68", "#7dcfff", "#bb9af7",
                 "#73daca", "#ff9e64", "#2ac3de", "#c0caf5", "#b9f27c", "#f472b6"];
const gc = c => GCOLORS[Math.abs(Number(c)) % GCOLORS.length];

async function graphStatus() {
  const d = await api("/memory", { op: "graph" });
  GSTATE = d.graph || (d.result && d.result.graph) || {};
  const s = GSTATE, p = s.progress || {};
  $("g-nodes").textContent = (s.nodes || 0).toLocaleString();
  $("g-edges").textContent = (s.edges || 0).toLocaleString();
  $("g-comm").textContent = (s.communities || 0).toLocaleString();
  // Coverage is the row ids the graph names, not the node count: a node is a concept the model
  // lifted out of several facts, so 147 nodes can speak for a thousand rows.
  $("g-graphed").textContent = (s.in_graph || 0).toLocaleString() + " / " + (s.facts || 0).toLocaleString();
  // The store's live count is already on the page (the FACTS tile), so this reads it rather
  // than paying for a second stats call.
  $("g-graphedsub").textContent = s.in_graph
    ? `${Math.round(100 * (s.in_graph || 0) / Math.max(1, s.facts || 1))}% of what the pass read · ${$("rows").textContent} live in the store`
    : "facts the graph names, over facts the pass read";
  $("g-built").textContent = s.built ? new Date(s.built).toLocaleString() : "never";
  $("g-builtsub").textContent = s.built
    ? `${s.mode || "full"} pass · ${(s.facts || 0).toLocaleString()} facts`
      + (s.seconds ? ` · ${Math.round(s.seconds / 60)} min` : "") + (s.model ? ` · ${s.model}` : "")
    : "a pass is LLM work on the served model";
  $("g-progtxt").textContent = s.running
    ? `pass running — chunk ${p.done}/${p.total}${p.files ? ` · ${p.files} files written` : ""}`
    : (s.error ? `last pass failed: ${s.error}`
               : (s.status === "ready"
                 ? `the graph stands · ${s.pending ? s.pending + " new fact(s) waiting a pass" : "nothing waiting"}`
                 : "no graph yet — a pass reads the shelves and asks what belongs with what"));
  return s;
}

async function graphTick() {
  const s = await graphStatus().catch(() => ({ running: false }));
  if (!s.running) { clearInterval(GPOLL); GPOLL = null; graphView(); }
}

async function graphView(rebuild) {
  try {
    const s = await graphStatus();
    if (s.running && !GPOLL) GPOLL = setInterval(graphTick, 15000);
    if (s.status !== "ready") {
      $("g-list").innerHTML = `<li class="empty">No graph yet. A pass reads every shelf once, eight files at a time.</li>`;
      return;
    }
    const v = await api("/memory", { op: "graph", action: "view" });
    const d = v.graph || (v.result && v.result.graph) || {};
    if (!d.nodes || !d.nodes.length) { $("g-list").innerHTML = `<li class="empty">The graph has no nodes.</li>`; return; }
    if (rebuild || !GDATA || GDATA.stamp !== s.built) {
      GDATA = d; GDATA.stamp = s.built;
      layout3(d);
      GVIS.clear(); (d.communities || []).forEach(c => GVIS.add(c.id));
      renderCommunities(d);
    }
    paint();
  } catch (e) { note(e.message, true); }
}

// A force simulation in three dimensions. Hubs sit on a Fibonacci sphere so communities get
// evenly spread shells; edges pull, nodes repel at short range, everything leans back toward
// its hub. Then normalise into the unit cube: the camera owns the framing, not the sim.
function layout3(d) {
  const N = d.nodes.length, hub = {};
  const phi = Math.PI * (3 - Math.sqrt(5));
  (d.communities || []).forEach((c, i) => {
    const y = 1 - (i / Math.max(1, d.communities.length - 1)) * 2;
    const r = Math.sqrt(Math.max(0, 1 - y * y)), a = phi * i;
    hub[c.id] = [Math.cos(a) * r * 0.82, y * 0.82, Math.sin(a) * r * 0.82];
  });
  const P = d.nodes.map((n, i) => {
    const h = hub[n.community] || [0, 0, 0], a = i * 2.399963, s = i * 0.618034 % 1;
    const z = 1 - s * 2, rr = Math.sqrt(Math.max(0, 1 - z * z)), th = phi * i;
    const rad = 0.05 + 0.30 * Math.sqrt(i / Math.max(1, N));
    return { x: h[0] + Math.cos(th) * rr * rad, y: h[1] + z * rad, z: h[2] + Math.sin(th) * rr * rad, i };
  });
  for (let it = 0; it < 240; it++) {
    const cool = 1 - it / 300;
    for (const [s, t] of (d.edges || [])) {
      const a = P[s], b = P[t]; if (!a || !b) continue;
      const dx = b.x - a.x, dy = b.y - a.y, dz = b.z - a.z;
      const dist = Math.hypot(dx, dy, dz) || 1e-6, f = (dist - 0.10) * 0.02 * cool;
      a.x += dx * f; a.y += dy * f; a.z += dz * f;
      b.x -= dx * f; b.y -= dy * f; b.z -= dz * f;
    }
    for (let i = 0; i < P.length; i++) {
      const a = P[i];
      for (let j = i + 1; j < P.length; j++) {
        const b = P[j], dx = a.x - b.x, dy = a.y - b.y, dz = a.z - b.z;
        const q = dx * dx + dy * dy + dz * dz;
        if (q > 0.30 || q < 1e-9) continue;
        const f = 0.0016 / q * cool;
        a.x += dx * f; a.y += dy * f; a.z += dz * f;
        b.x -= dx * f; b.y -= dy * f; b.z -= dz * f;
      }
    }
    for (const p of P) {
      const h = hub[d.nodes[p.i].community]; if (!h) continue;
      p.x += (h[0] - p.x) * 0.02; p.y += (h[1] - p.y) * 0.02; p.z += (h[2] - p.z) * 0.02;
    }
  }
  let mx = 0, my = 0, mz = 0;
  for (const p of P) { mx += p.x; my += p.y; mz += p.z; }
  mx /= Math.max(1, P.length); my /= Math.max(1, P.length); mz /= Math.max(1, P.length);
  let span = 1e-6;
  for (const p of P) { p.x -= mx; p.y -= my; p.z -= mz; span = Math.max(span, Math.abs(p.x), Math.abs(p.y), Math.abs(p.z)); }
  for (const p of P) { p.x /= span; p.y /= span; p.z /= span; }
  d.pos3 = P;                                              // unit cube, centred
  d.px = new Array(P.length); d.py = new Array(P.length);   // last projection, for hit tests
  d.pz = new Array(P.length);
}

function project(d, W, H) {
  const S = Math.min(W, H) * 0.46 * GCAM.k, cx = W / 2 + GCAM.x, cy = H / 2 + GCAM.y;
  const cy2 = Math.cos(GCAM.yaw), sy = Math.sin(GCAM.yaw);
  const cp = Math.cos(GCAM.pitch), sp = Math.sin(GCAM.pitch);
  const P = d.pos3;
  for (let i = 0; i < P.length; i++) {
    const p = P[i];
    const x1 = p.x * cy2 - p.z * sy, z1 = p.x * sy + p.z * cy2;   // yaw
    const y2 = p.y * cp - z1 * sp, z2 = p.y * sp + z1 * cp;        // pitch
    const persp = 1 / (1.55 - z2 * 0.75);                          // near grows, far shrinks
    d.px[i] = cx + x1 * S * persp * 1.55;
    d.py[i] = cy + y2 * S * persp * 1.55;
    d.pz[i] = z2;
  }
}

function paint() {
  const d = GDATA; if (!d || !d.pos3) return;
  const cv = $("g-canvas"), X = cv.getContext("2d");
  const dpr = window.devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
  if (!W || !H) return;
  if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) {
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
  }
  X.setTransform(dpr, 0, 0, dpr, 0, 0);
  X.clearRect(0, 0, W, H);
  project(d, W, H);
  const live = d.nodes.map((n, i) => i).filter(i => GVIS.has(d.nodes[i].community));
  const order = live.slice().sort((a, b) => d.pz[a] - d.pz[b]);        // far first, near on top
  X.lineWidth = 0.7;
  for (const [s, t] of (d.edges || [])) {
    if (!GVIS.has(d.nodes[s].community) || !GVIS.has(d.nodes[t].community)) continue;
    const depth = (d.pz[s] + d.pz[t]) / 2;
    X.strokeStyle = `rgba(150,164,186,${(0.10 + 0.22 * (depth + 1) / 2).toFixed(3)})`;
    X.beginPath(); X.moveTo(d.px[s], d.py[s]); X.lineTo(d.px[t], d.py[t]); X.stroke();
  }
  for (const i of order) {
    const n = d.nodes[i], depth = (d.pz[i] + 1) / 2;                   // 0 far, 1 near
    const r = (1.7 + Math.min(5.2, (n.degree || 0) * 0.85)) * (0.62 + 0.62 * depth);
    X.globalAlpha = 0.42 + 0.58 * depth;
    X.fillStyle = gc(n.community);
    X.beginPath(); X.arc(d.px[i], d.py[i], r, 0, Math.PI * 2); X.fill();
  }
  X.globalAlpha = 1;
  const seen = live.length, all = d.nodes.length;
  $("g-cap").textContent = `${seen === all ? all : seen + " of " + all} nodes drawn · ${(d.edges || []).length.toLocaleString()} edges`
    + ` · drag to orbit, wheel to zoom, click a node for the fact`;
}

// Communities as a browsable index: every fact in the group, in a scroll box, each one a link
// into the Text view. The graph is the map; the ledger is the ground truth under it.
function renderCommunities(d) {
  const ul = $("g-list");
  ul.innerHTML = "";
  const head = document.createElement("li");
  head.className = "fact";
  head.innerHTML = `<div class="body"><label style="cursor:pointer"><input type="checkbox" id="g-all" checked>
      all ${d.communities.length} communities · ${(d.nodes || []).length} nodes</label></div>`;
  head.querySelector("input").onchange = ev => {
    GVIS.clear();
    if (ev.target.checked) (d.communities || []).forEach(c => GVIS.add(c.id));
    ul.querySelectorAll("input[data-comm]").forEach(b => { b.checked = ev.target.checked; });
    paint();
  };
  ul.append(head);
  const by = {};
  (d.nodes || []).forEach((n, i) => { (by[n.community] = by[n.community] || []).push([n, i]); });
  for (const c of d.communities) {
    const members = (by[c.id] || []).slice().sort((a, b) => b[0].degree - a[0].degree);
    const li = document.createElement("li");
    li.className = "fact";
    const box = document.createElement("div");
    box.className = "txt";
    box.style.maxHeight = "150px";
    members.forEach(([n, i]) => {
      const row = document.createElement("a");
      row.href = "#";
      row.textContent = n.label;
      row.style.cssText = "display:block;color:inherit;text-decoration:none;cursor:pointer;padding:1px 0";
      row.title = `community ${n.community} · degree ${n.degree}${n.fact ? " · fact #" + n.fact : ""}`;
      row.onclick = e => { e.preventDefault(); focusNode(i); };
      box.append(row);
    });
    const body = document.createElement("div");
    body.className = "body";
    const title = document.createElement("div");
    title.className = "meta";
    title.innerHTML = `<input type="checkbox" data-comm="${c.id}" checked>
      <span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${gc(c.id)};margin:0 5px"></span>
      <strong style="font-weight:600">${c.size} node${c.size === 1 ? "" : "s"}</strong>
      · community ${c.id}${c.label ? " · " + esc(c.label) : ""}`;
    title.querySelector("input").onchange = ev => {
      const id = Number(ev.target.dataset.comm);
      ev.target.checked ? GVIS.add(id) : GVIS.delete(id);
      paint();
    };
    body.append(title, box);
    li.append(body);
    ul.append(li);
  }
}

function focusNode(i) {
  const n = GDATA.nodes[i];
  $("g-cap").innerHTML = "";
  $("g-cap").textContent = `${n.label} · community ${n.community} · degree ${n.degree}`
    + (n.fact ? ` · fact #${n.fact}` : "");
  if (n.label) { $("q").value = n.label.slice(0, 70); show($("q").value); tier("t3"); }
}

// camera: drag orbits, wheel zooms toward the pointer, resize repaints
$("g-canvas").onwheel = ev => {
  ev.preventDefault();
  const r = ev.target.getBoundingClientRect();
  const mx = ev.clientX - r.left - r.width / 2, my = ev.clientY - r.top - r.height / 2;
  const k = Math.min(6, Math.max(0.45, GCAM.k * (ev.deltaY < 0 ? 1.15 : 1 / 1.15)));
  GCAM.x = mx - (mx - GCAM.x) * (k / GCAM.k);
  GCAM.y = my - (my - GCAM.y) * (k / GCAM.k);
  GCAM.k = k;
  paint();
};
let GDRAG = null;
$("g-canvas").onpointerdown = ev => { GDRAG = [ev.clientX, ev.clientY, GCAM.yaw, GCAM.pitch, GCAM.x, GCAM.y]; ev.target.setPointerCapture(ev.pointerId); };
$("g-canvas").onpointerup = () => { GDRAG = null; };
$("g-canvas").onpointermove = ev => {
  const cv = ev.target;
  if (GDRAG) {
    const dx = ev.clientX - GDRAG[0], dy = ev.clientY - GDRAG[1];
    if (ev.shiftKey) { GCAM.x = GDRAG[4] + dx; GCAM.y = GDRAG[5] + dy; }
    else { GCAM.yaw = GDRAG[2] + dx * 0.006; GCAM.pitch = Math.max(-1.5, Math.min(1.5, GDRAG[3] + dy * 0.006)); }
    paint();
    return;
  }
  const d = GDATA; if (!d || !d.px) return;
  const r = cv.getBoundingClientRect(), mx = ev.clientX - r.left, my = ev.clientY - r.top;
  let best = 130, hit = -1;
  for (let i = 0; i < d.nodes.length; i++) {
    if (!GVIS.has(d.nodes[i].community)) continue;
    const q = (d.px[i] - mx) ** 2 + (d.py[i] - my) ** 2;
    if (q < best) { best = q; hit = i; }
  }
  const n = hit >= 0 ? d.nodes[hit] : null;
  cv.style.cursor = n ? "pointer" : "grab";
  cv.title = n ? `${n.label}\ncommunity ${n.community} · degree ${n.degree}${n.fact ? " · fact #" + n.fact : ""}` : "";
};
// Double-click, not single. Orbiting the camera is a drag that ends on a node, and a single
// click fired the jump through the whole gesture (owner's report, 2026-11-15). Hover previews,
// single click selects the node into the caption line, and the jump into the Text view needs a
// deliberate double-click.
$("g-canvas").ondblclick = ev => {
  const d = GDATA; if (!d || !d.px) return;
  const r = ev.target.getBoundingClientRect(), mx = ev.clientX - r.left, my = ev.clientY - r.top;
  let best = 130, hit = -1;
  for (let i = 0; i < d.nodes.length; i++) {
    if (!GVIS.has(d.nodes[i].community)) continue;
    const q = (d.px[i] - mx) ** 2 + (d.py[i] - my) ** 2;
    if (q < best) { best = q; hit = i; }
  }
  if (hit >= 0) focusNode(hit);
};
window.addEventListener("resize", () => paint());

async function graphPass(merge) {
  $("g-build").disabled = $("g-merge").disabled = true;
  try {
    await api("/memory", { op: "graph", action: merge ? "update" : "build" });
    if (!GPOLL) GPOLL = setInterval(graphTick, 15000);
    graphStatus();
  } catch (e) { note(e.message, true); $("g-build").disabled = $("g-merge").disabled = false; }
}
$("g-build").onclick = () => graphPass(false);
$("g-merge").onclick = () => graphPass(true);
show("");
