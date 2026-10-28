# 🛠️ Discord Token Manager (Ghost Joiner) - Kurulum Kılavuzu

Bu kılavuz, **Discord Token Manager** uygulamasını Windows ortamında hızlıca kurup çalıştırmanız için gereken adımları içerir.

---

## ⚡ 1. Hızlı Başlatma (Önerilen)

En kolay yöntem kök dizindeki başlatıcıyı kullanmaktır:

1. Klasördeki **`Baslat.bat`** dosyasına çift tıklayın.
2. Açılan menüden **`[2]`** tuşlayarak gerekli kütüphanelerin otomatik kurulmasını sağlayın.
3. Kurulum tamamlandıktan sonra menüden **`[1]`** seçeneğini seçerek arayüzü başlatın.

---

## 💻 2. Manuel Kurulum (Terminal / PowerShell)

Eğer komut satırı ile çalıştırmak isterseniz:

### Adım 1: Python Sürüm Kontrolü
Sisteminizde Python 3.9 veya daha yeni bir sürümün kurulu olduğundan emin olun:
```bash
python --version
```

### Adım 2: Sanal Ortam Oluşturma (İsteğe Bağlı ama Önerilir)
```bash
python -m venv .venv
.\.venv\Scripts\activate
```

### Adım 3: Bağımlılıkları Yükleme
```bash
pip install -r requirements.txt
```

### Adım 4: Uygulamayı Çalıştırma
```bash
python ghost_joiner.py
```

*(Yalnızca hafif ses botu modülünü açmak isterseniz: `python ses_botu.py`)*

---

## 🔒 Güvenlik Notu

- Tokenlarınız yerel SQLite veritabanında saklanır ve asla dışarı aktarılmaz.
- `.gitignore` dosyası tokenların veya veritabanının git geçmişine eklenmesini otomatik olarak engeller.
- Kişisel Discord tokenlarınızı kimseyle paylaşmayınız.
