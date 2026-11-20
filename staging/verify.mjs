import { createRemoteJWKSet, jwtVerify } from 'jose';
// JWKS URL is constructed from trusted Cloudflare configuration, not the JWT.
const jwksCache = new Map();
export async function verifyAccessJwt(token, issuer, audience) {
  let keys = jwksCache.get(issuer);
  if (!keys) {
    keys = createRemoteJWKSet(new URL(issuer + '/cdn-cgi/access/certs'));
    jwksCache.set(issuer, keys);
  }
  const { payload } = await jwtVerify(token, keys, {
    issuer,
    audience,
    algorithms: ['RS256'],
    requiredClaims: ['exp', 'iat', 'aud', 'iss']
  });
  return payload;
}
