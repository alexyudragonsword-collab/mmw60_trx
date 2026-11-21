package com.mmw60.app

import android.content.pm.ActivityInfo
import android.os.SystemClock
import android.util.Log
import android.view.KeyEvent
import android.view.MotionEvent
import androidx.lifecycle.Lifecycle
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * What a green build cannot say: that the app runs.
 *
 * The verdicts live in Python and in the page; these tests only assert them,
 * so the device and the desktop cannot be judged by different rules.  Each
 * test writes one line to logcat under the tag "mmw60-ondevice", which the
 * workflow prints (the device's interpreter, numpy, scipy, how far its
 * numbers sit from the shipped ones, how long it took).
 */
@RunWith(AndroidJUnit4::class)
class OnDeviceTest {

    /** Python starts, mmw60 imports on the app's numpy / scipy, reads its data files,
     *  and the analytic table recomputed on the device agrees with the shipped one. */
    @Test
    fun selfCheckAgreesWithTheShippedBaseline() {
        MainActivity.startPython(InstrumentationRegistry.getInstrumentation().targetContext)
        val text = Python.getInstance().getModule("mmw60.appbridge").callAttr("self_check").toString()
        val out = JSONObject(text)
        Log.i(TAG, "self_check " + out.optString("summary"))
        assertTrue("self_check: " + out.optString("summary"), out.getBoolean("ok"))
    }

    /** The whole shell: the assets are in the APK, the WebView loads them, the page finds
     *  window.host, Python answers through it and the page draws the table's rows. */
    @Test
    fun thePageDrawsTheTableThroughTheBridge() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            val rows = rowsDrawn(scenario)
            Log.i(TAG, "page rows drawn: $rows")
            assertTrue("the page drew no table row within four minutes", rows > 0)
        }
    }

    /**
     * Back leaves a screen of the page before it leaves the app, and from the first screen it
     * leaves the app.
     *
     * The screen is changed by a real tap and back by the real key.  A click made from JavaScript
     * carries no user activation, and Chromium does not count a history entry that was left
     * without one (WebView.canGoBack() then says false): the first version of this test clicked
     * from JavaScript, and back closed the app from the Runs screen (2026-11-21).
     */
    @Test
    fun backLeavesAScreenBeforeItLeavesTheApp() {
        val inst = InstrumentationRegistry.getInstrumentation()
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            assertTrue("the page drew no table row", rowsDrawn(scenario) > 0)
            val first = eval(scenario, "location.hash")
            tap(scenario, "nav-runs")
            val there = waitFor(scenario, "location.hash", 20) { it == RUNS }
            assertEquals("the tap did not take the page to the Runs screen", RUNS, there)
            inst.sendKeyDownUpSync(KeyEvent.KEYCODE_BACK)
            inst.waitForIdleSync()
            Thread.sleep(1_500)
            val alive = scenario.state.isAtLeast(Lifecycle.State.STARTED)
            Log.i(TAG, "back from $RUNS: app still open $alive")
            assertTrue("back closed the app instead of going back one screen", alive)
            val back = waitFor(scenario, "location.hash", 20) { it != RUNS }
            Log.i(TAG, "back: $first -> $RUNS -> $back")
            assertEquals("back did not return to the screen the tap left", first, back)
            inst.sendKeyDownUpSync(KeyEvent.KEYCODE_BACK)
            inst.waitForIdleSync()
            var closed = false
            for (i in 1..20) {
                closed = scenario.state == Lifecycle.State.DESTROYED
                if (closed) break
                Thread.sleep(500)
            }
            Log.i(TAG, "back on the first screen: app closed $closed")
            assertTrue("back on the first screen did not leave the app", closed)
        }
    }

    /** A rotation keeps the page: the same WebView, its rows still drawn, no reload. */
    @Test
    fun rotationKeepsThePage() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            val before = rowsDrawn(scenario)
            assertTrue("the page drew no table row", before > 0)
            var view = 0
            scenario.onActivity {
                view = System.identityHashCode(it.web)
                it.requestedOrientation = ActivityInfo.SCREEN_ORIENTATION_LANDSCAPE
            }
            val wide = waitFor(scenario, "window.innerWidth > window.innerHeight", 30) { it == "true" }
            var viewAfter = 0
            scenario.onActivity { viewAfter = System.identityHashCode(it.web) }
            val after = eval(scenario, ROWS).toIntOrNull() ?: 0
            Log.i(TAG, "rotation: landscape $wide, rows $before -> $after, same view ${view == viewAfter}")
            assertEquals("the page did not turn to landscape", "true", wide)
            assertTrue("the rotation replaced the WebView (the page reloaded)", view == viewAfter)
            assertEquals("rows were lost in the rotation", before, after)
        }
    }

    /** With the system in dark mode the page's "auto" theme sees a dark colour scheme. */
    @Test
    fun autoThemeFollowsTheSystemsDarkMode() {
        val ui = InstrumentationRegistry.getInstrumentation().uiAutomation
        ui.executeShellCommand("cmd uimode night yes").close()
        Thread.sleep(2_000)
        try {
            ActivityScenario.launch(MainActivity::class.java).use { scenario ->
                assertTrue("the page drew no table row", rowsDrawn(scenario) > 0)
                val dark = waitFor(scenario, "matchMedia('(prefers-color-scheme: dark)').matches", 20) { it == "true" }
                Log.i(TAG, "system dark mode: the page sees prefers-color-scheme dark = $dark")
                assertEquals("the page does not see the system's dark mode", "true", dark)
            }
        } finally {
            ui.executeShellCommand("cmd uimode night no").close()
        }
    }

    /** A real tap on the centre of an element of the page (a touch the system delivers, so the
     *  page has the user activation a finger gives it). */
    private fun tap(scenario: ActivityScenario<MainActivity>, id: String) {
        val at = eval(scenario, "(() => { const r = document.getElementById('$id').getBoundingClientRect(); " +
            "return [r.left + r.width / 2, r.top + r.height / 2, devicePixelRatio].join(' '); })()")
            .trim('"').split(" ").map { it.toFloat() }
        val origin = IntArray(2)
        scenario.onActivity { it.web.getLocationOnScreen(origin) }
        val x = origin[0] + at[0] * at[2]
        val y = origin[1] + at[1] * at[2]
        val inst = InstrumentationRegistry.getInstrumentation()
        val t = SystemClock.uptimeMillis()
        val down = MotionEvent.obtain(t, t, MotionEvent.ACTION_DOWN, x, y, 0)
        val up = MotionEvent.obtain(t, t + 60, MotionEvent.ACTION_UP, x, y, 0)
        inst.sendPointerSync(down)
        inst.sendPointerSync(up)
        down.recycle()
        up.recycle()
        inst.waitForIdleSync()
    }

    /** One JavaScript expression evaluated in the page; its JSON text ("null" when it did not answer). */
    private fun eval(scenario: ActivityScenario<MainActivity>, script: String): String {
        val latch = CountDownLatch(1)
        var out = "null"
        scenario.onActivity { activity ->
            activity.web.evaluateJavascript(script) { value ->
                out = value ?: "null"
                latch.countDown()
            }
        }
        latch.await(15, TimeUnit.SECONDS)
        return out
    }

    private fun waitFor(scenario: ActivityScenario<MainActivity>, script: String, seconds: Int,
                        ok: (String) -> Boolean): String {
        val deadline = System.currentTimeMillis() + seconds * 1000L
        var value = "null"
        while (System.currentTimeMillis() < deadline) {
            value = eval(scenario, script)
            if (ok(value)) return value
            Thread.sleep(1_000)
        }
        return value
    }

    /** Rows of the comparison table the page has drawn (waits up to four minutes for the first). */
    private fun rowsDrawn(scenario: ActivityScenario<MainActivity>): Int =
        waitFor(scenario, ROWS, 240) { (it.toIntOrNull() ?: 0) > 0 }.toIntOrNull() ?: 0

    companion object {
        const val TAG = "mmw60-ondevice"
        const val ROWS = "document.querySelectorAll('#screen-table [data-label]').length"
        const val RUNS = "\"#runs\""
    }
}
