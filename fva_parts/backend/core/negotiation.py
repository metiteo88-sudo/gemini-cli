"""لایه ۱ — مذاکرهٔ هم‌زمان اعراب‌گذار ↔ واج‌آرا (کشف ۲ و ۳).

مشکل فعلی (تأییدشده در کد): prepare_text اول واژه‌نامه را اعمال می‌کند (اعراب می‌گذارد)
و بعد CANINE دوباره روی همان کلمه اعراب می‌گذارد ← اعراب دوبل/متناقض.

راه‌حل: هر دو ستون روی «یک متن ورودی» جداگانه پیشنهاد می‌دهند و برای هر کلمه
یک تصمیم گرفته می‌شود. هر تصمیم در گزارش ثبت می‌شود (همان schema گزارش OCR:
stage, where, kind, original, suggestion, confidence) تا ویراستار نهایی اعمال کند.

قاعده‌های مذاکره برای هر کلمه:
  ۱. ماسک کلمهٔ کلیدی       ← دست‌نخورده (لایه ۲ رسیدگی می‌کند)
  ۲. اعراب دستی در ورودی    ← اعراب دستی برنده است (کشف ۱)
  ۳. واج‌آرا شکل دارد       ← واج‌آرا برنده؛ اعراب‌گذار روی آن اعراب نمی‌گذارد
  ۴. فقط اعراب‌گذار          ← قبول، به شرطی که حروف را عوض نکرده و اعراب متناقض نداشته باشد
  ۵. هیچ‌کدام               ← کلمهٔ اصلی
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from core.keywords import is_mask
from core.lexicon import TTS_LEXICON

MARKS = "\u064b\u064c\u064d\u064e\u064f\u0650\u0651\u0652"
_SHORT_VOWELS = "\u064e\u064f\u0650"  # فتحه، ضمه، کسره
_MARK_RE = re.compile(f"[{MARKS}]")
# علائم چسبیده به کلمه (، . « » ؟) جدا می‌شوند؛ اعراب جزو کلمه می‌ماند
_TOKEN_RE = re.compile(rf"^([^\w\u200c{MARKS}]*)(.*?)([^\w\u200c{MARKS}]*)$", re.S)
_CONTRADICTION_RE = re.compile(f"[{_SHORT_VOWELS}]\u0651?[{_SHORT_VOWELS}]")


@dataclass
class Decision:
    stage: str
    where: str
    kind: str
    original: str
    suggestion: str
    confidence: float

    def to_dict(self) -> dict:
        return asdict(self)


def strip_marks(word: str) -> str:
    return _MARK_RE.sub("", word)


def has_marks(word: str) -> bool:
    return bool(_MARK_RE.search(word))


def phonemizer_propose(word: str, lexicon: dict[str, str] | None = None) -> str | None:
    """ستون واج‌آرا: شکل تلفظی کلمه، اگر شناخته‌شده باشد."""
    lex = TTS_LEXICON if lexicon is None else lexicon
    return lex.get(strip_marks(word))


def _split_token(token: str) -> tuple[str, str, str]:
    m = _TOKEN_RE.match(token)
    return (m.group(1), m.group(2), m.group(3)) if m else ("", token, "")


def negotiate(text: str, diacritized: str | None, where: str = "",
              lexicon: dict[str, str] | None = None) -> tuple[str, list[Decision]]:
    """text: متن ماسک‌شدهٔ ویراستاری‌شده. diacritized: خروجی اعراب‌گذار روی همان متن (یا None)."""
    words = text.split(" ")
    report: list[Decision] = []

    d_words: list[str] | None = None
    if diacritized is not None:
        d_words = diacritized.split(" ")
        if len(d_words) != len(words):
            report.append(Decision("negotiation", where, "alignment_failed", text, diacritized, 0.0))
            d_words = None

    out: list[str] = []
    for i, token in enumerate(words):
        loc = f"{where}#w{i}"
        if not token or is_mask(token):
            out.append(token)
            continue

        pre, word, post = _split_token(token)
        d_word = _split_token(d_words[i])[1] if d_words else None

        if has_marks(word):  # قاعده ۲
            if d_word and d_word != word:
                report.append(Decision("negotiation", loc, "manual_kept", word, d_word, 1.0))
            out.append(token)
            continue

        p_word = phonemizer_propose(word, lexicon)
        if p_word:  # قاعده ۳
            kind = "phonemizer" if not d_word or d_word == p_word else "conflict_phonemizer_wins"
            report.append(Decision("negotiation", loc, kind, d_word or word, p_word, 0.95))
            out.append(pre + p_word + post)
            continue

        if d_word and d_word != word:  # قاعده ۴
            if strip_marks(d_word) != word:
                report.append(Decision("negotiation", loc, "rejected_letters_changed", word, d_word, 0.0))
            elif _CONTRADICTION_RE.search(d_word):
                report.append(Decision("negotiation", loc, "rejected_contradictory_marks", word, d_word, 0.0))
            else:
                report.append(Decision("negotiation", loc, "diacritizer", word, d_word, 0.6))
                out.append(pre + d_word + post)
                continue

        out.append(token)  # قاعده ۵
    return " ".join(out), report
