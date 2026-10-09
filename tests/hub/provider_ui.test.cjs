// Synthetic React/SDK harness: exercises the shipped panel with no server or API key.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const test = require("node:test");

function harness(profile = "default", fail = false, extraFetch) {
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
      if (extraFetch) {
        const handled = extraFetch(url, options);
        if (handled !== undefined) return handled;
      }
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

test("summary consent is bound to the selected model and changing it requires a new preview", () => {
  const page = harness();
  page.button(page.render(), "Görevler").props.onClick();
  page.walk(page.render()).find(node => node.tag === "textarea" && node.props.maxLength === 400)
    .props.onChange({ target: { value: "sentetik metin" } });
  page.button(page.render(), "Gönderim önizlemesini göster").props.onClick();
  page.walk(page.render()).find(node => node.tag === "input" && node.props.type === "checkbox")
    .props.onChange({ target: { checked: true } });
  page.walk(page.render()).find(node => node.tag === "select")
    .props.onChange({ target: { value: "poolside/laguna-s-2.1:free" } });
  assert.equal(page.button(page.render(), "Onayladığım metni ücretsiz özetle"), undefined);
  assert.equal(page.calls.length, 0);
  page.button(page.render(), "Gönderim önizlemesini göster").props.onClick();
  assert.ok(JSON.stringify(page.render()).includes("Hedef: OpenRouter / poolside/laguna-s-2.1:free"));
  assert.equal(page.button(page.render(), "Onayladığım metni ücretsiz özetle").props.disabled, true);
  page.walk(page.render()).find(node => node.tag === "input" && node.props.type === "checkbox")
    .props.onChange({ target: { checked: true } });
  page.button(page.render(), "Onayladığım metni ücretsiz özetle").props.onClick();
  assert.equal(JSON.parse(page.calls[0].options.body).model, "poolside/laguna-s-2.1:free");
  assert.equal(page.walk(page.render()).find(node => node.tag === "select").props.disabled, true);
});

test("failed summary exposes safe HTTP status and reason without retrying", async () => {
  const page = harness("default", false, url => url.includes("/selected-summary")
    ? Promise.resolve({ status: "stopped", http_status: 404,
      reason: "ücretsiz rota yanıt vermedi", cost_verified: false, hold_status: "unknown" })
    : undefined);
  page.button(page.render(), "Görevler").props.onClick();
  page.walk(page.render()).find(node => node.tag === "textarea" && node.props.maxLength === 400)
    .props.onChange({ target: { value: "sentetik metin" } });
  page.button(page.render(), "Gönderim önizlemesini göster").props.onClick();
  page.walk(page.render()).find(node => node.tag === "input" && node.props.type === "checkbox")
    .props.onChange({ target: { checked: true } });
  page.button(page.render(), "Onayladığım metni ücretsiz özetle").props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  const view = JSON.stringify(page.render());
  assert.ok(view.includes("HTTP 404"));
  assert.ok(view.includes("ücretsiz rota yanıt vermedi"));
  assert.ok(view.includes("uzlaştırılmamış kayıt var"));
  assert.equal(page.calls.filter(call => call.url.includes("/selected-summary")).length, 1);
});

test("apps list reads existing agent names only on click and cannot dispatch", () => {
  const page = harness();
  page.button(page.render(), "Uygulamalar").props.onClick();
  assert.equal(page.calls.length, 0);
  page.button(page.render(), "Mevcut Hermes ajanlarını göster").props.onClick();
  assert.equal(page.calls.length, 1);
  assert.ok(page.calls[0].url.endsWith("/hermes-agents?profile=default"));
  assert.equal(page.calls[0].options, undefined);
  const other = harness("other");
  other.button(other.render(), "Uygulamalar").props.onClick();
  const button = other.button(other.render(), "Mevcut Hermes ajanlarını göster");
  assert.equal(button.props.disabled, true);
  button.props.onClick();
  assert.equal(other.calls.length, 0);
});

test("GitHub is read only, explicit, and disabled outside default profile", () => {
  const page = harness();
  page.button(page.render(), "Uygulamalar").props.onClick();
  assert.equal(page.calls.length, 0);
  page.button(page.render(), "GitHub durumunu oku").props.onClick();
  assert.equal(page.calls.length, 1);
  assert.ok(page.calls[0].url.endsWith("/github-status?profile=default"));
  assert.equal(page.calls[0].options, undefined);
  const other = harness("other");
  other.button(other.render(), "Uygulamalar").props.onClick();
  const button = other.button(other.render(), "GitHub durumunu oku");
  assert.equal(button.props.disabled, true);
  button.props.onClick();
  assert.equal(other.calls.length, 0);
});

test("operation status reads only on click, never dispatches and clears pending double click", () => {
  const page = harness();
  page.button(page.render(), "Görevler").props.onClick();
  assert.equal(page.calls.length, 0);
  page.button(page.render(), "İşlem durumlarını oku").props.onClick();
  assert.equal(page.calls.length, 1);
  assert.ok(page.calls[0].url.endsWith("/operation-status?profile=default"));
  assert.equal(page.calls[0].options, undefined);
  page.button(page.render(), "İşlemler okunuyor…").props.onClick();
  assert.equal(page.calls.length, 1);
  const other = harness("other");
  other.button(other.render(), "Görevler").props.onClick();
  assert.equal(other.button(other.render(), "İşlem durumlarını oku"), undefined);
});

test("generation cost is an explicit click and does not invent an id", async () => {
  const stored = "11111111-1111-4111-8111-111111111111";
  const accepted = "22222222-2222-4222-8222-222222222222";
  const page = harness("default", false, url => {
    if (!url.includes("/operation-status")) return undefined;
    return Promise.resolve({
      total: 2, blocked: true, read_only: true,
      items: [
        { id: stored, state: "unknown", cost_verified: false, generation_id: "gen-aaaaaaaa",
          updated_at: "2026-10-09", day: "2026-10-09" },
        { id: accepted, state: "accepted", cost_verified: false, generation_id: null,
          updated_at: "2026-10-02", day: "2026-10-02" },
      ],
    });
  });
  page.button(page.render(), "Görevler").props.onClick();
  assert.equal(page.calls.some(call => String(call.url).includes("/generation-cost")), false);
  page.button(page.render(), "İşlem durumlarını oku").props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(page.calls.some(call => String(call.url).includes("/generation-cost")), false);
  page.button(page.render(), "Maliyeti doğrula").props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  const storedCall = page.calls.find(call => String(call.url).includes("/generation-cost"));
  assert.equal(storedCall.options.method, "POST");
  assert.ok(storedCall.url.endsWith("/generation-cost?profile=default"));
  assert.deepEqual(JSON.parse(storedCall.options.body), { request_id: stored });
  const before = page.calls.length;
  page.button(page.render(), "Sağlayıcı kanıtıyla uzlaştır").props.onClick();
  assert.equal(page.calls.length, before);
  page.walk(page.render()).find(node => node.tag === "input" && node.props.name === "generation-evidence")
    .props.onChange({ target: { value: "gen-bbbbbbbb" } });
  page.button(page.render(), "Sağlayıcı kanıtıyla uzlaştır").props.onClick();
  assert.equal(page.calls.filter(call => String(call.url).includes("/generation-cost")).length, 1);
  page.walk(page.render()).find(node => node.tag === "input" && node.props.name === "generation-match-confirmed")
    .props.onChange({ target: { checked: true } });
  page.button(page.render(), "Sağlayıcı kanıtıyla uzlaştır").props.onClick();
  const evidence = page.calls.filter(call => String(call.url).includes("/generation-cost"));
  assert.equal(evidence.length, 2);
  assert.deepEqual(JSON.parse(evidence[1].options.body), {
    request_id: accepted, generation_id: "gen-bbbbbbbb", evidence_confirmed: true,
  });
});

test("operation refresh shows safe HTTP evidence and does not call a model", async () => {
  const page = harness("default", false, url => {
    if (!url.includes("/operation-status")) return undefined;
    return Promise.resolve({
      total: 1, blocked: true, read_only: true,
      items: [{
        id: "33333333-3333-4333-8333-333333333333", state: "unknown", cost_verified: false,
        generation_id: null, http_status: 404, error_class: "http_rejected",
        requested_model: "poolside/laguna-s-2.1:free",
        updated_at: "2026-10-09T13:00:00+00:00", day: "2026-10-09",
      }],
    });
  });
  page.button(page.render(), "Görevler").props.onClick();
  assert.equal(page.calls.length, 0);
  page.button(page.render(), "İşlem durumlarını oku").props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  const view = JSON.stringify(page.render());
  assert.ok(view.includes("HTTP: 404"));
  assert.ok(view.includes("HTTP reddi"));
  assert.ok(view.includes("poolside/laguna-s-2.1:free"));
  assert.equal(view.includes("Bunu görev taslağına yaz"), false);
  page.button(page.render(), "İşlem durumlarını oku").props.onClick();
  assert.ok(page.calls.every(call => String(call.url).includes("/operation-status")));
  assert.equal(page.calls.some(call => String(call.url).includes("/free-pilot")
    || String(call.url).includes("/selected-summary")
    || String(call.url).includes("/generation-cost")), false);
});

test("nvidia super is listed and never dispatched from the existing model control", () => {
  const page = harness();
  page.button(page.render(), "Görevler").props.onClick();
  const select = page.walk(page.render()).find(node => node.tag === "select");
  const options = page.walk(select).filter(node => node.tag === "option").map(node => node.props.value);
  assert.ok(options.includes("nvidia/nemotron-3-super-120b-a12b"));
  assert.ok(options.includes("stealth/space-bunny-alpha"));
  select.props.onChange({ target: { value: "nvidia/nemotron-3-super-120b-a12b" } });
  const blocked = page.button(page.render(), "Sentetik ücretsiz testi çalıştır");
  assert.equal(blocked.props.disabled, true);
  blocked.props.onClick();
  assert.equal(page.calls.some(call => call.url.includes("/free-pilot")), false);
  page.button(page.render(), "Görevler").props.onClick();
  const input = page.walk(page.render()).find(node => node.tag === "textarea" && node.props.maxLength === 400);
  input.props.onChange({ target: { value: "sentetik metin" } });
  page.button(page.render(), "Gönderim önizlemesini göster").props.onClick();
  page.walk(page.render()).find(node => node.tag === "input" && node.props.type === "checkbox")
    .props.onChange({ target: { checked: true } });
  const send = page.button(page.render(), "Onayladığım metni ücretsiz özetle");
  assert.equal(send.props.disabled, true);
  send.props.onClick();
  assert.equal(page.calls.some(call => String(call.url).includes("/selected-summary")), false);
  assert.ok(JSON.stringify(page.render()).includes("Fiyat doğrulanmadan"));
});

test("search text reaches a summary only after consent and a draft only after save", async () => {
  const calls = [];
  const states = [];
  const effects = [];
  let cursor = 0;
  let component;
  const snippet = "Sentetik arama parçası";
  const saved = [];
  const SDK = {
    React: { createElement: (tag, props, ...children) => ({ tag, props: props || {}, children }) },
    hooks: {
      useState(initial) {
        const index = cursor++;
        if (!(index in states)) states[index] = typeof initial === "function" ? initial() : initial;
        return [states[index], value => { states[index] = typeof value === "function" ? value(states[index]) : value; }];
      },
      useEffect(fn) { effects.push(fn); },
    },
    fetchJSON(url, options) {
      calls.push({ url, options });
      if (url.includes("/search")) {
        return Promise.resolve({ items: [{ id: "mem_synthetic", kind: "memory", status: "active",
          title: "Sentetik kayıt", snippet }] });
      }
      if (url.includes("/selected-summary")) {
        return Promise.resolve({ status: "completed", cost_verified: true, output: "Kısa sentetik özet." });
      }
      if (url.includes("/tasks")) {
        const method = options && options.method;
        if (method === "POST") {
          const body = JSON.parse(options.body);
          const prior = saved.find(item => item.idempotency_key === body.idempotency_key);
          if (prior) {
            const same = ["title", "goal", "expected_output", "target_app", "data_class", "hermes_session_id"]
              .every(field => prior[field] === body[field]);
            if (!same) return Promise.reject(new Error("aynı işlem kimliği farklı bir taslak için kullanıldı"));
            return Promise.resolve({ created: false, dispatched: false, task: prior });
          }
          const task = Object.assign({ id: "task_synthetic", dispatched: false }, body);
          saved.push(task);
          return Promise.resolve({ created: true, dispatched: false, task });
        }
        return Promise.resolve({
          items: saved.map(item => ({ id: item.id, title: item.title, target_app: item.target_app,
            data_class: item.data_class, expected_output: item.expected_output,
            hermes_session_id: item.hermes_session_id })),
          total: saved.length,
        });
      }
      return Promise.resolve({ items: [], total: 0 });
    },
  };
  const window = { location: { search: "?profile=default" },
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
  button(render(), "Hafıza").props.onClick();
  const search = walk(render()).find(node => node.tag === "input" && node.props.type === "search");
  search.props.onChange({ target: { value: "sentetik" } });
  const form = walk(render()).find(node => node.tag === "form" && node.props.className === "nexus-search");
  form.props.onSubmit({ preventDefault() {} });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(calls.some(call => call.url.includes("/selected-summary")), false);
  button(render(), "Özete aktar").props.onClick();
  assert.equal(calls.some(call => call.url.includes("/selected-summary")), false);
  const summary = walk(render()).find(node => node.tag === "textarea" && node.props.maxLength === 400);
  assert.equal(summary.props.value, snippet);
  button(render(), "Gönderim önizlemesini göster").props.onClick();
  const consent = walk(render()).find(node => node.tag === "input" && node.props.type === "checkbox");
  consent.props.onChange({ target: { checked: true } });
  button(render(), "Onayladığım metni ücretsiz özetle").props.onClick();
  await new Promise(resolve => setImmediate(resolve));
  const summaryCall = calls.find(call => call.url.includes("/selected-summary"));
  assert.equal(JSON.parse(summaryCall.options.body).text, snippet);
  assert.equal(calls.some(call => String(call.url).includes("/tasks") && call.options && call.options.method === "POST"), false);
  button(render(), "Bunu görev taslağına yaz").props.onClick();
  const title = walk(render()).find(node => node.tag === "input" && node.props.maxLength === 160);
  const goal = walk(render()).find(node => node.tag === "textarea" && node.props.maxLength === 2000);
  assert.equal(title.props.value, "Kısa sentetik özet.");
  assert.equal(goal.props.value, "Kısa sentetik özet.");
  assert.equal(calls.some(call => String(call.url).includes("/tasks") && call.options && call.options.method === "POST"), false);
  const saveFormNode = walk(render()).find(node => node.tag === "form" && node.props.className === "nexus-task-form"
    && node.props.onSubmit && node.props.onSubmit.name === "saveDraft");
  saveFormNode.props.onSubmit({ preventDefault() {} });
  await new Promise(resolve => setImmediate(resolve));
  const posts = calls.filter(call => String(call.url).includes("/tasks") && call.options && call.options.method === "POST");
  assert.equal(posts.length, 1);
  const body = JSON.parse(posts[0].options.body);
  assert.equal(body.title, "Kısa sentetik özet.");
  assert.equal(body.goal, "Kısa sentetik özet.");
  assert.equal(body.expected_output, "Onaylı kısa özete dayalı taslak; çalıştırılmadı.");
  assert.equal(body.target_app, "NEXUS");
  assert.equal(saved.length, 1);
  assert.equal(saved[0].dispatched, false);
  const shown = walk(render()).filter(node => node.tag === "strong" && node.children.includes("Kısa sentetik özet."));
  assert.equal(shown.length, 1);
  const saveForm = () => walk(render()).find(node => node.tag === "form" && node.props.onSubmit
    && node.props.onSubmit.name === "saveDraft");
  const refill = (max, value) => walk(saveForm()).find(node =>
    (node.tag === "input" || node.tag === "textarea") && node.props.maxLength === max);
  refill(160).props.onChange({ target: { value: "Kısa sentetik özet." } });
  refill(2000).props.onChange({ target: { value: "Kısa sentetik özet." } });
  refill(1000).props.onChange({ target: { value: "Onaylı kısa özete dayalı taslak; çalıştırılmadı." } });
  const selects = walk(saveForm()).filter(node => node.tag === "select");
  selects[0].props.onChange({ target: { value: "NEXUS" } });
  selects[1].props.onChange({ target: { value: "selected_external" } });
  saveForm().props.onSubmit({ preventDefault() {} });
  await new Promise(resolve => setImmediate(resolve));
  const postsAgain = calls.filter(call => String(call.url).includes("/tasks") && call.options && call.options.method === "POST");
  assert.equal(postsAgain.length, 2);
  assert.equal(JSON.parse(postsAgain[1].options.body).idempotency_key, body.idempotency_key);
  assert.equal(saved.length, 1);
  assert.equal(walk(render()).filter(node => node.tag === "strong" && node.children.includes("Kısa sentetik özet.")).length, 1);
});
