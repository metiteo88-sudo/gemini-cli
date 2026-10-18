import pytest

from core.handshake import (
    FARID_SETTINGS,
    HandshakeError,
    SignedText,
    engine_code,
    find_forbidden_tags,
    require_handshake,
    run,
    sign,
    verify,
)

TEXT = "کوروش بزرگ در پاسارگاد آرمیده است."


def test_engine_code_is_stable_and_order_independent():
    reordered = dict(reversed(list(FARID_SETTINGS.items())))
    assert engine_code(FARID_SETTINGS) == engine_code(reordered)
    assert len(engine_code(FARID_SETTINGS)) == 12


def test_engine_code_changes_with_settings():
    other = {**FARID_SETTINGS, "rate": "-15%"}
    assert engine_code(other) != engine_code(FARID_SETTINGS)


def test_sign_and_verify_roundtrip():
    assert verify(sign(TEXT, FARID_SETTINGS), FARID_SETTINGS) == TEXT


def test_unsigned_text_rejected():
    with pytest.raises(HandshakeError) as e:
        verify(TEXT, FARID_SETTINGS)
    assert e.value.reason == "not_signed"


def test_engine_mismatch_rejected():
    signed = sign(TEXT, {**FARID_SETTINGS, "pitch": "+0Hz"})
    with pytest.raises(HandshakeError) as e:
        verify(signed, FARID_SETTINGS)
    assert e.value.reason == "engine_mismatch"


def test_modified_text_rejected():
    s = sign(TEXT, FARID_SETTINGS)
    tampered = SignedText(text=TEXT + " اضافه", engine_code=s.engine_code, signature=s.signature)
    with pytest.raises(HandshakeError) as e:
        verify(tampered, FARID_SETTINGS)
    assert e.value.reason == "text_modified"


@pytest.mark.parametrize("bad", ["سلام <break_short> دنیا", "نام <phoneme ph='x'>کوروش</phoneme>"])
def test_raw_tags_cannot_be_signed(bad):
    with pytest.raises(HandshakeError) as e:
        sign(bad, FARID_SETTINGS)
    assert e.value.reason == "raw_tags"


def test_real_break_tags_are_allowed():
    ssml = '<speak>سلام<break time="500ms"/>دنیا</speak>'
    assert find_forbidden_tags(ssml) == []
    assert verify(sign(ssml, FARID_SETTINGS), FARID_SETTINGS) == ssml


def test_decorator_blocks_bypass():
    calls = []

    @require_handshake(FARID_SETTINGS)
    def generate_voice(text, out):
        calls.append((text, out))
        return out

    assert generate_voice(sign(TEXT, FARID_SETTINGS), "a.mp3") == "a.mp3"
    with pytest.raises(HandshakeError):
        generate_voice(TEXT, "b.mp3")
    assert calls == [(TEXT, "a.mp3")]


def test_run_self_heals_after_engine_mismatch():
    old = {**FARID_SETTINGS, "rate": "-10%"}
    feedbacks = []

    def edit(text, feedback):
        feedbacks.append(feedback)
        # دور اول ویراستار با تنظیمات قدیمی امضا می‌کند، بعد از برگشت درست
        return sign(text, old if feedback is None else FARID_SETTINGS)

    synth = require_handshake(FARID_SETTINGS)(lambda text: "ok:" + text)
    assert run(TEXT, edit, synth, FARID_SETTINGS) == "ok:" + TEXT
    assert feedbacks[0] is None and feedbacks[1].reason == "engine_mismatch"


def test_run_gives_up_after_max_rounds():
    def edit(text, feedback):
        return sign(text, {**FARID_SETTINGS, "voice": "fa-IR-DilaraNeural"})

    synth = require_handshake(FARID_SETTINGS)(lambda text: text)
    with pytest.raises(HandshakeError) as e:
        run(TEXT, edit, synth, FARID_SETTINGS, max_rounds=2)
    assert e.value.reason == "engine_mismatch"
