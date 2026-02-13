#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple


# Order-preserving, hashable signature for an index key pattern
KeySig = Tuple[Tuple[str, Any], ...]



# -------------------------
# Filter helpers
# -------------------------

def _parse_csv_set(value: Optional[str]) -> Optional[Set[str]]:
    if not value:
        return None
    items = [v.strip() for v in value.split(",") if v.strip()]
    return set(items) if items else None


def _compile_regex(pattern: Optional[str]) -> Optional[re.Pattern]:
    if not pattern:
        return None
    return re.compile(pattern)


def ns_allowed(
    db: str,
    coll: str,
    include_dbs: Optional[Set[str]],
    exclude_dbs: Optional[Set[str]],
    include_ns_re: Optional[re.Pattern],
) -> bool:
    # include/exclude DBs
    if include_dbs is not None and db not in include_dbs:
        return False
    if exclude_dbs is not None and db in exclude_dbs:
        return False

    # system DBs are always excluded
    if db in ("admin", "local", "config"):
        return False

    # include-ns regex on db.collection
    if include_ns_re is not None:
        ns = f"{db}.{coll}"
        if not include_ns_re.search(ns):
            return False

    return True


# -------------------------
# Normalization + core logic
# -------------------------

def normalize_key_pattern(key_obj: Any) -> KeySig:
    """
    Normalize index key patterns into an order-preserving, hashable representation.

    IMPORTANT: Order matters for compound indexes in MongoDB.
    """

    if isinstance(key_obj, dict):
        return tuple((str(k), v) for k, v in key_obj.items())

    if isinstance(key_obj, (list, tuple)):
        pairs: List[Tuple[str, Any]] = []
        for item in key_obj:
            if isinstance(item, (list, tuple)) and len(item) == 2:
                pairs.append((str(item[0]), item[1]))
            else:
                return (("<<unrecognized_key>>", str(key_obj)),)
        return tuple(pairs)

    # Last resort: try .items() (dict-like)
    try:
        items = list(key_obj.items())  # type: ignore[attr-defined]
        return tuple((str(k), v) for k, v in items)
    except Exception:
        return (("<<unrecognized_key>>", str(key_obj)),)


def find_limitations(index_rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    index_rows yields dicts shaped like:
      {
        "database": str,
        "collection": str,
        "index_name": str,
        "key": <dict or list of pairs>,
        "unique": bool
      }
    """

    per_collection: Dict[Tuple[str, str], Dict[KeySig, Dict[str, List[str]]]] = defaultdict(
        lambda: defaultdict(lambda: {"unique": [], "non_unique": []})
    )

    for row in index_rows:
        db = row.get("database")
        coll = row.get("collection")
        name = row.get("index_name", "<unknown_index_name>")
        key = row.get("key")
        unique = bool(row.get("unique", False))

        if not db or not coll or key is None:
            continue

        key_pattern = normalize_key_pattern(key)
        bucket = "unique" if unique else "non_unique"
        per_collection[(db, coll)][key_pattern][bucket].append(str(name))

    limitations: List[Dict[str, Any]] = []

    for (db, coll), by_key in per_collection.items():
        for key_pattern, buckets in by_key.items():
            if buckets["unique"] and buckets["non_unique"]:
                limitations.append(
                    {
                        "database": db,
                        "collection": coll,
                        "index_keys": [list(kv) for kv in key_pattern],
                        "unique_index_names": sorted(set(buckets["unique"])),
                        "non_unique_index_names": sorted(set(buckets["non_unique"])),
                    }
                )

    limitations.sort(key=lambda d: (d["database"], d["collection"], str(d["index_keys"])))
    return limitations


# -------------------------
# Offline extractor (getMongoData)
# -------------------------

def iter_indexes_from_getmongodata(
    docs: List[Dict[str, Any]],
    include_dbs: Optional[Set[str]],
    exclude_dbs: Optional[Set[str]],
    include_ns_re: Optional[re.Pattern],
) -> Iterable[Dict[str, Any]]:
    for doc in docs:
        if doc.get("section") != "data_info":
            continue
        if doc.get("subsection") != "indexes":
            continue
        if doc.get("error") is not None:
            continue

        params = doc.get("commandParameters") or {}
        db = params.get("db")
        coll = params.get("collection")
        output = doc.get("output")

        if not db or not coll or not isinstance(output, list):
            continue

        if not ns_allowed(db, coll, include_dbs, exclude_dbs, include_ns_re):
            continue

        for idx in output:
            if not isinstance(idx, dict):
                continue

            yield {
                "database": db,
                "collection": coll,
                "index_name": idx.get("name", "<unknown_index_name>"),
                "key": idx.get("key"),
                "unique": bool(idx.get("unique", False)),
            }


# -------------------------
# Online extractor (MongoDB cluster)
# -------------------------

def iter_indexes_from_cluster(
    uri: str,
    include_dbs: Optional[Set[str]],
    exclude_dbs: Optional[Set[str]],
    include_ns_re: Optional[re.Pattern],
    use_certifi_ca: bool = False,
) -> Iterable[Dict[str, Any]]:
    try:
        from pymongo import MongoClient
    except Exception as e:
        raise RuntimeError(f"PyMongo is required for --uri mode. Install with: pip install pymongo. Error: {e}")

    client_kwargs: Dict[str, Any] = {}
    if use_certifi_ca:
        try:
            import certifi
            client_kwargs["tlsCAFile"] = certifi.where()
        except Exception as e:
            raise RuntimeError(
                f"--use-certifi-ca requested but certifi not available. Install: pip install certifi. Error: {e}"
            )

    client = MongoClient(uri, **client_kwargs)
    try:
        db_names = client.list_database_names()
        for db_name in db_names:
            # DB-level filters first
            if include_dbs is not None and db_name not in include_dbs:
                continue
            if exclude_dbs is not None and db_name in exclude_dbs:
                continue
            if db_name in ("admin", "local", "config"):
                continue

            db = client[db_name]
            try:
                coll_names = db.list_collection_names()
            except Exception:
                continue

            for coll_name in coll_names:
                if not ns_allowed(db_name, coll_name, include_dbs, exclude_dbs, include_ns_re):
                    continue

                coll = db[coll_name]
                try:
                    for idx in coll.list_indexes():
                        yield {
                            "database": db_name,
                            "collection": coll_name,
                            "index_name": idx.get("name", "<unknown_index_name>"),
                            "key": idx.get("key"),
                            "unique": bool(idx.get("unique", False)),
                        }
                except Exception:
                    continue
    finally:
        client.close()


# -------------------------
# Output helpers
# -------------------------

def print_report(limitations: List[Dict[str, Any]], title: str, input_label: str) -> None:
    print(title)
    print(f"Input: {input_label}")
    print("Checking for unique and non-unique indexes on the same field/s...")
    print(f"Limitations found: {len(limitations)}\n")

    if not limitations:
        print("No limitations found.")
        return

    for item in limitations:
        ns = f"{item['database']}.{item['collection']}"
        keys_dict = {k: v for k, v in item["index_keys"]}
        print(
            f"- {ns} | keys={keys_dict} "
            f"| uniqueIndex={item['unique_index_names']} | non-uniqueIndex={item['non_unique_index_names']}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Unified mongosync limitations checker (online MongoDB cluster OR offline getMongoData JSON)."
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--uri", help="MongoDB connection string (online mode).")
    mode.add_argument("--getmongodata", help="Path to getMongoData JSON file (offline mode).")

    # Filters
    parser.add_argument("--include-dbs", default=None, help="Comma-separated DB list to include (only these DBs).")
    parser.add_argument("--exclude-dbs", default=None, help="Comma-separated DB list to exclude.")
    parser.add_argument("--include-ns", default=None, help=r'Regex filter on namespace "db.collection". Example: "^prod_".')

    # Output / TLS helpers
    parser.add_argument("--out", default=None, help="Write limitations to a JSON file.")
    parser.add_argument(
        "--use-certifi-ca",
        action="store_true",
        help="Online mode only: use certifi CA bundle (fixes CERTIFICATE_VERIFY_FAILED on some machines).",
    )

    args = parser.parse_args()

    include_dbs = _parse_csv_set(args.include_dbs)
    exclude_dbs = _parse_csv_set(args.exclude_dbs)
    include_ns_re = _compile_regex(args.include_ns)

    try:
        if args.uri:
            rows = iter_indexes_from_cluster(
                args.uri,
                include_dbs=include_dbs,
                exclude_dbs=exclude_dbs,
                include_ns_re=include_ns_re,
                use_certifi_ca=args.use_certifi_ca,
            )
            limitations = find_limitations(rows)
            print_report(limitations, "Starting mongosync limitations checker (ONLINE).", args.uri)

        else:
            with open(args.getmongodata, "r", encoding="utf-8") as f:
                docs = json.load(f)
            if not isinstance(docs, list):
                print("ERROR: getMongoData JSON top-level must be a list.", file=sys.stderr)
                return 2

            rows = iter_indexes_from_getmongodata(
                docs,
                include_dbs=include_dbs,
                exclude_dbs=exclude_dbs,
                include_ns_re=include_ns_re,
            )
            limitations = find_limitations(rows)
            print_report(limitations, "Starting mongosync limitations checker (OFFLINE getMongoData).", args.getmongodata)

        if args.out:
            with open(args.out, "w", encoding="utf-8") as f:
                json.dump(limitations, f, indent=2)
            print(f"\nWrote JSON report to: {args.out}")

        print("\nFinishing mongosync limitations checker.")
        return 0

    except Exception as e:
        print(f"An error occurred: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
