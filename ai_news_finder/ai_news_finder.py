#!/usr/bin/env python3
"""AI News Finder — curate top 10 viral AI stories for Instagram Reels."""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv

from collectors import collect_reddit, collect_rss
from collectors.rss import enrich_story_summaries
from discord_notifier import send_error_notification, send_report_file
from generators import generate_html_report, generate_reel_content, generate_text_report
from generators.report import export_json, format_date_human, _first_published, _story_summary
from processors import filter_ai_stories, group_stories, select_top_stories

_pkg_dir = Path(__file__).resolve().parent
load_dotenv(_pkg_dir / ".env")

if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            try:
                reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass

logging.basicConfig(level=logging.WARNING, format="%(message)s")
logger = logging.getLogger(__name__)


def _pad(msg: str, width: int = 36) -> str:
    return msg.ljust(width)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Curate top 10 viral AI news stories for Instagram Reels.",
    )
    parser.add_argument(
        "--days",
        type=int,
        required=True,
        help="How many past days of news to scan",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Number of top stories to select (default: 10)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Custom HTML output filename (default: report_YYYY-MM-DD.html)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="export_json",
        help="Also export a JSON file alongside the HTML",
    )
    args = parser.parse_args()

    if args.days < 1:
        print("Error: --days must be at least 1", file=sys.stderr)
        send_error_notification(
            title="❌ AI News Finder Configuration Error",
            message="Invalid --days parameter provided.",
            error_details="--days must be at least 1",
        )
        return 1

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    reports_dir = Path(__file__).resolve().parent.parent / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    output_file = args.output or f"report_{today}.html"
    output_path = Path(output_file)
    if not output_path.is_absolute():
        output_path = reports_dir / output_path.name
    text_path = output_path.with_suffix(".txt")

    print("Running AI News Finder...")

    # Layer 1: collection
    rss_stories = collect_rss(cutoff)
    rss_ai = filter_ai_stories(rss_stories)
    print(f"{_pad('📡 Collecting from RSS feeds...')} {len(rss_ai)} AI stories found")

    all_raw = rss_ai
    if not all_raw:
        print(
            "\nNo stories collected from any source. Check your network connection "
            "and try again.",
            file=sys.stderr,
        )
        send_error_notification(
            title="❌ AI News Finder Collection Failed",
            message="No stories were collected from any source.",
            error_details="Check your network connection and try again. Verify RSS feeds are accessible.",
        )
        return 1

    total_scanned = len(all_raw)

    # Layer 3: dedup
    print(_pad("🔄 Deduplicating & grouping..."), end="", flush=True)
    groups = group_stories(all_raw)
    print(f" {len(groups)} unique story groups")

    # Layer 4: selection (may need Reddit fill)
    primary_pool = [g for g in groups if g.get("source_count", 0) >= 3]
    print(_pad("✅ Primary pool (3+ sources):"), f" {len(primary_pool)} stories")

    reddit_stories: list[dict] = []
    if len(primary_pool) < 10:
        print(_pad("📱 Filling from Reddit..."), end="", flush=True)
        reddit_raw = collect_reddit()
        reddit_stories = filter_ai_stories(reddit_raw) if reddit_raw else []
        if not reddit_stories and reddit_raw:
            reddit_stories = reddit_raw
        print(f" {len(reddit_stories)} trending AI posts")

    if len(primary_pool) == 0:
        print(
            "💡 Tip: add more RSS sources in ai_news_finder/.env for better coverage.",
        )

    selected, stats = select_top_stories(groups, reddit_stories, limit=args.limit)
    print(_pad("📊 Final selection:"), f" {len(selected)} stories")

    if not selected:
        print("\nNo AI stories matched your criteria. Try increasing --days.", file=sys.stderr)
        send_error_notification(
            title="❌ AI News Finder Selection Failed",
            message="No AI stories matched the selection criteria.",
            error_details=f"Scanned {len(groups)} story groups but none matched filters. Try increasing --days.",
        )
        return 1

    # Layer 5: reel content
    enrich_story_summaries(selected)
    for story in selected:
        generate_reel_content(story)

    # Sources used
    sources_used: list[str] = []
    seen_src: set[str] = set()
    for story in all_raw:
        s = story.get("source", "")
        if s and s not in seen_src:
            seen_src.add(s)
            sources_used.append(s)

    verified_count = sum(
        1 for s in selected
        if s.get("source_count", 0) >= 3 and not s.get("social_fallback")
    )

    # Layer 6: reports (HTML + plain text, optional JSON)
    report_kwargs = dict(
        days=args.days,
        total_scanned=total_scanned,
        sources_used=sources_used,
        verified_count=verified_count,
    )
    generate_html_report(selected, output_path=str(output_path), **report_kwargs)
    generate_text_report(selected, output_path=str(text_path), **report_kwargs)

    if args.export_json:
        json_path = output_path.with_suffix(".json")
        export_json(selected, str(json_path), days=args.days)
        print(f"📄 JSON saved: {json_path.name}")

    # Terminal summary
    print(f"\n🏆 TOP {len(selected)} AI STORIES (last {args.days} days):")
    print("━" * 34)
    for story in selected:
        rank = story.get("rank", 0)
        sc = story.get("source_count", 1)
        title = story.get("title", "")
        sources = ", ".join(story.get("sources") or [])
        hook = story.get("hook", "")
        first_pub = format_date_human(_first_published(story))
        summary = _story_summary(story)
        if len(summary) > 120:
            summary = summary[:117] + "..."
        print(f"#{rank}  [{sc} sources] {title}")
        print(f"    First published: {first_pub}")
        print(f"    Sources: {sources}")
        print(f"    Summary: {summary}")
        print(f"    Hook: {hook}")
        print()

    print(f"📄 HTML report: reports/{output_path.name}")
    print(f"📄 Text report:  reports/{text_path.name}")

    # Send the HTML report file to Discord
    if output_path.exists():
        send_report_file(
            str(output_path.resolve()),
            f"📱 Interactive Report - {today}\n{len(selected)} top AI stories • {len(sources_used)} sources • Click to expand details"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
