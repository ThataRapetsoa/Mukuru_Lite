from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.services.fx_service import get_rate


def test_fx_rate_changes_between_mock_time_buckets():
	earlier = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
	later = datetime(2026, 10, 1, 12, 30, tzinfo=timezone.utc)

	assert get_rate("USD", "ZAR", earlier) != get_rate("USD", "ZAR", later)


def test_same_currency_rate_is_one():
	assert get_rate("ZAR", "ZAR") == 1


def test_inverse_and_unsupported_rates():
	instant = datetime(2026, 10, 1, 12, 20, tzinfo=timezone.utc)
	forward = get_rate("USD", "ZAR", instant)
	reverse = get_rate("ZAR", "USD", instant)
	assert abs(forward * reverse - 1) < 0.0000001
	with pytest.raises(HTTPException) as error:
		get_rate("ABC", "XYZ")
	assert error.value.status_code == 400


def test_fx_endpoint_returns_utc_timestamp(client):
	response = client.get("/fx/rate?from_currency=USD&to_currency=ZAR")

	assert response.status_code == 200
	assert response.json()["rate"]
	assert response.json()["effective_at"].endswith("Z")
