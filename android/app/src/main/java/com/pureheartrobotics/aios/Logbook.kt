package com.pureheartrobotics.aios

import android.os.Handler
import android.os.Looper
import android.util.Log
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Recent events shown on the settings page. */
object Logbook {
    private const val MAX = 50
    private val lines = ArrayDeque<String>()
    private val main = Handler(Looper.getMainLooper())
    private val time = SimpleDateFormat("HH:mm:ss", Locale.US)

    @Volatile var onChange: (() -> Unit)? = null

    @Synchronized
    fun add(line: String) {
        Log.i("AiOs", line)
        lines.addLast("${time.format(Date())}  $line")
        while (lines.size > MAX) lines.removeFirst()
        main.post { onChange?.invoke() }
    }

    @Synchronized
    fun text(): String = lines.reversed().joinToString("\n")
}
