"""Scheduler process: sweeps due delayed jobs, scheduled cron jobs, and stale workers."""
import asyncio
import logging
import signal

from app.config import settings
from app.database import dispose_engine, engine
from app.services.jobs import promote_delayed_jobs, promote_scheduled_jobs
from app.services.workers import sweep_stale_workers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [scheduler] %(message)s",
)
logger = logging.getLogger(__name__)


async def run_scheduler_tick() -> None:
    """Execute a single scheduler sweep cycle across jobs, cron schedules, and workers."""
    async with engine.connect() as conn:
        try:
            # 1. Promote due delayed jobs (scheduled -> queued)
            delayed_count = await promote_delayed_jobs(conn)
            if delayed_count > 0:
                logger.info(f"Promoted {delayed_count} due delayed job(s) to queued")

            # 2. Promote due recurring/scheduled jobs (spawn jobs from scheduled_jobs)
            sched_count = await promote_scheduled_jobs(conn)
            if sched_count > 0:
                logger.info(f"Spawned {sched_count} job(s) from due schedule definition(s)")

            # 3. Sweep dead/stale workers
            stale_count = await sweep_stale_workers(
                conn, timeout_seconds=settings.WORKER_HEARTBEAT_TIMEOUT_SECONDS
            )
            if stale_count > 0:
                logger.warning(f"Swept {stale_count} stale worker(s) and recovered in-flight jobs")

            await conn.commit()
        except Exception as exc:
            await conn.rollback()
            logger.error(f"Error during scheduler sweep: {exc}", exc_info=True)


async def main() -> None:
    """Scheduler process main loop."""
    logger.info("Scheduler process starting...")
    stop_event = asyncio.Event()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            # Windows signal handler fallback
            pass

    logger.info(f"Scheduler ready. Sweep interval: {settings.SCHEDULER_INTERVAL_SECONDS}s")

    try:
        while not stop_event.is_set():
            await run_scheduler_tick()
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=settings.SCHEDULER_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass
    except asyncio.CancelledError:
        logger.info("Scheduler loop cancelled.")
    finally:
        logger.info("Scheduler shutting down...")
        await dispose_engine()
        logger.info("Scheduler shutdown complete.")


if __name__ == "__main__":
    asyncio.run(main())
