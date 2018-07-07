"""Runs a server which spaces out posts over time.

Periodically checks the post queue (i.e. the Sheet, but not so often to
avoid spamming the API) and its own queue (more often this is in-memory
or on-disk) to see how much is in the backlog and spaces posts
accordingly.

Only one instance of a server should be run across all admins.
"""

from flask import Flask, jsonify, request
import os
import pickle

app = Flask(__name__)
postq = []

def state():
    global postq

    return {
        "posts": postq
    }

@app.route('/posts', methods=["GET", "POST"])
def posts():
    global postq

    if request.method == "POST":
        postq += request.get_json()
        return "it g ma"
    else:
        return jsonify(state())

if __name__ == '__main__':
    try:
        try:
            postq = pickle.load(open("postq.p", "rb"))
        except:
            pass

        app.run()
    except:
        if postq:
            pickle.dump(postq, open("postq.p", "wb"))