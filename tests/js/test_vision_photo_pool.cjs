"use strict";

const assert=require("node:assert/strict");
const {test}=require("node:test");
const {planBoxPhotoPool}=require("../../src/smartfruit/web/vision_defaults.js");

function crop(index,group="TAKE_"+String(Math.floor(index*34/394)).padStart(2,"0")){
  const id="PHOTO_"+String(index).padStart(4,"0");
  return {photo_id:id,image_id:id,name:group+"_L"+index+".jpg",source_group:group,input_kind:"fruit_crop"};
}
const catalogue=Array.from({length:394},(_,index)=>crop(index));

test("a 150-fruit demo box receives only 150 known one-fruit photos from a 394-photo catalogue",()=>{
  const before=structuredClone(catalogue),pool=planBoxPhotoPool(catalogue,{targetCount:150});
  assert.equal(new Set(catalogue.map(photo=>photo.source_group)).size,34);
  assert.equal(pool.status,"ready");assert.equal(pool.knownFruitCount,150);assert.equal(pool.remainingCount,0);
  assert.equal(pool.availableCount,394);assert.deepEqual(pool.photoIds,catalogue.slice(0,150).map(photo=>photo.photo_id));
  assert.deepEqual(catalogue,before);
});

test("unprocessed box reservations remain disjoint and exhaustion never recycles earlier photos",()=>{
  const first=planBoxPhotoPool(catalogue,{targetCount:150});
  const second=planBoxPhotoPool(catalogue,{targetCount:150,reservedPhotoIds:new Set(first.photoIds)});
  assert.equal(second.status,"ready");assert.equal(second.availableCount,244);
  assert.equal(second.photoIds.some(id=>first.photoIds.includes(id)),false);
  const third=planBoxPhotoPool(catalogue,{targetCount:150,reservedPhotoIds:new Set([...first.photoIds,...second.photoIds])});
  assert.equal(third.status,"insufficient");assert.equal(third.knownFruitCount,94);assert.equal(third.remainingCount,56);
  assert.equal(new Set([...first.photoIds,...second.photoIds,...third.photoIds]).size,394);
  const exhausted=planBoxPhotoPool(catalogue,{targetCount:150,usedImageIds:new Set(catalogue.map(photo=>photo.image_id))});
  assert.equal(exhausted.status,"insufficient");assert.equal(exhausted.availableCount,0);
  assert.deepEqual(exhausted.photoIds,[]);assert.equal(exhausted.remainingCount,150);
});

test("reloading the same box keeps its persisted pool even if catalogue order changes",()=>{
  const assigned=planBoxPhotoPool(catalogue,{targetCount:150}).photoIds;
  const persisted=JSON.parse(JSON.stringify(assigned));
  const afterReload=planBoxPhotoPool([...catalogue].reverse(),{targetCount:150,assignedPhotoIds:persisted});
  assert.deepEqual(afterReload.photoIds,assigned);assert.deepEqual(persisted,assigned);
  const increased=planBoxPhotoPool(catalogue,{targetCount:170,assignedPhotoIds:persisted});
  assert.deepEqual(increased.photoIds.slice(0,150),assigned);assert.equal(increased.knownFruitCount,170);
  const decreased=planBoxPhotoPool(catalogue,{targetCount:100,assignedPhotoIds:persisted});
  assert.deepEqual(decreased.photoIds,assigned.slice(0,100));
});

test("already confirmed fruits reduce the remaining quota without reserving replacements for their photos",()=>{
  const original=planBoxPhotoPool(catalogue,{targetCount:150}).photoIds,used=new Set(original.slice(0,50));
  const remaining=planBoxPhotoPool(catalogue,{targetCount:100,assignedPhotoIds:original,usedImageIds:used});
  assert.deepEqual(remaining.photoIds,original.slice(50));assert.equal(remaining.remainingCount,0);
  const covered=planBoxPhotoPool(catalogue,{targetCount:0,assignedPhotoIds:original,usedImageIds:used});
  assert.equal(covered.status,"ready");assert.deepEqual(covered.photoIds,[]);
});

test("legacy scene aliases exclude all corresponding crops while one used crop leaves its siblings available",()=>{
  const photos=[crop(0,"IMG_6426"),crop(1,"IMG_6426"),crop(2,"IMG_6427")];
  const historic=planBoxPhotoPool(photos,{targetCount:2,usedImageIds:new Set(["IMG_6426"])});
  assert.deepEqual(historic.photoIds,[photos[2].photo_id]);assert.equal(historic.status,"insufficient");
  const partial=planBoxPhotoPool(photos,{targetCount:2,usedImageIds:new Set([photos[0].image_id])});
  assert.deepEqual(partial.photoIds,[photos[1].photo_id,photos[2].photo_id]);
});

test("a scene identified by content ID blocks its crops for used and reserved images",()=>{
  const photos=[crop(0,"IMG_6426"),crop(1,"IMG_6426"),crop(2,"IMG_6427"),
    {photo_id:"SCENE_HASH",image_id:"SCENE_HASH",name:"IMG_6426.jpg",source_group:"IMG_6426",input_kind:"scene"}];
  for(const excluded of [{usedImageIds:new Set(["SCENE_HASH"])},{reservedPhotoIds:new Set(["SCENE_HASH"])},{usedImageIds:new Set(["img_6426"])}]){
    const pool=planBoxPhotoPool(photos,{targetCount:3,...excluded});
    assert.deepEqual(pool.photoIds,[photos[2].photo_id]);assert.equal(pool.remainingCount,2);
  }
});

test("scenes never count as one fruit or silently fill a crop quota",()=>{
  const scene={photo_id:"SCENE",image_id:"SCENE",source_group:"OTHER",input_kind:"scene"};
  const scenes=planBoxPhotoPool([scene],{targetCount:150});
  assert.equal(scenes.status,"no_known_counts");assert.equal(scenes.knownFruitCount,0);assert.deepEqual(scenes.photoIds,[]);
  const mixed=planBoxPhotoPool([crop(0),scene],{targetCount:2});
  assert.equal(mixed.status,"insufficient");assert.equal(mixed.knownFruitCount,1);assert.equal(mixed.remainingCount,1);
  assert.equal(mixed.photoIds.includes("SCENE"),false);
});

test("missing or invalid targets do not propose arbitrary demo photos",()=>{
  for(const targetCount of [undefined,null,"150",-1,1.5,NaN,Infinity,Number.MAX_SAFE_INTEGER+1]){
    const pool=planBoxPhotoPool(catalogue,{targetCount});
    assert.equal(pool.status,"target_unavailable");assert.deepEqual(pool.photoIds,[]);assert.equal(pool.remainingCount,null);
  }
});

test("invalid, duplicate, used or reserved persisted assignments cannot add duplicate fruits",()=>{
  const photos=[crop(0),crop(1),crop(2),crop(3)],copy={...photos[0],photo_id:"COPY_SAME_IMAGE"};
  const pool=planBoxPhotoPool([photos[0],photos[0],copy,...photos.slice(1)],{
    targetCount:3,assignedPhotoIds:["MISSING",photos[0].photo_id,photos[0].photo_id,photos[1].photo_id,photos[2].photo_id],
    usedImageIds:new Set([photos[1].image_id]),reservedPhotoIds:new Set([photos[2].photo_id]),
  });
  assert.equal(pool.availableCount,2);assert.equal(pool.status,"insufficient");
  assert.deepEqual(pool.photoIds,[photos[0].photo_id,photos[3].photo_id]);
});
