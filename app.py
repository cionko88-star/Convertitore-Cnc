from flask import Flask, render_template_string, request, Response
import re
import os

app = Flask(__name__)

def converti_selca_a_iso(testo_selca: str) -> str:
    righe_greffe = testo_selca.strip().split('\n')
    righe_elaborate = []
    
    # 1. Parsing preliminare per estrarre gli utensili in ordine e associarli alle descrizioni
    utensili_info = [] # Lista di tuple: (num_utensile, descrizione_testo)
    for riga in righe_greffe:
        riga_clean = riga.strip()
        # Cerca pattern tipo T1 M6 [ Descrizione ] oppure T1 M6 ( Descrizione )
        match_t = re.search(r'T(\d+)\s+M6\b\s*[\(\[]\s*(.*?)\s*[\)\]]?', riga_clean, re.IGNORECASE)
        if match_t:
            t_num = match_t.group(1)
            t_desc = match_t.group(2).strip()
            utensili_info.append((t_num, t_desc))

    # Estrae la sequenza di tutti i numeri utensile trovati nel programma
    t_sequenza = [t[0] for t in utensili_info]
    
    idx_utensile_corrente = 0
    n_linea = 2
    modo_movimento_corrente = None
    
    i = 0
    while i < len(righe_greffe):
        riga_grezza = righe_greffe[i].strip()
        i += 1
        
        if not riga_grezza:
            continue
            
        # Gestione righe che sono PURAMENTE commenti (es. ( SGROSSATURA... ))
        if riga_grezza.startswith('[') or riga_grezza.startswith('('):
            commento = riga_grezza
            if commento.startswith('['):
                commento = '(' + commento[1:]
            commento = commento.replace('[', '(').replace(']', ')')
            if not commento.endswith(')'):
                commento += ')'
            righe_elaborate.append(commento)
            continue
            
        # Rimuove il vecchio numero di blocco se presente (es. N4, N6...)
        clean = re.sub(r'^N\d+\s*', '', riga_grezza)
        if not clean:
            continue
            
        # Intercetta il cambio utensile es. T1 M6 [ FRESA ... ] o simili
        match_cambio = re.search(r'T(\d+)\s+M6\b', clean, re.IGNORECASE)
        if match_cambio:
            t_num = match_cambio.group(1)
            
            # Trova la descrizione corrispondente
            descrizione = ""
            for item in utensili_info:
                if item[0] == t_num:
                    descrizione = item[1]
                    break
            if not descrizione:
                # Fallback se la descrizione era dentro la stessa riga ma non intercettata prima
                m_inline = re.search(r'[\(\[]\s*(.*?)\s*[\)\]]', clean)
                descrizione = m_inline.group(1).strip() if m_inline else ""

            # Determina il prossimo utensile per il pre-caricamento (M51)
            prossimo_t = ""
            try:
                current_idx_in_seq = t_sequenza.index(t_num)
                if current_idx_in_seq + 1 < len(t_sequenza):
                    prossimo_t = t_sequenza[current_idx_in_seq + 1]
            except ValueError:
                pass

            # Genera i blocchi strutturati richiesti
            # 1. Blocco cambio utensile principale
            righe_elaborate.append(f"N{n_linea} T{t_num} M06 M5 M9 ( T{t_num} - {descrizione} )")
            n_linea += 2
            
            # 2. Blocco sicurezza e zero pezzo
            righe_elaborate.append(f"N{n_linea} G00 G90 G54")
            n_linea += 2
            
            # 3. Blocco velocità e pre-caricamento successivo (se esiste)
            # Cerchiamo eventuale S nel blocco originale o nelle righe successive immediate
            s_val = "S4400" # Default o cerca nel testo
            m_s = re.search(r'S(\d+)', clean, re.IGNORECASE)
            if m_s:
                s_val = f"S{m_s.group(1)}"
            elif i < len(righe_greffe):
                m_s_next = re.search(r'S(\d+)', righe_greffe[i], re.IGNORECASE)
                if m_s_next:
                    s_val = f"S{m_s_next.group(1)}"
                    i += 1 # Salva la riga S già consumata

            if prossimo_t:
                righe_elaborate.append(f"N{n_linea} {s_val} M3 T{prossimo_t} M51")
            else:
                righe_elaborate.append(f"N{n_linea} {s_val} M3")
            n_linea += 2
            
            continue

        # Gestione riga con S e M3 isolata (se non gestita dal blocco sopra)
        if clean.startswith("S") and "M3" in clean:
            righe_elaborate.append(f"N{n_linea} {clean}")
            n_linea += 2
            # Subito dopo inseriamo G61.1 se siamo all'avvio del pezzo
            righe_elaborate.append(f"N{n_linea} G61.1")
            n_linea += 2
            continue

        # Gestione commenti inline generici
        if '[' in clean or ']' in clean:
            clean = clean.replace('[', '(').replace(']', ')')
            if not clean.endswith(')'):
                clean += ')'
            righe_elaborate.append(f"N{n_linea} {clean}")
            n_linea += 2
            continue
            
        # Spaziatura coordinate appiccicate
        clean = re.sub(r'([XYZ])(-?\d+\.?\d*)', r'\1\2 ', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        
        # Gestione Z pulita se richiesta (es. Z3)
        if clean == "G00 Z3 M18" or clean == "G0 Z3 M18":
            clean = "Z3"
        elif clean.startswith("G00 Z") or clean.startswith("G0 Z"):
            # Se vuoi accorciare i posizionamenti Z isolati in sicurezza
            pass

        # Gestione cicli fissi
        if clean.startswith("G81") or clean.startswith("G84"):
            parts = clean.split()
            cmd_g = parts[0]
            resto = " ".join(parts[1:])
            resto = re.sub(r'J\d+', 'R3', resto)
            clean = f"G99 {cmd_g} {resto}"

        # Gestione movimenti
        if clean.startswith("G00") or clean.startswith("G0 "):
            modo_movimento_corrente = "G00"
        elif clean.startswith("G01") or clean.startswith("G1 "):
            if modo_movimento_corrente == "G01":
                clean = re.sub(r'^G0?1\s*', '', clean)
            else:
                modo_movimento_corrente = "G01"
        else:
            if any(k in clean for k in ['X', 'Y', 'Z']) and not any(g in clean for g in ['G0', 'G1', 'G2', 'G3', 'G40', 'G41', 'G42', 'G81', 'G84']):
                is_lavoro = "F" in clean or modo_movimento_corrente == "G01"
                atteso_g = "G01" if is_lavoro else "G00"
                if atteso_g != modo_movimento_corrente:
                    clean = f"{atteso_g} {clean}"
                    modo_movimento_corrente = atteso_g

        righe_elaborate.append(f"N{n_linea} {clean}")
        n_linea += 2
        
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
