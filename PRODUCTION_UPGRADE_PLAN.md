# Talosly — Production-Grade Detection Engine Upgrade
## Complete Implementation Plan v2.0

---

# PART 1: SCORING PHILOSOPHY UPGRADE

## Current State
- 12 test cases, 12 passing
- Single-layer behavioral detection
- No protocol context
- No receipt/log analysis
- No feedback loop influence

## Target State
- 100+ test cases across 12 categories
- 5-layer detection pipeline
- Protocol-specific scoring profiles
- Receipt log analysis (token transfers, events)
- Feedback loop that improves scores over time

---

# PART 2: 100+ BENCHMARK CASE TYPES

## Category 1: TRUE_POSITIVE — Known Hacks (25 cases)
Expected: score >= 70

### Flash Loan Attacks
- euler_flash_loan_real (Euler $197M — real tx)
- euler_flash_loan_no_blacklist (behavioral only)
- cream_flash_loan_v1 (Cream $130M style)
- pancakebunny_flash_loan (PancakeBunny $45M style)
- beanstalk_flash_governance (Beanstalk $182M — flash loan + governance)
- fortress_protocol_flash (Fortress $3M style)
- deus_finance_flash (Deus Finance style)
- inverse_finance_flash (Inverse Finance $15M style)

### Reentrancy Attacks
- dao_reentrancy_classic (The DAO style)
- siren_protocol_reentrancy
- read_only_reentrancy (Curve style — read-only reentrancy)
- cross_contract_reentrancy

### Oracle Manipulation
- mango_markets_oracle (Mango $114M — price oracle manipulation)
- synthetix_oracle_attack
- venus_protocol_oracle
- raft_protocol_oracle

### Drain Patterns
- ronin_bridge_drain (Ronin $625M style — large ETH drain)
- nomad_bridge_drain (Nomad $190M style)
- harmony_bridge_drain
- wormhole_drain_style

### Approval Exploits
- unlimited_approval_drain
- permit2_signature_exploit
- multicall_approval_exploit

### Governance Attacks
- beanstalk_governance_real
- tornado_cash_governance
- build_finance_governance

---

## Category 2: TRUE_POSITIVE_BEHAVIORAL — No Blacklist (20 cases)
Expected: score >= 70
Purpose: Prove behavioral detection works WITHOUT knowing the attacker

All cases from Category 1 repeated with:
- blacklist_disabled: true
- fresh attacker address (never seen before)
- fresh contract address (deployed < 1 hour before attack)

Key principle: If your system ONLY catches known addresses, it's a blacklist,
not a detection engine. These tests prove real-time behavioral detection.

---

## Category 3: FALSE_POSITIVE_TEST — Normal DeFi (25 cases)
Expected: score <= 39

### Router Interactions
- uniswap_v2_normal_swap
- uniswap_v3_normal_swap
- uniswap_v3_large_whale_swap (>1000 ETH to safe router — should NOT alert)
- sushiswap_normal_swap
- 1inch_aggregated_swap
- curve_normal_swap
- balancer_normal_swap

### Lending Operations
- aave_v3_deposit
- aave_v3_borrow
- aave_v3_repay
- aave_v3_withdraw
- compound_supply
- compound_borrow
- maker_vault_open

### Normal User Behavior
- new_wallet_first_swap (new wallet should NOT alert alone)
- new_wallet_small_deposit
- high_gas_complex_route (high gas to safe router should NOT alert)
- whale_eth_transfer_simple (large ETH, 21K gas, no input)
- multisig_execution (gnosis safe execution — high gas, complex input)
- protocol_deployer_interaction (known protocol team address)

### Bridge Operations (legitimate)
- hop_protocol_bridge_normal
- across_protocol_bridge_normal
- stargate_bridge_normal
- canonical_bridge_deposit

### Governance (legitimate)
- compound_governance_vote
- uniswap_governance_vote
- aave_governance_vote

---

## Category 4: MEDIUM_RISK — Suspicious But Unconfirmed (15 cases)
Expected: score 40–69

- transferfrom_high_gas (transferFrom + high gas = 45)
- new_wallet_large_value (new wallet + 500 ETH = 50)
- new_contract_interaction (contract deployed 2 days ago = 45)
- failed_tx_then_success (probe pattern = 55)
- tornado_cash_recent_sender (interacted with mixer recently = 60)
- unusual_token_approval (approval to 3-day-old contract = 55)
- large_input_unknown_contract (complex calldata to unverified contract = 50)
- multiple_protocol_hops (3 protocol hops in 1 tx = 55)
- suspicious_timing (3 AM UTC + unusual value = 45)
- first_interaction_large_value (first tx to protocol, 200 ETH = 60)

---

## Category 5: CRITICAL_ALERT — Immediate Response (10 cases)
Expected: score >= 85

- blacklisted_to_address (score 98)
- blacklisted_from_address (score 98)
- max_approval_to_fresh_contract (50+55=105→98)
- proxy_upgrade_plus_drain (55+40=95)
- flash_loan_plus_extreme_gas (45+35=80 → 85 with new wallet)
- euler_exact_signature (zero-value + extreme-gas + known-selector)
- known_exploit_target_interaction (score 82+)
- bridge_drain_pattern (large ETH out + bridge contract + fresh wallet)
- governance_flash_borrow (flash loan selector + governance call = 90)
- coordinated_attack_multiblock (same pattern across 3 blocks = 95)

---

## Category 6: PROTOCOL_SPECIFIC — Context-Aware (15 cases)
Expected: varies by protocol profile

### Uniswap Profile (false_positive_prevention)
- uniswap_v3_500k_gas_normal (high gas for complex route — should NOT alert)
- uniswap_large_lp_add (large value LP addition — should NOT alert)
- uniswap_collectfees (protocol-normal operation)

### Aave Profile
- aave_liquidation_normal (high value, complex = MEDIUM not HIGH)
- aave_flashloan_legitimate (arbitrage via Aave flash = MEDIUM)
- aave_large_borrow_normal (large borrow by known wallet = LOW)

### Bridge Profile (HIGH sensitivity)
- bridge_unusual_recipient (different from/to chain address = HIGH)
- bridge_large_single_exit (>$1M leaving bridge in 1 tx = HIGH)
- bridge_repeated_small_exits (same amount × 10 = MEDIUM)

### Governance Profile
- governance_flash_borrow (flash loan + vote = CRITICAL)
- governance_large_delegation (massive voting power shift = MEDIUM)

---

# PART 3: NEW SIGNALS FROM RECEIPT LOGS

## Why Receipt Logs Matter
Current scoring only uses: to_address, from_address, value_eth, input_data, gas_used
Receipt logs reveal: what actually HAPPENED inside the transaction.

An attacker can disguise input_data. They cannot hide event logs.

## New Signals to Extract

### Token Transfer Analysis (from Transfer events)
Signal: MULTI_TOKEN_DRAIN
Trigger: >3 different tokens transferred OUT in same transaction
Weight: +40
Real example: Ronin hack moved ETH + USDC + multiple tokens simultaneously

Signal: CIRCULAR_TOKEN_FLOW
Trigger: Token A → Protocol → Token A (same token in and out, different amounts)
Weight: +45
Real example: Flash loan arbitrage gone wrong / price manipulation

Signal: LARGE_TOKEN_DRAIN_USD
Trigger: Token transfers with USD value > $500K leaving monitored protocol
Weight: +50
Real example: Any major token drain

### Event Log Analysis
Signal: EMERGENCY_PAUSE_EVENT
Trigger: Paused() or EmergencyShutdown() event fired by protocol
Weight: immediate 90 (protocol detected its own emergency)
Real example: Protocol self-pause during attack

Signal: OWNERSHIP_TRANSFER_EVENT
Trigger: OwnershipTransferred() to unknown address
Weight: +60
Real example: Rugpull step 1

Signal: UNAUTHORIZED_MINT_EVENT
Trigger: Transfer event FROM zero address (0x0000...0000) for large amount
Weight: +70
Real example: Unlimited mint exploits (Paid Network, etc.)

Signal: PROXY_UPGRADED_EVENT
Trigger: Upgraded() event in logs
Weight: +55
Real example: Proxy upgrade attacks

### Receipt-Level Signals
Signal: HIGH_LOG_COUNT
Trigger: >50 log entries in single transaction
Weight: +20
Real example: Reentrancy creates many repeated logs

Signal: REPEATED_CONTRACT_LOGS
Trigger: Same contract address appears >10 times in logs
Weight: +35
Real example: Reentrancy pattern — same contract emitting events repeatedly

Signal: REVERTED_SUBCALL
Trigger: Internal transaction reverted but outer succeeded
Weight: +15
Real example: Exploit probing which paths succeed

---

# PART 4: PROTOCOL-SPECIFIC SCORING PROFILES

## Design: ProtocolProfile dataclass

```python
@dataclass
class ProtocolProfile:
    name: str
    protocol_type: str  # ROUTER | LENDING | BRIDGE | GOVERNANCE | AMM | VAULT
    expected_gas_range: tuple[int, int]  # (min, max) normal gas
    expected_value_range: tuple[float, float]  # (min, max) normal ETH value
    high_value_threshold: float  # ETH value that triggers HIGH signal for THIS protocol
    safe_selectors: set[str]  # function selectors that are always normal
    sensitive_selectors: set[str]  # function selectors that need extra scrutiny
    bypass_behavioral: bool  # if True, skip _detect_exploit_behavior
    gas_multiplier: float  # multiply gas signals by this (0.5 = less sensitive)
```

## Profiles to Implement

### ROUTER Profile (Uniswap V2/V3, SushiSwap, 1inch)
```
expected_gas: 100K – 800K (high is NORMAL)
expected_value: 0 – unlimited (whales use routers)
bypass_behavioral: TRUE (routers are known safe)
high_value_threshold: N/A (bypassed)
```

### LENDING Profile (Aave, Compound, Maker)
```
expected_gas: 150K – 600K
expected_value: 0 – 10,000 ETH (large borrows are normal)
bypass_behavioral: FALSE
sensitive_selectors: flashLoan, liquidationCall
high_value_threshold: 5,000 ETH (above this = investigate)
gas_multiplier: 0.8 (slightly less sensitive than unknown contracts)
```

### BRIDGE Profile (Ronin, Nomad, Hop, Across)
```
expected_gas: 100K – 400K
expected_value: 0 – 1,000 ETH normal, >1,000 = SUSPICIOUS
bypass_behavioral: FALSE
sensitive: large single exits, unusual recipient addresses
high_value_threshold: 1,000 ETH (much lower than lending)
gas_multiplier: 1.2 (MORE sensitive — bridges are high-value targets)
```

### GOVERNANCE Profile (Compound, Uniswap, Aave governance)
```
expected_gas: 50K – 300K
expected_value: 0
bypass_behavioral: FALSE
sensitive_selectors: propose, castVote, execute, queue
CRITICAL rule: flash loan selector + governance selector in same tx = 90
```

### VAULT Profile (Yearn, Convex, Balancer vaults)
```
expected_gas: 200K – 800K
expected_value: 0 – 5,000 ETH
sensitive: unexpected withdraw all, emergency exit
high_value_threshold: 2,000 ETH
```

---

# PART 5: FALSE POSITIVE PREVENTION RULES

## Rule 1: Safe Router Hard Bypass
```
if to_address in KNOWN_SAFE_ROUTERS:
    skip _detect_exploit_behavior entirely
    return None (send to AI with low baseline)
```

## Rule 2: Signal Stacking Minimum
```
No single signal (except blacklist/exploit_target) should breach ALERT threshold (70)
Minimum 2 signals required to alert
Exception: MAX_APPROVAL alone = 50 (WATCH only, not ALERT)
Exception: PROXY_UPGRADE alone = 55 (WATCH only, not ALERT)
```

## Rule 3: New Wallet Cap
```
NEW_WALLET signal: +10 only
Cannot alone exceed LOW band (39)
Can be a tiebreaker when combined with other signals
```

## Rule 4: Gas Sensitivity by Protocol
```
ROUTER: high gas = 0 (bypass)
LENDING: high gas threshold raised by 20%
UNKNOWN: full sensitivity
BRIDGE: sensitivity raised by 20%
```

## Rule 5: Time-Decay for Repeated Patterns
```
If same from_address triggered WATCH 3x in last hour
without confirmed_threat = true:
  reduce subsequent scores by 15 (likely legitimate heavy user)
```

## Rule 6: Protocol Team Whitelist
```
If from_address is protocol's known deployer/multisig:
  reduce score by 20
  add KNOWN_PROTOCOL_TEAM indicator
```

## Rule 7: Value Context Normalization
```
1,000 ETH to Uniswap router = not suspicious (bypass)
1,000 ETH to unknown 3-day-old contract = HIGH
1,000 ETH to Aave = MEDIUM (large but normal for lending)
1,000 ETH to bridge = HIGH (above bridge threshold)
```

---

# PART 6: FEEDBACK LOOP DESIGN

## Database Schema Additions

```sql
-- Already exists (add if missing):
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS confirmed_threat BOOLEAN DEFAULT NULL;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS feedback_note TEXT DEFAULT NULL;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMP DEFAULT NULL;
ALTER TABLE alerts ADD COLUMN IF NOT EXISTS feedback_source VARCHAR(20) DEFAULT NULL;
-- feedback_source: 'user', 'admin', 'auto', 'rekt_news'

-- New table: track scoring accuracy over time
CREATE TABLE IF NOT EXISTS scoring_accuracy (
    id SERIAL PRIMARY KEY,
    week_start DATE NOT NULL,
    total_alerts INTEGER DEFAULT 0,
    confirmed_threats INTEGER DEFAULT 0,
    false_positives INTEGER DEFAULT 0,
    unreviewed INTEGER DEFAULT 0,
    true_positive_rate FLOAT DEFAULT 0,
    false_positive_rate FLOAT DEFAULT 0,
    avg_score_true_positive FLOAT DEFAULT 0,
    avg_score_false_positive FLOAT DEFAULT 0,
    created_at TIMESTAMP DEFAULT NOW(),
    UNIQUE(week_start)
);

-- New table: pattern performance tracking
CREATE TABLE IF NOT EXISTS signal_performance (
    id SERIAL PRIMARY KEY,
    signal_name VARCHAR(100) NOT NULL,
    total_fired INTEGER DEFAULT 0,
    confirmed_threat INTEGER DEFAULT 0,
    false_positive INTEGER DEFAULT 0,
    precision_rate FLOAT DEFAULT 0,
    last_updated TIMESTAMP DEFAULT NOW(),
    UNIQUE(signal_name)
);
```

## Feedback Loop Workflow

### Step 1: Alert fires → stored in alerts table with confirmed_threat = NULL

### Step 2: Admin reviews weekly (30 minutes)
- Open admin dashboard alerts page
- For each alert: was it real? Mark confirmed_threat = true/false
- Add feedback_note: "Euler-style flash loan — caught correctly"

### Step 3: Weekly scoring_accuracy update (automated)
```python
# Run every Sunday via cron or Railway scheduler
async def update_weekly_accuracy():
    week_alerts = await db.get_alerts_this_week()
    confirmed = sum(1 for a in week_alerts if a.confirmed_threat == True)
    false_pos = sum(1 for a in week_alerts if a.confirmed_threat == False)
    
    await db.upsert_scoring_accuracy(
        week_start=this_monday,
        total_alerts=len(week_alerts),
        confirmed_threats=confirmed,
        false_positives=false_pos,
        true_positive_rate=confirmed/len(week_alerts) if week_alerts else 0,
        false_positive_rate=false_pos/len(week_alerts) if week_alerts else 0,
    )
```

### Step 4: Signal performance tracking (automated)
```python
# After each labeled alert, update signal_performance
async def update_signal_performance(risk_factors: list[str], confirmed: bool):
    for signal in risk_factors:
        await db.increment_signal_performance(
            signal_name=signal,
            confirmed=confirmed
        )
```

### Step 5: Prompt tuning trigger
```
If any signal has precision_rate < 30% after 20 firings:
    → Add that signal to your "reduce weight" list
    → Update SCORING_PHILOSOPHY.md
    → Rerun replay_suite.py to verify improvement

If true_positive_rate < 70% in any week:
    → Review false negatives (missed threats)
    → Add new pattern to _detect_exploit_behavior
    → Add new test case to replay_test_cases.json
```

---

# PART 7: SAFE IMPLEMENTATION PLAN FOR CODEX

## Phase 1 — Zero Risk (Do This Week)
No changes to TransactionScorer API.
No changes to worker.py.
No changes to existing tests.

### Tasks:
1. Add 88 new test cases to replay_test_cases.json (expand from 12 to 100)
2. Add scoring_accuracy table migration
3. Add signal_performance table migration
4. Add feedback_note, reviewed_at, feedback_source columns to alerts
5. Add 👍/👎 endpoint: POST /api/alerts/{id}/feedback
6. Run replay_suite.py — all 100 cases must pass before Phase 2

### Codex prompt for Phase 1:
```
Add these database columns to alerts table (do not change any existing columns):
- confirmed_threat BOOLEAN DEFAULT NULL (already exists, verify)
- feedback_note TEXT DEFAULT NULL
- reviewed_at TIMESTAMP DEFAULT NULL  
- feedback_source VARCHAR(20) DEFAULT NULL

Create these new tables (do not modify existing tables):
[paste SQL from Part 6 above]

Add this FastAPI endpoint to backend/api/alerts.py:
POST /api/alerts/{alert_id}/feedback
Body: {confirmed_threat: bool, feedback_note: str}
Auth: Bearer token (same as existing endpoints)
Returns: {updated: true}

Do not change TransactionScorer.
Do not change worker.py.
Do not change any existing endpoints.
Run all existing tests — they must still pass.
```

## Phase 2 — Low Risk (Next Week)
Add new signals WITHOUT changing existing signal weights.
All new signals are ADDITIVE only.

### Tasks:
1. Add ProtocolProfile dataclass to scorer.py
2. Add 5 protocol profiles (Router, Lending, Bridge, Governance, Vault)
3. Add receipt log signal extraction (separate method, called after existing pre_screen)
4. All new signals must have their own test cases passing before merge

### Codex prompt for Phase 2:
```
Add to TransactionScorer in backend/services/scorer.py:

1. Add ProtocolProfile dataclass ABOVE the class definition
2. Add PROTOCOL_PROFILES dict with 5 profiles
3. Add _get_protocol_profile(to_address) method
4. Add _extract_log_signals(receipt_logs) method — NEW signals only
5. In score_transaction(), AFTER existing pre_screen call, also call
   _extract_log_signals if receipt data is available
6. Do NOT change pre_screen() logic
7. Do NOT change existing signal weights  
8. Do NOT change RiskScoreResponse structure
9. All 100 existing test cases must still pass
```

## Phase 3 — Medium Risk (Week 3)
Tune signal weights based on Phase 1 feedback data.
Only change weights if signal_performance data justifies it.

### Decision rule:
```
Only reduce a signal weight if:
  precision_rate < 40% AND total_fired > 20

Only increase a signal weight if:
  precision_rate > 80% AND total_fired > 20

Never change a weight without a corresponding test case proving the change works.
```

---

# PART 8: TESTS TO ADD BEFORE CHANGING SCORING LOGIC

## Rule: Every signal change needs 3 tests
1. Test that the signal FIRES correctly (true positive)
2. Test that the signal does NOT fire on normal tx (false positive prevention)
3. Test that the signal STACKS correctly with other signals

## Required New Tests (add to test_scorer.py)

### Protocol Profile Tests
```python
test_uniswap_v3_high_gas_no_alert()
test_uniswap_v3_large_value_no_alert()
test_aave_flash_loan_medium_not_critical()
test_bridge_large_exit_is_high_risk()
test_governance_flash_loan_is_critical()
```

### Signal Stacking Tests
```python
test_new_wallet_alone_is_low()           # +10 only = LOW
test_high_gas_alone_is_low()             # +25 only = LOW
test_new_wallet_plus_high_gas_is_low()   # +10+25=35 = still LOW
test_flash_loan_alone_is_medium()        # +45 = MEDIUM (not ALERT)
test_flash_loan_plus_extreme_gas_is_high()  # +45+35=80 = HIGH
test_max_approval_is_medium_not_critical()  # +50 = MEDIUM (not CRITICAL alone)
test_max_approval_plus_new_wallet_is_high() # +50+10=60 = MEDIUM still
test_proxy_upgrade_alone_is_medium()     # +55 = MEDIUM (not CRITICAL alone)
```

### Feedback Loop Tests
```python
test_feedback_endpoint_marks_confirmed()
test_feedback_endpoint_marks_false_positive()
test_signal_performance_increments_correctly()
```

### Receipt Log Tests (Phase 2)
```python
test_multi_token_drain_detected()
test_ownership_transfer_event_detected()
test_unauthorized_mint_detected()
test_high_log_count_is_medium()
test_repeated_contract_logs_is_high()
```

---

# PART 9: SUMMARY — WHAT MAKES THIS PRODUCTION-GRADE

## Current vs Target

| Metric | Current | Target |
|--------|---------|--------|
| Test cases | 12 | 100+ |
| Detection layers | 2 (blacklist + behavior) | 5 (blacklist + behavior + logs + profile + AI) |
| Protocol awareness | None | 5 profiles |
| False positive tracking | None | Automated weekly |
| Signal performance | None | Per-signal precision tracking |
| Feedback loop | DB columns only | Full workflow with dashboard |
| Receipt analysis | None | 8 new log signals |
| Benchmark coverage | Basic | All major attack types 2020–2025 |

## The One Number That Proves Production-Grade
False positive rate < 10% with true positive rate > 85%

You cannot know either number without the feedback loop.
Build the feedback loop first. Everything else is optimization.
