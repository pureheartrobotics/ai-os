package com.pureheartrobotics.aios

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import org.json.JSONObject

/**
 * adb entry point for testing:
 *   adb shell am broadcast -a com.pureheartrobotics.aios.RUN --es command "打开设置"
 *   adb shell am broadcast -a com.pureheartrobotics.aios.STOP
 *   adb shell am broadcast -a com.pureheartrobotics.aios.TOOL --es name click_element --es args '{"id":3}'
 * TOOL prints the tool result as the broadcast's result data.
 */
class CommandReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val service = AiOsService.instance
        if (service == null) {
            Logbook.add("收到 adb 指令，但无障碍服务未开启")
            resultData = "错误：无障碍服务未开启"
            return
        }
        when (intent.action) {
            "com.pureheartrobotics.aios.RUN" -> service.runCommand(intent.getStringExtra("command").orEmpty())
            "com.pureheartrobotics.aios.STOP" -> service.stop()
            "com.pureheartrobotics.aios.TOOL" -> {
                val args = try {
                    JSONObject(intent.getStringExtra("args") ?: "{}")
                } catch (e: Exception) {
                    resultData = "错误：args 不是合法 JSON"
                    return
                }
                val pending = goAsync()
                service.runTool(intent.getStringExtra("name").orEmpty(), args) { result ->
                    pending.resultData = result
                    pending.finish()
                }
            }
        }
    }
}
