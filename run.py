"""Entrada do servidor Saúde Simples — roteamento na rede WiFi local.

  - Padrão: apenas localhost (privado).
  - SAUDE_SIMPLES_COMPARTILHAR_REDE=true no .env abre para a rede local
    (bind 0.0.0.0); o IP é detectado automaticamente e exibido no banner.
  - Se instance/certs/server.crt existir, sobe em HTTPS (cheroot) com
    certificado self-signed que acompanha o IP da máquina; senão, HTTP
    (waitress). SAUDE_SIMPLES_DEBUG=true usa o servidor dev do Flask.

Uso: python run.py   (gerar TLS antes, se quiser HTTPS: python gerar_certificado.py)
"""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from rede_tls import (  # noqa: E402
    CERT_FILE,
    KEY_FILE,
    certificate_exists,
    ensure_certificate_current,
    get_lan_ip,
    network_sharing_enabled,
)

APP_NAME = "Saúde Simples"
DEFAULT_PORT = "5001"

# ── TLS: se houver certificado, o servidor sobe em HTTPS automaticamente ──────
# Se o IP da máquina mudou desde a última geração, o certificado é regenerado.
ensure_certificate_current()
USE_TLS = certificate_exists()

# Sob HTTPS, cookie de sessão Secure deve estar ativo — definido ANTES de
# importar o app (o config é lido no import).
if USE_TLS:
    os.environ.setdefault("SAUDE_SIMPLES_FORCE_HTTPS", "true")


def print_banner(port: int, scheme: str, sharing: bool) -> None:
    line = "=" * 62
    print(f"\n{line}")
    print(f"  {APP_NAME}")
    if sharing:
        print(f"  Servidor local ativo na rede WiFi ({scheme.upper()})")
    else:
        print(f"  Servidor ativo apenas neste computador ({scheme.upper()})")
    print(line)
    print(f"  Neste computador:      {scheme}://localhost:{port}")
    if sharing:
        print(f"  Outros dispositivos:   {scheme}://{get_lan_ip()}:{port}")
    print(line)
    if scheme == "https":
        print("  Certificado self-signed: no primeiro acesso cada dispositivo")
        print("  mostra um aviso de segurança. Aceite a exceção uma vez.")
    if sharing:
        print("  Conecte celulares/computadores na MESMA rede WiFi e")
        print("  acesse o endereço acima. Ctrl+C encerra o servidor.")
    else:
        print("  Para compartilhar na rede WiFi local, defina")
        print("  SAUDE_SIMPLES_COMPARTILHAR_REDE=true no .env e reinicie.")
    print(f"{line}\n", flush=True)


try:
    import app as app_module
except RuntimeError as exc:
    # Ex.: SECRET_KEY ausente — mensagem limpa em vez de traceback.
    print(f"\nNão foi possível iniciar o sistema.\n\n{exc}\n", file=sys.stderr)
    raise SystemExit(1)

app = app_module.app


if __name__ == "__main__":
    debug = os.environ.get("SAUDE_SIMPLES_DEBUG", "").lower() in ("1", "true", "sim", "yes")
    sharing = network_sharing_enabled()
    # Padrão: apenas localhost (privado). Um HOST explícito tem prioridade.
    host = os.environ.get("SAUDE_SIMPLES_HOST") or ("0.0.0.0" if sharing else "127.0.0.1")
    port = int(os.environ.get("SAUDE_SIMPLES_PORT", DEFAULT_PORT))
    scheme = "https" if USE_TLS else "http"

    app_module.preparar_primeiro_boot()
    print_banner(port, scheme, sharing)

    if USE_TLS:
        # HTTPS: cheroot (servidor WSGI puro-Python, multi-thread, com TLS).
        from cheroot.ssl.builtin import BuiltinSSLAdapter
        from cheroot.wsgi import Server as WSGIServer

        server = WSGIServer((host, port), app, numthreads=8, server_name=APP_NAME)
        server.ssl_adapter = BuiltinSSLAdapter(str(CERT_FILE), str(KEY_FILE))
        try:
            server.start()
        except KeyboardInterrupt:
            server.stop()
    elif debug:
        # Desenvolvimento: servidor do Flask com recarga de templates.
        app.run(host=host, port=port, debug=True, use_reloader=False)
    else:
        # Rede local em HTTP: waitress, servidor WSGI robusto e multi-thread.
        from waitress import serve

        serve(app, host=host, port=port, threads=8, ident=APP_NAME)
