mongo-ldap connector
==========

Conects to an LDAP instance to collect permissions for users and sync these to a MongoDB instance.

Usage:
	ruby mongo-ldap.rb <mongo URI> <ldap URI>

Permissions needed:
  The MongoDB URI needs to have permissions that will allow it to modify user permissions on any database (normally userAdminAnyDatabase)
  The LDAP URI needs to have permissions such that all of the MongoDB users can be read successfully

LDAP Setup:
  This script works by navigating to the specified MongoDB organizational unit (ou)
  From here it expects one ou for database that is being managed. Within these database
  entries there should be one organisational role cn for each permission needed
  These cn's should be populated with roleOccuptants which are the UID of people granted
  this given permission on a given database.

For an example of this setup please see the "example.ldif" file within this repository.
