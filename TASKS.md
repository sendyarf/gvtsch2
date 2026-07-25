# TASKS.md — Task Tracker

> Tracking progress pengembangan proyek gvtsch2.
> **Update file ini setiap ada perubahan status.**

---

## ✅ Selesai

### [2026-07-25] Optimasi Soco + AI Translation + Dokumentasi
- [x] Pull latest dari GitHub (sync dengan remote)
- [x] `soco.py` — Tambah scraping logo tim (home & away) sebagai fallback
- [x] `soco.py` — Tambah auto-translate nama liga via DeepSeek AI setelah scraping
- [x] `ai_matcher.py` — Perbaiki prompt league translation (English-only, handle Vietnamese/French/abbreviations)
- [x] `ai_matcher.py` — Perbaiki prompt team translation (tambah aturan English)
- [x] `sch.py` — AI Matcher selalu aktif by default (hapus `RUN_AI_MATCHER=true`)
- [x] `sch.py` — Tambah soco logo sebagai fallback di phase merge soco.json
- [x] Buat `SEOUL.md` — dokumentasi arsitektur proyek
- [x] Buat `MEMORY.md` — konteks AI untuk sesi berikutnya
- [x] Buat `TASKS.md` — file ini

---

## 🔄 Sedang Berjalan

_Tidak ada task aktif saat ini._

---

## 📋 Backlog

| Prioritas | Task | Catatan |
|-----------|------|---------|
| 🔴 High | Validasi semua nama liga di `sch.json` masih bahasa asing | Jalankan `sch.py` dan cek output |
| 🟡 Medium | Scraper untuk sumber tambahan | Livescore, 365scores, dll. |
| 🟡 Medium | Monitoring dashboard | Track match count per source per hari |
| 🟢 Low | Tambah field `sport_icon` di sch.json | URL icon per sport type |
| 🟢 Low | Improve matching accuracy untuk rugby/basketball | Saat ini fokus football |

---

## 🐛 Bug Tracking

| ID | Deskripsi | Status | Diselesaikan |
|----|-----------|--------|--------------|
| BUG-001 | Nama liga Vietnam tidak diterjemahkan | ✅ Fixed | 2026-07-25 |
| BUG-002 | "Amical club" tidak diubah ke "Club Friendly" | ✅ Fixed | 2026-07-25 |
| BUG-003 | AI Matcher tidak jalan tanpa env var `RUN_AI_MATCHER=true` | ✅ Fixed | 2026-07-25 |
| BUG-004 | Tidak ada logo fallback dari soco | ✅ Fixed | 2026-07-25 |

---

## 📊 Statistik

| Metric | Nilai |
|--------|-------|
| Total source files | 6 (soco, bolaloca, flashscore, streamcenter, sportsonline, manual_sch) |
| Enrichment sources | 1 (sofascore) |
| Mapping entries (approx) | 9000+ aliases |
| AI Model | DeepSeek v4 Flash |
