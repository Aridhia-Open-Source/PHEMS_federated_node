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
import re
import subprocess
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import select, text

from app import delivery
from app import github as github_api
from app.github import RateLimited
from app.gitea import GiteaError, shadow_login
from app.helpers.base_model import db
from app.models.mirror import Mirror, MirrorState, MirroredPullRequest

# First key of the two-int advisory lock; the second is the mirror id.
LOCK_NAMESPACE = 20020
MAX_ERROR_LEN = 4096
GITHUB_HOST = 'github.com'
GITHUB_GIT_SCOPE = f'https://{GITHUB_HOST}/'

logger = logging.getLogger(__name__)


class SyncError(Exception):
    """A problem with the mirror's configuration or upstream, recorded in last_error."""


class GitError(Exception):
    """A git command failed. Carries scrubbed stderr only: credentials never appear in it."""


class MirrorBusy(Exception):
    """Another sync holds this mirror's lock."""


class UnsupportedUpstream(SyncError):
    """The upstream is not https://github.com/<owner>/<repo>: the token is sent nowhere else."""


class InvalidRefName(SyncError, ValueError):
    """A branch name that is unsafe in a refspec or collides with the mirror's pr/<n> refs."""


class BranchCollision(SyncError):
    """An upstream branch named `pr` or `pr/<n>...` would collide with a mirrored PR head."""


class PoisonPullRequest(SyncError):
    """One PR cannot be replayed (no merge commit, unreachable parent, rejected by Gitea)."""


class PullRequestsFailed(SyncError):
    """Some PRs were quarantined; the others were mirrored and the base is at the upstream tip."""


_USERINFO = re.compile(r'(://)[^/@\s]*@')
_COLLIDING = re.compile(r'pr(/\d+(/.*)?)?')
_BRANCH_CHARS = re.compile(r'[A-Za-z0-9._/+@=,-]+')
_SHA = re.compile(r'[0-9a-f]{40}')


def scrub(message: str, secrets=()) -> str:
    """Remove credentials from text that is stored or shown: userinfo in URLs, given secrets."""
    message = _USERINFO.sub(r'\1', message)
    for secret in secrets:
        if secret:
            message = message.replace(secret, '***')
    return message


def check_branch_name(name: str) -> None:
    """Whitelist for a branch name that goes into a refspec; `pr` and `pr/<n>` are reserved."""
    parts = name.split('/') if isinstance(name, str) else []
    ok = (
        isinstance(name, str) and 0 < len(name) <= 200 and _BRANCH_CHARS.fullmatch(name)
        and '..' not in name and not name.startswith(('-', '/')) and not name.endswith(('/', '.'))
        and name != '@' and all(p and not p.startswith('.') and not p.endswith('.lock')
                                for p in parts)
    )
    if not ok:
        raise InvalidRefName(f'Invalid branch name: {name!r}')
    if _COLLIDING.fullmatch(name):
        raise InvalidRefName(f"Branch name {name!r} is reserved for mirrored pull request heads")


def check_upstream(upstream_uri: str) -> None:
    """The GitHub token is only ever sent to https://github.com (no userinfo, no other port)."""
    try:
        url = urlparse(upstream_uri)
        port = url.port
    except ValueError:
        raise UnsupportedUpstream('Upstream uri is not a valid URL') from None
    if (url.scheme != 'https' or (url.hostname or '').lower() != GITHUB_HOST or port is not None
            or url.username is not None or url.password is not None):
        raise UnsupportedUpstream(
            f'Only https://{GITHUB_HOST}/<owner>/<repo> upstreams are supported, '
            f'not {scrub(upstream_uri)}'
        )


def run_git(args: list[str], cwd: str = None, authorization: str = None,
            auth_scope: str = None) -> str:
    """
    Run git. `authorization` is sent as an HTTP header only to URLs under `auth_scope`
    (http.<scope>.extraHeader), set through GIT_CONFIG_* environment variables so it appears in
    neither argv nor the remote URL. Redirects are not followed when a header is set.
    """
    if bool(authorization) != bool(auth_scope):
        raise ValueError('authorization and auth_scope go together')
    env = {**os.environ, 'GIT_TERMINAL_PROMPT': '0'}
    secrets = []
    if authorization:
        n = int(env.get('GIT_CONFIG_COUNT') or 0)
        env.update({
            f'GIT_CONFIG_KEY_{n}': f'http.{auth_scope}.extraHeader',
            f'GIT_CONFIG_VALUE_{n}': f'Authorization: {authorization}',
            f'GIT_CONFIG_KEY_{n + 1}': 'http.followRedirects',
            f'GIT_CONFIG_VALUE_{n + 1}': 'false',
            'GIT_CONFIG_COUNT': str(n + 2),
        })
        secrets = [authorization, authorization.split()[-1]]
    result = subprocess.run(['git', *args], cwd=cwd, capture_output=True, text=True, env=env)
    if result.returncode:
        raise GitError(f'git {args[0]} failed: {scrub(result.stderr.strip(), secrets)}')
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
    is settled (mirrored, or history). Replay runs in merged_at order, which can differ from
    updated_at order. The cursor also never passes the merged_at of a PR that is still pending:
    the cursor doubles as the "no backfill" line (a PR merged before it is history), so it
    must stay at or before every PR that is genuinely new.
    """
    target = state.cursor
    for pr in sorted(pulls, key=lambda p: _ts(p['updated_at'])):
        if pr['number'] not in done:
            break
        target = max(target, _ts(pr['updated_at']))
    pending = [_ts(p.get('merged_at') or p['updated_at']) for p in pulls if p['number'] not in done]
    if pending:
        target = min(target, min(pending))
    if target > state.cursor:
        state.cursor = target


def _check_no_collisions(cache: str) -> None:
    names = run_git(['for-each-ref', '--format=%(refname)', 'refs/heads'], cwd=cache).splitlines()
    for ref in names:
        name = ref.removeprefix('refs/heads/')
        if _COLLIDING.fullmatch(name):
            raise BranchCollision(
                f"Upstream branch '{name}' collides with the pr/<n> branches the mirror "
                f"creates for pull requests; rename or delete it upstream"
            )


def _replay(mirror: Mirror, state: MirrorState, github, gitea, git_cache: GitCache) -> list[int]:
    check_upstream(mirror.upstream_uri)
    ns, key, base = mirror.secret_namespace, mirror.secret_key, mirror.base_branch
    org, repo = mirror.gitea_owner, mirror.gitea_repo
    check_branch_name(base)
    if state.cursor is None:  # sync starts from now (ADR 0020: no backfill)
        state.cursor = datetime.now(timezone.utc)
        db.session.commit()
    start = state.cursor
    pulls = github.list_merged_pulls(mirror.upstream_uri, ns, key, base, start.isoformat())
    mirrored_numbers = set(db.session.scalars(
        select(MirroredPullRequest.number).where(
            MirroredPullRequest.mirror_id == mirror.id,
            MirroredPullRequest.number.in_([p['number'] for p in pulls]),
        )
    ))
    # Merged before the mirror started (or before the cursor) but updated since, e.g. a late
    # comment: history, not replayed. The cursor invariant in advance_cursor makes this safe.
    history = {p['number'] for p in pulls
               if p['number'] not in mirrored_numbers and _ts(p['merged_at']) < start}
    done = mirrored_numbers | history
    new = sorted((p for p in pulls if p['number'] not in done), key=lambda p: _ts(p['merged_at']))
    advance_cursor(state, pulls, done)
    db.session.commit()

    gitea.ensure_org(org)
    gitea.ensure_repo(org, repo, base)

    cache = git_cache.repo(mirror.id)
    token = github_api.read_secret_token(ns, key)
    run_git(
        ['fetch', '--quiet', '--prune', mirror.upstream_uri, '+refs/heads/*:refs/heads/*',
         *[f'+refs/pull/{int(p["number"])}/head:refs/pull/{int(p["number"])}/head' for p in new]],
        cwd=cache, authorization=github_authorization(token), auth_scope=GITHUB_GIT_SCOPE,
    )
    _check_no_collisions(cache)
    gitea_url, gitea_authorization = gitea.git_remote(org, repo)
    gitea_origin = urlparse(gitea_url)
    gitea_scope = f'{gitea_origin.scheme}://{gitea_origin.netloc}/'

    def push(*refspecs):
        run_git(['push', '--quiet', '--force', gitea_url, *refspecs],
                cwd=cache, authorization=gitea_authorization, auth_scope=gitea_scope)

    push('refs/heads/*:refs/heads/*',
         *[f'refs/pull/{int(p["number"])}/head:refs/heads/pr/{int(p["number"])}' for p in new])

    gitea.set_default_branch(org, repo, base)

    upstream = mirror.upstream_uri.removesuffix('.git')

    def mirror_pull_request(pr: dict) -> None:
        number, sha = int(pr['number']), pr['merge_commit_sha']
        if not sha or not _SHA.fullmatch(sha):
            raise PoisonPullRequest('GitHub reports no merge commit')
        login = shadow_login(pr['author'])
        try:
            push(f'{sha}^1:refs/heads/{base}')
        except GitError as err:
            raise PoisonPullRequest(f'merge commit {sha[:12]} or its parent is not reachable: {err}')
        gitea.ensure_user(pr['author'])
        gitea.add_collaborator(org, repo, login)
        head = f'pr/{number}'
        # Gitea accepts duplicate PRs for a head, and a failure after the open (or a lost
        # response) must not open another on the retry: look first, then finish that PR.
        existing = gitea.find_pull_request(org, repo, head)
        if existing:
            index = existing['number']
            if not existing.get('merged'):
                # The base was restored to the tip after the failed attempt, so Gitea's stored
                # diff base for this PR is stale; let it recompute against the parent.
                gitea.wait_for_pull_request_base(org, repo, index)
        else:
            index = gitea.open_pull_request(
                org, repo, login, pr['title'], f'Mirrored from {upstream}/pull/{number}', head, base,
            )
        push(f'{sha}:refs/heads/{base}')
        if not (existing and existing.get('merged')):
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

    def restore_base():
        push(f'refs/heads/{base}:refs/heads/{base}')

    mirrored, failed = [], {}
    try:
        for pr in new:
            try:
                mirror_pull_request(pr)
                mirrored.append(pr['number'])
            except (PoisonPullRequest, GiteaError) as err:
                if isinstance(err, GiteaError) and err.status >= 500:
                    raise  # transient: stop here, retry next round
                db.session.rollback()
                failed[pr['number']] = str(err)
                logger.warning('Mirror %s: PR #%s quarantined: %s', mirror.id, pr['number'], err)
    except BaseException:
        try:
            restore_base()  # never leave Gitea's base rewound to some PR's parent
        except Exception:
            logger.exception('Mirror %s: could not restore base branch', mirror.id)
        raise
    restore_base()
    if failed:
        raise PullRequestsFailed('; '.join(f'PR #{n}: {msg}' for n, msg in sorted(failed.items())))
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
        state.last_error = scrub(str(err))[:MAX_ERROR_LEN]
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
