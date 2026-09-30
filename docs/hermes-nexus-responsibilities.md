# Hermes ve NEXUS: tek yönetim sahibi

30 Eylül 2026. Kullanıcının Hermes Bots ekranı ve yerel kaynak incelemesiyle
bot oluşturma/yönetme yeteneğinin Hermes'te mevcut olduğu doğrulandı.

Hermes bot/profil yönetimi yeniden geliştirilmez. Mevcut Writer, Research,
Coder, Scheduler ve Control Room profilleri yerel ad-listesi API'siyle görüldü.
`list_profile_names` yalnız profil kimliklerini okur; migration/ayar seed etme
riski taşıyan `list_profiles` kullanılmaz.

NEXUS Uygulamalar ekranı, kullanıcının düğmeye basmasıyla bilinen bu profilleri
salt okunur listeler ve mevcut Hermes sohbet ekranına bağlantı verir. Profil
bulunması runtime sağlığı, yetki, ücretsiz model veya görev teslim kanıtı değildir.
Bağlantı tıklaması mesaj/görev oluşturmaz. Profil/anahtar/konfigürasyon değiştirilmez.

Hermes'in sorumluluğu: botlar, sohbetler, çalışma yürütme, kanallar ve secret yönetimi.
NEXUS'un sorumluluğu: yerel kaynaklı hafıza, review, kullanıcı görev kapsamı,
NEXUS'a özel ücretsiz model politikası ve sonuç kanıtlarını görünür kılmak.
NEXUS'un 0 USD sınırı Hermes genel sohbetlerine aktarılmış kabul edilmez.

Bu paket ajanlara otomatik dispatch veya yeni scheduler değildir. Seçili metin
özeti mevcut dar NEXUS adaptöründe kalır; kanıtsız Hermes dispatch entegrasyonu
yapılmış gibi gösterilmez. H5'te seçili GitHub repo durum akışı henüz kalan iştir.

Kurulu sürüme geçiş ve canlı profil bağlantısı testi bu belge yazılırken yapılmadı.
