package com.mmw60.app

import android.annotation.SuppressLint
import android.app.Activity
import android.content.Context
import android.os.Bundle
import android.system.Os
import android.webkit.JavascriptInterface
import android.webkit.WebView
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.util.concurrent.Executors

/**
 * A WebView shell around mmw60.appbridge (the pattern the sibling apps use).
 *
 * Deliberately inert: every feature is a Python function behind webhost.Api
 * plus a render in the page.  If a change seems to need Kotlin, the logic
 * wanted to be in Python, where the test suite is.
 *
 * All bridge calls run on ONE background thread: the first call pays the
 * import of numpy + scipy (seconds on a phone), and the library has no
 * locking of its own.  Jobs run on mmw60's thread-backend queue, so a call
 * returns at once and the page polls the queue as it does on the desktop.
 */
class MainActivity : Activity() {

    private val executor = Executors.newSingleThreadExecutor()
    lateinit var web: WebView
        private set
    private var bridge: PyObject? = null

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        startPython(this)
        web = WebView(this)
        web.settings.javaScriptEnabled = true
        web.settings.domStorageEnabled = true          // the page keeps language and theme in localStorage
        web.addJavascriptInterface(HostBridge(), "host")
        setContentView(web)
        web.loadUrl("file:///android_asset/www/index.html")
    }

    /** Back leaves a screen of the page before it leaves the app (the page navigates by hash). */
    @Deprecated("Deprecated in Java")
    override fun onBackPressed() {
        if (web.canGoBack()) web.goBack() else super.onBackPressed()
    }

    inner class HostBridge {
        /** Async RPC: returns immediately, the reply lands via window.onHostReply. */
        @JavascriptInterface
        fun call(id: String, route: String, argsJson: String) {
            executor.execute {
                val reply = try {
                    val py = bridge ?: Python.getInstance()
                        .getModule("mmw60.appbridge").also { bridge = it }
                    py.callAttr("call", route, argsJson).toString()
                } catch (e: Exception) {
                    JSONObject().put("ok", false).put("error", e.toString()).toString()
                }
                runOnUiThread {
                    web.evaluateJavascript(
                        "window.onHostReply(${JSONObject.quote(id)},${JSONObject.quote(reply)})", null)
                }
            }
        }
    }

    companion object {
        /**
         * Start the interpreter with the environment mmw60 expects.  One place, so the
         * activity and the on-device tests cannot start it differently.  The variables
         * must be set BEFORE Python.start(): MMW60_HOME is where recomputed results
         * are kept (the app's own files directory), XDG_CACHE_HOME keeps any cache a
         * library wants off the read-only default, and MMW60_NO_JIT says outright that
         * the numba layer is absent here (it is a performance layer; the app ships none).
         */
        fun startPython(context: Context) {
            if (Python.isStarted()) return
            val home = context.filesDir.resolve("mmw60").apply { mkdirs() }
            val cache = context.filesDir.resolve("cache").apply { mkdirs() }
            Os.setenv("MMW60_HOME", home.path, true)
            Os.setenv("XDG_CACHE_HOME", cache.path, true)
            Os.setenv("MMW60_NO_JIT", "1", true)
            Python.start(AndroidPlatform(context))
        }
    }
}
