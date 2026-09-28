from __future__ import annotations

from sqlalchemy import Connection


def ensure_search_indexes(connection: Connection) -> None:
    """Create SQLite FTS5/RTree indexes and synchronization triggers."""

    if connection.dialect.name != "sqlite":
        return
    statements = (
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS station_fts USING fts5(
          station_id UNINDEXED, city_id UNINDEXED, name_cn, name_en,
          pinyin_full, pinyin_initials, aliases, tokenize='unicode61'
        )
        """,
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS rail_station_fts USING fts5(
          station_id UNINDEXED, rail_dataset_version_id UNINDEXED,
          province_name UNINDEXED, city_name UNINDEXED, name_cn, name_en,
          pinyin_full, pinyin_initials, station_code, aliases,
          tokenize='unicode61'
        )
        """,
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS station_spatial USING rtree(
          id, min_lon, max_lon, min_lat, max_lat
        )
        """,
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS route_edge_spatial USING rtree(
          id, min_lon, max_lon, min_lat, max_lat
        )
        """,
        """
        CREATE TRIGGER IF NOT EXISTS station_fts_insert AFTER INSERT ON station BEGIN
          INSERT INTO station_fts(
            rowid, station_id, city_id, name_cn, name_en,
            pinyin_full, pinyin_initials, aliases
          ) VALUES (
            new.id, new.id, new.city_id, new.name_cn, coalesce(new.name_en, ''),
            coalesce(new.pinyin_full, ''), coalesce(new.pinyin_initials, ''), ''
          );
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS station_fts_update AFTER UPDATE ON station BEGIN
          UPDATE station_fts SET
            city_id=new.city_id, name_cn=new.name_cn, name_en=coalesce(new.name_en, ''),
            pinyin_full=coalesce(new.pinyin_full, ''),
            pinyin_initials=coalesce(new.pinyin_initials, '')
          WHERE rowid=new.id;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS station_fts_delete AFTER DELETE ON station BEGIN
          DELETE FROM station_fts WHERE rowid=old.id;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS station_alias_fts_insert
        AFTER INSERT ON station_alias BEGIN
          UPDATE station_fts SET aliases=(
            SELECT coalesce(group_concat(alias, ' '), '')
            FROM station_alias WHERE station_id=new.station_id
          ) WHERE rowid=new.station_id;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS station_alias_fts_update
        AFTER UPDATE ON station_alias BEGIN
          UPDATE station_fts SET aliases=(
            SELECT coalesce(group_concat(alias, ' '), '')
            FROM station_alias WHERE station_id=old.station_id
          ) WHERE rowid=old.station_id;
          UPDATE station_fts SET aliases=(
            SELECT coalesce(group_concat(alias, ' '), '')
            FROM station_alias WHERE station_id=new.station_id
          ) WHERE rowid=new.station_id;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS station_alias_fts_delete
        AFTER DELETE ON station_alias BEGIN
          UPDATE station_fts SET aliases=(
            SELECT coalesce(group_concat(alias, ' '), '')
            FROM station_alias WHERE station_id=old.station_id
          ) WHERE rowid=old.station_id;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS rail_station_fts_insert
        AFTER INSERT ON rail_station BEGIN
          INSERT INTO rail_station_fts(
            rowid, station_id, rail_dataset_version_id, province_name, city_name,
            name_cn, name_en, pinyin_full, pinyin_initials, station_code, aliases
          ) VALUES (
            new.id, new.id, new.rail_dataset_version_id,
            coalesce(new.province_name, ''), coalesce(new.city_name, ''),
            new.name_cn, coalesce(new.name_en, ''), coalesce(new.pinyin_full, ''),
            coalesce(new.pinyin_initials, ''), coalesce(new.station_code, ''), ''
          );
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS rail_station_fts_update
        AFTER UPDATE ON rail_station BEGIN
          UPDATE rail_station_fts SET
            rail_dataset_version_id=new.rail_dataset_version_id,
            province_name=coalesce(new.province_name, ''),
            city_name=coalesce(new.city_name, ''), name_cn=new.name_cn,
            name_en=coalesce(new.name_en, ''),
            pinyin_full=coalesce(new.pinyin_full, ''),
            pinyin_initials=coalesce(new.pinyin_initials, ''),
            station_code=coalesce(new.station_code, '')
          WHERE rowid=new.id;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS rail_station_fts_delete
        AFTER DELETE ON rail_station BEGIN
          DELETE FROM rail_station_fts WHERE rowid=old.id;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS rail_station_alias_fts_insert
        AFTER INSERT ON rail_station_alias BEGIN
          UPDATE rail_station_fts SET aliases=(
            SELECT coalesce(group_concat(alias, ' '), '')
            FROM rail_station_alias WHERE station_id=new.station_id
          ) WHERE rowid=new.station_id;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS rail_station_alias_fts_update
        AFTER UPDATE ON rail_station_alias BEGIN
          UPDATE rail_station_fts SET aliases=(
            SELECT coalesce(group_concat(alias, ' '), '')
            FROM rail_station_alias WHERE station_id=old.station_id
          ) WHERE rowid=old.station_id;
          UPDATE rail_station_fts SET aliases=(
            SELECT coalesce(group_concat(alias, ' '), '')
            FROM rail_station_alias WHERE station_id=new.station_id
          ) WHERE rowid=new.station_id;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS rail_station_alias_fts_delete
        AFTER DELETE ON rail_station_alias BEGIN
          UPDATE rail_station_fts SET aliases=(
            SELECT coalesce(group_concat(alias, ' '), '')
            FROM rail_station_alias WHERE station_id=old.station_id
          ) WHERE rowid=old.station_id;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS station_spatial_insert
        AFTER INSERT ON station BEGIN
          INSERT INTO station_spatial
          VALUES(new.id, new.lon, new.lon, new.lat, new.lat);
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS station_spatial_update
        AFTER UPDATE OF lon, lat ON station BEGIN
          UPDATE station_spatial SET
            min_lon=new.lon, max_lon=new.lon, min_lat=new.lat, max_lat=new.lat
          WHERE id=new.id;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS station_spatial_delete
        AFTER DELETE ON station BEGIN
          DELETE FROM station_spatial WHERE id=old.id;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS route_edge_spatial_insert
        AFTER INSERT ON route_edge BEGIN
          INSERT INTO route_edge_spatial VALUES(
            new.id, new.min_lon, new.max_lon, new.min_lat, new.max_lat
          );
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS route_edge_spatial_update
        AFTER UPDATE OF min_lon, max_lon, min_lat, max_lat ON route_edge BEGIN
          UPDATE route_edge_spatial SET
            min_lon=new.min_lon, max_lon=new.max_lon,
            min_lat=new.min_lat, max_lat=new.max_lat
          WHERE id=new.id;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS route_edge_spatial_delete
        AFTER DELETE ON route_edge BEGIN
          DELETE FROM route_edge_spatial WHERE id=old.id;
        END
        """,
    )
    has_rail_station = connection.exec_driver_sql(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='rail_station'"
    ).first()
    for statement in statements:
        if has_rail_station is None and "rail_station" in statement:
            continue
        connection.exec_driver_sql(statement)

    connection.exec_driver_sql(
        """
        INSERT OR REPLACE INTO station_fts(
          rowid, station_id, city_id, name_cn, name_en,
          pinyin_full, pinyin_initials, aliases
        )
        SELECT s.id, s.id, s.city_id, s.name_cn, coalesce(s.name_en, ''),
               coalesce(s.pinyin_full, ''), coalesce(s.pinyin_initials, ''),
               coalesce((SELECT group_concat(a.alias, ' ') FROM station_alias a
                         WHERE a.station_id=s.id), '')
        FROM station s
        """
    )
    if has_rail_station is not None:
        connection.exec_driver_sql(
            """
            INSERT OR REPLACE INTO rail_station_fts(
              rowid, station_id, rail_dataset_version_id, province_name, city_name,
              name_cn, name_en, pinyin_full, pinyin_initials, station_code, aliases
            )
            SELECT s.id, s.id, s.rail_dataset_version_id,
                   coalesce(s.province_name, ''), coalesce(s.city_name, ''),
                   s.name_cn, coalesce(s.name_en, ''), coalesce(s.pinyin_full, ''),
                   coalesce(s.pinyin_initials, ''), coalesce(s.station_code, ''),
                   coalesce((SELECT group_concat(a.alias, ' ')
                             FROM rail_station_alias a WHERE a.station_id=s.id), '')
            FROM rail_station s
            """
        )
    connection.exec_driver_sql(
        """
        INSERT OR REPLACE INTO station_spatial(id, min_lon, max_lon, min_lat, max_lat)
        SELECT id, lon, lon, lat, lat FROM station
        """
    )
    connection.exec_driver_sql(
        """
        INSERT OR REPLACE INTO route_edge_spatial(
          id, min_lon, max_lon, min_lat, max_lat
        )
        SELECT id, min_lon, max_lon, min_lat, max_lat FROM route_edge
        """
    )
