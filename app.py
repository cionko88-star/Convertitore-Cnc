import re
import sys

def converti_selca_a_iso(testo_selca: str) -> str:
    righe = testo_selca.strip().split('\n')
    righe_iso = []
    
    n_linea = 2
    modo_movimento_corrente = None
    
    for riga in righe:
        riga_grezza = riga.strip()
        
        # Se la riga è vuota, salta
        if not riga_grezza:
            continue
            
        # Gestione e conservazione dei commenti (es. da [...] a (...))
        if riga_grezza.startswith('[') or riga_grezza.startswith('('):
            commento = riga_grezza.replace('[', '(').replace(']', ')')
            if not commento.endswith(')'):
                commento += ')'
            righe_iso.append(commento)
            continue
            
        # Rimuove il vecchio numero di blocco se presente (es. N4, N6...)
        clean = re.sub(r'^N\d+\s*', '', riga_grezza)
        if not clean:
            continue
            
        # Aggiunta spaziatura corretta tra le coordinate appiccicate (es. X429Y345 -> X429 Y345)
        clean = re.sub(r'([XYZ])(-?\d+\.?\d*)', r'\1\2 ', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        
        # Gestione cicli di foratura / maschiatura (es. G81, G84)
        if clean.startswith("G81") or clean.startswith("G84"):
            parts = clean.split()
            cmd_g = parts[0]
            resto = " ".join(parts[1:])
            resto = re.sub(r'J\d+', 'R3', resto) # Eventuale adattamento parametri quote
            clean = f"G99 {cmd_g} {resto}"

        # Gestione movimenti e modalità
        if clean.startswith("G00") or clean.startswith("G0 "):
            modo_movimento_corrente = "G00"
        elif clean.startswith("G01") or clean.startswith("G1 "):
            if modo_movimento_corrente == "G01":
                clean = re.sub(r'^G0?1\s*', '', clean)
            else:
                modo_movimento_corrente = "G01"
        else:
            # Se ci sono coordinate ma manca il comando G attivo, lo deduce
            if any(k in clean for k in ['X', 'Y', 'Z']) and not any(g in clean for g in ['G0', 'G1', 'G2', 'G3', 'G40', 'G41', 'G42', 'G81', 'G84']):
                is_lavoro = "F" in clean or modo_movimento_corrente == "G01"
                atteso_g = "G01" if is_lavoro else "G00"
                if atteso_g != modo_movimento_corrente:
                    clean = f"{atteso_g} {clean}"
                    modo_movimento_corrente = atteso_g

        # Scrittura della riga formattata con numerazione standard ISO (N...)
        righe_iso.append(f"N{n_linea} {clean}")
        n_linea += 2
        
    return "\n".join(righe_iso)

def converti_file(percorso_input, percorso_output):
    try:
        with open(percorso_input, 'r', encoding='utf-8') as f:
            contenuto = f.read()
            
        risultato = converti_selca_a_iso(contenuto)
        
        with open(percorso_output, 'w', encoding='utf-8') as f:
            f.write(risultato)
            
        print(f"Conversione completata con successo! File salvato in: {percorso_output}")
    except Exception as e:
        print(f"Errore durante la conversione: {e}")

if __name__ == "__main__":
    # Esempio d'uso da riga di comando o script diretto
    if len(sys.argv) > 2:
        converti_file(sys.argv[1], sys.argv[2])
    else:
        print("Utilizzo: python convertitore.py <file_input.sel> <file_output.eia>")
