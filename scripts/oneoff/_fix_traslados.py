# coding: utf-8
import io, os, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

BASE = r'C:\Users\sures\OneDrive\Desktop\sistema_ph\ph1\app\templates'
P = os.path.join(BASE, r'logistics\movement_audit.html')

def reparar(s):
    out = []
    buf = bytearray()
    def aplanar():
        if not buf:
            return
        try:
            out.append(bytes(buf).decode('utf-8'))
        except UnicodeDecodeError:
            out.append(u''.join(chr(x) for x in buf))
        del buf[:]
    for ch in s:
        if ord(ch) <= 0xFF:
            buf.append(ord(ch))
        else:
            aplanar()
            out.append(ch)
    aplanar()
    return u''.join(out)

b = open(P, 'rb').read()
bom = b.startswith(b'\xef\xbb\xbf')
t = (b[3:] if bom else b).decode('utf-8')
pre = t.count(u'\u00c3') + t.count(u'\u00c2')
t2 = reparar(t)
t3 = t2.replace(u'Auditor\u00eda Forense', u'Auditor\u00eda de Traslados')
t3 = t3.replace(u'Forense', u'de Traslados')
nuevo = (b'\xef\xbb\xbf' if bom else b'') + t3.encode('utf-8')
open(P, 'wb').write(nuevo)
print(u'BOM={0} mojibake_previo={1} -> reparado y renombrado a Traslados'.format(bom, pre))
