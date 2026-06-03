"""
Test Trade Republic API endpoints for per-position history
"""
import asyncio
import json
from pathlib import Path
from pytr.api import TradeRepublicApi
from pytr.utils import get_logger

log = get_logger(__name__)

TR_CREDENTIALS_DIR = Path.home() / ".pytr"

async def test_timeline_detail():
    """Test what timeline_detail_v2 actually returns for a savings plan."""
    
    # Load credentials
    credentials_file = TR_CREDENTIALS_DIR / "credentials"
    if not credentials_file.exists():
        print("No credentials found. Please run main.py and connect first.")
        return
    
    with open(credentials_file, "r") as f:
        lines = f.readlines()
    phone_no = lines[0].strip()
    pin = lines[1].strip()
    
    keyfile = TR_CREDENTIALS_DIR / "keyfile.pem"
    if not keyfile.exists():
        print("No keyfile found. Please complete device setup first.")
        return
    
    api = TradeRepublicApi(phone_no=phone_no, pin=pin, keyfile=keyfile)
    
    print("\n=== Testing timeline_detail_v2 ===\n")
    
    # Use the ID from the problematic transaction
    txn_id = "f2ee2a6a-a833-4d81-94bd-9193eec423c1"
    
    print(f"Fetching details for transaction: {txn_id}")
    await api.timeline_detail_v2(txn_id)
    sub_id, sub_params, response = await api.recv()
    await api.unsubscribe(sub_id)
    
    print(f"\nFull response:")
    print(json.dumps(response, indent=2, default=str))
    
    # Look specifically at sections
    sections = response.get('sections', [])
    print(f"\n\n=== SECTIONS ===")
    for section in sections:
        print(f"\nSection: {section.get('title', 'NO TITLE')}")
        for item in section.get('data', []):
            title = item.get('title', '')
            detail = item.get('detail', {})
            text = detail.get('text', '') if isinstance(detail, dict) else detail
            print(f"  {title}: {text}")

async def test_portfolio_history():
    """Test the portfolio history and per-instrument history endpoints."""
    
    # Load credentials
    credentials_file = TR_CREDENTIALS_DIR / "credentials"
    if not credentials_file.exists():
        print("No credentials found. Please run main.py and connect first.")
        return
    
    with open(credentials_file, "r") as f:
        lines = f.readlines()
    phone_no = lines[0].strip()
    pin = lines[1].strip()
    
    keyfile = TR_CREDENTIALS_DIR / "keyfile.pem"
    if not keyfile.exists():
        print("No keyfile found. Please complete device setup first.")
        return
    
    api = TradeRepublicApi(phone_no=phone_no, pin=pin, keyfile=keyfile)
    
    print("\n=== Testing Trade Republic API ===\n")
    
    # Test 1: Get portfolio aggregate history
    print("1. Testing portfolioAggregateHistory (max range)...")
    try:
        await api.portfolio_history("max")
        sub_id, sub_params, response = await api.recv()
        await api.unsubscribe(sub_id)
        print(f"   Response type: {type(response)}")
        print(f"   Response keys: {response.keys() if isinstance(response, dict) else 'N/A'}")
        if isinstance(response, dict):
            # Check structure
            if 'data' in response:
                data = response['data']
                print(f"   Data length: {len(data) if isinstance(data, list) else 'N/A'}")
                if isinstance(data, list) and len(data) > 0:
                    print(f"   First item: {data[0]}")
                    print(f"   Last item: {data[-1]}")
            else:
                # Maybe it's a list directly
                print(f"   Direct response sample: {str(response)[:500]}")
        elif isinstance(response, list):
            print(f"   List length: {len(response)}")
            if len(response) > 0:
                print(f"   First item: {response[0]}")
                print(f"   Last item: {response[-1]}")
        print("   SUCCESS\n")
    except Exception as e:
        print(f"   FAILED: {e}\n")
    
    # Test 2: Get compact portfolio to find ISINs
    print("2. Testing compactPortfolio...")
    positions = []
    try:
        await api.compact_portfolio()
        sub_id, sub_params, portfolio = await api.recv()
        await api.unsubscribe(sub_id)
        print(f"   Response keys: {portfolio.keys() if isinstance(portfolio, dict) else 'N/A'}")
        positions = portfolio.get('positions', [])
        print(f"   Positions count: {len(positions)}")
        if positions:
            print(f"   First position: {positions[0]}")
        print("   SUCCESS\n")
    except Exception as e:
        print(f"   FAILED: {e}\n")
    
    # Test 3: Get performance history for a specific instrument
    if positions:
        isin = positions[0].get('instrumentId', '')
        if isin:
            print(f"3. Testing aggregateHistory for ISIN: {isin}...")
            try:
                await api.performance_history(isin, "max", exchange="LSX")
                sub_id, sub_params, response = await api.recv()
                await api.unsubscribe(sub_id)
                print(f"   Response type: {type(response)}")
                if isinstance(response, dict):
                    print(f"   Response keys: {response.keys()}")
                    if 'aggregates' in response:
                        aggs = response['aggregates']
                        print(f"   Aggregates length: {len(aggs) if isinstance(aggs, list) else 'N/A'}")
                        if isinstance(aggs, list) and len(aggs) > 0:
                            print(f"   First aggregate: {aggs[0]}")
                            print(f"   Last aggregate: {aggs[-1]}")
                    elif 'data' in response:
                        data = response['data']
                        print(f"   Data length: {len(data) if isinstance(data, list) else 'N/A'}")
                    else:
                        print(f"   Response sample: {str(response)[:500]}")
                elif isinstance(response, list):
                    print(f"   List length: {len(response)}")
                    if len(response) > 0:
                        print(f"   First item: {response[0]}")
                print("   SUCCESS\n")
            except Exception as e:
                print(f"   FAILED: {e}\n")
            
            # Test 4: Try different exchanges
            print(f"4. Testing aggregateHistory with different exchanges for ISIN: {isin}...")
            for exchange in ["LSX", "TDG", "MUN", "FRA"]:
                try:
                    await api.performance_history(isin, "1y", exchange=exchange)
                    sub_id, sub_params, response = await api.recv()
                    await api.unsubscribe(sub_id)
                    if isinstance(response, dict) and 'aggregates' in response:
                        aggs = response['aggregates']
                        print(f"   {exchange}: {len(aggs)} data points")
                    elif isinstance(response, list):
                        print(f"   {exchange}: {len(response)} data points")
                    else:
                        print(f"   {exchange}: Response has keys {response.keys() if isinstance(response, dict) else 'unknown'}")
                except Exception as e:
                    print(f"   {exchange}: FAILED - {e}")
            print()
    
    # Test 5: Get instrument details to check for type info
    if positions:
        isin = positions[0].get('instrumentId', '')
        if isin:
            print(f"5. Testing instrument details for ISIN: {isin}...")
            try:
                await api.instrument_details(isin)
                sub_id, sub_params, response = await api.recv()
                await api.unsubscribe(sub_id)
                print(f"   Response keys: {response.keys() if isinstance(response, dict) else 'N/A'}")
                if isinstance(response, dict):
                    for key in ['typeId', 'type', 'imageId', 'shortName', 'name', 'isin']:
                        if key in response:
                            print(f"   {key}: {response[key]}")
                print("   SUCCESS\n")
            except Exception as e:
                print(f"   FAILED: {e}\n")
    
    print("=== Testing Complete ===")

if __name__ == "__main__":
    asyncio.run(test_timeline_detail())
