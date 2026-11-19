/* Persistencia de capturas QC incompletas; no guarda aprobación del inspector. */
(function (root, factory) {
  "use strict";
  const api = factory(root);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.SmartFruitDrafts = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function (root) {
  "use strict";

  const DATABASE = "smartfruit-inspection-drafts";
  const STORE = "active";
  const KEY = "inspection";
  const OPEN_TIMEOUT = 4000;
  const TRANSACTION_TIMEOUT = 8000;
  const approvalFields = [
    "confirmation", "final_decisions", "confirmed", "inspector_confirmed",
    "confirmed_at", "inspector_final_decision"
  ];

  function error(code, message, cause) {
    const result = new Error(message);
    result.name = "SmartFruitDraftError";
    result.code = code;
    if (cause) result.cause = cause;
    return result;
  }

  function storageError(cause) {
    if (cause && cause.name === "SmartFruitDraftError") return cause;
    if (cause && cause.name === "QuotaExceededError") {
      return error("storage_quota", "No se guardó la inspección: el navegador no tiene espacio disponible.", cause);
    }
    if (cause && cause.name === "VersionError") {
      return error("unsupported_version", "El almacenamiento de esta inspección pertenece a otra versión. No se ha modificado.", cause);
    }
    return error("storage_error", "No se pudo guardar o recuperar la inspección en este navegador. La captura almacenada no se ha sustituido.", cause);
  }

  function clone(value) {
    if (typeof root.structuredClone === "function") return root.structuredClone(value);
    // Los datos proceden de JSON y de campos de texto. Conservar incluso claves
    // especiales y undefined sin usar setters ni transformar los registros Vision.
    const seen = new Map();
    function copy(item) {
      if (item === null || typeof item !== "object") {
        if (typeof item === "function" || typeof item === "symbol") throw new TypeError("Valor no copiable");
        return item;
      }
      if (seen.has(item)) return seen.get(item);
      const result = Array.isArray(item) ? [] : {};
      seen.set(item, result);
      for (const key of Object.keys(item)) {
        Object.defineProperty(result, key, {
          value: copy(item[key]), enumerable: true, configurable: true, writable: true
        });
      }
      return result;
    }
    return copy(value);
  }

  function record(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value)
      && Object.prototype.toString.call(value) === "[object Object]";
  }

  function strings(value) {
    return record(value) && Object.values(value).every(item => typeof item === "string");
  }

  function isoDate(value) {
    return typeof value === "string"
      && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|[+-]\d{2}:\d{2})$/.test(value)
      && Number.isFinite(Date.parse(value));
  }

  function lotReception(value) {
    if (!record(value)) return false;
    const supplied = ["lot_id", "scan_input"].filter(key => value[key] !== undefined);
    return supplied.length > 0
      && supplied.every(key => typeof value[key] === "string" && value[key].trim() !== "")
      && Array.isArray(value.records)
      && value.records.every(record);
  }

  function reviewHistory(value) {
    // El backend comprueba los acumulados. El borrador conserva los originales
    // y permite recuperar la captura sin derivar cantidades ni decisiones.
    return record(value) && record(value.initial)
      && Array.isArray(value.additional) && value.additional.every(record);
  }

  function boxInspection(value) {
    return record(value) && typeof value.sample_box_id === "string" && value.sample_box_id.trim() !== ""
      && ["capturing", "completed"].includes(value.status)
      && typeof value.coverage_confirmed === "boolean"
      && (value.status !== "completed" || value.coverage_confirmed)
      && (value.manifest_record_index === null || (Number.isInteger(value.manifest_record_index) && value.manifest_record_index >= 0));
  }

  function pendingAdditional(value, sample, header) {
    const keys=["decay","styler","mold","soft","skin_breakdown","wounds","int_dryness","black_tips","skin_defect","scars","white_stain","blanching","yellow_color","stain","undersize"];
    return record(value) && Array.isArray(value.vision_records) && value.vision_records.length>0
      && value.vision_records.every(record) && boxInspection(value.box_inspection)
      && strings(value.manual_defects) && Object.keys(value.manual_defects).length===keys.length
      && keys.every(key=>typeof value.manual_defects[key]==="string")
      && typeof value.observations==="string" && strings(value.context)
      && ["lot_id","pallet_id","sample_id"].every(key=>typeof value.context[key]==="string" && value.context[key].trim()!=="")
      && typeof header.lot_id==="string"
      && value.context.lot_id===header.lot_id.trim()
      && value.context.pallet_id===sample.pallet_id.trim()
      && value.context.sample_id===sample.sample_id.trim();
  }

  function photoPools(value) {
    return record(value) && Object.entries(value).every(([key,pool]) => ["initial","additional"].includes(key)
      && record(pool) && typeof pool.context_key === "string" && pool.context_key !== ""
      && Number.isSafeInteger(pool.target_count) && pool.target_count >= 0
      && Array.isArray(pool.photo_ids) && pool.photo_ids.every(id => typeof id === "string" && id !== "")
      && new Set(pool.photo_ids).size === pool.photo_ids.length);
  }

  function validate(snapshot, checkDate) {
    if (!record(snapshot)) throw error("invalid_snapshot", "La captura guardada no tiene un formato compatible. No se ha modificado.");
    if (snapshot.version !== 1) {
      throw error("unsupported_version", "La captura guardada pertenece a otra versión. No se ha modificado.");
    }
    const validSample = sample => record(sample)
      && typeof sample.sample_id === "string"
      && typeof sample.pallet_id === "string"
      && strings(sample.qc_fields)
      && Array.isArray(sample.vision_records)
      && Array.isArray(sample.image_bindings)
      && ["", "true", "false"].includes(sample.coverage_choice)
      && typeof sample.observations === "string"
      && (sample.review_choice === undefined || ["", "STANDARD", "EXPAND", "EXTEND", "COMPLETE", "ESCALATE"].includes(sample.review_choice))
      && (sample.inspection_status === undefined || ["PENDING","SELECTED","IN_PROGRESS","COMPLETED","SKIPPED"].includes(sample.inspection_status))
      && (sample.skip_reason === undefined || typeof sample.skip_reason === "string")
      && ["selected_at","completed_at"].every(key => sample[key] == null || isoDate(sample[key]))
      && (sample.review_history === undefined || reviewHistory(sample.review_history))
      && (sample.box_inspection === undefined || boxInspection(sample.box_inspection))
      && (sample.pending_additional === undefined || pendingAdditional(sample.pending_additional,sample,snapshot.qc_header))
      && (sample.photo_pools === undefined || photoPools(sample.photo_pools))
      && (sample.reception === undefined || (record(sample.reception)
        && typeof sample.reception.scan_input === "string"
        && Array.isArray(sample.reception.records)));
    if (!strings(snapshot.qc_header)
      || (snapshot.qc_summary !== undefined && !strings(snapshot.qc_summary))
      || (snapshot.reason_source !== undefined && !["defect_summary", "inspector"].includes(snapshot.reason_source))
      || (snapshot.lot_reception !== undefined && !lotReception(snapshot.lot_reception))
      || (snapshot.workflow_step !== undefined && ![1,2,3,4].includes(snapshot.workflow_step))
      || !Array.isArray(snapshot.samples)
      || !snapshot.samples.every(validSample)
      || typeof snapshot.observations !== "string"
      || typeof snapshot.inspector_name !== "string"
      || typeof snapshot.demo_mode !== "boolean"
      || (checkDate && !isoDate(snapshot.saved_at))) {
      throw error("invalid_snapshot", "La captura guardada está incompleta o tiene un formato incompatible. No se ha modificado.");
    }
  }

  function prepare(snapshot, checkDate) {
    let result;
    try { result = clone(snapshot); }
    catch (cause) {
      throw error("invalid_snapshot", "No se pudo copiar la captura de inspección. No se ha modificado el registro guardado.", cause);
    }
    validate(result, checkDate);
    // Solo retirar la aprobación del envoltorio y de cada muestra. No descender
    // en qc_fields, reception, image_bindings, review_history ni en el JSON
    // original de Vision. review_choice es una elección de trabajo pendiente,
    // nunca una aprobación ni la decisión final confirmada.
    for (const key of approvalFields) delete result[key];
    for (const sample of result.samples) for (const key of approvalFields) {
      delete sample[key];
      if (sample.pending_additional) delete sample.pending_additional[key];
    }
    return result;
  }

  function createStore(options) {
    options = options || {};
    const indexedDB = Object.prototype.hasOwnProperty.call(options, "indexedDB")
      ? options.indexedDB : root.indexedDB;
    const databaseName = options.databaseName === undefined ? DATABASE : options.databaseName;
    let opening;
    let queue = Promise.resolve();

    function enqueue(operation) {
      // La siguiente acción se ejecuta también si falló la anterior. El Promise
      // original conserva el rechazo para el caller y para flush().
      const result = queue.then(operation, operation);
      queue = result;
      result.catch(function () {});
      return result;
    }

    function open() {
      if (!indexedDB || typeof indexedDB.open !== "function") {
        return Promise.reject(error("storage_unavailable", "Este navegador no permite guardar la inspección. Habilita su almacenamiento antes de continuar."));
      }
      if (typeof databaseName !== "string" || !databaseName) {
        return Promise.reject(error("storage_error", "El nombre del almacenamiento de inspecciones no es válido."));
      }
      if (opening) return opening;
      const attempt = new Promise((resolve, reject) => {
        let request;
        let settled = false;
        const timer = root.setTimeout(() => {
          finish(error("storage_timeout", "El navegador no respondió al abrir la inspección guardada. Cierra otras pestañas de SmartFruit y vuelve a intentar."));
        }, OPEN_TIMEOUT);

        function finish(cause, database) {
          if (settled) return;
          settled = true;
          root.clearTimeout(timer);
          if (cause) reject(cause);
          else resolve(database);
        }

        try { request = indexedDB.open(databaseName, 1); }
        catch (cause) { finish(storageError(cause)); return; }
        request.onblocked = () => finish(error("storage_blocked", "Otra pestaña bloquea la inspección guardada. Ciérrala y vuelve a intentar; no se ha borrado la captura."));
        request.onerror = () => finish(storageError(request.error));
        request.onupgradeneeded = () => {
          if (settled) {
            try { request.transaction.abort(); } catch (_) {}
            return;
          }
          try {
            if (!request.result.objectStoreNames.contains(STORE)) request.result.createObjectStore(STORE);
          } catch (cause) {
            try { request.transaction.abort(); } catch (_) {}
            finish(storageError(cause));
          }
        };
        request.onsuccess = () => {
          const database = request.result;
          if (settled) { database.close(); return; }
          if (!database.objectStoreNames.contains(STORE)) {
            database.close();
            finish(error("invalid_snapshot", "El almacenamiento guardado tiene un formato incompatible. No se ha modificado."));
            return;
          }
          database.onversionchange = () => {
            database.close();
            if (opening === attempt) opening = undefined;
          };
          finish(null, database);
        };
      });
      opening = attempt;
      attempt.catch(() => { if (opening === attempt) opening = undefined; });
      return attempt;
    }

    async function transaction(mode, work) {
      const database = await open();
      return new Promise((resolve, reject) => {
        let tx;
        let value;
        let failure;
        let settled = false;
        let timer;
        function finish(cause) {
          if (settled) return;
          settled = true;
          if (timer !== undefined) root.clearTimeout(timer);
          if (cause) reject(storageError(cause));
          else resolve(value);
        }
        function abort(cause) {
          failure = cause;
          try { tx.abort(); } catch (_) { finish(cause); }
        }
        try { tx = database.transaction(STORE, mode); }
        catch (cause) { finish(cause); return; }
        timer = root.setTimeout(() => {
          abort(error("storage_timeout", "El navegador no terminó de guardar la inspección. El guardado no se ha confirmado."));
          finish(failure);
        }, TRANSACTION_TIMEOUT);
        tx.oncomplete = () => finish(failure);
        tx.onerror = event => finish(failure || tx.error || (event.target && event.target.error));
        tx.onabort = () => finish(failure || tx.error || error("storage_error", "El navegador canceló el guardado de la inspección. No se ha confirmado el guardado."));
        try { work(tx.objectStore(STORE), next => { value = next; }, abort); }
        catch (cause) { abort(cause); }
      });
    }

    return {
      load() {
        return enqueue(() => transaction("readonly", (store, result, abort) => {
          const request = store.get(KEY);
          request.onsuccess = () => {
            if (request.result === undefined) { result(null); return; }
            try { result(prepare(request.result, true)); }
            catch (cause) { abort(cause); }
          };
        }));
      },
      save(snapshot) {
        // Capturar en el momento de la llamada, no cuando le toque a la cola.
        let copy;
        let failure;
        try { copy = prepare(snapshot, false); } catch (cause) { failure = cause; }
        return enqueue(() => {
          if (failure) throw failure;
          return transaction("readwrite", (store, result, abort) => {
            const current = store.get(KEY);
            current.onsuccess = () => {
              try {
                // El chequeo y el put comparten transacción: otra pestaña no
                // puede intercalar un borrador incompatible entre ambos.
                if (current.result !== undefined) validate(current.result, true);
                copy.saved_at = new Date().toISOString();
                const put = store.put(copy, KEY);
                put.onsuccess = () => { result(clone(copy)); };
              } catch (cause) { abort(cause); }
            };
          });
        });
      },
      clear() {
        // Descarte EXPLÍCITO del caller (p. ej. Nueva inspección confirmada).
        // Nunca se llama automáticamente por load/versiones incompatibles.
        return enqueue(() => transaction("readwrite", store => { store.delete(KEY); }));
      },
      flush() {
        return queue.then(() => undefined);
      }
    };
  }

  return {createStore};
});
