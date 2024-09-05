#! /usr/bin/env python3

# Fix iso-8859-1 encoded strings

from pymongo import MongoClient
from bson.raw_bson import RawBSONDocument
from bson.codec_options import CodecOptions
from bson.json_util import loads
import csv
import os
import codecs
import re
import bson

def fixup_single_string(with_backslashes, with_replace, _id):
    assert isinstance(with_backslashes, str)
    assert isinstance(with_replace, str)
    assert '\ufffd' in with_replace
    fixed = with_backslashes.encode('iso-8859-1')
    fixed = re.sub(rb'\\x([a-f0-9]{2})', lambda m: codecs.decode(m.group(1).decode('utf8'), 'hex'), fixed)
    fixed = fixed.decode('iso-8859-1')

    return fixed


def compare_and_fix(backs, repls, _id):
    if isinstance(repls, RawBSONDocument):
        return generate_update_to_convert_iso88591_data_to_utf8(repls, _id=_id)
    elif isinstance(repls, list):
        assert len(backs) == len(repls)
        return [compare_and_fix(backs[i], repls[i], _id) for i in range(len(backs))]
    elif backs != repls:
        return fixup_single_string(backs, repls, _id)
    else:
        return repls

def generate_update_to_convert_iso88591_data_to_utf8(raw_bson_doc, _id=None):
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
            fixed_key = fixup_single_string(key_bs, key_repl, _id)

        new_items[fixed_key] = compare_and_fix(value_bs, value_repl, _id)

    return RawBSONDocument(bson.encode(new_items))


csv_file = open('to_fix.csv', 'r', newline='')
reader = csv.reader(csv_file, delimiter=',')

# Connect to MongoDB
client = MongoClient(document_class=RawBSONDocument)

is_header = True
for row in reader:
    if is_header:
        is_header = False
        continue

    _id = loads(row[1])
    print ('Fixing document with _id ' + str(_id) + ' in ' + row[0])

    dot_index = row[0].rindex(".")
    db_name = row[0][0:dot_index]
    coll_name = row[0][dot_index+1:]
    db = client[db_name]
    coll = db[coll_name]

    doc = coll.find_one({"_id": _id})
    fixed_doc = generate_update_to_convert_iso88591_data_to_utf8(doc)
    coll.replace_one(doc, fixed_doc)

csv_file.close()