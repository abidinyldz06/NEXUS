# NEXUS yerel kullanım kontrolü — 15 Ekim 2026

## Kapsam

OpenRouter ve NVIDIA kullanıcı kararıyla ertelendi. Yerel, insan denetimli
arama/kaynak görünümü ve pasif görev taslağı kontrol edildi. Yeni model çağrısı,
ingest, görev yürütme, otomatik yayın veya kullanıcı verisi silme yapılmadı.
Kontrol sırasında Hermes paneli v0.22.0, NEXUS kurulu checkout'u `5994e678` idi.

## Canlı panelde doğrulananlar

- Ana sayfa 22 aranabilir kayıt ve 16 bekleyen inceleme gösterdi.
- Yerel arama eşleşen bir kayıt döndürdü. Özel içerik bu rapora alınmadı.
- Kayıt ayrıntısında “Kanonik kayıt ve indeks eşleşiyor” doğrulaması görüldü.
  Kaynak bölümü ve özgün konuşmanın ayrıca doğrulanmadığı uyarısı görüntülendi.
  Bu, özgün konuşma doğruluğunun veya tüm kaynakların kabulü değildir.
- Bir sentetik taslak kaydedildi: “NEXUS yerel kabul kontrolü — 15.10.2026”.
  Veri kapsamı yalnız yerel; görev çalıştırılmadı.
- Sayfa yenilendi, Görevler yeniden açıldı, aynı taslak tek kez geri okundu.
  Toplam iki taslak vardı: yeni kontrol ve önceki 9 Ekim sentetik taslağı.
  Kontrol taslağı silinmedi. Bu işlem tek başına çift gönderim testi değildir.

## Bulunan ve hedefli düzeltilen hata

İngest v2 inceleme adaylarını `statement` alanıyla kaydediyor; Hub önizlemesi
yalnız `summary`, `display_name`, `predicate`, `literal` alanlarını okuyordu.
Bu yüzden 16 mevcut aday metni olmasına rağmen “Önizleme yok” görünüyordu.

Hub'a yalnız `statement` geri dönüşü eklendi. Mevcut `summary` önceliği,
240 karakter sınırı, metin tipi kontrolü ve salt okunur davranış korunur.
Review kuyruğu ve aday verileri değiştirilmez; alıntısı boş olan kaynağa metin
uydurulmaz. Bu değişiklik kurulu eklentiye henüz uygulanmadı.

## Doğrulama ve sınırlar

- Python tam suite: 368 test geçti, atlanan yok.
- Panel: 16 test geçti, atlanan yok; JavaScript sözdizimi kontrolü temiz.
- Yeni testler ingest biçimindeki `statement` önizlemesini, 240 karakter
  sınırını, eski alan önceliğini, geçersiz değerleri ve review dosyasının
  okumada değişmemesini kapsar.
- İlk test çalışmasında yeni sentetik fixture kaynak referansı içermediği
  için sözleşme doğrulaması durdurdu; fixture'a sentetik kaynak eklendi.
  Üretim sözleşmesi veya test güvenlik kontrolü gevşetilmedi.
- Config ve ücretsiz pilot maliyet defteri önceki SHA-256 ile aynı kaldı.
  Laguna belirsiz maliyet kaydı silinmedi, sıfırlanmadı veya yeniden çağrılmadı.

Yerel panel akışları için bu kontrol somut kanıttır; H6'nın tüm gerçek kullanım
günlerini, A8'i, üretim yedeğini veya dış model özet akışını geçti saymaz.
GitHub PR/CI, main merge ve kurulu eklenti güncellemesi ayrı teslim adımlarıdır.
