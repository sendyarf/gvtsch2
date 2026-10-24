# gvtsch2-vps — Deploy ke VPS via PM2

Folder berisi **semua bot scraper + sch.py + ai_matcher** untuk dijalankan di VPS
tanpa batasan GitHub Actions. Semua berjalan cepat, bersamaan (concurrent),
dan dijaga hidup oleh **PM2**.

---

## 📁 Isi Folder

```
gvtsch2-vps/
├── run_all.py              # Orchestrator — menjalankan semua scraper + merge
├── ecosystem.config.js     # Config PM2 (scraper + server publik)
├── http_client.py          # Lapisan HTTP bersama (retry, session, impersonasi)
├── requirements.txt
├── soco.py → soco.json     # Selenium scraper
├── bolaloca.py → bolaloca.json
├── flashscore.py → flashscore.json
├── flashscore_home.py → flashscore_home.json
├── sportsonline.py → sportsonline.json
├── sofascore.py → sofascore.json
├── timstreams.py → timstreams.json
├── kralsport.py → kralsport.json
├── sch.py → sch.json       # Master merge (termasuk jalankan ai_matcher)
├── ai_matcher.py           # AI name matcher (sumopod / GLM)
├── manual_mapping.json
├── manual_sch.json         # Server manual (prioritas tertinggi) — buat sendiri
├── manual_sch.example.json # Template cara mengisi manual_sch.json
├── ai_mapping_cache.json
├── duration.json
└── logs/                   # Dibuat otomatis, berisi orchestrator.log
```

---

## 🚀 Setup di VPS

> Ubuntu 24.04+ memblokir `pip` sistem (PEP 668). Selalu pakai **virtual environment**.

### 1. Siapkan virtualenv & dependencies

```bash
cd /opt/gvtsch2   # letakkan folder di sini (atau path lain)

# buat venv DI DALAM folder proyek (path absolute ini dipakai PM2)
python3 -m venv venv

# aktifkan & install
. venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

> Pastikan `python3-venv` terpasang jika `python3 -m venv` gagal:
> `sudo apt install python3-venv python3-full`

> **Catatan Selenium:** `flashscore.py` butuh Chrome/Chromium + `chromedriver`.
> Install di VPS, atau matikan di `run_all.py` (`enabled=False`) bila tidak diperlukan.

### 2. Set environment (AI API key)

Default sudah tertanam di kode (`ai_matcher.py` / `soco.py`): endpoint
`https://ai.sumopod.com`, model `glm-5.3-flash`. Untuk override (mis. di CI),
set env var berikut (opsional):

```bash
export AI_API_KEY='sk-xxx'          # default sudah ada di kode
export AI_BASE_URL='https://ai.sumopod.com'
export AI_MODEL='glm-5.3-flash'
```

### 3. Jalankan via PM2

PM2 otomatis memakai python dari venv (lihat `ecosystem.config.js`).

```bash
# mulai sekali (buat test satu siklus)
./venv/bin/python run_all.py

# atau langsung sebagai daemon PM2
pm2 start ecosystem.config.js
pm2 save
pm2 startup   # agar otomatis start saat server reboot
```

### 4. Cek log

```bash
pm2 logs gvtsch2
pm2 status
tail -f logs/orchestrator.log
```

---

## ⚙️ Jadwal Scraper (default)

| Script | Interval |
|--------|----------|
| bolaloca, sportsonline, timstreams | 3 menit |
| soco, sofascore | 3 menit |
| kralsport (kralsportshd.com, "Andro Stream") | 3 menit |
| xoilac (xoilacz.vip) | 3 menit |
| flashscore (Selenium) — nonaktif (butuh Chrome di VPS) | — |
| sch.py (merge) | 2 menit |
| AI matcher (di dalam merge) | 30 menit (cooldown) |

Ubah interval di `run_all.py` (`SCRAPERS` / `MERGE_INTERVAL`). Khusus AI matcher,
cadence-nya dikontrol env `AI_MATCHER_INTERVAL` (detik, default `1800` = 30 mnt),
agar AI (GLM) tidak dipanggil tiap merge:

Ubah interval langsung di `run_all.py` (bagian `SCRAPERS` / `MERGE_INTERVAL`),
lalu restart PM2:

```bash
pm2 restart gvtsch2
```

---

## 🧪 Mode

- `python3 run_all.py` → jalankan **satu siklus penuh** lalu keluar (buat testing).
- `python3 run_all.py --daemon` → loop terus menerus (dijalankan otomatis oleh PM2).

---

## 🌐 Akses Publik untuk Frontend

`serve_public.py` menyajikan JSON secara HTTP (read-only, CORS aktif) sehingga
frontend di proyek/beda domain bisa mengambil data langsung:

```js
fetch("http://VPS_IP:9015/sch.json").then(r => r.json())
```

> 💡 **Zona waktu:** setiap match punya `startTimestamp` (unix UTC). Untuk
> menampilkan jam sesuai zona lokal pengguna (bukan hardcode GMT+7), gunakan:
> ```js
> const t = new Date(match.startTimestamp * 1000);
> console.log(t.toLocaleTimeString());   // otomatis zona lokal pengguna
> ```
> `kickoff_date`/`kickoff_time` tetap tersedia sebagai info tambahan (GMT+7).

### Jalankan

Sudah terdaftar di `ecosystem.config.js` sebagai app `gvtsch2-serve`
(port `9015`, host `127.0.0.1` — loopback, diexposkan via nginx), jadi cukup:

```bash
pm2 start ecosystem.config.js
pm2 save
```

Atau manual tanpa PM2:

```bash
python3 serve_public.py --port 9015 --host 127.0.0.1
```

> ⚠️ Dengan bind ke `127.0.0.1`, server hanya didengar dari mesin sendiri;
> publik diarahkan lewat nginx. Jika Anda mau mencoba langsung tanpa nginx,
> ganti `--host 0.0.0.0` (kurang aman — tanpa autentikasi ke internet).

```nginx
# /etc/nginx/sites-available/gvtsch2
server {
    listen 80;
    server_name api.domain.com;
    location / {
        proxy_pass http://127.0.0.1:9015;
        proxy_set_header Host $host;
    }
}
```

Frontend lalu memakai `https://api.domain.com/sch.json`.

---

## ✍️ Menambah Server Secara Manual

Buat file `manual_sch.json` di root proyek (template: `manual_sch.example.json`).
Format per pertandingan:

```json
{
  "league": "England - Premier League",
  "team1": { "name": "Arsenal", "logo": "" },
  "team2": { "name": "Chelsea", "logo": "" },
  "kickoff_date": "2026-08-17",
  "kickoff_time": "19:30",
  "duration": "3.5",
  "servers": [
    { "url": "https://example.com/stream1", "label": "CH-MANUAL-1" }
  ]
}
```

Aturan penting saat merge (`sch.py`):

- `kickoff_date` dan `kickoff_time` **wajib diisi** — entry tanpa keduanya dibuang
  pada tahap akhir.
- `manual_sch.json` punya **prioritas tertinggi**; server manual ditampilkan
  paling atas (prepend) untuk match yang cocok.
- Bila ingin **menambah server ke pertandingan yang sudah ada** (bukan membuat
  baris baru), isi `league` + pasangan tim + `kickoff_date` + `kickoff_time` yang
  sama dengan hasil scrape — servernya akan *digabung* ke match tsb.