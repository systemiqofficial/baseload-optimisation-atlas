"""
Optional steps after the BOA run: products priced from the per-pixel LCOE.

The core model never imports this package. ``hydrogen`` holds the LCOH arithmetic and its
parameters (``electrolysis.csv``, every row with a source label from
``boa/config/sources.toml``, where the sources of this step have the tag ``hydrogen``);
``lcoh_file`` applies it to a run's per-year GLOBAL outputs.
"""
