from flask import Flask, render_template_string, request, Response
import re
import os

app = Flask(__name__)

def traduci_iso_in_selca(codice_iso: str) -> str:
    righe = codice_iso.strip().split('\n')
    righe_selca = []
    
    for riga in righe:
        riga_pulita = riga.strip().upper()
        if not riga_pulita or riga_pulita.startswith('(') or riga_pulita.startswith('%'):
            continue

        if riga_pulita.startswith('O'):
            num_prog = re.search(r'O(\d+)', riga_pulita)
            if num_prog:
                righe_selca.append(f"O{num_prog.group(1)}")
            continue

        if 'T' in riga_pulita and 'M6' in riga_pulita:
            m_utensile = re.search(r'T(\d+)', riga_pulita)
            if m_utensile:
                righe_selca.append(f"T{m_utensile.group(1)}")
                righe_selca.append("M6")
            continue

        if 'G81' in riga_pulita:
            m_x = re.search(r'X([-\d.]+)', riga_pulita)
            m_y = re.search(r'Y([-\d.]+)', riga_pulita)
            m_z = re.search(r'Z([-\d.]+)', riga_pulita)
            m_r = re.search(r'R([-\d.]+)', riga_pulita)
            m_f = re.search(r'F([-\d.]+)', riga_pulita)

            pos_x = f"X{m_x.group(1)}" if m_x else ""
            pos_y = f"Y{m_y.group(1)}" if m_y else ""
            if pos_x or pos_y:
                righe_selca.append(f"G0 {pos_x} {pos_y}".strip())

            z_val = m_z.group(1) if m_z else "0"
            r_val = m_r.group(1) if m_r else "2"
            f_val = f"F{m_f.group(1)}" if m_f else ""
            righe_selca.append(f"G81 Z{z_val} R{r_val} {f_val}".strip())
            continue

        if 'G80' in riga_pulita:
            righe_selca.append("G80")
            continue

        righe_selca.append(riga_pulita)

    return "\n".join(righe_selca)

def traduci_selca_in_iso(codice_selca: str) -> str:
    righe = codice_selca.strip().split('\n')
    righe_iso = []
    
    for riga in righe:
        riga_pulita = riga.strip().upper()
        if not riga_pulita or riga_pulita.startswith('(') or riga_pulita.startswith('%'):
            continue

        if riga_pulita.startswith('O'):
            num_prog = re.search(r'O(\d+)', riga_pulita)
            if num_prog:
                righe_iso.append(f"O{num_prog.group(1)}")
            continue

        if 'G81' in riga_pulita:
            m_z = re.search(r'Z([-\d.]+)', riga_pulita)
            m_r = re.search(r'R([-\d.]+)', riga_pulita)
            m_f = re.search(r'F([-\d.]+)', riga_pulita)
            z_val = f"Z{m_z.group(1)}" if m_z else "Z0"
            r_val = f"R{m_r.group(1)}" if m_r else "R2"
            f_val = f"F{m_f.group(1)}" if m_f else ""
            righe_iso.append(f"G81 {z_val} {r_val} {f_val}".strip())
            continue

        righe_iso.append(riga_pulita)

    return "\n".join(righe_iso)


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="UTF-8">
    <title>Convertitore ISO ↔ SELCA</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; }
        body { display: flex; height: 100vh; background-color: #f7f6f0; color: #1e293b; }
        
        .sidebar { width: 260px; background-color: #1e293b; color: #fff; padding: 20px; display: flex; flex-direction: column; gap: 20px; }
        .logo { font-size: 18px; font-weight: bold; color: #38bdf8; display: flex; align-items: center; gap: 10px; }
        .menu-item { padding: 12px 15px; border-radius: 8px; background: #334155; color: #fff; text-decoration: none; font-size: 14px; font-weight: 500; }
        
        .main-content { flex: 1; padding: 40px; overflow-y: auto; }
        .header-subtitle { color: #64748b; font-size: 12px; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 8px; }
        .header-title { font-size: 30px; font-weight: 800; color: #0f172a; margin-bottom: 12px; }
        .header-title span { color: #0d9488; }
        
        .direction-bar { display: flex; align-items: center; gap: 15px; margin-bottom: 15px; background: #fff; padding: 12px 20px; border-radius: 10px; border: 1px solid #e2e8f0; width: fit-content; }
        .direction-badge { font-weight: 700; font-size: 14px; color: #0d9488; }

        .workspace { display: flex; gap: 20px; margin-top: 10px; }
        .card { flex: 1; background: #fff; border-radius: 12px; border: 1px solid #e2e8f0; padding: 20px; display: flex; flex-direction: column; }
        .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 15px; }
        .card-title { font-weight: 700; font-size: 15px; color: #334155; }
        
        textarea { width: 100%; height: 320px; border: 1px dashed #cbd5e1; border-radius: 8px; padding: 15px; font-family: monospace; font-size: 14px; resize: none; outline: none; background: #fafafa; }
        textarea.output { background: #0f172a; color: #38bdf8; border: none; }
        
        .actions { display: flex; justify-content: space-between; align-items: center; margin-top: 15px; }
        .btn { padding: 10px 18px; border-radius: 8px; font-weight: 600; cursor: pointer; border: none; font-size: 14px; display: inline-flex; align-items: center; gap: 6px; }
        .btn-primary { background-color: #5eead4; color: #0f172a; }
        .btn-primary:hover { background-color: #2dd4bf; }
        .btn-secondary { background-color: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; }
        .btn-swap { background-color: #f97316; color: #fff; }
        .btn-swap:hover { background-color: #ea580c; }
    </style>
</head>
<body>

    <div class="sidebar">
        <div class="logo">
            <span style="background: #f97316; color: #fff; padding: 4px 8px; border-radius: 6px;">&lt;/&gt;</span>
            ISO ↔ SELCA
        </div>
        <a href="#" class="menu-item">⇆ Convertitore</a>
    </div>

    <div class="main-content">
        <div class="header-subtitle">Trasformazione dei file controllata</div>
        <h1 class="header-title">Rendere visibile il cambiamento prima che raggiunga <span>la macchina.</span></h1>

        <form method="POST" action="/converti" id="mainForm">
            <input type="hidden" name="modalita" id="modalitaInput" value="{{ modalita or 'iso_to_selca' }}">

            <div class="direction-bar">
                <span>Modalità attuale:</span>
                <span class="direction-badge" id="directionLabel">
                    {% if modalita == 'selca_to_iso' %} SELCA ➔ ISO {% else %} ISO ➔ SELCA {% endif %}
                </span>
                <button type="submit" formaction="/scambia" class="btn btn-swap">🔄 Inverti Direzione</button>
            </div>

            <div class="workspace">
                <div class="card">
                    <div class="card-header">
                        <span class="card-title" id="titleSorgente">
                            {% if modalita == 'selca_to_iso' %} ➔ Fonte SELCA {% else %} ➔ Fonte ISO {% endif %}
                        </span>
                    </div>
                    <textarea name="codice_sorgente" placeholder="Incolla il tuo programma qui...">{{ codice_sorgente }}</textarea>
                    <div class="actions">
                        <button type="button" class="btn btn-secondary" onclick="document.getElementById('fileInput').click()">File di carico</button>
                        <input type="file" id="fileInput" style="display:none" onchange="caricaFile(this)">
                        <button type="submit" class="btn btn-primary">⚡ Convertire il programma</button>
                    </div>
                </div>

                <div class="card">
                    <div class="card-header">
                        <span class="card-title" id="titleDestinazione">
                            {% if modalita == 'selca_to_iso' %} ∿ Uscita ISO {% else %} ∿ Uscita SELCA {% endif %}
                        </span>
                    </div>
                    <textarea class="output" name="codice_convertito" readonly placeholder="I tuoi blocchi convertiti atterreranno qui.">{{ codice_convertito }}</textarea>
                    <div class="actions" style="justify-content: flex-end; gap: 10px;">
                        <button type="button" class="btn btn-secondary" onclick="copiaTesto()">Copia</button>
                        <button type="submit" formaction="/scarica" class="btn btn-primary">Scarica .NC</button>
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

        function copiaTesto() {
            let copyText = document.querySelector(".output");
            copyText.select();
            document.execCommand("copy");
            alert("Codice copiato!");
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE, codice_sorgente="", codice_convertito="", modalita="iso_to_selca")

@app.route('/converti', methods=['POST'])
def converti():
    codice_sorgente = request.form.get('codice_sorgente', '')
    modalita = request.form.get('modalita', 'iso_to_selca')
    
    if modalita == 'selca_to_iso':
        codice_convertito = traduci_selca_in_iso(codice_sorgente)
    else:
        codice_convertito = traduci_iso_in_selca(codice_sorgente)
        
    return render_template_string(HTML_TEMPLATE, codice_sorgente=codice_sorgente, codice_convertito=codice_convertito, modalita=modalita)

@app.route('/scambia', methods=['POST'])
def scambia():
    codice_sorgente = request.form.get('codice_sorgente', '')
    codice_convertito = request.form.get('codice_convertito', '')
    modalita = request.form.get('modalita', 'iso_to_selca')
    
    nuova_modalita = 'selca_to_iso' if modalita == 'iso_to_selca' else 'iso_to_selca'
    
    # Inverte anche il testo presente nei box
    return render_template_string(HTML_TEMPLATE, codice_sorgente=codice_convertito, codice_convertito=codice_sorgente, modalita=nuova_modalita)

@app.route('/scarica', methods=['POST'])
def scarica():
    codice_sorgente = request.form.get('codice_sorgente', '')
    modalita = request.form.get('modalita', 'iso_to_selca')
    
    if modalita == 'selca_to_iso':
        codice_convertito = traduci_selca_in_iso(codice_sorgente)
        nome_file = "programma_iso.nc"
    else:
        codice_convertito = traduci_iso_in_selca(codice_sorgente)
        nome_file = "programma_selca.nc"
        
    return Response(
        codice_convertito,
        mimetype="text/plain",
        headers={"Content-disposition": f"attachment; filename={nome_file}"}
    )

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
