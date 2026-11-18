package com.pureheartrobotics.aios.screen

import android.accessibilityservice.AccessibilityService
import android.content.pm.PackageManager
import android.graphics.Rect
import android.os.SystemClock
import android.view.accessibility.AccessibilityNodeInfo
import android.view.accessibility.AccessibilityWindowInfo
import com.pureheartrobotics.aios.core.Element
import com.pureheartrobotics.aios.core.RawNode
import com.pureheartrobotics.aios.core.ScreenModel
import com.pureheartrobotics.aios.core.dropRedundantLabels

/** Reads the accessibility tree of the windows on screen into a [ScreenModel]. */
class ScreenReader(private val service: AccessibilityService) {
    private val model = ScreenModel()
    private val labels = HashMap<String, String>()

    val elements: Map<Int, Element> get() = model.elements

    /** Last activity class reported by a window-state event, used only to make titles readable. */
    @Volatile var lastActivity: String = ""

    fun snapshot(): String = if (refresh() == null) UNAVAILABLE else model.fullListing()

    fun changes(): String = refresh()?.let { model.changesText(it) } ?: UNAVAILABLE

    fun currentPackage(): String? = activeRoot()?.packageName?.toString()

    fun activeRoot(): AccessibilityNodeInfo? =
        service.rootInActiveWindow ?: appWindows().firstOrNull()?.root

    /** The focused input field on screen, if any. */
    fun focusedInput(): AccessibilityNodeInfo? {
        val roots = listOfNotNull(service.rootInActiveWindow) + appWindows().mapNotNull { it.root }
        // Input focus can sit on a button of the page being left; only an editable node is a target for text.
        return roots.firstNotNullOfOrNull { root ->
            root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)?.takeIf { it.isEditable }
        }
    }

    /** The first visible editable field under [root] (default: all app windows); does not touch the numbered model. */
    fun firstEditable(root: AccessibilityNodeInfo? = null): AccessibilityNodeInfo? {
        fun find(node: AccessibilityNodeInfo, depth: Int): AccessibilityNodeInfo? {
            if (depth > MAX_DEPTH || !node.isVisibleToUser) return null
            if (node.isEditable) return node
            for (i in 0 until node.childCount) node.getChild(i)?.let { child -> find(child, depth + 1)?.let { return it } }
            return null
        }
        if (root != null) return find(root, 0)
        return appWindows().firstNotNullOfOrNull { w -> w.root?.let { find(it, 0) } }
    }

    private fun refresh(): ScreenModel.Update? {
        val active = activeRoot() ?: return null
        val pkg = active.packageName?.toString() ?: "unknown"
        val nodes = mutableListOf<RawNode>()
        val deadline = SystemClock.uptimeMillis() + TIME_BUDGET_MS
        val roots = appWindows().mapNotNull { it.root }.ifEmpty { listOf(active) }
        for (root in roots) walk(root, 0, nodes, insideNamedClickable = false, clickableName = "", deadline = deadline)
        return model.update(pkg, title(pkg), dropRedundantLabels(nodes))
    }

    /**
     * Application and system windows that occupy real screen space. The status and navigation bars,
     * the keyboard and our own overlay are left out.
     */
    private fun appWindows(): List<AccessibilityWindowInfo> {
        val screen = service.resources.displayMetrics
        val minHeight = screen.heightPixels / 4
        val bounds = Rect()
        return service.windows.filter { w ->
            when (w.type) {
                AccessibilityWindowInfo.TYPE_APPLICATION -> true
                AccessibilityWindowInfo.TYPE_SYSTEM -> {
                    w.getBoundsInScreen(bounds)
                    bounds.height() >= minHeight
                }
                else -> false
            }
        }
    }

    private fun walk(node: AccessibilityNodeInfo, depth: Int, out: MutableList<RawNode>,
                     insideNamedClickable: Boolean, clickableName: String, deadline: Long) {
        if (depth > MAX_DEPTH || out.size > MAX_NODES || SystemClock.uptimeMillis() > deadline) return
        if (!node.isVisibleToUser) return
        val rect = Rect()
        node.getBoundsInScreen(rect)
        if (rect.width() <= 0 || rect.height() <= 0) return

        val kind = kindOf(node)
        var name = if (node.isPassword) "" else clean(node.text).ifEmpty { clean(node.contentDescription) }
        if (name.isEmpty() && kind == "Edit") name = clean(node.hintText)
        var consumesChildren = false
        val clickable = node.isClickable || node.isLongClickable
        if (name.isEmpty() && clickable && kind != "Edit") {
            name = childTexts(node)
            consumesChildren = name.isNotEmpty()
        }
        if (name.isEmpty() && clickable) name = node.viewIdResourceName?.substringAfterLast('/')?.let { "id/$it" } ?: ""

        val listed = when (kind) {
            null -> false
            // A tile such as "Bluetooth, On" repeats its child labels; listing them again only adds noise.
            "Text", "Image" -> name.isNotEmpty() && !insideNamedClickable && name !in clickableName
            else -> true
        }
        if (listed) out += RawNode(kind!!, name, rect.left, rect.top, rect.right, rect.bottom, flagsOf(node, kind), node)

        val childInside = insideNamedClickable || consumesChildren
        val childClickableName = if (clickable && name.isNotEmpty()) name else clickableName
        for (i in 0 until node.childCount) {
            val child = node.getChild(i) ?: continue
            walk(child, depth + 1, out, childInside, childClickableName, deadline)
        }
    }

    private fun kindOf(node: AccessibilityNodeInfo): String? {
        val cls = node.className?.toString() ?: ""
        return when {
            node.isEditable || cls.endsWith("EditText") -> "Edit"
            cls.endsWith("Switch") || cls.endsWith("ToggleButton") -> "Switch"
            cls.endsWith("CheckBox") -> "CheckBox"
            cls.endsWith("RadioButton") -> "Radio"
            cls.endsWith("SeekBar") -> "Slider"
            node.isCheckable -> "CheckBox"
            node.isScrollable -> "List"
            node.isClickable || node.isLongClickable -> "Button"
            cls.endsWith("ImageView") -> "Image"
            cls.endsWith("TextView") || !node.text.isNullOrBlank() -> "Text"
            else -> null
        }
    }

    private fun flagsOf(node: AccessibilityNodeInfo, kind: String): List<String> {
        val flags = mutableListOf<String>()
        if (node.isCheckable) flags += if (node.isChecked) "已选中" else "未选中"
        // Plain text views report selected for marquee scrolling; only tabs and buttons mean it.
        else if (node.isSelected && kind == "Button") flags += "已选中"
        if (!node.isEnabled) flags += "不可用"
        if (node.isScrollable) flags += "可滚动"
        if (node.isEditable && node.isFocused) flags += "输入焦点"
        if (node.isPassword) flags += if (node.text.isNullOrEmpty()) "密码" else "密码，已填写"
        return flags
    }

    /** Text of non-clickable descendants, which is how list rows and cards usually carry their label. */
    private fun childTexts(node: AccessibilityNodeInfo): String {
        val parts = mutableListOf<String>()
        fun collect(n: AccessibilityNodeInfo, depth: Int) {
            if (parts.size >= 3 || depth > 6) return
            for (i in 0 until n.childCount) {
                val c = n.getChild(i) ?: continue
                if (!c.isVisibleToUser) continue
                val t = clean(c.text).ifEmpty { clean(c.contentDescription) }
                if (t.isNotEmpty()) parts += t
                if (!c.isClickable) collect(c, depth + 1)
                if (parts.size >= 3) return
            }
        }
        collect(node, 0)
        return parts.joinToString("，").let { if (it.length > MAX_NAME) it.take(MAX_NAME) + "…" else it }
    }

    private fun title(pkg: String): String {
        val label = labels.getOrPut(pkg) {
            try {
                val pm = service.packageManager
                pm.getApplicationLabel(pm.getApplicationInfo(pkg, 0)).toString()
            } catch (_: PackageManager.NameNotFoundException) {
                pkg
            }
        }
        val activity = lastActivity.substringAfterLast('.')
        if (activity.isNotEmpty() && lastActivity.startsWith(pkg)) return "$label · $activity"
        return if (label == pkg) pkg else "$label（$pkg）"
    }

    companion object {
        const val UNAVAILABLE = "（无法读取当前界面：屏幕可能已熄灭或锁定，或 AI OS 的无障碍服务未开启）"
        private const val MAX_DEPTH = 40
        private const val MAX_NODES = 400
        private const val MAX_NAME = 40
        private const val TIME_BUDGET_MS = 2500L
        private val INVISIBLE = Regex("[\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff\ue000-\uf8ff]")

        fun clean(text: CharSequence?): String {
            if (text == null) return ""
            val s = INVISIBLE.replace(text.toString(), "").replace('\n', ' ').trim()
            return if (s.length > MAX_NAME) s.take(MAX_NAME) + "…" else s
        }
    }
}
