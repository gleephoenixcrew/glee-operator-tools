import assert from 'node:assert/strict';
import test from 'node:test';
import { authenticateDelivery, prepareRequest } from '../src/index.js';
import { copy, fixture, resign, syntheticInsufficientEvidence, trust } from './helpers.mjs';

test('independent service PASS fixture authenticates with exact frozen v0 hashes', () => {
  const prepared = prepareRequest(fixture.request);
  assert.equal(prepared.requestHash, 'e23f4b389d1149b5ab976bd5f30d81c69743eba2c78234195a926538d44e3b6e');
  assert.equal(prepared.artifactHash, 'fc184ca08f449a65ace3397a644cbae63f043393e6c71a175819838524e380de');
  assert.equal(prepared.contractHash, 'd8df41c29628a272f9569d053935bb220db11e501656246e00d1ab7272f00247');
  const delivered = authenticateDelivery(fixture.body, fixture.request, trust);
  assert.equal(delivered.receipt_verified, true);
  assert.equal(delivered.result.verdict, 'PASS');
  assert.equal(delivered.result.verification_hash, '96a941173693805118c051cb1078f4937f1083532b3c9037b88603b741bb7389');
});

test('independent service FAIL fixture stays FAIL despite authentic delivery', () => {
  const delivered = authenticateDelivery(fixture.fail.body, fixture.fail.request, trust);
  assert.equal(delivered.receipt_verified, true);
  assert.equal(delivered.result.verdict, 'FAIL');
  assert.equal(delivered.result.findings[0].rule, 'banned_path');
});

test('synthetic locally signed INSUFFICIENT_EVIDENCE stays distinct from PASS and FAIL', () => {
  const synthetic = syntheticInsufficientEvidence();
  const delivered = authenticateDelivery(synthetic.body, fixture.request, synthetic.trust);
  assert.equal(delivered.receipt_verified, true);
  assert.equal(delivered.result.verdict, 'INSUFFICIENT_EVIDENCE');
});

const deliveryMutations = [
  ['missing receipt', body => { delete body.acceptance_receipt; }],
  ['placeholder signature', body => { body.acceptance_receipt.signature = 'ed25519_sig_test'; }],
  ['forged signature', body => { body.acceptance_receipt.signature = '00'.repeat(64); }],
  ['changed outcome', body => { body.result.verdict = 'FAIL'; }],
  ['changed score', body => { body.result.score = 0; }],
  ['changed findings', body => { body.result.findings.push({ severity: 'CRITICAL', rule: 'injected', message: 'tampered' }); }],
  ['changed file list', body => { body.result.modified_files.push('secret.txt'); }],
  ['changed line count', body => { body.result.stats.added_lines++; }],
  ['changed limitations', body => { body.result.limitations = []; }],
  ['changed artifact hash', body => { body.result.artifact_hash = '00'.repeat(32); }],
  ['changed contract hash', body => { body.result.acceptance_contract_hash = '00'.repeat(32); }],
  ['changed verification hash', body => { body.result.verification_hash = '00'.repeat(32); }],
  ['unknown result methodology', body => { body.result.methodology_hash = '00'.repeat(32); }],
  ['unknown receipt methodology', body => { body.acceptance_receipt.methodology_hash = '00'.repeat(32); }],
  ['unknown receipt schema', body => { body.acceptance_receipt.receipt_schema = 'glee.acceptance_receipt.v99'; }],
  ['unknown request schema', body => { body.acceptance_receipt.request_hash_schema = 'unknown'; }],
  ['changed signing key', body => { body.acceptance_receipt.key.public_key_hex = '00'.repeat(32); }],
  ['changed key fingerprint', body => { body.acceptance_receipt.key.fingerprint_sha256 = '00'.repeat(32); }],
  ['changed key identifier', body => { body.acceptance_receipt.key.key_id += '-other'; }],
  ['changed receipt timestamp', body => { body.acceptance_receipt.issued_at = '2099-01-01T00:00:00.000Z'; }],
  ['changed content-addressed freshness', body => { body.acceptance_receipt.freshness.mode = 'live'; }],
  ['added signed payload field', body => { body.acceptance_receipt.untrusted_extra = 'must be covered'; }],
  ['non-finite score', body => { body.result.score = Number.NaN; }],
  ['wrong result mode', body => { body.result.verification_mode = 'tests_passed'; }],
  ['wrong top-level success', body => { body.ok = false; }],
];
for (const [name, mutate] of deliveryMutations) {
  test(`rejects ${name} without exposing an authenticated result`, () => {
    const body = copy(fixture.body);
    mutate(body);
    assert.throws(() => authenticateDelivery(body, fixture.request, trust));
  });
}

for (const [name, mutate] of [
  ['patch', r => { r.patch += '\n'; }],
  ['policy', r => { r.path_policy.allowed_paths = ['other/']; }],
  ['assertion', r => { r.assertions[0].pattern = 'different'; }],
  ['job identifier', r => { r.job_id = 'another-job'; }],
]) {
  test(`rejects a valid original signature bound to another ${name}`, () => {
    const request = copy(fixture.request);
    mutate(request);
    assert.throws(() => authenticateDelivery(fixture.body, request, trust));
  });
}

test('self-consistent attacker-signed receipt cannot supply its own trust anchor', () => {
  const attacker = resign(fixture.body);
  assert.throws(() => authenticateDelivery(attacker.body, fixture.request, trust));
  assert.equal(authenticateDelivery(attacker.body, fixture.request, attacker.trust).receipt_verified, true);
});

for (const [name, mutate] of [
  ['payer', b => { b.acceptance_receipt.payment.payer = `0x${'33'.repeat(20)}`; }],
  ['payee', b => { b.acceptance_receipt.payment.pay_to = `0x${'33'.repeat(20)}`; }],
  ['amount', b => { b.acceptance_receipt.payment.amount_atomic = '1'; }],
  ['network', b => { b.acceptance_receipt.payment.network = 'eip155:1'; }],
  ['settlement stage', b => { b.acceptance_receipt.payment.stage = 'pending'; }],
  ['methodology', b => { b.acceptance_receipt.methodology_hash = '00'.repeat(32); }],
  ['verifier extension', b => { b.acceptance_receipt.verifier.extra_claim = 'trusted'; }],
]) {
  test(`valid signature does not bypass the pinned ${name} binding`, () => {
    const synthetic = resign(fixture.body, mutate);
    assert.throws(() => authenticateDelivery(synthetic.body, fixture.request, synthetic.trust));
  });
}

test('unsigned result extensions are discarded and never promoted to authenticated facts', () => {
  const body = copy(fixture.body);
  body.result.tests_passed = true;
  body.result.authority = 'deploy-now';
  body.result.timestamp = '2099-01-01T00:00:00.000Z';
  body.extra_result = { deployment_approved: true };
  const result = authenticateDelivery(body, fixture.request, trust);
  assert.equal(result.result.verdict, 'PASS');
  for (const key of ['tests_passed', 'authority', 'timestamp', 'proof_hash', 'evidence', 'job_id']) {
    assert.equal(Object.hasOwn(result.result, key), false);
  }
  assert.equal(Object.hasOwn(result, 'extra_result'), false);
});

test('incoming object key order is normalized without changing the v0 service digest', () => {
  const request = {
    job_id: fixture.request.job_id,
    assertions: [{ pattern: 'new', type: 'contains' }],
    path_policy: { allowed_paths: ['src/'] }, patch: fixture.request.patch,
  };
  const body = copy(fixture.body);
  body.result.stats = { hunks_count: 1, deleted_lines: 1, added_lines: 1 };
  body.acceptance_receipt = Object.fromEntries(Object.entries(body.acceptance_receipt).reverse());
  assert.equal(authenticateDelivery(body, request, trust).receipt_verified, true);
  assert.equal(prepareRequest(request).body, prepareRequest(fixture.request).body);
});

test('authenticated output is detached from subsequent untrusted input mutations', () => {
  const body = copy(fixture.body);
  const result = authenticateDelivery(body, fixture.request, trust);
  body.result.modified_files[0] = 'injected-after-verification';
  body.acceptance_receipt.payment.payer = 'changed-after-verification';
  assert.equal(result.result.modified_files[0], 'src/index.js');
  assert.equal(result.acceptance_receipt.payment.payer, trust.payer);
});

test('historical content-addressed receipt authentication makes no fresh-execution claim', () => {
  const delivered = authenticateDelivery(fixture.body, fixture.request, trust);
  assert.equal(delivered.acceptance_receipt.freshness.mode, 'content_addressed');
  assert.equal(Object.hasOwn(delivered, 'fresh_execution_verified'), false);
  assert.equal(Object.hasOwn(delivered, 'onchain_settlement_verified'), false);
});
