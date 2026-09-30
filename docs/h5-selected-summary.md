# H5 — seçili kısa metin özeti

30 Eylül 2026. Geliştirme/PR hazırlığı; kurulu eklenti teslimi değildir.

Kullanıcı, panelde seçtiği hassas olmayan metnin her işlemde panel onayıyla
OpenRouter'ın yalnız ücretsiz modeline gönderilmesini bu sohbette açıkça onayladı.
Bu yetki bütün Vault'a, dosyalara veya gözetimsiz işlemeye genişletilmez.

## Akış

Görevler → en fazla 400 karakter metin → yerel önizleme → bu metin için
onay kutusu → Space Bunny Alpha ile kısa Türkçe taslak özet.
Metin değişince önizleme ve onay silinir. Her yeni gönderim ayrı onay ister.
Veri hassasiyeti kullanıcı beyanıdır; otomatik hassas veri tespiti garantisi yoktur.
Sağlayıcının içerik saklama uyarısı panelde görünür.

## Sınırlar

- Yalnız default profil ve açık POST `/hub/selected-summary`.
- UUID, sabit izinli model, metin ve iki strict boolean onay alanı; ekstra alanlar reddedilir.
- Veri Vault'tan, dosyadan, görev taslağından veya hafıza bağlamından alınmaz.
- Her çağrıda güncel sıfır fiyat kontrolü; 0 USD sınırı, fallback ve otomatik retry yok.
- Sentetik testle aynı kalıcı metadata bütçe kaydı; içerik/yanıt bu kayda yazılmaz.
- Aynı UUID ikinci kez inference başlatmaz. Maliyet/timeout belirsizse sonraki iş durur.
- Yanıt yalnız panel belleğinde, HTML olarak çalıştırılmadan gösterilir; API `no-store` döndürür.
- Otomatik yayın kapalı olmalı; bulk ingest, canary guard, review/index/Vault değişmez.
- Sonuç bir taslak özettir; model yanıtının doğruluğunu kullanıcı kontrol eder.
- Canlı gerçek metin gönderimi bu geliştirme sırasında yapılmadı.

## Doğrulama

326 yerel Python testi, 7 panel testi; gönderim öncesi politika/boyut/onay kontrolleri,
strict boolean API doğrulaması, tekrar ve belirsiz maliyet engeli, içeriksiz metadata,
metin değişiminde onay iptali ve yerel önizlemenin ağ çağırmaması test edildi.
