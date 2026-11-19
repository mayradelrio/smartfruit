"use strict";
const assert=require("node:assert/strict"),{test}=require("node:test");
const {summary,review,adjudicate,selected,setIncluded,selectionSummary,applySelection,render}=require("../../src/smartfruit/web/vision_review.js");
function record(){return {image_id:"IMG",total_fruits:3,oleocellosis_count:2,oleocellosis_pct:200/3,fruit_predictions:[{crop_id:"A",predicted_class:"con_oleocelosis",oleocellosis_probability:0.99,confidence:0.99},{crop_id:"B",predicted_class:"con_oleocelosis",oleocellosis_probability:0.8,confidence:0.8},{crop_id:"C",predicted_class:"sin_oleocelosis",oleocellosis_probability:0.2,confidence:0.8}]};}
test("raw positives stay pending until QC confirms and rejection preserves raw model data",()=>{
 const data=record(),original=structuredClone(data);assert.deepEqual(summary([data]),{total:3,suspected:2,confirmed:0,pending:2,rejected:0});
 review(data.fruit_predictions[0],"confirmed","QC");review(data.fruit_predictions[1],"rejected","QC","scar");
 assert.deepEqual(summary([data]),{total:3,suspected:2,confirmed:1,pending:0,rejected:1});
 assert.equal(data.oleocellosis_count,2);assert.equal(data.fruit_predictions[1].predicted_class,original.fruit_predictions[1].predicted_class);assert.equal(data.fruit_predictions[1].oleocellosis_probability,0.8);
 assert.equal(data.fruit_predictions[1].override_label,"scar");assert.ok(data.fruit_predictions[1].reviewed_at.endsWith("Z"));
});
test("QC review requires reviewer and meaningful other correction before mutating predictions",()=>{
 const prediction=record().fruit_predictions[0],original=structuredClone(prediction);
 assert.throws(()=>review(prediction,"confirmed",""),/nombre/);assert.throws(()=>review(prediction,"rejected","QC","other"),/corrección/);assert.deepEqual(prediction,original);
});
test("reviewing a repeated identical JSON synchronizes audit fields and counts it once",()=>{
 const data=record(),duplicate=structuredClone(data),raw=structuredClone(data);const records=[data,duplicate];
 adjudicate(records,"IMG","A","confirmed","QC",null,"",new Date("2026-11-18T10:00:00Z"));
 assert.deepEqual(data,duplicate);assert.equal(summary(records).confirmed,1);assert.equal(summary(records).pending,1);assert.equal(summary(records).total,3);
 assert.equal(data.oleocellosis_count,raw.oleocellosis_count);assert.equal(data.fruit_predictions[0].predicted_class,raw.fruit_predictions[0].predicted_class);
});

test("new positive photos are all checked by default without changing original model predictions",()=>{
 const data=record(),before=structuredClone(data);
 assert.equal(selected(data.fruit_predictions[0]),true);
 assert.equal(selected(data.fruit_predictions[1]),true);
 assert.deepEqual(selectionSummary([data]),{total:3,suspected:2,included:2,excluded:0,pending:2});
 assert.deepEqual(data,before);
 assert.equal(summary([data]).confirmed,0);
});

test("unchecking and rechecking a detection changes its inclusion without changing other defects",()=>{
 const data=record(),before=structuredClone(data);
 setIncluded([data],"IMG","B",false);
 assert.equal(selected(data.fruit_predictions[1]),false);
 assert.equal(selectionSummary([data]).included,1);
 assert.equal(selectionSummary([data]).excluded,1);
 assert.equal(data.fruit_predictions[1].review_status,"pending");
 assert.equal(data.oleocellosis_count,2);
 assert.equal(data.fruit_predictions[1].predicted_class,before.fruit_predictions[1].predicted_class);
 assert.equal(data.fruit_predictions[1].oleocellosis_probability,before.fruit_predictions[1].oleocellosis_probability);
 assert.deepEqual(data.fruit_predictions[2],before.fruit_predictions[2]);
 setIncluded([data],"IMG","B",true);
 assert.equal(selectionSummary([data]).included,2);
});

test("one batch application records the checked positives and unchecked exclusions with QC audit",()=>{
 const data=record(),now=new Date("2026-11-18T15:00:00Z");
 setIncluded([data],"IMG","B",false);
 applySelection([data],"Inspector QC",now);
 const [confirmed,rejected,negative]=data.fruit_predictions;
 assert.equal(confirmed.review_status,"confirmed");assert.equal(rejected.review_status,"rejected");
 assert.equal(confirmed.reviewed_by,"Inspector QC");assert.equal(rejected.reviewed_by,"Inspector QC");
 assert.equal(confirmed.reviewed_at,now.toISOString());assert.equal(rejected.reviewed_at,now.toISOString());
 assert.equal(rejected.override_label,"other");assert.match(rejected.override_reason,/check de oleocelosis/);
 assert.equal(confirmed.override_label,null);assert.equal(negative.review_status,undefined);
 assert.equal(data.oleocellosis_count,2);assert.equal(rejected.predicted_class,"con_oleocelosis");
 assert.deepEqual(summary([data]),{total:3,suspected:2,confirmed:1,pending:0,rejected:1});
});

test("all positives can be unchecked without removing photos or relabeling healthy predictions",()=>{
 const data=record(),negative=structuredClone(data.fruit_predictions[2]);
 setIncluded([data],"IMG","A",false);setIncluded([data],"IMG","B",false);
 const recovered=JSON.parse(JSON.stringify(data));
 assert.equal(selected(recovered.fruit_predictions[0]),false);assert.equal(selected(recovered.fruit_predictions[1]),false);
 applySelection([recovered],"QC");
 assert.equal(summary([recovered]).confirmed,0);assert.equal(summary([recovered]).rejected,2);
 assert.equal(recovered.total_fruits,3);assert.equal(recovered.oleocellosis_count,2);
 assert.deepEqual(recovered.fruit_predictions[2],negative);
});

test("a missing reviewer prevents an entire batch from being applied",()=>{
 const data=record();setIncluded([data],"IMG","B",false);const before=structuredClone(data);
 assert.throws(()=>applySelection([data],"   "),/nombre/);
 assert.deepEqual(data,before);
});

test("saved QC exclusions stay unchecked and keep their existing reason until changed",()=>{
 const data=record();review(data.fruit_predictions[1],"rejected","QC original","scar","Cicatriz verificada",new Date("2026-11-17T15:00:00Z"));
 const previous=structuredClone(data.fruit_predictions[1]);
 assert.equal(selected(data.fruit_predictions[1]),false);
 applySelection([data],"QC nuevo",new Date("2026-11-18T15:00:00Z"));
 assert.deepEqual(data.fruit_predictions[1],previous);
 setIncluded([data],"IMG","B",true);
 assert.equal(data.fruit_predictions[1].review_status,"pending");
 assert.equal(data.fruit_predictions[1].reviewed_by,null);
 assert.equal(data.fruit_predictions[1].reviewed_at,null);
 applySelection([data],"QC nuevo");
 assert.equal(data.fruit_predictions[1].review_status,"confirmed");
 assert.equal(data.fruit_predictions[1].override_label,null);
 assert.equal(summary([data]).confirmed,2);
});

test("an inclusion change removes stale confirmation and stays synchronized across duplicate JSONs",()=>{
 const data=record();applySelection([data],"QC");const duplicate=structuredClone(data),records=[data,duplicate];
 setIncluded(records,"IMG","A",false);
 assert.deepEqual(data,duplicate);
 assert.equal(summary(records).confirmed,1);assert.equal(summary(records).pending,1);
 assert.equal(selectionSummary(records).included,1);assert.equal(selectionSummary(records).total,3);
 applySelection(records,"QC correction");
 assert.deepEqual(data,duplicate);assert.equal(summary(records).rejected,1);
});

function renderFixture(records,options={}){
 class Node{
  constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.attributes={};this.style={};this.dataset={};this.className="";this.classList={add:name=>{this.className+=" "+name;}};}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=[...nodes];}
  setAttribute(name,value){this.attributes[name]=value;}
  addEventListener(type,handler){this.listeners[type]=handler;}
 }
 const previous=global.document;global.document={createElement:tag=>new Node(tag)};
 const root=new Node("section"),controller=render(root,records,options);
 const nodes=()=>{const visit=node=>[node,...node.children.flatMap(visit)];return visit(root);};
 return {root,controller,nodes,cleanup(){global.document=previous;}};
}

test("the review renders one checked checkbox per positive detection and a single batch action",()=>{
 const data=record(),fixture=renderFixture([data,structuredClone(data)]);
 try{
  const checks=fixture.nodes().filter(node=>node.tagName==="INPUT"&&node.type==="checkbox");
  assert.equal(checks.length,2);assert.ok(checks.every(check=>check.checked));
  assert.equal(fixture.nodes().filter(node=>node.tagName==="SELECT").length,0);
  const buttons=fixture.nodes().filter(node=>node.tagName==="BUTTON");
  assert.equal(buttons.length,1);assert.equal(buttons[0].textContent,"Aplicar selección");
  checks[1].checked=false;checks[1].listeners.change({target:checks[1]});
  assert.equal(selectionSummary([data]).included,1);
  assert.equal(fixture.controller.hasPendingChanges(),true);
  fixture.controller.applySelection("QC");
  assert.equal(summary([data]).confirmed,1);assert.equal(summary([data]).rejected,1);
 }finally{fixture.cleanup();}
});

test("disabled saved reviews keep exclusions unchecked and expose no editable checkbox",()=>{
 const data=record();review(data.fruit_predictions[1],"rejected","QC","scar");
 const fixture=renderFixture([data],{disabled:true});
 try{
  const checks=fixture.nodes().filter(node=>node.tagName==="INPUT"&&node.type==="checkbox");
  assert.deepEqual(checks.map(check=>check.checked),[true,false]);
  assert.ok(checks.every(check=>check.disabled));
 }finally{fixture.cleanup();}
});
