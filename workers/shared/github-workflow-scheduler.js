const REQUEST_TIMEOUT_MS = 10_000;

function sanitizedMessage(error, token) {
  let message = error instanceof Error ? error.message : String(error);
  if (token) message = message.replaceAll(token, '[REDACTED]');
  return message
    .replace(/authorization\s*:\s*bearer\s+\S+/gi, 'Authorization: Bearer [REDACTED]')
    .replace(/bearer\s+\S+/gi, 'Bearer [REDACTED]')
    .slice(0, 300);
}

function failureKind(response) {
  if (
    response.status === 429 ||
    (response.status === 403 && response.headers.get('x-ratelimit-remaining') === '0')
  ) {
    return 'rate_limited';
  }
  if (response.status === 401 || response.status === 403) return 'authentication_failed';
  return 'unexpected_response';
}

export function createGitHubWorkflowScheduler({ workflow, userAgent }) {
  if (!/^[a-z0-9-]+\.yml$/.test(workflow)) throw new Error('Invalid workflow filename');
  if (!/^[a-z0-9-]+$/.test(userAgent)) throw new Error('Invalid scheduler user agent');

  const dispatchUrl =
    `https://api.github.com/repos/codysilly/spatchin/actions/workflows/${workflow}/dispatches`;

  function logAttempt(logger, details) {
    const method = details.outcome === 'accepted' ? 'info' : 'error';
    logger[method](
      JSON.stringify({
        event: 'github_workflow_dispatch',
        workflow,
        ref: 'main',
        attempt: 1,
        ...details,
      }),
    );
  }

  async function dispatchWorkflow(env, options = {}) {
    const fetchImpl = options.fetchImpl ?? fetch;
    const logger = options.logger ?? console;
    const timeoutMs = options.timeoutMs ?? REQUEST_TIMEOUT_MS;
    const timestamp = (options.now ?? (() => new Date()))().toISOString();
    const token = env.GITHUB_TOKEN;

    if (!token) {
      logAttempt(logger, {
        timestamp,
        http_status: null,
        outcome: 'failed',
        error: 'missing_credential',
      });
      throw new Error('GITHUB_TOKEN is not configured');
    }

    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), timeoutMs);
    let response;
    try {
      response = await fetchImpl(dispatchUrl, {
        method: 'POST',
        headers: {
          Accept: 'application/vnd.github+json',
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
          'User-Agent': userAgent,
          'X-GitHub-Api-Version': '2022-11-28',
        },
        body: JSON.stringify({ ref: 'main' }),
        signal: controller.signal,
      });
    } catch (error) {
      const timedOut = controller.signal.aborted;
      logAttempt(logger, {
        timestamp,
        http_status: null,
        outcome: 'failed',
        error: timedOut ? 'network_timeout' : 'network_failure',
        detail: sanitizedMessage(error, token),
      });
      throw new Error(timedOut ? 'GitHub dispatch timed out' : 'GitHub dispatch failed');
    } finally {
      clearTimeout(timeout);
    }

    if (response.status === 204) {
      logAttempt(logger, { timestamp, http_status: 204, outcome: 'accepted' });
      return { accepted: true, status: 204 };
    }

    const error = failureKind(response);
    const diagnostic = { timestamp, http_status: response.status, outcome: 'failed', error };
    const requestId = response.headers.get('x-github-request-id');
    const retryAfter = response.headers.get('retry-after');
    const rateReset = response.headers.get('x-ratelimit-reset');
    if (requestId) diagnostic.github_request_id = requestId;
    if (retryAfter) diagnostic.retry_after_seconds = retryAfter;
    if (rateReset) diagnostic.rate_limit_reset = rateReset;
    logAttempt(logger, diagnostic);
    throw new Error(`GitHub dispatch was not accepted (${response.status}, ${error})`);
  }

  const worker = {
    scheduled(_controller, env, ctx) {
      ctx.waitUntil(dispatchWorkflow(env));
    },
  };

  return { dispatchUrl, dispatchWorkflow, worker };
}

export { REQUEST_TIMEOUT_MS };
