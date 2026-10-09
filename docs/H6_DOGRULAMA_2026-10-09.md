# H6 doğrulama — 9 Ekim 2026

## Kapsam

NVIDIA ertelendi. Otomatik yayın, gözetimsiz ingest, Vault/Inbox/review/index/config
ve mevcut eval dosyaları değiştirilmedi. Kurulu sürüm `f615b089`.

## Gerçek panel ve yerel kayıt kanıtı

- Kullanıcının onayıyla bir sentetik, yalnız yerel görev taslağı kaydedildi:
  `NEXUS H6 — yerel kaydetme doğrulaması 09.10.2026`.
- Panel sayfası yenilendi; aynı taslak tek kayıt olarak geri okundu.
- Kayıtlı işlem kimliğiyle backend kaydetme işlemi iki kez tekrarlandı.
  İki sonuç da `created=false`; aynı görev kimliği döndü, yeni satır oluşmadı.
- Görev yürütülmedi; modele bu taslak gönderilmedi. Kontrol taslağı silinmedi.
- Bu, canlı panelde yerel kaydetme/yeniden okuma ve gerçek backend idempotency
  kanıtıdır. Arama → dış model özeti → taslak akışının bütünü geçti sayılmaz.

## Kesinti kanıtı ve sınırı

`tests/hub/test_pilot_crash_resume.py` ayrı bir Python süreci başlatır, sahte
sağlayıcı çağrısına ulaşınca süreci gerçekten sonlandırır. Veriler yalnız geçici
bir dizindedir; gerçek API anahtarı veya ağ çağrısı kullanılmaz.

Yeniden açılan kayıtta belirsiz işlem görünür, maliyet doğrulanmış sayılmaz,
aynı kimlikle tekrar çağrı yapılmaz ve yeni kimlikle de ikinci çağrı engellenir.
Bu, gerçek süreç kesintisiyle bir regresyon testidir; canlı OpenRouter HTTP
kesintisi veya insan denetimli pilot kabulünün yerine geçmez.

## Açık maliyet engeli

Panelin açık kullanım sorgusu 9 Ekim 11:04 İstanbul saatinde OpenRouter
anahtarının toplam kullanımını `0,003444 USD` olarak okudu. Bu, anahtarın tüm
kullanımıdır; iki belirsiz NEXUS işlemine ait tutar olarak yorumlanamaz.

Eski pilot kayıtlarında OpenRouter generation kimliği saklanmamış. Yerel işlem
UUID'si sağlayıcının generation kimliği değildir. Eldeki kayıtlar işlem bazında
sıfır maliyet kanıtı sağlamadığı için uzlaştırılmadı, silinmedi veya yeni bütçe
dosyasıyla etrafından dolaşılmadı. Ücretsiz model şartı değişmedi.

Sonraki gerekli kanıt: 2 Ekim 2026'daki ilgili istekler için OpenRouter Activity
kayıtlarının işlem zamanı, model, generation kimliği ve maliyet alanları.
Prompt/yanıt metni veya API anahtarı paylaşılmamalı. Bir kayıt yalnız zaman
yakınlığıyla otomatik eşleştirilmemeli.

Resmî kaynaklar:

- [Generation maliyet sorgusu](https://openrouter.ai/docs/api/api-reference/generations/get-request-&-usage-metadata-for-a-generation)
- [Activity API kapsamı ve management key şartı](https://openrouter.ai/docs/api/api-reference/analytics/get-user-activity-grouped-by-endpoint)

## Teslim sınırı

İlk yerel doğrulama: 346 Python testi ve 12 panel testi geçti. `git diff --check`
hata vermedi. Kurulu eklenti bu test dosyasını içermez; uygulama kodu değişmedi.

Yeni kesinti testi ve bu rapor yereldir; commit/push/PR/CI/kurulu eklentiye
teslim edildiği iddia edilmez. H6 genel kabulü açık kalır: işlem bazında maliyet
uzlaştırması ve engel kalktıktan sonra gerçek seçili metin özeti akışı gerekli.

## Cursor değişikliklerinin tamamlanması

Cursor'ın generation kimliği kaydı ve açık maliyet sorgulama değişiklikleri
incelendi. 422 eksik gövde ve 409 eksik/yanlış profil kontrolleri doğrulandı.

Ek düzeltmeler:

- Kimliği saklanmamış eski `unknown` kayıt da `accepted` kayıt gibi, yalnız
  açık kullanıcı eşleştirme onayı ve sağlayıcının sayısal maliyet yanıtıyla
  uzlaştırılabilir. Zaman yakınlığı otomatik eşleşme sayılmaz.
- Manuel uzlaştırma tamamlandıktan sonra aynı generation kimliğiyle aynı HTTP
  isteği tekrar gönderilirse hata vermeden aynı sonuç döner; kayıt değişmez.
- Eşleştirme onayı HTTP gövdesinde strict boolean; panelde ayrı kutucuktur.
  Kimlik metni değişince kutucuk sıfırlanır. Onay olmadan sağlayıcı sorgusu yok.
- Başarılı doğrulamadan sonra panel işlem durumunu tekrar okur.
- Bağımsız HTTP testinin Pydantic tip çözümlemesi için dinamik test modülü
  `sys.modules` içine test süresi boyunca kaydedilir; diğer testlere bağımlılık
  kaldırıldı.

HTTP bütünleşme testi gerçek geçici SQLite kaydına karşı çalıştı: onaysız giriş
409, yanlış sağlayıcı kimliği kaydı değiştirmiyor, doğrulanmış sıfır maliyet
engeli kaldırıyor, aynı isteğin tekrarı yeni kayıt oluşturmuyor. Sağlayıcı GET
yanıtları sentetik; canlı OpenRouter maliyet uzlaştırması yapıldığı iddia edilmez.

Son doğrulama: **357 Python testi + 13 panel testi geçti**, HTTP testleri
Hermes Python ortamında atlanmadı. JavaScript sözdizimi ve diff kontrolü geçti.
Bu ölçümün yapıldığı anda uygulama değişiklikleri geliştirme checkout'unda
yereldi; commit/push/merge ve kurulu `f615b089` eklentisine güncelleme yapılmamıştı. Eski iki gerçek kaydın
maliyeti değiştirilmedi. NVIDIA, kullanıcı verileri ve yayın/ingest sınırları
bu çalışmanın dışında kaldı.

Teslim hazırlığında CI'a ayrıca HTTP bağımlılıklarıyla API testleri ve Node
panel testleri eklendi. Bağımlılıklar yalnız CI ortamında kurulur. PR/CI,
main merge ve çalışan eklenti teslimi birbirinden ayrı doğrulanmalıdır.
