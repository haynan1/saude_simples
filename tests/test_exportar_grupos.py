"""Exportação por grupos demográficos — união entre grupos, interseção com
comorbidades, whitelist server-side e PDF válido em recorte vazio."""
from tests.conftest import criar_casa, criar_paciente


def _semear_territorio(logged_client):
    """Casa 1: idoso c/ diabetes, idosa sem condição, criança, sem-sexo.
    Casa 2: jovem c/ diabetes. Total: 5 pacientes ativos."""
    criar_casa(logged_client)
    criar_casa(logged_client, endereco="Rua B, 2", numero="2")
    criar_paciente(
        logged_client, nome="Idoso Com Diabetes", cpf="11111111111",
        data_nascimento="1950-01-01", sexo="Masculino", condicoes_saude=["diabetes"],
    )
    criar_paciente(
        logged_client, nome="Idosa Sem Condicao", cpf="22222222222",
        data_nascimento="1948-06-15", sexo="Feminino",
    )
    criar_paciente(
        logged_client, nome="Crianca Da Casa", cpf="33333333333",
        data_nascimento="2020-03-10", sexo="Feminino",
    )
    criar_paciente(
        logged_client, nome="Sem Sexo Informado", cpf="44444444444",
        data_nascimento="1990-01-01", sexo="",
    )
    criar_paciente(
        logged_client, casa_id=2, nome="Jovem Com Diabetes", cpf="55555555555",
        data_nascimento="2000-05-05", sexo="Masculino", condicoes_saude=["diabetes"],
    )


def test_recorte_criancas_0_a_2_separado(logged_client):
    """'Crianças 0 a 2 anos' é um recorte próprio, independente do 'até 11':
    o bebê entra nos dois; a criança de mais idade só no grupo amplo."""
    from datetime import datetime

    from tests.test_sem_casa import _texto_pdf

    criar_casa(logged_client)
    criar_paciente(
        logged_client, nome="Bebe Do Territorio", cpf="66666666666",
        data_nascimento=datetime.now().strftime("%Y-01-10"), sexo="Feminino",
    )
    criar_paciente(
        logged_client, nome="Crianca De Sete Anos", cpf="77777777777",
        data_nascimento="2019-03-10", sexo="Masculino",
    )
    data = logged_client.get("/exportar/preview?grupos=criancas_0_2").get_json()
    assert data["stats"]["total_pacientes"] == 1
    amplo = logged_client.get("/exportar/preview?grupos=criancas").get_json()
    assert amplo["stats"]["total_pacientes"] == 2
    # O PDF do recorte lista o nome — é assim que se sabe QUEM compõe o número.
    texto = _texto_pdf(
        logged_client.get("/exportar/pdf?filtrar=1&grupos=criancas_0_2").data
    )
    assert b"Bebe Do Territorio" in texto
    assert b"Crianca De Sete Anos" not in texto


def test_uniao_de_grupos(logged_client):
    _semear_territorio(logged_client)
    data = logged_client.get("/exportar/preview?grupos=idosos&grupos=criancas").get_json()
    assert data["modo"] == "filtrado"
    # Idoso + Idosa + Criança — quem pertence a QUALQUER grupo entra.
    assert data["stats"]["total_pacientes"] == 3
    totais = {g["codigo"]: g["total"] for g in data["grupos"]}
    assert totais == {"idosos": 2, "criancas": 1}


def test_interseccao_grupo_com_comorbidade(logged_client):
    _semear_territorio(logged_client)
    data = logged_client.get("/exportar/preview?grupos=idosos&condicoes=diabetes").get_json()
    # Idoso E diabetes: só o Idoso Com Diabetes. A Idosa (sem condição) e o
    # Jovem (não idoso) ficam fora.
    assert data["stats"]["total_pacientes"] == 1
    assert data["stats"]["idosos"] == 1


def test_sexo_nao_informado_fora_de_homens_e_mulheres(logged_client):
    _semear_territorio(logged_client)
    homens = logged_client.get("/exportar/preview?grupos=homens").get_json()
    mulheres = logged_client.get("/exportar/preview?grupos=mulheres").get_json()
    ambos = logged_client.get("/exportar/preview?grupos=homens&grupos=mulheres").get_json()
    assert homens["stats"]["total_pacientes"] == 2
    assert mulheres["stats"]["total_pacientes"] == 2
    assert ambos["stats"]["total_pacientes"] == 4  # "Sem Sexo Informado" fora


def test_casas_apenas_com_pacientes_no_recorte(logged_client):
    _semear_territorio(logged_client)
    # Idosos moram só na casa 1 — a casa 2 sai do relatório e das contagens.
    data = logged_client.get("/exportar/preview?grupos=idosos").get_json()
    assert data["stats"]["total_casas"] == 1
    assert data["stats"]["casas_vazias"] == 0


def test_grupo_vazio_gera_pdf_valido(logged_client):
    _semear_territorio(logged_client)  # nenhuma gestante no território
    preview = logged_client.get("/exportar/preview?grupos=gestantes").get_json()
    assert preview["stats"]["total_pacientes"] == 0

    resp = logged_client.get("/exportar/pdf?filtrar=1&grupos=gestantes")
    assert resp.status_code == 200
    assert resp.data.startswith(b"%PDF")
    assert "relatorio_gestantes.pdf" in resp.headers["Content-Disposition"]


def test_whitelist_de_grupos_invalidos(logged_client):
    _semear_territorio(logged_client)
    # Valor fora da whitelist é ignorado — comportamento geral, sem erro.
    data = logged_client.get("/exportar/preview?grupos=hacker&grupos=../etc").get_json()
    assert data["modo"] == "geral"
    assert data["stats"]["total_pacientes"] == 5

    resp = logged_client.get("/exportar/pdf?grupos=hacker")
    assert resp.status_code == 200
    assert "relatorio_pacientes_por_casa.pdf" in resp.headers["Content-Disposition"]


def test_pdf_com_grupos_e_comorbidades_nomeia_o_recorte(logged_client):
    _semear_territorio(logged_client)
    resp = logged_client.get("/exportar/pdf?filtrar=1&grupos=idosos&grupos=gestantes&condicoes=diabetes")
    assert resp.status_code == 200
    assert resp.data.startswith(b"%PDF")
    assert "relatorio_idosos_gestantes_comorbidades.pdf" in resp.headers["Content-Disposition"]


def test_grupos_ignoram_pacientes_inativos(logged_client):
    _semear_territorio(logged_client)
    logged_client.post("/paciente/1/status", data={"status": "mudou_se"})  # Idoso Com Diabetes
    data = logged_client.get("/exportar/preview?grupos=idosos").get_json()
    assert data["stats"]["total_pacientes"] == 1  # só a Idosa continua


def test_recorte_e_stats_usam_a_mesma_regua(logged_client):
    """Fonte única de verdade: o total de um recorte por grupo é exatamente a
    contagem que as stats gerais mostram para aquele grupo."""
    _semear_territorio(logged_client)
    geral = logged_client.get("/exportar/preview").get_json()["stats"]
    for grupo, chave in [("idosos", "idosos"), ("criancas", "criancas"),
                         ("gestantes", "gestantes"), ("homens", "homens"),
                         ("mulheres", "mulheres")]:
        recorte = logged_client.get(f"/exportar/preview?grupos={grupo}").get_json()
        assert recorte["stats"]["total_pacientes"] == geral[chave], grupo