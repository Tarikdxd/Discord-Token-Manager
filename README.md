<div align="center">

# ⚡ Discord Token Manager & Ghost Joiner (v4.0)

**Modern, Güvenli ve Kapsamlı Çoklu Discord Hesap ve Ses Yönetim Paneli**

[![Python Version](https://img.shields.io/badge/Python-3.9%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![GUI](https://img.shields.io/badge/GUI-CustomTkinter-blueviolet)](https://github.com/TomSchimansky/CustomTkinter)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D6?logo=windows&logoColor=white)](https://microsoft.com/windows)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

*Birden fazla Discord hesabını tek bir modern kontrol panelinden yönetin, durumlarını senkronize edin, ses kanallarına hayalet modda (Ghost Join) bağlanın ve token sağlığını otomatik test edin.*

---

</div>

## ✨ Öne Çıkan Özellikler

- 🎨 **Modern CustomTkinter Arayüzü:** Koyu ve açık tema destekli, duyarlı ve şık masaüstü kontrol merkezi.
- 🎙️ **Hayalet Ses Bağlantısı (Ghost Join):** Tokenları hedef ses kanallarına gizlice bağlama, otomatik sessize alma (mute/deafen) ve kanallar arası rastgele dağıtım.
- 🩺 **Token Sağlık Taraması (Health Checker):** Ekli tüm tokenların canlılığını ve durumunu Discord API üzerinden anlık doğrulama.
- 🎭 **Zengin Durum & Aktivite Yönetimi:**
  - Özel durum mesajları (Custom Status: Çevrimiçi, Boşta, Rahatsız Etmeyin, Görünmez)
  - Otomatik dönen durum mesajları (Rotating Statuses)
  - Sahte yayın (Fake Stream) ve sahte kamera (Fake Video) simülasyonları
- 🛡️ **Gelişmiş Güvenlik ve Gizlilik:**
  - Tokenlar arayüzde ve loglarda maskelenir (`••••••••`).
  - Veriler tamamen yerel SQLite (`database.sqlite`) dosyasında tutulur, hiçbir 3. parti sunucuya gönderilmez.
- 📥 **Hızlı Başlatıcı:** `.venv` sanal ortamını ve kütüphaneleri otomatik kuran `Baslat.bat` menüsü.
- 📌 **Sistem Tepsisi (Tray) Desteği:** Arka planda sessizce çalışabilme.

---

## 📸 Arayüz & Mimari

| Modül | Açıklama |
| :--- | :--- |
| **`ghost_joiner.py`** | CustomTkinter tabanlı tam teşekküllü modern masaüstü yönetim paneli. |
| **`ses_botu.py`** | Kaynak tasarrufu sağlayan, doğrudan Tkinter tabanlı hafif ses botu aracı. |
| **`Baslat.bat`** | Otomatik bağımlılık yönetimi ve menülü başlatıcı. |

---

## 🚀 Hızlı Başlangıç

### 1. Depoyu Klonlayın
```bash
git clone https://github.com/Tarikdxd/Discord-Token-Manager.git
cd Discord-Token-Manager
```

### 2. Başlatıcıyı Çalıştırın
Klasör içerisindeki **`Baslat.bat`** dosyasına çift tıklayın:
1. `[2]` tuşuna basarak gerekli paketlerin kurulmasını sağlayın.
2. `[1]` tuşuna basarak uygulamayı açın.

### Manuel Kurulum (Opsiyonel)
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python ghost_joiner.py
```

Detaylı yönergeler için [Kurulum Kılavuzu](kurulum.md)'na göz atabilirsiniz.

---

## 📦 Gereksinimler

- **Python:** 3.9+
- **Kütüphaneler:**
  - `discord.py-self`
  - `customtkinter`
  - `Pillow`
  - `PyNaCl`
  - `requests`
  - `pystray`
  - `psutil`

---

## ⚠️ Sorumluluk Reddi (Disclaimer)

*Bu yazılım yalnızca eğitim ve kişisel otomasyon testleri amacıyla geliştirilmiştir. Discord Hizmet Şartları'na (ToS) uygunluk kullanıcının sorumluluğundadır. Geliştirici, yazılımın kötüye kullanımından sorumlu tutulamaz.*

---

## 📄 Lisans

Bu proje [MIT Lisansı](LICENSE) kapsamında lisanslanmıştır.
