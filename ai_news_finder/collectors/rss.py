"""RSS feed collector — no API key required."""

from __future__ import annotations

import logging
import html
import json
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from functools import lru_cache
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlparse

import feedparser
import requests
from dateutil import parser as date_parser

logger = logging.getLogger(__name__)

USER_AGENT = "AINewsFinder/1.0 (educational project)"
BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)
TIMEOUT = 10

# (display name, feed URL)
FEEDS = [
    ("TechCrunch AI", "https://techcrunch.com/category/artificial-intelligence/feed/"),
    ("VentureBeat AI", "https://venturebeat.com/category/ai/feed/"),
    ("Ars Technica", "https://feeds.arstechnica.com/arstechnica/technology-lab"),
    ("MIT Tech Review", "https://www.technologyreview.com/feed/"),
    ("The Verge", "https://www.theverge.com/rss/index.xml"),
    ("Wired AI", "https://www.wired.com/feed/tag/ai/latest/rss"),
    ("ZDNet AI", "https://www.zdnet.com/topic/artificial-intelligence/rss.xml"),
    ("InfoQ AI", "https://feed.infoq.com/"),
]

GOOGLE_NEWS_QUERIES = [
    "artificial+intelligence",
    "OpenAI+OR+ChatGPT+OR+Claude+OR+Gemini",
    "machine+learning+OR+LLM",
]


class _MetaSummaryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.candidates: list[str] = []
        self.paragraphs: list[str] = []
        self.json_ld_blocks: list[str] = []
        self.canonical_urls: list[str] = []
        self.titles: list[str] = []
        self.article_headlines: list[str] = []
        self._capture_paragraph = False
        self._capture_json_ld = False
        self._capture_title = False
        self._paragraph_parts: list[str] = []
        self._json_ld_parts: list[str] = []
        self._title_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = tag.lower()
        if tag_name == "meta":
            attr_map = {k.lower(): v or "" for k, v in attrs}
            key = (attr_map.get("property") or attr_map.get("name") or "").lower()
            if key in {"description", "og:description", "twitter:description"}:
                self.candidates.append(attr_map.get("content", ""))
            if key == "og:url" and attr_map.get("content"):
                self.canonical_urls.append(attr_map["content"])
            if key in {"og:title", "twitter:title"} and attr_map.get("content"):
                self.titles.append(_clean_feed_text(attr_map["content"]))
        elif tag_name == "link":
            attr_map = {k.lower(): v or "" for k, v in attrs}
            rel = (attr_map.get("rel") or "").lower()
            href = attr_map.get("href") or ""
            if href and "canonical" in rel:
                self.canonical_urls.append(href)
        elif tag_name in {"p", "div"}:
            if tag_name == "p":
                self._capture_paragraph = True
                self._paragraph_parts = []
        elif tag_name == "script":
            attr_map = {k.lower(): v or "" for k, v in attrs}
            script_type = (attr_map.get("type") or "").lower()
            if "ld+json" in script_type:
                self._capture_json_ld = True
                self._json_ld_parts = []
        elif tag_name in {"h1", "h2", "title"}:
            self._capture_title = True
            self._title_parts = []

    def handle_endtag(self, tag: str) -> None:
        tag_name = tag.lower()
        if tag_name == "p" and self._capture_paragraph:
            text = _clean_feed_text(" ".join(self._paragraph_parts))
            if len(text.split()) >= 10:
                self.paragraphs.append(text)
            self._capture_paragraph = False
            self._paragraph_parts = []
        elif tag_name == "script" and self._capture_json_ld:
            block = " ".join(self._json_ld_parts).strip()
            if block:
                self.json_ld_blocks.append(block)
            self._capture_json_ld = False
            self._json_ld_parts = []
        elif tag_name in {"h1", "h2", "title"} and self._capture_title:
            title = _clean_feed_text(" ".join(self._title_parts))
            if title:
                self.article_headlines.append(title)
            self._capture_title = False
            self._title_parts = []

    def handle_data(self, data: str) -> None:
        if self._capture_paragraph:
            self._paragraph_parts.append(data)
        elif self._capture_json_ld:
            self._json_ld_parts.append(data)
        elif self._capture_title:
            self._title_parts.append(data)


def _google_news_url(query: str) -> str:
    q = quote_plus(query)
    return (
        f"https://news.google.com/rss/search?q={q}"
        "&hl=en-US&gl=US&ceid=US:en"
    )


def _fetch_feed(url: str) -> bytes | str | None:
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            },
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()
        return resp.content
    except Exception as exc:
        logger.warning("RSS fetch failed (%s): %s", url, exc)
        return None


def _parse_entry_date(entry: Any) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
    for attr in ("published", "updated"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                dt = date_parser.parse(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except (ValueError, TypeError):
                pass
    return None


def _clean_feed_text(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", html.unescape(raw or ""))
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\bContinue reading\b.*$", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\bRead more\b.*$", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\bThe post .+? appeared first on .+?\.$", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\bBy [A-Z][A-Za-z .'-]{2,80}$", "", text).strip()
    return text


def _looks_weak_summary(summary: str, title: str) -> bool:
    clean = _clean_feed_text(summary)
    clean_title = _clean_feed_text(title)
    if not clean:
        return True
    if len(clean.split()) < 10:
        return True
    clean_l = re.sub(r"\s(?:-|\|)\s+[^-|]{2,80}$", "", clean).lower()
    title_l = re.sub(r"\s(?:-|\|)\s+[^-|]{2,80}$", "", clean_title).lower()
    return clean_l in title_l or title_l in clean_l


def _is_redirect_url(url: str) -> bool:
    host = urlparse(url or "").netloc.lower()
    return "news.google.com" in host or "feedproxy" in host


def _sentence_split(text: str) -> list[str]:
    protected = text
    replacements = {
        "U.S.": "U<S>",
        "U.K.": "U<K>",
        "E.U.": "E<U>",
        "Mr.": "Mr<dot>",
        "Ms.": "Ms<dot>",
        "Dr.": "Dr<dot>",
    }
    for original, marker in replacements.items():
        protected = protected.replace(original, marker)
    sentences = []
    for sentence in re.split(r"(?<=[.!?])\s+", protected):
        for original, marker in replacements.items():
            sentence = sentence.replace(marker, original)
        if sentence.strip():
            sentences.append(sentence.strip())
    return sentences


def _jsonld_article_texts(blocks: list[str]) -> list[str]:
    texts: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key in ("articleBody", "description"):
                text = value.get(key)
                if isinstance(text, str):
                    clean = _clean_feed_text(text)
                    if clean:
                        texts.append(clean)
            for child in value.values():
                if isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    for block in blocks:
        try:
            visit(json.loads(block))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue

    unique: list[str] = []
    for text in texts:
        if text not in unique:
            unique.append(text)
    return unique


def _keywords(text: str) -> set[str]:
    stopwords = {
        "about", "after", "again", "against", "also", "amid", "among", "and",
        "are", "artificial", "because", "been", "being", "but", "can", "could",
        "from", "has", "have", "how", "into", "its", "machine", "more", "new",
        "not", "said", "says", "that", "the", "their", "this", "through", "was",
        "were", "what", "when", "where", "which", "while", "will", "with",
        "using", "real", "time", "improves", "announces", "brings",
    }
    words = re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", text.lower())
    return {w for w in words if w not in stopwords}


def _article_sentence_score(sentence: str, title_keywords: set[str], seen: set[str]) -> int:
    words = sentence.split()
    if len(words) < 10 or len(words) > 55:
        return -100
    lower = sentence.lower()
    noisy_phrases = (
        "subscribe", "newsletter", "cookie", "advertisement", "sign up",
        "live updates", "seems to be getting", "click here", "read our",
        "affiliate links", "earn us a commission",
    )
    if any(bad in lower for bad in noisy_phrases) or "…" in sentence:
        return -100
    overlap_terms = _keywords(sentence) & title_keywords
    weak_terms = {"code", "model", "models", "agent", "agents", "using", "real", "time"}
    kw_overlap = len(overlap_terms)
    if title_keywords and (kw_overlap == 0 or overlap_terms <= weak_terms):
        return -100
    novelty = len(_keywords(sentence) - seen)
    return (kw_overlap * 5) + min(novelty, 12) + min(len(words), 35)


def _build_detailed_summary(title: str, snippets: list[str]) -> str:
    title_keywords = _keywords(title)
    sentences: list[tuple[int, str]] = []
    for snippet in snippets:
        for sentence in _sentence_split(snippet):
            sentences.append((_article_sentence_score(sentence, title_keywords, set()), sentence))

    chosen: list[str] = []
    seen_keywords: set[str] = set()
    for initial_score, sentence in sentences:
        if len(chosen) >= 7:
            break
        clean = _clean_feed_text(sentence)
        score = _article_sentence_score(clean, title_keywords, seen_keywords)
        if initial_score < 0 or score < 18:
            continue
        if not clean or clean in chosen or _looks_weak_summary(clean, title):
            continue
        if any(clean.lower() in existing.lower() or existing.lower() in clean.lower() for existing in chosen):
            continue
        chosen.append(clean)
        seen_keywords.update(_keywords(clean))

    if len(chosen) < 3:
        ranked = sorted(sentences, key=lambda item: item[0], reverse=True)
        for _, sentence in ranked:
            if len(chosen) >= 7:
                break
            clean = _clean_feed_text(sentence)
            if not clean or clean in chosen or _looks_weak_summary(clean, title):
                continue
            if _article_sentence_score(clean, title_keywords, seen_keywords) < 18:
                continue
            chosen.append(clean)
            seen_keywords.update(_keywords(clean))

    if not chosen:
        return ""

    summary = " ".join(chosen)
    words = summary.split()
    if len(words) > 260:
        summary = " ".join(words[:260]).rsplit(" ", 1)[0].rstrip(",;:") + "..."
    return summary


def _best_article_summary(title: str, snippets: list[str]) -> str:
    """Build a multi-sentence article summary when ranked extraction is sparse."""
    sentences: list[str] = []
    for snippet in snippets:
        clean_snippet = _clean_feed_text(snippet)
        if not clean_snippet or len(clean_snippet.split()) < 10:
            continue
        sentences.extend(_sentence_split(clean_snippet))

    if not sentences:
        return ""

    chosen: list[str] = []

    def usable(sentence: str) -> bool:
        clean = _clean_feed_text(sentence)
        words = clean.split()
        lower = clean.lower()
        noisy_phrases = (
            "subscribe", "newsletter", "cookie", "advertisement", "sign up",
            "live updates", "click here", "read our", "all rights reserved",
            "affiliate links", "earn us a commission",
        )
        if len(words) < 10 or len(words) > 65:
            return False
        if any(bad in lower for bad in noisy_phrases):
            return False
        return not any(clean.lower() in existing.lower() or existing.lower() in clean.lower() for existing in chosen)

    for sentence in sentences:
        if len(chosen) >= 7:
            break
        clean = _clean_feed_text(sentence)
        if not usable(clean):
            continue
        chosen.append(clean)

    if not chosen:
        return ""

    summary = " ".join(chosen)
    words = summary.split()
    if len(words) > 260:
        summary = " ".join(words[:260]).rsplit(" ", 1)[0].rstrip(",;:") + "..."
    return summary


def _article_matches_title(title: str, text: str) -> bool:
    title_clean = _clean_feed_text(title).lower()
    text_clean = _clean_feed_text(text).lower()
    if not title_clean or not text_clean:
        return True

    title_keywords = _keywords(title_clean)
    text_keywords = _keywords(text_clean)
    overlap = title_keywords & text_keywords
    ai_terms = {
        "ai", "anthropic", "claude", "chatgpt", "gemini", "openai", "nvidia",
        "artificial intelligence", "machine learning", "llm",
    }
    title_ai_terms = {term for term in ai_terms if term in title_clean}
    if title_ai_terms and not any(term in text_clean for term in title_ai_terms):
        return False
    return len(overlap) >= 2 or bool(title_ai_terms and overlap)


def _article_title_matches(expected_title: str, article_titles: list[str]) -> bool:
    expected = _clean_title_for_search(expected_title).lower()
    expected_keywords = _keywords(expected)
    if not expected or not article_titles:
        return True
    for article_title in article_titles:
        actual = _clean_title_for_search(article_title).lower()
        if not actual:
            continue
        actual_keywords = _keywords(actual)
        if expected in actual or actual in expected:
            return True
        overlap = expected_keywords & actual_keywords
        if len(overlap) >= max(2, min(5, len(expected_keywords) - 1)):
            return True
        if SequenceMatcher(None, expected, actual).ratio() >= 0.50:
            return True
    return False


def _prefer_fuller_summary(ranked_summary: str, article_summary: str) -> str:
    if not ranked_summary:
        return article_summary
    if not article_summary:
        return ranked_summary
    ranked_words = len(ranked_summary.split())
    article_words = len(article_summary.split())
    if article_words >= 100 and article_words >= int(ranked_words * 0.65):
        return article_summary
    if ranked_words < 100 and article_words > ranked_words + 20:
        return article_summary
    return ranked_summary


def _is_detailed_article_summary(summary: str) -> bool:
    clean = _clean_feed_text(summary)
    if len(clean.split()) < 60:
        return False
    return len(_sentence_split(clean)) >= 2


def _resolve_redirect_url(url: str) -> str:
    if not url:
        return ""
    try:
        resp = requests.get(
            url,
            headers={
                "User-Agent": BROWSER_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
            timeout=TIMEOUT,
            allow_redirects=True,
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Redirect URL resolution failed (%s): %s", url, exc)
        return ""
    return resp.url if resp.url and not _is_redirect_url(resp.url) else ""


def fetch_article_details(url: str, title: str = "") -> dict:
    """Fetch article metadata and paragraph text for richer reporting."""
    if not url:
        return {}

    user_agents = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    ]

    for ua in user_agents:
        try:
            resp = requests.get(
                url,
                headers={
                    "User-Agent": ua,
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.9",
                    "Cache-Control": "no-cache",
                    "Referer": "https://www.google.com/",
                },
                timeout=TIMEOUT,
                allow_redirects=True,
            )
            resp.raise_for_status()
            break
        except requests.exceptions.HTTPError as e:
            if e.response.status_code in (403, 401):
                logger.debug(f"Access blocked ({e.response.status_code}) for {url}, trying next UA...")
                continue
            logger.debug("Article summary fetch failed (%s): %s", url, e)
            return {}
        except Exception as exc:
            logger.debug("Article summary fetch failed (%s): %s", url, exc)
            return {}
    else:
        logger.debug("All User-Agents blocked for %s", url)
        return {}

    parser = _MetaSummaryParser()
    try:
        parser.feed(resp.text[:1_000_000])
    except Exception:
        return {}

    jsonld_summaries = []
    for text in _jsonld_article_texts(parser.json_ld_blocks):
        if text and not (len(text.split()) < 30 and _looks_weak_summary(text, title)):
            jsonld_summaries.append(text)
    candidates = [_clean_feed_text(c) for c in parser.candidates]
    meta_summaries = [c for c in candidates if c and not _looks_weak_summary(c, title)]
    paragraphs = [p for p in parser.paragraphs if p]
    article_texts = [*jsonld_summaries, *paragraphs[:40]]
    article_text = "\n".join(article_texts)
    if not _article_title_matches(title, [*parser.titles, *parser.article_headlines]):
        return {}
    if article_text and not _article_matches_title(title, article_text):
        return {}
    detail_snippets = [*article_texts, *meta_summaries]
    detailed_summary = _build_detailed_summary(title, detail_snippets)
    article_summary = _best_article_summary(title, detail_snippets)
    canonical_url = next(
        (u for u in parser.canonical_urls if u and not _is_redirect_url(u)),
        "",
    )
    return {
        "url": canonical_url or resp.url,
        "meta_summary": max(meta_summaries, key=len) if meta_summaries else "",
        "detailed_summary": _prefer_fuller_summary(detailed_summary, article_summary),
        "article_text": article_text,
        "paragraphs": paragraphs[:40],
    }


def fetch_article_summary(url: str, title: str = "") -> str:
    """Fetch article-derived summary text, preferring richer article content."""
    details = fetch_article_details(url, title)
    return details.get("detailed_summary") or details.get("meta_summary") or ""


def _resolve_article_link(title: str, url: str, source_home: str, source: str = "") -> str:
    if not _is_redirect_url(url):
        return url
    resolved = _resolve_redirect_url(url)
    if resolved:
        return resolved
    source_home = source_home or _source_home_from_label(source)
    discovered = discover_article_url(title, source_home) if source_home else ""
    if not discovered:
        discovered = discover_article_url_by_source(title, source)
    if discovered:
        return discovered
    return url


def _read_more_links(story: dict, limit: int = 10) -> list[dict[str, str]]:
    urls = story.get("all_urls") or [story.get("url") or ""]
    sources = story.get("all_sources") or story.get("sources") or []
    source_homes = story.get("all_source_homes") or story.get("source_homes") or []
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for idx, url in enumerate(urls):
        if not url or url in seen:
            continue
        seen.add(url)
        source = sources[idx] if idx < len(sources) else urlparse(url).netloc or "Article"
        source_home = source_homes[idx] if idx < len(source_homes) else (source_homes[0] if source_homes else "")
        article_url = _resolve_article_link(story.get("title") or "", url, source_home, source)
        links.append({
            "url": article_url,
            "source": source,
            "original_url": url,
            "source_home": source_home,
        })
        if len(links) >= limit:
            break
    return links


def enrich_story_summaries(stories: list[dict]) -> None:
    """Improve selected stories with richer summaries and read-further links."""
    for idx, story in enumerate(stories, 1):
        title = story.get("title") or ""
        original_summary = story.get("summary") or ""
        story["read_more_links"] = _read_more_links(story, limit=10)
        article_texts: list[str] = []
        detail_texts: list[str] = []
        fetched_count = 0

        for link in story["read_more_links"]:
            if fetched_count >= 3:
                break
            details = fetch_article_details(link["url"], title)
            if not details and _is_redirect_url(link.get("original_url") or ""):
                fallback_url = discover_article_url_by_source(title, link.get("source") or "")
                if fallback_url and fallback_url != link["url"]:
                    link["url"] = fallback_url
                    details = fetch_article_details(fallback_url, title)
            if not details:
                logger.debug(f"Story #{idx}: Failed to fetch from {link.get('source', 'Unknown')}")
                continue
            fetched_count += 1
            final_url = details.get("url") or link["url"]
            if final_url:
                link["url"] = final_url
            article_text = details.get("article_text") or ""
            if article_text:
                article_texts.append(article_text)
            for key in ("detailed_summary", "meta_summary"):
                value = details.get(key) or ""
                if value:
                    detail_texts.append(value)

        summaries = story.setdefault("all_summaries", [])
        for text in detail_texts:
            if text and text not in summaries:
                summaries.append(text)

        summary_pool = [*article_texts, *detail_texts] if article_texts or detail_texts else [*summaries]
        detailed = _prefer_fuller_summary(
            _build_detailed_summary(title, summary_pool),
            _best_article_summary(title, summary_pool),
        )

        if detailed and _is_detailed_article_summary(detailed):
            story["detailed_summary"] = detailed
            story["summary"] = detailed
        elif original_summary and len(original_summary.split()) >= 20:
            story["summary"] = original_summary
            story["detailed_summary"] = original_summary
        elif _looks_weak_summary(story.get("summary") or "", title):
            fetched = fetch_article_summary(story.get("url") or "", title)
            if fetched and _is_detailed_article_summary(fetched):
                story["summary"] = fetched
                story["detailed_summary"] = fetched
                if fetched not in summaries:
                    summaries.append(fetched)


def _entry_summary(entry: Any) -> str:
    candidates: list[str] = []
    for key in ("summary", "description"):
        raw = entry.get(key) or ""
        if raw:
            candidates.append(_clean_feed_text(raw))

    for content in entry.get("content") or []:
        raw = content.get("value") if isinstance(content, dict) else ""
        if raw:
            candidates.append(_clean_feed_text(raw))

    candidates = [c for c in candidates if c]
    if not candidates:
        return ""
    return max(candidates, key=len)


def _publisher_from_title(title: str) -> str | None:
    """Google News titles often end with ' - Publisher Name'."""
    m = re.search(r"\s(?:-|\|)\s+(.+?)\s*$", title)
    if m:
        pub = m.group(1).strip()
        if len(pub) > 2 and len(pub) < 80:
            return pub
    return None


def _source_label(feed_name: str, title: str) -> str:
    if feed_name.startswith("Google News"):
        publisher = _publisher_from_title(title)
        if publisher:
            return publisher
    return feed_name


def _entry_source_home(entry: Any) -> str:
    source = entry.get("source") or {}
    href = source.get("href") if isinstance(source, dict) else ""
    return href or ""


def _clean_title_for_search(title: str) -> str:
    cleaned = re.sub(r"\s(?:-|\|)\s+[^-|]{2,80}$", "", title).strip() or title
    cleaned = re.sub(r"[“”\"'’]", "", cleaned)
    cleaned = re.sub(r"[—–-]", " ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _slugify_title(title: str) -> str:
    cleaned = _clean_title_for_search(title).lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned)
    return cleaned.strip("-")


def _same_site(url: str, source_home: str) -> bool:
    candidate_host = urlparse(url or "").netloc.lower().removeprefix("www.")
    source_host = urlparse(source_home or "").netloc.lower().removeprefix("www.")
    return bool(candidate_host and source_host and (candidate_host == source_host or candidate_host.endswith("." + source_host)))


SOURCE_HOME_BY_LABEL = {
    "android authority": "https://www.androidauthority.com",
    "android police": "https://www.androidpolice.com",
    "ars technica": "https://arstechnica.com",
    "gizmodo": "https://gizmodo.com",
    "investing.com": "https://www.investing.com",
    "mashable": "https://mashable.com",
    "mit tech review": "https://www.technologyreview.com",
    "pbs": "https://www.pbs.org",
    "techcrunch": "https://techcrunch.com",
    "techcrunch ai": "https://techcrunch.com",
    "the street": "https://www.thestreet.com",
    "thestreet": "https://www.thestreet.com",
    "the verge": "https://www.theverge.com",
    "venturebeat": "https://venturebeat.com",
    "venturebeat ai": "https://venturebeat.com",
    "wired": "https://www.wired.com",
    "wired ai": "https://www.wired.com",
    "zdnet": "https://www.zdnet.com",
    "zdnet ai": "https://www.zdnet.com",
}


def _source_home_from_label(source: str) -> str:
    clean = re.sub(r"\s+", " ", (source or "").strip()).lower()
    if not clean:
        return ""
    if clean in SOURCE_HOME_BY_LABEL:
        return SOURCE_HOME_BY_LABEL[clean]
    if "." in clean and " " not in clean:
        return "https://" + clean.removeprefix("www.")
    return ""


def _decode_ddg_href(href: str) -> str:
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and "uddg=" in parsed.query:
        return parse_qs(parsed.query).get("uddg", [href])[0]
    return href


def _link_matches_title(href: str, result_text: str, title: str) -> bool:
    search_title = _clean_title_for_search(title)
    title_terms = _keywords(title)
    overlap = _keywords(result_text) & title_terms
    result_terms = _keywords(result_text + " " + href)
    return (
        len(overlap) >= 2
        or len(result_terms & title_terms) >= 3
        or search_title.lower() in result_text.lower()
        or len(result_terms & title_terms) >= max(3, min(5, len(title_terms) - 1))
    )


def _discover_from_publisher_search(title: str, source_home: str) -> str:
    if not title or not source_home:
        return ""
    search_title = _clean_title_for_search(title)
    try:
        resp = requests.get(
            source_home.rstrip("/") + "/",
            params={"s": search_title},
            headers={"User-Agent": BROWSER_USER_AGENT},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Publisher site search failed (%s): %s", title, exc)
        return ""

    for match in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', resp.text, flags=re.IGNORECASE | re.DOTALL):
        href = html.unescape(match.group(1))
        result_text = _clean_feed_text(match.group(2))
        if href.startswith("/"):
            parsed_home = urlparse(source_home)
            href = f"{parsed_home.scheme}://{parsed_home.netloc}{href}"
        if not href.startswith("http") or not _same_site(href, source_home):
            continue
        parsed = urlparse(href)
        if parsed.path in ("", "/") or any(part in parsed.path for part in ("/tag/", "/category/", "/author/")):
            continue
        if _link_matches_title(href, result_text, title):
            return href
    return ""


def _discover_from_known_slug(title: str, source_home: str) -> str:
    slug = _slugify_title(title)
    if not slug or not source_home:
        return ""

    host = urlparse(source_home).netloc.lower().removeprefix("www.")
    candidates: list[str] = []
    if host == "pbs.org":
        candidates.append(source_home.rstrip("/") + f"/newshour/world/{slug}")

    for url in candidates:
        details = fetch_article_details(url, title)
        if details:
            return details.get("url") or url
    return ""


@lru_cache(maxsize=256)
def discover_article_url(title: str, source_home: str) -> str:
    """Find a publisher article URL when Google News only gives a wrapper link."""
    if not title or not source_home:
        return ""
    source_host = urlparse(source_home).netloc.lower().removeprefix("www.")
    if not source_host:
        return ""

    slug_url = _discover_from_known_slug(title, source_home)
    if slug_url:
        return slug_url

    search_title = _clean_title_for_search(title)
    query = f"site:{source_host} {search_title}"
    try:
        resp = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": BROWSER_USER_AGENT},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Article URL discovery failed (%s): %s", title, exc)
        return _discover_from_publisher_search(title, source_home)

    for match in re.finditer(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        resp.text,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        href = _decode_ddg_href(html.unescape(match.group(1)))
        result_text = _clean_feed_text(match.group(2))
        if not href.startswith("http") or not _same_site(href, source_home):
            continue
        parsed = urlparse(href)
        if parsed.path in ("", "/"):
            continue
        if _link_matches_title(href, result_text, title):
            return href
    return _discover_from_publisher_search(title, source_home)


@lru_cache(maxsize=256)
def discover_article_url_by_source(title: str, source_label: str) -> str:
    """Find a publisher article URL when only the display source label is known."""
    if not title or not source_label:
        return ""

    guessed_home = _source_home_from_label(source_label)
    if guessed_home:
        discovered = discover_article_url(title, guessed_home)
        if discovered:
            return discovered

    search_title = _clean_title_for_search(title)
    query = f"{search_title} {source_label}"
    try:
        resp = requests.get(
            "https://duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": BROWSER_USER_AGENT},
            timeout=TIMEOUT,
        )
        resp.raise_for_status()
    except Exception as exc:
        logger.warning("Article URL source-label discovery failed (%s): %s", title, exc)
        return ""

    for match in re.finditer(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        resp.text,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        href = _decode_ddg_href(html.unescape(match.group(1)))
        result_text = _clean_feed_text(match.group(2))
        if not href.startswith("http") or _is_redirect_url(href):
            continue
        if guessed_home and not _same_site(href, guessed_home):
            continue
        parsed = urlparse(href)
        if parsed.path in ("", "/"):
            continue
        if _link_matches_title(href, result_text, title):
            return href
    return ""


def _parse_feed(source_name: str, feed_url: str, cutoff: datetime) -> list[dict]:
    raw = _fetch_feed(feed_url)
    if not raw:
        return []

    parsed = feedparser.parse(raw)
    if not parsed.entries:
        if getattr(parsed, "bozo", False):
            logger.warning(
                "RSS parse issue for %s: %s",
                source_name,
                getattr(parsed, "bozo_exception", "no entries"),
            )
        return []

    stories: list[dict] = []
    for entry in parsed.entries:
        title = (entry.get("title") or "").strip()
        url = (entry.get("link") or "").strip()
        if not title or not url:
            continue

        pub = _parse_entry_date(entry)
        if pub and pub < cutoff:
            continue

        stories.append(
            {
                "title": title,
                "url": url,
                "source": _source_label(source_name, title),
                "source_home": _entry_source_home(entry),
                "summary": _entry_summary(entry),
                "date": pub.isoformat() if pub else None,
            }
        )
    return stories


def collect_rss(cutoff: datetime) -> list[dict]:
    """Pull stories from configured RSS feeds within the date window."""
    stories: list[dict] = []

    for source_name, feed_url in FEEDS:
        try:
            stories.extend(_parse_feed(source_name, feed_url, cutoff))
        except Exception as exc:
            logger.warning("RSS feed failed (%s): %s", source_name, exc)

    google_labels = ("Google News AI", "Google News LLM", "Google News OpenAI")
    for label, query in zip(google_labels, GOOGLE_NEWS_QUERIES):
        try:
            stories.extend(_parse_feed(label, _google_news_url(query), cutoff))
        except Exception as exc:
            logger.warning("Google News RSS failed (%s): %s", query, exc)

    return stories
