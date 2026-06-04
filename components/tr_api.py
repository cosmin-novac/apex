"""
Trade Republic API Wrapper
Uses pytr library for actual TR API communication
"""

import asyncio
from datetime import datetime, timedelta
import os
import json
import base64
import hashlib
from pathlib import Path
from typing import Optional, Dict, Any, Tuple, List
import threading
from concurrent.futures import TimeoutError as FuturesTimeoutError

# Minimum seconds between Trade Republic syncs.
# Keeps the app responsive and prevents accidental rapid re-syncs.
MIN_SYNC_INTERVAL_SECONDS = 6 * 60 * 60  # 6 hours

# pytr imports
from pytr.api import TradeRepublicApi
from pytr.utils import get_logger
from pytr.timeline import Timeline
from pytr.event import Event

# Setup logging
log = get_logger(__name__)

# Credentials storage path (server-side for keyfile only)
TR_CREDENTIALS_DIR = Path.home() / ".pytr"
TR_KEYFILE = TR_CREDENTIALS_DIR / "keyfile.pem"
TR_TRANSACTIONS_CACHE = TR_CREDENTIALS_DIR / "transactions_cache.json"

# Encryption key from environment (set this in your .env or hosting config)
ENCRYPTION_KEY = os.environ.get("TR_ENCRYPTION_KEY", "default-dev-key-change-in-prod")


def _get_cipher_key():
    """Derive a 32-byte key from the encryption key."""
    return hashlib.sha256(ENCRYPTION_KEY.encode()).digest()


def encrypt_credentials(phone_no: str, pin: str) -> str:
    """Encrypt credentials for browser storage."""
    from cryptography.fernet import Fernet
    # Derive Fernet key from our encryption key
    key = base64.urlsafe_b64encode(_get_cipher_key())
    f = Fernet(key)
    data = json.dumps({"phone": phone_no, "pin": pin})
    encrypted = f.encrypt(data.encode())
    return base64.urlsafe_b64encode(encrypted).decode()


def decrypt_credentials(encrypted: str) -> Tuple[Optional[str], Optional[str]]:
    """Decrypt credentials from browser storage."""
    try:
        from cryptography.fernet import Fernet
        key = base64.urlsafe_b64encode(_get_cipher_key())
        f = Fernet(key)
        encrypted_bytes = base64.urlsafe_b64decode(encrypted.encode())
        decrypted = f.decrypt(encrypted_bytes).decode()
        data = json.loads(decrypted)
        return data.get("phone"), data.get("pin")
    except Exception as e:
        log.error(f"Failed to decrypt credentials: {e}")
        return None, None


import re


def normalize_phone(phone_no: str) -> Optional[str]:
    """Normalize a phone number to E.164 (``+<countrycode><number>``).

    Trade Republic only accepts international format. Users routinely type the
    number with spaces, dashes or parentheses (the input placeholder even shows
    ``+49 XXX XXXXXXX``), so we strip formatting before sending it on.

    Returns the cleaned number, or ``None`` if it can't be made valid.
    """
    if not phone_no:
        return None
    # Keep a single leading '+', drop every other non-digit character.
    cleaned = phone_no.strip()
    plus = cleaned.startswith("+") or cleaned.startswith("00")
    digits = re.sub(r"\D", "", cleaned)
    if cleaned.startswith("00"):
        digits = digits[2:]  # 0049... -> 49...
    if not digits:
        return None
    # E.164 numbers are 8–15 digits incl. country code.
    if len(digits) < 8 or len(digits) > 15:
        return None
    if not plus and not cleaned.startswith("+"):
        # No country code indicated – we can't safely guess one.
        return None
    return "+" + digits


def friendly_tr_error(exc: Exception) -> str:
    """Translate a raw pytr/requests exception into an actionable message.

    pytr surfaces transport-level failures verbatim – e.g. an empty HTTP body
    becomes ``Expecting value: line 1 column 1 (char 0)`` from ``r.json()``,
    which is meaningless to a user. Map the common cases to plain language.
    """
    msg = str(exc)
    low = msg.lower()
    if "expecting value" in low or "json" in low:
        return ("Trade Republic returned an empty response. The service may be "
                "temporarily unavailable or is rate-limiting logins - please wait "
                "a minute and try again.")
    if "number_invalid" in low or "phonenumber" in low:
        return "That phone number wasn't accepted. Use international format, e.g. +49 151 23456789."
    if "too_many" in low or "rate" in low or "429" in low:
        return "Too many attempts. Please wait a few minutes before trying again."
    if "401" in low or "unauthorized" in low or "pin" in low:
        return "Login was rejected. Please double-check your phone number and PIN."
    if "validation" in low or "code" in low or "400" in low:
        return "The verification code was invalid or has expired. Please request a new code."
    return msg or "Connection to Trade Republic failed. Please try again."


class TRConnection:
    """Manages Trade Republic connection state.

    Each instance is scoped to a *user_id* so that server-side caches
    (portfolio, transactions, instruments) never collide between users.
    Logos in ``assets/logos/`` are shared – they are keyed by globally-unique
    ISIN so sharing is harmless and beneficial.
    """

    def __init__(self, user_id: str = "_default"):
        self.user_id = user_id
        self.api: Optional[TradeRepublicApi] = None
        self.phone_no: Optional[str] = None
        self.pin: Optional[str] = None
        self.is_connected = False
        self.portfolio_data: Optional[Dict] = None
        self.cash_data: Optional[Dict] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._loop_ready = threading.Event()
        self._op_lock = threading.Lock()

        # ── Per-user cache directory ────────────────────────────────────
        self._user_cache_dir = TR_CREDENTIALS_DIR / user_id
        self._user_cache_dir.mkdir(parents=True, exist_ok=True)
        self._instrument_cache_path = self._user_cache_dir / "instrument_cache.json"
        self._keyfile_path = self._user_cache_dir / "keyfile.pem"

        # Migrate legacy (non-namespaced) caches into the _default bucket
        # so existing single-user setups keep working without a re-sync.
        if user_id == "_default":
            for legacy_name in ("portfolio_cache.json", "transactions_cache.json", "instrument_cache.json", "keyfile.pem"):
                legacy = TR_CREDENTIALS_DIR / legacy_name
                dest   = self._user_cache_dir / legacy_name
                if legacy.exists() and not dest.exists():
                    try:
                        import shutil
                        shutil.move(str(legacy), str(dest))
                        log.info(f"Migrated legacy cache {legacy_name} → {self._user_cache_dir.name}/")
                    except Exception as e:
                        log.warning(f"Failed to migrate {legacy_name}: {e}")

    def _ensure_worker_loop(self) -> asyncio.AbstractEventLoop:
        """Ensure a single dedicated asyncio loop exists for all pytr websocket work.

        Dash callbacks can run in different threads; mixing event loops causes
        'Future attached to a different loop' runtime errors.
        """
        if self._loop and self._thread and self._thread.is_alive():
            return self._loop

        self._loop_ready.clear()

        def _runner():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            self._loop_ready.set()
            loop.run_forever()

        self._thread = threading.Thread(target=_runner, name="tr-async-loop", daemon=True)
        self._thread.start()
        if not self._loop_ready.wait(timeout=5):
            raise RuntimeError("Failed to start TR asyncio loop thread")
        if not self._loop:
            raise RuntimeError("TR asyncio loop not initialized")
        return self._loop

    def run(self, coro, timeout: float = 90):
        """Run a coroutine on the dedicated TR loop and wait for its result."""
        loop = self._ensure_worker_loop()
        fut = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return fut.result(timeout=timeout)
        except FuturesTimeoutError:
            fut.cancel()
            raise

    def run_serialized(self, coro, timeout: float = 90):
        """Run a coroutine while holding an operation lock.

        This prevents overlapping websocket recv/unsubscribe calls from multiple Dash callbacks.
        """
        with self._op_lock:
            return self.run(coro, timeout=timeout)

    def has_credentials(self) -> bool:
        """Best-effort check for a reusable TR session (keyfile)."""
        return self._keyfile_path.exists()

    def _load_instrument_cache(self) -> Dict[str, str]:
        try:
            if self._instrument_cache_path.exists():
                data = json.loads(self._instrument_cache_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    # values should be shortName/name strings
                    return {str(k): str(v) for k, v in data.items() if k and v}
        except Exception as e:
            log.warning(f"Failed to load instrument cache: {e}")
        return {}

    def _save_instrument_cache(self, cache: Dict[str, str]) -> None:
        try:
            TR_CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
            self._instrument_cache_path.write_text(json.dumps(cache), encoding="utf-8")
        except Exception as e:
            log.warning(f"Failed to save instrument cache: {e}")

    def _download_logos(self, enriched_positions: List[Dict]) -> None:
        """Download position logos into assets/logos/ for local serving.

        Strategy (in order):
        1. Parqet public CDN: ``https://assets.parqet.com/logos/isin/{ISIN}``
           – works for most stocks, ETFs and bonds (returns SVG).
        2. ui-avatars.com: generates a nice colored-initials PNG as fallback
           for anything Parqet doesn't cover (crypto, exotic small-caps).
        Images already on disk are skipped.
        """
        import requests as _requests
        from urllib.parse import quote

        logos_dir = Path(__file__).resolve().parent.parent / "assets" / "logos"
        logos_dir.mkdir(parents=True, exist_ok=True)

        PARQET_BASE = "https://assets.parqet.com/logos/isin"

        # Asset-class → background colour for the avatar fallback
        _CLASS_COLORS = {
            "stock": "10b981", "fund": "3b82f6", "etf": "3b82f6",
            "crypto": "f59e0b", "bond": "8b5cf6",
        }

        # Collect positions that need logo download
        to_download = []
        for pos in enriched_positions:
            isin = pos.get("isin", "")
            if not isin:
                continue
            # Accept both .svg and .png (Parqet returns SVG, avatar returns PNG)
            svg_dest = logos_dir / f"{isin}.svg"
            png_dest = logos_dir / f"{isin}.png"
            if (svg_dest.exists() and svg_dest.stat().st_size > 50) or \
               (png_dest.exists() and png_dest.stat().st_size > 50):
                continue  # already cached
            to_download.append(pos)

        if not to_download:
            log.info("All logos already cached – nothing to download.")
            return

        log.info(f"Downloading {len(to_download)} logos …")

        for pos in to_download:
            isin = pos["isin"]
            name = pos.get("name", isin)
            inst_type = pos.get("instrumentType", "").lower()

            # --- Attempt 1: Parqet CDN ---
            parqet_url = f"{PARQET_BASE}/{isin}"
            try:
                resp = _requests.get(parqet_url, timeout=8)
                if resp.status_code == 200 and len(resp.content) > 50:
                    ct = resp.headers.get("Content-Type", "")
                    ext = "svg" if "svg" in ct else "png"
                    dest = logos_dir / f"{isin}.{ext}"
                    dest.write_bytes(resp.content)
                    log.info(f"  ✓ {isin} logo from Parqet ({len(resp.content)}b {ext})")
                    continue
            except Exception:
                pass

            # --- Attempt 2: ui-avatars.com (coloured initials image) ---
            words = [w for w in name.split() if w]
            if len(words) >= 2:
                initials = words[0][0] + words[1][0]
            elif words:
                initials = words[0][:2]
            else:
                initials = "?"
            bg = _CLASS_COLORS.get(inst_type, "6b7280")
            avatar_url = (
                f"https://ui-avatars.com/api/?name={quote(initials)}"
                f"&background={bg}&color=fff&size=64&rounded=true&bold=true&format=png"
            )
            try:
                resp = _requests.get(avatar_url, timeout=8)
                if resp.status_code == 200 and len(resp.content) > 50:
                    dest = logos_dir / f"{isin}.png"
                    dest.write_bytes(resp.content)
                    log.info(f"  ✓ {isin} avatar fallback ({len(resp.content)}b)")
                    continue
            except Exception:
                pass

            log.debug(f"  ✗ {isin} – no logo source available")

    def _load_transactions_cache(self) -> List[Dict]:
        """Load cached transactions (user-scoped)."""
        cache_file = self._user_cache_dir / "transactions_cache.json"
        try:
            if cache_file.exists():
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                if isinstance(data, list):
                    return data
        except Exception as e:
            log.warning(f"Failed to load transactions cache: {e}")
        return []

    def _save_transactions_cache(self, transactions: List[Dict]) -> None:
        """Save transactions to cache (user-scoped).
        
        Note: We strip the 'details' field before saving as it's huge and not needed
        for caching purposes (shares are already extracted).
        """
        try:
            self._user_cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = self._user_cache_dir / "transactions_cache.json"
            # Strip 'details' field to save space - it can be huge!
            clean_transactions = [
                {k: v for k, v in txn.items() if k != 'details'}
                for txn in transactions
            ]
            cache_file.write_text(json.dumps(clean_transactions, default=str), encoding="utf-8")
            log.info(f"Saved {len(transactions)} transactions to cache (user={self.user_id})")
        except Exception as e:
            log.warning(f"Failed to save transactions cache: {e}")

    async def _fetch_timeline_transactions(self, delta_load: bool = True) -> List[Dict]:
        """Fetch timeline transactions from TR with delta loading.
        
        Delta loading: Only fetches new transactions since the last sync.
        This significantly speeds up subsequent syncs.
        
        Args:
            delta_load: If True, stop when we hit a transaction already in cache.
                       If False, fetch all transactions from scratch.
        
        Returns:
            Complete list of transactions (new + cached)
        """
        if not self.api or not self.is_connected:
            log.error("Cannot fetch timeline - not connected")
            return []
        
        # Load cached transactions for delta comparison
        cached_txns = self._load_transactions_cache() if delta_load else []
        cached_ids = {txn.get('id') for txn in cached_txns if txn.get('id')}
        
        if cached_txns and delta_load:
            log.info(f"Delta loading: {len(cached_txns)} transactions in cache")
        
        new_transactions = []
        after_cursor = None
        page = 0
        max_pages = 100  # Safety limit
        found_cached = False
        
        log.info("Fetching timeline transactions...")
        
        while page < max_pages:
            page += 1
            try:
                # Subscribe to timeline transactions
                await self.api.timeline_transactions(after=after_cursor)
                sub_id, sub_params, response = await self.api.recv()
                await self.api.unsubscribe(sub_id)
                
                # Handle unexpected response types
                if isinstance(response, list):
                    log.warning(f"Timeline page {page}: got list instead of dict, skipping")
                    break
                if not isinstance(response, dict):
                    log.warning(f"Timeline page {page}: unexpected response type {type(response)}")
                    break
                
                items = response.get('items', [])
                if not items:
                    log.info(f"Timeline page {page}: no more items")
                    break
                    
                page_new_count = 0
                for item in items:
                    item_id = item.get('id')
                    
                    # Delta loading: stop if we hit a cached transaction
                    if delta_load and item_id in cached_ids:
                        found_cached = True
                        log.info(f"Timeline page {page}: found cached transaction, stopping delta load")
                        break
                    
                    # Extract ISIN from icon field (e.g. "logos/IE00B5BMR087/v2")
                    icon = item.get('icon', '')
                    isin = None
                    if icon and 'logos/' in icon:
                        import re
                        match = re.search(r'logos/([A-Z0-9]{12})', icon)
                        if match:
                            isin = match.group(1)
                    
                    # Extract basic transaction info
                    txn = {
                        'id': item_id,
                        'timestamp': item.get('timestamp'),
                        'title': item.get('title'),
                        'subtitle': item.get('subtitle'),
                        'eventType': item.get('eventType'),
                        'amount': item.get('amount', {}).get('value'),
                        'currency': item.get('amount', {}).get('currency'),
                        'icon': icon,
                        'isin': isin,  # Add extracted ISIN
                    }
                    new_transactions.append(txn)
                    page_new_count += 1
                
                if found_cached:
                    break
                    
                log.info(f"Timeline page {page}: got {page_new_count} new items")
                
                # Check for next page
                cursors = response.get('cursors', {})
                after_cursor = cursors.get('after')
                if not after_cursor:
                    log.info(f"Timeline complete after {page} pages")
                    break
                    
            except Exception as e:
                log.error(f"Error fetching timeline page {page}: {e}")
                break
        
        # Merge new transactions with cached ones
        if delta_load and cached_txns and new_transactions:
            # New transactions are newer, so prepend them
            all_transactions = new_transactions + cached_txns
            log.info(f"Delta load complete: {len(new_transactions)} new + {len(cached_txns)} cached = {len(all_transactions)} total")
        elif delta_load and cached_txns and not new_transactions:
            all_transactions = cached_txns
            log.info(f"Delta load: No new transactions, using {len(cached_txns)} cached")
        else:
            all_transactions = new_transactions
            log.info(f"Full load: {len(all_transactions)} transactions")
        
        # Sort by timestamp descending (newest first) and deduplicate
        seen_ids = set()
        unique_transactions = []
        for txn in sorted(all_transactions, key=lambda x: x.get('timestamp', ''), reverse=True):
            txn_id = txn.get('id')
            if txn_id and txn_id not in seen_ids:
                seen_ids.add(txn_id)
                unique_transactions.append(txn)
        
        return unique_transactions

    async def _fetch_transaction_details(self, transaction_id: str, retries: int = 2) -> Optional[Dict]:
        """Fetch detailed info for a single transaction, including shares.
        
        Uses timeline_detail_v2 API to get full transaction details with quantity.
        Includes retry logic for robustness.
        """
        if not self.api or not self.is_connected:
            log.warning(f"Cannot fetch detail for {transaction_id} - not connected")
            return None
        
        for attempt in range(retries + 1):
            try:
                await self.api.timeline_detail_v2(transaction_id)
                sub_id, sub_params, response = await self.api.recv()
                await self.api.unsubscribe(sub_id)
                
                # Check if we got a valid response
                if response is None:
                    log.debug(f"Got None response for {transaction_id}, attempt {attempt+1}")
                    if attempt < retries:
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    return None
                    
                # Check for error responses
                if isinstance(response, dict) and response.get('errors'):
                    log.debug(f"Error response for {transaction_id}: {response.get('errors')}")
                    return None
                    
                return response
            except Exception as e:
                if attempt < retries:
                    await asyncio.sleep(0.5 * (attempt + 1))  # Backoff
                    continue
                log.debug(f"Error fetching detail for {transaction_id} after {retries+1} attempts: {e}")
                return None
        return None

    async def _enrich_transactions_with_shares(self, transactions: List[Dict]) -> List[Dict]:
        """Fetch shares/quantity for buy/sell transactions from TR.
        
        Uses pytr's concurrent approach: fire ALL detail requests at once, then
        receive responses as they arrive. This is MUCH faster than sequential calls.
        
        Uses pytr's Event.from_dict() for parsing - it handles German number formats
        correctly and is battle-tested code.
        
        Returns transactions with 'shares', 'type', and 'details' fields populated.
        """
        if not self.api or not self.is_connected:
            log.error("Cannot enrich transactions - not connected")
            return transactions
        
        # Transaction subtitles that involve share changes
        TRADE_SUBTITLES = {
            'Kauforder', 'Sparplan ausgeführt', 'Limit-Buy-Order',
            'Verkaufsorder', 'Limit-Sell-Order', 'Stop-Sell-Order',
            'Bonusaktien', 'Aktiensplit', 'Reverse Split', 'Tausch', 'Spin-off',
            'Wertlos',  # Expired worthless
        }
        
        # Map subtitles to transaction types
        SUBTITLE_TO_TYPE = {
            'Kauforder': 'buy',
            'Limit-Buy-Order': 'buy',
            'Sparplan ausgeführt': 'savings_plan',
            'Verkaufsorder': 'sell',
            'Limit-Sell-Order': 'sell',
            'Stop-Sell-Order': 'sell',
            'Bonusaktien': 'bonus',
            'Aktiensplit': 'split',
            'Reverse Split': 'reverse_split',
            'Tausch': 'exchange',
            'Spin-off': 'spinoff',
            'Wertlos': 'expired',
        }
        
        # First pass: set transaction types and identify which need enrichment
        txns_needing_details = {}  # id -> txn
        for txn in transactions:
            subtitle = txn.get('subtitle') or ''
            shares = txn.get('shares')
            
            # Add transaction type based on subtitle
            if subtitle in SUBTITLE_TO_TYPE:
                txn['type'] = SUBTITLE_TO_TYPE[subtitle]
            elif not txn.get('type'):
                # Fallback type detection based on subtitle keywords
                if 'Einzahlung' in subtitle or 'Überweisung' in subtitle:
                    txn['type'] = 'deposit'
                elif 'Auszahlung' in subtitle:
                    txn['type'] = 'withdrawal'
                elif 'Dividende' in subtitle:
                    txn['type'] = 'dividend'
                else:
                    txn['type'] = 'other'
            
            # Re-enrich if shares is missing, None, 0, or suspiciously large (>1M = likely parse error)
            needs_enrichment = shares is None or shares == 0 or shares > 1_000_000
            txn_id = txn.get('id')
            
            if subtitle in TRADE_SUBTITLES and needs_enrichment and txn_id:
                txns_needing_details[txn_id] = txn
        
        trade_count = len(txns_needing_details)
        if trade_count == 0:
            log.info("No transactions need share enrichment")
            return transactions
        
        # Test the connection with a simple API call first
        try:
            log.info("Testing TR connection before enrichment...")
            await self.api.cash()
            sub_id, _, _ = await self.api.recv()
            await self.api.unsubscribe(sub_id)
            log.info("TR connection verified")
        except Exception as e:
            log.error(f"TR connection test failed: {e}")
            log.error("Skipping enrichment - connection appears to be down")
            return transactions
        
        log.info(f"Enriching {trade_count} trade transactions with share quantities (concurrent)...")
        
        # ============================================================
        # CONCURRENT APPROACH (like pytr's Timeline._request_timeline_details)
        # Fire ALL requests first, then receive ALL responses
        # This is MUCH faster than sequential request/response pairs
        # ============================================================
        
        # Step 1: Fire all timeline_detail_v2 requests (no waiting!)
        pending_subscriptions = {}  # sub_id -> txn_id
        batch_size = 200  # Process in batches to avoid overwhelming the connection
        txn_ids = list(txns_needing_details.keys())
        
        total_success = 0  # Track across ALL batches
        
        for batch_start in range(0, len(txn_ids), batch_size):
            batch_end = min(batch_start + batch_size, len(txn_ids))
            batch = txn_ids[batch_start:batch_end]
            
            log.info(f"  Firing requests for batch {batch_start//batch_size + 1} ({len(batch)} transactions)...")
            
            # Fire all requests in this batch (no awaiting responses yet!)
            for txn_id in batch:
                try:
                    sub_id = await self.api.timeline_detail_v2(txn_id)
                    pending_subscriptions[sub_id] = txn_id
                except Exception as e:
                    log.debug(f"  Failed to request details for {txn_id}: {e}")
            
            # Step 2: Receive all responses for this batch
            received = 0
            batch_success = 0
            max_retries = len(pending_subscriptions) + 50  # Safety limit
            
            while pending_subscriptions and received < max_retries:
                try:
                    sub_id, sub_params, response = await asyncio.wait_for(
                        self.api.recv(), 
                        timeout=30.0
                    )
                    received += 1
                    
                    # Check if this is a response we're waiting for
                    txn_id = pending_subscriptions.pop(sub_id, None)
                    if txn_id is None:
                        continue
                    
                    # Unsubscribe to clean up
                    await self.api.unsubscribe(sub_id)
                    
                    if response is None or (isinstance(response, dict) and response.get('errors')):
                        continue
                    
                    # Get the transaction and add the details
                    txn = txns_needing_details.get(txn_id)
                    if not txn:
                        continue
                    
                    # NOTE: Do NOT store txn['details'] = response - it's huge and causes storage issues
                    # We only need to extract the shares from it
                    
                    # Log the raw shares text for debugging
                    raw_shares_text = self._find_raw_shares_text(response)
                    title = txn.get('title', '')
                    
                    # Use pytr's Event.from_dict() to parse shares - it handles German numbers correctly!
                    try:
                        # Build event dict in the format Event.from_dict expects
                        event_dict = {
                            'id': txn_id,
                            'timestamp': txn.get('timestamp', ''),
                            'title': txn.get('title', ''),
                            'subtitle': txn.get('subtitle', ''),
                            'eventType': txn.get('eventType', ''),
                            'icon': txn.get('icon', ''),
                            'details': response,
                        }
                        event = Event.from_dict(event_dict)
                        
                        if event.shares is not None and event.shares > 0:
                            # Validate the parsed shares using price sanity check
                            validated_shares = self._validate_shares(txn, event.shares)
                            if validated_shares:
                                txn['shares'] = validated_shares
                                batch_success += 1
                                total_success += 1
                            else:
                                # Validation failed - log details for debugging
                                ts = txn.get('timestamp', '')[:10]
                                log.warning(f"⚠️ Shares validation failed: {title} on {ts}")
                                log.warning(f"    pytr parsed: {event.shares}, raw text: {raw_shares_text}")
                                
                                # Try manual extraction as fallback
                                new_shares = self._extract_shares_from_details(response)
                                validated = self._validate_shares(txn, new_shares) if new_shares else None
                                if validated:
                                    txn['shares'] = validated
                                    batch_success += 1
                                    total_success += 1
                                    log.info(f"    ✓ Manual extraction succeeded: {validated}")
                                else:
                                    # For crypto, try to estimate from price in response
                                    estimated = self._estimate_crypto_shares(txn, response)
                                    validated_est = self._validate_shares(txn, estimated) if estimated else None
                                    if validated_est:
                                        txn['shares'] = validated_est
                                        batch_success += 1
                                        total_success += 1
                                        log.info(f"    ✓ Estimated from price: {validated_est}")
                                    else:
                                        log.warning(f"    ✗ All methods failed, transaction will be skipped")
                            
                            # Also extract ISIN if Event found it and we don't have it
                            if event.isin and not txn.get('isin'):
                                txn['isin'] = event.isin
                        else:
                            # Fallback to our manual extraction
                            new_shares = self._extract_shares_from_details(response)
                            if new_shares and new_shares > 0:
                                validated = self._validate_shares(txn, new_shares)
                                if validated:
                                    txn['shares'] = validated
                                    batch_success += 1
                                    total_success += 1
                                
                    except Exception as parse_err:
                        log.debug(f"  Event.from_dict failed for {txn_id}, trying manual: {parse_err}")
                        # Fallback to manual extraction
                        new_shares = self._extract_shares_from_details(response)
                        if new_shares and new_shares > 0:
                            validated = self._validate_shares(txn, new_shares)
                            if validated:
                                txn['shares'] = validated
                                batch_success += 1
                                total_success += 1
                    
                    if total_success <= 5 or total_success % 100 == 0:
                        title = txn.get('title', '')[:25]
                        shares = txn.get('shares', 0)
                        log.info(f"  [{total_success}/{trade_count}] {title}: {shares:.6f} shares")
                        
                except asyncio.TimeoutError:
                    log.warning(f"  Timeout waiting for responses, {len(pending_subscriptions)} remaining")
                    break
                except Exception as e:
                    log.debug(f"  Error receiving response: {e}")
                    received += 1
            
            # Unsubscribe from any remaining pending subscriptions
            for sub_id in list(pending_subscriptions.keys()):
                try:
                    await self.api.unsubscribe(sub_id)
                except:
                    pass
            pending_subscriptions.clear()
            
            log.info(f"  Batch complete: {batch_success} successful enrichments")
        
        # Report enrichment completeness
        success_rate = (total_success / trade_count * 100) if trade_count > 0 else 100
        log.info(f"Enriched {total_success}/{trade_count} transactions ({success_rate:.1f}% success)")
        
        if success_rate < 80:
            log.warning(f"⚠️ Low enrichment rate ({success_rate:.1f}%) - some share data may be missing")
        
        return transactions

    def _estimate_crypto_shares(self, txn: Dict, response: Dict) -> Optional[float]:
        """Estimate crypto shares from transaction amount when parsing fails.
        
        For crypto transactions where share parsing fails validation, we can
        estimate shares by finding the price in the transaction detail and
        dividing: shares = amount / price
        
        This is a fallback for cases where pytr misparsed the shares text.
        """
        amount = abs(txn.get('amount', 0) or 0)
        if amount <= 0:
            return None
            
        # Look for price in the response
        sections = response.get('sections', [])
        for section in sections:
            for item in section.get('data', []):
                item_title = item.get('title', '').lower()
                # Look for price-related fields
                if any(kw in item_title for kw in ['preis', 'kurs', 'price', 'quotation']):
                    detail = item.get('detail', {})
                    price_text = detail.get('text', '') if isinstance(detail, dict) else str(detail)
                    price = self._parse_german_number(price_text)
                    if price and price > 0:
                        estimated_shares = amount / price
                        log.info(f"    Estimated shares from price: {amount:.2f} / {price:.2f} = {estimated_shares:.8f}")
                        return estimated_shares
        
        return None

    def _validate_shares(self, txn: Dict, shares: Optional[float]) -> Optional[float]:
        """Validate share quantity by checking implied price against known bounds.
        
        For crypto (especially BTC), pytr sometimes returns clearly wrong values
        like 243 BTC for €50 (implying €0.21/BTC which is impossible).
        
        This validates by calculating implied price and checking against bounds.
        Returns the shares if valid, None if clearly wrong.
        """
        if shares is None or shares <= 0:
            return None
            
        amount = abs(txn.get('amount', 0) or 0)
        if amount <= 0:
            # Can't validate without amount, assume OK
            return shares
        
        # Calculate implied price per share
        implied_price = amount / shares
        
        # Get asset info from icon/isin
        icon = txn.get('icon', '')
        isin = txn.get('isin', '')
        title = txn.get('title', '').lower()
        
        # BTC-specific validation
        if 'BTC' in icon or 'BTC' in isin or 'bitcoin' in title:
            # BTC has never been below €1,000 or above €200,000
            if implied_price < 1000:
                log.warning(f"BTC shares validation FAILED: {shares:.8f} for €{amount:.2f} => €{implied_price:.2f}/BTC (too low)")
                return None
            if implied_price > 200000:
                log.warning(f"BTC shares validation FAILED: {shares:.8f} for €{amount:.2f} => €{implied_price:.2f}/BTC (too high)")
                return None
            return shares
        
        # ETH-specific validation  
        if 'ETH' in icon or 'ETH' in isin or 'ethereum' in title:
            # ETH has been between €100 and €5000
            if implied_price < 50:
                log.warning(f"ETH shares validation FAILED: {shares:.8f} for €{amount:.2f} => €{implied_price:.2f}/ETH")
                return None
            if implied_price > 10000:
                log.warning(f"ETH shares validation FAILED: {shares:.8f} for €{amount:.2f} => €{implied_price:.2f}/ETH")
                return None
            return shares
        
        # Generic stock/ETF validation - price per share is usually €0.01 to €100,000
        # Note: Very low implied prices often indicate German number format issues
        # e.g., "243.000" parsed as 243000 instead of 243
        if implied_price < 0.01:
            # Check if this could be a German number format issue (factor of 1000)
            corrected_shares = shares / 1000
            corrected_price = amount / corrected_shares
            if 0.01 <= corrected_price <= 500000:
                log.warning(f"⚠️ German number format fix: {shares:.0f} -> {corrected_shares:.6f} (€{implied_price:.6f} -> €{corrected_price:.2f}/share)")
                return corrected_shares
            log.warning(f"Shares validation FAILED: {shares:.8f} for €{amount:.2f} => €{implied_price:.6f}/share (too low)")
            return None
        if implied_price > 500000:
            log.warning(f"Shares validation FAILED: {shares:.8f} for €{amount:.2f} => €{implied_price:.2f}/share (too high)")
            return None
        
        return shares

    def _extract_shares_from_details(self, details: Dict) -> Optional[float]:
        """Extract share quantity from transaction detail response.
        
        Parses the 'sections' in the detail response to find share count.
        Looks for fields like 'Aktien', 'Anteile' in German responses.
        
        IMPORTANT: TR returns shares as formatted text like "7,470352" which 
        represents 7.470352 shares (German decimal format).
        """
        sections = details.get('sections', [])
        
        for section in sections:
            section_title = section.get('title', '')
            
            # Look in transaction-related sections
            if section_title in ['Transaktion', 'Geschäft', 'Übersicht', 'Order', 'Sparplan']:
                for item in section.get('data', []):
                    item_title = item.get('title', '')
                    # Share count fields
                    if item_title in ['Aktien', 'Anteile', 'Aktien hinzugefügt', 'Aktien entfernt', 'Stück']:
                        detail = item.get('detail', {})
                        
                        # Try numeric value field first
                        if isinstance(detail, dict):
                            if 'value' in detail:
                                try:
                                    return float(detail['value'])
                                except (ValueError, TypeError):
                                    pass
                            
                            # Fall back to text parsing
                            text = detail.get('text', '')
                            if text:
                                parsed = self._parse_german_number(text)
                                if parsed is not None:
                                    # Log for debugging
                                    log.debug(f"Parsed shares from text '{text}' = {parsed}")
                                    return parsed
                        elif isinstance(detail, (int, float)):
                            return float(detail)
                        elif isinstance(detail, str):
                            return self._parse_german_number(detail)
        
        # Also check for a top-level 'shares' or 'quantity' field
        for key in ['shares', 'quantity', 'amount']:
            if key in details and isinstance(details[key], (int, float)):
                return float(details[key])
        
        return None

    def _find_raw_shares_text(self, details: Dict) -> Optional[str]:
        """Find the raw shares text from TR API response for debugging."""
        sections = details.get('sections', [])
        
        for section in sections:
            section_title = section.get('title', '')
            if section_title in ['Transaktion', 'Geschäft', 'Übersicht', 'Order', 'Sparplan']:
                for item in section.get('data', []):
                    item_title = item.get('title', '')
                    if item_title in ['Aktien', 'Anteile', 'Aktien hinzugefügt', 'Aktien entfernt', 'Stück']:
                        detail = item.get('detail', {})
                        if isinstance(detail, dict):
                            return f"text='{detail.get('text', '')}', value={detail.get('value', 'N/A')}"
                        else:
                            return str(detail)
        return None

    def _parse_german_number(self, text: str) -> Optional[float]:
        """Parse a German-formatted number for share quantities.
        
        German format examples:
        - "1.234,56" = 1234.56 (dot=thousands, comma=decimal)
        - "7,470352" = 7.470352 (comma=decimal, for fractional shares)
        - "1.234" could be 1234 (thousands) or 1.234 (decimal)
        
        For share quantities, we expect high precision (many decimal places),
        so 6+ digits after separator likely means decimal, not thousands.
        """
        try:
            # Remove any currency symbols and whitespace
            text = text.strip().replace('€', '').replace('$', '').strip()
            
            # If both comma and dot present: German format (dot=thousands, comma=decimal)
            if ',' in text and '.' in text:
                # 1.234,56 -> 1234.56
                text = text.replace('.', '').replace(',', '.')
            elif ',' in text:
                # Comma only: it's the decimal separator
                # 7,470352 -> 7.470352
                text = text.replace(',', '.')
            elif '.' in text:
                # Dot only: check if it looks like thousands or decimal
                parts = text.split('.')
                if len(parts) == 2:
                    # If many digits after dot (>3), it's decimal, not thousands
                    # e.g., "7.470352" is 7.470352, not 7,470,352
                    if len(parts[1]) > 3:
                        # Already in correct format
                        pass
                    elif len(parts[1]) == 3 and len(parts[0]) <= 3:
                        # Ambiguous: "1.234" could be 1234 or 1.234
                        # For shares, assume decimal (more common for small quantities)
                        pass
                    else:
                        # Likely thousands separator: "1.234" = 1234
                        text = text.replace('.', '')
            
            return float(text)
        except (ValueError, AttributeError):
            return None

    async def _fetch_portfolio_aggregate_history(self, timeframe: str = "max") -> List[Dict]:
        """Fetch aggregate portfolio history from TR.
        
        Uses the portfolioAggregateHistory API to get real portfolio value over time.
        Timeframe options: 1d, 1w, 1m, 3m, 1y, max
        """
        if not self.api or not self.is_connected:
            log.error("Cannot fetch portfolio history - not connected")
            return []
        
        try:
            log.info(f"Fetching portfolio aggregate history (timeframe={timeframe})...")
            await self.api.portfolio_history(timeframe)
            sub_id, sub_params, response = await self.api.recv()
            await self.api.unsubscribe(sub_id)
            
            # Response should contain historical data points
            # Expected format: {aggregates: [{time, value, invested}, ...]}
            aggregates = response.get('aggregates', [])
            log.info(f"Got {len(aggregates)} aggregate history points")
            
            history = []
            for agg in aggregates:
                ts = agg.get('time', agg.get('timestamp', ''))
                if ts:
                    # Convert timestamp to date string
                    date_str = ts[:10] if len(ts) >= 10 else ts
                    history.append({
                        'date': date_str,
                        'value': float(agg.get('close', agg.get('value', 0))),
                        'invested': float(agg.get('invested', agg.get('averageBuyIn', 0))),
                    })
            
            return history
        except Exception as e:
            log.error(f"Error fetching portfolio history: {e}")
            return []

    async def _fetch_position_history(self, isin: str, timeframe: str = "max") -> List[Dict]:
        """Fetch price history for a single position/instrument.
        
        Uses the aggregateHistory API to get historical prices for an ISIN.
        NOTE: This is unreliable - many instruments fail. Use _build_position_histories_from_yahoo instead.
        """
        if not self.api or not self.is_connected:
            log.error("Cannot fetch position history - not connected")
            return []
        
        try:
            log.info(f"Fetching history for {isin}...")
            await self.api.performance_history(isin, timeframe, exchange="LSX")
            sub_id, sub_params, response = await self.api.recv()
            await self.api.unsubscribe(sub_id)
            
            aggregates = response.get('aggregates', response.get('expectedHistoryLight', []))
            log.info(f"Got {len(aggregates)} history points for {isin}")
            
            history = []
            for agg in aggregates:
                ts = agg.get('time', agg.get('date', ''))
                if ts:
                    date_str = ts[:10] if len(ts) >= 10 else ts
                    # Price data - close price
                    close_price = float(agg.get('close', agg.get('price', 0)))
                    history.append({
                        'date': date_str,
                        'price': close_price,
                    })
            
            return history
        except Exception as e:
            log.error(f"Error fetching history for {isin}: {e}")
            return []

    def _build_position_histories_from_transactions(
        self, transactions: List[Dict], positions: List[Dict]
    ) -> Dict[str, Dict]:
        """Build per-position price histories using TR transaction data.
        
        PRIMARY METHOD: Uses actual execution prices from transactions.
        - 100% coverage (crypto, bonds, small caps, everything)
        - No external API calls
        - Already in EUR
        
        Returns:
            Dict of {isin: {history: [{date, price}], quantity, instrumentType, name}}
        """
        from components.portfolio_history import (
            extract_isin_from_icon,
            get_prices_from_transactions,
            interpolate_prices,
            set_isin_mappings,
        )
        
        log.info("Building position histories from transaction prices (PRIMARY method)...")
        
        # Set up ISIN mappings from current positions (handles bonds, ISIN changes)
        set_isin_mappings(positions)
        
        # Extract prices from transactions (now with position context)
        isin_prices = get_prices_from_transactions(transactions, positions)
        
        # Build position lookup
        pos_lookup = {p.get('isin', ''): p for p in positions}
        isin_to_name = {p.get('isin', ''): p.get('name', '') for p in positions}
        
        # Buy/sell transaction subtitles (German)
        BUY_SUBTITLES = {'Kauforder', 'Sparplan ausgeführt', 'Limit-Buy-Order', 'Bonusaktien', 'Tausch'}
        SELL_SUBTITLES = {'Verkaufsorder', 'Limit-Sell-Order', 'Stop-Sell-Order'}
        
        # Find all ISINs that have transactions and collect dates
        isins_with_transactions = set()
        all_dates = set()
        
        for txn in transactions:
            subtitle = txn.get("subtitle", "")
            icon = txn.get("icon", "")
            timestamp = txn.get("timestamp", "")
            
            if not timestamp:
                continue
            
            isin = extract_isin_from_icon(icon)
            if not isin:
                continue
            
            if subtitle in BUY_SUBTITLES or subtitle in SELL_SUBTITLES:
                isins_with_transactions.add(isin)
                try:
                    date = datetime.fromisoformat(timestamp.replace("+0000", "+00:00")).replace(tzinfo=None)
                    all_dates.add(date.date())
                except:
                    pass
        
        if not isins_with_transactions or not all_dates:
            return {}
        
        # Generate history dates (weekly + transaction dates + today)
        start_date = min(all_dates)
        end_date = datetime.now().date()
        
        history_dates = set()
        current = start_date
        while current <= end_date:
            history_dates.add(current)
            current += timedelta(days=7)  # Weekly for smoother charts
        
        history_dates.update(all_dates)
        history_dates.add(end_date)
        sorted_dates = sorted(history_dates)
        date_strs = [d.strftime("%Y-%m-%d") for d in sorted_dates]
        
        # Build position histories
        position_histories = {}
        
        for isin in isins_with_transactions:
            name = isin_to_name.get(isin, isin)
            pos = pos_lookup.get(isin, {})
            
            # Get prices for this ISIN
            known_prices = isin_prices.get(isin, {})
            if not known_prices:
                continue
            
            # Interpolate prices for all dates
            prices = interpolate_prices(known_prices, date_strs)
            
            if prices:
                # Build price history list
                price_history = []
                for date_str in sorted(prices.keys()):
                    price = prices.get(date_str)
                    if price and price > 0:
                        price_history.append({
                            'date': date_str,
                            'price': price,
                        })
                
                if price_history:
                    position_histories[isin] = {
                        'history': price_history,
                        'quantity': pos.get('quantity', 0),
                        'instrumentType': pos.get('instrumentType', ''),
                        'name': name,
                    }
        
        log.info(f"Built position histories for {len(position_histories)} instruments from transaction prices")
        return position_histories

    def _build_position_histories_from_yahoo(
        self, transactions: List[Dict], positions: List[Dict]
    ) -> Dict[str, Dict]:
        """Build per-position price histories using Yahoo Finance.
        
        FALLBACK METHOD: Only used if transaction-based approach fails.
        
        Returns:
            Dict of {isin: {history: [{date, price}], quantity, instrumentType, name}}
        """
        from components.portfolio_history import (
            extract_isin_from_icon,
            get_prices_for_dates,
        )
        
        # Build position lookup
        pos_lookup = {p.get('isin', ''): p for p in positions}
        isin_to_name = {p.get('isin', ''): p.get('name', '') for p in positions}
        
        # Buy/sell transaction subtitles (German)
        BUY_SUBTITLES = {'Kauforder', 'Sparplan ausgeführt', 'Limit-Buy-Order', 'Bonusaktien', 'Tausch'}
        SELL_SUBTITLES = {'Verkaufsorder', 'Limit-Sell-Order', 'Stop-Sell-Order'}
        
        # Find all ISINs that have transactions
        isins_with_transactions = set()
        all_dates = set()
        
        for txn in transactions:
            subtitle = txn.get("subtitle", "")
            icon = txn.get("icon", "")
            timestamp = txn.get("timestamp", "")
            
            if not timestamp:
                continue
            
            isin = extract_isin_from_icon(icon)
            if not isin:
                continue
            
            if subtitle in BUY_SUBTITLES or subtitle in SELL_SUBTITLES:
                isins_with_transactions.add(isin)
                try:
                    date = datetime.fromisoformat(timestamp.replace("+0000", "+00:00")).replace(tzinfo=None)
                    all_dates.add(date.date())
                except:
                    pass
        
        if not isins_with_transactions or not all_dates:
            return {}
        
        # Generate history dates (monthly + transaction dates + today)
        start_date = min(all_dates)
        end_date = datetime.now().date()
        
        history_dates = set()
        current = start_date.replace(day=1)
        while current <= end_date:
            history_dates.add(current)
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        
        history_dates.update(all_dates)
        history_dates.add(end_date)
        sorted_dates = sorted(history_dates)
        
        # Fetch prices for each ISIN
        position_histories = {}
        
        for idx, isin in enumerate(isins_with_transactions):
            name = isin_to_name.get(isin, isin)
            pos = pos_lookup.get(isin, {})
            
            log.info(f"[{idx+1}/{len(isins_with_transactions)}] Fetching prices for {name}...")
            
            dates_as_dt = [datetime.combine(d, datetime.min.time()) for d in sorted_dates]
            prices = get_prices_for_dates(isin, name, dates_as_dt)
            
            if prices:
                # Build price history list
                price_history = []
                for date_str in sorted(prices.keys()):
                    price = prices.get(date_str)
                    if price and price > 0:
                        price_history.append({
                            'date': date_str,
                            'price': price,
                        })
                
                if price_history:
                    position_histories[isin] = {
                        'history': price_history,
                        'quantity': pos.get('quantity', 0),
                        'instrumentType': pos.get('instrumentType', ''),
                        'name': name,
                    }
            else:
                log.warning(f"  No prices available for {name}")
        
        return position_histories

    def _build_holdings_timeline(
        self, 
        transactions: List[Dict],
        current_positions: List[Dict]
    ) -> Dict[str, Dict[str, float]]:
        """Build a timeline of holdings: how many shares of each ISIN on each date.
        
        CRITICAL: This walks FORWARD through time, starting from empty holdings.
        See docs/SPECIFICATION.md "CRITICAL DECISIONS" section.
        
        Algorithm:
        1. Start with EMPTY holdings (we owned nothing before first transaction)
        2. Sort transactions by date ASCENDING (oldest first)
        3. For each transaction:
           - Buy: add shares to holdings[isin]
           - Sell: subtract shares from holdings[isin]
        4. Record quantity at each date with a change
        5. RECONCILIATION: Compare calculated vs actual holdings and apply adjustment
           - Stock splits: Apply multiplier to all historical holdings
           - Transfers-in with no transactions: Add position from first known date
        
        Args:
            transactions: List of transactions with 'shares' field populated
            current_positions: Current portfolio positions (ground truth)
            
        Returns:
            {isin: {date_str: quantity}} - holdings at end of each date
        """
        from components.portfolio_history import extract_isin_from_icon, set_isin_mappings
        
        # Set up ISIN mappings from current positions (handles bonds, ISIN changes)
        set_isin_mappings(current_positions)
        
        # Build lookup for current positions (to identify bonds)
        pos_lookup = {p.get('isin', ''): p for p in current_positions}
        
        # Transaction subtitles for buys and sells
        # Include Fusion (merger) and Tausch (exchange) as buys
        BUY_SUBTITLES = {'Kauforder', 'Sparplan ausgeführt', 'Limit-Buy-Order', 
                         'Bonusaktien', 'Aktiensplit', 'Spin-off', 'Fusion', 'Tausch'}
        SELL_SUBTITLES = {'Verkaufsorder', 'Limit-Sell-Order', 'Stop-Sell-Order', 
                          'Reverse Split'}
        
        # Collect all share changes: [(date, isin, delta)]
        share_changes: List[Tuple[str, str, float]] = []
        
        for txn in transactions:
            subtitle = txn.get('subtitle', '')
            icon = txn.get('icon', '')
            title = txn.get('title', '')  # For name-based ISIN lookup
            timestamp = txn.get('timestamp', '')
            shares = txn.get('shares')
            amount = txn.get('amount')
            
            if not timestamp:
                continue
            
            date_str = timestamp[:10]
            isin = extract_isin_from_icon(icon, title)  # Pass title for name-based lookup
            if not isin:
                continue
            
            # Handle bonds: they have shares=None but we can use amount as nominal value
            # Bonds are identified by 'bondissuer' in icon or instrumentType='bond'
            is_bond = 'bondissuer' in str(icon) or pos_lookup.get(isin, {}).get('instrumentType') == 'bond'
            
            if shares is not None:
                shares = float(shares)
            elif is_bond and amount is not None and subtitle in BUY_SUBTITLES:
                # For bonds: the amount (negative for purchase) approximates nominal value
                # Bond "quantity" in TR is the nominal value (e.g., 10543.18 EUR)
                shares = abs(float(amount))
                log.info(f"Bond {title}: using amount {shares:.2f} as nominal value")
            elif is_bond and amount is not None and subtitle in SELL_SUBTITLES:
                shares = abs(float(amount))
            else:
                continue  # Skip if no shares info
            
            if subtitle in BUY_SUBTITLES:
                share_changes.append((date_str, isin, shares))
            elif subtitle in SELL_SUBTITLES:
                share_changes.append((date_str, isin, -shares))
        
        if not share_changes:
            log.warning("No share changes found in transactions")
            # Fall back to current positions for today only
            today = datetime.now().strftime('%Y-%m-%d')
            timeline = {}
            for pos in current_positions:
                isin = pos.get('isin', '')
                qty = pos.get('quantity', 0)
                if isin and qty > 0:
                    timeline[isin] = {today: qty}
            return timeline
        
        # Sort by date ASCENDING (oldest first) - FORWARD walk
        share_changes.sort(key=lambda x: x[0])
        
        # Get all unique dates plus today
        all_dates = sorted(set(date for date, _, _ in share_changes))
        today = datetime.now().strftime('%Y-%m-%d')
        if today not in all_dates:
            all_dates.append(today)
            all_dates.sort()
        
        # Group changes by date: {date: {isin: total_delta}}
        changes_by_date: Dict[str, Dict[str, float]] = {}
        for date_str, isin, delta in share_changes:
            if date_str not in changes_by_date:
                changes_by_date[date_str] = {}
            changes_by_date[date_str][isin] = changes_by_date[date_str].get(isin, 0) + delta
        
        # Walk FORWARD: start from empty, accumulate holdings
        current_holdings: Dict[str, float] = {}  # {isin: quantity}
        holdings_timeline: Dict[str, Dict[str, float]] = {}  # {isin: {date: quantity}}
        
        for date_str in all_dates:
            # Apply changes for this date
            if date_str in changes_by_date:
                for isin, delta in changes_by_date[date_str].items():
                    old_qty = current_holdings.get(isin, 0)
                    new_qty = max(0, old_qty + delta)  # Can't go negative
                    current_holdings[isin] = new_qty
            
            # Record current holdings at end of this date
            for isin, qty in current_holdings.items():
                if qty > 0:
                    if isin not in holdings_timeline:
                        holdings_timeline[isin] = {}
                    holdings_timeline[isin][date_str] = qty
        
        # RECONCILIATION: Compare final holdings to current_positions (ground truth from TR)
        current_from_tr: Dict[str, float] = {}
        isin_to_name: Dict[str, str] = {}
        for pos in current_positions:
            isin = pos.get('isin', '')
            qty = pos.get('quantity', 0)
            name = pos.get('name', isin)
            if isin and qty > 0:
                current_from_tr[isin] = qty
                isin_to_name[isin] = name
        
        # Identify mismatches and categorize them
        mismatches = []
        adjustments_needed = []
        
        for isin in set(current_holdings.keys()) | set(current_from_tr.keys()):
            calculated = current_holdings.get(isin, 0)
            actual = current_from_tr.get(isin, 0)
            
            if abs(calculated - actual) > 0.001:  # Allow small float errors
                name = isin_to_name.get(isin, isin)
                mismatches.append({
                    'isin': isin,
                    'name': name,
                    'calculated': calculated,
                    'actual': actual,
                })
                
                if calculated > 0 and actual > 0:
                    # Case 1: Both exist but differ - likely stock split
                    # Apply ratio to all historical holdings
                    ratio = actual / calculated
                    adjustments_needed.append({
                        'isin': isin,
                        'type': 'ratio',
                        'ratio': ratio,
                        'reason': f"Stock split/adjustment (ratio {ratio:.2f}x)",
                    })
                elif calculated == 0 and actual > 0:
                    # Case 2: Position exists but no transactions - transfer in OR ISIN change
                    # Check if there's a "ghost" position with same quantity under different ISIN
                    # (ISIN change from corporate restructuring)
                    matched_old_isin = None
                    for old_isin, old_qty in current_holdings.items():
                        if old_isin not in current_from_tr and abs(old_qty - actual) < 0.01:
                            # Found a match - old ISIN has same quantity as new position
                            matched_old_isin = old_isin
                            break
                    
                    if matched_old_isin:
                        # ISIN change detected - transfer history from old to new
                        adjustments_needed.append({
                            'isin': isin,
                            'type': 'isin_change',
                            'old_isin': matched_old_isin,
                            'quantity': actual,
                            'reason': f"ISIN changed from {matched_old_isin}",
                        })
                    else:
                        # True transfer-in with no prior transactions
                        adjustments_needed.append({
                            'isin': isin,
                            'type': 'add_position',
                            'quantity': actual,
                            'reason': "Transfer-in (no purchase transactions)",
                        })
                elif calculated > 0 and actual == 0:
                    # Case 3: Calculated holdings but position is gone - sold/transferred out
                    # OR could be an old ISIN that got replaced (handled by isin_change above)
                    pass
        
        # Log mismatches before adjustment
        if mismatches:
            log.info(f"Holdings reconciliation needed ({len(mismatches)} positions):")
            for m in mismatches[:5]:
                log.info(f"  {m['isin']} ({m['name']}): calculated={m['calculated']:.4f}, actual={m['actual']:.4f}")
            if len(mismatches) > 5:
                log.info(f"  ... and {len(mismatches) - 5} more")
        
        # Apply adjustments
        for adj in adjustments_needed:
            isin = adj['isin']
            
            if adj['type'] == 'ratio':
                # Apply ratio to all historical holdings for this ISIN
                ratio = adj['ratio']
                if isin in holdings_timeline:
                    for date_str in holdings_timeline[isin]:
                        holdings_timeline[isin][date_str] *= ratio
                    log.info(f"  Applied {ratio:.2f}x ratio to {isin} ({adj['reason']})")
                # Update current_holdings too
                if isin in current_holdings:
                    current_holdings[isin] *= ratio
            
            elif adj['type'] == 'isin_change':
                # Transfer history from old ISIN to new ISIN
                old_isin = adj['old_isin']
                if old_isin in holdings_timeline:
                    holdings_timeline[isin] = holdings_timeline.pop(old_isin)
                    log.info(f"  Transferred history from {old_isin} to {isin} ({adj['reason']})")
                # Update current_holdings
                if old_isin in current_holdings:
                    current_holdings[isin] = current_holdings.pop(old_isin)
                    
            elif adj['type'] == 'add_position':
                # Add position starting from first date in portfolio (approximation)
                quantity = adj['quantity']
                # Find earliest date in the timeline
                if all_dates:
                    first_date = all_dates[0]
                    if isin not in holdings_timeline:
                        holdings_timeline[isin] = {}
                    # Add position from first date onwards
                    for date_str in all_dates:
                        holdings_timeline[isin][date_str] = quantity
                    current_holdings[isin] = quantity
                    log.info(f"  Added {quantity:.4f} shares of {isin} from {first_date} ({adj['reason']})")
        
        # Final validation after adjustments
        final_mismatches = []
        for isin in set(current_holdings.keys()) | set(current_from_tr.keys()):
            calculated = current_holdings.get(isin, 0)
            actual = current_from_tr.get(isin, 0)
            if abs(calculated - actual) > 0.001 and actual > 0:  # Only care about current positions
                final_mismatches.append(f"{isin}: calculated={calculated:.4f}, actual={actual:.4f}")
        
        if final_mismatches:
            log.warning(f"⚠️ {len(final_mismatches)} positions still mismatched after reconciliation")
        else:
            log.info(f"✅ Holdings reconciliation complete - all current positions match!")
        
        log.info(f"Built holdings timeline for {len(holdings_timeline)} ISINs over {len(all_dates)} dates")
        
        return holdings_timeline
    
    def _validate_sync_completeness(
        self,
        transactions: List[Dict],
        positions: List[Dict]
    ) -> Dict[str, Any]:
        """Validate that sync produced complete and plausible data.
        
        Returns a validation report dict with:
        - is_valid: bool - True if data looks good
        - issues: List[str] - Any problems found
        - stats: Dict - Statistics about the data
        """
        from components.portfolio_history import extract_isin_from_icon
        
        issues = []
        stats = {
            'total_transactions': len(transactions),
            'total_positions': len(positions),
            'trades_with_shares': 0,
            'trades_without_shares': 0,
            'positions_matched': 0,
            'positions_mismatched': 0,
        }
        
        # Check 1: Count trades with/without shares
        TRADE_SUBTITLES = {
            'Kauforder', 'Sparplan ausgeführt', 'Limit-Buy-Order',
            'Verkaufsorder', 'Limit-Sell-Order', 'Stop-Sell-Order',
            'Bonusaktien', 'Aktiensplit', 'Reverse Split', 'Tausch', 'Spin-off'
        }
        
        trades = [t for t in transactions if t.get('subtitle') in TRADE_SUBTITLES]
        with_shares = [t for t in trades if t.get('shares') and t.get('shares') > 0]
        without_shares = [t for t in trades if not t.get('shares') or t.get('shares') == 0]
        
        stats['trades_with_shares'] = len(with_shares)
        stats['trades_without_shares'] = len(without_shares)
        
        if len(without_shares) > 0:
            pct = len(without_shares) / len(trades) * 100 if trades else 0
            if pct > 20:
                issues.append(f"{len(without_shares)} trades ({pct:.0f}%) missing share data")
        
        # Check 2: Calculate shares per ISIN and compare to positions
        BUY_SUBTITLES = {'Kauforder', 'Sparplan ausgeführt', 'Limit-Buy-Order', 
                        'Bonusaktien', 'Aktiensplit', 'Spin-off'}
        SELL_SUBTITLES = {'Verkaufsorder', 'Limit-Sell-Order', 'Stop-Sell-Order', 
                         'Reverse Split'}
        
        calculated: Dict[str, float] = {}
        for txn in transactions:
            subtitle = txn.get('subtitle', '')
            shares = txn.get('shares', 0) or 0
            isin = extract_isin_from_icon(txn.get('icon', ''))
            if not isin or not shares:
                continue
            
            if subtitle in BUY_SUBTITLES:
                calculated[isin] = calculated.get(isin, 0) + shares
            elif subtitle in SELL_SUBTITLES:
                calculated[isin] = calculated.get(isin, 0) - shares
        
        actual: Dict[str, float] = {p.get('isin'): p.get('quantity', 0) for p in positions}
        
        for isin in set(calculated.keys()) | set(actual.keys()):
            calc_qty = calculated.get(isin, 0)
            actual_qty = actual.get(isin, 0)
            if abs(calc_qty - actual_qty) < 0.01:
                stats['positions_matched'] += 1
            else:
                stats['positions_mismatched'] += 1
        
        if stats['positions_mismatched'] > 0:
            total = stats['positions_matched'] + stats['positions_mismatched']
            pct = stats['positions_mismatched'] / total * 100 if total else 0
            if pct > 30:
                issues.append(f"{stats['positions_mismatched']} positions ({pct:.0f}%) have mismatched quantities")
        
        # Summary
        is_valid = len(issues) == 0
        
        log.info(f"=== Sync Validation ===")
        log.info(f"  Transactions: {stats['total_transactions']}")
        log.info(f"  Trades with shares: {stats['trades_with_shares']}/{len(trades)}")
        log.info(f"  Positions matched: {stats['positions_matched']}/{stats['positions_matched'] + stats['positions_mismatched']}")
        
        if issues:
            log.warning(f"⚠️ Validation issues:")
            for issue in issues:
                log.warning(f"  - {issue}")
        else:
            log.info(f"✅ Sync validation passed!")
        
        return {
            'is_valid': is_valid,
            'issues': issues,
            'stats': stats
        }

    def _build_cash_timeline(
        self, 
        transactions: List[Dict],
        current_cash: float
    ) -> Dict[str, float]:
        """Build a timeline of cash balance over time.
        
        Cash changes from:
        - INFLOWS: Deposits (Einzahlung), P2P received (Fertig), Dividends, Interest, Sales
        - OUTFLOWS: Withdrawals (Gesendet), Purchases
        
        Args:
            transactions: All timeline transactions
            current_cash: Current cash balance from TR (for reconciliation)
            
        Returns:
            Dict mapping date -> cash balance on that date
        """
        from components.portfolio_history import extract_isin_from_icon
        
        if not transactions:
            return {}
        
        # Cash flow events: (date, amount_change)
        cash_flows: List[Tuple[str, float]] = []
        
        # Subtitles that increase cash
        CASH_INFLOWS = {
            'Bardividende', 'Dividende',  # Dividends
            'Zinszahlung', 'Festzins',    # Interest
            'Verkaufsorder', 'Limit-Sell-Order', 'Stop-Sell-Order',  # Sales
        }
        
        # Subtitles that decrease cash (purchases)
        CASH_OUTFLOWS = {
            'Kauforder', 'Sparplan ausgeführt', 'Limit-Buy-Order',
        }
        
        for txn in transactions:
            ts = txn.get('timestamp', '')
            if not ts:
                continue
            
            date_str = ts[:10]
            title = txn.get('title', '') or ''
            subtitle = txn.get('subtitle', '') or ''
            amount = txn.get('amount')
            
            if amount is None:
                continue
            
            amount = float(amount)
            
            # === Deposits and withdrawals ===
            if title == 'Einzahlung' and amount > 0:
                cash_flows.append((date_str, amount))  # Deposit adds cash
            elif subtitle == 'Fertig' and amount > 0:
                cash_flows.append((date_str, amount))  # P2P received adds cash
            elif subtitle == 'Gesendet' and amount < 0:
                cash_flows.append((date_str, amount))  # Withdrawal removes cash
            elif title == 'Zinsen' and amount > 0:
                cash_flows.append((date_str, amount))  # Interest adds cash
            
            # === Dividends, interest, coupons (adds cash) ===
            elif subtitle in CASH_INFLOWS and amount > 0:
                cash_flows.append((date_str, amount))
            
            # === Purchases (removes cash) ===
            elif subtitle in CASH_OUTFLOWS and amount < 0:
                cash_flows.append((date_str, amount))  # Amount is negative for purchases
            
            # === Taxes (reduces cash) ===
            elif subtitle == 'Vorabpauschale' and amount < 0:
                cash_flows.append((date_str, amount))  # Tax payment reduces cash
        
        if not cash_flows:
            return {}
        
        # Sort by date and build cumulative cash balance
        cash_flows.sort(key=lambda x: x[0])
        
        # Group by date
        daily_changes: Dict[str, float] = {}
        for date_str, change in cash_flows:
            daily_changes[date_str] = daily_changes.get(date_str, 0.0) + change
        
        # Build cumulative timeline
        sorted_dates = sorted(daily_changes.keys())
        cash_timeline: Dict[str, float] = {}
        running_cash = 0.0
        
        for date_str in sorted_dates:
            running_cash += daily_changes[date_str]
            cash_timeline[date_str] = running_cash
        
        # Reconcile with current cash balance
        # The difference is accumulated fees, tax withholdings, etc.
        if cash_timeline and current_cash > 0:
            calculated_cash = list(cash_timeline.values())[-1]
            if abs(calculated_cash - current_cash) > 1:  # More than €1 difference
                # Calculate adjustment factor and apply retroactively
                # This accounts for fees/taxes we don't track individually
                adjustment = current_cash - calculated_cash
                log.info(f"Cash timeline adjustment: calculated={calculated_cash:.2f}, "
                        f"actual={current_cash:.2f}, adjustment={adjustment:.2f}")
        
        log.info(f"Built cash timeline: {len(cash_timeline)} dates, "
                f"final balance: {running_cash:.2f} EUR")
        
        return cash_timeline

    def _build_history_with_market_values(
        self, 
        transactions: List[Dict], 
        position_histories: Dict[str, Dict],
        invested_series: Dict[str, float],
        current_total: float,
        current_positions: List[Dict],
        current_cash: float = 0.0
    ) -> List[Dict]:
        """Build portfolio history with actual market values.
        
        STEP-BY-STEP APPROACH:
        1. Build holdings timeline: quantity of each ISIN on each date
        2. Build cash timeline: cash balance on each date
        3. For each date: value = sum(quantity[isin][date] × price[isin][date]) + cash[date]
        4. Use invested_series for the "invested" (added capital) line
        
        Args:
            transactions: All timeline transactions (with 'shares' field)
            position_histories: {isin: {history: [{date, price}], ...}} from transactions
            invested_series: {date: cumulative_invested} from deposits
            current_total: Current live portfolio value (from TR, includes cash)
            current_positions: Current portfolio positions with quantities
            current_cash: Current cash balance from TR
            
        Returns:
            List of {date, invested, value} dicts sorted by date
        """
        if not position_histories:
            log.warning("No position histories - cannot calculate market values")
            return self._build_history_from_transactions(transactions, current_total)
        
        # STEP 1: Build holdings timeline
        holdings_timeline = self._build_holdings_timeline(transactions, current_positions)
        
        # STEP 1b: Build cash timeline
        cash_timeline = self._build_cash_timeline(transactions, current_cash)
        
        # STEP 2: Build price lookup from position_histories
        # {isin: {date_str: price}}
        price_lookup: Dict[str, Dict[str, float]] = {}
        isin_names: Dict[str, str] = {}
        
        for isin, data in position_histories.items():
            price_lookup[isin] = {}
            isin_names[isin] = data.get('name', isin)
            for point in data.get('history', []):
                price_lookup[isin][point['date']] = point['price']
        
        # STEP 3: Determine the date range
        # Start from the FIRST deposit (when the user actually started investing)
        # Don't show history for dates before the first capital was added
        if not invested_series:
            log.warning("No invested series - cannot determine start date")
            return self._build_history_from_transactions(transactions, current_total)
        
        first_deposit_date = min(invested_series.keys())
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Collect all dates from holdings and prices, but only AFTER first deposit
        all_dates = set()
        
        # Add invested series dates
        for date in invested_series.keys():
            if date >= first_deposit_date:
                all_dates.add(date)
        
        # Add holdings timeline dates (only after first deposit)
        for isin in holdings_timeline:
            for date in holdings_timeline[isin].keys():
                if date >= first_deposit_date:
                    all_dates.add(date)
        
        # Add price dates (only after first deposit)
        for isin in price_lookup:
            for date in price_lookup[isin].keys():
                if date >= first_deposit_date:
                    all_dates.add(date)
        
        # Add cash timeline dates (only after first deposit)
        for date in cash_timeline.keys():
            if date >= first_deposit_date:
                all_dates.add(date)
        
        all_dates.add(today)
        sorted_dates = sorted(all_dates)
        
        if not sorted_dates:
            return self._build_history_from_transactions(transactions, current_total)
        
        log.info(f"Calculating history from {first_deposit_date} to {today} ({len(sorted_dates)} dates)")
        
        # STEP 4: Calculate value for each date
        history = []
        
        for date_str in sorted_dates:
            # Get invested amount (cumulative deposits up to this date)
            invested = 0.0
            for inv_date in sorted(invested_series.keys()):
                if inv_date <= date_str:
                    invested = invested_series[inv_date]
                else:
                    break
            
            # Get cash balance on this date (or nearest earlier)
            cash_balance = 0.0
            for cash_date in sorted(cash_timeline.keys()):
                if cash_date <= date_str:
                    cash_balance = cash_timeline[cash_date]
                else:
                    break
            
            # Calculate market value: sum(quantity × price) for each position
            securities_value = 0.0
            missing_prices = []
            
            for isin in set(holdings_timeline.keys()) | set(price_lookup.keys()):
                # Get quantity on this date
                quantity = 0.0
                if isin in holdings_timeline:
                    for h_date in sorted(holdings_timeline[isin].keys()):
                        if h_date <= date_str:
                            quantity = holdings_timeline[isin][h_date]
                        else:
                            break
                
                if quantity <= 0:
                    continue
                
                # Get price on this date (or nearest earlier)
                price = None
                if isin in price_lookup:
                    for p_date in sorted(price_lookup[isin].keys()):
                        if p_date <= date_str:
                            price = price_lookup[isin][p_date]
                        else:
                            break
                
                if price and price > 0:
                    position_value = quantity * price
                    securities_value += position_value
                else:
                    missing_prices.append(isin_names.get(isin, isin))
            
            # Total portfolio value = securities + cash
            # Cash should be positive (it's an asset)
            total_value = securities_value + max(0, cash_balance)
            
            # Only add if we have meaningful data
            if invested > 0 or total_value > 0:
                history.append({
                    'date': date_str,
                    'invested': round(invested, 2),
                    'value': round(total_value, 2) if total_value > 0 else round(invested, 2),
                })
        
        # STEP 5: Ensure today has the accurate live value from TR
        if history:
            if history[-1]['date'] == today:
                history[-1]['value'] = round(current_total, 2)
            else:
                history.append({
                    'date': today,
                    'invested': history[-1]['invested'] if history else 0,
                    'value': round(current_total, 2),
                })
        
        log.info(f"Built history with market values: {len(history)} data points")
        
        # Debug: show sample values
        if history:
            samples = history[:2] + history[-2:] if len(history) > 4 else history
            for h in samples:
                log.info(f"  History sample: {h['date']}: invested={h['invested']:,.2f}, value={h['value']:,.2f}")
        
        return history

    def _build_history_from_transactions(self, transactions: List[Dict], current_total: float) -> List[Dict]:
        """Build portfolio value history from transactions.
        
        Since TR doesn't provide historical portfolio values, we reconstruct them
        by tracking cash flows (deposits, withdrawals, interest, dividends) over time.
        
        Transaction types are identified by 'title' and 'subtitle' fields:
        - title='Einzahlung' (deposit) - positive cash inflow
        - title='Zinsen' (interest) - positive cash inflow  
        - subtitle='Fertig' with positive amount - completed transfer inflow
        - subtitle='Bardividende' or 'Dividende' - positive cash inflow
        - subtitle='Gesendet' with negative amount - outbound transfer
        """
        if not transactions:
            return []
        
        # Group cash inflows/outflows by date
        daily_flows: Dict[str, float] = {}
        
        for txn in transactions:
            ts = txn.get('timestamp', '')
            if not ts:
                continue
            
            date_str = ts[:10]  # YYYY-MM-DD
            title = txn.get('title', '') or ''
            subtitle = txn.get('subtitle', '') or ''
            amount = txn.get('amount')
            
            if amount is None:
                continue
            
            amount = float(amount)
            
            # Determine if this is a cash flow event
            flow = 0.0
            
            # Deposits - positive amounts with Einzahlung title
            if title == 'Einzahlung' and amount > 0:
                flow = amount
            # Completed transfers (deposits from bank) - subtitle='Fertig' with positive amount
            elif subtitle == 'Fertig' and amount > 0:
                flow = amount
            # Interest payments - positive amounts with Zinsen title
            elif title == 'Zinsen' and amount > 0:
                flow = amount
            # Dividends - check subtitle
            elif subtitle in {'Bardividende', 'Dividende'} and amount > 0:
                flow = amount
            # Withdrawals - 'Gesendet' (sent) with negative amounts
            elif subtitle == 'Gesendet' and amount < 0:
                flow = amount  # Already negative
            
            if flow != 0:
                daily_flows[date_str] = daily_flows.get(date_str, 0) + flow
        
        if not daily_flows:
            # No deposit/withdrawal transactions found, return minimal history
            log.warning("No cash flow transactions found - using minimal history")
            today = datetime.now().strftime('%Y-%m-%d')
            return [{'date': today, 'value': current_total}]
        
        # Sort dates ascending
        sorted_dates = sorted(daily_flows.keys())
        
        # Build history: start from first date and accumulate
        # We'll show cumulative cash inflows over time
        history = []
        cumulative = 0.0
        
        for date_str in sorted_dates:
            cumulative += daily_flows[date_str]
            history.append({
                'date': date_str,
                'invested': cumulative,
                'value': cumulative,  # We don't have market values, so use invested
            })
        
        # Add current value as latest point
        today = datetime.now().strftime('%Y-%m-%d')
        if not history or history[-1]['date'] != today:
            history.append({
                'date': today,
                'invested': cumulative,
                'value': current_total,
            })
        else:
            # Update today's value with actual current value
            history[-1]['value'] = current_total
        
        log.info(f"Built history with {len(history)} data points from {len(daily_flows)} cash flow days, total deposited: {cumulative:.2f}")
        
        return history
    
    def _build_invested_series_from_transactions(self, transactions: List[Dict]) -> Dict[str, float]:
        """Build a date -> cumulative invested amount mapping from transactions.
        
        This gives us accurate invested amounts at each date, computed from actual
        deposit/withdrawal transactions. TR's aggregate history often returns 0 or
        incorrect invested values, so we use this as the source of truth.
        
        CAPITAL INFLOWS (counted as positive):
        - Einzahlung: Bank deposits (title='Einzahlung', amount > 0)
        - Fertig transfers: Completed P2P incoming (subtitle='Fertig', amount > 0)
        - Old-style P2P: Historical transfers with person name as title (no subtitle, amount > 0)
        
        CAPITAL OUTFLOWS (counted as negative):
        - Gesendet: Bank withdrawals (subtitle='Gesendet', amount < 0)
        - Old-style P2P: Historical transfers with person name as title (no subtitle, amount < 0)
        
        NOT COUNTED as capital flows:
        - Dividends (Dividende, Bardividende) - returns on investment
        - Interest (Zinsen, Festzins, Zinszahlung) - returns
        - Tax corrections (Steuerkorrektur, Vorabpauschale)
        - Sales (Verkaufsorder, etc.) - internal portfolio movements
        - Purchases (Kauforder, Sparplan, etc.) - internal portfolio movements
        - Rejected transfers (Abgelehnt) - never completed
        
        Returns:
            Dict mapping date string (YYYY-MM-DD) to cumulative invested amount
        """
        if not transactions:
            return {}
        
        # Titles that represent system transactions, NOT capital flows
        # (even if they have no subtitle)
        non_capital_titles = {
            'Zinsen',           # Interest payments
            'Steuerkorrektur',  # Tax corrections
        }
        
        # Subtitles that are NOT capital flows
        non_capital_subtitles = {
            # Dividends and interest
            'Bardividende', 'Dividende', 
            'Festzins', 'Zinszahlung',
            # Internal portfolio operations
            'Verkaufsorder', 'Limit-Sell-Order', 'Stop-Sell-Order',
            'Kauforder', 'Limit-Buy-Order', 
            'Sparplan ausgeführt', 'Sparplan fehlgeschlagen',
            # Tax and adjustments
            'Vorabpauschale', 'Bonusaktien',
            # Failed/rejected transfers
            'Abgelehnt',
            # Corporate actions
            'Tausch', 'Fusion',
        }
        
        # Subtitles with variable suffixes (e.g., "2 % p.a.", "3,25 % p.a.")
        non_capital_subtitle_patterns = ['% p.a.', '1 % Bonus']
        
        # Build daily cash flows
        daily_flows = {}
        
        for txn in transactions:
            ts = txn.get('timestamp', '')
            if not ts:
                continue
            
            date_str = ts[:10]  # YYYY-MM-DD
            title = txn.get('title', '') or ''
            subtitle = txn.get('subtitle', '') or ''
            amount = txn.get('amount')
            
            if amount is None:
                continue
            
            amount = float(amount)
            flow = 0.0
            
            # Skip known non-capital titles
            if title in non_capital_titles:
                continue
            
            # Skip known non-capital subtitles
            if subtitle in non_capital_subtitles:
                continue
            
            # Skip pattern-based non-capital subtitles (interest rates, etc.)
            if any(pattern in subtitle for pattern in non_capital_subtitle_patterns):
                continue
            
            # === CAPITAL INFLOWS ===
            
            # 1. Bank deposits: title='Einzahlung', positive amount
            if title == 'Einzahlung' and amount > 0:
                flow = amount
            
            # 2. Completed P2P transfers: subtitle='Fertig', positive amount
            elif subtitle == 'Fertig' and amount > 0:
                flow = amount
            
            # 3. Old-style P2P transfers: no subtitle, positive amount, not a known system title
            # These are historical transfers (pre-2022) where the title is the sender's name
            # and there's no subtitle. They show up as positive cash inflows.
            elif not subtitle and amount > 0 and title not in non_capital_titles:
                # Additional check: title should look like a person name (has space or is not all caps)
                # System titles like "Zinsen" are filtered above, anything else is likely a P2P
                if ' ' in title or not title.isupper():
                    flow = amount
            
            # === CAPITAL OUTFLOWS ===
            
            # 4. Bank withdrawals: subtitle='Gesendet', negative amount
            elif subtitle == 'Gesendet' and amount < 0:
                flow = amount  # Already negative
            
            # 5. Old-style P2P outgoing: no subtitle, negative amount (sent to someone)
            elif not subtitle and amount < 0 and title not in non_capital_titles:
                if ' ' in title or not title.isupper():
                    flow = amount  # Already negative
            
            if flow != 0:
                daily_flows[date_str] = daily_flows.get(date_str, 0.0) + flow
        
        if not daily_flows:
            return {}
        
        # Sort dates and compute cumulative invested
        sorted_dates = sorted(daily_flows.keys())
        invested_series = {}
        cumulative = 0.0
        
        for date_str in sorted_dates:
            cumulative += daily_flows[date_str]
            invested_series[date_str] = cumulative
        
        log.info(f"Built invested series: {len(invested_series)} dates, "
                 f"final cumulative: {cumulative:,.2f} EUR")
        
        return invested_series
    
    def _merge_history_with_invested(self, history: List[Dict], invested_series: Dict[str, float]) -> List[Dict]:
        """Merge portfolio history with transaction-derived invested amounts.
        
        TR's aggregate history often returns incorrect invested values (0 or same as value).
        This function replaces those with accurate values computed from transactions.
        
        Args:
            history: List of {date, value, invested} from TR aggregate history
            invested_series: Dict mapping date -> cumulative invested from transactions
            
        Returns:
            History with corrected invested values
        """
        if not history or not invested_series:
            return history
        
        # Get sorted invested dates for interpolation
        invested_dates = sorted(invested_series.keys())
        if not invested_dates:
            return history
        
        # For each history point, find the most recent invested value
        for point in history:
            date_str = point.get('date', '')[:10]
            
            # Find most recent invested value on or before this date
            invested_value = None
            for inv_date in invested_dates:
                if inv_date <= date_str:
                    invested_value = invested_series[inv_date]
                else:
                    break
            
            # Only update if we found a value (keep original if before first transaction)
            if invested_value is not None:
                point['invested'] = invested_value
        
        return history
    
    def has_keyfile(self) -> bool:
        """Check if keyfile exists (needed for reconnect)."""
        return self._keyfile_path.exists()
    
    def get_encrypted_credentials(self, phone_no: str, pin: str) -> str:
        """Encrypt credentials for browser storage."""
        return encrypt_credentials(phone_no, pin)
    
    def set_credentials_from_encrypted(self, encrypted: str) -> bool:
        """Set credentials from encrypted browser storage."""
        phone, pin = decrypt_credentials(encrypted)
        if phone and pin:
            self.phone_no = phone
            self.pin = pin
            return True
        return False
    
    def clear_credentials(self):
        """Clear credentials and keyfile."""
        if self._keyfile_path.exists():
            self._keyfile_path.unlink()
        self.phone_no = None
        self.pin = None
        self.is_connected = False
        self.api = None
    
    async def _initiate_web_login(self, phone_no: str, pin: str) -> Dict[str, Any]:
        """
        Initiate the Trade Republic login - sends a 4-digit code to the TR app.

        Uses pytr's *device-reset* (app pairing) flow rather than the legacy
        web-login endpoint. Trade Republic disabled ``/api/v1/auth/web/login``
        (it now returns HTTP 405 with an empty body, which pytr would surface as
        the cryptic ``Expecting value: line 1 column 1`` JSON error). The
        device-reset flow is the one that's still live and, on completion, writes
        the keyfile that :meth:`_reconnect` depends on.
        """
        try:
            normalized = normalize_phone(phone_no)
            if not normalized:
                return {
                    "success": False,
                    "error": "Please enter your phone number in international format, e.g. +49 151 23456789.",
                }

            self.phone_no = normalized
            self.pin = pin

            # Create API instance
            self.api = TradeRepublicApi(
                phone_no=normalized,
                pin=pin,
                keyfile=str(self._keyfile_path)
            )

            # Pair this device (sends a 4-digit code to the TR app) - SYNC call.
            self.api.initiate_device_reset()

            return {
                "success": True,
                "message": "Verification code sent to your Trade Republic app.",
                "requires_code": True,
                "countdown": 60,
            }
        except Exception as e:
            log.error(f"TR login initiation failed: {e}")
            return {
                "success": False,
                "error": friendly_tr_error(e)
            }
    
    async def _complete_web_login(self, code: str) -> Dict[str, Any]:
        """
        Complete web login with the 4-digit verification code.
        Returns encrypted credentials for browser storage.
        """
        try:
            if not self.api:
                return {"success": False, "error": "No login in progress. Please start again."}

            code = (code or "").strip()
            if len(code) != 4 or not code.isdigit():
                return {"success": False, "error": "Please enter the 4-digit code from your TR app."}

            # Complete device pairing with the code. On success pytr writes the
            # keyfile; we then log in to obtain session tokens. Both are SYNC.
            self.api.complete_device_reset(code)

            if not self._keyfile_path.exists():
                # pytr only writes the keyfile on a 200 response, so a missing
                # keyfile means the code was wrong or expired.
                return {"success": False, "error": "The verification code was invalid or has expired. Please request a new code."}

            self.api.login()
            self.is_connected = True

            # Return encrypted credentials for browser storage
            encrypted_creds = None
            if self.phone_no and self.pin:
                encrypted_creds = self.get_encrypted_credentials(self.phone_no, self.pin)

            return {
                "success": True,
                "message": "Successfully connected to Trade Republic",
                "encrypted_credentials": encrypted_creds
            }
        except Exception as e:
            log.error(f"TR login completion failed: {e}")
            return {
                "success": False,
                "error": friendly_tr_error(e)
            }
    
    async def _fetch_portfolio(self) -> Dict[str, Any]:
        """Fetch portfolio data from TR."""
        try:
            if not self.api or not self.is_connected:
                return {"success": False, "error": "Not connected"}
            
            # Get compact portfolio (correct subscription type)
            # WebSocket connects automatically on first subscribe
            await self.api.compact_portfolio()
            sub_id, sub_params, portfolio_response = await self.api.recv()
            await self.api.unsubscribe(sub_id)
            
            log.info(f"Portfolio response: {portfolio_response}")
            
            # Get cash balance
            await self.api.cash()
            sub_id, sub_params, cash_response = await self.api.recv()
            await self.api.unsubscribe(sub_id)
            
            log.info(f"Cash response: {cash_response}")
            
            self.portfolio_data = portfolio_response
            self.cash_data = cash_response
            
            # Parse compact portfolio format
            # compactPortfolio returns: {netValue, positions: [{instrumentId, netSize, averageBuyIn, netValue}]}
            positions = portfolio_response.get('positions', [])
            net_value = portfolio_response.get('netValue', 0)
            
            # Cash might be in different format
            cash = 0
            if isinstance(cash_response, dict):
                cash = cash_response.get('value', cash_response.get('amount', 0))
            
            # Calculate totals from positions
            total_invested = sum(
                float(p.get('netSize', 0)) * float(p.get('averageBuyIn', 0)) 
                for p in positions
            )
            total_value = float(net_value) if net_value else sum(
                float(p.get('netValue', 0)) for p in positions
            )
            
            total_profit = total_value - total_invested
            total_profit_pct = (total_profit / total_invested * 100) if total_invested > 0 else 0
            
            return {
                "success": True,
                "data": {
                    "totalValue": total_value + cash,
                    "investedAmount": total_invested,
                    "cash": cash,
                    "totalProfit": total_profit,
                    "totalProfitPercent": total_profit_pct,
                    "positions": [
                        {
                            "name": p.get('name', p.get('instrumentId', 'Unknown')),
                            "isin": p.get('instrumentId', ''),
                            "quantity": float(p.get('netSize', 0)),
                            "averageBuyIn": float(p.get('averageBuyIn', 0)),
                            "value": float(p.get('netValue', 0)),
                            "profit": float(p.get('netValue', 0)) - (float(p.get('netSize', 0)) * float(p.get('averageBuyIn', 0))),
                        }
                        for p in positions
                    ]
                }
            }
        except Exception as e:
            log.error(f"Portfolio fetch failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _fetch_all_data(self) -> Dict[str, Any]:
        """Fetch all portfolio data with instrument names. Skip ticker prices (too slow)."""
        try:
            if not self.api or not self.is_connected:
                return {"success": False, "error": "Not connected"}

            log.info("Fetching compact portfolio...")
            
            # Get compact portfolio - handle async responses properly
            await self.api.compact_portfolio()
            sub_id, sub_params, portfolio_response = await self.api.recv()
            await self.api.unsubscribe(sub_id)
            
            # Check if we got the right response type
            if sub_params.get('type') != 'compactPortfolio':
                log.warning(f"Expected compactPortfolio, got {sub_params.get('type')}")
                # The response might be in the wrong order - check if it has positions
                if isinstance(portfolio_response, dict) and 'positions' in portfolio_response:
                    pass  # We got positions, use this
                else:
                    # Try to receive again
                    await self.api.compact_portfolio()
                    sub_id, sub_params, portfolio_response = await self.api.recv()
                    await self.api.unsubscribe(sub_id)
            
            log.info(f"Got portfolio with {len(portfolio_response.get('positions', []))} positions")
            
            # Get cash balance - TR returns an array: [{amount, currencyId}, ...]
            await self.api.cash()
            sub_id, sub_params, cash_response = await self.api.recv()
            await self.api.unsubscribe(sub_id)
            
            # Handle case where cash response contains portfolio data (async ordering issue)
            if isinstance(cash_response, dict) and 'positions' in cash_response:
                log.warning("Cash response contains portfolio data - using it for positions")
                portfolio_response = cash_response
                cash_response = []  # Reset cash, will default to 0
            
            log.info(f"Cash response type: {type(cash_response)}, len: {len(cash_response) if isinstance(cash_response, list) else 'N/A'}")
            
            # Parse portfolio data
            positions = portfolio_response.get('positions', [])
            net_value = float(portfolio_response.get('netValue', 0))
            
            # Cash is an array of {amount, currencyId} - typically EUR as first element
            cash = 0.0
            if isinstance(cash_response, list) and len(cash_response) > 0:
                # First element is usually the main cash balance
                cash = float(cash_response[0].get('amount', 0))
                log.info(f"Parsed cash from array: {cash} {cash_response[0].get('currencyId', 'EUR')}")
            elif isinstance(cash_response, dict):
                # Fallback if response format changes
                cash = float(cash_response.get('amount', cash_response.get('value', 0)))
            
            log.info(f"Portfolio netValue from TR: {net_value}, cash: {cash}")
            
            # Fetch instrument names only (skip ticker - too slow and unreliable)
            instrument_cache = self._load_instrument_cache()
            enriched_positions = []
            
            for i, p in enumerate(positions):
                isin = p.get('instrumentId', '')
                qty = float(p.get('netSize', 0))
                avg_buy = float(p.get('averageBuyIn', 0))
                invested = qty * avg_buy
                # TR provides netValue per position in compact_portfolio
                position_value = float(p.get('netValue', 0))
                
                # Default name is ISIN, check cache first
                cached_info = instrument_cache.get(isin, {})
                if isinstance(cached_info, str):
                    # Old cache format - just name string
                    cached_info = {"name": cached_info}
                
                name = cached_info.get("name") or isin
                instrument_type = cached_info.get("typeId", "")
                image_id = cached_info.get("imageId", "")
                
                # Fetch instrument details if:
                # 1. No name cached (name == isin), OR
                # 2. No typeId cached (needed for ETF/stock filtering)
                needs_fetch = (name == isin) or (not instrument_type)
                if needs_fetch:
                    try:
                        await self.api.instrument_details(isin)
                        inst_sub_id, inst_params, inst_response = await self.api.recv()
                        await self.api.unsubscribe(inst_sub_id)
                        new_name = inst_response.get('shortName', inst_response.get('name', isin))
                        new_type = inst_response.get('typeId', inst_response.get('type', ''))
                        new_image = inst_response.get('imageId', '')
                        # Update only if we got new data
                        if new_name and new_name != isin:
                            name = new_name
                        if new_type:
                            instrument_type = new_type
                        if new_image:
                            image_id = new_image
                        # Always save updated cache
                        instrument_cache[isin] = {
                            "name": name,
                            "typeId": instrument_type,
                            "imageId": image_id,
                        }
                        log.info(f"[{i+1}/{len(positions)}] {isin}: {name} (type={instrument_type}, img={image_id})")
                    except Exception as e:
                        log.warning(f"[{i+1}/{len(positions)}] Could not get details for {isin}: {e}")
                
                # Use TR's netValue if available, otherwise calculate from invested
                current_value = position_value if position_value > 0 else invested
                current_price = current_value / qty if qty > 0 else avg_buy
                profit = current_value - invested
                
                enriched_positions.append({
                    "name": name,
                    "isin": isin,
                    "quantity": qty,
                    "averageBuyIn": avg_buy,
                    "currentPrice": current_price,
                    "value": current_value,
                    "invested": invested,
                    "profit": profit,
                    "instrumentType": instrument_type,  # e.g., "stock", "fund", "crypto", "bond"
                    "imageId": image_id,  # TR's image identifier
                })
            
            total_invested = sum(p['invested'] for p in enriched_positions)
            total_current_value = sum(p['value'] for p in enriched_positions)
            # Use TR's netValue if we have it, otherwise sum of positions
            total_value = net_value if net_value > 0 else total_current_value
            total_profit = total_value - total_invested
            total_profit_pct = (total_profit / total_invested * 100) if total_invested > 0 else 0
            
            log.info(f"Portfolio summary: invested={total_invested:.2f}, value={total_value:.2f}, profit={total_profit:.2f} ({total_profit_pct:.2f}%)")
            
            # Fetch timeline transactions (for history reconstruction)
            log.info("Fetching timeline transactions...")
            transactions = await self._fetch_timeline_transactions()
            if transactions:
                self._save_transactions_cache(transactions)
            else:
                # Try to load from cache if fetch failed
                transactions = self._load_transactions_cache()
            
            # Enrich transactions with share quantities from TR (needed for holdings tracking)
            # This calls timeline_detail_v2 for each trade transaction
            log.info("Enriching transactions with share quantities...")
            transactions = await self._enrich_transactions_with_shares(transactions)
            
            # Save enriched transactions to cache
            if transactions:
                self._save_transactions_cache(transactions)
            
            # VALIDATION: Check that sync produced complete data
            validation = self._validate_sync_completeness(transactions, enriched_positions)
            
            # Build invested series from transactions (for the "added capital" line)
            invested_series = self._build_invested_series_from_transactions(transactions)
            log.info(f"Built invested series with {len(invested_series)} cash flow dates")
            
            # Build per-position price histories from TRANSACTION PRICES (PRIMARY)
            log.info("Building per-position price histories from transaction prices...")
            position_histories = self._build_position_histories_from_transactions(
                transactions, enriched_positions
            )
            log.info(f"Built position histories for {len(position_histories)} instruments")
            
            # Build history with market values calculated from holdings × prices + cash
            # No longer using portfolioAggregateHistory as it fails for this account
            log.info("Calculating portfolio history from holdings × prices + cash...")
            history = self._build_history_with_market_values(
                transactions, 
                position_histories, 
                invested_series, 
                total_value + cash,
                enriched_positions,  # Pass current positions for holdings baseline
                cash  # Pass current cash for reconciliation
            )
            
            # UPDATE POSITIONS with current prices from position_histories
            # TR's netValue is often 0, so we calculate currentPrice and profit ourselves
            log.info("Updating positions with calculated current prices...")
            for pos in enriched_positions:
                isin = pos.get('isin', '')
                qty = pos.get('quantity', 0)
                invested = pos.get('invested', 0)
                
                if isin in position_histories and qty > 0:
                    hist = position_histories[isin].get('history', [])
                    if hist:
                        # Get the most recent price
                        latest_price = hist[-1].get('price', 0)
                        if latest_price > 0:
                            current_value = qty * latest_price
                            pos['currentPrice'] = latest_price
                            pos['value'] = current_value
                            pos['profit'] = current_value - invested
                            log.debug(f"Updated {pos.get('name', isin)}: price={latest_price:.4f}, value={current_value:.2f}, profit={pos['profit']:.2f}")
            
            # Recalculate totals with updated position values
            total_current_value = sum(p['value'] for p in enriched_positions)
            total_invested = sum(p['invested'] for p in enriched_positions)
            total_value = total_current_value if total_current_value > 0 else net_value
            total_profit = total_value - total_invested
            total_profit_pct = (total_profit / total_invested * 100) if total_invested > 0 else 0
            
            log.info(f"Updated portfolio summary: invested={total_invested:.2f}, value={total_value:.2f}, profit={total_profit:.2f} ({total_profit_pct:.2f}%)")

            # Download logos from TR CDN into assets/logos/ for local serving
            try:
                self._download_logos(enriched_positions)
            except Exception as e:
                log.warning(f"Logo download failed (non-fatal): {e}")

            result = {
                "success": True,
                "data": {
                    "totalValue": total_value + cash,
                    "investedAmount": total_invested,
                    "cash": cash,
                    "totalProfit": total_profit,
                    "totalProfitPercent": total_profit_pct,
                    "positions": enriched_positions,
                    # Strip 'details' field from transactions to avoid localStorage quota issues
                    "transactions": [
                        {k: v for k, v in txn.items() if k != 'details'}
                        for txn in transactions
                    ],
                    "history": history,
                    "positionHistories": position_histories,  # Per-position price histories
                }
            }

            # Persist instrument name cache for next sync.
            if instrument_cache:
                self._save_instrument_cache(instrument_cache)
            
            # Save to local cache
            self._save_portfolio_cache(result)
            
            return result
            
        except Exception as e:
            log.error(f"Fetch all data failed: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "error": str(e)
            }
    
    def _calculate_and_cache_twr_series(self, history: List[Dict]) -> Dict[str, List]:
        """Pre-calculate TWR series for caching. This avoids recalculation on every chart render.
        
        Returns dict with:
            - dates: list of date strings (YYYY-MM-DD)
            - values: list of portfolio values
            - invested: list of invested amounts  
            - twr: list of TWR percentages (starting at 0%)
            - drawdown: list of drawdown percentages
        """
        if not history or len(history) < 2:
            return {}
        
        import pandas as pd
        
        # Sort and build dataframe
        sorted_history = sorted(history, key=lambda x: x.get('date', ''))
        df = pd.DataFrame(sorted_history)
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date')
        
        # Fill gaps with daily frequency
        df = df.set_index('date')
        full_date_range = pd.date_range(start=df.index.min(), end=df.index.max(), freq='D')
        df = df.reindex(full_date_range).ffill().reset_index().rename(columns={'index': 'date'})
        
        # Calculate TWR series using the shared module
        from components.performance_calc import calculate_twr_series, calculate_drawdown_series
        
        values_list = df['value'].tolist()
        invested_list = df['invested'].tolist() if 'invested' in df.columns else values_list
        
        twr_cumulative = calculate_twr_series(values_list, invested_list)
        
        # Calculate drawdown from TWR equity curve (excludes deposit effects)
        drawdown = calculate_drawdown_series(values_list, twr_series=twr_cumulative)
        
        return {
            'dates': df['date'].dt.strftime('%Y-%m-%d').tolist(),
            'values': [float(v) if pd.notna(v) else None for v in df['value'].tolist()],
            'invested': [float(v) if pd.notna(v) else None for v in invested_list],
            'twr': [float(v) if v is not None else 0.0 for v in twr_cumulative],
            'drawdown': [float(v) if v is not None else 0.0 for v in drawdown],
        }
    
    def _save_portfolio_cache(self, data: Dict[str, Any]):
        """Save portfolio data to local cache with pre-calculated series (user-scoped)."""
        cache_file = self._user_cache_dir / "portfolio_cache.json"
        try:
            import datetime
            data['cached_at'] = datetime.datetime.now().isoformat()
            
            # Pre-calculate TWR and drawdown series for faster chart rendering
            history = data.get('data', {}).get('history', [])
            if history:
                cached_series = self._calculate_and_cache_twr_series(history)
                data['data']['cachedSeries'] = cached_series
                log.info(f"Pre-calculated chart series with {len(cached_series.get('dates', []))} data points")
            
            with open(cache_file, 'w') as f:
                json.dump(data, f)
            log.info("Portfolio data cached")
        except Exception as e:
            log.error(f"Failed to cache portfolio: {e}")
    
    def _load_portfolio_cache(self) -> Optional[Dict[str, Any]]:
        """Load portfolio data from local cache (user-scoped)."""
        cache_file = self._user_cache_dir / "portfolio_cache.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                log.error(f"Failed to load cache: {e}")
        return None
    
    async def _reconnect(self, encrypted_credentials: str = None) -> Dict[str, Any]:
        """Reconnect using encrypted credentials from browser."""
        try:
            # Decrypt credentials from browser storage
            if encrypted_credentials:
                if not self.set_credentials_from_encrypted(encrypted_credentials):
                    return {"success": False, "error": "Invalid stored credentials"}
            
            if not self.phone_no or not self.pin:
                return {"success": False, "error": "No credentials available", "needs_reauth": True}
            
            if not self._keyfile_path.exists():
                return {"success": False, "error": "Session expired - please log in again", "needs_reauth": True}
            
            self._user_cache_dir.mkdir(parents=True, exist_ok=True)
            
            self.api = TradeRepublicApi(
                phone_no=self.phone_no,
                pin=self.pin,
                keyfile=str(self._keyfile_path)
            )
            
            # Try to login with existing keyfile - THIS IS SYNC, not async!
            self.api.login()
            self.is_connected = True
            
            return {
                "success": True,
                "message": "Reconnected successfully"
            }
        except Exception as e:
            log.error(f"Reconnect failed: {e}")
            return {
                "success": False,
                "error": friendly_tr_error(e),
                "needs_reauth": True
            }


# Per-user connection pool – keyed by username ("_default" for legacy callers)
_connections: Dict[str, TRConnection] = {}
_connections_lock = threading.Lock()


def get_connection(user_id: str = "_default") -> TRConnection:
    """Get or create a TRConnection scoped to *user_id*."""
    with _connections_lock:
        if user_id not in _connections:
            _connections[user_id] = TRConnection(user_id=user_id)
        return _connections[user_id]


def drop_connection(user_id: str) -> None:
    """Destroy the connection for *user_id* (call on logout).

    Clears in-memory credentials and removes the connection from the pool
    so a subsequent login creates a fresh instance.
    """
    with _connections_lock:
        conn = _connections.pop(user_id, None)
    if conn:
        try:
            conn.clear_credentials()
        except Exception:
            pass
        log.info(f"Dropped connection for user {user_id}")


# Public API functions (sync wrappers)
# All accept an optional *user_id* to scope per user.

def has_saved_credentials(user_id: str = "_default") -> bool:
    """Check if TR credentials are saved."""
    return get_connection(user_id).has_credentials()


def initiate_login(phone_no: str, pin: str, user_id: str = "_default") -> Dict[str, Any]:
    """Start the login process - sends verification code to TR app."""
    conn = get_connection(user_id)
    return conn.run(conn._initiate_web_login(phone_no, pin))


def complete_login(code: str, user_id: str = "_default") -> Dict[str, Any]:
    """Complete login with the 4-digit verification code."""
    conn = get_connection(user_id)
    return conn.run(conn._complete_web_login(code))


def fetch_portfolio(user_id: str = "_default") -> Dict[str, Any]:
    """Fetch current portfolio data."""
    conn = get_connection(user_id)
    return conn.run_serialized(conn._fetch_portfolio())


def fetch_all_data(user_id: str = "_default") -> Dict[str, Any]:
    """Fetch all portfolio data including history.
    
    This ALWAYS fetches fresh data from TR when called.
    The cache is only used for page loads (via get_cached_portfolio).
    """
    conn = get_connection(user_id)
    return conn.run_serialized(conn._fetch_all_data())


def get_cached_portfolio(user_id: str = "_default") -> Optional[Dict[str, Any]]:
    """Get cached portfolio data without connecting."""
    conn = get_connection(user_id)
    return conn._load_portfolio_cache()


def get_cached_transactions(user_id: str = "_default") -> List[Dict]:
    """Get cached transactions without connecting."""
    conn = get_connection(user_id)
    return conn._load_transactions_cache()


def reconnect(encrypted_credentials: str = None, user_id: str = "_default") -> Dict[str, Any]:
    """Try to reconnect using encrypted credentials from browser."""
    conn = get_connection(user_id)
    return conn.run_serialized(conn._reconnect(encrypted_credentials))


def disconnect(user_id: str = "_default"):
    """Disconnect and clear credentials."""
    drop_connection(user_id)


def has_keyfile(user_id: str = "_default") -> bool:
    """Check if keyfile exists for reconnect."""
    return get_connection(user_id).has_keyfile()


def is_connected(user_id: str = "_default") -> bool:
    """Check if currently connected."""
    return get_connection(user_id).is_connected


def read_keyfile(user_id: str = "_default") -> Optional[str]:
    """Return the pytr device keyfile (PEM text) for *user_id*, or None.

    Used to back the keyfile up into the per-user encrypted blob so that
    silent reconnect keeps working after the ephemeral server disk is wiped.
    """
    p = get_connection(user_id)._keyfile_path
    try:
        return p.read_text() if p.exists() else None
    except Exception:
        return None


def restore_keyfile(user_id: str, pem: str) -> bool:
    """Write a previously backed-up keyfile (PEM text) back to disk for pytr."""
    if not pem:
        return False
    conn = get_connection(user_id)
    try:
        conn._user_cache_dir.mkdir(parents=True, exist_ok=True)
        conn._keyfile_path.write_text(pem)
        return True
    except Exception as e:
        log.warning(f"Failed to restore keyfile for {user_id}: {e}")
        return False
