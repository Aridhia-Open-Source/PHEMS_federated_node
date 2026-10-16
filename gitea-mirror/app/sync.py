"""
Sync engine (ADR 0020, stage m5).

Per mirror, under a Postgres advisory lock:
1. List GitHub PRs merged since mirror_state.cursor; skip those already in
   mirrored_pull_requests (Gitea allows duplicate PRs, so our table is the idempotency key).
2. Fetch branches and refs/pull/<n>/head into a bare cache repository; push branches as-is and
   each PR head as pr/<n> to Gitea.
3. Replay PRs oldest merge first (spike surprise 1): force the base to merge_commit_sha^1, open
   the PR as the author's shadow user, fast-forward the base to merge_commit_sha, mark it
   manually merged. Otherwise /files is empty for merge-commit and fast-forward PRs.
4. Per PR, one transaction: the mirrored_pull_requests row, its webhook deliveries, the cursor.
5. Push the upstream base tip so Gitea ends identical to GitHub.
"""
import base64
import logging
import os
import subprocess
import time
from datetime import datetime, timezone

from sqlalchemy import select, text

from app import delivery
from app import github as github_api
from app.github import RateLimited
from app.gitea import shadow_login
from app.helpers.base_model import db
from app.models.mirror import Mirror, MirrorState, MirroredPullRequest

# First key of the two-int advisory lock; the second is the mirror id.
LOCK_NAMESPACE = 20020
MAX_ERROR_LEN = 4096

logger = logging.getLogger(__name__)


class GitError(Exception):
    """A git command failed. Carries stderr only: argv holds the auth header."""


class MirrorBusy(Exception):
    """Another sync holds this mirror's lock."""


def run_git(args: list[str], cwd: str = None, authorization: str = None) -> str:
    """Run git. `authorization` is sent as an HTTP header, never put in the remote URL."""
    cmd = ['git']
    if authorization:
        cmd += ['-c', f'http.extraHeader=Authorization: {authorization}']
    result = subprocess.run(
        cmd + args, cwd=cwd, capture_output=True, text=True,
        env={**os.environ, 'GIT_TERMINAL_PROMPT': '0'},
    )
    if result.returncode:
        raise GitError(f'git {args[0]} failed: {result.stderr.strip()}')
    return result.stdout.strip()


def github_authorization(token: str) -> str:
    """GitHub git-over-HTTPS takes the token as basic auth (as actions/checkout sends it)."""
    return 'Basic ' + base64.b64encode(f'x-access-token:{token}'.encode()).decode()


class GitCache:
    """One bare repository per mirror under a directory (an emptyDir in the chart)."""

    def __init__(self, root: str):
        self.root = root

    @classmethod
    def from_env(cls) -> 'GitCache':
        return cls(os.environ['GITEA_MIRROR_GIT_CACHE_DIR'])

    def repo(self, mirror_id: int) -> str:
        path = os.path.join(self.root, f'{mirror_id}.git')
        if not os.path.isdir(path):
            run_git(['init', '--bare', '--quiet', path])
        return path


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def advance_cursor(state: MirrorState, pulls: list[dict], done: set[int]) -> None:
    """
    Move the cursor to the latest updated_at such that every listed PR updated at or before it
    is mirrored. Replay runs in merged_at order, which can differ from updated_at order; moving
    the cursor past an unmirrored PR would lose it after a crash.
    """
    for pr in sorted(pulls, key=lambda p: _ts(p['updated_at'])):
        if pr['number'] not in done:
            return
        if _ts(pr['updated_at']) > state.cursor:
            state.cursor = _ts(pr['updated_at'])


def _replay(mirror: Mirror, state: MirrorState, github, gitea, git_cache: GitCache) -> list[int]:
    ns, key, base = mirror.secret_namespace, mirror.secret_key, mirror.base_branch
    org, repo = mirror.gitea_owner, mirror.gitea_repo
    pulls = github.list_merged_pulls(mirror.upstream_uri, ns, key, base, state.cursor.isoformat())
    done = set(db.session.scalars(
        select(MirroredPullRequest.number).where(
            MirroredPullRequest.mirror_id == mirror.id,
            MirroredPullRequest.number.in_([p['number'] for p in pulls]),
        )
    ))
    new = sorted((p for p in pulls if p['number'] not in done), key=lambda p: _ts(p['merged_at']))
    advance_cursor(state, pulls, done)
    db.session.commit()

    gitea.ensure_org(org)
    gitea.ensure_repo(org, repo, base)

    cache = git_cache.repo(mirror.id)
    token = github_api.read_secret_token(ns, key)
    run_git(
        ['fetch', '--quiet', '--prune', mirror.upstream_uri, '+refs/heads/*:refs/heads/*',
         *[f'+refs/pull/{p["number"]}/head:refs/pull/{p["number"]}/head' for p in new]],
        cwd=cache, authorization=github_authorization(token),
    )
    gitea_url, gitea_authorization = gitea.git_remote(org, repo)

    def push(*refspecs):
        run_git(['push', '--quiet', '--force', gitea_url, *refspecs],
                cwd=cache, authorization=gitea_authorization)

    push('refs/heads/*:refs/heads/*',
         *[f'refs/pull/{p["number"]}/head:refs/heads/pr/{p["number"]}' for p in new])

    upstream = mirror.upstream_uri.removesuffix('.git')
    mirrored = []
    for pr in new:
        number, sha = pr['number'], pr['merge_commit_sha']
        login = shadow_login(pr['author'])
        push(f'{sha}^1:refs/heads/{base}')
        gitea.ensure_user(login)
        gitea.add_collaborator(org, repo, login)
        index = gitea.open_pull_request(
            org, repo, login, pr['title'], f'Mirrored from {upstream}/pull/{number}',
            f'pr/{number}', base,
        )
        push(f'{sha}:refs/heads/{base}')
        gitea.mark_manually_merged(org, repo, login, index, sha)

        row = MirroredPullRequest(
            mirror_id=mirror.id, number=number, gitea_pr_number=index, title=pr['title'],
            author=pr['author'], merged_at=_ts(pr['merged_at']), merge_commit_sha=sha,
        )
        db.session.add(row)
        delivery.enqueue_deliveries(db.session, row)
        done.add(number)
        advance_cursor(state, pulls, done)
        db.session.commit()
        mirrored.append(number)

    push(f'refs/heads/{base}:refs/heads/{base}')
    return mirrored


def _sync_recording(mirror_id: int, github, gitea, git_cache: GitCache) -> list[int]:
    mirror = db.session.get(Mirror, mirror_id)
    state = db.session.get(MirrorState, mirror_id)
    state.last_sync_at = datetime.now(timezone.utc)
    db.session.commit()
    try:
        mirrored = _replay(mirror, state, github, gitea, git_cache)
    except Exception as err:
        db.session.rollback()
        # TokenExpired's message starts with 'token_expired', the status endpoint's flag.
        state.last_error = str(err)[:MAX_ERROR_LEN]
        db.session.commit()
        raise
    state.last_success_at = datetime.now(timezone.utc)
    state.last_error = None
    db.session.commit()
    return mirrored


def resync(mirror_id: int, github, gitea, git_cache: GitCache) -> list[int]:
    """Sync one mirror now. Returns the GitHub numbers mirrored. Raises MirrorBusy if locked."""
    params = {'ns': LOCK_NAMESPACE, 'id': mirror_id}
    # Session-level lock on its own connection: it must outlive the per-PR commits.
    with db.engine.connect() as lock:
        if not lock.execute(text('SELECT pg_try_advisory_lock(:ns, :id)'), params).scalar():
            raise MirrorBusy(f'Mirror {mirror_id} is already syncing')
        try:
            return _sync_recording(mirror_id, github, gitea, git_cache)
        finally:
            lock.execute(text('SELECT pg_advisory_unlock(:ns, :id)'), params)


def tick(app, paused: dict[int, datetime]) -> None:
    """
    One timer round: sync each enabled mirror, then attempt due webhook deliveries.
    `paused` maps mirror id -> GitHub rate-limit reset time; those mirrors wait until then.
    """
    with app.app_context():
        ext = app.extensions
        now = datetime.now(timezone.utc)
        ids = db.session.scalars(
            select(Mirror.id).where(Mirror.enabled.is_(True)).order_by(Mirror.id)
        ).all()
        for mirror_id in ids:
            if mirror_id in paused and paused[mirror_id] > now:
                continue
            paused.pop(mirror_id, None)
            try:
                resync(mirror_id, ext['github_client'], ext['gitea_client'], ext['git_cache'])
            except RateLimited as err:
                paused[mirror_id] = err.reset_at
            except MirrorBusy:
                pass
            except Exception:
                # Recorded on mirror_state; the next round retries.
                logger.exception('Sync of mirror %s failed', mirror_id)
        delivery.process_due_deliveries(db.session)


def run_forever(app) -> None:
    """The timer loop the app runner starts in a thread."""
    interval = int(os.environ['GITEA_MIRROR_SYNC_INTERVAL_SECONDS'])
    paused: dict[int, datetime] = {}
    while True:
        try:
            tick(app, paused)
        except Exception:
            logger.exception('Sync round failed')
        time.sleep(interval)
