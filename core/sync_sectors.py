import csv
import json
import logging
import sqlite3
import urllib.request
import urllib.error
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

# Setup basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

PRIMARY_SECTORS = [
    'AUTOMOBILE AND AUTO COMPONENTS', 'CAPITAL GOODS', 'CHEMICALS', 'CONSTRUCTION',
    'CONSTRUCTION MATERIALS', 'CONSUMER DURABLES', 'CONSUMER SERVICES', 'DIVERSIFIED',
    'FAST MOVING CONSUMER GOODS', 'FINANCIAL SERVICES', 'FOREST MATERIALS', 'HEALTHCARE',
    'INFORMATION TECHNOLOGY', 'MEDIA ENTERTAINMENT & PUBLICATION', 'METALS & MINING',
    'OIL GAS & CONSUMABLE FUELS', 'POWER', 'REALTY', 'SERVICES',
    'TELECOMMUNICATION', 'TEXTILES', 'UTILITIES'
]

INDUSTRY_TO_SECTOR = {
    'Automobile and Auto Components': 'AUTOMOBILE AND AUTO COMPONENTS',
    'Financial Services': 'FINANCIAL SERVICES',
    'Capital Goods': 'CAPITAL GOODS',
    'Chemicals': 'CHEMICALS',
    'Construction': 'CONSTRUCTION',
    'Construction Materials': 'CONSTRUCTION MATERIALS',
    'Realty': 'REALTY',
    'Consumer Durables': 'CONSUMER DURABLES',
    'Consumer Services': 'CONSUMER SERVICES',
    'Textiles': 'TEXTILES',
    'Fast Moving Consumer Goods': 'FAST MOVING CONSUMER GOODS',
    'Healthcare': 'HEALTHCARE',
    'Information Technology': 'INFORMATION TECHNOLOGY',
    'Metals & Mining': 'METALS & MINING',
    'Oil Gas & Consumable Fuels': 'OIL GAS & CONSUMABLE FUELS',
    'Power': 'POWER',
    'Telecommunication': 'TELECOMMUNICATION',
    'Media Entertainment & Publication': 'MEDIA ENTERTAINMENT & PUBLICATION',
    'Utilities': 'UTILITIES',
    'Services': 'SERVICES',
    'Diversified': 'DIVERSIFIED',
    'Forest Materials': 'FOREST MATERIALS',
}

EXPLICIT_OVERRIDES = {
    'CUPID': 'HEALTHCARE', 'STLTECH': 'TELECOMMUNICATION', 'MTARTECH': 'CAPITAL GOODS',
    'ATHERENERG': 'AUTOMOBILE AND AUTO COMPONENTS', 'SANSERA': 'AUTOMOBILE AND AUTO COMPONENTS', 'HFCL': 'TELECOMMUNICATION',
    'WELCORP': 'METALS & MINING', 'LAURUSLABS': 'HEALTHCARE', 'CPPLUS': 'CAPITAL GOODS',
    'RRKABEL': 'CAPITAL GOODS', 'TDPOWERSYS': 'CAPITAL GOODS', 'SKYGOLD': 'CONSUMER DURABLES',
    'AETHER': 'CHEMICALS', 'FEDERALBNK': 'FINANCIAL SERVICES', 'AVALON': 'CAPITAL GOODS',
    'GRWRHITECH': 'CHEMICALS', 'MCX': 'FINANCIAL SERVICES', 'SHILPAMED': 'HEALTHCARE',
    'DIACABS': 'CAPITAL GOODS', 'ACUTAAS': 'CHEMICALS', 'DIXON': 'CONSUMER DURABLES',
    'TRENT': 'CONSUMER SERVICES', 'POLYCAB': 'CAPITAL GOODS', 'NAUKRI': 'CONSUMER SERVICES',
    'LTTS': 'INFORMATION TECHNOLOGY', 'BHARTI': 'TELECOMMUNICATION', 'BEL': 'CAPITAL GOODS',
    'HAL': 'CAPITAL GOODS', 'SUNPHAR': 'HEALTHCARE', 'APOLLOH': 'HEALTHCARE',
    'MAXHEAL': 'HEALTHCARE', 'CHOLAF': 'FINANCIAL SERVICES', 'TVSMOTO': 'AUTOMOBILE AND AUTO COMPONENTS',
    'BAJAJ_A': 'AUTOMOBILE AND AUTO COMPONENTS', 'HEROMOT': 'AUTOMOBILE AND AUTO COMPONENTS', 'EICHERM': 'AUTOMOBILE AND AUTO COMPONENTS',
    'RELIANCE': 'OIL GAS & CONSUMABLE FUELS', 'TCS': 'INFORMATION TECHNOLOGY', 'INFY': 'INFORMATION TECHNOLOGY',
    'HDFCBANK': 'FINANCIAL SERVICES', 'ICICIBANK': 'FINANCIAL SERVICES', 'SBIN': 'FINANCIAL SERVICES',
    'ITC': 'FAST MOVING CONSUMER GOODS', 'HINDUNILVR': 'FAST MOVING CONSUMER GOODS',
    'LTI': 'INFORMATION TECHNOLOGY', 'LTIM': 'INFORMATION TECHNOLOGY', 'LTIMINDTRE': 'INFORMATION TECHNOLOGY',
    'ADANIENT': 'METALS & MINING', 'ADANIPORTS': 'SERVICES',
    'ADANIGREEN': 'POWER', 'ADANIPOWER': 'POWER',
    'ATGL': 'OIL GAS & CONSUMABLE FUELS', 'AWL': 'FAST MOVING CONSUMER GOODS',
    'TATAMOTORS': 'AUTOMOBILE AND AUTO COMPONENTS', 'M&M': 'AUTOMOBILE AND AUTO COMPONENTS', 'MARUTI': 'AUTOMOBILE AND AUTO COMPONENTS',
    'BAJAJ-AUTO': 'AUTOMOBILE AND AUTO COMPONENTS', 'EICHERMOT': 'AUTOMOBILE AND AUTO COMPONENTS', 'HEROMOTOCO': 'AUTOMOBILE AND AUTO COMPONENTS',
    'TVSMOTOR': 'AUTOMOBILE AND AUTO COMPONENTS', 'BHARATFORG': 'AUTOMOBILE AND AUTO COMPONENTS', 'SONACOMS': 'AUTOMOBILE AND AUTO COMPONENTS',
    'MOTHERSON': 'AUTOMOBILE AND AUTO COMPONENTS', 'BOSCHLTD': 'AUTOMOBILE AND AUTO COMPONENTS', 'MRF': 'AUTOMOBILE AND AUTO COMPONENTS',
    'APOLLOTYRE': 'AUTOMOBILE AND AUTO COMPONENTS', 'BALKRISIND': 'AUTOMOBILE AND AUTO COMPONENTS', 'CEAT': 'AUTOMOBILE AND AUTO COMPONENTS',
    'EXIDEIND': 'AUTOMOBILE AND AUTO COMPONENTS', 'AMARAJABAT': 'AUTOMOBILE AND AUTO COMPONENTS', 'ARE&M': 'AUTOMOBILE AND AUTO COMPONENTS',
    'UNOMINDA': 'AUTOMOBILE AND AUTO COMPONENTS', 'CRAFTSMAN': 'AUTOMOBILE AND AUTO COMPONENTS', 'ENDURANCE': 'AUTOMOBILE AND AUTO COMPONENTS',
    'SUNPHARMA': 'HEALTHCARE', 'DRREDDY': 'HEALTHCARE', 'DIVISLAB': 'HEALTHCARE',
    'CIPLA': 'HEALTHCARE', 'LUPIN': 'HEALTHCARE', 'AUROPHARMA': 'HEALTHCARE',
    'TORNTPHARM': 'HEALTHCARE', 'ALKEM': 'HEALTHCARE', 'MANKIND': 'HEALTHCARE',
    'ZYDUSLIFE': 'HEALTHCARE', 'BIOCON': 'HEALTHCARE', 'GLENMARK': 'HEALTHCARE',
    'IPCALAB': 'HEALTHCARE', 'AJANTPHARM': 'HEALTHCARE', 'NATCOPHARM': 'HEALTHCARE',
    'GRANULES': 'HEALTHCARE', 'JBCHEPHARM': 'HEALTHCARE', 'GLAND': 'HEALTHCARE',
    'SYNGENE': 'HEALTHCARE', 'APOLLOHOSP': 'HEALTHCARE', 'MAXHEALTH': 'HEALTHCARE',
    'FORTIS': 'HEALTHCARE', 'MEDANTA': 'HEALTHCARE', 'NH': 'HEALTHCARE',
    'METROPOLIS': 'HEALTHCARE', 'LALPATHLAB': 'HEALTHCARE',
    'WIPRO': 'INFORMATION TECHNOLOGY', 'HCLTECH': 'INFORMATION TECHNOLOGY', 'TECHM': 'INFORMATION TECHNOLOGY',
    'PERSISTENT': 'INFORMATION TECHNOLOGY', 'COFORGE': 'INFORMATION TECHNOLOGY', 'MPHASIS': 'INFORMATION TECHNOLOGY',
    'TATATECH': 'INFORMATION TECHNOLOGY', 'TATAELXSI': 'INFORMATION TECHNOLOGY', 'KPITTECH': 'INFORMATION TECHNOLOGY',
    'CYIENT': 'INFORMATION TECHNOLOGY', 'BIRLASOFT': 'INFORMATION TECHNOLOGY', 'ZENSARTECH': 'INFORMATION TECHNOLOGY',
    'SONATSOFTW': 'INFORMATION TECHNOLOGY', 'TANLA': 'INFORMATION TECHNOLOGY', 'NETWEB': 'INFORMATION TECHNOLOGY',
    'NEWGEN': 'INFORMATION TECHNOLOGY', 'AURIONPRO': 'INFORMATION TECHNOLOGY', 'INTELLECT': 'INFORMATION TECHNOLOGY',
    'HAPPSTMNDS': 'INFORMATION TECHNOLOGY', 'OFSS': 'INFORMATION TECHNOLOGY',
    'KOTAKBANK': 'FINANCIAL SERVICES', 'AXISBANK': 'FINANCIAL SERVICES',
    'INDUSINDBK': 'FINANCIAL SERVICES', 'BANKBARODA': 'FINANCIAL SERVICES',
    'PNB': 'FINANCIAL SERVICES', 'CANBK': 'FINANCIAL SERVICES', 'UNIONBANK': 'FINANCIAL SERVICES',
    'IDFCFIRSTB': 'FINANCIAL SERVICES', 'BANDHANBNK': 'FINANCIAL SERVICES',
    'BAJFINANCE': 'FINANCIAL SERVICES', 'BAJAJFINSV': 'FINANCIAL SERVICES',
    'CHOLAFIN': 'FINANCIAL SERVICES', 'SHRIRAMFIN': 'FINANCIAL SERVICES',
    'MUTHOOTFIN': 'FINANCIAL SERVICES', 'MANAPPURAM': 'FINANCIAL SERVICES',
    'SUNDARMFIN': 'FINANCIAL SERVICES', 'LTF': 'FINANCIAL SERVICES',
    'POONAWALLA': 'FINANCIAL SERVICES', 'LICI': 'FINANCIAL SERVICES',
    'HDFCLIFE': 'FINANCIAL SERVICES', 'SBILIFE': 'FINANCIAL SERVICES',
    'ICICIPRULI': 'FINANCIAL SERVICES', 'ICICIGI': 'FINANCIAL SERVICES',
    'BSE': 'FINANCIAL SERVICES', 'CDSL': 'FINANCIAL SERVICES', 'CAMSLTD': 'FINANCIAL SERVICES',
    'ANGELONE': 'FINANCIAL SERVICES', '360ONE': 'FINANCIAL SERVICES',
    'MOTILALOFS': 'FINANCIAL SERVICES', 'NAM-INDIA': 'FINANCIAL SERVICES',
    'HDFCAMC': 'FINANCIAL SERVICES', 'UTIAMC': 'FINANCIAL SERVICES',
    'JIOFIN': 'FINANCIAL SERVICES', 'CRISIL': 'FINANCIAL SERVICES',
    'ICRA': 'FINANCIAL SERVICES', 'CAREERP': 'FINANCIAL SERVICES',
    'LT': 'CAPITAL GOODS', 'SIEMENS': 'CAPITAL GOODS', 'ABB': 'CAPITAL GOODS',
    'CUMMINSIND': 'CAPITAL GOODS', 'BHEL': 'CAPITAL GOODS',
    'MAZDOCK': 'CAPITAL GOODS', 'COCHINSHIP': 'CAPITAL GOODS',
    'GRSE': 'CAPITAL GOODS', 'BEML': 'CAPITAL GOODS',
    'DATAPATTNS': 'CAPITAL GOODS', 'KAYNES': 'CAPITAL GOODS',
    'SYRMA': 'CAPITAL GOODS', 'ASTRAL': 'CAPITAL GOODS',
    'KEI': 'CAPITAL GOODS', 'HAVELLS': 'CAPITAL GOODS',
    'FINCABLES': 'CAPITAL GOODS', 'THERMAX': 'CAPITAL GOODS',
    'AIAENG': 'CAPITAL GOODS', 'TIMKEN': 'CAPITAL GOODS',
    'SKFINDIA': 'CAPITAL GOODS', 'SCHAEFFLER': 'CAPITAL GOODS',
    'SUZLON': 'CAPITAL GOODS', 'INOXWIND': 'CAPITAL GOODS',
    'CGPOWER': 'CAPITAL GOODS', 'SOLARINDS': 'CAPITAL GOODS', 'ACE': 'CAPITAL GOODS',
    'VOLTAS': 'CONSUMER DURABLES', 'BLUESTARCO': 'CONSUMER DURABLES',
    'TITAN': 'CONSUMER DURABLES', 'KALYANKJIL': 'CONSUMER DURABLES',
    'SENCO': 'CONSUMER DURABLES', 'DMART': 'CONSUMER SERVICES',
    'PAGEIND': 'CONSUMER DURABLES', 'MANYAVAR': 'CONSUMER DURABLES',
    'RAYMOND': 'TEXTILES', 'CAMPUS': 'CONSUMER DURABLES',
    'METROBRAND': 'CONSUMER DURABLES', 'BATAINDIA': 'CONSUMER DURABLES',
    'RELAXO': 'CONSUMER DURABLES', 'WHIRLPOOL': 'CONSUMER DURABLES',
    'CROMPTON': 'CONSUMER DURABLES', 'VGUARD': 'CONSUMER DURABLES',
    'AMBER': 'CONSUMER DURABLES', 'CELLO': 'CONSUMER DURABLES',
    'VIPIND': 'CONSUMER DURABLES', 'ETHOSLTD': 'CONSUMER DURABLES',
    'INDHOTEL': 'CONSUMER SERVICES', 'EIHOTEL': 'CONSUMER SERVICES',
    'CHALET': 'CONSUMER SERVICES', 'LEMONTREE': 'CONSUMER SERVICES',
    'TATASTEEL': 'METALS & MINING', 'JSWSTEEL': 'METALS & MINING',
    'JINDALSTEL': 'METALS & MINING', 'SAIL': 'METALS & MINING',
    'NMDC': 'METALS & MINING', 'COALINDIA': 'METALS & MINING',
    'HINDALCO': 'METALS & MINING', 'NATIONALUM': 'METALS & MINING',
    'VEDL': 'METALS & MINING', 'HINDZINC': 'METALS & MINING',
    'JSL': 'METALS & MINING', 'RATNAMANI': 'METALS & MINING', 'APLAPOLLO': 'METALS & MINING',
    'MAHLOG': 'SERVICES', 'CONCOR': 'SERVICES',
    'DELHIVERY': 'SERVICES', 'BHARTIARTL': 'TELECOMMUNICATION',
    'INDUSTOWER': 'TELECOMMUNICATION', 'TATACOMM': 'TELECOMMUNICATION',
    'IDEA': 'TELECOMMUNICATION', 'TEJASNET': 'TELECOMMUNICATION',
    'RAILTEL': 'TELECOMMUNICATION', 'ZEEL': 'MEDIA ENTERTAINMENT & PUBLICATION',
    'SUNTV': 'MEDIA ENTERTAINMENT & PUBLICATION', 'PVRINOX': 'MEDIA ENTERTAINMENT & PUBLICATION',
    'SAREGAMA': 'MEDIA ENTERTAINMENT & PUBLICATION', 'NTPC': 'POWER',
    'POWERGRID': 'POWER', 'TATAPOWER': 'POWER',
    'JSWENERGY': 'POWER', 'TORNTPOWER': 'POWER',
    'NHPC': 'POWER', 'SJVN': 'POWER',
    'CESC': 'POWER',
    'DLF': 'REALTY', 'LODHA': 'REALTY', 'MACROTECH': 'REALTY',
    'GODREJPROP': 'REALTY', 'OBEROIRLTY': 'REALTY',
    'PRESTIGE': 'REALTY', 'BRIGADE': 'REALTY',
    'SOBHA': 'REALTY', 'PHOENIXLTD': 'REALTY',
    'SUNTECK': 'REALTY', 'ULTRACEMCO': 'CONSTRUCTION MATERIALS',
    'AMBUJACEM': 'CONSTRUCTION MATERIALS', 'ACC': 'CONSTRUCTION MATERIALS',
    'DALBHARAT': 'CONSTRUCTION MATERIALS', 'SHREECEM': 'CONSTRUCTION MATERIALS',
    'RAMCOCEM': 'CONSTRUCTION MATERIALS', 'JKCEMENT': 'CONSTRUCTION MATERIALS',
    'PIDILITIND': 'CHEMICALS', 'SRF': 'CHEMICALS',
    'AARTIIND': 'CHEMICALS', 'FLUOROCHEM': 'CHEMICALS',
    'DEEPAKNTR': 'CHEMICALS', 'TATACHEM': 'CHEMICALS',
    'ATUL': 'CHEMICALS', 'VINATIORGA': 'CHEMICALS',
    'CLEAN': 'CHEMICALS', 'NAVINFLUOR': 'CHEMICALS',
    'PIIND': 'CHEMICALS', 'UPL': 'CHEMICALS',
    'COROMANDEL': 'CHEMICALS', 'CHAMBLFERT': 'CHEMICALS',
    'GNFC': 'CHEMICALS', 'GSFC': 'CHEMICALS', 'SUMICHEM': 'CHEMICALS',
    'ONGC': 'OIL GAS & CONSUMABLE FUELS', 'OIL': 'OIL GAS & CONSUMABLE FUELS', 'BPCL': 'OIL GAS & CONSUMABLE FUELS',
    'IOC': 'OIL GAS & CONSUMABLE FUELS', 'HINDPETRO': 'OIL GAS & CONSUMABLE FUELS', 'GAIL': 'OIL GAS & CONSUMABLE FUELS',
    'PETRONET': 'OIL GAS & CONSUMABLE FUELS', 'IGL': 'OIL GAS & CONSUMABLE FUELS', 'MGL': 'OIL GAS & CONSUMABLE FUELS',
    'GUJGASLTD': 'OIL GAS & CONSUMABLE FUELS', 'CASTROLIND': 'OIL GAS & CONSUMABLE FUELS',
    'MRPL': 'OIL GAS & CONSUMABLE FUELS', 'CHENNPETRO': 'OIL GAS & CONSUMABLE FUELS',
    'NESTLEIND': 'FAST MOVING CONSUMER GOODS', 'BRITANNIA': 'FAST MOVING CONSUMER GOODS',
    'DABUR': 'FAST MOVING CONSUMER GOODS', 'MARICO': 'FAST MOVING CONSUMER GOODS',
    'GODREJCP': 'FAST MOVING CONSUMER GOODS', 'COLPAL': 'FAST MOVING CONSUMER GOODS',
    'VBL': 'FAST MOVING CONSUMER GOODS', 'TATACONSUM': 'FAST MOVING CONSUMER GOODS',
    'EMAMILTD': 'FAST MOVING CONSUMER GOODS', 'BIKAJI': 'FAST MOVING CONSUMER GOODS',
    'BECTORFOOD': 'FAST MOVING CONSUMER GOODS', 'JYOTHYLAB': 'FAST MOVING CONSUMER GOODS',
    'RADICO': 'FAST MOVING CONSUMER GOODS', 'UNITDSPR': 'FAST MOVING CONSUMER GOODS', 'UBL': 'FAST MOVING CONSUMER GOODS',
}

def get_session():
    """Get HTTP session, trying curl_cffi first with requests fallback."""
    try:
        from curl_cffi import requests
        return requests.Session(impersonate="chrome")
    except ImportError:
        import requests
        return requests.Session()

def classify_symbol(symbol: str, company_name: str = '') -> str:
    """Fallback classification for unknown industries based on keywords using 22 AMFI macro industries."""
    text = f"{symbol} {company_name}".upper()
    
    if any(k in text for k in ['BANK', 'FINANCE', 'FINANCIAL', 'INSURANCE', 'CAPITAL', 'WEALTH', 'ASSET', 'MUTUAL']):
        return 'FINANCIAL SERVICES'
    if any(k in text for k in ['PHARMA', 'HEALTH', 'HOSPITAL', 'LIFE', 'BIO', 'MED', 'DRUGS']):
        return 'HEALTHCARE'
    if any(k in text for k in ['TECH', 'INFOTECH', 'SOFTWARE', 'IT ', 'COMPUTERS']):
        return 'INFORMATION TECHNOLOGY'
    if any(k in text for k in ['CHEM', 'FERTILIZER', 'POLYMER', 'PLASTIC']):
        return 'CHEMICALS'
    if any(k in text for k in ['MOTOR', 'AUTO', 'TYRE', 'WHEEL']):
        return 'AUTOMOBILE AND AUTO COMPONENTS'
    if any(k in text for k in ['STEEL', 'IRON', 'MINING', 'ALUMINIUM', 'METAL']):
        return 'METALS & MINING'
    if any(k in text for k in ['OIL', 'PETRO', 'GAS', 'ENERGY', 'FUEL']):
        return 'OIL GAS & CONSUMABLE FUELS'
    if any(k in text for k in ['FOOD', 'BEVERAGE', 'AGRO', 'DAIRY', 'FMCG']):
        return 'FAST MOVING CONSUMER GOODS'
    if any(k in text for k in ['REALTY', 'REAL ESTATE', 'ESTATE', 'HOUSING']):
        return 'REALTY'
    if any(k in text for k in ['CEMENT', 'CONSTRUCTION MATERIAL']):
        return 'CONSTRUCTION MATERIALS'
    if any(k in text for k in ['INFRA', 'CONSTRUCTION', 'PROJECT']):
        return 'CONSTRUCTION'
    if any(k in text for k in ['JEWEL', 'FOOTWEAR', 'FASHION', 'DURABLE', 'APPLIANCE']):
        return 'CONSUMER DURABLES'
    if any(k in text for k in ['HOTEL', 'RETAIL', 'REST', 'TRAVEL', 'SERVICE']):
        return 'CONSUMER SERVICES'
    if any(k in text for k in ['TELECOM', 'COMMUNICATION', 'FIBER', 'OPTIC']):
        return 'TELECOMMUNICATION'
    if any(k in text for k in ['MEDIA', 'ENTERTAINMENT', 'BROADCAST', 'FILM', 'MUSIC', 'PUBLICATION']):
        return 'MEDIA ENTERTAINMENT & PUBLICATION'
    if any(k in text for k in ['POWER', 'ELECTRIC', 'SOLAR', 'WIND', 'GRID', 'THERMAL']):
        return 'POWER'
    if any(k in text for k in ['UTILITY', 'WATER', 'WASTE']):
        return 'UTILITIES'
    if any(k in text for k in ['TEXTILE', 'YARN', 'GARMENT']):
        return 'TEXTILES'
    if any(k in text for k in ['PAPER', 'FOREST', 'WOOD']):
        return 'FOREST MATERIALS'
        
    return 'CAPITAL GOODS' # Default fallback

def get_symbol_sector(symbol: str) -> str:
    """Looks up official AMFI sector taxonomy for a symbol, with fallback."""
    if not symbol:
        return 'CAPITAL GOODS'
    clean_sym = str(symbol).strip().upper()
    try:
        from .data_engine import get_base_dir
        base_dir = get_base_dir()
    except Exception:
        base_dir = Path(__file__).resolve().parent.parent
    map_path = Path(base_dir) / "data" / "symbol_sector_map.json"
    if map_path.exists():
        try:
            with open(map_path, "r", encoding="utf-8") as f:
                sec_map = json.load(f)
            if clean_sym in sec_map:
                return sec_map[clean_sym]
        except Exception:
            pass
    if clean_sym in EXPLICIT_OVERRIDES:
        return EXPLICIT_OVERRIDES[clean_sym]
    return classify_symbol(clean_sym)

def sync_nse_sectors(base_dir: Optional[Path] = None) -> Dict[str, str]:
    """
    Downloads NSE industry data, builds symbol->sector mapping, 
    merges with DB universe, and exports to JSON.
    """
    if base_dir is None:
        from .data_engine import get_base_dir
        base_dir = get_base_dir()
    else:
        base_dir = Path(base_dir)
        
    raw_dir = base_dir / 'data' / 'raw_reference'
    raw_dir.mkdir(parents=True, exist_ok=True)
    
    files_to_sync = [
        ("ind_niftytotalmarket_list.csv", "https://www.niftyindices.com/IndexConstituent/ind_niftytotalmarket_list.csv"),
        ("ind_nifty500list.csv", "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"),
    ]
    
    session = get_session()
    for fname, url in files_to_sync:
        csv_path = raw_dir / fname
        logger.info(f"Downloading NSE Index list: {fname} from {url}")
        try:
            response = session.get(url, timeout=15)
            response.raise_for_status()
            csv_path.write_bytes(response.content)
            logger.info(f"Successfully downloaded {fname} ({len(response.content):,} bytes)")
        except Exception as e:
            logger.warning(f"Session download failed for {fname} ({e}). Trying urllib fallback...")
            try:
                # Enforce bounded timeout and memory allocation limit (OWASP A05 / CWE-400)
                max_bytes = 10 * 1024 * 1024
                with urllib.request.urlopen(req, timeout=15) as response:
                    csv_path.write_bytes(response.read(max_bytes))
                logger.info(f"Fallback download succeeded for {fname}")
            except Exception as e_url:
                logger.error(f"Fallback download failed for {fname}: {e_url}")
                if not csv_path.exists():
                    logger.warning(f"No cached version of {fname} available.")

    # Parse downloaded NSE mappings (Total Market + Nifty 500)
    nse_map = {}
    for fname, _ in files_to_sync:
        fpath = raw_dir / fname
        if not fpath.exists():
            continue
        with open(fpath, 'r', encoding='utf-8', errors='ignore') as f:
            reader = csv.DictReader(f)
            for row in reader:
                symbol = row.get('Symbol', '').strip()
                industry = row.get('Industry', '').strip()
                company = row.get('Company Name', '').strip()
                if not symbol:
                    continue
                if industry in INDUSTRY_TO_SECTOR:
                    nse_map[symbol] = INDUSTRY_TO_SECTOR[industry]
                elif symbol not in nse_map:
                    nse_map[symbol] = classify_symbol(symbol, company)

    # Get Universe symbols
    logger.info("Fetching universe symbols from database...")
    universe_symbols = []
    try:
        from .data_engine import get_connection
        conn = get_connection(read_only=True)
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT symbol FROM prices ORDER BY symbol;')
        universe_symbols = [row[0] for row in cursor.fetchall()]
    except Exception as e:
        logger.warning(f"Could not load universe from db: {e}")
        # If DB query fails for any reason, at least export what we have + overrides
        universe_symbols = list(set(list(nse_map.keys()) + list(EXPLICIT_OVERRIDES.keys())))
        
    logger.info(f"Loaded {len(universe_symbols)} symbols from universe.")

    # Build final map
    final_map = {}
    sector_counts = {s: 0 for s in PRIMARY_SECTORS}
    
    legacy_to_22 = {
        'AUTO': 'AUTOMOBILE AND AUTO COMPONENTS', 'FINSERV': 'FINANCIAL SERVICES',
        'CAPGOODS': 'CAPITAL GOODS', 'CHEMICALS': 'CHEMICALS', 'REALTY': 'REALTY',
        'CONSDUR': 'CONSUMER DURABLES', 'FMCG': 'FAST MOVING CONSUMER GOODS',
        'PHARMA': 'HEALTHCARE', 'IT': 'INFORMATION TECHNOLOGY', 'METALS': 'METALS & MINING',
        'ENERGY': 'OIL GAS & CONSUMABLE FUELS', 'INFRA_MEDIA': 'SERVICES',
    }
    for symbol in universe_symbols:
        if symbol in nse_map:
            sector = nse_map[symbol]
        elif symbol in EXPLICIT_OVERRIDES:
            ov = EXPLICIT_OVERRIDES[symbol]
            sector = legacy_to_22.get(ov, ov)
        else:
            sector = classify_symbol(symbol)
            
        final_map[symbol] = sector
        if sector in sector_counts:
            sector_counts[sector] += 1
        else:
            sector_counts[sector] = 1

    # Export to JSON
    json_path = base_dir / 'data' / 'symbol_sector_map.json'
    json_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(final_map, f, indent=2, sort_keys=True)
        
    logger.info(f"Successfully mapped {len(final_map)} symbols to sectors.")
    logger.info("Sector Distribution:")
    for sector, count in sorted(sector_counts.items()):
        logger.info(f"  {sector}: {count}")
        
    return final_map

if __name__ == '__main__':
    sync_nse_sectors()
