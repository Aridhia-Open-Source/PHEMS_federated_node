from common import enable_user_profile_at_realm_level, set_users_required_fields

VERSION = 1
DESCRIPTION = "baseline: user profile fields and realm-level user profile flag"


def migrate(admin_token: str):
    set_users_required_fields(admin_token)
    enable_user_profile_at_realm_level(admin_token)
