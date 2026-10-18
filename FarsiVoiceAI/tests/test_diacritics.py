from farsivoice.diacritics import postprocess_diacritics


def test_removes_repeated_marks():
    assert postprocess_diacritics("مَََرد") == "مَرد"


def test_removes_trailing_sukun():
    assert postprocess_diacritics("مردْ رفتْ.") == "مرد رفت."


def test_fixes_contradictory_kaf():
    assert postprocess_diacritics("کُِتاب") == "کِتاب"
