from __future__ import annotations

from datetime import date

from app.providers import CSV_TIMETABLE_PROVIDER, MANUAL_TIMETABLE_PROVIDER


def test_manual_and_csv_timetable_providers_normalize_user_facts() -> None:
    for provider, expected_name in (
        (MANUAL_TIMETABLE_PROVIDER, "manual"),
        (CSV_TIMETABLE_PROVIDER, "csv"),
    ):
        facts = provider.create_facts(
            travel_date=date(2026, 8, 20),
            train_no=" g123 ",
            train_type="G",
            start_station_id=1,
            end_station_id=3,
            via_station_ids=[2],
            route_hint=" 沪昆高速铁路 ",
        )

        assert facts.train_no == "G123"
        assert facts.route_hint == "沪昆高速铁路"
        assert facts.via_station_ids == (2,)
        assert facts.timetable_provider == expected_name
