"use strict";

const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const {test}=require("node:test");
const html=fs.readFileSync(path.join(__dirname,"../../src/smartfruit/web/index.html"),"utf8");
const keys=["decay","styler","mold","soft","skin_breakdown","oleocellosis","wounds","int_dryness","black_tips","skin_defect","scars","white_stain","blanching","yellow_color","stain","undersize"];

function source(name){
  const match=new RegExp("^  (?:async )?function "+name+"\\(","m").exec(html);assert.ok(match,name+" exists");
  const firstLine=html.slice(match.index).split("\n",1)[0];if(firstLine.trimEnd().endsWith("}"))return firstLine;
  const rest=html.slice(match.index+match[0].length),next=/\n  (?:async )?function /.exec(rest);assert.ok(next);
  return html.slice(match.index,match.index+match[0].length+next.index);
}

test("inspector choice updates alongside the suggestion and EXTEND exposes only that pallet's extra review",()=>{
  const first={id:{value:"S1"},controls:{pallet_id:{value:"P1"}},inspectorChoice:"",choiceControl:{value:""},inspectorStatus:{textContent:""},additionalPanel:{hidden:true}};
  const other={id:{value:"S2"},controls:{pallet_id:{value:"P2"}},inspectorChoice:"ESCALATE",additionalPanel:{hidden:true}};
  const state={samples:[first,other],report:{samples:[{sample_id:"S1",final_recommendation:"ESCALATE"}]}},confirmation={checked:true};let summaries=0,syncs=0;
  const context=vm.createContext({state,decisions:["STANDARD","EXPAND","ESCALATE"],
    renderInspectorDecisionSummary(){summaries++;},syncReviewMetadata(){syncs++;confirmation.checked=false;},status(){}});
  vm.runInContext(["canonicalDecision","decisionLabel","setInspectorChoice"].map(source).join("\n"),context);
  context.setInspectorChoice("S1","EXTEND");
  assert.equal(first.inspectorChoice,"EXPAND");assert.equal(first.choiceControl.value,"EXPAND");
  assert.equal(first.additionalPanel.hidden,false);assert.equal(other.additionalPanel.hidden,true);
  assert.match(first.inspectorStatus.textContent,/EXTEND/);assert.equal(confirmation.checked,false);
  assert.equal(state.report.samples[0].final_recommendation,"ESCALATE");
  context.setInspectorChoice("S1","STANDARD");assert.equal(first.additionalPanel.hidden,true);
  assert.equal(other.inspectorChoice,"ESCALATE");assert.equal(summaries,2);assert.equal(syncs,2);
  assert.throws(()=>context.setInspectorChoice("S1","APPROVED"),/STANDARD, EXTEND o ESCALATE/);
  assert.equal(first.inspectorChoice,"STANDARD");
});

function setupCommit(){
  const counts={...Object.fromEntries(keys.map(key=>[key,0])),sample_count:12,oleocellosis:1,scars:2};
  const sample=(id,pallet)=>({id:{value:id},controls:Object.fromEntries(Object.entries({pallet_id:pallet,label_brand:"Original",...counts}).map(([key,value])=>[key,{value:String(value)}])),records:[{image_id:"IMAGE-"+id,total_fruits:12,oleocellosis_count:1,original:{keep:true}}],imageBindings:[],inspectorChoice:"EXPAND",pendingAdditional:{visionRecords:[{image_id:"EXTRA"}]}});
  const target=sample("S1","P1"),other=sample("S2","P2");other.inspectorChoice="ESCALATE";
  const state={samples:[target,other],revision:3,evaluatedRevision:3,report:{lot_id:"LOT",samples:[]},finalized:false};
  const calls={vision:0,render:0,summary:0,sync:0,capture:0,steps:[]};
  const collectPayload=()=>({qc_header:{lot_id:"LOT"},samples:state.samples.map(item=>({sample_id:item.id.value,pallet_id:item.controls.pallet_id.value,vision_records:structuredClone(item.records),review_choice:item.inspectorChoice,review_history:item.reviewHistory}))});
  const context=vm.createContext({state,defectKeys:new Set(keys),headerControls:{lot_id:{value:"LOT"}},copy:structuredClone,collectPayload,
    updateVision(item,options){assert.equal(item,target);assert.equal(options.preserveQC,true);calls.vision++;},
    renderResults(){calls.render++;},renderLotSummary(){calls.summary++;},syncReviewMetadata(){calls.sync++;},captureChanged(){calls.capture++;},setStep(step){calls.steps.push(step);},status(){}});
  vm.runInContext(source("commitAdditionalReview"),context);
  const total={pallet_id:"P1",label_brand:"Original",...counts,sample_count:24,oleocellosis:2,scars:5};
  const history={initial:{vision_records:structuredClone(target.records),qc_fields:{...counts},system_recommendation:"EXPAND"},additional:[{review_number:2,trigger_decision:"EXPAND",vision_records:[{image_id:"EXTRA",total_fruits:12,oleocellosis_count:1}],manual_defects:{scars:3}}]};
  const response={capture:{samples:[{sample_id:"S1",pallet_id:"P1",vision_records:[...structuredClone(target.records),{image_id:"EXTRA",total_fruits:12,oleocellosis_count:1}],image_bindings:[{image_id:"EXTRA",sample_id:"S1",pallet_id:"P1",lot_id:"LOT"}],qc_fields:total,review_history:history}]},
    report:{lot_id:"LOT",samples:[{sample_id:"S1",pallet_id:"P1",qc_fields:structuredClone(total),inspection_summary:{total_fruits:24,oleocellosis_count:2,oleocellosis_pct:100*2/24},review_history:structuredClone(history),final_recommendation:"EXPAND"}]}};
  return {context,state,target,other,calls,response};
}

test("committing an additional box replaces only its pallet's accumulated capture and retains original evidence",()=>{
  const {context,state,target,other,calls,response}=setupCommit(),beforeOther=structuredClone(other),beforeResponse=structuredClone(response);
  context.commitAdditionalReview(target,response);
  assert.equal(target.controls.sample_count.value,"24");assert.equal(target.controls.oleocellosis.value,"2");assert.equal(target.controls.scars.value,"5");
  assert.deepEqual(target.records.map(record=>record.image_id),["IMAGE-S1","EXTRA"]);
  assert.deepEqual(target.reviewHistory,response.capture.samples[0].review_history);assert.equal(target.reviewHistory.initial.qc_fields.sample_count,12);
  assert.equal(target.inspectorChoice,"");assert.equal(target.pendingAdditional,null);assert.equal(Object.hasOwn(target,"coverage"),false);
  assert.equal(target.visionSummary.oleocellosis_pct,100*2/24);assert.deepEqual(other,beforeOther);
  assert.equal(state.revision,4);assert.equal(state.evaluatedRevision,4);assert.deepEqual(state.payload.samples[0].review_history,target.reviewHistory);
  assert.equal(state.payload.samples[1].review_choice,"ESCALATE");assert.deepEqual(calls,{vision:1,render:1,summary:1,sync:1,capture:1,steps:[4]});
  target.reviewHistory.additional[0].manual_defects.scars=99;assert.deepEqual(response,beforeResponse);
});

test("malformed extra-review responses leave the current capture and other pallets untouched",()=>{
  for(const mutate of [
    response=>{response.capture.samples[0].pallet_id="OTHER";},
    response=>{response.capture.samples[0].review_history.additional=[];},
    response=>{response.capture.samples[0].qc_fields.scars=-1;},
    response=>{response.report.samples[0].qc_fields.scars=99;},
    response=>{response.capture.samples[0].vision_records=null;}
  ]){
    const {context,state,target,calls,response}=setupCommit(),before=structuredClone(state);mutate(response);
    assert.throws(()=>context.commitAdditionalReview(target,response),/revisión adicional/);
    assert.deepEqual(state,before);assert.equal(calls.vision,0);assert.equal(calls.render,0);assert.equal(calls.sync,0);
  }
});

test("an additional box can be applied without another coverage confirmation",async()=>{
  const record={image_id:"EXTRA",total_fruits:12,oleocellosis_count:1};
  const sample={id:{value:"S1"},inspectorChoice:"EXPAND",
    pendingAdditional:{visionRecords:[record],summary:{total_fruits:12}},
    additionalControls:Object.fromEntries(keys.filter(key=>key!=="oleocellosis").map(key=>[key,{value:"0",focus(){}}])),
    additionalObservations:{value:" Second box "}};
  const response={capture:{},report:{},review:{review_number:2}},calls={requests:[],commits:0,unlocks:0};
  const context=vm.createContext({state:{revision:3},defectKeys:new Set(keys),fallbackColumns:[],
    ensureCurrent(){},collectPayload(){return {qc_header:{lot_id:"LOT"},samples:[]};},
    lockCaptureInputs(){return ()=>{calls.unlocks++;};},
    async request(url,payload){calls.requests.push({url,payload});return {async json(){return response;}};},
    commitAdditionalReview(target,result){assert.equal(target,sample);assert.equal(result,response);calls.commits++;}});
  vm.runInContext(source("applyAdditionalReview"),context);
  await context.applyAdditionalReview(sample);
  assert.equal(Object.hasOwn(sample,"additionalCoverage"),false);
  assert.equal(calls.requests.length,1);
  assert.equal(calls.requests[0].url,"/api/inspection/additional-review");
  assert.equal(calls.requests[0].payload.inspector_decision,"EXPAND");
  assert.equal(calls.requests[0].payload.additional_review.observations,"Second box");
  assert.deepEqual(calls.requests[0].payload.additional_review.vision_records,[record]);
  assert.equal(Object.keys(calls.requests[0].payload.additional_review.manual_defects).length,15);
  assert.equal(calls.commits,1);assert.equal(calls.unlocks,1);
});

test("the additional-box form contains only its observations and manual counts, without a coverage checkbox",()=>{
  const nodes=[];
  const element=(tag,text,className)=>{
    const node={tagName:tag.toUpperCase(),textContent:text??"",className:className??"",children:[],value:"",attributes:{},style:{},
      append(...children){this.children.push(...children);},replaceChildren(...children){this.children=[...children];},
      setAttribute(key,value){this.attributes[key]=String(value);},getAttribute(key){return this.attributes[key]??null;},addEventListener(){}};
    nodes.push(node);return node;
  };
  const sample={serial:1,additionalBody:element("div"),
    pendingAdditional:{summary:{images_processed:1,total_fruits:12,oleocellosis_count:1,oleocellosis_pct:100/12}}};
  const context=vm.createContext({element,sourceNodes:new WeakMap(),defectKeys:new Set(keys),numberText:String,busy(){},
    retainPendingAdditional(){},samePendingContext(){return true;},pendingAdditionalContext(){return {};}});
  const columns=html.slice(html.indexOf("  const fallbackColumns ="),html.indexOf("  const fallbackHeaders ="));
  vm.runInContext(columns+"\n"+["field","renderAdditionalForm"].map(source).join("\n"),context);
  context.renderAdditionalForm(sample);
  assert.equal(nodes.filter(node=>node.tagName==="INPUT"&&node.type==="checkbox").length,0);
  assert.equal(Object.hasOwn(sample,"additionalCoverage"),false);
  assert.equal(Object.keys(sample.additionalControls).length,15);
  assert.ok(nodes.some(node=>node.tagName==="BUTTON"&&node.textContent==="Agregar caja y actualizar resultados"));
});
