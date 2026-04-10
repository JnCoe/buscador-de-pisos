import hashlib
import hmac
import os
from typing import List, Tuple

from flask import Flask, jsonify, request
from werkzeug.utils import secure_filename

from email_render import IDEALISTA_SUBJECT_RE, extract_idealista_listings, render_email_for_telegram
from telegram_client import TelegramClient


app = Flask(__name__)
IGNORED_SUBJECTS = {
    "Uno de tus favoritos ya no está publicado",
    "Resumen diario de nuevos anuncios",
}

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

    if (subject or "").strip() in IGNORED_SUBJECTS:
        return jsonify({"ok": True, "ignored": True}), 200

    attachment_paths = _collect_attachments_to_tmp()

    tg = TelegramClient.from_env()

    # Idealista formatted flow.
    if IDEALISTA_SUBJECT_RE.search(subject or "") and body_html:
        listings = extract_idealista_listings(body_html)
        for listing in listings:
            lines: List[str] = []
            lines.append("🚨NUEVO PISO🚨")
            if listing.ubicacion:
                lines.append(listing.ubicacion)
            lines.append("")
            if listing.precio:
                lines.append(listing.precio)
            if listing.area:
                lines.append(listing.area)
            if listing.habitaciones:
                lines.append(listing.habitaciones)
            if listing.planta:
                lines.append(listing.planta)
            lines.append("")
            lines.append(f'<a href="{listing.url}">{listing.inmueble_id}</a>')
            caption = "\n".join(lines).strip()

            try:
                local_img = tg.download_to_tmp(
                    listing.image_url, filename_hint=f"idealista-{listing.inmueble_id}", timeout=5.0
                )
                tg.send_photo(
                    path=local_img,
                    filename=os.path.basename(local_img),
                    caption=caption,
                    parse_mode="HTML",
                )
            except Exception as exc:
                # Fallback: log + text-only message.
                tg.send_message(
                    f"[idealista] Image download failed ({exc}). Sending text only."
                )
                tg.send_message(caption, parse_mode="HTML")

        return jsonify({"ok": True, "idealista_listings": len(listings)}), 200

    # Default generic flow for all other emails.
    text, link_list = render_email_for_telegram(
        sender=sender,
        recipient=recipient,
        subject=subject,
        body_plain=body_plain,
        body_html=body_html,
    )

    tg.send_message(text)

    for path, original_name in attachment_paths:
        tg.send_file(path=path, filename=original_name)

    if link_list:
        tg.send_message("\n".join(link_list), parse_mode="HTML")

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

