import tkinter as tk
from tkinter import messagebox
import threading
import asyncio

try:
    import discord
except ModuleNotFoundError:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "Eksik Kütüphane",
        "discord.py-self kütüphanesi yüklü değil.\n\n"
        "Lütfen terminalde aşağıdaki komutu çalıştırın:\n"
        "pip install discord.py-self PyNaCl"
    )
    root.destroy()
    raise

class DiscordVoiceBotApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Discord Çoklu Ses Bağlayıcı V4 - Ghost Join Sürümü")
        self.root.geometry("480x520")
        self.root.configure(padx=20, pady=20)

        # Başlık
        tk.Label(root, text="🚀 Gelişmiş Ses Bağlayıcı (Ghost)", font=("Helvetica", 16, "bold")).pack(pady=(0, 15))

        # Kanal ID Girişi
        tk.Label(root, text="Bağlanılacak Ses Kanalı ID'si:", font=("Helvetica", 10)).pack(anchor="w")
        self.channel_entry = tk.Entry(root, width=40, font=("Helvetica", 11))
        self.channel_entry.pack(pady=5, fill="x")

        # Token Girişi
        tk.Label(root, text="Tokenler (Her satıra BİR token girin):", font=("Helvetica", 10)).pack(anchor="w", pady=(10, 0))
        self.token_text = tk.Text(root, height=10, width=40, font=("Helvetica", 9))
        self.token_text.pack(pady=5, fill="both", expand=True)

        # Başlat Butonu
        self.start_btn = tk.Button(root, text="Sırayla Bağlanmaya Başla (1 Dk Ara İle)", 
                                   bg="#5865F2", fg="white", font=("Helvetica", 11, "bold"), 
                                   command=self.start_threads)
        self.start_btn.pack(pady=15, fill="x", ipady=5)

        # Log (Bilgi) Ekranı
        tk.Label(root, text="Sistem Durumu:", font=("Helvetica", 10)).pack(anchor="w")
        self.log_text = tk.Text(root, height=8, width=40, state=tk.DISABLED, bg="#2C2F33", fg="#FFFFFF", font=("Consolas", 9))
        self.log_text.pack(fill="x")

    def log(self, message):
        """Arayüzdeki log ekranına güvenli bir şekilde bilgi yazar (Thread-Safe)."""
        self.root.after(0, self._safe_log_update, message)

    def _safe_log_update(self, message):
        self.log_text.config(state=tk.NORMAL)
        self.log_text.insert(tk.END, f"[>] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.config(state=tk.DISABLED)

    def start_threads(self):
        """Butona basıldığında arka plan işlemini başlatır."""
        channel_id = self.channel_entry.get().strip()
        tokens = self.token_text.get("1.0", tk.END).strip().split('\n')

        if not channel_id or not channel_id.isdigit():
            messagebox.showerror("Hata", "Lütfen geçerli bir Kanal ID'si girin (sadece sayılar).")
            return

        # Boş satırları temizle
        tokens = [t.strip() for t in tokens if t.strip()]

        if not tokens:
            messagebox.showerror("Hata", "Lütfen en az bir tane token girin.")
            return

        self.start_btn.config(state=tk.DISABLED, text="Bağlanıyor... Lütfen Bekleyin")
        
        # İşlemleri arka plan thread'inde başlatıyoruz
        threading.Thread(target=self.run_bots, args=(tokens, channel_id), daemon=True).start()

    def run_bots(self, tokens, channel_id):
        """Asenkron Discord döngüsünü başlatır ve yaşatır."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(self.start_clients(tokens, channel_id))
        except Exception as e:
            self.log(f"Sistem Hatası: {str(e)}")
        finally:
            loop.close()

    async def start_clients(self, tokens, channel_id):
        """Hesapları sırayla ve gecikme ile bağlar, döngüyü açık tutar."""
        tasks = []

        for i, token in enumerate(tokens):
            self.log(f"Hesap {i+1}/{len(tokens)} için hazırlık yapılıyor...")
            
            client = discord.Client()
            self._bind_events(client, channel_id)
            tasks.append(asyncio.create_task(self._run_single_client(client, token, i+1)))
            
            if i < len(tokens) - 1:
                self.log("Hesap banı yememek için 60 saniye bekleniyor...")
                await asyncio.sleep(60)
        
        self.log("Tüm hesaplar için bağlanma talimatı verildi!")
        self.root.after(0, lambda: self.start_btn.config(text="Tüm İşlemler Aktif"))
        
        await asyncio.gather(*tasks)

    def _bind_events(self, client, channel_id):
        """Client nesnesine olayları (events) bağlar."""
        @client.event
        async def on_ready():
            self.log(f"Giriş Başarılı: {client.user.name}")
            channel = client.get_channel(int(channel_id))
            
            if channel:
                try:
                    # Sese girmeden önce insansı bir bekleme süresi (Discord'un algılamasını engeller)
                    self.log(f"-> {client.user.name} kanala hayalet giriş yapıyor...")
                    await asyncio.sleep(3)
                    
                    # İŞTE MUCİZE SATIR BURASI (Ghost Join)
                    # Ses sunucusuna bağlanmak yerine sadece Discord Gateway'e "durum" günceller
                    await channel.guild.change_voice_state(channel=channel, self_mute=True, self_deaf=True)
                    
                    self.log(f"✅ {client.user.name} sese kalıcı olarak oturdu (Ghost Mode).")
                except Exception as e:
                    self.log(f"❌ Ses Bağlantı Hatası ({client.user.name}): {str(e)}")
            else:
                self.log(f"HATA: {client.user.name} kanalı bulamadı (ID/Yetki kontrol et).")

    async def _run_single_client(self, client, token, index):
        """Tek bir botu çalıştırır ve hataları izole eder."""
        try:
            await client.start(token)
        except discord.errors.LoginFailure:
            self.log(f"Hata: Hesap {index} için token geçersiz!")
        except Exception as e:
            self.log(f"Beklenmeyen Hata (Hesap {index}): {str(e)}")

if __name__ == "__main__":
    root = tk.Tk()
    app = DiscordVoiceBotApp(root)
    root.mainloop()
