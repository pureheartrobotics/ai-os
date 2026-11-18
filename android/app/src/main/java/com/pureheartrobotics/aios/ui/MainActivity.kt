package com.pureheartrobotics.aios.ui

import android.Manifest
import android.app.Activity
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.widget.Button
import android.widget.CheckBox
import android.widget.EditText
import android.widget.TextView
import android.widget.Toast
import com.pureheartrobotics.aios.AiOsService
import com.pureheartrobotics.aios.Config
import com.pureheartrobotics.aios.DEEPSEEK_BASE_URL
import com.pureheartrobotics.aios.Logbook
import com.pureheartrobotics.aios.R

class MainActivity : Activity() {
    private lateinit var serviceStatus: TextView
    private lateinit var micStatus: TextView
    private lateinit var log: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)
        serviceStatus = findViewById(R.id.serviceStatus)
        micStatus = findViewById(R.id.micStatus)
        log = findViewById(R.id.log)

        val apiKey = findViewById<EditText>(R.id.apiKey)
        val baseUrl = findViewById<EditText>(R.id.baseUrl)
        val model = findViewById<EditText>(R.id.model)
        val visionModel = findViewById<EditText>(R.id.visionModel)
        val cloudVoice = findViewById<CheckBox>(R.id.cloudVoice)
        val cfg = Config.load(this)
        apiKey.setText(cfg.apiKey)
        if (cfg.baseUrl != DEEPSEEK_BASE_URL) baseUrl.setText(cfg.baseUrl)
        if (cfg.model != "deepseek-flash") model.setText(cfg.model)
        visionModel.setText(cfg.visionModel)
        cloudVoice.isChecked = cfg.cloudVoice

        findViewById<Button>(R.id.openAccessibility).setOnClickListener {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        }
        findViewById<Button>(R.id.grantMic).setOnClickListener {
            requestPermissions(arrayOf(Manifest.permission.RECORD_AUDIO), 1)
        }
        findViewById<Button>(R.id.save).setOnClickListener {
            Config.save(this, apiKey.text.toString(), baseUrl.text.toString(), model.text.toString(),
                visionModel.text.toString(), cloudVoice.isChecked)
            Toast.makeText(this, "已保存", Toast.LENGTH_SHORT).show()
        }
        val command = findViewById<EditText>(R.id.command)
        findViewById<Button>(R.id.run).setOnClickListener {
            val service = AiOsService.instance
            val text = command.text.toString().trim()
            when {
                service == null -> Toast.makeText(this, "请先开启 AI OS 的无障碍服务", Toast.LENGTH_SHORT).show()
                text.isEmpty() -> Toast.makeText(this, "请输入指令", Toast.LENGTH_SHORT).show()
                else -> {
                    // Leave this page first so the agent starts from what the user was looking at.
                    moveTaskToBack(true)
                    Handler(Looper.getMainLooper()).postDelayed({ service.runCommand(text) }, 600)
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        refreshStatus()
        Logbook.onChange = { log.text = Logbook.text() }
        log.text = Logbook.text()
    }

    private fun refreshStatus() {
        val on = AiOsService.instance != null
        serviceStatus.text = if (on) "无障碍服务：已开启（屏幕边上有蓝色悬浮球）" else "无障碍服务：未开启"
        findViewById<Button>(R.id.openAccessibility).isEnabled = !on
        val mic = checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
        micStatus.text = if (mic) "麦克风：已允许" else "麦克风：未允许（语音指令需要）"
        findViewById<Button>(R.id.grantMic).isEnabled = !mic
    }

    override fun onPause() {
        Logbook.onChange = null
        super.onPause()
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        refreshStatus()
    }
}
