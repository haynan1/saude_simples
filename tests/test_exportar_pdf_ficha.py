"""Ficha do paciente no PDF: um registro em linha, sem campo vazio impresso.

A grade de cinco colunas anterior obrigava o relatório a preencher toda célula
— nome quebrado em três linhas, "Pai: -" e "Mãe: -" em cadastro recém-importado
do e-SUS. Estes testes travam o comportamento que substituiu isso.
"""
import app
from tests.conftest import criar_casa, criar_paciente, criar_quadra, texto_pdf


def ficha_lida(client):
    """Texto do PDF com os espaços normalizados — a ficha usa espaço fixo
    entre rótulo e valor, e a extração devolve isso como espaço comum."""
    return " ".join(texto_pdf(client.get("/exportar/pdf").data).split())


# ---------------------------------------------------------------------------
# Campos da ficha (funções puras)
# ---------------------------------------------------------------------------
def test_campo_vazio_nao_vira_linha():
    assert app.pdf_campo("Tel.", "") == ""
    assert app.pdf_campo("Tel.", None) == ""
    assert app.pdf_campo("Tel.", "   ") == ""


def test_campo_preenchido_marca_rotulo_e_escapa_valor():
    html = app.pdf_campo("Pai", "João & Filhos <do bairro>")
    assert app.PDF_COR_ROTULO in html  # rótulo apagado, valor em destaque
    assert "João &amp; Filhos &lt;do bairro&gt;" in html


def test_linha_junta_apenas_os_campos_existentes():
    linha = app.pdf_linha_de_campos(
        [app.pdf_campo("Nasc.", "01/01/1990"), app.pdf_campo("Tel.", ""), ""]
    )
    assert "01/01/1990" in linha
    # Campo único não pode arrastar separador solto para a linha.
    assert app.PDF_SEPARADOR not in linha

    dois = app.pdf_linha_de_campos(
        [app.pdf_campo("Nasc.", "01/01/1990"), app.pdf_campo("Tel.", "6399998888")]
    )
    assert dois.count(app.PDF_SEPARADOR) == 1


# ---------------------------------------------------------------------------
# Documento gerado
# ---------------------------------------------------------------------------
def test_ficha_completa_sai_no_pdf(logged_client):
    criar_casa(logged_client)
    criar_paciente(
        logged_client,
        nome="MARIA DA FICHA COMPLETA",
        nome_mae="Terezinha da Ficha",
        observacao="Acamada, visita quinzenal",
        condicoes_saude=["diabetes"],
    )
    texto = ficha_lida(logged_client)
    assert "MARIA DA FICHA COMPLETA" in texto
    assert "Mãe Terezinha da Ficha" in texto
    assert "Observação Acamada, visita quinzenal" in texto
    assert "Condições Tem diabetes" in texto


def test_cadastro_vazio_nao_imprime_filiacao(logged_client):
    """Cadastro que entrou limpo (importação): sem pai, sem mãe, sem telefone —
    o relatório mostra o que existe e cala o resto."""
    criar_casa(logged_client)
    criar_paciente(
        logged_client,
        nome="PACIENTE SEM FILIACAO",
        cpf="",
        telefone="",
        data_nascimento="",
        sexo="",
        nome_pai="",
        nome_mae="",
    )
    texto = ficha_lida(logged_client)
    assert "PACIENTE SEM FILIACAO" in texto
    # Nenhum rótulo de campo em branco na ficha.
    for rotulo in ("Pai ", "Mãe ", "Nasc.", "Tel.", "Observação", "Condições"):
        assert rotulo not in texto


def test_cabecalho_da_casa_conta_pacientes(logged_client):
    criar_casa(logged_client)
    assert "Sem pacientes" in ficha_lida(logged_client)

    criar_paciente(logged_client, nome="UNICO MORADOR")
    texto = ficha_lida(logged_client)
    assert "1 paciente" in texto
    assert "Sem pacientes" not in texto

    criar_paciente(logged_client, nome="SEGUNDO MORADOR", cpf="98765432100")
    assert "2 pacientes" in ficha_lida(logged_client)


def test_casa_longa_repete_o_cabecalho_ao_virar_a_pagina(logged_client):
    """Casa com muita gente atravessa a quebra: o cabeçalho volta no topo da
    página seguinte para a lista nunca ficar órfã de endereço."""
    criar_casa(logged_client, endereco="Rua da Casa Cheia, 500")
    for indice in range(40):
        criar_paciente(
            logged_client,
            nome=f"MORADOR {indice:02d} DA CASA CHEIA",
            cpf=str(10000000000 + indice),  # CPF repetido é recusado no cadastro
            observacao="Observação de campo para dar altura à ficha do paciente.",
        )
    texto = ficha_lida(logged_client)
    assert "40 pacientes" in texto
    assert "MORADOR 39 DA CASA CHEIA" in texto
    assert texto.count("Rua da Casa Cheia, 500") >= 2


# ---------------------------------------------------------------------------
# Quadra no cabeçalho da casa
# ---------------------------------------------------------------------------
def test_cabecalho_da_casa_diz_a_quadra(logged_client):
    """A numeração de casa recomeça a cada quadra, então o número sozinho não
    identifica casa nenhuma: o cabeçalho tem de carregar a quadra junto."""
    criar_quadra(logged_client, numero="13")
    criar_casa(logged_client, endereco="Rua das Flores, 42", numero="42", quadra_id="1")
    criar_paciente(logged_client, nome="MORADOR DA QUADRA TREZE")

    texto = ficha_lida(logged_client)
    assert "Casa Nº 42 · Quadra Nº 13" in texto


def test_casa_sem_quadra_diz_no_cabecalho(logged_client):
    criar_casa(logged_client, endereco="Rua B, 9", numero="9")
    criar_paciente(logged_client, nome="MORADOR SEM QUADRA")
    assert "Casa Nº 9 · Sem quadra" in ficha_lida(logged_client)


def test_mesmo_numero_de_casa_em_quadras_diferentes_se_distingue(logged_client):
    """Duas casas Nº 7 em quadras diferentes é o caso normal do território —
    no PDF elas não podem virar a mesma linha."""
    criar_quadra(logged_client, numero="1")
    criar_quadra(logged_client, numero="2")
    criar_casa(logged_client, endereco="Rua A, 7", numero="7", quadra_id="1")
    criar_casa(logged_client, endereco="Rua B, 7", numero="7", quadra_id="2")
    criar_paciente(logged_client, casa_id=1, nome="MORADOR DA UM", cpf="11111111111")
    criar_paciente(logged_client, casa_id=2, nome="MORADOR DA DOIS", cpf="22222222222")

    texto = ficha_lida(logged_client)
    assert "Casa Nº 7 · Quadra Nº 1" in texto
    assert "Casa Nº 7 · Quadra Nº 2" in texto


def test_quadra_volta_no_cabecalho_ao_virar_a_pagina(logged_client):
    """O título do capítulo sai uma vez por quadra; o cabeçalho da casa é que
    se repete na quebra. Sem a quadra nele, quem vira a folha perde de vista
    em que quadra está lendo."""
    criar_quadra(logged_client, numero="13")
    criar_casa(logged_client, endereco="Rua da Casa Cheia, 500", numero="42", quadra_id="1")
    for indice in range(40):
        criar_paciente(
            logged_client,
            nome=f"MORADOR {indice:02d} DA CASA CHEIA",
            cpf=str(10000000000 + indice),
            observacao="Observação de campo para dar altura à ficha do paciente.",
        )

    texto = ficha_lida(logged_client)
    assert texto.count("Casa Nº 42 · Quadra Nº 13") >= 2
