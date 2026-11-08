"""
Ecogent drift benchmark lab: local sites with known ground truth, a deterministic site-drift
generator and task oracles, so every system is measured on the same pages and the same changes.

  sites.py   three sites (shop, papers, jobs) rendered from fixed data; jobs records form posts
  drift.py   drift levels 0-4 applied to every HTML response (seeded, reproducible)
  server.py  local HTTP server serving the sites at a chosen drift level
  tasks.py   benchmark tasks (prompt + type) and their oracles (success, precision, recall)
"""
