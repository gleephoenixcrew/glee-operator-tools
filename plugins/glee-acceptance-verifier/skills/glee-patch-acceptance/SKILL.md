---
name: glee-patch-acceptance
description: Inspect GLEE's patch-acceptance service and try free static-check examples when a coding task needs a separate check of unified-diff path rules or added-line assertions; explain the authorized paid path for customer patches.
---

# GLEE patch acceptance

GLEE checks unified diffs against declared path rules and added-line assertions.
It does not apply patches, run tests, certify security, or prove correctness.
Use ordinary tests and review alongside any static acceptance result.

## Inspect and evaluate

Retrieve the current contract at
https://platform.gleephoenix.com/agents/services.json?service=patch_verification&ref=cursor_patch_20261018.
The inspectable request example and exact input/output contract are in that JSON.
The bundled [contract observation](references/contract-observed.json) is a dated
example; fetch the live offer before a purchase.

For a deterministic helper, resolve `scripts/inspect_service.py` relative to this
SKILL.md. Run it with Python 3 using `contract` or `preview pass`, `preview fail`,
or `preview insufficient`. It sends only GET requests to a fixed GLEE URL and
requires no wallet, sign-in, repository access, or third-party packages.
For maintainer tests, place `--internal-test` before the command to use the
separate internal campaign and user-agent. Never count those calls as customers.

Free previews evaluate fixed synthetic examples, accept no customer patch, cost
zero, and return unsigned results. Show the input, verdict, findings and scope.
Keep `observation.discovery_source` if the operator later chooses paid use.

## Decide whether paid use fits

Observed October 18, 2026: the advertised price is **0.05 USDC**, 50000 atomic
units with six decimals on Base (`eip155:8453`). The endpoint is
`POST https://platform.gleephoenix.com/api/x402/verify/patch`.
Inputs include `patch`, optional `path_policy`, `assertions`, artifact/contract
hashes and `job_id`. Assertion patterns are JavaScript regular expressions on
added lines (1–256 characters), despite older public copy saying "literal".
Binary diffs, quoted paths and rename-only changes are unsupported; unresolved
commit/URL artifact bindings yield INSUFFICIENT_EVIDENCE.

Outputs are PASS, FAIL or INSUFFICIENT_EVIDENCE with findings and a signed
acceptance receipt for a fulfilled paid request. PASS concerns the declared
checks only. The free preview is unsigned and cannot verify a customer patch.

This plugin supplies no wallet or paid-execution implementation. If the client
lacks a reviewed x402 V2 payment path, report that limitation and the price.
Installation grants no payment or private-code disclosure authority. Confirm
the operator's existing mandate or obtain their permission for the exact
service, code disclosure, chain, recipient, amount and cumulative budget before
signing. Do not create/fund wallets or increase a budget as part of inspection.

Use the operator's reviewed x402 V2 client and the current challenge from
https://platform.gleephoenix.com/docs/x402. Bind the exact URL, network, asset,
recipient, amount and identical request body. Reconcile an uncertain attempt
before issuing a new signature. Never send wallet keys as tool input/telemetry.

Verify the paid Ed25519 receipt offline using the documented canonicalization,
an independently trusted key fingerprint and the request's artifact, contract,
verdict and settlement bindings. Keys are published at
https://platform.gleephoenix.com/.well-known/glee-receipt-keys.
A newly fetched key is a trust-on-first-use decision. HTTP 200 is insufficient
evidence of acceptance or independently confirmed settlement.

If supported, carry the preview's `observation.discovery_source` as
`X-Discovery-Source` on an authorized paid call. The campaign/ref and header are
self-reported linkage hints. They establish neither operator independence nor
that a marketplace listing caused a purchase. Do not add private code, identity,
signatures or wallet secrets to attribution fields.
