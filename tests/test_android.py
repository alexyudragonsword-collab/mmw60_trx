"""The phone app, as far as text and a laptop can tell.

The shell (``android/``) is checked from its files: no permission, the activity calls the bridge
that exists and starts Python with the environment the library reads, Gradle bundles the page that
the desktop serves and installs the stack ``android/phone-stack.txt`` names, the workflow builds
with the same Python and asserts the number of on-device tests that exist.  What the device itself
must say (``appbridge.self_check``) runs here too, on this machine's numpy / scipy; CI runs it on
the app's (job ``test-phone-stack``) and on an emulator (``.github/workflows/android.yml``).
"""
import json
import re
from pathlib import Path

import pytest

import mmw60
from mmw60 import appbridge, guistore
from mmw60 import guiutil as g
from mmw60.webhost import WWW

ROOT = Path(__file__).resolve().parent.parent
ANDROID = ROOT / "android"
PKG = "android/app/src/main/java/com/mmw60/app"


def _text(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def _code(text: str, comment: str = "//") -> str:
    """The lines that do something: comments dropped (whole-line ones, KDoc bodies, and trailing ones
    after whitespace -- not the ``//`` of a URL), so a rule cannot be satisfied by a sentence."""
    out = []
    for line in text.splitlines():
        if line.lstrip().startswith((comment, "/*", "*")):
            continue
        out.append(re.split(rf"\s{re.escape(comment)}", line, maxsplit=1)[0])
    return "\n".join(out)


def test_manifest_asks_for_no_permission():
    m = _text("android/app/src/main/AndroidManifest.xml")
    body = re.sub(r"<!--.*?-->", "", m, flags=re.S)
    assert "<uses-permission" not in body and "permission" not in body.lower()
    assert 'android:name=".MainActivity"' in body
    # the theme is the app's own: light below API 29, the system's day / night from there on
    assert 'android:theme="@style/AppTheme"' in body
    day = _text("android/app/src/main/res/values/styles.xml")
    night = _text("android/app/src/main/res/values-v29/styles.xml")
    assert 'name="AppTheme" parent="android:Theme.Material.Light.NoActionBar"' in day
    assert 'name="AppTheme" parent="android:Theme.DeviceDefault.DayNight"' in night
    # a rotation is handled in place (the page is kept); a change of the system's dark mode is not,
    # so the activity is rebuilt and reads the theme again
    changes = re.search(r'android:configChanges="([^"]+)"', body).group(1).split("|")
    assert "orientation" in changes and "screenSize" in changes and "uiMode" not in changes
    for density in ("mdpi", "hdpi", "xhdpi", "xxhdpi", "xxxhdpi"):
        assert (ANDROID / f"app/src/main/res/mipmap-{density}/ic_launcher.png").is_file()


def test_activity_calls_the_bridge_that_exists_with_the_environment_the_library_reads():
    kt = _code(_text(f"{PKG}/MainActivity.kt"))
    assert 'getModule("mmw60.appbridge")' in kt and 'callAttr("call", route, argsJson)' in kt
    assert callable(appbridge.call) and callable(appbridge.self_check)
    assert 'addJavascriptInterface(HostBridge(), "host")' in kt and "window.onHostReply(" in kt
    assert 'loadUrl("file:///android_asset/www/index.html")' in kt and (WWW / "index.html").is_file()
    # the environment is set before the interpreter starts, in the one function both the activity
    # and the on-device tests go through
    start = kt.index("Python.start(AndroidPlatform(context))")
    for var in ("MMW60_HOME", "XDG_CACHE_HOME", "MMW60_NO_JIT"):
        assert 0 < kt.index(f'Os.setenv("{var}"') < start, var
    assert kt.count("Python.start(") == 1 and "startPython(this)" in kt
    test = _code(_text("android/app/src/androidTest/java/com/mmw60/app/OnDeviceTest.kt"))
    assert "MainActivity.startPython(" in test and "Python.start(" not in test
    assert 'getModule("mmw60.appbridge").callAttr("self_check")' in test


def test_page_speaks_the_bridge_the_activity_injects():
    js = _text("src/mmw60/webui/www/core.js")
    assert "window.onHostReply = " in js and "window.host.call(id, route, JSON.stringify(" in js


def test_gradle_bundles_the_page_takes_the_library_as_source_and_installs_the_named_stack():
    gradle = _code(_text("android/app/build.gradle.kts"))
    assets = re.search(r'assets\.setSrcDirs\(listOf\("([^"]+)"\)\)', gradle).group(1)
    assert (ANDROID / "app" / assets).resolve() == WWW.parent.resolve()
    src = re.search(r'srcDir\("([^"]+)"\)', gradle).group(1)
    assert (ANDROID / "app" / src).resolve() == Path(mmw60.__file__).resolve().parents[1]     # the library, as source
    assert 'extractPackages("mmw60")' in gradle           # the spec tables and the baseline are read by path
    # the stack file is installed with its dependencies (Chaquopy's numpy needs its OpenBLAS package:
    # --no-deps built a fine-looking APK that could not import numpy), and nothing else comes from pip
    assert 'file("../phone-stack.txt")' in gradle and "--no-deps" not in gradle
    assert re.findall(r'install\(("[^"]*"|\w+)\)', gradle) == ["it", '"pyyaml"']
    assert "matplotlib" not in gradle and "numba" not in gradle
    assert f'versionName = "{mmw60.__version__}"' in gradle
    major, minor, patch = (int(x) for x in mmw60.__version__.split("."))
    assert f"versionCode = {major * 10000 + minor * 100 + patch}" in gradle       # an update installs over the last
    stack = [ln for ln in _code(_text("android/phone-stack.txt"), "#").split() if ln]
    assert [re.fullmatch(r"(numpy|scipy)==\d+\.\d+\.\d+", ln) is not None for ln in stack] == [True, True]


def test_workflows_build_with_the_same_python_and_count_the_on_device_tests_that_exist():
    gradle = _code(_text("android/app/build.gradle.kts"))
    py = re.search(r'^\s*version = "(\d+\.\d+)"', gradle, flags=re.M).group(1)
    android = _code(_text(".github/workflows/android.yml"), "#")
    ci = _code(_text(".github/workflows/ci.yml"), "#")
    assert f'python-version: "{py}"' in android
    phone = ci[ci.index("  test-phone-stack:"):ci.index("  vendor-drift:")]
    assert f'python-version: "{py}"' in phone and "pip install -r android/phone-stack.txt" in phone
    assert "pip install --no-deps -e ." in phone and "python -m mmw60.appbridge --jobs" in phone
    tests = len(re.findall(r"^\s*@Test\b", _text("android/app/src/androidTest/java/com/mmw60/app/OnDeviceTest.kt"),
                           flags=re.M))
    counted = re.search(r"check_ondevice_results\.py \S+ (\d+)", android)
    assert tests == int(counted.group(1)) == 5
    assert "gradle :app:connectedDebugAndroidTest" in android and "check_apk.py" in android
    # the count is checked after the step that can fail, and always
    after = android[android.index("gradle :app:connectedDebugAndroidTest"):]
    assert "if: always()" in after[:after.index("check_ondevice_results.py")]


def test_the_back_key_test_taps_and_presses_the_real_key():
    """A click made from JavaScript carries no user activation, and Chromium does not count a
    history entry left without one: with such a click the back key closed the app from the Runs
    screen (android run 12, 2026-11-21).  The test must change screens the way a finger does."""
    body = _code(_text("android/app/src/androidTest/java/com/mmw60/app/OnDeviceTest.kt"))
    test = body[body.index("fun backLeavesAScreenBeforeItLeavesTheApp()"):body.index("fun rotationKeepsThePage()")]
    assert 'tap(scenario, "nav-runs")' in test and ".click()" not in test
    assert test.count("inst.sendKeyDownUpSync(KeyEvent.KEYCODE_BACK)") == 2     # back one screen, then out
    assert "onBackPressed()" not in test                    # not the activity's method called by hand
    tap = body[body.index("private fun tap("):body.index("private fun eval(")]
    assert "MotionEvent.ACTION_DOWN" in tap and "MotionEvent.ACTION_UP" in tap and "sendPointerSync(down)" in tap
    # the shell asks the WebView's own history
    main = _code(_text("android/app/src/main/java/com/mmw60/app/MainActivity.kt"))
    assert "if (web.canGoBack()) web.goBack() else super.onBackPressed()" in main


def test_the_bridge_path_imports_neither_matplotlib_nor_numba_and_reads_all_four_reports(tmp_path):
    """What the app leaves out must not be needed: in a fresh interpreter where importing either
    raises, the routes the page opens on still answer."""
    import subprocess
    import sys
    code = (
        "import sys, json\n"
        "class Block:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        "        if name.split('.')[0] in ('matplotlib', 'numba'):\n"
        "            raise ImportError(name + ' is not in the app')\n"
        "sys.meta_path.insert(0, Block())\n"
        "from mmw60 import appbridge\n"
        "for name in ('table', 'calibration', 'array', 'ay'):\n"
        "    j = json.loads(appbridge.call('report', json.dumps({'report': name, 'study': {}})))\n"
        "    assert j['ok'] and j['report'] is not None, (name, j.get('error'))\n"
        "assert json.loads(appbridge.call('state'))['ok'] and json.loads(appbridge.call('parts'))['ok']\n"
        "print('answered')\n")
    env = {"PYTHONPATH": str(ROOT / "src"), "MMW60_HOME": str(tmp_path), "PATH": ""}
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=300)
    assert r.returncode == 0 and r.stdout.strip() == "answered", r.stderr[-2000:]


def test_analytic_agreement_is_zero_on_itself_and_sees_a_moved_number_a_changed_word_and_a_lost_row():
    ref = guistore.load_baseline()["table"]["report"]
    same = g.analytic_agreement(ref, ref)
    assert same["rows"] == len(ref["rows"]) and same["numbers"] == same["identical"] > 500
    assert same["worst_scaled"] == 0.0 and same["mismatches"] == [] and same["worst"] is None
    moved = json.loads(json.dumps(ref))
    row = moved["rows"][3]
    row["floor_db"] += 1e-6
    row["reason"] += "?"
    del moved["rows"][0]
    a = g.analytic_agreement(moved, ref)
    assert a["rows"] == len(ref["rows"]) - 1 and a["numbers"] - a["identical"] == 1
    assert appbridge.SELF_CHECK_TOL < a["worst_scaled"] < 1e-6 and a["worst"]["where"] == f"{row['label']}: floor_db"
    assert sorted(m["where"] for m in a["mismatches"]) == sorted([f"{row['label']}: reason", ref["rows"][0]["label"]])
    # the decoder caps and the time-domain column are not judged: a preview legitimately differs there
    other = json.loads(json.dumps(ref))
    other["rows"][3].update(dec_mcs=0, td_evm_db=None)
    assert g.analytic_agreement(other, ref)["worst_scaled"] == 0.0


@pytest.mark.slow
def test_self_check_holds_on_this_machine_and_fails_on_a_baseline_that_is_not_what_the_code_computes(monkeypatch):
    appbridge.reset()
    monkeypatch.delenv("MMW60_HOME", raising=False)
    out = json.loads(appbridge.self_check())
    assert out["ok"] and [c["ok"] for c in out["checks"]] == [True, True, True], out["summary"]
    assert out["checks"][2]["detail"]["rows"] == 19 and out["summary"].startswith("ok: python ")
    # the same check on a doctored baseline goes red and names the row (a guard that cannot fail guards nothing)
    real = guistore.load_baseline()
    bad = json.loads(json.dumps(real))
    bad["table"]["report"]["rows"][5]["floor_db"] += 0.01
    monkeypatch.setattr(guistore, "load_baseline", lambda directory=None: bad)
    out = json.loads(appbridge.self_check())
    assert not out["ok"] and [c["ok"] for c in out["checks"]] == [True, True, False]
    assert real["table"]["report"]["rows"][5]["label"] in out["summary"]
    appbridge.reset()
