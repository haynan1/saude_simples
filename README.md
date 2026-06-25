# Saúde Simples

Sistema local de cadastro de quadras, casas e pacientes para uma unidade de saúde, com exportação de relatórios em PDF. Não depende de internet nem de serviços externos — roda inteiramente na máquina onde é instalado.

## Requisitos

- Python 3.9 ou superior
- Windows, Linux ou macOS

## Instalação (primeira vez nessa máquina)

```bash
# 1. Criar e ativar o ambiente virtual
python -m venv venv
venv\Scripts\activate          # Windows
source venv/bin/activate       # Linux/macOS

# 2. Instalar as dependências
pip install -r requirements.txt

# 3. Criar o arquivo de configuração
copy .env.example .env         # Windows
cp .env.example .env           # Linux/macOS
```

Abra o `.env` e defina a `SAUDE_SIMPLES_SECRET_KEY`:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

Cole o valor gerado em `SAUDE_SIMPLES_SECRET_KEY=` no `.env`. Esse valor não precisa (e não deve) ser o mesmo em outra instalação.

## Definir a senha de acesso

```bash
python resetar_senha.py
```

Ele vai pedir pra você digitar a nova senha duas vezes (mínimo 10 caracteres). Não precisa editar o `.env` nem gerar hash manualmente — é só rodar e seguir o prompt.

## Rodar o sistema

```bash
python app.py
```

Por padrão abre em `http://127.0.0.1:5001`. Acesse esse endereço no navegador e entre com a senha definida no passo anterior.

## Esqueci a senha / vou usar numa máquina nova

Mesmo comando dos dois casos:

```bash
python resetar_senha.py
```

Não é preciso saber a senha atual — quem roda esse comando já tem acesso direto à máquina onde os dados ficam, então esse já é o nível de confiança necessário (o mesmo de quem poderia abrir o arquivo `.env`). O script:

1. Pede confirmação antes de qualquer mudança.
2. Pede a nova senha duas vezes, validando o tamanho mínimo.
3. Cria um backup do banco de dados antes de aplicar a mudança.
4. Grava a nova senha.

Depois disso é só fazer login normalmente com a nova senha.

## Trocar a senha já logado

Dentro do sistema, clique no ícone de chave (🔑) no menu superior. Pede a senha atual + a nova senha — diferente do `resetar_senha.py`, que é pra quando você **não** sabe a senha atual.

## Backups automáticos

O sistema guarda cópias de segurança do banco de dados em `backups/`, criadas automaticamente:

- Toda vez que o servidor inicia.
- Antes de excluir uma quadra, casa ou paciente.
- Antes de redefinir a senha pelo `resetar_senha.py`.

São mantidos os 50 backups mais recentes; os mais antigos são removidos automaticamente. Se uma exclusão importante der problema, basta restaurar o `database.db` a partir do arquivo mais recente em `backups/` (renomeie para `database.db` com o servidor parado).

## Variáveis de ambiente (`.env`)

| Variável | Obrigatória | Descrição |
|---|---|---|
| `SAUDE_SIMPLES_SECRET_KEY` | Sim | Chave de sessão. Gere uma por instalação, nunca reaproveite. |
| `SAUDE_SIMPLES_PASSWORD_HASH` | Não | Só para setups automatizados que preferem definir a senha via `.env` em vez de `resetar_senha.py`. Na maioria dos casos, ignore esta variável. |
| `SAUDE_SIMPLES_DEBUG` | Não | `true` usa o servidor de desenvolvimento do Flask; `false` (padrão) usa waitress, recomendado mesmo em uso local. |
| `SAUDE_SIMPLES_HOST` | Não | Padrão `127.0.0.1` (só acessível na própria máquina). |
| `SAUDE_SIMPLES_PORT` | Não | Padrão `5001`. |

O `.env` nunca deve ser commitado — já está no `.gitignore`.

## Estrutura

```
app.py              # rotas, regras de negócio, geração de PDF
db.py               # banco de dados, senha e backups (sem depender do Flask)
resetar_senha.py    # ferramenta de recuperação/definição de senha
templates/          # páginas HTML
static/             # CSS e JS
database.db         # banco SQLite (gerado automaticamente, não commitado)
backups/            # cópias de segurança automáticas (não commitado)
```

## Segurança

- A senha de acesso fica como hash (nunca em texto plano) no banco de dados.
- Login tem limite de 5 tentativas por minuto por IP.
- Sessão expira em 8 horas.
- Todas as rotas, exceto login, exigem autenticação.
- `database.db`, `backups/` e `.env` ficam fora do controle de versão.
