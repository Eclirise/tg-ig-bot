from app.services.subscription_service import apply_subscription_action, subscription_flags_for_mode


def test_subscription_flags_for_mode() -> None:
    assert subscription_flags_for_mode("feed") == (True, False)
    assert subscription_flags_for_mode("story") == (False, True)
    assert subscription_flags_for_mode("both") == (True, True)


def test_apply_subscription_action_transitions() -> None:
    assert apply_subscription_action(True, True, "disable_feed") == (False, True)
    assert apply_subscription_action(True, False, "only_story") == (False, True)
    assert apply_subscription_action(False, True, "unsubscribe") == (False, False)
