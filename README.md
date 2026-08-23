# JS Escadas V2

Sistema web de gestão comercial para a JS Escadas.

## Recursos
- Login administrativo
- Dashboard
- Clientes e histórico
- Demandas e funil
- Orçamentos com cálculo, aprovação e impressão
- Agenda de serviços
- Financeiro com receitas, despesas e contas a receber
- Atalho para WhatsApp
- SQLite, sem configuração de banco externo

## Instalação
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
python app.py
```
Abra http://127.0.0.1:5000

Login inicial: admin@jsescadas.com / 1234

**Troque a senha e a SECRET_KEY antes de colocar em produção.**
