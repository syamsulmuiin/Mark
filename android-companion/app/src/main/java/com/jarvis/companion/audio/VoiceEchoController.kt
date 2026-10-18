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
        get() = try { aec?.enabled == true } catch (_: RuntimeException) { false }

    val noiseSuppressionActive: Boolean
        get() = try { ns?.enabled == true } catch (_: RuntimeException) { false }

    fun start(): Boolean {
        if (AcousticEchoCanceler.isAvailable()) {
            try {
                aec = AcousticEchoCanceler.create(sessionId)
                aec?.enabled = true
            } catch (_: RuntimeException) {
                try { aec?.release() } catch (_: RuntimeException) {}
                aec = null
            }
        }
        if (NoiseSuppressor.isAvailable()) {
            try {
                ns = NoiseSuppressor.create(sessionId)
                ns?.enabled = true
            } catch (_: RuntimeException) {
                try { ns?.release() } catch (_: RuntimeException) {}
                ns = null
            }
        }
        return echoCancellationActive
    }

    override fun close() {
        try { aec?.release() } catch (_: RuntimeException) {}
        try { ns?.release() } catch (_: RuntimeException) {}
        aec = null
        ns = null
    }
}
