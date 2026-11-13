import assert from 'node:assert/strict';
import test from 'node:test';
import { prepareRequest } from '../src/index.js';
import { copy, fixture } from './helpers.mjs';

test('request preparation takes an immutable snapshot of all nested acceptance conditions', () => {
  const request = copy(fixture.request);
  const prepared = prepareRequest(request);
  request.patch = 'different';
  request.path_policy.allowed_paths[0] = 'different/';
  request.assertions[0].pattern = 'different';
  assert.deepEqual(prepared.request, fixture.request);
  assert.equal(prepared.body, JSON.stringify(fixture.request));
  assert.ok(Object.isFrozen(prepared));
  assert.ok(Object.isFrozen(prepared.request));
  assert.ok(Object.isFrozen(prepared.request.assertions));
  assert.ok(Object.isFrozen(prepared.request.assertions[0]));
});

for (const [name, request] of [
  ['absent request', undefined],
  ['null request', null],
  ['array request', []],
  ['empty patch', { patch: '' }],
  ['blank patch', { patch: ' \n\t ' }],
  ['numeric patch', { patch: 12 }],
  ['oversized patch', { patch: 'x'.repeat(300 * 1024) }],
  ['oversized job', { patch: fixture.request.patch, job_id: 'j'.repeat(129) }],
  ['unknown contract field', { ...fixture.request, run_tests: true }],
  ['misspelled path restriction', { ...fixture.request, path_policy: { allowed_path: ['src/'] } }],
  ['non-array path restriction', { ...fixture.request, path_policy: { allowed_paths: 'src/' } }],
  ['non-string path restriction', { ...fixture.request, path_policy: { banned_paths: [null] } }],
  ['unknown assertion field', { ...fixture.request, assertions: [{ type: 'contains', pattern: 'new', flags: 'i' }] }],
  ['unknown assertion type', { ...fixture.request, assertions: [{ type: 'eval', pattern: 'new' }] }],
  ['non-string assertion', { ...fixture.request, assertions: [{ type: 'contains', pattern: null }] }],
  ['oversized assertion', { ...fixture.request, assertions: [{ type: 'contains', pattern: 'x'.repeat(257) }] }],
  ['empty assertion', { ...fixture.request, assertions: [{ type: 'contains', pattern: '' }] }],
  ['NaN input', { ...fixture.request, job_id: Number.NaN }],
  ['function input', { ...fixture.request, job_id: () => 'ignored' }],
  ['BigInt input', { ...fixture.request, job_id: 1n }],
  ['Date input', { ...fixture.request, job_id: new Date('2026-01-01') }],
]) {
  test(`request preparation rejects ${name} instead of weakening or coercing the contract`, () => {
    assert.throws(() => prepareRequest(request));
  });
}

test('minimal supported request can omit optional policy, assertions and job ID', () => {
  const prepared = prepareRequest({ patch: fixture.request.patch });
  assert.deepEqual(prepared.request, { patch: fixture.request.patch });
  assert.equal(typeof prepared.contractHash, 'string');
  assert.equal(prepared.contractHash.length, 64);
});

test('preparation preserves regular-expression text without executing it in the client', () => {
  const request = { ...fixture.request, assertions: [{ type: 'contains', pattern: '^(a+)+$' }] };
  assert.equal(prepareRequest(request).request.assertions[0].pattern, '^(a+)+$');
});

test('cyclic inputs are rejected without successful serialization', () => {
  const request = copy(fixture.request);
  request.assertions[0].message = request;
  assert.throws(() => prepareRequest(request));
});

test('prototype-bearing objects cannot smuggle hidden acceptance fields', () => {
  const request = Object.create({ path_policy: { banned_paths: ['src/'] } });
  request.patch = fixture.request.patch;
  assert.throws(() => prepareRequest(request));
});
