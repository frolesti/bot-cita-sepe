import json
import csv
import os

def process_municipis():
    # Define paths relative to this script
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR = os.path.join(BASE_DIR, 'data')
    
    input_file = os.path.join(DATA_DIR, 'municipis_data.txt') # Assuming input is also in data or root? Let's assume root for input or data.
    # Actually input file 'municipis_data.txt' was not in the file list earlier. It might be missing or I missed it.
    # Let's assume it should be in data if it exists.
    
    json_output_file = os.path.join(DATA_DIR, 'municipis_catalunya.json')
    comarques_output_file = os.path.join(DATA_DIR, 'comarques_catalunya.json')

    data = []
    comarques = set()

    if not os.path.exists(input_file):
        print(f"Error: {input_file} not found.")
        return

    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or not line.startswith('|'):
                continue
            
            parts = [p.strip() for p in line.split('|')]
            # parts[0] is empty string because line starts with |
            # parts[1] is Municipality
            # parts[2] is Comarca
            # parts[3] is Province
            
            if len(parts) < 4:
                continue

            municipality = parts[1]
            comarca = parts[2]
            province = parts[3]

            # Skip header if present (though I didn't include it in the file)
            if municipality.lower() == 'municipality':
                continue

            entry = {
                'municipality': municipality,
                'comarca': comarca,
                'province': province
            }
            data.append(entry)
            comarques.add(comarca)

    # Write JSON
    with open(json_output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print(f"Created {json_output_file} with {len(data)} entries.")

    # Write Comarques List
    sorted_comarques = sorted(list(comarques))
    with open(comarques_output_file, 'w', encoding='utf-8') as f:
        json.dump(sorted_comarques, f, ensure_ascii=False, indent=4)
    print(f"Created {comarques_output_file} with {len(sorted_comarques)} comarques.")

if __name__ == "__main__":
    process_municipis()
