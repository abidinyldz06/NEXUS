# NEXUS — güncel Türkçe yol haritası

Son değerlendirme: 30 Eylül 2026. Bu belge eski faz notlarını silmez; mevcut
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

PR/CI ile kurulu checkout/pin ve canlı arayüz doğrulaması ayrı kanıtlardır.
`431200e` kurulu sürümünün tam yerel suite'i 335 Python ve 9 panel testidir. CI ortamında
Hermes/FastAPI eksikse API testleri atlanır; atlanan testler geçti sayılmaz.

## Öncelikli kalan işler

| Öncelik | İş | Bağımlılık | Kapanış ölçütü |
| --- | --- | --- | --- |
| 1 | Görev sonucu ve kesinti görünürlüğü (#60) | Mevcut pasif taslak + dar ücretsiz özet akışı; Hermes yürütmesi incelenmeli | Taslak/başlamadı/çalışıyor/sonucu belirsiz/taslak sonuç ayrımı; model veya mesaj yan etkisi iki kez oluşmaz; bütçe belirsizliği açık görünür |
| 2 | Gerçek kullanım ve toparlanma kabulü (#61) | Kullanılabilir akışlar, insan gözlemi, güvenli yedek/restore kapsamı | Kullanılan günler ve sonuçlar kanıtlı; hata/mükerrer/provenance incelemesi; kontrollü sentetik toparlanma kanıtı; açık sorunlar dürüstçe sınıflı |

Görev görünürlüğünü tamamlamadan yeni bir bot yöneticisi, scheduler veya genel proxy kurulmaz.
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
  [görev/kesinti görünürlüğü #60](https://github.com/abidinyldz06/NEXUS/issues/60).
- [H6 gerçek kullanım/toparlanma](https://github.com/abidinyldz06/NEXUS/milestone/3):
  [kabul değerlendirmesi #61](https://github.com/abidinyldz06/NEXUS/issues/61).
