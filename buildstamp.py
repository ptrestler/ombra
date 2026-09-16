"""A short, comparable identity for a build.

Two rounds of "is it live yet?" today were really "is this page the build I just
made?", which nothing on the page could answer. Both builders stamp this into
the template, the standalone writes it beside itself as version.txt, and the
page compares the two to notice it is stale.

The commit is what identifies a build; the timestamp is only there so an
uncommitted local build still gets a distinct stamp.
"""
import datetime, subprocess


def stamp():
    when = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M")
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"],
                               capture_output=True, text=True, timeout=10).stdout.strip()
    except Exception:
        sha, dirty = "", ""
    if not sha:
        return when
    return when + " " + sha + ("+" if dirty else "")
