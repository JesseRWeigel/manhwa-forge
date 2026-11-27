const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { test } = require("node:test");
const { runInNewContext } = require("node:vm");

const template = readFileSync(join(__dirname, "../src/manhwa_forge/templates/index.html"), "utf8");
const script = template.match(/<script>([\s\S]*?)<\/script>/)[1];

async function launch(status, nextStartError) {
  const elements = new Map();
  const requests = [];
  const saved = new Map();
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
  let starts = 0;
  class FakeEventSource {
    static CLOSED = 2;
    constructor() { stream = this; this.listeners = {}; this.readyState = 1; }
    addEventListener(name, fn) { this.listeners[name] = fn; }
    close() { this.readyState = 2; }
  }
  runInNewContext(script, {
    document: { getElementById: element },
    EventSource: FakeEventSource,
    sessionStorage: {setItem: (key, value) => saved.set(key, value)},
    AbortSignal,
    fetch: async url => {
      requests.push(url);
      if (url === "/api/generate") {
        if (++starts > 1 && nextStartError) {
          return {ok: false, json: async () => ({error: nextStartError})};
        }
        return {ok: true, json: async () => ({job_id: "d9c1f2409aa2"})};
      }
      if (status === "unreachable") throw new Error("offline");
      return {ok: true, json: async () => ({status})};
    },
  });
  await element("f").listeners.submit({preventDefault() {}});
  return {element, stream, requests, saved};
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

test("a rejected new render keeps the preceding chapter available", async () => {
  const {element, stream} = await launch("done", "A render is already running.");
  stream.listeners.done({data: '{"url":"/api/image/previous/chapter.png"}'});
  await element("f").listeners.submit({preventDefault() {}});
  assert.equal(element("finalBox").classList.contains("active"), true);
  assert.equal(element("finalLink").href, "/api/image/previous/chapter.png");
  assert.equal(element("statusPill").textContent, "done");
  assert.match(element("errBox").textContent, /already running/);
  assert.equal(element("go").disabled, false);
});

test("a successful new render clears the preceding chapter", async () => {
  const {element, stream} = await launch("done");
  stream.listeners.done({data: '{"url":"/api/image/previous/chapter.png"}'});
  await element("f").listeners.submit({preventDefault() {}});
  assert.equal(element("finalBox").classList.contains("active"), false);
  assert.equal(element("statusPill").textContent, "rendering…");
  assert.equal(element("go").disabled, true);
});

test("another submit while rendering does not send a second POST", async () => {
  const {element, requests} = await launch("done");
  await element("f").listeners.submit({preventDefault() {}});
  assert.deepEqual(requests, ["/api/generate"]);
});

test("expired progress recovers a completed chapter without another render", async () => {
  const {element, stream, requests} = await launch("done");
  await stream.listeners["progress-expired"]?.({data: '{"message":"history expired"}'});
  await stream.listeners.error({});
  assert.deepEqual(requests, ["/api/generate", "/api/jobs/d9c1f2409aa2"]);
  assert.equal(element("statusPill").textContent, "done");
  assert.equal(element("finalLink").href, "/api/image/d9c1f2409aa2/chapter.png");
  assert.equal(element("go").disabled, false);
});

test("expired progress does not label a still-running job as failed", async () => {
  const {element, stream, requests} = await launch("running");
  await stream.listeners["progress-expired"]?.({});
  assert.deepEqual(requests, ["/api/generate", "/api/jobs/d9c1f2409aa2"]);
  assert.equal(element("statusPill").textContent, "disconnected");
  assert.match(element("errBox").textContent, /may still be running/i);
  assert.equal(element("go").disabled, false);
});

async function restoredPage(status, storedId = "d9c1f2409aa2") {
  const requests = [], elements = new Map();
  let stored = storedId;
  let stream;
  function element(id) {
    if (!elements.has(id)) {
      const classes = new Set();
      elements.set(id, {
        style: {}, classList: {add: x => classes.add(x), remove: x => classes.delete(x), contains: x => classes.has(x)},
        addEventListener() {},
      });
    }
    return elements.get(id);
  }
  class FakeEventSource {
    constructor(url) { requests.push(url); stream = this; this.listeners = {}; }
    addEventListener(name, fn) { this.listeners[name] = fn; }
    close() {}
  }
  runInNewContext(script, {
    document: {getElementById: element},
    sessionStorage: {
      getItem: () => stored,
      removeItem: () => { stored = null; },
    },
    EventSource: FakeEventSource,
    AbortSignal,
    fetch: async url => {
      requests.push(url);
      if (status === "unreachable") throw new Error("offline");
      return {ok: status !== "missing", status: status === "missing" ? 404 : 200, json: async () => ({status})};
    },
  });
  await new Promise(setImmediate);
  return {element, requests, stream, stored};
}

test("refresh restores a completed chapter without starting another render", async () => {
  const {element, requests, stored} = await restoredPage("done");
  assert.deepEqual(requests, ["/api/jobs/d9c1f2409aa2"]);
  assert.equal(element("finalBox").classList.contains("active"), true);
  assert.equal(element("finalLink").href, "/api/image/d9c1f2409aa2/chapter.png");
  assert.equal(element("go").disabled, false);
  assert.equal(stored, "d9c1f2409aa2");
});

test("refresh reconnects to running progress and keeps submission disabled", async () => {
  const {element, requests, stream} = await restoredPage("running");
  assert.deepEqual(requests, ["/api/jobs/d9c1f2409aa2", "/api/stream/d9c1f2409aa2"]);
  assert.equal(element("go").disabled, true);
  stream.listeners.done({data: '{"url":"/api/image/d9c1f2409aa2/chapter.png"}'});
  assert.equal(element("finalBox").classList.contains("active"), true);
  assert.equal(element("go").disabled, false);
});

test("refresh forgets an unknown job without inventing a render failure", async () => {
  const {element, requests, stored} = await restoredPage("missing");
  assert.deepEqual(requests, ["/api/jobs/d9c1f2409aa2"]);
  assert.equal(element("errBox").classList.contains("active"), false);
  assert.equal(element("go").disabled, false);
  assert.equal(stored, null);
});

test("refresh will not query an invalid stored job ID", async () => {
  const {requests, stored} = await restoredPage("done", "../invalid");
  assert.deepEqual(requests, []);
  assert.equal(stored, null);
});

test("a temporary status error on refresh does not discard the job ID", async () => {
  const {element, requests, stored} = await restoredPage("unreachable");
  assert.deepEqual(requests, ["/api/jobs/d9c1f2409aa2"]);
  assert.match(element("errBox").textContent, /may still be running/i);
  assert.equal(element("go").disabled, false);
  assert.equal(stored, "d9c1f2409aa2");
});

test("an accepted render stores only its ID in the tab and a rejection preserves it", async () => {
  const {element, stream, saved} = await launch("done", "A render is already running.");
  assert.deepEqual([...saved], [["manhwa-forge:last-job", "d9c1f2409aa2"]]);
  stream.listeners.done({data: '{"url":"/api/image/d9c1f2409aa2/chapter.png"}'});
  await element("f").listeners.submit({preventDefault() {}});
  assert.deepEqual([...saved], [["manhwa-forge:last-job", "d9c1f2409aa2"]]);
});
