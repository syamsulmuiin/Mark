from main import _partial_transcript_entries


def test_partial_transcript_preserves_input_and_output_on_rollover():
    assert _partial_transcript_entries(["buat laporan"], ["Saya mulai"], "JARVIS") == [
        ("user", "buat laporan"),
        ("jarvis", "Saya mulai"),
    ]


def test_partial_transcript_ignores_empty_buffers():
    assert _partial_transcript_entries([], [], "JARVIS") == []
