import streamlit as st
import re
import graphviz
import datetime
import io
import subprocess
import os
import json

# ─────────────────────────────────────────────
# HELPER: LOC METRICS
# ─────────────────────────────────────────────
def calculate_loc_metrics(code_string, total_cost, total_bugs):
    lines = code_string.split('\n')
    total_raw_lines = len(lines)
    blank_lines = 0
    comment_lines = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            blank_lines += 1
        elif stripped.startswith(('//','#','/*','*','<!--','-->')):
            comment_lines += 1

    loc = total_raw_lines - blank_lines - comment_lines
    kloc = loc / 1000 if loc > 0 else 0
    error_per_kloc = (total_bugs / kloc) if kloc > 0 else 0
    cost_per_loc   = (total_cost / total_raw_lines) if total_raw_lines > 0 else 0

    return {
        "Total Baris Kasar": total_raw_lines,
        "Baris Kosong": blank_lines,
        "Baris Komentar": comment_lines,
        "Nilai LOC": loc,
        "Nilai KLOC": round(kloc, 4),
        "Kesalahan per KLOC": round(error_per_kloc, 2),
        "Biaya per LOC": round(cost_per_loc, 2),
    }

# ─────────────────────────────────────────────
# HELPER: NODE / BLOCK SEGMENTATION
# ─────────────────────────────────────────────
PREDICATE_RE = re.compile(r'\b(if|else\s*if|elseif|elif|else|while|for|foreach|switch|case|default|catch|finally|try|do)\b', re.IGNORECASE)
FUNCTION_RE  = re.compile(r'\b(def |function |public |private |protected |static |async )\s*\w+\s*\(', re.IGNORECASE)

def segment_code_into_nodes(code_string):
    """
    Segment code into logical nodes for CFG.
    Returns list of dicts:
      { node_id, label, node_type, start_line, end_line, lines_preview }
    """
    raw_lines = code_string.split('\n')
    nodes = []
    current_block_lines = []
    current_start = 1
    node_id = 1

    def flush_block(end_line):
        nonlocal node_id, current_block_lines, current_start
        if not current_block_lines:
            return
        preview = '; '.join(l.strip() for l in current_block_lines[:3] if l.strip())
        if len(current_block_lines) > 3:
            preview += ' ...'
        nodes.append({
            "node_id": node_id,
            "label": f"Node {node_id}",
            "node_type": "process",
            "start_line": current_start,
            "end_line": end_line,
            "lines_preview": preview or "(blank/comment)",
            "raw_lines": list(current_block_lines),
        })
        node_id += 1
        current_block_lines = []
        current_start = end_line + 1

    for i, raw_line in enumerate(raw_lines, start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith(('//','#','/*','*','<!--')):
            current_block_lines.append(raw_line)
            continue

        is_decision = bool(PREDICATE_RE.search(stripped))
        is_function = bool(FUNCTION_RE.search(stripped))

        if is_function and node_id > 1:
            flush_block(i - 1)

        if is_decision:
            # flush whatever came before
            if current_block_lines:
                flush_block(i - 1)
            # create decision node
            preview = stripped[:80] + ('...' if len(stripped) > 80 else '')
            nodes.append({
                "node_id": node_id,
                "label": f"Node {node_id}",
                "node_type": "decision",
                "start_line": i,
                "end_line": i,
                "lines_preview": preview,
                "raw_lines": [raw_line],
            })
            node_id += 1
            current_start = i + 1
        else:
            current_block_lines.append(raw_line)

    flush_block(len(raw_lines))
    return nodes

# ─────────────────────────────────────────────
# HELPER: CYCLOMATIC COMPLEXITY
# ─────────────────────────────────────────────
def calculate_cyclomatic_complexity(nodes):
    """V(G) = E - N + 2P  (simplified: P + 1 where P = decision nodes)"""
    p = sum(1 for n in nodes if n["node_type"] == "decision")
    cc = p + 1

    n_count = len(nodes)
    # Edges: sequential (n-1) + each decision adds 1 extra branch
    e_count = (n_count - 1) + p
    cc_full = e_count - n_count + 2  # standard formula

    if cc <= 10:
        risk_level = "Rendah (Low Risk)"
        risk_color = "#28a745"
        desc = "Program sederhana dan mudah diuji. Semua jalur dapat diverifikasi dengan mudah."
    elif cc <= 20:
        risk_level = "Sedang (Moderate Complexity)"
        risk_color = "#ffc107"
        desc = "Kompleksitas masih terkelola. Disarankan memecah fungsi yang terlalu panjang."
    elif cc <= 50:
        risk_level = "Tinggi (High Risk)"
        risk_color = "#fd7e14"
        desc = "Algoritma padat dan rawan bug. Sangat disarankan refactoring ke fungsi terpisah."
    else:
        risk_level = "Sangat Tinggi (Untestable)"
        risk_color = "#dc3545"
        desc = "Kode tidak dapat diuji dengan baik. Wajib dilakukan refactoring menyeluruh."

    return {
        "P": p,
        "N": n_count,
        "E": e_count,
        "CC": cc,
        "CC_formula": cc_full,
        "risk_level": risk_level,
        "risk_color": risk_color,
        "desc": desc,
    }

# ─────────────────────────────────────────────
# HELPER: CFG GRAPHVIZ (numbered circles)
# ─────────────────────────────────────────────
def generate_cfg(nodes):
    dot = graphviz.Digraph("CFG")
    dot.attr(rankdir='TB', bgcolor='transparent', fontname='Arial')
    dot.attr('node', fontname='Arial', fontsize='13')
    dot.attr('edge', fontname='Arial', fontsize='11', color='#444444')

    # START node
    dot.node('START', 'START', shape='oval', style='filled,bold',
             fillcolor='#1a472a', fontcolor='white', color='#1a472a', width='1')

    for n in nodes:
        nid = str(n["node_id"])
        if n["node_type"] == "decision":
            dot.node(nid, nid, shape='circle', style='filled',
                     fillcolor='#e8c547', fontcolor='#1a1a1a',
                     color='#c8a020', width='0.8', fixedsize='true',
                     penwidth='2')
        else:
            dot.node(nid, nid, shape='circle', style='filled',
                     fillcolor='#2c5f8a', fontcolor='white',
                     color='#1a3f5f', width='0.8', fixedsize='true')

    # END node
    dot.node('END', 'END', shape='oval', style='filled,bold',
             fillcolor='#6b1a1a', fontcolor='white', color='#6b1a1a', width='1')

    # Edges
    if nodes:
        dot.edge('START', str(nodes[0]["node_id"]))

    for i, n in enumerate(nodes):
        nid = str(n["node_id"])
        if n["node_type"] == "decision":
            next_nid = str(nodes[i+1]["node_id"]) if i+1 < len(nodes) else 'END'
            after_nid = str(nodes[i+2]["node_id"]) if i+2 < len(nodes) else 'END'
            dot.edge(nid, next_nid, label='True', color='#28a745', fontcolor='#28a745')
            dot.edge(nid, after_nid, label='False', color='#dc3545', fontcolor='#dc3545', style='dashed')
        else:
            next_nid = str(nodes[i+1]["node_id"]) if i+1 < len(nodes) else 'END'
            dot.edge(nid, next_nid)

    if nodes:
        dot.edge(str(nodes[-1]["node_id"]), 'END')

    return dot

# ─────────────────────────────────────────────
# HELPER: INDEPENDENT PATHS
# ─────────────────────────────────────────────
def generate_independent_paths(nodes, cc):
    paths = []
    node_ids = [n["node_id"] for n in nodes]
    decision_ids = [n["node_id"] for n in nodes if n["node_type"] == "decision"]

    if not node_ids:
        return paths

    # Path 1: straight through
    paths.append({"path_no": 1, "description": "Jalur normal (semua kondisi False)", "sequence": ["START"] + [str(i) for i in node_ids] + ["END"]})

    # Additional paths: each decision branching True
    for idx, did in enumerate(decision_ids):
        if len(paths) >= cc:
            break
        path_seq = ["START"]
        for n in nodes:
            path_seq.append(str(n["node_id"]))
            if n["node_id"] == did:
                path_seq.append(f"({str(did)}→True branch)")
                break
        path_seq.append("END")
        paths.append({
            "path_no": len(paths) + 1,
            "description": f"Jalur dengan Node {did} = True",
            "sequence": path_seq,
        })

    return paths[:cc]

# ─────────────────────────────────────────────
# REPORT EXPORT (HTML → print-friendly)
# ─────────────────────────────────────────────
def build_html_report(project_name, analyst_name, loc_metrics, cc_data, nodes, paths, code_input, cfg_svg_str):
    today = datetime.date.today().strftime("%d %B %Y")
    node_rows = ""
    for n in nodes:
        badge = "🔶 Decision" if n["node_type"] == "decision" else "🔵 Process"
        node_rows += f"""
        <tr>
            <td class="center bold">{n['node_id']}</td>
            <td class="center">{badge}</td>
            <td class="center">{n['start_line']}</td>
            <td class="center">{n['end_line']}</td>
            <td>{n['lines_preview']}</td>
        </tr>"""

    path_rows = ""
    for p in paths:
        path_rows += f"""
        <tr>
            <td class="center bold">P{p['path_no']}</td>
            <td>{p['description']}</td>
            <td class="mono">{' → '.join(p['sequence'])}</td>
        </tr>"""

    cfg_block = cfg_svg_str if cfg_svg_str else "<p><em>CFG tidak dapat dirender.</em></p>"

    html = f"""<!DOCTYPE html>
<html lang="id">
<head>
<meta charset="UTF-8"/>
<title>Laporan White Box Testing – {project_name}</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Source+Serif+4:wght@400;600;700&family=JetBrains+Mono:wght@400;600&family=Inter:wght@400;500;600&display=swap');
  *{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:'Inter',sans-serif;font-size:10.5pt;color:#1a1a2e;background:#fff;line-height:1.6}}
  .cover{{min-height:100vh;display:flex;flex-direction:column;align-items:center;justify-content:center;background:linear-gradient(160deg,#0f2027,#203a43,#2c5364);color:white;text-align:center;padding:60px 40px;page-break-after:always}}
  .cover .logo{{font-size:48pt;margin-bottom:20px}}
  .cover h1{{font-family:'Source Serif 4',serif;font-size:22pt;font-weight:700;margin-bottom:8px;line-height:1.3}}
  .cover h2{{font-family:'Source Serif 4',serif;font-size:14pt;font-weight:400;opacity:.8;margin-bottom:40px}}
  .cover .meta{{border-top:1px solid rgba(255,255,255,.3);padding-top:24px;margin-top:24px;opacity:.85;font-size:10pt;line-height:2}}
  .content{{max-width:900px;margin:0 auto;padding:40px 48px}}
  h2{{font-family:'Source Serif 4',serif;font-size:14pt;font-weight:700;color:#0f2027;border-bottom:2px solid #2c5364;padding-bottom:6px;margin:32px 0 16px}}
  h3{{font-size:11pt;font-weight:600;color:#203a43;margin:20px 0 10px}}
  .card-row{{display:grid;gap:16px;margin-bottom:24px}}
  .card-row.four{{grid-template-columns:repeat(4,1fr)}}
  .card-row.three{{grid-template-columns:repeat(3,1fr)}}
  .card{{background:#f0f4f8;border-radius:8px;padding:16px;text-align:center;border-left:4px solid #2c5364}}
  .card .val{{font-size:18pt;font-weight:700;color:#0f2027}}
  .card .lbl{{font-size:8.5pt;color:#555;margin-top:4px}}
  .risk-badge{{display:inline-block;background:{cc_data['risk_color']};color:white;padding:6px 18px;border-radius:20px;font-weight:600;font-size:10.5pt}}
  table{{width:100%;border-collapse:collapse;margin:12px 0 24px;font-size:9.5pt}}
  th{{background:#0f2027;color:white;padding:9px 12px;text-align:left;font-weight:600}}
  td{{padding:8px 12px;border-bottom:1px solid #e0e6ed}}
  tr:nth-child(even) td{{background:#f7f9fc}}
  .center{{text-align:center}}
  .bold{{font-weight:600}}
  .mono{{font-family:'JetBrains Mono',monospace;font-size:8.5pt}}
  pre{{background:#0f1923;color:#a8d8ea;padding:20px;border-radius:8px;font-family:'JetBrains Mono',monospace;font-size:8pt;overflow-x:auto;white-space:pre-wrap;word-break:break-all;margin:12px 0 24px}}
  .cfg-wrap{{background:#f7f9fc;border:1px solid #dde3ea;border-radius:8px;padding:20px;text-align:center;margin:12px 0 24px}}
  .cfg-wrap svg{{max-width:100%;height:auto}}
  .formula-box{{background:#fff8e1;border-left:4px solid #ffc107;border-radius:6px;padding:14px 18px;margin:12px 0;font-family:'JetBrains Mono',monospace;font-size:10pt}}
  .conclusion{{background:#e8f4fd;border-radius:8px;padding:20px 24px;margin-top:16px;border-left:5px solid #2c5364;line-height:1.8}}
  .footer{{text-align:center;color:#999;font-size:8pt;margin-top:48px;padding-top:16px;border-top:1px solid #e0e6ed}}
  @media print{{
    .cover{{min-height:auto;padding:40px}}
    .content{{padding:20px 32px}}
    pre{{font-size:7pt}}
  }}
</style>
</head>
<body>

<!-- COVER PAGE -->
<div class="cover">
  <div class="logo">🧪</div>
  <h1>LAPORAN MANAJEMEN KUALITAS PERANGKAT LUNAK</h1>
  <h2>White Box Testing — LOC Metrics &amp; Basis Path Analysis</h2>
  <div class="meta">
    <div><strong>Nama Proyek:</strong> {project_name}</div>
    <div><strong>Analis:</strong> {analyst_name}</div>
    <div><strong>Tanggal:</strong> {today}</div>
    <div><strong>Metode:</strong> McCabe Cyclomatic Complexity + LOC Analysis</div>
  </div>
</div>

<!-- CONTENT -->
<div class="content">

  <!-- 1. LOC -->
  <h2>I. Pengujian Metrik LOC (Lines of Code)</h2>
  <p>Analisis LOC mengukur ukuran dan kepadatan kode secara kuantitatif dengan memisahkan baris aktif, baris kosong, dan baris komentar.</p>
  <h3>Rumus</h3>
  <div class="formula-box">
    LOC  = Total Baris Kasar − Baris Kosong − Baris Komentar<br>
    KLOC = LOC / 1000<br>
    Kesalahan/KLOC = Total Bug / KLOC<br>
    Biaya/LOC      = Total Biaya / Total Baris Kasar
  </div>
  <h3>Hasil Perhitungan</h3>
  <div class="card-row four">
    <div class="card"><div class="val">{loc_metrics['Total Baris Kasar']}</div><div class="lbl">Total Baris Kasar</div></div>
    <div class="card"><div class="val">{loc_metrics['Baris Kosong']}</div><div class="lbl">Baris Kosong</div></div>
    <div class="card"><div class="val">{loc_metrics['Baris Komentar']}</div><div class="lbl">Baris Komentar</div></div>
    <div class="card"><div class="val">{loc_metrics['Nilai LOC']}</div><div class="lbl">Nilai LOC Bersih</div></div>
  </div>
  <div class="card-row three">
    <div class="card"><div class="val">{loc_metrics['Nilai KLOC']}</div><div class="lbl">Nilai KLOC</div></div>
    <div class="card"><div class="val">{loc_metrics['Kesalahan per KLOC']}</div><div class="lbl">Kesalahan / KLOC</div></div>
    <div class="card"><div class="val">Rp {loc_metrics['Biaya per LOC']:,.0f}</div><div class="lbl">Biaya / LOC</div></div>
  </div>

  <!-- 2. CFG & CC -->
  <h2>II. Control Flow Graph (CFG) &amp; Cyclomatic Complexity</h2>
  <h3>Rumus McCabe</h3>
  <div class="formula-box">
    V(G) = P + 1&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;(P = jumlah predikat / simpul keputusan)<br>
    V(G) = E − N + 2 &nbsp;(E = edges, N = nodes)
  </div>
  <div class="card-row four">
    <div class="card"><div class="val">{cc_data['N']}</div><div class="lbl">Total Node (N)</div></div>
    <div class="card"><div class="val">{cc_data['E']}</div><div class="lbl">Total Edge (E)</div></div>
    <div class="card"><div class="val">{cc_data['P']}</div><div class="lbl">Predikat (P)</div></div>
    <div class="card"><div class="val">{cc_data['CC']}</div><div class="lbl">Cyclomatic Complexity V(G)</div></div>
  </div>
  <p>Status Risiko: <span class="risk-badge">{cc_data['risk_level']}</span></p>
  <p style="margin-top:10px">{cc_data['desc']}</p>

  <h3>Visualisasi CFG</h3>
  <div class="cfg-wrap">
    {cfg_block}
  </div>
  <p style="font-size:9pt;color:#555;text-align:center">🟡 = Decision Node (simpul keputusan/predikat) &nbsp;|&nbsp; 🔵 = Process Node (simpul proses)</p>

  <!-- 3. NODE TABLE -->
  <h2>III. Tabel Penjabaran Node</h2>
  <p>Setiap node merepresentasikan satu blok logika atau satu titik keputusan dalam alur program.</p>
  <table>
    <thead>
      <tr><th>No. Node</th><th>Tipe</th><th>Baris Mulai</th><th>Baris Akhir</th><th>Keterangan Kode</th></tr>
    </thead>
    <tbody>{node_rows}</tbody>
  </table>

  <!-- 4. INDEPENDENT PATHS -->
  <h2>IV. Jalur Independen (Basis Path)</h2>
  <p>Jumlah jalur independen = V(G) = <strong>{cc_data['CC']}</strong>. Berikut daftar jalur yang harus diuji:</p>
  <table>
    <thead>
      <tr><th style="width:60px">Jalur</th><th>Deskripsi</th><th>Urutan Node</th></tr>
    </thead>
    <tbody>{path_rows}</tbody>
  </table>

  <!-- 5. KODE SUMBER -->
  <h2>V. Kode Sumber yang Dianalisis</h2>
  <pre>{code_input}</pre>

  <!-- 6. KESIMPULAN -->
  <h2>VI. Kesimpulan &amp; Rekomendasi</h2>
  <div class="conclusion">
    <p><strong>Ukuran Kode (LOC):</strong> Program memiliki <strong>{loc_metrics['Nilai LOC']} LOC bersih</strong> dari total {loc_metrics['Total Baris Kasar']} baris kasar. KLOC sebesar <strong>{loc_metrics['Nilai KLOC']}</strong>, dengan estimasi kesalahan <strong>{loc_metrics['Kesalahan per KLOC']} bug/KLOC</strong> dan biaya produksi <strong>Rp {loc_metrics['Biaya per LOC']:,.0f}/baris</strong>.</p>
    <br>
    <p><strong>Kompleksitas (CFG):</strong> Berdasarkan analisis McCabe, kode memiliki <strong>{cc_data['P']} simpul keputusan</strong>, menghasilkan nilai <em>Cyclomatic Complexity</em> <strong>V(G) = {cc_data['CC']}</strong>. Sistem tergolong <strong>{cc_data['risk_level']}</strong>. {cc_data['desc']}</p>
    <br>
    <p><strong>Basis Path:</strong> Terdapat <strong>{cc_data['CC']} jalur independen</strong> yang harus dicakup dalam test case untuk memastikan pengujian white box yang komprehensif.</p>
    <br>
    <p><strong>Rekomendasi:</strong> {"Lanjutkan ke tahap pengujian unit untuk setiap jalur independen. Dokumentasikan test case berdasarkan setiap basis path yang teridentifikasi." if cc_data['CC'] <= 10 else "Pertimbangkan pemisahan fungsi/modul sebelum melanjutkan ke production. Prioritaskan refactoring pada decision node yang paling kompleks."}</p>
  </div>

  <div class="footer">
    Laporan dibuat otomatis oleh White Box Testing Analyzer &nbsp;|&nbsp; {today} &nbsp;|&nbsp; Analis: {analyst_name}
  </div>
</div>
</body>
</html>"""
    return html

# ─────────────────────────────────────────────
# STREAMLIT UI
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="White Box Testing Analyzer",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Custom CSS for Clean, Professional Hybrid Theme (Dark Sidebar + Light Main Canvas)
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* Global Reset & Base Theme - Clean light Slate for main body */
html, body, [class*="css"], [data-testid="stAppViewContainer"] {
    font-family: 'Inter', sans-serif !important;
    background-color: #f8fafc !important; /* Tailwind Slate 50 */
    color: #0f172a !important; /* Slate 900 */
}

/* ─────────────────────────────────────────────
   SIDEBAR CUSTOM STYLING: EXCLUSIVELY DARK
   ───────────────────────────────────────────── */
[data-testid="stSidebar"] {
    background-color: #090d16 !important; /* Deep dark slate sidebar */
    border-right: 1px solid #1e293b !important;
}
[data-testid="stSidebar"] * {
    color: #e2e8f0 !important; /* Light text for elements inside sidebar */
}
[data-testid="stSidebar"] h3 {
    font-family: 'Inter', sans-serif !important;
    color: #ffffff !important;
    font-weight: 600 !important;
    font-size: 1.15rem !important;
    margin-bottom: 15px !important;
}
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p {
    color: #94a3b8 !important; /* Light Slate Gray for input labels in sidebar */
    font-weight: 500 !important;
}
[data-testid="stSidebar"] input {
    background-color: #111827 !important; /* Sleek dark input field backgrounds */
    color: #ffffff !important;
    border: 1px solid #374151 !important;
    border-radius: 6px !important;
}
[data-testid="stSidebar"] input:focus {
    border-color: #6366f1 !important; /* Indigo active border */
}
[data-testid="stSidebar"] hr {
    border-color: #1e293b !important;
}

/* ─────────────────────────────────────────────
   MAIN PAGE ELEMENT STYLING: LIGHT SaaS STYLE
   ───────────────────────────────────────────── */

/* Make all main page input widget labels slate dark */
[data-testid="stWidgetLabel"] p {
    color: #334155 !important; /* Slate 700 */
    font-weight: 500 !important;
}

/* Header Container - Clean & Simple Light Bordered */
.main-header {
    background-color: #ffffff;
    border: 1px solid #e2e8f0; /* Slate 200 */
    color: #0f172a;
    padding: 24px 32px;
    border-radius: 12px;
    margin-bottom: 25px;
    text-align: left;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
}
.main-header h1 {
    font-family: 'Inter', sans-serif !important;
    font-size: 1.8rem;
    font-weight: 700;
    margin-bottom: 6px;
    color: #0f172a;
}
.main-header p {
    opacity: 1;
    font-size: 0.9rem;
    color: #64748b; /* Slate 500 */
}

/* Code Editor Wrapper Header - Dark Slate Console */
.editor-header {
    background-color: #1e293b;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 8px 16px;
    border: 1px solid #1e293b;
    border-bottom: none;
}
.editor-title {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.8rem;
    color: #94a3b8;
}

/* Custom Text Area Input Override - Dark Editor (Matches IDE) */
.stTextArea textarea {
    background-color: #0f172a !important;
    color: #ffffff !important; /* Bright white for typed code */
    border: 1px solid #1e293b !important;
    border-top-left-radius: 0px !important;
    border-top-right-radius: 0px !important;
    border-bottom-left-radius: 8px !important;
    border-bottom-right-radius: 8px !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 0.9rem !important;
    padding: 14px !important;
}
.stTextArea textarea::placeholder {
    color: #94a3b8 !important; /* Bright slate-gray for placeholder */
    opacity: 0.85 !important; /* Ensure high visibility */
}
.stTextArea textarea:focus {
    border-color: #4f46e5 !important; /* Indigo 600 */
    box-shadow: none !important;
}

/* Minimalist Card Layout - Pure White SaaS style */
.metric-card {
    background: #ffffff;
    border: 1px solid #e2e8f0; /* Slate 200 */
    border-radius: 8px;
    padding: 16px;
    text-align: left;
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
}
.metric-card:hover {
    border-color: #4f46e5; /* Indigo 600 */
    box-shadow: 0 4px 12px rgba(79, 70, 229, 0.05);
}
.metric-card .val {
    font-family: 'Inter', sans-serif;
    font-size: 1.7rem;
    font-weight: 700;
    color: #0f172a;
}
.metric-card .lbl {
    font-size: 0.75rem;
    color: #64748b;
    margin-top: 4px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

/* Risk Status Banner - Clean Light Border Left */
.risk-card {
    border-radius: 8px;
    padding: 20px;
    text-align: left;
    border: 1px solid #e2e8f0;
    background-color: #ffffff;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}

.formula-box {
    background: #f8fafc !important; /* Slate 50 */
    border-left: 3px solid #4f46e5; /* Indigo 600 */
    border-radius: 6px;
    padding: 12px 16px;
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.8rem;
    color: #334155;
    margin: 12px 0;
    border-top: 1px solid #e2e8f0;
    border-right: 1px solid #e2e8f0;
    border-bottom: 1px solid #e2e8f0;
}

.section-label {
    font-family: 'Inter', sans-serif !important;
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: #64748b;
    margin-bottom: 12px;
}

/* Tabs Styling - Light SaaS Minimalist */
.stTabs [data-baseweb="tab-list"] {
    gap: 4px;
    background-color: #f1f5f9 !important; /* Slate 100 */
    padding: 4px;
    border-radius: 8px;
    border: 1px solid #e2e8f0;
}
.stTabs [data-baseweb="tab"] {
    height: 36px !important;
    padding: 0 14px !important;
    border-radius: 6px !important;
    background-color: transparent !important;
    color: #64748b !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 500 !important;
    font-size: 0.85rem !important;
    border: none !important;
}
.stTabs [data-baseweb="tab"]:hover {
    color: #0f172a !important;
    background-color: #e2e8f0 !important;
}
.stTabs [aria-selected="true"] {
    background-color: #ffffff !important;
    color: #4f46e5 !important; /* Indigo 600 */
    font-weight: 600 !important;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1) !important;
}

/* Buttons - Solid Minimalist */
.stButton button {
    background: #4f46e5 !important; /* Indigo 600 */
    color: #ffffff !important;
    font-family: 'Inter', sans-serif !important;
    font-weight: 600 !important;
    border: none !important;
    border-radius: 6px !important;
    padding: 8px 20px !important;
    font-size: 0.9rem !important;
    transition: background-color 0.2s ease !important;
    box-shadow: none !important;
}
.stButton button:hover {
    background: #4338ca !important; /* Indigo 700 */
    transform: none !important;
}

/* Reset Button Style */
div[data-testid="stHorizontalBlock"] div:nth-child(2) button {
    background: transparent !important;
    color: #64748b !important;
    border: 1px solid #e2e8f0 !important;
}
div[data-testid="stHorizontalBlock"] div:nth-child(2) button:hover {
    border-color: #ef4444 !important;
    color: #ef4444 !important;
    background: rgba(239, 68, 68, 0.05) !important;
}

/* Clean Placeholder Panel - Pure White Bordered */
.waiting-card {
    border: 1px dashed #cbd5e1;
    padding: 48px 32px;
    border-radius: 8px;
    text-align: center;
    background-color: #ffffff;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.02);
}
.waiting-card h3 {
    font-family: 'Inter', sans-serif !important;
    color: #0f172a;
    font-weight: 600;
    font-size: 1.1rem;
}
.waiting-card p {
    color: #64748b;
    margin-top: 8px;
    font-size: 0.85rem;
}

/* Tables styling */
[data-testid="stDataFrame"] {
    border: 1px solid #e2e8f0 !important;
    border-radius: 8px !important;
}

/* Ensure HTML report preview text stays high-contrast dark gray on its white background */
.report-preview-container * {
    color: #1a1a2e !important;
}
.report-preview-container .cover * {
    color: #ffffff !important; /* Keep cover page text white */
}
.report-preview-container pre {
    color: #a8d8ea !important; /* Keep code block text light */
}
.report-preview-container .formula-box, .report-preview-container .formula-box * {
    color: #0f2027 !important; /* Keep formula text dark */
}

</style>
""", unsafe_allow_html=True)

# Main Dashboard Header - Flat Minimalist UI
st.markdown("""
<div class="main-header">
  <h1>White Box Testing Analyzer</h1>
  <p>Perkakas Analisis Kode Statis — Kompleksitas McCabe & Metrik LOC</p>
</div>
""", unsafe_allow_html=True)

# ── SIDEBAR: Project Info & Parameters ──────
with st.sidebar:
    st.markdown("### Detail Proyek")
    project_name = st.text_input("Nama Proyek", value="Sistem Perangkat Lunak A")
    analyst_name = st.text_input("Nama Analis", value="Tim QA")
    st.divider()
    st.markdown("### Parameter Metrik")
    input_biaya = st.number_input("Anggaran Proyek (Rp)", min_value=0, value=4_000_000, step=100_000, format="%d")
    input_bug   = st.number_input("Perkiraan Jumlah Bug", min_value=0, value=2)
    st.divider()
    st.markdown("""
    <div style="text-align: center; color: #64748b; font-size: 0.75rem; line-height: 1.5;">
        <strong>bayuadisaputro studio dev</strong>
    </div>
    """, unsafe_allow_html=True)

# ── DUAL COLUMN MAIN LAYOUT ──────────────────
col_left, col_right = st.columns([2, 3], gap="large")

# ── LEFT COLUMN: Code Control Console ────────
with col_left:
    st.markdown('<div class="section-label">Ruang Kerja Kode</div>', unsafe_allow_html=True)
    
    # Flat Professional Editor Header
    st.markdown("""
    <div class="editor-header">
        <span class="editor-title">editor_kode_sumber.py</span>
    </div>
    """, unsafe_allow_html=True)
    
    code_input = st.text_area(
        "Source Code",
        height=350,
        placeholder="// Tempelkan kode sumber Anda di sini (PHP, Python, JS, C++)\nfunction demo(x) {\n    if (x > 10) {\n        return 'Besar';\n    } else {\n        return 'Kecil';\n    }\n}",
        label_visibility="collapsed",
    )
    
    st.markdown("<div style='height: 10px;'></div>", unsafe_allow_html=True)
    
    # Action buttons
    col_btn1, col_btn2 = st.columns([3, 1])
    with col_btn1:
        run_btn = st.button("JALANKAN ANALISIS", use_container_width=True)
    with col_btn2:
        clear_btn = st.button("RESET", use_container_width=True)
        
    if clear_btn:
        st.rerun()

# ── RIGHT COLUMN: Diagnostic Dashboard ──────
with col_right:
    st.markdown('<div class="section-label">Hasil Diagnosis Analisis</div>', unsafe_allow_html=True)
    
    if run_btn:
        if not code_input.strip():
            st.warning("⚠️ Silakan masukkan kode sumber Anda terlebih dahulu pada ruang kerja.")
            st.stop()
            
        with st.spinner("Menganalisis kompleksitas kode..."):
            loc_metrics = calculate_loc_metrics(code_input, input_biaya, input_bug)
            nodes       = segment_code_into_nodes(code_input)
            cc_data     = calculate_cyclomatic_complexity(nodes)
            paths       = generate_independent_paths(nodes, cc_data["CC"])
            cfg_graph   = generate_cfg(nodes)
            
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "METRIK LOC",
            "DIAGRAM CFG",
            "KOMPLEKSITAS MCCABE",
            "JALUR BASIS",
            "EKSPOR LAPORAN",
        ])
        
        # ── TAB 1: METRIK LOC ──
        with tab1:
            st.markdown("### Kepadatan Kode (Lines of Code)")
            st.markdown('<div class="formula-box">LOC = Baris Kasar − Baris Kosong − Baris Komentar<br>KLOC = LOC / 1000<br>Biaya/LOC = Total Anggaran / Baris Kasar</div>', unsafe_allow_html=True)
            
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.markdown(f'<div class="metric-card"><div class="val">{loc_metrics["Total Baris Kasar"]}</div><div class="lbl">Baris Kasar</div></div>', unsafe_allow_html=True)
            with c2:
                st.markdown(f'<div class="metric-card"><div class="val">{loc_metrics["Baris Kosong"]}</div><div class="lbl">Baris Kosong</div></div>', unsafe_allow_html=True)
            with c3:
                st.markdown(f'<div class="metric-card"><div class="val">{loc_metrics["Baris Komentar"]}</div><div class="lbl">Baris Komentar</div></div>', unsafe_allow_html=True)
            with c4:
                st.markdown(f'<div class="metric-card"><div class="val">{loc_metrics["Nilai LOC"]}</div><div class="lbl">Nilai LOC</div></div>', unsafe_allow_html=True)
                
            st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
            
            c5, c6, c7 = st.columns(3)
            with c5:
                st.markdown(f'<div class="metric-card"><div class="val">{loc_metrics["Nilai KLOC"]:.4f}</div><div class="lbl">Nilai KLOC</div></div>', unsafe_allow_html=True)
            with c6:
                st.markdown(f'<div class="metric-card"><div class="val">{loc_metrics["Kesalahan per KLOC"]}</div><div class="lbl">Kesalahan / KLOC</div></div>', unsafe_allow_html=True)
            with c7:
                st.markdown(f'<div class="metric-card"><div class="val">Rp {loc_metrics["Biaya per LOC"]:,.0f}</div><div class="lbl">Biaya / LOC</div></div>', unsafe_allow_html=True)

        # ── TAB 2: CFG & NODE TABLE ──
        with tab2:
            st.markdown("### Control Flow Graph (CFG) & Segmentasi Node")
            col_cfg, col_tbl = st.columns([1, 1], gap="medium")
            
            with col_cfg:
                st.graphviz_chart(cfg_graph, use_container_width=True)
                st.caption("🟡 Kuning = Node Keputusan (Predikat)  |  🔵 Biru = Node Proses  |  ⬛ MULAI/SELESAI")
                
            with col_tbl:
                st.markdown("#### Detail Segmentasi Node")
                if nodes:
                    import pandas as pd
                    df = pd.DataFrame([{
                        "Node": n["node_id"],
                        "Tipe": "Keputusan" if n["node_type"] == "decision" else "Proses",
                        "Rentang Baris": f"{n['start_line']} - {n['end_line']}",
                        "Pratinjau": n["lines_preview"],
                    } for n in nodes])
                    st.dataframe(df, use_container_width=True, hide_index=True)
                else:
                    st.info("Tidak ada node yang terfragmentasi.")

        # ── TAB 3: CYCLOMATIC COMPLEXITY ──
        with tab3:
            st.markdown("### Analisis Kompleksitas Siklomatis McCabe")
            st.markdown('<div class="formula-box">V(G) = P + 1  &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;(P = Jumlah Node Keputusan / Predikat)<br>V(G) = E − N + 2 &nbsp;&nbsp;(E = Jumlah Sisi / Edge, N = Jumlah Simpul / Node)</div>', unsafe_allow_html=True)
            
            c1, c2, c3, c4 = st.columns(4)
            with c1:
                st.markdown(f'<div class="metric-card"><div class="val">{cc_data["N"]}</div><div class="lbl">Node (N)</div></div>', unsafe_allow_html=True)
            with c2:
                st.markdown(f'<div class="metric-card"><div class="val">{cc_data["E"]}</div><div class="lbl">Edge (E)</div></div>', unsafe_allow_html=True)
            with c3:
                st.markdown(f'<div class="metric-card"><div class="val">{cc_data["P"]}</div><div class="lbl">Predikat (P)</div></div>', unsafe_allow_html=True)
            with c4:
                st.markdown(f'<div class="metric-card"><div class="val">{cc_data["CC"]}</div><div class="lbl">Kompleksitas V(G)</div></div>', unsafe_allow_html=True)
                
            st.markdown(f"""
            <div class="risk-card" style="border-left: 4px solid {cc_data['risk_color']};">
                <div style="font-size:1.05rem; font-weight:700; color:{cc_data['risk_color']}; letter-spacing:0.02em; display: flex; align-items: center; gap: 8px;">
                    ● STATUS RISIKO: {cc_data['risk_level']}
                </div>
                <div style="margin-top:8px; color:#334155; font-size:0.9rem; line-height:1.5;">
                    {cc_data['desc']}
                </div>
                <div style="margin-top:12px; font-size:0.8rem; color:#64748b;">
                    Nilai kompleksitas sebesar <strong>{cc_data['CC']}</strong> menandakan bahwa setidaknya 
                    <strong>{cc_data['CC']} jalur independen</strong> harus dicakup oleh pengujian kasus uji (test cases).
                </div>
            </div>
            """, unsafe_allow_html=True)

        # ── TAB 4: BASIS PATH TESTING ──
        with tab4:
            st.markdown("### Jalur Basis Logika Independen (Independent Basis Paths)")
            st.info(f"Formula kompleksitas V(G) mewajibkan setidaknya **{cc_data['CC']} jalur independen** di bawah ini untuk diuji sepenuhnya:")
            
            if paths:
                import pandas as pd
                df_paths = pd.DataFrame([{
                    "ID Jalur": f"P{p['path_no']}",
                    "Deskripsi": p["description"],
                    "Urutan Node": " ➔ ".join(p["sequence"]),
                } for p in paths])
                st.dataframe(df_paths, use_container_width=True, hide_index=True)
            else:
                st.warning("Jalur basis tidak dapat dievaluasi.")

        # ── TAB 5: EXPORT REPORT ──
        with tab5:
            st.markdown("### Ekspor Laporan Kualitas")
            st.success("Analisis selesai! Anda dapat mengunduh hasil laporan dalam bentuk halaman HTML siap cetak atau data mentah JSON di bawah ini:")
            
            try:
                cfg_svg_bytes = cfg_graph.pipe(format='svg')
                cfg_svg_str   = cfg_svg_bytes.decode('utf-8')
            except Exception:
                cfg_svg_str   = ""
                
            html_report = build_html_report(
                project_name, analyst_name,
                loc_metrics, cc_data, nodes, paths,
                code_input, cfg_svg_str,
            )
            
            st.markdown("<div style='height: 15px;'></div>", unsafe_allow_html=True)
            col_dl1, col_dl2 = st.columns(2)
            with col_dl1:
                st.download_button(
                    label="UNDUH LAPORAN HTML (SIAP CETAK)",
                    data=html_report.encode("utf-8"),
                    file_name=f"laporan_wbt_{project_name.replace(' ','_')}.html",
                    mime="text/html",
                    use_container_width=True,
                    type="primary",
                )
            with col_dl2:
                st.download_button(
                    label="UNDUH DATA MENTAH JSON",
                    data=json.dumps({
                        "project": project_name,
                        "analyst": analyst_name,
                        "loc_metrics": loc_metrics,
                        "cc_data": {k: v for k, v in cc_data.items() if k != "risk_color"},
                        "nodes": [{k: v for k, v in n.items() if k != "raw_lines"} for n in nodes],
                        "paths": paths,
                    }, indent=2, ensure_ascii=False).encode("utf-8"),
                    file_name=f"data_wbt_{project_name.replace(' ','_')}.json",
                    mime="application/json",
                    use_container_width=True,
                )
                
            st.markdown("<div style='height: 25px;'></div>", unsafe_allow_html=True)
            st.markdown("#### Pratinjau Halaman Cetak Laporan:")
            st.markdown(f"<div class='report-preview-container' style='border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden;'>{html_report}</div>", unsafe_allow_html=True)

    else:
        # Initial Placeholder design - Clean & Professional White Card
        st.markdown("""
        <div class="waiting-card">
            <h3>Menunggu Input Kode</h3>
            <p>Silakan masukkan kode sumber Anda pada <strong>Ruang Kerja Kode</strong> di sebelah kiri,<br>
            kemudian klik tombol <strong>JALANKAN ANALISIS</strong> untuk memproses metrik White Box lengkap.</p>
        </div>
        """, unsafe_allow_html=True)
