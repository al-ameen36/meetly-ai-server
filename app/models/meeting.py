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
    user_id: str


class MeetingTable:
    def __init__(self, supabase_client, user_id):
        self.client = supabase_client
        self.user_id = user_id
        self.title = ""

    async def create_new(self):
        try:
            meeting = (
                self.client.table("meetings")
                .insert(
                    MeetingCreate(
                        status="in-progress",
                        title=datetime.now().strftime("%H:%M %a %d %b, %Y"),
                        user_id=self.user_id,
                    ).model_dump()
                )
                .execute()
            )

            self.id = meeting.data[0]["id"]
            self.title = meeting.data[0]["title"]
        except Exception as e:
            raise Exception(f"Failed to create meeting: {e}")
