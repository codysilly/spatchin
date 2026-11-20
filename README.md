# Spatchin

The public website at https://www.spatchin.com/ displays the holding page. The working, WIP v0.9 dashboard is at https://www.spatchin.com/dashboard/.

GitHub Pages serves the repository root. The dashboard HTML is in `dashboard/index.html` with `<base href="../">` to resolve all existing application scripts, styles, icon files and published `data/*.json` snapshots from the repository root. Do not move the data files or change scheduled update workflow paths to follow the page route. The public holding page has no dashboard scripts and does not make aviation-provider requests.
