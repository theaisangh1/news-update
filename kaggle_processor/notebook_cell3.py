"""
CELL 3 - Run the processor:
"""

queue_mgr = QueueManager(QUEUE_FILE)
telegram = TelegramNotifier(TELEGRAM_TOKEN, str(TELEGRAM_CHAT_ID))

print("Starting Qwen processor...")
telegram.send("🟢 Qwen is online and ready.")

pending = queue_mgr.get_pending()
print(f"Found {len(pending)} pending request(s)")

for request in pending:
    req_id = request["id"]
    article_id = request["article_id"]
    article_title = request["article_title"]
    request_type = request["request_type"]

    print(f"\nProcessing: {request_type} for {article_title}")
    queue_mgr.update_status(req_id, "processing")

    try:
        result = generate_content(
            article_title=article_title,
            article_summary=request.get("user_message", ""),
            request_type=request_type,
            article_id=article_id,
        )

        queue_mgr.update_status(req_id, "completed", result)

        chat_id = request.get("chat_id")
        if chat_id:
            telegram.chat_id = str(chat_id)
            msg = "✅ *" + request_type.title() + "* for:\n📰 " + article_title + "\n\n" + result
            telegram.send(msg)

        print("  Done!")

    except Exception as e:
        print(f"  Error: {e}")
        queue_mgr.update_status(req_id, "failed", str(e))

print("\nAll requests processed!")
telegram.send("🔴 Qwen session ended.")
