# H4.1 — Sağlayıcı kullanım/limit okuma

Bu dilim yalnız insanın açık düğme işlemiyle kullanım bilgisini okur.
H4'ün ücretli görev çalıştırma kabulü değildir. H3 öneri ve H2 taslak davranışı korunur.

## Uygulanan sınır

- `POST /api/plugins/nexus/hub/providers/{provider}/usage?profile=default`.
- Host dashboard kimlik doğrulaması ve profil-secret scope'u korunur.
- Panel açılışı/yenileme kullanım sorgusu veya model çağrısı yapmaz.
- OpenRouter: sabit TLS origin `openrouter.ai`, `GET /api/v1/key`, 8 sn socket
  timeout, 32 KiB yanıt sınırı; yönlendirme takip edilmez, otomatik retry yoktur.
- Dönen veriden yalnız toplam/günlük/haftalık/aylık kullanım, anahtar limiti,
  kalan anahtar limiti ve bilinen reset dönemi alınır. Bunlar USD ölçümleridir;
  hesap bakiyesi, tüm uygulamaların maliyeti veya görev bütçesi değildir.
- Eksik/geçersiz ölçüm `null` kalır; sıfır ya da sınırsız kabul edilmez.
- Anahtar etiketi, hesap/çalışma alanı kimliği ve sağlayıcı ham hatası dönmez.
- Anahtar Hermes'in profil-scoped secret mekanizmasından okunur. `model.key_env`
  / `model.api_key_env` pointer'ı yalnız model.provider=openrouter iken dikkate
  alınır; aksi halde `OPENROUTER_API_KEY` kullanılır. Yeni anahtar deposu yoktur.
- Salt credential-pool'da duran ve scoped secret'e bağlı olmayan bir anahtar bu
  dilimde okunmaz. Genel resolver'ın pool migration/persist yan etkisi nedeniyle
  ona fallback yoktur; gerekiyorsa Hermes'in mevcut anahtar yönetiminde bağlanır.
- Yönetim/provisioning anahtarı kullanım bütçesi olarak kabul edilmez; böyle
  bir anahtar istenmez. API'den yönetim anahtarı olduğu anlaşılırsa ölçüm gösterilmez.
- Gemini: proje kotası için AI Studio; NVIDIA: kota bağlantısı doğrulanmadı;
  Antigravity: uygulama aboneliği ayrı. Bu üç kart uydurma kota göstermez,
  secret okumaz ve dış istek yapmaz.
- Vault, Inbox, review, index, config, eval ve kimlik kayıtlarına yazılmaz.
  auto_publish/bulk ingest/canary ayarları değişmez. Ücretli inference endpoint'i yoktur.

## Doğrulama

Hermes Python ortamında tam unit suite ve API testleri; ayrıca native Node ile
`node --test tests/hub/provider_ui.test.cjs`. Ağ testleri sahte transport kullanır.
UI harness gerçek sunucu yerine SDK/React seam'lerini taklit eder; canlı tarayıcı
ve gerçek sağlayıcı testi yerine geçmez. Yeni bağımlılık eklenmedi.

## H4'te gerçekten kalanlar

1. Bu dilimin ayrı yayın incelemesi, main/pin ve canlı panel doğrulaması.
2. Kullanıcının seçtiği sağlayıcıya anahtarın Hermes'te güvenli bağlanması;
   anahtar chat'e, Git'e veya tarayıcı depolamasına yazılmaz.
3. İlk sentetik/seçili içerik işi için açık USD bütçesi ve model seçimi.
4. Ücretli iş öncesi atomik bütçe rezervasyonu, dış veri politikası, tek uçuş,
   toplam süre ve belirsiz timeout maliyetinin uzlaştırılması. Anahtar limiti tek
   başına bu iş bütçesinin yerine geçmez.
5. Politika/anahtar/bütçe reddinde sıfır ücretli çağrı testleri ve yetkili sınırlı
   canlı deneme. Bunlar yapılmadan H4 tamamlandı denmez.

## Kaynaklar

- [OpenRouter current-key API](https://openrouter.ai/docs/api/api-reference/api-keys/get-current-api-key)
- [Gemini rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)
