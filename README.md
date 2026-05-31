# sistemanalisiskode

Aplikasi White Box Testing Analyzer untuk mengukur metrik LOC (Lines of Code), McCabe Cyclomatic Complexity, menyajikan visualisasi Control Flow Graph (CFG) interaktif, serta menjabarkan Independent Basis Paths secara komprehensif.

## Fitur Utama
* **Analisis LOC Bersih:** Menghitung baris mentah, baris kosong, dan baris komentar secara akurat.
* **McCabe Cyclomatic Complexity:** Menilai tingkat risiko kode program dan jumlah jalur independen minimum.
* **Control Flow Graph (CFG):** Grafik interaktif yang memisahkan node keputusan (Predicate) dan node proses.
* **Independent Basis Paths:** Menghasilkan urutan jalur logika untuk pengujian unit secara menyeluruh.
* **Ekspor Laporan:** Mengunduh laporan berkualitas cetak (HTML) dan data mentah (JSON).

## Cara Menjalankan
1. Pastikan Python 3.13 dan pustaka pendukung terinstal:
   ```bash
   pip install streamlit graphviz pandas
   ```
2. Jalankan aplikasi menggunakan Streamlit:
   ```bash
   streamlit run app.py
   ```
