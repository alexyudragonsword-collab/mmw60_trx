/* The mmw60 results browser: navigation, data loading, the job poll and the events.
 * The page keeps the study (the form) and sends it with every request; every number it
 * shows was computed by the host.  One page, two transports (see api() in core.js). */
"use strict";
const SCREENS = ["system", "table", "row", "calibration", "array", "ay", "runs", "sources"];
const RENDER = { system: renderSystem, table: renderTable, row: renderRow, calibration: renderCalibration, array: renderArray, ay: renderAy, runs: renderRuns, sources: renderSources };
const isPhone = () => matchMedia("(max-width: 760px)").matches;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const studyKey = () => JSON.stringify(S.study);

/* ------------------------------------------------------------------ what is loaded, and for which stored result */
/* a report is the stored result picked for the study (plus, for the table's range column and the
 * SC-against-OFDM headline and item table, the array and table results): it is refetched when
 * that pick changes */
function repKey(name) {
  const sh = S.state ? S.state.shown : {}, k = m => (m ? m.id + "@" + m.at : "-"), pr = (sh.table && sh.table.part_results) || {};
  const table = sh.table ? Object.keys(pr).map(p => k(pr[p])).join("+") : "-";
  return [name === "table" ? table : k(sh[name]), ...(name === "table" ? [k(sh.array)] : name === "ay" ? [k(sh.array), table] : [])].join("|");
}
function invalidate() {
  for (const name of Object.keys(S.rep)) if (S.repStudy[name] !== repKey(name)) { delete S.rep[name]; delete S.repStudy[name]; }
  if (S.row && S.rowKey !== rowKey()) S.row = null;
  if (S.system && S.systemStudy !== sysKey()) S.system = null;
}
const sysKey = () => studyKey() + "|" + repKey("ay");
const rowKey = () => [S.sel, repKey("table"), repKey("calibration"), studyKey()].join("|");
async function loadReport(name) {
  const key = repKey(name);
  if (S.rep[name] && S.repStudy[name] === key) return false;
  const rep = await api("report", { report: name, study: S.study });
  if (rep.report && !nil(rep.report.absent_below_db)) ABSENT_DB = rep.report.absent_below_db;
  S.rep[name] = rep; S.repStudy[name] = key; return true;
}
/* fetch what the screen on show needs; true when something new arrived */
async function ensure(screen) {
  let got = false;
  const rep = async n => { if (await loadReport(n)) got = true; };
  if (screen === "table") await rep("table");
  else if (screen === "calibration") await rep("calibration");
  else if (screen === "array") { await rep("array"); await rep("table"); }
  else if (screen === "ay") await rep("ay");
  else if (screen === "system") {
    if (!S.system) { S.system = await api("system", { study: S.study }); S.systemStudy = sysKey(); got = true; }
    await rep("table");
  } else if (screen === "row" && S.sel) {
    await rep("table");
    const key = rowKey();
    if (!S.row || S.rowKey !== key) {
      S.rowErr = null;
      try { S.row = await api("row", { label: S.sel, study: S.study }); S.rowKey = key; if (!nil(S.row.absent_below_db)) ABSENT_DB = S.row.absent_below_db; } catch (e) { S.row = null; S.rowErr = e.message; }
      got = true;
    }
    if (S.row && isAy(S.row.row)) await rep("ay");
  } else if (screen === "runs") { const [r, sc] = await Promise.all([api("results"), api("selfcheck")]); if (S.state) S.state.results = r.results; S.selfcheck = sc; got = true; }
  return got;
}

/* ------------------------------------------------------------------ drawing */
function chrome() {
  if (S.version) $("engine-line").textContent = S.version.engine;
  const fp = fresh().parts, ids = S.parts ? S.parts.parts.map(p => p.id) : Object.keys(fp), stale = ids.filter(p => pstate(p) === "stale");
  $("fresh-parts").innerHTML = ids.map(p => `<i data-part="${esc(p)}" data-state="${pstate(p)}" title="${esc(pn(p))}${P_.c}${stateWord(pstate(p))}"></i>`).join("");
  const gone = ids.filter(p => pstate(p) === "missing").length;
  $("pill-fresh").classList.toggle("warn", stale.length > 0);
  $("pill-fresh-t").textContent = stale.length ? T(`${stale.length} 个部分过期`, `${stale.length} parts stale`)
    : gone ? T(`${gone} 个部分没有存着的结果`, `${gone} parts have nothing stored`) : T("结果全部新鲜", "All results fresh");
  const act = (S.jobs || []).filter(jobActive), run = act.filter(j => j.status === "running").length;
  $("pill-jobs-t").innerHTML = act.length ? `<span class="spin" style="display:inline-block;vertical-align:-1px"></span> ${T(`任务 ${run} 运行 · ${act.length - run} 排队`, `Jobs: ${run} running · ${act.length - run} queued`)}` : T("无任务", "No jobs");
  const bd = $("nav-badge"); bd.hidden = !act.length; bd.textContent = String(act.length);
  document.querySelectorAll("#bottom-nav a").forEach(a => { if (a.dataset.nav === S.screen) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current"); });
}
function render() {
  const el = $("screen-" + S.screen), same = !el.hidden && el.dataset.drawn === S.screen;
  const opens = same ? [...el.querySelectorAll("details")].map(d => d.open) : null, sx = same && el.querySelector(".sysbox") ? el.querySelector(".sysbox").scrollLeft : 0, y = scrollY;
  SCREENS.forEach(s => { const e = $("screen-" + s); e.hidden = s !== S.screen; if (s !== S.screen) { e.innerHTML = ""; delete e.dataset.drawn; } });
  let html;
  try { html = S.screen === "row" && S.rowErr ? `<div class="page"><div class="empty"><b>${esc(S.rowErr)}</b>${emptyReport("table")}</div></div>` : RENDER[S.screen](); }
  catch (e) { console.error("render " + S.screen, e); html = `<div class="page"><div class="empty"><b>${T("这一屏画不出来", "This screen could not be drawn")}</b><code>${esc(e.message)}</code></div></div>`; }
  el.innerHTML = html; el.dataset.drawn = S.screen;
  if (opens) { const ds = el.querySelectorAll("details"); if (ds.length === opens.length) ds.forEach((d, i) => { d.open = opens[i]; }); }
  drawCharts(el);
  if (sx) { const sb = el.querySelector(".sysbox"); if (sb) sb.scrollLeft = sx; }
  if (same) scrollTo(0, y);
  chrome();
}
let showSeq = 0;
async function show() {
  const seq = ++showSeq;
  render();
  try { if (await ensure(S.screen) && seq === showSeq) { render(); if (S.screen === "table" || S.screen === "row") renderForm(); } }
  catch (e) { showError(e); }
}
function go(screen, replace) {
  if (!SCREENS.includes(screen)) screen = "table";
  const changed = screen !== S.screen; S.screen = screen;
  try { history[replace ? "replaceState" : "pushState"](null, "", "#" + screen); } catch (e) { /* a WebView may refuse */ }
  if (changed) scrollTo(0, 0);
  show();
}

/* ------------------------------------------------------------------ the form: the study lives on the host */
async function refreshState(study) {
  const before = studyKey();
  const st = await api("state", study === undefined ? {} : { study });
  S.state = st; S.study = st.study; S.jobs = st.jobs;
  st.jobs.forEach(j => { if (!(j.id in S.lastJobs)) S.lastJobs[j.id] = j.status; });
  invalidate();
  if (before !== studyKey() || study !== undefined || !$("form").contains(document.activeElement)) renderForm();
  chrome();
}
async function setStudy(next, knobId) {
  try { await refreshState(next); S.knobErr = {}; renderForm(); await show(); }
  catch (e) { if (knobId) { S.knobErr = { [knobId]: e.message }; renderForm(); } showError(e); }      // the previous study is kept
}
function toggleForm(open) {
  const f = $("form"); open = open === undefined ? f.hidden : open;
  f.hidden = !open; document.body.classList.toggle("form-open", open); $("nav-form").setAttribute("aria-expanded", String(open));
  if (open) renderForm();
  setTimeout(() => drawCharts($("screen-" + S.screen)), 60);
}

/* ------------------------------------------------------------------ jobs */
const jobDone = s => s === "done" || s === "error" || s === "cancelled";
function drawQueue() { chrome(); const q = $("runs-queue"), c = $("selfcheck-run"); if (q && S.screen === "runs") { q.innerHTML = runsQueue(); if (c) c.innerHTML = selfcheckRun(); } }
/* Poll once a second while a job is queued or running, and not otherwise.  A submit sets
 * pollAgain, so a poll that saw the queue idle just before it does not stop. */
async function poll() {
  if (S.polling) { S.pollAgain = true; return; }
  S.polling = true;
  try {
    for (;;) {
      S.pollAgain = false;
      const j = await api("jobs");
      const ended = j.jobs.filter(x => jobDone(x.status) && S.lastJobs[x.id] !== undefined && S.lastJobs[x.id] !== x.status);
      j.jobs.forEach(x => { S.lastJobs[x.id] = x.status; });
      S.jobs = j.jobs;
      if (ended.length) {
        ended.filter(x => x.status === "error").forEach(x => showError(jn(x.job) + P_.c + String(x.error || "").trim().split("\n").pop()));
        ended.filter(x => x.status === "done").forEach(x => toast(jn(x.job) + P_.c + T("算完了，结果已存", "done, the result is stored")));
        S.parts = await api("parts");      /* a finished job leaves its own duration, a self-check the host's speed */
        await refreshState(); await show();
      } else drawQueue();
      if (!S.jobs.some(jobActive) && !S.pollAgain) break;
      await sleep(1000);
    }
  } catch (e) { showError(e); } finally { S.polling = false; }
}
async function runJob(job) {
  try {
    const r = await api("run", { job, study: S.study });
    S.lastJobs[r.job.id] = r.job.status; S.jobs = [...(S.jobs || []).filter(x => x.id !== r.job.id), r.job]; S.pollAgain = true;
    toast(T("已排队", "Queued") + P_.c + jn(job)); drawQueue(); poll();
  } catch (e) { showError(e); }
}
async function cancelJob(id) { try { await api("jobs/" + id + "/cancel", {}); } catch (e) { showError(e); } S.pollAgain = true; poll(); }
async function deleteResult(id) { try { await api("results/" + id + "/delete", {}); await refreshState(); await show(); } catch (e) { showError(e); } }

/* ------------------------------------------------------------------ events */
document.addEventListener("click", e => {
  const nav = e.target.closest("a[data-nav]");
  if (nav) { e.preventDefault(); go(nav.dataset.nav); return; }
  const cp = e.target.closest("[data-copy]");
  if (cp) { const done = () => { cp.textContent = T("已复制", "copied"); }; try { navigator.clipboard.writeText(cp.dataset.copy).then(done, () => {}); } catch (err) { /* no clipboard */ } return; }
  if (e.target.closest("#toast")) { $("toast").hidden = true; return; }
  const tg = e.target.closest(".tag[data-k], .stag[data-k]");
  if (tg && tg.dataset.k) { showPop(tg, true); e.stopPropagation(); return; }
  if (!e.target.closest(".pop")) hidePop(true);
  const b = e.target.closest("[data-act]"); if (!b) return;
  if (b.tagName === "A") e.preventDefault();
  const act = b.dataset.act, v = b.dataset.v;
  if (act === "go") go(v);
  else if (act === "form") toggleForm();
  else if (act === "lang") { S.lang = S.lang === "zh" ? "en" : "zh"; try { localStorage.setItem("mmw60.lang", S.lang); } catch (err) { /* no storage */ } applyLang(); renderForm(); render(); }
  else if (act === "theme") { S.theme = S.theme === "auto" ? "light" : S.theme === "light" ? "dark" : "auto"; try { localStorage.setItem("mmw60.theme", S.theme); } catch (err) { /* no storage */ } applyTheme(); }
  else if (act === "resetall") setStudy({});
  else if (act === "reset") { const next = Object.assign({}, S.study); delete next[v]; setStudy(next, v); }
  else if (act === "run") runJob(b.dataset.job);
  else if (act === "cancel") cancelJob(v);
  else if (act === "delres") deleteResult(v);
  else if (act === "detail") { S.sel = v; go("row"); }
  else if (act === "open") { const cur = S.open[v] ?? b.closest(".row").classList.contains("open"); S.open[v] = !cur; render(); }
  else if (act === "src") { S.srcOpen[v] = !S.srcOpen[v]; b.classList.toggle("open", S.srcOpen[v]); }
  else { S[act] = v; render(); }
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape") { hidePop(true); if (!$("form").hidden && isPhone()) toggleForm(false); }
  if (e.key === "Enter" && e.target.matches && e.target.matches(".row[data-label]")) { S.sel = e.target.dataset.label; go("row"); }
});
document.addEventListener("change", e => {
  const tg = e.target.closest("[data-toggle]"); if (tg) { S[tg.dataset.toggle] = tg.checked; render(); return; }
  const sl = e.target.closest("[data-sel]"); if (sl) { S[sl.dataset.sel] = sl.value || null; S.row = null; render(); renderForm(); return; }
  const el = e.target.closest("[data-knob]"); if (!el) return;
  const k = knob(el.dataset.knob); if (!k) return;
  let v = k.kind === "bool" ? el.checked : k.kind === "choice" ? el.value : Number((parseFloat(el.value) * (Number(el.dataset.sc) || 1)).toPrecision(12));
  if (typeof v === "number" && !isFinite(v)) { S.knobErr = { [k.id]: T("不是一个数", "not a number") }; renderForm(); return; }
  setStudy(Object.assign({}, S.study, { [k.id]: v }), k.id);
});
document.addEventListener("input", e => {
  if (e.target.id === "src-q") { S.srcQuery = e.target.value; const l = $("src-list"); if (l) l.innerHTML = sourceRows(); }
});
document.addEventListener("mouseover", e => {
  if (!e.target.closest) return;
  const tg = e.target.closest(".tag[data-k], .stag[data-k]"); if (tg && tg.dataset.k && !pinned) showPop(tg, false);
  const t = e.target.closest("[data-tip]"); if (t && t.dataset.tip) { $("tip").textContent = t.dataset.tip; const r = t.getBoundingClientRect(); place($("tip"), r.left + r.width / 2 + 8, r.top - 30); }
});
document.addEventListener("mouseout", e => { if (!e.target.closest) return; if (e.target.closest(".tag[data-k], .stag[data-k]")) hidePop(false); if (e.target.closest("[data-tip]")) $("tip").hidden = true; });
addEventListener("scroll", () => { hidePop(true); $("tip").hidden = true; }, { passive: true, capture: true });
addEventListener("hashchange", () => { const s = location.hash.slice(1); if (SCREENS.includes(s) && s !== S.screen) { S.screen = s; show(); } });
let rz = null, lastW = 0;
new ResizeObserver(() => { const w = $("main").clientWidth; if (w === lastW) return; lastW = w; clearTimeout(rz); rz = setTimeout(() => drawCharts($("screen-" + S.screen)), 80); }).observe($("main"));
matchMedia("(max-width: 760px)").addEventListener("change", () => render());

/* ------------------------------------------------------------------ start */
async function boot() {
  applyLang(); applyTheme();
  const h = location.hash.slice(1); if (SCREENS.includes(h)) S.screen = h;
  render();
  try {
    const [ver, parts] = await Promise.all([api("version"), api("parts")]);
    S.version = ver; S.parts = parts;
    await refreshState();
    go(S.screen, true);
    const src = await api("sources"); S.sources = src.sources; S.counts = src.counts;
    render(); renderForm();
    if ((S.jobs || []).some(jobActive)) poll();
  } catch (e) { showError(e); }
}
boot();
