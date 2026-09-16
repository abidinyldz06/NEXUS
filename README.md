# NEXUS

NEXUS, ATLAS kişisel asistanının local-first hafıza altyapısıdır. v0.1 kapsamı
yalnız güvenilir ingestion, provenance, review, Obsidian canonical records,
rebuild edilebilir SQLite indeks ve commitments hatırlatmalarını kapsar.

## Güncel durum

Phase 3'ün shadow-mode implementation'ı hazırdır. Mevcut kod güvenli plugin/CLI
iskeleti, source adapter'ları, idempotent source state, deterministik segmenter ve
provenance zorunlu structured extraction servisi içerir. ChatGPT adapter gerçek
export doğrulanana kadar experimental'dır. Aktif Hermes CLI hâlâ:

- Obsidian Vault'a veya private raw store'a yazmaz,
- Hermes config/cron/gateway dosyalarını değiştirmez,
- yalnız açık `eval --shadow` komutunda paketlenmiş sentetik fixture ile model çağrısı yapar,
- notification göndermez.

Paketlenmiş iki-vakalı frozen holdout, aktif `ollama-cloud` / `glm-5.3` rotasında
shadow modda başarıyla çalışmıştır. Bu sonuç Phase 3 contract kapısını doğrular;
geniş model-kalitesi kanıtı veya auto-publish yetkisi değildir.

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
[`docs/phase-3-status.md`](docs/phase-3-status.md).

## Mevcut CLI

Dört güvenli komut vardır:

```bash
hermes nexus status
hermes nexus config validate
hermes nexus ingest --dry-run
hermes nexus eval --shadow
```

`eval --shadow` yalnız paketlenmiş sentetik frozen holdout'u aktif
`nexus_extract` model yoluna gönderir; aday içeriği yazmaz veya yayınlamaz ve
yalnız kalite/audit ölçümlerini ekrana verir. Mutating ingest, review, rebuild,
search ve reminders komutları sonraki fazlarda, kendi acceptance testleri
tamamlandıkça açılacaktır.

Extraction servisi yalnız plugin-owned `nexus_extract` auxiliary task'ını kullanır;
provider/model override istemez ve adayları hiçbir yere yayınlamaz.
