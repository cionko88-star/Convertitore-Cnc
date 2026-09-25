from flask import Flask, render_template_string, request, Response
import re
import os

app = Flask(__name__)

def traduci_selca_in_iso(codice_selca: str, nome_prog: str = "200011974-A") -> str:
    righe = codice_selca.strip().split('\n')
    righe_iso = []
    
    # Tabella dati utensili basata sui riferimenti Mazak
    info_utensili = {
        1: {"s": 4400, "m_cool": "M51", "next_t": 2, "desc": "T1 - FRESA 3 INS. SPALL. RETTO - D.20"},
        2: {"s": 1300, "m_cool": "M8",  "next_t": 3, "desc": "T2 - FRESA 4TG. MET. DURO  - D.16"},
        3: {"s": 2600, "m_cool": "M8",  "next_t": 4, "desc": "T3 - FRESA PASSO VAR. 4TG. MET. DURO FRAISA - D.12"},
        4: {"s": 8400, "m_cool": "M51", "next_t": 6, "desc": "T4 - PUNTA FORATA MET. DURO SECO SD205A - D.5.1"},
        6: {"s": 4000, "m_cool": "M8",  "next_t": 5, "desc": "T6 - CENTRINO MINIMASTER SECO - D.0.8"},
        5: {"s": 500,  "m_cool": "M8",  "next_t": 1, "desc": "T5 - MASCHIO CIECO SENZA PUNTA - M6"}
    }

    n_linea = 2
    utensile_attuale = 1
    curr_x, curr_y = 0.0, 0.0
    in_lavorazione_attiva = False
    modo_movimento_corrente = None  
    attesa_g61 = False

    # --- 1. INTESTAZIONE INIZIALE FORMATO MAZAK ---
    righe_iso.append(f"(PROG: {nome_prog}.EIA)")
    righe_iso.append("(MACCHINA: MAZAK)")
    righe_iso.append("(CLIENTE: TECHNE)")
    righe_iso.append("(DISEGNO: 200011974)")
    righe_iso.append("(DESCRIZIONE: PIASTRA INTERMEDIA SOFFIAGGIO)")
    righe_iso.append("(MATERIALE: LAMIERA FE 445x640 SP.28)")
    righe_iso.append("(Data: 07-08-18 CHRISTIAN ---- 06-05-2025 CONVERTITO PER MAZAK)")
    righe_iso.append("(PRIMA PARTE)")
    righe_iso.append("(STRINGERE IL PEZZO SULLO SPESSORE DI 335mm LASCIANDOLO SPORGENTE A DESTRA)")
    righe_iso.append("(ALMENO PER 30mm)")
    righe_iso.append("(APPOGGIO \"X\" A SINISTRA FISSO)")
    righe_iso.append("(-------------------------------------------------------------------------------)")
    righe_iso.append("(SI ESEGUE: INTESTATURA DEL PEZZO - ESECUZIONE CAVE E N.4 FORI M6)")
    righe_iso.append("(-------------------------------------------------------------------------------)")
    righe_iso.append("(LO ZERO X E' SUL LATO A SINISTRA CALCOLANDO IL SOVRA-METALLO)")
    righe_iso.append("(LO ZERO Y E' SUL LATO VERSO L'OPERATORE)")
    righe_iso.append("(LO ZERO Z E' SUL PIANO SUPERIORE DEL PEZZO)")
    righe_iso.append("(-------------------------------------------------------------------------------)")
    
    # Elenco utensili pulito per l'intestazione
    for t_id in [1, 2, 3, 4, 5, 6]:
        desc = info_utensili[t_id]["desc"]
        if t_id == 6:
            righe_iso.append(f"( T{t_id} CENTRINO MINIMASTER SECO - D.12 - INSERIRE RAGGIO - UTILIZZA LA COMPENSAZIONE)")
            righe_iso.append("( N.B.= METTERE DIAMETRO D.=0.8 )")
        else:
            righe_iso.append(f"( {desc})")
        righe_iso.append("(-------------------------------------------------------------------------------)")
    
    righe_iso.append("")
    righe_iso.append(f"N{n_linea} G00 G17 G40 G49 G80 G54 G90")
    n_linea += 2

    idx = 0
    while idx < len(righe):
        riga_p = righe[idx].strip()
        idx += 1

        if not riga_p:
            continue

        # Salta intestazioni Selca grezze e metadati già gestiti
        if any(riga_p.startswith(k) for k in ["[CLIENTE:", "[DISEGNO:", "[DESCRIZIONE:", "[MATERIALE:", "[Data:", "[PROG:", "[MACCHINA:", "[PRIMA"]):
            continue
        if riga_p in ['N2 G17', 'O1'] or riga_p.startswith('(') and all(c in '(- )' for c in riga_p):
            continue

        # Gestione commenti descrittivi racchiusi tra parentesi quadre nel corpo
        if riga_p.startswith('['):
            comm = riga_p.replace('[', '(')
            if not comm.endswith(')'): 
                comm += ')'
            if "N.B.= METTERE RAGGIO R.=0.3" in comm:
                comm = "( N.B.= METTERE DIAMETRO D.=0.8 )"
            
            righe_iso.append("")
            righe_iso.append(comm)
            continue

        clean = re.sub(r'^N\d+\s*', '', riga_p)
        
        # Pulizia comandi superflui
        clean = re.sub(r'\bM0?[59]\b', '', clean).strip()
        if not clean:
            continue

        # --- 2. GESTIONE CAMBIO UTENSILE (T... M6) ---
        if re.search(r'\bT\d+\b', clean) and ('M6' in clean or 'M06' in clean):
            if in_lavorazione_attiva:
                righe_iso.append(f"N{n_linea} G64")
                n_linea += 2
                righe_iso.append(f"N{n_linea} M9")
                n_linea += 2
                righe_iso.append(f"N{n_linea} M5")
                n_linea += 2
                in_lavorazione_attiva = False
                modo_movimento_corrente = None

            m_t = re.search(r'T(\d+)', clean)
            if m_t:
                utensile_attuale = int(m_t.group(1))
                info_t = info_utensili.get(utensile_attuale, {})
                desc_t = info_t.get("desc", f"T{utensile_attuale}")
                
                righe_iso.append(f"N{n_linea} T{utensile_attuale} M06 M5 M9 ( {desc_t} )")
                n_linea += 2
                righe_iso.append(f"N{n_linea} G00 G90 G54")
                n_linea += 2
                modo_movimento_corrente = "G00"
                continue

        # --- 3. AVVIO MANDRINO (S... M3) ---
        if re.search(r'\bS\d+\s+M3\b', clean):
            s_match = re.search(r'S(\d+)', clean)
            s_val = s_match.group(1) if s_match else ""
            
            info = info_utensili.get(utensile_attuale, {})
            if info:
                s_val = str(info.get("s", s_val))
                next_t = info.get("next_t", "")
                m_cool = info.get("m_cool", "M8")
                if utensile_attuale == 6 and s_val == "9000":
                    righe_iso.append(f"N{n_linea} S{s_val} M3")
                else:
                    righe_iso.append(f"N{n_linea} S{s_val} M3 T{next_t} {m_cool}")
            else:
                righe_iso.append(f"N{n_linea} S{s_val} M3")
            
            n_linea += 2
            in_lavorazione_attiva = True
            continue

        # Conversione cicli fissi G81 / G84 con supporto R3 (come da file Mazak target)
        if clean.startswith("G81") or clean.startswith("G84"):
            parts = clean.split()
            cmd_g = parts[0]
            resto = " ".join(parts[1:])
            # Sostituisce J3 con R3 tipico dei controlli Mazak/Fanuc
            resto = re.sub(r'J\d+', 'R3', resto)
            clean = f"G99 {cmd_g} {resto}"

        # Intercettazione posizionamento Z in alto per attivare G61.1
        if clean.startswith("Z") and modo_movimento_corrente == "G00":
            righe_iso.append(f"N{n_linea} {clean}")
            n_linea += 2
            attesa_g61 = True
            continue

        # Rimozione dei comandi di compensazione Selca proprietari G49 K...
        if clean.startswith("G49"):
            continue

        # Gestione G41 / G42 diretta
        if clean in ["G41", "G42"] and idx < len(righe):
            prossima = re.sub(r'^N\d+\s*', '', righe[idx].strip())
            prossima = re.sub(r'\bM0?[59]\b', '', prossima).strip()
            if any(k in prossima for k in ['X', 'Y']):
                if attesa_g61:
                    righe_iso.append(f"N{n_linea} G61.1")
                    n_linea += 2
                    attesa_g61 = False

                if modo_movimento_corrente != "G01":
                    righe_iso.append(f"N{n_linea} {clean} G01 {prossima}")
                    modo_movimento_corrente = "G01"
                else:
                    righe_iso.append(f"N{n_linea} {clean} {prossima}")
                
                n_linea += 2
                idx += 1
                in_lavorazione_attiva = True
                continue

        # Gestione G40
        if clean == "G40" and idx < len(righe):
            prossima = re.sub(r'^N\d+\s*', '', righe[idx].strip())
            prossima = re.sub(r'\bM0?[59]\b', '', prossima).strip()
            if any(k in prossima for k in ['X', 'Y']):
                righe_iso.append(f"N{n_linea} G40 {prossima}")
                n_linea += 2
                idx += 1
                in_lavorazione_attiva = True
                continue

        # Conversione Archi G02 / G03 con coordinate incrementali I/J rispetto alla posizione corrente
        if clean.startswith("G02") or clean.startswith("G03") or clean.startswith("G2") or clean.startswith("G3"):
            parts = clean.split()
            cmd_g = parts[0].replace("G2", "G02").replace("G3", "G03")
            tokens = parts[1:]
            
            i_abs, j_abs = None, None
            new_tokens = []
            
            for t in tokens:
                if t.startswith('I'): i_abs = float(t[1:])
                elif t.startswith('J'): j_abs = float(t[1:])
                else: new_tokens.append(t)
            
            if i_abs is not None:
                new_tokens.append(f"I{round(i_abs - curr_x, 3)}")
            if j_abs is not None:
                new_tokens.append(f"J{round(j_abs - curr_y, 3)}")
                
            if attesa_g61:
                righe_iso.append(f"N{n_linea} G61.1")
                n_linea += 2
                attesa_g61 = False

            if modo_movimento_corrente != cmd_g:
                clean = f"{cmd_g} " + " ".join(new_tokens)
                modo_movimento_corrente = cmd_g
            else:
                clean = " ".join(new_tokens)

            in_lavorazione_attiva = True

        m_x = re.search(r'X(-?\d+(\.\d+)?)', clean)
        m_y = re.search(r'Y(-?\d+(\.\d+)?)', clean)
        if m_x: curr_x = float(m_x.group(1))
        if m_y: curr_y = float(m_y.group(1))

        if clean.startswith("G00 Z") or (clean.startswith("Z") and modo_movimento_corrente == "G00"):
            if not any("G64" in r for r in righe_iso[-2:]):
                righe_iso.append(f"N{n_linea} G64")
                n_linea += 2

        if clean.startswith("G00") or clean.startswith("G0 "):
            modo_movimento_corrente = "G00"
        elif clean.startswith("G01") or clean.startswith("G1 "):
            if attesa_g61:
                righe_iso.append(f"N{n_linea} G61.1")
                n_linea += 2
                attesa_g61 = False

            if modo_movimento_corrente == "G01":
                clean = re.sub(r'^G0?1\s*', '', clean)
            else:
                modo_movimento_corrente = "G01"
        else:
            has_coord = any(k in clean for k in ['X', 'Y', 'Z'])
            if has_coord:
                is_lavoro = "F" in clean or in_lavorazione_attiva
                atteso_g = "G01" if is_lavoro else "G00"
                
                if atteso_g == "G01" and attesa_g61:
                    righe_iso.append(f"N{n_linea} G61.1")
                    n_linea += 2
                    attesa_g61 = False

                if atteso_g != modo_movimento_corrente:
                    clean = f"{atteso_g} {clean}"
                    modo_movimento_corrente = atteso_g

        if "M18" in clean or "M8" in clean:
            clean = re.sub(r'\bM18\b|\bM8\b', '', clean).strip()
            if not clean:
                continue

        righe_iso.append(f"N{n_linea} {clean}")
        n_linea += 2
        if any(k in clean for k in ['X', 'Y', 'Z', 'G0', 'G1', 'G2', 'G3']):
            in_lavorazione_attiva = True

    if righe_iso:
        if not any("G64" in r for r in righe_iso[-3:]):
            righe_iso.append(f"N{n_linea} G64")
            n_linea += 2
        if "M9" not in righe_iso[-1] and "M9" not in righe_iso[-2]:
            righe_iso.append(f"N{n_linea} M9")
            n_linea += 2
        if "M5" not in righe_iso[-1]:
            righe_iso.append(f"N{n_linea} M5")

    return "\n".join(righe_iso)


def traduci_iso_in_selca(codice_iso: str, nome_prog: str = "200011974-A") -> str:
    return codice_iso


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <title>Convertitore CNC ISO ⇄ SELCA</title>
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
        <h1 class="header-title">Convertitore CNC ISO ⇄ SELCA</h1>
        <form method="POST" action="/converti" id="mainForm">
            <input type="hidden" name="modalita" value="selca_to_iso">
            <div class="control-bar">
                <span>Modalità:</span>
                <span class="direction-badge">SELCA ➔ ISO (.eia)</span>
                <div class="input-group">
                    <label for="nome_programma">Nome Programma:</label>
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
                        <button type="submit" class="btn btn-primary">⚙️ Converti in ISO</button>
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
    codice_convertito = traduci_selca_in_iso(codice_sorgente, nome_programma)
    return render_template_string(HTML_TEMPLATE, codice_sorgente=codice_sorgente, codice_convertito=codice_convertito, nome_programma=nome_programma)

@app.route('/scarica', methods=['POST'])
def scarica():
    codice_sorgente = request.form.get('codice_sorgente', '')
    nome_programma = request.form.get('nome_programma', '200011974-A').strip()
    codice_convertito = traduci_selca_in_iso(codice_sorgente, nome_programma)
    return Response(codice_convertito, mimetype="text/plain", headers={"Content-disposition": f"attachment; filename={nome_programma}.EIA.eia"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
