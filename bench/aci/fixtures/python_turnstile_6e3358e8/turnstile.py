"""Turnstile finite state machine.

States: LOCKED, UNLOCKED
Events: COIN, PUSH
"""

LOCKED = "LOCKED"
UNLOCKED = "UNLOCKED"

COIN = "COIN"
PUSH = "PUSH"

# Transition table: (state, event) -> next state
TRANSITIONS = {
    (LOCKED, COIN): LOCKED,
    (LOCKED, PUSH): LOCKED,
    (UNLOCKED, COIN): UNLOCKED,
    (UNLOCKED, PUSH): LOCKED,
}


class Turnstile:
    def __init__(self):
        self.state = LOCKED

    def handle(self, event):
        key = (self.state, event)
        if key not in TRANSITIONS:
            raise ValueError(f"Invalid event {event!r} in state {self.state!r}")
        self.state = TRANSITIONS[key]
        return self.state


if __name__ == "__main__":
    t = Turnstile()
    print("initial:", t.state)
    print("COIN ->", t.handle(COIN))
    print("PUSH ->", t.handle(PUSH))
    print("COIN ->", t.handle(COIN))
    print("PUSH ->", t.handle(PUSH))
