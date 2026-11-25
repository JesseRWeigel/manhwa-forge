const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { test } = require("node:test");
const { runInNewContext } = require("node:vm");

const template = readFileSync(join(__dirname, "../src/manhwa_forge/templates/index.html"), "utf8");
const script = template.match(/<script>([\s\S]*?)<\/script>/)[1];

async function launch(status) {
  const elements = new Map();
  const requests = [];
  function element(id) {
    if (!elements.has(id)) {
      const classes = new Set();
      elements.set(id, {
        style: {}, value: "fixture", listeners: {},
        classList: {add: x => classes.add(x), remove: x => classes.delete(x), contains: x => classes.has(x)},
        addEventListener(name, fn) { this.listeners[name] = fn; },
      });
    }
    return elements.get(id);
  }
  let stream;
  class FakeEventSource {
    static CLOSED = 2;
    constructor() { stream = this; this.listeners = {}; this.readyState = 1; }
    addEventListener(name, fn) { this.listeners[name] = fn; }
    close() { this.readyState = 2; }
  }
  runInNewContext(script, {
    document: { getElementById: element },
    EventSource: FakeEventSource,
    AbortSignal,
    fetch: async url => {
      requests.push(url);
      if (url === "/api/generate") return {ok: true, json: async () => ({job_id: "d9c1f2409aa2"})};
      if (status === "unreachable") throw new Error("offline");
      return {ok: true, json: async () => ({status})};
    },
  });
  await element("f").listeners.submit({preventDefault() {}});
  return {element, stream, requests};
}

test("a closed stream recovers a chapter already marked done", async () => {
  const {element, stream, requests} = await launch("done");
  stream.close();
  await stream.listeners.error({});
  assert.deepEqual(requests, ["/api/generate", "/api/jobs/d9c1f2409aa2"]);
  assert.equal(element("statusPill").textContent, "done");
  assert.equal(element("finalLink").href, "/api/image/d9c1f2409aa2/chapter.png");
  assert.equal(element("finalBox").classList.contains("active"), true);
  assert.equal(element("go").disabled, false);
});

test("an interrupted render is not shown as done", async () => {
  const {element, stream} = await launch("interrupted");
  stream.close();
  await stream.listeners.error({});
  assert.match(element("errBox").textContent, /interrupted/i);
  assert.equal(element("finalBox").classList.contains("active"), false);
  assert.equal(element("go").disabled, false);
});

test("a reconnecting stream performs no fallback request", async () => {
  const {element, stream, requests} = await launch("done");
  stream.readyState = 0;
  await stream.listeners.error({});
  assert.deepEqual(requests, ["/api/generate"]);
  assert.equal(element("go").disabled, true);
});

test("an unreachable status remains visibly uncertain", async () => {
  const {element, stream} = await launch("unreachable");
  stream.close();
  await stream.listeners.error({});
  assert.match(element("errBox").textContent, /may still be running/i);
  assert.equal(element("go").disabled, false);
});

test("a structured render error is shown directly without a status lookup", async () => {
  const {element, stream, requests} = await launch("done");
  await stream.listeners.error({data: '{"message":"render fixture failed"}'});
  await stream.listeners.error({});
  assert.deepEqual(requests, ["/api/generate"]);
  assert.equal(element("errBox").textContent, "render fixture failed");
  assert.equal(element("statusPill").textContent, "error");
  assert.equal(element("go").disabled, false);
});
