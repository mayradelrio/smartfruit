"use strict";

const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const {test}=require("node:test");
const {IDBFactory}=require("fake-indexeddb");
const {createStore}=require("../../src/smartfruit/web/drafts.js");
const html=fs.readFileSync(path.join(__dirname,"../../src/smartfruit/web/index.html"),"utf8");

function snapshot(){return {
  version:1,qc_header:{lot_id:"LOT"},samples:[{sample_id:"S1",pallet_id:"P1",qc_fields:{pallet_id:"P1"},vision_records:[],image_bindings:[],coverage_choice:"",observations:"",
    photo_pools:{initial:{context_key:'["LOT","P1","S1","initial",0]',target_count:150,photo_ids:["A","B"]},additional:{context_key:'["LOT","P1","S1","additional",0]',target_count:150,photo_ids:["C","D"]}},
  }],observations:"",inspector_name:"",demo_mode:true,
};}

test("prepared demo photo pools survive durable draft recovery without acquiring approval",async()=>{
  const input=snapshot();input.confirmed=true;input.samples[0].inspector_confirmed=true;
  const options={indexedDB:new IDBFactory(),databaseName:"demo-pool-recovery"},store=createStore(options);
  await store.save(input);const recovered=await createStore(options).load();
  assert.deepEqual(recovered.samples[0].photo_pools,input.samples[0].photo_pools);
  assert.equal(Object.hasOwn(recovered,"confirmed"),false);assert.equal(Object.hasOwn(recovered.samples[0],"inspector_confirmed"),false);
  recovered.samples[0].photo_pools.initial.photo_ids.push("CHANGED");
  assert.deepEqual((await store.load()).samples[0].photo_pools,input.samples[0].photo_pools);
});

test("malformed pool reservations cannot replace an already saved inspection",async()=>{
  const store=createStore({indexedDB:new IDBFactory(),databaseName:"demo-pool-invalid"}),saved=await store.save(snapshot());
  for(const photo_pools of [null,[],{initial:null},{third:{context_key:"BOX",target_count:1,photo_ids:["A"]}},
    {initial:{context_key:"",target_count:1,photo_ids:["A"]}},{initial:{context_key:"BOX",target_count:-1,photo_ids:["A"]}},
    {initial:{context_key:"BOX",target_count:1.5,photo_ids:["A"]}},{initial:{context_key:"BOX",target_count:1,photo_ids:["A","A"]}},
    {initial:{context_key:"BOX",target_count:1,photo_ids:[null]}},{initial:{context_key:"BOX",target_count:1,photo_ids:[""]}}]){
    const input=snapshot();input.samples[0].photo_pools=photo_pools;
    await assert.rejects(store.save(input),{code:"invalid_snapshot"});
    assert.deepEqual(await store.load(),saved);
  }
});

test("legacy drafts without photo pools remain unchanged and zero remaining quota can be saved",async()=>{
  const input=snapshot();delete input.samples[0].photo_pools;
  const store=createStore({indexedDB:new IDBFactory(),databaseName:"demo-pool-legacy"});await store.save(input);
  assert.equal(Object.hasOwn((await store.load()).samples[0],"photo_pools"),false);
  input.samples[0].photo_pools={initial:{context_key:"BOX",target_count:0,photo_ids:[]}};
  await store.save(input);assert.deepEqual((await store.load()).samples[0].photo_pools,input.samples[0].photo_pools);
});

function source(name){
  const match=new RegExp("^  (?:async )?function "+name+"\\(","m").exec(html);assert.ok(match,name+" exists");
  const first=html.slice(match.index).split("\n",1)[0];if(first.trimEnd().endsWith("}"))return first;
  const rest=html.slice(match.index+match[0].length),next=/\n  (?:async )?function /.exec(rest);assert.ok(next);
  return html.slice(match.index,match.index+match[0].length+next.index);
}

test("mounting Vision uses the box's remaining fruit count and reserves pools from every other box",()=>{
  const configs=[],calls={draft:0};
  const sample={id:{value:"S1"},controls:{pallet_id:{value:"P1"}},records:[{image_id:"INITIAL_USED",total_fruits:50}],inspectorChoice:"EXPAND",
    reception:{records:[{expected_count_per_box:"150",size_declared:"150"}]},boxInspection:{manifest_record_index:null},
    photoPools:{initial:{context_key:"INITIAL",target_count:100,photo_ids:["INITIAL_RESERVED"]},additional:{context_key:"ADDITIONAL",target_count:130,photo_ids:["ADDITIONAL_RESERVED"]}},
    pendingAdditional:{visionRecords:[{image_id:"EXTRA_USED",total_fruits:20}],boxInspection:{manifest_record_index:null}},additionalCaptureMemory:{selected:new Set(["OTHER_SELECTION"])},
  };
  const other={records:[],photoPools:{initial:{photo_ids:["OTHER_BOX_RESERVED"]}}};
  const context=vm.createContext({state:{samples:[sample,other]},headerControls:{lot_id:{value:"LOT"}},copy:structuredClone,
    element(){return {append(){}};},window:{SmartFruitVisionCapture:{create(options){configs.push(options);return {destroy(){},refresh(){}};}}},
    request(){},busy:fn=>fn(),lockCaptureInputs:()=>()=>{},error(){},status(){},scheduleDraft(){calls.draft++;},
  });
  vm.runInContext(["boxCaptureSummary","mountVisionCapture"].map(source).join("\n"),context);
  context.mountVisionCapture(sample,"initial");context.mountVisionCapture(sample,"additional");
  assert.equal(configs[0].getTargetCount(),100);assert.equal(configs[1].getTargetCount(),130);
  assert.equal(configs[0].getReservedPhotoIds().has("INITIAL_RESERVED"),false);
  assert.equal(configs[0].getReservedPhotoIds().has("ADDITIONAL_RESERVED"),true);
  assert.equal(configs[0].getReservedPhotoIds().has("OTHER_BOX_RESERVED"),true);
  assert.equal(configs[0].getReservedPhotoIds().has("OTHER_SELECTION"),true);
  assert.equal(configs[1].getReservedPhotoIds().has("INITIAL_RESERVED"),true);
  assert.equal(configs[1].getReservedPhotoIds().has("ADDITIONAL_RESERVED"),false);
  assert.equal(configs[1].getUsedImageIds().has("EXTRA_USED"),true);
  const updated={context_key:"UPDATED",target_count:100,photo_ids:["A","B"]};configs[0].onPhotoPool(updated);
  assert.deepEqual(sample.photoPools.initial,updated);assert.equal(calls.draft,1);
  updated.photo_ids.push("CALLER_MUTATION");assert.deepEqual(sample.photoPools.initial.photo_ids,["A","B"]);
  sample.records.push({image_id:"MORE_INITIAL",total_fruits:100});assert.equal(configs[0].getTargetCount(),0);
});
