"use strict";

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
  const rest=html.slice(match.index+match[0].length);
  const next=/\n  (?:async )?function /.exec(rest);
  assert.ok(next,name + " is followed by a function");
  return html.slice(match.index,match.index+match[0].length+next.index);
}

class Node {
  constructor(tag,text,className="") {
    this.tagName=tag.toUpperCase();this.textContent=text??"";this.className=className;
    this.children=[];this.value="";this.listeners={};this.disabled=false;
  }
  append(...nodes){this.children.push(...nodes);}
  addEventListener(type,callback){(this.listeners[type]??=[]).push(callback);}
  dispatch(type){for(const callback of this.listeners[type]||[])callback({target:this,stopPropagation(){}});}
  click(){if(!this.disabled)this.dispatch("click");}
}

function setup({rows=[{expected_count_per_box:"150",size_declared:"150"}],records=[{image_id:"GROUP_1",total_fruits:73},{image_id:"GROUP_2",total_fruits:73}]}={}){
  const state={busy:false},events={invalidated:0,changed:0,status:[]};
  const context=vm.createContext({state,element:(...args)=>new Node(...args),
    invalidate(){events.invalidated++;},captureChanged(){events.changed++;},
    status(message){events.status.push(message);},error(message){throw Error(message);},
  });
  vm.runInContext(["numberText","newBoxInspection","boxCaptureSummary","renderBoxCapture","updateBoxCapture"].map(source).join("\n"),context);
  const sample={serial:1,records,reception:{records:rows},boxInspection:context.newBoxInspection()};
  const host=new Node("section");context.renderBoxCapture(sample,"initial",host);
  return {context,sample,host,state,events,controls:sample.boxControls};
}

test("the box compares all distinct images with its manifest count, including a real deficit",()=>{
  const {context,sample}=setup();
  const summary=context.boxCaptureSummary(sample,sample.records,sample.boxInspection);
  assert.equal(summary.images_processed,2);
  assert.equal(summary.actual_count,146);
  assert.equal(summary.expected_count_per_box,150);
  assert.equal(summary.count_difference,-4);
  assert.ok(Math.abs(summary.count_deviation_pct-(-2.6666666667))<1e-8);
  assert.equal(sample.boxInspection.status,"capturing");
  assert.equal(sample.boxInspection.coverage_confirmed,false);
});

test("reimporting an identical image does not increase the box count or hide a deficit",()=>{
  const first={image_id:"GROUP_1",total_fruits:73};
  const {context,sample}=setup({records:[first,{...first},{image_id:"GROUP_2",total_fruits:73}]});
  const summary=context.boxCaptureSummary(sample,sample.records,sample.boxInspection);
  assert.equal(summary.images_processed,2);
  assert.equal(summary.actual_count,146);
  assert.equal(summary.count_difference,-4);
});

test("different manifest sizes require a choice before a box comparison or completion",()=>{
  const {sample,controls}=setup({rows:[{size_declared:"150",expected_count_per_box:"150"},{size_declared:"170",expected_count_per_box:"170"}]});
  assert.equal(controls.values[0].textContent,"Pendiente");
  assert.equal(controls.finish.disabled,true);
  controls.finish.click();
  assert.equal(sample.boxInspection.status,"capturing");
  controls.select.value="1";controls.select.dispatch("change");
  assert.equal(sample.boxInspection.manifest_record_index,1);
  assert.equal(controls.values[0].textContent,"170");
  assert.equal(controls.values[2].textContent,"-24");
  assert.equal(controls.finish.disabled,false);
});

test("finishing a whole box with fewer detected units is explicit and can be reopened",()=>{
  const {sample,controls,events}=setup();
  assert.match(controls.note.textContent,/Conteo parcial/);
  controls.finish.click();
  assert.equal(sample.boxInspection.status,"completed");
  assert.equal(sample.boxInspection.coverage_confirmed,true);
  assert.match(controls.note.textContent,/4 unidades menos detectadas/);
  assert.match(controls.note.textContent,/Verifica el conteo físico/);
  assert.equal(controls.finish.textContent,"Reabrir captura de esta caja");
  controls.finish.click();
  assert.equal(sample.boxInspection.status,"capturing");
  assert.equal(sample.boxInspection.coverage_confirmed,false);
  assert.match(controls.note.textContent,/Conteo parcial/);
  assert.equal(events.invalidated,2);
});

test("matching the expected count never completes the box automatically",()=>{
  const {sample,controls,context}=setup({records:[{image_id:"GROUP_1",total_fruits:75},{image_id:"GROUP_2",total_fruits:75}]});
  context.updateBoxCapture(sample);
  assert.equal(controls.values[2].textContent,"0");
  assert.equal(sample.boxInspection.status,"capturing");
  assert.equal(sample.boxInspection.coverage_confirmed,false);
  controls.finish.click();
  assert.equal(sample.boxInspection.status,"completed");
  assert.match(controls.note.textContent,/coincide/);
});

test("changing the selected manifest line invalidates previous box completion",()=>{
  const {sample,controls}=setup({rows:[{size_declared:"150",expected_count_per_box:"150"},{size_declared:"170",expected_count_per_box:"170"}]});
  controls.select.value="0";controls.select.dispatch("change");
  controls.finish.click();assert.equal(sample.boxInspection.status,"completed");
  controls.select.value="1";controls.select.dispatch("change");
  assert.equal(sample.boxInspection.status,"capturing");
  assert.equal(sample.boxInspection.coverage_confirmed,false);
  assert.equal(controls.values[0].textContent,"170");
  assert.equal(controls.values[2].textContent,"-24");
});

test("unknown expected counts stay pending rather than becoming zero",()=>{
  for(const expected of ["",null,"0"]){
    const {sample,controls}=setup({rows:[{size_declared:"150",expected_count_per_box:expected}]});
    assert.equal(controls.values[0].textContent,"Pendiente");
    assert.equal(controls.values[2].textContent,"—");
    assert.equal(controls.values[1].textContent,"146");
    controls.finish.click();
    assert.equal(sample.boxInspection.status,"completed");
    assert.match(controls.note.textContent,/no tiene un conteo esperado/);
  }
});

test("invalid declared counts prevent completion and show how to resolve the manifest",()=>{
  for(const expected of ["150.5","not-a-count","-150",true]){
    const {sample,controls}=setup({rows:[{size_declared:"150",expected_count_per_box:expected}]});
    assert.equal(controls.values[1].textContent,"146");
    assert.equal(controls.values[2].textContent,"—");
    assert.equal(controls.finish.disabled,true);
    assert.match(controls.note.textContent,/count declarado es inválido/);
    controls.finish.click();
    assert.equal(sample.boxInspection.status,"capturing");
  }
});

test("a second box cannot make the first box appear overfilled through pallet accumulation",()=>{
  const {sample,controls,context}=setup();
  const initialRecords=sample.records.slice();
  controls.finish.click();
  sample.reviewHistory={initial:{vision_records:initialRecords},additional:[{vision_records:[{image_id:"GROUP_3",total_fruits:150}]}]};
  sample.records=[...initialRecords,{image_id:"GROUP_3",total_fruits:150}];
  context.updateBoxCapture(sample);
  assert.equal(controls.values[1].textContent,"146");
  assert.equal(controls.values[2].textContent,"-4");
  assert.equal(controls.finish.disabled,true);
});

test("finishing and reopening the additional box controls whether it can be added to the pallet",()=>{
  const {context,sample}=setup();
  sample.pendingAdditional={visionRecords:sample.records,boxInspection:context.newBoxInspection(2)};
  sample.additionalAddButton=new Node("button");sample.additionalAddButton.disabled=true;
  context.renderBoxCapture(sample,"additional",new Node("section"));
  sample.additionalBoxControls.finish.click();
  assert.equal(sample.pendingAdditional.boxInspection.status,"completed");
  assert.equal(sample.additionalAddButton.disabled,false);
  sample.additionalBoxControls.finish.click();
  assert.equal(sample.pendingAdditional.boxInspection.status,"capturing");
  assert.equal(sample.additionalAddButton.disabled,true);
});

test("an unfinished additional box cannot be sent for pallet accumulation",async()=>{
  const context=vm.createContext({ensureCurrent(){}});
  vm.runInContext(source("applyAdditionalReview"),context);
  const sample={inspectorChoice:"EXPAND",pendingAdditional:{boxInspection:{status:"capturing",coverage_confirmed:false}}};
  await assert.rejects(context.applyAdditionalReview(sample),/Finaliza la inspección de la caja adicional/);
});
