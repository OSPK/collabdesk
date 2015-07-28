import datetime
import functools
import os
import re
import urllib, json

from flask import (Flask, flash, Markup, redirect, render_template, request,
				   Response, session, url_for, jsonify)
from markdown import markdown
from markdown.extensions.codehilite import CodeHiliteExtension
from markdown.extensions.extra import ExtraExtension
from micawber import bootstrap_basic, parse_html
from micawber.cache import Cache as OEmbedCache
from peewee import *
from playhouse.flask_utils import FlaskDB, get_object_or_404, object_list
from playhouse.sqlite_ext import *
from flask.ext.cache import Cache
import tweepy

#DO pip install -r requirements.txt
# pip list > requirements.txt


# Blog configuration values.

# You may consider using a one-way hash to generate the password, and then
# use the hash again in the login view to perform the comparison. This is just
# for simplicity.
ADMIN_PASSWORD = 'secret'
APP_DIR = os.path.dirname(os.path.realpath(__file__))

# The playhouse.flask_utils.FlaskDB object accepts database URL configuration.
DATABASE = 'sqliteext:///%s' % os.path.join(APP_DIR, 'blog.db')
DEBUG = False

# The secret key is used internally by Flask to encrypt session data stored
# in cookies. Make this unique for your app.
SECRET_KEY = 'shhh, secret!'

# This is used by micawber, which will attempt to generate rich media
# embedded objects with maxwidth=800.
SITE_WIDTH = 800


# Create a Flask WSGI app and configure it using values from the module.
app = Flask(__name__)
app.config.from_object(__name__)
application = app

# FlaskDB is a wrapper for a peewee database that sets up pre/post-request
# hooks for managing database connections.
flask_db = FlaskDB(app)

# The `database` is the actual peewee database, as opposed to flask_db which is
# the wrapper.
database = flask_db.database

# Configure micawber with the default OEmbed providers (YouTube, Flickr, etc).
# We'll use a simple in-memory cache so that multiple requests for the same
# video don't require multiple network requests.
oembed_providers = bootstrap_basic(OEmbedCache())

#Tweepy
auth = tweepy.OAuthHandler('HiSmGqvj8Az9E86RLnV78YgNw', 'yfWgaKvIOxRsLOTMQ1WeWJ6UAmIdExHZkPRJn9qX3Cgb1y7rer')
auth.set_access_token('3024265320-QPKgtETV2ge9jpWABDmciE9KtYu48pcJeLZM2XU', 'HMIooBSpGQZAHu4NWIET6VaAPbVljCfw4ixYnpqXZxJrM')

api = tweepy.API(auth)

cache = Cache(app,config={'CACHE_TYPE': 'simple'})


class Entry(flask_db.Model):
	title = CharField()
	fbtitle = CharField()
	link = CharField()
	publink = CharField()
	imgurl = CharField()
	slug = CharField(unique=True)
	content = TextField()
	published = BooleanField(index=True)
	timestamp = DateTimeField(default=datetime.datetime.now, index=True)

	@property
	def html_content(self):
		"""
		Generate HTML representation of the markdown-formatted blog entry,
		and also convert any media URLs into rich media objects such as video
		players or images.
		"""
		hilite = CodeHiliteExtension(linenums=False, css_class='highlight')
		extras = ExtraExtension()
		markdown_content = markdown(self.content, extensions=[hilite, extras])
		oembed_content = parse_html(
			markdown_content,
			oembed_providers,
			urlize_all=True,
			maxwidth=app.config['SITE_WIDTH'])
		return Markup(oembed_content)

	def save(self, *args, **kwargs):
		# Generate a URL-friendly representation of the entry's title.
		if not self.slug:
			self.slug = re.sub('[^\w]+', '-', self.title.lower()).strip('-')
		ret = super(Entry, self).save(*args, **kwargs)

		# Store search content.
		self.update_search_index()
		return ret

	def update_search_index(self):
		# Create a row in the FTSEntry table with the post content. This will
		# allow us to use SQLite's awesome full-text search extension to
		# search our entries.
		try:
			fts_entry = FTSEntry.get(FTSEntry.entry_id == self.id)
		except FTSEntry.DoesNotExist:
			fts_entry = FTSEntry(entry_id=self.id)
			force_insert = True
		else:
			force_insert = False
		fts_entry.content = '\n'.join((self.title, self.content))
		fts_entry.save(force_insert=force_insert)

	@classmethod
	def public(cls):
		return Entry.select().where(Entry.published == True)

	@classmethod
	def drafts(cls):
		return Entry.select().where(Entry.published == False)

	@classmethod
	def search(cls, query):
		words = [word.strip() for word in query.split() if word.strip()]
		if not words:
			# Return an empty query.
			return Entry.select().where(Entry.id == 0)
		else:
			search = ' '.join(words)

		# Query the full-text search index for entries matching the given
		# search query, then join the actual Entry data on the matching
		# search result.
		return (FTSEntry
				.select(
					FTSEntry,
					Entry,
					FTSEntry.rank().alias('score'))
				.join(Entry, on=(FTSEntry.entry_id == Entry.id).alias('entry'))
				.where(
					(Entry.published == True) &
					(FTSEntry.match(search)))
				.order_by(SQL('score').desc()))

class FTSEntry(FTSModel):
	entry_id = IntegerField(Entry)
	content = TextField()

	class Meta:
		database = database

def login_required(fn):
	@functools.wraps(fn)
	def inner(*args, **kwargs):
		if session.get('logged_in'):
			return fn(*args, **kwargs)
		return redirect(url_for('login', next=request.path))
	return inner

def draft_count():
	query = 0

	if Entry.drafts() is not None:
		query = Entry.drafts().order_by(Entry.timestamp.desc())
	a = 0
	for x in query:
		a += 1
	return a
app.jinja_env.globals.update(draft_count=draft_count)

@app.route('/login/', methods=['GET', 'POST'])
def login():
	next_url = request.args.get('next') or request.form.get('next')
	if request.method == 'POST' and request.form.get('password'):
		password = request.form.get('password')
		# TODO: If using a one-way hash, you would also hash the user-submitted
		# password and do the comparison on the hashed versions.
		if password == app.config['ADMIN_PASSWORD']:
			session['logged_in'] = True
			session.permanent = True  # Use cookie to store session.
			flash('You are now logged in.', 'success')
			return redirect(next_url or url_for('index'))
		else:
			flash('Incorrect password.', 'danger')
	return render_template('login.html', next_url=next_url)

@app.route('/logout/', methods=['GET', 'POST'])
def logout():
	if request.method == 'POST':
		session.clear()
		return redirect(url_for('login'))
	return render_template('logout.html')

@app.route('/')
def index():
	test="hi"
	# The `object_list` helper will take a base query and then handle
	# paginating the results if there are more than 20. For more info see
	# the docs:
	# http://docs.peewee-orm.com/en/latest/peewee/playhouse.html#object_list
	return render_template('home.html', test=test)

@app.route('/trends/')
@cache.cached(timeout=1800)
@login_required
def trends():
	karachi = api.trends_place(2211096)
	lahore = api.trends_place(2211177)
	pakistan = api.trends_place(23424922)
	india = api.trends_place(23424848)
	unitedstates = api.trends_place(23424977)
	world = api.trends_place(1)

	for karachi in karachi:
		karachi = karachi
	for pakistan in pakistan:
		pakistan = pakistan
	for lahore in lahore:
		lahore = lahore
	for india in india:
		india = india
	for unitedstates in unitedstates:
		unitedstates = unitedstates
	for world in world:
		world = world

	# The `object_list` helper will take a base query and then handle
	# paginating the results if there are more than 20. For more info see
	# the docs:
	# http://docs.peewee-orm.com/en/latest/peewee/playhouse.html#object_list
	return render_template('trends.html', karachi=karachi, lahore=lahore, pakistan=pakistan, india=india, unitedstates=unitedstates, world=world)

@app.route('/done/')
@login_required
def done():
	search_query = request.args.get('q')
	if search_query:
		query = Entry.search(search_query)
	else:
		query = Entry.public().order_by(Entry.timestamp.desc())

	# The `object_list` helper will take a base query and then handle
	# paginating the results if there are more than 20. For more info see
	# the docs:
	# http://docs.peewee-orm.com/en/latest/peewee/playhouse.html#object_list
	return object_list(
		'done.html',
		query,
		search=search_query,
		check_bounds=False)

@app.route('/create/', methods=['GET', 'POST'])
@login_required
def create():
	if request.method == 'POST':
		if request.form.get('title') and request.form.get('link'):
			entry = Entry.create(
				title=request.form['title'],
				fbtitle=request.form['fbtitle'],
				link=request.form['link'],
				imgurl=request.form['imgurl'],
				publink=request.form['publink'],
				content=request.form['content'],
				published=request.form.get('published') or False)
			flash('Entry created successfully.', 'success')
			if entry.published:
				return redirect(url_for('detail', slug=entry.slug))
			else:
				return redirect(url_for('edit', slug=entry.slug))
		else:
			flash('Title and Link are required.', 'danger')
	return render_template('create.html')

@app.route('/drafts/')
@login_required
def drafts():
	query = Entry.drafts().order_by(Entry.timestamp.desc())

	return object_list('todo.html', query, check_bounds=False)

@app.route('/<slug>/')
@login_required
def detail(slug):
	if session.get('logged_in'):
		query = Entry.select()
	else:
		query = Entry.public()
	entry = get_object_or_404(query, Entry.slug == slug)

	#fblink = urllib.quote_plus(entry.publink)
	fburl = ('https://api.facebook.com/method/links.getStats?urls=%s&format=json' % entry.publink)
	fbresponse = urllib.urlopen(fburl);
	fbshares = json.load(fbresponse)

	twurl = ('http://urls.api.twitter.com/1/urls/count.json?url=%s' % entry.publink)
	twresponse = urllib.urlopen(twurl);
	twshares = json.load(twresponse)

	return render_template('detail.html', entry=entry, fbshares=fbshares, twshares=twshares)

@app.route('/<slug>/edit/', methods=['GET', 'POST'])
@login_required
def edit(slug):
	entry = get_object_or_404(Entry, Entry.slug == slug)
	if request.method == 'POST':
		if request.form.get('title') and request.form.get('content'):
			entry.title = request.form['title']
			entry.fbtitle = request.form['fbtitle']
			entry.link = request.form['link']
			entry.imgurl = request.form['imgurl']
			entry.publink = request.form['publink']
			entry.content = request.form['content']
			entry.published = request.form.get('published') or False
			entry.save()

			flash('Entry saved successfully.', 'success')
			if entry.published:
				return redirect(url_for('detail', slug=entry.slug))
				#return redirect(url_for('drafts'))
			else:
				#return redirect(url_for('edit', slug=entry.slug))
				return redirect(url_for('drafts'))
		else:
			flash('Title and Content are required.', 'danger')

	return render_template('edit.html', entry=entry)

@app.route('/<slug>/update/', methods=['GET', 'POST'])
@login_required
def update(slug):
	entry = get_object_or_404(Entry, Entry.slug == slug)
	if request.method == 'POST':
		entry.publink=request.form['publink']
		entry.published = request.form.get('published') or False
		entry.save()

		flash('Entry saved successfully.', 'success')
		if entry.published:
			#return redirect(url_for('detail', slug=entry.slug))
			return redirect(url_for('drafts'))
		else:
			#return redirect(url_for('edit', slug=entry.slug))
			return redirect(url_for('drafts'))

	return render_template('edit.html', entry=entry)

@app.route('/graphic/<slug>/')
@login_required
def graphic(slug):
	if session.get('logged_in'):
		query = Entry.select()
	else:
		query = Entry.public()
	entry = get_object_or_404(query, Entry.slug == slug)

	return render_template('graphic.html', entry=entry)

@app.template_filter('clean_querystring')
def clean_querystring(request_args, *keys_to_remove, **new_values):
	# We'll use this template filter in the pagination include. This filter
	# will take the current URL and allow us to preserve the arguments in the
	# querystring while replacing any that we need to overwrite. For instance
	# if your URL is /?q=search+query&page=2 and we want to preserve the search
	# term but make a link to page 3, this filter will allow us to do that.
	querystring = dict((key, value) for key, value in request_args.items())
	for key in keys_to_remove:
		querystring.pop(key, None)
	querystring.update(new_values)
	return urllib.urlencode(querystring)

@app.errorhandler(404)
def not_found(exc):
	return Response('<h3>Not found</h3>'), 404

#def main():
#	database.create_tables([Entry, FTSEntry], safe=True)
#	app.run(debug=True,host='0.0.0.0')

if __name__ == '__main__':
	database.create_tables([Entry, FTSEntry], safe=True)
	app.run(debug=True,host='0.0.0.0')