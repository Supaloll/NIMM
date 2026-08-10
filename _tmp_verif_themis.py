# -*- coding: utf-8 -*-
import json
import sys
sys.stdout.reconfigure(encoding='utf-8')

with open('g:/NIMM/modules/masks/themis.json', 'r', encoding='utf-8') as f:
    d = json.load(f)
p = d['system_prompt']

sure = "s" + chr(251) + "r"
agrave = chr(224)

print("JSON OK, id=" + d['id'])
print("regle1_etendue:", "pas " + sure + " " + agrave + " 100%" in p)
print("citation_inventee:", "citation qui sonne juste" in p)
print("emoji_repr:", repr(d['emoji']))
print("emoji_u2696:", chr(9884) in d['emoji'])
print("emoji_longueur:", len(d['emoji']))
print("codes_emoji:", [hex(ord(c)) for c in d['emoji']])
