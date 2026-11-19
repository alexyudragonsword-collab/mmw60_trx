/* Inline-SVG charts, drawn at the container's pixel width.  A chart places payload values on
 * an axis; the axis range is fitted to the values drawn, nothing else is derived. */
"use strict";
const lin = (d0, d1, r0, r1) => v => r0 + (v - d0) / ((d1 - d0) || 1) * (r1 - r0);
const lgs = (d0, d1, r0, r1) => v => r0 + (Math.log(v) - Math.log(d0)) / ((Math.log(d1) - Math.log(d0)) || 1) * (r1 - r0);
const P = n => (Math.round(n * 10) / 10);
const svg = (w, h, inner, label) => `<svg class="cx" width="${w}" height="${P(h)}" viewBox="0 0 ${w} ${P(h)}" role="img" aria-label="${esc(label || "")}">${inner}</svg>`;
const tx = (x, y, s, o = {}) => `<text x="${P(x)}" y="${P(y)}" ${o.a ? `text-anchor="${o.a}"` : ""} class="${o.c || ""}">${s}</text>`;
const ln = (x1, y1, x2, y2, c, extra = "") => `<line x1="${P(x1)}" y1="${P(y1)}" x2="${P(x2)}" y2="${P(y2)}" class="${c}" ${extra}/>`;
const path = (pts, color, extra = "") => (pts.length < 2 ? "" : `<path d="${pts.map((p, i) => (i ? "L" : "M") + P(p[0]) + " " + P(p[1])).join("")}" fill="none" stroke="${color}" stroke-width="2" stroke-linejoin="round" ${extra}/>`);
const dot = (x, y, color, tip, r = 4) => `<circle cx="${P(x)}" cy="${P(y)}" r="${r}" fill="${color}" stroke="var(--panel)" stroke-width="2" data-tip="${esc(tip || "")}"/>`;
const num = v => (typeof v === "number" ? v : null);
const fin = a => a.filter(v => typeof v === "number" && isFinite(v));
/* an axis range that holds the values, snapped outward to a round step */
function span(vals, step, pad = 0) { const f = fin(vals); if (!f.length) return [0, 1]; const a = Math.floor((Math.min(...f) - pad) / step) * step, b = Math.ceil((Math.max(...f) + pad) / step) * step; return a === b ? [a, a + step] : [a, b]; }
function ticks(d0, d1, n = 5) { const raw = (d1 - d0) / n, p = Math.pow(10, Math.floor(Math.log10(raw))), s = [1, 2, 5, 10].map(m => m * p).find(m => m >= raw) || raw, out = []; for (let t = Math.ceil(d0 / s) * s; t <= d1 + s * 1e-9; t += s) out.push(Number(t.toPrecision(10))); return out; }
function logSpan(vals) { const f = fin(vals).filter(v => v > 0); if (!f.length) return [1, 10]; const a = Math.pow(10, Math.floor(Math.log10(Math.min(...f)))), b = Math.pow(10, Math.ceil(Math.log10(Math.max(...f)))); return a === b ? [a, a * 10] : [a, b]; }
function decades(d0, d1) { const out = []; for (let t = d0; t <= d1 * 1.0001; t *= 10) out.push(Number(t.toPrecision(6))); return out; }
/* the reports write an absent EVM term as a very large negative number: it is drawn as absent, not as a point */
const ABSENT_DB = -200;
const absent = v => nil(v) || v <= ABSENT_DB;
const TINT = [1, .68, .44, .28, .16, .56, .36, .8, .22];

/* dB ladder: one row per term, position only (a dB axis has no zero to grow a bar from) */
function ladder(w, o) {
  const two = o.series.length > 1, stack = w < 520;
  const L = stack ? 0 : Math.min(210, w * 0.32), R = two ? 118 : 52, top = 48, rh = stack ? 38 : 26;
  const dom = span([...o.rows.flatMap(r => r.vals), ...(o.refs || []).map(r => r.v)].filter(v => !absent(v)), 5, 1), x = lin(dom[0], dom[1], L + 6, w - R - 6);
  const h = top + o.rows.length * rh + 4; let s = "";
  ticks(dom[0], dom[1], w < 520 ? 4 : 8).forEach(t => { s += ln(x(t), top - 4, x(t), h - 4, "grid") + tx(x(t), top - 9, plain(t), { a: "middle", c: "m q" }); });
  s += tx(L + 6, 10, T("← 更好　EVM dB", "← better　EVM dB"), { c: "q" });
  if (two) o.series.forEach((se, i) => { s += `<rect x="${w - R + 8 + i * 56}" y="${top - 17}" width="8" height="8" rx="2" fill="${se.color}"/>` + tx(w - R + 19 + i * 56, top - 9, se.name, { c: "q" }); });
  (o.refs || []).forEach(r => { if (absent(r.v)) return; s += ln(x(r.v), top - 22, x(r.v), h - 4, "axis", `stroke-dasharray="${r.dash ? "4 3" : ""}" style="stroke:var(--ink)"`) + tx(x(r.v) + (r.side || 1) * 5, top - 24, r.label, { a: r.side === -1 ? "end" : "start", c: "m k" }); });
  o.rows.forEach((r, i) => {
    const y = top + i * rh + (stack ? 26 : rh / 2);
    s += tx(0, stack ? y - 12 : y + 4, esc(r.label), { c: r.k ? "k" : "" }) + ln(L + 6, y, w - R - 6, y, "grid");
    r.vals.forEach((v, j) => {
      const xr = two ? w - R + 8 + j * 56 : w - R + 2;
      if (absent(v)) { s += tx(xr, y + 4, "—", { c: "m q" }); return; }
      s += dot(x(v), y, o.series[j].color, `${r.label} · ${o.series[j].name}: ${fx(v, 1)} dB`, r.k ? 5.5 : 4.5) + tx(xr, y + 4, fx(v, 1), { c: "m" + (r.k ? " k" : "") });
    });
  });
  return svg(w, h, s, o.label);
}
/* stacked bars with direct labels; tints of one ink so no hue is spent on blocks */
function stackBars(w, o) {
  const stack = w < 520, L = stack ? 0 : Math.min(190, w * 0.3), R = 8, rh = stack ? 50 : 34, top = 4, mx = Math.max(...o.rows.map(r => r.segs.reduce((a, b) => a + (b.v || 0), 0)), 1e-12);
  const x = lin(0, mx, L, w - R); let s = "";
  o.rows.forEach((r, i) => {
    const y = top + i * rh + (stack ? 16 : 0); let acc = 0;
    s += tx(0, stack ? y - 4 : y + 12, esc(r.label), { c: "k" }) + (r.sub ? tx(stack ? w - R : 0, stack ? y - 4 : y + 25, esc(r.sub), { c: "m q", a: stack ? "end" : "start" }) : "");
    r.segs.forEach(g => {
      const v = g.v || 0, x0 = x(acc), x1 = x(acc + v), bw = Math.max(1, x1 - x0 - 2), op = TINT[o.keys.indexOf(g.k) % TINT.length];
      s += `<rect x="${P(x0)}" y="${y}" width="${P(bw)}" height="20" rx="2" fill="var(--ink)" fill-opacity="${op}" data-tip="${esc(g.name)}: ${sig(v)} ${o.unit}"/>`;
      if (bw > 34) s += `<text x="${P(x0 + 5)}" y="${y + 14}" class="m" style="fill:${op > .5 ? "var(--panel)" : "var(--ink)"}" pointer-events="none">${sig(v)}</text>`;
      acc += v;
    });
  });
  return svg(w, top + o.rows.length * rh + (stack ? 0 : -8), s, o.label);
}
const legendTint = (keys, name) => `<div class="lg">${keys.map((k, i) => `<span><span class="sw" style="background:var(--ink);opacity:${TINT[i % TINT.length]}"></span>${name(k)}</span>`).join("")}</div>`;
/* text measuring (an estimate) and wrapping for SVG, which has no line breaking of its own */
const tw = (str, fs = 10.5) => { let w = 0; for (const ch of String(str)) w += ch.charCodeAt(0) > 0x2e7f ? fs : /[A-Z@%MW]/.test(ch) ? fs * 0.68 : /[ilj.,:;·'|()\[\] ]/.test(ch) ? fs * 0.32 : fs * 0.6; return w; };
function wrapTx(str, maxW, fs = 10.5) {
  const out = []; let cur = "";
  const toks = String(str).match(/[⺀-￿]|[^\s⺀-￿]+\s*|\s+/g) || [];
  for (const t of toks) { if (cur && tw(cur + t, fs) > maxW) { out.push(cur.trimEnd()); cur = t.trimStart(); } else cur += t; }
  if (cur.trim()) out.push(cur.trimEnd());
  return out;
}
const arrowHead = (x, y, dir, c = "var(--ink2)") => { const d = { r: [[-7, -3.5], [-7, 3.5]], l: [[7, -3.5], [7, 3.5]], d: [[-3.5, -7], [3.5, -7]], u: [[-3.5, 7], [3.5, 7]] }[dir]; return `<polygon points="${P(x)},${P(y)} ${P(x + d[0][0])},${P(y + d[0][1])} ${P(x + d[1][0])},${P(y + d[1][1])}" fill="${c}"/>`; };
/* a plain x / y frame with grid lines; returns the svg text and the two scales */
function frame(w, o) {
  const ml = o.ml || 40, mr = o.mr || 14, top = o.top || 10, hh = o.h || 210;
  const x = (o.xlog ? lgs : lin)(o.xd[0], o.xd[1], ml, w - mr), y = (o.ylog ? lgs : lin)(o.yd[0], o.yd[1], top + hh, top); let s = "";
  (o.xt || (o.xlog ? decades(...o.xd) : ticks(o.xd[0], o.xd[1], w < 520 ? 4 : 7))).forEach(t => { s += ln(x(t), top, x(t), top + hh, "grid") + tx(x(t), top + hh + 13, plain(t), { a: "middle", c: "m q" }); });
  (o.yt || (o.ylog ? decades(...o.yd) : ticks(o.yd[0], o.yd[1], 5))).forEach(t => { s += ln(ml, y(t), w - mr, y(t), "grid") + tx(ml - 6, y(t) + 3.5, plain(t), { a: "end", c: "m q" }); });
  s += tx(w - mr, top + hh + 27, o.xl || "", { a: "end", c: "q" }) + tx(ml + 4, top + 9, o.yl || "", { c: "q" });
  return { s, x, y, ml, mr, top, hh, h: top + hh + 32 };
}

const CHARTS = {
  /* row detail: each EVM term alone, with the two floors as reference lines */
  terms(w) {
    const r = S.row.row;
    const rows = Object.entries(r.terms_db).map(t => ({ label: term(t[0]) + (t[0] === r.dominant ? T("（主导）", " (dominant)") : ""), vals: [t[1]], k: t[0] === r.dominant }));
    return ladder(w, { rows, series: [{ name: T("单独 EVM", "EVM alone"), color: `var(--${r.topology === "if_extender" ? "ta" : "tb"})` }], label: T("各项单独的 EVM", "EVM of each term alone"),
      refs: [{ v: r.floor_db, label: `${T("底板", "floor")} ${fx(r.floor_db, 1)}`, side: 1 }, { v: r.floor_cal_db, label: `${T("校准后", "calibrated")} ${fx(r.floor_cal_db, 1)}`, dash: 1, side: -1 }] });
  },
  /* each impairment switched on alone, both 802.11ay waveforms */
  imp(w) {
    const A = S.rep.ay && S.rep.ay.report; if (!A) return "";
    const rows = A.impairments_alone.map(x => ({ label: x.impairment, vals: [x.ay_sc_evm_db, x.ay_ofdm_evm_db] }));
    return ladder(w, { rows, series: [{ name: "SC", color: "var(--sc)" }, { name: "OFDM", color: "var(--ofdm)" }], label: T("每个损伤单独开", "each impairment alone") });
  },
  power(w) {
    const r = S.row.row, pts = powerPoints(r).filter(p => p.p);
    if (!pts.length) return "";
    const keys = [...new Set(pts.flatMap(p => Object.keys(p.p.blocks)))];
    const rows = pts.map(p => ({ label: p.name, sub: `${p.cap} · ${fx(p.p.pj_per_bit, 0)} pJ/bit`, segs: keys.filter(k => p.p.blocks[k]).map(k => ({ k, name: term(k), v: p.p.blocks[k].pj_per_bit })) }));
    return legendTint(keys, term) + stackBars(w, { rows, keys, unit: "pJ/bit", label: "pJ/bit" });
  },
  /* steps x columns: which step degrades where, the two verdicts kept apart */
  calmx(w, el) {
    const C = calReport(); if (!C) return "";
    const cols = C.columns, ci = cols.findIndex(c => c.label === el.dataset.col), L = Math.min(150, w * 0.38), cw = (w - L) / cols.length, top = 30, rh = 15, h = top + C.steps.length * rh + 4;
    let o = ci >= 0 ? `<rect x="${P(L + ci * cw)}" y="0" width="${P(cw)}" height="${h}" fill="var(--sunk)" rx="3"/>` : "";
    cols.forEach((c, j) => { const [a, b] = c.label.split(" "); o += `<text x="${P(L + j * cw + cw / 2)}" y="11" text-anchor="middle" class="m ${j === ci ? "k" : "q"}">${esc(a)}</text><text x="${P(L + j * cw + cw / 2)}" y="22" text-anchor="middle" class="m ${j === ci ? "k" : "q"}">${esc(b || "")}</text>`; });
    C.steps.forEach((sp, i) => {
      const y = top + i * rh + rh / 2;
      o += `<text x="0" y="${y + 3.5}" class="m">${esc(sp.step)}</text>` + ln(L, y + rh / 2, w, y + rh / 2, "grid");
      sp.cells.forEach((x, j) => {
        if (!x) return;
        const cx = L + j * cw + cw / 2, tip = `${sp.step} · ${cols[j].label}\nwifitrx: ${x.status_wifitrx} · ${T("汇总表", "summary")}: ${x.status_summary}${nil(x.value) ? "" : "\n" + fx(x.value, 1) + " " + metricUnit(x.metric)}`;
        const tri = `M${P(cx)} ${y - 5}L${P(cx + 5.5)} ${y + 4.5}L${P(cx - 5.5)} ${y + 4.5}Z`;
        if (x.status_wifitrx !== "ok") o += `<path d="${tri}" fill="var(--amber-line)" stroke="var(--amber-line)" stroke-width="1.2" stroke-linejoin="round" data-tip="${esc(tip)}"/>`;
        else if (x.status_summary !== "ok") o += `<path d="${tri}" fill="var(--panel)" stroke="var(--amber-line)" stroke-width="1.4" stroke-linejoin="round" data-tip="${esc(tip)}"/>`;
        else o += `<circle cx="${P(cx)}" cy="${y}" r="2.2" fill="var(--rule2)"/><rect x="${P(cx - cw / 2)}" y="${y - rh / 2}" width="${P(cw)}" height="${rh}" fill="transparent" data-tip="${esc(tip)}"/>`;
      });
    });
    return svg(w, h, o, T("校准步骤在各列上的状态", "calibration step status by column"));
  },
  arrpower(w) {
    const a = arrSel(); if (!a.pw.length) return "";
    const keys = ["pa", "ps", "rest"], nm = { pa: "PA", ps: T("移相器", "phase shifters"), rest: T("其余", "the rest") };
    const rows = a.pw.map(p => ({ label: `N = ${p.n}`, sub: `${sig(p.total_mw)} mW · ${fx(p.pj_per_bit, 0)} pJ/bit`, segs: [{ k: "pa", name: nm.pa, v: p.pa_mw }, { k: "ps", name: nm.ps, v: p.phase_shifters_mw }, { k: "rest", name: nm.rest, v: p.rest_mw }] }));
    return legendTint(keys, k => nm[k]) + stackBars(w, { rows, keys, unit: "mW", label: "mW" });
  },
  /* three aligned panels against N: the limit, what it does per element, what it does to range */
  array(w) {
    const a = arrSel(), AR = S.rep.array.report, Lm = AR.eirp_limit, col = `var(--${a.color})`, ml = 44, mr = w < 520 ? 14 : 96, nar = w < 520;
    const sizes = AR.header.sizes, nmax = Math.max(...sizes, a.bindN || 1), x = lgs(Math.min(...sizes), nmax, ml, w - mr);
    const H1 = 118, H2 = 100, H3 = 150, g = 34, t1 = 30, t2 = t1 + H1 + g, t3 = t2 + H2 + g, h = t3 + H3 + 26;
    const ns = [...new Set([...a.rows.map(r => r.n), ...(a.bindN ? [a.bindN] : [])])].sort((p, q) => p - q); let o = "";
    if (a.bindN) {
      o += `<rect x="${P(x(a.bindN))}" y="${t1 - 14}" width="${P(x(nmax) - x(a.bindN))}" height="${h - t1 - 12}" fill="var(--shade)"/>` + ln(x(a.bindN), t1 - 14, x(a.bindN), h - 26, "axis", 'style="stroke:var(--amber-line)" stroke-dasharray="3 3"');
      o += tx(x(a.bindN) + (nar ? -4 : 4), t1 - 18, T(`N ≥ ${a.bindN}：上限起作用`, `N ≥ ${a.bindN}: the limit binds`), { c: "k", a: nar ? "end" : "start" });
    }
    const panel = (top, H, title, tk, y) => {
      let p = tx(0, top - 6, title, { c: "k" });
      tk.forEach(t => { p += ln(ml, y(t), w - mr, y(t), "grid") + tx(ml - 6, y(t) + 3.5, plain(t), { a: "end", c: "m q" }); });
      ns.forEach(n => { p += ln(x(n), top + H, x(n), top + H + 4, "axis"); });
      return p + ln(ml, top + H, w - mr, top + H, "axis");
    };
    /* 1: EIRP against the limit */
    const d1 = span([...a.rows.map(r => r.eirp_dbm), Lm.limit_avg_dbm], 10, 2), y1 = lin(d1[0], d1[1], t1 + H1, t1); o += panel(t1, H1, "EIRP dBm", ticks(d1[0], d1[1], 4), y1);
    o += ln(ml, y1(Lm.limit_avg_dbm), w - mr, y1(Lm.limit_avg_dbm), "axis", 'style="stroke:var(--amber-line);stroke-width:2"');
    o += tx(ml + 4, y1(Lm.limit_avg_dbm) - 5, `${fx(Lm.limit_avg_dbm, 1)} dBm ${T("平均上限", "average limit")}`, { c: "k" });
    o += path(a.rows.map(r => [x(r.n), y1(r.eirp_dbm)]), col);
    a.rows.forEach(r => { o += dot(x(r.n), y1(r.eirp_dbm), col, `N = ${r.n}: EIRP ${fx(r.eirp_dbm, 1)} dBm`) + tx(x(r.n) + 7, y1(r.eirp_dbm) + 13, fx(r.eirp_dbm, 1), { c: "m" }); });
    /* 2: output per element */
    const pe = a.rows.map(r => [r.n, r.element_pout_dbm, r.obo_db]).concat(a.small ? [[a.small.n, a.small.element_pout_dbm, a.small.operating_obo_db, 1]] : []).sort((p, q) => p[0] - q[0]);
    const d2 = span(pe.map(p => p[1]), 4, 1), y2 = lin(d2[0], d2[1], t2 + H2, t2); o += panel(t2, H2, T("每单元输出 dBm 与回退", "Output per element, dBm, and back-off"), ticks(d2[0], d2[1], 4), y2);
    o += path(pe.map(p => [x(p[0]), y2(p[1])]), col);
    pe.forEach((p, i) => { const last = i === pe.length - 1; o += dot(x(p[0]), y2(p[1]), col, `N = ${p[0]}: ${fx(p[1], 1)} dBm, ${T("回退", "back-off")} ${fx(p[2], 1)} dB${p[3] ? " · " + T("顶到上限的最小阵列", "smallest array at the limit") : ""}`); if (i === 0 || last) o += tx(x(p[0]) + 6, y2(p[1]) + (last ? 16 : -8), `${fx(p[1], 1)} dBm · ${T("回退", "back-off")} ${fx(p[2], 1)} dB`, { c: "m" + (last ? " k" : ""), a: last ? "end" : "start" }); });
    /* 3: range, log */
    const ser = a.series, d3 = logSpan(a.rows.flatMap(r => ser.map(se => r[se[0]]))), y3 = lgs(d3[0], d3[1], t3 + H3, t3); o += panel(t3, H3, T("距离 m（对数）", "Range, m (log)"), decades(...d3), y3);
    ser.forEach((se, k) => {
      const pts = a.rows.filter(r => num(r[se[0]]) > 0).map(r => [r.n, r[se[0]], r.cap_mcs]);
      o += path(pts.map(p => [x(p[0]), y3(p[1])]), col, `stroke-dasharray="${se[2]}"`);
      pts.forEach((p, i) => { o += dot(x(p[0]), y3(p[1]), col, `N = ${p[0]} · ${se[1]}: ${sig(p[1])} m${se[3] ? " @" + mcs(p[2]) : ""}`, 3.5); if (i === pts.length - 1 || (k === 0 && !nar)) o += tx(x(p[0]) + (i === pts.length - 1 && !nar ? 7 : 0), y3(p[1]) + (i === pts.length - 1 && !nar ? 4 : -8), sig(p[1]), { c: "m", a: i === pts.length - 1 && !nar ? "start" : "middle" }); });
    });
    ns.forEach(n => { o += tx(x(n), h - 10, n, { a: "middle", c: "m" + (n === a.bindN ? " k" : " q") }); });
    if (!nar) o += tx(w - mr + 14, h - 10, T("N 单元", "N elements"), { c: "q" });
    return `<div class="lg">${ser.map(se => `<span><i style="border-color:${col};border-top-style:${se[2] === "" ? "solid" : se[2] === "5 4" ? "dashed" : "dotted"}"></i>${T("距离", "range")} · ${se[1]}</span>`).join("")}</div>` + svg(w, h, o, T("EIRP、每单元输出与距离随 N", "EIRP, output per element and range against N"));
  },
  /* every scheme of the array report on one range plot */
  arrall(w) {
    const AR = S.rep.array.report, cap = S.arrAll === "cap", nar = w < 560, Lm = AR.eirp_limit, sizes = AR.header.sizes, nmax = Math.max(...sizes), nb = Lm.binds_from_n;
    const ser = arrSchemes().map((s, i) => { const rows = arrRowsOf(s, "preset"), k = cap ? "range_cap_m" : s.kind === "be" ? "range_mcs0_m" : "range_mcs1_m"; return { s, pts: rows.filter(r => num(r[k]) > 0).map(r => [r.n, r[k], r.cap_mcs]), col: `var(--${s.color})`, dash: s.dash ? "5 4" : "" }; });
    const F = frame(w, { ml: 40, mr: nar ? 14 : 214, top: 22, h: 210, xlog: 1, ylog: 1, xd: [Math.min(...sizes), nmax], xt: [...sizes, ...(nb ? [nb] : [])], yd: logSpan(ser.flatMap(se => se.pts.map(p => p[1]))) });
    let o = F.s + tx(0, F.top - 6, T("距离 m（对数）", "Range, m (log)"), { c: "k" });
    if (nb && nb <= nmax) o += `<rect x="${P(F.x(nb))}" y="${F.top}" width="${P(F.x(nmax) - F.x(nb))}" height="${F.hh}" fill="var(--shade)"/>` + ln(F.x(nb), F.top, F.x(nb), F.top + F.hh, "axis", 'style="stroke:var(--amber-line)" stroke-dasharray="3 3"') + tx(F.x(nb) + (nar ? -4 : 4), F.top - 6, T(`N ≥ ${nb}：上限起作用`, `N ≥ ${nb}: the limit binds`), { c: "k", a: nar ? "end" : "start" });
    ser.forEach(se => { o += path(se.pts.map(p => [F.x(p[0]), F.y(p[1])]), se.col, `stroke-dasharray="${se.dash}"`); se.pts.forEach(p => { o += dot(F.x(p[0]), F.y(p[1]), se.col, `${se.s.name} · N = ${p[0]}: ${sig(p[1])} m${cap ? " @" + mcs(p[2]) : ""}`, 3.5); }); });
    const lastOf = se => se.pts[se.pts.length - 1];
    if (!nar) {
      const lab = ser.filter(lastOf).map(se => ({ se, y0: F.y(lastOf(se)[1]) })).sort((p, q) => p.y0 - q.y0); let prev = -99;
      lab.forEach(l => { l.y = Math.max(l.y0, prev + 13); prev = l.y; });
      lab.forEach(l => { const p = lastOf(l.se); o += `<path d="M${P(F.x(p[0]) + 5)} ${P(l.y0)}L${P(F.x(nmax) + 14)} ${P(l.y)}" stroke="${l.se.col}" fill="none"/>` + `<text x="${P(F.x(nmax) + 18)}" y="${P(l.y + 3.5)}"><tspan class="m k">${sig(p[1])} m</tspan><tspan class="q"> ${cap ? "@" + mcs(p[2]) + " · " : ""}${esc(l.se.s.name)}</tspan></text>`; });
    }
    return `<div class="lg">${ser.map(se => `<span><i style="border-color:${se.col};border-top-style:${se.dash ? "dashed" : "solid"}"></i>${esc(se.s.name)}${nar && lastOf(se) ? ` <b class="n">${sig(lastOf(se)[1])} m</b>${cap ? " @" + mcs(lastOf(se)[2]) : ""}` : ""}</span>`).join("")}</div>` + svg(w, F.h - 8, o, T("各方案的距离随 N", "range of every scheme against N"));
  },
  /* rate x range as areas from zero: the headline of SC against OFDM */
  prod(w) {
    const H = S.rep.ay && S.rep.ay.headline; if (!H) return "";
    const A = H.same_modulation_16qam_3_4, B = H.own_decoder_cap, all = [A.ay_sc, A.ay_ofdm, B.ay_sc, B.ay_ofdm];
    const F = frame(w, { ml: 34, mr: 12, top: 10, h: Math.min(210, Math.max(150, w * 0.42)), xd: [0, span(all.map(p => p.range_m), 50, 10)[1]], yd: [0, span(all.map(p => p.rate_bps / 1e9), 1, 0.5)[1]], xl: T("距离 m", "range, m"), yl: "Gb/s" });
    let o = F.s;
    const rect = (p, c, tip) => (nil(p.range_m) || nil(p.rate_bps) ? "" : `<rect x="${P(F.x(0))}" y="${P(F.y(p.rate_bps / 1e9))}" width="${P(F.x(p.range_m) - F.x(0))}" height="${P(F.y(0) - F.y(p.rate_bps / 1e9))}" fill="${c}" fill-opacity=".10" stroke="${c}" stroke-width="2" data-tip="${tip}: ${gbps(p.rate_bps)} Gb/s × ${fx(p.range_m, 0)} m"/>`);
    o += rect(A.ay_ofdm, "var(--ofdm)", "OFDM 16-QAM 3/4") + rect(A.ay_sc, "var(--sc)", "SC 16-QAM 3/4") + rect(B.ay_ofdm, "var(--ofdm)", "OFDM " + mcs(B.mcs.ay_ofdm)) + rect(B.ay_sc, "var(--sc)", "SC " + mcs(B.mcs.ay_sc));
    const lab = (p, title, x0, anchor) => (nil(p.ay_ofdm.range_m) ? "" : tx(x0, F.y(p.ay_ofdm.rate_bps / 1e9) + 15, title, { a: anchor, c: "k" }) + tx(x0, F.y(p.ay_ofdm.rate_bps / 1e9) + 29, `SC ${gbps(p.ay_sc.rate_bps)} Gb/s · ${fx(p.ay_sc.range_m, 0)} m`, { a: anchor, c: "m" }) + tx(x0, F.y(p.ay_ofdm.rate_bps / 1e9) + 42, `OFDM ${gbps(p.ay_ofdm.rate_bps)} Gb/s · ${fx(p.ay_ofdm.range_m, 0)} m`, { a: anchor, c: "m" }));
    o += lab(A, "16-QAM 3/4", F.x(A.ay_ofdm.range_m || 0) - 8, "end") + lab(B, T("解码器上限", "decoder cap"), F.x(0) + 6, "start");
    return svg(w, F.h, o, T("速率 × 距离", "rate × range"));
  },
  /* single antenna: every MCS of both waveforms at its best back-off */
  rr(w) {
    const A = S.rep.ay.report, rows = A.rate_vs_range, pos = v => num(v) > 0;
    const F = frame(w, { ml: 34, mr: 14, top: 8, h: 220, xlog: 1, xd: logSpan(rows.flatMap(p => [p.best_range_m, p.multipath_best_range_m])), yd: [0, span(rows.map(p => p.rate_bps / 1e9), 1, 0.3)[1]], xl: T("距离 m（对数）", "range, m (log)"), yl: "Gb/s" });
    let o = F.s;
    const line = (wf, key) => rows.filter(p => p.waveform === wf && pos(p[key])).sort((a, b) => a.rate_bps - b.rate_bps).map(p => [F.x(p[key]), F.y(p.rate_bps / 1e9), p]);
    [["ay_ofdm", "var(--ofdm)", "1.5 4"], ["ay_sc", "var(--sc)", "5 4"]].forEach(s => { o += path(line(s[0], "multipath_best_range_m"), s[1], `stroke-dasharray="${s[2]}" stroke-width="1.5" opacity=".8"`); });
    [["ay_ofdm", "var(--ofdm)", "OFDM"], ["ay_sc", "var(--sc)", "SC"]].forEach(s => {
      const f = line(s[0], "best_range_m"); o += path(f, s[1]);
      f.forEach(q => { const p = q[2]; o += dot(q[0], q[1], s[1], `${s[2]} ${mcs(p.mcs)} ${p.modulation} ${p.code_rate}: ${gbps(p.rate_bps)} Gb/s → ${sig(p.best_range_m)} m (${T("回退", "back-off")} ${fx(p.best_backoff_db, 1)} dB)`, 3); });
      if (f.length) o += tx(f[0][0] + 6, f[0][1] - 5, s[2], { c: "k" });
    });
    return svg(w, F.h, o, T("速率对距离", "rate against range"));
  },
  /* EVM against back-off with IQ and leakage calibrated away: the 16-QAM and 64-QAM payloads */
  evmbo(w) {
    const A = S.rep.ay.report, E = A.evm_vs_backoff.filter(r => r.tone_order >= 16);
    const F = frame(w, { ml: 38, mr: 14, top: 8, h: 220, xd: span(E.flatMap(r => r.backoff_db), 1), yd: span(E.flatMap(r => r.evm_db), 5), xl: T("回退 dB", "back-off, dB"), yl: "EVM dB" });
    let o = F.s;
    E.forEach(r => { const c = `var(--${r.waveform === "ay_sc" ? "sc" : "ofdm"})`, pts = r.backoff_db.map((b, i) => [F.x(b), F.y(r.evm_db[i])]).filter((p, i) => !nil(r.evm_db[i])); o += path(pts, c, r.tone_order > 16 ? 'stroke-dasharray="5 4" stroke-width="1.5"' : "") + `<path d="${pts.map((p, i) => (i ? "L" : "M") + P(p[0]) + " " + P(p[1])).join("")}" fill="none" stroke="transparent" stroke-width="12" data-tip="${esc(wfn(r.waveform) + " " + r.payload + " · " + mcs(r.mcs))}"/>`; });
    const pre = A.header.preset_backoff_db; if (!nil(pre)) o += ln(F.x(pre), F.top, F.x(pre), F.top + F.hh, "axis", 'stroke-dasharray="3 3"') + tx(F.x(pre) + 4, F.top + F.hh - 5, `${T("预设回退", "preset back-off")} ${fx(pre, 1)} dB`, { c: "q" });
    return `<div class="lg">${E.map(r => `<span><i class="${r.tone_order > 16 ? "dash" : ""}" style="border-color:var(--${r.waveform === "ay_sc" ? "sc" : "ofdm"})"></i>${wfn(r.waveform)} ${esc(r.payload)}</span>`).join("")}</div>` + svg(w, F.h, o, T("EVM 对回退", "EVM against back-off"));
  },
  /* the fastest MCS of each waveform at every output power */
  bestrate(w) {
    const B = S.rep.ay.report.best_rate_at_pout, A = S.rep.ay.report;
    const F = frame(w, { ml: 40, mr: 14, top: 8, h: 150, xd: span(B.map(r => r.backoff_db), 1), yd: [0, span(B.flatMap(r => [r.sc_rate_bps, r.ofdm_rate_bps]).map(v => (nil(v) ? null : v / 1e9)), 1, 0.3)[1]], xl: T("回退 dB", "back-off, dB"), yl: "Gb/s" });
    let o = F.s;
    const pre = A.header.preset_backoff_db; if (!nil(pre)) o += ln(F.x(pre), F.top, F.x(pre), F.top + F.hh, "axis", 'stroke-dasharray="3 3"') + tx(F.x(pre) + 4, F.top + F.hh - 5, `${T("预设回退", "preset back-off")} ${fx(pre, 1)} dB`, { c: "q" });
    [["ofdm", "var(--ofdm)", "OFDM"], ["sc", "var(--sc)", "SC"]].forEach(s => {
      const k = s[0] + "_rate_bps", rows = B.filter(r => !nil(r[k])), pts = []; rows.forEach((r, i) => { if (i) pts.push([F.x(r.backoff_db), F.y(rows[i - 1][k] / 1e9)]); pts.push([F.x(r.backoff_db), F.y(r[k] / 1e9)]); });
      o += path(pts, s[1]);
      rows.forEach(r => { o += dot(F.x(r.backoff_db), F.y(r[k] / 1e9), s[1], `${s[2]} @${fx(r.backoff_db, 1)} dB (Pout ${fx(r.pout_dbm, 1)} dBm): ${mcs(r[s[0] + "_mcs"])} ${gbps(r[k])} Gb/s`, 3); });
      const e = rows[rows.length - 1]; if (e) o += tx(F.x(e.backoff_db) - 4, F.y(e[k] / 1e9) + (s[0] === "sc" ? 14 : -7), `${s[2]} ${gbps(e[k])}`, { a: "end", c: "m k" });
    });
    return `<div class="lg"><span><i style="border-color:var(--sc)"></i>SC</span><span><i style="border-color:var(--ofdm)"></i>OFDM</span></div>` + svg(w, F.h, o, T("各输出功率上最快的一档", "fastest step at each output power"));
  },
  /* the dependency chains of the parts, coloured by what is stale now */
  deps(w) {
    if (!S.parts) return "";
    const ps = S.parts.parts, down = ps.filter(p => p.upstream.length), nar = w < 560, nh = 38, gap = nar ? 16 : 30, nw = nar ? w - 2 : (w - gap - 2) / 2; let o = "", yy = 1;
    const fit = (t, fs) => (tw(t, fs) > nw - 14 ? `textLength="${P(nw - 14)}" lengthAdjust="spacingAndGlyphs"` : "");
    const node = (x0, y0, id) => { const stl = pstate(id) === "stale", p = partInfo(id), sub = p.job ? jn(p.job) : T("存着的测量，这里不重算", "a stored measurement, not recomputed here");
      return `<g data-part="${esc(id)}" data-state="${pstate(id)}"><rect x="${P(x0)}" y="${P(y0)}" width="${P(nw)}" height="${nh}" rx="5" fill="${stl ? "var(--amber-bg)" : "var(--panel)"}" stroke="${stl ? "var(--amber-line)" : "var(--rule2)"}" ${p.job ? "" : 'stroke-dasharray="4 3"'}/><text x="${P(x0 + 7)}" y="${P(y0 + 15)}" class="k" ${fit(pn(id), 10.5)}>${esc(pn(id))}</text><text x="${P(x0 + 7)}" y="${P(y0 + 29)}" class="q" ${fit((stl ? "◷ " : "") + sub, 10.5)}>${stl ? `<tspan style="fill:var(--amber)">◷ ${T("过期", "stale")} · </tspan>` : ""}${esc(sub)}</text></g>`; };
    down.forEach(p => p.upstream.forEach(u => {
      const xa = 1, xb = nar ? 1 : 1 + nw + gap, yb = nar ? yy + nh + gap : yy; o += node(xa, yy, u) + node(xb, yb, p.id);
      o += nar ? ln(xa + nw / 2, yy + nh, xa + nw / 2, yy + nh + gap - 2, "axis") + arrowHead(xa + nw / 2, yy + nh + gap - 1, "d") : ln(xa + nw, yy + nh / 2, xa + nw + gap - 2, yy + nh / 2, "axis") + arrowHead(xa + nw + gap - 1, yy + nh / 2, "r");
      yy += nar ? 2 * nh + gap + 14 : nh + 10;
    }));
    return svg(w, yy, o, T("依赖链", "dependency chains"));
  },
};
function drawCharts(root = document) {
  root.querySelectorAll(".chartbox[data-chart]").forEach(el => {
    const w = Math.floor(el.clientWidth); if (w < 120 || !CHARTS[el.dataset.chart]) return;
    try { el.innerHTML = CHARTS[el.dataset.chart](w, el); } catch (e) { console.error("chart " + el.dataset.chart, e); el.textContent = ""; }
  });
}
