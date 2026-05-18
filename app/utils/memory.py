import asyncio
from typing import Awaitable, Callable, Optional

from app.models.segments import Segment


class TranscriptBuffer:
    def __init__(
        self,
        meeting_id: str,
        on_flush: Callable[[Segment], Awaitable[None]],
        timeout: float = 6.0,
        char_limit: int = 600,
    ):
        self.meeting_id = meeting_id
        self.on_flush = on_flush
        self.timeout = timeout
        self.char_limit = char_limit

        self.buffer = ""
        self.start_time: Optional[float] = None
        self.end_time: Optional[float] = None

        self.lock = asyncio.Lock()
        self.timer_task: asyncio.Task | None = None

    async def add(self, segment: Segment):
        text = segment.content.strip()
        if not text:
            return

        async with self.lock:
            if not self.buffer:
                self.start_time = segment.start_time

            if self.buffer and not self.buffer.endswith(" "):
                self.buffer += " "

            self.buffer += text
            self.end_time = segment.end_time

            if self._should_flush(text):
                await self._flush_locked()
                self._cancel_timer()
            else:
                self._restart_timer()

    def _should_flush(self, latest_text: str) -> bool:
        sentence_end = latest_text.endswith((".", "?", "!"))
        too_long = len(self.buffer) >= self.char_limit
        return sentence_end or too_long

    def _restart_timer(self):
        self._cancel_timer()
        self.timer_task = asyncio.create_task(self._flush_later())

    def _cancel_timer(self):
        if self.timer_task and not self.timer_task.done():
            self.timer_task.cancel()

    async def _flush_later(self):
        try:
            await asyncio.sleep(self.timeout)
            async with self.lock:
                if self.buffer.strip():
                    await self._flush_locked()
        except asyncio.CancelledError:
            pass

    async def _flush_locked(self):
        text = self.buffer.strip()
        if not text:
            return

        segment = Segment(
            content=text,
            meeting_id=self.meeting_id,
            start_time=self.start_time or 0.0,
            end_time=self.end_time or 0.0,
        )

        self.buffer = ""
        self.start_time = None
        self.end_time = None

        await self.on_flush(segment)