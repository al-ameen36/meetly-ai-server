import asyncio
import json
from contextlib import suppress

from dotenv import load_dotenv
from fastapi import (
    Depends,
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


async def get_current_user(websocket: WebSocket):
    await websocket.accept()

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

    print(f"User connected: {user.id}")
    return user


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    user=Depends(get_current_user),
):
    meeting = MeetingTable(supabase_client, user_id=user.id)
    meeting_row = await meeting.create_new()

    transcript_segments = SegmentsTable(supabase_client)
    insights_table = InsightsTable(supabase_client)

    llm_queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue()

    async def save_insight(segment_id: str, insight_text: str):
        await insights_table.add(
            Insight(
                content=insight_text,
                segment_id=segment_id,
                meeting_id=meeting.id,
            )
        )

    llm = LLMClient(on_insight=save_insight)

    async def llm_worker():
        while True:
            segment_id, content = await llm_queue.get()
            try:
                await llm.generate_insights(segment_id, content)
            except Exception as e:
                print("Failed to extract or save insights:", e)
            finally:
                llm_queue.task_done()

    worker_task = asyncio.create_task(llm_worker())

    async def on_flush(segment: Segment):
        new_segment = await transcript_segments.add(segment)
        segment_id = new_segment["id"]

        await llm_queue.put((segment_id, segment.content))

    transcript_buffer = TranscriptBuffer(
        meeting_id=meeting.id,
        on_flush=on_flush,
        timeout=6.0,
        char_limit=600,
    )

    outgoing: asyncio.Queue[str] = asyncio.Queue()

    async def sender():
        while True:
            payload = await outgoing.get()
            await websocket.send_text(payload)

    sender_task = asyncio.create_task(sender())

    try:
        async with AsyncClient(api_key=SPEECHMATICS_SECRET) as client:

            def push(msg):
                outgoing.put_nowait(json.dumps(msg))

            @client.on(ServerMessageType.ADD_TRANSCRIPT)
            def handle_final(msg):
                metadata = msg.get("metadata", {})
                text = (metadata.get("transcript") or "").strip()

                if text:
                    segment = Segment(
                        content=text,
                        meeting_id=meeting.id,
                        start_time=float(metadata.get("start_time") or 0.0),
                        end_time=float(metadata.get("end_time") or 0.0),
                    )
                    asyncio.create_task(transcript_buffer.add(segment))

                push(msg)

            @client.on(ServerMessageType.ADD_PARTIAL_TRANSCRIPT)
            def handle_partial(msg):
                push(msg)

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

        with suppress(asyncio.CancelledError):
            await sender_task

        with suppress(asyncio.CancelledError):
            await worker_task