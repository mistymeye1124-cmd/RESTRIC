# 🚀 Telegram Restricted Content Saver & Business Platform

An enterprise-grade Telegram Bot system engineered exclusively for **unlocking, downloading, watermarking, and cloning restricted content (`noforwards` / "Restrict saving content") from private Telegram channels and groups**.

Built to match and surpass the workflow shown in `E:\IMG_7652.MP4` with **automated VIP subscriptions, bKash/Nagad payments, FFmpeg watermarking, multi-worker priority queuing, viral channel growth, and a channel cloner tool**.

---

## 🌟 100% Dedicated Telegram Restricted Features

1. **All Restricted Telegram Content Types:**
   - 📹 **Videos:** Full HD, 720p/480p scaling, duration, crisp original thumbnails, and instant streamable playback.
   - 📄 **Documents & PDFs:** Lecture notes, question banks, study guides, zip packages.
   - 🖼️ **Photos & Graphics:** High-res original images without compression artifacts.
   - 🎙️ **Voice Notes & Audio:** Podcast lectures, voice instructions, and audio tracks.
   - 💬 **Restricted Text Posts:** Copies text-only restricted posts and announcements with complete formatting preserved!
2. **Every Telegram Link Format:**
   - Private Channels: `https://t.me/c/2459862936/1019`
   - Forum Topic Threads: `https://t.me/c/2459862936/2/1019`
   - Bulk Batch Ranges: `https://t.me/c/2459862936/1019-1050`
   - Public Restricted Channels: `https://t.me/channel_name/1019`
3. **Channel Auto-Joiner (`/join <link>`):**
   - Connect private invite links (`https://t.me/+xxxxxx`) directly through the bot.
4. **Channel Cloner Tool (`/clone`):**
   - Mirror/clone an entire series of restricted lectures into your own private backup channel sequentially in order!
5. **Exact Match with Reference Video UI:**
   - Live download card: `⬇️ Downloading from Telegram` `🟦🟦🟦⬜⬜⬜⬜⬜ 32%`
   - Inline Buttons: `[ Progress ⚡ ]` and `[ Cancel ❌ ]`
   - Interactive native Telegram modal alert on `Progress ⚡` tap.
   - Live upload card: `⬆️ Sending to Telegram` `🟩🟩🟩⬜⬜⬜⬜⬜ 35%`
   - Delivery card: `✅ Done` with video details and custom channel watermark!
6. **Automatic 2GB+ Video Splitting:**
   - Files over 2000 MB are seamlessly split into Part 1, Part 2 without quality loss so Telegram upload limits are never exceeded!
7. **Monetization (bKash / Nagad / One-Click Admin Approval):**
   - Free tier limit: 3 downloads / day.
   - VIP Premium: Unlimited downloads, high-speed priority queue, batch range downloading, and custom branding.
   - Interactive admin approval buttons in Telegram.

---

## 🛠️ Quick Configuration Guide

### 1. Configure `config.py`
Open `config.py` and set your credentials:
```python
API_ID = 12345678               # From https://my.telegram.org
API_HASH = "your_api_hash"      # From https://my.telegram.org
BOT_TOKEN = "your_bot_token"    # From @BotFather
ADMIN_IDS = [123456789]         # Your numeric Telegram ID

# Set your bKash & Nagad numbers for receiving subscription payments
PAYMENT_METHODS = {
    "bKash (Send Money)": "017XXXXXXXX",
    "Nagad (Send Money)": "018XXXXXXXX",
    "Rocket": "019XXXXXXXX",
    "Binance Pay ID / USDT": "123456789",
}
```

### 2. 1-Click Auto Deploy (VPS / Docker / OpenShift)

#### Option A: 1-Click Linux VPS (Recommended)
On your Ubuntu/Debian/CentOS VPS, simply run:
```bash
bash deploy.sh
```
*This automatically configures Python, FFmpeg, virtual environment, and background systemd services with auto-restart on boot.*

#### Option B: Docker Compose
```bash
docker compose up -d --build
```

#### Option C: Red Hat OpenShift
```bash
oc apply -f openshift.yaml
```

*For comprehensive bilingual instructions (English & Bangla), see [DEPLOY.md](DEPLOY.md).*

---

## 📱 Command Reference

| Command | Function |
|---|---|
| `/start` | Open main menu, view remaining quota and account status |
| `/login` | Connect Telegram account via Phone + OTP or StringSession |
| `/logout` | Disconnect and clear user session |
| `/join <link>` | Join private channel via invite link (`https://t.me/+...`) |
| `/setup` | Configure custom watermark and lecture headline banner |
| `/settings` | Set resolution (360p-1080p), caption, auto-forward channel |
| `/clone <range>` | Bulk clone an entire restricted channel topic to your channel |
| `/premium` | View VIP plans and payment instructions |
| `/pay <plan> <trx> <num>` | Submit bKash/Nagad payment for verification |
| `/status` | View connection and queue status |
| `/cancel` | Cancel active download task |
| `/admin` | Administrative control panel and statistics |
| `/stats` | View live revenue, user count, and total data delivered |
| `/broadcast` | Broadcast promo messages to all bot users |
