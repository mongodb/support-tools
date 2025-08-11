
const config = require('./config');

const DigestFetchClient = require('digest-fetch').default;

// === SOURCE PROJECT ===
const SOURCE_PUBLIC_KEY = config.SOURCE_PUBLIC_KEY;
const SOURCE_PRIVATE_KEY = config.SOURCE_PRIVATE_KEY;
const SOURCE_GROUP_ID = config.SOURCE_GROUP_ID;

// === DESTINATION PROJECT ===
const DEST_PUBLIC_KEY = config.DEST_PUBLIC_KEY;
const DEST_PRIVATE_KEY = config.DEST_PRIVATE_KEY;
const DEST_GROUP_ID = config.DEST_GROUP_ID;

// === CONSTANTS ===
const BASE_URL = config.ATLAS_API;
const ACCEPT_HEADER = config.ACCEPT_HEADER;

// === AUTH CLIENTS ===
const sourceClient = new DigestFetchClient(SOURCE_PUBLIC_KEY, SOURCE_PRIVATE_KEY, { algorithm: 'MD5' });
const destClient = new DigestFetchClient(DEST_PUBLIC_KEY, DEST_PRIVATE_KEY, { algorithm: 'MD5' });

// === Fetch all custom roles from source ===
async function fetchCustomRoles() {
  const url = `${BASE_URL}/groups/${SOURCE_GROUP_ID}/customDBRoles/roles?envelope=false`;
  const res = await sourceClient.fetch(url, {
    method: 'GET',
    headers: {
      Accept: ACCEPT_HEADER,
    },
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`❌ Failed to fetch custom roles: ${res.status} - ${text}`);
  }

  const json = await res.json();
  console.log(`🔍 Found ${JSON.stringify(json)} custom roles in source project.`);
  return json || [];
}

// === Create a role in the destination ===
async function createCustomRole(role) {
  const url = `${BASE_URL}/groups/${DEST_GROUP_ID}/customDBRoles/roles?envelope=false`;
  const payload = {
    roleName: role.roleName,
    actions: role.actions,
    inheritedRoles: role.inheritedRoles || [],
  };

  const res = await destClient.fetch(url, {
    method: 'POST',
    headers: {
      Accept: ACCEPT_HEADER,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify(payload),
  });

  if (res.ok) {
    console.log(`✅ Created custom role: ${role.roleName}`);
  } else {
    const errText = await res.text();
    console.error(`❌ Failed to create role ${role.roleName}: ${res.status} ${errText}`);
  }
}

// === MAIN ===
(async () => {
  try {
    const roles = await fetchCustomRoles();
    console.log(`🔍 Found ${roles.length} custom roles to migrate...\n`);

    for (const role of roles) {
      await createCustomRole(role);
    }

    console.log('\n🎉 All custom roles migrated successfully.');
  } catch (err) {
    console.error('❌ Migration failed:', err.message);
  }
})();
