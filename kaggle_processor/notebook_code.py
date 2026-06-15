"""
KAGGLE NOTEBOOK SETUP INSTRUCTIONS
===================================

CELL 1 - Install dependencies:
!pip install transformers>=4.35.0 accelerate requests -q

CELL 2 - Copy all code below this line:
"""

# ============================================================
# CELL 2 START - Copy everything below this line
# ============================================================

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

# Get secrets from Kaggle environment
try:
    from kaggle_secrets import UserSecretsClient
    secrets = UserSecretsClient()
    TELEGRAM_TOKEN = secrets.get_secret("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = secrets.get_secret("TELEGRAM_CHAT_ID")
except ImportError:
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Configuration
MODEL_NAME = "Qwen/Qwen2.5-14B-Instruct"
QUEUE_FILE = "/kaggle/input/ai-news-queue/request_queue.json"
POLL_INTERVAL = 30

print(f"Model: {MODEL_NAME}")
print(f"Queue: {QUEUE_FILE}")
print(f"Telegram configured: {bool(TELEGRAM_TOKEN)}")


class QueueManager:
    def __init__(self, queue_file: str):
        self.queue_file = Path(queue_file)

    def read_queue(self) -> dict:
        try:
            with open(self.queue_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"requests": [], "completed": []}

    def write_queue(self, data: dict) -> None:
        with open(self.queue_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def get_pending(self) -> list[dict]:
        queue = self.read_queue()
        return [r for r in queue.get("requests", []) if r["status"] == "pending"]

    def update_status(self, request_id: str, status: str, result: str = None) -> Optional[dict]:
        queue = self.read_queue()
        for i, request in enumerate(queue.get("requests", [])):
            if request["id"] == request_id:
                request["status"] = status
                request["completed_at"] = datetime.now(timezone.utc).isoformat()
                if result:
                    request["result"] = result
                if status in ("completed", "failed"):
                    queue["completed"].append(queue["requests"].pop(i))
                self.write_queue(queue)
                return request
        return None


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = chat_id

    def send(self, message: str) -> bool:
        if not self.token or not self.chat_id:
            print("Telegram not configured")
            return False

        url = f"https://api.telegram.org/bot{self.token}/sendMessage"

        chunks = []
        if len(message) <= 4000:
            chunks = [message]
        else:
            lines = message.split("\n")
            current = ""
            for line in lines:
                if len(current) + len(line) + 1 <= 4000:
                    current += line + "\n"
                else:
                    if current:
                        chunks.append(current.strip())
                    current = line + "\n"
            if current:
                chunks.append(current.strip())

        for chunk in chunks:
            payload = {
                "chat_id": self.chat_id,
                "text": chunk,
                "parse_mode": "Markdown",
            }
            try:
                response = requests.post(url, json=payload, timeout=30)
                response.raise_for_status()
            except Exception as e:
                print(f"Failed to send: {e}")
                return False
        return True


context_memory: dict[str, list[dict]] = {}

def get_context(article_id: str) -> list[dict]:
    return context_memory.get(article_id, [])

def add_to_context(article_id: str, role: str, content: str) -> None:
    if article_id not in context_memory:
        context_memory[article_id] = []
    context_memory[article_id].append({"role": role, "content": content})
    if len(context_memory[article_id]) > 10:
        context_memory[article_id] = context_memory[article_id][-10:]


print("Loading tokenizer...")
tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)

print("Loading model...")
model = AutoModelForCausalLM.from_pretrained(
    MODEL_NAME,
    torch_dtype=torch.float16,
    device_map="auto",
    trust_remote_code=True,
)
print("Model loaded!")


def get_system_prompt(request_type: str) -> str:
    base = """You are an expert content creator specializing in AI/tech content for social media.
You create engaging, viral content that educates and entertains.
Always include relevant hashtags and maintain a professional yet approachable tone."""

    prompts = {
        "generate": f"{base}\nCreate a comprehensive script for the given news story.",
        "shorter": f"{base}\nMake the previous script shorter and more concise while keeping key points.",
        "longer": f"{base}\nExpand the previous script with more details and examples.",
        "more viral": f"{base}\nRewrite the previous script to be more engaging and viral-worthy.",
        "carousel": f"{base}\nCreate a carousel post format with 5-7 slides.",
        "caption": f"{base}\nCreate an engaging social media caption.",
        "30 second reel": f"{base}\nCreate a script for a 30-second Instagram reel.",
        "60 second reel": f"{base}\nCreate a script for a 60-second Instagram reel.",
    }
    return prompts.get(request_type, base)


def generate_content(
    article_title: str,
    article_summary: str,
    request_type: str,
    article_id: str,
) -> str:
    system_prompt = get_system_prompt(request_type)
    context = get_context(article_id)

    user_prompt = f"""Article Title: {article_title}

Article Summary: {article_summary}

Request: {request_type}"""

    if request_type != "generate":
        user_prompt += "\n\nNote: This is a follow-up request. Please revise the previous output."

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(context)
    messages.append({"role": "user", "content": user_prompt})

    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )

    inputs = tokenizer([text], return_tensors="pt").to(model.device)

    outputs = model.generate(
        **inputs,
        max_new_tokens=2048,
        temperature=0.7,
        top_p=0.9,
        do_sample=True,
    )

    response = tokenizer.decode(
        outputs[0][inputs.input_ids.shape[1]:],
        skip_special_tokens=True,
    )

    add_to_context(article_id, "user", user_prompt)
    add_to_context(article_id, "assistant", response)

    return response


# ============================================================
# CELL 3 - Run the processor:
# ============================================================

queue_mgr = QueueManager(QUEUE_FILE)
telegram = TelegramNotifier(TELEGRAM_TOKEN, TELEGRAM_CHAT_ID)

print("Starting Qwen processor...")
telegram.send("🟢 Qwen is online and ready.")

# Process requests (run this cell to start)
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
            msg = f"✅ *{request_type.title()}* for:\n📰 {article_title}\n\n{result}"
            telegram.send(msg)

        print(f"  Done!")

    except Exception as e:
        print(f"  Error: {e}")
        queue_mgr.update_status(req_id, "failed", str(e))

print("\nAll requests processed!")
telegram.send("🔴 Qwen session ended.")
