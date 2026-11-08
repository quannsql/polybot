"""Package an explicit source allowlist. No data, account secrets or journals."""
import gzip
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'data/releases/polybot-twap-live-20261109.tar.gz'
FILES=['Dockerfile.live','.dockerignore','requirements-twap.txt','requirements-live-sdk.txt',
       '.env.live.example','.env.account.example','.env.example','run_bot.py',
       'verify_live_account.py','verify_twap_runtime.py','manage_twap.py','verify_release.py',
       'deploy_live_oracle.sh','deploy_twap_oracle.sh','ORACLE_TWAP_LIVE_GUIDE.md',
       'TWAP_LIVE_INTEGRATION.md']


def main():
    files=FILES+sorted(str(p.relative_to(ROOT)).replace('\\','/') for p in (ROOT/'polymarket_bot').glob('*.py'))
    contents={name:(ROOT/name).read_bytes().replace(b'\r\n',b'\n') for name in files}
    manifest=dict(strategy='twap60_spot_1400_v1',sdk='polymarket-client==0.17.0',
        release='20261109',source='Local workspace changes, including files not pushed to GitHub',
        files={name:hashlib.sha256(value).hexdigest() for name,value in contents.items()})
    contents['RELEASE_MANIFEST.json']=json.dumps(manifest,indent=2).encode()
    OUT.parent.mkdir(parents=True,exist_ok=True)
    with OUT.open('wb') as raw:
        with gzip.GzipFile(fileobj=raw,mode='wb',filename='',mtime=0) as compressed:
            with tarfile.open(fileobj=compressed,mode='w') as archive:
                for name,value in sorted(contents.items()):
                    info=tarfile.TarInfo(name); info.size=len(value); info.mtime=0
                    info.uid=info.gid=0; info.uname=info.gname=''; info.mode=0o644
                    archive.addfile(info,io.BytesIO(value))
    digest=hashlib.sha256(OUT.read_bytes()).hexdigest()
    OUT.with_suffix(OUT.suffix+'.sha256').write_text(f'{digest}  {OUT.name}\n',encoding='ascii')
    print(json.dumps(dict(path=str(OUT),bytes=OUT.stat().st_size,sha256=digest,files=len(contents)),indent=2))


if __name__=='__main__': main()
