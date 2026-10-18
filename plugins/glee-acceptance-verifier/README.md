# GLEE Acceptance Verifier for Cursor

Inspect the static patch-acceptance contract and try free fixed examples inside
a coding workflow. Paid verification of your own patch is advertised at
**0.05 USDC on Base** as observed October 18, 2026; confirm the current offer.

This plugin provides one skill and a Python 3 standard-library inspection helper.
It includes no payment client, wallet, install hooks, automatic network requests,
or MCP server. Loading the skill does not grant purchasing authority.

For local review, copy this entire directory into
`~/.cursor/plugins/local/glee-acceptance-verifier`, reload Cursor, and confirm
the skill appears in Customize. Existing marketplace installs take precedence;
organization policy can block local imports. The package has not yet been
installed in a real Cursor session or accepted by its marketplace.

Ask Cursor to inspect GLEE's patch-acceptance contract or demonstrate its fixed
PASS, FAIL and INSUFFICIENT_EVIDENCE cases. From this plugin's package root, run:

```sh
python3 skills/glee-patch-acceptance/scripts/inspect_service.py contract
python3 skills/glee-patch-acceptance/scripts/inspect_service.py preview pass
```

These are attributed public GETs. Previews accept no customer input and return
unsigned synthetic verdicts. Maintainers must add `--internal-test` before the
command to keep internal calls separate from the external campaign.

Before paid customer-patch use, authorize disclosure and an exact cumulative
budget, use your existing reviewed x402 V2 client and verify the signed receipt.
The skill explains this path and its limitations. It does not run tests, apply
patches, certify security, or prove correctness.

Contract: https://platform.gleephoenix.com/agents/services.json?service=patch_verification&ref=cursor_patch_20261018

The ref and request identifiers are attribution hints, not customer verification.
An unsigned sample, an installation, or an internal probe is not paid adoption.
