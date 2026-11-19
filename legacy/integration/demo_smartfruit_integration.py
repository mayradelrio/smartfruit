import json
from smartfruit_integration_v1 import (
    aggregate_vision_sample, add_qc_defects, evaluate_business_severity,
    attach_predictive, build_final_report, save_json
)

# DEMO: tres fotos reales de test tratadas como una misma muestra técnica.
vision_jsons = [
    '/mnt/data/IMG_6426.json',
    '/mnt/data/IMG_6427.json',
    '/mnt/data/IMG_6428.json',
]

sample = aggregate_vision_sample(
    vision_jsons,
    sample_id='SAMPLE_DEMO_001',
    lot_id='LOT_DEMO_001',
    pallet_id='PALLET_DEMO_01',
)

# Simulación de entrada manual del inspector desde tablet.
# Oleocelosis NO se ingresa aquí: viene automáticamente de Vision.
manual_defects = {
    'scars_pct': 2.0,
    'blanching_pct': 0.0,
    'yellow_color_pct': 0.0,
    'styler_pct': 0.0,
    'skin_breakdown_pct': 0.0,
    'mold_pct': 0.0,
    'decay_pct': 0.0,
}

record = add_qc_defects(sample, manual_defects)
record = evaluate_business_severity(record, boundary_policy='higher')
record = attach_predictive(record, enabled=False)
report = build_final_report(record)

out = '/mnt/data/demo_smartfruit_report.json'
save_json(report, out)
print(json.dumps(report, ensure_ascii=False, indent=2))
print('\nGuardado en:', out)
