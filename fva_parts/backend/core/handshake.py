"""Handshake — قرارداد اجباری بین ویراستار و موتور TTS (کشف ۴).

قاعده‌ها:
  ۱. هر تنظیمات موتور یک «کد یکتا» دارد  ← engine_code()
  ۲. ویراستار متن نهایی را با همان کد امضا می‌کند  ← sign()
  ۳. موتور قبل از ساخت صدا امضا را چک می‌کند  ← verify() / @require_handshake
  ۴. نامطابق ← متن برمی‌گردد به ویراستار؛ راه دور زدن وجود ندارد  ← run()

نکته: امضا برای «سازگاری» است، نه امنیت رمزنگاری (کلید مخفی ندارد).
فقط از کتابخانهٔ استاندارد پایتون استفاده می‌کند.
"""

import functools
import hashlib
import json
import re
from dataclasses import dataclass

PROTOCOL = "fva-handshake/1"

# تنظیمات طلایی (Farid، ‎-11%‎، ‎-8Hz‎)
FARID_SETTINGS = {
    "engine": "edge",
    "voice": "fa-IR-FaridNeural",
    "rate": "-11%",
    "pitch": "-8Hz",
}

# edge_tts همهٔ تگ‌ها را escape می‌کند و بلند می‌خواند؛
# فقط <speak> و <break .../> مجازند (موتور در breakها می‌شکند).
_ANY_TAG = re.compile(r"</?\s*([A-Za-z_][\w:-]*)[^>]*>")
_ALLOWED_TAGS = {"speak", "break"}
_PLACEHOLDER = re.compile(r"<break_(short|medium|long)>")


class HandshakeError(Exception):
    """reason یکی از: not_signed, engine_mismatch, text_modified, raw_tags"""

    def __init__(self, reason: str, message: str):
        super().__init__(f"[{reason}] {message}")
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class SignedText:
    text: str
    engine_code: str
    signature: str
    editor: str = "editor"


def engine_code(settings: dict) -> str:
    """کد یکتای ۱۲ کاراکتری برای یک تنظیمات موتور (ترتیب کلیدها مهم نیست)."""
    canonical = json.dumps(settings, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(f"{PROTOCOL}|{canonical}".encode("utf-8")).hexdigest()[:12]


def _signature(text: str, code: str) -> str:
    return hashlib.sha256(f"{PROTOCOL}|{code}|{text}".encode("utf-8")).hexdigest()[:16]


def find_forbidden_tags(text: str) -> list:
    """تگ‌هایی که موتور Edge بلند می‌خواند (مثل <break_short> یا <phoneme>)."""
    bad = [m.group(0) for m in _PLACEHOLDER.finditer(text)]
    for m in _ANY_TAG.finditer(text):
        if m.group(1).lower() not in _ALLOWED_TAGS and m.group(0) not in bad:
            bad.append(m.group(0))
    return bad


def _check_tags(text: str) -> None:
    bad = find_forbidden_tags(text)
    if bad:
        raise HandshakeError("raw_tags", f"تگ‌هایی که بلند خوانده می‌شوند: {', '.join(bad[:5])}")


def sign(text: str, settings: dict, editor: str = "editor") -> SignedText:
    """ویراستار: متن آماده را برای یک تنظیمات مشخص امضا می‌کند."""
    _check_tags(text)
    code = engine_code(settings)
    return SignedText(text=text, engine_code=code, signature=_signature(text, code), editor=editor)


def verify(signed, settings: dict) -> str:
    """موتور: امضا را چک می‌کند و متن را برمی‌گرداند؛ در غیر این صورت HandshakeError."""
    if not isinstance(signed, SignedText):
        raise HandshakeError("not_signed", "متن امضا نشده؛ اول باید از ویراستار بگذرد")
    code = engine_code(settings)
    if signed.engine_code != code:
        raise HandshakeError(
            "engine_mismatch",
            f"متن برای موتور {signed.engine_code} امضا شده ولی موتور فعلی {code} است",
        )
    if signed.signature != _signature(signed.text, signed.engine_code):
        raise HandshakeError("text_modified", "متن بعد از امضای ویراستار تغییر کرده")
    _check_tags(signed.text)
    return signed.text


def require_handshake(settings: dict):
    """دکوراتور برای تابع ساخت صدا: اولین آرگومان باید SignedText باشد.

        @require_handshake(FARID_SETTINGS)
        def generate_voice(text, output_path): ...

        generate_voice(signed, "out.mp3")   # درست
        generate_voice("متن خام", "out.mp3")  # HandshakeError(not_signed)
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(signed, *args, **kwargs):
            text = verify(signed, settings)
            return func(text, *args, **kwargs)

        return wrapper

    return decorator


def run(text: str, edit, synthesize, settings: dict, max_rounds: int = 2):
    """حلقهٔ خودترمیم: ویراستار ← موتور؛ اگر موتور رد کرد، متن با دلیل برمی‌گردد.

    edit(text, feedback) -> SignedText      (feedback در دور اول None است)
    synthesize(SignedText) -> نتیجه        (خودش verify می‌کند)
    """
    feedback = None
    for _ in range(max_rounds + 1):
        signed = edit(text, feedback)
        try:
            return synthesize(signed)
        except HandshakeError as err:
            feedback = err
    raise HandshakeError(feedback.reason, f"بعد از {max_rounds} بار برگشت هنوز نامطابق: {feedback.message}")
