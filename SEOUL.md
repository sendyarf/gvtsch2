# SEOUL.md — Arsitektur & Panduan Proyek gvtsch2

> **S**chedule **E**ngine **O**rchestrator & **U**nified **L**ist

Dokumen ini menjelaskan arsitektur sistem, alur data, dan panduan untuk AI/developer yang bekerja di proyek ini.

---

## 🎯 Tujuan Proyek

Menghasilkan `sch.json` — file jadwal pertandingan olahraga terstandarisasi dalam **bahasa Inggris** yang menggabungkan data dari berbagai sumber streaming, siap dikonsumsi oleh aplikasi frontend.

---

## 📁 Struktur File Utama

```
gvtsch2/
├── sch.py                  # ⭐ Master merger — menggabungkan semua sumber → sch.json
├── sch.json                # 📤 OUTPUT utama (hasil akhir)
│
├── ai_matcher.py           # 🤖 AI-powered name normalizer (DeepSeek API)
├── manual_mapping.json     # 📖 Kamus nama tim & liga (alias → canonical English)
├── ai_mapping_cache.json   # 💾 Cache hasil AI agar tidak hit API berulang
│
├── soco.py                 # Scraper: socolive25.cv (Selenium)
├── soco.json               # Data dari soco
│
├── bolaloca.py             # Scraper: bolaloca
├── bolaloca.json
│
├── flashscore.py           # Scraper: flashscore
├── flashscore.json         # Primary source (biasanya kosong/scheduled)
├── flashscore_home.json    # Extended flashscore data
│
├── sportsonline.py         # Scraper: sportsonline
├── sportsonline.json
│
├── streamcenter.py         # Scraper: streamcenter
├── streamcenter.json
│
├── sofascore.py            # Scraper: sofascore (untuk logo & status)
├── sofascore.json          # Enrichment source (sport, status, logo)
│
├── manual_sch.json         # Manual override — prioritas TERTINGGI
├── fetch_teams.py          # Utility: fetch team info
├── update_teams.py         # Utility: update team metadata
├── sort_mapping.py         # Utility: sort manual_mapping.json
│
├── SEOUL.md                # ← Dokumen ini
├── MEMORY.md               # Konteks AI & progress session
└── TASKS.md                # Task tracking publik
```

---

## 🔄 Alur Data (Pipeline)

```
manual_sch.json ─────────────────┐
flashscore.json ─────────────────┤
bolaloca.json   ─────────────────┤──► PHASE 1: Primary Merge
streamcenter.json ───────────────┘          (create + merge servers)
                                                    │
sportsonline.json ──────────────────► PHASE 2: Merge-only Sources
soco.json       ────────────────────► (only add servers to existing)
                                                    │
sofascore.json  ────────────────────► PHASE 3: Enrichment
                                      (sport, status, logo, gender)
                                                    │
ai_matcher.py + DEEPSEEK API ──────► PHASE 3.5: AI Name Resolution
manual_mapping.json ────────────────  (translate + normalize all names)
                                                    │
manual_mapping.json ────────────────► PHASE 4: Apply Display Names
                                      (apply canonical English names)
                                                    │
                                       PHASE 5-7: Filter, Sort, Output
                                                    │
                                              sch.json ✅
```

---

## 📋 Prioritas Sumber Data

| Prioritas | File | Fungsi |
|-----------|------|--------|
| 1 (Tertinggi) | `manual_sch.json` | Override manual, prepend servers |
| 2 | `flashscore.json` | Primary schedule source |
| 3 | `bolaloca.json` | Create + merge servers |
| 4 | `streamcenter.json` | Create + merge servers |
| 5 | `sportsonline.json` | Merge servers only (no date) |
| 6 | `soco.json` | Merge servers only + logo fallback |
| Enrichment | `sofascore.json` | Sport type, status, logos |
| Mapping | `manual_mapping.json` | Canonical name lookup (English) |

---

## 🤖 AI Matcher — Cara Kerja

`ai_matcher.py` menggunakan **DeepSeek API** untuk:

1. **Mengumpulkan** semua nama tim & liga dari semua source JSON
2. **Membandingkan** dengan nama di `sofascore.json` & `flashscore.json` (referensi)
3. **Mengirim** nama yang tidak match ke AI untuk di-resolve
4. **Menyimpan** hasil ke `manual_mapping.json` (persisten, tidak hit API lagi)
5. **Cache** disimpan di `ai_mapping_cache.json`

### Aktivasi
- AI Matcher **aktif by default** saat `sch.py` dijalankan
- Untuk menonaktifkan: set env var `SKIP_AI_MATCHER=true`
- Butuh env var: `DEEPSEEK_API_KEY`

### Format Output manual_mapping.json
```json
{
  "team_names": {
    "Canonical English Name": ["alias1", "alias2", "alias3"]
  },
  "league_names": {
    "Club Friendly": ["Amical club", "Amistoso", "Friendly Match"],
    "Spain - LaLiga": ["Laliga", "La Liga", "Primera Division"]
  }
}
```

---

## 📤 Format Output sch.json

```json
[
  {
    "id": "team1-team2",
    "sport": "Football",
    "league": "Spain - LaLiga",
    "team1": {
      "name": "Real Madrid",
      "logo": "https://..."
    },
    "team2": {
      "name": "Barcelona",
      "logo": "https://..."
    },
    "kickoff_date": "2026-07-25",
    "kickoff_time": "20:00",
    "match_date": "2026-07-25",
    "match_time": "19:55",
    "duration": "3.5",
    "status": "upcoming",
    "status_desc": "",
    "gender": "male",
    "servers": [
      { "url": "https://multi.govoet.cc/?shaka=...", "label": "CH-EN" }
    ]
  }
]
```

**Catatan:** `match_time` = `kickoff_time - 5 menit` (untuk pre-match buffer).

---

## 🌐 Bahasa & Standarisasi

**Semua nama tim dan liga di `sch.json` harus dalam Bahasa Inggris.**

- Liga: format `"Country - Competition"` (contoh: `"Brazil - Serie A"`)
- Friendly: selalu `"Club Friendly"` (BUKAN `"Amical club"`, `"Amistoso"`)
- Tim nasional: nama Inggris standar (contoh: `"South Korea"` bukan `"Corée du Sud"`)
- Jika AI tidak bisa menerjemahkan, tambahkan manual ke `manual_mapping.json`

---

## ⚙️ GitHub Actions

Pipeline berjalan otomatis via GitHub Actions:
- Scraper dijalankan secara terjadwal
- `DEEPSEEK_API_KEY` tersimpan sebagai GitHub Secret
- Output `sch.json` di-commit ke repo

---

## 🔧 Cara Menambah Mapping Manual

Edit `manual_mapping.json`, tambahkan di section `league_names`:
```json
"Club Friendly": ["Amical club", "nama_baru_disini"]
```

Atau jalankan `sort_mapping.py` setelah edit untuk menjaga urutan alfabetis.
