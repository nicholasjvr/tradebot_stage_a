# USB Auto-Mount for Tradebot on Raspberry Pi

This guide helps you configure the USB stick so it mounts at `/mnt/usb` when plugged into the Pi. The project expects `E:\projects` (Windows) to map to `/mnt/usb/projects` on the Pi.

## Quick Setup (Interactive Script)

From the project root on the Pi:

```bash
cd /mnt/usb/projects/tradebot_stage_a   # or wherever the USB is currently mounted
bash scripts/setup_usb_mount.sh
```

The script will:

1. Create `/mnt/usb` if it does not exist
2. Show block devices so you can identify your USB
3. Prompt for the USB's UUID
4. Append an fstab entry (with `nofail,noauto` for safety)
5. Print the manual mount command

## Manual Setup

### 1. Create mount point

```bash
sudo mkdir -p /mnt/usb
```

### 2. Find your USB UUID

Plug in the USB, then:

```bash
lsblk -f
# or
sudo blkid
```

Look for your USB device (e.g. `/dev/sda1`) and note its `UUID`.

### 3. Add to fstab

```bash
sudo nano /etc/fstab
```

Add this line (replace `YOUR_UUID` with the actual UUID):

```
UUID=YOUR_UUID  /mnt/usb  ext4  defaults,nofail,noauto  0  2
```

- **nofail** – Boot continues if the USB is not plugged in
- **noauto** – Not mounted at boot; you mount manually when needed

### 4. Mount when needed

```bash
sudo mount /mnt/usb
```

To unmount before unplugging:

```bash
sudo umount /mnt/usb
```

## Alternative: Auto-mount on plug-in (udev)

If you want the USB to mount automatically when plugged in (without editing fstab each time), you can use a udev rule. This is more advanced.

1. Create a udev rule:

```bash
sudo nano /etc/udev/rules.d/99-usb-tradebot.rules
```

2. Add (adjust `ID_FS_UUID` if you need to match a specific USB):

```
ACTION=="add", SUBSYSTEM=="block", ENV{ID_FS_TYPE}=="ext4", RUN+="/bin/mkdir -p /mnt/usb", RUN+="/bin/mount -t ext4 /dev/%k /mnt/usb"
ACTION=="remove", SUBSYSTEM=="block", RUN+="/bin/umount /mnt/usb"
```

3. Reload udev:

```bash
sudo udevadm control --reload-rules
```

**Warning:** udev rules can be tricky. Test with the fstab approach first.

## Troubleshooting

### USB not mounting

- Check the filesystem: `lsblk -f` – ensure it is `ext4` (or adjust fstab/udev for `vfat`/`exfat`)
- Check UUID: `sudo blkid`
- Check logs: `dmesg | tail`

### Permission denied

Ensure the `pi` user can read the mounted files:

```bash
ls -la /mnt/usb/projects
```

If needed, adjust ownership after mount:

```bash
sudo chown -R pi:pi /mnt/usb/projects
```

### Service starts before USB is ready

If using systemd for the collector/trader, add to the service unit:

```ini
[Unit]
RequiresMountsFor=/mnt/usb
```

This makes the service wait for the mount before starting.
