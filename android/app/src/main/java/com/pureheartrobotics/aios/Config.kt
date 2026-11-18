package com.pureheartrobotics.aios

import android.content.Context

const val DEEPSEEK_BASE_URL = "https://api.deepseek.com"

data class Config(
    val apiKey: String,
    val baseUrl: String,
    val model: String,
    val thinking: String,
    val visionModel: String,
    val visionApiKey: String,
    val visionBaseUrl: String,
    val cloudVoice: Boolean,
    val ttsVoice: String,
    val maxSteps: Int,
) {
    val isDeepSeek: Boolean get() = "deepseek.com" in baseUrl

    companion object {
        private const val PREFS = "ai_os"

        fun load(context: Context): Config {
            val p = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            val key = p.getString("api_key", "")!!.trim()
            val base = p.getString("base_url", "")!!.trim().ifEmpty { DEEPSEEK_BASE_URL }
            return Config(
                apiKey = key,
                baseUrl = base,
                model = p.getString("model", "")!!.trim().ifEmpty { "deepseek-flash" },
                thinking = p.getString("thinking", "disabled")!!,
                visionModel = p.getString("vision_model", "")!!.trim(),
                visionApiKey = p.getString("vision_api_key", "")!!.trim().ifEmpty { key },
                visionBaseUrl = p.getString("vision_base_url", "")!!.trim().ifEmpty { base },
                cloudVoice = p.getBoolean("cloud_voice", true),
                ttsVoice = p.getString("tts_voice", "stella")!!,
                maxSteps = p.getInt("max_steps", 25),
            )
        }

        fun save(context: Context, apiKey: String, baseUrl: String, model: String, visionModel: String, cloudVoice: Boolean) {
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putString("api_key", apiKey.trim())
                .putString("base_url", baseUrl.trim())
                .putString("model", model.trim())
                .putString("vision_model", visionModel.trim())
                .putBoolean("cloud_voice", cloudVoice)
                .apply()
        }
    }
}
