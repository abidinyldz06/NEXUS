(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;
  const h = SDK.React.createElement;
  const { useEffect, useState } = SDK.hooks;
  const API = "/api/plugins/nexus/hub";
  const tabs = [
    ["today", "Bugün"], ["apps", "Uygulamalar"], ["tasks", "Görevler"],
    ["memory", "Hafıza"], ["models", "Modeller ve kullanım"],
  ];

  function errorText(error) {
    const raw = error && error.message ? String(error.message) : "Bağlantı kurulamadı";
    const body = raw.replace(/^\d{3}:\s*/, "");
    try {
      const parsed = JSON.parse(body);
      return typeof parsed.detail === "string" ? parsed.detail : "İşlem tamamlanamadı";
    } catch (_ignored) {
      return body;
    }
  }

  function panel(title, children, extraClass, key) {
    return h("section", { key: key, className: "nexus-card " + (extraClass || "") },
      h("h2", null, title), children);
  }

  function HubPage() {
    const [tab, setTab] = useState("today");
    const [overview, setOverview] = useState(null);
    const [overviewError, setOverviewError] = useState("");
    const [reviews, setReviews] = useState(null);
    const [reviewError, setReviewError] = useState("");
    const [query, setQuery] = useState("");
    const [results, setResults] = useState(null);
    const [searchError, setSearchError] = useState("");
    const [searching, setSearching] = useState(false);
    const [detail, setDetail] = useState(null);
    const [detailError, setDetailError] = useState("");
    const [tasks, setTasks] = useState(null);
    const [taskError, setTaskError] = useState("");
    const [savingTask, setSavingTask] = useState(false);
    const [draft, setDraft] = useState({ title: "", goal: "", expected_output: "", target_app: "Hermes" });
    const [draftKey, setDraftKey] = useState(function () { return crypto.randomUUID(); });

    useEffect(function () {
      let active = true;
      SDK.fetchJSON(API + "/overview").then(function (data) {
        if (active) setOverview(data);
      }).catch(function (error) {
        if (active) setOverviewError(errorText(error));
      });
      SDK.fetchJSON(API + "/reviews?limit=20").then(function (data) {
        if (active) setReviews(data);
      }).catch(function (error) {
        if (active) setReviewError(errorText(error));
      });
      SDK.fetchJSON(API + "/tasks?limit=30").then(function (data) {
        if (active) setTasks(data);
      }).catch(function (error) {
        if (active) setTaskError(errorText(error));
      });
      return function () { active = false; };
    }, []);

    function editDraft(field, value) {
      setDraft(function (current) { return Object.assign({}, current, { [field]: value }); });
      setDraftKey(crypto.randomUUID());
      setTaskError("");
    }

    function saveDraft(event) {
      event.preventDefault();
      if (savingTask) return;
      setSavingTask(true);
      setTaskError("");
      SDK.fetchJSON(API + "/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.assign({ idempotency_key: draftKey }, draft)),
      }).then(function () {
        return SDK.fetchJSON(API + "/tasks?limit=30");
      }).then(function (data) {
        setTasks(data);
        setDraft({ title: "", goal: "", expected_output: "", target_app: "Hermes" });
        setDraftKey(crypto.randomUUID());
      }).catch(function (error) {
        setTaskError(errorText(error));
      }).finally(function () { setSavingTask(false); });
    }

    function runSearch(event) {
      event.preventDefault();
      const trimmed = query.trim();
      if (!trimmed) return;
      setSearching(true);
      setResults(null);
      setSearchError("");
      setDetail(null);
      SDK.fetchJSON(API + "/search?q=" + encodeURIComponent(trimmed) + "&limit=20")
        .then(setResults)
        .catch(function (error) { setSearchError(errorText(error)); })
        .finally(function () { setSearching(false); });
    }

    function openDetail(kind, id) {
      setDetail(null);
      setDetailError("");
      const path = kind === "review" ? "/reviews/" : "/records/";
      SDK.fetchJSON(API + path + encodeURIComponent(id))
        .then(setDetail)
        .catch(function (error) { setDetailError(errorText(error)); });
    }

    const index = overview && overview.index;
    const reviewState = overview && overview.review;
    let content;
    if (tab === "today") {
      content = h("div", { className: "nexus-grid" },
        panel("Hafıza", h("div", null,
          h("p", { className: "nexus-number" }, index && index.ready ? index.records : "—"),
          h("p", null, index && index.ready ? "Aranabilir kayıt" : "Arama henüz hazır değil"),
          h("button", { type: "button", onClick: function () { setTab("memory"); } }, "Hafızaya git"))),
        panel("Bekleyen inceleme", h("div", null,
          h("p", { className: "nexus-number" }, reviewState && reviewState.ready ? reviewState.pending : "—"),
          h("p", null, reviewState && reviewState.ready ? "İnsan kararı bekleyen aday" : "Kuyruk okunamadı"),
          h("button", { type: "button", onClick: function () { setTab("memory"); } }, "Adayları gör"))),
        panel("Çalışma durumu", h("div", null,
          h("p", null, "Bu panel verileri görüntüler; sayfayı açmak model çağırmaz."),
          h("p", { className: "nexus-muted" }, index && index.updated_at ?
            "İndeks: " + new Date(index.updated_at).toLocaleString("tr-TR") : "İndeks zamanı bilinmiyor"))));
    } else if (tab === "apps") {
      content = h("div", { className: "nexus-grid" },
        (overview && overview.apps || []).map(function (app) {
          return panel(app.name, h("p", null, app.status), "nexus-app", app.name);
        }),
        !overview && panel("Bağlantılar", h("p", null, "Bağlantı durumları yükleniyor.")));
    } else if (tab === "tasks") {
      const taskItems = tasks && tasks.items || [];
      content = h("div", { className: "nexus-memory" },
        panel("Yeni görev taslağı", h("div", null,
          h("p", { className: "nexus-muted" },
            "Kaydetmek görevi başlatmaz. Veri kapsamı, izin ve bütçe daha sonra belirlenir."),
          h("form", { className: "nexus-task-form", onSubmit: saveDraft },
            h("label", null, "Başlık",
              h("input", { required: true, maxLength: 160, value: draft.title,
                onChange: function (event) { editDraft("title", event.target.value); } })),
            h("label", null, "Amaç",
              h("textarea", { required: true, maxLength: 2000, value: draft.goal,
                onChange: function (event) { editDraft("goal", event.target.value); } })),
            h("label", null, "Beklenen çıktı",
              h("input", { required: true, maxLength: 1000, value: draft.expected_output,
                onChange: function (event) { editDraft("expected_output", event.target.value); } })),
            h("label", null, "Hedef uygulama (taslak)",
              h("select", { value: draft.target_app,
                onChange: function (event) { editDraft("target_app", event.target.value); } },
                ["Hermes", "NEXUS", "GitHub", "Diğer"].map(function (name) {
                  return h("option", { key: name, value: name }, name);
                }))),
            h("button", { type: "submit", disabled: savingTask ||
              !draft.title.trim() || !draft.goal.trim() || !draft.expected_output.trim() },
              savingTask ? "Kaydediliyor…" : "Taslak olarak kaydet")),
          taskError && h("p", { className: "nexus-error", role: "alert" }, taskError))),
        panel("Taslaklar", h("div", null,
          tasks && h("p", { className: "nexus-muted" }, tasks.total + " taslak; ilk " +
            taskItems.length + " gösteriliyor"),
          tasks && taskItems.length === 0 && h("p", null, "Henüz görev taslağı yok."),
          taskItems.map(function (item) {
            return h("div", { key: item.id, className: "nexus-task-row" },
              h("strong", null, item.title),
              h("span", { className: "nexus-muted" }, item.target_app + " · taslak · çalıştırılmadı"),
              h("span", null, item.expected_output));
          }))));
    } else if (tab === "models") {
      content = panel("Modeller ve kullanım", h("p", null,
        "OpenRouter bağlantısı, veri sınırları ve harcama kontrolü H4 aşamasında açılacak."));
    } else {
      const resultItems = results && results.items || [];
      const reviewItems = reviews && reviews.items || [];
      content = h("div", { className: "nexus-memory" },
        panel("Hafızada ara", h("div", null,
          h("form", { className: "nexus-search", onSubmit: runSearch },
            h("input", { type: "search", value: query, maxLength: 500,
              placeholder: "Bir konu veya karar ara", "aria-label": "Hafızada ara",
              onChange: function (event) { setQuery(event.target.value); } }),
            h("button", { type: "submit", disabled: searching || !query.trim() },
              searching ? "Aranıyor…" : "Ara")),
          searchError && h("p", { className: "nexus-error", role: "alert" }, searchError),
          results && h("p", { className: "nexus-muted" }, resultItems.length + " sonuç"),
          results && resultItems.length === 0 && h("p", null, "Eşleşen kayıt bulunamadı."),
          resultItems.map(function (item) {
            return h("button", { key: item.id, type: "button", className: "nexus-row",
              onClick: function () { openDetail("record", item.id); } },
              h("strong", null, item.title),
              h("span", { className: "nexus-muted" }, item.kind + " · " + item.status),
              h("span", null, item.snippet));
          }))),
        panel("Bekleyen incelemeler", h("div", null,
          reviewError && h("p", { className: "nexus-error", role: "alert" }, reviewError),
          reviews && h("p", { className: "nexus-muted" },
            reviews.total + " aday; ilk " + reviewItems.length + " gösteriliyor"),
          reviews && reviewItems.length === 0 && h("p", null, "Bekleyen aday yok."),
          reviewItems.map(function (item) {
            return h("button", { key: item.id, type: "button", className: "nexus-row",
              onClick: function () { openDetail("review", item.id); } },
              h("strong", null, item.preview),
              h("span", { className: "nexus-muted" }, item.kind + " · " + item.reason_codes.join(", ")));
          }))),
        (detail || detailError) && panel("Kayıt ayrıntısı", h("div", null,
          detailError && h("p", { className: "nexus-error", role: "alert" }, detailError),
          detail && h("div", null,
            h("h3", null, detail.title || detail.preview),
            h("p", null, detail.excerpt || detail.preview),
            detail.relative_path && h("p", { className: "nexus-muted" },
              "Obsidian: " + detail.relative_path),
            detail.canonical_verified && h("p", { className: "nexus-good" },
              "Kanonik kayıt ve indeks eşleşiyor."),
            detail.reason_codes && h("p", null, "İnceleme nedenleri: " + detail.reason_codes.join(", ")),
            (detail.source_refs || []).map(function (ref, index) {
              return h("div", { key: ref.source_id + index, className: "nexus-source" },
                h("strong", null, "Kaynak alıntısı"),
                h("p", null, ref.excerpt || "Alıntı yok"));
            }),
            h("p", { className: "nexus-muted" },
              "Özgün konuşma bu panelde ayrıca doğrulanmadı.")))));
    }

    return h("main", { className: "nexus-hub" },
      h("header", { className: "nexus-header" },
        h("div", null, h("p", { className: "nexus-eyebrow" }, "Yerel yönetim alanı"),
          h("h1", null, "NEXUS Hub")),
        h("span", { className: "nexus-badge" }, "H2 taslak · çalıştırma kapalı")),
      h("nav", { className: "nexus-tabs", "aria-label": "NEXUS bölümleri" },
        tabs.map(function (item) {
          return h("button", { key: item[0], type: "button",
            className: tab === item[0] ? "nexus-active" : "",
            "aria-current": tab === item[0] ? "page" : undefined,
            onClick: function () { setTab(item[0]); } }, item[1]);
        })),
      overviewError && h("p", { className: "nexus-error", role: "alert" }, overviewError),
      content);
  }

  window.__HERMES_PLUGINS__.register("nexus", HubPage);
})();
