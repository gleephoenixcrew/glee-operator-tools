import assert from 'node:assert/strict';
import test from 'node:test';
import {
  BASE_CHAIN_ID, BASE_USDC_MAINNET_ADDRESS, GLEE_PRICE_ATOMIC, GLEE_VERIFIER_URL,
  createVerifierClient, validatePaymentChallenge,
} from '../src/index.js';
import { challenge, copy, ENDPOINT, fixture, jsonResponse, transport, trust, USDC, wallet } from './helpers.mjs';

const config = extra => ({
  trustedPayTo: trust.trustedPayTo,
  trustedReceiptPublicKeyHex: trust.trustedReceiptPublicKeyHex,
  ...extra,
});
const paidOptions = w => ({ wallet: w, maxAmountAtomic: '50000' });
const headersFor = call => new Headers(call.headers);

test('public constants identify the frozen Base USDC service contract', () => {
  assert.equal(GLEE_VERIFIER_URL, ENDPOINT);
  assert.equal(BASE_CHAIN_ID, 8453);
  assert.equal(BASE_USDC_MAINNET_ADDRESS.toLowerCase(), USDC.toLowerCase());
  assert.equal(GLEE_PRICE_ATOMIC, '50000');
});

test('framework-free paid seam authenticates a service fixture using mocked transport and wallet', async () => {
  const network = transport(jsonResponse(challenge(), 402), jsonResponse(fixture.body));
  const w = wallet();
  const client = createVerifierClient(config({ fetchImpl: network.fetchImpl }));
  const result = await client.verifyPatch(fixture.request, paidOptions(w));
  assert.equal(result.receipt_verified, true);
  assert.equal(result.result.verdict, 'PASS');
  assert.equal(w.signCalls.length, 1);
  assert.equal(network.calls.length, 2);
  assert.equal(network.calls[0].body, network.calls[1].body);
  assert.equal(network.calls[0].body, JSON.stringify(fixture.request));
  for (const call of network.calls) {
    assert.equal(call.url, ENDPOINT);
    assert.equal(call.method, 'POST');
    assert.equal(call.redirect, 'error');
  }
  assert.equal(headersFor(network.calls[0]).has('PAYMENT-SIGNATURE'), false);
  const payload = JSON.parse(Buffer.from(headersFor(network.calls[1]).get('PAYMENT-SIGNATURE'), 'base64').toString());
  assert.equal(payload.x402Version, 2);
  assert.deepEqual(payload.accepted, challenge().accepts[0]);
  assert.equal(payload.payload.signature, `0x${'ab'.repeat(65)}`);
  assert.deepEqual(w.signCalls[0].domain, {
    name: 'USD Coin', version: '2', chainId: 8453, verifyingContract: USDC,
  });
  assert.equal(w.signCalls[0].primaryType, 'TransferWithAuthorization');
  const authorization = w.signCalls[0].message;
  assert.equal(authorization.from.toLowerCase(), trust.payer.toLowerCase());
  assert.equal(authorization.to.toLowerCase(), trust.trustedPayTo.toLowerCase());
  assert.equal(authorization.value, '50000');
  assert.match(authorization.nonce, /^0x[0-9a-f]{64}$/);
  assert.equal(authorization.validAfter, 0);
  assert.ok(authorization.validBefore > Math.floor(Date.now() / 1000));
  assert.ok(authorization.validBefore <= Math.floor(Date.now() / 1000) + 300);
  assert.deepEqual(payload.payload.authorization, authorization);
});

test('inspection validates an unpaid quote and emits no payment header', async () => {
  const network = transport(jsonResponse(challenge(), 402));
  const client = createVerifierClient(config({ fetchImpl: network.fetchImpl }));
  const quote = await client.inspectQuote(fixture.request);
  assert.equal(network.calls.length, 1);
  assert.equal(headersFor(network.calls[0]).has('PAYMENT-SIGNATURE'), false);
  assert.ok(quote && typeof quote === 'object');
  assert.equal(Object.hasOwn(quote, 'receipt_verified'), false);
});

test('x402 V2 PAYMENT-REQUIRED header is accepted without relying on a JSON body', async () => {
  const encoded = Buffer.from(JSON.stringify(challenge())).toString('base64');
  const network = transport(
    new Response(null, { status: 402, headers: { 'PAYMENT-REQUIRED': encoded } }),
    jsonResponse(fixture.body),
  );
  const w = wallet();
  const result = await createVerifierClient(config({ fetchImpl: network.fetchImpl }))
    .verifyPatch(fixture.request, paidOptions(w));
  assert.equal(result.receipt_verified, true);
  assert.equal(w.signCalls.length, 1);
});

test('payment challenge validation returns a detached immutable terms snapshot', () => {
  const untrusted = challenge();
  const terms = validatePaymentChallenge(untrusted, { endpoint: ENDPOINT, trustedPayTo: trust.trustedPayTo });
  untrusted.accepts[0].amount = '999999';
  untrusted.accepts[0].extra.name = 'Other Coin';
  assert.equal(terms.amount, '50000');
  assert.equal(terms.extra.name, 'USD Coin');
  assert.ok(Object.isFrozen(terms));
  assert.ok(Object.isFrozen(terms.extra));
});

for (const [name, field, value] of [
  ['higher amount', 'amount', '5000000'],
  ['lower amount', 'amount', '1'],
  ['noncanonical amount', 'amount', '050000'],
  ['numeric amount', 'amount', 50000],
  ['different recipient', 'payTo', `0x${'33'.repeat(20)}`],
  ['malformed recipient', 'payTo', 'bad'],
  ['different asset', 'asset', `0x${'33'.repeat(20)}`],
  ['missing asset', 'asset', undefined],
  ['different chain', 'network', 'eip155:1'],
  ['testnet', 'network', 'eip155:84532'],
  ['missing network', 'network', undefined],
  ['different scheme', 'scheme', 'upto'],
  ['missing scheme', 'scheme', undefined],
  ['excessive timeout', 'maxTimeoutSeconds', 3601],
  ['negative timeout', 'maxTimeoutSeconds', -1],
  ['zero timeout', 'maxTimeoutSeconds', 0],
  ['fractional timeout', 'maxTimeoutSeconds', 1.5],
  ['different token domain', 'extra', { name: 'Other Coin', version: '2' }],
  ['different token domain version', 'extra', { name: 'USD Coin', version: '1' }],
]) {
  test(`rejects challenge with ${name} before asking the wallet to sign`, async () => {
    const quote = challenge();
    quote.accepts[0][field] = value;
    const network = transport(jsonResponse(quote, 402));
    const w = wallet();
    const client = createVerifierClient(config({ fetchImpl: network.fetchImpl }));
    await assert.rejects(client.verifyPatch(fixture.request, paidOptions(w)));
    assert.equal(w.signCalls.length, 0);
    assert.equal(network.calls.length, 1);
  });
}

for (const [name, mutate] of [
  ['unknown x402 version', q => { q.x402Version = 1; }],
  ['wrong resource', q => { q.resource.url = 'https://other.example/verify'; }],
  ['missing offers', q => { q.accepts = []; }],
  ['multiple offers', q => { q.accepts.push(copy(q.accepts[0])); }],
]) {
  test(`rejects ${name} before signing`, async () => {
    const quote = challenge();
    mutate(quote);
    const network = transport(jsonResponse(quote, 402));
    const w = wallet();
    await assert.rejects(createVerifierClient(config({ fetchImpl: network.fetchImpl }))
      .verifyPatch(fixture.request, paidOptions(w)));
    assert.equal(w.signCalls.length, 0);
  });
}

for (const [name, overrides] of [
  ['absent trust key', { trustedReceiptPublicKeyHex: undefined }],
  ['malformed trust key', { trustedReceiptPublicKeyHex: 'bad' }],
  ['absent payee', { trustedPayTo: undefined }],
  ['malformed payee', { trustedPayTo: 'bad' }],
  ['coercible non-string payee', { trustedPayTo: { toString: () => trust.trustedPayTo } }],
  ['HTTP endpoint', { endpoint: 'http://gleephoenix.com/api/x402/verify/patch' }],
  ['endpoint credentials', { endpoint: 'https://user:pass@gleephoenix.com/api/x402/verify/patch' }],
  ['endpoint fragment', { endpoint: `${ENDPOINT}#fragment` }],
]) {
  test(`rejects ${name} with no network requests`, async () => {
    const network = transport();
    const w = wallet();
    await assert.rejects(async () => {
      const client = createVerifierClient(config({ ...overrides, fetchImpl: network.fetchImpl }));
      await client.verifyPatch(fixture.request, paidOptions(w));
    });
    assert.equal(network.calls.length, 0);
    assert.equal(w.signCalls.length, 0);
  });
}

for (const maxAmountAtomic of [undefined, '0', '49999', 50000]) {
  test(`missing/insufficient/non-string local spend ceiling ${maxAmountAtomic} blocks paid transport`, async () => {
    const network = transport();
    const w = wallet();
    await assert.rejects(createVerifierClient(config({ fetchImpl: network.fetchImpl }))
      .verifyPatch(fixture.request, { wallet: w, maxAmountAtomic }));
    assert.equal(network.calls.length, 0);
    assert.equal(w.signCalls.length, 0);
  });
}

for (const chainId of [1, 84532, undefined, '8453']) {
  test(`wrong or nonnumeric wallet chain ${chainId} blocks transport and signing`, async () => {
    const network = transport();
    const w = wallet();
    w.chainId = chainId;
    await assert.rejects(createVerifierClient(config({ fetchImpl: network.fetchImpl }))
      .verifyPatch(fixture.request, paidOptions(w)));
    assert.equal(network.calls.length, 0);
    assert.equal(w.signCalls.length, 0);
  });
}

test('request is snapshotted before asynchronous challenge transport can mutate caller objects', async () => {
  const request = copy(fixture.request);
  const network = transport(() => {
    request.patch = 'tampered during request';
    request.path_policy.allowed_paths = ['different/'];
    request.assertions[0].pattern = 'different';
    return jsonResponse(challenge(), 402);
  }, jsonResponse(fixture.body));
  const result = await createVerifierClient(config({ fetchImpl: network.fetchImpl }))
    .verifyPatch(request, paidOptions(wallet()));
  assert.equal(result.receipt_verified, true);
  assert.equal(network.calls[0].body, JSON.stringify(fixture.request));
  assert.equal(network.calls[1].body, network.calls[0].body);
});

test('wallet chain change during challenge is caught before signing', async () => {
  const w = wallet();
  const network = transport(() => {
    w.chainId = 1;
    return jsonResponse(challenge(), 402);
  });
  await assert.rejects(createVerifierClient(config({ fetchImpl: network.fetchImpl }))
    .verifyPatch(fixture.request, paidOptions(w)));
  assert.equal(w.signCalls.length, 0);
});

test('wallet address change during challenge is caught before signing', async () => {
  const w = wallet();
  const network = transport(() => {
    w.address = `0x${'33'.repeat(20)}`;
    return jsonResponse(challenge(), 402);
  });
  await assert.rejects(createVerifierClient(config({ fetchImpl: network.fetchImpl }))
    .verifyPatch(fixture.request, paidOptions(w)));
  assert.equal(w.signCalls.length, 0);
});

test('asynchronous address lookup cannot conceal a wallet network switch', async () => {
  const w = wallet();
  let lookups = 0;
  w.getAddress = async () => {
    if (++lookups > 1) w.chainId = 1;
    return trust.payer;
  };
  const network = transport(jsonResponse(challenge(), 402));
  await assert.rejects(createVerifierClient(config({ fetchImpl: network.fetchImpl }))
    .verifyPatch(fixture.request, paidOptions(w)));
  assert.equal(w.signCalls.length, 0);
});

test('operator trust config is snapshotted before asynchronous transport', async () => {
  const options = config();
  const network = transport(() => {
    options.trustedPayTo = `0x${'33'.repeat(20)}`;
    options.trustedReceiptPublicKeyHex = '00'.repeat(32);
    return jsonResponse(challenge(), 402);
  }, jsonResponse(fixture.body));
  options.fetchImpl = network.fetchImpl;
  const client = createVerifierClient(options);
  const result = await client.verifyPatch(fixture.request, paidOptions(wallet()));
  assert.equal(result.receipt_verified, true);
});

for (const status of [200, 202, 302, 400, 500]) {
  test(`initial HTTP ${status} cannot be promoted to an authenticated result`, async () => {
    const network = transport(jsonResponse(fixture.body, status));
    const w = wallet();
    await assert.rejects(createVerifierClient(config({ fetchImpl: network.fetchImpl }))
      .verifyPatch(fixture.request, paidOptions(w)));
    assert.equal(w.signCalls.length, 0);
    assert.equal(network.calls.length, 1);
  });
}

for (const status of [202, 302, 400, 402, 500]) {
  test(`paid HTTP ${status} rejects without retry and preserves ambiguous-settlement flag`, async () => {
    const network = transport(jsonResponse(challenge(), 402), jsonResponse(fixture.body, status));
    const w = wallet();
    await assert.rejects(createVerifierClient(config({ fetchImpl: network.fetchImpl }))
      .verifyPatch(fixture.request, paidOptions(w)), error => {
      assert.equal(error.paymentMayHaveSettled, true);
      assert.equal(typeof error.code, 'string');
      return true;
    });
    assert.equal(network.calls.length, 2);
    assert.equal(w.signCalls.length, 1);
  });
}

test('paid transport error never retries a possibly settled authorization', async () => {
  const network = transport(jsonResponse(challenge(), 402), new Error('lost response after submit'));
  const w = wallet();
  await assert.rejects(createVerifierClient(config({ fetchImpl: network.fetchImpl }))
    .verifyPatch(fixture.request, paidOptions(w)), error => {
    assert.equal(error.paymentMayHaveSettled, true);
    return true;
  });
  assert.equal(network.calls.length, 2);
  assert.equal(w.signCalls.length, 1);
});

for (const signature of [undefined, 'not-a-signature', '0xabcdef', `0x${'gg'.repeat(65)}`]) {
  test(`malformed wallet signature (${String(signature).slice(0, 18)}) never reaches paid transport`, async () => {
    const network = transport(jsonResponse(challenge(), 402));
    const w = wallet();
    w.signTypedData = async data => { w.signCalls.push(copy(data)); return signature; };
    await assert.rejects(createVerifierClient(config({ fetchImpl: network.fetchImpl }))
      .verifyPatch(fixture.request, paidOptions(w)));
    assert.equal(network.calls.length, 1);
    assert.equal(w.signCalls.length, 1);
  });
}

test('paid JSON parse failure preserves settlement ambiguity without exposing a verdict', async () => {
  const network = transport(jsonResponse(challenge(), 402), new Response('not JSON', { status: 200 }));
  const w = wallet();
  await assert.rejects(createVerifierClient(config({ fetchImpl: network.fetchImpl }))
    .verifyPatch(fixture.request, paidOptions(w)), error => {
    assert.equal(error.paymentMayHaveSettled, true);
    assert.equal(Object.hasOwn(error, 'result'), false);
    return true;
  });
});

test('paid receipt verification failure preserves settlement ambiguity', async () => {
  const body = copy(fixture.body);
  body.result.score = 0;
  const network = transport(jsonResponse(challenge(), 402), jsonResponse(body));
  await assert.rejects(createVerifierClient(config({ fetchImpl: network.fetchImpl }))
    .verifyPatch(fixture.request, paidOptions(wallet())), error => {
    assert.equal(error.paymentMayHaveSettled, true);
    return true;
  });
});

test('oversized response is rejected even when Content-Length understates it', async () => {
  const q = challenge();
  q.padding = 'x'.repeat(4096);
  const network = transport(jsonResponse(q, 402, { 'content-length': '1' }));
  const w = wallet();
  await assert.rejects(createVerifierClient(config({ fetchImpl: network.fetchImpl, maxResponseBytes: 1024 }))
    .verifyPatch(fixture.request, paidOptions(w)));
  assert.equal(w.signCalls.length, 0);
});

test('oversized PAYMENT-REQUIRED header is bounded before wallet signing', async () => {
  const q = challenge();
  q.padding = 'x'.repeat(4096);
  const network = transport(new Response(null, {
    status: 402, headers: { 'PAYMENT-REQUIRED': Buffer.from(JSON.stringify(q)).toString('base64') },
  }));
  const w = wallet();
  await assert.rejects(createVerifierClient(config({ fetchImpl: network.fetchImpl, maxResponseBytes: 1024 }))
    .verifyPatch(fixture.request, paidOptions(w)));
  assert.equal(w.signCalls.length, 0);
});

test('fetch deadline aborts challenge retrieval before signing', { timeout: 1000 }, async () => {
  const keeper = setTimeout(() => {}, 500);
  try {
    const network = transport((_url, options) => new Promise((resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(options.signal.reason), { once: true });
    }));
    const w = wallet();
    await assert.rejects(createVerifierClient(config({ fetchImpl: network.fetchImpl, timeoutMs: 20 }))
      .verifyPatch(fixture.request, paidOptions(w)));
    assert.equal(w.signCalls.length, 0);
  } finally {
    clearTimeout(keeper);
  }
});

test('response-body deadline also covers a stream that never produces bytes', { timeout: 1000 }, async () => {
  const keeper = setTimeout(() => {}, 500);
  let wasCancelled = false;
  try {
    const network = transport(new Response(new ReadableStream({ cancel() { wasCancelled = true; } }), {
      status: 402, headers: { 'content-type': 'application/json' },
    }));
    const w = wallet();
    await assert.rejects(createVerifierClient(config({ fetchImpl: network.fetchImpl, timeoutMs: 20 }))
      .verifyPatch(fixture.request, paidOptions(w)));
    assert.equal(w.signCalls.length, 0);
    assert.equal(wasCancelled, true);
  } finally {
    clearTimeout(keeper);
  }
});

test('repeated independent calls use distinct random authorization nonces', async () => {
  const network = transport(
    jsonResponse(challenge(), 402), jsonResponse(fixture.body),
    jsonResponse(challenge(), 402), jsonResponse(fixture.body),
  );
  const w = wallet();
  const client = createVerifierClient(config({ fetchImpl: network.fetchImpl }));
  await client.verifyPatch(fixture.request, paidOptions(w));
  await client.verifyPatch(fixture.request, paidOptions(w));
  assert.equal(w.signCalls.length, 2);
  assert.notEqual(w.signCalls[0].message.nonce, w.signCalls[1].message.nonce);
});
