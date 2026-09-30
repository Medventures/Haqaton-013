"""Exercise the real Whisper/PyAV boundary without downloading a model."""

import io
import wave

import numpy as np
from faster_whisper.audio import decode_audio


def test_whisper_decodes_pcm_audio_with_installed_pyav():
    # PyAV 19 removed metadata_errors, breaking faster-whisper's decoder.
    # A synthetic one-second WAV keeps this dependency regression offline.
    source = io.BytesIO()
    with wave.open(source, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x10" * 16000)
    source.seek(0)

    samples = decode_audio(source, sampling_rate=16000)

    assert samples.shape == (16000,)
    assert samples.dtype == np.float32
    np.testing.assert_allclose(samples, 0.125)
