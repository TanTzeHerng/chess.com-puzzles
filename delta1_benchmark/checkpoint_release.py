import os,pathlib,subprocess,sys,tempfile,zipfile
TAG='delta1-full-state-20261027T081416Z'
mode,shard,where=sys.argv[1:];dest=pathlib.Path(where).resolve();dest.mkdir(parents=True,exist_ok=True)
name='state-shard-'+shard+'.zip'
with tempfile.TemporaryDirectory(prefix='delta1-state-') as temporary:
 archive=pathlib.Path(temporary)/name
 if mode=='restore':
  r=subprocess.run(['gh','release','download',TAG,'--pattern',name,'--dir',temporary,'--clobber'],capture_output=True,text=True)
  if r.returncode:print('No prior checkpoint for this clean epoch; starting fresh.');sys.exit(0)
  with zipfile.ZipFile(archive) as z:
   for n in z.namelist():
    if not (dest/n).resolve().is_relative_to(dest):raise ValueError('Unsafe checkpoint path')
   z.extractall(dest)
  print('Restored',name)
 elif mode=='save':
  with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
   for f in dest.rglob('*'):
    if f.is_file() and not f.name.endswith('.tmp'):z.write(f,f.relative_to(dest))
  if archive.stat().st_size>=2*1024**3:raise RuntimeError('Checkpoint exceeds release-asset limit')
  subprocess.run(['gh','release','upload',TAG,str(archive),'--clobber'],check=True)
  print('Saved',name,'bytes',archive.stat().st_size)
 else:raise ValueError('Unknown checkpoint operation')
