"""
DEBUG CELL - Run this first to check everything
"""

import json
from pathlib import Path

# Check if queue file exists
queue_path = Path("/kaggle/input/ai-news-queue/request_queue.json")
print(f"Queue file exists: {queue_path.exists()}")

if queue_path.exists():
    with open(queue_path, "r") as f:
        data = json.load(f)
    print(f"Pending requests: {len(data.get('requests', []))}")
    print(f"Content: {json.dumps(data, indent=2)}")
else:
    print("File not found! Checking other paths...")
    # Check what's in the input directory
    input_dir = Path("/kaggle/input")
    if input_dir.exists():
        for item in input_dir.iterdir():
            print(f"  Found: {item}")

# Also check Telegram secrets
try:
    from kaggle_secrets import UserSecretsClient
    secrets = UserSecretsClient()
    token = secrets.get_secret("TELEGRAM_BOT_TOKEN")
    chat_id = secrets.get_secret("TELEGRAM_CHAT_ID")
    print(f"\nTelegram token: {token[:10]}...")
    print(f"Telegram chat_id: {chat_id}")
except Exception as e:
    print(f"\nError reading secrets: {e}")
