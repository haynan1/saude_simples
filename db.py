import logging
import os
import sqlite3
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("saude_simples")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "database.db")
BACKUP_DIR = os.path.join(BASE_DIR, "backups")
BACKUP_RETENTION = 50
MIN_PASSWORD_LENGTH = 10


def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS configuracao (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            senha_hash TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def garantir_senha_inicial(bootstrap_hash=None):
    conn = get_db_connection()
    existe = conn.execute("SELECT 1 FROM configuracao WHERE id = 1").fetchone() is not None
    if not existe:
        if not bootstrap_hash:
            conn.close()
            raise RuntimeError(
                "Nenhuma senha configurada ainda. Rode `python resetar_senha.py` para definir a "
                "senha inicial (recomendado), ou defina SAUDE_SIMPLES_PASSWORD_HASH no .env "
                "(veja .env.example) antes de iniciar o servidor."
            )
        conn.execute("INSERT INTO configuracao (id, senha_hash) VALUES (1, ?)", (bootstrap_hash,))
        conn.commit()
    conn.close()


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
