"""Define ou redefine a senha de acesso ao Saúde Simples.

Use isto se esqueceu a senha ou está configurando o sistema numa máquina nova.
Não precisa saber a senha atual — quem roda este script já tem acesso ao
computador onde os dados ficam, então esse é o nível de confiança necessário.

Uso: python resetar_senha.py
"""

import getpass
import sqlite3
import sys

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

from werkzeug.security import generate_password_hash

from db import MIN_PASSWORD_LENGTH, criar_backup, init_db, set_senha_hash


def pedir_nova_senha():
    while True:
        nova = getpass.getpass("Nova senha: ")
        if len(nova) < MIN_PASSWORD_LENGTH:
            print(f"A senha deve ter pelo menos {MIN_PASSWORD_LENGTH} caracteres.")
            continue

        confirmacao = getpass.getpass("Confirme a nova senha: ")
        if nova != confirmacao:
            print("As senhas não coincidem. Tente novamente.")
            continue

        return nova


def main():
    print("Saúde Simples — definir/redefinir senha de acesso")
    print()

    init_db()

    resposta = input("Isso substitui a senha atual (se houver). Continuar? [s/N] ").strip().lower()
    if resposta != "s":
        print("Cancelado.")
        return

    nova_senha = pedir_nova_senha()

    try:
        criar_backup("antes_resetar_senha")
    except (sqlite3.Error, OSError) as exc:
        print(f"Aviso: não foi possível criar backup de segurança ({exc}). Continuando mesmo assim.")

    set_senha_hash(generate_password_hash(nova_senha))
    print()
    print("Senha definida com sucesso. Já pode fazer login no sistema.")


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        print()
        print("Cancelado.")
        sys.exit(1)
