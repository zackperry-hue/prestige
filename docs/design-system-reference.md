# Roundup Care — Design System Reference

**Status:** Draft | **Date:** 2026-03-30 | **Owner:** Zack Perry, CEO

---

## 1. Brand Voice

**Tone:** Warm, plain-language, "knowledgeable friend" — not a financial institution.
- Empathetic, never condescending
- Emphasizes control and preparation, not fear
- Healthcare costs are systemic problems, not personal failures
- Uses "you" and "your," avoids jargon
- Celebrates small wins ("Your roundups just added $12.84 to your healthcare safety net")

**Copy principles:**
- Lead with benefit, not mechanism ("You're building a safety net" > "ACH transfer initiated")
- Numbers are always formatted for humans ($12.84, not 1284 cents)
- Error states are supportive, not blaming ("We couldn't complete your transfer this week — we'll try again next time")

---

## 2. Color Tokens

All tokens use `--rc-*` naming convention for the Roundup Care design system layer on top of shadcn/ui.

### Primary Palette
| Token | Value | Usage |
|-------|-------|-------|
| `--rc-primary` | `#1B9B8E` | Primary teal — buttons, progress bars, active states |
| `--rc-primary-light` | `#E6F5F3` | Light teal — backgrounds, cards, subtle highlights |
| `--rc-primary-dark` | `#157A70` | Dark teal — pressed states, hover on primary elements |

### Neutral Palette
| Token | Value | Usage |
|-------|-------|-------|
| `--rc-bg` | `#FFFFFF` | Page background |
| `--rc-bg-secondary` | `#F8FAFA` | Card backgrounds, sections |
| `--rc-bg-tertiary` | `#F0F2F2` | Input fields, disabled states |
| `--rc-text-primary` | `#1A1A2E` | Headings, primary text |
| `--rc-text-secondary` | `#6B7280` | Body text, labels |
| `--rc-text-tertiary` | `#9CA3AF` | Placeholder text, captions |
| `--rc-border` | `#E5E7EB` | Card borders, dividers |
| `--rc-border-focus` | `#1B9B8E` | Input focus rings |

### Semantic Colors
| Token | Value | Usage |
|-------|-------|-------|
| `--rc-success` | `#10B981` | Savings milestones, positive changes |
| `--rc-warning` | `#F59E0B` | Low balance alerts, attention items |
| `--rc-error` | `#EF4444` | Failed transfers, validation errors |
| `--rc-info` | `#3B82F6` | Informational badges, tips |

### Financial Display
| Token | Value | Usage |
|-------|-------|-------|
| `--rc-money-positive` | `#10B981` | Money gained / saved |
| `--rc-money-negative` | `#EF4444` | Money spent / deducted |
| `--rc-goal-track` | `#E6F5F3` | Progress bar background |
| `--rc-goal-fill` | `#1B9B8E` | Progress bar fill |

---

## 3. Typography

### Font Families
| Token | Family | Usage |
|-------|--------|-------|
| `--rc-font-display` | DM Serif Display | Headings, financial figures, hero numbers |
| `--rc-font-body` | DM Sans | Body text, labels, UI elements |
| `--rc-font-mono` | Inter | Fallback body, tabular numbers |

### Type Scale
| Name | Size | Weight | Line Height | Font | Usage |
|------|------|--------|-------------|------|-------|
| `display-lg` | 36px | 400 | 1.2 | DM Serif Display | Balance amount on dashboard |
| `display-md` | 28px | 400 | 1.2 | DM Serif Display | Section headings, goal amounts |
| `display-sm` | 22px | 400 | 1.3 | DM Serif Display | Card headings, feature titles |
| `title-lg` | 20px | 600 | 1.3 | DM Sans | Screen titles |
| `title-md` | 17px | 600 | 1.4 | DM Sans | Card titles, section headers |
| `title-sm` | 15px | 600 | 1.4 | DM Sans | List item titles |
| `body-lg` | 17px | 400 | 1.5 | DM Sans | Primary body text |
| `body-md` | 15px | 400 | 1.5 | DM Sans | Secondary body text |
| `body-sm` | 13px | 400 | 1.4 | DM Sans | Captions, timestamps |
| `label` | 13px | 500 | 1.0 | DM Sans | Form labels, button text (uppercase tracking) |
| `money-lg` | 36px | 400 | 1.0 | DM Serif Display | Hero balance display |
| `money-md` | 22px | 400 | 1.0 | DM Serif Display | Transaction amounts |
| `money-sm` | 15px | 500 | 1.0 | DM Sans | Inline amounts |

---

## 4. Spacing System

8px base grid. All spacing values are multiples of 4 or 8.

| Token | Value | Usage |
|-------|-------|-------|
| `--rc-space-xs` | 4px | Tight gaps (icon-to-text) |
| `--rc-space-sm` | 8px | Compact padding, list item gaps |
| `--rc-space-md` | 16px | Standard padding, card internal spacing |
| `--rc-space-lg` | 24px | Section spacing, card-to-card gaps |
| `--rc-space-xl` | 32px | Screen-level vertical rhythm |
| `--rc-space-2xl` | 48px | Major section breaks |

### Layout Constants
| Token | Value | Usage |
|-------|-------|-------|
| `--rc-screen-padding` | 20px | Horizontal padding on all screens |
| `--rc-card-padding` | 16px | Internal card padding |
| `--rc-card-radius` | 16px | Card corner radius |
| `--rc-button-radius` | 12px | Button corner radius |
| `--rc-input-radius` | 10px | Input field corner radius |
| `--rc-input-height` | 48px | Standard input height |
| `--rc-button-height` | 52px | Primary button height |

---

## 5. Component Patterns

Built on shadcn/ui with `--rc-*` token overrides. Cross-platform neutral feel.

### Buttons

**Primary Button**
- Background: `--rc-primary`
- Text: white, `label` style (DM Sans 13px 500, uppercase)
- Height: 52px, full-width on mobile
- Radius: 12px
- Pressed: `--rc-primary-dark`
- Disabled: 40% opacity

**Secondary Button**
- Background: transparent
- Border: 1px `--rc-border`
- Text: `--rc-text-primary`, `label` style
- Same dimensions as primary

**Text Button**
- No background or border
- Text: `--rc-primary`, `body-md` weight 500
- Used for in-line actions ("Skip", "Learn more")

### Cards
- Background: `--rc-bg` or `--rc-bg-secondary`
- Border: 1px `--rc-border`
- Radius: `--rc-card-radius` (16px)
- Padding: `--rc-card-padding` (16px)
- Shadow: `0 1px 3px rgba(0,0,0,0.05)` (subtle)

### Inputs
- Height: `--rc-input-height` (48px)
- Background: `--rc-bg-tertiary`
- Border: none by default; `--rc-border-focus` on focus
- Radius: `--rc-input-radius` (10px)
- Placeholder: `--rc-text-tertiary`
- Label above: `label` style

### Progress Bar (Savings Goal)
- Track: `--rc-goal-track` (light teal)
- Fill: `--rc-goal-fill` (primary teal)
- Height: 12px
- Radius: 6px (fully rounded)
- Animated fill on value change (simple ease-out, 300ms)

### Chat Bubble (AI Interactions)
- AI messages: `--rc-primary-light` background, left-aligned
- User messages: `--rc-bg-tertiary` background, right-aligned
- Radius: 16px with tail on sender side
- Body text: `body-md`

### Navigation
- Bottom tab bar (standard React Navigation pattern)
- Active tab: `--rc-primary` icon + label
- Inactive tab: `--rc-text-tertiary`
- Tabs: Home (Dashboard), Card, Bills, Settings

---

## 6. Iconography

- Use a consistent icon set (Lucide React Native or similar)
- Stroke width: 1.5px
- Size: 24px default, 20px in compact contexts
- Color inherits from parent text color

---

## 7. Screen Priority & Implementation Notes

### Priority 1 (Build First)
These screens map to the critical onboarding and activation flow:

**Login / Registration**
- Email + password (Supabase Auth)
- Clean, centered layout
- Roundup Care logo + tagline
- Primary CTA: "Get Started" / "Sign In"
- Design latitude: use as guideline

**Intro to Roundup Care**
- Onboarding walkthrough (2–3 screens)
- Explains the value prop: save automatically, pay with confidence, review bills
- Illustrations or simple graphics (TBD when mockups shared)
- "Next" / "Get Started" flow

**AI Savings Goal Estimator (Onboarding)**
- Hybrid: starts with structured form (insurance card scan, age, location, household)
- Transitions to conversational chat for refinement
- Displays savings goal range with `display-md` typography
- "Set My Goal" CTA stores result

**Bank Linking (Plaid)**
- Plaid Link SDK opens as modal
- Pre-link screen explains why: "Connect your bank so we can round up your purchases"
- Post-link confirmation: shows institution name + account mask
- Roundups activated by default

**Savings Dashboard (Home Screen)**
- Hero: current balance in `money-lg` (DM Serif Display 36px)
- Progress bar showing pace-to-goal
- Recent roundup activity (last 5–7 transactions with roundup amounts)
- Quick stats: total saved this month, roundup count
- "Your healthcare safety net is growing" warm messaging

### Priority 2 (Build After Core Flow)
**Virtual Debit Card Display**
- Apple Wallet-style card visual
- Card number masked, last 4 shown
- "Add to Apple Wallet" / "Add to Google Pay" buttons
- Freeze/unfreeze toggle

**Bill Upload + AI Review**
- Camera capture or file picker (image + PDF)
- Loading state while AI processes (~30 seconds per PRD)
- Results: plain-language summary, flagged charges, draft letter
- Chat-style display for AI analysis

**Push Notifications**
- System-level notifications via Expo
- In-app notification center not needed at MVP

**Referral**
- Simple share sheet with referral link
- "Invite a friend, you both get $X"
- Status tracker for pending/completed referrals

---

## 8. Animations & Transitions

Keep it simple (per discovery):
- Standard React Navigation screen transitions (slide from right)
- Progress bar fill: ease-out 300ms
- Balance counter: no animated counting, just display the number
- Card flip/reveal: not needed at MVP
- Loading states: simple spinner or skeleton screens

---

## 9. Dark Mode

Not in scope for MVP. Light theme only. Token system supports future dark mode by swapping `--rc-bg`, `--rc-text-*`, and `--rc-border` values.

---

## 10. Accessibility

- Minimum touch target: 44x44px (iOS guideline)
- Color contrast: all text meets WCAG AA (4.5:1 for body, 3:1 for large text)
- Financial amounts: always use aria-label with full dollar amount ("twelve dollars and eighty-four cents")
- Screen reader support via React Native Accessibility API
