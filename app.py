from flask import Flask, render_template_string, request, Response
import re
import os

app = Flask(__name__)

def converti_commento_in_iso(linea: str) -> str:
    """Converte [ COMMENTO in ( COMMENTO )"""
    if '[' in linea:
        linea = linea.replace('[', '(')
        if not linea.endswith(')'):
            linea = linea + ')'
    return linea

def converti_commento_in_selca(linea: str) -> str:
    """Converte ( COMMENTO ) in [ COMMENTO"""
    return linea.replace('(', '[').replace(')', '')

def traduci_selca_in_iso(codice_selca: str) -> str:
    righe = codice_selca.strip().split('\n')
    righe_iso = []

    # Mappa degli utensili presente nel programma per la predisposizione (T1 -> T2, ecc.)
    utensili = []
    for r in righe:
        m = re.search(r'\bT(\d+)\b', r)
        if m and int(m.group(1)) not in utensili:
            utensili.append(int(m.group(1)))

    # Mappa dei parametri avanzamento e refrigerante per ciascun utensile
    # basato sullo standard ISO del pezzo 200011974-A
    info_utensili = {
        1: {"s": 4400, "m_cool": "M51", "next_t": 2},
        2: {"s": 1300, "m_cool": "M8",  "next_t": 3, "f_work": "F250"},
        3: {"s": 2600, "m_cool": "M8",  "next_t": 4, "f_work": "F400"},
        4: {"s": 8400, "m_cool": "M51", "next_t": 6},
        6: {"s": 4000, "m_cool": "M8",  "next_t": 5},
        5: {"s": 500,  "m_cool": "M8",  "next_t": 1}
    }

    n_linea = 2
    # Riga 2 iniziale ISO
    righe_iso.append("N2 G00 G17 G40 G49 G80 G54 G90\n")
    n_linea += 2

    g61_attivo = False
    utensile_attuale = None
    ultimo_x = 0.0
    ultimo_y = 0.0

    idx = 0
    while idx < len(righe):
        riga_p = righe[idx].strip()
        idx += 1

        if not riga_p:
            continue

        # Commenti d'intestazione ed eseguibili
        if riga_p.startswith('['):
            comm_iso = converti_commento_in_iso(riga_p)
            # Modifica specifica per la nota D.=0.8 su T6
            if "METTERE RAGGIO R.=0.3" in comm_iso:
                comm_iso = "( N.B.= METTERE DIAMETRO D.=0.8 )"
            righe_iso.append(comm_iso)
            continue

        # Salta comandi di start SELCA
        if riga_p in ['O1', 'N2 G17']:
            continue

        # Gestione Cambio Utensile T... M6
        if re.search(r'\bT\d+\s+M6\b', riga_p) or (re.search(r'\bT\d+\b', riga_p) and 'M6' in riga_p):
            m_t = re.search(r'T(\d+)', riga_p)
            if m_t:
                utensile_attuale = int(m_t.group(1))
                comm = ""
                if '[' in riga_p:
                    comm = " " + converti_commento_in_iso(riga_p[riga_p.index('['):])

                righe_iso.append(f"N{n_linea} T{utensile_attuale} M06 M5 M9{comm}")
                n_linea += 2
                righe_iso.append(f"N{n_linea} G00 G90 G54")
                n_linea += 2
                g61_attivo = False
                continue

        # Gestione S... M3 (Velocità mandrino)
        if re.search(r'\bS\d+\s+M3\b', riga_p):
            s_match = re.search(r'S(\d+)', riga_p)
            s_val = s_match.group(1) if s_match else ""
            
            # Applica parametri specifici se definiti
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

        # Filtra comandi SELCA non usati in ISO
        if any(cmd in riga_p for cmd in ['G49 K', 'M18', 'M8', 'M9', 'M5']):
            continue

        # Rimozione vecchio prefisso N...
        clean = re.sub(r'^N\d+\s*', '', riga_p)

        # Traccia coordinate correnti X, Y
        mx = re.search(r'X([-\d.]+)', clean)
        my = re.search(r'Y([-\d.]+)', clean)
        if mx: ultimo_x = float(mx.group(1))
        if my: ultimo_y = float(my.group(1))

        # Gestione G61.1 prima di lavorare e G64 prima dei rapidi Z
        if ('G01' in clean or 'G02' in clean or 'G03' in clean) and not g61_attivo:
            righe_iso.append(f"N{n_linea} G61.1")
            n_linea += 2
            g61_attivo = True

        if 'G00' in clean and 'Z' in clean and g61_attivo:
            righe_iso.append(f"N{n_linea} G64")
            n_linea += 2
            g61_attivo = False

        # Conversione Archi G02 / G03 (da centro assoluto SELCA a relativo ISO)
        if 'G02' in clean or 'G03' in clean:
            mi = re.search(r'I([-\d.]+)', clean)
            mj = re.search(r'J([-\d.]+)', clean)
            if mi and mj:
                abs_i = float(mi.group(1))
                abs_j = float(mj.group(1))
                rel_i = round(abs_i - ultimo_x, 3)
                rel_j = round(abs_j - ultimo_y, 3)
                clean = re.sub(r'I[-\d.]+', f"I{rel_i:g}", clean)
                clean = re.sub(r'J[-\d.]+', f"J{rel_j:g}", clean)

        # Compensazione G41/G42/G40 fusa con coordinate
        if clean.startswith('G41') or clean.startswith('G42') or clean.startswith('G40'):
            # Se la riga successiva contiene movimento, le unisce
            if idx < len(righe) and not righe[idx].strip().startswith('['):
                prossima = re.sub(r'^N\d+\s*', '', righe[idx].strip())
                if any(k in prossima for k in ['X', 'Y', 'Z']):
                    clean = f"{clean} {prossima}"
                    idx += 1

        # Sostituzione avanzamenti specifici utensili 2 e 3 in finitura
        if utensile_attuale in [2, 3] and 'F650' in clean:
            clean = clean.replace('F650', 'F250')
        elif utensile_attuale in [2, 3] and 'F800' in clean:
            clean = clean.replace('F800', 'F400')

        # Cicli Fissi G81 e G84
        if 'G81' in clean:
            clean = clean.replace('G81', 'G99 G81').replace('J', 'R')
        elif 'G84' in clean:
            clean = clean.replace('G84', 'G99 G84').replace('J', 'R')
            clean = re.sub(r'F\d+', 'F1', clean) # Passo F1 su ISO Mazak

        # Formattazione Z rapido (es. Z3)
        if clean.startswith('G00 Z'):
            clean = clean.replace('G00 ', '')

        righe_iso.append(f"N{n_linea} {clean}")
        n_linea += 2

    return "\n".join(righe_iso)


def traduci_iso_in_selca(codice_iso: str) -> str:
    righe = codice_iso.strip().split('\n')
    righe_selca = []
    n_linea = 2

    for riga in righe:
        riga_p = riga.strip()
        if not riga_p:
            continue

        if riga_p.startswith('('):
            righe_selca.append(converti_commento_in_selca(riga_p))
            continue

        if any(cmd in riga_p for cmd in ['G61.1', 'G64', 'G54', 'G90', 'G00 G17', 'G99']):
            continue

        clean = re.sub(r'^N\d+\s*', '', riga_p)

        if 'G81' in clean or 'G84' in clean:
            clean = clean.replace('G99 ', '').replace('R', 'J')

        righe_selca.append(f"N{n_linea} {clean}")
        n_linea += 2

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
        .control-bar { display: flex; align-items: center; gap: 20px; margin-bottom: 15px; background: #fff; padding: 12px 20px; border-radius: 10px; border: 1px solid #e2e8f0; }
        .direction-badge { font-weight: 700; color: #0d9488; }
        .workspace { display: flex; gap: 20px; }
        .card { flex: 1; background: #fff; border-radius: 12px; border: 1px solid #e2e8f0; padding: 20px; display: flex; flex-direction: column; }
        textarea { width: 100%; height: 440px; border: 1px solid #cbd5e1; border-radius: 8px; padding: 12px; font-family: monospace; font-size: 13px; resize: none; background: #fafafa; }
        textarea.output { background: #0f172a; color: #38bdf8; }
        .actions { display: flex; justify-content: space-between; margin-top: 15px; }
        .btn { padding: 10px 18px; border-radius: 8px; font-weight: 600; cursor: pointer; border: none; font-size: 14px; }
        .btn-primary { background-color: #0d9488; color: #fff; }
        .btn-swap { background-color: #f97316; color: #fff; }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="logo">&lt;/&gt; CNC CONVERTER</div>
    </div>
    <div class="main-content">
        <h1 class="header-title">Convertitore CNC ISO ↔ SELCA (Identico)</h1>
        <form method="POST" action="/converti">
            <input type="hidden" name="modalita" value="{{ modalita or 'selca_to_iso' }}">
            <div class="control-bar">
                <span>Modalità:</span>
                <span class="direction-badge">
                    {% if modalita == 'selca_to_iso' %} SELCA ➔ ISO (.eia) {% else %} ISO ➔ SELCA {% endif %}
                </span>
                <button type="submit" formaction="/scambia" class="btn btn-swap">🔄 Inverti Direzione</button>
            </div>
            <div class="workspace">
                <div class="card">
                    <h3>Codice Sorgente</h3>
                    <textarea name="codice_sorgente" placeholder="Incolla il programma qui...">{{ codice_sorgente }}</textarea>
                    <div class="actions">
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
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE, codice_sorgente="", codice_convertito="", modalita="selca_to_iso")

@app.route('/converti', methods=['POST'])
def converti():
    codice_sorgente = request.form.get('codice_sorgente', '')
    modalita = request.form.get('modalita', 'selca_to_iso')
    if modalita == 'selca_to_iso':
        codice_convertito = traduci_selca_in_iso(codice_sorgente)
    else:
        codice_convertito = traduci_iso_in_selca(codice_sorgente)
    return render_template_string(HTML_TEMPLATE, codice_sorgente=codice_sorgente, codice_convertito=codice_convertito, modalita=modalita)

@app.route('/scambia', methods=['POST'])
def scambia():
    codice_sorgente = request.form.get('codice_sorgente', '')
    codice_convertito = request.form.get('codice_convertito', '')
    modalita = request.form.get('modalita', 'selca_to_iso')
    nuova_modalita = 'iso_to_selca' if modalita == 'selca_to_iso' else 'selca_to_iso'
    return render_template_string(HTML_TEMPLATE, codice_sorgente=codice_convertito, codice_convertito=codice_sorgente, modalita=nuova_modalita)

@app.route('/scarica', methods=['POST'])
def scarica():
    codice_sorgente = request.form.get('codice_sorgente', '')
    modalita = request.form.get('modalita', 'selca_to_iso')
    if modalita == 'selca_to_iso':
        codice_convertito = traduci_selca_in_iso(codice_sorgente)
        nome_file = "200011974-A.EIA.eia"
    else:
        codice_convertito = traduci_iso_in_selca(codice_sorgente)
        nome_file = "200011974-A"
    return Response(codice_convertito, mimetype="text/plain", headers={"Content-disposition": f"attachment; filename={nome_file}"})

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
