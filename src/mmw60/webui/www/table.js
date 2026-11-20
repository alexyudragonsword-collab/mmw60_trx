/* Screen: the comparison table (home).  One metric emphasised at a time, a shape per row for
 * its footing, the time-domain cross-check on every row, stale marked per column and cell.
 * Rows are sorted and filtered on fields the report carries; no number is derived here. */
"use strict";
const pct = (v, a, b) => Math.max(0, Math.min(100, (v - a) / ((b - a) || 1) * 100));
const pctLog = (v, a, b) => pct(Math.log10(v), Math.log10(a), Math.log10(b));
const tableRows = R => [...R.rows, ...R.ay_rows];
const isAy = r => r.footing === "ay";

/* what the three metric columns show for one row under the chosen cap basis: which payload
 * fields, and the group of fields each belongs to (for the stale marks) */
function rowMetrics(r, W) {
  const R = W.report, rg = (W.ranges || {})[r.label] || null, ay = isAy(r), fs = f => fieldState(R, f, ay), fg_ = f => fieldGroup(R, f, ay), arr = pstate("array");
  const pj = p => (p ? p.pj_per_bit : null);
  let m;
  if (S.basis === "conf") {
    m = ay ? { capRaw: mcs(r.cap_raw), capCal: mcs(r.cap_cal), rateRaw: r.rate_raw_mbps, rateCal: r.rate_cal_mbps, pjRaw: pj(r.power_raw), pjCal: pj(r.power_cal), sRaw: fs("cap_raw"), sCal: fs("cap_cal") }
      : { capRaw: mcs(r.max_mcs), capCal: mcs(r.max_mcs_cal), rateRaw: r.rate_mbps, rateCal: r.rate_cal_mbps, pjRaw: pj(r.power), pjCal: pj(r.power_cal), sRaw: fs("max_mcs"), sCal: fs("max_mcs_cal") };
  } else {
    m = ay ? { capRaw: "—", capCal: rg ? mcs(rg.cap_mcs) : "—", rateRaw: null, rateCal: rg ? rg.rate_mbps : null, pjRaw: null, pjCal: rg ? rg.pj_per_bit : null, sRaw: "fresh", sCal: arr, fromArray: true }
      : { capRaw: r.dec_cap_display || "—", capCal: r.dec_cap_cal_display || "—", rateRaw: r.dec_rate_mbps, rateCal: r.dec_rate_cal_mbps, pjRaw: pj(r.power_dec), pjCal: pj(r.power_dec_cal), sRaw: fs("dec_mcs"), sCal: fs("dec_mcs_cal") };
  }
  const cal = S.chain === "cal";
  return Object.assign(m, { ay, rg, rate: cal ? m.rateCal : m.rateRaw, pj: cal ? m.pjCal : m.pjRaw, range: rg ? (ay ? rg.range_mcs1_m : rg.range_mcs0_m) : null, sRange: arr,
    partRaw: m.fromArray ? "array" : fg_(S.basis === "conf" ? "max_mcs" : "dec_mcs"), partCal: m.fromArray ? "array" : fg_(S.basis === "conf" ? "max_mcs_cal" : "dec_mcs_cal") });
}
function rowName(r, R) {
  const b = badge(r.topology);
  if (isAy(r)) return {
    l1: `${b}<span>${wfsw(r.waveform)}802.11ay ${wfn(r.waveform)}</span><span class="arrow">${T("信道", "ch.")} ${plain(r.channel)} · ${mhz(r.bw_eff_hz)} MHz</span>`,
    l2: `${esc(r.label)} · ${T("占用", "occupied")} ${mhz(r.occupied_bw_hz)} MHz · ${plain(r.fs_eff_hz / 1e9)} GS/s` };
  return {
    l1: `${b}<span>${esc(r.standard)} ${mhz(r.base_bw_hz)} M${r.k > 1 ? ` ×${r.k}` : ""}</span><span class="arrow">→ ${mhz(r.bw_eff_hz)} MHz</span>`,
    l2: `${esc(r.label)} · SCS ${hz(r.scs_eff_hz)} · ${secs(r.t_symbol_eff_s)}` };
}
function homeRow(x, ctx) {
  const { r, m } = x, R = ctx.R, d = R.display, fc = r.footing, ay = m.ay, nm = rowName(r, R), cal = S.chain === "cal", fs = f => fieldState(R, f, ay), svf = (f, html) => svField(R, f, ay, html);
  const chips = [];
  if (!ay) {
    if (r.usable === false) chips.push(`<span class="vd no">✕ ${T("未校准链不能：", "raw chain fails: ")}${esc(tr(r.reason))}</span>`);
    else if (r.reason) chips.push(`<span class="vd">${esc(tr(r.reason))}</span>`);
    const best = R.be_best_at_calibrated_cap || {};
    if (best.fastest === r.label) chips.push(`<span class="vd best">${T("be 行里最快（校准后合规上限）", "fastest be row (calibrated conformance cap)")}</span>`);
    if (best.fewest_pj_per_bit === r.label) chips.push(`<span class="vd best">${T("be 行里每比特最省（校准后合规上限）", "fewest pJ/bit of the be rows (calibrated conformance cap)")}</span>`);
  } else if (nil(r.cap_raw)) chips.push(`<span class="vd no">✕ ${T("未校准链够不到任何一档", "raw chain reaches no MCS")}</span>`);
  /* EVM floor raw -> calibrated, with how the calibrated end was obtained and the time-domain check */
  const a = ay ? r.floor_raw_worst_db : r.floor_db, b = ay ? r.floor_cal_worst_db : r.floor_cal_db, fd = ay ? d.ay_floor_db : d.floor_db;
  const pa = pct(a, ...ctx.floorDom), pb = pct(b, ...ctx.floorDom);
  let how;
  if (fc === "be_zero_if") how = svf("irr_cal_db", `<span class="lookup">${T("查表", "lookup")} IRR ${fx(r.irr_cal_db, d.irr_cal_db)} dB @${mhz(r.irr_cal_measured_at_hz)} MHz</span>`) + (r.irr_cal_measured_at_hz !== r.bw_eff_hz ? ` <span class="dg">≠ ${T("本行带宽", "this row’s BW")}</span>` : "");
  else if (fc === "be_if_extender") how = T("芯片建链时已校准，两列相同", "chip calibrated at build; both columns equal");
  else how = svf("cal_irr_db", `${T("链上实测", "measured")}: IRR ${fx(r.cal_irr_db, 1)} dB · ${T("LO 泄漏", "LO leak")} ${fx(r.cal_lo_leak_dbc, 1)} dBc`);
  const td = ay ? `<div class="s">${T("两头都是时域读数", "both ends are time-domain readings")}</div>`
    : `<div class="s">${svf("td_evm_db", `${T("时域核对", "time-domain check")} <span class="n">${fx(r.td_evm_db, d.td_evm_db)} dB</span> ${r.td_ok === true ? st("ok") : r.td_ok === false ? `<span class="dg">✕ Δ ${fx(r.td_delta_db, d.td_delta_db)} dB</span>` : `<span class="mut">n/a</span>`}`)}</div>`;
  const floor = `<div class="v">${sv(fs(ay ? "floor_raw_db" : "floor_db"), fx(a, fd), ay ? "table.ay" : "table.analytic")} → ${svf("floor_cal_db", `<b class="${fc === "be_zero_if" ? "lookup" : ""}">${fx(b, fd)}</b>`)} <span class="mut">dB</span></div>
      <div class="trk" aria-hidden="true"><span class="ln" style="left:${Math.min(pa, pb)}%;width:${Math.abs(pa - pb)}%"></span><span class="raw" style="left:${pa}%"></span><span class="cal fg f-${fc}" style="left:${pb}%"></span></div>
      <div class="s">${how}</div>${td}`;
  /* cap, rate, pJ/bit: raw -> calibrated side by side, the chosen column set bold */
  const pair = (va, vb, sa, sb) => (cal ? `<span>${sv(sa, va, m.partRaw)} →</span> ${sv(sb, `<b>${vb}</b>`, m.partCal)}` : `${sv(sa, `<b>${va}</b>`, m.partRaw)} <span>→ ${sv(sb, vb, m.partCal)}</span>`);
  let capS = "";
  if (ay && S.basis === "conf") capS = `${T("不留余量", "no margin")} ${mcs(r.cap_cal_at_limit)}`;
  else if (ay) capS = m.rg ? T("取自阵列结果的单天线一行", "from the array result’s one-element row") : "";
  else if (S.basis === "dec") capS = `${T("离上一档", "to next step")} ${fx(cal ? r.dec_cal_next_margin_db : r.dec_next_margin_db, d.dec_next_margin_db)} dB`;
  const rd = ay ? 0 : d.rate_mbps;
  let rateS = "";
  if (nil(m.rate)) rateS = ay && S.basis === "dec" ? T("这一列没有算", "not computed for this column") : T("够不到任何一档", "reaches no MCS");
  else if (ay && S.basis === "conf" && cal) rateS = `${T("不留余量", "no margin")} ${fx(r.rate_cal_at_limit_mbps, 0)}`;
  let pjS = nil(m.pj) ? (nil(m.rate) ? "" : T("未算", "not computed")) : (ctx.R.footing[fc].decoder_counted_in_pj === false ? `<span class="dg">${T("不计解码器", "decoder not counted")}</span>` : T("计解码器", "decoder counted"));
  const rg = m.rg, slow = ay ? "MCS1" : "MCS0";
  const cells = {
    rate: `<span class="lab">${T("速率", "Rate")}</span><div class="v">${pair(fx(m.rateRaw, rd), fx(m.rateCal, rd), m.sRaw, m.sCal)} <span class="mut">Mb/s</span></div>${nil(m.rate) ? "" : `<div class="bar" style="width:${pct(m.rate, 0, ctx.mx.rate)}%"></div>`}<div class="s">${rateS}</div>`,
    pj: `<span class="lab">pJ/bit</span><div class="v">${pair(fx(m.pjRaw, d.pj_per_bit), fx(m.pjCal, d.pj_per_bit), m.sRaw, m.sCal)}</div>${nil(m.pj) ? "" : `<div class="trk" aria-hidden="true"><span class="pt" style="left:${pctLog(m.pj, ...ctx.pjDom)}%"></span></div>`}<div class="s">${pjS}</div>`,
    range: `<span class="lab">${T("距离（单天线）", "Range (single antenna)")}</span>` + (rg
      ? `<div class="v">${sv(m.sRange, sig(m.range), "array")} <span class="mut">m @${slow}</span></div><div class="bar" style="width:${pct(m.range, 0, ctx.mx.range)}%"></div><div class="s">${sv(m.sRange, `${sig(rg.range_cap_m)} m @${mcs(rg.cap_mcs)}${ay ? ` · ${sig(rg.range_common_m)} m @16-QAM 3/4` : ""}`, "array")}</div>`
      : `<div class="v">—</div><div class="s">${ctx.W.ranges ? T("未算：阵列结果里没有这一行", "not computed: the array result does not carry this row") : T("没有存着的阵列结果", "no array result is stored")}</div>`),
  };
  const order = ["rate", "pj", "range"], rest = order.filter(k => k !== S.lens);
  const cls = k => (k === S.lens ? "lens" : k === rest[0] ? "m1" : "m2");
  const open = S.open[r.label] ?? (ctx.phone && ctx.first === r.label);
  return `<div class="row ${S.sel === r.label ? "sel" : ""} ${open ? "open" : ""}" role="row" tabindex="0" data-label="${esc(r.label)}" ${x.usable ? "" : 'data-usable="false"'} data-act="detail" data-v="${esc(r.label)}">
    <div class="rk" role="cell">${x.rank ?? "–"}</div>
    <div class="nm" role="cell"><div class="l1">${nm.l1}</div><div class="l2">${nm.l2}</div>${chips.length ? `<div class="l3">${chips.join("")}</div>` : ""}</div>
    <div class="ft" role="cell" title="${esc(T(...FOOT[fc]))}">${fg(fc)}<span class="t">${T(...FOOT[fc])}</span></div>
    <div class="cell x1" role="cell"><span class="lab">${T("EVM 底板 未校准 → 校准后", "EVM floor raw → calibrated")}</span>${floor}</div>
    <div class="cell capc x2" role="cell"><span class="lab">${S.basis === "conf" ? T("合规上限 未校准 → 校准后", "Conformance cap raw → calibrated") : T("解码器上限 未校准 → 校准后", "Decoder cap raw → calibrated")}</span><div class="v">${pair(m.capRaw, m.capCal, m.sRaw, m.sCal)}</div><div class="s">${capS}</div></div>
    <div class="cell ${cls("rate")}" role="cell">${cells.rate}</div>
    <div class="cell ${cls("pj")}" role="cell">${cells.pj}</div>
    <div class="cell ${cls("range")}" role="cell">${cells.range}</div>
    <button type="button" class="more" data-act="open" data-v="${esc(r.label)}">${open ? T("收起", "less") : T("底板与口径 ▾", "floor and footing ▾")}</button>
  </div>`;
}
/* the one front end every row shares, as the stored table result was computed on it */
function feStrip(W, open) {
  const FE = W.report.front_end, sk = FE.source_keys, der = new Set(FE.derived_fields || []), stale = fresh().fields["table.analytic"] === "stale";
  const dd = (k, v, tg) => `<div><dt>${k}</dt><dd>${v}</dd>${tg || ""}</div>`, tg = f => (der.has(f) ? tagPlain("derived") : sk[f] ? tag(sk[f]) : "");
  const cnt = S.counts || {};
  return `<details class="fe" ${open ? "open" : ""}><summary><b>${T("一个 60 GHz 前端实例，每一行共用", "One 60 GHz front-end instance shared by every row")}</b>
      <span class="mut">${T("表里的数都算在它上面", "every number in the table is computed on it")}</span>${stale ? ` <span class="dg sm" data-state="stale" data-part="table.analytic">◷ ${T("这是存着的结果用的前端，表单已经改了", "this is the front end of the stored result; the form has moved on")}</span>` : ""}
      <span class="cnt">${T("规范表", "Spec table")}${P_.c}${["spec", "assumed", "derived", "survey"].map(s => `${tagPlain(s)} ${plain(cnt[s])}`).join(" ")}</span></summary>
    <div class="fe-grid">
      <div><span class="eyebrow">${T("载频", "Carrier")}</span><dl>${dd(T("载频", "carrier"), hz(FE.carrier_hz))}</dl></div>
      <div><span class="eyebrow">PA · ${esc(FE.pa_model)}</span><dl>
        ${dd("Psat", `${fx(FE.psat_dbm, 1)} dBm`, tg("psat_dbm"))}${dd(T("增益", "gain"), `${fx(FE.pa_gain_db, 1)} dB`, tg("pa_gain_db"))}
        ${dd(`${T("回退", "back-off")} (${esc(FE.obo_reference)})`, `${fx(FE.obo_db, 1)} dB`, (FE.edited || []).includes("frontend.pa.obo_db") ? tagEdited() : tg("obo_db"))}
        ${dd("Pout", `${fx(FE.pout_dbm, 1)} dBm`, tg("pout_dbm"))}${dd(T("PA 单独 EVM", "PA-alone EVM"), `${fx(FE.pa_isolated_evm_db, 1)} dB`, tg("pa_isolated_evm_db"))}</dl></div>
      <div><span class="eyebrow">${T("本振", "LO")} · ${esc(FE.lo_profile)}</span><dl>
        ${dd(T("积分相噪 IPN", "integrated PN"), `${fx(FE.lo_ipn_dbc, 1)} dBc`, tg("lo_ipn_dbc") + " " + tag(sk.lo))}
        ${dd(T("TX LO 泄漏", "TX LO leak"), `${fx(FE.tx_lo_leak_dbc, 1)} dBc`, tg("tx_lo_leak_dbc"))}${dd(T("RX 直流", "RX DC"), `${fx(FE.rx_dc_dbc, 1)} dBc`, tg("rx_dc_dbc"))}
        ${dd(T("转换器", "converters"), `ENOB ${plain(FE.converters.enob_ref)} @${hz(FE.converters.fs_ref_hz)} · −${plain(FE.converters.bits_per_octave)} bit/oct`, tag(sk.converters))}</dl></div>
      <div><span class="eyebrow">${T("接收前端", "Receive front end")}</span><dl>
        ${dd(T("增益", "gain"), `${fx(FE.rx_front.gain_db, 1)} dB`, tag(sk.rx_front))}${dd("NF", `${fx(FE.rx_front.nf_db, 1)} dB`, tag(sk.rx_front))}${dd("IIP3", `${fx(FE.rx_front.iip3_dbm, 1)} dBm`, tag(sk.rx_front))}
        ${dd(T("取哪颗芯片的数", "which chip’s numbers"), "", tag(sk.rx_front_pick))}</dl></div>
      <div><span class="eyebrow">${T("天线与 EIRP", "Antenna and EIRP")}</span><dl>
        ${dd(T("天线 发 / 收", "antenna TX / RX"), `${fx(FE.antenna_gain_tx_dbi, 1)} / ${fx(FE.antenna_gain_rx_dbi, 1)} dBi`, tag(sk.antenna))}${dd(T("单天线 EIRP", "single-antenna EIRP"), `${fx(FE.eirp_dbm, 1)} dBm`, tg("eirp_dbm"))}
        ${dd(T("平均上限", "average limit"), `${fx(FE.eirp_limit_avg_dbm, 1)} dBm`, tg("eirp_limit_avg_dbm"))}${dd(T("余量", "margin"), `${fx(FE.eirp_margin_db, W.report.display.eirp_margin_db)} dB`, tg("eirp_margin_db"))}</dl></div>
    </div></details>`;
}
/* Which guesses decide: the analytic side rerun at each end of each knob (computed with the table
 * job).  One line per knob end: how many rows' caps moved, how far pJ/bit moved, whether the
 * ranking changed.  It is part of table.analytic and goes stale with it. */
function sensSection(R) {
  const SN = R.sensitivity, ps = pstate("table.analytic"), m = v => sv(ps, v, "table.analytic"), d = R.display.pj_ratio;
  const head = `<header><h3>${T("哪些猜测决定结论", "Which guesses decide the verdict")}</h3><span class="mut sm">${T("每个假设拨到它的两头，解析一侧重算一遍；先看这里，再去改表单", "each guess moved to its ends and the analytic side rerun; look here before turning a knob")}</span></header>`;
  if (!SN) return `<section class="blk" id="sens" data-part="table.analytic" data-state="${ps}">${head}<p class="mut">${T("正在显示的这份结果里没有这一节。排一个同台表任务就有。", "The result shown does not carry this section. A comparison-table job computes it.")}</p>
    <span><button type="button" class="btn" data-act="run" data-job="table">${T("重算", "Recompute")}${P_.c}${jn("table")} · ${expected("table")}</button></span></section>`;
  const keys = s => String(s || "").split(" / ").map(p => { const k = /^[\w.]+/.exec(p.trim()); return k && S.sources && S.sources[k[0]] ? tag(k[0]) + esc(p.trim().slice(k[0].length)) : esc(p.trim()); }).join(" ");
  const moved = (list, kind) => `<div class="cellv"><span data-sens-moved="${kind}" class="${list.length ? "" : "mut"}">${m(`<b>${list.length}</b>`)}</span> ${T("行", "rows")}${list.length ? `<details class="mv"><summary>${T("哪几行", "which")}</summary>${list.map(x => `<div class="xs"><code>${esc(x.label)}</code> ${mcs(x.from)} → ${mcs(x.to)}</div>`).join("")}</details>` : ""}</div>`;
  const decides = new Set(SN.decides || []);
  return `<section class="blk" id="sens" data-part="table.analytic" data-state="${ps}">${head}
    <p class="note">${esc(T(SN.decoder_basis.zh, SN.decoder_basis.en))}</p>
    ${tbl([{ h: T("假设（基线值的出处）", "Guess (source of the baseline value)"), f: k => `<span class="cellv">${esc(tr(k.knob))} ${keys(k.source_key)}</span>` },
      { h: T("拨到", "Moved to"), r: 1, f: k => neg(esc(k.value_text)) },
      { h: T("合规上限移动的行", "Rows whose conformance cap moves"), f: k => moved(k.mcs_moved || [], "conf") },
      { h: T("解码器上限移动的行", "Rows whose decoder cap moves"), f: k => moved(k.dec_mcs_moved || [], "dec") },
      { h: T("pJ/bit 倍数（各行最小 – 最大）", "pJ/bit ratio (min – max over rows)"), r: 1, f: k => (nil(k.pj_ratio_min) ? "—" : m(`${fx(k.pj_ratio_min, d)} – ${fx(k.pj_ratio_max, d)}`)) },
      { h: T("pJ/bit 排名变了", "pJ/bit ranking changed"), f: k => (k.ranking_changed ? m(`<span class="dg">${T("变", "yes")}</span>`) : `<span class="mut">${T("不变", "no")}</span>`) },
    ], SN.knobs.map(k => Object.assign({}, k, { __attr: `data-sens-knob="${esc(k.knob + "|" + k.value_text)}"`, __cls: decides.has(k.knob) ? "" : "dim" })), { head: false })}
    <p class="xs mut" data-sens-decides>${T("至少一头动了某一行的上限或 pJ/bit 排名的假设", "Guesses with an end that moves some row’s cap or the pJ/bit ranking")}${P_.c}${m([...decides].map(k => esc(tr(k))).join(P_.d) || "—")}${T("；灰色的行 = 两头都不动。", "; a grey line = neither end moves anything.")}</p>
    <details class="fold"><summary>${T("基准的 pJ/bit 排名（最省在前）", "The base pJ/bit ranking (fewest first)")}</summary><div><ol class="plain">${(SN.base_ranking || []).map(l => `<li><code>${esc(l)}</code></li>`).join("")}</ol></div></details></section>`;
}
function renderTable() {
  const W = S.rep.table;
  if (!W) return `<div class="page"><div class="loading"><span class="spin"></span>${T("正在读取同台表…", "Loading the comparison table…")}</div></div>`;
  const parts = ["table.analytic", "table.td", "table.ay", "calibration.be", "thresholds.be", "array"];
  if (!W.report) return `<div class="page"><div class="phead"><h2>${T("同台对比表", "Side-by-side comparison")}</h2></div>${freshBanner(parts, ["table"], { noJobs: true })}${emptyReport("table")}</div>`;
  const R = W.report, phone = isPhone(), FE = R.front_end;
  const every = tableRows(R).map((r, i) => ({ r, m: rowMetrics(r, W), i }));
  const FILT = { all: () => true, A: r => r.topology === "if_extender", B: r => r.topology === "upclock_zero_if" && !isAy(r) && r.carrier_hz === FE.carrier_hz, ay: r => isAy(r), ref: r => !isAy(r) && r.carrier_hz !== FE.carrier_hz };
  const key = { rate: x => x.m.rate, pj: x => x.m.pj, range: x => x.m.range }[S.lens], dir = S.lens === "pj" ? 1 : -1;
  const byLens = (a, b) => { const va = key(a), vb = key(b); if (nil(va) && nil(vb)) return a.i - b.i; if (nil(va)) return 1; if (nil(vb)) return -1; return dir * (va - vb) || a.i - b.i; };
  /* a row that cannot carry data (usable: false) keeps its numbers but comes after the usable rows
   * whatever the sort key, takes no rank and does not set a bar's full width */
  every.forEach(x => { x.usable = x.r.usable !== false; });
  const all = every.filter(x => FILT[S.filt](x.r)), last = (a, b) => (a.usable === b.usable ? 0 : a.usable ? -1 : 1);
  const ranked = [...all].sort((a, b) => last(a, b) || byLens(a, b)); let rk = 0; ranked.forEach(x => { x.rank = !x.usable || nil(key(x)) ? null : ++rk; });
  const shown = S.keep ? [...all].sort((a, b) => last(a, b) || a.i - b.i) : ranked, good = all.filter(x => x.usable);
  const fl = every.flatMap(x => (x.m.ay ? [x.r.floor_raw_worst_db, x.r.floor_cal_worst_db] : [x.r.floor_db, x.r.floor_cal_db]));
  const ctx = { W, R, phone, first: shown.length ? shown[0].r.label : null, mx: { rate: Math.max(...good.map(x => x.m.rate ?? 0), 1e-9), range: Math.max(...good.map(x => x.m.range ?? 0), 1e-9) },
    floorDom: span(fl, 2, 1), pjDom: logSpan(every.flatMap(x => [x.m.pjRaw, x.m.pjCal])) };
  const f = fresh().fields, anyStale = Object.values(f).some(v => v === "stale") || pstate("array") === "stale";
  const hs = on => (on ? ` <span class="hst" data-state="stale" title="${T("这一列有过期的格", "this column has stale cells")}">◷</span>` : "");
  const colS = all.some(x => x.m.sRaw === "stale" || x.m.sCal === "stale");
  const cnt = c => every.filter(x => x.r.footing === c).length, nf = k => every.filter(x => FILT[k](x.r)).length;
  const arrow = k => (S.lens === k ? (S.keep ? " ●" : k === "pj" ? " ↑" : " ↓") : "");
  const mg = R.margins || {};
  const irr = R.irr_table || { db_by_bandwidth_hz: {} };
  /* a partial run (analytic columns only) is shown as what it is: its missing parts are named, not left as silent gaps */
  const lacks = ["table.analytic", "table.td", "table.ay"].filter(p => W.result && !W.result.parts.includes(p));
  const partial = lacks.length ? ` <b class="dg" data-partial="${esc(lacks.join(" "))}">${T("正在显示的这份结果没有算", "The result shown did not compute")}${P_.c}${lacks.map(p => esc(pn(p))).join(P_.d)}${T("——对应的列是空的、对应的行不在表里；排一个整表任务补上。", " — those columns are empty and those rows are absent; queue the full table to fill them.")}</b>` : "";
  const body = `
    <div class="phead"><div><h2>${T("同台对比表", "Side-by-side comparison")}</h2>
      <p class="sub hide-s">${T(`${every.length} 行有数，${R.pending.length} 个组合没有数（原因在表尾）。同一行里“未校准 → 校准后”并排；方块标记说明校准后的数是怎么来的。点一行看细节。`,
    `${every.length} rows with numbers, ${R.pending.length} combinations without (reasons at the end of the table). Raw → calibrated sit side by side; the square marker says how the calibrated number was obtained. Click a row for its detail.`)}</p></div></div>
    ${freshBanner(parts, ["table", "array"], { note: partial })}
    ${feStrip(W, !phone)}
    <div class="ctl">
      <span class="seglab"><span>${T("排序并突出", "Sort and highlight")}</span> ${seg("lens", S.lens, [["rate", T("速率", "Rate")], ["range", T("距离", "Range")], ["pj", "pJ/bit"]])}</span>
      <span class="seglab"><span class="hide-s">${T("上限口径", "Cap basis")}</span> ${seg("basis", S.basis, [["conf", `${T("合规：TX EVM 限值留", "Conformance: TX EVM limit less")} ${plain(mg.mcs_evm_margin_db)} dB`], ["dec", `${T("解码器：留", "Decoder: margin")} ${plain(mg.decoder_cap_margin_db)} dB`]])}</span>
      <span class="seglab"><span class="hide-s">${T("取哪一列", "Column")}</span> ${seg("chain", S.chain, [["raw", T("未校准", "Raw")], ["cal", T("校准后", "Calibrated")]])}</span>
    </div>
    <div class="ctl">
      <span class="seglab"><span>${T("只看", "Show")}</span> ${seg("filt", S.filt, [["all", `${T("全部", "All")} ${nf("all")}`], ["A", `${T("拓扑 A", "Topology A")} ${nf("A")}`], ["B", `${T("拓扑 B", "Topology B")} ${nf("B")}`], ["ay", `802.11ay ${nf("ay")}`], ["ref", `${T("6 GHz 参考", "6 GHz reference")} ${nf("ref")}`]])}</span>
      <label class="chk"><input type="checkbox" data-toggle="keep" ${S.keep ? "checked" : ""}> ${T("保持原顺序，只突出", "Keep the original order, highlight only")}</label>
      ${anyStale ? `<span class="sm legend-stale"><span class="sv">${T("斜纹底", "hatched")}</span> = ${T("过期的数（它来自的那份结果读了改过的旋钮）；没有底纹的仍然可信", "stale number (the result it comes from reads an edited knob); numbers without the hatch still hold")}</span>` : ""}
    </div>
    <div class="legend" aria-label="${T("口径图例", "Footing legend")}">
      ${["ay", "be_if_extender", "be_zero_if"].map(c => `<span title="${esc(tr(R.footing[c].cal_floor))}">${fg(c)}<b>${T(...FOOT[c])}</b> · ${cnt(c)} ${T("行", "rows")}<span class="hide-s">${P_.c}${esc(tr(R.footing[c].cal_floor))}</span></span>`).join("")}
    ${every.some(x => !x.usable) ? `<span class="dimkey">${T("变淡的行 = 未校准链带不了数据：数照旧，排在可用的行之后，不参与排名", "dimmed row = the raw chain cannot carry data: its numbers stay, it sorts after the usable rows and takes no rank")}</span>` : ""}
    </div>
    <div class="ct" role="table" aria-label="${T("同台对比表", "Comparison table")}">
      <div class="hrow" role="row"><span></span><span>${T("方案 · 未校准链的结论", "Scheme · verdict on the raw chain")}</span><span>${T("口径", "Footing")}</span>
        <span>${T("EVM 底板 dB　○ 未校准 →", "EVM floor dB　○ raw →")} ${fg("be_zero_if")}${fg("be_if_extender")}${fg("ay")} ${T("校准后", "calibrated")}${hs(["table.analytic", "table.analytic+calibration.be", "table.td", "table.ay"].some(g => f[g] === "stale"))}<span class="ax"><span>${plain(ctx.floorDom[0])}</span><span>${plain(ctx.floorDom[1])}</span></span></span>
        <span>${S.basis === "conf" ? T("合规上限", "Conformance cap") : T("解码器上限", "Decoder cap")}${hs(colS)}</span>
        <span><button type="button" data-act="lens" data-v="rate" class="${S.lens === "rate" ? "on" : ""}">${T("速率", "Rate")} Mb/s${arrow("rate")}</button>${hs(colS)}</span>
        <span><button type="button" data-act="lens" data-v="pj" class="${S.lens === "pj" ? "on" : ""}">pJ/bit${arrow("pj")}</button>${hs(colS)}<span class="ax"><span>${plain(ctx.pjDom[0])}</span><span>${plain(ctx.pjDom[1])}</span></span></span>
        <span><button type="button" data-act="lens" data-v="range" class="${S.lens === "range" ? "on" : ""}">${T("距离", "Range")} m${arrow("range")}</button>${hs(pstate("array") === "stale" && all.some(x => x.m.rg))}</span></div>
      ${shown.map(x => homeRow(x, ctx)).join("")}
      ${S.filt !== "all" ? "" : R.pending.map(n => `<div class="narow" data-pending="${esc(n.label)}"><code>${esc(n.label)}</code><span>${esc(n.status)}</span><span>${esc(n.reason)}</span></div>`).join("")}
    </div>
    ${sensSection(R)}
    <details class="fold"><summary>${T("表背后的三张小表：IRR 查表、余量、功耗系数", "Three small tables behind this one: the IRR lookup, the margins, the power coefficients")}</summary><div class="g3">
      <div><div class="eyebrow">${T("校准后的 IRR，按带宽查", "IRR after calibration, looked up by bandwidth")} · ${T("取自", "from")} <code>${esc(irr.from || "")}</code> ${(irr.from || "").includes(".") ? tag(irr.from) : ""}</div>
        ${tbl([{ h: T("带宽", "Bandwidth"), f: e => hz(Number(e[0])) }, { h: "IRR dB", r: 1, f: e => sv(f["table.analytic+calibration.be"], fx(e[1], R.display.irr_cal_db), "table.analytic+calibration.be") }], Object.entries(irr.db_by_bandwidth_hz || {}))}</div>
      <div><div class="eyebrow">${T("两种上限各留的余量", "Margin kept by each kind of cap")}</div>
        <dl class="kv" style="margin-top:6px"><dt>${T("合规上限", "conformance cap")}</dt><dd class="n">${plain(mg.mcs_evm_margin_db)} dB ${tag("assumed.mcs_evm_margin_db")}</dd><dt>${T("解码器上限", "decoder cap")}</dt><dd class="n">${plain(mg.decoder_cap_margin_db)} dB ${tag("assumed.decoder_cap_margin_db")}</dd></dl></div>
      <div><div class="eyebrow">${T("功耗模型的系数", "Coefficients of the power model")}</div>
        <dl class="kv" style="margin-top:6px">${Object.entries(R.coefficients || {}).map(([k, v]) => `<dt><code>${esc(k)}</code></dt><dd class="n">${plain(v)}</dd>`).join("")}</dl></div>
    </div></details>`;
  return `<div class="page">${body}</div>`;
}
