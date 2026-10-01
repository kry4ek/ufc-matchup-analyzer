"""Check PE architecture/import closure without relying on host developer DLLs."""
import argparse,json,struct
from pathlib import Path
SYSTEM={name+'.dll' for name in ('advapi32','bcrypt','cabinet','comctl32','comdlg32','crypt32','dwmapi','gdiplus','gdi32','imm32','iphlpapi','kernel32','msvcrt','msvcp_win','mswsock','netapi32','ntdll','ole32','oleaut32','powrprof','psapi','rpcrt4','secur32','shell32','shlwapi','ucrtbase','user32','userenv','version','winmm','winspool','ws2_32','wtsapi32','ncrypt','normaliz','propsys','rstrtmgr','setupapi','shcore','winhttp','wininet','vaultcli','cfgmgr32')}
SYSTEM.add('winspool.drv')  # Windows printing API used by the matching Tk DLL.

def imports(path):
    raw=path.read_bytes();pe=struct.unpack_from('<I',raw,0x3c)[0]
    assert raw[pe:pe+4]==b'PE\0\0',path.name
    machine,count,_,_,_,optional,_=struct.unpack_from('<HHIIIHH',raw,pe+4)
    assert machine==0x8664,(path.name,hex(machine))
    start=pe+24;assert struct.unpack_from('<H',raw,start)[0]==0x20b,path.name
    sections=[]
    for index in range(count):
        offset=start+optional+index*40
        size,rva,raw_size,raw_offset=struct.unpack_from('<IIII',raw,offset+8)
        sections.append((rva,max(size,raw_size),raw_offset))
    def position(rva):
        for address,size,offset in sections:
            if address<=rva<address+size:return offset+rva-address
        raise ValueError('Invalid import address in '+path.name)
    names=set()
    rva,size=struct.unpack_from('<II',raw,start+112+8)
    if rva:
        offset=position(rva)
        while any(raw[offset:offset+20]):
            name=position(struct.unpack_from('<I',raw,offset+12)[0]);names.add(raw[name:raw.index(b'\0',name)].decode('ascii').lower());offset+=20
    # Delay imports also need closure when optional paths are exercised.
    rva,size=struct.unpack_from('<II',raw,start+112+13*8)
    if rva:
        offset=position(rva)
        while any(raw[offset:offset+32]):
            flags,name_rva=struct.unpack_from('<II',raw,offset)
            if flags&1:
                name=position(name_rva);names.add(raw[name:raw.index(b'\0',name)].decode('ascii').lower())
            offset+=32
    return sorted(names),struct.unpack_from('<H',raw,start+68)[0]

def main():
    p=argparse.ArgumentParser();p.add_argument('--folder',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    files=[x for x in a.folder.rglob('*') if x.suffix.lower() in ('.exe','.dll','.pyd')]
    available={x.name.lower() for x in files};missing=[];rows=[]
    for path in files:
        names,subsystem=imports(path)
        unknown=[name for name in names if name not in available and name not in SYSTEM and not name.startswith(('api-ms-win-','ext-ms-win-'))]
        missing.extend(dict(file=path.relative_to(a.folder).as_posix(),dll=name) for name in unknown)
        rows.append(dict(file=path.relative_to(a.folder).as_posix(),imports=names,subsystem=subsystem))
    launcher=next(row for row in rows if row['file']=='UFC Matchup Analyzer.exe');assert launcher['subsystem']==2,'Launcher must use Windows subsystem'
    result=dict(status='FAIL' if missing else 'PASS',pe_files=len(rows),missing=missing,files=rows,scope='Static AMD64 PE and normal/delay import checks. Dynamic imports are covered by prediction/maintenance runs; clean OS verification remains separate.')
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(dict(status=result['status'],pe_files=len(rows),missing=missing),indent=2));return bool(missing)

if __name__=='__main__':raise SystemExit(main())
