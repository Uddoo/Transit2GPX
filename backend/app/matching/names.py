from __future__ import annotations

import re
import unicodedata

from pypinyin import Style, lazy_pinyin

_SEPARATORS = re.compile(r"[\s\-_·•./\\]+")
_PUNCTUATION = re.compile(r"[()（）\[\]【】{}<>《》,，;；:：'\"]+")


def normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized = _SEPARATORS.sub("", normalized)
    return _PUNCTUATION.sub("", normalized)


def normalize_city_name(value: str) -> str:
    normalized = normalize_name(value)
    for suffix in ("特别行政区", "自治州", "地区", "盟", "市"):
        if normalized.endswith(suffix):
            return normalized[: -len(suffix)]
    return normalized


def normalize_station_name(value: str) -> str:
    normalized = normalize_name(value)
    return normalized[:-1] if normalized.endswith("站") else normalized


def normalize_line_name(value: str) -> str:
    normalized = normalize_name(value).replace("地铁", "")
    if normalized.endswith("线路"):
        normalized = normalized[:-2] + "线"
    return normalized


def pinyin_keys(value: str) -> tuple[str, str]:
    syllables = lazy_pinyin(value, style=Style.NORMAL, errors="ignore")
    initials = lazy_pinyin(value, style=Style.FIRST_LETTER, errors="ignore")
    return "".join(syllables).casefold(), "".join(initials).casefold()
