# H4.2 — Pilot bütçe rezervasyon çekirdeği

Bu dilim model çalıştırmaz, anahtar okumaz ve panel ayarlarını değiştirmez.
Güncel çalışır kullanım panelinin yerine geçmez. H4 henüz tamamlanmış değildir.

## Uygulananlar

- İş/gün/ay USD sınırları açıkça verilir; varsayılan harcama izni yoktur.
  Kullanıcının yalnız ücretsiz model talebiyle üç sınırın da sıfır olması desteklenir;
  sıfır rezervasyonda bile tek uçuş ve unknown koruması korunur.
- Tutarlar altı ondalık basamaklı tam micro-USD olarak tutulur; float kullanılmaz.
- Özel SQLite dosyasında BEGIN IMMEDIATE ile eşzamanlı rezervasyonlar serileştirilir.
- Pilot başına tek uzlaştırılmamış istek; aynı işlem kimliği tekrar rezervasyon açmaz.
- Aynı defterde sınırlar yeniden açılışla artırılamaz. Gizli config değişikliği yoktur.
- Timeout/eksik maliyet `unknown`: sıfır harcama sayılmaz ve takvim geçişinde bile
  yeni çağrıya yer açmaz. Durum yeniden başlatmada korunur.
- Yalnız sağlayıcıdan doğrulanmış gerçek maliyetle uzlaştırılır. Sıfır da ancak
  doğrulanmışsa sıfırdır. Sonradan çelişkili maliyet yazımı reddedilir.
- Rezervasyon üstü doğrulanmış harcama dürüstçe kaydedilir; `overrun` yeni işleri
  bloke eder. Harcama kaydını silerek ya da üst sınırı artırarak test geçilmez.
- Gün/ay dönemleri UTC'dir. Çalıştırıcı zaman bilgisini kendisi vermelidir;
  bu çekirdek tarayıcıdan gelen zamanı güvenilir kabul edecek API açmaz.
- Defter yolu açıkça sağlanır, mevcut özel dizin gerektirir. Constructor I/O yapmaz.
  Gerçek üretim yolu seçilmedi ve üretim bütçe defteri oluşturulmadı.
- İçerik, prompt ve anahtar deftere yazılmaz; yalnız işlem kimliği, dönem ve tutar vardır.
- Ayrı veri politikası kontrolü yalnız açıkça izinli sentetik/seçili içerik ve seçilmiş
  model kabul eder; hassas/yerel/belirsiz kapsam veya Antigravity uygulaması reddedilir.

## Bir sonraki bağlantı adımı

Rezervasyon yetki veya sağlayıcının kesin harcama garantisi değildir. Bir sonraki
dispatcher veri politikasını, anahtarı, güvenilir güncel fiyatı ve token sınırlarını
doğrulamalı; rezervasyon `created=true` olduğunda yalnız bir kez dispatch etmelidir.
Gerçek maliyet kanıtı olmadan rezervasyon çözülmemelidir. Ücretli endpoint,
fiyatlandırma adaptörü, içerik aktarımı veya panel çalıştır düğmesi bu dilimde yoktur.

Kullanıcı OpenRouter anahtarı kaydını ve yalnız ücretsiz modelleri açıkça yetkilendirdi.
Anahtar Hermes'in desteklenen credential lifecycle mekanizmasıyla kaydedilir;
chat, Git, test fixture ve bu dokümana kopyalanmaz. Canlı ücretsiz pilot sıfır USD
sınırında kalır; ücretli çağrı yetkisi yoktur.

`free_model.py` yalnız `openrouter/free` kabul eder. Sabit TLS endpoint'inde,
64 çıktı tokenı ve 500 karakter girdi sınırıyla istek kurar. Ücretli model listesi,
otomatik retry, tool, plugin veya caller extra_body yoktur. Provider alanında
prompt/completion/request/image max_price=0, allow_fallbacks=false,
require_parameters=true ve data_collection=deny korunur. İzinli ücretsiz rota
yoksa işlem durur; kısıtlar gevşetilmez. Numeric cost=0 kanıtı yoksa harcama
doğrulanmış sayılmaz. Bu adaptör henüz panel/gateway görev akışına bağlanmadı;
Hermes'in diğer sohbet modellerini veya sağlayıcılarını değiştirmez.

Kaynak: [OpenRouter Free Router](https://openrouter.ai/docs/guides/routing/routers/free-router),
[provider fiyat ve veri kontrolü](https://openrouter.ai/docs/guides/routing/provider-selection).

## 30 Eylül bağlantı kanıtı

- Hermes anahtar kaydı tamamlandı; dosya izinleri 0600'a daraltıldı.
- Canlı kullanım paneli sağlayıcıdan metrik okuyabildi; o anda kullanım 0 USD idi.
  Bu hesap bakiyesi ya da tüm Hermes uygulamaları için ücretli model kilidi değildir.
- Tek sentetik free-router isteği HTTP başarı yanıtı alamadan `stopped` döndü.
  O koşunun adaptörü HTTP kodunu dışarı vermediği için kesin hata nedeni bilinmiyor;
  sonrasında güvenli HTTP kodu raporlaması eklendi. Aynı model isteği tekrarlanmadı.
- Maliyet kanıtı yok: bu istek kabul edilmiş veya kesin sıfır maliyetli sayılmadı.
  Tanı defterindeki hold `unknown` kaldı; üretim defteri oluşturulmadı.
- Anahtar geçerliliği ayrı salt okunur current-key sorgusuyla doğrulandı;
  bu sorgu inference değildir. Ücretli fallback veya kısıt gevşetme yapılmadı.
- Çalışan eklenti hâlâ 76276fea kullanım panelidir; bu yeni adaptör yereldir.

## Testler

Tamamen geçici özel dizinlerde: aynı bütçeye iki bağlantı yarışı, tam sınır,
gün/ay toplamları, crash sonrası yeniden açılış, unknown/overrun, idempotency,
çelişkili uzlaştırma, tutar hassasiyeti, izinli veri kapsamı ve dosya izinleri.
Bu testler gerçek model/crash-resume kullanım kabulü değildir.
