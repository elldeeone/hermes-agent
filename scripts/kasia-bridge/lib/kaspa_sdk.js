import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const bridgeDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const kaspaEntry = resolve(bridgeDir, "vendor", "kaspa-wasm", "kaspa.js");

if (!existsSync(kaspaEntry)) {
  throw new Error(
    "Pinned kaspa-wasm runtime is missing. Run `npm install` in scripts/kasia-bridge."
  );
}

const kaspa = require(kaspaEntry);

export default kaspa;
export const {
  Address,
  addressFromScriptPublicKey,
  calculateTransactionFee,
  createInputSignature,
  createTransaction,
  ConnectStrategy,
  Encoding,
  Generator,
  Mnemonic,
  NetworkId,
  PaymentOutput,
  PrivateKeyGenerator,
  RpcClient,
  ScriptPublicKey,
  signTransaction,
  TransactionOutput,
  UtxoContext,
  UtxoEntries,
  UtxoProcessor,
  updateTransactionMass,
  XPrv,
  XOnlyPublicKey,
  kaspaToSompi,
  payToAddressScript,
  signMessage,
} = kaspa;
