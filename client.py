# cow

import click
from datetime import datetime, time
from dotenv import load_dotenv, find_dotenv
import gspread
import facebook
from oauth2client.service_account import ServiceAccountCredentials
import os
import pprint
from pytz import timezone, utc
import sys
import traceback

load_dotenv(find_dotenv())


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


def schedule(access_token, group_id, last_sched, posts):
    tz = timezone("America/Los_Angeles")
    sched = last_sched
    good = 0
    if posts:
        try:
            graph = facebook.GraphAPI(access_token=access_token, version="3.0")
            now = int(datetime.now().timestamp())
            sched = max(now, last_sched)

            for item in posts:
                sched += 30 * 60

                # Nobody is reading posts at 4 am.
                # We make sure that posts start at 9 am and go no later than 2 am.
                if in_time(time(2, 0, tzinfo=tz), time(9, 00, tzinfo=tz), datetime.fromtimestamp(sched, tz=tz).timetz()):
                    sched = int(
                        datetime.fromtimestamp(sched, tz=tz).replace(
                                hour=9, minute=0, second=0).timestamp())

                graph.put_object(
                    parent_object=group_id,
                    connection_name='feed',
                    message=item,
                    published="false",
                    scheduled_publish_time=str(sched))
                good += 1
        except Exception as e:
            raise e

    return (good, sched)


##########
# REVIEW #
##########
@click.command()
def review():
    """Reviews submissions.

    Required environment vars: SHEET_URL, ACCESS_TOKEN, GROUP_ID
    Magic files: credentials.json
    """
    sheet_url = os.getenv("SHEET_URL")
    access_token = os.getenv("ACCESS_TOKEN")
    group_id = os.getenv("GROUP_ID")

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
            cstep = int(state[1][1])
            cstep_inc = 0
            crow = int(state[2][1]) if int(state[2][1]) >= 0 else 0
            last_sched = int(state[3][1])
            strs = []
            rc = 0

            click.echo("inf | beginning the review process.")
            click.echo("    | you can quit at any time by pressing Ctrl+C")
            click.echo("    | (if this does nothing, hit Enter afterwards).")
            click.echo("inf | the next item in the review queue will be")
            click.echo("    | displayed for your convenience. please type out")
            click.echo("    | the full post that you would like to schedule.")
            click.echo("inf | if you'd like to reject this post and move to the")
            click.echo("    | next queue item, type the n character.")

            # List comprehension to ignore timestamps
            items = [x[1] for x in confessions.get_all_values()[1 + crow:]]

            # TODO: Spam detection.

            # skip reviewed items which for some reason weren't deleted
            try:
                for item in items:
                    # TODO: spam detection.
                    # if this message is exactly the same as one seen before.
                    text = item

                    click.echo()
                    click.echo("rev : {}) {}".format(cstep + cstep_inc, text))
                    r = click.prompt("rev > Text")
                    if r != "N":
                        strs.append((cstep_inc, rc, "{}".format(
                            r)))
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
            click.echo("inf | scheduling approved posts...")
            good, new_sched = schedule(access_token, group_id, last_sched,
                                       [x[2] for x in strs])
            if good != rc:
                click.echo("err | {} approved post(s) could not be scheduled.".format(rc - good))
                click.echo(
                    "    | wait before approving more posts for up to an hour."
                )
                # set the new cstep and crow.
                state_ws.update_acell(
                    "B2",
                    str(cstep if good == 0 else cstep + strs[good - 1][0] + 1))
                state_ws.update_acell(
                    "B3",
                    str(crow if good == 0 else crow + strs[good - 1][1] + 1))
                state_ws.update_acell("B4", str(new_sched))
            else:
                click.echo("inf | done.")
                # set the new cstep and crow.
                state_ws.update_acell("B2", str(cstep + cstep_inc))
                state_ws.update_acell("B3", str(crow + rc))
                state_ws.update_acell("B4", str(new_sched))

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
    review()
