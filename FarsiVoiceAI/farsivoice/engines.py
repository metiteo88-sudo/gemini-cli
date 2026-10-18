"""TTS engines.

- edge  : Microsoft Edge neural voices (online). Replaces the 9 copies of
          edge_audiobook*.py / edge_book.py.
- piper : fully offline. Replaces piper_engine.py + book_to_voice.py.
- auto  : try edge, fall back to piper if edge fails (e.g. no internet / blocked).

Every engine exposes:  async synthesize(text, output_path) -> output_path
"""

import asyncio
import os
import shutil
import subprocess
import tempfile

from . import config
from .text import split_sentences


class EngineError(RuntimeError):
    pass


def _require(binary: str, hint: str) -> None:
    if shutil.which(binary) is None:
        raise EngineError(f"«{binary}» پیدا نشد. {hint}")


def _ffmpeg(*args: str) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", *args],
        check=True,
    )


class EdgeEngine:
    name = "edge"

    def __init__(self, voice=None, rate=None, pitch=None):
        self.voice = voice or config.EDGE_VOICE
        self.rate = rate or config.EDGE_RATE
        self.pitch = pitch or config.EDGE_PITCH

    async def synthesize(self, text: str, output_path: str) -> str:
        try:
            import edge_tts
        except ImportError as exc:
            raise EngineError("edge-tts نصب نیست: pip install edge-tts") from exc

        tmp_mp3 = output_path if output_path.lower().endswith(".mp3") else output_path + ".mp3"
        communicate = edge_tts.Communicate(text, voice=self.voice, rate=self.rate, pitch=self.pitch)
        try:
            await communicate.save(tmp_mp3)
        except Exception as exc:  # network errors, 403, DNS, ...
            if os.path.exists(tmp_mp3):
                os.remove(tmp_mp3)  # don't leave an empty/partial file behind
            raise EngineError(f"Edge TTS ناموفق بود: {exc}") from exc

        if tmp_mp3 != output_path:  # user asked for .wav / .ogg ...
            _require("ffmpeg", "برای خروجی غیر از mp3 لازم است: pkg install ffmpeg")
            _ffmpeg("-i", tmp_mp3, output_path)
            os.remove(tmp_mp3)
        return output_path


class PiperEngine:
    name = "piper"

    def __init__(self, model=None, sentence_pause=None):
        self.model = model or config.PIPER_MODEL
        self.sentence_pause = config.SENTENCE_PAUSE if sentence_pause is None else sentence_pause

    def _sentence_to_wav(self, sentence: str, wav_path: str) -> None:
        raw = wav_path + ".piper"
        subprocess.run([config.PIPER_BIN, "-m", self.model, "-f", raw, "--", sentence], check=True)
        with open(raw, "rb") as f:
            is_wav = f.read(4) == b"RIFF"
        if is_wav:
            # Piper already wrote a proper WAV: just normalize the format.
            _ffmpeg("-i", raw, "-ar", str(config.PIPER_SAMPLE_RATE), "-ac", "1", "-c:a", "pcm_s16le", wav_path)
        else:
            # Raw float32 output (the behaviour the old piper_engine.py relied on).
            _ffmpeg("-f", "f32le", "-ar", str(config.PIPER_SAMPLE_RATE), "-ac", "1",
                    "-i", raw, "-c:a", "pcm_s16le", wav_path)
        os.remove(raw)

    def _synthesize_sync(self, text: str, output_path: str) -> str:
        _require(config.PIPER_BIN, "Piper را نصب کنید: pip install piper-tts")
        _require("ffmpeg", "pkg install ffmpeg  (یا apt install ffmpeg)")

        sentences = split_sentences(text)
        if not sentences:
            raise EngineError("متنی برای خواندن وجود ندارد")

        with tempfile.TemporaryDirectory(prefix="farsivoice_") as tmp:
            silence = os.path.join(tmp, "silence.wav")
            _ffmpeg("-f", "lavfi", "-i", f"anullsrc=r={config.PIPER_SAMPLE_RATE}:cl=mono",
                    "-t", str(self.sentence_pause), "-c:a", "pcm_s16le", silence)

            parts = []
            for i, sentence in enumerate(sentences, 1):
                print(f"[{i}/{len(sentences)}] {sentence}")
                wav = os.path.join(tmp, f"s{i:05d}.wav")
                self._sentence_to_wav(sentence, wav)
                parts.append(wav)
                if i < len(sentences):
                    parts.append(silence)

            list_file = os.path.join(tmp, "list.txt")
            with open(list_file, "w", encoding="utf-8") as f:
                f.writelines(f"file '{p}'\n" for p in parts)

            _ffmpeg("-f", "concat", "-safe", "0", "-i", list_file, output_path)
        return output_path

    async def synthesize(self, text: str, output_path: str) -> str:
        return await asyncio.to_thread(self._synthesize_sync, text, output_path)


class AutoEngine:
    """Edge first; if it fails (offline / blocked), use Piper."""

    name = "auto"

    def __init__(self, **kwargs):
        self.edge = EdgeEngine(**{k: v for k, v in kwargs.items() if k in ("voice", "rate", "pitch")})
        self.piper = PiperEngine(**{k: v for k, v in kwargs.items() if k in ("model", "sentence_pause")})

    async def synthesize(self, text: str, output_path: str) -> str:
        try:
            return await self.edge.synthesize(text, output_path)
        except EngineError as exc:
            print(f"⚠️ {exc}\n↪️ استفاده از Piper (آفلاین)...")
            return await self.piper.synthesize(text, output_path)


ENGINES = {"edge": EdgeEngine, "piper": PiperEngine, "auto": AutoEngine}


def get_engine(name: str = None, **options):
    name = (name or config.DEFAULT_ENGINE).lower()
    if name not in ENGINES:
        raise EngineError(f"موتور ناشناخته: {name}  (گزینه‌ها: {', '.join(ENGINES)})")
    cls = ENGINES[name]
    if cls is EdgeEngine:
        options = {k: v for k, v in options.items() if k in ("voice", "rate", "pitch")}
    elif cls is PiperEngine:
        options = {k: v for k, v in options.items() if k in ("model", "sentence_pause")}
    return cls(**{k: v for k, v in options.items() if v is not None})
