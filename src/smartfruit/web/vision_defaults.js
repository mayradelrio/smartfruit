/* A default take is a convenience for the demo; the inspector still confirms it. */
(function (scope) {
  "use strict";
  const contextFields = ["lot_id", "pallet_id", "sample_id", "review_kind"];

  function contextKey(context) {
    if (!context || contextFields.some(key => typeof context[key] !== "string" || !context[key].trim())) return null;
    if (!["initial", "additional"].includes(context.review_kind.trim())) return null;
    return JSON.stringify(contextFields.map(key => context[key].trim()));
  }

  function chooseDefaultPhotoIds(groups, context, {reservedPhotoIds = new Set(), preferredIndex = 0} = {}) {
    if (!contextKey(context) || !Array.isArray(groups) || !groups.length) return [];
    const reserved = new Set(reservedPhotoIds);
    const first = Number.isSafeInteger(preferredIndex) && preferredIndex >= 0 ? preferredIndex % groups.length : 0;
    for (let offset = 0; offset < groups.length; offset++) {
      const photos = groups[(first + offset) % groups.length]?.photos;
      // Keep a take complete: a used/reserved member makes this group unavailable.
      if (!Array.isArray(photos) || !photos.length || photos.some(photo =>
        !photo || typeof photo.photo_id !== "string" || !photo.photo_id || photo.used || reserved.has(photo.photo_id)
      )) continue;
      return Array.from(new Set(photos.map(photo => photo.photo_id)));
    }
    return [];
  }

  function planBoxPhotoPool(photos, {targetCount, assignedPhotoIds = [], usedImageIds = new Set(), reservedPhotoIds = new Set()} = {}) {
    const catalogue=Array.isArray(photos)?photos:[],used=new Set(usedImageIds||[]),reserved=new Set(reservedPhotoIds||[]);
    const usedGroups=new Set([...used,...reserved].filter(value=>typeof value==="string").map(value=>value.trim().toLowerCase()));
    const groupName=photo=>typeof photo.source_group==="string"?photo.source_group.trim().toLowerCase():"";
    const blocked=photo=>photo.used===true||used.has(photo.photo_id)||used.has(photo.image_id)||reserved.has(photo.photo_id)||reserved.has(photo.image_id)||(groupName(photo)!==""&&usedGroups.has(groupName(photo)));
    // A used full scene also reserves all of its one-fruit crops, even when the
    // caller knows only the scene's content-based ID rather than its filename.
    const blockedSceneGroups=new Set(catalogue.filter(photo=>photo&&photo.input_kind==="scene"&&blocked(photo)).map(groupName).filter(Boolean));
    const seenIds=new Set(),seenImages=new Set(),available=[];let hasKnownCounts=false;
    for(const photo of catalogue){
      if(!photo||photo.input_kind!=="fruit_crop"||typeof photo.photo_id!=="string"||!photo.photo_id.trim())continue;
      hasKnownCounts=true;
      if(blocked(photo)||blockedSceneGroups.has(groupName(photo))||seenIds.has(photo.photo_id)||(typeof photo.image_id==="string"&&seenImages.has(photo.image_id)))continue;
      seenIds.add(photo.photo_id);if(typeof photo.image_id==="string")seenImages.add(photo.image_id);available.push(photo);
    }
    const empty={photoIds:[],knownFruitCount:0,remainingCount:null,availableCount:available.length};
    if(!Number.isSafeInteger(targetCount)||targetCount<0)return {...empty,status:"target_unavailable"};
    if(targetCount===0)return {...empty,remainingCount:0,status:"ready"};
    if(!hasKnownCounts)return {...empty,remainingCount:targetCount,status:"no_known_counts"};
    const allowed=new Set(available.map(photo=>photo.photo_id)),photoIds=[],assigned=new Set();
    for(const id of Array.isArray(assignedPhotoIds)?assignedPhotoIds:[]){
      if(photoIds.length>=targetCount)break;
      if(allowed.has(id)&&!assigned.has(id)){photoIds.push(id);assigned.add(id);}
    }
    for(const photo of available){
      if(photoIds.length>=targetCount)break;
      if(!assigned.has(photo.photo_id)){photoIds.push(photo.photo_id);assigned.add(photo.photo_id);}
    }
    return {photoIds,knownFruitCount:photoIds.length,remainingCount:targetCount-photoIds.length,availableCount:available.length,status:photoIds.length===targetCount?"ready":"insufficient"};
  }

  const api = {contextKey, chooseDefaultPhotoIds, planBoxPhotoPool};
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  scope.SmartFruitVisionDefaults = api;
})(typeof window !== "undefined" ? window : globalThis);
