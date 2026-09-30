const $ = (id) => document.getElementById(id);
const state = { case: null };

async function api(path, opts = {}) {
  const r = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  return r.json();
}
async function refreshStatus() {
  try {
    const s = await api("/api/status");
    $("status-pill").textContent = `${s.has_key ? "key ✓" : "no key"} · ${s.has_case ? "case open" : "no case"} · ${s.model}`;
  } catch { $("status-pill").textContent = "server offline"; }
}
function showBoards(d) {
  state.case = d;
  for (const id of ["case", "suspects", "evidence", "tools"]) $(id).hidden = false;
  $("btn-replay").hidden = false;
  $("case-title").textContent = d.title;
  $("case-intro").textContent = d.intro;
  $("case-brief").textContent = d.brief || "";
  $("timeline").innerHTML = (d.timeline || []).map((t) => `<li><b>${t.time}</b> — ${t.event}</li>`).join("");
  $("suspect-list").innerHTML = d.suspects.map((s) => `<li><b>${s.name}</b> <span class="tag">motive</span><br><span class="muted">${s.motive}</span></li>`).join("");
  $("ev-list").innerHTML = d.evidence.map((e) => `<li><button class="ev-btn" data-id="${e.id}">${e.id}: ${e.title}</button> <span class="muted">@ ${e.location}</span></li>`).join("");
  $("loc-list").innerHTML = d.locations.map((l) => `<li><button class="loc-btn" data-n="${l.name}">${l.name}</button></li>`).join("");
  const opts = d.suspects.map((s) => `<option>${s.name}</option>`).join("");
  $("iq-suspect").innerHTML = opts; $("acc-suspect").innerHTML = opts;
  document.querySelectorAll(".ev-btn").forEach((b) => b.onclick = () => inspectEv(b.dataset.id));
  document.querySelectorAll(".loc-btn").forEach((b) => b.onclick = () => searchLoc(b.dataset.n));
  updateProgress(d.progress);
}
function updateProgress(p) {
  if (!p) return;
  $("progress").hidden = false;
  $("clues-x").textContent = `${p.clues_found}/${p.clues_total}`;
  $("q-x").textContent = `${p.suspects_questioned}`;
}
async function newCase() {
  $("setup-msg").textContent = "Opening a new case…";
  const d = await api("/api/new-case", { method: "POST", body: JSON.stringify({ difficulty: $("difficulty").value }) });
  if (!d.ok) { $("setup-msg").textContent = "Error: " + d.error; return; }
  $("setup-msg").textContent = d.offline ? "Playing offline (no key) — add a key for full AI." : "Case opened. Investigate!";
  showBoards(d);
}
async function inspectEv(id) {
  const d = await api("/api/inspect", { method: "POST", body: JSON.stringify({ evidence_id: id }) });
  if (!d.ok) { $("ev-out").textContent = "Error: " + d.error; return; }
  $("ev-out").textContent = `${d.evidence.id} — ${d.evidence.title} @ ${d.evidence.location}\n${d.evidence.detail}`;
  updateProgress(d.progress);
}
async function searchLoc(n) {
  const d = await api("/api/search", { method: "POST", body: JSON.stringify({ location: n }) });
  if (!d.ok) { $("loc-out").textContent = "Error: " + d.error; return; }
  $("loc-out").textContent = `${d.location} clues:\n- ` + d.clues.join("\n- ");
  updateProgress(d.progress);
}
$("btn-new-case").onclick = newCase;
$("btn-replay").onclick = newCase;
$("btn-iq").onclick = async () => {
  const d = await api("/api/interrogate", { method: "POST", body: JSON.stringify({ suspect: $("iq-suspect").value, question: $("iq-q").value }) });
  $("iq-out").textContent = d.ok ? `${d.suspect}: ${d.answer}` : "Error: " + d.error;
  if (d.progress) updateProgress(d.progress);
};
$("btn-ask").onclick = async () => {
  const d = await api("/api/ask", { method: "POST", body: JSON.stringify({ question: $("ask-q").value }) });
  $("ask-out").textContent = d.ok ? d.hint : "Error: " + d.error;
};
$("btn-accuse").onclick = async () => {
  const d = await api("/api/accuse", { method: "POST", body: JSON.stringify({ suspect: $("acc-suspect").value, reasoning: $("acc-reason").value || "gut feeling" }) });
  $("acc-out").textContent = d.ok ? (d.win ? "🎉 " + d.message : "❌ " + d.message) : "Error: " + d.error;
};
$("btn-reveal").onclick = async () => {
  const d = await api("/api/reveal", { method: "POST" });
  $("reveal-out").textContent = d.ok ? `Culprit: ${d.culprit}\n${d.solution_summary}\n\n${d.explanation}` : "Error: " + d.error;
};
// settings modal — frontend NEVER stores/sends keys except POST /api/key body
$("btn-settings").onclick = () => { $("settings-modal").hidden = false; };
$("btn-close-settings").onclick = () => { $("settings-modal").hidden = true; };
$("btn-save-key").onclick = async () => {
  const d = await api("/api/key", { method: "POST", body: JSON.stringify({ key: $("key-input").value }) });
  $("key-msg").textContent = d.ok ? "Key verified and saved (server memory only)." : "Error: " + d.error;
  $("key-input").value = "";
  refreshStatus();
};
$("btn-del-key").onclick = async () => {
  await api("/api/key", { method: "DELETE" });
  $("key-msg").textContent = "Key forgotten.";
  refreshStatus();
};
// notes: localStorage, user notes only — never the key
$("notes").value = localStorage.getItem("md_notes") || "";
$("notes").oninput = (e) => localStorage.setItem("md_notes", e.target.value);
refreshStatus();
