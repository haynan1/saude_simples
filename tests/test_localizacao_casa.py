"""Localização da casa: link de mapa opcional, clicável na tela e no PDF.

O valor é colado pelo operador e vira `href` numa página e num documento — por
isso o esquema da URL é tratado como fronteira de segurança, não como detalhe
de formatação.
"""
from io import BytesIO

import pytest
from pypdf import PdfReader

import app
import db
from tests.conftest import criar_casa, criar_paciente

MAPA = "https://maps.app.goo.gl/aBcDeF123"


def _casa_no_banco(casa_id=1):
    conn = db.get_db_connection()
    row = conn.execute("SELECT * FROM casas WHERE id = ?", (casa_id,)).fetchone()
    conn.close()
    return row


def links_do_pdf(data):
    """URLs das anotações de link do PDF — é isso que torna o texto clicável."""
    leitor = PdfReader(BytesIO(data))
    urls = []
    for pagina in leitor.pages:
        for anotacao in pagina.get("/Annots") or []:
            objeto = anotacao.get_object()
            acao = objeto.get("/A") or {}
            if acao.get("/URI"):
                urls.append(str(acao["/URI"]))
    return urls


# ---------------------------------------------------------------------------
# Normalização e recusa (fronteira de segurança)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "entrada,esperado",
    [
        ("", None),
        ("   ", None),
        (None, None),
        (MAPA, MAPA),
        ("http://osm.org/x", "http://osm.org/x"),
        # Colado sem esquema (o app do Maps entrega assim): assume https.
        ("maps.app.goo.gl/aBcDeF", "https://maps.app.goo.gl/aBcDeF"),
        # Dois-pontos no caminho não é esquema — não pode confundir o parser.
        ("www.site.com/mapa?q=1:2", "https://www.site.com/mapa?q=1:2"),
        ("HTTPS://Maps.Google.com/x", "HTTPS://Maps.Google.com/x"),
    ],
)
def test_links_aceitos(entrada, esperado):
    url, erro = app.normalizar_link_localizacao(entrada)
    assert erro is None
    assert url == esperado


@pytest.mark.parametrize(
    "entrada",
    [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///C:/Windows/System32",
        "vbscript:msgbox(1)",
        "//evil.example/x",
        "https://exemplo.com/ com espaco",
        "java\tscript:alert(1)",
        "https://" + "a" * 600,
    ],
)
def test_links_recusados(entrada):
    url, erro = app.normalizar_link_localizacao(entrada)
    assert url is None
    assert erro  # o operador recebe o motivo, não um silêncio


# ---------------------------------------------------------------------------
# Cadastro e edição
# ---------------------------------------------------------------------------
def test_cadastrar_casa_com_localizacao(logged_client):
    logged_client.post(
        "/casa/nova",
        data={"endereco": "Rua A, 1", "numero_casa": "1", "quadra_id": "",
              "tipo_imovel": "domicilio", "localizacao": MAPA},
    )
    assert _casa_no_banco()["localizacao"] == MAPA


def test_localizacao_e_opcional(logged_client):
    criar_casa(logged_client)
    assert _casa_no_banco()["localizacao"] is None


def test_editar_grava_e_remove_a_localizacao(logged_client):
    criar_casa(logged_client)
    base = {"endereco": "Rua A, 1", "numero_casa": "1", "quadra_id": "", "tipo_imovel": "domicilio"}

    logged_client.post("/casa/1/editar", data={**base, "localizacao": MAPA})
    assert _casa_no_banco()["localizacao"] == MAPA

    logged_client.post("/casa/1/editar", data={**base, "localizacao": ""})
    assert _casa_no_banco()["localizacao"] is None


def test_link_invalido_recusa_e_devolve_o_formulario_preenchido(logged_client):
    criar_casa(logged_client)
    resp = logged_client.post(
        "/casa/1/editar",
        data={"endereco": "Rua Nova, 9", "numero_casa": "7", "quadra_id": "",
              "tipo_imovel": "lar_idosos", "localizacao": "javascript:alert(1)"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    corpo = resp.get_data(as_text=True)
    # Nada foi gravado...
    casa = _casa_no_banco()
    assert casa["endereco"] == "Rua A, 1"
    assert casa["localizacao"] is None
    # ...e o operador não perde o que digitou.
    assert "Rua Nova, 9" in corpo
    assert 'value="7"' in corpo
    assert "javascript:alert(1)" in corpo
    assert 'value="lar_idosos" selected' in corpo


# ---------------------------------------------------------------------------
# Onde o link aparece
# ---------------------------------------------------------------------------
def test_link_clicavel_no_painel_da_casa(logged_client):
    criar_casa(logged_client)
    logged_client.post(
        "/casa/1/editar",
        data={"endereco": "Rua A, 1", "numero_casa": "1", "quadra_id": "",
              "tipo_imovel": "domicilio", "localizacao": MAPA},
    )
    corpo = logged_client.get("/casa/1").get_data(as_text=True)
    assert f'href="{MAPA}"' in corpo
    assert 'rel="noopener noreferrer"' in corpo
    assert "Ver no mapa" in corpo


def test_link_clicavel_no_pdf(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="MORADOR COM MAPA")
    logged_client.post(
        "/casa/1/editar",
        data={"endereco": "Rua A, 1", "numero_casa": "1", "quadra_id": "",
              "tipo_imovel": "domicilio", "localizacao": MAPA},
    )
    resp = logged_client.get("/exportar/pdf")
    assert resp.status_code == 200
    assert MAPA in links_do_pdf(resp.data)


def test_pdf_sem_localizacao_nao_ganha_link(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="MORADOR SEM MAPA")
    assert links_do_pdf(logged_client.get("/exportar/pdf").data) == []


def test_link_hostil_gravado_direto_no_banco_nao_vira_href(logged_client):
    """O formulário não é a única porta: `/banco/importar` aceita um .db de
    outra máquina e valida estrutura, não conteúdo. Um "javascript:" gravado na
    coluna não pode virar link nem na tela nem no PDF."""
    conn = db.get_db_connection()
    conn.execute(
        "INSERT INTO casas (quadra_id, numero_casa, endereco, tipo_imovel, localizacao)"
        " VALUES (NULL, 1, 'Rua A, 1', 'domicilio', 'javascript:alert(document.cookie)')"
    )
    conn.execute(
        "INSERT INTO pacientes (casa_id, nome, data_nascimento, sexo)"
        " VALUES (1, 'MORADOR', '1990-01-01', 'Feminino')"
    )
    conn.commit()
    conn.close()

    painel_da_casa = logged_client.get("/casa/1").get_data(as_text=True)
    assert "javascript:" not in painel_da_casa
    assert "Ver no mapa" not in painel_da_casa

    formulario = logged_client.get("/casa/1/editar").get_data(as_text=True)
    assert "javascript:" not in formulario

    pdf = logged_client.get("/exportar/pdf")
    assert pdf.status_code == 200
    assert links_do_pdf(pdf.data) == []


def test_aspas_no_link_nao_escapam_do_atributo_no_pdf(logged_client):
    """Aspa na URL fecharia o href e o resto viraria marcação do documento."""
    conn = db.get_db_connection()
    conn.execute(
        "INSERT INTO casas (quadra_id, numero_casa, endereco, tipo_imovel, localizacao)"
        ' VALUES (NULL, 1, \'Rua A, 1\', \'domicilio\', \'https://x.com/a"b\')'
    )
    conn.execute(
        "INSERT INTO pacientes (casa_id, nome, data_nascimento, sexo)"
        " VALUES (1, 'MORADOR', '1990-01-01', 'Feminino')"
    )
    conn.commit()
    conn.close()

    resp = logged_client.get("/exportar/pdf")
    assert resp.status_code == 200  # antes de tudo: não quebra a geração
    assert 'https://x.com/a"b' in links_do_pdf(resp.data)
