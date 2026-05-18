from typing import Literal, Awaitable, Callable, Optional, Any
from pydantic import BaseModel
import json
import os
import re

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


class InsightResponse(BaseModel):
    type: Literal[
        "action_item",
        "decision",
        "risk",
        "follow_up",
        "update",
        "none",
    ]
    content: str = ""


def _clean_raw_json(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""

    # Remove fenced blocks if the model adds them
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    return raw.strip()


class LLMClient:
    def __init__(
        self,
        on_insight: Optional[Callable[[str, dict[str, Any]], Awaitable[None]]] = None,
    ):
        self.client = client
        self.on_insight = on_insight

    async def generate_insights(self, segment_id: str, content: str,recent_insights:str) -> Optional[dict]:
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
                        '{ "type": "action_item|decision|risk|follow_up|update|none", "content": "string" }\n\n'
                        'If nothing useful exists, return { "type": "none", "content": "" }.'
                    ),
                },
                {
                    "role": "user",
                    "content": content,
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

        if parsed.type != "none" and self.on_insight:
            await self.on_insight(segment_id,parsed)

        return parsed