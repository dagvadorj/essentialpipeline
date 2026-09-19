"""
Extract step - simulates pulling raw order data from a source system.

Writes data/raw_orders.csv, including a few invalid rows (zero/negative
quantity or price) on purpose, for the transform step to filter out.
"""

from pipeline_data import generate_raw_orders, write_csv

orders = generate_raw_orders()
write_csv('data/raw_orders.csv', orders, fieldnames=['order_id', 'product', 'quantity', 'unit_price'])

print(f"[extract] wrote {len(orders)} raw orders to data/raw_orders.csv")
