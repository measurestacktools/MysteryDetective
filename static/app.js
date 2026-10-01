const $ = (id) => document.getElementById(id);
const state = { case: null };

function escapeHtml(s) {
  return String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  let body = {};
  try { body = await r.json(); } catch { body = { ok: false, error: "Bad server response." }; }
  if (!r.ok && body && body.ok === undefined) return { ok: false, error: body.error || ("HTTP " + r.status) };
  return body;
}

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    $("status-pill").textContent = `${s.has_key ? "key OK" : "no key"} · ${s.has_case ? "case open" : "no case"}`;
  } catch { $("status-pill").textContent = "server offline"; }
}

function showBoards(d) {
  state.case = d;
  for (const id of ["case", "board", "suspects", "evidence", "tools"]) $(id).hidden = false;
  $("btn-replay").hidden = false;
  $("case-title").textContent = d.title || "Untitled case";
  $("case-intro").textContent = d.intro || "";
  $("case-brief").textContent = d.brief || "";
  $("timeline").innerHTML = (d.timeline || []).map((t) => `<li><b>${escapeHtml(t.time)}</b> — ${escapeHtml(t.event)}</li>`).join("");
  $("suspect-list").innerHTML = (d.suspects || []).map((s) => `<li><b>${escapeHtml(s.name)}</b> <span class="tag">motive</span><br><span class="muted">${escapeHtml(s.motive)}</span></li>`).join("");
  $("ev-list").innerHTML = (d.evidence || []).map((e) => `<li><button type="button" class="ev-btn" data-id="${escapeHtml(e.id)}">${escapeHtml(e.id)}: ${escapeHtml(e.title)}</button> <span class="muted">@ ${escapeHtml(e.location)}</span></li>`).join("");
  $("loc-list").innerHTML = (d.locations || []).map((l) => `<li><button type="button" class="loc-btn" data-n="${escapeHtml(l.name)}">${escapeHtml(l.name)}</button></li>`).join("");
  const opts = (d.suspects || []).map((s) => `<option>${escapeHtml(s.name)}</option>`).join("");
  $("iq-suspect").innerHTML = opts; $("acc-suspect").innerHTML = opts;
  document.querySelectorAll(".ev-btn").forEach((b) => { b.onclick = () => inspectEv(b.dataset.id); });
  document.querySelectorAll(".loc-btn").forEach((b) => { b.onclick = () => searchLoc(b.dataset.n); });
  updateProgress(d.progress);
  if (d.casefile) renderBoard(d.casefile, d);
}

function renderBoard(cf, d) {
  if (!cf || !$("board")) return;
  $("board").hidden = false;
  const pl = cf.probes_left ?? d?.progress?.probes_left;
  const al = cf.accusations_left ?? d?.progress?.accusations_left;
  if ($("probes-x")) $("probes-x").textContent = `${pl} left (${cf.probes_used ?? 0}/${cf.max_probes ?? 12} used)`;
  if ($("acc-x")) $("acc-x").textContent = `${al} left`;
  const found = (cf.evidence || []).filter((e) => e.found);
  $("board-found").innerHTML = found.length
    ? found.map((e) => `<li>📌 <b>${escapeHtml(e.id)}</b> — ${escapeHtml(e.title)}</li>`).join("")
    : `<li class="muted">Nothing pinned yet — inspect evidence to pin it here.</li>`;
  $("board-timeline").innerHTML = (cf.timeline || []).length
    ? cf.timeline.map((t) => `<li>#${escapeHtml(t.n)} — ${escapeHtml(t.event)}</li>`).join("")
    : `<li class="muted">No verified events yet.</li>`;
  const alibis = cf.alibis || {};
  $("board-alibis").innerHTML = Object.keys(alibis).length
    ? Object.entries(alibis).map(([n, s]) => `<li><b>${escapeHtml(n)}</b> — ${escapeHtml(s)}</li>`).join("")
    : `<li class="muted">No alibis checked.</li>`;
}

function updateProgress(p) {
  if (!p) return;
  $("progress").hidden = false;
  $("clues-x").textContent = `${p.clues_found}/${p.clues_total}`;
  $("q-x").textContent = `${p.suspects_questioned}`;
  if (p.probes_left !== undefined || p.accusations_left !== undefined) {
    $("progress").innerHTML =
      `Clues <b id="clues-x">${p.clues_found}/${p.clues_total}</b> · Questioned <b id="q-x">${p.suspects_questioned}</b>` +
      (p.probes_left !== undefined ? ` · Probes <b>${p.probes_left} left</b>` : "") +
      (p.accusations_left !== undefined ? ` · Accusations <b>${p.accusations_left} left</b>` : "");
  }
}

function setBusy(btn, busy, label) {
  if (!btn) return;
  btn.disabled = !!busy;
  if (label !== undefined) btn.dataset.label = btn.textContent;
  if (busy) { btn.dataset.label = btn.textContent; btn.textContent = label || "Working…"; }
  else if (btn.dataset.label) { btn.textContent = btn.dataset.label; }
}

async function restoreState() {
  try {
    const d = await api("/api/state");
    if (d && d.ok && d.has_case) {
      $("setup-msg").textContent = "Restored the open case from the server file.";
      showBoards(d);
    }
  } catch { /* offline: stay on setup */ }
}

async function newCase() {
  const btn = $("btn-new-case");
  $("setup-msg").textContent = "Opening a new case…";
  setBusy(btn, true, "Opening…");
  try {
    const d = await api("/api/new-case", { method: "POST", body: JSON.stringify({ difficulty: $("difficulty").value }) });
    if (!d.ok) { $("setup-msg").textContent = "Error: " + (d.error || "unknown"); return; }
    $("setup-msg").textContent = d.offline ? "Playing offline (no key) — add a key for full AI." : "Case opened. Investigate!";
    for (const id of ["iq-out", "ev-out", "loc-out", "ask-out", "acc-out", "reveal-out"]) { $(id).textContent = ""; }
    $("acc-reason").value = "";
    showBoards(d);
  } catch (e) {
    $("setup-msg").textContent = "Error: server unreachable. Is uvicorn running on 8014?";
  } finally {
    setBusy(btn, false);
  }
}

async function inspectEv(id) {
  $("ev-out").textContent = "Checking evidence…";
  try {
    const d = await api("/api/inspect", { method: "POST", body: JSON.stringify({ evidence_id: id }) });
    if (!d.ok) { $("ev-out").textContent = "Error: " + d.error; if (d.casefile) renderBoard(d.casefile, d); return; }
    $("ev-out").textContent = `${d.evidence.id} — ${d.evidence.title} @ ${d.evidence.location}\n${d.evidence.detail}`;
    updateProgress(d.progress);
    if (d.casefile) renderBoard(d.casefile, d);
  } catch { $("ev-out").textContent = "Error: server unreachable."; }
}

async function searchLoc(n) {
  $("loc-out").textContent = "Searching…";
  try {
    const d = await api("/api/search", { method: "POST", body: JSON.stringify({ location: n }) });
    if (!d.ok) { $("loc-out").textContent = "Error: " + d.error; if (d.casefile) renderBoard(d.casefile, d); return; }
    $("loc-out").textContent = `${d.location} clues:\n- ` + (d.clues || []).join("\n- ");
    updateProgress(d.progress);
    if (d.casefile) renderBoard(d.casefile, d);
  } catch { $("loc-out").textContent = "Error: server unreachable."; }
}

function onEnter(inputEl, fn) {
  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); fn(); }
  });
}

$("btn-new-case").onclick = newCase;
$("btn-replay").onclick = newCase;

$("btn-iq").onclick = async () => {
  const q = $("iq-q").value.trim();
  if (!q) { $("iq-out").textContent = "Error: type a question first."; $("iq-q").focus(); return; }
  const btn = $("btn-iq");
  setBusy(btn, true, "Asking…");
  try {
    const d = await api("/api/interrogate", { method: "POST", body: JSON.stringify({ suspect: $("iq-suspect").value, question: q }) });
    $("iq-out").textContent = d.ok ? `${d.suspect}: ${d.answer}` : "Error: " + d.error;
    if (d.progress) updateProgress(d.progress);
    if (d.casefile) renderBoard(d.casefile, d);
  } catch { $("iq-out").textContent = "Error: server unreachable."; }
  finally { setBusy(btn, false); }
};

$("btn-ask").onclick = async () => {
  const q = $("ask-q").value.trim();
  if (!q) { $("ask-out").textContent = "Error: type what you want a hint about."; $("ask-q").focus(); return; }
  const btn = $("btn-ask");
  setBusy(btn, true, "Thinking…");
  try {
    const d = await api("/api/ask", { method: "POST", body: JSON.stringify({ question: q }) });
    $("ask-out").textContent = d.ok ? d.hint : "Error: " + d.error;
  } catch { $("ask-out").textContent = "Error: server unreachable."; }
  finally { setBusy(btn, false); }
};

$("btn-accuse").onclick = async () => {
  const reason = $("acc-reason").value.trim();
  if (!reason) { $("acc-out").textContent = "Error: write your reasoning first — the captain won't sign a blank charge."; $("acc-reason").focus(); return; }
  const btn = $("btn-accuse");
  setBusy(btn, true, "Filing…");
  try {
    const d = await api("/api/accuse", { method: "POST", body: JSON.stringify({ suspect: $("acc-suspect").value, reasoning: reason }) });
    $("acc-out").textContent = d.ok ? (d.win ? "CASE CLOSED — " + d.message : " lead gone cold — " + d.message) : "Error: " + d.error;
    if (d.progress) updateProgress(d.progress);
    if (d.casefile) renderBoard(d.casefile, d);
  } catch { $("acc-out").textContent = "Error: server unreachable."; }
  finally { setBusy(btn, false); }
};

$("btn-reveal").onclick = async () => {
  const btn = $("btn-reveal");
  setBusy(btn, true, "Opening…");
  try {
    const d = await api("/api/reveal", { method: "POST" });
    $("reveal-out").textContent = d.ok ? `Culprit: ${d.culprit}\n${d.solution_summary}\n\n${d.explanation}` : "Error: " + d.error;
  } catch { $("reveal-out").textContent = "Error: server unreachable."; }
  finally { setBusy(btn, false); }
};

onEnter($("iq-q"), () => $("btn-iq").click());
onEnter($("ask-q"), () => $("btn-ask").click());
onEnter($("acc-reason"), () => $("btn-accuse").click());

// settings modal — frontend NEVER stores/sends keys except POST /api/key body
$("btn-settings").onclick = () => { $("settings-modal").hidden = false; };
$("btn-close-settings").onclick = () => { $("settings-modal").hidden = true; };
$("settings-modal").addEventListener("click", (e) => { if (e.target === $("settings-modal")) $("settings-modal").hidden = true; });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") $("settings-modal").hidden = true; });
$("btn-save-key").onclick = async () => {
  const v = $("key-input").value.trim();
  if (!v) { $("key-msg").textContent = "Paste a key first."; return; }
  $("key-msg").textContent = "Verifying…";
  try {
    const d = await api("/api/key", { method: "POST", body: JSON.stringify({ key: v }) });
    $("key-msg").textContent = d.ok ? "Key verified and saved (server memory only)." : "Error: " + d.error;
  } catch { $("key-msg").textContent = "Error: server unreachable."; }
  $("key-input").value = "";
  refreshStatus();
};
$("btn-del-key").onclick = async () => {
  try { await api("/api/key", { method: "DELETE" }); } catch { /* ignore */ }
  $("key-msg").textContent = "Key forgotten.";
  refreshStatus();
};

// notes: localStorage, user notes only — never the key; private-mode safe
try {
  $("notes").value = localStorage.getItem("md_notes") || "";
} catch { /* storage blocked */ }
$("notes").addEventListener("input", (e) => {
  try { localStorage.setItem("md_notes", e.target.value); } catch { /* ignore */ }
});

refreshStatus();
restoreState();
