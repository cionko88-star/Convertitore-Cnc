import re
from datetime import datetime

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
    ha_lavorato_questo_utensile = False

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

        # Gestione commenti / sezioni
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
        clean = re.sub(r'\bM0?[59]\b', '', clean).strip()
        if not clean:
            continue

        # Cambio Utensile (M6)
        if re.search(r'\bT\d+\s+M6\b', clean) or (re.search(r'\bT\d+\b', clean) and 'M6' in clean):
            if ha_lavorato_questo_utensile:
                righe_iso.append(f"N{n_linea} M5")
                n_linea += 2
                righe_iso.append(f"N{n_linea} M9")
                n_linea += 2
                ha_lavorato_questo_utensile = False

            m_t = re.search(r'T(\d+)', clean)
            if m_t:
                utensile_attuale = int(m_t.group(1))
                comm = ""
                if '[' in clean:
                    comm = " " + clean[clean.index('['):].replace('[', '(')
                    if not comm.endswith(')'): comm += ')'
                
                righe_iso.append(f"N{n_linea} T{utensile_attuale} M06{comm}")
                n_linea += 2
                righe_iso.append(f"N{n_linea} G00 G90 G54")
                n_linea += 2
                continue

        # Avvio Mandrino (Se subito dopo c'è un blocco di smussi senza Z positivo o cambio utensile, evitiamo lo spegnimento intermedio se voluto, 
        # ma qui gestiamo normalmente l'S... M3)
        if re.search(r'\bS\d+\s+M3\b', clean):
            s_match = re.search(r'S(\d+)', clean)
            s_val = s_match.group(1) if s_match else ""
            
            info = info_utensili.get(utensile_attuale, {})
            if info:
                s_val = str(info.get("s", s_val))
                next_t = info.get("next_t", "")
                m_cool = info.get("m_cool", "M8")
                # Se siamo sul blocco SMUSSI CAVE del T6 (dove non c'è M6 in mezzo ma solo S9000 M3), 
                # evitiamo di rimettere T(next) e M8 se il mandrino era già avviato o gestito, oppure lasciamo coerenza:
                if utensile_attuale == 6 and s_val == "9000":
                    righe_iso.append(f"N{n_linea} S{s_val} M3")
                else:
                    righe_iso.append(f"N{n_linea} S{s_val} M3 T{next_t} {m_cool}")
            else:
                righe_iso.append(f"N{n_linea} S{s_val} M3")
            
            n_linea += 2
            ha_lavorato_questo_utensile = True
            continue

        # Se SELCA ha G41/G42 isolato
        if clean in ["G41", "G42"] and idx < len(righe):
            prossima = re.sub(r'^N\d+\s*', '', righe[idx].strip())
            prossima = re.sub(r'\bM0?[59]\b', '', prossima).strip()
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
                ha_lavorato_questo_utensile = True
                continue

        # Se SELCA ha G40 isolato
        if clean == "G40" and idx < len(righe):
            prossima = re.sub(r'^N\d+\s*', '', righe[idx].strip())
            prossima = re.sub(r'\bM0?[59]\b', '', prossima).strip()
            if any(k in prossima for k in ['X', 'Y']):
                righe_iso.append(f"N{n_linea} G40 {prossima}")
                
                m_x = re.search(r'X(-?\d+(\.\d+)?)', prossima)
                m_y = re.search(r'Y(-?\d+(\.\d+)?)', prossima)
                if m_x: curr_x = float(m_x.group(1))
                if m_y: curr_y = float(m_y.group(1))
                
                n_linea += 2
                idx += 1
                ha_lavorato_questo_utensile = True
                continue

        # CONVERSIONE ARCHI G02 / G03
        if clean.startswith("G02") or clean.startswith("G03") or clean.startswith("G2") or clean.startswith("G3"):
            parts = clean.split()
            cmd_g = parts[0]
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
                
            clean = f"{cmd_g} " + " ".join(new_tokens)
            ha_lavorato_questo_utensile = True

        # Tracciamento coordinate
        m_x = re.search(r'X(-?\d+(\.\d+)?)', clean)
        m_y = re.search(r'Y(-?\d+(\.\d+)?)', clean)
        m_z = re.search(r'Z(-?\d+(\.\d+)?)', clean)
        if m_x: curr_x = float(m_x.group(1))
        if m_y: curr_y = float(m_y.group(1))

        # CICLI DI FORATURA/MASCHIATURA
        if any(ciclo in clean for ciclo in ["G81", "G84", "G85"]):
            clean_iso = re.sub(r'\bJ(\d+(\.\d+)?)', r'R\1', clean)
            if not clean_iso.startswith("G99"):
                clean_iso = "G99 " + clean_iso
            righe_iso.append(f"N{n_linea} {clean_iso}")
            n_linea += 2
            ha_lavorato_questo_utensile = True
            continue

        if "M18" in clean or "M8" in clean:
            clean = re.sub(r'\bM18\b|\bM8\b', '', clean).strip()
            if not clean:
                continue

        righe_iso.append(f"N{n_linea} {clean}")
        n_linea += 2
        if any(k in clean for k in ['X', 'Y', 'Z', 'G0', 'G1', 'G2', 'G3']):
            ha_lavorato_questo_utensile = True

        # CONTROLLO: INSERISCI M5 E M9 SUBITO DOPO IL POSIZIONAMENTO FINALE IN Z POSITIVO (es. G00 Z100)
        is_ritiro_z = m_z and float(m_z.group(1)) > 0
        if is_ritiro_z and ha_lavorato_questo_utensile:
            # Evitiamo di mettere M5/M9 se siamo nel bel mezzo di lavorazioni consecutive dello stesso utensile senza ritiro a Z100 (es. tra SMUSSI M6 e SMUSSI CAVE del T6)
            # Il ritiro finale a Z100 c'è alla fine di SMUSSI CAVE, quindi lì scatterà correttamente.
            if not (utensile_attuale == 6 and "9000" in righe[max(0, idx-2)]): # piccolo check di sicurezza o lasciamo gestire dallo Z100
                pass
            
            righe_iso.append(f"N{n_linea} M5")
            n_linea += 2
            righe_iso.append(f"N{n_linea} M9")
            n_linea += 2
            ha_lavorato_questo_utensile = False

    # Chiusura finale di sicurezza
    if righe_iso and ha_lavorato_questo_utensile:
        righe_iso.append(f"N{n_linea} M5")
        n_linea += 2
        righe_iso.append(f"N{n_linea} M9")

    return "\n".join(righe_iso)
