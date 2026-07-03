#!/bin/bash
# SERVER GATE Stress Test — bootable Live ISO builder.
#
# Remasters the official Debian Live (XFCE) image: installs Python + the app
# into the squashfs and adds an autostart entry, preserving the original
# BIOS+UEFI boot chain (Secure Boot friendly, Ventoy compatible).
#
# Requirements: Debian/Ubuntu host (WSL2 works), root, ~15 GB free disk,
#               internet connection.
# Usage:        sudo ./build_iso.sh
# Output:       ./build/servergate.iso

set -e
[ "$(id -u)" = 0 ] || { echo "Run as root: sudo ./build_iso.sh"; exit 1; }

HERE="$(cd "$(dirname "$0")" && pwd)"
PAYLOAD="$HERE/../app"
WORK="$HERE/build"
mkdir -p "$WORK"
cd "$WORK"

echo "[1/7] Installing build tools..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq xorriso squashfs-tools rsync wget curl ca-certificates

echo "[2/7] Downloading official Debian Live (XFCE)..."
BASE="https://cdimage.debian.org/debian-cd/current-live/amd64/iso-hybrid/"
NAME=$(curl -s "$BASE" | grep -oE 'debian-live-[0-9.]+-amd64-xfce\.iso' | head -1)
[ -n "$NAME" ] || { echo "ERROR: could not resolve Debian Live image name"; exit 1; }
if [ ! -f orig.iso ]; then
  wget -q --show-progress -O orig.iso.part "$BASE$NAME"
  mv orig.iso.part orig.iso
fi
EXPECT=$(curl -s "$BASE/SHA256SUMS" | grep " $NAME" | awk '{print $1}')
ACTUAL=$(sha256sum orig.iso | awk '{print $1}')
if [ -n "$EXPECT" ] && [ "$EXPECT" != "$ACTUAL" ]; then
  echo "ERROR: SHA256 mismatch for downloaded ISO"; exit 1
fi
echo "      $NAME — checksum OK"

echo "[3/7] Extracting squashfs..."
for m in rootfs/dev/pts rootfs/dev rootfs/proc rootfs/sys; do
  mountpoint -q "$m" 2>/dev/null && umount -lf "$m" || true
done
rm -rf rootfs filesystem.squashfs new.squashfs servergate.iso
xorriso -osirrox on -indev orig.iso \
        -extract /live/filesystem.squashfs "$WORK/filesystem.squashfs" 2>/dev/null
unsquashfs -f -d rootfs filesystem.squashfs >/dev/null

echo "[4/7] Installing app + dependencies into the image..."
cp -f /etc/resolv.conf rootfs/etc/resolv.conf
mount -t proc proc rootfs/proc
mount --bind /sys rootfs/sys
mount --bind /dev rootfs/dev
mount --bind /dev/pts rootfs/dev/pts
trap 'for m in rootfs/dev/pts rootfs/dev rootfs/proc rootfs/sys; do umount -lf "$m" 2>/dev/null || true; done' EXIT

CODENAME=$(. rootfs/etc/os-release; echo "$VERSION_CODENAME")
cat > rootfs/etc/apt/sources.list <<EOF
deb http://deb.debian.org/debian $CODENAME main contrib non-free-firmware
deb http://deb.debian.org/debian $CODENAME-updates main contrib non-free-firmware
deb http://deb.debian.org/debian-security $CODENAME-security main contrib non-free-firmware
EOF
chroot rootfs /bin/bash -c "export DEBIAN_FRONTEND=noninteractive; \
  apt-get update -qq && apt-get install -y --no-install-recommends \
  python3 python3-tk python3-numpy python3-psutil python3-pil python3-pip \
  fonts-dejavu-core fonts-dejavu x11-xserver-utils dmidecode pciutils" \
  2>&1 | tail -2
chroot rootfs /bin/bash -c \
  "pip3 install --break-system-packages --no-input customtkinter darkdetect" \
  2>&1 | tail -2

mkdir -p rootfs/opt/servergate
cp "$PAYLOAD"/*.py  rootfs/opt/servergate/
cp "$PAYLOAD"/*.png rootfs/opt/servergate/ 2>/dev/null || true
cp "$PAYLOAD"/*.ico rootfs/opt/servergate/ 2>/dev/null || true

cat > rootfs/opt/servergate/run.sh <<'RUN'
#!/bin/bash
export SERVERGATE_KIOSK=1
xset s off 2>/dev/null || true
xset -dpms 2>/dev/null || true
xset s noblank 2>/dev/null || true
cd /opt/servergate
exec python3 main.py
RUN
chmod +x rootfs/opt/servergate/run.sh

mkdir -p rootfs/etc/xdg/autostart rootfs/etc/skel/Desktop
cat > rootfs/etc/xdg/autostart/servergate.desktop <<'DESK'
[Desktop Entry]
Type=Application
Name=SERVER GATE Stress Test
Comment=CPU & Memory stress test
Exec=/opt/servergate/run.sh
Icon=/opt/servergate/logo_icon.png
Terminal=false
X-GNOME-Autostart-enabled=true
X-XFCE-Autostart-enabled=true
DESK
cp rootfs/etc/xdg/autostart/servergate.desktop rootfs/etc/skel/Desktop/
chmod +x rootfs/etc/skel/Desktop/servergate.desktop || true

echo "[5/7] Sanity check inside the image..."
chroot rootfs /bin/bash -c \
  "python3 -c 'import numpy,psutil,customtkinter,PIL,tkinter; print(\"  imports OK\")' && \
   python3 -m py_compile /opt/servergate/*.py && echo '  app compiles OK'"
chroot rootfs /bin/bash -c "apt-get clean" || true
rm -rf rootfs/var/lib/apt/lists/* rootfs/root/.cache rootfs/tmp/* 2>/dev/null || true

for m in rootfs/dev/pts rootfs/dev rootfs/proc rootfs/sys; do
  umount -lf "$m" 2>/dev/null || true
done
trap - EXIT

echo "[6/7] Rebuilding squashfs (slow, ~10 min)..."
mksquashfs rootfs new.squashfs -comp xz -b 1M -Xbcj x86 -noappend -no-progress >/dev/null

echo "[7/7] Repacking ISO (preserving BIOS+UEFI boot records)..."
xorriso -indev orig.iso -outdev servergate.iso \
        -boot_image any replay \
        -update new.squashfs /live/filesystem.squashfs \
        -commit 2>&1 | tail -2

sha256sum servergate.iso | tee servergate.iso.sha256
echo
echo "DONE → $WORK/servergate.iso"
echo "Copy it onto a Ventoy USB stick (or write raw with dd) and boot the server."
