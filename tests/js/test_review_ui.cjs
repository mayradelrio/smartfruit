"use strict";

// Exercise the actual review functions without browser or npm-only dependencies.
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
    this.tagName=tag.toUpperCase();this.children=[];this._text=String(text??"");this.className=className;
    this.parentElement=null;this.value="";this.style={};this.dataset={};this.attributes={};
    this.listeners={};this.hidden=false;this.readOnly=false;this.checked=false;
  }
  set textContent(value) {this._text=String(value??"");this.children=[];}
  get textContent() {return this._text+this.children.map(node=>node.textContent).join("");}
  append(...nodes) {for(const node of nodes){node.remove();node.parentElement=this;this.children.push(node);}}
  replaceChildren(...nodes) {for(const node of [...this.children])node.remove();this._text="";this.append(...nodes);}
  remove() {if(this.parentElement){const siblings=this.parentElement.children;siblings.splice(siblings.indexOf(this),1);this.parentElement=null;}}
  setAttribute(key,value) {this.attributes[key]=String(value);}
  getAttribute(key) {return this.attributes[key]??null;}
  removeAttribute(key) {delete this.attributes[key];}
  addEventListener(type,handler) {(this.listeners[type]??=[]).push(handler);}
  matches(selector) {
    if(selector[0]==="#")return this.id===selector.slice(1);
    if(selector[0]===".")return this.className.split(/\s+/).includes(selector.slice(1));
    const match=/^(\w+)?(?:\[([^=\]]+)(?:=["']?([^"'\]]+)["']?)?\])?$/.exec(selector);
    if(!match)return false;
    if(match[1]&&this.tagName!==match[1].toUpperCase())return false;
    if(!match[2])return true;
    const key=match[2];const value=key.startsWith("data-")?this.dataset[key.slice(5).replace(/-([a-z])/g,(_,letter)=>letter.toUpperCase())]:this.getAttribute(key);
    return match[3]===undefined?value!==undefined&&value!==null:String(value)===match[3];
  }
  querySelectorAll(selector) {const selectors=selector.split(",");return this.children.flatMap(node=>[...(selectors.some(part=>node.matches(part.trim()))?[node]:[]),...node.querySelectorAll(selector)]);}
  querySelector(selector) {return this.querySelectorAll(selector)[0]||null;}
  closest(selector) {for(let node=this;node;node=node.parentElement)if(node.matches(selector))return node;return null;}
  contains(other) {return this===other||this.children.some(node=>node.contains(other));}
  scrollIntoView() {}
  focus() {}
}

function setup(names) {
  const nodes=new Map(),element=(...args)=>new Node(...args);
  const byId=id=>{if(!nodes.has(id)){const node=element("div");node.id=id;nodes.set(id,node);}return nodes.get(id);};
  const headerControls=Object.fromEntries(Object.entries({
    lot_id:"LOT",inspection_date:"2026-11-14",Level_Flag:"",reason:"",remarks:"Original remarks",grade:"",color:"",plu_pct:""
  }).map(([key,value])=>{const node=element("input");node.value=value;node.name=key;node.id="header-"+key;return [key,node];}));
  const keys=["decay","styler","mold","soft","skin_breakdown","oleocellosis","wounds","int_dryness","black_tips","skin_defect","scars","white_stain","blanching","yellow_color","stain","undersize"];
  const state={config:{},samples:[],revision:7,evaluatedRevision:7,workflowStep:4,generatedReason:"",reasonSource:"defect_summary"};
  for(const [index,pallet]of ["P1","P2"].entries()){
    const controls={};
    for(const [key,value]of Object.entries({pallet_id:pallet,sample_count:"12",...Object.fromEntries(keys.map(key=>[key,key==="scars"?String(index+1):"0"]))})){
      const control=element("input");control.value=value;control.name=key;controls[key]=control;
    }
    state.samples.push({serial:index+1,id:{value:"S"+(index+1)},controls,records:[{image_id:"IMG"+index}],imageBindings:[],observations:{value:""}});
  }
  for(const [key,control]of Object.entries(headerControls))byId(key==="reason"?"reason-field":["Level_Flag","remarks","grade","color","plu_pct"].includes(key)?"final-header-fields":"header-fields").append(control);
  const summaryControls={};
  const context=vm.createContext({
    state,byId,element,headerControls,summaryControls,defectKeys:new Set(keys),decisions:["STANDARD","EXTEND","COMPLETE"],
    sourceNodes:new WeakMap(),copy:structuredClone,captureChanged(){},scheduleDraft(){},status(){},
    document:{querySelectorAll(){return [];}},window:{confirm(){return true;}},
    renderReviewHistory(){return null;},
    renderAdditionalReview(sample){const panel=element("section");panel.hidden=sample.inspectorChoice!=="EXTEND";sample.additionalPanel=panel;return panel;},
  });
  const columns=html.slice(html.indexOf("  const fallbackColumns ="),html.indexOf("  const fallbackHeaders ="));
  vm.runInContext(columns+"\n"+names.map(source).join("\n"),context);
  return {context,state,byId,headerControls};
}

function reportFor(state) {
  const samples=state.samples.map((sample,index)=>({
    sample_id:sample.id.value,pallet_id:sample.controls.pallet_id.value,
    qc_fields:Object.fromEntries(Object.entries(sample.controls).map(([key,control])=>[key,key==="pallet_id"?control.value:Number(control.value)])),
    inspection_summary:{total_fruits:12,oleocellosis_count:0,oleocellosis_pct:0},
    business_severity:{business_max_level:index+1,quality_max_level:index+1,condition_max_level:1,reasons:["Scars"]},
    final_recommendation:index?"EXTEND":"STANDARD",recommendation_reasons:["Scars"],predictive:{enabled:false},
  }));
  return {qc_header:{lot_id:"LOT",Level_Flag:"",reason:""},samples,generated_reason:"Scars: 3 fruits in 2 of 2 pallets (12.5%).",
    lot_summary:{pallet_count:2,sample_count:24,total_defect_incidents:3,total_combined_pct:12.5,
      defects:[{key:"scars",label:"Scars",count:3,pct:12.5,affected_pallets:2,inspected_pallets:2}]}};
}

test("all pallet results appear before the inspector's final report fields",()=>{
  const order=["results","reason-field","final-header-fields","inspector-decisions"].map(id=>html.indexOf('id="'+id+'"'));
  assert.ok(order.every(index=>index>=0));
  assert.deepEqual([...order].sort((a,b)=>a-b),order);
});

const reviewFunctions=["canonicalDecision","decisionLabel","setInspectorChoice","renderInspectorDecisionSummary","field","numberText","valueOf","collectPayload","invalidate","reviewAssessment",
  "syncReviewMetadata","handleInspectionEdit","updateReasonSource","applyGeneratedReason","renderLotSummary","renderResults","ensureCurrent"];

test("suggestions for every pallet are visible before any final decision is selected",()=>{
  const {context,state,byId}=setup(reviewFunctions);
  const report=reportFor(state);state.report=report;state.payload=context.collectPayload();
  context.renderResults(report);
  assert.equal(byId("results").querySelectorAll("article").length,2);
  assert.match(byId("results").textContent,/P1/);assert.match(byId("results").textContent,/P2/);
  assert.match(byId("results").textContent,/STANDARD/);assert.match(byId("results").textContent,/EXTEND/);
  assert.equal(byId("inspector-decisions").querySelectorAll("select").length,0);
  const decisions=byId("results").querySelectorAll("select[data-sample-id]");
  assert.equal(decisions.length,2);
  assert.ok(decisions.every(control=>control.value===""));
  assert.equal(byId("inspector-confirmation").checked,false);
});

test("Reason starts from the defect summary without replacing Remarks or assigning Level Flag",()=>{
  const {context,state,headerControls}=setup(reviewFunctions);
  const report=reportFor(state);state.report=report;state.payload=context.collectPayload();
  context.renderLotSummary(report);context.syncReviewMetadata();
  assert.equal(headerControls.reason.value,report.generated_reason);
  assert.equal(headerControls.reason.readOnly,true);
  assert.equal(state.payload.qc_header.reason,report.generated_reason);
  assert.equal(state.report.qc_header.reason,report.generated_reason);
  assert.equal(headerControls.remarks.value,"Original remarks");
  assert.equal(headerControls.Level_Flag.value,"");
  assert.equal(state.report.samples[1].final_recommendation,"EXTEND");
  context.ensureCurrent();
});

test("the inspector can decide after the suggestions while QC edits require reevaluation",()=>{
  const {context,state,byId,headerControls}=setup(reviewFunctions);
  const report=reportFor(state);state.report=report;
  context.applyGeneratedReason(report);state.payload=context.collectPayload();context.renderResults(report);
  const results=byId("results").children[0];
  const decisions=byId("results").querySelectorAll("select[data-sample-id]");
  context.setInspectorChoice("S1","STANDARD");context.setInspectorChoice("S2","EXTEND");
  byId("inspector-confirmation").checked=true;
  headerControls.Level_Flag.value="2";
  context.handleInspectionEdit({target:headerControls.Level_Flag});
  assert.equal(state.revision,7);assert.equal(state.evaluatedRevision,7);
  assert.equal(byId("results").children[0],results);
  assert.equal(state.payload.qc_header.Level_Flag,2);
  assert.equal(state.report.qc_header.Level_Flag,2);
  assert.equal(decisions[1].value,"EXTEND");assert.equal(byId("inspector-confirmation").checked,false);
  context.ensureCurrent();
  state.reasonSource="inspector";headerControls.reason.readOnly=false;
  headerControls.reason.value="Scars summary reviewed by QC.";
  context.handleInspectionEdit({target:headerControls.reason});context.ensureCurrent();
  assert.equal(state.payload.qc_header.reason,headerControls.reason.value);
  assert.equal(byId("results").children[0],results);
  state.samples[0].controls.scars.value="3";
  context.handleInspectionEdit({target:state.samples[0].controls.scars});
  assert.equal(state.report,null);assert.equal(byId("results").children.length,0);
  assert.equal(byId("inspector-decisions").children.length,0);
  assert.throws(()=>context.ensureCurrent(),/Evalúa de nuevo/);
});

test("editing final metadata cannot accept an unassessed change to pallet measurements",()=>{
  const {context,state,headerControls}=setup(reviewFunctions);
  const report=reportFor(state);state.report=report;
  context.applyGeneratedReason(report);state.payload=context.collectPayload();
  state.samples[0].controls.scars.value="8";
  headerControls.Level_Flag.value="2";
  context.handleInspectionEdit({target:headerControls.Level_Flag});
  assert.throws(()=>context.ensureCurrent(),/Evalúa de nuevo/);
  assert.equal(state.report,null);
});

test("a pallet with no QC-confirmed oleocellosis hides stale photos without hiding another pallet's evidence",()=>{
  const {context,state,byId}=setup(reviewFunctions);
  const report=reportFor(state);
  const rejected={defect:"oleocellosis",sample_box_id:"BOX_001",view:"fruit_crop",
    image_data_url:"data:image/png;base64,iVBORw0KGgo=",affected_fruits:1,
    vision_reviews:[{review_status:"rejected"}]};
  report.samples[0].evidence_photos=[rejected];
  report.samples[0].evidence_summary={status:"available",positive_fruits:1};
  report.samples[1].qc_fields.oleocellosis=1;
  report.samples[1].inspection_summary.oleocellosis_count=1;
  report.samples[1].inspection_summary.oleocellosis_pct=100/12;
  report.samples[1].evidence_photos=[{...rejected,vision_reviews:[{review_status:"confirmed"}]}];
  report.samples[1].evidence_summary={status:"available",positive_fruits:1};
  context.renderResults(report);
  const [healthy,positive]=byId("results").querySelectorAll("article");
  assert.equal(healthy.querySelectorAll("img").length,0);
  assert.equal(healthy.querySelectorAll(".vision-positive-gallery").length,0);
  assert.doesNotMatch(healthy.textContent,/Evidencia de oleocelosis|No hay fotografías disponibles/);
  assert.equal(positive.querySelectorAll("img").length,1);
  assert.equal(positive.querySelectorAll(".vision-positive-gallery").length,1);
  assert.match(positive.textContent,/Evidencia de oleocelosis/);
});

test("a pallet with no QC-confirmed oleocellosis does not report missing photos from a stale evidence summary",()=>{
  const {context,state,byId}=setup(reviewFunctions);
  const report=reportFor(state);
  report.samples[0].evidence_photos=[];
  report.samples[0].evidence_summary={status:"unavailable",positive_fruits:2,unavailable_fruits:2};
  context.renderResults(report);
  const healthy=byId("results").querySelectorAll("article")[0];
  assert.equal(healthy.querySelectorAll(".vision-positive-gallery").length,0);
  assert.doesNotMatch(healthy.textContent,/No hay fotografías disponibles/);
});

test("a partially corrected pallet displays only its confirmed photographic evidence",()=>{
  const {context,state,byId}=setup(reviewFunctions);
  const report=reportFor(state),sample=report.samples[0];
  sample.inspection_summary.oleocellosis_count=1;
  sample.evidence_summary={status:"available",positive_fruits:2};
  sample.evidence_photos=[
    {defect:"oleocellosis",image_data_url:"data:image/jpeg;base64,REJECTED",
      vision_reviews:[{review_status:"rejected"}]},
    {defect:"oleocellosis",image_data_url:"data:image/jpeg;base64,CONFIRMED",
      vision_reviews:[{review_status:"confirmed"}]},
  ];
  context.renderResults(report);
  const images=byId("results").querySelectorAll("article")[0].querySelectorAll("img");
  assert.equal(images.length,1);
  assert.equal(images[0].src,"data:image/jpeg;base64,CONFIRMED");
});

test("explicitly excluded audited photos are hidden while mixed groups and legacy attachments remain visible",()=>{
  const {context,state,byId}=setup(reviewFunctions);
  const report=reportFor(state),sample=report.samples[0];
  sample.inspection_summary.oleocellosis_count=2;
  sample.evidence_photos=[
    {defect:"oleocellosis",image_data_url:"data:image/jpeg;base64,EXCLUDED",
      vision_reviews:[{review_status:"confirmed",qc_included:false}]},
    {defect:"oleocellosis",view:"scene",image_data_url:"data:image/jpeg;base64,GROUP",
      vision_reviews:[{review_status:"rejected"},{review_status:"confirmed",qc_included:true}]},
    {defect:"oleocellosis",image_data_url:"data:image/jpeg;base64,LEGACY"},
  ];
  context.renderResults(report);
  const images=byId("results").querySelectorAll("article")[0].querySelectorAll("img");
  assert.deepEqual(images.map(image=>image.src),[
    "data:image/jpeg;base64,GROUP","data:image/jpeg;base64,LEGACY",
  ]);
});

