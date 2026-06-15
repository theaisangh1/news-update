"""Reddit JSON collector — social fallback when the primary pool has fewer than 10 stories."""

import logging
import time
from datetime import datetime, timezone

import requests

logger = logging.getLogger(__name__)

USER_AGENT = "AINewsFinder/1.0 (educational project)"
TIMEOUT = 10
MAX_POSTS = 20

SUBREDDITS = [
    "artificial",
    "MachineLearning",
    "singularity",
    "technology",
]


def _fetch_subreddit(sub: str) -> list[dict]:
    url = f"https://www.reddit.com/r/{sub}/search.json"
    params = {"q": "AI OR OpenAI OR ChatGPT OR LLM", "restrict_sr": "1", "sort": "new", "t": "week", "limit": 15}
    resp = requests.get(
        url,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    posts: list[dict] = []
    for child in resp.json().get("data", {}).get("children", []):
        data = child.get("data") or {}
        title = (data.get("title") or "").strip()
        if not title or data.get("is_self"):
            continue
        link = data.get("url") or ""
        if "reddit.com" in link:
            continue
        created = data.get("created_utc")
        date_iso = (
            datetime.fromtimestamp(created, tz=timezone.utc).isoformat()
            if created
            else None
        )
        posts.append(
            {
                "title": title,
                "url": link,
                "source": f"Reddit r/{sub}",
                "summary": title,
                "date": date_iso,
                "social_fallback": "reddit",
            }
        )
    return posts


def collect_reddit() -> list[dict]:
    """Fetch AI-related posts from tech subreddits."""
    stories: list[dict] = []
    seen_titles: set[str] = set()

    for sub in SUBREDDITS:
        if len(stories) >= MAX_POSTS:
            break
        try:
            time.sleep(0.3)
            for post in _fetch_subreddit(sub):
                if len(stories) >= MAX_POSTS:
                    break
                key = post["title"][:100].lower()
                if key in seen_titles:
                    continue
                seen_titles.add(key)
                stories.append(post)
        except Exception as exc:
            logger.warning("Reddit failed (r/%s): %s", sub, exc)

    return stories
