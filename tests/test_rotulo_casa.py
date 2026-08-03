"""Identidade da casa: número sozinho não identifica casa nenhuma.

`get_next_house_number` numera por quadra e não há índice único global, então
existe uma Casa 7 em cada quadra do território. Onde o operador ESCOLHE uma
casa — destino de transferência, seletor do cadastro — número solto é erro de
dado esperando acontecer: transferir um morador para a casa errada.

Estes testes cobrem as duas metades do problema:

1. O rótulo diz a quadra, e diz "Sem quadra" quando não há — silêncio apagava
   a diferença entre "esta casa não tem quadra" e "a tela não mostra".
2. A quadra REAL chega às telas. Se algum LEFT JOIN quadras sumir de uma
   consulta, o filtro passa a devolver "Sem quadra" para todo mundo, calado —
   por isso cada teste afirma o número da quadra, não só a presença do rótulo.
"""
import app
from tests.conftest import criar_casa, criar_paciente, criar_quadra


# ---------------------------------------------------------------------------
# O filtro, isolado
# ---------------------------------------------------------------------------
def test_rotulo_junta_casa_e_quadra():
    assert app.rotulo_casa({"numero_casa": 7, "numero_quadra": 13}) == "Casa 7 · Quadra 13"


def test_rotulo_diz_sem_quadra_em_vez_de_calar():
    assert app.rotulo_casa({"numero_casa": 7, "numero_quadra": None}) == "Casa 7 · Sem quadra"


def test_rotulo_vazio_quando_nao_ha_casa():
    assert app.rotulo_casa({"numero_casa": None, "numero_quadra": 13}) == ""
    assert app.rotulo_casa(None) == ""


def test_rotulo_tolera_consulta_sem_a_coluna():
    """Nem toda consulta seleciona as mesmas colunas; faltar não pode explodir."""
    assert app.rotulo_casa({"numero_casa": 7}) == "Casa 7 · Sem quadra"


# ---------------------------------------------------------------------------
# As telas onde a casa é escolhida
# ---------------------------------------------------------------------------
def _territorio_com_duas_casas_7(client):
    """O caso real: mesma numeração em quadras diferentes."""
    criar_quadra(client, numero="13")
    criar_quadra(client, numero="14")
    criar_casa(client, endereco="Rua A, 7", numero="7", quadra_id="1")
    criar_casa(client, endereco="Rua B, 7", numero="7", quadra_id="2")
    criar_casa(client, endereco="Rua C, 9", numero="9")  # sem quadra


def test_destino_da_transferencia_distingue_casas_de_mesmo_numero(logged_client):
    _territorio_com_duas_casas_7(logged_client)
    criar_paciente(logged_client, casa_id=1, nome="QUEM VAI MUDAR")

    corpo = logged_client.get("/pacientes").get_data(as_text=True)
    assert "Casa 7 · Quadra 13" in corpo
    assert "Casa 7 · Quadra 14" in corpo
    assert "Casa 9 · Sem quadra" in corpo


def test_seletor_de_casa_no_cadastro_distingue(logged_client):
    _territorio_com_duas_casas_7(logged_client)
    corpo = logged_client.get("/pacientes/novo").get_data(as_text=True)
    assert "Casa 7 · Quadra 13" in corpo
    assert "Casa 7 · Quadra 14" in corpo
    assert "Casa 9 · Sem quadra" in corpo


def test_busca_do_painel_diz_a_quadra(logged_client):
    _territorio_com_duas_casas_7(logged_client)
    criar_paciente(logged_client, casa_id=2, nome="ANA ENCONTRADA")
    corpo = logged_client.get("/?busca=Ana").get_data(as_text=True)
    assert "Casa 7 · Quadra 14" in corpo


def test_confirmacao_de_exclusao_nomeia_a_casa_inteira(logged_client):
    """Excluir casa apaga os moradores junto — a confirmação tem de dizer
    exatamente qual casa, não um número que pertence a duas."""
    _territorio_com_duas_casas_7(logged_client)
    corpo = logged_client.get("/").get_data(as_text=True)
    assert "Excluir Casa 7 · Quadra 13?" in corpo
    assert "Excluir Casa 7 · Quadra 14?" in corpo


def test_cabecalho_do_cadastro_e_da_edicao_dizem_a_quadra(logged_client):
    _territorio_com_duas_casas_7(logged_client)
    criar_paciente(logged_client, casa_id=2, nome="EM EDICAO")

    corpo = logged_client.get("/casa/2/paciente/novo").get_data(as_text=True)
    assert "Casa 7 · Quadra 14" in corpo

    corpo = logged_client.get("/paciente/1/editar").get_data(as_text=True)
    assert "Casa 7 · Quadra 14" in corpo


def test_confirmacao_da_transferencia_diz_para_onde_foi(logged_client):
    """A mensagem é onde o operador confere o destino depois do fato. "casa 7"
    não confere nada quando há uma Casa 7 em cada quadra."""
    _territorio_com_duas_casas_7(logged_client)
    criar_paciente(logged_client, casa_id=1, nome="QUEM MUDOU")

    resp = logged_client.post(
        "/paciente/1/transferir", data={"casa_destino_id": "2"}, follow_redirects=True
    )
    assert "QUEM MUDOU transferido para a Casa 7 · Quadra 14." in resp.get_data(as_text=True)


def test_confirmacao_da_transferencia_de_familia_diz_para_onde_foi(logged_client):
    _territorio_com_duas_casas_7(logged_client)
    criar_paciente(logged_client, casa_id=1, nome="UM DA FAMILIA", cpf="11111111111")
    criar_paciente(logged_client, casa_id=1, nome="OUTRO DA FAMILIA", cpf="22222222222")

    resp = logged_client.post(
        "/casa/1/transferir", data={"casa_destino_id": "2"}, follow_redirects=True
    )
    assert "2 morador(es) transferido(s) para a Casa 7 · Quadra 14." in resp.get_data(as_text=True)
