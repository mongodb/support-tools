// hot-doc-spread-check.js
(function () {
  const fs = require("fs");

  function bsonString(v) {
    return EJSON.stringify(v, null, 0, { relaxed: false });
  }

  const DEFAULTS = {
    namespaces: [],
    lookbackMs: 5 * 60 * 1000,
    burstWindowMs: 10 * 1000,
    runMs: 5 * 60 * 1000,
    idleMs: 2000,
    maxUniqueDocs: 200000,
    appliers: 128,
    spreadThreshold: 5,
    minDocCps: 2,
    minTotalCps: 10,
    topDocCountForProxy: 5,
    maxBurstCandidates: 100,
    outputFormat: "json",
    outputFile: "hot-doc-spread-check.json"
  };

  const INPUT = globalThis.MONITOR_ARGS || {};
  const CFG = Object.assign({}, DEFAULTS, INPUT);
  if (INPUT.outputMarkdown === true) {
    CFG.outputFormat = "markdown";
  }
  if (INPUT.spreadDisparityThreshold !== undefined) {
    CFG.spreadThreshold = INPUT.spreadDisparityThreshold;
  }

  function validateNumber(name, value, allowZero) {
    if (!Number.isFinite(value) || (!allowZero && value <= 0) || (allowZero && value < 0)) {
      throw new Error(`Invalid ${name}: ${value}`);
    }
  }

  validateNumber("lookbackMs", CFG.lookbackMs, false);
  validateNumber("burstWindowMs", CFG.burstWindowMs, false);
  validateNumber("runMs", CFG.runMs, false);
  validateNumber("idleMs", CFG.idleMs, true);
  validateNumber("maxUniqueDocs", CFG.maxUniqueDocs, false);
  validateNumber("appliers", CFG.appliers, false);
  validateNumber("spreadDisparityThreshold", CFG.spreadThreshold, false);
  validateNumber("minDocCps", CFG.minDocCps, false);
  validateNumber("minTotalCps", CFG.minTotalCps, true);
  validateNumber("topDocCountForProxy", CFG.topDocCountForProxy, false);
  validateNumber("maxBurstCandidates", CFG.maxBurstCandidates, false);

  if (!Number.isInteger(CFG.burstWindowMs) || CFG.burstWindowMs < 1000 || CFG.burstWindowMs % 1000 !== 0) {
    throw new Error(`Invalid burstWindowMs: ${CFG.burstWindowMs}. Expected a whole number of seconds greater than or equal to 1000.`);
  }

  if (!Number.isInteger(CFG.maxUniqueDocs) || CFG.maxUniqueDocs < 1) {
    throw new Error(`Invalid maxUniqueDocs: ${CFG.maxUniqueDocs}. Expected an integer greater than or equal to 1.`);
  }

  if (!Number.isInteger(CFG.appliers) || CFG.appliers < 2) {
    throw new Error(`Invalid appliers: ${CFG.appliers}. Expected an integer greater than or equal to 2.`);
  }

  if (!Number.isInteger(CFG.topDocCountForProxy) || CFG.topDocCountForProxy < 1 || CFG.topDocCountForProxy > 100) {
    throw new Error(`Invalid topDocCountForProxy: ${CFG.topDocCountForProxy}. Expected an integer between 1 and 100.`);
  }

  if (!Number.isInteger(CFG.maxBurstCandidates) || CFG.maxBurstCandidates < 1) {
    throw new Error(`Invalid maxBurstCandidates: ${CFG.maxBurstCandidates}. Expected an integer greater than or equal to 1.`);
  }

  if (!Array.isArray(CFG.namespaces)) {
    throw new Error('namespaces must be an array, e.g. ["db1.coll1", "db2.coll2"]');
  }

  function formatDurationMs(ms) {
    if (ms % 60000 === 0) return `${ms / 60000}m`;
    if (ms % 1000 === 0) return `${ms / 1000}s`;
    return `${ms}ms`;
  }

  const outputFormat = String(CFG.outputFormat || "json").toLowerCase();
  if (!["json", "markdown", "both"].includes(outputFormat)) {
    throw new Error(`Invalid outputFormat: ${CFG.outputFormat}. Expected one of: json, markdown, both.`);
  }

  function parseNamespace(ns) {
    const dot = ns.indexOf(".");
    if (dot <= 0 || dot === ns.length - 1) {
      throw new Error(`Invalid namespace "${ns}". Expected format: database.collection`);
    }
    const dbName = ns.slice(0, dot);
    const collName = ns.slice(dot + 1);
    if (dbName === "admin" || dbName === "config" || dbName === "local" || collName.startsWith("system.")) {
      throw new Error(`Invalid namespace "${ns}". Internal namespaces are not supported: admin, config, local, and system.*`);
    }
    return { db: dbName, coll: collName };
  }

  function timestampParts(value) {
    const seconds = typeof value.getHighBitsUnsigned === "function" ? value.getHighBitsUnsigned() : value.t;
    const increment = typeof value.getLowBitsUnsigned === "function" ? value.getLowBitsUnsigned() : value.i;
    if (!Number.isInteger(seconds) || !Number.isInteger(increment) || seconds < 0 || increment < 0) {
      throw new Error("Invalid BSON timestamp.");
    }
    return { seconds, increment };
  }

  function parseTimeSeconds(value, name) {
    const match = typeof value === "string" && value.match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,3}))?(Z|([+-])(\d{2}):(\d{2}))$/);
    if (!match) {
      throw new Error(`Invalid ${name}: expected an ISO-8601 timestamp with an explicit timezone, e.g. 2026-10-19T08:00:00-04:00.`);
    }

    const year = Number(match[1]);
    const month = Number(match[2]);
    const day = Number(match[3]);
    const hour = Number(match[4]);
    const minute = Number(match[5]);
    const second = Number(match[6]);
    const daysInMonth = [31, (year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0)) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    const offsetHour = match[10] === undefined ? 0 : Number(match[10]);
    const offsetMinute = match[11] === undefined ? 0 : Number(match[11]);
    const dateMs = Date.parse(value);

    if (month < 1 || month > 12 || day < 1 || day > daysInMonth[month - 1] || hour > 23 || minute > 59 || second > 59 || offsetHour > 23 || offsetMinute > 59 || !Number.isFinite(dateMs)) {
      throw new Error(`Invalid ${name}: timestamp components are out of range.`);
    }
    if (dateMs % 1000 !== 0) {
      throw new Error(`Invalid ${name}: MongoDB change-stream timestamps have whole-second precision; use a timestamp with no fractional seconds.`);
    }

    const seconds = dateMs / 1000;
    if (!Number.isInteger(seconds) || seconds < 0) {
      throw new Error(`Invalid ${name}: timestamp must be on or after the Unix epoch.`);
    }
    return seconds;
  }

  function isTimestampAtOrAfter(left, right) {
    const leftParts = timestampParts(left);
    const rightParts = timestampParts(right);
    return leftParts.seconds > rightParts.seconds ||
      (leftParts.seconds === rightParts.seconds && leftParts.increment >= rightParts.increment);
  }

  const watchedNamespaces = CFG.namespaces.map(String);
  const watchAllNamespaces = watchedNamespaces.length === 0;
  const namespaceFilters = watchedNamespaces.map(parseNamespace);

  let helloResult = typeof db.hello === "function" ? db.hello() : db.isMaster();
  if (!helloResult.operationTime && !helloResult.$clusterTime && typeof db.adminCommand === "function") {
    helloResult = db.adminCommand({ hello: 1 });
  }
  const caughtUpWatermark = helloResult.operationTime || (helloResult.$clusterTime && helloResult.$clusterTime.clusterTime);
  if (!caughtUpWatermark) {
    throw new Error("Unable to determine server-derived caught-up watermark from hello response.");
  }

  const hasStartTime = INPUT.startTime !== undefined;
  const hasEndTime = INPUT.endTime !== undefined;
  if (hasStartTime !== hasEndTime) {
    throw new Error("startTime and endTime must be provided together.");
  }
  if (hasStartTime && INPUT.lookbackMs !== undefined) {
    throw new Error("Use either startTime/endTime or lookbackMs, not both.");
  }

  const explicitTimeRange = hasStartTime && hasEndTime;
  const watermarkSeconds = timestampParts(caughtUpWatermark).seconds;
  const startSec = explicitTimeRange ? parseTimeSeconds(INPUT.startTime, "startTime") : watermarkSeconds - Math.ceil(CFG.lookbackMs / 1000);
  const endSec = explicitTimeRange ? parseTimeSeconds(INPUT.endTime, "endTime") : watermarkSeconds;
  if (endSec <= startSec) {
    throw new Error("endTime must be later than startTime.");
  }
  if (endSec > watermarkSeconds) {
    throw new Error("endTime must not be later than the current server time.");
  }

  const startAt = Timestamp(startSec, 0);
  const endAt = Timestamp(endSec, 0);
  const intervalSeconds = endSec - startSec;
  const burstWindowSeconds = Math.min(CFG.burstWindowMs / 1000, intervalSeconds);
  const deadline = Date.now() + CFG.runMs;

  const matchStage = {
    operationType: { $in: ["insert", "update", "delete", "replace"] }
  };

  if (!watchAllNamespaces) {
    matchStage.$or = namespaceFilters.map((x) => ({
      "ns.db": x.db,
      "ns.coll": x.coll
    }));
  } else {
    matchStage.$and = [
      {
        "ns.db": {
          $nin: ["admin", "config", "local"]
        }
      },
      {
        "ns.coll": {
          $not: /^system\./
        }
      }
    ];
  }

  const cs = db.getMongo().watch(
    [
      { $match: matchStage },
      {
        $project: {
          _id: 1,
          operationType: 1,
          clusterTime: 1,
          "ns.db": 1,
          "ns.coll": 1,
          "documentKey._id": 1
        }
      }
    ],
    {
      startAtOperationTime: startAt,
      maxAwaitTimeMS: 250
    }
  );

  if (typeof cs.disableBlockWarnings === "function") {
    cs.disableBlockWarnings();
  }

  const perNs = Object.create(null);
  const nsOrder = [];
  const opMap = {
    insert: "insert",
    update: "update",
    replace: "update",
    delete: "delete"
  };

  let matchedEventsSeen = 0;
  let qualifiedEventsSeen = 0;
  let uniqueDocsTracked = 0;
  let currentBurstWindowIndex = null;
  let currentBurstWindowTotal = 0;
  let currentBurstWindowCounts = new Map();
  let completeBurstWindowsAnalyzed = 0;
  let lastEventAt = Date.now();
  let lastClusterTime = null;
  let stopReason = "unknown";
  const sampleOpenedAt = Date.now();

  const spreadDisparityThreshold = CFG.spreadThreshold;
  const sqrtAppliersMinusOne = Math.sqrt(CFG.appliers - 1);
  const minShareRequired = spreadDisparityThreshold / sqrtAppliersMinusOne;
  const lookbackCurrentLabel = formatDurationMs(intervalSeconds * 1000);
  const lookbackDefaultLabel = formatDurationMs(DEFAULTS.lookbackMs);

  function finalizeBurstWindow(windowIndex) {
    if (windowIndex === null || currentBurstWindowTotal === 0) return;

    const windowStartSec = startSec + windowIndex * burstWindowSeconds;
    const windowSeconds = Math.min(burstWindowSeconds, endSec - windowStartSec);
    if (windowSeconds <= 0) return;

    completeBurstWindowsAnalyzed++;
    for (const [row, opCount] of currentBurstWindowCounts) {
      const eventShare = opCount / currentBurstWindowTotal;
      const spreadDisparityEstimate = eventShare * sqrtAppliersMinusOne;
      const docChangesPerSec = opCount / windowSeconds;
      const totalChangesPerSec = currentBurstWindowTotal / windowSeconds;
      const passesSpreadGate = spreadDisparityEstimate >= spreadDisparityThreshold;
      const passesDocCpsGate = docChangesPerSec >= CFG.minDocCps;
      const passesTotalCpsGate = totalChangesPerSec >= CFG.minTotalCps;
      const burst = {
        windowStartAt: Timestamp(windowStartSec, 0),
        windowEndAt: Timestamp(windowStartSec + windowSeconds, 0),
        windowSeconds,
        opCount,
        totalOpCount: currentBurstWindowTotal,
        eventShare,
        spreadDisparityEstimate,
        docChangesPerSec,
        totalChangesPerSec,
        passesSpreadGate,
        passesDocCpsGate,
        passesTotalCpsGate,
        qualifies: passesSpreadGate && passesDocCpsGate && passesTotalCpsGate
      };

      if (!row.peakBurstWindow || docChangesPerSec > row.peakBurstWindow.docChangesPerSec) {
        row.peakBurstWindow = burst;
      }
      if (burst.qualifies && (!row.qualifyingBurstWindow || docChangesPerSec > row.qualifyingBurstWindow.docChangesPerSec)) {
        row.qualifyingBurstWindow = burst;
      }
    }
  }

  print("");
  if (watchAllNamespaces) {
    print(`Reading change stream for ALL namespaces from ${new Date(startSec * 1000).toISOString()} (${explicitTimeRange ? "requested interval" : `lookback interval: current=${lookbackCurrentLabel}, default=${lookbackDefaultLabel}`}) ...`);
  } else {
    print(`Reading change stream for namespaces [${watchedNamespaces.join(", ")}] from ${new Date(startSec * 1000).toISOString()} (${explicitTimeRange ? "requested interval" : `lookback interval: current=${lookbackCurrentLabel}, default=${lookbackDefaultLabel}`}) ...`);
  }
  print(`Sample endpoint (exclusive): ${new Date(endSec * 1000).toISOString()}`);
  print("");

  while (true) {
    if (Date.now() > deadline) {
      stopReason = "run-ms-exceeded";
      break;
    }

    const evt = cs.tryNext();
    if (evt === null) {
      if (CFG.idleMs > 0 && Date.now() - lastEventAt > CFG.idleMs) {
        stopReason = "idle-timeout";
        break;
      }
      sleep(50);
      continue;
    }

    lastEventAt = Date.now();
    lastClusterTime = evt.clusterTime;

    if (evt.clusterTime && isTimestampAtOrAfter(evt.clusterTime, endAt)) {
      finalizeBurstWindow(currentBurstWindowIndex);
      stopReason = "caught-up";
      break;
    }
    if (!evt.clusterTime || !isTimestampAtOrAfter(evt.clusterTime, startAt)) continue;
    matchedEventsSeen++;

    if (!evt.ns || !evt.ns.db || !evt.ns.coll) {
      continue;
    }

    if (evt.ns.db === "admin" || evt.ns.db === "config" || evt.ns.db === "local" || evt.ns.coll.startsWith("system.")) {
      continue;
    }

    const opName = opMap[evt.operationType];
    if (!opName) {
      continue;
    }

    const eventSecond = timestampParts(evt.clusterTime).seconds;
    const burstWindowIndex = Math.floor((eventSecond - startSec) / burstWindowSeconds);

    if (currentBurstWindowIndex === null) {
      currentBurstWindowIndex = burstWindowIndex;
    } else if (burstWindowIndex > currentBurstWindowIndex) {
      finalizeBurstWindow(currentBurstWindowIndex);
      currentBurstWindowIndex = burstWindowIndex;
      currentBurstWindowTotal = 0;
      currentBurstWindowCounts = new Map();
    }

    const docId = evt.documentKey && evt.documentKey._id;
    if (docId === undefined || docId === null) {
      continue;
    }

    const ns = `${evt.ns.db}.${evt.ns.coll}`;
    const key = bsonString(docId);

    let nsBucket = perNs[ns];
    if (!nsBucket) {
      nsBucket = { rows: Object.create(null), keys: [] };
      perNs[ns] = nsBucket;
      nsOrder.push(ns);
    }

    let row = nsBucket.rows[key];
    if (!row) {
      if (uniqueDocsTracked >= CFG.maxUniqueDocs) {
        stopReason = "max-unique-docs-reached";
        print(`Stopping early after reaching maxUniqueDocs=${CFG.maxUniqueDocs}. Increase maxUniqueDocs to analyze larger cardinality workloads.`);
        break;
      }

      row = {
        ns,
        docId,
        opCount: 0,
        insert: 0,
        update: 0,
        delete: 0,
        peakBurstWindow: null,
        qualifyingBurstWindow: null
      };
      nsBucket.rows[key] = row;
      nsBucket.keys.push(key);
      uniqueDocsTracked++;
    }

    row.opCount++;
    row[opName]++;
    qualifiedEventsSeen++;
    currentBurstWindowTotal++;
    currentBurstWindowCounts.set(row, (currentBurstWindowCounts.get(row) || 0) + 1);
  }

  cs.close();

  const sampleClosedAt = Date.now();

  print(`Stream closed. Reason: ${stopReason}. Matched events: ${matchedEventsSeen}. Qualified doc events: ${qualifiedEventsSeen}.`);

  const sampleIsPartial = stopReason !== "caught-up";
  const observedWindowSeconds = Math.max((sampleClosedAt - sampleOpenedAt) / 1000, 0);
  const rateWindowSeconds = sampleIsPartial ? null : endSec - startSec;
  const totalChangesPerSec = sampleIsPartial ? null : qualifiedEventsSeen / rateWindowSeconds;

  const allDocsRaw = [];
  for (const ns of nsOrder) {
    const bucket = perNs[ns];
    for (const key of bucket.keys) {
      allDocsRaw.push(bucket.rows[key]);
    }
  }

  const allDocs = qualifiedEventsSeen === 0
    ? []
    : allDocsRaw
        .map((d) => {
          const eventShare = d.opCount / qualifiedEventsSeen;
          const spreadDisparityEstimate = eventShare * sqrtAppliersMinusOne;
          const docChangesPerSec = sampleIsPartial ? null : d.opCount / rateWindowSeconds;
          const passesSpreadGate = spreadDisparityEstimate >= spreadDisparityThreshold;
          const passesDocCpsGate = sampleIsPartial ? null : docChangesPerSec >= CFG.minDocCps;
          const passesTotalCpsGate = sampleIsPartial ? null : totalChangesPerSec >= CFG.minTotalCps;
          const qualifies = sampleIsPartial ? null : passesSpreadGate && passesDocCpsGate && passesTotalCpsGate;

          return {
            ns: d.ns,
            docId: d.docId,
            docChanges: d.opCount,
            opCount: d.opCount,
            insert: d.insert,
            update: d.update,
            delete: d.delete,
            eventShare,
            spreadDisparityEstimate,
            docChangesPerSec,
            totalChangesPerSec,
            passesSpreadGate,
            passesDocCpsGate,
            passesTotalCpsGate,
            qualifies,
            peakBurstWindow: d.peakBurstWindow,
            qualifyingBurstWindow: d.qualifyingBurstWindow
          };
        })
        .sort((a, b) => {
          if (b.opCount !== a.opCount) return b.opCount - a.opCount;
          return a.ns.localeCompare(b.ns);
        });

  const hotDocuments = allDocs.filter((d) => d.qualifies);
  const burstHotDocuments = allDocs
    .filter((d) => d.qualifyingBurstWindow)
    .sort((a, b) => b.qualifyingBurstWindow.docChangesPerSec - a.qualifyingBurstWindow.docChangesPerSec);
  const displayedBurstHotDocuments = burstHotDocuments.slice(0, CFG.maxBurstCandidates);
  const omittedBurstCandidateCount = burstHotDocuments.length - displayedBurstHotDocuments.length;
  const topBurstDocuments = allDocs
    .filter((d) => d.peakBurstWindow)
    .sort((a, b) => b.peakBurstWindow.docChangesPerSec - a.peakBurstWindow.docChangesPerSec)
    .slice(0, CFG.topDocCountForProxy);
  const burstSummary = completeBurstWindowsAnalyzed === 0
    ? "No complete burst windows were analyzed."
    : burstHotDocuments.length === 0
      ? `No documents passed all burst gates in ${completeBurstWindowsAnalyzed} complete window(s).`
      : `${burstHotDocuments.length} document(s) passed all burst gates in at least one complete window.`;

  const topDocCountForProxy = CFG.topDocCountForProxy;
  const topDocuments = allDocs.slice(0, topDocCountForProxy);
  const topCombinedOps = topDocuments.reduce((sum, d) => sum + d.opCount, 0);
  const topCombinedShare = qualifiedEventsSeen === 0 ? 0 : topCombinedOps / qualifiedEventsSeen;
  const topCombinedSingleDocSpreadEquivalent = topCombinedShare * sqrtAppliersMinusOne;
  const cappedByMaxUniqueDocs = stopReason === "max-unique-docs-reached";
  const analysisStatus = sampleIsPartial ? "inconclusive" : "complete";
  const warnings = cappedByMaxUniqueDocs
    ? ["Incomplete analysis: maxUniqueDocs reached. Later activity was not analyzed, so hot documents may have been missed. Rerun with fewer namespaces or increase maxUniqueDocs if memory permits."]
    : sampleIsPartial
      ? ["Incomplete analysis: the stream did not reach the caught-up watermark. Hot documents may have been missed."]
      : [];
  if (sampleIsPartial) {
    warnings.push("Workload CPS and CPS gates were not evaluated for this partial sample. Counts and shares describe only the observed activity.");
    warnings.push("Burst results include only event-time windows known to be complete; the trailing incomplete window is excluded.");
    if (!cappedByMaxUniqueDocs) {
      warnings.push("A quiet or filtered stream may already have been fully read, but completion cannot be confirmed without a matching event at the sample endpoint.");
    }
  }
  const hotDocumentsSummary = sampleIsPartial
    ? "Hot-document qualification was not evaluated: workload CPS is unavailable for this partial sample. Inspect the top documents for observed counts and shares."
    : hotDocuments.length === 0
      ? "No hot documents detected in the sample."
      : `${hotDocuments.length} hot document(s) detected in the sample.`;
  const partialHeadingSuffix = sampleIsPartial ? " (Partial Sample)" : "";

  const output = {
    generatedAt: new Date().toISOString(),
    namespacesRequested: watchAllNamespaces ? "ALL" : watchedNamespaces,
    timeRangeMode: explicitTimeRange ? "explicit" : "lookback",
    lookbackMs: intervalSeconds * 1000,
    appliers: CFG.appliers,
    spreadDisparityThreshold,
    spreadThreshold: spreadDisparityThreshold,
    minShareRequired,
    minDocCps: CFG.minDocCps,
    minTotalCps: CFG.minTotalCps,
    burstWindowMs: burstWindowSeconds * 1000,
    maxUniqueDocs: CFG.maxUniqueDocs,
    matchedEventsSeen,
    qualifiedEventsSeen,
    uniqueDocsTracked,
    sampleIsPartial,
    ratesAvailable: !sampleIsPartial,
    sampleStartAt: startAt,
    sampleEndAt: endAt,
    analysisStatus,
    warnings,
    hotDocumentsSummary,
    rateWindowSeconds,
    observedWindowSeconds,
    totalChangesPerSec,
    stopReason,
    cappedByMaxUniqueDocs,
    lastClusterTime,
    burstAnalysis: {
      windowMs: burstWindowSeconds * 1000,
      completeWindowsAnalyzed: completeBurstWindowsAnalyzed,
      summary: burstSummary,
      candidateDisplayLimit: CFG.maxBurstCandidates,
      candidateRowsDisplayed: displayedBurstHotDocuments.length,
      candidateRowsOmitted: omittedBurstCandidateCount,
      topDocuments: topBurstDocuments,
      hotDocuments: burstHotDocuments
    },
    topCombined: {
      requestedDocCount: topDocCountForProxy,
      effectiveDocCount: topDocuments.length,
      opCount: topCombinedOps,
      share: topCombinedShare,
      singleDocSpreadEquivalent: topCombinedSingleDocSpreadEquivalent,
      documents: topDocuments
    },
    hotDocuments
  };

  function toFixedNumber(v, digits) {
    return v === null ? "N/A" : Number(v).toFixed(digits);
  }

  function toPct(v, digits) {
    return `${(v * 100).toFixed(digits)}%`;
  }

  function mdEscape(v) {
    return String(v).replace(/\|/g, "\\|");
  }

  function buildMarkdownTableRows(docs) {
    return docs
      .map((d, i) => {
        return `| ${i + 1} | ${d.opCount} | ${d.insert} | ${d.delete} | ${d.update} | ${toPct(d.eventShare, 2)} | ${toFixedNumber(d.spreadDisparityEstimate, 3)} | ${toFixedNumber(d.docChangesPerSec, 3)} | ${toFixedNumber(d.totalChangesPerSec, 3)} | ${mdEscape(d.ns)} | ${mdEscape(bsonString(d.docId))} |`;
      })
      .join("\n");
  }

  function buildBurstMarkdownTableRows(docs, burstField) {
    return docs
      .map((d, i) => {
        const burst = d[burstField];
        return `| ${i + 1} | ${new Date(timestampParts(burst.windowStartAt).seconds * 1000).toISOString()} | ${burst.opCount} | ${toPct(burst.eventShare, 2)} | ${toFixedNumber(burst.spreadDisparityEstimate, 3)} | ${toFixedNumber(burst.docChangesPerSec, 3)} | ${toFixedNumber(burst.totalChangesPerSec, 3)} | ${mdEscape(d.ns)} | ${mdEscape(bsonString(d.docId))} |`;
      })
      .join("\n");
  }

  function buildMarkdownReport() {
    const scopeValue = watchAllNamespaces ? "ALL" : watchedNamespaces.join(", ");
    const topTableRows = buildMarkdownTableRows(topDocuments);
    const hotTableRows = buildMarkdownTableRows(hotDocuments);
    const burstTableRows = buildBurstMarkdownTableRows(topBurstDocuments, "peakBurstWindow");
    const burstHotTableRows = buildBurstMarkdownTableRows(displayedBurstHotDocuments, "qualifyingBurstWindow");
    const topTable = topTableRows || "| - | - | - | - | - | - | - | - | - | - | - |";
    const hotTable = hotTableRows || "| - | - | - | - | - | - | - | - | - | - | - |";

    return [
      "# Hot Doc Spread Check Report",
      "",
      `Generated at: ${output.generatedAt}`,
      `Namespaces requested: ${scopeValue}`,
      `Stop reason: ${stopReason}`,
      "",
      ...warnings.flatMap((warning) => [`> **WARNING: ${warning}**`, ""]),
      "## Summary",
      "",
      `- Analysis status: ${analysisStatus}`,
      `- Sample completeness: ${sampleIsPartial ? "partial" : "complete"}`,
      `- Sample interval: [${new Date(startSec * 1000).toISOString()}, ${new Date(endSec * 1000).toISOString()})`,
      `- Rate window seconds: ${toFixedNumber(rateWindowSeconds, 3)}`,
      `- Reading duration seconds: ${toFixedNumber(observedWindowSeconds, 3)}`,
      `- Appliers: ${CFG.appliers}`,
      `- SpreadDisparityThreshold: ${spreadDisparityThreshold}`,
      `- RequiredShare(single-doc): ${toPct(minShareRequired, 2)}`,
      `- MinDocCps: ${CFG.minDocCps}  MinTotalCps: ${CFG.minTotalCps} (Cps means changes per second)`,
      `- Burst window: ${burstWindowSeconds}s  Complete event windows analyzed: ${completeBurstWindowsAnalyzed}`,
      `- Unique docs tracked: ${uniqueDocsTracked} / ${CFG.maxUniqueDocs}`,
      `- Qualified changes in window: ${qualifiedEventsSeen}`,
      `- Total changes/sec: ${toFixedNumber(totalChangesPerSec, 3)}`,
      `- Top-${topDocCountForProxy} combined ops: ${topCombinedOps}`,
      `- Top-${topDocCountForProxy} combined share: ${toPct(topCombinedShare, 2)}`,
      `- Top-${topDocCountForProxy} single-doc spread equivalent: ${toFixedNumber(topCombinedSingleDocSpreadEquivalent, 3)}`,
      "",
      `## Top-${topDocCountForProxy} Documents (By Op Count)${partialHeadingSuffix}`,
      "",
      "| rank | opCount | insert | delete | update | share% | spreadDisp | docCps | totalCps | namespace | _id |",
      "| ---: | ------: | -----: | -----: | -----: | -----: | ---------: | -----: | -------: | :-------- | :-- |",
      topTable,
      "",
      `## Hot Documents${partialHeadingSuffix}`,
      "",
      hotDocumentsSummary,
      "",
      "| rank | opCount | insert | delete | update | share% | spreadDisp | docCps | totalCps | namespace | _id |",
      "| ---: | ------: | -----: | -----: | -----: | -----: | ---------: | -----: | -------: | :-------- | :-- |",
      hotTable,
      "",
      `## Peak Document Bursts (${burstWindowSeconds}s Windows)`,
      "",
      "| rank | window start | opCount | share% | spreadDisp | docCps | totalCps | namespace | _id |",
      "| ---: | :----------- | ------: | -----: | ---------: | -----: | -------: | :-------- | :-- |",
      burstTableRows || "| - | - | - | - | - | - | - | - | - |",
      "",
      "## Burst Candidates (Passed All Gates)",
      "",
      "| rank | window start | opCount | share% | spreadDisp | docCps | totalCps | namespace | _id |",
      "| ---: | :----------- | ------: | -----: | ---------: | -----: | -------: | :-------- | :-- |",
      burstHotTableRows || "| - | - | - | - | - | - | - | - | - |",
      ...(omittedBurstCandidateCount > 0 ? [`${omittedBurstCandidateCount} additional burst candidate(s) omitted (maxBurstCandidates=${CFG.maxBurstCandidates}).`] : []),
      ""
    ].join("\n");
  }

  function deriveOutputPath(format) {
    if (format === "json") {
      return CFG.outputFile;
    }
    if (format === "markdown") {
      if (CFG.outputFile === DEFAULTS.outputFile) {
        return "hot-doc-spread-check.md";
      }
      return CFG.outputFile;
    }
    return null;
  }

  if (outputFormat === "json" || outputFormat === "both") {
    const jsonPath = outputFormat === "json" ? deriveOutputPath("json") : DEFAULTS.outputFile;
    fs.writeFileSync(
      jsonPath,
      EJSON.stringify(output, null, 2, { relaxed: false })
    );
    print(`Wrote JSON results to ${jsonPath}`);
  }

  if (outputFormat === "markdown" || outputFormat === "both") {
    const markdownPath = outputFormat === "markdown" ? deriveOutputPath("markdown") : "hot-doc-spread-check.md";
    fs.writeFileSync(markdownPath, buildMarkdownReport());
    print(`Wrote Markdown results to ${markdownPath}`);
  }

  print("");
  print("=".repeat(112));
  print(`TOP-${topDocCountForProxy} COMBINED SHARE`);
  print("=".repeat(112));
  print(`Appliers: ${CFG.appliers}  SpreadDisparityThreshold: ${spreadDisparityThreshold}  RequiredShare(single-doc): ${(minShareRequired * 100).toFixed(2)}%`);
  print(`MinDocCps: ${CFG.minDocCps}  MinTotalCps: ${CFG.minTotalCps} (Cps means changes per second)`);
  print(`Burst window: ${burstWindowSeconds}s  Complete event windows analyzed: ${completeBurstWindowsAnalyzed}`);
  print(`Unique docs tracked: ${uniqueDocsTracked} / ${CFG.maxUniqueDocs}`);
  print(`Qualified changes in window: ${qualifiedEventsSeen}  Total changes/sec: ${toFixedNumber(totalChangesPerSec, 3)}`);
  print(`Top-${topDocCountForProxy} combined ops   : ${topCombinedOps}`);
  print(`Top-${topDocCountForProxy} combined share : ${(topCombinedShare * 100).toFixed(2)}%`);
  print(`Top-${topDocCountForProxy} single-doc spread equivalent : ${topCombinedSingleDocSpreadEquivalent.toFixed(3)}`);
  print(`Sample completeness: ${sampleIsPartial ? "partial" : "complete"}  Rate window seconds: ${toFixedNumber(rateWindowSeconds, 3)}  Reading duration seconds: ${toFixedNumber(observedWindowSeconds, 3)}`);
  print(`Analysis status: ${analysisStatus}`);
  warnings.forEach((warning) => print(`WARNING: ${warning}`));

  print("");
  print("=".repeat(112));
  print(`TOP-${topDocCountForProxy} DOCUMENTS (BY OP COUNT)${partialHeadingSuffix}`);
  print("=".repeat(112));
  const col = {
    rank: 4,
    opCount: 7,
    insert: 6,
    delete: 6,
    update: 6,
    sharePct: 7,
    spreadDisp: 10,
    docCps: 7,
    totalCps: 8,
    namespace: 22
  };

  function makeTableHeader() {
    return (
      `${"rank".padStart(col.rank)}  ` +
      `${"opCount".padStart(col.opCount)}  ` +
      `${"insert".padStart(col.insert)}  ` +
      `${"delete".padStart(col.delete)}  ` +
      `${"update".padStart(col.update)}  ` +
      `${"share%".padStart(col.sharePct)}  ` +
      `${"spreadDisp".padStart(col.spreadDisp)}  ` +
      `${"docCps".padStart(col.docCps)}  ` +
      `${"totalCps".padStart(col.totalCps)}  ` +
      `${"namespace".padEnd(col.namespace)}  _id`
    );
  }

  function makeTableRow(d, rank) {
    return (
      `${String(rank).padStart(col.rank)}  ` +
      `${String(d.opCount).padStart(col.opCount)}  ` +
      `${String(d.insert).padStart(col.insert)}  ` +
      `${String(d.delete).padStart(col.delete)}  ` +
      `${String(d.update).padStart(col.update)}  ` +
      `${(d.eventShare * 100).toFixed(2).padStart(col.sharePct)}  ` +
      `${d.spreadDisparityEstimate.toFixed(3).padStart(col.spreadDisp)}  ` +
      `${toFixedNumber(d.docChangesPerSec, 3).padStart(col.docCps)}  ` +
      `${toFixedNumber(d.totalChangesPerSec, 3).padStart(col.totalCps)}  ` +
      `${d.ns.padEnd(col.namespace)}  ` +
      `${bsonString(d.docId)}`
    );
  }

  print(makeTableHeader());

  topDocuments.forEach((d, i) => {
    print(makeTableRow(d, i + 1));
  });

  if (topDocuments.length === 0) {
    print("No documents found in this sample.");
  }

  print("");

  print("");
  print("=".repeat(112));
  print(`HOT DOCUMENTS${partialHeadingSuffix}`);
  print("=".repeat(112));
  print(hotDocumentsSummary);
  print(makeTableHeader());

  hotDocuments.forEach((d, i) => {
    print(makeTableRow(d, i + 1));
  });

  print("");
  print("");
  print("=".repeat(112));
  print(`PEAK DOCUMENT BURSTS (${burstWindowSeconds}s WINDOWS)`);
  print("=".repeat(112));
  printBurstTable(topBurstDocuments, "peakBurstWindow");
  if (topBurstDocuments.length === 0) print("No complete burst windows to report.");
  print("");
  print("BURST CANDIDATES (PASSED ALL GATES)");
  function printBurstTable(docs, burstField) {
    const columns = [
      { header: "rank", align: "right", value: (_doc, _burst, rank) => String(rank) },
      { header: "window start", align: "left", value: (_doc, burst) => new Date(timestampParts(burst.windowStartAt).seconds * 1000).toISOString() },
      { header: "opCount", align: "right", value: (_doc, burst) => String(burst.opCount) },
      { header: "share%", align: "right", value: (_doc, burst) => (burst.eventShare * 100).toFixed(2) },
      { header: "spreadDisp", align: "right", value: (_doc, burst) => burst.spreadDisparityEstimate.toFixed(3) },
      { header: "docCps", align: "right", value: (_doc, burst) => burst.docChangesPerSec.toFixed(3) },
      { header: "totalCps", align: "right", value: (_doc, burst) => burst.totalChangesPerSec.toFixed(3) },
      { header: "namespace", align: "left", minWidth: 22, value: (doc) => doc.ns },
      { header: "_id", align: "left", value: (doc) => bsonString(doc.docId) }
    ];
    const rows = docs.map((doc, index) => {
      const burst = doc[burstField];
      return columns.map((column) => column.value(doc, burst, index + 1));
    });
    const widths = columns.map((column) => Math.max(column.header.length, column.minWidth || 0));
    for (const row of rows) {
      for (let index = 0; index < row.length; index++) {
        widths[index] = Math.max(widths[index], row[index].length);
      }
    }
    const formatRow = (values) => values.map((value, index) =>
      columns[index].align === "right" ? value.padStart(widths[index]) : value.padEnd(widths[index])
    ).join("  ");

    print(formatRow(columns.map((column) => column.header)));
    rows.forEach((row) => print(formatRow(row)));
  }

  printBurstTable(displayedBurstHotDocuments, "qualifyingBurstWindow");
  if (burstHotDocuments.length === 0) print("No documents passed all burst gates.");
  if (omittedBurstCandidateCount > 0) {
    print(`${omittedBurstCandidateCount} additional burst candidate(s) omitted (maxBurstCandidates=${CFG.maxBurstCandidates}).`);
  }
  print("");
})();
