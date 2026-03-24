"""Test the bot with all fixes applied."""
import logging
import sys
import glob
import re
import os

# Filter out Selenium/WDM noise
class BotFilter(logging.Filter):
    def filter(self, record):
        skip = ['selenium', 'urllib3', 'webdriver_manager', 'WDM']
        return not any(s in record.name for s in skip)

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s', stream=sys.stdout)
for h in logging.root.handlers:
    h.addFilter(BotFilter())

# Clean old debug files
for f in glob.glob("debug_*.html"):
    os.remove(f)

from src.sepe_bot import SepeBot

print("=== TESTING SEPE BOT (CP 08018, tramite 158) ===\n")
bot = SepeBot(headless=True)
try:
    result = bot.check_appointment('08018', '39928988E', ['person'], tramite_id='158')
    print(f'\n=== RESULT: {result} ===\n')
finally:
    bot.close()

# Analyze debug files
debug_files = glob.glob("debug_*.html")
print(f"Debug files created: {debug_files}")

for f in debug_files:
    with open(f, 'r', encoding='utf-8') as fh:
        content = fh.read()
    print(f"\n--- {f} ({len(content)} chars) ---")
    
    keywords = ['primer buit', 'primer hueco', 'oficina', 'disponible', 
                'no podemos', 'no podem', 'seleccione', 'seleccioneu', 
                'canal', 'error', 'hueco']
    for kw in keywords:
        matches = re.findall(r'.{0,50}' + re.escape(kw) + r'.{0,50}', content.lower())
        if matches:
            print(f'  FOUND "{kw}": {len(matches)} matches')
            for m in matches[:3]:
                print(f'    ...{m.strip()}...')

print("\n=== DONE ===")
