from pydantic import BaseModel


class Insight(BaseModel):
    content: str
    segment_id: int


class InsightsTable:
    def __init__(self, supabase_client):
        self.client = supabase_client

    async def insert(self, insight: Insight):

        try:
            self.client.table("meeting_insights").insert(insight.model_dump()).execute()
        except Exception as e:
            raise Exception(f"Failed to save meeting insights: {e}")
