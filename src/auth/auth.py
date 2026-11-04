import os
import hashlib
import hmac
import base64
import json
import time
from typing import Optional

_DEFAULT_SECRET = "scholar-secure-secret-key-change-in-prod-12345"
SECRET_KEY = os.getenv("JWT_SECRET_KEY", _DEFAULT_SECRET)
ALGORITHM = "HS256"

if SECRET_KEY == _DEFAULT_SECRET:
    # Anyone who has read this (public) source can forge login tokens with the
    # default key. Fine for local dev; must be overridden in any deployment.
    print("[auth] WARNING: JWT_SECRET_KEY is unset — using the insecure built-in "
          "default. Set JWT_SECRET_KEY before deploying.")

# ── Password Hashing using standard library PBKDF2 ──

def hash_password(password: str) -> str:
    """Hashes a password using PBKDF2 HMAC-SHA256 with a random salt."""
    salt = os.urandom(16)
    key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt,
        100000  # 100k iterations
    )
    return f"{salt.hex()}:{key.hex()}"

def verify_password(password: str, hashed: str) -> bool:
    """Verifies a password against its PBKDF2 hash."""
    try:
        salt_hex, key_hex = hashed.split(":")
        salt = bytes.fromhex(salt_hex)
        key = bytes.fromhex(key_hex)
        new_key = hashlib.pbkdf2_hmac(
            'sha256',
            password.encode('utf-8'),
            salt,
            100000
        )
        return hmac.compare_digest(new_key, key)
    except Exception:
        return False

# ── Lightweight stateless JWT-like token implementation ──

def create_access_token(data: dict, expires_delta: int = 86400) -> str:
    """Creates a signed JWT-like access token using HMAC-SHA256."""
    payload = data.copy()
    payload["exp"] = int(time.time()) + expires_delta
    payload_json = json.dumps(payload)
    payload_b64 = base64.urlsafe_b64encode(payload_json.encode()).decode().rstrip("=")
    
    # Signature using HMAC-SHA256
    signature = hmac.new(
        SECRET_KEY.encode(),
        payload_b64.encode(),
        hashlib.sha256
    ).digest()
    sig_b64 = base64.urlsafe_b64encode(signature).decode().rstrip("=")
    
    return f"{payload_b64}.{sig_b64}"

def verify_access_token(token: str) -> Optional[dict]:
    """Verifies and decodes the JWT-like access token."""
    try:
        parts = token.split(".")
        if len(parts) != 2:
            return None
        payload_b64, sig_b64 = parts[0], parts[1]
        
        # Verify signature
        expected_sig = hmac.new(
            SECRET_KEY.encode(),
            payload_b64.encode(),
            hashlib.sha256
        ).digest()
        expected_sig_b64 = base64.urlsafe_b64encode(expected_sig).decode().rstrip("=")
        
        if not hmac.compare_digest(sig_b64, expected_sig_b64):
            return None
        
        # Add padding back to base64
        missing_padding = len(payload_b64) % 4
        if missing_padding:
            payload_b64 += "=" * (4 - missing_padding)
            
        payload_json = base64.urlsafe_b64decode(payload_b64).decode()
        payload = json.loads(payload_json)
        
        # Check expiration
        if payload.get("exp", 0) < time.time():
            return None
            
        return payload
    except Exception:
        return None
