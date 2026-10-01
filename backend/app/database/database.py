import os
from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.database.models import Base


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./mukuru_lite.db")


def build_engine(database_url: str = DATABASE_URL) -> Engine:
	connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
	engine = create_engine(database_url, connect_args=connect_args)
	if database_url.startswith("sqlite"):
		@event.listens_for(engine, "connect")
		def enable_foreign_keys(connection, _record) -> None:
			cursor = connection.cursor()
			cursor.execute("PRAGMA foreign_keys=ON")
			cursor.close()
	return engine


engine = build_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def create_tables() -> None:
	Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
	session = SessionLocal()
	try:
		yield session
	finally:
		session.close()
