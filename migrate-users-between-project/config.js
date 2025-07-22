// === SOURCE PROJECT ===
// Project from which database users or roles will be copied

const SOURCE_PUBLIC_KEY = 'your_source_public_key';      // Public API key for authenticating with the source Atlas project. The public key acts as the username when making API requests.
const SOURCE_PRIVATE_KEY = 'your_source_private_key';    // Private API key paired with the source public key. The private key acts as the password when making API requests.

const SOURCE_GROUP_ID   = 'your_source_project_id';      // Project ID (groupId) of the source project where users/roles exist

// === DESTINATION PROJECT ===
// Project to which users or roles will be copied or recreated

const DEST_PUBLIC_KEY = 'your_dest_public_key';          // Public API key for authenticating with the destination Atlas project. The public key acts as the username when making API requests.
const DEST_PRIVATE_KEY = 'your_dest_private_key';        // Private API key for destination project (keep it secure). The private key acts as the password when making API requests.

const DEST_GROUP_ID   = 'your_dest_project_id';          // Project ID (groupId) of the destination project where users/roles will be created

// === IMPORTANT NOTES ===
// How to Create API Keys: https://www.mongodb.com/docs/atlas/configure-api-access/#required-access



// === DEFAULT PASSWORD ===

const TEMP_PASSWORD = 'Temp@1234';                       // Default password to assign to users during creation in destination (can be overridden by env variable)

// === ATLAS API CONFIGURATION ===

const ATLAS_API = 'https://cloud.mongodb.com/api/atlas/v2';        // Base URL for MongoDB Atlas Admin API (v2)
const ACCEPT_HEADER = 'application/vnd.atlas.2025-03-12+json';     // Accept header to specify the version of the Admin API to use



module.exports = {
  SOURCE_PUBLIC_KEY,
  SOURCE_PRIVATE_KEY,
  SOURCE_GROUP_ID,
  DEST_PUBLIC_KEY,
  DEST_PRIVATE_KEY,
  DEST_GROUP_ID,
  TEMP_PASSWORD,
  ATLAS_API,
  ACCEPT_HEADER
};
