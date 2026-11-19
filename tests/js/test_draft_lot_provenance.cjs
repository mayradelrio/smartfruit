"use strict";

// Exercise the actual draft preparation/validation without an IndexedDB package.
const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const {test}=require("node:test");
const source=fs.readFileSync(path.join(__dirname,"../../src/smartfruit/web/drafts.js"),"utf8");
assert.equal(source.split("return {createStore};").length,2);
const scope={module:{exports:{}},structuredClone};
vm.runInNewContext(source.replace("return {createStore};","return {createStore, prepare};"),scope);
const {prepare}=scope.module.exports;

function snapshot(lot_reception){return {
  version:1,qc_header:{lot_id:"LOT"},qc_summary:{label_brand:"Original"},lot_reception,
  samples:[{sample_id:"S1",pallet_id:"P1",qc_fields:{label_brand:"Original",decay:""},
    vision_records:[],image_bindings:[],coverage_choice:"",observations:""}],
  observations:"",inspector_name:"",demo_mode:false,
};}

test("draft preparation preserves explicit lot selection and legacy scans without inventing provenance",()=>{
  for(const identity of [{lot_id:"LOT"},{scan_input:"P1"}]){
    const input=snapshot({...identity,records:[{lot_id:"LOT",pallet_id:"P1",label_brand:"Original"}]});
    input.confirmed=true;const original=structuredClone(input);
    const output=prepare(input,false);
    assert.deepEqual(output.lot_reception,input.lot_reception);
    assert.deepEqual(Object.keys(output.lot_reception),Object.keys(input.lot_reception));
    assert.equal(Object.hasOwn(output,"confirmed"),false);
    assert.deepEqual(input,original);
  }
});

test("draft preparation rejects missing or malformed lot identities",()=>{
  for(const identity of [{},{lot_id:""},{lot_id:" "},{lot_id:5815},{scan_input:null},
    {scan_input:""},{lot_id:"LOT",scan_input:""},{lot_id:5815,scan_input:"P1"}]){
    assert.throws(()=>prepare(snapshot({...identity,records:[]}),false),{code:"invalid_snapshot"});
  }
  assert.throws(()=>prepare(snapshot({lot_id:"LOT",records:[null]}),false),{code:"invalid_snapshot"});
});

test("draft preparation preserves summary or inspector Reason origin without inventing it in legacy captures",()=>{
  for(const reason_source of [undefined,"defect_summary","inspector"]){
    const input=snapshot({lot_id:"LOT",records:[]});
    input.qc_header.reason="Scars: 3 fruits.";
    if(reason_source!==undefined)input.reason_source=reason_source;
    input.confirmed=true;const before=structuredClone(input);
    const output=prepare(input,false);
    assert.equal(output.reason_source,reason_source);
    assert.equal(Object.hasOwn(output,"reason_source"),reason_source!==undefined);
    assert.equal(output.qc_header.reason,input.qc_header.reason);
    assert.equal(Object.hasOwn(output,"confirmed"),false);
    assert.deepEqual(input,before);
  }
});

test("draft preparation rejects unknown Reason origin instead of silently changing it",()=>{
  for(const reason_source of [null,"","summary","DEFECT_SUMMARY",0,true,[],{}]){
    const input=snapshot({lot_id:"LOT",records:[]});input.reason_source=reason_source;
    assert.throws(()=>prepare(input,false),{code:"invalid_snapshot"});
  }
});

function reviewHistory(){return {
  initial:{
    vision_records:[{image_id:"INITIAL",total_fruits:12,oleocellosis_count:1,confirmed:"raw model metadata"}],
    qc_fields:{sample_count:12,oleocellosis:1,scars:2},
    inspection_summary:{total_fruits:12,oleocellosis_count:1},system_recommendation:"EXTEND"
  },
  additional:[{
    review_number:2,trigger_decision:"EXTEND",
    vision_records:[{image_id:"ADDITIONAL",total_fruits:12,oleocellosis_count:2,unknown:{confirmed:true}}],
    manual_defects:{scars:1},qc_fields:{sample_count:12,oleocellosis:2,scars:1},
    inspection_summary:{total_fruits:12,oleocellosis_count:2},observations:"Second box",
    system_recommendation_before:"EXTEND",system_recommendation_after:"COMPLETE"
  }]
};}

test("draft preparation preserves additional-review evidence and provisional choice without approving it",()=>{
  const input=snapshot({lot_id:"LOT",records:[]});
  input.saved_at="2026-11-15T12:00:00.000Z";
  const sample=input.samples[0];sample.review_choice="EXTEND";sample.review_history=reviewHistory();
  input.confirmed=true;input.final_decisions={S1:"EXTEND"};
  sample.inspector_confirmed=true;sample.inspector_final_decision="EXTEND";sample.confirmed_at="old approval";
  const before=structuredClone(input),output=prepare(input,true);
  assert.equal(output.samples[0].review_choice,"EXTEND");
  assert.deepEqual(output.samples[0].review_history,before.samples[0].review_history);
  assert.equal(output.samples[0].review_history.additional[0].trigger_decision,"EXTEND");
  for(const value of [output,output.samples[0]])for(const key of ["confirmed","final_decisions","inspector_confirmed","inspector_final_decision","confirmed_at"]){
    assert.equal(Object.hasOwn(value,key),false);
  }
  output.samples[0].review_history.additional[0].vision_records[0].total_fruits=99;
  assert.deepEqual(input,before);
});

test("old drafts do not acquire additional-review history or a provisional inspector choice",()=>{
  const input=snapshot({lot_id:"LOT",records:[]}),output=prepare(input,false);
  assert.equal(Object.hasOwn(output.samples[0],"review_history"),false);
  assert.equal(Object.hasOwn(output.samples[0],"review_choice"),false);
  for(const review_choice of ["","STANDARD","EXTEND","COMPLETE"]){
    input.samples[0].review_choice=review_choice;
    assert.equal(prepare(input,false).samples[0].review_choice,review_choice);
  }
});

test("malformed provisional choices and additional-review wrappers cannot replace a draft",()=>{
  for(const review_choice of [null,"APPROVED","expand","APPROVED",true,1,[],{}]){
    const input=snapshot({lot_id:"LOT",records:[]});input.samples[0].review_choice=review_choice;
    assert.throws(()=>prepare(input,false),{code:"invalid_snapshot"});
  }
  for(const review_history of [null,[],{}, {initial:[],additional:[]},{initial:{},additional:{}},
    {initial:{},additional:[null]},{initial:{},additional:[[]]}]){
    const input=snapshot({lot_id:"LOT",records:[]});input.samples[0].review_history=review_history;
    assert.throws(()=>prepare(input,false),{code:"invalid_snapshot"});
  }
});
