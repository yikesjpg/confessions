# cow
# TODO: Making it so that the script spaces out posts properly
# you'd have to keep the script on for a while. But how do you sync approves
# from disparate computers? one computer has to be the single source of truth.
# potential solution: when a post is approved, a POST is sent to a machine
# running a server.
# TODO: Make this a proper OAuth2 app which requests permission from the user.

import click
from dotenv import load_dotenv, find_dotenv
import gspread
import json
from oauth2client.service_account import ServiceAccountCredentials
import os
import pickle
import pprint
import requests
import sys
import traceback

load_dotenv(find_dotenv())

def j(relative_path):
    base_path = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)

def read_credentials():
    creds_filename = j("credentials.json")
    scope = [
        'https://spreadsheets.google.com/feeds',
    ]
    return ServiceAccountCredentials.from_json_keyfile_name(creds_filename, scope)

@click.group()
def cli():
    pass

#########
# STATE #
#########
@cli.command()
@click.argument('filename', required=False)
def state(filename):
    """Updates the server's state based on a json file or retrieves it.
    """
    server = os.getenv("SERVER")
    r = None
    try:
        if filename is None:
            r = requests.get(server + "/state")
        else:
            with open(filename) as f:
                data = json.load(open(filename))
                r = requests.post(server + "/state", json=data)
    except OSError as e:
        click.echo("err | invalid file.")
        raise e
    else:
        pp = pprint.PrettyPrinter()
        pp.pprint(r.json())

##########
# REVIEW #
##########
@cli.command()
def review():
    """Reviews submissions.

    Required environment vars: SHEET_URL, SERVER
    Magic files: credentials.json, todo_post.p
    """
    sheet_url = os.getenv("SHEET_URL")
    server = os.getenv("SERVER")

    try:
        click.echo("inf | attempting to get google api credentials...")
        gc = gspread.authorize(read_credentials())
    except Exception as e:
        traceback.print_exc()
        click.echo("err | couldn't read google api credentials.")
        click.echo("err | debug information has been printed.")
        return
    
    try:
        sh = gc.open_by_url(sheet_url)
    except Exception as e:
        traceback.print_exc()
        click.echo("err | this sheet doesn't exist. maybe you need to share")
        click.echo("    | it with the client_email first?")
        click.echo("err | debug information has been printed.")
        return
    
    click.echo("inf | loading worksheet data.")
    click.echo("    | this may take a while...")

    confessions = sh.get_worksheet(0)
    state_ws = sh.get_worksheet(1)
    state = state_ws.get_all_values()

    if state[0][1] == "FALSE":
        try:
            # we're not locked; lock it
            # note: STATE FORMAT: B1 is locked, B2 is current step (the number
            # before every confession on the fb page), B3 is current row (the
            # row of the confession we're currently on)
            state_ws.update_acell("B1", "TRUE")
            # TODO: We might not need to store cstep as state in the sheet; the
            # server can keep track of that
            cstep = int(state[1][1])
            cstep_inc = 0
            crow = int(state[2][1]) if int(state[2][1]) >= 0 else 0
            strs = []
            rc = 0

            click.echo("inf | beginning the review process.")
            click.echo("    | you can quit at any time by pressing Ctrl+C")
            click.echo("    | (if this does nothing, hit Enter afterwards).")

            # List comprehension to ignore timestamps
            items = [x[1] for x in confessions.get_all_values()[1 + crow:]]

            # skip reviewed items which for some reason weren't deleted
            try:
                for item in items:
                    # TODO: spam detection.
                    # if this message is exactly the same as one seen before.
                    text = item

                    click.echo()
                    click.echo("rev : {}) {}".format(cstep + cstep_inc, text))
                    if click.confirm("rev > Approve?"):
                        strs.append("{})\n{}".format(cstep + cstep_inc, text))
                        cstep_inc += 1
                    rc += 1
            except click.Abort:
                click.echo()
                click.echo("inf | aborted. {} items reviewed.".format(rc))
            else:
                click.echo("inf | end of queue reached. {} items reviewed.".format(rc))

            # set the new cstep and crow.
            state_ws.update_acell("B2", str(cstep + cstep_inc))
            state_ws.update_acell("B3", str(crow + rc))

            # propagate changes: post.
            # We combine both things we haven't posted that are sitting on-disk
            # and the things we gotta post now
            try:
                strs = pickle.load(open("todo_post.p", "rb")) + strs
                click.echo("inf | loading previous unsubmitted posts...")
            except:
                pass

            # We try to post what we have; otherwise, we pickle it all
            try:
                click.echo("inf | uploading approved posts to server...")
                requests.post(server + "/posts", json=strs)
                click.echo("inf | done.")
            except:
                pickle.dump(strs, open("todo_post.p", "wb"))
                click.echo("err | could not send approvals to posting server.")
                click.echo("    | approved posts have been saved to disk at `todo_post.p`.")
            else:
                if os.path.isfile("todo_post.p"):
                    os.remove("todo_post.p")

        except Exception as e:
            traceback.print_exc()
            click.echo("err | something went wrong...")
            click.echo("    | debug information has been printed.")
        finally:
            state_ws.update_acell("B1", "FALSE")
    else:
        # we're locked
        click.echo("err | the responses sheet is currently locked.")
        click.echo("    | another admin is probably reviewing submissions.")
        click.echo("    |")
        click.echo("    | if this is not true, go into the 'state' worksheet")
        click.echo("    | and set 'locked' to 'FALSE'.")

if __name__ == '__main__':
    cli()