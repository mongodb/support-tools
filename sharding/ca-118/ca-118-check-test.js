
load("/home/ubuntu/support-tools/ca-118/ca-118-check.js");

const testCases = [
  // cases of not impacted:
  {
    title: 'no events',
    endingNumShards: 3,
    expectedNs: [],
    docs: [],
  },
  {
    title: 'moveChunk, no resharding',
    endingNumShards: 3,
    expectedNs: [],
    docs: [
      {
        '_id': 1,
        'time': new Date('2025-01-01T00:00:00.000Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_no_reshard',
        'details': {},
      },
    ],
  },
  {
    title: 'resharding, no moveChunk',
    endingNumShards: 3,
    expectedNs: [],
    docs: [
      {
        '_id': 1,
        'time': new Date('2025-01-01T00:00:00.001Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_not_impacted',
        'details': {'newState': 'committing'},
      },
    ],
  },
  {
    title: 'resharding with less than 3 shards, moveChunk',
    endingNumShards: 2,
    expectedNs: [],
    docs: [
      {
        '_id': 1,
        'time': new Date('2025-01-01T00:00:00.001Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_not_impacted',
        'details': {'newState': 'committing'},
      },
      {
        '_id': 2,
        'time': new Date('2025-01-01T00:00:01.000Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_not_impacted',
        'details': {},
      },
    ],
  },
  {
    title: 'addShard, resharding with less than 3 shards, moveChunk',
    endingNumShards: 2,
    expectedNs: [],
    docs: [
      {
        '_id': 1,
        'time': new Date('2025-01-01T00:00:00.001Z'),
        'what': 'addShard',
      },
      {
        '_id': 2,
        'time': new Date('2025-01-01T00:00:01.001Z'),
        'what': 'addShard',
      },
      {
        '_id': 3,
        'time': new Date('2025-01-01T00:01:00.000Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_not_impacted',
        'details': {'newState': 'committing'},
      },
      {
        '_id': 4,
        'time': new Date('2025-01-01T00:02:00.000Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_not_impacted',
        'details': {},
      },
    ],
  },
  {
    title: 'addShard, removeShard, resharding with less than 3 shards, moveChunk',
    endingNumShards: 2,
    expectedNs: [],
    docs: [
      {
        '_id': 1,
        'time': new Date('2025-01-01T00:00:00.001Z'),
        'what': 'addShard',
      },
      {
        '_id': 2,
        'time': new Date('2025-01-01T00:00:01.001Z'),
        'what': 'addShard',
      },
      {
        '_id': 3,
        'time': new Date('2025-01-01T00:00:02.001Z'),
        'what': 'addShard',
      },
      {
        '_id': 4,
        'time': new Date('2025-01-01T00:00:03.001Z'),
        'what': 'removeShard',
      },
      {
        '_id': 5,
        'time': new Date('2025-01-01T00:01:00.000Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_not_impacted',
        'details': {'newState': 'committing'},
      },
      {
        '_id': 6,
        'time': new Date('2025-01-01T00:02:00.000Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_not_impacted',
        'details': {},
      },
    ],
  },
  {
    title: 'moveChunk, then resharding',
    endingNumShards: 3,
    expectedNs: [],
    docs: [
      {
        '_id': 1,
        'time': new Date('2025-01-01T00:00:00.000Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_not_impacted',
        'details': {},
      },
      {
        '_id': 2,
        'time': new Date('2025-01-01T00:00:00.001Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_not_impacted',
        'details': {'newState': 'committing'},
      },
    ],
  },
  {
    title: 'resharding, then moveChunk outside of interval',
    endingNumShards: 3,
    expectedNs: [],
    docs: [
      {
        '_id': 1,
        'time': new Date('2025-01-01T00:00:00.000Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_not_impacted',
        'details': {'newState': 'committing'},
      },
      {
        '_id': 2,
        'time': new Date('2025-01-01T00:30:00.001Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_not_impacted',
        'details': {},
      },
    ],
  },
  {
    title: 'resharding, then moveChunk in other collection',
    endingNumShards: 3,
    expectedNs: [],
    docs: [
      {
        '_id': 1,
        'time': new Date('2025-01-01T00:00:00.000Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_not_impacted',
        'details': {'newState': 'committing'},
      },
      {
        '_id': 2,
        'time': new Date('2025-01-01T00:00:00.001Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_move_chunk',
        'details': {},
      },
    ],
  },
  {
    title: 'resharding aborted before committing, then moveChunk',
    endingNumShards: 3,
    expectedNs: [],
    docs: [
      {
        '_id': 1,
        'time': new Date('2025-01-01T00:00:00.000Z'),
        'what': 'reasharding.coordinator.transition',
        'ns': 'test.coll_not_impacted',
        'details': {'newState': 'aborting'},
      },
      {
        '_id': 2,
        'time': new Date('2025-01-01T00:00:00.001Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_move_chunk',
        'details': {},
      },
    ]
  },
  {
    title: 'resharding aborted after committing, then moveChunk',
    endingNumShards: 3,
    expectedNs: [],
    docs: [
      {
        '_id': 1,
        'time': new Date('2025-01-01T00:00:00.000Z'),
        'what': 'reasharding.coordinator.transition',
        'ns': 'test.coll_not_impacted',
        'details': {'newState': 'committing'},
      },
      {
        '_id': 2,
        'time': new Date('2025-01-01T00:00:01.000Z'),
        'what': 'reasharding.coordinator.transition',
        'ns': 'test.coll_not_impacted',
        'details': {'newState': 'aborting'},
      },
      {
        '_id': 3,
        'time': new Date('2025-01-01T00:00:02.000Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_move_chunk',
        'details': {},
      },
    ]
  },
  {
    title: 'multiple resharding, moveChunk outside of interval',
    endingNumShards: 3,
    expectedNs: [],
    docs: [
      {
        '_id': 1,
        'time': new Date('2025-01-01T00:00:00.000Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_not_impacted',
        'details': {'newState': 'committing'},
      },
      {
        '_id': 2,
        'time': new Date('2025-01-01T01:00:00.000Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_not_impacted',
        'details': {'newState': 'committing'},
      },
      {
        '_id': 3,
        'time': new Date('2025-01-01T01:30:00.001Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_not_impacted',
        'details': {},
      },
      {
        '_id': 4,
        'time': new Date('2025-01-01T02:00:00.000Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_not_impacted',
        'details': {'newState': 'committing'},
      },
      {
        '_id': 5,
        'time': new Date('2025-01-01T02:30:00.001Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_not_impacted',
        'details': {},
      },
      {
        '_id': 6,
        'time': new Date('2025-01-01T02:31:00.000Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_not_impacted',
        'details': {},
      },
    ],
  },

  // cases of may be impacted
  {
    title: 'one collection, resharding, moveChunk within interval',
    endingNumShards: 3,
    expectedNs: ['test.coll_impacted'],
    docs: [
      {
        '_id': 1,
        'time': new Date('2025-01-01T00:00:00.000Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_impacted',
        'details': {'newState': 'committing'},
      },
      {
        '_id': 2,
        'time': new Date('2025-01-01T00:00:01.001Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_impacted',
        'details': {},
      },
    ],
  },
  {
    title: 'one collection, resharding, moveChunk on interval border',
    endingNumShards: 4,
    expectedNs: ['test.coll_impacted'],
    docs: [
      {
        '_id': 1,
        'time': new Date('2025-01-01T00:00:00.000Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_impacted',
        'details': {'newState': 'committing'},
      },
      {
        '_id': 6,
        'time': new Date('2025-01-01T00:30:00.000Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_impacted',
        'details': {},
      },
    ],
  },
  {
    title:
        'one collection, resharding, multiple moveChunk within and outside of interval',
    endingNumShards: 3,
    expectedNs: ['test.coll_impacted'],
    docs: [
      {
        '_id': 1,
        'time': new Date('2025-01-01T00:00:00.000Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_impacted',
        'details': {'newState': 'committing'},
      },
      {
        '_id': 2,
        'time': new Date('2025-01-01T00:01:00.000Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_impacted',
        'details': {},
      },
      {
        '_id': 3,
        'time': new Date('2025-01-01T00:02:00.000Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_impacted',
        'details': {},
      },
      {
        '_id': 4,
        'time': new Date('2025-01-01T00:30:00.001Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_impacted',
        'details': {},
      },
    ],
  },
  {
    title:
        'one collection, multiple resharding, moveChunk within interval',
    endingNumShards: 3,
    expectedNs: ['test.coll_impacted'],
    docs: [
      {
        '_id': 1,
        'time': new Date('2025-01-01T00:00:00.000Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_impacted',
        'details': {'newState': 'committing'},
      },
      {
        '_id': 2,
        'time': new Date('2025-01-01T00:00:01.000Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_impacted',
        'details': {'newState': 'aborting'},
      },
      {
        '_id': 3,
        'time': new Date('2025-01-01T00:01:00.000Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_impacted',
        'details': {'newState': 'committing'},
      },
      {
        '_id': 4,
        'time': new Date('2025-01-01T00:02:00.000Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_impacted',
        'details': {},
      },
      {
        '_id': 3,
        'time': new Date('2025-01-01T00:03:00.000Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_impacted',
        'details': {},
      },
      {
        '_id': 4,
        'time': new Date('2025-01-01T00:30:00.001Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_impacted',
        'details': {},
      },
    ],
  },
  {
    title: 'one collection, addShards, resharding, moveChunk within interval',
    endingNumShards: 3,
    expectedNs: ['test.coll_impacted'],
    docs: [
      {
        '_id': 1,
        'time': new Date('2025-01-01T00:00:00.001Z'),
        'what': 'addShard',
      },
      {
        '_id': 2,
        'time': new Date('2025-01-01T00:00:01.001Z'),
        'what': 'addShard',
      },
      {
        '_id': 3,
        'time': new Date('2025-01-01T00:00:02.001Z'),
        'what': 'addShard',
      },
      {
        '_id': 4,
        'time': new Date('2025-01-01T00:01:00.000Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_impacted',
        'details': {'newState': 'committing'},
      },
      {
        '_id': 5,
        'time': new Date('2025-01-01T00:01:00.001Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_impacted',
        'details': {},
      },
    ],
  },
  {
    title: 'one collection, removeShards, resharding, moveChunk within interval',
    endingNumShards: 3,
    expectedNs: ['test.coll_impacted'],
    docs: [
      {
        '_id': 1,
        'time': new Date('2025-01-01T00:00:00.001Z'),
        'what': 'removeShard',
      },
      {
        '_id': 2,
        'time': new Date('2025-01-01T00:00:01.001Z'),
        'what': 'removeShard',
      },
      {
        '_id': 3,
        'time': new Date('2025-01-01T00:00:02.001Z'),
        'what': 'removeShard',
      },
      {
        '_id': 4,
        'time': new Date('2025-01-01T00:01:00.000Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_impacted',
        'details': {'newState': 'committing'},
      },
      {
        '_id': 5,
        'time': new Date('2025-01-01T00:01:00.001Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_impacted',
        'details': {},
      },
    ],
  },
  {
    title: 'one collection, removeShard, resharding, moveChunk within interval',
    endingNumShards: 3,
    expectedNs: ['test.coll_impacted'],
    docs: [
      {
        '_id': 1,
        'time': new Date('2025-01-01T00:00:00.001Z'),
        'what': 'removeShard',
      },
      {
        '_id': 4,
        'time': new Date('2025-01-01T00:01:00.000Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_impacted',
        'details': {'newState': 'committing'},
      },
      {
        '_id': 5,
        'time': new Date('2025-01-01T00:01:00.001Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_impacted',
        'details': {},
      },
    ],
  },
  {
    title: 'one collection, addShard, removeShard, resharding, moveChunk within interval',
    endingNumShards: 4,
    expectedNs: ['test.coll_impacted'],
    docs: [
      {
        '_id': 1,
        'time': new Date('2025-01-01T00:00:00.001Z'),
        'what': 'addShard',
      },
      {
        '_id': 2,
        'time': new Date('2025-01-01T00:00:01.001Z'),
        'what': 'removeShard',
      },
      {
        '_id': 2,
        'time': new Date('2025-01-01T00:00:02.001Z'),
        'what': 'removeShard',
      },
      {
        '_id': 4,
        'time': new Date('2025-01-01T00:01:00.000Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_impacted',
        'details': {'newState': 'committing'},
      },
      {
        '_id': 5,
        'time': new Date('2025-01-01T00:01:00.001Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_impacted',
        'details': {},
      },
    ],
  },
  {
    title: 'one collection, addShard, removeShards, resharding, moveChunk within interval',
    endingNumShards: 4,
    expectedNs: ['test.coll_impacted'],
    docs: [
      {
        '_id': 1,
        'time': new Date('2025-01-01T00:00:00.001Z'),
        'what': 'addShard',
      },
      {
        '_id': 2,
        'time': new Date('2025-01-01T00:00:01.001Z'),
        'what': 'removeShard',
      },
      {
        '_id': 4,
        'time': new Date('2025-01-01T00:01:00.000Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_impacted',
        'details': {'newState': 'committing'},
      },
      {
        '_id': 5,
        'time': new Date('2025-01-01T00:01:00.001Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_impacted',
        'details': {},
      },
    ],
  },
  {
    title: 'two collections, only one impacted',
    endingNumShards: 3,
    expectedNs: ['test.coll_impacted'],
    docs: [
      {
        '_id': 1,
        'time': new Date('2025-01-01T00:00:00.000Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_impacted',
        'details': {'newState': 'committing'},
      },
      {
        '_id': 2,
        'time': new Date('2025-01-01T00:01:00.000Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_not_impacted',
        'details': {'newState': 'committing'},
      },
      {
        '_id': 3,
        'time': new Date('2025-01-01T00:02:00.000Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_impacted',
        'details': {},
      },
      {
        '_id': 4,
        'time': new Date('2025-01-02T00:00:00.000Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_not_impacted',
        'details': {},
      },
    ],
  },
  {
    title: 'two collections, both impacted',
    endingNumShards: 3,
    expectedNs: ['test.coll_impacted1', 'test.coll_impacted2'],
    docs: [
      {
        '_id': 1,
        'time': new Date('2025-01-01T00:00:00.000Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_impacted1',
        'details': {'newState': 'committing'},
      },
      {
        '_id': 2,
        'time': new Date('2025-01-01T00:01:00.000Z'),
        'what': 'resharding.coordinator.transition',
        'ns': 'test.coll_impacted2',
        'details': {'newState': 'committing'},
      },
      {
        '_id': 3,
        'time': new Date('2025-01-01T00:02:00.000Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_impacted1',
        'details': {},
      },
      {
        '_id': 4,
        'time': new Date('2025-01-01T00:31:00.000Z'),
        'what': 'moveChunk.commit',
        'ns': 'test.coll_impacted2',
        'details': {},
      },
    ],
  },

];

function runTest() {
  testCases.forEach(function(testCase) {
    jsTest.log(`Test case: ${testCase.title}`);
    let retval = _testCA118(testCase.docs, testCase.endingNumShards, true);
    retval.sort();

    const expected = testCase.expectedNs;
    expected.sort();

    assert.eq(tojson(retval), tojson(expected), testCase.title);
    jsTest.log(`passed`);
  });
}

runTest();
