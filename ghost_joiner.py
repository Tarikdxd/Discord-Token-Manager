import asyncio
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
import sqlite3
import base64
import os
import re
import json
import requests
import shutil
import random
import time
from datetime import datetime
from urllib.parse import urlparse

# --- GÜVENLİK SABİTLERİ ---
MAX_AVATAR_BYTES   = 8 * 1024 * 1024   # 8 MB (Discord limiti)
REQUEST_TIMEOUT    = 10                 # saniye
ALLOWED_IMG_EXT   = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
PROXY_RE           = re.compile(r'^(\d{1,3}\.){3}\d{1,3}:\d{2,5}$')  # IPv4:Port

# --- ANTİ-BAN SABİTLERİ ---
VOICE_JOIN_DELAY   = (3, 8)    # Ses girişi öncesi rastgele bekleme aralığı (sn)
ACTION_DELAY       = (1, 3)    # İşlemler arası insansı bekleme (sn)

# --- DB KİLİDİ ---
import threading as _threading
_db_lock = _threading.Lock()

def _sanitize_token(token):
    """Token'ın loglara sızmasını engeller — sadece ilk ve son 4 karakteri gösterir."""
    if not token or len(token) < 10:
        return '***'
    return token[:4] + '•' * (len(token) - 8) + token[-4:]

try:
    import customtkinter as ctk
    from PIL import Image, ImageTk, ImageDraw
    import discord
    import psutil
    import pystray
except ImportError as e:
    messagebox.showerror("Kütüphane Hatası", f"Gerekli kütüphaneler eksik.\nLütfen terminalden kurulum yapın.\n{e}")
    exit(1)

APP_START_TIME = time.time()

import sys

# Veritabanı Yapılandırması
if getattr(sys, 'frozen', False):
    # Eğer .exe olarak çalışıyorsa veritabanını exe'nin yanında tut
    DB_NAME = os.path.join(os.path.dirname(sys.executable), "database.sqlite")
else:
    DB_NAME = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database.sqlite")

def get_asset_path(filename):
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, "assets", filename)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("PRAGMA table_info(accounts)")
    columns = [col[1] for col in c.fetchall()]
    
    if not columns:
        c.execute('''CREATE TABLE IF NOT EXISTS accounts (
                 id INTEGER PRIMARY KEY AUTOINCREMENT, 
                 token TEXT UNIQUE, name TEXT, channel_id TEXT, 
                 is_muted INTEGER, is_deafened INTEGER, 
                 bio TEXT, avatar_type TEXT, avatar_data TEXT,
                 status_text TEXT, status_type TEXT, proxy TEXT,
                 fake_stream INTEGER, fake_video INTEGER,
                 afk_message TEXT DEFAULT '',
                 rotating_statuses TEXT DEFAULT '',
                 reactive_mode INTEGER DEFAULT 0)''')
    else:
        migrations = {
            'status_text': "TEXT DEFAULT ''", 'status_type': "TEXT DEFAULT 'Yok'",
            'proxy': "TEXT DEFAULT ''", 'fake_stream': "INTEGER DEFAULT 0",
            'fake_video': "INTEGER DEFAULT 0", 'afk_message': "TEXT DEFAULT ''",
            'rotating_statuses': "TEXT DEFAULT ''", 'reactive_mode': "INTEGER DEFAULT 0",
        }
        for col, typedef in migrations.items():
            if col not in columns:
                c.execute(f"ALTER TABLE accounts ADD COLUMN {col} {typedef}")
    
    conn.commit()
    conn.close()

def execute_query(query, params=(), fetch=False):
    """Thread-safe veritabanı sorgusu."""
    with _db_lock:
        conn = sqlite3.connect(DB_NAME)
        try:
            c = conn.cursor()
            c.execute(query, params)
            result = None
            if fetch:
                result = c.fetchall()
            conn.commit()
            return result
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

def get_accounts():
    rows = execute_query("SELECT id, token, name, channel_id, is_muted, is_deafened, bio, avatar_type, avatar_data, status_text, status_type, proxy, fake_stream, fake_video, afk_message, rotating_statuses, reactive_mode FROM accounts", fetch=True)
    accs = []
    for r in rows:
        accs.append({
            'id': r[0], 'token': r[1], 'name': r[2], 'channel_id': r[3], 'is_muted': r[4], 'is_deafened': r[5],
            'bio': r[6], 'avatar_type': r[7], 'avatar_data': r[8], 'status_text': r[9], 'status_type': r[10],
            'proxy': r[11], 'fake_stream': r[12], 'fake_video': r[13],
            'afk_message': r[14] or '', 'rotating_statuses': r[15] or '', 'reactive_mode': r[16] or 0
        })
    return accs

# Asenkron Bot Yöneticisi Sınıfı
class BotWorkerThread(threading.Thread):
    def __init__(self, log_callback, status_callback):
        super().__init__(daemon=True)
        self.loop = asyncio.new_event_loop()
        self.clients = {}  # token -> Client
        self.log_callback = log_callback
        self.status_callback = status_callback
        self.running_tasks = {}
        self._scatter_task = None
        self._scatter_active = False

        self.hype_active = False
        self.hype_channel = None
        self.hype_target = None
        self.hype_delay_sec = 10
        self.hype_quota = 5
        self.hype_emojis = ["🔥", "🎉", "👍", "❤️", "💯"]
        self._hyped_msg_ids = set()

    async def _execute_hype(self, channel_id, message_id):
        self.log_callback(f"⏳ Hype: Yöneticinin tepki atması için {self.hype_delay_sec} sn bekleniyor...")
        await asyncio.sleep(self.hype_delay_sec)
        
        active_clients = list(self.clients.values())
        if not active_clients: return
        
        # 1. Mesajı Yeniden Oku (Tepkileri toplamak için)
        emojis_to_add = []
        try:
            msg_data = await active_clients[0].http.get_message(channel_id, message_id)
            for r in msg_data.get('reactions', []):
                emo = r.get('emoji', {})
                if emo.get('id'):
                    emojis_to_add.append(f"{emo['name']}:{emo['id']}")
                else:
                    emojis_to_add.append(emo.get('name'))
        except Exception as e:
            self.log_callback(f"⚠️ Hype: Hedef mesaj doğrulanamadı: {e}")
            return
            
        # 2. Eğer üzerinde emoji yoksa, yedek (fallback) olanları kullan
        if not emojis_to_add:
            emojis_to_add = self.hype_emojis

        if not emojis_to_add:
            return
            
        # 3. Kotalı Bot Seçimi
        pool = random.sample(active_clients, min(len(active_clients), self.hype_quota))
        self.log_callback(f"🚀 Hype: {len(pool)} bot {len(emojis_to_add)} emojiyi göndermeye başlıyor (Gecikmeli)...")
        
        for client in pool:
            for emoji in emojis_to_add:
                try:
                    await client.http.add_reaction(channel_id, message_id, emoji)
                    await asyncio.sleep(random.uniform(1.5, 3.5))
                except Exception:
                    pass
        self.log_callback("✅ Hype Görevi Tamamlandı!")

    def run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run_coro(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop)

    async def _start_client(self, account):
        token = account['token']
        safe_token = _sanitize_token(token)
        if token in self.clients:
            self.log_callback(f"⚠️ {account['name']} zaten aktif!")
            return

        proxy_url = account['proxy'].strip() if account['proxy'] else None
        if proxy_url and not proxy_url.startswith("http"):
            proxy_url = f"http://{proxy_url}"
            
        client = discord.Client(proxy=proxy_url)
        self.clients[token] = client

        @client.event
        async def on_ready():
            uname = client.user.name if client.user else safe_token
            self.log_callback(f"✅ {uname} sisteme giriş yaptı! ({'Proxy: '+proxy_url if proxy_url else 'Kendi IPniz'})")
            self.status_callback(account['id'], "Bağlandı", "green")
            
            # --- STATUS / ACTIVITY (insansı gecikme ile) ---
            s_text = account['status_text']
            s_type = account['status_type']
            if s_text and s_type != 'Yok':
                await asyncio.sleep(random.uniform(*ACTION_DELAY))
                try:
                    act_type = discord.ActivityType.playing
                    if s_type == 'İzliyor': act_type = discord.ActivityType.watching
                    elif s_type == 'Dinliyor': act_type = discord.ActivityType.listening
                    
                    if s_type == 'Özel Durum':
                        await client.change_presence(activity=discord.CustomActivity(name=s_text))
                    else:
                        await client.change_presence(activity=discord.Activity(type=act_type, name=s_text))
                    self.log_callback(f"🌟 {uname} durumu ayarlandı: {s_type} {s_text}")
                except Exception as e:
                    self.log_callback(f"⚠️ {uname} durum ayarlanırken hata: {e}")

            # --- VOICE JOIN (rastgele insansı gecikme) ---
            channel_id = account['channel_id']
            if channel_id and channel_id.isdigit():
                channel = client.get_channel(int(channel_id))
                if channel:
                    join_delay = random.uniform(*VOICE_JOIN_DELAY)
                    self.log_callback(f"⏳ {uname} sesli kanala {join_delay:.1f} sn sonra bağlanacak...")
                    await asyncio.sleep(join_delay)
                    try:
                        mute = bool(account['is_muted'])
                        deaf = bool(account['is_deafened'])
                        f_stream = bool(account['fake_stream'])
                        f_video = bool(account['fake_video'])
                        
                        # Gateway OP 4 (Voice State Update) ile bağlan
                        # discord.py-self change_voice_state self_stream/self_video desteklemez
                        # Bu yüzden ham gateway paketi gönderiyoruz
                        payload = {
                            'op': 4,
                            'd': {
                                'guild_id': str(channel.guild.id),
                                'channel_id': str(channel.id),
                                'self_mute': mute,
                                'self_deaf': deaf,
                                'self_video': f_video,
                            }
                        }
                        await client.ws.send_as_json(payload)
                        
                        extra_log = []
                        if f_video: extra_log.append("Kamera Açık")
                        log_ext = f" ({', '.join(extra_log)})" if extra_log else ""
                        
                        self.log_callback(f"🎙️ {uname} Ghost Olarak Sese Oturdu!{log_ext}")
                        self.status_callback(account['id'], "Seste (Ghost Mod)", "green")
                        
                        # Sahte yayın (Stream) ayrı bir gateway çağrısı gerektirir
                        if f_stream:
                            await asyncio.sleep(random.uniform(1, 2))
                            try:
                                stream_payload = {
                                    'op': 18,
                                    'd': {
                                        'type': 'guild',
                                        'guild_id': str(channel.guild.id),
                                        'channel_id': str(channel.id),
                                        'preferred_region': None,
                                    }
                                }
                                await client.ws.send_as_json(stream_payload)
                                self.log_callback(f"📺 {uname} Sahte Yayın başlatıldı!")
                            except Exception as e:
                                self.log_callback(f"⚠️ {uname} Sahte Yayın başlatılamadı: {e}")
                        
                    except Exception as e:
                        self.log_callback(f"❌ {uname} sesli kanala katılırken hata: {str(e)}")
                else:
                    self.log_callback(f"❌ Kanal bulunamadı (ID: {channel_id}). Hesabın sunucuda olduğunu doğrulayın.")

            # --- AFK YANITLAYICI & HYPE MOTURU ---
            afk_msg = account.get('afk_message', '')
            client._afk_cooldown = {}
            
            @client.event
            async def on_message(message):
                if message.author == client.user:
                    return

                # Hype Modu Tetikleyicisi
                if self.hype_active:
                    cid = str(message.channel.id)
                    uid = str(message.author.id)
                    if cid == self.hype_channel and uid == self.hype_target:
                        mid = message.id
                        if mid not in self._hyped_msg_ids:
                            self._hyped_msg_ids.add(mid)
                            self.run_coro(self._execute_hype(message.channel.id, message.id))

                # AFK Yanıt Modu
                if afk_msg and isinstance(message.channel, discord.DMChannel):
                    uid = message.author.id
                    now = time.time()
                    if uid in client._afk_cooldown and (now - client._afk_cooldown[uid]) < 600:
                        return
                    client._afk_cooldown[uid] = now
                    try:
                        await asyncio.sleep(random.uniform(2, 5))
                        await message.channel.send(afk_msg)
                        self.log_callback(f"💬 {uname} → {message.author.name}'e AFK yanıtı gönderildi.")
                    except Exception:
                        pass

            # --- ANİMASYONLU DURUM (60sn döngü) ---
            rot_raw = account.get('rotating_statuses', '')
            if rot_raw.strip():
                lines = [l.strip() for l in rot_raw.strip().split('\n') if l.strip()]
                if lines:
                    async def _rotate_loop():
                        idx = 0
                        while client.is_ready():
                            line = lines[idx % len(lines)]
                            parts = line.split('|', 1)
                            s_type_r = parts[0].strip() if len(parts) > 1 else 'Özel Durum'
                            s_text_r = parts[1].strip() if len(parts) > 1 else parts[0].strip()
                            try:
                                if s_type_r == 'Özel Durum':
                                    await client.change_presence(activity=discord.CustomActivity(name=s_text_r))
                                else:
                                    at = discord.ActivityType.playing
                                    if s_type_r == 'İzliyor': at = discord.ActivityType.watching
                                    elif s_type_r == 'Dinliyor': at = discord.ActivityType.listening
                                    await client.change_presence(activity=discord.Activity(type=at, name=s_text_r))
                            except Exception:
                                pass
                            idx += 1
                            await asyncio.sleep(60)
                    client.loop.create_task(_rotate_loop())
                    self.log_callback(f"🔄 {uname} animasyonlu durum aktif ({len(lines)} durum)")

            # --- REAKTİF DAVRANIŞI ---
            if account.get('reactive_mode'):
                client._reactive_timer = None
                @client.event
                async def on_voice_state_update(member, before, after):
                    if member == client.user:
                        return
                    my_vc = client.user.voice
                    if not my_vc or not my_vc.channel:
                        return
                    my_ch = my_vc.channel
                    real_users = [m for m in my_ch.members if not m.bot and m != client.user]
                    guild = my_ch.guild
                    if after.channel == my_ch and len(real_users) > 0:
                        # Gerçek kullanıcı girdi → mute+deaf
                        if client._reactive_timer:
                            client._reactive_timer.cancel()
                            client._reactive_timer = None
                        payload = {'op': 4, 'd': {'guild_id': str(guild.id), 'channel_id': str(my_ch.id), 'self_mute': True, 'self_deaf': True, 'self_video': False}}
                        await client.ws.send_as_json(payload)
                    elif before.channel == my_ch and len(real_users) == 0:
                        # Son gerçek kullanıcı çıktı → 5dk sonra açılacak
                        async def _reopen():
                            await asyncio.sleep(300)
                            if client.is_ready() and client.user.voice and client.user.voice.channel == my_ch:
                                payload = {'op': 4, 'd': {'guild_id': str(guild.id), 'channel_id': str(my_ch.id), 'self_mute': False, 'self_deaf': False, 'self_video': False}}
                                await client.ws.send_as_json(payload)
                                self.log_callback(f"🛡️ {uname} reaktif mod: mikrofon açıldı (kanal boş)")
                        client._reactive_timer = client.loop.create_task(_reopen())

        @client.event
        async def on_disconnect():
            self.log_callback(f"🔌 {account['name']} bağlantı kesildi — Discord yeniden bağlanmayı deneyecek.")
            self.status_callback(account['id'], "Yeniden Bağlanıyor...", "orange")

        @client.event
        async def on_resumed():
            self.log_callback(f"🔄 {account['name']} yeniden bağlandı!")
            self.status_callback(account['id'], "Seste (Ghost Mod)", "green")

        try:
            self.status_callback(account['id'], "Bağlanıyor...", "orange")
            await client.start(token)
        except discord.errors.LoginFailure:
            self.log_callback(f"🔴 {account['name']} token geçersiz veya süresi dolmuş! ({safe_token})")
            self.status_callback(account['id'], "Token Geçersiz", "red")
            if token in self.clients:
                del self.clients[token]
        except Exception as e:
            err_msg = str(e)
            # Token'ın hata mesajına sızmasını engelle
            if token in err_msg:
                err_msg = err_msg.replace(token, safe_token)
            self.log_callback(f"🔴 {account['name']} bağlanamadı: {err_msg}")
            self.status_callback(account['id'], "Bağlantı Hatası", "red")
            if token in self.clients:
                del self.clients[token]

    async def _update_profile(self, client, account):
        payload = {}
        if account['bio']:
            payload['bio'] = account['bio']
            
        if account['avatar_type'] and account['avatar_type'] != 'Yok' and account['avatar_data']:
            try:
                if account['avatar_type'] == 'path':
                    # 🔒 Path traversal koruması: sadece izin verilen uzantılar
                    safe_path = os.path.realpath(account['avatar_data'])
                    ext = os.path.splitext(safe_path)[1].lower()
                    if ext not in ALLOWED_IMG_EXT:
                        raise ValueError(f"İzin verilmeyen dosya uzantısı: {ext}")
                    if not os.path.isfile(safe_path):
                        raise FileNotFoundError("Dosya bulunamadı.")
                    file_size = os.path.getsize(safe_path)
                    if file_size > MAX_AVATAR_BYTES:
                        raise ValueError(f"Dosya çok büyük ({file_size//1024//1024} MB). Maks 8 MB.")
                    with open(safe_path, "rb") as f:
                        img_bytes = f.read()
                elif account['avatar_type'] == 'url':
                    # 🔒 SSRF koruması: sadece http/https, yerel IP yasak
                    parsed = urlparse(account['avatar_data'])
                    if parsed.scheme not in ('http', 'https'):
                        raise ValueError("Sadece http/https URL'lerine izin verilir.")
                    host = parsed.hostname or ""
                    blocked = ('localhost', '127.', '0.0.0.0', '169.254.', '10.', '192.168.', '::1')
                    if any(host.startswith(b) or host == b.rstrip('.') for b in blocked):
                        raise ValueError("Yerel ağ adreslerine istek atılamaz.")
                    loop = asyncio.get_running_loop()
                    resp_bytes = await loop.run_in_executor(
                        None,
                        lambda: requests.get(account['avatar_data'], timeout=REQUEST_TIMEOUT, stream=True).content
                    )
                    if len(resp_bytes) > MAX_AVATAR_BYTES:
                        raise ValueError("URL'den indirilen resim 8 MB'ı aşıyor.")
                    img_bytes = resp_bytes
                
                b64_img = base64.b64encode(img_bytes).decode('ascii')
                payload['avatar'] = f"data:image/png;base64,{b64_img}"
            except Exception as e:
                self.log_callback(f"⚠️ {account['name']} Avatar ayarlanırken hata: {str(e)}")

        if payload:
            self.log_callback(f"⚙️ {client.user.name} Profil güncelleniyor...")
            try:
                await client.http.request(discord.http.Route('PATCH', '/users/@me'), json=payload)
                self.log_callback(f"✅ {client.user.name} Profil güncellendi!")
            except discord.errors.HTTPException as e:
                err_text = str(e)
                if "captcha" in err_text.lower():
                    self.log_callback(f"❌ {client.user.name} Discord Captcha İstiyor! Biyografi/PP şu an değiştirilemez.")
                else:
                    self.log_callback(f"❌ {client.user.name} Profil güncelleme hatası: {err_text}")
            except Exception as e:
                self.log_callback(f"❌ {client.user.name} Beklenmeyen profil hatası: {str(e)}")
        else:
            self.log_callback(f"⚠️ {client.user.name} güncellemek için Bio veya PP bilgisi eksik/boş.")

    def push_profile(self, account):
        token = account['token']
        if token in self.clients:
            self.run_coro(self._update_profile(self.clients[token], account))
        else:
            self.log_callback(f"⚠️ Önce {account['name']} hesabını 'Başlat' ile aktif edin, sonra 'Profili İşle' butonunu kullanın.")

    def start_bot(self, account):
        task = self.run_coro(self._start_client(account))
        self.running_tasks[account['token']] = task

    def stop_bot(self, account):
        token = account['token']
        if token in self.clients:
            client = self.clients.pop(token, None)
            if client:
                async def _safe_close():
                    try:
                        await client.close()
                    except Exception:
                        pass
                self.run_coro(_safe_close())
            self.log_callback(f"🛑 {account['name']} durduruldu.")
            self.status_callback(account['id'], "Durduruldu", "gray")

    # ============ KATEGORİ DAĞITIM (SCATTER) ============

    async def _move_client_to_channel(self, client, guild_id, channel_id, mute=True, deaf=True):
        """Bir client'ı belirli bir kanalda taşır (Gateway OP 4)."""
        payload = {
            'op': 4,
            'd': {
                'guild_id': str(guild_id),
                'channel_id': str(channel_id),
                'self_mute': mute,
                'self_deaf': deaf,
                'self_video': False,
            }
        }
        await client.ws.send_as_json(payload)

    async def _scatter_distribute(self, category_id):
        """
        Aktif botları bir kategorideki ses kanallarına 2-3'ünü bir gruba düşecek
        şekilde rastgele dağıtır.
        """
        if not self.clients:
            self.log_callback("⚠️ Dağıtım için önce hesapları 'Başlat' ile aktif edin.")
            return False

        # İlk aktif client üzerinden kategori kanallarını bul
        ref_client = next(iter(self.clients.values()))
        category = ref_client.get_channel(int(category_id))
        if not category:
            self.log_callback(f"❌ Kategori bulunamadı (ID: {category_id}). Hesapların o sunucuda olduğunu kontrol edin.")
            return False

        # Kategorideki sesli kanalları bul
        voice_channels = [ch for ch in category.channels if ch.type.value == 2]  # 2 = voice
        if not voice_channels:
            self.log_callback(f"❌ '{category.name}' kategorisinde hiç sesli kanal yok!")
            return False

        active_tokens = list(self.clients.keys())
        random.shuffle(active_tokens)
        random.shuffle(voice_channels)

        self.log_callback(f"🎲 {len(active_tokens)} hesap → {len(voice_channels)} kanal arasında dağıtılıyor...")

        # Her kanala 2-3 bot atanacak şekilde grupla
        assignments = []  # [(client, channel), ...]
        ch_idx = 0
        i = 0
        while i < len(active_tokens):
            ch = voice_channels[ch_idx % len(voice_channels)]
            group_size = random.choice([2, 3])
            for _ in range(group_size):
                if i >= len(active_tokens):
                    break
                assignments.append((active_tokens[i], ch))
                i += 1
            ch_idx += 1

        # Her botu atandığı kanala taşı
        guild_id = category.guild.id
        for token, ch in assignments:
            client = self.clients.get(token)
            if not client or not client.ws:
                continue
            try:
                await self._move_client_to_channel(client, guild_id, ch.id)
                uname = client.user.name if client.user else '?'
                self.log_callback(f"   ➡️ {uname} → #{ch.name}")
                await asyncio.sleep(random.uniform(1, 3))  # Anti-ban aralık
            except Exception as e:
                self.log_callback(f"   ❌ {token[:4]}... taşınamadı: {e}")

        self.log_callback(f"✅ Dağıtım tamamlandı! ({len(assignments)} hesap yerleştirildi)")
        return True

    async def _scatter_loop(self, category_id, interval_hours):
        """Belirtilen aralıkla botları yeniden karıştırır."""
        self._scatter_active = True
        interval_secs = interval_hours * 3600

        # İlk dağıtım
        ok = await self._scatter_distribute(category_id)
        if not ok:
            self._scatter_active = False
            return

        # Periyodik karıştırma döngüsü
        while self._scatter_active:
            self.log_callback(f"⏰ Sonraki karıştırma: {interval_hours} saat sonra...")
            await asyncio.sleep(interval_secs)
            if not self._scatter_active:
                break
            self.log_callback(f"🔄 Botlar yeniden karıştırılıyor...")
            await self._scatter_distribute(category_id)

    def start_scatter(self, category_id, interval_hours):
        if self._scatter_active:
            self.log_callback("⚠️ Kategori dağıtımı zaten aktif! Önce durdurun.")
            return
        self._scatter_task = self.run_coro(self._scatter_loop(category_id, interval_hours))

    def stop_scatter(self):
        self._scatter_active = False
        if self._scatter_task:
            self._scatter_task.cancel()
            self._scatter_task = None
        self.log_callback("🛑 Kategori dağıtımı durduruldu.")

class CustomApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Kanser TManager V4.0")
        self.geometry("1200x800")
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")
        
        init_db()

        self.bot_worker = BotWorkerThread(self.log, self.update_account_status)
        self.bot_worker.start()

        self.account_frames = {}
        self._tray_icon = None

        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)

        # -- Logo Yükleme --
        logo_path = get_asset_path("No Background Logo.png")
        pil_img = None
        try:
            pil_img = Image.open(logo_path)
            self.iconphoto(True, ImageTk.PhotoImage(pil_img))
        except Exception as e:
            pass

        # ---- SOL MENÜ (SIDEBAR) - Column 0 ----
        self.sidebar_frame = ctk.CTkFrame(self, width=220, corner_radius=0, fg_color="#2F3136")
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(12, weight=1)

        # Sidebar Logo & Title
        if pil_img:
            ctk_img = ctk.CTkImage(light_image=pil_img, size=(60, 60))
            self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="", image=ctk_img)
            self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 5))

        self.title_label = ctk.CTkLabel(self.sidebar_frame, text="Kanser TManager", font=ctk.CTkFont(size=18, weight="bold"), text_color="#FFFFFF")
        self.title_label.grid(row=1, column=0, padx=20, pady=0)
        
        self.dev_label = ctk.CTkLabel(self.sidebar_frame, text="Dev: Tarikdxd", font=ctk.CTkFont(size=11, slant="italic"), text_color="#B9BBBE")
        self.dev_label.grid(row=2, column=0, padx=20, pady=(0, 20))

        # Buton Stilleri
        btn_kwargs = {
            "width": 190, "height": 38, "corner_radius": 6, "anchor": "w", "font": ctk.CTkFont(size=13, weight="bold"),
            "fg_color": "transparent", "text_color": "#DCDDDE", "hover_color": "#393C43"
        }
        
        # Araçlar Başlığı
        ctk.CTkLabel(self.sidebar_frame, text="AĞ YÖNETİMİ", text_color="#8E9297", font=ctk.CTkFont(size=11, weight="bold")).grid(row=3, column=0, sticky="w", padx=25, pady=(10, 5))

        ctk.CTkButton(self.sidebar_frame, text="Yeni Hesap Ekle", command=self.open_add_account_window, **btn_kwargs).grid(row=4, column=0, pady=2, padx=15)
        
        ctk.CTkLabel(self.sidebar_frame, text="ARAÇLAR", text_color="#8E9297", font=ctk.CTkFont(size=11, weight="bold")).grid(row=5, column=0, sticky="w", padx=25, pady=(15, 5))
        
        ctk.CTkButton(self.sidebar_frame, text="Tokenları Test Et & Sil", command=self.open_token_checker, **btn_kwargs).grid(row=6, column=0, pady=2, padx=15)
        ctk.CTkButton(self.sidebar_frame, text="Ses Kanallarına Dağıt", command=self.open_scatter_modal, **btn_kwargs).grid(row=7, column=0, pady=2, padx=15)
        ctk.CTkButton(self.sidebar_frame, text="Seçililere İşlem Yap", command=self.open_bulk_modal, **btn_kwargs).grid(row=8, column=0, pady=2, padx=15)
        ctk.CTkButton(self.sidebar_frame, text="Otomatik Başlatma Saati", command=self.open_schedule_modal, **btn_kwargs).grid(row=9, column=0, pady=2, padx=15)
        ctk.CTkButton(self.sidebar_frame, text="Durum Taklit Et(Klon)", command=self.open_clone_modal, **btn_kwargs).grid(row=10, column=0, pady=2, padx=15)
        ctk.CTkButton(self.sidebar_frame, text="Sunucudaki İsimleri Değiş", command=self.open_nick_modal, **btn_kwargs).grid(row=11, column=0, pady=2, padx=15)
        
        # Hype action (highlighted)
        ctk.CTkButton(self.sidebar_frame, text="Mesajlara Oto-Emoji At",  command=self.open_hype_modal, width=190, height=38, corner_radius=6, anchor="w", font=ctk.CTkFont(size=13, weight="bold"), fg_color="#ED4245", hover_color="#C9383B", text_color="#FFFFFF").grid(row=12, column=0, pady=(10, 5), padx=15, sticky="n")
        
        # Bottom tools
        ctk.CTkButton(self.sidebar_frame, text="Veritabanı (VT) Yönetimi", command=self.open_db_modal, **btn_kwargs).grid(row=13, column=0, pady=(0, 20), padx=15, sticky="s")


        # ---- SAĞ İÇERİK (MAIN CONTENT) - Column 1 ----
        self.main_content = ctk.CTkFrame(self, corner_radius=0, fg_color="#36393F")
        self.main_content.grid(row=0, column=1, sticky="nsew")
        self.main_content.grid_rowconfigure(1, weight=1)
        self.main_content.grid_columnconfigure(0, weight=1)

        # Main Header (Actions)
        self.header_frame = ctk.CTkFrame(self.main_content, fg_color="#2F3136", height=60, corner_radius=8)
        self.header_frame.grid(row=0, column=0, sticky="ew", padx=20, pady=(20, 10))
        
        ctk.CTkLabel(self.header_frame, text="Sistem Durumu", font=ctk.CTkFont(size=15, weight="bold"), text_color="#FFFFFF").pack(side="left", padx=20, pady=15)

        self.start_all_btn = ctk.CTkButton(self.header_frame, text="Tüm Botları Başlat", fg_color="#5865F2", hover_color="#4752C4", command=self.start_all, font=ctk.CTkFont(weight="bold"))
        self.start_all_btn.pack(side="right", padx=20, pady=15)
        
        self.delay_frame = ctk.CTkFrame(self.header_frame, fg_color="transparent")
        self.delay_frame.pack(side="right", padx=10, pady=15)
        ctk.CTkLabel(self.delay_frame, text="Katılma Gecikmesi (sn):", font=ctk.CTkFont(size=12), text_color="#B9BBBE").pack(side="left", padx=(0, 5))
        self.delay_var = ctk.StringVar(value="3-8")
        ctk.CTkEntry(self.delay_frame, textvariable=self.delay_var, width=50, fg_color="#202225", border_width=0, text_color="#FFFFFF").pack(side="left")

        # Accounts List Frame
        self.scrollable_frame = ctk.CTkScrollableFrame(self.main_content, fg_color="#2F3136", corner_radius=8, label_text="Ekli Hesaplar", label_font=ctk.CTkFont(size=14, weight="bold"))
        self.scrollable_frame.grid(row=1, column=0, sticky="nsew", padx=20, pady=(0, 10))

        # ── Alt Panel: Console + Monitor ──
        self.bottom_frame = ctk.CTkFrame(self.main_content, fg_color="#2F3136", corner_radius=8)
        self.bottom_frame.grid(row=2, column=0, sticky="ew", padx=20, pady=(0, 20))
        self.bottom_frame.grid_columnconfigure(0, weight=3)
        self.bottom_frame.grid_columnconfigure(1, weight=1)

        self.console_frame = ctk.CTkFrame(self.bottom_frame)
        self.console_frame.grid(row=0, column=0, sticky="nsew", padx=(0,10))
        self.console_frame.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(self.console_frame, text="Sistem Logları", font=ctk.CTkFont(weight="bold")).grid(row=0, column=0, sticky="w", padx=10, pady=(5,0))
        self.console_text = ctk.CTkTextbox(self.console_frame, height=140, state="disabled")
        self.console_text.grid(row=1, column=0, sticky="ew", padx=10, pady=5)

        self.monitor_frame = ctk.CTkFrame(self.bottom_frame)
        self.monitor_frame.grid(row=0, column=1, sticky="nsew")
        ctk.CTkLabel(self.monitor_frame, text="📊 Monitör", font=ctk.CTkFont(weight="bold")).pack(pady=(5,3))
        self.mon_uptime = ctk.CTkLabel(self.monitor_frame, text="Uptime: 0s", font=ctk.CTkFont(size=11))
        self.mon_uptime.pack(anchor="w", padx=10)
        self.mon_bots = ctk.CTkLabel(self.monitor_frame, text="Aktif: 0 bot", font=ctk.CTkFont(size=11))
        self.mon_bots.pack(anchor="w", padx=10)
        self.mon_ram = ctk.CTkLabel(self.monitor_frame, text="RAM: 0 MB", font=ctk.CTkFont(size=11))
        self.mon_ram.pack(anchor="w", padx=10)
        self.mon_cpu = ctk.CTkLabel(self.monitor_frame, text="CPU: 0%", font=ctk.CTkFont(size=11))
        self.mon_cpu.pack(anchor="w", padx=10, pady=(0,5))

        self.load_accounts()
        self._update_monitor()
        self._setup_tray()

    # ── System Tray ──
    def _setup_tray(self):
        self.protocol("WM_DELETE_WINDOW", self._hide_to_tray)

    def _create_tray_icon_image(self):
        logo_path = get_asset_path("No Background Logo.png")
        try:
            img = Image.open(logo_path)
            return img.convert("RGBA")
        except Exception:
            pass
        # Fallback çizim
        img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse([4, 4, 60, 60], fill=(106, 27, 154))
        d.text((20, 18), "GJ", fill="white")
        return img

    def _hide_to_tray(self):
        self.withdraw()
        icon_img = self._create_tray_icon_image()
        menu = pystray.Menu(
            pystray.MenuItem("Göster", self._show_from_tray),
            pystray.MenuItem("Çıkış", self._exit_app)
        )
        self._tray_icon = pystray.Icon("KanserTManager", icon_img, "Kanser TManager V4.0", menu)
        threading.Thread(target=self._tray_icon.run, daemon=True).start()
        self.log("🌑 Uygulama sistem tepsisine küçültüldü.")

    def _show_from_tray(self, icon=None, item=None):
        if self._tray_icon:
            self._tray_icon.stop()
            self._tray_icon = None
        self.after(0, self.deiconify)

    def _exit_app(self, icon=None, item=None):
        if self._tray_icon:
            self._tray_icon.stop()
        self.after(0, self.destroy)

    # ── Monitor ──
    def _update_monitor(self):
        elapsed = int(time.time() - APP_START_TIME)
        h, m, s = elapsed // 3600, (elapsed % 3600) // 60, elapsed % 60
        self.mon_uptime.configure(text=f"Uptime: {h}s {m}dk {s}sn")
        self.mon_bots.configure(text=f"Aktif: {len(self.bot_worker.clients)} bot")
        proc = psutil.Process()
        ram_mb = proc.memory_info().rss / (1024 * 1024)
        cpu = proc.cpu_percent(interval=None)
        self.mon_ram.configure(text=f"RAM: {ram_mb:.1f} MB")
        self.mon_cpu.configure(text=f"CPU: {cpu:.1f}%")
        self.after(5000, self._update_monitor)

    def log(self, text):
        self.after(0, self._append_log, text)
    
    def _append_log(self, text):
        self.console_text.configure(state="normal")
        self.console_text.insert("end", f"> {text}\n")
        self.console_text.see("end")
        self.console_text.configure(state="disabled")

    def update_account_status(self, account_id, text, color):
        if account_id in self.account_frames:
            self.after(0, self.account_frames[account_id]['status_label'].configure, {"text": text, "text_color": color})

    def load_accounts(self):
        for widget in self.scrollable_frame.winfo_children():
            widget.destroy()
        self.account_frames = {}

        accounts = get_accounts()
        for acc in accounts:
            self.create_account_row(acc)

    def create_account_row(self, acc_dict):
        frame = ctk.CTkFrame(self.scrollable_frame)
        frame.pack(fill="x", pady=5, padx=5)

        info_label = ctk.CTkLabel(frame, text=f"👤 {acc_dict['name']}", font=ctk.CTkFont(weight="bold"))
        info_label.pack(side="left", padx=15, pady=10)

        channel_text = f"Kanal: {acc_dict['channel_id']}" if acc_dict['channel_id'] else "Kanal Yok"
        if acc_dict['proxy']: channel_text += " | 🌍 Proxyli"
        if acc_dict['fake_stream']: channel_text += " | 📺 Yayında"
        
        detail_label = ctk.CTkLabel(frame, text=channel_text)
        detail_label.pack(side="left", padx=15)

        status_label = ctk.CTkLabel(frame, text="Bekliyor", text_color="gray")
        status_label.pack(side="left", padx=15)

        # Buttons
        del_btn = ctk.CTkButton(frame, text="Sil", width=50, fg_color="#C62828", hover_color="#B71C1C", command=lambda: self.delete_account(acc_dict))
        del_btn.pack(side="right", padx=5)

        edit_btn = ctk.CTkButton(frame, text="Düzenle", width=70, fg_color="gray", hover_color="darkgray", command=lambda: self.open_add_account_window(acc_dict))
        edit_btn.pack(side="right", padx=5)

        stop_btn = ctk.CTkButton(frame, text="Durdur", width=70, fg_color="orange", hover_color="darkorange", command=lambda: self.bot_worker.stop_bot(acc_dict))
        stop_btn.pack(side="right", padx=5)
        
        push_btn = ctk.CTkButton(frame, text="Profili İşle", width=90, fg_color="#5E35B1", hover_color="#4527A0", command=lambda: self.bot_worker.push_profile(acc_dict))
        push_btn.pack(side="right", padx=5)

        start_btn = ctk.CTkButton(frame, text="Başlat", width=70, command=lambda: self.bot_worker.start_bot(acc_dict))
        start_btn.pack(side="right", padx=5)

        self.account_frames[acc_dict['id']] = {
            'frame': frame,
            'status_label': status_label
        }

    def delete_account(self, acc_dict):
        self.bot_worker.stop_bot(acc_dict)
        execute_query("DELETE FROM accounts WHERE id = ?", (acc_dict['id'],))
        self.log(f"🗑️ Hesap silindi: {acc_dict['name']}")
        self.load_accounts()

    def start_all(self):
        try:
            val = self.delay_var.get().replace(" ", "")
            if "-" in val:
                min_d, max_d = map(int, val.split("-"))
            else:
                min_d = max_d = int(val)
        except (ValueError, TypeError):
            min_d, max_d = 3, 8  # Geçersiz girişte güvenli varsayılan

        accounts = get_accounts()
        
        def staggered_start():
            for acc in accounts:
                if acc['token'] in self.bot_worker.clients: continue
                self.after(0, self.bot_worker.start_bot, acc)
                if min_d > 0 or max_d > 0:
                    wait_time = random.uniform(min_d, max_d)
                    self.log(f"⏱️ {acc['name']} işlemi için {wait_time:.1f} sn bekleniyor...")
                    time.sleep(wait_time)
                    
        threading.Thread(target=staggered_start, daemon=True).start()

    def open_add_account_window(self, existing_account=None):
        AccountModal(self, existing_account, callback=self.load_accounts)

    def open_db_modal(self):
        DatabaseModal(self, callback=self.load_accounts)

    def open_bulk_modal(self):
        BulkActionModal(self, callback=self.load_accounts)

    def open_scatter_modal(self):
        ScatterModal(self, self.bot_worker)

    def open_token_checker(self):
        TokenCheckerModal(self)

    def open_schedule_modal(self):
        ScheduleModal(self, self.bot_worker)

    def open_clone_modal(self):
        CloneModal(self, self.bot_worker)

    def open_nick_modal(self):
        NicknameModal(self, self.bot_worker)

    def open_hype_modal(self):
        HypeModal(self, self.bot_worker)

class AccountModal(ctk.CTkToplevel):
    def __init__(self, parent, account=None, callback=None):
        super().__init__(parent)
        self.title("Hesap Düzenle" if account else "Yeni Hesap Ekle")
        self.geometry("600x800")
        self.geometry("+%d+%d" % (parent.winfo_rootx() + 50, parent.winfo_rooty() + 50))
        self.grab_set()

        self.account = account
        self.callback = callback
        
        self.avatar_type_var = ctk.StringVar(value=account['avatar_type'] if account and account['avatar_type'] else "Yok")
        self.avatar_data_var = ctk.StringVar(value=account['avatar_data'] if account and account['avatar_data'] else "")
        self.status_type_var = ctk.StringVar(value=account['status_type'] if account and account['status_type'] else "Yok")

        # Scrollable content frame
        self.cframe = ctk.CTkScrollableFrame(self)
        self.cframe.pack(fill="both", expand=True, padx=20, pady=20)

        # Temel Bilgiler
        ctk.CTkLabel(self.cframe, text="Hesap Adı / Alias:").pack(anchor="w")
        self.name_entry = ctk.CTkEntry(self.cframe, width=350)
        self.name_entry.pack(anchor="w", pady=(0, 10))

        ctk.CTkLabel(self.cframe, text="Token:").pack(anchor="w")
        token_frame = ctk.CTkFrame(self.cframe, fg_color="transparent")
        token_frame.pack(anchor="w", fill="x", pady=(0, 10))
        self.token_entry = ctk.CTkEntry(token_frame, width=310, show="•")
        self.token_entry.pack(side="left")
        self._token_visible = False
        self._toggle_token_btn = ctk.CTkButton(token_frame, text="👁", width=30,
            command=self._toggle_token_vis)
        self._toggle_token_btn.pack(side="left", padx=5)

        ctk.CTkLabel(self.cframe, text="Ses Kanalı ID'si:").pack(anchor="w")
        self.channel_entry = ctk.CTkEntry(self.cframe, width=350)
        self.channel_entry.pack(anchor="w", pady=(0, 10))

        # Proxy Alanı
        ctk.CTkLabel(self.cframe, text="Proxy (IP:Port):", text_color="orange").pack(anchor="w")
        proxy_pf = ctk.CTkFrame(self.cframe, fg_color="transparent")
        proxy_pf.pack(anchor="w", fill="x", pady=(0, 15))
        self.proxy_entry = ctk.CTkEntry(proxy_pf, width=220, placeholder_text="Boş kalabilir")
        self.proxy_entry.pack(side="left")
        ctk.CTkButton(proxy_pf, text="🌍 Oto Doldur", width=100, command=self.auto_proxy).pack(side="left", padx=10)

        # Durum Alanı
        ctk.CTkLabel(self.cframe, text="Aktivite Durumu (Oynuyor vs.):").pack(anchor="w")
        status_pf = ctk.CTkFrame(self.cframe, fg_color="transparent")
        status_pf.pack(anchor="w", fill="x", pady=(0, 10))
        self.status_menu = ctk.CTkOptionMenu(status_pf, values=["Yok", "Oynuyor", "İzliyor", "Dinliyor", "Özel Durum"], variable=self.status_type_var)
        self.status_menu.pack(side="left")
        self.status_text_entry = ctk.CTkEntry(status_pf, width=200, placeholder_text="Durum metni...")
        self.status_text_entry.pack(side="left", padx=10)

        # Mute / Deaf / Fake Stream
        checks_f = ctk.CTkFrame(self.cframe, fg_color="transparent")
        checks_f.pack(anchor="w", fill="x", pady=(10, 15))
        
        self.mute_var = ctk.IntVar(value=account['is_muted'] if account else 1)
        self.deaf_var = ctk.IntVar(value=account['is_deafened'] if account else 1)
        self.stream_var = ctk.IntVar(value=account['fake_stream'] if account and 'fake_stream' in account else 0)
        self.video_var = ctk.IntVar(value=account['fake_video'] if account and 'fake_video' in account else 0)
        self.reactive_var = ctk.IntVar(value=account['reactive_mode'] if account else 0)

        ctk.CTkCheckBox(checks_f, text="Mute", variable=self.mute_var).grid(row=0, column=0, padx=5, pady=5, sticky="w")
        ctk.CTkCheckBox(checks_f, text="Deafen", variable=self.deaf_var).grid(row=0, column=1, padx=20, pady=5, sticky="w")
        ctk.CTkCheckBox(checks_f, text="Sahte Yayın (Stream)", variable=self.stream_var).grid(row=1, column=0, padx=5, pady=5, sticky="w")
        ctk.CTkCheckBox(checks_f, text="Kamera Açık (Video)", variable=self.video_var).grid(row=1, column=1, padx=20, pady=5, sticky="w")
        ctk.CTkCheckBox(checks_f, text="🛡️ Reaktif Mod", variable=self.reactive_var).grid(row=2, column=0, padx=5, pady=5, sticky="w", columnspan=2)

        # Bio 
        ctk.CTkLabel(self.cframe, text="Bio (Hakkımda):").pack(anchor="w")
        self.bio_entry = ctk.CTkEntry(self.cframe, width=350)
        self.bio_entry.pack(anchor="w", pady=(0, 10))

        # AFK Yanıtlayıcı
        ctk.CTkLabel(self.cframe, text="💬 AFK Mesajı (DM yanıtı):").pack(anchor="w")
        self.afk_entry = ctk.CTkEntry(self.cframe, width=350, placeholder_text="Boş = kapalı")
        self.afk_entry.pack(anchor="w", pady=(0, 10))

        # Dönen Durumlar
        ctk.CTkLabel(self.cframe, text="🔄 Animasyonlu Durumlar (her satır 60sn):", text_color="#80CBC4").pack(anchor="w")
        ctk.CTkLabel(self.cframe, text="Format: Tip|Metin  (Örn: Oynuyor|Valorant)", font=ctk.CTkFont(size=10), text_color="gray").pack(anchor="w")
        self.rot_text = ctk.CTkTextbox(self.cframe, height=80, width=350)
        self.rot_text.pack(anchor="w", pady=(0, 15))

        # Avatar
        ctk.CTkLabel(self.cframe, text="Profil Resmi (PP):", font=ctk.CTkFont(weight="bold")).pack(anchor="w")
        pp_frame = ctk.CTkFrame(self.cframe, fg_color="transparent")
        pp_frame.pack(anchor="w", fill="x", pady=(0, 10))

        self.radio_none = ctk.CTkRadioButton(pp_frame, text="Değiştirme", variable=self.avatar_type_var, value="Yok", command=self.update_pp_ui)
        self.radio_none.pack(side="left", padx=(0, 10))
        self.radio_file = ctk.CTkRadioButton(pp_frame, text="Dosya", variable=self.avatar_type_var, value="path", command=self.update_pp_ui)
        self.radio_file.pack(side="left", padx=10)
        self.radio_url = ctk.CTkRadioButton(pp_frame, text="URL", variable=self.avatar_type_var, value="url", command=self.update_pp_ui)
        self.radio_url.pack(side="left", padx=10)

        self.dynamic_pp_frame = ctk.CTkFrame(self.cframe, fg_color="transparent")
        self.dynamic_pp_frame.pack(anchor="w", fill="x")
        self.url_entry = ctk.CTkEntry(self.dynamic_pp_frame, width=300, placeholder_text="Resim URL")
        self.file_btn = ctk.CTkButton(self.dynamic_pp_frame, text="Dosya Seç...", command=self.browse_image)
        self.file_label = ctk.CTkLabel(self.dynamic_pp_frame, text="Seçilmedi", text_color="gray")

        self.update_pp_ui()
        self._finish_init(account)

    def _toggle_token_vis(self):
        self._token_visible = not self._token_visible
        self.token_entry.configure(show="" if self._token_visible else "•")
        self._toggle_token_btn.configure(text="🙈" if self._token_visible else "👁")

    def _finish_init(self, account):
        """Called at end of __init__ to add save button and prefill data."""
        self.save_btn = ctk.CTkButton(self.cframe, text="Kaydet", fg_color="#4CAF50", hover_color="#388E3C", command=self.save)
        self.save_btn.pack(pady=30)

        if account:
            self.name_entry.insert(0, account['name'] or "")
            self.token_entry.insert(0, account['token'] or "")
            self.channel_entry.insert(0, account['channel_id'] or "")
            self.proxy_entry.insert(0, account['proxy'] or "")
            self.bio_entry.insert(0, account['bio'] or "")
            self.status_text_entry.insert(0, account['status_text'] or "")
            self.afk_entry.insert(0, account.get('afk_message', '') or "")
            rot = account.get('rotating_statuses', '') or ''
            if rot:
                self.rot_text.insert('1.0', rot)

            if account['avatar_type'] == 'url':
                self.url_entry.insert(0, account['avatar_data'])
            elif account['avatar_type'] == 'path':
                self.file_label.configure(text=account['avatar_data'])

    def auto_proxy(self):
        def fetch():
            try:
                r = requests.get(
                    "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=yes&anonymity=elite",
                    timeout=REQUEST_TIMEOUT
                )
                # 🔒 Sadece geçerli IP:Port formatına sahip proxy'leri kabul et
                raw = r.text.strip().split()
                prx_list = [p for p in raw if PROXY_RE.match(p.strip())]
                if prx_list:
                    selected = random.choice(prx_list)
                    self.proxy_entry.delete(0, 'end')
                    self.proxy_entry.insert(0, selected)
                    messagebox.showinfo("Başarılı", f"Rastgele proxy atandı:\n{selected}")
                else:
                    messagebox.showwarning("Bulunamadı", "Geçerli formattta Proxy Bulunamadı!")
            except requests.Timeout:
                messagebox.showerror("Zaman Aşımı", "Proxy listesi alınamadı: Bağlantı zaman aşımına uğradı.")
            except Exception as e:
                messagebox.showerror("Hata", f"Proxy çekerken hata: {str(e)}")
        threading.Thread(target=fetch, daemon=True).start()

    def update_pp_ui(self):
        sel = self.avatar_type_var.get()
        self.url_entry.pack_forget()
        self.file_btn.pack_forget()
        self.file_label.pack_forget()

        if sel == "url":
            self.url_entry.pack(anchor="w", pady=5)
        elif sel == "path":
            self.file_btn.pack(anchor="w", pady=5)
            self.file_label.pack(anchor="w")

    def browse_image(self):
        filepath = filedialog.askopenfilename(filetypes=[("Image", "*.png *.jpg *.jpeg *.gif")])
        if filepath:
            self.avatar_data_var.set(filepath)
            self.file_label.configure(text=os.path.basename(filepath))

    def save(self):
        name = self.name_entry.get().strip()
        token = self.token_entry.get().strip()
        channel_id = self.channel_entry.get().strip()
        is_muted = self.mute_var.get()
        is_deaf = self.deaf_var.get()
        f_stream = self.stream_var.get()
        f_video = self.video_var.get()
        reactive = self.reactive_var.get()
        proxy = self.proxy_entry.get().strip()
        s_type = self.status_type_var.get()
        s_text = self.status_text_entry.get().strip()[:128]
        bio = self.bio_entry.get().strip()[:190]
        afk_msg = self.afk_entry.get().strip()[:200]
        rot_statuses = self.rot_text.get('1.0', 'end').strip()
        a_type = self.avatar_type_var.get()
        
        a_data = ""
        if a_type == "url": a_data = self.url_entry.get().strip()
        elif a_type == "path": a_data = self.avatar_data_var.get().strip()
        if a_type != "Yok" and not a_data: a_type = "Yok"

        if not token or not name:
            messagebox.showerror("Hata", "Ad ve Token zorunludur.")
            return
        if proxy and not PROXY_RE.match(proxy):
            messagebox.showerror("Hata", "Proxy formatı geçersiz. Doğru format: 1.2.3.4:8080")
            return
        if channel_id and not channel_id.isdigit():
            messagebox.showerror("Hata", "Kanal ID yalnızca rakamlardan oluşmalıdır.")
            return

        if self.account:
            execute_query("UPDATE accounts SET token=?, name=?, channel_id=?, is_muted=?, is_deafened=?, bio=?, avatar_type=?, avatar_data=?, status_text=?, status_type=?, proxy=?, fake_stream=?, fake_video=?, afk_message=?, rotating_statuses=?, reactive_mode=? WHERE id=?", 
                        (token, name, channel_id, is_muted, is_deaf, bio, a_type, a_data, s_text, s_type, proxy, f_stream, f_video, afk_msg, rot_statuses, reactive, self.account['id']))
        else:
            execute_query("INSERT INTO accounts (token, name, channel_id, is_muted, is_deafened, bio, avatar_type, avatar_data, status_text, status_type, proxy, fake_stream, fake_video, afk_message, rotating_statuses, reactive_mode) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (token, name, channel_id, is_muted, is_deaf, bio, a_type, a_data, s_text, s_type, proxy, f_stream, f_video, afk_msg, rot_statuses, reactive))

        if self.callback: self.callback()
        self.destroy()

class BulkActionModal(ctk.CTkToplevel):
    def __init__(self, parent, callback=None):
        super().__init__(parent)
        self.title("Seçililere İşlem Yap")
        self.geometry("450x650")
        self.geometry("+%d+%d" % (parent.winfo_rootx() + 80, parent.winfo_rooty() + 50))
        self.grab_set()

        self.parent_app = parent
        
        accounts = get_accounts()
        self.checkboxes = {}

        # Üst Panel: Seçim 
        sf = ctk.CTkFrame(self, fg_color="transparent")
        sf.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(sf, text="İşlem Yapılacak Hesapları Seçin:", font=ctk.CTkFont(weight="bold")).pack(side="left")
        
        def toggle_all():
            for cb in self.checkboxes.values():
                if cb.get(): cb.deselect()
                else: cb.select()
                
        ctk.CTkButton(sf, text="Tümünü Seç / Bırak", width=120, command=toggle_all).pack(side="right")
        
        # Scrollable Hesap Listesi
        self.ac_frame = ctk.CTkScrollableFrame(self, height=180)
        self.ac_frame.pack(fill="x", padx=20, pady=5)
        
        for acc in accounts:
            cb = ctk.CTkCheckBox(self.ac_frame, text=acc['name'])
            cb.pack(anchor="w", pady=2)
            cb.select() # Default selected
            self.checkboxes[acc['id']] = cb

        # Kanal
        self.ch_tick = ctk.CTkCheckBox(self, text="Kanal ID'yi Değiştir:", width=150)
        self.ch_tick.pack(anchor="w", padx=20, pady=5)
        self.ch_val = ctk.CTkEntry(self, width=200)
        self.ch_val.pack(anchor="w", padx=40, pady=(0,10))

        # Proxy
        self.pr_tick = ctk.CTkCheckBox(self, text="Proxy Değiştir/Ekle:", width=150)
        self.pr_tick.pack(anchor="w", padx=20, pady=5)
        
        pf = ctk.CTkFrame(self, fg_color="transparent")
        pf.pack(anchor="w", padx=40, pady=(0,10))
        self.pr_val = ctk.CTkEntry(pf, width=150, placeholder_text="boş bırakırsanız siler")
        self.pr_val.pack(side="left")
        ctk.CTkButton(pf, text="Oto", width=40, command=self.auto_prx).pack(side="left", padx=5)

        # Mute / Deaf
        self.mt_tick = ctk.CTkCheckBox(self, text="Ses Mute/Deaf Değiştir:")
        self.mt_tick.pack(anchor="w", padx=20, pady=5)
        mf = ctk.CTkFrame(self, fg_color="transparent")
        mf.pack(anchor="w", padx=40, pady=(0,10))
        self.m_var = ctk.IntVar(value=1)
        self.d_var = ctk.IntVar(value=1)
        ctk.CTkCheckBox(mf, text="Mute", variable=self.m_var, width=70).pack(side="left", padx=5)
        ctk.CTkCheckBox(mf, text="Deafen", variable=self.d_var, width=70).pack(side="left", padx=5)

        # Stream / Video
        self.st_tick = ctk.CTkCheckBox(self, text="Yayın/Kamera Değiştir:")
        self.st_tick.pack(anchor="w", padx=20, pady=5)
        sf2 = ctk.CTkFrame(self, fg_color="transparent")
        sf2.pack(anchor="w", padx=40, pady=(0,10))
        self.str_var = ctk.IntVar(value=0)
        self.vid_var = ctk.IntVar(value=0)
        ctk.CTkCheckBox(sf2, text="Sahte Yayın", variable=self.str_var, width=100).pack(side="left", padx=5)
        ctk.CTkCheckBox(sf2, text="Kamera Aç", variable=self.vid_var, width=100).pack(side="left", padx=5)

        ctk.CTkButton(self, text="Seçili Hesaplara Uygula", fg_color="#C62828", hover_color="#B71C1C", command=self.apply).pack(pady=15)
        
    def auto_prx(self):
        try:
            r = requests.get(
                "https://api.proxyscrape.com/v2/?request=displayproxies&protocol=http&timeout=5000&country=all&ssl=yes&anonymity=elite",
                timeout=REQUEST_TIMEOUT
            )
            raw = r.text.strip().split()
            p = [x for x in raw if PROXY_RE.match(x.strip())]
            if p:
                self.pr_val.delete(0, 'end')
                self.pr_val.insert(0, random.choice(p))
        except Exception:
            pass

    def apply(self):
        selected_ids = [aid for aid, cb in self.checkboxes.items() if cb.get()]
        if not selected_ids:
            messagebox.showwarning("Uyarı", "Lütfen en az bir hesap seçin.")
            return

        if not messagebox.askyesno("Onay", f"Seçili {len(selected_ids)} hesabın özellikleri güncellenecek. Emin misiniz?"): return
        
        updates = []
        params = []
        
        if self.ch_tick.get():
            updates.append("channel_id=?")
            params.append(self.ch_val.get().strip())
        
        if self.pr_tick.get():
            updates.append("proxy=?")
            params.append(self.pr_val.get().strip())
            
        if self.mt_tick.get():
            updates.append("is_muted=?")
            updates.append("is_deafened=?")
            params.append(self.m_var.get())
            params.append(self.d_var.get())
            
        if self.st_tick.get():
            updates.append("fake_stream=?")
            updates.append("fake_video=?")
            params.append(self.str_var.get())
            params.append(self.vid_var.get())
            
        if not updates:
            messagebox.showwarning("Uyarı", "Değiştirmek için hiçbir özellik işaretlemediniz.")
            return
            
        set_clause = ", ".join(updates)
        placeholders = ",".join("?" * len(selected_ids))
        
        query = f"UPDATE accounts SET {set_clause} WHERE id IN ({placeholders})"
        full_params = params + selected_ids

        with _db_lock:
            conn = sqlite3.connect(DB_NAME)
            c = conn.cursor()
            c.execute(query, full_params)
            conn.commit()
            conn.close()
            
        self.parent_app.log(f"⚡ {len(selected_ids)} Hesap için özellikler başarıyla güncellendi.")
        self.parent_app.load_accounts()
        self.destroy()

class DatabaseModal(ctk.CTkToplevel):
    def __init__(self, parent, callback=None):
        super().__init__(parent)
        self.title("Veritabanı Yönetimi")
        self.geometry("400x320")
        self.geometry("+%d+%d" % (parent.winfo_rootx() + 100, parent.winfo_rooty() + 100))
        self.grab_set()
        self.callback = callback
        
        ctk.CTkLabel(self, text="Veritabanı (SQLite) İşlemleri", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=20)
        btn_backup = ctk.CTkButton(self, text="💾 Veritabanını Yedekle", command=self.backup_db)
        btn_backup.pack(pady=10, fill="x", padx=40)
        btn_restore = ctk.CTkButton(self, text="📂 Veritabanını Geri Yükle", command=self.restore_db)
        btn_restore.pack(pady=10, fill="x", padx=40)
        btn_clear = ctk.CTkButton(self, text="⚠️ Tüm Hesapları Temizle", fg_color="#C62828", hover_color="#B71C1C", command=self.clear_db)
        btn_clear.pack(pady=10, fill="x", padx=40)
        
    def backup_db(self):
        filepath = filedialog.asksaveasfilename(defaultextension=".sqlite", filetypes=[("SQLite Database", "*.sqlite")], initialfile="database_yedek.sqlite")
        if filepath:
            try:
                shutil.copy2(DB_NAME, filepath)
                messagebox.showinfo("Başarılı", "Yedeklendi.")
            except Exception as e: messagebox.showerror("Hata", str(e))

    def restore_db(self):
        filepath = filedialog.askopenfilename(filetypes=[("SQLite Database", "*.sqlite")])
        if filepath and messagebox.askyesno("Onay", "Tüm veriler silinip yedek yüklenecek. Onaylıyor musunuz?"):
            try:
                shutil.copy2(filepath, DB_NAME)
                if self.callback: self.callback()
                messagebox.showinfo("Başarılı", "Geri yüklendi.")
                self.destroy()
            except Exception as e: messagebox.showerror("Hata", str(e))
                    
    def clear_db(self):
        if messagebox.askyesno("Kritik Onay", "Tüm hesaplar SİLİNECEK! Emin misiniz?"):
            execute_query("DELETE FROM accounts")
            if self.callback: self.callback()
            messagebox.showinfo("Başarılı", "Temizlendi.")
            self.destroy()

class ScatterModal(ctk.CTkToplevel):
    def __init__(self, parent, bot_worker):
        super().__init__(parent)
        self.title("🎲 Kategoriye Dağıt (Scatter Mode)")
        self.geometry("450x380")
        self.geometry("+%d+%d" % (parent.winfo_rootx() + 100, parent.winfo_rooty() + 100))
        self.grab_set()
        self.bot_worker = bot_worker

        ctk.CTkLabel(self, text="Kategoriye Dağıtım", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=15)

        ctk.CTkLabel(self, text="Hesaplar, seçtiğiniz ses kategorisindeki kanallara\n2-3'lü gruplar halinde rastgele dağıtılır.\nBelirli aralıklarla otomatik karıştırılır.",
                     text_color="gray", justify="center").pack(pady=(0, 15))

        ctk.CTkLabel(self, text="Ses Kategori ID'si:").pack(anchor="w", padx=30)
        self.cat_entry = ctk.CTkEntry(self, width=250, placeholder_text="Kategori ID (sağ tık → ID kopyala)")
        self.cat_entry.pack(anchor="w", padx=30, pady=(0, 15))

        ctk.CTkLabel(self, text="Karıştırma Aralığı (saat):").pack(anchor="w", padx=30)
        self.interval_var = ctk.StringVar(value="2")
        self.interval_entry = ctk.CTkEntry(self, width=100, textvariable=self.interval_var)
        self.interval_entry.pack(anchor="w", padx=30, pady=(0, 20))

        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.pack(fill="x", padx=30, pady=10)

        self.start_btn = ctk.CTkButton(btn_frame, text="▶️ Dağıtımı Başlat", fg_color="#2E7D32", hover_color="#1B5E20", command=self.start)
        self.start_btn.pack(side="left", expand=True, fill="x", padx=(0, 5))

        self.stop_btn = ctk.CTkButton(btn_frame, text="⏹️ Durdur", fg_color="#C62828", hover_color="#B71C1C", command=self.stop)
        self.stop_btn.pack(side="right", expand=True, fill="x", padx=(5, 0))

        self.now_btn = ctk.CTkButton(self, text="🔀 Şimdi Karıştır (Anında)", fg_color="#E65100", hover_color="#BF360C", command=self.shuffle_now)
        self.now_btn.pack(fill="x", padx=30, pady=(5, 10))

    def start(self):
        cat_id = self.cat_entry.get().strip()
        if not cat_id or not cat_id.isdigit():
            messagebox.showerror("Hata", "Geçerli bir Kategori ID'si girin (sadece rakam).")
            return
        try:
            interval = float(self.interval_var.get())
            if interval <= 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Hata", "Karıştırma aralığı 0'dan büyük bir sayı olmalı.")
            return

        self.bot_worker.start_scatter(cat_id, interval)
        messagebox.showinfo("Başlatıldı", f"Botlar {cat_id} kategorisine dağıtılıyor.\nHer {interval} saatte bir yeniden karıştırılacak.")
        self.destroy()

    def stop(self):
        self.bot_worker.stop_scatter()
        messagebox.showinfo("Durduruldu", "Kategori dağıtımı durduruldu.")
        self.destroy()

    def shuffle_now(self):
        cat_id = self.cat_entry.get().strip()
        if not cat_id or not cat_id.isdigit():
            messagebox.showerror("Hata", "Geçerli bir Kategori ID'si girin.")
            return
        self.bot_worker.run_coro(self.bot_worker._scatter_distribute(cat_id))

class TokenCheckerModal(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("🩺 Token Sağlık Taraması")
        self.geometry("550x500")
        self.geometry("+%d+%d" % (parent.winfo_rootx() + 80, parent.winfo_rooty() + 80))
        self.grab_set()
        self.parent_app = parent
        self.results = []

        ctk.CTkLabel(self, text="Token Sağlık Kontrolü", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=10)
        ctk.CTkLabel(self, text="Tüm hesapların tokenlarını Discord API ile doğrular.", text_color="gray").pack()

        self.result_box = ctk.CTkTextbox(self, height=300, state="disabled")
        self.result_box.pack(fill="both", expand=True, padx=20, pady=10)

        btn_f = ctk.CTkFrame(self, fg_color="transparent")
        btn_f.pack(fill="x", padx=20, pady=10)
        ctk.CTkButton(btn_f, text="▶ Taramayı Başlat", fg_color="#2E7D32", command=self.run_check).pack(side="left", expand=True, fill="x", padx=(0,5))
        self.del_btn = ctk.CTkButton(btn_f, text="🗑️ Geçersizleri Sil", fg_color="#C62828", hover_color="#B71C1C", command=self.delete_invalid, state="disabled")
        self.del_btn.pack(side="right", expand=True, fill="x", padx=(5,0))

    def _log(self, msg):
        self.result_box.configure(state="normal")
        self.result_box.insert("end", msg + "\n")
        self.result_box.see("end")
        self.result_box.configure(state="disabled")

    def run_check(self):
        self.results = []
        self.result_box.configure(state="normal")
        self.result_box.delete("1.0", "end")
        self.result_box.configure(state="disabled")

        accounts = get_accounts()
        if not accounts:
            self._log("⚠️ Hiç hesap yok!")
            return

        def check_all():
            valid = invalid = 0
            for acc in accounts:
                try:
                    r = requests.get("https://discord.com/api/v9/users/@me",
                                     headers={"Authorization": acc['token']},
                                     timeout=REQUEST_TIMEOUT)
                    if r.status_code == 200:
                        data = r.json()
                        self.after(0, self._log, f"✅ {acc['name']} → {data.get('username', '?')} (Geçerli)")
                        valid += 1
                    elif r.status_code == 401:
                        self.after(0, self._log, f"❌ {acc['name']} → Token Geçersiz!")
                        self.results.append(acc['id'])
                        invalid += 1
                    elif r.status_code == 403:
                        self.after(0, self._log, f"⚠️ {acc['name']} → Kısıtlı (Captcha/Phone)")
                        invalid += 1
                    else:
                        self.after(0, self._log, f"⚠️ {acc['name']} → HTTP {r.status_code}")
                except Exception as e:
                    self.after(0, self._log, f"⚠️ {acc['name']} → Bağlantı hatası")
                time.sleep(1)  # Rate-limit koruması
            self.after(0, self._log, f"\n📊 Sonuç: {valid} geçerli, {invalid} sorunlu")
            if self.results:
                self.after(0, lambda: self.del_btn.configure(state="normal"))

        threading.Thread(target=check_all, daemon=True).start()

    def delete_invalid(self):
        if not self.results:
            return
        if messagebox.askyesno("Onay", f"{len(self.results)} geçersiz hesap silinecek. Emin misiniz?"):
            for acc_id in self.results:
                execute_query("DELETE FROM accounts WHERE id = ?", (acc_id,))
            self._log(f"🗑️ {len(self.results)} hesap silindi.")
            self.results = []
            self.del_btn.configure(state="disabled")
            self.parent_app.load_accounts()

class ScheduleModal(ctk.CTkToplevel):
    def __init__(self, parent, bot_worker):
        super().__init__(parent)
        self.title("⏰ Çalışma Saatleri (Mesai)")
        self.geometry("400x300")
        self.geometry("+%d+%d" % (parent.winfo_rootx() + 100, parent.winfo_rooty() + 100))
        self.grab_set()
        self.bot_worker = bot_worker
        self.parent_app = parent
        self._scheduler_running = False
        self._scheduler_thread = None

        ctk.CTkLabel(self, text="Mesai Zamanlayıcısı", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=10)
        ctk.CTkLabel(self, text="Botlar mesai saatleri dışında otomatik durur,\nmesai başlayınca otomatik başlar.", text_color="gray", justify="center").pack(pady=(0,10))

        tf = ctk.CTkFrame(self, fg_color="transparent")
        tf.pack(pady=10)
        ctk.CTkLabel(tf, text="Başlangıç (HH:MM):").grid(row=0, column=0, padx=5)
        self.start_entry = ctk.CTkEntry(tf, width=80, placeholder_text="10:00")
        self.start_entry.grid(row=0, column=1, padx=5)
        ctk.CTkLabel(tf, text="Bitiş (HH:MM):").grid(row=1, column=0, padx=5, pady=5)
        self.end_entry = ctk.CTkEntry(tf, width=80, placeholder_text="02:00")
        self.end_entry.grid(row=1, column=1, padx=5, pady=5)

        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.pack(fill="x", padx=40, pady=15)
        ctk.CTkButton(bf, text="▶ Zamanlayıcıyı Başlat", fg_color="#2E7D32", command=self.start_schedule).pack(side="left", expand=True, fill="x", padx=(0,5))
        ctk.CTkButton(bf, text="⏹ Durdur", fg_color="#C62828", command=self.stop_schedule).pack(side="right", expand=True, fill="x", padx=(5,0))

    def _parse_time(self, val):
        parts = val.strip().split(":")
        return int(parts[0]), int(parts[1])

    def start_schedule(self):
        try:
            sh, sm = self._parse_time(self.start_entry.get())
            eh, em = self._parse_time(self.end_entry.get())
        except (ValueError, IndexError):
            messagebox.showerror("Hata", "Geçerli saat girin (ör: 10:00)")
            return
        self._scheduler_running = True
        self.bot_worker.log_callback(f"⏰ Mesai zamanlayıcısı aktif: {sh:02d}:{sm:02d} - {eh:02d}:{em:02d}")

        def scheduler_loop():
            while self._scheduler_running:
                now = datetime.now()
                current_mins = now.hour * 60 + now.minute
                start_mins = sh * 60 + sm
                end_mins = eh * 60 + em
                if start_mins <= end_mins:
                    in_work = start_mins <= current_mins < end_mins
                else:
                    in_work = current_mins >= start_mins or current_mins < end_mins

                if in_work and not self.bot_worker.clients:
                    self.bot_worker.log_callback("⏰ Mesai başladı — botlar başlatılıyor!")
                    self.parent_app.after(0, self.parent_app.start_all)
                elif not in_work and self.bot_worker.clients:
                    self.bot_worker.log_callback("⏰ Mesai bitti — botlar durduruluyor!")
                    for acc in get_accounts():
                        self.bot_worker.stop_bot(acc)
                time.sleep(60)

        self._scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
        self._scheduler_thread.start()
        self.destroy()

    def stop_schedule(self):
        self._scheduler_running = False
        self.bot_worker.log_callback("⏰ Zamanlayıcı durduruldu.")
        self.destroy()

class CloneModal(ctk.CTkToplevel):
    def __init__(self, parent, bot_worker):
        super().__init__(parent)
        self.title("👻 Klonlama / Taklit Modu")
        self.geometry("400x250")
        self.geometry("+%d+%d" % (parent.winfo_rootx() + 100, parent.winfo_rooty() + 100))
        self.grab_set()
        self.bot_worker = bot_worker
        self._clone_active = False

        ctk.CTkLabel(self, text="Durum Klonlama", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=10)
        ctk.CTkLabel(self, text="Hedef kullanıcının durumunu tüm\nbotlara yansıtır (30sn aralıkla).", text_color="gray", justify="center").pack()

        ctk.CTkLabel(self, text="Hedef Kullanıcı ID:").pack(anchor="w", padx=30, pady=(10,0))
        self.uid_entry = ctk.CTkEntry(self, width=250, placeholder_text="123456789012345678")
        self.uid_entry.pack(anchor="w", padx=30, pady=(0,15))

        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.pack(fill="x", padx=30, pady=10)
        ctk.CTkButton(bf, text="▶ Klonlamayı Başlat", fg_color="#2E7D32", command=self.start_clone).pack(side="left", expand=True, fill="x", padx=(0,5))
        ctk.CTkButton(bf, text="⏹ Durdur", fg_color="#C62828", command=self.stop_clone).pack(side="right", expand=True, fill="x", padx=(5,0))

    def start_clone(self):
        uid = self.uid_entry.get().strip()
        if not uid or not uid.isdigit():
            messagebox.showerror("Hata", "Geçerli bir User ID girin.")
            return
        self._clone_active = True
        target_id = int(uid)
        bw = self.bot_worker

        async def clone_loop():
            while self._clone_active and bw.clients:
                ref_client = next(iter(bw.clients.values()), None)
                if not ref_client:
                    break
                target = ref_client.get_user(target_id)
                if not target:
                    for g in ref_client.guilds:
                        target = g.get_member(target_id)
                        if target:
                            break
                if target and target.activities:
                    act = target.activities[0]
                    # Thread-safe dictionary iteration copy
                    for client in list(bw.clients.values()):
                        try:
                            if isinstance(act, discord.CustomActivity):
                                await client.change_presence(activity=discord.CustomActivity(name=act.name))
                            elif hasattr(act, 'type') and hasattr(act, 'name'):
                                await client.change_presence(activity=discord.Activity(type=act.type, name=act.name))
                        except Exception:
                            pass
                    bw.log_callback(f"👻 Durum klonlandı: {act.name if hasattr(act,'name') else '?'}")
                await asyncio.sleep(30)

        bw.run_coro(clone_loop())
        bw.log_callback(f"👻 Klonlama başlatıldı → Hedef: {uid}")
        self.destroy()

    def stop_clone(self):
        self._clone_active = False
        self.bot_worker.log_callback("👻 Klonlama durduruldu.")
        self.destroy()

TURKISH_NAMES = ["Ahmet","Mehmet","Fatma","Ayşe","Mustafa","Can","Ece","Deniz","Emir","Zeynep","Ali","Yusuf","Elif","Selin","Berk","Emre","Gizem","Hakan","Burak","Ceren","Doruk","Efe","Sude","Defne","Kerem","Mert","Nisa","Pelin","Arda","Bilge","Cansu","Cem","Derya","Esra","Furkan","Gamze","Hande","İrem","Kaan","Leyla","Mina","Naz","Ozan","Pınar","Rüzgar","Sibel","Tuna","Umut","Yağmur","Zehra"]

class NicknameModal(ctk.CTkToplevel):
    def __init__(self, parent, bot_worker):
        super().__init__(parent)
        self.title("🎭 Rastgele İsim Değiştirici")
        self.geometry("450x400")
        self.geometry("+%d+%d" % (parent.winfo_rootx() + 100, parent.winfo_rooty() + 100))
        self.grab_set()
        self.bot_worker = bot_worker

        ctk.CTkLabel(self, text="Toplu Nickname Değiştir", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=10)
        ctk.CTkLabel(self, text="Sunucu ID:").pack(anchor="w", padx=30)
        self.guild_entry = ctk.CTkEntry(self, width=250, placeholder_text="Sunucu ID")
        self.guild_entry.pack(anchor="w", padx=30, pady=(0,10))

        ctk.CTkLabel(self, text="İsim Listesi (her satıra bir isim, boş=Türkçe ön tanımlı):").pack(anchor="w", padx=30)
        self.name_box = ctk.CTkTextbox(self, height=150, width=380)
        self.name_box.pack(padx=30, pady=(0,10))

        ctk.CTkButton(self, text="🎲 Rastgele Nick Ata", fg_color="#2E7D32", command=self.apply_nicks).pack(pady=10)

    def apply_nicks(self):
        guild_id = self.guild_entry.get().strip()
        if not guild_id or not guild_id.isdigit():
            messagebox.showerror("Hata", "Geçerli bir Sunucu ID girin.")
            return
        custom = self.name_box.get('1.0', 'end').strip()
        names = [n.strip() for n in custom.split('\n') if n.strip()] if custom else list(TURKISH_NAMES)
        random.shuffle(names)
        bw = self.bot_worker
        gid = int(guild_id)

        async def set_nicks():
            # Thread-safe dictionary iteration copy
            for i, (token, client) in enumerate(list(bw.clients.items())):
                nick = names[i % len(names)]
                try:
                    await client.http.request(discord.http.Route('PATCH', '/guilds/{guild_id}/members/@me', guild_id=gid), json={'nick': nick})
                    uname = client.user.name if client.user else '?'
                    bw.log_callback(f"🎭 {uname} → '{nick}'")
                except Exception as e:
                    bw.log_callback(f"❌ Nick değiştirilemedi: {e}")
                await asyncio.sleep(random.uniform(2, 4))
            bw.log_callback("✅ Tüm nickler atandı!")

        bw.run_coro(set_nicks())
        self.destroy()

class HypeModal(ctk.CTkToplevel):
    def __init__(self, parent, bot_worker):
        super().__init__(parent)
        self.title("🔥 Şakşakçı (Hype) Modu")
        self.geometry("450x550")
        self.geometry("+%d+%d" % (parent.winfo_rootx() + 90, parent.winfo_rooty() + 90))
        self.grab_set()
        self.bot_worker = bot_worker

        ctk.CTkLabel(self, text="Oto-Reaksiyon Hype Motoru", font=ctk.CTkFont(size=18, weight="bold")).pack(pady=10)
        ctk.CTkLabel(self, text="Hedef kişi kanala mesaj attığında,\nstoklanan botlar insansı bir şekilde emoji basar.", text_color="gray", justify="center").pack(pady=(0, 10))

        cf = ctk.CTkFrame(self, fg_color="transparent")
        cf.pack(fill="x", padx=30, pady=5)
        ctk.CTkLabel(cf, text="Kanal ID:").grid(row=0, column=0, sticky="w", pady=5)
        self.cid_entry = ctk.CTkEntry(cf, width=200, placeholder_text="1234567890123...")
        self.cid_entry.grid(row=0, column=1, sticky="e", pady=5, padx=10)
        self.cid_entry.insert(0, self.bot_worker.hype_channel or "")

        ctk.CTkLabel(cf, text="Yönetici (Hedef) ID:").grid(row=1, column=0, sticky="w", pady=5)
        self.uid_entry = ctk.CTkEntry(cf, width=200, placeholder_text="1234567890123...")
        self.uid_entry.grid(row=1, column=1, sticky="e", pady=5, padx=10)
        self.uid_entry.insert(0, self.bot_worker.hype_target or "")

        ctk.CTkLabel(cf, text="Bekleme Süresi (sn):").grid(row=2, column=0, sticky="w", pady=5)
        self.delay_entry = ctk.CTkEntry(cf, width=80)
        self.delay_entry.grid(row=2, column=1, sticky="w", pady=5, padx=10)
        self.delay_entry.insert(0, str(self.bot_worker.hype_delay_sec))

        ctk.CTkLabel(cf, text="Bot Kotası (Maks):").grid(row=3, column=0, sticky="w", pady=5)
        self.quota_entry = ctk.CTkEntry(cf, width=80)
        self.quota_entry.grid(row=3, column=1, sticky="w", pady=5, padx=10)
        self.quota_entry.insert(0, str(self.bot_worker.hype_quota))

        ctk.CTkLabel(cf, text="Yedek Emojiler\n(Virgülle ayırın):").grid(row=4, column=0, sticky="w", pady=5)
        self.emo_entry = ctk.CTkEntry(cf, width=200)
        self.emo_entry.grid(row=4, column=1, sticky="e", pady=5, padx=10)
        self.emo_entry.insert(0, ",".join(self.bot_worker.hype_emojis))

        bf = ctk.CTkFrame(self, fg_color="transparent")
        bf.pack(fill="x", padx=30, pady=20)
        ctk.CTkButton(bf, text="▶ Hype Başlat", fg_color="#2E7D32", command=self.start_hype).pack(side="left", expand=True, fill="x", padx=(0,5))
        ctk.CTkButton(bf, text="⏹ Durdur", fg_color="#C62828", command=self.stop_hype).pack(side="right", expand=True, fill="x", padx=(5,0))

        if self.bot_worker.hype_active:
            ctk.CTkLabel(self, text="🟢 Hype Modu Aktif Çalışıyor!", text_color="#4CAF50", font=ctk.CTkFont(weight="bold")).pack()

    def start_hype(self):
        cid = self.cid_entry.get().strip()
        uid = self.uid_entry.get().strip()
        delay = self.delay_entry.get().strip()
        quota = self.quota_entry.get().strip()
        emojis = self.emo_entry.get().strip()

        if not cid.isdigit() or not uid.isdigit():
            messagebox.showerror("Hata", "Kanal ID ve Yönetici ID sadece rakam olmalıdır.")
            return

        self.bot_worker.hype_channel = cid
        self.bot_worker.hype_target = uid
        self.bot_worker.hype_delay_sec = int(delay) if delay.isdigit() else 10
        self.bot_worker.hype_quota = int(quota) if quota.isdigit() else 5
        self.bot_worker.hype_emojis = [e.strip() for e in emojis.split(",") if e.strip()]
        self.bot_worker.hype_active = True
        
        self.bot_worker.log_callback(f"🔥 Hype Aktif! Kanal: {cid} | Hedef: {uid}")
        self.destroy()

    def stop_hype(self):
        self.bot_worker.hype_active = False
        self.bot_worker.log_callback("🔥 Hype Modu durduruldu.")
        self.destroy()

if __name__ == "__main__":
    try:
        app = CustomApp()
        app.mainloop()
    except Exception as e:
        import traceback
        with open("error.txt", "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        print(f"CRITICAL ERROR: {e}")
