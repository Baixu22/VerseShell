import pytest

from scheduler import (
    CANCELLED,
    DONE,
    FAILED,
    PENDING,
    RUNNING,
    InvalidTransitionError,
    Job,
)


def test_lifecycle_start_complete():
    job = Job("build")
    assert job.state == PENDING
    job.fire("start")
    assert job.state == RUNNING
    job.fire("complete")
    assert job.state == DONE
    assert job.is_terminal


def test_fail_then_retry_lifecycle():
    job = Job("deploy")
    job.fire("start")
    job.fire("fail")
    assert job.state == FAILED
    job.fire("retry")
    assert job.state == PENDING
    job.fire("start")
    job.fire("complete")
    assert job.state == DONE
    assert job.history == [PENDING, RUNNING, FAILED, PENDING, RUNNING, DONE]


def test_cancel_from_pending():
    job = Job("report")
    job.fire("cancel")
    assert job.state == CANCELLED
    assert job.is_terminal


def test_cancel_from_running_goes_to_cancelled():
    job = Job("index")
    job.fire("start")
    assert job.state == RUNNING
    job.fire("cancel")
    assert job.state == CANCELLED
    assert job.is_terminal


def test_unknown_event_raises():
    job = Job("cache")
    with pytest.raises(InvalidTransitionError):
        job.fire("complete")


def test_terminal_jobs_accept_no_events():
    job = Job("cleanup")
    job.fire("start")
    job.fire("complete")
    with pytest.raises(InvalidTransitionError):
        job.fire("cancel")
