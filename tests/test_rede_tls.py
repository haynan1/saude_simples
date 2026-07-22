"""Testes do módulo de rede local e certificado TLS (rede_tls.py)."""
import datetime

import pytest
from cryptography import x509

import rede_tls


@pytest.fixture()
def certs_isolados(tmp_path, monkeypatch):
    """Aponta os artefatos de certificado para um diretório isolado."""
    cert_dir = tmp_path / "certs"
    monkeypatch.setattr(rede_tls, "CERT_DIR", cert_dir)
    monkeypatch.setattr(rede_tls, "CERT_FILE", cert_dir / "server.crt")
    monkeypatch.setattr(rede_tls, "KEY_FILE", cert_dir / "server.key")
    monkeypatch.setattr(rede_tls, "EXTRA_FILE", cert_dir / "enderecos_extra.json")
    return cert_dir


# ---------------------------------------------------------------------------
# Opt-in de rede
# ---------------------------------------------------------------------------
def test_padrao_e_apenas_localhost(monkeypatch):
    monkeypatch.delenv("SAUDE_SIMPLES_COMPARTILHAR_REDE", raising=False)
    monkeypatch.delenv("SAUDE_SIMPLES_HOST", raising=False)
    assert rede_tls.network_sharing_enabled() is False


def test_compartilhar_rede_liga_por_flag(monkeypatch):
    monkeypatch.setenv("SAUDE_SIMPLES_COMPARTILHAR_REDE", "true")
    assert rede_tls.network_sharing_enabled() is True


def test_host_explicito_nao_local_conta_como_compartilhamento(monkeypatch):
    monkeypatch.delenv("SAUDE_SIMPLES_COMPARTILHAR_REDE", raising=False)
    monkeypatch.setenv("SAUDE_SIMPLES_HOST", "0.0.0.0")
    assert rede_tls.network_sharing_enabled() is True


def test_host_localhost_nao_liga_compartilhamento(monkeypatch):
    monkeypatch.delenv("SAUDE_SIMPLES_COMPARTILHAR_REDE", raising=False)
    monkeypatch.setenv("SAUDE_SIMPLES_HOST", "127.0.0.1")
    assert rede_tls.network_sharing_enabled() is False


def test_get_lan_ip_retorna_ipv4():
    import ipaddress

    ip = rede_tls.get_lan_ip()
    ipaddress.ip_address(ip)  # levanta ValueError se não for IP válido


# ---------------------------------------------------------------------------
# Certificado
# ---------------------------------------------------------------------------
def test_gerar_certificado_cria_par_e_san_minimo(certs_isolados, monkeypatch):
    monkeypatch.delenv("SAUDE_SIMPLES_COMPARTILHAR_REDE", raising=False)
    monkeypatch.delenv("SAUDE_SIMPLES_HOST", raising=False)

    info = rede_tls.generate_certificate()
    assert rede_tls.certificate_exists()
    assert "localhost" in info["dns_names"]
    assert "127.0.0.1" in info["ip_addresses"]
    # Sem compartilhamento, o certificado sempre cobre o cenário atual.
    assert info["covers_current_ip"] is True

    validade = info["not_valid_after"]
    assert validade > datetime.datetime.now(datetime.timezone.utc)


def test_certificado_inclui_ip_da_lan_quando_compartilhando(certs_isolados, monkeypatch):
    monkeypatch.setenv("SAUDE_SIMPLES_COMPARTILHAR_REDE", "true")
    info = rede_tls.generate_certificate()
    assert rede_tls.get_lan_ip() in info["ip_addresses"]
    assert info["covers_current_ip"] is True


def test_enderecos_extras_persistem_e_entram_no_san(certs_isolados, monkeypatch):
    monkeypatch.delenv("SAUDE_SIMPLES_COMPARTILHAR_REDE", raising=False)
    info = rede_tls.generate_certificate(extra_addresses=["192.168.9.9", "recepcao.local"])
    assert "192.168.9.9" in info["ip_addresses"]
    assert "recepcao.local" in info["dns_names"]
    # Persistidos: nova geração sem argumentos preserva os extras.
    info2 = rede_tls.generate_certificate()
    assert "192.168.9.9" in info2["ip_addresses"]


def test_regeneracao_quando_ip_nao_coberto(certs_isolados, monkeypatch):
    monkeypatch.setenv("SAUDE_SIMPLES_COMPARTILHAR_REDE", "true")
    rede_tls.generate_certificate()

    # Simula troca de IP (DHCP): o IP atual passa a não estar no certificado.
    monkeypatch.setattr(rede_tls, "get_lan_ip", lambda: "10.99.99.99")
    assert rede_tls.certificate_info()["covers_current_ip"] is False
    assert rede_tls.ensure_certificate_current() is True
    assert "10.99.99.99" in rede_tls.certificate_info()["ip_addresses"]


def test_sem_certificado_ensure_nao_gera(certs_isolados):
    assert rede_tls.ensure_certificate_current() is False
    assert not rede_tls.certificate_exists()


def test_certificado_e_um_x509_valido(certs_isolados, monkeypatch):
    monkeypatch.delenv("SAUDE_SIMPLES_COMPARTILHAR_REDE", raising=False)
    rede_tls.generate_certificate()
    cert = x509.load_pem_x509_certificate(rede_tls.CERT_FILE.read_bytes())
    assert cert.signature_hash_algorithm.name == "sha256"
