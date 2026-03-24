# Investigation: VM 104 RX580 GPU — renderD128 Missing
**Session:** S034 | **Date:** 2026-02-20

## Problem
VM 104 (Tdarr-Node) has an AMD RX580 GPU passed through via VFIO, but `/dev/dri/renderD128` does not exist. Only `/dev/dri/card0` (the QEMU bochs VGA) is present. GPU hardware transcoding is non-functional.

## Investigation

### Host-Side (pve03 — 10.25.255.28)
- **IOMMU Group 14:** Both GPU functions correctly isolated
  - `0000:06:00.0` — Ellesmere [Radeon RX 470/480/570/580] (VGA)
  - `0000:06:00.1` — Ellesmere HDMI Audio
- **VFIO-PCI:** Bound to both functions, resets completing normally
- **Proxmox VM config:** `hostpci0: 0000:06:00.0;0000:06:00.1,pcie=1`, machine=q35, bios=ovmf, cpu=host

### Guest-Side (VM 104 — 10.25.255.34)
- **lspci:** RX580 visible at `01:00.0`, but "Kernel driver in use" is BLANK (not bound)
- **Kernel module:** `amdgpu` is loaded (14MB, 0 references)
- **Firmware:** `firmware-amd-graphics` installed, polaris10 firmware files present
- **dmesg error:**
  ```
  amdgpu 0000:01:00.0: probe with driver amdgpu failed with error -22
  WARNING: at amdgpu_irq.c:631 amdgpu_irq_put
  amdgpu_device_fini_hw → amdgpu_driver_load_kms.cold
  ```

## Root Cause
The amdgpu kernel driver attempts to probe the GPU but fails during interrupt initialization (`amdgpu_irq_put`). Error -22 = EINVAL. This is a known class of issues with AMD Polaris (RX 5xx) GPU passthrough in KVM/QEMU:

1. **Polaris reset bug** — AMD Polaris GPUs don't properly reset when passed through via VFIO. The `vendor-reset` kernel module is the standard community fix.
2. **Interrupt routing** — The PCIe MSI/MSI-X interrupt configuration may not be properly forwarded from host to guest.

## Recommended Fix Path (For Sonny)

### Option A: Install vendor-reset module on pve03 (Recommended)
```bash
# On pve03:
apt install pve-headers-$(uname -r) dkms git
git clone https://github.com/gnif/vendor-reset.git /opt/vendor-reset
cd /opt/vendor-reset && dkms install .
echo "vendor-reset" >> /etc/modules
# Reboot pve03, then start VM 104
```

### Option B: Try adding rombar=0 to VM config
```bash
# On pve03:
qm set 104 --hostpci0 0000:06:00.0;0000:06:00.1,pcie=1,rombar=0
qm stop 104 && qm start 104
```

### Option C: Try x-vga=1 flag
```bash
qm set 104 --hostpci0 0000:06:00.0;0000:06:00.1,pcie=1,x-vga=1
```

### Verification After Fix
```bash
# In VM 104:
ls -la /dev/dri/          # Should show renderD128
vainfo                     # Should show AMD VAAPI support
sudo docker exec tdarr-node ls -la /dev/dri/  # Container sees GPU
```

## Status
**BLOCKED** — Requires Proxmox host-level changes (kernel module install or VM config change on pve03). Cannot be done from inside the VM.
