#!/usr/bin/env python3
#pylint: disable=too-many-locals, disable=too-many-branches, disable=too-many-statements
#pylint: disable=too-many-return-statements, inconsistent-return-statements

"""
=================================================
repair_checked_documents.py: MongoDB guided dbCheck remediation
=================================================

Copyright MongoDB, Inc, 2022

Use this script as part of the guidance in
https://github.com/mongodb/support-tools/tree/replset-consistency/replset-consistency/README.md

This script allowes the user to repair inconsistent replica set documents found using dbcheck
and scan_checked_replset.  On 5.0 and later, the server parameter
'oplogApplicationEnforcesSteadyStateConstraints' must be 'false' (the default) or this script
is likely to trigger fatal errors on the secondaries.  The URI provided must contain authentication
for a privileged use which can read and write any user collection as well as the
"__corruption_repair.unhealthyRanges" metadata collection

Please note: all tools/ scripts in this repo are released for use "AS
IS" without any warranties of any kind, including, but not limited to
their installation, use, or performance. We disclaim any and all
warranties, either express or implied, including but not limited to
any warranty of noninfringement, merchantability, and/ or fitness for
a particular purpose. We do not warrant that the technology will
meet your requirements, that the operation thereof will be
uninterrupted or error-free, or that any errors will be corrected.

Any use of these scripts and tools is at your own risk. There is no
guarantee that they have been through thorough testing in a
comparable environment and we are not responsible for any damage
or data loss incurred with their use.

You are responsible for reviewing and testing any scripts you run
thoroughly before use in any non-testing environment.

LICENSE

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

  http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""

import argparse
import json
import pprint
import sys
import pymongo

METADATA_DB_NAME = "__corruption_repair"
RANGE_COLL_NAME = "unhealthyRanges"
MISSING_DOC_MARKER = "dbcheck_docWasMissing"

def count_same_docs(docs):
    """Goes through each possibility in "docs" and adds unique ones to "doc_counts".
    This is O(N^2) when they are all different and O(N) when they are all the same, but
    we expect N is small (number of nodes in the system)."""
    doc_counts = []
    for i,doc in enumerate(docs):
        for doc_count in doc_counts:
            if doc_count["doc"] == doc:
                doc_count["count"] += 1
                doc_count["indices"].append(i)
                break
        else:
            doc_counts.append({"doc": docs[i], "count":1, "indices": [i]})
    doc_counts.sort(key=lambda doc_count: doc_count["count"], reverse=True)
    return doc_counts

def to_int(int_str, default = 0):
    """ Convert string to integer without exceptions. """
    try:
        return int(int_str)
    except ValueError:
        return default

def project_document(coll, doc_id, proj_str):
    """ Convert the proj_str to a projection, and project doc_id from coll using it """
    try:
        projection = json.loads(proj_str, strict=False)
        return coll.find_one({"_id" : doc_id}, projection)
    except ValueError as ex:
        print("Projection is not valid:", proj_str)
        print(ex)
    except pymongo.errors.PyMongoError as ex:
        print("Document could not be projected: ", proj_str)
        print(ex)
    return None

def ask_user_for_choice(db, nss, coll_names, doc_counts):
    """ Provide the user with info on how to resolve document, and ask how to resolve it """
    pp = pprint.PrettyPrinter(compact=True)
    doc_id = doc_counts[0]["doc"]["_id"]
    choice = None
    while choice is None:
        print("Document in '" + nss + "' with _id", doc_id,
              "is inconsistent across replica set nodes.")
        doc_version_map = dict()
        doc_version = 0
        for i,doc_count in enumerate(doc_counts):
            doc = doc_count["doc"]
            count = doc_count["count"]
            nodes_str = "node" if count == 1 else "nodes"
            if MISSING_DOC_MARKER in doc:
                print("  Document is not present on", count, nodes_str)
            else:
                doc_version += 1
                doc_version_map[doc_version] = i
                print("  Version", doc_version, "is present on", count, nodes_str)
        print("Enter a document version number, optionally followed by a space and a projection")
        print("(e.g. '1 { \"<fieldName>\": 0}'), to view that document version.")
        print("Enter 'r' followed by the document version number to resolve the document to that version on all nodes.")
        print("Enter 'delete' to delete the document on all nodes.")
        print("Enter 'skip' to not resolve this document at this time.")
        while choice is None:
            choice_str = input().strip()
            version = None
            if len(choice_str) == 0:
                break
            if choice_str.lower() == "skip":
                choice = "skip"
            elif choice_str.lower()[0] == 'r' and to_int(choice_str[1:]) > 0:
                version = to_int(choice_str[1:])
                choice = "replace"
                if version not in doc_version_map:
                    print("Document version '" + choice_str[1:] + "'", "does not exist.")
                    choice = None
            elif choice_str[0].isdigit():
                version_projection = choice_str.split(' ', 2)
                version_str = version_projection[0]
                version = to_int(version_str)
                if version not in doc_version_map:
                    print("Document version '" + str(version_str) + "'", "does not exist.")
                    choice = None
                else:
                    doc = doc_counts[doc_version_map[version]]["doc"]
                    if len(version_projection) > 1:
                        projection = version_projection[1]
                        index =  doc_counts[doc_version_map[version]]["indices"][0]
                        doc = project_document(db[coll_names[index]], doc_id, projection)
                    if doc is not None:
                        pp.pprint(doc)
            elif choice_str.lower() == "delete":
                choice = "delete"
            else:
                print("'" + choice_str + "'", "is not valid input")
            if choice in ("delete", "replace"):
                sure = input("Are you sure?  Enter 'yes' to " + choice + ": ")
                if sure.strip().lower() != "yes":
                    print("Not", choice[:-1] + "ing.")
                    choice = None
            print()
            if choice == "replace":
                choice = doc_version_map[version]
    return choice

def make_choice(db, nss, coll_names, doc_counts, strategy):
    """ Make a choice for a document according to the strategy """
    fallback = "ask"
    choice = None
    num_nodes = len(coll_names)
    if strategy is not None:
        fallback = strategy["fallback"]
        if doc_counts[0]["count"] > (num_nodes/2):
            # There is a clear majority.
            if MISSING_DOC_MARKER in doc_counts[0]["doc"]:
                if strategy["delete"] in ["majority", "plurality"]:
                    choice = "delete"
            else:
                if strategy["keep"] in ["majority", "plurality"]:
                    choice = 0   # choice is index into doc_counts.
        elif doc_counts[0]["count"] > doc_counts[1]["count"]:
            # There is a clear plurality
            if MISSING_DOC_MARKER in doc_counts[0]["doc"]:
                if strategy["delete"] == "plurality":
                    choice = "delete"
            else:
                if strategy["keep"] == "plurality":
                    choice = 0   # choice is index into doc_counts.
        else:
            # There is no clear plurality
            keep_versions = 0
            delete_versions = 0  # can only be 0 or 1
            plurality_count = doc_counts[0]["count"]
            for doc_count in doc_counts:
                if doc_count["count"] != plurality_count:
                    break
                if MISSING_DOC_MARKER in doc_count["doc"]:
                    delete_versions += 1
                else:
                    keep_versions += 1
            # With an unclear plurality, only a few cases can be resolved
            # 1) Keep is "majority" or "never", delete is "plurality" and there is a delete
            # 2) delete is "majority" or "never", keep is "plurality" and there is exactly one
            #    keep.
            if (delete_versions == 1 and strategy["delete"] == "plurality" and
                strategy["keep"] in ["majority", "never"]):
                choice = "delete"
            elif (keep_versions == 1 and strategy["keep"] == "plurality" and
                     strategy["delete"] in ["majority", "never"]):
                choice = 1 if MISSING_DOC_MARKER in doc_counts[0]["doc"] else 0
    if choice is None:
        if fallback == "ask":
            choice = ask_user_for_choice(db, nss, coll_names, doc_counts)
        else:
            choice = "skip"
    return choice

def delete_doc(coll, doc_id):
    """
    Replace-then-delete deletes on all nodes regardless of whether the node already had the
    document. It will trigger a fatal error if steady state constraints are enabled and some nodes
    have the document but others don't.
    """
    coll.replace_one({"_id": doc_id}, {"_id": doc_id, "dbcheck_transient_delete": 1}, upsert=True)
    coll.delete_one({"_id": doc_id})

def replace_doc(coll, doc):
    """
    Delete-then-replace replaces on all nodes regardless of whether the node already had the
    document. It will trigger a fatal error if steady state constraints are enabled and some nodes
    have the document but others don't.
    """
    doc_id = doc["_id"]
    coll.delete_one({"_id": doc_id})
    coll.replace_one({"_id": doc_id}, doc, upsert=True)

def announce_choice(nss, doc_choices, choice, *, dryrun=False):
    """ Print out the choice """
    doc_id = doc_choices[0]["doc"]["_id"]
    doc_str = "Document in '" + nss + "' with _id " + str(doc_id)
    dryrun_str = " (dry run)" if dryrun else ""
    total = 0
    missing = 0
    for doc_choice in doc_choices:
        total += doc_choice["count"]
        if MISSING_DOC_MARKER in doc_choice["doc"]:
            missing += doc_choice["count"]
    if choice == "delete":
        print(doc_str, "was deleted (missing on " + str(missing) + "/" + str(total) + " nodes)",
              dryrun_str)
    elif isinstance(choice, int):
        count = doc_choices[choice]["count"]
        print(doc_str, "was replaced with a version present on " +
              str(count) + "/" + str(total) + " nodes)", dryrun_str)
    else:
        print(doc_str, "was not resolved", dryrun_str)

def repair_range(client, range_to_repair, strategy, *, dryrun=False, verbose=False):
    """
    Goes through the documents in the scan collections for a single range, asking the user
    how to resolve them if they are not already resolved.
    """
    fixed_docs = set()
    range_id = range_to_repair["_id"]
    if "fixedDocs" in range_to_repair:
        fixed_docs = set(range_to_repair["fixedDocs"])
    db_to_repair = client[range_id["db"]]
    coll_to_repair = db_to_repair[range_id["collection"]]
    nss = range_id["db"] + "." + range_id["collection"]
# By the operation of the scanning script, all the scan collections should have the same
# set of document ids.  Thus we can scan one and look up by ID in the others.
    scan_collections = range_to_repair["scanCollections"]
    scan_coll0 = db_to_repair[scan_collections[0]]
    min_key = range_id["minKey"]
    max_key = range_id["maxKey"]
    for doc0 in scan_coll0.find({"_id": {"$gte": min_key, "$lt": max_key}}):
        doc_id = doc0["_id"]
        if doc_id in fixed_docs:
            continue
        docs = [doc0]
        for i in range(1, len(scan_collections)):
            docs.append(db_to_repair[scan_collections[i]].find_one({"_id" : doc_id}))
        doc_counts = count_same_docs(docs)
        choice = make_choice(db_to_repair, nss,  scan_collections, doc_counts, strategy)
        if verbose or dryrun:
            announce_choice(nss, doc_counts, choice, dryrun=dryrun)
        if dryrun:
            continue
        if choice == "delete":
            delete_doc(coll_to_repair, doc_id)
        elif isinstance(choice, int):
            doc = doc_counts[choice]["doc"]
            replace_doc(coll_to_repair, doc)
        else:
            continue
        metadata_db = client[METADATA_DB_NAME]
        metadata_db[RANGE_COLL_NAME].update_one({"_id": range_id}, {"$addToSet" : {"fixedDocs": doc_id}})

def repair_ranges(client, strategy, *, dryrun=False, verbose=False):
    """ Calls repair_range for every range scanned """
    metadata_db = client[METADATA_DB_NAME]
    for range_to_repair in metadata_db[RANGE_COLL_NAME].find({"scanned" : True}):
        repair_range(client, range_to_repair, strategy, dryrun=dryrun, verbose=verbose)

def parse_strategy(strategy, fallback):
    """ Break the strategy and fallback arguments up into a dict """
    if strategy == "ask":
        return None
    if strategy == "majority":
        return { "keep": "majority", "delete": "majority", "fallback" : fallback}
    if strategy == "majorityDeletePluralityKeep":
        return { "keep": "plurality", "delete": "majority", "fallback" : fallback}
    if strategy == "majorityKeepPluralityDelete":
        return { "keep": "majority", "delete": "plurality", "fallback" : fallback}
    if strategy == "plurality":
        return { "keep": "plurality", "delete": "plurality", "fallback" : fallback}
    if strategy == "majorityKeepNeverDelete":
        return { "keep": "majority", "delete": "never", "fallback" : fallback}
    if strategy == "pluralityKeepNeverDelete":
        return { "keep": "plurality", "delete": "never", "fallback" : fallback}
    if strategy == "majorityDeleteNeverKeep":
        return { "keep": "never", "delete": "majority", "fallback" : fallback}
    if strategy == "pluralityDeleteNeverKeep":
        return { "keep": "never", "delete": "plurality", "fallback" : fallback}
    assert False, "Strategy " + strategy + " is invalid"

def repair_checked_documents():
    """ Go through the scanned ranges and ask the user for a resolution fro each document """
    parser = argparse.ArgumentParser(description='Resolve documents with no plurality on a corrupted cluster')
    parser.add_argument('uri', metavar='mongoUri',
                    help='The URI for the replica set, including authentication information.')
    parser.add_argument('--strategy', choices=['ask',
                                               'majority',
                                               'majorityDeletePluralityKeep',
                                               'majorityKeepPluralityDelete',
                                               'plurality',
                                               'majorityKeepNeverDelete',
                                               'pluralityKeepNeverDelete',
                                               'majorityDeleteNeverKeep',
                                               'pluralityDeleteNeverKeep'],
                        dest = 'strategy',
                        default='ask',
                        help='The strategy for automatically resolving corrupt documents')
    parser.add_argument('--fallback', choices=['skip', 'ask'], default = 'skip',
                        dest = 'fallback',
                        help='If a strategy other than "ask" is specified, whether to ask for documents which cannot be resolved by the strategy.')
    parser.add_argument('--no-dryrun', action='store_false', dest = 'dryrun',
                        help='If NOT specified, do not actually resolve documents, just print how they would be resolved (if not specificed, implies --verbose).')
    parser.add_argument('--verbose', '-v', action='store_true', dest = 'verbose',
                        help='Print out the disposition of all documents examined.')

    args = parser.parse_args()
    strategy = parse_strategy(args.strategy, args.fallback)
    client = pymongo.MongoClient(args.uri)
    try:
        client.admin.command('ping')
        if not client.is_primary:
            print('Mongo URI', args.uri, 'does not refer to a primary node.',
                  'Please specify a primary node.')
            exit(-1)
    except pymongo.errors.OperationFailure as ex:
        if ex.code == 18:
            print('Unable to authenticate to server, or attempted to connect to an arbiter.')
            exit(-1)
        raise ex
    except pymongo.errors.ConnectionFailure:
        print('Server not available')
        exit(-1)
    repair_ranges(client, strategy, dryrun=args.dryrun, verbose=args.verbose)
    return 0

if __name__ == '__main__':
    sys.exit(repair_checked_documents())
