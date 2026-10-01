import os
from collections.abc import Generator

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from ussd.config import get_settings
from ussd.models import Base


def build_engine(database_url: str | None = None) -> Engine:
	url = database_url or get_settings().database_url
	connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
	engine = create_engine(url, connect_args=connect_args, pool_pre_ping=True)
	if url.startswith("sqlite"):
		@event.listens_for(engine, "connect")
		def _enable_foreign_keys(connection, _record) -> None:
			cursor = connection.cursor()
			cursor.execute("PRAGMA foreign_keys=ON")
			cursor.close()
	return engine


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
	return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def create_tables(engine: Engine) -> None:
	Base.metadata.create_all(bind=engine)


def session_scope(factory: sessionmaker[Session]) -> Generator[Session, None, None]:
	session = factory()
	try:
		yield session
	finally:
		session.close()
