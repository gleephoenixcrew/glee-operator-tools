// Derived from GLEE's contribution to Coinbase AgentKit; see ../NOTICE.
import { createHash } from 'node:crypto';

export const GLEE_VERIFIER_URL = 'https://gleephoenix.com/api/x402/verify/patch';
export const BASE_CHAIN_ID = 8453;
export const BASE_USDC_MAINNET_ADDRESS = '0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913';
export const GLEE_PRICE_ATOMIC = '50000';
export const VERIFIER = Object.freeze({ name: 'glee-acceptance-verifier', version: '0.1.0' });
export const METHODOLOGY_HASH = '0f3b0b09ab269ca98c862b20ec6eb39af4de14751bd6a3a1bd47d947b5ac0cb1';
export const MAX_REQUEST_BYTES = 512 * 1024;
export const MAX_RESPONSE_BYTES = 1024 * 1024;
export const HASH = /^[a-f0-9]{64}$/;
export const ADDRESS = /^0x[a-fA-F0-9]{40}$/;
export const VERDICTS = Object.freeze(['PASS', 'FAIL', 'INSUFFICIENT_EVIDENCE']);

export class VerifierError extends Error {
  constructor(code, message, options = {}) {
    super(message, options.cause ? { cause: options.cause } : undefined);
    this.name = 'VerifierError';
    this.code = code;
    this.paymentMayHaveSettled = options.paymentMayHaveSettled === true;
  }
}

export function requireCondition(condition, code, message) {
  if (!condition) throw new VerifierError(code, message);
}

export const isRecord = value => value !== null && typeof value === 'object' && !Array.isArray(value);
export const sha256 = text => createHash('sha256').update(text, 'utf8').digest('hex');

// Reject non-JSON values before serialization: no silent NaN/undefined coercion,
// getters, custom toJSON methods, cycles, sparse arrays, or excessive nesting.
export function jsonSnapshot(value, maxBytes = MAX_RESPONSE_BYTES) {
  let nodes = 0;
  let stringBytes = 0;
  const active = new Set();
  function visit(item, depth) {
    requireCondition(depth <= 32 && ++nodes <= 100000, 'INVALID_JSON', 'JSON structure exceeds limits');
    if (item === null || typeof item === 'boolean') return;
    if (typeof item === 'string') {
      stringBytes += Buffer.byteLength(item, 'utf8');
      requireCondition(stringBytes <= maxBytes, 'INPUT_TOO_LARGE', 'JSON text exceeds byte limit');
      return;
    }
    if (typeof item === 'number') {
      requireCondition(Number.isFinite(item), 'INVALID_JSON', 'Numbers must be finite');
      return;
    }
    requireCondition(typeof item === 'object', 'INVALID_JSON', 'Only plain JSON data is supported');
    const prototype = Object.getPrototypeOf(item);
    requireCondition(Array.isArray(item) ? prototype === Array.prototype :
      prototype === Object.prototype || prototype === null, 'INVALID_JSON', 'Only plain JSON objects are supported');
    requireCondition(!active.has(item), 'INVALID_JSON', 'Cyclic data is unsupported');
    requireCondition(Object.getOwnPropertySymbols(item).length === 0, 'INVALID_JSON', 'Symbol properties are unsupported');
    const descriptors = Object.getOwnPropertyDescriptors(item);
    const keys = Object.keys(descriptors).filter(key => !(Array.isArray(item) && key === 'length'));
    requireCondition(!Array.isArray(item) || keys.length === item.length, 'INVALID_JSON', 'Sparse or decorated arrays are unsupported');
    active.add(item);
    for (const key of keys) {
      const descriptor = descriptors[key];
      requireCondition(descriptor.enumerable && Object.hasOwn(descriptor, 'value'), 'INVALID_JSON', 'Accessors and hidden fields are unsupported');
      requireCondition(!Array.isArray(item) || /^(0|[1-9][0-9]*)$/.test(key), 'INVALID_JSON', 'Array properties are unsupported');
      stringBytes += Buffer.byteLength(key, 'utf8');
      requireCondition(stringBytes <= maxBytes, 'INPUT_TOO_LARGE', 'JSON text exceeds byte limit');
      visit(descriptor.value, depth + 1);
    }
    active.delete(item);
  }
  visit(value, 0);
  const text = JSON.stringify(value);
  requireCondition(Buffer.byteLength(text, 'utf8') <= maxBytes, 'INPUT_TOO_LARGE', 'JSON encoding exceeds byte limit');
  return JSON.parse(text);
}

export function deepFreeze(value) {
  if (value && typeof value === 'object' && !Object.isFrozen(value)) {
    Object.values(value).forEach(deepFreeze);
    Object.freeze(value);
  }
  return value;
}

// This is the existing service's encoding, not a claim of RFC 8785 support.
export function canonicalJson(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(',')}]`;
  return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`;
}

function onlyKeys(value, allowed, name) {
  requireCondition(isRecord(value), 'INVALID_REQUEST', `${name} must be an object`);
  requireCondition(Object.keys(value).every(key => allowed.includes(key)), 'INVALID_REQUEST', `${name} contains an unsupported field`);
}

function boundedString(value, max, name, allowEmpty = false) {
  requireCondition(typeof value === 'string' && (allowEmpty || value.length > 0) && value.length <= max,
    'INVALID_REQUEST', `${name} must be a ${allowEmpty ? 'possibly empty ' : ''}string of at most ${max} characters`);
  return value;
}

/** Normalize once, retaining the original provider's field order for v0 hashes. */
export function prepareRequest(input) {
  const value = jsonSnapshot(input, MAX_REQUEST_BYTES);
  onlyKeys(value, ['patch', 'path_policy', 'assertions', 'job_id'], 'request');
  requireCondition(typeof value.patch === 'string' && value.patch.trim().length > 0,
    'INVALID_REQUEST', 'patch must be nonempty text');
  requireCondition(Buffer.byteLength(value.patch, 'utf8') <= 256 * 1024,
    'INPUT_TOO_LARGE', 'patch exceeds 256 KiB');
  const request = { patch: value.patch };
  if (Object.hasOwn(value, 'path_policy')) {
    onlyKeys(value.path_policy, ['allowed_paths', 'banned_paths'], 'path_policy');
    request.path_policy = {};
    for (const key of ['allowed_paths', 'banned_paths']) {
      if (!Object.hasOwn(value.path_policy, key)) continue;
      const paths = value.path_policy[key];
      requireCondition(Array.isArray(paths) && paths.length <= 128, 'INVALID_REQUEST', `${key} must contain at most 128 prefixes`);
      request.path_policy[key] = paths.map(path => boundedString(path, 512, key));
    }
  }
  if (Object.hasOwn(value, 'assertions')) {
    requireCondition(Array.isArray(value.assertions) && value.assertions.length <= 32,
      'INVALID_REQUEST', 'assertions must contain at most 32 rules');
    request.assertions = value.assertions.map(assertion => {
      onlyKeys(assertion, ['type', 'pattern', 'message'], 'assertion');
      requireCondition(['contains', 'prohibits'].includes(assertion.type), 'INVALID_REQUEST', 'Unsupported assertion type');
      const normalized = { type: assertion.type, pattern: boundedString(assertion.pattern, 256, 'pattern') };
      if (Object.hasOwn(assertion, 'message')) normalized.message = boundedString(assertion.message, 2048, 'message', true);
      return normalized;
    });
  }
  if (Object.hasOwn(value, 'job_id')) request.job_id = boundedString(value.job_id, 128, 'job_id', true);
  const body = JSON.stringify(request);
  const artifactHash = sha256(request.patch);
  const contractHash = sha256(canonicalJson({
    contract_schema: 'glee.acceptance.v0',
    path_policy: request.path_policy || {},
    assertions: request.assertions || [],
    verifier: VERIFIER,
    methodology_hash: METHODOLOGY_HASH,
  }));
  return deepFreeze({ request, body, requestHash: sha256(canonicalJson(request)), artifactHash, contractHash });
}

export function validateTrust(config, requirePayer = false) {
  requireCondition(isRecord(config) && typeof config.trustedPayTo === 'string' && ADDRESS.test(config.trustedPayTo) &&
    typeof config.trustedReceiptPublicKeyHex === 'string' && /^[a-fA-F0-9]{64}$/.test(config.trustedReceiptPublicKeyHex),
    'INVALID_TRUST', 'Configure independently trustedPayTo and trustedReceiptPublicKeyHex');
  if (requirePayer) requireCondition(typeof config.payer === 'string' && ADDRESS.test(config.payer),
    'INVALID_TRUST', 'Configure the expected payer');
  return Object.freeze({
    trustedPayTo: config.trustedPayTo,
    trustedReceiptPublicKeyHex: config.trustedReceiptPublicKeyHex.toLowerCase(),
    ...(requirePayer ? { payer: config.payer } : {}),
  });
}

export function validateEndpoint(endpoint) {
  let url;
  try { url = new URL(endpoint); } catch { throw new VerifierError('INVALID_ENDPOINT', 'Endpoint must be an HTTPS URL'); }
  requireCondition(typeof endpoint === 'string' && url.protocol === 'https:' && !url.username && !url.password && !url.hash &&
    url.href === endpoint, 'INVALID_ENDPOINT', 'Endpoint must be a canonical HTTPS URL without credentials or fragment');
  return endpoint;
}

export function validatePaymentChallenge(input, config) {
  const body = jsonSnapshot(input);
  const endpoint = validateEndpoint(config.endpoint ?? GLEE_VERIFIER_URL);
  requireCondition(typeof config.trustedPayTo === 'string' && ADDRESS.test(config.trustedPayTo), 'INVALID_TRUST', 'Missing trusted payment recipient');
  requireCondition(isRecord(body) && body.x402Version === 2 && isRecord(body.resource) &&
    body.resource.url === endpoint && Array.isArray(body.accepts) && body.accepts.length === 1,
    'INVALID_CHALLENGE', 'Expected one x402 V2 offer for the configured resource');
  const terms = body.accepts[0];
  requireCondition(isRecord(terms) && terms.scheme === 'exact' && terms.network === 'eip155:8453' &&
    terms.amount === GLEE_PRICE_ATOMIC && typeof terms.asset === 'string' && ADDRESS.test(terms.asset) &&
    terms.asset.toLowerCase() === BASE_USDC_MAINNET_ADDRESS.toLowerCase() &&
    typeof terms.payTo === 'string' && ADDRESS.test(terms.payTo) &&
    terms.payTo.toLowerCase() === config.trustedPayTo.toLowerCase() &&
    Number.isInteger(terms.maxTimeoutSeconds) && terms.maxTimeoutSeconds > 0 && terms.maxTimeoutSeconds <= 3600 &&
    isRecord(terms.extra) && terms.extra.name === 'USD Coin' && terms.extra.version === '2',
    'INVALID_CHALLENGE', 'Unapproved or malformed payment terms');
  return deepFreeze(terms);
}
