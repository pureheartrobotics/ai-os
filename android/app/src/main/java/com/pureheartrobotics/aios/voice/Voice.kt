package com.pureheartrobotics.aios.voice

import android.annotation.SuppressLint
import android.content.Context
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaPlayer
import android.media.MediaRecorder
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Log
import com.pureheartrobotics.aios.agent.DeepSeekSpeech
import com.pureheartrobotics.aios.core.Vad
import com.pureheartrobotics.aios.core.Wav
import java.io.File
import java.util.Locale
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

private const val TAG = "AiOs"

// Whisper-style models tend to emit these on silence or noise.
private val HALLUCINATIONS = listOf("谢谢观看", "字幕", "点赞", "订阅", "明镜", "请不吝")

/** Records one utterance and transcribes it. Requires RECORD_AUDIO. */
class Listener(private val speech: DeepSeekSpeech?) {
    @Volatile var cancelled = false

    /** Returns recognized text, "" when nothing usable was heard, or null when speech is not configured. */
    @SuppressLint("MissingPermission")
    fun listen(timeoutMs: Int, onSpeech: () -> Unit = {}): String? {
        val client = speech ?: return null
        cancelled = false
        val minBuf = AudioRecord.getMinBufferSize(Vad.SAMPLE_RATE, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        val record = AudioRecord(MediaRecorder.AudioSource.VOICE_RECOGNITION, Vad.SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT, maxOf(minBuf, Vad.FRAME_SAMPLES * 8))
        if (record.state != AudioRecord.STATE_INITIALIZED) {
            record.release()
            throw IllegalStateException("麦克风不可用")
        }
        val vad = Vad()
        val frame = ShortArray(Vad.FRAME_SAMPLES)
        var spoke = false
        try {
            record.startRecording()
            while (!cancelled) {
                var read = 0
                while (read < frame.size) {
                    val n = record.read(frame, read, frame.size - read)
                    if (n <= 0) throw IllegalStateException("读取麦克风失败：$n")
                    read += n
                }
                when (vad.accept(frame.copyOf(), timeoutMs)) {
                    Vad.State.SPEAKING -> if (!spoke) { spoke = true; onSpeech() }
                    Vad.State.DONE -> break
                    Vad.State.TIMED_OUT -> return ""
                    Vad.State.WAITING -> {}
                }
            }
        } finally {
            record.stop()
            record.release()
        }
        if (cancelled) return ""
        val samples = vad.utterance() ?: return ""
        val text = client.transcribe(Wav.encode(samples))
        Log.i(TAG, "[识别] $text")
        return if (HALLUCINATIONS.any { it in text }) "" else text
    }
}

/** Speaks replies with DeepSeek TTS when configured, otherwise with the system engine. */
class Speaker(context: Context, private val speech: DeepSeekSpeech?) {
    private val cacheDir = context.cacheDir
    private var player: MediaPlayer? = null
    private val ttsReady = CountDownLatch(1)
    private var ttsOk = false
    private val tts = TextToSpeech(context.applicationContext) { status ->
        ttsOk = status == TextToSpeech.SUCCESS
        ttsReady.countDown()
    }

    @Volatile private var stopped = false

    /** Blocks until done speaking or [stop] is called. */
    fun say(text: String) {
        if (text.isBlank()) return
        stopped = false
        Log.i(TAG, "[朗读] $text")
        if (speech != null) {
            try {
                playWav(speech.synthesize(text))
                return
            } catch (e: Exception) {
                Log.w(TAG, "DeepSeek 朗读失败，改用系统语音：${e.message}")
            }
        }
        if (!stopped) systemSay(text)
    }

    fun stop() {
        stopped = true
        player?.runCatching { stop() }
        tts.stop()
    }

    fun shutdown() {
        stop()
        tts.shutdown()
    }

    private fun playWav(wav: ByteArray) {
        val file = File(cacheDir, "reply.wav").apply { writeBytes(wav) }
        val done = CountDownLatch(1)
        val mp = MediaPlayer().apply {
            setAudioAttributes(AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ASSISTANT)
                .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH).build())
            setDataSource(file.absolutePath)
            setOnCompletionListener { done.countDown() }
            setOnErrorListener { _, _, _ -> done.countDown(); true }
            prepare()
        }
        player = mp
        try {
            mp.start()
            while (!stopped && !done.await(100, TimeUnit.MILLISECONDS)) Unit
        } finally {
            mp.release()
            player = null
        }
    }

    private fun systemSay(text: String) {
        if (!ttsReady.await(3, TimeUnit.SECONDS) || !ttsOk) return
        tts.language = Locale.SIMPLIFIED_CHINESE
        val done = CountDownLatch(1)
        tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(id: String?) {}
            override fun onDone(id: String?) = done.countDown()
            @Deprecated("Deprecated in Java")
            override fun onError(id: String?) = done.countDown()
        })
        tts.speak(text, TextToSpeech.QUEUE_FLUSH, null, "reply")
        val deadline = System.currentTimeMillis() + 30_000
        while (!stopped && System.currentTimeMillis() < deadline && !done.await(100, TimeUnit.MILLISECONDS)) Unit
    }
}
