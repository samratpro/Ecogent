# Hosting the benchmark lab on a VPS

The public server (`bench/lab/public.py`) serves the four lab sites (shop, papers, jobs, crm).
Each visitor gets their own state and their own drift version.

## One-time setup (Ubuntu/Debian, as root)

```bash
apt update && apt install -y python3-venv nginx certbot python3-certbot-nginx git
useradd --system --home /opt/ecogent --shell /usr/sbin/nologin ecolab
git clone <your repo url> /opt/ecogent          # or copy just bench/ (it needs only bench/lab)
python3 -m venv /opt/ecogent/.venv
/opt/ecogent/.venv/bin/pip install beautifulsoup4
chown -R ecolab:ecolab /opt/ecogent

# Set your subdomain in both files (lab.example.com)
cp /opt/ecogent/bench/lab/deploy/ecogent-lab.service /etc/systemd/system/
cp /opt/ecogent/bench/lab/deploy/nginx-lab.conf /etc/nginx/sites-available/ecogent-lab
ln -s /etc/nginx/sites-available/ecogent-lab /etc/nginx/sites-enabled/
systemctl daemon-reload && systemctl enable --now ecogent-lab
nginx -t && systemctl reload nginx
certbot --nginx -d lab.example.com             # HTTPS
```

DNS: add an `A` record for `lab` pointing to the VPS IP.

## Using it

| URL | What it does |
|---|---|
| `/lab/` | Control page: pick the version, reset, see what was recorded, task prompts, score automation tasks |
| `/shop/?lab_level=2&lab_seed=1` | Set the version for this browser, then redirect to `/shop/` |
| switch bar (bottom of every page) | One click changes the page you are on to version 0-4 |
| `?lab_bar=0` / `?lab_bar=1` | Hide / show the bar (hide it when an agent is being tested) |

Versions: 0 original, 1 attributes (ids and classes renamed), 2 structure, 3 text, 4 redesign.
They are cumulative and reproducible from the seed, and the data is the same in all of them.

To freeze a version for an agent run, put it in the start URL. A fresh agent browser then starts on that version:
`https://lab.example.com/shop/?lab_level=3&lab_seed=1&lab_bar=0`

## Updating

```bash
cd /opt/ecogent && sudo -u ecolab git pull && systemctl restart ecogent-lab
```

Tag the commit you benchmark against (`git tag lab-v1`) so the paper can cite the exact site build.
