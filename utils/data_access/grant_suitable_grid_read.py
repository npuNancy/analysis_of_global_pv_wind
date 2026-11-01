"""Grant the analysis account read access to accepted suitable-grid products."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess

ROOT = Path('/work/home/acsep06cn2/generation_loss_suitable_grid/suitable_grid')
UID = '403202'
LOG = Path('/work/home/aczlvkl1ac/project_climate_patchify/repos/analysis_of_global_pv_wind/logs/paper_figures/suitable_grid_loss/access')


def acl(paths, default=False):
    if paths:
        entry = ('d:u:' + UID + ':r-x') if default else ('u:' + UID + ':rX')
        subprocess.run(['setfacl', '-n', '-m', entry, *map(str, paths)], check=True)


def tree(path):
    # Existing masks and other users' ACL entries remain unchanged.
    subprocess.run(['setfacl', '-R', '-P', '-n', '-m', 'u:' + UID + ':rX', str(path)], check=True)
    directories = []
    for directory, _, _ in os.walk(path, followlinks=False):
        directories.append(Path(directory))
        if len(directories) == 128:
            acl(directories, default=True)
            directories = []
    acl(directories, default=True)
    return str(path)


def main():
    c = json.loads((ROOT / 'runtime/completion.json').read_text())
    if c['status'] != 'COMPLETED' or c['completed'] != 1044:
        raise ValueError('Unexpected completion index')
    units = set()
    for receipt_path in c['receipts']:
        receipt = json.loads(Path(receipt_path).read_text())
        folder = Path(receipt['manifest']).parent
        if folder.parent != ROOT / 'outputs':
            raise ValueError('Manifest outside published outputs')
        units.add(folder)
    acl([ROOT, ROOT / 'outputs'])
    acl([ROOT, ROOT / 'outputs'], default=True)
    work = [ROOT / 'runtime', ROOT / 'inputs', *sorted(units)]
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = [pool.submit(tree, path) for path in work]
        for i, future in enumerate(as_completed(futures), 1):
            future.result()
            if i % 100 == 0:
                print('ACL_COMPLETED', i, '/', len(work), flush=True)
    report = dict(status='COMPLETED', source_root=str(ROOT), reader_uid=UID,
                  units=len(units), permission='read files; read/traverse directories',
                  existing_masks_preserved=True, default_directory_acl=True)
    (LOG / 'access.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
