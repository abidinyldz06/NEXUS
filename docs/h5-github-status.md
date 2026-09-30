# H5 — salt okunur NEXUS GitHub görünümü

Yalnız `abidinyldz06/NEXUS`. Uygulamalar bölümünde açık düğme ile main SHA,
o SHA'daki en son main workflow koşusu ve en fazla 10 açık PR/head/check okunur.
PR listesi tüm PR'ların sayımı değildir; son main koşusu tüm workflow veya
deployment kabulü değildir. Kurulu plugin pin'i ayrıca doğrulanmalıdır.

Mevcut `gh` erişimi kullanılır; yeni anahtar veya connector yok. Sabit GET/pr
list/run list komutları kabuksuz çalışır; her çağrı en fazla 8 saniye (üç çağrı).
Panel modeli çağırmaz, merge/push/yorum/iş oluşturmaz. Default profil dışında
API okumaz. Hata, eksik auth, yanlış SHA ve timeout başarı sayılmaz; eski veri
gösterilmez, raw stderr ve secret döndürülmez. Atlanan/nötr kontroller yeşil
kabul edilmez; kontrol yoksa bilinmiyor gösterilir.

Yerel sahte taşıyıcı/API/UI testleri ve salt okunur gerçek GitHub adaptörü
kontrolü, kurulu paneldeki uçtan uca testten ayrı tutulur. Bu geliştirme paketi
henüz plugin'e kurulmuş sayılmaz; #59 ancak canlı panel kanıtından sonra kapanır.
