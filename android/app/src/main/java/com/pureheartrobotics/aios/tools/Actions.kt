package com.pureheartrobotics.aios.tools

import android.accessibilityservice.AccessibilityService
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.provider.MediaStore
import android.provider.Settings
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityNodeInfo.AccessibilityAction
import com.pureheartrobotics.aios.AiOsService
import com.pureheartrobotics.aios.agent.LlmClient
import com.pureheartrobotics.aios.core.Element
import com.pureheartrobotics.aios.screen.ScreenReader
import org.json.JSONArray
import org.json.JSONObject
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Executes tool calls. Transport-agnostic: the built-in agent calls [dispatch], and so could an MCP endpoint. */
class Actions(
    private val service: AiOsService,
    private val screen: ScreenReader,
    private val vision: LlmClient?,
    private val ask: (String) -> String,
) {
    private var screenshotScale = 1.0

    /** Tool definitions this instance can actually serve; without a vision model there is nothing to look with. */
    val tools: JSONArray = if (vision != null) TOOLS else JSONArray().apply {
        for (i in 0 until TOOLS.length()) {
            val tool = TOOLS.getJSONObject(i)
            val name = tool.getJSONObject("function").getString("name")
            if (name != "look_at_screen" && name != "tap_xy") put(tool)
        }
    }

    fun dispatch(name: String, args: JSONObject): String = try {
        when (name) {
            "get_screen_elements" -> screen.snapshot()
            "click_element" -> clickElement(args.getInt("id"), args.optBoolean("long_press"))
            "tap_xy" -> tapXy(args.getInt("x"), args.getInt("y"))
            "type_text" -> typeText(args.getString("text"), args.optIntOrNull("element_id"), args.optBoolean("press_enter"))
            "press_key" -> pressKey(args.getString("key"), args.optInt("times", 1))
            "scroll" -> scroll(args.getString("direction"), args.optIntOrNull("element_id"), args.optInt("times", 1))
            "open_app" -> openApp(args.getString("name"))
            "list_apps" -> listApps(args.optString("keyword"))
            "open_url" -> openUrl(args.getString("url"))
            "look_at_screen" -> lookAtScreen(args.getString("question"))
            "wait" -> waitSeconds(args.optDouble("seconds", 1.0))
            "ask_user" -> ask(args.getString("question")).let { if (it.isBlank()) "用户没有回答。" else "用户回答：$it" }
            else -> "错误：未知工具 $name"
        }
    } catch (e: Exception) {
        "错误：${e.javaClass.simpleName}: ${e.message}"
    }

    private fun element(id: Int): Element =
        screen.elements[id] ?: throw IllegalArgumentException("控件 $id 不存在，请先调用 get_screen_elements 刷新。")

    private fun clickElement(id: Int, long: Boolean): String {
        val el = element(id)
        val node = el.handle as? AccessibilityNodeInfo
        val action = if (long) AccessibilityNodeInfo.ACTION_LONG_CLICK else AccessibilityNodeInfo.ACTION_CLICK
        val target = node?.let { ancestorOrSelf(it) { n -> if (long) n.isLongClickable else n.isClickable } }
        val done = target?.performAction(action) == true || service.tap(el.x, el.y, if (long) 700L else 60L)
        if (!done) return "错误：点击 [$id] 失败，请调用 get_screen_elements 重新读取界面。"
        return "已${if (long) "长按" else "点击"} [$id] ${el.kind} \"${el.name}\""
    }

    private fun tapXy(x: Int, y: Int): String {
        val sx = (x / screenshotScale).toInt()
        val sy = (y / screenshotScale).toInt()
        return if (service.tap(sx, sy, 60L)) "已点击屏幕坐标 ($sx,$sy)" else "错误：点击屏幕坐标 ($sx,$sy) 失败"
    }

    private fun typeText(text: String, elementId: Int?, pressEnter: Boolean): String {
        val target = elementId?.let { element(it) }
        val node = target?.let { e ->
            val handle = e.handle as? AccessibilityNodeInfo
            handle?.takeIf { it.isEditable } ?: handle?.let { screen.firstEditable(it) }
                ?: return "错误：[${e.id}] ${e.kind} 不是输入框，请先点击它，或指定 Edit 类控件。"
        }
            ?: awaitFocusedInput()
            ?: screen.firstEditable()
            ?: return "错误：当前界面没有输入框，请先点击要输入的位置。"
        if (!node.isFocused) node.performAction(AccessibilityNodeInfo.ACTION_FOCUS)

        val args = Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, text)
        }
        // A field on a page that is still animating in rejects text for a moment.
        val deadline = SystemClock.uptimeMillis() + 2000
        var ok = node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
        while (!ok && SystemClock.uptimeMillis() < deadline) {
            Thread.sleep(250)
            node.refresh()
            ok = node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
        }
        if (!ok) ok = paste(node, text)
        if (!ok) return "错误：无法在该输入框输入文字。"
        var result = if (node.isPassword) "已在密码框输入 ${text.length} 个字符" else "已输入：${text.take(50)}"
        if (pressEnter) result += if (imeEnter(node)) "，并按下回车" else "（此输入框不支持模拟回车，请点击发送或搜索按钮）"
        return result
    }

    /** A tap that opens a search page focuses its field a moment later. */
    private fun awaitFocusedInput(): AccessibilityNodeInfo? {
        val deadline = SystemClock.uptimeMillis() + 1500
        while (true) {
            screen.focusedInput()?.let { return it }
            if (SystemClock.uptimeMillis() > deadline) return null
            Thread.sleep(150)
        }
    }

    private fun paste(node: AccessibilityNodeInfo, text: String): Boolean {
        val latch = CountDownLatch(1)
        Handler(Looper.getMainLooper()).post {
            val clipboard = service.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
            clipboard.setPrimaryClip(ClipData.newPlainText("ai-os", text))
            latch.countDown()
        }
        latch.await(1, TimeUnit.SECONDS)
        return node.performAction(AccessibilityNodeInfo.ACTION_PASTE)
    }

    private fun imeEnter(node: AccessibilityNodeInfo?): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return false
        val target = node ?: screen.focusedInput() ?: return false
        return target.performAction(AccessibilityAction.ACTION_IME_ENTER.id)
    }

    private fun pressKey(key: String, times: Int): String {
        val normalized = KEY_ALIASES[key.trim()] ?: key.trim().lowercase()
        repeat(times.coerceIn(1, 10)) {
            val ok = when (normalized) {
                "back" -> service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_BACK)
                "home" -> service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_HOME)
                "recents" -> service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_RECENTS)
                "notifications" -> service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_NOTIFICATIONS)
                "quick_settings" -> service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_QUICK_SETTINGS)
                "lock_screen" -> Build.VERSION.SDK_INT >= Build.VERSION_CODES.P &&
                    service.performGlobalAction(AccessibilityService.GLOBAL_ACTION_LOCK_SCREEN)
                "enter" -> imeEnter(null)
                else -> return "错误：无法识别的按键 $key，可用：${KEYS.joinToString("、")}"
            }
            if (!ok) return "错误：按键 $normalized 没有生效"
            Thread.sleep(250)
        }
        return "已按下 $normalized" + if (times > 1) " ×$times" else ""
    }

    private fun scroll(direction: String, elementId: Int?, times: Int): String {
        val start = elementId?.let { element(it).handle as? AccessibilityNodeInfo }
        val container = start?.let { ancestorOrSelf(it) { n -> n.isScrollable } }
            ?: screen.elements.values.filter { "可滚动" in it.flags }.maxByOrNull { it.area }?.handle as? AccessibilityNodeInfo
        val label = "已向${DIRECTION_LABELS[direction] ?: direction}滚动" + if (times > 1) " $times 次" else ""
        repeat(times.coerceIn(1, 10)) {
            if (container == null || !scrollNode(container, direction)) {
                if (!service.swipe(direction, container)) return "错误：滚动失败"
            }
            Thread.sleep(350)
        }
        return label
    }

    private fun scrollNode(node: AccessibilityNodeInfo, direction: String): Boolean {
        val specific = when (direction) {
            "up" -> AccessibilityAction.ACTION_SCROLL_UP
            "down" -> AccessibilityAction.ACTION_SCROLL_DOWN
            "left" -> AccessibilityAction.ACTION_SCROLL_LEFT
            else -> AccessibilityAction.ACTION_SCROLL_RIGHT
        }
        if (node.actionList.any { it.id == specific.id } && node.performAction(specific.id)) return true
        val generic = if (direction == "down" || direction == "right") AccessibilityNodeInfo.ACTION_SCROLL_FORWARD
        else AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD
        return node.performAction(generic)
    }

    private fun openApp(name: String): String {
        val query = name.trim()
        val before = screen.currentPackage()
        val (intent, label) = specialIntent(query) ?: findLauncherApp(query)
            ?: return "错误：没有找到名为“$query”的应用，可调用 list_apps 查看已安装的应用。"
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_RESET_TASK_IF_NEEDED)
        service.startActivity(intent)

        // New apps take a moment to come to the front; acting before that hits the previous app.
        val target = intent.component?.packageName ?: intent.`package`
        val deadline = System.currentTimeMillis() + APP_WAIT_MS
        while (System.currentTimeMillis() < deadline) {
            Thread.sleep(300)
            val now = screen.currentPackage() ?: continue
            if (if (target != null) now == target else now != before) {
                Thread.sleep(500)
                return "已打开 $label"
            }
        }
        return "已尝试打开 $label，但 ${APP_WAIT_MS / 1000} 秒内它没有出现在前台，请调用 get_screen_elements 检查。"
    }

    private fun specialIntent(query: String): Pair<Intent, String>? {
        val intent = when (query.lowercase()) {
            "设置", "系统设置", "settings" -> Intent(Settings.ACTION_SETTINGS)
            "wifi", "wi-fi", "无线网络", "wlan" -> Intent(Settings.ACTION_WIFI_SETTINGS)
            "蓝牙", "bluetooth" -> Intent(Settings.ACTION_BLUETOOTH_SETTINGS)
            "显示", "显示设置" -> Intent(Settings.ACTION_DISPLAY_SETTINGS)
            "相机", "照相机", "camera" -> Intent(MediaStore.INTENT_ACTION_STILL_IMAGE_CAMERA)
            "电话", "拨号", "phone" -> Intent(Intent.ACTION_DIAL)
            "短信", "信息", "messages" -> Intent.makeMainSelectorActivity(Intent.ACTION_MAIN, Intent.CATEGORY_APP_MESSAGING)
            "联系人", "通讯录", "contacts" -> Intent.makeMainSelectorActivity(Intent.ACTION_MAIN, Intent.CATEGORY_APP_CONTACTS)
            "日历", "calendar" -> Intent.makeMainSelectorActivity(Intent.ACTION_MAIN, Intent.CATEGORY_APP_CALENDAR)
            "相册", "图库", "照片", "gallery" -> Intent.makeMainSelectorActivity(Intent.ACTION_MAIN, Intent.CATEGORY_APP_GALLERY)
            "计算器", "calculator" -> Intent.makeMainSelectorActivity(Intent.ACTION_MAIN, Intent.CATEGORY_APP_CALCULATOR)
            "浏览器", "browser" -> Intent.makeMainSelectorActivity(Intent.ACTION_MAIN, Intent.CATEGORY_APP_BROWSER)
            "地图", "maps" -> Intent.makeMainSelectorActivity(Intent.ACTION_MAIN, Intent.CATEGORY_APP_MAPS)
            "音乐", "music" -> Intent.makeMainSelectorActivity(Intent.ACTION_MAIN, Intent.CATEGORY_APP_MUSIC)
            "邮件", "邮箱", "email" -> Intent.makeMainSelectorActivity(Intent.ACTION_MAIN, Intent.CATEGORY_APP_EMAIL)
            else -> return null
        }
        if (intent.resolveActivity(service.packageManager) == null) return findLauncherApp(query)
        return intent to query
    }

    private data class App(val label: String, val pkg: String, val activity: String)

    private fun launcherApps(): List<App> {
        val pm = service.packageManager
        val main = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
        return pm.queryIntentActivities(main, 0)
            .map { App(it.loadLabel(pm).toString(), it.activityInfo.packageName, it.activityInfo.name) }
            .distinctBy { it.pkg + it.activity }
            .sortedBy { it.label }
    }

    private fun findLauncherApp(query: String): Pair<Intent, String>? {
        val q = query.lowercase()
        val apps = launcherApps()
        val app = apps.firstOrNull { it.label.lowercase() == q }
            ?: apps.firstOrNull { it.label.lowercase().startsWith(q) }
            ?: apps.firstOrNull { q in it.label.lowercase() }
            ?: apps.firstOrNull { it.label.lowercase() in q && it.label.length >= 2 }
            ?: apps.firstOrNull { q in it.pkg.lowercase() }
            ?: return null
        val intent = Intent(Intent.ACTION_MAIN).addCategory(Intent.CATEGORY_LAUNCHER)
            .setClassName(app.pkg, app.activity)
        return intent to app.label
    }

    private fun listApps(keyword: String): String {
        val q = keyword.trim().lowercase()
        val apps = launcherApps().filter { q.isEmpty() || q in it.label.lowercase() || q in it.pkg.lowercase() }
        if (apps.isEmpty()) return "没有找到匹配“$keyword”的应用"
        val shown = apps.take(MAX_APPS).joinToString("\n") { "- ${it.label}（${it.pkg}）" }
        return if (apps.size > MAX_APPS) "$shown\n……共 ${apps.size} 个，可用 keyword 过滤" else shown
    }

    private fun openUrl(raw: String): String {
        val url = if (raw.startsWith("http://") || raw.startsWith("https://")) raw else "https://$raw"
        service.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
        Thread.sleep(2000)
        return "已打开 $url"
    }

    private fun lookAtScreen(question: String): String {
        val client = vision ?: return "错误：未配置视觉模型，请改用 get_screen_elements。"
        val shot = service.screenshotJpeg(MAX_SCREENSHOT_WIDTH)
            ?: return "错误：截图失败（需要 Android 11 及以上），请改用 get_screen_elements。"
        screenshotScale = shot.scale
        val prompt = "这是用户手机的屏幕截图，尺寸 ${shot.width}x${shot.height} 像素。$question\n" +
            "如果涉及要点击的目标，请给出其中心点在这张图片中的像素坐标 (x, y)。"
        return client.describeImage(prompt, shot.base64Jpeg).ifBlank { "（视觉模型无返回）" }
    }

    private fun waitSeconds(seconds: Double): String {
        Thread.sleep((seconds.coerceIn(0.0, 10.0) * 1000).toLong())
        return "已等待 $seconds 秒"
    }

    private fun ancestorOrSelf(node: AccessibilityNodeInfo, test: (AccessibilityNodeInfo) -> Boolean): AccessibilityNodeInfo? {
        var n: AccessibilityNodeInfo? = node
        var depth = 0
        while (n != null && depth < 12) {
            if (test(n)) return n
            n = n.parent
            depth++
        }
        return null
    }

    companion object {
        private const val APP_WAIT_MS = 8000L
        private const val MAX_APPS = 80
        private const val MAX_SCREENSHOT_WIDTH = 1080
        private val DIRECTION_LABELS = mapOf("up" to "上", "down" to "下", "left" to "左", "right" to "右")
        private val KEY_ALIASES = mapOf(
            "返回" to "back", "主页" to "home", "桌面" to "home", "回到桌面" to "home",
            "最近任务" to "recents", "多任务" to "recents", "通知" to "notifications", "通知栏" to "notifications",
            "快捷设置" to "quick_settings", "控制中心" to "quick_settings", "回车" to "enter", "锁屏" to "lock_screen",
        )
    }
}

private fun JSONObject.optIntOrNull(key: String): Int? = if (has(key) && !isNull(key)) optInt(key) else null
