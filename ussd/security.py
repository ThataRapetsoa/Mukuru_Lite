"""PIN hashing using PBKDF2-HMAC-SHA256 (stdlib, per-user salt).

Format: pbkdf2$<iterations>$<salt_hex>$<hash_hex>
PINs are never stored or logged in plain text.
"""
from __future__ import annotations

import hashlib
import hmac
import os

_ITERATIONS = 200_000
_ALGORITHM = "sha256"


def hash_pin(pin: str) -> str:
	if not pin.isdigit() or len(pin) != 4:
		raise ValueError("PIN must be exactly 4 digits")
	salt = os.urandom(16)
	digest = hashlib.pbkdf2_hmac(_ALGORITHM, pin.encode("ascii"), salt, _ITERATIONS)
	return f"pbkdf2${_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_pin(pin: str, stored: str) -> bool:
	try:
		scheme, iterations, salt_hex, hash_hex = stored.split("$")
		if scheme != "pbkdf2":
			return False
		digest = hashlib.pbkdf2_hmac(
			_ALGORITHM, pin.encode("ascii"), bytes.fromhex(salt_hex), int(iterations)
		)
		return hmac.compare_digest(digest.hex(), hash_hex)
	except (ValueError, AttributeError):
		return False
