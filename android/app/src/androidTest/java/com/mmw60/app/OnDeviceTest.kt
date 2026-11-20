package com.mmw60.app

import android.util.Log
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.chaquo.python.Python
import org.json.JSONObject
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
        val js = "document.querySelectorAll('#screen-table [data-label]').length"
        var rows = 0
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            val deadline = System.currentTimeMillis() + 240_000
            while (rows == 0 && System.currentTimeMillis() < deadline) {
                Thread.sleep(2_000)
                val latch = CountDownLatch(1)
                scenario.onActivity { activity ->
                    activity.web.evaluateJavascript(js) { value ->
                        rows = value?.toIntOrNull() ?: 0
                        latch.countDown()
                    }
                }
                latch.await(10, TimeUnit.SECONDS)
            }
        }
        Log.i(TAG, "page rows drawn: $rows")
        assertTrue("the page drew no table row within four minutes", rows > 0)
    }

    companion object {
        const val TAG = "mmw60-ondevice"
    }
}
