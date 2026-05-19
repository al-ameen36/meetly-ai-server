from shutil import ExecError
from pydantic import BaseModel


class Segment(BaseModel):
    content: str
    user_id:str
    meeting_id: str
    start_time: float
    end_time: float


class SegmentsTable:
    def __init__(self, supabase_client):
        self.client = supabase_client

    async def add(self, segment: Segment):
        try:
            response = (
                self.client
                .table("segments")
                .insert(segment.model_dump())
                .execute()
            )

            return response.data[0]

        except Exception as e:
            raise ExecError(
                f"Failed to save transcript segment: {e}"
            )