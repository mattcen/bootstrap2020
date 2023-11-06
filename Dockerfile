FROM debian:11

WORKDIR /build

RUN printf '%s\n' \
  "apt-cacher-ng apt-cacher-ng/tunnelenable boolean false" \
  "locales locales/locales_to_be_generated multiselect en_AU.UTF-8 UTF-8" \
  "locales locales/default_environment_locale select en_AU.UTF-8" \
  | debconf-set-selections

RUN apt-get update && \
    apt-get install -y \
      mmdebstrap \
      python3-hyperlink \
      python3-pypass \
      python3-requests \
      python3-jsmin \
      # Should this be Suggested/Recommended by mmdebstrap?
      libdpkg-perl \
      samba \
      git \
      locales \
      auto-apt-proxy \
      squashfs-tools-ng \
      moreutils \
      apt-cacher-ng \
      pxelinux \
      wget2 \
      openssh-client \
      rsync \
    && \
    rm -rf /var/lib/apt/lists/*

ENV LANG=en_AU.UTF-8
VOLUME /var/cache/apt-cacher-ng
#VOLUME /tmp/bootstrap2020

# We can't easily run qemu inside the container, so instead, store the intended
# qemu command in a script alongside the image files
RUN cat >  /usr/local/bin/qemu-system-x86_64 <<"EOF"
#!/bin/bash
dir=$(echo "$@" | grep -m1 -o '/tmp/bootstrap2020/[[:alnum:]-]*' | head -1)
printf '%s\n' '#!/bin/bash' 'image_dir="${0%/*}"' > "$dir"/cmd
printf '%q \\\n' qemu-system-x86_64 "$@" |
    sed 's/--enable-kvm/--accel hvf/' |
    sed 's/\/tmp\/bootstrap2020\/[[:alnum:]-]*\/[[:alnum:]-]*/"$image_dir"/g' |
    sed '$s/ \\$//' >> "$dir"/cmd
    chmod +x "$dir"/cmd
    echo QEMU_CMD: "$dir"/cmd
EOF
RUN chmod +x /usr/local/bin/qemu-system-x86_64
# We don't have systemctl, but bootstrap tries to run it
RUN ln -s /bin/true /usr/local/bin/systemctl

#RUN adduser --disabled-password --gecos "" container
#RUN chown container:container .
#USER container

RUN git clone https://github.com/cyberitsolutions/bootstrap2020 .
COPY debian-11-main.py .


COPY docker-entrypoint.sh /
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["bash"]
