import asyncio
import logging

from app.database import engine, dispose_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Worker process entrypoint. Full implementation in Phase 5."""
    logger.info("Worker starting...")
    async with engine.connect() as conn:
        from sqlalchemy import text
        result = await conn.execute(text("SELECT 1"))
        logger.info(f"DB connection verified: {result.scalar()}")
    logger.info("Worker ready (stub — no claim loop yet)")

    # Keep alive until interrupted
    try:
        while True:
            await asyncio.sleep(60)
    except asyncio.CancelledError:
        pass
    finally:
        await dispose_engine()
        logger.info("Worker shut down.")


if __name__ == "__main__":
    asyncio.run(main())
