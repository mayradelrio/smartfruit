"use strict";

const assert = require("node:assert/strict");
const {test} = require("node:test");
const {IDBFactory} = require("fake-indexeddb");
const {createStore} = require("../../src/smartfruit/web/drafts.js");

function snapshot() {
  return {
    version:1,
    saved_at:"2026-11-14T01:00:00.000Z",
    qc_header:{inspection_date:"2026-11-13",lot_id:"",remarks:""},
    samples:[{
      sample_id:"SAMPLE_001",pallet_id:"",qc_fields:{mold:"",scars:"",sample_count:""},
      vision_records:[],image_bindings:[],coverage_choice:"",observations:"",
      reception:{scan_input:"",records:[]}
    }],
    observations:"",inspector_name:"",demo_mode:false
  };
}

function options() { return {indexedDB:new IDBFactory(),databaseName:"test-drafts"}; }

function rawDatabase(factory, name) {
  return new Promise((resolve,reject)=>{
    const request=factory.open(name,1);
    request.onupgradeneeded=()=>request.result.createObjectStore("active");
    request.onsuccess=()=>resolve(request.result);
    request.onerror=()=>reject(request.error);
  });
}

async function rawPut(config, value) {
  const db=await rawDatabase(config.indexedDB,config.databaseName);
  try {
    await new Promise((resolve,reject)=>{
      const tx=db.transaction("active","readwrite");
      tx.oncomplete=resolve;tx.onabort=tx.onerror=()=>reject(tx.error);
      tx.objectStore("active").put(value,"inspection");
    });
  } finally { db.close(); }
}

async function rawGet(config) {
  const db=await rawDatabase(config.indexedDB,config.databaseName);
  try {
    return await new Promise((resolve,reject)=>{
      const request=db.transaction("active","readonly").objectStore("active").get("inspection");
      request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
    });
  } finally { db.close(); }
}

test("starts without a draft; an incomplete inspection survives another instance",async()=>{
  const config=options();const store=createStore(config);
  assert.equal(await store.load(),null);
  const input=snapshot();input.saved_at=undefined;
  const stored=await store.save(input);
  assert.match(stored.saved_at,/^\d{4}-\d{2}-\d{2}T/);
  assert.ok(Number.isFinite(Date.parse(stored.saved_at)));
  const restored=await createStore(config).load();
  assert.deepEqual(restored,stored);
  assert.equal(restored.samples[0].qc_fields.mold,"");
  assert.equal(restored.samples[0].qc_fields.scars,"");
  assert.equal(restored.samples[0].coverage_choice,"");
  assert.equal(restored.samples[0].pallet_id,"");
  assert.equal(input.saved_at,undefined);
});

test("captures copies at save time and returns independent copies on save and load",async()=>{
  const config=options();const store=createStore(config);const input=snapshot();
  input.qc_header.remarks="Original";
  const pending=store.save(input);input.qc_header.remarks="Edited before commit";
  const stored=await pending;assert.equal(stored.qc_header.remarks,"Original");
  stored.qc_header.remarks="Edited returned value";
  const loaded=await store.load();assert.equal(loaded.qc_header.remarks,"Original");
  loaded.samples[0].qc_fields.mold="7";
  assert.equal((await store.load()).samples[0].qc_fields.mold,"");
});

test("optional QC summary preserves original raw fields and blanks without deriving values",async()=>{
  const config=options();const store=createStore(config);const input=snapshot();
  input.qc_summary={label_brand:"",packing_date:"N/A",plu_coo:"4048/Mexico",open_rating:"Good",color_rating:""};
  const saved=await store.save(input);
  assert.deepEqual(saved.qc_summary,input.qc_summary);
  assert.deepEqual((await createStore(config).load()).qc_summary,input.qc_summary);
  const invalid=snapshot();invalid.qc_summary={open_rating:true};
  await assert.rejects(store.save(invalid),{code:"invalid_snapshot"});
  assert.deepEqual((await store.load()).qc_summary,input.qc_summary);
});

test("retains imported Vision and reception verbatim while stripping only approval wrappers",async()=>{
  const config=options();const input=snapshot();
  const vision={
    image_id:"IMG_TECHNICAL",total_fruits:12,oleocellosis_count:2,
    confirmed:true,inspector_final_decision:"VISION_RAW",final_decisions:{raw:"keep"},
    fruit_predictions:[{crop_id:"CROP",unknown:{confirmed_at:"raw model field",score:0.125}}],
    unknown_extra:{confirmation:{allowed:true}},unicode:"limón"
  };
  input.confirmed=true;input.inspector_confirmed=true;input.confirmed_at="old approval";
  input.confirmation={approved:true};input.final_decisions={SAMPLE_001:"STANDARD"};
  input.inspector_final_decision="STANDARD";input.inspector_name="Inspector saved as text";
  const sample=input.samples[0];
  sample.vision_records.push(vision);sample.image_bindings=[{image_id:"IMG_TECHNICAL",confirmed:true}];
  sample.reception={scan_input:"SF-5815-5645",records:[{lot_id:"5815",confirmed:true}]};
  sample.inspector_final_decision="STANDARD";sample.inspector_confirmed=true;sample.confirmed=true;
  sample.confirmed_at="old approval";sample.confirmation={approved:true};sample.final_decisions={bad:true};
  input.qc_header.confirmed="raw field stays";sample.qc_fields.confirmed="raw field stays";
  input.extra_draft_note={confirmed:"unrelated object stays"};
  const store=createStore(config);await store.save(input);const restored=await store.load();
  for (const key of ["confirmation","final_decisions","confirmed","inspector_confirmed","confirmed_at","inspector_final_decision"]) {
    assert.equal(Object.hasOwn(restored,key),false,key);
    assert.equal(Object.hasOwn(restored.samples[0],key),false,key);
  }
  assert.deepEqual(restored.samples[0].vision_records,[vision]);
  assert.deepEqual(restored.samples[0].image_bindings,sample.image_bindings);
  assert.deepEqual(restored.samples[0].reception,sample.reception);
  assert.deepEqual(restored.extra_draft_note,input.extra_draft_note);
  assert.equal(restored.qc_header.confirmed,"raw field stays");
  assert.equal(restored.samples[0].qc_fields.confirmed,"raw field stays");
  assert.equal(restored.inspector_name,"Inspector saved as text");
  assert.equal(input.confirmed,true);
});

test("load strips old approval metadata without changing the stored copy",async()=>{
  const config=options();const old=snapshot();old.inspector_confirmed=true;
  old.samples[0].inspector_final_decision="COMPLETE";
  await rawPut(config,old);
  const restored=await createStore(config).load();
  assert.equal(Object.hasOwn(restored,"inspector_confirmed"),false);
  assert.equal(Object.hasOwn(restored.samples[0],"inspector_final_decision"),false);
  assert.deepEqual(await rawGet(config),old);
});

test("serial saves, clear and a new save cannot revive a discarded older draft",async()=>{
  const config=options();const store=createStore(config);
  const first=snapshot();first.observations="first";
  const second=snapshot();second.observations="second";
  const third=snapshot();third.observations="new inspection";
  const a=store.save(first);const b=store.save(second);const c=store.clear();const d=store.save(third);
  await Promise.all([a,b,c,d]);await store.flush();
  assert.equal((await createStore(config).load()).observations,"new inspection");
  await store.save(first);const discarded=store.clear();
  await store.flush();await discarded;
  assert.equal(await store.load(),null);
});

test("flush waits for the queued transaction, not a request success event",async()=>{
  const config=options();const store=createStore(config);
  const pending=store.save(snapshot());let settled=false;
  const flushed=store.flush().then(()=>{settled=true;});
  await Promise.resolve();assert.equal(settled,false);
  await flushed;await pending;
  assert.notEqual(await rawGet(config),undefined);
});

for (const [name,modify] of [
  ["future snapshot version",value=>{value.version=2;}],
  ["missing version",value=>{delete value.version;}],
  ["invalid saved timestamp",value=>{value.saved_at="not an ISO date";}],
  ["wrong samples shape",value=>{value.samples={};}],
  ["wrong raw header value",value=>{value.qc_header.lot_id=42;}],
  ["wrong coverage choice",value=>{value.samples[0].coverage_choice=true;}],
  ["missing Vision array",value=>{delete value.samples[0].vision_records;}]
]) {
  test(`${name} is preserved on load and prevents silent autosave overwrite`,async()=>{
    const config=options();const corrupt=snapshot();modify(corrupt);await rawPut(config,corrupt);
    const store=createStore(config);
    await assert.rejects(store.load(),{name:"SmartFruitDraftError"});
    await assert.rejects(store.save(snapshot()),{name:"SmartFruitDraftError"});
    await assert.rejects(store.flush(),{name:"SmartFruitDraftError"});
    assert.deepEqual(await rawGet(config),corrupt);
    // Caller invokes clear only after an explicit user discard/new inspection.
    await store.clear();assert.equal(await store.load(),null);
    await store.save(snapshot());assert.equal((await store.load()).version,1);
  });
}

test("invalid incoming snapshots do not damage a valid existing draft",async()=>{
  const config=options();const store=createStore(config);const original=await store.save(snapshot());
  const bad=snapshot();bad.samples[0].reception.records={};
  await assert.rejects(store.save(bad),{code:"invalid_snapshot"});
  assert.deepEqual(await store.load(),original);
});

test("an unavailable IndexedDB rejects save, load and clear without false success",async()=>{
  const store=createStore({indexedDB:null});
  await assert.rejects(store.save(snapshot()),{code:"storage_unavailable"});
  await assert.rejects(store.flush(),{code:"storage_unavailable"});
  await assert.rejects(store.load(),{code:"storage_unavailable"});
  await assert.rejects(store.clear(),{code:"storage_unavailable"});
});

test("an open error can be retried without poisoning the action queue",async()=>{
  const real=new IDBFactory();let fail=true;
  const factory={open(...args){if(fail)throw new DOMException("denied","SecurityError");return real.open(...args);}};
  const store=createStore({indexedDB:factory});
  await assert.rejects(store.save(snapshot()),{code:"storage_error"});
  fail=false;await store.save(snapshot());assert.equal((await store.load()).version,1);
});

test("blocked opens reject promptly and a late connection is closed",async()=>{
  let closed=false;
  const factory={open(){const request={};queueMicrotask(()=>request.onblocked());setImmediate(()=>{
    request.result={close(){closed=true;}};request.onsuccess();
  });return request;}};
  const store=createStore({indexedDB:factory});
  await assert.rejects(store.load(),{code:"storage_blocked"});
  await new Promise(resolve=>setImmediate(resolve));assert.equal(closed,true);
});

test("an open that never responds times out instead of hanging recovery",async t=>{
  t.mock.timers.enable({apis:["setTimeout"]});
  try {
    const store=createStore({indexedDB:{open(){return {};}}});
    const recovery=store.load();
    await Promise.resolve();
    t.mock.timers.tick(4000);
    await assert.rejects(recovery,{code:"storage_timeout"});
  } finally {t.mock.timers.reset();}
});

test("quota failure aborts a save and preserves the preceding durable snapshot",async()=>{
  const config=options();const store=createStore(config);const original=await store.save(snapshot());
  // Fail the next put after the existing snapshot was read, as a real quota error.
  const db=await rawDatabase(config.indexedDB,config.databaseName);
  const prototype=Object.getPrototypeOf(db.transaction("active","readonly").objectStore("active"));
  const realPut=prototype.put;
  prototype.put=function(){throw new DOMException("quota","QuotaExceededError");};
  try {
    const changed=snapshot();changed.observations="must not be stored";
    await assert.rejects(store.save(changed),{code:"storage_quota"});
    await assert.rejects(store.flush(),{code:"storage_quota"});
  } finally {prototype.put=realPut;db.close();}
  assert.deepEqual(await store.load(),original);
});

test("an abort after a put request succeeds never reports a durable save",async()=>{
  const config=options();const store=createStore(config);const original=await store.save(snapshot());
  const db=await rawDatabase(config.indexedDB,config.databaseName);
  const tx=db.transaction("active","readonly");const prototype=Object.getPrototypeOf(tx.objectStore("active"));
  const realPut=prototype.put;
  prototype.put=function(...args){
    const request=realPut.apply(this,args);const transaction=this.transaction;
    request.addEventListener("success",()=>transaction.abort());
    return request;
  };
  try {
    const changed=snapshot();changed.observations="request succeeded, transaction aborted";
    await assert.rejects(store.save(changed),{code:"storage_error"});
  } finally {prototype.put=realPut;db.close();}
  assert.deepEqual(await store.load(),original);
});

test("an explicit discard failure rejects and keeps the existing draft",async()=>{
  const config=options();const store=createStore(config);const original=await store.save(snapshot());
  const db=await rawDatabase(config.indexedDB,config.databaseName);
  const prototype=Object.getPrototypeOf(db.transaction("active","readonly").objectStore("active"));
  const realDelete=prototype.delete;
  prototype.delete=function(){throw new DOMException("delete failed","UnknownError");};
  try {
    await assert.rejects(store.clear(),{code:"storage_error"});
    await assert.rejects(store.flush(),{code:"storage_error"});
  } finally {prototype.delete=realDelete;db.close();}
  assert.deepEqual(await store.load(),original);
});

test("lot roster and workflow step survive recovery without approval",async()=>{
 const config=options(),input=snapshot();input.workflow_step=3;
 input.lot_reception={scan_input:"P1",records:[{lot_id:"LOT",pallet_id:"P1",grower:"ORIGINAL",confirmed:"raw"}]};
 input.confirmed=true;const store=createStore(config);await store.save(input);
 const restored=await createStore(config).load();
 assert.equal(restored.workflow_step,3);assert.deepEqual(restored.lot_reception,input.lot_reception);
 assert.equal(Object.hasOwn(restored,"confirmed"),false);
});
test("a lot selected without a scan survives recovery with its original provenance",async()=>{
 const config=options(),input=snapshot();input.workflow_step=3;input.qc_header.lot_id="LOT";
 input.lot_reception={lot_id:"LOT",records:[{lot_id:"LOT",pallet_id:"P1",label_brand:"ORIGINAL"}]};
 const before=structuredClone(input.lot_reception);const store=createStore(config);
 await store.save(input);const restored=await createStore(config).load();
 assert.deepEqual(restored.lot_reception,before);
 assert.equal(Object.hasOwn(restored.lot_reception,"scan_input"),false);
 assert.deepEqual(input.lot_reception,before);
});
for(const reason_source of ["defect_summary","inspector"]){
 test("Reason source survives recovery without restoring approval: "+reason_source,async()=>{
  const config=options(),input=snapshot();input.reason_source=reason_source;
  input.qc_header.reason="Scars: 3 fruits.";input.confirmed=true;
  const store=createStore(config);await store.save(input);
  const restored=await createStore(config).load();
  assert.equal(restored.reason_source,reason_source);
  assert.equal(restored.qc_header.reason,input.qc_header.reason);
  assert.equal(Object.hasOwn(restored,"confirmed"),false);
 });
}
test("an invalid Reason source cannot replace the saved draft",async()=>{
 const store=createStore(options()),saved=await store.save(snapshot());
 await assert.rejects(store.save({...snapshot(),reason_source:"unknown"}),{code:"invalid_snapshot"});
 assert.deepEqual(await store.load(),saved);
});

test("additional-review history and working choice survive recovery without final approval",async()=>{
 const config=options(),input=snapshot(),sample=input.samples[0];
 sample.review_choice="EXTEND";
 sample.review_history={
  initial:{vision_records:[{image_id:"INITIAL",confirmed:"raw"}],qc_fields:{sample_count:12}},
  additional:[{review_number:2,trigger_decision:"EXTEND",vision_records:[{image_id:"EXTRA"}],manual_defects:{scars:1}}]
 };
 sample.inspector_confirmed=true;sample.inspector_final_decision="EXTEND";input.confirmed=true;
 const store=createStore(config);await store.save(input);const restored=await createStore(config).load();
 assert.equal(restored.samples[0].review_choice,"EXTEND");
 assert.deepEqual(restored.samples[0].review_history,sample.review_history);
 assert.equal(Object.hasOwn(restored.samples[0],"inspector_confirmed"),false);
 assert.equal(Object.hasOwn(restored.samples[0],"inspector_final_decision"),false);
 assert.equal(Object.hasOwn(restored,"confirmed"),false);
});

test("invalid additional-review draft fields preserve the previous saved inspection",async()=>{
 const store=createStore(options()),saved=await store.save(snapshot());
 for(const update of [{review_choice:"APPROVED"},{review_choice:true},{review_history:{}},
  {review_history:{initial:{},additional:[null]}}]){
  const input=snapshot();Object.assign(input.samples[0],update);
  await assert.rejects(store.save(input),{code:"invalid_snapshot"});
  assert.deepEqual(await store.load(),saved);
 }
});
for(const lot_reception of [
 {records:[]},{lot_id:"",records:[]},{lot_id:" ",records:[]},{lot_id:5815,records:[]},
 {scan_input:"",records:[]},{scan_input:null,records:[]},
 {lot_id:"LOT",records:[null]},{lot_id:"LOT",records:{}},
 {lot_id:"LOT",scan_input:"",records:[]},{lot_id:5815,scan_input:"P1",records:[]}
]){
 test("invalid lot selection provenance preserves the saved draft "+JSON.stringify(lot_reception),async()=>{
  const config=options(),store=createStore(config);const saved=await store.save(snapshot());
  await assert.rejects(store.save({...snapshot(),lot_reception}),{code:"invalid_snapshot"});
  assert.deepEqual(await store.load(),saved);
 });
}
for(const bad of [{workflow_step:5},{workflow_step:"2"},{lot_reception:{scan_input:"P1",records:"bad"}},{lot_reception:{scan_input:"P1",records:[null]}}]){
 test("invalid lot draft extension cannot replace a valid capture "+JSON.stringify(bad),async()=>{
  const store=createStore(options());await store.save(snapshot());
  await assert.rejects(store.save({...snapshot(),...bad}),{code:"invalid_snapshot"});
  assert.equal((await store.load()).qc_header.remarks,"");
 });
}
