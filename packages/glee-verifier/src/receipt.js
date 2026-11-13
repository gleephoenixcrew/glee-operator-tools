// Derived from GLEE's contribution to Coinbase AgentKit; see ../NOTICE.
import { createPublicKey, verify } from 'node:crypto';
import {
  VERIFIER, METHODOLOGY_HASH, GLEE_PRICE_ATOMIC, HASH, ADDRESS, VERDICTS,
  canonicalJson, sha256, jsonSnapshot, prepareRequest, validateTrust,
  isRecord, requireCondition, deepFreeze,
} from './protocol.js';

function validateReceipt(receipt) {
  const valid = isRecord(receipt) && receipt.receipt_schema === 'glee.acceptance_receipt.v0' &&
    receipt.service === '/api/x402/verify/patch' && receipt.capability === 'patch_verification' &&
    VERDICTS.includes(receipt.outcome) &&
    ['artifact_hash', 'acceptance_contract_hash', 'verification_hash', 'request_hash'].every(key =>
      typeof receipt[key] === 'string' && HASH.test(receipt[key])) &&
    receipt.request_hash_schema === 'glee.canonical_request.v1' &&
    (receipt.job_id === null || typeof receipt.job_id === 'string') &&
    canonicalJson(receipt.verifier) === canonicalJson(VERIFIER) && receipt.methodology_hash === METHODOLOGY_HASH &&
    isRecord(receipt.payment) && receipt.payment.network === 'eip155:8453' && receipt.payment.asset === 'USDC' &&
    receipt.payment.amount_atomic === GLEE_PRICE_ATOMIC && receipt.payment.stage === 'settled' &&
    typeof receipt.payment.pay_to === 'string' && ADDRESS.test(receipt.payment.pay_to) &&
    typeof receipt.payment.payer === 'string' && ADDRESS.test(receipt.payment.payer) &&
    isRecord(receipt.key) && receipt.key.algorithm === 'Ed25519' && typeof receipt.key.key_id === 'string' &&
    typeof receipt.key.public_key_hex === 'string' && HASH.test(receipt.key.public_key_hex) &&
    typeof receipt.key.fingerprint_sha256 === 'string' && HASH.test(receipt.key.fingerprint_sha256) &&
    typeof receipt.signature === 'string' && /^[a-fA-F0-9]{128}$/.test(receipt.signature);
  requireCondition(valid, 'INVALID_RECEIPT', 'Invalid or unsupported receipt schema');
}

function projectResult(result) {
  requireCondition(isRecord(result) && result.service === 'patch_verification' && result.verification_mode === 'static_analysis' &&
    VERDICTS.includes(result.verdict) && typeof result.score === 'number' && Number.isFinite(result.score) &&
    Array.isArray(result.findings) && result.findings.every(isRecord) &&
    Array.isArray(result.modified_files) && result.modified_files.every(path => typeof path === 'string') &&
    Array.isArray(result.limitations) && result.limitations.every(item => typeof item === 'string') &&
    isRecord(result.stats) && ['added_lines', 'deleted_lines', 'hunks_count'].every(key =>
      Number.isSafeInteger(result.stats[key]) && result.stats[key] >= 0) &&
    ['artifact_hash', 'acceptance_contract_hash', 'verification_hash'].every(key => typeof result[key] === 'string' && HASH.test(result[key])) &&
    result.methodology_hash === METHODOLOGY_HASH && isRecord(result.verifier) &&
    result.verifier.name === VERIFIER.name && result.verifier.version === VERIFIER.version,
    'INVALID_RESULT', 'Invalid or unsupported result schema');
  // v0 uses ordinary JSON.stringify here. This projection order is contractual.
  return {
    service: result.service,
    verification_mode: result.verification_mode,
    verdict: result.verdict,
    score: result.score,
    findings: result.findings,
    modified_files: result.modified_files,
    stats: {
      added_lines: result.stats.added_lines,
      deleted_lines: result.stats.deleted_lines,
      hunks_count: result.stats.hunks_count,
    },
    limitations: result.limitations,
  };
}

/** Authenticate a saved service delivery. Does not execute static analysis or pay. */
export function authenticateDelivery(input, inputRequest, inputTrust) {
  const trust = validateTrust(inputTrust, true);
  const prepared = prepareRequest(inputRequest);
  const body = jsonSnapshot(input);
  requireCondition(isRecord(body) && body.ok === true, 'INVALID_DELIVERY', 'Expected a successful delivery envelope');
  const receipt = body.acceptance_receipt;
  validateReceipt(receipt);
  const canonicalResult = projectResult(body.result);
  const { signature, ...signedPayload } = receipt;
  const key = receipt.key;
  requireCondition(key.public_key_hex === trust.trustedReceiptPublicKeyHex &&
    key.fingerprint_sha256 === sha256(key.public_key_hex) &&
    key.key_id === `glee-acceptance-${key.fingerprint_sha256.slice(0, 16)}`,
    'UNTRUSTED_KEY', 'Receipt signing key does not match the independent trust anchor');
  const publicKey = createPublicKey({
    key: Buffer.concat([Buffer.from('302a300506032b6570032100', 'hex'), Buffer.from(trust.trustedReceiptPublicKeyHex, 'hex')]),
    format: 'der', type: 'spki',
  });
  requireCondition(verify(null, Buffer.from(sha256(canonicalJson(signedPayload)), 'utf8'), publicKey, Buffer.from(signature, 'hex')),
    'INVALID_SIGNATURE', 'Invalid Ed25519 receipt signature');
  const { request, artifactHash, contractHash, requestHash } = prepared;
  const verificationHash = sha256(JSON.stringify({
    canonical_request: {
      patch: request.patch,
      path_policy: request.path_policy || {},
      assertions: request.assertions || [],
      artifact_sha256: artifactHash,
      job_id: request.job_id || null,
      acceptance_contract_hash: contractHash,
    },
    verifier: VERIFIER,
    verifier_version: VERIFIER.version,
    methodology_hash: METHODOLOGY_HASH,
    policy_version: 'v1.0.0',
    canonical_result: canonicalResult,
  }));
  requireCondition(receipt.request_hash === requestHash && receipt.artifact_hash === artifactHash &&
    receipt.acceptance_contract_hash === contractHash && receipt.job_id === (request.job_id || null) &&
    receipt.outcome === canonicalResult.verdict && receipt.verification_hash === verificationHash &&
    body.result.verification_hash === verificationHash && body.result.artifact_hash === artifactHash &&
    body.result.acceptance_contract_hash === contractHash &&
    receipt.payment.pay_to.toLowerCase() === trust.trustedPayTo.toLowerCase() &&
    receipt.payment.payer.toLowerCase() === trust.payer.toLowerCase(),
    'BINDING_MISMATCH', 'Receipt request, result, or payment binding mismatch');
  return deepFreeze({
    ok: true,
    receipt_verified: true,
    acceptance_receipt: receipt,
    result: { ...canonicalResult, verification_hash: verificationHash },
  });
}
