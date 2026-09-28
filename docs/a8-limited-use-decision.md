# NEXUS: A8 açıkken sınırlı kullanım kararı

Tarih: 2026-09-28. Bu karar A8 kabulü değildir ve kabul eşiklerini değiştirmez.

## Doğrulanan durum

- Gerçek export gölge işlemede 51/57 konuşma tamamlandı (%89,5); 55/57 eşiği geçilmedi.
- Tarihsel p95 553 saniye; 60 saniye koşulu geçilmedi. İnsan etiketli 30 örnek ve canlı kesinti-devam testi yok.
- Otomatik yayın kapalı. Son kalan beş timeout tekrarını sürdürmek anlamlı ilerleme sağlamadı.
- Ledger'daki Vault dosyası olmayan tek eski satır, son canary olayından sonra tamamlanan bir gölge segmentle eşleşiyor. Eski satırda açık yayın niyeti alanı olmadığı için bu satır **kesin kayıp değil** diye otomatik aklanmaz; ayrıca kendiliğinden Vault'a onarılmaz.

## Kullanım sınırı

A8, gözetimsiz gerçek-export toplu ingest ve otomatik yayın için **başarısız/açık** kalır. NEXUS'un bağımsız, salt-okunur sorgu, arama, yönlendirme ve insan incelemeli taslak akışları A8 tamamlanmasını beklemeden kullanılabilir. Bu karar mevcut güvenlik kapılarını kaldırmaz: yayın yalnız ilgili kaydın gözden geçirilmesi ve mevcut kesin onay mekanizmasıyla yapılır. Varsayılan `auto_publish_enabled=false` değişmez. Bu belge yeni bir üretim yayını, Vault yazısı, Telegram teslimi veya canlı çalışma onayı değildir.

## Yeniden A8 ölçümü için kapanış koşulu

Yeni model çağrısı yapılmadan önce kalan timeout'lar için sağlayıcı süresi/kuşaklama sorunu ayrı bir teknik kararla çözülmeli; kaynak eşleşmeyen konuşma zorlanmamalı, hash uyuşmazlığı insan incelemesinde kalmalı. Ardından ayrı bir maliyet/süre bütçeli denemede en az 55/57, p95 <60 saniye, sıfır açıklanamayan canonical kayıp, insan kalite etiketi ve canlı kesinti-devam kanıtı birlikte ölçülmelidir. Eski niyetsiz ledger satırı ayrıca incelenene kadar kayıp kontrolü geçmiş sayılmaz.

Yeni ledger satırları `publication_intent=shadow` olarak başlar; yalnız canonical yazım denemesi öncesinde `canonical` olur. Kabul raporu gölgede yayımlanmamış satırları, canonical yazımı eksik satırları ve eski sınıflandırılamayan satırları ayrı sayar. Sınıflandırılamayan eski satırlar güvenli tarafta kalır; A8'in `silent_loss_0` koşulunu geçirmez.
