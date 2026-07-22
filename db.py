import logging
import os
import secrets
import shutil
import sqlite3
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("saude_simples")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
INSTANCE_DIR = os.path.join(BASE_DIR, "instance")
DATABASE = os.path.join(INSTANCE_DIR, "database.db")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
BACKUP_RETENTION = 50
MIN_PASSWORD_LENGTH = 10

# O banco morava na raiz do projeto até a v2. Instalações existentes são
# migradas automaticamente no primeiro boot — dado nunca se perde por upgrade.
_LEGACY_DATABASE = os.path.join(BASE_DIR, "database.db")


def _migrar_banco_legado():
    if os.path.exists(DATABASE) or not os.path.exists(_LEGACY_DATABASE):
        return

    os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
    shutil.move(_LEGACY_DATABASE, DATABASE)
    # Journals do WAL acompanham o banco; sem eles, transações não consolidadas
    # da última sessão seriam perdidas.
    for sufixo in ("-wal", "-shm"):
        legado = _LEGACY_DATABASE + sufixo
        if os.path.exists(legado):
            shutil.move(legado, DATABASE + sufixo)
    logger.info("Banco de dados migrado para %s", DATABASE)


def get_db_connection():
    os.makedirs(os.path.dirname(DATABASE), exist_ok=True)
    _migrar_banco_legado()
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # WAL: leituras não bloqueiam escritas — o servidor (waitress) é multi-thread.
    # busy_timeout: escrita concorrente espera em vez de falhar com "database is locked".
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def podar_backups_antigos():
    if not os.path.isdir(BACKUP_DIR):
        return

    arquivos = sorted(
        nome for nome in os.listdir(BACKUP_DIR) if nome.startswith("database_") and nome.endswith(".db")
    )
    excedentes = arquivos[:-BACKUP_RETENTION] if len(arquivos) > BACKUP_RETENTION else []
    for nome in excedentes:
        os.remove(os.path.join(BACKUP_DIR, nome))


def criar_backup(motivo):
    if not os.path.exists(DATABASE):
        return

    os.makedirs(BACKUP_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destino = os.path.join(BACKUP_DIR, f"database_{timestamp}_{motivo}.db")

    origem = sqlite3.connect(DATABASE)
    try:
        copia = sqlite3.connect(destino)
        try:
            origem.backup(copia)
        finally:
            copia.close()
    finally:
        origem.close()

    logger.info("Backup criado (%s): %s", motivo, destino)
    podar_backups_antigos()


def listar_backups():
    """Backups disponíveis, do mais recente ao mais antigo."""
    if not os.path.isdir(BACKUP_DIR):
        return []

    backups = []
    for nome in os.listdir(BACKUP_DIR):
        if not (nome.startswith("database_") and nome.endswith(".db")):
            continue
        caminho = os.path.join(BACKUP_DIR, nome)
        try:
            stat = os.stat(caminho)
        except OSError:
            continue
        # database_YYYYMMDD_HHMMSS_micros_motivo.db → motivo legível
        miolo = nome[len("database_"):-len(".db")]
        partes = miolo.split("_", 3)
        motivo = partes[3].replace("_", " ") if len(partes) == 4 else ""
        backups.append(
            {
                "nome": nome,
                "tamanho": stat.st_size,
                "modificado": datetime.fromtimestamp(stat.st_mtime),
                "motivo": motivo,
            }
        )

    backups.sort(key=lambda item: item["nome"], reverse=True)
    return backups


def backup_valido(nome):
    """Só aceita nomes que existem de fato no diretório de backups — nunca um
    caminho vindo do cliente. Bloqueia path traversal por construção."""
    if not os.path.isdir(BACKUP_DIR):
        return False
    return nome in os.listdir(BACKUP_DIR) and nome.startswith("database_") and nome.endswith(".db")


def caminho_backup(nome):
    if not backup_valido(nome):
        raise ValueError(f"Backup inexistente ou nome inválido: {nome!r}")
    return os.path.join(BACKUP_DIR, nome)


def exportar_snapshot(destino):
    """Grava em `destino` um snapshot consistente do banco (API de backup do
    SQLite — inclui transações do WAL, ao contrário de copiar o arquivo cru)."""
    origem = get_db_connection()
    try:
        copia = sqlite3.connect(destino)
        try:
            origem.backup(copia)
        finally:
            copia.close()
    finally:
        origem.close()


def _sobrescrever_banco_com(caminho_origem):
    """Substitui o conteúdo do banco ativo pelo do arquivo dado, via API de
    backup (transacional — leitores concorrentes nunca veem estado parcial)."""
    origem = sqlite3.connect(caminho_origem)
    try:
        destino = get_db_connection()
        try:
            origem.backup(destino)
        finally:
            destino.close()
    finally:
        origem.close()


def restaurar_backup(nome):
    """Restaura um backup por cima do banco ativo. O chamador é responsável
    por criar backup do estado atual ANTES de chamar."""
    _sobrescrever_banco_com(caminho_backup(nome))
    logger.info("Banco restaurado a partir do backup %s", nome)


class BancoInvalido(ValueError):
    """Arquivo enviado não é um banco do Saúde Simples utilizável."""


_TABELAS_OBRIGATORIAS = {"quadras", "casas", "pacientes"}


def validar_banco_importado(caminho):
    """Valida um candidato a importação: assinatura SQLite, integridade e
    esquema mínimo. Levanta BancoInvalido com mensagem legível."""
    try:
        with open(caminho, "rb") as arquivo:
            cabecalho = arquivo.read(16)
    except OSError as exc:
        raise BancoInvalido("Não foi possível ler o arquivo enviado.") from exc

    if cabecalho != b"SQLite format 3\x00":
        raise BancoInvalido("O arquivo enviado não é um banco de dados SQLite.")

    try:
        conn = sqlite3.connect(caminho)
        try:
            resultado = conn.execute("PRAGMA integrity_check").fetchone()
            if not resultado or resultado[0] != "ok":
                raise BancoInvalido("O banco enviado está corrompido (falhou na verificação de integridade).")
            tabelas = {
                linha[0]
                for linha in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
        finally:
            conn.close()
    except sqlite3.DatabaseError as exc:
        raise BancoInvalido("O arquivo enviado não pôde ser aberto como banco SQLite.") from exc

    faltando = _TABELAS_OBRIGATORIAS - tabelas
    if faltando:
        raise BancoInvalido(
            "O banco enviado não parece ser do Saúde Simples — faltam as tabelas: "
            + ", ".join(sorted(faltando))
            + "."
        )


def importar_banco(caminho_origem):
    """Substitui o banco ativo pelo arquivo validado, preservando a senha de
    acesso ATUAL — importar dados de outra máquina nunca tranca o operador
    para fora. O chamador cria backup do estado atual antes."""
    validar_banco_importado(caminho_origem)

    senha_atual = get_senha_hash()
    _sobrescrever_banco_com(caminho_origem)
    # Reaplica migrações/índices sobre o banco importado (pode vir de versão antiga).
    init_db()
    if senha_atual:
        set_senha_hash(senha_atual)
    logger.info("Banco importado com sucesso (senha de acesso local preservada).")


def init_db():
    conn = get_db_connection()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS quadras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero_quadra INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS casas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            quadra_id INTEGER,
            numero_casa INTEGER,
            endereco TEXT NOT NULL,
            FOREIGN KEY(quadra_id) REFERENCES quadras(id) ON DELETE SET NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pacientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            casa_id INTEGER,
            nome TEXT NOT NULL,
            cpf TEXT,
            telefone TEXT,
            data_nascimento TEXT,
            sexo TEXT,
            nome_pai TEXT,
            nome_mae TEXT,
            condicoes_saude TEXT,
            observacao TEXT,
            FOREIGN KEY(casa_id) REFERENCES casas(id) ON DELETE CASCADE
        )
        """
    )
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(pacientes)").fetchall()]
    if "telefone" not in columns:
        conn.execute("ALTER TABLE pacientes ADD COLUMN telefone TEXT")
    if "sexo" not in columns:
        conn.execute("ALTER TABLE pacientes ADD COLUMN sexo TEXT")
    if "condicoes_saude" not in columns:
        conn.execute("ALTER TABLE pacientes ADD COLUMN condicoes_saude TEXT")
    casa_columns = [row["name"] for row in conn.execute("PRAGMA table_info(casas)").fetchall()]
    if "quadra_id" not in casa_columns:
        conn.execute("ALTER TABLE casas ADD COLUMN quadra_id INTEGER")
    if "tipo_imovel" not in casa_columns:
        # Imóveis existentes eram todos domicílios — o default preenche o legado.
        conn.execute("ALTER TABLE casas ADD COLUMN tipo_imovel TEXT NOT NULL DEFAULT 'domicilio'")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS configuracao (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            senha_hash TEXT NOT NULL
        )
        """
    )
    # SQLite não indexa FKs automaticamente — sem estes índices, os JOINs do
    # painel e o ON DELETE CASCADE viram full scans conforme a base cresce.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_casas_quadra_id ON casas(quadra_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pacientes_casa_id ON pacientes(casa_id)")
    conn.commit()
    conn.close()


def senha_configurada():
    conn = get_db_connection()
    existe = conn.execute("SELECT 1 FROM configuracao WHERE id = 1").fetchone() is not None
    conn.close()
    return existe


def garantir_senha_inicial(bootstrap_hash=None):
    """Aplica o hash do ambiente (setups automatizados) se ainda não houver senha.

    Retorna True se há senha configurada ao final. Sem senha e sem hash, o
    servidor sobe mesmo assim: o assistente /setup assume a partir daí.
    """
    if senha_configurada():
        return True
    if bootstrap_hash:
        set_senha_hash(bootstrap_hash)
        return True
    return False


# ---------------------------------------------------------------------------
# Código de segurança do primeiro acesso (/setup)
#
# Propriedade central: só quem lê o terminal (ou o arquivo em instance/) da
# máquina onde o servidor roda conhece o código — estar na mesma rede não
# basta para se tornar dono do sistema.
# ---------------------------------------------------------------------------
SETUP_TOKEN_PATH = os.path.join(INSTANCE_DIR, "setup_token")

# Sem 0/O/1/I: o código é feito para ser lido no terminal e digitado sem
# ambiguidade (ou ditado por telefone).
_SETUP_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _gerar_codigo_legivel():
    blocos = ["".join(secrets.choice(_SETUP_ALPHABET) for _ in range(4)) for _ in range(2)]
    return "-".join(blocos)


def _normalizar_codigo(codigo):
    return "".join(char for char in str(codigo or "").upper() if char.isalnum())


def ensure_setup_token():
    """Gera (ou reaproveita) o código de configuração inicial, persistido em
    instance/setup_token com permissão restrita ao dono."""
    os.makedirs(INSTANCE_DIR, exist_ok=True)

    if os.path.exists(SETUP_TOKEN_PATH):
        with open(SETUP_TOKEN_PATH, encoding="utf-8") as arquivo:
            codigo = arquivo.read().strip()
        if _normalizar_codigo(codigo):
            return codigo

    codigo = _gerar_codigo_legivel()
    with open(SETUP_TOKEN_PATH, "w", encoding="utf-8") as arquivo:
        arquivo.write(codigo + "\n")
    os.chmod(SETUP_TOKEN_PATH, 0o600)
    return codigo


def verify_setup_token(candidato):
    """Compara em tempo constante, tolerando hífen/minúsculas na digitação."""
    if not os.path.exists(SETUP_TOKEN_PATH):
        return False
    with open(SETUP_TOKEN_PATH, encoding="utf-8") as arquivo:
        esperado = _normalizar_codigo(arquivo.read())
    recebido = _normalizar_codigo(candidato)
    if not esperado or not recebido:
        return False
    return secrets.compare_digest(esperado, recebido)


def clear_setup_token():
    try:
        os.remove(SETUP_TOKEN_PATH)
    except FileNotFoundError:
        pass


def get_senha_hash():
    conn = get_db_connection()
    row = conn.execute("SELECT senha_hash FROM configuracao WHERE id = 1").fetchone()
    conn.close()
    return row["senha_hash"] if row else None


def set_senha_hash(novo_hash):
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO configuracao (id, senha_hash) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET senha_hash = excluded.senha_hash",
        (novo_hash,),
    )
    conn.commit()
    conn.close()
