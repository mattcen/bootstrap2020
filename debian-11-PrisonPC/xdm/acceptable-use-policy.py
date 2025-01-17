#!/usr/bin/python3

__doc__ = """ display an "Acceptable Use Policy" (AUP) on the xdm login screen

The AUP says something like

    You may be monitored at any time.
    You will not know WHEN you are being monitored.
    This is a privilege; naughty users may be banned.

We used to do this by pre-rendering it to an XPM,
and telling XDM it was the company logo.
That didn't work very well;
instead create a trivial window in the bottom-right corner,
and kill it (/etc/X11/xdm/Xstartup) when the login succeeds.

This has to work **without a WM's help**, because
it's at the login screen.

We can't just use zenity, because
that has unavoidable "OK/Cancel" buttons.
Moriarty can walk up and hit "OK", then walk away, and
Arthur can then walk up and use the computer without seeing the AUP.

UPDATE: zenity also bundles an entire insecure web browser for its
"calendar" mode, these days.  SCARY!

https://python-gtk-3-tutorial.readthedocs.io/en/latest/
"""

import subprocess
import urllib.request

import gi
gi.require_version('Gtk', '3.0')
import gi.repository.Gtk        # noqa: E402


stdout = subprocess.check_output(['xrdb', '-query'], text=True)
xresources = dict(line.split(':\t', 1) for line in stdout.splitlines()
                  # At xdm (normal use), there are no blank lines.
                  # At xfce (debugging), there is a blank line!
                  if ':\t' in line)
stylesheet_str = f'''
* {{
    background-color: {xresources.get('xlogin.Login.Background', 'chartreuse')};
    color: {xresources.get('xlogin.Login.Foreground', 'magenta')};
    /* Hard-coded because GTK3 no longer accepts fontconfig notation,
       despite (AFAIK) it being correct for "real" CSS3.
       I'm not too worried about this because
       (unlike color) this is pretty much set-and-forget. */
    /* font: {xresources.get('xlogin.Login.face', 'Sans')}; */
    font-family: Universalis ADF Std;
    font-size: 18pt;
}}
'''
css_provider = gi.repository.Gtk.CssProvider()
css_provider.load_from_data(stylesheet_str.encode())

data = urllib.request.urlopen(
    'https://ppc-services/motd?text=1').read().decode().strip()
# Apparently you have to set margin here instead of in CssProvider,
# even though margins are pretty basic part of REAL CSS.
# This is probably in pixels, where the font is in points.
#
# NOTE: in GTK2 we had wrap=True here.
#       in GTK3, wrap=True makes the window as tall as possible.
#       This makes the label align near the center (not bottom) of the screen.
#       This makes the aup draw over the top of the login prompt.
#       The former issue is tolerable; the latter issue is not.
label = gi.repository.Gtk.Label(label=data, margin=18, wrap=False)
window = gi.repository.Gtk.Window()
window.get_style_context().add_provider(
    css_provider,
    gi.repository.Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
window.add(label)
window.show_all()
window.parse_geometry('-0-0')   # Place in top-right corner
window.connect('destroy', gi.repository.Gtk.main_quit)
gi.repository.Gtk.main()
