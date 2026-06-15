"""
KAGGLE NOTEBOOK - FastAPI Server for AI SANGH

This notebook runs a FastAPI server that the Telegram bot can call directly.

SETUP:
1. Create new Kaggle notebook
2. Add GPU runtime (T4)
3. Add secrets: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
4. Run all cells
5. Copy the public URL from the output
6. Update bot.py with this URL
"""

# ============================================================
# CELL 1 - Install dependencies
# ============================================================
# !pip install transformers>=4.35.0 accelerate requests fastapi uvicorn -q

# ============================================================
# CELL 2 - Imports and config
# ============================================================
import json
import os
import threading
from datetime import datetime, timezone

import requests
import torch
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from transformers import AutoModelForCausalLM, AutoTokenizer

# Get secrets
try:
    from kaggle_secrets import UserSecretsClient
    secrets = UserSecretsClient()
    TELEGRAM_TOKEN = secrets.get_secret("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = secrets.get_secret("TELEGRAM_CHAT_ID")
except ImportError:
    TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"

print(f"Model: {MODEL_NAME}")
print(f"Telegram configured: {bool(TELEGRAM_TOKEN)}")

# ============================================================
# CELL 3 - Load Model
# ============================================================
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

# ============================================================
# CELL 4 - AI SANGH Prompt and Generation
# ============================================================
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
    prompts = {
        "generate": AI_SANGH_SYSTEM_PROMPT,
        "shorter": AI_SANGH_SYSTEM_PROMPT + "\n\nMake shorter and more concise.",
        "longer": AI_SANGH_SYSTEM_PROMPT + "\n\nExpand with more details.",
        "more viral": AI_SANGH_SYSTEM_PROMPT + "\n\nMake more engaging and viral-worthy.",
        "carousel": AI_SANGH_SYSTEM_PROMPT + "\n\nCreate carousel format with 5-7 slides.",
        "caption": AI_SANGH_SYSTEM_PROMPT + "\n\nCreate social media caption.",
        "30 second reel": AI_SANGH_SYSTEM_PROMPT + "\n\nCreate 30-second reel script.",
        "60 second reel": AI_SANGH_SYSTEM_PROMPT + "\n\nCreate 60-second reel script.",
        "proceed": AI_SANGH_SYSTEM_PROMPT + "\n\nGenerate Stage 2: CLIP 1 MASTER PROMPT, CLIP 2 MASTER PROMPT, and CAPTION.",
    }
    return prompts.get(request_type, AI_SANGH_SYSTEM_PROMPT)


# Conversation memory per article
conversations = {}


def generate_content(article_title, article_summary, request_type, article_id, conversation=None):
    system_prompt = get_system_prompt(request_type)
    user_prompt = "Article Title: " + article_title + "\n\nArticle Text: " + article_summary

    messages = [{"role": "system", "content": system_prompt}]

    if conversation:
        for msg in conversation[-10:]:
            role = "user" if msg["role"] in ("user_article", "user") else "assistant"
            messages.append({"role": role, "content": msg["content"][:1000]})

    messages.append({"role": "user", "content": user_prompt})

    text = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer([text], return_tensors="pt").to(model.device)

    outputs = model.generate(**inputs, max_new_tokens=2048, temperature=0.7, top_p=0.9, do_sample=True)
    response = tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)

    return response


# ============================================================
# CELL 5 - FastAPI Server
# ============================================================
app = FastAPI(title="AI SANGH API")


class GenerateRequest(BaseModel):
    article_title: str
    article_text: str
    request_type: str
    article_id: str


@app.get("/")
def root():
    return {"status": "online", "model": MODEL_NAME, "message": "AI SANGH API is running"}


@app.get("/health")
def health():
    return {"status": "healthy", "gpu": torch.cuda.is_available()}


@app.post("/generate")
def generate(request: GenerateRequest):
    try:
        # Get or create conversation
        if request.article_id not in conversations:
            conversations[request.article_id] = []

        conversation = conversations[request.article_id]

        # Generate content
        result = generate_content(
            article_title=request.article_title,
            article_summary=request.article_text,
            request_type=request.request_type,
            article_id=request.article_id,
            conversation=conversation,
        )

        # Save to conversation
        conversations[request.article_id].append({
            "role": "user",
            "content": request.article_text[:500] if request.request_type == "generate" else request.request_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        conversations[request.article_id].append({
            "role": "assistant",
            "content": result[:500],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

        # Keep last 20 messages
        if len(conversations[request.article_id]) > 20:
            conversations[request.article_id] = conversations[request.article_id][-20:]

        return {
            "status": "success",
            "result": result,
            "request_type": request.request_type,
            "article_title": request.article_title,
        }

    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(e)}
        )


@app.get("/conversations/{article_id}")
def get_conversation(article_id: str):
    return {"conversations": conversations.get(article_id, [])}


# ============================================================
# CELL 6 - Start Server with localtunnel
# ============================================================
import subprocess
import time

# Install localtunnel
subprocess.run(["npm", "install", "-g", "localtunnel"], capture_output=True)

# Start server in background thread
def run_server():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

server_thread = threading.Thread(target=run_server, daemon=True)
server_thread.start()

time.sleep(3)

# Create tunnel
print("Creating public tunnel...")
result = subprocess.run(
    ["lt", "--port", "8000"],
    capture_output=True,
    text=True,
    timeout=30
)

# Get the URL from output
public_url = None
for line in result.stdout.split("\n"):
    if "your url is:" in line.lower() or "url is" in line.lower():
        public_url = line.split(":")[-1].strip()
        break

if not public_url:
    # Try to find URL pattern
    import re
    urls = re.findall(r'https?://[^\s]+', result.stdout + result.stderr)
    if urls:
        public_url = urls[0]

if public_url:
    print(f"\n{'='*50}")
    print(f"API URL: {public_url}")
    print(f"{'='*50}")
    print(f"\nCopy this URL and update bot.py .env:")
    print(f'KAGGLE_API_URL="{public_url}"')
    print(f"\n{'='*50}")
else:
    print("Could not get URL. Check the output above.")
    print("Look for a URL in the output.")
