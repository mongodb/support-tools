
/**
 * @file ca-118-check.js
 * This file implements a check for determining a sharded cluster's
 * susceptibility to CA-118. It returns a list of namespaces that
 * are potentially impacted. To run this check, start a Mongo shell connected to the config
 * server and enter
 *
 *   load("<path>/ca-118-check.js")
 *   use config
 *   nslist = isImpactedByCA118(db)
 *
 * nslist will contain a list of namespaces potentially impacted, or an empty
 * list if no namespaces are impacted. isImpactedByCA118() will also print "may
 * be impacted" if there are namespaces susceptible to CA-118 or "not impacted"
 * if no namespaces are impacted.
 */

const ImpactedIntervalMs = 60000 * 30;  // 30 minutes

/**
 * For a given ns, this object stores a set of resharding-finish times and
 * impacted chunk migration times.
 * @param  finish_time  [optional] resharding finish time
 */
class _NsEvents {
  constructor(finish_time, diffShardCount) {
    // an associative array indexed by resharding-finish times of arrays
    // of chunk migration times.
    this._chunkMigrationTimes = {};
    // an associative array indexed by resharding-finish times of the
    // change-in-shard-count. Change-in-shard-count tracks how the shard
    // count has changed since the beginning of config.changelog.
    this._diffShardCount = {};
    this._currentCommittingTime;
    if (finish_time) {
      this.addReshardCommittingTime(finish_time, diffShardCount);
    }
  }

  getCurrentFinishTime() {
    return this._currentCommittingTime;
  }

  isImpacted() {
    return Object.keys(this._chunkMigrationTimes)
        .reduce(
            (accum, time) => Boolean(this._chunkMigrationTimes[time]), false);
  }

  addReshardCommittingTime(time, shardDiff) {
    this._diffShardCount[time] = shardDiff;
    this._currentCommittingTime = time;
  }

  reshardAborting() {
    if (this._currentCommittingTime &&
      this._chunkMigrationTimes[this._currentCommittingTime]) {
      // Preceeding committing event did not have an impacting chunk migration.
      this._chunkMigrationTimes[this._currentCommittingTime] = null;
      this._currentCommittingTime = null;
    }
  }

  addChunkMigrationTime(time) {
    if (this._currentCommittingTime) {
      if (!Object.keys(this._chunkMigrationTimes).includes(this._currentCommittingTime)) {
        this._chunkMigrationTimes[this._currentCommittingTime] = new Array;
      }
      this._chunkMigrationTimes[this._currentCommittingTime].push(time);
    }
  }

  /**
   * setStartingNumShards() omits impacting moveChunk events for resharding
   * operations where the number of shards is less than three.
   * While config.changelog is being read, we only know the number of shards at
   * the end of the changelog history; we can only determine the number of
   * shards at the beginning of the changelog history by reading the addShard
   * and removeShard events in the changelog. Thus, this function is called
   * after processing the changelog history to cancel the impact of reshard
   * operations now that the actual number of shards is known.
   * @param startingNumShards number of shards at the beginning of changelog.
   */
  setStartingNumShards(startingNumShards) {
    Object.keys(this._diffShardCount).forEach((time) => {
      const numShards = startingNumShards + this._diffShardCount[time];
      if (numShards < 3 && Object.keys(this._chunkMigrationTimes).includes(time)) {
        // This resharding operation is not impacted.
        this._chunkMigrationTimes[time] = null;
      }
    });
  }

  debugString(prefix = '') {
    let retval = "";
    const times = this._chunkMigrationTimes;
    Object.keys(this._chunkMigrationTimes).forEach((reshardTime) => {
      if (this._chunkMigrationTimes[reshardTime]) {
        retval = retval + prefix + `reshard commit at:    ${reshardTime}\n`;
        this._chunkMigrationTimes[reshardTime].forEach(function(migrationTime) {
          retval = retval + prefix + `  chunk migration at: ${migrationTime}\n`;
        });
      }
    });
    return retval;
  }
}

/**
 * isImpactedByCA118() checks a sharded cluster for susceptibility to CA-118.
 * The function returns a list of namespaces where the history of
 * reshards and chunk migrations indicates susceptibility to CA-118; returns
 * empty list if there is no susceptibility. The function also prints the
 * timestamp indicating the start of its analysis, and "may be impacted" if
 * returning a non-empty list of namespaces or "not impacted" if returning an
 * empty list.
 * @param db         config database of the config server.
 * @param timestamps if true, prints resharding and chunk migration times and
 *                   namespaces that demonstrate susceptibility.
 * @param readPref   string indicating read preference mode.
 * @return list of namespaces possibly impacted by CA-118.
 */
function isImpactedByCA118(db, timestamps = false, readPref = "secondaryPreferred") {
  if (!_prologue(db, readPref)) {
    return null;
  }

  const docs = _getChangelogEvents(db.changelog, readPref);

  const endingNumShards = db.shards.countDocuments({});
  const nsEvents = _processEvents(docs, endingNumShards);
  const nsImpacted = _namespacesImpacted(nsEvents, timestamps);

  return nsImpacted;
}

function _prologue(db, readPref) {
  print('** CA-118 susceptibility check **');
  const caution =
      'CAUTION: This script does not determine whether there may have been an\n\
         impact due to CA-118 prior to this time for this cluster.';
  const advice =
      'NOTE 1:  Determining CA-118 susceptibility beyond the history of\n\
         config.changelog may be possible by examining mongod\n\
         server logs.\n' + 
      'NOTE 2:  This script only determines whether a potentially impacting chunk\n\
         migration occurred after a reshard operation. In addition to this\n\
         condition, impact due to CA-118 requires a retryable write during\n\
         resharding that is subsequently retried; this script is not able to\n\
         check for the presence of retryable write operations.\n' +
      'For more information: https://jira.mongodb.org/browse/SERVER-89529.';
  const check_db =
    'Ensure that you are connected to the config database on the config server.';

  if (db.getName() !== "config") {
    print("error: db name is not 'config'.");
    print(check_db);
    return false;
  }
  const collOk = ['changelog', 'shards'].reduce((accum, collName) => {
    if (!(db.getCollectionNames().includes(collName))) {
      print(`error: db does not have collection ${collName}`);
      return false;
    } else {
      return accum;
    }
  }, true);
  if (!collOk) {
    print(check_db);
    return false;
  }

  const first = db.changelog.findOne(
      {}, {time: 1},
      {sort: {time: 1}, readPreference: readPref, allowDiskUse: true});
  if (first) {
    print(`CA-118 analysis begins at ${first.time}`);
    print(caution);
    print(advice);
  } else {
    print("CA-118 analysis has no events to check (config.changelog is empty).");
    print(advice);
    return false;
  }
  return true;
}

/**
 * _getChangeLogEvents() returns cursor to documents from the collection needed
 * for CA-118 susceptibility check. The documents are sorted ascending by time
 * field.
 * @param  collection Mongo shell collection, should be config.changelog.
 * @returns cursor over config.changelog documents
 */
function _getChangelogEvents(collection, readPref) {
  // We look for resharding 'committing' state instead of 'done' state
  // because v5.x and v6.x do not log the 'done' state.
  const query = {
    $or: [
      {what: 'addShard'},
      {what: 'removeShard'},
      {
        $and: [
          {what: 'resharding.coordinator.transition'},
          {
            $or: [
              {'details.newState': 'aborting'},
              {'details.newState': 'committing'},
            ]
          },
        ],
      },
      {what: 'moveChunk.commit'},
    ],
  };
  const project = {_id: 1, ns: 1, time: 1, what: 1, details: 1};
  return collection.find(query, project)
      .readPref(readPref)
      .sort({time: 1})
      .allowDiskUse();
}

/**
 * _processEvents() returns an array of NsEvents processed from the input.
 * @param  docs Documents from config.changelog.
 * @param  endingNumShards Current number of shards (at the end of changelog).
 * @returns array of NsEvents indexed by namespace.
 */
function _processEvents(docs, endingNumShards) {
  const nsEvents = {};

  let diffShardCount = 0;

  docs.forEach(function(doc) {

    // Reshard operations can transition from other states to 'aborting',
    // from other states to 'committing', and  from 'committing' to 'aborting'.
    // Multiple reshard operations cannot overlap each other. We do not have an
    // event showing that a reshard operation is 'done'; however, chunk
    // migrations cannot overlap with reshard operations, so the presence of a
    // chunk migration indicates that a preceding reshard operation either
    // aborted or finished committing. The following logic shows that we do not
    // need to track the transitions of multiple resharding operations.
    //
    // There are seven combinations of 'aborting' and 'committing' transitions
    // and chunk migrations that are within the interval of the previous reshard
    // transition:
    // 1. reshard operation 1 aborting
    //    chunk migration within interval
    //    --> no impact
    // 2. reshard operation 1 committing
    //    chunk migration within interval
    //    --> potential impact
    // 3. reshard operation 1 aborting
    //    reshard operation 2 aborting
    //    chunk migration within interval
    //    --> no impact
    // 4. reshard operation 1 committing
    //    reshard operation 2 committing
    //    chunk migration within interval
    //    --> potential impact
    // 5. reshard operation 1 committing
    //    reshard operation 1 aborting
    //    chunk migration within interval
    //    --> no impact
    // 6. reshard operation 1 committing
    //    reshard operation 2 aborting
    //    chunk migration within interval
    //    --> no impact
    // 7. reshard operation 1 aborting
    //    reshard operation 2 committing
    //    chunk migration within interval
    //    --> potential impact
    //
    // Other combinations are sequential combinations of the above seven
    // possibilities. From the above, it follows that there is potential impact
    // iff chunk migration occurs within the interval following a 'committing'
    // event without any intervening 'aborting' event. For any 'aborting' event
    // that is preceded by a 'committing' event, if there is no intervening
    // chunk migration within interval (that is, no impact), then the preceding
    // 'committing' event will never cause an impact. Therefore, we only need to
    // track whether a 'committing' event has a succeeding chunk migration
    // within interval; we do not need to track individual reshard operation
    // id's.

    if (doc.what === 'addShard') {
      diffShardCount += 1;
    } else if (doc.what === 'removeShard') {
      diffShardCount += -1;
    } else if (doc.what === 'resharding.coordinator.transition') {
      if (doc.details.newState === 'aborting') {
        if (Object.keys(nsEvents).includes(doc.ns)) {
          nsEvents[doc.ns].reshardAborting();
        }
      } else if (doc.details.newState === 'committing') {
        if (!Object.keys(nsEvents).includes(doc.ns)) {
          nsEvents[doc.ns] = new _NsEvents(doc.time, diffShardCount);
        } else {
          nsEvents[doc.ns].addReshardCommittingTime(doc.time, diffShardCount);
        }
      }
    } else if (doc.what === 'moveChunk.commit') {
      if (Object.keys(nsEvents).includes(doc.ns)) {
        const reshardTime = nsEvents[doc.ns].getCurrentFinishTime();
        if (reshardTime && doc.time - reshardTime <= ImpactedIntervalMs) {
          nsEvents[doc.ns].addChunkMigrationTime(doc.time);
        }
      }
    }
  });

  Object.keys(nsEvents).forEach(function(ns) {
    nsEvents[ns].setStartingNumShards(endingNumShards - diffShardCount);
  });

  return nsEvents;
}

/**
 * _namespacesImpacted returns the namespaces susceptible to CA-118 using the
 * events in the input.
 * @param nsEvents array of NsEvents indexed by namespace.
 * @returns list of namespaces potentially impacted by CA-118.
 */
function _namespacesImpacted(nsEvents, timestamps = false) {
	let retval = new Array;
        Object.keys(nsEvents).forEach((ns) => {
          if (!retval.includes(ns) && nsEvents[ns].isImpacted()) {
            if (timestamps) {
              print(`namespace: ${ns}:`);
              print(nsEvents[ns].debugString("  "));
            }
            retval.push(ns);
          }
        });

        if (retval.length > 0) {
          print('result: may be impacted');
          print('namespaces: ', retval);
        } else {
          print('result: not impacted');
        }

        return retval;
}

/**
 * Tests business logic
 * @param docs Documents from config.changelog
 * @return list of potentially impacted namespaces
 */
function _testCA118(docs, endingNumShards, timestamps = false) {
	return _namespacesImpacted(_processEvents(docs, endingNumShards), timestamps);
}
