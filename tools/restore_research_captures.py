"""Restore receipt-bound research snapshots; never touch accepted account state."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.request
import zipfile

def registry():
    p=Path(__file__).resolve().parents[1]/'docs/research_source_reuse_registry.json'
    value=json.loads(p.read_text())
    if value['schema_version']!='research-source-reuse-registry-v1':raise ValueError('registry_schema')
    snapshots=value['snapshots']
    if not {'current','sample'}<=set(snapshots)<={'current','sample','rs_extension'}:
        raise ValueError('registry_scope')
    for name,r in snapshots.items():
        if (r['prefix'] not in ('research_source_snapshots','research_source_extensions') or
                not re.fullmatch('[0-9]+-[0-9]+-[0-9a-f]{40}',r['snapshot']) or
                not re.fullmatch('[0-9a-f]{64}',r['receipts_sha256'])):
            raise ValueError('registry_identity')
    return snapshots


def main():
    from admit_connected_research import verify_capture
    root=Path(os.environ['RUNNER_TEMP'])/'us-research-reuse';root.mkdir(mode=0o700,exist_ok=False)
    config=root/'rclone.conf';config.write_text(os.environ['RESEARCH_RCLONE_CONFIG']);config.chmod(0o600)
    try:
        archive=root/'rclone.zip'
        with urllib.request.urlopen('https://downloads.rclone.org/v1.75.0/rclone-v1.75.0-linux-amd64.zip',timeout=30) as response:
            raw=response.read(40*1024*1024)
        if hashlib.sha256(raw).hexdigest()!='aa2804e08f48250e71009c727124b6341cd0288465804a9a09d14663cabafbaa':raise ValueError('binary_digest')
        archive.write_bytes(raw)
        with zipfile.ZipFile(archive) as z:
            binary=root/'rclone';binary.write_bytes(z.read('rclone-v1.75.0-linux-amd64/rclone'));binary.chmod(0o700)
        for name,item in registry().items():
            snapshot,expected=item['snapshot'],item['receipts_sha256']
            target=root/name
            subprocess.run([str(binary),'--config',str(config),'copy',
                'gdrive:'+item['prefix']+'/'+snapshot+'/',str(target),'--immutable','--transfers','4','--checkers','4'],
                check=True,timeout=600,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            report=verify_capture(target)
            if report['source_receipts_hash']!=expected:raise ValueError('snapshot_identity')
            print(json.dumps({'restored':name,'snapshot':snapshot,'receipts_hash':expected,'status':'VERIFIED'}),flush=True)
    finally:
        config.unlink(missing_ok=True)

if __name__=='__main__':
    try:main()
    except Exception:
        raise SystemExit('Research snapshot restore failed; no credential or provider error text is emitted.') from None
