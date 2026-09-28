# NEXUS Hub H0+H1 — yerel geliştirme durumu

Bu paket, NEXUS'un mevcut otomatik yayın ve ingest sınırlarını değiştirmez.
Hermes paneli yalnızca mevcut indeks, kanonik Vault kayıtları ve inceleme
kuyruğundan okur. Görev çalıştırma, model yönlendirme, API anahtarı yönetimi ve
inceleme kararı verme bu pakette yoktur.

## H0: arama doğruluğu

- Tam metin indeksine yalnız kullanıcıya gösterilen alanlar ve kaynak alıntıları
  girer. Çıkarıcı kimlikleri ve teknik metadata arama eşleşmesi üretmez.
- Yeni indeks `search_profile` sürümü taşır. Eski indeks aramada kullanılmaz;
  kanonik Vault'tan kontrollü `index rebuild` gerekir. Rebuild, indeks dosyasını
  atomik olarak değiştirir; Vault'a yazmaz. Bu operasyon canlı ortamda ayrıca
  planlanmalı ve doğrulanmalıdır.

## H1: salt okunur yerel panel

- Hermes dashboard için Bugün, Uygulamalar, Görevler, Hafıza ve Modeller
  sekmeleri hazırlanmıştır. Görevler ve Modeller gerçek işlem yapmaz; sonraki
  aşama oldukları ekranda açıkça görünür.
- Hafıza araması ve bekleyen incelemeler GET uç noktalarıyla sunulur. Kayıt
  ayrıntısında kanonik dosyanın SHA-256 değeri indeks ile eşleşmeden "doğrulandı"
  denmez. Özgün konuşma bu panelde ayrıca doğrulanmış sayılmaz.
- Dashboard API'si Hermes'in kurulu ve etkin kullanıcı eklentisi kapılarından
  geçerek yüklenir. Test istemcisindeki doğrudan router montajı, canlı oturum
  kimlik doğrulamasını kanıtlamaz.

## Yayın/kabul sınırı

Kodun yerel testleri ile kurulu Hermes eklentisinin güncellenmesi ayrı adımlardır.
Bu değişiklikler merge/pin edilmeden, eski arama indeksi kontrollü biçimde
yeniden oluşturulmadan ve gerçek dashboard oturumunda ekran açılışı gözlenmeden
H0+H1'i canlı kullanımda tamamlandı sayma. Vault, Inbox, config, otomatik yayın,
canary guard'ları ve gözetimsiz bulk ingest bu paketin dışında kalır.
