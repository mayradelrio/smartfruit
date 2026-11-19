/* Transporte local para la interfaz QC existente. Los cálculos siguen en Python. */
"use strict";
(() => {
  const nativeFetch = window.fetch.bind(window);
  const databaseName = "smartfruit-qc-reports";
  const xlsxType = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
  const reportRoute = /^\/api\/reports\/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\/(xlsx|json|print)$/;
  let databasePromise;
  let dispatcher;
  let pythonQueue = Promise.resolve();

  function loading(message) {
    const target = document.getElementById("loading");
    if (target) target.textContent = message;
  }

  function fail(message) {
    const target = document.getElementById("app-error");
    if (target) {
      target.textContent = message;
      target.hidden = false;
      target.scrollIntoView({block:"center", behavior:"smooth"});
    }
  }

  function jsonResponse(body, status = 200) {
    return new Response(JSON.stringify(body), {
      status,
      headers: {"Content-Type":"application/json; charset=utf-8"}
    });
  }

  function bytesFromBase64(value) {
    const text = atob(value);
    const bytes = new Uint8Array(text.length);
    for (let i = 0; i < text.length; i++) bytes[i] = text.charCodeAt(i);
    return bytes;
  }

  function openDatabase() {
    if (!window.indexedDB) {
      return Promise.reject(new Error("Este navegador no permite guardar reportes. Usa un navegador con almacenamiento habilitado y descarga tus copias."));
    }
    if (!databasePromise) {
      databasePromise = new Promise((resolve, reject) => {
        const request = indexedDB.open(databaseName, 1);
        request.onupgradeneeded = () => {
          const db = request.result;
          if (!db.objectStoreNames.contains("reports")) db.createObjectStore("reports", {keyPath:"id"});
        };
        request.onerror = () => reject(new Error("No se pudo abrir el almacenamiento de reportes de este navegador."));
        request.onblocked = () => reject(new Error("Cierra otras pestañas de SmartFruit y vuelve a intentar guardar."));
        request.onsuccess = () => {
          const db = request.result;
          db.onversionchange = () => { db.close(); databasePromise = undefined; };
          resolve(db);
        };
      }).catch(error => { databasePromise = undefined; throw error; });
    }
    return databasePromise;
  }

  async function storeReport(record) {
    const db = await openDatabase();
    return new Promise((resolve, reject) => {
      const transaction = db.transaction("reports", "readwrite");
      transaction.oncomplete = () => resolve();
      transaction.onabort = transaction.onerror = () => reject(new Error(
        "No se guardó el reporte. El navegador puede estar sin espacio o tener el almacenamiento bloqueado. La inspección sigue abierta."
      ));
      transaction.objectStore("reports").add(record);
    });
  }

  async function getReport(id) {
    const db = await openDatabase();
    return new Promise((resolve, reject) => {
      const transaction = db.transaction("reports", "readonly");
      const request = transaction.objectStore("reports").get(id);
      request.onsuccess = () => resolve(request.result || null);
      request.onerror = transaction.onabort = () => reject(new Error("No se pudo leer el reporte guardado en este navegador."));
    });
  }

  async function getReports() {
    const db = await openDatabase();
    return new Promise((resolve, reject) => {
      const transaction = db.transaction("reports", "readonly");
      const request = transaction.objectStore("reports").getAll();
      request.onsuccess = () => resolve(request.result);
      request.onerror = transaction.onabort = () => reject(new Error("No se pudieron leer los reportes guardados."));
    });
  }

  async function downloadResponse(path) {
    const match = path.match(reportRoute);
    if (!match) return jsonResponse({detail:"Reporte no encontrado."},404);
    const record = await getReport(match[1]);
    if (!record) return jsonResponse({detail:"Este reporte no está guardado en este navegador."},404);
    const kind = match[2];
    if(kind === "print"){
      const envelope = await runPython("POST","/api/report/print-saved",JSON.stringify({report:record.report}),"");
      return new Response(envelope.body,{status:envelope.status,headers:{"Content-Type":envelope.content_type}});
    }
    return new Response(
      kind === "xlsx" ? record.xlsx : JSON.stringify(record.report,null,2),
      {status:200, headers:{
        "Content-Type": kind === "xlsx" ? xlsxType : "application/json; charset=utf-8",
        "Content-Disposition": `attachment; filename="smartfruit_qc_${record.id}.${kind}"`
      }}
    );
  }

  function loadRuntimeScript() {
    return new Promise((resolve,reject) => {
      if (typeof window.loadPyodide === "function") { resolve(); return; }
      const script=document.createElement("script");
      script.src="/runtime/pyodide.js";
      script.onload=resolve;
      script.onerror=()=>reject(new Error("No se pudo cargar SmartFruit. Comprueba tu conexión y recarga esta página."));
      document.head.append(script);
    });
  }

  async function checkedFetch(path) {
    const response=await nativeFetch(path);
    if(!response.ok)throw new Error("No se pudo cargar un componente de SmartFruit. Recarga la página para intentar de nuevo.");
    return response;
  }

  async function boot() {
    loading("Preparando SmartFruit para este navegador… La primera carga puede tardar unos segundos.");
    await loadRuntimeScript();
    const py=await window.loadPyodide({indexURL:"/runtime/",stdout:()=>{},stderr:()=>{}});
    loading("Preparando el formato QC y las reglas existentes…");
    await py.loadPackage("pillow");
    const bundle=await (await checkedFetch("/python/smartfruit_bundle.zip")).arrayBuffer();
    py.unpackArchive(bundle,"zip",{extractDir:"/app"});
    py.runPython("import sys, os, zoneinfo\nsys.path.insert(0, '/app')\nzoneinfo.reset_tzpath(['/app/zoneinfo'])\nos.environ['USE_PREDICTIVE'] = 'False'\n");
    const source=await (await checkedFetch("/python/browser_api.py")).text();
    py.runPython(source);
    dispatcher=py.globals.get("smartfruit_browser_api");
    return py;
  }

  // La UI existente puede llamar /api/config inmediatamente; esperará a Python.
  const ready=boot();
  ready.catch(error => {
    loading("No se pudo preparar SmartFruit.");
    fail(error.message || "No se pudo preparar SmartFruit. Recarga la página.");
  });

  async function runPython(method,path,body,reportId) {
    await ready;
    const result=pythonQueue.then(() => JSON.parse(dispatcher(method,path,body,reportId)));
    pythonQueue=result.catch(()=>{});
    return result;
  }

  async function apiFetch(path,method,body) {
    if(path==="/api/report/print-saved")return jsonResponse({detail:"Ruta interna del historial."},404);
    if(path.startsWith("/api/reports/")){
      if(method!=="GET")return jsonResponse({detail:"Método no permitido."},405);
      return downloadResponse(path);
    }
    const id=path==="/api/finalize"?crypto.randomUUID():"";
    const envelope=await runPython(method,path,body,id);
    if(envelope.storage){
      // Persistir los tres componentes en UNA transacción antes de confirmar éxito.
      const source=envelope.storage;
      await storeReport({
        id:source.id,
        report:source.report,
        source:source.source,
        xlsx:bytesFromBase64(source.xlsx_base64)
      });
      refreshHistory().catch(()=>{});
    }
    return new Response(
      envelope.encoding==="base64"?bytesFromBase64(envelope.body):envelope.content_type.startsWith("text/html")?envelope.body:JSON.stringify(envelope.body),
      {status:envelope.status,headers:{"Content-Type":envelope.content_type}}
    );
  }

  window.fetch=async function(input,init){
    let target;
    try{target=new URL(typeof input==="string"||input instanceof URL?input:input.url,window.location.href);}
    catch(_){return nativeFetch(input,init);}
    if(target.origin!==window.location.origin||!target.pathname.startsWith("/api/"))return nativeFetch(input,init);
    const method=String(init?.method||(input instanceof Request?input.method:"GET")).toUpperCase();
    let body=init?.body;
    if(body===undefined&&input instanceof Request)body=await input.clone().text();
    if(body===undefined||body===null)body="";
    if(typeof body!=="string")return jsonResponse({detail:"El cuerpo debe ser JSON válido."},422);
    try{return await apiFetch(target.pathname,method,body);}
    catch(error){return jsonResponse({detail:error.message||"No se pudo completar la operación en este navegador."},503);}
  };

  // Los links nativos no pasan por fetch: resolverlos localmente sin subir el QC.
  document.addEventListener("click",async event=>{
    const anchor=event.target instanceof Element?event.target.closest("a[href]"):null;
    if(!anchor)return;
    const target=new URL(anchor.href,window.location.href);
    if(target.origin!==window.location.origin||!reportRoute.test(target.pathname))return;
    event.preventDefault();
    const printable=target.pathname.endsWith("/print");
    const tab=printable?window.open("about:blank","_blank"):null;
    try{
      const response=await downloadResponse(target.pathname);
      if(!response.ok)throw new Error((await response.json()).detail);
      const blob=await response.blob();
      const url=URL.createObjectURL(blob);
      if(printable){if(tab){tab.opener=null;tab.location.href=url;}else{const link=document.createElement("a");link.href=url;link.download="smartfruit_qc_imprimible.html";link.click();}setTimeout(()=>URL.revokeObjectURL(url),60000);return;}
      const link=document.createElement("a");
      const match=target.pathname.match(reportRoute);
      link.href=url;link.download=`smartfruit_qc_${match[1]}.${match[2]}`;
      document.body.append(link);link.click();link.remove();
      setTimeout(()=>URL.revokeObjectURL(url),1000);
    }catch(error){if(tab)tab.close();fail(error.message||"No se pudo descargar el reporte.");}
  },true);

  function addStorageNotice(){
    const main=document.querySelector("main");
    const heading=document.querySelector(".page-heading");
    if(!main||!heading)return;
    const note=document.createElement("p");
    note.className="hint";
    note.textContent="Los reportes se guardan en este navegador. Descarga Excel y JSON para conservar una copia; borrar los datos del navegador elimina el registro local.";
    heading.insertAdjacentElement("afterend",note);
    const history=document.createElement("details");
    history.className="rule-note";history.id="browser-report-history";
    const title=document.createElement("summary");title.textContent="Reportes guardados en este navegador";
    const list=document.createElement("div");list.id="browser-report-list";
    history.append(title,list);note.insertAdjacentElement("afterend",history);
    refreshHistory().catch(error=>{list.textContent=error.message;});
  }

  async function refreshHistory(){
    const target=document.getElementById("browser-report-list");
    if(!target)return;
    const reports=await getReports();
    reports.sort((a,b)=>String(b.report.confirmed_at).localeCompare(String(a.report.confirmed_at)));
    target.replaceChildren();
    if(!reports.length){target.textContent="Aún no hay reportes confirmados en este navegador.";return;}
    for(const item of reports){
      const line=document.createElement("p");
      const date=new Intl.DateTimeFormat("es-PE",{timeZone:"America/Lima",dateStyle:"short",timeStyle:"short"}).format(new Date(item.report.confirmed_at));
      line.append(document.createTextNode(`${item.report.lot_id} · ${date} · `));
      for(const [kind,label]of [["xlsx","Excel"],["json","JSON"],["print","Ver / imprimir PDF"]]){
        const link=document.createElement("a");link.href=`/api/reports/${item.id}/${kind}`;link.download="";link.textContent=label;
        line.append(link,document.createTextNode(" "));
      }
      target.append(line);
    }
  }

  if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",addStorageNotice,{once:true});
  else addStorageNotice();
})();
