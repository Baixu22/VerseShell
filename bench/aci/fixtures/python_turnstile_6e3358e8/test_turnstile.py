"""Tests for the turnstile finite state machine.

These tests verify the full transition table and the state behavior of the
Turnstile class. Expected behavior:

    (LOCKED, COIN)   -> UNLOCKED
    (LOCKED, PUSH)   -> LOCKED
    (UNLOCKED, COIN) -> UNLOCKED
    (UNLOCKED, PUSH) -> LOCKED
"""

import pytest

from turnstile import (
    LOCKED,
    UNLOCKED,
    COIN,
    PUSH,
    TRANSITIONS,
    Turnstile,
)


class TestTransitionTable:
    def test_locked_coin_goes_to_unlocked(self):
        actual = TRANSITIONS[(LOCKED, COIN)]
        expected = UNLOCKED
        assert actual == expected, (
            f"transition (LOCKED, COIN): expected {expected!r}, got {actual!r}"
        )

    def test_locked_push_stays_locked(self):
        actual = TRANSITIONS[(LOCKED, PUSH)]
        expected = LOCKED
        assert actual == expected, (
            f"transition (LOCKED, PUSH): expected {expected!r}, got {actual!r}"
        )

    def test_unlocked_coin_stays_unlocked(self):
        actual = TRANSITIONS[(UNLOCKED, COIN)]
        expected = UNLOCKED
        assert actual == expected, (
            f"transition (UNLOCKED, COIN): expected {expected!r}, got {actual!r}"
        )

    def test_unlocked_push_goes_to_locked(self):
        actual = TRANSITIONS[(UNLOCKED, PUSH)]
        expected = LOCKED
        assert actual == expected, (
            f"transition (UNLOCKED, PUSH): expected {expected!r}, got {actual!r}"
        )


class TestTurnstileClass:
    def test_initial_state_is_locked(self):
        t = Turnstile()
        actual = t.state
        expected = LOCKED
        assert actual == expected, (
            f"initial state: expected {expected!r}, got {actual!r}"
        )

    def test_coin_unlocks_the_turnstile(self):
        t = Turnstile()
        result = t.handle(COIN)
        assert result == UNLOCKED, (
            f"handle(COIN) from LOCKED returned {result!r}, expected {UNLOCKED!r}"
        )
        assert t.state == UNLOCKED, (
            f"state after COIN from LOCKED is {t.state!r}, expected {UNLOCKED!r}"
        )

    def test_push_after_coin_locks_again(self):
        t = Turnstile()
        t.handle(COIN)
        result = t.handle(PUSH)
        assert result == LOCKED, (
            f"handle(PUSH) from UNLOCKED returned {result!r}, expected {LOCKED!r}"
        )
        assert t.state == LOCKED, (
            f"state after COIN then PUSH is {t.state!r}, expected {LOCKED!r}"
        )

    def test_coin_when_already_unlocked_stays_unlocked(self):
        t = Turnstile()
        t.handle(COIN)
        result = t.handle(COIN)
        assert result == UNLOCKED, (
            f"handle(COIN) from UNLOCKED returned {result!r}, expected {UNLOCKED!r}"
        )
        assert t.state == UNLOCKED, (
            f"state after two COINs is {t.state!r}, expected {UNLOCKED!r}"
        )

    def test_full_session_sequence(self):
        t = Turnstile()
        states = [t.state]
        for event in (COIN, PUSH, COIN, PUSH):
            states.append(t.handle(event))
        expected = [LOCKED, UNLOCKED, LOCKED, UNLOCKED, LOCKED]
        assert states[0] == expected[0], f"step 0: {states[0]!r} != {expected[0]!r}"
        assert states[1] == expected[1], f"step 1: {states[1]!r} != {expected[1]!r}"
        assert states[2] == expected[2], f"step 2: {states[2]!r} != {expected[2]!r}"
        assert states[3] == expected[3], f"step 3: {states[3]!r} != {expected[3]!r}"
        assert states[4] == expected[4], f"step 4: {states[4]!r} != {expected[4]!r}"

    def test_invalid_event_raises(self):
        t = Turnstile()
        with pytest.raises(ValueError):
            t.handle("EJECT")
