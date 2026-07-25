"""
Decision-correctness tests for trade_logger.py -- proves a
new log gets the current header (with 'reason'), and an
OLDER-schema file is archived rather than silently corrupted
by column misalignment.
"""

import csv
import os

import trading.trade_logger as trade_logger


def test_new_log_file_gets_current_header_with_reason(tmp_path, monkeypatch):
    log_path = os.path.join(str(tmp_path), "trade_log.csv")
    monkeypatch.setattr(trade_logger, "TRADE_LOG_PATH", log_path)
    monkeypatch.setattr(trade_logger, "LOG_DIR", str(tmp_path))

    trade_logger.log_trade("BUY", "TCS", "1", 100, 250.0, reason="STRUCTURAL_LONG_BREAKOUT")

    with open(log_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    assert rows[0]["reason"] == "STRUCTURAL_LONG_BREAKOUT"
    assert rows[0]["symbol"] == "TCS"


def test_old_schema_file_is_archived_not_corrupted(tmp_path, monkeypatch):
    log_path = os.path.join(str(tmp_path), "trade_log.csv")
    monkeypatch.setattr(trade_logger, "TRADE_LOG_PATH", log_path)
    monkeypatch.setattr(trade_logger, "LOG_DIR", str(tmp_path))

    # Simulate a pre-existing log written under the OLD 6-column
    # schema (no 'reason').
    with open(log_path, "w", newline="", encoding="utf-8") as f:
        f.write("time,side,symbol,security_id,qty,price\n")
        f.write("2026-07-23T09:31:00,BUY,TCS,1,1,250.0\n")

    trade_logger.log_trade("SELL", "TCS", "1", 100, 260.0, reason="TRAILING_STOP")

    # Old file must be renamed aside, not overwritten or appended to
    # with mismatched columns.
    archived = [
        f for f in os.listdir(str(tmp_path))
        if f.startswith("trade_log_archived_")
    ]
    assert len(archived) == 1

    with open(os.path.join(str(tmp_path), archived[0])) as f:
        assert "security_id,qty,price\n" in f.read()

    # The live path now has a fresh file with the CURRENT header only.
    with open(log_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == 1
    assert rows[0]["reason"] == "TRAILING_STOP"
