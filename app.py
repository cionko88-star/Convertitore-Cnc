from flask import Flask, render_template_string, request, Response
import re
import os

app = Flask(__name__)

def converti_selca_a_iso(testo_selca: str) -> str:
    righe_greffe = testo_selca.strip().split('\n')
    righe_elaborate = []
    
    # 1. Parsing preliminare per trovare le descrizioni degli utensili (supporta M6 e M06)
    utensili_info = {} 
    for idx, riga in enumerate(righe_greffe):
        riga_clean = riga.strip()
        match_t = re.search(r'\bT(\d+)\s+M0?6\b', riga_clean, re.IGNORECASE)
        if match_t:
            t_num = match_t.group(1)
            descrizione = ""
            match_desc = re.search(r'[\(\[]\s*(.*?)\s*[\)\]]', riga_clean)
            if match_desc:
                descrizione = match_desc.group(1).strip()
            else:
                if idx > 0:
                    prev_riga = righe_greffe[idx - 1].strip()
                    match_desc_prev = re.search(r'[\(\[]\s*(.*?)\s*[\)\]]', prev_riga)
                    if match_desc_prev:
                        descrizione = match_desc_prev.group(1).strip()
            
            if not descrizione:
                for r_testa in righe_greffe[:30]:
                    m_testa = re.search(rf'\bT\s*{t_num}\b\s*[:-]?\s*(.*)', r_testa, re.IGNORECASE)
                    if m_testa:
                        descrizione = m_testa.group(1).strip()
                        break
            
            if descrizione:
                match_taglio = re.search(r'(.*?-?\s*D\.\d+(?:\.\d+)?)', descrizione, re.IGNORECASE)
                if match_taglio:
                    descrizione = match_taglio.group(1).strip()
                descrizione = re.sub(r'\s*-\s*$', '', descrizione).strip()

            utensili_info[t_num] = descrizione

    if "4" not in utensili_info:
        for riga in righe_greffe:
            if "T4" in riga and ("D." in riga or "PUNTA" in riga):
                m_desc = re.search(r'[\(\[]\s*(.*?)\s*[\)\]]', riga)
                if m_desc:
                    utensili_info["4"] = m_desc.group(1).strip()
                    break
        if "4" not in utensili_info:
            utensili_info["4"] = "PUNTA FORATA MET. DURO"

    t_sequenza_ordinata = []
    for riga in righe_greffe:
        m_t = re.search(r'\bT(\d+)\s+M0?6\b', riga, re.IGNORECASE)
        if m_t:
            t_num = m_t.group(1)
            if t_num not in t_sequenza_ordinata:
                t_sequenza_ordinata.append(t_num)
        elif "T4" in riga and "M51" in riga and "4" not in t_sequenza_ordinata:
            if "4" not in t_sequenza_ordinata:
                t_sequenza_ordinata.append("4")
    
    n_linea = 2
    modo_movimento_corrente = None
    header_iniziale_inserito = False
    in_ciclo_foratura = False
    utensile_corrente = None
    inserito_primo_g64_utensile = False
    
    i = 0
    while i < len(righe_greffe):
        riga_grezza = righe_greffe[i].strip()
        i += 1
        
        if not riga_grezza:
            continue
            
        if riga_grezza.startswith('[') or riga_grezza.startswith('('):
            commento = riga_grezza
            if commento.startswith('['):
                commento = '(' + commento[1:]
            commento = commento.replace('[', '(').replace(']', ')')
            if not commento.endswith(')'):
                commento += ')'
            righe_elaborate.append(commento)
            
            if "PREFORI PER M6" in commento.upper() and utensile_corrente != "4":
                utensile_corrente = "4"
                inserito_primo_g64_utensile = False
                descrizione = utensili_info.get("4", "PUNTA FORATA")
                righe_elaborate.append(f"N{n_linea} T4 M06 M5 M9 ( T4 - {descrizione} )")
                n_linea += 2
                righe_elaborate.append(f"N{n_linea} G00 G90 G54")
                n_linea += 2
            continue
            
        clean = re.sub(r'^N\d+\s*', '', riga_grezza)
        if not clean:
            continue

        if "M30" in clean.upper():
            break # Interrompiamo qui per gestire la chiusura pulita standard in fondo

        if (re.search(r'\bG17\b', clean, re.IGNORECASE) or re.search(r'\bO1\b', clean, re.IGNORECASE)) and not header_iniziale_inserito:
            righe_elaborate.append(f"N{n_linea} G00 G17 G40 G49 G80 G54 G90")
            n_linea += 2
            header_iniziale_inserito = True
            continue

        if re.search(r'\bG49\b', clean, re.IGNORECASE):
            continue
            
        match_cambio = re.search(r'\bT(\d+)\s+M0?6\b', clean, re.IGNORECASE)
        if match_cambio:
            t_num = match_cambio.group(1)
            utensile_corrente = t_num
            inserito_primo_g64_utensile = False
            descrizione = utensili_info.get(t_num, "")

            prossimo_t = ""
            try:
                current_idx_in_seq = t_sequenza_ordinata.index(t_num)
                if current_idx_in_seq + 1 < len(t_sequenza_ordinata):
                    prossimo_t = t_sequenza_ordinata[current_idx_in_seq + 1]
            except ValueError:
                pass

            if descrizione:
                if re.match(rf'^T\s*{t_num}\b', descrizione, re.IGNORECASE):
                    desc_str = f" ( {descrizione} )"
                else:
                    desc_str = f" ( T{t_num} - {descrizione} )"
            else:
                desc_str = f" ( T{t_num} )"

            righe_elaborate.append(f"N{n_linea} T{t_num} M06 M5 M9{desc_str}")
            n_linea += 2
            
            righe_elaborate.append(f"N{n_linea} G00 G90 G54")
            n_linea += 2
            
            s_val = "S4400"
            m_s = re.search(r'S(\d+)', clean, re.IGNORECASE)
            if m_s:
                s_val = f"S{m_s.group(1)}"
            elif i < len(righe_greffe):
                m_s_next = re.search(r'S(\d+)', righe_greffe[i], re.IGNORECASE)
                if m_s_next:
                    s_val = f"S{m_s_next.group(1)}"
                    i += 1

            if prossimo_t:
                righe_elaborate.append(f"N{n_linea} {s_val} M3 T{prossimo_t} M51")
            else:
                righe_elaborate.append(f"N{n_linea} {s_val} M3")
            n_linea += 2
            continue

        if clean.startswith("S") and "M3" in clean:
            righe_elaborate.append(f"N{n_linea} {clean}")
            n_linea += 2
            continue

        if '[' in clean or ']' in clean:
            clean = clean.replace('[', '(').replace(']', ')')
            if not clean.endswith(')'):
                clean += ')'
            righe_elaborate.append(f"N{n_linea} {clean}")
            n_linea += 2
            continue
            
        clean = re.sub(r'([XYZ])(-?\d+\.?\d*)', r'\1\2 ', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        
        if clean in ["G00 Z3 M18", "G0 Z3 M18", "G00 Z3", "G0 Z3"]:
            clean = "Z3"

        if clean.startswith("G81") or clean.startswith("G84"):
            in_ciclo_foratura = True
            parts = clean.split()
            cmd_g = parts[0]
            resto = " ".join(parts[1:])
            resto = re.sub(r'J\d+', 'R3', resto)
            clean = f"G99 {cmd_g} {resto}"
            righe_elaborate.append(f"N{n_linea} {clean}")
            n_linea += 2
            
            while i < len(righe_greffe):
                riga_successiva_grezza = righe_greffe[i].strip()
                if not riga_successiva_grezza or riga_successiva_grezza.startswith('(') or riga_successiva_grezza.startswith('['):
                    break
                test_prox = re.sub(r'^N\d+\s*', '', riga_successiva_grezza)
                test_prox = re.sub(r'([XYZ])(-?\d+\.?\d*)', r'\1\2 ', test_prox)
                test_prox = re.sub(r'\s+', ' ', test_prox).strip()
                
                if "G64" in test_prox or "G80" in test_prox or "Z" in test_prox:
                    break
                if any(k in test_prox for k in ['X', 'Y']):
                    i += 1
                    break
                break
            continue

        if clean.startswith("G80"):
            in_ciclo_foratura = False

        if "G41" in clean or "G42" in clean:
            if not any(k in clean for k in ['X', 'Y', 'Z']) and i < len(righe_greffe):
                prossima_riga = righe_greffe[i].strip()
                prossima_riga = re.sub(r'^N\d+\s*', '', prossima_riga)
                if any(k in prossima_riga for k in ['X', 'Y']):
                    clean += " " + prossima_riga
                    i += 1
            modo_movimento_corrente = "G01"
            righe_elaborate.append(f"N{n_linea} {clean}")
            n_linea += 2
            continue

        if "G40" in clean:
            if not any(k in clean for k in ['X', 'Y', 'Z']) and i < len(righe_greffe):
                prossima_riga = righe_greffe[i].strip()
                prossima_riga = re.sub(r'^N\d+\s*', '', prossima_riga)
                if any(k in prossima_riga for k in ['X', 'Y', 'Z']):
                    clean += " " + prossima_riga
                    i += 1
            righe_elaborate.append(f"N{n_linea} {clean}")
            n_linea += 2
            continue

        is_z_rapido = False
        if ("Z" in clean and not "Z-" in clean and not any(g in clean for g in ['G01', 'G1', 'G02', 'G2', 'G03', 'G3'])) or clean in ["Z3", "Z100"]:
            is_pre_foratura = False
            for look_ahead_idx in range(i, min(i + 3, len(righe_greffe))):
                if any(g in righe_greffe[look_ahead_idx] for g in ['G81', 'G84']):
                    is_pre_foratura = True
                    break
            if not is_pre_foratura:
                is_z_rapido = True

        if is_z_rapido and not in_ciclo_foratura:
            if inserito_primo_g64_utensile:
                righe_elaborate.append(f"N{n_linea} G64")
                n_linea += 2
            else:
                inserito_primo_g64_utensile = True
            
            modo_movimento_corrente = "G00"
            clean = re.sub(r'^G0?1\s*', '', clean)
            clean = re.sub(r'^G0?0?\s*', '', clean)
            clean = f"G00 {clean}".strip()

        is_g_speciale = any(clean.startswith(g) for g in ["G02", "G2", "G03", "G3"])
        
        if "G02" in clean or "G2" in clean or "G03" in clean or "G3" in clean:
            modo_movimento_corrente = "G01"

        if clean.startswith("G00") or clean.startswith("G0 "):
            modo_movimento_corrente = "G00"
        elif is_g_speciale:
            pass
        elif clean.startswith("G01") or clean.startswith("G1 "):
            modo_movimento_corrente = "G01"
            clean = re.sub(r'^G0?1\s*', '', clean)
            clean = f"G01 {clean}"
        else:
            if modo_movimento_corrente == "G01" and any(k in clean for k in ['X', 'Y', 'Z']):
                pass

        ha_z = bool(re.search(r'\bZ-?\d+', clean))
        if ha_z and modo_movimento_corrente == "G01" and not in_ciclo_foratura:
            righe_elaborate.append(f"N{n_linea} G61.1")
            n_linea += 2

        righe_elaborate.append(f"N{n_linea} {clean}")
        n_linea += 2

    # Chiusura standard pulita in fondo
    primo_t = t_sequenza_ordinata[0] if t_sequenza_ordinata else "1"
    desc_primo_t = utensili_info.get(primo_t, "")
    desc_str_finale = f" ( T{primo_t} - {desc_primo_t} )" if desc_primo_t else f" ( T{primo_t} )"

    righe_elaborate.append(f"N{n_linea} M5 M9")
    n_linea += 2
    righe_elaborate.append(f"N{n_linea} T{primo_t} M06{desc_str_finale}")
    n_linea += 2
    righe_elaborate.append(f"N{n_linea} M30")

    return "\n".join(righe_elaborate)


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <title>Convertitore CNC SELCA ➔ ISO</title>
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
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="logo">&lt;/&gt; CNC CONVERTER</div>
    </div>
    <div class="main-content">
        <h1 class="header-title">Convertitore CNC SELCA ➔ ISO</h1>
        <form method="POST" action="/converti" id="mainForm">
            <div class="control-bar">
                <span>Modalità:</span>
                <span class="direction-badge">SELCA ➔ ISO (.eia)</span>
                <div class="input-group">
                    <label for="nome_programma">Nome File Output:</label>
                    <input type="text" id="nome_programma" name="nome_programma" value="{{ nome_programma or '200011974-A' }}">
                </div>
            </div>
            <div class="workspace">
                <div class="card">
                    <h3>Codice Sorgente (SELCA)</h3>
                    <textarea name="codice_sorgente" placeholder="Incolla il programma Selca...">{{ codice_sorgente }}</textarea>
                    <div class="actions">
                        <button type="button" class="btn btn-secondary" onclick="document.getElementById('fileInput').click()">📁 Carica file</button>
                        <input type="file" id="fileInput" style="display:none" onchange="caricaFile(this)">
                        <button type="submit" class="btn btn-primary">⚙️ Converti</button>
                    </div>
                </div>
                <div class="card">
                    <h3>Codice Convertito (ISO)</h3>
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
    return render_template_string(HTML_TEMPLATE, codice_sorgente="", codice_convertito="", nome_programma="200011974-A")

@app.route('/converti', methods=['POST'])
def converti():
    codice_sorgente = request.form.get('codice_sorgente', '')
    nome_programma = request.form.get('nome_programma', '200011974-A').strip()
    codice_convertito = converti_selca_a_iso(codice_sorgente)
    return render_template_string(HTML_TEMPLATE, codice_sorgente=codice_sorgente, codice_convertito=codice_convertito, nome_programma=nome_programma)

@app.route('/scarica', methods=['POST'])
def scarica():
    codice_sorgente = request.form.get('codice_sorgente', '')
    nome_programma = request.form.get('nome_programma', '200011974-A').strip()
    codice_convertito = converti_selca_a_iso(codice_sorgente)
    
    nome_file_pulito = re.sub(r'\.eia$', '', nome_programma, flags=re.IGNORECASE)
    
    return Response(
        codice_convertito, 
        mimetype="text/plain", 
        headers={"Content-disposition": f"attachment; filename={nome_file_pulito}.eia"}
    )

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
