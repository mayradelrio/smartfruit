/* Origen visible de los campos existentes; no define reglas de severidad. */
"use strict";
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  if (root) root.SmartFruitFieldSources = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  function missing(value) {
    return value === null || value === undefined ||
      (typeof value === "string" && value.trim() === "");
  }
  function same(first, second) {
    return !missing(first) && !missing(second) && String(first).trim() === String(second).trim();
  }
  function common(records, key) {
    if (!records.length) return undefined;
    const values = records.map(row => row && row[key]);
    if (values.some(missing)) return undefined;
    const unique = new Set(values.map(value => String(value).trim()));
    return unique.size === 1 ? values[0] : undefined;
  }
  function item(meta, value, source) {
    return {key: meta.key, label: meta.label, source,
      state: missing(value) ? "Pendiente" : "Registrado"};
  }
  function receivedSize(rows) {
    if (!rows.length) return undefined;
    const values = new Set();
    for (const row of rows) {
      const present = [row.size_declared, row.size].filter(value => !missing(value));
      if (!present.length) return undefined;
      for (const value of present) values.add(String(value).trim());
    }
    return values.size === 1 ? [...values][0] : undefined;
  }
  function describe(capture = {}, config = {}) {
    const samples = Array.isArray(capture.samples) ? capture.samples : [];
    const receiptRows = samples.flatMap(sample =>
      Array.isArray(sample.reception?.records) ? sample.reception.records : []);
    const headerValues = capture.qc_header || {};
    const header = (config.header_fields || []).map(meta => {
      const sourceKey = {lot_id: "lot_id", country_origin: "country_origin", vessel:"vessel", container:"container"}[meta.key];
      const origin = meta.key === "reason" && capture.reason_source === "defect_summary"
        && !missing(headerValues[meta.key]) ? "Resumen de defectos"
        : sourceKey && same(headerValues[meta.key], common(receiptRows, sourceKey))
          ? "Recepción" : "Inspector";
      return item(meta, headerValues[meta.key], origin);
    });
    const groups = samples.map(sample => {
      const rows = Array.isArray(sample.reception?.records) ? sample.reception.records : [];
      const fields = (config.qc_columns || []).map(meta => {
        const value = (sample.qc_fields || {})[meta.key];
        const receiptKey = {pallet_id: "pallet_id", label_brand: "label_brand",
          grower:"grower",packing_date: "packing_date", size: "size_declared",
          avg_count_per_box:"avg_count_per_box",plu_pct:"plu_pct",plu_coo:"plu_coo"}[meta.key];
        const received = meta.key === "size" ? receivedSize(rows) : common(rows, receiptKey);
        let origin = receiptKey && same(value, received) ? "Recepción" : "Inspector";
        if (meta.key === "oleocellosis" ||
            (meta.key === "sample_count" && sample.vision_covers_sample === true)) origin = "Vision";
        return item(meta, value, origin);
      });
      return {sample_id: sample.sample_id, fields};
    });
    const summaryRows = Array.isArray(capture.lot_reception?.records)
      ? capture.lot_reception.records : receiptRows;
    const summary = (config.qc_summary_fields || []).map(meta => {
      const value = (capture.qc_summary || {})[meta.key];
      const receiptKey = {label_brand: "label_brand", packing_date: "packing_date",
        plu_coo: "plu_coo"}[meta.key];
      const origin = receiptKey && same(value, common(summaryRows, receiptKey))
        ? "Recepción" : "Inspector";
      return item(meta, value, origin);
    });
    const all = [...header, ...summary, ...groups.flatMap(group => group.fields)];
    return {header, samples: groups, summary,
      pending_count: all.filter(field => field.state === "Pendiente").length,
      registered_count: all.filter(field => field.state === "Registrado").length};
  }
  return {describe};
});
