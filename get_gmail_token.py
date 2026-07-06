"""
Gmail OAuth Refresh Token Tool
Gets a refresh token for the Gmail API using your existing OAuth credentials.

Run:  python get_gmail_token.py
Then: set GOOGLE_REFRESH_TOKEN on Railway with the printed token.
"""
import asyncio
import json
import os
import webbrowser
from urllib.parse import urlencode, urlparse, parse_qs
import httpx

CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
REDIRECT_URI = "http://localhost:8080"
SCOPES = "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.compose https://www.googleapis.com/auth/gmail.modify"

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def get_auth_url() -> str:
    params = {
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPES,
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"{AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(TOKEN_URL, data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        })
        if resp.status_code != 200:
            print(f"Error exchanging code: {resp.status_code}")
            print(resp.text)
            return {}
        return resp.json()


async def main():
    if not CLIENT_ID or not CLIENT_SECRET:
        print("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables first.")
        print("These are on Railway or in your Google Cloud Console.")
        return

    print("=" * 60)
    print("  Gmail OAuth — Get Your Refresh Token")
    print("=" * 60)
    print()
    print("This will:")
    print("  1. Open your browser to Google's login page")
    print("  2. You log in and authorize the app")
    print("  3. Google redirects back to this script")
    print("  4. We exchange the code for a refresh token")
    print()

    # Step 1: Open browser
    auth_url = get_auth_url()
    print("Opening browser...")
    print(f"If it doesn't open, go to: {auth_url[:80]}...")
    print()
    webbrowser.open(auth_url)

    # Step 2: Wait for callback via local server
    print("Waiting for Google to redirect back to localhost:8080...")
    print("(After you authorize, you'll see a 'connection refused' page — that's normal)")
    print()

    # Start a simple HTTP server to catch the callback
    import socket
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("localhost", 8080))
    server.listen(1)
    server.settimeout(120)  # 2 minute timeout

    try:
        conn, addr = server.accept()
        data = conn.recv(4096).decode()
        conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<html><body><h1>Got it!</h1><p>You can close this window.</p></body></html>")
        conn.close()

        # Parse the authorization code from the request
        request_line = data.split("\r\n")[0]
        path = request_line.split(" ")[1]
        query = urlparse(path).query
        params = parse_qs(query)
        code = params.get("code", [None])[0]

        if not code:
            print("❌ No authorization code found in callback.")
            print(f"Request was: {request_line}")
            return

        print("✅ Authorization code received!")
        print()

        # Step 3: Exchange for tokens
        print("Exchanging code for tokens...")
        tokens = await exchange_code(code)

        if not tokens:
            print("❌ Failed to get tokens.")
            return

        refresh_token = tokens.get("refresh_token", "")
        access_token = tokens.get("access_token", "")

        print()
        print("=" * 60)
        print("  SUCCESS! Here's your refresh token:")
        print("=" * 60)
        print()
        print(f"  {refresh_token}")
        print()
        print("=" * 60)
        print()

        email_label = input("  What email is this for? (e.g. you@gmail.com): ").strip() or "unknown"

        print()
        print("For SINGLE account, set on Railway:")
        print(f"  GOOGLE_REFRESH_TOKEN={refresh_token}")
        print()
        print("For MULTIPLE accounts, add to GOOGLE_ACCOUNTS JSON:")
        entry = {"email": email_label, "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET, "refresh_token": refresh_token}
        print(f"  {json.dumps(entry)}")
        print()
        print(f"Access token (temporary): {access_token[:30]}...")
        print()

    except socket.timeout:
        print("❌ Timed out waiting for authorization (2 minutes).")
        print("Try again and make sure to authorize in the browser window.")

    finally:
        server.close()


if __name__ == "__main__":
    asyncio.run(main())
