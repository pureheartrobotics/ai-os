package com.pureheartrobotics.aios

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.graphics.Bitmap
import android.graphics.Path
import android.graphics.Rect
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Base64
import android.util.Log
import android.view.Display
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import com.pureheartrobotics.aios.agent.Agent
import com.pureheartrobotics.aios.agent.DeepSeekSpeech
import com.pureheartrobotics.aios.agent.LlmClient
import com.pureheartrobotics.aios.screen.ScreenReader
import com.pureheartrobotics.aios.tools.Actions
import com.pureheartrobotics.aios.ui.Overlay
import com.pureheartrobotics.aios.voice.Listener
import com.pureheartrobotics.aios.voice.Speaker
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.util.concurrent.CountDownLatch
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit

class AiOsService : AccessibilityService() {
    private val main = Handler(Looper.getMainLooper())
    private lateinit var worker: ExecutorService
    private lateinit var screen: ScreenReader
    private lateinit var overlay: Overlay

    private var agent: Agent? = null
    private var speaker: Speaker? = null
    private var listener: Listener? = null
    private var lastRunAt = 0L

    @Volatile var busy = false
        private set

    override fun onServiceConnected() {
        super.onServiceConnected()
        worker = Executors.newSingleThreadExecutor()
        screen = ScreenReader(this)
        overlay = Overlay(this, onTap = ::onBubbleTap)
        overlay.attach()
        instance = this
        Logbook.add("无障碍服务已连接")
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent) {
        if (event.eventType == AccessibilityEvent.TYPE_WINDOW_STATE_CHANGED) {
            val cls = event.className?.toString() ?: return
            val pkg = event.packageName?.toString() ?: return
            if (cls.startsWith(pkg) || cls.contains("Activity")) screen.lastActivity = cls
        }
    }

    override fun onInterrupt() = stop()

    override fun onDestroy() {
        instance = null
        stop()
        if (::overlay.isInitialized) overlay.detach()
        if (::worker.isInitialized) worker.shutdownNow()
        speaker?.shutdown()
        super.onDestroy()
    }

    /** Runs a typed command (settings page or adb). */
    fun runCommand(command: String) {
        if (command.isBlank()) return
        if (busy) {
            Logbook.add("正在执行上一条指令，已忽略：$command")
            return
        }
        busy = true
        worker.execute {
            try {
                execute(command)
            } finally {
                finishSession()
            }
        }
    }

    /** Tap on the bubble: start a voice session, or stop whatever is running. */
    private fun onBubbleTap() {
        if (busy) {
            stop()
            return
        }
        busy = true
        worker.execute {
            try {
                voiceSession()
            } finally {
                finishSession()
            }
        }
    }

    /** Runs one tool without the model (adb testing); [done] receives the tool's text result on the worker thread. */
    fun runTool(name: String, args: JSONObject, done: (String) -> Unit) {
        if (busy) {
            done("错误：正在执行指令，稍后再试")
            return
        }
        worker.execute {
            val tools = toolActions ?: Actions(this, screen, vision = null, ask = { "" }).also { toolActions = it }
            done(tools.dispatch(name, args))
        }
    }

    private var toolActions: Actions? = null

    fun stop() {
        agent?.cancelled = true
        listener?.cancelled = true
        speaker?.stop()
        setStatus("已停止")
    }

    private fun voiceSession() {
        prepare()
        val ear = listener!!
        var timeout = FIRST_LISTEN_MS
        while (true) {
            setStatus("请说…")
            val heard = try {
                ear.listen(timeout) { setStatus("聆听中…") }
            } catch (e: Exception) {
                Log.w(TAG, "listen failed", e)
                say("麦克风用不了：${e.message}")
                return
            }
            if (heard == null) {
                say("还没有配置 DeepSeek API Key，语音识别用不了。请先在 AI OS 设置页填写。")
                return
            }
            if (heard.isBlank()) {
                if (timeout == FIRST_LISTEN_MS && !ear.cancelled) say("没听清，再点一下悬浮球重新说。")
                return
            }
            execute(heard)
            if (agent?.cancelled == true) return
            // A short window to follow up without tapping again, as on Windows.
            timeout = FOLLOW_UP_MS
        }
    }

    private fun execute(command: String) {
        prepare()
        val a = agent
        if (a == null) {
            say("还没有配置 DeepSeek API Key，请先在 AI OS 设置页填写。")
            return
        }
        if (SystemClock.uptimeMillis() - lastRunAt > CONTEXT_TTL_MS) a.resetConversation()
        Logbook.add("指令：$command")
        val reply = try {
            a.run(command)
        } catch (e: Exception) {
            Log.e(TAG, "agent failed", e)
            "出错了：${e.message?.take(80)}"
        }
        lastRunAt = SystemClock.uptimeMillis()
        Logbook.add("结果：$reply")
        say(reply)
    }

    /** Builds the agent and voice clients from the current settings, keeping the conversation if nothing changed. */
    private fun prepare() {
        val cfg = Config.load(this)
        val stamp = cfg.hashCode()
        if (stamp == configStamp && agent != null) return
        configStamp = stamp
        speaker?.shutdown()
        val speech = if (cfg.apiKey.isNotEmpty() && cfg.cloudVoice) DeepSeekSpeech(DEEPSEEK_BASE_URL, cfg.apiKey, cfg.ttsVoice) else null
        speaker = Speaker(this, speech)
        listener = Listener(speech)
        if (cfg.apiKey.isEmpty()) {
            agent = null
            return
        }
        val thinking = if (cfg.isDeepSeek && cfg.thinking != "disabled") cfg.thinking else null
        val llm = LlmClient(cfg.baseUrl, cfg.apiKey, cfg.model, thinking)
        val vision = if (cfg.visionModel.isNotEmpty()) LlmClient(cfg.visionBaseUrl, cfg.visionApiKey, cfg.visionModel) else null
        val actions = Actions(this, screen, vision, ask = ::askUser)
        agent = Agent(llm, actions, screen, cfg.maxSteps, ::setStatus)
    }

    private var configStamp = 0

    private fun askUser(question: String): String {
        say(question)
        setStatus("请回答…")
        return try {
            listener?.listen(ANSWER_MS) { setStatus("聆听中…") } ?: ""
        } catch (e: Exception) {
            ""
        }
    }

    private fun say(text: String) {
        setStatus(text)
        speaker?.say(text)
    }

    private fun finishSession() {
        busy = false
        main.post { overlay.idle() }
    }

    private fun setStatus(text: String) {
        main.post { overlay.status(text) }
    }

    // ---- primitives used by Actions; call from the worker thread only ----

    fun tap(x: Int, y: Int, durationMs: Long): Boolean {
        val path = Path().apply { moveTo(x.toFloat(), y.toFloat()) }
        return gesture(path, durationMs)
    }

    /** Swipes inside [node]'s bounds (or the whole screen) so that content moves toward [direction]. */
    fun swipe(direction: String, node: AccessibilityNodeInfo?): Boolean {
        val r = Rect()
        if (node != null) node.getBoundsInScreen(r) else {
            val m = resources.displayMetrics
            r.set(0, 0, m.widthPixels, m.heightPixels)
        }
        val cx = r.exactCenterX()
        val cy = r.exactCenterY()
        val dx = r.width() * 0.3f
        val dy = r.height() * 0.3f
        val path = Path()
        when (direction) {
            "down" -> { path.moveTo(cx, cy + dy); path.lineTo(cx, cy - dy) }
            "up" -> { path.moveTo(cx, cy - dy); path.lineTo(cx, cy + dy) }
            "right" -> { path.moveTo(cx + dx, cy); path.lineTo(cx - dx, cy) }
            else -> { path.moveTo(cx - dx, cy); path.lineTo(cx + dx, cy) }
        }
        return gesture(path, 350L)
    }

    private fun gesture(path: Path, durationMs: Long): Boolean {
        val description = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, durationMs))
            .build()
        val latch = CountDownLatch(1)
        var completed = false
        val dispatched = dispatchGesture(description, object : GestureResultCallback() {
            override fun onCompleted(gestureDescription: GestureDescription?) {
                completed = true
                latch.countDown()
            }

            override fun onCancelled(gestureDescription: GestureDescription?) = latch.countDown()
        }, null)
        if (!dispatched) return false
        latch.await(durationMs + 3000, TimeUnit.MILLISECONDS)
        return completed
    }

    data class Shot(val base64Jpeg: String, val width: Int, val height: Int, val scale: Double)

    fun screenshotJpeg(maxWidth: Int): Shot? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.R) return null
        val latch = CountDownLatch(1)
        var bitmap: Bitmap? = null
        takeScreenshot(Display.DEFAULT_DISPLAY, mainExecutor, object : TakeScreenshotCallback {
            override fun onSuccess(result: ScreenshotResult) {
                val hw = Bitmap.wrapHardwareBuffer(result.hardwareBuffer, result.colorSpace)
                bitmap = hw?.copy(Bitmap.Config.ARGB_8888, false)
                result.hardwareBuffer.close()
                latch.countDown()
            }

            override fun onFailure(errorCode: Int) {
                Log.w(TAG, "screenshot failed: $errorCode")
                latch.countDown()
            }
        })
        latch.await(5, TimeUnit.SECONDS)
        val full = bitmap ?: return null
        val scale = if (full.width > maxWidth) maxWidth.toDouble() / full.width else 1.0
        val img = if (scale < 1.0) Bitmap.createScaledBitmap(full, maxWidth, (full.height * scale).toInt(), true) else full
        val bytes = ByteArrayOutputStream().use {
            img.compress(Bitmap.CompressFormat.JPEG, 80, it)
            it.toByteArray()
        }
        return Shot(Base64.encodeToString(bytes, Base64.NO_WRAP), img.width, img.height, scale)
    }

    companion object {
        private const val TAG = "AiOs"
        private const val FIRST_LISTEN_MS = 8000
        private const val FOLLOW_UP_MS = 6000
        private const val ANSWER_MS = 10000
        private const val CONTEXT_TTL_MS = 3 * 60 * 1000L

        @Volatile var instance: AiOsService? = null
            private set
    }
}
