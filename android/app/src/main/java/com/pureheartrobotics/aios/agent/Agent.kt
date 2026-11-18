package com.pureheartrobotics.aios.agent

import android.util.Log
import com.pureheartrobotics.aios.core.SCREEN_MARK
import com.pureheartrobotics.aios.core.dropStaleScreens
import com.pureheartrobotics.aios.core.trimTurns
import com.pureheartrobotics.aios.screen.ScreenReader
import com.pureheartrobotics.aios.tools.Actions
import com.pureheartrobotics.aios.tools.READ_ONLY_TOOLS
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject

private const val TAG = "AiOs"
private const val SCREEN_TAG = "AiOsScreen"

private const val SYSTEM_PROMPT = """你是一个运行在安卓手机上的语音操作助手，用户主要通过语音控制手机。
你的任务是把用户的口语指令转化为一系列手机操作并执行完成。

工作方式：
- 每次操作后你会收到最新的屏幕控件列表，格式为 [编号] 类型 名称（状态）。
- 优先使用 click_element 按编号点击；控件列表里找不到目标时，再用 look_at_screen + tap_xy（未提供这两个工具时，改用滚动、返回或换一种操作路径）。
- 善用 open_app、open_url、press_key（back 返回、home 回桌面），它们比逐个点击更可靠。
- 列表里没看到目标时先 scroll 再找，不要猜编号。
- 输入文字用 type_text，它会填进当前焦点输入框；需要时先点击输入框。
- 每一步后检查屏幕状态是否符合预期，不符合就调整策略，不要盲目重复同一个动作。
- 用户口述可能有同音错别字，请结合语境理解。
- 指令有歧义或缺少关键信息（如联系人、金额）时，用 ask_user 询问。
- 发送消息、付款、删除、拨打电话、修改密码等不可逆操作，执行前先用 ask_user 确认。
- 网页和应用加载需要时间；要读取的结果没出现在控件列表里时，先 wait 再 get_screen_elements，不要凭空给出结果。
- summary 只陈述你在屏幕上确认过的结果；没能在手机上完成时如实说明，不要声称用了某个应用。
- 完成后调用 finish，summary 用一两句口语化中文告诉用户结果。纯问答类问题（不需要操作手机）也直接用 finish 回答。"""

private val TOOL_LABELS = mapOf(
    "get_screen_elements" to "读取屏幕", "click_element" to "点击", "tap_xy" to "点击坐标",
    "type_text" to "输入", "press_key" to "按键", "scroll" to "滚动", "open_app" to "打开",
    "list_apps" to "查看应用", "open_url" to "打开网址", "look_at_screen" to "看屏幕",
    "wait" to "等待", "ask_user" to "询问",
)

class Agent(
    private val llm: LlmClient,
    private val actions: Actions,
    private val screen: ScreenReader,
    private val maxSteps: Int,
    private val status: (String) -> Unit,
) {
    /** Conversation across follow-up turns, so "关掉它" can refer to what was just opened. */
    private var messages = JSONArray().put(JSONObject().put("role", "system").put("content", SYSTEM_PROMPT))

    @Volatile var cancelled = false

    fun resetConversation() {
        messages = JSONArray().put(messages.getJSONObject(0))
    }

    /** Runs one command to completion and returns what should be spoken to the user. */
    fun run(command: String): String {
        Log.i(TAG, "[用户] $command")
        cancelled = false
        messages = trimTurns(messages, MAX_TURNS)
        messages.put(JSONObject().put("role", "user").put("content", command + SCREEN_MARK + screen.snapshot()))
        dropStaleScreens(messages)
        for (step in 0 until maxSteps) {
            if (cancelled) return "已停止。"
            step()?.let { return it }
        }
        return "步骤太多了，我先停下来。你可以换个说法再试一次。"
    }

    /** One model turn; returns the final reply when the task is finished. */
    private fun step(): String? {
        status("思考中…")
        val message = llm.chat(messages, actions.tools)
        val toolCalls = message.optJSONArray("tool_calls") ?: JSONArray()

        val entry = JSONObject().put("role", "assistant").put("content", message.optString("content", ""))
        // DeepSeek thinking mode requires the reasoning to be echoed back while tool calls are in flight.
        message.optString("reasoning_content").takeIf { it.isNotEmpty() }?.let { entry.put("reasoning_content", it) }
        if (toolCalls.length() > 0) entry.put("tool_calls", toolCalls)
        messages.put(entry)

        if (toolCalls.length() == 0) return message.optString("content").ifBlank { "好的。" }

        var screenChanged = false
        for (i in 0 until toolCalls.length()) {
            val call = toolCalls.getJSONObject(i)
            val id = call.getString("id")
            val fn = call.getJSONObject("function")
            val name = fn.getString("name")
            val args = try {
                JSONObject(fn.optString("arguments").ifBlank { "{}" })
            } catch (_: JSONException) {
                JSONObject()
            }

            if (name == "finish") {
                messages.put(toolResult(id, "ok"))
                return args.optString("summary").ifBlank { "完成了。" }
            }
            if (cancelled) {
                messages.put(toolResult(id, "用户已叫停。"))
                continue
            }

            Log.i(TAG, "  -> $name($args)")
            status(describe(name, args))
            var result = actions.dispatch(name, args)
            Log.i(TAG, "     ${result.lineSequence().firstOrNull() ?: ""}")
            if (name == "get_screen_elements") result = SCREEN_MARK.trimStart() + result
            screenChanged = screenChanged || name !in READ_ONLY_TOOLS
            messages.put(toolResult(id, result))
        }

        if (screenChanged && !cancelled) {
            Thread.sleep(SETTLE_MS)
            val last = messages.getJSONObject(messages.length() - 1)
            val snapshot = screen.snapshot()
            Log.d(SCREEN_TAG, snapshot)
            last.put("content", last.getString("content") + SCREEN_MARK + snapshot)
        }
        dropStaleScreens(messages)
        return null
    }

    private fun toolResult(id: String, content: String) =
        JSONObject().put("role", "tool").put("tool_call_id", id).put("content", content)

    private fun describe(name: String, args: JSONObject): String {
        val verb = TOOL_LABELS[name] ?: name
        val target = if (name == "click_element") {
            screen.elements[args.optInt("id")]?.let { it.name.ifEmpty { it.kind } } ?: ""
        } else {
            listOf("name", "text", "key", "url", "direction", "question").firstNotNullOfOrNull { k ->
                args.optString(k).takeIf { it.isNotEmpty() }
            } ?: ""
        }
        return "$verb $target".trim()
    }

    companion object {
        private const val MAX_TURNS = 6
        private const val SETTLE_MS = 700L
    }
}
