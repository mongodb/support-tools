const fs = require('fs');
const path = require('path');
const readline = require('readline');

// Get the command-line arguments
const args = process.argv.slice(2); // Skip the first two arguments: `node` and script name

const outputAsMarkdown = args.includes('--markdown'); // Check for the optional --markdown flag
const suppressConsole = args.includes('--no-console'); // Check for the optional --no-console flag

// Separate flags from input paths
const inputPaths = args.filter((a) => !a.startsWith('--'));

if (inputPaths.length < 1) {
  console.error('\x1b[31m%s\x1b[0m', 'Error: Please provide the path to a mongosync log file, a directory, or a wildcard pattern.');
  console.error(`Usage: node ${path.basename(process.argv[1])} <path/to/log/files-or-directory> [--markdown] [--no-console]`);
  console.error('  Accepts a single file, multiple files (e.g. via wildcard), or a directory.');
  console.error('  If a directory is provided, all files matching mongosync*.log will be processed.');
  process.exit(1); // Exit with error code 1
}

// Resolve the list of log files to process
let filePaths = [];
for (const inputPath of inputPaths) {
  if (!fs.existsSync(inputPath)) {
    console.error('\x1b[31m%s\x1b[0m', `Error: "${inputPath}" does not exist.`);
    process.exit(1);
  }
  const stat = fs.statSync(inputPath);
  if (stat.isDirectory()) {
    const dirFiles = fs.readdirSync(inputPath)
      .filter((f) => f.startsWith('mongosync') && f.endsWith('.log'))
      .sort()
      .map((f) => path.join(inputPath, f));
    if (dirFiles.length === 0) {
      console.error('\x1b[31m%s\x1b[0m', `Error: No mongosync*.log files found in directory "${inputPath}".`);
      process.exit(1);
    }
    filePaths.push(...dirFiles);
  } else {
    filePaths.push(inputPath);
  }
}

// Sort all resolved files and remove duplicates
filePaths = [...new Set(filePaths)].sort();

// Function to process one or more JSON Lines log files
async function processFiles(filePaths) {
  const namespaceSummary = {};
  const eventTypesSet = new Set(['delete', 'insert', 'replace', 'update']);
  const MAX_LINES_PER_FILE = 5000000; // Optional safeguard for very large files
  for (const filePath of filePaths) {
    if (!suppressConsole) {
      console.log(`Processing file: ${filePath}`);
    }

    // Setup a readable stream
    const fileStream = fs.createReadStream(filePath);
    const rl = readline.createInterface({
      input: fileStream,
      crlfDelay: Infinity,
    });

    fileStream.on('error', (err) => {
      const message = `Error reading file "${filePath}": ${err.message}`;
      if (!suppressConsole) {
        console.error('\x1b[31m%s\x1b[0m', message);
      }
      rl.close();
    });
    let lineCounter = 0; // Count lines processed per file

    // Read each line of the file
    for await (const line of rl) {
      lineCounter++;
      if (lineCounter > MAX_LINES_PER_FILE) {
        if (!suppressConsole) {
          console.warn('\x1b[33m%s\x1b[0m', `Warning: Processing of "${filePath}" stopped after ${MAX_LINES_PER_FILE} lines for safety.`);
        }
        break;
      }

      try {
        // Parse the line into a JSON object
        const jsonObj = JSON.parse(line);

        // Check if the message field matches
        if (jsonObj.message === 'Recent CRUD change event statistics.') {
          const busiestCollections = jsonObj.recentCRUDStatistics?.busiestCollections || [];

          // Loop through busiestCollections to summarize namespaces
          busiestCollections.forEach((collection) => {
            const namespace = collection.namespace;
            const totalEvents = collection.totalEvents;
            const totalEventsPerType = collection.totalEventsPerType || {};

            if (namespace) {
              // Initialize namespace entry if not already present
              if (!namespaceSummary[namespace]) {
                namespaceSummary[namespace] = { totalEvents: 0, totalEventsPerType: {} };
              }

              // Accumulate totalEvents
              namespaceSummary[namespace].totalEvents += totalEvents;

              // Accumulate totalEventsPerType for each type
              for (const [type, count] of Object.entries(totalEventsPerType)) {
                if (!namespaceSummary[namespace].totalEventsPerType[type]) {
                  namespaceSummary[namespace].totalEventsPerType[type] = 0;
                }
                namespaceSummary[namespace].totalEventsPerType[type] += count;

                // Add type to the set for later use in header creation
                eventTypesSet.add(type);
              }
            }
          });
        }
      } catch (error) {
        if (!suppressConsole) {
          console.error('Error processing line:', line);
          console.error('Error details:', error.message);
        }
      }
    }
  }

  // Convert the summary object into an array for sorting
  const summarizedData = Object.entries(namespaceSummary)
    .map(([namespace, { totalEvents, totalEventsPerType }]) => ({
      namespace,
      totalEvents,
      totalEventsPerType,
    }))
    .sort((a, b) => b.totalEvents - a.totalEvents); // Sort by totalEvents in descending order

  const eventTypes = Array.from(eventTypesSet).sort(); // Sort event types alphabetically for consistent output

  // Dynamically calculate column widths
  const columnWidthNamespace = Math.max(30, ...summarizedData.map(({ namespace }) => namespace.length)) + 2;
  const columnWidthEvents = Math.max(15, ...summarizedData.map(({ totalEvents }) => totalEvents.toLocaleString().length)) + 2;
  const columnWidthsByType = eventTypes.map(
    (type) =>
      Math.max(type.length + 2, ...summarizedData.map(({ totalEventsPerType }) => (totalEventsPerType[type] || 0).toLocaleString().length)) + 2
  );

  // Output the sorted result in a readable column format
  if (!suppressConsole) {
    console.log('\n# Namespace Statistics\n');
    console.log('# Sorted by descending total number of write operations\n');

    // Format and print the header
    const headerNamespace = 'Namespace'.padEnd(columnWidthNamespace);
    const headerEvents = 'Total Write Ops'.padStart(columnWidthEvents);
    const headerTypes = eventTypes.map((type, i) => type.padStart(columnWidthsByType[i])).join(' | ');

    console.log(`${headerNamespace} | ${headerEvents} | ${headerTypes}`);

    // Fixing separator row padding
    const separator = `${'-'.repeat(columnWidthNamespace)} | ${'-'.repeat(columnWidthEvents)} | ${columnWidthsByType.map((width) => '-'.repeat(width)).join(' | ')}`;
    console.log(separator);

    // Format and print each row of data
    summarizedData.forEach(({ namespace, totalEvents, totalEventsPerType }) => {
      const typeCounts = eventTypes
        .map((type, i) => (totalEventsPerType[type] || 0).toLocaleString().padStart(columnWidthsByType[i]))
        .join(' | ');

      console.log(`${namespace.padEnd(columnWidthNamespace)} | ${totalEvents.toLocaleString().padStart(columnWidthEvents)} | ${typeCounts}`);
    });
  }

  // Optionally export the data to JSON
  const outputPath = 'busiest_collections.json';
  try {
    fs.writeFileSync(outputPath, JSON.stringify(summarizedData, null, 2));
    if (!suppressConsole) {
      console.log('\x1b[34m%s\x1b[0m', `\nData successfully exported to "${outputPath}". You can open it for offline analysis.\n`);
    }
  } catch (error) {
    console.error('\x1b[31m%s\x1b[0m', `Error writing to "${outputPath}": ${error.message}`);
  }

  // If --markdown flag is provided, generate Markdown output
  if (outputAsMarkdown) {
    const markdownOutput = generateMarkdown(summarizedData, eventTypes, columnWidthNamespace, columnWidthEvents, columnWidthsByType);
    const markdownPath = 'busiest_collections.md';
    try {
      fs.writeFileSync(markdownPath, markdownOutput);
      if (!suppressConsole) {
        console.log('\x1b[34m%s\x1b[0m', `\nMarkdown results successfully exported to "${markdownPath}".\n`);
      }
    } catch (error) {
      console.error('\x1b[31m%s\x1b[0m', `Error writing to "${markdownPath}": ${error.message}`);
    }
  }
}

// Function to generate Markdown output
function generateMarkdown(data, eventTypes, columnWidthNamespace, columnWidthEvents, columnWidthsByType) {
  let markdown = `# Namespace Statistics\n\n`;
  markdown += `# Sorted by descending total number of write operations\n\n`;
  
  // Use dynamic column widths for consistent alignment
  const headerNamespace = 'Namespace'.padEnd(columnWidthNamespace);
  const headerEvents = 'Total Write Ops'.padStart(columnWidthEvents);
  const headerTypes = eventTypes.map((type, i) => type.padStart(columnWidthsByType[i])).join(' | ');
  
  markdown += `| ${headerNamespace} | ${headerEvents} | ${headerTypes} |\n`;
  markdown += `|${'-'.repeat(columnWidthNamespace + 2)}|${'-'.repeat(columnWidthEvents + 2)}|${columnWidthsByType.map((width) => '-'.repeat(width + 2)).join('|')}|\n`;

  data.forEach(({ namespace, totalEvents, totalEventsPerType }) => {
    const typeCounts = eventTypes.map((type, i) => (totalEventsPerType[type] || 0).toLocaleString().padStart(columnWidthsByType[i])).join(' | ');
    markdown += `| ${namespace.padEnd(columnWidthNamespace)} | ${totalEvents.toLocaleString().padStart(columnWidthEvents)} | ${typeCounts} |\n`;
  });

  return markdown;
}

// Run the function with proper error handling
processFiles(filePaths).catch((error) => {
  console.error('\x1b[31m%s\x1b[0m', `Error: ${error.message}`);
  process.exit(1);
});

