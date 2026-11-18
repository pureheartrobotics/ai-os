package com.pureheartrobotics.aios.core

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ContextTest {
    private fun msg(role: String, content: String) = JSONObject().put("role", role).put("content", content)

    @Test
    fun onlyTheLatestScreenSurvives() {
        val messages = JSONArray()
            .put(msg("system", "sys"))
            .put(msg("user", "打开设置${SCREEN_MARK}[1] Button 设置"))
            .put(msg("tool", "已打开${SCREEN_MARK}[1] Button 网络"))

        dropStaleScreens(messages)

        val first = messages.getJSONObject(1).getString("content")
        val last = messages.getJSONObject(2).getString("content")
        assertFalse(first.contains("[1] Button 设置"))
        assertTrue(first.startsWith("打开设置"))
        assertTrue(last.contains("[1] Button 网络"))
    }

    @Test
    fun trimmingKeepsSystemPromptAndWholeTurns() {
        val messages = JSONArray().put(msg("system", "sys"))
        for (turn in 1..4) {
            messages.put(msg("user", "u$turn"))
            messages.put(JSONObject().put("role", "assistant").put("content", "").put("tool_calls", JSONArray()))
            messages.put(msg("tool", "t$turn"))
        }

        val trimmed = trimTurns(messages, maxTurns = 2)

        assertEquals("sys", trimmed.getJSONObject(0).getString("content"))
        assertEquals("u3", trimmed.getJSONObject(1).getString("content"))
        assertEquals(1 + 2 * 3, trimmed.length())
    }
}
