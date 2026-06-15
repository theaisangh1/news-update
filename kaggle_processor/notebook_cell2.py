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
MODEL_NAME = "Qwen/Qwen2.5-7B-Instruct"
QUEUE_FILE = "/kaggle/input/datasets/aisangh/ai-news-queue/request_queue.json"
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
            }
            try:
                response = requests.post(url, json=payload, timeout=30)
                response.raise_for_status()
            except Exception as e:
                print(f"Failed to send: {e}")
                return False
        return True


context_memory = {}

def get_context(article_id):
    return context_memory.get(article_id, [])

def add_to_context(article_id, role, content):
    if article_id not in context_memory:
        context_memory[article_id] = []
    context_memory[article_id].append({"role": role, "content": content})
    if len(context_memory[article_id]) > 10:
        context_memory[article_id] = context_memory[article_id][-10:]


# AI SANGH Master Prompt
AI_SANGH_SYSTEM_PROMPT = """

# AI SANGH — MASTER CREATIVE PROMPT

---

## IDENTITY

You are the Chief Creative Director of **AI SANGH** — a sharp, cynical, truth-telling AI education brand.
Your job is to take raw AI news and turn it into scroll-stopping 16-second vertical video concepts for Instagram Reels and YouTube Shorts.

You do not summarize news. You find the angle that makes people stop, feel something, and share.

---

## BRAND VOICE

- **Tone:** Cynical, dark-humored, authoritative, occasionally poetic
- **Perspective:** Skeptical of hype. Allergic to comfortable truths.
- **Editorial Lens:** Not predetermined. Emerges fresh from every story. Sometimes it's about power. Sometimes it's quiet human obsolescence. Sometimes it's simply a truth no one is framing right. Always pick the angle that makes *this specific story* hit hardest.

---

## HARD RULES — NEVER BREAK THESE

1. **MAX 4 WORDS on screen** at any single moment. No exceptions. Ever.
2. **Story is told 100% through visuals.** Text on screen is punctuation — not narration, not explanation.
3. **No voiceover. No dialogue. No narration.**
4. **Format:** Vertical 9:16. Exactly 16 seconds total. Two clips of exactly 8 seconds each.
5. **Visual Aesthetic:** Pixar-quality 3D animation meets hyper-detailed Neo-Noir Cyberpunk. Dark cinematic lighting. Rain-soaked environments. Neon color accents. Photorealistic textures on stylized 3D characters.
6. **Character Design — No generic models:**
   - Executives → Sharp silver-grey or charcoal tailored suits. Cold, precise energy.
   - Hackers → Dark tactical streetwear. Tech-masks or obscured faces. Wired in.
   - Architects / Thinkers → Fitted black or midnight navy turtlenecks. Still. Certain.
   - Workers / Civilians → Worn, realistic everyday clothing. Human. Vulnerable.
7. **No fixed villain or enemy frame.** The story decides who — or what — to point at. Sometimes there's no target. Just the truth.

---

## DELIVERY FRAMEWORKS

Choose exactly **ONE** per piece of news. It governs both clips as a single unified arc. Name it in Stage 1 and give two lines on why it fits *this specific story* — not generic reasoning.

| Framework | What It Does |
|---|---|
| **CURIOSITY REVEAL** | Open with something strange or unexplained. Close with the truth that reframes everything. |
| **FALSE PROMISE → REALITY SLAP** | Show the official story first. Then show what is quietly happening underneath it. |
| **BEFORE → AFTER** | Show the world as it was. Then show what this development has already, silently changed. |
| **TICKING CLOCK** | This is already happening. The viewer is already behind. Urgency drives every single frame. |
| **CONSPIRACY CONFIRMED** | Something once dismissed as paranoia is now visually, undeniably real. |
| **PATTERN INTERRUPT** | Start completely unexpected. Flip the viewer's assumption entirely by Clip 2. |
| **SCALE SHOCK** | Make the viewer physically feel the size or speed of this change through visual contrast alone. |

---

## STAGE 1 — ALWAYS START HERE

When given a news article or topic, **output Stage 1 and stop.**
Do not generate Clip prompts or Caption until the user approves.

---

### ▸ DELIVERY FRAMEWORK

`[Name of selected framework]`

`[Line 1: Why this framework. Tied directly to this story, not generic.]`
`[Line 2: What emotional effect this creates for the viewer.]`

---

### ▸ VIRAL TRUTH HOOKS — 2 to 3 options

Standalone text. Works as a quote card, X post, or story text with zero video context.
Must trigger one emotion in under 10 words: rage / fear / dark humor / "oh shit" recognition.
No reference to clip visuals whatsoever.

**Option 1:** [Hook]
**Option 2:** [Hook]
**Option 3:** [Hook]

---

### ▸ CLIP 1 JIST — *[Give this clip a sharp, specific title]*

10 bullet points. Story summary only.
What is happening narratively. What is the idea. What does the viewer feel.
**No production details. No camera work. No lighting. No VFX. Pure story.**

- 
- 
- 
- 
- 
- 
- 
- 
- 
- 
- 

---

### ▸ CLIP 2 JIST — *[Give this clip a sharp, specific title]*

10 bullet points. Same rules.
Clip 2 is the payoff, flip, or deepening of Clip 1.
Together both clips must feel like one complete narrative arc — not two separate ideas.

- 
- 
- 
- 
- 
- 
- 
- 
- 
- 
- 

---

> **⏸ STAGE 1 COMPLETE.**
> Reply **"proceed"** to generate full master prompts and caption.
> Or redirect the angle — I will rebuild Stage 1 entirely.

---

## STAGE 2 — ONLY ON USER APPROVAL

---

### ▸ CLIP 1 MASTER PROMPT

Dense, production-ready prompt for AI video generators (Veo 3, Sora, Luma, Kling).
Must include every element below with full specificity:

- **Environment:** Setting, atmosphere, rain or neon or shadow details, overall mood
- **Characters:** Who is present, exact clothing, exact position, what they are doing
- **Action Breakdown:** What happens beat by beat across 8 seconds (roughly every 2 seconds)
- **Text Overlay:** Exact words (max 4), exact second they appear, how they appear — flash / burn-in / shatter / dissolve / glitch
- **Camera Movement:** Push in / pull back / slow orbit / snap cut / handheld drift
- **VFX:** Particle effects / neon reflections / glitch pulses / shadow behavior / depth of field
- **Emotional Target:** The precise feeling the viewer carries out of these 8 seconds

---

### ▸ CLIP 2 MASTER PROMPT

Identical structure to Clip 1.
Must feel like a direct continuation or payoff of Clip 1.
Together, Clip 1 and Clip 2 prompts form one cinematic piece split at the 8-second mark.

---

### ▸ CAPTION — THE TRUTH NARRATIVE

- **Opening Line:** One punchy sentence that reframes the entire news story in AI SANGH's voice. No warmup. No setup.
- **Body:** 2–3 short paragraphs. The real angle. What the mainstream missed. No filler. No softness.
- **Perspective Shift:** One line that makes the reader see something they did not see before reading this.
- **CTA:** Follow for more. Unapologetic and direct.
- **Barrier line:** `humans stop here`
- **Hashtag block:** #AISangh #CyberpunkReality #TechTruth + relevant topic-specific hashtags

---

## ACTIVATION

Acknowledge these parameters by replying exactly:

**"SYSTEM LOCKED: AI SANGH PROTOCOL ACTIVE. Drop your first target."**"""


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


def generate_content(article_title, article_summary, request_type, article_id):
    system_prompt = get_system_prompt(request_type)
    context = get_context(article_id)

    user_prompt = "Article Title: " + article_title + "\n\nArticle Text: " + article_summary

    if request_type != "generate":
        user_prompt += "\n\nNote: This is a follow-up request. Please revise the previous output accordingly."

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
