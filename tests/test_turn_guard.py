from core.turn_guard import AssistantResponseGuard


def test_exact_and_semantic_duplicates_are_emitted_once_per_request():
    guard = AssistantResponseGuard()
    guard.begin("request-1")
    assert guard.accept("The answer is 2.") is True
    assert guard.accept("The answer is 2.") is False
    assert guard.accept("The answer is: 2") is False


def test_new_request_and_reconnect_replay_do_not_suppress_legitimate_follow_up():
    guard = AssistantResponseGuard()
    guard.begin("request-1")
    assert guard.accept("1 + 1 = 2") is True
    guard.begin("request-2")
    assert guard.accept("1 + 1 = 2") is True
    guard.begin("request-3")
    assert guard.accept("replayed answer") is True
    guard.begin("request-3")
    assert guard.accept("replayed answer") is False
