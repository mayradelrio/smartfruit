"use strict";

const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const {test}=require("node:test");
const {IDBFactory}=require("fake-indexeddb");
const {createStore}=require("../../src/smartfruit/web/drafts.js");
const html=fs.readFileSync(path.join(__dirname,"../../src/smartfruit/web/index.html"),"utf8");
const keys=["decay","styler","mold","soft","skin_breakdown","wounds","int_dryness","black_tips","skin_defect","scars","white_stain","blanching","yellow_color","stain","undersize"];

function source(name){
  const match=new RegExp("^  (?:async )?function "+name+"\\(","m").exec(html);assert.ok(match,name+" exists");
  const first=html.slice(match.index).split("\n",1)[0];if(first.trimEnd().endsWith("}"))return first;
  const rest=html.slice(match.index+match[0].length),next=/\n  (?:async )?function /.exec(rest);assert.ok(next);
  return html.slice(match.index,match.index+match[0].length+next.index);
}
class Node{
  constructor(tag="div",text="",className=""){this.tagName=tag.toUpperCase();this.textContent=text;this.className=className;this.children=[];this.value="";this.listeners={};this.hidden=false;}
  append(...items){this.children.push(...items);}
  replaceChildren(...items){this.children=items;}
  addEventListener(type,callback){(this.listeners[type]??=[]).push(callback);}
  dispatch(type){for(const callback of this.listeners[type]||[])callback({target:this,stopPropagation(){}});}
  click(){this.dispatch("click");}
}
function setup(extra=[]){
  const byName=new Map(),byId=name=>{if(!byName.has(name))byName.set(name,new Node());return byName.get(name);};
  const state={samples:[],revision:1,report:{approved:false},payload:{},evaluatedRevision:1,workflowStep:4,demoMode:true,reasonSource:"defect_summary"};
  const calls={capture:0,status:[]},headerControls={lot_id:{value:"LOT"}},summaryControls={};
  const sample={serial:1,id:{value:"S1"},controls:{pallet_id:{value:"P1"}},records:[{image_id:"INITIAL",total_fruits:150,oleocellosis_count:0}],imageBindings:[],observations:{value:"Initial notes"},inspectorChoice:"EXPAND",
    boxInspection:{sample_box_id:"BOX_001",status:"completed",coverage_confirmed:true,manifest_record_index:null},
    pendingAdditional:{visionRecords:[{image_id:"EXTRA_1",total_fruits:12,oleocellosis_count:1,confirmed:"raw Vision metadata"},{image_id:"EXTRA_2",total_fruits:11,oleocellosis_count:2}],boxInspection:{sample_box_id:"BOX_002",status:"completed",coverage_confirmed:true,manifest_record_index:null},summary:{images_processed:2,total_fruits:23,oleocellosis_count:3,oleocellosis_pct:300/23},context:{lot_id:"LOT",pallet_id:"P1",sample_id:"S1"}},
    additionalControls:Object.fromEntries(keys.map(key=>[key,{value:key==="decay"?"1":""}])),additionalObservations:{value:"Second box still pending"},additionalBody:new Node(),
  };
  state.samples.push(sample);
  const context=vm.createContext({state,byId,headerControls,summaryControls,copy:structuredClone,defectKeys:new Set([...keys,"oleocellosis"]),
    element:(...args)=>new Node(...args),fallbackColumns:keys.map(key=>({key,label:key,group:"condition"})),
    field(key,label){return {input:new Node("input"),wrap:new Node("label",label)};},
    captureChanged(){calls.capture++;},status(message){calls.status.push(message);},refreshReceptionControls(){},updateCapturePresentation(){},numberText:String,
    renderBoxCapture(){},busy:action=>action(),setStep(){},unambiguous(){return "LOT";},receptionFromSample(){return null;},
    addSample(values){state.samples.push({serial:state.samples.length+1,id:{value:values.sample_id},controls:{pallet_id:{value:values.pallet_id}},records:values.records,imageBindings:values.image_bindings,observations:{value:values.observations},boxInspection:values.box_inspection});},
  });
  const names=["pendingAdditionalContext","samePendingContext","sameVisionRecord","pendingAdditionalSnapshot","retainPendingAdditional","decodePendingAdditional","ensureNoPendingAdditional","draftSnapshot","invalidate","renderAdditionalForm","discardPendingAdditional","restoreSnapshot","canonicalDecision","ensureCurrent",...extra];
  vm.runInContext([...new Set(names)].map(source).join("\n"),context);
  return {context,state,sample,calls,byId,headerControls};
}

test("pending photos, raw manual blanks, closure and context survive durable draft recovery without approval",async()=>{
  const {context,sample}=setup();
  const input=context.draftSnapshot();input.confirmed=true;input.samples[0].pending_additional.inspector_confirmed=true;
  const store=createStore({indexedDB:new IDBFactory(),databaseName:"pending-box-roundtrip"});
  await store.save(input);const saved=await store.load(),pending=saved.samples[0].pending_additional;
  assert.equal(Object.hasOwn(saved,"confirmed"),false);
  assert.equal(Object.hasOwn(pending,"inspector_confirmed"),false);
  assert.deepEqual(pending.vision_records,sample.pendingAdditional.visionRecords);
  assert.equal(pending.vision_records[0].confirmed,"raw Vision metadata");
  assert.equal(pending.manual_defects.decay,"1");assert.equal(pending.manual_defects.scars,"");
  assert.equal(pending.box_inspection.status,"completed");assert.equal(pending.observations,"Second box still pending");
  context.restoreSnapshot(saved);
  const recovered=context.state.samples[0];
  assert.equal(recovered.pendingAdditional.summary.total_fruits,23);
  assert.equal(recovered.pendingAdditional.summary.oleocellosis_count,3);
  assert.equal(recovered.pendingAdditional.manualValues.scars,"");
  assert.equal(recovered.inspectorChoice,"");assert.equal(context.state.report,null);
  assert.equal(context.state.evaluatedRevision,null);assert.equal(recovered.pendingAdditional.needsReview,true);
  assert.throws(()=>context.ensureCurrent(),/Evalúa de nuevo/);
  assert.match(context.byId("draft-recovery-note").textContent,/cajas adicionales pendientes/);
});

test("editing initial QC withdraws evaluation and preserves pending box observations for later EXTEND",()=>{
  const {context,state,sample}=setup();const before=structuredClone(sample.pendingAdditional.visionRecords);
  context.invalidate();
  assert.equal(state.report,null);assert.equal(sample.inspectorChoice,"");
  assert.deepEqual(sample.pendingAdditional.visionRecords,before);
  assert.equal(sample.pendingAdditional.manualValues.decay,"1");
  assert.equal(sample.pendingAdditional.manualValues.scars,"");
  assert.equal(sample.pendingAdditional.observations,"Second box still pending");
  assert.equal(sample.pendingAdditional.needsReview,true);
  sample.additionalControls=null;sample.additionalObservations=null;
  context.renderAdditionalForm(sample);
  assert.equal(sample.additionalControls.decay.value,"1");assert.equal(sample.additionalControls.scars.value,"");
  assert.equal(sample.additionalObservations.value,"Second box still pending");
});

test("manual edits, notes and explicit zero entry update the pending draft without approving a report",()=>{
  const {context,sample,calls}=setup();context.renderAdditionalForm(sample);
  sample.additionalControls.scars.value="2";sample.additionalControls.scars.dispatch("input");
  sample.additionalObservations.value="Checked physical count";sample.additionalObservations.dispatch("input");
  sample.additionalBody.children.find(node=>node.textContent==="Registrar pendientes de esta caja en 0").click();
  const snapshot=context.draftSnapshot().samples[0].pending_additional;
  assert.equal(snapshot.manual_defects.scars,"2");assert.equal(snapshot.manual_defects.decay,"1");
  assert.equal(snapshot.manual_defects.mold,"0");assert.equal(snapshot.observations,"Checked physical count");
  assert.equal(calls.capture,3);
});

test("a pending box blocks final confirmation until explicitly incorporated or discarded",()=>{
  const {context,sample,state,calls}=setup();
  assert.throws(()=>context.ensureNoPendingAdditional(),/caja adicional pendiente/);
  const original=structuredClone(sample.records),initialBox=structuredClone(sample.boxInspection);
  context.renderAdditionalForm(sample);
  sample.additionalBody.children.find(node=>node.textContent==="Descartar caja adicional pendiente").click();
  assert.equal(sample.pendingAdditional,null);assert.deepEqual(sample.records,original);assert.deepEqual(sample.boxInspection,initialBox);
  assert.doesNotThrow(()=>context.ensureNoPendingAdditional());
  assert.equal(state.report.approved,false);assert.equal(calls.capture,1);
});

test("a pending box from another context cannot overwrite a durable draft or partly restore the UI",async()=>{
  const {context,state}=setup();const valid=context.draftSnapshot();
  const store=createStore({indexedDB:new IDBFactory(),databaseName:"pending-context"});await store.save(valid);
  const invalid=structuredClone(valid);invalid.samples[0].pending_additional.context.pallet_id="OTHER";
  await assert.rejects(store.save(invalid),{code:"invalid_snapshot"});
  assert.equal((await store.load()).samples[0].pending_additional.context.pallet_id,"P1");
  const before=structuredClone(state.samples[0].pendingAdditional);
  assert.throws(()=>context.restoreSnapshot(invalid),/contexto recuperables/);
  assert.deepEqual(state.samples[0].pendingAdditional,before);
});

test("identical additional JSON with reordered keys does not reopen a completed pending box or add fruits",async()=>{
  const {context,state,sample}=setup(["stageAdditionalReview"]);
  context.ensureCurrent=()=>{};context.lockCaptureInputs=()=>()=>{};context.collectPayload=()=>({});
  context.request=async()=>({async json(){return {inspection_summary:{total_fruits:23}};}});
  const original=sample.pendingAdditional.visionRecords[0];
  await context.stageAdditionalReview(sample,[{confirmed:original.confirmed,oleocellosis_count:original.oleocellosis_count,total_fruits:original.total_fruits,image_id:original.image_id}]);
  assert.equal(sample.pendingAdditional.visionRecords.length,2);assert.equal(sample.pendingAdditional.summary.total_fruits,23);
  assert.equal(sample.pendingAdditional.boxInspection.status,"completed");
  assert.equal(sample.additionalControls.decay.value,"1");assert.equal(state.report.approved,false);
});
