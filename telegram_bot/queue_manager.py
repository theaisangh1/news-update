#!/usr/bin/env python3
"""Lightweight JSON-based queue for Telegram bot requests."""

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


class QueueManager:
    """Manages a JSON-based request queue for Telegram bot."""

    def __init__(self, queue_file: str = "request_queue.json"):
        self.queue_file = Path(queue_file)
        self._ensure_file_exists()

    def _ensure_file_exists(self) -> None:
        """Create queue file if it doesn't exist."""
        if not self.queue_file.exists():
            self._write_queue({"requests": [], "completed": []})

    def _read_queue(self) -> dict:
        """Read queue from JSON file."""
        try:
            with open(self.queue_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {"requests": [], "completed": []}

    def _write_queue(self, data: dict) -> None:
        """Write queue to JSON file."""
        with open(self.queue_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def add_request(
        self,
        article_id: str,
        article_title: str,
        request_type: str,
        user_message: str = "",
        user_id: Optional[int] = None,
        chat_id: Optional[int] = None,
    ) -> dict:
        """Add a new request to the queue."""
        queue = self._read_queue()

        request = {
            "id": str(uuid.uuid4()),
            "article_id": article_id,
            "article_title": article_title,
            "request_type": request_type,
            "user_message": user_message,
            "user_id": user_id,
            "chat_id": chat_id,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
            "result": None,
        }

        queue["requests"].append(request)
        self._write_queue(queue)
        return request

    def get_pending_requests(self) -> list[dict]:
        """Get all pending requests."""
        queue = self._read_queue()
        return [r for r in queue.get("requests", []) if r["status"] == "pending"]

    def mark_completed(self, request_id: str, result: str) -> Optional[dict]:
        """Mark a request as completed and store the result."""
        queue = self._read_queue()

        for i, request in enumerate(queue.get("requests", [])):
            if request["id"] == request_id:
                request["status"] = "completed"
                request["completed_at"] = datetime.now(timezone.utc).isoformat()
                request["result"] = result

                # Move to completed list
                queue["completed"].append(queue["requests"].pop(i))
                self._write_queue(queue)
                return request

        return None

    def mark_failed(self, request_id: str, error: str) -> Optional[dict]:
        """Mark a request as failed."""
        queue = self._read_queue()

        for i, request in enumerate(queue.get("requests", [])):
            if request["id"] == request_id:
                request["status"] = "failed"
                request["completed_at"] = datetime.now(timezone.utc).isoformat()
                request["result"] = f"ERROR: {error}"

                # Move to completed list
                queue["completed"].append(queue["requests"].pop(i))
                self._write_queue(queue)
                return request

        return None

    def get_request_by_id(self, request_id: str) -> Optional[dict]:
        """Get a specific request by ID."""
        queue = self._read_queue()
        for request in queue.get("requests", []) + queue.get("completed", []):
            if request["id"] == request_id:
                return request
        return None

    def get_requests_by_article(self, article_id: str) -> list[dict]:
        """Get all requests for a specific article."""
        queue = self._read_queue()
        return [
            r for r in queue.get("requests", []) + queue.get("completed", [])
            if r["article_id"] == article_id
        ]

    def get_recent_completed(self, limit: int = 10) -> list[dict]:
        """Get recent completed requests."""
        queue = self._read_queue()
        completed = queue.get("completed", [])
        return completed[-limit:]

    def cleanup_old_requests(self, max_age_hours: int = 24) -> int:
        """Remove old completed requests."""
        queue = self._read_queue()
        now = datetime.now(timezone.utc)
        cleaned = 0

        new_completed = []
        for request in queue.get("completed", []):
            try:
                created = datetime.fromisoformat(request["created_at"])
                if (now - created).total_seconds() < max_age_hours * 3600:
                    new_completed.append(request)
                else:
                    cleaned += 1
            except (ValueError, KeyError):
                new_completed.append(request)

        queue["completed"] = new_completed
        self._write_queue(queue)
        return cleaned


# Global queue instance
queue_manager = QueueManager(os.getenv("QUEUE_FILE", "request_queue.json"))
