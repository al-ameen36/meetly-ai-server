from typing import Literal
from pydantic import BaseModel
from datetime import datetime


# class Meeting(BaseModel):
#     end_time: datetime | None
#     id: str
#     start_time: datetime
#     status: Literal["ended", "in-progress"]
#     title: str
#     user_id: str


class MeetingCreate(BaseModel):
    status: Literal["ended", "in-progress"]
    title: str


from shutil import ExecError
from datetime import datetime, timezone


class MeetingTable:
    def __init__(self, supabase_client):
        self.client = supabase_client

    async def create_new(self):

        payload = {
            "title": f"Meeting {datetime.now(timezone.utc).isoformat()}",
            "status": "in_progress",
            "start_time": datetime.now(timezone.utc).isoformat(),
        }

        try:
            response = self.client.table("meetings").insert(payload).execute()

            if not response.data:
                raise ExecError("No row returned after meeting insert")

            return response.data[0]

        except Exception as e:
            raise ExecError(f"Failed to create meeting: {e}")
