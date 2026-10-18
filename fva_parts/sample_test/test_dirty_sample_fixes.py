"""باگ‌هایی که آزمون متن کثیف (صفحه‌های واقعی کتاب) پیدا کرد.

هر مورد از خروجی واقعی fva.py روی متن کتاب آمده است:
- ۱۵۰۰۰۰۰ نفر → ۱۵۰ نفر (ocr_normalizer صفرها را «حرف تکراری» می‌دید)
- نخست‌وزیر → نخست و زیر (fix_attached_waw)
- تیتر و فهرست هرگز خوانده نمی‌شدند (split_chapters)
- «/» در عدد مبهم بود (۲/۵ میلیون، ۲/۵۰۰/۰۰۰)
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from processors.ocr_normalizer import normalize_ocr_line  # noqa: E402
from core.text_cleaner import fix_attached_waw, clean_text  # noqa: E402


# ── ۱. عددها نباید کوتاه شوند ──
@pytest.mark.parametrize("src", ["برابر با ۱۵۰۰۰۰۰ نفر", "۱۰۰۰۰۰۰", "سال ۱۳۳۳", "1000000"])
def test_digit_runs_survive_ocr_normalizer(src):
    assert normalize_ocr_line(src) == src


def test_repeated_letters_still_collapse():
    assert normalize_ocr_line("ایس سسسسسران") == "ایس سران"


# ── ۲. «و» چسبیده ──
@pytest.mark.parametrize("src,expected", [
    ("وابسته\u200cوهمدل", "وابسته و همدل"),
    ("صلح\u200cوامنیت", "صلح و امنیت"),
    ("خانه\u200cو\u200cکاشانه", "خانه و کاشانه"),
    ("به\u200cوی", "به وی"),
])
def test_attached_waw_conjunction_is_split(src, expected):
    assert fix_attached_waw(src) == expected


@pytest.mark.parametrize("word", [
    "نخست\u200cوزیر", "نخست\u200cوزیری", "جلای\u200cوطن", "هم\u200cوطنان", "بی\u200cوقفه",
    "حمله\u200cور", "پیشه\u200cوران", "پیشه\u200cوری", "بهره\u200cوری", "می\u200cورزید",
    "دیوانه\u200cوار", "قهرمانان\u200cورزشی",
])
def test_compounds_with_waw_are_kept(word):
    assert fix_attached_waw(word) == word


# ── ۳. «/» در عدد ──
@pytest.mark.parametrize("src,expected", [
    ("۲/۵ میلیون خانواده", "۲ ممیز ۵ میلیون خانواده"),
    ("۲/۵۰۰/۰۰۰ نفر", "۲۵۰۰۰۰۰ نفر"),
    ("۲۵۰/۰۰۰ تن", "۲۵۰۰۰۰ تن"),
    ("2/5 درصد", "۲ ممیز ۵ درصد"),
    ("در ۱۳۵۷/۱۱/۲۲", "در ۱۳۵۷/۱۱/۲۲"),
])
def test_number_slash(src, expected):
    assert clean_text(src) == expected


# ── ۴. تیترها خوانده می‌شوند ──
ITEMS = [
    {"type": "heading", "text": "پاسخ به تاریخ"},
    {"type": "heading", "text": "دیباچه"},
    {"type": "heading", "text": "قسمت اول: پاسخ به تاریخ"},
    {"type": "paragraph", "text": "متن دیباچه."},
    {"type": "heading", "text": "فصل چهارم"},
    {"type": "paragraph", "text": "متن فصل."},
]


@pytest.mark.parametrize("module", ["fva", "audiobook"])
def test_headings_are_spoken(module):
    mod = pytest.importorskip(module)
    chapters = mod.split_chapters(ITEMS)
    S, L = '<break time="400ms"/>', '<break time="900ms"/>'
    assert chapters == [
        ("پاسخ به تاریخ", [f"پاسخ به تاریخ {L}", f"دیباچه {L}", f"قسمت اول {S} پاسخ به تاریخ {L}", "متن دیباچه."]),
        ("فصل چهارم", [f"فصل چهارم {L}", "متن فصل."]),
    ]


@pytest.mark.parametrize("module", ["fva", "audiobook"])
@pytest.mark.parametrize("heading,expected", [
    ("فصل دوم: بهره\u200cوری", 'فصل دوم <break time="400ms"/> بهره\u200cوری <break time="900ms"/>'),
    ("فصل ۲ - آغاز", 'فصل ۲ <break time="400ms"/> آغاز <break time="900ms"/>'),
    ("فصل چهارم", 'فصل چهارم <break time="900ms"/>'),
    ("پاسخ به تاریخ.", 'پاسخ به تاریخ <break time="900ms"/>'),
])
def test_heading_label_and_title_get_separate_pauses(module, heading, expected):
    mod = pytest.importorskip(module)
    assert mod.spoken_heading(heading) == expected


def test_heading_breaks_survive_every_path():
    """تگ مکث تیتر در هر سه مسیر درست فهمیده می‌شود و هرگز خوانده نمی‌شود."""
    import fva
    from core.prosody import add_prosody
    from core.ssml_builder import build_ssml, strip_ssml
    from engines.edge_engine import _split_ssml
    h = fva.spoken_heading("فصل دوم: بهره\u200cوری") + " متن."
    for ssml in (build_ssml(add_prosody(h)), h):          # fva/audiobook ، tts_txt (بدون build_ssml)
        seg = _split_ssml(ssml)
        texts = [v.strip() for k, v in seg if k == "text" and v.strip()]
        assert texts[:2] == ["فصل دوم", "بهره\u200cوری"]
        assert [v for k, v in seg if k == "break"][:2] == [400, 900]
        assert all("<" not in t and "break" not in t for t in texts)
    assert "<" not in strip_ssml(add_prosody(h))         # Piper


@pytest.mark.parametrize("module", ["fva", "audiobook"])
def test_no_headings_unchanged(module):
    mod = pytest.importorskip(module)
    chapters = mod.split_chapters([{"type": "paragraph", "text": "الف"}, {"type": "paragraph", "text": "ب"}])
    assert len(chapters) == 1 and chapters[0][1] == ["الف", "ب"]
