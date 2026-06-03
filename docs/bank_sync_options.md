# Bank Sync — Provider Options & Honest Cost Analysis

> **TL;DR:** There is currently **no free production-grade PSD2 bank API** accepting new signups.  
> The only one that was free (GoCardless/Nordigen) has closed new registrations.  
> Every other provider (Tink, Plaid, Yapily, Salt Edge, TrueLayer) charges for production use.  
> **Recommended free path:** CSV/file import from your bank (every bank supports this).

---

## Provider Comparison

| Provider | Free Sandbox | Free Production | Coverage | Status |
|---|---|---|---|---|
| **GoCardless Bank Account Data** (ex-Nordigen) | ✅ | ✅ Was free | 2400+ EU banks | ❌ **New signups disabled** |
| **Tink** (by Visa) | ✅ Test data only | ❌ Enterprise only | 3000+ banks, 18 countries | Contact sales for pricing |
| **Plaid** | ✅ 200 calls | ❌ Pay-per-use | US-focused, some EU | Pay per connected account |
| **Salt Edge** | ✅ Fake providers | ❌ Contact sales | 5000+ banks, 50+ countries | Need live account approval |
| **Yapily** | ✅ Console access | ❌ "Tailored pricing" | EU-focused | Contact sales |
| **TrueLayer** | ✅ Sandbox | ❌ Paid | UK + EU | Contact sales |

---

## Detailed Breakdown

### 1. GoCardless Bank Account Data (formerly Nordigen) — THE BEST, BUT CLOSED

**What it was:**  
Nordigen was the **only truly free** PSD2 Account Information API. GoCardless acquired them in 2022 and kept the free model running. You got:
- Free production access to 2400+ EU banks
- Up to 24 months of transaction history
- 90 days continuous access per consent
- Account details, balances, transactions
- No per-call or per-user charges

**Current status:**  
"New signups for Bank Account Data are currently disabled."  

The API docs are still live at `developer.gocardless.com/bank-account-data/`, and existing users still have access. The portal at `bankaccountdata.gocardless.com` is still running. This could mean:
- They're restructuring the product (likely integrating deeper into GoCardless payments)
- They may re-open signups in the future
- They may add pricing when they re-launch

**Verdict:** Best option if/when it re-opens. Worth checking periodically.

---

### 2. Tink (by Visa) — SANDBOX ONLY IS FREE

**What they say:**  
From Tink's own FAQ:

> **"Is there a pay-per-use option?"**  
> "No, however you are welcome to create a free account to try Tink products with **test data in a sandbox environment** before upgrading to an Enterprise account."

**What this means:**
- Free account at `console.tink.com` → **sandbox only** (fake/test data)
- To connect real banks → need Enterprise agreement (contact sales, paid)
- The pricing page says: *"The prices listed on this page are applicable exclusively to our existing customers... New prospects should contact our sales team for personalised pricing."*

**Verdict:** ❌ Not free for production. The `bank_api.py` I built will work if you pay, but you're paying.

---

### 3. Plaid — PAY PER USE

- Free sandbox for testing
- "Limited Production" = 200 API calls with real data
- Beyond that: pay per connected item (one-time, subscription, or per-request depending on product)
- Primarily US-focused, limited EU coverage

**Verdict:** ❌ Not free. Also weak on EU banks.

---

### 4. Salt Edge — CONTACT SALES

- Comprehensive API, 5000+ banks worldwide
- Free Test mode with fake providers only
- Going "live" requires: verification process, eIDAS certificates, Salt Edge approval
- Pricing: contact sales, no published free tier

**Verdict:** ❌ Not free. Good product but enterprise-oriented.

---

### 5. Yapily — CONTACT SALES

- "Tailored pricing for every business" = no free tier
- Good EU coverage
- Enterprise-oriented

**Verdict:** ❌ Not free.

---

## Truly Free Alternatives

### Option A: CSV/File Import (RECOMMENDED — $0 forever)

Every bank in Europe lets you download transactions as CSV, OFX, MT940, or CAMT files. This approach:

- **Cost:** $0, forever, no API keys needed
- **Coverage:** 100% — works with literally every bank
- **Privacy:** Data never touches a third-party API
- **Reliability:** No API rate limits, no consent expiry, no provider outages
- **Implementation:** Parse CSV files on upload, map columns, categorise

**How it works in the app:**
1. User goes to their bank's online banking
2. Downloads transactions as CSV (every bank has this)
3. Uploads the CSV file into APE•X
4. App parses it, categorises transactions, applies rules

**Downsides:**
- Not automatic (user must manually download & upload)
- No real-time sync
- Different banks have different CSV formats (solvable with column mapping)

### Option B: Manual Transaction Entry ($0)

Simple form to add transactions manually. Good for tracking a few recurring payments.

### Option C: Wait for GoCardless to re-open ($0 if they keep it free)

Keep checking `bankaccountdata.gocardless.com` periodically. If they re-enable signups with the same free model, it's the perfect solution. The code architecture in `bank_api.py` can be adapted to GoCardless's API quickly.

### Option D: Hybrid — CSV now, API later

Build CSV import now (free), add API-based sync later when a free option becomes available or when you're willing to pay.

---

## Recommendation

**Go with Option D (Hybrid):**

1. **Now:** Add CSV import to the Bank Sync page. User uploads their bank's CSV export. App parses it, normalises transactions, categorises with AI, monitors recurring payments. All the existing rules/monitoring logic works unchanged.

2. **Later:** When GoCardless re-opens (or if you decide to pay for Tink/Salt Edge), the API-based sync slots in alongside CSV import. Users get a choice: upload CSV or connect via API.

This gives you:
- Zero cost today
- Working feature for users immediately  
- Forward-compatible architecture for API sync later
- No dependency on any third-party service availability

---

## Current Code Status

| File | Status | Notes |
|---|---|---|
| `components/bank_api.py` | ✅ Built (Tink) | Full Tink API wrapper. Works but requires paid Enterprise account for production. |
| `pages/bank_sync.py` | ✅ Built (Tink) | UI + callbacks using Tink flow |
| `data/default_categories.json` | ✅ Ready | 40 transaction categories |
| `components/gocardless_api.py` | 🗑️ Deleted | Was GoCardless version, removed |

**Next step if you choose CSV import:** I'll add a CSV upload component to `bank_sync.py` that auto-detects common bank formats (Deutsche Bank, Sparkasse, N26, ING, Commerzbank, Revolut, etc.) and falls back to manual column mapping. All existing categorisation, rules, and monitoring features work identically regardless of how transactions enter the system.
