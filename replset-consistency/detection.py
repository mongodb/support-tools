# Find accidentally iso-8859-1 encoded strings in the db

from pymongo import MongoClient
from bson.raw_bson import RawBSONDocument
from bson.codec_options import CodecOptions
import os
import re
import codecs
import bson

def find_docs_to_fix(collection, raw_bson_doc, needs_fixing=None, _id=None):
    if not isinstance(raw_bson_doc, RawBSONDocument):
        return raw_bson_doc

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

    # needs_fixing[0] = False
    new_items = {}

    for item_bs, item_repl in zip(doc_with_backslash_escape.items(), doc_with_replace.items()):
        key_bs, value_bs = item_bs
        key_repl, value_repl = item_repl

        fixed_key = key_repl
        if key_bs != key_repl:
            needs_fixing[0] = True

        if isinstance(value_repl, RawBSONDocument):
            fixed_value = find_docs_to_fix(collection, value_repl.raw, needs_fixing=needs_fixing, _id=_id)
        elif isinstance(value_repl, list):
            fixed_value = [find_docs_to_fix(collection, doc, needs_fixing=needs_fixing, _id=_id) for doc in value_repl]
        elif value_bs != value_repl:
            assert not is_toplevel or key_bs != '_id'
            needs_fixing[0] = True
        else:
            fixed_value = value_repl


    if needs_fixing[0]:
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
