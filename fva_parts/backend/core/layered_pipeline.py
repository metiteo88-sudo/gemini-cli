"""معماری نهایی هدف (INSIGHTS.md) — روی ماژول‌های موجود پروژه ساخته شده.

  لایه ۱ — ستون‌های تصمیم‌گیری
      ویراستار (پیش)  : clean_text + SmartTextEditor.clean_chars_and_ocr
      ماسک کلیدی‌ها   : core.keywords (تا ستون‌ها به آن‌ها دست نزنند)
      اعراب‌گذار ↔ واج‌آرا : core.negotiation (مذاکره روی یک ورودی، تصمیم کلمه‌به‌کلمه)
      ویراستار (نهایی): MINIMAL_DIACRITICS + امضا با کد موتور
          ↓
  [Handshake — کد اجباری]      core.handshake
          ↓
  لایه ۲ — خط لولهٔ کلمات کلیدی  (باز کردن ماسک با تلفظ ثابت)
          ↓
  prosody → build_ssml (فقط یک بار) → [TTS — Farid] → صدای نهایی

هیچ فایل موجودی تغییر نکرده؛ این ماژول فقط آن‌ها را صدا می‌زند.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from core.handshake import FARID_SETTINGS, SignedText, sign, verify
from core.keywords import KeywordRegistry
from core.lexicon import apply_minimal_diacritics
from core.negotiation import Decision, negotiate
from core.prosody import add_prosody
from core.ssml_builder import build_ssml
from core.text_cleaner import clean_text
from processors.text_analyzer import analyze_text

TITLE_TYPES = {"book_title", "part_title", "section_title"}


def _default_diacritizer() -> Callable[[str], str] | None:
    """CANINE فقط اگر transformers نصب باشد؛ وگرنه ستون اعراب‌گذار پیشنهادی نمی‌دهد."""
    try:
        import transformers  # noqa: F401
    except ImportError:
        return None
    from processors.diacritizer import diacritize
    return diacritize


def _pre_editor(text: str, convert_years: bool) -> str:
    from processors.smart_text_editor import SmartTextEditor
    text = clean_text(text, convert_years=convert_years)
    # فقط لایهٔ کاراکترها؛ fix_structure_and_zwnj نقطهٔ اعشار را می‌شکند (۲.۵ ← ۲. ۵)
    return SmartTextEditor().clean_chars_and_ocr(text)


@dataclass
class Item:
    """یک خط/پاراگراف بعد از لایه ۱."""

    type: str
    signed: SignedText | None
    keywords: list[str] = field(default_factory=list)
    report: list[Decision] = field(default_factory=list)


@dataclass
class LayeredPipeline:
    settings: dict = field(default_factory=lambda: dict(FARID_SETTINGS))
    keywords: KeywordRegistry = field(default_factory=KeywordRegistry.default)
    diacritizer: Callable[[str], str] | None = None
    use_diacritizer: bool = False
    convert_years: bool = False

    # ---------------- لایه ۱ ----------------
    def layer1(self, text: str) -> list[Item]:
        diacritize = None
        if self.use_diacritizer:
            diacritize = self.diacritizer or _default_diacritizer()

        items: list[Item] = []
        for n, raw in enumerate(analyze_text(text)):
            if raw["type"] == "blank" or not raw["text"]:
                items.append(Item(raw["type"], None))
                continue

            edited = _pre_editor(raw["text"], self.convert_years)
            masked, found = self.keywords.mask(edited)

            proposal = diacritize(masked) if (diacritize and raw["type"] == "normal_text") else None
            resolved, report = negotiate(masked, proposal, where=f"item{n}")

            final = apply_minimal_diacritics(resolved)
            items.append(Item(raw["type"], sign(final, self.settings, editor="layered_pipeline"), found, report))
        return items

    # ------- Handshake + لایه ۲ + آماده‌سازی برای موتور -------
    def to_ssml(self, item: Item) -> str | None:
        if item.signed is None:
            return None
        text = verify(item.signed, self.settings)      # Handshake: نامطابق ← HandshakeError
        text = self.keywords.unmask(text, item.keywords)  # لایه ۲
        text = add_prosody(text)
        if item.type in TITLE_TYPES:
            text = text.rstrip() + " <break_long>"
        return build_ssml(text)                          # فقط یک بار (باگ double-wrap)

    async def synthesize(self, item: Item, output_file: str, generate_voice=None) -> str | None:
        ssml = self.to_ssml(item)
        if ssml is None:
            return None
        if generate_voice is None:
            from engines.edge_engine import generate_voice
        s = self.settings
        await generate_voice(ssml, output_file, voice=s["voice"], rate=s["rate"], pitch=s["pitch"], is_ssml=True)
        return output_file


def report_rows(items: list[Item]) -> list[dict]:
    """گزارش همهٔ تصمیم‌های مذاکره (برای بازبینی دستی)."""
    return [d.to_dict() for it in items for d in it.report]
