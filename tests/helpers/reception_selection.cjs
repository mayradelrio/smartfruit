"use strict";

// Execute the interface functions against real API responses supplied by pytest.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const html = fs.readFileSync(path.join(__dirname, "../../src/smartfruit/web/index.html"), "utf8");

function source(name) {
  const start = html.indexOf("  function " + name + "(");
  assert.notEqual(start, -1, name + " must exist in the interface");
  const end = html.indexOf("\n  function ", start + 1);
  assert.notEqual(end, -1);
  return html.slice(start, end);
}

function element(tag, textContent) {
  return {
    tag, textContent, children: [], hidden: true, value: "",
    append(...children) { this.children.push(...children); },
    replaceChildren(...children) { this.children = children; },
  };
}

for (const lot of JSON.parse(fs.readFileSync(0, "utf8"))) {
  const nodes = new Map();
  const byId = id => {
    if (!nodes.has(id)) nodes.set(id, element("div"));
    return nodes.get(id);
  };
  const state = {samples: []};
  const headerControls = Object.fromEntries([...new Set([...Object.keys(lot.qc_header), "country_origin", "vessel", "container"])].map(key => [key, element("input")]));
  const summaryControls = Object.fromEntries(["label_brand", "packing_date", "plu_coo"].map(key => [key, element("input")]));
  const context = vm.createContext({
    state, headerControls, summaryControls, byId, element, copy: structuredClone,
    refreshReceptionControls() {}, captureChanged() {}, status() {},
    setStep(step) { state.workflowStep = step; },
    addReceptionSample(pallet) { state.samples.push(pallet); },
  });
  vm.runInContext(["unambiguous", "receptionTable", "renderSelection", "prefillSummary", "startLot"].map(source).join("\n"), context);

  const original = structuredClone(lot);
  context.renderSelection(lot);
  assert.deepEqual(state.receptionSelection, lot);
  assert.notEqual(state.receptionSelection, lot);
  assert.equal(byId("reception-selection").hidden, false);
  if (lot.scanned_pallet_id !== null) assert.ok(byId("selection-title").textContent.includes(lot.scanned_pallet_id));
  else assert.ok(!byId("selection-title").textContent.includes("null"));
  assert.ok(byId("selection-title").textContent.includes(lot.pallets.length + " paletas"));

  byId("scan-input").value = lot.scanned_pallet_id;
  context.startLot(state.receptionSelection);
  assert.deepEqual(state.samples.map(pallet => pallet.pallet_id), lot.pallets.map(pallet => pallet.pallet_id));
  assert.deepEqual(state.lotReception.records, lot.records);
  if (lot.selection_mode === "lot") {
    assert.equal(state.lotReception.lot_id, lot.lot_id);
    assert.equal(Object.hasOwn(state.lotReception, "scan_input"), false);
  } else assert.equal(state.lotReception.scan_input, lot.scan_input);
  for (const key of ["label_brand", "packing_date", "plu_coo"]) {
    const values = new Set(lot.records.map(row => String(row[key] ?? "").trim()));
    assert.equal(summaryControls[key].value, values.size === 1 ? [...values][0] : "");
  }
  assert.equal(state.workflowStep, 2);
  assert.equal(byId("inspection-form").hidden, false);
  assert.deepEqual(lot, original);
  const changed = structuredClone(lot);
  changed.records[0].label_brand = "CHANGED-RECEPTION";
  assert.throws(() => context.startLot(changed), /manifiesto.*cambi/i);
  assert.deepEqual(state.lotReception.records, lot.records);

  for (const mutate of [
    invalid => { invalid.records = []; },
    invalid => { invalid.records = [null]; },
    invalid => { invalid.pallets = []; },
    invalid => { invalid.pallets = [null]; },
    invalid => { invalid.pallets[0].records = []; },
    invalid => { invalid.scanned_pallet_id = "NOT-IN-LOT"; },
  ]) {
    const invalid = structuredClone(lot);
    mutate(invalid);
    assert.throws(() => context.renderSelection(invalid), /No se recibieron filas/);
    assert.deepEqual(state.receptionSelection, lot);
  }
}
