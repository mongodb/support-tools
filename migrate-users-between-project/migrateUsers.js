
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

// You can also access TEMP_PASSWORD if needed
const TEMP_PASSWORD = config.TEMP_PASSWORD;
// === ATLAS API URL ===
const ATLAS_API = config.ATLAS_API;
const ACCEPT_HEADER = config.ACCEPT_HEADER;

// === CLIENTS ===
const sourceClient = new DigestFetchClient(SOURCE_PUBLIC_KEY, SOURCE_PRIVATE_KEY, {
  algorithm: 'MD5',
});

const destClient = new DigestFetchClient(DEST_PUBLIC_KEY, DEST_PRIVATE_KEY, {
  algorithm: 'MD5',
});

// === FETCH USERS FROM SOURCE ===
async function fetchUsers() {
  const url = `${ATLAS_API}/groups/${SOURCE_GROUP_ID}/databaseUsers?envelope=false`;
  const res = await sourceClient.fetch(url, {
    method: 'GET',
    headers: { Accept: ACCEPT_HEADER },
  });

  if (!res.ok) {
    throw new Error(`Fetch failed: ${res.status}`);
  }

  const json = await res.json();
  return json.results || [];
}

// === CREATE USER IN DESTINATION ===
async function createUserInDestination(user) {
  const {
    username,
    databaseName,
    roles,
    x509Type,
    ldapAuthType,
    oidcAuthType,
    awsIAMType,
    labels,
    scopes,
  } = user;

  if (databaseName === '$external') {
    console.log(`⚠️  Skipping $external user: ${username}`);
    return;
  }

  const payload = {
    username,
    databaseName,
    roles,
    x509Type,
    ldapAuthType,
    oidcAuthType,
    awsIAMType,
    labels,
    scopes,
  };

  if (x509Type === 'NONE') {
    payload.password = TEMP_PASSWORD;
  }

  const url = `${ATLAS_API}/groups/${DEST_GROUP_ID}/databaseUsers`;
  const res = await destClient.fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: ACCEPT_HEADER,
    },
    body: JSON.stringify(payload),
  });

  if (res.ok) {
    console.log(`✅ Created user in destination: ${username}`);
  } else {
    const errBody = await res.text();
    console.error(`❌ Failed to create ${username}: ${res.status} ${errBody}`);
  }
}

// === MAIN FLOW ===
(async () => {
  try {
    const users = await fetchUsers();
    console.log(`✅ Users found in source: ${users.length}`);

    for (const user of users) {
      await createUserInDestination(user);
    }

    console.log('🎉 Migration complete.');
  } catch (err) {
    console.error('❌ Migration failed:', err.message);
  }
})();
