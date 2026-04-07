import hashlib
import hmac
import os
import time

import requests


def sign(signing_key: str, timestamp: str, token: str) -> str:
    return hmac.new(
        signing_key.encode("utf-8"),
        msg=f"{timestamp}{token}".encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()


def main() -> None:
    url = os.environ.get("LOCAL_URL", "http://127.0.0.1:8080/email-trigger")
    signing_key = os.environ["MAILGUN_SIGNING_KEY"]

    timestamp = str(int(time.time()))
    token = os.urandom(16).hex()
    signature = sign(signing_key, timestamp, token)

    data = {
        "timestamp": timestamp,
        "token": token,
        "signature": signature,
        "sender": os.environ.get("TEST_SENDER", "test@example.com"),
        "recipient": os.environ.get("TEST_RECIPIENT", "route@example.com"),
        "subject": os.environ.get("TEST_SUBJECT", "Local test"),
        "body-plain": os.environ.get("TEST_BODY_PLAIN", "Hello from local test."),
        "body-html": os.environ.get(
            "TEST_BODY_HTML",
            "<p>Hello from <b>local test</b>. <a href='https://example.com'>Example</a></p>",
        ),
    }

    files = {}
    attachment_path = os.environ.get("TEST_ATTACHMENT_PATH", "")
    if attachment_path:
        files["attachment-1"] = open(attachment_path, "rb")

    try:
        resp = requests.post(url, data=data, files=files or None, timeout=15)
        print(resp.status_code, resp.text)
        resp.raise_for_status()
    finally:
        for f in files.values():
            try:
                f.close()
            except Exception:
                pass


if __name__ == "__main__":
    main()

