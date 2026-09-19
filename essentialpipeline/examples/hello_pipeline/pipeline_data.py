"""
Shared helpers for the sample ETL pipeline (extract.py/transform.py/load.py).

Demonstrates that a project can have shared library code alongside its
task entry scripts, not just standalone scripts.
"""

import csv
import os
import random

PRODUCTS = ["Widget", "Gadget", "Gizmo", "Doohickey", "Thingamajig"]


def generate_raw_orders(n=20, seed=42):
    """Deterministic synthetic 'raw' order data, standing in for a real source system."""
    rng = random.Random(seed)
    return [
        {
            'order_id': i,
            'product': rng.choice(PRODUCTS),
            'quantity': rng.choice([-1, 0, 1, 2, 3, 5, 8]),  # a few bad rows on purpose
            'unit_price': round(rng.uniform(5, 50), 2),
        }
        for i in range(1, n + 1)
    ]


def clean_orders(raw_orders):
    """Drop invalid rows and compute total_price. Returns (cleaned, dropped_count)."""
    cleaned = []
    dropped = 0
    for row in raw_orders:
        quantity = int(row['quantity'])
        unit_price = float(row['unit_price'])
        if quantity <= 0 or unit_price <= 0:
            dropped += 1
            continue
        cleaned.append({
            'order_id': row['order_id'],
            'product': row['product'],
            'quantity': quantity,
            'unit_price': unit_price,
            'total_price': round(quantity * unit_price, 2),
        })
    return cleaned, dropped


def read_csv(path):
    """Read a CSV back into a list of dicts, or None if it doesn't exist yet"""
    if not os.path.exists(path):
        return None
    with open(path, newline='') as f:
        return list(csv.DictReader(f))


def write_csv(path, rows, fieldnames):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
