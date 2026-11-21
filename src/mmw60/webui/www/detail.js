/* Screens: one comparison-table row opened (the `row` payload), and the calibration runs
 * (report "calibration").  Two verdicts per calibration step are kept apart everywhere:
 * wifitrx's own, and this library's summary rule. */
"use strict";
const calReport = () => (S.screen === "row" ? (S.row && S.row.calibration) : (S.rep.calibration && S.rep.calibration.report));
/* the operating points a row carries a power breakdown for */
function powerPoints(r) {
  if (isAy(r)) return [{ name: T("合规上限 · 未校准", "Conformance cap · raw"), cap: mcs(r.cap_raw), p: r.power_raw, f: "power_raw" }, { name: T("合规上限 · 校准后", "Conformance cap · calibrated"), cap: mcs(r.cap_cal), p: r.power_cal, f: "power_cal" },
    { name: T("解码器上限 · 未校准", "Decoder cap · raw"), cap: mcs(r.dec_mcs), p: r.power_dec, f: "power_dec" }, { name: T("解码器上限 · 校准后", "Decoder cap · calibrated"), cap: mcs(r.dec_mcs_cal), p: r.power_dec_cal, f: "power_dec_cal" }];
  return [{ name: T("合规上限 · 未校准", "Conformance cap · raw"), cap: mcs(r.max_mcs), p: r.power, f: "power" }, { name: T("合规上限 · 校准后", "Conformance cap · calibrated"), cap: mcs(r.max_mcs_cal), p: r.power_cal, f: "power_cal" },
    { name: T("解码器上限 · 未校准", "Decoder cap · raw"), cap: r.dec_cap_display || "—", p: r.power_dec, f: "power_dec" },
    { name: T("解码器上限 · 校准后", "Decoder cap · calibrated"), cap: r.dec_cap_cal_display || "—", p: r.power_dec_cal, f: "power_dec_cal" }];
}
const BUDGET_KEY = { pa: "pa_nonlinearity", converters: "quantization" };
/* a step's two verdicts, side by side */
const verdicts = x => `<span class="vv" title="wifitrx · ${T("汇总表", "summary")}">wifitrx ${st(x.status_wifitrx)} · ${T("汇总", "summary")} ${st(x.status_summary)}</span>`;
const stepVal = (x, d = 1) => (nil(x.value) ? `<small>${T("无指标", "no metric")}</small>` : `${fx(x.value, d)} ${metricUnit(x)} <small>${esc(x.metric || "")}</small>`);
function statusRule(C) {
  const sr = C.status_rule;
  return `<b>wifitrx</b>${P_.c}${esc(bi(sr, "status_wifitrx"))}<br><b>${T("汇总表", "summary table")}</b>${P_.c}${esc(bi(sr, "status_summary"))}`;
}
function calMatrix(C, col) {
  return `<figure class="calmx"><div class="eyebrow">${C.steps.length} ${T("步", "steps")} × ${C.columns.length} ${T("列：哪一步在哪一列退化", "columns: which step degrades where")}</div><div class="chartbox" data-chart="calmx" data-col="${esc(col || "")}"></div>
    <figcaption class="xs mut"><span class="mxl ok"></span> ok　<span class="mxl w"></span> ${T("wifitrx 判 degraded", "degraded by wifitrx")}　<span class="mxl s"></span> ${T("只有汇总表判 degraded（本库规则）", "degraded only in the summary (this library’s rule)")}${col ? "　" + T("底色列 = 本行", "shaded column = this row") : ""}</figcaption></figure>`;
}
function footCard(fc, f) {
  return `<section class="blk"><header><h3>${fg(fc)} ${T("这一行的口径", "How this row is counted")}${P_.c}${T(...FOOT[fc])}</h3></header>
    <dl class="kv"><dt>${T("未校准底板", "Raw floor")}</dt><dd>${esc(bi(f, "raw_floor"))}</dd><dt>${T("校准后底板", "Calibrated floor")}</dt><dd>${esc(bi(f, "cal_floor"))}</dd>
    <dt>${T("校准在这条链上真跑过", "Calibration actually run on this chain")}</dt><dd>${f.calibration_run_on_this_chain ? `<span class="ok">✓ ${T("是", "yes")}</span>` : `<span class="dg">▲ ${T("否：查表", "no: looked up")}</span>`}</dd>
    <dt>${T("pJ/bit 计解码器", "Decoder counted in pJ/bit")}</dt><dd>${f.decoder_counted_in_pj ? `<span class="ok">✓ ${T("计", "counted")}</span>` : `<span class="dg">▲ ${T("不计", "not counted")}</span>`}</dd></dl></section>`;
}
function reproCard(W) {
  const rp = W.repro, p = rp.provenance, res = W.results, tm = res.table, was = tm && tm.provenance ? tm.provenance.commit : null;
  return `<section class="blk" id="repro"><header><h3>${T("可复现卡", "Reproducibility card")}</h3><span class="mut sm">${T("重算这一行要用的配置、代码与命令", "the configuration, code and commands that compute this row again")}</span></header>
    <dl class="kv">
      <dt>${T("配置", "Configuration")}</dt><dd><code>${esc(rp.config_label)}</code></dd>
      <dt>seed</dt><dd class="n">${plain(rp.seed)}</dd>
      <dt>${T("表单", "Form")}</dt><dd><code>${esc(JSON.stringify(rp.study))}</code>${Object.keys(rp.study).length ? "" : " " + T("（预设）", "(the presets)")}</dd>
      <dt>${T("当前代码", "Current code")}</dt><dd><code>${esc(p.library)} ${esc(p.version)} @ ${esc(p.commit || "—")}</code></dd>
      <dt>${T("规范表摘要", "Spec-table digest")}</dt><dd><code>${esc(p.spec_digest)}</code> · schema ${plain(p.schema)}</dd>
    </dl>
    <div><div class="eyebrow">${T("配置 sha256", "Configuration sha256")}</div><div class="hash" data-sha>${esc(rp.config_sha256)}</div>
      ${Object.keys(S.study).length && JSON.stringify(S.study) !== JSON.stringify(rp.study) ? `<div class="note warn" style="margin-top:6px">${T("表单现在的取值已不是这份配置；新配置的哈希在重算完成时生成。", "The form no longer holds this configuration; the new hash is produced when the recompute finishes.")}</div>` : ""}
      ${was && p.commit && was !== p.commit ? `<div class="note" style="margin-top:6px">${T("存着的结果是在另一个提交上算的", "The stored result was computed at another commit")}${P_.c}<code>${short(was)}</code> → <code>${short(p.commit)}</code></div>` : ""}</div>
    <div><div class="eyebrow">${T("vendored 库", "Vendored libraries")}</div>
      <dl class="kv" style="margin-top:4px">${Object.entries(p.vendored || {}).map(([k, v]) => `<dt>${esc(k)}${v.version ? " " + esc(v.version) : ""}</dt><dd><code>${esc(v.pin)}</code></dd>`).join("")}</dl></div>
    <div style="display:grid;gap:5px"><div class="eyebrow">${T("等价的命令行", "Equivalent command line")}</div>${rp.commands.map(cmd).join("")}</div>
    <div class="sm" style="display:grid;gap:3px;color:var(--ink2)"><div class="eyebrow">${T("这一屏画的是哪几份存着的结果", "Which stored results this screen draws")}</div>${W.part_results ? `<div class="provs">${tableProv(W.part_results)}</div>` : ""}${[...(W.part_results ? [] : ["table"]), "calibration", "array"].map(k => (res[k] ? `<div>${provLine(res[k])}</div>` : `<div class="mut">${T(...REPNAME[k])}${P_.c}${T("没有存着的结果", "no stored result")}</div>`)).join("")}</div>
  </section>`;
}
function powerTable(p) {
  return tbl([
    { h: T("功耗块", "Block"), f: r => term(r[0]) }, { h: "mW", r: 1, f: r => sig(r[1].watts * 1e3) }, { h: "pJ/bit", r: 1, f: r => sig(r[1].pj_per_bit) }, { h: T("怎么算的", "How it is counted"), f: r => `<span class="sm">${asWritten(r[1].note, awLang("power_block_note"))}</span>` },
  ], Object.entries(p.blocks)) + (p.omitted && p.omitted.length ? `<p class="note">${T("没有计入", "Not counted")}${P_.c}${p.omitted.map(esc).join(P_.s)}</p>` : "");
}
function renderRow() {
  const W = S.row;
  if (!S.sel) return `<div class="page"><div class="empty"><b>${T("还没有选行", "No row selected")}</b><span class="mut">${T("在同台表里点一行。", "Click a row of the comparison table.")}</span><button type="button" class="btn" data-act="go" data-v="table">${T("去同台表", "Open the table")}</button></div></div>`;
  if (!W || W.row.label !== S.sel) return `<div class="page"><div class="loading"><span class="spin"></span>${esc(S.sel)}</div></div>`;
  const r = W.row, fc = r.footing, ay = isAy(r), TW = S.rep.table, R = TW && TW.report ? TW.report : { fields: {}, display: {} }, d = Object.assign({ floor_db: 1, td_evm_db: 1, td_delta_db: 1, terms_db: 1, pj_per_bit: 0, rate_mbps: 0, irr_cal_db: 1, dec_next_margin_db: 2, dec_required_snr_db: 2, dec_penalty_db: 2, ay_floor_db: 2, cfo_subcarriers: 2 }, R.display);
  const fs = f => fieldState(R, f, ay), svf = (f, html) => svField(R, f, ay, html), nm = rowName(r, R), C = W.calibration, rg = W.range, arr = pstate("array");
  const parts = fc === "be_zero_if" ? ["table.analytic", "table.td", "calibration.be", "thresholds.be"] : ay ? ["table.ay", "array", "ay", "thresholds.ay"] : ["table.analytic", "table.td", "thresholds.be"];
  const head = `<div class="phead"><div>
      <div class="eyebrow"><a href="#table" data-act="go" data-v="table">${T("同台表", "Comparison table")}</a> › ${T("行细节", "row detail")}</div>
      <h2 style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:3px">${nm.l1}</h2>
      <p class="sub"><code>${esc(r.label)}</code></p></div>
    <button type="button" class="btn" data-act="go" data-v="system">${T("在框图上看它的 EVM 分项", "See its EVM terms on the diagram")}</button></div>`;
  const pj = p => (p ? fx(p.pj_per_bit, d.pj_per_bit) : "—");
  let stats, main, aside;
  if (!ay) {
    const b = r.evm_budget || { components_db: {} };
    stats = `<div class="stats">
      <div><span class="eyebrow">${T("EVM 底板", "EVM floor")}</span><div class="big"><span class="from">${svf("floor_db", fx(r.floor_db, d.floor_db))} →</span> ${svf("floor_cal_db", fx(r.floor_cal_db, d.floor_db))} <small>dB</small></div>
        <div class="sm mut">${T("解析和", "analytic sum")} · ${svf("td_evm_db", `${T("时域", "time-domain")} ${fx(r.td_evm_db, d.td_evm_db)} dB，${T("差", "Δ")} ${fx(r.td_delta_db, d.td_delta_db)} dB`)} ${yes(r.td_ok, "ok")}</div></div>
      <div><span class="eyebrow">${T("合规上限", "Conformance cap")}</span><div class="big"><span class="from">${svf("max_mcs", mcs(r.max_mcs))} →</span> ${svf("max_mcs_cal", mcs(r.max_mcs_cal))}</div>
        <div class="sm mut">${fx(r.rate_mbps, d.rate_mbps)} → ${fx(r.rate_cal_mbps, d.rate_mbps)} Mb/s · ${esc(bi(r, "verdict"))}${r.reason ? P_.c + esc(bi(r, "reason")) : ""}</div></div>
      <div><span class="eyebrow">${T("解码器上限", "Decoder cap")}</span><div class="big"><span class="from">${svf("dec_mcs", esc(r.dec_cap_display || "—"))} →</span> ${svf("dec_mcs_cal", esc(r.dec_cap_cal_display || "—"))}</div>
        <div class="sm mut">${fx(r.dec_rate_mbps, d.rate_mbps)} → ${fx(r.dec_rate_cal_mbps, d.rate_mbps)} Mb/s · ${T("离上一档", "to next step")} ${fx(r.dec_next_margin_db, d.dec_next_margin_db)} / ${fx(r.dec_cal_next_margin_db, d.dec_next_margin_db)} dB</div></div>
      <div><span class="eyebrow">pJ/bit · ${T("合规上限处", "at the conformance cap")}</span><div class="big"><span class="from">${svf("power", pj(r.power))} →</span> ${svf("power_cal", pj(r.power_cal))}</div>
        <div class="sm mut">${W.footing.decoder_counted_in_pj ? T("计解码器", "decoder counted") : T("不计解码器", "decoder not counted")} · ${T("解码器上限处", "at the decoder cap")} ${svf("power_dec", pj(r.power_dec))} → ${svf("power_dec_cal", `<span data-pj-dec-cal>${pj(r.power_dec_cal)}</span>`)}</div></div></div>`;
    const sh = r.terms_share || {}, bk = t => b.components_db[BUDGET_KEY[t] || t];
    const terms = Object.entries(r.terms_db).map(t => Object.assign([...t], { __attr: `data-term="${esc(t[0])}"` }));
    /* a term's share of the floor's power: the fraction the report gives, as a percentage and a bar */
    const share = t => { const v = sh[t]; return nil(v) ? `<span class="mut">—</span>` : svf("terms_share", `<span class="shr" data-share><b>${fx(v * 100, d.terms_share_pct)} %</b><span class="shrt"><i style="width:${Math.max(0, Math.min(100, v * 100))}%"></i></span></span>`); };
    const evm = `<section class="blk"><header><h3>${T("EVM 预算分项 · 未校准链", "EVM budget by term · raw chain")}</h3>
        <span class="mut sm">${T("每项单独的 EVM；底板是它们的和", "each term’s EVM on its own; the floor is their sum")}</span></header>
      <div class="chartbox" data-chart="terms"></div>
      ${tbl([
      { h: T("项", "Term"), f: t => `${term(t[0])}${t[0] === r.dominant ? ` <span class="vd best">${T("主导", "dominant")}</span>` : ""}` },
      { h: T("单独 EVM dB", "EVM alone, dB"), r: 1, f: t => svf("terms_db", absent(t[1]) ? `<span class="mut" title="${fx(t[1], 1)}">—</span>` : fx(t[1], d.terms_db)) },
      ...(r.terms_share ? [{ h: T("占底板功率的份额", "Share of the floor’s power"), r: 1, f: t => share(t[0]) }] : []),
      { h: "wifitrx EvmBudget dB", r: 1, f: t => (absent(bk(t[0])) ? `<span class="mut">—</span>` : fx(bk(t[0]), 1)) + (t[0] === "phase_noise" && !nil(b.cpe_tracked_fraction) ? ` <span class="mut sm">CPE ${T("跟掉的比例", "tracked fraction")} ${fx(b.cpe_tracked_fraction, 2)}</span>` : "") },
    ], terms)}
      <p class="note">${T("交叉核对", "Cross-check")}${P_.c}${T("解析和", "analytic sum")} <b class="n">${fx(r.floor_db, d.floor_db)} dB</b> · wifitrx EvmBudget <b class="n">${fx(b.predicted_evm_db, 1)} dB</b> (${T("差", "Δ")} ${fx(r.budget_delta_db, 2)}) · ${T("同一格的时域 EVM", "time-domain EVM of the same cell")} <b class="n">${fx(r.td_evm_db, d.td_evm_db)} dB</b> ${yes(r.td_ok, "ok")} · IPN ${fx(b.ipn_dbc_10k_100m, 1)} dBc</p>
      ${fc === "be_zero_if" ? `<p class="note warn">${fg(fc)} ${T("校准后", "Calibrated")} <b class="n">${fx(r.floor_cal_db, d.floor_db)} dB</b>${P_.c}${esc(bi(W.footing, "cal_floor"))}${P_.p}IRR <b class="n">${svf("irr_cal_db", fx(r.irr_cal_db, d.irr_cal_db))} dB</b> @${hz(r.irr_cal_measured_at_hz)}${W.irr_looked_up_from_column ? ` · ${T("查的是校准的这一列", "looked up from calibration column")} <code>${esc(W.irr_looked_up_from_column)}</code>` : ""}${R.irr_table ? ` · ${T("表取自", "table from")} <code>${esc(R.irr_table.from)}</code>` : ""}</p>` : `<p class="note">${fg(fc)} ${esc(bi(W.footing, "cal_floor"))}</p>`}
    </section>`;
    let cal;
    if (!C) cal = `<section class="blk"><header><h3>${T("校准步骤", "Calibration steps")}</h3></header>${emptyReport("calibration")}</section>`;
    else {
      const col = W.calibration_column, ci = C.columns.findIndex(c => c.label === col), cc = ci >= 0 ? C.columns[ci] : null, cst = pstate("calibration.be");
      const steps = cc ? C.steps.map((sp, i) => {
        const x = sp.cells[ci]; if (!x) return "";
        const strip = `<div class="kstrip" style="grid-template-columns:repeat(${C.columns.length},minmax(0,1fr))" title="${esc(C.columns.map(c => c.label).join(" | "))}">${sp.cells.map((y, j) => (y ? `<span class="${j === ci ? "cur" : ""} ${y.status_wifitrx !== "ok" ? "d" : y.status_summary !== "ok" ? "d2" : ""}" data-tip="${esc(C.columns[j].label)}: wifitrx ${esc(y.status_wifitrx)} · ${T("汇总表", "summary")} ${esc(y.status_summary)}">${nil(y.value) ? "·" : fx(y.value, 1)}</span>` : "<span>·</span>")).join("")}</div>`;
        return `<div class="step"><span class="no">${i + 1}</span><span class="nm">${esc(sp.step)}</span><span class="vv2">${verdicts(x)}</span>
          <span class="val">${sv(cst, stepVal(x), "calibration.be")}</span><span class="mech"><span>${esc(bi(sp, "mechanism"))}</span>${x.detail ? `<div class="xs mut">${asWritten(x.detail, (C.as_written || {}).calibration_step_detail || awLang("calibration_step_detail"))}</div>` : ""}${strip}</span></div>`;
      }).join("") : "";
      const tv = cc && cc.three_views, mv = cc && cc.modem_view;
      cal = `<section class="blk"><header><h3>${cc ? T("校准步骤 · wifitrx 序列在这条链上真跑的结果", "Calibration steps · the wifitrx sequence as actually run on this chain") : T("校准步骤 · 这一行的链不在校准的各列里", "Calibration steps · this row’s chain is not one of the calibration columns")}</h3>
          ${cc ? `<span class="mut sm">${esc(cc.label)} · ${hz(cc.fs_eff_hz)} · ${T("序列跑", "sequence runs")} ${plain(cc.passes)} ${T("遍", "pass(es)")}</span>` : ""}</header>
        <div class="calhead"><dl class="kv">${cc ? `<dt>${T("评分波形", "Scoring waveform")}</dt><dd>${esc(cc.waveform)}</dd>
          <dt>${T("工作点", "Operating point")}</dt><dd class="n">Pout ${fx(cc.pout_dbm, 1)} dBm · ${T("回退", "back-off")} ${fx(cc.backoff_db, 1)} dB</dd>
          <dt>${T("回环 EVM", "Loopback EVM")}</dt><dd class="n">${fx(cc.evm_before_db, 1)} → <b>${fx(cc.evm_after_db, 1)} dB</b> <span class="mut">${T("校准前 → 后", "before → after")}</span></dd>` : `<dt>${T("口径", "Footing")}</dt><dd>${esc(bi(W.footing, "raw_floor"))}</dd>`}
          <dt>${T("两种判定", "Two verdicts")}</dt><dd class="sm">${statusRule(C)}</dd></dl>
          ${calMatrix(C, col)}</div>
        ${cc ? `<div class="xs mut">${T("每步下面的一排格 = 同一步在各列上的读数", "the strip under each step = the same step across the columns")}${P_.c}${C.columns.map((c, j) => `<span class="${j === ci ? "b" : ""}">${esc(c.label)}</span>`).join(" · ")}</div>
        <div class="steps">${steps}</div>
        <div class="g2">${tv ? `<div><div class="eyebrow">${T("最终回环 EVM 的三种读法", "Three readings of the final loopback EVM")}</div>
            <dl class="kv" style="margin-top:4px"><dt>isolation</dt><dd class="n">${fx(tv.isolation_db, 1)} dB</dd><dt>CPE first</dt><dd class="n">${fx(tv.isolation_cpe_first_db, 1)} dB</dd><dt>modem</dt><dd class="n">${fx(tv.modem_db, 1)} dB</dd>
            <dt>${T("相位斜坡", "phase ramp")}</dt><dd class="n">${fx(tv.phase_ramp_rad, 3)} rad</dd><dt>${T("相干度", "coherence")}</dt><dd class="n">${fx(tv.cpe_coherence, 3)}</dd></dl></div>` : ""}
          ${mv ? `<div><div class="eyebrow">${T("modem 口径拆开", "Modem view, split")}</div>
            <dl class="kv" style="margin-top:4px"><dt>${T("回环", "loopback")}</dt><dd class="n">${fx(mv.evm_modem_db, 1)} dB</dd><dt>${T("只 TX", "TX alone")}</dt><dd class="n">${fx(mv.tx_evm_modem_db, 1)} dB</dd><dt>${T("只 RX", "RX alone")}</dt><dd class="n">${fx(mv.rx_evm_modem_db, 1)} dB</dd><dt>RX NF</dt><dd class="n">${fx(mv.rx_nf_db, 1)} dB</dd></dl></div>` : ""}</div>` : ""}
        <p class="note"><a href="#calibration" data-act="go" data-v="calibration">${T("校准页有全部各列 →", "The calibration screen has every column →")}</a></p></section>`;
    }
    const pts = powerPoints(r).filter(p => p.p), first = pts[0];
    const pw = `<section class="blk"><header><h3>${T("功耗分块 pJ/bit", "Power by block, pJ/bit")}</h3><span class="mut sm">${pts.length} ${T("个工作点", "operating points")}</span></header>
      ${first ? `<div class="chartbox" data-chart="power"></div><div class="eyebrow">${esc(first.name)} · ${first.cap} · ${fx(first.p.bit_rate_bps / 1e6, d.rate_mbps)} Mb/s · ${sig(first.p.total_w * 1e3)} mW</div>${powerTable(first.p)}` : `<p class="mut">${T("这一行没有功耗分块（够不到任何一档）。", "No power breakdown for this row (it reaches no MCS).")}</p>`}</section>`;
    main = evm + cal + pw;
    aside = footCard(fc, W.footing) + `<section class="blk"><header><h3>${T("数字学与余量", "Numerology and margins")}</h3></header><dl class="kv">
        <dt>${T("基准 PHY", "Base PHY")}</dt><dd class="n">${esc(r.standard)} ${mhz(r.base_bw_hz)} MHz × K ${plain(r.k)} → ${mhz(r.bw_eff_hz)} MHz</dd>
        <dt>${T("采样率", "Sample rate")}</dt><dd class="n">${hz(r.fs_eff_hz)}</dd>
        <dt>SCS</dt><dd class="n">${hz(r.scs_eff_hz)}</dd><dt>${T("符号时长", "Symbol time")}</dt><dd class="n">${secs(r.t_symbol_eff_s)}</dd>
        <dt>${T("载频", "Carrier")}</dt><dd class="n">${hz(r.carrier_hz)}</dd>
        <dt>CFO</dt><dd><span class="n">${hz(r.cfo_hz)} · ${fx(r.cfo_subcarriers, d.cfo_subcarriers)}</span> ${T("个子载波", "subcarriers")} · L-STF ±${hz(r.stf_capture_hz)} ${yes(r.cfo_captured, T("接得住", "captures it"), T("接不住", "does not capture it"))}</dd>
        <dt>${T("频率规划", "Frequency plan")}</dt><dd>${yes(r.plan_ok)}</dd>
        <dt>${T("解码器所需 SNR", "SNR the decoder needs")}</dt><dd class="n">${fx(r.dec_required_snr_db, d.dec_required_snr_db)} dB · ${T("实现损失", "penalty")} ${fx(r.dec_penalty_db, d.dec_penalty_db)} dB</dd>
        <dt>${T("解码器看到的底板", "Floor the decoder sees")}</dt><dd class="n">${svf("dec_floor_db", fx(r.dec_floor_db, d.floor_db))} dB</dd>
        <dt>Pout</dt><dd class="n">${fx(r.pout_dbm, 1)} dBm · ${fx(r.bits_per_s_per_hz, 2)} bit/s/Hz</dd>
        <dt>EIRP</dt><dd class="n">${r.eirp ? `${fx(r.eirp.eirp_avg_dbm, 1)} dBm · ${T("离上限", "under the limit by")} ${fx(r.eirp.margin_avg_db, 1)} dB ${yes(r.eirp.ok, "ok")}` : `<span class="mut">${T("不适用", "does not apply")}</span>`} ${tag("fcc15255.eirp_avg_dbm")}</dd>
        <dt>${T("距离（单天线）", "Range (single antenna)")}</dt><dd class="n">${rg ? sv(arr, `${sig(rg.range_mcs0_m)} m @MCS0 · ${sig(rg.range_cap_m)} m @${mcs(rg.cap_mcs)}`, "array") : `<span class="mut">${T("未算：阵列结果里没有这一行", "not computed: the array result does not carry this row")}</span>`}</dd></dl></section>`
      + reproCard(W);
  } else {
    const A = S.rep.ay && S.rep.ay.report, by = o => Object.entries(o || {}).map(([k, v]) => `M=${esc(k)} ${fx(v, d.ay_floor_db)}`).join(" · ");
    stats = `<div class="stats">
      <div><span class="eyebrow">${T("EVM 底板", "EVM floor")} ${fg(fc)}</span><div class="big"><span class="from">${svf("floor_raw_db", fx(r.floor_raw_worst_db, d.ay_floor_db))} →</span> ${svf("floor_cal_db", fx(r.floor_cal_worst_db, d.ay_floor_db))} <small>dB</small></div>
        <div class="sm mut">${T("两头都是时域读数，取最差星座", "both ends are time-domain readings, worst constellation")}</div></div>
      <div><span class="eyebrow">${T("合规上限", "Conformance cap")}</span><div class="big"><span class="from">${mcs(r.cap_raw)} →</span> ${svf("cap_cal", mcs(r.cap_cal))}</div>
        <div class="sm mut">${fx(r.rate_cal_mbps, 0)} Mb/s · ${T("留", "margin")} ${plain(r.cap_margin_db)} dB · ${T("不留余量", "no margin")} ${mcs(r.cap_cal_at_limit)} ${fx(r.rate_cal_at_limit_mbps, 0)} Mb/s</div></div>
      <div><span class="eyebrow">${T("解码器上限", "Decoder cap")}</span><div class="big"><span class="from">${svf("dec_mcs", mcs(r.dec_mcs))} →</span> ${svf("dec_mcs_cal", `<span data-dec-cap-cal>${mcs(r.dec_mcs_cal)}</span>`)}</div>
        <div class="sm mut">${svf("dec_rate_mbps", fx(r.dec_rate_mbps, 0))} → ${svf("dec_rate_cal_mbps", fx(r.dec_rate_cal_mbps, 0))} Mb/s${nil(r.dec_margin_db) ? "" : ` · ${T("留", "margin")} ${plain(r.dec_margin_db)} dB`}</div></div>
      <div><span class="eyebrow">pJ/bit · ${T("合规上限处", "at the conformance cap")}</span><div class="big">${svf("power_cal", pj(r.power_cal))}</div>
        <div class="sm">${W.footing.decoder_counted_in_pj ? T("计解码器", "decoder counted") : `<span class="dg">${T("不计解码器", "decoder not counted")}</span>`} <span class="mut">· ${T("解码器上限处", "at the decoder cap")} ${svf("power_dec", pj(r.power_dec))} → ${svf("power_dec_cal", `<span data-pj-dec-cal>${pj(r.power_dec_cal)}</span>`)}</span></div></div></div>`;
    const wfk = r.waveform + "_evm_db", ast = pstate("ay");
    const res = A ? A.residuals.find(x => x.backoff_db === A.header.preset_backoff_db) || A.residuals[0] : null, rw = res ? res.waveforms.find(x => x.waveform === r.waveform) : null;
    const evm = `<section class="blk"><header><h3>${T("底板逐星座 · 时域 EVM", "Floor by constellation · time-domain EVM")}</h3></header>
        <dl class="kv"><dt>${T("未校准 dB", "Raw, dB")}</dt><dd class="n">${svf("floor_raw_db", by(r.floor_raw_db))}</dd><dt>${T("校准后 dB", "Calibrated, dB")}</dt><dd class="n">${svf("floor_cal_db", by(r.floor_cal_db))}</dd>
        <dt>${T("校准后链上实测", "Measured on the calibrated chain")}</dt><dd class="n">IRR ${fx(r.cal_irr_db, 1)} dB · ${T("LO 泄漏", "LO leak")} ${fx(r.cal_lo_leak_dbc, 1)} dBc</dd></dl>
        <p class="note">${T("这类行没有解析和：底板直接读时域 EVM。", "These rows have no analytic sum: the floor is read as time-domain EVM.")} ${esc(bi(W.footing, "raw_floor"))}</p>
      ${A ? `<div class="eyebrow">${T("每个损伤单独开（SC 对 OFDM 那份结果）", "Each impairment switched on alone (from the SC against OFDM result)")}</div><div class="chartbox" data-chart="imp"></div>
        ${rw ? `<div class="eyebrow">${T("校准后的残差逐项", "Residuals on the calibrated chain")} · ${T("回退", "back-off")} ${fx(res.backoff_db, 1)} dB · ${mcs(rw.mcs)}</div>
        ${tbl([{ h: T("只留这一项残差", "Residual left in"), f: x => esc(x[0]) }, { h: "EVM dB", r: 1, f: x => sv(ast, fx(x[1], 2), "ay") }], [[T("全部校准掉", "everything calibrated away"), rw.none_evm_db], ...rw.alone.map(a => [a.label, a.evm_db]), [T("IQ 与泄漏校准掉的链", "chain with IQ and leak calibrated away"), rw.calibrated_away_evm_db], [T("功率和核对", "power-sum check"), rw.power_sum_evm_db], [T("真校准过的链", "the chain as actually calibrated"), rw.calibrated_chain_evm_db]])}` : ""}` : `<p class="mut">${T("没有存着的 SC 对 OFDM 结果：单项损伤与残差无从显示。", "No SC against OFDM result is stored: the single-impairment and residual tables cannot be shown.")}</p>`}</section>`;
    const cc = A ? A.calibration : null;
    const cal = cc ? `<section class="blk"><header><h3>${T("校准步骤 · 在 ay 这条链上真跑的", "Calibration steps · actually run on the ay chain")} ${cc.steps.length} ${T("步", "steps")}</h3><span class="mut sm">${hz(A.header.chain_fs_hz)} · ${T("回退", "back-off")} ${fx(cc.backoff_db, 1)} dB</span></header>
      <dl class="kv"><dt>${T("评分波形", "Scoring waveform")}</dt><dd>${esc(cc.probe)} ${tag("assumed.ay_cal_probe")}</dd></dl>
      <div class="steps">${cc.steps.map((x, i) => `<div class="step"><span class="no">${i + 1}</span><span class="nm">${esc(x.step)}</span><span>${st(x.status)}</span><span class="val">${sv(ast, nil(x.value) ? `<small>${T("无指标", "no metric")}</small>` : `${fx(x.value, 1)} ${metricUnit(x)} <small>${esc(x.metric || "")}</small>`, "ay")}</span><span class="mech xs mut">${asWritten(x.detail, awLang("calibration_step_detail"))}</span></div>`).join("")}</div>
      <dl class="kv"><dt>${T("最终核对", "Final check")}</dt><dd class="n">isolation ${fx(cc.final.isolation_evm_db, 1)} dB · modem ${fx(cc.final.modem_evm_db, 1)} dB · TX ${fx(cc.final.tx_modem_evm_db, 1)} dB · RX ${fx(cc.final.rx_modem_evm_db, 1)} dB · Pout ${fx(cc.final.pout_dbm, 1)} dBm</dd></dl>
      <p class="note">${T("这份序列只有 wifitrx 自己的判定（没有汇总表）。", "This sequence carries wifitrx’s own verdict only (there is no summary table for it).")}</p></section>` : "";
    const pts = powerPoints(r).filter(p => p.p), first = pts[0];
    const pw = `<section class="blk"><header><h3>${T("功耗分块 pJ/bit", "Power by block, pJ/bit")}</h3>${first ? `<span class="mut sm">${esc(first.name)} · ${first.cap} · ${fx(first.p.bit_rate_bps / 1e6, 0)} Mb/s · ${sig(first.p.total_w * 1e3)} mW</span>` : ""}</header>
      ${first ? `<div class="chartbox" data-chart="power"></div>${powerTable(first.p)}` : ""}</section>`;
    main = evm + cal + pw;
    aside = footCard(fc, W.footing) + `<section class="blk"><header><h3>${T("数字学与距离", "Numerology and range")}</h3></header><dl class="kv">
        <dt>${T("信道", "Channel")}</dt><dd class="n">${plain(r.channel)} · ${mhz(r.bw_eff_hz)} MHz (${T("占用", "occupied")} ${mhz(r.occupied_bw_hz)} MHz) · GI ${esc(r.gi)}</dd>
        <dt>${T("采样率", "Sample rate")}</dt><dd class="n">${hz(r.fs_eff_hz)}</dd><dt>${T("块 / 符号时长", "Block / symbol time")}</dt><dd class="n">${secs(r.unit_s)}</dd>
        ${nil(r.scs_hz) ? "" : `<dt>SCS</dt><dd class="n">${hz(r.scs_hz)}</dd>`}
        <dt>CFO</dt><dd><span class="n">${hz(r.cfo_hz)}</span> · STF ±${hz(r.stf_range_hz)} ${yes(r.cfo_captured, T("接得住", "captures it"), T("接不住", "does not capture it"))}</dd>
        <dt>Pout</dt><dd class="n">${fx(r.pout_dbm, 1)} dBm</dd>
        <dt>EIRP</dt><dd class="n">${r.eirp ? `${fx(r.eirp.eirp_avg_dbm, 1)} dBm · ${T("离上限", "under the limit by")} ${fx(r.eirp.margin_avg_db, 1)} dB` : "—"} ${tag("fcc15255.eirp_avg_dbm")}</dd>
        ${rg ? `<dt>${T("距离", "Range")} @MCS1</dt><dd class="n">${sv(arr, sig(rg.range_mcs1_m) + " m", "array")}</dd><dt>@16-QAM 3/4</dt><dd class="n">${sv(arr, `${sig(rg.range_common_m)} m · ${T("多径", "multipath")} ${sig(rg.range_common_multipath_m)} m`, "array")}</dd>
        <dt>@${mcs(rg.cap_mcs)}</dt><dd class="n">${sv(arr, sig(rg.range_cap_m) + " m", "array")}</dd>` : `<dt>${T("距离", "Range")}</dt><dd class="mut">${T("没有存着的阵列结果", "no array result is stored")}</dd>`}</dl></section>`
      + reproCard(W);
  }
  const floorNote = !ay && W.assembled && W.assembled.decoder_caps_from_analytic_floor ? ` <b class="warnt" data-assembled-note>${T("解析列来自只算解析列的预览：解码器上限只从解析底板出发，可能比整表高一档。", "The analytic columns come from an analytic-only preview: the decoder cap starts from the analytic floor alone and may read one MCS higher than a full run will.")}</b>` : "";
  return `<div class="page">${head}${freshBanner(parts, fc === "be_zero_if" ? ["table", "calibration"] : ay ? ["table", "array", "ay"] : ["table"], { note: floorNote })}${stats}<div class="two"><div>${main}</div><div>${aside}</div></div></div>`;
}

/* ------------------------------------------------------------------ the calibration screen */
function renderCalibration() {
  const W = S.rep.calibration;
  if (!W) return `<div class="page"><div class="loading"><span class="spin"></span>${T("正在读取校准结果…", "Loading the calibration result…")}</div></div>`;
  const head = `<div class="phead"><div><div class="eyebrow">${T("校准 · wifitrx 的序列在升频零中频链上真跑", "Calibration · wifitrx’s sequence really run on the upclocked zero-IF chain")}</div><h2 style="margin-top:3px">${T("每一列是一次真实运行，不是手填的“已校准”", "Each column is one real run, not a typed-in “calibrated”")}</h2></div></div>`;
  if (!W.report) return `<div class="page">${head}${freshBanner(["calibration.be"], ["calibration"], { noJobs: true })}${emptyReport("calibration")}</div>`;
  const C = W.report, cs = pstate("calibration.be"), op = C.operating_point, m = v => sv(cs, v, "calibration.be"), cols = C.columns;
  const irr = Object.entries(C.irr_after_cal_db || {});
  const body = `${head}${freshBanner(["calibration.be"], ["calibration"])}
    <div class="stats">
      <div><span class="eyebrow">${T("工作点", "Operating point")}</span><div class="big">${fx(op.target_pout_dbm, 1)} <small>dBm</small></div><div class="sm mut">Psat ${fx(op.psat_dbm, 1)} dBm · ${T("回退", "back-off")} ${fx(op.obo_db, 1)} dB (${esc(op.obo_reference)})</div></div>
      <div><span class="eyebrow">${T("列 × 步", "Columns × steps")}</span><div class="big">${cols.length} × ${C.steps.length}</div><div class="sm mut">${cols.map(c => esc(c.label)).join(" · ")}</div></div>
      <div><span class="eyebrow">${T("校准后 IRR", "IRR after calibration")} · ${esc(cols[0].label)}</span><div class="big">${irr.length ? m(fx(irr[0][1], 1)) : "—"} <small>dB</small></div><div class="sm mut">${T("同台表的“校准后”各列查的就是这张表", "the comparison table’s calibrated columns look this table up")}</div></div>
      <div><span class="eyebrow">${T("回环 EVM", "Loopback EVM")} · ${esc(cols[cols.length - 1].label)}</span><div class="big"><span class="from">${m(fx(cols[cols.length - 1].evm_before_db, 1))} →</span> ${m(fx(cols[cols.length - 1].evm_after_db, 1))} <small>dB</small></div><div class="sm mut">${T("校准前 → 后", "before → after")}</div></div>
    </div>
    <div class="two">
      <div><section class="blk"><header><h3>${T("每一步在每一列上的读数与两种判定", "Every step on every column: the reading and both verdicts")}</h3></header>
        <p class="sm" style="color:var(--ink2)">${statusRule(C)}</p>
        ${tbl([{ h: T("步", "Step"), f: (sp, i) => `<span class="n">${i + 1}. ${esc(sp.step)}</span><div class="xs mut">${esc(bi(sp, "mechanism"))}</div>` },
      ...cols.map((c, j) => ({ h: esc(c.label), r: 1, f: sp => { const x = sp.cells[j]; if (!x) return `<span class="mut">·</span>`; return `<div class="cell2" title="${esc(x.detail || "")}"><span>${m(nil(x.value) ? "—" : fx(x.value, 1) + " " + metricUnit(x))}</span><span class="xs" data-v-wifitrx="${esc(x.status_wifitrx)}" data-v-summary="${esc(x.status_summary)}">w ${st(x.status_wifitrx)}</span><span class="xs">${T("汇", "s")} ${st(x.status_summary)}</span></div>`; } }))], C.steps, { cls: "mx" })}
        <p class="xs mut">w = wifitrx · ${T("汇 = 汇总表（本库的规则）", "s = the summary table (this library’s rule)")} · ${T("每格第一行是这一步的指标读数", "the first line of a cell is the step’s metric reading")}</p></section></div>
      <div><section class="blk">${calMatrix(C, "")}</section>
        <section class="blk"><header><h3>${T("校准后的 IRR，按带宽", "IRR after calibration, by bandwidth")}</h3><span class="mut sm">${T("这次运行量到的", "as measured by these runs")}</span></header>
          ${tbl([{ h: T("带宽", "Bandwidth"), f: e => hz(Number(e[0])) }, { h: "IRR dB", r: 1, f: e => m(fx(e[1], 1)) }], irr)}
          <p class="xs mut">${T("取 tx_iq 与 rx_iq 两步里较小的一个", "the smaller of the tx_iq and rx_iq steps")}</p></section></div>
    </div>
    <section class="blk"><header><h3>${T("各列的运行条件与最终读数", "Each column: how it ran and its final readings")}</h3></header>
      ${tbl([{ h: T("列", "Column"), f: c => `<b>${esc(c.label)}</b><div class="xs mut">${esc(c.waveform)}</div>` }, { h: "K", r: 1, f: c => plain(c.k) }, { h: T("带宽", "BW"), r: 1, f: c => hz(c.bw_eff_hz) }, { h: "fs", r: 1, f: c => hz(c.fs_eff_hz) },
      { h: T("遍数", "Passes"), r: 1, f: c => plain(c.passes) }, { h: "Pout dBm", r: 1, f: c => m(fx(c.pout_dbm, 1)) }, { h: T("回退 dB", "Back-off dB"), r: 1, f: c => m(fx(c.backoff_db, 1)) },
      { h: T("回环 EVM 前 → 后 dB", "Loopback EVM before → after, dB"), r: 1, f: c => m(`${fx(c.evm_before_db, 1)} → ${fx(c.evm_after_db, 1)}`) },
      { h: T("modem：回环 / TX / RX dB", "modem: loopback / TX / RX, dB"), r: 1, f: c => (c.modem_view ? m(`${fx(c.modem_view.evm_modem_db, 1)} / ${fx(c.modem_view.tx_evm_modem_db, 1)} / ${fx(c.modem_view.rx_evm_modem_db, 1)}`) : "—") },
      { h: "RX NF dB", r: 1, f: c => (c.modem_view ? m(fx(c.modem_view.rx_nf_db, 1)) : "—") },
      { h: T("isolation / CPE first dB", "isolation / CPE first, dB"), r: 1, f: c => (c.three_views ? m(`${fx(c.three_views.isolation_db, 1)} / ${fx(c.three_views.isolation_cpe_first_db, 1)}`) : "—") },
      { h: T("捕获：符号 / 样本", "Capture: symbols / samples"), r: 1, f: c => `${plain(c.capture_symbols)} / ${plain(c.capture_samples)}` }], cols)}</section>`;
  return `<div class="page">${body}</div>`;
}
