# H5 — işlem sonucu ve kesinti görünürlüğü (#60)

Görevler bölümündeki **İşlem durumlarını oku** düğmesi mevcut ücretsiz test/özet
kayıtlarını salt okunur okur. Sayfa açılışı, okuma veya restart model çağırmaz.
Bu liste Hermes yürütme kaydının kopyası değildir; pasif görev taslakları başlamadı.

Yeni, açıkça başlatılan test/özet işlemi yalnız UUID, durum ve UTC zamanını
mevcut özel bütçe dosyasının `outcomes` tablosuna ekler. Prompt, yanıt, anahtar
ve kişisel içerik eklenmez. Yeni tablo yalnız açık model işlemi sırasında
oluşur; okuma eski dosyayı migrate etmez, eksik dosya/dizin oluşturmaz.

- **Çalışıyor:** mevcut servis sürecinde aktif işlem gözlendi. Başka worker'da
  veya restart sonrasında canlı kanıt yoksa “çalışıyor” varsayılmaz.
- **Taslak sonuç doğrulandı:** tamamlanma metadatası ve uzlaştırılmış maliyet
  birlikte mevcut. Yanıt diske kaydedilmedi; kaybolan yanıt geri getirilemez.
- **Model çağrısı başlamadan hata:** maliyet sıfırla uzlaştırıldı ve çağrı başlamadı.
- **Sonuç belirsiz:** eski yalnız maliyet kaydı, kesinti veya eksik sonuç kanıtı.
  Eski başarılı maliyet kaydı geriye dönük başarılı sonuç sayılmaz.

Uzlaştırılmamış `reserved/unknown/overrun` kayıtları mevcut bütçe korumasıyla
yeni işi durdurur. Aynı UUID tekrar gönderilirse dispatch yapılmaz. Durum paneli
kaydı temizlemez, hold'u çözmez, resume/retry yapmaz veya yeni izin vermez.
Liste en fazla 30 kayıt gösterir; toplam ve blokaj tüm kayıtlardan hesaplanır.
Default profil dışında desteklenmez. Hata eski başarı sonucu olarak gösterilmez.

## Geliştirme kanıtı

341 Python ve 10 arayüz testi geçti. Yeni testler çift gönderim sırasında tek
model çağrısı, timeout sonrası blokaj, restart sonrası belirsizlik, eski store'un
değişmeden okunması ve default/read-only API sınırlarını sahte sağlayıcıyla ölçer.
Gerçek sağlayıcı çağrısı yapılmadı; production verileri veya guard'lar değişmedi.
Bu geliştirme kanıtı tek başına kurulu canlı panel kabulü değildir.

## Kurulum ve canlı görünüm kanıtı — 30 Eylül 2026

PR #65 main'e `8f5f6afb9d5bc5b71276b2735525434182b19c04` ile birleşti.
Temiz kurulu checkout ve Hermes pin'i aynı SHA; kurulu suite 341 Python ve
10 arayüz testi geçti. Main CI `36690375311` başarılı.
Canlı default panelde iki eski kaydın maliyeti doğrulanmış, sonucu belirsiz
gösterildi; sayfa yenilemesi ve ikinci okuma aynı kayıtları korudu. Bu eski
yalnız maliyet kayıtları yeni hata değildir; tamamlanma metadatası geçmişte
saklanmadığı için sonuç başarısı varsayılmaz. Yeni model çağrısı yapılmadı.
#60 dar görünürlük kapsamı kapandı. Gerçek sağlayıcı timeout/crash testi veya
üretim restore yapılmış sayılmıyor; #61 ve A8 teknik koşulları ayrı açık kalır.
