import { join } from "node:path";
import { homedir } from "node:os";

export function getArg(args, name, defaultValue) {
  const flag = `--${name}`;
  const index = args.indexOf(flag);
  return index >= 0 && args[index + 1] ? args[index + 1] : defaultValue;
}

export function resolveStateDir(value, homeDir = homedir()) {
  if (!value) {
    return join(homeDir, ".hermes", "kasia");
  }
  if (value.startsWith("~")) {
    return join(homeDir, value.slice(1));
  }
  return value;
}

export function sendJson(res, statusCode, payload) {
  const body = `${JSON.stringify(payload)}\n`;
  res.writeHead(statusCode, {
    "Content-Type": "application/json",
    "Content-Length": Buffer.byteLength(body),
  });
  res.end(body);
}

export async function readJsonBody(req) {
  const chunks = [];
  for await (const chunk of req) {
    chunks.push(Buffer.from(chunk));
  }
  if (chunks.length === 0) {
    return {};
  }
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

export function createSyncRunner(core, logger = console) {
  let syncInFlight = null;
  return async function runSync() {
    if (syncInFlight) {
      return syncInFlight;
    }
    syncInFlight = core
      .syncOnce()
      .catch((error) => {
        logger.warn(`[kasia-bridge] Sync failed: ${error?.message || error}`);
      })
      .finally(() => {
        syncInFlight = null;
      });
    return syncInFlight;
  };
}

export function createBridgeHandler(core) {
  return async function bridgeHandler(req, res) {
    try {
      const url = new URL(req.url || "/", "http://127.0.0.1");
      const method = req.method || "GET";

      if (method === "GET" && url.pathname === "/health") {
        return sendJson(res, 200, core.health());
      }

      if (method === "GET" && url.pathname === "/wallet") {
        const txId = String(url.searchParams.get("txId") || "").trim() || null;
        return sendJson(res, 200, await core.inspectWallet({ txId }));
      }

      if (method === "GET" && url.pathname === "/messages") {
        return sendJson(res, 200, core.dequeueMessages());
      }

      if (method === "POST" && url.pathname === "/handshakes/respond") {
        const body = await readJsonBody(req);
        const result = await core.respondToHandshake(body.chatId || body.address);
        return sendJson(res, 200, result);
      }

      if (method === "POST" && url.pathname === "/handshakes/initiate") {
        const body = await readJsonBody(req);
        const result = await core.initiateHandshake({
          chatId: body.chatId || body.address || body.target,
          displayName: body.displayName || body.nickname || null,
          retry: Boolean(body.retry),
        });
        return sendJson(res, 200, result);
      }

      if (method === "POST" && url.pathname === "/send") {
        const body = await readJsonBody(req);
        const result = await core.send({
          chatId: body.chatId,
          message: body.message,
          waitMs: body.waitMs,
        });
        return sendJson(res, 200, result);
      }

      if (method === "GET" && url.pathname.startsWith("/send/")) {
        const jobId = decodeURIComponent(url.pathname.slice("/send/".length));
        const result = core.getSendJob(jobId);
        if (!result) {
          return sendJson(res, 404, { error: "Send job not found" });
        }
        return sendJson(res, 200, result);
      }

      if (method === "POST" && url.pathname === "/broadcasts/send") {
        const body = await readJsonBody(req);
        const result = await core.sendBroadcast({
          channelName: body.channelName || body.chatId || body.channel,
          message: body.message,
          waitMs: body.waitMs,
        });
        return sendJson(res, 200, result);
      }

      if (method === "POST" && url.pathname === "/broadcasts/subscribe") {
        const body = await readJsonBody(req);
        const result = await core.subscribeBroadcastChannel({
          channelName: body.channelName || body.chatId || body.channel,
          publishers: body.publishers || [],
        });
        return sendJson(res, 200, result);
      }

      if (method === "GET" && url.pathname.startsWith("/resolve-target/")) {
        const target = decodeURIComponent(url.pathname.slice("/resolve-target/".length));
        const result = await core.resolveTarget(target);
        return sendJson(res, 200, result);
      }

      if (method === "GET" && url.pathname.startsWith("/chat/")) {
        const chatId = decodeURIComponent(url.pathname.slice("/chat/".length));
        return sendJson(res, 200, core.getChatInfo(chatId));
      }

      return sendJson(res, 404, { error: "Not found" });
    } catch (error) {
      return sendJson(res, 500, {
        error: error?.message || String(error),
      });
    }
  };
}
