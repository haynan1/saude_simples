# -*- coding: utf-8 -*-
"""Peças compartilhadas pelos scripts da importação do caderno de campo.

Existe para que normalização de nome, validação de CPF e conversão de data
tenham UMA implementação só. Antes estavam copiadas em três arquivos, e uma
regra de casamento de paciente que diverge entre a carga e a correção é o tipo
de bug que só aparece depois, no dado errado.
"""

import os
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime

# scripts/importacao_pdf/comum.py -> raiz do projeto
RAIZ = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BANCO = os.path.join(RAIZ, "instance", "database.db")

# Saída padrão em temp/: o JSON da extração carrega nome, CPF e filiação de
# centenas de pessoas. temp/ está no .gitignore — dado de paciente não entra
# no repositório em hipótese nenhuma.
SAIDA_PADRAO = os.path.join(RAIZ, "temp")

PDF_PADRAO = os.path.join(
    SAIDA_PADRAO, "LISTA DE TODOS OS DADOS DO PESSOAL DA RESIDENCIA.pdf"
)


def conectar(banco=None):
    conn = sqlite3.connect(banco or BANCO)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def stdout_utf8():
    """O console do Windows quebra em acento; a saída destes scripts é toda em
    português e cheia deles."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except AttributeError:  # Python < 3.7
        pass


# ---------------------------------------------------------------------------
# Normalização
# ---------------------------------------------------------------------------
def sem_acento(valor):
    valor = unicodedata.normalize("NFKD", str(valor or ""))
    return "".join(c for c in valor if not unicodedata.combining(c))


def chave(valor):
    """Forma canônica de um rótulo: sem acento, minúsculo, espaços colapsados."""
    return re.sub(r"\s+", " ", sem_acento(valor)).strip().lower()


def norm(valor):
    """Forma canônica de um NOME para comparação: sem acento, maiúsculo e com
    espaços internos colapsados.

    Propositalmente MAIS estrito que `app.texto_normalizado`, que não mexe em
    espaço: o caderno foi digitado à mão e tem "MARIA  APARECIDA" com espaço
    duplo. Sem colapsar, a mesma pessoa entraria duas vezes. A diferença é
    segura porque erra para o lado de reconhecer duplicata, nunca de criar.
    Ver tests/test_scripts_importacao.py."""
    return re.sub(r"\s+", " ", sem_acento(valor)).strip().upper()


def digitos(valor):
    return "".join(c for c in str(valor or "") if c.isdigit())


RE_PARENTESE = re.compile(r"\s*\(([^)]*)\)\s*$")


def nome_e_nota(nome):
    """'SERGIO ... (MORA NA CASA DE CIMA)' -> ('SERGIO ...', 'MORA NA CASA DE CIMA').

    O parêntese no fim do nome é recado do agente, não parte do nome — vai para
    a observação em vez de sujar o cadastro."""
    nome = re.sub(r"\s+", " ", str(nome or "")).strip()
    m = RE_PARENTESE.search(nome)
    if m and len(m.group(1)) > 3:
        return nome[: m.start()].strip(), m.group(1).strip()
    return nome, ""


def nome_limpo(nome):
    return nome_e_nota(nome)[0]


def data_iso(valor):
    """'02-06-1957' e '02/06/1957' -> '1957-06-02'. Data impossível vira ''."""
    valor = re.sub(r"[-.]", "/", str(valor or "").strip())
    try:
        dt = datetime.strptime(valor, "%d/%m/%Y")
    except ValueError:
        return ""
    return dt.strftime("%Y-%m-%d") if 1900 <= dt.year <= 2026 else ""


def cpf_valido(cpf):
    """Confere os dois dígitos verificadores. O caderno tem CPF digitado errado,
    e gravar sem checar esconderia o erro."""
    d = digitos(cpf)
    if len(d) != 11 or len(set(d)) == 1:
        return False
    for corte in (9, 10):
        soma = sum(int(d[i]) * (corte + 1 - i) for i in range(corte))
        if (soma * 10) % 11 % 10 != int(d[corte]):
            return False
    return True


# ---------------------------------------------------------------------------
# Formatação — cópias fiéis de app.py
#
# Importar o módulo app levantaria o Flask inteiro (e exigiria SECRET_KEY) só
# para usar duas funções puras. As cópias existem para o dado gravado por script
# ficar EXATAMENTE no formato que o app escreve pelo formulário; se elas
# divergirem, o CPF gravado aqui deixa de casar com a busca de lá.
# tests/test_scripts_importacao.py trava as duas contra as originais.
# ---------------------------------------------------------------------------
def formatar_cpf_ou_cns(valor):
    d = digitos(valor)[:15]
    if len(d) <= 11:
        if len(d) <= 3:
            return d
        if len(d) <= 6:
            return "%s.%s" % (d[:3], d[3:])
        if len(d) <= 9:
            return "%s.%s.%s" % (d[:3], d[3:6], d[6:])
        return "%s.%s.%s-%s" % (d[:3], d[3:6], d[6:9], d[9:])
    partes = [d[:3], d[3:7], d[7:11], d[11:15]]
    return " ".join(p for p in partes if p)


def formatar_telefone(valor):
    d = digitos(valor)[:11]
    if len(d) <= 2:
        return d
    if len(d) <= 6:
        return "(%s) %s" % (d[:2], d[2:])
    if len(d) <= 10:
        return "(%s) %s-%s" % (d[:2], d[2:6], d[6:])
    return "(%s) %s-%s" % (d[:2], d[2:7], d[7:])


# ---------------------------------------------------------------------------
# Casamento de paciente do PDF com o banco
# ---------------------------------------------------------------------------
def indexar_pacientes(conn):
    """Índices de busca do banco: por documento e por (nome, nascimento)."""
    linhas = [dict(r) for r in conn.execute("SELECT * FROM pacientes")]
    por_documento = {digitos(p["cpf"]): p for p in linhas if len(digitos(p["cpf"])) == 11}
    por_nome = {}
    for p in linhas:
        por_nome.setdefault((norm(p["nome"]), p["data_nascimento"] or ""), p)
    return linhas, por_documento, por_nome


def encontrar_paciente(pessoa, por_documento, por_nome):
    """Regra única de identidade: CPF/CNS primeiro, depois nome + nascimento.

    A mesma em toda a importação — carga, reativação e correção precisam
    concordar sobre quem é quem, senão uma cria o que a outra não acha."""
    nome = nome_limpo(pessoa["nome"])
    documento = digitos(pessoa.get("cpf", "")) or digitos(pessoa.get("cns", ""))
    if len(documento) == 11:
        achado = por_documento.get(documento)
        if achado is not None:
            return nome, achado
    return nome, por_nome.get((norm(nome), data_iso(pessoa.get("data_nascimento", ""))))


def confirmar_gravacao(conn, gravar, rotulo="GRAVADO"):
    if gravar:
        conn.commit()
        print("\n>>> %s" % rotulo)
    else:
        conn.rollback()
        print("\n>>> SIMULAÇÃO — nada foi gravado. Use --gravar para efetivar.")


def backup(motivo, banco=None):
    """Usa o mesmo mecanismo de backup do app, para o arquivo aparecer na tela
    de Banco junto com os demais.

    Aponta db.DATABASE para o banco em uso antes de copiar: sem isso, rodar um
    script com --banco faria backup do banco de produção e alteraria outro —
    a pior combinação possível."""
    sys.path.insert(0, RAIZ)
    import db as db_modulo

    if banco:
        db_modulo.DATABASE = banco
    db_modulo.criar_backup(motivo)
