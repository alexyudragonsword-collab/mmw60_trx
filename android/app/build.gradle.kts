plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("com.chaquo.python")
}

android {
    namespace = "com.mmw60.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.mmw60.app"
        minSdk = 24
        targetSdk = 34
        versionCode = 1
        versionName = "0.2.0"             // tracks the mmw60 version it bundles (tests/test_android.py)
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
        ndk {
            // arm64 for phones, x86_64 for the emulator the CI job runs; each
            // ABI carries its own CPython + numpy + scipy (tens of MB each)
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
    sourceSets {
        getByName("main") {
            // The page is one file set for every host: the desktop and the
            // browser get it from mmw60.webhost (src/mmw60/webui/www), and this
            // APK takes the very same files as its assets, loaded from
            // file:///android_asset/www/.
            assets.setSrcDirs(listOf("../../src/mmw60/webui"))
        }
    }
}

chaquopy {
    defaultConfig {
        // 3.10: the newest Python for which Chaquopy's repository has a scipy
        // wheel (chaquo/chaquopy#1237); mmw60 declares requires-python >= 3.10.
        version = "3.10"
        // mmw60 reads its spec tables and the shipped baseline through file
        // paths next to its modules; modules are otherwise imported straight
        // from the APK and those paths would not exist.
        extractPackages("mmw60")
        pip {
            // Exact versions from android/phone-stack.txt, resolved WITH their
            // dependencies: Chaquopy's numpy and scipy wheels depend on native
            // runtime packages (OpenBLAS, libgfortran) that live in the same
            // repository.  The first build of this app installed with --no-deps
            // and built fine; the emulator then failed on
            // `dlopen failed: library "libopenblas.so" not found`.
            file("../phone-stack.txt").readLines().map { it.trim() }
                .filter { it.isNotEmpty() && !it.startsWith("#") }
                .forEach { install(it) }
            install("pyyaml")
        }
    }
    sourceSets {
        getByName("main") {
            // mmw60 itself comes in as source, not through pip: its declared
            // floors (numpy >= 1.26, scipy >= 1.11, matplotlib) are the
            // desktop's and would fight the versions above in pip's resolve.
            // What keeps running below those floors honest is CI's
            // test-phone-stack job, on exactly android/phone-stack.txt.
            srcDir("../../src")
        }
    }
}

dependencies {
    // only the on-device tests use androidx; the app itself is android.app.Activity
    androidTestImplementation("androidx.test.ext:junit:1.1.5")
    androidTestImplementation("androidx.test:runner:1.5.2")
    androidTestImplementation("androidx.test:core:1.5.0")
}
