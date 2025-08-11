const { exec } = require('child_process');

function runScript(script) {
  return new Promise((resolve, reject) => {
    const process = exec(`node ${script}`, (error, stdout, stderr) => {
      if (error) {
        console.error(`❌ Error in ${script}:`, error.message);
        reject(error);
      } else {
        console.log(`✅ Finished ${script}\n`);
        console.log(stdout);
        resolve();
      }
    });

    process.stdout.pipe(process.stdout);
    process.stderr.pipe(process.stderr);
  });
}

(async () => {
  try {
    console.log('🚀 Running migrateCustomRoles.js...');
    await runScript('migrateCustomRoles.js');

    // Wait a bit for roles to register
    console.log('\n⏳ Waiting 15 seconds before migrating users...\n');
    await new Promise((res) => setTimeout(res, 15000));

    console.log('🚀 Running migrateUsers.js...');
    await runScript('migrateUsers.js');

    console.log('\n🎉 All migrations completed successfully!');
  } catch (err) {
    console.error('\n❌ Migration process failed.');
  }
})();
