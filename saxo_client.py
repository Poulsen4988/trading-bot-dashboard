"""
Saxo Bank API client med automatisk token refresh.
"""
import json
import os
import time

import requests
import time as _time
from dotenv import load_dotenv

load_dotenv()

APP_KEY = os.getenv("SAXO_APP_KEY")
APP_SECRET = os.getenv("SAXO_APP_SECRET")
TOKEN_URL = os.getenv("SAXO_TOKEN_URL")
API_BASE = os.getenv("SAXO_API_BASE")
TOKENS_FILE = "tokens.json"


def load_tokens():
    with open(TOKENS_FILE) as f:
        return json.load(f)


def save_tokens(tokens):
    with open(TOKENS_FILE, "w") as f:
        json.dump(tokens, f, indent=2)


def refresh_access_token(tokens):
    response = requests.post(TOKEN_URL, data={
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
        "client_id": APP_KEY,
        "client_secret": APP_SECRET,
    })
    new_tokens = response.json()
    if "access_token" not in new_tokens:
        raise Exception(f"Token refresh fejlede: {response.text}")
    new_tokens["issued_at"] = _time.time()
    save_tokens(new_tokens)
    return new_tokens


def get_valid_token():
    tokens = load_tokens()
    issued_at = tokens.get("issued_at", 0)
    expires_in = tokens.get("expires_in", 1200)
    if time.time() - issued_at > expires_in - 60:
        tokens = refresh_access_token(tokens)
    return tokens["access_token"]


def get(endpoint, params=None):
    token = get_valid_token()
    response = requests.get(
        f"{API_BASE}{endpoint}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
    )
    response.raise_for_status()
    return response.json()


def post(endpoint, body):
    token = get_valid_token()
    response = requests.post(
        f"{API_BASE}{endpoint}",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=body,
    )
    response.raise_for_status()
    return response.json()
