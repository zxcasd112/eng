const test = require('node:test');
const assert = require('node:assert');
const { createStudyQueueManager } = require('../app/web/app.js');

test('study queue manager initializes correctly', () => {
  const manager = createStudyQueueManager();
  assert.deepStrictEqual(manager.getQueue(), []);
  assert.strictEqual(manager.getIndex(), 0);
  assert.strictEqual(manager.isAnswerRevealed(), false);
  assert.strictEqual(manager.getFilter(), 'ALL');
  assert.strictEqual(manager.isSubmitting(), false);
});

test('setting queue loads cards and resets index', () => {
  const manager = createStudyQueueManager();
  const cards = [{ id: 1, word: { lemma: 'apple' } }, { id: 2, word: { lemma: 'banana' } }];
  manager.setQueue(cards);

  assert.strictEqual(manager.getQueue().length, 2);
  assert.strictEqual(manager.getIndex(), 0);
  assert.strictEqual(manager.getCurrentCard().id, 1);
});

test('filter change resets study index to 0', () => {
  const manager = createStudyQueueManager();
  manager.setQueue([{ id: 1 }, { id: 2 }, { id: 3 }]);
  manager.startSubmit();
  manager.finishSubmitSuccess();
  assert.strictEqual(manager.getIndex(), 1);

  // Changing filter must reset index
  manager.setFilter('en_ru');
  assert.strictEqual(manager.getFilter(), 'en_ru');
  assert.strictEqual(manager.getIndex(), 0);
});

test('double submission is blocked by in-flight guard', () => {
  const manager = createStudyQueueManager();
  manager.setQueue([{ id: 1 }, { id: 2 }]);

  const firstAttempt = manager.startSubmit();
  assert.strictEqual(firstAttempt, true);
  assert.strictEqual(manager.isSubmitting(), true);

  // Second rapid click while submitting must return false
  const secondAttempt = manager.startSubmit();
  assert.strictEqual(secondAttempt, false);
});

test('network failure does NOT advance the queue', () => {
  const manager = createStudyQueueManager();
  manager.setQueue([{ id: 10, word: { lemma: 'resilience' } }, { id: 20 }]);

  manager.revealAnswer();
  assert.strictEqual(manager.isAnswerRevealed(), true);

  manager.startSubmit();
  // Simulate network/server error
  manager.finishSubmitFailure();

  // Queue must remain on the same card!
  assert.strictEqual(manager.getIndex(), 0);
  assert.strictEqual(manager.getCurrentCard().id, 10);
  assert.strictEqual(manager.isSubmitting(), false);
});

test('successful review advances queue to next card', () => {
  const manager = createStudyQueueManager();
  manager.setQueue([{ id: 10 }, { id: 20 }]);

  manager.revealAnswer();
  manager.startSubmit();
  manager.finishSubmitSuccess();

  assert.strictEqual(manager.getIndex(), 1);
  assert.strictEqual(manager.getCurrentCard().id, 20);
  assert.strictEqual(manager.isAnswerRevealed(), false);
});
