"""Command line:  python -m farsivoice book.txt [-o out.mp3] [--engine auto]"""

import argparse
import asyncio
import os
import sys

from . import config
from .engines import EngineError
from .pipeline import file_to_voice


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="farsivoice", description="تبدیل فایل متنی فارسی به صدا")
    p.add_argument("input", help="فایل متنی ورودی (UTF-8)")
    p.add_argument("-o", "--output", help="فایل خروجی (پیش‌فرض: نام ورودی با پسوند mp3 یا wav)")
    p.add_argument("-e", "--engine", default=config.DEFAULT_ENGINE, choices=["edge", "piper", "auto"],
                   help="موتور صدا (پیش‌فرض: %(default)s)")
    p.add_argument("--voice", help=f"صدای Edge (پیش‌فرض: {config.EDGE_VOICE})")
    p.add_argument("--rate", help=f"سرعت Edge (پیش‌فرض: {config.EDGE_RATE})".replace("%", "%%"))
    p.add_argument("--pitch", help=f"زیروبمی Edge (پیش‌فرض: {config.EDGE_PITCH})")
    p.add_argument("--model", help=f"مدل Piper (پیش‌فرض: {config.PIPER_MODEL})")
    p.add_argument("--pause", type=float, dest="sentence_pause",
                   help=f"مکث بین جمله‌ها در Piper به ثانیه (پیش‌فرض: {config.SENTENCE_PAUSE})")
    p.add_argument("--diacritize", action="store_true", help="اعراب‌گذاری خودکار قبل از خواندن (نیاز به transformers)")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)

    if not os.path.isfile(args.input):
        print(f"❌ فایل پیدا نشد: {args.input}")
        return 1

    output = args.output
    if not output:
        ext = ".wav" if args.engine == "piper" else ".mp3"
        output = os.path.splitext(args.input)[0] + ext

    print(f"🎙️ در حال ساخت صدا با موتور {args.engine} ...")
    try:
        asyncio.run(file_to_voice(
            args.input, output,
            engine=args.engine, diacritize=args.diacritize,
            voice=args.voice, rate=args.rate, pitch=args.pitch,
            model=args.model, sentence_pause=args.sentence_pause,
        ))
    except (EngineError, ValueError, RuntimeError) as exc:
        print(f"❌ {exc}")
        return 1

    print(f"✅ تمام شد: {output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
