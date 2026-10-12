# NEXUS — güncel Türkçe yol haritası

Son değerlendirme: 12 Ekim 2026. Bu belge eski faz notlarını silmez; mevcut
teslimi ve gerçekten kalan işleri ayırır. Tahmini tarih veya yüzde, kabul kanıtı değildir.

## Teslim edilen dilimler

| Dilim | Kanıt | Durum ve sınır |
| --- | --- | --- |
| H0/H1 yerel hafıza paneli | Mevcut arama/index profili, kayıt hash kontrolü ve review görünümü | Kullanımda; kaynak referansı özgün konuşmanın ayrıca doğrulandığı anlamına gelmez |
| H2 pasif görev masası | Taslak kaydı, UUID, Hermes oturum referansı | Kullanımda; otomatik yürütme yok |
| H3 yerel yönlendirme önerisi | PR #54 | Main'de; model dispatch yok, tüm H3 kalite ölçümleri bu belgede geçti sayılmaz |
| H4 sağlayıcı kullanım görünümü | PR #55 | Kullanımda; tüm sağlayıcılarda kota/erişim kanıtı değil |
| H4 sıfır maliyet koruması ve sentetik model testi | PR #56; çalışan panelde Space Bunny testi | Kullanımda, doğrulanmış 0 USD; genel Hermes sohbet maliyetlerini yönetmez |
| H5 seçili kısa metin özeti | PR #57; çalışan panelde Türkçe sentetik özet | Kullanımda; 400 karakter, her işlemde onay, yalnız taslak sonuç |
| Hermes mevcut ajan bağlantıları | PR #58; kurulu pin `074412a`; canlı listede altı profil, Writer sohbet geçişi | Kullanımda; yeni bot, mesaj veya dispatch yok |
| H5 salt okunur GitHub durumu | PR #63; kurulu pin `431200e`; canlı panel main ve başarılı son koşuyu gösterdi, #59 kapandı | Kullanımda; yalnız NEXUS, en fazla 10 açık PR; merge/push yok |
| H5 işlem sonucu ve kesinti görünürlüğü | PR #65; kurulu pin `8f5f6af`; canlı panel ve sayfa yenilemesi aynı iki eski kaydı gösterdi, #60 kapandı | Kullanımda; eski maliyet kaydı sonuç başarısı sayılmaz, içerik/yanıt saklanmaz, tekrar/resume yok |

PR/CI ile kurulu checkout/pin ve canlı arayüz doğrulaması ayrı kanıtlardır.
`8f5f6af` kurulu sürümünün tam yerel suite'i 341 Python ve 10 panel testidir. CI ortamında
Hermes/FastAPI eksikse API testleri atlanır; atlanan testler geçti sayılmaz.

## Öncelikli kalan işler

### H6 güncellemesi — 12 Ekim

- PR #70 birleşti: main `5994e678`. Kurulu checkout aynı commit'te ve temiz.
- 9 Ekim teslim kanıtı: 366 Python + 16 panel testi, atlanan yok; main CI
  `37939220788` unit/HTTP/panel başarılı. Bu ölçüm canlı kullanım kabulü değildir.
- Yerel görev kaydetme, sayfa yenilemesinde geri okuma ve aynı işlem kimliğiyle
  mükerrer oluşturmama kanıtlandı. Model çağrısı ve görev yürütme yapılmadı.
- Süreç kesintisi/toparlanma testi sahte sağlayıcı ve geçici veriyle mevcut;
  production restore veya canlı sağlayıcı kesintisi kabulü değildir.
- 12 Ekim hedefli yeniden ölçüm: sentetik restore, Git rollback, süreç
  kesintisi ve yerel görev testlerinde 16/16 geçti. Yalnız geçici test verisi
  kullanıldı; production verisi ve canlı model çağrısı kullanılmadı.
- Dört maliyet kaydı doğrulanmış, bir Laguna kaydı belirsizdir. Eski kayıtta
  sağlayıcı kimliği ve HTTP kodu yok; yeni teşhis paketi geçmiş kanıtı üretmez.
- Kullanıcı 10 Ekim destek başvurusunu gönderdiğini bildirdi. Gönderim/talep
  kimliği ve yanıt bağımsız doğrulanmadı; yeni başvuru açılmaz.
- NVIDIA ertelenmiş, otomatik yayın ve gözetimsiz ingest kapalı kalır.

Destek yanıtı bütün yerel geliştirmeyi durdurmaz. Yalnız maliyeti belirsiz yeni
dış model çağrıları durur; salt okunur hafıza ve pasif yerel taslaklar kullanılabilir.

| Öncelik | İş | Bağımlılık | Kapanış ölçütü |
| --- | --- | --- | --- |
| 1a | Laguna maliyet kanıtı | Mevcut destek başvurusunun yanıtı | İstekle eşleşen sağlayıcı kimliği veya resmi işlem/ücret teyidi; bilinmeyen kayıt silinmez veya sıfır varsayılmaz |
| 1b | Yerel toparlanma regresyonu | Mevcut geçici-veri testleri | Kaydetme/geri okuma/mükerrer engeli ve sentetik restore/kesinti testleri; canlı pilot yerine geçmez |
| 1c | Seçili metin → özet → kalıcı taslak canlı kabulü | 1a, güncel ücretsiz katalog, her çağrı için onay | Tek sınırlı sentetik akış, doğrulanmış maliyet, taslağın geri okunması ve mükerrer oluşturmama |
| 1 | Gerçek kullanım ve toparlanma kabulü (#61) | Kullanılabilir akışlar, insan gözlemi, güvenli yedek/restore kapsamı | Kullanılan günler ve sonuçlar kanıtlı; hata/mükerrer/provenance incelemesi; kontrollü sentetik toparlanma kanıtı; açık sorunlar dürüstçe sınıflı |

H5'in tanımlı dar akışları teslim edildi; bu genel bir bot yöneticisi, scheduler
veya proxy kurma izni değildir. Gerçek kullanım/toparlanma kabulü ayrı kalır.
Hermes'in mevcut yeteneği tekrar geliştirilmez. Görev yürütmesinin asıl kaydı
Hermes'te; NEXUS'taki taslak onu otomatik başlatmaz.

## Ayrı kabul ve ertelenen kapsam

- **A8 teknik kapısı açık:** 51/57, eşik 55/57; tarihsel süre koşulu, insan kalite
  etiketi, canlı kesinti-devam ve eski niyetsiz ledger satırı konusu kapanmadı.
  Salt okunur/insan denetimli akışlara genel bekleme şartı değildir.
- **29 Eylül–5 Ekim insan denetimli pilot:** geçen gün veya cron başarısı kullanım
  günü değildir. 28 Eylül Telegram testi ve sentetik model örnekleri tek başına
  pilot kabulü sağlamaz. 5 Ekim değerlendirmesi gerçek kanıtları özetlemelidir.
- Gözetimsiz bulk ingest, auto-publish, sürekli Telegram gönderimi, Vault'a
  otomatik yazma, ücretli model ve rastgele uygulamaya dispatch bu yol haritasının
  mevcut teslim kapsamı değildir; ayrıca açık yetki ve kabul gerekir.
- NVIDIA/Gemini/Antigravity kartlarının varlığı tam bağlantı veya kullanım API'si
  doğrulaması değildir. Gerçek ihtiyaç belirlenmeden yeni bağımlılık eklenmez.

## GitHub takibi

Milestone'lar Türkçe tutulur: teslim edilmiş dar Hub akışları, H5 kalan iş yapan
akışlar ve H6 gerçek kullanım/toparlanma. Bir milestone ancak tanımlı kapsamı
kanıtlandığında kapanır; tüm proje bitti veya A8 geçti anlamına gelmez.

- [Teslim edilen dar akışlar](https://github.com/abidinyldz06/NEXUS/milestone/1): PR #54–58.
- [H5 kalan iş yapan akışlar](https://github.com/abidinyldz06/NEXUS/milestone/2):
  [GitHub durum ekranı #59](https://github.com/abidinyldz06/NEXUS/issues/59) tamamlandı (PR #63);
  [görev/kesinti görünürlüğü #60](https://github.com/abidinyldz06/NEXUS/issues/60) tamamlandı (PR #65).
- [H6 gerçek kullanım/toparlanma](https://github.com/abidinyldz06/NEXUS/milestone/3):
  [kabul değerlendirmesi #61](https://github.com/abidinyldz06/NEXUS/issues/61).
