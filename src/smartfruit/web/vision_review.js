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
    Object.assign(prediction,{review_status:status,reviewed_by:reviewer.trim(),reviewed_at:now.toISOString(),override_label:status==="rejected"?label:null,override_reason:status==="rejected"?(reason.trim()||labels[label]):null});
    return prediction;
  }
  function adjudicate(records,imageId,cropId,status,reviewer,label=null,reason="",now=new Date()){
    const matches=(records||[]).filter(record=>record.image_id===imageId).flatMap(record=>record.fruit_predictions||[]).filter(prediction=>prediction.crop_id===cropId);
    if(!matches.length)throw Error("No se encontró la detección para revisar.");
    const updated=review({...matches[0]},status,reviewer,label,reason,now);
    for(const prediction of matches)for(const key of ["review_status","reviewed_by","reviewed_at","override_label","override_reason"])prediction[key]=updated[key];
    return updated;
  }
  function render(root,records,options={}){
    root.replaceChildren();
    const make=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
    const stats=summary(records);if(!stats.suspected)return;
    root.className="vision-human-review";const heading=make("h4","Revisar sospechas de oleocelosis");root.append(heading,make("p",stats.confirmed+" confirmadas · "+stats.rejected+" rechazadas · "+stats.pending+" pendientes"));
    const reviewerLabel=make("label","Revisor QC"),reviewer=make("input");reviewer.type="text";reviewer.autocomplete="name";reviewer.value=options.reviewer||"";reviewer.placeholder="Nombre del inspector";reviewerLabel.append(reviewer);root.append(reviewerLabel);
    const message=make("p");message.setAttribute("role","alert");root.append(message);
    const rendered=new Set();for(const record of records){if(rendered.has(record.image_id))continue;rendered.add(record.image_id);(record.fruit_predictions||[]).forEach((prediction,index)=>{
      if(prediction.predicted_class!=="con_oleocelosis")return;
      const row=make("div");row.className="vision-review-row";row.append(make("strong",record.image_id+" · "+prediction.crop_id));
      const photo=options.photos?.find(item=>item.image_id===record.image_id||item.name===record.inference?.source_filename||item.name?.toLowerCase()===prediction.crop_id?.toLowerCase());
      const imageURL=photo?.evidence_url||photo?.url;
      if(imageURL){const image=make("img");image.src=imageURL;image.alt="Foto de la detección "+prediction.crop_id;image.loading="lazy";image.style.maxWidth="100%";image.style.maxHeight="240px";row.append(image);const region=record.inference?.fruit_boxes_xyxy?.[index];if(region&&region.length===4){const canvas=make("canvas");canvas.setAttribute("aria-label","Recorte de "+prediction.crop_id);canvas.style.maxWidth="100%";canvas.style.maxHeight="240px";image.addEventListener("load",()=>{const [x1,y1,x2,y2]=region;canvas.width=x2-x1;canvas.height=y2-y1;canvas.getContext("2d")?.drawImage(image,x1,y1,x2-x1,y2-y1,0,0,canvas.width,canvas.height);image.hidden=true;});row.append(canvas);}}
      const box=record.inference?.fruit_boxes_xyxy?.[index];if(box)row.append(make("small","Detección "+(index+1)+" · región ["+box.join(", ")+"]"));
      row.append(make("p",prediction.review_status==="confirmed"?"Confirmada por "+prediction.reviewed_by:prediction.review_status==="rejected"?"Rechazada: "+(labels[prediction.override_label]||prediction.override_label):"Pendiente de revisión"));
      const label=make("select");label.setAttribute("aria-label","Corrección de "+prediction.crop_id);const blank=make("option","Selecciona corrección");blank.value="";label.append(blank);for(const [value,text]of Object.entries(labels)){const option=make("option",text);option.value=value;label.append(option);}label.value=prediction.override_label||"";
      const reason=make("input");reason.type="text";reason.placeholder="Motivo (obligatorio para Otro)";reason.setAttribute("aria-label","Motivo de corrección");reason.value=prediction.override_reason||"";
      const actions=make("div");actions.className="actions";
      for(const [status,text]of [["confirmed","Confirmar oleocelosis"],["rejected","Rechazar positivo"]]){const button=make("button",text);button.type="button";button.className="secondary";button.disabled=Boolean(options.disabled);button.addEventListener("click",()=>{try{adjudicate(records,record.image_id,prediction.crop_id,status,reviewer.value,label.value,reason.value);options.onReviewer?.(reviewer.value);options.onChange?.();render(root,records,{...options,reviewer:reviewer.value});}catch(error){message.textContent=error.message;}});actions.append(button);}
      row.append(label,reason,actions);root.append(row);
    });}
  }
  const api={summary,review,adjudicate,render};if(typeof module!=="undefined"&&module.exports)module.exports=api;scope.SmartFruitVisionReview=api;
})(typeof window!=="undefined"?window:globalThis);
