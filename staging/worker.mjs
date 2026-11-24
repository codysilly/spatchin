import { verifyAccessJwt } from './verify.mjs';
import { makeHandler } from './worker-core.mjs';
// Authentication is fail-closed even if Cloudflare Access is mistakenly disabled.
export default { fetch: makeHandler(verifyAccessJwt) };
