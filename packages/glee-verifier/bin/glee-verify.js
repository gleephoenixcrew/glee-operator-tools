#!/usr/bin/env node
import { open } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import {
  authenticateDelivery,
  createVerifierClient,
  prepareRequest,
} from "../src/index.js";

const INPUT_LIMIT = 2 * 1024 * 1024;
const HELP = `GLEE verifier prototype (Node 22+)

  glee-verify demo
  glee-verify prepare --request REQUEST.json
  glee-verify authenticate --request REQUEST.json --delivery DELIVERY.json --trust TRUST.json
  glee-verify quote --request REQUEST.json --trust TRUST.json [--endpoint HTTPS_URL]

demo, prepare and authenticate run offline. quote sends your request without
payment to the configured endpoint. This CLI has no wallet or paid command.
authenticate exit codes: PASS=0, FAIL=1, INSUFFICIENT_EVIDENCE=2, invalid/error=3.
All commands emit JSON except --help.
`;

async function readJson(path) {
  const file = await open(path, "r");
  try {
    const info = await file.stat();
    if (!info.isFile() || info.size > INPUT_LIMIT) {
      throw new Error(`JSON input must be a regular file of at most ${INPUT_LIMIT} bytes`);
    }
    const chunks = [];
    let total = 0;
    while (true) {
      const buffer = Buffer.alloc(Math.min(65536, INPUT_LIMIT + 1 - total));
      const { bytesRead } = await file.read(buffer, 0, buffer.length, null);
      if (bytesRead === 0) break;
      total += bytesRead;
      if (total > INPUT_LIMIT) throw new Error("JSON input exceeds byte limit");
      chunks.push(buffer.subarray(0, bytesRead));
    }
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(Buffer.concat(chunks)));
  } finally {
    await file.close();
  }
}

function parseOptions(args, allowed, required) {
  const options = Object.create(null);
  for (let i = 0; i < args.length; i += 2) {
    const flag = args[i];
    const name = flag?.startsWith("--") ? flag.slice(2) : "";
    const value = args[i + 1];
    if (!allowed.includes(name) || Object.hasOwn(options, name) || !value || value.startsWith("--")) {
      throw new Error(`Unknown, duplicate, or incomplete option: ${flag ?? ""}`);
    }
    options[name] = value;
  }
  for (const name of required) {
    if (!Object.hasOwn(options, name)) throw new Error(`Missing required --${name}`);
  }
  return options;
}

function trustFromFixture(fixture) {
  return {
    trustedReceiptPublicKeyHex: fixture.body.acceptance_receipt.key.public_key_hex,
    trustedPayTo: fixture.body.acceptance_receipt.payment.pay_to,
    payer: fixture.body.acceptance_receipt.payment.payer,
  };
}

async function demo() {
  const fixture = await readJson(fileURLToPath(new URL("../test/fixtures/receipt.fixture.json", import.meta.url)));
  // Demo-only fixture trust. Production trust must be independently configured.
  const trust = trustFromFixture(fixture);
  const pass = authenticateDelivery(fixture.body, fixture.request, trust);
  const fail = authenticateDelivery(fixture.fail.body, fixture.fail.request, trust);
  const tampered = structuredClone(fixture.body);
  tampered.result.score += 1;
  let tamperRejected = false;
  try {
    authenticateDelivery(tampered, fixture.request, trust);
  } catch {
    tamperRejected = true;
  }
  if (!tamperRejected || pass.result.verdict !== "PASS" || fail.result.verdict !== "FAIL") {
    throw new Error("Offline fixture demonstration failed");
  }
  return {
    mode: "offline_fixture_demo",
    provenance: fixture.provenance,
    scope: "Authenticates stored service-generated test receipts; does not run patch verification or reconcile settlement",
    network_requests: 0,
    payments: 0,
    cases: [
      { name: "service_fixture_pass", receipt_verified: pass.receipt_verified, verdict: pass.result.verdict },
      { name: "service_fixture_fail", receipt_verified: fail.receipt_verified, verdict: fail.result.verdict },
      { name: "tampered_result", rejected: tamperRejected },
    ],
  };
}

function print(value) {
  process.stdout.write(`${JSON.stringify(value, null, 2)}\n`);
}

try {
  const [command, ...args] = process.argv.slice(2);
  if (command === "--help" || command === "help" || command === undefined) {
    if (args.length) throw new Error("Help takes no options");
    process.stdout.write(HELP);
  } else if (command === "demo") {
    parseOptions(args, [], []);
    print(await demo());
  } else if (command === "prepare") {
    const flags = parseOptions(args, ["request"], ["request"]);
    print(prepareRequest(await readJson(flags.request)));
  } else if (command === "authenticate") {
    const flags = parseOptions(args, ["request", "delivery", "trust"], ["request", "delivery", "trust"]);
    const output = authenticateDelivery(
      await readJson(flags.delivery),
      await readJson(flags.request),
      await readJson(flags.trust),
    );
    print(output);
    const codes = { PASS: 0, FAIL: 1, INSUFFICIENT_EVIDENCE: 2 };
    if (!Object.hasOwn(codes, output.result.verdict)) throw new Error("Unsupported verdict");
    process.exitCode = codes[output.result.verdict];
  } else if (command === "quote") {
    const flags = parseOptions(args, ["request", "trust", "endpoint"], ["request", "trust"]);
    const trust = await readJson(flags.trust);
    const client = createVerifierClient({
      trustedPayTo: trust.trustedPayTo,
      trustedReceiptPublicKeyHex: trust.trustedReceiptPublicKeyHex,
      ...(flags.endpoint ? { endpoint: flags.endpoint } : {}),
    });
    print(await client.inspectQuote(await readJson(flags.request)));
  } else {
    throw new Error(`Unknown command: ${command}`);
  }
} catch (error) {
  print({
    ok: false,
    error: {
      code: typeof error?.code === "string" ? error.code : "CLI_ERROR",
      message: error instanceof Error ? error.message : "Unknown error",
      paymentMayHaveSettled: error?.paymentMayHaveSettled === true,
    },
  });
  process.exitCode = 3;
}
