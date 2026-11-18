package com.pureheartrobotics.aios.core

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Test

class VadTest {
    private fun frame(amplitude: Int) = ShortArray(Vad.FRAME_SAMPLES) { if (it % 2 == 0) amplitude.toShort() else (-amplitude).toShort() }

    private fun feed(vad: Vad, frames: List<ShortArray>, timeoutMs: Int? = null): Vad.State {
        var state = Vad.State.WAITING
        for (f in frames) {
            state = vad.accept(f, timeoutMs)
            if (state == Vad.State.DONE || state == Vad.State.TIMED_OUT) break
        }
        return state
    }

    @Test
    fun speechFollowedBySilenceEndsTheUtterance() {
        val vad = Vad()
        val frames = List(10) { frame(20) } + List(30) { frame(3000) } + List(40) { frame(20) }
        assertEquals(Vad.State.DONE, feed(vad, frames))
        assertNotNull(vad.utterance())
    }

    @Test
    fun aClickIsNotSpeech() {
        val vad = Vad()
        val frames = List(10) { frame(20) } + List(2) { frame(3000) } + List(40) { frame(20) }
        assertEquals(Vad.State.WAITING, feed(vad, frames))
    }

    @Test
    fun speechRightAtTheStartIsStillDetected() {
        val vad = Vad()
        assertEquals(Vad.State.DONE, feed(vad, List(30) { frame(3000) } + List(40) { frame(20) }))
        assertNotNull(vad.utterance())
    }

    @Test
    fun steadyBackgroundNoiseRaisesTheThreshold() {
        val vad = Vad()
        // 400 RMS hum sits under the 500 base threshold, so the floor becomes 1200 and 800 RMS no longer counts.
        val frames = List(60) { frame(400) } + List(10) { frame(800) }
        assertEquals(Vad.State.WAITING, feed(vad, frames))
    }

    @Test
    fun silenceTimesOut() {
        val vad = Vad()
        assertEquals(Vad.State.TIMED_OUT, feed(vad, List(100) { frame(20) }, timeoutMs = 1500))
    }

    @Test
    fun tooShortUtteranceIsDiscarded() {
        val vad = Vad(silenceMs = 90)
        val frames = List(3) { frame(3000) } + List(5) { frame(10) }
        assertEquals(Vad.State.DONE, feed(vad, frames))
        assertNull(vad.utterance())
    }

    @Test
    fun wavHeaderDescribes16kMonoPcm() {
        val wav = Wav.encode(ShortArray(16000))
        assertEquals(44 + 32000, wav.size)
        assertEquals("RIFF", String(wav, 0, 4, Charsets.US_ASCII))
        assertEquals("WAVE", String(wav, 8, 4, Charsets.US_ASCII))
        val rate = java.nio.ByteBuffer.wrap(wav, 24, 4).order(java.nio.ByteOrder.LITTLE_ENDIAN).int
        assertEquals(16000, rate)
    }
}
