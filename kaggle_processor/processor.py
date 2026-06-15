#!/usr/bin/env python3
"""
Kaggle Processor for AI News Bot.

This script runs on Kaggle, loads the Qwen model, polls the queue,
processes pending requests, and sends results back to Telegram.

Setup:
1. Upload this script to Kaggle
2. Set environment variables:
   - TELEGRAM_BOT_TOKEN
   - TELEGRAM_CHAT_ID
   - QUEUE_FILE (path to request_queue.json)
   - QWEN_MODEL (default: Qwen/Qwen2.5-14B-Instruct)
3. Mount Google Drive or use Kaggle Dataset for queue storage
"""

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer


class KaggleProcessor:
    """Processes queue requests using Qwen model on Kaggle."""

    def __init__(
        self,
        model_name: str = "Qwen/Qwen2.5-14B-Instruct",
        queue_file: str = "request_queue.json",
        poll_interval: int = 30,
    ):
        self.model_name = model_name
        self.queue_file = Path(queue_file)
        self.poll_interval = poll_interval
        self.model = None
        self.tokenizer = None

        # Telegram config
        self.telegram_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")

        # Context memory for each article
        self.context_memory: dict[str, list[dict]] = {}

    def load_model(self) -> None:
        """Load Qwen model and tokenizer."""
        print(f"Loading model: {self.model_name}")

        self.tokenizer = AutoTokenizer.from_pretrained(
            self.model_name,
            trust_remote_code=True,
        )

        self.model = AutoModelForCausalLM.from_pretrained(
            self.model_name,
            torch_dtype=torch.float16,
            device_map="auto",
            trust_remote_code=True,
        )

        print("Model loaded successfully!")

    def send_telegram_message(self, message: str, chat_id: Optional[str] = None) -> bool:
        """Send a message to Telegram."""
        if not self.telegram_token:
            print("TELEGRAM_BOT_TOKEN not set, skipping notification")
            return False

        chat_id = chat_id or self.telegram_chat_id
        if not chat_id:
            print("TELEGRAM_CHAT_ID not set, skipping notification")
            return False

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"

        # Split long messages (Telegram limit is 4096 chars)
        chunks = self._split_message(message, max_length=4000)

        for chunk in chunks:
            payload = {
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "Markdown",
            }

            try:
                response = requests.post(url, json=payload, timeout=30)
                response.raise_for_status()
                print(f"Telegram message sent successfully")
            except requests.exceptions.RequestException as e:
                print(f"Failed to send Telegram message: {e}")
                return False

        return True

    def _split_message(self, message: str, max_length: int = 4000) -> list[str]:
        """Split message into chunks for Telegram."""
        if len(message) <= max_length:
            return [message]

        chunks = []
        lines = message.split("\n")
        current_chunk = ""

        for line in lines:
            if len(current_chunk) + len(line) + 1 <= max_length:
                current_chunk += line + "\n"
            else:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                current_chunk = line + "\n"

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks

    def read_queue(self) -> dict:
        """Read queue from JSON file."""
        try:
            with open(self.queue_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"requests": [], "completed": []}

    def write_queue(self, data: dict) -> None:
        """Write queue to JSON file."""
        with open(self.queue_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def get_pending_requests(self) -> list[dict]:
        """Get all pending requests."""
        queue = self.read_queue()
        return [r for r in queue.get("requests", []) if r["status"] == "pending"]

    def update_request_status(
        self, request_id: str, status: str, result: str = None
    ) -> Optional[dict]:
        """Update request status and move to completed if done."""
        queue = self.read_queue()

        for i, request in enumerate(queue.get("requests", [])):
            if request["id"] == request_id:
                request["status"] = status
                request["completed_at"] = datetime.now(timezone.utc).isoformat()
                if result:
                    request["result"] = result

                # Move to completed list if terminal state
                if status in ("completed", "failed"):
                    queue["completed"].append(queue["requests"].pop(i))

                self.write_queue(queue)
                return request

        return None

    def get_context(self, article_id: str) -> list[dict]:
        """Get conversation context for an article."""
        return self.context_memory.get(article_id, [])

    def add_to_context(self, article_id: str, role: str, content: str) -> None:
        """Add a message to the conversation context."""
        if article_id not in self.context_memory:
            self.context_memory[article_id] = []

        self.context_memory[article_id].append({
            "role": role,
            "content": content,
        })

        # Keep only last 10 messages for context window
        if len(self.context_memory[article_id]) > 10:
            self.context_memory[article_id] = self.context_memory[article_id][-10:]

    def generate_script(
        self,
        article_title: str,
        article_summary: str,
        request_type: str,
        article_id: str,
    ) -> str:
        """Generate content using Qwen model."""
        # Build prompt based on request type
        system_prompt = self._get_system_prompt(request_type)
        user_prompt = self._build_user_prompt(
            article_title, article_summary, request_type
        )

        # Get conversation context
        context = self.get_context(article_id)

        # Build messages for chat template
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(context)
        messages.append({"role": "user", "content": user_prompt})

        # Generate response
        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True,
        )

        inputs = self.tokenizer([text], return_tensors="pt").to(self.model.device)

        outputs = self.model.generate(
            **inputs,
            max_new_tokens=2048,
            temperature=0.7,
            top_p=0.9,
            do_sample=True,
        )

        response = self.tokenizer.decode(
            outputs[0][inputs.input_ids.shape[1]:],
            skip_special_tokens=True,
        )

        # Store in context memory
        self.add_to_context(article_id, "user", user_prompt)
        self.add_to_context(article_id, "assistant", response)

        return response

    def _get_system_prompt(self, request_type: str) -> str:
        """Get system prompt based on request type."""
        base_prompt = """You are an expert content creator specializing in AI/tech content for social media.
You create engaging, viral content that educates and entertains.
Always include relevant hashtags and maintain a professional yet approachable tone."""

        if request_type == "generate":
            return base_prompt + "\nCreate a comprehensive script for the given news story."
        elif request_type == "shorter":
            return base_prompt + "\nMake the previous script shorter and more concise while keeping key points."
        elif request_type == "longer":
            return base_prompt + "\nExpand the previous script with more details and examples."
        elif request_type == "more viral":
            return base_prompt + "\nRewrite the previous script to be more engaging and viral-worthy. Add hooks and emotional triggers."
        elif request_type == "carousel":
            return base_prompt + "\nCreate a carousel post format with 5-7 slides, each with a key point."
        elif request_type == "caption":
            return base_prompt + "\nCreate an engaging social media caption for this news."
        elif request_type == "30 second reel":
            return base_prompt + "\nCreate a script for a 30-second Instagram reel. Keep it punchy and visual."
        elif request_type == "60 second reel":
            return base_prompt + "\nCreate a script for a 60-second Instagram reel with more depth."
        else:
            return base_prompt

    def _build_user_prompt(
        self,
        article_title: str,
        article_summary: str,
        request_type: str,
    ) -> str:
        """Build user prompt for the request."""
        context_note = ""
        if request_type != "generate":
            context_note = "\n\nNote: This is a follow-up request. Please revise the previous output accordingly."

        return f"""Article Title: {article_title}

Article Summary: {article_summary}

Request: {request_type}{context_note}

Please create the content based on this article."""

    def process_request(self, request: dict) -> bool:
        """Process a single request."""
        request_id = request["id"]
        article_id = request["article_id"]
        article_title = request["article_title"]
        request_type = request["request_type"]

        print(f"Processing request: {request_type} for {article_title}")

        # Mark as processing
        self.update_request_status(request_id, "processing")

        try:
            # For non-generate commands, we need the article summary from context
            # or from the request itself
            article_summary = request.get("user_message", "")

            # Generate content
            result = self.generate_script(
                article_title=article_title,
                article_summary=article_summary,
                request_type=request_type,
                article_id=article_id,
            )

            # Mark as completed
            self.update_request_status(request_id, "completed", result)

            # Send to Telegram
            chat_id = request.get("chat_id")
            if chat_id:
                response_msg = (
                    f"✅ *{request_type.title()}* for:\n"
                    f"📰 {article_title}\n\n"
                    f"{result}"
                )
                self.send_telegram_message(response_msg, str(chat_id))

            print(f"Request {request_id} completed successfully")
            return True

        except Exception as e:
            error_msg = str(e)
            print(f"Error processing request {request_id}: {error_msg}")

            # Mark as failed
            self.update_request_status(request_id, "failed", error_msg)

            # Notify user of failure
            chat_id = request.get("chat_id")
            if chat_id:
                fail_msg = (
                    f"❌ Failed to process {request_type} for:\n"
                    f"📰 {article_title}\n\n"
                    f"Error: {error_msg}"
                )
                self.send_telegram_message(fail_msg, str(chat_id))

            return False

    def poll_and_process(self) -> None:
        """Main loop: poll queue and process requests."""
        print(f"Starting queue poller (interval: {self.poll_interval}s)")

        # Notify that Qwen is online
        self.send_telegram_message("🟢 Qwen is online and ready.")

        while True:
            try:
                pending = self.get_pending_requests()
                if pending:
                    print(f"Found {len(pending)} pending request(s)")
                    for request in pending:
                        self.process_request(request)
                else:
                    print(f"No pending requests. Waiting {self.poll_interval}s...")

                time.sleep(self.poll_interval)

            except KeyboardInterrupt:
                print("Shutting down processor...")
                self.send_telegram_message("🔴 Qwen session ended.")
                break
            except Exception as e:
                print(f"Error in poll loop: {e}")
                time.sleep(10)


def main():
    """Main entry point for Kaggle processor."""
    # Configuration
    model_name = os.getenv("QWEN_MODEL", "Qwen/Qwen2.5-14B-Instruct")
    queue_file = os.getenv("QUEUE_FILE", "request_queue.json")
    poll_interval = int(os.getenv("POLL_INTERVAL", "30"))

    # Create processor
    processor = KaggleProcessor(
        model_name=model_name,
        queue_file=queue_file,
        poll_interval=poll_interval,
    )

    # Load model
    processor.load_model()

    # Start processing
    processor.poll_and_process()


if __name__ == "__main__":
    main()
