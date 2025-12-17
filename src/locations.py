import json
import os
import requests
import csv
import io
import logging

logger = logging.getLogger(__name__)

# URLs dels datasets
URL_MUNICIPIOS = "https://raw.githubusercontent.com/codeforspain/ds-organizacion-administrativa/master/data/municipios.csv"
URL_CODIGOS_POSTALES = "https://raw.githubusercontent.com/inigoflores/ds-codigos-postales/master/data/codigos_postales_municipios.csv"

# Define paths relative to this file
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, 'data')
CACHE_FILE = os.path.join(DATA_DIR, "locations_cache.json")

# Mapeig de codis de província (primers 2 dígits del CP) a Nom i Comunitat
PROVINCE_DATA = {
    "01": {"name": "Araba/Álava", "community": "País Vasco"},
    "02": {"name": "Albacete", "community": "Castilla-La Mancha"},
    "03": {"name": "Alicante/Alacant", "community": "Comunidad Valenciana"},
    "04": {"name": "Almería", "community": "Andalucía"},
    "05": {"name": "Ávila", "community": "Castilla y León"},
    "06": {"name": "Badajoz", "community": "Extremadura"},
    "07": {"name": "Illes Balears", "community": "Illes Balears"},
    "08": {"name": "Barcelona", "community": "Cataluña"},
    "09": {"name": "Burgos", "community": "Castilla y León"},
    "10": {"name": "Cáceres", "community": "Extremadura"},
    "11": {"name": "Cádiz", "community": "Andalucía"},
    "12": {"name": "Castellón/Castelló", "community": "Comunidad Valenciana"},
    "13": {"name": "Ciudad Real", "community": "Castilla-La Mancha"},
    "14": {"name": "Córdoba", "community": "Andalucía"},
    "15": {"name": "A Coruña", "community": "Galicia"},
    "16": {"name": "Cuenca", "community": "Castilla-La Mancha"},
    "17": {"name": "Girona", "community": "Cataluña"},
    "18": {"name": "Granada", "community": "Andalucía"},
    "19": {"name": "Guadalajara", "community": "Castilla-La Mancha"},
    "20": {"name": "Gipuzkoa", "community": "País Vasco"},
    "21": {"name": "Huelva", "community": "Andalucía"},
    "22": {"name": "Huesca", "community": "Aragón"},
    "23": {"name": "Jaén", "community": "Andalucía"},
    "24": {"name": "León", "community": "Castilla y León"},
    "25": {"name": "Lleida", "community": "Cataluña"},
    "26": {"name": "La Rioja", "community": "La Rioja"},
    "27": {"name": "Lugo", "community": "Galicia"},
    "28": {"name": "Madrid", "community": "Madrid"},
    "29": {"name": "Málaga", "community": "Andalucía"},
    "30": {"name": "Murcia", "community": "Murcia"},
    "31": {"name": "Navarra", "community": "Navarra"},
    "32": {"name": "Ourense", "community": "Galicia"},
    "33": {"name": "Asturias", "community": "Asturias"},
    "34": {"name": "Palencia", "community": "Castilla y León"},
    "35": {"name": "Las Palmas", "community": "Canarias"},
    "36": {"name": "Pontevedra", "community": "Galicia"},
    "37": {"name": "Salamanca", "community": "Castilla y León"},
    "38": {"name": "Santa Cruz de Tenerife", "community": "Canarias"},
    "39": {"name": "Cantabria", "community": "Cantabria"},
    "40": {"name": "Segovia", "community": "Castilla y León"},
    "41": {"name": "Sevilla", "community": "Andalucía"},
    "42": {"name": "Soria", "community": "Castilla y León"},
    "43": {"name": "Tarragona", "community": "Cataluña"},
    "44": {"name": "Teruel", "community": "Aragón"},
    "45": {"name": "Toledo", "community": "Castilla-La Mancha"},
    "46": {"name": "Valencia/València", "community": "Comunidad Valenciana"},
    "47": {"name": "Valladolid", "community": "Castilla y León"},
    "48": {"name": "Bizkaia", "community": "País Vasco"},
    "49": {"name": "Zamora", "community": "Castilla y León"},
    "50": {"name": "Zaragoza", "community": "Aragón"},
    "51": {"name": "Ceuta", "community": "Ceuta"},
    "52": {"name": "Melilla", "community": "Melilla"}
}

class LocationManager:
    _data = {}
    _cat_data = []
    CAT_DATA_FILE = os.path.join(DATA_DIR, "municipis_catalunya.json")

    @classmethod
    def load_cat_data(cls):
        if cls._cat_data: return
        try:
            if os.path.exists(cls.CAT_DATA_FILE):
                with open(cls.CAT_DATA_FILE, 'r', encoding='utf-8') as f:
                    cls._cat_data = json.load(f)
        except Exception as e:
            print(f"Error loading cat data: {e}")

    @classmethod
    def get_comarques(cls, province=None):
        cls.load_cat_data()
        
        items = cls._cat_data
        if province:
            # Handle list
            if isinstance(province, list):
                items = [i for i in items if i.get('province') in province]
            else:
                items = [i for i in items if i.get('province') == province]
                
        return sorted(list(set(item['comarca'] for item in items if 'comarca' in item)))

    @classmethod
    def load_data(cls):
        """Carrega les dades del fitxer local o les descarrega si no existeix."""
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                    cls._data = json.load(f)
                print("Dades de localització carregades de la memòria cau.")
                return
            except Exception as e:
                print(f"Error llegint cau: {e}. Descarregant de nou...")

        print("Descarregant base de dades de municipis i codis postals...")
        try:
            # 1. Descarregar i processar noms de municipis
            print("Descarregant catàleg de municipis...")
            resp_munis = requests.get(URL_MUNICIPIOS)
            resp_munis.raise_for_status()
            
            id_to_name = {}
            csv_munis = io.StringIO(resp_munis.text)
            reader_munis = csv.DictReader(csv_munis)
            for row in reader_munis:
                # municipio_id ja ve com '01059' (string amb padding)
                mid = row.get('municipio_id')
                nombre = row.get('nombre')
                if mid and nombre:
                    id_to_name[mid] = nombre.strip()

            # 2. Descarregar i processar codis postals
            print("Descarregant codis postals...")
            resp_cps = requests.get(URL_CODIGOS_POSTALES)
            resp_cps.raise_for_status()
            
            csv_cps = io.StringIO(resp_cps.text)
            reader_cps = csv.DictReader(csv_cps)
            
            # Estructura: Comunitat -> Província -> Municipi -> [CPs]
            structured = {}
            count = 0
            
            for row in reader_cps:
                cp = row.get('codigo_postal')
                mid_raw = row.get('municipio_id')
                
                if not cp or not mid_raw:
                    continue
                
                # Normalitzar CP i ID de municipi
                cp = cp.zfill(5)
                mid = mid_raw.zfill(5)
                
                muni_name = id_to_name.get(mid)
                if not muni_name:
                    continue

                prov_code = cp[:2]
                if prov_code not in PROVINCE_DATA:
                    continue
                    
                prov_info = PROVINCE_DATA[prov_code]
                ccaa = prov_info['community']
                prov = prov_info['name']
                
                if ccaa not in structured:
                    structured[ccaa] = {}
                if prov not in structured[ccaa]:
                    structured[ccaa][prov] = {}
                if muni_name not in structured[ccaa][prov]:
                    structured[ccaa][prov][muni_name] = []
                
                if cp not in structured[ccaa][prov][muni_name]:
                    structured[ccaa][prov][muni_name].append(cp)
                count += 1
            
            cls._data = structured
            
            # Guardar a disc
            with open(CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(structured, f, ensure_ascii=False, indent=2)
                
            print(f"Base de dades actualitzada amb {count} registres.")
            
        except Exception as e:
            print(f"Error greu descarregant dades: {e}")
            # Fallback buit
            cls._data = {}

    @classmethod
    def get_communities(cls):
        if not cls._data: cls.load_data()
        return sorted(list(cls._data.keys()))

    @classmethod
    def get_provinces(cls, community=None):
        if not cls._data: cls.load_data()
        provinces = []
        
        # Handle list of communities
        if isinstance(community, list):
            for c in community:
                if c in cls._data:
                    provinces.extend(cls._data[c].keys())
        elif community and community in cls._data:
            provinces.extend(cls._data[community].keys())
        elif not community:
            for comm in cls._data.values():
                provinces.extend(comm.keys())
        return sorted(list(set(provinces)))

    @classmethod
    def get_municipios(cls, province=None, community=None, comarca=None):
        if not cls._data: cls.load_data()
        municipios = []
        
        # Helper to get munis from a specific province data
        def extract_munis(prov_data):
            return list(prov_data.keys())

        # 1. Gather all potential municipalities based on Province/Community
        if province:
            # Handle list of provinces
            if isinstance(province, list):
                for p in province:
                    # Find p in any community
                    for comm_data in cls._data.values():
                        if p in comm_data:
                            municipios.extend(extract_munis(comm_data[p]))
            else:
                # Single province
                if community and community in cls._data and province in cls._data[community]:
                    municipios.extend(extract_munis(cls._data[community][province]))
                else:
                    for comm_data in cls._data.values():
                        if province in comm_data:
                            municipios.extend(extract_munis(comm_data[province]))
        
        elif community:
            # Handle list of communities
            if isinstance(community, list):
                for c in community:
                    if c in cls._data:
                        for prov_data in cls._data[c].values():
                            municipios.extend(extract_munis(prov_data))
            elif community in cls._data:
                for prov_data in cls._data[community].values():
                    municipios.extend(extract_munis(prov_data))
        else:
            # All
            for comm_data in cls._data.values():
                for prov_data in comm_data.values():
                    municipios.extend(extract_munis(prov_data))
        
        # 2. Filter by Comarca (if provided and we have data)
        if comarca:
            cls.load_cat_data()
            # Handle list of comarques
            if isinstance(comarca, list):
                target_comarques = set(comarca)
                cat_munis = set(item['municipality'] for item in cls._cat_data if item.get('comarca') in target_comarques)
            else:
                cat_munis = set(item['municipality'] for item in cls._cat_data if item.get('comarca') == comarca)
            
            # Filter: keep only those that are in the comarca list
            municipios = [m for m in municipios if m in cat_munis]

        return sorted(list(set(municipios)))

    @classmethod
    def get_zips(cls, scope, value, extra_context=None):
        """
        Retorna llista de CPs.
        scope: 'community', 'provincia', 'municipi', 'zip', 'comarca'
        value: El nom (o llista de noms).
        extra_context: Diccionari amb info extra
        """
        if not cls._data: cls.load_data()
        zips = []
        
        # Ensure value is a list for uniform processing
        values = value if isinstance(value, list) else [value]
        
        if scope == 'zip':
            return [v.strip() for v in values]
            
        elif scope == 'community':
            for v in values:
                if v in cls._data:
                    for prov in cls._data[v].values():
                        for mun_zips in prov.values():
                            zips.extend(mun_zips)

        elif scope == 'provincia':
            for v in values:
                for comm in cls._data.values():
                    if v in comm:
                        for mun_zips in comm[v].values():
                            zips.extend(mun_zips)
        
        elif scope == 'comarca':
            # Get municipalities for these comarques
            cls.load_cat_data()
            target_comarques = set(values)
            target_munis = set(item['municipality'] for item in cls._cat_data if item.get('comarca') in target_comarques)
            
            logger.info(f"Cercant CPs per comarques: {values}. Municipis trobats: {len(target_munis)}")
            
            # Now find zips for these munis
            for comm_name, comm_data in cls._data.items():
                for prov_data in comm_data.values():
                    for muni_name, mun_zips in prov_data.items():
                        # Normalització bàsica per comparar noms (majúscules/minúscules)
                        if muni_name in target_munis:
                            zips.extend(mun_zips)
                        else:
                            # Intentar cerca parcial o normalitzada si no troba exacte
                            # Això és lent però pot ajudar si els noms difereixen lleugerament
                            pass

        elif scope == 'municipi':
            target_community = extra_context.get('community') if extra_context else None
            target_province = extra_context.get('province') if extra_context else None
            
            # Normalize to lists if they are strings
            if target_community and isinstance(target_community, str): target_community = [target_community]
            if target_province and isinstance(target_province, str): target_province = [target_province]
            
            logger.info(f"Cercant CPs per municipis: {values}. Filtres -> Comunitat: {target_community}, Província: {target_province}")

            for v in values:
                found_for_v = False
                for comm_name, comm_data in cls._data.items():
                    # Check if community matches (if filter provided)
                    if target_community and comm_name not in target_community: continue
                    
                    for prov_name, prov_data in comm_data.items():
                        # Check if province matches (if filter provided)
                        if target_province and prov_name not in target_province: continue
                        
                        if v in prov_data:
                            zips.extend(prov_data[v])
                            found_for_v = True
                
                if not found_for_v:
                    logger.warning(f"No s'han trobat CPs per al municipi '{v}' amb els filtres actuals.")
                        
        return list(set(zips))
