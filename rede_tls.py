"""Gerenciamento de rede local e certificado TLS self-signed do Saúde Simples.

Por padrão o sistema roda apenas em localhost (privado). Quando o
compartilhamento na rede WiFi local está ligado
(SAUDE_SIMPLES_COMPARTILHAR_REDE=true), o certificado passa a incluir também o
IP atual da máquina, mais endereços extras configurados. Se o IP mudar (DHCP),
`ensure_certificate_current` regenera o certificado no próximo start — o
endereço nunca fica "chumbado".

Dependência: cryptography (apenas para os fluxos de certificado).
"""
import datetime
import ipaddress
import json
import logging
import os
import socket
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

logger = logging.getLogger("saude_simples")

APP_NAME = os.environ.get("SAUDE_SIMPLES_APP_NAME", "Saúde Simples")
BASE_DIR = Path(__file__).resolve().parent

CERT_DIR = BASE_DIR / "instance" / "certs"
CERT_FILE = CERT_DIR / "server.crt"
KEY_FILE = CERT_DIR / "server.key"
EXTRA_FILE = CERT_DIR / "enderecos_extra.json"
VALID_DAYS = 825


_LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}


def network_sharing_enabled() -> bool:
    """Compartilhamento na rede WiFi local. Desligado por padrão (só localhost).

    Liga com SAUDE_SIMPLES_COMPARTILHAR_REDE=true. Definir um
    SAUDE_SIMPLES_HOST explícito diferente de localhost (ex.: 0.0.0.0) também
    conta como compartilhamento ligado.
    """
    if os.environ.get("SAUDE_SIMPLES_COMPARTILHAR_REDE", "").lower() in ("1", "true", "sim", "yes"):
        return True
    host = os.environ.get("SAUDE_SIMPLES_HOST", "").strip().lower()
    return bool(host) and host not in _LOCAL_HOSTS


def get_lan_ip() -> str:
    """Descobre o IP da máquina na rede local (sem enviar nenhum pacote)."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("10.255.255.255", 1))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def certificate_exists() -> bool:
    return CERT_FILE.exists() and KEY_FILE.exists()


def load_extra_addresses() -> list[str]:
    if not EXTRA_FILE.exists():
        return []
    try:
        data = json.loads(EXTRA_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return [str(item).strip() for item in data if str(item).strip()]
    except (json.JSONDecodeError, OSError):
        pass
    return []


def save_extra_addresses(addresses: list[str]) -> None:
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    cleaned = sorted({a.strip() for a in addresses if a.strip()})
    EXTRA_FILE.write_text(json.dumps(cleaned, ensure_ascii=False, indent=2), encoding="utf-8")


def _build_san(extra_names: list[str]) -> tuple[x509.SubjectAlternativeName, list[str], list[str]]:
    dns_names = {"localhost"}
    ip_addresses = {"127.0.0.1"}
    if network_sharing_enabled():
        ip_addresses.add(get_lan_ip())

    for name in extra_names:
        try:
            ipaddress.ip_address(name)
            ip_addresses.add(name)
        except ValueError:
            dns_names.add(name)

    sorted_dns = sorted(dns_names)
    sorted_ips = sorted(ip_addresses)
    entries: list[x509.GeneralName] = [x509.DNSName(n) for n in sorted_dns]
    entries += [x509.IPAddress(ipaddress.ip_address(ip)) for ip in sorted_ips]
    return x509.SubjectAlternativeName(entries), sorted_dns, sorted_ips


def generate_certificate(extra_addresses: list[str] | None = None) -> dict:
    """Gera (ou substitui) o certificado para o IP atual + endereços extras."""
    if extra_addresses is not None:
        save_extra_addresses(extra_addresses)
    extras = load_extra_addresses()

    CERT_DIR.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, APP_NAME),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, APP_NAME),
    ])

    san, dns_names, ip_addresses = _build_san(extras)
    now = datetime.datetime.now(datetime.timezone.utc)

    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=VALID_DAYS))
        .add_extension(san, critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )

    KEY_FILE.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    CERT_FILE.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    logger.info("TLS_CERT_GENERATED ips=%s dns=%s", ip_addresses, dns_names)

    return certificate_info()


def certificate_info() -> dict:
    """Estado atual do certificado: existência, validade e endereços cobertos."""
    current_ip = get_lan_ip()
    info = {
        "exists": certificate_exists(),
        "current_ip": current_ip,
        "extra_addresses": load_extra_addresses(),
        "dns_names": [],
        "ip_addresses": [],
        "not_valid_after": None,
        "covers_current_ip": False,
        "cert_path": str(CERT_FILE),
    }
    if not info["exists"]:
        return info

    try:
        cert = x509.load_pem_x509_certificate(CERT_FILE.read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        info["dns_names"] = san.get_values_for_type(x509.DNSName)
        info["ip_addresses"] = [str(ip) for ip in san.get_values_for_type(x509.IPAddress)]
        info["not_valid_after"] = cert.not_valid_after_utc
        # Só localhost: não há IP de rede para cobrir, então o certificado
        # nunca precisa ser regenerado por mudança de IP.
        info["covers_current_ip"] = (
            not network_sharing_enabled() or current_ip in info["ip_addresses"]
        )
    except (ValueError, OSError, x509.ExtensionNotFound):
        info["exists"] = False

    return info


def ensure_certificate_current() -> bool:
    """Se já existe certificado mas não cobre o IP atual, regenera. Retorna True se regenerou."""
    if not certificate_exists():
        return False
    info = certificate_info()
    if info["exists"] and not info["covers_current_ip"]:
        logger.info("TLS_CERT_IP_CHANGED regenerando para %s", info["current_ip"])
        generate_certificate()
        return True
    return False
