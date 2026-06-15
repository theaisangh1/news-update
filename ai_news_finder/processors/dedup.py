"""Deduplication and grouping by title similarity."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from difflib import SequenceMatcher

from dateutil import parser as date_parser

REDIRECT_HOSTS = ("news.google.com", "feeds.", "feedproxy", "rss.")

STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "from", "that", "this", "will", "have",
        "has", "are", "was", "were", "into", "about", "after", "before", "over",
        "under", "your", "their", "they", "them", "what", "when", "where", "how",
        "why", "who", "its", "our", "you", "can", "may", "new", "says", "said",
        "artificial", "intelligence", "ai", "generative", "machine", "learning",
        "technology", "technologies", "tech", "using", "use", "uses", "used",
    }
)

SIMILARITY_THRESHOLD = 0.64
MIN_SHARED_KEYWORDS = 3


def normalize_title(title: str) -> str:
    t = _strip_outlet_suffix(title)
    t = t.lower()
    t = re.sub(r"[^\w\s]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _strip_outlet_suffix(title: str) -> str:
    """Remove trailing ' - Publisher' common in Google News titles."""
    return re.sub(r"\s(?:-|\|)\s+[^-|]{2,80}$", "", title).strip() or title


def _keywords(title: str) -> set[str]:
    words = normalize_title(title).split()
    return {w for w in words if len(w) > 3 and w not in STOPWORDS}


def _title_similarity(a: str, b: str) -> float:
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    seq = SequenceMatcher(None, na, nb).ratio()
    ka, kb = _keywords(a), _keywords(b)
    if not ka or not kb:
        return seq if seq >= 0.85 else 0.0
    overlap = len(ka & kb)
    jaccard = overlap / len(ka | kb)
    if overlap < 2 and seq < 0.82:
        return 0.0
    # Boost when several distinctive words match (same event, different headlines)
    if overlap >= MIN_SHARED_KEYWORDS:
        jaccard = min(1.0, jaccard + 0.15 * overlap)
    return max(seq, jaccard)


def _is_redirect_url(url: str) -> bool:
    lower = url.lower()
    return any(host in lower for host in REDIRECT_HOSTS)


def _parse_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        dt = date_parser.parse(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _earlier_iso(a: str | None, b: str | None) -> str | None:
    da, db = _parse_date(a), _parse_date(b)
    if da and db:
        return a if da <= db else b
    return a or b


def _better_summary(current: str, candidate: str) -> str:
    if not current:
        return candidate
    if not candidate:
        return current
    return candidate if len(candidate) > len(current) else current


def _append_unique(items: list[str], value: str) -> None:
    value = (value or "").strip()
    if value and value not in items:
        items.append(value)


def _pick_canonical_url(urls: list[str]) -> str:
    for url in urls:
        if url and not _is_redirect_url(url):
            return url
    return urls[0] if urls else ""


def group_stories(stories: list[dict]) -> list[dict]:
    """
    Group stories referring to the same event.
    Returns list of group dicts with title, url, sources, source_count, summary, date, all_urls.
    """
    groups: list[dict] = []

    for story in stories:
        title = story.get("title") or ""
        if not normalize_title(title):
            continue

        matched: dict | None = None
        best_ratio = 0.0
        for group in groups:
            ratio = _title_similarity(title, group["title"])
            if ratio > SIMILARITY_THRESHOLD and ratio >= best_ratio:
                best_ratio = ratio
                matched = group

        if matched is None:
            story_date = story.get("date")
            groups.append(
                {
                    "title": title,
                    "url": story.get("url") or "",
                    "sources": [story.get("source") or "Unknown"],
                    "source_count": 1,
                    "summary": story.get("summary") or "",
                    "all_summaries": [story.get("summary") or ""] if story.get("summary") else [],
                    "all_titles": [title],
                    "source_homes": [story.get("source_home") or ""],
                    "date": story_date,
                    "first_published": story_date,
                    "all_urls": [story.get("url") or ""],
                    "all_sources": [story.get("source") or "Unknown"],
                    "all_source_homes": [story.get("source_home") or ""],
                }
            )
        else:
            src = story.get("source") or "Unknown"
            if src not in matched["sources"]:
                matched["sources"].append(src)
            url = story.get("url") or ""
            if url and url not in matched["all_urls"]:
                matched["all_urls"].append(url)
                matched.setdefault("all_sources", []).append(src)
                matched.setdefault("all_source_homes", []).append(story.get("source_home") or "")
            elif url:
                matched.setdefault("all_sources", [])
                matched.setdefault("all_source_homes", [])
            _append_unique(matched.setdefault("source_homes", []), story.get("source_home") or "")
            _append_unique(matched.setdefault("all_titles", []), title)
            _append_unique(matched.setdefault("all_summaries", []), story.get("summary") or "")
            matched["summary"] = _better_summary(
                matched.get("summary") or "",
                story.get("summary") or "",
            )
            story_date = story.get("date")
            earliest = _earlier_iso(matched.get("first_published"), story_date)
            matched["first_published"] = earliest
            matched["date"] = earliest

    for group in groups:
        seen: set[str] = set()
        unique_sources: list[str] = []
        for s in group["sources"]:
            if s not in seen:
                seen.add(s)
                unique_sources.append(s)
        group["sources"] = unique_sources
        group["source_count"] = len(unique_sources)
        group["url"] = _pick_canonical_url(group["all_urls"])
        group["all_urls"] = [u for u in group["all_urls"] if u]

    return groups
