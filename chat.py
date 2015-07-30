#!/usr/bin/env python
import os
import os.path
import datetime
import flask
import redis
from flask import render_template

from flask.ext.sqlalchemy import SQLAlchemy

app = flask.Flask(__name__)
app.secret_key = 'shhh, secret!'
red = redis.StrictRedis()


#Start: gunicorn -b 128.199.140.153:8080 --worker-class=gevent -t 99999 chat:app

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
	numsub = pubsub.subscription_count
	msgs = Msg.query.order_by(Msg.time.desc()).all()
	user = flask.session['user']

	return render_template('chat.html', user=user, msgs=msgs, numsub=numsub)


if __name__ == '__main__':
	app.debug = True
	app.run()
