#!/usr/bin/env python3
"""Manage news data from the existing pipeline."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class NewsManager:
    """Manages news data from the existing AI news pipeline."""

    def __init__(self, news_dir: str = "reports"):
        self.news_dir = Path(news_dir)
        self._cache = None
        self._cache_date = None

    def get_latest_news(self, limit: int = 5) -> list[dict]:
        """Get the latest top news stories from the most recent report."""
        latest_json = self._find_latest_json()
        if not latest_json:
            return []

        try:
            with open(latest_json, "r", encoding="utf-8") as f:
                data = json.load(f)

            stories = data.get("stories", [])[:limit]
            return stories
        except (json.JSONDecodeError, KeyError):
            return []

    def _find_latest_json(self) -> Optional[Path]:
        """Find the most recent JSON report file."""
        if not self.news_dir.exists():
            return None

        json_files = list(self.news_dir.glob("report_*.json"))
        if not json_files:
            return None

        # Sort by modification time (newest first)
        json_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return json_files[0]

    def get_article_by_index(self, index: int) -> Optional[dict]:
        """Get a specific article by its 1-based index."""
        news = self.get_latest_news(limit=10)
        if 1 <= index <= len(news):
            return news[index - 1]
        return None

    def format_news_for_telegram(self, news: list[dict]) -> str:
        """Format news list for Telegram display."""
        if not news:
            return "📭 No news available. Run the news collector first."

        lines = ["📰 *AI SANGH — Today's Targets*\n"]

        for i, story in enumerate(news, 1):
            title = story.get("title", "No title")
            sources = story.get("sources", [])
            source_homes = story.get("source_homes", [])
            source_count = story.get("source_count", len(sources))

            lines.append(f"*{i}. {title}*")
            lines.append(f"   📡 {source_count} source{'s' if source_count != 1 else ''}")

            # Show up to 3 source links
            shown = 0
            seen_homes = set()
            for j, home in enumerate(source_homes):
                if shown >= 3:
                    break
                if home and home not in seen_homes:
                    seen_homes.add(home)
                    source_name = sources[j] if j < len(sources) else "Source"
                    lines.append(f"   🔗 [{source_name}]({home})")
                    shown += 1

            lines.append("")

        lines.append("👇 Select a topic (1-5) then paste the article text")
        return "\n".join(lines)

    def format_article_details(self, article: dict) -> str:
        """Format a single article for detailed display."""
        title = article.get("title", "No title")
        summary = article.get("summary") or article.get("detailed_summary", "")
        sources = article.get("sources", [])
        url = article.get("url", "")
        hook = article.get("hook", "")

        lines = [f"📰 *{title}*\n"]

        if summary:
            # Truncate summary for Telegram
            if len(summary) > 500:
                summary = summary[:497] + "..."
            lines.append(f"📝 {summary}\n")

        if sources:
            lines.append(f"📡 Sources: {', '.join(sources[:5])}")

        if url:
            lines.append(f"🔗 [Read more]({url})")

        if hook:
            lines.append(f"\n💡 *Hook:* {hook}")

        return "\n".join(lines)


# Global news instance - look for reports in parent directory
_reports_dir = Path(__file__).resolve().parent.parent / "reports"
news_manager = NewsManager(str(_reports_dir))
