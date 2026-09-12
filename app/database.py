"""
Database configuration and session management for Belnova Backend API.
Connects to PostgreSQL with connection pooling, automatic schema initialization, and fast-fail timeouts.
"""

import os
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from app.core.config import DATABASE_URL

# Create engine with fast fail connection timeout, connection pool settings, SessionLocal, and declarative Base
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    pool_size=5,
    max_overflow=10,
    connect_args={"connect_timeout": 5}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Database session dependency
def get_db():
    from app.db_migrations import ensure_database_migrated
    ensure_database_migrated()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
