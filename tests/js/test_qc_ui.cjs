"use strict";

// The real UI functions run against a small DOM; no browser or DOM package is required.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const {test} = require("node:test");
const html = fs.readFileSync(path.join(__dirname,"../../src/smartfruit/web/index.html"),"utf8");

function source(name) {
  const match = new RegExp("^  (?:async )?function " + name + "\\(","m").exec(html);
  assert.ok(match,name + " exists");
  const firstLine=html.slice(match.index).split("\n",1)[0];
  if(firstLine.trimEnd().endsWith("}"))return firstLine;
  const rest = html.slice(match.index + match[0].length);
  const next = /\n  (?:async )?function /.exec(rest);
  assert.ok(next,name + " is followed by a function");
  return html.slice(match.index,match.index + match[0].length + next.index);
}

class Node {
  constructor(tag,text,className="") {
    this.tagName=tag.toUpperCase();this.textContent=text??"";this.className=className;
    this.children=[];this.parentElement=null;this.value="";this.style={};this.dataset={};
    this.attributes={};this.listeners={};this.hidden=false;this.readOnly=false;
    this.classList={add:(...names)=>{this.className=[this.className,...names].join(" ");}};
  }
  append(...nodes) {for(const node of nodes){node.remove();node.parentElement=this;this.children.push(node);}}
  replaceChildren(...nodes) {for(const node of [...this.children])node.remove();this.append(...nodes);}
  remove() {if(this.parentElement){const siblings=this.parentElement.children;siblings.splice(siblings.indexOf(this),1);this.parentElement=null;}}
  setAttribute(key,value) {this.attributes[key]=String(value);}
  getAttribute(key) {return this.attributes[key]??null;}
  removeAttribute(key) {delete this.attributes[key];delete this[key];}
  addEventListener(type,handler) {(this.listeners[type]??=[]).push(handler);}
  click() {for(const handler of this.listeners.click||[])handler({target:this});}
  contains(other) {return this===other||this.children.some(node=>node.contains(other));}
  matches(selector) {return selector.startsWith(".")?this.className.split(/\s+/).includes(selector.slice(1)):this.tagName===selector.toUpperCase();}
  querySelectorAll(selector) {const selectors=selector.split(",");return this.children.flatMap(node=>[...(selectors.some(part=>node.matches(part))?[node]:[]),...node.querySelectorAll(selector)]);}
  querySelector(selector) {return this.querySelectorAll(selector)[0]||null;}
  closest(selector) {for(let node=this;node;node=node.parentElement)if(node.matches(selector))return node;return null;}
  scrollIntoView() {}
  focus() {}
  checkValidity() {
    if(this.disabled||this.readOnly)return true;
    if(this.required&&this.value==="")return false;
    if(this.type==="number"&&this.value!==""){
      const number=Number(this.value);
      return Number.isFinite(number)&&(this.min===undefined||number>=Number(this.min))
        &&(this.max===undefined||number<=Number(this.max))&&(this.step!=="1"||Number.isInteger(number));
    }
    return true;
  }
  reportValidity() {return this.checkValidity();}
}

function setup(extraNames=[]) {
  const nodes=new Map();const element=(...args)=>new Node(...args);
  const byId=id=>{if(!nodes.has(id))nodes.set(id,element("div"));return nodes.get(id);};
  const state={config:{qc_columns:[]},samples:[],nextSample:1,lotReception:{lot_id:"LOT",records:[]},selectedPallet:"",workflowStep:3};
  const context=vm.createContext({
    state,byId,element,sourceNodes:new WeakMap(),headerControls:{lot_id:{value:"LOT"}},summaryControls:{},
    copy:structuredClone,window:{},document:{querySelectorAll(){return [];}},
    invalidate(){},refreshReceptionControls(){},captureChanged(){},updateCapturePresentation(){},setStep(){},status(){},error(message){throw Error(message);},
  });
  const constants=html.slice(html.indexOf("  const defectKeys ="),html.indexOf("  const headerControls ="));
  const names=["canonicalDecision","field","numberText","newBoxInspection","boxCaptureSummary","renderBoxCapture","updateBoxCapture","unambiguous","receptionTable","updateVision","updateReviewLocks","updateSampleTotal",
    "receiptValue","updateReceiptLocks","renderQCEditor","mountVisionCapture","addSample","mountQCRow","pendingDefects",
    "renderQCPallets","renderQCOverview","refreshWorkflow","selectQCPallet"];
  vm.runInContext(constants+"\n"+[...new Set([...names,...extraNames])].map(source).join("\n"),context);
  byId("inspection-form").append(byId("qc-editor-list"),byId("sample-list"));
  return {context,state,byId};
}

function reception(pallet,label) {
  const row={lot_id:"LOT",pallet_id:pallet,label_brand:label,size_declared:"42",packing_date:"2026-11-14",expected_count_per_box:"110"};
  return {pallet_id:pallet,qc_fields:{pallet_id:pallet,label_brand:label,size:"42",packing_date:row.packing_date},
    reception:{scan_input:pallet,records:[row]},receptionLot:"LOT"};
}

test("an inspector selects any pallet and skips another without inventing measurements",()=>{
  const {context,state,byId}=setup(["valueOf","collectPayload"]);
  const first=context.addSample(reception("P1","First")),second=context.addSample(reception("P2","Second"));
  assert.equal(first.inspectionStatus,"PENDING");
  context.selectQCPallet(second.serial);assert.equal(second.inspectionStatus,"SELECTED");assert.ok(second.selectedAt);
  second.startButton.click();assert.equal(second.inspectionStatus,"IN_PROGRESS");
  first.skipReasonControl.value="Muestreo QC";first.skipButton.click();
  assert.equal(first.inspectionStatus,"SKIPPED");assert.equal(first.skipReason,"Muestreo QC");
  const payload=context.collectPayload(),skipped=payload.samples[0];
  assert.equal(skipped.inspection_status,"SKIPPED");assert.equal(skipped.qc_fields,undefined);
  assert.equal(skipped.vision_records,undefined);assert.equal(skipped.box_inspection,undefined);
  assert.equal(payload.lot_reception.pallets[0].skip_reason,"Muestreo QC");
  context.renderQCOverview();
  const row=byId("qc-table-body").children[0];
  assert.equal(row.children[5].textContent,"No inspeccionada");
  assert.equal(row.children[3].textContent,"—");
  first.startButton.click();assert.equal(first.inspectionStatus,"IN_PROGRESS");assert.equal(first.skipReason,"");
  assert.equal(state.samples.length,2);
});

test("QUALITY INSPECTION keeps receipt fields in grouped forms and its overview contains no inputs",()=>{
  assert.match(html,/<h1>QUALITY INSPECTION<\/h1>/);
  const {context,state,byId}=setup();
  const first=context.addSample(reception("P1","Label one"));
  const second=context.addSample(reception("P2","Label two"));
  assert.equal(first.controls.label_brand.value,"Label one");
  assert.equal(first.controls.label_brand.readOnly,true);
  assert.equal(first.controls.pallet_id.readOnly,true);
  assert.equal(first.controls.avg_count_per_box.value,"");
  assert.equal(first.controls.decay.value,"");
  assert.deepEqual(first.qcEditor.querySelectorAll("legend").map(node=>node.textContent),["General Information","Condition","Quality"]);
  for(const sample of state.samples)for(const control of Object.values(sample.controls)){
    assert.ok(sample.qcEditor.contains(control));assert.ok(byId("inspection-form").contains(control));
    assert.equal(sample.card.contains(control),false);
  }
  const originalParent=first.controls.label_brand.parentElement;
  context.renderQCOverview();context.mountQCRow(first);
  assert.equal(first.controls.label_brand.parentElement,originalParent);
  assert.equal(byId("qc-table-body").querySelectorAll("input,select,textarea").length,0);
  assert.equal(byId("qc-editor-list").children.length,2);
  assert.equal(second.controls.label_brand.value,"Label two");
});

test("switching pallets preserves entered amounts and zero fill is explicit and isolated",()=>{
  const {context,state}=setup();const input=reception("P1","Original");const original=structuredClone(input.reception);
  const first=context.addSample(input),second=context.addSample(reception("P2","Other"));
  first.controls.sample_count.value="12";first.controls.decay.value="2";first.controls.scars.value="3";
  context.selectQCPallet(first.serial);assert.equal(first.qcEditor.hidden,false);assert.equal(second.qcEditor.hidden,true);
  context.selectQCPallet(second.serial);assert.equal(first.qcEditor.hidden,true);assert.equal(second.qcEditor.hidden,false);
  context.selectQCPallet(first.serial);assert.equal(first.controls.decay.value,"2");assert.equal(first.controls.scars.value,"3");
  assert.equal(first.controls.mold.value,"");assert.equal(second.controls.mold.value,"");
  first.zeroButton.click();assert.equal(first.controls.decay.value,"2");assert.equal(first.controls.mold.value,"0");
  assert.equal(first.controls.oleocellosis.value,"");assert.equal(second.controls.mold.value,"");
  assert.equal(first.controls.decay.max,"12");
  first.receiptButton.click();assert.equal(first.controls.label_brand.readOnly,false);
  first.controls.label_brand.value="Inspector correction";first.receiptButton.click();
  assert.equal(first.controls.label_brand.value,"Inspector correction");assert.deepEqual(first.reception,original);
  assert.equal(state.selectedPallet,String(first.serial));
});

test("native selector input then change switches pallet values without invalidating the inspection",()=>{
  const {context,state,byId}=setup(["handleInspectionEdit","invalidate"]);
  const first=context.addSample(reception("P1","First label"));
  const second=context.addSample(reception("P2","Second label"));
  for(const [sample,total,oleo,decay,size,note]of [
    [first,"12","1","2","42","First pallet note"],
    [second,"30","4","7","60","Second pallet note"],
  ]){
    sample.inspectionStatus="COMPLETED";
    Object.assign(sample.controls.sample_count,{value:total});
    Object.assign(sample.controls.oleocellosis,{value:oleo});
    Object.assign(sample.controls.decay,{value:decay});
    Object.assign(sample.controls.size,{value:size});
    sample.observations.value=note;
  }
  state.workflowStep=2;state.revision=42;state.evaluatedRevision=42;
  const report={samples:[{sample_id:first.id.value},{sample_id:second.id.value}]};
  const payload={qc_header:{lot_id:"LOT"}};
  state.report=report;state.payload=payload;
  first.inspectorChoice="STANDARD";second.inspectorChoice="EXTEND";
  byId("inspector-confirmation").checked=true;
  // Reproduce the real cascade: a bubbled edit refreshes the whole form.
  context.captureChanged=()=>context.refreshWorkflow();
  const selector=byId("vision-pallet-select");selector.id="vision-pallet-select";selector.tagName="SELECT";
  const binding=html.split("\n").find(line=>line.trim().startsWith('byId("vision-pallet-select").addEventListener("change",'));
  assert.ok(binding,"the actual selector change handler exists");
  vm.runInContext(binding,context);
  context.selectQCPallet(first.serial);
  function choose(sample){
    selector.value=String(sample.serial);
    // A native select emits input on the form before its own change handler.
    context.handleInspectionEdit({type:"input",target:selector});
    for(const handler of selector.listeners.change||[])handler({type:"change",target:selector});
    context.handleInspectionEdit({type:"change",target:selector});
  }
  choose(second);
  assert.equal(selector.value,String(second.serial));
  assert.equal(state.selectedPallet,String(second.serial));
  assert.equal(first.card.hidden,true);assert.equal(second.card.hidden,false);
  assert.equal(first.qcEditor.hidden,true);assert.equal(second.qcEditor.hidden,false);
  assert.equal(second.controls.label_brand.value,"Second label");
  assert.equal(second.controls.size.value,"60");
  assert.equal(second.controls.sample_count.value,"30");
  assert.equal(second.controls.oleocellosis.value,"4");
  assert.equal(second.controls.decay.value,"7");
  assert.equal(second.observations.value,"Second pallet note");
  choose(first);
  assert.equal(first.card.hidden,false);assert.equal(first.qcEditor.hidden,false);
  assert.equal(second.card.hidden,true);assert.equal(second.qcEditor.hidden,true);
  assert.equal(first.controls.label_brand.value,"First label");
  assert.equal(first.controls.sample_count.value,"12");
  assert.equal(first.controls.oleocellosis.value,"1");
  assert.equal(first.controls.decay.value,"2");
  assert.equal(first.observations.value,"First pallet note");
  assert.equal(state.revision,42);assert.equal(state.evaluatedRevision,42);
  assert.equal(state.report,report);assert.equal(state.payload,payload);
  assert.equal(first.inspectorChoice,"STANDARD");assert.equal(second.inspectorChoice,"EXTEND");
  assert.equal(byId("inspector-confirmation").checked,true);
});

test("Vision derives a readonly Sample from unique JSONs and requires explicit box completion",()=>{
  const {context,byId}=setup(["valueOf","collectPayload","validateForEvaluation"]);
  const first={image_id:"FIRST",total_fruits:12,oleocellosis_count:1,fruit_predictions:[]};
  const second={image_id:"SECOND",total_fruits:8,oleocellosis_count:2,fruit_predictions:[]};
  const sample=context.addSample({...reception("P1","Original"),records:[first,structuredClone(first),second]});
  assert.equal(sample.card.querySelectorAll("select").length,0);
  assert.equal(Object.hasOwn(sample,"coverage"),false);
  assert.equal(sample.controls.sample_count.value,"20");
  assert.equal(sample.controls.sample_count.readOnly,true);
  assert.equal(sample.controls.oleocellosis.value,"3");
  assert.equal(context.collectPayload().samples[0].vision_covers_sample,false);
  assert.ok(byId("inspection-form").contains(sample.controls.sample_count));
  sample.zeroButton.click();assert.throws(()=>context.validateForEvaluation(),/Finaliza la inspección/);
  sample.boxControls.finish.click();
  assert.equal(context.collectPayload().samples[0].vision_covers_sample,true);
  assert.doesNotThrow(()=>context.validateForEvaluation());
  sample.clearFiles.click();
  assert.equal(sample.controls.sample_count.value,"");
  assert.equal(sample.controls.oleocellosis.value,"");
  assert.equal(context.collectPayload().samples[0].vision_covers_sample,false);
  assert.throws(()=>context.validateForEvaluation(),/Finaliza la inspección/);
});

test("a legacy partial-coverage draft uses the actual JSON count and remains an unfinished box",()=>{
  const {context}=setup(["valueOf","collectPayload","draftSnapshot"]);
  const values={...reception("P1","Original"),restore:true,coverage_choice:"false",
    records:[{image_id:"SAVED",total_fruits:12,oleocellosis_count:2,fruit_predictions:[]}],
    observations:"Saved inspector note"};
  values.qc_fields={...values.qc_fields,sample_count:"100",oleocellosis:"20",scars:"3"};
  const before=structuredClone(values),sample=context.addSample(values);
  assert.equal(sample.card.querySelectorAll("select").length,0);
  assert.equal(Object.hasOwn(sample,"coverage"),false);
  assert.equal(sample.controls.sample_count.value,"12");
  assert.equal(sample.controls.sample_count.readOnly,true);
  assert.equal(sample.controls.oleocellosis.value,"2");
  assert.equal(sample.controls.scars.value,"3");
  assert.equal(sample.observations.value,"Saved inspector note");
  assert.equal(context.collectPayload().samples[0].vision_covers_sample,false);
  assert.equal(context.draftSnapshot().samples[0].coverage_choice,"false");
  assert.deepEqual(values,before);
});
