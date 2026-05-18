import os
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


class LLMClient:
    def __init__(self, on_insight):
        self.client = client
        self.on_insight = on_insight

    async def generate_insights(self, segment_id: str, content: str):
        response = await self.client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a specialized meeting assistant. "
                        "Extract any key insights, action items, decisions, risks, "
                        "or follow-ups from the transcript segment. "
                        "If there is nothing useful, return an empty string. "
                        "Be extremely concise."
                    ),
                },
                {
                    "role": "user",
                    "content": content,
                },
            ],
            temperature=0.3,
        )

        insight_text = (response.choices[0].message.content or "").strip()

        if insight_text:
            await self.on_insight(segment_id, insight_text)

        return insight_text