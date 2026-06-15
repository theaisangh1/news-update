#!/usr/bin/env python3
"""Local test script for Telegram bot components."""

import sys
from pathlib import Path

# Add telegram_bot to path
sys.path.insert(0, str(Path(__file__).parent / "telegram_bot"))

from news_manager import news_manager
from queue_manager import queue_manager


def test_news_manager():
    """Test news manager functionality."""
    print("=" * 50)
    print("Testing News Manager")
    print("=" * 50)

    # Get latest news
    news = news_manager.get_latest_news(limit=5)
    print(f"Found {len(news)} articles")

    if news:
        # Display formatted news
        formatted = news_manager.format_news_for_telegram(news)
        print("\nFormatted for Telegram:")
        print(formatted)

        # Test article details
        article = news_manager.get_article_by_index(1)
        if article:
            details = news_manager.format_article_details(article)
            print("\nArticle details:")
            print(details)
    else:
        print("No news found. Run the news collector first.")


def test_queue_manager():
    """Test queue manager functionality."""
    print("\n" + "=" * 50)
    print("Testing Queue Manager")
    print("=" * 50)

    # Add a test request
    request = queue_manager.add_request(
        article_id="test_article_123",
        article_title="Test Article Title",
        request_type="generate",
        user_message="generate",
        user_id=123456789,
        chat_id=123456789,
    )
    print(f"Created request: {request['id']}")

    # Get pending requests
    pending = queue_manager.get_pending_requests()
    print(f"Pending requests: {len(pending)}")

    # Mark as completed
    completed = queue_manager.mark_completed(
        request["id"],
        "This is a test script output from the Qwen processor."
    )
    print(f"Request status: {completed['status']}")

    # Get recent completed
    recent = queue_manager.get_recent_completed(limit=5)
    print(f"Recent completed: {len(recent)}")


def main():
    """Run all tests."""
    print("Telegram Bot Component Tests")
    print("=" * 50)

    try:
        test_news_manager()
        test_queue_manager()
        print("\n" + "=" * 50)
        print("All tests passed!")
        print("=" * 50)
    except Exception as e:
        print(f"\nError during testing: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
