/* Local photo capture: inference results stay pending until the inspector confirms. */
(function (scope) {
  "use strict";
  const contextKeys = ["lot_id", "pallet_id", "sample_id", "review_kind"];
  let catalogue = null;
  let catalogueRequest = null;

  function sameContext(first, second) {
    return contextKeys.every(key => String(first?.[key] ?? "").trim() === String(second?.[key] ?? "").trim());
  }

  function groupPhotos(photos, usedImageIds = new Set()) {
    const groups = new Map();
    for (const photo of photos) {
      const key = photo.source_group || photo.name;
      if (!groups.has(key)) groups.set(key, {name:key, photos:[], crops:true});
      const group = groups.get(key);
      group.photos.push({...photo, used:usedImageIds.has(photo.image_id)||(photo.input_kind==="fruit_crop"&&usedImageIds.has(photo.source_group))});
      group.crops = group.crops && photo.input_kind === "fruit_crop";
    }
    return Array.from(groups.values());
  }

  function positivePhotos(job, availablePhotos = []) {
    const validPhotos=Array.isArray(availablePhotos)?availablePhotos.filter(photo=>photo&&typeof photo==="object"):[];
    const photos = new Map(validPhotos.map(photo => [photo.image_id || photo.photo_id, photo]));
    for (const photo of Array.isArray(job.photos)?job.photos:[]) if(photo&&typeof photo==="object")photos.set(photo.image_id || photo.photo_id, photo);
    const byName = new Map(Array.from(photos.values()).map(photo => [photo.name?.toLowerCase(),photo]));
    const seen = new Set(), result = [];
    function appendPhoto(record,photo,positive,metadata={}) {
      if(!photo || seen.has(photo.image_id||photo.photo_id))return;
      const photoId=photo.photo_id;
      const snapshot=job.job_id&&photoId?"/api/vision/jobs/"+encodeURIComponent(job.job_id)+"/photos/"+encodeURIComponent(photoId)+"/image":null;
      const url=photo.evidence_url||snapshot||photo.url;if(!url)return;
      seen.add(photo.image_id||photoId);
      const confidences=positive.map(prediction=>prediction.confidence).filter(value=>typeof value==="number"&&Number.isFinite(value)&&value>=0&&value<=1);
      result.push({image_id:photo.image_id||photoId,name:metadata.source_filename||photo.name||record.image_id,url,
        input_kind:metadata.input_kind||photo.input_kind||"scene",affected:positive.length,total:record.total_fruits,
        confidence:confidences.length?confidences.reduce((sum,value)=>sum+value,0)/confidences.length:null});
    }
    for (const record of Array.isArray(job.records)?job.records:[]) {
      if(!record||typeof record!=="object")continue;
      const positive = (Array.isArray(record.fruit_predictions)?record.fruit_predictions:[]).filter(prediction => prediction?.predicted_class === "con_oleocelosis");
      if (!positive.length) continue;
      const photo = photos.get(record.image_id), metadata = record.inference || {};
      if(photo){appendPhoto(record,photo,positive,metadata);continue;}
      // Los JSON históricos identifican la toma; crop_id conserva el nombre del fruto.
      for(const prediction of positive){
        const name=typeof prediction.crop_id==="string"?prediction.crop_id.split(/[\\/]/).pop().toLowerCase():"";
        const crop=byName.get(name);if(crop)appendPhoto({...record,total_fruits:1},crop,[prediction]);
      }
    }
    return result;
  }

  function checkReady(job, context) {
    if (!sameContext(job.context, context)) throw Error("El resultado pertenece a otro lote, paleta o revisión. No se incorporó a la inspección.");
    if (job.status !== "ready" || !Array.isArray(job.records) || !job.records.length) throw Error("Vision no devolvió resultados listos para confirmar.");
    if (job.records.some(record => !record || typeof record.image_id !== "string" || !Number.isInteger(record.total_fruits) || record.total_fruits < 0 || !Number.isInteger(record.oleocellosis_count) || record.oleocellosis_count < 0 || record.oleocellosis_count > record.total_fruits)) throw Error("Vision devolvió cantidades inválidas. Se conservaron los resultados anteriores.");
    if (!job.records.some(record => record.total_fruits > 0)) throw Error("No se identificaron frutos en las fotos seleccionadas. Revisa las imágenes antes de continuar.");
    return job.records;
  }

  async function processPhotos(request, context, photoIds, onProgress, wait = milliseconds => new Promise(resolve => setTimeout(resolve, milliseconds))) {
    if (!photoIds.length) throw Error("Selecciona las fotos de esta caja antes de procesar.");
    let job = await (await request("/api/vision/jobs", {...context, photo_ids:photoIds})).json();
    const jobId = job.job_id;
    if (typeof jobId !== "string" || !jobId) throw Error("Vision no devolvió un identificador de procesamiento.");
    const started = Date.now();
    while (true) {
      if (job.job_id !== jobId || !sameContext(job.context, context)) throw Error("El procesamiento devolvió una asociación distinta de la seleccionada.");
      onProgress(job);
      if (job.status === "failed") {const error=Error(job.error || "No se pudieron procesar las imágenes.");error.code=job.error_type==="timeout"||job.phase==="TIMEOUT"?"TIMEOUT":"ERROR";throw error;}
      if (job.status === "ready") { checkReady(job, context); return job; }
      if (!["queued", "running"].includes(job.status)) throw Error("Estado de Vision desconocido.");
      if (Date.now() - started > 15 * 60 * 1000) {const error=Error("Vision no respondió a tiempo. Reintenta para recuperar el trabajo de esta caja.");error.code="TIMEOUT";throw error;}
      await wait(900);
      job = await (await request("/api/vision/jobs/" + encodeURIComponent(jobId))).json();
    }
  }

  function create(options) {
    const {root, request, getContext, getUsedImageIds, onConfirm} = options;
    const memory = options.memory || {};
    if (!(memory.selected instanceof Set)) memory.selected = new Set();
    if (!(memory.openGroups instanceof Set)) memory.openGroups = new Set();
    let busy = false, destroyed = false, loaded = false, page = 0, search = "", issue = "";
    const make = (tag, text, className) => {
      const node = document.createElement(tag);
      if (text !== undefined) node.textContent = text;
      if (className) node.className = className;
      return node;
    };
    root.classList.add("vision-capture");
    root.addEventListener("input", event => event.stopPropagation());
    root.addEventListener("change", event => event.stopPropagation());
    const header = make("div", undefined, "vision-heading");
    header.append(make("h4", "Fotos disponibles"), make("span", "Vision integrada", "auto-tag"));
    const description = make("p", "Añade la foto general y las fotos grupales por defecto. No repitas frutos entre las fotos que se suman al conteo.", "hint");
    const catalogueStatus = make("p", "Consultando las fotos disponibles…", "hint");
    const controls = make("div", undefined, "vision-photo-controls");
    const searchInput = make("input");searchInput.type="search";searchInput.placeholder="Buscar toma o fotografía";searchInput.setAttribute("aria-label", "Buscar fotos disponibles");
    searchInput.addEventListener("input", () => {search=searchInput.value.trim().toLowerCase();page=0;drawGroups();});
    const reload = make("button", "Actualizar fotos", "quiet");reload.type="button";reload.addEventListener("click", () => run(() => load(true)));
    controls.append(searchInput, reload);
    const groupsArea = make("div", undefined, "vision-photo-groups");
    const navigation = make("div", undefined, "vision-photo-navigation");
    const previous = make("button", "Anterior", "quiet"), next=make("button", "Siguiente", "quiet"), pageText=make("span", "", "hint");
    previous.type=next.type="button";
    previous.addEventListener("click", () => {page--;drawGroups();});next.addEventListener("click", () => {page++;drawGroups();});navigation.append(previous,pageText,next);
    const actions=make("div",undefined,"actions");
    const selectedText=make("p","Sin fotos seleccionadas.","hint");
    const poolText=make("p","","hint");
    const selectBox=make("button","Seleccionar fotos de esta caja","secondary");selectBox.type="button";
    const process=make("button","Procesar fotos de esta caja");process.type="button";
    const clear=make("button","Limpiar selección","quiet");clear.type="button";
    clear.addEventListener("click",()=>{memory.selected.clear();memory.job=null;draw();});
    process.addEventListener("click",()=>run(async()=>{
      const context={...getContext()};
      if (!contextKeys.every(key=>String(context[key]||"").trim())) throw Error("Completa la identificación de la paleta antes de procesar sus fotos.");
      if (options.canProcess && !options.canProcess()) throw Error("Esta paleta ya tiene revisiones adicionales. Procesa la siguiente caja desde EXTEND.");
      memory.job={status:"queued",phase:"QUEUED",context,progress:{completed:0,total:memory.selected.size},records:[]};drawResult();
      memory.job=await processPhotos(request,context,Array.from(memory.selected),job=>{memory.job=job;drawResult();});
      if (!sameContext(context,getContext())) throw Error("La inspección cambió durante el procesamiento. No se incorporaron los resultados.");
      options.onStatus?.("Vision terminó. Revisa cada sospecha de oleocelosis.");
    }));
    actions.append(selectBox,process,clear);
    const result=make("div",undefined,"vision-capture-result");result.setAttribute("aria-live","polite");
    const imageDialog=make("dialog",undefined,"vision-image-dialog");imageDialog.setAttribute("aria-label","Imagen clasificada con oleocelosis");
    const imageClose=make("button","Cerrar imagen","quiet vision-image-close");imageClose.type="button";
    const imageTitle=make("h4"),largeImage=make("img",undefined,"vision-image-large"),imageCaption=make("p",undefined,"hint");
    largeImage.alt="";imageDialog.append(imageClose,imageTitle,largeImage,imageCaption);imageDialog.hidden=true;
    let imageOpener=null;
    function closeImage(){if(typeof imageDialog.close==="function")imageDialog.close();imageDialog.hidden=true;imageOpener?.focus?.();}
    imageClose.addEventListener("click",closeImage);
    imageDialog.addEventListener("cancel",event=>{event.preventDefault?.();closeImage();});
    imageDialog.addEventListener("click",event=>{if(event.target===imageDialog)closeImage();});
    root.append(header,description,catalogueStatus,controls,poolText,groupsArea,navigation,selectedText,actions,result,imageDialog);
    let offeredPhotos=[];
    selectBox.addEventListener("click",()=>{memory.job=null;for(const photo of offeredPhotos)memory.selected.add(photo.photo_id);drawGroups();drawResult();});

    function defaultSelectionKey() {
      return options.getDefaultSelectionKey?.() || scope.SmartFruitVisionDefaults?.contextKey(getContext());
    }

    async function run(action) {
      if (busy || destroyed) return;
      busy=true;issue="";draw();
      try { await (options.runAction || (fn=>fn()))(action); }
      catch (error) {memory.failureState=error.code==="TIMEOUT"?"TIMEOUT":"ERROR";issue=error.message || "No se pudo completar Vision.";options.onError?.(issue);}
      finally {busy=false;if (!destroyed) draw();}
    }

    async function load(force=false) {
      try {
        if (force) catalogue=null;
        if (!catalogue) {
          if (!catalogueRequest) catalogueRequest=request("/api/vision/photos").then(response=>response.json()).then(data=>{
            if (!Array.isArray(data.photos)) throw Error("No se pudo leer el catálogo de fotografías.");
            catalogue=data;return data;
          }).finally(()=>{catalogueRequest=null;});
          await catalogueRequest;
        }
        loaded=true;issue="";
      } catch (error) {
        loaded=true;issue="No se pudo consultar Vision integrada: "+error.message+" Puedes usar la importación de JSON disponible debajo.";
      }
      if (!destroyed) draw();
    }

    function drawGroups() {
      const used=getUsedImageIds();
      const photos=catalogue?.photos || [];
      const allGroups=groupPhotos(photos,used);
      for (const group of allGroups) for(const photo of group.photos) if(photo.used) memory.selected.delete(photo.photo_id);
      const reserved=options.getReservedPhotoIds?.()||new Set();
      const available=allGroups.flatMap(group=>group.photos).filter(photo=>!photo.used&&!reserved.has(photo.photo_id)&&!reserved.has(photo.image_id));
      let visible=available;poolText.textContent="";
      const enabled=options.canProcess?.()!==false;
      if(!enabled){visible=[];poolText.textContent="La selección de fotos está inactiva para esta revisión.";}
      else if(available.some(photo=>photo.input_kind==="scene")){visible=available.filter(photo=>photo.input_kind==="scene");poolText.textContent="Fotos grupales de la caja. Los recortes históricos siguen disponibles al importar JSON.";}
      else if(options.getTargetCount){
        const target=options.getTargetCount(),key=defaultSelectionKey();
        const assigned=options.getPhotoPool?.();
        const previous=assigned?.context_key===key?assigned.photo_ids:[];
        const planner=scope.SmartFruitVisionDefaults?.planBoxPhotoPool;
        const plan=planner?planner(photos,{targetCount:target,assignedPhotoIds:previous,usedImageIds:used,reservedPhotoIds:reserved}):{photoIds:[],status:"target_unavailable"};
        const allowed=new Set(plan.photoIds);visible=available.filter(photo=>allowed.has(photo.photo_id));
        if(catalogue&&plan.status!=="target_unavailable"&&plan.status!=="no_known_counts"){
          const pool={context_key:key,photo_ids:plan.photoIds,target_count:target};
          if(JSON.stringify(pool)!==JSON.stringify(assigned))options.onPhotoPool?.(pool);
        }
        poolText.textContent=plan.status==="target_unavailable"?"Selecciona el count de esta caja en el manifiesto para preparar sus fotos de demostración.":plan.status==="no_known_counts"?"La preparación de demostración necesita recortes de un fruto por foto. Las fotos completas se cuentan después de analizarlas.":plan.status==="insufficient"?"Demostración: quedan "+plan.knownFruitCount+" fotos de un fruto para "+target+" unidades pendientes. Faltan "+plan.remainingCount+" fotos disponibles; no se reutilizan las de otras cajas.":target===0?"Ya se cubrió el count esperado de esta caja con las fotos confirmadas.":"Demostración: "+plan.knownFruitCount+" fotos de un fruto preparadas para las "+target+" unidades pendientes de esta caja.";
      }
      offeredPhotos=visible;const visibleIds=new Set(visible.map(photo=>photo.photo_id));
      if(catalogue&&enabled)for(const id of memory.selected)if(!visibleIds.has(id))memory.selected.delete(id);
      const groups=groupPhotos(visible).filter(group=>group.name.toLowerCase().includes(search)||group.photos.some(photo=>photo.name.toLowerCase().includes(search)));
      const pageSize=6, pages=Math.max(1,Math.ceil(groups.length/pageSize));page=Math.max(0,Math.min(page,pages-1));
      groupsArea.replaceChildren();
      for (const group of groups.slice(page*pageSize,(page+1)*pageSize)) {
        const card=make("div",undefined,"vision-photo-group");
        const groupLabel=make("label",undefined,"vision-group-label");
        const checkbox=make("input");checkbox.type="checkbox";
        const available=group.photos.filter(photo=>!photo.used),selected=available.filter(photo=>memory.selected.has(photo.photo_id)).length;
        checkbox.checked=available.length>0&&selected===available.length;checkbox.indeterminate=selected>0&&selected<available.length;checkbox.disabled=busy||!available.length;
        checkbox.addEventListener("change",()=>{memory.job=null;for(const photo of available){if(checkbox.checked)memory.selected.add(photo.photo_id);else memory.selected.delete(photo.photo_id);}drawGroups();drawResult();});
        const labelText=make("span");labelText.append(make("strong","Grupo / toma "+group.name),make("small",group.photos.length+(group.crops?" recortes de una toma":" fotografía(s)")+(available.length<group.photos.length?" · "+(group.photos.length-available.length)+" ya utilizadas":"")));
        groupLabel.append(checkbox,labelText);card.append(groupLabel);
        const thumbs=make("div",undefined,"vision-group-thumbnails");
        for (const photo of group.photos.slice(0,3)) {const image=make("img");image.src=photo.url;image.alt=photo.name;image.loading="lazy";thumbs.append(image);}card.append(thumbs);
        const details=make("details",undefined,"vision-photo-details");details.append(make("summary","Ver / elegir fotos individuales"));
        details.open=memory.openGroups.has(group.name);details.addEventListener("toggle",()=>{if(details.open)memory.openGroups.add(group.name);else memory.openGroups.delete(group.name);});
        const individual=make("div",undefined,"vision-individual-photos");
        for(const photo of group.photos){
          const label=make("label",undefined,"vision-individual-photo"),check=make("input");check.type="checkbox";check.checked=memory.selected.has(photo.photo_id);check.disabled=busy||photo.used;
          const image=make("img");image.src=photo.url;image.alt="";image.loading="lazy";
          const name=make("span",photo.name+(photo.used?" · utilizada":""));label.append(check,image,name);
          check.addEventListener("change",()=>{memory.job=null;if(check.checked)memory.selected.add(photo.photo_id);else memory.selected.delete(photo.photo_id);drawGroups();drawResult();});individual.append(label);
        }
        details.append(individual);card.append(details);groupsArea.append(card);
      }
      if(!groups.length && loaded) groupsArea.append(make("p",photos.length?search?"No hay fotos de esta caja que coincidan con la búsqueda.":"No quedan fotos nuevas para esta caja.":"Todavía no hay fotos disponibles en la carpeta de entrada.","hint"));
      previous.disabled=busy||page===0;next.disabled=busy||page>=pages-1;navigation.hidden=pages===1;pageText.textContent="Página "+(page+1)+" de "+pages;
      const selectedGroups=allGroups.filter(group=>group.photos.some(photo=>memory.selected.has(photo.photo_id))).length;
      selectedText.textContent=memory.selected.size?selectedGroups+" grupo(s) / toma(s) · "+memory.selected.size+" foto(s) seleccionada(s) en esta tanda.":"Selecciona los grupos o fotos de esta caja. No hay imágenes preseleccionadas.";
      process.disabled=busy||!memory.selected.size||catalogue?.runtime?.available===false||options.canProcess?.()===false;
      process.textContent=issue?"Reintentar procesamiento":"Procesar fotos de esta caja";
      process.hidden=Boolean(memory.job?.status==="ready");
      clear.hidden=!memory.selected.size;selectBox.hidden=memory.selected.size>0||!offeredPhotos.length;
      clear.disabled=busy||!memory.selected.size;reload.disabled=busy;searchInput.disabled=busy;
      selectBox.disabled=busy||!offeredPhotos.length||options.canProcess?.()===false;
    }

    function drawResult() {
      result.replaceChildren();
      if(issue){result.setAttribute("data-job-state",memory.failureState||"ERROR");result.append(make("strong",memory.failureState==="TIMEOUT"?"Tiempo de espera agotado":"Error de procesamiento"),make("p",issue,"notice"));return;}
      const confirmed=!memory.job;
      const savedRecords=options.getConfirmedRecords?.()||[];
      const restored=!memory.job&&!memory.confirmedJob&&savedRecords.length>0;
      const job=memory.job||memory.confirmedJob||(restored?{status:"ready",context:getContext(),records:savedRecords}:null);
      if(!job || !sameContext(job.context,getContext()))return;
      if(job.status==="queued"||job.status==="running"){
        const progress=job.progress||{},done=progress.completed??progress.processed??0,total=progress.total??memory.selected.size;
        result.setAttribute("data-job-state",job.phase||job.status.toUpperCase());const phases={QUEUED:"En cola",LOADING_MODEL:"Cargando modelo",DETECTING:"Detectando frutos",CLASSIFYING:"Clasificando"};
        const message=(phases[job.phase]||(job.status==="queued"?"En cola":"Procesando"))+" · "+done+" / "+total+" fotos"+(progress.detected_fruits===undefined?"":" · "+progress.detected_fruits+" frutos detectados");
        result.append(make("p",message,"vision-processing"));return;
      }
      if(job.status==="failed"){result.append(make("p",job.error||"No se pudieron procesar las fotos.","notice"));return;}
      if(job.status!=="ready")return;
      result.setAttribute("data-job-state",confirmed?"COMPLETED":"REVIEW_READY");
      const context=job.context,records=job.records||[],total=records.reduce((sum,record)=>sum+record.total_fruits,0),affected=records.reduce((sum,record)=>sum+record.oleocellosis_count,0);
      const reviewed=scope.SmartFruitVisionReview?.summary(records);
      result.append(make("strong",restored?"Fotos incorporadas a la paleta":confirmed?"Fotos incorporadas a la caja":"Resultados listos para revisión"),make("p","Paleta "+context.pallet_id+" · "+total+" frutos · "+affected+" sospechas"+(reviewed?" · "+reviewed.confirmed+" confirmadas por QC":""),"vision-context"));
      drawPositiveGallery(job);
      const details=make("details");details.append(make("summary","Ver resultados generados por fotografía"));const list=make("ul",undefined,"file-list");for(const record of records)list.append(make("li",record.image_id+": "+record.oleocellosis_count+" / "+record.total_fruits+" con oleocelosis"));details.append(list);result.append(details);
      if(confirmed)return;
      const confirm=make("button",context.review_kind==="additional"?"Incorporar fotos de la segunda caja":"Incorporar fotos a la caja");confirm.type="button";confirm.disabled=busy||Boolean(reviewed?.pending);
      if(scope.SmartFruitVisionReview){const reviewHost=make("section");result.append(reviewHost);scope.SmartFruitVisionReview.render(reviewHost,records,{reviewer:options.getReviewer?.()||memory.reviewer||"",photos:job.photos||catalogue?.photos||[],onReviewer:name=>{memory.reviewer=name;options.onReviewer?.(name);},onChange:()=>{const counts=scope.SmartFruitVisionReview.summary(records);confirm.disabled=busy||counts.pending>0;}});}
      confirm.addEventListener("click",()=>run(async()=>{
        const current=getContext();const records=checkReady(memory.job,current);
        await onConfirm(records,memory.job);
        memory.confirmedJob=memory.job;memory.confirmedSelectionKey=defaultSelectionKey();
        memory.job=null;memory.selected.clear();
        options.onStatus?.(current.review_kind==="additional"?"Tanda confirmada para la caja adicional. Puedes añadir más fotos antes de finalizarla.":"Tanda confirmada para la caja de la paleta "+current.pallet_id+". Continúa con los grupos restantes antes de finalizarla.");
      }));result.append(confirm);
    }

    function drawPositiveGallery(job) {
      const photos=positivePhotos(job,catalogue?.photos||[]);
      const gallery=make("section",undefined,"vision-positive-gallery");gallery.append(make("h4","Fotos con sospechas de oleocelosis"));
      if(!photos.length){
        const affected=(job.records||[]).some(record=>record.oleocellosis_count>0);
        gallery.append(make("p",affected?"Las imágenes de los frutos clasificados no están disponibles en la carpeta actual.":"No se clasificaron frutos con oleocelosis en esta revisión.","hint"));result.append(gallery);return;
      }
      gallery.append(make("p","Selecciona una imagen para verla ampliada.","hint"));
      const grid=make("div",undefined,"vision-positive-grid");
      for(const photo of photos){
        const card=make("figure",undefined,"vision-positive-card"),open=make("button",undefined,"vision-positive-open");open.type="button";open.setAttribute("aria-label","Ampliar "+photo.name+", clasificada con oleocelosis");
        const thumbnail=make("img");thumbnail.src=photo.url;thumbnail.alt=photo.name+" · oleocelosis";thumbnail.loading="lazy";open.append(thumbnail);
        const confidence=photo.confidence===null?"":"Confianza del modelo: "+(100*photo.confidence).toLocaleString("es-PE",{maximumFractionDigits:1})+" %";
        const detection=photo.input_kind==="fruit_crop"?"Oleocelosis":photo.affected+" de "+photo.total+" frutos clasificados con oleocelosis";
        const caption=make("figcaption",undefined,"vision-positive-caption");caption.append(make("strong",photo.name),make("span",detection));if(confidence)caption.append(make("small",confidence));
        open.addEventListener("click",()=>{imageOpener=open;largeImage.src=photo.url;largeImage.alt=photo.name+" · clasificada con oleocelosis";imageTitle.textContent=photo.name;imageCaption.textContent=detection+(confidence?" · "+confidence:"");imageDialog.hidden=false;if(typeof imageDialog.showModal==="function")imageDialog.showModal();else imageDialog.setAttribute("open","");imageClose.focus?.();});
        card.append(open,caption);grid.append(card);
      }
      gallery.append(grid);result.append(gallery);
    }

    function draw() {
      if(destroyed)return;
      const photos=catalogue?.photos||[],crops=photos.filter(photo=>photo.input_kind==="fruit_crop").length;
      catalogueStatus.textContent=catalogue?(options.getTargetCount?"Fotos de demostración preparadas para esta caja.":photos.length+" fotos disponibles"+(crops?" · "+crops+" recortes de frutos. Cada recorte cuenta como un fruto.":""))+(catalogue.runtime?.available===false?" · "+(catalogue.runtime.message||"El procesamiento no está disponible."):""):loaded?"Vision integrada no disponible.":"Consultando las fotos disponibles…";
      drawGroups();drawResult();
    }
    draw();
    return {
      getPhotos(){return [...(memory.confirmedJob?.photos||[]),...(catalogue?.photos||[])];},
      refresh(){if(destroyed)return;if(!loaded&&!catalogueRequest)load();else if(!loaded&&catalogueRequest)catalogueRequest.then(()=>{loaded=true;if(!destroyed)draw();}).catch(()=>{});else draw();},
      destroy(){destroyed=true;closeImage();},
    };
  }

  const api={create,sameContext,groupPhotos,positivePhotos,checkReady,processPhotos};
  if(typeof module!=="undefined"&&module.exports)module.exports=api;
  scope.SmartFruitVisionCapture=api;
})(typeof window!=="undefined"?window:globalThis);
