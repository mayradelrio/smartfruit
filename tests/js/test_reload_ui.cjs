"use strict";

// Reload must preserve saved work without reopening its lot before the inspector chooses it.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");
const html = fs.readFileSync(path.join(__dirname,"../../src/smartfruit/web/index.html"),"utf8");

function source(name) {
  const match = new RegExp("^  (?:async )?function " + name + "\\(","m").exec(html);
  assert.ok(match,name + " exists");
  const rest = html.slice(match.index + match[0].length);
  const next = /\n  (?:async )?function /.exec(rest);
  assert.ok(next,name + " is followed by a function");
  return html.slice(match.index,match.index + match[0].length + next.index);
}

class Node {
  constructor(tag,text) {
    this.tagName=tag.toUpperCase();this.textContent=text??"";this.children=[];
    this.value="";this.hidden=true;this.dataset={};this.attributes={};this.style={};
  }
  append(...nodes) {this.children.push(...nodes);}
  replaceChildren(...nodes) {this.children=[...nodes];if(this.tagName==="SELECT")this.value=nodes[0]?.value??"";}
  setAttribute(key,value) {this.attributes[key]=String(value);}
  removeAttribute(key) {delete this.attributes[key];}
  querySelectorAll() {return [];}
  focus() {}
}

function snapshot() {
  return {version:1,saved_at:"2026-11-14T14:00:00.000Z",workflow_step:3,
    qc_header:{lot_id:"5815",inspection_date:"2026-11-14",reason:"",Level_Flag:""},
    qc_summary:{label_brand:"Paramount"},reason_source:"defect_summary",
    lot_reception:{lot_id:"5815",records:[{lot_id:"5815",pallet_id:"5645",label_brand:"Paramount"}]},
    samples:[{sample_id:"S1",pallet_id:"5645",qc_fields:{pallet_id:"5645",label_brand:"Paramount",scars:"2"},
      vision_records:[{image_id:"IMG_TEST",total_fruits:12,oleocellosis_count:1}],
      image_bindings:[{image_id:"IMG_TEST",lot_id:"5815",pallet_id:"5645",sample_id:"S1"}],
      coverage_choice:"true",observations:"Saved inspector note"}],
    observations:"Keep this saved work",inspector_name:"Inspector saved",demo_mode:false};
}

function setup(names,{saved=snapshot(),manifest}={}) {
  const nodes=new Map();const element=(...args)=>new Node(...args);
  const byId=id=>{if(!nodes.has(id))nodes.set(id,element(id==="scan-lot"?"select":"div"));return nodes.get(id);};
  const calls={loaded:0,saved:0,cleared:0,restored:[],opened:0,status:[],manifestReady:[]};
  const state={config:{},samples:[],workflowStep:1,lotReception:null,receptionSelection:null,
    activeReception:null,manifestCsv:null,draftReady:false,draftBlocked:false,draftPaused:false,
    draftEpoch:0,draftEdit:0,scanRevision:0,restoring:false,finalized:false,pendingDraft:null};
  const store={
    async load(){calls.loaded++;return saved===null?null:structuredClone(saved);},
    async save(){calls.saved++;throw Error("Reload must not overwrite saved work");},
    async clear(){calls.cleared++;throw Error("Reload must not delete saved work");},
    async flush(){},
  };
  const context=vm.createContext({
    state,byId,element,copy:structuredClone,headerControls:{lot_id:{value:""}},summaryControls:{},
    window:{SmartFruitDrafts:{createStore(){return store;}},confirm(){return true;}},
    clearTimeout,setTimeout,
    setDraftStatus(message){calls.status.push(message);},status(message){calls.status.push(message);},clearError(){},
    refreshReceptionControls(){},refreshWorkflow(){},updateCapturePresentation(){},showPersistence(){},
    clearReceptionSelection(){state.receptionSelection=null;state.scanRevision++;},
    async busy(action){await action();},
    async receptionStorage(action){assert.equal(action,"get");return manifest;},
    async request(){return {async json(){return {records:[{lot_id:"5815",pallet_id:"5645"}],lot_ids:["5815"],pallets_count:1};}};},
    async manifestReady(...args){calls.manifestReady.push(args);},
    async openSelectedLot(){calls.opened++;state.receptionSelection={lot_id:byId("scan-lot").value};},
    restoreSnapshot(value){calls.restored.push(structuredClone(value));state.samples=structuredClone(value.samples);state.lotReception=structuredClone(value.lot_reception);state.workflowStep=value.workflow_step;},
  });
  vm.runInContext(names.map(source).join("\n"),context);
  return {context,state,byId,calls,store};
}

test("a remembered manifest is restored as a catalogue without opening its old lot",async()=>{
  const manifest={filename:"Saved manifest.csv",manifest_csv:"CSV-FROM-STORAGE"};
  const {context,state,calls}=setup(["restoreManifest"],{manifest});
  await context.restoreManifest();
  assert.equal(calls.manifestReady.length,1);
  const [csv,filename,info,options]=calls.manifestReady[0];
  assert.equal(csv,manifest.manifest_csv);assert.equal(filename,manifest.filename);
  assert.deepEqual(info.lot_ids,["5815"]);assert.equal(options.autoSelect,false);
  assert.equal(calls.opened,0);assert.equal(state.receptionSelection,null);
  assert.equal(state.samples.length,0);assert.equal(state.lotReception,null);
});

test("a newly uploaded one-lot CSV still prepares its lot, but a restored CSV does not",async()=>{
  const info={records:[{lot_id:"5815",pallet_id:"5645"}],lot_ids:["5815"],pallets_count:1};
  const fresh=setup(["manifestReady"]);
  await fresh.context.manifestReady("FRESH-CSV","New manifest.csv",info);
  assert.equal(fresh.calls.opened,1);assert.equal(fresh.byId("scan-lot").value,"5815");
  const reloaded=setup(["manifestReady"]);
  await reloaded.context.manifestReady("SAVED-CSV","Saved manifest.csv",info,{autoSelect:false});
  assert.equal(reloaded.calls.opened,0);assert.equal(reloaded.byId("scan-lot").value,"");
  assert.equal(reloaded.state.receptionSelection,null);assert.equal(reloaded.state.lotReception,null);
});

test("reload offers saved work without applying, overwriting or deleting the saved inspection",async()=>{
  const saved=snapshot(),before=structuredClone(saved);
  const {context,state,calls}=setup(["restoreDraft"],{saved});
  await context.restoreDraft();
  assert.equal(calls.loaded,1);assert.equal(calls.restored.length,0);
  assert.equal(calls.saved,0);assert.equal(calls.cleared,0);
  assert.equal(state.samples.length,0);assert.equal(state.lotReception,null);
  assert.equal(state.workflowStep,1);assert.equal(state.draftReady,true);
  assert.deepEqual(saved,before);
});

test("the saved lot resumes only after the inspector explicitly chooses to continue",async()=>{
  const saved=snapshot(),before=structuredClone(saved);
  const {context,state,calls}=setup(["restoreDraft","resumeSavedDraft"],{saved});
  await context.restoreDraft();assert.equal(calls.restored.length,0);
  await context.resumeSavedDraft();
  assert.equal(calls.restored.length,1);assert.deepEqual(calls.restored[0],before);
  assert.equal(state.lotReception.lot_id,"5815");assert.equal(state.samples[0].qc_fields.scars,"2");
  assert.equal(calls.saved,0);assert.equal(calls.cleared,0);assert.deepEqual(saved,before);
});

test("reload with no saved inspection keeps reception empty",async()=>{
  const {context,state,calls}=setup(["restoreDraft"],{saved:null});
  await context.restoreDraft();
  assert.equal(state.workflowStep,1);assert.equal(state.samples.length,0);
  assert.equal(state.lotReception,null);assert.equal(calls.restored.length,0);
  assert.equal(calls.saved,0);assert.equal(calls.cleared,0);
});

test("another lot cannot overwrite a saved inspection that has not been resumed or discarded",async()=>{
  const {context,state,calls}=setup(["restoreDraft","startLot","saveActiveDraft"]);
  await context.restoreDraft();
  assert.throws(()=>context.startLot({lot_id:"OTHER",selection_mode:"lot",records:[]}),/borrador|continuar|retoma|guardad/i);
  assert.equal(state.samples.length,0);assert.equal(state.lotReception,null);
  state.samples=[{sample_id:"Other capture"}];state.draftPaused=false;
  assert.equal(await context.saveActiveDraft(),false);
  assert.equal(calls.saved,0);assert.equal(calls.cleared,0);
});
