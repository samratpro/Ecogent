/*
 * Baseline runner: Stagehand v3 agent with its action cache and self-heal (called by bench/drift_bench.py).
 *
 *   node bench/baselines/stagehand/run_stagehand.mjs <config.json>
 *
 * config.json: {"prompt", "out_dir", "cache_dir", "llm": {"provider", "model", "base_url"},
 * "browser": {"executable", "headless"}, "max_steps", "timeout_s"}. The API key comes from the
 * BENCH_LLM_KEY environment variable (never written to disk). Writes <out_dir>/result.json like the
 * browser-use runner.
 *
 * Stagehand runs locally (env LOCAL, disableAPI, no server cache), with cacheDir set: the first run
 * records the agent's actions; later runs with the same instruction replay them without the LLM
 * and self-heal (selfHeal: true) when a cached action no longer works - Stagehand's intended use.
 * Every LLM call is counted by a model middleware (calls, input / output / cached tokens).
 */
import fs from "node:fs";
import path from "node:path";
import { Stagehand } from "@browserbasehq/stagehand";

const cfg = JSON.parse(fs.readFileSync(process.argv[2], "utf-8"));
const out = cfg.out_dir;
fs.mkdirSync(out, { recursive: true });
const usage = { calls: 0, input_tokens: 0, output_tokens: 0, cached_input_tokens: 0 };

function count(u) {
  usage.calls += 1;
  if (!u) return;
  usage.input_tokens += Number(u.inputTokens ?? 0) || 0;
  usage.output_tokens += Number(u.outputTokens ?? 0) || 0;
  usage.cached_input_tokens += Number(u.cachedInputTokens ?? 0) || 0;
}

const middleware = {
  wrapGenerate: async ({ doGenerate }) => {
    const r = await doGenerate();
    count(r.usage);
    return r;
  },
  wrapStream: async ({ doStream }) => {
    const r = await doStream();
    const stream = r.stream.pipeThrough(new TransformStream({
      transform(part, controller) {
        if (part.type === "finish") count(part.usage);
        controller.enqueue(part);
      },
    }));
    return { ...r, stream };
  },
};

function modelConfig(llm) {
  const key = process.env.BENCH_LLM_KEY || "";
  if (llm.provider === "anthropic") return { modelName: `anthropic/${llm.model}`, apiKey: key, middleware };
  const base = llm.provider === "openrouter" ? "https://openrouter.ai/api/v1" : (llm.base_url || undefined);
  // "openai/<model>": OpenAI-compatible client; everything after the first "/" is sent as the model id,
  // so OpenRouter ids like "openai/gpt-4o-mini" pass through unchanged.
  return { modelName: `openai/${llm.model}`, apiKey: key, baseURL: base, middleware,
           ...(base ? { openaiEndpointFormat: "chat" } : {}) };
}

async function run() {
  fs.mkdirSync(path.join(out, "profile"), { recursive: true });   // chrome-launcher writes chrome.pid there
  const stagehand = new Stagehand({
    env: "LOCAL",
    model: modelConfig(cfg.llm),
    cacheDir: cfg.cache_dir,
    selfHeal: true,
    verbose: Number(cfg.verbose ?? 1),
    disablePino: true,
    logger: (line) => fs.appendFileSync(path.join(out, "stagehand.log"), JSON.stringify(line) + "\n"),
    disableAPI: true,
    serverCache: false,
    localBrowserLaunchOptions: {
      executablePath: cfg.browser.executable || undefined,
      headless: Boolean(cfg.browser.headless),
      userDataDir: path.join(out, "profile"),
    },
  });
  await stagehand.init();
  try {
    const agent = stagehand.agent();
    const res = await agent.execute({ instruction: cfg.prompt, maxSteps: Number(cfg.max_steps || 60) });
    if (!usage.calls && res.usage) {            // fallback when no call went through the middleware
      usage.input_tokens = res.usage.input_tokens || 0;
      usage.output_tokens = res.usage.output_tokens || 0;
      usage.cached_input_tokens = res.usage.cached_input_tokens || 0;
    }
    return { status: res.completed ? "done" : "failed", claimed_success: !!res.success,
             final_text: res.message || "", files: [], steps: (res.actions || []).length, ...usage,
             model: `${cfg.llm.provider}:${cfg.llm.model}`, error: "" };
  } finally {
    await stagehand.close();
  }
}

const t0 = Date.now();
let result;
try {
  const timeout = new Promise((_, rej) => setTimeout(() => rej(new Error("timeout")), 1000 * Number(cfg.timeout_s || 900)));
  result = await Promise.race([run(), timeout]);
} catch (e) {
  result = { status: String(e?.message) === "timeout" ? "timeout" : "failed", error: String(e?.stack || e).slice(0, 2000), ...usage,
             model: `${cfg.llm.provider}:${cfg.llm.model}` };
}
result.seconds = Math.round((Date.now() - t0) / 100) / 10;
fs.writeFileSync(path.join(out, "result.json"), JSON.stringify(result, null, 2));
process.exit(0);
