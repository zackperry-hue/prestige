# Roundup Care — Technical Design Document

**Status:** Draft | **Date:** 2026-03-30 | **Owner:** Zack Perry, CEO

---

## 1. System Architecture

### Monorepo Structure

```
roundup-care/
├── packages/
│   ├── mobile/          # React Native / Expo app
│   ├── api/             # Express.js backend
│   └── shared/          # Shared types, validation schemas, constants
├── package.json         # Workspace root
├── turbo.json           # Turborepo config (optional)
└── docs/
```

**Tooling:** npm workspaces (or yarn workspaces). Turborepo optional for build orchestration.

### High-Level Architecture

```
┌─────────────────────────────────────────────────────┐
│                    MOBILE APP                        │
│              React Native / Expo                     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐            │
│  │Onboarding│ │Dashboard │ │Bill Chat │            │
│  │  + Chat  │ │  + Card  │ │ + Upload │            │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘            │
│       │             │            │                   │
│       └─────────────┴────────────┘                   │
│                     │                                │
│              Expo Push Notifications                 │
└─────────────────────┬───────────────────────────────┘
                      │ HTTPS
┌─────────────────────▼───────────────────────────────┐
│                  EXPRESS API                          │
│                                                      │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐  │
│  │Auth/KYC │ │ Roundup  │ │  AI Svc  │ │ Bills  │  │
│  │ Routes  │ │  Engine  │ │(Anthropic)│ │ Routes │  │
│  └────┬────┘ └────┬─────┘ └────┬─────┘ └───┬────┘  │
│       │           │            │            │        │
│  ┌────▼────┐ ┌────▼─────┐ ┌───▼────┐ ┌────▼─────┐  │
│  │  Unit   │ │  Plaid   │ │Claude  │ │Supabase  │  │
│  │  SDK    │ │  SDK     │ │  API   │ │ Storage  │  │
│  └────┬────┘ └────┬─────┘ └────────┘ └────┬─────┘  │
│       │           │                        │         │
│  ┌────▼───────────▼────────────────────────▼─────┐  │
│  │              SUPABASE (PostgreSQL)              │  │
│  └────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
                      │                │
            ┌─────────▼──┐    ┌───────▼────────┐
            │    Unit    │    │     Plaid      │
            │  Banking   │    │  Data Layer    │
            │ (Accounts, │    │ (Transactions, │
            │  Cards,    │    │  Balances,     │
            │  ACH)      │    │  Webhooks)     │
            └────────────┘    └────────────────┘
```

---

## 2. Data Model

### Core Tables

#### `users`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID, PK | Default: gen_random_uuid() |
| email | TEXT, UNIQUE | Indexed |
| display_name | TEXT | |
| phone | TEXT | |
| onboarding_completed_at | TIMESTAMPTZ | NULL until onboarding done |
| referral_code | TEXT, UNIQUE | Auto-generated at signup |
| created_at | TIMESTAMPTZ | Default: now() |
| updated_at | TIMESTAMPTZ | |

#### `kyc_records`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID, PK | |
| user_id | UUID, FK → users | |
| unit_customer_id | TEXT | Unit's customer ID |
| status | ENUM | pending, approved, rejected, retry |
| rejection_reason | TEXT | |
| created_at / updated_at | TIMESTAMPTZ | |

#### `bank_connections`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID, PK | |
| user_id | UUID, FK → users | |
| plaid_item_id | TEXT | |
| plaid_access_token_enc | BYTEA | Fernet-encrypted |
| institution_name | TEXT | e.g. "Chase" |
| account_mask | TEXT | Last 4 digits |
| is_active | BOOLEAN | Default: true |
| connected_at | TIMESTAMPTZ | |
| disconnected_at | TIMESTAMPTZ | NULL if active |

#### `transactions`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID, PK | |
| user_id | UUID, FK → users | Indexed |
| bank_connection_id | UUID, FK | |
| plaid_transaction_id | TEXT, UNIQUE | Dedup key |
| amount_cents | INTEGER | Purchase amount in cents |
| merchant_name | TEXT | |
| category | TEXT | Plaid category |
| transaction_date | DATE | |
| roundup_amount_cents | INTEGER | ceil(amount) - amount |
| sweep_id | UUID, FK → sweeps | NULL until swept |
| created_at | TIMESTAMPTZ | |

#### `sweeps`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID, PK | |
| user_id | UUID, FK → users | Indexed |
| total_amount_cents | INTEGER | Sum of roundups in batch |
| status | ENUM | pending, initiated, completed, failed, returned |
| unit_ach_transfer_id | TEXT | |
| initiated_at | TIMESTAMPTZ | |
| completed_at | TIMESTAMPTZ | |
| failure_reason | TEXT | |
| retry_count | INTEGER | Default: 0 |

#### `savings_accounts`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID, PK | |
| user_id | UUID, FK → users, UNIQUE | One per user |
| unit_account_id | TEXT | |
| balance_cents | INTEGER | Cached from Unit |
| last_synced_at | TIMESTAMPTZ | |
| created_at | TIMESTAMPTZ | |

#### `savings_goals`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID, PK | |
| user_id | UUID, FK → users | |
| estimated_low_cents | INTEGER | |
| estimated_high_cents | INTEGER | |
| insurance_type | TEXT | uninsured, medicaid, marketplace, other |
| ai_reasoning | TEXT | Explanation of estimate |
| created_at / updated_at | TIMESTAMPTZ | |

#### `debit_cards`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID, PK | |
| user_id | UUID, FK → users | |
| unit_card_id | TEXT | |
| card_type | ENUM | virtual, physical |
| last_four | TEXT | |
| status | ENUM | active, frozen, closed |
| issued_at | TIMESTAMPTZ | |
| activated_at | TIMESTAMPTZ | |

#### `bills`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID, PK | |
| user_id | UUID, FK → users | |
| provider_name | TEXT | |
| total_amount_cents | INTEGER | |
| upload_type | ENUM | image, pdf |
| file_url | TEXT | Supabase Storage path |
| ai_summary | TEXT | Plain-language summary |
| ai_flags | JSONB | Flagged line items |
| ai_letter_draft | TEXT | Generated inquiry letter |
| status | ENUM | uploaded, reviewing, reviewed |
| created_at | TIMESTAMPTZ | |
| reviewed_at | TIMESTAMPTZ | |

#### `referrals`
| Column | Type | Notes |
|--------|------|-------|
| id | UUID, PK | |
| referrer_user_id | UUID, FK → users | |
| referred_user_id | UUID, FK → users | NULL until signup |
| referral_code_used | TEXT | |
| bonus_amount_cents | INTEGER | $5-$10 per PRD |
| bonus_credited_at | TIMESTAMPTZ | |
| created_at | TIMESTAMPTZ | |

---

## 3. Services Map

### Authentication & KYC
- **Supabase Auth** for user registration/login (email + password, magic link)
- **Unit hosted KYC widget** embedded in React Native WebView
- KYC status stored in `kyc_records`; webhook from Unit updates status
- Account creation flow: Register → KYC → Account provisioned → Onboarding

### Plaid Integration
- **Plaid Link** SDK (React Native) for bank account connection
- **Webhook endpoint** `/webhooks/plaid` receives transaction updates
- Per-transaction roundup calculation on webhook receipt
- Plaid access tokens encrypted at rest (Fernet)
- Balance check via Plaid before each sweep

### Roundup Engine
- **Per-transaction:** On Plaid webhook, calculate `ceil(amount) - amount`, store in `transactions.roundup_amount_cents`
- **Weekly sweep (default):** Cron job runs Monday 6 AM user-local-time
  1. Sum un-swept roundups per user
  2. Skip if total < $1.00
  3. Check external account balance via Plaid (require balance > sweep + $25 buffer)
  4. Initiate ACH pull via Unit API
  5. Mark transactions with `sweep_id`
  6. Update sweep status on Unit webhook
- **Failure handling:**
  - ACH return → mark sweep `failed`, notify user, skip cycle
  - 3 consecutive failures → pause roundups, prompt user
- **Configurable cadence:** Users can switch to daily in settings

### AI Services (Anthropic API — Server-Side Only)
- **Cost Estimator (Onboarding):** Hybrid approach
  - Structured form collects: insurance card scan (Claude vision), age, location, household size
  - Conversational follow-up refines estimate based on conditions, planned procedures
  - Returns savings goal range (e.g. $650–$1,050) within 10 seconds
  - Stored in `savings_goals`
- **Bill Review:**
  - User uploads image or PDF
  - Image/PDF sent to Claude API with vision capability
  - AI returns: plain-language summary, flagged charges, draft inquiry letter
  - All stored in `bills` table (ai_summary, ai_flags, ai_letter_draft)

### Debit Card (Unit)
- Virtual card provisioned via Unit API after KYC approval (instant)
- Physical card deferred to Phase 2
- Apple/Google Wallet provisioning via Unit tokens
- Card spending limited to available savings balance (Unit enforces)

### Push Notifications
- **Expo Push Notification service** (free, built into Expo)
- Triggers:
  - Roundup sweep confirmation ("Your roundups just added $12.84...")
  - Sweep failure notification
  - Bill review complete
  - Savings milestone (25%, 50%, 75%, 100% of goal)

### File Storage
- **Supabase Storage** for bill uploads (images, PDFs)
- Private buckets, authenticated access only
- Max file size: 10MB

---

## 4. API Route Structure

```
POST   /auth/register
POST   /auth/login
POST   /auth/logout
GET    /auth/me

POST   /kyc/initiate          → Returns Unit widget URL
POST   /webhooks/unit          → Unit KYC + transfer status updates

POST   /plaid/link-token       → Generate Plaid Link token
POST   /plaid/exchange-token   → Exchange public token for access token
POST   /webhooks/plaid         → Transaction updates

GET    /dashboard              → Balance, goal, recent activity
GET    /transactions           → Roundup history with pagination
PATCH  /settings/sweep-cadence → daily | weekly

GET    /savings/goal           → Current savings goal
POST   /savings/goal/estimate  → AI cost estimator (onboarding)
POST   /savings/goal/chat      → Conversational follow-up

GET    /card                   → Card details (masked)
POST   /card/freeze            → Freeze/unfreeze
GET    /card/wallet-token      → Apple/Google Wallet provisioning

POST   /bills/upload           → Image or PDF upload
GET    /bills                  → Bill history
GET    /bills/:id              → Bill detail + AI analysis

POST   /referrals/share        → Generate referral link
GET    /referrals              → Referral status + bonuses
```

---

## 5. Environment Checklist

| Service | Status | Action Required |
|---------|--------|-----------------|
| Supabase | Not set up | Create project, get API keys + service role key |
| Unit | **Sandbox ready** | Have API token; need webhook secret configured |
| Plaid | Not set up | Create developer account, get sandbox credentials |
| Anthropic | Not set up | Create account, get API key |
| Expo / EAS | Not set up | Create Expo account, configure EAS Build |
| Apple Developer | Not set up | Enroll in Apple Developer Program ($99/yr) |
| Google Play | Not set up | Register developer account ($25 one-time) |
| Domain (roundup.care) | Unknown | Confirm domain ownership / DNS |

### Required Environment Variables
```
# Supabase
SUPABASE_URL=
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
DATABASE_URL=

# Unit
UNIT_API_TOKEN=
UNIT_WEBHOOK_SECRET=
UNIT_ENVIRONMENT=sandbox

# Plaid
PLAID_CLIENT_ID=
PLAID_SECRET=
PLAID_ENVIRONMENT=sandbox

# Anthropic
ANTHROPIC_API_KEY=

# App
APP_SECRET_KEY=
TOKEN_ENCRYPTION_KEY=          # Fernet key for Plaid token encryption
EXPO_PUSH_ACCESS_TOKEN=

# Apple/Google (for wallet provisioning)
APPLE_PUSH_CERTIFICATE=
```

---

## 6. Build Order

Per the brief, after both documents are approved:

1. Supabase schema + backend scaffolding (Express, routes, middleware)
2. Authentication + KYC flow (Supabase Auth + Unit widget)
3. Plaid bank linking + roundup calculation engine
4. Savings dashboard (home screen)
5. Onboarding AI cost estimator (hybrid chat)
6. Debit card provisioning + display (virtual only)
7. Bill upload + AI review
8. Push notifications
9. Referral loop

---

## 7. Deployment Strategy

- **Development:** Local Express + Supabase (cloud project in sandbox mode)
- **Testing:** TestFlight (iOS) + Google Play internal track
- **Production:** TBD (Railway, Render, or AWS for API; Expo EAS for mobile builds)
- **OTA Updates:** Expo OTA for JS-only changes post-app-store-approval
