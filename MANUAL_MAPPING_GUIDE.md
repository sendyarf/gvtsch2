# Manual Mapping Configuration

File `manual_mapping.json` digunakan untuk mendefinisikan alias/variasi nama tim dan liga yang berbeda di berbagai sumber.

## 📁 Struktur File

```json
{
  "team_aliases": {
    "variant_name": "canonical_name"
  },
  "league_aliases": {
    "variant_name": "canonical_name"
  }
}
```

## 🎯 Cara Menambahkan Alias Baru

### Untuk Tim

Jika Anda menemukan tim dengan nama yang berbeda di berbagai sumber, tambahkan ke `team_aliases`:

```json
{
  "team_aliases": {
    "manchesterutd": "manchesterunited",
    "manutd": "manchesterunited",
    "manunited": "manchesterunited"
  }
}
```

**Catatan Penting:**

- **Key** (kiri): Tulis semua huruf kecil, tanpa spasi, tanpa karakter khusus
- **Value** (kanan): Nama canonical (standar) yang akan digunakan
- Semua variant yang berbeda harus mengarah ke nama canonical yang sama

### Untuk Liga

Sama seperti tim, tambahkan variasi nama liga:

```json
{
  "league_aliases": {
    "laliga": "laliga",
    "ligaespanola": "laliga",
    "primeradivision": "laliga"
  }
}
```

## 📝 Contoh Kasus Penggunaan

### Kasus 1: Nama dalam Bahasa Berbeda

```json
{
  "team_aliases": {
    "gerone": "girona", // Bahasa Prancis
    "girona": "girona", // Bahasa Spanyol/Inggris
    "bologne": "bologna", // Bahasa Prancis
    "bologna": "bologna" // Bahasa Italia
  }
}
```

### Kasus 2: Singkatan

```json
{
  "team_aliases": {
    "manchestercity": "manchestercity",
    "mancity": "manchestercity",
    "mcfc": "manchestercity"
  }
}
```

### Kasus 3: Format Berbeda

```json
{
  "team_aliases": {
    "parissaintgermain": "parissaintgermain",
    "psg": "parissaintgermain",
    "parissg": "parissaintgermain"
  }
}
```

## ⚙️ Normalisasi Otomatis

Sistem akan otomatis menormalisasi nama sebelum mapping:

- Semua huruf dijadikan lowercase
- Karakter khusus dihapus (é → e, ñ → n)
- Spasi dihapus

**Contoh:**

- Input: `"Gérone"` → Normalized: `"gerone"` → Mapped to: `"girona"`
- Input: `"Man. City"` → Normalized: `"mancity"` → Mapped to: `"manchestercity"`

## 🔄 Cara Reload Mapping

Setelah mengedit `manual_mapping.json`, cukup jalankan ulang script:

```bash
python sch.py
```

Tidak perlu restart atau compile ulang!

## ⚠️ Tips & Best Practices

1. **Gunakan nama pendek yang mudah diingat** sebagai canonical name
2. **Konsisten** - gunakan canonical name yang sama di semua variant
3. **Tambahkan komentar** jika perlu menggunakan field `"_comment"`
4. **Test** setelah menambahkan alias baru dengan menjalankan `python sch.py`
5. **Backup** file ini sebelum melakukan perubahan besar

## 🔍 Cara Menemukan Duplikasi

Jika Anda melihat jadwal duplikat di output, cek:

1. **Lihat nama tim di kedua sumber**

   - Apakah ada perbedaan ejaan?
   - Apakah salah satu menggunakan singkatan?

2. **Tambahkan ke mapping**

   ```json
   {
     "team_aliases": {
       "namavarian1": "namastandar",
       "namavarian2": "namastandar"
     }
   }
   ```

3. **Jalankan ulang script**

   ```bash
   python sch.py
   ```

4. **Cek output**
   - Duplikat seharusnya berkurang

## 📊 Format JSON

Pastikan format JSON valid:

- Gunakan double quotes (`"`) bukan single quotes (`'`)
- Tambahkan koma (`,`) di antara entries
- **JANGAN** tambahkan koma di entry terakhir
- Pastikan semua kurung `{}` dan `[]` tertutup dengan benar

**✅ Benar:**

```json
{
  "team_aliases": {
    "team1": "canonical1",
    "team2": "canonical2"
  }
}
```

**❌ Salah:**

```json
{
  "team_aliases": {
    "team1": "canonical1",
    "team2": "canonical2"
  }
}
```

## 🆘 Troubleshooting

### Error: "manual_mapping.json not found"

- File tidak ditemukan di folder yang sama dengan `sch.py`
- Script akan tetap jalan dengan alias kosong

### Error: "Error parsing manual_mapping.json"

- Format JSON tidak valid
- Gunakan JSON validator online untuk cek format
- Pastikan tidak ada koma berlebih atau kurung tidak tertutup

## 🛠️ Alat Bantu: Fetch Team Names

Anda dapat menggunakan script `fetch_teams.py` untuk mengambil nama tim dari API-Football dan memformatnya untuk `manual_mapping.json`.

### Cara Menggunakan

{
  "team_aliases": {
    "variant_name": "canonical_name"
  },
  "league_aliases": {
    "variant_name": "canonical_name"
  }
}
```

## 🎯 Cara Menambahkan Alias Baru

### Untuk Tim

Jika Anda menemukan tim dengan nama yang berbeda di berbagai sumber, tambahkan ke `team_aliases`:

```json
{
  "team_aliases": {
    "manchesterutd": "manchesterunited",
    "manutd": "manchesterunited",
    "manunited": "manchesterunited"
  }
}
```

**Catatan Penting:**

- **Key** (kiri): Tulis semua huruf kecil, tanpa spasi, tanpa karakter khusus
- **Value** (kanan): Nama canonical (standar) yang akan digunakan
- Semua variant yang berbeda harus mengarah ke nama canonical yang sama

### Untuk Liga

Sama seperti tim, tambahkan variasi nama liga:

```json
{
  "league_aliases": {
    "laliga": "laliga",
    "ligaespanola": "laliga",
    "primeradivision": "laliga"
  }
}
```

## 📝 Contoh Kasus Penggunaan

### Kasus 1: Nama dalam Bahasa Berbeda

```json
{
  "team_aliases": {
    "gerone": "girona", // Bahasa Prancis
    "girona": "girona", // Bahasa Spanyol/Inggris
    "bologne": "bologna", // Bahasa Prancis
    "bologna": "bologna" // Bahasa Italia
  }
}
```

### Kasus 2: Singkatan

```json
{
  "team_aliases": {
    "manchestercity": "manchestercity",
    "mancity": "manchestercity",
    "mcfc": "manchestercity"
  }
}
```

### Kasus 3: Format Berbeda

```json
{
  "team_aliases": {
    "parissaintgermain": "parissaintgermain",
    "psg": "parissaintgermain",
    "parissg": "parissaintgermain"
  }
}
```

## ⚙️ Normalisasi Otomatis

Sistem akan otomatis menormalisasi nama sebelum mapping:

- Semua huruf dijadikan lowercase
- Karakter khusus dihapus (é → e, ñ → n)
- Spasi dihapus

**Contoh:**

- Input: `"Gérone"` → Normalized: `"gerone"` → Mapped to: `"girona"`
- Input: `"Man. City"` → Normalized: `"mancity"` → Mapped to: `"manchestercity"`

## 🔄 Cara Reload Mapping

Setelah mengedit `manual_mapping.json`, cukup jalankan ulang script:

```bash
python sch.py
```

Tidak perlu restart atau compile ulang!

## ⚠️ Tips & Best Practices

1. **Gunakan nama pendek yang mudah diingat** sebagai canonical name
2. **Konsisten** - gunakan canonical name yang sama di semua variant
3. **Tambahkan komentar** jika perlu menggunakan field `"_comment"`
4. **Test** setelah menambahkan alias baru dengan menjalankan `python sch.py`
5. **Backup** file ini sebelum melakukan perubahan besar

## 🔍 Cara Menemukan Duplikasi

Jika Anda melihat jadwal duplikat di output, cek:

1. **Lihat nama tim di kedua sumber**

   - Apakah ada perbedaan ejaan?
   - Apakah salah satu menggunakan singkatan?

2. **Tambahkan ke mapping**

   ```json
   {
     "team_aliases": {
       "namavarian1": "namastandar",
       "namavarian2": "namastandar"
     }
   }
   ```

3. **Jalankan ulang script**

   ```bash
   python sch.py
   ```

4. **Cek output**
   - Duplikat seharusnya berkurang

## 📊 Format JSON

Pastikan format JSON valid:

- Gunakan double quotes (`"`) bukan single quotes (`'`)
- Tambahkan koma (`,`) di antara entries
- **JANGAN** tambahkan koma di entry terakhir
- Pastikan semua kurung `{}` dan `[]` tertutup dengan benar

**✅ Benar:**

```json
{
  "team_aliases": {
    "team1": "canonical1",
    "team2": "canonical2"
  }
}
```

**❌ Salah:**

```json
{
  "team_aliases": {
    "team1": "canonical1",
    "team2": "canonical2"
  }
}
```

## 🆘 Troubleshooting

### Error: "manual_mapping.json not found"

- File tidak ditemukan di folder yang sama dengan `sch.py`
- Script akan tetap jalan dengan alias kosong

### Error: "Error parsing manual_mapping.json"

- Format JSON tidak valid
- Gunakan JSON validator online untuk cek format
- Pastikan tidak ada koma berlebih atau kurung tidak tertutup

## 🛠️ Alat Bantu: Fetch Team Names

Anda dapat menggunakan script `fetch_teams.py` untuk mengambil nama tim dari API-Football dan memformatnya untuk `manual_mapping.json`.

### Cara Menggunakan

1.  **Jalankan Script:**
    ```bash
    python fetch_teams.py
    ```
2.  **Pilih Mode:**
    *   **League Mode:** Masukkan ID Liga (contoh: `39` untuk Premier League) untuk mendapatkan daftar semua tim.
    *   **Search Team:** Ketik `search <nama_tim>` (contoh: `search persib`) untuk mencari tim spesifik.
    *   **Search League:** Ketik `league <nama_liga>` (contoh: `league indonesia`) untuk mencari ID liga.

3.  **Copy-Paste Output:**
    *   Script akan menghasilkan output dalam format JSON yang siap di-copy.
    *   Paste output tersebut ke dalam bagian `team_names` di file `manual_mapping.json`.

### Contoh Command Line

Anda juga bisa menjalankan script langsung dengan argumen:

*   **Fetch Liga:** `python fetch_teams.py 39 2023` (ID 39, Musim 2023)
*   **Search Tim:** `python fetch_teams.py search persib`
*   **Search Liga:** `python fetch_teams.py search-league indonesia`
