from core.llm_policy import live_delegation_instruction


def test_non_gemini_provider_prefers_text_reasoning():
    policy = live_delegation_instruction({"llm_provider": "deepseek"})
    assert "deepseek" in policy
    assert "delegate_to_text_llm" in policy
    assert "do not claim" in policy


def test_gemini_default_keeps_existing_live_behavior():
    assert live_delegation_instruction({}) == ""
    assert live_delegation_instruction({"llm_provider": "gemini"}) == ""
