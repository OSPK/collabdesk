#!/usr/bin/env python
import os
import os.path
import time
import datetime
import flask
import redis
from flask import render_template

from flask.ext.sqlalchemy import SQLAlchemy

app = flask.Flask(__name__)
app.secret_key = 'shhh, secret!'

# redis.StrictRedis(host='localhost', port=6379, db=0, password=None, socket_timeout=None, connection_pool=None, charset='utf-8', errors='strict', unix_socket_path=None)
red = redis.StrictRedis(password='secret3v')


#Start: gunicorn -b 0.0.0.0:8080 --worker-class=gevent -t 99999 chat:app

APP_DIR = os.path.dirname(os.path.realpath(__file__))

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///%s' % os.path.join(APP_DIR, 'chat.db')
db = SQLAlchemy(app)

##now = datetime.datetime.now()
##now = datetime.datetime.now().replace(microsecond=0).time()
##now = now.isoformat()
#one = Msg('waqas', now, 'HEY LMAO')
#db.session.add(one)
#db.session.commit()
# Msgs = Msg.query.all()
# admin = User.query.filter_by(username='admin').first()

class Msg(db.Model):
	id = db.Column(db.Integer, primary_key=True)
	time = db.Column(db.DateTime)
	usr = db.Column(db.String(80), unique=False)
	msg = db.Column(db.String(520), unique=False)

	def __init__(self, usr, time, msg):
		self.time = time
		self.usr = usr
		self.msg = msg

	def __repr__(self):
		return u'[%s] %s: %s' % (self.time, self.usr, self.msg)

def event_stream():
	pubsub = red.pubsub()
	pubsub.subscribe('chat')
	# TODO: handle client disconnection.
	for message in pubsub.listen():
		print message
		yield 'data: %s\n\n' % message['data']

app.config['ONLINE_LAST_MINUTES'] = 5

def mark_online(user_id):
	now = int(time.time())
	expires = now + (app.config['ONLINE_LAST_MINUTES'] * 60) + 10
	all_users_key = 'online-users/%d' % (now // 60)
	user_key = 'user-activity/%s' % user_id
	p = red.pipeline()
	p.sadd(all_users_key, user_id)
	p.set(user_key, now)
	p.expireat(all_users_key, expires)
	p.expireat(user_key, expires)
	p.execute()

def get_user_last_activity(user_id):
	last_active = red.get('user-activity/%s' % user_id)
	if last_active is None:
		return None
	return datetime.utcfromtimestamp(int(last_active))

def get_online_users():
	current = int(time.time()) // 60
	minutes = xrange(app.config['ONLINE_LAST_MINUTES'])
	return red.sunion(['online-users/%d' % (current - x) for x in minutes])

@app.before_request
def mark_current_user_online():
	if 'user' in flask.session:
		user = flask.session['user']
		mark_online(user)

@app.route('/login', methods=['GET', 'POST'])
def login():
	if flask.request.method == 'POST':
		usrcap = flask.request.form['user']
		flask.session['user'] = usrcap.upper()
		return flask.redirect('/')
	return '<form action="" method="post">You Name: <input class="form-control" name="user">'


@app.route('/post', methods=['POST'])
def post():
	message = flask.request.form['message']
	user = flask.session.get('user', 'anonymous')
	now = datetime.datetime.now()
	#.replace(microsecond=0).time()
	masg = Msg(user, now, message)
	db.session.add(masg)
	db.session.commit()
	#red.publish('chat', u'[%s] %s: %s' % (now.isoformat(), user, message))
	red.publish('chat', u'<p><strong>%s:</strong> %s </p>' % (user, message))

	return flask.Response(status=204)


@app.route('/stream')
def stream():
	return flask.Response(event_stream(), mimetype="text/event-stream")


@app.route('/')
def home():
	if 'user' not in flask.session:
		return flask.redirect('/login')

	online = get_online_users()
	msgs = Msg.query.order_by(Msg.time.desc()).all()
	user = flask.session['user']

	return render_template('chat.html', user=user, msgs=msgs, online=online)


if __name__ == '__main__':
	app.debug = True
	app.run()
