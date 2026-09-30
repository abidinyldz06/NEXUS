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

## Teslim kanıtı — 30 Eylül 2026

PR #63 main'e `431200e26620950dbf2fc555db4669f3d18acdd6` ile birleşti.
Temiz kurulu checkout ve Hermes envanter pin'i aynı SHA'da doğrulandı.
Kurulu sürümde 335 Python ve 9 panel testi geçti; main CI koşusu
`36685923690` başarılı. Canlı panelde 10:51'de düğmeyle yapılan okuma aynı
main SHA'sını, `completed / success` sonucunu ve açık PR olmadığını gösterdi.
#59 bu kanıtla kapandı. Yerel test, CI, kurulum ve canlı panel kanıtı ayrıdır.
Model çağrısı veya kullanıcı verisine yazma yapılmadı; auto-publish kapalı kaldı.
Bu teslim #60 görev görünürlüğü veya #61 gerçek kullanım kabulünü kapatmaz.
