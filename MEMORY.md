# MEMORY.md — Konteks AI untuk Sesi Berikutnya

> File ini dibaca oleh AI di awal setiap sesi untuk memahami konteks proyek dan progress terkini.
> **Update file ini setelah setiap sesi signifikan.**

---

## 📌 Status Proyek Saat Ini

- **Tanggal Update Terakhir:** 2026-07-25
- **Fase Aktif:** Maintenance + Optimasi kualitas data

---

## 🔑 Poin Penting yang Harus Diingat

### 1. Bahasa Output
- **sch.json HARUS dalam bahasa Inggris** — ini prioritas utama
- Format liga: `"Country - Competition"` (bukan bahasa lokal)
- Friendly: selalu `"Club Friendly"` (bukan `"Amical club"`, `"Amistoso"`)
- Jika ada nama yang masih dalam bahasa lain di output, **tambahkan ke `manual_mapping.json`**

### 2. Arsitektur AI Matcher
- AI Matcher menggunakan **DeepSeek API** (bukan Groq/OpenAI)
- Model: `deepseek-v4-flash`
- Key: `DEEPSEEK_API_KEY` (ada di GitHub Secrets & environment variable lokal)
- AI Matcher **selalu aktif** saat `sch.py` dijalankan (sejak 2026-07-25)
- Untuk disable: set `SKIP_AI_MATCHER=true`
- Sebelumnya pakai `RUN_AI_MATCHER=true` — **ini sudah DIUBAH**

### 3. soco.py
- Scraper untuk socolive25.cv menggunakan Selenium
- **Sejak 2026-07-25:** scrape juga logo tim (sebagai fallback jika SofaScore tidak punya)
- **Sejak 2026-07-25:** setelah scraping, otomatis translate nama liga via DeepSeek AI
- Hasil terjemahan disimpan permanen ke `manual_mapping.json`
- Logo soco = **fallback** (SofaScore tetap prioritas utama)

### 4. Sumber Data & Prioritas
```
manual_sch.json > flashscore.json > bolaloca.json > streamcenter.json
    (create)            (create)          (create)        (create)

sportsonline.json → merge servers only
soco.json → merge servers only + logo fallback

sofascore.json → enrichment (sport, status, logo)
manual_mapping.json → normalization (canonical English names)
```

### 5. manual_mapping.json
- File **sangat besar** (~200KB+, 9000+ baris)
- Format: `"Canonical English Name": ["alias1", "alias2"]`
- AI Matcher **otomatis menambahkan** alias baru ke file ini
- Jangan hapus entry yang ada kecuali benar-benar salah

---

## 🐛 Bug / Masalah yang Sudah Diketahui

| Masalah | Status | Solusi |
|---------|--------|--------|
| Nama liga Vietnam di soco tidak diterjemahkan | ✅ Fixed (2026-07-25) | soco.py sekarang auto-translate via AI |
| "Amical club" tidak diubah ke "Club Friendly" | ✅ Fixed (2026-07-25) | Prompt AI diperbaiki + manual mapping |
| AI Matcher hanya jalan jika `RUN_AI_MATCHER=true` | ✅ Fixed (2026-07-25) | Sekarang always-on, disable dengan `SKIP_AI_MATCHER=true` |
| Tidak ada logo fallback dari soco | ✅ Fixed (2026-07-25) | sch.py sekarang pakai soco logo jika SofaScore kosong |

---

## 📝 Perubahan Terakhir (2026-07-25)

### `soco.py`
- Tambah scraping logo tim (home & away) dari elemen `img` di halaman
- Tambah fungsi `translate_leagues_with_ai()` — translate nama liga setelah scraping
- Output `soco.json` sekarang bisa punya field `logo` di `team1`/`team2`

### `ai_matcher.py`
- Perbaiki prompt **league translation** — lebih detail, khusus Vietnamese/French/Portuguese/abbreviation
- Perbaiki prompt **team translation** — tambah aturan output English-only
- Tambah contoh spesifik: `"Amical club"` → `"Club Friendly"`, Vietnam league names

### `sch.py`
- **Phase 3.5:** Ubah dari `RUN_AI_MATCHER=true` → always-on (`SKIP_AI_MATCHER=true` untuk disable)
- **Phase 2 (soco merge):** Tambah logo fallback dari soco jika primary source tidak punya logo

---

## 🔜 Backlog / Ide

- [ ] Scrape jadwal dari lebih banyak sumber (e.g., livescore, 365scores)
- [ ] Tambah field `sport_icon` di sch.json
- [ ] Improve matching untuk pertandingan rugby/basketball (saat ini fokus ke football)
- [ ] Dashboard monitoring untuk melihat match count per source

---

## 💡 Tips untuk AI

1. **Selalu baca file ini sebelum mulai bekerja** di proyek ini
2. Kalau user request terjemahan nama, **selalu simpan ke `manual_mapping.json`** — jangan hanya fix di output
3. Setelah setiap perubahan signifikan, **update tanggal dan deskripsi** di file ini
4. `manual_mapping.json` punya format khusus — format: `"Canonical": ["alias1", "alias2"]` (canonical = English)
5. Jangan ubah `ai_mapping_cache.json` secara manual — itu dikelola otomatis oleh `ai_matcher.py`
