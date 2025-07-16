// === SOURCE PROJECT ===
const SOURCE_PUBLIC_KEY = 'your_source_public_key';
const SOURCE_PRIVATE_KEY = 'your_source_private_key';
const SOURCE_GROUP_ID = 'your_source_project_id';

// === DESTINATION PROJECT ===
const DEST_PUBLIC_KEY = 'your_dest_public_key';
const DEST_PRIVATE_KEY = 'your_dest_private_key';
const DEST_GROUP_ID = 'your_dest_project_id';

// === DEFAULT PASSWORD ===
const TEMP_PASSWORD = 'Temp@1234'; // You may choose to override this via env variable

// === ATLAS API URL ===
const ATLAS_API = 'https://cloud.mongodb.com/api/atlas/v2';
const ACCEPT_HEADER = 'application/vnd.atlas.2025-03-12+json';


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
