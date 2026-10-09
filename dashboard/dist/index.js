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
    const [summaryText, setSummaryText] = useState("");
    const [summaryPreview, setSummaryPreview] = useState(null);
    const [summaryConsent, setSummaryConsent] = useState(false);
    const [summaryKey, setSummaryKey] = useState(newDraftKey);
    const [summaryLoading, setSummaryLoading] = useState(false);
    const [summaryResult, setSummaryResult] = useState(null);
    const [summaryError, setSummaryError] = useState("");
    const [operations, setOperations] = useState(null);
    const [operationsLoading, setOperationsLoading] = useState(false);
    const [operationsError, setOperationsError] = useState("");
    const [hermesAgents, setHermesAgents] = useState(null);
    const [agentsLoading, setAgentsLoading] = useState(false);
    const [agentsError, setAgentsError] = useState("");
    const [githubStatus, setGithubStatus] = useState(null);
    const [githubLoading, setGithubLoading] = useState(false);
    const [githubError, setGithubError] = useState("");
    const [savingTask, setSavingTask] = useState(false);
    const [draft, setDraft] = useState({ title: "", goal: "", expected_output: "",
      target_app: "Hermes", data_class: "undetermined", hermes_session_id: "" });
    const [draftKey, setDraftKey] = useState(newDraftKey);
    const [generationDrafts, setGenerationDrafts] = useState({});
    const [generationMatches, setGenerationMatches] = useState({});
    const [reconcilingId, setReconcilingId] = useState("");
    const [reconcileNote, setReconcileNote] = useState("");

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

    function loadGithubStatus() {
      if (githubLoading || !defaultTaskScope()) return;
      setGithubLoading(true); setGithubStatus(null); setGithubError("");
      SDK.fetchJSON(API + "/github-status?profile=default").then(function (data) {
        setGithubStatus(data);
      }).catch(function (error) { setGithubError(errorText(error));
      }).finally(function () { setGithubLoading(false); });
    }

    function loadHermesAgents() {
      if (agentsLoading || !defaultTaskScope()) return;
      setAgentsLoading(true); setAgentsError("");
      SDK.fetchJSON(API + "/hermes-agents?profile=default").then(function (data) {
        setHermesAgents(data);
      }).catch(function (error) {
        setHermesAgents(null); setAgentsError(errorText(error));
      }).finally(function () { setAgentsLoading(false); });
    }

    function runSummary() {
      if (pilotModel === "nvidia/nemotron-3-super-120b-a12b") {
        setSummaryError("Nemotron 3 Super seçildi. Resmi USD fiyatı doğrulanmadı; çağrı yok.");
        return;
      }
      if (summaryLoading || !summaryKey || !summaryConsent || !defaultTaskScope() ||
          !summaryPreview || summaryPreview !== summaryText || summaryText.length > 400) return;
      setSummaryLoading(true); setSummaryConsent(false); setSummaryResult(null); setSummaryError("");
      SDK.fetchJSON(API + "/selected-summary?profile=default", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: summaryKey, model: pilotModel,
          text: summaryPreview, external_authorized: true, non_sensitive: true })
      }).then(function (result) {
        setSummaryResult(result);
        if (result.cost_verified === true) setSummaryKey(newDraftKey());
      }).catch(function (error) {
        setSummaryError(errorText(error) + " Sonuç belirsiz olabilir; işlem durumlarını okuyun. Otomatik tekrar yok.");
      }).finally(function () { setSummaryLoading(false); });
    }

    function loadOperations() {
      if (operationsLoading || !defaultTaskScope()) return;
      setOperationsLoading(true); setOperations(null); setOperationsError("");
      SDK.fetchJSON(API + "/operation-status?profile=default").then(function (data) {
        setOperations(data);
      }).catch(function (error) { setOperationsError(errorText(error));
      }).finally(function () { setOperationsLoading(false); });
    }

    function confirmGenerationCost(item) {
      if (reconcilingId || !defaultTaskScope() || !item || typeof item.id !== "string") return;
      const body = { request_id: item.id };
      if (item.generation_id) {
        if (item.state === "running") return;
      } else if (item.state === "accepted" || item.state === "unknown") {
        const typed = generationDrafts[item.id];
        if (typeof typed !== "string" || !/^gen-[A-Za-z0-9_-]{8,80}$/.test(typed)) return;
        if (generationMatches[item.id] !== true) return;
        body.generation_id = typed;
        body.evidence_confirmed = true;
      } else {
        return;
      }
      setReconcilingId(item.id);
      setReconcileNote("");
      SDK.fetchJSON(API + "/generation-cost?profile=default", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      }).then(function (result) {
        if (result && result.confirmed_now === true && result.status === "settled") {
          setReconcileNote("Maliyet sağlayıcı kaydından doğrulandı.");
        } else if (result && result.confirmed_now === true) {
          setReconcileNote("Sağlayıcı ücreti doğrulandı; sıfır kabul edilmedi. Yeni iş durur.");
        } else if (result && result.cost_verified === true) {
          setReconcileNote("Bu deneme doğrulanamadı; önceki kayıt değiştirilmedi. Otomatik tekrar yok.");
        } else {
          setReconcileNote("Maliyet doğrulanamadı; kayıt belirsiz kaldı. Otomatik tekrar yok.");
        }
        setReconcilingId("");
        if (result && result.confirmed_now === true) loadOperations();
      }).catch(function () {
        setReconcileNote("Maliyet doğrulanamadı; kayıt belirsiz kaldı. Otomatik tekrar yok.");
        setReconcilingId("");
      });
    }

    function runFreePilot() {
      if (pilotModel === "nvidia/nemotron-3-super-120b-a12b") {
        setPilotError("Nemotron 3 Super seçildi. Resmi USD fiyatı doğrulanmadı; 0 USD sınırında çağrı yok.");
        return;
      }
      if (pilotLoading || !pilotKey || !defaultTaskScope()) return;
      setPilotLoading(true); setPilotResult(null); setPilotError("");
      SDK.fetchJSON(API + "/free-pilot?profile=default", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: pilotKey, model: pilotModel })
      }).then(function (result) {
        setPilotResult(result);
        if (result.cost_verified === true) setPilotKey(newDraftKey());
      }).catch(function (error) {
        setPilotError(errorText(error) + " Sonuç belirsiz olabilir; işlem durumlarını okuyun. Otomatik tekrar yok.");
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

    function stageSummary(text) {
      const clipped = String(text || "").trim().slice(0, 400);
      if (!clipped || summaryLoading) return;
      setTab("tasks");
      setSummaryText(clipped);
      setSummaryPreview(null);
      setSummaryConsent(false);
      setSummaryResult(null);
      setSummaryError("");
      setSummaryKey(newDraftKey());
    }

    function stageDraftFromSummary(output) {
      const text = String(output || "").trim().slice(0, 2000);
      if (!text || savingTask) return;
      setDraft({
        title: text.slice(0, 160),
        goal: text,
        expected_output: "Onaylı kısa özete dayalı taslak; çalıştırılmadı.",
        target_app: "NEXUS",
        data_class: "selected_external",
        hermes_session_id: "",
      });
      setDraftKey(newDraftKey());
      setTaskError("");
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
        panel("GitHub · NEXUS durumu", h("div", null,
          h("p", null, "Yalnız abidinyldz06/NEXUS: main commit'i, en son main koşusu ve en fazla 10 açık PR. Okuma düğmeyle yapılır; merge, push veya yorum yok."),
          h("button", { type: "button", onClick: loadGithubStatus,
            disabled: githubLoading || !defaultTaskScope() },
            githubLoading ? "GitHub okunuyor…" : "GitHub durumunu oku"),
          githubError && h("p", { role: "alert" }, githubError),
          githubStatus && !githubStatus.available && h("p", { role: "alert" }, githubStatus.reason),
          githubStatus && githubStatus.available && h("div", null,
            h("p", null, "Okuma: " + new Date(githubStatus.read_at).toLocaleString("tr-TR")),
            h("p", null, "Main: " + githubStatus.main),
            h("p", null, "Son main koşusu: " + githubStatus.main_run.status + " / " + (githubStatus.main_run.conclusion || "bilinmiyor")),
            h("p", { className: "nexus-muted" }, "Bu sonuç kurulu eklenti veya canlı sistem sürümünü doğrulamaz. Son koşu tüm workflow'ların kabulü değildir."),
            (githubStatus.items || []).length === 0 && h("p", null, "Açık PR bulunmadı."),
            (githubStatus.items || []).map(function (pr) {
              return h("div", { key: pr.number }, h("a", { href: "https://github.com/abidinyldz06/NEXUS/pull/" + pr.number }, "#" + pr.number + " " + pr.title),
                h("p", null, "Commit: " + pr.head + " · Kontroller: " + pr.checks));
            })))),
        panel("Hermes ajanları · mevcut profiller", h("div", null,
          h("p", null, "Bot oluşturma ve yönetme Hermes'te kalır. NEXUS yalnız mevcut profilleri listeler; sohbet açmak görev veya mesaj başlatmaz."),
          h("p", { className: "nexus-muted" }, "Profilin bulunması çalıştığı veya erişiminin doğrulandığı anlamına gelmez. Hermes sohbetlerinin model/maliyet ayarları ayrıdır; NEXUS'un ücretsiz sınırı bu sohbetlere uygulanmaz."),
          h("button", { type: "button", onClick: loadHermesAgents,
            disabled: agentsLoading || !defaultTaskScope() },
            agentsLoading ? "Profiller okunuyor…" : "Mevcut Hermes ajanlarını göster"),
          !defaultTaskScope() && h("p", null, "Profil listesi yalnız default profilde okunur."),
          agentsError && h("p", { role: "alert", className: "nexus-error" }, agentsError),
          hermesAgents && !hermesAgents.available && h("p", null, hermesAgents.reason),
          hermesAgents && hermesAgents.available && (hermesAgents.items || []).map(function (agent) {
            const knownProfiles = ["default", "writer-agent", "research-agent", "coder-agent", "scheduler-agent", "control-room"];
            const safeLink = agent.present === true && knownProfiles.includes(agent.profile);
            return h("div", { key: agent.profile }, h("h3", null, agent.name),
              h("p", null, agent.role + " · " + (agent.present ? "Profil mevcut" : "Kurulu profil bulunmadı")),
              safeLink && h("a", { href: "/chat?profile=" + agent.profile }, "Hermes sohbetini aç"));
          }))),
        (overview && overview.apps || []).map(function (app) {
          return panel(app.name, h("p", null, app.status), "nexus-app", app.name);
        }),
        !overview && panel("Bağlantılar", h("p", null, "Bağlantı durumları yükleniyor.")));
    } else if (tab === "tasks") {
      const taskItems = tasks && tasks.items || [];
      content = !defaultTaskScope() ? panel("Görev masası", h("p", null,
        "Görev taslakları yalnız default profilde kullanılabilir; profil seçimini değiştirin.")) :
        h("div", { className: "nexus-memory" },
        panel("İşlem sonucu ve kesinti durumu", h("div", null,
          h("p", null, "Görev taslakları başlamadı. Aşağıdaki liste yalnız açıkça başlatılan ücretsiz test/özet işlemlerinin içeriksiz kayıtlarıdır; Hermes görevlerinin yürütme kaydı değildir."),
          h("p", null, "Ağ kesilirse veya sayfa yenilenirse sonuç belirsiz olabilir. Durumu okuyun; bu düğme modeli tekrar çağırmaz. Eski maliyet kaydı tek başına başarılı sonuç değildir."),
          h("p", null, "Maliyet doğrulama ayrı bir düğmedir. Modeli yeniden çağırmaz. Kimliği olmayan veya doğrulanamayan kayıt sıfır sayılmaz."),
          h("button", { type: "button", onClick: loadOperations, disabled: operationsLoading },
            operationsLoading ? "İşlemler okunuyor…" : "İşlem durumlarını oku"),
          operationsError && h("p", { role: "alert" }, operationsError),
          reconcileNote && h("p", { role: "status" }, reconcileNote),
          operations && h("p", { role: "status" }, operations.total + " işlem · " +
            (operations.blocked ? "Yeni model işlemi durduruldu: uzlaştırılmamış kayıt var." : "Uzlaştırılmamış bütçe kaydı yok; bu çalıştırma izni değildir.")),
          operations && (operations.items || []).map(function (item) {
            const labels = { running: "Çalışıyor (bu süreçte gözlendi)", draft_result: "Taslak sonuç doğrulandı", failed: "Model çağrısı başlamadan hata", accepted: "Maliyet doğrulanmadı; yeni iş durur", unknown: "Sonuç belirsiz" };
            return h("div", { key: item.id, className: "nexus-task-row" },
              h("p", null, item.id + " · " + (labels[item.state] || "Sonuç belirsiz")),
              h("p", null, "Maliyet: " + (item.cost_verified ? "doğrulandı" : "belirsiz") + " · Kayıt: " + (item.updated_at || item.day)),
              h("p", null, "HTTP: " + (Number.isInteger(item.http_status) && item.http_status >= 100 && item.http_status <= 599 ? String(item.http_status) : "bilinmiyor")
                + " · Sınıf: " + ({ http_rejected: "HTTP reddi", timeout: "Ağ zaman aşımı", invalid_output: "Çıktı doğrulanamadı", invalid_response: "Yanıt doğrulanamadı", unverified_cost: "Maliyet doğrulanamadı", verified_zero: "Doğrulanmış sıfır maliyet" }[item.error_class] || "bilinmiyor")),
              typeof item.requested_model === "string" && /^[A-Za-z0-9_.:/+-]{1,200}$/.test(item.requested_model) && h("p", null, "İstenen model: " + item.requested_model),
              item.generation_id && h("p", null, "Sağlayıcı kimliği: " + item.generation_id),
              item.generation_id && item.state !== "running" && h("button", {
                type: "button",
                onClick: function () { confirmGenerationCost(item); },
                disabled: reconcilingId === item.id
              }, reconcilingId === item.id ? "Maliyet okunuyor…" : "Maliyeti doğrula"),
              (item.state === "accepted" || item.state === "unknown") && !item.generation_id && h("input", {
                name: "generation-evidence",
                value: generationDrafts[item.id] || "",
                maxLength: 84,
                onChange: function (event) {
                  const next = Object.assign({}, generationDrafts);
                  next[item.id] = event.target.value;
                  setGenerationDrafts(next);
                  setGenerationMatches(Object.assign({}, generationMatches, { [item.id]: false }));
                }
              }),
              (item.state === "accepted" || item.state === "unknown") && !item.generation_id && h("label", null,
                h("input", { type: "checkbox", name: "generation-match-confirmed",
                  checked: generationMatches[item.id] === true,
                  onChange: function (event) {
                    setGenerationMatches(Object.assign({}, generationMatches, { [item.id]: event.target.checked === true }));
                  } }),
                "OpenRouter Activity kaydındaki kimliğin bu NEXUS işlemiyle eşleştiğini doğruladım; yalnız zaman yakınlığı yeterli değildir."),
              (item.state === "accepted" || item.state === "unknown") && !item.generation_id && h("button", {
                type: "button",
                onClick: function () { confirmGenerationCost(item); },
                disabled: reconcilingId === item.id || generationMatches[item.id] !== true
              }, "Sağlayıcı kanıtıyla uzlaştır"),
              !item.generation_id && !item.cost_verified && item.state !== "accepted" && h("p", { className: "nexus-muted" },
                "Generation kimliği yok; kayıt belirsiz kalır."),
              h("p", { className: "nexus-muted" }, "Metin/yanıt saklanmadı; sonuç geri getirilemez. Otomatik tekrar yok."));
          }))),
        panel("Ücretsiz model bağlantı testi", h("div", null,
          h("p", null, "Yalnız sabit sentetik test metni gönderilir; Vault, notlar veya taslaklar gönderilmez. Harcama sınırı 0 USD; otomatik tekrar ve başka modele geçiş yok."),
          h("label", null, "Test modeli",
            h("select", { value: pilotModel, disabled: pilotLoading || summaryLoading,
              onChange: function (event) {
                setPilotModel(event.target.value);
                setSummaryPreview(null); setSummaryConsent(false);
                setSummaryResult(null); setSummaryError("");
              } },
              [["stealth/space-bunny-alpha", "Space Bunny Alpha"],
                ["nvidia/nemotron-3-ultra-550b-a55b:free", "Nemotron 3 Ultra (free)"],
                ["poolside/laguna-s-2.1:free", "Laguna S 2.1 (free)"],
                ["dots-studio/dots-3-note-preview:free", "Dots3-Note Preview (free)"],
                ["nvidia/nemotron-3.5-lightning:free", "Nemotron 3.5 Lightning (free)"],
                ["nvidia/nemotron-3-super-120b-a12b", "Nemotron 3 Super (NVIDIA NIM, ücret doğrulanmadı)"]].map(function (row) {
                return h("option", { key: row[0], value: row[0] }, row[1]);
              }))),
          h("p", { className: "nexus-muted" }, "Space Bunny sağlayıcısında içerik saklama uyarısı vardır. Veri koruması kapatılmaz; uygun ücretsiz rota yoksa durur."),
          pilotModel === "nvidia/nemotron-3-super-120b-a12b" && h("p", { className: "nexus-muted" },
            "Bu seçim NVIDIA NIM uç noktasıdır. Katalog sıfır fiyat gösterse bile NVIDIA faturası doğrulanmadan çağrı yapılmaz."),
          h("button", { type: "button", onClick: runFreePilot,
            disabled: pilotLoading || !pilotKey || !defaultTaskScope() ||
              pilotModel === "nvidia/nemotron-3-super-120b-a12b" ||
              (pilotResult && pilotResult.hold_status === "unknown") },
            pilotLoading ? "Test çalışıyor…" : "Sentetik ücretsiz testi çalıştır"),
          pilotError && h("p", { className: "nexus-error", role: "alert" }, pilotError),
          pilotResult && h("p", { role: "status" },
            pilotResult.status === "completed" && pilotResult.expected_output === true ?
              "Bağlantı testi başarılı · doğrulanmış maliyet 0 USD · " + pilotResult.elapsed_seconds + " saniye" :
              "Test kabul edilmedi veya daha önce kaydedildi; otomatik tekrar yok. Durum: " + pilotResult.status))),
        panel("Seçili metin özeti", h("div", null,
          h("p", null, "Önizleme yereldir. Arama parçası buraya aktarılabilir; onaylayıp özetle düğmesine basınca yalnız aşağıdaki metin OpenRouter'a gönderilir. Vault okunmaz; metin ve sonuç diske kaydedilmez."),
          h("label", null, "Özetlenecek metin (en fazla 400 karakter)",
            h("textarea", { value: summaryText, maxLength: 400, disabled: summaryLoading,
              onChange: function (event) {
                setSummaryText(event.target.value); setSummaryPreview(null); setSummaryConsent(false);
                setSummaryResult(null); setSummaryError(""); setSummaryKey(newDraftKey());
              } })),
          h("p", { className: "nexus-muted" }, "API anahtarı, kişisel veya hassas bilgi eklemeyin. Otomatik hassas veri tespiti yapılmaz."),
          h("button", { type: "button", disabled: summaryLoading || !summaryText.trim() || summaryText.length > 400,
            onClick: function () {
              if (!summaryText.trim() || summaryText.length > 400) return;
              setSummaryPreview(summaryText); setSummaryConsent(false);
            } }, "Gönderim önizlemesini göster"),
          summaryPreview && h("div", { role: "status" },
            h("p", null, "Hedef: OpenRouter / " + pilotModel + " · güncel sıfır fiyat çağrı öncesinde doğrulanır · harcama sınırı 0 USD. Sağlayıcı içerik saklayabilir; hassas metin göndermeyin."),
            h("p", null, "Yalnız aşağıdaki metin kullanılacak; başka dosya, not veya görev eklenmeyecek."),
            h("pre", null, summaryPreview),
            h("label", null, h("input", { type: "checkbox", checked: summaryConsent,
              disabled: summaryLoading,
              onChange: function (event) { setSummaryConsent(event.target.checked); } }),
              "Bu metinden hassas bilgileri çıkardım; bu işlem için OpenRouter'a gönderilmesini onaylıyorum."),
            pilotModel === "nvidia/nemotron-3-super-120b-a12b" && h("p", { className: "nexus-muted" },
              "Özet modeli Nemotron 3 Super. Fiyat doğrulanmadan metin gönderilmez."),
            h("button", { type: "button", onClick: runSummary,
              disabled: summaryLoading || !summaryConsent || !summaryKey ||
                pilotModel === "nvidia/nemotron-3-super-120b-a12b" ||
                (summaryResult && summaryResult.hold_status === "unknown") },
              summaryLoading ? "Özet hazırlanıyor…" : "Onayladığım metni ücretsiz özetle")),
          summaryError && h("p", { className: "nexus-error", role: "alert" }, summaryError),
          summaryResult && h("div", { role: "status" },
            summaryResult.status === "completed" && summaryResult.cost_verified === true ?
              h("div", null, h("p", null, "Taslak özet · doğrulanmış maliyet 0 USD. Doğruluğunu kontrol edin."),
                h("pre", null, summaryResult.output),
                h("button", { type: "button", onClick: function () {
                  stageDraftFromSummary(summaryResult.output);
                } }, "Bunu görev taslağına yaz"),
                h("p", { className: "nexus-muted" },
                  "Taslak alanları dolar; kayıt ve çalıştırma ayrı düğmelerdedir.")) :
              h("p", null, "Sonuç doğrulanamadı veya daha önce kaydedildi; otomatik tekrar yok. Durum: " +
                summaryResult.status +
                (Number.isInteger(summaryResult.http_status) ? " · HTTP " + summaryResult.http_status : "") +
                (summaryResult.reason ? " · " + summaryResult.reason : "") +
                (summaryResult.hold_status === "unknown"
                  ? " Yeni model işlemi durduruldu: uzlaştırılmamış kayıt var." : ""))))),
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
            const snippet = typeof item.snippet === "string" ? item.snippet.trim() : "";
            return h("div", { key: item.id, className: "nexus-hit" },
              h("button", { type: "button", className: "nexus-row",
                onClick: function () { openDetail("record", item.id); } },
                h("strong", null, item.title),
                h("span", { className: "nexus-muted" }, item.kind + " · " + item.status),
                h("span", null, item.snippet)),
              h("button", { type: "button", disabled: !snippet || summaryLoading,
                onClick: function () { stageSummary(snippet); } },
                "Özete aktar"));
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
            detail.excerpt && h("button", { type: "button", disabled: summaryLoading,
              onClick: function () { stageSummary(detail.excerpt); } },
              "Bu alıntıyı özete aktar"),
            h("p", { className: "nexus-muted" },
              "Özgün konuşma bu panelde ayrıca doğrulanmadı. Aktarma model çağırmaz.")))));
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
