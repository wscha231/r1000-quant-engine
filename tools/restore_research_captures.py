"""Read two exact private research snapshots; never touch accepted account state."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import urllib.request
import zipfile

SNAPSHOTS={
    'current':('34499199863-1-9e850fa113c6ccdb046087cce8d31fbdb0a72967',
        'e3e1ca98835cbf95a7ced8501100ee228f66bf7742de0deefc38be193f3fd10e'),
    'sample':('34490195617-1-cf839ea6d8a74d0c1f261e628d917bf19c8da632',
        'ed3e85711eb063cef430158a68e589261c66193bea69aa4eb0a8a524b45a442e')}


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
        for name,(snapshot,expected) in SNAPSHOTS.items():
            target=root/name
            subprocess.run([str(binary),'--config',str(config),'copy',
                'gdrive:research_source_snapshots/'+snapshot+'/',str(target),'--immutable','--transfers','4','--checkers','4'],
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
