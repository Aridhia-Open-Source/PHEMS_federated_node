from urllib.parse import urlparse
from app.helpers.errors import BadRequest

STRING_FIELDS = (
    'upstream_uri', 'secret_namespace', 'secret_key', 'gitea_owner', 'gitea_repo', 'base_branch'
)
MAX_LEN = 256


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
    if 'enabled' in body and not isinstance(body['enabled'], bool):
        raise BadRequest('enabled must be a boolean')
    if 'upstream_uri' in body:
        parsed = urlparse(body['upstream_uri'])
        if parsed.scheme != 'https' or not parsed.netloc:
            raise BadRequest('upstream_uri must be an https URL')
    return body
