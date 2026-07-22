"""Gera um certificado TLS self-signed para o servidor local, com o IP atual
da máquina incluído automaticamente. Endereços extras podem ser passados como
argumentos.

Uso: python gerar_certificado.py
     python gerar_certificado.py 192.168.1.50 recepcao.local
"""
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT_DIR / ".env")

from rede_tls import CERT_FILE, KEY_FILE, VALID_DAYS, generate_certificate  # noqa: E402


def main() -> None:
    extra = sys.argv[1:]
    # Passar lista (mesmo vazia) substitui os endereços extras salvos.
    info = generate_certificate(extra_addresses=extra if extra else None)

    enderecos = ", ".join(info["dns_names"] + info["ip_addresses"])
    print("Certificado gerado:")
    print(f"  {CERT_FILE}")
    print(f"  {KEY_FILE}")
    print(f"  Válido por {VALID_DAYS} dias | Endereços: {enderecos}")
    print("\nAgora rode: python run.py  (o servidor subirá em HTTPS)")


if __name__ == "__main__":
    main()
