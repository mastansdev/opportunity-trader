"""
Appends every trade to trade_log.csv. One file, one format,
always written -- this is the record the operator checks
after every session.
"""

import csv
import io
import os
from datetime import datetime

from config import TRADE_LOG_PATH, LOG_DIR
from core.logger import warn

_FIELDS = [
    "time", "side", "symbol", "security_id", "qty", "price", "reason",
]


def _archive_if_schema_changed():
    """
    If trade_log.csv already exists with an OLDER column layout
    (e.g. from before 'reason' existed), blindly appending rows
    with the CURRENT _FIELDS would silently misalign columns --
    old rows with 6 fields, new rows with 7, no header change to
    show it happened. Instead of corrupting the file, archive the
    old one by renaming it with a timestamp and start fresh with
    the current header. Old data is kept, just not silently mixed
    with a different schema.
    """
    if not os.path.exists(TRADE_LOG_PATH):
        return

    with open(TRADE_LOG_PATH, "r", newline="", encoding="utf-8") as f:
        first_line = f.readline().strip()

    current_header = ",".join(_FIELDS)
    if first_line in ("", current_header):
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archived_path = TRADE_LOG_PATH.replace(".csv", f"_archived_{stamp}.csv")
    os.rename(TRADE_LOG_PATH, archived_path)
    warn(
        f"[TRADE_LOG] Column layout changed -- archived old log to "
        f"{archived_path}, starting a fresh trade_log.csv."
    )


def log_trade(side, symbol, security_id, qty, price, reason=""):
    os.makedirs(LOG_DIR, exist_ok=True)
    _archive_if_schema_changed()

    is_new = (
        not os.path.exists(TRADE_LOG_PATH)
        or os.path.getsize(TRADE_LOG_PATH) == 0
    )

    # #3 fix, 2026-07-24 (evening): build the COMPLETE line(s) in
    # memory first, then write them to disk in a SINGLE f.write()
    # followed by flush + fsync. The old code wrote via a DictWriter
    # bound straight to the file handle, so csv could split one row
    # across several write() calls -- a kill mid-row left a torn
    # partial line (the stray "_BREAKDOWN" seen in trade_log.csv on
    # 2026-07-24). One buffered write of a small line is atomic on
    # every mainstream OS, and fsync guarantees it's actually on
    # disk before we return.
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_FIELDS)
    if is_new:
        writer.writeheader()
    writer.writerow({
        "time": datetime.now().isoformat(timespec="seconds"),
        "side": side,
        "symbol": symbol,
        "security_id": security_id,
        "qty": qty,
        "price": price,
        "reason": reason,
    })
    line = buf.getvalue()

    with open(TRADE_LOG_PATH, "a", newline="", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())
