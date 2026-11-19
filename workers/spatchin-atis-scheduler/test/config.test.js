import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const configUrl = new URL("../wrangler.toml", import.meta.url);

test("Wrangler configuration names the isolated Worker and hourly UTC cron", async () => {
  const config = await readFile(configUrl, "utf8");
  assert.match(config, /^name = "spatchin-atis-scheduler"$/m);
  assert.match(config, /^main = "src\/index\.js"$/m);
  assert.match(config, /^\[triggers\]$/m);
  assert.match(config, /^crons = \["0 \* \* \* \*"\]$/m);
  assert.doesNotMatch(config, /route|custom_domain|kv_namespaces|d1_databases/i);
  assert.doesNotMatch(config, /GITHUB_TOKEN|token\s*=/i);
});
