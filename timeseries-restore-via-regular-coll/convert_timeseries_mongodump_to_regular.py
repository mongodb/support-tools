#!/usr/bin/env python3
import argparse
import gzip
import json
import shutil
import sys
from pathlib import Path


def _find_file(directory: Path, base_name: str) -> tuple:
    """Return (path, is_gzipped). Raises FileNotFoundError if neither form exists."""
    plain = directory / base_name
    gz    = directory / (base_name + ".gz")
    if plain.is_file():
        return plain, False
    if gz.is_file():
        return gz, True
    raise FileNotFoundError(f"Missing file: {plain} (also tried {gz})")


def _decode_extended_json(obj):
    """Recursively convert MongoDB Extended JSON scalars to plain Python values.

    mongodump writes metadata as Extended JSON, so integers appear as
    {"$numberInt": "3600"} rather than 3600.  This decoder normalises them so
    the rest of the script can treat values as ordinary Python primitives.
    """
    if isinstance(obj, dict):
        if "$numberInt" in obj:
            return int(obj["$numberInt"])
        if "$numberLong" in obj:
            return int(obj["$numberLong"])
        if "$numberDouble" in obj:
            raw = obj["$numberDouble"]
            return float(raw) if raw not in ("Infinity", "-Infinity", "NaN") else raw
        if "$numberDecimal" in obj:
            return float(obj["$numberDecimal"])
        return {k: _decode_extended_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_decode_extended_json(item) for item in obj]
    return obj


def _format_create_collection(coll_name: str, ts_options: dict) -> str:
    """Return a mongosh db.createCollection() snippet for the given timeseries options."""
    known_keys = (
        "timeField", "metaField", "granularity",
        "bucketMaxSpanSeconds", "bucketRoundingSeconds",
    )
    present = [(k, ts_options[k]) for k in known_keys if k in ts_options]
    lines = [f'  db.createCollection("{coll_name}", {{', "    timeseries: {"]
    for i, (key, val) in enumerate(present):
        comma = "," if i < len(present) - 1 else ""
        quoted = f'"{val}"' if isinstance(val, str) else val
        lines.append(f"      {key}: {quoted}{comma}")
    lines += ["    }", "  })"]
    return "\n".join(lines)


def rewrite_dump(dump_dir: Path, db: str, src_ts_coll: str, dst_coll: str,
                 overwrite: bool = False) -> dict:
    if src_ts_coll == dst_coll:
        raise ValueError(
            f"Source and destination collection names must differ; both are '{src_ts_coll}'"
        )

    db_dir = dump_dir / db
    if not db_dir.is_dir():
        raise FileNotFoundError(f"Database directory not found in dump: {db_dir}")

    src_bson, bson_gz = _find_file(db_dir, f"system.buckets.{src_ts_coll}.bson")
    src_meta, meta_gz = _find_file(db_dir, f"{src_ts_coll}.metadata.json")

    dst_bson = db_dir / (f"{dst_coll}.bson.gz" if bson_gz else f"{dst_coll}.bson")
    dst_meta = db_dir / (f"{dst_coll}.metadata.json.gz" if meta_gz else f"{dst_coll}.metadata.json")

    if not overwrite:
        for path in (dst_bson, dst_meta):
            if path.exists():
                raise FileExistsError(
                    f"Destination file already exists: {path}. Use --overwrite to replace it."
                )

    # Read and validate metadata BEFORE touching any output files so that a bad
    # metadata file does not leave a half-written BSON with no matching metadata.
    _open_meta = gzip.open if meta_gz else open
    with _open_meta(src_meta, "rt", encoding="utf-8") as f:
        meta = _decode_extended_json(json.load(f))

    # Extract timeseries options before stripping so we can print them for Phase 2.
    raw_options = meta.get("options") or {}
    ts_options  = dict(raw_options.get("timeseries") or {})

    # Strip timeseries / view-only bits from options.
    options = raw_options
    options.pop("timeseries", None)
    options.pop("viewOn", None)
    options.pop("pipeline", None)
    meta["options"] = options

    # Fix index namespaces.
    indexes = meta.get("indexes") or []
    for idx in indexes:
        if "ns" in idx:
            idx["ns"] = f"{db}.{dst_coll}"
    meta["indexes"] = indexes

    # Drop top-level type / update collectionName.
    meta.pop("type", None)
    if "collectionName" in meta:
        meta["collectionName"] = dst_coll

    meta_json = json.dumps(meta, indent=2, sort_keys=True) + "\n"

    # 1) Copy BSON (metadata is already validated — no partial-write risk).
    shutil.copyfile(src_bson, dst_bson)

    # 2) Write rewritten metadata.
    if meta_gz:
        with gzip.open(dst_meta, "wt", encoding="utf-8") as f:
            f.write(meta_json)
    else:
        with dst_meta.open("w", encoding="utf-8") as f:
            f.write(meta_json)

    print("Wrote:")
    print(f"  BSON:     {dst_bson}")
    print(f"  metadata: {dst_meta}")
    print()
    print("Restore the bucket documents into a regular collection (Phase 2, step 1):")
    gz_flag = " --gzip" if bson_gz else ""
    print(f'  mongorestore{gz_flag} --db "{db}" --collection "{dst_coll}" "{dst_bson}"')
    print()
    if ts_options:
        print("Create the target timeseries collection before running the restore script (Phase 2, step 2):")
        print(_format_create_collection(src_ts_coll, ts_options))

    return ts_options


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Rewrite a timeseries dump so mongorestore sees it as a regular collection "
            "containing bucket documents."
        )
    )
    parser.add_argument("dump_dir", help="Path to mongodump directory (e.g. ./dump)")
    parser.add_argument("db_name",  help="Database name in the dump (e.g. test)")
    parser.add_argument(
        "src_ts_coll",
        help="Logical timeseries collection name (e.g. weather)",
    )
    parser.add_argument(
        "dst_coll",
        help="Destination regular collection name (e.g. weather_buckets)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite destination files if they already exist.",
    )

    args = parser.parse_args(argv)

    try:
        rewrite_dump(
            dump_dir=Path(args.dump_dir),
            db=args.db_name,
            src_ts_coll=args.src_ts_coll,
            dst_coll=args.dst_coll,
            overwrite=args.overwrite,
        )
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
