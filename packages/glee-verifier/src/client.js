// Derived from GLEE's contribution to Coinbase AgentKit; see ../NOTICE.
import { randomBytes } from 'node:crypto';
import {
  GLEE_VERIFIER_URL, BASE_CHAIN_ID, BASE_USDC_MAINNET_ADDRESS, GLEE_PRICE_ATOMIC,
  MAX_RESPONSE_BYTES, ADDRESS, VerifierError, requireCondition, isRecord,
  prepareRequest, validateTrust, validateEndpoint, validatePaymentChallenge,
  deepFreeze,
} from './protocol.js';
import { authenticateDelivery } from './receipt.js';

function parseJson(bytes) {
  try {
    return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
  } catch (cause) {
    throw new VerifierError('INVALID_JSON', 'Response is not valid UTF-8 JSON', { cause });
  }
}

async function readBytes(response, maxBytes, signal) {
  const length = response.headers.get('content-length');
  if (length !== null) requireCondition(/^\d+$/.test(length) && Number(length) <= maxBytes,
    'RESPONSE_TOO_LARGE', 'Response Content-Length exceeds the byte limit');
  requireCondition(response.body && typeof response.body.getReader === 'function', 'INVALID_RESPONSE', 'Response has no readable body');
  const reader = response.body.getReader();
  const cancelReader = () => { void reader.cancel().catch(() => {}); };
  signal.addEventListener('abort', cancelReader, { once: true });
  if (signal.aborted) cancelReader();
  const chunks = [];
  let count = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      requireCondition(!signal.aborted, 'TIMEOUT', 'Response body read was aborted');
      if (done) break;
      count += value.byteLength;
      requireCondition(count <= maxBytes, 'RESPONSE_TOO_LARGE', 'Response body exceeds the byte limit');
      chunks.push(Buffer.from(value));
    }
    return Buffer.concat(chunks, count);
  } catch (error) {
    void reader.cancel().catch(() => {});
    throw error;
  } finally {
    signal.removeEventListener('abort', cancelReader);
    reader.releaseLock();
  }
}

/** No imports or assumptions about AgentKit, wallet SDKs, or an agent runtime. */
export function createVerifierClient(config) {
  const trust = validateTrust(config);
  const endpoint = validateEndpoint(config.endpoint ?? GLEE_VERIFIER_URL);
  const fetchImpl = config.fetchImpl ?? globalThis.fetch;
  const timeoutMs = config.timeoutMs ?? 10000;
  const maxResponseBytes = config.maxResponseBytes ?? MAX_RESPONSE_BYTES;
  requireCondition(typeof fetchImpl === 'function', 'INVALID_CONFIG', 'A fetch implementation is required');
  requireCondition(Number.isInteger(timeoutMs) && timeoutMs > 0 && timeoutMs <= 60000,
    'INVALID_CONFIG', 'timeoutMs must be an integer from 1 through 60000');
  requireCondition(Number.isInteger(maxResponseBytes) && maxResponseBytes > 0 && maxResponseBytes <= MAX_RESPONSE_BYTES,
    'INVALID_CONFIG', 'maxResponseBytes must be positive and at most 1 MiB');

  // One deadline covers response headers AND all body chunks. No retry here.
  async function post(body, paymentHeader) {
    const controller = new AbortController();
    let timer;
    let response;
    const timeout = new Promise((_, reject) => {
      timer = setTimeout(() => {
        controller.abort();
        reject(new VerifierError('TIMEOUT', 'Verifier request exceeded its deadline'));
      }, timeoutMs);
    });
    const operation = (async () => {
      response = await fetchImpl(endpoint, {
        method: 'POST', redirect: 'error', signal: controller.signal,
        headers: { 'Content-Type': 'application/json', ...(paymentHeader ? { 'PAYMENT-SIGNATURE': paymentHeader } : {}) },
        body,
      });
      requireCondition(response && response.headers && Number.isInteger(response.status), 'INVALID_RESPONSE', 'Invalid HTTP response');
      requireCondition(!response.redirected && (!response.url || response.url === endpoint),
        'REDIRECT_REJECTED', 'Verifier redirects are not allowed');
      const expected = paymentHeader ? 200 : 402;
      requireCondition(response.status === expected, 'HTTP_STATUS', `Expected HTTP ${expected}; received ${response.status}`);
      const encoded = paymentHeader ? null : response.headers.get('PAYMENT-REQUIRED');
      if (encoded !== null) {
        requireCondition(encoded.length > 0 && encoded.length <= Math.min(32768, maxResponseBytes * 2) &&
          encoded.length % 4 === 0 && /^[A-Za-z0-9+/]+={0,2}$/.test(encoded),
          'INVALID_CHALLENGE', 'Malformed PAYMENT-REQUIRED header');
        const decoded = Buffer.from(encoded, 'base64');
        requireCondition(decoded.length <= maxResponseBytes && decoded.toString('base64') === encoded,
          'INVALID_CHALLENGE', 'Noncanonical or oversized PAYMENT-REQUIRED header');
        if (response.body) void response.body.cancel().catch(() => {});
        return parseJson(decoded);
      }
      return parseJson(await readBytes(response, maxResponseBytes, controller.signal));
    })();
    try {
      return await Promise.race([operation, timeout]);
    } catch (error) {
      controller.abort();
      if (response?.body && !response.body.locked) void response.body.cancel().catch(() => {});
      if (error instanceof VerifierError) throw error;
      throw new VerifierError('TRANSPORT_ERROR', 'Verifier transport failed', { cause: error });
    } finally {
      clearTimeout(timer);
    }
  }

  async function getTerms(prepared) {
    return validatePaymentChallenge(await post(prepared.body), { endpoint, trustedPayTo: trust.trustedPayTo });
  }

  async function inspectQuote(input) {
    const prepared = prepareRequest(input);
    const terms = await getTerms(prepared);
    return deepFreeze({
      status: 'PAYMENT_REQUIRED',
      endpoint,
      request_hash: prepared.requestHash,
      network: terms.network,
      amount_atomic: terms.amount,
      pay_to: terms.payTo,
      terms,
    });
  }

  async function verifyPatch(input, payment) {
    // Keep this synchronous prefix ahead of the first await. An agent-supplied
    // patch cannot supply a wallet or silently opt the application into spending.
    const prepared = prepareRequest(input);
    requireCondition(isRecord(payment) && payment.maxAmountAtomic === GLEE_PRICE_ATOMIC,
      'PAYMENT_NOT_AUTHORIZED', 'An explicit per-call maxAmountAtomic of 50000 is required');
    const wallet = payment.wallet;
    requireCondition(wallet && ['getChainId', 'getAddress', 'signTypedData'].every(key => typeof wallet[key] === 'function'),
      'INVALID_WALLET', 'Supply an explicitly authorized wallet adapter');
    // Capture methods so later mutation of the options cannot substitute a signer.
    const getChainId = wallet.getChainId.bind(wallet);
    const getAddress = wallet.getAddress.bind(wallet);
    const signTypedData = wallet.signTypedData.bind(wallet);
    requireCondition(await getChainId() === BASE_CHAIN_ID, 'WRONG_CHAIN', 'Wallet must be on Base mainnet (8453)');
    const payer = await getAddress();
    requireCondition(typeof payer === 'string' && ADDRESS.test(payer), 'INVALID_WALLET', 'Invalid payer address');
    const terms = await getTerms(prepared);
    const authorization = deepFreeze({
      from: payer,
      to: trust.trustedPayTo,
      value: GLEE_PRICE_ATOMIC,
      validAfter: 0,
      validBefore: Math.floor(Date.now() / 1000) + terms.maxTimeoutSeconds,
      nonce: `0x${randomBytes(32).toString('hex')}`,
    });
    const typedData = deepFreeze({
      domain: { name: 'USD Coin', version: '2', chainId: BASE_CHAIN_ID, verifyingContract: BASE_USDC_MAINNET_ADDRESS },
      types: {
        TransferWithAuthorization: [
          { name: 'from', type: 'address' }, { name: 'to', type: 'address' },
          { name: 'value', type: 'uint256' }, { name: 'validAfter', type: 'uint256' },
          { name: 'validBefore', type: 'uint256' }, { name: 'nonce', type: 'bytes32' },
        ],
      },
      primaryType: 'TransferWithAuthorization',
      message: authorization,
    });
    // A wallet remains a trusted capability. These rechecks detect common
    // account/network switches; no client can make an arbitrary wallet atomic.
    const currentPayer = await getAddress();
    requireCondition(typeof currentPayer === 'string' && currentPayer.toLowerCase() === payer.toLowerCase(),
      'WALLET_CHANGED', 'Wallet account changed before signing');
    requireCondition(await getChainId() === BASE_CHAIN_ID, 'WALLET_CHANGED', 'Wallet network changed before signing');
    const signature = await signTypedData(typedData);
    requireCondition(typeof signature === 'string' && /^0x[a-fA-F0-9]{130}$/.test(signature),
      'INVALID_SIGNATURE', 'Wallet must return a 65-byte EIP-3009 signature');
    requireCondition(Math.floor(Date.now() / 1000) < authorization.validBefore, 'AUTHORIZATION_EXPIRED', 'Payment authorization expired before submission');
    const paymentHeader = Buffer.from(JSON.stringify({
      x402Version: 2, accepted: terms, payload: { signature, authorization },
    })).toString('base64');
    try {
      // Once a paid POST is attempted, errors do not establish non-settlement.
      const delivery = await post(prepared.body, paymentHeader);
      return authenticateDelivery(delivery, prepared.request, { ...trust, payer });
    } catch (cause) {
      throw new VerifierError(cause instanceof VerifierError ? cause.code : 'DELIVERY_ERROR',
        'Paid submission did not yield an authenticated verdict; settlement may have occurred. Do not automatically retry.',
        { cause, paymentMayHaveSettled: true });
    }
  }
  return Object.freeze({ inspectQuote, verifyPatch });
}
