#!/usr/bin/env python3
"""Telegram bot for AI News - AI SANGH Style with continuous conversation."""

import logging
import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

_env_path = Path(__file__).resolve().parent / ".env"
load_dotenv(_env_path)

from news_manager import news_manager
from github_storage import github_storage

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Content generation commands
GENERATION_COMMANDS = [
    "generate",
    "shorter",
    "longer",
    "more viral",
    "carousel",
    "caption",
    "30 second reel",
    "60 second reel",
    "proceed",
]


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    welcome_message = (
        "👋 Welcome to AI SANGH Bot!\n\n"
        "I help you create scroll-stopping AI content.\n\n"
        "📰 /news - See latest topics\n"
        "🔍 /status - Check Qwen availability\n"
        "❓ /help - All commands\n\n"
        "Workflow:\n"
        "1. /news → Select topic\n"
        "2. Paste article text\n"
        "3. Get AI SANGH Stage 1\n"
        "4. Say 'proceed' for Stage 2\n"
        "5. Keep refining until you love it"
    )
    await update.message.reply_text(welcome_message)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    help_text = (
        "📖 *Commands*\n\n"
        "📰 /news - Show topics\n"
        "🔍 /status - Check Qwen\n"
        "❓ /help - This message\n\n"
        "*After selecting a topic:*\n"
        "• Paste article text → Get Stage 1\n"
        "• proceed → Get Stage 2 (full prompts)\n"
        "• shorter → Make shorter\n"
        "• longer → Expand\n"
        "• more viral → More engaging\n"
        "• carousel → Carousel format\n"
        "• caption → Social caption\n"
        "• 30 second reel → Short reel\n"
        "• 60 second reel → Medium reel\n\n"
        "*Context is remembered per article!*"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command."""
    kaggle_status = os.getenv("KAGGLE_STATUS", "offline")

    if kaggle_status.lower() == "online":
        status_msg = "🟢 *Qwen is online and ready.*"
    else:
        status_msg = "🔴 *Qwen session ended.*"

    pending = github_storage.get_pending_requests()
    if pending:
        status_msg += f"\n\n📋 *{len(pending)} pending request(s)*"

    await update.message.reply_text(status_msg, parse_mode="Markdown")


async def news_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /news command."""
    news = news_manager.get_latest_news(limit=5)

    if not news:
        await update.message.reply_text("📭 No news available. Run the collector first!")
        return

    keyboard = []
    for i, story in enumerate(news[:5], 1):
        title = story.get("title", "No title")
        if len(title) > 45:
            title = title[:42] + "..."
        keyboard.append([InlineKeyboardButton(f"{i}. {title}", callback_data=f"news_{i}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    lines = ["📰 *AI SANGH — Today's Targets*\n"]

    for i, story in enumerate(news[:5], 1):
        title = story.get("title", "No title")
        sources = story.get("sources", [])
        source_homes = story.get("source_homes", [])
        source_count = story.get("source_count", len(sources))

        lines.append(f"*{i}. {title}*")
        lines.append(f"   📡 {source_count} source{'s' if source_count != 1 else ''}")

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

    lines.append("👇 Select a topic (1-5) then paste article text")

    await update.message.reply_text(
        "\n".join(lines),
        reply_markup=reply_markup,
        parse_mode="Markdown",
    )


async def news_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle news topic selection."""
    query = update.callback_query
    await query.answer()

    callback_data = query.data
    if not callback_data.startswith("news_"):
        return

    try:
        index = int(callback_data.split("_")[1])
    except (ValueError, IndexError):
        await query.edit_message_text("❌ Invalid selection.")
        return

    article = news_manager.get_article_by_index(index)
    if not article:
        await query.edit_message_text("❌ Article not found.")
        return

    # Store article in user context
    context.user_data["active_article"] = article
    context.user_data["article_id"] = str(article.get("url", f"article_{index}"))
    context.user_data["awaiting_article_text"] = True

    title = article.get("title", "Unknown")
    sources = article.get("sources", [])
    source_homes = article.get("source_homes", [])

    msg = f"📰 *Selected:* {title}\n\n"

    shown = 0
    seen_homes = set()
    for j, home in enumerate(source_homes):
        if shown >= 3:
            break
        if home and home not in seen_homes:
            seen_homes.add(home)
            source_name = sources[j] if j < len(sources) else "Source"
            msg += f"🔗 [{source_name}]({home})\n"
            shown += 1

    if shown == 0:
        url = article.get("url", "")
        if url:
            msg += f"🔗 [Read Article]({url})\n"

    msg += (
        f"\n📝 *Next step:*\n"
        f"Copy-paste the full article text here.\n"
        f"I'll generate AI SANGH Stage 1 content."
    )

    await query.edit_message_text(msg, parse_mode="Markdown")


async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle text messages."""
    text = update.message.text.strip()
    text_lower = text.lower()

    # Check if user is providing article text
    if context.user_data.get("awaiting_article_text"):
        article = context.user_data.get("active_article", {})
        article_id = context.user_data.get("article_id", "unknown")
        article_title = article.get("title", "Unknown")

        # Add to conversation memory
        github_storage.add_to_conversation(article_id, "user_article", text)

        # Create generation request
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id

        request = github_storage.add_request(
            article_id=article_id,
            article_title=article_title,
            request_type="generate",
            user_message=text,
            user_id=user_id,
            chat_id=chat_id,
        )

        context.user_data["awaiting_article_text"] = False
        context.user_data["awaiting_stage1"] = True

        response_msg = (
            f"✅ *Article received!*\n\n"
            f"📰 {article_title}\n\n"
            f"⏳ Generating AI SANGH Stage 1...\n"
            f"Check back in a moment."
        )

        await update.message.reply_text(response_msg, parse_mode="Markdown")
        return

    # Check for generation commands
    if text_lower in [cmd.lower() for cmd in GENERATION_COMMANDS]:
        original_cmd = text_lower if text_lower == "proceed" else next(
            (cmd for cmd in GENERATION_COMMANDS if cmd.lower() == text_lower), text_lower
        )
        await _process_generation_command(original_cmd, None, context, update)
        return

    # Number selection
    if text.isdigit():
        index = int(text)
        if 1 <= index <= 5:
            article = news_manager.get_article_by_index(index)
            if article:
                context.user_data["active_article"] = article
                context.user_data["article_id"] = str(article.get("url", f"article_{index}"))
                context.user_data["awaiting_article_text"] = True

                title = article.get("title", "Unknown")
                sources = article.get("sources", [])
                source_homes = article.get("source_homes", [])

                msg = f"📰 *Selected:* {title}\n\n"

                shown = 0
                seen_homes = set()
                for j, home in enumerate(source_homes):
                    if shown >= 3:
                        break
                    if home and home not in seen_homes:
                        seen_homes.add(home)
                        source_name = sources[j] if j < len(sources) else "Source"
                        msg += f"🔗 [{source_name}]({home})\n"
                        shown += 1

                msg += (
                    f"\n📝 *Next step:*\n"
                    f"Copy-paste the full article text here."
                )
                await update.message.reply_text(msg, parse_mode="Markdown")
                return

    # If user sends text without selecting topic first, treat as feedback
    article = context.user_data.get("active_article")
    if article:
        await _process_generation_command(text, None, context, update)
        return

    await update.message.reply_text(
        "🤔 I don't understand.\n\n"
        "Use /news to see topics or /help for commands."
    )


async def _process_generation_command(
    command: str,
    query,
    context: ContextTypes.DEFAULT_TYPE,
    update: Update = None,
) -> None:
    """Process a generation command."""
    article = context.user_data.get("active_article")
    if not article:
        msg = "❌ No article selected. Use /news first."
        if query:
            await query.edit_message_text(msg)
        elif update:
            await update.message.reply_text(msg)
        return

    article_id = context.user_data.get("article_id", "unknown")
    article_title = article.get("title", "Unknown")

    user_id = update.effective_user.id if update else (query.from_user.id if query else None)
    chat_id = update.effective_chat.id if update else (query.message.chat_id if query else None)

    # Get conversation history for context
    conversation = github_storage.get_conversation(article_id)
    context_text = "\n".join([f"{msg['role']}: {msg['content'][:200]}" for msg in conversation[-5:]]) if conversation else ""

    request = github_storage.add_request(
        article_id=article_id,
        article_title=article_title,
        request_type=command,
        user_message=command + (f"\n\nPrevious context:\n{context_text}" if context_text else ""),
        user_id=user_id,
        chat_id=chat_id,
    )

    pending = github_storage.get_pending_requests()
    position = next(
        (i + 1 for i, r in enumerate(pending) if r["id"] == request["id"]),
        len(pending),
    )

    response_msg = (
        f"✅ *Queued!*\n\n"
        f"📰 {article_title}\n"
        f"🎯 {command}\n"
        f"📍 Position: {position}\n\n"
        f"⏳ Processing when Qwen is available."
    )

    if query:
        await query.edit_message_text(response_msg, parse_mode="Markdown")
    elif update:
        await update.message.reply_text(response_msg, parse_mode="Markdown")


def create_bot() -> Application:
    """Create and configure the Telegram bot application."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")

    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(CommandHandler("news", news_command))

    application.add_handler(CallbackQueryHandler(news_callback, pattern=r"^news_\d+$"))

    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, message_handler)
    )

    return application


def main() -> None:
    """Start the Telegram bot."""
    application = create_bot()
    logger.info("Starting Telegram bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
