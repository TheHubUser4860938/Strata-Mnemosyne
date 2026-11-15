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
// view polls it through op=graph. The drawing is a dependency-free canvas: a force layout run
// once and cached, normalised into the box, with wheel zoom, drag pan, and a legend that
// toggles communities.
let GPOLL = null, GDATA = null, GSTATE = null;
const GVIS = new Set();
let GVIEW = { k: 1, x: 0, y: 0 };
const gc = c => `hsl(${(c * 47) % 360} 62% 62%)`;

async function graphStatus() {
  const d = await api("/memory", { op: "graph" });
  GSTATE = d.graph || (d.result && d.result.graph) || {};
  const s = GSTATE, p = s.progress || {};
  $("g-nodes").textContent = (s.nodes || 0).toLocaleString();
  $("g-edges").textContent = (s.edges || 0).toLocaleString();
  $("g-comm").textContent = (s.communities || 0).toLocaleString();
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
  if (!s.running) { clearInterval(GPOLL); GPOLL = null; graphView(true); }
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
      GDATA = d; GDATA.stamp = s.built; layout(GDATA);
      GVIS.clear(); (d.communities || []).forEach(c => GVIS.add(c.id));
      renderLegend(d);
    }
    paint();
  } catch (e) { note(e.message, true); }
}

// Run ONCE per graph, then cached on GDATA.pos. Positions are normalised into a centred unit
// square: an earlier version drew raw force output and a strong repulsion threw nodes off-canvas.
function layout(d) {
  const hub = {}, N = d.nodes.length;
  (d.communities || []).forEach((c, i) => {
    const a = (i / Math.max(1, d.communities.length)) * Math.PI * 2;
    hub[c.id] = [Math.cos(a) * 0.82, Math.sin(a) * 0.82];
  });
  const P = d.nodes.map((n, i) => {
    const h = hub[n.community] || [0, 0], a = i * 2.399963
      , r = 0.06 + 0.5 * Math.sqrt(i / Math.max(1, N));
    return { x: h[0] + Math.cos(a) * r, y: h[1] + Math.sin(a) * r, i };
  });
  for (let it = 0; it < 300; it++) {
    const cool = 1 - it / 340;
    for (const [s, t] of (d.edges || [])) {
      const a = P[s], b = P[t]; if (!a || !b) continue;
      const dx = b.x - a.x, dy = b.y - a.y, dist = Math.hypot(dx, dy) || 1e-6;
      const f = (dist - 0.11) * 0.02 * cool;
      a.x += dx * f; a.y += dy * f; b.x -= dx * f; b.y -= dy * f;
    }
    for (let i = 0; i < P.length; i++) {
      const a = P[i];
      for (let j = i + 1; j < P.length; j++) {
        const b = P[j], dx = a.x - b.x, dy = a.y - b.y, q = (dx * dx + dy * dy) || 1e-6;
        if (q > 0.25) continue;
        const f = 0.0009 / q * cool;
        a.x += dx * f; a.y += dy * f; b.x -= dx * f; b.y -= dy * f;
      }
    }
    for (const p of P) {
      const h = hub[d.nodes[p.i].community]; if (!h) continue;
      p.x += (h[0] - p.x) * 0.02; p.y += (h[1] - p.y) * 0.02;
    }
  }
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const p of P) { x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y); x1 = Math.max(x1, p.x); y1 = Math.max(y1, p.y); }
  const side = Math.max(x1 - x0, y1 - y0) || 1;
  const mx = (x0 + x1) / 2, my = (y0 + y1) / 2;
  d.pos = P.map(p => [(p.x - mx) / side, (p.y - my) / side]);
  GVIEW = { k: 1, x: 0, y: 0 };
}

function renderLegend(d) {
  const ul = $("g-list");
  ul.innerHTML = "";
  const head = document.createElement("li");
  head.className = "fact";
  head.innerHTML = `<div class="body"><label style="cursor:pointer"><input type="checkbox" id="g-all" checked> all ${d.communities.length} communities</label></div>`;
  head.querySelector("input").onchange = ev => {
    GVIS.clear();
    if (ev.target.checked) (d.communities || []).forEach(c => GVIS.add(c.id));
    ul.querySelectorAll("input[data-comm]").forEach(b => { b.checked = ev.target.checked; });
    paint();
  };
  ul.append(head);
  for (const c of d.communities) {
    const li = document.createElement("li");
    li.className = "fact";
    li.innerHTML = `<div class="body"><div class="txt" style="max-height:none">
        <input type="checkbox" data-comm="${c.id}" checked>
        <span style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${gc(c.id)};margin:0 5px"></span>${esc(c.label)}</div>
      <div class="meta">${c.size} node${c.size === 1 ? "" : "s"}</div></div>`;
    li.querySelector("input").onchange = ev => {
      const id = Number(ev.target.dataset.comm);
      ev.target.checked ? GVIS.add(id) : GVIS.delete(id);
      paint();
    };
    ul.append(li);
  }
}

function paint() {
  const d = GDATA; if (!d || !d.pos) return;
  const cv = $("g-canvas"), X = cv.getContext("2d");
  const dpr = window.devicePixelRatio || 1, W = cv.clientWidth, H = cv.clientHeight;
  if (!W || !H) return;
  if (cv.width !== Math.round(W * dpr) || cv.height !== Math.round(H * dpr)) {
    cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
  }
  X.setTransform(dpr, 0, 0, dpr, 0, 0);
  X.clearRect(0, 0, W, H);
  const S = Math.min(W, H) * 0.92 * GVIEW.k, cx = W / 2 + GVIEW.x, cy = H / 2 + GVIEW.y;
  const at = i => [cx + d.pos[i][0] * S, cy + d.pos[i][1] * S];
  X.lineWidth = 0.7;
  for (const [s, t] of (d.edges || [])) {
    if (!GVIS.has(d.nodes[s].community) || !GVIS.has(d.nodes[t].community)) continue;
    const a = at(s), b = at(t);
    X.strokeStyle = "rgba(160,172,190,.28)";
    X.beginPath(); X.moveTo(a[0], a[1]); X.lineTo(b[0], b[1]); X.stroke();
  }
  for (let i = 0; i < d.nodes.length; i++) {
    const n = d.nodes[i];
    if (!GVIS.has(n.community)) continue;
    const p = at(i);
    X.fillStyle = gc(n.community);
    X.beginPath(); X.arc(p[0], p[1], 2.2 + Math.min(5.5, (n.degree || 0) * 0.9), 0, Math.PI * 2); X.fill();
  }
  $("g-cap").textContent = `${d.nodes.length.toLocaleString()} nodes · ${(d.edges || []).length.toLocaleString()} edges drawn`
    + ` of ${d.nodes_total ? d.nodes_total.toLocaleString() + " nodes, " : ""}${(d.links_total || 0).toLocaleString()} edges in the graph`
    + ` · colour is the community, size is degree`;
}

// wheel zooms about the cursor, drag pans; the transform lives in GVIEW and paint() re-applies
$("g-canvas").onwheel = ev => {
  ev.preventDefault();
  const r = ev.target.getBoundingClientRect();
  const mx = ev.clientX - r.left - r.width / 2, my = ev.clientY - r.top - r.height / 2;
  const k = Math.min(12, Math.max(0.4, GVIEW.k * (ev.deltaY < 0 ? 1.15 : 1 / 1.15)));
  GVIEW.x = mx - (mx - GVIEW.x) * (k / GVIEW.k);
  GVIEW.y = my - (my - GVIEW.y) * (k / GVIEW.k);
  GVIEW.k = k;
  paint();
};
let GPAN = null;
$("g-canvas").onpointerdown = ev => { GPAN = [ev.clientX, ev.clientY, GVIEW.x, GVIEW.y]; ev.target.setPointerCapture(ev.pointerId); };
$("g-canvas").onpointerup = () => { GPAN = null; };
$("g-canvas").onpointermove = ev => {
  const cv = ev.target;
  if (GPAN) { GVIEW.x = GPAN[2] + (ev.clientX - GPAN[0]); GVIEW.y = GPAN[3] + (ev.clientY - GPAN[1]); paint(); return; }
  const d = GDATA; if (!d || !d.pos) return;
  const r = cv.getBoundingClientRect();
  const mx = ev.clientX - r.left, my = ev.clientY - r.top;
  const S = Math.min(r.width, r.height) * 0.92 * GVIEW.k;
  let best = 120, hit = -1;
  for (let i = 0; i < d.nodes.length; i++) {
    if (!GVIS.has(d.nodes[i].community)) continue;
    const px = r.width / 2 + GVIEW.x + d.pos[i][0] * S, py = r.height / 2 + GVIEW.y + d.pos[i][1] * S;
    const q = (px - mx) ** 2 + (py - my) ** 2;
    if (q < best) { best = q; hit = i; }
  }
  const n = hit >= 0 ? d.nodes[hit] : null;
  cv.style.cursor = n ? "pointer" : "grab";
  cv.title = n ? `${n.label}\ncommunity ${n.community} · degree ${n.degree}${n.fact ? ` · fact #${n.fact}` : ""}` : "";
};
$("g-canvas").onclick = ev => {
  const d = GDATA; if (!d || !d.pos) return;
  const r = ev.target.getBoundingClientRect();
  const mx = ev.clientX - r.left, my = ev.clientY - r.top;
  const S = Math.min(r.width, r.height) * 0.92 * GVIEW.k;
  let best = 120, hit = -1;
  for (let i = 0; i < d.nodes.length; i++) {
    if (!GVIS.has(d.nodes[i].community)) continue;
    const px = r.width / 2 + GVIEW.x + d.pos[i][0] * S, py = r.height / 2 + GVIEW.y + d.pos[i][1] * S;
    const q = (px - mx) ** 2 + (py - my) ** 2;
    if (q < best) { best = q; hit = i; }
  }
  if (hit < 0) return;
  const n = d.nodes[hit];
  $("g-cap").innerHTML = `<b>${esc(n.label)}</b> · community ${n.community} · degree ${n.degree}`
    + (n.fact ? ` · <a href="#" id="g-jump">open fact #${n.fact}</a>` : "");
  const jump = $("g-jump");
  if (jump) jump.onclick = e => { e.preventDefault(); $("q").value = String(n.fact); show(String(n.fact)); tier("t3"); };
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
graphView();
show("");
