import java.util.Properties

plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

val versionFile = rootProject.file("../packaging/version.txt")
val nudgeVersion = if (versionFile.exists()) versionFile.readText().trim() else "2.1.0"

android {
    namespace = "com.nudge.app"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.nudge.app"
        minSdk = 24
        targetSdk = 34
        versionCode = nudgeVersion.replace(".", "").toIntOrNull() ?: 210
        versionName = nudgeVersion
        buildConfigField("String", "NUDGE_URL", "\"https://eternity0628.pythonanywhere.com\"")
    }

    buildFeatures {
        buildConfig = true
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("debug")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("androidx.webkit:webkit:1.11.0")
}