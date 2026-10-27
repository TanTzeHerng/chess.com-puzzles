"""Separate durable release checkpoint. Never touches Delta-1 original run."""
import os,sys,subprocess,pathlib,tempfile,zipfile
TAG='delta1-puzzle-torture-20261028'
mode,shard,target=sys.argv[1:]
dest=pathlib.Path(target).resolve()
dest.mkdir(parents=True,exist_ok=True)
name='torture-state-shard-'+str(shard)+'.zip'
with tempfile.TemporaryDirectory(prefix='delta1-torture-') as temp:
 archive=pathlib.Path(temp)/name
 if mode=='restore':
  r=subprocess.run(['gh','release','download',TAG,'--pattern',name,
   '--dir',temp,'--clobber'],capture_output=True,text=True)
  if r.returncode:
   print('TORTURE_RESTORE_CLEAN no previous checkpoint for '+name,flush=True)
   sys.exit(0)
  with zipfile.ZipFile(archive) as z:
   for n in z.namelist():
    if not (dest/n).resolve().is_relative_to(dest):
     raise ValueError('Unsafe checkpoint path: '+n)
   z.extractall(dest)
  print('TORTURE_RESTORED',name,archive.stat().st_size,flush=True)
 elif mode=='save':
  with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=3) as z:
   for f in dest.rglob('*'):
    if f.is_file() and not f.name.endswith('.tmp'):
     z.write(f,f.relative_to(dest))
  if archive.stat().st_size >= 2*1024**3:raise RuntimeError('Release asset limit exceeded')
  subprocess.run(['gh','release','upload',TAG,str(archive),'--clobber'],check=True)
  print('TORTURE_SAVED',name,archive.stat().st_size,flush=True)
 else:raise ValueError('Unknown checkpoint mode')
