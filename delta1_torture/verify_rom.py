import hashlib,re,pathlib
p=pathlib.Path(__file__).resolve().parent
def read(name):
 s=(p/name).read_text().split('{',1)[1].split('}',1)[0]
 return bytes(map(int,re.findall(r'\b\d+\b',s)))
original=read('original_rom.inc')
patched=read('original_rom_extended.inc')
assert len(original)==len(patched)==4096
assert hashlib.sha1(original).hexdigest()=='bbf334c82bc89b2f131f5a50f0a617bc3bc4c329'
assert [(i,a,b) for i,(a,b) in enumerate(zip(original,patched)) if a!=b]==[(0xd2c,0x5c,0x2b)]
print('TORTURE_PATCH_VERIFIED_ONE_BYTE',hashlib.sha1(patched).hexdigest())
