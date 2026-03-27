import test from "node:test";
import assert from "node:assert/strict";
import { createServer } from "node:http";

import { createBridgeHandler, resolveStateDir } from "../lib/bridge_app.js";

async function withServer(handler, fn) {
  const server = createServer(handler);
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const address = server.address();
  const baseUrl = `http://127.0.0.1:${address.port}`;
  try {
    await fn(baseUrl);
  } finally {
    await new Promise((resolve, reject) => server.close((error) => {
      if (error) {
        reject(error);
        return;
      }
      resolve();
    }));
  }
}

function makeCore(overrides = {}) {
  return {
    health() {
      return { ok: true };
    },
    async inspectWallet({ txId } = {}) {
      return { wallet: { address: "kaspa:qwallet" }, txQuery: txId ? { txId } : null };
    },
    async signWalletMessage(payload) {
      return { signed: true, ...payload };
    },
    async previewKaspaSend(payload) {
      return { canSend: true, ...payload };
    },
    async sendKaspa(payload) {
      return { accepted: true, txId: "kaspa-send-1", ...payload };
    },
    dequeueMessages() {
      return { messages: [] };
    },
    async respondToHandshake(chatId) {
      return { chatId };
    },
    async initiateHandshake(payload) {
      return payload;
    },
    async send(payload) {
      return payload;
    },
    getSendJob(jobId) {
      return { jobId };
    },
    async sendBroadcast(payload) {
      return payload;
    },
    async subscribeBroadcastChannel(payload) {
      return payload;
    },
    async resolveTarget(target) {
      return { target };
    },
    getChatInfo(chatId) {
      return { chatId };
    },
    ...overrides,
  };
}

test("resolveStateDir expands home-relative Kasia paths", () => {
  assert.equal(
    resolveStateDir("~/.hermes/kasia", "/tmp/home"),
    "/tmp/home/.hermes/kasia",
  );
  assert.equal(resolveStateDir("", "/tmp/home"), "/tmp/home/.hermes/kasia");
});

test("bridge handler exposes health and decoded chat lookups", async () => {
  const core = makeCore({
    health() {
      return { walletAddress: "kaspa:qwallet" };
    },
    async inspectWallet({ txId } = {}) {
      return {
        wallet: { address: "kaspa:qwallet" },
        txQuery: txId ? { txId, found: true } : null,
      };
    },
    getChatInfo(chatId) {
      return { chatId, kind: "dm" };
    },
  });

  await withServer(createBridgeHandler(core), async (baseUrl) => {
    const healthResponse = await fetch(`${baseUrl}/health`);
    assert.equal(healthResponse.status, 200);
    assert.deepEqual(await healthResponse.json(), { walletAddress: "kaspa:qwallet" });

    const walletResponse = await fetch(`${baseUrl}/wallet?txId=tx-topup`);
    assert.equal(walletResponse.status, 200);
    assert.deepEqual(await walletResponse.json(), {
      wallet: { address: "kaspa:qwallet" },
      txQuery: { txId: "tx-topup", found: true },
    });

    const chatResponse = await fetch(`${baseUrl}/chat/${encodeURIComponent("kaspa:qpeer")}`);
    assert.equal(chatResponse.status, 200);
    assert.deepEqual(await chatResponse.json(), { chatId: "kaspa:qpeer", kind: "dm" });
  });
});

test("bridge handler forwards JSON bodies for send and handshake routes", async () => {
  const calls = [];
  const core = makeCore({
    async initiateHandshake(payload) {
      calls.push(["initiate", payload]);
      return { status: "pending", ...payload };
    },
    async send(payload) {
      calls.push(["send", payload]);
      return { status: "submitted", ...payload };
    },
  });

  await withServer(createBridgeHandler(core), async (baseUrl) => {
    const initiateResponse = await fetch(`${baseUrl}/handshakes/initiate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        target: "kaspa:qpeer",
        displayName: "Peer",
        retry: true,
      }),
    });
    assert.equal(initiateResponse.status, 200);
    assert.deepEqual(await initiateResponse.json(), {
      status: "pending",
      chatId: "kaspa:qpeer",
      displayName: "Peer",
      retry: true,
    });

    const sendResponse = await fetch(`${baseUrl}/send`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chatId: "kaspa:qpeer",
        message: "hello",
        waitMs: 2500,
      }),
    });
    assert.equal(sendResponse.status, 200);
    assert.deepEqual(await sendResponse.json(), {
      status: "submitted",
      chatId: "kaspa:qpeer",
      message: "hello",
      waitMs: 2500,
    });
  });

  assert.deepEqual(calls, [
    [
      "initiate",
      { chatId: "kaspa:qpeer", displayName: "Peer", retry: true },
    ],
    [
      "send",
      { chatId: "kaspa:qpeer", message: "hello", waitMs: 2500 },
    ],
  ]);
});

test("bridge handler forwards wallet action requests", async () => {
  const calls = [];
  const core = makeCore({
    async signWalletMessage(payload) {
      calls.push(["sign", payload]);
      return { signature: "signed-payload", ...payload };
    },
    async previewKaspaSend(payload) {
      calls.push(["preview", payload]);
      return { canSend: true, feeSompi: "1000", ...payload };
    },
    async sendKaspa(payload) {
      calls.push(["send-kaspa", payload]);
      return { accepted: true, txId: "kaspa-send-1", ...payload };
    },
  });

  await withServer(createBridgeHandler(core), async (baseUrl) => {
    const signResponse = await fetch(`${baseUrl}/wallet/sign-message`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: "sign me" }),
    });
    assert.equal(signResponse.status, 200);
    assert.deepEqual(await signResponse.json(), {
      signature: "signed-payload",
      message: "sign me",
    });

    const previewResponse = await fetch(`${baseUrl}/wallet/send-kaspa/preview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        destinationAddress: "kaspa:qpeer",
        amountSompi: "101000000",
        feePolicy: "priority",
      }),
    });
    assert.equal(previewResponse.status, 200);
    assert.deepEqual(await previewResponse.json(), {
      canSend: true,
      feeSompi: "1000",
      destinationAddress: "kaspa:qpeer",
      amountSompi: "101000000",
      feePolicy: "priority",
    });

    const sendResponse = await fetch(`${baseUrl}/wallet/send-kaspa`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        destinationAddress: "kaspa:qpeer",
        amountSompi: "101000000",
        feePolicy: "priority",
      }),
    });
    assert.equal(sendResponse.status, 200);
    assert.deepEqual(await sendResponse.json(), {
      accepted: true,
      txId: "kaspa-send-1",
      destinationAddress: "kaspa:qpeer",
      amountSompi: "101000000",
      feePolicy: "priority",
    });
  });

  assert.deepEqual(calls, [
    ["sign", { message: "sign me" }],
    [
        "preview",
        {
          destinationAddress: "kaspa:qpeer",
          amountSompi: "101000000",
          feePolicy: "priority",
        },
      ],
    [
        "send-kaspa",
        {
          destinationAddress: "kaspa:qpeer",
          amountSompi: "101000000",
          feePolicy: "priority",
        },
      ],
  ]);
});

test("bridge handler returns route-appropriate 404 and 500 responses", async () => {
  const core = makeCore({
    getSendJob() {
      return null;
    },
    async send() {
      throw new Error("node offline");
    },
  });

  await withServer(createBridgeHandler(core), async (baseUrl) => {
    const notFound = await fetch(`${baseUrl}/send/job-404`);
    assert.equal(notFound.status, 404);
    assert.deepEqual(await notFound.json(), { error: "Send job not found" });

    const failed = await fetch(`${baseUrl}/send`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ chatId: "kaspa:qpeer", message: "hello" }),
    });
    assert.equal(failed.status, 500);
    assert.deepEqual(await failed.json(), { error: "node offline" });
  });
});
