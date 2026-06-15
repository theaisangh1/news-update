import json
import os
import time
import base64
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
    GITHUB_TOKEN = secrets.get_secret("GITHUB_TOKEN")
except ImportError:
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
    GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")

# Configuration
MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"
GITHUB_REPO = "aisangh/news-update"
QUEUE_FILE = "request_queue.json"
POLL_INTERVAL = 30

print(f"Model: {MODEL_NAME}")
print(f"GitHub Repo: {GITHUB_REPO}")
print(f"Telegram configured: {bool(TELEGRAM_TOKEN)}")
print(f"GitHub configured: {bool(GITHUB_TOKEN)}")


class GitHubStorage:
    def __init__(self, token: str, repo: str, file_path: str):
        self.token = token
        self.repo = repo
        self.file_path = file_path
        self.api_url = f"https://api.github.com/repos/{repo}/contents/{file_path}"
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }

    def read_queue(self) -> dict:
        try:
            response = requests.get(self.api_url, headers=self.headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                content = base64.b64decode(data["content"]).decode("utf-8")
                return json.loads(content)
            else:
                print(f"GitHub read error: {response.status_code}")
                return {"requests": [], "completed": [], "conversations": {}}
        except Exception as e:
            print(f"GitHub read failed: {e}")
            return {"requests": [], "completed": [], "conversations": {}}

    def write_queue(self, data: dict) -> bool:
        try:
            response = requests.get(self.api_url, headers=self.headers, timeout=30)
            sha = None
            if response.status_code == 200:
                sha = response.json().get("sha")

            content = json.dumps(data, indent=2, ensure_ascii=False)
            encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")

            payload = {
                "message": f"Kaggle update {datetime.now(timezone.utc).isoformat()}",
                "content": encoded,
            }
            if sha:
                payload["sha"] = sha

            response = requests.put(
                self.api_url,
                headers=self.headers,
                json=payload,
                timeout=30,
            )

            return response.status_code in (200, 201)
        except Exception as e:
            print(f"GitHub write failed: {e}")
            return False

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

    def get_conversation(self, article_id: str) -> list[dict]:
        queue = self.read_queue()
        return queue.get("conversations", {}).get(article_id, [])

    def add_to_conversation(self, article_id: str, role: str, content: str) -> None:
        queue = self.read_queue()
        if "conversations" not in queue:
            queue["conversations"] = {}
        if article_id not in queue["conversations"]:
            queue["conversations"][article_id] = []

        queue["conversations"][article_id].append({
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        if len(queue["conversations"][article_id]) > 20:
            queue["conversations"][article_id] = queue["conversations"][article_id][-20:]

        self.write_queue(queue)


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
            }
            try:
                response = requests.post(url, json=payload, timeout=30)
                response.raise_for_status()
            except Exception as e:
                print(f"Failed to send: {e}")
                return False
        return True


# AI SANGH Master Prompt
AI_SANGH_SYSTEM_PROMPT = """You are the Chief Creative Director of AI SANGH — a sharp, cynical, truth-telling AI education brand.

Your job is to take raw AI news and turn it into scroll-stopping 16-second vertical video concepts for Instagram Reels and YouTube Shorts.

BRAND VOICE:
- Tone: Cynical, dark-humored, authoritative, occasionally poetic
- Perspective: Skeptical of hype. Allergic to comfortable truths.

HARD RULES:
1. MAX 4 WORDS on screen at any single moment.
2. Story is told 100% through visuals. Text on screen is punctuation.
3. No voiceover. No dialogue. No narration.
4. Format: Vertical 9:16. Exactly 16 seconds total. Two clips of 8 seconds each.
5. Visual Aesthetic: Pixar-quality 3D animation meets Neo-Noir Cyberpunk. Dark cinematic lighting. Rain-soaked. Neon accents.

DELIVERY FRAMEWORKS (choose ONE):
- CURIOSITY REVEAL: Open with something strange. Close with reframing truth.
- FALSE PROMISE → REALITY SLAP: Show official story first. Then what's underneath.
- BEFORE → AFTER: Show world as it was. Then what changed.
- TICKING CLOCK: This is happening. Viewer is behind.
- CONSPIRACY CONFIRMED: Something dismissed is now real.
- PATTERN INTERRUPT: Start unexpected. Flip assumption by Clip 2.
- SCALE SHOCK: Make viewer feel the size/speed through visual contrast.

OUTPUT FORMAT:

### DELIVERY FRAMEWORK
[Name]
[Why this fits this story]
[Emotional effect]

### VIRAL TRUTH HOOKS (2-3 options)
Standalone text. Under 10 words. Triggers rage/fear/dark humor/"oh shit" recognition.

### CLIP 1 JIST — [Sharp title]
10 bullet points. Story only. No production details.

### CLIP 2 JIST — [Sharp title]
10 bullet points. Payoff/flip of Clip 1.

Reply "proceed" to generate full master prompts and caption."""


def get_system_prompt(request_type):
    if request_type == "generate":
        return AI_SANGH_SYSTEM_PROMPT
    elif request_type == "shorter":
        return AI_SANGH_SYSTEM_PROMPT + "\n\nMake the previous output shorter and more concise."
    elif request_type == "longer":
        return AI_SANGH_SYSTEM_PROMPT + "\n\nExpand the previous output with more details."
    elif request_type == "more viral":
        return AI_SANGH_SYSTEM_PROMPT + "\n\nRewrite to be more engaging and viral-worthy."
    elif request_type == "carousel":
        return AI_SANGH_SYSTEM_PROMPT + "\n\nCreate a carousel post format with 5-7 slides."
    elif request_type == "caption":
        return AI_SANGH_SYSTEM_PROMPT + "\n\nCreate an engaging social media caption."
    elif request_type == "30 second reel":
        return AI_SANGH_SYSTEM_PROMPT + "\n\nCreate a script for a 30-second Instagram reel."
    elif request_type == "60 second reel":
        return AI_SANGH_SYSTEM_PROMPT + "\n\nCreate a script for a 60-second Instagram reel."
    elif request_type == "proceed":
        return AI_SANGH_SYSTEM_PROMPT + "\n\nGenerate Stage 2: CLIP 1 MASTER PROMPT, CLIP 2 MASTER PROMPT, and CAPTION."
    else:
        return AI_SANGH_SYSTEM_PROMPT


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


def generate_content(article_title, article_summary, request_type, article_id, conversation=None):
    system_prompt = get_system_prompt(request_type)

    user_prompt = "Article Title: " + article_title + "\n\nArticle Text: " + article_summary

    if request_type != "generate":
        user_prompt += "\n\nNote: This is a follow-up request. Please revise the previous output accordingly."

    messages = [{"role": "system", "content": system_prompt}]

    # Add conversation history for context
    if conversation:
        for msg in conversation[-10:]:
            if msg["role"] in ("user_article", "user"):
                messages.append({"role": "user", "content": msg["content"][:1000]})
            elif msg["role"] == "assistant":
                messages.append({"role": "assistant", "content": msg["content"][:1000]})

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

    return response


# Initialize
github = GitHubStorage(GITHUB_TOKEN, GITHUB_REPO, QUEUE_FILE)
telegram = TelegramNotifier(TELEGRAM_TOKEN, str(TELEGRAM_CHAT_ID))

print("Starting Qwen processor...")
telegram.send("🟢 Qwen is online and ready.")

while True:
    try:
        pending = github.get_pending()
        if pending:
            print(f"Processing {len(pending)} request(s)...")
            for request in pending:
                req_id = request["id"]
                article_id = request["article_id"]
                article_title = request["article_title"]
                request_type = request["request_type"]
                user_message = request.get("user_message", "")

                print(f"  - {request_type} for: {article_title[:50]}")
                github.update_status(req_id, "processing")

                try:
                    # Get conversation history
                    conversation = github.get_conversation(article_id)

                    result = generate_content(
                        article_title=article_title,
                        article_summary=user_message,
                        request_type=request_type,
                        article_id=article_id,
                        conversation=conversation,
                    )

                    # Save to conversation memory
                    github.add_to_conversation(article_id, "user", user_message)
                    github.add_to_conversation(article_id, "assistant", result)

                    github.update_status(req_id, "completed", result)

                    # Send to Telegram
                    chat_id = request.get("chat_id")
                    if chat_id:
                        telegram.chat_id = str(chat_id)
                        msg = "✅ *" + request_type.title() + "* for:\n📰 " + article_title + "\n\n" + result
                        telegram.send(msg)

                    print("    Done!")

                except Exception as e:
                    print(f"    Error: {e}")
                    github.update_status(req_id, "failed", str(e))
        else:
            print(f"No pending requests. Waiting {POLL_INTERVAL}s...")

        time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        print("Shutting down...")
        telegram.send("🔴 Qwen session ended.")
        break
    except Exception as e:
        print(f"Error in loop: {e}")
        time.sleep(10)
