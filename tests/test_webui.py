"""The page (``src/mmw60/webui/www``): rules checked from its text (it speaks only routes the host
answers, it types no result number, it loads nothing from elsewhere), and the page in a real
Chromium against the real host on the shipped baseline — the form marks numbers stale instead of
clearing them, a job runs and its result is what the page then shows, the phone layout switches.
Assertions are on wiring and on numbers landing in the right cell, not on pixels.

Needs Playwright and a Chromium: the browser tests skip without them, except when
MMW60_REQUIRE_BROWSER=1 (CI's test-gui job), where the skip is a failure so a green run that tested
nothing cannot pass for one that did.
"""
from __future__ import annotations

import glob
import json
import os
import re
import threading

import pytest

from mmw60 import guistore
from mmw60 import guiutil as g
from mmw60.webhost import GET_ROUTES, POST_HEADER, POST_ROUTES, WWW, State, make_server

B32 = "be_upclocked 11ac 20M K=32 @60.48 GHz"
STALE_IN_TABLE = "document.querySelectorAll('#screen-table [data-state=\"stale\"]').length"
SOURCES = sorted(WWW.glob("*.js")) + sorted(WWW.glob("*.html"))


def _js() -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(WWW.glob("*.js")))


# ------------------------------------------------------------------ rules checked from the text
def test_the_page_speaks_only_routes_the_host_answers():
    """Every ``api("...")`` in the page is a route ``webhost`` serves, and POSTs carry the header
    the host demands."""
    js = _js()
    routes = set(re.findall(r'api\(\s*"([a-z_/]+)"', js))
    assert routes, "no api(\"route\") call found"
    served = set(GET_ROUTES) | set(POST_ROUTES) | {"jobs/", "results/"}        # the prefixes of the id routes
    assert routes <= served, routes - served
    assert {"state", "report", "run", "jobs", "system", "row"} <= routes
    assert POST_HEADER in js and "onHostReply" in js and "window.host.call(" in js
    assert not re.search(r"""fetch\(\s*["'`]/""", js), "absolute URL: a WebView has no server root"


def test_the_page_loads_nothing_from_elsewhere_and_names_no_model():
    for path in SOURCES + sorted(WWW.glob("*.css")):
        text = path.read_text(encoding="utf-8")
        urls = [u for u in re.findall(r"""https?://[^\s"'`)<>]+""", text) if "www.w3.org" not in u]
        assert not urls, (path.name, urls[:3])
        assert not re.search(r"@import|<link[^>]+href=[\"']https?:|<script[^>]+src=[\"'](https?:)?//", text), path.name
        names = r"\b(claude|anthropic|opus|sonnet|haiku|gpt|openai|gemini|copilot)\b"
        assert not re.search(names, text, re.I), path.name
        assert path.stat().st_size < 90_000, f"{path.name}: {path.stat().st_size} bytes (split it)"


#: digits a user-facing string may carry: names of standards, bands, modulations and symbols — never a result
_NAMES = re.compile(
    r"802\.11\w*|IEEE 802\.\d+\w*|FCC 15\.255|Wi-?Fi ?[67]|\b(sub-)?[67] ?GHz|\b60 ?GHz|\d+-?QAM|\b\d/\d\b|π/2|"
    r"\bx ?1\b|[×x] ?K\b|\bK ?= ?1\b|\bN ?= ?1\b|L-STF|L-LTF|[A-Za-z_]+\d+[a-z]?\b|\{\d+\}|%\d|\$\d|&#\d+;|\bH[1-6]\b")


def _strings(js: str) -> list[str]:
    """The string literals of the page's dictionaries and templates that hold words (a letter or a
    CJK character next to the digits), without code-like ones (selectors, paths, colours, ids)."""
    out = []
    for m in re.finditer(r'"((?:[^"\\\n]|\\.)*)"|\'((?:[^\'\\\n]|\\.)*)\'', js):
        s = m.group(1) if m.group(1) is not None else m.group(2)
        if re.search(r"\d", s) and re.search(r"[一-鿿]|[A-Za-z]{3,} [A-Za-z]{2,}", s):
            out.append(s)
    return out


def test_no_result_number_is_typed_into_the_page():
    """A sentence in the page that carries a number must have got it from a payload: after the names
    of standards and symbols are set aside, no user-facing string literal holds a digit.  (The
    mock-up's prose quoted "53.6 dB", "8 %", ranges in metres: copies that drift.)"""
    html = "\n".join(p.read_text(encoding="utf-8") for p in sorted(WWW.glob("*.html")))
    attrs = re.findall(r'data-(?:zh|en)="([^"]*)"', html)
    bad = [s for s in _strings(_js()) + attrs if re.search(r"\d", _NAMES.sub("", s))]
    assert not bad, bad[:8]


def test_bilingual_markup_is_paired_and_wraps_no_controls():
    """A [data-zh] element's content is replaced on every language switch: one that wraps another
    element would delete it (the pitfall array_tx's page met)."""
    html = (WWW / "index.html").read_text(encoding="utf-8")
    assert html.count("data-zh=") == html.count("data-en=") >= 10
    for m in re.finditer(r"<(\w+)([^>]*\bdata-zh=[^>]*)>(.*?)</\1>", html, flags=re.S):
        assert "<" not in m.group(3), f"data-zh element wraps markup: {m.group(0)[:80]}"


# ------------------------------------------------------------------ the page in a browser
def _browser():
    required = os.environ.get("MMW60_REQUIRE_BROWSER") == "1"
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        if required:
            raise
        pytest.skip("playwright not installed")
    pw = sync_playwright().start()
    # MMW60_CHROMIUM, else Playwright's own download, else any Chromium under PLAYWRIGHT_BROWSERS_PATH
    exes = [os.environ.get("MMW60_CHROMIUM"), None] + sorted(glob.glob(
        os.path.join(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""), "chromium-*", "chrome-linux*", "chrome")))
    last = None
    for exe in exes:
        if exe == "" or (exe is None and exes[0]):
            continue
        try:
            return pw, (pw.chromium.launch(executable_path=exe, args=["--no-sandbox"]) if exe
                        else pw.chromium.launch(args=["--no-sandbox"]))
        except Exception as exc:                # noqa: BLE001 (try the next one)
            last = exc
    pw.stop()
    if required:
        raise RuntimeError(f"no Chromium: {last}")
    pytest.skip(f"no Chromium: {last}")


@pytest.fixture(scope="module")
def browser():
    pw, b = _browser()
    yield b
    b.close()
    pw.stop()


def _canned_runner(job, st, params, emit, cancelled=None):
    """The queue's job for the page tests: the shipped result of that job re-labelled for the study
    (the page is tested on what it does with a result; the real jobs run in ``test_webhost``).
    ``calibration_be`` waits to be let through so the page can be seen while it runs."""
    import time
    base = guistore.load_baseline()[job if job != "table_analytic" else "table"]
    for i in range(3):
        emit("progress", [i + 1, 3, f"step {i + 1}"])
        time.sleep(0.3)
        if cancelled is not None and cancelled():
            emit("cancelled", None)
            return
    cal = params.get("calibration")
    report = base["report"]
    if job == "table_analytic":                 # what an analytic-only run returns: no time-domain column, no ay rows
        td = g.BE_FIELDS["table.td"]
        report = dict(report, time_domain=False, ay_rows=[], lo_models=None,
                      rows=[{k: (None if k in td else v) for k, v in r.items()} for r in report["rows"]])
    out = g.job_result(job, st, report, seconds=0.9,
                       built_on={"calibration.be": cal["study"]} if cal else None)
    out["quick"] = False
    emit("done", out)


@pytest.fixture()
def host():
    """A fresh host per test on the shipped baseline, results in memory, jobs on threads."""
    state = State(backend="thread", store=guistore.Store(None), runner=_canned_runner)
    srv = make_server(0, state=state)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/", state
    srv.shutdown()
    srv.server_close()


def _open(browser, url, width=1440, height=900):
    page = browser.new_page(viewport={"width": width, "height": height})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("requestfailed", lambda r: errors.append(f"request failed: {r.url}"))
    page.goto(url)
    page.wait_for_selector(f'#screen-table [data-label="{B32}"]', timeout=30000)
    return page, errors


def _row(page, label):
    return page.text_content(f'#screen-table [data-label="{label}"]')


def test_the_page_opens_on_the_shipped_table_with_the_engine_line(host, browser):
    url, _ = host
    page, errors = _open(browser, url)
    table = guistore.load_baseline()["table"]["report"]
    labels = page.evaluate("[...document.querySelectorAll('#screen-table [data-label]')].map(e => e.dataset.label)")
    assert set(labels) >= {r["label"] for r in table["rows"] + table["ay_rows"]}
    # the numbers in the row are that row's, rounded once to the report's decimals
    r = next(x for x in table["rows"] if x["label"] == B32)
    d = table["display"]
    text = _row(page, B32)
    assert f"{r['rate_mbps']:.{d['rate_mbps']}f}" in text.replace(",", "").replace(" ", "").replace(" ", "")
    assert f"MCS{r['max_mcs']}" in text or f"MCS {r['max_mcs']}" in text
    other = next(x for x in table["rows"] if x["label"].startswith("be 11be 80M K=1 "))
    assert f"{other['rate_mbps']:.0f}" not in text.replace(",", "") or other["rate_mbps"] == r["rate_mbps"]
    assert "not endorsed" in page.text_content("body") or "不能背书" in page.text_content("body") \
        or "不背书" in page.text_content("body")
    assert page.evaluate(STALE_IN_TABLE) == 0
    assert not errors, errors
    page.close()


def test_editing_the_form_marks_numbers_stale_and_keeps_them_and_reset_restores(host, browser):
    url, state = host
    page, errors = _open(browser, url)
    before = _row(page, B32)
    knob = page.locator('[data-knob="frontend.pa.obo_db"]').first
    if not knob.is_visible():                       # the form may live in a drawer
        page.click("#nav-form")
    knob.fill("9.5")
    knob.press("Tab")
    page.wait_for_function(STALE_IN_TABLE + " > 0", timeout=15000)
    assert state.study == {"frontend.pa.obo_db": 9.5}             # the host was told: the page did not keep it
    if not page.locator(f'#screen-table [data-label="{B32}"]').first.is_visible():
        page.click("#nav-table")
    assert "MCS" in _row(page, B32)                                # the numbers are still there
    for part in ("table.analytic", "table.td", "calibration.be", "array"):
        assert page.evaluate(f"!!document.querySelector('[data-part=\"{part}\"][data-state=\"stale\"]')"), part
    assert page.evaluate("!!document.querySelector('[data-part=\"thresholds.be\"][data-state=\"fresh\"]')")
    body = page.text_content("body")
    assert "frontend.pa.obo_db" in body or "回退" in body
    assert "assumed" in page.text_content('[data-knob-row="frontend.pa.obo_db"]')
    # reset: fresh again, the same row text as before the edit
    page.click("#form-reset")
    page.wait_for_function(STALE_IN_TABLE + " === 0", timeout=15000)
    assert state.study == {} and _row(page, B32) == before
    assert not errors, errors
    page.close()


def test_a_job_runs_from_the_page_and_its_result_is_what_the_page_then_shows(host, browser):
    url, state = host
    state.study = {"frontend.pa.obo_db": 9.5}
    page, errors = _open(browser, url)
    page.click("#nav-runs")
    page.click('#screen-runs [data-job="calibration_be"]')
    page.wait_for_function("document.querySelectorAll('#screen-runs [data-job-id]').length >= 1", timeout=15000)
    page.wait_for_function(
        "!!document.querySelector('[data-part=\"calibration.be\"][data-state=\"fresh\"]')", timeout=30000)
    done = [j for j in state.jobs.listing() if j["status"] == "done"]
    assert len(done) == 1 and done[0]["job"] == "calibration_be" and done[0]["study"] == state.study
    assert state.store.pick("calibration", state.study)["id"] == done[0]["result_id"]
    # the table was not recomputed: still stale, and it says its calibration is not the one it was built on
    assert page.evaluate("!!document.querySelector('[data-part=\"table.analytic\"][data-state=\"stale\"]')")
    # now the table: it builds on that calibration and reads fresh for its own knobs
    page.click('#screen-runs [data-job="table"]')
    page.wait_for_function("!!document.querySelector('[data-part=\"table.td\"][data-state=\"fresh\"]')", timeout=30000)
    tab = state.store.pick("table", state.study)["result"]
    assert tab["built_on"] == {"calibration.be": state.study}
    assert g.freshness(state.study, state.store.envelopes(state.study))["table.analytic"]["state"] == "fresh"
    assert not errors, errors
    page.close()


def test_every_screen_draws_from_the_baseline_without_errors(host, browser):
    url, _ = host
    page, errors = _open(browser, url)
    base = guistore.load_baseline()
    for name in ("system", "table", "calibration", "array", "ay", "runs", "sources"):
        page.click(f"#nav-{name}")
        page.wait_for_function(f"getComputedStyle(document.getElementById('screen-{name}')).display !== 'none'")
        page.wait_for_function(f"document.getElementById('screen-{name}').textContent.trim().length > 200",
                               timeout=20000)
    # a number of each report lands on its screen
    cal = base["calibration_be"]["report"]
    page.click("#nav-calibration")
    assert f"{cal['irr_after_cal_db']['20000000.0']:.1f}" in page.text_content("#screen-calibration")
    assert "degraded" in page.text_content("#screen-calibration") or "降级" in page.text_content("#screen-calibration")
    head = g.sc_vs_ofdm_headline(base["array"]["report"])
    page.click("#nav-ay")
    assert f"{head['same_modulation_16qam_3_4']['sc_advantage_pct']:.0f}" in page.text_content("#screen-ay")
    page.click("#nav-array")
    assert str(base["array"]["report"]["eirp_limit"]["binds_from_n"]) in page.text_content("#screen-array")
    # a row opens to its detail with its config hash
    page.click("#nav-table")
    page.click(f'#screen-table [data-label="{B32}"]')
    sha = next(r["cfg_sha"] for r in base["table"]["report"]["rows"] if r["label"] == B32)
    page.wait_for_function(f"document.body.textContent.includes('{sha[:12]}')", timeout=15000)
    assert not errors, errors
    page.close()


def test_phone_width_has_bottom_navigation_and_no_sideways_scroll(host, browser):
    url, _ = host
    page = browser.new_page(viewport={"width": 400, "height": 860})
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(url)
    page.wait_for_selector(f'#screen-table [data-label="{B32}"]', state="attached", timeout=30000)
    assert page.evaluate("getComputedStyle(document.getElementById('bottom-nav')).display") != "none"
    for name in ("table", "array", "runs"):
        page.click(f'#bottom-nav [data-nav="{name}"]')
        page.wait_for_function(f"getComputedStyle(document.getElementById('screen-{name}')).display !== 'none'")
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), name
    assert not errors, errors
    page.close()


def test_language_toggle_switches_the_words_not_the_numbers(host, browser):
    url, _ = host
    page, errors = _open(browser, url)
    zh = _row(page, B32)
    page.click("#lang-toggle")
    page.wait_for_function("document.documentElement.lang.startsWith('en')")
    en = _row(page, B32)
    assert re.findall(r"-?\d+(?:\.\d+)?", zh) == re.findall(r"-?\d+(?:\.\d+)?", en)
    assert json.dumps(page.text_content("#nav-table")) != json.dumps("")
    assert not errors, errors
    page.close()


def test_with_nothing_stored_the_page_says_missing_and_offers_the_jobs(browser):
    """No baseline, no results: no part reads fresh on the strength of numbers the page cannot show."""
    state = State(backend="thread", store=guistore.Store(None, {}), runner=_canned_runner)
    srv = make_server(0, state=state)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{srv.server_address[1]}/")
        page.wait_for_selector('#screen-table [data-empty="table"]', timeout=30000)
        for part in ("table.analytic", "calibration.be", "array", "ay"):
            assert page.evaluate(f"!!document.querySelector('[data-part=\"{part}\"][data-state=\"missing\"]')"), part
        assert page.evaluate("!!document.querySelector('[data-part=\"thresholds.be\"][data-state=\"fresh\"]')")
        assert page.evaluate("document.querySelectorAll('#screen-table [data-label]').length") == 0
        # the job it offers fills the screen
        page.click('#screen-table [data-job="table"]')
        page.wait_for_selector(f'#screen-table [data-label="{B32}"]', timeout=30000)
        assert page.evaluate("!!document.querySelector('[data-part=\"table.td\"][data-state=\"fresh\"]')")
        assert not errors, errors
        page.close()
    finally:
        srv.shutdown()
        srv.server_close()


def test_the_data_the_page_lacked_is_drawn_from_the_payloads(host, browser):
    """Which guesses decide, each term's share of the floor, the rows that cannot carry data, and SC
    against OFDM item by item: computed in the compute layer, drawn here, each in its own cell."""
    url, _ = host
    page, errors = _open(browser, url)
    base = guistore.load_baseline()
    table = base["table"]["report"]
    # 1. the sensitivity section: one line per knob end, with the count of rows whose caps moved
    sens = table["sensitivity"]
    page.wait_for_selector("#sens [data-sens-knob]", state="attached", timeout=15000)
    assert page.evaluate("document.querySelectorAll('#sens [data-sens-knob]').length") == len(sens["knobs"]) == 13
    k = next(x for x in sens["knobs"] if x["knob"] == "PA back-off" and x["value_text"] == "-2")
    line = page.text_content(f'#sens [data-sens-knob="{k["knob"]}|{k["value_text"]}"]')
    assert str(len(k["mcs_moved"])) in line and str(len(k["dec_mcs_moved"])) in line
    assert f"{k['pj_ratio_max']:.{table['display']['pj_ratio']}f}" in line
    # 2. a row that cannot carry data is marked, keeps its numbers and comes after every usable row
    #    — on the column on show: calibrated (the default) or raw.  The 2.56 GHz row cannot carry data raw
    #    (its IQ image blocks every MCS) and is the fastest row once calibrated
    def marked():
        order = page.evaluate("[...document.querySelectorAll('#screen-table [data-label]')]"
                              ".map(e => [e.dataset.label, e.dataset.usable || 'true'])")
        flags = [u for _, u in order]
        assert flags == sorted(flags, reverse=True), "an unusable row is ranked among the usable ones"
        return {lab for lab, u in order if u == "false"}
    assert marked() == {r["label"] for r in table["rows"] if not r["usable_cal"]} and len(marked()) == 1
    page.click('#screen-table [data-col="raw"]')
    assert marked() == {r["label"] for r in table["rows"] if not r["usable"]} and len(marked()) == 2
    page.click('#screen-table [data-col="cal"]')
    assert len(marked()) == 1
    # 3. the row detail: each term's share of the floor
    r = next(x for x in table["rows"] if x["label"] == B32)
    page.click(f'#screen-table [data-label="{B32}"]')
    page.wait_for_selector('[data-term="iq_image"] [data-share]', timeout=15000)
    d = table["display"]["terms_share_pct"]
    for term, share in r["terms_share"].items():
        if share is not None:
            assert f"{100 * share:.{d}f}" in page.text_content(f'[data-term="{term}"]'), term
    assert f"{r['power_dec_cal']['pj_per_bit']:.0f}" in page.text_content("#screen-row")
    # 4. SC against OFDM, item by item
    items = g.sc_vs_ofdm_items(table, base["array"]["report"], base["ay"]["report"])
    page.click("#nav-ay")
    page.wait_for_selector("#items [data-item]", timeout=15000)
    assert page.evaluate("document.querySelectorAll('#items [data-item]').length") == len(items) == 15
    for it in items:
        row = page.locator(f'#items [data-item="{it["id"]}"]')
        assert row.get_attribute("data-winner") == it["winner"], it["id"]
        assert f"{abs(it['sc_over_ofdm_pct']):.1f}" in row.text_content(), it["id"]
    assert not errors, errors
    page.close()


def test_the_lo_models_the_ay_caps_and_the_preview_that_hides_nothing(host, browser):
    url, state = host
    page, errors = _open(browser, url)
    table = guistore.load_baseline()["table"]["report"]
    d = table["display"]
    # 1. the LO models side by side: one cell group per (model, K), with that row's numbers
    lo = table["lo_models"]["rows"]
    page.wait_for_selector("#lo-models [data-lo-model]", state="attached", timeout=15000)
    assert page.evaluate("document.querySelectorAll('#lo-models [data-lo-model][data-k]').length") == len(lo) == 18
    for r in (lo[2], lo[5], lo[-1]):
        text = page.text_content(f'#lo-models [data-lo-model="{r["model"]}"][data-k="{r["k"]}"]')
        for key in ("ipn_dbc", "pn_ici_db", "floor_db", "td_evm_db"):
            assert f"{abs(r[key]):.{d[key]}f}" in text, (r["model"], r["k"], key)
        assert f"MCS{r['max_mcs']}" in text.replace("MCS ", "MCS")
    # 2. an 802.11ay row opens to its own decoder cap
    ay = next(r for r in table["ay_rows"] if r["waveform"] == "ay_sc")
    page.click(f'#screen-table [data-label="{ay["label"]}"]')
    page.wait_for_function(f"document.getElementById('screen-row').textContent.includes('{ay['cfg_sha'][:12]}')")
    detail = page.text_content("#screen-row").replace("MCS ", "MCS")
    assert f"MCS{ay['dec_mcs_cal']}" in detail and f"{ay['power_dec_cal']['pj_per_bit']:.0f}" in detail
    # 3. the preview: an analytic-only run for an edited form sits beside the full table
    page.click("#nav-form") if not page.locator('[data-knob="frontend.pa.obo_db"]').first.is_visible() else None
    knob = page.locator('[data-knob="frontend.pa.obo_db"]').first
    knob.fill("9.5")
    knob.press("Tab")
    page.wait_for_function("!!document.querySelector('[data-part=\"table.analytic\"][data-state=\"stale\"]')")
    page.click("#nav-runs")
    page.click('#screen-runs [data-job="table_analytic"]')
    # the analytic columns are the new run's (their field group is fresh); the part itself stays stale,
    # because the calibration it leans on was not rerun for the edited back-off
    page.wait_for_function("!!document.querySelector('[data-field-group=\"table.analytic\"][data-state=\"fresh\"]')",
                           timeout=30000)
    part = "#screen-runs [data-part=\"table.analytic\"]"
    assert page.evaluate(f"!!document.querySelector('{part}[data-state=\"stale\"]')")
    assert not page.evaluate(f"!!document.querySelector('{part}[data-state=\"fresh\"]')")
    parts = state.store.table_parts(state.study)
    assert parts["table.analytic"]["result"]["job"] == "table_analytic"
    assert parts["table.td"]["id"] == parts["table.ay"]["id"] == "baseline-table"
    page.click("#nav-table")
    page.wait_for_selector('#screen-table [data-part-result="table.analytic"]', timeout=15000)
    ids = {p: page.get_attribute(f'#screen-table [data-part-result="{p}"]', "data-result-id")
           for p in guistore.TABLE_PARTS}
    assert ids == {p: e["id"] for p, e in parts.items()}
    labels = page.evaluate("[...document.querySelectorAll('#screen-table [data-label]')].map(e => e.dataset.label)")
    assert {r["label"] for r in table["rows"] + table["ay_rows"]} <= set(labels)      # nothing vanished
    r32 = next(r for r in table["rows"] if r["label"] == B32)
    assert f"{r32['td_evm_db']:.{d['td_evm_db']}f}".lstrip("-") in _row(page, B32)   # the full run's column, kept
    for part in ("table.td", "table.ay"):
        assert page.evaluate(f"!!document.querySelector('[data-part=\"{part}\"][data-state=\"stale\"]')"), part
    assert page.evaluate("!!document.getElementById('assembled-note')")
    assert not errors, errors
    page.close()
