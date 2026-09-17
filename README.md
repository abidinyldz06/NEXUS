# NEXUS

NEXUS, ATLAS kişisel asistanının local-first hafıza altyapısıdır. v0.1 kapsamı
yalnız güvenilir ingestion, provenance, review, Obsidian canonical records,
rebuild edilebilir SQLite indeks ve commitments hatırlatmalarını kapsar.

## Güncel durum

Phase 6'nın yerel implementation'ı hazırdır. Mevcut kod güvenli plugin/CLI
iskeleti, source adapter'ları, idempotent source state, deterministik segmenter,
provenance zorunlu structured extraction, exact-only entity resolver,
deterministik policy, tekrar oynatılabilir review kuyruğu ve atomik canonical
Vault writer ile disposable SQLite FTS5 indeksini içerir. ChatGPT adapter gerçek
export doğrulanana kadar experimental'dır. Phase 6 kaynak kodu `main` dalına
birleştirilmiştir; aktif Hermes kurulumu ayrı bir teslim kapısıdır ve her seferinde
installed plugin SHA ile ayrıca doğrulanır. Sistem hâlâ:

- Obsidian Vault'a veya private raw store'a yazmaz,
- Hermes config/cron/gateway dosyalarını değiştirmez,
- yalnız açık `eval --shadow` komutunda paketlenmiş sentetik fixture ile model çağrısı yapar,
- notification göndermez.

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
[`docs/phase-6-status.md`](docs/phase-6-status.md).

## Mevcut CLI

Kaynak dalda aşağıdaki güvenli komut yüzeyleri vardır:

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
```

`eval --shadow` yalnız paketlenmiş sentetik frozen holdout'u aktif
`nexus_extract` model yoluna gönderir; aday içeriği yazmaz veya yayınlamaz ve
yalnız kalite/audit ölçümlerini ekrana verir. Review komutları yalnız private
olay kaydını değiştirir ve `vault_writes: false` raporlar. `rebuild` ve `search`
yalnız Vault dışındaki disposable indeksi değiştirir/okur. Mutating ingest,
canonical Vault publish ve reminders komutları sonraki fazlarda, kendi acceptance
testleri tamamlandıkça açılacaktır.

Extraction servisi yalnız plugin-owned `nexus_extract` auxiliary task'ını kullanır;
provider/model override istemez ve adayları hiçbir yere yayınlamaz.
