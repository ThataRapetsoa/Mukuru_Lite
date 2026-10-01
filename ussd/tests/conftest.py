import os
import sys
from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session, sessionmaker

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from ussd.db import build_engine, build_session_factory, create_tables
from ussd.services.users_service import register_user


@pytest.fixture()
def db_url(tmp_path):
	return f"sqlite:///{tmp_path}/test.db"


@pytest.fixture()
def factory(db_url) -> Generator[sessionmaker[Session], None, None]:
	engine = build_engine(db_url)
	create_tables(engine)
	yield build_session_factory(engine)
	engine.dispose()


@pytest.fixture()
def session(factory):
	with factory() as session:
		yield session


@pytest.fixture()
def alice(session):
	return register_user(session, "Alice", "Smith", "+27820000010", "01.01.1990", "English", "1111")


@pytest.fixture()
def bob(session):
	return register_user(session, "Bob", "Jones", "+26377000011", "02.02.1992", "isiZulu", "2222")
