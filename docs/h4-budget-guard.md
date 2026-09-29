# H4.2 — Pilot bütçe rezervasyon çekirdeği

Bu dilim model çalıştırmaz, anahtar okumaz ve panel ayarlarını değiştirmez.
Güncel çalışır kullanım panelinin yerine geçmez. H4 henüz tamamlanmış değildir.

## Uygulananlar

- İş/gün/ay USD sınırları açıkça verilir; varsayılan harcama izni yoktur.
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

Canlı pilot için gerekenler: Hermes'te sağlayıcı anahtarı, seçilmiş model ve açık
USD pilot sınırı. Bunlar kullanıcıdan alınmadan ücretli çağrı yapılmaz.

## Testler

Tamamen geçici özel dizinlerde: aynı bütçeye iki bağlantı yarışı, tam sınır,
gün/ay toplamları, crash sonrası yeniden açılış, unknown/overrun, idempotency,
çelişkili uzlaştırma, tutar hassasiyeti, izinli veri kapsamı ve dosya izinleri.
Bu testler gerçek model/crash-resume kullanım kabulü değildir.
