// Entry-point-independent security boundary. Never serve assets before auth.
const allowedData = new Set(['metars.json', 'atis.json', 'runways.json', 'notams.json']);
const securityHeaders = Object.freeze({
  'Cache-Control': 'private, no-store',
  'X-Content-Type-Options': 'nosniff',
  'X-Robots-Tag': 'noindex, nofollow, noarchive',
  'Referrer-Policy': 'no-referrer',
  'Content-Security-Policy': "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; object-src 'none'; script-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com"
});

function withSecurity(response) {
  const headers = new Headers(response.headers);
  for (const [key, value] of Object.entries(securityHeaders)) headers.set(key, value);
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}
function deny() {
  return withSecurity(new Response('Access denied', { status: 403, headers: { 'Content-Type': 'text/plain; charset=utf-8' } }));
}
function parseConfig(env) {
  const issuer = env?.TEAM_DOMAIN?.trim();
  const audience = env?.POLICY_AUD?.trim();
  const emails = env?.ALLOWED_EMAILS?.trim();
  // Only a configured Cloudflare team domain is trusted; never derive JWKS from a request or JWT.
  if (!/^https:\/\/[a-z0-9-]+\.cloudflareaccess\.com$/.test(issuer || '') ||
      !/^[A-Za-z0-9_-]{16,256}$/.test(audience || '') || !emails) return null;
  const allow = new Set(emails.split(',').map(s => s.trim().toLowerCase()).filter(Boolean));
  if (allow.size === 0 || [...allow].some(v => !/^[^\s@,]+@[^\s@,]+\.[^\s@,]+$/.test(v))) return null;
  return { issuer, audience, allow };
}
// verifyToken must verify signature, expected issuer, audience, exp and nbf (see verify.mjs).
export function makeHandler(verifyToken, fetchPublic = fetch) {
  return async (request, env) => {
    if (!['GET', 'HEAD'].includes(request.method)) {
      return withSecurity(new Response('Method not allowed', { status: 405, headers: { Allow: 'GET, HEAD' } }));
    }
    const config = parseConfig(env);
    if (!config || !env?.ASSETS || typeof env.ASSETS.fetch !== 'function') return deny();
    const token = request.headers.get('Cf-Access-Jwt-Assertion');
    if (!token) return deny();
    let identity;
    try {
      identity = await verifyToken(token, config.issuer, config.audience);
    } catch {
      return deny();
    }
    if (!config.allow.has(String(identity?.email || '').toLowerCase())) return deny();
    const url = new URL(request.url);
    // Refuse alternate hostnames even if another Worker URL is accidentally enabled.
    if (url.hostname !== 'dev.spatchin.com' || url.protocol !== 'https:') return deny();
    const dataMatch = /^\/data\/([a-z]+\.json)$/.exec(url.pathname);
    if (dataMatch) {
      if (!allowedData.has(dataMatch[1])) return withSecurity(new Response('Not found', { status: 404 }));
      try {
        // Read existing public snapshots only. Never call the FAA, AWC or atis.info.
        const upstream = await fetchPublic('https://www.spatchin.com/data/' + dataMatch[1], {
          method: 'GET', cache: 'no-store', redirect: 'error'
        });
        if (!upstream.ok) throw new Error('Snapshot unavailable');
        return withSecurity(new Response(request.method === 'HEAD' ? null : upstream.body, {
          status: 200, headers: { 'Content-Type': 'application/json; charset=utf-8' }
        }));
      } catch {
        return withSecurity(new Response('Snapshot unavailable', { status: 503 }));
      }
    }
    // The static-asset router MUST invoke this Worker first for every request.
    // The build directory contains only explicit dashboard files.
    try {
      const response = await env.ASSETS.fetch(request);
      return withSecurity(response);
    } catch {
      return withSecurity(new Response('Unavailable', { status: 503 }));
    }
  };
}
