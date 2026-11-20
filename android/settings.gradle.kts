pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
        // Chaquopy: the Gradle plugin AND the package repository pip resolves
        // Android binary wheels from (numpy / scipy; PyPI has none for Android).
        maven("https://chaquo.com/maven")
    }
}
dependencyResolutionManagement {
    repositories {
        google()
        mavenCentral()
        maven("https://chaquo.com/maven")
    }
}
rootProject.name = "mmw60"
include(":app")
