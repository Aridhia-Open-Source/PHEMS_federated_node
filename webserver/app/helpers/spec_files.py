from app.models.pull_request import PullRequest


def is_under_dir(filename: str, directory: str) -> bool:
    """
    Whether the file's directory is the given directory or inside it, matching whole path
    segments. An empty directory is the whole repository.
    """
    wanted = [s for s in directory.split("/") if s not in ("", ".")]
    return filename.split("/")[:-1][:len(wanted)] == wanted


def spec_files(pull_request: PullRequest, watch_dir: str) -> list[str]:
    """
    The paths of the spec files the pull request carries for a watch_dir: files it adds,
    ending in `.json`, under the directory. The one rule of what a pull request matches,
    used by the fan-out and exposed on the trigger for Dagster's evaluate step.
    """
    return [
        file.path for file in pull_request.files
        if file.status == "added" and file.path.endswith('.json') and is_under_dir(file.path, watch_dir)
    ]
