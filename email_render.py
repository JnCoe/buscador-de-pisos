from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List, Tuple

from bs4 import BeautifulSoup, Comment


TELEGRAM_MESSAGE_SOFT_LIMIT = 3900
IDEALISTA_SUBJECT_MARKER = "Nuevo piso en tu búsqueda"
IDEALISTA_INMUEBLE_PREFIX = "https://www.idealista.com/inmueble/"
_IDEALISTA_CANONICAL_RE = re.compile(r"^https?://www\.idealista\.com/inmueble/(\d+)/")
_AREA_RE = re.compile(r"\b\d+(?:[.,]\d+)?\s*m(?:²|2)\b", flags=re.IGNORECASE)
_HAB_RE = re.compile(r"\b\d+\s*hab\.?\b", flags=re.IGNORECASE)
_PLANTA_RE = re.compile(
    r"\b(?:\d+\s*(?:ª|º)?|baja|bajo|entresuelo|entreplanta)\s*planta\b",
    flags=re.IGNORECASE,
)
_PRICE_RE = re.compile(
    r"\b\d{1,3}(?:[.\s]\d{3})*(?:[.,]\d+)?\s*€\s*(?:/\s*mes|/mes|€/mes)?\b",
    flags=re.IGNORECASE,
)


@dataclass(frozen=True)
class RenderResult:
    text: str
    links: List[str]


@dataclass(frozen=True)
class IdealistaListing:
    inmueble_id: str
    url: str
    image_url: str
    ubicacion: str
    precio: str | None
    area: str | None
    habitaciones: str | None
    planta: str | None


def _canonicalize_idealista_inmueble_url(url: str) -> tuple[str, str] | None:
    url = (url or "").strip()
    m = _IDEALISTA_CANONICAL_RE.match(url)
    if not m:
        return None
    inmueble_id = m.group(1)
    return inmueble_id, f"{IDEALISTA_INMUEBLE_PREFIX}{inmueble_id}/"


def _extract_first_token(text: str, token: str) -> str | None:
    # Returns the first "word-like" chunk containing token.
    for part in (text or "").split():
        if token in part:
            return part
    return None


def _clean_visible_text(s: str) -> str:
    return " ".join((s or "").replace("\xa0", " ").split()).strip()


def _gather_text_after_anchor(a, *, max_strings: int = 220) -> str:
    """
    Collect nearby visible text *after* the hero-image anchor in document order.
    Stops when encountering the next listing hero-image anchor.
    """
    chunks: List[str] = []
    count = 0

    for el in a.next_elements:
        # Stop at next listing hero card (another inmueble anchor with img).
        if getattr(el, "name", None) == "a":
            href = (el.get("href") or "").strip()
            if href.startswith(IDEALISTA_INMUEBLE_PREFIX) and el.find("img") is not None:
                break

        s = None
        # BeautifulSoup text nodes are usually strings; avoid importing NavigableString type.
        if isinstance(el, str):
            s = _clean_visible_text(el)
        elif getattr(el, "name", None) in ("br", "p", "div", "td", "tr"):
            # Some templates place important info as direct text of a td/tr.
            try:
                s = _clean_visible_text(el.get_text(" ", strip=True))
            except Exception:
                s = None

        if s:
            chunks.append(s)
            count += 1
            if count >= max_strings:
                break

    return " ".join(chunks)

def _extract_price_using_comment_marker(container) -> str | None:
    """
    Idealista emails often include: <!-- precio con logo-->
    We'll use it if present, but keep regex fallbacks for future template changes.
    """
    if not container:
        return None

    try:
        for node in container.find_all(string=lambda s: isinstance(s, Comment)):
            if "precio con logo" not in (str(node) or "").lower():
                continue
            # After the marker comment, the next meaningful text node tends to be the price.
            for nxt in node.next_elements:
                if isinstance(nxt, str) and not isinstance(nxt, Comment):
                    t = _clean_visible_text(nxt)
                    if not t:
                        continue
                    m = _PRICE_RE.search(t)
                    if m:
                        return m.group(0).strip()
                    if "€" in t:
                        # Last-ditch: return the text containing €.
                        return t.strip()
                # stop if we reached a new row/cell after scanning a bit
                if getattr(nxt, "name", None) in ("tr", "table") and nxt is not node:
                    break
    except Exception:
        return None

    return None


def _normalize_precio(precio: str | None) -> str | None:
    if not precio:
        return None
    s = _clean_visible_text(precio)
    # Avoid accidental link creation in Telegram by ensuring a space before "/mes".
    s = re.sub(r"€\s*/\s*mes\b", "€ /mes", s, flags=re.IGNORECASE)
    s = re.sub(r"€/mes\b", "€ /mes", s, flags=re.IGNORECASE)
    return s


def extract_idealista_listings(html: str) -> List[IdealistaListing]:
    """
    Extract Idealista listings from email HTML.

    Strategy (robust to template changes):
    - Find anchors whose href starts with the Idealista inmueble prefix.
    - Prefer anchors that contain an <img> with src+title (hero card).
    - Canonicalize href to https://www.idealista.com/inmueble/<id>/
    - From the anchor's nearby container, parse a line containing m²/hab/planta and a price containing €.
    """
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    results: List[IdealistaListing] = []
    seen_ids: set[str] = set()

    for a in soup.find_all("a"):
        href = (a.get("href") or "").strip()
        if not href.startswith(IDEALISTA_INMUEBLE_PREFIX):
            continue

        canon = _canonicalize_idealista_inmueble_url(href)
        if not canon:
            continue
        inmueble_id, canonical_url = canon
        if inmueble_id in seen_ids:
            continue

        img = a.find("img")
        image_url = (img.get("src") or "").strip() if img else ""
        ubicacion = (img.get("title") or "").strip() if img else ""
        if not ubicacion:
            ubicacion = (a.get("title") or "").strip()
        if not ubicacion:
            ubicacion = _clean_visible_text(a.get_text(" ", strip=True))

        # If there's no image, this anchor likely isn't the listing hero card; skip it
        # (there are multiple inmueble links like "Contactar" that we don't want).
        if not image_url:
            continue

        # Gather text around the card. This template often renders features as loose text
        # inside table cells, so scanning forward from the hero image is more reliable.
        container = a
        for _ in range(5):
            if not container or not getattr(container, "parent", None):
                break
            container = container.parent

        block_text = _clean_visible_text(container.get_text("\n", strip=True)) if container else ""
        after_text = _clean_visible_text(_gather_text_after_anchor(a))

        # Heuristic: price often appears as "1.057 €/mes" (may be split); keep full line if possible.
        precio: str | None = None
        area: str | None = None
        habitaciones: str | None = None
        planta: str | None = None

        # Prefer lines that include key tokens.
        lines = [ln.strip() for ln in (container.get_text("\n", strip=True).splitlines() if container else [])]
        lines = [_clean_visible_text(ln) for ln in lines if _clean_visible_text(ln)]

        # Price: first try explicit comment marker (most stable for this template),
        # then fall back to searching text near the hero image.
        precio = _extract_price_using_comment_marker(container)
        if not precio:
            for source in (after_text, block_text):
                m = _PRICE_RE.search(source)
                if m:
                    precio = m.group(0).strip()
                    break
        if not precio:
            # Last-ditch: first line containing €
            for ln in lines:
                if "€" in ln:
                    precio = ln
                    break
        precio = _normalize_precio(precio)

        # Features: prefer parsing from text after the hero image anchor.
        # Typical: "75 m² 2 hab. 3ª planta"
        for source in (after_text, block_text):
            if not area:
                m = _AREA_RE.search(source)
                if m:
                    area = m.group(0)
            if not habitaciones:
                m = _HAB_RE.search(source)
                if m:
                    habitaciones = m.group(0)
            if not planta:
                m = _PLANTA_RE.search(source)
                if m:
                    planta = m.group(0)
            if area and habitaciones and planta:
                break

        # Extra fallback: sometimes area is expressed as "75 metros" etc (optional; only if m² missing).
        # (Leaving out for now to avoid false positives.)

        # Reduce price noise if it's an overly long line (keep around the € chunk).
        if precio and len(precio) > 80:
            # Keep the shortest substring containing the € token if possible.
            # Otherwise keep first 80 chars.
            euro_idx = precio.find("€")
            if euro_idx != -1:
                start = max(0, euro_idx - 12)
                end = min(len(precio), euro_idx + 12)
                precio = precio[start:end].strip()
            else:
                precio = precio[:80].strip()

        results.append(
            IdealistaListing(
                inmueble_id=inmueble_id,
                url=canonical_url,
                image_url=image_url,
                ubicacion=ubicacion,
                precio=precio,
                area=area,
                habitaciones=habitaciones,
                planta=planta,
            )
        )
        seen_ids.add(inmueble_id)

    return results


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

