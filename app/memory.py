import asyncio


class TranscriptBuffer:
    def __init__(self, on_flush=None, timeout: float = 6.0, char_limit: int = 600):
        self.timeout = timeout
        self.char_limit = char_limit
        self.buffer = ""
        self.lock = asyncio.Lock()
        self.timer_task: asyncio.Task | None = None
        self.on_flush = on_flush

    def get_buffer(self):
        return self.buffer

    async def add_text(self, text: str):
        text = text.strip()
        if not text:
            return

        async with self.lock:
            if self.buffer and not self.buffer.endswith(" "):
                self.buffer += " "
            self.buffer += text

            if self._should_flush():
                await self._flush()
                self._cancel_timer()
            else:
                self._restart_timer()

    def _should_flush(self) -> bool:
        return len(self.buffer) >= self.char_limit and self.buffer.strip().endswith(
            (".", "?", "!")
        )

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
                if self.buffer:
                    await self._flush()
        except asyncio.CancelledError:
            pass

    async def _flush(self) -> str:
        text = self.buffer
        self.buffer = ""

        if self.on_flush:
            await self.on_flush(text)
        return text
