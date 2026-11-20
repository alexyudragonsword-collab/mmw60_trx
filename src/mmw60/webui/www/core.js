/* The mmw60 results browser: transport, page state, language, formatting, source tags and
 * freshness marks.  Every number on the page comes from a payload of the local API; this
 * file formats and arranges, it never computes a result. */
"use strict";
const $ = id => document.getElementById(id);

/* ------------------------------------------------------------------ transport */
/* On the desktop the page talks to the local server; in a phone WebView the activity injects
 * window.host and the reply comes back through window.onHostReply (async, because a
 * @JavascriptInterface call arrives on a binder thread). */
const ON_DEVICE = !!(window.host && window.host.call);
const pendingHost = {}; let hostSeq = 0;
window.onHostReply = (id, text) => { const p = pendingHost[id]; delete pendingHost[id]; if (p) p(text); };
async function api(route, body) {
  let j;
  if (ON_DEVICE) {
    const text = await new Promise(res => { const id = String(++hostSeq); pendingHost[id] = res;
      window.host.call(id, route, JSON.stringify(body === undefined ? {} : body)); });
    j = JSON.parse(text);
  } else {
    const r = await fetch("api/" + route, body === undefined ? {} :
      { method: "POST", headers: { "Content-Type": "application/json", "X-MMW60": "1" }, body: JSON.stringify(body) });
    j = await r.json();
  }
  if (j.ok === false) throw new Error(j.error || ("api/" + route + " failed"));
  return j;
}

/* ------------------------------------------------------------------ state */
const S = {
  lang: "zh", theme: "auto", screen: "table", formOpen: false,
  study: {},                       // the form: shared knobs that differ from the presets (normalised by the host)
  state: null,                     // last `state` payload: form, freshness, shown, jobs, results
  version: null, parts: null, sources: null, counts: null,
  rep: {}, repStudy: {},           // `report` payloads by name, and the study each was fetched for
  row: null, system: null, systemStudy: null,
  sel: null,                       // the selected comparison-table row (label)
  lens: "rate", basis: "conf", chain: "cal", filt: "all", keep: false, open: {},
  arr: null, arrPt: "preset", arrAll: "slow", sysLight: true,
  srcFilter: "all", srcQuery: "", srcOpen: {},
  knobErr: {}, loading: {}, polling: false, pollAgain: false, lastJobs: {},
};
try { const l = localStorage.getItem("mmw60.lang"); if (l === "en" || l === "zh") S.lang = l; } catch (e) { /* no storage */ }
try { const t = localStorage.getItem("mmw60.theme"); if (t === "light" || t === "dark") S.theme = t; } catch (e) { /* no storage */ }

/* ------------------------------------------------------------------ language */
const T = (zh, en) => (S.lang === "zh" ? zh : en);
const P_ = { get c() { return T("：", ": "); }, get s() { return T("；", "; "); }, get d() { return T("、", ", "); }, get p() { return T("。", ". "); } };
/* Words the payloads carry in one language only.  Only strings without result numbers are
 * translated; anything else is shown as the payload has it. */
const TR = {
  "能": "works", "不能": "does not work", "PA 限 MCS": "PA limits the MCS", "CFO 捕获": "CFO capture",
  "IQ 不平衡 限 MCS": "IQ imbalance limits the MCS", "IQ 不平衡": "IQ imbalance", "同上": "same as above", "同 tx_iq": "same as tx_iq",
  "与 fs 无关": "independent of fs",
};
const TR_ZH = {
  "analytic sum of terms; cross-checked by a time-domain EVM run of the same cell": "各项的解析和；用同一格的时域 EVM 交叉核对",
  "not measured on this chain: the analytic sum with the IQ image at the IRR the calibration runs measured at that bandwidth (a looked-up value)":
    "不是在这条链上量的：解析和，其中 IQ 镜像取校准运行在该带宽量到的 IRR（查表值）",
  "analytic sum of terms; the chip's residual in it is measured after the chip's own calibration, which runs when the chain is built":
    "各项的解析和；其中芯片残差是芯片自己校准之后实测的，校准在建链时真跑",
  "the same as the raw floor (the chip is already calibrated)": "与未校准底板相同（芯片已经校准过）",
  "time-domain EVM on the uncalibrated chain, worst constellation (no analytic sum)": "未校准链上的时域 EVM，取最差星座（没有解析和）",
  "measured: time-domain EVM on the chain wifitrx's calibration sequence calibrated": "实测：wifitrx 校准序列校准过的链上的时域 EVM",
  "wifitrx's own verdict of the step on that run": "wifitrx 自己对这一步在这次运行上的判定",
  "calibration result": "校准结果", "accepted presets": "已验收的预设结果", "envelope": "存着的结果",
};
const tr = s => (s === null || s === undefined ? "" : S.lang === "zh" ? (TR_ZH[s] ?? s) : (TR[s] ?? s));
function applyLang() {
  document.documentElement.lang = S.lang === "zh" ? "zh-CN" : "en";
  document.querySelectorAll("[data-zh]").forEach(e => { e.textContent = e.dataset[S.lang] || e.dataset.zh; });
  document.title = T("mmw60 结果台", "mmw60 results browser");
  const b = $("lang-toggle"); if (b) b.textContent = S.lang === "zh" ? "EN" : "中";
}
function applyTheme() {
  if (S.theme === "auto") document.documentElement.removeAttribute("data-theme"); else document.documentElement.setAttribute("data-theme", S.theme);
  const b = $("btn-theme"); if (b) b.textContent = S.theme === "light" ? "☀" : S.theme === "dark" ? "☾" : "◐";
}

/* ------------------------------------------------------------------ formatting (drawing, not computing) */
const esc = s => String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const neg = s => String(s).replace(/^-/, "−");
const nil = v => v === null || v === undefined || (typeof v === "number" && !isFinite(v));
/* one rounding, from the full-precision value, to d decimals */
function fx(v, d) { if (nil(v)) return "—"; if (typeof v !== "number") return esc(v); return neg(v.toFixed(d === undefined ? 1 : d)); }
/* a configuration value as it is (no decimals imposed): floating-point dust trimmed, nothing else */
function plain(v) {
  if (nil(v)) return "—";
  if (typeof v === "boolean") return v ? T("是", "yes") : T("否", "no");
  if (typeof v !== "number") return esc(typeof v === "object" ? JSON.stringify(v) : v);
  return neg(String(Number(v.toPrecision(10))));
}
/* three significant figures for quantities that span decades (ranges in metres, mW) */
function sig(v) { if (nil(v)) return "—"; const a = Math.abs(v); return fx(v, a >= 100 ? 0 : a >= 10 ? 1 : 2); }
/* unit prefixes */
function hz(v) { if (nil(v)) return "—"; const a = Math.abs(v), [sc, u] = a >= 1e9 ? [1e9, "GHz"] : a >= 1e6 ? [1e6, "MHz"] : a >= 1e3 ? [1e3, "kHz"] : [1, "Hz"]; return plain(v / sc) + " " + u; }
const mhz = v => (nil(v) ? "—" : plain(v / 1e6));
function secs(v) { if (nil(v)) return "—"; const a = Math.abs(v), [sc, u] = a >= 1 ? [1, "s"] : a >= 1e-3 ? [1e-3, "ms"] : a >= 1e-6 ? [1e-6, "µs"] : [1e-9, "ns"]; return plain(Number((v / sc).toPrecision(4))) + " " + u; }
const gbps = v => (nil(v) ? "—" : fx(v / 1e9, 2));
const mcs = v => (nil(v) ? "—" : "MCS" + v);
/* a duration in seconds as a person reads it */
function dur(s) { if (nil(s)) return "—"; s = Math.round(s); return s < 90 ? s + " s" : Math.floor(s / 60) + " min " + String(s % 60).padStart(2, "0") + " s"; }
function when(at) { if (!at) return ""; const d = new Date(at * 1000), p = n => String(n).padStart(2, "0"); return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; }
const short = c => (c ? String(c).slice(0, 7) : "—");

/* ------------------------------------------------------------------ source labels */
function tag(key, src) {
  const s = S.sources && S.sources[key]; src = src || (s ? s.source : null);
  if (!src) return "";
  return `<button type="button" class="tag t-${esc(src)}" data-k="${esc(key || "")}" aria-label="${esc(src)}: ${esc(key || "")}">${esc(src)}</button>`;
}
const tagPlain = src => (src ? `<span class="tag t-${esc(src)}" style="cursor:default">${esc(src)}</span>` : "");
const tagEdited = was => `${was ? `<span class="tag t-${esc(was)} t-was" style="cursor:default">${esc(was)}</span>` : ""}<span class="tag t-edited" style="cursor:default">✎ assumed</span>`;
/* the label a payload entry carries: {source, source_key?, edited?, source_was?} */
function tagOf(p) {
  if (!p) return "";
  if (p.edited) return tagEdited(p.source_was);
  return p.source_key ? tag(p.source_key, p.source) : tagPlain(p.source);
}

/* ------------------------------------------------------------------ knobs */
const knobs = () => (S.state ? S.state.form.knobs : []);
const knob = id => knobs().find(k => k.id === id);
const knobLabel = k => T(k.zh, k.en);
function knobShow(k, v) {
  if (k.unit === "Hz" && typeof v === "number") { const a = Math.abs(v), [sc, u] = a >= 1e9 ? [1e9, "GHz"] : a >= 1e6 ? [1e6, "MHz"] : [1e3, "kHz"]; return { v: Number((v / sc).toPrecision(12)), u, sc }; }
  return { v, u: k.unit, sc: 1 };
}
function knobText(k, v) { const a = knobShow(k, v); return plain(a.v) + (a.u ? " " + esc(a.u) : ""); }

/* ------------------------------------------------------------------ parts, jobs, freshness */
const JOBNAME = {
  calibration_be: ["校准序列", "Calibration sequence"], table: ["同台表", "Comparison table"],
  table_analytic: ["同台表 · 只算解析列", "Comparison table, analytic columns only"], array: ["阵列", "Array"], ay: ["SC 对 OFDM", "SC against OFDM"],
};
const REPNAME = { table: ["同台表", "comparison table"], calibration: ["校准", "calibration"], array: ["阵列", "array"], ay: ["SC 对 OFDM", "SC against OFDM"] };
const jn = id => (JOBNAME[id] ? T(...JOBNAME[id]) : id);
const partInfo = id => (S.parts ? S.parts.parts.find(p => p.id === id) : null);
const pn = id => { const p = partInfo(id); return p ? T(p.zh, p.en) : id; };
const fresh = () => (S.state ? S.state.freshness : { parts: {}, fields: {} });
const pstate = id => (fresh().parts[id] ? fresh().parts[id].state : "fresh");
/* fresh | stale | missing (nothing stored for the part: the host draws only what its store holds) */
const stateWord = s => (s === "stale" ? T("过期", "stale") : s === "missing" ? T("没有存着的结果", "nothing stored") : T("新鲜", "fresh"));
const stateSign = s => (s === "stale" ? "◷" : s === "missing" ? "○" : "●");
/* the stored result that carries a part for the study on screen (or null: judged against the accepted presets) */
function metaOfPart(id) {
  const sh = S.state ? S.state.shown : {}, pr = sh.table && sh.table.part_results;
  if (pr && id in pr) return pr[id];                      // the table is drawn from up to three results, one per part
  for (const r in sh) if (sh[r] && sh[r].parts.includes(id)) return sh[r];
  return null;
}
/* the group of fields a comparison-table field belongs to (a stale one first, when it is in two)
 * and its state: stale when any group it belongs to is */
function fieldGroup(rep, field, ay) {
  /* a be row's field is looked up in the be groups, an 802.11ay row's in the ay groups (the two kinds share field names) */
  const f = fresh().fields, own = Object.keys(rep.fields || {}).filter(g => g.startsWith("table.ay") === !!ay && rep.fields[g].includes(field)), gs = own.length ? own : [ay ? "table.ay" : "table.analytic"];
  return gs.find(g => f[g] === "stale") || gs[0];
}
const fieldState = (rep, field, ay) => fresh().fields[fieldGroup(rep, field, ay)] || "fresh";
/* a stale mark around a number: the number stays, hatched */
const sv = (state, html, part) => (state === "stale" ? `<span class="sv" data-state="stale" data-part="${esc(part || "")}" title="${T("过期：它来自的结果读了改过的旋钮", "stale: the result it comes from reads an edited knob")}">${html}</span>` : html);
const svField = (rep, field, ay, html) => sv(fieldState(rep, field, ay), html, fieldGroup(rep, field, ay));
function expected(job) {
  const j = S.parts && S.parts.jobs[job]; if (!j) return "";
  return j.seconds && j.seconds.length ? j.seconds.map(dur).join(" / ") : T("没有记录", "not recorded");
}
function changeText(id, part) {
  const k = knob(id); if (!k) return esc(id);
  const m = metaOfPart(part), was = m && id in m.study ? m.study[id] : k.preset, a = knobShow(k, was), b = knobShow(k, k.value);
  return `${esc(knobLabel(k))} ${plain(a.v)}${a.u && a.u !== b.u ? " " + esc(a.u) : ""} → ${plain(b.v)}${b.u ? " " + esc(b.u) : ""}`;
}
/* where a stored result was computed, and whether this code would compute the same */
function provLine(meta) {
  if (!meta) return "";
  const p = meta.provenance || {}, bo = Object.entries(meta.built_on || {}), oos = meta.out_of_step || [];
  return `<span class="prov" data-result="${esc(meta.id)}">${T("结果", "result")} <code>${esc(meta.id)}</code> · ${meta.origin === "baseline" ? T("随包基线", "shipped baseline") : T("本机重算", "computed here") + " " + when(meta.at)}
    · <code>${esc(p.version || meta.version || "")} @ ${short(p.commit || meta.commit)}</code>${nil(meta.seconds) ? "" : " · " + dur(meta.seconds)}${Object.keys(meta.study || {}).length ? " · " + T("表单", "form") + " <code>" + esc(JSON.stringify(meta.study)) + "</code>" : ""}
    ${bo.map(([u, st]) => ` · ${T("建在", "built on")} ${esc(pn(u))} <code>${esc(JSON.stringify(st))}</code>`).join("")}
    ${oos.length ? ` <span class="oos" data-oos="1" title="${esc(oos.join("\n"))}">${T("与当前代码不同步", "out of step with this code")}</span> <span class="sm" style="color:var(--red)">${oos.map(esc).join(P_.s)}</span>` : ""}</span>`;
}
/* The comparison table's provenance: one line when its three parts come from one stored result,
 * else one line per part (which result, its form, when); a part with no result at all says so. */
const TABLE_PARTS = ["table.analytic", "table.td", "table.ay"];
function tableProv(pr) {
  if (!pr) return "";
  const ids = TABLE_PARTS.map(p => (pr[p] ? pr[p].id + "@" + pr[p].at : null));
  if (ids.every(i => i !== null && i === ids[0])) return `<span>${provLine(pr[TABLE_PARTS[0]])}${TABLE_PARTS.map(p => `<span data-part-result="${p}" data-result-id="${esc(pr[p].id)}"></span>`).join("")}</span>`;
  return TABLE_PARTS.map(p => (pr[p] ? `<span data-part-result="${p}" data-result-id="${esc(pr[p].id)}"><b>${esc(pn(p))}</b>${P_.c}${provLine(pr[p])}</span>`
    : `<span data-part-result="${p}" class="warnt"><b>${esc(pn(p))}</b>${P_.c}${T("没有存着的结果：这部分的列是空的、行不在表里", "no stored result: its columns are empty and its rows are absent")}</span>`)).join("");
}
/* The freshness strip of a screen: what is stale and why, what still holds, which stored
 * result is drawn, and the jobs that would recompute it.  `parts` are the parts the screen
 * draws, `reports` the stored reports it needs (a missing one says so and offers its job). */
function freshBanner(parts, reports, opts = {}) {
  const fp = fresh().parts, shown = S.state ? S.state.shown : {};
  const missing = reports.filter(r => !shown[r]), repOf = p => { const pi = partInfo(p), j = pi && pi.job && S.parts.jobs[pi.job]; return j ? j.report : null; };
  /* a part whose report is not stored has nothing on screen to call valid, whatever its state reads */
  const stale = parts.filter(p => pstate(p) === "stale"), valid = parts.filter(p => pstate(p) !== "stale" && (!repOf(p) || shown[repOf(p)]));
  const why = [...new Set(stale.flatMap(p => (fp[p].changed || []).map(id => changeText(id, p))))];
  const ups = [...new Set(stale.flatMap(p => fp[p].upstream || []))];
  const upS = ups.filter(u => pstate(u) === "stale"), upO = ups.filter(u => pstate(u) !== "stale");
  const jobs = [...new Set([...stale.map(p => fp[p].recompute).filter(Boolean), ...missing.flatMap(r => (S.parts ? Object.keys(S.parts.jobs).filter(j => S.parts.jobs[j].report === r) : []))])];
  /* the analytic-only preview sits next to the full table's job whenever the analytic part needs recomputing */
  if (jobs.includes("table") && !jobs.includes("table_analytic") && S.parts && S.parts.jobs.table_analytic && parts.some(p => p === "table.analytic" && pstate(p) !== "fresh")) jobs.splice(jobs.indexOf("table") + 1, 0, "table_analytic");
  const stored = [...new Set([...stale, ...ups])].filter(p => fp[p] && fp[p].stored && fp[p].state === "stale");
  const chip = p => `<span class="pchip" data-part="${esc(p)}" data-state="${pstate(p)}">${stateSign(pstate(p))} ${esc(pn(p))}</span>`;
  const runBtn = j => `<button type="button" class="btn" data-act="run" data-job="${esc(j)}">${T("重算", "Recompute")}${P_.c}${jn(j)} · ${expected(j)}</button>`;
  const prov = reports.map(r => (r === "table" && shown.table && shown.table.part_results ? tableProv(shown.table.part_results) : provLine(shown[r]))).filter(Boolean).join("");
  const any = stale.length || missing.length;
  return `<div class="fresh ${any ? "stale" : ""}" role="status" data-state="${any ? "stale" : "fresh"}">
    <span class="st">${any ? (missing.length && !stale.length ? "○ " + T("没有存着的结果", "No stored result") : "◷ " + T("过期", "Stale")) : `<span class="dot"></span>${T("与当前表单一致", "Matches the current form")}`}</span>
    <span class="grow">${why.length ? T("表单改了：", "Changed on the form: ") + "<b>" + why.join(P_.s) + "</b> " + tagEdited() + " " : ""}${upS.length ? `${T("上游结果过期：", "upstream results are stale: ")}${upS.map(u => esc(pn(u))).join(P_.d)}${P_.p}` : ""}${upO.length ? `${T("不是建在现在这份上游结果上：", "not built on the upstream result now stored: ")}${upO.map(u => esc(pn(u))).join(P_.d)}${T("（在它上面重算才对得上）。", " (a recompute on it brings them in step). ")}` : ""}
      ${missing.length ? `${T("这份表单没有存着的", "nothing is stored for this form: ")}${missing.map(r => T(...REPNAME[r])).join(P_.d)}${T("；在运行台排一个任务。", "; queue a job.")}` : ""}
      ${stale.length ? `<span class="hide-s">${T("下面仍是旧表单上算的数字，没有清空。", "The numbers below are still the ones computed for the old form; nothing is blanked.")}</span>` : ""}${opts.note || ""}</span>
    ${any && !opts.noJobs ? jobs.map(runBtn).join("") : ""}
    <span class="l2">${stale.length ? `<span>${T("过期", "Stale")}${P_.c}${stale.map(chip).join(" ")}</span>` : ""}${valid.length ? `<span><span class="ok">${any ? T("仍有效", "Still valid") : T("新鲜", "Fresh")}</span>${P_.c}${valid.map(chip).join(" ")}</span>` : ""}
      ${stored.map(p => `<span>${esc(pn(p))}${P_.c}${T("这里不能重算（要几小时），命令", "cannot be recomputed here (it takes hours); command")} <code>${esc(fp[p].stored.command)}</code>${fp[p].stored.seconds_note ? " · " + esc(fp[p].stored.seconds_note) : ""}</span>`).join("")}
      ${prov}</span></div>`;
}
/* the placeholder of a screen whose report is not stored for this study */
function emptyReport(report) {
  const jobs = S.parts ? Object.keys(S.parts.jobs).filter(j => S.parts.jobs[j].report === report) : [];
  return `<div class="empty" data-empty="${esc(report)}"><b>${T("这份表单还没有算过", "Nothing computed for this form yet")}${P_.c}${T(...REPNAME[report])}</b>
    <span class="mut">${T("排一个后台任务；算完之前这里没有数可显示。", "Queue a background job; there are no numbers to show until it is done.")}</span>
    <span style="display:flex;gap:6px;flex-wrap:wrap">${jobs.map(j => `<button type="button" class="btn pri" data-act="run" data-job="${esc(j)}">${jn(j)} · ${expected(j)}</button>`).join("")}</span></div>`;
}

/* ------------------------------------------------------------------ small HTML helpers */
function tbl(cols, rows, o = {}) {
  const th = cols.map(c => `<th class="${c.r ? "r" : ""}">${c.h}</th>`).join("");
  const tb = rows.map((r, ri) => {
    if (r.__grp) return `<tr class="grp"><td colspan="${cols.length}">${r.__grp}</td></tr>`;
    return `<tr class="${r.__cls || ""}" ${r.__attr || ""}>${cols.map((c, i) => {
      const v = c.f(r, ri);
      return `<td class="${c.r ? "r " : ""}${i === 0 && o.head !== false ? "rt-h " : ""}${c.cls ? c.cls(r) : ""}" data-l="${esc(String(c.h).replace(/<[^>]+>/g, ""))}">${v ?? ""}</td>`;
    }).join("")}</tr>`;
  }).join("");
  return `<div class="tw"><table class="dt rt ${o.cls || ""}"><thead><tr>${th}</tr></thead><tbody>${tb}</tbody></table></div>`;
}
const cmd = c => `<div class="cmd"><code>${esc(c)}</code><button type="button" data-copy="${esc(c)}">${T("复制", "copy")}</button></div>`;
const st = s => (s === "ok" ? `<span class="ok">✓ ok</span>` : `<span class="dg">▲ ${esc(s)}</span>`);
const yes = (b, y, n) => (b === null || b === undefined ? `<span class="mut">n/a</span>` : b ? `<span class="ok">✓ ${y || T("是", "yes")}</span>` : `<span class="dg">✕ ${n || T("否", "no")}</span>`);
const fg = c => `<span class="fg f-${esc(c)}" aria-hidden="true"></span>`;
const seg = (act, cur, opts, hook) => `<span class="seg" role="group">${opts.map(o => `<button type="button" data-act="${act}" data-v="${esc(o[0])}" ${hook ? `${hook}="${esc(o[0])}"` : ""} aria-pressed="${String(o[0]) === String(cur)}">${o[1]}</button>`).join("")}</span>`;
const FOOT = {
  ay: ["链上实测", "measured on the chain"],
  be_if_extender: ["芯片残差实测 + 解析和", "chip residual measured + analytic sum"],
  be_zero_if: ["解析和 + IRR 查表", "analytic sum + IRR lookup"],
};
const TERM = {
  phase_noise: ["相噪", "phase noise"], iq_image: ["IQ 镜像", "IQ image"], converters: ["转换器", "converters"], pa: ["PA", "PA"], isi: ["ISI", "ISI"],
  chip: ["芯片残差", "chip residual"], chip_lo: ["芯片本振", "chip LO"], pa_nonlinearity: ["PA 非线性", "PA nonlinearity"], quantization: ["量化", "quantisation"],
  lo: ["本振", "LO"], fft: ["FFT", "FFT"], decoder: ["解码器", "decoder"], chip_pa: ["芯片 PA", "chip PA"], chip_dpd: ["芯片 DPD", "chip DPD"],
};
const term = k => (TERM[k] ? T(...TERM[k]) : esc(k));
/* the unit a calibration metric's name ends in (the payload names the metric, not its unit) */
/* the unit of a calibration reading is the cell's own field (guiutil.metric_unit) */
function metricUnit(x) { return (x && x.unit) || ""; }
const badge = topo => { const A = topo === "if_extender"; return `<span class="tb ${A ? "A" : "B"}" title="${A ? T("拓扑 A：IF 延伸", "Topology A: IF extender") : T("拓扑 B：升频零中频", "Topology B: upclocked zero-IF")}"><i>${A ? "A" : "B"}</i></span>`; };
const wfsw = wf => `<span class="sw" style="background:var(--${wf === "ay_sc" ? "sc" : "ofdm"})"></span>`;
const wfn = wf => (wf === "ay_sc" ? "SC" : wf === "ay_ofdm" ? "OFDM" : esc(wf));

/* ------------------------------------------------------------------ toast, popover, tooltip */
let toastTimer = null;
function toast(msg, err) {
  const el = $("toast"); el.textContent = String(msg); el.className = "toast" + (err ? " err" : ""); el.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { el.hidden = true; }, err ? 9000 : 3500);
}
const showError = e => toast(e && e.message ? e.message : e, true);
let pinned = false;
function place(el, x, y) { el.hidden = false; const r = el.getBoundingClientRect(); el.style.left = Math.max(8, Math.min(x, innerWidth - r.width - 8)) + "px"; el.style.top = (y + r.height + 8 > innerHeight ? Math.max(8, y - r.height - 26) : y) + "px"; }
function showPop(tg, pin) {
  const key = tg.dataset.k, s = S.sources && S.sources[key]; if (!s) return;
  const val = typeof s.value === "object" ? JSON.stringify(s.value) : String(s.value);
  $("pop").innerHTML = `<div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">${tagPlain(s.source)}<span class="k">${esc(key)}</span></div>
    <div class="n" style="margin-top:5px;overflow-wrap:anywhere">${esc(val.length > 150 ? val.slice(0, 150) + "…" : val)}${typeof s.value === "object" ? "" : " " + esc(s.unit)}</div>
    ${s.cite ? `<div class="c"><b>${T("出处", "Cite")}</b> ${esc(s.cite)}</div>` : ""}${s.note ? `<div class="c"><b>${T("注", "Note")}</b> ${esc(s.note)}</div>` : ""}`;
  const r = tg.getBoundingClientRect(); place($("pop"), r.left, r.bottom + 6); pinned = !!pin;
}
function hidePop(force) { if (force || !pinned) { $("pop").hidden = true; pinned = false; } }
