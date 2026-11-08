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
import { z } from "zod";

// The agent's own "done" message is a one-line summary, so the requested data/report is asked for through
// Stagehand's documented `output` schema (filled in the final done call) - like browser-use's done text.
const OUTPUT = z.object({
  answer: z.string().describe("The complete final answer the task asks for (the full report, list or data), not a summary of what you did"),
});

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

// Stagehand 3.7.3's act() schema has a nullable object (anyOf [object, null]) without
// "additionalProperties": false. OpenAI strict structured output (also behind OpenRouter) rejects it with
// HTTP 400, so every act() failed. Closing every object schema is what strict mode requires; prompts and
// Stagehand's logic are unchanged.
function closeObjects(s) {
  if (Array.isArray(s)) return s.map(closeObjects);
  if (!s || typeof s !== "object") return s;
  const o = Object.fromEntries(Object.entries(s).map(([k, v]) => [k, closeObjects(v)]));
  if (o.type === "object" && o.properties && o.additionalProperties === undefined) o.additionalProperties = false;
  return o;
}

const middleware = {
  transformParams: async ({ params }) =>
    params.responseFormat?.type === "json" && params.responseFormat.schema
      ? { ...params, responseFormat: { ...params.responseFormat, schema: closeObjects(params.responseFormat.schema) } }
      : params,
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
    // Needed only for the agent `output` schema. Checked in 3.7.3 local mode: the flag is otherwise passed
    // to the a11y snapshot / LLM client without being read, so act/extract/cache behave the same.
    experimental: true,
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
    const res = await agent.execute({ instruction: cfg.prompt, maxSteps: Number(cfg.max_steps || 60), output: OUTPUT });
    const answer = typeof res.output?.answer === "string" ? res.output.answer : "";
    if (!usage.calls && res.usage) {            // fallback when no call went through the middleware
      usage.input_tokens = res.usage.input_tokens || 0;
      usage.output_tokens = res.usage.output_tokens || 0;
      usage.cached_input_tokens = res.usage.cached_input_tokens || 0;
    }
    return { status: res.completed ? "done" : "failed", claimed_success: !!res.success,
             final_text: [answer, res.message || ""].filter(Boolean).join("\n\n"), files: [], steps: (res.actions || []).length, ...usage,
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
