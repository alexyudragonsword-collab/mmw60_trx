plugins {
    id("com.android.application") version "8.1.4" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
    // The version set is the one the sibling apps build with (array_tx,
    // polar_tx, pll_simulator): Chaquopy 15.x is the newest line whose
    // repository carries scipy for Python 3.10, and 3.10 is the newest Python
    // with an Android scipy wheel at all.  Change one of plugin / Python
    // version / the workflow's setup-python and re-check the others.
    id("com.chaquo.python") version "15.0.1" apply false
}
