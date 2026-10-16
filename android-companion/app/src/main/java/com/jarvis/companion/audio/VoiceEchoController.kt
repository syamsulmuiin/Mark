package com.jarvis.companion.audio

import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.NoiseSuppressor

/**
 * AudioRecord-session scoped platform AEC/NS.
 * Attach immediately after creating AudioRecord, using its audioSessionId,
 * and close before releasing AudioRecord. Do not attach to playback session.
 * Some Android devices do not provide an effective platform AEC.
 */
class VoiceEchoController(private val sessionId: Int) : AutoCloseable {
    private var aec: AcousticEchoCanceler? = null
    private var ns: NoiseSuppressor? = null

    val echoCancellationActive: Boolean
        get() = aec?.enabled == true

    fun start(): Boolean {
        if (AcousticEchoCanceler.isAvailable()) {
            try {
                aec = AcousticEchoCanceler.create(sessionId)?.also { it.enabled = true }
            } catch (_: RuntimeException) {
                aec?.release()
                aec = null
            }
        }
        if (NoiseSuppressor.isAvailable()) {
            try {
                ns = NoiseSuppressor.create(sessionId)?.also { it.enabled = true }
            } catch (_: RuntimeException) {
                ns?.release()
                ns = null
            }
        }
        return echoCancellationActive
    }

    override fun close() {
        aec?.release()
        ns?.release()
        aec = null
        ns = null
    }
}
