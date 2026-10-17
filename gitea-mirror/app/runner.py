"""Container entry point: the API under waitress plus the sync timer loop in a thread."""
import logging
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from waitress import serve

from app import create_app, delivery
from app.helpers.base_model import db
from app.models.mirror import Mirror
from app.github import RateLimited
from app.sync import MirrorBusy, resync

logger = logging.getLogger(__name__)

STALE_FACTOR = 3  # /health fails when no tick finished for this many intervals


@dataclass
class LoopStatus:
    """What /health reads about the sync loop. Registered as app.extensions['sync_status']."""
    interval: int
    thread: threading.Thread | None = None
    last_tick_at: datetime | None = None

    def __post_init__(self):
        self.started_at = datetime.now(timezone.utc)

    def beat(self) -> None:
        self.last_tick_at = datetime.now(timezone.utc)

    def snapshot(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        alive = bool(self.thread and self.thread.is_alive())
        reference = self.last_tick_at or self.started_at
        stale = (now - reference).total_seconds() > STALE_FACTOR * self.interval
        return {
            'alive': alive,
            'last_tick_at': self.last_tick_at.isoformat() if self.last_tick_at else None,
            'healthy': alive and not stale,
        }


def tick(app, paused: dict, status: LoopStatus | None = None) -> None:
    """
    One timer round: sync each enabled mirror, then attempt due webhook deliveries.
    Each mirror is isolated: whatever it raises, the session is rolled back before the next one.
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
            finally:
                db.session.rollback()  # never hand a poisoned session to the next mirror
                if status:
                    status.beat()
        try:
            delivery.process_due_deliveries(db.session)
        except Exception:
            db.session.rollback()
            logger.exception('Webhook delivery round failed')
        if status:
            status.beat()


def run_loop(app, status: LoopStatus, tick_fn=tick, stop: threading.Event | None = None, sleep=time.sleep) -> None:
    paused: dict = {}
    while not (stop and stop.is_set()):
        try:
            tick_fn(app, paused, status)
        except Exception:
            logger.exception('Sync round failed')
        status.beat()
        sleep(status.interval)


def main():
    app = create_app()
    status = LoopStatus(interval=int(os.environ['GITEA_MIRROR_SYNC_INTERVAL_SECONDS']))
    status.thread = threading.Thread(target=run_loop, args=(app, status), daemon=True, name='sync-timer')
    app.extensions['sync_status'] = status
    status.thread.start()
    serve(app, host='0.0.0.0', port=5000)


if __name__ == '__main__':
    main()
