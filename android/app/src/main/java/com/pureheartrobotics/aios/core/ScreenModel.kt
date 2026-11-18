package com.pureheartrobotics.aios.core

/** One control as read from the platform, before it gets an id. [handle] is opaque to the model. */
data class RawNode(
    val kind: String,
    val name: String,
    val left: Int,
    val top: Int,
    val right: Int,
    val bottom: Int,
    val flags: List<String> = emptyList(),
    val handle: Any? = null,
)

/**
 * Web pages expose a button and its label as separate nodes ("Button 7" and "Text 7").
 * Drops a Text or Image whose name equals that of a control containing its center.
 */
fun dropRedundantLabels(nodes: List<RawNode>): List<RawNode> {
    val controls = nodes.filter { it.kind != "Text" && it.kind != "Image" && it.name.isNotEmpty() }
    if (controls.isEmpty()) return nodes
    val byName = controls.groupBy { it.name }
    return nodes.filterNot { n ->
        if (n.kind != "Text" && n.kind != "Image") return@filterNot false
        val cx = (n.left + n.right) / 2
        val cy = (n.top + n.bottom) / 2
        byName[n.name]?.any { c -> cx in c.left..c.right && cy in c.top..c.bottom } == true
    }
}

data class Element(
    val id: Int,
    val kind: String,
    val name: String,
    val x: Int,
    val y: Int,
    val left: Int,
    val top: Int,
    val right: Int,
    val bottom: Int,
    val flags: List<String>,
    val handle: Any?,
) {
    val area: Long get() = (right - left).toLong() * (bottom - top).toLong()

    fun describe(): String {
        val head = if (name.isEmpty()) "[$id] $kind" else "[$id] $kind $name"
        return if (flags.isEmpty()) head else "$head（${flags.joinToString("，")}）"
    }
}

/**
 * Numbers the controls of the foreground app.
 *
 * Ids are stable while the same app stays in front: a control keeps its id across reads, so a caller
 * that keeps earlier listings in context can be sent only what changed.
 */
class ScreenModel(private val maxElements: Int = 150) {
    data class Update(
        val windowChanged: Boolean,
        val added: List<Int>,
        val removed: List<Int>,
        val changed: List<Int>,
    ) {
        val isEmpty: Boolean get() = added.isEmpty() && removed.isEmpty() && changed.isEmpty()
    }

    private data class Key(val kind: String, val name: String, val x: Int, val y: Int)

    private var windowKey: String? = null
    private val ids = HashMap<Key, Int>()
    private var nextId = 1

    var title: String = ""
        private set
    var truncated: Boolean = false
        private set
    var elements: Map<Int, Element> = emptyMap()
        private set

    fun update(windowKey: String, title: String, nodes: List<RawNode>): Update {
        val windowChanged = windowKey != this.windowKey
        if (windowChanged) {
            this.windowKey = windowKey
            ids.clear()
            nextId = 1
            elements = emptyMap()
        }
        this.title = title
        truncated = nodes.size > maxElements

        val previous = elements
        val kept = nodes.take(maxElements)
        val keys = kept.map { Key(it.kind, it.name, (it.left + it.right) / 2, (it.top + it.bottom) / 2) }
        val moved = movedIds(previous, keys)

        val next = LinkedHashMap<Int, Element>()
        for ((i, n) in kept.withIndex()) {
            val key = keys[i]
            val id = ids[key] ?: moved[i]?.also { ids[key] = it } ?: (nextId++).also { ids[key] = it }
            if (id in next) continue
            next[id] = Element(id, n.kind, n.name, key.x, key.y, n.left, n.top, n.right, n.bottom, n.flags, n.handle)
        }
        elements = next

        return Update(
            windowChanged = windowChanged,
            added = next.keys.filter { it !in previous }.sorted(),
            removed = previous.keys.filter { it !in next }.sorted(),
            changed = next.keys.filter { it in previous && previous.getValue(it).flags != next.getValue(it).flags }.sorted(),
        )
    }

    fun fullListing(): String {
        val lines = mutableListOf("前台: $title")
        elements.values.mapTo(lines) { it.describe() }
        if (truncated) lines += TRUNCATED_NOTE
        return lines.joinToString("\n")
    }

    /**
     * Scrolling moves every control, so position-based keys miss. A named control whose kind and name are
     * unique both in the previous read and among the unmatched new nodes keeps its old id.
     */
    private fun movedIds(previous: Map<Int, Element>, keys: List<Key>): Map<Int, Int> {
        val unmatched = keys.withIndex().filter { (_, k) -> k.name.isNotEmpty() && k !in ids }
        val taken = keys.mapNotNullTo(HashSet()) { ids[it] }
        val candidates = previous.values.filter { it.id !in taken }.groupBy { it.kind to it.name }
        val result = HashMap<Int, Int>()
        for ((group, nodes) in unmatched.groupBy { (_, k) -> k.kind to k.name }) {
            val old = candidates[group] ?: continue
            if (old.size == 1 && nodes.size == 1) result[nodes[0].index] = old[0].id
        }
        return result
    }

    fun changesText(update: Update): String {
        if (update.windowChanged) return "前台应用已切换。\n" + fullListing()
        if (update.isEmpty) return "前台: $title（控件无变化）"
        // A new page inside the same app replaces most controls; a full listing reads better than a diff.
        if (elements.size > 8 && update.added.size * 10 >= elements.size * 6) return "界面已大幅变化。\n" + fullListing()

        val lines = mutableListOf("前台: $title")
        if (update.added.isNotEmpty()) {
            lines += "新增 ${update.added.size} 个控件:"
            update.added.mapTo(lines) { elements.getValue(it).describe() }
        }
        if (update.changed.isNotEmpty()) {
            lines += "状态变化:"
            update.changed.mapTo(lines) { elements.getValue(it).describe() }
        }
        if (update.removed.isNotEmpty()) {
            lines += "消失 ${update.removed.size} 个控件: " + update.removed.joinToString(",")
        }
        if (truncated) lines += TRUNCATED_NOTE
        return lines.joinToString("\n")
    }

    companion object {
        const val TRUNCATED_NOTE = "（控件过多，列表已截断；可以先滚动，或使用 look_at_screen）"
    }
}
