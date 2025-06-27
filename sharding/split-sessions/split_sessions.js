/*
 *	This script is meant to be executed on a mongos instance of a MongoDB
 *	sharded cluster.
 *
 *	Sessions records are small in size, so usually the sessions collection
 *	doesn't get automatically splitted by the auto-splitter and thus it is
 *	not balanced automatically. This can cause an high load on the primary
 *	shard of the sessions collection.
 *
 *	This script splits and distributes the `config.system.sessions`
 *	collection information among all the shards in the cluster. It creates
 *	and move one chunk to every shard in the cluster.
 */

// Number of chars of the first two groups (most-significant) in UUID string
var UUIDHeadChars = 12;
// Max number of integers that can be represented using
var UUIDHeadMax = Math.pow(16, UUIDHeadChars);

/*
 * Generate an UUID that has @num encoded in the first 12 chars
 */
function UUIDFromInt(num) {
    assert(num < UUIDHeadMax);
    // Format num as hexadecimal string with enough left-zero-padding
    // to reach UUIDHeadChars
    head =
	(('0'.repeat(UUIDHeadChars)) + num.toString(16)).substr(-UUIDHeadChars);
    assert.eq(head.length, UUIDHeadChars);
    // return UUID(HHHHHHHH-HHHH-0000-0000-000000000000)
    return UUID(
	head.substr(0, 8) + '-' + head.substr(8) + '-' +
	'0'.repeat(4) + '-' +
	'0'.repeat(4) + '-' +
	'0'.repeat(12));
}

/*
 * Generate split points to partition a UUID space in
 * @numChunks of equally-sized chunks.
 */
function genUUIDSplitPoints(numChunks) {
    var splitPoints = [];
    var gap = Math.round(UUIDHeadMax / numChunks);
    var currHead = 0;
    for (var i = 0; i < (numChunks - 1); i++) {
	currHead += gap;
	splitPoints.push(UUIDFromInt(currHead));
    }
    return splitPoints;
}

function chunkInfos(ns) {
    var s = '';
    confDB.chunks.find({ns: ns}).sort({ns: 1, min: 1}).forEach(function(z) {
	s += ' ' + z._id + '  ' + z.shard + '\n\tmin: ' + tojson(z.min) +
	    '\n\tmax: ' + tojson(z.max) + '\n';
    });

    return s;
}

var confDB = db.getSiblingDB('config');
var sessNS = 'config.system.sessions';
// Ensure session collection is sharded
assert.eq(
    true,
    confDB.system.sessions.stats().sharded,
    'Sessions collection is not sharded');
// Ensure no split have been done so far
assert.eq(
    1, confDB.chunks.count({ns: sessNS}),
    'Sessions collection has been already splitted. ' +
	'There are more then one chunks already');

sh.stopBalancer();

var shards = confDB.shards.find().toArray();
var splitPoints = genUUIDSplitPoints(shards.length);
assert.eq(splitPoints.length, shards.length - 1);

// Split collection
for (var i = 0; i < splitPoints.length; i++) {
    var splitPt = {_id: {id: splitPoints[i]}};
    assert.commandWorked(sh.splitAt(sessNS, splitPt));
}

// Distribute one chunk to every shard
for (var i = 0; i < splitPoints.length; i++) {
    var splitPt = {_id: {id: splitPoints[i]}};
    assert.commandWorked(sh.moveChunk(sessNS, splitPt, shards[i + 1]._id));
}

sh.startBalancer();

print('\n### Chunks info for \'config.system.sesssions\' collection\n')
print(chunkInfos(sessNS));
