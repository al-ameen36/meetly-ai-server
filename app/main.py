from app.llm import LLMClient
from app.memory import TranscriptBuffer
from app.models.meeting import MeetingTable
from contextlib import suppress
import asyncio
import json

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, WebSocket, WebSocketDisconnect

from speechmatics.rt import (
    AsyncClient,
    ServerMessageType,
)

from app.db import supabase_client
from app.speech import (
    audio_format,
    speechmatics_config,
    SPEECHMATICS_SECRET,
)

load_dotenv()

app = FastAPI()
llm = LLMClient()


async def get_current_user(websocket: WebSocket):
    await websocket.accept()

    auth_message = await websocket.receive_text()

    try:
        data = json.loads(auth_message)
    except Exception:
        await websocket.close(code=1008)
        raise WebSocketDisconnect()

    token = data.get("token")

    if not token:
        await websocket.close(code=1008)
        raise WebSocketDisconnect()

    try:
        result = supabase_client.auth.get_user(token)
        user = result.user
    except Exception:
        await websocket.close(code=1008)
        raise WebSocketDisconnect()

    if not user:
        await websocket.close(code=1008)
        raise WebSocketDisconnect()

    print(f"User: {user.id} connected")
    return user


@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    user=Depends(get_current_user),
):
    meeting = MeetingTable(supabase_client, user_id=user.id)
    await meeting.create_new()

    transcript_buffer = TranscriptBuffer(on_flush=llm.generate_insights)

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
                text = msg.get("metadata", {}).get("transcript", "")
                if text:
                    asyncio.create_task(transcript_buffer.add_text(text))

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

                # text frame
                if "text" in message and message["text"] is not None:
                    continue

                # binary audio frame
                chunk = message.get("bytes")

                if chunk:
                    await client.send_audio(chunk)

    except WebSocketDisconnect:
        pass

    except Exception as e:
        print("WebSocket error:", e)

    finally:
        sender_task.cancel()

        with suppress(asyncio.CancelledError):
            await sender_task
