"""Scripts de importação do caderno de campo (scripts/importacao_pdf/).

O teste que mais importa aqui é o de divergência: `comum.py` tem cópias de duas
funções de formatação do app.py, porque importar o módulo app levantaria o
Flask inteiro só para usá-las. Se as cópias divergirem do original, o CPF
gravado por script deixa de casar com a busca da tela — e ninguém percebe até
alguém não encontrar um paciente.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "importacao_pdf"
))

import comum  # noqa: E402

DOCUMENTOS = [
    "", "1", "123", "1234", "123456", "1234567", "123456789", "12345678901",
    "082.789.891-68", "905.429.831-68", "700405941455241", "898005145572605",
    "abc", "12.345", "0000000000000000000",
]

TELEFONES = [
    "", "6", "64", "6499", "649932", "6499323", "6499323510", "64993235106",
    "(64) 99323-5106", "(64)9 8419-2770", "letras", "649932351061234",
]


@pytest.mark.parametrize("valor", DOCUMENTOS)
def test_formatar_cpf_ou_cns_nao_divergiu_do_app(valor):
    import app

    assert comum.formatar_cpf_ou_cns(valor) == app.formatar_cpf_ou_cns(valor)


@pytest.mark.parametrize("valor", TELEFONES)
def test_formatar_telefone_nao_divergiu_do_app(valor):
    import app

    assert comum.formatar_telefone(valor) == app.formatar_telefone(valor)


def test_norm_e_mais_estrito_que_o_app_de_proposito():
    """`norm` acrescenta o colapso de espaço ao que o app faz.

    O caderno é digitado à mão e tem espaço duplo no meio de nome; sem colapsar,
    a mesma pessoa entraria duas vezes. Fora isso, as duas concordam — se essa
    parte divergir, o casamento por nome entre script e app quebra."""
    import app

    for nome in ("José da Silva", "MARIA APARECIDA", "Conceição"):
        assert comum.norm(nome) == app.texto_normalizado(nome).upper().strip()

    assert comum.norm("MARIA  APARECIDA") == "MARIA APARECIDA"
    assert app.texto_normalizado("MARIA  APARECIDA").upper() == "MARIA  APARECIDA"


# ---------------------------------------------------------------------------
# Regras próprias dos scripts
# ---------------------------------------------------------------------------
def test_cpf_valido_confere_digito_verificador():
    assert comum.cpf_valido("082.789.891-68")
    assert comum.cpf_valido("90542983168")
    # Os dois que o caderno traz com dígito errado.
    assert not comum.cpf_valido("283.036.012-54")
    assert not comum.cpf_valido("323.802.881-34")
    # Casos degenerados.
    assert not comum.cpf_valido("11111111111")
    assert not comum.cpf_valido("")
    assert not comum.cpf_valido("123")


def test_data_iso_aceita_as_formas_do_caderno():
    assert comum.data_iso("19/05/1951") == "1951-05-19"
    assert comum.data_iso("02-06-1957") == "1957-06-02"  # separador diferente
    assert comum.data_iso("4/8/1945") == "1945-08-04"
    # Erros reais do documento: nada é inventado.
    assert comum.data_iso("10/06/193") == ""
    assert comum.data_iso("(64)9 9960-6563") == ""
    assert comum.data_iso("") == ""
    assert comum.data_iso("30/02/1990") == ""  # data inexistente


def test_nome_e_nota_separa_o_recado_do_agente():
    assert comum.nome_e_nota("SERGIO LISBOA (MORA NA CASA DE CIMA)") == (
        "SERGIO LISBOA", "MORA NA CASA DE CIMA")
    # Parêntese curto demais para ser recado continua no nome.
    assert comum.nome_e_nota("JOAO (JR)") == ("JOAO (JR)", "")
    assert comum.nome_e_nota("MARIA   APARECIDA  ") == ("MARIA APARECIDA", "")


def test_encontrar_paciente_casa_por_documento_e_por_nome(logged_client):
    """A regra de identidade é a mesma nos três scripts que mexem no banco."""
    import db

    conn = db.get_db_connection()
    conn.execute(
        "INSERT INTO pacientes (casa_id, nome, cpf, data_nascimento, sexo)"
        " VALUES (NULL, 'JOSÉ DA SILVA', '082.789.891-68', '1951-05-19', 'Masculino')"
    )
    conn.execute(
        "INSERT INTO pacientes (casa_id, nome, cpf, data_nascimento, sexo)"
        " VALUES (NULL, 'ANA SEM DOCUMENTO', '', '1970-03-02', 'Feminino')"
    )
    conn.commit()
    _, por_documento, por_nome = comum.indexar_pacientes(conn)
    conn.close()

    # Casa por CPF mesmo com o nome escrito diferente.
    _, achado = comum.encontrar_paciente(
        {"nome": "JOSE DA SILVA JUNIOR", "cpf": "08278989168"}, por_documento, por_nome)
    assert achado is not None and achado["nome"] == "JOSÉ DA SILVA"

    # Sem documento, casa por nome + nascimento (acento não atrapalha).
    _, achado = comum.encontrar_paciente(
        {"nome": "Ana Sem Documento", "data_nascimento": "02/03/1970"},
        por_documento, por_nome)
    assert achado is not None and achado["nome"] == "ANA SEM DOCUMENTO"

    # Nome igual, nascimento diferente: é outra pessoa.
    _, achado = comum.encontrar_paciente(
        {"nome": "Ana Sem Documento", "data_nascimento": "02/03/1990"},
        por_documento, por_nome)
    assert achado is None
