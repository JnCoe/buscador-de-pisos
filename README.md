# Mailgun → Telegram Email Rerouter (Fly.io)

Lightweight Flask service that receives incoming email webhooks from **Mailgun Routes**, verifies the request signature, and forwards the email content + attachments to **Telegram**.

## What it does

- **Endpoint**: `POST /email-trigger`
- **Security**: Mailgun signature verification (HMAC SHA-256)
- **Forwarding**:
  - Sends a first Telegram message with a readable text rendering (prefers `body-html`, falls back to `body-plain`)
  - Sends attachments/images as separate Telegram uploads
  - Sends extracted links as a final message

## Environment variables

- **MAILGUN_SIGNING_KEY**: Mailgun “Signing key” for webhook verification
- **TELEGRAM_BOT_TOKEN**: Telegram Bot token
- **TELEGRAM_CHAT_ID**: Chat ID (user, group, or channel where the bot can post)

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export MAILGUN_SIGNING_KEY="..."
export TELEGRAM_BOT_TOKEN="..."
export TELEGRAM_CHAT_ID="..."

python app.py
```

Server listens on `http://0.0.0.0:8080`.

## Local secrets: how people usually handle it

- **Local dev**: store secrets in a local `.env` file (already gitignored) or export them in your shell.
- **Fly**: store secrets with `flyctl secrets set ...` (never committed).

If you want a `.env` file, create one like:

```bash
cat > .env <<'EOF'
MAILGUN_SIGNING_KEY=...
TELEGRAM_BOT_TOKEN=...
TELEGRAM_CHAT_ID=...
EOF
```

Then load it into your shell before running:

```bash
set -a
source .env
set +a
python app.py
```

## Simulate a Mailgun webhook locally

This repo includes `simulate_mailgun.py`, which signs a request the same way Mailgun does and posts it to your local server.

1) Start the server (with env vars loaded as above), then run:

```bash
python simulate_mailgun.py
```

Optional overrides:

```bash
export TEST_SUBJECT="Hello"
export TEST_BODY_HTML="<p>hi <a href='https://example.com'>link</a></p>"
export TEST_ATTACHMENT_PATH="/path/to/file.png"
python simulate_mailgun.py
```

## Deploy to Fly.io

1) Install `flyctl` and login:

```bash
flyctl auth login
```

2) Launch (use existing `fly.toml` / `Dockerfile`):

```bash
flyctl launch
```

3) Set secrets:

```bash
flyctl secrets set \
  MAILGUN_SIGNING_KEY="..." \
  TELEGRAM_BOT_TOKEN="..." \
  TELEGRAM_CHAT_ID="..."
```

4) Deploy:

```bash
flyctl deploy
```

## Configure Mailgun Inbound Route

In Mailgun, create an **Inbound Route** that forwards to:

`https://<your-fly-app>.fly.dev/email-trigger`

Mailgun will send `multipart/form-data` including:
- `timestamp`, `token`, `signature`
- `sender`, `recipient`, `subject`, `body-plain`, `body-html`
- attachments in `request.files`

## Troubleshooting

- **403 invalid signature**: verify `MAILGUN_SIGNING_KEY` matches the domain’s webhook signing key.
- **500 missing env vars**: ensure Fly secrets are set and the machine restarted (`flyctl deploy` will restart).
- **Telegram errors**: confirm the bot is allowed to post to the chat, and `TELEGRAM_CHAT_ID` is correct.