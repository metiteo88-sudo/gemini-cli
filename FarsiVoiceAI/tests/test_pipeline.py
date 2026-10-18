import asyncio

import pytest

from farsivoice import engines, pipeline
from farsivoice.engines import AutoEngine, EdgeEngine, EngineError, PiperEngine, get_engine


def test_get_engine_defaults_match_golden_settings():
    e = get_engine("edge")
    assert isinstance(e, EdgeEngine)
    assert (e.voice, e.rate, e.pitch) == ("fa-IR-FaridNeural", "-11%", "-8Hz")


def test_get_engine_ignores_irrelevant_options():
    assert isinstance(get_engine("piper", voice="x", rate=None), PiperEngine)
    assert isinstance(get_engine("auto", rate="-5%"), AutoEngine)


def test_unknown_engine():
    with pytest.raises(EngineError):
        get_engine("gemini")


def test_text_to_voice_cleans_before_engine(monkeypatch, tmp_path):
    seen = {}

    class Fake:
        async def synthesize(self, text, out):
            seen["text"] = text
            return out

    monkeypatch.setattr(pipeline, "get_engine", lambda *a, **k: Fake())
    asyncio.run(pipeline.text_to_voice("سال 1400 ...", str(tmp_path / "o.mp3")))
    assert seen["text"] == "سال ۱۴۰۰ …"


def test_empty_text_rejected(tmp_path):
    with pytest.raises(ValueError):
        asyncio.run(pipeline.text_to_voice("  ", str(tmp_path / "o.mp3")))


def test_auto_falls_back_to_piper(monkeypatch, tmp_path):
    async def edge_fail(self, text, out):
        raise EngineError("blocked")

    async def piper_ok(self, text, out):
        return "piper:" + out

    monkeypatch.setattr(engines.EdgeEngine, "synthesize", edge_fail)
    monkeypatch.setattr(engines.PiperEngine, "synthesize", piper_ok)
    result = asyncio.run(AutoEngine().synthesize("سلام", "x.wav"))
    assert result == "piper:x.wav"
