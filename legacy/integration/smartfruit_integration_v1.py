from pathlib import Path
import json

BUSINESS_DEFECT_MAP = {
    'scars_pct': {'business_name': 'Cicatrices / defectos de piel', 'group': 'quality', 'rule': 'quality_5_20'},
    'blanching_pct': {'business_name': 'Blanqueamiento / decoloración', 'group': 'quality', 'rule': 'quality_5_20'},
    'yellow_color_pct': {'business_name': 'Color amarillo / sobremaduro', 'group': 'quality', 'rule': 'quality_5_20'},
    'oleocellosis_pct': {'business_name': 'Oleocelosis', 'group': 'condition', 'rule': 'condition_5_10'},
    'styler_pct': {'business_name': 'Styler (limes)', 'group': 'condition', 'rule': 'condition_5_10'},
    'skin_breakdown_pct': {'business_name': 'Skin Breakdown / Fumigation Damage', 'group': 'condition', 'rule': 'skin_breakdown_0_5'},
    'mold_pct': {'business_name': 'Moho', 'group': 'condition', 'rule': 'mold_decay_0_1'},
    'decay_pct': {'business_name': 'Pudrición', 'group': 'condition', 'rule': 'mold_decay_0_1'},
}


def load_vision_json(path):
    path = Path(path)
    with path.open('r', encoding='utf-8') as f:
        data = json.load(f)
    required = {'image_id','total_fruits','oleocellosis_count','oleocellosis_pct','fruit_predictions'}
    missing = required - set(data)
    if missing:
        raise ValueError(f'{path.name}: faltan campos {sorted(missing)}')
    return data


def validate_vision_record(data):
    total = int(data['total_fruits'])
    count = int(data['oleocellosis_count'])
    preds = data['fruit_predictions']
    if len(preds) != total:
        raise ValueError(f"{data['image_id']}: total_fruits={total}, fruit_predictions={len(preds)}")
    calc = 0.0 if total == 0 else 100.0 * count / total
    if abs(calc - float(data['oleocellosis_pct'])) > 0.02:
        raise ValueError(f"{data['image_id']}: oleocellosis_pct inconsistente")


def aggregate_vision_sample(json_paths, sample_id, lot_id=None, pallet_id=None, low_confidence_threshold=0.70):
    records, seen, duplicates = [], set(), []
    for path in json_paths:
        data = load_vision_json(path)
        validate_vision_record(data)
        image_id = data['image_id']
        if image_id in seen:
            duplicates.append(image_id)
            continue
        seen.add(image_id)
        records.append(data)
    if not records:
        raise ValueError('No hay JSON válidos para agregar.')

    total = sum(int(r['total_fruits']) for r in records)
    oleo = sum(int(r['oleocellosis_count']) for r in records)
    pct = 0.0 if total == 0 else 100.0 * oleo / total

    confidences, low = [], []
    for r in records:
        for p in r['fruit_predictions']:
            c = float(p.get('confidence', 0.0))
            confidences.append(c)
            if c < low_confidence_threshold:
                low.append({
                    'image_id': r['image_id'],
                    'crop_id': p.get('crop_id'),
                    'predicted_class': p.get('predicted_class'),
                    'confidence': c,
                    'oleocellosis_probability': p.get('oleocellosis_probability')
                })

    return {
        'schema_version': '1.0',
        'sample_id': sample_id,
        'lot_id': lot_id,
        'pallet_id': pallet_id,
        'vision_summary': {
            'images_processed': len(records),
            'image_ids': [r['image_id'] for r in records],
            'total_fruits': total,
            'oleocellosis_count': oleo,
            'oleocellosis_pct': round(pct, 4),
            'mean_confidence': round(sum(confidences)/len(confidences), 6) if confidences else None,
            'low_confidence_threshold': low_confidence_threshold,
            'low_confidence_count': len(low),
            'low_confidence_items': low,
            'duplicate_image_ids_ignored': duplicates,
        }
    }


def _boundary_compare(value, threshold, boundary_policy):
    if boundary_policy == 'higher':
        return value >= threshold
    if boundary_policy == 'lower':
        return value > threshold
    raise ValueError("boundary_policy debe ser 'higher' o 'lower'")


def business_level(value, rule, boundary_policy='higher'):
    x = float(value)
    if x < 0:
        raise ValueError('Porcentaje de defecto no puede ser negativo')

    if rule == 'quality_5_20':
        if _boundary_compare(x, 20.0, boundary_policy): return 3
        if _boundary_compare(x, 5.0, boundary_policy): return 2
        return 1
    if rule == 'condition_5_10':
        if _boundary_compare(x, 10.0, boundary_policy): return 3
        if _boundary_compare(x, 5.0, boundary_policy): return 2
        return 1
    if rule == 'skin_breakdown_0_5':
        if _boundary_compare(x, 5.0, boundary_policy): return 3
        if x > 0: return 2
        return 1
    if rule == 'mold_decay_0_1':
        if _boundary_compare(x, 1.0, boundary_policy): return 3
        if x > 0: return 2
        return 1
    raise ValueError(f'Regla no reconocida: {rule}')


def add_qc_defects(sample_summary, manual_defects=None):
    manual_defects = manual_defects or {}
    values = {
        'oleocellosis_pct': sample_summary['vision_summary']['oleocellosis_pct'],
        'scars_pct': 0.0,
        'blanching_pct': 0.0,
        'yellow_color_pct': 0.0,
        'styler_pct': 0.0,
        'skin_breakdown_pct': 0.0,
        'mold_pct': 0.0,
        'decay_pct': 0.0,
    }
    values.update({k: float(v) for k,v in manual_defects.items() if k in values and k != 'oleocellosis_pct'})

    defects = {}
    for col, meta in BUSINESS_DEFECT_MAP.items():
        defects[col] = {
            'business_name': meta['business_name'],
            'group': meta['group'],
            'source': 'vision_ai' if col == 'oleocellosis_pct' else 'qc_manual',
            'pct': float(values[col]),
        }
    out = dict(sample_summary)
    out['defects'] = defects
    return out


def evaluate_business_severity(record, boundary_policy='higher'):
    defects_out = {}
    quality_levels, condition_levels = [], []

    for col, meta in BUSINESS_DEFECT_MAP.items():
        pct = record['defects'][col]['pct']
        level = business_level(pct, meta['rule'], boundary_policy)
        d = dict(record['defects'][col])
        d['business_level'] = level
        defects_out[col] = d
        (quality_levels if meta['group']=='quality' else condition_levels).append(level)

    all_levels = quality_levels + condition_levels
    max_level = max(all_levels) if all_levels else 1

    # Regla operativa MVP: Level 1=STANDARD, Level 2=EXPAND, Level 3=ESCALATE.
    # Inspector conserva la decisión final.
    decision = {1:'STANDARD', 2:'EXPAND', 3:'ESCALATE'}[max_level]

    reasons = [
        d['business_name'] for d in defects_out.values()
        if d['business_level'] == max_level and max_level > 1
    ]

    out = dict(record)
    out['defects'] = defects_out
    out['business_severity'] = {
        'boundary_policy': boundary_policy,
        'quality_max_level': max(quality_levels) if quality_levels else 1,
        'condition_max_level': max(condition_levels) if condition_levels else 1,
        'business_max_level': max_level,
        'recommendation': decision,
        'reasons': reasons,
    }
    return out


def attach_predictive(record, enabled=False, predicted_loss_pct=None):
    out = dict(record)
    out['predictive'] = {
        'enabled': bool(enabled),
        'experimental': True,
        'predicted_loss_pct': float(predicted_loss_pct) if enabled and predicted_loss_pct is not None else None,
        'decision': None,
    }
    return out


def build_final_report(record):
    sev = record['business_severity']
    return {
        'schema_version': record.get('schema_version', '1.0'),
        'lot_id': record.get('lot_id'),
        'pallet_id': record.get('pallet_id'),
        'sample_id': record.get('sample_id'),
        'inspection_summary': record['vision_summary'],
        'defects': record['defects'],
        'business_severity': sev,
        'predictive': record.get('predictive'),
        'final_recommendation': sev['recommendation'],
        'recommendation_reasons': sev['reasons'],
        'human_confirmation_required': True,
        'inspector_final_decision': None,
    }


def save_json(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
