import os

from fastapi import FastAPI
from speechmatics.rt import (
    AudioEncoding,
    AudioFormat,
    TranscriptionConfig,
)

SPEECHMATICS_SECRET = os.environ.get("SPEECHMATICS_SECRET")
if not SPEECHMATICS_SECRET:
    raise RuntimeError("SPEECHMATICS_SECRET environment variable is not set.")

app = FastAPI()

audio_format = AudioFormat(
    encoding=AudioEncoding.PCM_F32LE,
    sample_rate=16000,
)

speechmatics_config = TranscriptionConfig(
    language="en",
    max_delay=0.7,
    enable_partials=True,
)
