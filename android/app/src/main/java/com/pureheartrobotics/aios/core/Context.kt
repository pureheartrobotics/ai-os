package com.pureheartrobotics.aios.core

import org.json.JSONArray
import org.json.JSONObject

const val SCREEN_MARK = "\n\n=== 当前屏幕 ===\n"
private const val STALE_SCREEN = "\n\n（旧的屏幕状态已省略）"

/** Keeps only the latest screen snapshot in context to bound token usage. */
fun dropStaleScreens(messages: JSONArray) {
    val marker = SCREEN_MARK.trim()
    var seenLatest = false
    for (i in messages.length() - 1 downTo 0) {
        val msg = messages.optJSONObject(i) ?: continue
        val content = msg.opt("content") as? String ?: continue
        if (marker !in content) continue
        if (!seenLatest) {
            seenLatest = true
            continue
        }
        msg.put("content", content.substringBefore(marker).trimEnd() + STALE_SCREEN)
    }
}

/**
 * Drops whole earlier turns (a user message and everything after it up to the next user message)
 * until at most [maxTurns] remain, so tool calls and their results are never split.
 */
fun trimTurns(messages: JSONArray, maxTurns: Int): JSONArray {
    val userIdx = (0 until messages.length()).filter { messages.getJSONObject(it).optString("role") == "user" }
    if (userIdx.size <= maxTurns) return messages
    val cut = userIdx[userIdx.size - maxTurns]
    val out = JSONArray()
    for (i in 0 until messages.length()) {
        val msg: JSONObject = messages.getJSONObject(i)
        if (i < cut && msg.optString("role") != "system") continue
        out.put(msg)
    }
    return out
}
