# Peer Wake Protocol v0.2 — Verification Receipt

Recorded: `2026-08-22T20:47:58Z`

This receipt records the verification state of the reviewable GLEE peer-wake
reference implementation after two defects were found during review and repaired:

1. wake budget was initially a static contract field and did not enforce a
   cumulative budget across accepted wakes;
2. replay check and receipt append were initially separate operations, allowing
   a concurrent duplicate-wake race.

v0.2 repairs both by deriving wake-budget use from accepted receipts sharing the
same `sleep_id`, and by holding one exclusive ledger lock across replay read →
budget read → policy decision → receipt append.

## Exact tested Git blobs

```text
peer_wake.py       a328136888d59a5bef16ae218b8a220f7ba1476f
test_peer_wake.py  0b301e2566fcc9898f064c3b2031f8c3832da472
PEER_WAKE.md       89723be8ef3158b25416cdf0ab4e58190d288295
```

The first two files above were the exact files executed locally. The documentation
blob was independently hash-compared with the pushed branch.

## Compile

```bash
python3 -m py_compile peer_wake.py test_peer_wake.py
```

Result: `PASS`

## Hostile / acceptance suite

```bash
python3 test_peer_wake.py
```

Result:

```text
Ran 18 tests

OK
```

Coverage includes:

- valid authenticated wake and receipt;
- bad signature cannot consume a legitimate nonce;
- replay by envelope ID;
- replay by sender nonce with a new envelope ID;
- **four concurrent identical valid requests authorize exactly one wake**;
- expiry and future-clock-skew rejection;
- wrong recipient rejection;
- peer wake disabled by sleep contract;
- sleep-contract peer sender allowlist;
- minimum-sleep deferral;
- zero/negative wake-budget behavior;
- **receipt-derived cumulative wake budget**;
- non-integer priority fails as typed malformed input rather than raising;
- unknown envelope fields fail closed;
- transport/reply metadata does not grant authority;
- receipt-chain tamper detection.

## CLI end-to-end

Executed against the exact tested `peer_wake.py`:

```text
unsigned envelope
  → peer_wake.py sign
  → peer_wake.py decide
  → append/fsync receipt
  → peer_wake.py verify-receipts
```

Observed decision:

```json
{
  "decision": "ACCEPT_WAKE_NOW",
  "reason": "authenticated peer wake accepted",
  "should_wake": true
}
```

Receipt verification:

```json
{
  "valid": true
}
```

## Claim boundary

This receipt establishes behavior of the standalone reference gate in
`glee-operator-tools`. It does **not** establish that the private/main GLEE
runtime currently accepts external peer wakes: that requires integration into the
live Harbor/ARIADNE continuity state and controlled launcher/Agent Bus in the core
GLEE repository.
