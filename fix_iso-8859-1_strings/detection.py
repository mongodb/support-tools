#! /usr/bin/env python3

# Find iso-8859-1 encoded strings

from pymongo import MongoClient
from bson.raw_bson import RawBSONDocument
from bson.codec_options import CodecOptions
from bson.json_util import dumps
import csv
import re
import bson

csv_file = open('to_fix.csv', 'w', newline='')
writer = csv.writer(csv_file, delimiter=',')

# Header
writer.writerow(['collection', '_id'])

def compare_and_fix(collection, backs, repls, needs_fixing, _id):
    if isinstance(repls, RawBSONDocument):
        return find_docs_to_fix(collection, repls, needs_fixing=needs_fixing, _id=_id)
    elif isinstance(repls, list):
        assert len(backs) == len(repls)
        return [compare_and_fix(collection, backs[i], repls[i], needs_fixing, _id) for i in range(len(backs))]
    elif backs != repls:
        needs_fixing[0] = True


def find_docs_to_fix(collection, raw_bson_doc, needs_fixing=None, _id=None):
    if needs_fixing is None: needs_fixing = [False]
    doc_with_backslash_escape = bson.decode(
        raw_bson_doc.raw,
        codec_options=CodecOptions(document_class=RawBSONDocument,unicode_decode_error_handler='backslashreplace'))
    doc_with_replace = bson.decode(
        raw_bson_doc.raw,
        codec_options=CodecOptions(document_class=RawBSONDocument,unicode_decode_error_handler='replace'))

    is_toplevel = _id is None
    if is_toplevel:
        for key, value in doc_with_backslash_escape.items():
            if key == '_id':
                _id = value
                break

    new_items = {}

    for item_bs, item_repl in zip(doc_with_backslash_escape.items(), doc_with_replace.items()):
        key_bs, value_bs = item_bs
        key_repl, value_repl = item_repl

        fixed_key = key_repl
        if key_bs != key_repl:
            needs_fixing[0] = True

        compare_and_fix(collection, value_bs, value_repl, needs_fixing, _id)

    if needs_fixing[0] and is_toplevel:
        writer.writerow([collection, dumps(_id)])
        print ('Document with _id ' + str(_id) + ' in ' + collection + ' needs fixing')
    return raw_bson_doc

# Connect to MongoDB
client = MongoClient(document_class=RawBSONDocument)

dbs = client.list_database_names()
for db_name in dbs:
    db = client[db_name]
    colls = db.list_collection_names()
    for coll_name in colls:
        collection = db[coll_name]

        for doc in collection.find():
            find_docs_to_fix(db_name + '.' + coll_name, doc)

csv_file.close()