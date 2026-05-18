import asyncio
import json
from collections import deque
from contextlib import suppress

from dotenv import load_dotenv
from fastapi import (
    FastAPI,
    WebSocket,
    WebSocketDisconnect,
    WebSocketException,
    status,
)

from speechmatics.rt import (
    AsyncClient,
    ServerMessageType,
)

from app.utils.db import supabase_client
from app.utils.llm import LLMClient
from app.utils.memory import TranscriptBuffer
from app.models.insights import Insight, InsightsTable
from app.models.meeting import MeetingTable
from app.models.segments import Segment, SegmentsTable
from app.utils.speech import audio_format, speechmatics_config, SPEECHMATICS_SECRET

load_dotenv()

app = FastAPI()

meeting_table = MeetingTable(supabase_client)
transcript_segments = SegmentsTable(supabase_client)
insights_table = InsightsTable(supabase_client)


class RecentInsights:
    def __init__(self, limit: int = 15):
        self._insights = deque(maxlen=limit)

    def add(self, insight: Insight):
        self._insights.append(insight)

    def get(self) -> str:
        return "\n".join(
            f"{item.type}: {item.content}" for item in self._insights
        )


async def get_current_user(websocket: WebSocket):
    try:
        raw = await websocket.receive_text()
        data = json.loads(raw)
    except Exception:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    token = data.get("token")
    if not token:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    try:
        result = supabase_client.auth.get_user(token)
        user = result.user
    except Exception:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    if not user:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)

    return user


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()

    user = await get_current_user(websocket)
    print(f"User connected: {user.id}")

    meeting_row = await meeting_table.create_new(user.id)
    meeting_id = meeting_row["id"]

    recent_insights = RecentInsights()
    outgoing: asyncio.Queue[str] = asyncio.Queue()
    llm_queue: asyncio.Queue[tuple[str, str, str]] = asyncio.Queue()
    segment_queue: asyncio.Queue[Segment] = asyncio.Queue()

    async def sender():
        while True:
            payload = await outgoing.get()
            try:
                await websocket.send_text(payload)
            except Exception:
                break

    async def save_insight(segment_id: str, insight_data: dict):
        if not insight_data or insight_data.get("type") == "none":
            return

        insight_row = Insight(
            content=insight_data.get("content", ""),
            type=insight_data["type"],
            segment_id=segment_id,
            meeting_id=meeting_id,
        )

        saved = await insights_table.add(insight_row)
        recent_insights.add(insight_row)

        outgoing.put_nowait(
            json.dumps(
                {
                    "message": "Insight",
                    "data": {
                        "id": saved.get("id"),
                        "content": saved.get("content", insight_row.content),
                        "type": saved.get("type", insight_row.type),
                        "segment_id": saved.get("segment_id", segment_id),
                        "meeting_id": saved.get("meeting_id", meeting_id),
                    },
                }
            )
        )

    llm = LLMClient(on_insight=save_insight)

    async def llm_worker():
        while True:
            segment_id, content, memory_snapshot = await llm_queue.get()
            try:
                await llm.generate_insights(segment_id, content, memory_snapshot)
            except Exception as e:
                print("Failed to extract or save insights:", e)
            finally:
                llm_queue.task_done()

    async def on_flush(segment: Segment):
        saved_segment = await transcript_segments.add(segment)
        segment_id = saved_segment["id"]

        await llm_queue.put(
            (
                segment_id,
                segment.content,
                recent_insights.get(),
            )
        )

    transcript_buffer = TranscriptBuffer(
        meeting_id=meeting_id,
        on_flush=on_flush,
        timeout=6.0,
        char_limit=600,
    )

    async def segment_worker():
        while True:
            segment = await segment_queue.get()
            try:
                await transcript_buffer.add(segment)
            except Exception as e:
                print("Failed to buffer segment:", e)
            finally:
                segment_queue.task_done()

    sender_task = asyncio.create_task(sender())
    worker_task = asyncio.create_task(llm_worker())
    segment_task = asyncio.create_task(segment_worker())

    try:
        await websocket.send_text(json.dumps({"message": "auth_ok"}))

        async with AsyncClient(api_key=SPEECHMATICS_SECRET) as client:

            def push(msg):
                outgoing.put_nowait(json.dumps(msg))

            @client.on(ServerMessageType.ADD_TRANSCRIPT)
            def handle_final(msg):
                try:
                    metadata = msg.get("metadata", {})
                    text = (metadata.get("transcript") or "").strip()

                    if text:
                        segment_queue.put_nowait(
                            Segment(
                                content=text,
                                meeting_id=meeting_id,
                                start_time=float(metadata.get("start_time") or 0.0),
                                end_time=float(metadata.get("end_time") or 0.0),
                            )
                        )

                    push(msg)
                except Exception as e:
                    print("handle_final error:", e)

            @client.on(ServerMessageType.ADD_PARTIAL_TRANSCRIPT)
            def handle_partial(msg):
                try:
                    push(msg)
                except Exception as e:
                    print("handle_partial error:", e)

            await client.start_session(
                transcription_config=speechmatics_config,
                audio_format=audio_format,
            )

            while True:
                message = await websocket.receive()

                if message["type"] == "websocket.disconnect":
                    break

                if message.get("text") is not None:
                    continue

                chunk = message.get("bytes")
                if chunk:
                    await client.send_audio(chunk)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print("WebSocket error:", e)
    finally:
        sender_task.cancel()
        worker_task.cancel()
        segment_task.cancel()

        with suppress(asyncio.CancelledError):
            await sender_task

        with suppress(asyncio.CancelledError):
            await worker_task

        with suppress(asyncio.CancelledError):
            await segment_task

        with suppress(Exception):
            await websocket.close()