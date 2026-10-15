# H6 — yerel teknik kabul ve gerçek kullanım ayrımı

Değerlendirme: 15 Ekim 2026. Kapsam: kullanıcının istediği yerel,
insan denetimli NEXUS sürümü. OpenRouter ve NVIDIA ertelenmiştir.

## Doğrulanmış teslim

PR #71 ve #72 main'de; güncel main ve temiz kurulu checkout
`a8e7c99090a2c404fbe997e50e1e0c0fc1afe1d8` sürümündedir.
Main CI `38728920357` başarılıdır. Önceki teslim sırasında kurulu sürümde
368 Python ve 16 panel testi atlanmadan geçmiştir; bu rapor için testler
gereksiz yere tekrar çalıştırılmadı.

Canlı panelde arama, kanonik kayıt/indeks eşleşmesi, yerel taslak kaydetme ve
sayfa yenilemesinde geri okuma kontrol edildi. İnceleme önizlemesi düzeltmesi
kurulu sürüme alındı ve 16 adayın önizlemesinin göründüğü doğrulandı.

## Bu değerlendirmedeki salt okunur denetim

| Kontrol | Sonuç | Sınır |
| --- | --- | --- |
| Kanonik kayıt ve indeks | 22/22 hash, güvenli dosya yolu ve kayıt kimliği doğrulandı; hata yok | Özgün konuşmanın anlamsal doğruluğu ayrıca incelenmedi |
| Kaynak referansı varlığı | 22/22 kanonik kayıtta mevcut | Referansın varlığı özgün kaynak içeriğinin doğrulanması değildir |
| Bekleyen inceleme | 16 adayda metin ve kaynak referansı mevcut | Adaylar onaylanmadı, yayımlanmadı veya silinmedi |
| Yerel taslak | İki kayıt; işlem anahtarında mükerrer grup 0 | Aynı içeriğin farklı anahtarlarla yazılması bu ölçümün dışında |
| Taslak yürütme | `dispatch_enabled=false` | Taslak kaydı Hermes görev yürütmesi sayılmaz |
| Otomatik yayın | `auto_publish_enabled=false` | Koruma değiştirilmedi |

İki taslak da bilinen sentetik kontrollerdir (9 ve 15 Ekim). Bunlardan gerçek
kullanım günü çıkarılmadı. 29 Eylül–5 Ekim pilotunu geçti sayacak yedi ayrı
insan kullanım günü bu denetimde doğrulanmadı. Bu, hiç kullanılmadığı iddiası
değil; kabul için yeterli kanıt olmadığı tespitidir.

## Karar ve kalan iş

Yerel teknik teslim tamamlandı: arama, kaynak görünümü, inceleme önizlemesi ve
pasif taslaklar kullanılabilir. Bu denetim yeni bir kod gereksinimi ortaya
çıkarmadı. Kullanıcı sıradan yerel işlerinde sistemi kullanabilir.

Genel H6 #61 açık kalır; eksik olan yeni bir özellik değil, gerçek kullanım
ve sonuç kanıtıdır. Gerçek bir arama/sonuç yararlılığı kullanıcı tarafından
doğrulanmalı; gerçek görev taslağının beklenen işi doğru temsil ettiği
gözlenmelidir. Sentetik taslaklar ve otomatik cron başarısı bu gözlemin yerine
geçmez. Eski pilot tarihi veya teknik eşikler sessizce değiştirilmez.

OpenRouter maliyet kaydı, NVIDIA, A8, gözetimsiz ingest, otomatik yayın ve
otomatik görev yürütme ayrı ertelenen/açık kapsamlardır. Yerel teslimin önüne
genel bekleme şartı olarak konulmaz; güvenlik engelleri de kaldırılmaz.

Bu rapor yereldir; GitHub'a commit/push/PR teslimi veya #61'in kapatıldığı
iddia edilmez. Vault, Inbox, config, review, index veya maliyet kayıtlarına
yazılmadı; yeni model çağrısı ve yeni taslak oluşturulmadı.

## Ek uygulama ve yönlendirme kontrolü

Canlı panelin GitHub düğmesi `a8e7c990` main sürümünü, başarılı son main
koşusunu ve açık PR bulunmadığını gösterdi. “NEXUS projesinin GitHub durumunu
göster” isteği yerel kurallarla GitHub salt okunur önerisine yönlendirildi;
model rolü gerekmiyor, çalıştırma kapalı kaldı.

Ajan listesi yalnız sabit İngilizce isimleri tanıdığı için mevcut `yazar`,
`arastirmaci`, `kodcu` profilleri listede bulunmuyordu. Bu profillerin varlığı
Hermes'in salt okunur isim listesiyle doğrulandı. Bu bir profil silinmesi veya
ajanın kimliğinin/çalışmasının doğrulanması değildir.

Dar düzeltme yalnız bu üç alternatif profil adını destekler. Eski profil adı
da mevcutsa önce o kullanılır. Diğer özel profiller açığa çıkarılmaz; profil
config'i okunmaz, profil/ajan oluşturulmaz ve mesaj gönderilmez. Panelin
bağlantı izin listesi aynı üç adla genişletildi; rastgele veya dış URL'ye
bağlantı verilmez. Düzeltme kurulu eklentiye henüz alınmadı.

Yerel doğrulama: 370 Python + 17 panel testi, atlanan yok; JavaScript
sözdizimi ve diff kontrolü temiz. Yeni testler alternatif adları, eski ad
önceliğini, özel profil gizliliğini ve güvenli sohbet bağlantılarını kapsar.
