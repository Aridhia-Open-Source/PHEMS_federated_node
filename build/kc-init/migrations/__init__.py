"""
Ordered, run-once realm migrations, auto-discovered from this package.

Why this exists
---------------
`realms.json` is applied only by `kc.sh start --import-realm`, which skips a realm that already
exists. `partial_import()` in common.py covers the additive case (new top-level roles, groups,
clients, identity providers), but it uses `ifResourceExists: SKIP` and so will never *change*
something already present. Anything that must mutate existing realm configuration goes here.

That includes, notably, everything inside the `global` client: because that client already exists,
partial_import skips it wholesale, and the FederatedNode authz model (the can_* scopes, the role
policies, the scope permissions) lives in its authorizationSettings.

Adding a migration
------------------
Drop a new `mNNN_short_description.py` in this package exporting three names:

    VERSION      = 3                      # int, one greater than the current highest
    DESCRIPTION  = "what it does"         # shown in the realm-init log
    def migrate(admin_token: str): ...    # the work

Discovery is automatic and ordered by VERSION, so nothing else needs editing. Modules whose name
starts with `_` are ignored, which is how a migration can share private helpers.

Contract for a migration
------------------------
- Append only. Never renumber or reorder, and never edit a migration that has shipped -- a
  deployment that already ran it will not run it again.
- Each migration must be idempotent anyway. The version is advanced *per migration* rather than
  once at the end of the batch, so a failure part-way through does not re-run the ones that
  already succeeded, but a migration can still be retried if it fails mid-way itself.
"""
import importlib
import logging
import pkgutil

from common import get_realm_version, set_realm_version

logger = logging.getLogger('realm_migrations')


def _discover():
    """
    Import every migration module in this package and return them ordered by VERSION.

    The validation below is the point of doing this by discovery rather than by hand-maintaining a
    list: two branches that each add "version 3" merge cleanly and would previously have produced a
    list where one of them silently never ran, because the version counter had already passed it.
    """
    by_version = {}
    for found in pkgutil.iter_modules(__path__):
        if found.name.startswith('_'):
            continue
        module = importlib.import_module(f"{__name__}.{found.name}")
        for attr in ("VERSION", "DESCRIPTION", "migrate"):
            if not hasattr(module, attr):
                raise RuntimeError(
                    f"migration module '{found.name}' does not define {attr} -- see the "
                    "'Adding a migration' section in migrations/__init__.py"
                )
        if module.VERSION in by_version:
            raise RuntimeError(
                f"duplicate migration VERSION {module.VERSION}: "
                f"'{by_version[module.VERSION].__name__}' and '{module.__name__}'"
            )
        by_version[module.VERSION] = module

    versions = sorted(by_version)
    if versions != list(range(1, len(versions) + 1)):
        raise RuntimeError(
            f"migration VERSIONs must be contiguous and start at 1, got {versions}"
        )
    return [by_version[v] for v in versions]


MIGRATIONS = _discover()


def run_migrations(admin_token: str):
    """
    Apply every migration newer than the version recorded on the realm.

    The applied version lives in the `fn_realm_version` realm attribute. A realm attribute is used
    rather than a Kubernetes ConfigMap or annotation because realm-init's ServiceAccount is
    read-only (get/watch/list on pods and statefulsets), so a Kubernetes-side marker would mean
    granting it write access.
    """
    current = get_realm_version(admin_token)
    target = MIGRATIONS[-1].VERSION if MIGRATIONS else 0

    # Logged unconditionally so `kubectl logs` answers "did migrations apply?" without guesswork.
    # A permanently failing migration otherwise just looks like a CrashLoopBackOff.
    logger.info(f"Realm migrations: at version {current}, target {target}")

    if current >= target:
        logger.info("Realm is up to date, no migrations to apply")
        return

    for module in MIGRATIONS:
        if module.VERSION <= current:
            continue
        logger.info(f"Applying realm migration {module.VERSION}: {module.DESCRIPTION}")
        module.migrate(admin_token)
        # Advance per migration, not once at the end. Any failure exits the process and the kubelet
        # restarts it, so a batch-level bump would re-run everything that had already succeeded.
        set_realm_version(module.VERSION, admin_token)

    logger.info("Realm migrations complete")
