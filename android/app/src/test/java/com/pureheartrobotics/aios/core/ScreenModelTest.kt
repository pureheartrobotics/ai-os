package com.pureheartrobotics.aios.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ScreenModelTest {
    private fun node(kind: String, name: String, x: Int, y: Int, flags: List<String> = emptyList()) =
        RawNode(kind, name, x - 10, y - 10, x + 10, y + 10, flags)

    @Test
    fun idsStayStableWithinTheSameApp() {
        val model = ScreenModel()
        model.update("com.android.settings", "设置", listOf(node("Button", "网络", 100, 100), node("Button", "显示", 100, 200)))
        val first = model.elements.values.associate { it.name to it.id }

        val update = model.update("com.android.settings", "设置",
            listOf(node("Button", "蓝牙", 100, 50), node("Button", "网络", 100, 100), node("Button", "显示", 100, 200)))

        val second = model.elements.values.associate { it.name to it.id }
        assertEquals(first["网络"], second["网络"])
        assertEquals(first["显示"], second["显示"])
        assertEquals(listOf(second.getValue("蓝牙")), update.added)
        assertTrue(update.removed.isEmpty())
    }

    @Test
    fun webLabelsInsideTheirButtonsAreDropped() {
        val nodes = listOf(
            node("Text", "7", 100, 100), node("Button", "7", 100, 100),
            node("Text", "7", 500, 500),
            node("Text", "结果 5888", 100, 300),
        )
        val kept = dropRedundantLabels(nodes)
        assertEquals(listOf("Button" to "7", "Text" to "7", "Text" to "结果 5888"), kept.map { it.kind to it.name })
    }

    @Test
    fun scrolledControlsKeepTheirIds() {
        val model = ScreenModel()
        model.update("s", "设置", listOf(node("Button", "网络", 100, 100), node("Button", "蓝牙", 100, 200), node("Button", "显示", 100, 300)))
        val before = model.elements.values.associate { it.name to it.id }

        val update = model.update("s", "设置", listOf(node("Button", "蓝牙", 100, 80), node("Button", "显示", 100, 180), node("Button", "声音", 100, 280)))

        val after = model.elements.values.associate { it.name to it.id }
        assertEquals(before["蓝牙"], after["蓝牙"])
        assertEquals(before["显示"], after["显示"])
        assertEquals(180, model.elements.getValue(after.getValue("显示")).y)
        assertEquals(listOf(after.getValue("声音")), update.added)
        assertEquals(listOf(before.getValue("网络")), update.removed)
    }

    @Test
    fun ambiguousNamesAreNotCarriedAcrossMoves() {
        val model = ScreenModel()
        model.update("s", "列表", listOf(node("Button", "删除", 100, 100), node("Button", "删除", 100, 200)))
        val before = model.elements.keys

        model.update("s", "列表", listOf(node("Button", "删除", 100, 150), node("Button", "删除", 100, 250)))

        assertTrue(model.elements.keys.none { it in before })
    }

    @Test
    fun switchingAppsRestartsNumberingAndListsEverything() {
        val model = ScreenModel()
        model.update("a", "A", listOf(node("Button", "x", 1, 1), node("Button", "y", 2, 2)))
        val update = model.update("b", "B", listOf(node("Text", "hello", 5, 5)))

        assertTrue(update.windowChanged)
        assertEquals(listOf(1), model.elements.keys.toList())
        assertTrue(model.changesText(update).startsWith("前台应用已切换。"))
    }

    @Test
    fun toggledSwitchIsReportedAsStateChange() {
        val model = ScreenModel()
        model.update("s", "设置", listOf(node("Switch", "深色模式", 50, 50, listOf("未选中"))))
        val update = model.update("s", "设置", listOf(node("Switch", "深色模式", 50, 50, listOf("已选中"))))

        assertEquals(listOf(1), update.changed)
        val text = model.changesText(update)
        assertTrue(text, text.contains("状态变化:\n[1] Switch 深色模式（已选中）"))
    }

    @Test
    fun removedControlsAreListedById() {
        val model = ScreenModel()
        model.update("s", "t", listOf(node("Button", "确定", 1, 1), node("Button", "取消", 2, 2)))
        val update = model.update("s", "t", listOf(node("Button", "确定", 1, 1)))

        assertEquals(listOf(2), update.removed)
        assertTrue(model.changesText(update).contains("消失 1 个控件: 2"))
    }

    @Test
    fun mostlyNewPageFallsBackToFullListing() {
        val model = ScreenModel()
        model.update("s", "t", (1..10).map { node("Text", "旧$it", 10, it * 30) })
        val update = model.update("s", "t", (1..10).map { node("Text", "新$it", 10, it * 30) })

        assertTrue(model.changesText(update).startsWith("界面已大幅变化。"))
    }

    @Test
    fun listingIsTruncatedAtTheLimit() {
        val model = ScreenModel(maxElements = 3)
        model.update("s", "t", (1..5).map { node("Text", "$it", 10, it * 30) })

        assertEquals(3, model.elements.size)
        assertTrue(model.fullListing().endsWith(ScreenModel.TRUNCATED_NOTE))
    }

    @Test
    fun noChangeIsSaidPlainly() {
        val model = ScreenModel()
        val nodes = listOf(node("Button", "确定", 1, 1))
        model.update("s", "相机", nodes)
        assertEquals("前台: 相机（控件无变化）", model.changesText(model.update("s", "相机", nodes)))
    }
}
