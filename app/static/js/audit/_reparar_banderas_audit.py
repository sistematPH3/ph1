# coding: utf-8
# Reparacion byte-exacta de las 2 banderas corruptas + agregar a accesos.
# Usa Get-Content/Get-ChildItem del powershell? NO: usa Python puro byte-level.
import io, sys, os
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ====== PATH REAL: el que resolvio los reads (workdir OneDrive) ======
BASE = r'C:\Users\sures\OneDrive\Desktop\sistema_ph\ph1\app\templates'

# trans: A) movement_audit.html corrupto L26
f = os.path.join(BASE, r'logistics\movement_audit.html')
b = open(f, 'rb').read()

corrupto = u"{% include 'reports/{% set export_sin_fechas = True %}\n".encode('utf-8')
if corrupto in b:
    b = b.replace(corrupto, u"{% set export_sin_fechas = True %}\n".encode('utf-8'))
    open(f, 'wb').write(b)
    print(u'  [OK] movement_audit.html: literal corrupto -> bandera limpia')
else:
    print(u'  [FALLO] movement_audit.html: literal corrupto NO encontrado')

# trans: B) auditinventory.html corrupto L69
f = os.path.join(BASE, r'waste\auditinventory.html')
b = open(f, 'rb').read()
if corrupto in b:
    b = b.replace(corrupto, u"{% set export_sin_fechas = True %}\n".encode('utf-8'))
    open(f, 'wb').write(b)
    print(u'  [OK] auditinventory.html: literal corrupto -> bandera limpia')
else:
    print(u'  [FALLO] auditinventory.html: literal corrupto NO encontrado')

# C) login_audit.html (accesos): agregar bandera ANTES del include del toolbar
f = os.path.join(BASE, r'security\login_audit.html')
b = open(f, 'rb').read()
t = b.decode('utf-8')
punto = u"{% set export_base_url = url_for('audit_exports.descargar_accesos', _external=False) %}\n"
if punto in t:
    if u'export_sin_fechas = True' in t:
        print(u'  [ya] login_audit.html: ya tiene bandera')
    else:
        t = t.replace(punto, punto + u"    {% set export_sin_fechas = True %}\n")
        open(f, 'w', encoding='utf-8', newline='\n').write(t)
        print(u'  [OK] login_audit.html: bandera agregada antes del include')
else:
    print(u'  [FALLO] login_audit.html: literal de base_url NO encontrado')

print(u'')
print(u'== verificacion posterior ==')
for rel in (r'logistics\movement_audit.html', r'waste\auditinventory.html',
            r'security\login_audit.html'):
    p = os.path.join(BASE, rel)
    c = open(p, encoding='utf-8').read()
    band = (u'export_sin_fechas = True' in c)
    inc = (u"include 'reports/audit_export_toolbar.html'" in c)
    roto = (u"include 'reports/{% set" in c)
    u'  {0,-34} bandera={1} include_limpio={2} leftover_corrupto={3}'.format(rel, band, inc, roto)
