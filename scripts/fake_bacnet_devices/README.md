# Fake BACnet devices for Open FDD test bench

Fake AHU and VAV BACnet devices (BACpypes3) that expose scheduled faults so Open FDD can be validated end-to-end. Each device can run on a separate Raspberry Pi; Open FDD runs on its own server and scrapes + runs FDD rules.

## Quick start (manual, one Pi)

Copy the right pair of files to each device and run:

- **AHU Pi:** `fake_ahu_faults.py` + `fault_schedule.py`  
  `python fake_ahu_faults.py --name BensFakeAhu --instance 3456789`
- **VAV Pi:** `fake_vav_faults.py` + `fault_schedule.py`  
  `python fake_vav_faults.py --name Zone1VAV --instance 3456790`

Install deps first: `pip install bacpypes3 ifaddr` (or use a venv).


### Deploy + verify only (no apt upgrade)
```bash
ansible-playbook -i scripts/fake_bacnet_devices/inventory.yml scripts/fake_bacnet_devices/fix_dpkg.yml
```

---

## Ansible deploy (recommended)

The playbook copies the scripts to each Pi, ensures a virtualenv with `bacpypes3` and `ifaddr`, and runs the fake device under systemd so it survives reboot.

### 1. Install Ansible and sshpass (control machine)

On the machine where you run the playbook (e.g. hvac-edge-01), not on the Pis:

```bash
# Ubuntu/Debian
sudo apt update && sudo apt install -y ansible-core sshpass
```

`sshpass` is needed for password-based SSH (user ben / password ben in inventory). Then:

```bash
ansible-playbook --version
```

### 2. SSH access to the Raspberry Pis

Ensure you can SSH into both devices without a password prompt (use SSH keys).

The default inventory uses user **ben** and password **ben** on both Pis (test bench). For password-based SSH you need `sshpass` on the control machine:

```bash
sudo apt install sshpass   # Ubuntu/Debian
```

Then run the playbook; it will connect as `ben` with password `ben`.

The playbook can also **update the Pi OS** (apt update + safe upgrade) and **verify** the BACnet services are running. On **Armbian** (or if you see `raspi-firmware` / dpkg conflicts), skip the update: run with `--skip-tags update` so only deploy + verify run. If the update step fails on one Pi, the playbook now continues and still deploys both. To fix broken dpkg on **both** Pis in one go (uses same ben/ben from inventory):  
`ansible-playbook -i scripts/fake_bacnet_devices/inventory.yml scripts/fake_bacnet_devices/fix_dpkg.yml`

Optional: use SSH keys instead (no password, no sshpass). Create a key, copy it to the Pis, and in `inventory.yml` set `ansible_ssh_private_key_file: ~/.ssh/id_ed25519` and comment out or remove `ansible_password`.

### 3. Edit the inventory (optional)

From the **open-fdd** repo root or from this directory:

- **Inventory file:** `scripts/fake_bacnet_devices/inventory.yml`  
  - AHU: `192.168.204.13`  
  - VAV: `192.168.204.14`  
  - Default user: `pi`. Change `ansible_user` under `all.vars` if your Pi user is different.
  - To use a specific SSH key, uncomment and set:
    ```yaml
    ansible_ssh_private_key_file: ~/.ssh/id_rsa
    ```

### 4. Run the playbook

From the **open-fdd** repo root:

```bash
ansible-playbook -i scripts/fake_bacnet_devices/inventory.yml scripts/fake_bacnet_devices/playbook.yml
```

Or from this directory (`scripts/fake_bacnet_devices`):

```bash
ansible-playbook -i inventory.yml playbook.yml
```

To deploy only one device:

```bash
# AHU only (192.168.204.13)
ansible-playbook -i inventory.yml playbook.yml --limit ahu_fake

# VAV only (192.168.204.14)
ansible-playbook -i inventory.yml playbook.yml --limit vav_fake
```

The playbook will:

1. Create `/opt/openfdd-fake-bacnet` on each Pi (override with `deploy_path` in inventory if needed).
2. Copy `fault_schedule.py` and the correct script (`fake_ahu_faults.py` or `fake_vav_faults.py`) via SCP.
3. Create a Python 3 venv in that directory (if missing) and run `pip install bacpypes3 ifaddr`.
4. Install a systemd unit and start the service so the fake device runs with the right args and restarts on reboot.

### 5. Check that the services are running

On each Pi (or via Ansible):

```bash
# AHU
ssh pi@192.168.204.13 "sudo systemctl status openfdd-fake-ahu"

# VAV
ssh pi@192.168.204.14 "sudo systemctl status openfdd-fake-vav"
```

Logs:

```bash
ssh pi@192.168.204.13 "sudo journalctl -u openfdd-fake-ahu -f"
```

### 6. Re-run after code changes

Re-run the same playbook anytime you change the scripts. Ansible will copy updated files and restart the service.

---

## Troubleshooting

- **`No identities found` (when running ssh-copy-id)**  
  You don’t have an SSH key. Create one: `ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519 -N ""`, then `ssh-copy-id -i ~/.ssh/id_ed25519.pub pi@192.168.204.13` (and same for .14). Set `ansible_ssh_private_key_file: ~/.ssh/id_ed25519` in `inventory.yml`.

- **`Host key verification failed`**  
  First time connecting to the Pi, SSH asks to verify the host key. Either:
  - SSH once manually and type `yes`, or  
  - Run with `ANSIBLE_HOST_KEY_CHECKING=False` (or use the included `ansible.cfg` by running the playbook from this directory).

- **`Permission denied (password)`**  
  Ansible is trying to use password auth and failing. Use SSH keys so you can log in without a password:
  ```bash
  ssh-copy-id pi@192.168.204.13
  ssh-copy-id pi@192.168.204.14
  ```
  If your Pi user is not `pi`, set `ansible_user` in `inventory.yml`.

- **`Permission denied (publickey)`**  
  No SSH key is being accepted. Confirm you can log in with `ssh pi@192.168.204.13` (no password). If you use a specific key file, set in inventory:
  ```yaml
  ansible_ssh_private_key_file: ~/.ssh/id_rsa
  ```

- **Playbook runs but service fails on the Pi**  
  On the Pi, check: `sudo systemctl status openfdd-fake-ahu` (or `openfdd-fake-vav`) and `sudo journalctl -u openfdd-fake-ahu -n 50`. Ensure Python 3 and `python3-venv` are installed (`sudo apt install python3 python3-venv`).

---

## Fault schedule (UTC)

Both devices use the same time-based schedule (see `fault_schedule.py`), by **UTC** minute-of-hour:

| Minute (UTC) | Mode      | Open FDD rule expected   |
|--------------|-----------|----------------------------|
| 0–9          | normal    | —                          |
| 10–49        | flatline  | `flatline_flag`            |
| 50–54        | out-of-bounds | `bad_sensor_flag`   |
| 55–59        | normal    | —                          |

If the Pis are not on UTC, set `TZ=UTC` in the systemd unit or adjust the schedule in `fault_schedule.py` to use local time.

---

## Files in this directory

| File / dir        | Purpose |
|-------------------|--------|
| `fake_ahu_faults.py` | Fake AHU BACnet device (SA-T, RA-T, MA-T on schedule) |
| `fake_vav_faults.py` | Fake VAV BACnet device (ZoneTemp on schedule) |
| `fault_schedule.py`  | Shared schedule (UTC minutes); used by both scripts |
| `requirements.txt`    | `bacpypes3`, `ifaddr` (used by playbook pip install) |
| `inventory.yml`      | Ansible inventory (AHU 192.168.204.13, VAV 192.168.204.14) |
| `playbook.yml`       | Ansible playbook: copy, venv, systemd, start |
| `templates/fake_bacnet.service.j2` | Systemd unit template (stdout/stderr → null, no log files or journal persistence) |
| `README.md`           | This file |
