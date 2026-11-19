"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");

const html = fs.readFileSync(path.join(__dirname, "../../src/smartfruit/web/index.html"), "utf8");
const start = html.indexOf("  function receptionStorage(");
assert.notEqual(start, -1);
const end = html.indexOf("\n  function ", start + 1);
assert.notEqual(end, -1);
const source = html.slice(start, end);

function clock() {
  let now = 0, next = 1;
  const timers = new Map();
  return {
    setTimeout(callback, delay) {
      const id = next++;
      timers.set(id, {callback, at: now + delay});
      return id;
    },
    clearTimeout(id) { timers.delete(id); },
    tick(delay) {
      const target = now + delay;
      for (;;) {
        const due = [...timers].filter(([, timer]) => timer.at <= target)
          .sort((left, right) => left[1].at - right[1].at)[0];
        if (!due) break;
        now = due[1].at;
        timers.delete(due[0]);
        due[1].callback();
      }
      now = target;
    },
  };
}

function setup() {
  const time = clock(), opening = {}, operation = {};
  const calls = {close: 0, abort: 0, transaction: 0, get: 0, put: 0, delete: 0};
  const store = {
    get(key) { assert.equal(key, "manifest");calls.get++;return operation; },
    put(value, key) { assert.equal(key, "manifest");calls.put++;return operation; },
    delete(key) { assert.equal(key, "manifest");calls.delete++;return operation; },
  };
  const transaction = {
    objectStore(name) { assert.equal(name, "active");return store; },
    abort() { calls.abort++; },
  };
  const database = {
    close() { calls.close++; },
    transaction(name, mode) {
      assert.equal(name, "active");assert.ok(["readonly", "readwrite"].includes(mode));
      calls.transaction++;
      return transaction;
    },
  };
  const context = vm.createContext({
    window: {indexedDB: {open(name, version) {
      assert.equal(name, "smartfruit-reception");assert.equal(version, 1);return opening;
    }}},
    setTimeout: time.setTimeout,
    clearTimeout: time.clearTimeout,
  });
  vm.runInContext(source, context);
  return {time, opening, operation, transaction, database, calls,
    receptionStorage: context.receptionStorage,
    opened() { opening.result = database;opening.onsuccess(); },
  };
}

function observe(promise) {
  const outcome = {state: "pending"};
  promise.then(() => { outcome.state = "resolved"; }, () => { outcome.state = "rejected"; });
  return outcome;
}

const storageFailure = /manifiesto|almacenamiento|tiempo|tard/i;

test("a blocked manifest database times out and a late open closes without starting a transaction", async () => {
  const fixture = setup();
  const result = fixture.receptionStorage("get"), outcome = observe(result);
  fixture.time.tick(3999);await Promise.resolve();
  assert.equal(outcome.state, "pending");
  fixture.time.tick(1);
  await assert.rejects(result, storageFailure);
  assert.equal(fixture.calls.transaction, 0);
  fixture.opened();
  assert.equal(fixture.calls.close, 1);
  assert.equal(fixture.calls.transaction, 0);
  fixture.time.tick(20000);
  assert.equal(fixture.calls.abort, 0);
});

for (const action of ["get", "put"]) {
  test("a stalled manifest " + action + " aborts and closes its transaction after the time limit", async () => {
    const fixture = setup(), value = {manifest_csv: "original CSV text", filename: "manifest.csv"};
    const original = structuredClone(value);
    const result = fixture.receptionStorage(action, value), outcome = observe(result);
    fixture.opened();fixture.time.tick(7999);await Promise.resolve();
    assert.equal(outcome.state, "pending");
    fixture.time.tick(1);
    await assert.rejects(result, storageFailure);
    assert.equal(fixture.calls.abort, 1);
    assert.ok(fixture.calls.close >= 1);
    assert.equal(fixture.calls[action], 1);
    assert.equal(fixture.calls.delete, 0);
    assert.deepEqual(value, original);
  });
}

test("a manifest read resolves on transaction completion and cancels both time limits", async () => {
  const fixture = setup(), manifest = {manifest_csv: "preserved CSV", filename: "saved.csv"};
  const result = fixture.receptionStorage("get"), outcome = observe(result);
  fixture.opened();
  fixture.operation.result = manifest;fixture.operation.onsuccess();
  await Promise.resolve();
  assert.equal(outcome.state, "pending");
  fixture.time.tick(7999);await Promise.resolve();
  assert.equal(outcome.state, "pending");
  fixture.transaction.oncomplete();
  assert.equal(await result, manifest);
  fixture.time.tick(20000);
  assert.equal(fixture.calls.abort, 0);
  assert.equal(fixture.calls.close, 1);
  assert.equal(fixture.calls.delete, 0);
});
