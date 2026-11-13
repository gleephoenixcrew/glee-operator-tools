import { createHash, generateKeyPairSync, sign } from 'node:crypto';
import { readFileSync } from 'node:fs';

export const fixture = JSON.parse(readFileSync(new URL('./fixtures/receipt.fixture.json', import.meta.url), 'utf8'));
export const ENDPOINT = 'https://gleephoenix.com/api/x402/verify/patch';
export const USDC = '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913';
export const trust = Object.freeze({
  trustedPayTo: fixture.body.acceptance_receipt.payment.pay_to,
  trustedReceiptPublicKeyHex: fixture.body.acceptance_receipt.key.public_key_hex,
  payer: fixture.body.acceptance_receipt.payment.payer,
});
export const copy = value => structuredClone(value);
export const sha = text => createHash('sha256').update(text, 'utf8').digest('hex');

export function challenge() {
  return {
    x402Version: 2,
    resource: { url: ENDPOINT },
    accepts: [{
      scheme: 'exact', network: 'eip155:8453', amount: '50000',
      asset: USDC, payTo: trust.trustedPayTo, maxTimeoutSeconds: 300,
      extra: { name: 'USD Coin', version: '2' },
    }],
  };
}

export function jsonResponse(value, status = 200, headers = {}) {
  return new Response(JSON.stringify(value), {
    status, headers: { 'content-type': 'application/json', ...headers },
  });
}

export function transport(...responses) {
  const calls = [];
  const fetchImpl = async (url, options) => {
    calls.push({ url, ...options });
    if (!responses.length) throw new Error('Unexpected extra network request');
    const next = responses.shift();
    if (typeof next === 'function') return next(url, options);
    if (next instanceof Error) throw next;
    return next;
  };
  return { calls, fetchImpl };
}

export function wallet() {
  const instance = {
    chainId: 8453, address: trust.payer, signCalls: [],
    getChainId() { return this.chainId; },
    async getAddress() { return this.address; },
    async signTypedData(data) {
      this.signCalls.push(copy(data));
      return `0x${'ab'.repeat(65)}`;
    },
  };
  return instance;
}

// This signer exists only to generate adversarial/synthetic test cases. The
// immutable PASS/FAIL fixture remains the independent service compatibility oracle.
function sorted(value) {
  if (Array.isArray(value)) return value.map(sorted);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)
      .map(([key, item]) => [key, sorted(item)]));
  }
  return value;
}

export function resign(body, mutate = () => {}) {
  const pair = generateKeyPairSync('ed25519');
  const publicKeyHex = pair.publicKey.export({ type: 'spki', format: 'der' }).subarray(-32).toString('hex');
  const fingerprint = sha(publicKeyHex);
  const result = copy(body);
  result.acceptance_receipt.key = {
    algorithm: 'Ed25519', public_key_hex: publicKeyHex,
    fingerprint_sha256: fingerprint, key_id: `glee-acceptance-${fingerprint.slice(0, 16)}`,
  };
  mutate(result);
  delete result.acceptance_receipt.signature;
  result.acceptance_receipt.signature = sign(null,
    Buffer.from(sha(JSON.stringify(sorted(result.acceptance_receipt)))), pair.privateKey).toString('hex');
  return { body: result, trust: { ...trust, trustedReceiptPublicKeyHex: publicKeyHex } };
}

export function syntheticInsufficientEvidence() {
  return resign(fixture.body, body => {
    const receipt = body.acceptance_receipt;
    const r = body.result;
    r.verdict = 'INSUFFICIENT_EVIDENCE';
    receipt.outcome = r.verdict;
    // Explicit frozen v0 wire order; this helper never imports client hashing.
    const canonicalResult = {
      service: r.service, verification_mode: r.verification_mode,
      verdict: r.verdict, score: r.score, findings: r.findings,
      modified_files: r.modified_files, stats: r.stats, limitations: r.limitations,
    };
    const verificationHash = sha(JSON.stringify({
      canonical_request: {
        patch: fixture.request.patch,
        path_policy: fixture.request.path_policy,
        assertions: fixture.request.assertions,
        artifact_sha256: receipt.artifact_hash,
        job_id: fixture.request.job_id,
        acceptance_contract_hash: receipt.acceptance_contract_hash,
      },
      verifier: { name: 'glee-acceptance-verifier', version: '0.1.0' },
      verifier_version: '0.1.0',
      methodology_hash: '0f3b0b09ab269ca98c862b20ec6eb39af4de14751bd6a3a1bd47d947b5ac0cb1',
      policy_version: 'v1.0.0', canonical_result: canonicalResult,
    }));
    r.verification_hash = verificationHash;
    receipt.verification_hash = verificationHash;
  });
}
