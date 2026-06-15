#!/usr/bin/env python3
"""GitHub-based queue storage for real-time sync."""

import base64
import json
import os
from datetime import datetime, timezone
from typing import Optional

import requests


class GitHubStorage:
    """Read/write queue to GitHub for shared access."""

    def __init__(
        self,
        token: str = None,
        repo: str = None,
        file_path: str = "request_queue.json",
    ):
        self.token = token or os.getenv("GITHUB_TOKEN", "")
        self.repo = repo or os.getenv("GITHUB_REPO", "theaisangh1/news-update")
        self.file_path = file_path
        self.api_url = f"https://api.github.com/repos/{self.repo}/contents/{self.file_path}"
        self.headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json",
        }

    def read_queue(self) -> dict:
        """Read queue from GitHub."""
        try:
            response = requests.get(self.api_url, headers=self.headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                content = base64.b64decode(data["content"]).decode("utf-8")
                return json.loads(content)
            elif response.status_code == 404:
                # File doesn't exist, create it
                self.write_queue({"requests": [], "completed": [], "conversations": {}})
                return {"requests": [], "completed": [], "conversations": {}}
            else:
                print(f"GitHub read error: {response.status_code}")
                return {"requests": [], "completed": [], "conversations": {}}
        except Exception as e:
            print(f"GitHub read failed: {e}")
            return {"requests": [], "completed": [], "conversations": {}}

    def write_queue(self, data: dict) -> bool:
        """Write queue to GitHub."""
        try:
            # Get current file SHA (required for updates)
            response = requests.get(self.api_url, headers=self.headers, timeout=30)
            sha = None
            if response.status_code == 200:
                sha = response.json().get("sha")

            # Prepare content
            content = json.dumps(data, indent=2, ensure_ascii=False)
            encoded = base64.b64encode(content.encode("utf-8")).decode("utf-8")

            payload = {
                "message": f"Update queue {datetime.now(timezone.utc).isoformat()}",
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

            if response.status_code in (200, 201):
                return True
            else:
                print(f"GitHub write error: {response.status_code}")
                return False
        except Exception as e:
            print(f"GitHub write failed: {e}")
            return False

    def get_pending_requests(self) -> list[dict]:
        """Get all pending requests."""
        queue = self.read_queue()
        return [r for r in queue.get("requests", []) if r["status"] == "pending"]

    def add_request(
        self,
        article_id: str,
        article_title: str,
        request_type: str,
        user_message: str = "",
        user_id: int = None,
        chat_id: int = None,
    ) -> dict:
        """Add a new request to the queue."""
        import uuid
        queue = self.read_queue()

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
        self.write_queue(queue)
        return request

    def update_request_status(
        self, request_id: str, status: str, result: str = None
    ) -> Optional[dict]:
        """Update request status."""
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
        """Get conversation history for an article."""
        queue = self.read_queue()
        conversations = queue.get("conversations", {})
        return conversations.get(article_id, [])

    def add_to_conversation(self, article_id: str, role: str, content: str) -> None:
        """Add message to conversation history."""
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

        # Keep last 20 messages
        if len(queue["conversations"][article_id]) > 20:
            queue["conversations"][article_id] = queue["conversations"][article_id][-20:]

        self.write_queue(queue)


# Global instance
github_storage = GitHubStorage()
