from pydantic import BaseModel
from shutil import ExecError


class Insight(BaseModel):
    content: str
    segment_id: str


class InsightsTable:
    def __init__(self, supabase_client):
        self.client = supabase_client

    async def add(self, insight: Insight):
        try:
            print(insight.content)
            print(insight.segment_id)
            response = (
                self.client.table("segments")
                .update({"insights": insight.content})
                .eq("id", insight.segment_id)
                .execute()
            )


            if not response.data:
                raise ExecError("No row returned after insert")

            return response.data[0]

        except Exception as e:
            raise ExecError(f"Failed to save insight: {e}")
