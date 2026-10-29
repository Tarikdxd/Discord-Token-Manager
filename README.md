# Discord Token Manager

Birden fazla Discord hesabını tek bir masaüstü panelinden yönetmek için bir araç. Hesapların
durumunu gösterir, ses kanallarına bağlanır ve tokenların hâlâ geçerli olup olmadığını kontrol
eder.

## Özellikler

- Token sağlık kontrolü: kayıtlı tokenlar Discord API üzerinden doğrulanır.
- Hayalet ses bağlantısı: bir veya birden fazla tokenı seçilen ses kanalına bağlar, mute ve
  deafen durumlarını ayarlar, kanallar arasında dağıtır.
- Durum yönetimi: özel durum metni, dönen durumlar, sahte yayın ve sahte kamera görünümü.
- Tokenlar arayüzde ve loglarda maskelenir. Veriler yalnızca yerel `database.sqlite` dosyasında
  tutulur.
- Sistem tepsisi desteği ve düşük kaynak kullanan ayrı bir ses botu.

## Gereksinimler

- Python 3.9 veya üzeri
- Windows (başlatıcı betiği ve tepsi desteği Windows için yazıldı)

## Kurulum

Klasördeki `Baslat.bat` dosyasını çalıştırın:

1. `[2]` ile `requirements.txt` içindeki paketleri kurun.
2. `[1]` ile paneli açın.
3. `[3]` ile yalnızca ses botunu başlatın.

Elle kurulum:

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python ghost_joiner.py
```

## Dosyalar

| Dosya | Açıklama |
| --- | --- |
| `ghost_joiner.py` | CustomTkinter tabanlı yönetim paneli |
| `ses_botu.py` | Tkinter tabanlı hafif ses botu |
| `Baslat.bat` | Bağımlılık kurulumu ve menülü başlatıcı |

## Uyarı

Bu araç kullanıcı tokenlarıyla çalışır ve Discord Hizmet Şartları'na aykırı düşebilir. Hesap
askıya alınması riski kullanıcıya aittir.

## Lisans

MIT. Ayrıntılar için [LICENSE](LICENSE) dosyasına bakın.
