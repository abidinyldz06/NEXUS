(function () {
  "use strict";

  const SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;
  const h = SDK.React.createElement;
  const { useEffect, useState } = SDK.hooks;
  const API = "/api/plugins/nexus/hub";
  const TASKS = API + "/tasks?profile=default";
  const tabs = [
    ["today", "Bugün"], ["apps", "Uygulamalar"], ["tasks", "Görevler"],
    ["memory", "Hafıza"], ["models", "Modeller ve kullanım"],
  ];
  const providerCatalog = [
    ["OpenRouter", "openrouter", "Model API · hesap bakiyesi burada okunmuyor"],
    ["Gemini API", "gemini", "Model API · Antigravity abonelik kotasından ayrı"],
    ["NVIDIA NIM", "nvidia", "Model API · inference anahtarı NGC anahtarından ayrı"],
    ["Antigravity", null, "Ajan uygulaması · uygulama kotası burada okunmuyor"],
  ];

  function providerConnection(rows, slug) {
    if (!slug) return "Hermes model sağlayıcısı değil; bağlantı durumu bilinmiyor.";
    const row = rows.find(function (item) {
      return item && item.slug === slug;
    });
    if (!row) return "Hermes'te açıkça tanımlı bağlantı bulunmadı.";
    return row.authenticated === true ?
      "Hermes'te yetkili görünüyor; canlı API testi yapılmadı." :
      "Hermes'te tanımlı, ancak yetki doğrulanmadı.";
  }

  function providerUsage(snapshot) {
    const groups = new Map();
    (snapshot && Array.isArray(snapshot.models) ? snapshot.models : []).forEach(function (row) {
      if (!row || typeof row !== "object") return;
      const name = typeof row.provider === "string" && row.provider.trim() ?
        row.provider.trim() : "Sağlayıcı atfı bilinmiyor";
      const entry = groups.get(name) || { name: name, models: 0, sessions: 0 };
      entry.models += 1;
      if (typeof row.sessions === "number" && Number.isFinite(row.sessions) && row.sessions >= 0) {
        entry.sessions += row.sessions;
      }
      groups.set(name, entry);
    });
    return Array.from(groups.values()).sort(function (a, b) { return b.sessions - a.sessions; });
  }

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

  function defaultTaskScope() {
    return new URLSearchParams(window.location.search).get("profile") === "default";
  }

  function dataClassLabel(value) {
    return { undetermined: "belirlenmedi", local_only: "yalnız yerel",
      selected_external: "seçili içerik dışarı çıkabilir",
      sensitive: "hassas; dışarı gönderilmez" }[value] || "bilinmiyor";
  }

  function newDraftKey() {
    if (!window.crypto || !window.crypto.getRandomValues) return "";
    const bytes = new Uint8Array(16);
    try {
      window.crypto.getRandomValues(bytes);
    } catch (_ignored) {
      return "";
    }
    bytes[6] = (bytes[6] & 15) | 64;
    bytes[8] = (bytes[8] & 63) | 128;
    const hex = Array.from(bytes, function (byte) {
      return byte.toString(16).padStart(2, "0");
    }).join("");
    return hex.slice(0, 8) + "-" + hex.slice(8, 12) + "-" + hex.slice(12, 16) +
      "-" + hex.slice(16, 20) + "-" + hex.slice(20);
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
    const [sessionStatus, setSessionStatus] = useState({});
    const [routeText, setRouteText] = useState("");
    const [routeDataClass, setRouteDataClass] = useState("undetermined");
    const [routeAdvice, setRouteAdvice] = useState(null);
    const [routeError, setRouteError] = useState("");
    const [routeLoading, setRouteLoading] = useState(false);
    const [modelUsage, setModelUsage] = useState(null);
    const [modelUsageError, setModelUsageError] = useState("");
    const [modelUsageLoading, setModelUsageLoading] = useState(false);
    const [providerConnections, setProviderConnections] = useState(null);
    const [providerConnectionError, setProviderConnectionError] = useState("");
    const [providerConnectionLoading, setProviderConnectionLoading] = useState(false);
    const [quotaSnapshots, setQuotaSnapshots] = useState({});
    const [quotaLoading, setQuotaLoading] = useState(false);
    const [quotaError, setQuotaError] = useState("");
    const [pilotModel, setPilotModel] = useState("stealth/space-bunny-alpha");
    const [pilotKey, setPilotKey] = useState(newDraftKey);
    const [pilotResult, setPilotResult] = useState(null);
    const [pilotError, setPilotError] = useState("");
    const [pilotLoading, setPilotLoading] = useState(false);
    const [savingTask, setSavingTask] = useState(false);
    const [draft, setDraft] = useState({ title: "", goal: "", expected_output: "",
      target_app: "Hermes", data_class: "undetermined", hermes_session_id: "" });
    const [draftKey, setDraftKey] = useState(newDraftKey);

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
      if (defaultTaskScope()) {
        SDK.fetchJSON(TASKS + "&limit=30").then(function (data) {
          if (active) setTasks(data);
        }).catch(function (error) {
          if (active) setTaskError(errorText(error));
        });
      }
      return function () { active = false; };
    }, []);

    function editDraft(field, value) {
      setDraft(function (current) {
        const update = { [field]: value };
        if (field === "target_app" && value !== "Hermes") update.hermes_session_id = "";
        return Object.assign({}, current, update);
      });
      setDraftKey(newDraftKey());
      setTaskError("");
    }

    function saveDraft(event) {
      event.preventDefault();
      if (!defaultTaskScope()) {
        setTaskError("Görev taslakları yalnız default profilde kullanılabilir.");
        return;
      }
      if (!draftKey) {
        setTaskError("Güvenli işlem kimliği üretilemedi; taslak kaydedilmedi.");
        return;
      }
      if (savingTask) return;
      setSavingTask(true);
      setTaskError("");
      SDK.fetchJSON(TASKS, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(Object.assign({ idempotency_key: draftKey }, draft)),
      }).then(function () {
        return SDK.fetchJSON(TASKS + "&limit=30");
      }).then(function (data) {
        setTasks(data);
        setDraft({ title: "", goal: "", expected_output: "",
          target_app: "Hermes", data_class: "undetermined", hermes_session_id: "" });
        setDraftKey(newDraftKey());
      }).catch(function (error) {
        setTaskError(errorText(error));
      }).finally(function () { setSavingTask(false); });
    }

    function suggestRoute(event) {
      event.preventDefault();
      if (routeLoading || !routeText.trim() || !defaultTaskScope()) return;
      setRouteLoading(true);
      setRouteAdvice(null);
      setRouteError("");
      SDK.fetchJSON(API + "/route-advice?profile=default", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_text: routeText, data_class: routeDataClass }),
      }).then(function (data) {
        if (!data || data.execution_enabled !== false || typeof data.reason !== "string") {
          throw new Error("geçersiz yönlendirme yanıtı");
        }
        setRouteAdvice(data);
      }).catch(function (error) { setRouteError(errorText(error)); })
        .finally(function () { setRouteLoading(false); });
    }

    function checkSession(item) {
      if (!defaultTaskScope()) {
        setTaskError("Hermes oturumu yalnız default profilde doğrulanabilir.");
        return;
      }
      setSessionStatus(function (current) {
        return Object.assign({}, current, { [item.id]: "Oturum kontrol ediliyor…" });
      });
      SDK.fetchJSON("/api/sessions/" + encodeURIComponent(item.hermes_session_id) +
        "?profile=default").then(function (session) {
        const message = session.id === item.hermes_session_id && session.profile === "default" ?
          (session.ended_at == null ? "Oturum kaydı mevcut · henüz açık" :
            "Oturum kaydı mevcut · sonlandı") + ". Görev sonucu doğrulanmadı." :
          "Oturum kimliği veya profili eşleşmedi.";
        setSessionStatus(function (current) {
          return Object.assign({}, current, { [item.id]: message });
        });
      }).catch(function () {
        setSessionStatus(function (current) {
          return Object.assign({}, current, { [item.id]: "Oturum doğrulanamadı; durum bilinmiyor." });
        });
      });
    }

    function loadModelUsage() {
      if (modelUsageLoading) return;
      if (!defaultTaskScope()) {
        setModelUsageError("Kullanım yalnız default profilde görüntülenebilir.");
        return;
      }
      setModelUsageLoading(true);
      setModelUsage(null);
      setModelUsageError("");
      SDK.fetchJSON("/api/analytics/models?days=30&profile=default").then(function (data) {
        if (!data || !Array.isArray(data.models) || data.period_days !== 30) {
          throw new Error("geçersiz kullanım yanıtı");
        }
        setModelUsage(data);
      }).catch(function () {
        setModelUsageError("Hermes kullanım verisi alınamadı; durum bilinmiyor.");
      }).finally(function () { setModelUsageLoading(false); });
    }

    function loadProviderConnections() {
      if (providerConnectionLoading) return;
      if (!defaultTaskScope()) {
        setProviderConnectionError("Bağlantı durumu yalnız default profilde görüntülenebilir.");
        return;
      }
      setProviderConnectionLoading(true);
      setProviderConnections(null);
      setProviderConnectionError("");
      SDK.fetchJSON("/api/model/options?profile=default&explicit_only=true").then(function (data) {
        if (!data || !Array.isArray(data.providers)) {
          throw new Error("geçersiz sağlayıcı yanıtı");
        }
        setProviderConnections(data.providers.map(function (row) {
          return { slug: row.slug, authenticated: row.authenticated === true };
        }));
      }).catch(function () {
        setProviderConnectionError("Hermes bağlantı durumu alınamadı; durum bilinmiyor.");
      }).finally(function () { setProviderConnectionLoading(false); });
    }

    function runFreePilot() {
      if (pilotLoading || !pilotKey || !defaultTaskScope()) return;
      setPilotLoading(true); setPilotResult(null); setPilotError("");
      SDK.fetchJSON(API + "/free-pilot?profile=default", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: pilotKey, model: pilotModel })
      }).then(function (result) {
        setPilotResult(result);
        if (result.cost_verified === true) setPilotKey(newDraftKey());
      }).catch(function (error) {
        setPilotError(errorText(error));
      }).finally(function () { setPilotLoading(false); });
    }

    function loadProviderQuota() {
      if (quotaLoading || !defaultTaskScope()) return;
      setQuotaLoading(true);
      setQuotaSnapshots({});
      setQuotaError("");
      Promise.all(providerCatalog.map(function (item) {
        const slug = item[1] || "antigravity";
        return SDK.fetchJSON(API + "/providers/" + slug + "/usage?profile=default", {
          method: "POST"
        }).then(function (data) {
          if (!data || data.provider !== slug || data.inference_called !== false) {
            throw new Error("geçersiz kullanım yanıtı");
          }
          return [slug, data];
        });
      })).then(function (rows) {
        setQuotaSnapshots(Object.fromEntries(rows));
      }).catch(function () {
        setQuotaError("Sağlayıcı kullanım bilgisi alınamadı; eski veri gösterilmiyor.");
      }).finally(function () { setQuotaLoading(false); });
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
      content = !defaultTaskScope() ? panel("Görev masası", h("p", null,
        "Görev taslakları yalnız default profilde kullanılabilir; profil seçimini değiştirin.")) :
        h("div", { className: "nexus-memory" },
        panel("Ücretsiz model bağlantı testi", h("div", null,
          h("p", null, "Yalnız sabit sentetik test metni gönderilir; Vault, notlar veya taslaklar gönderilmez. Harcama sınırı 0 USD; otomatik tekrar ve başka modele geçiş yok."),
          h("label", null, "Test modeli",
            h("select", { value: pilotModel, disabled: pilotLoading,
              onChange: function (event) { setPilotModel(event.target.value); } },
              [["stealth/space-bunny-alpha", "Space Bunny Alpha"],
                ["nvidia/nemotron-3-ultra-550b-a55b:free", "Nemotron 3 Ultra (free)"],
                ["poolside/laguna-s-2.1:free", "Laguna S 2.1 (free)"],
                ["dots-studio/dots-3-note-preview:free", "Dots3-Note Preview (free)"],
                ["nvidia/nemotron-3.5-lightning:free", "Nemotron 3.5 Lightning (free)"]].map(function (row) {
                return h("option", { key: row[0], value: row[0] }, row[1]);
              }))),
          h("p", { className: "nexus-muted" }, "Space Bunny sağlayıcısında içerik saklama uyarısı vardır. Veri koruması kapatılmaz; uygun ücretsiz rota yoksa durur."),
          h("button", { type: "button", onClick: runFreePilot,
            disabled: pilotLoading || !pilotKey || !defaultTaskScope() ||
              (pilotResult && pilotResult.hold_status === "unknown") },
            pilotLoading ? "Test çalışıyor…" : "Sentetik ücretsiz testi çalıştır"),
          pilotError && h("p", { className: "nexus-error", role: "alert" }, pilotError),
          pilotResult && h("p", { role: "status" },
            pilotResult.status === "completed" && pilotResult.expected_output === true ?
              "Bağlantı testi başarılı · doğrulanmış maliyet 0 USD · " + pilotResult.elapsed_seconds + " saniye" :
              "Test kabul edilmedi veya daha önce kaydedildi; otomatik tekrar yok. Durum: " + pilotResult.status))),
        panel("Nereye yönlendirelim? · yalnız öneri", h("div", null,
          h("p", { className: "nexus-muted" },
            "İstek bu cihazda kurallarla değerlendirilir. Model çağrısı, görev başlatma veya taslak kaydı yapılmaz."),
          h("form", { className: "nexus-task-form", onSubmit: suggestRoute },
            h("label", null, "Tek bir iş yazın",
              h("textarea", { required: true, maxLength: 500, value: routeText,
                disabled: routeLoading,
                onChange: function (event) {
                  setRouteText(event.target.value); setRouteAdvice(null);
                } })),
            h("label", null, "Veri kapsamı",
              h("select", { value: routeDataClass, disabled: routeLoading,
                onChange: function (event) {
                  setRouteDataClass(event.target.value); setRouteAdvice(null);
                } },
                [["undetermined", "Henüz belirlenmedi"], ["local_only", "Yalnız yerel"],
                  ["selected_external", "Seçili içerik dışarı çıkabilir"],
                  ["sensitive", "Hassas; dışarı gönderilmez"]].map(function (item) {
                  return h("option", { key: item[0], value: item[0] }, item[1]);
                }))),
            h("button", { type: "submit", disabled: routeLoading || !routeText.trim() },
              routeLoading ? "Değerlendiriliyor…" : "Yönlendirme öner")),
          routeError && h("p", { className: "nexus-error", role: "alert" }, routeError),
          routeAdvice && h("div", { className: "nexus-task-row", role: "status" },
            h("strong", null, routeAdvice.target_app || "Hedef belirsiz"),
            h("span", { className: "nexus-muted" },
              ({ suggested: "Yalnız öneri", requires_review: "İnsan incelemesi gerekli",
                needs_clarification: "İstek belirsiz" }[routeAdvice.status] || "Durum bilinmiyor")),
            h("span", null, routeAdvice.reason),
            h("span", { className: "nexus-muted" },
              "Model rolü: " + ({ none: "gerekmez", local_required: "yalnız yerel model gerekli",
                summarizer: "özetleme adayı", researcher: "araştırma adayı" }[routeAdvice.model_role] ||
                "belirlenmedi") + " · çalıştırma kapalı")))),
        panel("Yeni görev taslağı", h("div", null,
          h("p", { className: "nexus-muted" },
            "Yalnız default profiline kaydedilir; görev başlatmaz. Veri kapsamı, izin ve bütçe daha sonra belirlenir."),
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
            h("label", null, "Veri kapsamı (taslak)",
              h("select", { value: draft.data_class,
                onChange: function (event) { editDraft("data_class", event.target.value); } },
                [["undetermined", "Henüz belirlenmedi"], ["local_only", "Yalnız yerel"],
                  ["selected_external", "Seçili içerik dışarı çıkabilir"],
                  ["sensitive", "Hassas; dışarı gönderilmez"]].map(function (item) {
                    return h("option", { key: item[0], value: item[0] }, item[1]);
                  }))),
            draft.target_app === "Hermes" && h("label", null,
              "Mevcut Hermes oturum kimliği (isteğe bağlı)",
              h("input", { maxLength: 128, value: draft.hermes_session_id,
                placeholder: "Yalnız tam oturum kimliği; yeni iş başlatmaz",
                onChange: function (event) { editDraft("hermes_session_id", event.target.value); } })),
            h("button", { type: "submit", disabled: savingTask ||
              !draftKey || !draft.title.trim() || !draft.goal.trim() ||
              !draft.expected_output.trim() },
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
              h("span", { className: "nexus-muted" }, "Veri kapsamı: " + dataClassLabel(item.data_class)),
              h("span", null, item.expected_output),
              item.hermes_session_id && h("div", null,
                h("span", { className: "nexus-muted" },
                  "Hermes oturum referansı: " + item.hermes_session_id),
                h("button", { type: "button", onClick: function () { checkSession(item); } },
                  "Oturumu kontrol et"),
                h("p", { className: "nexus-muted" },
                  sessionStatus[item.id] || "Oturum henüz doğrulanmadı.")));
          }))));
    } else if (tab === "models") {
      const providerRows = providerUsage(modelUsage);
      content = h("div", { className: "nexus-memory" },
        panel("Sağlayıcı Merkezi", h("div", null,
          h("p", null, "OpenRouter tek seçenek değil. Bağlantılar Hermes veya ilgili uygulamada yönetilir; NEXUS anahtar saklamaz."),
          h("p", { className: "nexus-muted" },
            "Hermes bağlantı bilgisi hesap bakiyesi, kalan kota veya canlı erişim kanıtı değildir. Sayfa açılırken sorgulanmaz."),
          h("button", { type: "button", onClick: loadProviderConnections,
            disabled: providerConnectionLoading || !defaultTaskScope() },
            providerConnectionLoading ? "Kontrol ediliyor…" : "Hermes bağlantılarını kontrol et"),
          providerConnectionError && h("p", { className: "nexus-error", role: "alert" },
            providerConnectionError),
          h("p", { className: "nexus-muted" },
            "Kullanım sorgusu yalnız düğmeye basınca yapılır; modele içerik göndermez. Bilinmeyen limit sıfır veya sınırsız sayılmaz."),
          h("button", { type: "button", onClick: loadProviderQuota,
            disabled: quotaLoading || !defaultTaskScope() },
            quotaLoading ? "Okunuyor…" : "Sağlayıcı kullanım/limit bilgisini oku"),
          quotaError && h("p", { className: "nexus-error", role: "alert" }, quotaError))),
        h("div", { className: "nexus-grid" }, providerCatalog.map(function (item) {
          const snapshot = quotaSnapshots[item[1] || "antigravity"];
          const labels = { usage: "Toplam kullanım", usage_daily: "Günlük kullanım",
            usage_weekly: "Haftalık kullanım", usage_monthly: "Aylık kullanım",
            limit: "Anahtar limiti", limit_remaining: "Anahtar limitinden kalan" };
          return panel(item[0], h("div", null,
            h("p", { className: "nexus-muted" }, item[2]),
            h("p", null, providerConnections ?
              providerConnection(providerConnections, item[1]) : "Bağlantı durumu kontrol edilmedi."),
            h("p", null, snapshot ? snapshot.reason : "Kullanım/limit henüz okunmadı."),
            snapshot && snapshot.checked_at && h("p", { className: "nexus-muted" },
              "Sağlayıcıdan okuma: " + new Date(snapshot.checked_at).toLocaleString("tr-TR")),
            snapshot && snapshot.metrics && Object.keys(labels).map(function (field) {
              const value = snapshot.metrics[field];
              return h("p", { key: field }, labels[field] + ": " +
                (typeof value === "number" && Number.isFinite(value) ?
                  value.toLocaleString("tr-TR", { maximumFractionDigits: 6 }) + " USD" : "Bilinmiyor"));
            })),
            "nexus-app", item[0]);
        })),
        panel("Hermes model-oturum kayıtları · son 30 gün", h("div", null,
          h("p", { className: "nexus-muted" },
            "Yalnız Hermes'in default profilindeki model-oturum kayıtlarıdır; tek bir oturum birden çok modelde sayılabilir. Token, API çağrısı ve maliyet tahminleri eksik olabileceğinden burada gösterilmez; sağlayıcı faturası veya kalan kota değildir. Sayfa açılırken sorgulanmaz."),
          !defaultTaskScope() && h("p", { className: "nexus-muted" },
            "Kullanımı görmek için default profiline geçin."),
          h("button", { type: "button", onClick: loadModelUsage,
            disabled: modelUsageLoading || !defaultTaskScope() },
            modelUsageLoading ? "Getiriliyor…" : "Oturumları getir"),
          modelUsageError && h("p", { className: "nexus-error", role: "alert" }, modelUsageError),
          modelUsage && providerRows.length === 0 && h("p", null,
            "Bu dönemde Hermes model oturumu kaydedilmemiş."),
          providerRows.map(function (row) {
            return h("div", { key: row.name, className: "nexus-task-row" },
              h("strong", null, row.name),
              h("span", null, row.models + " model kaydı · " +
                row.sessions.toLocaleString("tr-TR") + " model-oturum kaydı"));
          }))));
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
