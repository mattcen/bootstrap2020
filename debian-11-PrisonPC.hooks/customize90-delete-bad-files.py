#!/usr/bin/python3
import argparse
import logging
import pathlib
import shutil
import subprocess
import sys

__doc__ = """ if we can't remove it, block it

We can't avoid shipping some binaries like gnupg(1), because
they're genuinely needed at boot time.

If they're ONLY needed at build time, delete them.
If they're needed at boot time, but ONLY by root, chmod them.

Why we don't |tar --delete
============================================================
The most logical way to do removals is outside of mmdebstrap:

    mmdebstrap … fs.sq          # BEFORE

    mmdebstrap … - |            # AFTER
    tar --delete --wildcards … |
    tar2sqfs fs.sq

But this runs into a few problems:

  • python3.9 pipeline process is a little fiddly if you want to make
    sure all processes exited nonzero.

  • systemd puts ACLs on /var/log/journal that tar2sqfs can't handle.
    Normally mmdebstrap auto-strips them, but when we tar2sqfs ourselves, I can't see how.
    Simply adding --xattrs-exclude=system.* to OUR tar didn't work.
    This didn't actually error, though, so we could just ignore this.

        $ <x.tar tar --xattrs --xattrs-exclude=system.*  --delete ./dev | tar2sqfs --quiet x.sq
        WARNING: squashfs does not support xattr prefix of system.posix_acl_default
        WARNING: squashfs does not support xattr prefix of system.posix_acl_access
        $ echo $?
        0

  • tar --delete --wildcards has no equivalent of shopt -s nullglob.
    We want to say "remove /bin/gpg (if not there, ignore)" not
    "remove /bin/gpg (if not there, half and catch fire)".

  • tar --delete -vvv still doesn't print "removing foo" or similar.
    Past experience has shown that when you have a large number of
    delete rules, you REALLY want an easy logged way to say "oh, shit,
    /bin/gpgame-rpg was wrongly deleted because it looked like GPG,
    but it's actually a game".


Why we don't bash extglob
============================================================
In the old codebase, we just did basically

    # chroot $1 bash -v < delete-bad-files.bash
    shopt -s globstar extglob nullglob
    shopt -u failglob
    rm -vrf *badthing*
    removing '/usr/bin/badthing'
    removing '/var/cache/badthing/'
    removing '/usr/lib/libbadthing.so.0'

This no longer works because mmdebstrap mounts /proc and /sys, and
bash and python globs lack "--one-file-system" or "-xdev".


Why we don't --dpkgopt=path-exclude=**bin/foo
============================================================
No one single reason, but:

  * cannot path-exclude files generated by postinst

  * cannot path-exclude files needed at build time (but not post-build).
    For example, initramfs config.

  * harder to debug, because dpkg does not log

     "skipped $path due to path-exclude $pattern"


"""


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('chroot_path', type=pathlib.Path)
parser.set_defaults(shitlist_path=(
    pathlib.Path(sys.argv[0]).parent /  # noqa: W504
    'customize90-delete-bad-files.glob'))
args = parser.parse_args()

if args.chroot_path.resolve() == '/':
    raise RuntimeError('Refusing to trash your rootfs!')

with args.shitlist_path.open() as f:
    shitlist = [
        line.strip()
        for line in f
        if line.strip()
        if not line.startswith('#')]

# Walk the filesystem exactly once, with -xdev.
# Then, use python globbing to decide what to remove.
find_stdout = subprocess.check_output(
    ['chroot', args.chroot_path,
     'find', '/', '-xdev', '-depth',
     '-print0'],
    text=True)
for path in find_stdout.strip('\0').split('\0'):
    path = pathlib.Path(path)
    matching_globs = [
        glob for glob in shitlist
        if path.match(glob)]
    if matching_globs:
        logging.info('Removing ‘%s’\t(matches %s)', path, matching_globs)
        # NOTE: "chroot_path / path" does the Wrong ThingTM as path is absolute.
        path_outside_chroot = args.chroot_path.joinpath(*path.parts[1:])
        if path_outside_chroot.is_dir():
            shutil.rmtree(path_outside_chroot)
        else:
            path_outside_chroot.unlink()
