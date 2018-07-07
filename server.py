"""Runs a server which spaces out posts over time.

Periodically checks the post queue (i.e. the Sheet, but not so often to
avoid spamming the API) and its own queue (more often this is in-memory
or on-disk) to see how much is in the backlog and spaces posts
accordingly.

Only one instance of a server should be run across all admins.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import atexit
import datetime
from dotenv import load_dotenv, find_dotenv
import facebook
from flask import Flask, jsonify, request
import os
from pytz import timezone
import redis

load_dotenv(find_dotenv())

app = Flask(__name__)
db  = redis.StrictRedis.from_url(os.environ["REDIS_URL"], decode_responses=True)

def post(s):
    access_token = os.environ["ACCESS_TOKEN"]
    group_id = os.environ["GROUP_ID"]
    graph = facebook.GraphAPI(access_token=access_token, version="3.0")
    graph.put_object(parent_object=group_id, connection_name='feed',
        message=s)

def popq():
    if db.exists("postq"):
        time = datetime.datetime.utcnow()
        if db.exists("last_modified"):
            prev = datetime.datetime.strptime(db.get("last_modified"), "%Y-%m-%d %H:%M:%S")
            diff = time - prev
            if diff <= datetime.timedelta(minutes=1):
                return

        t = time.strftime("%Y-%m-%d %H:%M:%S")
        db.set("last_modified", t)
        post(db.lpop("postq"))

@app.route('/posts', methods=["GET", "POST"])
def posts():
    if request.method == "POST":
        db.rpush("postq", *request.get_json())
        return "it g ma"
    else:
        return jsonify(db.lrange("postq", 0, -1))

@app.route('/state', methods=["GET", "POST"])
def state():
    if request.method == "POST":
        json = request.get_json()
        for k in json:
            if k == "postq":
                db.delete("postq")
                db.rpush(k, *json[k])

    st = {
        "postq": [] if not db.exists("postq") else db.lrange("postq", 0, -1)
    }
    return jsonify(st)

@app.route('/')
def index():
    return "ping! pong!"

scheduler = BackgroundScheduler(timezone=timezone("America/Los_Angeles"))
scheduler.start()
scheduler.add_job(
    func=popq,
    trigger=CronTrigger(hour='0-2,9-23', minute="0,30"),
    id='posting_job',
    name='Post every hour.',
    replace_existing=True)

atexit.register(lambda: scheduler.shutdown())
