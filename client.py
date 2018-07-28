# cow

import base64
import click
from datetime import datetime, time
from dotenv import load_dotenv, find_dotenv
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import os
import pprint
from pytz import timezone, utc
import re
import requests
import sys
import traceback

load_dotenv(find_dotenv())


class St(object):
    def __init__(self, state_ws):
        self._ws = state_ws
        self._cells = state_ws.range("B1:B8")
        state = [x.value for x in self._cells]

        self.locked = state[0]
        self.cstep = int(state[1])
        self.crow = int(state[2]) if int(state[2]) >= 0 else 0
        self.last_sched = int(state[3])
        self.access_token = state[4]
        self.refresh_token = state[5]
        self.group_id = state[6]
        self.defer_row = int(state[7])

    def lock(self):
        self._ws.update_acell("B1", "TRUE")

    def unlock(self):
        self._ws.update_acell("B1", "FALSE")

    def update(self, cstep, crow, last_sched, access_token, refresh_token):
        self._cells[1].value = cstep
        self._cells[2].value = crow
        self._cells[3].value = last_sched
        self._cells[4].value = access_token
        self._cells[5].value = refresh_token

        self._ws.update_cells(self._cells[1:])


def j(relative_path):
    base_path = getattr(sys, '_MEIPASS',
                        os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_path, relative_path)


def read_credentials():
    creds_filename = j("credentials.json")
    scope = [
        'https://spreadsheets.google.com/feeds',
    ]
    return ServiceAccountCredentials.from_json_keyfile_name(
        creds_filename, scope)


def in_time(start, end, now):
    if start < end:
        return now >= start and now <= end
    else:  #Over midnight
        return now >= start or now <= end


def schedule(access_token, refresh_token, group_id, last_sched, posts):
    """
    Env vars: CLIENT_ID, CLIENT_SECRET
    """
    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")

    tz = timezone("America/Los_Angeles")
    sched = last_sched
    good = 0
    again = False

    endpoint = "https://platform.hootsuite.com/v1/messages"
    headers = {"Authorization": "Bearer {}".format(access_token)}
    if posts:
        try:
            now = int(datetime.now().timestamp())
            sched = max(now, last_sched)

            for item in posts:
                sched += 30 * 60

                tt = tz.localize(datetime.fromtimestamp(sched))

                # Nobody is reading posts at 4 am.
                # We make sure that posts start at 9 am and go no later than 2 am.
                if in_time(
                        time(2, 0, tzinfo=tz), time(9, 00, tzinfo=tz),
                        tt.timetz()):
                    tt = tt.replace(hour=9, minute=0, second=0)
                    sched = int(tt.timestamp())

                data = {
                    "text": item,
                    "socialProfileIds": [group_id],
                    "scheduledSendTime": tt.astimezone(utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                }

                resp = requests.post(endpoint, json=data, headers=headers)
                if "error" in resp.json():
                    if resp.json()["error"] == "request_forbidden":
                        again = True
                    resp.raise_for_status()

                good += 1
        except:
            traceback.print_exc()
            print("err | an error occurred")

    if again:
        try:
            print(
                "inf | old hootsuite access token expired. tryna get a new one..."
            )
            s = "{}:{}".format(client_id, client_secret)
            auth = base64.b64encode(s.encode("ascii")).decode("utf-8")
            headers = {"Authorization": "Basic {}".format(auth)}
            data = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token
            }
            resp = requests.post(
                "https://platform.hootsuite.com/oauth2/token",
                data=data,
                headers=headers)
            resp.raise_for_status()
            resp = resp.json()

            return schedule(resp["access_token"], resp["refresh_token"],
                            group_id, last_sched, posts[good:])
        except:
            print("err | failed...")

    return (good, sched, access_token, refresh_token)


##########
# REVIEW #
##########
def review():
    """Reviews submissions.

    Required environment vars: SHEET_URL
    Magic files: credentials.json
    """
    click.echo("inf | confessions mgr v2018.07.24")
    sheet_url = os.getenv("SHEET_URL")
    post_r = re.compile("@[0-9]+")

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
    prevs = sh.get_worksheet(1)
    prev_vals = {int(a[0]): int(a[1]) for a in prevs.get_all_values()}
    old_prev = len(prev_vals)
    state_ws = sh.get_worksheet(2)
    state = St(state_ws)

    if state.locked == "FALSE":
        try:
            # we're not locked; lock it
            state.lock()
            # note: STATE FORMAT: B1 is locked, B2 is current step (the number
            # before every confession on the fb page), B3 is current row (the
            # row of the confession we're currently on)
            cstep = state.cstep
            cstep_inc = 0
            crow = state.crow
            rc = 0
            last_sched = state.last_sched
            strs = []

            click.echo("inf | beginning the review process.")
            click.echo("inf | When prompted for a deliberation, the following options are available:")
            click.echo("    | y - approve")
            click.echo("    | p - approve [p]lain, without quoting previous confessions")
            click.echo("    | n - reject")
            click.echo("    | q - quit")
            click.echo("    | anything else will be added as text after the confession.")

            # List comprehension to ignore timestamps
            items_all = [x[1].rstrip("\r\n") for x in confessions.get_all_values()[1:]]
            items = items_all[crow:]

            # TODO: Spam detection.

            try:
                for item in items:
                    # TODO: spam detection.
                    # if this message is exactly the same as one seen before.

                    # traverse: auto-quote previous.
                    prev_csteps = []
                    ix = -1

                    cur_text = item
                    cur_cstep = cstep + cstep_inc
                    while True:
                        matches = [
                            int(x[1:]) for x in post_r.findall(cur_text)
                            if int(x[1:]) not in prev_csteps
                            and int(x[1:]) in prev_vals
                            and int(x[1:]) < cur_cstep
                        ]
                        prev_csteps += matches
                        ix += 1
                        if ix >= len(prev_csteps):
                            break
                        else:
                            cur_cstep = prev_csteps[ix]
                            cur_text = items_all[prev_vals[cur_cstep]]

                    # Printing
                    prev_csteps.sort(reverse=True)
                    orig = item.rstrip("\r\n")
                    text = orig + "\n"
                    for prev in prev_csteps:
                        text += "\n\"{})\n{}\"".format(
                            prev, items_all[prev_vals[prev]])
                    text = text.rstrip("\n\n")

                    click.echo("rev | next confession:")
                    click.echo("{})\n{}".format(cstep + cstep_inc, text))
                    prompt = click.prompt("rev > Deliberation")
                    if prompt.lower() == "y":
                        strs.append((cstep_inc, rc, "{})\n{}".format(
                            cstep + cstep_inc, text)))
                        prev_vals[cstep + cstep_inc] = crow + rc
                        cstep_inc += 1
                    elif prompt.lower() == "p":
                        strs.append((cstep_inc, rc, "{})\n{}".format(
                            cstep + cstep_inc, orig)))
                        prev_vals[cstep + cstep_inc] = crow + rc
                        cstep_inc += 1
                    elif prompt.lower() == "n":
                        pass
                    elif prompt.lower() == "q":
                        raise click.Abort()
                    else:
                        strs.append((cstep_inc, rc, "{})\n{}\n{}".format(
                            cstep + cstep_inc, orig, prompt)))
                        prev_vals[cstep + cstep_inc] = crow + rc
                        cstep_inc += 1

                    rc += 1
            except click.Abort:
                click.echo()
                click.echo("inf | aborted. {} items reviewed.".format(rc))
            else:
                click.echo(
                    "inf | end of queue reached. {} items reviewed.".format(
                        rc))

            # propagate changes: post.
            # We try to post what we have; otherwise, we give up
            click.echo("inf | scheduling {} approved posts... (this will take a long while)".format(cstep_inc))
            good, new_sched, access_token, refresh_token = schedule(
                state.access_token, state.refresh_token, state.group_id,
                last_sched, [x[2] for x in strs])
            if good != cstep_inc:
                click.echo(
                    "err | {} approved post(s) could not be scheduled.".format(
                        rc - good))
                click.echo(
                    "    | wait before approving more posts for up to a day.")

                # update state.
                state.update(
                    str(cstep if good == 0 else cstep + strs[good - 1][0] + 1),
                    str(crow if good == 0 else crow + strs[good - 1][1] + 1),
                    str(new_sched), access_token, refresh_token)
            else:
                click.echo("inf | done.")
                # set the new cstep and crow.
                state.update(
                    str(cstep + cstep_inc), str(crow + rc), str(new_sched),
                    access_token, refresh_token)

            if good > 0:
                vals = sorted(prev_vals.items(), key=lambda x: x[0])[old_prev:]
                cs = prevs.range(old_prev + 1, 1, old_prev + good, 1)
                for i, c in enumerate(cs):
                    c.value = vals[i][0]
                prevs.update_cells(cs)

                cs = prevs.range(old_prev + 1, 2, old_prev + good, 2)
                for i, c in enumerate(cs):
                    c.value = vals[i][1]
                prevs.update_cells(cs)

        except Exception as e:
            traceback.print_exc()
            click.echo("err | something went wrong...")
            click.echo("    | debug information has been printed.")
        finally:
            state.unlock()
    else:
        # we're locked
        click.echo("err | the responses sheet is currently locked.")
        click.echo("    | another admin is probably reviewing submissions.")
        click.echo("    |")
        click.echo("    | if this is not true, go into the 'state' worksheet")
        click.echo("    | and set 'locked' to 'FALSE'.")


if __name__ == '__main__':
    review()
