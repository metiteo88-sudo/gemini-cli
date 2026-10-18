"""تست معماری لایه‌ای روی ماژول‌های واقعی پروژه.
CANINE واقعی لازم نیست؛ اعراب‌گذار با یک تابع ساختگی جایگزین می‌شود."""

import asyncio

import pytest

from core.handshake import FARID_SETTINGS, HandshakeError, SignedText
from core.keywords import KeywordRegistry
from core.layered_pipeline import LayeredPipeline, report_rows
from core.negotiation import negotiate, strip_marks

FATHA, KASRA, SUKUN, DAMMA = "\u064e", "\u0650", "\u0652", "\u064f"


def fake_canine(text):
    """بعد از هر حرف اول کلمه فتحه می‌گذارد (حتی روی کلمات واژه‌نامه — مثل CANINE واقعی)."""
    return " ".join(w[0] + FATHA + w[1:] if w and w[0].isalpha() else w for w in text.split(" "))


# ---------------- کلمات کلیدی (لایه ۲) ----------------

def test_keywords_mask_and_unmask_roundtrip():
    reg = KeywordRegistry.default()
    masked, found = reg.mask("محمدرضا پهلوی و داریوش آمدند.")
    assert "پهلوی" not in masked and "داریوش" not in masked
    assert found == ["محمدرضا پهلوی", "داریوش"]
    assert reg.unmask(masked, found) == "محمدرضا پهلوی و داریوش آمدند."


def test_keyword_spoken_form_comes_from_lexicon():
    reg = KeywordRegistry.default()
    masked, found = reg.mask("استقرار نظم")
    assert reg.unmask(masked, found) == "اِستِقرار نظم"


def test_keyword_recognised_after_text_analyzer_changed_it():
    # text_analyzer قبلاً کوروش را به «کورُش» تبدیل می‌کند
    reg = KeywordRegistry.default()
    masked, found = reg.mask("کورُش بزرگ")
    assert found == ["کورُش"]


def test_unmask_ignores_marks_injected_inside_mask():
    reg = KeywordRegistry.default()
    masked, found = reg.mask("داریوش")
    damaged = masked.replace("kw", "k" + FATHA + "w")
    assert reg.unmask(damaged, found) == "داریوش"


# ---------------- مذاکره اعراب‌گذار ↔ واج‌آرا ----------------

def test_phonemizer_wins_and_no_double_marks():
    text = "مرد استقرار یافت"
    out, report = negotiate(text, fake_canine(text))
    words = out.split(" ")
    assert words[1] == "اِستِقرار"           # از واژه‌نامه، بدون فتحهٔ اضافی CANINE
    assert words[0] == "م" + FATHA + "رد"    # کلمهٔ عادی ← پیشنهاد اعراب‌گذار
    assert any(d.kind == "conflict_phonemizer_wins" for d in report)


def test_manual_diacritics_are_kept():
    text = "کتابِ تاریخ"
    out, report = negotiate(text, fake_canine(text))
    assert out.split(" ")[0] == "کتابِ"
    assert any(d.kind == "manual_kept" for d in report)


def test_rejects_diacritizer_that_changes_letters():
    out, report = negotiate("مرد", "مارد")
    assert out == "مرد" and report[0].kind == "rejected_letters_changed"


def test_rejects_contradictory_marks():
    out, report = negotiate("کتاب", "ک" + DAMMA + KASRA + "تاب")
    assert out == "کتاب" and report[0].kind == "rejected_contradictory_marks"


def test_alignment_failure_falls_back_safely():
    out, report = negotiate("یک دو", "یکدو")
    assert strip_marks(out) == "یِک دو".replace(KASRA, "") and report[0].kind == "alignment_failed"


def test_punctuation_is_preserved():
    out, _ = negotiate("«استقرار»، آمد.", None)
    assert out == "«اِستِقرار»، آمد."


# ---------------- کل زنجیره ----------------

BOOK = "دیباچه\n\nکوروش بزرگ در پاسارگاد آرمیده است، و استقرار نظم مهم بود.\n"


def test_full_chain_produces_signed_items_and_clean_ssml():
    p = LayeredPipeline(diacritizer=fake_canine, use_diacritizer=True)
    items = p.layer1(BOOK)
    assert [i.type for i in items] == ["section_title", "blank", "normal_text"]
    assert all(isinstance(i.signed, SignedText) for i in items if i.type != "blank")

    ssml = p.to_ssml(items[2])
    assert ssml.startswith("<speak>") and ssml.count("<speak>") == 1
    assert "<break_" not in ssml                 # تگ خام به موتور نمی‌رسد
    assert "کورُش" in ssml and "اِستِقرار" in ssml  # تلفظ ثابت کلیدی‌ها
    assert "⟦" not in ssml
    assert '<break time="900ms"/>' in p.to_ssml(items[0])  # مکث بعد از تیتر
    assert report_rows(items)


def test_engine_rejects_text_signed_for_other_settings():
    p = LayeredPipeline()
    item = p.layer1("مرد آمد.")[0]
    other = LayeredPipeline(settings={**FARID_SETTINGS, "rate": "-15%"})
    with pytest.raises(HandshakeError) as e:
        other.to_ssml(item)
    assert e.value.reason == "engine_mismatch"


def test_synthesize_calls_edge_engine_with_farid_settings(tmp_path):
    calls = {}

    async def fake_generate_voice(text, out, voice, rate, pitch, is_ssml):
        calls.update(text=text, voice=voice, rate=rate, pitch=pitch, is_ssml=is_ssml)

    p = LayeredPipeline()
    item = p.layer1("داریوش آمد.")[0]
    asyncio.run(p.synthesize(item, str(tmp_path / "o.mp3"), generate_voice=fake_generate_voice))
    assert (calls["voice"], calls["rate"], calls["pitch"], calls["is_ssml"]) == ("fa-IR-FaridNeural", "-11%", "-8Hz", True)
    assert "داریوش" in calls["text"]


def test_works_without_diacritizer():
    p = LayeredPipeline(use_diacritizer=True, diacritizer=None)
    p.diacritizer = None
    items = LayeredPipeline().layer1("مرد آمد.")
    assert items[0].signed.text.startswith("مرد")
