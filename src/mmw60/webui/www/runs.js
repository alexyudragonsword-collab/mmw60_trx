/* Screens: Runs (the queue, the stored results, freshness of every part, what reads what),
 * Sources (the spec-table entries with their labels) and the form drawer (the shared knobs). */
"use strict";
const jobActive = j => j.status === "queued" || j.status === "running";
const STATUS = { queued: ["排队", "queued"], running: ["运行中", "running"], done: ["完成", "done"], error: ["失败", "failed"], cancelled: ["已取消", "cancelled"] };
const studyCode = st => (Object.keys(st || {}).length ? `<code>${esc(JSON.stringify(st))}</code>` : `<span class="mut">${T("预设", "the presets")}</span>`);

function jobCard(j) {
  const [done, total] = j.progress || [0, null], run = j.status === "running", now = Date.now() / 1000;
  const el = j.started ? (j.finished || now) - j.started : null, exp = j.expected_seconds;
  return `<div class="job ${run ? "run" : ""} ${j.status === "error" ? "err" : ""}" data-job-id="${esc(j.id)}" data-status="${esc(j.status)}">
    <div class="top"><span class="q">#${esc(j.id)} · ${T(...(STATUS[j.status] || [j.status, j.status]))}</span><span class="nm">${jn(j.job)}</span>
      ${jobActive(j) ? `<button type="button" class="btn" data-act="cancel" data-v="${esc(j.id)}">${T("取消", "Cancel")}</button>` : ""}</div>
    <div class="sm">${T("表单", "Form")}${P_.c}${studyCode(j.study)} · ${T("产出", "produces")}${P_.c}${(j.parts || []).map(p => esc(pn(p))).join(P_.d)}</div>
    ${run ? `<div class="bar2 ${total ? "" : "ind"}"><i ${total ? `style="width:${Math.min(100, 100 * done / total)}%"` : ""}></i></div>` : ""}
    ${run || j.text ? `<div class="sm">${run ? `<span class="spin" style="display:inline-block;vertical-align:-1px"></span> ` : ""}${total ? `${plain(done)} / ${plain(total)}` : run ? plain(done) : ""} ${esc(j.text || "")}</div>` : ""}
    <div class="sm mut">${nil(el) ? "" : `${T("已用", "elapsed")} <b style="color:var(--ink)">${dur(el)}</b> · `}${T("预计", "expected")} ${exp && exp.length ? exp.map(dur).join(" / ") : T("没有记录", "not recorded")}</div>
    ${j.result_id ? `<div class="sm">${T("结果", "result")} <code>${esc(j.result_id)}</code></div>` : ""}
    ${j.error ? `<pre>${esc(j.error)}</pre>` : ""}</div>`;
}
function runsQueue() {
  const jobs = (S.jobs || []).slice().reverse(), act = jobs.filter(jobActive);
  return `<header><h3>${T("后台任务", "Background jobs")}</h3><span class="mut sm">${act.length ? `${act.filter(j => j.status === "running").length} ${T("个运行", "running")} · ${act.filter(j => j.status === "queued").length} ${T("个排队", "queued")}` : T("没有在跑的任务", "nothing is running")}</span></header>
    ${jobs.length ? jobs.map(jobCard).join("") : `<p class="mut">${T("队列是空的。用下面的按钮为当前表单排一个任务。", "The queue is empty. Use the buttons below to queue a job for the current form.")}</p>`}`;
}
/* the jobs in the payload's order, with the analytic-only preview right after the full table */
function runOrder(jobs) { const ks = Object.keys(jobs).filter(j => j !== "table_analytic"); if (jobs.table_analytic) ks.splice(ks.indexOf("table") + 1, 0, "table_analytic"); return ks; }
function renderRuns() {
  if (!S.parts || !S.state) return `<div class="page"><div class="loading"><span class="spin"></span></div></div>`;
  const PT = S.parts, fp = fresh().parts, res = S.state.results || [], ed = Object.keys(S.study);
  const runBtn = (job, j) => { const stale = j.parts.some(p => pstate(p) === "stale"), stored = (S.state.shown || {})[j.report];
    return `<button type="button" class="runbtn" data-act="run" data-job="${esc(job)}" data-state="${stale || !stored ? "stale" : "fresh"}"><b>▶ ${jn(job)}</b>
      <span class="sm">${T("预计", "expected")} ${expected(job)}${j.seconds_note ? " · " + esc(j.seconds_note) : ""}</span>
      <span class="sm">${T("产出", "produces")}${P_.c}${j.parts.map(p => `${pstate(p) === "stale" ? "◷" : "●"} ${esc(pn(p))}`).join(P_.s)}</span><code class="xs">${esc(j.command)}</code></button>`; };
  const groups = [...new Set(PT.knobs.map(k => k.group))], gname = g => { const x = S.state.form.groups[g]; return x ? T(x.zh, x.en) : g; };
  const matrix = `<div class="tw"><table class="dt mx dots"><thead><tr><th rowspan="2">${T("部分", "Part")}</th>${groups.map(g => `<th colspan="${PT.knobs.filter(k => k.group === g).length}" class="gh">${esc(gname(g))}</th>`).join("")}</tr>
      <tr>${PT.knobs.map(k => { const kb = knob(k.id); return `<th class="vh ${ed.includes(k.id) ? "hit" : ""}" title="${esc(k.id)}"><span>${esc(kb ? knobLabel(kb) : k.id)}</span></th>`; }).join("")}</tr></thead>
      <tbody>${PT.parts.map(p => `<tr><td class="rt-h" title="${esc(p.id)}">${esc(pn(p.id))}</td>${PT.knobs.map(k => { const y = p.reads.includes(k.id), hit = y && (fp[p.id].changed || []).includes(k.id); return `<td class="${hit ? "hit" : y ? "y" : "n0"}" title="${esc(p.id)} × ${esc(k.id)}">${y ? "●" : "·"}</td>`; }).join("")}</tr>`).join("")}</tbody></table></div>`;
  const ledger = tbl([
    { h: T("部分", "Part"), f: p => `${esc(pn(p.id))}<div class="xs mut n">${esc(p.id)}</div>` },
    { h: T("状态", "State"), f: p => `<span class="pchip" data-part="${esc(p.id)}" data-state="${pstate(p.id)}">${stateSign(pstate(p.id))} ${stateWord(pstate(p.id))}</span>` },
    { h: T("是哪个旋钮动了它", "Knobs that moved it"), f: p => (fp[p.id].changed || []).map(id => changeText(id, p.id)).join("<br>") || `<span class="mut">—</span>` },
    { h: T("上游", "Upstream"), f: p => (fp[p.id].upstream || []).map(u => `<span class="dg">${esc(pn(u))}${pstate(u) === "stale" ? "" : " · " + T("不是建在现在这份上", "not built on the one now stored")}</span>`).join("<br>") || (p.upstream.length ? `<span class="mut">${p.upstream.map(u => esc(pn(u))).join(P_.d)}</span>` : `<span class="mut">—</span>`) },
    { h: T("按什么判", "Judged against"), f: p => { const m = metaOfPart(p.id), c = fp[p.id].computed_at; return `${basisWord(fp[p.id].basis)}${m ? ` <code>${esc(m.id)}</code>` : ""}${c ? `<div class="xs mut n">${esc(c.version || "")} @ ${short(c.commit)}</div>` : ""}`; } },
    { h: T("怎么重算", "How to recompute"), f: p => (p.job ? `${jn(p.job)} · ${expected(p.job)}` : p.stored ? `<span class="sm">${T("这里不能重算（要几小时）", "not from this page (it takes hours)")}</span><div class="xs n">${esc(p.stored.command)}</div>${p.stored.seconds_note ? `<div class="xs mut">${esc(p.stored.seconds_note)}</div>` : ""}` : "") },
  ], PT.parts);
  const results = tbl([
    { h: T("结果", "Result"), f: r => `<code>${esc(r.id)}</code>${r.shown ? ` <span class="vd best">${T("正在显示", "shown")}</span>` : ""}${r.quick ? ` <span class="vd">${T("试算规模", "smoke size")}</span>` : ""}` },
    { h: T("任务", "Job"), f: r => jn(r.job) }, { h: T("来源", "Origin"), f: r => (r.origin === "baseline" ? T("随包基线", "shipped baseline") : T("本机重算", "computed here") + `<div class="xs mut">${when(r.at)}</div>`) },
    { h: T("表单", "Form"), f: r => studyCode(r.study) + Object.entries(r.built_on || {}).map(([u, s]) => `<div class="xs">${T("建在", "built on")} ${esc(pn(u))} ${studyCode(s)}</div>`).join("") },
    { h: T("耗时", "Took"), r: 1, f: r => dur(r.seconds) }, { h: T("代码", "Code"), f: r => `<code>${esc(r.version || "")} @ ${short(r.commit)}</code>${(r.out_of_step || []).length ? `<div><span class="oos" data-oos="1">${T("与当前代码不同步", "out of step with this code")}</span><div class="xs" style="color:var(--red)">${r.out_of_step.map(esc).join("<br>")}</div></div>` : ""}` },
    { h: "", f: r => (r.origin === "user" ? `<button type="button" class="btn" data-act="delres" data-v="${esc(r.id)}">${T("删除", "Delete")}</button>` : "") },
  ], res.map(r => Object.assign({}, r, { __attr: `data-result-id="${esc(r.id)}"`, __cls: r.shown ? "" : "dim" })));
  return `<div class="page">
    <div class="phead"><div><h2>${T("运行台：后台任务、存着的结果、新鲜度", "Runs: background jobs, stored results, freshness")}</h2>
      <p class="sub">${T("一次计算要几十秒到几十分钟，所以改表单不会立刻重算：它只把读过那个旋钮的结果标成过期。重算是这里排的后台任务。", "One computation takes tens of seconds to tens of minutes, so changing the form does not recompute at once: it marks the results that read that knob as stale. A recompute is a background job queued here.")}</p></div>
      <span class="sm">${T("当前表单", "Current form")}${P_.c}${studyCode(S.study)} <button type="button" class="btn" data-act="form">${T("打开表单", "Open the form")}</button></span></div>
    <div class="two run2">
      <div>
        <section class="blk" id="runs-queue">${runsQueue()}</section>
        <section class="blk"><header><h3>${T("为当前表单排一个任务", "Queue a job for the current form")}</h3></header>
          <div class="runbtns">${runOrder(PT.jobs).map(job => runBtn(job, PT.jobs[job])).join("")}</div>
          <p class="note">${T("同台表是由三部分拼成的（解析列、时域核对列、802.11ay 两行），各取存着的那份结果。只算解析列的预览只换掉解析列：时域核对列和 802.11ay 两行还是上一次整表的，照样标着过期。", "The comparison table is assembled from three parts (analytic columns, time-domain column, the two 802.11ay rows), each from the result stored for it. The analytic-only preview replaces the analytic columns alone: the time-domain column and the 802.11ay rows stay the last full run’s, still marked stale.")}</p></section>
      </div>
      <div>
        <section class="blk"><header><h3>${T("新鲜度：每个部分读哪些旋钮、按哪份结果判", "Freshness: which knobs each part reads, and which result it is judged against")}</h3></header>
          ${ledger}
          <div class="fgroups"><div class="eyebrow">${T("同台表的列按字段组过期：一个部分自己的旋钮没动、只是上游过期时，过期的只有建在那个上游上的列", "The table’s columns go stale by field group: when a part’s own knobs hold and only an upstream is stale, only the columns built on that upstream are stale")}</div>
            ${Object.entries(fresh().fields || {}).map(([g, s]) => { const [own, up] = g.split("+"); return `<span class="pchip" data-field-group="${esc(g)}" data-state="${esc(s)}">${stateSign(s)} ${esc(pn(own))}${up ? " + " + esc(pn(up)) : T("（自己读的旋钮）", " (its own knobs)")}${P_.c}${stateWord(s)}</span>`; }).join("")}</div>
          <div class="lg"><span>● ${T("读这个旋钮", "reads the knob")}</span><span>· ${T("不读", "does not read")}</span><span><span class="sw hitsw"></span>${T("读到了改过的旋钮", "reads an edited knob")}</span></div>
          ${matrix}
          <div><div class="eyebrow">${T("依赖链：上游过期，下游跟着过期", "Dependency chains: when upstream goes stale, downstream follows")}</div><div class="chartbox" data-chart="deps" style="margin-top:6px"></div></div>
          <p class="note">${T("这张“谁读什么”的表由测试守着：每个部分在配置读取的追踪下实跑，追踪到的必须都在声明里。", "This table of what reads what is guarded by a test: every part is run under a tracer of configuration reads, and what is traced must be declared.")}</p>
        </section>
      </div>
    </div>
    <section class="blk"><header><h3>${T("存着的结果", "Stored results")}</h3><span class="mut sm">${res.length} · ${S.version && S.version.results_dir ? `<code>${esc(S.version.results_dir)}</code>` : T("只在内存里", "in memory only")}</span></header>${results}</section>
    <section class="blk"><header><h3>${T("这份界面跑在什么上", "What this page is running on")}</h3></header>${S.version ? `<dl class="kv"><dt>${T("库", "Library")}</dt><dd><code>${esc(S.version.library)} ${esc(S.version.version)} @ ${esc(S.version.provenance.commit || "—")}</code></dd><dt>Python</dt><dd class="n">${esc(S.version.python)}</dd>
      <dt>${T("队列", "Queue")}</dt><dd class="n">${esc(S.version.backend)} · ${plain(S.version.workers)} ${T("个同时", "at a time")}</dd><dt>${T("规范表摘要", "Spec-table digest")}</dt><dd><code>${esc(S.version.provenance.spec_digest)}</code></dd>
      ${Object.entries(S.version.provenance.vendored || {}).map(([k, v]) => `<dt>${esc(k)}${v.version ? " " + esc(v.version) : ""}</dt><dd><code>${esc(v.pin)}</code></dd>`).join("")}</dl>` : ""}</section></div>`;
}

/* ------------------------------------------------------------------ sources */
function sourceRows() {
  const q = S.srcQuery.trim().toLowerCase(), all = Object.values(S.sources || {});
  const rows = all.filter(s => (S.srcFilter === "all" || s.source === S.srcFilter) && (!q || (s.key + " " + s.cite + " " + s.note + " " + s.unit).toLowerCase().includes(q)));
  const val = s => (typeof s.value === "object" && s.value !== null ? JSON.stringify(s.value) : String(s.value));
  return `<div class="xs mut" style="padding:6px 12px">${rows.length} / ${all.length}</div>` + rows.map(s => `<div class="srcrow" data-source-key="${esc(s.key)}"><span class="k">${esc(s.key)}</span><span>${tagPlain(s.source)}</span>
    <span class="v">${esc(val(s))}${s.unit ? ` <span class="mut">${esc(s.unit)}</span>` : ""}</span>
    <span class="c clamp ${S.srcOpen[s.key] ? "open" : ""}" data-act="src" data-v="${esc(s.key)}">${s.cite ? `<b>${T("出处", "Cite")}</b> ${esc(s.cite)}` : ""}${s.note ? ` <b>${T("注", "Note")}</b> ${esc(s.note)}` : ""}</span></div>`).join("");
}
function renderSources() {
  if (!S.sources) return `<div class="page"><div class="loading"><span class="spin"></span></div></div>`;
  const c = S.counts || {}, n = Object.keys(S.sources).length;
  return `<div class="page">
    <div class="phead"><div><h2>${T("出处：规范表的每一条", "Sources: every entry of the spec table")}</h2>
      <p class="sub">${T("页面上每个带标签的数都指到这里的一条。spec = 规范或论文原文；survey = 拿不到原文、注明了出处的；assumed = 原文没说、本库选的；derived = 由上面几类算出来的。", "Every labelled number on the page points to an entry here. spec = the standard or paper itself; survey = no original at hand, the source is named; assumed = the original does not say, this library chose; derived = computed from the others.")}</p></div></div>
    <div class="ctl"><span class="seglab">${T("只看", "Show")} ${seg("srcFilter", S.srcFilter, [["all", `${T("全部", "All")} ${n}`], ...["spec", "survey", "assumed", "derived"].map(s => [s, `${s} ${plain(c[s] ?? 0)}`])])}</span>
      <input class="q" id="src-q" type="search" placeholder="${T("筛选键 / 出处 / 注", "filter key / cite / note")}" value="${esc(S.srcQuery)}" aria-label="filter"></div>
    <div class="ct" id="src-list">${sourceRows()}</div></div>`;
}

/* ------------------------------------------------------------------ the form drawer */
function knobRow(k) {
  const ed = k.tag.edited, sh = knobShow(k, k.value), id = "k-" + k.id.replace(/\./g, "-"), psh = knobShow(k, k.preset), err = S.knobErr[k.id];
  let input;
  if (k.kind === "choice") input = `<select id="${id}" data-knob="${esc(k.id)}">${k.choices.map(c => `<option ${c === k.value ? "selected" : ""}>${esc(c)}</option>`).join("")}</select>`;
  else if (k.kind === "bool") input = `<input type="checkbox" id="${id}" data-knob="${esc(k.id)}" ${k.value ? "checked" : ""}>`;
  else input = `<input type="number" id="${id}" data-knob="${esc(k.id)}" data-sc="${sh.sc}" value="${sh.v}" ${nil(k.lo) ? "" : `min="${k.lo / sh.sc}"`} ${nil(k.hi) ? "" : `max="${k.hi / sh.sc}"`} step="${nil(k.step) ? "any" : k.step / sh.sc}">`;
  const prov = ed ? `${tagEdited(k.tag.was)} <span>${T("原值", "was")} <span class="n">${plain(psh.v)}${psh.u ? " " + esc(psh.u) : ""}</span></span> <button type="button" class="btn ghost" data-act="reset" data-v="${esc(k.id)}">${T("还原", "reset")}</button>`
    : (k.tag.key ? `${tag(k.tag.key, k.tag.source)} <code>${esc(k.tag.key)}</code>` : `<span class="tag t-none">${T("配置项，无外部出处", "configuration choice, no external source")}</span>`);
  const help = T(k.help_zh, k.help_en);
  return `<div class="knob ${ed ? "ed" : ""}" data-knob-row="${esc(k.id)}"><label for="${id}">${esc(knobLabel(k))}<code>${esc(k.id)}</code></label>
    <div class="in">${input}<span class="u">${esc(sh.u || "")}</span></div>
    <div class="pv">${prov}${help ? `<span style="flex-basis:100%">${esc(help)}</span>` : ""}
      <span class="rb" title="${T("读它的部分", "parts that read it")}">${T("读它的", "read by")}${P_.c}${k.read_by.map(p => `<span data-state="${pstate(p)}" title="${esc(pn(p))}">${esc(p)}</span>`).join("")}</span></div>
    ${err ? `<div class="kerr" role="alert">${esc(err)}</div>` : ""}</div>`;
}
function renderForm() {
  if (!S.state) return;
  const F = S.state.form, shared = F.knobs.filter(k => !k.row_knob), rowk = F.knobs.filter(k => k.row_knob), n = Object.keys(S.study).length;
  const R = S.rep.table && S.rep.table.report, row = R && S.sel ? tableRows(R).find(r => r.label === S.sel) : null;
  const rv = { topology: row ? row.topology : null, waveform: row ? row.waveform : null, upclock_k: row && !isAy(row) ? row.k : null };
  const focus = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.knob : null;
  $("form-body").innerHTML = `<div class="rowknobs"><div class="eyebrow">${rowk.length} ${T("个行旋钮：选的是同台表的哪一行，不属于表单，从不让结果过期", "row knobs: they pick a row of the table, are not part of the form and never make a result stale")}</div>
      ${rowk.map(k => `<div data-row-knob="${esc(k.id)}">${esc(knobLabel(k))} <code>${esc(k.id)}</code>${P_.c}<b class="n">${k.id === "phy.mcs" ? T("表里给的是上限", "the table gives the caps") : row ? plain(rv[k.id]) : "—"}</b></div>`).join("")}
      <div class="xs mut">${row ? esc(row.label) : T("还没有选行；同台表本身跨着这四个旋钮。", "No row selected; the table itself spans these four knobs.")}</div></div>
    <div class="sm mut">${shared.length} ${T("个共享旋钮，对每一行同时生效。界面上改过的值不再是原文的：标签变成", "shared knobs, applied to every row at once. A value changed here is no longer the source’s: its label becomes")} ${tagEdited()}</div>
    ${Object.keys(F.groups).map(g => { const ks = shared.filter(k => k.group === g); return ks.length ? `<section class="kgroup"><header><h3>${esc(T(F.groups[g].zh, F.groups[g].en))}</h3><span class="mut sm">${ks.length}</span></header>${ks.map(knobRow).join("")}</section>` : ""; }).join("")}`;
  const rb = $("form-reset"); rb.hidden = !n; rb.textContent = T(`还原全部（${n}）`, `Reset all (${n})`);
  const fc = $("form-count"); fc.hidden = !n; fc.textContent = String(n);
  if (focus) { const el = document.querySelector(`[data-knob="${CSS.escape(focus)}"]`); if (el && !$("form").hidden) el.focus({ preventScroll: true }); }
}
