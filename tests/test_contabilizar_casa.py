"""Casa fora do relatório.

A marcação tira a casa E os moradores dela de toda contagem do território
(painel, perfil epidemiológico, exportações), sem esconder nem apagar nada:
a casa continua na lista, aberta e editável. É recorte de relatório, não
exclusão.
"""
import db
from tests.conftest import criar_casa, criar_paciente, criar_quadra
from tests.test_sem_casa import _texto_pdf


def _contabilizar(client, casa_id, ligado):
    return client.post(
        f"/casa/{casa_id}/contabilizar",
        data={"contabilizar": "1" if ligado else "0", "next": "/"},
    )


def _valor_contabilizar(casa_id):
    conn = db.get_db_connection()
    linha = conn.execute("SELECT contabilizar FROM casas WHERE id = ?", (casa_id,)).fetchone()
    conn.close()
    return linha["contabilizar"]


def _seed(client):
    """Duas casas com um morador cada — a segunda sairá do relatório."""
    criar_quadra(client)
    criar_casa(client, endereco="Rua Dentro, 1", numero="1")
    criar_casa(client, endereco="Rua Fora, 2", numero="2")
    criar_paciente(client, casa_id=1, nome="MORADOR CONTADO", cpf="11111111111",
                   sexo="Feminino", condicoes_saude=["hipertensao"])
    criar_paciente(client, casa_id=2, nome="MORADOR NAO CONTADO", cpf="22222222222",
                   sexo="Masculino", condicoes_saude=["diabetes"])


# ---------------------------------------------------------------------------
# Coluna e migração
# ---------------------------------------------------------------------------
def test_casa_nova_nasce_contabilizada(logged_client):
    criar_casa(logged_client)
    assert _valor_contabilizar(1) == 1


def test_migracao_adiciona_coluna_contabilizando_o_legado(logged_client):
    """Banco anterior à coluna: init_db precisa adicioná-la já contabilizando
    tudo. Zerar em silêncio o relatório de quem atualiza seria o pior erro
    possível — por isso a tabela aqui é recriada SEM a coluna, para o
    ALTER TABLE ser de fato exercitado."""
    conn = db.get_db_connection()
    conn.execute("DROP TABLE casas")
    conn.execute(
        """
        CREATE TABLE casas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quadra_id INTEGER,
            numero_casa INTEGER,
            endereco TEXT NOT NULL
        )
        """
    )
    conn.execute("INSERT INTO casas (endereco, numero_casa) VALUES ('Legado', 9)")
    conn.commit()
    colunas = [r["name"] for r in conn.execute("PRAGMA table_info(casas)")]
    conn.close()
    assert "contabilizar" not in colunas  # o cenário legado existe de verdade

    db.init_db()

    conn = db.get_db_connection()
    linha = conn.execute("SELECT contabilizar FROM casas WHERE endereco = 'Legado'").fetchone()
    conn.close()
    assert linha["contabilizar"] == 1

    # E a casa legada continua entrando nas contagens.
    from app import build_dashboard_stats, carregar_dados_relatorio

    casas, pacientes = carregar_dados_relatorio()
    assert build_dashboard_stats(casas, pacientes)["total_casas"] == 1


# ---------------------------------------------------------------------------
# Alternar a marcação
# ---------------------------------------------------------------------------
def test_alternar_tira_e_devolve_ao_relatorio(logged_client):
    criar_casa(logged_client)

    assert _contabilizar(logged_client, 1, False).status_code == 302
    assert _valor_contabilizar(1) == 0

    assert _contabilizar(logged_client, 1, True).status_code == 302
    assert _valor_contabilizar(1) == 1


def test_alternar_exige_login(client):
    resp = client.post("/casa/1/contabilizar", data={"contabilizar": "0"})
    assert resp.status_code == 302
    assert "/login" in resp.headers["Location"]


def test_alternar_casa_inexistente_nao_quebra(logged_client):
    resp = logged_client.post("/casa/999/contabilizar", data={"contabilizar": "0"})
    assert resp.status_code == 302


def test_alternar_nao_permite_open_redirect(logged_client):
    """O campo `next` volta para a tela de origem — não pode virar trampolim
    para fora do sistema."""
    criar_casa(logged_client)
    resp = logged_client.post(
        "/casa/1/contabilizar",
        data={"contabilizar": "0", "next": "https://evil.example.com"},
    )
    assert resp.status_code == 302
    assert "evil.example.com" not in resp.headers["Location"]

    resp = logged_client.post(
        "/casa/1/contabilizar",
        data={"contabilizar": "1", "next": "//evil.example.com"},
    )
    assert "evil.example.com" not in resp.headers["Location"]


def test_alternar_exige_csrf(app, logged_client):
    app.config["WTF_CSRF_ENABLED"] = True
    try:
        criar_casa(logged_client)
        resp = logged_client.post("/casa/1/contabilizar", data={"contabilizar": "0"})
        assert resp.status_code == 400
    finally:
        app.config["WTF_CSRF_ENABLED"] = False


def test_editar_casa_salva_a_marcacao(logged_client):
    criar_quadra(logged_client)
    criar_casa(logged_client)

    # Checkbox ausente no POST = desmarcada = fora do relatório.
    logged_client.post("/casa/1/editar", data={
        "endereco": "Rua A, 1", "numero_casa": "1", "quadra_id": "1",
        "tipo_imovel": "domicilio",
    })
    assert _valor_contabilizar(1) == 0

    logged_client.post("/casa/1/editar", data={
        "endereco": "Rua A, 1", "numero_casa": "1", "quadra_id": "1",
        "tipo_imovel": "domicilio", "contabilizar": "1",
    })
    assert _valor_contabilizar(1) == 1


# ---------------------------------------------------------------------------
# Efeito nas contagens
# ---------------------------------------------------------------------------
def test_painel_ignora_casa_fora_do_relatorio(logged_client):
    _seed(logged_client)
    from app import build_dashboard_stats, carregar_dados_relatorio

    casas, pacientes = carregar_dados_relatorio()
    assert build_dashboard_stats(casas, pacientes)["total_pacientes"] == 2

    _contabilizar(logged_client, 2, False)

    casas, pacientes = carregar_dados_relatorio()
    stats = build_dashboard_stats(casas, pacientes)
    assert stats["total_pacientes"] == 1
    assert stats["total_casas"] == 1
    assert [nome for nome in (p["nome"] for p in pacientes)] == ["MORADOR CONTADO"]


def test_perfil_epidemiologico_ignora_casa_fora_do_relatorio(logged_client):
    _seed(logged_client)
    from app import calcular_perfil_epidemiologico

    antes = calcular_perfil_epidemiologico()
    assert antes["familias"] == 2
    assert antes["diabeticos"]["m"] == 1

    _contabilizar(logged_client, 2, False)

    depois = calcular_perfil_epidemiologico()
    assert depois["familias"] == 1
    assert depois["diabeticos"]["m"] == 0
    assert depois["hipertensos"]["f"] == 1  # o morador contado continua


def test_pdf_nao_lista_casa_fora_do_relatorio(logged_client):
    _seed(logged_client)
    _contabilizar(logged_client, 2, False)

    texto = _texto_pdf(logged_client.get("/exportar/pdf").data)
    assert b"MORADOR CONTADO" in texto
    assert b"MORADOR NAO CONTADO" not in texto


def test_paciente_sem_casa_continua_contando(logged_client):
    """A marcação é da casa. Quem não tem casa não pode ser varrido junto."""
    from app import build_dashboard_stats, carregar_dados_relatorio

    conn = db.get_db_connection()
    conn.execute(
        "INSERT INTO pacientes (casa_id, nome, cpf, data_nascimento, sexo)"
        " VALUES (NULL, 'SEM CASA', '333', '1950-01-01', 'Masculino')"
    )
    conn.commit()
    conn.close()

    casas, pacientes = carregar_dados_relatorio()
    assert build_dashboard_stats(casas, pacientes)["total_pacientes"] == 1


# ---------------------------------------------------------------------------
# Visibilidade e filtro
# ---------------------------------------------------------------------------
def test_casa_fora_do_relatorio_continua_visivel(logged_client):
    _seed(logged_client)
    _contabilizar(logged_client, 2, False)

    corpo = logged_client.get("/").data.decode()
    assert "Rua Fora, 2" in corpo
    assert "fora do relat" in corpo.lower()

    assert logged_client.get("/casa/2").status_code == 200


def test_filtro_por_contabilizacao(logged_client):
    _seed(logged_client)
    _contabilizar(logged_client, 2, False)

    dentro = logged_client.get("/?contabilizar=1").data.decode()
    assert "Rua Dentro, 1" in dentro
    assert "Rua Fora, 2" not in dentro

    fora = logged_client.get("/?contabilizar=0").data.decode()
    assert "Rua Fora, 2" in fora
    assert "Rua Dentro, 1" not in fora

    todas = logged_client.get("/").data.decode()
    assert "Rua Dentro, 1" in todas and "Rua Fora, 2" in todas


def test_filtro_invalido_e_ignorado(logged_client):
    _seed(logged_client)
    corpo = logged_client.get("/?contabilizar=banana").data.decode()
    assert "Rua Dentro, 1" in corpo and "Rua Fora, 2" in corpo
