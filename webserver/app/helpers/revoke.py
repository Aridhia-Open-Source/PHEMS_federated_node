from flask import g

from app.helpers.base_model import db
from app.helpers.exceptions import UnauthorizedError


def revoke_links(links) -> list[int]:
    """
    Admin only. Revokes every one of the links of a global resource at once, like
    revoking a single link. Revoking a revoked link changes nothing. Returns the link ids.
    """
    if not g.caller_is_admin:
        raise UnauthorizedError("Only an admin can revoke a link")
    links = list(links)
    for link in links:
        link.revoked = True
    db.session.commit()
    return [link.id for link in links]
