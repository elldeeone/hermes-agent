#!/usr/bin/env node

import process from "node:process";
import WebSocket from "isomorphic-ws";
import { Encoding, RpcClient } from "kaspa-wasm";

globalThis.WebSocket = WebSocket;

function readStdin() {
  return new Promise((resolve, reject) => {
    let data = "";
    process.stdin.setEncoding("utf8");
    process.stdin.on("data", (chunk) => {
      data += chunk;
    });
    process.stdin.on("end", () => resolve(data));
    process.stdin.on("error", reject);
  });
}

function timeoutAfter(ms, label) {
  return new Promise((_, reject) => {
    setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms);
  });
}

async function withTimeout(promise, ms, label) {
  return await Promise.race([promise, timeoutAfter(ms, label)]);
}

function bigintSafe(value) {
  return JSON.parse(JSON.stringify(value, (_key, item) => {
    if (typeof item === "bigint") {
      return item.toString();
    }
    return item;
  }));
}

function normalizeInput(raw) {
  const input = raw.trim() ? JSON.parse(raw) : {};
  const host = String(input.host || "127.0.0.1").trim();
  const port = Number(input.port || 16110);
  const network = String(input.network || "mainnet").trim();
  const timeoutSeconds = Math.max(1, Math.min(30, Number(input.timeout_seconds || 10)));
  const url = String(input.url || `ws://${host}:${port}`).trim();
  return { host, port, network, timeoutSeconds, url };
}

async function main() {
  const input = normalizeInput(await readStdin());
  const rpc = new RpcClient(input.url, Encoding.Borsh, input.network);
  try {
    await withTimeout(
      rpc.connect({ blockAsyncConnect: true, timeoutDuration: input.timeoutSeconds * 1000 }),
      input.timeoutSeconds * 1000,
      "kaspa rpc connect",
    );

    const [serverInfo, syncStatus, blockDagInfo] = await Promise.allSettled([
      withTimeout(rpc.getServerInfo(), input.timeoutSeconds * 1000, "getServerInfo"),
      withTimeout(rpc.getSyncStatus(), input.timeoutSeconds * 1000, "getSyncStatus"),
      withTimeout(rpc.getBlockDagInfo(), input.timeoutSeconds * 1000, "getBlockDagInfo"),
    ]);

    const server = serverInfo.status === "fulfilled" ? bigintSafe(serverInfo.value) : null;
    const sync = syncStatus.status === "fulfilled" ? bigintSafe(syncStatus.value) : null;
    const dag = blockDagInfo.status === "fulfilled" ? bigintSafe(blockDagInfo.value) : null;

    const output = {
      network: server?.networkId || server?.network || input.network,
      is_synced: typeof server?.isSynced === "boolean" ? server.isSynced : sync,
      server_version: server?.serverVersion || server?.version || null,
      virtual_daa_score: dag?.virtualDaaScore || dag?.virtualDAAScore || null,
      selected_tip_hash: dag?.selectedParentHash || dag?.selectedTipHash || null,
      endpoint: input.url,
      raw: {
        server_info: server,
        sync_status: sync,
        block_dag_info: dag,
      },
    };
    process.stdout.write(`${JSON.stringify(output)}\n`);
  } finally {
    try {
      await rpc.disconnect();
    } catch {
      // Best-effort cleanup only.
    }
  }
}

main().catch((error) => {
  process.stderr.write(`${error?.stack || error?.message || String(error)}\n`);
  process.exit(1);
});
