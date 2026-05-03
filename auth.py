"""
Run this script once to authenticate with Saxo Bank.
It opens a browser window, you log in, and tokens are saved to tokens.json.
"""
import json
import os
import time
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

APP_KEY = os.getenv("SAXO_APP_KEY")
APP_SECRET = os.getenv("SAXO_APP_SECRET")
AUTH_URL = os.getenv("SAXO_AUTH_URL")
TOKEN_URL = os.getenv("SAXO_TOKEN_URL")
REDIRECT_URI = os.getenv("SAXO_REDIRECT_URI")
TOKENS_FILE = "tokens.json"

auth_code = None


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        params = parse_qs(urlparse(self.path).query)
        if "code" in params:
            auth_code = params["code"][0]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"<h2>Login lykkedes! Du kan lukke dette vindue.</h2>")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Fejl: ingen kode modtaget.")

    def log_message(self, format, *args):
        pass


def get_tokens():
    params = urlencode({
        "response_type": "code",
        "client_id": APP_KEY,
        "redirect_uri": REDIRECT_URI,
    })
    url = f"{AUTH_URL}?{params}"

    server = HTTPServer(("localhost", 8080), CallbackHandler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()

    print("Åbner browser til Saxo login...")
    webbrowser.open(url)
    thread.join(timeout=120)

    if not auth_code:
        print("Fejl: Ingen auth kode modtaget inden timeout.")
        return

    response = requests.post(TOKEN_URL, data={
        "grant_type": "authorization_code",
        "code": auth_code,
        "redirect_uri": REDIRECT_URI,
        "client_id": APP_KEY,
        "client_secret": APP_SECRET,
    })

    tokens = response.json()
    if "access_token" not in tokens:
        print(f"Fejl ved token-hentning: {response.text}")
        return

    tokens["issued_at"] = time.time()
    with open(TOKENS_FILE, "w") as f:
        json.dump(tokens, f, indent=2)

    print(f"Tokens gemt i {TOKENS_FILE}")
    print(f"Access token udloeber om: {tokens.get('expires_in', '?')} sekunder")


if __name__ == "__main__":
    get_tokens()
