import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtemp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { syntheticInsufficientEvidence } from "../test/helpers.mjs";

const packageRoot = fileURLToPath(new URL("../", import.meta.url));
const scratch = await mkdtemp(join(tmpdir(), "glee-verifier-install-"));
const app = join(scratch, "clean-app");
const npm = process.platform === "win32" ? "npm.cmd" : "npm";
const env = { ...process.env, npm_config_cache: join(scratch, "npm-cache") };

function run(command, args, cwd, expectedStatus = 0) {
  const result = spawnSync(command, args, { cwd, env, encoding: "utf8", timeout: 60000 });
  if (result.error || result.status !== expectedStatus) {
    throw new Error(
      `${command} ${args.join(" ")} failed (expected ${expectedStatus}, got ${result.status}): ` +
      `${result.error?.message ?? ""}\n${result.stdout ?? ""}\n${result.stderr ?? ""}`,
    );
  }
  return result.stdout;
}

try {
  await mkdir(app);
  await writeFile(join(app, "package.json"), JSON.stringify({ name: "glee-clean-consumer", private: true, type: "module" }));
  const pack = JSON.parse(run(npm, ["pack", "--offline", "--ignore-scripts", "--json", "--pack-destination", scratch], packageRoot));
  assert.equal(pack.length, 1);
  const tarball = join(scratch, pack[0].filename);
  run(npm, ["install", "--offline", "--ignore-scripts", "--no-audit", "--no-fund", "--package-lock=false", tarball], app);

  const installed = join(app, "node_modules", "@gleephoenix", "verifier");
  const manifest = JSON.parse(await readFile(join(installed, "package.json"), "utf8"));
  assert.equal(manifest.name, "@gleephoenix/verifier");
  for (const key of ["dependencies", "peerDependencies", "optionalDependencies"]) {
    assert.equal(Object.keys(manifest[key] ?? {}).length, 0, `${key} must remain empty`);
  }

  const fixture = JSON.parse(await readFile(join(installed, "test", "fixtures", "receipt.fixture.json"), "utf8"));
  const trust = {
    trustedReceiptPublicKeyHex: fixture.body.acceptance_receipt.key.public_key_hex,
    trustedPayTo: fixture.body.acceptance_receipt.payment.pay_to,
    payer: fixture.body.acceptance_receipt.payment.payer,
  };
  await writeFile(join(app, "request.json"), JSON.stringify(fixture.request));
  await writeFile(join(app, "delivery.json"), JSON.stringify(fixture.body));
  await writeFile(join(app, "fail-request.json"), JSON.stringify(fixture.fail.request));
  await writeFile(join(app, "fail-delivery.json"), JSON.stringify(fixture.fail.body));
  await writeFile(join(app, "trust.json"), JSON.stringify(trust));
  // Only the PASS/FAIL fixtures came from the real service implementation.
  // This generated IE fixture verifies CLI verdict handling, not service behavior.
  const insufficient = syntheticInsufficientEvidence();
  await writeFile(join(app, "synthetic-ie-delivery.json"), JSON.stringify(insufficient.body));
  await writeFile(join(app, "synthetic-ie-trust.json"), JSON.stringify(insufficient.trust));
  const tampered = structuredClone(fixture.body);
  tampered.result.score += 1;
  await writeFile(join(app, "tampered.json"), JSON.stringify(tampered));

  await writeFile(join(app, "consumer.mjs"), `
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { authenticateDelivery, prepareRequest } from "@gleephoenix/verifier";
import { asGleeWallet } from "@gleephoenix/verifier/adapters/agentkit-wallet";
const read = async path => JSON.parse(await readFile(path, "utf8"));
const request = await read("request.json");
const trust = await read("trust.json");
assert.equal(authenticateDelivery(await read("delivery.json"), request, trust).result.verdict, "PASS");
assert.equal(prepareRequest(request).requestHash.length, 64);
assert.throws(() => createRequire(import.meta.url).resolve("@coinbase/agentkit"), { code: "MODULE_NOT_FOUND" });
let signCount = 0;
const adapter = asGleeWallet({
  getNetwork: () => ({ protocolFamily: "evm", chainId: "8453" }),
  getAddress: () => trust.payer,
  signTypedData: () => { signCount += 1; throw new Error("No signing permitted in install smoke"); },
});
assert.equal(await adapter.getChainId(), 8453);
assert.equal(await adapter.getAddress(), trust.payer);
assert.equal(signCount, 0);
process.stdout.write("Installed SDK imports and authenticates without AgentKit\\n");
`);
  run(process.execPath, ["consumer.mjs"], app);
  const cli = join(installed, "bin", "glee-verify.js");
  const demo = JSON.parse(run(process.execPath, [cli, "demo"], app));
  assert.equal(demo.mode, "offline_fixture_demo");
  assert.equal(demo.network_requests, 0);
  assert.equal(demo.payments, 0);
  assert.equal(demo.cases[2].rejected, true);
  if (process.platform !== "win32") {
    const linkedDemo = JSON.parse(run(join(app, "node_modules", ".bin", "glee-verify"), ["demo"], app));
    assert.equal(linkedDemo.mode, "offline_fixture_demo");
  }
  const pass = JSON.parse(run(process.execPath, [cli, "authenticate", "--request", "request.json", "--delivery", "delivery.json", "--trust", "trust.json"], app));
  assert.equal(pass.result.verdict, "PASS");
  const fail = JSON.parse(run(process.execPath, [cli, "authenticate", "--request", "fail-request.json", "--delivery", "fail-delivery.json", "--trust", "trust.json"], app, 1));
  assert.equal(fail.result.verdict, "FAIL");
  const ie = JSON.parse(run(process.execPath, [cli, "authenticate", "--request", "request.json", "--delivery", "synthetic-ie-delivery.json", "--trust", "synthetic-ie-trust.json"], app, 2));
  assert.equal(ie.receipt_verified, true);
  assert.equal(ie.result.verdict, "INSUFFICIENT_EVIDENCE");
  const rejected = JSON.parse(run(process.execPath, [cli, "authenticate", "--request", "request.json", "--delivery", "tampered.json", "--trust", "trust.json"], app, 3));
  assert.equal(rejected.ok, false);
  run(process.execPath, [cli, "prepare", "--request", "request.json", "--request", "request.json"], app, 3);
  process.stdout.write(JSON.stringify({
    ok: true,
    package: `${manifest.name}@${manifest.version}`,
    tarball_install: "offline clean app",
    agentkit_installed: false,
    runtime_dependencies: 0,
    sdk: "authenticated PASS",
    cli: "demo; PASS exit 0; FAIL exit 1; INSUFFICIENT_EVIDENCE exit 2; tamper and duplicate-option exit 3",
    insufficient_evidence_fixture_mode: "synthetic; disposable local key; not service-generated",
    paid_requests: 0,
  }, null, 2) + "\n");
} finally {
  await rm(scratch, { recursive: true, force: true });
}
