from app.models.insights import Insight
from typing import Literal, Awaitable, Callable, Optional, Any
from pydantic import BaseModel
import json
import os
import re
from difflib import SequenceMatcher

from openai import AsyncOpenAI

OPENAI_MODEL = os.environ.get("OPENAI_MODEL")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_API_BASE_URL = os.environ.get("OPENAI_API_BASE_URL")

if not OPENAI_MODEL:
    raise RuntimeError("OPENAI_MODEL is not set")

if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY is not set")

client = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_API_BASE_URL or None,
)

# Similarity threshold: 0.0 = no match, 1.0 = exact match.
# 0.8 catches rephrased duplicates while allowing genuinely new insights through.
DEDUP_SIMILARITY_THRESHOLD = 0.8


class InsightResponse(BaseModel):
    type: Literal[
        "action_item",
        "decision",
        "risk",
        "task",
        "update",
        "none",
    ]
    content: str = ""


def _clean_raw_json(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""

    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    return raw.strip()


def _is_duplicate(new_content: str, recent_insights: list[InsightResponse], threshold: float) -> bool:
    """
    Returns True if new_content is too similar to any previously emitted insight.
    Uses SequenceMatcher for fuzzy comparison so rephrased duplicates are caught.
    """
    new_normalized = new_content.strip().lower()
    for insight in recent_insights:
        existing_normalized = insight.content.strip().lower()
        ratio = SequenceMatcher(None, new_normalized, existing_normalized).ratio()
        if ratio >= threshold:
            return True
    return False


class LLMClient:
    def __init__(
        self,
        on_insight: Optional[Callable[[str, dict[str, Any]], Awaitable[None]]] = None,
    ):
        self.client = client
        self.on_insight = on_insight
        # Keeps a rolling list of emitted InsightResponse objects for deduplication.
        self._emitted: list[InsightResponse] = []

    async def generate_insights(
        self,
        segment_id: str,
        content: str,
        recent_insights: str,
    ) -> Optional[InsightResponse]:
        response = await self.client.chat.completions.create(
            model=OPENAI_MODEL,
            temperature=0.3,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a meeting intelligence system.\n"
                        "Return ONLY valid JSON.\n"
                        "Do NOT use markdown.\n"
                        "Do NOT wrap in code fences.\n\n"
                        "Schema:\n"
                        '{ "type": "action_item|decision|risk|task|update|none", "content": "string" }\n\n'
                        'If nothing useful exists, return { "type": "none", "content": "" }.\n\n'
                        "IMPORTANT: The recent insights below have already been captured. "
                        "Do NOT repeat or rephrase any of them. "
                        "Only return something new and distinct, or return none."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"**Recent insights (do not repeat these):**\n{recent_insights}\n\n"
                        f"**Current segment to analyze:**\n{content}"
                    ),
                },
            ],
        )

        raw = _clean_raw_json(response.choices[0].message.content or "")
        if not raw:
            return None

        try:
            parsed_json = json.loads(raw)
        except Exception as e:
            print("Failed to parse insight JSON:", e)
            print("RAW RESPONSE:", raw)
            return None

        if not isinstance(parsed_json, dict):
            print("Insight response was not a JSON object:", parsed_json)
            return None

        if "type" not in parsed_json:
            print("Missing type field:", parsed_json)
            return None

        try:
            parsed = InsightResponse.model_validate(parsed_json)
        except Exception as e:
            print("Failed to validate insight JSON:", e)
            print("RAW PARSED JSON:", parsed_json)
            return None

        if parsed.type == "none":
            return parsed

        # Structural deduplication — catches cases where the prompt instruction alone
        # wasn't enough (e.g. model rephrased an existing insight).
        if _is_duplicate(parsed.content, self._emitted, DEDUP_SIMILARITY_THRESHOLD):
            print("Duplicate insight suppressed:", parsed.content)
            return None

        self._emitted.append(parsed)

        if self.on_insight:
            await self.on_insight(segment_id, parsed)

        return parsed