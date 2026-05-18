from shutil import ExecError
from pydantic import BaseModel
from datetime import datetime


class Segment(BaseModel):
    content: str
    end_time: datetime
    meeting_id: str
    start_time: datetime


class SegmentsTable:
    def __init__(self, supabase_client):
        self.client = supabase_client

    async def insert(self, segment: Segment):
        try:
            self.client.table("transcript_segments").insert(
                segment.model_dump()
            ).execute()
        except Exception as e:
            raise ExecError(f"Failed to save transcript segment to Supabase: {e}")
