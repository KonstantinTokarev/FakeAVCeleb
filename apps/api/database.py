from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base
from .config import settings

url = settings.database_url
if url.startswith("postgresql://"):
    url = url.replace("postgresql://", "postgresql+asyncpg://", 1)

engine = create_async_engine(url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


async def init_db():
    from . import models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Idempotent schema migrations for columns added after initial deploy
        await _migrate(conn)


async def _migrate(conn):
    """Add new columns to existing tables without dropping data."""
    migrations = [
        "ALTER TABLE results ADD COLUMN IF NOT EXISTS verdict VARCHAR(32)",
        "ALTER TABLE results ADD COLUMN IF NOT EXISTS sub_scores JSON",
        "ALTER TABLE results ADD COLUMN IF NOT EXISTS findings JSON",
        "ALTER TABLE results ADD COLUMN IF NOT EXISTS flagged_frames JSON",
    ]
    for sql in migrations:
        try:
            await conn.execute(__import__("sqlalchemy").text(sql))
        except Exception:
            # SQLite doesn't support IF NOT EXISTS on ALTER TABLE; ignore errors there
            pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
