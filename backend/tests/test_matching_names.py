from app.matching.names import (
    normalize_city_name,
    normalize_line_name,
    normalize_station_name,
    pinyin_keys,
)


def test_normalizes_common_city_line_and_station_variants() -> None:
    assert normalize_city_name(" 上海市 ") == "上海"
    assert normalize_line_name("地铁 2 号线路") == "2号线"
    assert normalize_station_name("人民广场站") == "人民广场"


def test_builds_full_and_initial_pinyin_keys() -> None:
    assert pinyin_keys("人民广场") == ("renminguangchang", "rmgc")
