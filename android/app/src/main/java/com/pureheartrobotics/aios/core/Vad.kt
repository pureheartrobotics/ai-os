package com.pureheartrobotics.aios.core

import kotlin.math.max
import kotlin.math.sqrt

/**
 * Energy-based end-of-utterance detection on 30 ms frames of 16 kHz mono PCM, same rules as the
 * Windows build: speech starts after a few loud frames, ends after a stretch of silence.
 */
class Vad(
    private val baseThreshold: Double = 500.0,
    private val silenceMs: Int = 800,
) {
    enum class State { WAITING, SPEAKING, DONE, TIMED_OUT }

    private var noiseFloor: Double? = null
    private val preRoll = ArrayDeque<ShortArray>()
    private val voiced = mutableListOf<ShortArray>()
    private var loudFrames = 0
    private var silence = 0
    private var waitedMs = 0
    private var threshold = baseThreshold

    fun reset() {
        preRoll.clear()
        voiced.clear()
        loudFrames = 0
        silence = 0
        waitedMs = 0
        threshold = currentThreshold()
    }

    /** Feeds one frame; [timeoutMs] bounds how long to wait for speech to begin. */
    fun accept(frame: ShortArray, timeoutMs: Int? = null): State {
        val level = rms(frame)
        if (voiced.isEmpty()) {
            waitedMs += FRAME_MS
            if (timeoutMs != null && waitedMs >= timeoutMs) return State.TIMED_OUT
            preRoll.addLast(frame)
            if (preRoll.size > PRE_ROLL_MS / FRAME_MS) preRoll.removeFirst()
            loudFrames = if (level > threshold) loudFrames + 1 else 0
            if (loudFrames >= MIN_SPEECH_FRAMES) {
                voiced.addAll(preRoll)
                return State.SPEAKING
            }
            // The first loud frames of an utterance must not raise the noise floor above the speech itself.
            if (level <= threshold) {
                trackNoise(level)
                threshold = currentThreshold()
            }
            return State.WAITING
        }

        voiced.add(frame)
        silence = if (level < threshold) silence + FRAME_MS else 0
        return if (silence >= silenceMs || voiced.size * FRAME_MS >= MAX_UTTERANCE_MS) State.DONE else State.SPEAKING
    }

    /** The finished utterance, or null when it was too short to be speech. */
    fun utterance(): ShortArray? {
        val total = voiced.sumOf { it.size }
        if (total < SAMPLE_RATE * MIN_UTTERANCE_MS / 1000) return null
        val out = ShortArray(total)
        var offset = 0
        for (f in voiced) {
            f.copyInto(out, offset)
            offset += f.size
        }
        return out
    }

    private fun trackNoise(level: Double) {
        noiseFloor = noiseFloor?.let { 0.95 * it + 0.05 * level } ?: level
    }

    private fun currentThreshold(): Double = max(baseThreshold, (noiseFloor ?: 0.0) * 3)

    companion object {
        const val SAMPLE_RATE = 16000
        const val FRAME_MS = 30
        const val FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS / 1000
        private const val PRE_ROLL_MS = 300
        private const val MIN_SPEECH_FRAMES = 3
        private const val MIN_UTTERANCE_MS = 400
        private const val MAX_UTTERANCE_MS = 20_000

        fun rms(frame: ShortArray): Double {
            if (frame.isEmpty()) return 0.0
            var sum = 0.0
            for (s in frame) sum += s.toDouble() * s
            return sqrt(sum / frame.size)
        }
    }
}

object Wav {
    fun encode(samples: ShortArray, sampleRate: Int = Vad.SAMPLE_RATE): ByteArray {
        val dataLen = samples.size * 2
        val out = java.nio.ByteBuffer.allocate(44 + dataLen).order(java.nio.ByteOrder.LITTLE_ENDIAN)
        out.put("RIFF".toByteArray(Charsets.US_ASCII)).putInt(36 + dataLen)
        out.put("WAVE".toByteArray(Charsets.US_ASCII))
        out.put("fmt ".toByteArray(Charsets.US_ASCII)).putInt(16)
        out.putShort(1).putShort(1).putInt(sampleRate).putInt(sampleRate * 2).putShort(2).putShort(16)
        out.put("data".toByteArray(Charsets.US_ASCII)).putInt(dataLen)
        for (s in samples) out.putShort(s)
        return out.array()
    }
}
