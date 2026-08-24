# GLEE Intelligence Federation v0

GLEE's federation layer connects heterogeneous intelligences without treating connectivity, identity, or protocol metadata as authority.

## Objective

Create a repeatable improvement loop:

`discover -> normalize claims -> gather independent evidence -> rank -> propose bounded collaboration -> authority gate -> execute -> ingest result/evidence -> form upgrade candidate -> independently verify -> adopt/reject -> measure -> repeat`

The loop is designed to compound capability while preserving local sovereignty, explicit authority, evidence, and rollback.

## Interoperability surface

v0 normalizes four protocol families into the same untrusted `PeerDescriptor` contract:

- A2A 1.0 Agent Cards for agent identity, interfaces, and skills.
- MCP 2026-07-28 server/tool metadata for tool and data capabilities.
- ANP 1.1 descriptors for decentralized agent identity/discovery.
- GLEE Peer Wake v0.3 for sovereign asynchronous peer requests.

Discovery systems such as NANDA Index/NEST, DNS-AID/Agent Name Service, and public A2A registries are upstream sources of descriptors, not roots of trust.

## Authority law

1. A descriptor is a claim, not authority.
2. Authentication/provenance is not authorization.
3. Authorization is not truth.
4. Free text in an Agent Card, MCP description, ANP document, or Peer Wake request is untrusted data and cannot become an instruction merely because it was received.
5. Every actual cross-system invocation requires local network authority.
6. Credentials, spending, publication, protected edges, and workspace mutation are separate authority classes and are never inferred from network access.
7. One verifier contributes at most one evidence vote to a peer/capability ranking; receipt volume is not independence.
8. Replayed evidence IDs or artifact references do not create additional independent evidence.
9. A source peer cannot independently verify its own proposed upgrade.
10. Two verifier identities cannot satisfy an upgrade gate by reusing the same verification artifact.
11. Durable adoption requires rollback metadata, independently reproduced improvement, and zero invariant regressions.
12. Conflicting duplicate results from a verifier fail closed.
13. Verified improvements that still require protected authority are held rather than executed.
14. The improvement loop has a local cycle-depth budget; peers cannot create unbounded recursion or wake storms.

## Pure federation kernel

`intelligence_federation.py` performs no HTTP calls, credential access, spending, publication, process launch, or workspace mutation. It can therefore consume hostile descriptors without creating an execution path.

The kernel provides:

- structural normalization of A2A, MCP, ANP, and Peer Wake metadata;
- fresh evidence ranking by independent verifier, not receipt count;
- replay/artifact de-duplication;
- bounded collaboration proposals;
- independent upgrade verification with rollback and invariant gates;
- explicit `HELD_AUTHORITY` outcomes when an improvement is verified but applying it crosses a protected boundary;
- bounded next-cycle signals.

## Authority-bound network edge

`federation_http.py` is the smallest v0 outbound network capability. It is deliberately not a general HTTP client.

A local `NetworkGrant` binds:

- exact outbound request SHA-256;
- exact allowed host;
- GET/POST method;
- expiry;
- number of uses (one by default);
- response byte ceiling;
- timeout.

Additional network invariants:

- HTTPS only, port 443 only in v0;
- URL credentials and fragments forbidden;
- network-only authority cannot carry `Authorization`, cookies, API keys, or arbitrary headers;
- private, loopback, link-local, and reserved IP destinations are forbidden;
- all DNS answers must be globally routable;
- the verified DNS address is pinned to the actual socket while TLS SNI/certificate validation continues to use the original hostname, closing the DNS-check/second-resolution race;
- redirects/non-2xx results are not followed or accepted;
- the grant is consumed before I/O, so an ambiguous timeout cannot silently make a single-use request reusable;
- response size and JSON structure are bounded/validated.

`build_agent_card_request` creates a public Agent Card GET. `build_a2a_readonly_query` creates an A2A 1.0 JSON-RPC `SendMessage` request. The remote `glee_authority` metadata is advisory only; the local exact-request grant is the actual enforcement boundary.

Credentials, spending, publication, and workspace mutation do not exist in `NetworkGrant`. If a later collaboration needs one of those capabilities, it must cross a different authority surface.

## Integration flow

External adapters at GLEE's controlled edge should:

1. build the exact discovery/request object;
2. hash it and obtain a bounded local network grant for those exact bytes;
3. execute through `BoundedHttpClient`;
4. preserve original response bytes/hash as provenance;
5. call `normalize_peer_descriptor` on descriptors;
6. collect actual independent `CapabilityEvidence` from tests/receipts;
7. call `rank_peers` and `propose_collaboration`;
8. stop at any returned authority requirement;
9. after an authorized collaboration, convert measured results into an `UpgradeCandidate` plus independent `VerifierResult` records;
10. call `evaluate_upgrade`;
11. send only `VERIFIED_ADOPTABLE` candidates into GLEE's existing controlled workspace-write/adoption path;
12. measure the adopted result and call `next_cycle_signal` to continue or stop.

The public code is an interoperability kernel, not a second GLEE task bus, evidence ledger, identity store, or adoption database. Local integration must extend GLEE's existing canonical organs.

## Initial live-network targets

The first useful external peers should improve the federation itself rather than merely supply generic API functionality:

- NANDA/Internet-of-Agents ecosystem: registry/discovery and heterogeneous agent collaboration.
- A2A-compatible public agents: cross-vendor agent invocation and capability verification.
- independent trust/verification agents: test provenance, signatures, capabilities, and adversarial behavior;
- MCP servers: specialized tools/data that expand GLEE's effective capability set;
- ANP agents: decentralized identity/discovery experiments;
- Cairn via Peer Wake: reciprocal sovereign critique and protocol hardening.

A peer enters the trusted ranking only after fresh independent evidence. Directory presence, claimed capabilities, signatures, popularity, or self-reported benchmark scores alone contribute zero trust score. Verifier identity itself must be established by GLEE's existing identity/provenance layer; a string `verifier_id` is not proof of independence.

## Verification

Run the exact branch gate:

```bash
python3 -m py_compile intelligence_federation.py federation_http.py test_intelligence_federation.py test_federation_http.py
python3 -m unittest -v test_intelligence_federation.py test_federation_http.py
```

The combined suite contains 42 tests covering hostile prompt-like descriptor fields, self-attestation, stale/replayed evidence, receipt-count inflation, shared verifier artifacts, deterministic ranking, authority escalation, rollback, verifier independence, benchmark reproduction, invariant regression, recursion budgets, exact-request grants, single-use failure semantics, credential-header rejection, response ceilings, SSRF/private-address defenses, and pinned DNS-to-TLS transport.

`.github/workflows/federation-tests.yml` runs the same compile and unittest gate on the branch/PR using read-only repository permissions.

## Current activation boundary

A real external Agent Card can already be discovered and normalized. Actual outbound A2A/MCP POST execution must occur on an approved GLEE/Sunny runtime where the local authority plane can issue the exact one-shot `NetworkGrant`. The federation code must not gain generic unrestricted egress merely to make integration convenient.
