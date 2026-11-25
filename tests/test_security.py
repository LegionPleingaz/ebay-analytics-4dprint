from app.api.security import STATE_TTL_SECONDS, create_state, is_valid_state


def test_fresh_state_is_valid(settings):
    assert is_valid_state(create_state(settings, now=1000), settings, now=1001)


def test_expired_state_is_rejected(settings):
    state = create_state(settings, now=1000)
    assert not is_valid_state(state, settings, now=1001 + STATE_TTL_SECONDS)


def test_forged_or_missing_state_is_rejected(settings):
    assert not is_valid_state("1000.deadbeef", settings, now=1001)
    assert not is_valid_state("", settings, now=1001)
