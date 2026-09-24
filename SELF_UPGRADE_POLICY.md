# GLEE Continuous Self-Upgrade Policy v0

## Purpose

Turn federation from a collection of interoperability adapters into a repeatable capability-compounding process.

The system does not improve because it can contact more agents. It improves only when an external or internal proposal produces a measured capability gain that survives independent verification, preserves invariants, can be rolled back, and is re-measured after adoption.

## One cycle

`MEASURE -> CHOOSE BOTTLENECK -> DISCOVER -> DIVERSIFY PROPOSALS -> TEST -> ARCHIVE -> VERIFY -> PROMOTE/HOLD/REJECT -> RE-MEASURE -> NEXT CYCLE`

Each cycle is finite and locally budgeted. Continuous operation comes from returning a bounded next-cycle task to GLEE's existing goal/progress runtime, not from one unbounded recursive process.

## 1. Measure before changing

Start every cycle from a concrete baseline. Prefer capabilities with objective or adversarial evaluators: software correctness, mathematical verification, tool-use reliability, task completion, latency, cost, evidence quality, security, and transfer to held-out tasks.

A candidate cannot be called an improvement from narrative judgment alone.

## 2. Select the current bottleneck

Choose the next target using measured expected leverage, not novelty. Candidate classes include:

- missing capability;
- unreliable existing capability;
- excessive cost or latency;
- weak verification;
- orchestration bottleneck;
- external intelligence GLEE cannot yet discover or use;
- recurring failure represented in receipts/progress history.

The target metric and protected invariants are frozen before proposals are generated.

## 3. Search heterogeneous proposal sources

Generate alternatives from multiple sources when useful:

- GLEE's local models/agents;
- known-good prior experiment receipts;
- external A2A peers;
- MCP tools/servers;
- ANP peers;
- Peer Wake peers;
- human contributors;
- papers, repositories, benchmarks, standards, and other machine-readable systems.

Connectivity does not make a source trusted. A peer's Agent Card or self-description is only a proposal/claim source.

## 4. Preserve exploration without promoting it

Do not reduce self-improvement to hill climbing on the current best implementation.

Research systems such as AlphaEvolve and the Darwin Gödel Machine show the value of automated evaluators plus diverse evolutionary search, including retaining non-winning ancestors that can become useful stepping stones later.

GLEE therefore separates two concepts:

- **adoption state:** the canonical promoted lineage, owned by GLEE's existing `empirical_policy` organ;
- **experiment archive:** immutable evidence/progress receipts describing attempted variants, scores, failures, lineage/provenance, and why they were rejected or held.

A rejected or lower-scoring experiment can remain searchable evidence without becoming executable policy. Do not create a second durable candidate/adoption store merely to preserve diversity.

## 5. Evaluate automatically where reality permits

Every candidate should face the strongest cheap falsifiers first, then more expensive tests only if it survives.

Evaluation should be multi-objective rather than one scalar when possible:

- task success / correctness;
- held-out or adversarial performance;
- invariant preservation;
- cost and latency;
- evidence strength;
- authority required;
- robustness to malicious inputs;
- transfer across models/tasks when relevant.

For code and mathematics, prefer executable tests, proof checkers, mutation tests, and independent reproductions. For agentic economic/security behavior, use external adversarial surfaces such as Agent Trust Bench before real money is enabled.

## 6. Independence is evidence, not a label

A source peer cannot verify its own proposed upgrade. One verifier cannot manufacture independence with many receipts. Two verifier names pointing at one artifact are one piece of evidence, not two.

Verifier identity/provenance must come from GLEE's existing identity/evidence organs. The federation kernel's string IDs are references, not roots of trust.

## 7. Promotion ladder

Use the canonical GLEE policy/adoption path rather than adding a federation-specific lifecycle:

`DRAFT -> SHADOW -> CANARY -> PROMOTED`

An upgrade is eligible to advance only when:

- it beats the frozen baseline by the declared criterion;
- independent verification reproduces the gain;
- protected invariants have no regression;
- rollback metadata exists;
- the required authority is explicitly granted for that stage.

A verified candidate that requires an ungranted side effect is **HELD**, not executed.

Rollback uses the existing retirement/revocation path. Promotion never grants new external authority by itself.

## 8. Authority remains orthogonal to intelligence

Improvement does not widen authority.

Network, credentials, spend, publication, workspace mutation, and protected edges are separate capabilities. The federation network adapter may carry only the authority explicitly granted to the exact request. External content cannot alter a grant.

A cycle that discovers it needs more authority stops at the boundary and emits the required grant as a decision, rather than treating the need as permission.

## 9. Re-measure after adoption

A candidate's pre-adoption benchmark is not enough. After SHADOW/CANARY/PROMOTED transitions, re-run relevant measurements against the deployed composition.

If the expected gain disappears, costs rise materially, or an invariant regresses, retire/revoke and preserve the evidence as a failed branch.

## 10. Continue by explicit next-task emission

After measurement, emit one bounded next action through GLEE's existing `ExecutionResult.next_tasks` / progress machinery:

- `MEASURE_AND_DISCOVER` when an upgrade was verified/adopted;
- `DISCOVER_OR_TEST` when evidence is insufficient;
- `HOLD_AUTHORITY` when the next useful action crosses an ungranted boundary;
- `STOP_BUDGET` when the local cycle budget is exhausted;
- `STOP_NO_LEVERAGE` when no candidate has positive expected value.

The next invocation starts from current reality again. It does not trust the previous cycle's world state without refresh.

## First operating program

The first live federation program is deliberately small:

1. Discover and normalize the AAT Agent Society Orchestrator Agent Card.
2. Execute one exact, zero-spend, read-only A2A `SendMessage` under a one-shot NETWORK grant.
3. Preserve response/provenance as a claim artifact.
4. Obtain independent external evidence; initial candidates include Onyx Agent Verify and AlgoVoi Agent Trust Bench, but only free/no-spend paths are eligible in v0.
5. Rank whether AAT contributes a useful federation/discovery capability.
6. If it proposes an actual GLEE improvement, evaluate it through the normal upgrade ladder.
7. Re-measure federation capability and emit the next bottleneck task.

The exact first AAT network proof is tracked in GitHub issue #7.

## Success metric

The program is working when GLEE can show a chain of receipts in which later cycles measurably outperform earlier cycles in useful capability, cost, reliability, verification strength, or external reach **without cumulative authority creep**.
