import re
from app.helpers.errors import BadRequest

STRING_FIELDS = (
    'upstream_uri', 'secret_namespace', 'secret_key', 'gitea_owner', 'gitea_repo', 'base_branch'
)
MAX_LEN = 256

# `owner/repo` on github.com only: https, host exactly github.com, no userinfo, port, query or
# fragment. fullmatch (not match/$) so a trailing newline cannot slip through.
GITHUB_NAME = r'[A-Za-z0-9_.-]{1,100}'
UPSTREAM_RE = re.compile(rf'https://github\.com/({GITHUB_NAME})/({GITHUB_NAME})')
# Gitea owner and repository names: they go into API paths and the clone URL.
GITEA_NAME_RE = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,99}')
# Branch names are interpolated into refspecs (refs/heads/{base}): git ref-name rules, tightened.
BRANCH_RE = re.compile(r'[A-Za-z0-9_][A-Za-z0-9_./-]{0,199}')
# Kubernetes namespace (DNS-1123 label) and secret name (DNS-1123 subdomain): both go into the
# secrets API URL.
K8S_LABEL_RE = re.compile(r'[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?')
K8S_NAME_RE = re.compile(r'[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?')


def _valid_upstream_uri(value: str) -> bool:
    match = UPSTREAM_RE.fullmatch(value)
    if not match:
        return False
    return not any(part.strip('.') == '' for part in match.groups())


def _valid_gitea_name(value: str) -> bool:
    return bool(GITEA_NAME_RE.fullmatch(value)) and '..' not in value and not value.endswith('.')


def _valid_branch(value: str) -> bool:
    if not BRANCH_RE.fullmatch(value) or '..' in value or '//' in value or '@{' in value:
        return False
    if value.endswith(('/', '.')) or value == '@':
        return False
    return not any(p.startswith('.') or p.endswith('.lock') for p in value.split('/'))


def _valid_k8s_name(value: str) -> bool:
    return bool(K8S_NAME_RE.fullmatch(value)) and '..' not in value


FIELD_CHECKS = {
    'upstream_uri': (_valid_upstream_uri, 'must be a https://github.com/<owner>/<repo> URL'),
    'gitea_owner': (_valid_gitea_name, 'may only contain letters, digits, "_", "-" and "." (max 100)'),
    'gitea_repo': (_valid_gitea_name, 'may only contain letters, digits, "_", "-" and "." (max 100)'),
    'base_branch': (_valid_branch, 'must be a plain branch name (letters, digits, "_", "-", ".", "/")'),
    'secret_namespace': (lambda v: bool(K8S_LABEL_RE.fullmatch(v)), 'must be a Kubernetes namespace name'),
    'secret_key': (_valid_k8s_name, 'must be a Kubernetes secret name'),
}


def validate_secret_ref(body: dict) -> None:
    """Whitelist check shared by mirrors and webhooks for secret_namespace and secret_key."""
    for field in ('secret_namespace', 'secret_key'):
        if field in body and not FIELD_CHECKS[field][0](body[field]):
            raise BadRequest(f'{field} {FIELD_CHECKS[field][1]}')


def validate_mirror(body, partial: bool) -> dict:
    if not isinstance(body, dict):
        raise BadRequest('Body must be a JSON object')
    unknown = set(body) - set(STRING_FIELDS) - {'enabled'}
    if unknown:
        raise BadRequest(f'Unknown fields: {", ".join(sorted(unknown))}')
    if not partial:
        missing = [f for f in STRING_FIELDS if f not in body]
        if missing:
            raise BadRequest(f'Missing required fields: {", ".join(missing)}')
    for field in STRING_FIELDS:
        if field in body:
            value = body[field]
            if not isinstance(value, str) or not value.strip() or len(value) > MAX_LEN:
                raise BadRequest(f'{field} must be a non-empty string of at most {MAX_LEN} chars')
            check, hint = FIELD_CHECKS[field]
            if not check(value):
                raise BadRequest(f'{field} {hint}')
    if 'enabled' in body and not isinstance(body['enabled'], bool):
        raise BadRequest('enabled must be a boolean')
    return body
