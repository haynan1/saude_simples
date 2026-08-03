"""Pacientes sem casa vinculada (ex.: importados do e-SUS ainda não alocados).
Nenhuma tela ou relatório pode quebrar com eles — nem omiti-los."""
import db
from tests.conftest import criar_casa, criar_paciente, texto_pdf


def _inserir_sem_casa(nome="Paciente Sem Casa", cpf="999.888.777-66"):
    conn = db.get_db_connection()
    conn.execute(
        "INSERT INTO pacientes (casa_id, nome, cpf, data_nascimento, sexo)"
        " VALUES (NULL, ?, ?, '1950-01-01', 'Masculino')",
        (nome, cpf),
    )
    conn.commit()
    conn.close()


def test_pdf_geral_lista_pacientes_sem_casa(logged_client):
    """Regressão do relatório em branco: só pacientes sem casa no sistema —
    o PDF precisa listá-los na seção 'Sem casa definida'."""
    _inserir_sem_casa("PACIENTE INVISIVEL")
    resp = logged_client.get("/exportar/pdf")
    assert resp.status_code == 200
    texto = texto_pdf(resp.data)
    assert "PACIENTE INVISIVEL" in texto
    assert "Sem casa definida" in texto


def test_pdf_filtrado_inclui_sem_casa(logged_client):
    _inserir_sem_casa("IDOSO SEM CASA")  # 1950 → idoso
    resp = logged_client.get("/exportar/pdf?filtrar=1&grupos=idosos")
    assert resp.status_code == 200
    assert "IDOSO SEM CASA" in texto_pdf(resp.data)


def test_pdf_mistura_casas_e_sem_casa(logged_client):
    criar_casa(logged_client)
    criar_paciente(logged_client, nome="MORADOR DA CASA", cpf="11111111111")
    _inserir_sem_casa("AINDA SEM CASA")
    texto = texto_pdf(logged_client.get("/exportar/pdf").data)
    assert "MORADOR DA CASA" in texto
    assert "AINDA SEM CASA" in texto
    assert "Sem casa definida" in texto


def test_editar_paciente_sem_casa_funciona(logged_client):
    _inserir_sem_casa()
    assert logged_client.get("/paciente/1/editar").status_code == 200

    resp = logged_client.post("/paciente/1/editar", data={"nome": "NOME CORRIGIDO"})
    assert resp.status_code == 302
    assert "/pacientes" in resp.headers["Location"]

    conn = db.get_db_connection()
    nome = conn.execute("SELECT nome FROM pacientes WHERE id = 1").fetchone()["nome"]
    conn.close()
    assert nome == "NOME CORRIGIDO"


def test_excluir_paciente_sem_casa_funciona(logged_client):
    _inserir_sem_casa()
    resp = logged_client.post("/paciente/1/excluir")
    assert resp.status_code == 302
    assert "/pacientes" in resp.headers["Location"]

    conn = db.get_db_connection()
    total = conn.execute("SELECT COUNT(*) AS c FROM pacientes").fetchone()["c"]
    conn.close()
    assert total == 0


def test_busca_do_painel_com_paciente_sem_casa(logged_client):
    _inserir_sem_casa("Fulano Procurado")
    resp = logged_client.get("/?busca=Fulano Procurado")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "Fulano Procurado" in body
    assert "Definir casa" in body  # CTA leva à página Pacientes


def test_status_e_obito_de_paciente_sem_casa(logged_client):
    _inserir_sem_casa()
    logged_client.post("/paciente/1/status", data={"status": "obito"})
    conn = db.get_db_connection()
    status = conn.execute("SELECT status FROM pacientes WHERE id = 1").fetchone()["status"]
    conn.close()
    assert status == "obito"
    # Fora das contagens; PDF geral continua válido.
    resp = logged_client.get("/exportar/pdf")
    assert resp.status_code == 200
    assert "Paciente Sem Casa" not in texto_pdf(resp.data)
