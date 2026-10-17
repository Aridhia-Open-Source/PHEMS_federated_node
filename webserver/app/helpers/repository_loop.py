from app.helpers.exceptions import InvalidRequest
from app.models.project_results_repository import ProjectResultsRepository
from app.models.project_trigger_repository import ProjectTriggerRepository
from app.models.results_repository import ResultsRepository
from app.models.trigger_repository import TriggerRepository


def normalise_dir(directory: str) -> str:
    """
    Drops '.' and empty segments and the leading and trailing '/'. A '..' segment is refused,
    as it would let a directory point outside the one it is written under.
    """
    if not isinstance(directory, str):
        raise InvalidRequest("Directory must be a string")
    segments = [s for s in directory.split('/') if s not in ('', '.')]
    if '..' in segments:
        raise InvalidRequest(f"Directory '{directory}' must not contain '..'")
    return '/'.join(segments)


def _segments(directory: str) -> list[str]:
    return [s for s in normalise_dir(directory).split('/') if s]


def _overlaps(a: list[str], b: list[str]) -> bool:
    shorter = min(len(a), len(b))
    return a[:shorter] == b[:shorter]


def check_no_loop(provider_id: int, repo_path: str):
    """
    A results repository written into the directory a trigger repository watches would fire
    the trigger with its own output. So where a project's results assignment and a trigger
    repository, of any project, are the same repository, their directories must not overlap,
    and the trigger must watch a directory of its own.
    """
    results = ProjectResultsRepository.query.join(ResultsRepository).filter(
        ResultsRepository.provider_id == provider_id, ResultsRepository.repo_path == repo_path
    ).all()
    triggers = ProjectTriggerRepository.query.join(TriggerRepository).filter(
        TriggerRepository.provider_id == provider_id, TriggerRepository.repo_path == repo_path
    ).all()
    for results_assignment in results:
        for trigger_assignment in triggers:
            if not _segments(trigger_assignment.watch_dir):
                raise InvalidRequest(
                    f"Trigger repository {trigger_assignment.trigger_repository.uri} watches the whole repository, "
                    "which a results repository also writes to"
                )
            if _overlaps(_segments(trigger_assignment.watch_dir), _segments(results_assignment.target_dir)):
                raise InvalidRequest(
                    f"Trigger watch_dir '{trigger_assignment.watch_dir}' and results target_dir "
                    f"'{results_assignment.target_dir}' overlap in repository {trigger_assignment.trigger_repository.uri}"
                )
