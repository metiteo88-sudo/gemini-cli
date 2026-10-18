# FarsiVoiceAI 🎙️

تبدیل فایل متنی فارسی به صدای طبیعی — روی ترموکس، اوبونتو و ویندوز/لینوکس.
**بدون هیچ وابستگی به Gemini.**

| موتور | نیاز به اینترنت | کیفیت | توضیح |
|---|---|---|---|
| `edge` (پیش‌فرض) | ✅ | عالی | صدای `fa-IR-FaridNeural`، سرعت `-11%`، زیروبمی `-8Hz` (همان تنظیمات طلایی قبلی) |
| `piper` | ❌ آفلاین | خوب | مدل `fa_IR-gyro-medium`، جمله‌به‌جمله با ۰٫۶ ثانیه مکث |
| `auto` | — | — | اول Edge؛ اگر قطع/مسدود بود خودکار Piper |

## نصب (ترموکس یا اوبونتو)

```bash
pkg install python ffmpeg git        # در اوبونتو: apt install python3-pip ffmpeg git
git clone https://github.com/mahditouri20-crypto/FarsiVoiceAI
cd FarsiVoiceAI
pip install -r requirements.txt

# اختیاری — موتور آفلاین:
pip install piper-tts
python -m piper.download_voices fa_IR-gyro-medium
```

## استفاده

```bash
python -m farsivoice examples/book.txt                 # → examples/book.mp3
python -m farsivoice book.txt -o kitab.mp3 --engine auto
python -m farsivoice book.txt --engine piper --pause 0.8
python -m farsivoice book.txt --rate -5% --pitch -4Hz
python -m farsivoice --help
```

همهٔ تنظیمات در `farsivoice/config.py` هستند و با متغیر محیطی هم قابل تغییرند،
مثلاً `FARSIVOICE_ENGINE=auto`.

## سرور API (اختیاری)

```bash
pip install -r requirements-api.txt
uvicorn farsivoice.api:app --host 0.0.0.0 --port 8000
```

| مسیر | کار |
|---|---|
| `POST /text` | `{"text": "...", "engine": "auto"}` → ساخت صدا |
| `POST /file` | آپلود فایل متنی UTF-8 → ساخت صدا |
| `GET /audio/{name}` | دانلود فایل صوتی ساخته‌شده |

## اعراب‌گذاری خودکار (اختیاری، آزمایشی)

```bash
pip install -r requirements-diacritizer.txt     # حجیم (torch)
python -m farsivoice book.txt --diacritize
python -m farsivoice.diacritics                 # نمایش نمونه‌ها
```

## ساختار

```
farsivoice/
  config.py      تنظیمات (یک‌جا)
  text.py        پاک‌سازی متن، اعداد فارسی، تقسیم جمله
  diacritics.py  اعراب‌گذاری + پس‌پردازش
  engines.py     موتورهای edge / piper / auto
  pipeline.py    متن → صدا
  cli.py         خط فرمان
  api.py         سرور HTTP
tests/           تست‌ها (pytest)
examples/        نمونهٔ ورودی
```

## نقشهٔ فایل‌های قدیمی → جدید

| قدیمی (`backend/`) | وضعیت |
|---|---|
| `edge_audiobook.py` + ۸ کپی (`_golden`, `_backup`, `_backup2`, `_test`, `_before_natural`, `_natural_backup`, `_paragraph_test`, `edge_book.py`) | یکی شدند → `engines.EdgeEngine` (تفاوتشان فقط `RATE` و نام خروجی بود؛ حالا `--rate` و `-o`) |
| `piper_engine.py` + `book_to_voice.py` | → `engines.PiperEngine` |
| `text_cleaner.py` + `test_clean.py` (نسخهٔ قدیمی) | → `text.py` |
| `test_diacritizer.py` + `diacritizer_postprocess.py` (هیچ‌جا وصل نبودند) | → `diacritics.py` و گزینهٔ `--diacritize` |
| `main.py` | → `api.py` (به‌علاوهٔ دانلود فایل و آپلود متن) |
| `prosody.py` + `voice_pipeline.py` | **حذف شدند** — تگ‌هایی مثل `<break_short>` می‌ساختند که هیچ موتوری نمی‌فهمد؛ مکث‌ها حالا در موتور Piper واقعاً اعمال می‌شوند |
| `book.txt`, `audiobook_parts/` | → `examples/book.txt` |
| `.github/workflows/python-package-conda.yml` | → `tests.yml` (قبلی به `environment.yml` ناموجود نیاز داشت و همیشه شکست می‌خورد) |

## تست

```bash
pip install pytest && pytest -q
```
