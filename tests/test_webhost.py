"""The host of the page (``mmw60.webhost``): the queue on both backends, the JSON API as the page
and the phone bridge call it, and the HTTP transport.  The jobs here are stand-ins (a queue is
tested on what it does with a job, not on the job); the real ones run in the slow tests."""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request

import pytest

from mmw60 import appbridge, guistore
from mmw60 import guiutil as g
from mmw60.webhost import GET_ROUTES, POST_HEADER, POST_ROUTES, Api, JobQueue, State, dumps, make_server

OBO = {"frontend.pa.obo_db": 9.5}


def canned(job: str, st: dict, quick: bool = False) -> dict:
    """A job result with a report small enough to read: what ``run_job`` returns, minus the run."""
    report = {"kind": g.JOBS[job]["report"], "study": g.study(st), "rows": [], "ay_rows": [], "columns": [],
              "irr_after_cal_db": {"20000000.0": 50.0}}
    out = g.job_result(job, st, report, seconds=0.01)
    out["quick"] = quick
    return out


def fake_runner(job, st, params, emit, cancelled=None):
    """Three progress steps, then a canned result.  ``params['hold']`` keeps it running until
    cancelled (thread backend) or terminated (process backend); ``params['boom']`` raises."""
    for i in range(3):
        emit("progress", [i + 1, 3, f"step {i + 1}"])
        if cancelled is not None and cancelled():
            emit("cancelled", None)
            return
    if params.get("boom"):
        emit("error", "Traceback: boom")
        return
    t0 = time.time()
    while params.get("hold") and time.time() - t0 < 30:
        if cancelled is not None and cancelled():
            emit("cancelled", None)
            return
        time.sleep(0.02)
    emit("done", canned(job, st))


def wait(pred, timeout=20.0):
    t0 = time.time()
    while time.time() - t0 < timeout:
        v = pred()
        if v:
            return v
        time.sleep(0.02)
    raise AssertionError("timed out")


def state(backend="thread", baseline=None, home=None):
    return State(backend=backend, store=guistore.Store(home, baseline if baseline is not None else {}),
                 runner=fake_runner)


# ------------------------------------------------------------------ the queue
@pytest.mark.parametrize("backend", ["thread", "process"])
def test_a_job_runs_reports_progress_and_its_result_is_stored_before_it_reads_done(backend):
    st = state(backend)
    job = st.jobs.submit("calibration_be", OBO)
    assert job["status"] == "queued" and job["study"] == OBO and job["parts"] == ["calibration.be"]
    assert job["expected_seconds"] == g.JOBS["calibration_be"]["seconds"] and "_params" not in job
    done = wait(lambda: (j := st.jobs.get(job["id"]))["status"] == "done" and j)
    assert done["progress"] == [3, 3] and done["text"] == "step 3" and done["finished"] >= done["started"]
    entry = st.store.get(done["result_id"])
    assert entry["origin"] == "user" and entry["result"]["study"] == OBO
    assert not st.jobs.busy()


@pytest.mark.parametrize("backend", ["thread", "process"])
def test_cancel_stops_a_running_job_and_a_queued_one_never_starts(backend):
    st = state(backend)
    a = st.jobs.submit("array", {}, {"hold": True})
    b = st.jobs.submit("ay", {})                                   # one worker: waits behind a
    wait(lambda: st.jobs.get(a["id"])["progress"][0] == 3)
    assert st.jobs.get(b["id"])["status"] == "queued" and st.jobs.busy()
    assert st.jobs.cancel(b["id"]) and st.jobs.get(b["id"])["status"] == "cancelled"
    assert st.jobs.cancel(a["id"])
    wait(lambda: st.jobs.get(a["id"])["status"] == "cancelled")
    assert st.jobs.get(a["id"])["result_id"] is None and st.store.entries() == []
    assert not st.jobs.cancel(a["id"]) and not st.jobs.cancel("99")     # finished / unknown: not cancellable


def test_a_failing_job_reads_error_with_its_traceback_and_stores_nothing():
    st = state()
    job = st.jobs.submit("table", {}, {"boom": True})
    done = wait(lambda: (j := st.jobs.get(job["id"]))["status"] == "error" and j)
    assert "boom" in done["error"] and st.store.entries() == []
    with pytest.raises(KeyError):
        st.jobs.submit("no_such_job", {})
    with pytest.raises(ValueError):
        JobQueue(backend="fork")


def test_a_worker_that_dies_is_an_error_not_a_hang():
    st = State(backend="process", store=guistore.Store(None, {}), runner=_dies)
    job = st.jobs.submit("table", {})
    done = wait(lambda: (j := st.jobs.get(job["id"]))["status"] == "error" and j)
    assert "exited with code" in done["error"]


def _dies(job, st, params, emit, cancelled=None):
    import os
    os._exit(3)


# ------------------------------------------------------------------ the API
def test_state_is_the_form_the_freshness_and_what_is_shown():
    base = {"table": canned("table", {}), "calibration_be": canned("calibration_be", {})}
    api = Api(state(baseline=base))
    code, s = api.call("state", {"study": {}})
    assert code == 200 and s["ok"] and s["study"] == {}
    assert len(s["form"]["knobs"]) == len(g.ROW_KNOBS) + len(g.SHARED_KNOBS)
    # the host draws what its store holds: a part nothing is stored for reads missing, not fresh
    states = {p: v["state"] for p, v in s["freshness"]["parts"].items()}
    assert states == {**dict.fromkeys(g.PARTS, "fresh"), "array": "missing", "ay": "missing"}
    assert s["freshness"]["parts"]["array"]["recompute"] == "array"
    assert s["shown"]["table"]["id"] == "baseline-table" and s["shown"]["array"] is None
    assert s["shown"]["table"]["provenance"]["engine"] and "report" not in s["shown"]["table"]
    # the form moves: nothing is cleared, the parts that read the knob go stale and say which knob
    code, s = api.call("state", {"study": OBO})
    f = s["freshness"]["parts"]
    assert f["calibration.be"]["state"] == "stale" and f["calibration.be"]["changed"] == ["frontend.pa.obo_db"]
    assert f["thresholds.be"]["state"] == "fresh" and s["shown"]["table"]["id"] == "baseline-table"
    assert s["freshness"]["fields"]["table.analytic"] == "stale"
    # the host remembers the last form it was sent (a reloaded page finds it again)
    assert api.call("state", {})[1]["study"] == OBO
    assert api.call("state", {"study": {"frontend.pa.obo_db": 99}})[0] == 400
    assert api.call("state", {})[1]["study"] == OBO


def test_report_serves_the_stored_result_with_its_freshness_and_never_computes():
    base = {"table": canned("table", {})}
    api = Api(state(baseline=base))
    code, r = api.call("report", {"report": "table", "study": OBO})
    assert code == 200 and r["report"]["kind"] == "table" and r["result"]["id"] == "baseline-table"
    assert r["freshness"]["parts"]["table.td"]["state"] == "stale" and r["ranges"] is None
    assert r["jobs"] == ["table"]                                   # the jobs a host queues: the full ones
    code, r = api.call("report", {"report": "array", "study": {}})
    assert code == 200 and r["report"] is None and r["result"] is None and r["jobs"] == ["array"]
    # the SC-against-OFDM report comes with what is computed across results: the headline and the
    # item table, each naming the results it was computed from (none of the array's here)
    api.state.store.add(canned("ay", {}))
    code, r = api.call("report", {"report": "ay", "study": {}})
    assert code == 200 and r["headline"] is None and r["items"] == []
    assert r["items_results"]["array"] is None and r["items_results"]["table"]["id"] == "baseline-table"
    assert api.call("report", {"report": "everything"})[0] == 400
    assert api.state.jobs.listing() == []                         # asking for a report queued nothing


def test_run_queues_a_job_and_a_table_is_built_on_this_studys_calibration_when_there_is_one():
    st = state()
    api = Api(st)
    code, r = api.call("run", {"job": "table", "study": OBO})
    assert code == 200 and r["job"]["job"] == "table"
    wait(lambda: not st.jobs.busy())
    assert st.jobs.jobs[r["job"]["id"]]["_params"] == {}        # no calibration for this study: the accepted IRR
    # what a job builds on is decided when it starts: a table queued right behind the calibration builds on it
    api.call("run", {"job": "calibration_be", "study": OBO})
    code, r = api.call("run", {"job": "table", "study": OBO})
    wait(lambda: not st.jobs.busy())
    assert st.jobs.jobs[r["job"]["id"]]["_params"]["calibration"]["study"] == OBO
    # a calibration computed for another back-off is not this study's
    code, r = api.call("run", {"job": "table", "study": {"frontend.pa.obo_db": 10.0}})
    wait(lambda: not st.jobs.busy())
    assert st.jobs.jobs[r["job"]["id"]]["_params"] == {}
    assert api.call("run", {"job": "thresholds", "study": {}})[0] == 400
    assert api.call("run", {"job": "table_analytic", "study": {}})[0] == 400     # a command-line job, not a host's
    code, jobs = api.call("jobs")
    assert [j["status"] for j in jobs["jobs"]] == ["done"] * 4
    code, one = api.call("jobs/1")
    assert one["job"]["result_id"] and api.call("jobs/77")[0] == 404
    code, res = api.call("results")
    assert {x["job"] for x in res["results"]} == {"table", "calibration_be"}
    rid = next(x["id"] for x in res["results"] if x["job"] == "calibration_be")
    assert api.call(f"results/{rid}/delete", {})[1]["ok"] and not api.call(f"results/{rid}/delete", {})[1]["ok"]


def test_the_cheap_routes_answer_and_unknown_routes_are_404():
    api = Api(state())
    code, v = api.call("version")
    assert v["backend"] == "thread" and v["provenance"]["spec_digest"] == g.spec_digest() and v["results_dir"] is None
    code, p = api.call("parts")
    assert {x["id"] for x in p["parts"]} == set(g.PARTS) and p["stored"]
    assert set(p["jobs"]) == set(guistore.BASELINE_JOBS) == set(g.JOBS) - {"table_analytic"}
    code, s = api.call("sources")
    assert sum(s["counts"].values()) == len(s["sources"])
    code, y = api.call("system", {"study": OBO})
    assert code == 200 and y["kind"] == "system" and y["study"] == OBO
    assert api.call("nope")[0] == 404 and api.call("jobs/1/cancel", {})[1]["ok"] is False
    assert api.call("row", {"label": "x", "study": {}})[0] == 400          # no table stored
    for route in GET_ROUTES + POST_ROUTES:
        json.loads(dumps(api.call(route, {"study": {}, "report": "table", "label": "x", "job": "ay"})[1]))


# ------------------------------------------------------------------ the HTTP transport
@pytest.fixture()
def server():
    srv = make_server(0, state=state(baseline={"table": canned("table", {})}))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()


def _http(url, body=None, headers=None):
    req = urllib.request.Request(url, None if body is None else json.dumps(body).encode(), headers or {})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def test_http_serves_the_api_and_a_post_needs_the_header(server):
    code, body, hdr = _http(server + "/api/version")
    assert code == 200 and json.loads(body)["library"] == "mmw60_trx" and hdr["Cache-Control"] == "no-store"
    code, body, _ = _http(server + "/api/state", {"study": {}})
    assert code == 403 and POST_HEADER in json.loads(body)["error"]
    code, body, _ = _http(server + "/api/state", {"study": {}}, {POST_HEADER: "1"})
    assert code == 200 and json.loads(body)["shown"]["table"]["id"] == "baseline-table"
    assert _http(server + "/api/state")[0] == 404                                   # a GET cannot reach a POST route
    assert _http(server + "/api/jobs", {}, {POST_HEADER: "1"})[0] == 405
    assert _http(server + "/api/nope")[0] == 404
    req = urllib.request.Request(server + "/api/state", b"[1]", {POST_HEADER: "1"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req, timeout=10)
    assert e.value.code == 400


def test_http_serves_the_page_and_nothing_outside_its_directory(server):
    code, body, hdr = _http(server + "/")
    assert code == 200 and b"<html" in body.lower() and "text/html" in hdr["Content-Type"]
    assert _http(server + "/app.js")[0] == 200
    assert _http(server + "/../webhost.py")[0] == 404 and _http(server + "/%2e%2e/webhost.py")[0] == 404
    assert _http(server + "/no-such-file.js")[0] == 404


# ------------------------------------------------------------------ the phone bridge: same dispatch, another transport
def test_appbridge_is_the_same_api_on_threads_and_never_raises(monkeypatch, tmp_path):
    monkeypatch.setenv("MMW60_HOME", str(tmp_path))
    appbridge.reset()
    try:
        v = json.loads(appbridge.call("version"))
        assert v["ok"] and v["backend"] == "thread" and v["workers"] == 1
        assert v["results_dir"] == str(tmp_path / "results")
        s = json.loads(appbridge.call("state", json.dumps({"study": OBO})))
        assert s["study"] == OBO and s["freshness"]["parts"]["array"]["state"] == "stale"
        assert json.loads(appbridge.call("parts"))["ok"]
        for bad in (("state", "not json"), ("state", "[1]"), ("nope", "{}"), ("run", '{"job": "x"}')):
            out = json.loads(appbridge.call(*bad))
            assert out["ok"] is False and out["error"]
    finally:
        appbridge.reset()


# ------------------------------------------------------------------ a real job through the real runner
@pytest.mark.parametrize("backend", ["process", "thread"])
def test_a_real_calibration_runs_through_the_queue_and_a_table_then_builds_on_it(backend):
    """The stand-ins above are a queue's view of a job; this is the job: wifitrx's sequence (smoke
    size) in a spawned child or on a thread, stored, then an analytic table for the same study that
    takes its IRR from that result and says so."""
    st = State(backend=backend, store=guistore.Store(None, {}))
    cal = st.jobs.submit("calibration_be", OBO, {"quick": True})
    done = wait(lambda: (j := st.jobs.get(cal["id"]))["status"] in ("done", "error") and j, timeout=180)
    assert done["status"] == "done", done["error"]
    assert done["progress"][0] == done["progress"][1] > 12 and done["text"].endswith("final_loopback_evm")
    res = st.store.get(done["result_id"])["result"]
    assert res["quick"] and res["report"]["kind"] == "calibration" and res["provenance"]["engine"]
    assert [c["cells"] for c in res["report"]["steps"]] and res["report"]["irr_after_cal_db"]
    # a smoke-size result is stored but never shown, and a table does not build on it
    assert st.store.pick("calibration", OBO) is None
    full = dict(res, quick=False)
    st.store.add(full)
    tab = st.jobs.submit("table_analytic", OBO, {"quick": True})    # the queue itself hands it the calibration
    done = wait(lambda: (j := st.jobs.get(tab["id"]))["status"] in ("done", "error") and j, timeout=180)
    assert done["status"] == "done", done["error"]
    out = st.store.get(done["result_id"])["result"]
    assert out["parts"] == ["table.analytic"] and out["built_on"] == {}      # a smoke run builds on nothing
