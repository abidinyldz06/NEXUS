# NEXUS

NEXUS, ATLAS kişisel asistanının local-first hafıza altyapısıdır. v0.1 kapsamı
yalnız güvenilir ingestion, provenance, review, Obsidian canonical records,
rebuild edilebilir SQLite indeks ve commitments hatırlatmalarını kapsar.

## Güncel durum

Phase 7 ile Phase 8 retention, permission-audit, synthetic restore-drill ve
synthetic external git-dir rollback dilimleri `main` dalına birleştirilmiş ve tam
merge commit'i aktif Hermes plugin'ine kurulmuştur. Mevcut
kod güvenli plugin/CLI iskeleti, source adapter'ları, idempotent source state,
deterministik segmenter,
provenance zorunlu structured extraction, exact-only entity resolver,
deterministik policy, tekrar oynatılabilir review kuyruğu ve atomik canonical
Vault writer, disposable SQLite FTS5 indeks ve local-only Pulse scanner içerir.
ChatGPT adapter güncel `chat.html` export biçimini script çalıştırmadan açar;
gerçek export dry-run'ı 208 konuşma ve 8.065 mesajı içerik yazdırmadan
doğrulamıştır. Gerçek konuşmalar üzerinde extraction/shadow kabulü ayrıca
tamamlanacaktır. Aktif kurulum merge commit'i
`03117b3730bb221f05678f3caf95b0adcddd9280` ile sabitlenmiş; 235 kurulu-kopya
testi, bytecode doğrulaması, Plugin Doctor,
local/no-agent reminder canary, retention dry-run ve salt-okunur production
permission audit, iki synthetic drill, yazmasız canonical forget ve approved
memory publish dry-run'ları ile doğrulanmıştır. Sistem
hâlâ:

Hermes official JSONL adapter'ı gerçek, tek-session ve `--redact` export ile
içerik yazdırmadan doğrulanmıştır. Export wrapper yalnız owner-only dizine yazar
ve alt süreci `umask 077` ile başlatıp çıktıyı descriptor üzerinden `0600`e
sıkılaştırır.

- canonical record auto-publish yapmaz; yalnız explicit local reminder komutu
  mevcut commitment'ın `notified_at` state'ini güncelleyebilir,
- retention komutundan Hermes config/cron/gateway dosyalarını değiştirmez;
  reminder canary ayrı olarak local/no-agent çalışır,
- yalnız açık `eval --shadow`, exact-source `ingest --shadow` veya SHA-onaylı
  `ingest --stage` komutlarında model çağrısı yapar,
- Telegram veya başka bir dış kanala notification göndermez.

Phase 8'in ilk iki dar parçası olarak retention dry-run ve permission audit aktif
kuruluma alınmıştır. Retention komutu raw/quarantine dosyaları ile süresi dolmuş
rejected candidate'ları yalnız toplu sayılarla raporlar; audit komutu private data
ve Inbox metadata'sını kontrol eder. İki komut da içerik/yol/ID göstermez ve silme,
yeniden yazma veya izin değiştirme yapmaz.

Üçüncü Phase 8 dilimi yalnız sentetik verilerle çalışan geçici restore drill'i
ekler. Drill kullanıcı config'ini ve production yollarını okumaz; canonical hash,
derived-index, private permission ve cleanup eşliğini doğrular.

Dördüncü Phase 8 dilimi altı sentetik dosyayla external git-dir rollback drill'i
ekler. Git metadata geçici worktree dışında tutulur; kullanıcı ve sistem Git
config/template/hook kaynakları yüklenmez. Bu dilim kurulu kopyada kabul
edilmiştir; production Vault için Git geçmişi oluşturmaz.

Beşinci Phase 8 dilimi tek canonical kayıt için hedefe özel forget workflow'u
ekler. Dry-run bağımlılık etkisini yazmadan gösterir; apply ancak hedef ID ikinci
kez birebir doğrulanırsa ve başka canonical kayıt hedefe bağlı değilse çalışır.
Silme, generated memory view ve disposable SQLite indeks birlikte güncellenir;
hata durumunda önceki byte'lar geri yüklenir. Workflow kurulu kopyada sentetik
testlerle kabul edilmiştir; production canonical kayıt silinmemiştir.

Altıncı dar dilim, onaylanmış veya düzenlenmiş bir `memory` review adayını
canonical Vault'a taşımak için açık publish workflow'u ekler. Dry-run yazmaz;
apply aynı review ID'nin birebir doğrulanmasını ister, deterministik record ID
kullanır, source reference'ları korur, Current-Memory view'i ve derived indeksi
yeniler ve private publication audit'i ekler. Bu komut otomatik yayın değildir;
production apply ayrıca hedefe özel operasyon onayı gerektirir.

Yedinci dar dilim aynı explicit dry-run/exact-ID apply kapısını onaylanmış veya
düzenlenmiş `commitment` adaylarına genişletir. Staging actor kimliğini boş ve
`notify=false` bırakır; operatör mevcut kapalı alanları edit ederek actor/target
entity ID'lerini ve tarihi doğrulamadıkça publication planı çalışmaz. Başarılı
apply canonical commitment'ı ve reminder indeksini günceller, Current-Memory
view'ine dokunmaz ve otomatik yayın açmaz.

Sekizinci dar dilim `entity` adayını kapalı bir insan-tamamlama şekline alır.
Staging yalnız tek açık mention varsa adı normalize eder; entity türünü boş
bırakır. Yayın exact review-ID onayı, insanın seçtiği tür ve ad-normalizasyon
eşitliği ister; aynı türde mevcut exact ad/alias veya linked-note çakışmasını
yeni duplicate oluşturmadan reddeder. Apply canonical entity'yi ve derived indeksi günceller,
Current-Memory view'ine dokunmaz.

Dokuzuncu dar dilim `relation` adayını kapalı bir insan-tamamlama şekline alır.
Staging kaynak/hedef entity kimliklerini ve predicate'i boş bırakır. Yayın yalnız
mevcut canonical entity uçlarını, dar predicate allowlist'ini ve exact review-ID
onayını kabul eder; literal hedef yalnız `has_role` için kullanılabilir. Aynı
aktif ilişki yeniden oluşturulmaz; apply derived indeksi günceller ve
Current-Memory view'ine dokunmaz.

Onuncu dar dilim `correction` adayını kapalı bir insan-tamamlama şekline alır.
Staging hedef memory kimliğini ve yeni memory türünü boş bırakır; modelin olası
hedefleri yalnız extractor kanıtı olarak kalır. Yayın yalnız insanın seçtiği tek
aktif memory'yi supersede eder, eski ve yeni karşılıklı bağlantıları ile
Current-Memory view'ini tek Vault işleminde günceller ve exact review-ID onayı
olmadan yazmaz.

Güncel 12-vakalı frozen holdout, aktif `ollama-cloud` / `glm-5.3-flash` rotasında
prompt v2 ile shadow kabul kapısını geçmiştir: recall `%100`, precision `%90`,
exact-case `%91,67`, empty-case precision ve provenance `%100`, schema failure
`0`. Bu sentetik contract kanıtıdır; private golden-dataset kabulü veya
auto-publish yetkisi değildir.

Aktif kurulum ayrıca owner-only `data_path/eval/private/` altında basename ve
exact SHA-256 ile seçilen private golden fixture'ı aggregate-only shadow modunda
çalıştırabilir. İnsan etiketli gerçek fixture henüz sağlanmadığı için bu yolun
model-kalite kabul koşusu yapılmamıştır.

Phase 4 review kararları yalnız Vault dışındaki private data dizininde `0600`
append-only JSONL olayları olarak saklanır. Approve/edit kararı tek başına
canonical kayıt yayınlamaz; yayın ayrıca açık dry-run/apply komutu, exact review
ID doğrulaması ve production için hedefe özel operasyon onayı gerektirir.

Phase 5 writer yalnız immutable ID tabanlı sabit `Nexus/` yolları üretir;
create/update precondition, symlink containment, rollback ve run audit uygular.
Writer kütüphanesinin hazır olması production auto-publish yetkisi vermez.
Aktif config'te `auto_publish_enabled: false` kalır; canonical mutation yalnız
açık publish/forget veya reminder-state komutlarının dar güvenlik kapılarındadır.

Phase 6 `rebuild` komutu canonical Markdown kayıtlarını salt okunur tarar ve
Vault dışındaki SQLite indeksini yan dosyada tamamen kurduktan sonra atomik
olarak değiştirir. `search` FTS ifadesi çalıştırmaz; kullanıcı sorgusunu literal
terimlere çevirip tüm filtreleri parametreli SQL ile uygular.

Phase 7 reminder scanner yalnız onaylı, açık, tarihi kesin ve `notify=true`
commitment'ları işler. `notified_at` canonical kayda content-hash precondition ile
yazılır; indeks yenileme başarısızsa exact canonical byte'lar geri yüklenir.
No-agent wrapper boş stdout'ta sessizdir. Günlük 09:00 `Europe/Istanbul`
local/no-agent cron canary'si aktiftir; Telegram teslimi henüz etkin değildir.

Makinece okunabilir v1 kayıt contract'ı
[`schemas/nexus-v1.schema.json`](schemas/nexus-v1.schema.json) dosyasındadır.

Ayrıntılı kapsam: [NEXUS_V0_1_TEKNIK_PLAN.md](NEXUS_V0_1_TEKNIK_PLAN.md).

## Mimari sınır

- Kaynak repo: bu repository
- Aktif Hermes: vendor/runtime; core patch yapılmaz
- Entegrasyon: standalone Hermes plugin + CLI + mevcut cron/gateway
- Canonical memory: mevcut Obsidian Vault altında gelecekte oluşturulacak `Nexus/`
- Private raw/state: Vault dışında local dizin
- SQLite: yalnız derived index/state/cache

## Güvenli doğrulama

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q __init__.py nexus tests
hermes plugins doctor . --ci
```

`hermes plugins doctor` plugin'i geçici ve izole bir `HERMES_HOME` ile yükler;
aktif kullanıcı config'ini veya Vault'u değiştirmez.

Phase kanıtları: [`docs/phase-0-1-status.md`](docs/phase-0-1-status.md) ve
[`docs/phase-2-status.md`](docs/phase-2-status.md),
[`docs/phase-3-status.md`](docs/phase-3-status.md) ve
[`docs/phase-4-status.md`](docs/phase-4-status.md),
[`docs/phase-5-status.md`](docs/phase-5-status.md) ve
[`docs/phase-6-status.md`](docs/phase-6-status.md),
[`docs/phase-7-status.md`](docs/phase-7-status.md) ve
[`docs/phase-8-status.md`](docs/phase-8-status.md).

## Mevcut CLI

Aktif kurulumda aşağıdaki güvenli komut yüzeyleri vardır:

```bash
hermes nexus status
hermes nexus config validate
hermes nexus ingest --dry-run
hermes nexus ingest --shadow --source FILE --confirm-sha SHA256 --conversation ID
hermes nexus ingest --stage --source FILE --confirm-sha SHA256 --conversation ID
hermes nexus eval --shadow
hermes nexus eval --shadow --private-dataset golden-v1.json --confirm-sha SHA256
hermes nexus review list
hermes nexus review show REV_ID
hermes nexus review approve REV_ID
hermes nexus review reject REV_ID
hermes nexus review edit REV_ID --candidate-file /absolute/path/candidate.json
hermes nexus review publish REV_ID --dry-run
hermes nexus review publish REV_ID --apply --confirm REV_ID
hermes nexus rebuild
hermes nexus route --shadow --text "…"
hermes nexus search "Türk kahvesi" --kind memory
hermes nexus reminders --emit-local
hermes nexus retention --dry-run
hermes nexus forget RECORD_ID --dry-run
hermes nexus forget RECORD_ID --apply --confirm RECORD_ID
hermes nexus audit permissions
hermes nexus drill restore --synthetic
hermes nexus drill git-rollback --synthetic
```

`ingest --shadow` tek bir exact Inbox kaynağını path ve SHA ile doğrular. Çok
konuşmalı export'ta exact `--conversation` ister, varsayılan 20 ve en fazla 100
segment sınırını model çağrısından önce uygular; yalnız aggregate tür/audit
sayıları basar ve raw/state/review/Vault yazmaz.
`ingest --stage` aynı exact-source ve segment sınırlarını kullanır. Tüm model
çağrıları başarıyla tamamlandıktan sonra kaynağı owner-only raw/quarantine
alanına içerik-adresli olarak alır, source lineage state'ini idempotent günceller
ve yalnız policy'nin review'a uygun bulduğu adayları private append-only review
kuyruğuna ekler. Tekrar çalıştırma review adayını çoğaltmaz; çıktı yalnız toplu
sayılar verir. Vault'a yazmaz, aday yayınlamaz; memory adayları insanın
`memory_type`, commitment adayları actor/target/tarih/notification, entity
adayları entity türü, relation adayları ise uç/predicate seçimini gerektirir.
`eval --shadow` varsayılan olarak paketlenmiş sentetik frozen holdout'u aktif
`nexus_extract` model yoluna gönderir. `--private-dataset` ise yalnız
`data_path/eval/private/` altındaki SHA-onaylı JSON basename'ini kabul eder.
İki mod da aday içeriği yazmaz veya yayınlamaz ve yalnız kalite/audit ölçümlerini
ekrana verir. Private fixture hazırlama sözleşmesi
[`docs/private-golden-eval.md`](docs/private-golden-eval.md) içinde kayıtlıdır.
Review komutları yalnız private
olay kaydını değiştirir ve `vault_writes: false` raporlar. `rebuild` ve `search`
yalnız Vault dışındaki disposable indeksi değiştirir/okur. `route --shadow` tek
bir cümleyi sınıflandırır; yazmaz, yayınlamaz ve çalıştırmaz, kaynak metni
ekrana basmaz. Ingest mutation yalnız
exact-source `--stage` ile private raw/state/review alanıyla sınırlıdır; automatic
canonical record publish ve dış-kanal reminder teslimi kapalıdır. Reminder komutu
yalnız local output üretir ve işlenen canonical commitment'ın notification state'ini
güvenli biçimde günceller.

`retention --dry-run` yalnız aggregate expiry sayıları üretir. Apply/delete modu
yoktur; gerçek retention temizliği ayrı güvenlik kapısıdır.
`forget RECORD_ID --dry-run` hedef canonical kaydın türünü ve bağımlılık sayısını
yazmadan inceler. `--apply` yalnız aynı ID `--confirm` ile tekrar verildiğinde ve
bağımlılık sayısı sıfırken hedefi siler, memory view'i yeniler, indeksi rebuild eder
ve içeriksiz private audit olayı yazar. Bu kayıt-bazlı workflow raw/quarantine
dosyalarını veya subject-wide kişisel veri kopyalarını temizlemez.
`review publish REV_ID --dry-run` yalnız APPROVED/EDITED durumundaki `memory`,
`commitment`, `entity` veya `relation` adayını ve deterministik hedefini
doğrular. `--apply --confirm REV_ID` canonical kaydı ve derived indeksi günceller; yalnız memory
için generated view de yenilenir. Aynı içeriğin tekrarı
idempotent'tır. Canonical commit sonrasında private review audit yazımı geçici
olarak başarısız olursa komut hata verir; aynı apply komutunun tekrarı eksik audit'i
tamamlar ve canonical kaydı yeniden yazmaz.
`audit permissions` yalnız metadata ve toplu sorun sayılarını okur; dosya yolu,
isim veya içerik basmaz ve izinleri değiştirmez.
`drill restore --synthetic` yalnız sistem geçici dizininde sentetik kayıt, snapshot
ve iki derived indeks oluşturur; production yollarını okumadan hash/index eşliğini
doğrular ve geçici alanı komut bitmeden siler.
`drill git-rollback --synthetic` altı geçici dosyayı worktree dışındaki Git
metadata ile commit eder, kontrollü mutation'ı exact commit'e geri alır, hash ve
clean-worktree eşliğini doğrular ve tüm geçici alanı siler.

## Ingest Pipeline v2 geri alma

`ingest_pipeline_v2` varsayılanı kapalıdır (pilot). Bayrak kapatılınca komut
`1424c7f` shadow-only davranışa döner: 90 saniyelik `nexus_extract` hard timeout,
en fazla 3 deneme, checkpoint yazılmaz, Vault'a yazılmaz. Bayrağı kapatmak
checkpoint, ledger veya canonical kayıt silmez.
`hermes nexus ingest pause` canlı yazımı durdurur; gölge JSONL kalır.
`hermes nexus ingest unpause` pause bayrağını kaldırır; model çağırmaz.
`hermes nexus ingest rollback <ingest_id>` varsayılanı dry-run'dır; `--apply --confirm <id>`
eşleşen ledger satırlarını retracted yapar, varsa aynı id'li `Nexus/Memory` dosyalarını
tombstone eder ve derived index'i rebuild eder. Dry-run Vault'a dokunmaz.
`hermes nexus ingest status <ingest_id>` tek sorguda başarısızlık nedenini verir.
`hermes nexus ingest reprocess <ingest_id>` FAILED_SEGMENT satırlarını sonraki koşu için
hazırlar; model çağırmaz. `hermes nexus ingest queue` review kuyruğunu okur.
`--long-unit-budget` yalnız insan tetiklemelidir (default 300s, her kullanım loglanır).
`--canary-write --confirm canary` kabul edilen kayıtları `Nexus/` altına yazar; günde en fazla 25 ingest.
Auto-publish kapalı kalır. Dry-run ve `--shadow` (canary'siz) Vault'a dokunmaz.
Güncel A8 sonucu ve A8 açıkken insan denetimli kullanım sınırı:
[`docs/a8-limited-use-decision.md`](docs/a8-limited-use-decision.md).
v2 segmenter mesaj sınırında böler; karakter bütçesi 12.000 ve en fazla 12 mesaj,
böylece 54 mesajlık v1 tek-segment timeout sınıfı tek 90s çağrıda kalmaz.
Overlap varsayılanı kapalıdır; süreklilik önceki kabulün salt-okunur özetidir
(checkpoint'te tutulur, resume sonrası yeniden verilir).

Backup sınıflandırması ve restore güvenlik sınırı:
[`docs/backup-policy.md`](docs/backup-policy.md).
Canonical kayıt unutma güvenlik akışı:
[`docs/forget-workflow.md`](docs/forget-workflow.md).
Onaylı hafıza/entity/relation/commitment yayınlama güvenlik akışı:
[`docs/publication-workflow.md`](docs/publication-workflow.md).

Extraction servisi yalnız plugin-owned `nexus_extract` auxiliary task'ını kullanır;
provider/model override istemez ve adayları hiçbir yere yayınlamaz.
