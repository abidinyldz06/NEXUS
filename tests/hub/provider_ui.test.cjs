// Synthetic React/SDK harness: exercises the shipped panel with no server or API key.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

function harness(profile = "default", fail = false) {
  const states = [], effects = [], calls = [];
  let cursor = 0, component;
  const SDK = {
    React: { createElement: (tag, props, ...children) => ({ tag, props: props || {}, children }) },
    hooks: {
      useState(initial) {
        const index = cursor++;
        if (!(index in states)) states[index] = typeof initial === "function" ? initial() : initial;
        return [states[index], value => { states[index] = value; }];
      },
      useEffect(fn) { effects.push(fn); },
    },
    fetchJSON(url, options) {
      calls.push({ url, options });
      if (!url.includes("/providers/")) return Promise.resolve({});
      if (fail) return Promise.reject(new Error("synthetic-private-error"));
      const provider = url.split("/providers/")[1].split("/")[0];
      return Promise.resolve({ provider, inference_called: false, reason: "sentetik sonuç",
        metrics: provider === "openrouter" ? { usage: 0, limit_remaining: null } : null });
    },
  };
  const window = { location: { search: "?profile=" + profile }, __HERMES_PLUGIN_SDK__: SDK,
    __HERMES_PLUGINS__: { register(_name, value) { component = value; } } };
  vm.runInNewContext(fs.readFileSync(path.join(__dirname, "../../dashboard/dist/index.js"), "utf8"),
    { window, URLSearchParams });
  function render() { cursor = 0; return component(); }
  function walk(tree) {
    if (Array.isArray(tree)) return tree.flatMap(walk);
    if (!tree || typeof tree !== "object") return [];
    return [tree, ...tree.children.flatMap(walk)];
  }
  function button(tree, label) {
    return walk(tree).find(node => node.tag === "button" && node.children.includes(label));
  }
  button(render(), "Modeller ve kullanım").props.onClick();
  return { render, calls, effects, button, walk };
}

test("panel opening and effects do not fetch provider usage; explicit click uses POST", async () => {
  const page = harness();
  page.render();
  for (const effect of page.effects) effect();
  assert.equal(page.calls.filter(call => call.url.includes("/providers/")).length, 0);
  page.button(page.render(), "Sağlayıcı kullanım/limit bilgisini oku").props.onClick();
  assert.equal(page.button(page.render(), "Okunuyor…").props.disabled, true);
  await new Promise(resolve => setImmediate(resolve));
  const calls = page.calls.filter(call => call.url.includes("/providers/"));
  assert.equal(calls.length, 4);
  assert.ok(calls.every(call => call.options.method === "POST"));
  assert.ok(calls.every(call => !call.options.body));
  const text = JSON.stringify(page.render());
  assert.ok(text.includes("Bilinmiyor"));
  assert.ok(text.includes("0 USD"));
});

test("non-default profile cannot trigger provider query", () => {
  const page = harness("other");
  const button = page.button(page.render(), "Sağlayıcı kullanım/limit bilgisini oku");
  assert.equal(button.props.disabled, true);
  button.props.onClick();
  assert.equal(page.calls.length, 0);
});

test("failed fetch shows a generic error without leaking transport details", async () => {
  const page = harness("default", true);
  page.button(page.render(), "Sağlayıcı kullanım/limit bilgisini oku").props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  const text = JSON.stringify(page.render());
  assert.ok(text.includes("eski veri gösterilmiyor"));
  assert.ok(!text.includes("synthetic-private-error"));
});
