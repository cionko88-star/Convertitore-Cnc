import re
import sys

def converti_selca_a_iso(testo_selca: str) -> str:
    righe = testo_selca.strip().split('\n')
    righe_iso = []
    
    n_linea = 2
    modo_movimento_corrente = None
    
    for riga in righe:
        riga_grezza = riga.strip()
        
        if not riga_grezza:
            continue
            
        # Conservazione e conversione dei commenti (da [...] a (...))
        if riga_grezza.startswith('[') or riga_grezza.startswith('('):
            commento = riga_grezza.replace('[', '(').replace(']', ')')
            if not commento.endswith(')'):
                commento += ')'
            righe_iso.append(commento)
            continue
            
        # Rimuove il vecchio numero di blocco se presente
        clean = re.sub(r'^N\d+\s*', '', riga_grezza)
        if not clean:
            continue
            
        # Spaziatura coordinate appiccicate
        clean = re.sub(r'([XYZ])(-?\d+\.?\d*)', r'\1\2 ', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        
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

        righe_iso.append(f"N{n_linea} {clean}")
        n_linea += 2
        
    return "\n".join(righe_iso)

def converti_file(percorso_input, percorso_output):
    # Tentativo di lettura con codifiche multiple per evitare errori di caricamento
    codifiche = ['utf-8', 'latin-1', 'cp1252', 'iso-8859-1']
    contenuto = None
    
    for enc in codifiche:
        try:
            with open(percorso_input, 'r', encoding=enc) as f:
                contenuto = f.read()
            print(f"File letto con successo usando la codifica: {enc}")
            break
        except UnicodeDecodeError:
            continue
            
    if contenuto is None:
        print("Errore: Impossibile leggere il file. Codifica non riconosciuta.")
        return

    try:
        risultato = converti_selca_a_iso(contenuto)
        
        with open(percorso_output, 'w', encoding='utf-8') as f:
            f.write(risultato)
            
        print(f"Conversione completata! File salvato in: {percorso_output}")
    except Exception as e:
        print(f"Errore durante la scrittura del file convertito: {e}")

if __name__ == "__main__":
    if len(sys.argv) > 2:
        converti_file(sys.argv[1], sys.argv[2])
    else:
        print("Utilizzo: python convertitore.py <file_input.sel> <file_output.eia>")
