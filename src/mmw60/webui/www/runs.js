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
      ${jobActive(j) ? `<button type="button" class="btn" data-act="cancel" data-v="${esc(j.id)}" data-cancel="${esc(j.id)}">${T("取消", "Cancel")}</button>` : ""}</div>
    <div class="sm">${T("表单", "Form")}${P_.c}${studyCode(j.study)}${(j.parts || []).length ? ` · ${T("产出", "produces")}${P_.c}${j.parts.map(p => esc(pn(p))).join(P_.d)}` : ""}</div>
    ${run ? `<div class="bar2 ${total ? "" : "ind"}"><i ${total ? `style="width:${Math.min(100, 100 * done / total)}%"` : ""}></i></div>` : ""}
    ${run || j.text ? `<div class="sm">${run ? `<span class="spin" style="display:inline-block;vertical-align:-1px"></span> ` : ""}${total ? `${plain(done)} / ${plain(total)}` : run ? plain(done) : ""} ${esc(j.text || "")}</div>` : ""}
    <div class="sm mut">${nil(el) ? "" : `${T("已用", "elapsed")} <b style="color:var(--ink)">${dur(el)}</b> · `}${T("预计", "expected")} ${exp && exp.length ? exp.map(dur).join(" / ") : T("没有记录", "not recorded")}</div>
    ${j.result_id ? `<div class="sm">${T("结果", "result")} <code>${esc(j.result_id)}</code></div>` : ""}
    ${j.error ? jobError(j) : ""}</div>`;
}
/* a failed job's error: the last line of the traceback is what went wrong, the rest is folded */
function jobError(j) {
  const lines = String(j.error).replace(/\s+$/, "").split("\n"), last = lines.pop();
  return `<div class="joberr" data-job-error="${esc(j.id)}"><b>${esc(last)}</b>${lines.length ? `<details><summary>${T("完整的出错栈", "the whole traceback")}</summary><pre>${esc(lines.join("\n"))}</pre></details>` : ""}</div>`;
}
/* The table's field groups.  A group whose part a job is about to replace (from the press of the button
 * until the job ends) says so (data-running); data-state stays what it is everywhere else on the page,
 * the group's freshness. */
function fieldGroups() {
  const busy = new Set([...(S.jobs || []).filter(jobActive).flatMap(j => j.parts || []), ...Object.keys(S.submitting || {}).flatMap(j => ((S.parts.jobs[j] || {}).parts || []))]);
  return Object.entries(fresh().fields || {}).map(([g, s]) => { const [own, up] = g.split("+"), run = busy.has(own);
    return `<span class="pchip" data-field-group="${esc(g)}" data-state="${esc(s)}"${run ? ' data-running="true"' : ""}>${stateSign(s)} ${esc(pn(own))}${up ? " + " + esc(pn(up)) : T("（自己读的旋钮）", " (its own knobs)")}${P_.c}${stateWord(s)}${run ? ` · <span class="spin" style="display:inline-block;vertical-align:-1px"></span> ${T("正在重算", "being recomputed")}` : ""}</span>`; }).join("");
}
/* ------------------------------------------------------------------ self-check */
const sci = v => (nil(v) ? "—" : v === 0 ? plain(v) : neg(Number(v).toExponential(1)));
function detailText(d) {
  if (nil(d)) return "";
  if (typeof d !== "object") return esc(String(d));
  return Object.entries(d).map(([k, v]) => `<span class="dg">${esc(k)}${P_.c}${esc(v !== null && typeof v === "object" ? JSON.stringify(v) : String(v))}</span>`).join(" ");
}
/* the self-check job while it is queued or running (redrawn with the queue) */
function selfcheckRun() {
  const j = (S.jobs || []).filter(x => x.job === "selfcheck" && jobActive(x)).pop();
  if (!j) return "";
  const [done, total] = j.progress || [0, null];
  return `<div class="sm"><span class="spin" style="display:inline-block;vertical-align:-1px"></span> ${T(...STATUS[j.status])}${total ? ` · ${plain(done)} / ${plain(total)}` : ""} ${esc(j.text || "")}</div>`;
}
function selfcheckCard() {
  const SC = S.selfcheck, o = SC && SC.selfcheck, last = o && o.checks.length ? o.checks[o.checks.length - 1].detail : null, cmp = last && typeof last === "object" && !nil(last.numbers) ? last : null;
  const exp = SC && SC.expected_seconds && SC.expected_seconds.length ? SC.expected_seconds.map(dur).join(" / ") : expected("table_analytic");
  const out = !o ? `<div id="selfcheck" class="selfc">${SC ? `<span class="mut">${T("这台机器上还没有跑过自检。", "No self-check has been run on this machine yet.")}</span>` : `<span class="spin"></span>`}</div>`
    : `<div id="selfcheck" class="selfc ${o.ok ? "pass" : "fail"}" data-ok="${o.ok ? "true" : "false"}">
      <div class="selfv"><span class="vd ${o.ok ? "best" : "no"}">${o.ok ? T("通过", "passed") : T("没通过", "failed")}</span> <span class="n">${when(o.at)}</span> · ${T("用时", "took")} <span class="n">${dur(o.seconds)}</span></div>
      <div class="selfstack">${Object.entries(o.stack || {}).map(([k, v]) => `<span><span class="mut">${esc(k.replace(/_/g, " "))}</span> <b class="n">${typeof v === "boolean" ? (v ? T("是", "yes") : T("否", "no")) : esc(v)}</b></span>`).join("")}</div>
      <div class="selfchecks">${o.checks.map(c => `<div data-check="${esc(c.name)}" data-ok="${c.ok ? "true" : "false"}"><span class="${c.ok ? "okm" : "badm"}">${c.ok ? "✓" : "✗"}</span> ${esc(T(c.zh, c.name))}${c.ok ? "" : `<div class="xs selfd">${detailText(c.detail)}</div>`}</div>`).join("")}</div>
      ${cmp ? `<div class="selfn">${T("逐个数比对", "Number by number")}${P_.c}<span>${T("行", "rows")} <b class="n">${plain(cmp.rows)}</b></span><span>${T("比了", "compared")} <b class="n">${plain(cmp.numbers)}</b></span><span>${T("逐位相同", "identical")} <b class="n">${plain(cmp.identical)}</b></span>
        <span>${T("最大相对差", "worst scaled difference")} <b class="n">${sci(cmp.worst_scaled)}</b> ${T("容差", "against a tolerance of")} <b class="n">${sci(nil(cmp.tolerance) ? o.tolerance : cmp.tolerance)}</b></span>
        ${cmp.worst ? `<span class="dg">${T("最差的一个", "the worst one")}${P_.c}${detailText(cmp.worst)}</span>` : ""}${(cmp.mismatches || []).length ? `<div class="xs selfd">${T("对不上的", "mismatches")}${P_.c}${cmp.mismatches.map(detailText).join("<br>")}</div>` : ""}</div>` : ""}
      ${o.speed ? `<div id="selfcheck-speed" class="selfn">${T("这台机器有多快", "How fast this machine is")}${P_.c}<span>${jn(o.speed.job)} ${T("在本机用了", "took")} <b class="n">${dur(o.speed.seconds_here)}</b>${T("，引用的是", " here, against the quoted")} <b class="n">${dur(o.speed.seconds_reference)}</b></span>
        <span>${T("比值", "ratio")} <b class="n">${fx(o.speed.ratio, 2)}</b></span><span class="mut">${T("别的任务的时长不按这个比值折算。", "Other jobs’ durations are not scaled by this ratio.")}</span></div>` : ""}</div>`;
  return `<section class="blk" id="selfcheck-card"><header><h3>${T("自检", "Self-check")}</h3><span class="mut sm">${T("这台机器算出来的数对不对", "does this machine compute the same numbers")}</span></header>
    <p class="sub">${T("在本机把解析列重算一遍，与随包基线逐个数比对；同时核对随包报告都读得出来、预设下每个部分都是新鲜的。", "Recomputes the analytic table on this machine and compares it with the shipped baseline number by number; it also checks that the shipped reports can be read and that every part is fresh on the presets.")}</p>
    <div class="runbtns"><button type="button" class="runbtn" data-act="run" data-job="selfcheck"><b>▶ ${jn("selfcheck")}</b><span class="sm">${T("预计", "expected")} ${exp}${SC ? " · " + esc(bi(SC, "seconds_note")) : ""}</span></button></div>
    <div id="selfcheck-run">${selfcheckRun()}</div>${out}</section>`;
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
      <span class="sm">${T("引用的时长", "quoted")} ${expected(job)}${j.seconds_note ? " · " + esc(bi(j, "seconds_note")) : ""}</span>${secondsHere(job) ? `<span class="sm">${secondsHere(job)}</span>` : ""}
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
    { h: T("怎么重算", "How to recompute"), f: p => (p.job ? `${jn(p.job)} · ${expected(p.job)}` : p.stored ? `<span class="sm">${T("这里不能重算（要几小时）", "not from this page (it takes hours)")}</span><div class="xs n">${esc(p.stored.command)}</div>${p.stored.seconds_note ? `<div class="xs mut">${esc(bi(p.stored, "seconds_note"))}</div>` : ""}` : "") },
  ], PT.parts);
  const results = tbl([
    { h: T("结果", "Result"), f: r => `<code>${esc(r.id)}</code>${r.shown ? ` <span class="vd best">${T("正在显示", "shown")}</span>` : ""}${r.quick ? ` <span class="vd">${T("试算规模", "smoke size")}</span>` : ""}` },
    { h: T("任务", "Job"), f: r => jn(r.job) }, { h: T("来源", "Origin"), f: r => (r.origin === "baseline" ? T("随包基线", "shipped baseline") : T("本机重算", "computed here") + `<div class="xs mut">${when(r.at)}</div>`) },
    { h: T("表单", "Form"), f: r => studyCode(r.study) + Object.entries(r.built_on || {}).map(([u, s]) => `<div class="xs">${T("建在", "built on")} ${esc(pn(u))} ${studyCode(s)}</div>`).join("") },
    { h: T("耗时", "Took"), r: 1, f: r => dur(r.seconds) }, { h: T("代码", "Code"), f: r => `<code>${esc(r.version || "")} @ ${short(r.commit)}</code>${(r.out_of_step || []).length ? `<div><span class="oos" data-oos="1">${T("与当前代码不同步", "out of step with this code")}</span><div class="xs" style="color:var(--red)">${((S.lang === "zh" && r.out_of_step_zh) || r.out_of_step).map(esc).join("<br>")}</div></div>` : ""}` },
    { h: "", f: r => (r.origin === "user" ? `<button type="button" class="btn" data-act="delres" data-v="${esc(r.id)}" data-delete="${esc(r.id)}">${T("删除", "Delete")}</button>` : "") },
  ], res.map(r => Object.assign({}, r, { __attr: `data-result-id="${esc(r.id)}"`, __cls: r.shown ? "" : "dim" })));
  return `<div class="page">
    <div class="phead"><div><h2>${T("运行台：后台任务、存着的结果、新鲜度", "Runs: background jobs, stored results, freshness")}</h2>
      <p class="sub">${T("一次计算要几十秒到几十分钟，所以改表单不会立刻重算：它只把读过那个旋钮的结果标成过期。重算是这里排的后台任务。", "One computation takes tens of seconds to tens of minutes, so changing the form does not recompute at once: it marks the results that read that knob as stale. A recompute is a background job queued here.")}</p></div>
      <span class="sm">${T("当前表单", "Current form")}${P_.c}${studyCode(S.study)} <button type="button" class="btn" data-act="form">${T("打开表单", "Open the form")}</button></span></div>
    <div class="two run2">
      <div>
        <section class="blk" id="runs-queue">${runsQueue()}</section>
        ${selfcheckCard()}
        <section class="blk"><header><h3>${T("为当前表单排一个任务", "Queue a job for the current form")}</h3></header>
          <p class="note" id="durations-note">${T("按钮上的时长是引用的：在一台四核台式机上量的，不是这台机器的。这台机器自己跑过的时长，有就写在旁边。", "The durations on the buttons are quoted: measured on a four-core desktop, not on this machine. Where this machine has run a job itself, its own time is beside it.")}
            ${PT.host_speed ? `<span id="host-speed" class="b">${T("这台机器跑", "This machine ran")} ${jn(PT.host_speed.job)} ${T("用了", "in")} <span class="n">${dur(PT.host_speed.seconds_here)}</span>${T("，引用的是", ", against the quoted")} <span class="n">${dur(PT.host_speed.seconds_reference)}</span>${T("；别的任务不按它折算。", "; other jobs are not scaled by it.")}</span>` : ""}</p>
          <div class="runbtns">${runOrder(PT.jobs).map(job => runBtn(job, PT.jobs[job])).join("")}</div>
          <p class="note">${T("同台表是由几部分拼成的（解析列、时域核对列、本振模型并排、802.11ay 两行），各取存着的那份结果。只算解析列的预览只换掉解析列：其余几部分还是上一次整表的，照样标着过期。", "The comparison table is assembled from several parts (the analytic columns, the time-domain check, the LO models side by side, the two 802.11ay rows), each taken from the result stored for it. The analytic-only preview replaces the analytic columns alone: the other parts stay those of the last full table and stay marked stale.")}</p></section>
      </div>
      <div>
        <section class="blk"><header><h3>${T("新鲜度：每个部分读哪些旋钮、按哪份结果判", "Freshness: which knobs each part reads, and which result it is judged against")}</h3></header>
          ${ledger}
          <div class="fgroups"><div class="eyebrow">${T("同台表的列按字段组过期：一个部分自己的旋钮没动、只是上游过期时，过期的只有建在那个上游上的列", "The table’s columns go stale by field group: when a part’s own knobs hold and only an upstream is stale, only the columns built on that upstream are stale")}</div>
            <div id="field-groups">${fieldGroups()}</div></div>
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
