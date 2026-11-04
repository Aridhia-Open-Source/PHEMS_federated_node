"""Checks of the state moves the tables in app/models allow. A refused move is a 409."""

from http import HTTPStatus

from app.helpers.exceptions import InvalidRequest


def transition(moves: dict[str, set[str]], current: str, new: str) -> None:
    """The same state again is allowed. Any other move must be in moves[current]."""
    if new != current and new not in moves[current]:
        raise InvalidRequest(f"Cannot move from {current} to {new}", HTTPStatus.CONFLICT)


def forward_only(order: dict[str, int], current: str, new: str) -> None:
    """
    The same state again is allowed. Any other move must go to a higher rank, so states of equal
    rank refuse a move between them.
    """
    if new != current and order[new] <= order[current]:
        raise InvalidRequest(f"Cannot move from {current} to {new}", HTTPStatus.CONFLICT)
