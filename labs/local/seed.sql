-- shopfront seed data: 12 products (labs/CONTRACT.md §4). Idempotent through the unique SKU.
-- On a fresh database the ids are 1..12 in this order, so GET /products/1 is the mechanical keyboard.

INSERT INTO products (sku, name, price_cents, stock) VALUES
  ('KB-MECH-87',   'Mechanical keyboard, 87 keys',        8999, 120),
  ('MS-WL-PRO',    'Wireless mouse Pro',                  4999, 250),
  ('MON-27-4K',    '27-inch 4K monitor',                 42900,  35),
  ('HUB-USBC-7',   'USB-C hub, 7 ports',                  5499, 400),
  ('CAM-1080P',    '1080p webcam',                        6999,  90),
  ('HS-ANC-BT',    'Noise-cancelling headset, Bluetooth', 15900,  60),
  ('DESK-LAMP-W',  'Desk lamp, warm white',               3499, 180),
  ('CHAIR-ERGO-M', 'Ergonomic office chair, medium',     28900,  15),
  ('CAB-USBC-2M',  'USB-C cable, 2 m',                     999, 999),
  ('SSD-NVME-2TB', 'NVMe SSD, 2 TB',                     17900,  75),
  ('MAT-DESK-XL',  'Desk mat, XL',                        2499, 300),
  ('STAND-LAPTOP', 'Aluminium laptop stand',              3999, 140)
ON CONFLICT (sku) DO NOTHING;
