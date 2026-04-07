from __future__ import annotations

from dataclasses import dataclass
from typing import List, Tuple

from bs4 import BeautifulSoup


TELEGRAM_MESSAGE_SOFT_LIMIT = 3900


@dataclass(frozen=True)
class RenderResult:
    text: str
    links: List[str]


def _extract_links(soup: BeautifulSoup) -> List[str]:
    links: List[str] = []
    seen = set()
    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href:
            continue
        if href in seen:
            continue
        seen.add(href)
        links.append(href)
    return links


def _html_to_text_and_links(html: str) -> Tuple[str, List[str]]:
    soup = BeautifulSoup(html, "html.parser")

    # Remove noisy elements that often carry tracking.
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    links = _extract_links(soup)
    text = soup.get_text("\n", strip=True)

    # Normalize too many blank lines.
    lines = [ln.strip() for ln in text.splitlines()]
    cleaned_lines: List[str] = []
    for ln in lines:
        if not ln:
            if cleaned_lines and cleaned_lines[-1] == "":
                continue
        cleaned_lines.append(ln)
    cleaned = "\n".join(cleaned_lines).strip()
    return cleaned, links


def render_email_for_telegram(
    *,
    sender: str,
    recipient: str,
    subject: str,
    body_plain: str,
    body_html: str,
) -> Tuple[str, List[str]]:
    header_lines = []
    if sender:
        header_lines.append(f"From: {sender}")
    if recipient:
        header_lines.append(f"To: {recipient}")
    if subject:
        header_lines.append(f"Subject: {subject}")
    header = "\n".join(header_lines)

    links: List[str] = []
    body = ""
    if body_html:
        body, links = _html_to_text_and_links(body_html)
    if not body:
        body = (body_plain or "").strip()

    # Keep message compact to reduce delivery failures and retries.
    combined = (header + "\n\n" + body).strip() if header else body
    if len(combined) > TELEGRAM_MESSAGE_SOFT_LIMIT:
        combined = combined[:TELEGRAM_MESSAGE_SOFT_LIMIT] + "\n\n[truncated]"

    # Put links in a separate message; return as display-ready lines.
    link_lines: List[str] = []
    if links:
        link_lines.append("Links:")
        for url in links[:50]:
            link_lines.append(url)
        if len(links) > 50:
            link_lines.append(f"...and {len(links) - 50} more")

    return combined, link_lines

