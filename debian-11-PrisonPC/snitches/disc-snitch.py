#!/usr/bin/python3

# We want inmates to have access to optical media.
# They are useful for:
# * education;
# * accessing legal libraries;
# * entertainment (DVD movies, CDDA music); &
# * personal data (e.g. family photo album).
#
# Unlike USB keys, they are (mostly) read-only,
# and harder to smuggle in body cavities.
#
# Uploading discs to a central network share & manage access.
# At this time there is no budget for the hardware
# (AMC would need about 15TiB of storage!)
# nor for coding the management UI.
# So optical discs are directly inserted into desktops.
#
# Some sites don't allow any discs at all.
# Some sites allow all discs.
# Some sites allow only discs that on an approved whitelist.
#
# Policy is implemented on the server side;
# this script ALWAYS asks "hey server, what should I do with disc X?"
#
# The server can reply "allow" (or "yes"), "eject", or "lock".
# The purpose of "lock" is to make it easier to seize contraband discs,
# by making it harder to reclaim & hide the disc when the inmate hears the guards coming.

# NB: this script is heavily based on usb-snitchd.
# For concision, where they overlap,
# I have elided the comments here.
# FIXME: merge usb-snitchd & disc-snitchd?

import pyudev
import subprocess
import systemd.daemon
import sys
import os                       # for os.path.exists

# When an exception is raised,
# by default python prints the exception itself *AND*
# a backtrace ("traceback") of each line in the call stack.
#
# This disables the latter, but *NOT* the former.
# This reduces logcheck for "expected" errors.
# It's OK here because we can infer the call stack from the exception
# itself & nearby stderr print statements.
# --twb, Sep 2016 (#30950)
#
# UPDATE: Mike found that in Python3.0+, 0 means ∞ (not 0).
# As the next best thing, set to 1 instead. —twb, Jun 2017 (#31932)
# Ref. https://docs.python.org/3/library/sys.html#sys.tracebacklimit
# Ref. https://bugs.python.org/issue12276
sys.tracebacklimit = 1

# This magic string is used when ID_FS_LABEL is not set.
# MUST NOT change until require-lucid-disc-snitch is gone.
ID_FS_LABEL_UNKNOWN = 'UNKNOWN'


def main():
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by_tag('disc-snitch')
    monitor.start()
    systemd.daemon.notify('READY=1')
    print('<7>Ready!', file=sys.stderr, flush=True)

    for device in iter(monitor.poll, None):
        assert 'DEVNAME' in device

        # Skip to next event when disc is *REMOVED*.
        if 'remove' == device.get('ACTION', None):
            print('<7>Drive removed, not processing.', file=sys.stderr, flush=True)
            continue
        if '1' == device.get('DISK_EJECT_REQUEST', None):
            print('<7>Disc eject request, not processing.', file=sys.stderr, flush=True)
            continue

        # Skip to next event if it's a music CD,
        # i.e. *ALL* tracks are audio tracks.
        # FIXME: after #24643, this policy changes.
        if (device.get('ID_CDROM_MEDIA_TRACK_COUNT', True) ==
            device.get('ID_CDROM_MEDIA_TRACK_COUNT_AUDIO', False)):
            print('<7>All tracks are CDDA, not processing.', file=sys.stderr, flush=True)
            continue

        # FIXME: Pete's code used to skip in these circumstances.
        # I think that's a mistake, but preserving semantics for now.
        # Reconsider when implementing #24643! --twb, Nov 2015
        if os.path.exists('/require-lucid-disc-snitch'):
            if not device.get('ID_CDROM_MEDIA', False):
                print('<7>ID_CDROM_MEDIA missing or empty, not processing. (tray-open event?)', file=sys.stderr, flush=True)
                continue
            # UPDATE: when the disc (or drive?) is damaged,
            # udev fails to find a filesystem---but vlc can still play the movie.
            # Therefore, skipping when ID_FS_TYPE is not set, is very dangerous.
            # What we expect to happen now, is for isoinfo to run and crash (therefore eject),
            # or to run and successfully fingerprint the disc.  --twb, Nov 2015
            if not device.get('ID_FS_TYPE', False):
                print('<7>WARNING: ID_FS_TYPE not set, PROCESSING CONTINUES. (damaged disc?)', file=sys.stderr, flush=True)
                # We *DO NOT* continue here, because sometimes a
                # damaged disc will not be recognized by udev, but
                # WILL be playable in vlc.
                #
                # So: do nothing here.
                # Either fingerprinting will fail (triggering fallback eject),
                # or fingerprinting will continue as normal.
                # # continue      # WRONG!

            # The data_lucid method (isoinfo) can't handle unusual discs,
            # with a mix of audio/data tracks, or multiple data tracks.
            # In these cases, log & force an eject.
            if (('0' != device.get('ID_CDROM_MEDIA_TRACK_COUNT_DATA', '0')) and
                ('0' != device.get('ID_CDROM_MEDIA_TRACK_COUNT_AUDIO', '0'))):
                print('<7>Device has audio *and* data tracks, eject forced.', file=sys.stderr, flush=True)
                eject(device)
                continue
            if '1' != device.get('ID_CDROM_MEDIA_TRACK_COUNT_DATA', '1'):
                print('<7>Device has multiple data tracks, eject forced.', file=sys.stderr, flush=True)
                eject(device)
                continue

        print('<7>Disc "{}" was inserted.'.format(
            device.get('ID_FS_LABEL', ID_FS_LABEL_UNKNOWN)), file=sys.stderr, flush=True)

        try:
            if os.path.exists('/require-lucid-disc-snitch'):
                answer = ask_lucid_server_about(device)
            else:
                answer = ask_jessie_server_about(device)
            print('<7>Server said "{}".'.format(answer), file=sys.stderr, flush=True)

            # FIXME: in here, check what 'answer' is and allow/lock/eject.
            if answer == 'yes':     # FIXME: remove after #24643.
                pass
            elif answer == 'allow':
                pass
            elif answer == 'lock':
                lock(device)
            else:
                eject(device)

        # If there's a problem probing the disc or asking the server,
        # just force-eject the disc -- don't reboot the whole desktop.
        # FIXME: is this too forgiving?  Errors are errors...
        # User story: "I have a scratched old DVD of Mad Max.
        # Sometimes when I insert it, my whole desktop reboots! Why?"
        except subprocess.CalledProcessError as error:
            # Print the exception itself so we know WHICH command failed.
            # This means we can safely send direct isoinfo stderr to /dev/null,
            # since that output is near-useless. --twb, Sep 2016 (#30950)
            print('<3>', error, file=sys.stderr, flush=True)
            eject(device)


def prisonpc_active_user():
    try:
        with open('/run/prisonpc-active-user') as fh:
            return fh.read()
    except FileNotFoundError:
        return 'nobody'


# NB: this is proof-of-concept code for the #24643 cleanup.
# As at 15.09, it is not used.
def data_jessie(device):
    return '\n'.join(
        # This content is directly visible by prison staff as a <PRE> block,
        # when considering whether to approve/reject a disc.
        # So, start with a nicely formatted list of metadata.
        #
        # Since the server turns into a disc UUID,
        # we MUST only give data about the disc (not the drive).
        sorted(['{}: {}'.format(key, device[key])
                for key in device
                if key.startswith('ID_CDROM_MEDIA_')
                or key.startswith('ID_FS_')]) +
        ['',                    # blank separator line
         subprocess.check_output(['cd-info',
                                  '--no-header',
                                  '--no-cddb',
                                  '--no-device-info',
                                  '--dvd',
                                  '--iso9660',
                                  device['DEVNAME']],
                                 universal_newlines=True)])


# The output of cd-info is more robust and detailed than
# the output from lsdvd + isoinfo.
#
# AMC has a large (~6000) corpus of known discs,
# and we SHOULD NOT invalidate it.
#
# That means we need to generate data the *OLD* way, as well as the
# new way, and have the server migrate discs from the old corpus as
# they're re-reported.  As at 15.09, that is not coded. (#24643)
#
# That means this output MUST BE BYTE-IDENTICAL to the old code.
#
# NB: "isoinfo dev=/dev/sr0" tries to take an exclusive lock,
# but "isoinfo  -i /dev/sr0" doesn't.
# The former has (and had!) problems if the GUI mounted the disc,
# so we use the latter.  It seems to be working.  --twb, Oct 2015
def data_lucid(device):
    # Bypass ALL this ugliness unless explicitly enabled.
    # NB: This is separate from /require-lucid-disc-snitch,
    # because during migration we send data_lucid *AND* data_jessie.
    if not os.path.exists('/require-lucid-disc-snitch-data'):
        return 'UNUSED'

    # NB: Pete used to run lsdvd when ID_CDROM_MEDIA_DVD=="1";
    # (i.e. when the *disc type* is a DVD, not a CD).
    # But lsdvd only works when there are .VOB files (i.e. a movie).
    # Pete ignored errors, so putting in a data DVD "worked";
    # there lsdvd gave no stdout, and its stderr was thrown away.
    #
    # We care about errors, but we don't have a udev header to tell us
    # when it's a MOVIE.  So run lsdvd ALWAYS, and if it crashes,
    # pretend we didn't run it.  Syslog will fill with lsdvd errors,
    # but we don't care.  --twb, Nov 2015 (#30332 - Problem 22).
    # UPDATE: this generated 30MLOC / 10GiB of logs overnight.
    # That's too much, so discard stderr from lsdvd. --twb, Jan 2016 (#30645)
    #
    # WARNING!!!  This means that if lsdvd fails to read a damaged
    # disc, but isoinfo works OK, it'll be added as a candidate disc
    # instead of ejecting.  YUK.  --twb, Nov 2015
    try:
        lsdvd = subprocess.check_output(['lsdvd', device['DEVNAME']],
                                        stderr=subprocess.DEVNULL,
                                        universal_newlines=True)

        # lsdvd is a shitty toy project we should never have used.
        # It's output changed between wheezy & jessie.
        # Specifically: there are fewer blank lines, &
        # the track lengths milliseconds are different.
        # We can't munge the latter from jessie to wheezy,
        # so munge them both to a common denominator (by removing the milliseconds).
        #
        # I was loathe to "import re" just for this.
        # From RTFS, it is clear I can just cut on character boundaries.
        # http://sources.debian.net/src/lsdvd/0.17-1/ohuman.c/#L14
        lsdvd = '\n'.join([
            (line[0:27] + line[31:] if line.startswith('Title:') else line)
            for line in lsdvd.splitlines()
            if line != ''])
        # Re-add the final newline that splitlines/join chomped.
        lsdvd += '\n'
    except subprocess.CalledProcessError:
        lsdvd = ''              # Not a movie.

    pvd = subprocess.check_output(
        ['isoinfo', '-d', '-i', device['DEVNAME']],
        stderr=subprocess.DEVNULL,
        universal_newlines=True)

    # Get (roughly) the output of "ls -lR" of the disc's first ISO9660/UDF filesystem.
    # For movies this is short, but for data discs it can be VERY long.
    # Apparently Ron/Pete decreed that "the first 400 lines is enough".
    # --twb, Dec 2014
    #
    # This used to just pipe into "head -400",
    # but since isoinfo still blocks to generate the rest of the output,
    # there is no harm in python collecting it all,
    # THEN discarding lines 401 onwards.
    lslR = subprocess.check_output(
        ['isoinfo',
         '-l' +
         # NB: isoinfo -J on a non-Joliet disc will crash isoinfo.
         ('' if 'NO Joliet present' in pvd else 'J') +
         # NB: isoinfo -R on a non-RR disc will print one error line per file.
         ('' if 'NO Rock Ridge present' in pvd else 'R'),
         '-i',
         device['DEVNAME']],
        stderr=subprocess.DEVNULL,
        universal_newlines=True)
    lslR = '\n'.join(lslR.splitlines()[:400])
    # Re-add the final newline that splitlines/join chomped.
    lslR += '\n'

    # This dumb separator is inherited from Pete.
    return '====\n'.join([lsdvd, pvd, lslR])


# NB: this is proof-of-concept code for the #24643 cleanup.
# As at 15.09, it is not used.
def ask_jessie_server_about(device):
    # NB: relies on systemd RuntimeDirectory=disc-snitch.
    with open('payload-jessie.bin', 'w') as fh:
        fh.write(data_jessie(device))
    with open('payload-lucid.bin', 'w') as fh:
        fh.write(data_lucid(device))

    return subprocess.check_output(
        ['curl', '-sLSf', 'https://ppc-services/discokay',
         '--retry', '10',
         '--retry-max-time', '60',
         '-Fuser={}'.format(prisonpc_active_user()),
         '-Fdata=@payload-jessie.bin',
         '-Fdata_pete=@payload-lucid.bin'] +
        # Rather than having to join & split all the metadata,
        # just pass them as individual fields.
        # The server's method will get them as **kwargs.
        # Then the server can evolve to use them later,
        # without needing updates on the desktop side.
        ['-F{}={}'.format(key, device[key])
         for key in device],
        universal_newlines=True)


def ask_lucid_server_about(device):
    # We are talking to a yukky Lucid server that predates #24643.
    #
    # FIXME: using curl -Fk1=v1 -Fk2=v2 doesn't work with this server.
    # FIXME: using curl -dk1=v1 -dk2=v2 doesn't work either.
    # As a workaround, continue doing it the Pete way,
    # which I strongly suspect is prone to injection attacks.

    # The shit server requires a UID, not a username.
    from pwd import getpwnam
    uid = getpwnam(prisonpc_active_user()).pw_uid

    # The shit server gets the IP address from the request body (spoofable)
    # rather than from the request headers (not spoofable).
    # Copy-and-pasted from what-is-my-ip(1prisonpc).
    from socket import socket, AF_INET, SOCK_DGRAM
    s = socket(AF_INET, SOCK_DGRAM)
    s.connect(('prisonpc', 0))
    host_ip = s.getsockname()[0]
    s.close()

    # NB: relies on systemd RuntimeDirectory=disc-snitch.
    with open('payload.bin', 'w') as fh:
        fh.write(
            '&'.join(['host_ip={}'.format(host_ip),
                      'uid={}'.format(uid),
                      'label={}'.format(
                          device.get('ID_FS_LABEL', ID_FS_LABEL_UNKNOWN)),
                      'summary=']))

    # And this is where it gets tricky.
    #
    # The stack of shitty webservers we used in 2008 would reject data that was too long.
    # So Pete decided the best solution was to gzip the data -- but only the summary(!).
    # Since he's using curl -d instead of curl -F,
    # that means he has to deal with escaping gzip's arbitrary bytes.
    # So OF COURSE he invented his own way to do that.
    #
    # Since the server side is hard-coded to expect this exact format,
    # we have to keep doing it here.  SIGH.

    # Based closely on prisonpc:eric/eric-apps/discokay.py.
    from gzip import compress
    from base64 import urlsafe_b64encode

    with open('payload.bin', 'ab') as fh:
        fh.write(urlsafe_b64encode(compress(data_lucid(device).encode())))

    return subprocess.check_output(
        ['curl', '-sLSf',
         '-d@payload.bin',
         '--retry', '10',
         '--retry-max-time', '60',
         # FIXME: stupid FQDN.
         'https://prisonpc/discokay'],
        universal_newlines=True)


def eject(device):
    subprocess.check_call(['eject', '-m', device['DEVNAME']])


# FIXME: some of this is pretty shady;
# we accept that as the cost of locking the drive.
# Inmates who reach this code were naughty,
# if it makes their computer act funny, I don't really care.
def lock(device):
    # Disable the physical eject button.
    subprocess.check_call(['eject', '-i1', device['DEVNAME']])

    # udev's defaults configure the eject button like the power button:
    # instead of ejecting, it just tells udev the eject button was pressed.
    # This is meant to give the OS an opportunity to umount cleanly.
    # But we need udev to NOT follow up by actually ejecting the drive!
    subprocess.check_call(['sed', '-i', 's/--eject-media//',
                           '/lib/udev/rules.d/60-cdrom_id.rules'])
    subprocess.check_call(['udevadm', 'control', '--reload-rules'])

    # Thunar asks udisks (via dbus) to eject the disk,
    # and udisks asks polkit (via dbus) if it should do so.
    # Tell polkit the answer is "no".
    # NB: o.f.udisks2 is for jessie; o.f.udisks is for wheezy.
    # The latter is in case I backport this to wheezy without paying attention.
    with open('/etc/polkit-1/localauthority/50-local.d/99-disc-snitchd.pkla', 'w') as fh:
        fh.write('\n'.join(['[disc-snitchd]',
                            'Identity=*',
                            'Action=org.freedesktop.udisks2.eject-media;org.freedesktop.udisks.drive-eject',
                            'ResultAny=no',
                            'ResultInactive=no',
                            'ResultActive=no']))

    # Disable umount (except umount -l and umount -f).
    #
    # If the disc is mounted (e.g. at /media/Ubuntu_14.04),
    # background a child process that has an open read fd on that dir.
    # FIXME: BROKEN.
    # On Linux, bash let's me open dirs for reading, as long as I don't read from them.
    # Python appears to explicitly ban this.
    #
    # Working bash version:
    #
    #     shopt -s nullglob
    #     for dir in /media/*/
    #     do sleep infinity <"$dir" &
    #     done
    #
    # An even older version tried to open files inside the mountpoint,
    # but this was less sexy.

    ## THIS FAILS (IsADirectoryError)
    # from glob import glob
    # for mountpoint in glob('/media/*/'):
    #     with open(mountpoint) as fh:
    #         # FIXME: double-check this actually backgrounded.
    #         subprocess.Popen(['sleep','infinity'], stdin=fh)
    ## THIS WORKS
    # from glob import glob
    # subprocess.Popen(['sh',
    #                   '-c', 'for i; do sleep infinity < "$i" & done',
    #                   '--'] + glob('/media/*/'))
    ## THIS WORKS
    import os
    if not os.fork():
        # ME AM CHILD!
        from glob import glob
        # NB: cannot handle more than ~1000 /media/*/ entries, due to ulimit.
        for d in glob('/media/*/'):
            os.open(d, 0)
        # Now all mountpoints are held open,
        # umount(8) will refuse to unmount them without -l or -f.
        # Now sit here forever doing nothing.
        # NB: python cannot say "forever", so we approximate.
        # NB: sleep(float('inf')) ==> OSError
        # NB: sleep(float('inf')) ==> OSError
        # NB: sleep(sys.float_info.max) ==> OSError
        #from time import sleep
        #sleep(60*60*24*365)
        # UPDATE: this is better?
        from signal import pause
        pause()


try:
    main()
finally:
    print('<0>Snitching interrupted, systemd should now force a reboot!', file=sys.stderr, flush=True)

# NOTE: if we exit() inside the "finally" block,
#       python exits *BEFORE THE BACKTRACE PRINTS*!
#       Therefore do it at the top level.
exit(1)