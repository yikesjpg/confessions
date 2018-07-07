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
import facebook
from flask import Flask, jsonify, request
import json
import os
from pytz import timezone
import redis

app = Flask(__name__)
db  = redis.Redis.from_url(os.environ["REDIS_URL"])

if not db.exists("postq"):
    db.set("postq", [])

def post(s):
    access_token = os.environ["ACCESS_TOKEN"]
    group_id = os.environ["GROUP_ID"]
    graph = facebook.GraphAPI(access_token=access_token, version="3.0")
    graph.put_object(parent_object=group_id, connection_name='feed',
        message=s)

def popq():
    if db.get("postq"):
        post(db.lpop("postq"))

@app.route('/posts', methods=["GET", "POST"])
def posts():
    if request.method == "POST":
        db.rpush("postq", *request.get_json())
        return "it g ma"
    else:
        return jsonify(db.get("postq"))

@app.route('/state', methods=["GET", "POST"])
def state():
    global st

    if request.method == "POST":
        json = request.get_json()
        for k in json:
            db.set(k, json[k])

    st = {
        "postq": db.get("postq")
    }
    return jsonify(st)

scheduler = BackgroundScheduler(timezone=timezone("America/Los_Angeles"))
scheduler.start()
scheduler.add_job(
    func=popq,
    trigger=CronTrigger(hour='0-2,9-23', minute="0,30"),
    id='posting_job',
    name='Post every hour.',
    replace_existing=True)

atexit.register(lambda: scheduler.shutdown())
