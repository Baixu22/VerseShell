"""A tiny job scheduler built on an explicit state machine.

Jobs move between states in response to events.  Every legal
(state, event) pair is listed in TRANSITIONS; firing an event that is
not listed for the job's current state raises InvalidTransitionError.
"""

PENDING = "PENDING"
RUNNING = "RUNNING"
DONE = "DONE"
FAILED = "FAILED"
CANCELLED = "CANCELLED"

TERMINAL_STATES = frozenset({DONE, FAILED, CANCELLED})

TRANSITIONS = {
    (PENDING, "start"): RUNNING,
    (PENDING, "cancel"): CANCELLED,
    (RUNNING, "complete"): DONE,
    (RUNNING, "fail"): FAILED,
    (RUNNING, "cancel"): DONE,
    (FAILED, "retry"): PENDING,
}


class InvalidTransitionError(Exception):
    """Raised when an event is not legal for the job's current state."""


class Job:
    def __init__(self, name: str):
        self.name = name
        self.state = PENDING
        self.history = [PENDING]

    def fire(self, event: str) -> str:
        key = (self.state, event)
        if key not in TRANSITIONS:
            raise InvalidTransitionError(
                f"job {self.name!r}: event {event!r} is not allowed in state {self.state}"
            )
        self.state = TRANSITIONS[key]
        self.history.append(self.state)
        return self.state

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL_STATES
