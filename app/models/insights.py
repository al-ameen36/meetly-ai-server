from pydantic import BaseModel


class Insight(BaseModel):
    content: str
    segment_id: str
    user_id:str
    type: str


class InsightsTable:
    def __init__(self, supabase_client):
        self.client = supabase_client

    async def add(self,insight: Insight):
        try:
            response = (
                self.client.table("insights")
                .insert(insight.model_dump())
                .execute()
            )

            if not response.data:
                raise RuntimeError("No row returned after insert")

            return response.data[0]

        except Exception as e:
            raise RuntimeError(f"Failed to save insight: {e}") from e