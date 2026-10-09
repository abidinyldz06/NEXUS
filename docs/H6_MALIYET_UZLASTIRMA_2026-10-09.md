# H6 — canlı maliyet uzlaştırması, 9 Ekim 2026

## Tamamlanan

Safari'deki açık OpenRouter hesabının 2 Ekim kayıtları incelendi. Kullanıcı,
10:50 ve 11:58 Space Bunny çağrılarının iki NEXUS testi olduğunu açıkça doğruladı.
Yalnız zaman yakınlığıyla otomatik eşleşme yapılmadı.

İki generation kimliği resmi `/api/v1/generation` GET sorgusuyla tekrar okundu.
Her iki yanıtta HTTP 200, eşleşen kimlik ve sayısal `total_cost=0` doğrulandı.
Mevcut panelin **Sağlayıcı kanıtıyla uzlaştır** yolu kullanıldı. Eski kayıtlar
silinmedi; iki kanıt bağlantısı eklendi. Bu aşamada dört bütçe kaydı da
`settled`, `actual=0` oldu. Eski çıktıların başarısı doğrulanmış sayılmadı.

## Yeni canlı deneme ve açık engel

Kişisel veri içermeyen kısa sentetik metinle seçili özet akışı denendi.
Space Bunny güncel katalogda bulunmadığından preflight model çağrısı ve yeni
bütçe kaydı oluşturmadan durdu.

İzin listesindeki Laguna S 2.1 katalogda sıfır fiyatlıydı. Açık seçimle bir kez
denendi. Panel `stopped` sonucu ve yeni belirsiz maliyet kaydı gösterdi; özet
ve görev taslağı oluşmadı. Yeni işlemin sağlayıcı kimliği yok. Mevcut panel
hata durumunda HTTP kodunu göstermediği için kesin hata kodu doğrulanamadı.
OpenRouter Generations ve Upstream Requests listelerinde yeni denemeye ait
bir kayıt görülmedi; bu tek başına sıfır maliyet kanıtı değildir.

Yeni kayıt uzlaştırılmadan başka çağrı yapılmadı. Bütçe kapısı zayıflatılmadı,
veri silinmedi, yeni bir bütçe dosyasıyla engelin etrafından dolaşılmadı.
Son durum: eski iki engel kapandı; yeni bir belirsiz işlem açık.

## Hedefli yerel düzeltme

- Önizleme sabit Space Bunny adı yerine seçilen gerçek model kimliğini gösterir.
- Model değişince önizleme/onay/sonuç temizlenir; yeniden onay gerekir.
- Özet sürerken model seçimi kilitlenir.
- Başarısız özetin HTTP kodu ve güvenli sabit hata nedeni gösterilir.
- Sağlayıcının ham hata gövdesi, anahtarı veya kişisel içerik yayımlanmaz.

Düzeltme ayrı yerel `codex/h6-summary-consent-feedback` dalındadır. GitHub'a
teslim, CI, main merge ve çalışan eklenti güncellemesi ayrı doğrulanmalıdır.

Doğrulama: Hermes Python ortamında **358 test**, Node panelinde **15 test**
geçti. JavaScript sözdizimi ve `git diff --check` temiz. HTTP 404 panel testi
sentetiktir; canlı Laguna isteğinin hata kodunun 404 olduğu iddia edilmez.

## Devam incelemesi

Resmi Laguna endpoints GET sorgusu HTTP 200 döndü. Bir ücretsiz Poolside
rotası listeleniyor; `max_tokens` desteği mevcut. Bu kamuya açık metadata
önceki çağrının hesabımıza özgü yönlendirme, gizlilik, kota veya hata nedenini
kanıtlamaz. Gizlilik koşulları gevşetilmedi, başka inference isteği yapılmadı.
Yeni belirsiz kayıt hâlâ korunuyor; kesin maliyet kanıtı olmadan kapatılmadı.

[OpenRouter endpoints API](https://openrouter.ai/docs/api/api-reference/endpoints/list-endpoints)

## Korunan sınırlar

Vault, Inbox, review, index, config ve eval dosyaları değiştirilmedi.
Config SHA-256: `423f84a6eac3d645d7d0c4f91dedf2c397358fe10a903e8010fb7fe6d673ac92`.
Otomatik yayın ve gözetimsiz ingest açılmadı. NVIDIA ertelenmiş kaldı.
Arama → dış model özeti → kalıcı görev taslağı canlı uçtan uca kabulü açık.
