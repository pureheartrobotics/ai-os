plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.pureheartrobotics.aios"
    compileSdk = 35
    buildToolsVersion = "35.0.0"

    defaultConfig {
        applicationId = "com.pureheartrobotics.aios"
        minSdk = 26
        targetSdk = 35
        versionCode = 2
        versionName = "0.1.1"
    }

    // The keystore and its passwords live in ~/.gradle/gradle.properties, never in the repo.
    val releaseStore = providers.gradleProperty("AIOS_RELEASE_STORE_FILE").orNull
    signingConfigs {
        if (releaseStore != null) {
            create("release") {
                storeFile = file(releaseStore)
                storePassword = providers.gradleProperty("AIOS_RELEASE_STORE_PASSWORD").get()
                keyAlias = providers.gradleProperty("AIOS_RELEASE_KEY_ALIAS").get()
                keyPassword = providers.gradleProperty("AIOS_RELEASE_KEY_PASSWORD").get()
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.findByName("release")
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    buildFeatures {
        buildConfig = true
    }
}

dependencies {
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
