"""Pure federation contracts for GLEE's heterogeneous intelligence network.

This module intentionally performs no network, credential, spending, publication,
or mutation operations. It turns external protocol metadata into untrusted claims,
scores claims only with independent evidence, and decides whether an improvement
is verified/adoptable or must be held behind an authority boundary.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

FEDERATION_PROTOCOL = "glee.intelligence-federation/v0"


class PeerProtocol(str, Enum):
    A2A_1 = "a2a/1.0"
    MCP_2026_07_28 = "mcp/2026-07-28"
    ANP_1_1 = "anp/1.1"
    PEER_WAKE_0_3 = "glee.peer-wake/v0.3"


class Authority(str, Enum):
    NETWORK = "network"
    CREDENTIAL = "credential"
    SPEND = "spend"
    PUBLICATION = "publication"
    PROTECTED_EDGE = "protected_edge"
    WORKSPACE_WRITE = "workspace_write"


class UpgradeDecision(str, Enum):
    VERIFIED_ADOPTABLE = "VERIFIED_ADOPTABLE"
    HELD_AUTHORITY = "HELD_AUTHORITY"
    REJECTED = "REJECTED"


@dataclass(frozen=True)
class PeerDescriptor:
    """Normalized *claim* about an external intelligence.

    Nothing in this object is authority. `claims_hash` binds the normalized record
    to the original descriptor bytes so later evidence can name exactly what was
    evaluated.
    """

    peer_id: str
    protocol: PeerProtocol
    endpoint: str
    capabilities: Tuple[str, ...]
    observed_at: str
    claims_hash: str

    def validate(self) -> None:
        if not self.peer_id:
            raise ValueError("peer_id must be non-empty")
        _parse_time(self.observed_at)
        if any(not capability for capability in self.capabilities):
            raise ValueError("capabilities must be non-empty strings")


@dataclass(frozen=True)
class CapabilityEvidence:
    evidence_id: str
    peer_id: str
    capability: str
    verifier_id: str
    observed_at: str
    expires_at: str
    passed: bool
    quality: float
    artifact_ref: str

    def validate(self) -> None:
        if not all((self.evidence_id, self.peer_id, self.capability, self.verifier_id, self.artifact_ref)):
            raise ValueError("evidence identifiers and artifact_ref must be non-empty")
        observed = _parse_time(self.observed_at)
        expires = _parse_time(self.expires_at)
        if expires <= observed:
            raise ValueError("evidence expires_at must be after observed_at")
        if isinstance(self.quality, bool) or not isinstance(self.quality, (int, float)):
            raise ValueError("quality must be numeric")
        if not 0.0 <= float(self.quality) <= 1.0:
            raise ValueError("quality must be between 0 and 1")


@dataclass(frozen=True)
class RankedPeer:
    peer: PeerDescriptor
    score: float
    independent_evidence_count: int


@dataclass(frozen=True)
class CollaborationProposal:
    proposal_id: str
    protocol: str
    peer_id: str
    capability: str
    goal_hash: str
    endpoint: str
    required_authority: Tuple[Authority, ...]
    claims_hash: str

    @property
    def can_execute_without_grant(self) -> bool:
        return not self.required_authority


@dataclass(frozen=True)
class UpgradeCandidate:
    candidate_id: str
    source_peer_id: str
    capability: str
    baseline_score: float
    candidate_score: float
    rollback_ref: str
    required_authority: Tuple[Authority, ...] = ()
    proposal_ref: str = ""


@dataclass(frozen=True)
class VerifierResult:
    verifier_id: str
    candidate_id: str
    passed: bool
    benchmark_score: float
    invariant_failures: Tuple[str, ...]
    artifact_ref: str


@dataclass(frozen=True)
class UpgradePolicy:
    minimum_independent_verifiers: int = 2
    minimum_improvement: float = 0.0

    def validate(self) -> None:
        if self.minimum_independent_verifiers < 1:
            raise ValueError("minimum_independent_verifiers must be >= 1")
        if self.minimum_improvement < 0:
            raise ValueError("minimum_improvement must be >= 0")


@dataclass(frozen=True)
class UpgradeVerdict:
    decision: UpgradeDecision
    reason: str
    verifier_ids: Tuple[str, ...]
    evidence_hash: str


@dataclass(frozen=True)
class CycleSignal:
    cycle_number: int
    next_action: str
    reason: str


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def normalize_peer_descriptor(
    raw: Mapping[str, Any],
    protocol: PeerProtocol,
    *,
    observed_at: str,
) -> PeerDescriptor:
    """Normalize protocol metadata without interpreting free text as instructions.

    Only structural identity/endpoint/capability fields are used. Fields such as
    `description`, `prompt`, `system_prompt`, `authorized`, or claimed permissions
    remain inert source data and have zero effect on authority.
    """

    if not isinstance(raw, Mapping):
        raise ValueError("peer descriptor must be an object")
    _parse_time(observed_at)

    peer_id = ""
    endpoint = ""
    capabilities: Sequence[str] = ()

    if protocol is PeerProtocol.A2A_1:
        peer_id = _first_string(raw.get("id"), raw.get("name"))
        interfaces = raw.get("supportedInterfaces", ())
        if isinstance(interfaces, Sequence) and not isinstance(interfaces, (str, bytes)):
            for interface in interfaces:
                if isinstance(interface, Mapping):
                    endpoint = _first_string(interface.get("url"), interface.get("endpoint"))
                    if endpoint:
                        break
        endpoint = endpoint or _first_string(raw.get("url"), raw.get("endpoint"))
        capabilities = _names_from_objects(raw.get("skills", ()), ("id", "name"))

    elif protocol is PeerProtocol.MCP_2026_07_28:
        server_info = raw.get("serverInfo", {})
        if isinstance(server_info, Mapping):
            peer_id = _first_string(server_info.get("name"), raw.get("name"))
        else:
            peer_id = _first_string(raw.get("name"))
        endpoint = _first_string(raw.get("endpoint"), raw.get("url"))
        capabilities = _names_from_objects(raw.get("tools", ()), ("name", "id"))
        if not capabilities:
            caps = raw.get("capabilities", {})
            if isinstance(caps, Mapping):
                capabilities = tuple(str(name) for name, enabled in caps.items() if enabled)

    elif protocol is PeerProtocol.ANP_1_1:
        peer_id = _first_string(raw.get("did"), raw.get("id"), raw.get("name"))
        endpoint = _first_string(raw.get("serviceEndpoint"), raw.get("endpoint"), raw.get("url"))
        interfaces = raw.get("interfaces", ())
        capabilities = _names_from_objects(interfaces, ("id", "name", "protocol"))
        if not capabilities:
            values = raw.get("capabilities", ())
            if isinstance(values, Sequence) and not isinstance(values, (str, bytes)):
                capabilities = tuple(str(value) for value in values if isinstance(value, str) and value)

    elif protocol is PeerProtocol.PEER_WAKE_0_3:
        peer_id = _first_string(raw.get("sender"), raw.get("peer_id"), raw.get("name"))
        endpoint = _first_string(raw.get("endpoint"))
        capabilities = ("peer-wake",)

    else:  # pragma: no cover - enum exhaustiveness guard
        raise ValueError(f"unsupported peer protocol: {protocol}")

    normalized_caps = tuple(sorted(set(capability.strip() for capability in capabilities if capability.strip())))
    descriptor = PeerDescriptor(
        peer_id=peer_id.strip(),
        protocol=protocol,
        endpoint=endpoint.strip(),
        capabilities=normalized_caps,
        observed_at=observed_at,
        claims_hash=sha256_json(raw),
    )
    descriptor.validate()
    return descriptor


def rank_peers(
    peers: Iterable[PeerDescriptor],
    capability: str,
    evidence: Iterable[CapabilityEvidence],
    *,
    now: str,
) -> Tuple[RankedPeer, ...]:
    """Rank matching peers using fresh independent evidence only.

    Self-attestation and repeated evidence IDs contribute zero. A descriptor's
    mere existence contributes no trust score.
    """

    current = _parse_time(now)
    by_peer: Dict[str, Dict[str, CapabilityEvidence]] = {}
    for item in evidence:
        item.validate()
        if item.capability != capability or item.verifier_id == item.peer_id:
            continue
        if not _evidence_fresh(item, current):
            continue
        by_peer.setdefault(item.peer_id, {}).setdefault(item.evidence_id, item)

    ranked = []
    for peer in peers:
        peer.validate()
        if capability not in peer.capabilities:
            continue
        records = tuple(by_peer.get(peer.peer_id, {}).values())
        passed = tuple(record for record in records if record.passed)
        score = 0.0
        if passed:
            score = sum(float(record.quality) for record in passed) / len(passed)
        ranked.append(RankedPeer(peer=peer, score=round(score, 9), independent_evidence_count=len(passed)))

    return tuple(sorted(ranked, key=lambda item: (-item.score, -item.independent_evidence_count, item.peer.peer_id)))


def propose_collaboration(
    peer: PeerDescriptor,
    capability: str,
    goal: Mapping[str, Any],
    *,
    proposal_id: Optional[str] = None,
) -> CollaborationProposal:
    peer.validate()
    if capability not in peer.capabilities:
        raise ValueError(f"peer {peer.peer_id!r} does not claim capability {capability!r}")

    # Any actual cross-system invocation crosses the network authority boundary.
    # External metadata can never add or remove authority requirements.
    required = (Authority.NETWORK,)
    return CollaborationProposal(
        proposal_id=proposal_id or str(uuid.uuid4()),
        protocol=FEDERATION_PROTOCOL,
        peer_id=peer.peer_id,
        capability=capability,
        goal_hash=sha256_json(goal),
        endpoint=peer.endpoint,
        required_authority=required,
        claims_hash=peer.claims_hash,
    )


def evaluate_upgrade(
    candidate: UpgradeCandidate,
    results: Iterable[VerifierResult],
    *,
    policy: UpgradePolicy = UpgradePolicy(),
) -> UpgradeVerdict:
    """Evaluate an improvement without executing it.

    VERIFIED_ADOPTABLE means the candidate cleared evidence/invariant gates and
    requires no protected capability to *apply*. HELD_AUTHORITY means the evidence
    passed but execution still needs an external grant.
    """

    policy.validate()
    if not candidate.candidate_id or not candidate.source_peer_id or not candidate.capability:
        return _verdict(UpgradeDecision.REJECTED, "candidate identifiers must be non-empty", ())
    if not candidate.rollback_ref:
        return _verdict(UpgradeDecision.REJECTED, "rollback_ref is required", ())
    if candidate.candidate_score < candidate.baseline_score + policy.minimum_improvement:
        return _verdict(UpgradeDecision.REJECTED, "candidate does not beat baseline", ())

    by_verifier: Dict[str, VerifierResult] = {}
    for result in results:
        if result.candidate_id != candidate.candidate_id:
            continue
        if not result.verifier_id or not result.artifact_ref:
            continue
        if result.verifier_id == candidate.source_peer_id:
            continue
        by_verifier.setdefault(result.verifier_id, result)

    verifier_ids = tuple(sorted(by_verifier))
    if len(verifier_ids) < policy.minimum_independent_verifiers:
        return _verdict(UpgradeDecision.REJECTED, "insufficient independent verifiers", verifier_ids)

    selected = tuple(by_verifier[verifier_id] for verifier_id in verifier_ids)
    if any(not result.passed for result in selected):
        return _verdict(UpgradeDecision.REJECTED, "one or more independent verifiers failed", verifier_ids)
    failures = sorted({failure for result in selected for failure in result.invariant_failures if failure})
    if failures:
        return _verdict(UpgradeDecision.REJECTED, "invariant regression: " + ", ".join(failures), verifier_ids)
    if any(result.benchmark_score < candidate.candidate_score for result in selected):
        return _verdict(UpgradeDecision.REJECTED, "independent benchmark does not reproduce candidate score", verifier_ids)

    if candidate.required_authority:
        names = ",".join(sorted(authority.value for authority in candidate.required_authority))
        return _verdict(UpgradeDecision.HELD_AUTHORITY, "verified; external grant required: " + names, verifier_ids)

    return _verdict(UpgradeDecision.VERIFIED_ADOPTABLE, "verified improvement with rollback and no invariant regression", verifier_ids)


def next_cycle_signal(
    cycle_number: int,
    *,
    improvement_verified: bool,
    max_cycle_depth: int = 8,
) -> CycleSignal:
    if isinstance(cycle_number, bool) or cycle_number < 0:
        raise ValueError("cycle_number must be a non-negative integer")
    if isinstance(max_cycle_depth, bool) or max_cycle_depth < 1:
        raise ValueError("max_cycle_depth must be >= 1")
    if cycle_number >= max_cycle_depth:
        return CycleSignal(cycle_number, "STOP_BUDGET", "cycle depth budget exhausted")
    if improvement_verified:
        return CycleSignal(cycle_number + 1, "MEASURE_AND_DISCOVER", "measure adopted improvement, then seek the next bottleneck")
    return CycleSignal(cycle_number + 1, "DISCOVER_OR_TEST", "no verified improvement yet; gather better evidence or another peer")


def _verdict(decision: UpgradeDecision, reason: str, verifier_ids: Tuple[str, ...]) -> UpgradeVerdict:
    evidence_hash = sha256_json(
        {
            "decision": decision.value,
            "reason": reason,
            "verifier_ids": verifier_ids,
        }
    )
    return UpgradeVerdict(decision, reason, verifier_ids, evidence_hash)


def _names_from_objects(value: Any, keys: Sequence[str]) -> Tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    names = []
    for item in value:
        if isinstance(item, str) and item:
            names.append(item)
            continue
        if not isinstance(item, Mapping):
            continue
        for key in keys:
            candidate = item.get(key)
            if isinstance(candidate, str) and candidate:
                names.append(candidate)
                break
    return tuple(names)


def _first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return ""


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp must be a non-empty string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid ISO-8601 timestamp {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _evidence_fresh(evidence: CapabilityEvidence, now: datetime) -> bool:
    observed = _parse_time(evidence.observed_at)
    expires = _parse_time(evidence.expires_at)
    return observed <= now < expires
