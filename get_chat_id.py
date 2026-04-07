# get_chat_id.py
import os
import sys
import requests


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("Missing TELEGRAM_BOT_TOKEN in environment.", file=sys.stderr, flush=True)
        print(
            "Tip: set it in .env, then run: set -a; source .env; set +a",
            file=sys.stderr,
            flush=True,
        )
        return 2

    url = f"https://api.telegram.org/bot{token}/getUpdates"
    session = requests.Session()
    # Avoid broken corporate/WSL proxy env vars interfering with Telegram calls.
    session.trust_env = False
    try:
        resp = session.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.ProxyError as exc:
        print(
            "Network/proxy error reaching api.telegram.org.",
            file=sys.stderr,
            flush=True,
        )
        print(
            "If you have HTTPS_PROXY/HTTP_PROXY set, try: unset HTTPS_PROXY HTTP_PROXY ALL_PROXY",
            file=sys.stderr,
            flush=True,
        )
        print(f"Details: {exc}", file=sys.stderr, flush=True)
        return 3
    except requests.exceptions.RequestException as exc:
        print(
            "Network error reaching api.telegram.org.",
            file=sys.stderr,
            flush=True,
        )
        print(
            "If you're on WSL/behind a firewall, make sure DNS and outbound HTTPS work.",
            file=sys.stderr,
            flush=True,
        )
        print(f"Details: {exc}", file=sys.stderr, flush=True)
        return 4

    if not data.get("ok"):
        print(f"Telegram API returned ok=false: {data}", file=sys.stderr)
        return 1

    results = data.get("result", [])
    if not results:
        print("No updates found.", flush=True)
        print("Do this, then re-run:", flush=True)
        print("- In the Telegram group, send a message like: /start (or any text)", flush=True)
        print("- If privacy mode is ON, mention the bot or use a command.", flush=True)
        return 0

    seen = set()
    print("Chats seen in getUpdates():", flush=True)
    print("(Copy the chat id you want into TELEGRAM_CHAT_ID)", flush=True)
    print("", flush=True)

    for upd in results:
        msg = upd.get("message") or upd.get("channel_post") or upd.get("edited_message") or upd.get("edited_channel_post")
        if not msg:
            continue

        chat = msg.get("chat") or {}
        chat_id = chat.get("id")
        chat_type = chat.get("type")
        title = chat.get("title") or ""
        username = chat.get("username") or ""
        text = msg.get("text") or ""

        key = (chat_id, chat_type, title, username)
        if key in seen:
            continue
        seen.add(key)

        print(
            f"- chat_id={chat_id} type={chat_type} title={title!r} username={username!r} sample_text={text!r}",
            flush=True,
        )

    print("", flush=True)
    print("If you don't see the group:", flush=True)
    print("- Make sure the bot is added to the group", flush=True)
    print("- Send a new message in the group", flush=True)
    print("- If privacy mode is ON, mention the bot or use /command", flush=True)
    print("- Try removing webhook (if you set one elsewhere):", flush=True)
    print("  https://api.telegram.org/bot<token>/deleteWebhook", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())