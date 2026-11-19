"use strict";

const assert=require("node:assert/strict");
const {test}=require("node:test");
const fs=require("node:fs");
const path=require("node:path");
const vm=require("node:vm");
const capture=require("../../src/smartfruit/web/vision_capture.js");
const context={lot_id:"LOT-ANY",pallet_id:"PALLET-ANY",sample_id:"S1",review_kind:"initial"};
const record={image_id:"PHOTO-1",total_fruits:1,oleocellosis_count:1};
const ready={job_id:"JOB1",status:"ready",context,records:[record]};

test("individual fruit photos are grouped by source take and retain their used identity",()=>{
  const groups=capture.groupPhotos([
    {photo_id:"1",image_id:"A1",name:"IMG_1_L1.jpg",source_group:"IMG_1",input_kind:"fruit_crop"},
    {photo_id:"2",image_id:"A2",name:"IMG_1_L2.jpg",source_group:"IMG_1",input_kind:"fruit_crop"},
    {photo_id:"3",image_id:"B1",name:"whole.jpg",source_group:"IMG_2",input_kind:"scene"},
  ],new Set(["A1"]));
  assert.equal(groups.length,2);assert.equal(groups[0].photos.length,2);assert.equal(groups[0].crops,true);
  assert.equal(groups[0].photos[0].used,true);assert.equal(groups[0].photos[1].used,false);assert.equal(groups[1].crops,false);
});

test("legacy whole-image JSON marks its individual-fruit crops as already used",()=>{
  const photos=[{photo_id:"1",image_id:"HASH-1",name:"IMG_6426_L01.jpg",source_group:"IMG_6426",input_kind:"fruit_crop"},
    {photo_id:"2",image_id:"HASH-2",name:"IMG_6427_L01.jpg",source_group:"IMG_6427",input_kind:"fruit_crop"}];
  const groups=capture.groupPhotos(photos,new Set(["IMG_6426"]));
  assert.equal(groups[0].photos[0].used,true);assert.equal(groups[1].photos[0].used,false);
  const partial=capture.groupPhotos(photos,new Set(["HASH-1"]));
  assert.equal(partial[0].photos[0].used,true);assert.equal(partial[1].photos[0].used,false);
});

test("photo jobs pass the selected manifest identity and wait for real ready results",async()=>{
  const calls=[],updates=[],waits=[];
  const responses=[{job_id:"JOB1",status:"queued",context},{job_id:"JOB1",status:"running",context,progress:{completed:0,total:1}},ready];
  const result=await capture.processPhotos(async(url,payload)=>{
    calls.push({url,payload});return {async json(){return responses.shift();}};
  },context,["LOCAL-1"],job=>updates.push(job.status),async delay=>{waits.push(delay);});
  assert.equal(result,ready);assert.deepEqual(updates,["queued","running","ready"]);
  assert.deepEqual(calls[0],{url:"/api/vision/jobs",payload:{...context,photo_ids:["LOCAL-1"]}});
  assert.deepEqual(calls.slice(1).map(call=>call.url),["/api/vision/jobs/JOB1","/api/vision/jobs/JOB1"]);
  assert.equal(waits.length,2);
});

test("a processing error cannot be interpreted as a ready inspection result",async()=>{
  await assert.rejects(capture.processPhotos(async()=>({async json(){return {job_id:"JOB1",status:"failed",context,error:"Modelo no disponible"};}}),context,["1"],()=>{}),/Modelo no disponible/);
  await assert.rejects(capture.processPhotos(async()=>{throw Error("must not request without photos");},context,[],()=>{}),/Selecciona las fotos/);
});

test("results cannot cross lot, pallet, sample or initial/additional review boundaries",()=>{
  for(const key of ["lot_id","pallet_id","sample_id","review_kind"]){
    assert.throws(()=>capture.checkReady(ready,{...context,[key]:"OTHER"}),/otro lote, paleta o revisión/);
  }
  assert.equal(capture.checkReady(ready,{...context}),ready.records);
  assert.throws(()=>capture.checkReady({...ready,records:[{...record,total_fruits:0,oleocellosis_count:0}]},context),/No se identificaron frutos/);
  assert.throws(()=>capture.checkReady({...ready,records:[{...record,total_fruits:1,oleocellosis_count:2}]},context),/cantidades inválidas/);
});

test("polling rejects a ready result whose manifest identity changed",async()=>{
  const job={...ready,context:{...context,pallet_id:"WRONG"}};
  await assert.rejects(capture.processPhotos(async()=>({async json(){return job;}}),context,["1"],()=>{}),/asociación distinta/);
});

test("initial and EXTEND confirmations use their existing import and additional-review validators",async()=>{
  const html=fs.readFileSync(path.join(__dirname,"../../src/smartfruit/web/index.html"),"utf8");
  const start=html.indexOf("  function mountVisionCapture("),end=html.indexOf("\n  function addSample(",start);
  const sample={id:{value:"S1"},controls:{pallet_id:{value:"P1"}},records:[],inspectorChoice:"EXTEND"};
  const configs=[],calls=[];
  const sandbox=vm.createContext({state:{samples:[sample]},headerControls:{lot_id:{value:"LOT"}},request(){},
    element(){return {append(){}};},window:{SmartFruitVisionCapture:{create(options){configs.push(options);return {destroy(){},refresh(){}};}}},
    busy:fn=>fn(),lockCaptureInputs:()=>()=>{},error(){},status(){},
    importVisionRecords(target,records){calls.push(["initial",target,records]);},
    stageAdditionalReview(target,records){calls.push(["additional",target,records]);}});
  vm.runInContext(html.slice(start,end),sandbox);
  sandbox.mountVisionCapture(sample,"initial");sandbox.mountVisionCapture(sample,"additional");
  await configs[0].onConfirm([record]);await configs[1].onConfirm([record]);
  assert.deepEqual(calls,[["initial",sample,[record]],["additional",sample,[record]]]);
  assert.equal(configs[0].getContext().pallet_id,"P1");assert.equal(configs[1].getContext().review_kind,"additional");
  sample.controls.pallet_id.value="P2";assert.equal(configs[0].getContext().pallet_id,"P2");
});

test("the photo interface requires a separate confirmation after producing real job results",async()=>{
  class Node {
    constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.className="";this.classList={add:name=>{this.className+=" "+name;}};}
    append(...nodes){this.children.push(...nodes);}
    replaceChildren(...nodes){this.children=[...nodes];}
    setAttribute(){}
    addEventListener(type,handler){this.listeners[type]=handler;}
  }
  global.document={createElement:tag=>new Node(tag)};
  try{
    const root=new Node("section"),calls=[],confirmed=[],memory={};
    const photos=[{photo_id:"1",image_id:"PHOTO-1",name:"IMG_1_L1.jpg",source_group:"IMG_1",input_kind:"fruit_crop",url:"/api/vision/photos/1"}];
    const widget=capture.create({root,memory,getContext:()=>({...context}),getUsedImageIds:()=>new Set(),
      request:async(url,payload)=>{calls.push({url,payload});return {async json(){return url==="/api/vision/photos"?{photos,runtime:{available:true}}:ready;}};},
      onConfirm:async records=>confirmed.push(records)});
    widget.refresh();await new Promise(resolve=>setImmediate(resolve));
    const descendants=node=>[node,...node.children.flatMap(descendants)];
    let nodes=descendants(root);const groupCheck=nodes.find(node=>node.className==="vision-group-label").children[0];
    groupCheck.checked=true;groupCheck.listeners.change();
    nodes=descendants(root);const process=nodes.find(node=>node.tagName==="BUTTON"&&node.textContent==="Procesar fotos de esta caja");
    assert.equal(process.disabled,false);await process.listeners.click();
    assert.equal(confirmed.length,0);assert.equal(memory.job.status,"ready");
    assert.deepEqual(calls.find(call=>call.url==="/api/vision/jobs").payload.photo_ids,["1"]);
    nodes=descendants(root);const confirm=nodes.find(node=>node.tagName==="BUTTON"&&node.textContent==="Incorporar fotos a la caja");
    assert.equal(confirm.disabled,false);await confirm.listeners.click();
    assert.deepEqual(confirmed,[[record]]);assert.equal(memory.job,null);assert.equal(memory.selected.size,0);
    widget.destroy();
  }finally{delete global.document;}
});

function prediction(name,positive=true,confidence=0.92){return {crop_id:name,predicted_class:positive?"con_oleocelosis":"sin_oleocelosis",confidence,oleocellosis_probability:positive?confidence:1-confidence};}
function classified(id,name,positive=true){return {image_id:id,total_fruits:1,oleocellosis_count:positive?1:0,fruit_predictions:[prediction(name,positive)],inference:{source_filename:name,input_kind:"fruit_crop"}};}
function localPhoto(id,name,group="IMG_1"){return {photo_id:id,image_id:id,name,source_group:group,input_kind:"fruit_crop",url:"/api/vision/photos/"+id+"/image"};}

test("positive gallery contains only affected predictions with original names and immutable job images",()=>{
  const photos=[localPhoto("A","IMG_1_L01.jpg"),localPhoto("B","IMG_1_L02.jpg")];
  const job={job_id:"job/encoded",photos,records:[classified("A",photos[0].name),classified("B",photos[1].name,false)]};
  const positive=capture.positivePhotos(job);
  assert.equal(positive.length,1);assert.equal(positive[0].name,"IMG_1_L01.jpg");
  assert.equal(positive[0].confidence,0.92);assert.equal(positive[0].input_kind,"fruit_crop");
  assert.equal(positive[0].url,"/api/vision/jobs/job%2Fencoded/photos/A/image");
  assert.deepEqual(capture.positivePhotos({...job,records:[classified("A",photos[0].name,false)]}),[]);
});

test("historical JSON resolves positive crop names without showing healthy fruits",()=>{
  const photos=[localPhoto("A","IMG_6426_L01.jpg"),localPhoto("B","IMG_6426_L02.jpg")];
  const historical={image_id:"IMG_6426",total_fruits:2,oleocellosis_count:1,fruit_predictions:[prediction("IMG_6426_L01.jpg"),prediction("IMG_6426_L02.jpg",false)]};
  const gallery=capture.positivePhotos({records:[historical]},photos);
  assert.equal(gallery.length,1);assert.equal(gallery[0].name,photos[0].name);assert.equal(gallery[0].url,photos[0].url);
});

test("whole-photo results label their affected fruits while showing the source photograph",()=>{
  const photo={...localPhoto("SCENE","whole.jpg"),input_kind:"scene"};
  const scene={image_id:"SCENE",total_fruits:3,oleocellosis_count:2,fruit_predictions:[prediction("crop1"),prediction("crop2",true,0.8),prediction("crop3",false)],inference:{source_filename:"whole.jpg",input_kind:"scene"}};
  const gallery=capture.positivePhotos({job_id:"J",photos:[photo],records:[scene,scene]});
  assert.equal(gallery.length,1);assert.equal(gallery[0].affected,2);assert.equal(gallery[0].total,3);assert.equal(gallery[0].input_kind,"scene");
});

function componentFixture(options={}){
  class Node {
    constructor(tag){this.tagName=tag.toUpperCase();this.children=[];this.listeners={};this.attributes={};this.style={};this.className="";this.classList={add:name=>{this.className+=" "+name;}};}
    append(...nodes){this.children.push(...nodes);}
    replaceChildren(...nodes){this.children=[...nodes];}
    setAttribute(name,value){this.attributes[name]=value;}
    addEventListener(type,handler){this.listeners[type]=handler;}
    showModal(){this.open=true;}
    close(){this.open=false;}
    focus(){this.focused=true;}
  }
  const previousDocument=global.document,previousDefaults=global.SmartFruitVisionDefaults;
  global.document={createElement:tag=>new Node(tag)};
  global.SmartFruitVisionDefaults=require("../../src/smartfruit/web/vision_defaults.js");
  const modulePath=require.resolve("../../src/smartfruit/web/vision_capture.js");delete require.cache[modulePath];
  const api=require(modulePath),root=new Node("section"),memory=options.memory||{},confirmed=[];
  const photos=options.photos||[localPhoto("A","IMG_1_L01.jpg"),localPhoto("B","IMG_1_L02.jpg")];
  const readyJob=options.job||{job_id:"J",status:"ready",context,photos,records:photos.map((photo,index)=>classified(photo.image_id,photo.name,index===0))};
  const widget=api.create({root,memory,getContext:()=>({...context}),getUsedImageIds:()=>new Set(),
    request:async url=>({async json(){return url==="/api/vision/photos"?{photos,runtime:{available:true}}:readyJob;}}),
    onConfirm:async records=>confirmed.push(records),...options});
  const nodes=()=>{const visit=node=>[node,...node.children.flatMap(visit)];return visit(root);};
  return {root,memory,widget,confirmed,nodes,photos,readyJob,async load(){widget.refresh();await new Promise(resolve=>setImmediate(resolve));},cleanup(){widget.destroy();global.document=previousDocument;global.SmartFruitVisionDefaults=previousDefaults;}};
}

function selectGroup(fixture,index=0){
  const labels=fixture.nodes().filter(node=>node.className==="vision-group-label");
  const label=typeof index==="string"?labels.find(node=>node.children[1]?.children[0]?.textContent==="Grupo / toma "+index):labels[index];
  assert.ok(label,"group available: "+index);
  const checkbox=label.children[0];
  checkbox.checked=true;checkbox.listeners.change();
}

test("a submit shows queued feedback immediately and a double click starts only one request",async()=>{
  let release,submissions=0;
  const response=new Promise(resolve=>{release=resolve;});
  const photos=[localPhoto("A","group.jpg")];
  const fixture=componentFixture({photos,request:async url=>{
    if(url==="/api/vision/photos")return {json:async()=>({photos,runtime:{available:true}})};
    submissions++;await response;return {json:async()=>({job_id:"J",status:"ready",context,photos,records:[classified("A","group.jpg")]})};
  }});
  try{
    await fixture.load();selectGroup(fixture);
    const button=fixture.nodes().find(node=>node.textContent==="Procesar fotos de esta caja");
    const processing=button.listeners.click();await button.listeners.click();
    assert.equal(submissions,1);assert.equal(button.disabled,true);
    assert.equal(fixture.nodes().some(node=>String(node.textContent).includes("En cola · 0 / 1 fotos")),true);
    release();await processing;assert.equal(fixture.memory.job.status,"ready");
  }finally{release();fixture.cleanup();}
});

test("a timeout is visible and an explicit retry can finish the same photo selection",async()=>{
  const photos=[localPhoto("A","group.jpg")];let submissions=0;
  const fixture=componentFixture({photos,request:async url=>({json:async()=>{
    if(url==="/api/vision/photos")return {photos,runtime:{available:true}};
    submissions++;return submissions===1?{job_id:"J",status:"failed",phase:"TIMEOUT",error_type:"timeout",error:"El worker no responde",context}:{job_id:"RETRY",status:"ready",context,photos,records:[classified("A","group.jpg")]};
  }})});
  try{
    await fixture.load();selectGroup(fixture);
    await fixture.nodes().find(node=>node.textContent==="Procesar fotos de esta caja").listeners.click();
    assert.equal(fixture.nodes().some(node=>node.attributes?.["data-job-state"]==="TIMEOUT"),true);
    assert.equal(fixture.nodes().some(node=>node.textContent==="Tiempo de espera agotado"),true);
    const retry=fixture.nodes().find(node=>node.textContent==="Reintentar procesamiento");assert.equal(retry.disabled,false);
    await retry.listeners.click();assert.equal(submissions,2);assert.equal(fixture.memory.job.status,"ready");
  }finally{fixture.cleanup();}
});

test("the photo widget requires human adjudication before incorporating raw positives",async()=>{
  const previous=global.SmartFruitVisionReview;global.SmartFruitVisionReview=require("../../src/smartfruit/web/vision_review.js");
  const fixture=componentFixture();
  try{
    await fixture.load();selectGroup(fixture);
    await fixture.nodes().find(node=>node.textContent==="Procesar fotos de esta caja").listeners.click();
    const incorporate=fixture.nodes().find(node=>node.textContent==="Incorporar fotos a la caja");assert.equal(incorporate.disabled,true);
    fixture.nodes().find(node=>node.placeholder==="Nombre del inspector").value="QC Test";
    fixture.nodes().find(node=>node.textContent==="Confirmar oleocelosis").listeners.click();
    assert.equal(incorporate.disabled,false);await incorporate.listeners.click();
    assert.equal(fixture.confirmed.length,1);
    assert.equal(fixture.confirmed[0][0].fruit_predictions[0].review_status,"confirmed");
    assert.equal(fixture.confirmed[0][0].oleocellosis_count,1);
  }finally{fixture.cleanup();global.SmartFruitVisionReview=previous;}
});

test("affected photos can be enlarged and remain visible after explicit confirmation",async()=>{
  const fixture=componentFixture();
  try{
    await fixture.load();
    assert.equal(fixture.memory.selected.size,0);
    selectGroup(fixture);
    assert.equal(fixture.memory.selected.size,2);
    const process=fixture.nodes().find(node=>node.textContent==="Procesar fotos de esta caja");await process.listeners.click();
    let cards=fixture.nodes().filter(node=>node.className==="vision-positive-card");assert.equal(cards.length,1);
    const enlarge=fixture.nodes().find(node=>node.className==="vision-positive-open");enlarge.listeners.click();
    const dialog=fixture.nodes().find(node=>node.className==="vision-image-dialog"),large=fixture.nodes().find(node=>node.className==="vision-image-large");
    assert.equal(dialog.open,true);assert.equal(dialog.hidden,false);assert.equal(large.src,"/api/vision/jobs/J/photos/A/image");
    fixture.nodes().find(node=>node.className==="quiet vision-image-close").listeners.click();assert.equal(dialog.hidden,true);assert.equal(enlarge.focused,true);
    await fixture.nodes().find(node=>node.textContent==="Incorporar fotos a la caja").listeners.click();
    assert.equal(fixture.confirmed.length,1);assert.equal(fixture.memory.job,null);assert.equal(fixture.memory.confirmedJob.status,"ready");
    assert.equal(fixture.nodes().filter(node=>node.className==="vision-positive-card").length,1);
    assert.equal(fixture.nodes().some(node=>node.textContent==="Incorporar fotos a la caja"),false);
    assert.equal(fixture.memory.selected.size,0);fixture.widget.refresh();assert.equal(fixture.memory.selected.size,0);
  }finally{fixture.cleanup();}
});

test("a healthy result explicitly reports no affected fruit images",async()=>{
  const photo=localPhoto("A","IMG_1_L01.jpg");
  const fixture=componentFixture({photos:[photo],memory:{job:{job_id:"J",status:"ready",context,photos:[photo],records:[classified("A",photo.name,false)]}}});
  try{
    assert.equal(fixture.nodes().filter(node=>node.className==="vision-positive-card").length,0);
    assert.equal(fixture.nodes().some(node=>node.textContent==="No se clasificaron frutos con oleocelosis en esta revisión."),true);
  }finally{fixture.cleanup();}
});

test("clearing an explicit selection stays empty after refresh and catalog reload",async()=>{
  const fixture=componentFixture();
  try{
    await fixture.load();assert.equal(fixture.memory.selected.size,0);
    selectGroup(fixture);assert.equal(fixture.memory.selected.size,2);
    fixture.nodes().find(node=>node.textContent==="Limpiar selección").listeners.click();
    fixture.widget.refresh();assert.equal(fixture.memory.selected.size,0);
    await fixture.nodes().find(node=>node.textContent==="Actualizar fotos").listeners.click();assert.equal(fixture.memory.selected.size,0);
  }finally{fixture.cleanup();}
});

test("catalogue loading never preselects a take or replaces manual or restored results",async()=>{
  const photos=[localPhoto("A","IMG_1_L01.jpg"),localPhoto("B","IMG_2_L01.jpg","IMG_2")];
  const reserved=componentFixture({photos,getReservedPhotoIds:()=>new Set(["A"])});
  try{await reserved.load();assert.deepEqual([...reserved.memory.selected],[]);assert.deepEqual(reserved.nodes().filter(node=>node.className==="vision-individual-photo").map(node=>node.children[2].textContent),[photos[1].name]);}finally{reserved.cleanup();}
  const manual=componentFixture({photos,memory:{selected:new Set(["B"])}});
  try{await manual.load();assert.deepEqual([...manual.memory.selected],["B"]);}finally{manual.cleanup();}
  const restored=componentFixture({photos,hasExistingResults:()=>true,getConfirmedRecords:()=>[classified("A",photos[0].name)]});
  try{await restored.load();assert.equal(restored.memory.selected.size,0);assert.equal(restored.nodes().filter(node=>node.className==="vision-positive-card").length,1);}finally{restored.cleanup();}
});

test("a new EXTEND round waits for explicit selection without losing the previous confirmed gallery",async()=>{
  let round=0;
  const additional={...context,review_kind:"additional"};
  const photos=[localPhoto("A","IMG_1_L01.jpg"),localPhoto("B","IMG_2_L01.jpg","IMG_2")];
  const fixture=componentFixture({photos,getContext:()=>additional,getDefaultSelectionKey:()=>"round-"+round,getUsedImageIds:()=>new Set(round?["A"]:[]),
    memory:{confirmedJob:{job_id:"J",status:"ready",context:additional,photos:[photos[0]],records:[classified("A",photos[0].name)]},confirmedSelectionKey:"round-0"}});
  try{
    await fixture.load();assert.equal(fixture.memory.selected.size,0);
    round=1;fixture.widget.refresh();assert.deepEqual([...fixture.memory.selected],[]);
    selectGroup(fixture,"IMG_2");assert.deepEqual([...fixture.memory.selected],["B"]);
    assert.equal(fixture.nodes().filter(node=>node.className==="vision-group-label").length,1);
    assert.equal(fixture.nodes().filter(node=>node.className==="vision-positive-card").length,1);
  }finally{fixture.cleanup();}
});

test("several physical groups can be selected together without selecting the rest of the catalogue",async()=>{
  const photos=[localPhoto("A","IMG_1_L01.jpg"),localPhoto("B","IMG_1_L02.jpg"),localPhoto("C","IMG_2_L01.jpg","IMG_2"),localPhoto("D","IMG_3_L01.jpg","IMG_3")];
  const fixture=componentFixture({photos});
  try{
    await fixture.load();
    assert.equal(fixture.memory.selected.size,0);
    selectGroup(fixture,0);selectGroup(fixture,1);
    assert.deepEqual([...fixture.memory.selected],["A","B","C"]);
    assert.equal(fixture.nodes().some(node=>node.textContent==="2 grupo(s) / toma(s) · 3 foto(s) seleccionada(s) en esta tanda."),true);
    assert.equal(fixture.nodes().some(node=>String(node.textContent).includes("No repitas frutos entre las fotos")),true);
    await fixture.nodes().find(node=>node.textContent==="Procesar fotos de esta caja").listeners.click();
    assert.equal(fixture.confirmed.length,0);
    assert.equal(fixture.nodes().some(node=>String(node.textContent).includes("Resultados listos para revisión")),true);
  }finally{fixture.cleanup();}
});

test("confirmed batches leave unused groups available for explicit continued capture of the same box",async()=>{
  const photos=[localPhoto("A","IMG_1_L01.jpg"),localPhoto("B","IMG_2_L01.jpg","IMG_2")];
  const used=new Set(),batches=[],requests=[];
  const fixture=componentFixture({photos,getUsedImageIds:()=>used,
    request:async(url,payload)=>({async json(){
      if(url==="/api/vision/photos")return {photos,runtime:{available:true}};
      requests.push(payload.photo_ids);
      const chosen=photos.filter(photo=>payload.photo_ids.includes(photo.photo_id));
      return {job_id:"JOB-"+requests.length,status:"ready",context,photos:chosen,records:chosen.map(photo=>classified(photo.image_id,photo.name))};
    }}),
    onConfirm:async records=>{batches.push(records);for(const record of records)used.add(record.image_id);},
  });
  try{
    await fixture.load();
    for(const name of ["IMG_1","IMG_2"]){
      selectGroup(fixture,name);
      await fixture.nodes().find(node=>node.textContent==="Procesar fotos de esta caja").listeners.click();
      await fixture.nodes().find(node=>node.textContent==="Incorporar fotos a la caja").listeners.click();
      assert.equal(fixture.memory.selected.size,0);
      assert.equal(fixture.nodes().some(node=>node.className==="vision-group-label"&&node.children[1]?.children[0]?.textContent==="Grupo / toma "+name),false);
    }
    assert.deepEqual(requests,[["A"],["B"]]);
    assert.deepEqual(batches.map(batch=>batch.map(record=>record.image_id)),[["A"],["B"]]);
  }finally{fixture.cleanup();}
});

function demoCatalogue(count=394){
  return Array.from({length:count},(_,index)=>{const group="DEMO_"+String(Math.floor(index*34/count)).padStart(2,"0");return localPhoto("PHOTO_"+String(index).padStart(4,"0"),group+"_L"+index+".jpg",group);});
}
function offeredNames(fixture){
  const names=[];
  for(let page=0;page<100;page++){
    names.push(...fixture.nodes().filter(node=>node.className==="vision-individual-photo").map(node=>node.children[2].textContent));
    const next=fixture.nodes().find(node=>node.tagName==="BUTTON"&&node.textContent==="Siguiente");
    if(next.disabled)break;next.listeners.click();
  }
  return names;
}

test("a demo box offers only its 150 prepared photos across pages and selects no remainder",async()=>{
  const photos=demoCatalogue();let pool=null;
  const fixture=componentFixture({photos,getTargetCount:()=>150,getDefaultSelectionKey:()=>"BOX_001",getPhotoPool:()=>pool,onPhotoPool:value=>{pool=structuredClone(value);}});
  try{
    await fixture.load();
    assert.equal(pool.photo_ids.length,150);assert.equal(pool.context_key,"BOX_001");
    assert.equal(fixture.memory.selected.size,0);
    const visible=offeredNames(fixture);
    assert.equal(visible.length,150);assert.equal(new Set(visible).size,150);
    assert.equal(visible.some(name=>name===photos[150].name),false);
    fixture.nodes().find(node=>node.textContent==="Seleccionar fotos de esta caja").listeners.click();
    assert.deepEqual([...fixture.memory.selected],pool.photo_ids);
    assert.equal(fixture.nodes().some(node=>String(node.textContent).includes("Demostración: 150 fotos de un fruto")),true);
  }finally{fixture.cleanup();}
});

test("another demo box excludes the first box's unprocessed photo reservation",async()=>{
  const photos=demoCatalogue();let firstPool=null,secondPool=null;
  const first=componentFixture({photos,getTargetCount:()=>150,getDefaultSelectionKey:()=>"BOX_001",getPhotoPool:()=>firstPool,onPhotoPool:value=>{firstPool=structuredClone(value);}});
  let second;
  try{
    await first.load();
    second=componentFixture({photos,getTargetCount:()=>150,getDefaultSelectionKey:()=>"BOX_002",getContext:()=>({...context,review_kind:"additional"}),getPhotoPool:()=>secondPool,onPhotoPool:value=>{secondPool=structuredClone(value);},getReservedPhotoIds:()=>new Set(firstPool.photo_ids)});
    await second.load();
    assert.equal(secondPool.photo_ids.length,150);assert.equal(secondPool.photo_ids.some(id=>firstPool.photo_ids.includes(id)),false);
    const visible=offeredNames(second);
    assert.equal(visible.some(name=>photos.slice(0,150).some(photo=>photo.name===name)),false);
    assert.equal(first.memory.selected.size,0);
  }finally{second?.cleanup();first.cleanup();}
});

test("refresh and catalog reload retain the same prepared demo pool",async()=>{
  const photos=demoCatalogue();let pool=null;
  const fixture=componentFixture({photos,getTargetCount:()=>150,getDefaultSelectionKey:()=>"BOX_001",getPhotoPool:()=>pool,onPhotoPool:value=>{pool=structuredClone(value);}});
  try{
    await fixture.load();const original=structuredClone(pool);
    fixture.widget.refresh();assert.deepEqual(pool,original);
    await fixture.nodes().find(node=>node.textContent==="Actualizar fotos").listeners.click();
    assert.deepEqual(pool,original);assert.equal(fixture.memory.selected.size,0);
  }finally{fixture.cleanup();}
});

test("demo exhaustion offers only the remaining 94 photos and reports the missing 56 without recycling",async()=>{
  const photos=demoCatalogue(),used=new Set(photos.slice(0,300).map(photo=>photo.image_id));let pool=null;
  const fixture=componentFixture({photos,getTargetCount:()=>150,getDefaultSelectionKey:()=>"BOX_003",getUsedImageIds:()=>used,getPhotoPool:()=>pool,onPhotoPool:value=>{pool=structuredClone(value);}});
  try{
    await fixture.load();
    assert.equal(pool.photo_ids.length,94);assert.equal(pool.photo_ids.some(id=>used.has(id)),false);
    assert.equal(offeredNames(fixture).length,94);
    assert.equal(fixture.nodes().some(node=>String(node.textContent).includes("Faltan 56 fotos disponibles")),true);
    fixture.nodes().find(node=>node.textContent==="Seleccionar fotos de esta caja").listeners.click();
    assert.equal(fixture.memory.selected.size,94);
  }finally{fixture.cleanup();}
});

test("confirming the prepared demo photos empties the selector when the box target has been covered",async()=>{
  const photos=demoCatalogue(10),used=new Set(),records=[],requests=[];let pool=null;
  const fixture=componentFixture({photos,getTargetCount:()=>Math.max(3-records.length,0),getDefaultSelectionKey:()=>"BOX_001",getUsedImageIds:()=>used,getPhotoPool:()=>pool,onPhotoPool:value=>{pool=structuredClone(value);},getConfirmedRecords:()=>records,
    request:async(url,payload)=>({async json(){
      if(url==="/api/vision/photos")return {photos,runtime:{available:true}};
      requests.push(payload.photo_ids);const selected=photos.filter(photo=>payload.photo_ids.includes(photo.photo_id));
      return {job_id:"J",status:"ready",context,photos:selected,records:selected.map(photo=>classified(photo.image_id,photo.name))};
    }}),onConfirm:async incoming=>{records.push(...incoming);for(const record of incoming)used.add(record.image_id);},
  });
  try{
    await fixture.load();fixture.nodes().find(node=>node.textContent==="Seleccionar fotos de esta caja").listeners.click();
    await fixture.nodes().find(node=>node.textContent==="Procesar fotos de esta caja").listeners.click();
    assert.equal(requests[0].length,3);assert.equal(records.length,0);
    await fixture.nodes().find(node=>node.textContent==="Incorporar fotos a la caja").listeners.click();
    assert.equal(records.length,3);assert.deepEqual(pool.photo_ids,[]);
    assert.equal(fixture.nodes().filter(node=>node.className==="vision-individual-photo").length,0);
    assert.equal(fixture.nodes().find(node=>node.textContent==="Seleccionar fotos de esta caja").disabled,true);
    assert.equal(fixture.nodes().some(node=>String(node.textContent).includes("Ya se cubrió el count esperado")),true);
    assert.equal(fixture.nodes().filter(node=>node.className==="vision-positive-card").length,3);
  }finally{fixture.cleanup();}
});

test("a missing target does not expose an arbitrary sample from the demo catalogue",async()=>{
  const fixture=componentFixture({photos:demoCatalogue(10),getTargetCount:()=>null,getDefaultSelectionKey:()=>"BOX_001"});
  try{
    await fixture.load();
    assert.equal(fixture.nodes().filter(node=>node.className==="vision-individual-photo").length,0);
    assert.equal(fixture.nodes().find(node=>node.textContent==="Seleccionar fotos de esta caja").disabled,true);
    assert.equal(fixture.nodes().some(node=>String(node.textContent).includes("Selecciona el count de esta caja")),true);
  }finally{fixture.cleanup();}
});

test("an inactive additional review reserves no photos until the inspector enables that box",async()=>{
  let enabled=false,pool=null;
  const fixture=componentFixture({photos:demoCatalogue(),getTargetCount:()=>150,getDefaultSelectionKey:()=>"BOX_002",getContext:()=>({...context,review_kind:"additional"}),canProcess:()=>enabled,getPhotoPool:()=>pool,onPhotoPool:value=>{pool=structuredClone(value);}});
  try{
    await fixture.load();assert.equal(pool,null);
    assert.equal(fixture.nodes().find(node=>node.textContent==="Seleccionar fotos de esta caja").disabled,true);
    enabled=true;fixture.widget.refresh();
    assert.equal(pool.photo_ids.length,150);
    assert.equal(fixture.nodes().find(node=>node.textContent==="Seleccionar fotos de esta caja").disabled,false);
  }finally{fixture.cleanup();}
});
