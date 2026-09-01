# -*- coding: utf-8 -*-
import sys, json
sys.stdout.reconfigure(encoding='utf-8')

path = r'g:\NIMM\modules\masks\mlle_liam.json'

with open(path, 'r', encoding='utf-8') as f:
    raw = f.read()

# Normalise les fins de ligne pour la manipulation (CRLF possible)
content = raw.replace('\r\n', '\n').replace('\r', '\n')
if content.startswith('\ufeff'):
    content = content[1:]

marker = '{"personnage":'
count = content.count(marker)
if count != 1:
    print('ERR: occurrences du marqueur =', count)
    sys.exit(1)

idx = content.find(marker)
prefix = content[:idx]              # se termine par '  "ghost": true,\n'
inner_text = content[idx:].rstrip() # commence par '{"personnage":...' et se termine par '}}'

if not inner_text.endswith('}'):
    print('ERR: la queue ne se termine pas par }')
    sys.exit(1)
inner_text = inner_text[:-1]        # retire le '}' de fermeture externe -> objet interne seul

prefix = prefix.rstrip()
if prefix.endswith(','):
    prefix = prefix[:-1]            # retire la virgule pendante apres 'ghost'

outer = json.loads(prefix + '}')
inner = json.loads(inner_text)

nl = chr(10)
prompt = (
    'Tu es ' + inner['personnage'] + '. ' + inner['statut'] + '.' + nl + nl +
    'PHYSIQUE : ' + inner['physique'] + nl +
    'MISE EN SCENE : ' + inner['mise_en_scene'] + nl +
    'REGISTRE : ' + inner['registre'] + nl +
    'TON : ' + inner['ton'] + nl +
    'PRINCIPE : ' + inner['principe'] + nl +
    "GESTION DE L'EXPLICITE : " + inner['gestion_explicite'] + nl +
    'SIGNATURE : ' + inner['signature'] + nl +
    'REGLES : ' + inner['regles']
)

outer['system_prompt'] = prompt

out = json.dumps(outer, ensure_ascii=False, indent=2) + nl
with open(path, 'w', encoding='utf-8') as f:
    f.write(out)

# Relecture et validation
with open(path, 'r', encoding='utf-8') as f:
    check = json.load(f)

if check['system_prompt'] != prompt:
    print('ERR: system_prompt recrit different de l attente')
    sys.exit(1)
if check['emoji'] != '\U0001f48b':
    print('ERR: emoji altere')
    sys.exit(1)
if 'sc\u00e8ne' not in check['system_prompt']:
    print('ERR: accent altere')
    sys.exit(1)

print('OK: json valide, cles:', list(check.keys()))
print('OK: emoji intact (💋) et accents presents')
print('--- system_prompt ---')
print(check['system_prompt'])
print('--- fin ---')
