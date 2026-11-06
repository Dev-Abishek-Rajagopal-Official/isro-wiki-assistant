import { describe, expect, it } from "vitest";
import { linkCitations } from "../components/Markdown";
import { buildSteps, summarizeResult } from "../features/steps/buildSteps";
import { applyMessage, emptyRun, type LiveRun } from "../features/runs/runsSlice";
import { encodeWav } from "../lib/audio";
import { storedToMessage } from "../lib/events";
import type { WsMessage } from "../lib/types";

const T = "thread-1";
let id = 0;
const m = (type: string, data: Record<string, unknown> = {}, extra: Partial<WsMessage> = {}): WsMessage =>
  ({ type, thread_id: T, run_id: "run-1", event_id: ++id, ts: new Date(2026, 0, 1, 0, 0, id).toISOString(), data, ...extra });

function play(messages: WsMessage[], start: LiveRun | undefined = { ...emptyRun("q"), status: "pending" }) {
  return messages.reduce<LiveRun | undefined>((run, msg) => applyMessage(run, msg), start);
}

const happyPath = () => [
  m("run_started", { question: "Is Cartosat-3 in orbit?", input_type: "text" }),
  m("llm_call", { role: "router", model: "gpt", input_tokens: 10, output_tokens: 2 }, { node: "router" }),
  m("router_decision", { structured: { next_agent: "celestrak_agent", task: "check Cartosat-3", reason: "live data" } }),
  m("agent_progress", { task: "check Cartosat-3" }, { step: "agent_started", node: "celestrak_agent" }),
  m("agent_progress", { rewritten_query: "CARTOSAT-3 status", tool_calls: [{ tool: "search_satellites", arguments_json: "{}" }] },
    { step: "query_rewritten", node: "celestrak_agent" }),
  m("agent_progress", { tool: "search_satellites", arguments: '{"name":"CARTOSAT-3"}' }, { step: "tool_called", node: "celestrak_agent" }),
  m("agent_progress", { tool: "search_satellites", ok: true, empty: false, duration_ms: 400, result: { satellites: [{ name: "CARTOSAT-3" }] } },
    { step: "tool_result", node: "celestrak_agent" }),
  m("agent_progress", { content: "Still in orbit [S1]", sources: [{ title: "CelesTrak", url: "u" }] }, { step: "agent_content", node: "celestrak_agent" }),
];

describe("runs reducer", () => {
  it("builds a live run from messages and streams tokens", () => {
    const run = play([...happyPath(), m("token", { text: "Yes, " }), m("token", { text: "still in orbit." })])!;
    expect(run.status).toBe("running");
    expect(run.question).toBe("Is Cartosat-3 in orbit?");
    expect(run.answer).toBe("Yes, still in orbit.");
    const done = play([m("final_answer", { answer: "Yes [1]", sources: [{ n: 1, title: "x" }] }),
      m("run_finished", { seconds: 9.5, agents_used: ["celestrak_agent"], run_usage: { llm_calls: 4, input_tokens: 100, output_tokens: 20 } })], run)!;
    expect(done.status).toBe("succeeded");
    expect(done.answer).toBe("Yes [1]");
    expect(done.runUsage?.llm_calls).toBe(4);
  });

  it("starts fresh on a new run (replayed history ends with the latest run)", () => {
    const first = play(happyPath())!;
    const second = applyMessage(first, m("run_started", { question: "second" }, { run_id: "run-2" }))!;
    expect(second.runId).toBe("run-2");
    expect(second.timeline).toHaveLength(0);
  });

  it("marks failures", () => {
    const run = play([...happyPath(), m("error", { error: "boom" })])!;
    expect(run.status).toBe("failed");
    expect(run.error).toBe("boom");
  });

  it("ignores messages for runs it does not know (no crash)", () => {
    expect(applyMessage(undefined, m("token", { text: "x" }))).toBeUndefined();
  });
});

describe("buildSteps", () => {
  it("maps events to router -> agent (with tool call) -> waiting", () => {
    const steps = buildSteps(play(happyPath()));
    expect(steps.map((s) => s.kind)).toEqual(["router", "agent", "waiting"]);
    const [router, agent] = steps;
    expect(router.title).toBe("Router → Satellite tracker");
    expect(router.llm).toHaveLength(1);                         // router LLM call attached
    expect(agent.status).toBe("done");
    expect(agent.tools[0]).toMatchObject({ tool: "search_satellites", status: "ok", durationMs: 400 });
    expect(agent.rewrites[0].rewritten_query).toBe("CARTOSAT-3 status");
    expect(agent.content).toContain("Still in orbit");
  });

  it("shows a running tool call before its result arrives", () => {
    const steps = buildSteps(play(happyPath().slice(0, 6)));
    const agent = steps.find((s) => s.kind === "agent")!;
    expect(agent.status).toBe("running");
    expect(agent.tools[0].status).toBe("running");
    expect(agent.detail).toBe("Calling search_satellites…");
  });

  it("completes the final step when the run succeeds", () => {
    const run = play([...happyPath(),
      m("router_decision", { structured: { next_agent: "final_agent", reason: "enough" } }),
      m("agent_progress", { task: "write" }, { step: "agent_started", node: "final_agent" }),
      m("final_answer", { answer: "Yes", sources: [] }), m("run_finished", { seconds: 3 })]);
    const steps = buildSteps(run);
    expect(steps.at(-1)).toMatchObject({ kind: "final", status: "done" });
    expect(steps.some((s) => s.kind === "waiting")).toBe(false);
  });

  it("shows a waiting row before the first decision", () => {
    const steps = buildSteps(play([m("run_started", { question: "q" })]));
    expect(steps).toHaveLength(1);
    expect(steps[0]).toMatchObject({ kind: "waiting", status: "running" });
  });

  it("summarises tool results", () => {
    expect(summarizeResult("search_isro_documents", { results: [{}, {}] })).toBe("2 passages found");
    expect(summarizeResult("upcoming_isro_launches", { launches: [{}] })).toBe("1 launch");
  });
});

describe("helpers", () => {
  it("encodes 16-bit PCM WAV", () => {
    const buf = encodeWav(new Float32Array([0, 1, -1]), 16000);
    const v = new DataView(buf);
    expect(String.fromCharCode(...new Uint8Array(buf, 0, 4))).toBe("RIFF");
    expect(v.getUint32(24, true)).toBe(16000);
    expect(v.getInt16(46, true)).toBe(32767);
    expect(v.getInt16(48, true)).toBe(-32768);
    expect(buf.byteLength).toBe(44 + 6);
  });

  it("turns [n] citations into links but leaves real links alone", () => {
    expect(linkCitations("Fact [1][2].")).toBe("Fact [1](#cite-1)[2](#cite-2).");
    expect(linkCitations("[docs](https://x)")).toBe("[docs](https://x)");
  });

  it("maps stored events to WebSocket messages", () => {
    const msg = storedToMessage({ id: 5, ts: "t", seq: 2, node: "rag_agent", event_type: "tool_result", payload: { ok: true } }, "history:r");
    expect(msg).toMatchObject({ type: "agent_progress", step: "tool_result", thread_id: "history:r", event_id: 5, replay: true });
    expect(storedToMessage({ id: 6, ts: "t", seq: 3, node: null, event_type: "run_finished", payload: {} }, "k").type).toBe("run_finished");
  });
});
