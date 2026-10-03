from core.transcript_corrections import ScopedTranscriptCorrections


def test_explicit_correction_is_learned_only_for_the_scoped_device():
    first = ScopedTranscriptCorrections("user-a/device-1")
    second = ScopedTranscriptCorrections("user-a/device-2")

    assert first.learn_from_conversation("Maksud saya halaman, bukan elemen") is True
    assert first.correct("Buka elemen berikutnya") == "Buka halaman berikutnya"
    assert second.correct("Buka elemen berikutnya") == "Buka elemen berikutnya"


def test_partial_fragments_are_aggregated_before_learning_or_correction():
    memory = ScopedTranscriptCorrections("user-a/device-1")
    assert memory.aggregate("hala") == "hala"
    assert memory.aggregate("halaman") == "halaman"
    assert memory.learn_from_conversation("halaman, bukan elemen") is True
    assert memory.correct("halaman kedua") == "halaman kedua"


def test_sensitive_values_are_not_learned_and_memory_is_bounded():
    memory = ScopedTranscriptCorrections("user-a/device-1", max_entries=2)
    assert memory.learn("kode", "A1B2C3D4E5F6G7H8I9J0K1L2") is False
    assert memory.learn("nomor", "+1 202-555-0199") is False
    assert memory.learn("elemen", "halaman") is True
    assert memory.learn("buku", "book") is True
    assert memory.learn("suara", "voice") is True
    assert len(memory.mapping()) == 2
