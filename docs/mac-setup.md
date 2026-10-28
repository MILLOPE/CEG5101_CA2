# Ubuntu desktop on a Mac

Skip this if you already have an Ubuntu 20.04 desktop. These steps use
Multipass, which should be installed on the Mac first.

In the Mac terminal:

```bash
multipass launch 20.04 --name ca2-part1 --cpus 2 --memory 4G --disk 30G
multipass shell ca2-part1
```

Inside Ubuntu, install XFCE and the remote desktop service:

```bash
sudo apt-get update
sudo apt-get install -y xfce4 xfce4-terminal xrdp
printf 'startxfce4\n' > ~/.xsession
sudo passwd ubuntu
sudo adduser xrdp ssl-cert
sudo systemctl enable --now xrdp
sudo systemctl restart xrdp
```

Set a password for `ubuntu` when prompted. Then, in another Mac terminal:

```bash
multipass info ca2-part1
```

Copy the IPv4 address. In an RDP client such as Windows App, connect to that
address on port 3389. Select the Xorg session and sign in as `ubuntu` with the
password you just set.

Open a terminal in the Ubuntu desktop and follow the [README](../README.md).
