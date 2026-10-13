from app.helpers.exceptions import InvalidRequest
from app.models.results_repository import ResultsRepository
from app.models.trigger_repository import TriggerRepository


def _segments(directory: str) -> list[str]:
    return [s for s in directory.split('/') if s]


def _overlaps(a: list[str], b: list[str]) -> bool:
    shorter = min(len(a), len(b))
    return a[:shorter] == b[:shorter]


def check_no_loop(project_id: int, uri: str):
    """
    A results repository written into the directory a trigger repository watches would fire
    the trigger with its own output. So where a project's results repository and a trigger
    repository are the same repository, their directories must not overlap, and the trigger
    must watch a directory of its own.
    """
    results = ResultsRepository.query.filter_by(project_id=project_id, uri=uri).all()
    triggers = TriggerRepository.query.filter_by(project_id=project_id, uri=uri).all()
    for results_repo in results:
        for trigger_repo in triggers:
            if not _segments(trigger_repo.watch_dir):
                raise InvalidRequest(
                    f"Trigger repository {trigger_repo.uri} watches the whole repository, "
                    "which the results repository in the same project also writes to"
                )
            if _overlaps(_segments(trigger_repo.watch_dir), _segments(results_repo.target_dir)):
                raise InvalidRequest(
                    f"Trigger watch_dir '{trigger_repo.watch_dir}' and results target_dir "
                    f"'{results_repo.target_dir}' overlap in repository {uri}"
                )
