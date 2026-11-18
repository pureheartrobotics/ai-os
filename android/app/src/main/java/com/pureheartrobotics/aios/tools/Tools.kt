package com.pureheartrobotics.aios.tools

import org.json.JSONArray
import org.json.JSONObject

private fun fn(name: String, description: String, properties: JSONObject = JSONObject(), required: List<String> = emptyList()) =
    JSONObject()
        .put("type", "function")
        .put("function", JSONObject()
            .put("name", name)
            .put("description", description)
            .put("parameters", JSONObject()
                .put("type", "object")
                .put("properties", properties)
                .put("required", JSONArray(required))))

private fun prop(type: String, description: String? = null, enum: List<String>? = null) = JSONObject().apply {
    put("type", type)
    description?.let { put("description", it) }
    enum?.let { put("enum", JSONArray(it)) }
}

val KEYS = listOf("back", "home", "recents", "notifications", "quick_settings", "enter", "lock_screen")

/** OpenAI-style tool definitions; the same list can back an MCP tools/list response. */
val TOOLS: JSONArray = JSONArray()
    .put(fn("get_screen_elements", "重新读取当前界面的控件列表（带编号）。"))
    .put(fn("click_element", "点击控件列表中编号为 id 的控件。",
        JSONObject()
            .put("id", prop("integer"))
            .put("long_press", prop("boolean", "是否长按")),
        listOf("id")))
    .put(fn("tap_xy", "按 look_at_screen 截图中的像素坐标点击。仅在控件列表里找不到目标时使用。",
        JSONObject().put("x", prop("integer")).put("y", prop("integer")),
        listOf("x", "y")))
    .put(fn("type_text", "把文字填进输入框（支持中文），会替换输入框原有内容。不指定 element_id 时填入当前焦点输入框。",
        JSONObject()
            .put("text", prop("string"))
            .put("element_id", prop("integer", "可选，目标输入框编号"))
            .put("press_enter", prop("boolean", "填完后是否按键盘上的回车/搜索/发送键")),
        listOf("text")))
    .put(fn("press_key", "系统按键：back 返回，home 回桌面，recents 最近任务，notifications 下拉通知栏，" +
            "quick_settings 快捷设置，enter 键盘回车，lock_screen 锁屏。",
        JSONObject()
            .put("key", prop("string", enum = KEYS))
            .put("times", prop("integer", "重复次数，默认 1")),
        listOf("key")))
    .put(fn("scroll", "滚动列表或页面，默认滚动一屏。指定 element_id 时滚动包含该控件的列表。",
        JSONObject()
            .put("direction", prop("string", enum = listOf("up", "down", "left", "right")))
            .put("element_id", prop("integer"))
            .put("times", prop("integer", "滚动几次，默认 1")),
        listOf("direction")))
    .put(fn("open_app", "按名称打开应用，例如 '微信'、'设置'、'相机'、'Chrome'。",
        JSONObject().put("name", prop("string")), listOf("name")))
    .put(fn("list_apps", "列出手机上已安装、可以打开的应用。",
        JSONObject().put("keyword", prop("string", "可选，按名称过滤"))))
    .put(fn("open_url", "用默认浏览器打开网址。搜索时可构造搜索引擎网址。",
        JSONObject().put("url", prop("string")), listOf("url")))
    .put(fn("look_at_screen", "截图并让视觉模型回答关于屏幕内容的问题，可要求返回目标的像素坐标供 tap_xy 使用。",
        JSONObject().put("question", prop("string")), listOf("question")))
    .put(fn("wait", "等待界面加载。", JSONObject().put("seconds", prop("number")), listOf("seconds")))
    .put(fn("ask_user", "当指令有歧义或缺少信息时，语音询问用户并获得回答。",
        JSONObject().put("question", prop("string")), listOf("question")))
    .put(fn("finish", "任务完成或无法继续时调用，summary 会被朗读给用户，应简短口语化。",
        JSONObject().put("summary", prop("string")), listOf("summary")))

val READ_ONLY_TOOLS = setOf("get_screen_elements", "list_apps", "look_at_screen", "wait", "ask_user", "finish")
