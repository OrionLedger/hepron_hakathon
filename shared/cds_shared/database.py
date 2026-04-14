"""
SQLAlchemy database setup with production-grade connection pool.
Call init_db() once at service startup. Use get_db() as a FastAPI dependency.
"""
from typing import Generator
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase, Session
from sqlalchemy.pool import QueuePool
import structlog

logger = structlog.get_logger(__name__)

_engine = None
_SessionLocal = None


class Base(DeclarativeBase):
    """Declarative base for all ORM models across all services."""
    pass


def init_db(database_url: str) -> None:
    """
    Initialise the database engine and session factory.
    Must be called once during service startup.
    """
    global _engine, _SessionLocal

    _engine = create_engine(
        database_url,
        poolclass=QueuePool,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=3600,
        pool_timeout=30,
        echo=False,
    )

    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

    try:
        with _engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        # Log host only, never credentials
        host_part = database_url.split("@")[-1] if "@" in database_url else "unknown"
        logger.info("database_initialized", host=host_part)
    except Exception as e:
        logger.error("database_init_failed", error=str(e))
        raise


def get_engine():
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    return _engine


def get_db() -> Generator[Session, None, None]:
    """
    FastAPI dependency that yields a transactional database session.
    Commits on success, rolls back on any exception, always closes.
    """
    if _SessionLocal is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    db = _SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def create_all_tables() -> None:
    """Create all mapped tables. For use in tests and initial setup only."""
    if _engine is None:
        raise RuntimeError("Database not initialized. Call init_db() first.")
    Base.metadata.create_all(bind=_engine)
