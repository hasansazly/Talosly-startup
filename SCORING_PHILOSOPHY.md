# Talosly Scoring Philosophy

## Core Principle

Talosly should use signal stacking, not single weak triggers. One weak signal
should usually produce `LOW` or `MEDIUM`; multiple exploit-like signals should
cross the alert threshold.

## Score Bands

| Band | Range | Meaning |
| --- | --- | --- |
| CRITICAL | 85-100 | High-confidence exploit behavior |
| HIGH | 70-84 | Strong exploit signals, human review now |
| MEDIUM | 40-69 | Suspicious, monitor closely |
| LOW | 10-39 | Mildly unusual but likely benign |
| NORMAL | 0-9 | Clean transaction |

## Current Signals

| Signal | Weight |
| --- | --- |
| BLACKLISTED_ADDRESS | 98 immediate |
| KNOWN_EXPLOIT_TARGET | 82 immediate |
| MAX_APPROVAL | +50 |
| PROXY_UPGRADE | +55 |
| FLASH_LOAN_SELECTOR | +45 |
| LARGE_VALUE_TRANSACTION | +40 |
| EXTREME_GAS_USAGE | +35 |
| ZERO_VALUE_CONTRACT_CALL | +35 |
| HIGH_GAS_EXECUTION | +25 |
| LARGE_PAYLOAD_PROBE | +20 |
| TRANSFER_FROM | +20 |
| NEW_WALLET | +10 |

## False Positive Controls

Known safe routers bypass behavior rules because they commonly produce high gas,
complex calldata, and large-value swaps:

- Uniswap V2 Router
- Uniswap V3 Router
- 1inch V5
- Uniswap Universal Router
- SushiSwap Router

New wallet, high gas, and large value should not alert alone.

## Euler Rule

Euler-style behavior is:

- zero ETH value
- contract function selector present
- high or extreme gas

This combination should produce at least `85`, even with blacklist disabled.
