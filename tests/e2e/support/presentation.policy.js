const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.resolve(__dirname, '../../../freq/data/web/js/presentation.js'), 'utf8');
function helpers() {
  const scope = {};
  for (const key of ['document', 'fetch', 'localStorage', 'setTimeout', 'setInterval']) {
    Object.defineProperty(scope, key, { get() { throw new Error('Unexpected dependency: ' + key); } });
  }
  vm.runInNewContext(source, scope);
  return scope.FreqPresentation.create();
}
test('factory has no browser dependencies and returns immutable independent helpers', () => {
  const h = helpers();
  assert.equal(Object.isFrozen(h), true);
  assert.notEqual(h, helpers());
});
test('text escaping preserves hostile strings as literal text', () => {
  const h = helpers();
  assert.equal(h._esc(`<img onerror="x">&'`), '&lt;img onerror=&quot;x&quot;&gt;&amp;&#39;');
  assert.equal(h._esc(null), '');
  assert.equal(h._esc('&lt;'), '&amp;lt;');
});
test('identity display does not infer scope from arbitrary guest IDs', () => {
  const h = helpers();
  for (const vmid of [120, 9050, 999999]) {
    const guest = { vmid, name: 'guest', raw_label: 'node-b/guest', display_name: 'My guest', ip: '192.0.2.11' };
    assert.equal(h._displayName(guest), 'My guest');
    assert.equal(h._rawLabel(guest), 'node-b/guest');
    assert.equal(h._secondaryIdentity(guest), 'node-b/guest · 192.0.2.11');
  }
  assert.equal(h._displayName(null), '');
  assert.equal(h._secondaryIdentity({ name: 'guest' }), '');
  assert.equal(h._displayName({ display_label: '<host>' }), '<host>'); // callers own escaping
});
test('unknown, stale and failed health stay distinct; formatting stays stable', () => {
  const h = helpers();
  assert.equal(h._healthState(null), 'unknown');
  assert.equal(h._healthLabel({ state: 'stale', status: 'up' }), 'STALE');
  assert.equal(h._healthIsLive({ state: 'auth_failed', status: 'up' }), false);
  assert.equal(h._healthLabel({ state: 'auth_failed' }), 'DOWN');
  assert.equal(h._healthLabel({ state: 'unrecognized' }), 'UNKNOWN');
  assert.equal(h._healthLabel({ state: 'recovering' }), 'UP');
  assert.equal(h._healthColor({ state: 'stale' }), 'var(--yellow)');
  assert.equal(h._ramGB(1536), '1.5GB');
  assert.equal(h._ramGB(null), '0MB');
  assert.equal(h._fmtBytes(1536), '1.5 KiB');
  assert.equal(h._fmtBytes(Infinity), '0B');
});
