#!/usr/bin/env python3
"""Telegram bot for AI News - AI SANGH Style with direct API."""

import logging
import os
import requests
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

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Kaggle API URL - update this after starting the notebook
KAGGLE_API_URL = os.getenv("KAGGLE_API_URL", "")

# Conversation memory
conversations = {}


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /start command."""
    await update.message.reply_text(
        "👋 Welcome to AI SANGH Bot!\n\n"
        "📰 /news - See latest topics\n"
        "🔍 /status - Check Qwen\n"
        "❓ /help - All commands"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help command."""
    await update.message.reply_text(
        "📖 *Commands*\n\n"
        "📰 /news - Show topics\n"
        "🔍 /status - Check Qwen\n"
        "❓ /help - This message\n\n"
        "*After selecting a topic:*\n"
        "• Paste article text → Get Stage 1\n"
        "• proceed → Get Stage 2\n"
        "• shorter / longer / more viral → Refine\n"
        "• carousel / caption → Different formats\n"
        "• 30 second reel / 60 second reel → Reels\n\n"
        "*Context is remembered!*",
        parse_mode="Markdown",
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /status command."""
    if not KAGGLE_API_URL:
        await update.message.reply_text("🔴 Qwen is offline. Start the Kaggle notebook first.")
        return

    try:
        response = requests.get(f"{KAGGLE_API_URL}/health", timeout=5)
        if response.status_code == 200:
            await update.message.reply_text("🟢 *Qwen is online and ready!*", parse_mode="Markdown")
        else:
            await update.message.reply_text("🔴 Qwen is having issues.")
    except:
        await update.message.reply_text("🔴 Qwen is offline. Start the Kaggle notebook.")


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

        context.user_data["awaiting_article_text"] = False

        # Call Kaggle API directly
        await call_kaggle_api(
            update, context, article_id, article_title, "generate", text
        )
        return

    # Generation commands
    generation_commands = [
        "generate", "shorter", "longer", "more viral", "carousel",
        "caption", "30 second reel", "60 second reel", "proceed"
    ]

    if text_lower in [cmd.lower() for cmd in generation_commands]:
        article = context.user_data.get("active_article")
        if not article:
            await update.message.reply_text("❌ No article selected. Use /news first.")
            return

        original_cmd = text_lower if text_lower == "proceed" else next(
            (cmd for cmd in generation_commands if cmd.lower() == text_lower), text_lower
        )

        article_id = context.user_data.get("article_id", "unknown")
        article_title = article.get("title", "Unknown")

        await call_kaggle_api(
            update, context, article_id, article_title, original_cmd, original_cmd
        )
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

                msg += f"\n📝 *Next step:*\nCopy-paste the full article text here."
                await update.message.reply_text(msg, parse_mode="Markdown")
                return

    # If we have an active article, treat text as feedback
    article = context.user_data.get("active_article")
    if article:
        article_id = context.user_data.get("article_id", "unknown")
        article_title = article.get("title", "Unknown")
        await call_kaggle_api(
            update, context, article_id, article_title, text_lower, text
        )
        return

    await update.message.reply_text(
        "🤔 I don't understand.\n\nUse /news to see topics or /help for commands."
    )


async def call_kaggle_api(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    article_id: str,
    article_title: str,
    request_type: str,
    article_text: str,
) -> None:
    """Call Kaggle API and send result to Telegram."""
    if not KAGGLE_API_URL:
        await update.message.reply_text(
            "🔴 Qwen is offline.\n\nStart the Kaggle notebook first."
        )
        return

    # Show typing indicator
    await update.message.chat.send_action("typing")

    try:
        payload = {
            "article_title": article_title,
            "article_text": article_text,
            "request_type": request_type,
            "article_id": article_id,
        }

        response = requests.post(
            f"{KAGGLE_API_URL}/generate",
            json=payload,
            timeout=120,
        )

        if response.status_code == 200:
            data = response.json()
            result = data.get("result", "No result generated.")

            # Save to local memory
            if article_id not in conversations:
                conversations[article_id] = []
            conversations[article_id].append({"role": "user", "content": article_text[:200]})
            conversations[article_id].append({"role": "assistant", "content": result[:200]})

            # Send result
            msg = f"✅ *{request_type.title()}* for:\n📰 {article_title}\n\n{result}"

            # Split if too long
            if len(msg) > 4000:
                chunks = [msg[i:i+4000] for i in range(0, len(msg), 4000)]
                for chunk in chunks:
                    await update.message.reply_text(chunk, parse_mode=None)
            else:
                await update.message.reply_text(msg, parse_mode=None)
        else:
            await update.message.reply_text("❌ Error generating content. Try again.")

    except requests.exceptions.Timeout:
        await update.message.reply_text("⏳ Still generating... This may take a minute.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)[:100]}")


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
    if not KAGGLE_API_URL:
        print("WARNING: KAGGLE_API_URL not set!")
        print("Start the Kaggle notebook and update .env with the API URL.")

    application = create_bot()
    logger.info("Starting Telegram bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
