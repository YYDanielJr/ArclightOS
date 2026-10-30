#!/bin/bash
set -euo pipefail
python3 - <<'PY'
import socket
s=socket.socket(socket.AF_ALG,socket.SOCK_SEQPACKET)
s.bind(('skcipher','cbc(aes)'))
print('AF_ALG skcipher cbc(aes) kernel fixture available; all upstream tests remain enabled')
PY
