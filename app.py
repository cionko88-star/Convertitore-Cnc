from flask import Flask, render_template_string, request, Response
import re
import os
from datetime import datetime

app = Flask(__name__)

def traduci_selca_in_iso(codice_selca: str, nome_prog: str = "200011974-A") -> str:
    righe = codice_selca.strip().split('\n')
    righe_iso = []
    data_oggi = datetime.now().strftime("%d-%m-%Y")
    
    righe_iso.append(f"(PROG: {nome_prog}.EIA)")
    righe_iso.append("(MACCHINA: MAZAK)")
    
    info_utensili = {
        1: {"s": 4400, "m_cool": "M51", "next_t": 2},
        2: {"s": 1300, "m_cool": "M8",  "next_t": 3},
        3: {"s": 2600, "m_cool": "M8",  "next_t": 4},
        4: {"s": 8400, "m_cool": "M51", "next_t": 6},
        6: {"s": 4000, "m_cool": "M8",  "next_t": 5},
        5: {"s": 500,  "m_cool": "M8",  "next_t": 1}
    }

    n_linea = 2
    utensile_attuale = 1
    curr_x, curr_y = 0.0, 0.0

    idx = 0
    while idx < len(righe):
        riga_p = righe[idx].strip()
        idx += 1

        if not riga_p:
            continue

        if riga_p.startswith("[CLIENTE:") or riga_p.startswith("[DISEGNO:") or riga_p.startswith("[DESCRIZIONE:") or riga_p.startswith("[MATERIALE:"):
            righe_iso.append(riga_p.replace('[', '(') + ')')
            continue
        elif riga_p.startswith("[Data:"):
            base_data = riga_p.replace('[', '(')
            righe_iso.append(f"{base_data} ---- {data_oggi} CONVERTITO PER MAZAK)")
            continue
        elif riga_p.startswith("[PROG:") or riga_p.startswith("[MACCHINA:"):
            continue

        if riga_p.startswith('['):
            comm = riga_p.replace('[', '(')
            if not comm.endswith(')'): comm += ')'
            if "N.B.= METTERE RAGGIO R.=0.3" in comm:
                comm = "( N.B.= METTERE DIAMETRO D.=0.8 )"
            righe_iso.append(comm)
            continue

        if riga_p in ['N2 G17', 'O1']:
            if "N2 G00 G17 G40 G49 G80 G54 G90" not in righe_iso:
                righe_iso.append("N2 G00 G17 G40 G49 G80 G54 G90")
                n_linea = 4
            continue

        clean = re.sub(r'^N\d+\s*', '', riga_p)

        # Cambio Utensile
        if re.search(r'\bT\d+\s+M6\b', clean) or (re.search(r'\bT\d+\b', clean) and 'M6' in clean):
            m_t = re.search(r'T(\d+)', clean)
            if m_t:
                utensile_attuale = int(m_t.group(1))
                comm = ""
                if '[' in clean:
                    comm = " " + clean[clean.index('['):].replace('[', '(')
                    if not comm.endswith(')'): comm += ')'
                
                righe_iso.append(f"N{n_linea} T{utensile_attuale} M06 M5 M9{comm}")
                n_linea += 2
                righe_iso.append(f"N{n_linea} G00 G90 G54")
                n_linea += 2
                continue

        # Avvio Mandrino
        if re.search(r'\bS\d+\s+M3\b', clean):
            s_match = re.search(r'S(\d+)', clean)
            s_val = s_match.group(1) if s_match else ""
            
            info = info_utensili.get(utensile_attuale, {})
            if info:
                s_val = str(info.get("s", s_val))
                next_t = info.get("next_t", "")
                m_cool = info.get("m_cool", "M8")
                righe_iso.append(f"N{n_linea} S{s_val} M3 T{next_t} {m_cool}")
            else:
                righe_iso.append(f"N{n_linea} S{s_val} M3")
            
            n_linea += 2
            continue

        # Se SELCA ha G41/G42 isolato
        if clean in ["G41", "G42"] and idx < len(righe):
            prossima = re.sub(r'^N\d+\s*', '', righe[idx].strip())
            if any(k in prossima for k in ['X', 'Y']):
                if not (righe_iso and "G49" in righe_iso[-1]):
                    righe_iso.append(f"N{n_linea} G49 K{utensile_attuale}")
                    n_linea += 2
                prossima_mod = prossima.replace("F400", "F800")
                righe_iso.append(f"N{n_linea} {clean} {prossima_mod}")
                
                m_x = re.search(r'X(-?\d+(\.\d+)?)', prossima_mod)
                m_y = re.search(r'Y(-?\d+(\.\d+)?)', prossima_mod)
                if m_x: curr_x = float(m_x.group(1))
                if m_y: curr_y = float(m_y.group(1))
                
                n_linea += 2
                idx += 1
                continue

        # Se SELCA ha G40 isolato
        if clean == "G40" and idx < len(righe):
            prossima = re.sub(r'^N\d+\s*', '', righe[idx].strip())
            if any(k in prossima for k in ['X', 'Y']):
                righe_iso.append(f"N{n_linea} G40 {prossima}")
                
                m_x = re.search(r'X(-?\d+(\.\d+)?)', prossima)
                m_y = re.search(r'Y(-?\d+(\.\d+)?)', prossima)
                if m_x: curr_x = float(m_x.group(1))
                if m_y: curr_y = float(m_y.group(1))
                
                n_linea += 2
                idx += 1
                continue

        # CONVERSIONE ARCHI G02 / G03 (SELCA -> ISO: Assoluto -> Incrementale)
        if clean.startswith("G02") or clean.startswith("G03") or clean.startswith("G2") or clean.startswith("G3"):
            parts = clean.split()
            cmd_g = parts[0]
            tokens = parts[1:]
            
            i_abs, j_abs = None, None
            new_tokens = []
            
            for t in tokens:
                if t.startswith('I'):
                    i_abs = float(t[1:])
                elif t.startswith('J'):
                    j_abs = float(t[1:])
                else:
                    new_tokens.append(t)
            
            if i_abs is not None:
                i_inc = round(i_abs - curr_x, 3)
                new_tokens.append(f"I{i_inc}")
            if j_abs is not None:
                j_inc = round(j_abs - curr_y, 3)
                new_tokens.append(f"J{j_inc}")
                
            clean = f"{cmd_g} " + " ".join(new_tokens)

        # Tracciamento coordinate Correnti
        m_x = re.search(r'X(-?\d+(\.\d+)?)', clean)
        m_y = re.search(r'Y(-?\d+(\.\d+)?)', clean)
        if m_x: curr_x = float(m_x.group(1))
        if m_y: curr_y = float(m_y.group(1))

        # CICLI DI FORATURA/MASCHIATURA (SELCA -> ISO)
        if any(ciclo in clean for ciclo in ["G81", "G84", "G85"]):
            clean_iso = re.sub(r'\bJ(\d+(\.\d+)?)', r'R\1', clean)
            if not clean_iso.startswith("G99"):
                clean_iso = "G99 " + clean_iso
            righe_iso.append(f"N{n_linea} {clean_iso}")
            n_linea += 2
            continue

        if "M18" in clean or "M8" in clean:
            clean = re.sub(r'\bM18\b|\bM8\b', '', clean).strip()
            if not clean:
                continue

        if clean in ["M5", "M05"]:
            righe_iso.append(f"N{n_linea} M9")
            n_linea += 2
            righe_iso.append(f"N{n_linea} {clean}")
            n_linea += 2
            continue

        righe_iso.append(f"N{n_linea} {clean}")
        n_linea += 2

    if righe_iso and "M9" not in righe_iso[-1]:
        righe_iso.append(f"N{n_linea} M9")

    return "\n".join(righe_iso)


def traduci_iso_in_selca(codice_iso: str, nome_prog: str = "200011974-A") -> str:
    righe = codice_iso.strip().split('\n')
    righe_selca = []
    
    righe_selca.append(f"[PROG: {nome_prog}")
    righe_selca.append("[MACCHINA: PARPAS_PHS812")
    
    n_linea = 2
    utensile_attuale = 1
    primo_z_utensile = True
    curr_x, curr_y = 0.0, 0.0

    idx = 0
    while idx < len(righe):
        riga = righe[idx].strip()
        idx += 1
        
        if not riga or riga.startswith("(PROG:") or riga.startswith("(MACCHINA:"):
            continue

        if riga.startswith('('):
            comm = riga.replace('(', '[').replace(')', '')
            if "CONVERTITO PER MAZAK" in comm:
                comm = comm.split("----")[0].strip()
            if "N.B.= METTERE DIAMETRO D.=0.8" in comm:
                comm = "[ N.B.= METTERE RAGGIO R.=0.3"
            righe_selca.append(comm)
            continue

        if "G00 G17 G40 G49 G80 G54 G90" in riga:
            righe_selca.append("N2 G17")
            righe_selca.append("O1")
            n_linea = 4
            continue

        clean = re.sub(r'^N\d+\s*', '', riga)

        if "M06" in clean:
            m_t = re.search(r'T(\d+)', clean)
            if m_t:
                utensile_attuale = int(m_t.group(1))
                primo_z_utensile = True
                comm = ""
                if '(' in clean:
                    comm = " [" + clean[clean.index('(')+1:].replace(')', '')
                righe_selca.append(f"N{n_linea} T{utensile_attuale} M6{comm}")
                n_linea += 2
            continue

        if any(cmd in clean for cmd in ['G61.1', 'G64', 'G54', 'G90']):
            continue

        # COMPENSAZIONE RAGGIO G41 / G42
        if clean.startswith("G41") or clean.startswith("G42"):
            cmd_g = "G41" if "G41" in clean else "G42"
            rest_xy = clean.replace(cmd_g, "").strip()
            
            if not (righe_selca and "G49" in righe_selca[-1]):
                righe_selca.append(f"N{n_linea} G49 K{utensile_attuale}")
                n_linea += 2
            
            righe_selca.append(f"N{n_linea} {cmd_g}")
            n_linea += 2
            
            if rest_xy:
                rest_xy = rest_xy.replace("F800", "F400")
                righe_selca.append(f"N{n_linea} {rest_xy}")
                
                m_x = re.search(r'X(-?\d+(\.\d+)?)', rest_xy)
                m_y = re.search(r'Y(-?\d+(\.\d+)?)', rest_xy)
                if m_x: curr_x = float(m_x.group(1))
                if m_y: curr_y = float(m_y.group(1))
                
                n_linea += 2
            continue

        # ANNULLAMENTO COMPENSAZIONE G40
        if "G40" in clean:
            rest_xy = clean.replace("G40", "").strip()
            
            righe_selca.append(f"N{n_linea} G40")
            n_linea += 2
            
            if rest_xy:
                righe_selca.append(f"N{n_linea} {rest_xy}")
                
                m_x = re.search(r'X(-?\d+(\.\d+)?)', rest_xy)
                m_y = re.search(r'Y(-?\d+(\.\d+)?)', rest_xy)
                if m_x: curr_x = float(m_x.group(1))
                if m_y: curr_y = float(m_y.group(1))
                
                n_linea += 2
            continue

        if "G49 K" in clean:
            clean = f"G49 K{utensile_attuale}"
            righe_selca.append(f"N{n_linea} {clean}")
            n_linea += 2
            continue

        # CONVERSIONE ARCHI G02 / G03 (ISO -> SELCA: Incrementale -> Assoluto)
        if clean.startswith("G02") or clean.startswith("G03") or clean.startswith("G2") or clean.startswith("G3"):
            parts = clean.split()
            cmd_g = parts[0]
            tokens = parts[1:]
            
            i_inc, j_inc = None, None
            new_tokens = []
            
            next_x, next_y = curr_x, curr_y
            
            for t in tokens:
                if t.startswith('I'):
                    i_inc = float(t[1:])
                elif t.startswith('J'):
                    j_inc = float(t[1:])
                else:
                    new_tokens.append(t)
                    if t.startswith('X'): next_x = float(t[1:])
                    elif t.startswith('Y'): next_y = float(t[1:])
            
            if i_inc is not None:
                i_abs = round(curr_x + i_inc, 3)
                new_tokens.append(f"I{i_abs:g}")
            if j_inc is not None:
                j_abs = round(curr_y + j_inc, 3)
                new_tokens.append(f"J{j_abs:g}")
                
            clean = f"{cmd_g} " + " ".join(new_tokens)
            curr_x, curr_y = next_x, next_y

        # Tracciamento coordinate Correnti
        m_x = re.search(r'X(-?\d+(\.\d+)?)', clean)
        m_y = re.search(r'Y(-?\d+(\.\d+)?)', clean)
        if m_x and not (clean.startswith("G02") or clean.startswith("G03") or clean.startswith("G2") or clean.startswith("G3")):
            curr_x = float(m_x.group(1))
        if m_y and not (clean.startswith("G02") or clean.startswith("G03") or clean.startswith("G2") or clean.startswith("G3")):
            curr_y = float(m_y.group(1))

        # PRIMO POSIZIONAMENTO IN Z
        if primo_z_utensile and re.search(r'\bZ-?\d+(\.\d+)?\b', clean):
            codice_acqua = "M18" if utensile_attuale in [1, 4] else "M8"
            if not clean.startswith("G00") and not clean.startswith("G01"):
                clean = "G00 " + clean
            righe_selca.append(f"N{n_linea} {clean} {codice_acqua}")
            n_linea += 2
            primo_z_utensile = False
            continue

        # CICLI DI FORATURA E MASCHIATURA (ISO -> SELCA: Aggiunta automatica della prima posizione XY)
        if any(ciclo in clean for ciclo in ["G81", "G84", "G85"]):
            m_x_iso = re.search(r'X(-?\d+(\.\d+)?)', clean)
            m_y_iso = re.search(r'Y(-?\d+(\.\d+)?)', clean)
            
            if m_x_iso: curr_x = float(m_x_iso.group(1))
            if m_y_iso: curr_y = float(m_y_iso.group(1))
            
            clean_selca = clean.replace("G99 ", "").replace("G99", "").strip()
            clean_selca = re.sub(r'\b[XY]-?\d+(\.\d+)?', '', clean_selca).strip()
            clean_selca = re.sub(r'\s+', ' ', clean_selca)
            clean_selca = re.sub(r'\bR(\d+(\.\d+)?)', r'J\1', clean_selca)
            
            righe_selca.append(f"N{n_linea} {clean_selca}")
            n_linea += 2
            
            righe_selca.append(f"N{n_linea} X{curr_x:g} Y{curr_y:g}")
            n_linea += 2
            continue

        if re.match(r'^X-?\d+.*Y-?\d+', clean) and not clean.startswith("G01") and not clean.startswith("G02") and not clean.startswith("G03"):
            clean = "G00 " + clean

        if "S" in clean and "M3" in clean:
            m_s = re.search(r'S\d+', clean)
            s_str = m_s.group(0) if m_s else "S4400"
            righe_selca.append(f"N{n_linea} {s_str} M3")
            n_linea += 2
            continue

        if clean in ["M5", "M05"]:
            righe_selca.append(f"N{n_linea} M9")
            n_linea += 2
            righe_selca.append(f"N{n_linea} {clean}")
            n_linea += 2
            continue

        righe_selca.append(f"N{n_linea} {clean}")
        n_linea += 2

    if righe_selca and "M9" not in righe_selca[-1]:
        righe_selca.append(f"N{n_linea} M9")

    return "\n".join(righe_selca)


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <title>Convertitore CNC ISO ↔ SELCA</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, sans-serif; }
        body { display: flex; height: 100vh; background-color: #f7f6f0; color: #1e293b; }
        .sidebar { width: 250px; background-color: #1e293b; color: #fff; padding: 20px; display: flex; flex-direction: column; gap: 20px; }
        .logo { font-size: 18px; font-weight: bold; color: #38bdf8; }
        .main-content { flex: 1; padding: 30px; overflow-y: auto; }
        .header-title { font-size: 26px; font-weight: 800; color: #0f172a; margin-bottom: 15px; }
        .control-bar { display: flex; align-items: center; gap: 20px; margin-bottom: 15px; background: #fff; padding: 12px 20px; border-radius: 10px; border: 1px solid #e2e8f0; flex-wrap: wrap; }
        .direction-badge { font-weight: 700; color: #0d9488; }
        .input-group { display: flex; align-items: center; gap: 8px; font-size: 14px; font-weight: 600; color: #334155; }
        .input-group input { padding: 6px 10px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 14px; width: 180px; }
        .workspace { display: flex; gap: 20px; }
        .card { flex: 1; background: #fff; border-radius: 12px; border: 1px solid #e2e8f0; padding: 20px; display: flex; flex-direction: column; }
        textarea { width: 100%; height: 420px; border: 1px solid #cbd5e1; border-radius: 8px; padding: 12px; font-family: monospace; font-size: 13px; resize: none; background: #fafafa; }
        textarea.output { background: #0f172a; color: #38bdf8; }
        .actions { display: flex; justify-content: space-between; margin-top: 15px; }
        .btn { padding: 10px 18px; border-radius: 8px; font-weight: 600; cursor: pointer; border: none; font-size: 14px; }
        .btn-primary { background-color: #0d9488; color: #fff; }
        .btn-secondary { background-color: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; }
        .btn-swap { background-color: #f97316; color: #fff; }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="logo">&lt;/&gt; CNC CONVERTER</div>
    </div>
    <div class="main-content">
        <h1 class="header-title">Convertitore CNC ISO ↔ SELCA</h1>
        <form method="POST" action="/converti" id="mainForm">
            <input type="hidden" name="modalita" value="{{ modalita or 'selca_to_iso' }}">
            <div class="control-bar">
                <span>Modalità:</span>
                <span class="direction-badge">
                    {% if modalita == 'selca_to_iso' %} SELCA ➔ ISO (.eia) {% else %} ISO ➔ SELCA {% endif %}
                </span>

                <div class="input-group">
                    <label for="nome_programma">Nome Programma (PROG):</label>
                    <input type="text" id="nome_programma" name="nome_programma" value="{{ nome_programma or '200011974-A' }}" placeholder="es. 200011974-A">
                </div>

                <button type="submit" formaction="/scambia" class="btn btn-swap">🔄 Inverti Direzione</button>
            </div>
            <div class="workspace">
                <div class="card">
                    <h3>Codice Sorgente</h3>
                    <textarea name="codice_sorgente" placeholder="Incolla il programma o caricalo da file...">{{ codice_sorgente }}</textarea>
                    <div class="actions">
                        <button type="button" class="btn btn-secondary" onclick="document.getElementById('fileInput').click()">📁 Carica file</button>
                        <input type="file" id="fileInput" style="display:none" onchange="caricaFile(this)">
                        <button type="submit" class="btn btn-primary">⚡ Converti Programma</button>
                    </div>
                </div>
                <div class="card">
                    <h3>Codice Convertito</h3>
                    <textarea class="output" readonly>{{ codice_convertito }}</textarea>
                    <div class="actions" style="justify-content: flex-end;">
                        <button type="submit" formaction="/scarica" class="btn btn-primary">Scarica File</button>
                    </div>
                </div>
            </div>
        </form>
    </div>

    <script>
        function caricaFile(input) {
            let file = input.files[0];
            if (file) {
                let reader = new FileReader();
                reader.onload = function(e) {
                    document.querySelector("textarea[name='codice_sorgente']").value = e.target.result;
                };
                reader.readAsText(file);
            }
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE, codice_sorgente="", codice_convertito="", modalita="selca_to_iso", nome_programma="200011974-A")

@app.route('/converti', methods=['POST'])
def converti():
    codice_sorgente = request.form.get('codice_sorgente', '')
    modalita = request.form.get('modalita', 'selca_to_iso')
    nome_programma = request.form.get('nome_programma', '200011974-A').strip()
    
    if modalita == 'selca_to_iso':
        codice_convertito = traduci_selca_in_iso(codice_sorgente, nome_programma)
    else:
        codice_convertito = traduci_iso_in_selca(codice_sorgente, nome_programma)
        
    return render_template_string(HTML_TEMPLATE, codice_sorgente=codice_sorgente, codice_convertito=codice_convertito, modalita=modalita, nome_programma=nome_programma)

@app.route('/scambia', methods=['POST'])
def scambia():
    codice_sorgente = request.form.get('codice_sorgente', '')
    codice_convertito = request.form.get('codice_convertito', '')
    modalita = request.form.get('modalita', 'selca_to_iso')
    nome_programma = request.form.get('nome_programma', '200011974-A').strip()
    
    nuova_modalita = 'iso_to_selca' if modalita == 'selca_to_iso' else 'selca_to_iso'
    return render_template_string(HTML_TEMPLATE, codice_sorgente=codice_convertito, codice_convertito=codice_sorgente, modalita=nuova_modalita, nome_programma=nome_programma)

@app.route('/scarica', methods=['POST'])
def scarica():
    codice_sorgente = request.form.get('codice_sorgente', '')
    modalita = request.form.get('modalita', 'selca_to_iso')
    nome_programma = request.form.get('nome_programma', '200011974-A').strip()
    
    if modalita == 'selca_to_iso':
        codice_convertito = traduci_selca_in_iso(codice_sorgente, nome_programma)
        nome_file = f"{nome_programma}.EIA.eia"
    else:
        codice_convertito = traduci_iso_in_selca(codice_sorgente, nome_programma)
        nome_file = nome_programma
        
    return Response(codice_convertito, mimetype="text/plain", headers={"Content-disposition": f"attachment; filename={nome_file}"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
