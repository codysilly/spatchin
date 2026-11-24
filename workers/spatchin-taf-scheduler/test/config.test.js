import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const configUrl = new URL("../wrangler.toml", import.meta.url);

test("Wrangler configuration names the isolated Worker and ten-minute UTC cron", async () => {
  const config = await readFile(configUrl, "utf8");
  assert.match(config, /^name = "spatchin-taf-scheduler"$/m);
  assert.match(config, /^main = "src\/index\.js"$/m);
  assert.match(config, /^\[triggers\]$/m);
  assert.match(config, /^crons = \["8-58\/10 \* \* \* \*"\]$/m);
  assert.match(config, /^workers_dev = false$/m);
  assert.match(config, /^preview_urls = false$/m);
  assert.doesNotMatch(config, /route|custom_domain|kv_namespaces|d1_databases/i);
  assert.doesNotMatch(config, /GITHUB_TOKEN|token\s*=/i);
});
