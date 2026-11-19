const {test}=require('node:test');
const assert=require('node:assert/strict');
const {describe}=require('../../src/smartfruit/web/field_sources.js');
const config={header_fields:[{key:'lot_id',label:'AgroPeru Lot Number'},{key:'country_origin',label:'Country Of Origin'}],
 qc_columns:['pallet_id','label_brand','size','avg_count_per_box','sample_count','oleocellosis','mold'].map(key=>({key,label:key})),
 qc_summary_fields:[{key:'open_rating',label:'Open Rating'}]};
function capture(){return {qc_header:{lot_id:'LOT_TEST',country_origin:'COUNTRY_TEST'},
 samples:[{sample_id:'SAMPLE_TEST',pallet_id:'PALLET_TEST',vision_records:[],vision_covers_sample:true,
 qc_fields:{pallet_id:'PALLET_TEST',label_brand:'LABEL_TEST',size:'42',avg_count_per_box:'',sample_count:36,oleocellosis:3,mold:0},
 reception:{records:[{lot_id:'LOT_TEST',pallet_id:'PALLET_TEST',label_brand:'LABEL_TEST',country_origin:'COUNTRY_TEST',size_declared:'42',expected_count_per_box:'110'}]}}],qc_summary:{open_rating:''}};}
function field(result,key){return result.samples[0].fields.find(value=>value.key===key);}
test('identification comes from receipt while measured sample comes from Vision',()=>{
 const value=capture();const before=structuredClone(value);const result=describe(value,config);
 assert.equal(result.header[0].source,'Recepción');
 assert.equal(field(result,'pallet_id').source,'Recepción');
 assert.equal(field(result,'sample_count').source,'Vision');
 assert.equal(field(result,'oleocellosis').source,'Vision');
 assert.equal(field(result,'avg_count_per_box').source,'Inspector');
 assert.equal(field(result,'avg_count_per_box').state,'Pendiente');
 assert.deepEqual(value,before);
});
test('observed zero and N/A are registered, missing values stay pending',()=>{
 const value=capture();value.samples[0].qc_fields.avg_count_per_box='N/A';
 const result=describe(value,config);
 assert.equal(field(result,'mold').state,'Registrado');
 assert.equal(field(result,'avg_count_per_box').state,'Registrado');
 assert.equal(result.summary[0].state,'Pendiente');
 assert.equal(result.summary[0].source,'Inspector');
});
test('inspector changes do not overwrite receipt and change displayed origin',()=>{
 const value=capture();value.samples[0].qc_fields.label_brand='Observed label';
 const result=describe(value,config);
 assert.equal(field(result,'label_brand').source,'Inspector');
 assert.equal(value.samples[0].reception.records[0].label_brand,'LABEL_TEST');
});
test('mixed receipt sizes do not choose the first line or fill measurements',()=>{
 const value=capture();value.samples[0].reception.records.push({...value.samples[0].reception.records[0],size_declared:'48'});
 const result=describe(value,config);
 assert.equal(field(result,'size').source,'Inspector');
 assert.equal(field(result,'avg_count_per_box').state,'Pendiente');
});
test('manual sample count remains inspector data before full Vision coverage',()=>{
 const value=capture();value.samples[0].vision_covers_sample=false;
 assert.equal(field(describe(value,config),'sample_count').source,'Inspector');
});
test('explicit optional packing data retains receipt origin and size alias',()=>{
 const value=capture(),sample=value.samples[0],row=sample.reception.records[0];
 Object.assign(row,{grower:'GROWER_TEST',avg_count_per_box:'42',plu_pct:'100',plu_coo:'4048/Mexico',size_declared:'',size:'42'});
 Object.assign(sample.qc_fields,{grower:'GROWER_TEST',avg_count_per_box:'42',plu_pct:'100',plu_coo:'4048/Mexico'});
 const extended={...config,qc_columns:[...config.qc_columns,...['grower','plu_pct','plu_coo'].map(key=>({key,label:key}))]};
 const result=describe(value,extended);
 for(const key of ['grower','avg_count_per_box','plu_pct','plu_coo','size'])assert.equal(field(result,key).source,'Recepción');
});

const summaryConfig={...config,qc_summary_fields:[
 'label_brand','packing_date','plu_coo','open_rating','color_rating'
].map(key=>({key,label:key}))};
function summaryField(result,key){return result.summary.find(value=>value.key===key);}

test('uniform manifest summary fields keep reception origin without replacing inspector ratings',()=>{
 const value=capture(),first=value.samples[0].reception.records[0];
 Object.assign(first,{packing_date:'2026-11-01',plu_coo:'4048/Mexico',open_rating:'Good',color_rating:'Good'});
 value.lot_reception={records:[first,{...first,pallet_id:'PALLET_SECOND'}]};
 value.qc_summary={label_brand:'LABEL_TEST',packing_date:'2026-11-01',plu_coo:'4048/Mexico',open_rating:'Good',color_rating:'Good'};
 const before=structuredClone(value),result=describe(value,summaryConfig);
 for(const key of ['label_brand','packing_date','plu_coo'])assert.equal(summaryField(result,key).source,'Recepción');
 for(const key of ['open_rating','color_rating'])assert.equal(summaryField(result,key).source,'Inspector');
 assert.deepEqual(value,before);
});

test('whole manifest controls summary origin even when current samples have a common label',()=>{
 for(const secondLabel of ['OTHER_LABEL','']){
  const value=capture(),first=value.samples[0].reception.records[0];
  value.lot_reception={records:[first,{...first,pallet_id:'PALLET_SECOND',label_brand:secondLabel}]};
  value.qc_summary.label_brand='LABEL_TEST';
  assert.equal(summaryField(describe(value,summaryConfig),'label_brand').source,'Inspector');
 }
});

test('edited or missing summary values stay inspector data; old captures can use their receipt rows',()=>{
 const value=capture();value.qc_summary.label_brand='LABEL_TEST';
 assert.equal(summaryField(describe(value,summaryConfig),'label_brand').source,'Recepción');
 value.qc_summary.label_brand='Inspector observed label';
 assert.equal(summaryField(describe(value,summaryConfig),'label_brand').source,'Inspector');
 value.qc_summary.label_brand='';
 const empty=summaryField(describe(value,summaryConfig),'label_brand');
 assert.equal(empty.source,'Inspector');assert.equal(empty.state,'Pendiente');
});

test('Reason identifies the defect summary only when it has a computed value and explicit origin',()=>{
 const extended={...config,header_fields:[...config.header_fields,{key:'reason',label:'Reason'}]};
 for(const [reason_source,reason,source,state]of [
  ['defect_summary','Scars: 3 fruits.','Resumen de defectos','Registrado'],
  ['defect_summary','  ','Inspector','Pendiente'],
  ['inspector','Redacción revisada por QC.','Inspector','Registrado'],
  [undefined,'See below','Inspector','Registrado']
 ]){
  const value=capture();value.qc_header.reason=reason;
  if(reason_source!==undefined)value.reason_source=reason_source;
  const before=structuredClone(value);
  const item=describe(value,extended).header.find(field=>field.key==='reason');
  assert.equal(item.source,source);assert.equal(item.state,state);assert.deepEqual(value,before);
 }
});
