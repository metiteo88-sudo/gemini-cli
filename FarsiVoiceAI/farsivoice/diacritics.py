"""Optional Persian diacritization (اعراب‌گذاری).

Merges test_diacritizer.py (model inference) and diacritizer_postprocess.py,
which were never connected to each other or to the pipeline before.

The model needs `transformers` + `torch` (see requirements-diacritizer.txt).
They are imported lazily, so the rest of the project works without them.
"""

import re

MODEL_NAME = "PedramR/canine-fa-diacritizer"

MARKS = {
    "FATHA": "َ",
    "DAMMA": "ُ",
    "KASRA": "ِ",
    "SOKUN": "ْ",
    "SHADDA": "ّ",
    "SHADDA_FATHA": "َّ",
    "SHADDA_DAMMA": "ُّ",
    "SHADDA_KASRA": "ِّ",
    "FATHATAN": "ً",
}

_model = None
_tokenizer = None


def postprocess_diacritics(text: str) -> str:
    """Clean CANINE Persian diacritization output for TTS."""
    # حذف اعراب تکراری
    text = re.sub(r"([ًٌٍَُِّْ])\1+", r"\1", text)

    # حذف ترکیب متناقض ضمه+کسره روی «ک»
    text = text.replace("کُِ", "کِ")

    # حذف سکون در انتهای کلمات
    text = re.sub(r"ْ(?=\s|[.!؟،,:؛]|$)", "", text)

    # حذف فاصله‌های اضافی
    text = re.sub(r"\s+", " ", text).strip()

    return text


def _load():
    global _model, _tokenizer
    if _model is None:
        try:
            from transformers import CanineForTokenClassification, CanineTokenizer
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "برای اعراب‌گذاری باید نصب کنید: pip install -r requirements-diacritizer.txt"
            ) from exc
        _tokenizer = CanineTokenizer.from_pretrained(MODEL_NAME)
        _model = CanineForTokenClassification.from_pretrained(MODEL_NAME).eval()
    return _tokenizer, _model


def diacritize_line(text: str) -> str:
    tokenizer, model = _load()
    enc = tokenizer(text, return_tensors="pt", truncation=True, max_length=2048)
    preds = model(**enc).logits.argmax(-1)[0].tolist()
    id2label = model.config.id2label
    char_preds = preds[1:1 + len(text)]

    out = []
    for ch, pid in zip(text, char_preds):
        out.append(ch)
        out.append(MARKS.get(id2label[pid], ""))
    return postprocess_diacritics("".join(out))


def diacritize(text: str) -> str:
    """Diacritize text line by line (keeps paragraph breaks)."""
    return "\n".join(diacritize_line(line) if line.strip() else line for line in text.split("\n"))


if __name__ == "__main__":
    samples = [
        "مرد از خانه بیرون رفت.",
        "او مُرد و همه ناراحت شدند.",
        "شیر در جنگل زندگی می‌کند.",
        "شیر را در لیوان ریخت.",
        "کشاورز زمین را کِشت کرد.",
        "او دشمن خود را کُشت.",
    ]
    for s in samples:
        print("INPUT :", s)
        print("OUTPUT:", diacritize_line(s))
        print()
