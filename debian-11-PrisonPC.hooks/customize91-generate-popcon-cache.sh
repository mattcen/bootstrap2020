#!/bin/sh -ev
PYTHONDONTWRITEBYTECODE=1 chroot "$1" bootstrap2020-popularity-contest --generate
