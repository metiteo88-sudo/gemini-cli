"""لایه ۲ — خط لولهٔ کلمات کلیدی (کشف ۵).

کلمات کلیدی (کوروش، داریوش، محمدرضا پهلوی، استقرار، ...) در لایه ۱ «ماسک» می‌شوند
تا ستون‌ها (ویراستار، اعراب‌گذار، واج‌آرا) به آن‌ها دست نزنند و کُند نشوند.
بعد از Handshake، لایه ۲ ماسک را با تلفظ ثابت همان کلمه جایگزین می‌کند.

ماسک فقط از حروف لاتین و ⟦ ⟧ ساخته شده، چون clean_text اعداد را فارسی می‌کند
و SmartTextEditor دور «- . : ،» فاصله می‌گذارد.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from core.lexicon import HISTORICAL_NAMES, TTS_LEXICON

_MARKS = "\u064b\u064c\u064d\u064e\u064f\u0650\u0651\u0652"
_MASK_RE = re.compile(r"⟦kw([a-z]+)⟧")
_MASK_ANY_RE = re.compile(r"⟦[^⟧]*⟧")

# تلفظ‌هایی که کاربر با گوش تأیید کرده یا در INSIGHTS به‌عنوان کلید آمده‌اند.
# None یعنی «فقط محافظت کن، شکل نوشتاری را عوض نکن».
DEFAULT_KEYWORDS: dict[str, str | None] = {
    "کوروش": None,
    "کورش": None,
    "داریوش": None,
    "خشایارشا": None,
    "خشایارشاه": None,
    "محمدرضا پهلوی": None,
    "استقرار": None,
    "اضمحلال": None,
}


def _index_to_letters(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(97 + r) + s
    return s


def _letters_to_index(s: str) -> int:
    n = 0
    for ch in s:
        n = n * 26 + (ord(ch) - 96)
    return n - 1


@dataclass
class KeywordRegistry:
    """word -> spoken form. شکل گفتاری از TTS_LEXICON / HISTORICAL_NAMES پر می‌شود."""

    spoken: dict[str, str] = field(default_factory=dict)

    @classmethod
    def default(cls, extra: dict[str, str | None] | None = None) -> "KeywordRegistry":
        reg = cls()
        for word, form in {**DEFAULT_KEYWORDS, **(extra or {})}.items():
            reg.add(word, form)
        return reg

    def add(self, word: str, spoken: str | None = None) -> None:
        form = spoken or HISTORICAL_NAMES.get(word) or TTS_LEXICON.get(word) or word
        self.spoken[word] = form
        # text_analyzer قبلاً HISTORICAL_NAMES را اعمال می‌کند (کوروش ← کورُش)،
        # پس شکل گفتاری هم باید به‌عنوان همان کلمهٔ کلیدی شناخته شود.
        self.spoken.setdefault(form, form)

    def _pattern(self) -> re.Pattern | None:
        if not self.spoken:
            return None
        keys = sorted(self.spoken, key=len, reverse=True)
        return re.compile(r"(?<!\w)(" + "|".join(re.escape(k) for k in keys) + r")(?!\w)")

    def mask(self, text: str) -> tuple[str, list[str]]:
        """متن ماسک‌شده + فهرست کلمات اصلی به ترتیب ماسک."""
        pattern = self._pattern()
        found: list[str] = []
        if pattern is None:
            return text, found

        def repl(m: re.Match) -> str:
            found.append(m.group(1))
            return f"⟦kw{_index_to_letters(len(found) - 1)}⟧"

        return pattern.sub(repl, text), found

    def unmask(self, text: str, found: list[str]) -> str:
        """ماسک‌ها را با تلفظ ثابت جایگزین می‌کند (اعراب احتمالی داخل ماسک نادیده گرفته می‌شود)."""
        text = _MASK_ANY_RE.sub(lambda m: re.sub(f"[{_MARKS}\\s]", "", m.group(0)), text)

        def repl(m: re.Match) -> str:
            i = _letters_to_index(m.group(1))
            if i >= len(found):
                raise ValueError(f"ماسک ناشناخته: {m.group(0)}")
            return self.spoken.get(found[i], found[i])

        return _MASK_RE.sub(repl, text)


def is_mask(token: str) -> bool:
    return "⟦" in token
