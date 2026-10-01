import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.database import get_db
from app.database.models import Base
from app.main import create_app


@pytest.fixture
def client():
	engine = create_engine(
		"sqlite://",
		connect_args={"check_same_thread": False},
		poolclass=StaticPool,
	)
	Base.metadata.create_all(engine)
	testing_sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

	def override_get_db():
		with testing_sessions() as session:
			yield session

	application = create_app(initialize_db=False)
	application.dependency_overrides[get_db] = override_get_db
	with TestClient(application) as test_client:
		yield test_client
	application.dependency_overrides.clear()
	engine.dispose()


@pytest.fixture
def user_and_recipient(client):
	user_response = client.post("/users", json={
		"full_name": "Amina Ndlovu",
		"phone_number": "+27123456789",
		"email": None,
	})
	assert user_response.status_code == 201
	user = user_response.json()

	recipient_response = client.post("/recipients", json={
		"user_id": user["id"],
		"full_name": "Tariro Moyo",
		"phone_number": "+263771234567",
		"country": "zw",
		"payout_method": "mobile_money",
		"payout_details": "EcoCash 0771234567",
	})
	assert recipient_response.status_code == 201
	return user, recipient_response.json()


@pytest.fixture
def funded_user_and_recipient(client, user_and_recipient):
	user, recipient = user_and_recipient
	response = client.post("/balances/deposit", json={
		"user_id": user["id"],
		"currency": "USD",
		"amount": "10000.00",
		"idempotency_key": "test-initial-funding",
	})
	assert response.status_code == 201
	return user, recipient
