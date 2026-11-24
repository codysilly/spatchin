import assert from "node:assert/strict";
import test from "node:test";

import worker, { DISPATCH_URL, dispatchWorkflow } from "../src/index.js";

const TOKEN = "synthetic-secret-test-token";

function response(status, headers = {}) {
  return new Response(null, { status, headers });
}

function recordingLogger() {
  const entries = [];
  return {
    entries,
    info(message) { entries.push(message); },
    error(message) { entries.push(message); },
  };
}

test("scheduled invocation dispatches one background request", async () => {
  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls += 1; return response(204); };
  try {
    let task;
    worker.scheduled({}, { GITHUB_TOKEN: TOKEN }, { waitUntil(value) { task = value; } });
    await task;
    assert.equal(calls, 1);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("uses the exact ATIS workflow endpoint and main ref", async () => {
  let request;
  await dispatchWorkflow({ GITHUB_TOKEN: TOKEN }, {
    fetchImpl: async (url, init) => { request = { url, init }; return response(204); },
    logger: recordingLogger(),
  });

  assert.equal(request.url, DISPATCH_URL);
  assert.equal(request.url, "https://api.github.com/repos/codysilly/spatchin/actions/workflows/atis-update.yml/dispatches");
  assert.equal(request.init.method, "POST");
  assert.deepEqual(JSON.parse(request.init.body), { ref: "main" });
  assert.equal(request.init.headers.Authorization, `Bearer ${TOKEN}`);
  assert.equal(request.init.headers.Accept, "application/vnd.github+json");
  assert.equal(request.init.headers["X-GitHub-Api-Version"], "2022-11-28");
  assert.equal(request.init.headers["User-Agent"], "spatchin-atis-scheduler");
});

test("treats HTTP 204 as accepted, not completed", async () => {
  const logger = recordingLogger();
  const result = await dispatchWorkflow({ GITHUB_TOKEN: TOKEN }, {
    fetchImpl: async () => response(204), logger,
    now: () => new Date("2026-11-19T18:00:00Z"),
  });
  assert.deepEqual(result, { accepted: true, status: 204 });
  const entry = JSON.parse(logger.entries[0]);
  assert.equal(entry.outcome, "accepted");
  assert.equal(entry.timestamp, "2026-11-19T18:00:00.000Z");
  assert.equal(entry.http_status, 204);
  assert.equal(entry.completed, undefined);
});

test("fails without a credential before making a request", async () => {
  let calls = 0;
  const logger = recordingLogger();
  await assert.rejects(dispatchWorkflow({}, {
    fetchImpl: async () => { calls += 1; return response(204); }, logger,
  }), /GITHUB_TOKEN is not configured/);
  assert.equal(calls, 0);
  assert.equal(JSON.parse(logger.entries[0]).error, "missing_credential");
});

for (const status of [401, 403]) {
  test(`classifies HTTP ${status} as an authentication failure`, async () => {
    const logger = recordingLogger();
    await assert.rejects(dispatchWorkflow({ GITHUB_TOKEN: TOKEN }, {
      fetchImpl: async () => response(status), logger,
    }), /authentication_failed/);
    assert.equal(JSON.parse(logger.entries[0]).error, "authentication_failed");
  });
}

test("reports a network failure without retrying", async () => {
  let calls = 0;
  const logger = recordingLogger();
  await assert.rejects(dispatchWorkflow({ GITHUB_TOKEN: TOKEN }, {
    fetchImpl: async () => { calls += 1; throw new Error("connection refused"); }, logger,
  }), /dispatch failed/);
  assert.equal(calls, 1);
  assert.equal(JSON.parse(logger.entries[0]).error, "network_failure");
});

test("aborts a request that exceeds the timeout", async () => {
  const logger = recordingLogger();
  await assert.rejects(dispatchWorkflow({ GITHUB_TOKEN: TOKEN }, {
    fetchImpl: (_url, init) => new Promise((_resolve, reject) => {
      init.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
    }),
    logger,
    timeoutMs: 5,
  }), /timed out/);
  assert.equal(JSON.parse(logger.entries[0]).error, "network_timeout");
});

test("classifies rate limiting and records safe retry metadata", async () => {
  let calls = 0;
  const logger = recordingLogger();
  await assert.rejects(dispatchWorkflow({ GITHUB_TOKEN: TOKEN }, {
    fetchImpl: async () => { calls += 1; return response(429, { "retry-after": "60" }); }, logger,
  }), /rate_limited/);
  const entry = JSON.parse(logger.entries[0]);
  assert.equal(calls, 1);
  assert.equal(entry.error, "rate_limited");
  assert.equal(entry.retry_after_seconds, "60");
});

test("classifies exhausted GitHub rate limits reported as HTTP 403", async () => {
  const logger = recordingLogger();
  await assert.rejects(dispatchWorkflow({ GITHUB_TOKEN: TOKEN }, {
    fetchImpl: async () => response(403, { "x-ratelimit-remaining": "0" }), logger,
  }), /rate_limited/);
  assert.equal(JSON.parse(logger.entries[0]).error, "rate_limited");
});

test("never leaks the credential in network failure logs", async () => {
  const logger = recordingLogger();
  await assert.rejects(dispatchWorkflow({ GITHUB_TOKEN: TOKEN }, {
    fetchImpl: async () => { throw new Error(`Authorization: Bearer ${TOKEN}`); }, logger,
  }));
  assert.equal(logger.entries.join("\n").includes(TOKEN), false);
  assert.match(logger.entries[0], /\[REDACTED\]/);
});
