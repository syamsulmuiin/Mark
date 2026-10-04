import subprocess,sys
from pathlib import Path
base=Path(__file__).resolve().parent
subprocess.check_call([sys.executable,'-m','pip','install','-r',str(base/'requirements.txt')])
print('Installed. Start desktop companion with:')
print(f'  "{sys.executable}" "{base / "companion.py"}"')
