"""
Transform step - cleans raw order data and computes total_price.

Each task run currently gets a fresh container extracted straight from
the project zip - task runs don't share a persistent volume yet (see
Decision 4/Garage in plan.md) - so this reads data/raw_orders.csv if a
previous step already left it on disk, and regenerates the same data
deterministically otherwise, so it also runs standalone.
"""

from pipeline_data import generate_raw_orders, clean_orders, read_csv, write_csv

raw_orders = read_csv('data/raw_orders.csv') or generate_raw_orders()
cleaned, dropped = clean_orders(raw_orders)

write_csv('data/cleaned_orders.csv', cleaned,
          fieldnames=['order_id', 'product', 'quantity', 'unit_price', 'total_price'])

print(f"[transform] cleaned {len(cleaned)} orders, dropped {dropped} invalid rows -> data/cleaned_orders.csv")
