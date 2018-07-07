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
from oauth2client import file, client, tools
import os
import pickle
import pprint
import requests

load_dotenv(find_dotenv())

def j(s):
    return os.path.join(os.path.dirname(__file__), s)

def read_credentials():
    client_secret = j("client_secret.json")
    scope = 'https://spreadsheets.google.com/feeds'
    store = file.Storage(j('credentials.json'))

    creds = store.get()
    if not creds or creds.invalid:
        flow = client.flow_from_clientsecrets(client_secret, scope)
        creds = tools.run_flow(flow, store)

    return creds

@click.group()
def cli():
    pass

#########
# QUERY #
#########
@cli.command()
def query():
    """Queries the server for posts
    """
    server = os.getenv("SERVER")
    r = requests.get(server + "/posts")

    pp = pprint.PrettyPrinter(width=60, indent=4)
    pp.pprint(r.json())

##########
# REVIEW #
##########
@cli.command()
def review():
    """Reviews submissions.

    Required environment vars: SHEET_URL, SERVER
    Magic files: client_secret.json, todo_post.p, credentials.json
    """
    sheet_url = os.getenv("SHEET_URL")
    server = os.getenv("SERVER")

    try:
        click.echo("inf | attempting to get google api credentials...")
        gc = gspread.authorize(read_credentials())
    except:
        click.echo("err | couldn't read google api credentials. check .env")
        click.echo("    | and try again.")
        return
    
    try:
        sh = gc.open_by_url(sheet_url)
    except:
        click.echo("err | this sheet doesn't exist. maybe you need to share")
        click.echo("    | it with the client_email in $APP_JSON first?")
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
            except:
                pass

            # We try to post what we have; otherwise, we pickle it all
            try:
                requests.post(server + "/posts", json=strs)
            except Exception as e:
                pickle.dump(strs, open("todo_post.p", "wb"))
                click.echo("err | could not send approvals to posting server.")
                click.echo("    | approved posts have been saved to disk at `todo_post.p`.")
            else:
                if os.path.isfile("todo_post.p"):
                    os.remove("todo_post.p")

        except Exception as e:
            click.echo("err | something went horribly wrong with modifying the sheet.")
            click.echo("    | please send over this debug information:")
            raise e
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