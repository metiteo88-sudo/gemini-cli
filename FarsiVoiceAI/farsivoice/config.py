"""Single source of truth for all default settings.

These values are taken from the "golden" script (edge_audiobook_golden.py)
so the generated voice sounds exactly like before.
Every value can be overridden from the CLI or with environment variables.
"""

import os

# --- Edge TTS (online, Microsoft) ---
EDGE_VOICE = os.getenv("FARSIVOICE_VOICE", "fa-IR-FaridNeural")
EDGE_RATE = os.getenv("FARSIVOICE_RATE", "-11%")
EDGE_PITCH = os.getenv("FARSIVOICE_PITCH", "-8Hz")

# --- Piper (offline) ---
PIPER_BIN = os.getenv("FARSIVOICE_PIPER_BIN", "piper")
PIPER_MODEL = os.getenv("FARSIVOICE_PIPER_MODEL", "fa_IR-gyro-medium")
PIPER_SAMPLE_RATE = 22050

# Silence inserted between sentences by the Piper engine (seconds).
SENTENCE_PAUSE = float(os.getenv("FARSIVOICE_SENTENCE_PAUSE", "0.6"))

# Default engine: "edge", "piper" or "auto" (edge, falls back to piper).
DEFAULT_ENGINE = os.getenv("FARSIVOICE_ENGINE", "edge")

# Where the API stores generated audio files.
OUTPUT_DIR = os.getenv("FARSIVOICE_OUTPUT_DIR", "output")
