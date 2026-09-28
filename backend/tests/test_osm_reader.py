from pathlib import Path

import pytest

from app.rail.importer import read_rail_station_records


def test_osm_reader_preserves_named_nodes_areas_and_nested_relations(
    tmp_path: Path,
) -> None:
    path = tmp_path / "stations.osm"
    path.write_text(
        """<osm version="0.6">
      <node id="1" lat="31.0" lon="121.0"><tag k="railway" v="station"/>
      <tag k="name" v="A"/>
      <tag k="name:zh" v="甲站"/>
      <tag k="ref:cr" v="ABC"/>
      <tag k="alt_name" v="旧甲站"/>

      </node>
      <node id="2" lat="31.0" lon="121.1"><tag k="railway" v="station"/>
      <tag k="station" v="subway"/>
      <tag k="name" v="地铁站"/>

      </node>
      <node id="3" lat="31.1" lon="121.1"/>
      <node id="4" lat="31.1" lon="121.0"/>
      <way id="10"><nd ref="1"/>
      <nd ref="2"/>
      <nd ref="3"/>
      <nd ref="4"/>
      <nd ref="1"/>
      <tag k="railway" v="station"/>
      <tag k="name" v="面车站"/>
      <tag k="area" v="yes"/>

      </way>
      <way id="11"><nd ref="3"/>
      <nd ref="4"/>

      </way>
      <relation id="20"><member type="way" ref="11" role=""/>
      <tag k="type" v="site"/>

      </relation>
      <relation id="21"><member type="relation" ref="20" role=""/>
      <member type="node" ref="1" role=""/>
      <tag k="type" v="site"/>
      <tag k="railway" v="station"/>
      <tag k="name" v="关系车站"/>

      </relation>
    </osm>""",
        encoding="utf-8",
    )
    records = {
        (row.osm_type, row.osm_id): row for row in read_rail_station_records(path)
    }
    assert records.keys() == {("node", 1), ("way", 10), ("relation", 21)}
    assert records[("node", 1)].name_cn == "甲站"
    assert records[("node", 1)].station_code == "ABC"
    assert records[("node", 1)].aliases == (("旧甲站", "alternate_name"),)
    for record in records.values():
        assert 121 <= record.lon <= 121.1 and 31 <= record.lat <= 31.1
    # Match the legacy GDAL reader's identity/name contract on supported layers.
    import pyogrio

    old = {
        (row.osm_type, row.osm_id): row
        for row in read_rail_station_records(path, frame_reader=pyogrio.read_dataframe)
    }
    assert {(key, row.name_cn) for key, row in old.items()} == {
        (key, row.name_cn) for key, row in records.items()
    }


def test_incomplete_relation_is_reported_instead_of_silently_missing(
    tmp_path: Path,
) -> None:
    path = tmp_path / "incomplete.osm"
    path.write_text(
        """<osm version="0.6"><relation id="2">
      <member type="relation" ref="99" role=""/>
      <tag k="railway" v="station"/>
      <tag k="name" v="missing"/>

      </relation></osm>"""
    )
    with pytest.raises(RuntimeError, match="不存在"):
        read_rail_station_records(path)
