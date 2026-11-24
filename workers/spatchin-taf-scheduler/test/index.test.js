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

test("uses the exact workflow endpoint, main ref, and documented authentication headers", async () => {
  let request;
  await dispatchWorkflow({ GITHUB_TOKEN: TOKEN }, {
    fetchImpl: async (url, init) => { request = { url, init }; return response(204); },
    logger: recordingLogger(),
  });

  assert.equal(request.url, DISPATCH_URL);
  assert.equal(request.url, "https://api.github.com/repos/codysilly/spatchin/actions/workflows/taf-update.yml/dispatches");
  assert.equal(request.init.method, "POST");
  assert.deepEqual(JSON.parse(request.init.body), { ref: "main" });
  assert.equal(request.init.headers.Authorization, `Bearer ${TOKEN}`);
  assert.equal(request.init.headers.Accept, "application/vnd.github+json");
  assert.equal(request.init.headers["X-GitHub-Api-Version"], "2022-11-28");
});

test("treats HTTP 204 as accepted, not completed", async () => {
  const logger = recordingLogger();
  const result = await dispatchWorkflow({ GITHUB_TOKEN: TOKEN }, {
    fetchImpl: async () => response(204), logger,
    now: () => new Date("2026-11-18T18:00:00Z"),
  });
  assert.deepEqual(result, { accepted: true, status: 204 });
  const entry = JSON.parse(logger.entries[0]);
  assert.equal(entry.outcome, "accepted");
  assert.equal(entry.timestamp, "2026-11-18T18:00:00.000Z");
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

test("reports an unexpected GitHub API failure without retrying", async () => {
  let calls = 0;
  const logger = recordingLogger();
  await assert.rejects(dispatchWorkflow({ GITHUB_TOKEN: TOKEN }, {
    fetchImpl: async () => { calls += 1; return response(500, { "x-github-request-id": "TEST123" }); },
    logger,
  }), /unexpected_response/);
  assert.equal(calls, 1);
  assert.equal(JSON.parse(logger.entries[0]).github_request_id, "TEST123");
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
  const logger = recordingLogger();
  await assert.rejects(dispatchWorkflow({ GITHUB_TOKEN: TOKEN }, {
    fetchImpl: async () => response(429, { "retry-after": "60" }), logger,
  }), /rate_limited/);
  const entry = JSON.parse(logger.entries[0]);
  assert.equal(entry.error, "rate_limited");
  assert.equal(entry.retry_after_seconds, "60");
});

test("never leaks the credential in network failure logs", async () => {
  const logger = recordingLogger();
  await assert.rejects(dispatchWorkflow({ GITHUB_TOKEN: TOKEN }, {
    fetchImpl: async () => { throw new Error(`Bearer ${TOKEN} could not connect`); }, logger,
  }));
  assert.equal(logger.entries.join("\n").includes(TOKEN), false);
  assert.match(logger.entries[0], /\[REDACTED\]/);
});

test("does not retry or duplicate rate-limited dispatches", async () => {
  let calls = 0;
  await assert.rejects(dispatchWorkflow({ GITHUB_TOKEN: TOKEN }, {
    fetchImpl: async () => { calls += 1; return response(429); },
    logger: recordingLogger(),
  }));
  assert.equal(calls, 1);
});


test("scheduler has no public HTTP handler", () => {
  assert.equal(worker.fetch, undefined);
});

test("dispatch logs identify only the TAF workflow", async () => {
  const logger = recordingLogger();
  await dispatchWorkflow({ GITHUB_TOKEN: TOKEN }, {
    fetchImpl: async () => response(204), logger,
  });
  assert.equal(JSON.parse(logger.entries[0]).workflow, "taf-update.yml");
  assert.equal(JSON.parse(logger.entries[0]).ref, "main");
});
