"""
Database Session Management
"""
from app.db.base import SessionLocal


def get_db():
    """Dependency for FastAPI routes. Keep transactions short to avoid blocking worker writes (WAL helps)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

