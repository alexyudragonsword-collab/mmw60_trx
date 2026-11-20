/* Screens: the array (report "array") and SC against OFDM (report "ay" with its computed
 * headline).  Tables and charts place the report's rows; who wins and by how much is read
 * from the headline the API computed, never restated from a document. */
"use strict";
/* ------------------------------------------------------------------ array */
function arrSchemes() {
  const AR = S.rep.array.report, TR_ = S.rep.table && S.rep.table.report ? tableRows(S.rep.table.report) : [];
  const topo = name => { const row = TR_.find(r => r.label === AR.table_row_of[name]); return row ? row.topology : null; };
  const seen = {};
  const be = [...new Set(AR.link.map(r => r.scheme))].map(name => { const A = topo(name) === "if_extender", c = A ? "ta" : "tb"; seen[c] = (seen[c] || 0) + 1; return { id: name, name, kind: "be", color: c, dash: seen[c] > 1 }; });
  const ay = [...new Set((AR.ay || []).map(r => r.waveform))].map(wf => ({ id: wf, name: "802.11ay " + wfn(wf), kind: "ay", wf, color: wf === "ay_sc" ? "sc" : "ofdm" }));
  return [...be, ...ay];
}
const arrRowsOf = (s, point) => { const AR = S.rep.array.report; return s.kind === "be" ? AR.link.filter(r => r.scheme === s.id) : AR.ay.filter(r => r.waveform === s.wf && r.point === point); };
function arrSel() {
  const AR = S.rep.array.report, all = arrSchemes(), s = all.find(x => x.id === S.arr) || all[0], be = s.kind === "be";
  const small = be ? null : (AR.ay_smallest || []).find(x => x.waveform === s.wf && x.point === S.arrPt) || null;
  return Object.assign({}, s, { rows: arrRowsOf(s, S.arrPt), pw: be ? AR.power.filter(r => r.scheme === s.id) : [], small, bindN: be ? AR.eirp_limit.binds_from_n : small ? small.n : null,
    series: be ? [["range_mcs0_m", T("最慢一档 MCS0", "slowest step, MCS0"), ""], ["range_cap_m", T("解码器上限那一档", "at the decoder cap"), "5 4", 1]]
      : [["range_mcs1_m", T("最慢一档 MCS1", "slowest step, MCS1"), ""], ["range_common_m", "16-QAM 3/4", "5 4"], ["range_cap_m", T("解码器上限那一档", "at the decoder cap"), "1.5 4", 1]] });
}
const nCell = (r, lim) => `N&nbsp;=&nbsp;${r.n}${r.eirp_dbm >= lim ? ` <span class="dg">${T("上限卡住", "limit binds")}</span>` : ""}`;
const kvDump = o => `<dl class="kv">${Object.entries(o).map(([k, v]) => `<dt><code>${esc(k)}</code></dt><dd class="n">${plain(v)}</dd>`).join("")}</dl>`;
function renderArray() {
  const W = S.rep.array;
  if (!W) return `<div class="page"><div class="loading"><span class="spin"></span>${T("正在读取阵列结果…", "Loading the array result…")}</div></div>`;
  const parts = ["array", "thresholds.be", "thresholds.ay"];
  if (!W.report) return `<div class="page"><div class="phead"><h2>${T("阵列", "Array")}</h2></div>${freshBanner(parts, ["array"], { noJobs: true })}${emptyReport("array")}</div>`;
  const AR = W.report, H = AR.header, L = AR.eirp_limit, a = arrSel(), all = arrSchemes(), ast = pstate("array"), m = v => sv(ast, v, "array");
  const sizes = [...H.sizes].sort((p, q) => p - q), nb = sizes[sizes.length - 1], na = sizes.length > 1 ? sizes[sizes.length - 2] : nb;
  const s0 = all[0], r0 = arrRowsOf(s0, "preset"), at = (rows, n) => rows.find(r => r.n === n) || {};
  const sm = AR.ay_smallest || [], smf = (wf, pt) => sm.find(x => x.waveform === wf && x.point === pt);
  const hl = r => (r.eirp_dbm >= L.limit_avg_dbm ? "hl" : "");
  const be = a.kind === "be", pw = n => a.pw.find(p => p.n === n) || {};
  const schemeTbl = be ? tbl([
    { h: "N", f: r => nCell(r, L.limit_avg_dbm) }, { h: "EIRP dBm", r: 1, f: r => m(fx(r.eirp_dbm, 1)) }, { h: T("每单元 Pout dBm", "Pout per element dBm"), r: 1, f: r => m(fx(r.element_pout_dbm, 1)) }, { h: T("回退 dB", "Back-off dB"), r: 1, f: r => m(fx(r.obo_db, 1)) },
    { h: T("PA 单独 EVM dB", "PA-alone EVM dB"), r: 1, f: r => m(fx(r.pa_evm_db, 1)) }, { h: T("底板 dB", "Floor dB"), r: 1, f: r => m(fx(r.floor_db, 1)) }, { h: T("解码器上限", "Decoder cap"), f: r => m(mcs(r.cap_mcs)) },
    { h: T("距离 @MCS0 m", "Range @MCS0 m"), r: 1, f: r => m(sig(r.range_mcs0_m)) }, { h: T("距离 @上限 m", "Range @cap m"), r: 1, f: r => m(sig(r.range_cap_m)) },
    { h: T("速率 Mb/s", "Rate Mb/s"), r: 1, f: r => m(fx(pw(r.n).rate_mbps, 0)) }, { h: T("总功耗 mW", "Total mW"), r: 1, f: r => m(sig(pw(r.n).total_mw)) }, { h: "pJ/bit", r: 1, f: r => m(fx(pw(r.n).pj_per_bit, 0)) },
  ], a.rows.map(r => ({ ...r, __cls: hl(r) }))) : tbl([
    { h: "N", f: r => nCell(r, L.limit_avg_dbm) }, { h: "EIRP dBm", r: 1, f: r => m(fx(r.eirp_dbm, 1)) }, { h: T("每单元 Pout dBm", "Pout per element dBm"), r: 1, f: r => m(fx(r.element_pout_dbm, 1)) }, { h: T("回退 dB", "Back-off dB"), r: 1, f: r => m(fx(r.obo_db, 1)) },
    { h: T("PA 单独 EVM dB", "PA-alone EVM dB"), r: 1, f: r => m(fx(r.pa_evm_db, 1)) }, { h: T("底板 dB", "Floor dB"), r: 1, f: r => m(fx(r.floor_db, 1)) }, { h: T("解码器上限", "Decoder cap"), f: r => m(mcs(r.cap_mcs)) },
    { h: T("距离 @MCS1 m", "Range @MCS1 m"), r: 1, f: r => m(sig(r.range_mcs1_m)) }, { h: "@16-QAM 3/4 m", r: 1, f: r => m(sig(r.range_common_m)) }, { h: T("多径一列 m", "multipath col. m"), r: 1, f: r => m(sig(r.range_common_multipath_m)) }, { h: T("距离 @上限 m", "Range @cap m"), r: 1, f: r => m(sig(r.range_cap_m)) },
    { h: T("上限处速率 Mb/s", "Rate at cap Mb/s"), r: 1, f: r => m(fx(r.rate_mbps, 0)) }, { h: T("上限处 pJ/bit", "pJ/bit at cap"), r: 1, f: r => m(fx(r.pj_per_bit, 0)) },
  ], a.rows.map(r => ({ ...r, __cls: hl(r) })));
  const beS = be ? a : s0, ox = AR.oxygen.filter(x => x.scheme === beS.id), trn = AR.training.filter(x => x.scheme === beS.id), rep = AR.training_repetitions.filter(x => x.scheme === beS.id);
  const alphas = H.oxygen_alphas_db_per_km || [];
  const cmp = (() => {
    const ayr = (wf, n) => at(AR.ay.filter(x => x.waveform === wf && x.point === "preset"), n);
    const rows = [[T("每单元输出 dBm", "Output per element, dBm"), fx(at(r0, na).element_pout_dbm, 1), fx(at(r0, nb).element_pout_dbm, 1)], [T("每单元回退 dB", "Back-off per element, dB"), fx(at(r0, na).obo_db, 1), fx(at(r0, nb).obo_db, 1)],
      [`${T("PA 单独 EVM dB", "PA-alone EVM dB")} · ${esc(s0.name)}`, fx(at(r0, na).pa_evm_db, 1), fx(at(r0, nb).pa_evm_db, 1)],
      ...all.filter(x => x.kind === "ay").map(x => [`${T("PA 单独 EVM dB", "PA-alone EVM dB")} · ${esc(x.name)}`, fx(ayr(x.wf, na).pa_evm_db, 1), fx(ayr(x.wf, nb).pa_evm_db, 1)]),
      ...all.map(x => { const rows_ = arrRowsOf(x, "preset"); return [`${T("解码器上限", "Decoder cap")} · ${esc(x.name)}`, mcs(at(rows_, na).cap_mcs), mcs(at(rows_, nb).cap_mcs)]; })];
    return tbl([{ h: "", f: r => r[0] }, { h: `N = ${na}`, r: 1, f: r => m(r[1]) }, { h: `N = ${nb}`, r: 1, f: r => m(`<b>${r[2]}</b>`), cls: () => "cur" }], rows);
  })();
  const body = `
    <div class="phead"><div><div class="eyebrow">${T("阵列 · 两端各一列 N 个单元，每个单元都是同一个前端", "Array · one row of N elements at both ends, every element the same front end")}</div>
      <h2 style="margin-top:3px">${nil(L.binds_from_n) ? T("EIRP 上限在算过的阵列大小里不起作用", "The EIRP limit does not bind within the sizes searched") : T(`EIRP 上限从 N = ${L.binds_from_n} 个单元开始起作用`, `The EIRP limit starts to bind at N = ${L.binds_from_n} elements`)}</h2>
      <p class="sub"><span class="n">${esc(L.law)}</span> · ${T("平均上限", "average limit")} ${fx(L.limit_avg_dbm, 1)} dBm ${tag(L.source_key)} · ${T("单个单元", "one element")} ${fx(L.single_element_eirp_dbm, 1)} dBm</p></div></div>
    ${freshBanner(parts, ["array"])}
    <div class="stats">
      <div><span class="eyebrow">${T("顶到上限的最小阵列", "Smallest array at the limit")}</span><div class="big">N = ${m(plain(L.binds_from_n))}</div>
        <div class="sm mut">${T("预设回退", "preset back-off")} ${fx(H.obo_db, 1)} dB${smf("ay_sc", "own") && smf("ay_ofdm", "own") ? ` · ${T("ay 各自的工作点", "ay at their own operating points")}${P_.c}SC N = ${plain(smf("ay_sc", "own").n)}${P_.d}OFDM N = ${plain(smf("ay_ofdm", "own").n)}` : ""}</div></div>
      <div><span class="eyebrow">${T("每单元输出", "Output per element")} · N = ${na} → ${nb}</span><div class="big"><span class="from">${m(fx(at(r0, na).element_pout_dbm, 1))} →</span> ${m(fx(at(r0, nb).element_pout_dbm, 1))} <small>dBm</small></div>
        <div class="sm mut">EIRP ${fx(at(r0, na).eirp_dbm, 1)} → ${fx(at(r0, nb).eirp_dbm, 1)} dBm</div></div>
      <div><span class="eyebrow">${T("每单元回退", "Back-off per element")} · N = ${na} → ${nb}</span><div class="big"><span class="from">${m(fx(at(r0, na).obo_db, 1))} →</span> ${m(fx(at(r0, nb).obo_db, 1))} <small>dB</small></div>
        <div class="sm mut">${T("PA 单独 EVM", "PA-alone EVM")} ${fx(at(r0, na).pa_evm_db, 1)} → ${fx(at(r0, nb).pa_evm_db, 1)} dB</div></div>
      <div><span class="eyebrow">${T("距离 @解码器上限", "Range @decoder cap")} · ${esc(s0.name)}</span><div class="big"><span class="from">${m(sig(at(r0, na).range_cap_m))} →</span> ${m(sig(at(r0, nb).range_cap_m))} <small>m</small></div>
        <div class="sm mut">N = ${na} → ${nb} · ${mcs(at(r0, na).cap_mcs)} → ${mcs(at(r0, nb).cap_mcs)}</div></div>
    </div>
    <div class="two arr2">
      <section class="blk"><header><h3>${T("随单元数 N：EIRP、每单元输出、距离", "Against the element count N: EIRP, output per element, range")}</h3></header>
        <div class="ctl"><span class="seglab">${T("方案", "Scheme")} ${seg("arr", a.id, all.map(x => [x.id, esc(x.name)]))}</span>
          ${be ? "" : `<span class="seglab">${T("工作点", "Operating point")} ${seg("arrPt", S.arrPt, [["preset", T("共用回退", "shared back-off") + " " + fx(H.obo_db, 1) + " dB"], ["own", T("各自的回退", "own back-off")]])}</span>`}</div>
        <div class="chartbox" data-chart="array"></div>
        <p class="xs mut">${T("只算了", "Computed sizes only")}${P_.c}N = ${sizes.join(P_.d)}${be ? "" : a.small ? T(`，外加顶到上限的最小阵列 N = ${a.small.n}`, `, plus the smallest array at the limit, N = ${a.small.n}`) : ""}${T("；点与点之间没有算过。距离 = 自由空间 + 氧吸收", "; nothing is computed between the points. Range = free space + oxygen absorption")} ${fx(H.oxygen_db_per_km, 1)} dB/km ${tag("assumed.oxygen_absorption")}${T("，视距。阵列：", ", line of sight. Arrays: ")}${T("间距", "spacing")} ${plain(H.spacing_lambda)} λ · ${esc(H.element_pattern)} ${tag("assumed.array_geometry")} · ${T("移相器", "phase shifters")} ${plain(H.phase_bits)} bit ${tag("assumed.array_phase_bits")} · ${T("单元误差", "element errors")} ${plain(H.element_errors.gain_db_rms)} dB / ${plain(H.element_errors.phase_deg_rms)}° rms ${tag("assumed.array_element_errors")}</p>
      </section>
      <div>
        ${sm.length ? `<section class="blk"><header><h3>${T("顶到上限的最小阵列与代价", "Smallest array at the limit, and what it costs")}</h3><span class="mut sm">16-QAM 3/4</span></header>
          ${tbl([{ h: T("波形 · 工作点", "Waveform · point"), f: r => `${wfsw(r.waveform)}${wfn(r.waveform)} · ${r.point === "preset" ? T("共用", "shared") : T("各自", "own")} ${fx(r.operating_obo_db, 1)} dB` },
      { h: "N", r: 1, f: r => m(plain(r.n)), cls: () => "cur" }, { h: T("每单元 dBm", "Per element dBm"), r: 1, f: r => m(fx(r.element_pout_dbm, 1)) }, { h: "PAE %", r: 1, f: r => m(fx(r.pae_pct, 1)) }, { h: "PA mW", r: 1, f: r => m(fx(r.pa_mw, 0)) }, { h: T("移相器 mW", "Phase shifters mW"), r: 1, f: r => m(fx(r.phase_shifters_mw, 0)) },
      { h: T("距离 m", "Range m"), r: 1, f: r => m(sig(r.range_common_m)) }, { h: "pJ/bit", r: 1, f: r => m(fx(r.pj_per_bit, 0)) }], sm)}
          ${tbl([{ h: T("波形", "Waveform"), f: r => wfsw(r.waveform) + wfn(r.waveform) }, { h: T("各自的回退 dB", "Own back-off dB"), r: 1, f: r => m(fx(r.own_obo_db, 2)) }, { h: T("预设回退下 PA 单独 EVM dB", "PA-alone EVM at the preset back-off, dB"), r: 1, f: r => m(fx(r.pa_alone_evm_at_preset_db, 1)) }, { h: T("共同的那一档", "The common step"), f: r => mcs(r.common_mcs) }], AR.ay_operating_points || [])}</section>` : ""}
        <section class="blk"><header><h3>${T("阵面", "Array faces")}</h3><span class="mut sm">${T("几何", "geometry")} ${tag("assumed.array_geometry")} · ${T("码本", "codebook")} ${tag("assumed.array_codebook")}</span></header>
          ${tbl([{ h: "N", f: r => `N&nbsp;=&nbsp;${r.n}` }, { h: T("发射增益 dB", "TX gain dB"), r: 1, f: r => m(fx(r.tx_gain_db, 1)) }, { h: T("接收增益 dB", "RX gain dB"), r: 1, f: r => m(fx(r.rx_gain_db, 1)) }, { h: T("半功率波束宽 °", "Half-power beamwidth °"), r: 1, f: r => m(fx(r.beamwidth_3db_deg, 1)) }, { h: T("扇区", "Sectors"), r: 1, f: r => plain(r.sectors) },
      { h: `${T("扫到", "Scan to")} ${plain(H.scan_deg)}° dB`, r: 1, f: r => m(fx(r.scan_rel_db, 2)) }, { h: T("量化损失 dB", "Phase loss dB"), r: 1, f: r => m(fx(r.phase_loss_db, 2)) }, { h: T("含误差 dB", "With errors dB"), r: 1, f: r => m(fx(r.phase_and_error_loss_db, 2)) }], AR.faces)}</section>
      </div>
    </div>
    <div class="two arr2">
      <section class="blk"><header><h3>${T("全部方案同框：距离对单元数 N", "Every scheme together: range against the element count N")}</h3>
        ${seg("arrAll", S.arrAll, [["slow", T("最慢一档", "Slowest step")], ["cap", T("解码器上限那一档", "At the decoder cap")]])}</header>
        <div class="chartbox" data-chart="arrall"></div>
        <p class="xs mut">${T("同一个前端、同一个 EIRP 上限；ay 取共用回退。最慢一档是 be 的 MCS0、ay 的 MCS1。", "Same front end, same EIRP limit; ay at the shared back-off. The slowest step is MCS0 for be and MCS1 for ay.")}</p></section>
      <section class="blk"><header><h3>${T("上限起作用前后", "Before and after the limit binds")}${P_.c}N = ${na} ${T("对", "against")} N = ${nb}</h3></header>${cmp}
        <p class="note">${T("上限卡住以后，多出来的单元换不来更高的 EIRP，只换来每单元更深的回退。", "Once the limit binds, extra elements buy no more EIRP, only a deeper back-off per element.")}</p></section>
    </div>
    <section class="blk"><header><h3>${esc(a.name)}${be ? "" : " · " + (S.arrPt === "preset" ? T("共用回退", "shared back-off") : T("各自的回退", "own back-off"))}</h3><span class="mut sm">${T("底色行 = EIRP 顶在上限上", "shaded row = EIRP pinned at the limit")}${AR.table_row_of[a.id] ? ` · ${T("同台表的行", "comparison-table row")} <code>${esc(AR.table_row_of[a.id])}</code>` : ""}</span></header>${schemeTbl}</section>
    <div class="g2">
      <section class="blk"><header><h3>${T("功耗 mW", "Power, mW")} · ${esc(beS.name)}</h3></header>${be ? `<div class="chartbox" data-chart="arrpower"></div>` : `<p class="mut sm">${T("功耗分块只对 be 方案算了；选一个 be 方案看。", "The power breakdown is computed for the be schemes only; pick one to see it.")}</p>`}
        <p class="xs mut">${T("每单元每侧一个移相器", "one phase shifter per element per side")} ${plain(H.phase_shifter_mw)} mW ${tag("assumed.array_phase_shifter_power_mw")}</p></section>
      <section class="blk"><header><h3>${T("氧吸收取多少，MCS0 的距离", "MCS0 range against the oxygen-absorption figure")}</h3></header>
        ${tbl([{ h: "N", f: r => `N&nbsp;=&nbsp;${r.n}` }, ...alphas.map((al, i) => ({ h: `${plain(al)} dB/km${al === H.oxygen_db_per_km ? " ●" : ""}`, r: 1, f: r => m(sig(r.range_mcs0_by_alpha_m[i])), cls: () => (al === H.oxygen_db_per_km ? "cur" : "") }))], ox)}
        <p class="xs mut">● ${T("预设", "preset")} ${tag("assumed.oxygen_absorption")} · ${esc(beS.name)} · m</p></section>
    </div>
    <div>
      <section class="blk"><header><h3>${T("波束训练：扫一遍要多久", "Beam training: time for one sweep")}</h3><span>${tag("assumed.array_training")}</span></header>
        ${tbl([{ h: "N", f: r => `N&nbsp;=&nbsp;${r.n}` }, { h: T("扫描 µs", "Sweep µs"), r: 1, f: r => m(fx(r.sweep_us, 1)) }, { h: "TXSS − MCS0 dB", r: 1, f: r => m(fx(r.txss_minus_mcs0_db, 1)) }, { h: T("TXSS − 上限 dB", "TXSS − cap dB"), r: 1, f: r => m(fx(r.txss_minus_cap_db, 1)) },
      { h: T("重复到够得着 MCS0 边缘", "Repeats to reach the MCS0 edge"), r: 1, f: r => { const x = rep.find(y => y.n === r.n); return x ? m(x.cells.map(c => `${esc(c.combining)} R${plain(c.repetitions)} · ${fx(c.tx_sweep_us, 1)} µs`).join("<br>")) : `<span class="mut">—</span>`; } }], trn)}
        <p class="xs mut">${esc(beS.name)} · ${esc(H.training_field)} · ${esc(H.training_estimator)} ${tag("assumed.array_training_repetition")}</p></section>
    </div>
    ${AR.ay_sweep ? `<details class="fold"><summary>${T("ay 自己的扇区扫描 对 be 的扫描", "ay’s own sector sweep against the be sweep")}</summary><div>
      ${tbl([{ h: "N", f: r => `N&nbsp;=&nbsp;${r.n}` }, { h: "EIRP dBm", r: 1, f: r => m(fx(r.eirp_dbm, 1)) }, { h: T("ay 扫描 µs", "ay sweep µs"), r: 1, f: r => m(fx(r.ay_sweep_us, 1)) }, { h: T("be 扫描 µs", "be sweep µs"), r: 1, f: r => m(fx(r.be_sweep_us, 1)) },
      ...(H.ay_waveforms || []).map(wf => ({ h: `${wfn(wf)}: TXSS − MCS1 dB`, r: 1, f: r => { const x = (r.waveforms || []).find(y => y.waveform === wf); return x ? m(fx(x.txss_minus_mcs1_db, 1)) : "—"; } })), { h: "be: TXSS − MCS0 dB", r: 1, f: r => m(fx(r.be_txss_minus_mcs0_db, 1)) }], AR.ay_sweep)}
      <p class="xs mut">${T("每扇区一个 SSW 帧", "one SSW frame per sector")} ${fx(H.ssw_frame_us, 2)} µs + SBIFS ${fx(H.sbifs_us, 1)} µs ${tag("dmg.ssw_frame")} ${tag("assumed.ay_sector_sweep")}</p></div></details>` : ""}
    <details class="fold"><summary>${T("两级扫描", "Two-stage sweep")} · N = ${plain(H.two_stage_n)}</summary><div>
      ${tbl([{ h: T("方案", "Scheme"), f: r => esc(r.scheme) }, { h: T("目标", "Target"), f: r => esc(r.target) }, { h: T("目标路损 dB", "Target path loss dB"), r: 1, f: r => m(fx(r.target_path_loss_db, 1)) }, { h: "M", r: 1, f: r => plain(r.m) },
      { h: T("一级扫 µs（重复）", "Flat sweep µs (repeats)"), r: 1, f: r => m(`${fx(r.flat.time_us, 1)} (R${plain(r.flat.repetitions)})`) }, { h: T("宽波束 EIRP dBm", "Wide-beam EIRP dBm"), r: 1, f: r => m(fx(r.wide.eirp_dbm, 1)) }, { h: T("宽 µs", "Wide µs"), r: 1, f: r => m(fx(r.wide.time_us, 1)) }, { h: T("窄 µs", "Narrow µs"), r: 1, f: r => m(fx(r.narrow.time_us, 1)) }, { h: T("两级合计 µs", "Two-stage total µs"), r: 1, f: r => m(fx(r.two_stage_us, 1)) }], AR.two_stage)}
      <p class="xs mut">${T("“—” = 宽波束在允许的重复次数内够不着目标。", "“—” = the wide beam does not reach the target within the repetitions allowed.")}</p></div></details>
    <details class="fold"><summary>${plain(H.scan_deg)}° ${T("斜视 与 单项灵敏度", "squint, and one-at-a-time sensitivities")} · N = ${plain(H.sensitivity_n)}</summary><div class="g2">
      ${tbl([{ h: T("频带", "Band"), f: r => esc(r.band) }, { h: "N", r: 1, f: r => plain(r.n) }, { h: T("移相 平均 dB", "phase, mean dB"), r: 1, f: r => m(fx(r.phase_mean_db, 2)) }, { h: T("移相 带边 dB", "phase, edge dB"), r: 1, f: r => m(fx(r.phase_edge_db, 2)) }, { h: T("真时延 平均 dB", "TTD, mean dB"), r: 1, f: r => m(fx(r.ttd_mean_db, 2)) }, { h: T("真时延 带边 dB", "TTD, edge dB"), r: 1, f: r => m(fx(r.ttd_edge_db, 2)) }], AR.squint)}
      ${tbl([{ h: T("改哪一项", "Input changed"), f: r => esc(r.input) }, { h: T("发射增益 dB", "TX gain dB"), r: 1, f: r => m(fx(r.tx_gain_db, 1)) }, { h: T("量化损失 dB", "Phase loss dB"), r: 1, f: r => m(fx(r.phase_loss_db, 2)) }, { h: T("扇区", "Sectors"), r: 1, f: r => plain(r.sectors) }, { h: T("所需 SNR dB", "Required SNR dB"), r: 1, f: r => m(fx(r.req_tx_db, 1)) }, { h: "TXSS − MCS0 dB", r: 1, f: r => m(fx(r.txss_minus_mcs0_db, 1)) }], AR.sensitivity)}</div></details>
    <details class="fold"><summary>${T("这次运行的条件（报告头，原样）", "Conditions of this run (the report header, as it is)")}</summary><div>${kvDump(H)}</div></details>`;
  return `<div class="page">${body}</div>`;
}

/* ------------------------------------------------------------------ SC against OFDM */
const signed = (v, d) => (nil(v) ? "—" : (v > 0 ? "+" : "") + fx(v, d));
const mc = r => `${esc(r.modulation)} ${esc(r.code_rate)}`;
const never = v => (nil(v) ? `<span class="mut">—</span>` : fx(v, 2));
/* SC against OFDM item by item: the host computed every pair, its percentage and who is ahead from
 * the three stored results; each item is stale with the part its numbers come from */
const ITEM_GROUP = { rate: ["速率", "Rate"], range: ["距离", "Range"], pj_per_bit: ["pJ/bit", "pJ/bit"] };
function ayItems(W) {
  const items = W.items || [], IR = W.items_results || {}, gone = ["table", "array", "ay"].filter(k => !IR[k]);
  const fmt = { rate: v => fx(v, 0), range: v => sig(v), pj_per_bit: v => fx(v, 0) };
  const side = (it, x) => { const extra = [nil(x.mcs) ? "" : mcs(x.mcs), nil(x.n) || x.n === it.n ? "" : "N = " + plain(x.n), nil(x.backoff_db) ? "" : `${T("回退", "back-off")} ${fx(x.backoff_db, 2)} dB`].filter(Boolean).join(" · ");
    return `<div class="cellv">${sv(pstate(it.part), `<b>${(fmt[it.metric] || plain)(x.value)}</b>`, it.part)} <span class="mut">${esc(it.unit)}</span>${extra ? `<div class="xs mut">${extra}</div>` : ""}</div>`; };
  const rows = []; let g = null;
  for (const it of items) {
    if (it.metric !== g) { g = it.metric; const nm = ITEM_GROUP[g] ? T(...ITEM_GROUP[g]) : esc(g); rows.push({ __grp: `${nm}${it.unit === nm ? "" : " · " + esc(it.unit)} · ${it.better === "lower" ? T("低者好", "lower is better") : T("高者好", "higher is better")}` }); }
    rows.push(Object.assign({}, it, { __attr: `data-item="${esc(it.id)}" data-metric="${esc(it.metric)}" data-part="${esc(it.part)}" data-state="${pstate(it.part)}"${it.winner ? ` data-winner="${esc(it.winner)}"` : ""}` }));
  }
  const n = w => items.filter(it => it.winner === w).length;
  return `<section class="blk" id="items"><header><h3>${T("逐项对照：SC 对 OFDM", "Item by item: SC against OFDM")}</h3>
      <span class="sm">${wfsw("ay_sc")}<b>SC ${T("领先", "ahead")} ${n("ay_sc")}</b> · ${wfsw("ay_ofdm")}OFDM ${T("领先", "ahead")} ${n("ay_ofdm")} <span class="mut">/ ${items.length} ${T("项", "items")}</span></span></header>
    ${gone.length ? `<p class="note warn" data-items-missing="${esc(gone.join(" "))}">${T("没有存着的结果", "No stored result")}${P_.c}${gone.map(k => T(...REPNAME[k])).join(P_.d)}${T("——来自它的项不在表里。", " — the items that come from it are absent.")}</p>` : ""}
    ${IR.table && !IR.table.parts.includes("table.ay") ? `<p class="note warn" data-items-missing="table.ay">${T("正在显示的同台表结果里没有 802.11ay 两行——来自它的项不在表里。", "The comparison-table result shown has no 802.11ay rows — the items that come from them are absent.")}</p>` : ""}
    ${items.length ? tbl([{ h: T("比什么", "What is compared"), f: it => esc(T(it.zh, it.en)) },
      { h: "SC", r: 1, f: it => side(it, it.sc) }, { h: "OFDM", r: 1, f: it => side(it, it.ofdm) },
      { h: T("SC 对 OFDM", "SC over OFDM"), r: 1, f: it => sv(pstate(it.part), `<span data-pct>${signed(it.sc_over_ofdm_pct, 1)} %</span>`, it.part) },
      { h: T("谁领先", "Who is ahead"), f: it => (it.winner ? `<span class="win-sc">${wfsw(it.winner)}${wfn(it.winner)}</span>` : `<span class="mut">—</span>`) },
      { h: T("取自", "From"), f: it => `<span class="pchip xs" data-state="${pstate(it.part)}">${stateSign(pstate(it.part))} ${esc(pn(it.part))}</span>` }], rows) : `<p class="mut">${T("没有可比的项。", "There is no item to compare.")}</p>`}
    <p class="xs mut">${T("百分比 = SC 比 OFDM 多（正）或少（负）多少；pJ/bit 一组低者好，所以负的百分比是 SC 领先。没有“打平”一说：数据里没有门限，差多少由百分比说话。", "The percentage is how far SC is above (positive) or below (negative) OFDM; pJ/bit is lower-is-better, so a negative percentage there means SC is ahead. No “tie” is called: the data carry no threshold, the percentage says how close it is.")}</p>
    <div class="xs" style="display:grid;gap:2px;color:var(--ink2)">${["table", "array", "ay"].filter(k => IR[k]).map(k => `<div>${provLine(IR[k])}</div>`).join("")}</div></section>`;
}
function renderAy() {
  const W = S.rep.ay;
  if (!W) return `<div class="page"><div class="loading"><span class="spin"></span>${T("正在读取 SC 对 OFDM 的结果…", "Loading the SC against OFDM result…")}</div></div>`;
  const parts = ["ay", "array", "table.ay", "thresholds.be", "thresholds.ay"];
  const eyebrow = `<div class="phead"><div><div class="eyebrow">${T("SC 对 OFDM · 802.11ay 两种波形跑在同一套硬件上", "SC against OFDM · the two 802.11ay waveforms on the same hardware")}</div></div></div>`;
  if (!W.report) return `<div class="page">${eyebrow}${freshBanner(parts, ["ay", "array", "table"], { noJobs: true })}${emptyReport("ay")}</div>`;
  const A = W.report, H = A.header, HL = W.headline, ast = pstate("ay"), m = v => sv(ast, v, "ay"), hm = v => sv(pstate("array"), v, "array"), LB = A.link_budget || {};
  let verdict;
  if (HL) {
    const a = HL.same_modulation_16qam_3_4, b = HL.own_decoder_cap, pa = a.sc_advantage_pct, pb = b.sc_advantage_pct;
    const call = nil(pa) || nil(pb) ? T("乘积没有算全", "the products are incomplete") : pa > 0 && pb > 0 ? T("SC 领先", "SC is ahead") : pa < 0 && pb < 0 ? T("OFDM 领先", "OFDM is ahead") : T("两种口径结论不同", "the two footings disagree");
    const pair = (x, lab) => `<div><span class="eyebrow">${lab}</span>
      <span class="pair">${wfsw("ay_sc")}SC ${mcs(x.mcs.ay_sc)} <b>${hm(gbps(x.ay_sc.rate_bps))} Gb/s</b> → <b>${hm(fx(x.ay_sc.range_m, 0))} m</b></span>
      <span class="pair">${wfsw("ay_ofdm")}OFDM ${mcs(x.mcs.ay_ofdm)} <b>${hm(gbps(x.ay_ofdm.rate_bps))} Gb/s</b> → <b>${hm(fx(x.ay_ofdm.range_m, 0))} m</b></span>
      <span class="adv" data-adv>SC ${hm(signed(x.sc_advantage_pct, 0))} % <span class="mut sm">${T("速率 × 距离", "rate × range")}</span></span></div>`;
    verdict = `<div class="verdict"><div>
        <span class="eyebrow">${T("结论 · 由阵列结果的 802.11ay 行算出", "Conclusion · computed from the array result’s 802.11ay rows")}</span>
        <p class="call">${call}<em> · ${T("净吞吐 × 距离", "net throughput × range")}</em></p>
        <p style="max-width:70ch">${T("单信道、同一个前端、同一个阵列、同一个 EIRP 上限下比速率 × 距离；两组各自的数与差距在下面，差多少由这两个百分比说话。", "Rate × range on one channel with the same front end, the same array and the same EIRP limit; both pairs and their gap are below, and the two percentages say how large it is.")}</p>
        <div class="hl2">${pair(a, `N = ${plain(HL.n)} (EIRP ${fx(HL.eirp_dbm, 1)} dBm) · 16-QAM 3/4`)}${pair(b, `N = ${plain(HL.n)} · ${T("各取自己的解码器上限", "each at its own decoder cap")}`)}</div>
        <div class="chartbox" data-chart="prod"></div>
        <p class="xs mut">${T("矩形面积 = 速率 × 距离，从零画起。", "Rectangle area = rate × range, drawn from zero.")} ${W.headline_result ? provLine(W.headline_result) : ""}</p></div>`;
  } else verdict = `<div class="verdict"><div><span class="eyebrow">${T("结论", "Conclusion")}</span><p class="call"><em>${T("没有存着的阵列结果，结论算不出来", "No array result is stored, so the headline cannot be computed")}</em></p>${emptyReport("array")}</div>`;
  const prem = [
    T(`单信道（信道 ${plain(H.channel)}，${hz(H.carrier_hz)}，信道间隔 ${hz(H.channel_spacing_hz)}），单流；拓扑 B 的硬件，两种波形共用一个前端实例、一条 ${hz(H.chain_fs_hz)} 的链、同一次校准。`, `One channel (channel ${plain(H.channel)}, ${hz(H.carrier_hz)}, spacing ${hz(H.channel_spacing_hz)}), one stream; topology B’s hardware, both waveforms sharing one front-end instance, one chain at ${hz(H.chain_fs_hz)} and the same calibration run.`),
    T(`PA 是预设的：回退 ${fx(H.preset_backoff_db, 1)} dB（自 ${esc(H.backoff_reference)}），Pout ${fx(H.pout_dbm, 1)} dBm，不带 DPD；天线发 ${plain(H.tx_antenna_gain_dbi)} / 收 ${plain(H.rx_antenna_gain_dbi)} dBi。`, `The PA is the preset one: back-off ${fx(H.preset_backoff_db, 1)} dB (from ${esc(H.backoff_reference)}), Pout ${fx(H.pout_dbm, 1)} dBm, no DPD; antenna ${plain(H.tx_antenna_gain_dbi)} dBi transmit / ${plain(H.rx_antenna_gain_dbi)} dBi receive.`),
    T(`门限是本库接收机在理想链、flat 信道上量的，不是规范数。距离是自由空间加 ${plain(LB.oxygen_db_per_km)} dB/km 的氧吸收，视距；接收 NF ${plain(LB.rx_nf_db)} dB。`, `Thresholds were measured with this library’s receiver on the ideal chain over a flat channel; they are not spec numbers. Range is free space plus ${plain(LB.oxygen_db_per_km)} dB/km of oxygen absorption, line of sight; receive NF ${plain(LB.rx_nf_db)} dB.`),
    T(`多径一列口径不同：SC 是量的，OFDM 是一个 assumed 余量（${plain(H.ofdm_multipath_margin_db)} dB）。`, `The multipath column is on two footings: SC is measured, OFDM is an assumed margin (${plain(H.ofdm_multipath_margin_db)} dB).`),
    T("线性化引擎：带外、杂散、模板不背书。", "Linearised engine: out-of-band emissions, spurs and the mask are not endorsed."),
  ];
  verdict += `<div><span class="eyebrow">${T("前提 · 结论只在这些条件下成立", "Premises · the conclusion holds only under these")}</span>
      <ul class="plain">${prem.map(p => `<li>${p}</li>`).join("")}</ul>
      <div class="sm" style="display:flex;gap:4px 8px;flex-wrap:wrap;color:var(--ink2)">${Object.entries(H.sources || {}).map(([k, s]) => `<span><code>${esc(k)}</code> ${tag(k, s)}</span>`).join("")}</div></div></div>`;
  const cal = A.same_modulation_calibrated || [], calOf = r => cal.find(x => x.modulation === r.modulation && x.code_rate === r.code_rate) || {};
  const floors = A.calibrated_floors || A.floors || [], caps = [...(A.caps || []), ...(A.calibrated_caps || [])], cc = A.calibration, reuse = A.one_calibration_reused;
  const resCols = (A.residuals || []).flatMap(x => x.waveforms.map(wv => ({ bo: x.backoff_db, wv })));
  const resRows = resCols.length ? [[T("全部校准掉", "everything calibrated away"), c => c.wv.none_evm_db], ...resCols[0].wv.alone.map((al, i) => [al.label, c => (c.wv.alone[i] || {}).evm_db]),
    [T("IQ 与泄漏校准掉的链", "chain with IQ and leak calibrated away"), c => c.wv.calibrated_away_evm_db], [T("功率和核对", "power-sum check"), c => c.wv.power_sum_evm_db], [T("真校准过的链", "the chain as actually calibrated"), c => c.wv.calibrated_chain_evm_db]] : [];
  const body = `${eyebrow}${freshBanner(parts, ["ay", "array", "table"])}${verdict}${ayItems(W)}
    <div class="g2">
      <section class="blk"><header><h3>${T("单天线：速率对距离", "Single antenna: rate against range")}</h3><span class="mut sm">${A.rate_vs_range.length} ${T("档，各取最佳回退", "steps, each at its best back-off")}</span></header>
        <div class="lg"><span><i style="border-color:var(--sc)"></i>SC flat</span><span><i style="border-color:var(--ofdm)"></i>OFDM flat</span>
          <span><i class="dash" style="border-color:var(--sc)"></i>SC ${T("多径（量的）", "multipath (measured)")}</span><span><i class="dot" style="border-color:var(--ofdm)"></i>OFDM ${T("多径", "multipath")} ${tag("assumed.ay_ofdm_multipath_margin_db")}</span></div>
        <div class="chartbox" data-chart="rr"></div>
        <p class="note warn">${T("多径两条线口径不同：SC 的门限是逐档量的，OFDM 是统一加", "The two multipath lines are on different footings: SC thresholds are measured per step, OFDM adds a flat")} ${plain(H.ofdm_multipath_margin_db)} dB${P_.p}</p>
        ${tbl([{ h: T("距离 m", "Distance m"), r: 1, f: r => plain(r.distance_m) }, { h: "SC Gb/s", r: 1, f: r => m(`${gbps(r.sc_rate_bps)} ${mcs(r.sc_mcs)}`) }, { h: "OFDM Gb/s", r: 1, f: r => m(`${gbps(r.ofdm_rate_bps)} ${mcs(r.ofdm_mcs)}`) },
      { h: `SC ${T("多径", "multipath")}`, r: 1, f: r => m(`${gbps(r.sc_multipath_rate_bps)} ${mcs(r.sc_multipath_mcs)}`) }, { h: `OFDM ${T("多径", "multipath")}`, r: 1, f: r => m(`${gbps(r.ofdm_multipath_rate_bps)} ${mcs(r.ofdm_multipath_mcs)}`) }], A.fastest_rate_at_distance || [], { head: false })}
      </section>
      <section class="blk"><header><h3>${T("EVM 对回退：低 PAPR 能换成多少回退", "EVM against back-off: how much back-off the low PAPR buys")}</h3><span class="mut sm">${T("IQ 与泄漏校准掉", "IQ and leak calibrated away")}</span></header>
        <div class="chartbox" data-chart="evmbo"></div>
        <div class="eyebrow">${T("每个输出功率上各自最快的一档", "Fastest step of each at every output power")}</div>
        <div class="chartbox" data-chart="bestrate"></div>
      </section>
    </div>
    <div class="g2">
      <section class="blk"><header><h3>${T("同调制同码率：限值、所需回退、ΔPout", "Same modulation and code rate: limit, back-off needed, ΔPout")}</h3><span class="mut sm">dB</span></header>
        ${tbl([{ h: T("调制 · 码率", "Modulation · rate"), f: r => mc(r) }, { h: T("SC 限值", "SC limit"), r: 1, f: r => fx(r.sc_evm_limit_db, 1) }, { h: T("SC 回退", "SC back-off"), r: 1, f: r => m(never(r.sc_backoff_db)) },
      { h: T("OFDM 限值", "OFDM limit"), r: 1, f: r => fx(r.ofdm_evm_limit_db, 1) }, { h: T("OFDM 回退", "OFDM back-off"), r: 1, f: r => m(never(r.ofdm_backoff_db)) },
      { h: T("ΔPout 校准掉", "ΔPout cal. away"), r: 1, f: r => m(never(r.delta_pout_db)) }, { h: T("ΔPout 校准链", "ΔPout cal. chain"), r: 1, f: r => m(never(calOf(r).delta_pout_db)) }, { h: T("速率比 SC / OFDM", "Rate ratio SC / OFDM"), r: 1, f: r => fx(r.rate_ratio, 3) }], A.same_modulation || [])}
        <p class="xs mut">${T("“—” = 这个回退范围内到不了限值。两列 ΔPout 是两种口径：IQ 与泄漏假定校准掉 / 真校准过的链。", "“—” = the limit is not reached within the back-off range. The two ΔPout columns are two footings: IQ and leak assumed calibrated away / the chain as actually calibrated.")}</p>
      </section>
      <section class="blk"><header><h3>PAPR</h3><span class="mut sm">SC ${T("滚降取", "roll-off taken as")} ${plain(H.sc_rolloff_assumed)} ${tag("assumed.ay_sc_pulse")}</span></header>
        ${tbl([{ h: T("波形 · 星座", "Waveform · payload"), f: p => `${wfsw(p.waveform)}${wfn(p.waveform)} ${esc(p.payload)}` }, { h: "MCS", r: 1, f: p => plain(p.mcs) }, { h: T("滚降", "Roll-off"), r: 1, f: p => (nil(p.rolloff) ? "" : plain(p.rolloff)) },
      { h: "CCDF 1e-3 dB", r: 1, f: p => m(fx(p.papr_1e3_db, 2)) }, { h: "CCDF 1e-4 dB", r: 1, f: p => m(fx(p.papr_1e4_db, 2)) }], (A.papr || []).map(p => ({ ...p, __cls: p.rolloff === H.sc_rolloff_assumed ? "hl" : "" })))}
      </section>
    </div>
    <div class="g2">
      <section class="blk"><header><h3>${T("每个损伤单独开 · 时域 EVM", "Each impairment switched on alone · time-domain EVM")}</h3></header><div class="chartbox" data-chart="imp"></div></section>
      <section class="blk"><header><h3>${T("底板与合规上限", "Floors and conformance caps")}</h3></header>
        ${tbl([{ h: T("波形 · 星座", "Waveform · payload"), f: x => `${wfsw(x.waveform)}${wfn(x.waveform)} ${esc(x.payload)}` }, { h: "MCS", r: 1, f: x => plain(x.mcs) }, { h: T("未校准 dB", "Raw dB"), r: 1, f: x => m(fx(x.raw_evm_db, 2)) }, { h: T("校准掉 dB", "Calibrated away dB"), r: 1, f: x => m(fx(x.calibrated_away_evm_db, 2)) }, { h: T("校准链 dB", "Calibrated chain dB"), r: 1, f: x => m(fx(x.calibrated_evm_db, 2)) }], floors)}
        ${tbl([{ h: T("链", "Chain"), f: x => esc(x.chain) }, { h: T("波形", "Waveform"), f: x => wfsw(x.waveform) + wfn(x.waveform) }, { h: T("上限", "Cap"), f: x => m(`${mcs(x.mcs)} ${mc(x)}`) }, { h: T("限值 dB", "Limit dB"), r: 1, f: x => fx(x.evm_limit_db, 1) }, { h: "Gb/s", r: 1, f: x => m(gbps(x.rate_bps)) }], caps)}
      </section>
    </div>
    <div class="g2">
      <section class="blk"><header><h3>${T("多径的代价：两列口径不同", "What multipath costs: two columns on different footings")}</h3></header>
        ${tbl([{ h: T("调制 · 码率", "Modulation · rate"), f: r => mc(r) }, { h: `SC ${T("代价 dB", "cost dB")}`, r: 1, f: r => m(fx(r.sc_cost_db, 2)) }, { h: "SC m", r: 1, f: r => m(sig(r.sc_multipath_range_m)) },
      { h: `OFDM ${T("代价 dB", "cost dB")}`, r: 1, f: r => fx(r.ofdm_cost_db, 2) }, { h: "OFDM m", r: 1, f: r => m(sig(r.ofdm_multipath_range_m)) }, { h: T("OFDM m，若取 SC 的代价", "OFDM m at SC’s cost"), r: 1, f: r => m(sig(r.ofdm_range_at_sc_cost_m)) }], A.multipath_same_modulation || [])}
        <p class="xs mut">SC ${tagPlain("derived")} ${T("逐档量的门限之差", "difference of measured thresholds")} · OFDM ${tag("assumed.ay_ofdm_multipath_margin_db")}</p>
      </section>
      <section class="blk"><header><h3>${T("校准后残差逐项", "Residuals on the calibrated chain, one at a time")}</h3><span class="mut sm">EVM dB</span></header>
        ${tbl([{ h: T("只留这一项残差", "Residual left in"), f: x => esc(x[0]) }, ...resCols.map(c => ({ h: `${wfn(c.wv.waveform)} ${mcs(c.wv.mcs)} @${fx(c.bo, 1)} dB`, r: 1, f: x => m(fx(x[1](c), 2)) }))], resRows)}
        ${cc ? `<div class="eyebrow">${T("在 ay 这条链上真跑的校准", "The calibration actually run on the ay chain")} · ${cc.steps.length} ${T("步", "steps")} · ${T("回退", "back-off")} ${fx(cc.backoff_db, 1)} dB</div>
        <dl class="kv"><dt>${T("评分波形", "Scoring waveform")}</dt><dd>${esc(cc.probe)}</dd><dt>${T("各步", "Steps")}</dt><dd class="sm">${cc.steps.map(x => `<span>${esc(x.step)} ${st(x.status)}${nil(x.value) ? "" : " " + m(fx(x.value, 1)) + " " + metricUnit(x)}</span>`).join(" · ")}</dd>
          <dt>${T("最终核对", "Final check")}</dt><dd class="n">isolation ${m(fx(cc.final.isolation_evm_db, 1))} · modem ${m(fx(cc.final.modem_evm_db, 1))} · TX ${m(fx(cc.final.tx_modem_evm_db, 1))} · RX ${m(fx(cc.final.rx_modem_evm_db, 1))} dB</dd>
          ${reuse ? `<dt>${T("一次校准用在别的回退上", "One calibration reused at another back-off")}</dt><dd class="n">${T("校准于", "calibrated at")} ${fx(reuse.calibrated_at_backoff_db, 1)} dB → ${T("用在", "run at")} ${fx(reuse.run_at_backoff_db, 1)} dB${P_.c}${m(fx(reuse.evm_db, 2))} dB · ${T("在那里重新校准", "calibrated there")} ${m(fx(reuse.evm_calibrated_there_db, 2))} dB</dd>` : ""}</dl>` : ""}
      </section>
    </div>
    <details class="fold"><summary>${T("每一档 MCS：限值、够得着限值的回退、门限、最佳回退下的距离", "Every MCS: limit, back-off that meets it, threshold, range at the best back-off")}</summary><div>
      ${tbl([{ h: T("波形", "Waveform"), f: r => wfsw(r.waveform) + wfn(r.waveform) }, { h: "MCS", r: 1, f: r => plain(r.mcs) }, { h: T("调制 · 码率", "Modulation · rate"), f: r => mc(r) }, { h: "Gb/s", r: 1, f: r => gbps(r.rate_bps) },
      { h: T("门限 dB", "Threshold dB"), r: 1, f: r => fx(r.threshold_db, 2) }, { h: T("预设回退下 m", "At the preset back-off, m"), r: 1, f: r => m(sig(r.range_at_preset_m)) }, { h: T("最佳回退 dB", "Best back-off dB"), r: 1, f: r => m(fx(r.best_backoff_db, 2)) }, { h: T("最佳距离 m", "Best range m"), r: 1, f: r => m(sig(r.best_range_m)) },
      { h: T("多径门限 dB", "Multipath threshold dB"), r: 1, f: r => fx(r.multipath_threshold_db, 2) }, { h: T("多径最佳距离 m", "Multipath best range m"), r: 1, f: r => m(sig(r.multipath_best_range_m)) }], A.rate_vs_range || [])}
      <p class="xs mut">${T("最小回退压在 PA 的极限上时，“最佳回退”的距离是上界。", "Where the best back-off is the smallest the PA allows, that range is an upper bound.")}</p></div></details>
    <details class="fold"><summary>${T("多径下的 EVM、灵敏度的几种取法、门限对照", "EVM under multipath, the sensitivity alternatives, the threshold comparison")}</summary><div>
      ${tbl([{ h: T("波形", "Waveform"), f: r => `${wfsw(r.waveform)}${wfn(r.waveform)} ${mcs(r.mcs)}` }, { h: T("信道", "Channel"), f: r => esc(r.channel) }, { h: "GI", f: r => esc(r.gi) },
      ...(H.multipath_snrs_db || []).map((sn, i) => ({ h: `${nil(sn) ? T("无噪声", "no noise") : "SNR " + plain(sn) + " dB"} · ${T("平均 / P90 dB", "mean / P90 dB")}`, r: 1, f: r => (r.evm[i] ? m(`${fx(r.evm[i].mean_evm_db, 1)} / ${fx(r.evm[i].p90_evm_db, 1)}`) : "—") })), { h: T("对 flat 的差 dB", "Δ vs flat dB"), r: 1, f: r => m(fx(r.delta_vs_flat_db, 2)) }], A.multipath_evm || [])}
      ${tbl([{ h: T("波形", "Waveform"), f: r => `${wfsw(r.waveform)}${wfn(r.waveform)} ${mcs(r.mcs)}` }, { h: T("预设 m", "Preset m"), r: 1, f: r => m(sig(r.preset_range_m)) }, { h: T("换成孪生门限 m", "With the twin threshold m"), r: 1, f: r => m(sig(r.twin_threshold_range_m)) }, { h: T("再加实现损失 m", "And implementation loss m"), r: 1, f: r => m(sig(r.twin_with_implementation_loss_range_m)) },
      { h: T("天线不计增益 m", "Antenna gain left out m"), r: 1, f: r => m(sig(r.unspecified_antenna_range_m)) }, { h: T("换成 WiFi 7 接收梯子 m", "With the WiFi 7 receive ladder m"), r: 1, f: r => m(`${sig(r.wifi7_rx_ladder_range_m)} (NF ${plain(r.wifi7_rx_ladder_nf_db)} dB)`) }], A.sensitivity_rows || [])}
      ${tbl([{ h: T("调制 · 码率", "Modulation · rate"), f: r => esc(r.label) }, { h: T("波形", "Waveform"), f: r => `${wfn(r.waveform)} ${mcs(r.mcs)}` }, { h: T("孪生门限 dB", "Twin threshold dB"), r: 1, f: r => fx(r.twin_threshold_db, 2) }, { h: T("量的门限 dB", "Measured threshold dB"), r: 1, f: r => fx(r.measured_threshold_db, 2) }, { h: T("be 的门限 dB", "be threshold dB"), r: 1, f: r => fx(r.be_threshold_db, 2) },
      { h: T("孪生 − 量的 dB", "Twin − measured dB"), r: 1, f: r => fx(r.twin_minus_measured_db, 2) }], A.threshold_comparison || [])}</div></details>`;
  return `<div class="page">${body}</div>`;
}
