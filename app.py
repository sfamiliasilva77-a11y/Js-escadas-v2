import os, sqlite3
from datetime import date, datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, abort

BASE=os.path.dirname(os.path.abspath(__file__))
DB=os.path.join(BASE,'jsescadas.db')
app=Flask(__name__)
app.secret_key=os.environ.get('SECRET_KEY','js-escadas-v2-change-this-secret')

SERVICE_TYPES=['Escada pré-moldada','Montagem / desmontagem','Remoção de escada','Abertura de vão na laje','Manutenção','Churrasqueira pré-moldada','Outro']
STATUSES=['Novo','Orçamento','Aguardando resposta','Aprovado','Agendado','Em execução','Concluído','Cancelado']

SCHEMA='''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,email TEXT UNIQUE NOT NULL,password TEXT NOT NULL,name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,phone TEXT,email TEXT,city TEXT,address TEXT,notes TEXT,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS demands(id INTEGER PRIMARY KEY AUTOINCREMENT,client_id INTEGER NOT NULL,service_type TEXT NOT NULL,estimated_value REAL DEFAULT 0,measurements TEXT,description TEXT,status TEXT NOT NULL,created_at TEXT NOT NULL,FOREIGN KEY(client_id) REFERENCES clients(id));
CREATE TABLE IF NOT EXISTS quotes(id INTEGER PRIMARY KEY AUTOINCREMENT,demand_id INTEGER NOT NULL,number TEXT UNIQUE NOT NULL,subtotal REAL NOT NULL,discount REAL DEFAULT 0,total REAL NOT NULL,description TEXT,terms TEXT,status TEXT NOT NULL,created_at TEXT NOT NULL,approved_at TEXT,FOREIGN KEY(demand_id) REFERENCES demands(id));
CREATE TABLE IF NOT EXISTS services(id INTEGER PRIMARY KEY AUTOINCREMENT,demand_id INTEGER NOT NULL,date TEXT NOT NULL,time TEXT,team TEXT,address TEXT,notes TEXT,status TEXT NOT NULL,FOREIGN KEY(demand_id) REFERENCES demands(id));
CREATE TABLE IF NOT EXISTS transactions(id INTEGER PRIMARY KEY AUTOINCREMENT,client_id INTEGER,quote_id INTEGER,kind TEXT NOT NULL,description TEXT,amount REAL NOT NULL,due_date TEXT,paid_date TEXT,status TEXT NOT NULL,FOREIGN KEY(client_id) REFERENCES clients(id),FOREIGN KEY(quote_id) REFERENCES quotes(id));
'''

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c

def init_db():
    c=db(); c.executescript(SCHEMA)
    if not c.execute('SELECT 1 FROM users LIMIT 1').fetchone(): c.execute('INSERT INTO users(email,password,name) VALUES(?,?,?)',('admin@jsescadas.com','1234','Administrador'))
    c.commit(); c.close()

def login_required(f):
    @wraps(f)
    def w(*a,**kw):
        if 'user_id' not in session: return redirect(url_for('login',next=request.path))
        return f(*a,**kw)
    return w

def money(v): return f'R$ {float(v or 0):,.2f}'.replace(',','X').replace('.',',').replace('X','.')
app.jinja_env.filters['money']=money

def now(): return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def row(sql,args=()):
    c=db(); r=c.execute(sql,args).fetchone(); c.close(); return r

def rows(sql,args=()):
    c=db(); r=c.execute(sql,args).fetchall(); c.close(); return r

@app.context_processor
def inject(): return {'today':date.today().isoformat(),'service_types':SERVICE_TYPES}

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        r=row('SELECT * FROM users WHERE email=? AND password=?',(request.form['email'].strip().lower(),request.form['password']))
        if r:
            session['user_id']=r['id']; session['user_name']=r['name']; return redirect(request.args.get('next') or url_for('dashboard'))
        flash('E-mail ou senha inválidos.','danger')
    return render_template('login.html',title='Login')
@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    c=db()
    stats={
      'clients':c.execute('SELECT COUNT(*) n FROM clients').fetchone()['n'],
      'new':c.execute("SELECT COUNT(*) n FROM demands WHERE status='Novo'").fetchone()['n'],
      'waiting':c.execute("SELECT COUNT(*) n FROM demands WHERE status='Aguardando resposta'").fetchone()['n'],
      'scheduled':c.execute("SELECT COUNT(*) n FROM services WHERE date>=date('now') AND status NOT IN ('Concluído','Cancelado')").fetchone()['n'],
      'received':c.execute("SELECT COALESCE(SUM(amount),0) v FROM transactions WHERE kind='receita' AND status='Pago'").fetchone()['v'],
      'pending':c.execute("SELECT COALESCE(SUM(amount),0) v FROM transactions WHERE kind='receita' AND status!='Pago'").fetchone()['v']}
    upcoming=c.execute('''SELECT s.*,c.name client,d.service_type FROM services s JOIN demands d ON d.id=s.demand_id JOIN clients c ON c.id=d.client_id WHERE s.date>=date('now') ORDER BY s.date,s.time LIMIT 8''').fetchall()
    pipeline=c.execute("SELECT status,COUNT(*) n FROM demands GROUP BY status ORDER BY n DESC").fetchall(); c.close()
    return render_template('dashboard.html',title='Painel',s=stats,upcoming=upcoming,pipeline=pipeline)

@app.route('/clients')
@login_required
def clients():
    q=request.args.get('q','').strip(); args=[]; sql='SELECT * FROM clients'
    if q: sql+=' WHERE name LIKE ? OR phone LIKE ? OR city LIKE ?'; args=[f'%{q}%',f'%{q}%',f'%{q}%']
    sql+=' ORDER BY name'; return render_template('clients.html',title='Clientes',rows=rows(sql,args),q=q)
@app.route('/clients/new',methods=['GET','POST'])
@login_required
def client_new():
    if request.method=='POST':
        c=db(); c.execute('INSERT INTO clients(name,phone,email,city,address,notes,created_at) VALUES(?,?,?,?,?,?,?)',(request.form['name'],request.form.get('phone'),request.form.get('email'),request.form.get('city'),request.form.get('address'),request.form.get('notes'),now())); c.commit(); c.close(); flash('Cliente cadastrado.','success'); return redirect(url_for('clients'))
    return render_template('form_client.html',title='Novo cliente')
@app.route('/clients/<int:id>')
@login_required
def client_detail(id):
    client=row('SELECT * FROM clients WHERE id=?',(id,));
    if not client: abort(404)
    demands=rows('SELECT * FROM demands WHERE client_id=? ORDER BY id DESC',(id,)); tx=rows('SELECT * FROM transactions WHERE client_id=? ORDER BY id DESC',(id,)); return render_template('client_detail.html',title=client['name'],client=client,demands=demands,tx=tx)

@app.route('/demands')
@login_required
def demands():
    q=request.args.get('q','').strip(); status=request.args.get('status',''); args=[]
    sql='''SELECT d.*,c.name client,c.phone FROM demands d JOIN clients c ON c.id=d.client_id WHERE 1=1'''
    if q: sql+=' AND (c.name LIKE ? OR d.service_type LIKE ?)'; args += [f'%{q}%',f'%{q}%']
    if status: sql+=' AND d.status=?'; args.append(status)
    sql+=' ORDER BY d.id DESC'; return render_template('demands.html',title='Demandas',rows=rows(sql,args),q=q,status=status,statuses=STATUSES)
@app.route('/demands/new',methods=['GET','POST'])
@login_required
def demand_new():
    clients=rows('SELECT * FROM clients ORDER BY name')
    if request.method=='POST':
        c=db(); c.execute('INSERT INTO demands(client_id,service_type,estimated_value,measurements,description,status,created_at) VALUES(?,?,?,?,?,?,?)',(request.form['client_id'],request.form['service_type'],float(request.form.get('value') or 0),request.form.get('measurements'),request.form.get('description'),request.form.get('status') or 'Novo',now())); c.commit(); c.close(); flash('Demanda criada.','success'); return redirect(url_for('demands'))
    return render_template('form_demand.html',title='Nova demanda',clients=clients)
@app.route('/demands/<int:id>/status',methods=['POST'])
@login_required
def demand_status(id):
    st=request.form['status'];
    if st not in STATUSES: abort(400)
    c=db(); c.execute('UPDATE demands SET status=? WHERE id=?',(st,id)); c.commit(); c.close(); flash('Status atualizado.','success'); return redirect(request.referrer or url_for('demands'))

@app.route('/quotes')
@login_required
def quotes():
    r=rows('''SELECT q.*,d.service_type,c.name client FROM quotes q JOIN demands d ON d.id=q.demand_id JOIN clients c ON c.id=d.client_id ORDER BY q.id DESC''')
    return render_template('quotes.html',title='Orçamentos',rows=r)
@app.route('/quotes/new',methods=['GET','POST'])
@login_required
def quote_new():
    demands=rows("SELECT d.*,c.name client FROM demands d JOIN clients c ON c.id=d.client_id WHERE d.status!='Cancelado' ORDER BY d.id DESC")
    if request.method=='POST':
        sub=float(request.form['subtotal']); disc=float(request.form.get('discount') or 0); total=max(sub-disc,0)
        c=db(); c.execute('INSERT INTO quotes(demand_id,number,subtotal,discount,total,description,terms,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(request.form['demand_id'],'TEMP',sub,disc,total,request.form.get('description'),request.form.get('terms'), 'Enviado',now())); qid=c.execute('SELECT last_insert_rowid()').fetchone()[0]; number=f'ORC-{datetime.now().year}-{qid:04d}'; c.execute('UPDATE quotes SET number=? WHERE id=?',(number,qid)); c.execute("UPDATE demands SET status='Orçamento' WHERE id=?",(request.form['demand_id'],)); c.commit(); c.close(); flash(f'Orçamento {number} criado.','success'); return redirect(url_for('quote_detail',id=qid))
    return render_template('form_quote.html',title='Novo orçamento',demands=demands)
@app.route('/quotes/<int:id>')
@login_required
def quote_detail(id):
    q=row('''SELECT q.*,d.service_type,d.measurements,d.description demand_description,c.* FROM quotes q JOIN demands d ON d.id=q.demand_id JOIN clients c ON c.id=d.client_id WHERE q.id=?''',(id,));
    if not q: abort(404)
    return render_template('quote_detail.html',title=q['number'],q=q)
@app.route('/quotes/<int:id>/whatsapp')
@login_required
def quote_whatsapp(id):
    q=row('''SELECT q.*,d.service_type,d.measurements,d.description demand_description,c.name,c.phone,c.email,c.city,c.address
             FROM quotes q JOIN demands d ON d.id=q.demand_id JOIN clients c ON c.id=d.client_id
             WHERE q.id=?''',(id,))
    if not q: abort(404)
    phone=''.join(ch for ch in (q['phone'] or '') if ch.isdigit())
    if phone.startswith('55'):
        pass
    elif len(phone) in (10,11):
        phone='55'+phone
    if not phone:
        flash('O cliente não possui um número de WhatsApp cadastrado.','warning')
        return redirect(url_for('quote_detail',id=id))
    description=q['description'] or q['demand_description'] or 'Serviço conforme vistoria e medidas.'
    terms=q['terms'] or 'Condições conforme orçamento.'
    msg=(
        f"Olá, {q['name']}! Tudo bem?\n\n"
        f"Aqui é da *JS Escadas*. Conforme solicitado, segue o orçamento *{q['number']}*.\n\n"
        f"🪜 *Serviço:* {q['service_type']}\n"
        f"💰 *Valor total:* {money(q['total'])}\n"
        f"📄 *Descrição:* {description}\n\n"
        f"💳 *Condições:* {terms}\n\n"
        "Ficamos à disposição para qualquer dúvida. Se estiver de acordo, podemos prosseguir com o agendamento.\n\n"
        "*JS Escadas*"
    )
    from urllib.parse import quote
    return redirect('https://wa.me/'+phone+'?text='+quote(msg))

@app.route('/quotes/<int:id>/approve',methods=['POST'])
@login_required
def quote_approve(id):
    q=row('SELECT * FROM quotes WHERE id=?',(id,));
    if not q: abort(404)
    c=db(); c.execute("UPDATE quotes SET status='Aprovado',approved_at=? WHERE id=?",(now(),id)); c.execute("UPDATE demands SET status='Aprovado' WHERE id=?",(q['demand_id'],)); c.execute('INSERT INTO transactions(client_id,quote_id,kind,description,amount,due_date,status) SELECT d.client_id,?,\'receita\',?,q.total,date(\'now\'),\'Pendente\' FROM quotes q JOIN demands d ON d.id=q.demand_id WHERE q.id=?',(id,f'Orçamento {q["number"]}',id)); c.commit(); c.close(); flash('Orçamento aprovado e lançado como a receber.','success'); return redirect(url_for('quote_detail',id=id))

@app.route('/services')
@login_required
def services():
    r=rows('''SELECT s.*,c.name client,d.service_type FROM services s JOIN demands d ON d.id=s.demand_id JOIN clients c ON c.id=d.client_id ORDER BY s.date,s.time'''); return render_template('services.html',title='Serviços',rows=r)
@app.route('/services/new',methods=['GET','POST'])
@login_required
def service_new():
    demands=rows("SELECT d.*,c.name client FROM demands d JOIN clients c ON c.id=d.client_id WHERE d.status='Aprovado' ORDER BY d.id DESC")
    if request.method=='POST':
        did=request.form['demand_id']; d=row('SELECT * FROM demands WHERE id=?',(did,));
        c=db(); c.execute('INSERT INTO services(demand_id,date,time,team,address,notes,status) VALUES(?,?,?,?,?,?,?)',(did,request.form['date'],request.form.get('time'),request.form.get('team'),request.form.get('address'),request.form.get('notes'),'Agendado')); c.execute("UPDATE demands SET status='Agendado' WHERE id=?",(did,)); c.commit(); c.close(); flash('Serviço agendado.','success'); return redirect(url_for('services'))
    return render_template('form_service.html',title='Agendar serviço',demands=demands)
@app.route('/services/<int:id>/status',methods=['POST'])
@login_required
def service_status(id):
    st=request.form['status']; c=db(); c.execute('UPDATE services SET status=? WHERE id=?',(st,id)); c.commit(); c.close(); return redirect(request.referrer or url_for('services'))

@app.route('/finance')
@login_required
def finance():
    r=rows('SELECT t.*,c.name client,q.number quote_number FROM transactions t LEFT JOIN clients c ON c.id=t.client_id LEFT JOIN quotes q ON q.id=t.quote_id ORDER BY t.id DESC')
    sums={}
    for k,sql in [('received',"SELECT COALESCE(SUM(amount),0) FROM transactions WHERE kind='receita' AND status='Pago'"),('pending',"SELECT COALESCE(SUM(amount),0) FROM transactions WHERE kind='receita' AND status!='Pago'"),('expenses',"SELECT COALESCE(SUM(amount),0) FROM transactions WHERE kind='despesa'" )]: sums[k]=row(sql)[0]
    sums['profit']=sums['received']-sums['expenses']; return render_template('finance.html',title='Financeiro',rows=r,**sums)
@app.route('/finance/new',methods=['POST'])
@login_required
def finance_new():
    c=db(); c.execute('INSERT INTO transactions(client_id,kind,description,amount,due_date,paid_date,status) VALUES(?,?,?,?,?,?,?)',(request.form.get('client_id') or None,request.form['kind'],request.form.get('description'),float(request.form['amount']),request.form.get('due_date'),request.form.get('paid_date') if request.form.get('status')=='Pago' else None,request.form.get('status','Pendente'))); c.commit(); c.close(); flash('Lançamento salvo.','success'); return redirect(url_for('finance'))
@app.route('/finance/<int:id>/pay',methods=['POST'])
@login_required
def finance_pay(id):
    c=db(); c.execute("UPDATE transactions SET status='Pago',paid_date=? WHERE id=?",(date.today().isoformat(),id)); c.commit(); c.close(); flash('Recebimento registrado.','success'); return redirect(url_for('finance'))

@app.route('/whatsapp/<int:client_id>')
@login_required
def whatsapp(client_id):
    c=row('SELECT * FROM clients WHERE id=?',(client_id,));
    if not c: abort(404)
    phone=''.join(ch for ch in (c['phone'] or '') if ch.isdigit());
    if phone and len(phone) in (10,11): phone='55'+phone
    msg=request.args.get('message','Olá! Aqui é da JS Escadas.'); return redirect('https://wa.me/'+phone+'?text='+__import__('urllib.parse').parse.quote(msg))

@app.cli.command('init-db')
def cli_init(): init_db(); print('Banco inicializado.')

if __name__=='__main__': init_db(); app.run(host='0.0.0.0',port=int(os.environ.get('PORT',5000)),debug=True)
