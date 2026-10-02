# 🚀 Complete Deployment Guide: Telegram Restricted Content Bot & Web Studio

[English Version Below](#english-deployment-guide) | [বাংলা গাইড নিচে দেখুন](#bangla-deployment-guide)

---

<a name="bangla-deployment-guide"></a>
## 🇧🇩 বাংলা ডিপ্লয়মেন্ট গাইড (VPS & Cloud Server)

এই প্রজেক্টটি যেকোনো Linux VPS (Ubuntu, Debian, CentOS, Hostinger, DigitalOcean, Hetzner, AWS) অথবা OpenShift / Docker প্ল্যাটফর্মে **১-ক্লিকে (1-Click Auto Deploy)** চালানোর জন্য প্রস্তুত করা হয়েছে।

### 📌 মূল ফিচারসমূহ (Project Overview)
- **রেস্ট্রিক্টেড কনটেন্ট সেভার ও ফরওয়ার্ডার:** পাবলিক এবং প্রাইভেট চ্যানেল/গ্রুপের রেস্ট্রিক্টেড ভিডিও, ফটো এবং ফাইল ক্লাউড প্রসেসিংয়ের মাধ্যমে অনায়াসে সংরক্ষণ।
- **মাল্টি-ওয়ার্কার ইঞ্জিন:** একযোগে ১৬টি পর্যন্ত ফাইল প্যারালালে প্রসেস করার ক্ষমতা।
- **সাইবারপাঙ্ক ওয়েব স্টুডিও ককপিট:** পোর্ট `8888`-এ লাইভ গ্রাফিক্যাল মনিটরিং, চ্যানেল ক্লোনার, ওয়াটারমার্ক স্টুডিও এবং ডাটাবেজ ভিজ্যুয়ালাইজার।
- **অটো রিস্টার্ট ও ফল্ট টলারেন্স:** সার্ভার রিবুট হলে বা কোনো কারণে ক্র্যাশ করলে স্বয়ংক্রিয়ভাবে পুনরায় চালু হওয়া (Systemd & Docker)।

---

### 🛠️ পদ্ধতি ১: Linux VPS-এ ১-ক্লিক অটো ডিপ্লয় (সবচেয়ে সহজ ও রেকমেন্ডেড)

আপনার VPS সার্ভারে SSH দিয়ে লগইন করুন এবং প্রজেক্ট ফোল্ডারে গিয়ে শুধুমাত্র একটি কমান্ড রান করুন:

```bash
bash deploy.sh
```

**এই স্ক্রিপ্টটি স্বয়ংক্রিয়ভাবে যা যা করবে:**
1. আপনার সার্ভারের অপারেটিং সিস্টেম (Ubuntu/Debian ইত্যাদি) শনাক্ত করবে।
2. পাইথন, এফএফএমপেক (FFmpeg), এবং প্রয়োজনীয় সমস্ত লাইব্রেরি ইনস্টল করবে।
3. `.env` ফাইলে প্রয়োজনীয় টেলিগ্রাম ক্রেডেনশিয়াল না থাকলে স্ক্রিনে ইনপুট দেওয়ার অপশন দেবে।
4. ব্যাকগ্রাউন্ডে দুটি সিস্টেম সার্ভিস চালু করবে:
   - `bot.service` (মূল টেলিগ্রাম বট)
   - `bot-studio.service` (ওয়েব ড্যাশবোর্ড)
5. সার্ভার রিবুট হলেও বট নিজে থেকেই চালু থাকবে।

---

### 🐳 পদ্ধতি ২: Docker & Docker Compose ডিপ্লয়

যদি আপনি ডকার কন্টেইনারে সম্পূর্ণ আইসোলেটেডভাবে চালাতে চান:

```bash
# ১. .env কনফিগার করুন
cp .env.example .env
nano .env

# ২. কন্টেইনার বিল্ড ও ব্যাকগ্রাউন্ডে রান করুন
docker compose up -d --build

# ৩. লাইভ লগ চেক করুন
docker compose logs -f
```

---

### ☁️ পদ্ধতি ৩: Red Hat OpenShift ডিপ্লয়

OpenShift ক্লাস্টারে ডিপ্লয় করতে:

```bash
# ১. সিক্রেট তৈরি করুন (.env থেকে)
oc create secret generic bot-secrets --from-env-file=.env

# ২. ওপেনশিফট ম্যানিফেস্ট অ্যাপ্লাই করুন
oc apply -f openshift.yaml

# ৩. ডিপ্লয়মেন্টের স্ট্যাটাস দেখুন
oc get pods -w
oc get route restricted-bot-route
```

---

### 🕹️ দরকারী কমান্ডসমূহ (Cheat Sheet)

| কাজ | Native Systemd কমান্ড | Docker কমান্ড |
|---|---|---|
| **বটের লাইভ লগ দেখা** | `sudo journalctl -u bot -f` | `docker compose logs -f telegram-bot` |
| **বট রিস্টার্ট করা** | `sudo systemctl restart bot` | `docker compose restart` |
| **বট স্টপ করা** | `sudo systemctl stop bot` | `docker compose down` |
| **কোড আপডেট করা** | `bash update.sh` | `bash update.sh` |
| **ডাটাবেজ ব্যাকআপ** | `bash backup_db.sh` | `bash backup_db.sh` |
| **ওয়েব স্টুডিও লগ** | `sudo journalctl -u bot-studio -f` | ডকার লগের সাথেই অন্তর্ভুক্ত |

---
---

<a name="english-deployment-guide"></a>
## 🇬🇧 English Deployment Guide

### 🛠️ Method 1: 1-Click Universal VPS Auto-Deploy (Recommended)

Connect to your VPS via SSH, navigate to the project directory, and run:

```bash
bash deploy.sh
```

**What this automated script handles:**
- Detects OS (Ubuntu, Debian, CentOS, Alma, Alpine, etc.)
- Installs Python 3, FFmpeg, fonts, and compilation tools
- Prompts for API credentials if `.env` is unconfigured
- Creates Python virtual environment and installs dependencies
- Configures two background systemd daemons with auto-restart on boot:
  - `bot.service` (Telegram Bot Engine)
  - `bot-studio.service` (Web Studio on port 8888)

---

### 🐳 Method 2: Docker & Docker Compose

Deploy seamlessly across any Docker-enabled host:

```bash
cp .env.example .env
# Edit credentials in .env
nano .env

# Launch services in detached mode
docker compose up -d --build

# Monitor live output
docker compose logs -f
```

---

### ☁️ Method 3: Red Hat OpenShift Deployment

Deploy directly to an OpenShift cluster using `openshift.yaml`:

```bash
# 1. Create Secret from .env
oc create secret generic bot-secrets --from-env-file=.env

# 2. Apply Kubernetes/OpenShift resources (PVC, Deployment, Service, Route)
oc apply -f openshift.yaml

# 3. View running pods and exposed Route
oc get pods -l app=restricted-bot
oc get route restricted-bot-route
```

---

### ⚙️ Environment Configuration (`.env`)

| Key | Description | Required |
|---|---|---|
| `TELEGRAM_API_ID` | Telegram API ID from [my.telegram.org](https://my.telegram.org) | Yes |
| `TELEGRAM_API_HASH` | Telegram API Hash from [my.telegram.org](https://my.telegram.org) | Yes |
| `TELEGRAM_BOT_TOKEN` | Bot Token from [@BotFather](https://t.me/BotFather) | Yes |
| `ADMIN_IDS` | Comma-separated admin Telegram IDs | Yes |
| `FORCE_SUB_CHANNEL` | Optional channel username (e.g., `@mychannel`) for force-sub | No |
| `ADMIN_ARCHIVE_CHANNEL`| Silent archive channel ID for cloning media | No |
| `BKASH_NUMBER` / `NAGAD_NUMBER` | Payment recipient numbers for monetization | No |
| `MAX_CONCURRENT_WORKERS` | Max simultaneous downloads (default: auto-tuned, 16) | No |
