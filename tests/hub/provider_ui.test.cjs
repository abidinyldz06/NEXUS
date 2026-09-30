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
  const window = { location: { search: "?profile=" + profile },
    crypto: { getRandomValues(bytes) { return bytes.fill(1); } }, __HERMES_PLUGIN_SDK__: SDK,
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

test("pilot is explicit and sends only selected model and id, never draft content", () => {
  const page = harness();
  page.button(page.render(), "Görevler").props.onClick();
  page.render();
  assert.equal(page.calls.length, 0);
  page.button(page.render(), "Sentetik ücretsiz testi çalıştır").props.onClick();
  const call = page.calls.find(item => item.url.includes("/free-pilot"));
  assert.equal(call.options.method, "POST");
  const body = JSON.parse(call.options.body);
  assert.deepEqual(Object.keys(body).sort(), ["model", "request_id"]);
  assert.equal(body.model, "stealth/space-bunny-alpha");
  assert.equal(page.button(page.render(), "Test çalışıyor…").props.disabled, true);
});

test("failed fetch shows a generic error without leaking transport details", async () => {
  const page = harness("default", true);
  page.button(page.render(), "Sağlayıcı kullanım/limit bilgisini oku").props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  const text = JSON.stringify(page.render());
  assert.ok(text.includes("eski veri gösterilmiyor"));
  assert.ok(!text.includes("synthetic-private-error"));
});

test("selected summary preview stays local and clears when the selection changes", () => {
  const page = harness();
  page.button(page.render(), "Görevler").props.onClick();
  const label = "Gönderim önizlemesini göster";
  assert.equal(page.button(page.render(), label).props.disabled, true);
  let input = page.walk(page.render()).find(node => node.tag === "textarea" && node.props.maxLength === 400);
  const text = "<script>sentetik veri</script>";
  input.props.onChange({ target: { value: text } });
  page.button(page.render(), label).props.onClick();
  assert.equal(page.calls.length, 0);
  const preview = page.walk(page.render()).find(node => node.tag === "pre");
  assert.equal(preview.children[0], text);
  assert.ok(!preview.props.dangerouslySetInnerHTML);
  input = page.walk(page.render()).find(node => node.tag === "textarea" && node.props.maxLength === 400);
  input.props.onChange({ target: { value: "yeni metin" } });
  assert.ok(!page.walk(page.render()).some(node => node.tag === "pre"));
  input.props.onChange({ target: { value: "a".repeat(401) } });
  assert.equal(page.button(page.render(), label).props.disabled, true);
  page.button(page.render(), label).props.onClick();
  assert.ok(!page.walk(page.render()).some(node => node.tag === "pre"));
  assert.equal(page.calls.length, 0);
});

test("selected summary preview is unavailable outside the default profile", () => {
  const page = harness("other");
  page.button(page.render(), "Görevler").props.onClick();
  assert.equal(page.button(page.render(), "Gönderim önizlemesini göster"), undefined);
  assert.equal(page.calls.length, 0);
});

test("summary dispatch requires current preview and fresh checkbox consent", () => {
  const page = harness();
  page.button(page.render(), "Görevler").props.onClick();
  const input = () => page.walk(page.render()).find(node => node.tag === "textarea" && node.props.maxLength === 400);
  input().props.onChange({ target: { value: "sentetik metin" } });
  page.button(page.render(), "Gönderim önizlemesini göster").props.onClick();
  const send = "Onayladığım metni ücretsiz özetle";
  assert.equal(page.button(page.render(), send).props.disabled, true);
  page.button(page.render(), send).props.onClick();
  assert.equal(page.calls.length, 0);
  let checkbox = page.walk(page.render()).find(node => node.tag === "input" && node.props.type === "checkbox");
  checkbox.props.onChange({ target: { checked: true } });
  page.button(page.render(), send).props.onClick();
  assert.equal(page.calls.length, 1);
  const call = page.calls[0];
  assert.ok(call.url.includes("/selected-summary?profile=default"));
  assert.equal(call.options.method, "POST");
  const body = JSON.parse(call.options.body);
  assert.equal(body.text, "sentetik metin");
  assert.equal(body.model, "stealth/space-bunny-alpha");
  assert.equal(body.external_authorized, true);
  assert.equal(body.non_sensitive, true);
  assert.equal(page.button(page.render(), "Özet hazırlanıyor…").props.disabled, true);
  assert.equal(input().props.disabled, true);
});
