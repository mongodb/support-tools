mongo-ldap connector
==========

Connects to an LDAP instance to collect permissions for users and sync these to a MongoDB instance.

Usage:
	ruby mongo-ldap.rb <mongo URI> <ldap URI>

Permissions needed:
  The MongoDB URI needs to have permissions that will allow it to modify user permissions on any database (normally userAdminAnyDatabase).
  The LDAP URI needs to have permissions such that all of the MongoDB users can be read successfully.

LDAP Setup:
  This script works by navigating to the specified MongoDB organizational unit (ou).
  From here it expects one ou for database that is being managed. Within these database.
  entries there should be one organisational role cn for each permission needed.
  These cn's should be populated with roleOccupants which are the UID of people granted
  this given permission on a given database.

For an example of this setup please see the "example.ldif" file within this repository.

DISCLAIMER
----------
Please note: all tools/ scripts in this repo are released for use "AS IS" **without any warranties of any kind**,
including, but not limited to their installation, use, or performance.  We disclaim any and all warranties, either
express or implied, including but not limited to any warranty of noninfringement, merchantability, and/ or fitness
for a particular purpose.  We do not warrant that the technology will meet your requirements, that the operation
thereof will be uninterrupted or error-free, or that any errors will be corrected.

Any use of these scripts and tools is **at your own risk**.  There is no guarantee that they have been through
thorough testing in a comparable environment and we are not responsible for any damage or data loss incurred with
their use.

You are responsible for reviewing and testing any scripts you run *thoroughly* before use in any non-testing
environment.

Thanks,
The MongoDB Support Team
