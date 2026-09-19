"""
Load step - aggregates cleaned order data into a small revenue report.

Same standalone fallback as transform.py: reads data/cleaned_orders.csv
if present, otherwise reproduces it from raw data so this also runs on
its own.
"""

import json
import os
from collections import defaultdict
from pipeline_data import generate_raw_orders, clean_orders, read_csv

cleaned = read_csv('data/cleaned_orders.csv')
if cleaned:
    for row in cleaned:
        row['quantity'] = int(row['quantity'])
        row['unit_price'] = float(row['unit_price'])
        row['total_price'] = float(row['total_price'])
else:
    cleaned, _ = clean_orders(generate_raw_orders())

revenue_by_product = defaultdict(float)
for row in cleaned:
    revenue_by_product[row['product']] += row['total_price']

report = {
    'order_count': len(cleaned),
    'total_revenue': round(sum(revenue_by_product.values()), 2),
    'revenue_by_product': {k: round(v, 2) for k, v in revenue_by_product.items()},
    'top_product': max(revenue_by_product, key=revenue_by_product.get) if revenue_by_product else None,
}

os.makedirs('data', exist_ok=True)
with open('data/report.json', 'w') as f:
    json.dump(report, f, indent=2)

print(f"[load] {report['order_count']} orders, ${report['total_revenue']} total revenue, top product: {report['top_product']}")
print(json.dumps(report, indent=2))
