import hashlib
import hmac
import os
from typing import List, Tuple

from flask import Flask, jsonify, request
from werkzeug.utils import secure_filename

from email_render import render_email_for_telegram
from telegram_client import TelegramClient


app = Flask(__name__)

@app.get("/healthz")
def healthz():
    return jsonify({"ok": True}), 200


def _verify_mailgun_signature(
    signing_key: str, timestamp: str, token: str, signature: str
) -> bool:
    digest = hmac.new(
        signing_key.encode("utf-8"),
        msg=f"{timestamp}{token}".encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(digest, signature)


def _collect_attachments_to_tmp() -> List[Tuple[str, str]]:
    """
    Returns list of (file_path, original_filename).
    Files are saved under /tmp for best-effort handling on Fly.io.
    """
    saved: List[Tuple[str, str]] = []

    for key in request.files:
        for f in request.files.getlist(key):
            if not f or not getattr(f, "filename", None):
                continue

            original_name = f.filename
            safe_name = secure_filename(original_name) or "attachment"
            path = os.path.join("/tmp", safe_name)

            # Avoid collisions if multiple attachments share names.
            if os.path.exists(path):
                base, ext = os.path.splitext(safe_name)
                path = os.path.join("/tmp", f"{base}-{os.urandom(4).hex()}{ext}")

            f.save(path)
            saved.append((path, original_name))

    return saved


@app.post("/email-trigger")
def email_trigger():
    signing_key = os.environ.get("MAILGUN_SIGNING_KEY", "")
    if not signing_key:
        # Misconfiguration: fail fast so it's noticed immediately.
        return jsonify({"ok": False, "error": "MAILGUN_SIGNING_KEY not set"}), 500

    form = request.form
    timestamp = form.get("timestamp", "")
    token = form.get("token", "")
    signature = form.get("signature", "")

    if not (timestamp and token and signature):
        return jsonify({"ok": False, "error": "missing signature fields"}), 400

    if not _verify_mailgun_signature(signing_key, timestamp, token, signature):
        return jsonify({"ok": False, "error": "invalid signature"}), 403

    sender = form.get("sender", "")
    recipient = form.get("recipient", "")  # Mailgun route recipient
    subject = form.get("subject", "")
    body_plain = form.get("body-plain", "")
    body_html = form.get("body-html", "")

    attachment_paths = _collect_attachments_to_tmp()

    tg = TelegramClient.from_env()
    text, link_list = render_email_for_telegram(
        sender=sender,
        recipient=recipient,
        subject=subject,
        body_plain=body_plain,
        body_html=body_html,
    )

    # Send main message first.
    tg.send_message(text)

    # Then send attachments (images/documents) separately.
    for path, original_name in attachment_paths:
        tg.send_file(path=path, filename=original_name)

    # Finally, if we extracted links, send them as a separate message.
    if link_list:
        tg.send_message("\n".join(link_list))

    # --- Example local script execution (disabled by default) ---
    # If you ever want to run a local script instead (or in addition to Telegram),
    # you can enable something like:
    #
    # import subprocess
    # if subject == "RUN JOB" or sender.endswith("@example.com"):
    #     subprocess.run(["python", "your_script.py", "--sender", sender], check=True)
    # -----------------------------------------------------------

    return jsonify({"ok": True}), 200


if __name__ == "__main__":
    # Fly routes to internal port 8080.
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")))

