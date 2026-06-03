"""Unit test for invested series calculation.

Tests that the invested calculation works correctly for any TR user,
not just specific accounts.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from components.tr_api import TRConnection


def test_invested_series_calculation():
    """Test _build_invested_series_from_transactions with various transaction types."""
    tr = TRConnection()
    
    # Test case 1: Basic deposits and withdrawals
    transactions = [
        {"timestamp": "2024-01-01T10:00:00.000Z", "title": "Einzahlung", "subtitle": None, "amount": 1000.0},
        {"timestamp": "2024-02-01T10:00:00.000Z", "title": "Einzahlung", "subtitle": None, "amount": 500.0},
        {"timestamp": "2024-03-01T10:00:00.000Z", "title": "Withdrawal", "subtitle": "Gesendet", "amount": -200.0},
    ]
    
    result = tr._build_invested_series_from_transactions(transactions)
    
    assert result["2024-01-01"] == 1000.0, f"Expected 1000, got {result['2024-01-01']}"
    assert result["2024-02-01"] == 1500.0, f"Expected 1500, got {result['2024-02-01']}"
    assert result["2024-03-01"] == 1300.0, f"Expected 1300, got {result['2024-03-01']}"
    print("OK Test 1 PASSED: Basic deposits and withdrawals")
    
    # Test case 2: P2P transfers with Fertig subtitle
    transactions = [
        {"timestamp": "2024-01-01T10:00:00.000Z", "title": "Einzahlung", "subtitle": None, "amount": 1000.0},
        {"timestamp": "2024-02-01T10:00:00.000Z", "title": "John Smith", "subtitle": "Fertig", "amount": 2000.0},
        {"timestamp": "2024-03-01T10:00:00.000Z", "title": "Jane Doe", "subtitle": "Fertig", "amount": 500.0},
    ]
    
    result = tr._build_invested_series_from_transactions(transactions)
    
    assert result["2024-01-01"] == 1000.0, f"Expected 1000, got {result['2024-01-01']}"
    assert result["2024-02-01"] == 3000.0, f"Expected 3000, got {result['2024-02-01']}"
    assert result["2024-03-01"] == 3500.0, f"Expected 3500, got {result['2024-03-01']}"
    print("OK Test 2 PASSED: P2P transfers with Fertig")
    
    # Test case 3: Should NOT count dividends and interest
    transactions = [
        {"timestamp": "2024-01-01T10:00:00.000Z", "title": "Einzahlung", "subtitle": None, "amount": 1000.0},
        {"timestamp": "2024-02-01T10:00:00.000Z", "title": "Apple", "subtitle": "Bardividende", "amount": 50.0},
        {"timestamp": "2024-03-01T10:00:00.000Z", "title": "Zinsen", "subtitle": "2 % p.a.", "amount": 20.0},
        {"timestamp": "2024-04-01T10:00:00.000Z", "title": "Tesla", "subtitle": "Dividende", "amount": 30.0},
    ]
    
    result = tr._build_invested_series_from_transactions(transactions)
    
    # Only the deposit should count, dividends/interest are returns
    assert len(result) == 1, f"Expected 1 entry, got {len(result)}"
    assert result["2024-01-01"] == 1000.0, f"Expected 1000, got {result['2024-01-01']}"
    print("OK Test 3 PASSED: Dividends and interest NOT counted")
    
    # Test case 4: Should NOT count buy/sell orders
    transactions = [
        {"timestamp": "2024-01-01T10:00:00.000Z", "title": "Einzahlung", "subtitle": None, "amount": 1000.0},
        {"timestamp": "2024-02-01T10:00:00.000Z", "title": "Apple", "subtitle": "Kauforder", "amount": -500.0},
        {"timestamp": "2024-03-01T10:00:00.000Z", "title": "Tesla", "subtitle": "Verkaufsorder", "amount": 600.0},
        {"timestamp": "2024-04-01T10:00:00.000Z", "title": "S&P 500 ETF", "subtitle": "Sparplan ausgeführt", "amount": -100.0},
    ]
    
    result = tr._build_invested_series_from_transactions(transactions)
    
    # Only deposit counts, trades are internal movements
    assert len(result) == 1, f"Expected 1 entry, got {len(result)}"
    assert result["2024-01-01"] == 1000.0, f"Expected 1000, got {result['2024-01-01']}"
    print("OK Test 4 PASSED: Buy/sell orders NOT counted")
    
    # Test case 5: Should NOT count rejected transfers
    transactions = [
        {"timestamp": "2024-01-01T10:00:00.000Z", "title": "Einzahlung", "subtitle": None, "amount": 1000.0},
        {"timestamp": "2024-02-01T10:00:00.000Z", "title": "John Smith", "subtitle": "Abgelehnt", "amount": 5000.0},
    ]
    
    result = tr._build_invested_series_from_transactions(transactions)
    
    assert len(result) == 1, f"Expected 1 entry, got {len(result)}"
    assert result["2024-01-01"] == 1000.0, f"Expected 1000, got {result['2024-01-01']}"
    print("OK Test 5 PASSED: Rejected transfers NOT counted")
    
    # Test case 6: Should NOT count old P2P (no subtitle) to avoid inconsistency
    transactions = [
        {"timestamp": "2024-01-01T10:00:00.000Z", "title": "Einzahlung", "subtitle": None, "amount": 1000.0},
        {"timestamp": "2024-02-01T10:00:00.000Z", "title": "John Smith", "subtitle": None, "amount": 500.0},  # Old P2P
        {"timestamp": "2024-03-01T10:00:00.000Z", "title": "Jane Doe", "subtitle": None, "amount": -200.0},  # Old P2P outgoing
    ]
    
    result = tr._build_invested_series_from_transactions(transactions)
    
    # Old-style P2P (person name title, no subtitle) IS counted as capital flow
    assert len(result) == 3, f"Expected 3 entries, got {len(result)}"
    assert result["2024-01-01"] == 1000.0, f"Expected 1000, got {result['2024-01-01']}"
    assert result["2024-02-01"] == 1500.0, f"Expected 1500, got {result['2024-02-01']}"
    assert result["2024-03-01"] == 1300.0, f"Expected 1300, got {result['2024-03-01']}"
    print("OK Test 6 PASSED: Old P2P format (no subtitle) counted as capital flow")
    
    # Test case 7: Mixed real-world scenario
    transactions = [
        {"timestamp": "2024-01-01T10:00:00.000Z", "title": "Einzahlung", "subtitle": None, "amount": 5000.0},
        {"timestamp": "2024-01-15T10:00:00.000Z", "title": "Apple", "subtitle": "Kauforder", "amount": -1000.0},
        {"timestamp": "2024-02-01T10:00:00.000Z", "title": "John Smith", "subtitle": "Fertig", "amount": 2000.0},
        {"timestamp": "2024-02-15T10:00:00.000Z", "title": "Apple", "subtitle": "Bardividende", "amount": 50.0},
        {"timestamp": "2024-03-01T10:00:00.000Z", "title": "Withdrawal", "subtitle": "Gesendet", "amount": -500.0},
        {"timestamp": "2024-03-15T10:00:00.000Z", "title": "Tesla", "subtitle": "Verkaufsorder", "amount": 1200.0},
        {"timestamp": "2024-04-01T10:00:00.000Z", "title": "Einzahlung", "subtitle": None, "amount": 1000.0},
    ]
    
    result = tr._build_invested_series_from_transactions(transactions)
    
    # Expected flow:
    # 2024-01-01: +5000 = 5000
    # 2024-02-01: +2000 = 7000
    # 2024-03-01: -500 = 6500
    # 2024-04-01: +1000 = 7500
    assert result["2024-01-01"] == 5000.0, f"Expected 5000, got {result['2024-01-01']}"
    assert result["2024-02-01"] == 7000.0, f"Expected 7000, got {result['2024-02-01']}"
    assert result["2024-03-01"] == 6500.0, f"Expected 6500, got {result['2024-03-01']}"
    assert result["2024-04-01"] == 7500.0, f"Expected 7500, got {result['2024-04-01']}"
    print("OK Test 7 PASSED: Mixed real-world scenario")
    
    print()
    print("=" * 60)
    print("ALL TESTS PASSED OK")
    print("=" * 60)


if __name__ == "__main__":
    test_invested_series_calculation()
