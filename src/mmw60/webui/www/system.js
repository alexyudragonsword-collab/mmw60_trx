/* Screen: the system block diagram.  Structure, words, parameters and source labels all come
 * from the `system` payload; the per-row EVM terms that light the blocks come from the
 * comparison-table report.  The drawing only places them. */
"use strict";
/* a block's short title: its description up to the first bracket or colon (the rest is the tooltip) */
function headOf(s) { const m = /^(.*?)(（|\s\(|：|:\s|；|;\s|\s→)/.exec(s || ""); return (m ? m[1] : s || "").trim(); }
function subOf(s) { const m = /（([^（）]{1,36})）|\(([^()]{1,44})\)/.exec(s || ""); return m ? (m[1] || m[2]) : ""; }
const bt = b => T(b.zh, b.en);
function pval(p) {
  const v = p.value;
  if (nil(v)) return "—";
  if (typeof v === "boolean") return v ? T("是", "yes") : T("否", "no");
  /* a computed value is shown to one decimal (dB) or four figures; a configured one as it is */
  if (typeof v === "number") return p.unit === "Hz" ? hz(v) : (p.source === "derived" && !p.source_key ? (/^dB/.test(p.unit || "") ? fx(v, 1) : plain(Number(v.toPrecision(4)))) : plain(v)) + (p.unit ? " " + esc(p.unit) : "");
  if (typeof v === "object") return "…";
  return esc(v) + (p.unit ? " " + esc(p.unit) : "");
}
const scalar = p => p.value === null || typeof p.value !== "object";
const psrc = p => (p.edited ? "edited" : p.source || null);
/* every block of both chains by id; a block both chains list keeps topology B's entry and topology A's extra parameters */
function sysBlocks(SY) {
  const B = {};
  for (const [ch, t] of [[SY.topology_b_chain, "B"], [SY.topology_a_chain, "A"]]) for (const side of ["tx", "rx"]) for (const b of ch[side]) {
    if (!B[b.id]) B[b.id] = Object.assign({}, b, { params: [...(b.params || [])], topo: b.shared ? "S" : t });
    else { B[b.id].topo = "S"; B[b.id].extraA = (b.params || []); B[b.id].alsoA = b; }
  }
  return B;
}
/* which blocks the selected row's EVM terms come from */
function sysLit(SY) {
  const R = S.rep.table && S.rep.table.report, r = R && S.sysLight && S.sel ? tableRows(R).find(x => x.label === S.sel) : null;
  if (!r) return null;
  const ay = isAy(r), topoA = r.topology === "if_extender", chain = topoA ? SY.topology_a_chain : SY.topology_b_chain;
  const mine = new Set([...chain.tx, ...chain.rx].map(b => b.id)); mine.add("channel");
  const badges = {}, list = [];
  if (!ay) for (const [k, v] of Object.entries(r.terms_db)) {
    const blocks = ((SY.evm_term_to_block[k] || {}).blocks || []).filter(b => mine.has(b)), dom = k === r.dominant;
    blocks.forEach(b => (badges[b] = badges[b] || []).push({ name: term(k), v, dom })); list.push({ k, name: term(k), v, dom });
  }
  /* an 802.11ay row: the impairments its report measured alone, each on the blocks the payload names.
   * A reading that shows the same as the ideal chain's at the decimals drawn is faint: it does not show. */
  const AT = ay && SY.ay_terms ? SY.ay_terms.waveforms[r.waveform] : null;
  if (AT) for (const t of AT.terms) {
    const faint = fx(t.evm_db, 1) === fx(AT.reference_evm_db, 1), name = headOf(T(t.zh, t.en));
    (t.blocks || []).forEach(b => (badges[b] = badges[b] || []).push({ name, v: t.evm_db, dom: t.dominant, faint })); list.push(Object.assign({ name, faint }, t));
  }
  return { r, ay, topoA, badges, list, ayTerms: AT };
}

CHARTS.sys = function (wpx) {
  const SY = S.system, W = 1320, H = 972, UPS = SY.upclock_scope, SB = sysBlocks(SY), stt = sysLit(SY), dimA = stt && !stt.topoA, dimB = stt && stt.topoA;
  const cA = "var(--ta)", cB = "var(--tb)", FS = 9.5, box = {};
  let o = "", top = "";
  const text = (x, y, s, cls = "", extra = "") => `<text x="${P(x)}" y="${P(y)}" class="${cls}" ${extra}>${s}</text>`;
  const LET = { spec: "S", survey: "V", assumed: "A", derived: "D", edited: "✎" };
  const stag = (x, y, src, key) => `<g class="stag s-${src === "edited" ? "assumed" : src}" ${key ? `data-k="${esc(key)}"` : ""}><rect x="${P(x)}" y="${P(y - 8.5)}" width="11" height="11" rx="2"/><text x="${P(x + 5.5)}" y="${P(y)}" text-anchor="middle">${LET[src] || "?"}</text></g>`;
  /* a block: title, sub, parameter lines with a source letter, the calibration steps that own it */
  function block(q) {
    const inner = q.w - 14, L = [];
    wrapTx(q.title, inner, 10.5).forEach(t => L.push({ h: 13, cls: "k", t, fs: 10.5 }));
    if (q.sub) wrapTx(q.sub, inner, 9).forEach(t => L.push({ h: 11, cls: "q", t, fs: 9 }));
    (q.params || []).forEach(p => {
      const lab = T(p.zh, p.en) + (p.pre || ""), val = pval(p), src = psrc(p), vw = tw(val.replace(/&[a-z]+;/g, "x"), FS) * 1.06;
      if (tw(lab, FS) + 5 + vw <= inner - 15) L.push({ h: 12, p: 1, lab, val, src, key: p.source_key });
      else { wrapTx(lab, inner - 15, FS).forEach((t, i) => L.push({ h: 11.5, p: 1, lab: t, val: "", src: i === 0 ? src : null, key: p.source_key })); wrapTx(val, (inner - 10) / 1.12, FS).forEach(t => L.push({ h: 12, p: 1, lab: "", val: t, src: null, ind: 8 })); }
    });
    (q.lines || []).forEach(l => wrapTx(l.t, inner - (l.src ? 15 : 0), FS).forEach((t, i) => L.push({ h: 11.5, cls: l.cls || "", t, fs: FS, src: i === 0 ? l.src : null, key: l.key })));
    if (q.cal && q.cal.length) wrapTx("⟲ " + q.cal.join(" · "), inner, 8.5).forEach(t => L.push({ h: 10.5, cls: "q m", t, fs: 8.5 }));
    const h = L.reduce((a, l) => a + l.h, 0) + 11, y0 = q.y !== undefined ? q.y : q.cy - h / 2, col = q.kind === "A" ? cA : q.kind === "B" ? cB : q.kind === "S" ? "var(--ink)" : "var(--rule2)";
    const bd = stt && q.id && stt.badges[q.id], lit = bd && bd.some(b => !b.faint), dom = lit && bd.some(b => b.dom);
    let g = `<rect x="${q.x}" y="${P(y0)}" width="${q.w}" height="${P(h)}" rx="5" fill="${dom ? "var(--amber-bg)" : "var(--panel)"}" stroke="${col}" stroke-width="${lit ? 2.2 : 1.2}" ${q.dash ? 'stroke-dasharray="5 3"' : ""} ${q.id ? `data-block="${esc(q.id)}"` : ""} ${lit ? 'data-lit="1"' : ""} data-tip="${esc(q.tip || "")}"/>`;
    if (q.kind === "S") g += `<rect x="${q.x + 3}" y="${P(y0 + 3)}" width="${q.w - 6}" height="${P(h - 6)}" rx="3" fill="none" stroke="var(--ink)" stroke-width=".6" pointer-events="none"/>`;
    let yy = y0 + 4;
    L.forEach(l => {
      yy += l.h;
      if (l.p) g += `<text x="${q.x + 7 + (l.ind || 0)}" y="${P(yy)}" style="font-size:${FS}px" pointer-events="none"><tspan class="q">${esc(l.lab)}</tspan>${l.val ? `<tspan class="m k" dx="${l.lab ? 4 : 0}">${l.val}</tspan>` : ""}</text>`;
      else g += `<text x="${q.x + 7}" y="${P(yy)}" class="${l.cls}" style="font-size:${l.fs}px" pointer-events="none">${esc(l.t)}</text>`;
      if (l.src) g += stag(q.x + q.w - 17, yy, l.src, l.key);
    });
    if (bd) bd.forEach((b, i) => {
      const s = `${b.name} ${absent(b.v) ? "—" : fx(b.v, 1) + " dB"}`, bw = tw(s, 9.5) + 14, bx = q.x + q.w - bw, by = y0 - 15 - i * 15;
      top += `<g ${b.faint ? 'opacity=".45" data-faint="1"' : ""}><rect x="${P(bx)}" y="${P(by)}" width="${P(bw)}" height="13" rx="6.5" fill="${b.dom ? "var(--ink)" : "var(--panel)"}" stroke="var(--ink)" stroke-width="1"/><text x="${P(bx + bw / 2)}" y="${P(by + 9.6)}" text-anchor="middle" style="font-size:9.5px;font-weight:650;fill:${b.dom ? "var(--panel)" : "var(--ink)"}">${esc(s)}</text></g>`;
    });
    const out = { g, x: q.x, y: y0, w: q.w, h, cy: y0 + h / 2, cx: q.x + q.w / 2, r: q.x + q.w, b: y0 + h };
    if (q.as || q.id) box[q.as || q.id] = out;
    return out;
  }
  const bq = (id, x, w, cy, kind, extra = {}) => { const b = SB[id]; return block(Object.assign({ id, x, w, cy, kind, title: headOf(bt(b)), sub: subOf(bt(b)), params: b.params.filter(scalar), cal: b.calibrated_by, tip: bt(b) }, extra)); };
  const wire = (pts, cls = "", head = "r") => { const e = pts[pts.length - 1]; return `<polyline points="${pts.map(p => P(p[0]) + "," + P(p[1])).join(" ")}" fill="none" class="wr ${cls}"/>` + (head ? arrowHead(e[0], e[1], head, cls.includes("lo") ? "var(--ink3)" : cls.includes("cal") ? "var(--amber-line)" : "var(--ink)") : ""); };
  const note = (x, y, s, maxW, cls = "q", fs = 9.5) => wrapTx(s, maxW, fs).map((t, i) => text(x, y + i * (fs + 2), esc(t), cls, `style="font-size:${fs}px"`)).join("");
  /* the x K clock domain as a visible extent around the blocks the payload lists: hatched ground, dotted outline, a black tab */
  const kdom = (ids, lab, pad = 7) => { const bs = ids.map(i => box[i]).filter(Boolean); if (!bs.length) return "";
    const x0 = Math.min(...bs.map(b => b.x)) - pad, y0 = Math.min(...bs.map(b => b.y)) - pad, x1 = Math.max(...bs.map(b => b.r)) + pad, y1 = Math.max(...bs.map(b => b.b)) + pad, lw = Math.min(tw(lab, 9) + 14, x1 - x0 - 8);
    return `<rect x="${P(x0)}" y="${P(y0)}" width="${P(x1 - x0)}" height="${P(y1 - y0)}" rx="4" fill="url(#kh)" stroke="var(--ink)" stroke-width="1.1" stroke-dasharray="1.5 3" data-kdom="${esc(ids.join(" "))}"/><rect x="${P(x0 + 6)}" y="${P(y0 - 8)}" width="${P(lw)}" height="14" rx="3" fill="var(--ink)"/><text x="${P(x0 + 13)}" y="${P(y0 + 2.4)}" style="font-size:9px;font-weight:650;fill:var(--panel)" ${tw(lab, 9) + 14 > lw ? `textLength="${P(lw - 12)}" lengthAdjust="spacingAndGlyphs"` : ""}>${esc(lab)}</text>`; };
  const rowLine = r => `${T("本行", "this row")}${P_.c}K = ${plain(r.k)} · ${mhz(r.bw_eff_hz)} MHz · SCS ${hz(r.scs_eff_hz)}`;
  o += `<defs><pattern id="kh" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="var(--ink)" stroke-width="1.2" stroke-opacity=".2"/></pattern></defs>`;
  /* lanes */
  const LN = { b_tx: [58, 292], a_tx: [360, 136], lo: [504, 112], a_rx: [624, 116], b_rx: [748, 158] };
  const lane = (k, col, lab) => `<rect x="26" y="${LN[k][0]}" width="782" height="${LN[k][1]}" rx="6" fill="${col}" fill-opacity=".07"/><text transform="translate(17 ${LN[k][0] + LN[k][1] / 2}) rotate(-90)" text-anchor="middle" style="font-size:10.5px;font-weight:650;fill:${col}">${lab}</text>`;
  const cy = k => LN[k][0] + LN[k][1] / 2;
  let gB = lane("b_tx", cB, T("拓扑 B · 发 →", "Topology B · TX →")) + lane("b_rx", cB, T("← 收 · 拓扑 B", "← RX · Topology B"));
  let gA = lane("a_tx", cA, T("拓扑 A · 发 →", "Topology A · TX →")) + lane("a_rx", cA, T("← 收 · A", "← RX · A"));
  let gS = "", gN = "", gAy = "", gBe = "", gK = "";
  const DB = SY.digital_baseband, inB = new Set(UPS.topology_b.clock_domain_blocks || []), inA = new Set(UPS.topology_a.clock_domain_blocks || []);
  /* topology B, transmit */
  const y1 = cy("b_tx") - 16, btx = DB.be_tx, ayd = DB.ay;
  const bb = block({ as: "be_tx", x: 40, w: 172, y: 70, kind: "B", title: bt(btx), lines: [...btx.blocks.map(b => ({ t: "· " + bt(b) })), { t: bt(btx.clock), cls: "k" }, ...(stt && !stt.ay && !stt.topoA ? [{ t: rowLine(stt.r), cls: "k m" }] : [])], tip: bt(btx.clock) });
  const dfe = bq("dig_fe", 228, 128, y1, "B"), dac = bq("dac", 366, 124, y1, "B"), tlpf = bq("tx_lpf", 500, 100, y1, "B"), iqm = bq("iq_mod", 644, 158, y1, "B");
  const ayb = block({ as: "ay", x: 40, w: 172, y: Math.max(bb.b, dfe.b, dac.b, tlpf.b) + 18, kind: "B", dash: 1, title: T("802.11ay 波形（选项）", "802.11ay waveforms (option)"), tip: bt(ayd),
    lines: ["sc", "ofdm", "preamble"].filter(k => ayd[k]).map(k => ({ t: headOf(bt(ayd[k])), src: (ayd[k].params[0] || {}).source, key: (ayd[k].params[0] || {}).source_key })) });
  gBe += bb.g; gAy += ayb.g;
  gK += kdom(["be_tx", "dig_fe", "dac", "tx_lpf"].filter(i => inB.has(i)), T("× K 时钟域：数字基带 → DAC、低通", "× K clock domain: digital baseband → DAC, filters"));
  gB += wire([[212, bb.cy], [220, bb.cy], [220, y1], [228, y1]], "", "r") + wire([[212, ayb.cy], [220, ayb.cy], [220, y1]], "opt", null);
  gB += wire([[dfe.r, y1], [dac.x, y1]]) + wire([[dac.r, y1], [tlpf.x, y1]]) + wire([[tlpf.r, y1], [iqm.x, y1]]) + dfe.g + dac.g + tlpf.g + iqm.g;
  gB += `<path d="M${tlpf.r + 22} ${y1 - 12}v24" stroke="${cB}" stroke-width="2" stroke-dasharray="3 2"/>` + text(tlpf.r + 22, y1 + 24, "▾ B", "k", `text-anchor="middle" style="font-size:9px;fill:${cB}"`);
  /* topology A, transmit */
  const y2 = cy("a_tx"), chipB = SB.chip, ua = UPS.topology_a, sub = id => (chipB.sub_blocks || []).find(x => x.id === id) || { zh: "", en: "" };
  const chans = (ua.chip_channels_hz || []).map(mhz).join(" / ");
  const chd = block({ as: "chip_digital_tx", x: 40, w: 172, cy: y2, kind: "A", title: headOf(bt(sub("chip_digital"))) + T(" · 发", " · TX"), tip: bt(sub("chip_digital")),
    lines: [{ t: `K × ${T("基准带宽", "base BW")} ∈ ${chans} MHz`, src: ua.source, key: ua.source_key, cls: "k" }, ...(ua.rows_without_numbers || []).map(l => ({ t: T("越界、没有数：", "out of range, no numbers: ") + l })), ...(stt && stt.topoA ? [{ t: rowLine(stt.r), cls: "k m" }] : [])] });
  const chip = block({ id: "chip", x: 228, w: 188, cy: y2, kind: "A", title: headOf(bt(sub("chip_analog"))) + T(" · 发", " · TX"), params: chipB.params.filter(scalar), tip: bt(sub("chip_analog")),
    lines: chipB.option ? [{ t: headOf(bt(chipB.option)), src: chipB.option.source, key: chipB.option.source_key }] : [] });
  const ifb = bq("if_bpf", 428, 124, y2, "A"), mix = bq("mixer", 562, 130, y2, "A");
  if (inA.has("chip_digital")) gK += kdom(["chip_digital_tx"], T("× K 时钟域：只到数字基带", "× K clock domain: digital baseband only"));
  gA += wire([[chd.r, y2], [chip.x, y2]]) + wire([[chip.r, y2], [ifb.x, y2]]) + wire([[ifb.r, y2], [mix.x, y2]]) + chd.g + chip.g + ifb.g + mix.g;
  gA += `<path d="M${chip.r + 6} ${y2 - 12}v24" stroke="${cA}" stroke-width="2" stroke-dasharray="3 2"/>` + text(chip.r + 6, y2 - 16, "▾ A", "k", `text-anchor="middle" style="font-size:9px;fill:${cA}"`);
  /* LO row */
  const yl = cy("lo"), mlo = SY.topology_a_chain.mlo;
  const mlob = block({ as: "mlo", x: 40, w: 300, cy: yl, kind: "A", dash: 1, title: headOf(bt(mlo)) + T(" 预补偿通路", " pre-compensation path"), params: mlo.params, tip: bt(mlo) });
  const flo = bq("fixed_lo", 500, 164, yl, "A"), lo60 = bq("lo60", 672, 136, yl, "B");
  gA += mlob.g + flo.g + wire([[120, mlob.y], [120, chd.b + 7]], "cal", "u") + text(126, mlob.y - 3, T("CFO 预补偿", "CFO pre-comp."), "q", 'style="font-size:9px"');
  /* topology A, receive */
  const y3 = cy("a_rx"), crx = SB.chip_rx;
  const chrx = block({ id: "chip_rx", x: 228, w: 188, cy: y3, kind: "A", title: headOf(bt(crx)), sub: subOf(bt(crx)), tip: bt(crx) });
  const chdr = block({ as: "chip_digital_rx", x: 40, w: 172, cy: y3, kind: "A", title: headOf(bt(sub("chip_digital"))) + T(" · 收", " · RX"), lines: [{ t: bt(ua.cfo), src: ua.source, key: ua.source_key }], tip: bt(ua.cfo) });
  const dmx = bq("down_mixer", 562, 130, y3, "A");
  if (inA.has("chip_digital")) gK += kdom(["chip_digital_rx"], "× K");
  gA += wire([[dmx.x, y3], [chrx.r, y3]], "", "l") + wire([[chrx.x, y3], [chdr.r, y3]], "", "l") + chrx.g + chdr.g + dmx.g;
  gA += wire([[627, flo.y], [627, mix.b]], "lo", "u") + wire([[627, flo.b], [627, dmx.y]], "lo", "d");
  gA += wire([[384, chip.b], [384, chrx.y]], "cal", "d") + note(391, yl - 10, T("芯片自校准回环（建链时真跑）", "chip’s own calibration loop (really runs at build)"), 104, "q", 9);
  /* topology B, receive */
  const y4 = cy("b_rx"), brx = DB.be_rx;
  const iqd = bq("iq_demod", 644, 158, y4, "B"), rlpf = bq("rx_lpf", 500, 100, y4, "B"), adc = bq("adc", 346, 138, y4, "B");
  const drx = block({ as: "be_rx", x: 40, w: 292, cy: y4, kind: "B", title: bt(brx), lines: brx.blocks.map(b => { const p = (b.params || []).find(x => x.source) || {}; return { t: "· " + headOf(bt(b)), src: psrc(p), key: p.source_key }; }) });
  gK += kdom(["be_rx", "adc", "rx_lpf"].filter(i => inB.has(i)), T("× K 时钟域：低通、ADC → 数字接收机", "× K clock domain: filters, ADC → digital receiver"));
  gB += wire([[iqd.x, y4], [rlpf.r, y4]], "", "l") + wire([[rlpf.x, y4], [adc.r, y4]], "", "l") + wire([[adc.x, y4], [drx.r, y4]], "", "l") + iqd.g + rlpf.g + adc.g + drx.g + lo60.g;
  /* the shared front end, drawn once */
  const PX = 814, PW = 312;
  gS += `<rect x="${PX}" y="40" width="${PW}" height="${H - 102}" rx="8" fill="var(--sunk)" fill-opacity=".55" stroke="var(--ink)" stroke-width="1.6" stroke-dasharray="7 4"/>` + text(PX + 10, 56, T("共用的 60 GHz 前端 · 只画一次", "The shared 60 GHz front end · drawn once"), "k", 'style="font-size:11px"');
  gS += note(PX + 10, 69, T("同一个对象：两条拓扑、每一行都接到这里", "One object: both topologies and every row connect here"), PW - 20, "q", 9);
  const pa = bq("pa60", 832, 140, y1 + 4, "S"), ant = bq("ant_tx", 1004, 116, y1 + 232, "S");
  const lnaB = SB.lna60, lna = block({ id: "lna60", x: 828, w: 152, cy: (y3 + y4) / 2 + 14, kind: "S", title: headOf(bt(lnaB)), sub: subOf(bt(lnaB)), params: lnaB.params.filter(scalar), cal: lnaB.calibrated_by, tip: bt(lnaB) + (lnaB.alsoA ? "\n" + bt(lnaB.alsoA) : "") });
  const jx = 822;
  gB += wire([[iqm.r, y1], [jx, y1], [jx, pa.cy], [pa.x, pa.cy]]) + wire([[jx, lna.cy], [jx, y4], [iqd.r, y4]], "", "l");
  gA += wire([[mix.r, y2], [jx - 6, y2], [jx - 6, pa.b - 14], [pa.x, pa.b - 14]]) + wire([[jx, lna.cy], [jx, y3], [dmx.r, y3]], "", "l");
  gS += wire([[lna.x, lna.cy], [jx, lna.cy]], "", null);
  const ax = ant.cx + 12;
  gS += wire([[pa.r, pa.cy], [ax, pa.cy], [ax, ant.y]], "", "d") + wire([[ax, ant.b], [ax, lna.cy], [lna.r, lna.cy]], "", "l");
  const cpx = 986, loopB = SY.topology_b_chain.calibration_loop;
  gS += wire([[cpx, pa.cy], [cpx, H - 94], [808, H - 94], [808, y4 + 1]], "cal", "u") + `<rect x="${cpx - 4}" y="${P(pa.cy - 4)}" width="8" height="8" fill="var(--ink)"/>` + text(cpx + 6, pa.cy - 6, T("耦合器", "coupler"), "q", 'style="font-size:9px"');
  gS += note(828, H - 79, headOf(bt(loopB)) + T("：耦合器 → 接收链", ": coupler → receive chain"), PW - 26, "q", 9) + pa.g + ant.g + lna.g;
  gB += wire([[740, lo60.y], [740, iqm.b]], "lo", "u") + wire([[740, lo60.b], [740, iqd.y]], "lo", "d");
  /* over the air */
  const btw = SY.between, OX = 1140, OW = 176;
  const arr = block({ as: "array", x: OX, w: OW, y: 78, kind: "N", title: headOf(bt(btw.array)), sub: subOf(bt(btw.array)), params: btw.array.params, tip: bt(btw.array) });
  const chn = block({ id: "channel", x: OX, w: OW, y: Math.max(arr.b + 44, ant.cy - 40), kind: "N", title: headOf(bt(btw.channel)), params: btw.channel.params, tip: bt(btw.channel) });
  const cfo = block({ as: "cfo", x: OX, w: OW, y: chn.b + 44, kind: "N", title: bt(btw.cfo), params: btw.cfo.params, tip: bt(btw.cfo) });
  gN += `<polyline points="${ant.r},${P(ant.cy)} ${OX - 12},${P(ant.cy)} ${OX - 12},${P(chn.cy)} ${OX},${P(chn.cy)}" class="wr"/>` + arrowHead(OX, chn.cy, "r", "var(--ink)") + arrowHead(ant.r, ant.cy, "l", "var(--ink)");
  gN += `<line x1="${OX + OW / 2}" y1="${P(arr.b)}" x2="${OX + OW / 2}" y2="${P(chn.y)}" class="wr lo"/><line x1="${OX + OW / 2}" y1="${P(chn.b)}" x2="${OX + OW / 2}" y2="${P(cfo.y)}" class="wr lo"/>` + arr.g + chn.g + cfo.g;
  gN += note(OX, cfo.b + 22, T("对端是同一套收发机：框图只画一端。", "The far end is the same transceiver: the diagram draws one end."), OW, "q", 9);
  /* the engine caveat, on the drawing */
  o += `<rect x="26" y="${H - 58}" width="${W - 30}" height="48" rx="5" fill="var(--amber-bg)" stroke="var(--amber-line)" stroke-dasharray="4 3"/>` + note(36, H - 44, bt(SY.engine_caveat), (W - 60) * 0.9, "k", 9.5) + text(36, H - 18, esc(SY.engine), "m q", 'style="font-size:9px"');
  const op = d => (d ? ' opacity=".42"' : ""), beDim = stt && (stt.ay || stt.topoA), ayDim = stt && !stt.ay;
  o += `<g${op(dimB)}>${gB}<g${op(!dimB && beDim)}>${gBe}</g><g${op(!dimB && ayDim)}>${gAy}</g></g><g${op(dimA)}>${gA}</g>${gK}${gS}${gN}${top}`;
  return `<svg class="cx sysd" width="${wpx}" height="${P(wpx * H / W)}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(T("系统框图：拓扑 A 与拓扑 B 共用同一个 60 GHz 前端", "System block diagram: topologies A and B share one 60 GHz front end"))}">${o}</svg>`;
};

/* the diagram as a list: every block with all its parameters and source labels */
function sysCards(SY) {
  const SB = sysBlocks(SY);
  const pv = p => (p.value !== null && typeof p.value === "object" ? `<span class="xs">${Object.entries(p.value).map(([k, v]) => `${esc(k)}: ${plain(v)}`).join(" · ")}</span>` : pval(p));
  const plist = ps => (ps && ps.length ? `<dl>${ps.map(p => `<div ${p.knob ? `data-param-knob="${esc(p.knob)}"` : ""}><dt>${esc(T(p.zh, p.en))}</dt><dd class="n">${pv(p)}</dd>${tagOf(p)}</div>`).join("")}</dl>` : "");
  const card = (b, kind, extra = "") => `<div class="scard k-${kind}"><div class="b">${esc(bt(b))}</div>${plist(b.params)}${b.extraA && b.extraA.length ? `<div class="xs mut">A${P_.c}${esc(bt(b.alsoA))}</div>${plist(b.extraA)}` : ""}
    ${b.evm_term ? `<div class="xs"><b>EVM</b> ${term(b.evm_term)}${b.evm_term_2 ? " · " + term(b.evm_term_2) : ""}</div>` : ""}${b.calibrated_by ? `<div class="xs mut n">⟲ ${b.calibrated_by.map(esc).join(" · ")}</div>` : ""}
    ${b.option ? `<div class="xs">${esc(bt(b.option))} ${tagOf(b.option)}</div>` : ""}
    ${b.sub_blocks ? b.sub_blocks.map(x => `<div class="xs">${x.clock_x_k ? '<span class="kdl">× K</span> ' : `<span class="mut">${T("不在 × K 域", "outside × K")}</span> `}${esc(bt(x))}</div>`).join("") : ""}${extra}</div>`;
  const grp = (title, list) => `<div class="sgrp"><div class="eyebrow">${title}</div><div class="scards">${list.join("")}</div></div>`;
  const ids = Object.keys(SB), UP = SY.upclock_scope, DB = SY.digital_baseband, tA = SY.topology_a_chain;
  const scope = (kind, u) => `<div class="scard k-${kind}"><div class="b"><span class="kdl">× K</span> ${T("时钟 × K 的范围", "Reach of the × K clock")}</div><div class="xs">${esc(bt(u))} ${tagOf(u)}</div>${u.cfo ? `<div class="xs">${esc(bt(u.cfo))}</div>` : ""}${u.rows_in_comparison_table ? `<div class="xs mut n">${u.rows_in_comparison_table.map(esc).join("<br>")}</div>` : ""}</div>`;
  return grp(T("共用的 60 GHz 前端（同一个对象）", "Shared 60 GHz front end (one object)"), ids.filter(i => SB[i].topo === "S").map(i => card(SB[i], "S")))
    + grp(esc(bt(SY.topology_b_chain)), [...ids.filter(i => SB[i].topo === "B").map(i => card(SB[i], "B")), card(SY.topology_b_chain.calibration_loop, "B"), scope("B", UP.topology_b)])
    + grp(esc(bt(tA)), [...ids.filter(i => SB[i].topo === "A").map(i => card(SB[i], "A")), card(tA.mlo, "A"), card(tA.calibration_loop, "A"), scope("A", UP.topology_a)])
    + grp(T("数字基带与 802.11ay 波形", "Digital baseband and the 802.11ay waveforms"), [
      `<div class="scard k-B"><div class="b">${esc(bt(DB.be_tx))}</div><div class="xs">${DB.be_tx.blocks.map(b => esc(bt(b))).join(" → ")}</div><div class="xs">${esc(bt(DB.be_tx.clock))}</div>${plist(DB.be_tx.clock.params)}</div>`,
      `<div class="scard k-B"><div class="b">${esc(bt(DB.be_rx))}</div>${DB.be_rx.blocks.map(b => `<div class="xs">${esc(bt(b))}</div>${plist(b.params)}`).join("")}</div>`,
      ...["sc", "ofdm", "preamble"].filter(k => DB.ay[k]).map(k => card(DB.ay[k], "B"))])
    + grp(T("空口：晶振与 CFO、信道、阵列", "Over the air: crystals and CFO, channel, array"), ["cfo", "channel", "array"].map(k => card(SY.between[k], "N")));
}
/* the list beside the diagram for an 802.11ay row: each impairment alone, against the ideal chain's reading */
function ayStrip(SY, lit, sel) {
  const ps = pstate("ay"), m = v => sv(ps, v, "ay");
  if (!SY.ay_terms || !lit || !lit.ayTerms) return `<div class="fresh" data-ay-terms="none"><span class="b">${esc(sel.label)}</span><span>${T("没有存着的 SC 对 OFDM 结果：这一行的各项损伤读数无从点亮。", "No SC against OFDM result is stored: this row’s single-impairment readings cannot be lit.")}</span>
    <button type="button" class="btn" data-act="run" data-job="ay">${T("重算", "Recompute")}${P_.c}${jn("ay")} · ${expected("ay")}</button></div>`;
  const AT = lit.ayTerms;
  return `<div class="fresh ${ps === "stale" ? "stale" : ""}" style="border-color:var(--ink)" data-lit-row="${esc(sel.label)}" data-part="ay" data-state="${ps}"><span class="b">${esc(sel.label)}</span>
    <span>${T("每个损伤单独开时的 EVM（未校准链）", "EVM with each impairment alone (uncalibrated chain)")}${P_.c}</span>
    <span class="l2 ayterms">${lit.list.map(t => `<span data-ay-term="${esc(t.impairment)}" class="${t.dominant ? "b" : ""} ${t.faint ? "faint" : ""}" title="${esc(T(t.zh, t.en))} · ${(t.blocks || []).map(esc).join(", ")}">${esc(T(t.zh, t.en))} <span class="n">${m(fx(t.evm_db, 1) + " dB")}</span>${t.faint ? ` <span class="mut xs">${T("与参考一样", "the same as the reference")}</span>` : nil(t.above_reference_db) ? "" : ` <span class="mut xs">${T("比参考高", "above the reference by")} ${m(fx(t.above_reference_db, 1) + " dB")}</span>`}${t.dominant ? ` <span class="vd best">${T("主导", "dominant")}</span>` : ""}</span>`).join("")}
      <span data-ay-reference>${T("参考：理想链", "reference: the ideal chain")} <span class="n">${m(fx(AT.reference_evm_db, 1) + " dB")}</span></span></span>
    <span class="l2"><span>${esc(bt(SY.ay_terms.note))}</span><span class="mut">${T("变淡的一项 = 读数与参考一样，看不出它", "a faint term = it reads the same as the reference, so it does not show")}</span>${SY.ay_terms_result ? provLine(SY.ay_terms_result) : ""}</span></div>`;
}
function renderSystem() {
  const SY = S.system;
  if (!SY) return `<div class="page"><div class="loading"><span class="spin"></span>${T("正在读取框图…", "Loading the diagram…")}</div></div>`;
  const R = S.rep.table && S.rep.table.report, rows = R ? tableRows(R) : [], lit = sysLit(SY), stt = lit && !lit.ay ? lit : null, UP = SY.upclock_scope, ta = pstate("table.analytic"), sel = rows.find(r => r.label === S.sel);
  const three = UP.same_bandwidth_three_ways, trow = l => rows.find(r => r.label === l);
  const body = `
    <div class="phead"><div><div class="eyebrow">${T("系统框图 · 结构示意", "System block diagram · structure only")}</div>
      <h2 style="margin-top:3px">${T("两条拓扑，一个共用的 60 GHz 前端", "Two topologies, one shared 60 GHz front end")}</h2>
      <p class="sub">${esc(bt(SY.what_is_shared))}</p></div></div>
    <div class="ctl">
      <label class="seglab" for="sysrow-sel"><span>${T("点亮哪一行的 EVM 分项", "Light up the EVM terms of")}</span>
        <select id="sysrow-sel" data-sel="sel" class="selbox"><option value="">${T("（不点亮）", "(none)")}</option>${rows.map(r => `<option value="${esc(r.label)}" ${r.label === S.sel ? "selected" : ""}>${esc(r.label)}</option>`).join("")}</select></label>
      ${R ? "" : `<span class="sm mut">${T("没有存着的同台表：框图照画，分项点不亮。", "No comparison table is stored: the diagram is drawn, the terms cannot be lit.")}</span>`}
      ${Object.keys(SY.study || {}).length ? `<span class="sm">${T("框图上的参数跟着表单", "The diagram’s parameters follow the form")}${P_.c}<code>${esc(JSON.stringify(SY.study))}</code> ${tagEdited()}</span>` : ""}
    </div>
    ${stt ? `<div class="fresh" style="border-color:var(--ink)" data-lit-row="${esc(stt.r.label)}"><span class="b">${esc(stt.r.label)}</span>
      <span>${T("EVM 预算分项（未校准链，解析和）", "EVM budget terms (raw chain, analytic sum)")}${P_.c}</span>
      ${stt.list.map(x => `<span class="${x.dom ? "b" : ""}">${esc(x.name)} <span class="n">${sv(ta, absent(x.v) ? "—" : fx(x.v, 1) + " dB", "table.analytic")}</span>${x.dom ? ` <span class="vd best">${T("主导", "dominant")}</span>` : ""}</span>`).join("")}
      <span class="grow"></span><span>${T("底板", "floor")} <span class="n">${sv(ta, `${fx(stt.r.floor_db, 1)} → <b>${fx(stt.r.floor_cal_db, 1)} dB</b>`, "table.analytic")}</span></span></div>`
    : sel && isAy(sel) ? ayStrip(SY, lit, sel) : ""}
    <div class="lg sysleg">
      <span><span class="sw" style="background:var(--tb)"></span>${T("拓扑 B：升频零中频", "Topology B: upclocked zero-IF")}</span><span><span class="sw" style="background:var(--ta)"></span>${T("拓扑 A：IF 延伸", "Topology A: IF extender")}</span>
      <span><span class="sw dbl"></span>${T("双线框 = 两条拓扑共用的同一个对象", "double frame = the one object both topologies share")}</span>
      <span><i style="border-color:var(--ink)"></i>${T("信号", "signal")}</span><span><i class="dot" style="border-color:var(--ink3)"></i>${T("本振", "LO")}</span><span><i class="dash" style="border-color:var(--amber-line)"></i>${T("校准 / 预补偿回环", "calibration / pre-compensation loop")}</span>
      <span><span class="kdl">× K</span> ${T("时钟 × K 走到的范围（斜纹底）", "how far the × K clock reaches (hatched ground)")}</span>
      <span>⟲ ${T("管这一块的校准步骤", "calibration steps that own this block")}</span>
      <span><b class="n">S V A D</b> ${T("出处：spec / survey / assumed / derived（点开看原文）；✎ = 表单改过的值", "source: spec / survey / assumed / derived (click for the citation); ✎ = a value the form changed")}</span>
      <span><span class="vd best">${T("项 dB", "term dB")}</span> ${T("这一行的 EVM 分项落在哪一块；黑底 = 主导项", "where this row’s EVM terms come from; black = dominant")}</span>
    </div>
    <div class="sysbox" tabindex="0" aria-label="${T("框图，可左右滚动", "diagram, scrolls sideways")}"><div class="chartbox" data-chart="sys"></div></div>
    <p class="xs mut onlynarrow">${T("← 左右滑动看全图；下面的清单是同一批内容的竖排版本 →", "← swipe sideways for the whole diagram; the list below carries the same content stacked →")}</p>
    <div class="g2">
      <section class="blk"><header><h3>${T("两个插入点", "The two insertion points")}</h3></header>
        <p>${badge("if_extender")} ${esc(bt(SY.insertion_points.topology_a))}</p><p>${badge("upclock_zero_if")} ${esc(bt(SY.insertion_points.topology_b))}</p></section>
      <section class="blk"><header><h3>${T("只有一条拓扑才有的项", "Terms only one topology has")}</h3></header>
        <p>${badge("if_extender")} ${esc(bt(SY.only_in.topology_a))}</p><p>${badge("upclock_zero_if")} ${esc(bt(SY.only_in.topology_b))}</p>
        <div class="eyebrow">${T("时钟 × K 走到哪一步", "How far the × K clock reaches")}</div>
        <p>${badge("if_extender")} ${esc(bt(UP.topology_a))} ${tagOf(UP.topology_a)}</p><p>${badge("upclock_zero_if")} ${esc(bt(UP.topology_b))}</p></section>
    </div>
    <section class="blk"><header><h3>${esc(bt(three))}</h3><span class="mut sm">${hz(three.bandwidth_hz)} · ${T("未校准链", "raw chain")}</span></header>
      ${tbl([{ h: T("同台表的行", "Row of the comparison table"), f: l => { const r = trow(l); return `${r ? `<span style="display:inline-flex;gap:6px;align-items:center;flex-wrap:wrap">${rowName(r, R).l1}</span>` : ""}<div class="xs mut n">${esc(l)}</div>`; } },
      { h: "K", r: 1, f: l => (trow(l) ? plain(trow(l).k) : "—") }, { h: T("带宽 MHz", "Bandwidth MHz"), r: 1, f: l => (trow(l) ? mhz(trow(l).bw_eff_hz) : "—") }, { h: T("子载波间隔", "Subcarrier spacing"), r: 1, f: l => (trow(l) ? hz(trow(l).scs_eff_hz) : "—") },
      { h: T("相噪 ICI dB", "Phase-noise ICI dB"), r: 1, f: l => (trow(l) && trow(l).evm_budget ? sv(ta, fx(trow(l).evm_budget.pn_ici_db, 1), "table.analytic") : "—") }, { h: T("底板 dB", "Floor dB"), r: 1, f: l => (trow(l) ? sv(ta, fx(trow(l).floor_db, 1), "table.analytic") : "—") },
      { h: T("时域 EVM dB", "Time-domain EVM dB"), r: 1, f: l => (trow(l) ? sv(pstate("table.td"), fx(trow(l).td_evm_db, 1), "table.td") : "—") }, { h: T("合规上限", "Conformance cap"), f: l => (trow(l) ? sv(ta, mcs(trow(l).max_mcs), "table.analytic") : "—") },
      { h: T("× K 走到哪", "Where × K reaches"), f: l => { const r = trow(l); return !r ? "" : r.k === 1 ? T("不升频：原生信道", "not upclocked: the native channel") : `<span class="kdl">× K</span> ${r.topology === "if_extender" ? T("只到数字基带", "digital baseband only") : T("数字和模拟都升", "digital and analog")}`; } }], three.rows || [])}
      <p class="note">${T("拓扑 A 的 K × 基准带宽必须是芯片有的信道", "In topology A, K × base bandwidth must be one of the chip’s channels")}${P_.c}<span class="n">${(UP.topology_a.chip_channels_hz || []).map(mhz).join(" / ")} MHz</span> ${tag(UP.topology_a.chip_channels_source_key)}${P_.s}${T("同台表里 A × be_upclocked 的行", "A × be_upclocked rows in the comparison table")}${P_.c}${(UP.topology_a.rows_in_comparison_table || []).length}${P_.s}${T("越界而没有数的", "out of range, without numbers")}${P_.c}${(UP.topology_a.rows_without_numbers || []).map(l => `<code>${esc(l)}</code>`).join(P_.d)}</p></section>
    <section class="blk"><header><h3>${T("EVM 预算的每一项来自哪一块", "Which block each EVM budget term comes from")}</h3></header>
      ${tbl([{ h: T("项", "Term"), f: e => term(e[0]) }, { h: T("来自的块", "Blocks"), f: e => e[1].blocks.map(b => `<code>${esc(b)}</code>`).join(" · ") }, { h: T("说明", "What it is"), f: e => esc(bt(e[1])) },
      { h: T("这一行 dB", "This row, dB"), r: 1, f: e => { const v = stt ? stt.r.terms_db[e[0]] : undefined; return v === undefined ? '<span class="mut">·</span>' : sv(ta, absent(v) ? "—" : fx(v, 1), "table.analytic"); } }], Object.entries(SY.evm_term_to_block))}
      <p class="note">${T("两条校准回环", "Two calibration loops")}${P_.c}${badge("upclock_zero_if")} ${esc(bt(SY.topology_b_chain.calibration_loop))}　${badge("if_extender")} ${esc(bt(SY.topology_a_chain.calibration_loop))}</p>
      <p class="note warn">${esc(bt(SY.engine_caveat))}</p></section>
    <details class="fold" open><summary>${T("各块的全部参数与出处（框图的清单版）", "Every block’s parameters and sources (the diagram as a list)")}</summary><div>${sysCards(SY)}</div></details>`;
  return `<div class="page">${body}</div>`;
}
