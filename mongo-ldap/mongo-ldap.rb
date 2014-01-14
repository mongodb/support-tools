#!/usr/bin/ruby
#
# mongo-ldap.rb -- Utility sync LDAP user roles/permissions into MongoDB
# MongoDB Inc. 2013-2014 -- David Hows
#
# Script Sync Procedure:
#  - Set up connections to MongoDB and LDAP server
#  - Gather the permissions from MongoDB and LDAP
#  - Construct a list of commands to be executed to alter the relevant user permissions
#    - Find all users which exist in MongoDB but not LDAP
#      - These users need to be deleted
#    - Compare all existing users in LDAP and MongoDB
#      - Update permissions on users (if needed) so that both will match
#    - Find all users which exist in LDAP but not MongoDB
#      - These users need to be added
#  - Execute each item in the list of commands against MongoDB to complete the sync
#
# Requires the net/ldap gem and the 1.10 release of the Mongo gem
#
# Usage:
#  ruby mongo-ldap.rb <mongodb URI> <ldap URI>
#
# Permissions needed:
#  The MongoDB URI needs to have permissions that will allow it to modify user permissions on any database (normally userAdminAnyDatabase)
#  The LDAP URI needs to have permissions such that all of the MongoDB users can be read successfully
#
# LDAP Setup:
#  This script works by navigating to the specified MongoDB organizational unit (ou)
#  From here it expects one ou for database that is being managed. Within these database
#  entries there should be one organisational role cn for each permission needed
#  These cn's should be populated with roleOccuptants which are the UID of people granted
#  this given permission on a given database.
#
#  For an example of this setup please see the "example.ldif" file within this repository.
#
#  DISCLAIMER
#
#  Please note: all tools/ scripts in this repo are released for use "AS
#  IS" without any warranties of any kind, including, but not limited to
#  their installation, use, or performance. We disclaim any and all
#  warranties, either express or implied, including but not limited to
#  any warranty of noninfringement, merchantability, and/ or fitness for
#  a particular purpose. We do not warrant that the technology will
#  meet your requirements, that the operation thereof will be
#  uninterrupted or error-free, or that any errors will be corrected.
#
#  Any use of these scripts and tools is at your own risk. There is no
#  guarantee that they have been through thorough testing in a
#  comparable environment and we are not responsible for any damage
#  or data loss incurred with their use.
#
#  You are responsible for reviewing and testing any scripts you run
#  thoroughly before use in any non-testing environment.
#

require 'net/ldap'	# gem install net-ldap
require 'mongo'		# gem install mongo

mongouri = ARGV[0]
ldapuri = ARGV[1]

#MongoDB URI Format mongodb://username:password@host:port/db
#mongouri = 'mongodb://mongoAdmin:password@myhostname:27017/$external'

#LDAP URI Format ldap://user:password@host:port/mongoDN
#ldapuri = "ldap://cn=Admin,dc=nodomain:password@myhostname:389/ou=MongoDB,dc=nodomain"

#Quick parse for the ldap details
ldapuser,ldappass,ldapstring,ldapMongoDn = /^ldap:\/\/(.+):(.+)@(.+)\/(.+)$/.match(ldapuri).captures

#Ldap Connection Information
ldap = Net::LDAP.new
ldap.host = ldapstring.split(":")[0]
ldap.port = ldapstring.split(":")[1]
ldap.auth ldapuser, ldappass
unless ldap.bind
  p ldap.get_operation_result
  exit(1)
end

#Filter, find all sub-units, but exclude the top level mongodb
filter = Net::LDAP::Filter.join(Net::LDAP::Filter.eq("ou", "*"), ~Net::LDAP::Filter.begins("ou", "MongoDB"))
#We want the cn entries which represent each 
permissionFilter = Net::LDAP::Filter.eq("cn", "*")
dbentries = []
permissionsStructure = {}
dbPermissions = {}
commandsToExecute = []

#Search the top level DN
ldap.search(:base => ldapMongoDn, :filter => filter) do |databaseOu|
  dbentries.push databaseOu.dn
end

dbentries.each do |dbentry|
  ldap.search(:base => dbentry, :filter => permissionFilter) do |databaseEntries|
    #We only care about the roleoccupants, so just iterate them out
    databaseEntries["roleoccupant"].each do |user|
      username = user.split(",")[0].split("=")[1]
      db = dbentry.split(",")[0].split("=")[1]
      role = databaseEntries.dn.split(",")[0].split("=")[1]
      dataHash = {"role" => role, "db" => db}
      (permissionsStructure[username] ||= []) << dataHash
    end
  end	
end
if permissionsStructure.empty?
  p 'Failed to pull any permissions down from LDAP, this feels like an error. Cowardly bailing before doing anything'
  exit(2)
end

#Connect to the MongoDB instance we want to mange
mongo = Mongo::MongoClient.from_uri(mongouri)
#Grab the users
col = mongo["admin"]["system.users"]
col.find({"_id" => /^\$external/ }).each do |user|
  #If this is an externally managed user, add it to our hash
  dbPermissions[user["user"]] = user
end

#Cant delete from an iterative loop mid-flight, so we need to maintain a list of things to delete
delUser1 = []
delUser2 = []

#First go through and remove any users which are to be deleted
dbPermissions.each_key do |userName|
  unless permissionsStructure.has_key? userName
    delUser1 << userName
    commandsToExecute << {"dropUser" => userName }
  end
end
#Delete any of these users which we dont need
delUser1.each do |del|
  dbPermissions.delete(del)
end


#Delta the two maps
permissionsStructure.each_key do |userName|
  unless dbPermissions.has_key? userName
  #Find anything which is 100% missing, we need to add it
  	commandsToExecute << {"createUser" => userName, "roles" => permissionsStructure[userName] }
  	permissionsStructure.delete(userName)
  else
  #Cant delete from an iterative loop mid-flight, so we need to maintain a list of things to delete
  tbd1 = []
  tbd2 = []

  #User exists, we should review it and see whats different
  	permissionsStructure[userName].each do |topIter|
      dbPermissions[userName]["roles"].each do |innerIter|
      	#Do we have this document represented in the hash?
  		if topIter["role"] == innerIter["role"] && topIter["db"] == innerIter["db"]
          #Have we checked for all the permissions? If so, delete them from our mapping
          tbd1 << topIter
          tbd2 << innerIter
  		end
  	  end
  	end
  	
  	tbd1.each do |del|
      permissionsStructure[userName].delete(del)
  	end
  	tbd2.each do |del|
      dbPermissions[userName]["roles"].delete(del)
  	end
  	if dbPermissions[userName]["roles"].empty?
  		delUser1 << userName
    end
  	if permissionsStructure[userName].empty?
  		delUser2 << userName
    end
  end
end

#Delete the finished users
delUser1.each do |del|
  dbPermissions.delete(del)
end
delUser2.each do |del|
  permissionsStructure.delete(del)
end

#From the remaining list build up the roles we need to grant and revoke
dbPermissions.each_key do |userName|
  dbPermissions[userName]["roles"].each do |role|
    commandsToExecute << { "revokeRolesFromUser" => userName, "roles" => [] << role }
  end
end
dbPermissions.clear

permissionsStructure.each_key do |userName|
  permissionsStructure[userName].each do |role|
    commandsToExecute << { "grantRolesToUser" => userName, "roles" => [] << role }
  end
end
permissionsStructure.clear

#Execute the commands needed to bring mongo into line
externalDB = mongo["$external"]
commandsToExecute.each do |cmd|
  p "Executing: #{cmd}"
  res = externalDB.command(cmd)
  if res["ok"] != 1
    p "Execution failed: #{res}"
  end
end
