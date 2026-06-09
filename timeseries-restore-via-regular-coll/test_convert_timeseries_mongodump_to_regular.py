# test_convert_timeseries_mongodump_to_regular.py
#
# Unit / integration tests for convert-timeseries-mongodump-to-regular.py.
#
# Usage:
#   pip install pytest
#   pytest test_convert_timeseries_mongodump_to_regular.py -v

import gzip
import json
import pytest
from pathlib import Path

from convert_timeseries_mongodump_to_regular import (
    rewrite_dump,
    main,
    _format_create_collection,
    _decode_extended_json,
)

# ---------------------------------------------------------------------------
# Helpers and fixtures
# ---------------------------------------------------------------------------

SAMPLE_BSON = b"\x05\x00\x00\x00\x00"  # one empty BSON document

SAMPLE_META = {
    "options": {
        "timeseries": {
            "timeField": "t",
            "metaField": "host",
            "granularity": "seconds",
            "bucketMaxSpanSeconds": 3600,
            "bucketRoundingSeconds": 3600,
        }
    },
    "indexes": [
        {"v": 2, "key": {"_id": 1}, "name": "_id_", "ns": "mydb.weather"}
    ],
    "uuid": "deadbeef",
    "collectionName": "weather",
    "type": "timeseries",
}

# Mirrors the Extended JSON format that mongodump actually writes to disk.
SAMPLE_META_EXTJSON = {
    "options": {
        "timeseries": {
            "timeField": "t",
            "metaField": "location",
            "bucketMaxSpanSeconds": {"$numberInt": "3600"},
            "bucketRoundingSeconds": {"$numberInt": "3600"},
        }
    },
    "indexes": [
        {"v": {"$numberInt": "2"}, "key": {"location": {"$numberInt": "1"}, "t": {"$numberInt": "1"}},
         "name": "location_1_t_1"},
    ],
    "collectionName": "weather",
    "type": "timeseries",
}


@pytest.fixture()
def dump_db(tmp_path):
    """Returns (dump_root, db_dir) with the mydb sub-directory already created."""
    db_dir = tmp_path / "dump" / "mydb"
    db_dir.mkdir(parents=True)
    return tmp_path / "dump", db_dir


def write_plain(db_dir, ts_coll, meta=None, bson_data=None):
    bson_path = db_dir / f"system.buckets.{ts_coll}.bson"
    meta_path = db_dir / f"{ts_coll}.metadata.json"
    bson_path.write_bytes(bson_data or SAMPLE_BSON)
    meta_path.write_text(json.dumps(meta or SAMPLE_META), encoding="utf-8")
    return bson_path, meta_path


def write_gz(db_dir, ts_coll, meta=None, bson_data=None):
    bson_path = db_dir / f"system.buckets.{ts_coll}.bson.gz"
    meta_path = db_dir / f"{ts_coll}.metadata.json.gz"
    with gzip.open(bson_path, "wb") as f:
        f.write(bson_data or SAMPLE_BSON)
    with gzip.open(meta_path, "wt", encoding="utf-8") as f:
        json.dump(meta or SAMPLE_META, f)
    return bson_path, meta_path


def read_dst_meta(db_dir, dst_coll):
    plain = db_dir / f"{dst_coll}.metadata.json"
    gz    = db_dir / f"{dst_coll}.metadata.json.gz"
    if plain.exists():
        return json.loads(plain.read_text(encoding="utf-8"))
    with gzip.open(gz, "rt", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# TEST: happy path — plain files
# ---------------------------------------------------------------------------

class TestPlainFiles:
    def test_bson_file_created(self, dump_db):
        dump, db = dump_db
        write_plain(db, "weather")
        rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        assert (db / "weather_buckets.bson").exists()

    def test_bson_content_copied(self, dump_db):
        dump, db = dump_db
        write_plain(db, "weather", bson_data=b"\x01\x02\x03")
        rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        assert (db / "weather_buckets.bson").read_bytes() == b"\x01\x02\x03"

    def test_metadata_file_created(self, dump_db):
        dump, db = dump_db
        write_plain(db, "weather")
        rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        assert (db / "weather_buckets.metadata.json").exists()

    def test_timeseries_option_stripped(self, dump_db):
        dump, db = dump_db
        write_plain(db, "weather")
        rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        meta = read_dst_meta(db, "weather_buckets")
        assert "timeseries" not in meta["options"]

    def test_type_field_stripped(self, dump_db):
        dump, db = dump_db
        write_plain(db, "weather")
        rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        meta = read_dst_meta(db, "weather_buckets")
        assert "type" not in meta

    def test_collection_name_updated(self, dump_db):
        dump, db = dump_db
        write_plain(db, "weather")
        rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        meta = read_dst_meta(db, "weather_buckets")
        assert meta["collectionName"] == "weather_buckets"

    def test_index_namespace_updated(self, dump_db):
        dump, db = dump_db
        write_plain(db, "weather")
        rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        meta = read_dst_meta(db, "weather_buckets")
        for idx in meta["indexes"]:
            if "ns" in idx:
                assert idx["ns"] == "mydb.weather_buckets"

    def test_options_key_present_after_strip(self, dump_db):
        """options dict must remain even if empty after stripping timeseries fields."""
        dump, db = dump_db
        write_plain(db, "weather", meta={**SAMPLE_META, "options": {"timeseries": {}}})
        rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        meta = read_dst_meta(db, "weather_buckets")
        assert "options" in meta
        assert meta["options"] == {}

    def test_viewon_and_pipeline_stripped(self, dump_db):
        dump, db = dump_db
        meta = {**SAMPLE_META, "options": {"viewOn": "other", "pipeline": [{"$match": {}}]}}
        write_plain(db, "weather", meta=meta)
        rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        result = read_dst_meta(db, "weather_buckets")
        assert "viewOn"   not in result["options"]
        assert "pipeline" not in result["options"]

    def test_unrelated_metadata_fields_preserved(self, dump_db):
        dump, db = dump_db
        write_plain(db, "weather")
        rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        meta = read_dst_meta(db, "weather_buckets")
        assert meta["uuid"] == "deadbeef"


# ---------------------------------------------------------------------------
# TEST: happy path — gzip files
# ---------------------------------------------------------------------------

class TestGzipFiles:
    def test_gz_bson_copied(self, dump_db):
        dump, db = dump_db
        write_gz(db, "weather")
        rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        dst = db / "weather_buckets.bson.gz"
        assert dst.exists()
        with gzip.open(dst, "rb") as f:
            assert f.read() == SAMPLE_BSON

    def test_gz_metadata_file_created(self, dump_db):
        dump, db = dump_db
        write_gz(db, "weather")
        rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        assert (db / "weather_buckets.metadata.json.gz").exists()

    def test_gz_timeseries_option_stripped(self, dump_db):
        dump, db = dump_db
        write_gz(db, "weather")
        rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        meta = read_dst_meta(db, "weather_buckets")
        assert "timeseries" not in meta["options"]

    def test_gz_collection_name_updated(self, dump_db):
        dump, db = dump_db
        write_gz(db, "weather")
        rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        meta = read_dst_meta(db, "weather_buckets")
        assert meta["collectionName"] == "weather_buckets"

    def test_gz_no_plain_files_created(self, dump_db):
        """When source is gzip, output should also be gzip — no plain files."""
        dump, db = dump_db
        write_gz(db, "weather")
        rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        assert not (db / "weather_buckets.bson").exists()
        assert not (db / "weather_buckets.metadata.json").exists()


# ---------------------------------------------------------------------------
# TEST: collision detection and --overwrite
# ---------------------------------------------------------------------------

class TestCollisionDetection:
    def test_raises_when_dst_bson_exists(self, dump_db):
        dump, db = dump_db
        write_plain(db, "weather")
        (db / "weather_buckets.bson").write_bytes(b"existing")
        with pytest.raises(FileExistsError, match="weather_buckets.bson"):
            rewrite_dump(dump, "mydb", "weather", "weather_buckets")

    def test_raises_when_dst_meta_exists(self, dump_db):
        dump, db = dump_db
        write_plain(db, "weather")
        (db / "weather_buckets.metadata.json").write_text("{}", encoding="utf-8")
        with pytest.raises(FileExistsError, match="weather_buckets.metadata.json"):
            rewrite_dump(dump, "mydb", "weather", "weather_buckets")

    def test_existing_bson_not_modified_on_collision(self, dump_db):
        """Collision check must fire before any files are written."""
        dump, db = dump_db
        write_plain(db, "weather")
        (db / "weather_buckets.bson").write_bytes(b"original")
        with pytest.raises(FileExistsError):
            rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        assert (db / "weather_buckets.bson").read_bytes() == b"original"

    def test_overwrite_flag_allows_replacement(self, dump_db):
        dump, db = dump_db
        write_plain(db, "weather")
        (db / "weather_buckets.bson").write_bytes(b"stale")
        rewrite_dump(dump, "mydb", "weather", "weather_buckets", overwrite=True)
        assert (db / "weather_buckets.bson").read_bytes() == SAMPLE_BSON


# ---------------------------------------------------------------------------
# TEST: write ordering — metadata parsed before BSON is written
# ---------------------------------------------------------------------------

class TestWriteOrdering:
    def test_bad_metadata_json_leaves_no_bson(self, dump_db):
        """If metadata JSON is malformed, the BSON must not be written."""
        dump, db = dump_db
        (db / "system.buckets.weather.bson").write_bytes(SAMPLE_BSON)
        (db / "weather.metadata.json").write_text("{bad json", encoding="utf-8")
        with pytest.raises(json.JSONDecodeError):
            rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        assert not (db / "weather_buckets.bson").exists()


# ---------------------------------------------------------------------------
# TEST: error cases
# ---------------------------------------------------------------------------

class TestErrorCases:
    def test_missing_bson_raises(self, dump_db):
        dump, db = dump_db
        (db / "weather.metadata.json").write_text(json.dumps(SAMPLE_META), encoding="utf-8")
        with pytest.raises(FileNotFoundError, match="system.buckets.weather.bson"):
            rewrite_dump(dump, "mydb", "weather", "weather_buckets")

    def test_missing_metadata_raises(self, dump_db):
        dump, db = dump_db
        (db / "system.buckets.weather.bson").write_bytes(SAMPLE_BSON)
        with pytest.raises(FileNotFoundError, match="weather.metadata.json"):
            rewrite_dump(dump, "mydb", "weather", "weather_buckets")

    def test_wrong_db_name_raises(self, dump_db):
        dump, _ = dump_db
        with pytest.raises(FileNotFoundError, match="wrongdb"):
            rewrite_dump(dump, "wrongdb", "weather", "weather_buckets")

    def test_src_equals_dst_raises(self, dump_db):
        dump, db = dump_db
        write_plain(db, "weather")
        with pytest.raises(ValueError, match="must differ"):
            rewrite_dump(dump, "mydb", "weather", "weather")


# ---------------------------------------------------------------------------
# TEST: CLI (main)
# ---------------------------------------------------------------------------

class TestCLI:
    def test_happy_path_returns_0(self, dump_db):
        dump, db = dump_db
        write_plain(db, "weather")
        rc = main([str(dump), "mydb", "weather", "weather_buckets"])
        assert rc == 0

    def test_missing_file_returns_1(self, dump_db):
        dump, _ = dump_db
        rc = main([str(dump), "mydb", "noexist", "out"])
        assert rc == 1

    def test_collision_without_flag_returns_1(self, dump_db):
        dump, db = dump_db
        write_plain(db, "weather")
        (db / "weather_buckets.bson").write_bytes(b"existing")
        rc = main([str(dump), "mydb", "weather", "weather_buckets"])
        assert rc == 1

    def test_overwrite_flag_via_cli(self, dump_db):
        dump, db = dump_db
        write_plain(db, "weather")
        (db / "weather_buckets.bson").write_bytes(b"stale")
        rc = main([str(dump), "mydb", "weather", "weather_buckets", "--overwrite"])
        assert rc == 0
        assert (db / "weather_buckets.bson").read_bytes() == SAMPLE_BSON

    def test_gz_via_cli(self, dump_db):
        dump, db = dump_db
        write_gz(db, "weather")
        rc = main([str(dump), "mydb", "weather", "weather_buckets"])
        assert rc == 0
        assert (db / "weather_buckets.bson.gz").exists()


# ---------------------------------------------------------------------------
# TEST: timeseries options returned and printed
# ---------------------------------------------------------------------------

class TestTimeseriesOptions:
    def test_returns_timeseries_options(self, dump_db):
        dump, db = dump_db
        write_plain(db, "weather")
        ts = rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        assert ts["timeField"] == "t"
        assert ts["metaField"] == "host"
        assert ts["bucketMaxSpanSeconds"] == 3600
        assert ts["bucketRoundingSeconds"] == 3600

    def test_returns_empty_dict_when_no_timeseries_options(self, dump_db):
        dump, db = dump_db
        meta_no_ts = {**SAMPLE_META, "options": {}, "type": "collection"}
        write_plain(db, "weather", meta=meta_no_ts)
        ts = rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        assert ts == {}

    def test_create_collection_snippet_in_stdout(self, dump_db, capsys):
        dump, db = dump_db
        write_plain(db, "weather")
        rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        out = capsys.readouterr().out
        assert 'db.createCollection("weather"' in out
        assert 'timeField: "t"' in out
        assert 'metaField: "host"' in out
        assert "bucketMaxSpanSeconds: 3600" in out
        assert "bucketRoundingSeconds: 3600" in out

    def test_no_create_collection_snippet_when_no_ts_options(self, dump_db, capsys):
        dump, db = dump_db
        meta_no_ts = {**SAMPLE_META, "options": {}, "type": "collection"}
        write_plain(db, "weather", meta=meta_no_ts)
        rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        out = capsys.readouterr().out
        assert "createCollection" not in out

    def test_snippet_omits_absent_fields(self, dump_db, capsys):
        """bucketMaxSpanSeconds should not appear if not in source metadata."""
        dump, db = dump_db
        meta_minimal = {**SAMPLE_META, "options": {"timeseries": {"timeField": "ts"}}}
        write_plain(db, "weather", meta=meta_minimal)
        rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        out = capsys.readouterr().out
        assert 'timeField: "ts"' in out
        assert "metaField" not in out
        assert "bucketMaxSpanSeconds" not in out


# ---------------------------------------------------------------------------
# TEST: _format_create_collection unit tests
# ---------------------------------------------------------------------------

class TestFormatCreateCollection:
    def test_all_fields(self):
        ts = {
            "timeField": "t",
            "metaField": "host",
            "granularity": "hours",
            "bucketMaxSpanSeconds": 3600,
            "bucketRoundingSeconds": 3600,
        }
        out = _format_create_collection("events", ts)
        assert 'db.createCollection("events"' in out
        assert 'timeField: "t"' in out
        assert 'metaField: "host"' in out
        assert 'granularity: "hours"' in out
        assert "bucketMaxSpanSeconds: 3600" in out
        assert "bucketRoundingSeconds: 3600" in out

    def test_no_trailing_comma_on_last_field(self):
        ts = {"timeField": "t", "metaField": "host"}
        out = _format_create_collection("events", ts)
        lines = out.splitlines()
        last_field_line = [l for l in lines if "metaField" in l][0]
        assert not last_field_line.rstrip().endswith(",")

    def test_string_values_quoted(self):
        ts = {"timeField": "timestamp"}
        out = _format_create_collection("c", ts)
        assert 'timeField: "timestamp"' in out

    def test_numeric_values_unquoted(self):
        ts = {"timeField": "t", "bucketMaxSpanSeconds": 86400}
        out = _format_create_collection("c", ts)
        assert "bucketMaxSpanSeconds: 86400" in out
        assert '"86400"' not in out

    def test_unknown_fields_omitted(self):
        ts = {"timeField": "t", "unknownField": "x"}
        out = _format_create_collection("c", ts)
        assert "unknownField" not in out


# ---------------------------------------------------------------------------
# TEST: _decode_extended_json unit tests
# ---------------------------------------------------------------------------

class TestDecodeExtendedJson:
    def test_numberint_decoded(self):
        assert _decode_extended_json({"$numberInt": "3600"}) == 3600

    def test_numberlong_decoded(self):
        assert _decode_extended_json({"$numberLong": "999"}) == 999

    def test_numberdouble_decoded(self):
        assert _decode_extended_json({"$numberDouble": "1.5"}) == 1.5

    def test_nested_dict_decoded(self):
        obj = {"bucketMaxSpanSeconds": {"$numberInt": "3600"}, "timeField": "t"}
        assert _decode_extended_json(obj) == {"bucketMaxSpanSeconds": 3600, "timeField": "t"}

    def test_list_decoded(self):
        obj = [{"$numberInt": "1"}, {"$numberInt": "2"}]
        assert _decode_extended_json(obj) == [1, 2]

    def test_plain_values_unchanged(self):
        assert _decode_extended_json("hello") == "hello"
        assert _decode_extended_json(42) == 42
        assert _decode_extended_json(None) is None


# ---------------------------------------------------------------------------
# TEST: real Extended JSON metadata (as produced by mongodump)
# ---------------------------------------------------------------------------

class TestExtendedJsonMetadata:
    def test_numeric_fields_decoded_in_returned_options(self, dump_db):
        dump, db = dump_db
        write_plain(db, "weather", meta=SAMPLE_META_EXTJSON)
        ts = rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        assert ts["bucketMaxSpanSeconds"] == 3600
        assert ts["bucketRoundingSeconds"] == 3600

    def test_snippet_shows_plain_integers(self, dump_db, capsys):
        dump, db = dump_db
        write_plain(db, "weather", meta=SAMPLE_META_EXTJSON)
        rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        out = capsys.readouterr().out
        assert "bucketMaxSpanSeconds: 3600" in out
        assert "$numberInt" not in out

    def test_index_version_decoded_in_output_metadata(self, dump_db):
        dump, db = dump_db
        write_plain(db, "weather", meta=SAMPLE_META_EXTJSON)
        rewrite_dump(dump, "mydb", "weather", "weather_buckets")
        meta = read_dst_meta(db, "weather_buckets")
        assert meta["indexes"][0]["v"] == 2
