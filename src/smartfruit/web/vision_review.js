/* QC adjudication preserves model predictions and changes only human review fields. */
(function(scope){
  "use strict";
  const labels={styler:"Styler",scar:"Scar",inking:"Inking",clean:"Sin defecto",other:"Otro"};
  function summary(records){
    let total=0,suspected=0,confirmed=0,pending=0,rejected=0;
    const seen=new Set();
    for(const record of records||[]){if(seen.has(record.image_id))continue;seen.add(record.image_id);total+=record.total_fruits||0;
      for(const prediction of record.fruit_predictions||[]){if(prediction.predicted_class!=="con_oleocelosis")continue;suspected++;
        if(prediction.review_status==="confirmed")confirmed++;else if(prediction.review_status==="rejected")rejected++;else pending++;
      }
    }
    return {total,suspected,confirmed,pending,rejected};
  }
  function review(prediction,status,reviewer,label=null,reason="",now=new Date()){
    if(prediction.predicted_class!=="con_oleocelosis")throw Error("Esta detección no es un positivo sospechoso.");
    if(!["confirmed","rejected"].includes(status))throw Error("Selecciona confirmar o rechazar.");
    if(typeof reviewer!=="string"||!reviewer.trim())throw Error("Registra el nombre de quien revisa las detecciones.");
    if(status==="rejected"&&(!labels[label]||(label==="other"&&!reason.trim())))throw Error("Selecciona el defecto observado y describe la corrección si eliges Otro.");
    Object.assign(prediction,{review_status:status,reviewed_by:reviewer.trim(),reviewed_at:now.toISOString(),override_label:status==="rejected"?label:null,override_reason:status==="rejected"?(reason.trim()||labels[label]):null,qc_included:status==="confirmed"});
    return prediction;
  }
  function adjudicate(records,imageId,cropId,status,reviewer,label=null,reason="",now=new Date()){
    const matches=(records||[]).filter(record=>record.image_id===imageId).flatMap(record=>record.fruit_predictions||[]).filter(prediction=>prediction.crop_id===cropId);
    if(!matches.length)throw Error("No se encontró la detección para revisar.");
    const updated=review({...matches[0]},status,reviewer,label,reason,now);
    for(const prediction of matches)for(const key of ["review_status","reviewed_by","reviewed_at","override_label","override_reason","qc_included"])prediction[key]=updated[key];
    return updated;
  }
  function selected(prediction){
    if(prediction.predicted_class!=="con_oleocelosis")return false;
    return typeof prediction.qc_included==="boolean"?prediction.qc_included:prediction.review_status!=="rejected";
  }
  function selectionSummary(records){
    const stats=summary(records);let included=0;const seen=new Set();
    for(const record of records||[]){
      if(seen.has(record.image_id))continue;seen.add(record.image_id);
      included+=(record.fruit_predictions||[]).filter(selected).length;
    }
    return {total:stats.total,suspected:stats.suspected,included,excluded:stats.suspected-included,pending:stats.pending};
  }
  function setIncluded(records,imageId,cropId,included){
    if(typeof included!=="boolean")throw Error("El check de oleocelosis debe estar marcado o desmarcado.");
    const matches=(records||[]).filter(record=>record.image_id===imageId)
      .flatMap(record=>record.fruit_predictions||[]).filter(prediction=>prediction.crop_id===cropId);
    if(!matches.length||matches.some(prediction=>prediction.predicted_class!=="con_oleocelosis"))throw Error("No se encontró el positivo de Vision para revisar.");
    for(const prediction of matches){
      if(selected(prediction)!==included){
        prediction.review_status="pending";
        for(const field of ["reviewed_by","reviewed_at","override_label","override_reason"])prediction[field]=null;
      }
      prediction.qc_included=included;
    }
  }
  function applySelection(records,reviewer,now=new Date()){
    const predictions=(records||[]).flatMap(record=>record.fruit_predictions||[])
      .filter(prediction=>prediction.predicted_class==="con_oleocelosis");
    if(!predictions.length)return records;
    if(typeof reviewer!=="string"||!reviewer.trim())throw Error("Registra el nombre de quien revisa las fotos.");
    const updates=new Map();
    for(const record of records||[]){
      for(const prediction of record.fruit_predictions||[]){
        if(prediction.predicted_class!=="con_oleocelosis")continue;
        const included=selected(prediction),status=included?"confirmed":"rejected";
        const key=JSON.stringify([record.image_id,prediction.crop_id]);
        if(updates.has(key))continue;
        const consistent=prediction.review_status===status&&prediction.reviewed_by&&prediction.reviewed_at;
        const updated=consistent?{...prediction,qc_included:included}:review({...prediction},status,reviewer,
          included?null:prediction.override_label||"other",
          included?"":prediction.override_reason||"Excluido por QC mediante el check de oleocelosis.",now);
        updates.set(key,updated);
      }
    }
    // Prepare all changes before mutating, including duplicate copies of a JSON.
    for(const record of records||[])for(const prediction of record.fruit_predictions||[]){
      const updated=updates.get(JSON.stringify([record.image_id,prediction.crop_id]));
      if(updated)for(const field of ["review_status","reviewed_by","reviewed_at","override_label","override_reason","qc_included"])prediction[field]=updated[field];
    }
    return records;
  }
  function render(root,records,options={}){
    root.replaceChildren();
    if(!root.visionReviewEventsBound){
      root.addEventListener("input",event=>event.stopPropagation());
      root.addEventListener("change",event=>event.stopPropagation());
      root.visionReviewEventsBound=true;
    }
    const make=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
    const stats=selectionSummary(records);if(!stats.suspected)return {applySelection:()=>records,hasPendingChanges:()=>false};
    root.className="vision-human-review";
    root.append(make("h4","Oleocelosis"),make("p","Desmarca las detecciones que no correspondan a oleocelosis.","hint"));
    const count=make("p");count.setAttribute("aria-live","polite");root.append(count);
    const reviewerLabel=make("label","Revisor QC"),reviewer=make("input");
    reviewer.type="text";reviewer.autocomplete="name";reviewer.value=options.reviewer||(records||[]).flatMap(record=>record.fruit_predictions||[]).find(prediction=>prediction.reviewed_by)?.reviewed_by||"";reviewer.placeholder="Nombre del inspector";reviewer.disabled=Boolean(options.disabled);
    reviewer.addEventListener("input",()=>options.onReviewer?.(reviewer.value));
    reviewerLabel.append(reviewer);root.append(reviewerLabel);
    const message=make("p");message.setAttribute("role","alert");root.append(message);
    const grid=make("div");grid.className="vision-positive-grid";root.append(grid);
    const controls=[];let applyButton=null;
    function update(){
      const current=selectionSummary(records);
      count.textContent=current.included+" activas · "+current.excluded+" excluidas";
      for(const {prediction,check,row}of controls){check.checked=selected(prediction);row.className="vision-review-row vision-positive-card"+(check.checked?"":" vision-review-excluded");}
      if(applyButton){applyButton.disabled=Boolean(options.disabled)||current.pending===0;applyButton.hidden=current.pending===0;}
    }
    function commit(name=reviewer.value){
      applySelection(records,name);options.onReviewer?.(name);message.textContent="";update();options.onChange?.();return records;
    }
    const rendered=new Set();for(const record of records){if(rendered.has(record.image_id))continue;rendered.add(record.image_id);(record.fruit_predictions||[]).forEach((prediction,index)=>{
      if(prediction.predicted_class!=="con_oleocelosis")return;
      const row=make("figure");
      const photo=options.photos?.find(item=>item.image_id===record.image_id||item.name===record.inference?.source_filename||item.name?.toLowerCase()===prediction.crop_id?.toLowerCase());
      const imageURL=photo?.evidence_url||photo?.url;
      if(imageURL){
        const image=make("img");image.src=imageURL;image.alt="Detección "+prediction.crop_id;image.loading="lazy";
        const view=options.onOpenImage?make("button"):make("div");view.className="vision-positive-open";
        if(options.onOpenImage){view.type="button";view.setAttribute("aria-label","Ampliar "+prediction.crop_id);view.addEventListener("click",()=>options.onOpenImage({url:imageURL,name:prediction.crop_id}));}
        view.append(image);row.append(view);
        const region=record.inference?.fruit_boxes_xyxy?.[index];
        if(Array.isArray(region)&&region.length===4&&region.every(Number.isFinite)&&region[2]>region[0]&&region[3]>region[1]){
          const canvas=make("canvas");canvas.setAttribute("aria-label","Recorte de "+prediction.crop_id);canvas.style.width="100%";canvas.style.height="160px";canvas.style.objectFit="contain";
          image.addEventListener("load",()=>{const [x1,y1,x2,y2]=region;canvas.width=x2-x1;canvas.height=y2-y1;const context=canvas.getContext?.("2d");if(context){context.drawImage(image,x1,y1,x2-x1,y2-y1,0,0,canvas.width,canvas.height);image.hidden=true;}});view.append(canvas);
        }
      }else row.append(make("p","Imagen no disponible","hint"));
      const caption=make("figcaption");caption.append(make("small",prediction.crop_id));
      const label=make("label");label.className="vision-review-check";
      const check=make("input");check.type="checkbox";check.checked=selected(prediction);check.disabled=Boolean(options.disabled);check.setAttribute("aria-label","Contar como oleocelosis: "+prediction.crop_id);
      check.addEventListener("change",event=>{event.stopPropagation?.();setIncluded(records,record.image_id,prediction.crop_id,check.checked);update();options.onChange?.();});
      label.append(check,make("span","Contar como oleocelosis"));caption.append(label);row.append(caption);grid.append(row);controls.push({prediction,check,row});
    });}
    if(!options.deferApply&&!options.disabled){
      applyButton=make("button","Aplicar selección");applyButton.type="button";
      applyButton.addEventListener("click",()=>{try{commit();}catch(error){message.textContent=error.message;reviewer.focus?.();}});root.append(applyButton);
    }
    update();
    return {applySelection:commit,hasPendingChanges:()=>summary(records).pending>0};
  }
  const api={summary,review,adjudicate,selected,setIncluded,selectionSummary,applySelection,render};if(typeof module!=="undefined"&&module.exports)module.exports=api;scope.SmartFruitVisionReview=api;
})(typeof window!=="undefined"?window:globalThis);
