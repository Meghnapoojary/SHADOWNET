"""Generate deterministic fictional multi-institution transactions for SHADOWNET."""
from __future__ import annotations
import csv
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "synthetic_transactions.csv"
FIELDS = ["transaction_id", "case_id", "bank", "timestamp", "source_account", "target_account", "amount", "channel", "device_id", "ip_hash"]
rows = []

BANKS = [
    "Northstar Cooperative", "Meridian Retail Bank", "Crescent Finance", "Harbor Trust", 
    "Pioneer Digital Bank", "Summit Commercial", "Evergreen Payments", "Lighthouse Credit", "Atlas Community Bank"
]

# Repeated, timestamp-relative flow template: three disconnected cases are intentionally
# structurally/behaviourally alike while all account IDs remain distinct.
FINGERPRINT_TEMPLATE = [
    ("A", "B", 1100.0, 0, 9, 10, "UPI"),
    ("A", "C", 900.0, 0, 9, 20, "UPI"),
    ("B", "D", 1050.0, 0, 10, 0, "IMPS"),
    ("C", "D", 850.0, 0, 10, 10, "IMPS"),
    ("D", "E", 1800.0, 0, 11, 0, "NEFT"),
    ("E", "F", 900.0, 0, 12, 15, "UPI"),
    ("E", "G", 900.0, 0, 12, 20, "UPI"),
    ("F", "H", 890.0, 0, 13, 5, "IMPS"),
]

def add_case(case_id: str, bank: str, prefix: str, start: datetime, transfers: list[tuple], extra: list[tuple] | None = None):
    for idx, item in enumerate(transfers + (extra or []), 1):
        src, dst, amount, day, hour, minute, channel = item
        stamp = start + timedelta(days=day)
        stamp = stamp.replace(hour=hour, minute=minute, second=0, microsecond=0)
        rows.append({
            "transaction_id": f"TX-{case_id}-{idx:03d}",
            "case_id": case_id,
            "bank": bank,
            "timestamp": stamp.isoformat(),
            "source_account": src if src.startswith("X-SHARED-") else f"{prefix}-{src}",
            "target_account": dst if dst.startswith("X-SHARED-") else f"{prefix}-{dst}",
            "amount": f"{amount:.2f}",
            "channel": channel,
            "device_id": f"DEV-{prefix}-{(idx % 3) + 1}",
            "ip_hash": f"IP-{prefix}-{(idx % 4) + 1}",
        })

# Direct-link pair 1: same canonical identifier occurs across two separate case records.
base1 = [
    ("S1", "M1", 4200, 0, 8, 15, "NEFT"), ("S1", "M2", 1800, 0, 8, 40, "NEFT"),
    ("M1", "X-SHARED-ALPHA", 3900, 0, 10, 5, "IMPS"), ("M2", "M3", 1650, 1, 14, 10, "UPI"),
    ("X-SHARED-ALPHA", "R1", 2500, 1, 16, 20, "NEFT"), ("R1", "R2", 2380, 2, 9, 35, "IMPS"),
    ("S2", "R3", 7600, 3, 11, 0, "RTGS"), ("R2", "R4", 2290, 4, 18, 45, "UPI"),
]
base2 = [
    ("U1", "U2", 9600, 0, 21, 5, "RTGS"), ("U2", "X-SHARED-ALPHA", 9400, 1, 2, 15, "NEFT"),
    ("U3", "U4", 310, 1, 7, 50, "UPI"), ("U4", "U5", 295, 3, 19, 10, "IMPS"),
    ("U5", "U6", 280, 3, 23, 55, "UPI"), ("U7", "U8", 12500, 5, 12, 30, "RTGS"),
    ("X-SHARED-ALPHA", "U9", 8800, 6, 6, 5, "NEFT"), ("U9", "U10", 8200, 8, 17, 40, "IMPS"),
]
add_case("CASE-101", BANKS[0], "NORTH", datetime(2026, 9, 1), base1)
add_case("CASE-102", BANKS[1], "MERID", datetime(2026, 9, 8), base2)

# Direct-link pair 2: a separate shared canonical identifier, unrelated to pair 1.
base3 = [
    ("P1", "P2", 15000, 0, 10, 0, "RTGS"), ("P2", "P3", 14800, 0, 10, 5, "RTGS"),
    ("P3", "X-SHARED-BETA", 14600, 0, 10, 10, "NEFT"), ("P4", "P5", 2200, 1, 15, 30, "UPI"),
    ("P5", "P6", 2150, 1, 16, 5, "UPI"), ("X-SHARED-BETA", "P7", 14100, 2, 9, 25, "NEFT"),
    ("P7", "P8", 13800, 4, 13, 15, "IMPS"), ("P8", "P9", 13500, 6, 20, 45, "NEFT"),
]
base4 = [
    ("Q1", "Q2", 550, 0, 6, 0, "UPI"), ("Q2", "Q3", 525, 0, 6, 2, "UPI"),
    ("Q3", "X-SHARED-BETA", 500, 0, 6, 6, "IMPS"), ("Q4", "Q5", 4700, 2, 22, 40, "NEFT"),
    ("Q5", "Q6", 4550, 5, 3, 5, "RTGS"), ("X-SHARED-BETA", "Q7", 480, 6, 9, 0, "UPI"),
    ("Q8", "Q9", 125, 8, 18, 20, "UPI"), ("Q9", "Q10", 110, 10, 23, 10, "UPI"),
]
add_case("CASE-103", BANKS[2], "CRES", datetime(2026, 9, 2), base3)
add_case("CASE-104", BANKS[3], "HARB", datetime(2026, 9, 3), base4)

# Three disconnected cases with the same behavioural fingerprint but disjoint account IDs.
for case_id, bank, prefix, day in [
    ("CASE-201", BANKS[4], "PIONEER", 5),
    ("CASE-202", BANKS[5], "SUMMIT", 12),
    ("CASE-203", BANKS[6], "EVERGR", 19),
]:
    add_case(case_id, bank, prefix, datetime(2026, 10, day), FINGERPRINT_TEMPLATE)

# Benign look-alike pair: similar multi-hop/splitting concept, but distinct timings,
# amount structure and graph shape. They must NOT clear the high-match threshold.
benign_a = [
    ("L1", "L2", 1300, 0, 9, 0, "UPI"), ("L1", "L3", 700, 0, 9, 30, "UPI"),
    ("L2", "L4", 1250, 0, 15, 0, "IMPS"), ("L3", "L5", 680, 1, 8, 0, "UPI"),
    ("L4", "L6", 1100, 3, 12, 0, "NEFT"), ("L5", "L6", 600, 4, 17, 0, "NEFT"),
    ("L6", "L7", 1600, 6, 10, 0, "RTGS"), ("L7", "L8", 1500, 9, 14, 0, "IMPS"),
    ("L8", "L9", 1450, 11, 11, 0, "IMPS"),
]
benign_b = [
    ("M1", "M2", 12500, 0, 1, 10, "RTGS"), ("M2", "M3", 120, 2, 23, 45, "UPI"),
    ("M3", "M4", 8450, 2, 23, 52, "IMPS"), ("M4", "M5", 250, 7, 4, 15, "UPI"),
    ("M5", "M6", 18700, 12, 18, 30, "NEFT"), ("M6", "M7", 670, 13, 2, 5, "UPI"),
    ("M7", "M8", 9500, 21, 11, 40, "RTGS"), ("M8", "M9", 95, 27, 22, 55, "UPI"),
    ("M9", "M10", 3100, 29, 6, 20, "IMPS"),
]
add_case("CASE-301", BANKS[7], "LIGHT", datetime(2026, 10, 5), benign_a)
add_case("CASE-302", BANKS[8], "ATLAS", datetime(2026, 10, 12), benign_b)

with OUT.open("w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=FIELDS)
    writer.writeheader()
    writer.writerows(rows)
print(f"Wrote {len(rows)} transactions across {len(set(r['case_id'] for r in rows))} cases to {OUT}")
