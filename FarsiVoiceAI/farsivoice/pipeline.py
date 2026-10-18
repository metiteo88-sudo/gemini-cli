"""text -> (clean) -> (optional diacritize) -> engine -> audio file."""

from .engines import get_engine
from .text import clean_text


def prepare_text(text: str, diacritize: bool = False) -> str:
    text = clean_text(text)
    if diacritize:
        from .diacritics import diacritize as _diacritize
        text = _diacritize(text)
    return text


async def text_to_voice(text: str, output_path: str, engine: str = None,
                        diacritize: bool = False, **engine_options) -> str:
    prepared = prepare_text(text, diacritize=diacritize)
    if not prepared:
        raise ValueError("متن خالی است")
    tts = get_engine(engine, **engine_options)
    return await tts.synthesize(prepared, output_path)


async def file_to_voice(input_path: str, output_path: str, **kwargs) -> str:
    with open(input_path, "r", encoding="utf-8") as f:
        text = f.read()
    return await text_to_voice(text, output_path, **kwargs)
