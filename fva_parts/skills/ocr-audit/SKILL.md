# ocr-audit
بازرسی مرحلهٔ «اسکن → متن خام» (و هر مرحلهٔ متنی بعدی) با عدد واقعی، نه حدس.
جایگزین پیشرفتهٔ ocr-pipeline-mapper.md و مکمل ocr-cleanup.
ابزار: `.skills/ocr-audit/ocr_audit.py` (فقط کتابخانهٔ استاندارد پایتون؛ در Termux بدون نصب اجرا می‌شود).

## قانون‌ها
1. فقط‌خواندنی است. هیچ ورودی را تغییر نمی‌دهد؛ اگر --out برابر ورودی باشد، اجرا متوقف می‌شود.
2. گزارش‌ها .txt هستند و در `backend/work/ocr_audit/` ذخیره می‌شوند.
3. به golden/ دست نزن. فقط آن را بخوان.
4. مرجع (ref) «بهترین متن موجود» است، نه حقیقت. FINAL هم با زنجیرهٔ خودکار (cleaner + postfix + LLM) ساخته شده
   و هنوز خطای OCR دارد (مثلاً «آشها» به‌جای «آنها»). اختلاف یعنی «یک انسان نگاه کند»، نه «خودکار اصلاح کن».
5. هیچ قاعده‌ای بدون اجرای `rules` روی دادهٔ واقعی و تأیید کاربر وارد کد نمی‌شود.
6. دستورها را یکی‌یکی بده و منتظر خروجی بمان.

## ترتیب کار (همیشه از backend)
`cd ~/FarsiVoiceAI/backend`

۱) نقشه: کدام فایل OCR واقعاً در مسیر تولید است، کدام یتیم است، کدام مسیرش خراب است.
`python3 ../.skills/ocr-audit/ocr_audit.py map --extra ../extract-book-standalone`
- PROD = از main/fva/fva_agents/pipeline قابل دسترسی است (زنجیره در via: آمده).
- SCRIPT = جدا اجرا می‌شود. ORPHAN = هیچ‌کدام. TEST = تست.
- +BROKEN = خطای نحوی دارد، یا مسیری مثل tests/golden/... که دیگر وجود ندارد.

۲) کیفیت: متن خام OCR در برابر مرجع، صفحه‌به‌صفحه (هر دو فایل باید [[page N]] داشته باشند).
`python3 ../.skills/ocr-audit/ocr_audit.py quality manual_scripts/golden/main_content_raw.txt manual_scripts/golden/FINAL/main_content_cleaned.txt`
- WER و CER تقریبی، به‌همراه دسته‌بندی خطا:
  - glued: واژه‌های چسبیده (درسال در برابر «در سال»)
  - split: واژهٔ شکسته (کشا ورزی)
  - zwnj: فرق فقط در نیم‌فاصله
  - char_insert_delete: حرف اضافه یا جاافتاده، مثل «س» اضافهٔ tesseract (ایسران)
  - char_substitution: جابه‌جایی حرف (ابران، اقتمادی)
  - glued_and_chars و split_and_chars: هم فاصله و هم حرف
  - arabic_letter_form: ي/ك عربی
  - missing_text و extra_text: متن جاافتاده یا اضافه
- «top character confusions» نشان می‌دهد OCR کدام حرف را با کدام اشتباه می‌گیرد.
- «rule candidates» قاعده‌های پیشنهادی است با ستون collide:
  - collide = چند بار همان شکل غلط در مرجع به‌عنوان واژهٔ درست آمده است.
  - collide بزرگ‌تر از صفر یعنی RISKY: قاعدهٔ کور متن سالم را خراب می‌کند (درس ماجرای «رزندم» و «بدرم»).
- با `--apply core.text_cleaner:clean_text` می‌توان خروجی یک تمیزکننده را هم سنجید.

۳) سهم هر مرحله: تمیزکننده چه چیزی را درست کرد و چه چیزی را خراب کرد؟
`python3 ../.skills/ocr-audit/ocr_audit.py stage manual_scripts/golden/main_content_raw.txt manual_scripts/golden/FINAL/main_content_cleaned.txt --apply core.text_cleaner:clean_text`
- «BROKEN by cleaner» = واژه‌ای که در متن خام با مرجع یکی بود و بعد از تمیزکاری دیگر نیست.
- فهرست regressions را یکی‌یکی نگاه کن: گاهی تمیزکننده درست می‌گوید و مرجع غلط است (مثلاً «بدرم» در FINAL).

۴) سنجش قاعده‌ها، قبل از اعتماد:
`python3 ../.skills/ocr-audit/ocr_audit.py rules manual_scripts/golden/main_content_raw.txt manual_scripts/golden/FINAL/main_content_cleaned.txt --table processors.ocr_normalizer:OCR_SPACING_RULES --mode token`
- هر قاعده جداگانه اجرا می‌شود و برای هر کدام شمرده می‌شود: چند صفحه بهتر شد (helped)، چند صفحه بدتر شد (hurt)، و delta.
- برای جدول‌هایی که جایگزینی رشته‌ای انجام می‌دهند (مثل `core.text_cleaner:_OCR_JOINED_FIXES`) از `--mode substring` استفاده کن.
- معنی verdictها:
  - good یا good~: کمک می‌کند.
  - HARMFUL: خراب می‌کند و مرجع هم شکل منبع را ندارد؛ پیشنهاد حذف، با تأیید کاربر.
  - REF-KEEPS-SRC: مرجع خودش شکل منبع را دارد؛ آزمون نمی‌تواند داوری کند و انسان تصمیم می‌گیرد.
  - unused: در این کتاب هیچ اثری ندارد.

## گزینه‌های کلی (قبل از نام فرمان)
`--out مسیر.txt`، `--top 40`، `--root .`
نمونه: `python3 ../.skills/ocr-audit/ocr_audit.py --top 40 quality A.txt B.txt --min-count 5`

## گزارش به کاربر (کوتاه)
مکان (گوشی، بکاپ یا ابر)، فرمان، سه عدد اصلی، سه نمونه، و یک پیشنهاد که با `rules` سنجیده شده باشد. سپس منتظر تأیید بمان.

## محدودیت‌های شناخته‌شده
- WER و CER از هم‌ترازی difflib است، نه Levenshtein کامل؛ برای مقایسهٔ نسبی (قبل و بعد) دقیق است.
- اگر صفحه‌بندی دو فایل فرق کند، فقط صفحه‌های مشترک مقایسه می‌شوند (تعدادشان در گزارش آمده).
- تشخیص مسیر خراب در map ایستا است: مسیرهایی که در زمان اجرا ساخته می‌شوند دیده نمی‌شوند.
- تست‌ها: `python3 -m pytest tests/test_ocr_audit.py -q`
