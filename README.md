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
ChatGPT adapter gerçek
export doğrulanana kadar experimental'dır. Aktif kurulum merge commit'i
`74ebf71ea5f065c6b133543b5440cf88d847af83` ile sabitlenmiş; Plugin Doctor,
local/no-agent reminder canary, retention dry-run ve salt-okunur production
permission audit ile iki synthetic drill kullanılarak doğrulanmıştır. Sistem
hâlâ:

- canonical record auto-publish yapmaz; yalnız explicit local reminder komutu
  mevcut commitment'ın `notified_at` state'ini güncelleyebilir,
- retention komutundan Hermes config/cron/gateway dosyalarını değiştirmez;
  reminder canary ayrı olarak local/no-agent çalışır,
- yalnız açık `eval --shadow` komutunda paketlenmiş sentetik fixture ile model çağrısı yapar,
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
hata durumunda önceki byte'lar geri yüklenir.

Paketlenmiş iki-vakalı frozen holdout, aktif `ollama-cloud` / `glm-5.3` rotasında
shadow modda başarıyla çalışmıştır. Bu sonuç Phase 3 contract kapısını doğrular;
geniş model-kalitesi kanıtı veya auto-publish yetkisi değildir.

Phase 4 review kararları yalnız Vault dışındaki private data dizininde `0600`
append-only JSONL olayları olarak saklanır. Approve/edit kararı canonical kayıt
yayınlamaz; production canary ve ayrı publish yetkisi verilene kadar kapalıdır.

Phase 5 writer yalnız immutable ID tabanlı sabit `Nexus/` yolları üretir;
create/update precondition, symlink containment, rollback ve run audit uygular.
Writer kütüphanesinin hazır olması production auto-publish yetkisi vermez:
aktif config'te `write_enabled: false` ve `auto_publish_enabled: false` kalır.

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
hermes nexus eval --shadow
hermes nexus review list
hermes nexus review show REV_ID
hermes nexus review approve REV_ID
hermes nexus review reject REV_ID
hermes nexus review edit REV_ID --candidate-file /absolute/path/candidate.json
hermes nexus rebuild
hermes nexus search "Türk kahvesi" --kind memory
hermes nexus reminders --emit-local
hermes nexus retention --dry-run
hermes nexus forget RECORD_ID --dry-run
hermes nexus forget RECORD_ID --apply --confirm RECORD_ID
hermes nexus audit permissions
hermes nexus drill restore --synthetic
hermes nexus drill git-rollback --synthetic
```

`eval --shadow` yalnız paketlenmiş sentetik frozen holdout'u aktif
`nexus_extract` model yoluna gönderir; aday içeriği yazmaz veya yayınlamaz ve
yalnız kalite/audit ölçümlerini ekrana verir. Review komutları yalnız private
olay kaydını değiştirir ve `vault_writes: false` raporlar. `rebuild` ve `search`
yalnız Vault dışındaki disposable indeksi değiştirir/okur. Mutating ingest,
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
`audit permissions` yalnız metadata ve toplu sorun sayılarını okur; dosya yolu,
isim veya içerik basmaz ve izinleri değiştirmez.
`drill restore --synthetic` yalnız sistem geçici dizininde sentetik kayıt, snapshot
ve iki derived indeks oluşturur; production yollarını okumadan hash/index eşliğini
doğrular ve geçici alanı komut bitmeden siler.
`drill git-rollback --synthetic` altı geçici dosyayı worktree dışındaki Git
metadata ile commit eder, kontrollü mutation'ı exact commit'e geri alır, hash ve
clean-worktree eşliğini doğrular ve tüm geçici alanı siler.

Backup sınıflandırması ve restore güvenlik sınırı:
[`docs/backup-policy.md`](docs/backup-policy.md).
Canonical kayıt unutma güvenlik akışı:
[`docs/forget-workflow.md`](docs/forget-workflow.md).

Extraction servisi yalnız plugin-owned `nexus_extract` auxiliary task'ını kullanır;
provider/model override istemez ve adayları hiçbir yere yayınlamaz.
