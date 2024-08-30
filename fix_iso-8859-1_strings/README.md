In the event BSON data was written to a cluster using Node v22.7.0 where [UTF-8 encodings are broken](https://github.com/nodejs/node/issues/54543), this script can be used to identify these documents.

The `detection.py` script leverages PyMongo and has been tested against 4.2.25, 4.4.29, 5.0.28, and 6.0.17. Its output includes the `_id` and the database and collection.

This information can then be used to remediate the issue. It is recommended that you leverage the script as an example and make it applicable to your environment.

> python3 detection.py
Document with _id 66d161042719006a01c1b10f in myProject.documents needs fixing

Note that this will scan all documents in all databases and collections and should only be done as a scheduled maintenance activity. If you require assistance with the proposed processes for detecting incorrectly encoded documents please contact MongoDB Support.