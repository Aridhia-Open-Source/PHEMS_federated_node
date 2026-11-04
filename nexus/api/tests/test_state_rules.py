"""Every (current, new) pair against the state tables and their two checks."""

import itertools

import pytest

from app.helpers.exceptions import InvalidRequest
from app.helpers.state_rules import forward_only, transition
from app.models.pull_request_result_step import RESULT_ORDER
from app.models.task_status import RETRYABLE, TASK_MOVES, TaskStatus
from app.models.trigger_state import TRIGGER_MOVES


def pairs(states):
    return list(itertools.product(states, repeat=2))


@pytest.mark.parametrize("moves", [TRIGGER_MOVES, TASK_MOVES])
def test_tables_name_every_state_once_and_only_known_states(moves):
    assert all(targets <= set(moves) for targets in moves.values())


@pytest.mark.parametrize("current,new", pairs(TRIGGER_MOVES))
def test_trigger_moves(current, new):
    if new == current or new in TRIGGER_MOVES[current]:
        transition(TRIGGER_MOVES, current, new)
    else:
        with pytest.raises(InvalidRequest) as error:
            transition(TRIGGER_MOVES, current, new)
        assert error.value.code == 409


@pytest.mark.parametrize("current,new", pairs(TASK_MOVES))
def test_task_moves(current, new):
    allowed = new == current or (current not in ("SUCCESS", "FAILED", "CANCELED") and new in TASK_MOVES[current])
    if allowed:
        transition(TASK_MOVES, current, new)
    else:
        with pytest.raises(InvalidRequest) as error:
            transition(TASK_MOVES, current, new)
        assert error.value.code == 409


def test_task_moves_are_forward_only():
    order = [s.value for s in TaskStatus]
    assert all(order.index(new) > order.index(current) for current, news in TASK_MOVES.items() for new in news)
    assert RETRYABLE == {"FAILED", "CANCELED"}


@pytest.mark.parametrize("current,new", pairs(RESULT_ORDER))
def test_result_moves(current, new):
    if new == current or RESULT_ORDER[new] > RESULT_ORDER[current]:
        forward_only(RESULT_ORDER, current, new)
    else:
        with pytest.raises(InvalidRequest) as error:
            forward_only(RESULT_ORDER, current, new)
        assert error.value.code == 409
