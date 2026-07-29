"""Imóvel inativo: está na área, não é acompanhado pela equipe.

Sai de toda contagem e de todo relatório — junto com os moradores — sem sair
do cadastro. É o meio-termo entre manter e excluir, e é reversível.
"""
import re

import db
from tests.conftest import criar_casa, criar_paciente, texto_pdf


def indicador_do_painel(client, rotulo):
    """Número que o painel mostra no card de um indicador.

    A afirmação passa pela rota, não por uma cópia da consulta: um filtro que
    a `index()` esquecesse de aplicar tem que aparecer aqui."""
    html = client.get("/").get_data(as_text=True)
    achado = re.search(
        rf">{re.escape(rotulo)}</p>\s*<p[^>]*>\s*([\d/ ]+?)\s*</p>", html
    )
    assert achado, f"indicador “{rotulo}” não encontrado no painel"
    return achado.group(1)


def _inativar(client, casa_id=1, motivo="Lar de idosos acompanhado por outra equipe"):
    return client.post(
        f"/casa/{casa_id}/situacao", data={"status": "inativa", "motivo": motivo}
    )


def _reativar(client, casa_id=1):
    return client.post(f"/casa/{casa_id}/situacao", data={"status": "ativa"})


def _status_no_banco(casa_id=1):
    conn = db.get_db_connection()
    row = conn.execute(
        "SELECT status, motivo_inativacao FROM casas WHERE id = ?", (casa_id,)
    ).fetchone()
    conn.close()
    return row


def _territorio(logged_client):
    """Duas casas com um morador idoso cada — uma vira o 'lar', a outra fica."""
    criar_casa(logged_client, endereco="Rua A, 1", numero="1")
    criar_casa(logged_client, endereco="Rua B, 2", numero="2")
    criar_paciente(
        logged_client, casa_id=1, nome="MORADOR DO LAR", cpf="11111111111",
        data_nascimento="1940-05-10", sexo="Feminino", condicoes_saude=["hipertensao"],
    )
    criar_paciente(
        logged_client, casa_id=2, nome="MORADOR DA AREA", cpf="22222222222",
        data_nascimento="1945-05-10", sexo="Masculino", condicoes_saude=["hipertensao"],
    )


# ---------------------------------------------------------------------------
# Efeito nas contagens
# ---------------------------------------------------------------------------
def test_inativar_tira_casa_e_moradores_do_painel(logged_client):
    _territorio(logged_client)
    assert indicador_do_painel(logged_client, "Casas") == "2"
    assert indicador_do_painel(logged_client, "Pacientes") == "2"
    assert indicador_do_painel(logged_client, "Idosos 60+") == "2"

    _inativar(logged_client)

    # A casa some do indicador — e o morador dela vai junto.
    assert indicador_do_painel(logged_client, "Casas") == "1"
    assert indicador_do_painel(logged_client, "Pacientes") == "1"
    assert indicador_do_painel(logged_client, "Idosos 60+") == "1"
    assert indicador_do_painel(logged_client, "Homens / Mulheres") == "1 / 0"


def test_inativar_tira_a_casa_e_os_moradores_do_pdf(logged_client):
    _territorio(logged_client)
    _inativar(logged_client)

    texto = texto_pdf(logged_client.get("/exportar/pdf").data)
    assert "MORADOR DA AREA" in texto
    assert "MORADOR DO LAR" not in texto
    assert "Rua A, 1" not in texto


def test_inativar_tira_do_perfil_epidemiologico(logged_client):
    import app as app_module

    _territorio(logged_client)
    antes = app_module.calcular_perfil_epidemiologico()
    assert antes["familias"] == 2
    assert antes["pessoas"] == {"f": 1, "m": 1}

    _inativar(logged_client)
    depois = app_module.calcular_perfil_epidemiologico()
    assert depois["familias"] == 1
    assert depois["pessoas"] == {"f": 0, "m": 1}
    assert depois["hipertensos"] == {"f": 0, "m": 1}


def test_reativar_devolve_tudo(logged_client):
    import app as app_module

    _territorio(logged_client)
    _inativar(logged_client)
    _reativar(logged_client)

    perfil = app_module.calcular_perfil_epidemiologico()
    assert perfil["familias"] == 2
    assert perfil["pessoas"] == {"f": 1, "m": 1}
    assert "MORADOR DO LAR" in texto_pdf(logged_client.get("/exportar/pdf").data)


def test_paciente_sem_casa_continua_contando(logged_client):
    """O LEFT JOIN não pode derrubar quem ainda não tem casa vinculada."""
    import app as app_module

    conn = db.get_db_connection()
    conn.execute(
        "INSERT INTO pacientes (casa_id, nome, cpf, data_nascimento, sexo)"
        " VALUES (NULL, 'SEM CASA AINDA', '33333333333', '1950-01-01', 'Feminino')"
    )
    conn.commit()
    conn.close()

    perfil = app_module.calcular_perfil_epidemiologico()
    assert perfil["pessoas"] == {"f": 1, "m": 0}
    assert "SEM CASA AINDA" in texto_pdf(logged_client.get("/exportar/pdf").data)


# ---------------------------------------------------------------------------
# Cadastro preservado e reversível
# ---------------------------------------------------------------------------
def test_casa_inativa_continua_na_lista_e_no_painel_da_casa(logged_client):
    _territorio(logged_client)
    _inativar(logged_client)

    painel = logged_client.get("/").get_data(as_text=True)
    assert "Rua A, 1" in painel  # é pela lista que se reativa
    assert "inativa" in painel

    casa = logged_client.get("/casa/1").get_data(as_text=True)
    assert "MORADOR DO LAR" in casa  # os moradores continuam ali
    assert "Imóvel inativo" in casa
    assert "Reativar imóvel" in casa
    assert "Lar de idosos acompanhado por outra equipe" in casa


def test_preview_da_exportacao_ignora_o_imovel_inativo(logged_client):
    """A página Exportar mostra o tamanho do recorte antes de gerar o PDF —
    o número tem que bater com o documento."""
    _territorio(logged_client)
    _inativar(logged_client)

    dados = logged_client.get("/exportar/preview").get_json()
    assert dados["stats"]["total_casas"] == 1
    assert dados["stats"]["total_pacientes"] == 1


def test_moradores_de_casa_inativa_continuam_no_cadastro(logged_client):
    """Fora das contagens não é fora do sistema: a lista de pacientes é o
    cadastro, e o morador precisa continuar localizável ali."""
    _territorio(logged_client)
    _inativar(logged_client)

    lista = logged_client.get("/pacientes").get_data(as_text=True)
    assert "MORADOR DO LAR" in lista

    busca = logged_client.get("/?busca=MORADOR DO LAR").get_data(as_text=True)
    assert "MORADOR DO LAR" in busca


def test_casa_inativa_segue_como_destino_de_transferencia_marcado(logged_client):
    """Mudar-se para o lar que a equipe não acompanha é um destino real — e é
    a transferência que tira o morador das contagens sem apagar o cadastro."""
    _territorio(logged_client)
    _inativar(logged_client)

    corpo = logged_client.get("/casa/2").get_data(as_text=True)
    assert "(imóvel inativo)" in corpo

    logged_client.post("/paciente/2/transferir", data={"casa_destino_id": "1"})
    dados = logged_client.get("/exportar/preview").get_json()
    assert dados["stats"]["total_pacientes"] == 0  # os dois estão no imóvel inativo


def test_motivo_e_gravado_e_limpo_na_reativacao(logged_client):
    criar_casa(logged_client)
    _inativar(logged_client, motivo="Não acompanho mais")
    row = _status_no_banco()
    assert row["status"] == "inativa"
    assert row["motivo_inativacao"] == "Não acompanho mais"

    _reativar(logged_client)
    row = _status_no_banco()
    assert row["status"] == "ativa"
    assert row["motivo_inativacao"] is None


def test_motivo_e_opcional(logged_client):
    criar_casa(logged_client)
    _inativar(logged_client, motivo="   ")
    row = _status_no_banco()
    assert row["status"] == "inativa"
    assert row["motivo_inativacao"] is None


def test_situacao_invalida_nao_altera_nada(logged_client):
    criar_casa(logged_client)
    resp = logged_client.post("/casa/1/situacao", data={"status": "excluida"})
    assert resp.status_code == 302
    assert _status_no_banco()["status"] == "ativa"


def test_casa_inexistente_volta_para_o_painel(logged_client):
    resp = logged_client.post("/casa/99/situacao", data={"status": "inativa"})
    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/")


def test_banco_de_versao_anterior_migra_com_a_casa_ativa(tmp_path, monkeypatch):
    """Banco gravado antes desta versão não tem as colunas novas. A migração
    precisa criá-las sem perder dado, e a casa que já existia entra ATIVA —
    ninguém some do relatório por causa de uma atualização."""
    import sqlite3

    antigo = tmp_path / "instance" / "database.db"
    antigo.parent.mkdir(parents=True)
    conn = sqlite3.connect(antigo)
    conn.execute(
        "CREATE TABLE casas (id INTEGER PRIMARY KEY AUTOINCREMENT, quadra_id INTEGER,"
        " numero_casa INTEGER, endereco TEXT NOT NULL)"
    )
    conn.execute("INSERT INTO casas (numero_casa, endereco) VALUES (7, 'Rua Antiga, 7')")
    conn.commit()
    conn.close()

    monkeypatch.setattr(db, "DATABASE", str(antigo))
    db.init_db()

    conn = db.get_db_connection()
    casa = conn.execute("SELECT * FROM casas WHERE numero_casa = 7").fetchone()
    conn.close()
    assert casa["endereco"] == "Rua Antiga, 7"
    assert casa["status"] == "ativa"
    assert casa["localizacao"] is None


def test_lar_de_idosos_e_um_tipo_de_imovel(logged_client):
    """O tipo existe, e imóvel coletivo sem morador não vira 'casa vazia'."""
    import app as app_module

    assert "lar_idosos" in app_module.TIPOS_IMOVEL_POR_CODIGO
    assert app_module.tipo_imovel_label("lar_idosos") == "Lar de Idosos"
    assert "lar_idosos" not in app_module.TIPOS_IMOVEL_RESIDENCIAIS

    logged_client.post(
        "/casa/nova",
        data={"endereco": "Lar Vicentino", "numero_casa": "10", "quadra_id": "",
              "tipo_imovel": "lar_idosos"},
    )
    painel = logged_client.get("/").get_data(as_text=True)
    assert indicador_do_painel(logged_client, "Casas") == "1"
    assert "0 vazia(s)" in painel
    assert "Lar de Idosos" in painel
