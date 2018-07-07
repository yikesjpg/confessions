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
import os
from pytz import timezone

app = Flask(__name__)

st = {
    "postq": []
}

def post(s):
    access_token = os.environ["ACCESS_TOKEN"]
    group_id = os.environ["GROUP_ID"]
    graph = facebook.GraphAPI(access_token=access_token, version="3.0")
    graph.put_object(parent_object=group_id, connection_name='feed',
        message=s)

def popq():
    global st

    if st["postq"]:
        post(st["postq"].pop(0))

@app.route('/posts', methods=["GET", "POST"])
def posts():
    global st

    if request.method == "POST":
        st["postq"] += request.get_json()
        return "it g ma"
    else:
        return jsonify(postq)

@app.route('/state', methods=["GET", "POST"])
def state():
    global st

    if request.method == "POST":
        json = request.get_json()
        for k in json:
            state[k] = v
        return jsonify(st)
    else:
        return jsonify(st)

scheduler = BackgroundScheduler(timezone=timezone("America/Los_Angeles"))
scheduler.start()
scheduler.add_job(
    func=popq,
    trigger=CronTrigger(hour='9-23', minute="0,30"),
    id='posting_job',
    name='Post every hour.',
    replace_existing=True)

atexit.register(lambda: scheduler.shutdown())

if __name__ == '__main__':
    app.run(host="0.0.0.0")