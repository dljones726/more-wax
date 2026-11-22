# Requirements — Valuation Accuracy

**Features:** FR-new-1 Condition-based valuation · FR-new-2 Value confidence score
**Status:** Proposed (backlog, implement after current feature set if time permits)
**Priority (MoSCoW):** Should
**Depends on:** Snapshot analytics, Value history, Purchase price / gain-loss (all consume the value these features produce)

---

## 1. Background and rationale

### 1.1 Problem

More'Wax values every record as if it were a **VG+** copy, regardless of its real condition. `_parse_prices()` in `server/discogs.py` maps the Discogs price suggestions as:

| Stored field | Discogs grade used |
|---|---|
| `price_low` | Very Good (VG), else Good Plus (G+) |
| `price_median` | Very Good Plus (VG+) |
| `price_high` | Near Mint (NM or M-), else Mint (M) |

All collection totals, value history and gain/loss use `price_median`, so a worn VG copy and a sealed Mint copy of the same release are valued identically. Values are also shown without any indication of whether the record could actually sell at that price.

### 1.2 Market evidence (from requirements validation)

- Dealers report that app valuations present a best-case figure and that worn copies reduce real value ([Dutch Vinyl](https://www.dutchvinyl.com.au/pages/how-much-are-vinyl-records-worth)).
- "A record with no buyers does not have value — even if an app assigns it a price" ([WeBuyRecords](https://webuyrecordsusa.com/sellingrecords/record-scanner-app-lying)).
- Competing apps market "verified sold prices, not inflated listings" as a differentiator.

### 1.3 Why now / why cheap

The data is **already fetched**. `discogs_refresh_prices()` calls `/marketplace/price_suggestions/{id}` (which returns a value per grade) and `/marketplace/stats/{id}` (which returns `num_for_sale`). Today most grades are discarded after parsing. No new external API is required.

---

## 2. Scope

**In scope**
- Recording media and sleeve condition per record.
- Storing the full per-grade price suggestion map.
- Valuing each record at the suggestion for its media grade.
- A confidence level (High / Medium / Low / None) with reasons for every valuation.
- Splitting collection totals by confidence.
- Importing grades from the Discogs collection during sync (Could).

**Out of scope**
- Automatic grading (e.g. from photos).
- Using realized sale prices (Discogs sales history is not exposed through the API).
- Sleeve-condition price adjustment (Discogs suggestions are per media grade only; sleeve is recorded but informational).
- Writing grades back to Discogs (future).

---

## 3. Assumptions and dependencies

| ID | Assumption / dependency | Impact if false |
|---|---|---|
| A-1 | `/marketplace/price_suggestions` returns a `{currency, value}` object keyed by grade name (Mint (M), Near Mint (NM or M-), Very Good Plus (VG+), Very Good (VG), Good Plus (G+), Good (G), Fair (F), Poor (P)). | Grade mapping must be re-derived. Verify with one live call before implementation. |
| A-2 | The price suggestions endpoint requires the account's Discogs seller settings to be completed; otherwise it returns an error. This is already true today. | Condition values unavailable → FR-1.6 fallback applies, confidence drops (FR-2.2). |
| A-3 | `num_for_sale` reflects current marketplace supply, not completed sales. It is used as a **proxy** for liquidity. | Documented limitation; shown to the user in reasons text (FR-2.4). |
| A-4 | Discogs collections have default custom fields "Media Condition" and "Sleeve Condition". | Only affects the optional import (FR-1.8). |
| D-1 | Value-consuming features (analytics totals, value history snapshots, gain/loss) read value through a single function (see SR-1.5). | Inconsistent values across views. |

---

## 4. User requirements

| ID | User requirement |
|---|---|
| **UR-V1** | As a collector, I want to record the condition of my copy so that its value reflects what *my* record is worth, not a generic copy. |
| **UR-V2** | As a collector, I want my collection total to be realistic, so I can rely on it for insurance, selling or budgeting. |
| **UR-V3** | As a collector, I want to see how trustworthy each value is, so I know which numbers I can rely on and which are guesses. |
| **UR-V4** | As a collector who already graded records in Discogs, I don't want to re-enter conditions by hand. |

---

## 5. System requirements — Functional

### FR-new-1 — Condition-based valuation

| ID | Requirement | Priority | Traces to |
|---|---|---|---|
| **FR-1.1** | Each record shall have two optional fields: `media_condition` and `sleeve_condition`. | Must | UR-V1 |
| **FR-1.2** | `media_condition` shall accept only the Discogs/Goldmine grades: `M`, `NM`, `VG+`, `VG`, `G+`, `G`, `F`, `P`, or empty. `sleeve_condition` shall accept the same set plus `Generic`, `No Cover`, or empty. Any other value shall be rejected with HTTP 400. | Must | UR-V1 |
| **FR-1.3** | The add and edit APIs (`_api_add`, `_api_update` field allowlists in `server/handler.py`) shall accept both fields. | Must | UR-V1 |
| **FR-1.4** | On every price fetch/refresh, the system shall store the full grade→value map from price suggestions in a new field `price_by_condition` (JSON object keyed by short grade code, values as decimal strings), plus `prices_updated_at` (ISO-8601 UTC). Existing `price_low/median/high` fields shall continue to be populated unchanged for backward compatibility. | Must | UR-V1, UR-V2 |
| **FR-1.5** | The system shall compute a record's **value** as `price_by_condition[media_condition]`. | Must | UR-V1, UR-V2 |
| **FR-1.6** | Fallback rules, applied in order: (a) no `media_condition` set → use `VG+` (identical to current behaviour); (b) grade set but no suggestion for it → use the nearest *lower* grade that has a suggestion, else nearest higher; (c) no `price_by_condition` at all → use `price_median`; (d) nothing available → value is `null` (unpriced). The grade actually used shall be reported as `value_condition_used` and whether a fallback occurred as `value_fallback` (boolean). | Must | UR-V2 |
| **FR-1.7** | The background price refresh shall treat records with no `price_by_condition` as stale so existing records are back-filled over time, respecting the current rate limit (≥ 5 s between records, stop on HTTP 429). | Must | UR-V2 |
| **FR-1.8** | During Discogs collection import (`server/sync.py`), the system shall read the Media Condition and Sleeve Condition collection fields when present and map them to `media_condition` / `sleeve_condition`. Local values already set shall not be overwritten. | Could | UR-V4 |
| **FR-1.9** | The record detail and edit UI shall show grade selectors for media and sleeve, and display the value with the grade used (e.g. "€24.00 · valued at VG"). | Must | UR-V1 |

### FR-new-2 — Value confidence score

| ID | Requirement | Priority | Traces to |
|---|---|---|---|
| **FR-2.1** | Every valued record shall have a computed `value_confidence` of `high`, `medium`, `low`, or `none`, and a list `value_confidence_reasons` (machine codes, localised in UI). Confidence shall be computed at read time (it depends on the current date), not stored. | Must | UR-V3 |
| **FR-2.2** | Confidence rules (first matching rule wins; thresholds defined as constants in one module): | Must | UR-V3 |
| | • **none** — value is `null`. Reason: `no_price`. | | |
| | • **low** — any of: `num_for_sale` = 0 (`no_market`); `prices_updated_at` older than 90 days or missing (`stale_price`); value came from fallback (c) `price_median` with no condition map (`no_condition_data`). | | |
| | • **medium** — any of: `num_for_sale` between 1 and 4 (`thin_market`); `prices_updated_at` 31–90 days old (`aging_price`); grade fallback (b) used (`grade_fallback`); no `media_condition` set (`ungraded`). | | |
| | • **high** — otherwise (graded, exact grade price, ≥ 5 for sale, refreshed ≤ 30 days ago). | | |
| **FR-2.3** | All applicable reasons shall be returned, not only the one that set the level. | Should | UR-V3 |
| **FR-2.4** | The UI shall show a confidence indicator next to every displayed value (detail, collection list, analytics top-lists) with the reasons available on tap/hover, in all supported locales (`en`, `de`, `fr`, `ja`). Indicator must not rely on colour alone. | Must | UR-V3 |
| **FR-2.5** | Collection totals (`GET /api/analytics`) shall report value grouped by confidence: `{high, medium, low}` sums, `unpriced_count`, and a headline `reliable_total = high + medium`. | Must | UR-V2, UR-V3 |
| **FR-2.6** | Value-history snapshots shall store `reliable_total` and `low_confidence_total` in addition to the overall total, so the chart can show the reliable band. | Should | UR-V2 |
| **FR-2.7** | The collection view shall allow filtering by confidence level (integrates with `static/js/smart-filter.js`), so users can find records to grade or refresh. | Could | UR-V3 |

### Shared system requirements

| ID | Requirement |
|---|---|
| **SR-1.5** | A single pure function `record_value(record, now) -> {value, currency, condition_used, fallback, confidence, reasons}` shall be the only place value and confidence are calculated. Analytics, value history, gain/loss and the API serializer shall all call it. |
| **SR-1.6** | API responses for records (`GET /api/collection`, `GET /api/collection/{id}`) shall include `value`, `value_currency`, `value_condition_used`, `value_fallback`, `value_confidence`, `value_confidence_reasons`. |
| **SR-1.7** | JSON export (`/api/export`) and Drive backups shall include the new stored fields (`media_condition`, `sleeve_condition`, `price_by_condition`, `prices_updated_at`). Computed fields are not exported. |
| **SR-1.8** | Schema: add the four stored fields to the records schema (SQLite: `media_condition TEXT`, `sleeve_condition TEXT`, `price_by_condition TEXT` (JSON), `prices_updated_at TEXT`) with a `PRAGMA user_version` bump; existing rows default to NULL. |

---

## 6. System requirements — Non-functional

| ID | Category | Requirement |
|---|---|---|
| **NFR-V1** | Backward compatibility | For a record with no grade set, `value` shall equal today's `price_median` exactly. Upgrading shall not change any existing collection total until the user grades records or prices are refreshed. |
| **NFR-V2** | Performance | Computing value and confidence for 5,000 records shall add ≤ 50 ms to `GET /api/analytics` and `GET /api/collection` (p95, Raspberry Pi 4-class hardware). |
| **NFR-V3** | External API budget | No additional Discogs requests per refresh (both endpoints are already called). Back-fill (FR-1.7) shall respect the existing 5 s spacing and 429 handling. |
| **NFR-V4** | Accuracy | Sums shall use `Decimal`; displayed values rounded to 2 dp in the record currency. |
| **NFR-V5** | Usability / accessibility | Grade selectors use standard grade names with a short description (e.g. "VG+ — light signs of play"). Confidence indicator is distinguishable without colour (icon or label) and has an accessible label. |
| **NFR-V6** | Maintainability | Confidence thresholds (5 for-sale, 30/90 days) defined as named constants in one place; changing them requires no other code change. |
| **NFR-V7** | Dependencies | Standard library only; no new runtime dependencies. |
| **NFR-V8** | Testability | `record_value()` is a pure function with 100 % branch coverage of the fallback and confidence rules. |

---

## 7. Data and interface summary

**Stored record fields (new)**

```json
{
  "media_condition": "VG",
  "sleeve_condition": "VG+",
  "price_by_condition": {"M": "48.00", "NM": "40.00", "VG+": "30.00", "VG": "21.00", "G+": "12.00", "G": "8.00"},
  "prices_updated_at": "2026-11-20T08:14:03Z"
}
```

**Computed in API responses**

```json
{
  "value": "21.00",
  "value_currency": "EUR",
  "value_condition_used": "VG",
  "value_fallback": false,
  "value_confidence": "medium",
  "value_confidence_reasons": ["thin_market"]
}
```

**Analytics totals (addition to `GET /api/analytics`)**

```json
"value_by_confidence": {"high": "1840.00", "medium": "622.50", "low": "310.00"},
"reliable_total": "2462.50",
"unpriced_count": 14
```

---

## 8. Acceptance criteria

| ID | Given | When | Then |
|---|---|---|---|
| AC-1 | A record with `price_by_condition` = {VG+: 30, VG: 21} and no grade | It is fetched | `value` = 30, `value_condition_used` = VG+, confidence includes `ungraded` |
| AC-2 | Same record | User sets `media_condition` = VG | `value` = 21, no fallback |
| AC-3 | Record graded `F`, map has no F, G or G+ but has VG | Fetched | `value` = VG price, `value_fallback` = true, reason `grade_fallback` |
| AC-4 | Edit request with `media_condition` = "Excellent" | Submitted | HTTP 400, record unchanged |
| AC-5 | Record with `num_for_sale` = 0 | Fetched | confidence `low`, reason `no_market` |
| AC-6 | Graded record, exact grade price, 12 for sale, refreshed 3 days ago | Fetched | confidence `high`, no reasons |
| AC-7 | Same record, clock advanced 95 days | Fetched | confidence `low`, reason `stale_price` |
| AC-8 | Existing collection from before upgrade, no grades | Analytics opened | Overall total identical to pre-upgrade total (NFR-V1) |
| AC-9 | Price refresh runs on a record missing `price_by_condition` | Completes | Map and `prices_updated_at` stored; `price_low/median/high` unchanged in meaning |
| AC-10 | Discogs collection item with Media Condition "Very Good Plus (VG+)" and local grade empty | Sync import | `media_condition` = VG+; a locally set grade is never overwritten |
| AC-11 | UI in `ja` locale | Confidence reason shown | Reason text localised; indicator readable in greyscale |

---

## 9. Analysis and validation plan

| Requirement(s) | Analysis | Validation |
|---|---|---|
| FR-1.4–1.6 | Make one live call to `price_suggestions` and record the actual key names and currency (A-1). Check behaviour when seller settings are missing (A-2). | Unit tests on `_parse_prices` with recorded fixtures; AC-1 to AC-3, AC-9. |
| FR-1.2 | Confirm grade list against Discogs grading guide. | Boundary tests: every valid grade accepted, invalid strings / wrong case rejected (AC-4). |
| FR-1.8 | Inspect a real Discogs collection export for the condition field names and value format. | Sync tests with mocked collection payloads (AC-10). |
| FR-2.1–2.3 | Review thresholds with 3–5 collectors: does "5 for sale / 30 days" match their sense of "reliable"? Adjust constants (NFR-V6). | Table-driven unit tests covering every rule and combination; time injected via `now` (AC-5 to AC-7). |
| FR-2.5–2.6 | Agree headline definition (`reliable_total`) with users before UI work. | Analytics unit tests with hand-computed fixtures; `Decimal` drift test. |
| UR-V2 (real-world) | — | Ask 3–5 collectors to grade 20 records each, then compare More'Wax value against their own estimate or recent sale. Success: median error improves vs. ungraded VG+ value. |
| UR-V3 (real-world) | — | Usability test: "Which of your values would you trust for insurance?" Success: ≥ 4/5 users answer correctly using the indicator alone. |
| NFR-V1 | — | Golden test: totals before/after upgrade on a fixture collection are identical (AC-8). |
| NFR-V2 | — | Benchmark with 5,000 synthetic records, 100 runs, p95. |
| NFR-V5, FR-2.4 | — | Playwright screenshot test per locale; greyscale check of indicator (AC-11). |

---

## 10. Traceability

| User req | Functional | Non-functional | Acceptance |
|---|---|---|---|
| UR-V1 | FR-1.1, 1.2, 1.3, 1.5, 1.9 | NFR-V5 | AC-2, AC-4 |
| UR-V2 | FR-1.4, 1.6, 1.7, 2.5, 2.6 | NFR-V1, V3, V4 | AC-1, AC-3, AC-8, AC-9 |
| UR-V3 | FR-2.1–2.4, 2.7 | NFR-V5, V6, V8 | AC-5, AC-6, AC-7, AC-11 |
| UR-V4 | FR-1.8 | — | AC-10 |

---

## 11. Components affected

| Component | Change |
|---|---|
| `server/discogs.py` | `_parse_prices` also returns `price_by_condition`; set `prices_updated_at` |
| `server/valuation.py` (new) | `record_value()`, grade constants, confidence thresholds |
| `server/database.py` | Schema fields (SR-1.8) |
| `server/handler.py` | Allowlists (FR-1.3), validation (FR-1.2), stale criterion (FR-1.7), serializer (SR-1.6) |
| `server/analytics.py` | Totals by confidence (FR-2.5) via `record_value()` |
| Value history job | Store `reliable_total` (FR-2.6) |
| `server/sync.py` | Condition import (FR-1.8) |
| `static/js/detail.js`, `add-modal.js` | Grade selectors, value with grade (FR-1.9) |
| `static/js/collection.js`, `dashboard.js`, `smart-filter.js` | Confidence indicator and filter (FR-2.4, 2.7) |
| `static/locales/*.json` | Grade names, reason texts |
| `tests/` | `test_valuation.py` (new), additions to discogs, handler, sync, analytics tests |

**Rough effort:** backend 1.5–2 days, frontend 1.5–2 days, tests 1 day.

---

## 12. Open questions

1. Should the user be able to override a value manually (e.g. for a signed copy)? If yes, add `value_override` with confidence `user`.
2. Should sleeve condition apply a discount (e.g. −10 % per grade below media)? Currently out of scope because Discogs gives no data for it.
3. Are the 5 / 30 / 90 thresholds right? To be set from collector feedback (Section 9).
