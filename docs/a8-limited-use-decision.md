# NEXUS: A8 sınırlı kullanım kabulü

Tarih: 2026-09-28. Proje sahibi, A8'in **yalnız insan denetimli, sınırlı kullanım kapısını** mevcut kanıtlarla kabul etti. Bu, teknik A8 kabul koşullarının geçtiği anlamına gelmez; eşikler ve ölçülen sonuçlar değişmez. Sınırlı kullanım kararı A8 üzerinde daha fazla pahalı timeout tekrarını beklemeyi bırakır.

## Doğrulanan durum

- Gerçek export gölge işlemede 51/57 konuşma tamamlandı (%89,5); 55/57 eşiği geçilmedi.
- Tarihsel p95 553 saniye; 60 saniye koşulu geçilmedi. İnsan etiketli 30 örnek ve canlı kesinti-devam testi yok.
- Otomatik yayın kapalı. Son kalan beş timeout tekrarını sürdürmek anlamlı ilerleme sağlamadı.
- Ledger'daki Vault dosyası olmayan tek eski satır, son canary olayından sonra tamamlanan bir gölge segmentle eşleşiyor. Eski satırda açık yayın niyeti alanı olmadığı için bu satır **kesin kayıp değil** diye otomatik aklanmaz; ayrıca kendiliğinden Vault'a onarılmaz.

## Kullanım sınırı

Sınırlı kullanım kapısı **kabul edildi**. Gözetimsiz gerçek-export toplu ingest ve otomatik yayın için teknik A8 **başarısız/açık** kalır. NEXUS'un bağımsız, salt-okunur sorgu, arama, yönlendirme ve insan incelemeli taslak akışları A8'in kalan ölçümlerini beklemeden kullanılabilir. Bu karar mevcut güvenlik kapılarını kaldırmaz: yayın yalnız ilgili kaydın gözden geçirilmesi ve mevcut kesin onay mekanizmasıyla yapılır. Varsayılan `auto_publish_enabled=false` değişmez. Bu belge yeni bir üretim yayını, Vault yazısı, Telegram teslimi veya gözetimsiz çalışma onayı değildir.

## Ertelenen teknik A8 koşulları

Sınırlı kullanım için tekrar ingest koşulmaz. İleride gözetimsiz kapsam ayrıca istenirse önce sağlayıcı süresi/kuşaklama sorunu ayrı bir teknik kararla çözülmeli; kaynak eşleşmeyen konuşma zorlanmamalı, hash uyuşmazlığı insan incelemesinde kalmalı. Ayrı bir maliyet/süre bütçeli denemede en az 55/57, p95 <60 saniye, sıfır açıklanamayan canonical kayıp, insan kalite etiketi ve canlı kesinti-devam kanıtı birlikte ölçülmelidir. Eski niyetsiz ledger satırı ayrıca incelenene kadar kayıp kontrolü geçmiş sayılmaz.

Yeni ledger satırları `publication_intent=shadow` olarak başlar; yalnız canonical yazım denemesi öncesinde `canonical` olur. Kabul raporu gölgede yayımlanmamış satırları, canonical yazımı eksik satırları ve eski sınıflandırılamayan satırları ayrı sayar. Sınıflandırılamayan eski satırlar güvenli tarafta kalır; A8'in `silent_loss_0` koşulunu geçirmez.
