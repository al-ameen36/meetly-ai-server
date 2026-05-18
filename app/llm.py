import os
from openai import AsyncOpenAI, Client

openai_client: Client | None = None
try:
    OPENAI_MODEL = os.environ.get("OPENAI_MODEL")
    OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
    OPENAI_API_BASE_URL = os.environ.get("OPENAI_API_BASE_URL")

    if not OPENAI_API_BASE_URL and not OPENAI_API_KEY and not OPENAI_MODEL:
        raise Exception(
            "OPENAI_API_KEY, OPENAI_API_BASE_URL and OPENAI_MODEL not set in environment"
        )

    openai_client = (
        AsyncOpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_API_BASE_URL)
        if OPENAI_API_KEY
        else None
    )
    if not openai_client:
        raise Exception("Failed to initalize openai client")
except ImportError:
    penai_client = None
    raise Exception("openai python package not installed.")


class LLMClient:
    def __init__(self):
        self.client = openai_client

    async def generate_insights(self, content: str):
        try:
            response = await openai_client.chat.completions.create(
                model=OPENAI_MODEL,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a specialized meeting assistant. Extract any key insights, action items, or decisions from the following transcript segment. If it's just casual conversation with no clear insights, return an empty string. Be extremely concise (use brief bullet points).",
                    },
                    {"role": "user", "content": content},
                ],
                temperature=0.3,
            )
            insight_text = response.choices[0].message.content.strip()
            print("-" * 10)
            print(insight_text)
            return insight_text

        except Exception as e:
            raise Exception(f"Failed to extract or save insights: {e}")
