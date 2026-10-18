import pytest
from core.response_language import input_language_codes
from core.llm_openai_realtime import session_options


@pytest.mark.parametrize('value,expected', [
    ('ID', ['id-ID']), ('Indonesian', ['id-ID']), ('Bahasa Indonesia', ['id-ID']),
    ('EN', ['en-US']), ('JA', ['ja-JP']), ('en-GB', ['en-GB']),
    ('zh-Hant-TW', ['zh-Hant-TW']), ('auto', []), ('Unknown Language Name', []),
])
def test_primary_language_generates_valid_asr_hints(value, expected):
    assert input_language_codes({'response_language': value}, {}) == expected


def test_observed_spanish_cannot_override_explicit_indonesian():
    memory = {'identity': {'language': {'value': 'Spanish'}}}
    assert input_language_codes({'response_language': 'ID'}, memory) == ['id-ID']
    assert input_language_codes({}, memory) == []


def test_realtime_hint_preserves_transcription_model_and_manual_turns():
    options = session_options({'input_audio_transcription': {'language_codes': ['id-ID']}},
        {'realtime_transcription_model': 'configured-model'})
    assert options['audio']['input']['transcription'] == {'model': 'configured-model', 'language': 'id'}
    assert options['audio']['input']['turn_detection'] is None
    assert session_options({'input_audio_transcription': {'language_codes': []}},
        {'response_language': 'ID'})['audio']['input']['transcription'].get('language') is None


def test_actual_google_setup_serializes_hint_without_an_extra_model():
    from google.genai import types, _live_converters, _common
    parent = {}
    config = types.LiveConnectConfig(input_audio_transcription={'language_codes': ['id-ID']})
    _live_converters._LiveConnectConfig_to_mldev(None, config.model_dump(exclude_none=True), parent)
    serialized = _common.convert_to_dict(parent)
    assert serialized['setup']['inputAudioTranscription']['language_codes'] == ['id-ID']
    assert 'model' not in serialized['setup']
