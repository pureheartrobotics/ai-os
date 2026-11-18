package com.pureheartrobotics.aios.agent

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.util.concurrent.TimeUnit

private val JSON = "application/json; charset=utf-8".toMediaType()

internal val http: OkHttpClient = OkHttpClient.Builder()
    .connectTimeout(20, TimeUnit.SECONDS)
    .readTimeout(120, TimeUnit.SECONDS)
    .writeTimeout(60, TimeUnit.SECONDS)
    .build()

private fun Request.Builder.auth(key: String) = header("Authorization", "Bearer $key")

private fun execute(request: Request): okhttp3.Response {
    val response = http.newCall(request).execute()
    if (!response.isSuccessful) {
        val body = response.body?.string()?.take(300) ?: ""
        response.close()
        throw IOException("HTTP ${response.code}: $body")
    }
    return response
}

/** OpenAI-compatible chat completions client. */
class LlmClient(
    baseUrl: String,
    private val apiKey: String,
    private val model: String,
    private val thinking: String? = null,
) {
    private val base = baseUrl.trimEnd('/')

    /** Returns the assistant message object of the first choice. */
    fun chat(messages: JSONArray, tools: JSONArray?): JSONObject {
        val body = JSONObject()
            .put("model", model)
            .put("messages", messages)
            .put("temperature", 0.2)
        if (tools != null) body.put("tools", tools).put("tool_choice", "auto")
        if (!thinking.isNullOrBlank()) body.put("thinking", JSONObject().put("type", thinking))
        val request = Request.Builder().url("$base/chat/completions").auth(apiKey)
            .post(body.toString().toRequestBody(JSON)).build()
        execute(request).use { response ->
            val json = JSONObject(response.body!!.string())
            return json.getJSONArray("choices").getJSONObject(0).getJSONObject("message")
        }
    }

    fun describeImage(prompt: String, base64Jpeg: String): String {
        val content = JSONArray()
            .put(JSONObject().put("type", "text").put("text", prompt))
            .put(JSONObject().put("type", "image_url")
                .put("image_url", JSONObject().put("url", "data:image/jpeg;base64,$base64Jpeg")))
        val messages = JSONArray().put(JSONObject().put("role", "user").put("content", content))
        return chat(messages, null).optString("content")
    }
}

/** DeepSeek standalone speech APIs, same endpoints as the Windows build. */
class DeepSeekSpeech(baseUrl: String, private val apiKey: String, private val voice: String) {
    private val base = baseUrl.trimEnd('/')

    fun transcribe(wav: ByteArray): String {
        val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            .addFormDataPart("file", "speech.wav", wav.toRequestBody("audio/wav".toMediaType()))
            .build()
        val request = Request.Builder().url("$base/v1/tools/asr").auth(apiKey).post(body).build()
        execute(request).use { return JSONObject(it.body!!.string()).optString("text").trim() }
    }

    fun synthesize(text: String): ByteArray {
        val body = JSONObject().put("text", text).put("voice_id", voice).put("format", "wav").put("filter_markdown", true)
        val request = Request.Builder().url("$base/v1/tools/tts").auth(apiKey)
            .post(body.toString().toRequestBody(JSON)).build()
        execute(request).use { return it.body!!.bytes() }
    }
}
