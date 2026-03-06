#!/bin/bash
# Setup USB auto-mount at /mnt/usb for Tradebot on Raspberry Pi
# Run on the Pi: bash setup_usb_mount.sh
# Requires: sudo

set -e

MOUNT_POINT="/mnt/usb"
FSTAB_BACKUP="/etc/fstab.bak.$(date +%Y%m%d_%H%M%S)"

echo "=== Tradebot USB Mount Setup ==="
echo "This script configures the USB stick to mount at $MOUNT_POINT"
echo "so that E:\\projects maps to $MOUNT_POINT/projects"
echo ""

# Create mount point
if [ ! -d "$MOUNT_POINT" ]; then
    echo "Creating $MOUNT_POINT..."
    sudo mkdir -p "$MOUNT_POINT"
    echo "Done."
else
    echo "$MOUNT_POINT already exists."
fi

# Show block devices to help user identify USB
echo ""
echo "=== Block devices (find your USB) ==="
lsblk -f
echo ""
echo "Run 'sudo blkid' to see UUIDs for each device."
echo ""

# Prompt for UUID
read -p "Enter your USB's UUID (or press Enter to skip fstab): " USB_UUID

if [ -n "$USB_UUID" ]; then
    FSTAB_LINE="UUID=$USB_UUID  $MOUNT_POINT  ext4  defaults,nofail,noauto  0  2"
    echo ""
    echo "The following line will be appended to /etc/fstab:"
    echo "  $FSTAB_LINE"
    echo ""
    echo "  nofail  = boot continues if USB is not plugged in"
    echo "  noauto  = not mounted at boot; you mount manually when needed"
    echo ""
    read -p "Proceed? (y/n): " CONFIRM
    if [ "$CONFIRM" = "y" ] || [ "$CONFIRM" = "Y" ]; then
        sudo cp /etc/fstab "$FSTAB_BACKUP"
        echo "Backed up fstab to $FSTAB_BACKUP"
        echo "$FSTAB_LINE" | sudo tee -a /etc/fstab
        echo "Added to fstab."
    else
        echo "Skipped fstab update."
    fi
fi

echo ""
echo "=== Manual mount ==="
echo "When the USB is plugged in, mount it with:"
echo "  sudo mount $MOUNT_POINT"
echo ""
echo "Verify:"
echo "  ls $MOUNT_POINT/projects/tradebot_stage_a"
echo ""
