"use strict";
const assert=require("node:assert/strict"),{test}=require("node:test");
const {summary,review,adjudicate}=require("../../src/smartfruit/web/vision_review.js");
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
