# BankPilot Sitemap

Production sitemap for `https://bankpilot.eu`.

---

## Public Pages (No Auth)

| Route | Title | Description |
|-------|-------|-------------|
| `/` | Landing Page | Hero, feature showcase, pricing cards, trust bar, mini-FAQ, CTA to signup |
| `/faq` | FAQ | Expandable Q&A — connections, rules, security, pricing, data management |
| `/impressum` | Impressum | Legal company info, contact, registration (EN/DE) |
| `/agb` | AGB / Terms of Service | Terms of service (EN/DE) |
| `/privacy` | Privacy Policy | GDPR-compliant privacy policy (EN/DE) |
| `/mieteingangskontrolle` | Landlord Payment Monitor | Vertical landing page for rent monitoring use case |

These are the public routes included in [sitemap.xml](/c:/Repos/backtesting/sitemap.xml).

## Authentication Pages (Unauthenticated)

| Route | Title | Description |
|-------|-------|-------------|
| `/signup` | Sign Up | Email + password registration (referral code required, or waitlist link) |
| `/waitlist` | Waitlist | Join waitlist if no referral code |
| `/confirm?token=…` | Email Confirmation | Verify email via token → redirect to `/app` |
| `/reset-password?token=…` | Password Reset | Reset password via emailed token |

`/signup` and `/waitlist` are included in the XML sitemap because they are public pages.
`/confirm` and `/reset-password` are excluded because they are tokenized utility routes.

## Authenticated Pages (Auth Required)

| Route | Title | Description |
|-------|-------|-------------|
| `/app` | BankPilot App | Main dashboard (subscription-gated via Stripe) |
| `/settings` | Account Settings | Notification prefs, sync interval, password change, delete account, logout |

Authenticated routes are documented here for completeness, but they are excluded from the XML sitemap.

### `/app` Sub-sections

| Section | Description |
|---------|-------------|
| Connect Accounts | Tink Open Banking — link bank accounts |
| Transactions | List, view, filter, tag, AI-categorize transactions |
| Rules | Create recurring-transaction rules, auto-categorization |
| Monitoring | Expected vs actual cash flow, alert summary |
| Notifications | Alert configuration per rule |
| Account | Manage Stripe subscription |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/banksync/api/session` | POST | Exchange Bearer token for HttpOnly `bss_auth` cookie |
| `/banksync/api/logout` | POST | Clear cookies, invalidate session |

## Navigation

### Top Navbar (sticky)
- **Left**: BankPilot logo + `.eu`
- **Center** (desktop): Features · Pricing · FAQ
- **Right**: Language toggle (EN/DE), CTA button ("Zum App" / Login), or account dropdown when authenticated

### Footer
- Copyright © 2026 BankPilot.eu
- Links: Impressum · AGB · Privacy

### Mobile
- Responsive navbar — links collapse behind hamburger menu

## Key Integrations

| Integration | Component | Purpose |
|-------------|-----------|---------|
| Tink | `components/tink_api.py` | Open Banking — bank account connections |
| Stripe | `components/stripe_integration.py` | Subscription billing gate |
| OpenAI | `components/gpt_functionality.py` | AI transaction categorization |

## i18n

- Languages: English (`en`), German (`de`)
- Controlled via `?lang=` query param or toggle button
- Persisted in `lang-store` (localStorage)
