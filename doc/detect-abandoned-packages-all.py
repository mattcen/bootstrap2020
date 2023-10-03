#!/usr/bin/python3
import subprocess
import datetime
import urllib.request
import urllib.error
import collections

import lxml.html


# FIXME: this is listing virtual packages, e.g. arpd
# FIXME: sometimes has wrong source package, e.g. autoconf-doc
def get_packages():
    acc = collections.defaultdict(set)
    stdout = subprocess.check_output(
        ['dpkg-query', '--show',
         '--showformat=${source:Package}\t${binary:Package}\n',
         '*'],
        text=True)
    for line in sorted(stdout.splitlines()):
        source_package, binary_package = line.split()
        acc[source_package].add(binary_package)
    return {
        k: ' '.join(sorted(v))
        for k, v in acc.items()}


# I initially was going to do this via "apt changelog | dpkg-parsechangelog".
# But that was actually EVEN MORE annoying than this is.
# This is getting the more recent change to any release,
# i.e. if Debian stable is really old, but sid is fine, it'll say "fine".
def get_age(source_package):
    try:
        with urllib.request.urlopen(f'https://tracker.debian.org/pkg/{source_package}/news/') as f:
            ts = datetime.date.fromisoformat(
                lxml.html.fromstring(
                    f.read()).xpath(
                        '//span[@class="news-date"]/text()')[0])
        return f'{(datetime.date.today() - ts).days} days ago'
    except urllib.error.HTTPError:
        return '???? days ago [1]'
    except IndexError:
        return '???? days ago [2]'


# FIXME: Do a proper CSV.  Also, sort the output.
print('Staleness', 'Source', 'Binaries', sep='\t', flush=True)
for source_package, binary_packages in get_packages().items():
    print(get_age(source_package), source_package, binary_packages, sep='\t', flush=True)
