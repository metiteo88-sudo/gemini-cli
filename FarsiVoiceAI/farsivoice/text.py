"""Persian text preparation for TTS.

Merges the old text_cleaner.py, test_clean.py and split_text() from
book_to_voice.py into one module.
"""

import re

_EN_TO_FA_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def normalize_numbers(text: str) -> str:
    """Convert English digits to Persian digits."""
    return text.translate(_EN_TO_FA_DIGITS)


def clean_text(text: str) -> str:
    """Normalize spacing and punctuation (same rules as the old text_cleaner)."""
    # یکسان‌سازی فاصله‌های معمولی
    text = re.sub(r"[ \t]+", " ", text)

    # تبدیل سه نقطه به علامت مکث
    text = text.replace("...", "…")

    # حذف فاصله قبل از علائم نگارشی
    text = re.sub(r"\s+([،؛؟!.:])", r"\1", text)

    # افزودن فاصله بعد از علائم نگارشی
    text = re.sub(r"([،؛؟!])(?=\S)", r"\1 ", text)

    # تبدیل اعداد انگلیسی به فارسی
    text = normalize_numbers(text)

    # فاصله بعد از نقطه در صورت چسبیدن جمله بعدی
    text = re.sub(r"\.(?=\S)", ". ", text)

    # حذف فاصله‌های تکراری
    text = re.sub(r" {2,}", " ", text)

    # حذف فاصله ابتدای خطوط
    text = re.sub(r"\n[ \t]+", "\n", text)

    # حذف خطوط خالی اضافی
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()


def split_sentences(text: str) -> list[str]:
    """Split text into sentences on . ! ؟ ؛ (used by the Piper engine)."""
    text = re.sub(r"\s+", " ", text).strip()
    sentences = re.split(r"(?<=[.!؟؛…])\s+", text)
    return [s.strip() for s in sentences if s.strip()]
