"use strict";

const assert = require("node:assert/strict");
const {test} = require("node:test");
const defaults = require("../../src/smartfruit/web/vision_defaults.js");
const context = {lot_id:"ANY-LOT", pallet_id:"ANY-PALLET", sample_id:"ANY-SAMPLE", review_kind:"initial"};
const groups = [
  {name:"ANY-TAKE-A", photos:[{photo_id:"A1"}, {photo_id:"A2"}]},
  {name:"ANY-TAKE-B", photos:[{photo_id:"B1"}, {photo_id:"B2"}]},
  {name:"ANY-TAKE-C", photos:[{photo_id:"C1"}]},
];

test("a demo default selects one complete take without hardcoded lot or photo identities", () => {
  const before = structuredClone(groups);
  assert.deepEqual(defaults.chooseDefaultPhotoIds(groups, context), ["A1", "A2"]);
  assert.deepEqual(defaults.chooseDefaultPhotoIds(groups, {...context,lot_id:"NEW-LOT",pallet_id:"NEW-PALLET"}), ["A1", "A2"]);
  assert.deepEqual(groups, before);
});

test("another pallet's reservation chooses a distinct take before either pallet is confirmed", () => {
  const reserved = new Set(defaults.chooseDefaultPhotoIds(groups, context));
  const second = defaults.chooseDefaultPhotoIds(groups, {...context,pallet_id:"SECOND-PALLET"}, {reservedPhotoIds:reserved});
  assert.deepEqual(second, ["B1", "B2"]);
  assert.deepEqual(Array.from(reserved), ["A1", "A2"]);
});

test("used fruit or a partial reservation skips the entire take rather than reusing part of it", () => {
  const current = structuredClone(groups);
  current[0].photos[1].used = true;
  assert.deepEqual(defaults.chooseDefaultPhotoIds(current, context, {reservedPhotoIds:new Set(["B2"])}), ["C1"]);
  assert.equal(current[0].photos[0].used, undefined);
});

test("EXTEND can select the next unused take while retaining the same pallet context", () => {
  const current = structuredClone(groups);
  for (const photo of current[0].photos) photo.used = true;
  const additional = {...context,review_kind:"additional"};
  assert.deepEqual(defaults.chooseDefaultPhotoIds(current, additional), ["B1", "B2"]);
  assert.notEqual(defaults.contextKey(context), defaults.contextKey(additional));
});

test("no default is proposed without identified context or when no complete group remains", () => {
  for (const key of ["lot_id","pallet_id","sample_id","review_kind"]) {
    assert.deepEqual(defaults.chooseDefaultPhotoIds(groups, {...context,[key]:""}), []);
  }
  assert.deepEqual(defaults.chooseDefaultPhotoIds(groups, {...context,review_kind:"other"}), []);
  assert.deepEqual(defaults.chooseDefaultPhotoIds(groups, context, {reservedPhotoIds:new Set(["A1","B1","C1"])}), []);
  assert.deepEqual(defaults.chooseDefaultPhotoIds([], context), []);
});

test("preferred take order remains deterministic and wraps when that take is unavailable", () => {
  assert.deepEqual(defaults.chooseDefaultPhotoIds(groups, context, {preferredIndex:1}), ["B1", "B2"]);
  assert.deepEqual(defaults.chooseDefaultPhotoIds(groups, context, {preferredIndex:5,reservedPhotoIds:new Set(["C1"])}), ["A1", "A2"]);
});

test("context keys trim identifiers and do not confuse delimiter-containing lot and pallet IDs", () => {
  assert.equal(defaults.contextKey({...context,lot_id:" ANY-LOT "}), defaults.contextKey(context));
  assert.notEqual(defaults.contextKey({...context,lot_id:"A/B",pallet_id:"C"}), defaults.contextKey({...context,lot_id:"A",pallet_id:"B/C"}));
  assert.notEqual(defaults.contextKey(context), defaults.contextKey({...context,sample_id:"ANOTHER-SAMPLE"}));
});
