import gzip,pathlib
p=pathlib.Path(__file__).resolve().parent
src=pathlib.Path(r'C:\Khan Academy\Delta1_Chesscom_2000_2500\sources-full.json.gz')
data=gzip.decompress(src.read_bytes())
(p/'sources.json').write_bytes(data)
print('SOURCE_BYTES',len(data))
